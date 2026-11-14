//! Locally encrypted reusable mixed-source Checks (`/v1/user-checks`).
//!
//! Titles, descriptions, definitions and result detail are encrypted with a
//! per-Check key wrapped by the Project key (plus the master or Team key); the
//! gating metadata the server aggregates (source kinds, roles, statuses) stays
//! plaintext. Spec: `specifications/features/checks`.
use super::*;
use serde::{Deserialize, Serialize};

mod logic;
pub use logic::*;
#[cfg(test)]
#[path = "checks/tests.rs"]
mod tests;

/// Largest accepted serialized definition (the server limit is 4 MiB of ciphertext).
const MAX_DEFINITION_BYTES: usize = 2 * 1024 * 1024;

/// Input of `create` and `revise`; ids are client-made and kept for retries.
#[derive(Clone, Serialize, Deserialize)]
pub struct CheckInput {
    #[serde(default)]
    pub check_id: Option<String>,
    #[serde(default)]
    pub revision_id: Option<String>,
    pub title: String,
    #[serde(default)]
    pub description: Option<String>,
    /// `draft`, `ready` or (revise only) `archived`.
    #[serde(default)]
    pub status: Option<String>,
    #[serde(default)]
    pub requires_deterministic: bool,
    pub sources: Vec<SourceDefinition>,
}

/// Machine result of one source.
#[derive(Clone, Serialize, Deserialize)]
pub struct SourceResultInput {
    pub status: String,
    #[serde(default)]
    pub test_result_embed_id: Option<String>,
    #[serde(default)]
    pub ai_score: Option<f64>,
    #[serde(default)]
    pub ai_threshold: Option<f64>,
    /// Free-text detail, stored encrypted.
    #[serde(default)]
    pub detail: Option<String>,
}

