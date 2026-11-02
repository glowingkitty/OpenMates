//! Plan review, dependency, verification evidence and linked Task services.
use super::children::PlanVerificationInput;
use super::*;
#[derive(Clone, Default, Serialize, Deserialize)]
#[serde(default, deny_unknown_fields)]
pub struct PlanVerificationEvidence {
    pub status: String,
    #[serde(
        skip_serializing_if = "Option::is_none",
        deserialize_with = "super::nullable"
    )]
    pub score: Option<Option<f64>>,
    #[serde(
        skip_serializing_if = "Option::is_none",
        deserialize_with = "super::nullable"
    )]
    pub threshold: Option<Option<f64>>,
    #[serde(
        skip_serializing_if = "Option::is_none",
        deserialize_with = "super::nullable"
    )]
    pub confidence: Option<Option<String>>,
    #[serde(
        skip_serializing_if = "Option::is_none",
        deserialize_with = "super::nullable"
    )]
    pub run_id: Option<Option<String>>,
    pub result_summary: Option<String>,
    pub required_fixes: Option<String>,
}
#[derive(Clone, Default, Serialize, Deserialize)]
#[serde(default, deny_unknown_fields)]
pub struct PlanLearningSelection {
    pub learning_ids: Vec<String>,
    pub all: bool,
}
#[derive(Clone, Copy, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum PlanField {
    Goal,
    ScopeIn,
    ScopeOut,
    Assumptions,
    OpenQuestions,
    Constraints,
    Decisions,
    Risks,
    ReferencePatterns,
    Context,
}
impl PlanField {
    fn name(self) -> &'static str {
        match self {
            Self::Goal => "goal",
            Self::ScopeIn => "scope_in",
            Self::ScopeOut => "scope_out",
            Self::Assumptions => "assumptions",
            Self::OpenQuestions => "open_questions",
            Self::Constraints => "constraints",
            Self::Decisions => "decisions",
            Self::Risks => "risks",
            Self::ReferencePatterns => "reference_patterns",
            Self::Context => "context",
        }
    }
}
impl Plans<'_> {
    pub async fn set_field(&mut self, id: &str, field: PlanField, text: &str) -> Result<Value> {
        let patch =
            serde_json::from_value(json!({field.name():text})).map_err(|_| Error::Protocol)?;
        self.update(id, patch).await
    }
    pub async fn clear_field(&mut self, id: &str, field: PlanField) -> Result<Value> {
        self.set_field(id, field, "").await
    }
    pub async fn set_user_flows(&mut self, id: &str, flows: Vec<PlanFlow>) -> Result<Value> {
        self.update(
            id,
            PlanPatch {
                user_flows: Some(flows),
                ..Default::default()
            },
        )
        .await
    }
    pub async fn list_dependencies(&mut self, id: &str) -> Result<Value> {
        let plan = self.resolve(id).await?;
        self.tasks
            .backend
            .request(
                Method::GET,
                &format!(
                    "/v1/user-plans/{}/dependencies",
                    string(&plan.raw, "plan_id")?
                ),
                None,
                None,
            )
            .await
    }
    pub async fn add_dependency(&mut self, id: &str, target: &DependencyTarget) -> Result<Value> {
        let plan = self.resolve(id).await?;
        let target_id = self.tasks.dependency_target(target).await?;
        let kind = match target.kind {
            WorkKind::Task => "task",
            WorkKind::Plan => "plan",
        };
        self.tasks
            .backend
            .request(
                Method::POST,
                &format!(
                    "/v1/user-plans/{}/dependencies",
                    string(&plan.raw, "plan_id")?
                ),
                Some(json!({"target_ref":format!("{kind}:{target_id}")})),
                None,
            )
            .await
    }
    pub async fn remove_dependency(
        &mut self,
        id: &str,
        target: &DependencyTarget,
    ) -> Result<Value> {
        let plan = self.resolve(id).await?;
        let target_id = self.tasks.dependency_target(target).await?;
        let kind = match target.kind {
            WorkKind::Task => "task",
            WorkKind::Plan => "plan",
        };
        self.tasks
            .backend
            .request(
                Method::DELETE,
                &format!(
                    "/v1/user-plans/{}/dependencies/{kind}/{target_id}",
                    string(&plan.raw, "plan_id")?
                ),
                None,
                None,
            )
            .await
    }
    /// Submit a locally encrypted immutable snapshot; approval is never written here.
    pub async fn create_revision(&mut self, id: &str) -> Result<Value> {
        let plan = self.resolve(id).await?;
        let mut snapshot = plan.public;
        for field in [
            "approval_state",
            "submitted_revision_id",
            "approved_revision_id",
        ] {
            snapshot
                .as_object_mut()
                .ok_or(Error::Protocol)?
                .remove(field);
        }
        let snapshot = serde_json::to_string(&snapshot)?;
        let value=self.tasks.backend.request(Method::POST,&format!("/v1/user-plans/{}/revisions",string(&plan.raw,"plan_id")?),Some(json!({"fingerprint":hash(&snapshot),"encrypted_snapshot":crypto::server_fields::encrypt_text(&snapshot,&plan.key, &[])?,"created_at":now()})),None).await?;
        if value["revision"]["revision_id"].as_str().is_none() {
            return Err(Error::Protocol);
        }
        Ok(value)
    }
    pub async fn list_revisions(&mut self, id: &str) -> Result<Vec<Value>> {
        let plan = self.resolve(id).await?;
        let value = self
            .tasks
            .backend
            .request(
                Method::GET,
                &format!("/v1/user-plans/{}/revisions", string(&plan.raw, "plan_id")?),
                None,
                None,
            )
            .await?;
        Ok(value["revisions"]
            .as_array()
            .ok_or(Error::Protocol)?
            .clone())
    }
    pub async fn approval_status(&mut self, id: &str) -> Result<Value> {
        let plan = self.resolve(id).await?;
        let value = self
            .tasks
            .backend
            .request(
                Method::GET,
                &format!(
                    "/v1/user-plans/{}/approval-status",
                    string(&plan.raw, "plan_id")?
                ),
                None,
                None,
            )
            .await?;
        value
            .get("approval")
            .filter(|v| v.is_object())
            .cloned()
            .ok_or(Error::Protocol)
    }
    /// Browser-session approval remains a separate human action in the protocol.
    pub async fn submit_for_review(&mut self, id: &str) -> Result<Value> {
        let plan = self.resolve(id).await?;
        let id = string(&plan.raw, "plan_id")?.to_owned();
        let value = self.create_revision(&id).await?;
        let revision = value["revision"].clone();
        let mut url =
            url::Url::parse(&self.tasks.backend.app_origin()).map_err(|_| Error::Protocol)?;
        url.set_path(&format!("/plans/{id}/review"));
        url.query_pairs_mut()
            .append_pair("revision", string(&revision, "revision_id")?);
        Ok(json!({"revision":revision,"review_url":url.as_str()}))
    }
    pub async fn add_verification_evidence(
        &mut self,
        id: &str,
        verification: &str,
        input: PlanVerificationEvidence,
    ) -> Result<Value> {
        if ![
            "proposed",
            "pending",
            "passed",
            "failed",
            "passed_unexpectedly",
            "skipped",
            "skipped_with_reason",
            "not_applicable",
            "waived",
        ]
        .contains(&input.status.as_str())
        {
            return Err(Error::Invalid("Invalid Plan verification evidence status."));
        }
        if input.score.flatten().is_some_and(|n| !n.is_finite())
            || input.threshold.flatten().is_some_and(|n| !n.is_finite())
        {
            return Err(Error::Invalid(
                "Plan scores and thresholds must be finite numbers.",
            ));
        }
        let plan = self.resolve(id).await?;
        let mut payload = json!({"status":input.status,"updated_at":now()});
        for (field, value) in [
            ("score", input.score.map(|v| json!(v))),
            ("threshold", input.threshold.map(|v| json!(v))),
            ("confidence", input.confidence.map(|v| json!(v))),
            ("run_id", input.run_id.map(|v| json!(v))),
        ] {
            if let Some(value) = value {
                payload[field] = value;
            }
        }
        for (field, text) in [
            ("result_summary", input.result_summary),
            ("required_fixes", input.required_fixes),
        ] {
            if let Some(text) = text {
                payload[format!("encrypted_{field}")] =
                    json!(crypto::server_fields::encrypt_text(&text, &plan.key, &[])?);
            }
        }
        let value = self
            .tasks
            .backend
            .request(
                Method::POST,
                &format!(
                    "/v1/user-plans/{}/verification/{}/evidence",
                    string(&plan.raw, "plan_id")?,
                    segment(verification)?
                ),
                Some(payload),
                None,
            )
            .await?;
        super::children::public::<PlanVerificationInput>(&value["verification"], &plan.key)
    }
    pub async fn get_verification_run(
        &mut self,
        id: &str,
        verification: &str,
        run: &str,
    ) -> Result<Value> {
        let plan = self.resolve(id).await?;
        self.tasks
            .backend
            .request(
                Method::GET,
                &format!(
                    "/v1/user-plans/{}/verification/{}/runs/{}",
                    string(&plan.raw, "plan_id")?,
                    segment(verification)?,
                    segment(run)?
                ),
                None,
                None,
            )
            .await
    }
    pub async fn show_learning(&mut self, id: &str, learning: &str) -> Result<Value> {
        self.list_learnings(id)
            .await?
            .into_iter()
            .find(|row| row["learning_id"] == learning)
            .ok_or(Error::Invalid("Plan learning is unavailable."))
    }
    pub async fn create_learning_tasks(
        &mut self,
        id: &str,
        selection: PlanLearningSelection,
    ) -> Result<Value> {
        if !selection.all && selection.learning_ids.is_empty() {
            return Err(Error::Invalid("Select at least one Plan learning."));
        }
        let plan = self.resolve(id).await?;
        let id = string(&plan.raw, "plan_id")?.to_owned();
        let learnings = self.list_learnings(&id).await?;
        for learning in learnings.iter().filter(|row| {
            selection.all
                || row["learning_id"]
                    .as_str()
                    .is_some_and(|id| selection.learning_ids.iter().any(|i| i == id))
        }) {
            if ["proposed", "accepted", "applied"]
                .contains(&learning["status"].as_str().unwrap_or(""))
                && learning["applied_task_id"].is_null()
            {
                super::children::safe_draft(learning["task_draft"].as_str().unwrap_or(""))?;
            }
        }
        let mut response=self.tasks.backend.request(Method::POST,&format!("/v1/user-plans/{id}/learnings/create-tasks"),Some(json!({"learning_ids":selection.learning_ids,"all":selection.all,"created_at":now(),"updated_at":now()})),None).await?;
        let tasks = response["tasks"].as_array().ok_or(Error::Protocol)?;
        let mut public = Vec::with_capacity(tasks.len());
        for task in tasks {
            if task["plan_id"] != id || task["source_plan_id"] != id {
                return Err(Error::Forbidden);
            }
            let source = task["source_learning_id"].as_str().ok_or(Error::Protocol)?;
            if !learnings.iter().any(|learning| {
                learning["learning_id"] == source
                    && (selection.all || selection.learning_ids.iter().any(|id| id == source))
            }) {
                return Err(Error::Forbidden);
            }
            public.push(task_crypto::decode_with_key(task.clone(), plan.key.clone())?.public);
        }
        response["tasks"] = json!(public);
        Ok(response)
    }
    pub async fn list_tasks(&mut self, id: &str) -> Result<Vec<Value>> {
        let plan = self.resolve(id).await?;
        let previous = self.tasks.filters.clone();
        self.tasks.filters = TaskFilters {
            personal: true,
            plan_id: Some(string(&plan.raw, "plan_id")?.into()),
            ..Default::default()
        };
        let result = self.tasks.list().await;
        self.tasks.filters = previous;
        result
    }
    pub async fn create_task(&mut self, id: &str, mut input: TaskCreate) -> Result<Value> {
        let plan = self.resolve(id).await?;
        input.plan_id = Some(string(&plan.raw, "plan_id")?.into());
        self.tasks.create(input).await
    }
    pub async fn update_task(&mut self, id: &str, task: &str, input: TaskPatch) -> Result<Value> {
        let plan = self.resolve(id).await?;
        let previous = self.tasks.filters.clone();
        self.tasks.filters = TaskFilters {
            personal: true,
            plan_id: Some(string(&plan.raw, "plan_id")?.into()),
            ..Default::default()
        };
        let result = self.tasks.update(task, input).await;
        self.tasks.filters = previous;
        result
    }
    pub async fn delete_task(&mut self, id: &str, task: &str, confirmed: bool) -> Result<Value> {
        let plan = self.resolve(id).await?;
        let previous = self.tasks.filters.clone();
        self.tasks.filters = TaskFilters {
            personal: true,
            plan_id: Some(string(&plan.raw, "plan_id")?.into()),
            ..Default::default()
        };
        let result = self.tasks.delete(task, confirmed).await;
        self.tasks.filters = previous;
        result
    }
    pub async fn check_assumption(
        &mut self,
        id: &str,
        assumption: &str,
        mut input: PlanAssumptionInput,
    ) -> Result<Value> {
        input.status = Some(input.status.unwrap_or_else(|| "checking".into()));
        self.update_assumption(id, assumption, input).await
    }
    pub async fn waive_assumption(
        &mut self,
        id: &str,
        assumption: &str,
        mut input: PlanAssumptionInput,
    ) -> Result<Value> {
        input.status = Some("waived".into());
        self.update_assumption(id, assumption, input).await
    }
    pub async fn inspect_reference_pattern(
        &mut self,
        id: &str,
        pattern: &str,
        mut input: PlanReferencePatternInput,
    ) -> Result<Value> {
        input.status = Some(input.status.unwrap_or_else(|| "inspected".into()));
        self.update_reference_pattern(id, pattern, input).await
    }
    pub async fn waive_reference_pattern(
        &mut self,
        id: &str,
        pattern: &str,
        mut input: PlanReferencePatternInput,
    ) -> Result<Value> {
        input.status = Some("waived".into());
        self.update_reference_pattern(id, pattern, input).await
    }
}
fn segment(id: &str) -> Result<String> {
    super::children::segment(id)
}

