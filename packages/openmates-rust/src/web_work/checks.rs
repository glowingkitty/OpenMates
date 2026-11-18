//! Check decisions for the web worker (`/v1/user-checks`): decrypted views, request
//! bodies and the shared pure rules. The page decrypts/encrypts; this decides.
//!
//! Spec: `specifications/features/checks`.
use std::collections::BTreeMap;

use serde_json::{Value, json};

use super::Fallback::{Null, One};
use super::Src::{Or, Raw, Text};
use super::{Decision, Src, member, object, project, refusal, text};
use crate::work::{
    CheckDefinition, Run, SourceBinding, SourceDefinition, SourceKind, aggregate_status, hash,
    is_stale, text_hash,
};

/// Runs one `check*` op.
///
/// - `checkView` `{record, fields}`: a Check head (`encrypted_title`, `encrypted_description`).
/// - `checkRevisionView` `{record, fields}`: a revision with its parsed `definition`;
///   `{"error"}` when the decrypted definition does not match `definition_hash`.
/// - `checkRunView` `{record, fields, sources, currentRevisionId, subjectNow?}`: a run
///   with `aggregateStatus`, decrypted `summary`, per-source `detail` (from
///   `fields.results[binding_id]`) and `stale`.
/// - `checkAggregate` `{sources, statuses}`: the offline aggregate status.
/// - `checkValidate` `{requires_deterministic, sources}`: local validation, `{"error"}` on refusal.
/// - `checkStartRunBody`, `checkResultBody`, `checkConfirmBody`: request bodies.
/// - `checkCreateBody` `{check_id, revision_id, project_id, title, description?, status?,
///   requires_deterministic, sources}`: the plaintext create document. The page seals
///   `title`, `description` and `definition_text` with a fresh Check key and wraps that key
///   for the Project (`hashed_project_id`) and the master key; `body` carries the rest.
///
/// # Errors
/// `unknown_op:<name>` or a malformed-input error.
pub(crate) fn run(op: &str, input: &Value) -> Decision {
    match op {
        "checkView" => {
            let (record, fields) = (object(input, "record")?, object(input, "fields")?);
            Ok(Value::Object(project(record, fields, HEAD)?))
        }
        "checkRevisionView" => revision_view(input),
        "checkRunView" => run_view(input),
        "checkAggregate" => {
            let sources = bindings(input, "sources")?;
            let statuses: BTreeMap<String, String> =
                serde_json::from_value(member(input, "statuses")?.clone())
                    .map_err(|_| "bad_field:statuses")?;
            Ok(json!(aggregate_status(&sources, &statuses)))
        }
        "checkValidate" => {
            let sources = bindings(input, "sources")?;
            let deterministic = input
                .get("requires_deterministic")
                .and_then(Value::as_bool)
                .unwrap_or(false);
            Ok(
                match crate::work::validate_sources(&sources, deterministic) {
                    Ok(()) => json!({"ok": true}),
                    Err(error) => refusal(&error_code(&error)),
                },
            )
        }
        "checkStartRunBody" => Ok(pick(input, &["subject_revision", "encrypted_summary"])),
        "checkResultBody" => result_body(input),
        "checkCreateBody" => create_body(input),
        "checkConfirmBody" => {
            let decision = member(input, "decision")?.as_str().unwrap_or("");
            if !matches!(decision, "confirmed" | "rejected" | "blocked" | "waived") {
                return Ok(refusal(
                    "A decision is confirmed, rejected, blocked or waived.",
                ));
            }
            let mut body = pick(input, &["decision", "encrypted_result"]);
            body["decision"] = json!(decision);
            Ok(body)
        }
        _ => Err(format!("unknown_op:{op}")),
    }
}

/// Normalises and validates a draft definition and returns what the page must seal.
fn create_body(input: &Value) -> Decision {
    let sources: Vec<SourceDefinition> = serde_json::from_value(member(input, "sources")?.clone())
        .map_err(|_| "bad_field:sources")?;
    let deterministic = input
        .get("requires_deterministic")
        .and_then(Value::as_bool)
        .unwrap_or(false);
    let title = member(input, "title")?.as_str().unwrap_or("").trim();
    if title.is_empty() {
        return Ok(refusal("A Check needs a title."));
    }
    let project = member(input, "project_id")?
        .as_str()
        .ok_or("bad_field:project_id")?;
    let definition = match (CheckDefinition {
        requires_deterministic: deterministic,
        sources,
    })
    .normalized()
    {
        Ok(definition) => definition,
        Err(error) => return Ok(refusal(&error_code(&error))),
    };
    let text = definition.canonical_text().map_err(|e| e.to_string())?;
    let bindings: Vec<SourceBinding> = definition
        .sources
        .iter()
        .map(SourceDefinition::binding)
        .collect();
    let description = input
        .get("description")
        .and_then(Value::as_str)
        .map(str::trim)
        .filter(|d| !d.is_empty());
    let mut out = json!({
        "title": title,
        "definition_text": text,
        "hashed_project_id": hash(project),
        "body": {
            "check_id": member(input, "check_id")?, "project_id": project,
            "status": input.get("status").and_then(Value::as_str).unwrap_or("draft"),
            "revision": {
                "revision_id": member(input, "revision_id")?,
                "definition_hash": text_hash(&text),
                "requires_deterministic": definition.requires_deterministic,
                "sources": bindings,
            },
        },
    });
    if let Some(description) = description {
        out["description"] = json!(description);
    }
    Ok(out)
}

fn error_code(error: &crate::Error) -> String {
    match error {
        crate::Error::Invalid(code) => (*code).to_owned(),
        _ => "CHECK_SOURCE_INVALID".to_owned(),
    }
}

