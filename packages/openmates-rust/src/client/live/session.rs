//! `LiveSession`: the sans-I/O state machine that keeps open live items in sync over the
//! core's WebSocket. The host (native client, wasm binding, test) feeds it frames, user
//! operations, connection changes, keys and clock ticks, and performs the returned
//! [`Action`]s. It never touches a socket, cache or clock itself, so every transition is
//! unit-testable; keys stay inside the session and the engine.

use super::engine::{LiveItem, LocalOp, SealedUpdate};
use super::ops_json::{add_suggestions, view_json};
use super::packet::{PacketType, seal_packet};
use super::session_types::{
    Action, CheckpointPolicy, CheckpointRequest, CheckpointResult, Event, IdleCheckpointPolicy,
    Status,
};
use super::{LiveError, LiveItemKind, SheetOp};
use base64::{Engine as _, engine::general_purpose::STANDARD};
use serde_json::{Value, json};
use std::collections::{BTreeSet, HashMap, HashSet};
use yrs::StateVector;
use yrs::updates::encoder::Encode;
use zeroize::Zeroizing;

/// Updates since the last snapshot that trigger a new one.
pub const SNAPSHOT_UPDATE_THRESHOLD: usize = 500;
/// Bytes since the last snapshot that trigger a new one.
pub const SNAPSHOT_BYTES_THRESHOLD: usize = 64 * 1024;
/// Presence expires this long after the last heartbeat.
pub const PRESENCE_TTL_MS: u64 = 30_000;
/// Conflicts one checkpoint retries on before it is reported as failed.
const CHECKPOINT_RETRIES: u8 = 3;

pub(super) struct Slot {
    pub(super) kind: LiveItemKind,
    pub(super) key: Option<Zeroizing<[u8; 32]>>,
    pub(super) epoch: u32,
    pub(super) previous_keys: Vec<(u32, crate::crypto::Key)>,
    pub(super) item: Option<LiveItem>,
    /// `Some(true)` edit, `Some(false)` view, `None` before the server state arrived.
    pub(super) can_edit: Option<bool>,
    /// The server state of this connection arrived.
    pub(super) subscribed: bool,
    pub(super) stored_outbox: Vec<SealedUpdate>,
    pub(super) persist_due: bool,
    pub(super) sent: HashSet<String>,
    pub(super) updates_since_snapshot: usize,
    pub(super) bytes_since_snapshot: usize,
    pub(super) verify_snapshot: Option<(u64, u32)>,
    pub(super) presence: HashMap<String, (Value, u64)>,
    pub(super) dirty_since: Option<u64>,
    pub(super) last_edit: u64,
    pub(super) checkpoint_inflight: bool,
    pub(super) checkpoint_retries: u8,
    pub(super) base_version: Option<i64>,
    pub(super) latest_assistant: Option<String>,
    pub(super) contributors: BTreeSet<String>,
    pub(super) status: Option<Status>,
    /// Sheet suggestion cards of assistant changes (`rowId:colId` to assistant value); local
    /// state, not part of the shared doc.
    pub(super) suggestions: HashMap<String, String>,
    /// The server refused an update for its rate limit: unacknowledged updates are sent
    /// again on the next tick (they stay in the outbox, so nothing is lost meanwhile).
    pub(super) resend_due: bool,
    /// This person's latest stamped presence, kept to resend it after a rate-limit refusal
    /// so peers never keep a stale cursor.
    pub(super) last_presence: Option<String>,
    /// The server refused a presence for its rate limit.
    pub(super) presence_refused: bool,
}

/// The live items one shell connection has open.
pub struct LiveSession {
    pub(super) slots: HashMap<String, Slot>,
    pub(super) connected: bool,
    pub(super) user_id: Option<String>,
    pub(super) assistant: super::assistant_session::AssistantSession,
    /// Items the core opened itself for an assistant change (no editor holds them).
    headless: HashSet<String>,
    policy: Box<dyn CheckpointPolicy>,
}

impl Default for LiveSession {
    fn default() -> Self {
        Self::new(Box::new(IdleCheckpointPolicy))
    }
}

pub(super) fn b64(bytes: &[u8]) -> String {
    STANDARD.encode(bytes)
}

fn missing(item_id: &str) -> LiveError {
    LiveError::InvalidUpdate(format!("item not open: {item_id}"))
}

