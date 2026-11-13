//! Workflow template portability decisions (shared Rust core `work` op, Workflows slice).
//!
//! spec: specifications/features/workflows#workflows.portability.private-content-boundary
//!
//! Mirrors the pure logic of the web `workflowTemplateService.ts`: the portable
//! template payload built from a workflow (`buildWorkflowTemplatePayload`), the
//! structural check of a received template (`validateWorkflowTemplatePayload`),
//! the projection compatibility check and the disabled-import check. The page
//! keeps the template key, AES-GCM, the SHA-256 checksum and fetch. The payload
//! comes back in TS key order because the page encrypts its `JSON.stringify` text.

use super::workflow_json::{Tree, defined, str_tree, strict_eq, truthy};
use crate::web_apps::js_string;

/// Field-name fragments a portable template must not carry (normalized, see [`normalized_key`]).
const FORBIDDEN_FIELD_PARTS: &[&str] = &[
    "token", "secret", "credential", "accountid", "connectionid", "connectedaccountid",
    "provideruserid", "webhooksecret", "apikey", "password", "vault", "grant", "runid",
    "versionid", "workflowid", "nextrunat", "claim", "wait", "output", "providerresponse",
    "sourcechatid", "encryptedgraphblobref", "encryptedcontentref", "fragmentkey", "shortkey",
    "templatekey",
];

/// `PROJECTION_SCHEMA_VERSION` of the TS service.
pub(crate) const PROJECTION_SCHEMA_VERSION: i64 = 1;

/// Why a decision did not produce its result.
pub(crate) enum Fail {
    /// A TS `Error` the page rethrows with this exact message.
    Refuse(String),
    /// A malformed input the TS code would have hit as a `TypeError` (`bad_field:<name>`).
    Bad(String),
}

fn refuse(message: &str) -> Fail {
    Fail::Refuse(message.to_owned())
}

/// `key.toLowerCase().replace(/[^a-z0-9]/g, "")`.
fn normalized_key(key: &str) -> String {
    key.to_lowercase().chars().filter(|c| c.is_ascii_lowercase() || c.is_ascii_digit()).collect()
}

/// `assertPortableValue`: the first forbidden key in `Object.entries` order is reported.
fn assert_portable(value: &Tree, path: &str) -> Result<(), Fail> {
    match value {
        Tree::Arr(items) => {
            for (index, item) in items.iter().enumerate() {
                assert_portable(item, &format!("{path}[{index}]"))?;
            }
        }
        Tree::Obj(entries) => {
            for (key, child) in entries {
                let normalized = normalized_key(key);
                if FORBIDDEN_FIELD_PARTS.iter().any(|part| normalized.contains(part)) {
                    return Err(Fail::Refuse(format!("Workflow template contains a non-portable field at {path}.{key}.")));
                }
                assert_portable(child, &format!("{path}.{key}"))?;
            }
        }
        _ => {}
    }
    Ok(())
}

/// `${value}` inside a TS template literal (`undefined` for a missing member).
fn template(value: Option<&Tree>) -> String {
    value.map_or_else(|| "undefined".to_owned(), |v| js_string(&v.to_value()))
}

fn is_record(value: Option<&Tree>) -> bool {
    matches!(value, Some(Tree::Obj(_)))
}

fn non_empty_str(value: Option<&Tree>) -> bool {
    matches!(value, Some(Tree::Str(s)) if !s.is_empty())
}

/// `value === undefined || typeof value === "string"`.
fn optional_str(value: Option<&Tree>) -> bool {
    matches!(value, None | Some(Tree::Str(_)))
}

fn is_portable_node(value: &Tree) -> bool {
    is_record(Some(value)) && non_empty_str(value.get("id")) && non_empty_str(value.get("type")) && is_record(value.get("config"))
}

fn is_portable_edge(value: &Tree) -> bool {
    is_record(Some(value)) && non_empty_str(value.get("from")) && non_empty_str(value.get("to")) && optional_str(value.get("branch"))
}

fn is_binding_requirement(value: &Tree) -> bool {
    is_record(Some(value))
        && non_empty_str(value.get("type"))
        && non_empty_str(value.get("node_id"))
        && optional_str(value.get("app_id"))
        && optional_str(value.get("skill_id"))
}

fn record<'a>(value: &'a Tree, name: &str) -> Result<&'a Tree, Fail> {
    match value {
        Tree::Obj(_) => Ok(value),
        _ => Err(Fail::Bad(format!("bad_field:{name}"))),
    }
}

