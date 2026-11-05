//! Chat workspace overview order (architecture.sync@2, `sync.overview.priority-order`).
//!
//! Pure and deterministic: every first-party client derives the same order from
//! the same synchronized state. Due-soon items come first, then the last opened
//! chat, then the remaining parent chats by pinned, non-empty draft,
//! `last_edited_overall_timestamp` desc, `updated_at` desc and chat ID asc.
//! Due-soon classification is a port of the web welcome carousel
//! (`frontend/packages/ui/src/services/continueCarouselService.ts`): reminder
//! due / due within 24 h, ongoing saved item, saved item starting within 24 h
//! or started within the last 12 h; ties go to the item nearest to now.
//! Labels and presentation stay in the UI adapters.
#[path = "overview_cards.rs"]
pub mod cards;
#[path = "inspirations.rs"]
pub mod inspirations;
use serde::{Deserialize, Serialize};
use serde_json::Value;
use std::cmp::Ordering;
use std::collections::{BTreeMap, BTreeSet};
use std::sync::OnceLock;

pub const HOUR_MS: i64 = 60 * 60 * 1000;
/// Reminder soon / saved item starting soon (`UPCOMING_WINDOW_MS`).
pub const UPCOMING_WINDOW_MS: i64 = 24 * HOUR_MS;
/// Recently fired reminder / recently started saved item (`RECENT_WINDOW_MS`).
pub const RECENT_WINDOW_MS: i64 = 12 * HOUR_MS;

#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum DueReason {
    ReminderDue,
    ReminderSoon,
    OngoingSavedItem,
    UpcomingSavedItem,
}

impl DueReason {
    fn rank(self) -> u8 {
        match self {
            Self::ReminderDue => 0,
            Self::ReminderSoon => 1,
            Self::OngoingSavedItem => 2,
            Self::UpcomingSavedItem => 3,
        }
    }
}

#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub struct DuePriority {
    pub reason: DueReason,
    /// Unix milliseconds of the trigger, start or end time that classified it.
    pub timestamp_ms: i64,
}

static LOCAL_UTC_OFFSET_MINUTES: std::sync::atomic::AtomicI32 = std::sync::atomic::AtomicI32::new(0);

/// The adapter's local UTC offset (minutes, east positive) for zone-less times.
/// Process-wide because it is a property of the host, not of an account; the
/// default is UTC until an adapter that can read the system zone sets it.
pub fn set_local_utc_offset_minutes(minutes: i32) {
    LOCAL_UTC_OFFSET_MINUTES.store(minutes, std::sync::atomic::Ordering::Relaxed);
}

pub fn local_utc_offset_minutes() -> i32 {
    LOCAL_UTC_OFFSET_MINUTES.load(std::sync::atomic::Ordering::Relaxed)
}

/// One active reminder as returned by the due-soon set (server-decrypted target IDs).
#[derive(Clone, Debug, Default, PartialEq, Eq, Serialize, Deserialize)]
pub struct ReminderInput {
    pub reminder_id: String,
    /// Unix seconds.
    pub trigger_at: i64,
    #[serde(default)]
    pub status: String,
    #[serde(default)]
    pub target_type: String,
    #[serde(default)]
    pub target_chat_id: Option<String>,
    #[serde(default)]
    pub target_embed_id: Option<String>,
}

/// One decrypted saved-item memory entry (`item_value` holds `embed_id` and its times).
#[derive(Clone, Debug, Default, PartialEq)]
pub struct SavedItemInput {
    pub entry_id: String,
    pub app_id: String,
    /// Memory group (`item_type`); selects the saved-item presentation.
    pub item_type: String,
    pub item_value: Value,
}

/// Ordering inputs of one cached chat row.
#[derive(Clone, Debug, Default, PartialEq)]
pub struct ChatRank {
    pub id: String,
    pub pinned: bool,
    pub has_draft: bool,
    pub last_edited_overall_timestamp: f64,
    pub updated_at: f64,
    pub is_sub_chat: bool,
}

impl ChatRank {
    /// Read the ordering inputs from a cached ciphertext chat row.
    pub fn from_row(row: &Value) -> Option<Self> {
        let id = row.get("id")?.as_str().filter(|id| !id.is_empty())?.to_owned();
        let number = |field: &str| row.get(field).and_then(Value::as_f64).filter(|v| v.is_finite()).unwrap_or(0.0);
        Some(Self {
            id,
            pinned: row.get("pinned").and_then(Value::as_bool).unwrap_or(false),
            has_draft: row.get("encrypted_draft_md").and_then(Value::as_str).is_some_and(|v| !v.is_empty()),
            last_edited_overall_timestamp: number("last_edited_overall_timestamp"),
            updated_at: number("updated_at"),
            is_sub_chat: row.get("is_sub_chat").and_then(Value::as_bool).unwrap_or(false)
                || row.get("parent_id").and_then(Value::as_str).is_some_and(|v| !v.is_empty()),
        })
    }
}

