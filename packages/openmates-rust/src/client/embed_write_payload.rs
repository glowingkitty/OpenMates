//! Row and payload shapes for streamed embed writes. Mirrors the finalized
//! `send_embed_data` path and the processing->finished `embed_update` path of
//! `chatSyncServiceHandlersAI.ts` plus `embedStore.putEncrypted` entry building.
//!
//! JS `undefined` is modelled as an absent map key and `null` stays `null`, so
//! IndexedDB rows and WebSocket payloads keep the deployed shapes byte-for-byte.
//! The local entry carries the RAW embed type; the web adapter applies its
//! embed type registry normalization at the IndexedDB boundary.
use super::keys::{NonceSource, encrypt_text, hash_id, wrap_key};
use super::normalize_to_unix_seconds;
use super::ref_index::js_trim;
use crate::error::{Error, Result};
use serde::Serialize;
use serde_json::{Map, Value, json};

const MAX_CHILD_REF_EMBED_IDS: usize = 50;
/// Types whose plaintext carries app/skill metadata (`putEncrypted`).
const METADATA_TYPES: [&str; 9] = [
    "app-skill-use",
    "app_skill_use",
    "code",
    "code-code",
    "sheet",
    "sheets-sheet",
    "math-plot",
    "document",
    "docs-doc",
];

/// Finalized `send_embed_data` payload plus adapter context (`team_id`,
/// `local_only`). Holds plaintext content: intentionally not Debug.
pub struct StreamedEmbedData {
    raw: Map<String, Value>,
}
fn text<'a>(raw: &'a Map<String, Value>, key: &str) -> Option<&'a str> {
    raw.get(key).and_then(Value::as_str)
}
fn truthy_text<'a>(raw: &'a Map<String, Value>, key: &str) -> Option<&'a str> {
    text(raw, key).filter(|value| !value.is_empty())
}
fn required<'a>(raw: &'a Map<String, Value>, key: &str) -> Result<&'a str> {
    text(raw, key).ok_or(Error::Invalid("Streamed embed payload is missing a required field."))
}
fn copy_present(dst: &mut Map<String, Value>, src: &Map<String, Value>, key: &str) {
    if let Some(value) = src.get(key) {
        dst.insert(key.to_owned(), value.clone());
    }
}
fn or_default(src: &Map<String, Value>, key: &str, default: Value) -> Value {
    match src.get(key) {
        None | Some(Value::Null) => default,
        Some(value) => value.clone(),
    }
}
/// `x.createdAt ?? x.created_at ?? Date.now()` (and the updatedAt twin).
fn entry_timestamp(src: &Map<String, Value>, camel: &str, snake: &str, now_ms: i64) -> Value {
    [camel, snake]
        .iter()
        .find_map(|key| src.get(*key).filter(|value| !value.is_null()).cloned())
        .unwrap_or_else(|| json!(now_ms))
}

