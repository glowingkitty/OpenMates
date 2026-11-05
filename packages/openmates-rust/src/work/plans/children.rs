//! Fixed Plan child namespaces. Plaintext private content is encrypted locally.
use super::*;
pub(super) trait Child: Serialize {
    const ROUTE: &'static str;
    const ONE: &'static str;
    const MANY: &'static str;
    const ID: &'static str;
    const REQUIRED: &'static str;
    const PRIVATE: &'static [&'static str];
    fn validate(&self) -> Result<()> {
        Ok(())
    }
}
#[derive(Clone, Default, Serialize, Deserialize)]
#[serde(default, deny_unknown_fields)]
pub struct PlanCriterionInput {
    #[serde(skip_serializing_if = "Option::is_none")]
    pub criterion_id: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub text: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub r#type: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub status: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub required: Option<bool>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub linked_task_ids: Option<Vec<String>>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub verification_ids: Option<Vec<String>>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub evidence: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub coverage_note: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub waiver_reason: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub coverage_status: Option<String>,
    #[serde(
        skip_serializing_if = "Option::is_none",
        deserialize_with = "super::nullable"
    )]
    pub verification_scope: Option<Option<String>>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub version: Option<u64>,
}
impl Child for PlanCriterionInput {
    const ROUTE: &'static str = "criteria";
    const ONE: &'static str = "criterion";
    const MANY: &'static str = "criteria";
    const ID: &'static str = "criterion_id";
    const REQUIRED: &'static str = "text";
    const PRIVATE: &'static [&'static str] =
        &["text", "evidence", "coverage_note", "waiver_reason"];
}
impl Plans<'_> {
    pub async fn create_criterion(
        &mut self,
        plan: &str,
        input: PlanCriterionInput,
    ) -> Result<Value> {
        self.child_write(plan, None, Method::POST, input).await
    }
    pub async fn update_criterion(
        &mut self,
        plan: &str,
        id: &str,
        input: PlanCriterionInput,
    ) -> Result<Value> {
        self.child_write(plan, Some(id), Method::PATCH, input).await
    }
    pub async fn list_criteria(&mut self, plan: &str) -> Result<Vec<Value>> {
        self.child_list::<PlanCriterionInput>(plan).await
    }
    pub async fn delete_criterion(&mut self, plan: &str, id: &str) -> Result<Value> {
        self.child_delete::<PlanCriterionInput>(plan, id).await
    }
}
#[derive(Clone, Default, Serialize, Deserialize)]
#[serde(default, deny_unknown_fields)]
pub struct PlanAssumptionInput {
    #[serde(skip_serializing_if = "Option::is_none")]
    pub assumption_id: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub text: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub category: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub status: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub required_before: Option<String>,
    #[serde(deserialize_with = "super::nullable")]
    #[serde(skip_serializing_if = "Option::is_none")]
    pub linked_sub_chat_id: Option<Option<String>>,
    #[serde(deserialize_with = "super::nullable")]
    #[serde(skip_serializing_if = "Option::is_none")]
    pub linked_task_id: Option<Option<String>>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub linked_criterion_ids: Option<Vec<String>>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub source_count: Option<u32>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub corrected_text: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub evidence_summary: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub blocker_reason: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub waiver_reason: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub sources: Option<String>,
}
impl Child for PlanAssumptionInput {
    const ROUTE: &'static str = "assumptions";
    const ONE: &'static str = "assumption";
    const MANY: &'static str = "assumptions";
    const ID: &'static str = "assumption_id";
    const REQUIRED: &'static str = "text";
    const PRIVATE: &'static [&'static str] = &[
        "text",
        "corrected_text",
        "evidence_summary",
        "blocker_reason",
        "waiver_reason",
        "sources",
    ];
}
impl Plans<'_> {
    pub async fn create_assumption(
        &mut self,
        plan: &str,
        input: PlanAssumptionInput,
    ) -> Result<Value> {
        self.child_write(plan, None, Method::POST, input).await
    }
    pub async fn update_assumption(
        &mut self,
        plan: &str,
        id: &str,
        input: PlanAssumptionInput,
    ) -> Result<Value> {
        self.child_write(plan, Some(id), Method::PATCH, input).await
    }
    pub async fn list_assumptions(&mut self, plan: &str) -> Result<Vec<Value>> {
        self.child_list::<PlanAssumptionInput>(plan).await
    }
    pub async fn delete_assumption(&mut self, plan: &str, id: &str) -> Result<Value> {
        self.child_delete::<PlanAssumptionInput>(plan, id).await
    }
}
#[derive(Clone, Default, Serialize, Deserialize)]
#[serde(default, deny_unknown_fields)]
pub struct PlanReferencePatternInput {
    #[serde(skip_serializing_if = "Option::is_none")]
    pub pattern_id: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub title: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub description: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub category: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub status: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub required_before: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub source_count: Option<u32>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub linked_task_ids: Option<Vec<String>>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub linked_check_ids: Option<Vec<String>>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub sources: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub match_rules: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub anti_patterns: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub evidence_summary: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub waiver_reason: Option<String>,
}
impl Child for PlanReferencePatternInput {
    const ROUTE: &'static str = "reference-patterns";
    const ONE: &'static str = "reference_pattern";
    const MANY: &'static str = "reference_patterns";
    const ID: &'static str = "pattern_id";
    const REQUIRED: &'static str = "title";
    const PRIVATE: &'static [&'static str] = &[
        "title",
        "description",
        "sources",
        "match_rules",
        "anti_patterns",
        "evidence_summary",
        "waiver_reason",
    ];
}
impl Plans<'_> {
    pub async fn create_reference_pattern(
        &mut self,
        plan: &str,
        input: PlanReferencePatternInput,
    ) -> Result<Value> {
        self.child_write(plan, None, Method::POST, input).await
    }
    pub async fn update_reference_pattern(
        &mut self,
        plan: &str,
        id: &str,
        input: PlanReferencePatternInput,
    ) -> Result<Value> {
        self.child_write(plan, Some(id), Method::PATCH, input).await
    }
    pub async fn list_reference_patterns(&mut self, plan: &str) -> Result<Vec<Value>> {
        self.child_list::<PlanReferencePatternInput>(plan).await
    }
    pub async fn delete_reference_pattern(&mut self, plan: &str, id: &str) -> Result<Value> {
        self.child_delete::<PlanReferencePatternInput>(plan, id)
            .await
    }
}
#[derive(Clone, Default, Serialize, Deserialize)]
#[serde(default, deny_unknown_fields)]
pub struct PlanVerificationInput {
    #[serde(skip_serializing_if = "Option::is_none")]
    pub verification_id: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub kind: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub phase: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub status: Option<String>,
    #[serde(deserialize_with = "super::nullable")]
    #[serde(skip_serializing_if = "Option::is_none")]
    pub lifecycle_status: Option<Option<String>>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub required_for_done: Option<bool>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub covers: Option<Vec<String>>,
    #[serde(deserialize_with = "super::nullable")]
    #[serde(skip_serializing_if = "Option::is_none")]
    pub source_hash: Option<Option<String>>,
    #[serde(deserialize_with = "super::nullable")]
    #[serde(skip_serializing_if = "Option::is_none")]
    pub threshold: Option<Option<f64>>,
    #[serde(deserialize_with = "super::nullable")]
    #[serde(skip_serializing_if = "Option::is_none")]
    pub score: Option<Option<f64>>,
    #[serde(deserialize_with = "super::nullable")]
    #[serde(skip_serializing_if = "Option::is_none")]
    pub confidence: Option<Option<String>>,
    #[serde(deserialize_with = "super::nullable")]
    #[serde(skip_serializing_if = "Option::is_none")]
    pub linked_sub_chat_id: Option<Option<String>>,
    #[serde(deserialize_with = "super::nullable")]
    #[serde(skip_serializing_if = "Option::is_none")]
    pub source_embed_id: Option<Option<String>>,
    #[serde(deserialize_with = "super::nullable")]
    #[serde(skip_serializing_if = "Option::is_none")]
    pub runner_kind: Option<Option<String>>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub description: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub command: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub evaluation_prompt: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub evaluator_instructions: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub expected_result: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub source_path: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub red_phase_reason: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub linked_task_id: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub run_id: Option<String>,
}
impl Child for PlanVerificationInput {
    const ROUTE: &'static str = "verification";
    const ONE: &'static str = "verification";
    const MANY: &'static str = "verifications";
    const ID: &'static str = "verification_id";
    const REQUIRED: &'static str = "kind";
    const PRIVATE: &'static [&'static str] = &[
        "description",
        "command",
        "evaluation_prompt",
        "evaluator_instructions",
        "expected_result",
        "source_path",
        "red_phase_reason",
    ];
    fn validate(&self) -> Result<()> {
        if self.score.flatten().is_some_and(|n| !n.is_finite())
            || self.threshold.flatten().is_some_and(|n| !n.is_finite())
        {
            Err(Error::Invalid(
                "Plan scores and thresholds must be finite numbers.",
            ))
        } else {
            Ok(())
        }
    }
}

