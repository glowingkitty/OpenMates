//! Chat timeline entry merging and exchange pairing.
//!
//! Mirrors `utils/chatTimeline.ts` (`mergeTimelineEntries`,
//! `buildTimelineExchangeIndex`, `timelineResponseId`, `pairTimelineExchange`).
//! The page sends the identity fields only (ids, roles, `user_message_id`, sort
//! timestamps) and applies index/id answers to its own message objects, so no
//! message body crosses the Worker boundary. An empty `userMessageId` is the
//! JS-falsy case and counts as absent.
//! spec: specifications/architecture/sync/specification.yml#sync.client.shared-rust-policy
use std::cmp::Ordering;
use std::collections::HashSet;

use serde_json::{Value, json};

use super::args::{array, flag, number, opt_text, text};
use super::{parse, protocol};

struct Entry<'a> {
    id: &'a str,
    role: &'a str,
    user_message_id: Option<&'a str>,
}

fn entries(value: &Value) -> Result<Vec<Entry<'_>>, String> {
    array(value, "entries")?
        .iter()
        .map(|e| {
            Ok(Entry {
                id: text(e, "id")?,
                role: text(e, "role")?,
                user_message_id: opt_text(e, "userMessageId")?.filter(|s| !s.is_empty()),
            })
        })
        .collect()
}

/// Insertion-ordered map with JS `Map` semantics (`set` on an existing key keeps its position).
#[derive(Default)]
struct OrderedMap<'a> {
    items: Vec<(&'a str, Vec<&'a str>)>,
}

impl<'a> OrderedMap<'a> {
    fn position(&self, key: &str) -> Option<usize> {
        self.items.iter().position(|(k, _)| *k == key)
    }
    fn set(&mut self, key: &'a str, value: Vec<&'a str>) {
        match self.position(key) {
            Some(i) => self.items[i].1 = value,
            None => self.items.push((key, value)),
        }
    }
}

/// Insertion-ordered set.
#[derive(Default)]
struct OrderedSet<'a> {
    seen: HashSet<&'a str>,
    items: Vec<&'a str>,
}

impl<'a> OrderedSet<'a> {
    fn add(&mut self, id: &'a str) {
        if self.seen.insert(id) {
            self.items.push(id);
        }
    }
    fn has(&self, id: &str) -> bool {
        self.seen.contains(id)
    }
}

/// `String.prototype.localeCompare` for the ids the timeline sorts by: ICU root
/// order for ASCII (punctuation, then digits, then letters case-insensitively;
/// lower case before upper case only as the final tie-break).
fn locale_compare(a: &str, b: &str) -> Ordering {
    fn primary(c: char) -> (u8, char) {
        let lower = c.to_lowercase().next().unwrap_or(c);
        let class = if c.is_ascii_digit() {
            1
        } else if c.is_alphabetic() {
            2
        } else {
            0
        };
        (class, lower)
    }
    let by_primary = a.chars().map(primary).cmp(b.chars().map(primary));
    by_primary.then_with(|| {
        a.chars()
            .zip(b.chars())
            .find(|(x, y)| x != y)
            .map_or(Ordering::Equal, |(x, y)| {
                if x.is_lowercase() && y.is_uppercase() {
                    Ordering::Less
                } else {
                    Ordering::Greater
                }
            })
    })
}

/// `mergeTimelineEntries` for `{pages: [[{id, createdAt}]]}`: indices into the
/// pages flattened in order, one per id (the last row of an id wins), sorted by
/// `createdAt` then id.
///
/// # Errors
/// Returns the fixed `protocol` code for malformed input.
pub fn merge_json(input: &str) -> Result<String, String> {
    let value = parse(input)?;
    let mut slots: Vec<(&str, f64, usize)> = Vec::new();
    let mut flat = 0usize;
    for page in array(&value, "pages")? {
        for row in page.as_array().ok_or_else(|| protocol(()))? {
            let (id, at) = (text(row, "id")?, number(row, "createdAt")?);
            match slots.iter_mut().find(|slot| slot.0 == id) {
                Some(slot) => *slot = (id, at, flat),
                None => slots.push((id, at, flat)),
            }
            flat += 1;
        }
    }
    slots.sort_by(|a, b| {
        (a.1 - b.1)
            .partial_cmp(&0.0)
            .unwrap_or(Ordering::Equal)
            .then_with(|| locale_compare(a.0, b.0))
    });
    Ok(json!(slots.iter().map(|s| s.2).collect::<Vec<_>>()).to_string())
}

