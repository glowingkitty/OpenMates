//! Message-scoped image versions (`images-generate.revision.message-shows-its-version`).
//! Shared client core: resolves which version of an image embed each message
//! shows from the `pinned_embeds` of the chat's `app_skill_use` parents, and
//! opens that version's content (head or `embed_diffs` snapshot). Contract:
//! `docs/plans/image-edit-as-embed-version/wire-contract.md` ("How a client
//! reads version K of an image"). Shells only render the result.
use super::payload::decode_object;
use super::revision::stored_version;
use crate::error::{Error, Result};
use serde::{Deserialize, Serialize};
use serde_json::{Map, Value};
use zeroize::Zeroizing;

const MAX_SAFE_INTEGER: f64 = 9_007_199_254_740_991.0;

/// Version K is not stored locally (no head at K and no `embed_diffs` row K).
pub const VERSION_UNAVAILABLE: Error = Error::Unavailable {
    code: "embed_version_unavailable",
    reason: "EMBED_VERSION_NOT_STORED",
};

/// One `pinned_embeds` entry of a finished `app_skill_use` parent: the message
/// of that parent shows `embed_id` at `version`.
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub struct PinnedEmbed {
    pub embed_id: String,
    pub version: i64,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub embed_ref: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub previous_version: Option<i64>,
}

fn safe_int(value: &Value) -> Option<i64> {
    value
        .as_f64()
        .filter(|n| n.fract() == 0.0 && n.abs() <= MAX_SAFE_INTEGER)
        .map(|n| n as i64)
}
fn pinned_from_map(content: &Map<String, Value>) -> Result<Vec<PinnedEmbed>> {
    let entries = match content.get("pinned_embeds") {
        None | Some(Value::Null) => return Ok(Vec::new()),
        Some(Value::Array(entries)) => entries,
        Some(_) => return Err(Error::Protocol),
    };
    entries
        .iter()
        .map(|entry| {
            let embed_id = entry
                .get("embed_id")
                .and_then(Value::as_str)
                .filter(|id| !id.is_empty())
                .ok_or(Error::Protocol)?;
            let version = entry
                .get("version")
                .and_then(safe_int)
                .filter(|v| *v >= 1)
                .ok_or(Error::Protocol)?;
            let previous_version = match entry.get("previous_version") {
                None | Some(Value::Null) => None,
                Some(value) => Some(
                    safe_int(value)
                        .filter(|v| *v >= 1 && *v < version)
                        .ok_or(Error::Protocol)?,
                ),
            };
            let embed_ref = entry
                .get("embed_ref")
                .and_then(Value::as_str)
                .filter(|r| !r.is_empty())
                .map(str::to_owned);
            Ok(PinnedEmbed {
                embed_id: embed_id.to_owned(),
                version,
                embed_ref,
                previous_version,
            })
        })
        .collect()
}

/// Pins of one decrypted `app_skill_use` parent content (TOON or JSON).
///
/// # Errors
/// `Error::Protocol` when the content is not an object or a pin is malformed
/// (missing id, version below 1, `previous_version` not below `version`).
pub fn pinned_embeds(parent_content: &str) -> Result<Vec<PinnedEmbed>> {
    pinned_from_map(&decode_object(parent_content).ok_or(Error::Protocol)?)
}

/// The decrypted `app_skill_use` parent contents of one message (none for a
/// message without a skill use).
#[derive(Clone, Debug, Deserialize)]
pub struct MessageParents {
    pub message_id: String,
    #[serde(default)]
    pub parent_contents: Vec<String>,
}

/// The version of the image a message shows.
#[derive(Clone, Debug, PartialEq, Eq, Serialize)]
pub struct MessageImageVersion {
    pub message_id: String,
    /// Latest pin at or before this message, else 1.
    pub version: i64,
    /// True when this message's own parent pins the image: it renders the
    /// image although the image is not in its parent's `embed_ids`.
    pub pinned_here: bool,
}

