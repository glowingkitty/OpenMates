//! The terminal UI as host of the core view-model actor (lanes L6b, L7): the
//! event sink that turns core `ViewEvent`s into terminal `View` replies, the
//! record-to-model mapping the terminal renders, and the `ViewHost` hooks the
//! terminal still implements (profile origin, trusted account, admission with
//! the live monitor, completion recovery). Send runs in the core (lane L9);
//! the terminal paints its turn from the core's `Stream` events.
//! Spec: `a2-design.md` (View model).
use super::{Actor, Reply, Stamp, View};
use openmates::{
    client::FreshChatInventory,
    completion_recovery_adapter,
    error::{Error, Result},
    model::{Chat, Item, Message, StreamUpdate, Workspace},
    runtime_store::RuntimeStoreGeneration,
    storage::{CacheBytes, Session},
};
use openmates_sdk::view_model::{
    ChatListRow, ChatRowStatus, ChatWindowRecord, EmbedRef, ListRecovery, MessageRecord, MessageRole,
    SessionEvent, StreamEvent, ViewCore, ViewEvent, ViewHost, ViewSink,
};
use openmates_sdk::client::ChatOwnerLease;
use futures_util::future::BoxFuture;
use std::sync::{Arc, Mutex, PoisonError};
use tokio::sync::mpsc;
use tokio_util::sync::CancellationToken;

/// Core events for one terminal request, stamped with its epochs so the UI
/// drops replies of a superseded request exactly like its own replies.
/// Chat plaintext (windows, live lists) also carries the store generation
/// and request lifetime: a logout or cancel while the reply waits in the
/// bounded channel still keeps it off the screen. Windows and live lists
/// also carry an owner lease (owner key, expiry, chat denials).
pub(super) struct TerminalSink {
    replies: mpsc::Sender<Reply>,
    epoch: Stamp,
    generation: RuntimeStoreGeneration,
    request: CancellationToken,
    /// Chat lists of this sink are live updates (selection kept by id).
    live: bool,
    /// Owner fence for queued chat plaintext; windows need one.
    owner: Option<Arc<ChatOwnerLease>>,
    /// A send's sink: its turn is painted from `Stream` events and the final
    /// `Sent` reply, so the core's send windows and list are not painted, and
    /// updates of a dropped send are delivered through `emit_detached`.
    send: Option<RelaySlot>,
}

/// The task that delivers the stream updates of a dropped send; the actor
/// awaits it before it reports the send's failure, so the `Submitted` fence
/// always precedes a restored draft.
pub(super) type RelaySlot = Arc<Mutex<Option<tokio::task::JoinHandle<()>>>>;

impl TerminalSink {
    pub(super) fn new(replies: &mpsc::Sender<Reply>, epoch: Stamp, generation: RuntimeStoreGeneration,
        request: &CancellationToken) -> Self {
        Self { replies: replies.clone(), epoch, generation, request: request.clone(), live: false, owner: None, send: None }
    }
    pub(super) fn live(mut self) -> Self { self.live = true; self }
    /// The sink of one send; `relay` receives the delivery task of a dropped send.
    pub(super) fn sending(mut self, relay: &RelaySlot) -> Self { self.send = Some(relay.clone()); self }
    /// Fence this sink's chat data by the current owner (and `chat_id`). No
    /// lease (no authenticated owner yet) leaves windows unpaintable.
    pub(super) fn owned_by(mut self, core: &ViewCore<CacheBytes>, chat_id: Option<&str>) -> Self {
        self.owner = core.client().chat_owner_lease(core.chat_monitor(), chat_id).ok().map(Arc::new);
        self
    }
    fn fence<T>(&self, value: T) -> Fenced<T> {
        Fenced { value, generation: self.generation.clone(), request: self.request.clone(), owner: self.owner.clone() }
    }
    /// The terminal view for a core event; `None` for an event without a
    /// terminal paint (a restored session without a cached display name).
    fn view_for_event(&self, event: ViewEvent) -> Result<Option<View>> {
        Ok(match event {
            ViewEvent::Session(SessionEvent::SignedOut) => Some(View::SignedOut),
            ViewEvent::Session(SessionEvent::Restored { display_name }) => display_name.map(View::Greeting),
            // The terminal paints a send's turn from its stream updates.
            ViewEvent::ChatList { .. } | ViewEvent::ChatWindow { .. } if self.send.is_some() => None,
            ViewEvent::Stream { event, .. } => Some(View::Stream(update_from_stream(event)?)),
            // Reply text reaches the terminal through the `Stream` content update.
            ViewEvent::MessageUpdated { .. } => None,
            ViewEvent::ChatList { rows, .. } => {
                let items = rows.iter().map(item_from_row).collect();
                Some(if self.live { View::LiveItems(self.fence(items)) } else { View::Items(Workspace::Chats, items) })
            }
            ViewEvent::ChatWindow { window, .. } => {
                // Fail closed: a window without an owner lease is never queued.
                if self.owner.is_none() { return Err(Error::Cancelled); }
                Some(View::Window(self.fence(window)))
            }
            ViewEvent::ChatUnavailable { chat_id } => Some(View::ChatUnavailable(chat_id)),
            ViewEvent::Done => Some(View::Done),
            _ => return Err(Error::Invalid("This view event is not routed by the terminal.")),
        })
    }
}

