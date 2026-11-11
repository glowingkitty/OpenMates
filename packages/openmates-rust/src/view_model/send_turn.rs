//! The open-window half of one send (lane L9): the optimistic user message,
//! the streamed reply applied in order, and the failed or cancelled end
//! state. Pure state over the actor's `OpenWindow`; the orchestration that
//! feeds it lives in `send_flows.rs`. Moved from the terminal UI's stream
//! handling (`Ui::stream`); spec `a2-design.md` (View model).
//!
//! Invariants: only the turn's own chat window changes (a new chat's window
//! opens at `Started`); the reply placeholder is replaced, never duplicated,
//! by the completed reply; a turn whose chat is not open changes no window.
use super::{
    ChatWindowRecord, ChatWindowSource, MessageRecord, MessageRole, MessageStatus, PiiRestoration,
    RequestId, SendState, ViewErrorKind, ViewEvent, window::OpenWindow,
};
use crate::model::StreamUpdate;

/// Id of the optimistic user message before the client assigned one.
fn provisional_user_id(request: RequestId) -> String {
    format!("pending-message:{}", request.0)
}

/// Id of the streamed reply before the server's completion names it.
fn provisional_reply_id(user_id: &str) -> String {
    format!("pending-reply:{user_id}")
}

fn empty_record(chat_id: &str) -> ChatWindowRecord {
    ChatWindowRecord {
        chat_id: chat_id.to_owned(),
        title: String::new(),
        category: String::new(),
        messages: Vec::new(),
        source: ChatWindowSource::Live,
        has_more_before: None,
        history_complete: false,
        refreshing: false,
        pii_restoration: PiiRestoration::PageLocal,
    }
}

/// The window state of one running send.
pub(super) struct SendTurn {
    request: RequestId,
    /// The turn's chat; `None` for a new chat until `Started` names it.
    chat_id: Option<String>,
    /// Whether the window follows this turn: a new chat, or the open chat.
    tracked: bool,
    /// Id of the user message (provisional until `Started`).
    user_id: String,
    /// The optimistic user message as text, for a new chat's first window.
    text: String,
    expects_reply: bool,
    submitted: bool,
}

impl SendTurn {
    /// A turn of `request` into `chat_id` (`None`: a new chat), given the id
    /// of the chat that is open now.
    pub(super) fn new(
        request: RequestId,
        chat_id: Option<String>,
        text: &str,
        open_chat_id: Option<&str>,
    ) -> Self {
        let tracked = chat_id.is_none() || chat_id.as_deref() == open_chat_id;
        Self {
            request,
            chat_id,
            tracked,
            user_id: provisional_user_id(request),
            text: text.to_owned(),
            expects_reply: true,
            submitted: false,
        }
    }

    /// The send request this turn answers.
    pub(super) fn request(&self) -> RequestId {
        self.request
    }

    /// Whether the window follows this turn.
    pub(super) fn tracked(&self) -> bool {
        self.tracked
    }

    /// The turn's chat id; empty for a new chat before `Started`.
    pub(super) fn chat_id(&self) -> &str {
        self.chat_id.as_deref().unwrap_or("")
    }

    fn user_message(&self) -> MessageRecord {
        MessageRecord {
            id: self.user_id.clone(),
            role: MessageRole::User,
            status: MessageStatus::Complete,
            content: self.text.clone(),
            sender: String::new(),
            thinking: String::new(),
            embeds: Vec::new(),
            send_state: Some(SendState::Sending),
        }
    }

