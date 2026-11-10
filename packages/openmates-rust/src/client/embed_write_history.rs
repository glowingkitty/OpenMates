//! Encrypted embed revision history writes (`streamedEmbedRevisionHistory.ts`
//! and `embedDiffStore.ts`). Rows keep the `embed_diffs` IndexedDB shape:
//! id `${embed_id}_v${n}`, base64(IV||ct||tag) snapshot/patch, unix seconds.
//! HTTP/WS/IndexedDB IO stays in the adapter; Rust decides and encrypts.
use super::keys::{NonceSource, decrypt_text, encrypt_text, hash_id};
use super::normalize_to_unix_seconds;
use crate::error::{Error, Result};
use serde::{Deserialize, Serialize};
use serde_json::{Value, json};
use std::collections::{HashMap, HashSet};
use zeroize::Zeroizing;

/// Every 32nd version carries a full encrypted snapshot checkpoint.
pub const SNAPSHOT_INTERVAL: i64 = 32;
const MAX_SAFE_INTEGER: f64 = 9_007_199_254_740_991.0;

#[derive(Clone, PartialEq, Eq, Serialize, Deserialize, Debug)]
pub struct EncryptedDiffRow {
    pub id: String,
    pub embed_id: String,
    pub version_number: i64,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub encrypted_snapshot: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub encrypted_patch: Option<String>,
    pub created_at: i64,
    /// Local durability marker of child revision rows
    /// (`images-generate.revision.same-embed-new-version`): true once the
    /// server stored this exact row (its `store_embed_diff` succeeded, or it
    /// was adopted/cached from a canonical page). Never sent; omitted when
    /// false, so every other row keeps its deployed IndexedDB shape.
    #[serde(default, skip_serializing_if = "is_false")]
    pub server_confirmed: bool,
}
fn is_false(value: &bool) -> bool {
    !*value
}
impl EncryptedDiffRow {
    pub(super) fn new(embed_id: &str, version: i64, snapshot: Option<String>, patch: Option<String>, created_at: i64) -> Self {
        Self {
            id: format!("{embed_id}_v{version}"),
            embed_id: embed_id.to_owned(),
            version_number: version,
            encrypted_snapshot: snapshot,
            encrypted_patch: patch,
            created_at,
            server_confirmed: false,
        }
    }
    /// This row marked as stored by the server (see `server_confirmed`).
    pub fn confirmed(mut self) -> Self {
        self.server_confirmed = true;
        self
    }
    /// `store_embed_diff` WebSocket payload (absent ciphertext is `null`).
    pub fn server_payload(&self, hashed_user_id: &str) -> Value {
        json!({
            "embed_id": self.embed_id, "version_number": self.version_number,
            "encrypted_snapshot": self.encrypted_snapshot, "encrypted_patch": self.encrypted_patch,
            "hashed_user_id": hashed_user_id, "created_at": self.created_at,
        })
    }
}

/// One streamed `version_history_rows` element (plaintext snapshot/patch).
/// Not Debug: it carries plaintext.
pub struct StreamedHistoryRow<'a> {
    pub embed_id: Option<&'a str>,
    pub version: Option<i64>,
    pub snapshot: Option<&'a str>,
    pub patch: Option<&'a str>,
    pub created_at: Option<&'a Value>,
}
impl<'a> StreamedHistoryRow<'a> {
    pub fn parse(row: &'a Value) -> Self {
        let version = row.get("version_number").and_then(|v| match v.as_f64() {
            Some(n) if n.fract() == 0.0 && n.abs() <= MAX_SAFE_INTEGER => Some(n as i64),
            _ => None,
        });
        Self {
            embed_id: row.get("embed_id").and_then(Value::as_str),
            version,
            snapshot: row.get("snapshot").and_then(Value::as_str),
            patch: row.get("patch").and_then(Value::as_str),
            created_at: row.get("created_at"),
        }
    }
    fn created_at(&self, now_seconds: i64) -> i64 {
        normalize_to_unix_seconds(self.created_at, now_seconds)
    }
}