impl LiveSession {
    /// A session with the given checkpoint policy.
    pub fn new(policy: Box<dyn CheckpointPolicy>) -> Self {
        Self {
            slots: HashMap::new(),
            connected: false,
            user_id: None,
            assistant: Default::default(),
            headless: HashSet::new(),
            policy,
        }
    }

    /// The signed-in user id, recorded as contributor of versions.
    pub fn set_user(&mut self, user_id: &str) {
        self.user_id = Some(user_id.to_string());
    }

    /// Marks an open item as opened by the core for an assistant change; it is closed by
    /// [`Self::take_settled_headless`] once nothing is left to send. An editor opening it
    /// later takes it over (the mark is dropped in [`Self::open`]).
    pub fn mark_headless(&mut self, item_id: &str) {
        self.headless.insert(item_id.to_owned());
    }

    /// Core-opened items whose local changes are all acknowledged (empty outbox, subscribed):
    /// removes their marks and returns the ids for the caller to close.
    pub fn take_settled_headless(&mut self) -> Vec<String> {
        let settled: Vec<String> = self
            .headless
            .iter()
            .filter(|id| match self.slots.get(*id) {
                None => true,
                Some(slot) => {
                    slot.subscribed
                        && slot.stored_outbox.is_empty()
                        && slot.item.as_ref().is_some_and(|i| i.outbox().is_empty())
                }
            })
            .cloned()
            .collect();
        for id in &settled {
            self.headless.remove(id);
        }
        settled
    }

    /// Number of open items.
    pub fn len(&self) -> usize {
        self.slots.len()
    }

    /// No item is open.
    pub fn is_empty(&self) -> bool {
        self.slots.is_empty()
    }

    /// Starts opening an item: the host answers [`Action::NeedKey`] with [`Self::provide_key`].
    pub fn open(&mut self, item_id: &str, kind: LiveItemKind) -> Vec<Action> {
        self.headless.remove(item_id);
        self.slots.insert(
            item_id.to_string(),
            Slot {
                kind,
                key: None,
                epoch: 0,
                previous_keys: Vec::new(),
                item: None,
                can_edit: None,
                subscribed: false,
                stored_outbox: Vec::new(),
                persist_due: false,
                sent: HashSet::new(),
                updates_since_snapshot: 0,
                bytes_since_snapshot: 0,
                verify_snapshot: None,
                presence: HashMap::new(),
                dirty_since: None,
                last_edit: 0,
                checkpoint_inflight: false,
                checkpoint_retries: 0,
                base_version: None,
                latest_assistant: None,
                contributors: BTreeSet::new(),
                status: None,
                suggestions: HashMap::new(),
                resend_due: false,
                last_presence: None,
                presence_refused: false,
            },
        );
        vec![Action::NeedKey {
            item_id: item_id.to_string(),
            stale: false,
        }]
    }

    /// Supplies the embed key and epoch (and the outbox persisted in the cache). For an
    /// open item this is the answer to `key_epoch_stale`: the outbox is re-sealed and resent.
    ///
    /// # Errors
    /// Item not open, or re-sealing errors.
    pub fn provide_keys(
        &mut self,
        item_id: &str,
        keys: super::driver::LiveKeys,
        stored_outbox: Vec<SealedUpdate>,
    ) -> Result<Vec<Action>, LiveError> {
        let connected = self.connected;
        let slot = self
            .slots
            .get_mut(item_id)
            .ok_or_else(|| missing(item_id))?;
        let changed_epoch = slot.epoch != keys.epoch;
        if let Some(item) = slot.item.as_mut() {
            item.rekey(&keys.current, keys.epoch)?;
            item.add_previous_keys(&keys.previous);
        }
        slot.key = Some(keys.current);
        slot.epoch = keys.epoch;
        slot.previous_keys = keys.previous;
        let mut out = Vec::new();
        if let Some(item) = slot.item.as_ref() {
            if changed_epoch {
                let since = item.head_seq();
                slot.subscribed = false;
                slot.sent.clear();
                slot.updates_since_snapshot = SNAPSHOT_UPDATE_THRESHOLD;
                out.push(persist(item_id, slot));
                if connected {
                    out.push(subscribe(item_id, slot, Some(since)));
                }
            }
        } else {
            slot.stored_outbox = stored_outbox;
            if connected {
                out.push(subscribe(item_id, slot, None));
            }
        }
        Ok(out)
    }