/// Check operations in the current Personal or Team scope.
pub struct Checks<'a> {
    backend: Backend<'a>,
    team: Option<String>,
}
struct Opened {
    head: Value,
    key: Key,
}
impl<'a> Checks<'a> {
    pub(crate) fn cookie(client: &'a mut Client, team: Option<String>) -> Self {
        Self {
            backend: Backend::Cookie(client),
            team,
        }
    }
    pub(crate) fn api_key(client: &'a mut OpenMates) -> Self {
        Self {
            backend: Backend::ApiKey(client),
            team: None,
        }
    }
    /// Selects the Team scope; `None` keeps Personal.
    pub fn with_team(mut self, team: Option<String>) -> Self {
        self.team = team;
        self
    }
    fn route(&self, suffix: &str, params: &[(String, String)]) -> Result<String> {
        if let Some(team) = &self.team {
            uuid(team)?;
        }
        Ok(path(
            &format!("/v1/user-checks{suffix}"),
            self.team.as_deref(),
            params,
        ))
    }
    async fn project_key(&mut self, project: &str) -> Result<Key> {
        uuid(project)?;
        let route = path(
            &format!("/v1/projects/{project}"),
            self.team.as_deref(),
            &[],
        );
        let data = self
            .backend
            .request(Method::GET, &route, None, None)
            .await?;
        let row = &data["project"];
        if row["project_id"] != project {
            return Err(Error::Forbidden);
        }
        if self.team.is_none()
            && let Backend::ApiKey(client) = &mut self.backend
            && let Some(key) = client.project_grant_key(project).await?
        {
            return Ok(key);
        }
        let wrapping = self.backend.wrapping(self.team.as_deref()).await?;
        super::projects::project_key(row, &wrapping, self.team.as_deref())
    }
    /// Unwraps the Check key: the Project wrapper when a Project is known, else the master/Team one.
    async fn check_key(&mut self, head: &Value, project: Option<&str>) -> Result<Key> {
        let wrappers = head["key_wrappers"].as_array().ok_or(Error::Forbidden)?;
        let (wrapper, unwrapping) = match (project, &self.team) {
            (Some(project), _) => {
                let wanted = hash(project);
                let found = wrappers
                    .iter()
                    .find(|w| w["key_type"] == "project" && w["hashed_project_id"] == wanted);
                (found, self.project_key(project).await?)
            }
            (None, Some(team)) => {
                let wanted = hash(team);
                let found = wrappers
                    .iter()
                    .find(|w| w["key_type"] == "team" && w["hashed_team_id"] == wanted);
                (found, self.backend.wrapping(Some(team)).await?)
            }
            (None, None) => (
                wrappers.iter().find(|w| w["key_type"] == "master"),
                self.backend.master().await?,
            ),
        };
        let wrapper = wrapper.ok_or(Error::Forbidden)?;
        key_bytes(&crypto::server_fields::decrypt_bytes(
            string(wrapper, "encrypted_check_key")?,
            &unwrapping,
            &[],
        )?)
    }
    async fn open(&mut self, head: Value, project: Option<&str>) -> Result<Opened> {
        let key = self.check_key(&head, project).await?;
        Ok(Opened { head, key })
    }
    fn text(raw: &Value, field: &str, key: &[u8; 32]) -> Result<String> {
        crypto::server_fields::decrypt_text(string(raw, field)?, key, &[])
    }
    fn optional_text(raw: &Value, field: &str, key: &[u8; 32]) -> Result<Option<String>> {
        match raw[field].as_str().filter(|s| !s.is_empty()) {
            Some(cipher) => Ok(Some(crypto::server_fields::decrypt_text(cipher, key, &[])?)),
            None => Ok(None),
        }
    }
    fn head_view(opened: &Opened) -> Result<Value> {
        let h = &opened.head;
        Ok(json!({
            "check_id": h["check_id"], "status": h["status"],
            "current_revision_id": h["current_revision_id"],
            "current_revision_number": h["current_revision_number"],
            "created_at": h["created_at"], "updated_at": h["updated_at"],
            "title": Self::text(h, "encrypted_title", &opened.key)?,
            "description": Self::optional_text(h, "encrypted_description", &opened.key)?,
        }))
    }
    fn definition(raw: &Value, key: &[u8; 32]) -> Result<CheckDefinition> {
        let text = Self::text(raw, "encrypted_definition", key)?;
        if text_hash(&text) != string(raw, "definition_hash")? {
            return Err(Error::Conflict);
        }
        serde_json::from_str(&text).map_err(|_| Error::Protocol)
    }
    fn revision_view(raw: &Value, key: &[u8; 32]) -> Result<Value> {
        Ok(json!({
            "revision_id": raw["revision_id"], "revision_number": raw["revision_number"],
            "base_revision_id": raw["base_revision_id"], "definition_hash": raw["definition_hash"],
            "requires_deterministic": raw["requires_deterministic"], "sources": raw["sources"],
            "created_at": raw["created_at"],
            "definition": Self::definition(raw, key)?,
        }))
    }
    fn run_view(raw: &Value, key: &[u8; 32], sources: &Value) -> Result<Value> {
        let mut run = raw.clone();
        run["summary"] = json!(Self::optional_text(raw, "encrypted_summary", key)?);
        run["encrypted_summary"] = Value::Null;
        let results = raw["source_results"]
            .as_array()
            .cloned()
            .unwrap_or_default();
        let mut statuses = std::collections::BTreeMap::new();
        let mut views = vec![];
        for result in results {
            let mut view = result.clone();
            view["detail"] = json!(Self::optional_text(&result, "encrypted_result", key)?);
            view["encrypted_result"] = Value::Null;
            if let (Some(id), Some(status)) = (
                result["source_binding_id"].as_str(),
                result["status"].as_str(),
            ) {
                statuses.insert(id.to_owned(), status.to_owned());
            }
            views.push(view);
        }
        run["source_results"] = json!(views);
        if let Ok(bindings) = serde_json::from_value::<Vec<SourceBinding>>(sources.clone()) {
            run["aggregate_status"] = json!(aggregate_status(&bindings, &statuses));
        }
        Ok(run)
    }
    fn revision_body(input: &CheckInput, revision: &str, key: &[u8; 32]) -> Result<Value> {
        let definition = CheckDefinition {
            requires_deterministic: input.requires_deterministic,
            sources: input.sources.clone(),
        }
        .normalized()?;
        let text = definition.canonical_text()?;
        if text.len() > MAX_DEFINITION_BYTES {
            return Err(Error::Invalid("The Check definition is too large."));
        }
        let bindings: Vec<SourceBinding> = definition
            .sources
            .iter()
            .map(SourceDefinition::binding)
            .collect();
        Ok(json!({
            "revision_id": revision, "definition_hash": text_hash(&text),
            "requires_deterministic": definition.requires_deterministic, "sources": bindings,
            "encrypted_definition": crypto::server_fields::encrypt_text(&text, key, &[])?,
        }))
    }
    fn title(input: &CheckInput) -> Result<&str> {
        let title = input.title.trim();
        if title.is_empty() {
            return Err(Error::Invalid("A Check needs a title."));
        }
        Ok(title)
    }