impl StreamedEmbedData {
    pub fn from_value(value: Value) -> Result<Self> {
        let Value::Object(raw) = value else {
            return Err(Error::Invalid("Streamed embed payload must be an object."));
        };
        for key in ["embed_id", "chat_id", "message_id", "user_id", "type", "content"] {
            required(&raw, key)?;
        }
        if text(&raw, "embed_id").is_some_and(str::is_empty) {
            return Err(Error::Invalid("Streamed embed payload requires an embed ID."));
        }
        Ok(Self { raw })
    }
    pub fn embed_id(&self) -> &str {
        text(&self.raw, "embed_id").unwrap_or_default()
    }
    pub fn chat_id(&self) -> &str {
        text(&self.raw, "chat_id").unwrap_or_default()
    }
    pub fn embed_type(&self) -> &str {
        text(&self.raw, "type").unwrap_or_default()
    }
    /// `!!embedData.parent_embed_id`.
    pub fn parent_embed_id(&self) -> Option<&str> {
        truthy_text(&self.raw, "parent_embed_id")
    }
    pub fn local_only(&self) -> bool {
        self.raw.get("local_only").and_then(Value::as_bool).unwrap_or(false)
    }
    /// Sealed revision: a root with `version_number ?? 1` above one, or a
    /// child revision (`payload.revision` with `version_number > 1`, see
    /// [`Self::child_revision`]). A child without `revision` stays unsealed.
    pub fn sealed_history(&self) -> bool {
        let root_revision = self.parent_embed_id().is_none()
            && self.raw.get("version_number").and_then(Value::as_f64).unwrap_or(1.0) > 1.0;
        // A malformed `revision` is refused by `plan_stream_completion` before any
        // write is built, so `Err` here never reaches a prepared write.
        root_revision || matches!(self.child_revision(), Ok(Some(_)))
    }
    /// `payload.revision` of a generated child's next version
    /// (`images-generate.revision.same-embed-new-version`, wire-contract.md
    /// "send_embed_data for the revised image"). `Ok(None)` when absent/null.
    ///
    /// # Errors
    /// `Error::Protocol` when `revision` is present on a root, is not an object,
    /// lacks a positive integer `base_version` or a boolean
    /// `base_snapshot_required`, or `version_number != base_version + 1`.
    pub fn child_revision(&self) -> Result<Option<super::revision::ChildRevision>> {
        super::revision::ChildRevision::from_payload(&self.raw, self.parent_embed_id().is_some())
    }
    /// Raw payload map for sibling write builders (plaintext; never logged).
    pub(super) fn raw(&self) -> &Map<String, Value> {
        &self.raw
    }
    pub fn version_history_rows(&self) -> &[Value] {
        self.raw.get("version_history_rows").and_then(Value::as_array).map_or(&[], Vec::as_slice)
    }
    pub fn declared_version(&self) -> f64 {
        self.raw.get("version_number").and_then(Value::as_f64).unwrap_or(f64::NAN)
    }
    /// Parent key cache targets (the embed plus its known children).
    pub fn key_cache_targets(&self) -> Vec<String> {
        cache_targets(self.embed_id(), self.parent_embed_id().is_some(), self.embed_type(), &self.raw)
    }
}
fn cache_targets(embed_id: &str, child: bool, embed_type: &str, raw: &Map<String, Value>) -> Vec<String> {
    let mut targets = vec![embed_id.to_owned()];
    if !child && embed_type != "application" && embed_type != "authored_results" {
        if let Some(children) = raw.get("embed_ids").and_then(Value::as_array) {
            targets.extend(children.iter().filter_map(Value::as_str).map(str::to_owned));
        }
    }
    targets
}

/// Every storage/send artifact of one embed write. Ciphertext and hashes only.
#[derive(Serialize, Debug)]
pub struct PreparedEmbedWrite {
    pub local_entry: Value,
    pub local_key_wrappers: Vec<Value>,
    pub store_payload: Option<Value>,
    pub server_keys: Option<Value>,
    pub key_cache_embed_ids: Vec<String>,
    pub embed_ref_registration: Option<Value>,
    pub child_ref_embed_ids: Vec<String>,
    pub sealed_history: bool,
    /// Ordered writes of a child revision (base snapshot, head, history row);
    /// absent for every other write so their JSON keeps the deployed shape.
    #[serde(skip_serializing_if = "Option::is_none")]
    pub child_revision: Option<super::revision::ChildRevisionWrites>,
}

/// Head identity a child revision keeps from the stored head instead of
/// deriving it from the event: the extension requires the creating message's
/// hash, the chat hash and the byte-identical `encrypted_type`
/// (`operations.js` `requireChildRevisionHead` and the acknowledged advance).
pub(crate) struct KeptHeadIdentity<'a> {
    pub hashed_message_id: &'a str,
    pub hashed_chat_id: &'a str,
    pub encrypted_type: &'a str,
    /// Resume of a head already stored locally at N+1: resend its exact
    /// content/preview ciphertext instead of encrypting again, so a send that
    /// reached the server before a crash is repeated byte for byte.
    pub resend: Option<KeptHeadCiphertext<'a>>,
}
/// Stored head ciphertext reused by a resumed child revision.
pub(crate) struct KeptHeadCiphertext<'a> {
    pub encrypted_content: &'a str,
    pub encrypted_text_preview: Option<&'a str>,
}

