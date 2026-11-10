//! Child revision persistence: version N+1 of a generated image child embed
//! (`images-generate.revision.same-embed-new-version`). Shared client core;
//! the shells only perform the ordered IO this module returns. Contract:
//! `docs/plans/image-edit-as-embed-version/wire-contract.md` ("How a client
//! persists version N+1"); the server check is `embed-version-transaction`
//! `requireChildRevisionHead` and the acknowledged child advance.
use super::history::{self, EncryptedDiffRow, same_plaintext};
use super::keys::{NonceSource, decrypt_text, hash_id};
use super::normalize_to_unix_seconds;
use super::payload::{
    KeptHeadCiphertext, KeptHeadIdentity, PreparedEmbedWrite, StreamedEmbedData, WriteKeys,
    build_stream_completion_keeping,
};
use crate::error::{Error, Result};
use serde::Serialize;
use serde_json::{Map, Value, json};
use zeroize::Zeroizing;

const MAX_SAFE_INTEGER: f64 = 9_007_199_254_740_991.0;

/// A revision payload reached the ordinary stream path, which would hash the
/// changing message and re-encrypt the type (403 `project_context_required`).
pub const REVISION_HEAD_REQUIRED: Error = Error::Unavailable {
    code: "embed_revision_head_required",
    reason: "CHILD_REVISION_NEEDS_STORED_HEAD",
};
/// No local head row exists for the revised child.
pub const REVISION_HEAD_MISSING: Error = Error::Unavailable {
    code: "embed_revision_head_missing",
    reason: "CHILD_REVISION_LOCAL_HEAD_MISSING",
};
/// The local head is at another version than `revision.base_version`.
pub const REVISION_BASE_MISMATCH: Error = Error::Unavailable {
    code: "embed_revision_base_mismatch",
    reason: "CHILD_REVISION_HEAD_NOT_AT_BASE_VERSION",
};
/// The head and every required row of this version are already confirmed by
/// the server (full replay): nothing to write; the shell acknowledges the
/// sealed outputs.
pub const REVISION_ALREADY_APPLIED: Error = Error::Unavailable {
    code: "embed_revision_already_applied",
    reason: "CHILD_REVISION_HEAD_ALREADY_AT_VERSION",
};
/// The local head belongs to another parent, chat or type, or lacks the
/// creating-message hash or ciphertext the revision must keep.
pub const REVISION_HEAD_MISMATCH: Error = Error::Unavailable {
    code: "embed_revision_head_mismatch",
    reason: "CHILD_REVISION_HEAD_IDENTITY_MISMATCH",
};
/// The local head is already at N+1 but the required base row N is not
/// stored locally, so the version-N snapshot cannot be rebuilt.
pub const REVISION_BASE_UNAVAILABLE: Error = Error::Unavailable {
    code: "embed_revision_base_unavailable",
    reason: "CHILD_REVISION_BASE_ROW_LOST",
};
/// Another tab or device already stored this `(embed, version)` row with
/// different plaintext: the revision must not overwrite immutable history.
pub const REVISION_ROW_DIVERGED: Error = Error::Unavailable {
    code: "embed_revision_row_diverged",
    reason: "CHILD_REVISION_CANONICAL_ROW_DIFFERS",
};

fn safe_int(value: &Value) -> Option<i64> {
    value
        .as_f64()
        .filter(|n| n.fract() == 0.0 && n.abs() <= MAX_SAFE_INTEGER)
        .map(|n| n as i64)
}
/// `version_number` of a stored head; absent/null means 1.
pub(crate) fn stored_version(head: &Map<String, Value>) -> Result<i64> {
    match head.get("version_number") {
        None | Some(Value::Null) => Ok(1),
        Some(value) => safe_int(value).filter(|v| *v >= 1).ok_or(Error::Protocol),
    }
}

