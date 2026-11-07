//! Unread-message bookkeeping of the web chat list.
//!
//! Mirrors `stores/unreadMessagesStore.ts` (per-chat counts, once-per-reply
//! counting capped at 50 ids per chat, manually-unread set) and the read gate of
//! `services/chatReadState.ts` (`hasUnread`, `markWhenSettled` pre/post checks).
//! The reducer is pure: the page holds the state value, sends `{state, event}` and
//! stores the answer. Counts keep Map insertion order (delete then set moves a
//! chat to the end), so the state is ordered pair lists, not objects.
//! spec: specifications/architecture/sync/specification.yml#sync.client.shared-rust-policy
use serde_json::{json, Value};

use super::{parse, protocol};

/// Replies remembered per chat so local and server signals never double count.
const MAX_COUNTED_REPLY_IDS_PER_CHAT: usize = 50;

#[derive(Default)]
struct State {
    counts: Vec<(String, i64)>,
    counted: Vec<(String, Vec<String>)>,
    manual: Vec<String>,
}

fn string(value: &Value) -> Result<String, String> {
    value.as_str().map(str::to_string).ok_or_else(|| protocol(()))
}

fn list<'a>(value: &'a Value, key: &str) -> Result<&'a Vec<Value>, String> {
    value.get(key).and_then(Value::as_array).ok_or_else(|| protocol(()))
}

fn parse_state(value: &Value) -> Result<State, String> {
    let mut state = State::default();
    for pair in list(value, "counts")? {
        let pair = pair.as_array().filter(|p| p.len() == 2).ok_or_else(|| protocol(()))?;
        state.counts.push((string(&pair[0])?, pair[1].as_i64().ok_or_else(|| protocol(()))?));
    }
    for pair in list(value, "counted")? {
        let pair = pair.as_array().filter(|p| p.len() == 2).ok_or_else(|| protocol(()))?;
        let ids = pair[1].as_array().ok_or_else(|| protocol(()))?;
        state.counted.push((string(&pair[0])?, ids.iter().map(string).collect::<Result<_, _>>()?));
    }
    for id in list(value, "manual")? {
        state.manual.push(string(id)?);
    }
    Ok(state)
}

fn state_json(state: &State) -> Value {
    json!({"counts": state.counts, "counted": state.counted, "manual": state.manual})
}

fn count_of(state: &State, chat: &str) -> i64 {
    state.counts.iter().find(|(id, _)| id == chat).map_or(0, |(_, n)| *n)
}

/// Map `set`: replaces in place, appends when new.
fn set_count(state: &mut State, chat: &str, count: i64) {
    match state.counts.iter_mut().find(|(id, _)| id == chat) {
        Some((_, n)) => *n = count,
        None => state.counts.push((chat.to_string(), count)),
    }
}

fn delete_count(state: &mut State, chat: &str) {
    state.counts.retain(|(id, _)| id != chat);
}

/// `rememberCountedReply`: false when the reply was already counted.
fn remember(state: &mut State, chat: &str, message: &str) -> bool {
    let index = match state.counted.iter().position(|(id, _)| id == chat) {
        Some(index) => index,
        None => {
            state.counted.push((chat.to_string(), Vec::new()));
            state.counted.len() - 1
        }
    };
    let ids = &mut state.counted[index].1;
    if ids.iter().any(|id| id == message) {
        return false;
    }
    ids.push(message.to_string());
    if ids.len() > MAX_COUNTED_REPLY_IDS_PER_CHAT {
        ids.remove(0);
    }
    true
}

/// Reply id of an event; absent, null or empty counts as none (JS falsy).
fn message_id(event: &Value) -> Option<&str> {
    event.get("messageId").and_then(Value::as_str).filter(|m| !m.is_empty())
}

