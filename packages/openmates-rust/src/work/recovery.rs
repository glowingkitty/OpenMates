//! Work recovery projection: one Project's Plans, Tasks, dependencies,
//! assumptions and revisions as an external cleartext document. Pure document
//! logic (schema validation, conflicts, semantic comparison, projections and
//! restore inputs) is portable; YAML formatting and the atomic file write are
//! native-only. Network operations live on `Plans` (`plans/recovery_ops.rs`).
use super::{PlanCreate, PlanFlow, TaskCreate};
use crate::Error;
use serde::Serialize;
use serde_json::{Value, json};
use std::collections::{HashMap, HashSet};
use std::fmt;

/// Recovery failures carry the existing CLI's exact messages.
#[derive(Debug)]
pub enum RecoveryError {
    Invalid(String),
    Client(Error),
}
impl fmt::Display for RecoveryError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::Invalid(message) => f.write_str(message),
            Self::Client(error) => error.fmt(f),
        }
    }
}
impl std::error::Error for RecoveryError {}
impl From<Error> for RecoveryError {
    fn from(error: Error) -> Self {
        Self::Client(error)
    }
}
pub type RecoveryResult<T> = std::result::Result<T, RecoveryError>;

fn invalid<T>(message: impl Into<String>) -> RecoveryResult<T> {
    Err(RecoveryError::Invalid(message.into()))
}

/// A restore blocker; serialized field order matches the existing CLI JSON.
#[derive(Clone, Debug, PartialEq, Eq, Serialize)]
pub struct RecoveryConflict {
    pub kind: &'static str,
    pub id: String,
    pub reason: &'static str,
}

/// Server-generated lifecycle metadata ignored by semantic comparison.
const IGNORED: &[&str] = &[
    "short_id",
    "revision_id",
    "version",
    "created_at",
    "updated_at",
    "completed_at",
    "position",
    "queue_state",
    "priority_level",
];
const ARRAYS: &[&str] = &["plans", "tasks", "dependencies", "assumptions", "revisions"];

fn truthy(value: &Value) -> bool {
    match value {
        Value::Null => false,
        Value::Bool(flag) => *flag,
        Value::Number(number) => number.as_f64().is_some_and(|n| n != 0.0 && !n.is_nan()),
        Value::String(text) => !text.is_empty(),
        _ => true,
    }
}

/// JavaScript `String(value)` for interpolated identifiers.
fn js_string(value: &Value) -> String {
    match value {
        Value::Null => "null".into(),
        Value::Bool(flag) => flag.to_string(),
        Value::Number(number) => number.to_string(),
        Value::String(text) => text.clone(),
        Value::Array(items) => items
            .iter()
            .map(|item| if item.is_null() { String::new() } else { js_string(item) })
            .collect::<Vec<_>>()
            .join(","),
        Value::Object(_) => "[object Object]".into(),
    }
}

fn items<'a>(document: &'a Value, field: &str) -> &'a [Value] {
    document[field].as_array().map(Vec::as_slice).unwrap_or(&[])
}

fn read_id<'a>(value: &'a Value, key: &str, kind: &str) -> RecoveryResult<&'a str> {
    match value.get(key).and_then(Value::as_str).filter(|id| !id.is_empty()) {
        Some(id) => Ok(id),
        None => invalid(format!("Recovery {kind} requires {key}.")),
    }
}

fn add_stable_id(value: &Value, key: &str, ids: &mut HashSet<String>, kind: &str) -> RecoveryResult<()> {
    let id = read_id(value, key, kind)?;
    if !ids.insert(id.to_owned()) {
        return invalid(format!("Recovery document has duplicate {kind} ID {id}."));
    }
    Ok(())
}

fn assert_project_link(value: &Value, project_id: &Value, kind: &str) -> RecoveryResult<()> {
    let scoped = value
        .get("linked_project_ids")
        .and_then(Value::as_array)
        .is_some_and(|ids| ids.len() == 1 && ids[0] == *project_id);
    if !scoped {
        return invalid(format!(
            "Recovery {kind} must be scoped only to project {}.",
            js_string(project_id)
        ));
    }
    Ok(())
}

