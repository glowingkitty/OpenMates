//! Locally encrypted Plan authoring shared by first-party and API-key clients.
use super::*;
use serde::{Deserialize, Serialize};
#[derive(Clone, Default, Serialize, Deserialize)]
#[serde(default, deny_unknown_fields)]
pub struct PlanFilters {
    pub personal: bool,
    pub team_id: Option<String>,
    pub status: Option<String>,
    pub chat_id: Option<String>,
    pub project_id: Option<String>,
    pub active_only: Option<bool>,
}
#[derive(Clone, Default, Serialize, Deserialize)]
#[serde(default, deny_unknown_fields)]
pub struct PlanCreate {
    pub title: String,
    pub goal: String,
    pub slug: Option<String>,
    pub plan_id: Option<String>,
    pub scope_in: String,
    pub scope_out: String,
    pub user_flows: Vec<PlanFlow>,
    pub assumptions: String,
    pub open_questions: String,
    pub constraints: String,
    pub decisions: String,
    pub risks: String,
    pub reference_patterns: String,
    pub context: String,
    pub status: Option<String>,
    pub primary_chat_id: Option<String>,
    pub linked_project_ids: Vec<String>,
    pub planner_focus_id: Option<String>,
}
#[derive(Clone, Default, Serialize, Deserialize)]
#[serde(default, deny_unknown_fields)]
pub struct PlanPatch {
    pub title: Option<String>,
    pub goal: Option<String>,
    pub slug: Option<String>,
    pub scope_in: Option<String>,
    pub scope_out: Option<String>,
    pub user_flows: Option<Vec<PlanFlow>>,
    pub assumptions: Option<String>,
    pub open_questions: Option<String>,
    pub constraints: Option<String>,
    pub decisions: Option<String>,
    pub risks: Option<String>,
    pub reference_patterns: Option<String>,
    pub context: Option<String>,
    pub status: Option<String>,
    #[serde(deserialize_with = "nullable")]
    pub primary_chat_id: Option<Option<String>>,
    pub linked_project_ids: Option<Vec<String>>,
    #[serde(deserialize_with = "nullable")]
    pub planner_focus_id: Option<Option<String>>,
}
fn nullable<'de, D, T>(de: D) -> std::result::Result<Option<Option<T>>, D::Error>
where
    D: serde::Deserializer<'de>,
    T: Deserialize<'de>,
{
    Option::<T>::deserialize(de).map(Some)
}
#[derive(Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct PlanFlow {
    pub flow_id: String,
    pub title: String,
    pub actor: Option<String>,
    pub steps: Vec<PlanFlowStep>,
    pub expected_outcome: String,
    #[serde(default)]
    pub linked_task_ids: Vec<String>,
    #[serde(default)]
    pub linked_criterion_ids: Vec<String>,
}
#[derive(Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct PlanFlowStep {
    pub step_id: String,
    pub text: String,
    #[serde(default)]
    pub references: Vec<PlanEvidence>,
}
#[derive(Clone, Serialize, Deserialize)]
#[serde(tag = "kind", rename_all = "snake_case", deny_unknown_fields)]
pub enum PlanEvidence {
    Embed {
        embed_id: String,
        start_line: Option<u32>,
        end_line: Option<u32>,
    },
    File {
        path: String,
        start_line: Option<u32>,
        end_line: Option<u32>,
    },
    Url {
        url: String,
    },
}
struct ResolvedPlan {
    raw: Value,
    public: Value,
    key: Key,
}
pub struct Plans<'a> {
    tasks: Tasks<'a>,
    filters: PlanFilters,
}
impl<'a> Plans<'a> {
    pub(crate) fn cookie(client: &'a mut Client, team: Option<String>) -> Self {
        Self {
            tasks: Tasks::cookie(client, team.clone()),
            filters: PlanFilters {
                team_id: team,
                ..Default::default()
            },
        }
    }
    pub(crate) fn api_key(client: &'a mut OpenMates) -> Self {
        Self {
            tasks: Tasks::api_key(client),
            filters: Default::default(),
        }
    }
    pub fn with_filters(mut self, mut filters: PlanFilters) -> Self {
        if !filters.personal && filters.team_id.is_none() {
            filters.team_id = self.filters.team_id.clone();
        }
        self.tasks.filters = TaskFilters {
            team_id: filters.team_id.clone(),
            personal: filters.personal,
            ..Default::default()
        };
        self.filters = filters;
        self
    }
    fn scope(&self) -> Result<()> {
        if self.filters.team_id.is_some() {
            return Err(Error::Unavailable {
                code: "team_plan_keys_unavailable",
                reason: "TEAM_PLAN_WRAPPERS_NOT_SUPPORTED",
            });
        }
        Ok(())
    }
    async fn read_response(&mut self, value: Value) -> Result<Value> {
        let master = self.tasks.backend.master().await?;
        let mut plan = decode(value["plan"].clone(), &master)?.public;
        if let Some(history) = value.get("history") {
            plan["history"] = history.clone();
        }
        Ok(plan)
    }
    pub async fn list(&mut self) -> Result<Vec<Value>> {
        Ok(self
            .list_resolved()
            .await?
            .into_iter()
            .map(|p| p.public)
            .collect())
    }
    async fn list_resolved(&mut self) -> Result<Vec<ResolvedPlan>> {
        self.scope()?;
        let mut params = vec![];
        if let Some(status) = &self.filters.status {
            valid_status(status)?;
            params.push(("status".into(), status.clone()));
        }
        if let Some(chat) = self.filters.chat_id.clone() {
            params.push(("chat_id".into(), self.tasks.reference("chat", &chat).await?));
        }
        if let Some(project) = self.filters.project_id.clone() {
            params.push((
                "project_id".into(),
                self.tasks.reference("project", &project).await?,
            ));
        }
        if let Some(active) = self.filters.active_only {
            params.push(("active_only".into(), active.to_string()));
        }
        let data = self
            .tasks
            .backend
            .request(
                Method::GET,
                &path("/v1/user-plans", None, &params),
                None,
                None,
            )
            .await?;
        let master = self.tasks.backend.master().await?;
        data["plans"]
            .as_array()
            .ok_or(Error::Protocol)?
            .iter()
            .map(|p| decode(p.clone(), &master))
            .collect()
    }
    async fn resolve(&mut self, id: &str) -> Result<ResolvedPlan> {
        self.scope()?;
        if uuid::Uuid::parse_str(id).is_ok()
            && self.filters.status.is_none()
            && self.filters.chat_id.is_none()
            && self.filters.project_id.is_none()
            && self.filters.active_only != Some(true)
        {
            let data = self
                .tasks
                .backend
                .request(Method::GET, &format!("/v1/user-plans/{id}"), None, None)
                .await?;
            let master = self.tasks.backend.master().await?;
            let plan = decode(data["plan"].clone(), &master)?;
            if plan.raw["plan_id"] != id {
                return Err(Error::Forbidden);
            }
            return Ok(plan);
        }
        let plans = self.list_resolved().await?;
        let slug = crypto::normalize_object_slug(id).ok();
        let exact = plans
            .iter()
            .enumerate()
            .filter(|(_, p)| {
                p.public["slug"].as_str() == slug.as_deref()
                    || p.public["short_id"]
                        .as_str()
                        .is_some_and(|s| s.eq_ignore_ascii_case(id))
                    || id.eq_ignore_ascii_case(&format!(
                        "PLAN-{}",
                        u16::from_str_radix(
                            &hash(p.raw["plan_id"].as_str().unwrap_or(""))[..4],
                            16
                        )
                        .unwrap_or(0)
                            % 10000
                    ))
                    || id.len() >= 8
                        && p.public["plan_id"]
                            .as_str()
                            .is_some_and(|s| s.starts_with(id))
            })
            .map(|(i, _)| i)
            .collect::<Vec<_>>();
        if exact.len() != 1 {
            return Err(Error::Invalid(
                "Plan selector is missing or ambiguous; use its full ID.",
            ));
        }
        plans.into_iter().nth(exact[0]).ok_or(Error::Protocol)
    }
    pub async fn show(&mut self, id: &str) -> Result<Value> {
        Ok(self.resolve(id).await?.public)
    }
    async fn project_key(&mut self, id: &str) -> Result<Key> {
        uuid(id)?;
        let data = self
            .tasks
            .backend
            .request(Method::GET, &format!("/v1/projects/{id}"), None, None)
            .await?;
        let row = &data["project"];
        if row["project_id"] != id
            || row["hashed_team_id"]
                .as_str()
                .is_some_and(|s| !s.is_empty())
        {
            return Err(Error::Forbidden);
        }
        let master = self.tasks.backend.master().await?;
        key_bytes(&crypto::decrypt_bytes(
            string(row, "encrypted_project_key")?,
            &master,
        )?)
    }
    async fn chat_key(&mut self, id: &str) -> Result<Key> {
        uuid(id)?;
        match &mut self.tasks.backend {
            Backend::Cookie(client) => client.work_chat_key(id).await,
            Backend::ApiKey(client) => {
                let data = client
                    .task_request(Method::GET, "/v1/sdk/chats?limit=0", None, false, None)
                    .await?;
                let row = data["chats"]
                    .as_array()
                    .and_then(|rows| rows.iter().find(|r| r["id"] == id))
                    .ok_or(Error::Forbidden)?;
                if row["hashed_team_id"]
                    .as_str()
                    .is_some_and(|s| !s.is_empty())
                {
                    return Err(Error::Forbidden);
                }
                let master = client.master_key().await?;
                key_bytes(&crypto::decrypt_bytes(
                    string(row, "encrypted_chat_key")?,
                    &master,
                )?)
            }
        }
    }
    async fn wrappers(
        &mut self,
        key: &[u8; 32],
        projects: &[String],
        chat: Option<&str>,
    ) -> Result<Value> {
        let master = self.tasks.backend.master().await?;
        let mut rows = vec![
            json!({"key_type":"master","encrypted_plan_key":crypto::server_fields::encrypt_bytes(key,&master, &[])?,"created_at":now()}),
        ];
        for project in projects {
            let project_key = self.project_key(project).await?;
            rows.push(json!({"key_type":"project","hashed_project_id":hash(project),"encrypted_plan_key":crypto::server_fields::encrypt_bytes(key,&project_key, &[])?,"created_at":now()}));
        }
        if let Some(chat) = chat {
            let chat_key = self.chat_key(chat).await?;
            rows.push(json!({"key_type":"chat","hashed_chat_id":hash(chat),"encrypted_plan_key":crypto::server_fields::encrypt_bytes(key,&chat_key, &[])?,"created_at":now()}));
        }
        Ok(json!(rows))
    }
    async fn canonical_projects(&mut self, projects: &mut [String]) -> Result<()> {
        if projects.is_empty() {
            return Err(Error::Invalid("Plans require at least one Project link."));
        }
        let mut unique = std::collections::BTreeSet::new();
        for project in projects.iter_mut() {
            *project = self.tasks.reference("project", project).await?;
            if !unique.insert(project.clone()) {
                return Err(Error::Invalid("Duplicate Plan Project links."));
            }
        }
        Ok(())
    }
    async fn prepare_create_wire(&mut self, mut input: PlanCreate) -> Result<Value> {
        self.scope()?;
        self.canonical_projects(&mut input.linked_project_ids)
            .await?;
        if let Some(chat) = &mut input.primary_chat_id {
            *chat = self.tasks.reference("chat", chat).await?;
        }
        let master = self.tasks.backend.master().await?;
        let key = crypto::random_key();
        let mut payload = encode_create(&input, &key, &master)?;
        payload["key_wrappers"] = self
            .wrappers(
                &key,
                &input.linked_project_ids,
                input.primary_chat_id.as_deref(),
            )
            .await?;
        Ok(payload)
    }
    pub async fn create(&mut self, input: PlanCreate) -> Result<Value> {
        let payload = self.prepare_create_wire(input).await?;
        let data = self
            .tasks
            .backend
            .request(Method::POST, "/v1/user-plans", Some(payload), None)
            .await?;
        self.read_response(data).await
    }
    async fn prepare_patch_wire(
        &mut self,
        id: &str,
        mut input: PlanPatch,
    ) -> Result<(String, Value)> {
        let plan = self.resolve(id).await?;
        if let Some(projects) = &mut input.linked_project_ids {
            self.canonical_projects(projects).await?;
        }
        if let Some(Some(chat)) = &mut input.primary_chat_id {
            *chat = self.tasks.reference("chat", chat).await?;
        }
        let master = self.tasks.backend.master().await?;
        let mut patch = encode_patch(&plan, &input, &master)?;
        if input.linked_project_ids.is_some() || input.primary_chat_id.is_some() {
            let projects = input.linked_project_ids.as_ref().cloned().unwrap_or(
                serde_json::from_value(plan.public["linked_project_ids"].clone())
                    .map_err(|_| Error::Protocol)?,
            );
            let chat = input
                .primary_chat_id
                .as_ref()
                .map(|v| v.as_deref())
                .unwrap_or_else(|| plan.public["primary_chat_id"].as_str());
            patch["key_wrappers"] = self.wrappers(&plan.key, &projects, chat).await?;
        }
        Ok((string(&plan.raw, "plan_id")?.into(), patch))
    }
    pub async fn update(&mut self, id: &str, input: PlanPatch) -> Result<Value> {
        let (id, patch) = self.prepare_patch_wire(id, input).await?;
        let data = self
            .tasks
            .backend
            .request(
                Method::PATCH,
                &format!("/v1/user-plans/{id}"),
                Some(patch),
                None,
            )
            .await?;
        self.read_response(data).await
    }
    pub async fn edit(&mut self, id: &str, input: PlanPatch) -> Result<Value> {
        self.update(id, input).await
    }
    pub async fn start(&mut self, id: &str) -> Result<Value> {
        self.update(
            id,
            PlanPatch {
                status: Some("executing".into()),
                ..Default::default()
            },
        )
        .await
    }
    pub async fn resume(&mut self, id: &str) -> Result<Value> {
        self.update(
            id,
            PlanPatch {
                status: Some("active".into()),
                ..Default::default()
            },
        )
        .await
    }
    pub async fn complete(&mut self, id: &str) -> Result<Value> {
        let plan = self.resolve(id).await?;
        let data = self
            .tasks
            .backend
            .request(
                Method::POST,
                &format!("/v1/user-plans/{}/complete", string(&plan.raw, "plan_id")?),
                Some(json!({"version":plan.raw["version"]})),
                None,
            )
            .await?;
        self.read_response(data).await
    }
    pub async fn activate(&mut self, id: &str, chat: Option<&str>) -> Result<Value> {
        let plan = self.resolve(id).await?;
        let mut payload = json!({});
        if let Some(chat) = chat {
            let chat = self.tasks.reference("chat", chat).await?;
            let projects: Vec<String> =
                serde_json::from_value(plan.public["linked_project_ids"].clone())
                    .map_err(|_| Error::Protocol)?;
            payload["chat_id"] = json!(chat);
            payload["key_wrappers"] = self.wrappers(&plan.key, &projects, Some(&chat)).await?;
        }
        let data = self
            .tasks
            .backend
            .request(
                Method::POST,
                &format!("/v1/user-plans/{}/activate", string(&plan.raw, "plan_id")?),
                Some(payload),
                None,
            )
            .await?;
        self.read_response(data).await
    }
    pub async fn attach(&mut self, id: &str, chat: Option<&str>) -> Result<Value> {
        self.activate(id, chat).await
    }
    pub async fn delete(&mut self, id: &str, confirmed: bool) -> Result<Value> {
        if !confirmed {
            return Err(Error::Invalid(
                "Explicit Plan deletion confirmation is required.",
            ));
        }
        let plan = self.resolve(id).await?;
        self.tasks
            .backend
            .request(
                Method::DELETE,
                &format!(
                    "/v1/user-plans/{}?version={}",
                    string(&plan.raw, "plan_id")?,
                    plan.raw["version"]
                ),
                None,
                None,
            )
            .await
    }
    pub async fn add_to_project(&mut self, id: &str, project: &str) -> Result<Value> {
        let plan = self.resolve(id).await?;
        let project = self.tasks.reference("project", project).await?;
        let mut projects: Vec<String> =
            serde_json::from_value(plan.public["linked_project_ids"].clone())
                .map_err(|_| Error::Protocol)?;
        if !projects.contains(&project) {
            projects.push(project);
        }
        self.update(
            string(&plan.raw, "plan_id")?,
            PlanPatch {
                linked_project_ids: Some(projects),
                ..Default::default()
            },
        )
        .await
    }
    pub async fn remove_from_project(&mut self, id: &str, project: &str) -> Result<Value> {
        let plan = self.resolve(id).await?;
        let project = self.tasks.reference("project", project).await?;
        let mut projects: Vec<String> =
            serde_json::from_value(plan.public["linked_project_ids"].clone())
                .map_err(|_| Error::Protocol)?;
        projects.retain(|id| id != &project);
        self.update(
            string(&plan.raw, "plan_id")?,
            PlanPatch {
                linked_project_ids: Some(projects),
                ..Default::default()
            },
        )
        .await
    }
    pub async fn history(&mut self, id: &str, limit: Option<u16>) -> Result<Vec<Value>> {
        let limit = limit.unwrap_or(50);
        if !(1..=500).contains(&limit) {
            return Err(Error::Invalid("History limit must be 1–500."));
        }
        let plan = self.resolve(id).await?;
        let data = self
            .tasks
            .backend
            .request(
                Method::GET,
                &format!(
                    "/v1/user-plans/{}/history?limit={limit}",
                    string(&plan.raw, "plan_id")?
                ),
                None,
                None,
            )
            .await?;
        Ok(data["entries"].as_array().ok_or(Error::Protocol)?.clone())
    }
    pub async fn restore(&mut self, id: &str, entry: &str, state: RestoreState) -> Result<Value> {
        if entry.is_empty() || entry.len() > 512 || entry.chars().any(char::is_control) {
            return Err(Error::Invalid("Invalid Plan history entry ID."));
        }
        let plan = self.resolve(id).await?;
        self.tasks
            .backend
            .request(
                Method::POST,
                &format!("/v1/user-plans/{}/restore", string(&plan.raw, "plan_id")?),
                Some(json!({"entry_id":entry,"state":state})),
                None,
            )
            .await
    }
}
fn valid_status(status: &str) -> Result<()> {
    if [
        "draft",
        "checking_assumptions",
        "awaiting_confirmation",
        "active",
        "executing",
        "running_checks",
        "blocked",
        "completed",
        "archived",
    ]
    .contains(&status)
    {
        Ok(())
    } else {
        Err(Error::Invalid("Invalid Plan status."))
    }
}
const TEXT: &[&str] = &[
    "title",
    "goal",
    "scope_in",
    "scope_out",
    "assumptions",
    "open_questions",
    "constraints",
    "decisions",
    "risks",
    "reference_patterns",
    "context",
];
fn validate_flows(flows: &[PlanFlow]) -> Result<()> {
    for flow in flows {
        if flow.flow_id.is_empty()
            || flow.title.is_empty()
            || flow.expected_outcome.is_empty()
            || flow
                .steps
                .iter()
                .any(|step| step.step_id.is_empty() || step.text.is_empty())
        {
            return Err(Error::Invalid(
                "Plan flows require IDs, titles, ordered steps and expected outcomes.",
            ));
        }
        for reference in flow.steps.iter().flat_map(|s| &s.references) {
            let valid = match reference {
                PlanEvidence::Url { url } => url::Url::parse(url).is_ok_and(|u| {
                    u.scheme() == "https"
                        && !u.host_str().unwrap_or("").is_empty()
                        && u.username().is_empty()
                        && u.password().is_none()
                }),
                PlanEvidence::Embed {
                    embed_id,
                    start_line,
                    end_line,
                } => !embed_id.trim().is_empty() && lines(*start_line, *end_line),
                PlanEvidence::File {
                    path,
                    start_line,
                    end_line,
                } => {
                    !path.is_empty()
                        && !path.starts_with('/')
                        && !path.starts_with('\\')
                        && !path.split(['/', '\\']).any(|s| s == "..")
                        && lines(*start_line, *end_line)
                }
            };
            if !valid {
                return Err(Error::Invalid(
                    "Plan evidence requires HTTPS URLs, embed IDs or repository-relative paths and valid lines.",
                ));
            }
        }
    }
    Ok(())
}
fn lines(start: Option<u32>, end: Option<u32>) -> bool {
    start.is_none_or(|s| s > 0)
        && end.is_none_or(|e| e > 0)
        && start.zip(end).is_none_or(|(s, e)| s <= e)
}
fn decode(raw: Value, master: &[u8; 32]) -> Result<ResolvedPlan> {
    uuid(string(&raw, "plan_id")?)?;
    if raw["hashed_team_id"]
        .as_str()
        .is_some_and(|s| !s.is_empty())
    {
        return Err(Error::Forbidden);
    }
    let wrappers = raw["key_wrappers"].as_array().ok_or(Error::Forbidden)?;
    if wrappers.iter().any(|w| w["key_type"] == "team") {
        return Err(Error::Forbidden);
    }
    let master_wrappers = wrappers
        .iter()
        .filter(|w| w["key_type"] == "master")
        .collect::<Vec<_>>();
    if master_wrappers.len() != 1 {
        return Err(Error::Forbidden);
    }
    let key = key_bytes(&crypto::decrypt_bytes(
        string(master_wrappers[0], "encrypted_plan_key")?,
        master,
    )?)?;
    let mut public = json!({});
    for field in [
        "plan_id",
        "status",
        "approval_state",
        "submitted_revision_id",
        "approved_revision_id",
        "primary_chat_id",
        "planner_focus_id",
        "version",
        "created_at",
        "updated_at",
        "completed_at",
    ] {
        public[field] = raw[field].clone();
    }
    raw["version"].as_u64().ok_or(Error::Protocol)?;
    for field in TEXT {
        public[*field] = json!(task_crypto::text(
            &raw,
            &format!("encrypted_{field}"),
            &key
        )?);
    }
    public["slug"] = json!(task_crypto::text(&raw, "encrypted_slug", &key)?);
    let flows = task_crypto::text(&raw, "encrypted_user_flows", &key)?;
    public["user_flows"] = if flows.is_empty() {
        json!([])
    } else {
        let flows: Vec<PlanFlow> = serde_json::from_str(&flows).map_err(|_| Error::Crypto)?;
        validate_flows(&flows)?;
        json!(flows)
    };
    let projects = task_crypto::text(&raw, "encrypted_linked_project_ids", &key)?;
    public["linked_project_ids"] = if projects.is_empty() {
        raw["linked_project_ids"].clone()
    } else {
        serde_json::from_str::<Value>(&projects).map_err(|_| Error::Crypto)?
    };
    let projects: Vec<String> = serde_json::from_value(public["linked_project_ids"].clone())
        .map_err(|_| Error::Protocol)?;
    for project in projects {
        uuid(&project)?;
    }
    public["short_id"] = raw.get("short_id").cloned().unwrap_or_else(|| {
        json!(format!(
            "PLAN-{}",
            hash(raw["plan_id"].as_str().unwrap_or(""))[..6].to_uppercase()
        ))
    });
    Ok(ResolvedPlan { raw, public, key })
}
fn encode_create(input: &PlanCreate, key: &[u8; 32], master: &[u8; 32]) -> Result<Value> {
    if input.title.trim().is_empty() || input.goal.trim().is_empty() {
        return Err(Error::Invalid("Plan title and goal are required."));
    }
    let status = input.status.as_deref().unwrap_or("draft");
    valid_status(status)?;
    validate_flows(&input.user_flows)?;
    let id = input
        .plan_id
        .clone()
        .unwrap_or_else(|| uuid::Uuid::new_v4().to_string());
    uuid(&id)?;
    let slug = crypto::normalize_object_slug(input.slug.as_deref().unwrap_or(&input.title))?;
    let mut value = json!({"plan_id":id,"version":1,"status":status,"primary_chat_id":input.primary_chat_id,"linked_project_ids":input.linked_project_ids,"planner_focus_id":input.planner_focus_id,"created_at":now(),"updated_at":now(),"encrypted_slug":crypto::server_fields::encrypt_text(&slug,key, &[])?,"slug_lookup_hash":crypto::object_slug_lookup_hash(&slug,master)?,"encrypted_linked_project_ids":crypto::server_fields::encrypt_text(&serde_json::to_string(&input.linked_project_ids)?,key, &[])?,"encrypted_user_flows":crypto::server_fields::encrypt_text(&serde_json::to_string(&input.user_flows)?,key, &[])?});
    let input = serde_json::to_value(input)?;
    for field in TEXT {
        let text = input[*field].as_str().ok_or(Error::Protocol)?;
        if text.len() > 1_000_000 {
            return Err(Error::Invalid("Plan text exceeds the supported limit."));
        }
        value[format!("encrypted_{field}")] = json!(crypto::server_fields::encrypt_text(text, key, &[])?);
    }
    Ok(value)
}
fn encode_patch(plan: &ResolvedPlan, input: &PlanPatch, master: &[u8; 32]) -> Result<Value> {
    let mut patch = json!({"version":plan.raw["version"],"updated_at":now()});
    let input_value = serde_json::to_value(input)?;
    for field in TEXT {
        if let Some(text) = input_value[*field].as_str() {
            if text.len() > 1_000_000 {
                return Err(Error::Invalid("Plan text exceeds the supported limit."));
            }
            patch[format!("encrypted_{field}")] = json!(crypto::server_fields::encrypt_text(text, &plan.key, &[])?);
        }
    }
    if let Some(slug) = &input.slug {
        let slug = crypto::normalize_object_slug(slug)?;
        patch["encrypted_slug"] = json!(crypto::server_fields::encrypt_text(&slug, &plan.key, &[])?);
        patch["slug_lookup_hash"] = json!(crypto::object_slug_lookup_hash(&slug, master)?);
    }
    if let Some(status) = &input.status {
        valid_status(status)?;
        patch["status"] = json!(status);
    }
    if let Some(flows) = &input.user_flows {
        validate_flows(flows)?;
        patch["encrypted_user_flows"] = json!(crypto::server_fields::encrypt_text(
            &serde_json::to_string(flows)?,
            &plan.key
        , &[])?);
    }
    if let Some(projects) = &input.linked_project_ids {
        patch["linked_project_ids"] = json!(projects);
        patch["encrypted_linked_project_ids"] = json!(crypto::server_fields::encrypt_text(
            &serde_json::to_string(projects)?,
            &plan.key
        , &[])?);
    }
    if let Some(chat) = &input.primary_chat_id {
        patch["primary_chat_id"] = json!(chat);
    }
    if let Some(focus) = &input.planner_focus_id {
        patch["planner_focus_id"] = json!(focus);
    }
    Ok(patch)
}

