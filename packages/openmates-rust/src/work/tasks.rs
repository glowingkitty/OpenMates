//! Typed Task API and persistent-delivery preparation shared by both transports.
use super::*;
use serde::{Deserialize, Serialize};
use std::collections::BTreeSet;
use task_crypto::{Resolved, decrypt, encrypt_create, encrypt_patch};
mod ai_jobs;
#[derive(Clone, Default, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct ExternalChat {
    pub provider: String,
    pub id: String,
    #[serde(default)]
    pub title: String,
}
#[derive(Clone, Default, Serialize, Deserialize)]
#[serde(default, deny_unknown_fields)]
pub struct TaskFilters {
    pub team_id: Option<String>,
    pub personal: bool,
    pub status: Option<String>,
    pub chat_id: Option<String>,
    pub project_id: Option<String>,
    pub plan_id: Option<String>,
    #[serde(alias = "tags")]
    pub labels: Vec<String>,
    pub external_chat: Option<ExternalChat>,
    pub priority: Option<u8>,
    pub limit: Option<u16>,
}
#[derive(Clone, Default, Serialize, Deserialize)]
#[serde(default, deny_unknown_fields)]
pub struct TaskCreate {
    pub title: String,
    pub description: String,
    pub slug: Option<String>,
    pub task_id: Option<String>,
    pub assign: Option<String>,
    #[serde(alias = "tags")]
    pub labels: Vec<String>,
    pub status: Option<String>,
    pub priority: Option<u8>,
    pub due_at: Option<i64>,
    #[serde(alias = "chat_id")]
    pub primary_chat_id: Option<String>,
    #[serde(alias = "project_ids")]
    pub linked_project_ids: Vec<String>,
    pub plan_id: Option<String>,
    pub external_chat: Option<ExternalChat>,
    pub position: Option<i64>,
}
fn nullable<'de, D, T>(deserializer: D) -> std::result::Result<Option<Option<T>>, D::Error>
where
    D: serde::Deserializer<'de>,
    T: Deserialize<'de>,
{
    Option::<T>::deserialize(deserializer).map(Some)
}
#[derive(Clone, Default, Serialize, Deserialize)]
#[serde(default, deny_unknown_fields)]
pub struct TaskPatch {
    pub title: Option<String>,
    pub description: Option<String>,
    pub slug: Option<String>,
    pub assign: Option<String>,
    pub status: Option<String>,
    pub priority: Option<u8>,
    #[serde(alias = "tags")]
    pub labels: Option<Vec<String>>,
    #[serde(alias = "add_tags")]
    pub add_labels: Vec<String>,
    #[serde(alias = "remove_tags")]
    pub remove_labels: Vec<String>,
    #[serde(alias = "chat_id", deserialize_with = "nullable")]
    pub primary_chat_id: Option<Option<String>>,
    #[serde(deserialize_with = "nullable")]
    pub plan_id: Option<Option<String>>,
    #[serde(deserialize_with = "nullable")]
    pub due_at: Option<Option<i64>>,
    #[serde(deserialize_with = "nullable")]
    pub external_chat: Option<Option<ExternalChat>>,
    #[serde(alias = "project_ids")]
    pub linked_project_ids: Option<Vec<String>>,
}
#[derive(Clone, Default, Serialize, Deserialize)]
#[serde(default, deny_unknown_fields)]
pub struct TaskActivityInput {
    pub message: String,
    pub entry_id: Option<String>,
    pub embed_refs: Vec<String>,
    pub embed_key_material: Option<String>,
    pub created_at: Option<u64>,
}
#[derive(Clone, Default)]
pub struct TaskCaller {
    pub codex_thread_id: Option<String>,
    pub as_assignee: bool,
}
#[derive(Clone, Copy, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum RestoreState {
    Before,
    After,
}
#[derive(Clone, Default, Serialize, Deserialize)]
#[serde(default, deny_unknown_fields)]
pub struct TaskMove {
    #[serde(skip_serializing_if = "Option::is_none")]
    pub before_task_id: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub after_task_id: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub status: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub position: Option<i64>,
}
#[derive(Clone, Copy, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum WorkKind {
    Task,
    Plan,
}
#[derive(Clone, Serialize, Deserialize)]
pub struct DependencyTarget {
    pub kind: WorkKind,
    pub id: String,
}
pub struct Tasks<'a> {
    pub(super) backend: Backend<'a>,
    pub(super) filters: TaskFilters,
    caller: TaskCaller,
}
impl<'a> Tasks<'a> {
    pub(crate) fn cookie(client: &'a mut Client, team: Option<String>) -> Self {
        Self {
            backend: Backend::Cookie(client),
            filters: TaskFilters {
                team_id: team,
                ..TaskFilters::default()
            },
            caller: TaskCaller::default(),
        }
    }
    pub(crate) fn api_key(client: &'a mut OpenMates) -> Self {
        Self {
            backend: Backend::ApiKey(client),
            filters: TaskFilters::default(),
            caller: TaskCaller::default(),
        }
    }
    pub fn with_filters(mut self, mut filters: TaskFilters) -> Self {
        if filters.team_id.is_none() && !filters.personal {
            filters.team_id = self.filters.team_id.clone();
        }
        self.filters = filters;
        self
    }
    pub fn with_caller(mut self, caller: TaskCaller) -> Self {
        self.caller = caller;
        self
    }
    pub async fn list(&mut self) -> Result<Vec<Value>> {
        if self.filters.limit.is_some_and(|n| n == 0 || n > 500) {
            return Err(Error::Invalid("Task list limit must be 1–500."));
        }
        let mut rows = self
            .list_resolved()
            .await?
            .into_iter()
            .map(|t| t.public)
            .collect::<Vec<_>>();
        if let Some(limit) = self.filters.limit {
            rows.truncate(usize::from(limit));
        }
        Ok(rows)
    }
    pub async fn show(&mut self, id: &str) -> Result<Value> {
        Ok(self.resolve(id).await?.public)
    }
    async fn keys(&mut self) -> Result<(Key, Key)> {
        if self.filters.personal && self.filters.team_id.is_some() {
            return Err(Error::Invalid("Choose Personal or a Team scope, not both."));
        }
        let master = self.backend.master().await?;
        let wrapping = self
            .backend
            .wrapping(self.filters.team_id.as_deref())
            .await?;
        Ok((master, wrapping))
    }
    fn scoped(&self, p: &str, params: &[(String, String)]) -> String {
        path(p, self.filters.team_id.as_deref(), params)
    }
    async fn list_resolved(&mut self) -> Result<Vec<Resolved>> {
        if let Some(project) = self.filters.project_id.clone() {
            self.filters.project_id = Some(self.reference("project", &project).await?);
        }
        if let Some(chat) = self.filters.chat_id.clone() {
            self.filters.chat_id = Some(self.reference("chat", &chat).await?);
        }
        if let Some(plan) = self.filters.plan_id.clone() {
            self.filters.plan_id = Some(self.reference("plan", &plan).await?);
        }
        let (master, wrapping) = self.keys().await?;
        let mut params = vec![
            ("limit".into(), "500".into()),
            ("paginate".into(), "true".into()),
        ];
        for (key, value) in [
            ("status", self.filters.status.clone()),
            ("chat_id", self.filters.chat_id.clone()),
            ("project_id", self.filters.project_id.clone()),
            ("plan_id", self.filters.plan_id.clone()),
        ] {
            if let Some(value) = value {
                params.push((key.into(), value));
            }
        }
        if let Some(priority) = self.filters.priority {
            if priority > 4 {
                return Err(Error::Invalid("Task priority must be 0–4."));
            }
            params.push(("priority".into(), priority.to_string()));
        }
        for hash in task_crypto::label_hashes(&wrapping, &self.filters.labels)? {
            params.push(("label_hash".into(), hash));
        }
        if let Some(external) = &self.filters.external_chat {
            params.push(("external_chat_provider".into(), external.provider.clone()));
            params.push((
                "external_chat_lookup_hash".into(),
                task_crypto::external_hash(&master, external)?,
            ));
        }
        let mut cursor: Option<String> = None;
        let mut result = vec![];
        let mut seen = BTreeSet::new();
        for _ in 0..100 {
            let mut query = params.clone();
            if let Some(cursor) = &cursor {
                query.push(("cursor".into(), cursor.clone()));
            }
            let p = self.scoped("/v1/user-tasks", &query);
            let data = self.backend.request(Method::GET, &p, None, None).await?;
            for raw in data["tasks"].as_array().ok_or(Error::Protocol)? {
                let id = string(raw, "task_id")?;
                if !seen.insert(id.to_owned()) {
                    return Err(Error::Protocol);
                }
                result.push(self.decode_row(raw.clone(), &master, &wrapping).await?);
            }
            let next = data["next_cursor"].as_str().filter(|s| !s.is_empty());
            if next.is_none() {
                if data["complete"] == false {
                    return Err(Error::Protocol);
                }
                if let Some(plan) = &self.filters.plan_id {
                    result.retain(|task| task.public["plan_id"] == *plan);
                }
                return Ok(result);
            }
            if next == cursor.as_deref() {
                return Err(Error::Protocol);
            }
            cursor = next.map(str::to_owned);
        }
        Err(Error::Invalid(
            "Task listing exceeds the supported pagination limit.",
        ))
    }
    async fn decode_row(
        &mut self,
        mut raw: Value,
        master: &[u8; 32],
        wrapping: &[u8; 32],
    ) -> Result<Resolved> {
        if raw["source"] != "workflow_run" {
            let team = self.filters.team_id.as_deref();
            let usable = raw["key_wrappers"].as_array().is_some_and(|rows| {
                rows.iter().any(|w| {
                    if let Some(team) = team {
                        w["key_type"] == "team"
                            && w["hashed_team_id"] == hash(team)
                            && w["team_key_epoch"] == 1
                    } else {
                        w["key_type"] == "master"
                    }
                })
            });
            let legacy = team.is_none()
                && raw["encrypted_task_key"]
                    .as_str()
                    .is_some_and(|s| !s.is_empty());
            if !usable && !legacy {
                let id = string(&raw, "task_id")?;
                uuid(id)?;
                let route = self.scoped(&format!("/v1/user-tasks/{id}/key-wrappers"), &[]);
                let response = self
                    .backend
                    .request(Method::GET, &route, None, None)
                    .await?;
                let rows = response["key_wrappers"].as_array().ok_or(Error::Protocol)?;
                if rows.len() > 50
                    || rows
                        .iter()
                        .any(|w| w["hashed_task_id"].as_str().is_some_and(|v| v != hash(id)))
                {
                    return Err(Error::Forbidden);
                }
                raw["key_wrappers"] = json!(rows);
            }
        }
        decrypt(raw, master, wrapping, self.filters.team_id.as_deref())
    }
    async fn resolve(&mut self, id: &str) -> Result<Resolved> {
        if uuid::Uuid::parse_str(id).is_ok()
            && matches!(self.backend, Backend::Cookie(_))
            && self.filters.status.is_none()
            && self.filters.chat_id.is_none()
            && self.filters.project_id.is_none()
            && self.filters.plan_id.is_none()
            && self.filters.labels.is_empty()
            && self.filters.external_chat.is_none()
            && self.filters.priority.is_none()
        {
            let (master, wrapping) = self.keys().await?;
            let p = self.scoped(&format!("/v1/user-tasks/{id}"), &[]);
            let data = self.backend.request(Method::GET, &p, None, None).await?;
            let row = data.get("task").ok_or(Error::Protocol)?;
            if string(row, "task_id")? != id {
                return Err(Error::Forbidden);
            }
            return self.decode_row(row.clone(), &master, &wrapping).await;
        }
        let all = self.list_resolved().await?;
        if let Some(index) = all.iter().position(|task| task.public["task_id"] == id) {
            return all.into_iter().nth(index).ok_or(Error::Protocol);
        }
        let normalized = crypto::normalize_object_slug(id).ok();
        let matches = all
            .iter()
            .enumerate()
            .filter(|(_, t)| {
                normalized
                    .as_deref()
                    .is_some_and(|n| t.public["slug"].as_str() == Some(n))
            })
            .map(|(i, _)| i)
            .collect::<Vec<_>>();
        let matches = if matches.is_empty() {
            all.iter()
                .enumerate()
                .filter(|(_, t)| {
                    t.public["short_id"]
                        .as_str()
                        .is_some_and(|s| s.eq_ignore_ascii_case(id))
                        || id.len() >= 8
                            && t.public["task_id"]
                                .as_str()
                                .is_some_and(|s| s.starts_with(id))
                })
                .map(|(i, _)| i)
                .collect::<Vec<_>>()
        } else {
            matches
        };
        if matches.len() != 1 {
            return Err(Error::Invalid(
                "Task selector is missing or ambiguous; use its full ID.",
            ));
        }
        all.into_iter().nth(matches[0]).ok_or(Error::Protocol)
    }
}

