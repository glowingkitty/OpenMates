//! Chat list placement of due-soon home entries (moved from the TUI
//! `home_items.rs` tests; `sync.overview.priority-order`).
use super::place_home_entries;
use crate::client::overview::cards::HomeEntry;
use crate::model::Item;

fn chat(id: &str) -> Item {
    Item {
        id: id.into(),
        title: id.into(),
        category: "general_knowledge".into(),
        fields: serde_json::json!({}),
        ..Item::default()
    }
}

// contract-test: supporting surface=cli assertions=sync.overview.priority-order
#[test]
fn due_entries_lead_with_footers_and_saved_items_are_embed_cards() {
    let placed = place_home_entries(
        vec![chat("a"), chat("b"), chat("c")],
        vec![
            HomeEntry::SavedItem {
                embed_id: "e1".into(),
                title: "Concert".into(),
                summary: None,
                category: Some("events".into()),
                footer: "Event in 3h · Saved".into(),
            },
            HomeEntry::Chat {
                chat_id: "c".into(),
                footer: Some("Reminder in 5m".into()),
            },
            HomeEntry::Chat {
                chat_id: "a".into(),
                footer: None,
            },
        ],
    );
    let ids: Vec<&str> = placed.iter().map(|item| item.id.as_str()).collect();
    assert_eq!(ids, ["embed:e1", "c", "a", "b"]);
    assert_eq!(placed[0].fields["footer"], "Event in 3h · Saved");
    assert_eq!(placed[0].description, "Open saved item");
    assert_eq!(placed[1].fields["footer"], "Reminder in 5m");
    assert!(placed[2].fields.get("footer").is_none());
}
