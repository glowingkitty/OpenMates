//! Per-message chat actions of first-party session clients: delete one
//! message, truncate a chat for an edited user message and stop a running
//! assistant reply. Mirrors the web `chatSyncService.sendDeleteMessage`,
//! the edit-mode branch of `sendHandlers.ts` (delete from the edited message
//! on, then resend) and `sendCancelAITask`; the frames come from
//! `chat_state::management`. Plan `apple-client-core-migration` step A5;
//! spec `client-core` (send, streaming, cancel).
use super::chat_rewrite::ChatRewriteState;
use super::sync_capability::AsyncCryptoScope;
use super::transport::{send, wait};
use super::*;
use crate::chat_state::management::delete_message_frame;

/// How long a delete or stop waits for the server's answer on its socket.
const ACK_TIMEOUT: Duration = Duration::from_secs(20);
const MISSING_MESSAGE: &str = "The message is not in this chat.";
const NOT_USER_MESSAGE: &str = "Only your own messages can be edited.";

/// What an edit of one user message removes before the new text is sent.
#[derive(Debug, PartialEq, Eq)]
pub enum EditTruncation {
    /// Rewind the chat to this boundary index: messages after it are deleted
    /// in one versioned server operation (`POST /v1/chats/{id}/rewind`).
    Rewind(usize),
    /// The edited message is the first one, which a rewind cannot remove:
    /// delete these server message ids one by one (the web edit path).
    DeleteAll(Vec<String>),
}

/// The truncation an edit of `message_id` needs: everything from the edited
/// message on goes, so the server sees the history before it.
///
/// # Errors
/// `Invalid` when the message is not in the chat or is not a user message;
/// `Protocol` when a row has no server identity.
pub fn edit_truncation(state: &ChatRewriteState, message_id: &str) -> Result<EditTruncation> {
    let index = state
        .boundary_index(message_id)
        .ok_or(Error::Invalid(MISSING_MESSAGE))?;
    let role = state.messages()[index].role.to_lowercase();
    if role != "user" {
        return Err(Error::Invalid(NOT_USER_MESSAGE));
    }
    if index > 0 {
        return Ok(EditTruncation::Rewind(index - 1));
    }
    (0..state.messages().len())
        .map(|i| state.server_message_id(i))
        .collect::<Result<Vec<_>>>()
        .map(EditTruncation::DeleteAll)
}

impl Client {
    /// Delete `message_id` of personal chat `chat_id` on every device
    /// (`delete_message`, answered by the `message_deleted` broadcast), then
    /// drop the chat's loaded history so the next open reads the server's.
    ///
    /// # Errors
    /// `Invalid` for a malformed chat id, an empty message id or a volatile
    /// chat; `Forbidden` in a team scope or for a chat the account may not
    /// write; `Protocol` when the server answers with an error frame;
    /// `Offline` without an answer within 20 seconds; `Cancelled` when the
    /// operation token fires.
    pub async fn delete_message(&mut self, chat_id: &str, message_id: &str) -> Result<()> {
        self.delete_messages(chat_id, &[message_id.to_owned()])
            .await
    }

    /// [`Client::delete_message`] for several messages over one socket, in
    /// order. Messages deleted before a failure stay deleted.
    ///
    /// # Errors
    /// As [`Client::delete_message`].
    pub async fn delete_messages(&mut self, chat_id: &str, message_ids: &[String]) -> Result<()> {
        self.check_message_action(chat_id)?;
        if message_ids.is_empty() || message_ids.iter().any(String::is_empty) {
            return Err(Error::Invalid(MISSING_MESSAGE));
        }
        let cancel = self.operation_cancel.clone();
        if cancel.is_cancelled() {
            return Err(Error::Cancelled);
        }
        let mut ws = self.socket_with_task_jobs(false).await?;
        let scope = AsyncCryptoScope::begin(self)?;
        let mut result = Ok(());
        for message_id in message_ids {
            // Re-checked per frame: a logout, team switch or denial between
            // two deletes stops the rest.
            result = scope.check_chat(self, chat_id);
            if result.is_err() {
                break;
            }
            let frame = delete_message_frame(chat_id, message_id, &[]);
            result = acknowledged(&cancel, async {
                send(&mut ws, frame.frame_type, frame.payload).await?;
                wait(&mut ws, "message_deleted", "message_id", message_id).await
            })
            .await
            .map(drop);
            if result.is_err() {
                break;
            }
        }
        let _ = ws.close(None).await;
        // Even a partial delete changed the server history.
        self.forget_loaded_history(chat_id);
        result?;
        scope.check_chat(self, chat_id)
    }