impl<'a> Tasks<'a> {
    async fn canonical_create(&mut self, mut input: TaskCreate) -> Result<TaskCreate> {
        for project in &mut input.linked_project_ids {
            *project = self.reference("project", project).await?;
        }
        if let Some(chat) = input.primary_chat_id.as_mut() {
            *chat = self.reference("chat", chat).await?;
        }
        if let Some(plan) = input.plan_id.as_mut() {
            *plan = self.reference("plan", plan).await?;
        }
        if let Some(thread) = &self.caller.codex_thread_id
            && input
                .external_chat
                .as_ref()
                .is_some_and(|c| c.provider != "codex" || c.id != *thread)
        {
            return Err(Error::Forbidden);
        }
        Ok(input)
    }
    async fn canonical_patch(&mut self, mut input: TaskPatch) -> Result<TaskPatch> {
        if let Some(projects) = &mut input.linked_project_ids {
            for project in projects {
                *project = self.reference("project", project).await?;
            }
        }
        if let Some(Some(chat)) = input.primary_chat_id.as_mut() {
            *chat = self.reference("chat", chat).await?;
        }
        if let Some(Some(plan)) = input.plan_id.as_mut() {
            *plan = self.reference("plan", plan).await?;
        }
        Ok(input)
    }
    pub(super) async fn reference(&mut self, kind: &str, query: &str) -> Result<String> {
        if uuid::Uuid::parse_str(query).is_ok() {
            return Ok(query.into());
        }
        let (master, wrapping) = self.keys().await?;
        let mut choices = vec![];
        match kind {
            "project" => {
                let p = self.scoped(
                    "/v1/projects",
                    &[("include_archived".into(), "true".into())],
                );
                let data = self.backend.request(Method::GET, &p, None, None).await?;
                for row in data["projects"].as_array().ok_or(Error::Protocol)? {
                    let encrypted = if let Some(team) = self.filters.team_id.as_deref() {
                        row["key_wrappers"]
                            .as_array()
                            .and_then(|rows| {
                                rows.iter().find(|w| {
                                    w["key_type"] == "team"
                                        && w["hashed_team_id"] == hash(team)
                                        && w["team_key_epoch"] == 1
                                })
                            })
                            .and_then(|w| w["encrypted_project_key"].as_str())
                            .ok_or(Error::Forbidden)?
                    } else {
                        string(row, "encrypted_project_key")?
                    };
                    let key = key_bytes(&crypto::decrypt_bytes(encrypted, &wrapping)?)?;
                    choices.push((
                        string(row, "project_id")?.to_owned(),
                        task_crypto::text(row, "encrypted_slug", &key)?,
                        task_crypto::text(row, "encrypted_name", &key)?,
                    ));
                }
            }
            "plan" => {
                if self.filters.team_id.is_some() {
                    return Err(Error::Forbidden);
                }
                let data = self
                    .backend
                    .request(Method::GET, "/v1/user-plans?active_only=false", None, None)
                    .await?;
                for row in data["plans"].as_array().ok_or(Error::Protocol)? {
                    let encrypted = row["key_wrappers"]
                        .as_array()
                        .and_then(|rows| rows.iter().find(|w| w["key_type"] == "master"))
                        .and_then(|w| w["encrypted_plan_key"].as_str())
                        .or_else(|| row["encrypted_plan_key"].as_str())
                        .ok_or(Error::Crypto)?;
                    let key = key_bytes(&crypto::decrypt_bytes(encrypted, &master)?)?;
                    choices.push((
                        string(row, "plan_id")?.into(),
                        task_crypto::text(row, "encrypted_slug", &key)?,
                        row["short_id"].as_str().unwrap_or("").into(),
                    ));
                }
            }
            "chat" => match &mut self.backend {
                Backend::Cookie(client) => {
                    if client.work_team()?.as_deref() != self.filters.team_id.as_deref() {
                        return Err(Error::Forbidden);
                    }
                    for item in client.list(crate::model::Workspace::Chats).await? {
                        choices.push((
                            item.id,
                            item.fields["slug"].as_str().unwrap_or("").into(),
                            item.title,
                        ));
                    }
                }
                Backend::ApiKey(client) => {
                    if self.filters.team_id.is_some() {
                        return Err(Error::Invalid(
                            "Use a full Team chat ID for this SDK context.",
                        ));
                    }
                    let data = client
                        .task_request(Method::GET, "/v1/sdk/chats?limit=0", None, false, None)
                        .await?;
                    for row in data["chats"].as_array().ok_or(Error::Protocol)? {
                        let key = key_bytes(&crypto::decrypt_bytes(
                            string(row, "encrypted_chat_key")?,
                            &master,
                        )?)?;
                        choices.push((
                            string(row, "id")?.into(),
                            task_crypto::text(row, "encrypted_slug", &key)?,
                            task_crypto::text(row, "encrypted_title", &key)?,
                        ));
                    }
                }
            },
            _ => return Err(Error::Protocol),
        }
        let mut indices = choices
            .iter()
            .enumerate()
            .filter(|(_, c)| query.len() >= 8 && c.0.starts_with(query))
            .map(|(i, _)| i)
            .collect::<Vec<_>>();
        if indices.is_empty() {
            let slug = crypto::normalize_object_slug(query).ok();
            indices = choices
                .iter()
                .enumerate()
                .filter(|(_, c)| slug.as_ref().is_some_and(|slug| slug == &c.1))
                .map(|(i, _)| i)
                .collect();
        }
        if indices.is_empty() {
            let normalized = query
                .split_whitespace()
                .collect::<Vec<_>>()
                .join(" ")
                .to_lowercase();
            indices = choices
                .iter()
                .enumerate()
                .filter(|(_, c)| {
                    c.2.split_whitespace()
                        .collect::<Vec<_>>()
                        .join(" ")
                        .to_lowercase()
                        == normalized
                })
                .map(|(i, _)| i)
                .collect();
        }
        if indices.len() != 1 {
            return Err(Error::Invalid(
                "Linked object selector is missing or ambiguous; use its full ID.",
            ));
        }
        Ok(choices[indices[0]].0.clone())
    }
    fn owner_headers(&self, task: Option<&Resolved>, creating: bool) -> Result<TaskHeaders> {
        let mut headers = TaskHeaders {
            assignee: self.caller.as_assignee,
            ..TaskHeaders::default()
        };
        if let Some(thread) = &self.caller.codex_thread_id {
            uuid(thread)?;
            if creating {
                if !matches!(self.backend, Backend::Cookie(_)) {
                    return Err(Error::Invalid(
                        "External Task creator provenance requires a paired first-party session.",
                    ));
                }
                headers.creator = true;
                headers.assignee = true;
            }
            if let Some(task) = task {
                let external = &task.public["external_chat"];
                if !external.is_null()
                    && (external["provider"] != "codex" || external["id"] != *thread)
                {
                    return Err(Error::Forbidden);
                }
                if !task.public["primary_chat_id"].is_null() {
                    return Err(Error::Forbidden);
                }
                headers.owner = task.raw["external_chat_lookup_hash"]
                    .as_str()
                    .map(str::to_owned);
            }
        }
        if self.caller.as_assignee
            && !creating
            && (self.caller.codex_thread_id.is_none()
                || task.is_none_or(|task| {
                    task.public["external_chat"]["provider"] != "codex"
                        || task.public["external_chat"]["id"].as_str()
                            != self.caller.codex_thread_id.as_deref()
                }))
        {
            return Err(Error::Forbidden);
        }
        if self.caller.as_assignee && matches!(self.backend, Backend::ApiKey(_)) {
            return Err(Error::Invalid(
                "Assignee activity requires the first-party paired-session surface.",
            ));
        }
        Ok(headers)
    }
    pub async fn create(&mut self, input: TaskCreate) -> Result<Value> {
        if input.assign.as_deref() == Some("openmates") {
            self.backend.verify_private_operation()?;
        }
        let input = self.canonical_create(input).await?;
        let (master, wrapping) = self.keys().await?;
        let mut payload =
            encrypt_create(&input, &master, &wrapping, self.filters.team_id.as_deref())?;
        let headers = self.owner_headers(None, input.external_chat.is_some())?;
        if payload["assignee_type"] == "openmates" {
            payload["plaintext_title"] = json!(input.title);
            payload["plaintext_description"] = json!(input.description);
        }
        let data = self
            .backend
            .request(
                Method::POST,
                "/v1/user-tasks",
                Some(payload),
                Some(&headers),
            )
            .await?;
        Ok(self
            .decode_row(data["task"].clone(), &master, &wrapping)
            .await?
            .public)
    }
    pub async fn update(&mut self, id: &str, input: TaskPatch) -> Result<Value> {
        let input = self.canonical_patch(input).await?;
        let mut target = id.to_owned();
        for attempt in 0..2 {
            let task = self.resolve(&target).await?;
            target = string(&task.raw, "task_id")?.to_owned();
            let headers = self.owner_headers(Some(&task), false)?;
            let (master, wrapping) = self.keys().await?;
            let mut payload = encrypt_patch(&task, &input, &master, &wrapping)?;
            self.project_wrappers(&task, &input, &mut payload, &wrapping)
                .await?;
            let p = self.scoped(
                &format!("/v1/user-tasks/{}", string(&task.raw, "task_id")?),
                &[],
            );
            match self
                .backend
                .request(Method::PATCH, &p, Some(payload), Some(&headers))
                .await
            {
                Ok(data) => {
                    return Ok(self
                        .decode_row(data["task"].clone(), &master, &wrapping)
                        .await?
                        .public);
                }
                Err(Error::Conflict) if attempt == 0 => {
                    crate::platform::time::sleep(std::time::Duration::from_secs(1)).await
                }
                Err(e) => return Err(e),
            }
        }
        Err(Error::Conflict)
    }
    pub async fn edit(&mut self, id: &str, input: TaskPatch) -> Result<Value> {
        self.update(id, input).await
    }
    pub async fn history(&mut self, id: &str, limit: Option<u16>) -> Result<Vec<Value>> {
        let task = self.resolve(id).await?;
        let p = self.scoped(
            &format!("/v1/user-tasks/{}/history", string(&task.raw, "task_id")?),
            &[(
                "limit".into(),
                limit.unwrap_or(50).clamp(1, 500).to_string(),
            )],
        );
        let data = self.backend.request(Method::GET, &p, None, None).await?;
        Ok(data["entries"].as_array().ok_or(Error::Protocol)?.clone())
    }
    pub async fn restore(&mut self, id: &str, entry: &str, state: RestoreState) -> Result<Value> {
        entry_id(entry)?;
        let task = self.resolve(id).await?;
        let headers = self.owner_headers(Some(&task), false)?;
        let p = self.scoped(
            &format!("/v1/user-tasks/{}/restore", string(&task.raw, "task_id")?),
            &[],
        );
        self.backend
            .request(
                Method::POST,
                &p,
                Some(json!({"entry_id":entry,"state":state})),
                Some(&headers),
            )
            .await
    }
    pub async fn list_activity(&mut self, id: &str, limit: Option<u16>) -> Result<Vec<Value>> {
        let task = self.resolve(id).await?;
        let id = string(&task.raw, "task_id")?;
        let mut cursor: Option<String> = None;
        let mut entries = vec![];
        let mut ids = BTreeSet::new();
        for _ in 0..100 {
            let mut query = vec![(
                "limit".into(),
                limit.unwrap_or(100).clamp(1, 200).to_string(),
            )];
            if let Some(cursor) = &cursor {
                query.push(("cursor".into(), cursor.clone()));
            }
            let p = self.scoped(&format!("/v1/user-tasks/{id}/activity"), &query);
            let data = self.backend.request(Method::GET, &p, None, None).await?;
            for row in data["entries"].as_array().ok_or(Error::Protocol)? {
                if !ids.insert(string(row, "entry_id")?.to_owned()) {
                    return Err(Error::Protocol);
                }
                entries.push(task_crypto::activity(&task, row)?);
            }
            let next = data["next_cursor"].as_str().filter(|s| !s.is_empty());
            if next.is_none() {
                return Ok(entries);
            }
            if next == cursor.as_deref() {
                return Err(Error::Protocol);
            }
            cursor = next.map(str::to_owned);
        }
        Err(Error::Invalid(
            "Task activity exceeds the supported pagination limit.",
        ))
    }
    pub async fn add_activity_comment(
        &mut self,
        id: &str,
        input: TaskActivityInput,
    ) -> Result<Value> {
        let task = self.resolve(id).await?;
        let headers = self.owner_headers(Some(&task), false)?;
        let payload = activity_input(&task, &input)?;
        let p = self.scoped(
            &format!("/v1/user-tasks/{}/activity", string(&task.raw, "task_id")?),
            &[],
        );
        let data = self
            .backend
            .request(Method::POST, &p, Some(payload), Some(&headers))
            .await?;
        task_crypto::activity(&task, &data["entry"])
    }
    pub async fn delete_activity_comment(&mut self, id: &str, entry: &str) -> Result<Value> {
        entry_id(entry)?;
        let entry = url::form_urlencoded::byte_serialize(entry.as_bytes()).collect::<String>();
        let task = self.resolve(id).await?;
        let headers = self.owner_headers(Some(&task), false)?;
        let p = self.scoped(
            &format!(
                "/v1/user-tasks/{}/activity/{entry}",
                string(&task.raw, "task_id")?
            ),
            &[],
        );
        let data = self
            .backend
            .request(Method::DELETE, &p, None, Some(&headers))
            .await?;
        task_crypto::activity(&task, &data["entry"])
    }
    pub async fn start(&mut self, id: &str) -> Result<Value> {
        self.backend.verify_private_operation()?;
        let task = self.resolve(id).await?;
        readonly(&task)?;
        if task.public["assignee_type"] == "external_ai" {
            return Err(Error::Invalid(
                "Resume an explicitly connected external Task; start runs OpenMates AI.",
            ));
        }
        let headers = self.owner_headers(Some(&task), false)?;
        let p = format!("/v1/user-tasks/{}/start-ai", string(&task.raw, "task_id")?);
        let payload = json!({"version":task.raw["version"],"primary_chat_id":task.public["primary_chat_id"],"linked_project_ids":task.public["linked_project_ids"],"plaintext_title":task.public["title"],"plaintext_description":task.public["description"],"plaintext_latest_instruction":task.public["latest_instruction"],"team_id":self.filters.team_id});
        let data = self
            .backend
            .request(Method::POST, &p, Some(payload), Some(&headers))
            .await?;
        let (master, wrapping) = self.keys().await?;
        Ok(self
            .decode_row(data["task"].clone(), &master, &wrapping)
            .await?
            .public)
    }
    pub async fn done(&mut self, id: &str) -> Result<Value> {
        self.action(id, "complete", json!({})).await
    }
    pub async fn complete(&mut self, id: &str) -> Result<Value> {
        self.done(id).await
    }
    pub async fn unblock(&mut self, id: &str) -> Result<Value> {
        self.action(id, "unblock", json!({})).await
    }
    pub async fn skip(&mut self, id: &str) -> Result<Value> {
        self.action(id, "skip", json!({})).await
    }
    pub async fn block(&mut self, id: &str, reason: &str, text: Option<&str>) -> Result<Value> {
        let reason = reason.trim().to_lowercase().replace([' ', '-'], "_");
        if ![
            "needs_user_input",
            "waiting_for_approval",
            "missing_credentials",
            "ambiguous_requirement",
            "external_dependency",
            "environment_unavailable",
            "verification_failed",
            "other",
        ]
        .contains(&reason.as_str())
        {
            return Err(Error::Invalid("Invalid Task blocked reason code."));
        }
        let task = self.resolve(id).await?;
        let mut payload = json!({"blocked_reason_code":reason});
        if let Some(text) = text {
            payload["encrypted_blocked_reason"] = json!(crypto::server_fields::encrypt_text(text, &task.key, &[])?);
        }
        self.action_resolved(task, "block", payload).await
    }
    async fn action(&mut self, id: &str, action: &str, payload: Value) -> Result<Value> {
        let task = self.resolve(id).await?;
        self.action_resolved(task, action, payload).await
    }
    async fn action_resolved(
        &mut self,
        task: Resolved,
        action: &str,
        mut payload: Value,
    ) -> Result<Value> {
        readonly(&task)?;
        let headers = self.owner_headers(Some(&task), false)?;
        payload["version"] = task.raw["version"].clone();
        payload["team_id"] = json!(self.filters.team_id);
        let p = format!("/v1/user-tasks/{}/{action}", string(&task.raw, "task_id")?);
        let data = self
            .backend
            .request(Method::POST, &p, Some(payload), Some(&headers))
            .await?;
        let (master, wrapping) = self.keys().await?;
        Ok(self
            .decode_row(data["task"].clone(), &master, &wrapping)
            .await?
            .public)
    }
    pub async fn delete(&mut self, id: &str, confirmed: bool) -> Result<Value> {
        if !confirmed {
            return Err(Error::Invalid(
                "Explicit Task deletion confirmation is required.",
            ));
        }
        let task = self.resolve(id).await?;
        deletable(&task)?;
        let headers = self.owner_headers(Some(&task), false)?;
        let p = self.scoped(
            &format!("/v1/user-tasks/{}", string(&task.raw, "task_id")?),
            &[(
                "version".into(),
                task.raw["version"].as_u64().unwrap_or(1).to_string(),
            )],
        );
        self.backend
            .request(Method::DELETE, &p, None, Some(&headers))
            .await
    }
    pub async fn reorder(&mut self, id: &str, mut movement: TaskMove) -> Result<Vec<Value>> {
        let task = self.resolve(id).await?;
        readonly(&task)?;
        let headers = self.owner_headers(Some(&task), false)?;
        if movement.before_task_id.is_some() && movement.after_task_id.is_some() {
            return Err(Error::Invalid(
                "Choose either a before or after Task anchor.",
            ));
        }
        for anchor in [&mut movement.before_task_id, &mut movement.after_task_id]
            .into_iter()
            .flatten()
        {
            *anchor = string(&self.resolve(anchor).await?.raw, "task_id")?.into();
        }
        let mut item = serde_json::to_value(movement)?;
        item["task_id"] = task.raw["task_id"].clone();
        item["version"] = task.raw["version"].clone();
        let data = self
            .backend
            .request(
                Method::POST,
                "/v1/user-tasks/reorder",
                Some(json!({"moves":[item],"team_id":self.filters.team_id})),
                Some(&headers),
            )
            .await?;
        let (master, wrapping) = self.keys().await?;
        let mut result = Vec::new();
        for row in data["tasks"].as_array().ok_or(Error::Protocol)? {
            result.push(
                self.decode_row(row.clone(), &master, &wrapping)
                    .await?
                    .public,
            );
        }
        Ok(result)
    }
    pub async fn add_to_project(&mut self, id: &str, project: &str) -> Result<Value> {
        let task = self.resolve(id).await?;
        let project = self.reference("project", project).await?;
        let mut projects = task.public["linked_project_ids"]
            .as_array()
            .ok_or(Error::Protocol)?
            .iter()
            .map(|v| v.as_str().ok_or(Error::Protocol).map(str::to_owned))
            .collect::<Result<Vec<_>>>()?;
        if !projects.contains(&project) {
            projects.push(project);
        }
        self.update(
            id,
            TaskPatch {
                linked_project_ids: Some(projects),
                ..TaskPatch::default()
            },
        )
        .await
    }
    pub async fn remove_from_project(&mut self, id: &str, project: &str) -> Result<Value> {
        let task = self.resolve(id).await?;
        let project = self.reference("project", project).await?;
        let projects = task.public["linked_project_ids"]
            .as_array()
            .ok_or(Error::Protocol)?
            .iter()
            .filter_map(Value::as_str)
            .filter(|id| *id != project)
            .map(str::to_owned)
            .collect();
        self.update(
            id,
            TaskPatch {
                linked_project_ids: Some(projects),
                ..TaskPatch::default()
            },
        )
        .await
    }
    pub async fn connect(&mut self, id: &str, external: ExternalChat) -> Result<Value> {
        let task = self.resolve(id).await?;
        readonly(&task)?;
        if let Some(thread) = &self.caller.codex_thread_id
            && (external.provider != "codex" || external.id != *thread)
        {
            return Err(Error::Forbidden);
        }
        if !task.public["primary_chat_id"].is_null() {
            return Err(Error::Forbidden);
        }
        if !task.public["external_chat"].is_null() {
            return if task.public["external_chat"]["provider"] == external.provider
                && task.public["external_chat"]["id"] == external.id
            {
                Ok(task.public)
            } else {
                Err(Error::Forbidden)
            };
        }
        self.update(
            id,
            TaskPatch {
                assign: Some("codex".into()),
                external_chat: Some(Some(external)),
                ..TaskPatch::default()
            },
        )
        .await
    }
    pub async fn release(&mut self, id: &str) -> Result<Value> {
        let task = self.resolve(id).await?;
        readonly(&task)?;
        let headers = self.owner_headers(Some(&task), false)?;
        let (master, wrapping) = self.keys().await?;
        let patch = TaskPatch {
            primary_chat_id: Some(None),
            external_chat: Some(None),
            status: if task.public["status"] == "in_progress" {
                Some("todo".into())
            } else {
                None
            },
            ..TaskPatch::default()
        };
        let mut payload = encrypt_patch(&task, &patch, &master, &wrapping)?;
        payload["queue_state"] = json!("none");
        payload["ai_execution_state"] = Value::Null;
        let p = self.scoped(
            &format!("/v1/user-tasks/{}", string(&task.raw, "task_id")?),
            &[],
        );
        let data = self
            .backend
            .request(Method::PATCH, &p, Some(payload), Some(&headers))
            .await?;
        Ok(self
            .decode_row(data["task"].clone(), &master, &wrapping)
            .await?
            .public)
    }
    pub fn dependencies(&mut self) -> TaskDependencies<'_, 'a> {
        TaskDependencies { tasks: self }
    }
}
fn readonly(task: &Resolved) -> Result<()> {
    if task.public["read_only"] == true {
        Err(Error::Invalid(
            "Workflow projection Tasks require their Workflow run controls.",
        ))
    } else {
        Ok(())
    }
}
fn activity_input(task: &Resolved, input: &TaskActivityInput) -> Result<Value> {
    readonly(task)?;
    if input.message.trim().is_empty()
        || input.message.len() > 1_000_000
        || input.embed_refs.len() > 100
    {
        return Err(Error::Invalid(
            "Task activity requires a nonempty bounded comment.",
        ));
    }
    let entry = input
        .entry_id
        .clone()
        .unwrap_or_else(|| uuid::Uuid::new_v4().to_string());
    entry_id(&entry)?;
    let id = string(&task.raw, "task_id")?;
    let mut payload = json!({"entry_id":entry,"encrypted_message":task_crypto::aad_encrypt(&input.message,&task.key,&format!("task_activity_comment:{id}:{entry}:v1"))?,"embed_refs":input.embed_refs,"created_at":input.created_at.unwrap_or_else(now)});
    if let Some(material) = &input.embed_key_material {
        payload["encrypted_embed_key_material"] = json!(task_crypto::aad_encrypt(
            material,
            &task.key,
            &format!("task_activity_embed_keys:{id}:{entry}:v1")
        )?);
    }
    Ok(payload)
}
pub struct TaskDependencies<'a, 'b> {
    tasks: &'a mut Tasks<'b>,
}
impl TaskDependencies<'_, '_> {
    pub async fn list(&mut self, source: &str) -> Result<Value> {
        let task = self.tasks.resolve(source).await?;
        let p = self.tasks.scoped(
            &format!(
                "/v1/user-tasks/{}/dependencies",
                string(&task.raw, "task_id")?
            ),
            &[],
        );
        self.tasks
            .backend
            .request(Method::GET, &p, None, None)
            .await
    }
    pub async fn add(&mut self, source: &str, target: &DependencyTarget) -> Result<Value> {
        let task = self.tasks.resolve(source).await?;
        let headers = self.tasks.owner_headers(Some(&task), false)?;
        let target_id = self.tasks.dependency_target(target).await?;
        let p = self.tasks.scoped(
            &format!(
                "/v1/user-tasks/{}/dependencies",
                string(&task.raw, "task_id")?
            ),
            &[],
        );
        let kind = match target.kind {
            WorkKind::Task => "task",
            WorkKind::Plan => "plan",
        };
        self.tasks
            .backend
            .request(
                Method::POST,
                &p,
                Some(json!({"target_ref":format!("{kind}:{target_id}")})),
                Some(&headers),
            )
            .await
    }
    pub async fn remove(&mut self, source: &str, target: &DependencyTarget) -> Result<Value> {
        let task = self.tasks.resolve(source).await?;
        let headers = self.tasks.owner_headers(Some(&task), false)?;
        let target_id = self.tasks.dependency_target(target).await?;
        let kind = match target.kind {
            WorkKind::Task => "task",
            WorkKind::Plan => "plan",
        };
        let p = self.tasks.scoped(
            &format!(
                "/v1/user-tasks/{}/dependencies/{kind}/{}",
                string(&task.raw, "task_id")?,
                target_id
            ),
            &[],
        );
        self.tasks
            .backend
            .request(Method::DELETE, &p, None, Some(&headers))
            .await
    }
}

