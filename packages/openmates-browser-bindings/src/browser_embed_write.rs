//! Worker-only exports of the shared embed write engine
//! (`openmates_sdk::client::embed_write`). JS supplies wrapped keys, plaintext
//! stream payloads and IndexedDB/HTTP results; it receives only ciphertext rows,
//! payload JSON and reconstructed plaintext content. No raw-key RPC exists:
//! keys are adopted from master/chat/parent wrappers and stay in Rust memory.
//!
//! Errors reject with a stable code string: an `Unavailable` code
//! (`embed_parent_key_pending`, `embed_chat_key_unavailable`,
//! `embed_key_unavailable`, `embed_history_read_failed`) or one of
//! `conflict`, `protocol`, `crypto`, `invalid`, `cancelled`, `unavailable`.
use openmates_sdk::client::embed_write::{
    self, CanonicalRead, EmbedRefIndex, EmbedRefIndexEntry, EmbedStatus, EmbedWriteSession, OsNonces,
    ProcessingEmbedUpdate, RestoreRequest, StreamedEmbedData,
    history::{self, EncryptedDiffRow},
};
use crate::browser_crypto_batch::WebAead;
use openmates_sdk::crypto::aead::AeadProvider;
use openmates_sdk::crypto::master::MasterCapability;
use serde_json::{Value, json};
use std::cell::RefCell;
use std::collections::HashMap;
use std::rc::Rc;
use wasm_bindgen::{JsCast, prelude::*};

fn code(error: openmates_sdk::Error) -> JsValue {
    use openmates_sdk::Error as E;
    JsValue::from_str(match error {
        E::Unavailable { code, .. } => code,
        E::Conflict => "conflict",
        E::Protocol => "protocol",
        E::Crypto => "crypto",
        E::Invalid(_) => "invalid",
        E::Cancelled => "cancelled",
        _ => "unavailable",
    })
}
fn parse(text: &str) -> Result<Value, JsValue> {
    serde_json::from_str(text).map_err(|_| JsValue::from_str("invalid"))
}
fn proto(_: serde_json::Error) -> JsValue {
    JsValue::from_str("protocol")
}
fn array(text: &str) -> Result<Vec<Value>, JsValue> {
    match parse(text)? {
        Value::Array(rows) => Ok(rows),
        _ => Err(JsValue::from_str("invalid")),
    }
}
fn now_ms() -> i64 {
    js_sys::Date::now() as i64
}
fn now_seconds() -> i64 {
    now_ms().div_euclid(1000)
}
fn worker_only() -> Result<(), JsValue> {
    js_sys::global()
        .dyn_into::<web_sys::DedicatedWorkerGlobalScope>()
        .map(|_| ())
        .map_err(|_| JsValue::from_str("unavailable"))
}

/// Embed write session bound to the account's non-extractable master CryptoKey.
#[wasm_bindgen]
pub struct BrowserEmbedWriter {
    session: Rc<RefCell<EmbedWriteSession>>,
}