/// Reject any `encrypted_*` field anywhere in a projection.
pub fn assert_no_ciphertext(value: &Value) -> RecoveryResult<()> {
    match value {
        Value::Array(items) => items.iter().try_for_each(assert_no_ciphertext),
        Value::Object(map) => {
            for (key, nested) in map {
                if key.starts_with("encrypted_") {
                    return invalid(format!(
                        "Recovery projection must not contain ciphertext field {key}."
                    ));
                }
                assert_no_ciphertext(nested)?;
            }
            Ok(())
        }
        _ => Ok(()),
    }
}

/// Validate schema, stable IDs, Project scope, references and acyclic dependencies.
pub fn validate_document(document: &Value) -> RecoveryResult<()> {
    if !document.is_object() && !document.is_array() {
        return invalid("Work recovery document must be an object.");
    }
    if document.get("schema_version").and_then(Value::as_f64) != Some(1.0) {
        return invalid("Unsupported work recovery schema_version.");
    }
    let project_id = document
        .get("project")
        .and_then(|project| project.get("project_id"))
        .filter(|id| truthy(id))
        .ok_or_else(|| RecoveryError::Invalid("Work recovery document requires project.project_id.".into()))?;
    for field in ARRAYS {
        if !document[*field].is_array() {
            return invalid(format!("Work recovery document requires {field}."));
        }
    }
    assert_no_ciphertext(document)?;
    let mut plan_ids = HashSet::new();
    let mut task_ids = HashSet::new();
    for plan in items(document, "plans") {
        add_stable_id(plan, "plan_id", &mut plan_ids, "plan")?;
    }
    for task in items(document, "tasks") {
        add_stable_id(task, "task_id", &mut task_ids, "task")?;
    }
    for plan in items(document, "plans") {
        assert_project_link(plan, project_id, "plan")?;
    }
    for task in items(document, "tasks") {
        assert_project_link(task, project_id, "task")?;
    }
    for task in items(document, "tasks") {
        let plan = &task["plan_id"];
        if !plan.is_null() && !plan.as_str().is_some_and(|id| plan_ids.contains(id)) {
            return invalid(format!("Task references missing plan {}.", js_string(plan)));
        }
    }
    for assumption in items(document, "assumptions") {
        let plan = read_id(assumption, "plan_id", "assumption")?;
        if !plan_ids.contains(plan) {
            return invalid(format!("Assumption references missing plan {plan}."));
        }
        read_id(assumption, "assumption_id", "assumption")?;
        if !assumption["sources"].is_array() {
            return invalid("Assumption sources must be a typed cleartext proof list.");
        }
    }
    for revision in items(document, "revisions") {
        let plan = read_id(revision, "plan_id", "revision")?;
        if !plan_ids.contains(plan) {
            return invalid(format!("Revision references missing plan {plan}."));
        }
        read_id(revision, "revision_id", "revision")?;
        if !revision["snapshot"].is_object() {
            return invalid("Revision requires a canonical plan snapshot.");
        }
    }
    let mut order: Vec<String> = vec![];
    let mut graph: HashMap<String, Vec<String>> = HashMap::new();
    for dependency in items(document, "dependencies") {
        let (source, target) = (&dependency["source_ref"], &dependency["target_ref"]);
        if !truthy(source) || !truthy(target) {
            return invalid("Work recovery dependencies require source_ref and target_ref.");
        }
        for reference in [source, target] {
            let known = reference.as_str().is_some_and(|text| {
                let mut parts = text.split(':');
                let (kind, id) = (parts.next().unwrap_or(""), parts.next().unwrap_or(""));
                !id.is_empty()
                    && match kind {
                        "plan" => plan_ids.contains(id),
                        "task" => task_ids.contains(id),
                        _ => false,
                    }
            });
            if !known {
                return invalid(format!(
                    "Work recovery dependency references missing object {}.",
                    js_string(reference)
                ));
            }
        }
        let (source, target) = (js_string(source), js_string(target));
        if !graph.contains_key(&source) {
            order.push(source.clone());
        }
        graph.entry(source).or_default().push(target);
    }
    let mut visiting = HashSet::new();
    let mut visited = HashSet::new();
    for node in &order {
        visit(node, &graph, &mut visiting, &mut visited)?;
    }
    Ok(())
}