    /// Lists Checks of a Project and/or linked to a Plan (first page).
    pub async fn list(
        &mut self,
        project: Option<&str>,
        plan: Option<&str>,
        limit: u8,
    ) -> Result<Vec<Value>> {
        let mut params = vec![("limit".to_owned(), limit.clamp(1, 100).to_string())];
        if let Some(project) = project {
            params.push(("project_hash".into(), hash(uuid(project)?)));
        }
        if let Some(plan) = plan {
            params.push(("plan_id".into(), plan.to_owned()));
        }
        let route = self.route("", &params)?;
        let data = self
            .backend
            .request(Method::GET, &route, None, None)
            .await?;
        let rows = data["checks"].as_array().ok_or(Error::Protocol)?.clone();
        let mut views = vec![];
        for head in rows {
            let opened = self.open(head, project).await?;
            views.push(Self::head_view(&opened)?);
        }
        Ok(views)
    }
    /// Reads a Check with its current revision, latest run and source results.
    ///
    /// `subject_now` adds a `stale` flag to a passed latest run.
    pub async fn show(
        &mut self,
        id: &str,
        project: Option<&str>,
        subject_now: Option<&str>,
    ) -> Result<Value> {
        let route = self.route(&format!("/{}", uuid(id)?), &[])?;
        let data = self
            .backend
            .request(Method::GET, &route, None, None)
            .await?;
        if data["check"]["check_id"] != id {
            return Err(Error::Forbidden);
        }
        let opened = self.open(data["check"].clone(), project).await?;
        let revision = Self::revision_view(&data["revision"], &opened.key)?;
        let mut latest = Value::Null;
        if !data["latest_run"].is_null() {
            latest = Self::run_view(
                &data["latest_run"],
                &opened.key,
                &data["revision"]["sources"],
            )?;
            let run: Run = serde_json::from_value(latest.clone()).map_err(|_| Error::Protocol)?;
            let current = string(&opened.head, "current_revision_id")?;
            latest["stale"] = json!(is_stale(Some(&run), current, subject_now));
        }
        Ok(json!({"check": Self::head_view(&opened)?, "revision": revision, "latest_run": latest}))
    }
    /// Revision history, newest first.
    pub async fn revisions(
        &mut self,
        id: &str,
        project: Option<&str>,
        limit: u8,
    ) -> Result<Vec<Value>> {
        let head = self.show_head(id, project).await?;
        let params = [("limit".to_owned(), limit.clamp(1, 100).to_string())];
        let route = self.route(&format!("/{id}/revisions"), &params)?;
        let data = self
            .backend
            .request(Method::GET, &route, None, None)
            .await?;
        data["revisions"]
            .as_array()
            .ok_or(Error::Protocol)?
            .iter()
            .map(|raw| Self::revision_view(raw, &head.key))
            .collect()
    }
    async fn show_head(&mut self, id: &str, project: Option<&str>) -> Result<Opened> {
        let route = self.route(&format!("/{}", uuid(id)?), &[])?;
        let data = self
            .backend
            .request(Method::GET, &route, None, None)
            .await?;
        if data["check"]["check_id"] != id {
            return Err(Error::Forbidden);
        }
        self.open(data["check"].clone(), project).await
    }
    fn fresh_id(given: &Option<String>) -> Result<String> {
        match given {
            Some(id) => Ok(uuid(id)?.to_owned()),
            None => Ok(uuid::Uuid::new_v4().to_string()),
        }
    }
    /// Creates a Check with its first revision.
    pub async fn create(&mut self, project: &str, input: CheckInput) -> Result<Value> {
        let id = Self::fresh_id(&input.check_id)?;
        let revision = Self::fresh_id(&input.revision_id)?;
        let project_key = self.project_key(project).await?;
        let key = crypto::random_key();
        let seal = |value: &str| crypto::server_fields::encrypt_text(value, &key, &[]);
        let revision_body = Self::revision_body(&input, &revision, &key)?;
        let wrap =
            |wrapping: &[u8; 32]| crypto::server_fields::encrypt_bytes(key.as_ref(), wrapping, &[]);
        let mut wrappers = vec![
            json!({"key_type":"project","hashed_project_id":hash(project),"encrypted_check_key":wrap(&project_key)?}),
        ];
        match &self.team {
            Some(team) => {
                let team_key = self.backend.wrapping(Some(team)).await?;
                wrappers.push(json!({"key_type":"team","hashed_team_id":hash(team),"team_key_epoch":1,"encrypted_check_key":wrap(&team_key)?}));
            }
            None => {
                let master = self.backend.master().await?;
                wrappers.push(json!({"key_type":"master","encrypted_check_key":wrap(&master)?}));
            }
        }
        let mut body = json!({
            "check_id": id, "project_id": uuid(project)?,
            "status": input.status.clone().unwrap_or_else(|| "draft".into()),
            "encrypted_title": seal(Self::title(&input)?)?,
            "key_wrappers": wrappers, "revision": revision_body,
        });
        if let Some(description) = input
            .description
            .as_deref()
            .filter(|d| !d.trim().is_empty())
        {
            body["encrypted_description"] = json!(seal(description.trim())?);
        }
        let route = self.route("", &[])?;
        let data = self
            .backend
            .request(Method::POST, &route, Some(body), None)
            .await?;
        self.written(&id, Some(project), data).await
    }
    /// Adds a revision on top of `base_revision`; a stale base is a conflict.
    pub async fn revise(
        &mut self,
        id: &str,
        project: Option<&str>,
        base_revision: &str,
        input: CheckInput,
    ) -> Result<Value> {
        let head = self.show_head(id, project).await?;
        let revision = Self::fresh_id(&input.revision_id)?;
        let mut body = Self::revision_body(&input, &revision, &head.key)?;
        body["base_revision_id"] = json!(uuid(base_revision)?);
        body["encrypted_title"] = json!(crypto::server_fields::encrypt_text(
            Self::title(&input)?,
            &head.key,
            &[]
        )?);
        if let Some(description) = input
            .description
            .as_deref()
            .filter(|d| !d.trim().is_empty())
        {
            body["encrypted_description"] = json!(crypto::server_fields::encrypt_text(
                description.trim(),
                &head.key,
                &[]
            )?);
        }
        if let Some(status) = &input.status {
            body["status"] = json!(status);
        }
        let route = self.route(&format!("/{id}/revisions"), &[])?;
        let data = self
            .backend
            .request(Method::POST, &route, Some(body), None)
            .await?;
        self.written(id, project, data).await
    }
    async fn written(&mut self, id: &str, project: Option<&str>, data: Value) -> Result<Value> {
        if data["check"]["check_id"] != id {
            return Err(Error::Forbidden);
        }
        let opened = self.open(data["check"].clone(), project).await?;
        Ok(json!({
            "check": Self::head_view(&opened)?,
            "revision": Self::revision_view(&data["revision"], &opened.key)?,
        }))
    }
    /// Starts a run on the current revision; the subject is the code/spec revision under test.
    pub async fn start_run(
        &mut self,
        id: &str,
        subject_revision: Option<&str>,
        summary: Option<&str>,
        project: Option<&str>,
    ) -> Result<Value> {
        let mut body = json!({});
        if let Some(subject) = subject_revision {
            body["subject_revision"] = json!(subject);
        }
        if let Some(summary) = summary {
            let head = self.show_head(id, project).await?;
            body["encrypted_summary"] = json!(crypto::server_fields::encrypt_text(
                summary,
                &head.key,
                &[]
            )?);
        }
        let route = self.route(&format!("/{}/runs", uuid(id)?), &[])?;
        let data = self
            .backend
            .request(Method::POST, &route, Some(body), None)
            .await?;
        Ok(json!({"run": data["run"]}))
    }
    /// Runs of a Check, newest first, with decrypted details.
    pub async fn runs(&mut self, id: &str, project: Option<&str>, limit: u8) -> Result<Vec<Value>> {
        let current = self.show(id, project, None).await?;
        let head = self.show_head(id, project).await?;
        let params = [("limit".to_owned(), limit.clamp(1, 100).to_string())];
        let route = self.route(&format!("/{id}/runs"), &params)?;
        let data = self
            .backend
            .request(Method::GET, &route, None, None)
            .await?;
        let sources = current["revision"]["sources"].clone();
        data["runs"]
            .as_array()
            .ok_or(Error::Protocol)?
            .iter()
            .map(|raw| Self::run_view(raw, &head.key, &sources))
            .collect()
    }
    /// The revision's binding for `binding_id`, plus the Check key.
    async fn binding(
        &mut self,
        check: &str,
        binding_id: &str,
        project: Option<&str>,
    ) -> Result<(SourceDefinition, Key)> {
        let head = self.show_head(check, project).await?;
        let route = self.route(&format!("/{check}"), &[])?;
        let data = self
            .backend
            .request(Method::GET, &route, None, None)
            .await?;
        let definition = Self::definition(&data["revision"], &head.key)?;
        let source = definition
            .sources
            .into_iter()
            .find(|s| s.source_binding_id == binding_id)
            .ok_or(Error::Invalid("source_not_found"))?;
        Ok((source, head.key))
    }
    /// Reports a machine result of one source (kind is taken from the Check's binding).
    pub async fn report_source_result(
        &mut self,
        check: &str,
        run: &str,
        binding_id: &str,
        result: SourceResultInput,
        project: Option<&str>,
    ) -> Result<Value> {
        uuid(run)?;
        let (source, key) = self.binding(uuid(check)?, binding_id, project).await?;
        let mut body = json!({
            "source_kind": source.source_kind, "status": result.status,
            "test_result_embed_id": result.test_result_embed_id,
            "ai_score": result.ai_score, "ai_threshold": result.ai_threshold,
        });
        if let Some(detail) = result.detail.as_deref().filter(|d| !d.is_empty()) {
            body["encrypted_result"] =
                json!(crypto::server_fields::encrypt_text(detail, &key, &[])?);
        }
        let route = self.route(
            &format!("/runs/{run}/sources/{}/result", url_segment(binding_id)),
            &[],
        )?;
        let data = self
            .backend
            .request(Method::POST, &route, Some(body), None)
            .await?;
        Ok(json!({"run": data["run"]}))
    }
    /// Records the human decision (`confirmed`, `rejected`, `blocked`, `waived`).
    pub async fn confirm_human(
        &mut self,
        run: &str,
        binding_id: &str,
        decision: &str,
        note: Option<(&str, &str)>,
        project: Option<&str>,
    ) -> Result<Value> {
        uuid(run)?;
        if !matches!(decision, "confirmed" | "rejected" | "blocked" | "waived") {
            return Err(Error::Invalid(
                "A decision is confirmed, rejected, blocked or waived.",
            ));
        }
        let mut body = json!({"decision": decision});
        if let Some((check, note)) = note.filter(|(_, n)| !n.is_empty()) {
            let (_, key) = self.binding(uuid(check)?, binding_id, project).await?;
            body["encrypted_result"] = json!(crypto::server_fields::encrypt_text(note, &key, &[])?);
        }
        let route = self.route(
            &format!("/runs/{run}/sources/{}/confirm", url_segment(binding_id)),
            &[],
        )?;
        let data = self
            .backend
            .request(Method::POST, &route, Some(body), None)
            .await?;
        Ok(json!({"run": data["run"]}))
    }
    /// Sends the source's question and the evidence (plaintext, by design) to the
    /// evaluator; the server records the verdict on the run.
    pub async fn ai_evaluate(
        &mut self,
        check: &str,
        run: &str,
        binding_id: &str,
        evidence: &str,
        threshold: Option<f64>,
        project: Option<&str>,
    ) -> Result<Value> {
        uuid(run)?;
        let (source, _) = self.binding(uuid(check)?, binding_id, project).await?;
        if source.source_kind != SourceKind::AiEvaluation {
            return Err(Error::Invalid("CHECK_RESULT_MISMATCH"));
        }
        let mut body = json!({"question": source.reference, "evidence": evidence});
        if let Some(threshold) = threshold {
            body["threshold"] = json!(threshold);
        }
        let route = self.route(
            &format!(
                "/runs/{run}/sources/{}/ai-evaluate",
                url_segment(binding_id)
            ),
            &[],
        )?;
        self.backend
            .request(Method::POST, &route, Some(body), None)
            .await
    }
    /// Links the Check to a Plan (required by default).
    pub async fn link_plan(
        &mut self,
        id: &str,
        plan: &str,
        required: bool,
        criterion: Option<&str>,
    ) -> Result<Value> {
        let mut body = json!({"plan_id": plan, "required": required});
        if let Some(criterion) = criterion {
            body["criterion_id"] = json!(criterion);
        }
        let route = self.route(&format!("/{}/plan-links", uuid(id)?), &[])?;
        self.backend
            .request(Method::POST, &route, Some(body), None)
            .await
    }
    /// Removes a Plan link.
    pub async fn unlink_plan(&mut self, id: &str, plan: &str) -> Result<Value> {
        let route = self.route(
            &format!("/{}/plan-links/{}", uuid(id)?, url_segment(plan)),
            &[],
        )?;
        self.backend
            .request(Method::DELETE, &route, None, None)
            .await
    }
}
fn url_segment(value: &str) -> String {
    url::form_urlencoded::byte_serialize(value.as_bytes()).collect()
}
