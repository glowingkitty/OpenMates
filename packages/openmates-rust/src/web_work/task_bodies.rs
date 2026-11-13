//! Task request paths and bodies (shared Rust core `work` op, slice 2).
//!
//! spec: specifications/features/tasks#tasks.content.client-encrypted
//!
//! Mirrors the request building of the web `userTaskService.ts`: list/item/
//! activity/delete paths with the Team context route, external-chat checks,
//! and every body as ordered [`Body`] steps. Plaintexts leave only as
//! `encrypt` steps the page seals with the task key (`"task"`); Activity steps
//! carry their AES-GCM associated data. The wrapped task key, the external
//! chat blind index (HMAC of the master key) and the key wrappers stay page `slot`s.

use serde_json::{Map, Value, json};

use super::plan_bodies::context_route;
use super::{
    Body, Decision, defined, defined_text, input_text, input_text_or_empty, member, object, or, refusal, search_params,
    template, truthy,
};
use crate::web_apps::{encode_uri_component, js_string};

const BOTH_CHATS: &str = "A task cannot use both native chat and external chat context.";
const EXTERNAL_MEMBERS: [&str; 4] =
    ["external_chat_provider", "external_chat_lookup_hash", "encrypted_external_chat_id", "encrypted_external_chat_title"];

impl Body {
    /// A member the page encrypts with the named key and AES-GCM associated data
    /// (wire step `{"encrypt": text, "key": role, "aad": aad}`).
    fn encrypt_aad(&mut self, name: &str, text: &str, key: &str, aad: &str) {
        self.0.push(json!([name, { "encrypt": text, "key": key, "aad": aad }]));
    }
}

/// Runs one `task*Path` / `task*Body` op.
///
/// # Errors
/// `unknown_op:<name>` or a malformed-input error; TS refusals come back as `{"error"}`.
pub(crate) fn run(op: &str, input: &Value) -> Decision {
    match op {
        "taskListPath" => list_path(input),
        "taskItemPath" => item_path(input, ""),
        "taskKeyWrappersPath" => key_wrappers_path(input),
        "taskDependenciesPath" => item_path(input, "/dependencies"),
        "taskActivityPath" => {
            let team = first_defined(input, "team_id", "task_team_id");
            Ok(json!(activity_path(input, team, input.get("cursor"))?))
        }
        "taskActivityDeletePath" => activity_delete_path(input),
        "taskDeletePath" => delete_path(input),
        "taskWorkflowCancelPath" => workflow_cancel_path(input),
        "taskCreateBody" => create(input),
        "taskUpdateBody" => update(input),
        "taskActionBody" => action(input),
        "taskBlockBody" => block(input),
        "taskReorderBody" => reorder(input),
        "taskStartAiBody" => start_ai(input),
        "taskExtractBody" => extract(input),
        "taskKeyWrappersAddBody" => key_wrappers_add(input),
        "taskActivityCreateBody" => activity_create(input),
        _ => Err(format!("unknown_op:{op}")),
    }
}

/// JS `a ?? b` over two optional input members (absent and `null` are nullish).
fn first_defined<'a>(input: &'a Value, first: &str, second: &str) -> Option<&'a Value> {
    match input.get(first) {
        None | Some(Value::Null) => input.get(second),
        value => value,
    }
}

fn timestamp(input: &Value) -> Result<Value, String> {
    member(input, "timestamp").cloned()
}

/// `assertExternalChatContext`: codex or claude, an id, and a session UUID for Claude Code.
fn external_chat_refusal(context: &Value) -> Option<Value> {
    let provider = context.get("provider");
    let name = provider.and_then(Value::as_str);
    if !matches!(name, Some("codex" | "claude")) {
        let message = format!("Unsupported external chat provider '{}'. Expected codex or claude.", template(provider));
        return Some(refusal(&message));
    }
    if !truthy(context.get("id")) {
        return Some(refusal("External chat id is required."));
    }
    if name == Some("claude") && !is_session_uuid(&template(context.get("id"))) {
        return Some(refusal("Claude Code external chat ids must be session UUIDs."));
    }
    None
}

/// `/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i`.
fn is_session_uuid(id: &str) -> bool {
    let groups: Vec<&str> = id.split('-').collect();
    groups.len() == 5
        && groups.iter().zip([8, 4, 4, 4, 12]).all(|(group, len)| {
            group.len() == len && group.bytes().all(|b| b.is_ascii_hexdigit())
        })
}