fn visit(
    node: &str,
    graph: &HashMap<String, Vec<String>>,
    visiting: &mut HashSet<String>,
    visited: &mut HashSet<String>,
) -> RecoveryResult<()> {
    if visiting.contains(node) {
        return invalid(format!("Work recovery dependency cycle includes {node}."));
    }
    if visited.contains(node) {
        return Ok(());
    }
    visiting.insert(node.to_owned());
    for next in graph.get(node).into_iter().flatten() {
        visit(next, graph, visiting, visited)?;
    }
    visiting.remove(node);
    visited.insert(node.to_owned());
    Ok(())
}

/// Existing Plans/Tasks that block a restore into `project_id`.
pub fn find_conflicts(
    document: &Value,
    project_id: &str,
    plan_ids: &[String],
    task_ids: &[String],
) -> Vec<RecoveryConflict> {
    let declared = &document["project"]["project_id"];
    if declared.as_str() != Some(project_id) {
        return vec![RecoveryConflict { kind: "plan", id: js_string(declared), reason: "wrong_project" }];
    }
    let mut conflicts = vec![];
    for (kind, key, current) in [("plan", "plan_id", plan_ids), ("task", "task_id", task_ids)] {
        for record in items(document, &format!("{kind}s")) {
            if let Some(id) = record[key].as_str().filter(|id| current.iter().any(|c| c == id)) {
                conflicts.push(RecoveryConflict { kind, id: id.into(), reason: "already_exists" });
            }
        }
    }
    conflicts
}

/// Restore preview reported by `--dry-run`.
pub fn dry_run_report(document: &Value, project_id: &str, conflicts: &[RecoveryConflict]) -> Value {
    let would_restore = if conflicts.is_empty() {
        let count = |field: &str| items(document, field).len();
        json!({"plans": count("plans"), "tasks": count("tasks"), "assumptions": count("assumptions"),
               "dependencies": count("dependencies"), "revisions": count("revisions")})
    } else {
        Value::Null
    };
    json!({"valid": true, "dry_run": true, "project_id": project_id, "conflicts": conflicts, "would_restore": would_restore})
}

/// Compare restored content while ignoring server-generated lifecycle metadata.
pub fn semantically_equal(left: &Value, right: &Value) -> bool {
    semantic_mismatch_paths(left, right).is_empty()
}

/// JSON-path-like locations (at most about 20) where two documents differ.
pub fn semantic_mismatch_paths(left: &Value, right: &Value) -> Vec<String> {
    let mut mismatches = vec![];
    collect_mismatches(&normalize(left), &normalize(right), "$", &mut mismatches);
    mismatches
}

fn normalize(value: &Value) -> Value {
    match value {
        Value::Array(items) => Value::Array(items.iter().map(normalize).collect()),
        Value::Object(map) => Value::Object(
            map.iter()
                .filter(|(key, _)| !IGNORED.contains(&key.as_str()))
                .map(|(key, nested)| (key.clone(), normalize(nested)))
                .collect(),
        ),
        other => other.clone(),
    }
}

fn collect_mismatches(left: &Value, right: &Value, path: &str, mismatches: &mut Vec<String>) {
    if mismatches.len() >= 20 {
        return;
    }
    match (left, right) {
        (Value::Number(a), Value::Number(b)) if a.as_f64() == b.as_f64() => {}
        (Value::Array(a), Value::Array(b)) => {
            if a.len() != b.len() {
                mismatches.push(format!("{path}.length"));
            }
            for (index, (l, r)) in a.iter().zip(b).enumerate() {
                collect_mismatches(l, r, &format!("{path}[{index}]"), mismatches);
            }
        }
        (Value::Object(a), Value::Object(b)) => {
            let keys = a.keys().chain(b.keys().filter(|key| !a.contains_key(*key)));
            for key in keys {
                match (a.get(key), b.get(key)) {
                    (Some(l), Some(r)) => collect_mismatches(l, r, &format!("{path}.{key}"), mismatches),
                    _ => mismatches.push(format!("{path}.{key}")),
                }
            }
        }
        (l, r) if l == r => {}
        _ => mismatches.push(path.into()),
    }
}