#[derive(Clone, Debug, PartialEq, Serialize)]
#[serde(tag = "kind", rename_all = "snake_case")]
pub enum OverviewEntry {
    DueChat { chat_id: String, reminder_id: String, priority: DuePriority },
    DueSavedItem { embed_id: String, entry_id: String, app_id: String, priority: DuePriority },
    LastOpenedChat { chat_id: String },
    Chat { chat_id: String },
}

impl OverviewEntry {
    pub fn chat_id(&self) -> Option<&str> {
        match self {
            Self::DueChat { chat_id, .. } | Self::LastOpenedChat { chat_id } | Self::Chat { chat_id } => Some(chat_id),
            Self::DueSavedItem { .. } => None,
        }
    }
    fn priority(&self) -> Option<&DuePriority> {
        match self {
            Self::DueChat { priority, .. } | Self::DueSavedItem { priority, .. } => Some(priority),
            _ => None,
        }
    }
    fn tie_key(&self) -> (u8, &str) {
        match self {
            Self::DueChat { chat_id, .. } => (0, chat_id),
            Self::DueSavedItem { embed_id, .. } => (1, embed_id),
            Self::LastOpenedChat { chat_id } => (2, chat_id),
            Self::Chat { chat_id } => (3, chat_id),
        }
    }
}

pub struct OverviewInputs<'a> {
    pub chats: &'a [ChatRank],
    pub last_opened_chat_id: Option<&'a str>,
    pub reminders: &'a [ReminderInput],
    pub saved_items: &'a [SavedItemInput],
    pub now_ms: i64,
    /// Local UTC offset; zone-less ISO times and date-only end times are local.
    pub utc_offset_minutes: i32,
    /// `chats list` keeps sub-chats (after their order position); the home overview omits them.
    pub include_sub_chats: bool,
}

/// `buildReminderPriority`.
pub fn reminder_priority(reminder: &ReminderInput, now_ms: i64) -> Option<DuePriority> {
    let trigger_ms = reminder.trigger_at.checked_mul(1000)?;
    if trigger_ms <= 0 {
        return None;
    }
    if trigger_ms <= now_ms {
        if now_ms - trigger_ms > RECENT_WINDOW_MS && reminder.status != "pending" {
            return None;
        }
        return Some(DuePriority { reason: DueReason::ReminderDue, timestamp_ms: trigger_ms });
    }
    (trigger_ms - now_ms <= UPCOMING_WINDOW_MS)
        .then_some(DuePriority { reason: DueReason::ReminderSoon, timestamp_ms: trigger_ms })
}

/// `compareContinuePriority`: rank, then nearest to now.
pub fn compare_priority(a: &DuePriority, b: &DuePriority, now_ms: i64) -> Ordering {
    a.reason.rank().cmp(&b.reason.rank()).then_with(|| {
        let distance = |p: &DuePriority| (p.timestamp_ms - now_ms).unsigned_abs();
        distance(a).cmp(&distance(b))
    })
}

/// Pinned, non-empty draft, `last_edited_overall_timestamp` desc, `updated_at` desc, ID asc.
pub fn compare_chats(a: &ChatRank, b: &ChatRank) -> Ordering {
    b.pinned
        .cmp(&a.pinned)
        .then_with(|| b.has_draft.cmp(&a.has_draft))
        .then_with(|| b.last_edited_overall_timestamp.total_cmp(&a.last_edited_overall_timestamp))
        .then_with(|| b.updated_at.total_cmp(&a.updated_at))
        .then_with(|| a.id.cmp(&b.id))
}

fn iso_pattern() -> &'static regex::Regex {
    static PATTERN: OnceLock<regex::Regex> = OnceLock::new();
    PATTERN.get_or_init(|| {
        regex::Regex::new(
            r"^(\d{4})-(\d{2})-(\d{2})(?:[T ](\d{2}):(\d{2})(?::(\d{2})(?:\.(\d{1,9}))?)?(Z|[+-]\d{2}:?\d{2})?)?$",
        )
        .expect("static ISO pattern")
    })
}

fn days_from_civil(year: i64, month: i64, day: i64) -> i64 {
    let year = if month <= 2 { year - 1 } else { year };
    let era = year.div_euclid(400);
    let year_of_era = year - era * 400;
    let month_index = (month + 9) % 12;
    let day_of_year = (153 * month_index + 2) / 5 + day - 1;
    let day_of_era = year_of_era * 365 + year_of_era / 4 - year_of_era / 100 + day_of_year;
    era * 146_097 + day_of_era - 719_468
}