/// The shared create/update chat checks; `Some` is the refusal to answer.
fn chat_context_refusal(primary: Option<&Value>, external: Option<&Value>) -> Option<Value> {
    if truthy(primary) && external.is_some() {
        return Some(refusal(BOTH_CHATS));
    }
    external.and_then(external_chat_refusal)
}

/// The truthy `externalChat` member as an object (the checks have passed).
fn external_of(record: &Map<String, Value>) -> Option<&Value> {
    record.get("externalChat").filter(|value| truthy(Some(value)))
}

/// The external-chat steps: provider, the page's blind index slot and the sealed id/title.
fn external_steps(body: &mut Body, context: &Value) -> Result<(), String> {
    let context = context.as_object().ok_or("bad_field:input.externalChat")?;
    body.raw("external_chat_provider", context, "provider");
    body.slot("external_chat_lookup_hash");
    body.encrypt("encrypted_external_chat_id", input_text(context, "id")?, "task");
    body.encrypt("encrypted_external_chat_title", input_text(context, "title")?, "task");
    Ok(())
}

/// `listTaskBoardItems` path: `/v1/user-tasks${buildQuery(filters)}`; the
/// page sends the external chat blind index it computed for `externalChat`.
fn list_path(input: &Value) -> Decision {
    let filters = object(input, "filters")?;
    let mut pairs: Vec<(&str, String)> = Vec::new();
    for (key, name) in [("teamId", "team_id"), ("status", "status"), ("chatId", "chat_id"), ("projectId", "project_id")] {
        if truthy(filters.get(key)) {
            pairs.push((name, template(filters.get(key))));
        }
    }
    if truthy(filters.get("externalChat")) {
        pairs.push(("external_chat_provider", template(filters["externalChat"].get("provider"))));
        pairs.push(("external_chat_lookup_hash", template(Some(member(input, "external_chat_lookup_hash")?))));
    }
    let query = search_params(&pairs);
    let path = if query.is_empty() { "/v1/user-tasks".to_owned() } else { format!("/v1/user-tasks?{query}") };
    Ok(json!(path))
}

/// `/v1/user-tasks/${encodeURIComponent(taskId)}<suffix>` under the optional Team context.
fn item_path(input: &Value, suffix: &str) -> Decision {
    let id = template(Some(member(input, "task_id")?));
    let path = format!("/v1/user-tasks/{}{suffix}", encode_uri_component(&id));
    Ok(json!(context_route(path, input.get("team_id"))))
}

/// `listUserTaskKeyWrappers` path (the TS template leaves the id unencoded).
fn key_wrappers_path(input: &Value) -> Decision {
    let path = format!("/v1/user-tasks/{}/key-wrappers", template(Some(member(input, "task_id")?)));
    Ok(json!(context_route(path, input.get("team_id"))))
}

/// `taskActivityPath(taskId, teamId, cursor)`: 200-entry pages, optional Team and cursor.
fn activity_path(input: &Value, team: Option<&Value>, cursor: Option<&Value>) -> Result<String, String> {
    let id = template(Some(member(input, "task_id")?));
    let mut pairs: Vec<(&str, String)> = vec![("limit", "200".into())];
    if truthy(team) {
        pairs.push(("team_id", template(team)));
    }
    if truthy(cursor) {
        pairs.push(("cursor", template(cursor)));
    }
    Ok(format!("/v1/user-tasks/{}/activity?{}", encode_uri_component(&id), search_params(&pairs)))
}

/// `deleteUserTaskActivity` path (`teamId ?? task.teamId`).
fn activity_delete_path(input: &Value) -> Decision {
    let id = template(Some(member(input, "task_id")?));
    let entry = template(Some(member(input, "entry_id")?));
    let team = first_defined(input, "team_id", "task_team_id");
    let query = if truthy(team) { search_params(&[("team_id", template(team))]) } else { String::new() };
    let query = if query.is_empty() { query } else { format!("?{query}") };
    Ok(json!(format!("/v1/user-tasks/{}/activity/{}{query}", encode_uri_component(&id), encode_uri_component(&entry))))
}