#[wasm_bindgen]
impl BrowserEmbedWriter {
    #[wasm_bindgen(constructor)]
    pub fn new(master: web_sys::CryptoKey) -> Result<BrowserEmbedWriter, JsValue> {
        worker_only()?;
        let port = super::browser_crypto::BrowserMasterCrypto::new(master).map_err(code)?;
        let master = MasterCapability::from_browser_port(Rc::new(port));
        Ok(Self { session: Rc::new(RefCell::new(EmbedWriteSession::new(master))) })
    }
    /// Adopt a chat key from its master-wrapped `encrypted_chat_key`.
    pub fn adopt_chat_key(&self, chat_id: &str, encrypted_chat_key: &str) -> Result<js_sys::Promise, JsValue> {
        let adoption = self.session.borrow().chat_key_adoption(chat_id, encrypted_chat_key).map_err(code)?;
        let session = self.session.clone();
        Ok(wasm_bindgen_futures::future_to_promise(async move {
            let adopted = adoption.resolve().await.map_err(code)?;
            session.borrow_mut().install(adopted);
            Ok(JsValue::UNDEFINED)
        }))
    }
    /// Adopt an embed key from an `embed_keys` IndexedDB/server row (JSON).
    pub fn adopt_embed_key_wrapper(&self, embed_id: &str, chat_id: &str, row_json: &str) -> Result<js_sys::Promise, JsValue> {
        let row = parse(row_json)?;
        let adoption = self.session.borrow().embed_wrapper_adoption(embed_id, chat_id, &row).map_err(code)?;
        let session = self.session.clone();
        Ok(wasm_bindgen_futures::future_to_promise(async move {
            let adopted = adoption.resolve().await.map_err(code)?;
            session.borrow_mut().install(adopted);
            Ok(JsValue::UNDEFINED)
        }))
    }
    /// Shared child key wrapped by its parent embed key.
    pub fn adopt_child_embed_key(&self, child_id: &str, parent_id: &str, wrapped_by_parent: &str) -> Result<(), JsValue> {
        self.session.borrow_mut().adopt_child_key(child_id, parent_id, wrapped_by_parent).map_err(code)
    }
    pub fn has_chat_key(&self, chat_id: &str) -> bool {
        self.session.borrow().has_chat_key(chat_id)
    }
    pub fn has_embed_key(&self, embed_id: &str) -> bool {
        self.session.borrow().has_embed_key(embed_id)
    }
    /// Finalized `send_embed_data` (payload JSON plus `team_id`/`local_only`).
    /// Resolves to `PreparedEmbedWrite` JSON.
    pub fn prepare_stream_completion(&self, payload_json: &str) -> Result<js_sys::Promise, JsValue> {
        let data = StreamedEmbedData::from_value(parse(payload_json)?).map_err(code)?;
        let planned = self.session.borrow_mut().plan_stream_completion(data).map_err(code)?;
        Ok(wasm_bindgen_futures::future_to_promise(async move {
            let prepared = planned.finish(now_ms()).await.map_err(code)?;
            Ok(JsValue::from_str(&serde_json::to_string(&prepared).map_err(proto)?))
        }))
    }
    /// Processing->finished `embed_update`; `normalized_type` comes from the
    /// web embed type registry. Resolves to `PreparedEmbedWrite` JSON.
    pub fn prepare_processing_update(
        &self,
        existing_json: &str,
        chat_id: &str,
        user_id: Option<String>,
        message_id: Option<String>,
        normalized_type: &str,
    ) -> Result<js_sys::Promise, JsValue> {
        let Value::Object(existing) = parse(existing_json)? else { return Err(JsValue::from_str("invalid")) };
        let update = ProcessingEmbedUpdate {
            existing,
            chat_id: chat_id.to_owned(),
            user_id,
            message_id,
            normalized_type: normalized_type.to_owned(),
        };
        let planned = self.session.borrow_mut().plan_processing_update(update).map_err(code)?;
        Ok(wasm_bindgen_futures::future_to_promise(async move {
            let prepared = planned.finish(now_ms()).await.map_err(code)?;
            Ok(JsValue::from_str(&serde_json::to_string(&prepared).map_err(proto)?))
        }))
    }
    /// Ordinary path, one streamed row: `{local_row, server_payload}` JSON or
    /// `undefined` when TS would skip the row.
    pub fn encrypt_history_row(&self, embed_id: &str, row_json: &str, hashed_user_id: &str) -> Result<Option<String>, JsValue> {
        let row = parse(row_json)?;
        let encrypted = self
            .session
            .borrow()
            .with_embed_key(embed_id, |key| history::encrypt_streamed_row(&row, key, now_seconds(), &mut OsNonces))
            .map_err(code)?;
        encrypted
            .map(|row| serde_json::to_string(&json!({ "local_row": row, "server_payload": row.server_payload(hashed_user_id) })).map_err(proto))
            .transpose()
    }
    /// Sealed root revision: validate, reuse matching local rows, encrypt the
    /// rest. Resolves to the `embed_diffs` rows to store (never sent).
    pub fn reconcile_sealed_history(&self, embed_id: &str, rows_json: &str, declared_version: f64, existing_rows_json: &str) -> Result<String, JsValue> {
        let rows = array(rows_json)?;
        let existing: Vec<EncryptedDiffRow> = serde_json::from_str(existing_rows_json).map_err(|_| JsValue::from_str("invalid"))?;
        let by_version: HashMap<i64, EncryptedDiffRow> = existing.into_iter().map(|row| (row.version_number, row)).collect();
        history::validate_sealed_rows(&rows, embed_id, declared_version).map_err(code)?;
        let stored = self
            .session
            .borrow()
            .with_embed_key(embed_id, |key| {
                let mut stored = Vec::new();
                for row in &rows {
                    let version = row.get("version_number").and_then(Value::as_i64).unwrap_or_default();
                    if let Some(reconciled) = history::reconcile_sealed_row(row, by_version.get(&version), key, now_seconds(), &mut OsNonces)? {
                        stored.push(reconciled);
                    }
                }
                Ok(stored)
            })
            .map_err(code)?;
        serde_json::to_string(&stored).map_err(proto)
    }
    /// Validate a bounded-v1 page for one streamed row; returns the row to store.
    pub fn adopt_canonical_row(&self, embed_id: &str, page_json: &str, row_json: &str) -> Result<String, JsValue> {
        let (page, row) = (parse(page_json)?, parse(row_json)?);
        let adopted = self
            .session
            .borrow()
            .with_embed_key(embed_id, |key| history::adopt_canonical_row(&page, &row, key, now_seconds()))
            .map_err(code)?;
        serde_json::to_string(&adopted).map_err(proto)
    }
    /// Verify the durable canonical head page; returns rows to store.
    pub fn verify_canonical_head(&self, embed_id: &str, page_json: &str, rows_json: &str) -> Result<String, JsValue> {
        let (page, rows) = (parse(page_json)?, array(rows_json)?);
        let verified = self
            .session
            .borrow()
            .with_embed_key(embed_id, |key| history::verify_canonical_head(&page, &rows, embed_id, key, now_seconds()))
            .map_err(code)?;
        serde_json::to_string(&verified).map_err(proto)
    }
    /// `restoreEmbedVersion` encryption; returns `RestorePlan` JSON.
    pub fn prepare_restore(&self, embed_id: &str, selected_version: f64, current_version: f64, current_content: &str, restored_content: &str) -> Result<String, JsValue> {
        let request = RestoreRequest {
            embed_id,
            selected_version: selected_version as i64,
            current_version: current_version as i64,
            current_content,
            restored_content,
        };
        let plan = self
            .session
            .borrow()
            .with_embed_key(embed_id, |key| history::prepare_restore(&request, key, now_seconds(), &mut OsNonces))
            .map_err(code)?;
        serde_json::to_string(&plan).map_err(proto)
    }
    /// `publishClientSnapshot` request body JSON.
    pub fn client_snapshot_body(&self, embed_id: &str, content: &str, version: f64, current_version: f64, project_id: Option<String>, team_id: Option<String>) -> Result<String, JsValue> {
        let project = project_id.as_deref().map(|project| (project, team_id.as_deref()));
        let body = self
            .session
            .borrow()
            .with_embed_key(embed_id, |key| history::client_snapshot_body(content, version as i64, current_version as i64, project, key, &mut OsNonces))
            .map_err(code)?;
        serde_json::to_string(&body).map_err(proto)
    }
    /// Reconstruct version content from encrypted rows (plaintext for the UI).
    pub fn reconstruct_versions(&self, embed_id: &str, rows_json: &str) -> Result<String, JsValue> {
        let rows = array(rows_json)?;
        let content = self.session.borrow().with_embed_key(embed_id, |key| history::reconstruct(&rows, key)).map_err(code)?;
        Ok(content.as_str().to_owned())
    }
    pub fn forget_chat(&self, chat_id: &str) {
        self.session.borrow_mut().forget_chat(chat_id);
    }
    pub fn clear(&self) {
        self.session.borrow_mut().clear();
    }
}

