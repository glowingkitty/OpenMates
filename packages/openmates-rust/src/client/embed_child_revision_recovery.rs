//! Recovery receipts of a generated image child's version N+1
//! (`images-generate.revision.same-embed-new-version`). Shared client core:
//! the server seals two recovery outputs per change, `(embed, N+1)` (the
//! `send_embed_data` payload with `revision`) and `(diff, N+1)` (its snapshot-only
//! history row). This module decides, from the canonical server rows, whether
//! that exact version is stored and which digest the shell acknowledges
//! (`chat-recovery-transaction` `acknowledgeOutputEmbed`). Contract:
//! `docs/plans/image-edit-as-embed-version/wire-contract.md` ("The same event
//! arrives through recovery").
use super::history::validate_child_revision_rows;
use super::keys::{decrypt_text, hash_id};
use super::payload::StreamedEmbedData;
use super::revision::{REVISION_HEAD_MISMATCH, stored_version};
use crate::error::{Error, Result};
use serde::Serialize;
use serde_json::{Value, json};

/// The canonical row of the sealed version opens to other plaintext, so the
/// server holds a different version N+1 than the one this output seals.
pub const REVISION_CANONICAL_DIFFERS: Error = Error::Unavailable {
    code: "embed_revision_canonical_differs",
    reason: "CHILD_REVISION_CANONICAL_CONTENT_DIFFERS",
};

/// `canonical_source` of a receipt: which canonical row the digest covers.
#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum ReceiptSource {
    /// The head is exactly at the sealed version: digest of its `encrypted_content`.
    Head,
    /// The `embed_diffs` row of the sealed version: digest of `[snapshot, patch]`.
    VersionRow,
}

/// What the canonical server state proves for one sealed revision output.
#[derive(Clone, Debug, PartialEq, Eq, Serialize)]
#[serde(tag = "state", rename_all = "snake_case")]
pub enum RevisionRecoveryReceipt {
    /// The server does not hold this version yet: the shell writes it through
    /// `prepare_child_revision` (embed output) or waits for that write (diff
    /// output); nothing is acknowledged.
    NotApplied,
    /// The head is already past this version: the shell reads the bounded-v1
    /// page of `version` and asks again with it.
    VersionPageRequired { version: i64 },
    /// The server holds exactly the sealed version: acknowledge with this
    /// digest and source (the server recomputes both under its lock).
    Verified {
        canonical_digest: String,
        canonical_source: ReceiptSource,
    },
}

fn field<'a>(row: &'a Value, name: &str) -> Option<&'a str> {
    row.get(name).and_then(Value::as_str).filter(|value| !value.is_empty())
}

/// `digest([encrypted_snapshot, encrypted_patch])` of the extension (its
/// `stableJson` of an array equals compact JSON) and of the web shell's
/// `computeSHA256(JSON.stringify([snapshot, patch]))`.
fn row_digest(snapshot: &str) -> String {
    hash_id(&json!([snapshot, Value::Null]).to_string())
}

/// Row `version` of a bounded-v1 page (`{embed_id, version_number, rows}`):
/// exactly one snapshot-only row whose snapshot opens to `expected`.
fn verify_page_row(page: &Value, embed_id: &str, version: i64, expected: &str, key: &[u8; 32]) -> Result<RevisionRecoveryReceipt> {
    if field(page, "embed_id") != Some(embed_id) || page.get("version_number").and_then(Value::as_i64) != Some(version) {
        return Err(Error::Protocol);
    }
    let rows = page.get("rows").and_then(Value::as_array).ok_or(Error::Protocol)?;
    let matching: Vec<&Value> = rows
        .iter()
        .filter(|row| row.get("version_number").and_then(Value::as_i64) == Some(version))
        .collect();
    let [row] = matching.as_slice() else {
        return Err(Error::Protocol);
    };
    // Child versions are full replacements: a patch here is not this output's row.
    if !row.get("encrypted_patch").is_none_or(Value::is_null) {
        return Err(REVISION_CANONICAL_DIFFERS);
    }
    let snapshot = field(row, "encrypted_snapshot").ok_or(Error::Protocol)?;
    if decrypt_text(snapshot, key, None)?.as_str() != expected {
        return Err(REVISION_CANONICAL_DIFFERS);
    }
    Ok(RevisionRecoveryReceipt::Verified {
        canonical_digest: row_digest(snapshot),
        canonical_source: ReceiptSource::VersionRow,
    })
}

/// True when a sealed `(diff, N)` output content is a child revision row:
/// one snapshot-only row with `version_number >= 2` (root revision rows of
/// version two and above always carry a patch).
pub fn is_child_revision_row(row: &Value) -> bool {
    let version = row.get("version_number").and_then(Value::as_i64).unwrap_or(0);
    let embed_id = field(row, "embed_id").unwrap_or_default();
    version >= 2 && validate_child_revision_rows(std::slice::from_ref(row), embed_id, version).is_ok()
}