    /// Records the server version the embed is at, the base of the next checkpoint.
    pub fn set_base_version(&mut self, item_id: &str, version: Option<i64>) {
        if let Some(slot) = self.slots.get_mut(item_id) {
            slot.base_version = version;
        }
    }

    /// Connection state change. Reconnect resubscribes every item; the outbox is resent
    /// once the server state arrived.
    pub fn set_connected(&mut self, connected: bool) -> Vec<Action> {
        self.connected = connected;
        let mut out = Vec::new();
        for (id, slot) in &mut self.slots {
            slot.sent.clear();
            slot.subscribed = false;
            if connected && slot.key.is_some() {
                let since = slot.item.as_ref().map(LiveItem::head_seq);
                out.push(subscribe(id, slot, since));
            } else if !connected
                && slot
                    .item
                    .as_ref()
                    .is_some_and(|item| !item.outbox().is_empty())
            {
                // An online edit can still be pending when connectivity drops.
                out.push(persist(id, slot));
            }
            status_event(id, slot, connected, &mut out);
        }
        out
    }

    /// Supplies the embed's current text form for an empty log; creates the item.
    ///
    /// # Errors
    /// Item not open or no key yet, or text the kind rejects.
    pub fn provide_content(
        &mut self,
        item_id: &str,
        text: &str,
        now_ms: u64,
    ) -> Result<Vec<Action>, LiveError> {
        let connected = self.connected;
        let slot = self
            .slots
            .get_mut(item_id)
            .ok_or_else(|| missing(item_id))?;
        let key = slot.key.as_ref().ok_or_else(|| missing(item_id))?;
        let mut item = LiveItem::create(slot.kind, item_id, key, slot.epoch, text)?;
        item.add_previous_keys(&slot.previous_keys);
        slot.item = Some(item);
        let mut out = vec![persist(item_id, slot)];
        emit_full(item_id, slot, &mut out);
        touch(slot, now_ms, &self.user_id);
        flush(item_id, slot, connected, &mut out);
        status_event(item_id, slot, connected, &mut out);
        Ok(out)
    }

    /// Update bytes from the JS mirror (documents and code).
    ///
    /// # Errors
    /// Item not open or not ready, wrong kind, invalid update.
    pub fn apply_mirror_update(
        &mut self,
        item_id: &str,
        bytes: &[u8],
        now_ms: u64,
    ) -> Result<Vec<Action>, LiveError> {
        let connected = self.connected;
        self.guard_edit(item_id)?;
        let slot = self
            .slots
            .get_mut(item_id)
            .ok_or_else(|| missing(item_id))?;
        let item = slot.item.as_mut().ok_or(LiveError::Empty)?;
        let update = item.apply_mirror_update(bytes)?;
        slot.latest_assistant = None;
        let mut out = Vec::new();
        sealed_local(
            item_id,
            slot,
            &update,
            now_ms,
            &self.user_id,
            connected,
            &mut out,
        );
        Ok(out)
    }

    /// A typed operation (sheets, decks, code line replacement).
    ///
    /// # Errors
    /// Item not open or not ready, or the engine's operation errors.
    pub fn apply_local_op(
        &mut self,
        item_id: &str,
        op: LocalOp,
        now_ms: u64,
    ) -> Result<Vec<Action>, LiveError> {
        let connected = self.connected;
        self.guard_edit(item_id)?;
        let slot = self
            .slots
            .get_mut(item_id)
            .ok_or_else(|| missing(item_id))?;
        let item = slot.item.as_mut().ok_or(LiveError::Empty)?;
        if let LocalOp::Sheet(SheetOp::SetCell { row_id, col_id, .. }) = &op {
            slot.suggestions.remove(&format!("{row_id}:{col_id}"));
        }
        let before = item.state_vector();
        let change = item.apply_local_op(op)?;
        let mut out = Vec::new();
        if let Some(update) = change.update {
            slot.latest_assistant = None;
            sealed_local(
                item_id,
                slot,
                &update,
                now_ms,
                &self.user_id,
                connected,
                &mut out,
            );
            emit_change(item_id, slot, &before, &mut out);
        }
        Ok(out)
    }

    fn guard_edit(&self, item_id: &str) -> Result<(), LiveError> {
        let slot = self.slots.get(item_id).ok_or_else(|| missing(item_id))?;
        if slot.item.is_none() {
            return Err(LiveError::Empty);
        }
        if slot.can_edit == Some(false) {
            return Err(LiveError::InvalidUpdate("read_only".to_string()));
        }
        Ok(())
    }

