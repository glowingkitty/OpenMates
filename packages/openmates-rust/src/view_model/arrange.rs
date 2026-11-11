//! Chat list order of the shared client core ("Continue where you left off"):
//! the shared overview comparator, with due-soon chats carrying their reminder
//! label as footer and due-soon saved items placed as `embed:<id>` entries,
//! interleaved by due priority ahead of the other chats.
//!
//! Moved from the TUI `home_items.rs` (`arrange`, `place`; lane L6b of
//! `docs/plans/apple-client-core-migration/a2-design.md`). Spec:
//! `architecture.sync@2`, assertion `sync.overview.priority-order`.
use crate::client::Client;
use crate::client::overview::{
    cards::{HomeEntry, home_entries},
    local_utc_offset_minutes,
};
use crate::model::Item;
use std::collections::BTreeMap;

/// Arrange chat inventory items in display order at the current time and the
/// shell-provided local UTC offset (`overview::set_local_utc_offset_minutes`).
pub fn arrange_chat_list(client: &Client, items: Vec<Item>) -> Vec<Item> {
    arrange_chat_list_at(
        client,
        items,
        crate::platform::unix_ms() as i64,
        local_utc_offset_minutes(),
    )
}

/// [`arrange_chat_list`] at an explicit time and offset (deterministic).
pub fn arrange_chat_list_at(
    client: &Client,
    items: Vec<Item>,
    now_ms: i64,
    utc_offset_minutes: i32,
) -> Vec<Item> {
    let ordered = client.order_chat_list_items(items, now_ms, utc_offset_minutes);
    let saved = client.due_soon_saved_items();
    let overview = client.workspace_overview(now_ms, utc_offset_minutes, &saved);
    place_home_entries(ordered, home_entries(&overview.entries, &saved, now_ms))
}

/// Pure placement of due-soon home entries over the ordered chat items: due
/// entries lead (chats get their `footer`, saved items become `embed:<id>`
/// items), the first plain chat entry ends the due block and the remaining
/// chats follow in their original order.
pub fn place_home_entries(ordered: Vec<Item>, entries: Vec<HomeEntry>) -> Vec<Item> {
    let mut by_id: BTreeMap<String, Item> = BTreeMap::new();
    let order: Vec<String> = ordered.iter().map(|item| item.id.clone()).collect();
    by_id.extend(ordered.into_iter().map(|item| (item.id.clone(), item)));
    let mut result = Vec::with_capacity(order.len());
    for entry in entries {
        match entry {
            HomeEntry::Chat {
                chat_id,
                footer: Some(footer),
            } => {
                if let Some(mut item) = by_id.remove(&chat_id) {
                    if !item.fields.is_object() {
                        item.fields = serde_json::json!({});
                    }
                    item.fields["footer"] = serde_json::Value::String(footer);
                    result.push(item);
                }
            }
            HomeEntry::SavedItem {
                embed_id,
                title,
                summary,
                category,
                footer,
            } => result.push(Item {
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
