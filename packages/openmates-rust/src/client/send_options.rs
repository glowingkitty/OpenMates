//! Pure chat-send options and observed response metadata.
//!
//! Contract sources: `openmates-cli/src/client.ts::sendMessage` and
//! `openmates-cli/src/cli.ts::sendMessageStreaming`. This module performs no
//! network, terminal, environment, profile, or model-selection operations.
//!
//! Option inventory (a DTO field alone does not imply transport support):
//! - `slug`: encrypted chat slug; CLI `--slug`, new chats only.
//! - `project_id`: canonical authorized Project UUID; CLI resolves `--project`
//!   before sending. Project focus/context and write policy remain mandatory.
//! - `incognito`: `messagePayload.is_incognito`; it also disables admission,
//!   persistence and history retention, rather than merely changing this flag.
//! - `pii_detection`: controls local privacy preparation, never a model option.
//! - `task_update_jobs`: controls socket capabilities and encrypted job execution;
//!   disabling it must not report received jobs as successfully persisted.
//! - `response_timeout_ms`: positive timeout up to one day for response and
//!   confirmation waits. Bounded to prevent timer overflow/unbounded waits.
//! - consent policies: `--auto-approve` / `--auto-approve-memories` explicitly
//!   approve only fresh server-requested categories or the proposed batch.
//!
//! CLI-only work remains outside these options: JSON/human presentation,
//! `--followup` selection, `--accept-task-proposals` post-actions, Team/personal
//! scope, `chat --goal` Plan creation, attachments/mentions and anonymous Learning
//! Mode. There is intentionally no model or provider override.
//!
//! Observed metadata inventory (`ws.ts::collectAiResponse`):
//! - Turn-bound `ai_message_update` / `ai_background_response_completed` carry
//!   assistant message ID, category, model name and final response content.
//! - Final `suggested_followup_message` is trimmed and capped at 400 characters;
//!   it is distinct from the stored follow-up chips.
//! - `post_processing_completed` / `post_processing_metadata` carry
//!   `follow_up_request_suggestions`, `task_proposals`, `task_update_proposals`.
//! - `task_event`, `task_update_jobs_available` and the sub-chat lifecycle frames
//!   remain distinct collections. Pending jobs are removed only after actual
//!   encrypted persistence, not after reception or dispatch.
//! - Memory requests record exact requested/approved category IDs and the number
//!   of entries actually disclosed through the consent protocol.
//! - Usage maps observed snake_case token/credit metrics to camelCase;
//!   `llmUsageBreakdown` is accepted only with schema version 1, and
//!   `promptBudget.systemPromptTokens` comes from `system_prompt_tokens`.
//! - Queued admissions retain the persisted human ID, queue mode and revision;
//!   a queued turn is not a completed assistant response. Ordinary Team sends
//!   have no assistant message ID.
//!
//! The CLI additionally projects a valid interactive-question waiting state to
//! its legacy snake_case `chat_id` / `message_id` / `parent_id` envelope. That
//! presentation conversion does not change the SDK's typed result.
use crate::{error::Error, model::Chat};
use serde::{Deserialize, Serialize};
use serde_json::Value;

/// Explicit policy for a server-requested private-context or sub-chat approval.
#[derive(Clone, Copy, Default, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum SendConsentPolicy {
    /// Deliver the request through the caller's independent consent receiver.
    #[default]
    Caller,
    /// Reject the request without disclosing additional private context.
    Reject,
    /// Approve the exact current request, subject to ordinary protocol limits.
    ApproveRequested,
}

#[derive(Clone, Serialize, Deserialize)]
#[serde(default, deny_unknown_fields)]
pub struct SendOptions {
    pub slug: Option<String>,
    /// Canonical UUID; never an unchecked CLI selector or inferred Project.
    pub project_id: Option<String>,
    pub incognito: bool,
    pub pii_detection: bool,
    pub task_update_jobs: bool,
    pub response_timeout_ms: Option<u64>,
    pub sub_chat_consent: SendConsentPolicy,
    pub memory_consent: SendConsentPolicy,
}
impl Default for SendOptions {
    fn default() -> Self {
        Self {
            slug: None,
            project_id: None,
            incognito: false,
            pii_detection: true,
            task_update_jobs: true,
            response_timeout_ms: None,
            sub_chat_consent: SendConsentPolicy::Caller,
            memory_consent: SendConsentPolicy::Caller,
        }
    }
}
impl SendOptions {
    pub fn validate(&self) -> crate::Result<()> {
        if self
            .response_timeout_ms
            .is_some_and(|value| !(1..=86_400_000).contains(&value))
        {
            return Err(Error::Invalid(
                "Response timeout must be from 1 ms to one day.",
            ));
        }
        if let Some(project) = &self.project_id
            && uuid::Uuid::parse_str(project)
                .map(|id| id.hyphenated().to_string() != project.to_ascii_lowercase())
                .unwrap_or(true)
        {
            return Err(Error::Invalid("Project ID must be a canonical UUID."));
        }
        Ok(())
    }
}

#[derive(Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum SendStatus {
    Completed,
    WaitingForUser,
    Queued,
}
#[derive(Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum SendQueueMode {
    FollowUp,
    Steer,
}
#[derive(Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct SendMemoryRequest {
    pub request_id: Option<String>,
    pub requested_keys: Vec<String>,
    pub approved_keys: Vec<String>,
    pub entry_count: u64,
}

