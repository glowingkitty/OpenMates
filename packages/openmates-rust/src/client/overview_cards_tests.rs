use super::*;
use crate::client::overview::{DuePriority, DueReason, HOUR_MS};
use serde_json::json;

const NOW: i64 = 1_800_000_000_000;

fn priority(reason: DueReason, timestamp_ms: i64) -> DuePriority {
    DuePriority { reason, timestamp_ms }
}

// contract-test: supporting surface=cli assertions=sync.overview.priority-order
#[test]
fn relative_labels_round_like_the_web_carousel() {
    assert_eq!(relative_label("Reminder", NOW + 5 * MINUTE_MS, NOW), "Reminder in 5m");
    assert_eq!(relative_label("Reminder", NOW - 20_000, NOW), "Reminder 1m ago");
    assert_eq!(relative_label("Event", NOW + 90 * MINUTE_MS, NOW), "Event in 2h");
    assert_eq!(relative_label("Event", NOW - 3 * HOUR_MS, NOW), "Event 3h ago");
    assert_eq!(relative_label("Trip", NOW + 36 * HOUR_MS, NOW), "Trip in 2d");
}

// contract-test: supporting surface=cli assertions=sync.overview.priority-order
#[test]
fn saved_item_presentation_matches_the_web_groups() {
    let travel = json!({"origin": "Berlin", "destination": "Rome", "notes": " "});
    assert_eq!(saved_item_presentation("travel", "", &travel), ("Trip", Some("travel"), Some("Berlin · Rome".into())));
    assert_eq!(saved_item_presentation("x", "saved_event", &json!({"location": "Hall"})), ("Event", Some("events"), Some("Hall".into())));
    assert_eq!(saved_item_presentation("health", "", &json!({})), ("Appointment", Some("health"), None));
    assert_eq!(saved_item_presentation("other", "", &json!({"notes": "n"})), ("Saved item", None, Some("n".into())));
}

// contract-test: supporting surface=cli assertions=sync.overview.priority-order
#[test]
fn due_saved_item_and_chat_entries_carry_their_footers() {
    let item = json!({"embed_id": "e1", "title": "Concert", "location": "Arena", "date_start": "2027-01-15T12:00:00Z"});
    let start = crate::client::overview::parse_time(item.get("date_start"), 0).unwrap();
    let saved = vec![SavedItemInput { entry_id: "m1".into(), app_id: "events".into(), item_type: "event".into(), item_value: item }];
    let entries = vec![
        OverviewEntry::DueChat { chat_id: "c1".into(), reminder_id: "r1".into(), priority: priority(DueReason::ReminderSoon, start - 3 * HOUR_MS + 30 * MINUTE_MS) },
        OverviewEntry::DueSavedItem { embed_id: "e1".into(), entry_id: "m1".into(), app_id: "events".into(), priority: priority(DueReason::UpcomingSavedItem, start) },
        OverviewEntry::Chat { chat_id: "c2".into() },
    ];
    let cards = home_entries(&entries, &saved, start - 3 * HOUR_MS);
    assert_eq!(cards[0], HomeEntry::Chat { chat_id: "c1".into(), footer: Some("Reminder in 30m".into()) });
    assert_eq!(
        cards[1],
        HomeEntry::SavedItem {
            embed_id: "e1".into(),
            title: "Concert".into(),
            summary: Some("Arena".into()),
            category: Some("events".into()),
            footer: "Event in 3h · Saved".into(),
        }
    );
    assert_eq!(cards[2], HomeEntry::Chat { chat_id: "c2".into(), footer: None });
}
