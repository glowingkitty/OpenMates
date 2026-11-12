//! Fresh host admission; never promote a Task watch/read binding.
use super::*;
use crate::client::{SourceHostAdapter, SourceHostBinding, SourceHostScope};
use std::sync::Arc;
impl Projects<'_> {
    pub async fn source_host_binding(
        &mut self,
        selector: &str,
        id: &str,
        adapter: Arc<dyn SourceHostAdapter>,
    ) -> Result<SourceHostBinding> {
        // Explicit API-key refusal before validation, Project or source transport.
        if matches!(&self.backend, Backend::ApiKey(_)) {
            return Err(Error::Unavailable {
                code: "project_source_host_unavailable",
                reason: "PROJECT_SOURCE_HOST_REQUIRES_COOKIE_SESSION",
            });
        }
        self.scope()?;
        if self.operation_cancel.is_cancelled() {
            return Err(Error::Cancelled);
        }
        if id.is_empty() || id.len() > 128 || id.chars().any(char::is_control) {
            return Err(Error::Invalid("Supply an exact Project source ID."));
        }
        let capabilities = adapter.implemented_capabilities();
        if capabilities.is_empty()
            || capabilities.len() > 5
            || capabilities
                .iter()
                .enumerate()
                .any(|(i, c)| capabilities[..i].contains(c))
            || capabilities
                .iter()
                .any(|c| matches!(c, ProjectSourceCapability::Import))
        {
            return Err(Error::Invalid(
                "Supply nonempty implemented bridge capabilities.",
            ));
        }
        // Every operation covered by an advertised capability has an adapter entry.
        for capability in &capabilities {
            use crate::client::SourceHostOperation as Op;
            let operations: &[Op] = match capability {
                ProjectSourceCapability::Read => &[
                    Op::List,
                    Op::ReadText,
                    Op::ReadImageChunk,
                    Op::ReadFileChunk,
                ],
                ProjectSourceCapability::Search => &[Op::Search],
                ProjectSourceCapability::WriteRequest => &[
                    Op::CreateFile,
                    Op::UpdateFile,
                    Op::CopyEntries,
                    Op::MoveEntries,
                ],
                // The adapter advertises this only when a sandbox tier exists.
                ProjectSourceCapability::RunCommand => &[Op::RunCommand],
                _ => &[],
            };
            if !operations.iter().all(|op| adapter.supports_operation(*op)) {
                return Err(Error::Invalid(
                    "Advertised host capability has no implementation.",
                ));
            }
        }
        let (owner, api) = match &mut self.backend {
            Backend::Cookie(client) => {
                client.validate_session().await?;
                (
                    client.user()["id"]
                        .as_str()
                        .or_else(|| client.user()["user_id"].as_str())
                        .filter(|v| !v.is_empty())
                        .ok_or(Error::Authentication)?
                        .to_owned(),
                    client
                        .session()
                        .ok_or(Error::Authentication)?
                        .api_url
                        .trim_end_matches('/')
                        .to_owned(),
                )
            }
            _ => return Err(Error::Authentication),
        };
        let project = self.resolve(selector).await?;
        let project_id = string(&project.raw, "project_id")?.to_owned();
        let route = self.path(&format!("/v1/projects/{project_id}/sources"), &[]);
        let response = self
            .backend
            .request(Method::GET, &route, None, None)
            .await?;
        let rows = response["sources"].as_array().ok_or(Error::Protocol)?;
        let exact = rows
            .iter()
            .filter(|row| row["source_id"] == id)
            .collect::<Vec<_>>();
        if exact.len() != 1 {
            return Err(Error::Forbidden);
        }
        let raw = exact[0];
        let configured: Vec<ProjectSourceCapability> =
            serde_json::from_value(raw["capabilities"].clone())?;
        let status: ProjectSourceStatus = serde_json::from_value(raw["status"].clone())?;
        if status == ProjectSourceStatus::Revoked
            || capabilities.iter().any(|cap| !configured.contains(cap))
        {
            return Err(Error::Forbidden);
        }
        if self.filters.team_id.is_some() {
            // Canonical Team list strips raw owner hashes and computes this
            // label from attached_by_user_hash==hash(authenticated user).
            if raw["ownership_label"] != "attached_by_you" {
                return Err(Error::Forbidden);
            }
        } else if raw["hashed_project_id"] != hash(&project_id)
            || raw["hashed_user_id"] != hash(&owner)
            || !raw["hashed_team_id"].is_null()
        {
            return Err(Error::Forbidden);
        }
        if self.operation_cancel.is_cancelled() {
            return Err(Error::Cancelled);
        }
        let scope = SourceHostScope {
            api,
            owner,
            team: self.filters.team_id.clone(),
            project: project_id,
            source: id.to_owned(),
            key_epoch: 1,
        };
        match &self.backend {
            Backend::Cookie(client) => {
                client.bind_source_host(scope, project.key, adapter, capabilities)
            }
            _ => Err(Error::Authentication),
        }
    }
}
#[cfg(test)]
#[path = "source_host_tests.rs"]
mod tests;
