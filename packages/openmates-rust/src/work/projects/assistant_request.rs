//! Assistant-initiated Project creation (`openmates.project_create_request` v1).
//!
//! Shared-core executor for the pending client action the server sends when a
//! chat turn needs a Project: validate the request, create the encrypted
//! Project (Apply and show), activate its default focus without countdown and
//! undo both again. The WebSocket exchange lives in
//! `client::project_create_request`; this module only owns REST and crypto.
//! Contract: `docs/plans/cloud-project-development/contracts/project-create-request.md`;
//! assertion `projects.creation.assistant-inferred`.
//!
//! The "created Project" card survives a chat reload without a new store: the
//! creation record is written into the Project's own encrypted settings
//! (`creation`), and the chat's active focus binding finds the Project again.
use super::*;

/// Whether a Project's encrypted `settings.creation` marks it as created by the
/// assistant for `chat_id`. The one rule behind Undo for every shell.
pub(crate) fn is_creation_record(creation: &Value, chat_id: &str) -> bool {
    creation["origin"] == "assistant_request" && creation["chat_id"] == chat_id
}

/// Contract name every request must carry.
pub const PROJECT_CREATE_CONTRACT: &str = "openmates.project_create_request";
/// Contract version this core implements.
pub const PROJECT_CREATE_VERSION: u64 = 1;
/// Plaintext proposal limits from the contract.
const MAX_NAME_CHARS: usize = 120;
const MAX_DESCRIPTION_CHARS: usize = 400;

/// A validated creation request. Built only by [`ProjectCreateRequest::parse`].
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct ProjectCreateRequest {
    /// Opaque request id, echoed unchanged in the report.
    pub request_id: String,
    /// Chat whose turn is waiting for the report.
    pub chat_id: String,
    /// Personal when `None`, else the Team that receives the Project.
    pub team_id: Option<String>,
    /// Plaintext proposal; encrypted before it leaves the client.
    pub name: String,
    /// Plaintext description proposal (may be empty).
    pub description: String,
    /// `web_app` or `native_app`.
    pub kind: String,
    /// Project folder for the application's files (`web-app` / `native-app`).
    pub subfolder: String,
    /// Unix seconds after which the server rejects the report.
    pub expires_at: u64,
    /// Where the Project lives; a machine request needs the user's confirmation.
    pub(crate) location: ProjectCreateLocation,
    /// Short plaintext hint naming the wanted machine (may be empty).
    pub(crate) machine_hint: String,
}

/// Where the requested Project is created.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub(crate) enum ProjectCreateLocation {
    /// Encrypted Project in the cloud, created automatically.
    Cloud,
    /// Project plus a folder on one of the user's machines, only after the user
    /// confirmed it.
    Machine,
}

/// Why a request was refused; the code is the report's `error_code`.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum ProjectCreateRefusal {
    /// Wrong contract name/version, shape or limits.
    Invalid,
    /// `expires_at` has passed; nothing is created.
    Expired,
}

impl ProjectCreateRefusal {
    /// Stable `error_code` for the `failed` report (`^[A-Z0-9_]{1,64}$`).
    pub fn code(self) -> &'static str {
        match self {
            Self::Invalid => "PROJECT_CREATE_REQUEST_INVALID",
            Self::Expired => "PROJECT_CREATE_REQUEST_EXPIRED",
        }
    }
}