/// Walk `messages` (chat order) and give each the version of `embed_id` it
/// shows: the `version` of the latest pin in any message up to and including
/// it, or 1 when there is none (the creating message shows v1).
///
/// # Errors
/// `Error::Protocol` from [`pinned_embeds`] for any malformed parent.
pub fn versions_by_message(
    messages: &[MessageParents],
    embed_id: &str,
) -> Result<Vec<MessageImageVersion>> {
    let mut current = 1;
    let mut out = Vec::with_capacity(messages.len());
    for message in messages {
        let mut pinned_here = false;
        for content in &message.parent_contents {
            for pin in pinned_embeds(content)?
                .into_iter()
                .filter(|pin| pin.embed_id == embed_id)
            {
                current = pin.version;
                pinned_here = true;
            }
        }
        out.push(MessageImageVersion {
            message_id: message.message_id.clone(),
            version: current,
            pinned_here,
        });
    }
    Ok(out)
}

/// Head version of a stored embed row (`version_number`, missing means 1).
///
/// # Errors
/// `Error::Protocol` for a non-object row or a malformed version.
pub fn head_version(head: &Value) -> Result<i64> {
    stored_version(head.as_object().ok_or(Error::Protocol)?)
}

/// True when storing `incoming` (a row from sync or a server read) over the
/// stored child head `stored` would lower its version: the shell then keeps
/// the stored row. Only child embeds (`parent_embed_id` set) advance through
/// local revisions, and a server row can still be at version N while this
/// device already holds the N+1 head it wrote. Messages pinning N+1 would
/// otherwise wait for a head this device had and lost. Equal or higher
/// incoming versions, and every root embed, are written as before.
///
/// # Errors
/// `Error::Protocol` for a non-object row, rows of different embeds or a
/// malformed `version_number`.
pub fn synced_head_regresses(stored: &Value, incoming: &Value) -> Result<bool> {
    let stored = stored.as_object().ok_or(Error::Protocol)?;
    let incoming = incoming.as_object().ok_or(Error::Protocol)?;
    fn id(row: &Map<String, Value>) -> Option<&str> {
        row.get("embed_id").and_then(Value::as_str)
    }
    if let (Some(a), Some(b)) = (id(stored), id(incoming))
        && a != b
    {
        return Err(Error::Protocol);
    }
    let child = stored
        .get("parent_embed_id")
        .and_then(Value::as_str)
        .is_some_and(|parent| !parent.is_empty());
    if !child {
        return Ok(false);
    }
    Ok(stored_version(incoming)? < stored_version(stored)?)
}

/// Content of version `version` of `embed_id`: the head's content when it is
/// the head version, else the `embed_diffs` chain from the latest snapshot at
/// or below `version` up to it (a child's row K is a full snapshot, so that is
/// row K alone). `key` is the key owner's key (the parent's for a child).
///
/// # Errors
/// [`VERSION_UNAVAILABLE`] when `version` is outside `1..=head` or row K is not
/// stored; `Error::Protocol` for rows of another embed or a broken chain;
/// `Error::Crypto` when ciphertext does not open with `key`.
pub fn version_content(
    embed_id: &str,
    version: i64,
    head: &Value,
    rows: &[Value],
    key: &[u8; 32],
) -> Result<Zeroizing<String>> {
    if head.get("embed_id").and_then(Value::as_str) != Some(embed_id) {
        return Err(Error::Protocol);
    }
    let head_version = head_version(head)?;
    if version < 1 || version > head_version {
        return Err(VERSION_UNAVAILABLE);
    }
    if version == head_version {
        let encrypted = head
            .get("encrypted_content")
            .and_then(Value::as_str)
            .filter(|c| !c.is_empty())
            .ok_or(Error::Protocol)?;
        return super::keys::decrypt_text(encrypted, key, None);
    }
    let mut chain: Vec<(i64, &Value)> = Vec::new();
    for row in rows {
        if row
            .get("embed_id")
            .and_then(Value::as_str)
            .is_some_and(|id| id != embed_id)
        {
            return Err(Error::Protocol);
        }
        let row_version = row
            .get("version_number")
            .and_then(safe_int)
            .filter(|v| *v >= 1)
            .ok_or(Error::Protocol)?;
        if row_version <= version {
            chain.push((row_version, row));
        }
    }
    if !chain.iter().any(|(v, _)| *v == version) {
        return Err(VERSION_UNAVAILABLE);
    }
    let has_snapshot = |row: &Value| {
        row.get("encrypted_snapshot")
            .and_then(Value::as_str)
            .is_some_and(|s| !s.is_empty())
    };
    let start = chain
        .iter()
        .filter(|(_, row)| has_snapshot(row))
        .map(|(v, _)| *v)
        .max()
        .unwrap_or(1);
    let rows: Vec<Value> = chain
        .into_iter()
        .filter(|(v, _)| *v >= start)
        .map(|(_, row)| row.clone())
        .collect();
    crate::sdk_embeds::reconstruct_version_rows(&rows, key)
}