#[wasm_bindgen]
pub fn embed_status_transition_allowed(current: &str, target: &str) -> bool {
    embed_write::status::transition_allowed(current, target)
}
#[wasm_bindgen]
pub fn embed_status_is_terminal(status: &str) -> bool {
    embed_write::status::is_terminal(status)
}
#[wasm_bindgen]
pub fn embed_status_normalize(value_json: &str) -> Result<String, JsValue> {
    Ok(EmbedStatus::normalize(&parse(value_json)?).as_str().to_owned())
}
#[wasm_bindgen]
pub fn embed_build_unified_diff(current: &str, restored: &str, current_version: f64, new_version: f64) -> String {
    history::build_unified_diff(current, restored, current_version as i64, new_version as i64)
}
/// `"absent"` or `"present"`; rejects for unreadable canonical history.
#[wasm_bindgen]
pub fn embed_classify_canonical_read(status: u16, body_json: Option<String>, version: f64, durable_head: bool) -> Result<String, JsValue> {
    let body = body_json.as_deref().map(parse).transpose()?;
    let read = if durable_head {
        history::classify_head_read(status)
    } else {
        history::classify_canonical_read(status, body.as_ref(), version as i64)
    }
    .map_err(code)?;
    Ok(match read {
        CanonicalRead::Absent => "absent",
        CanonicalRead::Present => "present",
    }
    .to_owned())
}
#[wasm_bindgen]
pub fn embed_history_head_version(rows_json: &str, embed_id: &str) -> Result<Option<f64>, JsValue> {
    Ok(history::head_version(&array(rows_json)?, embed_id).map(|v| v as f64))
}
#[wasm_bindgen]
pub fn embed_should_publish_client_snapshot(row_count: u32, readonly: Option<bool>) -> bool {
    history::should_publish_client_snapshot(row_count as usize, readonly)
}

