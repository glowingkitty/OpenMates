//! Workflow-in-Project and Project authoring decisions: the item and connected source a
//! saved workflow binds to, why a remote workflow file stays pending, the bounded
//! authoring transcript and the authoring catalog. Shared core part of `web_projects`.
//!
//! spec: specifications/surfaces/sdk#sdk.client.thin-platform-boundary
//! Mirrors `projectState/projectWorkflowPolicy.ts`; an empty transcript throws like TS.

use super::js::{
    as_str, gt, is_integer, is_str, len16, nullish_or, number_to_string, opt_prop, prop, put, req_array, req_str,
    slice16, strict_eq, to_number, trim, truthy,
};
use super::{Fault, Outcome, throw};
use serde_json::{Map, Value, json};

/// Character budget (UTF-16 units) of the authoring transcript.
const HISTORY_BUDGET_CHARS: i64 = 12_000;
/// Largest catalog the authoring assessment accepts; a larger one answers `null`.
const MAX_AUTHORING_CATALOG: usize = 40;

/// `projectWorkflowTarget`: existing item index, bound source index, remote flag and binding plan.
pub(super) fn target(input: &Value) -> Outcome {
    let root = Some(input);
    let sources = req_array(prop(root, "sources")?, "sources")?;
    let items = req_array(prop(root, "items")?, "items")?;
    let target_source_id = prop(root, "targetSourceId")?;

    let mut remote_sources: Vec<usize> = Vec::new();
    for (index, source) in sources.iter().enumerate() {
        let source_type = req_str(prop(Some(source), "source_type")?, "source_type")?;
        if source_type.starts_with("remote_") || truthy(prop(Some(source), "sourceSessionId")?) {
            remote_sources.push(index);
        }
    }

    let workflow_id = prop(root, "workflowId")?;
    let mut existing: Option<usize> = None;
    for (index, item) in items.iter().enumerate() {
        if is_str(prop(Some(item), "item_type")?, "workflow") && strict_eq(prop(Some(item), "target_id")?, workflow_id) {
            existing = Some(index);
            break;
        }
    }
    let prior = match existing {
        Some(index) => prop(prop(Some(&items[index]), "metadata")?, "remote_workflow_file")?,
        None => None,
    };
    let prior_source_id = opt_prop(prior, "source_id");
    let source_id = if truthy(prior_source_id) { prior_source_id } else { target_source_id };

    let source_index = if truthy(source_id) {
        let mut found = None;
        for (index, source) in sources.iter().enumerate() {
            if strict_eq(prop(Some(source), "source_id")?, source_id) {
                found = Some(index);
                break;
            }
        }
        found
    } else if remote_sources.len() == 1 {
        Some(remote_sources[0])
    } else {
        None
    };
    let remote = source_index.is_some() || !remote_sources.is_empty() || truthy(target_source_id) || truthy(prior);

    let binding = if !remote {
        Value::Null
    } else if truthy(prior_source_id) {
        json!({ "mode": "prior" })
    } else {
        let mut plan = Map::new();
        plan.insert("mode".to_owned(), Value::from("new"));
        put(&mut plan, "project_id", prop(root, "projectId")?);
        match source_index {
            Some(index) => put(&mut plan, "source_id", prop(Some(&sources[index]), "source_id")?),
            None => {
                plan.insert("source_id".to_owned(), Value::from(""));
            }
        }
        let empty = Value::from("");
        plan.insert("folder_path".to_owned(), nullish_or(prop(root, "folderPath")?, &empty).clone());
        Value::Object(plan)
    };
    Ok(json!({
        "existingIndex": existing,
        "sourceIndex": source_index,
        "remote": remote,
        "binding": binding,
    }))
}

/// `projectWorkflowRemoteGate`: `source_offline`, `project_focus_required` or `null`.
pub(super) fn remote_gate(input: &Value) -> Outcome {
    let root = Some(input);
    let project_id = prop(root, "projectId")?;
    let pending = if is_str(prop(root, "phase")?, "source") {
        if is_str(prop(root, "sourceStatus")?, "offline") {
            Some("source_offline")
        } else if !strict_eq(prop(root, "bindingProjectId")?, project_id) {
            Some("project_focus_required")
        } else {
            None
        }
    } else if !truthy(prop(root, "sourceFound")?)
        || !truthy(prop(root, "chatId")?)
        || !strict_eq(prop(root, "focusProjectId")?, project_id)
    {
        Some("project_focus_required")
    } else {
        None
    };
    Ok(json!({ "pending": pending }))
}