/// `payload.revision` of a child's next version, validated against
/// `version_number` (`version == base_version + 1`, so always above one).
#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize)]
pub struct ChildRevision {
    /// Version N the change was drawn from (the head the client must hold).
    pub base_version: i64,
    /// Version N+1 this event carries.
    pub version: i64,
    /// True when no `embed_diffs` row exists for N: the client writes it from its head.
    pub base_snapshot_required: bool,
}
impl ChildRevision {
    pub(super) fn from_payload(raw: &Map<String, Value>, child: bool) -> Result<Option<Self>> {
        let Some(revision) = raw.get("revision").filter(|value| !value.is_null()) else {
            return Ok(None);
        };
        if !child || !revision.is_object() {
            return Err(Error::Protocol);
        }
        let base_version = revision
            .get("base_version")
            .and_then(safe_int)
            .filter(|v| *v >= 1)
            .ok_or(Error::Protocol)?;
        let base_snapshot_required = revision
            .get("base_snapshot_required")
            .and_then(Value::as_bool)
            .ok_or(Error::Protocol)?;
        let version = raw
            .get("version_number")
            .and_then(safe_int)
            .ok_or(Error::Protocol)?;
        if base_version.checked_add(1) != Some(version) {
            return Err(Error::Protocol);
        }
        Ok(Some(Self {
            base_version,
            version,
            base_snapshot_required,
        }))
    }
}

/// Which `embed_diffs` row a `store_embed_diff` step writes.
#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum RevisionRowRole {
    /// Version N from the local head (only when `base_snapshot_required`).
    BaseSnapshot,
    /// Snapshot-only row of version N+1 from `version_history_rows[0]`.
    History,
}

/// One write of a child revision still missing on the server. Ciphertext and
/// hashes only. The shell stores the local value, sends, and after the send
/// succeeded stores the `confirmed_*` value (the durability marker), so a
/// replay after a crash plans exactly the writes that are still missing.
#[derive(Debug, Serialize)]
#[serde(tag = "op", rename_all = "snake_case")]
// At most three short-lived steps per write: boxing would only add allocations.
#[allow(clippy::large_enum_variant)]
pub enum ChildRevisionStep {
    /// Store `local_row` in `embed_diffs`, send `store_embed_diff` with
    /// `server_payload`, then store `confirmed_row`.
    StoreEmbedDiff {
        role: RevisionRowRole,
        local_row: EncryptedDiffRow,
        server_payload: Value,
        confirmed_row: EncryptedDiffRow,
    },
    /// Store the prepared `local_entry`, send `store_embed` with
    /// `store_payload` (no key wrappers: the child keeps its parent's key and
    /// wrappers), then store `confirmed_entry`.
    StoreEmbed {
        store_payload: Value,
        confirmed_entry: Value,
    },
}

/// Ordered writes of version N+1. The shell runs `steps` strictly in order and
/// stops at the first failure: the extension admits the head only after the
/// version-N history row and the history row N+1 only for an advanced child head.
#[derive(Debug, Serialize)]
pub struct ChildRevisionWrites {
    pub base_version: i64,
    pub version_number: i64,
    pub steps: Vec<ChildRevisionStep>,
}

/// Local-entry key marking a child head stored at N+1 whose `store_embed` is
/// not yet confirmed by the server. Absent on synced and confirmed heads.
pub const PENDING_HEAD_MARKER: &str = "revision_pending_version";

/// Where the local head stands relative to the revision.
#[derive(Clone, Copy, PartialEq, Eq)]
enum HeadStage {
    /// Still at N: nothing of the revision was stored locally.
    AtBase,
    /// Stored locally at N+1 with the event's content; `confirmed` once the
    /// server accepted the head (no [`PENDING_HEAD_MARKER`]).
    Advanced { confirmed: bool },
}

