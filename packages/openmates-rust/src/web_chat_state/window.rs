//! Bounded decrypted message window pruning and expanded-window preservation.
//!
//! Mirrors `utils/messageWindowPruning.ts` (`pruneDecryptedMessageWindow`,
//! `shouldPreserveExpandedMessageWindow`). The page normalises each message to
//! `{role, status, category, createdAt}` (the `created_at ?? original_message`
//! fallbacks resolved) and applies the returned kept indices to its own array.
//! spec: specifications/architecture/sync/specification.yml#sync.client.shared-rust-policy
use std::collections::HashSet;

use serde_json::{Value, json};

use super::args::{array, maybe_number, opt_number, opt_text, text};
use super::{parse, protocol};

const PAGE_LIMIT: f64 = 30.0;
const TARGET: f64 = 60.0;
const HARD_CAP: f64 = 90.0;
const UNSAFE: [&str; 8] = [
    "sending",
    "waiting_for_upload",
    "waiting_for_internet",
    "processing",
    "streaming",
    "failed",
    "waiting_for_user",
    "delivered",
];

struct Row {
    normal: bool,
    unsafe_status: bool,
}

fn limit(value: &Value, key: &str, default: f64, min: f64) -> Result<usize, String> {
    let raw = maybe_number(value, key)?.unwrap_or(default);
    Ok(raw.floor().max(min) as usize)
}

/// Kept input indices for `{messages: [{role, status, category, createdAt}],
/// checkpoints: [{createdAt, upTo}], pageLimit?, target?, hardCap?}`.
///
/// # Errors
/// Returns the fixed `protocol` code for malformed input.
pub fn prune_json(input: &str) -> Result<String, String> {
    let value = parse(input)?;
    let page_limit = limit(&value, "pageLimit", PAGE_LIMIT, 1.0)?;
    let target = limit(&value, "target", TARGET, page_limit as f64)?;
    let hard_cap = limit(&value, "hardCap", HARD_CAP, target as f64)?;
    // Newest checkpoint (first of equals, like a stable descending sort).
    let mut boundary: Option<f64> = None;
    let mut newest: Option<f64> = None;
    for cp in array(&value, "checkpoints")? {
        let created = opt_number(cp, "createdAt")?.ok_or_else(|| protocol(()))?;
        if newest.is_none_or(|n| created > n) {
            newest = Some(created);
            boundary = opt_number(cp, "upTo")?;
        }
    }
    let mut rows = Vec::new();
    for message in array(&value, "messages")? {
        let created_at = opt_number(message, "createdAt")?;
        let role = text(message, "role")?;
        let category = opt_text(message, "category")?;
        let status = opt_text(message, "status")?;
        let normal = match created_at {
            None => false,
            Some(at) => {
                !(role == "system" && category == Some("compression_summary"))
                    && !boundary.is_some_and(|b| at <= b)
            }
        };
        rows.push(Row {
            normal,
            unsafe_status: status.is_some_and(|s| UNSAFE.contains(&s)),
        });
    }
    let normal: Vec<usize> = (0..rows.len()).filter(|&i| rows[i].normal).collect();
    let kept: Vec<usize> = if normal.len() <= hard_cap {
        (0..rows.len()).collect()
    } else {
        let mut keep: HashSet<usize> = HashSet::new();
        keep.extend(normal.iter().copied().filter(|&i| rows[i].unsafe_status));
        keep.extend(normal.iter().take(page_limit).copied());
        keep.extend(normal.iter().skip(normal.len().saturating_sub(page_limit)));
        for &index in normal.iter().rev() {
            if keep.len() >= target {
                break;
            }
            keep.insert(index);
        }
        (0..rows.len())
            .filter(|&i| !rows[i].normal || keep.contains(&i))
            .collect()
    };
    Ok(json!(kept).to_string())
}

/// Message ids of one `preserve` list; an empty or missing id is `None`.
fn ids<'a>(value: &'a Value, key: &str) -> Result<Vec<Option<&'a str>>, String> {
    array(value, key)?
        .iter()
        .map(|v| match v {
            Value::Null => Ok(None),
            Value::String(s) if s.is_empty() => Ok(None),
            Value::String(s) => Ok(Some(s.as_str())),
            _ => Err(protocol(())),
        })
        .collect()
}

/// `shouldPreserveExpandedMessageWindow` for `{current: [id|null], incoming:
/// [id|null]}`; an empty or missing id is `null`.
///
/// # Errors
/// Returns the fixed `protocol` code for malformed input.
pub fn preserve_json(input: &str) -> Result<String, String> {
    let value = parse(input)?;
    let (current, incoming) = (ids(&value, "current")?, ids(&value, "incoming")?);
    if incoming.is_empty() || current.len() <= incoming.len() {
        return Ok("false".to_string());
    }
    let known: HashSet<&str> = current.iter().flatten().copied().collect();
    let all = incoming
        .iter()
        .all(|id| id.is_some_and(|id| known.contains(id)));
    Ok(json!(all).to_string())
}
