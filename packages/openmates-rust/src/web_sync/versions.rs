//! Version-wins plans of inbound chat updates (shared Rust core Worker `sync` unit).
//!
//! Mirrors `chatSyncVersionPlans.ts`: which encrypted-metadata revision and
//! version counters an `encrypted_chat_metadata` broadcast may apply, whether a
//! `draft_deleted` frame is versionless/stale, and the `messages_v` advance of
//! the confirmation and CoreSync content paths. Only version numbers cross the
//! boundary; the page copies the admitted values itself. Proven by
//! `versions_vectors.json`. Spec: `sync.client.shared-rust-policy`.
use serde_json::{Value, json};

use super::{PROTOCOL, field, nullish, num, number, or, parse};

/// The version counters an `encrypted_chat_metadata` broadcast can carry, in apply order.
const VERSION_KEYS: [&str; 4] = ["messages_v", "metadata_v", "title_v", "draft_v"];

/// `Math.max` over JS numbers: any `NaN` operand makes the result `NaN`.
fn js_max(values: impl IntoIterator<Item = f64>) -> f64 {
    values.into_iter().fold(f64::NEG_INFINITY, |max, v| {
        if max.is_nan() || v.is_nan() {
            f64::NAN
        } else {
            max.max(v)
        }
    })
}

/// `(value || 0)` as a number.
fn or_zero(value: Option<&Value>) -> f64 {
    or(value).map_or(0.0, |v| num(Some(v)))
}

/// `encrypted_chat_metadata` version plan. Input `{local: {messages_v?, metadata_v?,
/// title_v?, draft_v?}, versions?: object | null}` (absent = `undefined`); output
/// `{"acceptsRevision": bool, "apply": [key...]}`.
///
/// `acceptsRevision` is `metadata_v === undefined || metadata_v >= (local.metadata_v
/// || local.title_v || 0)`: an older metadata revision must not overwrite the
/// title, summary or follow-up of a newer one. `apply` names the version keys the
/// page copies from `versions` (raw values, `null` included): `messages_v` and
/// `draft_v` only when strictly ahead, `metadata_v` (plus a defined `title_v`) when
/// the revision is accepted, otherwise `title_v` only when strictly ahead.
///
/// # Errors
/// `protocol` when `local` is not an object or `versions` is neither absent,
/// `null` nor an object.
pub fn metadata_versions_json(input: &str) -> Result<String, String> {
    let input = parse(input)?;
    let local = field(&input, "local")
        .filter(|c| c.is_object())
        .ok_or_else(|| PROTOCOL.to_string())?;
    let versions = match nullish(field(&input, "versions")) {
        None => None,
        Some(v) if v.is_object() => Some(v),
        Some(_) => return Err(PROTOCOL.to_string()),
    };
    let incoming_metadata = versions.and_then(|v| field(v, "metadata_v"));
    let local_metadata = or(field(local, "metadata_v"))
        .or_else(|| or(field(local, "title_v")))
        .map_or(0.0, |v| num(Some(v)));
    let accepts = incoming_metadata.is_none_or(|v| num(Some(v)) >= local_metadata);
    let mut apply = Vec::new();
    if let Some(versions) = versions {
        let ahead = |key: &str| {
            field(versions, key).is_some_and(|v| num(Some(v)) > or_zero(field(local, key)))
        };
        let defined = |key: &str| field(versions, key).is_some();
        if ahead(VERSION_KEYS[0]) {
            apply.push(VERSION_KEYS[0]);
        }
        if defined(VERSION_KEYS[1]) && accepts {
            apply.push(VERSION_KEYS[1]);
            if defined(VERSION_KEYS[2]) {
                apply.push(VERSION_KEYS[2]);
            }
        } else if ahead(VERSION_KEYS[2]) {
            apply.push(VERSION_KEYS[2]);
        }
        if ahead(VERSION_KEYS[3]) {
            apply.push(VERSION_KEYS[3]);
        }
    }
    Ok(json!({"acceptsRevision": accepts, "apply": apply}).to_string())
}

/// `draft_deleted` plan against an existing local chat. Input `{local: {draft_v?,
/// cleared_draft_v?}, draftV?}`; output `{"ignore": null | "versionless" | "stale",
/// "clearedDraftV": number | null}`.
///
/// The local draft version is `Math.max(draft_v ?? 0, cleared_draft_v ?? 0)`: a
/// versionless deletion never clears a versioned local draft, and a deletion
/// older than it is stale. An admitted deletion fences later stale draft frames
/// with `clearedDraftV = Math.max(cleared_draft_v ?? 0, draftV ?? draft_v ?? 0)`.
///
/// # Errors
/// `protocol` when `local` is not an object.
pub fn draft_deleted_json(input: &str) -> Result<String, String> {
    let input = parse(input)?;
    let local = field(&input, "local")
        .filter(|c| c.is_object())
        .ok_or_else(|| PROTOCOL.to_string())?;
    let nullish_num = |value: Option<&Value>| nullish(value).map_or(0.0, |v| num(Some(v)));
    let draft_v = field(local, "draft_v");
    let cleared_v = nullish_num(field(local, "cleared_draft_v"));
    let local_version = js_max([nullish_num(draft_v), cleared_v]);
    let incoming = field(&input, "draftV");
    let ignore = match incoming {
        None if local_version > 0.0 => Some("versionless"),
        Some(v) if local_version > num(Some(v)) => Some("stale"),
        _ => None,
    };
    let cleared = ignore.is_none().then(|| {
        js_max([
            cleared_v,
            nullish_num(nullish(incoming).or(nullish(draft_v))),
        ])
    });
    Ok(json!({"ignore": ignore, "clearedDraftV": cleared.map(number)}).to_string())
}

/// `messages_v` advance: `Math.max(local || 0, ...candidates)`. Input `{local?,
/// candidates: [...]}`; output `{"messagesV": number | null, "advanced": bool}`
/// (`advanced`: strictly ahead of `local || 0`). Versions only move forward, so
/// a late confirmation or content batch never rewinds a newer local counter.
///
/// # Errors
/// `protocol` when `candidates` is not an array.
pub fn messages_version_json(input: &str) -> Result<String, String> {
    let input = parse(input)?;
    let candidates = field(&input, "candidates")
        .and_then(Value::as_array)
        .ok_or_else(|| PROTOCOL.to_string())?;
    let base = or_zero(field(&input, "local"));
    let next = js_max(std::iter::once(base).chain(candidates.iter().map(|v| num(Some(v)))));
    Ok(json!({"messagesV": number(next), "advanced": next > base}).to_string())
}

#[cfg(test)]
#[path = "versions_tests.rs"]
mod tests;
