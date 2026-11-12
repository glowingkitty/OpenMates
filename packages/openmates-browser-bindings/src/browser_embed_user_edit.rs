//! Worker-only glue for user-made embed versions (`feature.embed-user-edits`):
//! content edits, restore, Image Enhance and the chat-open reconcile of
//! pending embed notices, all run by the signed-in shared core `Client`
//! (`openmates_sdk::client::{embed_user_revision, image_enhance}`). Marshalling
//! only: arguments are JSON strings, results the core's presentation JSON, and
//! errors reject with the core's stable code string (`embed_version_conflict`,
//! `project_context_required`, `insufficient_credits`, `enhance_timeout`, ...).
use super::BrowserCoreClient;
use openmates_sdk::client::embed_updated_event::EmbedEventIdentity;
use openmates_sdk::client::embed_user_revision::{EmbedHead, RevisionScope, UserRevisionRequest};
use openmates_sdk::client::image_enhance::{
    DEFAULT_ENHANCE_DEADLINE, ImageEnhanceError, ImageEnhanceWaker,
};
use std::time::Duration;
use wasm_bindgen::prelude::*;
use zeroize::Zeroizing;

fn invalid() -> JsValue {
    JsValue::from_str("invalid_request")
}

fn proto(_: serde_json::Error) -> JsValue {
    JsValue::from_str("protocol")
}

fn head(embed_id: &str, head_json: &str) -> Result<EmbedHead, JsValue> {
    let row: serde_json::Value = serde_json::from_str(head_json).map_err(|_| invalid())?;
    let now_seconds = (js_sys::Date::now() as i64).div_euclid(1000);
    EmbedHead::from_cached_row(embed_id, &row, now_seconds)
        .map_err(|error| JsValue::from_str(error.code()))
}

fn scope(scope_json: &str) -> Result<RevisionScope, JsValue> {
    serde_json::from_str(scope_json).map_err(|_| invalid())
}

fn identity(identity_json: Option<String>) -> Result<Option<EmbedEventIdentity>, JsValue> {
    identity_json
        .as_deref()
        .map(serde_json::from_str)
        .transpose()
        .map_err(|_| invalid())
}

fn version(value: f64) -> Result<i64, JsValue> {
    if value.fract() != 0.0 || !(1.0..=9_007_199_254_740_991.0).contains(&value) {
        return Err(invalid());
    }
    Ok(value as i64)
}

fn enhance_code(error: ImageEnhanceError) -> JsValue {
    JsValue::from_str(error.code())
}

/// Forwards `image_enhance_ready` / `image_enhance_failed` WebSocket frames
/// into a running Enhance wait, so the next job read happens at once. A
/// separate object: the Worker calls it while the client is busy waiting.
#[wasm_bindgen]
pub struct BrowserImageEnhanceWaker {
    inner: ImageEnhanceWaker,
}

#[wasm_bindgen]
impl BrowserImageEnhanceWaker {
    /// A waker with no pending event.
    #[wasm_bindgen(constructor)]
    pub fn new() -> Self {
        Self {
            inner: ImageEnhanceWaker::new(),
        }
    }

    /// Feed one WebSocket frame (`type`, `payload` as JSON). True when it was
    /// an Enhance event and woke the wait; false for every other frame.
    pub fn notify_frame(&self, event_type: &str, payload_json: &str) -> Result<bool, JsValue> {
        let payload: serde_json::Value =
            serde_json::from_str(payload_json).map_err(|_| invalid())?;
        Ok(self.inner.notify_frame(event_type, &payload))
    }
}

impl Default for BrowserImageEnhanceWaker {
    fn default() -> Self {
        Self::new()
    }
}

impl BrowserCoreClient {
    /// Refuse writes from a stale handle or a local read-only admission.
    fn writable(&self, handle: &str, generation: f64) -> Result<(), JsValue> {
        if self.status(handle, generation)?.local_read_only() {
            return Err(JsValue::from_str("session_expired"));
        }
        Ok(())
    }
}

