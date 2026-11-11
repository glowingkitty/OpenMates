//! The terminal UI as host of the core view-model actor (lane L6b): the event
//! sink that turns core `ViewEvent`s into terminal `View` replies, and the
//! `ViewHost` hooks the terminal still implements (profile origin, trusted
//! account, admission with the live monitor, completion recovery, and the
//! bridged chat open, mark-read and send paths). Spec: `a2-design.md` (View model).
use super::{Actor, Reply, Stamp, View};
use openmates::{
    client::FreshChatInventory,
    completion_recovery_adapter,
    error::{Error, Result},
    model::{Item, Workspace},
    storage::{CacheBytes, Session},
};
use openmates_sdk::view_model::{
    ChatListRow, ChatRowStatus, ListRecovery, SessionEvent, ViewCommand, ViewCore, ViewEvent,
    ViewHost, ViewSink,
};
use futures_util::future::BoxFuture;
use tokio::sync::mpsc;
use tokio_util::sync::CancellationToken;

/// Core events for one terminal request, stamped with its epochs so the UI
/// drops replies of a superseded request exactly like its own replies.
pub(super) struct TerminalSink {
    pub(super) replies: mpsc::Sender<Reply>,
    pub(super) epoch: Stamp,
}

impl ViewSink for TerminalSink {
    fn emit(&self, event: ViewEvent) -> BoxFuture<'_, Result<()>> {
        Box::pin(async move {
            let Some(view) = view_for_event(event)? else { return Ok(()) };
            self.replies.send(Reply { epoch: self.epoch, view }).await.map_err(|_| Error::Cancelled)
        })
    }
}

/// The terminal view for a core event; `None` for an event without a
/// terminal paint (a restored session without a cached display name).
fn view_for_event(event: ViewEvent) -> Result<Option<View>> {
    Ok(match event {
        ViewEvent::Session(SessionEvent::SignedOut) => Some(View::SignedOut),
        ViewEvent::Session(SessionEvent::Restored { display_name }) => display_name.map(View::Greeting),
        ViewEvent::ChatList { rows, .. } => Some(View::Items(Workspace::Chats, rows.iter().map(item_from_row).collect())),
        ViewEvent::Done => Some(View::Done),
        _ => return Err(Error::Invalid("This view event is not routed by the terminal.")),
    })
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
                    let selected = self.live_selected.clone();
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
    fn bridge<'a>(&'a mut self, command: ViewCommand, sink: &'a TerminalSink, cancel: &'a CancellationToken)
        -> BoxFuture<'a, Result<()>> {
        match command {
            ViewCommand::OpenChat { chat_id, .. } => Box::pin(self.open_chat(chat_id, &sink.replies, sink.epoch, cancel)),
            ViewCommand::MarkRead { chat_id } => Box::pin(self.mark_read(chat_id, cancel)),
            ViewCommand::Send { chat_id, text, .. } => Box::pin(self.send_message(chat_id, text, &sink.replies, sink.epoch, cancel)),
            _ => Box::pin(async { Err(Error::Invalid("This action is handled by the terminal.")) }),
        }
    }
}