#[cfg(test)]
mod tests;

mod children;
pub use children::*;

mod advanced;
pub use advanced::*;

mod ask;
pub use ask::{PlanAskOptions, PlanAskUpdate, PlanProposal};

#[cfg(all(test,not(target_arch="wasm32")))]
mod field_interop_tests {
    use super::*;
    use super::super::task_crypto::field_interop_support::{case,assert_web};
    #[test]
    fn actual_plan_create_patch_fields_read_in_web_legacy_decoders(){
        let master=[7;32];let key=[9;32];
        let input=PlanCreate{title:"Synthetic Plan ✓".into(),goal:"Useful private goal".into(),..Default::default()};
        let created=encode_create(&input,&key,&master).unwrap();
        let plan=ResolvedPlan{raw:created.clone(),public:json!({}),key:zeroize::Zeroizing::new(key)};
        let patch=encode_patch(&plan,&PlanPatch{title:Some("Updated Plan 界".into()),goal:Some("".into()),..Default::default()},&master).unwrap();
        assert_web(vec![case("plan-title","object-text",created["encrypted_title"].as_str().unwrap(),&key,input.title.as_bytes(),""),case("plan-goal","object-text",created["encrypted_goal"].as_str().unwrap(),&key,input.goal.as_bytes(),""),case("plan-user-flows","object-text",created["encrypted_user_flows"].as_str().unwrap(),&key,b"[]",""),case("plan-patch-title","object-text",patch["encrypted_title"].as_str().unwrap(),&key,"Updated Plan 界".as_bytes(),""),case("plan-empty-goal","object-text",patch["encrypted_goal"].as_str().unwrap(),&key,b"","")]);
    }
}
