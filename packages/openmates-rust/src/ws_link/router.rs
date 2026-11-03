//! Inbound message routing of the shared link: one socket carries every
//! handler family. Handlers themselves stay platform functions; the router
//! owns their registration order, de-duplication, serialization lane and the
//! early-message buffer for frames that arrive before a handler registers.
use super::FrameKind;
use super::envelope::auth_error_message;
use std::collections::HashMap;

/// Adapter-assigned identity of one handler function.
pub type HandlerId = u32;

/// Phased-sync frames run strictly after the previous one finished.
const SERIALIZED: [&str; 5] = [
    "phase_1_last_chat_ready",
    "phase_1b_chat_content_ready",
    "phase_2_last_20_chats_ready",
    "phase_3_last_100_chats_ready",
    "phased_sync_complete",
];
/// Always buffered until a handler registers (TypeScript replay set).
const REPLAYABLE: [&str; 2] = ["recovery_jobs_available", "recovery_outputs_available"];
/// Acknowledgements that need no handler.
const ALLOWED_WITHOUT_HANDLER: [&str; 4] = [
    "active_chat_set_ack",
    "pong",
    "draft_update_receipt",
    "draft_delete_receipt",
];
/// Buffered frames kept per type (newest win).
pub const EARLY_BUFFER_CAP: u32 = 20;

/// Handler families that share the one socket with chat sync.
#[derive(Clone, Copy, Debug, PartialEq, Eq, Hash)]
pub enum Family {
    AppSettings,
    Webhooks,
    ConnectedAccounts,
    Highlights,
}
impl Family {
    pub const ALL: [Family; 4] = [Self::AppSettings, Self::Webhooks, Self::ConnectedAccounts, Self::Highlights];

    /// Message types of the family, as registered by `chatSyncService.ts`.
    pub fn types(self) -> &'static [&'static str] {
        match self {
            Self::AppSettings => &[
                "request_app_settings_memories",
                "dismiss_app_settings_memories_dialog",
                "app_settings_memories_sync_ready",
                "app_settings_memories_entry_synced",
                "app_settings_memories_entry_stored",
                "system_message_confirmed",
                "new_system_message",
                "reminder_fired",
                "user_notification",
            ],
            Self::Webhooks => &["webhook_chat", "webhook_chat_approved", "webhook_chat_rejected"],
            Self::ConnectedAccounts => &["request_connected_account_permission", "connected_account_action_receipt"],
            Self::Highlights => &["message_highlight_added", "message_highlight_updated", "message_highlight_removed"],
        }
    }

    pub fn of(message_type: &str) -> Option<Family> {
        Self::ALL.into_iter().find(|family| family.types().contains(&message_type))
    }

    pub fn code(self) -> u32 {
        match self {
            Self::AppSettings => 0,
            Self::Webhooks => 1,
            Self::ConnectedAccounts => 2,
            Self::Highlights => 3,
        }
    }

    pub fn from_code(code: u32) -> Option<Family> {
        Self::ALL.into_iter().find(|family| family.code() == code)
    }
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Lane {
    Concurrent,
    Serialized,
}

/// What the adapter does with one inbound frame.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Route<'r> {
    /// Call `handlers` in order, each awaited before the next.
    Dispatch { lane: Lane, handlers: &'r [HandlerId] },
    /// Keep the payload for replay; drop the oldest kept one first if asked.
    Buffer { evict_oldest: bool },
    /// Known acknowledgement without handler.
    Ignore,
    /// No handler; the adapter logs it.
    Unhandled,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Registered {
    /// Added; replay the `replay` buffered payloads of this type to it.
    Added { replay: u32 },
    Duplicate,
}

/// `Route` without the handler slice, for adapters that mirror handler order.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum RouteAction {
    Dispatch(Lane),
    Buffer { evict_oldest: bool },
    Ignore,
    Unhandled,
}

impl Route<'_> {
    pub fn action(&self) -> RouteAction {
        match *self {
            Route::Dispatch { lane, .. } => RouteAction::Dispatch(lane),
            Route::Buffer { evict_oldest } => RouteAction::Buffer { evict_oldest },
            Route::Ignore => RouteAction::Ignore,
            Route::Unhandled => RouteAction::Unhandled,
        }
    }
}

/// Server message types are a small closed set; the cap bounds a hostile server.
pub const INTERN_CAP: usize = 1024;

#[derive(Default)]
pub struct Router {
    handlers: HashMap<Box<str>, Vec<HandlerId>>,
    buffered: HashMap<Box<str>, u32>,
    declared: [bool; 4],
    types: Vec<Box<str>>,
    type_ids: HashMap<Box<str>, u32>,
    /// Per interned id: its dispatch lane once routed to handlers. A pure
    /// function of the registrations, so every registration change clears it.
    dispatch: Vec<Option<Lane>>,
}

