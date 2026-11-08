//! README decisions: which stored item is the root README, its text field, the
//! connected-source README entry and the image chunk continuation check. Shared core
//! part of `web_projects`; image source resolution lives in `readme_images.rs`.
//!
//! spec: specifications/surfaces/sdk#sdk.client.thin-platform-boundary
//! Mirrors `projectState/projectReadmePolicy.ts`; fetch, decryption and blob URLs stay in
//! `projectReadme.ts`.

use super::js::{as_str, gt, is_safe_integer, is_str, number_value, prop, req_array, strict_eq, to_number, truthy};
use super::{Fault, Outcome};
use serde_json::{Value, json};

/// Root README file name.
pub(super) const README_PATH: &str = "README.md";
const CONTENT_FIELDS: [&str; 4] = ["code", "content", "markdown", "text"];
const REMOTE_IMAGE_CHUNK_BYTES: f64 = 128.0 * 1024.0;
const MAX_REMOTE_IMAGE_BYTES: f64 = 2.0 * 1024.0 * 1024.0;

/// `item.item_type === "embed" && !item.encrypted.hashed_folder_id`: a stored root embed.
pub(super) fn is_root_embed(item: &Value) -> Result<bool, Fault> {
    Ok(is_str(prop(Some(item), "item_type")?, "embed")
        && !truthy(prop(prop(Some(item), "encrypted")?, "hashed_folder_id")?))
}

/// `storedReadmePath`: whether the item's stored path names the root `README.md`.
fn stored_readme_path(item: &Value) -> Result<bool, Fault> {
    let metadata = prop(Some(item), "metadata")?;
    let path = as_str(prop(metadata, "path")?).unwrap_or("");
    let remote = as_str(prop(metadata, "remote_path")?).unwrap_or("");
    let candidate = if !path.is_empty() {
        path
    } else if !remote.is_empty() {
        remote
    } else {
        let display = prop(Some(item), "displayName")?;
        if !truthy(display) {
            return Ok(false);
        }
        as_str(display).ok_or_else(|| Fault::Malformed("bad_field:displayName".to_owned()))?
    };
    if candidate.is_empty() || candidate.starts_with('/') || candidate.contains('\\') || candidate.contains('/') {
        return Ok(false);
    }
    Ok(candidate.to_lowercase() == README_PATH.to_lowercase())
}

fn upload_time(item: &Value) -> Result<f64, Fault> {
    let value = prop(prop(Some(item), "metadata")?, "readme_uploaded_at_ms")?;
    let n = value.and_then(Value::as_f64).unwrap_or(0.0);
    Ok(if is_safe_integer(value) && n > 0.0 { n } else { 0.0 })
}

fn stamp(item: &Value, name: &str) -> Result<f64, Fault> {
    Ok(to_number(prop(prop(Some(item), "encrypted")?, name)?))
}

/// The JS sort comparator value (`b - a || ...`); a NaN difference falls through, a final NaN is 0.
fn compare(a: &Value, b: &Value) -> Result<f64, Fault> {
    for diff in [
        upload_time(b)? - upload_time(a)?,
        stamp(b, "updated_at")? - stamp(a, "updated_at")?,
        stamp(b, "created_at")? - stamp(a, "created_at")?,
    ] {
        if diff != 0.0 && !diff.is_nan() {
            return Ok(diff);
        }
    }
    Ok(0.0)
}

/// `projectReadmeFind`: index of the newest root README item, or `null`.
pub(super) fn find(input: &Value) -> Outcome {
    let mut best: Option<(usize, &Value)> = None;
    for (index, item) in req_array(input.get("items"), "items")?.iter().enumerate() {
        if !(is_root_embed(item)? && stored_readme_path(item)?) {
            continue;
        }
        // First element of the stable sort: the earliest of the minimal candidates.
        best = match best {
            Some((_, current)) if compare(item, current)? >= 0.0 => best,
            _ => Some((index, item)),
        };
    }
    Ok(json!({ "index": best.map(|(index, _)| index) }))
}

/// `projectReadmeText`: the first string content field of a decrypted README head.
pub(super) fn text(input: &Value) -> Outcome {
    let content = input.get("content");
    for field in CONTENT_FIELDS {
        if let Some(Value::String(text)) = prop(content, field)? {
            return Ok(json!({ "text": text }));
        }
    }
    Ok(json!({ "text": null }))
}

/// `projectReadmeRemotePick`: the root README entry of a listing; `incomplete` when omitted entries hide it.
pub(super) fn remote_pick(input: &Value) -> Outcome {
    for entry in req_array(input.get("entries"), "entries")? {
        if !is_str(prop(Some(entry), "kind")?, "file") {
            continue;
        }
        let path = as_str(prop(Some(entry), "path")?).ok_or_else(|| Fault::Malformed("bad_field:path".to_owned()))?;
        if path.strip_prefix("./").unwrap_or(path).to_lowercase() == README_PATH.to_lowercase() {
            return Ok(json!({ "path": path, "incomplete": false }));
        }
    }
    Ok(json!({ "path": null, "incomplete": gt(input.get("omitted"), Some(&json!(0))) }))
}

/// `projectImageChunkCheck`: whether one image chunk continues the read, and its decoded length.
pub(super) fn image_chunk_check(input: &Value) -> Outcome {
    let offset = input.get("offset");
    let result = input.get("result");
    let size = prop(result, "size_bytes")?;
    let size_n = to_number(size);
    let continued = to_number(offset) > 0.0;
    let refused = !strict_eq(prop(result, "offset")?, offset)
        || size_n <= 0.0
        || size_n > MAX_REMOTE_IMAGE_BYTES
        || (continued
            && (!strict_eq(size, input.get("size"))
                || !strict_eq(prop(result, "mime_type")?, input.get("mime"))
                || !strict_eq(prop(result, "content_hash")?, input.get("hash"))));
    let expected = if refused { 0.0 } else { REMOTE_IMAGE_CHUNK_BYTES.min(size_n - to_number(offset)) };
    // `Math.min` propagates NaN where `f64::min` would drop it.
    let expected = if !refused && (size_n - to_number(offset)).is_nan() { f64::NAN } else { expected };
    Ok(json!({ "ok": !refused, "expectedLength": number_value(expected) }))
}
