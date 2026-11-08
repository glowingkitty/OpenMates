//! Chat-to-project placement decisions of the web chat list.
//!
//! Mirrors `assertOrganizableChats` and the planning half of
//! `placeChatsInProject` (`services/chatProjectService.ts`, TS reference in
//! `utils/chatProjectPlacement.ts`). The page keeps every HTTP call, the
//! workspace identity fences and the cache invalidation; it executes the steps
//! this module returns in order.
//! spec: specifications/architecture/sync/specification.yml#sync.client.shared-rust-policy
use std::collections::HashSet;

use serde_json::{json, Value};

use super::args::{array, flag, opt_text, text};
use super::{parse, protocol};

/// Whether every chat may be organised in the active workspace
/// (`assertOrganizableChats` predicate). Input `{chats: [{incognito,
/// sharedByOthers, demo, legal, public, teamId}], teamId}`; output `{ok}`.
///
/// # Errors
/// Returns the fixed `protocol` code for malformed input.
pub fn organizable_json(input: &str) -> Result<String, String> {
    let value = parse(input)?;
    let team = opt_text(&value, "teamId")?;
    let chats = array(&value, "chats")?;
    let mut ok = !chats.is_empty();
    for chat in chats {
        let blocked = ["incognito", "sharedByOthers", "demo", "legal", "public"]
            .iter()
            .try_fold(false, |any, key| flag(chat, key).map(|f| any || f))?;
        if blocked || opt_text(chat, "teamId")? != team {
            ok = false;
        }
    }
    Ok(json!({ "ok": ok }).to_string())
}

/// Chat ids shown at `folder_id` of a sidebar project (`projectFolderChatIds`,
/// non-recursive). An unknown folder holds nothing.
fn folder_chat_ids<'a>(project: &'a Value, folder_id: Option<&str>) -> Result<HashSet<&'a str>, String> {
    let hash = match folder_id {
        None => None,
        Some(id) => {
            let folder = array(project, "folders")?
                .iter()
                .find(|f| f.get("id").and_then(Value::as_str) == Some(id));
            match folder {
                None => return Ok(HashSet::new()),
                Some(f) => Some(text(f, "hash")?),
            }
        }
    };
    let mut ids = HashSet::new();
    for item in array(project, "chats")? {
        if opt_text(item, "folderHash")? == hash {
            ids.insert(text(item, "chatId")?);
        }
    }
    Ok(ids)
}

/// Ordered placement steps for `{chatIds, destination, location: {projectId,
/// folderId}, mode, index}` (`index` is every sidebar project incl. the
/// destination). Output `{error}` (`project_unavailable` or
/// `folder_unavailable`) or `{steps: [{kind: "move", itemId, chatId} |
/// {kind: "add", chatId} | {kind: "remove", sourceId, chatId}]}`.
///
/// # Errors
/// Returns the fixed `protocol` code for malformed input.
pub fn plan_json(input: &str) -> Result<String, String> {
    let value = parse(input)?;
    let location = value.get("location").ok_or_else(|| protocol(()))?;
    let project_id = text(location, "projectId")?;
    let folder = opt_text(location, "folderId")?;
    let move_mode = match text(&value, "mode")? {
        "move" => true,
        "add" => false,
        _ => return Err(protocol(())),
    };
    let index = array(&value, "index")?;
    let destination = index.iter().find(|p| p.get("id").and_then(Value::as_str) == Some(project_id));
    let Some(destination) = destination else {
        return Ok(json!({ "error": "project_unavailable" }).to_string());
    };
    if let Some(folder_id) = folder {
        let known = array(destination, "folders")?
            .iter()
            .any(|f| f.get("id").and_then(Value::as_str) == Some(folder_id));
        if !known {
            return Ok(json!({ "error": "folder_unavailable" }).to_string());
        }
    }
    let chat_ids: Vec<&str> = array(&value, "chatIds")?
        .iter()
        .map(|c| c.as_str().ok_or_else(|| protocol(())))
        .collect::<Result<_, _>>()?;
    let in_folder = folder_chat_ids(destination, folder)?;
    let mut steps = Vec::new();
    for chat in &chat_ids {
        if in_folder.contains(chat) {
            continue;
        }
        let existing = array(destination, "chats")?
            .iter()
            .find(|item| item.get("chatId").and_then(Value::as_str) == Some(chat));
        match existing {
            Some(item) => steps.push(json!({ "kind": "move", "itemId": text(item, "id")?, "chatId": chat })),
            None => steps.push(json!({ "kind": "add", "chatId": chat })),
        }
    }
    if move_mode {
        for source in index.iter().filter(|p| p.get("id").and_then(Value::as_str) != Some(project_id)) {
            let held: HashSet<&str> = array(source, "chats")?
                .iter()
                .map(|item| text(item, "chatId"))
                .collect::<Result<_, _>>()?;
            for chat in chat_ids.iter().filter(|c| held.contains(**c)) {
                steps.push(json!({ "kind": "remove", "sourceId": text(source, "id")?, "chatId": chat }));
            }
        }
    }
    Ok(json!({ "steps": steps }).to_string())
}