    /// Seals and sends the local presence JSON (relay only, never stored).
    ///
    /// # Errors
    /// Item not open or no key, sealing errors.
    pub fn set_presence(
        &mut self,
        item_id: &str,
        presence_json: &str,
    ) -> Result<Vec<Action>, LiveError> {
        let connected = self.connected;
        let user_id = self.user_id.clone();
        let slot = self
            .slots
            .get_mut(item_id)
            .ok_or_else(|| missing(item_id))?;
        if slot.key.is_none() {
            return Err(missing(item_id));
        }
        if !connected || slot.can_edit.is_none() {
            return Ok(Vec::new());
        }
        let stamped = stamp_presence(presence_json, user_id.as_deref())?;
        slot.presence_refused = false;
        let send = presence_send(item_id, slot, &stamped)?;
        slot.last_presence = Some(stamped);
        Ok(vec![send])
    }

    /// Leaving the editor ends this person's editing session: when the item has edits not yet
    /// in a stored version, its version is written now instead of after the idle time, so the
    /// read view and the version timeline show the text just typed. Call before [`Self::close`];
    /// the slot stays open until the write (and a conflict retry) has finished.
    pub fn checkpoint_before_close(&mut self, item_id: &str) -> Vec<Action> {
        let Some(slot) = self.slots.get_mut(item_id) else {
            return Vec::new();
        };
        if slot.dirty_since.is_none() || slot.checkpoint_inflight || slot.can_edit != Some(true) {
            return Vec::new();
        }
        match checkpoint_request(item_id, slot) {
            Some(request) => {
                slot.checkpoint_inflight = true;
                vec![Action::WriteCheckpoint(request)]
            }
            None => Vec::new(),
        }
    }

    /// Release a replica and its headless subscription state without sending.
    pub(super) fn forget(&mut self, item_id: &str) -> bool {
        self.headless.remove(item_id);
        self.slots.remove(item_id).is_some()
    }

    /// Closes an item (unsubscribes).
    pub fn close(&mut self, item_id: &str) -> Vec<Action> {
        match self.forget(item_id) {
            true if self.connected => vec![Action::Send {
                message_type: "live_item_unsubscribe",
                payload: json!({"item_id": item_id}),
            }],
            _ => Vec::new(),
        }
    }

    /// Recovery is needed only while the replica cannot publish its local edits.
    pub(super) fn offline_replica(&self, item_id: &str) -> Option<&LiveItem> {
        if self.connected {
            return None;
        }
        self.slots
            .get(item_id)?
            .item
            .as_ref()
            .filter(|item| !item.outbox().is_empty())
    }

    /// A failed write keeps the outbox live and resends only after the next durable save.
    pub(super) fn outbox_write_result(&mut self, item_id: &str, saved: bool) {
        if let Some(slot) = self.slots.get_mut(item_id) {
            slot.persist_due = !saved;
            if !saved {
                slot.sent.clear();
                slot.status = None;
            }
        }
    }

    /// Clock tick: expires presence, resends what the server refused for its rate limit and
    /// starts due checkpoints.
    pub fn tick(&mut self, now_ms: u64) -> Vec<Action> {
        let mut out = self.assistant_tick(now_ms);
        let connected = self.connected;
        for (id, slot) in &mut self.slots {
            if slot.persist_due {
                out.push(persist(id, slot));
                status_event(id, slot, connected, &mut out);
            }
            if slot.persist_due || (slot.resend_due && connected) {
                slot.resend_due = false;
                flush(id, slot, connected, &mut out);
            }
            if slot.presence_refused && connected {
                slot.presence_refused = false;
                if let Some(stamped) = slot.last_presence.clone()
                    && let Ok(send) = presence_send(id, slot, &stamped)
                {
                    out.push(send);
                }
            }
            let before = slot.presence.len();
            slot.presence
                .retain(|_, (_, seen)| now_ms.saturating_sub(*seen) < PRESENCE_TTL_MS);
            if slot.presence.len() != before {
                out.push(presence_event(id, slot));
            }
            let outbox_empty = slot.item.as_ref().is_some_and(|i| i.outbox().is_empty());
            if let (Some(since), false, true) =
                (slot.dirty_since, slot.checkpoint_inflight, outbox_empty)
                && self.policy.due(now_ms, since, slot.last_edit)
                && let Some(request) = checkpoint_request(id, slot)
            {
                slot.checkpoint_inflight = true;
                out.push(Action::WriteCheckpoint(request));
            }
        }
        out
    }