/// `projectAuthoringHistory`: newest completed user/assistant turns (oldest first) within
/// the character budget.
///
/// # Errors
/// Throws `project_authoring_history_unavailable` when no turn qualifies.
pub(super) fn authoring_history(input: &Value) -> Outcome {
    let root = Some(input);
    let messages = req_array(prop(root, "messages")?, "messages")?;
    let anchor = prop(root, "anchorCreatedAt")?;
    let mut rows: Vec<Value> = Vec::new();
    let mut remaining = HISTORY_BUDGET_CHARS;
    for message in messages.iter().rev() {
        let message = Some(message);
        let created_at = prop(message, "created_at")?;
        // `anchor !== null && created_at > anchor`; an absent anchor compares as NaN (false).
        if !matches!(anchor, Some(Value::Null)) && gt(created_at, anchor) {
            continue;
        }
        let role = prop(message, "role")?;
        if !is_str(role, "user") && !is_str(role, "assistant") {
            continue;
        }
        let content = match prop(message, "content")? {
            None | Some(Value::Null) => continue,
            Some(Value::String(text)) => text,
            // `content?.trim()` on a non-string is a TypeError in TS.
            Some(_) => return Err(Fault::Malformed("bad_field:content".to_owned())),
        };
        if trim(content).is_empty() {
            continue;
        }
        let status = prop(message, "status")?;
        if ["streaming", "processing", "failed"].iter().any(|blocked| is_str(status, blocked)) {
            continue;
        }
        let kept = slice16(content, -remaining, None);
        let kept_len = len16(&kept) as i64;
        if !kept.is_empty() {
            rows.insert(0, json!({ "role": as_str(role), "content": kept }));
        }
        remaining -= kept_len;
        if remaining <= 0 {
            break;
        }
    }
    if rows.is_empty() {
        return Err(throw("project_authoring_history_unavailable"));
    }
    Ok(json!({ "rows": rows }))
}

/// The members of `new Set(linkedIds)`: `undefined`/`null` is empty, a string iterates
/// by code point, anything else that is not an array is a TypeError.
fn linked_set(value: Option<&Value>) -> Result<Vec<Value>, Fault> {
    let members: Vec<Value> = match value {
        None | Some(Value::Null) => Vec::new(),
        Some(Value::Array(items)) => items.clone(),
        Some(Value::String(text)) => text.chars().map(|c| Value::from(c.to_string())).collect(),
        Some(_) => return Err(Fault::Malformed("bad_field:linkedIds".to_owned())),
    };
    Ok(members)
}

/// A required string field sliced to `limit` UTF-16 units (`text.slice(0, limit)`).
fn sliced(value: Option<&Value>, name: &str, limit: i64) -> Result<String, Fault> {
    Ok(slice16(req_str(value, name)?, 0, Some(limit)))
}

/// `projectAuthoringCatalog`: focuses plus the linked workflows, or `null` when the
/// workflow catalog is unavailable while workflows are linked or it exceeds 40 entries.
pub(super) fn authoring_catalog(input: &Value) -> Outcome {
    let root = Some(input);
    let linked = linked_set(prop(root, "linkedIds")?)?;
    let workflows_ok = truthy(prop(root, "workflowsOk")?);
    if !workflows_ok && !linked.is_empty() {
        return Ok(json!({ "catalog": null }));
    }
    let mut catalog: Vec<Value> = Vec::new();
    for focus in req_array(prop(root, "focuses")?, "focuses")? {
        let focus = Some(focus);
        let mut entry = Map::new();
        for field in ["kind", "id", "title", "summary", "revision"] {
            put(&mut entry, field, prop(focus, field)?);
        }
        catalog.push(Value::Object(entry));
    }
    if workflows_ok {
        for item in req_array(prop(root, "workflows")?, "workflows")? {
            let item = Some(item);
            let id = prop(item, "id")?;
            if !linked.iter().any(|member| strict_eq(Some(member), id)) || !is_integer(prop(item, "version")?) {
                continue;
            }
            let summary_source = match prop(item, "description")? {
                None | Some(Value::Null) => match prop(item, "trigger_summary")? {
                    None | Some(Value::Null) => None,
                    other => other,
                },
                other => other,
            };
            let summary = match summary_source {
                None => String::new(),
                some => sliced(some, "summary", 2_000)?,
            };
            let mut entry = Map::new();
            entry.insert("kind".to_owned(), Value::from("workflow"));
            put(&mut entry, "id", id);
            entry.insert("title".to_owned(), Value::from(sliced(prop(item, "title")?, "title", 200)?));
            entry.insert("summary".to_owned(), Value::from(summary));
            let version = to_number(prop(item, "version")?);
            entry.insert("revision".to_owned(), Value::from(number_to_string(version)));
            catalog.push(Value::Object(entry));
        }
    }
    Ok(json!({ "catalog": if catalog.len() > MAX_AUTHORING_CATALOG { Value::Null } else { Value::Array(catalog) } }))
}
