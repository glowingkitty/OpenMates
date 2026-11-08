//! Task record views and key-envelope choice (shared Rust core `work` op, slice 2).
//!
//! spec: specifications/features/tasks#tasks.content.client-encrypted
//!
//! Mirrors `taskKeyEnvelope`, `decryptTask`, `workflowRunTaskProjection`,
//! `decryptTaskActivityEntry` and the dependency mapping of the web
//! `userTaskService.ts`. The page unwraps the task key and decrypts every
//! ciphertext member itself; views omit `encrypted` (the page reattaches it).
//! Parity: `tasks_ts_vectors.json` (`workTaskVectors.test.ts`).

use serde_json::{Map, Value, json};

use super::Fallback::{Null, Str, Zero};
use super::Src::{Or, Raw, Text};
use super::{Decision, Src, copy, member, object, or, project, refusal, string_array, task_bodies, template, text, truthy};

/// Runs one `task*` op: the views here, every path/body op in [`task_bodies`].
///
/// # Errors
/// `unknown_op:<name>` or a malformed-input error; TS refusals come back as `{"error"}`.
pub(crate) fn run(op: &str, input: &Value) -> Decision {
    match op {
        "taskKeyEnvelope" => key_envelope(input),
        "taskView" => task_view(input),
        "taskWorkflowRunView" => Ok(Value::Object(workflow_run_view(object(input, "record")?))),
        "taskActivityView" => activity_view(input),
        "taskDependenciesView" => dependencies_view(input),
        _ => task_bodies::run(op, input),
    }
}

/// `taskKeyEnvelope(record, teamId)`: the personal wrapped key, or the one
/// Team wrapper for the active Team. The page hashes the Team id (SHA-256)
/// and unwraps the envelope; a Team task without exactly one valid wrapper
/// (`team`, matching hash, integer epoch >= 1, non-empty key) fails closed.
fn key_envelope(input: &Value) -> Decision {
    let record = object(input, "record")?;
    if !truthy(input.get("team_id")) {
        return Ok(json!({ "envelope": or(record, "encrypted_task_key", Value::Null) }));
    }
    let hash = member(input, "team_hash")?;
    let wrappers: &[Value] = match record.get("key_wrappers") {
        None | Some(Value::Null) => &[],
        Some(Value::Array(items)) => items.as_slice(),
        Some(_) => return Err("bad_field:record.key_wrappers".into()),
    };
    let valid: Vec<&Value> = wrappers
        .iter()
        .filter(|wrapper| {
            let epoch = wrapper.get("team_key_epoch").and_then(Value::as_f64);
            wrapper.get("key_type") == Some(&json!("team"))
                && wrapper.get("hashed_team_id") == Some(hash)
                && epoch.is_some_and(|e| e.is_finite() && e.fract() == 0.0 && e >= 1.0)
                && wrapper.get("encrypted_task_key").and_then(Value::as_str).is_some_and(|key| !key.is_empty())
        })
        .collect();
    if valid.len() != 1 {
        let message = format!("Team task {} has no unique Team key wrapper", template(record.get("task_id")));
        return Ok(refusal(&message));
    }
    Ok(json!({ "envelope": valid[0]["encrypted_task_key"] }))
}