/// `deleteUserTask` path: the version, plus the Team for a non-workflow row.
fn delete_path(input: &Value) -> Decision {
    let task = object(input, "task")?;
    let mut pairs: Vec<(&str, String)> = vec![("version", template(task.get("version")))];
    let workflow = task.get("source") == Some(&json!("workflow_run"));
    if !workflow && truthy(task.get("teamId")) {
        pairs.push(("team_id", template(task.get("teamId"))));
    }
    Ok(json!(format!("/v1/user-tasks/{}?{}", template(task.get("task_id")), search_params(&pairs))))
}

/// `cancelWorkflowRunTaskProjection` path (a projection without a run id is refused).
fn workflow_cancel_path(input: &Value) -> Decision {
    let run = input.get("workflow_run_id");
    if !truthy(run) {
        return Ok(refusal("Workflow run projection has no run id to cancel"));
    }
    let workflow = template(Some(member(input, "workflow_id")?));
    let path = format!(
        "/v1/workflows/{}/runs/{}/cancel",
        encode_uri_component(&workflow),
        encode_uri_component(&template(run))
    );
    Ok(json!(path))
}

/// `createUserTask`: the chat checks, then every member in the TS literal order.
fn create(input: &Value) -> Decision {
    let task = object(input, "input")?;
    let external = external_of(task);
    if let Some(refused) = chat_context_refusal(task.get("primaryChatId"), external) {
        return Ok(refused);
    }
    let team = input.get("team_id");
    let at = timestamp(input)?;
    let openmates = task.get("assigneeType") == Some(&json!("openmates"));
    let primary = or(task, "primaryChatId", Value::Null);
    let linked = or(task, "linkedProjectIds", json!([]));
    let mut body = Body::default();
    body.value("task_id", member(input, "task_id")?.clone());
    body.slot("encrypted_task_key");
    if truthy(team) {
        body.value("team_id", team.cloned().unwrap_or(Value::Null));
    }
    body.encrypt("encrypted_title", input_text(task, "title")?, "task");
    body.encrypt("encrypted_description", input_text_or_empty(task, "description")?, "task");
    body.encrypt_input("encrypted_tags", "tags", "task");
    body.encrypt_input("encrypted_linked_project_ids", "linkedProjectIds", "task");
    let status = if openmates && !truthy(task.get("dueAt")) { "in_progress" } else { "todo" };
    body.value("status", or(task, "status", json!(status)));
    body.value("assignee_type", or(task, "assigneeType", json!("user")));
    let identity = if openmates { json!("openmates") } else { Value::Null };
    body.value("assignee_identity", or(task, "assigneeIdentity", identity));
    body.value("assignee_hash", or(task, "assigneeHash", Value::Null));
    body.value("primary_chat_id", primary.clone());
    if let Some(context) = external {
        external_steps(&mut body, context)?;
    }
    body.value("linked_project_ids", linked.clone());
    body.value("due_at", or(task, "dueAt", Value::Null));
    body.value("priority", or(task, "priority", json!(0)));
    body.value("position", at.clone());
    body.value("version", json!(1));
    body.value("created_at", at.clone());
    body.value("updated_at", at);
    body.slot("key_wrappers");
    let mut extra = Map::new();
    extra.insert("wrapper_chat_id".into(), primary);
    extra.insert("wrapper_project_ids".into(), linked);
    Ok(body.request("/v1/user-tasks".into(), "POST", extra))
}

