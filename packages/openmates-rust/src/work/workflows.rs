//! Shared Workflow definition, execution and retained-result services.
use super::*;
use serde::{Deserialize, Serialize};
use std::collections::BTreeMap;
mod advanced;
pub use advanced::*;
mod file;
pub use file::*;
mod wait;
pub use wait::*;
type Object = BTreeMap<String, Value>;
#[derive(Clone, Default, Serialize, Deserialize)]
#[serde(default, deny_unknown_fields)]
pub struct WorkflowFilters {
    pub personal: bool,
    pub team_id: Option<String>,
    pub app_id: Option<String>,
    pub offset: Option<u64>,
    pub limit: Option<u16>,
}
#[derive(Clone, Copy, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum WorkflowNodeType {
    ScheduleTrigger,
    ManualTrigger,
    WebhookTrigger,
    EventTrigger,
    AppSkillAction,
    Decision,
    Check,
    SendChatMessage,
    Repeat,
    ForEach,
    CreateChatReport,
    StartNewChat,
    SendNotification,
    SendEmailNotification,
    AskUser,
    Wait,
    CustomCode,
    End,
}
#[derive(Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct WorkflowNode {
    pub id: String,
    pub r#type: WorkflowNodeType,
    #[serde(default)]
    pub title: Option<String>,
    #[serde(default)]
    pub config: Object,
    #[serde(default)]
    pub input_mapping: Object,
    #[serde(default)]
    pub ui: Object,
}
#[derive(Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct WorkflowEdge {
    pub from: String,
    pub to: String,
    #[serde(default)]
    pub branch: Option<String>,
}
#[derive(Clone, Serialize, Deserialize)]
#[serde(default, deny_unknown_fields)]
pub struct WorkflowGraph {
    pub version: u32,
    pub trigger_node_id: Option<String>,
    pub nodes: Vec<WorkflowNode>,
    pub edges: Vec<WorkflowEdge>,
    pub variables: Object,
    pub limits: Object,
    pub ui_layout: Object,
}
impl Default for WorkflowGraph {
    fn default() -> Self {
        Self {
            version: 1,
            trigger_node_id: None,
            nodes: vec![],
            edges: vec![],
            variables: Default::default(),
            limits: Default::default(),
            ui_layout: Default::default(),
        }
    }
}
#[derive(Clone, Copy, Default, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum WorkflowRetention {
    #[default]
    #[serde(rename = "last_5")]
    Last5,
    None,
}
#[derive(Clone, Copy, Default, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum WorkflowLifecycle {
    #[default]
    Persisted,
    Temporary,
    ChatEmbed,
}
#[derive(Clone, Default, Serialize, Deserialize)]
#[serde(default, deny_unknown_fields)]
pub struct WorkflowCreate {
    pub title: String,
    pub description: Option<String>,
    pub category: Option<String>,
    pub icon: Option<String>,
    pub graph: WorkflowGraph,
    pub enabled: bool,
    pub run_content_retention: WorkflowRetention,
    pub lifecycle: WorkflowLifecycle,
    pub source: Option<String>,
    pub slug: Option<String>,
    pub source_chat_id: Option<String>,
    pub created_by_assistant: bool,
    pub auto_delete_at: Option<u64>,
}
#[derive(Clone, Default, Serialize, Deserialize)]
#[serde(default, deny_unknown_fields)]
pub struct WorkflowPatch {
    pub title: Option<String>,
    pub description: Option<String>,
    pub category: Option<String>,
    pub icon: Option<String>,
    pub graph: Option<WorkflowGraph>,
    pub enabled: Option<bool>,
    pub run_content_retention: Option<WorkflowRetention>,
    pub slug: Option<String>,
    pub version: Option<u64>,
}
#[derive(Clone, Copy, Default, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum WorkflowRunMode {
    #[default]
    Manual,
    Test,
}
#[derive(Clone, Default, Serialize, Deserialize)]
#[serde(default, deny_unknown_fields)]
pub struct WorkflowRunOptions {
    pub idempotency_key: String,
    pub mode: WorkflowRunMode,
    pub input: Object,
    pub source_chat_id: Option<String>,
    pub message_destination_overrides: BTreeMap<String, String>,
    pub return_outputs: BTreeMap<String, BTreeMap<String, String>>,
}
#[derive(Clone, Default, Serialize, Deserialize)]
#[serde(default, deny_unknown_fields)]
pub struct WorkflowStepOptions {
    pub input: Object,
    pub node: Option<WorkflowNode>,
    pub upstream_outputs: BTreeMap<String, Object>,
    pub confirmed: bool,
}
#[derive(Clone, Default, Serialize, Deserialize)]
#[serde(default, deny_unknown_fields)]
pub struct WorkflowInputOptions {
    pub text: Option<String>,
    pub input_type: Option<String>,
    pub audio_ref: Option<Object>,
    pub selected_workflow_id: Option<String>,
    pub selected_project_id: Option<String>,
    pub timezone: Option<String>,
    pub optimistic_save: bool,
    pub idempotency_key: Option<String>,
}
pub struct Workflows<'a> {
    backend: Backend<'a>,
    filters: WorkflowFilters,
}
impl<'a> Workflows<'a> {
    pub(crate) fn cookie(client: &'a mut Client, team_id: Option<String>) -> Self {
        Self {
            backend: Backend::Cookie(client),
            filters: WorkflowFilters {
                team_id,
                ..Default::default()
            },
        }
    }
    pub(crate) fn api_key(client: &'a mut OpenMates) -> Self {
        Self {
            backend: Backend::ApiKey(client),
            filters: Default::default(),
        }
    }
    pub fn with_filters(mut self, mut filters: WorkflowFilters) -> Self {
        if !filters.personal && filters.team_id.is_none() {
            filters.team_id = self.filters.team_id.clone();
        }
        self.filters = filters;
        self
    }
    fn scope(&self, team_allowed: bool) -> Result<()> {
        if self.filters.personal && self.filters.team_id.is_some() {
            return Err(Error::Invalid("Choose Personal or a Team, not both."));
        }
        if let Some(team) = &self.filters.team_id {
            uuid(team)?;
            if !team_allowed {
                return Err(Error::Unavailable {
                    code: "workflow_unavailable",
                    reason: "TEAM_WORKFLOW_OPERATION_UNAVAILABLE",
                });
            }
        }
        Ok(())
    }
    fn path(&self, route: &str, params: &[(String, String)]) -> String {
        path(route, self.filters.team_id.as_deref(), params)
    }
    async fn decode(&mut self, mut row: Value) -> Result<Value> {
        uuid(string(&row, "id")?)?;
        if let Some(cipher) = row["encrypted_slug"].as_str() {
            let key = self
                .backend
                .wrapping(self.filters.team_id.as_deref())
                .await?;
            row["slug"] = json!(crypto::decrypt_combined(cipher, &key)?);
        }
        if let Some(map) = row.as_object_mut() {
            map.remove("encrypted_slug");
            map.remove("slug_lookup_hash");
        }
        Ok(row)
    }
    async fn rows(
        &mut self,
        route: &str,
        params: &[(String, String)],
        field: &str,
        team: bool,
    ) -> Result<Vec<Value>> {
        self.scope(team)?;
        let route = self.path(route, params);
        let response = self
            .backend
            .request(Method::GET, &route, None, None)
            .await?;
        let mut output = vec![];
        for row in response[field].as_array().ok_or(Error::Protocol)? {
            output.push(self.decode(row.clone()).await?);
        }
        Ok(output)
    }
    pub async fn list(&mut self) -> Result<Vec<Value>> {
        let mut params = vec![];
        if let Some(app) = &self.filters.app_id {
            if app.is_empty() || app.len() > 100 {
                return Err(Error::Invalid("Invalid app ID."));
            }
            params.push(("app_id".into(), app.clone()));
        }
        if let Some(offset) = self.filters.offset {
            params.push(("offset".into(), offset.to_string()));
        }
        if let Some(limit) = self.filters.limit {
            if !(1..=50).contains(&limit) {
                return Err(Error::Invalid("Workflow limit must be 1–50."));
            }
            params.push(("limit".into(), limit.to_string()));
        }
        self.rows("/v1/workflows", &params, "workflows", true).await
    }
    pub async fn temporary(&mut self) -> Result<Vec<Value>> {
        self.rows("/v1/workflows/temporary", &[], "workflows", false)
            .await
    }
    async fn resolve(&mut self, id: &str) -> Result<String> {
        self.scope(true)?;
        if uuid::Uuid::parse_str(id).is_ok() {
            return Ok(id.into());
        }
        let filters = std::mem::take(&mut self.filters);
        self.filters = WorkflowFilters {
            personal: filters.personal,
            team_id: filters.team_id.clone(),
            ..Default::default()
        };
        let rows = self.list().await;
        self.filters = filters;
        let rows = rows?;
        let lower = id.to_lowercase();
        let slug = crypto::normalize_object_slug(id).ok();
        let matches = rows
            .iter()
            .filter(|row| {
                row["slug"].as_str() == slug.as_deref()
                    || row["title"].as_str().is_some_and(|s| {
                        s.split_whitespace()
                            .collect::<Vec<_>>()
                            .join(" ")
                            .to_lowercase()
                            == id
                                .split_whitespace()
                                .collect::<Vec<_>>()
                                .join(" ")
                                .to_lowercase()
                    })
                    || id.len() >= 8
                        && row["id"]
                            .as_str()
                            .is_some_and(|s| s.to_lowercase().starts_with(&lower))
            })
            .collect::<Vec<_>>();
        if matches.len() != 1 {
            return Err(Error::Invalid(
                "Workflow selector is missing or ambiguous; use its full ID.",
            ));
        }
        Ok(string(matches[0], "id")?.into())
    }
    async fn resource(
        &mut self,
        id: &str,
        suffix: &str,
        method: Method,
        body: Option<Value>,
        team: bool,
    ) -> Result<Value> {
        self.scope(team)?;
        let id = self.resolve(id).await?;
        let route = self.path(&format!("/v1/workflows/{id}{suffix}"), &[]);
        self.backend.request(method, &route, body, None).await
    }
    pub async fn get(&mut self, id: &str) -> Result<Value> {
        let data = self.resource(id, "", Method::GET, None, true).await?;
        self.decode(data["workflow"].clone()).await
    }
    pub async fn show(&mut self, id: &str) -> Result<Value> {
        self.get(id).await
    }
    pub async fn capabilities(&mut self) -> Result<Vec<Value>> {
        self.scope(true)?;
        let route = self.path("/v1/workflows/capabilities", &[]);
        let response = self
            .backend
            .request(Method::GET, &route, None, None)
            .await?;
        Ok(response["capabilities"]
            .as_array()
            .ok_or(Error::Protocol)?
            .clone())
    }
    async fn create_wire(&mut self, input: WorkflowCreate) -> Result<Value> {
        self.scope(true)?;
        self.backend.verify_private_operation()?;
        validate_title(&input.title, input.description.as_deref())?;
        validate_graph(&input.graph)?;
        if matches!(input.lifecycle, WorkflowLifecycle::ChatEmbed) {
            return Err(Error::Invalid("Use run-once for chat-owned Workflows."));
        }
        if self.filters.team_id.is_some() && input.enabled {
            return Err(Error::Unavailable {
                code: "workflow_unavailable",
                reason: "TEAM_WORKFLOW_EXECUTION_UNAVAILABLE",
            });
        }
        if let Some(chat) = &input.source_chat_id {
            uuid(chat)?;
        }
        let key = self
            .backend
            .wrapping(self.filters.team_id.as_deref())
            .await?;
        let slug = crypto::normalize_object_slug(input.slug.as_deref().unwrap_or(&input.title))?;
        let mut payload = serde_json::to_value(input)?;
        payload
            .as_object_mut()
            .ok_or(Error::Protocol)?
            .remove("slug");
        payload["source"] = payload["source"]
            .as_str()
            .map(|s| json!(s))
            .unwrap_or(json!("manual"));
        payload["encrypted_slug"] = json!(crypto::server_fields::encrypt_text(&slug, &key, &[])?);
        payload["slug_lookup_hash"] = json!(crypto::object_slug_lookup_hash(&slug, &key)?);
        payload["team_id"] = json!(self.filters.team_id);
        Ok(payload)
    }
    pub async fn create(&mut self, input: WorkflowCreate) -> Result<Value> {
        let payload = self.create_wire(input).await?;
        let route = self.path("/v1/workflows", &[]);
        let response = self
            .backend
            .request(Method::POST, &route, Some(payload), None)
            .await?;
        let mut workflow = self.decode(response["workflow"].clone()).await?;
        workflow["authoring_warnings"] = response["warnings"]
            .as_array()
            .cloned()
            .map(Value::Array)
            .unwrap_or(json!([]));
        Ok(workflow)
    }
    async fn patch_wire(&mut self, input: WorkflowPatch) -> Result<Value> {
        self.scope(true)?;
        self.backend.verify_private_operation()?;
        if let Some(title) = &input.title {
            validate_title(title, input.description.as_deref())?;
        } else if input
            .description
            .as_ref()
            .is_some_and(|s| s.chars().count() > 2000)
        {
            return Err(Error::Invalid(
                "Workflow description exceeds 2,000 characters.",
            ));
        }
        if let Some(graph) = &input.graph {
            validate_graph(graph)?;
        }
        let mut payload = serde_json::to_value(&input)?;
        payload
            .as_object_mut()
            .ok_or(Error::Protocol)?
            .retain(|_, v| !v.is_null());
        payload
            .as_object_mut()
            .ok_or(Error::Protocol)?
            .remove("slug");
        if let Some(slug) = input.slug {
            let key = self
                .backend
                .wrapping(self.filters.team_id.as_deref())
                .await?;
            let slug = crypto::normalize_object_slug(&slug)?;
            payload["encrypted_slug"] = json!(crypto::server_fields::encrypt_text(&slug, &key, &[])?);
            payload["slug_lookup_hash"] = json!(crypto::object_slug_lookup_hash(&slug, &key)?);
        }
        if payload.as_object().is_none_or(|m| m.is_empty()) {
            return Err(Error::Invalid("Choose at least one Workflow field."));
        }
        Ok(payload)
    }
    pub async fn update(&mut self, id: &str, input: WorkflowPatch) -> Result<Value> {
        let payload = self.patch_wire(input).await?;
        let data = self
            .resource(id, "", Method::PATCH, Some(payload), true)
            .await?;
        let mut result = self.decode(data["workflow"].clone()).await?;
        result["authoring_warnings"] = data["warnings"]
            .as_array()
            .cloned()
            .map(Value::Array)
            .unwrap_or(json!([]));
        Ok(result)
    }
    async fn action(&mut self, id: &str, action: &str, team: bool) -> Result<Value> {
        let data = self
            .resource(
                id,
                &format!("/{action}"),
                Method::POST,
                Some(json!({})),
                team,
            )
            .await?;
        self.decode(data["workflow"].clone()).await
    }
    pub async fn enable(&mut self, id: &str) -> Result<Value> {
        self.backend.verify_private_operation()?;
        self.action(id, "enable", true).await
    }
    pub async fn disable(&mut self, id: &str) -> Result<Value> {
        self.action(id, "disable", true).await
    }
    pub async fn keep(&mut self, id: &str) -> Result<Value> {
        self.action(id, "keep", false).await
    }
    pub async fn delete(&mut self, id: &str, confirmed: bool) -> Result<Value> {
        if !confirmed {
            return Err(Error::Invalid(
                "Explicit Workflow deletion confirmation is required.",
            ));
        }
        self.resource(id, "", Method::DELETE, None, true).await
    }
    pub async fn history(&mut self, id: &str, limit: Option<u16>) -> Result<Vec<Value>> {
        self.scope(false)?;
        let limit = limit.unwrap_or(50);
        if limit == 0 || limit > 500 {
            return Err(Error::Invalid("History limit must be 1–500."));
        }
        let id = self.resolve(id).await?;
        let route = self.path(
            &format!("/v1/workflows/{id}/history"),
            &[("limit".into(), limit.to_string())],
        );
        let data = self
            .backend
            .request(Method::GET, &route, None, None)
            .await?;
        Ok(data["entries"].as_array().ok_or(Error::Protocol)?.clone())
    }
    pub async fn restore(&mut self, id: &str, entry: &str, state: RestoreState) -> Result<Value> {
        opaque_id(entry)?;
        self.resource(
            id,
            "/restore",
            Method::POST,
            Some(json!({"entry_id":entry,"state":state})),
            false,
        )
        .await
    }
}
fn opaque_id(id: &str) -> Result<String> {
    if id.trim().is_empty() || id.len() > 512 || id.chars().any(char::is_control) {
        return Err(Error::Invalid("Invalid Workflow resource ID."));
    }
    Ok(url::form_urlencoded::byte_serialize(id.as_bytes()).collect())
}
fn validate_title(title: &str, description: Option<&str>) -> Result<()> {
    if title.trim().is_empty()
        || title.chars().count() > 200
        || description.is_some_and(|s| s.chars().count() > 2000)
    {
        return Err(Error::Invalid(
            "Workflow title requires 1–200 characters and description at most 2,000.",
        ));
    }
    Ok(())
}
fn validate_graph(graph: &WorkflowGraph) -> Result<()> {
    let mut ids = std::collections::BTreeSet::new();
    if !(1..=2).contains(&graph.version) || graph.nodes.len() > 500 || graph.edges.len() > 2000 {
        return Err(Error::Invalid("Invalid Workflow graph version or size."));
    }
    for node in &graph.nodes {
        if node.id.trim().is_empty() || node.id.len() > 200 || !ids.insert(&node.id) {
            return Err(Error::Invalid(
                "Workflow node IDs must be nonempty and unique.",
            ));
        }
    }
    for edge in &graph.edges {
        if !ids.contains(&edge.from) || !ids.contains(&edge.to) {
            return Err(Error::Invalid("Workflow edges must reference graph nodes."));
        }
    }
    if graph
        .trigger_node_id
        .as_ref()
        .is_some_and(|id| !ids.contains(id))
    {
        return Err(Error::Invalid(
            "Workflow trigger must reference a graph node.",
        ));
    }
    Ok(())
}
impl Workflows<'_> {
    pub async fn validate_yaml(&mut self, source: &str) -> Result<Value> {
        self.scope(true)?;
        yaml(source)?;
        let route = self.path("/v1/workflows/validate", &[]);
        let data = self
            .backend
            .request(Method::POST, &route, Some(json!({"source":source})), None)
            .await?;
        object_field(&data, "validation")
    }
    pub async fn create_from_yaml(&mut self, source: &str) -> Result<Value> {
        self.scope(false)?;
        self.backend.verify_private_operation()?;
        yaml(source)?;
        let data = self
            .backend
            .request(
                Method::POST,
                "/v1/workflows/yaml",
                Some(json!({"source":source})),
                None,
            )
            .await?;
        self.yaml_output(data).await
    }
    pub async fn update_from_yaml(&mut self, id: &str, source: &str) -> Result<Value> {
        self.scope(false)?;
        self.backend.verify_private_operation()?;
        yaml(source)?;
        let data = self
            .resource(
                id,
                "/yaml",
                Method::POST,
                Some(json!({"source":source})),
                false,
            )
            .await?;
        self.yaml_output(data).await
    }
    async fn yaml_output(&mut self, mut data: Value) -> Result<Value> {
        object_field(&data, "validation")?;
        data["workflow"] = self.decode(data["workflow"].clone()).await?;
        Ok(data)
    }
    pub async fn runs(&mut self, id: &str) -> Result<Vec<Value>> {
        let data = self.resource(id, "/runs", Method::GET, None, true).await?;
        Ok(data["runs"].as_array().ok_or(Error::Protocol)?.clone())
    }
    pub async fn run_detail(&mut self, id: &str, run: &str) -> Result<Value> {
        let run = opaque_id(run)?;
        let data = self
            .resource(id, &format!("/runs/{run}"), Method::GET, None, true)
            .await?;
        object_field(&data, "run")
    }
    pub async fn delete_run(&mut self, id: &str, run: &str) -> Result<Value> {
        let run = opaque_id(run)?;
        let data = self
            .resource(id, &format!("/runs/{run}"), Method::DELETE, None, false)
            .await?;
        if !matches!(
            data["status"].as_str(),
            Some("deleted" | "deletion_pending")
        ) {
            return Err(Error::Protocol);
        }
        Ok(data)
    }
    pub async fn cancel_run(&mut self, id: &str, run: &str) -> Result<Value> {
        let run = opaque_id(run)?;
        let data = self
            .resource(
                id,
                &format!("/runs/{run}/cancel"),
                Method::POST,
                Some(json!({})),
                false,
            )
            .await?;
        if !matches!(
            data["status"].as_str(),
            Some("cancellation_requested" | "cancelled")
        ) {
            return Err(Error::Protocol);
        }
        Ok(data)
    }
    pub async fn respond(
        &mut self,
        id: &str,
        run: &str,
        step: &str,
        input: Object,
    ) -> Result<Value> {
        self.backend.verify_private_operation()?;
        let run = opaque_id(run)?;
        opaque_id(step)?;
        let data = self
            .resource(
                id,
                &format!("/runs/{run}/respond"),
                Method::POST,
                Some(json!({"step_id":step,"input":input})),
                false,
            )
            .await?;
        object_field(&data, "run")
    }
    pub async fn preview_step(
        &mut self,
        id: &str,
        step: &str,
        input: WorkflowStepOptions,
    ) -> Result<Value> {
        self.backend.verify_private_operation()?;
        let step = opaque_id(step)?;
        let mut payload = serde_json::to_value(input)?;
        payload
            .as_object_mut()
            .ok_or(Error::Protocol)?
            .remove("confirmed");
        let data = self
            .resource(
                id,
                &format!("/steps/{step}/preview"),
                Method::POST,
                Some(payload),
                false,
            )
            .await?;
        object_field(&data, "preview")
    }
    pub async fn step_test(
        &mut self,
        id: &str,
        step: &str,
        input: WorkflowStepOptions,
    ) -> Result<Value> {
        self.backend.verify_private_operation()?;
        let step = opaque_id(step)?;
        let data = self
            .resource(
                id,
                &format!("/steps/{step}/test"),
                Method::POST,
                Some(serde_json::to_value(input)?),
                false,
            )
            .await?;
        object_field(&data, "run")
    }
    async fn resource_idempotent(
        &mut self,
        id: &str,
        suffix: &str,
        key: &str,
        payload: Value,
    ) -> Result<Value> {
        self.scope(false)?;
        self.backend.verify_private_operation()?;
        idempotency(key)?;
        let id = self.resolve(id).await?;
        let route = self.path(&format!("/v1/workflows/{id}{suffix}"), &[]);
        self.backend
            .request_idempotent(Method::POST, &route, Some(payload), key)
            .await
    }
    pub async fn save_as_reusable(&mut self, id: &str, idempotency_key: &str) -> Result<Value> {
        let data = self
            .resource_idempotent(id, "/save-as-reusable", idempotency_key, json!({}))
            .await?;
        self.decode(data["workflow"].clone()).await
    }
    pub async fn run(&mut self, id: &str, input: WorkflowRunOptions) -> Result<Value> {
        let key = input.idempotency_key.clone();
        let payload = run_payload(input)?;
        let data = self.resource_idempotent(id, "/run", &key, payload).await?;
        object_field(&data, "run")
    }
    pub async fn run_once(
        &mut self,
        title: &str,
        graph: WorkflowGraph,
        input: WorkflowRunOptions,
    ) -> Result<Value> {
        self.scope(false)?;
        self.backend.verify_private_operation()?;
        validate_title(title, None)?;
        validate_graph(&graph)?;
        idempotency(&input.idempotency_key)?;
        if input.source_chat_id.is_none() {
            return Err(Error::Invalid(
                "Workflow run-once requires a source chat ID.",
            ));
        }
        let key = input.idempotency_key.clone();
        let mut payload = run_payload(input)?;
        payload["title"] = json!(title);
        payload["graph"] = serde_json::to_value(graph)?;
        let mut data = self
            .backend
            .request_idempotent(Method::POST, "/v1/workflows/run-once", Some(payload), &key)
            .await?;
        object_field(&data, "run")?;
        data["workflow"] = self.decode(data["workflow"].clone()).await?;
        Ok(data)
    }
    pub async fn start_input(&mut self, input: WorkflowInputOptions) -> Result<Value> {
        self.scope(true)?;
        self.backend.verify_private_operation()?;
        let kind = input.input_type.as_deref().unwrap_or("text");
        match kind {
            "text" => {
                if input
                    .text
                    .as_ref()
                    .is_none_or(|s| s.trim().is_empty() || s.chars().count() > 20_000)
                    || input.audio_ref.is_some()
                {
                    return Err(Error::Invalid(
                        "Text Workflow input requires nonempty text and no audio reference.",
                    ));
                }
            }
            "audio" => {
                if input.text.is_some()
                    || input
                        .audio_ref
                        .as_ref()
                        .and_then(|r| r.get("id"))
                        .and_then(Value::as_str)
                        .is_none_or(|s| s.is_empty())
                {
                    return Err(Error::Invalid(
                        "Audio Workflow input requires an audio reference and no text.",
                    ));
                }
            }
            _ => return Err(Error::Invalid("Workflow input type must be text or audio.")),
        };
        let workflow = if let Some(id) = input.selected_workflow_id.as_deref() {
            Some(self.resolve(id).await?)
        } else {
            None
        };
        let project = if let Some(id) = input.selected_project_id.as_deref() {
            Some(self.project_id(id).await?)
        } else {
            None
        };
        if let Some(key) = &input.idempotency_key {
            uuid(key)?;
        }
        let mut payload = serde_json::to_value(&input)?;
        payload
            .as_object_mut()
            .ok_or(Error::Protocol)?
            .retain(|_, v| !v.is_null());
        payload["input_type"] = json!(kind);
        if let Some(id) = workflow {
            payload["selected_workflow_id"] = json!(id);
        }
        if let Some(id) = project {
            payload["selected_project_id"] = json!(id);
        }
        let route = self.path("/v1/workflows/input", &[]);
        let data = self
            .backend
            .request(Method::POST, &route, Some(payload), None)
            .await?;
        object_field(&data, "session")
    }
    pub async fn input_session(&mut self, session: &str) -> Result<Value> {
        self.scope(true)?;
        let session = opaque_id(session)?;
        let route = self.path(&format!("/v1/workflows/input/{session}"), &[]);
        let data = self
            .backend
            .request(Method::GET, &route, None, None)
            .await?;
        object_field(&data, "session")
    }
    pub async fn input_events(&mut self, session: &str, after_event_id: u64) -> Result<Vec<Value>> {
        self.scope(true)?;
        let session = opaque_id(session)?;
        let route = self.path(
            &format!("/v1/workflows/input/{session}/events"),
            &[("after_event_id".into(), after_event_id.to_string())],
        );
        let data = self
            .backend
            .request(Method::GET, &route, None, None)
            .await?;
        Ok(data["events"].as_array().ok_or(Error::Protocol)?.clone())
    }
    async fn input_action(&mut self, session: &str, action: &str, payload: Value) -> Result<Value> {
        self.scope(true)?;
        let session = opaque_id(session)?;
        let route = self.path(&format!("/v1/workflows/input/{session}/{action}"), &[]);
        let data = self
            .backend
            .request(Method::POST, &route, Some(payload), None)
            .await?;
        object_field(&data, "session")
    }
    pub async fn follow_up_input(&mut self, session: &str, text: &str) -> Result<Value> {
        self.backend.verify_private_operation()?;
        if text.is_empty() || text.chars().count() > 20_000 {
            return Err(Error::Invalid(
                "Workflow follow-up requires 1–20,000 characters.",
            ));
        }
        self.input_action(session, "follow-up", json!({"text":text}))
            .await
    }
    pub async fn stop_input(&mut self, session: &str) -> Result<Value> {
        self.input_action(session, "stop", json!({})).await
    }
    pub async fn undo_input(&mut self, session: &str) -> Result<Value> {
        self.input_action(session, "undo", json!({})).await
    }
    async fn project_id(&mut self, id: &str) -> Result<String> {
        let project = match &mut self.backend {
            Backend::Cookie(client) => {
                client
                    .projects()
                    .with_filters(ProjectFilters {
                        personal: self.filters.personal,
                        team_id: self.filters.team_id.clone(),
                        ..Default::default()
                    })
                    .show(id)
                    .await?
            }
            Backend::ApiKey(client) => {
                client
                    .projects()
                    .with_filters(ProjectFilters {
                        personal: self.filters.personal,
                        team_id: self.filters.team_id.clone(),
                        ..Default::default()
                    })
                    .show(id)
                    .await?
            }
        };
        Ok(string(&project, "project_id")?.into())
    }
}
fn object_field(data: &Value, key: &str) -> Result<Value> {
    data.get(key)
        .filter(|v| v.is_object())
        .cloned()
        .ok_or(Error::Protocol)
}
fn yaml(source: &str) -> Result<()> {
    if source.is_empty() || source.chars().count() > 65_536 {
        return Err(Error::Invalid(
            "Workflow YAML requires 1–65,536 characters.",
        ));
    }
    Ok(())
}
fn idempotency(key: &str) -> Result<()> {
    if key.trim().is_empty() || key.len() > 255 || key.bytes().any(|b| b < 32 || b == 127) {
        return Err(Error::Invalid(
            "A stable Workflow idempotency key of at most 255 bytes is required.",
        ));
    }
    Ok(())
}
fn run_payload(input: WorkflowRunOptions) -> Result<Value> {
    idempotency(&input.idempotency_key)?;
    if let Some(chat) = &input.source_chat_id {
        uuid(chat)?;
    }
    for chat in input.message_destination_overrides.values() {
        uuid(chat)?;
    }
    let mut payload = serde_json::to_value(input)?;
    let map = payload.as_object_mut().ok_or(Error::Protocol)?;
    map.remove("idempotency_key");
    map.retain(|_, v| !v.is_null());
    Ok(payload)
}