impl ViewSink for TerminalSink {
    fn emit(&self, event: ViewEvent) -> BoxFuture<'_, Result<()>> {
        Box::pin(async move {
            let Some(view) = self.view_for_event(event)? else { return Ok(()) };
            self.replies.send(Reply { epoch: self.epoch, view }).await.map_err(|_| Error::Cancelled)
        })
    }
    fn emit_detached(&self, events: Vec<ViewEvent>) {
        let Some(slot) = &self.send else { return };
        let views: Vec<View> = events.into_iter().filter_map(|event| self.view_for_event(event).ok().flatten()).collect();
        let (replies, epoch) = (self.replies.clone(), self.epoch);
        let task = tokio::spawn(async move {
            for view in views { if replies.send(Reply { epoch, view }).await.is_err() { break; } }
        });
        // A poisoned lock only means a panic elsewhere; the slot stays valid.
        *slot.lock().unwrap_or_else(PoisonError::into_inner) = Some(task);
    }
}

/// The terminal's stream update for a core stream event (the UI's turn,
/// delivery fence and consent form read `StreamUpdate`).
fn update_from_stream(event: StreamEvent) -> Result<StreamUpdate> {
    Ok(match event {
        StreamEvent::Consent { request_id, items } => StreamUpdate::Consent {
            request_id, items: items.iter().map(item_from_embed).collect::<Result<_>>()? },
        StreamEvent::Started { chat_id, message_id, expects_reply } => StreamUpdate::Started { chat_id, message_id, expects_reply },
        StreamEvent::Submitted { chat_id, message_id } => StreamUpdate::Submitted { chat_id, message_id },
        StreamEvent::Admitted { chat_id, message_id } => StreamUpdate::Admitted { chat_id, message_id },
        StreamEvent::Content { content, thinking, mate } => StreamUpdate::Content { content, thinking, mate },
        StreamEvent::Completed { chat_id, message_id, content } => StreamUpdate::Completed { chat_id, message_id, content },
        StreamEvent::Status { message } => StreamUpdate::Status(message),
    })
}

/// Chat plaintext queued for the UI; usable only while the store generation,
/// the request lifetime and the owner lease (owner, expiry, denials) it was
/// produced under are current.
pub(super) struct Fenced<T> {
    pub(super) value: T,
    generation: RuntimeStoreGeneration,
    request: CancellationToken,
    owner: Option<Arc<ChatOwnerLease>>,
}

impl<T> Fenced<T> {
    pub(super) fn into_inner(self) -> Result<T> {
        if !self.generation.is_current() || self.request.is_cancelled()
            || self.owner.as_ref().is_some_and(|owner| !owner.is_valid()) { return Err(Error::Cancelled); }
        Ok(self.value)
    }
}

/// The terminal's chat model for a core window record (the transcript view
/// renders `Chat`). Embed metadata comes back from `data_json`.
pub(super) fn chat_from_window(window: &ChatWindowRecord) -> Result<Chat> {
    Ok(Chat { id: window.chat_id.clone(), title: window.title.clone(), category: window.category.clone(),
        messages: window.messages.iter().map(message_from_record).collect::<Result<_>>()? })
}

fn message_from_record(message: &MessageRecord) -> Result<Message> {
    let role = match message.role { MessageRole::User => "user", MessageRole::Assistant => "assistant", MessageRole::System => "system" };
    Ok(Message { id: message.id.clone(), role: role.into(), content: message.content.clone(),
        sender: message.sender.clone(), thinking: message.thinking.clone(),
        embeds: message.embeds.iter().map(item_from_embed).collect::<Result<_>>()? })
}

fn item_from_embed(embed: &EmbedRef) -> Result<Item> {
    let fields = serde_json::from_str(&embed.data_json).map_err(|_| Error::Protocol)?;
    Ok(Item { id: embed.id.clone(), title: embed.title.clone(), description: embed.description.clone(),
        status: embed.status.clone(), category: embed.kind.clone(), fields })
}