/// `buildTimelineExchangeIndex` for `{entries: [{id, role, userMessageId}],
/// bookmarks: [id]}`.
///
/// # Errors
/// Returns the fixed `protocol` code for malformed input.
pub fn exchange_index_json(input: &str) -> Result<String, String> {
    let value = parse(input)?;
    let entries = entries(&value)?;
    let bookmarks: HashSet<&str> = array(&value, "bookmarks")?
        .iter()
        .map(|b| b.as_str().ok_or_else(|| protocol(())))
        .collect::<Result<_, _>>()?;
    let users: HashSet<&str> = entries
        .iter()
        .filter(|e| e.role == "user")
        .map(|e| e.id)
        .collect();
    let (mut explicit, mut legacy) = (OrderedMap::default(), OrderedMap::default());
    let (mut assistant_users, mut aliases) = (OrderedMap::default(), OrderedMap::default());
    let (mut result, mut assistant_bookmarks) = (OrderedSet::default(), OrderedSet::default());
    let mut previous_user: Option<&str> = None;
    for entry in &entries {
        if entry.role == "user" {
            previous_user = Some(entry.id);
        }
        if entry.role != "assistant" {
            continue;
        }
        let Some(target) = entry.user_message_id.or(previous_user) else {
            continue;
        };
        if !users.contains(target) {
            continue;
        }
        assistant_users.set(entry.id, vec![target]);
        let responses = if entry.user_message_id.is_some() {
            &mut explicit
        } else {
            &mut legacy
        };
        if responses.position(target).is_none() {
            responses.set(target, vec![entry.id]);
        }
        if bookmarks.contains(entry.id) {
            result.add(target);
            assistant_bookmarks.add(entry.id);
        }
    }
    let mut exchanges = Vec::new();
    for (index, question) in entries.iter().enumerate().filter(|(_, e)| e.role == "user") {
        let response = explicit
            .position(question.id)
            .map(|i| explicit.items[i].1[0])
            .or_else(|| legacy.position(question.id).map(|i| legacy.items[i].1[0]));
        if let Some(response) = response {
            aliases.set(response, vec![question.id]);
            if bookmarks.contains(question.id) {
                result.add(question.id);
                assistant_bookmarks.add(response);
            }
        }
        exchanges.push(json!([index, response, result.has(question.id)]));
    }
    let answered = explicit.items.len()
        + legacy
            .items
            .iter()
            .filter(|(k, _)| explicit.position(k).is_none())
            .count();
    let pairs = |map: &OrderedMap<'_>| -> Vec<Value> {
        map.items.iter().map(|(k, v)| json!([k, v])).collect()
    };
    Ok(json!({
        "exchanges": exchanges,
        "answeredCount": answered,
        "assistantBookmarks": assistant_bookmarks.items,
        "legacyAliases": pairs(&aliases),
        "assistantUsers": assistant_users.items.iter().map(|(k, v)| json!([k, v[0]])).collect::<Vec<_>>(),
        "bookmarkedExchanges": result.items,
    })
    .to_string())
}

/// Index of the response entry of the user entry `id`, if any.
fn response_index(entries: &[Entry<'_>], id: &str) -> Option<usize> {
    let index = entries
        .iter()
        .position(|e| e.id == id && e.role == "user")?;
    if let Some(linked) = entries
        .iter()
        .position(|e| e.role == "assistant" && e.user_message_id == Some(id))
    {
        return Some(linked);
    }
    entries[index + 1..]
        .iter()
        .take_while(|e| e.role != "user")
        .position(|e| e.role == "assistant" && e.user_message_id.is_none())
        .map(|offset| index + 1 + offset)
}

/// `timelineResponseId` for `{entries, id}`: the response message id or null.
///
/// # Errors
/// Returns the fixed `protocol` code for malformed input.
pub fn response_id_json(input: &str) -> Result<String, String> {
    let value = parse(input)?;
    let entries = entries(&value)?;
    let id = text(&value, "id")?;
    Ok(json!(response_index(&entries, id).map(|i| entries[i].id)).to_string())
}

/// `pairTimelineExchange` for `{entries, id, pendingUserId, undecryptable}`
/// (`undecryptable`: the user row has ciphertext but no content). Answers
/// `{user, assistant, pending}` as input indices, or `{error}` with
/// `unavailable` / `undecryptable` for the two TS throws.
///
/// # Errors
/// Returns the fixed `protocol` code for malformed input.
pub fn pair_json(input: &str) -> Result<String, String> {
    let value = parse(input)?;
    let entries = entries(&value)?;
    let id = text(&value, "id")?;
    let pending_user = opt_text(&value, "pendingUserId")?;
    let Some(user) = entries.iter().position(|e| e.id == id && e.role == "user") else {
        return Ok(json!({"error": "unavailable"}).to_string());
    };
    if flag(&value, "undecryptable")? {
        return Ok(json!({"error": "undecryptable"}).to_string());
    }
    let assistant = response_index(&entries, id)
        .and_then(|r| entries.iter().position(|e| e.id == entries[r].id));
    let pending = assistant.is_none() && pending_user == Some(id);
    Ok(json!({"user": user, "assistant": assistant, "pending": pending}).to_string())
}
