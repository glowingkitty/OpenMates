//! Selects the newest usable personalized Daily Inspiration snapshot for the
//! start row. Mirrors the six-card contract in the web dailyInspirationStore
//! and the existing native offline expiry rules. See feature.daily-inspiration.

use serde_json::{Value, json};
use std::collections::HashSet;

#[cfg(test)]
#[path = "inspiration_snapshot_tests.rs"]
mod tests;

const SNAPSHOT_TTL_SECONDS: f64 = 72.0 * 60.0 * 60.0;
const MAX_PAYLOAD_BYTES: usize = 2 * 1024 * 1024;
const MAX_STORED_RECORDS: usize = 30;
const SET_SIZE: usize = 6;
const RETIRED_GUEST_IDS: [&str; 6] = [
    "openmates-intro",
    "openmates-actionable-events",
    "openmates-privacy-safety",
    "openmates-mates-focus",
    "openmates-provider-cross-platform",
    "openmates-signup-cta",
];

/// Returns a normalized JSON snapshot of three videos and three articles.
/// Input must already belong to the caller's authenticated cache scope.
/// Malformed, expired, future, incomplete or ambiguous sets are unavailable.
/// The returned snapshot retains the selected rows' metadata for rendering.
pub fn select_personalized_snapshot(payload: &[u8], now_seconds: f64) -> Option<Vec<u8>> {
    if payload.len() > MAX_PAYLOAD_BYTES || !now_seconds.is_finite() {
        return None;
    }
    let document: Value = serde_json::from_slice(payload).ok()?;
    let records = document.get("inspirations")?.as_array()?;
    if records.len() > MAX_STORED_RECORDS {
        return None;
    }
    let mut candidates: Vec<_> = records
        .iter()
        .filter_map(|record| usable_record(record, now_seconds))
        .collect();
    candidates.sort_by(|left, right| right.0.total_cmp(&left.0).then(left.1.cmp(right.1)));
    candidates.truncate(SET_SIZE);

    let distinct_ids: HashSet<_> = candidates.iter().map(|candidate| candidate.1).collect();
    let videos = candidates
        .iter()
        .filter(|candidate| candidate.2["content_type"] == "video")
        .count();
    if distinct_ids.len() != SET_SIZE || videos != 3 {
        return None;
    }
    let selected: Vec<_> = candidates.into_iter().map(|(_, _, row)| row).collect();
    serde_json::to_vec(&json!({ "inspirations": selected })).ok()
}

fn usable_record(record: &Value, now_seconds: f64) -> Option<(f64, &str, &Value)> {
    let generated_at = record.get("generated_at")?.as_f64()?;
    if generated_at > now_seconds || now_seconds - generated_at >= SNAPSHOT_TTL_SECONDS {
        return None;
    }
    let id = record.get("inspiration_id")?.as_str()?;
    let phrase = record.get("phrase")?.as_str()?;
    let category = record.get("category")?.as_str()?;
    let content_type = record.get("content_type")?.as_str()?;
    let retired_guest = record
        .pointer("/feature/feature_id")
        .and_then(Value::as_str)
        .is_some_and(|feature_id| RETIRED_GUEST_IDS.contains(&feature_id));
    if id.trim().is_empty()
        || phrase.trim().is_empty()
        || category.trim().is_empty()
        || !matches!(content_type, "video" | "wiki")
        || RETIRED_GUEST_IDS.contains(&id)
        || retired_guest
    {
        return None;
    }
    Some((generated_at, id, record))
}
