//! Worker export of the Project file-job protocol (`projectFileJobs` unit),
//! plus assistant Project creation requests (`Client::project_create_step`).
//! Marshalling only: operation handling, approvals, leases and privacy
//! restoration are the core's (`Client::project_file_job_*`); the page sends the
//! returned frames on its one main socket. Results are step JSON, never keys.
//! Spec: feature.projects project file operations.
use super::BrowserCoreClient;
use openmates_sdk::Error;
use wasm_bindgen::prelude::*;

/// Stable code of a core refusal; never internal text.
fn code(error: Error) -> JsValue {
    if let Some(code) = error.sdk_code() {
        return JsValue::from_str(code);
    }
    JsValue::from_str(match error {
        Error::Invalid(_) => "invalid_request",
        Error::Locked => "locked",
        Error::Crypto => "crypto",
        Error::Protocol => "protocol",
        Error::Cancelled => "cancelled",
        Error::Unavailable { code, .. } => code,
        Error::Authentication => "authentication",
        Error::TwoFactorRequired => "two_factor_required",
        Error::SignupRequired => "signup_required",
        Error::Offline => "offline",
        Error::Forbidden => "forbidden",
        Error::Expired => "expired",
        Error::VerificationRequired => "verification_required",
        Error::Io => "io",
        Error::Conflict => "conflict",
    })
}

#[wasm_bindgen]
impl BrowserCoreClient {
    /// Handle one `project_file_operation_available` / `_request` payload and
    /// return the step JSON `{frames, prompts, applied, notices}`.
    pub async fn project_file_job_step(
        &mut self,
        handle: &str,
        generation: f64,
        kind: &str,
        event_json: &str,
        interactive: bool,
    ) -> Result<String, JsValue> {
        self.status(handle, generation)?;
        let event: serde_json::Value =
            serde_json::from_str(event_json).map_err(|_| JsValue::from_str("invalid_request"))?;
        let step = self
            .client
            .project_file_job_step(kind, &event, interactive)
            .await
            .map_err(code)?;
        self.status(handle, generation)?;
        serde_json::to_string(&step).map_err(|_| JsValue::from_str("protocol"))
    }

    /// Apply the user's answer to a pending prompt; returns the step JSON.
    pub async fn project_file_job_decide(
        &mut self,
        handle: &str,
        generation: f64,
        chat_id: &str,
        operation_id: &str,
        accept: bool,
    ) -> Result<String, JsValue> {
        self.status(handle, generation)?;
        let step = self
            .client
            .project_file_job_decide(chat_id, operation_id, accept)
            .await
            .map_err(code)?;
        self.status(handle, generation)?;
        serde_json::to_string(&step).map_err(|_| JsValue::from_str("protocol"))
    }

    /// Set the chat's privacy mappings (JSON array) used to restore file writes.
    pub fn project_file_job_set_mappings(
        &mut self,
        handle: &str,
        generation: f64,
        chat_id: &str,
        mappings_json: &str,
    ) -> Result<(), JsValue> {
        self.status(handle, generation)?;
        let mappings: Vec<serde_json::Value> = serde_json::from_str(mappings_json)
            .map_err(|_| JsValue::from_str("invalid_request"))?;
        self.client.project_file_job_set_mappings(chat_id, &mappings);
        Ok(())
    }

    /// Install the chat's privacy layer (settings rows as a JSON array and the
    /// sealed blob previously returned by a step, if any). On error the page
    /// must not feed that chat's file jobs.
    pub async fn project_file_job_set_privacy(
        &mut self,
        handle: &str,
        generation: f64,
        chat_id: &str,
        project_id: &str,
        enabled: bool,
        memories_json: &str,
        sealed: Option<String>,
    ) -> Result<(), JsValue> {
        self.status(handle, generation)?;
        let memories: Vec<serde_json::Value> = serde_json::from_str(memories_json)
            .map_err(|_| JsValue::from_str("invalid_request"))?;
        self.client
            .project_file_job_set_privacy(chat_id, project_id, enabled, memories, sealed.as_deref())
            .await
            .map_err(code)?;
        self.status(handle, generation)?;
        Ok(())
    }

    /// Handle one `project_create_requested` / `_confirmed` / `_error` payload;
    /// returns the `project_create_result` payload JSON to send, or `null`.
    pub async fn project_create_step(
        &mut self,
        handle: &str,
        generation: f64,
        kind: &str,
        event_json: &str,
    ) -> Result<String, JsValue> {
        self.status(handle, generation)?;
        let event: serde_json::Value =
            serde_json::from_str(event_json).map_err(|_| JsValue::from_str("invalid_request"))?;
        let report = self
            .client
            .project_create_step(kind, &event)
            .await
            .map_err(code)?;
        self.status(handle, generation)?;
        serde_json::to_string(&report).map_err(|_| JsValue::from_str("protocol"))
    }

    /// Answer one `project_sandbox_key_request` payload; returns the finished
    /// WS frame JSON `{event, payload}` (grant sealed to the sandbox, or a
    /// decline). The Project key never leaves the core.
    pub async fn answer_project_sandbox_key_request(
        &mut self,
        handle: &str,
        generation: f64,
        event_json: &str,
        now_seconds: f64,
    ) -> Result<String, JsValue> {
        self.status(handle, generation)?;
        let event: serde_json::Value =
            serde_json::from_str(event_json).map_err(|_| JsValue::from_str("invalid_request"))?;
        let frame = self
            .client
            .answer_project_sandbox_key_request(&event, now_seconds as i64)
            .await
            .map_err(code)?;
        self.status(handle, generation)?;
        serde_json::to_string(&frame).map_err(|_| JsValue::from_str("protocol"))
    }

    /// Describe one `embed_revision_committed` payload of a hosted-sandbox
    /// write as the applied-change card JSON `{projectId, chatId, mutation}`,
    /// or `null` when the core shows nothing (another source, no focus, no key).
    pub async fn describe_project_sandbox_commit(
        &mut self,
        handle: &str,
        generation: f64,
        event_json: &str,
    ) -> Result<String, JsValue> {
        self.status(handle, generation)?;
        let event: serde_json::Value =
            serde_json::from_str(event_json).map_err(|_| JsValue::from_str("invalid_request"))?;
        let card = self
            .client
            .describe_project_sandbox_commit(&event)
            .await
            .map_err(code)?;
        self.status(handle, generation)?;
        serde_json::to_string(&card).map_err(|_| JsValue::from_str("protocol"))
    }
}