#[derive(Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum TaskMutationKind {
    Create,
    Update,
    Complete,
    Delete,
    Activity,
    Noop,
}
/// Ciphertext-only durable intent. The application encrypts and persists this
/// exact DTO before dispatch; retries must not regenerate its random ciphertext.
#[derive(Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct TaskDelivery {
    pub protocol_version: u8,
    pub delivery_id: String,
    pub task_id: String,
    pub team_id: Option<String>,
    pub scope: String,
    pub kind: TaskMutationKind,
    pub input: Value,
    pub expected_owner_hash: Option<String>,
    pub creator: bool,
    pub actor_assignee: bool,
}
impl Tasks<'_> {
    async fn delivery_scope(&mut self) -> Result<String> {
        let master = self.backend.master().await?;
        task_crypto::hmac(
            &master,
            format!(
                "openmates-task-delivery-v1\0{}\0{}\0{}\0{}",
                self.backend.origin(),
                self.filters.team_id.as_deref().unwrap_or("personal"),
                self.caller.codex_thread_id.as_deref().unwrap_or("human"),
                self.caller.as_assignee
            )
            .as_bytes(),
        )
    }
    async fn prepare(
        &mut self,
        id: &str,
        kind: TaskMutationKind,
        task_id: String,
        input: Value,
        headers: TaskHeaders,
    ) -> Result<TaskDelivery> {
        if id.len() != 64
            || !id
                .bytes()
                .all(|b| b.is_ascii_digit() || (b'a'..=b'f').contains(&b))
        {
            return Err(Error::Invalid(
                "Task delivery ID must contain 64 hexadecimal characters.",
            ));
        }
        if kind == TaskMutationKind::Delete {
            entry_id(&task_id)?;
        } else {
            uuid(&task_id)?;
        }
        Ok(TaskDelivery {
            protocol_version: 1,
            delivery_id: id.into(),
            task_id,
            team_id: self.filters.team_id.clone(),
            scope: self.delivery_scope().await?,
            kind,
            input,
            expected_owner_hash: headers.owner,
            creator: headers.creator,
            actor_assignee: headers.assignee,
        })
    }
    pub async fn prepare_create(
        &mut self,
        input: TaskCreate,
        delivery_id: &str,
    ) -> Result<TaskDelivery> {
        let input = self.canonical_create(input).await?;
        let (master, wrapping) = self.keys().await?;
        let payload = encrypt_create(&input, &master, &wrapping, self.filters.team_id.as_deref())?;
        let id = string(&payload, "task_id")?.to_owned();
        let headers = self.owner_headers(None, input.external_chat.is_some())?;
        self.prepare(delivery_id, TaskMutationKind::Create, id, payload, headers)
            .await
    }
    pub async fn prepare_update(
        &mut self,
        id: &str,
        input: TaskPatch,
        delivery_id: &str,
    ) -> Result<TaskDelivery> {
        let input = self.canonical_patch(input).await?;
        let task = self.resolve(id).await?;
        let headers = self.owner_headers(Some(&task), false)?;
        let (master, wrapping) = self.keys().await?;
        let mut payload = encrypt_patch(&task, &input, &master, &wrapping)?;
        self.project_wrappers(&task, &input, &mut payload, &wrapping)
            .await?;
        self.prepare(
            delivery_id,
            TaskMutationKind::Update,
            string(&task.raw, "task_id")?.into(),
            payload,
            headers,
        )
        .await
    }
    pub async fn prepare_complete(&mut self, id: &str, delivery_id: &str) -> Result<TaskDelivery> {
        let task = self.resolve(id).await?;
        readonly(&task)?;
        let headers = self.owner_headers(Some(&task), false)?;
        self.prepare(
            delivery_id,
            TaskMutationKind::Complete,
            string(&task.raw, "task_id")?.into(),
            json!({"version":task.raw["version"],"team_id":self.filters.team_id}),
            headers,
        )
        .await
    }
    pub async fn prepare_delete(
        &mut self,
        id: &str,
        delivery_id: &str,
        confirmed: bool,
    ) -> Result<TaskDelivery> {
        if !confirmed {
            return Err(Error::Invalid(
                "Explicit Task deletion confirmation is required.",
            ));
        }
        let task = self.resolve(id).await?;
        deletable(&task)?;
        let headers = self.owner_headers(Some(&task), false)?;
        self.prepare(
            delivery_id,
            TaskMutationKind::Delete,
            string(&task.raw, "task_id")?.into(),
            json!({"version":task.raw["version"].as_u64().unwrap_or(1),"projection_scheduled_at":task.raw["scheduled_at"]}),
            headers,
        )
        .await
    }
    pub async fn prepare_activity(
        &mut self,
        id: &str,
        input: TaskActivityInput,
        delivery_id: &str,
    ) -> Result<TaskDelivery> {
        let task = self.resolve(id).await?;
        let headers = self.owner_headers(Some(&task), false)?;
        let payload = activity_input(&task, &input)?;
        self.prepare(
            delivery_id,
            TaskMutationKind::Activity,
            string(&task.raw, "task_id")?.into(),
            payload,
            headers,
        )
        .await
    }
    /// Call only after the application persisted this exact intent and marked
    /// it uncertain. `uncertain=true` forces reconciliation before any retry.
    pub async fn execute_delivery(
        &mut self,
        delivery: &TaskDelivery,
        uncertain: bool,
    ) -> Result<Value> {
        if delivery.protocol_version != 1
            || delivery.team_id != self.filters.team_id
            || delivery.scope != self.delivery_scope().await?
            || delivery.delivery_id.len() != 64
            || !delivery
                .delivery_id
                .bytes()
                .all(|b| b.is_ascii_digit() || (b'a'..=b'f').contains(&b))
        {
            return Err(Error::Forbidden);
        }
        if delivery.kind == TaskMutationKind::Delete {
            entry_id(&delivery.task_id)?;
        } else {
            uuid(&delivery.task_id)?;
        }
        if serde_json::to_vec(delivery)?.len() > 2 * 1024 * 1024
            || delivery.input.as_object().is_none_or(|m| {
                m.keys().any(|k| {
                    k.starts_with("plaintext_")
                        || ["title", "description", "message", "external_chat"]
                            .contains(&k.as_str())
                })
            })
        {
            return Err(Error::Invalid(
                "Queued Task intents must contain only canonical ciphertext and safe metadata.",
            ));
        }
        if delivery.kind == TaskMutationKind::Create
            && delivery.input["assignee_type"] == "openmates"
        {
            self.backend.verify_private_operation()?;
        }
        let headers = TaskHeaders {
            assignee: delivery.actor_assignee,
            creator: delivery.creator,
            owner: delivery.expected_owner_hash.clone(),
            ..Default::default()
        };
        headers.headers()?;
        if delivery.creator && !matches!(self.backend, Backend::Cookie(_)) {
            return Err(Error::Forbidden);
        }
        if delivery.kind == TaskMutationKind::Noop {
            let task = self.resolve(&delivery.task_id).await?;
            if delivery
                .expected_owner_hash
                .as_ref()
                .is_some_and(|hash| task.raw["external_chat_lookup_hash"] != *hash)
            {
                return Err(Error::Conflict);
            }
            self.owner_headers(Some(&task), false)?;
            return Ok(task.public);
        }
        if uncertain && let Some(value) = self.reconcile_delivery(delivery).await? {
            return Ok(value);
        }
        let mut payload = delivery.input.clone();
        if delivery.kind == TaskMutationKind::Create && payload["assignee_type"] == "openmates" {
            let (master, wrapping) = self.keys().await?;
            let task = decrypt(
                payload.clone(),
                &master,
                &wrapping,
                self.filters.team_id.as_deref(),
            )?;
            payload["plaintext_title"] = task.public["title"].clone();
            payload["plaintext_description"] = task.public["description"].clone();
        }
        let p = match delivery.kind {
            TaskMutationKind::Noop => return Err(Error::Protocol),
            TaskMutationKind::Create => "/v1/user-tasks".into(),
            TaskMutationKind::Update => {
                self.scoped(&format!("/v1/user-tasks/{}", delivery.task_id), &[])
            }
            TaskMutationKind::Complete => format!("/v1/user-tasks/{}/complete", delivery.task_id),
            TaskMutationKind::Delete => self.scoped(
                &format!("/v1/user-tasks/{}", delivery.task_id),
                &[("version".into(), delivery.input["version"].to_string())],
            ),
            TaskMutationKind::Activity => self.scoped(
                &format!("/v1/user-tasks/{}/activity", delivery.task_id),
                &[],
            ),
        };
        let method = match delivery.kind {
            TaskMutationKind::Update => Method::PATCH,
            TaskMutationKind::Delete => Method::DELETE,
            _ => Method::POST,
        };
        let data = self
            .backend
            .request(
                method,
                &p,
                if delivery.kind == TaskMutationKind::Delete {
                    None
                } else {
                    Some(payload)
                },
                Some(&headers),
            )
            .await?;
        match delivery.kind {
            TaskMutationKind::Delete => {
                if data["deleted"] != true || data["task_id"] != delivery.task_id {
                    return Err(Error::Protocol);
                }
                Ok(data)
            }
            TaskMutationKind::Activity => {
                let task = self.resolve(&delivery.task_id).await?;
                if !same_activity(&delivery.input, &data["entry"]) {
                    return Err(Error::Conflict);
                }
                task_crypto::activity(&task, &data["entry"])
            }
            _ => {
                let raw = data["task"].clone();
                if !accepted(delivery, Some(&raw))? {
                    return Err(Error::Protocol);
                }
                self.verify_delivery_wrappers(delivery).await?;
                let (master, wrapping) = self.keys().await?;
                Ok(self.decode_row(raw, &master, &wrapping).await?.public)
            }
        }
    }
    async fn reconcile_delivery(&mut self, delivery: &TaskDelivery) -> Result<Option<Value>> {
        let p = self.scoped(&format!("/v1/user-tasks/{}", delivery.task_id), &[]);
        let raw = if matches!(self.backend, Backend::ApiKey(_))
            || delivery.input["projection_scheduled_at"].is_number()
        {
            let previous = self.filters.clone();
            self.filters = TaskFilters {
                team_id: previous.team_id.clone(),
                personal: previous.personal,
                ..TaskFilters::default()
            };
            let rows = self.list_resolved().await;
            self.filters = previous;
            rows?
                .into_iter()
                .find(|task| task.raw["task_id"] == delivery.task_id)
                .map(|task| task.raw)
        } else {
            match self.backend.request(Method::GET, &p, None, None).await {
                Ok(data) => Some(data["task"].clone()),
                Err(Error::Invalid(_)) => None,
                Err(e) => return Err(e),
            }
        };
        if delivery.kind == TaskMutationKind::Activity {
            let raw = raw.ok_or(Error::Conflict)?;
            if delivery
                .expected_owner_hash
                .as_ref()
                .is_some_and(|h| raw["external_chat_lookup_hash"] != *h)
            {
                return Err(Error::Conflict);
            }
            let mut cursor: Option<String> = None;
            for _ in 0..100 {
                let mut query = vec![("limit".into(), "200".into())];
                if let Some(cursor) = &cursor {
                    query.push(("cursor".into(), cursor.clone()));
                }
                let p = self.scoped(
                    &format!("/v1/user-tasks/{}/activity", delivery.task_id),
                    &query,
                );
                let data = self.backend.request(Method::GET, &p, None, None).await?;
                for entry in data["entries"].as_array().ok_or(Error::Protocol)? {
                    if entry["entry_id"] == delivery.input["entry_id"] {
                        if !same_activity(&delivery.input, entry) {
                            return Err(Error::Conflict);
                        }
                        let (master, wrapping) = self.keys().await?;
                        let task = self.decode_row(raw, &master, &wrapping).await?;
                        return Ok(Some(task_crypto::activity(&task, entry)?));
                    }
                }
                let next = data["next_cursor"].as_str().filter(|s| !s.is_empty());
                if next.is_none() {
                    return Ok(None);
                }
                if next == cursor.as_deref() {
                    return Err(Error::Protocol);
                }
                cursor = next.map(str::to_owned);
            }
            return Err(Error::Invalid(
                "Activity reconciliation exceeded the supported pagination limit.",
            ));
        }
        if accepted(delivery, raw.as_ref())? {
            self.verify_delivery_wrappers(delivery).await?;
            return match raw {
                Some(raw) => {
                    let (master, wrapping) = self.keys().await?;
                    Ok(Some(self.decode_row(raw, &master, &wrapping).await?.public))
                }
                None => Ok(Some(json!({"deleted":true,"task_id":delivery.task_id}))),
            };
        }
        Ok(None)
    }
}
fn same_activity(input: &Value, entry: &Value) -> bool {
    entry["kind"] == "comment"
        && ["entry_id", "encrypted_message", "embed_refs", "created_at"]
            .iter()
            .all(|key| input[*key] == entry[*key])
        && input
            .get("encrypted_embed_key_material")
            .is_none_or(|value| entry["encrypted_embed_key_material"] == *value)
}
fn accepted(delivery: &TaskDelivery, current: Option<&Value>) -> Result<bool> {
    let Some(current) = current else {
        return match delivery.kind {
            TaskMutationKind::Create => Ok(false),
            TaskMutationKind::Delete => Ok(true),
            _ => Err(Error::Conflict),
        };
    };
    if current["task_id"] != delivery.task_id {
        return Err(Error::Forbidden);
    }
    let release = delivery.kind == TaskMutationKind::Update
        && delivery.input.get("external_chat_provider") == Some(&Value::Null)
        && current["external_chat_provider"].is_null()
        && current["primary_chat_id"].is_null();
    if delivery
        .expected_owner_hash
        .as_ref()
        .is_some_and(|hash| current["external_chat_lookup_hash"] != *hash)
        && !release
    {
        return Err(Error::Conflict);
    }
    if delivery.kind == TaskMutationKind::Delete
        && delivery.input["projection_scheduled_at"].is_number()
    {
        return if current["source"] == "workflow_run"
            && current["projection_kind"] == "next_run"
            && current["scheduled_at"] == delivery.input["projection_scheduled_at"]
            && current["can_delete"] != false
        {
            Ok(false)
        } else {
            Err(Error::Conflict)
        };
    }
    let expected = delivery.input["version"].as_u64().ok_or(Error::Protocol)?;
    let version = current["version"].as_u64().ok_or(Error::Protocol)?;
    let next_version = expected.checked_add(1).ok_or(Error::Protocol)?;
    match delivery.kind {
        TaskMutationKind::Complete => {
            if current["status"] == "done" && version == next_version {
                return Ok(true);
            }
            if version == expected {
                return Ok(false);
            }
            Err(Error::Conflict)
        }
        TaskMutationKind::Delete => {
            if version == expected {
                Ok(false)
            } else {
                Err(Error::Conflict)
            }
        }
        TaskMutationKind::Create => {
            if (current["encrypted_task_key"] == delivery.input["encrypted_task_key"]
                || delivery.team_id.as_ref().is_some_and(|team| {
                    current["key_wrappers"].as_array().is_some_and(|rows| {
                        rows.iter().any(|w| {
                            w["key_type"] == "team"
                                && w["hashed_team_id"] == hash(team)
                                && w["encrypted_task_key"] == delivery.input["encrypted_task_key"]
                        })
                    })
                }))
                && current["created_at"] == delivery.input["created_at"]
            {
                Ok(true)
            } else {
                Err(Error::Conflict)
            }
        }
        TaskMutationKind::Update => {
            let same = delivery
                .input
                .as_object()
                .ok_or(Error::Protocol)?
                .iter()
                .filter(|(key, _)| {
                    !["version", "updated_at", "key_wrappers"].contains(&key.as_str())
                })
                .all(|(key, value)| {
                    if key == "linked_project_ids" {
                        let expected = value.as_array().map(|ids| {
                            ids.iter()
                                .filter_map(Value::as_str)
                                .map(|id| json!(hash(id)))
                                .collect::<Vec<_>>()
                        });
                        expected
                            .is_some_and(|hashes| current["linked_project_hashes"] == json!(hashes))
                    } else {
                        current[key] == *value
                    }
                });
            if same && version == next_version {
                return Ok(true);
            }
            if version == expected {
                Ok(false)
            } else {
                Err(Error::Conflict)
            }
        }
        TaskMutationKind::Activity | TaskMutationKind::Noop => Err(Error::Protocol),
    }
}