/// The terminal's chat list item for a typed row. The terminal list renders
/// `Item`s; every field it reads (title, summary, category, status, unread
/// count, pin/archive flags, footer, exact title) is carried by the row.
pub(super) fn item_from_row(row: &ChatListRow) -> Item {
    let status = match row.status {
        ChatRowStatus::Ready => "",
        ChatRowStatus::Draft => "draft",
        ChatRowStatus::Locked => "locked",
    };
    let mut fields = serde_json::json!({
        "chat_list_title": row.chat_list_title,
        "unread_count": row.unread_count,
    });
    let object = fields.as_object_mut().expect("a json! object literal is an object");
    for (key, value) in [("created_at", row.created_at.map(serde_json::Value::from)),
        ("updated_at", row.updated_at.map(serde_json::Value::from)),
        ("messages_v", row.messages_v.map(serde_json::Value::from)),
        ("footer", row.footer.clone().map(serde_json::Value::from))] {
        if let Some(value) = value { object.insert(key.into(), value); }
    }
    for (key, set) in [("pinned", row.pinned), ("archived", row.archived), ("has_draft", row.has_draft)] {
        if set { object.insert(key.into(), true.into()); }
    }
    Item { id: row.id.clone(), title: row.title.clone(), description: row.summary.clone(),
        status: status.into(), category: row.category.clone(), fields }
}

impl ViewHost<CacheBytes> for Actor {
    type Sink = TerminalSink;
    fn core(&self) -> &ViewCore<CacheBytes> { &self.core }
    fn core_mut(&mut self) -> &mut ViewCore<CacheBytes> { &mut self.core }
    fn prepare_start(&mut self, credentials: &Session) -> Result<String> {
        let api = self.explicit_api.as_deref().unwrap_or(&credentials.api_url).to_owned();
        let app = openmates::profile::application_origin(
            &api,
            self.explicit_app.clone(),
            self.installed_app.as_ref().map(|(api, _)| api.as_str()),
            self.installed_app.as_ref().map(|(_, app)| app.clone()),
        )?;
        self.core.client_mut().set_app_origin(app)?;
        Ok(api)
    }
    fn verify_start(&mut self) -> BoxFuture<'_, Result<()>> {
        Box::pin(async move {
            self.trusted_verified = false;
            self.verify_trusted(false).await
        })
    }
    fn admit<'a>(&'a mut self, sink: &'a TerminalSink) -> BoxFuture<'a, Result<()>> {
        Box::pin(self.authorized_admission(&sink.replies, sink.epoch))
    }
    fn recover_before_list<'a>(&'a mut self, sink: &'a TerminalSink, recovery: ListRecovery)
        -> BoxFuture<'a, Result<Option<FreshChatInventory>>> {
        Box::pin(async move {
            match recovery {
                ListRecovery::BootSync => self.recover_before_view_with_inventory(&sink.replies, sink.epoch, None, false, true)
                    .await.map(|outcome| outcome.fresh_inventory),
                ListRecovery::Refresh => {
                    let selected = self.core.open_chat_id().map(str::to_owned);
                    self.recover_before_view(&sink.replies, sink.epoch, selected, true).await.map(|_| None)
                }
            }
        })
    }
    fn recovery_idle(&mut self) -> BoxFuture<'_, bool> {
        Box::pin(async move {
            completion_recovery_adapter::load_pending(self.core.client(), &self.store)
                .await.is_ok_and(|pending| pending.is_empty())
        })
    }
    fn recover_before_open<'a>(&'a mut self, sink: &'a TerminalSink, chat_id: &'a str) -> BoxFuture<'a, Result<()>> {
        Box::pin(async move {
            self.recover_before_view(&sink.replies, sink.epoch, Some(chat_id.to_owned()), true).await.map(|_| ())
        })
    }
    fn offline_cache_allowed(&self) -> bool { !self.cached_views_blocked }
}

#[cfg(test)]
impl TerminalSink {
    /// The fenced window this sink would queue for `record` (runtime tests).
    pub(super) fn window_for(&self, record: ChatWindowRecord) -> Fenced<ChatWindowRecord> {
        assert!(self.owner.is_some(), "windows need an owner lease");
        self.fence(record)
    }
}

/// A queued window reply for runtime tests (fresh generation and lifetime).
#[cfg(test)]
pub(super) fn test_window(chat: &Chat, source: openmates_sdk::view_model::ChatWindowSource) -> View {
    let record = openmates_sdk::view_model::chat_window_from_chat(chat, source, None, false, false,
        openmates_sdk::view_model::PiiRestoration::PageLocal).expect("synthetic chats convert");
    View::Window(Fenced { value: record, generation: openmates_sdk::local_cache::OrderedBlocking::new().guard(),
        request: CancellationToken::new(), owner: None })
}