#[cfg(test)]
mod tests;

#[cfg(all(test, not(target_arch = "wasm32")))]
mod field_interop_tests {
    use super::*;
    use crate::work::tasks::tests::client;
    use crate::work::task_crypto::field_interop_support::{assert_web, case};
    #[tokio::test]
    async fn actual_workflow_create_patch_slugs_read_in_web_legacy_decoders() {
        let mut client = client("http://127.0.0.1:1");
        let mut workflows = client.workflows();
        let create = workflows.create_wire(WorkflowCreate { title: "Fixture".into(), slug: Some("private-slug".into()), ..Default::default() }).await.unwrap();
        let patch = workflows.patch_wire(WorkflowPatch { slug: Some("updated-slug".into()), ..Default::default() }).await.unwrap();
        assert_web(vec![case("workflow.create.slug","master-text",create["encrypted_slug"].as_str().unwrap(),&[7;32],b"private-slug",""),case("workflow.patch.slug","master-text",patch["encrypted_slug"].as_str().unwrap(),&[7;32],b"updated-slug","")]);
        assert_eq!(create["slug_lookup_hash"], crypto::object_slug_lookup_hash("private-slug",&[7;32]).unwrap());
        assert!(create.get("slug").is_none() && patch.get("slug").is_none());
    }
}