/// `decodeToonContentLocal` result when it is an object (TOON, then JSON).
/// TOON uses the vector-proven port of the web's non-strict decoder
/// (`crate::toon_decode`), so embed_ref/app metadata match the TS writer.
pub(crate) fn decode_object(content: &str) -> Option<Map<String, Value>> {
    match crate::toon_decode::decode(content).map(|value| value.to_json_value()) {
        Ok(Value::Object(map)) => Some(map),
        _ => match serde_json::from_str::<Value>(content) {
            Ok(Value::Object(map)) => Some(map),
            _ => None,
        },
    }
}
fn child_ref_embed_ids(decoded: Option<&Map<String, Value>>) -> Vec<String> {
    let Some(raw) = decoded.and_then(|map| map.get("embed_ids")) else { return Vec::new() };
    let candidates: Vec<&str> = match raw {
        Value::String(joined) => joined.split('|').collect(),
        Value::Array(items) => items.iter().filter_map(Value::as_str).collect(),
        _ => return Vec::new(),
    };
    candidates
        .into_iter()
        .filter(|id| !id.is_empty())
        .map(js_trim)
        .map(|id| id.strip_prefix("embed:").unwrap_or(id))
        .filter(|id| !id.is_empty())
        .take(MAX_CHILD_REF_EMBED_IDS)
        .map(str::to_owned)
        .collect()
}
fn key_wrapper(hashed_embed_id: &str, key_type: &str, hashed_chat_id: Option<&str>, wrapped: String, hashed_user_id: &str, now_seconds: i64) -> Value {
    json!({
        "hashed_embed_id": hashed_embed_id, "key_type": key_type, "hashed_chat_id": hashed_chat_id,
        "encrypted_embed_key": wrapped, "hashed_user_id": hashed_user_id, "created_at": now_seconds,
    })
}

/// Explicit key material for one write. `chat_key` is required for parents
/// (chat wrapper); `master_wrapper` is the already master-wrapped embed key
/// (absent for children and local-only writes).
pub struct WriteKeys<'a> {
    pub embed_key: &'a [u8; 32],
    pub chat_key: Option<&'a [u8; 32]>,
    pub master_wrapper: Option<String>,
}

/// Finalized streamed write. Nonces: content, type, preview (when truthy),
/// chat wrapper (parents).
pub fn build_stream_completion(
    data: &StreamedEmbedData,
    keys: WriteKeys<'_>,
    now_ms: i64,
    nonces: &mut impl NonceSource,
) -> Result<PreparedEmbedWrite> {
    build_stream_completion_keeping(data, keys, now_ms, nonces, None)
}