/// Applies one store mutation to `{state, event}`. Events (`type`): `increment`
/// `{chat, messageId?}`, `set` `{chat, count, messageId?}`, `clear` `{chat}`,
/// `mark_manual` `{chat}`, `release_manual` `{chat}`, `clear_all`. Answers the
/// new state.
///
/// # Errors
/// Returns the fixed `protocol` code for malformed input or an unknown event.
pub fn reduce_json(input: &str) -> Result<String, String> {
    let value = parse(input)?;
    let mut state = parse_state(value.get("state").ok_or_else(|| protocol(()))?)?;
    let event = value.get("event").ok_or_else(|| protocol(()))?;
    let kind = event.get("type").and_then(Value::as_str).ok_or_else(|| protocol(()))?;
    if kind == "clear_all" {
        return Ok(state_json(&State::default()).to_string());
    }
    let chat = string(event.get("chat").ok_or_else(|| protocol(()))?)?;
    match kind {
        "increment" => {
            let counted_before = message_id(event).is_none_or(|m| remember(&mut state, &chat, m));
            if counted_before {
                let next = count_of(&state, &chat) + 1;
                set_count(&mut state, &chat, next);
            }
        }
        "set" => {
            if let Some(m) = message_id(event) {
                remember(&mut state, &chat, m);
            }
            let count = event.get("count").and_then(Value::as_i64).ok_or_else(|| protocol(()))?;
            if count <= 0 {
                delete_count(&mut state, &chat);
            } else {
                set_count(&mut state, &chat, count);
            }
        }
        "clear" => {
            state.manual.retain(|id| *id != chat);
            delete_count(&mut state, &chat);
        }
        "mark_manual" => {
            if !state.manual.contains(&chat) {
                state.manual.push(chat.clone());
            }
            set_count(&mut state, &chat, 1);
        }
        "release_manual" => state.manual.retain(|id| *id != chat),
        _ => return Err(protocol(())),
    }
    Ok(state_json(&state).to_string())
}

/// Read model for `{state, chat, persisted}`: `{count, manual, hasUnread}`.
/// `hasUnread` is `hasUnread()` of chatReadState (store count or the persisted
/// count above zero).
///
/// # Errors
/// Returns the fixed `protocol` code for malformed input.
pub fn query_json(input: &str) -> Result<String, String> {
    let value = parse(input)?;
    let state = parse_state(value.get("state").ok_or_else(|| protocol(()))?)?;
    let chat = string(value.get("chat").ok_or_else(|| protocol(()))?)?;
    let persisted = match value.get("persisted") {
        None | Some(Value::Null) => 0,
        Some(n) => n.as_i64().ok_or_else(|| protocol(()))?,
    };
    let count = count_of(&state, &chat);
    Ok(json!({
        "count": count,
        "manual": state.manual.contains(&chat),
        "hasUnread": count > 0 || persisted > 0,
    })
    .to_string())
}

/// Read gate of `markWhenSettled` for `{stage, visible, manual, hasUnread,
/// endVisible, stillOpen}` (`stage` is `pre` before the settle delay, `post`
/// after it): `{proceed}`. `stillOpen` is null when the caller gave no check.
///
/// # Errors
/// Returns the fixed `protocol` code for malformed input or an unknown stage.
pub fn read_gate_json(input: &str) -> Result<String, String> {
    let value = parse(input)?;
    let get = |key: &str| value.get(key).and_then(Value::as_bool).ok_or_else(|| protocol(()));
    let stage = value.get("stage").and_then(Value::as_str).ok_or_else(|| protocol(()))?;
    let still_open = match value.get("stillOpen") {
        Some(Value::Null) => true,
        Some(Value::Bool(open)) => *open,
        _ => return Err(protocol(())),
    };
    if !matches!(stage, "pre" | "post") {
        return Err(protocol(()));
    }
    let open_ok = stage == "pre" || still_open;
    let proceed = open_ok && get("visible")? && !get("manual")? && get("hasUnread")? && get("endVisible")?;
    Ok(json!({"proceed": proceed}).to_string())
}