#[wasm_bindgen]
impl BrowserCoreClient {
    /// Read the current server head of `embed_id` for a user edit and load its
    /// key wrappers into the client cache (a freshly opened embed has none
    /// there yet, so a commit would fail with `embed_key_unavailable`).
    /// Resolves to `{head, chat_id}` JSON: `head` is the head as a cached
    /// `embeds` row (`embed_id`, `version_number`, `encrypted_content`,
    /// `created_at`, `hashed_chat_id`; ciphertext only) to pass back as
    /// `head_json`, `chat_id` the embed's chat when this device has it cached.
    pub async fn embed_user_edit_head(
        &mut self,
        handle: &str,
        generation: f64,
        embed_id: &str,
    ) -> Result<String, JsValue> {
        self.writable(handle, generation)?;
        let (head, chat_id) = self
            .client
            .embed_user_edit_head(embed_id)
            .await
            .map_err(|error| JsValue::from_str(error.code()))?;
        self.status(handle, generation)?;
        let row = serde_json::json!({
            "embed_id": head.embed_id,
            "version_number": head.version,
            "encrypted_content": head.encrypted_content,
            "created_at": head.created_at,
            "hashed_chat_id": head.hashed_chat_id,
        });
        serde_json::to_string(&serde_json::json!({ "head": row, "chat_id": chat_id }))
            .map_err(proto)
    }

    /// Commit a user edit of a diagram, slides, sheet or document embed as its
    /// next version. `head_json` is the head from `embed_user_edit_head`,
    /// `base_version` the version the edit was made on (another head version
    /// rejects with `embed_version_conflict`), `scope_json` `{kind: "chat",
    /// chat_id, team_id?}` or `{kind: "project", project_id, team_id?}`,
    /// `content` the new head plaintext (TOON), `identity_json` `{embed_ref,
    /// embed_kind}` or `undefined` (read from the cached embed). Resolves to
    /// `EmbedRevisionOutcome` JSON (`{commit: {committed, cache_synchronized},
    /// event: {state, code?}}`).
    #[allow(clippy::too_many_arguments)] // One flat argument per wire field of the commit.
    pub async fn commit_embed_content_revision(
        &mut self,
        handle: &str,
        generation: f64,
        embed_id: &str,
        head_json: &str,
        base_version: f64,
        scope_json: &str,
        content: String,
        text_preview: Option<String>,
        operation_id: Option<String>,
        identity_json: Option<String>,
    ) -> Result<String, JsValue> {
        let content = Zeroizing::new(content);
        let text_preview = text_preview.map(Zeroizing::new);
        self.writable(handle, generation)?;
        let head = head(embed_id, head_json)?;
        head.require_version(version(base_version)?)
            .map_err(|error| JsValue::from_str(error.code()))?;
        let request = UserRevisionRequest::content_edit(
            head,
            scope(scope_json)?,
            content,
            text_preview,
            operation_id,
        );
        let outcome = self
            .client
            .commit_embed_user_revision(request, identity(identity_json)?)
            .await
            .map_err(|error| JsValue::from_str(error.code()))?;
        self.status(handle, generation)?;
        serde_json::to_string(&outcome).map_err(proto)
    }

    /// Restore version `restored_from` of an embed as its next version
    /// (content and, for images, its files). Arguments as
    /// `commit_embed_content_revision`; resolves to `EmbedRevisionOutcome` JSON.
    #[allow(clippy::too_many_arguments)] // One flat argument per input of the core call.
    pub async fn restore_embed_version(
        &mut self,
        handle: &str,
        generation: f64,
        embed_id: &str,
        head_json: &str,
        scope_json: &str,
        restored_from: f64,
        identity_json: Option<String>,
    ) -> Result<String, JsValue> {
        self.writable(handle, generation)?;
        let outcome = self
            .client
            .restore_embed_version(
                head(embed_id, head_json)?,
                scope(scope_json)?,
                version(restored_from)?,
                identity(identity_json)?,
            )
            .await
            .map_err(|error| JsValue::from_str(error.code()))?;
        self.status(handle, generation)?;
        serde_json::to_string(&outcome).map_err(proto)
    }

    /// Enhance the head version of an image embed and save the result as its
    /// next version: start, wait (forward the job's frames to `waker`), commit
    /// and write the chat event. `operation_id` is the job's UUID; keep it to
    /// resume with `save_image_enhance_result` after `enhance_timeout` or a
    /// lost answer. Resolves to `ImageEnhanceSaved` JSON (`{state: "committed",
    /// operation_id, outcome}` or `{state: "already_committed", operation_id,
    /// version}`).
    #[allow(clippy::too_many_arguments)] // One flat argument per input of the core call.
    pub async fn enhance_image(
        &mut self,
        handle: &str,
        generation: f64,
        embed_id: &str,
        head_json: &str,
        scope_json: &str,
        operation_id: &str,
        identity_json: Option<String>,
        waker: &BrowserImageEnhanceWaker,
    ) -> Result<String, JsValue> {
        self.writable(handle, generation)?;
        let saved = self
            .client
            .enhance_image(
                head(embed_id, head_json)?,
                scope(scope_json)?,
                Some(operation_id),
                identity(identity_json)?,
                Some(&waker.inner),
            )
            .await
            .map_err(enhance_code)?;
        self.status(handle, generation)?;
        serde_json::to_string(&saved).map_err(proto)
    }

