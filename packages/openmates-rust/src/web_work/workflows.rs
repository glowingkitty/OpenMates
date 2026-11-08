//! Workflow client decisions (shared Rust core Worker `work` op, Workflows slice).
//!
//! spec: specifications/features/workflows#workflows.authoring.atomic-update
//!
//! Entry point of every `workflow*` op. Mirrors the pure logic of the web
//! `workflowInputService.ts` (`normalizeSession` over a server reply),
//! `appsWorkflowLibraryService.ts` (page projection) and
//! `workflowRunPreviewMetadata.ts` (metadata merge), and routes the template
//! decisions to [`workflow_template`] and paths/bodies to [`workflow_bodies`].
//! Ordered ops parse the input as a key-ordered [`Tree`] and answer in TS key
//! order; the page keeps fetch, SSE parsing, every cache/generation fence and
//! all WebCrypto. Parity: `workflows_ts_vectors.json` (`workWorkflowVectors.test.ts`).

use super::workflow_bodies;
use super::workflow_json::{self, Tree, defined, strict_eq, truthy};
use super::workflow_template::{self, Fail};

/// Runs one named workflow decision on the page's JSON text.
///
/// # Errors
/// `unknown_op:<name>`, a parse error, or `missing_field:`/`bad_field:` for a
/// malformed input. TS refusals come back as `{"error": "<same message>"}`.
pub(crate) fn run_json(op: &str, input: &str) -> Result<String, String> {
    let ordered = match op {
        "workflowTemplatePayload" | "workflowTemplateValidate" | "workflowTemplateProjectionCheck"
        | "workflowTemplateImportCheck" | "workflowInputSession" | "workflowAppsLibraryPage"
        | "workflowRunPreviewMerge" => true,
        _ => false,
    };
    if !ordered {
        let value: serde_json::Value = serde_json::from_str(input).map_err(|e| e.to_string())?;
        let output = workflow_bodies::run(op, &value)?;
        return serde_json::to_string(&output).map_err(|e| e.to_string());
    }
    let input = workflow_json::parse(input)?;
    let result = match op {
        "workflowTemplatePayload" => workflow_template::payload(member(&input, "workflow")?).map(|payload| wrap("payload", payload)),
        "workflowTemplateValidate" => workflow_template::validate(member(&input, "value")?).map(|()| ok()),
        "workflowTemplateProjectionCheck" => {
            workflow_template::projection_check(input.get("template_id"), member(&input, "projection")?).map(|()| ok())
        }
        "workflowTemplateImportCheck" => workflow_template::import_check(member(&input, "response")?).map(|()| ok()),
        "workflowInputSession" => normalize_session(member(&input, "session")?).map(|session| wrap("session", session)),
        "workflowAppsLibraryPage" => apps_library_page(member(&input, "result")?),
        _ => Ok(run_preview_merge(&input)),
    };
    let output = match result {
        Ok(tree) => tree,
        Err(Fail::Refuse(message)) => wrap("error", Tree::Str(message)),
        Err(Fail::Bad(reason)) => return Err(reason),
    };
    workflow_json::to_text(&output)
}

/// A required input member.
fn member<'a>(input: &'a Tree, name: &str) -> Result<&'a Tree, String> {
    input.get(name).ok_or_else(|| format!("missing_field:{name}"))
}

fn wrap(name: &str, value: Tree) -> Tree {
    let mut out = Tree::object();
    out.set(name, value);
    out
}

fn ok() -> Tree {
    wrap("ok", Tree::Bool(true))
}

fn bad(name: &str) -> Fail {
    Fail::Bad(format!("bad_field:{name}"))
}

fn items<'a>(value: &'a Tree, name: &str) -> Result<&'a [Tree], Fail> {
    match value {
        Tree::Arr(items) => Ok(items),
        _ => Err(bad(name)),
    }
}

/// `value ?? []` of an id list (an array, or nullish).
fn list_or_empty(value: Option<&Tree>, name: &str) -> Result<Tree, Fail> {
    match defined(value) {
        None => Ok(Tree::Arr(Vec::new())),
        Some(list @ Tree::Arr(_)) => Ok(list.clone()),
        Some(_) => Err(bad(name)),
    }
}

