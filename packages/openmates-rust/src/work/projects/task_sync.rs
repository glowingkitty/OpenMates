//! Explicit Cookie authorization; this does not register a remote-access host.
use super::*;
use crate::{client::ProjectTaskBinding, project_task_sync::TaskSyncWorkspace};
impl Projects<'_> {
    /// Bind an exact source to a freshly authorized Project and its selected key.
    /// Offline sources remain valid; revoked sources never authorize a watch.
    pub async fn task_source(
        &mut self,
        selector: &str,
        source_id: &str,
    ) -> Result<ProjectTaskBinding> {
        self.scope()?;
        if self.operation_cancel.is_cancelled() {
            return Err(Error::Cancelled);
        }
        match &mut self.backend {
            Backend::ApiKey(_) => {
                return Err(Error::Unavailable {
                    code: "project_task_watch_unavailable",
                    reason: "PROJECT_TASK_WATCH_REQUIRES_COOKIE_SESSION",
                });
            }
            Backend::Cookie(client) => client.validate_session().await?,
        }
        if source_id.is_empty() || source_id.len() > 128 || source_id.chars().any(char::is_control)
        {
            return Err(Error::Invalid("Supply an exact Project source ID."));
        }
        let project = self.resolve(selector).await?;
        let id = string(&project.raw, "project_id")?.to_owned();
        let path = self.path(&format!("/v1/projects/{id}/sources"), &[]);
        let response = self.backend.request(Method::GET, &path, None, None).await?;
        let sources = response["sources"].as_array().ok_or(Error::Protocol)?;
        let matches = sources
            .iter()
            .filter(|row| row["source_id"] == source_id)
            .collect::<Vec<_>>();
        if matches.len() != 1 {
            return Err(Error::Forbidden);
        }
        match matches[0]["status"].as_str() {
            Some("offline" | "connected" | "permission_required") => {}
            Some("revoked") => return Err(Error::Forbidden),
            _ => return Err(Error::Protocol),
        }
        if self.operation_cancel.is_cancelled() {
            return Err(Error::Cancelled);
        }
        let workspace = self
            .filters
            .team_id
            .clone()
            .map(TaskSyncWorkspace::Team)
            .unwrap_or(TaskSyncWorkspace::Personal);
        match &self.backend {
            Backend::Cookie(client) => {
                client.bind_project_task_source(workspace, &id, source_id, project.key)
            }
            Backend::ApiKey(_) => Err(Error::Authentication),
        }
    }
}
