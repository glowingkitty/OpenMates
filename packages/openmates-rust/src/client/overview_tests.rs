//! Overview order and due-soon classification (port of continueCarouselService.ts).
use super::*;
use serde_json::json;

const NOW: i64 = 1_800_000_000_000; // 2027-01-15T08:00:00Z

fn reminder(id: &str, trigger_ms: i64, status: &str, chat: Option<&str>, embed: Option<&str>) -> ReminderInput {
    ReminderInput {
        reminder_id: id.into(),
        trigger_at: trigger_ms / 1000,
        status: status.into(),
        target_type: if embed.is_some() { "embed".into() } else { "existing_chat".into() },
        target_chat_id: chat.map(str::to_owned),
        target_embed_id: embed.map(str::to_owned),
    }
}

fn chat(id: &str, pinned: bool, draft: bool, edited: f64, updated: f64) -> ChatRank {
    ChatRank { id: id.into(), pinned, has_draft: draft, last_edited_overall_timestamp: edited, updated_at: updated, is_sub_chat: false }
}

fn iso(ms: i64) -> String {
    let seconds = ms.div_euclid(1000);
    let days = seconds.div_euclid(86_400);
    let secs = seconds.rem_euclid(86_400);
    // civil_from_days (inverse of days_from_civil) for test fixtures only.
    let z = days + 719_468;
    let era = z.div_euclid(146_097);
    let doe = z - era * 146_097;
    let yoe = (doe - doe / 1460 + doe / 36_524 - doe / 146_096) / 365;
    let doy = doe - (365 * yoe + yoe / 4 - yoe / 100);
    let mp = (5 * doy + 2) / 153;
    let day = doy - (153 * mp + 2) / 5 + 1;
    let month = if mp < 10 { mp + 3 } else { mp - 9 };
    let year = yoe + era * 400 + i64::from(month <= 2);
    format!("{year:04}-{month:02}-{day:02}T{:02}:{:02}:{:02}Z", secs / 3600, secs % 3600 / 60, secs % 60)
}

// contract-test: direct surface=sdks.rust assertions=sync.overview.priority-order
#[test]
fn reminder_windows_match_the_web_carousel() {
    let p = |trigger: i64, status: &str| reminder_priority(&reminder("r", trigger, status, None, None), NOW).map(|p| p.reason);
    assert_eq!(p(NOW - HOUR_MS, "fired"), Some(DueReason::ReminderDue));
    assert_eq!(p(NOW - 13 * HOUR_MS, "fired"), None, "fired more than 12 h ago");
    assert_eq!(p(NOW - 13 * HOUR_MS, "pending"), Some(DueReason::ReminderDue), "still pending");
    assert_eq!(p(NOW + 23 * HOUR_MS, "pending"), Some(DueReason::ReminderSoon));
    assert_eq!(p(NOW + 25 * HOUR_MS, "pending"), None);
    assert_eq!(p(0, "pending"), None);
}

// contract-test: direct surface=sdks.rust assertions=sync.overview.priority-order
#[test]
fn saved_item_windows_match_the_web_carousel() {
    let p = |value: serde_json::Value| saved_item_priority(&value, NOW, 0).map(|p| (p.reason, p.timestamp_ms));
    let start = NOW + 3 * HOUR_MS;
    assert_eq!(p(json!({"date_start": iso(start)})), Some((DueReason::UpcomingSavedItem, start)));
    assert_eq!(p(json!({"appointment_time": iso(NOW - 11 * HOUR_MS)})).map(|v| v.0), Some(DueReason::UpcomingSavedItem));
    assert_eq!(p(json!({"departure": iso(NOW - 13 * HOUR_MS)})), None);
    assert_eq!(p(json!({"starts_at": iso(NOW + 25 * HOUR_MS)})), None);
    let end = NOW + 2 * HOUR_MS;
    assert_eq!(p(json!({"date_start": iso(NOW - 2 * HOUR_MS), "date_end": iso(end)})), Some((DueReason::OngoingSavedItem, end)));
    assert_eq!(p(json!({"checkout": iso(end)})).map(|v| v.0), Some(DueReason::OngoingSavedItem));
    assert_eq!(p(json!({"title": "no time"})), None);
}