/// Ordinary (non-sealed) path: encrypt `typeof === "string"` snapshot then
/// patch. `None` for rows TS skips (no id/version, nothing to store).
pub fn encrypt_streamed_row(row: &Value, key: &[u8; 32], now_seconds: i64, nonces: &mut impl NonceSource) -> Result<Option<EncryptedDiffRow>> {
    let parsed = StreamedHistoryRow::parse(row);
    let (Some(embed_id), Some(version)) = (parsed.embed_id.filter(|id| !id.is_empty()), parsed.version) else {
        return Ok(None);
    };
    let snapshot = parsed.snapshot.map(|text| encrypt_text(text, key, None, nonces)).transpose()?;
    let patch = parsed.patch.map(|text| encrypt_text(text, key, None, nonces)).transpose()?;
    if snapshot.is_none() && patch.is_none() {
        return Ok(None);
    }
    Ok(Some(EncryptedDiffRow::new(embed_id, version, snapshot, patch, parsed.created_at(now_seconds))))
}

/// Sealed root revision: identity, range and uniqueness of streamed rows.
pub fn validate_sealed_rows(rows: &[Value], embed_id: &str, declared_version: f64) -> Result<()> {
    let mut seen = HashSet::new();
    for row in rows {
        let parsed = StreamedHistoryRow::parse(row);
        let valid = parsed.embed_id == Some(embed_id)
            && parsed.version.is_some_and(|v| v >= 1 && (v as f64) <= declared_version && seen.insert(v));
        if !valid {
            return Err(Error::Protocol);
        }
    }
    Ok(())
}

/// Child revision (`images-generate.revision.same-embed-new-version`): the
/// streamed history is exactly one snapshot-only row for `version` (children
/// are full-replacement versions; `operations.js` accepts no other shape).
///
/// # Errors
/// `Error::Protocol` for any other embed id, version, count, an empty
/// snapshot or a present patch.
pub fn validate_child_revision_rows(rows: &[Value], embed_id: &str, version: i64) -> Result<()> {
    let [row] = rows else { return Err(Error::Protocol) };
    let parsed = StreamedHistoryRow::parse(row);
    let patch_absent = row.get("patch").is_none_or(Value::is_null);
    if parsed.embed_id != Some(embed_id)
        || parsed.version != Some(version)
        || parsed.snapshot.is_none_or(str::is_empty)
        || !patch_absent
    {
        return Err(Error::Protocol);
    }
    Ok(())
}

/// `samePlaintext`: expected `None` requires absent/null ciphertext.
pub fn same_plaintext(ciphertext: Option<&Value>, expected: Option<&str>, key: &[u8; 32]) -> bool {
    match (ciphertext.filter(|v| !v.is_null()), expected) {
        (None, None) => true,
        (Some(Value::String(text)), Some(expected)) => {
            decrypt_text(text, key, None).is_ok_and(|plain| plain.as_str() == expected)
        }
        _ => false,
    }
}
fn opt_value(value: &Option<String>) -> Option<Value> {
    value.as_ref().map(|text| Value::String(text.clone()))
}

/// Sealed path for one row: existing local ciphertext must hold the same
/// plaintext and is reused; otherwise truthy plaintext is encrypted. Never sent.
pub fn reconcile_sealed_row(
    row: &Value,
    existing: Option<&EncryptedDiffRow>,
    key: &[u8; 32],
    now_seconds: i64,
    nonces: &mut impl NonceSource,
) -> Result<Option<EncryptedDiffRow>> {
    let parsed = StreamedHistoryRow::parse(row);
    let (Some(embed_id), Some(version)) = (parsed.embed_id.filter(|id| !id.is_empty()), parsed.version) else {
        return Ok(None);
    };
    if let Some(existing) = existing {
        if !same_plaintext(opt_value(&existing.encrypted_snapshot).as_ref(), parsed.snapshot, key)
            || !same_plaintext(opt_value(&existing.encrypted_patch).as_ref(), parsed.patch, key)
        {
            return Err(Error::Conflict);
        }
    }
    let reuse = |field: Option<&String>| field.cloned();
    let snapshot = match reuse(existing.and_then(|e| e.encrypted_snapshot.as_ref())) {
        Some(found) => Some(found),
        None => parsed.snapshot.filter(|s| !s.is_empty()).map(|s| encrypt_text(s, key, None, nonces)).transpose()?,
    };
    let patch = match reuse(existing.and_then(|e| e.encrypted_patch.as_ref())) {
        Some(found) => Some(found),
        None => parsed.patch.filter(|s| !s.is_empty()).map(|s| encrypt_text(s, key, None, nonces)).transpose()?,
    };
    if snapshot.as_deref().is_none_or(str::is_empty) && patch.as_deref().is_none_or(str::is_empty) {
        return Ok(None);
    }
    Ok(Some(EncryptedDiffRow::new(embed_id, version, snapshot, patch, parsed.created_at(now_seconds))))
}

