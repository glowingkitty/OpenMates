//! Origin-side stop of one running remote command execution (npm
//! `projects settings <project> command stop`). The chat must have this
//! Project's focus active; the request then goes over a short-lived socket
//! that declares only the `remote_command_jobs` capability set.
use super::*;

/// npm `stopRemoteCommand` focus guard message.
pub const REMOTE_COMMAND_FOCUS_INACTIVE: &str =
    "The requested Project focus is not active for this chat.";

impl Projects<'_> {
    /// Request a stop and return the server `remote_command_stop_ack` payload.
    pub async fn stop_remote_command(
        &mut self,
        project_id: &str,
        chat_id: &str,
        execution_id: &str,
    ) -> Result<Value> {
        if matches!(self.backend, Backend::ApiKey(_)) {
            return Err(Error::Unavailable {
                code: "remote_command_stop_unavailable",
                reason: "REMOTE_COMMAND_STOP_REQUIRES_COOKIE_SESSION",
            });
        }
        self.scope()?;
        uuid(project_id)?;
        uuid(chat_id)?;
        if self.operation_cancel.is_cancelled() {
            return Err(Error::Cancelled);
        }
        let focus = self.active_focus(chat_id).await?;
        if focus["project_id"].as_str() != Some(project_id) {
            return Err(Error::Invalid(REMOTE_COMMAND_FOCUS_INACTIVE));
        }
        if self.operation_cancel.is_cancelled() {
            return Err(Error::Cancelled);
        }
        let team = self.filters.team_id.clone();
        match &mut self.backend {
            Backend::Cookie(client) => {
                client
                    .stop_remote_command(execution_id, chat_id, project_id, team.as_deref())
                    .await
            }
            Backend::ApiKey(_) => Err(Error::Unavailable {
                code: "remote_command_stop_unavailable",
                reason: "REMOTE_COMMAND_STOP_REQUIRES_COOKIE_SESSION",
            }),
        }
    }
}