impl Router {
    pub fn new() -> Self {
        Self::default()
    }

    /// Declare a family whose handlers register asynchronously (dynamic
    /// import). Its frames are buffered until a handler registers instead of
    /// being dropped as in the TypeScript race.
    pub fn declare(&mut self, family: Family) {
        self.declared[family.code() as usize] = true;
    }

    /// Stable small id for a message type; `None` once `INTERN_CAP` types exist.
    pub fn intern(&mut self, message_type: &str) -> Option<u32> {
        if let Some(id) = self.type_ids.get(message_type) {
            return Some(*id);
        }
        if self.types.len() >= INTERN_CAP {
            return None;
        }
        let id = self.types.len() as u32;
        self.types.push(message_type.into());
        self.type_ids.insert(message_type.into(), id);
        self.dispatch.push(None);
        Some(id)
    }

    pub fn type_name(&self, id: u32) -> Option<&str> {
        self.types.get(id as usize).map(|name| &**name)
    }

    /// `route` by interned id; dispatch decisions are memoized until the next
    /// registration change. `None` for an id `intern` never issued.
    pub fn route_id(&mut self, id: u32) -> Option<RouteAction> {
        let index = id as usize;
        if let Some(lane) = *self.dispatch.get(index)? {
            return Some(RouteAction::Dispatch(lane));
        }
        let name = std::mem::take(&mut self.types[index]);
        let action = self.route(&name).action();
        self.types[index] = name;
        if let RouteAction::Dispatch(lane) = action {
            self.dispatch[index] = Some(lane);
        }
        Some(action)
    }

    fn invalidate(&mut self) {
        self.dispatch.fill(None);
    }

    pub fn on(&mut self, message_type: &str, handler: HandlerId) -> Registered {
        self.invalidate();
        let handlers = self.handlers.entry(message_type.into()).or_default();
        if handlers.contains(&handler) {
            return Registered::Duplicate;
        }
        handlers.push(handler);
        // Only the first handler takes the buffer, like the TypeScript replay.
        let replay = self.buffered.remove(message_type).unwrap_or(0);
        Registered::Added { replay }
    }

    pub fn off(&mut self, message_type: &str, handler: HandlerId) -> bool {
        self.invalidate();
        let Some(handlers) = self.handlers.get_mut(message_type) else { return false };
        let Some(index) = handlers.iter().position(|id| *id == handler) else { return false };
        handlers.remove(index);
        if handlers.is_empty() {
            self.handlers.remove(message_type);
        }
        true
    }

    pub fn clear(&mut self, message_type: &str) -> bool {
        self.invalidate();
        self.handlers.remove(message_type).is_some()
    }

    /// Remove every handler; returns how many were registered.
    pub fn clear_all(&mut self) -> u32 {
        self.invalidate();
        let count = self.handlers.values().map(|handlers| handlers.len() as u32).sum();
        self.handlers.clear();
        count
    }

    pub fn handler_count(&self, message_type: &str) -> usize {
        self.handlers.get(message_type).map_or(0, Vec::len)
    }

    /// Registered handlers of one type, in dispatch order.
    pub fn handlers(&self, message_type: &str) -> &[HandlerId] {
        self.handlers.get(message_type).map_or(&[], Vec::as_slice)
    }

    /// Route one frame type. Buffering is recorded here; the adapter keeps the
    /// payloads in the same order.
    pub fn route(&mut self, message_type: &str) -> Route<'_> {
        if let Some(handlers) = self.handlers.get(message_type).filter(|handlers| !handlers.is_empty()) {
            let lane = if SERIALIZED.contains(&message_type) { Lane::Serialized } else { Lane::Concurrent };
            return Route::Dispatch { lane, handlers };
        }
        let buffer = REPLAYABLE.contains(&message_type)
            || Family::of(message_type).is_some_and(|family| self.declared[family.code() as usize]);
        if buffer {
            let count = self.buffered.entry(message_type.into()).or_insert(0);
            let evict_oldest = *count >= EARLY_BUFFER_CAP;
            if !evict_oldest {
                *count += 1;
            }
            return Route::Buffer { evict_oldest };
        }
        if ALLOWED_WITHOUT_HANDLER.contains(&message_type) {
            Route::Ignore
        } else {
            Route::Unhandled
        }
    }

    /// Link-level meaning of a frame. `error_message` is the `message` of an
    /// `error` payload (or the payload itself when it is a string).
    pub fn classify<'a>(message_type: &str, error_message: Option<&'a str>) -> FrameKind<'a> {
        match message_type {
            "pong" => FrameKind::Pong,
            "server_restarting" => FrameKind::ServerRestarting,
            "error" => match error_message.filter(|message| auth_error_message(message)) {
                Some(message) => FrameKind::AuthError(message),
                None => FrameKind::Data,
            },
            _ => FrameKind::Data,
        }
    }
}
