//! Workflow request paths and bodies (shared Rust core `work` op, Workflows slice).
//!
//! spec: specifications/features/workflows#workflows.execution.lifecycle-visible
//!
//! Mirrors the request building of the web `workflowWorkspaceStore.ts`,
//! `workflowTemplateService.ts`, `workflowInputService.ts`,
//! `appsWorkflowLibraryService.ts` and `workflowRunPreviewMetadata.ts` as
//! paths and ordered [`Body`] steps. Members only the page holds (graphs, run
//! inputs, ciphertexts, the owner-wrapped template key, the encrypted short URL)
//! are page `slot`s, so nested key order is the page's own and no key bytes cross.

use serde_json::{Map, Value, json};

use super::workflow_template::PROJECTION_SCHEMA_VERSION;
use super::{Body, Decision, defined, member, object, or, refusal, search_params, template, truthy};
use crate::web_apps::encode_uri_component;

/// Runs one workflow path or body op.
///
/// # Errors
/// `unknown_op:<name>` or a malformed-input error; TS refusals come back as `{"error"}`.
pub(crate) fn run(op: &str, input: &Value) -> Decision {
    match op {
        "workflowPath" => workspace_path(input).map(Value::String),
        "workflowTemplatePath" => template_path(input).map(Value::String),
        "workflowInputPath" => input_path(input).map(Value::String),
        "workflowAppsLibraryPath" => Ok(Value::String(apps_library_path(input))),
        "workflowRunPreviewPaths" => Ok(run_preview_paths(input)),
        "workflowCreateBody" => create(input),
        "workflowRunBody" => run_body(input),
        "workflowTemplateUpsertBody" => template_upsert(input),
        "workflowTemplateShortUrlBody" => short_url(input),
        "workflowTemplateBindingBody" => template_binding(input),
        "workflowInputBody" => instruction(input),
        _ => Err(format!("unknown_op:{op}")),
    }
}

/// `encodeURIComponent(<input member>)` (a missing member reads `undefined`, as in TS).
fn enc(input: &Value, name: &str) -> String {
    encode_uri_component(&template(input.get(name)))
}

/// `/v1/workflows/${encodeURIComponent(workflowId)}`.
fn workflow_root(input: &Value) -> String {
    format!("/v1/workflows/{}", enc(input, "workflow_id"))
}

fn route(input: &Value) -> Result<&str, String> {
    member(input, "route")?.as_str().ok_or_else(|| "bad_field:route".to_owned())
}

/// The `workflowWorkspaceStore` request paths.
fn workspace_path(input: &Value) -> Result<String, String> {
    let root = workflow_root(input);
    Ok(match route(input)? {
        "list" => "/v1/workflows".to_owned(),
        "file_import" => "/v1/workflows/file-import".to_owned(),
        "detail" => root,
        "runs" => format!("{root}/runs"),
        "versions" => format!("{root}/versions"),
        "version" => format!("{root}/versions/{}", enc(input, "version_id")),
        "restore" => format!("{root}/versions/{}/restore", enc(input, "version_id")),
        "toggle" => format!("{root}/{}", if truthy(input.get("enabled")) { "enable" } else { "disable" }),
        "save_reusable" => format!("{root}/save-as-reusable"),
        "binding_complete" => format!("{root}/binding-requirements/complete"),
        "run" => format!("{root}/run"),
        "run_detail" => format!("{root}/runs/{}", enc(input, "run_id")),
        "cancel" => format!("{root}/runs/{}/cancel", enc(input, "run_id")),
        _ => return Err("bad_field:route".to_owned()),
    })
}

/// The `workflowTemplateService` request paths.
fn template_path(input: &Value) -> Result<String, String> {
    let projection = format!("{}/template-projection", workflow_root(input));
    Ok(match route(input)? {
        "projection" => projection,
        "revoke" => format!("{projection}/revoke"),
        "unrevoke" => format!("{projection}/unrevoke"),
        "public" => format!("/v1/workflows/template-projections/{}", enc(input, "template_id")),
        "short_url_delete" => format!("/v1/share/short-url/{}", enc(input, "token")),
        _ => return Err("bad_field:route".to_owned()),
    })
}

/// The `workflowInputService` session paths (`get`, `stop`, `undo`).
fn input_path(input: &Value) -> Result<String, String> {
    let root = format!("/v1/workflows/input/{}", enc(input, "session_id"));
    Ok(match route(input)? {
        "get" => root,
        "stop" => format!("{root}/stop"),
        "undo" => format!("{root}/undo"),
        _ => return Err("bad_field:route".to_owned()),
    })
}

/// `listAppsWorkflows`: `new URLSearchParams({ app_id, offset, limit })` plus `team_id` when set.
fn apps_library_path(input: &Value) -> String {
    let mut pairs = vec![
        ("app_id", template(input.get("app_id"))),
        ("offset", template(input.get("offset"))),
        ("limit", template(input.get("limit"))),
    ];
    if truthy(input.get("team_id")) {
        pairs.push(("team_id", template(input.get("team_id"))));
    }
    format!("/v1/workflows?{}", search_params(&pairs))
}

/// `loadWorkflowRunPreviewMetadata`: which owner-scoped reads are needed (`null` = already known).
fn run_preview_paths(input: &Value) -> Value {
    let provenance = input.get("provenance").cloned().unwrap_or(Value::Null);
    let root = format!("/v1/workflows/{}", enc(&provenance, "workflowId"));
    let workflow = if truthy(provenance.get("title")) { Value::Null } else { json!(root) };
    let run = if truthy(provenance.get("startedAt")) {
        Value::Null
    } else {
        json!(format!("{root}/runs/{}", enc(&provenance, "runId")))
    };
    json!({ "workflow": workflow, "run": run })
}