/// Turn a fetched bounded-v1 page (`GET /v1/embeds/{id}/versions/{K}`:
/// `{embed_id, version_number: K, rows: [{version_number, encrypted_snapshot?,
/// encrypted_patch?, created_at}]}`) into local `embed_diffs` rows, so a
/// fetched version is cached instead of fetched again. Every ciphertext must
/// open with `key` (the head's key owner: the parent for a child) before
/// anything is stored; rows come back `server_confirmed`.
///
/// # Errors
/// `Error::Protocol` for a page of another embed, `K` outside `1..=head`, no
/// row K, duplicate or out-of-range versions, rows without ciphertext or
/// non-string ciphertext; `Error::Crypto` when a ciphertext does not open.
pub fn cache_version_page(
    embed_id: &str,
    head: &Value,
    page: &Value,
    key: &[u8; 32],
    now_seconds: i64,
) -> Result<Vec<super::history::EncryptedDiffRow>> {
    if head.get("embed_id").and_then(Value::as_str) != Some(embed_id)
        || page.get("embed_id").and_then(Value::as_str) != Some(embed_id)
    {
        return Err(Error::Protocol);
    }
    let head_version = head_version(head)?;
    let page_version = page
        .get("version_number")
        .and_then(safe_int)
        .filter(|v| *v >= 1 && *v <= head_version)
        .ok_or(Error::Protocol)?;
    let rows = page
        .get("rows")
        .and_then(Value::as_array)
        .ok_or(Error::Protocol)?;
    let mut seen = std::collections::HashSet::new();
    let mut cached = Vec::with_capacity(rows.len());
    for row in rows {
        let version = row
            .get("version_number")
            .and_then(safe_int)
            .filter(|v| *v >= 1 && *v <= page_version && seen.insert(*v))
            .ok_or(Error::Protocol)?;
        let cipher = |name: &str| -> Result<Option<String>> {
            match row.get(name) {
                None | Some(Value::Null) => Ok(None),
                Some(Value::String(text)) if !text.is_empty() => {
                    // Authenticate with the owner's key; the plaintext is dropped (zeroized).
                    super::keys::decrypt_text(text, key, None)?;
                    Ok(Some(text.clone()))
                }
                Some(_) => Err(Error::Protocol),
            }
        };
        let (snapshot, patch) = (cipher("encrypted_snapshot")?, cipher("encrypted_patch")?);
        if snapshot.is_none() && patch.is_none() {
            return Err(Error::Protocol);
        }
        let created_at = super::normalize_to_unix_seconds(row.get("created_at"), now_seconds);
        cached.push(
            super::history::EncryptedDiffRow::new(embed_id, version, snapshot, patch, created_at)
                .confirmed(),
        );
    }
    if !seen.contains(&page_version) {
        return Err(Error::Protocol);
    }
    cached.sort_by_key(|row| row.version_number);
    Ok(cached)
}