fn empty_null(value: &Value) -> Value {
    match value.as_str() {
        Some("") => Value::Null,
        _ => value.clone(),
    }
}

fn pick(source: &Value, fields: &[&str]) -> Value {
    Value::Object(fields.iter().map(|field| ((*field).to_owned(), source[*field].clone())).collect())
}

/// The existing CLI's Plan JSON shape for one decrypted Plan.
pub fn plan_projection(plan: &Value) -> Value {
    let mut value = pick(
        plan,
        &[
            "plan_id", "short_id", "title", "goal", "scope_in", "scope_out", "user_flows", "assumptions",
            "open_questions", "constraints", "decisions", "risks", "reference_patterns", "context", "status",
            "primary_chat_id", "linked_project_ids", "planner_focus_id", "version", "created_at", "updated_at",
            "completed_at",
        ],
    );
    value["slug"] = empty_null(&plan["slug"]);
    value
}

/// The existing CLI's Task JSON shape for one decrypted Task.
pub fn task_projection(task: &Value) -> Value {
    let mut value = pick(
        task,
        &[
            "task_id", "short_id", "title", "description", "labels", "tags", "latest_instruction", "status",
            "assignee_type", "assignee_identity", "assignee_hash", "primary_chat_id", "linked_project_ids",
            "plan_id", "due_at", "priority", "priority_level", "position", "queue_state", "blocked_reason_code",
            "ai_execution_state", "version",
        ],
    );
    value["slug"] = empty_null(&task["slug"]);
    value["blocked_reason"] = empty_null(&task["blocked_reason"]);
    value["external_chat"] = match &task["external_chat"] {
        chat @ Value::Object(_) => json!({"provider": chat["provider"], "id": chat["id"],
            "title": chat["title"].as_str().unwrap_or("")}),
        _ => Value::Null,
    };
    value
}

fn typed_source(value: &Value) -> bool {
    let has = |key: &str| value[key].is_string();
    value.is_object()
        && match value["kind"].as_str() {
            Some("embed") => has("embed_id"),
            Some("url") => has("url"),
            Some("file") => has("path"),
            _ => false,
        }
}

fn typed_sources(text: &str) -> RecoveryResult<Value> {
    if text.is_empty() {
        return Ok(json!([]));
    }
    let parsed: Value = serde_json::from_str(text).map_err(|_| {
        RecoveryError::Invalid("Assumption encrypted_sources was not valid JSON after decryption.".into())
    })?;
    if !parsed.as_array().is_some_and(|sources| sources.iter().all(typed_source)) {
        return invalid("Assumption encrypted_sources must contain typed proof records.");
    }
    Ok(parsed)
}

/// Cleartext assumption projection from a decrypted Plan child row, whose
/// private fields (`text`, `sources`, ...) are already decrypted strings.
pub fn assumption_projection(plan_id: &str, assumption: &Value) -> RecoveryResult<Value> {
    let text = |key: &str| json!(assumption[key].as_str().unwrap_or(""));
    let or_null = |key: &str| assumption.get(key).cloned().unwrap_or(Value::Null);
    let criteria = match &assumption["linked_criterion_ids"] {
        Value::Null => json!([]),
        other => other.clone(),
    };
    Ok(json!({
        "plan_id": plan_id,
        "assumption_id": assumption["assumption_id"],
        "text": text("text"),
        "category": or_null("category"),
        "status": or_null("status"),
        "required_before": or_null("required_before"),
        "linked_sub_chat_id": or_null("linked_sub_chat_id"),
        "linked_task_id": or_null("linked_task_id"),
        "linked_criterion_ids": criteria,
        "corrected_text": text("corrected_text"),
        "evidence_summary": text("evidence_summary"),
        "blocker_reason": text("blocker_reason"),
        "waiver_reason": text("waiver_reason"),
        "sources": typed_sources(assumption["sources"].as_str().unwrap_or(""))?,
        "created_at": or_null("created_at"),
        "updated_at": or_null("updated_at"),
    }))
}