/// Local head of the revised child, checked against the event and opened with
/// the parent's key. Holds ciphertext and hashes; the plaintext stays zeroizing.
pub(super) struct StoredChildHead {
    hashed_message_id: String,
    hashed_chat_id: String,
    encrypted_type: String,
    encrypted_content: String,
    encrypted_text_preview: Option<String>,
    base_created_at: Option<Value>,
    content: Zeroizing<String>,
    stage: HeadStage,
}
impl StoredChildHead {
    /// Validate `head` (the stored `embeds` row / local entry of the child).
    /// A head at N is fresh; a head at N+1 holding the event's content is a
    /// resumed revision (crash or replay after the local head store).
    ///
    /// # Errors
    /// [`REVISION_HEAD_MISSING`], [`REVISION_HEAD_MISMATCH`],
    /// [`REVISION_BASE_MISMATCH`] (any other version, or N+1 with other
    /// content), `Error::Crypto` when the head does not open with the
    /// parent's key (the child would otherwise be re-keyed),
    /// `Error::Protocol` for a malformed row.
    pub(super) fn check(
        head: Option<&Value>,
        data: &StreamedEmbedData,
        revision: &ChildRevision,
        key: &[u8; 32],
    ) -> Result<Self> {
        let head = match head {
            None | Some(Value::Null) => return Err(REVISION_HEAD_MISSING),
            Some(Value::Object(head)) => head,
            Some(_) => return Err(Error::Protocol),
        };
        let field = |name: &str| {
            head.get(name)
                .and_then(Value::as_str)
                .filter(|value| !value.is_empty())
        };
        if field("embed_id") != Some(data.embed_id())
            || field("parent_embed_id") != data.parent_embed_id()
            || field("hashed_chat_id") != Some(hash_id(data.chat_id()).as_str())
        {
            return Err(REVISION_HEAD_MISMATCH);
        }
        let (
            Some(hashed_message_id),
            Some(hashed_chat_id),
            Some(encrypted_type),
            Some(encrypted_content),
        ) = (
            field("hashed_message_id"),
            field("hashed_chat_id"),
            field("encrypted_type"),
            field("encrypted_content"),
        )
        else {
            return Err(REVISION_HEAD_MISMATCH);
        };
        let content = decrypt_text(encrypted_content, key, None)?;
        if decrypt_text(encrypted_type, key, None)?.as_str() != data.embed_type() {
            return Err(REVISION_HEAD_MISMATCH);
        }
        let version = stored_version(head)?;
        let stage = if version == revision.base_version {
            // A base head whose own revision is not yet confirmed: the server
            // may still be at N-1, so this change must wait for that one.
            if head
                .get(PENDING_HEAD_MARKER)
                .is_some_and(|marker| !marker.is_null())
            {
                return Err(REVISION_BASE_MISMATCH);
            }
            HeadStage::AtBase
        } else if version == revision.version
            && data.raw().get("content").and_then(Value::as_str) == Some(content.as_str())
        {
            let pending = match head.get(PENDING_HEAD_MARKER) {
                None | Some(Value::Null) => false,
                Some(marker) => {
                    if safe_int(marker) != Some(revision.version) {
                        return Err(Error::Protocol);
                    }
                    true
                }
            };
            HeadStage::Advanced {
                confirmed: !pending,
            }
        } else {
            return Err(REVISION_BASE_MISMATCH);
        };
        let base_created_at = ["updatedAt", "updated_at", "createdAt", "created_at"]
            .iter()
            .find_map(|name| head.get(*name).filter(|value| !value.is_null()).cloned());
        Ok(Self {
            hashed_message_id: hashed_message_id.to_owned(),
            hashed_chat_id: hashed_chat_id.to_owned(),
            encrypted_type: encrypted_type.to_owned(),
            encrypted_content: encrypted_content.to_owned(),
            encrypted_text_preview: field("encrypted_text_preview").map(str::to_owned),
            base_created_at,
            content,
            stage,
        })
    }
}

/// A snapshot-only local row: anything else is not a child revision row.
fn snapshot_of(row: &EncryptedDiffRow) -> Result<Value> {
    match (&row.encrypted_snapshot, &row.encrypted_patch) {
        (Some(snapshot), None) if !snapshot.is_empty() => Ok(Value::String(snapshot.clone())),
        _ => Err(Error::Conflict),
    }
}

