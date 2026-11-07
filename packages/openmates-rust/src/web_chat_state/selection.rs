//! Active-chat selection decisions of the web app.
//!
//! Mirrors the branching of `stores/activeChatStore.ts` (URL hash plan of
//! `updateUrlHash`) and the selection guards in `Chats.svelte`
//! (`globalChatSelected` mirror, stale persisted-draft activation). The page
//! keeps `window.location`, `replaceState` and the hash string building; it
//! sends only the facts a decision needs and applies the returned plan.
//! spec: specifications/architecture/sync/specification.yml#sync.client.shared-rust-policy
use serde_json::{json, Value};

use super::{parse, protocol};

fn text<'a>(value: &'a Value, key: &str) -> Result<&'a str, String> {
    value.get(key).and_then(Value::as_str).ok_or_else(|| protocol(()))
}

fn flag(value: &Value, key: &str) -> Result<bool, String> {
    value.get(key).and_then(Value::as_bool).ok_or_else(|| protocol(()))
}

/// Chat id (`string` or null) at `key`; JS truthiness is applied by callers.
fn chat_id<'a>(value: &'a Value, key: &str) -> Result<Option<&'a str>, String> {
    match value.get(key) {
        Some(Value::Null) => Ok(None),
        Some(Value::String(id)) => Ok(Some(id.as_str())),
        _ => Err(protocol(())),
    }
}

/// URL plan of `updateUrlHash` for `{chatId, appsRoute, hasChatIdParam,
/// workflowHandoff, onSemanticPath, currentHash, targetHash}`. `targetHash` is
/// the hash the page built for the change (chat id set, or cleared when
/// `chatId` is null). The answer is `{action, programmatic}`: `none`,
/// `replace_root` (`replaceState('/')`), `replace_root_hash`
/// (`replaceState('/' + targetHash)`) or `replace_hash` (current path + search +
/// `targetHash`); `programmatic` asks the page to stamp the programmatic-update
/// window.
///
/// # Errors
/// Returns the fixed `protocol` code for malformed input.
pub fn url_plan_json(input: &str) -> Result<String, String> {
    let value = parse(input)?;
    let id = chat_id(&value, "chatId")?.filter(|id| !id.is_empty());
    let on_semantic_path = flag(&value, "onSemanticPath")?;
    let hash_differs = text(&value, "currentHash")? != text(&value, "targetHash")?;
    let (action, programmatic) = if id.is_some() {
        if on_semantic_path {
            ("replace_root_hash", false)
        } else if hash_differs {
            ("replace_hash", true)
        } else {
            ("none", false)
        }
    } else if (flag(&value, "appsRoute")? && !flag(&value, "hasChatIdParam")?)
        || flag(&value, "workflowHandoff")?
    {
        // Apps owns the URL, or a Workflow completion deep link awaits its chat.
        ("none", false)
    } else if on_semantic_path {
        ("replace_root", false)
    } else if hash_differs {
        ("replace_hash", true)
    } else {
        ("none", false)
    };
    Ok(json!({"action": action, "programmatic": programmatic}).to_string())
}

/// `globalChatSelected` mirror of `Chats.svelte` for `{selected, newId, active}`:
/// `{setSelected, writeStore}`. The store is rewritten only while another chat
/// is active, never while the user is in new-chat mode (`active` null).
///
/// # Errors
/// Returns the fixed `protocol` code for malformed input.
pub fn global_selected_json(input: &str) -> Result<String, String> {
    let value = parse(input)?;
    let new_id = text(&value, "newId")?;
    let set_selected = chat_id(&value, "selected")? != Some(new_id);
    let write_store = set_selected && chat_id(&value, "active")?.is_some_and(|a| a != new_id);
    Ok(json!({"setSelected": set_selected, "writeStore": write_store}).to_string())
}

/// Stale persisted-draft activation guard for `{selected, persisted}`: skip when
/// a different (non-empty) chat is selected.
///
/// # Errors
/// Returns the fixed `protocol` code for malformed input.
pub fn draft_activation_json(input: &str) -> Result<String, String> {
    let value = parse(input)?;
    let persisted = text(&value, "persisted")?;
    let skip = chat_id(&value, "selected")?.is_some_and(|s| !s.is_empty() && s != persisted);
    Ok(json!({"skip": skip}).to_string())
}