/// JS `a === b` between two JSON scalars (`undefined === undefined` is true).
fn same(a: Option<&Value>, b: Option<&Value>) -> bool {
    match (a, b) {
        (None, None) | (Some(Value::Null), Some(Value::Null)) => true,
        (Some(Value::String(x)), Some(Value::String(y))) => x == y,
        (Some(Value::Number(x)), Some(Value::Number(y))) => x.as_f64() == y.as_f64(),
        (Some(Value::Bool(x)), Some(Value::Bool(y))) => x == y,
        _ => false,
    }
}

/// `createWorkflow`: the workspace fence, then `POST /v1/workflows` (graph stays a page slot).
fn create(input: &Value) -> Decision {
    let record = object(input, "input")?;
    let context = input.get("context_team_id");
    let team_id = if defined(record, "teamId") { record.get("teamId") } else { context };
    if !same(team_id, context) {
        return Ok(refusal("The selected Project belongs to another workspace."));
    }
    let mut body = Body::default();
    for name in ["title", "description", "category", "icon"] {
        body.raw(name, record, name);
    }
    if defined(record, "graph") {
        body.slot("graph");
    }
    body.raw("enabled", record, "enabled");
    body.raw("run_content_retention", record, "runContentRetention");
    if let Some(team_id) = team_id {
        body.value("team_id", team_id.clone());
    }
    Ok(body.request("/v1/workflows".to_owned(), "POST", Map::new()))
}

/// `runWorkflow`: the run body (run inputs and output maps stay page slots) and its idempotency key.
fn run_body(input: &Value) -> Decision {
    let invocation = object(input, "invocation")?;
    let mut body = Body::default();
    body.value("mode", or(invocation, "mode", json!("test")));
    if matches!(invocation.get("input"), None | Some(Value::Null)) {
        body.value("input", json!({}));
    } else {
        body.slot("input");
    }
    if truthy(invocation.get("sourceChatId")) {
        body.raw("source_chat_id", invocation, "sourceChatId");
    }
    if truthy(invocation.get("messageDestinationOverrides")) {
        body.slot("message_destination_overrides");
    }
    if truthy(invocation.get("returnOutputs")) {
        body.slot("return_outputs");
    }
    let fallback = json!(format!("{}-{}", template(input.get("workflow_id")), template(input.get("uuid"))));
    let mut extra = Map::new();
    extra.insert("idempotency_key".into(), or(invocation, "idempotencyKey", fallback));
    Ok(body.request(format!("{}/run", workflow_root(input)), "POST", extra))
}

/// `upsertWorkflowTemplateProjection`: the `PUT` body (ciphertext, checksum and wrapped key are page slots).
fn template_upsert(input: &Value) -> Decision {
    let mut body = Body::default();
    body.value("template_id", member(input, "template_id")?.clone());
    body.value("source_version", match input.get("version") {
        None | Some(Value::Null) => json!(1),
        Some(version) => version.clone(),
    });
    body.slot("ciphertext");
    body.slot("ciphertext_checksum");
    body.slot("owner_wrapped_key");
    body.value("projection_schema_version", json!(PROJECTION_SCHEMA_VERSION));
    Ok(body.request(format!("{}/template-projection", workflow_root(input)), "PUT", Map::new()))
}

/// `createWorkflowTemplateShare`: the short-URL registration (the encrypted URL is a page slot).
fn short_url(input: &Value) -> Decision {
    let mut body = Body::default();
    body.value("token", member(input, "token")?.clone());
    body.slot("encrypted_url");
    body.value("content_type", json!("workflow_template"));
    body.value("content_id", member(input, "template_id")?.clone());
    body.value("password_protected", json!(false));
    Ok(body.request("/v1/share/short-url".to_owned(), "POST", Map::new()))
}

/// `completeWorkflowTemplateBinding`: `{ type, node_id }` of the requirement.
fn template_binding(input: &Value) -> Decision {
    let requirement = object(input, "requirement")?;
    let mut body = Body::default();
    body.raw("type", requirement, "type");
    body.raw("node_id", requirement, "node_id");
    Ok(body.request(format!("{}/binding-requirements/complete", workflow_root(input)), "POST", Map::new()))
}

/// `instructionBody` on `/v1/workflows/input` or its `/stream` variant.
fn instruction(input: &Value) -> Decision {
    let path = match route(input)? {
        "input" => "/v1/workflows/input",
        "stream" => "/v1/workflows/input/stream",
        _ => return Err("bad_field:route".to_owned()),
    };
    let record = input.as_object().ok_or_else(|| "bad_field:input".to_owned())?;
    let mut body = Body::default();
    body.raw("text", record, "text");
    body.value("input_type", json!("text"));
    body.value("selected_workflow_id", or(record, "selected_workflow_id", Value::Null));
    let timezone = if truthy(record.get("timezone")) { record["timezone"].clone() } else { json!("UTC") };
    body.value("timezone", timezone);
    body.value("optimistic_save", json!(true));
    if truthy(record.get("idempotency_key")) {
        body.raw("idempotency_key", record, "idempotency_key");
    }
    Ok(body.request(path.to_owned(), "POST", Map::new()))
}