#[test]
fn iso_parsing_follows_javascript_date_rules() {
    assert_eq!(parse_time(Some(&json!("2027-01-15T08:00:00Z")), 120), Some(NOW));
    assert_eq!(parse_time(Some(&json!("2027-01-15T10:00:00+02:00")), 0), Some(NOW));
    assert_eq!(parse_time(Some(&json!("2027-01-15T09:00:00")), 60), Some(NOW), "zone-less is local");
    assert_eq!(parse_time(Some(&json!("2027-01-15")), 600), Some(NOW - 8 * HOUR_MS), "date-only is UTC");
    assert_eq!(parse_time(Some(&json!("2027-01-15T08:00:00.5Z")), 0), Some(NOW + 500));
    for invalid in ["tomorrow", "2027-13-01", "", "2027-01-15T25:00:00Z"] {
        assert_eq!(parse_time(Some(&json!(invalid)), 0), None, "{invalid}");
    }
    // `date` alone is a date-only start at 23:59:59.999 local time.
    let (start, _) = saved_item_window(&json!({"date": "2027-01-15"}), 60);
    assert_eq!(start, Some(NOW + 15 * HOUR_MS + 59 * 60_000 + 59_999 - HOUR_MS));
}

// contract-test: direct surface=sdks.rust assertions=sync.overview.priority-order
#[test]
fn priority_ranks_then_nearest_to_now() {
    let due = DuePriority { reason: DueReason::ReminderDue, timestamp_ms: NOW - 5 * HOUR_MS };
    let soon = DuePriority { reason: DueReason::ReminderSoon, timestamp_ms: NOW + HOUR_MS };
    let ongoing = DuePriority { reason: DueReason::OngoingSavedItem, timestamp_ms: NOW + HOUR_MS };
    let upcoming_near = DuePriority { reason: DueReason::UpcomingSavedItem, timestamp_ms: NOW + HOUR_MS };
    let upcoming_far = DuePriority { reason: DueReason::UpcomingSavedItem, timestamp_ms: NOW + 9 * HOUR_MS };
    let mut all = [upcoming_far, ongoing, soon, upcoming_near, due];
    all.sort_by(|a, b| compare_priority(a, b, NOW));
    assert_eq!(all, [due, soon, ongoing, upcoming_near, upcoming_far]);
}

// contract-test: direct surface=sdks.rust assertions=sync.overview.priority-order,sync.overview.cross-device
#[test]
fn chat_order_is_deterministic_for_any_input_order() {
    let chats = vec![
        chat("e", false, false, 50.0, 1.0),
        chat("b", false, false, 100.0, 5.0),
        chat("a", false, false, 100.0, 5.0),
        chat("c", false, false, 100.0, 9.0),
        chat("d", false, true, 10.0, 1.0),
        chat("p", true, false, 1.0, 1.0),
    ];
    let expected = ["p", "d", "c", "a", "b", "e"];
    for rotation in 0..chats.len() {
        let mut rotated = chats.clone();
        rotated.rotate_left(rotation);
        rotated.reverse();
        let inputs = OverviewInputs { chats: &rotated, last_opened_chat_id: None, reminders: &[], saved_items: &[], now_ms: NOW, utc_offset_minutes: 0, include_sub_chats: false };
        assert_eq!(ordered_chat_ids(&inputs), expected);
    }
}