impl ProjectCreateRequest {
    /// Validate the event payload's `pending_client_action` for `chat_id`.
    ///
    /// The request id is returned even for a refused request, so the caller can
    /// still report `failed` for it.
    ///
    /// # Errors
    /// [`ProjectCreateRefusal::Invalid`] for a foreign contract, version,
    /// action, chat, write mode, focus policy or oversize text;
    /// [`ProjectCreateRefusal::Expired`] once `now_s` reached `expires_at`.
    pub fn parse(
        payload: &Value,
        chat_id: &str,
        now_s: u64,
    ) -> std::result::Result<Self, (Option<String>, ProjectCreateRefusal)> {
        let action = &payload["pending_client_action"];
        let id = action["request_id"]
            .as_str()
            .filter(|id| is_request_id(id))
            .map(str::to_owned);
        let refuse = |why| Err((id.clone(), why));
        if action["contract"] != PROJECT_CREATE_CONTRACT
            || action["version"] != PROJECT_CREATE_VERSION
            || action["action"] != "create"
            || action["chat_id"] != chat_id
            || payload["request_id"] != action["request_id"]
            || action["write_mode"] != "apply_and_show"
            || id.is_none()
        {
            return refuse(ProjectCreateRefusal::Invalid);
        }
        let (location, focus_policy) = match action["location"].as_str() {
            None if action["location"].is_null() => (ProjectCreateLocation::Cloud, "immediate"),
            Some("cloud") => (ProjectCreateLocation::Cloud, "immediate"),
            Some("machine") if action["confirmation_required"] == true => {
                (ProjectCreateLocation::Machine, "after_confirmation")
            }
            _ => return refuse(ProjectCreateRefusal::Invalid),
        };
        if action["focus"]["activate"] != focus_policy {
            return refuse(ProjectCreateRefusal::Invalid);
        }
        let machine_hint = match &action["machine_hint"] {
            Value::Null => String::new(),
            Value::String(hint) if hint.chars().count() <= 60 => hint.clone(),
            _ => return refuse(ProjectCreateRefusal::Invalid),
        };
        let text = |field: &str| action[field].as_str().map(str::to_owned);
        // A machine request may leave the application kind open.
        let open_kind = location == ProjectCreateLocation::Machine && action["kind"].is_null();
        let (Some(name), Some(description), Some(kind), Some(subfolder), Some(expires_at)) = (
            text("name").map(|v| v.trim().to_owned()),
            Some(text("description").unwrap_or_default()),
            text("kind").or_else(|| open_kind.then(String::new)),
            text("subfolder").or_else(|| open_kind.then(String::new)),
            action["expires_at"].as_u64(),
        ) else {
            return refuse(ProjectCreateRefusal::Invalid);
        };
        let folder_matches = matches!(
            (kind.as_str(), subfolder.as_str()),
            ("web_app", "web-app") | ("native_app", "native-app") | ("", "")
        ) && (open_kind || !kind.is_empty());
        let team_id = match &action["team_id"] {
            Value::Null => None,
            Value::String(team) if uuid::Uuid::parse_str(team).is_ok() => Some(team.clone()),
            _ => return refuse(ProjectCreateRefusal::Invalid),
        };
        if name.is_empty()
            || name.chars().count() > MAX_NAME_CHARS
            || description.chars().count() > MAX_DESCRIPTION_CHARS
            || !folder_matches
        {
            return refuse(ProjectCreateRefusal::Invalid);
        }
        if expires_at <= now_s {
            return refuse(ProjectCreateRefusal::Expired);
        }
        Ok(Self {
            request_id: id.unwrap_or_default(),
            chat_id: chat_id.to_owned(),
            team_id,
            name,
            description,
            kind,
            subfolder,
            expires_at,
            location,
            machine_hint,
        })
    }
}

fn is_request_id(id: &str) -> bool {
    id.strip_prefix("project-create-request-")
        .is_some_and(|rest| uuid::Uuid::parse_str(rest).is_ok())
}

/// The default focus a new Project gets; mirrors the rule `encode_create`
/// applies when the caller supplies none ("Work on <name>").
pub(super) fn default_focus(name: &str) -> ProjectDefaultFocus {
    ProjectDefaultFocus {
        focus_id: uuid::Uuid::new_v4().to_string(),
        name: format!("Work on {name}"),
        instructions: format!(
            "Help with work in {name}. Follow the user's instructions and the Project's connected source guidance."
        ),
        source: "generated".into(),
    }
}

/// What the shells render as the "Created project" card.
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct CreatedProjectRecord {
    /// Request that produced the Project.
    pub request_id: String,
    /// Chat the Project was created for.
    pub chat_id: String,
    /// New Project id.
    pub project_id: String,
    /// Default focus id that was activated.
    pub focus_id: String,
    /// Decrypted Project name.
    pub name: String,
    /// `web_app` or `native_app`.
    pub kind: String,
    /// Folder the application's files go to.
    pub subfolder: String,
    /// Team the Project belongs to, `None` for a personal Project.
    pub team_id: Option<String>,
    /// Always true while the Project exists; the card offers Undo.
    pub undo_available: bool,
}