/// Receipt of a sealed `(embed, N+1)` output (`sealed` = its `send_embed_data`
/// payload with `revision`). `canonical_head` is the server row
/// (`GET /v1/embeds/chats/{chat}/embeds/{id}`), `page` the bounded-v1 page of
/// N+1 when asked for, `stored_head` this device's local head when it has one.
/// `key` is the parent's key (children inherit it).
///
/// Identity: same embed, chat hash and original parent; the type opens to the
/// sealed type. The head keeps the hash of the message that created the image
/// (not the sealed changing message): it must equal the local head's hash when
/// one is stored; the extension compares it with the sealed record on ACK.
///
/// # Errors
/// [`REVISION_HEAD_MISMATCH`] for another embed, chat, parent, type or creating
/// message; [`REVISION_CANONICAL_DIFFERS`] when version N+1 holds other
/// content; `Error::Protocol` for a payload without `revision`, a malformed
/// row or page; `Error::Crypto` when a ciphertext does not open with `key`.
pub fn embed_receipt(
    sealed: &StreamedEmbedData,
    canonical_head: &Value,
    page: Option<&Value>,
    stored_head: Option<&Value>,
    key: &[u8; 32],
) -> Result<RevisionRecoveryReceipt> {
    let revision = sealed.child_revision()?.ok_or(Error::Protocol)?;
    let parent = sealed.parent_embed_id().ok_or(Error::Protocol)?;
    let content = sealed.raw().get("content").and_then(Value::as_str).ok_or(Error::Protocol)?;
    let message_hash = field(canonical_head, "hashed_message_id");
    // A stored row without the hash (an entry cached before heads carried it)
    // proves nothing either way; the canonical row is the authority.
    let stored_hash = stored_head.and_then(|head| field(head, "hashed_message_id"));
    if field(canonical_head, "embed_id") != Some(sealed.embed_id())
        || field(canonical_head, "hashed_chat_id") != Some(hash_id(sealed.chat_id()).as_str())
        || field(canonical_head, "parent_embed_id") != Some(parent)
        || message_hash.is_none()
        || stored_hash.is_some_and(|stored| Some(stored) != message_hash)
    {
        return Err(REVISION_HEAD_MISMATCH);
    }
    let encrypted_type = field(canonical_head, "encrypted_type").ok_or(REVISION_HEAD_MISMATCH)?;
    if decrypt_text(encrypted_type, key, None)?.as_str() != sealed.embed_type() {
        return Err(REVISION_HEAD_MISMATCH);
    }
    let version = stored_version(canonical_head.as_object().ok_or(Error::Protocol)?)?;
    if version < revision.version {
        return Ok(RevisionRecoveryReceipt::NotApplied);
    }
    if version > revision.version {
        return match page {
            None => Ok(RevisionRecoveryReceipt::VersionPageRequired { version: revision.version }),
            Some(page) => verify_page_row(page, sealed.embed_id(), revision.version, content, key),
        };
    }
    let encrypted = field(canonical_head, "encrypted_content").ok_or(Error::Protocol)?;
    if decrypt_text(encrypted, key, None)?.as_str() != content {
        return Err(REVISION_CANONICAL_DIFFERS);
    }
    Ok(RevisionRecoveryReceipt::Verified {
        canonical_digest: hash_id(encrypted),
        canonical_source: ReceiptSource::Head,
    })
}

/// Receipt of a sealed `(diff, N+1)` child revision row (`row` =
/// `{embed_id, version_number, snapshot, created_at}`). `canonical_head`
/// is the server head (its `parent_embed_id` names the key owner), `page`
/// the bounded-v1 page of N+1 or `None` when the server has no such row
/// (404). `key` is the parent's key.
///
/// # Errors
/// `Error::Protocol` when `row` is not a child revision row or the page is
/// malformed; [`REVISION_HEAD_MISMATCH`] for a head of another embed or a
/// root head; [`REVISION_CANONICAL_DIFFERS`] when the stored row holds other
/// content; `Error::Crypto` when it does not open with `key`.
pub fn row_receipt(row: &Value, canonical_head: &Value, page: Option<&Value>, key: &[u8; 32]) -> Result<RevisionRecoveryReceipt> {
    if !is_child_revision_row(row) {
        return Err(Error::Protocol);
    }
    let embed_id = field(row, "embed_id").ok_or(Error::Protocol)?;
    let version = row.get("version_number").and_then(Value::as_i64).ok_or(Error::Protocol)?;
    let snapshot = field(row, "snapshot").ok_or(Error::Protocol)?;
    if field(canonical_head, "embed_id") != Some(embed_id) || field(canonical_head, "parent_embed_id").is_none() {
        return Err(REVISION_HEAD_MISMATCH);
    }
    // The extension admits row N+1 only for a head already at N+1 or later.
    if stored_version(canonical_head.as_object().ok_or(Error::Protocol)?)? < version {
        return Ok(RevisionRecoveryReceipt::NotApplied);
    }
    match page {
        None => Ok(RevisionRecoveryReceipt::NotApplied),
        Some(page) => verify_page_row(page, embed_id, version, snapshot, key),
    }
}