/// `decryptTask` after the key unwrap; `team_id` is the active Team for a Team row, else null.
fn task_view(input: &Value) -> Decision {
    let record = object(input, "record")?;
    let fields = object(input, "fields")?;
    // TS parses tags leniently: any JSON value is kept and malformed text reads
    // as `[]` (its try/catch), before the version check.
    let tags_text = text(record, fields, "encrypted_tags")?;
    let tags = if tags_text.is_empty() {
        json!([])
    } else {
        serde_json::from_str::<Value>(tags_text).unwrap_or_else(|_| json!([]))
    };
    if !record.get("version").is_some_and(Value::is_number) {
        return Ok(refusal(&format!("Task {} is missing version.", template(record.get("task_id")))));
    }
    let external = if truthy(record.get("external_chat_provider")) && truthy(record.get("encrypted_external_chat_id")) {
        json!({
            "provider": record["external_chat_provider"],
            "id": text(record, fields, "encrypted_external_chat_id")?,
            "title": text(record, fields, "encrypted_external_chat_title")?,
        })
    } else {
        Value::Null
    };
    // Deliberate deviation: malformed linked-Project JSON is refused with this
    // message, where the TS `JSON.parse` throws an engine-worded SyntaxError.
    let linked = match string_array(text(record, fields, "encrypted_linked_project_ids")?, "Task linked Project ids") {
        Ok(ids) => ids,
        Err(refused) => return Ok(refused),
    };
    let mut out = project(record, fields, TASK)?;
    out.insert("teamId".into(), input.get("team_id").cloned().unwrap_or(Value::Null));
    out.insert("tags".into(), tags);
    out.insert("externalChat".into(), external);
    out.insert("linkedProjectIds".into(), linked);
    Ok(Value::Object(out))
}

const TASK: &[(&str, Src)] = &[
    ("task_id", Raw("task_id")),
    ("title", Text("encrypted_title")),
    ("description", Text("encrypted_description")),
    ("latestInstruction", Text("encrypted_latest_instruction")),
    ("status", Raw("status")),
    ("assigneeType", Raw("assignee_type")),
    ("assigneeIdentity", Or("assignee_identity", Null)),
    ("primaryChatId", Or("primary_chat_id", Null)),
    ("planId", Or("plan_id", Null)),
    ("dueAt", Or("due_at", Null)),
    ("priority", Or("priority", Zero)),
    ("position", Or("position", Zero)),
    ("version", Raw("version")),
    ("createdAt", Raw("created_at")),
    ("updatedAt", Raw("updated_at")),
    ("blockedReasonCode", Or("blocked_reason_code", Null)),
    ("blockedReason", Text("encrypted_blocked_reason")),
    ("aiExecutionState", Or("ai_execution_state", Null)),
];

/// `workflowRunTaskProjection`: a read-only board row for a workflow run.
fn workflow_run_view(record: &Map<String, Value>) -> Map<String, Value> {
    let mut out = Map::new();
    copy(&mut out, "task_id", record, "task_id");
    copy(&mut out, "source", record, "source");
    copy(&mut out, "projectionKind", record, "projection_kind");
    copy(&mut out, "workflowId", record, "workflow_id");
    out.insert("workflowRunId".into(), or(record, "workflow_run_id", Value::Null));
    out.insert("triggerId".into(), or(record, "trigger_id", Value::Null));
    // `record.title || record.label`: a falsy title falls back to the label.
    if truthy(record.get("title")) {
        copy(&mut out, "title", record, "title");
    } else {
        copy(&mut out, "title", record, "label");
    }
    out.insert("description".into(), or(record, "blocked_message", json!("")));
    out.insert("tags".into(), json!([]));
    out.insert("latestInstruction".into(), json!(""));
    copy(&mut out, "status", record, "status");
    out.insert("assigneeType".into(), json!("user"));
    out.insert("assigneeIdentity".into(), Value::Null);
    out.insert("primaryChatId".into(), Value::Null);
    out.insert("linkedProjectIds".into(), json!([]));
    out.insert("dueAt".into(), or(record, "due_at", Value::Null));
    out.insert("priority".into(), json!(0));
    copy(&mut out, "position", record, "position");
    out.insert("version".into(), json!(0));
    copy(&mut out, "canCancel", record, "can_cancel");
    out.insert("canDelete".into(), json!(truthy(record.get("can_delete"))));
    out.insert("readOnly".into(), json!(true));
    out
}