/// ISO 8601 like JavaScript `new Date(text)`: date-only is UTC, a zone-less
/// date-time is local, an explicit `Z`/offset wins. Other formats are not
/// classified (returns None).
pub fn parse_time(value: Option<&Value>, utc_offset_minutes: i32) -> Option<i64> {
    let text = value?.as_str()?.trim();
    let captures = iso_pattern().captures(text)?;
    let number = |index: usize| captures.get(index).map(|m| m.as_str().parse::<i64>().ok()).unwrap_or(Some(0));
    let (year, month, day) = (number(1)?, number(2)?, number(3)?);
    if !(1..=12).contains(&month) || !(1..=31).contains(&day) {
        return None;
    }
    let (hour, minute, second) = (number(4)?, number(5)?, number(6)?);
    if hour > 23 || minute > 59 || second > 59 {
        return None;
    }
    let millis = captures
        .get(7)
        .map(|m| format!("{:0<3}", m.as_str())[..3].parse::<i64>().unwrap_or(0))
        .unwrap_or(0);
    let local = ((days_from_civil(year, month, day) * 24 + hour) * 60 + minute) * 60_000 + second * 1000 + millis;
    let offset_ms = match captures.get(8).map(|m| m.as_str()) {
        Some("Z") => 0,
        Some(zone) => {
            let digits: String = zone[1..].chars().filter(char::is_ascii_digit).collect();
            let minutes = digits[..2].parse::<i64>().ok()? * 60 + digits[2..].parse::<i64>().ok()?;
            if zone.starts_with('-') { -minutes * 60_000 } else { minutes * 60_000 }
        }
        None if captures.get(4).is_none() => 0,
        None => i64::from(utc_offset_minutes) * 60_000,
    };
    Some(local - offset_ms)
}

/// `parseDateOnlyEnd`: `YYYY-MM-DD` as 23:59:59.999 local time.
fn parse_date_only_end(value: Option<&Value>, utc_offset_minutes: i32) -> Option<i64> {
    let text = value?.as_str()?.trim();
    if text.len() != 10 || captures_date_only(text).is_none() {
        return None;
    }
    parse_time(Some(&Value::String(format!("{text}T23:59:59.999"))), utc_offset_minutes)
}

fn captures_date_only(text: &str) -> Option<()> {
    let bytes = text.as_bytes();
    (bytes[4] == b'-' && bytes[7] == b'-' && text.chars().enumerate().all(|(i, c)| i == 4 || i == 7 || c.is_ascii_digit()))
        .then_some(())
}

/// `getSavedItemTimeWindow`: (start, end) in Unix ms.
pub fn saved_item_window(item: &Value, utc_offset_minutes: i32) -> (Option<i64>, Option<i64>) {
    let first = |fields: &[&str]| fields.iter().find_map(|field| parse_time(item.get(*field), utc_offset_minutes));
    let exact_start = first(&["date_start", "departure", "start_time", "starts_at", "datetime", "appointment_time"]);
    let date_only_start = if exact_start.is_none() { parse_date_only_end(item.get("date"), utc_offset_minutes) } else { None };
    let start = exact_start.or(date_only_start).or_else(|| parse_time(item.get("available_from"), utc_offset_minutes));
    let end = first(&["date_end", "arrival", "end_time", "ends_at", "checkout", "available_until"]);
    (start, end)
}

/// `getSavedItemPriority`.
pub fn saved_item_priority(item: &Value, now_ms: i64, utc_offset_minutes: i32) -> Option<DuePriority> {
    let (start, end) = saved_item_window(item, utc_offset_minutes);
    if let Some(end) = end.filter(|end| *end != 0 && *end >= now_ms)
        && start.is_none_or(|start| start == 0 || start <= now_ms)
    {
        return Some(DuePriority { reason: DueReason::OngoingSavedItem, timestamp_ms: end });
    }
    let start = start.filter(|start| *start != 0)?;
    let started_recently = start <= now_ms && now_ms - start <= RECENT_WINDOW_MS;
    let starts_soon = start > now_ms && start - now_ms <= UPCOMING_WINDOW_MS;
    (started_recently || starts_soon).then_some(DuePriority { reason: DueReason::UpcomingSavedItem, timestamp_ms: start })
}