/// `updateUserTask`: defined patch members only, chat-context switches and a
/// key-wrapper rebuild when links or chat context change. Repeated step names
/// re-assign the same body member (JS keeps its first position).
fn update(input: &Value) -> Decision {
    let task = object(input, "task")?;
    let patch = object(input, "patch")?;
    let external = external_of(patch);
    if let Some(refused) = chat_context_refusal(patch.get("primaryChatId"), external) {
        return Ok(refused);
    }
    let mut body = Body::default();
    body.raw("version", task, "version");
    body.value("updated_at", timestamp(input)?);
    for (name, key) in [("encrypted_title", "title"), ("encrypted_description", "description")] {
        if let Some(text) = defined_text(patch, key)? {
            body.encrypt(name, text, "task");
        }
    }
    for (name, key) in [("encrypted_tags", "tags"), ("encrypted_linked_project_ids", "linkedProjectIds")] {
        match patch.get(key) {
            None => {}
            // `JSON.stringify(null)`; the page's `encrypt_input` would read `null ?? []`.
            Some(Value::Null) => body.encrypt(name, "null", "task"),
            Some(_) => body.encrypt_input(name, key, "task"),
        }
    }
    body.raw("status", patch, "status");
    if defined(patch, "assigneeType") {
        body.raw("assignee_type", patch, "assigneeType");
        let identity = if patch["assigneeType"] == json!("openmates") { json!("openmates") } else { Value::Null };
        body.value("assignee_identity", or(patch, "assigneeIdentity", identity));
    }
    body.raw("assignee_hash", patch, "assigneeHash");
    if defined(patch, "primaryChatId") {
        body.raw("primary_chat_id", patch, "primaryChatId");
        for name in EXTERNAL_MEMBERS {
            body.value(name, Value::Null);
        }
    }
    if let Some(context) = external {
        body.value("primary_chat_id", Value::Null);
        external_steps(&mut body, context)?;
    }
    body.raw("linked_project_ids", patch, "linkedProjectIds");
    let mut extra = Map::new();
    if defined(patch, "linkedProjectIds") || defined(patch, "primaryChatId") || defined(patch, "externalChat") {
        let chat = if external.is_some() {
            Value::Null
        } else if defined(patch, "primaryChatId") {
            patch["primaryChatId"].clone()
        } else {
            or(task, "primaryChatId", Value::Null)
        };
        let linked =
            if defined(patch, "linkedProjectIds") { patch["linkedProjectIds"].clone() } else { member_of(task, "linkedProjectIds")? };
        if linked.is_null() {
            // TS builds the wrappers from `null` and reads `null.length`.
            return Ok(refusal("Cannot read properties of null (reading 'length')"));
        }
        extra.insert("wrapper_chat_id".into(), chat);
        extra.insert("wrapper_project_ids".into(), linked);
        body.slot("key_wrappers");
    }
    body.raw("due_at", patch, "dueAt");
    body.raw("priority", patch, "priority");
    let path = context_route(format!("/v1/user-tasks/{}", template(task.get("task_id"))), task.get("teamId"));
    Ok(body.request(path, "PATCH", extra))
}

fn member_of(record: &Map<String, Value>, key: &str) -> Result<Value, String> {
    record.get(key).cloned().ok_or_else(|| format!("missing_field:task.{key}"))
}

/// `/v1/user-tasks/${task.task_id}<suffix>` (the TS template, unencoded).
fn task_path(task: &Map<String, Value>, suffix: &str) -> String {
    format!("/v1/user-tasks/{}{suffix}", template(task.get("task_id")))
}

/// `completeUserTask` / `unblockUserTask` / `skipUserTask`.
fn action(input: &Value) -> Decision {
    let task = object(input, "task")?;
    let action = member(input, "action")?.as_str().ok_or("bad_field:action")?;
    if !matches!(action, "complete" | "unblock" | "skip") {
        return Err("bad_field:action".into());
    }
    let mut body = Body::default();
    body.raw("version", task, "version");
    body.raw("team_id", task, "teamId");
    Ok(body.request(task_path(task, &format!("/{action}")), "POST", Map::new()))
}

/// `blockUserTask`: a non-empty reason is sealed with the task key.
fn block(input: &Value) -> Decision {
    let task = object(input, "task")?;
    let mut body = Body::default();
    body.raw("version", task, "version");
    body.raw("team_id", task, "teamId");
    body.value("blocked_reason_code", member(input, "blocked_reason_code")?.clone());
    if let Some(reason) = input.as_object().and_then(|i| i.get("blocked_reason")).filter(|r| truthy(Some(r))) {
        body.encrypt("encrypted_blocked_reason", reason.as_str().ok_or("bad_field:blocked_reason")?, "task");
    }
    Ok(body.request(task_path(task, "/block"), "POST", Map::new()))
}

/// `reorderUserTasks`: one workspace per batch; nullish before/after ids are dropped.
fn reorder(input: &Value) -> Decision {
    let moves = member(input, "moves")?.as_array().ok_or("bad_field:moves")?;
    let team_of = |entry: &Value| entry.get("team_id").cloned().unwrap_or(Value::Null);
    let team = moves.first().map_or(Value::Null, team_of);
    if moves.iter().any(|entry| team_of(entry) != team) {
        return Ok(refusal("Cannot reorder tasks across workspaces"));
    }
    let mut out = Vec::with_capacity(moves.len());
    for entry in moves {
        let entry = entry.as_object().ok_or("bad_field:moves")?;
        let mut item = Map::new();
        super::copy(&mut item, "task_id", entry, "task_id");
        for (name, key) in [("before_task_id", "beforeTaskId"), ("after_task_id", "afterTaskId")] {
            if let Some(id) = entry.get(key).filter(|id| !id.is_null()) {
                item.insert(name.into(), id.clone());
            }
        }
        super::copy(&mut item, "status", entry, "status");
        super::copy(&mut item, "position", entry, "position");
        super::copy(&mut item, "version", entry, "version");
        out.push(Value::Object(item));
    }
    let mut body = Body::default();
    body.value("team_id", team);
    body.value("moves", Value::Array(out));
    Ok(body.request("/v1/user-tasks/reorder".into(), "POST", Map::new()))
}