/// Opens one stored `embeds` row (separate-fields model) with its embed key:
/// `encrypted_content` / `encrypted_type` / `encrypted_text_preview` in one
/// batched WebCrypto call (`embed_write::read`). Resolves to
/// `{content, content_failed, type, text_preview}` (strings or `null`); the
/// key bytes are imported non-extractable and the JS copy is not retained.
#[wasm_bindgen]
pub async fn embed_open_row_fields(
    key: Vec<u8>,
    encrypted_content: Option<String>,
    encrypted_type: Option<String>,
    encrypted_text_preview: Option<String>,
) -> Result<JsValue, JsValue> {
    worker_only()?;
    let raw = crate::browser_crypto_batch::chat_key(key).ok_or_else(|| JsValue::from_str("invalid"))?;
    let handle = WebAead.import_key(&raw).await.map_err(code)?;
    let fields = [encrypted_content.as_deref(), encrypted_type.as_deref(), encrypted_text_preview.as_deref()];
    let opened = embed_write::read::open_fields(handle.as_ref(), fields).await.map_err(code)?;
    let result = js_sys::Object::new();
    let text = |value: Option<String>| value.map_or(JsValue::NULL, |text| JsValue::from_str(&text));
    js_sys::Reflect::set(&result, &JsValue::from_str("content"), &text(opened.content))?;
    js_sys::Reflect::set(&result, &JsValue::from_str("content_failed"), &JsValue::from_bool(opened.content_failed))?;
    js_sys::Reflect::set(&result, &JsValue::from_str("type"), &text(opened.embed_type))?;
    js_sys::Reflect::set(&result, &JsValue::from_str("text_preview"), &text(opened.text_preview))?;
    Ok(result.into())
}

/// In-memory embed_ref index (never persisted).
#[wasm_bindgen]
pub struct BrowserEmbedRefIndex {
    index: EmbedRefIndex,
}
impl Default for BrowserEmbedRefIndex {
    fn default() -> Self {
        Self::new()
    }
}
#[wasm_bindgen]
impl BrowserEmbedRefIndex {
    #[wasm_bindgen(constructor)]
    pub fn new() -> BrowserEmbedRefIndex {
        Self { index: EmbedRefIndex::new() }
    }
    /// Returns whether subscribers must refresh.
    pub fn register(&mut self, embed_ref: &str, entry_json: &str) -> Result<bool, JsValue> {
        let entry: EmbedRefIndexEntry = serde_json::from_str(entry_json).map_err(|_| JsValue::from_str("invalid"))?;
        Ok(self.index.register(embed_ref, entry))
    }
    /// `{embedRef, entry}` JSON or `undefined`.
    pub fn resolve(&self, embed_ref: &str) -> Result<Option<String>, JsValue> {
        self.index.resolve(embed_ref).map(|resolved| serde_json::to_string(&resolved).map_err(proto)).transpose()
    }
    pub fn version(&self) -> f64 {
        self.index.version() as f64
    }
    pub fn clear(&mut self) {
        self.index.clear();
    }
}