fn bindings(input: &Value, name: &str) -> Result<Vec<SourceBinding>, String> {
    serde_json::from_value(member(input, name)?.clone()).map_err(|_| format!("bad_field:{name}"))
}

/// Copies the present, non-null members of `names`.
fn pick(input: &Value, names: &[&str]) -> Value {
    let mut out = serde_json::Map::new();
    for name in names {
        if let Some(value) = input.get(*name).filter(|v| !v.is_null()) {
            out.insert((*name).to_owned(), value.clone());
        }
    }
    Value::Object(out)
}

fn result_body(input: &Value) -> Decision {
    let kind = member(input, "source_kind")?.as_str().unwrap_or("");
    if SourceKind::parse(kind).is_err() {
        return Ok(refusal("CHECK_SOURCE_INVALID"));
    }
    let status = member(input, "status")?.as_str().unwrap_or("");
    const STATUSES: [&str; 9] = [
        "pending",
        "running",
        "passed",
        "failed",
        "error",
        "blocked",
        "skipped",
        "cancelled",
        "waived",
    ];
    if !STATUSES.contains(&status) {
        return Ok(refusal("CHECK_SOURCE_INVALID"));
    }
    if kind == "human_confirmation" && !matches!(status, "pending" | "running") {
        return Ok(refusal("CHECK_HUMAN_CONFIRMATION_REQUIRED"));
    }
    Ok(pick(
        input,
        &[
            "source_kind",
            "status",
            "test_result_embed_id",
            "ai_score",
            "ai_threshold",
            "encrypted_result",
        ],
    ))
}

fn revision_view(input: &Value) -> Decision {
    let (record, fields) = (object(input, "record")?, object(input, "fields")?);
    let definition_text = text(record, fields, "encrypted_definition")?;
    let committed = record
        .get("definition_hash")
        .and_then(Value::as_str)
        .unwrap_or("");
    if text_hash(definition_text) != committed {
        return Ok(refusal("Check definition does not match its recorded hash"));
    }
    let Ok(definition) = serde_json::from_str::<CheckDefinition>(definition_text) else {
        return Ok(refusal("Check definition is not valid JSON"));
    };
    let mut out = project(record, fields, REVISION)?;
    out.insert(
        "definition".into(),
        serde_json::to_value(definition).map_err(|e| e.to_string())?,
    );
    Ok(Value::Object(out))
}

fn run_view(input: &Value) -> Decision {
    let (record, fields) = (object(input, "record")?, object(input, "fields")?);
    let sources = bindings(input, "sources")?;
    let mut out = project(record, fields, RUN)?;
    let results = record
        .get("source_results")
        .and_then(Value::as_array)
        .cloned()
        .unwrap_or_default();
    let details = fields.get("results").and_then(Value::as_object);
    let mut statuses = BTreeMap::new();
    let mut views = Vec::new();
    for result in &results {
        let id = result["source_binding_id"].as_str().unwrap_or("");
        statuses.insert(
            id.to_owned(),
            result["status"].as_str().unwrap_or("pending").to_owned(),
        );
        let mut view = result.clone();
        view["detail"] = details
            .and_then(|d| d.get(id))
            .cloned()
            .unwrap_or(Value::Null);
        view["encrypted_result"] = Value::Null;
        views.push(view);
    }
    // A run stores a result row only once a source reports; every other bound
    // source of the run is still pending (a human source waits for confirmation).
    for source in &sources {
        if !statuses.contains_key(&source.source_binding_id) {
            views.push(json!({
                "source_binding_id": source.source_binding_id,
                "status": "pending",
                "detail": Value::Null,
            }));
        }
    }
    out.insert("sourceResults".into(), json!(views));
    out.insert(
        "aggregateStatus".into(),
        json!(aggregate_status(&sources, &statuses)),
    );
    let current = input
        .get("currentRevisionId")
        .and_then(Value::as_str)
        .unwrap_or("");
    let subject_now = input.get("subjectNow").and_then(Value::as_str);
    let run: Option<Run> = serde_json::from_value(Value::Object(record.clone())).ok();
    out.insert(
        "stale".into(),
        json!(is_stale(run.as_ref(), current, subject_now)),
    );
    Ok(Value::Object(out))
}

const HEAD: &[(&str, Src)] = &[
    ("check_id", Raw("check_id")),
    ("title", Text("encrypted_title")),
    ("description", Text("encrypted_description")),
    ("status", Raw("status")),
    ("currentRevisionId", Or("current_revision_id", Null)),
    ("currentRevisionNumber", Or("current_revision_number", One)),
    ("createdAt", Raw("created_at")),
    ("updatedAt", Raw("updated_at")),
];

const REVISION: &[(&str, Src)] = &[
    ("revision_id", Raw("revision_id")),
    ("revisionNumber", Or("revision_number", One)),
    ("baseRevisionId", Or("base_revision_id", Null)),
    ("definitionHash", Raw("definition_hash")),
    ("requiresDeterministic", Or("requires_deterministic", Null)),
    ("sources", Raw("sources")),
    ("createdAt", Raw("created_at")),
];

const RUN: &[(&str, Src)] = &[
    ("run_id", Raw("run_id")),
    ("check_id", Raw("check_id")),
    ("checkRevisionId", Raw("check_revision_id")),
    ("subjectRevision", Or("subject_revision", Null)),
    ("status", Raw("status")),
    ("createdAt", Raw("created_at")),
    ("finishedAt", Or("finished_at", Null)),
    ("summary", Text("encrypted_summary")),
];
