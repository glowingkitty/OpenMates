//! Personal and Team Project authoring with client-side encryption and scopes.
use super::*;
use serde::{Deserialize, Serialize};
#[derive(Clone, Default, Serialize, Deserialize)]
#[serde(default, deny_unknown_fields)]
pub struct ProjectFilters {
    pub personal: bool,
    pub team_id: Option<String>,
    pub include_archived: Option<bool>,
}
#[derive(Clone, Copy, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum ProjectWriteMode {
    ApplyAndShow,
    AlwaysAsk,
}
#[derive(Clone, Copy, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum ProjectFocusActivationPolicy {
    Delayed,
    Immediate,
    Approval,
}
#[derive(Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct ProjectDefaultFocus {
    pub focus_id: String,
    pub name: String,
    pub instructions: String,
    pub source: String,
}
#[derive(Clone, Default, Serialize, Deserialize)]
#[serde(default, deny_unknown_fields)]
pub struct ProjectCreate {
    pub name: String,
    pub description: String,
    pub icon: Option<String>,
    pub color: Option<String>,
    pub slug: Option<String>,
    pub pinned: bool,
    pub project_id: Option<String>,
    pub write_mode: Option<ProjectWriteMode>,
    pub chat_organization_only: bool,
    pub default_focus: Option<ProjectDefaultFocus>,
}
#[derive(Clone, Default, Serialize, Deserialize)]
#[serde(default, deny_unknown_fields)]
pub struct ProjectPatch {
    pub name: Option<String>,
    pub description: Option<String>,
    pub icon: Option<String>,
    pub color: Option<String>,
    pub slug: Option<String>,
    pub pinned: Option<bool>,
    pub archived: Option<bool>,
    pub last_opened_at: Option<u64>,
}
#[derive(Clone, Default, Serialize, Deserialize)]
#[serde(default, deny_unknown_fields)]
pub struct ProjectSettingsPatch {
    pub write_mode: Option<ProjectWriteMode>,
    pub auto_selection: Option<bool>,
    pub focus_activation_policy: Option<ProjectFocusActivationPolicy>,
    pub default_focus: Option<ProjectDefaultFocus>,
}
mod ask;
pub use ask::*;
mod focus;
mod items;
mod workflow_files;
pub use workflow_files::WorkflowFileSaveStatus;
mod source_host;
mod source_read;
pub use source_read::ProjectSourcesDecodedNames;
mod sources;
mod task_sync;
pub use items::{ProjectItemType, ProjectLink};
pub use sources::*;
pub(super) struct ResolvedProject {
    pub(super) raw: Value,
    pub(super) public: Value,
    pub(super) key: Key,
}
pub struct Projects<'a> {
    backend: Backend<'a>,
    filters: ProjectFilters,
    operation_cancel: tokio_util::sync::CancellationToken,
}
impl<'a> Projects<'a> {
    pub(crate) fn cookie(
        client: &'a mut Client,
        team: Option<String>,
        operation_cancel: tokio_util::sync::CancellationToken,
    ) -> Self {
        Self {
            backend: Backend::Cookie(client),
            filters: ProjectFilters {
                team_id: team,
                ..Default::default()
            },
            operation_cancel,
        }
    }
    pub(crate) fn api_key(
        client: &'a mut OpenMates,
        operation_cancel: tokio_util::sync::CancellationToken,
    ) -> Self {
        Self {
            backend: Backend::ApiKey(client),
            filters: Default::default(),
            operation_cancel,
        }
    }
    pub fn with_filters(mut self, mut filters: ProjectFilters) -> Self {
        if !filters.personal && filters.team_id.is_none() {
            filters.team_id = self.filters.team_id.clone();
        }
        self.filters = filters;
        self
    }
    fn scope(&self) -> Result<()> {
        if self.filters.personal && self.filters.team_id.is_some() {
            return Err(Error::Invalid("Choose Personal or a Team, not both."));
        }
        if let Some(team) = &self.filters.team_id {
            uuid(team)?;
        }
        Ok(())
    }
    fn path(&self, route: &str, params: &[(String, String)]) -> String {
        path(route, self.filters.team_id.as_deref(), params)
    }
    async fn row_key(&mut self, raw: &Value) -> Result<Key> {
        self.scope()?;
        let id = string(raw, "project_id")?;
        uuid(id)?;
        if self.filters.team_id.is_none() {
            if raw["hashed_team_id"]
                .as_str()
                .is_some_and(|s| !s.is_empty())
                || raw["key_wrappers"]
                    .as_array()
                    .is_some_and(|rows| rows.iter().any(|r| r["key_type"] == "team"))
            {
                return Err(Error::Forbidden);
            }
            if let Backend::ApiKey(client) = &mut self.backend
                && let Some(key) = client.project_grant_key(id).await?
            {
                return Ok(key);
            }
        }
        let wrapping = self
            .backend
            .wrapping(self.filters.team_id.as_deref())
            .await?;
        project_key(raw, &wrapping, self.filters.team_id.as_deref())
    }
    pub(super) async fn resolve(&mut self, id: &str) -> Result<ResolvedProject> {
        self.scope()?;
        if uuid::Uuid::parse_str(id).is_ok() {
            let path = self.path(&format!("/v1/projects/{id}"), &[]);
            let response = self.backend.request(Method::GET, &path, None, None).await?;
            let raw = response["project"].clone();
            if raw["project_id"] != id {
                return Err(Error::Forbidden);
            }
            let key = self.row_key(&raw).await?;
            return decode(raw, key);
        }
        let all = self.list_resolved(Some(true)).await?;
        let slug = crypto::normalize_object_slug(id).ok();
        let exact = all
            .iter()
            .enumerate()
            .filter(|(_, p)| {
                p.public["slug"].as_str() == slug.as_deref()
                    || p.public["name"].as_str() == Some(id)
                    || id.len() >= 8
                        && p.public["project_id"]
                            .as_str()
                            .is_some_and(|s| s.starts_with(id))
            })
            .map(|(i, _)| i)
            .collect::<Vec<_>>();
        if exact.len() != 1 {
            return Err(Error::Invalid(
                "Project selector is missing or ambiguous; use its full ID.",
            ));
        }
        all.into_iter().nth(exact[0]).ok_or(Error::Protocol)
    }
    async fn list_resolved(&mut self, include: Option<bool>) -> Result<Vec<ResolvedProject>> {
        self.scope()?;
        let params = include
            .or(self.filters.include_archived)
            .map(|v| vec![("include_archived".into(), v.to_string())])
            .unwrap_or_default();
        let path = self.path("/v1/projects", &params);
        let data = self.backend.request(Method::GET, &path, None, None).await?;
        let rows = data["projects"].as_array().ok_or(Error::Protocol)?;
        let mut result = vec![];
        let mut ids = std::collections::BTreeSet::new();
        for row in rows {
            if !ids.insert(string(row, "project_id")?.to_owned()) {
                return Err(Error::Protocol);
            }
            let key = self.row_key(row).await?;
            result.push(decode(row.clone(), key)?);
        }
        Ok(result)
    }
    pub async fn list(&mut self) -> Result<Vec<Value>> {
        Ok(self
            .list_resolved(None)
            .await?
            .into_iter()
            .map(|p| p.public)
            .collect())
    }
    pub(crate) async fn sdk_embed_link_context(&mut self, selector: &str) -> Result<(String, Key)> {
        let project = self.resolve(selector).await?;
        Ok((string(&project.raw, "project_id")?.to_owned(), project.key))
    }
    pub async fn show(&mut self, id: &str) -> Result<Value> {
        Ok(self.resolve(id).await?.public)
    }
    async fn prepare_create(&mut self, input: ProjectCreate) -> Result<(Value, Key)> {
        self.scope()?;
        let wrapping = self
            .backend
            .wrapping(self.filters.team_id.as_deref())
            .await?;
        let key = crypto::random_key();
        let payload = encode_create(&input, &key, &wrapping, self.filters.team_id.as_deref())?;
        Ok((payload, key))
    }
    pub async fn create(&mut self, input: ProjectCreate) -> Result<Value> {
        let (payload, key) = self.prepare_create(input).await?;
        let expected = string(&payload, "project_id")?.to_owned();
        let route = self.path("/v1/projects", &[]);
        let data = self
            .backend
            .request(Method::POST, &route, Some(payload), None)
            .await?;
        if data["project"]["project_id"] != expected {
            return Err(Error::Forbidden);
        }
        let mut public = decode(data["project"].clone(), key)?.public;
        if let Some(history) = data.get("history") {
            public["history"] = history.clone();
        }
        Ok(public)
    }
    async fn prepare_patch(
        &mut self,
        id: &str,
        input: ProjectPatch,
    ) -> Result<(ResolvedProject, Value)> {
        let project = self.resolve(id).await?;
        let wrapping = if input.slug.is_some() {
            Some(
                self.backend
                    .wrapping(self.filters.team_id.as_deref())
                    .await?,
            )
        } else {
            None
        };
        let patch = encode_patch(&project, &input, wrapping.as_deref())?;
        Ok((project, patch))
    }
    pub async fn update(&mut self, id: &str, input: ProjectPatch) -> Result<Value> {
        let (project, patch) = self.prepare_patch(id, input).await?;
        let route = self.path(
            &format!("/v1/projects/{}", string(&project.raw, "project_id")?),
            &[],
        );
        let data = self
            .backend
            .request(Method::PATCH, &route, Some(patch), None)
            .await?;
        if data["project"]["project_id"] != project.raw["project_id"] {
            return Err(Error::Forbidden);
        }
        let mut public = decode(data["project"].clone(), project.key)?.public;
        if let Some(history) = data.get("history") {
            public["history"] = history.clone();
        }
        Ok(public)
    }
    pub async fn edit(&mut self, id: &str, input: ProjectPatch) -> Result<Value> {
        self.update(id, input).await
    }
    pub async fn open(&mut self, id: &str) -> Result<Value> {
        self.update(
            id,
            ProjectPatch {
                last_opened_at: Some(now()),
                ..Default::default()
            },
        )
        .await
    }
    pub async fn archive(&mut self, id: &str) -> Result<Value> {
        self.update(
            id,
            ProjectPatch {
                archived: Some(true),
                ..Default::default()
            },
        )
        .await
    }
    pub async fn unarchive(&mut self, id: &str) -> Result<Value> {
        self.update(
            id,
            ProjectPatch {
                archived: Some(false),
                ..Default::default()
            },
        )
        .await
    }
    pub async fn delete(&mut self, id: &str, confirmed: bool) -> Result<Value> {
        if !confirmed {
            return Err(Error::Invalid(
                "Explicit Project deletion confirmation is required.",
            ));
        }
        let project = self.resolve(id).await?;
        let id = string(&project.raw, "project_id")?;
        let route = self.path(
            &format!("/v1/projects/{id}"),
            &[("confirmation_project_id".into(), id.into())],
        );
        let result = self
            .backend
            .request(Method::DELETE, &route, None, None)
            .await?;
        if result["deleted"] != true {
            return Err(Error::Protocol);
        }
        Ok(result)
    }
    pub async fn history(&mut self, id: &str, limit: Option<u16>) -> Result<Vec<Value>> {
        let limit = limit.unwrap_or(50);
        if limit == 0 || limit > 500 {
            return Err(Error::Invalid("History limit must be 1–500."));
        }
        let project = self.resolve(id).await?;
        let route = self.path(
            &format!(
                "/v1/projects/{}/history",
                string(&project.raw, "project_id")?
            ),
            &[("limit".into(), limit.to_string())],
        );
        let value = self
            .backend
            .request(Method::GET, &route, None, None)
            .await?;
        Ok(value["entries"].as_array().ok_or(Error::Protocol)?.clone())
    }
    pub async fn restore(&mut self, id: &str, entry: &str, state: RestoreState) -> Result<Value> {
        segment(entry)?;
        let project = self.resolve(id).await?;
        let route = self.path(
            &format!(
                "/v1/projects/{}/restore",
                string(&project.raw, "project_id")?
            ),
            &[],
        );
        self.backend
            .request(
                Method::POST,
                &route,
                Some(json!({"entry_id":entry,"state":state})),
                None,
            )
            .await
    }
    pub async fn settings(&mut self, id: &str) -> Result<Value> {
        let project = self.resolve(id).await?;
        let route = self.path(
            &format!(
                "/v1/projects/{}/settings",
                string(&project.raw, "project_id")?
            ),
            &[],
        );
        let data = self
            .backend
            .request(Method::GET, &route, None, None)
            .await?;
        decode_settings(&data["settings"], &project.key)
    }
    pub async fn update_settings(
        &mut self,
        id: &str,
        input: ProjectSettingsPatch,
    ) -> Result<Value> {
        let project = self.resolve(id).await?;
        let id = string(&project.raw, "project_id")?;
        let route = self.path(&format!("/v1/projects/{id}/settings"), &[]);
        let mut payload = json!({"updated_at":now()});
        if let Some(mode) = input.write_mode {
            payload["write_mode"] = json!(mode);
        }
        if let Some(selection) = input.auto_selection {
            payload["auto_selection"] = json!(selection);
        }
        if let Some(policy) = input.focus_activation_policy {
            payload["focus_activation_policy"] = json!(policy);
        }
        if let Some(focus) = input.default_focus {
            validate_focus(&focus)?;
            let data = self
                .backend
                .request(Method::GET, &route, None, None)
                .await?;
            let current = decode_settings(&data["settings"], &project.key)?;
            let mut settings = current["settings"].clone();
            if !settings.is_object() {
                return Err(Error::Protocol);
            }
            settings["default_focus"] = json!(focus);
            payload["default_focus_id"] = json!(focus.focus_id);
            payload["encrypted_settings"] = json!(crypto::server_fields::encrypt_text(
                &serde_json::to_string(&settings)?,
                &project.key
            , &[])?);
        }
        if payload.as_object().ok_or(Error::Protocol)?.len() == 1 {
            return Err(Error::Invalid("Choose at least one Project setting."));
        }
        let data = self
            .backend
            .request(Method::PATCH, &route, Some(payload), None)
            .await?;
        decode_settings(&data["settings"], &project.key)
    }
}
fn project_key(raw: &Value, wrapping: &[u8; 32], team: Option<&str>) -> Result<Key> {
    let encrypted = if let Some(team) = team {
        if raw["hashed_team_id"]
            .as_str()
            .is_some_and(|s| s != hash(team))
        {
            return Err(Error::Forbidden);
        }
        let rows = raw["key_wrappers"].as_array().ok_or(Error::Forbidden)?;
        let rows = rows
            .iter()
            .filter(|row| {
                row["key_type"] == "team"
                    && row["hashed_team_id"] == hash(team)
                    && row["team_key_epoch"] == 1
            })
            .collect::<Vec<_>>();
        if rows.len() != 1 {
            return Err(Error::Forbidden);
        }
        string(rows[0], "encrypted_project_key")?
    } else {
        if raw["hashed_team_id"]
            .as_str()
            .is_some_and(|s| !s.is_empty())
            || raw["key_wrappers"]
                .as_array()
                .is_some_and(|rows| rows.iter().any(|w| w["key_type"] == "team"))
        {
            return Err(Error::Forbidden);
        }
        string(raw, "encrypted_project_key")?
    };
    key_bytes(&crypto::decrypt_bytes(encrypted, wrapping)?)
}
fn decode(raw: Value, key: Key) -> Result<ResolvedProject> {
    uuid(string(&raw, "project_id")?)?;
    let mut public = json!({});
    public["short_id"] = json!(&string(&raw, "project_id")?[..8]);
    for field in [
        "project_id",
        "pinned",
        "archived",
        "version",
        "created_at",
        "updated_at",
        "last_opened_at",
        "mutation_permissions",
    ] {
        public[field] = raw[field].clone();
    }
    for field in ["name", "description", "icon", "color", "slug"] {
        public[field] = json!(super::task_crypto::text(
            &raw,
            &format!("encrypted_{field}"),
            &key
        )?);
    }
    Ok(ResolvedProject { raw, public, key })
}
fn validate_focus(focus: &ProjectDefaultFocus) -> Result<()> {
    uuid(&focus.focus_id)?;
    if focus.name.trim().is_empty()
        || focus.instructions.trim().is_empty()
        || focus.name.len() > 10_000
        || focus.instructions.len() > 200_000
        || focus.source.is_empty()
        || focus.source.len() > 512
    {
        return Err(Error::Invalid(
            "Project focus requires a name, instructions and source.",
        ));
    }
    Ok(())
}
fn encode_create(
    input: &ProjectCreate,
    key: &[u8; 32],
    wrapping: &[u8; 32],
    team: Option<&str>,
) -> Result<Value> {
    if input.name.trim().is_empty()
        || input.name.len() > 100_000
        || input.description.len() > 1_000_000
    {
        return Err(Error::Invalid(
            "Project name is required and private text must fit the supported limits.",
        ));
    }
    if input.write_mode.is_none() && !input.chat_organization_only {
        return Err(Error::Invalid("Choose an explicit Project write mode."));
    }
    let id = input
        .project_id
        .clone()
        .unwrap_or_else(|| uuid::Uuid::new_v4().to_string());
    uuid(&id)?;
    let name = input.name.trim();
    let focus=input.default_focus.clone().unwrap_or_else(||ProjectDefaultFocus{focus_id:uuid::Uuid::new_v4().to_string(),name:format!("Work on {name}"),instructions:format!("Help with work in {name}. Follow the user's instructions and the Project's connected source guidance."),source:"generated".into()});
    validate_focus(&focus)?;
    let slug = crypto::normalize_object_slug(input.slug.as_deref().unwrap_or(name))?;
    let wrapped = crypto::server_fields::encrypt_bytes(key, wrapping, &[])?;
    let mut value = json!({"project_id":id,"encrypted_project_key":if team.is_none(){json!(wrapped)}else{Value::Null},"encrypted_name":crypto::server_fields::encrypt_text(name,key, &[])?,"encrypted_description":crypto::server_fields::encrypt_text(&input.description,key, &[])?,"encrypted_icon":crypto::server_fields::encrypt_text(input.icon.as_deref().unwrap_or("folder"),key, &[])?,"encrypted_color":crypto::server_fields::encrypt_text(input.color.as_deref().unwrap_or("default"),key, &[])?,"encrypted_slug":crypto::server_fields::encrypt_text(&slug,key, &[])?,"slug_lookup_hash":crypto::object_slug_lookup_hash(&slug,wrapping)?,"pinned":input.pinned,"created_at":now(),"updated_at":now(),"last_opened_at":now(),"write_mode":input.write_mode,"chat_organization_only":input.chat_organization_only,"default_focus_id":focus.focus_id,"encrypted_settings":crypto::server_fields::encrypt_text(&serde_json::to_string(&json!({"default_focus":focus}))?,key, &[])?,"key_wrappers":[]});
    if let Some(team) = team {
        value["key_wrappers"] = json!([{"key_type":"team","hashed_team_id":hash(team),"team_key_epoch":1,"wrapper_version":1,"encrypted_project_key":wrapped,"created_at":now()}]);
    }
    Ok(value)
}
fn encode_patch(
    project: &ResolvedProject,
    input: &ProjectPatch,
    wrapping: Option<&[u8; 32]>,
) -> Result<Value> {
    let mut payload = json!({"updated_at":now()});
    if let Some(version) = project.raw["version"].as_u64() {
        payload["version"] = json!(version);
    }
    for (field, text) in [
        ("name", &input.name),
        ("description", &input.description),
        ("icon", &input.icon),
        ("color", &input.color),
    ] {
        if let Some(text) = text {
            if text.len() > 1_000_000 || field == "name" && text.trim().is_empty() {
                return Err(Error::Invalid(
                    "Invalid Project name or private text length.",
                ));
            }
            payload[format!("encrypted_{field}")] =
                json!(crypto::server_fields::encrypt_text(text, &project.key, &[])?);
        }
    }
    if let Some(slug) = &input.slug {
        let slug = crypto::normalize_object_slug(slug)?;
        payload["encrypted_slug"] = json!(crypto::server_fields::encrypt_text(&slug, &project.key, &[])?);
        payload["slug_lookup_hash"] = json!(crypto::object_slug_lookup_hash(
            &slug,
            wrapping.ok_or(Error::Crypto)?
        )?);
    }
    if let Some(pinned) = input.pinned {
        payload["pinned"] = json!(pinned);
    }
    if let Some(archived) = input.archived {
        payload["archived"] = json!(archived);
    }
    if let Some(opened) = input.last_opened_at {
        payload["last_opened_at"] = json!(opened);
    }
    Ok(payload)
}
fn decode_settings(raw: &Value, key: &[u8; 32]) -> Result<Value> {
    if !raw.is_object() {
        return Err(Error::Protocol);
    }
    let mut output = json!({});
    for (field, value) in raw.as_object().ok_or(Error::Protocol)? {
        if !field.starts_with("encrypted_") && !field.starts_with("hashed_") {
            output[field] = value.clone();
        }
    }
    let settings = task_crypto::text(raw, "encrypted_settings", key)?;
    let settings = if settings.is_empty() {
        json!({})
    } else {
        serde_json::from_str::<Value>(&settings).map_err(|_| Error::Crypto)?
    };
    if !settings.is_object() {
        return Err(Error::Protocol);
    }
    if let Some(expected) = raw["default_focus_id_hash"].as_str() {
        let focus: ProjectDefaultFocus = serde_json::from_value(settings["default_focus"].clone())
            .map_err(|_| Error::Protocol)?;
        validate_focus(&focus)?;
        if hash(&focus.focus_id) != expected {
            return Err(Error::Forbidden);
        }
    }
    output["default_focus"] = settings["default_focus"].clone();
    output["settings"] = settings;
    Ok(output)
}
fn segment(id: &str) -> Result<String> {
    if id.is_empty() || id.len() > 512 || id.chars().any(char::is_control) {
        return Err(Error::Invalid("Invalid Project history entry ID."));
    }
    Ok(url::form_urlencoded::byte_serialize(id.as_bytes()).collect())
}