fn best_reminders<'a>(
    reminders: &'a [ReminderInput],
    target: impl Fn(&ReminderInput) -> Option<&str>,
    now_ms: i64,
) -> BTreeMap<String, (&'a ReminderInput, DuePriority)> {
    let mut best: BTreeMap<String, (&ReminderInput, DuePriority)> = BTreeMap::new();
    for reminder in reminders {
        let Some(id) = target(reminder).map(str::trim).filter(|id| !id.is_empty()) else { continue };
        let Some(priority) = reminder_priority(reminder, now_ms) else { continue };
        let replace = best
            .get(id)
            .is_none_or(|(current, existing)| match compare_priority(&priority, existing, now_ms) {
                Ordering::Less => true,
                Ordering::Equal => reminder.reminder_id < current.reminder_id,
                Ordering::Greater => false,
            });
        if replace {
            best.insert(id.to_owned(), (reminder, priority));
        }
    }
    best
}

/// The ordered overview: due-soon items, the last opened chat, then chats.
pub fn build_overview(inputs: &OverviewInputs<'_>) -> Vec<OverviewEntry> {
    let now = inputs.now_ms;
    let by_id: BTreeMap<&str, &ChatRank> = inputs.chats.iter().map(|chat| (chat.id.as_str(), chat)).collect();
    let mut due: Vec<OverviewEntry> = vec![];
    let chat_reminders = best_reminders(inputs.reminders, |r| r.target_chat_id.as_deref(), now);
    for (chat_id, (reminder, priority)) in &chat_reminders {
        if by_id.get(chat_id.as_str()).is_some_and(|chat| !chat.is_sub_chat) {
            due.push(OverviewEntry::DueChat {
                chat_id: chat_id.clone(),
                reminder_id: reminder.reminder_id.clone(),
                priority: *priority,
            });
        }
    }
    let embed_reminders = best_reminders(inputs.reminders, |r| r.target_embed_id.as_deref(), now);
    let mut seen_embeds = BTreeSet::new();
    let mut saved: Vec<OverviewEntry> = vec![];
    for item in inputs.saved_items {
        let Some(embed_id) = item.item_value.get("embed_id").and_then(Value::as_str).map(str::trim).filter(|id| !id.is_empty()) else {
            continue;
        };
        let (start, end) = saved_item_window(&item.item_value, inputs.utc_offset_minutes);
        let priority = if start.is_some_and(|v| v != 0) || end.is_some_and(|v| v != 0) {
            saved_item_priority(&item.item_value, now, inputs.utc_offset_minutes)
        } else {
            embed_reminders.get(embed_id).map(|(_, priority)| *priority)
        };
        if let Some(priority) = priority {
            saved.push(OverviewEntry::DueSavedItem {
                embed_id: embed_id.to_owned(),
                entry_id: item.entry_id.clone(),
                app_id: item.app_id.clone(),
                priority,
            });
        }
    }
    let rank = |entry: &OverviewEntry| entry.priority().copied();
    saved.sort_by(|a, b| {
        compare_priority(&rank(a).unwrap(), &rank(b).unwrap(), now).then_with(|| a.tie_key().cmp(&b.tie_key()))
    });
    for entry in saved {
        if let OverviewEntry::DueSavedItem { embed_id, .. } = &entry
            && seen_embeds.insert(embed_id.clone())
        {
            due.push(entry);
        }
    }
    due.sort_by(|a, b| {
        compare_priority(&rank(a).unwrap(), &rank(b).unwrap(), now).then_with(|| a.tie_key().cmp(&b.tie_key()))
    });
    let mut listed: BTreeSet<String> = due.iter().filter_map(OverviewEntry::chat_id).map(str::to_owned).collect();
    let mut entries = due;
    if let Some(opened) = inputs.last_opened_chat_id
        && let Some(chat) = by_id.get(opened)
        && (inputs.include_sub_chats || !chat.is_sub_chat)
        && listed.insert(chat.id.clone())
    {
        entries.push(OverviewEntry::LastOpenedChat { chat_id: chat.id.clone() });
    }
    let mut rest: Vec<&ChatRank> = inputs
        .chats
        .iter()
        .filter(|chat| (inputs.include_sub_chats || !chat.is_sub_chat) && !listed.contains(&chat.id))
        .collect();
    rest.sort_by(|a, b| compare_chats(a, b));
    let mut emitted = BTreeSet::new();
    for chat in rest {
        if emitted.insert(chat.id.as_str()) {
            entries.push(OverviewEntry::Chat { chat_id: chat.id.clone() });
        }
    }
    entries
}

/// Chat IDs of `build_overview` in order (due chats, last opened, the rest).
pub fn ordered_chat_ids(inputs: &OverviewInputs<'_>) -> Vec<String> {
    build_overview(inputs).iter().filter_map(OverviewEntry::chat_id).map(str::to_owned).collect()
}

#[cfg(test)]
#[path = "overview_tests.rs"]
mod tests;