/// [`build_stream_completion`] with an optional kept head identity (child
/// revisions only). With `kept`, the type ciphertext is reused, so the nonce
/// order is content, preview; without it the output is unchanged.
pub(crate) fn build_stream_completion_keeping(
    data: &StreamedEmbedData,
    keys: WriteKeys<'_>,
    now_ms: i64,
    nonces: &mut impl NonceSource,
    kept: Option<&KeptHeadIdentity<'_>>,
) -> Result<PreparedEmbedWrite> {
    let raw = &data.raw;
    let child = data.parent_embed_id().is_some();
    let now_seconds = now_ms.div_euclid(1000);
    let content = required(raw, "content")?;
    let embed_type = data.embed_type();
    let message_id = required(raw, "message_id")?;
    let (hashed_chat_id, hashed_message_id) = match kept {
        Some(kept) => (kept.hashed_chat_id.to_owned(), kept.hashed_message_id.to_owned()),
        None => (hash_id(data.chat_id()), hash_id(message_id)),
    };
    let hashed_user_id = hash_id(required(raw, "user_id")?);
    let hashed_embed_id = hash_id(data.embed_id());
    let resend = kept.and_then(|kept| kept.resend.as_ref());
    let encrypted_content = match resend {
        Some(resend) => resend.encrypted_content.to_owned(),
        None => encrypt_text(content, keys.embed_key, None, nonces)?,
    };
    let encrypted_type = match kept {
        Some(kept) => kept.encrypted_type.to_owned(),
        None => encrypt_text(embed_type, keys.embed_key, None, nonces)?,
    };
    let encrypted_preview = match resend {
        Some(resend) => resend.encrypted_text_preview.map(str::to_owned),
        None => truthy_text(raw, "text_preview")
            .map(|preview| encrypt_text(preview, keys.embed_key, None, nonces))
            .transpose()?,
    };
    if !child && (keys.master_wrapper.is_some() == data.local_only()) {
        return Err(Error::Invalid("Parent embed writes need a master wrapper unless local-only."));
    }
    let chat_wrapper = if child {
        None
    } else {
        let chat_key = keys.chat_key.ok_or(Error::Unavailable {
            code: "embed_chat_key_unavailable",
            reason: "CHAT_KEY_REQUIRED_FOR_EMBED_KEY_WRAPPER",
        })?;
        Some(wrap_key(keys.embed_key, chat_key, nonces)?)
    };

    let decoded = decode_object(content);
    let decoded_text = |key: &str| decoded.as_ref().and_then(|map| text(map, key));
    let (pre_app, pre_skill) = match &decoded {
        Some(_) => (
            text(raw, "app_id").or_else(|| decoded_text("app_id")),
            text(raw, "skill_id").or_else(|| decoded_text("skill_id")),
        ),
        None => (None, None),
    };
    let embed_ref_registration = decoded_text("embed_ref").filter(|r| !r.is_empty()).map(|embed_ref| {
        json!({
            "embed_ref": embed_ref, "embed_id": data.embed_id(),
            "app_id": decoded_text("app_id").or(pre_app), "type": embed_type, "skill_id": pre_skill,
        })
    });

    let mut shared = Map::new();
    shared.insert("encrypted_type".into(), json!(encrypted_type));
    shared.insert("encrypted_content".into(), json!(encrypted_content));
    if let Some(preview) = &encrypted_preview {
        shared.insert("encrypted_text_preview".into(), json!(preview));
    }
    copy_present(&mut shared, raw, "status");
    shared.insert("hashed_chat_id".into(), json!(hashed_chat_id));
    shared.insert("hashed_message_id".into(), json!(hashed_message_id));
    if let Some(task) = truthy_text(raw, "task_id") {
        shared.insert("hashed_task_id".into(), json!(hash_id(task)));
    }
    shared.insert("hashed_user_id".into(), json!(hashed_user_id));
    copy_present(&mut shared, raw, "embed_ids");
    copy_present(&mut shared, raw, "parent_embed_id");
    shared.insert("version_number".into(), or_default(raw, "version_number", json!(1)));
    for key in ["file_path", "content_hash", "text_length_chars"] {
        copy_present(&mut shared, raw, key);
    }
    shared.insert("is_private".into(), or_default(raw, "is_private", json!(false)));
    shared.insert("is_shared".into(), or_default(raw, "is_shared", json!(false)));

    let mut entry = Map::new();
    entry.insert("contentRef".into(), json!(format!("embed:{}", data.embed_id())));
    entry.insert("type".into(), json!(embed_type));
    entry.insert("createdAt".into(), entry_timestamp(raw, "createdAt", "created_at", now_ms));
    entry.insert("updatedAt".into(), entry_timestamp(raw, "updatedAt", "updated_at", now_ms));
    if let Some(app) = pre_app {
        entry.insert("app_id".into(), json!(app));
    }
    if let Some(skill) = pre_skill {
        entry.insert("skill_id".into(), json!(skill));
    }
    entry.insert("embed_id".into(), json!(data.embed_id()));
    entry.extend(shared.clone());
    entry.insert("encryption_mode".into(), json!("client"));

    let store_payload = (!data.local_only()).then(|| {
        let mut store = Map::new();
        store.insert("embed_id".into(), json!(data.embed_id()));
        if let Some(app) = pre_app.filter(|v| !v.is_empty()) {
            store.insert("app_id".into(), json!(app));
        }
        if let Some(skill) = pre_skill.filter(|v| !v.is_empty()) {
            store.insert("skill_id".into(), json!(skill));
        }
        store.insert("chat_id".into(), json!(data.chat_id()));
        store.insert("team_id".into(), json!(text(raw, "team_id")));
        store.extend(shared);
        store.insert("created_at".into(), json!(normalize_to_unix_seconds(raw.get("createdAt"), now_seconds)));
        store.insert("updated_at".into(), json!(normalize_to_unix_seconds(raw.get("updatedAt"), now_seconds)));
        Value::Object(store)
    });

    let mut local_key_wrappers = Vec::new();
    if let Some(chat_wrapper) = chat_wrapper {
        if let Some(master) = keys.master_wrapper {
            local_key_wrappers.push(key_wrapper(&hashed_embed_id, "master", None, master, &hashed_user_id, now_seconds));
        }
        local_key_wrappers.push(key_wrapper(&hashed_embed_id, "chat", Some(&hashed_chat_id), chat_wrapper, &hashed_user_id, now_seconds));
    }
    let server_keys = (local_key_wrappers.len() == 2).then(|| json!({ "keys": local_key_wrappers }));
    Ok(PreparedEmbedWrite {
        local_entry: Value::Object(entry),
        local_key_wrappers,
        store_payload,
        server_keys,
        key_cache_embed_ids: data.key_cache_targets(),
        embed_ref_registration,
        child_ref_embed_ids: child_ref_embed_ids(decoded.as_ref()),
        sealed_history: data.sealed_history(),
        child_revision: None,
    })
}