/// Version-N base row, or `None` when the server already confirmed it.
/// - Head at N: an existing local row must hold the head's plaintext and is
///   reused; otherwise the head's own content ciphertext becomes the snapshot
///   (same key, same plaintext, same `base64(IV||ct||tag)` encoding that
///   `writeLegacyEmbedDiff` stores opaquely; no new nonce).
/// - Head already at N+1: the base can only come from the local row stored
///   before the head; without it the base is lost ([`REVISION_BASE_UNAVAILABLE`]).
fn pending_base_row(
    embed_id: &str,
    revision: &ChildRevision,
    head: &StoredChildHead,
    existing: Option<&EncryptedDiffRow>,
    key: &[u8; 32],
    now_seconds: i64,
) -> Result<Option<EncryptedDiffRow>> {
    match (head.stage, existing) {
        (HeadStage::AtBase, Some(row)) => {
            if !same_plaintext(Some(&snapshot_of(row)?), Some(head.content.as_str()), key) {
                return Err(Error::Conflict);
            }
            Ok((!row.server_confirmed).then(|| row.clone()))
        }
        (HeadStage::AtBase, None) => {
            let created_at = normalize_to_unix_seconds(head.base_created_at.as_ref(), now_seconds);
            Ok(Some(EncryptedDiffRow::new(
                embed_id,
                revision.base_version,
                Some(head.encrypted_content.clone()),
                None,
                created_at,
            )))
        }
        (HeadStage::Advanced { .. }, Some(row)) => {
            snapshot_of(row)?;
            Ok((!row.server_confirmed).then(|| row.clone()))
        }
        (HeadStage::Advanced { .. }, None) => Err(REVISION_BASE_UNAVAILABLE),
    }
}

fn diff_step(
    role: RevisionRowRole,
    local_row: EncryptedDiffRow,
    hashed_user_id: &str,
) -> ChildRevisionStep {
    let server_payload = local_row.server_payload(hashed_user_id);
    let confirmed_row = local_row.clone().confirmed();
    ChildRevisionStep::StoreEmbedDiff {
        role,
        local_row,
        server_payload,
        confirmed_row,
    }
}