    /// Outcome of a [`Action::WriteCheckpoint`]. A 409 retries on the server's version.
    pub fn checkpoint_result(
        &mut self,
        item_id: &str,
        result: CheckpointResult,
        now_ms: u64,
    ) -> Vec<Action> {
        let Some(slot) = self.slots.get_mut(item_id) else {
            return Vec::new();
        };
        match result {
            CheckpointResult::Written(version) => {
                slot.base_version = Some(version);
                slot.checkpoint_inflight = false;
                slot.checkpoint_retries = 0;
                slot.dirty_since = None;
                slot.contributors.clear();
                Vec::new()
            }
            CheckpointResult::Conflict(current) if slot.checkpoint_retries < CHECKPOINT_RETRIES => {
                slot.checkpoint_retries += 1;
                slot.base_version = Some(current);
                match checkpoint_request(item_id, slot) {
                    Some(request) => vec![Action::WriteCheckpoint(request)],
                    None => Vec::new(),
                }
            }
            CheckpointResult::Conflict(_) | CheckpointResult::Failed => {
                slot.checkpoint_inflight = false;
                slot.checkpoint_retries = 0;
                slot.last_edit = now_ms;
                Vec::new()
            }
        }
    }
}

impl LiveSession {
    /// The materialized text form of an open item (document HTML, sheet or code text), as
    /// written into a stored version; `None` when the item is not open or has no content yet.
    /// Lets shells without a Yjs mirror render the current content.
    pub fn text_of(&self, item_id: &str) -> Option<String> {
        self.slots.get(item_id)?.item.as_ref()?.text_form().ok()
    }
}

fn checkpoint_request(item_id: &str, slot: &Slot) -> Option<CheckpointRequest> {
    let text = slot.item.as_ref()?.text_form().ok()?;
    Some(CheckpointRequest {
        item_id: item_id.to_string(),
        text,
        base_version: slot.base_version,
        version_kind: "session",
        restored_from: None,
        contributors: slot.contributors.iter().cloned().collect(),
    })
}

pub(super) fn touch(slot: &mut Slot, now_ms: u64, user: &Option<String>) {
    slot.dirty_since.get_or_insert(now_ms);
    slot.last_edit = now_ms;
    if let Some(user) = user {
        slot.contributors.insert(user.clone());
    }
}

/// Bookkeeping after a local change was sealed.
pub(super) fn sealed_local(
    item_id: &str,
    slot: &mut Slot,
    update: &SealedUpdate,
    now_ms: u64,
    user: &Option<String>,
    connected: bool,
    out: &mut Vec<Action>,
) {
    slot.updates_since_snapshot += 1;
    slot.bytes_since_snapshot += update.sealed.len();
    touch(slot, now_ms, user);
    out.push(persist(item_id, slot));
    flush(item_id, slot, connected, out);
    status_event(item_id, slot, connected, out);
}

pub(super) fn persist(item_id: &str, slot: &Slot) -> Action {
    Action::PersistOutbox {
        item_id: item_id.to_string(),
        entries: slot
            .item
            .as_ref()
            .map(|i| i.outbox().to_vec())
            .unwrap_or_default(),
    }
}

pub(super) fn subscribe(item_id: &str, slot: &Slot, since: Option<u64>) -> Action {
    let mut payload = json!({"item_id": item_id, "kind": slot.kind.as_str()});
    if let Some(since) = since {
        payload["since_seq"] = json!(since);
    }
    Action::Send {
        message_type: "live_item_subscribe",
        payload,
    }
}

/// The sealed presence frame of this person (the caller stamped who it is).
fn presence_send(item_id: &str, slot: &Slot, stamped: &str) -> Result<Action, LiveError> {
    let key = slot.key.as_ref().ok_or_else(|| missing(item_id))?;
    let sealed = seal_packet(
        key,
        item_id,
        slot.kind,
        slot.epoch,
        PacketType::Presence,
        stamped.as_bytes(),
    )?;
    Ok(Action::Send {
        message_type: "live_item_presence",
        payload: json!({"item_id": item_id, "epoch": slot.epoch, "payload": b64(&sealed)}),
    })
}

