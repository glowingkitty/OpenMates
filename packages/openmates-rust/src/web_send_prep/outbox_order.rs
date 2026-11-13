//! Replay order of queued offline changes (port of `orderOfflineChanges`).
//!
//! spec: specifications/features/chats#chats.message.identity-idempotent
use super::protocol;
use serde_json::{Value, json};

/// Largest integer a JavaScript number represents exactly (`Number.MAX_SAFE_INTEGER`).
const MAX_SAFE: f64 = 9_007_199_254_740_991.0;

struct Row {
    key: (Option<String>, String, bool),
    /// `None`: the row has no `queue_order` member (legacy row).
    order: Option<Option<u64>>,
}

fn row(value: &Value) -> Result<Row, String> {
    let chat = value.get("chat_id").and_then(Value::as_str).ok_or("protocol")?;
    let team = match value.get("team_id") {
        None | Some(Value::Null) => None,
        Some(Value::String(team)) => Some(team.clone()),
        Some(_) => return Err("protocol".into()),
    };
    let title = value.get("type").and_then(Value::as_str) == Some("title");
    let order = value.get("queue_order").map(|order| {
        let number = order.as_f64()?;
        // `Number.isSafeInteger(order) && order >= 1`; anything else makes the group ambiguous.
        (number.fract() == 0.0 && (1.0..=MAX_SAFE).contains(&number)).then_some(number as u64)
    });
    Ok(Row { key: (team, chat.to_string(), title), order })
}

/// `{rows: [{chat_id, team_id?, type, queue_order?}]}` -> `{ready: [row index], retained}`.
pub fn order_offline_changes_json(input: &str) -> Result<String, String> {
    let value: Value = serde_json::from_str(input).map_err(protocol)?;
    let rows = value.get("rows").and_then(Value::as_array).ok_or("protocol")?;
    let rows: Vec<Row> = rows.iter().map(row).collect::<Result<_, _>>()?;
    // Groups keep the order of their first member (a JS Map iterates by insertion).
    let mut groups: Vec<(&(Option<String>, String, bool), Vec<usize>)> = Vec::new();
    for (index, row) in rows.iter().enumerate() {
        match groups.iter_mut().find(|(key, _)| **key == row.key) {
            Some((_, members)) => members.push(index),
            None => groups.push((&row.key, vec![index])),
        }
    }
    let (mut ready, mut retained) = (Vec::new(), 0usize);
    for (_, members) in groups {
        let legacy: Vec<usize> = members.iter().copied().filter(|i| rows[*i].order.is_none()).collect();
        let mut ordered: Vec<(u64, usize)> = Vec::new();
        let mut invalid = false;
        for index in &members {
            match rows[*index].order {
                Some(Some(order)) => ordered.push((order, *index)),
                Some(None) => invalid = true,
                None => {}
            }
        }
        let mut seen: Vec<u64> = ordered.iter().map(|(order, _)| *order).collect();
        seen.sort_unstable();
        seen.dedup();
        // Several legacy rows, or legacy mixed with ordered rows, have no recoverable chronology.
        if legacy.len() > 1 || (!legacy.is_empty() && !ordered.is_empty()) || invalid
            || seen.len() != ordered.len()
        {
            retained += members.len();
            continue;
        }
        ordered.sort_unstable_by_key(|(order, _)| *order);
        ready.extend(legacy);
        ready.extend(ordered.into_iter().map(|(_, index)| index));
    }
    Ok(json!({"ready": ready, "retained": retained}).to_string())
}