    /// Start (or replay) the Enhance job `operation_id` (a fresh UUID when
    /// `undefined`) of the head version. Resolves to `EnhanceJob` JSON
    /// (`{operation_id, embed_id, state, base_version, target_version,
    /// credits, charged, created_at, expires_at, error_code}`).
    pub async fn start_image_enhance(
        &mut self,
        handle: &str,
        generation: f64,
        embed_id: &str,
        head_json: &str,
        scope_json: &str,
        operation_id: Option<String>,
    ) -> Result<String, JsValue> {
        self.writable(handle, generation)?;
        let (head, scope) = (head(embed_id, head_json)?, scope(scope_json)?);
        let job = self
            .client
            .start_image_enhance(&head, &scope, operation_id.as_deref())
            .await
            .map_err(enhance_code)?;
        self.status(handle, generation)?;
        serde_json::to_string(&job).map_err(proto)
    }

    /// Read the job of `operation_id` now (after an Enhance frame or on
    /// resume). Resolves to `EnhanceJob` JSON.
    pub async fn image_enhance_status(
        &mut self,
        handle: &str,
        generation: f64,
        operation_id: &str,
    ) -> Result<String, JsValue> {
        self.writable(handle, generation)?;
        let job = self
            .client
            .image_enhance_status(operation_id)
            .await
            .map_err(enhance_code)?;
        self.status(handle, generation)?;
        serde_json::to_string(&job).map_err(proto)
    }

    /// Wait until the job of `operation_id` is ready or committed, for at most
    /// `deadline_ms` (default 180 s; `enhance_timeout` after it, the job keeps
    /// running). Resolves to `EnhanceJob` JSON.
    pub async fn wait_image_enhance(
        &mut self,
        handle: &str,
        generation: f64,
        operation_id: &str,
        waker: &BrowserImageEnhanceWaker,
        deadline_ms: Option<f64>,
    ) -> Result<String, JsValue> {
        self.writable(handle, generation)?;
        let deadline = match deadline_ms {
            None => DEFAULT_ENHANCE_DEADLINE,
            Some(ms) => Duration::from_millis(version(ms)? as u64),
        };
        let job = self
            .client
            .wait_image_enhance(operation_id, Some(&waker.inner), deadline)
            .await
            .map_err(enhance_code)?;
        self.status(handle, generation)?;
        serde_json::to_string(&job).map_err(proto)
    }

    /// Save the result of Enhance job `operation_id` as the next version; the
    /// head is the version the job started from, the scope the one it was
    /// started in. Safe to repeat. Resolves to `ImageEnhanceSaved` JSON.
    #[allow(clippy::too_many_arguments)] // One flat argument per input of the core call.
    pub async fn save_image_enhance_result(
        &mut self,
        handle: &str,
        generation: f64,
        embed_id: &str,
        head_json: &str,
        scope_json: &str,
        operation_id: &str,
        identity_json: Option<String>,
    ) -> Result<String, JsValue> {
        self.writable(handle, generation)?;
        let saved = self
            .client
            .save_image_enhance_result(
                head(embed_id, head_json)?,
                scope(scope_json)?,
                operation_id,
                identity(identity_json)?,
            )
            .await
            .map_err(enhance_code)?;
        self.status(handle, generation)?;
        serde_json::to_string(&saved).map_err(proto)
    }

    /// Chat-open reconcile: write the `embed_updated` events the server still
    /// lists as pending for `chat_id` (edits made in the Projects workspace or
    /// on another device). Run after the chat window is shown. Resolves to
    /// `NoticeReconcileReport` JSON (`{written, already_present, unresolved,
    /// deferred?}`); offline or refused reads resolve as `deferred`.
    pub async fn reconcile_embed_update_notices(
        &mut self,
        handle: &str,
        generation: f64,
        chat_id: &str,
    ) -> Result<String, JsValue> {
        self.writable(handle, generation)?;
        let report = self
            .client
            .reconcile_embed_update_notices_on_open(chat_id)
            .await
            .map_err(|error| {
                JsValue::from_str(match error {
                    openmates_sdk::Error::Cancelled => "cancelled",
                    _ => "session_expired",
                })
            })?;
        self.status(handle, generation)?;
        serde_json::to_string(&report).map_err(proto)
    }
}