impl Projects<'_> {
    /// Create the Project for `request` and activate its default focus.
    ///
    /// Order follows the contract: encrypted `POST /v1/projects` with write mode
    /// `apply_and_show`, then `POST .../focus/activate` without an activation
    /// request id. If activation fails the new Project is deleted again so no
    /// half-created Project remains; the caller reports `failed` either way.
    ///
    /// # Errors
    /// Any transport/crypto error of the two calls. A rollback failure is
    /// returned as the original error after the attempt.
    pub async fn create_for_request(
        &mut self,
        request: &ProjectCreateRequest,
    ) -> Result<CreatedProjectRecord> {
        let focus = default_focus(&request.name);
        let input = ProjectCreate {
            name: request.name.clone(),
            description: request.description.clone(),
            write_mode: Some(ProjectWriteMode::ApplyAndShow),
            default_focus: Some(focus.clone()),
            ..Default::default()
        };
        let (mut payload, key) = self.prepare_create(input).await?;
        let project_id = string(&payload, "project_id")?.to_owned();
        // The creation record rides in the encrypted settings next to the focus,
        // so the server learns nothing new and a reload can find it again.
        let settings = json!({
            "default_focus": focus,
            "creation": {
                "origin": "assistant_request",
                "request_id": request.request_id,
                "chat_id": request.chat_id,
                "kind": request.kind,
                "subfolder": request.subfolder,
            },
        });
        payload["encrypted_settings"] = json!(crypto::server_fields::encrypt_text(
            &serde_json::to_string(&settings)?,
            &key,
            &[]
        )?);
        let route = self.path("/v1/projects", &[]);
        let data = self
            .backend
            .request(Method::POST, &route, Some(payload), None)
            .await?;
        if data["project"]["project_id"] != project_id {
            return Err(Error::Forbidden);
        }
        let activation = self
            .activate_exact_focus(&project_id, &request.chat_id, &focus)
            .await;
        if let Err(error) = activation {
            // Best effort: the original error is what the report carries.
            let _ = self.delete(&project_id, true).await;
            return Err(error);
        }
        Ok(CreatedProjectRecord {
            request_id: request.request_id.clone(),
            chat_id: request.chat_id.clone(),
            project_id,
            focus_id: focus.focus_id,
            name: request.name.clone(),
            kind: request.kind.clone(),
            subfolder: request.subfolder.clone(),
            team_id: request.team_id.clone(),
            undo_available: true,
        })
    }

    async fn activate_exact_focus(
        &mut self,
        project_id: &str,
        chat_id: &str,
        focus: &ProjectDefaultFocus,
    ) -> Result<()> {
        let route = self.path(&format!("/v1/projects/{project_id}/focus/activate"), &[]);
        let data = self
            .backend
            .request(
                Method::POST,
                &route,
                Some(json!({
                    "chat_id": chat_id,
                    "focus_id": focus.focus_id,
                    "instruction": focus.instructions,
                })),
                None,
            )
            .await?;
        data.get("focus")
            .filter(|f| f.is_object())
            .map(|_| ())
            .ok_or(Error::Protocol)
    }

    /// The assistant-created Project of `chat_id`, if its focus is still active.
    ///
    /// Reads the chat's active focus binding, then the Project's encrypted
    /// settings; only a Project whose `creation.chat_id` is this chat counts.
    ///
    /// # Errors
    /// Transport or decryption failures. A chat without such a Project is `Ok(None)`.
    pub async fn created_for_chat(
        &mut self,
        chat_id: &str,
    ) -> Result<Option<CreatedProjectRecord>> {
        let focus = self.active_focus(chat_id).await?;
        let Some(project_id) = focus["project_id"].as_str().map(str::to_owned) else {
            return Ok(None);
        };
        let settings = self.settings(&project_id).await?;
        let creation = &settings["settings"]["creation"];
        if !is_creation_record(creation, chat_id) {
            return Ok(None);
        }
        let project = self.show(&project_id).await?;
        Ok(Some(CreatedProjectRecord {
            request_id: creation["request_id"]
                .as_str()
                .unwrap_or_default()
                .to_owned(),
            chat_id: chat_id.to_owned(),
            project_id,
            focus_id: settings["default_focus"]["focus_id"]
                .as_str()
                .unwrap_or_default()
                .to_owned(),
            name: project["name"].as_str().unwrap_or_default().to_owned(),
            kind: creation["kind"].as_str().unwrap_or_default().to_owned(),
            subfolder: creation["subfolder"]
                .as_str()
                .unwrap_or_default()
                .to_owned(),
            team_id: self.filters.team_id.clone(),
            undo_available: true,
        }))
    }

    /// Undo an assistant-created Project: deactivate the chat focus, then delete
    /// the Project (contract section 7). The chat and its embeds stay intact.
    ///
    /// # Errors
    /// `Error::Forbidden` when the Project is not the creation record of
    /// `chat_id` (this never deletes a Project the assistant did not create for
    /// the chat); transport errors of either call.
    pub async fn undo_created(&mut self, chat_id: &str) -> Result<CreatedProjectRecord> {
        let record = self
            .created_for_chat(chat_id)
            .await?
            .ok_or(Error::Forbidden)?;
        self.deactivate_focus(chat_id).await?;
        self.delete(&record.project_id, true).await?;
        Ok(record)
    }
}