fn array<'a>(value: Option<&'a Tree>, name: &str) -> Result<&'a [Tree], Fail> {
    match value {
        Some(Tree::Arr(items)) => Ok(items),
        _ => Err(Fail::Bad(format!("bad_field:{name}"))),
    }
}

/// `portableNode`: `{ id, type, title?, config: cloneJson(config ?? {}) }`, then checked.
fn portable_node(node: &Tree) -> Result<Tree, Fail> {
    let node = record(node, "workflow.graph.nodes")?;
    let mut candidate = Tree::object();
    candidate.set_defined("id", node.get("id"));
    candidate.set_defined("type", node.get("type"));
    if truthy(node.get("title")) {
        candidate.set_defined("title", node.get("title"));
    }
    candidate.set("config", defined(node.get("config")).cloned().unwrap_or_else(Tree::object));
    assert_portable(&candidate, &format!("$.nodes.{}", template(node.get("id"))))?;
    Ok(candidate)
}

/// `String(config[key] ?? "")` of a node config (a non-object config reads `undefined`).
fn config_string(config: &Tree, key: &str) -> Tree {
    Tree::Str(defined(config.get(key)).map_or_else(String::new, |v| js_string(&v.to_value())))
}

/// `bindingRequirements(graph)`: one requirement per schedule, skill and notification node.
fn binding_requirements(nodes: &[Tree]) -> Result<Vec<Tree>, Fail> {
    let mut out = Vec::new();
    for node in nodes {
        let node = record(node, "workflow.graph.nodes")?;
        let mut requirement = Tree::object();
        let kind = match node.get("type").and_then(Tree::as_str) {
            Some("schedule_trigger") => "schedule",
            Some("app_skill_action") => "app_skill",
            Some("send_notification" | "send_email_notification") => "notification_preferences",
            _ => continue,
        };
        requirement.set("type", str_tree(kind));
        requirement.set_defined("node_id", node.get("id"));
        if kind == "app_skill" {
            let config = defined(node.get("config")).cloned().unwrap_or_else(Tree::object);
            requirement.set("app_id", config_string(&config, "app_id"));
            requirement.set("skill_id", config_string(&config, "skill_id"));
        }
        out.push(requirement);
    }
    Ok(out)
}

/// `Array.from(new Set(...)).sort()`: JS sorts strings by UTF-16 code units.
fn required_capabilities(requirements: &[Tree]) -> Tree {
    let mut capabilities: Vec<String> = Vec::new();
    let mut add = |value: String| {
        if !capabilities.contains(&value) {
            capabilities.push(value);
        }
    };
    for requirement in requirements {
        if requirement.get("type").and_then(Tree::as_str) != Some("app_skill") || !truthy(requirement.get("app_id")) {
            continue;
        }
        let app = template(requirement.get("app_id"));
        add(app.clone());
        if truthy(requirement.get("skill_id")) {
            add(format!("{app}.{}", template(requirement.get("skill_id"))));
        }
    }
    capabilities.sort_by(|a, b| a.encode_utf16().cmp(b.encode_utf16()));
    Tree::Arr(capabilities.into_iter().map(Tree::Str).collect())
}

/// `value.trim()` of a string member; anything else is a TS `TypeError`.
fn trimmed<'a>(value: Option<&'a Tree>, name: &str) -> Result<&'a str, Fail> {
    match value {
        Some(Tree::Str(s)) => Ok(super::teams::js_trim(s)),
        _ => Err(Fail::Bad(format!("bad_field:{name}"))),
    }
}