#[cfg(test)]
mod tests;

#[cfg(all(test,not(target_arch="wasm32")))]
mod field_interop_tests {
    use super::*;
    use super::super::task_crypto::field_interop_support::{case,assert_web};
    #[test]
    fn actual_project_create_patch_and_team_wrapper_read_in_web_legacy_decoders(){
        let master=[7;32];let key=[9;32];
        let input=ProjectCreate{name:"Synthetic Project ✓".into(),description:"Private project".into(),write_mode:Some(ProjectWriteMode::AlwaysAsk),..Default::default()};
        let created=encode_create(&input,&key,&master,None).unwrap();
        let project=ResolvedProject{raw:created.clone(),public:json!({}),key:zeroize::Zeroizing::new(key)};
        let patch=encode_patch(&project,&ProjectPatch{name:Some("Updated Project 界".into()),description:Some("".into()),..Default::default()},Some(&master)).unwrap();
        let team=encode_create(&input,&key,&master,Some("11111111-1111-4111-8111-111111111111")).unwrap();
        assert!(team["encrypted_project_key"].is_null());
        assert_web(vec![case("project-key","master-binary",created["encrypted_project_key"].as_str().unwrap(),&master,&key,""),case("project-team-key","object-binary",team["key_wrappers"][0]["encrypted_project_key"].as_str().unwrap(),&master,&key,""),case("project-name","object-text",created["encrypted_name"].as_str().unwrap(),&key,input.name.as_bytes(),""),case("project-patch-name","object-text",patch["encrypted_name"].as_str().unwrap(),&key,"Updated Project 界".as_bytes(),""),case("project-empty-description","object-text",patch["encrypted_description"].as_str().unwrap(),&key,b"","")]);
    }
}
