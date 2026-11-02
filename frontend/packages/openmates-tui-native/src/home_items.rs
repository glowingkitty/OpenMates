//! Home carousel arrangement ("Continue where you left off").
//!
//! The chat list order is the shared overview comparator. Due-soon chats get
//! their reminder label as card footer and due-soon saved items become
//! `embed:<id>` entries, interleaved by due priority ahead of the other chats.
use openmates_sdk::client::{Client, overview::cards::{HomeEntry, home_entries}};
use openmates_sdk::model::Item;
use std::collections::BTreeMap;

fn now_ms() -> i64 {
    std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .map_or(0, |elapsed| elapsed.as_millis() as i64)
}

pub fn arrange(client: &Client, items: Vec<Item>) -> Vec<Item> {
    arrange_at(client, items, now_ms())
}

fn arrange_at(client: &Client, items: Vec<Item>, now: i64) -> Vec<Item> {
    let ordered = client.order_chat_list_items_now(items);
    let saved = client.due_soon_saved_items();
    let overview = client.workspace_overview(now, crate::local_zone::utc_offset_minutes(), &saved);
    place(ordered, home_entries(&overview.entries, &saved, now))
}

/// Pure placement of home entries over the ordered chat items.
pub fn place(ordered: Vec<Item>, entries: Vec<HomeEntry>) -> Vec<Item> {
    let mut by_id: BTreeMap<String, Item> = BTreeMap::new();
    let order: Vec<String> = ordered.iter().map(|item| item.id.clone()).collect();
    by_id.extend(ordered.into_iter().map(|item| (item.id.clone(), item)));
    let mut result = Vec::with_capacity(order.len());
    for entry in entries {
        match entry {
            HomeEntry::Chat { chat_id, footer: Some(footer) } => {
                if let Some(mut item) = by_id.remove(&chat_id) {
                    if !item.fields.is_object() {
                        item.fields = serde_json::json!({});
                    }
                    item.fields["footer"] = serde_json::Value::String(footer);
                    result.push(item);
                }
            }
            HomeEntry::SavedItem { embed_id, title, summary, category, footer } => result.push(Item {
                id: format!("embed:{embed_id}"),
                title,
                description: summary.unwrap_or_else(|| "Open saved item".to_owned()),
                category: category.unwrap_or_default(),
                fields: serde_json::json!({ "footer": footer }),
                ..Item::default()
            }),
            HomeEntry::Chat { footer: None, .. } => break,
        }
    }
    result.extend(order.into_iter().filter_map(|id| by_id.remove(&id)));
    result
}

#[cfg(test)]
mod tests {
    use super::*;

    fn chat(id: &str) -> Item {
        Item { id: id.into(), title: id.into(), category: "general_knowledge".into(), fields: serde_json::json!({}), ..Item::default() }
    }

    // contract-test: supporting surface=cli assertions=sync.overview.priority-order
    #[test]
    fn due_entries_lead_with_footers_and_saved_items_are_embed_cards() {
        let placed = place(
            vec![chat("a"), chat("b"), chat("c")],
            vec![
                HomeEntry::SavedItem { embed_id: "e1".into(), title: "Concert".into(), summary: None, category: Some("events".into()), footer: "Event in 3h · Saved".into() },
                HomeEntry::Chat { chat_id: "c".into(), footer: Some("Reminder in 5m".into()) },
                HomeEntry::Chat { chat_id: "a".into(), footer: None },
            ],
        );
        let ids: Vec<&str> = placed.iter().map(|item| item.id.as_str()).collect();
        assert_eq!(ids, ["embed:e1", "c", "a", "b"]);
        assert_eq!(placed[0].fields["footer"], "Event in 3h · Saved");
        assert_eq!(placed[0].description, "Open saved item");
        assert_eq!(placed[1].fields["footer"], "Reminder in 5m");
        assert!(placed[2].fields.get("footer").is_none());
    }
}