/// `buildWorkflowTemplatePayload(workflow)`, in TS evaluation (and refusal) order.
///
/// # Errors
/// `Refuse` with the TS message (no trigger, blank title, non-portable field);
/// `Bad` for a workflow the TS code could not have read.
pub(crate) fn payload(workflow: &Tree) -> Result<Tree, Fail> {
    let workflow = record(workflow, "workflow")?;
    let graph = record(workflow.get("graph").unwrap_or(&Tree::Null), "workflow.graph")?;
    let nodes = array(graph.get("nodes"), "workflow.graph.nodes")?;
    let trigger_index = nodes
        .iter()
        .position(|node| strict_eq(node.get("id"), graph.get("trigger_node_id")))
        .ok_or_else(|| refuse("Workflow does not have a portable trigger node."))?;
    let trigger = &nodes[trigger_index];
    let requirements = binding_requirements(nodes)?;
    let mut out = Tree::object();
    out.set_defined("template_version", graph.get("version"));
    let title = trimmed(workflow.get("title"), "workflow.title")?.to_owned();
    out.set("title", Tree::Str(title.clone()));
    let description = match defined(workflow.get("description")) {
        None => Tree::Null,
        Some(value) => match trimmed(Some(value), "workflow.description")? {
            "" => Tree::Null,
            text => str_tree(text),
        },
    };
    out.set("description", description);
    out.set("trigger_template", portable_node(trigger)?);
    let mut node_templates = Vec::new();
    for (index, node) in nodes.iter().enumerate() {
        // `node.id !== trigger.id`: the trigger itself is the same reference, so it is always skipped.
        if index == trigger_index || strict_eq(node.get("id"), trigger.get("id")) {
            continue;
        }
        node_templates.push(portable_node(node)?);
    }
    out.set("node_templates", Tree::Arr(node_templates));
    let mut edge_templates = Vec::new();
    for edge in array(graph.get("edges"), "workflow.graph.edges")? {
        let edge = record(edge, "workflow.graph.edges")?;
        let mut template_edge = Tree::object();
        template_edge.set_defined("from", edge.get("from"));
        template_edge.set_defined("to", edge.get("to"));
        if truthy(edge.get("branch")) {
            template_edge.set_defined("branch", edge.get("branch"));
        }
        edge_templates.push(template_edge);
    }
    out.set("edge_templates", Tree::Arr(edge_templates));
    out.set("variables_schema", Tree::object());
    out.set("required_capabilities", required_capabilities(&requirements));
    out.set("binding_requirements", Tree::Arr(requirements));
    if title.is_empty() {
        return Err(refuse("Workflow title is required before sharing."));
    }
    assert_portable(&out, "$")?;
    Ok(out)
}

/// `validateWorkflowTemplatePayload(value)`: `Ok(())` means the page keeps its own value.
///
/// # Errors
/// `Refuse` with the TS message of the first failed check.
pub(crate) fn validate(value: &Tree) -> Result<(), Fail> {
    let version_ok = match value.get("template_version") {
        Some(Tree::Num(n)) => n.as_f64().is_some_and(|v| v.fract() == 0.0 && v >= 1.0),
        _ => false,
    };
    if !is_record(Some(value)) || !version_ok {
        return Err(refuse("Workflow template has an invalid version."));
    }
    let title_ok = matches!(value.get("title"), Some(Tree::Str(s)) if !super::teams::js_trim(s).is_empty());
    let trigger_ok = value.get("trigger_template").is_some_and(is_portable_node);
    if !title_ok || !trigger_ok {
        return Err(refuse("Workflow template is missing required portable fields."));
    }
    let all = |name: &str, check: fn(&Tree) -> bool| match value.get(name) {
        Some(Tree::Arr(items)) => items.iter().all(check),
        _ => false,
    };
    let structure_ok = all("node_templates", is_portable_node)
        && all("edge_templates", is_portable_edge)
        && is_record(value.get("variables_schema"))
        && all("required_capabilities", |item| matches!(item, Tree::Str(_)))
        && all("binding_requirements", is_binding_requirement);
    if !structure_ok {
        return Err(refuse("Workflow template has an invalid portable structure."));
    }
    assert_portable(value, "$")
}

/// The `loadSharedWorkflowTemplate` compatibility check (before the page's checksum check).
///
/// # Errors
/// `Refuse` when the projection names another template or schema version.
pub(crate) fn projection_check(template_id: Option<&Tree>, projection: &Tree) -> Result<(), Fail> {
    let projection = record(projection, "projection")?;
    let schema = Tree::Num(PROJECTION_SCHEMA_VERSION.into());
    if !strict_eq(projection.get("template_id"), template_id) || !strict_eq(projection.get("projection_schema_version"), Some(&schema)) {
        return Err(refuse("Workflow template projection is not compatible with this app version."));
    }
    Ok(())
}

/// The `importWorkflowTemplate` reply check: the imported workflow must stay disabled.
///
/// # Errors
/// `Refuse` for a missing workflow or an enabled one.
pub(crate) fn import_check(response: &Tree) -> Result<(), Fail> {
    let workflow = response.get("workflow");
    if !truthy(workflow) || truthy(workflow.and_then(|w| w.get("enabled"))) {
        return Err(refuse("Imported workflow did not remain disabled for rebinding."));
    }
    Ok(())
}