/// Sends every outbox entry not yet sent on this connection (editors only, after state).
pub(super) fn flush(item_id: &str, slot: &mut Slot, connected: bool, out: &mut Vec<Action>) {
    if !connected || !slot.subscribed || slot.can_edit != Some(true) {
        return;
    }
    let Some(item) = slot.item.as_ref() else {
        return;
    };
    for entry in item.outbox() {
        if slot.sent.insert(entry.client_msg_id.clone()) {
            out.push(Action::Send {
                message_type: "live_item_update",
                payload: json!({"item_id": item_id, "client_msg_id": entry.client_msg_id,
                    "epoch": entry.epoch, "payload": b64(&entry.sealed)}),
            });
        }
    }
}

/// Emits the status when it changed.
pub(super) fn status_event(item_id: &str, slot: &mut Slot, connected: bool, out: &mut Vec<Action>) {
    let pending = slot.item.as_ref().is_none_or(|i| !i.outbox().is_empty());
    let status = if slot.can_edit == Some(false) && connected {
        Status::ReadOnly
    } else if !connected {
        Status::Offline
    } else if pending || !slot.subscribed {
        Status::Saving
    } else {
        Status::Saved
    };
    if slot.status != Some(status) {
        slot.status = Some(status);
        out.push(Action::Emit(Event::Status {
            item_id: item_id.to_string(),
            status,
        }));
    }
}

/// The full state for a shell that holds nothing yet.
pub(super) fn emit_full(item_id: &str, slot: &Slot, out: &mut Vec<Action>) {
    emit_change(item_id, slot, &StateVector::default().encode_v1(), out);
}

/// Tells the shell what changed since `before` (the state vector prior to the change):
/// the view model for sheets and decks, plain Yjs bytes for documents and code.
pub(super) fn emit_change(item_id: &str, slot: &Slot, before: &[u8], out: &mut Vec<Action>) {
    let Some(item) = slot.item.as_ref() else {
        return;
    };
    match view_json(item) {
        Ok(Some(mut view)) => {
            if slot.kind == LiveItemKind::Deck {
                view["can_undo"] =
                    json!(slot.can_edit == Some(true) && slot.latest_assistant.is_some());
            }
            add_suggestions(&mut view, &slot.suggestions);
            out.push(Action::Emit(Event::View {
                item_id: item_id.to_string(),
                view,
            }));
        }
        Ok(None) => {
            if let Ok(bytes) = item.encode_update_since(before) {
                out.push(Action::Emit(Event::RemoteUpdate {
                    item_id: item_id.to_string(),
                    bytes,
                }));
            }
        }
        Err(_) => {}
    }
}

pub(super) fn presence_event(item_id: &str, slot: &Slot) -> Action {
    let peers: Vec<Value> = slot.presence.values().map(|(v, _)| v.clone()).collect();
    Action::Emit(Event::Presence {
        item_id: item_id.to_string(),
        peers: Value::Array(peers),
    })
}

/// Peer colours; a person keeps one colour per account (picked from the hashed id).
const PEER_COLOURS: [&str; 8] = [
    "#E5484D", "#30A46C", "#0090FF", "#F76B15", "#8E4EC6", "#12A594", "#D6409F", "#AD7F58",
];

/// Adds who is present to the shell's presence object: `user_id` (the SHA-256 of the
/// signed-in user id, so the sealed packet never carries the raw id) and a stable
/// `color`. The shell supplies only its cursor and `display_name`; receivers key peers
/// by `user_id`, so the identity comes from the core, not from the page.
///
/// # Errors
/// [`LiveError`] when the presence is not a JSON object.
fn stamp_presence(presence_json: &str, user_id: Option<&str>) -> Result<String, LiveError> {
    let mut value: Value = serde_json::from_str(presence_json)
        .map_err(|e| LiveError::InvalidUpdate(format!("presence: {e}")))?;
    let object = value
        .as_object_mut()
        .ok_or_else(|| LiveError::InvalidUpdate("presence is not an object".to_string()))?;
    if let Some(user) = user_id {
        let hashed = crate::client::sha256(user);
        let colour = PEER_COLOURS[usize::from(hashed.as_bytes()[0]) % PEER_COLOURS.len()];
        object.insert("user_id".into(), Value::String(hashed));
        object
            .entry("color")
            .or_insert_with(|| Value::String(colour.into()));
    }
    object
        .entry("display_name")
        .or_insert_with(|| Value::String(String::new()));
    Ok(value.to_string())
}