/// Classified bounded-v1 canonical version read.
#[derive(Clone, Copy, PartialEq, Eq, Debug)]
pub enum CanonicalRead {
    /// Not yet canonical: write the local row and send it.
    Absent,
    /// Response body is a page to validate.
    Present,
}
/// Per-row adoption read: 404, or 409 `snapshot_required` for v1, is absent.
pub fn classify_canonical_read(status: u16, body: Option<&Value>, version: i64) -> Result<CanonicalRead> {
    match status {
        404 => Ok(CanonicalRead::Absent),
        409 if version == 1 && body.and_then(|b| b.get("detail")).and_then(Value::as_str) == Some("snapshot_required") => {
            Ok(CanonicalRead::Absent)
        }
        200..=299 => Ok(CanonicalRead::Present),
        _ => Err(Error::Unavailable { code: "embed_history_read_failed", reason: "CANONICAL_REVISION_HISTORY_READ_FAILED" }),
    }
}
/// Durable-head verification read: 404/409 mean sealed recovery is pending.
pub fn classify_head_read(status: u16) -> Result<CanonicalRead> {
    match status {
        404 | 409 => Ok(CanonicalRead::Absent),
        200..=299 => Ok(CanonicalRead::Present),
        _ => Err(Error::Unavailable { code: "embed_history_read_failed", reason: "CANONICAL_REVISION_HISTORY_READ_FAILED" }),
    }
}
fn page_rows<'a>(page: &'a Value, embed_id: &str, version: i64) -> Result<&'a Vec<Value>> {
    if page.get("embed_id").and_then(Value::as_str) != Some(embed_id)
        || page.get("version_number").and_then(Value::as_i64) != Some(version)
    {
        return Err(Error::Protocol);
    }
    page.get("rows").and_then(Value::as_array).ok_or(Error::Protocol)
}
fn canonical_text(row: &Value, key: &str) -> Option<String> {
    row.get(key).and_then(Value::as_str).map(str::to_owned)
}

/// `adoptCanonicalRow`: the single canonical row for `version` must equal the
/// streamed plaintext; its ciphertext becomes the local row.
pub fn adopt_canonical_row(page: &Value, row: &Value, key: &[u8; 32], now_seconds: i64) -> Result<EncryptedDiffRow> {
    let parsed = StreamedHistoryRow::parse(row);
    let (Some(embed_id), Some(version)) = (parsed.embed_id, parsed.version) else {
        return Err(Error::Protocol);
    };
    let rows = page_rows(page, embed_id, version)?;
    let matching: Vec<&Value> = rows.iter().filter(|r| r.get("version_number").and_then(Value::as_i64) == Some(version)).collect();
    let [canonical] = matching.as_slice() else { return Err(Error::Conflict) };
    if !same_plaintext(canonical.get("encrypted_snapshot"), parsed.snapshot, key)
        || !same_plaintext(canonical.get("encrypted_patch"), parsed.patch, key)
    {
        return Err(Error::Conflict);
    }
    Ok(EncryptedDiffRow::new(
        embed_id,
        version,
        canonical_text(canonical, "encrypted_snapshot"),
        canonical_text(canonical, "encrypted_patch"),
        normalize_to_unix_seconds(canonical.get("created_at"), now_seconds),
    ))
}

/// Highest streamed version owned by `embed_id` (the durable head to read).
pub fn head_version(rows: &[Value], embed_id: &str) -> Option<i64> {
    rows.iter()
        .map(StreamedHistoryRow::parse)
        .filter(|r| r.embed_id == Some(embed_id))
        .filter_map(|r| r.version.filter(|v| *v > 0))
        .max()
}
/// Verify every streamed row against the canonical head page and return the
/// canonical ciphertext rows to store locally.
pub fn verify_canonical_head(page: &Value, rows: &[Value], embed_id: &str, key: &[u8; 32], now_seconds: i64) -> Result<Vec<EncryptedDiffRow>> {
    let Some(head) = head_version(rows, embed_id) else { return Ok(Vec::new()) };
    let canonical_rows = page_rows(page, embed_id, head)?;
    let mut by_version = HashMap::new();
    for canonical in canonical_rows {
        let version = canonical.get("version_number").and_then(Value::as_i64).ok_or(Error::Protocol)?;
        if by_version.insert(version, canonical).is_some() {
            return Err(Error::Protocol);
        }
    }
    let mut verified = Vec::new();
    for row in rows {
        let parsed = StreamedHistoryRow::parse(row);
        let Some(version) = parsed.version.filter(|v| *v > 0 && parsed.embed_id == Some(embed_id)) else { continue };
        let canonical = by_version.get(&version).ok_or(Error::Conflict)?;
        if !same_plaintext(canonical.get("encrypted_snapshot"), parsed.snapshot, key)
            || !same_plaintext(canonical.get("encrypted_patch"), parsed.patch, key)
        {
            return Err(Error::Conflict);
        }
        verified.push(EncryptedDiffRow::new(
            embed_id,
            version,
            canonical_text(canonical, "encrypted_snapshot"),
            canonical_text(canonical, "encrypted_patch"),
            parsed.created_at(now_seconds),
        ));
    }
    Ok(verified)
}

