//! Work recovery network operations on the Plans namespace: build one Project's
//! cleartext projection, preview a restore and apply it into an empty Project.
//! Pure document rules live in `work::recovery`.
use super::children::public as child_public;
use super::*;
use crate::work::recovery::{
    self as projection, RecoveryConflict, RecoveryError, RecoveryResult, record_string,
};

impl Plans<'_> {
    async fn recovery_project_plans(&mut self, project_id: &str) -> Result<Vec<ResolvedPlan>> {
        let saved = self.filters.clone();
        self.filters = PlanFilters {
            personal: saved.personal,
            team_id: saved.team_id.clone(),
            project_id: Some(project_id.into()),
            ..Default::default()
        };
        let result = self.list_resolved().await;
        self.filters = saved;
        result
    }
    async fn recovery_project_tasks(&mut self, project_id: &str) -> Result<Vec<Value>> {
        let saved = self.tasks.filters.clone();
        self.tasks.filters = TaskFilters {
            personal: saved.personal,
            team_id: saved.team_id.clone(),
            project_id: Some(project_id.into()),
            ..Default::default()
        };
        let result = self.tasks.list().await;
        self.tasks.filters = saved;
        result
    }
    async fn recovery_get(&mut self, route: &str) -> Result<Value> {
        let route = path(route, self.tasks.filters.team_id.as_deref(), &[]);
        self.tasks.backend.request(Method::GET, &route, None, None).await
    }
    /// Decrypt and project one canonical Project ID's Plans, Tasks, dependency
    /// edges, assumptions and revisions. Never touches chats or other Projects.
    pub async fn recovery_document(&mut self, project_id: &str) -> RecoveryResult<Value> {
        uuid(project_id)?;
        let plans = self.recovery_project_plans(project_id).await?;
        let tasks = self.recovery_project_tasks(project_id).await?;
        let (mut dependencies, mut assumptions, mut revisions) = (vec![], vec![], vec![]);
        for plan in &plans {
            let id = string(&plan.raw, "plan_id")?.to_owned();
            let edges = self.recovery_get(&format!("/v1/user-plans/{id}/dependencies")).await?;
            for edge in edges["dependencies"].as_array().ok_or(Error::Protocol)? {
                dependencies.push(json!({"source_ref": format!("plan:{id}"), "target_ref": string(edge, "target_ref")?}));
            }
            let rows = self.recovery_get(&format!("/v1/user-plans/{id}/assumptions")).await?;
            for row in rows["assumptions"].as_array().ok_or(Error::Protocol)? {
                let decrypted = child_public::<PlanAssumptionInput>(row, &plan.key)?;
                assumptions.push(projection::assumption_projection(&id, &decrypted)?);
            }
            let rows = self.recovery_get(&format!("/v1/user-plans/{id}/revisions")).await?;
            for row in rows["revisions"].as_array().ok_or(Error::Protocol)? {
                let snapshot = task_crypto::text(row, "encrypted_snapshot", &plan.key)?;
                revisions.push(projection::revision_projection(&id, row, &snapshot)?);
            }
        }
        for task in &tasks {
            let id = string(task, "task_id")?.to_owned();
            let edges = self.recovery_get(&format!("/v1/user-tasks/{id}/dependencies")).await?;
            for edge in edges["dependencies"].as_array().ok_or(Error::Protocol)? {
                dependencies.push(json!({"source_ref": format!("task:{id}"), "target_ref": string(edge, "target_ref")?}));
            }
        }
        Ok(projection::document(
            project_id,
            plans.iter().map(|plan| projection::plan_projection(&plan.public)).collect(),
            tasks.iter().map(projection::task_projection).collect(),
            dependencies,
            assumptions,
            revisions,
        ))
    }
    /// Existing Project objects that would collide with a validated document.
    pub async fn recovery_conflicts(
        &mut self,
        document: &Value,
        project_id: &str,
    ) -> RecoveryResult<Vec<RecoveryConflict>> {
        let plans = self.recovery_project_plans(project_id).await?;
        let plan_ids = plans
            .iter()
            .map(|plan| string(&plan.raw, "plan_id").map(str::to_owned))
            .collect::<Result<Vec<_>>>()?;
        let task_ids = self
            .recovery_project_tasks(project_id)
            .await?
            .iter()
            .map(|task| string(task, "task_id").map(str::to_owned))
            .collect::<Result<Vec<_>>>()?;
        Ok(projection::find_conflicts(document, project_id, &plan_ids, &task_ids))
    }
    /// Validate and report what a restore would create; writes nothing.
    pub async fn recovery_dry_run(&mut self, document: &Value, project_id: &str) -> RecoveryResult<Value> {
        projection::validate_document(document)?;
        let conflicts = self.recovery_conflicts(document, project_id).await?;
        Ok(projection::dry_run_report(document, project_id, &conflicts))
    }
    /// Restore into an empty Project, then regenerate and verify semantic
    /// equality. Not cross-object atomic: a failure reports what was applied.
    pub async fn recovery_restore(&mut self, document: &Value, project_id: &str) -> RecoveryResult<Vec<String>> {
        projection::validate_document(document)?;
        if document["project"]["project_id"].as_str() != Some(project_id) {
            return Err(RecoveryError::Invalid(
                "Recovery restore --project must exactly match document.project.project_id.".into(),
            ));
        }
        let conflicts = self.recovery_conflicts(document, project_id).await?;
        if !conflicts.is_empty() {
            return Err(RecoveryError::Invalid(format!(
                "Recovery restore found conflicts and made no changes: {}",
                serde_json::to_string(&conflicts).map_err(Error::from)?
            )));
        }
        let mut applied = vec![];
        if let Err(error) = self.recovery_apply(document, project_id, &mut applied).await {
            let done = if applied.is_empty() { "nothing".to_owned() } else { applied.join(", ") };
            return Err(RecoveryError::Invalid(format!(
                "Recovery restore partially applied ({done}); it is not cross-object atomic. {error}"
            )));
        }
        let restored = self.recovery_document(project_id).await?;
        let mismatches = projection::semantic_mismatch_paths(document, &restored);
        if !mismatches.is_empty() {
            return Err(RecoveryError::Invalid(format!(
                "Recovery restore completed but regenerated YAML is not semantically equal at: {}.",
                mismatches.join(", ")
            )));
        }
        Ok(applied)
    }
    async fn recovery_apply(
        &mut self,
        document: &Value,
        project_id: &str,
        applied: &mut Vec<String>,
    ) -> RecoveryResult<()> {
        let records = |field: &str| document[field].as_array().cloned().unwrap_or_default();
        for record in records("plans") {
            let input = projection::plan_create_input(&record, project_id)?;
            let id = input.plan_id.clone().unwrap_or_default();
            self.create(input).await?;
            applied.push(format!("plan:{id}"));
        }
        for record in records("tasks") {
            let input = projection::task_create_input(&record, project_id)?;
            let id = input.task_id.clone().unwrap_or_default();
            self.tasks.create(input).await?;
            applied.push(format!("task:{id}"));
        }
        let restored = self.recovery_project_plans(project_id).await?;
        let find = |id: &str, purpose: &str| {
            restored
                .iter()
                .find(|plan| plan.raw["plan_id"] == id)
                .ok_or_else(|| RecoveryError::Invalid(format!("Restored plan {id} was not available for its {purpose}.")))
        };
        for record in records("assumptions") {
            let plan_id = record_string(&record, "plan_id")?;
            let plan = find(plan_id, "assumption")?;
            let payload = assumption_payload(&record, &plan.key)?;
            self.tasks
                .backend
                .request(Method::POST, &format!("/v1/user-plans/{plan_id}/assumptions"), Some(payload), None)
                .await?;
            applied.push(format!("assumption:{}", record_string(&record, "assumption_id")?));
        }
        for dependency in records("dependencies") {
            let (source, target) = (record_string(&dependency, "source_ref")?, record_string(&dependency, "target_ref")?);
            let (kind, id) = split_ref(source);
            let target_ref = target_from_ref(target)?;
            if kind == "plan" {
                self.add_dependency(id, &target_ref).await?;
            } else {
                self.tasks.dependencies().add(id, &target_ref).await?;
            }
            applied.push(format!("dependency:{source}->{target}"));
        }
        for record in records("revisions") {
            let plan_id = record_string(&record, "plan_id")?;
            let plan = find(plan_id, "revision")?;
            let snapshot = serde_json::to_string(&record["snapshot"]).map_err(Error::from)?;
            let payload = json!({"fingerprint": record_string(&record, "fingerprint")?,
                "encrypted_snapshot": crypto::server_fields::encrypt_text(&snapshot, &plan.key, &[])?, "created_at": now()});
            self.tasks
                .backend
                .request(Method::POST, &format!("/v1/user-plans/{plan_id}/revisions"), Some(payload), None)
                .await?;
            applied.push(format!("revision:{}", record_string(&record, "revision_id")?));
        }
        Ok(())
    }
}

