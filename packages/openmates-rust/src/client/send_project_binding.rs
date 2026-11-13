//! Explicit Project binding for one saved send (`SendOptions::project_id`).
//!
//! Shared core for CLI/TUI `chats new|send --project <uuid>` and any shell that
//! starts a chat inside a Project. Mirrors the npm CLI
//! `prepareCliProjectFocusForPreflight` (`openmates-cli/src/projectFileExecutor.ts`)
//! and the web @Project mention (`activateProjectFocusForSend`): a new chat is
//! first stored with its wrapped key, then the Project's default focus is
//! activated, so the same turn already carries the Project context and Memories.
//! Implements `feature.projects` Project focus activation.
use super::*;
use super::transport::{Socket, send, wait};

/// How long the server may take to store a new chat's key shell.
const CHAT_STORED_TIMEOUT: Duration = Duration::from_secs(20);

impl Client {
    /// Activate `project_id`'s default focus in chat `id` before the turn's
    /// context is collected.
    ///
    /// For a new chat the chat key shell is stored first (`encrypted_chat_metadata`,
    /// answered by `encrypted_metadata_stored`), because the server activates a
    /// Project focus only for an existing chat. The later admission still
    /// carries the same wrapped key and `created` (seconds), which the server
    /// accepts only when they match the stored shell field by field.
    ///
    /// # Errors
    /// [`Error::Cancelled`] on cancellation, [`Error::Offline`] when the chat is
    /// not stored in time, and the Project service errors (`Forbidden` for a
    /// Project the account cannot use).
    #[allow(clippy::too_many_arguments)] // One socket-bound step of the send; each value is turn state.
    pub(in crate::client) async fn bind_project_for_send(
        &mut self,
        ws: &mut Socket,
        id: &str,
        project_id: &str,
        new_chat: bool,
        wrapped: &str,
        created: u64,
        team: Option<&str>,
        cancel: &CancellationToken,
    ) -> Result<()> {
        if new_chat {
            let mut shell = json!({"chat_id":id,"encrypted_chat_key":wrapped,"created_at":created,"versions":{}});
            if let Some(team) = team {
                shell["team_id"] = json!(team);
            }
            send(ws, "encrypted_chat_metadata", shell).await?;
            tokio::select! {
                biased;
                _ = cancel.cancelled() => return Err(Error::Cancelled),
                stored = crate::platform::time::timeout(CHAT_STORED_TIMEOUT, wait(ws, "encrypted_metadata_stored", "chat_id", id)) => {
                    stored.map_err(|_| Error::Offline)??;
                }
            }
        }
        if cancel.is_cancelled() {
            return Err(Error::Cancelled);
        }
        self.projects().activate_focus(project_id, id).await?;
        Ok(())
    }
}