    /// Remove `message_id` and every later message of personal chat `chat_id`
    /// so the edited text can be sent as the next turn ([`edit_truncation`]).
    /// Reads the chat's full history first (one exact read, no account sync).
    ///
    /// # Errors
    /// As [`Client::chat_rewrite_state`], [`edit_truncation`],
    /// [`Client::rewind_chat`] and [`Client::delete_messages`].
    pub async fn truncate_for_edit(&mut self, chat_id: &str, message_id: &str) -> Result<()> {
        self.check_message_action(chat_id)?;
        let state = self.chat_rewrite_state(chat_id).await?;
        match edit_truncation(&state, message_id)? {
            EditTruncation::Rewind(boundary) => self
                .rewind_chat(&state, boundary, false, true)
                .await
                .map(drop),
            EditTruncation::DeleteAll(ids) => self.delete_messages(chat_id, &ids).await,
        }
    }

    /// Ask the server to stop assistant task `task_id` of `chat_id`
    /// (`cancel_ai_task`, answered by `ai_task_cancel_requested`). The reply
    /// ends through the normal stream path of whichever socket runs it. For a
    /// send this client runs, cancel that send instead: it sends the same
    /// frame on its own socket.
    ///
    /// # Errors
    /// `Invalid` for a malformed chat id or an empty task id; `Protocol` for
    /// an error answer; `Offline` without an answer within 20 seconds;
    /// `Cancelled` when the operation token fires.
    pub async fn cancel_ai_task(&mut self, chat_id: &str, task_id: &str) -> Result<()> {
        self.require_session()?;
        uuid::Uuid::parse_str(chat_id).map_err(|_| Error::Invalid("Invalid chat ID."))?;
        if task_id.is_empty() {
            return Err(Error::Invalid("A task ID is required."));
        }
        let cancel = self.operation_cancel.clone();
        if cancel.is_cancelled() {
            return Err(Error::Cancelled);
        }
        let mut ws = self.socket_with_task_jobs(false).await?;
        let scope = AsyncCryptoScope::begin(self)?;
        scope.check_chat(self, chat_id)?;
        let result = acknowledged(&cancel, async {
            send(
                &mut ws,
                "cancel_ai_task",
                json!({"task_id": task_id, "chat_id": chat_id}),
            )
            .await?;
            wait(&mut ws, "ai_task_cancel_requested", "task_id", task_id).await
        })
        .await;
        let _ = ws.close(None).await;
        result.map(drop)
    }

    /// Refusals shared by the message actions, before any network.
    fn check_message_action(&self, chat_id: &str) -> Result<()> {
        self.require_session()?;
        uuid::Uuid::parse_str(chat_id).map_err(|_| Error::Invalid("Invalid chat ID."))?;
        if self.is_ephemeral_chat(chat_id) {
            return Err(Error::Invalid("Volatile chats have no saved messages."));
        }
        if self.team()?.is_some() {
            return Err(Error::Forbidden);
        }
        Ok(())
    }

    /// Drop the loaded history of `chat_id` (as after a rewind) so no stale
    /// message survives a server-side delete.
    fn forget_loaded_history(&mut self, chat_id: &str) {
        self.history.remove(chat_id);
        self.sync_message_windows.remove(chat_id);
        self.selected_first_pages.remove(chat_id);
        self.invalidate_chat_list_freshness();
    }
}

/// `work` bounded by [`ACK_TIMEOUT`] and by `cancel`.
pub(super) async fn acknowledged<T>(
    cancel: &CancellationToken,
    work: impl std::future::Future<Output = Result<T>>,
) -> Result<T> {
    tokio::select! {
        biased;
        () = cancel.cancelled() => Err(Error::Cancelled),
        result = crate::platform::time::timeout(ACK_TIMEOUT, work) => {
            result.map_err(|_| Error::Offline)?
        }
    }
}

#[cfg(test)]
#[path = "message_actions_tests.rs"]
pub(super) mod tests;
