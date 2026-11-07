//! Running-chat grouping for the sidebar activity indicators.
//!
//! Mirrors `utils/chatActivity.ts` (`processingAncestorIds`,
//! `aggregateRunningChats`). Chats arrive as `{id, parent, hidden}` records (hidden is
//! `is_hidden || is_hidden_candidate`); answers are ids or input indices.
//! spec: specifications/architecture/sync/specification.yml#sync.client.shared-rust-policy
use std::collections::{HashMap, HashSet};

use serde_json::{Value, json};

use super::args::{array, flag, opt_text, text};
use super::{parse, protocol};

struct Chat<'a> {
    id: &'a str,
    parent: Option<&'a str>,
    hidden: bool,
}

/// Chats by id (the last record of a duplicated id wins, like `new Map`) plus running ids.
fn read(value: &Value) -> Result<(Vec<Chat<'_>>, HashMap<&str, usize>, Vec<&str>), String> {
    let mut chats = Vec::new();
    let mut by_id = HashMap::new();
    for chat in array(value, "chats")? {
        let id = text(chat, "id")?;
        by_id.insert(id, chats.len());
        chats.push(Chat {
            id,
            parent: opt_text(chat, "parent")?.filter(|p| !p.is_empty()),
            hidden: flag(chat, "hidden")?,
        });
    }
    let running = array(value, "running")?
        .iter()
        .map(|v| v.as_str().ok_or_else(|| protocol(())))
        .collect::<Result<Vec<&str>, String>>()?;
    Ok((chats, by_id, running))
}

/// `processingAncestorIds`: every chat on the ancestry of a running chat, unless
/// any chat on that ancestry is hidden. Ids in first-added order.
///
/// # Errors
/// Returns the fixed `protocol` code for malformed input.
pub fn ancestors_json(input: &str) -> Result<String, String> {
    let value = parse(input)?;
    let (chats, by_id, running) = read(&value)?;
    let mut result: Vec<&str> = Vec::new();
    let mut seen: HashSet<&str> = HashSet::new();
    for id in running {
        let mut ancestry: Vec<&Chat<'_>> = Vec::new();
        let mut visited: HashSet<&str> = HashSet::new();
        let mut current = by_id.get(id).map(|&i| &chats[i]);
        while let Some(chat) = current {
            if !visited.insert(chat.id) {
                break;
            }
            ancestry.push(chat);
            current = chat.parent.and_then(|p| by_id.get(p)).map(|&i| &chats[i]);
        }
        if ancestry.iter().any(|c| c.hidden) {
            continue;
        }
        for ancestor in ancestry {
            if seen.insert(ancestor.id) {
                result.push(ancestor.id);
            }
        }
    }
    Ok(json!(result).to_string())
}

/// `aggregateRunningChats`: `[rootIndex, activeSubChatCount]` per visible root, in first-seen order.
///
/// # Errors
/// Returns the fixed `protocol` code for malformed input.
pub fn aggregate_json(input: &str) -> Result<String, String> {
    let value = parse(input)?;
    let (chats, by_id, running) = read(&value)?;
    let mut groups: Vec<(usize, usize)> = Vec::new();
    for id in running {
        let Some(&start) = by_id.get(id) else {
            continue;
        };
        let mut root = start;
        let mut visited: HashSet<&str> = HashSet::from([id]);
        let mut hidden = chats[root].hidden;
        while let Some(&parent) = chats[root]
            .parent
            .filter(|p| !visited.contains(p))
            .and_then(|p| by_id.get(p))
        {
            visited.insert(chats[parent].id);
            root = parent;
            hidden |= chats[root].hidden;
        }
        if hidden {
            continue;
        }
        // Groups are keyed by chat id, like the TS Map.
        let slot = match groups
            .iter()
            .position(|(r, _)| chats[*r].id == chats[root].id)
        {
            Some(slot) => slot,
            None => {
                groups.push((root, 0));
                groups.len() - 1
            }
        };
        if id != chats[root].id {
            groups[slot].1 += 1;
        }
    }
    Ok(json!(groups).to_string())
}