    /// The turn's window record, re-keyed to this request; `None` when the
    /// window does not follow the turn or shows another chat.
    fn record<'w>(&self, window: &'w mut Option<OpenWindow>) -> Option<&'w mut ChatWindowRecord> {
        if !self.tracked {
            return None;
        }
        let chat_id = self.chat_id.as_deref()?;
        let open = window.as_mut().filter(|open| open.chat_id == chat_id)?;
        open.request = self.request;
        Some(open.record.get_or_insert_with(|| empty_record(chat_id)))
    }

    fn event(&self, record: &mut ChatWindowRecord) -> ViewEvent {
        record.source = ChatWindowSource::Live;
        ViewEvent::ChatWindow {
            request: self.request,
            window: record.clone(),
        }
    }

    fn user<'r>(&self, record: &'r mut ChatWindowRecord) -> Option<&'r mut MessageRecord> {
        record
            .messages
            .iter_mut()
            .find(|message| message.id == self.user_id && message.role == MessageRole::User)
    }

    /// Show the optimistic user message in the open chat's window before
    /// any network request. A new chat has no window until `Started`.
    pub(super) fn begin(&mut self, window: &mut Option<OpenWindow>) -> Option<ViewEvent> {
        let message = self.user_message();
        let record = self.record(window)?;
        record.messages.push(message);
        Some(self.event(record))
    }

    /// Record a delivery fact (`Started`, `Submitted`, `Admitted`) of a
    /// cancelled turn without publishing; reply text is ignored.
    pub(super) fn apply_fence(&mut self, update: &StreamUpdate, window: &mut Option<OpenWindow>) {
        if matches!(
            update,
            StreamUpdate::Started { .. }
                | StreamUpdate::Submitted { .. }
                | StreamUpdate::Admitted { .. }
        ) {
            // The changed window is published once, by the cancelled end state.
            drop(self.apply(update, window));
        }
    }

    /// Apply one stream update; returns the changed window, if any. The
    /// stream event itself is the caller's to emit (also for untracked turns).
    pub(super) fn apply(
        &mut self,
        update: &StreamUpdate,
        window: &mut Option<OpenWindow>,
    ) -> Option<ViewEvent> {
        match update {
            StreamUpdate::Started {
                chat_id,
                message_id,
                expects_reply,
            } => self.started(chat_id, message_id, *expects_reply, window),
            StreamUpdate::Submitted { message_id, .. } => {
                if *message_id != self.user_id {
                    return None;
                }
                self.submitted = true;
                self.set_user_state(SendState::Submitted, window)
            }
            StreamUpdate::Admitted { message_id, .. } => {
                if *message_id != self.user_id {
                    return None;
                }
                self.set_user_state(SendState::Delivered, window)
            }
            StreamUpdate::Content {
                content,
                thinking,
                mate,
            } => self.content(content, thinking, mate, window),
            StreamUpdate::Completed {
                message_id,
                content,
                ..
            } => self.completed(message_id, content, window),
            StreamUpdate::Consent { .. } | StreamUpdate::Status(_) => None,
        }
    }

    fn started(
        &mut self,
        chat_id: &str,
        message_id: &str,
        expects_reply: bool,
        window: &mut Option<OpenWindow>,
    ) -> Option<ViewEvent> {
        self.expects_reply = expects_reply;
        let previous = std::mem::replace(&mut self.user_id, message_id.to_owned());
        if self.chat_id.is_none() {
            // A new chat: the server-assigned chat becomes the open window.
            self.chat_id = Some(chat_id.to_owned());
            *window = Some(OpenWindow {
                request: self.request,
                chat_id: chat_id.to_owned(),
                record: Some(empty_record(chat_id)),
                older: None,
            });
            let message = self.user_message();
            let record = self.record(window)?;
            record.messages.push(message);
            return Some(self.event(record));
        }
        let user_id = self.user_id.clone();
        let record = self.record(window)?;
        let message = record
            .messages
            .iter_mut()
            .find(|message| message.id == previous)?;
        message.id = user_id;
        Some(self.event(record))
    }

    fn set_user_state(
        &mut self,
        state: SendState,
        window: &mut Option<OpenWindow>,
    ) -> Option<ViewEvent> {
        let record = self.record(window)?;
        self.user(record)?.send_state = Some(state);
        Some(self.event(record))
    }

    fn content(
        &mut self,
        content: &str,
        thinking: &str,
        mate: &str,
        window: &mut Option<OpenWindow>,
    ) -> Option<ViewEvent> {
        if !self.expects_reply {
            return None;
        }
        let id = provisional_reply_id(&self.user_id);
        let record = self.record(window)?;
        let index = match record
            .messages
            .iter()
            .position(|message| message.id == id && message.role == MessageRole::Assistant)
        {
            Some(index) => index,
            None => {
                record.messages.push(MessageRecord {
                    id,
                    role: MessageRole::Assistant,
                    status: MessageStatus::Streaming,
                    content: String::new(),
                    sender: String::new(),
                    thinking: String::new(),
                    embeds: Vec::new(),
                    send_state: None,
                });
                record.messages.len() - 1
            }
        };
        let reply = &mut record.messages[index];
        // Each update carries the reply text so far, not a suffix.
        reply.content = content.to_owned();
        reply.thinking = thinking.to_owned();
        if !mate.is_empty() {
            reply.sender = mate.to_owned();
        }
        Some(self.event(record))
    }

    fn completed(
        &mut self,
        message_id: &str,
        content: &str,
        window: &mut Option<OpenWindow>,
    ) -> Option<ViewEvent> {
        let placeholder = provisional_reply_id(&self.user_id);
        let user_id = self.user_id.clone();
        let expects_reply = self.expects_reply;
        let record = self.record(window)?;
        if message_id == user_id {
            if !content.is_empty() {
                return None;
            }
            // Delivery without a reply: drop an empty placeholder.
            record.messages.retain(|message| {
                message.id != placeholder
                    || !message.content.is_empty()
                    || !message.thinking.is_empty()
            });
        } else {
            if !expects_reply {
                return None;
            }
            let position = record
                .messages
                .iter()
                .position(|message| {
                    message.role == MessageRole::Assistant && message.id == message_id
                })
                .or_else(|| {
                    record.messages.iter().position(|message| {
                        message.role == MessageRole::Assistant && message.id == placeholder
                    })
                });
            match position {
                Some(index) => {
                    let reply = &mut record.messages[index];
                    reply.id = message_id.to_owned();
                    reply.content = content.to_owned();
                    reply.status = MessageStatus::Complete;
                }
                None => record.messages.push(MessageRecord {
                    id: message_id.to_owned(),
                    role: MessageRole::Assistant,
                    status: MessageStatus::Complete,
                    content: content.to_owned(),
                    sender: String::new(),
                    thinking: String::new(),
                    embeds: Vec::new(),
                    send_state: None,
                }),
            }
        }
        Some(self.event(record))
    }

    /// End a failed send: the user message stays with `Failed`, a partial
    /// reply stops streaming.
    pub(super) fn fail(
        &mut self,
        error: ViewErrorKind,
        window: &mut Option<OpenWindow>,
    ) -> Option<ViewEvent> {
        let state = SendState::Failed {
            error,
            submitted: self.submitted,
        };
        self.end(state, window)
    }

    /// End a cancelled send: the user message shows `Cancelled`, a partial
    /// reply stops streaming and receives no further text.
    pub(super) fn cancel(&mut self, window: &mut Option<OpenWindow>) -> Option<ViewEvent> {
        let state = SendState::Cancelled {
            submitted: self.submitted,
        };
        self.end(state, window)
    }

    fn end(&mut self, state: SendState, window: &mut Option<OpenWindow>) -> Option<ViewEvent> {
        let placeholder = provisional_reply_id(&self.user_id);
        let record = self.record(window)?;
        self.user(record)?.send_state = Some(state);
        for reply in record
            .messages
            .iter_mut()
            .filter(|message| message.id == placeholder)
        {
            reply.status = MessageStatus::Complete;
        }
        Some(self.event(record))
    }
}