impl Plans<'_> {
    pub async fn create_verification(
        &mut self,
        plan: &str,
        input: PlanVerificationInput,
    ) -> Result<Value> {
        self.child_write(plan, None, Method::POST, input).await
    }
    pub async fn update_verification(
        &mut self,
        plan: &str,
        id: &str,
        input: PlanVerificationInput,
    ) -> Result<Value> {
        self.child_write(plan, Some(id), Method::PATCH, input).await
    }
    pub async fn list_verifications(&mut self, plan: &str) -> Result<Vec<Value>> {
        self.child_list::<PlanVerificationInput>(plan).await
    }
    pub async fn delete_verification(&mut self, plan: &str, id: &str) -> Result<Value> {
        self.child_delete::<PlanVerificationInput>(plan, id).await
    }
}
#[derive(Clone, Default, Serialize, Deserialize)]
#[serde(default, deny_unknown_fields)]
pub struct PlanLearningInput {
    #[serde(skip_serializing_if = "Option::is_none")]
    pub learning_id: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub r#type: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub target_kind: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub status: Option<String>,
    #[serde(deserialize_with = "super::nullable")]
    #[serde(skip_serializing_if = "Option::is_none")]
    pub severity: Option<Option<String>>,
    #[serde(deserialize_with = "super::nullable")]
    #[serde(skip_serializing_if = "Option::is_none")]
    pub confidence: Option<Option<String>>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub linked_task_ids: Option<Vec<String>>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub linked_check_ids: Option<Vec<String>>,
    #[serde(deserialize_with = "super::nullable")]
    #[serde(skip_serializing_if = "Option::is_none")]
    pub applied_task_id: Option<Option<String>>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub title: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub observation: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub root_cause: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub suggested_change: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub evidence_summary: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub task_draft: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub rejection_reason: Option<String>,
}
impl Child for PlanLearningInput {
    const ROUTE: &'static str = "learnings";
    const ONE: &'static str = "learning";
    const MANY: &'static str = "learnings";
    const ID: &'static str = "learning_id";
    const REQUIRED: &'static str = "title";
    const PRIVATE: &'static [&'static str] = &[
        "title",
        "observation",
        "root_cause",
        "suggested_change",
        "evidence_summary",
        "task_draft",
        "rejection_reason",
    ];
}
impl Plans<'_> {
    pub async fn create_learning(&mut self, plan: &str, input: PlanLearningInput) -> Result<Value> {
        self.child_write(plan, None, Method::POST, input).await
    }
    pub async fn update_learning(
        &mut self,
        plan: &str,
        id: &str,
        input: PlanLearningInput,
    ) -> Result<Value> {
        self.child_write(plan, Some(id), Method::PATCH, input).await
    }
    pub async fn list_learnings(&mut self, plan: &str) -> Result<Vec<Value>> {
        self.child_list::<PlanLearningInput>(plan).await
    }
    pub async fn delete_learning(&mut self, plan: &str, id: &str) -> Result<Value> {
        self.child_delete::<PlanLearningInput>(plan, id).await
    }
}