/// Processing->finished `embed_update` for an embed the stream already holds
/// in plaintext. `normalized_type` is the registry-normalized type (adapter).
pub struct ProcessingEmbedUpdate {
    pub existing: Map<String, Value>,
    pub chat_id: String,
    pub user_id: Option<String>,
    pub message_id: Option<String>,
    pub normalized_type: String,
}
impl ProcessingEmbedUpdate {
    pub fn embed_id(&self) -> &str {
        text(&self.existing, "embed_id").unwrap_or_default()
    }
    pub fn is_child(&self) -> bool {
        truthy_text(&self.existing, "parent_embed_id").is_some()
    }
    pub fn key_cache_targets(&self) -> Vec<String> {
        let embed_type = text(&self.existing, "type").unwrap_or_default();
        cache_targets(self.embed_id(), false, embed_type, &self.existing)
    }
}

/// Nonces: content, type (when present), chat wrapper (parents).
pub fn build_processing_update(
    update: &ProcessingEmbedUpdate,
    keys: WriteKeys<'_>,
    now_ms: i64,
    nonces: &mut impl NonceSource,
) -> Result<PreparedEmbedWrite> {
    let existing = &update.existing;
    let embed_id = update.embed_id();
    if embed_id.is_empty() || update.chat_id.is_empty() {
        return Err(Error::Invalid("Embed update requires embed and chat IDs."));
    }
    let content = truthy_text(existing, "content").ok_or(Error::Invalid("Embed update has no plaintext content."))?;
    let now_seconds = now_ms.div_euclid(1000);
    let child = update.is_child();
    let hashed_chat_id = hash_id(&update.chat_id);
    let hashed_embed_id = hash_id(embed_id);
    let hashed_user_id = update.user_id.as_deref().filter(|u| !u.is_empty()).map_or_else(|| "unknown".to_owned(), hash_id);
    let encrypted_content = encrypt_text(content, keys.embed_key, None, nonces)?;
    let encrypted_type = truthy_text(existing, "type")
        .map(|embed_type| encrypt_text(embed_type, keys.embed_key, None, nonces))
        .transpose()?;
    let mut local_key_wrappers = Vec::new();
    if !child {
        let master = keys.master_wrapper.ok_or(Error::Invalid("Parent embed update needs a master wrapper."))?;
        let chat_key = keys.chat_key.ok_or(Error::Unavailable {
            code: "embed_chat_key_unavailable",
            reason: "CHAT_KEY_REQUIRED_FOR_EMBED_KEY_WRAPPER",
        })?;
        let chat_wrapper = wrap_key(keys.embed_key, chat_key, nonces)?;
        local_key_wrappers.push(key_wrapper(&hashed_embed_id, "master", None, master, &hashed_user_id, now_seconds));
        local_key_wrappers.push(key_wrapper(&hashed_embed_id, "chat", Some(&hashed_chat_id), chat_wrapper, &hashed_user_id, now_seconds));
    }
    let mut rest = Map::new();
    rest.insert("embed_id".into(), json!(embed_id));
    if let Some(encrypted_type) = &encrypted_type {
        rest.insert("encrypted_type".into(), json!(encrypted_type));
    }
    rest.insert("encrypted_content".into(), json!(encrypted_content));
    copy_present(&mut rest, existing, "status");
    rest.insert("hashed_chat_id".into(), json!(hashed_chat_id));
    match update.message_id.as_deref().filter(|m| !m.is_empty()) {
        Some(message_id) => {
            rest.insert("hashed_message_id".into(), json!(hash_id(message_id)));
        }
        None => copy_present(&mut rest, existing, "hashed_message_id"),
    }
    copy_present(&mut rest, existing, "hashed_task_id");
    rest.insert("hashed_user_id".into(), json!(hashed_user_id));
    for key in ["embed_ids", "parent_embed_id", "version_number", "file_path", "content_hash", "text_length_chars"] {
        copy_present(&mut rest, existing, key);
    }
    rest.insert("is_private".into(), or_default(existing, "is_private", json!(false)));
    rest.insert("is_shared".into(), or_default(existing, "is_shared", json!(false)));

    // putEncrypted metadata: pre-extracted existing app/skill win; otherwise
    // metadata-bearing types decode their plaintext (and may register a ref).
    let mut app = text(existing, "app_id").map(str::to_owned);
    let mut skill = text(existing, "skill_id").map(str::to_owned);
    let mut embed_ref_registration = None;
    let mut child_refs = Vec::new();
    if app.is_none() && skill.is_none() && METADATA_TYPES.contains(&update.normalized_type.as_str()) {
        if let Some(decoded) = decode_object(content) {
            app = text(&decoded, "app_id").map(str::to_owned);
            skill = text(&decoded, "skill_id").map(str::to_owned);
            if let Some(embed_ref) = truthy_text(&decoded, "embed_ref") {
                let decoded_type = text(&decoded, "type").unwrap_or(&update.normalized_type);
                let ref_skill = if decoded_type != "app_skill_use" && decoded_type != "app-skill-use" {
                    Some(decoded_type.to_owned())
                } else {
                    skill.clone()
                };
                embed_ref_registration = Some(json!({
                    "embed_ref": embed_ref, "embed_id": embed_id, "app_id": app, "type": decoded_type, "skill_id": ref_skill,
                }));
            }
            child_refs = child_ref_embed_ids(Some(&decoded));
        }
    }
    let mut entry = Map::new();
    entry.insert("contentRef".into(), json!(format!("embed:{embed_id}")));
    copy_present(&mut entry, existing, "type");
    entry.insert("createdAt".into(), entry_timestamp(existing, "createdAt", "created_at", now_ms));
    entry.insert("updatedAt".into(), entry_timestamp(existing, "updatedAt", "updated_at", now_ms));
    if let Some(app) = &app {
        entry.insert("app_id".into(), json!(app));
    }
    if let Some(skill) = &skill {
        entry.insert("skill_id".into(), json!(skill));
    }
    entry.extend(rest.clone());
    entry.insert("encryption_mode".into(), json!("client"));
    let mut store = rest;
    store.insert("created_at".into(), json!(normalize_to_unix_seconds(existing.get("createdAt"), now_seconds)));
    store.insert("updated_at".into(), json!(normalize_to_unix_seconds(existing.get("updatedAt"), now_seconds)));
    let server_keys = (!local_key_wrappers.is_empty()).then(|| json!({ "keys": local_key_wrappers }));
    Ok(PreparedEmbedWrite {
        local_entry: Value::Object(entry),
        local_key_wrappers,
        store_payload: Some(Value::Object(store)),
        server_keys,
        key_cache_embed_ids: update.key_cache_targets(),
        embed_ref_registration,
        child_ref_embed_ids: child_refs,
        sealed_history: false,
        child_revision: None,
    })
}