impl Tasks<'_> {
    pub(super) async fn dependency_target(&mut self, target: &DependencyTarget) -> Result<String> {
        if uuid::Uuid::parse_str(&target.id).is_ok() {
            return Ok(target.id.clone());
        }
        match target.kind {
            WorkKind::Plan => self.reference("plan", &target.id).await,
            WorkKind::Task => {
                let filters = self.filters.clone();
                self.filters = TaskFilters {
                    team_id: filters.team_id.clone(),
                    ..TaskFilters::default()
                };
                let result = self.resolve(&target.id).await.map(|task| {
                    task.public["task_id"]
                        .as_str()
                        .ok_or(Error::Protocol)
                        .map(str::to_owned)
                });
                self.filters = filters;
                result?
            }
        }
    }
}

#[derive(Clone, Default, Serialize, Deserialize)]
#[serde(default, deny_unknown_fields)]
pub struct TaskActivityQuery {
    pub cursor: Option<String>,
    pub limit: Option<u16>,
    pub max_entries: Option<u16>,
    pub newest_first: bool,
    pub query: Option<String>,
}
impl Tasks<'_> {
    pub async fn activity_history(&mut self, id: &str, query: TaskActivityQuery) -> Result<Value> {
        if query
            .cursor
            .as_ref()
            .is_some_and(|s| s.is_empty() || s.len() > 512)
            || query.max_entries.is_some_and(|n| n == 0 || n > 200)
            || query.limit.is_some_and(|n| n == 0 || n > 200)
            || query.query.as_ref().is_some_and(|s| s.trim().is_empty())
        {
            return Err(Error::Invalid(
                "Invalid activity cursor, nonempty query or entry/page limits (1–200).",
            ));
        }
        let task = self.resolve(id).await?;
        let id = string(&task.raw, "task_id")?;
        let mut cursor = query.cursor;
        let mut entries = vec![];
        let mut matched = 0usize;
        let mut ids = BTreeSet::new();
        let mut cursors = BTreeSet::new();
        let max = query
            .max_entries
            .map(usize::from)
            .unwrap_or(if query.query.is_some() {
                200
            } else {
                usize::MAX
            });
        let needle = query.query.as_ref().map(|s| s.to_lowercase());
        for _ in 0..100 {
            let limit = usize::from(query.limit.unwrap_or(100)).min(if query.query.is_some() {
                usize::MAX
            } else {
                max - entries.len()
            });
            if limit == 0 {
                return Ok(
                    json!({"entries":entries,"next_cursor":cursor,"truncated":cursor.is_some(),"matched":matched}),
                );
            }
            let mut params = vec![
                ("limit".into(), limit.to_string()),
                ("newest_first".into(), query.newest_first.to_string()),
            ];
            if let Some(cursor) = &cursor {
                params.push(("cursor".into(), cursor.clone()));
            }
            let p = self.scoped(&format!("/v1/user-tasks/{id}/activity"), &params);
            let data = self.backend.request(Method::GET, &p, None, None).await?;
            for row in data["entries"].as_array().ok_or(Error::Protocol)? {
                if !ids.insert(string(row, "entry_id")?.to_owned()) {
                    return Err(Error::Protocol);
                }
                let entry = task_crypto::activity(&task, row)?;
                if needle.as_ref().is_none_or(|q| {
                    entry["message"]
                        .as_str()
                        .unwrap_or("")
                        .to_lowercase()
                        .contains(q)
                }) {
                    matched += 1;
                    if entries.len() < max {
                        entries.push(entry);
                    }
                }
            }
            cursor = data["next_cursor"]
                .as_str()
                .filter(|s| !s.is_empty())
                .map(str::to_owned);
            if cursor.as_ref().is_some_and(|c| !cursors.insert(c.clone())) {
                return Err(Error::Protocol);
            }
            if cursor.is_none() || (query.query.is_none() && entries.len() >= max) {
                return Ok(
                    json!({"entries":entries,"next_cursor":cursor,"truncated":cursor.is_some()||matched>entries.len(),"matched":matched}),
                );
            }
        }
        Err(Error::Invalid(
            "Activity history exceeds the supported pagination bound.",
        ))
    }
    async fn project_wrappers(
        &mut self,
        task: &Resolved,
        input: &TaskPatch,
        payload: &mut Value,
        wrapping: &[u8; 32],
    ) -> Result<()> {
        let Some(projects) = &input.linked_project_ids else {
            return Ok(());
        };
        let task_id = string(&task.raw, "task_id")?;
        let p = self.scoped(&format!("/v1/user-tasks/{task_id}/key-wrappers"), &[]);
        let data = self.backend.request(Method::GET, &p, None, None).await?;
        let mut wrappers = vec![];
        if self.filters.team_id.is_none() {
            wrappers.push(json!({"key_type":"master","encrypted_task_key":string(&task.raw,"encrypted_task_key")?,"created_at":now()}));
        }
        let chat = input
            .primary_chat_id
            .as_ref()
            .map(|v| v.as_deref())
            .unwrap_or_else(|| task.public["primary_chat_id"].as_str());
        let chat = if input.external_chat.as_ref().is_some_and(Option::is_some) {
            None
        } else {
            chat
        };
        let plan = input
            .plan_id
            .as_ref()
            .map(|v| v.as_deref())
            .unwrap_or_else(|| task.public["plan_id"].as_str());
        for row in data["key_wrappers"].as_array().ok_or(Error::Protocol)? {
            let kind = string(row, "key_type")?;
            if ["master", "project"].contains(&kind) {
                continue;
            }
            if kind == "chat" && chat.is_none_or(|id| row["hashed_chat_id"] != hash(id)) {
                continue;
            }
            if kind == "plan" && plan.is_none_or(|id| row["hashed_plan_id"] != hash(id)) {
                continue;
            }
            if kind == "team"
                && self
                    .filters
                    .team_id
                    .as_ref()
                    .is_none_or(|team| row["hashed_team_id"] != hash(team))
            {
                return Err(Error::Forbidden);
            }
            if !["chat", "plan", "team"].contains(&kind) {
                return Err(Error::Protocol);
            }
            string(row, "encrypted_task_key")?;
            let mut retained = json!({});
            for field in [
                "key_type",
                "encrypted_task_key",
                "hashed_chat_id",
                "hashed_plan_id",
                "hashed_team_id",
                "team_key_epoch",
                "created_at",
                "expires_at",
            ] {
                if let Some(value) = row.get(field) {
                    retained[field] = value.clone();
                }
            }
            wrappers.push(retained);
        }
        if chat.is_some() && !wrappers.iter().any(|w| w["key_type"] == "chat")
            || plan.is_some() && !wrappers.iter().any(|w| w["key_type"] == "plan")
            || self.filters.team_id.is_some() && !wrappers.iter().any(|w| w["key_type"] == "team")
        {
            return Err(Error::Forbidden);
        }
        for project in projects {
            uuid(project)?;
            let p = self.scoped(&format!("/v1/projects/{project}"), &[]);
            let data = self.backend.request(Method::GET, &p, None, None).await?;
            let row = &data["project"];
            if string(row, "project_id")? != project {
                return Err(Error::Forbidden);
            }
            let encrypted = if let Some(team) = &self.filters.team_id {
                row["key_wrappers"]
                    .as_array()
                    .and_then(|r| {
                        r.iter().find(|w| {
                            w["key_type"] == "team"
                                && w["hashed_team_id"] == hash(team)
                                && w["team_key_epoch"] == 1
                        })
                    })
                    .and_then(|w| w["encrypted_project_key"].as_str())
                    .ok_or(Error::Forbidden)?
            } else {
                string(row, "encrypted_project_key")?
            };
            let key = key_bytes(&crypto::decrypt_bytes(encrypted, wrapping)?)?;
            wrappers.push(json!({"key_type":"project","hashed_project_id":hash(project),"encrypted_task_key":crypto::server_fields::encrypt_bytes(task.key.as_ref(),&key, &[])?,"created_at":now()}));
        }
        payload["key_wrappers"] = json!(wrappers);
        Ok(())
    }
}