/// The `before.graph.nodes` of the change's mutation (`?.` chain, `?? []`).
fn before_nodes<'a>(session: &'a Tree, workflow_id: Option<&Tree>) -> Result<&'a [Tree], Fail> {
    let mutations = match defined(session.get("mutations")) {
        None => return Ok(&[]),
        Some(list) => items(list, "session.mutations")?,
    };
    let found = mutations.iter().find(|item| strict_eq(item.get("target_id"), workflow_id));
    let nodes = found
        .and_then(|item| defined(item.get("before")))
        .and_then(|before| defined(before.get("graph")))
        .and_then(|graph| defined(graph.get("nodes")));
    match nodes {
        None => Ok(&[]),
        Some(list) => items(list, "session.mutations.before.graph.nodes"),
    }
}

/// `node?.title || node?.type.replaceAll('_', ' ') || id` (`||` keeps the value itself).
fn removed_title(node: Option<&Tree>, id: &Tree) -> Result<Tree, Fail> {
    let Some(node) = node else { return Ok(id.clone()) };
    if truthy(node.get("title")) {
        return Ok(node.get("title").cloned().unwrap_or(Tree::Null));
    }
    match node.get("type") {
        Some(Tree::Str(kind)) if !kind.is_empty() => Ok(Tree::Str(kind.replace('_', " "))),
        Some(Tree::Str(_)) => Ok(id.clone()),
        _ => Err(bad("session.mutations.before.graph.nodes.type")),
    }
}

/// `normalizeSession(session)`: change lists get their defaults, removed ids become `{id, title}`.
fn normalize_session(session: &Tree) -> Result<Tree, Fail> {
    let changes = match session.get("changes") {
        Some(Tree::Arr(changes)) if !changes.is_empty() => changes,
        // `!session.changes?.length`: no changes leaves the reply untouched.
        _ => return Ok(session.clone()),
    };
    let mut normalized = Vec::with_capacity(changes.len());
    for change in changes {
        if !matches!(change, Tree::Obj(_)) {
            return Err(bad("session.changes"));
        }
        let before = before_nodes(session, change.get("workflow_id"))?;
        let mut next = change.clone();
        let empty = || Tree::Arr(Vec::new());
        next.set("added_node_ids", defined(change.get("added_node_ids")).cloned().unwrap_or_else(empty));
        let edited = defined(change.get("edited_node_ids")).or_else(|| defined(change.get("changed_node_ids")));
        next.set("edited_node_ids", edited.cloned().unwrap_or_else(empty));
        let removed = match defined(change.get("removed_nodes")) {
            Some(existing) => existing.clone(),
            None => {
                let ids = list_or_empty(change.get("removed_node_ids"), "removed_node_ids")?;
                let mut out = Vec::new();
                for id in items(&ids, "removed_node_ids")? {
                    let node = before.iter().find(|item| strict_eq(item.get("id"), Some(id)));
                    let mut entry = Tree::object();
                    entry.set("id", id.clone());
                    entry.set("title", removed_title(node, id)?);
                    out.push(entry);
                }
                Tree::Arr(out)
            }
        };
        next.set("removed_nodes", removed);
        normalized.push(next);
    }
    let mut out = session.clone();
    out.set("changes", Tree::Arr(normalized));
    Ok(out)
}

/// `listAppsWorkflows` reply projection: `{ items: [{id, title}], hasMore, offset, limit }`.
fn apps_library_page(result: &Tree) -> Result<Tree, Fail> {
    let mut list = Vec::new();
    for item in items(result.get("workflows").unwrap_or(&Tree::Null), "result.workflows")? {
        if !matches!(item, Tree::Obj(_)) {
            return Err(bad("result.workflows"));
        }
        let mut entry = Tree::object();
        entry.set_defined("id", item.get("id"));
        entry.set_defined("title", item.get("title"));
        list.push(entry);
    }
    let mut out = Tree::object();
    out.set("items", Tree::Arr(list));
    out.set_defined("hasMore", result.get("has_more"));
    out.set_defined("offset", result.get("offset"));
    out.set_defined("limit", result.get("limit"));
    Ok(out)
}

/// `loadWorkflowRunPreviewMetadata` merge: provenance first, then the fetched workflow/run.
fn run_preview_merge(input: &Tree) -> Tree {
    let provenance = input.get("provenance");
    let own = |key: &str| defined(provenance.and_then(|p| p.get(key)));
    let workflow = |key: &str| defined(input.get("workflow").and_then(|w| w.get(key)));
    let run = |key: &str| defined(input.get("run").and_then(|r| r.get(key)));
    let mut out = Tree::object();
    out.set_defined("title", own("title").or_else(|| input.get("workflow").and_then(|w| w.get("title"))));
    out.set_defined("description", own("description").or_else(|| workflow("description")));
    out.set_defined("startedAt", own("startedAt").or_else(|| run("started_at")));
    out
}
