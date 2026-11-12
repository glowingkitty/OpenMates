//! Chat and message actions on `ViewModelCore`: delete a chat or a message,
//! edit a user message, retry the last turn, fork, save and clear drafts and
//! stop a running reply, exported to Swift over the core view-model flows
//! (`openmates_sdk::view_model::{delete_chat, delete_message, edit_message,
//! retry_turn, fork_chat, save_draft, clear_draft, stop_reply}`). Bindings
//! only marshal. Plan `apple-client-core-migration` A5; spec `client-core`.
use crate::core::CoreCancellation;
use crate::view_core::ViewModelCore;
use crate::view_send::SendSettings;
use crate::{CoreError, view_records::ChatWindowViewRecord};
use openmates_sdk::view_model::{self, RequestId};
use std::sync::Arc;

#[uniffi::export]
impl ViewModelCore {
    /// Delete chat `chat_id` on every device (a draft-only chat loses its
    /// draft instead), close its window when open, then emit `ChatList`.
    /// Runs on the actor, so it waits for a running command.
    ///
    /// # Errors
    /// `Authentication` when signed out; `Invalid` for a malformed or
    /// volatile chat id; `Protocol` when the server refuses; `Offline`;
    /// `Cancelled`. Nothing is published on failure.
    pub async fn delete_chat(
        &self,
        chat_id: String,
        cancellation: Option<Arc<CoreCancellation>>,
    ) -> Result<(), CoreError> {
        let (shared, token) = (self.shared.clone(), self.detached(cancellation));
        self.run(async move {
            shared
                .signed_in(token, move |host, sink, cancel| {
                    view_model::delete_chat(host, chat_id, sink, cancel)
                })
                .await
        })
        .await
    }

    /// Delete message `message_id` of personal chat `chat_id` on every
    /// device. When that chat is the open window it is read again and
    /// emitted as `ChatWindow` events carrying `request`.
    ///
    /// # Errors
    /// `Authentication` when signed out; `Invalid` for a malformed chat id or
    /// an empty message id; `Forbidden` in a team scope; `Protocol` when the
    /// server refuses; `Offline` without an answer in 20 seconds;
    /// `Cancelled`.
    pub async fn delete_message(
        &self,
        request: u64,
        chat_id: String,
        message_id: String,
        cancellation: Option<Arc<CoreCancellation>>,
    ) -> Result<(), CoreError> {
        let (shared, token) = (self.shared.clone(), self.detached(cancellation));
        self.run(async move {
            shared
                .signed_in(token, move |host, sink, cancel| {
                    view_model::delete_message(
                        host,
                        RequestId(request),
                        chat_id,
                        message_id,
                        sink,
                        cancel,
                    )
                })
                .await
        })
        .await
    }

    /// Edit user message `message_id` of personal chat `chat_id`: the core
    /// removes it and every later message, reads the open window again, then
    /// sends `text` as `request` exactly like `send` (same events, same
    /// `cancelSend`, same send settings). Returns the sent window
    /// (`Canonical`). A failed send keeps the truncation.
    ///
    /// # Errors
    /// `Authentication` when signed out; `Invalid` for empty text, an
    /// assistant or unknown message; `Forbidden` in a team scope; rewind,
    /// delete and send errors as `deleteMessage` and `send`; `Cancelled`.
    pub async fn edit_message(
        &self,
        request: u64,
        chat_id: String,
        message_id: String,
        text: String,
        cancellation: Option<Arc<CoreCancellation>>,
    ) -> Result<ChatWindowViewRecord, CoreError> {
        let (shared, token) = (self.shared.clone(), self.foreground(cancellation));
        self.run(async move {
            let settings = SendSettings::read(&shared);
            let record = shared
                .signed_in(token, move |host, sink, cancel| {
                    settings.apply(host);
                    view_model::edit_message(
                        host,
                        RequestId(request),
                        chat_id,
                        message_id,
                        text,
                        sink,
                        cancel,
                    )
                })
                .await?;
            Ok(ChatWindowViewRecord::from(record))
        })
        .await
    }