/// `buildUnifiedDiff`: legacy LF-preserving whole-content replacement patch.
pub fn build_unified_diff(current: &str, restored: &str, current_version: i64, new_version: i64) -> String {
    let split = |text: &str| -> Vec<String> {
        if text.is_empty() { Vec::new() } else { text.split('\n').map(str::to_owned).collect() }
    };
    let (old, new) = (split(current), split(restored));
    let start = |lines: &[String]| usize::from(!lines.is_empty());
    let mut out = Vec::with_capacity(3 + old.len() + new.len());
    out.push(format!("--- v{current_version}"));
    out.push(format!("+++ v{new_version}"));
    out.push(format!("@@ -{},{} +{},{} @@", start(&old), old.len(), start(&new), new.len()));
    out.extend(old.iter().map(|line| format!("-{line}")));
    out.extend(new.iter().map(|line| format!("+{line}")));
    out.join("\n")
}

#[derive(Serialize, Debug)]
pub struct RestorePlan {
    pub new_version: i64,
    pub content_hash: String,
    pub diff_row: EncryptedDiffRow,
}
/// Inputs of `restoreEmbedVersion` (plaintext: intentionally not Debug).
pub struct RestoreRequest<'a> {
    pub embed_id: &'a str,
    pub selected_version: i64,
    pub current_version: i64,
    pub current_content: &'a str,
    pub restored_content: &'a str,
}
/// `restoreEmbedVersion` encryption: patch, then a checkpoint snapshot when
/// the new version is a multiple of 32. Nonces: patch, snapshot.
pub fn prepare_restore(
    request: &RestoreRequest<'_>,
    key: &[u8; 32],
    now_seconds: i64,
    nonces: &mut impl NonceSource,
) -> Result<RestorePlan> {
    if request.selected_version == request.current_version {
        return Err(Error::Invalid("Selected version is already current."));
    }
    let new_version = request.current_version.checked_add(1).ok_or(Error::Protocol)?;
    let patch = Zeroizing::new(build_unified_diff(
        request.current_content,
        request.restored_content,
        request.current_version,
        new_version,
    ));
    let encrypted_patch = encrypt_text(&patch, key, None, nonces)?;
    let encrypted_snapshot = (new_version % SNAPSHOT_INTERVAL == 0)
        .then(|| encrypt_text(request.restored_content, key, None, nonces))
        .transpose()?;
    Ok(RestorePlan {
        new_version,
        content_hash: hash_id(request.restored_content),
        diff_row: EncryptedDiffRow::new(request.embed_id, new_version, encrypted_snapshot, Some(encrypted_patch), now_seconds),
    })
}

/// Client snapshot publication after reconstructing a long writable chain.
pub fn should_publish_client_snapshot(row_count: usize, readonly: Option<bool>) -> bool {
    row_count > SNAPSHOT_INTERVAL as usize && readonly == Some(false)
}
/// `publishClientSnapshot` request body.
pub fn client_snapshot_body(
    content: &str,
    version: i64,
    current_version: i64,
    project: Option<(&str, Option<&str>)>,
    key: &[u8; 32],
    nonces: &mut impl NonceSource,
) -> Result<Value> {
    let mut body = json!({
        "encrypted_snapshot": encrypt_text(content, key, None, nonces)?,
        "expected_revision": current_version,
        "operation_id": format!("snapshot.v{version}"),
    });
    if let Some((project_id, team_id)) = project {
        body["project_id"] = json!(project_id);
        if let Some(team_id) = team_id {
            body["team_id"] = json!(team_id);
        }
    }
    Ok(body)
}
/// Reconstruct a version from encrypted rows (snapshot + ordered patches).
pub fn reconstruct(rows: &[Value], key: &[u8; 32]) -> Result<Zeroizing<String>> {
    crate::sdk_embeds::reconstruct_version_rows(rows, key)
}