/// Build the writes of version N+1 that are still missing on the server, in
/// the contract order: base snapshot (when required), head, history row N+1.
/// Durability comes from the local markers: `server_confirmed` on rows and
/// [`PENDING_HEAD_MARKER`] on the head. The head keeps the stored
/// `hashed_message_id`/`hashed_chat_id`/`encrypted_type` and the original
/// `parent_embed_id`; content is encrypted with the parent's key, and a
/// resumed head resends its stored ciphertext.
/// Nonces: content and preview (fresh head only), history snapshot (unless a
/// local row is reused).
///
/// # Errors
/// [`REVISION_ALREADY_APPLIED`] when head and every row are confirmed;
/// [`REVISION_BASE_UNAVAILABLE`]; `Error::Protocol` for history rows outside
/// the contract shape; `Error::Conflict` when a stored diff row holds other
/// plaintext or is not snapshot-only; `Error::Invalid` for a local-only
/// revision; crypto errors from encryption.
pub(super) fn build_child_revision(
    data: &StreamedEmbedData,
    revision: &ChildRevision,
    head: &StoredChildHead,
    existing: &[EncryptedDiffRow],
    key: &[u8; 32],
    now_ms: i64,
    nonces: &mut impl NonceSource,
) -> Result<PreparedEmbedWrite> {
    let embed_id = data.embed_id();
    let rows = data.version_history_rows();
    history::validate_child_revision_rows(rows, embed_id, revision.version)?;
    if data.local_only() {
        return Err(Error::Invalid("A child revision is never local-only."));
    }
    let now_seconds = now_ms.div_euclid(1000);
    let user_id = data
        .raw()
        .get("user_id")
        .and_then(Value::as_str)
        .ok_or(Error::Protocol)?;
    let hashed_user_id = hash_id(user_id);
    let existing_at = |version: i64| existing.iter().find(|row| row.version_number == version);

    let mut steps = Vec::with_capacity(3);
    if revision.base_snapshot_required {
        let base = existing_at(revision.base_version);
        if let Some(row) = pending_base_row(embed_id, revision, head, base, key, now_seconds)? {
            steps.push(diff_step(
                RevisionRowRole::BaseSnapshot,
                row,
                &hashed_user_id,
            ));
        }
    }
    let resend = matches!(head.stage, HeadStage::Advanced { .. }).then(|| KeptHeadCiphertext {
        encrypted_content: &head.encrypted_content,
        encrypted_text_preview: head.encrypted_text_preview.as_deref(),
    });
    let kept = KeptHeadIdentity {
        hashed_message_id: &head.hashed_message_id,
        hashed_chat_id: &head.hashed_chat_id,
        encrypted_type: &head.encrypted_type,
        resend,
    };
    let keys = WriteKeys {
        embed_key: key,
        chat_key: None,
        master_wrapper: None,
    };
    let mut prepared = build_stream_completion_keeping(data, keys, now_ms, nonces, Some(&kept))?;
    let confirmed_entry = prepared.local_entry.clone();
    if head.stage != (HeadStage::Advanced { confirmed: true }) {
        let store_payload = prepared
            .store_payload
            .clone()
            .ok_or(Error::Invalid("A child revision needs a store payload."))?;
        let entry = prepared
            .local_entry
            .as_object_mut()
            .ok_or(Error::Protocol)?;
        entry.insert(PENDING_HEAD_MARKER.into(), json!(revision.version));
        steps.push(ChildRevisionStep::StoreEmbed {
            store_payload,
            confirmed_entry,
        });
    }
    let history_existing = existing_at(revision.version);
    if let Some(row) = history_existing {
        snapshot_of(row)?;
    }
    // Reuses a matching local row (same ciphertext on replay), refuses other plaintext.
    let local_row =
        history::reconcile_sealed_row(&rows[0], history_existing, key, now_seconds, nonces)?
            .ok_or(Error::Protocol)?;
    if !history_existing.is_some_and(|row| row.server_confirmed) {
        steps.push(diff_step(
            RevisionRowRole::History,
            local_row,
            &hashed_user_id,
        ));
    }
    if steps.is_empty() {
        return Err(REVISION_ALREADY_APPLIED);
    }
    prepared.child_revision = Some(ChildRevisionWrites {
        base_version: revision.base_version,
        version_number: revision.version,
        steps,
    });
    Ok(prepared)
}

/// `store_embed_diff` answered `embed_diff_conflict` (or the extension's
/// `immutable_version_mismatch`) for a revision step's `local_row`: another tab
/// or device stored that row first with its own ciphertext. `page` is the
/// bounded-v1 canonical read of that version. The canonical row is adopted
/// (and becomes the local row) only when it opens to the same plaintext as
/// `local_row`; child rows are snapshot-only, so a patch on either side fails.
///
/// # Errors
/// [`REVISION_ROW_DIVERGED`] when the canonical row holds other plaintext or
/// is not a single snapshot-only row; `Error::Protocol` for a page of another
/// embed/version or a `local_row` with a patch; `Error::Crypto` when
/// `local_row` does not open with `key`.
pub fn adopt_conflicting_row(
    page: &Value,
    local_row: &EncryptedDiffRow,
    key: &[u8; 32],
    now_seconds: i64,
) -> Result<EncryptedDiffRow> {
    let snapshot = local_row
        .encrypted_snapshot
        .as_deref()
        .filter(|s| !s.is_empty())
        .ok_or(Error::Protocol)?;
    if local_row.encrypted_patch.is_some() {
        return Err(Error::Protocol);
    }
    let plaintext = decrypt_text(snapshot, key, None)?;
    let mut expected = json!({
        "embed_id": local_row.embed_id, "version_number": local_row.version_number, "snapshot": plaintext.as_str(),
    });
    let adopted = history::adopt_canonical_row(page, &expected, key, now_seconds);
    // The synthetic row holds plaintext; wipe it before returning.
    crate::model::zeroize_json(&mut expected);
    match adopted {
        Err(Error::Conflict) => Err(REVISION_ROW_DIVERGED),
        // The server holds exactly this row: it is durable by definition.
        other => other.map(EncryptedDiffRow::confirmed),
    }
}