/// `startUserTaskWithAI`: the plaintext prompt context the user chose to share.
fn start_ai(input: &Value) -> Decision {
    let task = object(input, "task")?;
    let linked = task.get("linkedProjectIds").and_then(Value::as_array).ok_or("bad_field:task.linkedProjectIds")?;
    let mut body = Body::default();
    body.raw("version", task, "version");
    body.raw("team_id", task, "teamId");
    body.value("updated_at", timestamp(input)?);
    body.raw("linked_project_ids", task, "linkedProjectIds");
    if truthy(task.get("primaryChatId")) {
        body.raw("primary_chat_id", task, "primaryChatId");
        body.raw("plaintext_title", task, "title");
        body.raw("plaintext_description", task, "description");
        body.raw("plaintext_latest_instruction", task, "latestInstruction");
    }
    if truthy(task.get("externalChat")) {
        body.value("primary_chat_id", Value::Null);
        for name in EXTERNAL_MEMBERS {
            body.value(name, Value::Null);
        }
    }
    if !linked.is_empty() {
        // `Array.prototype.join` writes nullish items as "".
        let ids: Vec<String> = linked.iter().map(|id| if id.is_null() { String::new() } else { js_string(id) }).collect();
        body.value("plaintext_project_context", json!(format!("Linked projects: {}", ids.join(", "))));
    }
    Ok(body.request(task_path(task, "/start-ai"), "POST", Map::new()))
}

/// `extractUserTaskProposals`.
fn extract(input: &Value) -> Decision {
    let request = object(input, "input")?;
    let mut body = Body::default();
    body.raw("corrected_text", request, "correctedText");
    body.value("mode", or(request, "mode", json!("create")));
    body.value("context_chat_id", or(request, "contextChatId", Value::Null));
    body.value("project_ids", or(request, "projectIds", json!([])));
    Ok(body.request("/v1/user-tasks/extract".into(), "POST", Map::new()))
}

/// `addUserTaskKeyWrappers` (wrappers are page-made ciphertext, passed through).
fn key_wrappers_add(input: &Value) -> Decision {
    let id = template(Some(member(input, "task_id")?));
    let mut body = Body::default();
    body.value("version", member(input, "version")?.clone());
    body.value("key_wrappers", member(input, "key_wrappers")?.clone());
    Ok(body.request(format!("/v1/user-tasks/{id}/key-wrappers"), "POST", Map::new()))
}

/// `createUserTaskActivity`: the comment (and optional embed keys) sealed with
/// the task key under `task_activity_*:<task>:<entry>:v1` associated data.
fn activity_create(input: &Value) -> Decision {
    let comment = object(input, "input")?;
    let task_id = template(Some(member(input, "task_id")?));
    let entry_id = or(comment, "entryId", member(input, "fresh_id")?.clone());
    let entry = template(Some(&entry_id));
    let mut body = Body::default();
    body.value("entry_id", entry_id);
    let aad = format!("task_activity_comment:{task_id}:{entry}:v1");
    body.encrypt_aad("encrypted_message", input_text(comment, "message")?, "task", &aad);
    if truthy(comment.get("embedKeyMaterial")) {
        let aad = format!("task_activity_embed_keys:{task_id}:{entry}:v1");
        body.encrypt_aad("encrypted_embed_key_material", input_text(comment, "embedKeyMaterial")?, "task", &aad);
    }
    body.value("embed_refs", or(comment, "embedRefs", json!([])));
    body.value("created_at", or(comment, "createdAt", timestamp(input)?));
    let path = activity_path(input, first_defined(input, "team_id", "task_team_id"), None)?;
    Ok(body.request(path, "POST", Map::new()))
}