/// Cleartext revision projection from its server row and decrypted snapshot.
pub fn revision_projection(plan_id: &str, revision: &Value, snapshot: &str) -> RecoveryResult<Value> {
    let id = js_string(&revision["revision_id"]);
    if snapshot.is_empty() {
        return invalid(format!("Revision {id} could not be decrypted."));
    }
    let canonical: Value = serde_json::from_str(snapshot)
        .ok()
        .filter(Value::is_object)
        .ok_or_else(|| RecoveryError::Invalid(format!("Revision {id} has an invalid plan snapshot.")))?;
    assert_no_ciphertext(&canonical)?;
    Ok(json!({"plan_id": plan_id, "revision_id": revision["revision_id"], "fingerprint": revision["fingerprint"],
              "snapshot": canonical, "created_at": revision["created_at"]}))
}

/// Assemble a document; dependency, assumption and revision order is caller-defined.
pub fn document(
    project_id: &str,
    plans: Vec<Value>,
    tasks: Vec<Value>,
    dependencies: Vec<Value>,
    assumptions: Vec<Value>,
    revisions: Vec<Value>,
) -> Value {
    json!({"schema_version": 1, "project": {"project_id": project_id}, "plans": plans, "tasks": tasks,
           "dependencies": dependencies, "assumptions": assumptions, "revisions": revisions})
}

/// A required string field of a restore record.
pub fn record_string<'a>(record: &'a Value, key: &str) -> RecoveryResult<&'a str> {
    match record[key].as_str() {
        Some(value) => Ok(value),
        None => invalid(format!("Recovery record requires {key}.")),
    }
}

fn record_strings(record: &Value, key: &str) -> RecoveryResult<Vec<String>> {
    match record[key].as_array() {
        Some(values) if values.iter().all(Value::is_string) => {
            Ok(values.iter().filter_map(Value::as_str).map(str::to_owned).collect())
        }
        _ => invalid(format!("Recovery record requires {key} string array.")),
    }
}

fn optional_string(record: &Value, key: &str) -> Option<String> {
    record[key].as_str().map(str::to_owned)
}

/// Plan creation input restoring one projected Plan into `project_id`.
pub fn plan_create_input(record: &Value, project_id: &str) -> RecoveryResult<PlanCreate> {
    let flows = record["user_flows"].as_array().ok_or_else(|| {
        RecoveryError::Invalid("Recovery record requires user_flows array.".into())
    })?;
    let user_flows: Vec<PlanFlow> = serde_json::from_value(Value::Array(flows.clone())).map_err(|_| {
        RecoveryError::Invalid("Recovery record user_flows are not valid Plan flows.".into())
    })?;
    let text = |key: &str| record_string(record, key).map(str::to_owned);
    Ok(PlanCreate {
        plan_id: Some(text("plan_id")?),
        title: text("title")?,
        goal: text("goal")?,
        scope_in: text("scope_in")?,
        scope_out: text("scope_out")?,
        user_flows,
        assumptions: text("assumptions")?,
        open_questions: text("open_questions")?,
        constraints: text("constraints")?,
        decisions: text("decisions")?,
        risks: text("risks")?,
        reference_patterns: text("reference_patterns")?,
        context: text("context")?,
        status: Some(text("status")?),
        slug: optional_string(record, "slug"),
        primary_chat_id: optional_string(record, "primary_chat_id"),
        linked_project_ids: vec![project_id.to_owned()],
        planner_focus_id: optional_string(record, "planner_focus_id"),
    })
}