pub(super) fn segment(id: &str) -> Result<String> {
    if id.is_empty() || id.len() > 512 || id.chars().any(char::is_control) {
        return Err(Error::Invalid("Invalid Plan child identifier."));
    }
    Ok(url::form_urlencoded::byte_serialize(id.as_bytes()).collect())
}
fn encode<C: Child>(input: C, key: &[u8; 32], create: bool) -> Result<Value> {
    input.validate()?;
    let mut input = serde_json::to_value(input)?;
    let input = input.as_object_mut().ok_or(Error::Protocol)?;
    if create {
        if C::ONE == "criterion"
            && ["evidence", "coverage_note", "waiver_reason", "version"]
                .iter()
                .any(|key| input.contains_key(*key))
            || C::ONE == "verification"
                && ["linked_task_id", "run_id"]
                    .iter()
                    .any(|key| input.contains_key(*key))
        {
            return Err(Error::Unavailable {
                code: "plan_field_unavailable",
                reason: "PLAN_FIELD_NOT_SUPPORTED_BY_CURRENT_PROTOCOL",
            });
        }
        if C::ONE == "learning"
            && ["type", "target_kind"].iter().any(|key| {
                input
                    .get(*key)
                    .and_then(Value::as_str)
                    .is_none_or(str::is_empty)
            })
        {
            return Err(Error::Invalid(
                "Learning type and target kind are required.",
            ));
        }
        if input
            .get(C::REQUIRED)
            .and_then(Value::as_str)
            .is_none_or(|s| s.trim().is_empty())
        {
            return Err(Error::Invalid(
                "Required Plan child text or kind is missing.",
            ));
        }
        input
            .entry(C::ID)
            .or_insert_with(|| json!(uuid::Uuid::new_v4().to_string()));
        input.insert("created_at".into(), json!(now()));
    } else {
        input.remove(C::ID);
        let allowed: &[&str] = match C::ONE {
            "criterion" => &[
                "status",
                "evidence",
                "coverage_note",
                "waiver_reason",
                "verification_ids",
                "coverage_status",
                "verification_scope",
                "version",
            ],
            "assumption" => &[
                "status",
                "required_before",
                "linked_sub_chat_id",
                "linked_task_id",
                "source_count",
                "corrected_text",
                "evidence_summary",
                "blocker_reason",
                "waiver_reason",
                "sources",
            ],
            "reference_pattern" => &[
                "status",
                "required_before",
                "source_count",
                "linked_task_ids",
                "linked_check_ids",
                "description",
                "sources",
                "match_rules",
                "anti_patterns",
                "evidence_summary",
                "waiver_reason",
            ],
            "verification" => &[
                "kind",
                "phase",
                "status",
                "lifecycle_status",
                "required_for_done",
                "covers",
                "source_hash",
                "threshold",
                "score",
                "confidence",
                "linked_sub_chat_id",
                "source_embed_id",
                "runner_kind",
                "description",
                "command",
                "evaluation_prompt",
                "evaluator_instructions",
                "expected_result",
                "source_path",
                "red_phase_reason",
            ],
            "learning" => &[
                "status",
                "severity",
                "confidence",
                "linked_task_ids",
                "linked_check_ids",
                "applied_task_id",
                "title",
                "observation",
                "root_cause",
                "suggested_change",
                "evidence_summary",
                "task_draft",
                "rejection_reason",
            ],
            _ => return Err(Error::Protocol),
        };
        if input.keys().any(|field| !allowed.contains(&field.as_str())) {
            return Err(Error::Unavailable {
                code: "plan_field_unavailable",
                reason: "PLAN_FIELD_NOT_SUPPORTED_BY_CURRENT_PROTOCOL",
            });
        }
    }
    input.insert("updated_at".into(), json!(now()));
    if let Some(draft) = input.get("task_draft").and_then(Value::as_str) {
        safe_draft(draft)?;
    }
    for field in C::PRIVATE {
        if let Some(value) = input.remove(*field) {
            let text = value.as_str().ok_or(Error::Protocol)?;
            if text.len() > 1_000_000 {
                return Err(Error::Invalid(
                    "Plan child text exceeds the supported limit.",
                ));
            }
            input.insert(
                format!("encrypted_{field}"),
                json!(crypto::server_fields::encrypt_text(text, key, &[])?),
            );
        }
    }
    Ok(Value::Object(input.clone()))
}
pub(super) fn public<C: Child>(raw: &Value, key: &[u8; 32]) -> Result<Value> {
    if !raw.is_object() {
        return Err(Error::Protocol);
    }
    let mut value = json!({});
    for (field, v) in raw.as_object().ok_or(Error::Protocol)? {
        if !field.starts_with("encrypted_") && !field.starts_with("hashed_") {
            value[field] = v.clone();
        }
    }
    for field in C::PRIVATE {
        value[*field] = json!(task_crypto::text(raw, &format!("encrypted_{field}"), key)?);
    }
    for field in ["result_summary", "required_fixes"] {
        if raw.get(format!("encrypted_{field}")).is_some() {
            value[field] = json!(task_crypto::text(raw, &format!("encrypted_{field}"), key)?);
        }
    }
    Ok(value)
}
pub(super) fn safe_draft(text: &str) -> Result<()> {
    if text.chars().any(|c|(c.is_control()&&!['\t','\r','\n'].contains(&c))||matches!(c,'\u{200b}'..='\u{200f}'|'\u{202a}'..='\u{202e}'|'\u{2060}'..='\u{206f}'))||regex::Regex::new(r"(?i)\b(ignore (all|previous) instructions|system prompt|developer message|exfiltrat|reveal secrets?|api[_-]?key|access[_-]?token|refresh[_-]?token|password|private key|rm\s+-rf|drop\s+database|delete\s+production|force[- ]?push)\b").expect("constant learning safety pattern").is_match(text){return Err(Error::Invalid("Learning Task draft contains unsafe credential, control or destructive instructions."))}
    Ok(())
}
impl Plans<'_> {
    async fn child_list<C: Child>(&mut self, id: &str) -> Result<Vec<Value>> {
        let plan = self.resolve(id).await?;
        let data = self
            .tasks
            .backend
            .request(
                Method::GET,
                &format!(
                    "/v1/user-plans/{}/{}",
                    string(&plan.raw, "plan_id")?,
                    C::ROUTE
                ),
                None,
                None,
            )
            .await?;
        data[C::MANY]
            .as_array()
            .ok_or(Error::Protocol)?
            .iter()
            .map(|row| public::<C>(row, &plan.key))
            .collect()
    }
    async fn child_write<C: Child>(
        &mut self,
        id: &str,
        child: Option<&str>,
        method: Method,
        input: C,
    ) -> Result<Value> {
        let plan = self.resolve(id).await?;
        let child = child.map(segment).transpose()?;
        let path = format!(
            "/v1/user-plans/{}/{}{}",
            string(&plan.raw, "plan_id")?,
            C::ROUTE,
            child
                .as_ref()
                .map(|id| format!("/{id}"))
                .unwrap_or_default()
        );
        let payload = encode(input, &plan.key, child.is_none())?;
        let data = self
            .tasks
            .backend
            .request(method, &path, Some(payload), None)
            .await?;
        public::<C>(&data[C::ONE], &plan.key)
    }
    async fn child_delete<C: Child>(&mut self, id: &str, child: &str) -> Result<Value> {
        let plan = self.resolve(id).await?;
        self.tasks
            .backend
            .request(
                Method::DELETE,
                &format!(
                    "/v1/user-plans/{}/{}/{}",
                    string(&plan.raw, "plan_id")?,
                    C::ROUTE,
                    segment(child)?
                ),
                None,
                None,
            )
            .await
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn missing_and_explicit_null_are_distinct_and_fractional_values_survive() {
        let omitted = encode(
            PlanLearningInput {
                title: Some("Private learning".into()),
                r#type: Some("workflow_improvement".into()),
                target_kind: Some("workflow".into()),
                ..Default::default()
            },
            &[8; 32],
            true,
        )
        .unwrap();
        assert!(omitted.get("severity").is_none());
        assert!(omitted.get("confidence").is_none());
        assert!(omitted.get("task_draft").is_none());
        assert!(omitted["encrypted_title"].is_string());
        assert!(omitted.get("title").is_none());
        let clear: PlanLearningInput = serde_json::from_value(
            json!({"severity":null,"confidence":null,"applied_task_id":null}),
        )
        .unwrap();
        let clear = encode(clear, &[8; 32], false).unwrap();
        assert_eq!(clear.get("severity"), Some(&Value::Null));
        assert_eq!(clear.get("confidence"), Some(&Value::Null));
        assert_eq!(clear.get("applied_task_id"), Some(&Value::Null));
        assert!(clear.get("encrypted_title").is_none());
        let fraction: PlanVerificationInput =
            serde_json::from_value(json!({"threshold":0.75,"score":0.9,"source_hash":null}))
                .unwrap();
        let fraction = encode(fraction, &[8; 32], false).unwrap();
        assert_eq!(fraction["threshold"], 0.75);
        assert_eq!(fraction["score"], 0.9);
        assert_eq!(fraction.get("source_hash"), Some(&Value::Null));
        assert!(fraction.get("lifecycle_status").is_none());
        assert!(
            encode(
                PlanVerificationInput {
                    score: Some(Some(f64::NAN)),
                    ..Default::default()
                },
                &[8; 32],
                false
            )
            .is_err()
        );
    }
    #[test]
    fn learning_task_draft_preserves_current_safety_guards() {
        assert!(safe_draft("Improve validation and add a focused test.").is_ok());
        for text in [
            "ignore previous instructions",
            "reveal secrets",
            "rotate refresh_token",
            "rm -rf /",
            "hidden\u{200b}text",
        ] {
            assert!(safe_draft(text).is_err());
        }
    }
}