// contract-test: direct surface=sdks.rust assertions=sync.overview.priority-order
#[test]
fn due_items_then_last_opened_then_chats_without_duplicates() {
    let mut sub = chat("sub", false, false, 999.0, 999.0);
    sub.is_sub_chat = true;
    let chats = vec![
        chat("a", false, false, 10.0, 1.0),
        chat("b", false, false, 20.0, 1.0),
        chat("c", true, false, 5.0, 1.0),
        chat("d", false, false, 300.0, 1.0),
        sub,
    ];
    let reminders = vec![
        reminder("r1", NOW + 30 * 60_000, "pending", Some("a"), None),
        reminder("r2", NOW + 2 * HOUR_MS, "pending", None, Some("embed-without-time")),
        reminder("r3", NOW + HOUR_MS, "pending", Some("missing-chat"), None),
    ];
    let saved = vec![
        SavedItemInput { entry_id: "m1".into(), app_id: "events".into(), item_type: String::new(), item_value: json!({"embed_id": "concert", "date_start": iso(NOW + 3 * HOUR_MS)}) },
        SavedItemInput { entry_id: "m2".into(), app_id: "health".into(), item_type: String::new(), item_value: json!({"embed_id": "embed-without-time"}) },
        SavedItemInput { entry_id: "m3".into(), app_id: "travel".into(), item_type: String::new(), item_value: json!({"embed_id": "far", "departure": iso(NOW + 72 * HOUR_MS)}) },
    ];
    let inputs = OverviewInputs { chats: &chats, last_opened_chat_id: Some("b"), reminders: &reminders, saved_items: &saved, now_ms: NOW, utc_offset_minutes: 0, include_sub_chats: false };
    let entries = build_overview(&inputs);
    let labels: Vec<String> = entries
        .iter()
        .map(|entry| match entry {
            OverviewEntry::DueChat { chat_id, .. } => format!("due:{chat_id}"),
            OverviewEntry::DueSavedItem { embed_id, .. } => format!("saved:{embed_id}"),
            OverviewEntry::LastOpenedChat { chat_id } => format!("opened:{chat_id}"),
            OverviewEntry::Chat { chat_id } => chat_id.clone(),
        })
        .collect();
    assert_eq!(labels, ["due:a", "saved:embed-without-time", "saved:concert", "opened:b", "c", "d"]);
    let with_subs = OverviewInputs { include_sub_chats: true, ..inputs };
    assert_eq!(ordered_chat_ids(&with_subs), ["a", "b", "c", "sub", "d"]);
}

#[test]
fn last_opened_that_is_already_due_is_not_repeated() {
    let chats = vec![chat("a", false, false, 1.0, 1.0), chat("b", false, false, 2.0, 1.0)];
    let reminders = vec![reminder("r", NOW - 60_000, "fired", Some("a"), None)];
    let inputs = OverviewInputs { chats: &chats, last_opened_chat_id: Some("a"), reminders: &reminders, saved_items: &[], now_ms: NOW, utc_offset_minutes: 0, include_sub_chats: false };
    assert_eq!(ordered_chat_ids(&inputs), ["a", "b"]);
    assert!(matches!(build_overview(&inputs)[0], OverviewEntry::DueChat { .. }));
}

#[test]
fn chat_rank_reads_cached_rows() {
    let rank = ChatRank::from_row(&json!({"id":"x","pinned":true,"encrypted_draft_md":"cipher","last_edited_overall_timestamp":7,"updated_at":3.5,"parent_id":"p"})).unwrap();
    assert_eq!(rank, ChatRank { id: "x".into(), pinned: true, has_draft: true, last_edited_overall_timestamp: 7.0, updated_at: 3.5, is_sub_chat: true });
    assert!(!ChatRank::from_row(&json!({"id":"y","encrypted_draft_md":""})).unwrap().has_draft);
    assert!(ChatRank::from_row(&json!({"title":"no id"})).is_none());
}

// contract-test: direct surface=sdks.rust assertions=sync.overview.priority-order
#[test]
fn adapter_local_offset_is_process_wide_and_defaults_to_utc() {
    assert_eq!(local_utc_offset_minutes(), 0);
    set_local_utc_offset_minutes(330);
    assert_eq!(local_utc_offset_minutes(), 330);
    // A zone-less appointment 09:00 local is 03:30 UTC at +05:30.
    let value = json!("2027-01-15T09:00:00");
    assert_eq!(parse_time(Some(&value), local_utc_offset_minutes()), parse_time(Some(&json!("2027-01-15T03:30:00Z")), 0));
    set_local_utc_offset_minutes(0);
}