fn split_ref(reference: &str) -> (&str, &str) {
    let mut parts = reference.split(':');
    (parts.next().unwrap_or(""), parts.next().unwrap_or(""))
}

fn target_from_ref(reference: &str) -> RecoveryResult<DependencyTarget> {
    let (kind, id) = split_ref(reference);
    let kind = match kind {
        "plan" => WorkKind::Plan,
        "task" => WorkKind::Task,
        _ => {
            return Err(RecoveryError::Invalid(format!(
                "Work recovery dependency references missing object {reference}."
            )));
        }
    };
    Ok(DependencyTarget { kind, id: id.into() })
}

/// The existing CLI's assumption create body; every private field is encrypted
/// with the Plan key, including empty strings and the typed source list.
fn assumption_payload(record: &Value, key: &[u8; 32]) -> RecoveryResult<Value> {
    let encrypt = |text: &str| crypto::server_fields::encrypt_text(text, key, &[]);
    let field = |name: &str| encrypt(record[name].as_str().unwrap_or(""));
    let mut payload = json!({
        "assumption_id": record_string(record, "assumption_id")?,
        "encrypted_text": field("text")?,
        "linked_sub_chat_id": record["linked_sub_chat_id"].as_str(),
        "linked_task_id": record["linked_task_id"].as_str(),
        "linked_criterion_ids": record["linked_criterion_ids"].as_array().cloned().unwrap_or_default(),
        "encrypted_corrected_text": field("corrected_text")?,
        "encrypted_evidence_summary": field("evidence_summary")?,
        "encrypted_blocker_reason": field("blocker_reason")?,
        "encrypted_waiver_reason": field("waiver_reason")?,
        "encrypted_sources": encrypt(&serde_json::to_string(&record["sources"]).map_err(Error::from)?)?,
        "created_at": now(),
        "updated_at": now(),
    });
    for name in ["category", "status", "required_before"] {
        if let Some(value) = record[name].as_str() {
            payload[name] = json!(value);
        }
    }
    Ok(payload)
}