/// Task creation input restoring one projected Task into `project_id`.
pub fn task_create_input(record: &Value, project_id: &str) -> RecoveryResult<TaskCreate> {
    let due_at = match &record["due_at"] {
        Value::Number(number) => Some(number.as_i64().ok_or_else(|| {
            RecoveryError::Invalid("Recovery record requires an integer due_at.".into())
        })?),
        _ => None,
    };
    let priority = match &record["priority"] {
        Value::Number(number) => Some(number.as_u64().and_then(|n| u8::try_from(n).ok()).ok_or_else(|| {
            RecoveryError::Invalid("Recovery record requires a priority from 0 to 4.".into())
        })?),
        _ => None,
    };
    let assign = match record["assignee_hash"].as_str() {
        Some(hash) => hash.to_owned(),
        None => record_string(record, "assignee_type")?.to_owned(),
    };
    Ok(TaskCreate {
        task_id: Some(record_string(record, "task_id")?.to_owned()),
        title: record_string(record, "title")?.to_owned(),
        description: record_string(record, "description")?.to_owned(),
        labels: record_strings(record, "labels")?,
        status: Some(record_string(record, "status")?.to_owned()),
        assign: Some(assign),
        primary_chat_id: optional_string(record, "primary_chat_id"),
        linked_project_ids: vec![project_id.to_owned()],
        plan_id: optional_string(record, "plan_id"),
        due_at,
        priority,
        slug: optional_string(record, "slug"),
        ..Default::default()
    })
}

/// `<root>/<project-id>.yml`, dropping one trailing slash from `root`.
pub fn projection_path(root: &str, project_id: &str) -> String {
    format!("{}/{project_id}.yml", root.strip_suffix('/').unwrap_or(root))
}

/// Sorted-key YAML for a validated document.
#[cfg(feature = "workflow-yaml")]
pub fn serialize_document(document: &Value) -> RecoveryResult<String> {
    validate_document(document)?;
    serde_yaml::to_string(document)
        .map_err(|_| RecoveryError::Invalid("Recovery projection could not be serialized.".into()))
}

/// Parse YAML text; callers still run `validate_document`.
#[cfg(feature = "workflow-yaml")]
pub fn parse_document(source: &str) -> RecoveryResult<Value> {
    serde_yaml::from_str::<Value>(source)
        .map_err(|_| RecoveryError::Invalid("Recovery projection is not valid YAML.".into()))
}

/// Validate, then write via a `.tmp` sibling and rename (directory 0700, file 0600).
#[cfg(all(feature = "workflow-yaml", not(target_arch = "wasm32")))]
pub fn write_document_atomically(path: &std::path::Path, document: &Value) -> RecoveryResult<()> {
    use std::io::Write;
    let source = serialize_document(document)?;
    let failed = |error: std::io::Error| {
        RecoveryError::Invalid(format!("Recovery projection could not be written: {}: {error}", path.display()))
    };
    if let Some(parent) = path.parent().filter(|parent| !parent.as_os_str().is_empty()) {
        let mut builder = std::fs::DirBuilder::new();
        builder.recursive(true);
        #[cfg(unix)]
        std::os::unix::fs::DirBuilderExt::mode(&mut builder, 0o700);
        builder.create(parent).map_err(failed)?;
    }
    let mut temporary = path.as_os_str().to_owned();
    temporary.push(".tmp");
    let temporary = std::path::PathBuf::from(temporary);
    let mut options = std::fs::OpenOptions::new();
    options.write(true).create(true).truncate(true);
    #[cfg(unix)]
    std::os::unix::fs::OpenOptionsExt::mode(&mut options, 0o600);
    let mut file = options.open(&temporary).map_err(failed)?;
    file.write_all(source.as_bytes()).map_err(failed)?;
    file.sync_all().map_err(failed)?;
    drop(file);
    std::fs::rename(&temporary, path).map_err(failed)
}

#[cfg(test)]
#[path = "recovery_tests.rs"]
mod tests;
