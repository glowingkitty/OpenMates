//! Chat-list ordering and time grouping.
//!
//! Mirrors `sortChats` (pinned, then non-empty draft, then newest
//! `last_edited_overall_timestamp`, then the server order, then newest
//! `updated_at`) and `groupChats` / `chatTimeGroupKey` (explicit `group_key`
//! first, otherwise a calendar-day bucket). The page normalises each chat to the
//! small records below (JS truthiness, `|| 0` fallbacks, local calendar date of
//! the timestamp) and gets back index lists, so duplicate chat ids and the
//! caller's object identity are preserved. The sort is stable, like JS
//! `Array.prototype.sort`, so ties keep their input order.
//! spec: specifications/architecture/sync/specification.yml#sync.client.shared-rust-policy
use std::cmp::Ordering;
use std::collections::HashMap;

use serde_json::{json, Value};

use super::{parse, protocol};

/// One chat as `sortChats` reads it, already normalised by the page.
struct SortEntry {
    pinned: bool,
    draft: bool,
    timestamp: f64,
    updated: f64,
    server_index: Option<usize>,
}

fn number(value: &Value) -> Result<f64, String> {
    value.as_f64().ok_or_else(|| protocol(()))
}

fn flag(value: &Value) -> Result<bool, String> {
    value.as_bool().ok_or_else(|| protocol(()))
}

fn array<'a>(value: &'a Value, key: &str) -> Result<&'a Vec<Value>, String> {
    value
        .get(key)
        .and_then(Value::as_array)
        .ok_or_else(|| protocol(()))
}

/// JS comparator `b - a` of two finite numbers as an [`Ordering`].
fn newest_first(a: f64, b: f64) -> Ordering {
    b.partial_cmp(&a).unwrap_or(Ordering::Equal)
}

fn compare(a: &SortEntry, b: &SortEntry) -> Ordering {
    // Pinned chats first, then chats with a non-empty draft (within each class).
    b.pinned
        .cmp(&a.pinned)
        .then_with(|| b.draft.cmp(&a.draft))
        .then_with(|| newest_first(a.timestamp, b.timestamp))
        .then_with(|| match (a.server_index, b.server_index) {
            (Some(x), Some(y)) => x.cmp(&y),
            (Some(_), None) => Ordering::Less,
            (None, Some(_)) => Ordering::Greater,
            (None, None) => newest_first(a.updated, b.updated),
        })
}

/// Sort plan for `{chats: [{id, pinned, draft, timestamp, updated}], serverOrder: [id]}`:
/// the input indices in display order (a stable sort, so equal chats keep their
/// input order).
///
/// # Errors
/// Returns the fixed `protocol` code for malformed input.
pub fn sort_json(input: &str) -> Result<String, String> {
    let value = parse(input)?;
    let mut server_index: HashMap<&str, usize> = HashMap::new();
    for (index, id) in array(&value, "serverOrder")?.iter().enumerate() {
        // `indexOf` finds the first occurrence.
        server_index
            .entry(id.as_str().ok_or_else(|| protocol(()))?)
            .or_insert(index);
    }
    let mut entries = Vec::new();
    for chat in array(&value, "chats")? {
        let id = chat
            .get("id")
            .and_then(Value::as_str)
            .ok_or_else(|| protocol(()))?;
        entries.push(SortEntry {
            pinned: flag(&chat["pinned"])?,
            draft: flag(&chat["draft"])?,
            timestamp: number(&chat["timestamp"])?,
            updated: number(&chat["updated"])?,
            server_index: server_index.get(id).copied(),
        });
    }
    let mut order: Vec<usize> = (0..entries.len()).collect();
    order.sort_by(|&a, &b| compare(&entries[a], &entries[b]));
    Ok(json!(order).to_string())
}

/// Days since 1970-01-01 of a proleptic Gregorian calendar date (the
/// `Date.UTC(y, m, d) / 86_400_000` of `chatTimeGroupKey`).
fn day_number(year: i64, month: i64, day: i64) -> i64 {
    let y = if month <= 2 { year - 1 } else { year };
    let era = y.div_euclid(400);
    let year_of_era = y.rem_euclid(400);
    let shifted_month = (month + 9) % 12;
    let day_of_year = (153 * shifted_month + 2) / 5 + day - 1;
    let day_of_era = year_of_era * 365 + year_of_era / 4 - year_of_era / 100 + day_of_year;
    era * 146_097 + day_of_era - 719_468
}

fn date(value: &Value) -> Result<(i64, i64, i64), String> {
    let parts = value
        .as_array()
        .filter(|p| p.len() == 3)
        .ok_or_else(|| protocol(()))?;
    let part = |i: usize| parts[i].as_i64().ok_or_else(|| protocol(()));
    let (year, month, day) = (part(0)?, part(1)?, part(2)?);
    if !(1..=12).contains(&month) || !(1..=31).contains(&day) {
        return Err(protocol(()));
    }
    Ok((year, month, day))
}

/// Bucket key of a local calendar `day` seen from `today` (`chatTimeGroupKey`).
/// A future day counts as `previous_7_days`, like the TS day-difference compare.
fn time_group_key(today: (i64, i64, i64), day: (i64, i64, i64)) -> String {
    let days = day_number(today.0, today.1, today.2) - day_number(day.0, day.1, day.2);
    match days {
        0 => "today".to_string(),
        1 => "yesterday".to_string(),
        d if d < 7 => "previous_7_days".to_string(),
        d if d < 30 => "previous_30_days".to_string(),
        _ => format!("month_{}_{}", day.0, day.1),
    }
}

/// Group plan for `{chats: [{group, day}], today: [y, m, d]}`: `[key, [input
/// indices]]` pairs in first-seen key order. `group` is the explicit
/// `group_key` (or null); `day` is the local calendar date of the chat's
/// timestamp, or null when the timestamp is absent or invalid (`today`).
///
/// # Errors
/// Returns the fixed `protocol` code for malformed input.
pub fn group_json(input: &str) -> Result<String, String> {
    let value = parse(input)?;
    let today = date(value.get("today").ok_or_else(|| protocol(()))?)?;
    let mut groups: Vec<(String, Vec<usize>)> = Vec::new();
    for (index, chat) in array(&value, "chats")?.iter().enumerate() {
        let key = match chat.get("group") {
            Some(Value::String(group)) => group.clone(),
            Some(Value::Null) => match chat.get("day") {
                Some(Value::Null) => "today".to_string(),
                Some(day) => time_group_key(today, date(day)?),
                None => return Err(protocol(())),
            },
            _ => return Err(protocol(())),
        };
        match groups.iter_mut().find(|(existing, _)| *existing == key) {
            Some((_, indices)) => indices.push(index),
            None => groups.push((key, vec![index])),
        }
    }
    Ok(json!(groups).to_string())
}
