//! Presentation facts of the "Continue where you left off" home entries.
//!
//! Ports `continueCarouselService.ts` (labels, saved-item presentation) on top
//! of the pure overview order. Pure and deterministic; terminals and other
//! adapters only render the returned strings. English wording is the web's.
use super::{DuePriority, DueReason, HOUR_MS, OverviewEntry, SavedItemInput, local_utc_offset_minutes, parse_time};
use serde_json::Value;

const MINUTE_MS: i64 = 60_000;
const DAY_MS: i64 = 24 * HOUR_MS;

/// One home carousel entry in display order.
#[derive(Clone, Debug, PartialEq)]
pub enum HomeEntry {
    /// A chat; `footer` is the due-soon label (reminder), `None` for plain chats.
    Chat { chat_id: String, footer: Option<String> },
    SavedItem { embed_id: String, title: String, summary: Option<String>, category: Option<String>, footer: String },
}

/// `formatRelativeLabel` (JavaScript `Math.round` equals half-up for positives).
pub fn relative_label(prefix: &str, timestamp_ms: i64, now_ms: i64) -> String {
    let diff = timestamp_ms - now_ms;
    let minutes = (((diff.unsigned_abs() as f64) / MINUTE_MS as f64).round() as i64).max(1);
    let (value, unit) = if minutes < 60 {
        (minutes, "m")
    } else {
        let hours = (((minutes as f64) / 60.0).round() as i64).max(1);
        if hours < 24 { (hours, "h") } else { ((((hours as f64) / 24.0).round() as i64).max(1), "d") }
    };
    if diff >= 0 { format!("{prefix} in {value}{unit}") } else { format!("{prefix} {value}{unit} ago") }
}

fn date_only_label(prefix: &str, timestamp_ms: i64, now_ms: i64, offset_minutes: i32) -> String {
    let local = |ms: i64| (ms + i64::from(offset_minutes) * MINUTE_MS).div_euclid(DAY_MS);
    match local(timestamp_ms) - local(now_ms) {
        0 => format!("{prefix} today"),
        1 => format!("{prefix} tomorrow"),
        -1 => format!("{prefix} yesterday"),
        days if days > 0 => format!("{prefix} in {days}d"),
        days => format!("{prefix} {}d ago", days.abs()),
    }
}

fn text(value: &Value, field: &str) -> String {
    value.get(field).and_then(Value::as_str).map(str::trim).unwrap_or_default().to_owned()
}

fn joined(parts: &[String], separator: &str) -> Option<String> {
    let parts: Vec<&str> = parts.iter().map(String::as_str).filter(|part| !part.is_empty()).collect();
    (!parts.is_empty()).then(|| parts.join(separator))
}

/// `getSavedItemPresentation`: (item label, category, summary).
pub fn saved_item_presentation(app_id: &str, item_type: &str, item: &Value) -> (&'static str, Option<&'static str>, Option<String>) {
    if app_id == "travel" || item_type.contains("connection") {
        return ("Trip", Some("travel"), joined(&[text(item, "origin"), text(item, "destination"), text(item, "notes")], " · "));
    }
    if app_id == "events" || item_type.contains("event") {
        return ("Event", Some("events"), joined(&[text(item, "location"), text(item, "provider")], " · "));
    }
    if app_id == "health" {
        return ("Appointment", Some("health"), Some(text(item, "notes")).filter(|notes| !notes.is_empty()));
    }
    if app_id == "home" {
        return ("Listing", Some("home"), joined(&[text(item, "location"), text(item, "notes")], " · "));
    }
    ("Saved item", None, Some(text(item, "notes")).filter(|notes| !notes.is_empty()))
}

/// True when the item's start comes only from a `YYYY-MM-DD` `date` field.
fn start_is_date_only(item: &Value, offset_minutes: i32) -> bool {
    let exact = ["date_start", "departure", "start_time", "starts_at", "datetime", "appointment_time"]
        .iter()
        .any(|field| parse_time(item.get(*field), offset_minutes).is_some());
    !exact && item.get("date").and_then(Value::as_str).is_some_and(|date| date.trim().len() == 10)
}

/// The footer label of one due-soon priority.
pub fn priority_label(priority: &DuePriority, item_label: Option<&str>, item: Option<&Value>, now_ms: i64, offset_minutes: i32) -> String {
    match (priority.reason, item_label) {
        (DueReason::OngoingSavedItem, Some(label)) => format!("{label} ongoing"),
        (DueReason::UpcomingSavedItem, Some(label)) => {
            if item.is_some_and(|item| start_is_date_only(item, offset_minutes)) {
                date_only_label(label, priority.timestamp_ms, now_ms, offset_minutes)
            } else {
                relative_label(label, priority.timestamp_ms, now_ms)
            }
        }
        _ => relative_label("Reminder", priority.timestamp_ms, now_ms),
    }
}

/// Resolve overview entries into presentable home entries (local zone offset).
pub fn home_entries(entries: &[OverviewEntry], saved: &[SavedItemInput], now_ms: i64) -> Vec<HomeEntry> {
    let offset = local_utc_offset_minutes();
    entries
        .iter()
        .filter_map(|entry| match entry {
            OverviewEntry::DueChat { chat_id, priority, .. } => Some(HomeEntry::Chat {
                chat_id: chat_id.clone(),
                footer: Some(priority_label(priority, None, None, now_ms, offset)),
            }),
            OverviewEntry::LastOpenedChat { chat_id } | OverviewEntry::Chat { chat_id } => {
                Some(HomeEntry::Chat { chat_id: chat_id.clone(), footer: None })
            }
            OverviewEntry::DueSavedItem { embed_id, entry_id, app_id, priority } => {
                let input = saved.iter().find(|input| &input.entry_id == entry_id)?;
                let (label, category, summary) = saved_item_presentation(app_id, &input.item_type, &input.item_value);
                let title = Some(text(&input.item_value, "title"))
                    .filter(|t| !t.is_empty())
                    .or_else(|| Some(text(&input.item_value, "name")).filter(|t| !t.is_empty()))
                    .unwrap_or_else(|| label.to_owned());
                Some(HomeEntry::SavedItem {
                    embed_id: embed_id.clone(),
                    title,
                    summary,
                    category: category.map(str::to_owned),
                    footer: format!("{} · Saved", priority_label(priority, Some(label), Some(&input.item_value), now_ms, offset)),
                })
            }
        })
        .collect()
}

#[cfg(test)]
#[path = "overview_cards_tests.rs"]
mod tests;
