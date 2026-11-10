//! Turn-bound observations; receiving metadata never proves durable completion.
use super::*;

#[derive(Default)]
pub(super) struct SendObservations {
    pub(super) category: Option<String>,
    pub(super) model: Option<String>,
    pub(super) mate: Option<String>,
    pub(super) suggestions: Vec<String>,
    pub(super) recommendations: Vec<Value>,
    pub(super) suggested: Option<Option<String>>,
    pub(super) proposals: Vec<Value>,
    pub(super) updates: Vec<Value>,
    pub(super) events: Vec<Value>,
    pub(super) jobs: BTreeMap<String, Value>,
    pub(super) subchats: Vec<Value>,
    pub(super) memories: Vec<SendMemoryRequest>,
    pub(super) usage: Option<Value>,
    pub(super) budget: Option<Value>,
    pub(super) project_create: super::project_create_request::ProjectCreateState,
}
impl SendObservations {
    /// The caller establishes current chat/user/turn/task ownership first.
    pub(super) fn capture_owned(&mut self, kind: &str, p: &Value) -> Result<()> {
        for (key, target) in [
            ("category", &mut self.category),
            ("model_name", &mut self.model),
            ("mate_name", &mut self.mate),
        ] {
            if let Some(value) = p[key].as_str().filter(|v| !v.is_empty()) {
                *target = Some(value.to_owned());
            }
        }
        let mut usage = serde_json::Map::new();
        for (wire, public) in [
            ("prompt_tokens", "promptTokens"),
            ("completion_tokens", "completionTokens"),
            ("user_input_tokens", "userInputTokens"),
            ("system_prompt_tokens", "systemPromptTokens"),
            ("total_credits", "totalCredits"),
        ] {
            if p[wire].as_f64().is_some_and(|v| v.is_finite() && v >= 0.0) {
                usage.insert(public.into(), p[wire].clone());
                if wire == "system_prompt_tokens" {
                    self.budget = Some(json!({"systemPromptTokens":p[wire]}));
                }
            }
        }
        if p["llm_usage_breakdown"].is_object() && p["llm_usage_breakdown"]["schema_version"] == 1 {
            usage.insert("llmUsageBreakdown".into(), p["llm_usage_breakdown"].clone());
        }
        if !usage.is_empty() {
            self.usage = Some(Value::Object(usage));
        }
        if p["is_final_chunk"] == true || kind == "ai_background_response_completed" {
            if let Some(value) = p["suggested_followup_message"].as_str() {
                let value: String = value.trim().chars().take(400).collect();
                self.suggested = Some((!value.is_empty()).then_some(value));
            } else if p
                .get("suggested_followup_message")
                .is_some_and(Value::is_null)
            {
                self.suggested = Some(None);
            }
        }
        if matches!(
            kind,
            "post_processing_completed" | "post_processing_metadata"
        ) {
            if let Some(rows) = p["follow_up_request_suggestions"].as_array() {
                self.suggestions = rows
                    .iter()
                    .filter_map(Value::as_str)
                    .filter(|v| !v.is_empty())
                    .map(str::to_owned)
                    .collect();
            }
            if let Some(rows) = p["recommendations"].as_array() {
                // Only well-formed rows survive so CLI output never shows junk.
                self.recommendations = super::recommendations::recommendations_from_payload(rows)
                    .iter()
                    .filter_map(|row| serde_json::to_value(row).ok())
                    .collect();
            }
            for (wire, target) in [
                ("task_proposals", &mut self.proposals),
                ("task_update_proposals", &mut self.updates),
            ] {
                if let Some(rows) = p[wire].as_array() {
                    *target = rows.iter().filter(|v| v.is_object()).cloned().collect();
                }
            }
        }
        if kind == "task_event"
            && ["event_id", "task_id", "event_type"]
                .iter()
                .all(|key| p[*key].is_string())
            && !self
                .events
                .iter()
                .any(|previous| previous["event_id"] == p["event_id"])
        {
            self.events.push(p.clone());
        }
        if kind.starts_with("sub_chat_") && kind != "sub_chat_confirmation_required" {
            self.subchats.push(json!({"type":kind,"payload":p}));
        }
        if self.events.len() > 1024
            || self.subchats.len() > 1024
            || self.proposals.len() > 256
            || self.updates.len() > 256
            || self.suggestions.len() > 256
        {
            return Err(Error::Protocol);
        }
        Ok(())
    }
    pub(super) fn capture_jobs(&mut self, payload: &Value, chat: &str) -> Result<()> {
        let rows = payload["jobs"].as_array().ok_or(Error::Protocol)?;
        if rows.len() > 256 {
            return Err(Error::Protocol);
        }
        for row in rows {
            if row["chat_id"].as_str() != Some(chat) {
                continue;
            }
            let id = required(row, "job_id")?;
            required(row, "task_id")?;
            for field in ["revision", "task_key_version", "expires_at"] {
                row[field].as_u64().ok_or(Error::Protocol)?;
            }
            self.jobs.insert(id.into(), row.clone());
        }
        if self.jobs.len() > 256 {
            return Err(Error::Protocol);
        }
        Ok(())
    }
    pub(super) fn finish(
        self,
        chat: Chat,
        user: &str,
        assistant: Option<&str>,
        status: SendStatus,
    ) -> SendOutcome {
        let content = assistant
            .and_then(|id| chat.messages.iter().find(|m| m.id == id))
            .map(|m| m.content.clone())
            .unwrap_or_default();
        // Like the npm CLI, the mate comes from the category when the server omits it.
        let mate_name = self.mate.or_else(|| {
            self.category
                .as_deref()
                .and_then(super::search::mate_name)
                .map(str::to_owned)
        });
        SendOutcome {
            chat_id: chat.id.clone(),
            chat,
            status,
            message_id: assistant.map(str::to_owned),
            user_message_id: Some(user.into()),
            queue_mode: None,
            queue_revision: None,
            assistant: content,
            category: self.category,
            model_name: self.model,
            mate_name,
            follow_up_suggestions: self.suggestions,
            recommendations: self.recommendations,
            suggested_followup_message: self.suggested,
            task_proposals: self.proposals,
            task_update_proposals: self.updates,
            task_events: self.events,
            pending_task_update_jobs: self.jobs.into_values().collect(),
            sub_chat_events: self.subchats,
            app_settings_memory_requests: self.memories,
            token_usage: self.usage,
            prompt_budget: self.budget,
            project_creations: self.project_create.cards(),
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    // contract-test: supporting surface=cli assertions=billing.usage.receipt-token-breakdown
    #[test]
    fn metrics_keep_only_valid_observations_and_final_suggestion_is_bounded() {
        let mut observed = SendObservations::default();
        observed.capture_owned("ai_message_update",&json!({"category":"software_development","model_name":"observed-model","prompt_tokens":24,"completion_tokens":-2,"system_prompt_tokens":10,"total_credits":0.25,"is_final_chunk":true,"suggested_followup_message":" x ","llm_usage_breakdown":{"schema_version":2}})).unwrap();
        assert_eq!(
            observed.usage,
            Some(json!({"promptTokens":24,"systemPromptTokens":10,"totalCredits":0.25}))
        );
        assert_eq!(observed.budget, Some(json!({"systemPromptTokens":10})));
        assert_eq!(observed.suggested, Some(Some("x".into())));
        observed
            .capture_owned(
                "ai_message_update",
                &json!({"is_final_chunk":true,"suggested_followup_message":"x".repeat(401)}),
            )
            .unwrap();
        assert_eq!(observed.suggested.unwrap().unwrap().len(), 400);
    }
    #[test]
    fn post_processing_recommendations_keep_only_well_formed_rows() {
        let mut observed = SendObservations::default();
        let good = json!({"id":"r1","kind":"memory","action":"create","target_id":null,"title":"T","summary":"S"});
        observed
            .capture_owned(
                "post_processing_completed",
                &json!({"recommendations":[good,{"id":"bad"},"x"]}),
            )
            .unwrap();
        assert_eq!(observed.recommendations, vec![good.clone()]);
        // Other frame kinds never touch the field.
        observed
            .capture_owned("ai_message_update", &json!({"recommendations":[]}))
            .unwrap();
        assert_eq!(observed.recommendations.len(), 1);
        let outcome = observed.finish(Chat::default(), "u", None, SendStatus::Completed);
        assert_eq!(outcome.recommendations, vec![good]);
    }
    #[test]
    fn jobs_require_exact_chat_and_remain_pending_without_a_persistence_receipt() {
        let mut observed = SendObservations::default();
        observed.capture_jobs(&json!({"jobs":[{"chat_id":"other","job_id":"wrong"},{"chat_id":"chat","job_id":"job","task_id":"task","revision":2,"task_key_version":1,"expires_at":42}]}),"chat").unwrap();
        assert_eq!(observed.jobs.len(), 1);
        let result = observed.finish(
            Chat {
                id: "chat".into(),
                ..Chat::default()
            },
            "human",
            None,
            SendStatus::Completed,
        );
        assert_eq!(result.pending_task_update_jobs[0]["job_id"], "job");
        assert_eq!(result.message_id, None);
    }
}