fn entry_id(id: &str) -> Result<()> {
    if id.is_empty() || id.len() > 512 || id.chars().any(char::is_control) {
        Err(Error::Invalid("Invalid Task activity/history entry ID."))
    } else {
        Ok(())
    }
}
fn deletable(task: &Resolved) -> Result<()> {
    if task.public["source"] == "workflow_run" {
        if task.public["projection_kind"] == "next_run" && task.public["can_delete"] != false {
            Ok(())
        } else {
            Err(Error::Invalid(
                "Only scheduled next-run projections can be skipped by Task deletion.",
            ))
        }
    } else {
        Ok(())
    }
}

impl Tasks<'_> {
    async fn verify_delivery_wrappers(&mut self, delivery: &TaskDelivery) -> Result<()> {
        let Some(expected) = delivery.input.get("key_wrappers").and_then(Value::as_array) else {
            return Ok(());
        };
        let p = self.scoped(
            &format!("/v1/user-tasks/{}/key-wrappers", delivery.task_id),
            &[],
        );
        let data = self.backend.request(Method::GET, &p, None, None).await?;
        let actual = data["key_wrappers"].as_array().ok_or(Error::Protocol)?;
        for wrapper in expected {
            if !actual.iter().any(|row| {
                wrapper.as_object().is_some_and(|fields| {
                    fields
                        .iter()
                        .filter(|(key, _)| !["created_at", "expires_at"].contains(&key.as_str()))
                        .all(|(key, value)| row[key] == *value)
                })
            }) {
                return Err(Error::Conflict);
            }
        }
        Ok(())
    }
    pub async fn prepare_connect(
        &mut self,
        id: &str,
        external: ExternalChat,
        delivery_id: &str,
    ) -> Result<TaskDelivery> {
        let task = self.resolve(id).await?;
        readonly(&task)?;
        if self
            .caller
            .codex_thread_id
            .as_ref()
            .is_some_and(|thread| external.provider != "codex" || external.id != *thread)
            || !task.public["primary_chat_id"].is_null()
        {
            return Err(Error::Forbidden);
        }
        let mut headers = self.owner_headers(Some(&task), false)?;
        if !task.public["external_chat"].is_null() {
            if task.public["external_chat"]["provider"] != external.provider
                || task.public["external_chat"]["id"] != external.id
            {
                return Err(Error::Forbidden);
            }
            headers.owner = task.raw["external_chat_lookup_hash"]
                .as_str()
                .map(str::to_owned);
            return self
                .prepare(
                    delivery_id,
                    TaskMutationKind::Noop,
                    string(&task.raw, "task_id")?.into(),
                    json!({"version":task.raw["version"]}),
                    headers,
                )
                .await;
        }
        let (master, wrapping) = self.keys().await?;
        let payload = encrypt_patch(
            &task,
            &TaskPatch {
                assign: Some("codex".into()),
                external_chat: Some(Some(external)),
                ..TaskPatch::default()
            },
            &master,
            &wrapping,
        )?;
        self.prepare(
            delivery_id,
            TaskMutationKind::Update,
            string(&task.raw, "task_id")?.into(),
            payload,
            headers,
        )
        .await
    }
    pub async fn prepare_release(&mut self, id: &str, delivery_id: &str) -> Result<TaskDelivery> {
        let task = self.resolve(id).await?;
        readonly(&task)?;
        let headers = self.owner_headers(Some(&task), false)?;
        let (master, wrapping) = self.keys().await?;
        let mut payload = encrypt_patch(
            &task,
            &TaskPatch {
                primary_chat_id: Some(None),
                external_chat: Some(None),
                status: if task.public["status"] == "in_progress" {
                    Some("todo".into())
                } else {
                    None
                },
                ..TaskPatch::default()
            },
            &master,
            &wrapping,
        )?;
        payload["queue_state"] = json!("none");
        payload["ai_execution_state"] = Value::Null;
        self.prepare(
            delivery_id,
            TaskMutationKind::Update,
            string(&task.raw, "task_id")?.into(),
            payload,
            headers,
        )
        .await
    }
}

#[cfg(test)]
pub(super) mod tests;

mod ask;
pub use ask::{TaskAskOptions, TaskExtractionMode, TaskProposal, TaskProposalContext};