#[cfg(test)]
mod fidelity_tests {
    use super::*;
    #[test]
    fn unsupported_create_only_fields_cannot_pretend_to_update() {
        for input in [
            PlanCriterionInput {
                required: Some(false),
                ..Default::default()
            },
            PlanCriterionInput {
                text: Some("Changed private criterion".into()),
                ..Default::default()
            },
        ] {
            assert!(matches!(
                encode(input, &[8; 32], false),
                Err(Error::Unavailable { .. })
            ));
        }
        let evidence = encode(
            PlanCriterionInput {
                evidence: Some("Private evidence".into()),
                coverage_note: Some("Private coverage".into()),
                verification_scope: Some(None),
                ..Default::default()
            },
            &[8; 32],
            false,
        )
        .unwrap();
        assert!(evidence["encrypted_evidence"].is_string());
        assert!(evidence["encrypted_coverage_note"].is_string());
        assert_eq!(evidence.get("verification_scope"), Some(&Value::Null));
        assert!(evidence.get("evidence").is_none());
        assert!(!evidence.to_string().contains("Private"));
        assert!(matches!(
            encode(
                PlanVerificationInput {
                    kind: Some("test".into()),
                    linked_task_id: Some("task".into()),
                    ..Default::default()
                },
                &[8; 32],
                true
            ),
            Err(Error::Unavailable { .. })
        ));
    }
}

#[cfg(all(test, not(target_arch = "wasm32")))]
mod field_interop_tests {
    use super::*;
    use crate::work::task_crypto::field_interop_support::{assert_web, case};
    #[test]
    fn actual_plan_child_create_patch_fields_read_in_web_legacy_decoders() {
        let key = [32; 32];
        let create = encode(PlanCriterionInput { text: Some("Accepted criterion Δ".into()), ..Default::default() }, &key, true).unwrap();
        let patch = encode(PlanCriterionInput { evidence: Some("Private evidence".into()), coverage_note: Some("Exact coverage".into()), waiver_reason: Some("Explicit waiver".into()), ..Default::default() }, &key, false).unwrap();
        let mut cases = vec![case("criterion.text", "object-text", create["encrypted_text"].as_str().unwrap(), &key, b"Accepted criterion \xce\x94", "")];
        for (field, text) in [("evidence", "Private evidence"), ("coverage_note", "Exact coverage"), ("waiver_reason", "Explicit waiver")] {
            cases.push(case(field, "object-text", patch[format!("encrypted_{field}")].as_str().unwrap(), &key, text.as_bytes(), ""));
        }
        assert_web(cases);
        assert!(create.get("text").is_none());
        assert!(patch.get("evidence").is_none());
    }
}