/// A send result assembled from actual protocol observations and persistence.
///
/// There is no `Default`: callers must choose a confirmed status and retain
/// every metadata collection. Empty pending jobs means none remain observed;
/// receiving a job is never evidence that its encrypted write succeeded.
/// Versioned frame records retain all backend fields instead of projecting
/// unknown fields away. `acceptedTaskProposals` is a CLI post-action, not an
/// inference result, and is deliberately absent here.
#[derive(Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct SendOutcome {
    /// Saved/decrypted messages for native callers, excluded from legacy JSON.
    #[serde(skip)]
    pub chat: Chat,
    pub status: SendStatus,
    pub chat_id: String,
    /// Assistant ID, null for ordinary Team sends and queued turns.
    pub message_id: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub user_message_id: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub queue_mode: Option<SendQueueMode>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub queue_revision: Option<u64>,
    pub assistant: String,
    pub category: Option<String>,
    pub model_name: Option<String>,
    pub mate_name: Option<String>,
    pub follow_up_suggestions: Vec<String>,
    /// Memory/workflow recommendations of the completed turn (`ChatRecommendation` objects, at most 6).
    #[serde(default)]
    pub recommendations: Vec<Value>,
    /// None = omitted; Some(None) = explicitly observed null.
    #[serde(
        default,
        skip_serializing_if = "Option::is_none",
        deserialize_with = "nullable"
    )]
    pub suggested_followup_message: Option<Option<String>>,
    pub task_proposals: Vec<Value>,
    pub task_update_proposals: Vec<Value>,
    pub task_events: Vec<Value>,
    pub pending_task_update_jobs: Vec<Value>,
    pub sub_chat_events: Vec<Value>,
    pub app_settings_memory_requests: Vec<SendMemoryRequest>,
    pub token_usage: Option<Value>,
    pub prompt_budget: Option<Value>,
}
fn nullable<'de, D, T>(deserializer: D) -> std::result::Result<Option<Option<T>>, D::Error>
where
    D: serde::Deserializer<'de>,
    T: Deserialize<'de>,
{
    Option::<T>::deserialize(deserializer).map(Some)
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    fn queued() -> Value {
        json!({"status":"queued","chatId":"chat","messageId":null,
            "userMessageId":"human","queueMode":"follow_up","queueRevision":4,
            "assistant":"","category":null,"modelName":null,"mateName":null,
            "followUpSuggestions":[],"recommendations":[],"taskProposals":[],"taskUpdateProposals":[],
            "taskEvents":[],"pendingTaskUpdateJobs":[{"job_id":"job","revision":3}],
            "subChatEvents":[{"type":"sub_chat_progress","payload":{"status":"running"}}],
            "appSettingsMemoryRequests":[{"requestId":null,"requestedKeys":["health-medications"],"approvedKeys":[],"entryCount":2}],
            "tokenUsage":null,"promptBudget":null})
    }
    #[test]
    fn options_keep_privacy_and_caller_consent_defaults_without_routing_overrides() {
        let options: SendOptions = serde_json::from_value(json!({})).unwrap();
        assert!(options.pii_detection && options.task_update_jobs);
        assert!(!options.incognito);
        assert!(options.memory_consent == SendConsentPolicy::Caller);
        assert!(options.sub_chat_consent == SendConsentPolicy::Caller);
        assert!(options.validate().is_ok());
        for invalid in [json!({"model":"forced"}), json!({"provider":"forced"})] {
            assert!(serde_json::from_value::<SendOptions>(invalid).is_err());
        }
        let options = SendOptions {
            response_timeout_ms: Some(0),
            ..Default::default()
        };
        assert!(matches!(options.validate(), Err(Error::Invalid(_))));
        let options = SendOptions {
            response_timeout_ms: Some(u64::MAX),
            ..Default::default()
        };
        assert!(matches!(options.validate(), Err(Error::Invalid(_))));
        let options = SendOptions {
            project_id: Some("project-selector".into()),
            ..Default::default()
        };
        assert!(matches!(options.validate(), Err(Error::Invalid(_))));
        let options = SendOptions {
            project_id: Some("11111111-1111-4111-8111-111111111111".into()),
            response_timeout_ms: Some(86_400_000),
            ..Default::default()
        };
        assert!(options.validate().is_ok());
    }
    #[test]
    fn queued_metadata_round_trips_without_claiming_completion_or_job_persistence() {
        let expected = queued();
        let outcome: SendOutcome = serde_json::from_value(expected.clone()).unwrap();
        assert!(outcome.status == SendStatus::Queued);
        assert!(outcome.message_id.is_none());
        assert_eq!(outcome.pending_task_update_jobs[0]["job_id"], "job");
        assert_eq!(serde_json::to_value(outcome).unwrap(), expected);
        let mut missing = expected;
        missing
            .as_object_mut()
            .unwrap()
            .remove("pendingTaskUpdateJobs");
        assert!(serde_json::from_value::<SendOutcome>(missing).is_err());
    }
    #[test]
    fn optional_suggestion_distinguishes_absence_null_and_text_and_excludes_chat() {
        for suggestion in [None, Some(Value::Null), Some(json!("Next step"))] {
            let mut expected = queued();
            if let Some(value) = suggestion {
                expected["suggestedFollowupMessage"] = value;
            }
            let mut outcome: SendOutcome = serde_json::from_value(expected.clone()).unwrap();
            outcome.chat.id = "private-native-chat".into();
            assert_eq!(serde_json::to_value(outcome).unwrap(), expected);
        }
    }
}