/// `decryptTaskActivityEntry` without the decrypts: the plain entry plus the
/// ordered AAD-bound decrypts the page performs with the task key. Each
/// decrypt names the entry member, the ciphertext member, the AES-GCM
/// associated data (`task_activity_comment|task_activity_embed_keys:<task>:<entry>:v1`)
/// and the error text the page throws when it fails. Only comments decrypt.
fn activity_view(input: &Value) -> Decision {
    let task_id = template(Some(member(input, "task_id")?));
    let record = object(input, "record")?;
    let mut entry = project(record, &Map::new(), ACTIVITY)?;
    let author = or(record, "author_hash", or(record, "actor_hash", Value::Null));
    entry.insert("authorHash".into(), author);
    let kind = record.get("kind").and_then(Value::as_str);
    if kind == Some("tombstone") {
        entry.insert("embedRefs".into(), json!([]));
    } else {
        copy(&mut entry, "embedRefs", record, "embed_refs");
    }
    let mut decrypts = Vec::new();
    if kind == Some("comment") {
        let entry_id = template(record.get("entry_id"));
        if !truthy(record.get("encrypted_message")) {
            return Ok(refusal(&format!("Task Activity entry {entry_id} is missing encrypted content")));
        }
        decrypts.push(json!({
            "name": "message", "member": "encrypted_message",
            "aad": format!("task_activity_comment:{task_id}:{entry_id}:v1"),
            "failure": format!("Could not decrypt Task Activity entry {entry_id}"),
        }));
        if truthy(record.get("encrypted_embed_key_material")) {
            decrypts.push(json!({
                "name": "embedKeyMaterial", "member": "encrypted_embed_key_material",
                "aad": format!("task_activity_embed_keys:{task_id}:{entry_id}:v1"),
                "failure": format!("Could not decrypt Task Activity embed keys {entry_id}"),
            }));
        }
    }
    Ok(json!({ "entry": entry, "decrypts": decrypts }))
}

const ACTIVITY: &[(&str, Src)] = &[
    ("entryId", Raw("entry_id")),
    ("taskId", Raw("task_id")),
    ("kind", Raw("kind")),
    ("actorType", Raw("actor_type")),
    ("actorIdentity", Or("actor_identity", Null)),
    ("actorHash", Or("actor_hash", Null)),
    ("actorDisplayName", Or("actor_display_name", Null)),
    ("actorProfileImageUrl", Or("actor_profile_image_url", Null)),
    ("eventType", Raw("event_type")),
    ("sourceSurface", Raw("source_surface")),
    ("previousStatus", Or("previous_status", Null)),
    ("nextStatus", Or("next_status", Null)),
    ("createdAt", Raw("created_at")),
    ("deletedAt", Or("deleted_at", Null)),
    ("deletedByHash", Or("deleted_by_hash", Null)),
    ("deletedByDisplayName", Or("deleted_by_display_name", Null)),
];

const DEPENDENCY: &[(&str, Src)] = &[
    ("targetRef", Raw("target_ref")),
    ("targetKind", Raw("target_kind")),
    ("targetId", Raw("target_id")),
    ("targetStatus", Or("target_status", Str("unknown"))),
    ("satisfied", Raw("satisfied")),
];

/// `listUserTaskDependencies` mapping (`edge_id ?? target_ref`, unknown status default).
fn dependencies_view(input: &Value) -> Decision {
    let items = member(input, "dependencies")?.as_array().ok_or("bad_field:dependencies")?;
    let mut out = Vec::with_capacity(items.len());
    for item in items {
        let dependency = item.as_object().ok_or("bad_field:dependencies")?;
        let mut view = Map::new();
        match dependency.get("edge_id") {
            None | Some(Value::Null) => copy(&mut view, "edgeId", dependency, "target_ref"),
            Some(edge) => {
                view.insert("edgeId".into(), edge.clone());
            }
        }
        view.extend(project(dependency, &Map::new(), DEPENDENCY)?);
        out.push(Value::Object(view));
    }
    Ok(Value::Array(out))
}