#[cfg(all(test, not(target_arch = "wasm32")))]
mod field_interop_tests {
    use super::*;
    use crate::work::tasks::tests::{client, mock};
    use crate::work::task_crypto::field_interop_support::{assert_web, case};
    const PLAN: &str = "aabbccdd-1111-4111-8111-aabbccddeeff";
    #[tokio::test]
    async fn actual_revision_and_evidence_requests_read_in_web_legacy_decoders() {
        let key = [33; 32];
        let mut raw = encode_create(&PlanCreate { plan_id: Some(PLAN.into()), title: "Private plan".into(), goal: "Accepted goal".into(), ..Default::default() }, &key, &[7; 32]).unwrap();
        raw["key_wrappers"] = json!([{"key_type":"master","encrypted_plan_key":crypto::encrypt_bytes(&key,&[7;32]).unwrap()}]);
        let mut snapshot = decode(raw.clone(), &[7; 32]).unwrap().public;
        for field in ["approval_state", "submitted_revision_id", "approved_revision_id"] { snapshot.as_object_mut().unwrap().remove(field); }
        let expected = serde_json::to_string(&snapshot).unwrap();
        let (api, server) = mock(vec![json!({"plan":raw}), json!({"revision":{"revision_id":"fixture"}}), json!({"plan":raw}), json!({"verification":{}})]).await;
        let mut client = client(&api);
        client.plans().create_revision(PLAN).await.unwrap();
        client.plans().add_verification_evidence(PLAN, "fixture", PlanVerificationEvidence { status: "passed".into(), result_summary: Some("Private result".into()), required_fixes: Some("Private fixes".into()), ..Default::default() }).await.unwrap();
        let requests = server.await.unwrap();
        assert_eq!(requests.len(), 4);
        let revision: Value = serde_json::from_str(requests[1].split("\r\n\r\n").nth(1).unwrap()).unwrap();
        let evidence: Value = serde_json::from_str(requests[3].split("\r\n\r\n").nth(1).unwrap()).unwrap();
        assert_eq!(revision["fingerprint"], hash(&expected));
        assert_web(vec![case("revision.snapshot", "object-text", revision["encrypted_snapshot"].as_str().unwrap(), &key, expected.as_bytes(), ""),
            case("verification.result", "object-text", evidence["encrypted_result_summary"].as_str().unwrap(), &key, b"Private result", ""),
            case("verification.fixes", "object-text", evidence["encrypted_required_fixes"].as_str().unwrap(), &key, b"Private fixes", "")]);
    }
}
