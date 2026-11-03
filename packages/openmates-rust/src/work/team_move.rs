//! npm `moveWorkspaceToTeam`: move a personal workspace object into a Team.
//! The slug lookup index is re-keyed with the Team key (the slug itself stays
//! encrypted with the object's own key) and a Project additionally gains a
//! Team key wrapper, all locally before the server performs the move.
use super::*;

/// Workspace object kinds accepted by `teams move --type`.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum WorkspaceMoveType {
    Chat,
    Project,
    Task,
    Plan,
    Workflow,
}
impl WorkspaceMoveType {
    /// npm `parseWorkspaceMoveType` accepts exactly these lowercase names.
    pub fn parse(value: &str) -> Option<Self> {
        match value {
            "chat" => Some(Self::Chat),
            "project" => Some(Self::Project),
            "task" => Some(Self::Task),
            "plan" => Some(Self::Plan),
            "workflow" => Some(Self::Workflow),
            _ => None,
        }
    }
    pub fn as_str(self) -> &'static str {
        match self {
            Self::Chat => "chat",
            Self::Project => "project",
            Self::Task => "task",
            Self::Plan => "plan",
            Self::Workflow => "workflow",
        }
    }
    fn route(self, id: &str) -> Result<String> {
        let id = uuid(id)?;
        Ok(match self {
            Self::Chat => format!("/v1/chats/{id}/move"),
            Self::Project => format!("/v1/projects/{id}/move"),
            Self::Task => format!("/v1/user-tasks/{id}/move"),
            Self::Plan => format!("/v1/user-plans/{id}/move"),
            Self::Workflow => format!("/v1/workflows/{id}/move"),
        })
    }
}

/// Failures the CLI reports with the npm wording.
pub enum WorkspaceMoveError {
    /// The Team record carries no Team key this account can unwrap.
    TeamKeyUnavailable,
    /// The move request itself failed with this HTTP status.
    Http(u16),
    Sdk(Error),
}
impl From<Error> for WorkspaceMoveError {
    fn from(error: Error) -> Self {
        Self::Sdk(error)
    }
}

/// npm `buildWorkspaceMovePayload` with explicit keys. The slug index uses
/// the Team key; a Project also gets an epoch-1 Team key wrapper.
pub(crate) fn move_payload(
    team: &str,
    moved_at: u64,
    slug: &str,
    object_key: &[u8; 32],
    team_key: &[u8; 32],
    project_key: Option<&[u8; 32]>,
) -> Result<Value> {
    let mut payload = json!({"team_id":team,"confirmed":true,"moved_at":moved_at});
    if !slug.is_empty() {
        let slug = crypto::normalize_object_slug(slug)?;
        payload["encrypted_slug"] =
            json!(super::teams::legacy_encrypt(slug.as_bytes(), object_key)?);
        payload["slug_lookup_hash"] = json!(crypto::object_slug_lookup_hash(&slug, team_key)?);
    }
    if let Some(project_key) = project_key {
        payload["team_project_key_wrapper"] = json!({
            "key_type":"team",
            "hashed_team_id":hash(team),
            "team_key_epoch":1,
            "encrypted_project_key":super::teams::legacy_encrypt(project_key, team_key)?,
            "wrapper_version":1,
            "created_at":moved_at,
        });
    }
    Ok(payload)
}

/// npm spreads the server response over `{success: true}`.
pub(crate) fn move_result(response: &Value) -> Value {
    let mut result = json!({"success":true});
    if let Some(fields) = response.as_object() {
        for (key, value) in fields {
            result[key] = value.clone();
        }
    }
    result
}

impl Client {
    /// The Team key unwrapped with this account's master key (npm `loadTeamKeyBytes`).
    async fn move_team_key(&mut self, team: &str) -> std::result::Result<Key, WorkspaceMoveError> {
        let master = self.work_master_key()?;
        let row = self.teams().get(team).await?;
        let wrapped = row["encrypted_team_key"]
            .as_str()
            .filter(|value| !value.is_empty())
            .ok_or(WorkspaceMoveError::TeamKeyUnavailable)?;
        let raw = crypto::decrypt_bytes(wrapped, &master)
            .map_err(|_| WorkspaceMoveError::TeamKeyUnavailable)?;
        Ok(key_bytes(&raw)?)
    }

    /// Move one personal Project, Task, Plan or Workflow into `team`.
    /// Chats need their synced chat key and are refused explicitly here.
    pub async fn move_workspace_to_team(
        &mut self,
        kind: WorkspaceMoveType,
        selector: &str,
        team: &str,
    ) -> std::result::Result<Value, WorkspaceMoveError> {
        self.require_session()?;
        if kind == WorkspaceMoveType::Chat {
            return Err(WorkspaceMoveError::Sdk(Error::Unavailable {
                code: "workspace_move_unavailable",
                reason: "CHAT_MOVE_REQUIRES_SYNCED_CHAT_KEY",
            }));
        }
        let moved_at = now();
        let team_key = self.move_team_key(team).await?;
        let (object_id, payload) = match kind {
            WorkspaceMoveType::Project => {
                let project = self
                    .projects()
                    .with_filters(ProjectFilters {
                        personal: true,
                        ..Default::default()
                    })
                    .resolve(selector)
                    .await?;
                let slug = project.public["slug"].as_str().unwrap_or("");
                let payload = move_payload(
                    team,
                    moved_at,
                    slug,
                    &project.key,
                    &team_key,
                    Some(&*project.key),
                )?;
                (string(&project.raw, "project_id")?.to_owned(), payload)
            }
            WorkspaceMoveType::Task => {
                let task = self
                    .tasks()
                    .with_filters(TaskFilters {
                        personal: true,
                        ..Default::default()
                    })
                    .resolve(selector)
                    .await?;
                let slug = task.public["slug"].as_str().unwrap_or("");
                let payload = move_payload(team, moved_at, slug, &task.key, &team_key, None)?;
                (string(&task.raw, "task_id")?.to_owned(), payload)
            }
            WorkspaceMoveType::Plan => {
                let plan = self
                    .plans()
                    .with_filters(PlanFilters {
                        personal: true,
                        ..Default::default()
                    })
                    .resolve(selector)
                    .await?;
                let slug = plan.public["slug"].as_str().unwrap_or("");
                let payload = move_payload(team, moved_at, slug, &plan.key, &team_key, None)?;
                (string(&plan.raw, "plan_id")?.to_owned(), payload)
            }
            WorkspaceMoveType::Workflow => {
                let workflow = self
                    .workflows()
                    .with_filters(WorkflowFilters {
                        personal: true,
                        ..Default::default()
                    })
                    .get(selector)
                    .await?;
                let slug = workflow["slug"].as_str().unwrap_or("");
                let payload = move_payload(team, moved_at, slug, &team_key, &team_key, None)?;
                (string(&workflow, "id")?.to_owned(), payload)
            }
            WorkspaceMoveType::Chat => return Err(WorkspaceMoveError::Sdk(Error::Protocol)),
        };
        let route = kind.route(&object_id)?;
        let mut status = None;
        match self
            .request_task_headers_observed(
                Method::POST,
                &route,
                Some(payload),
                None,
                None,
                None,
                &mut status,
            )
            .await
        {
            Ok(response) => Ok(move_result(&response)),
            Err(error @ (Error::Expired | Error::Cancelled)) => Err(error.into()),
            Err(error) => Err(match status {
                Some(status) => WorkspaceMoveError::Http(status),
                None => error.into(),
            }),
        }
    }
}

#[cfg(test)]
#[path = "team_move_tests.rs"]
mod tests;