    /// Retry the newest unanswered user turn of personal chat `chat_id`:
    /// the core rewinds to the message before it, reads the open window
    /// again and sends the same text as `request` like `send`. Returns the
    /// sent window (`Canonical`).
    ///
    /// # Errors
    /// `Authentication` when signed out; `Invalid` for a malformed id, when
    /// no turn is retryable or it is the first message; `Forbidden` in a
    /// team scope; rewind and send errors; `Cancelled`.
    pub async fn retry_last_turn(
        &self,
        request: u64,
        chat_id: String,
        cancellation: Option<Arc<CoreCancellation>>,
    ) -> Result<ChatWindowViewRecord, CoreError> {
        let (shared, token) = (self.shared.clone(), self.foreground(cancellation));
        self.run(async move {
            let settings = SendSettings::read(&shared);
            let record = shared
                .signed_in(token, move |host, sink, cancel| {
                    settings.apply(host);
                    view_model::retry_turn(host, RequestId(request), chat_id, sink, cancel)
                })
                .await?;
            Ok(ChatWindowViewRecord::from(record))
        })
        .await
    }

    /// Fork personal chat `chat_id` up to and including `message_id` into a
    /// new encrypted chat titled `title` (`nil`: "Fork of <title>"), then
    /// refresh and emit `ChatList`. Returns the new chat's id.
    ///
    /// # Errors
    /// `Authentication` when signed out; `Invalid` for a malformed id or an
    /// unknown message; `Forbidden` in a team scope; `Invalid` for a Direct
    /// chat; server refusals; `Protocol`, `Offline`; `Cancelled`.
    pub async fn fork_chat(
        &self,
        chat_id: String,
        message_id: String,
        title: Option<String>,
        cancellation: Option<Arc<CoreCancellation>>,
    ) -> Result<String, CoreError> {
        let (shared, token) = (self.shared.clone(), self.detached(cancellation));
        self.run(async move {
            shared
                .signed_in(token, move |host, sink, cancel| {
                    view_model::fork_chat(host, chat_id, message_id, title, sink, cancel)
                })
                .await
        })
        .await
    }

    /// Save `markdown` as the encrypted draft of `chat_id` (`nil`: a new
    /// chat), then emit `ChatList`. Returns the draft's chat id.
    ///
    /// # Errors
    /// `Authentication` when signed out; `Invalid` for a malformed id, a
    /// volatile chat or an oversized draft; `Forbidden` in a team scope;
    /// `Offline`; `Cancelled`.
    pub async fn save_draft(
        &self,
        chat_id: Option<String>,
        markdown: String,
        cancellation: Option<Arc<CoreCancellation>>,
    ) -> Result<String, CoreError> {
        let (shared, token) = (self.shared.clone(), self.detached(cancellation));
        self.run(async move {
            shared
                .signed_in(token, move |host, sink, cancel| {
                    view_model::save_draft(host, chat_id, markdown, sink, cancel)
                })
                .await
        })
        .await
    }

    /// Clear the draft of `chat_id` with its versioned tombstone (a
    /// draft-only chat disappears), then emit `ChatList`.
    ///
    /// # Errors
    /// `Authentication` when signed out; `Invalid` for a malformed or
    /// volatile id; `Unavailable(team_draft_clear_unavailable)` in a team
    /// scope; `Conflict`, `Offline`; `Cancelled`.
    pub async fn clear_draft(
        &self,
        chat_id: String,
        cancellation: Option<Arc<CoreCancellation>>,
    ) -> Result<(), CoreError> {
        let (shared, token) = (self.shared.clone(), self.detached(cancellation));
        self.run(async move {
            shared
                .signed_in(token, move |host, sink, cancel| {
                    view_model::clear_draft(host, chat_id, sink, cancel)
                })
                .await
        })
        .await
    }

    /// Stop assistant task `task_id` in `chat_id` (a reply this core did not
    /// start, for example one from another device). To stop this core's own
    /// running `send`, `editMessage` or `retryLastTurn`, call `cancelSend`:
    /// this call queues behind the running command. The reply then ends
    /// through the normal stream events.
    ///
    /// # Errors
    /// `Authentication` when signed out; `Invalid` for a malformed chat id or
    /// an empty task id; `Protocol` when the server refuses; `Offline`
    /// without an answer in 20 seconds; `Cancelled`.
    pub async fn stop_reply(
        &self,
        chat_id: String,
        task_id: String,
        cancellation: Option<Arc<CoreCancellation>>,
    ) -> Result<(), CoreError> {
        let (shared, token) = (self.shared.clone(), self.detached(cancellation));
        self.run(async move {
            shared
                .signed_in(token, move |host, _sink, cancel| {
                    view_model::stop_reply(host, chat_id, task_id, cancel)
                })
                .await
        })
        .await
    }
}
