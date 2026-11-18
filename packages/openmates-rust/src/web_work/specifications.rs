//! Specification decisions of the web `work` op: record projections over the
//! page-decrypted fields, the content-commitment check and the approval body.
//! The page only decrypts, sends requests and renders; it decides nothing.
use serde_json::{Value, json};
use sha2::{Digest, Sha256};

use super::Fallback::{Null, One};
use super::Src::{Or, Raw, Text};
use super::{Decision, Src, member, object, project, refusal, text};
use crate::work::{
    DEFAULT_CATALOG_REVISION, MAX_DOCUMENT_BYTES, SpecificationDocument, specification_content_hash,
};

/// Runs one `specification*` op.
///
/// - `specificationView` `{record, fields}`: a Specification head.
/// - `specificationRevisionView` `{record, fields}`: one revision with its parsed
///   document; `{"error"}` when the decrypted document does not match `content_hash`.
/// - `specificationApproveBody` `{revision}`: the `POST .../approve` body.
/// - `specificationCreatePlan` `{document, specification_id, revision_id}`: validates
///   the document and answers the canonical plaintext (`document_text`, the exact text
///   the commitment covers), its `content_hash`, the trimmed `title`/`summary` to seal
///   and the catalog revision; `{"error"}` for a document the reader cannot resolve.
///
/// # Errors
/// `unknown_op:<name>` or a malformed-input error.
pub(crate) fn run(op: &str, input: &Value) -> Decision {
    match op {
        "specificationView" => {
            let (record, fields) = (object(input, "record")?, object(input, "fields")?);
            Ok(Value::Object(project(record, fields, HEAD)?))
        }
        "specificationRevisionView" => {
            let (record, fields) = (object(input, "record")?, object(input, "fields")?);
            let document_text = text(record, fields, "encrypted_specification_document")?;
            let committed = record
                .get("content_hash")
                .and_then(Value::as_str)
                .unwrap_or("");
            if format!("{:x}", Sha256::digest(document_text.as_bytes())) != committed {
                return Ok(refusal(
                    "Specification content does not match its recorded hash",
                ));
            }
            let Ok(document) = serde_json::from_str::<Value>(document_text) else {
                return Ok(refusal("Specification document is not valid JSON"));
            };
            let mut out = project(record, fields, REVISION)?;
            out.insert("document".into(), document);
            Ok(Value::Object(out))
        }
        "specificationApproveBody" => {
            let revision = object(input, "revision")?;
            let field = |name: &str| {
                revision
                    .get(name)
                    .filter(|value| value.as_str().is_some_and(|s| !s.is_empty()))
                    .cloned()
                    .ok_or_else(|| format!("missing_field:revision.{name}"))
            };
            member(input, "revision")?;
            Ok(
                json!({"revision_id": field("revision_id")?, "content_hash": field("content_hash")?}),
            )
        }
        "specificationCreatePlan" => create_plan(input),
        _ => Err(format!("unknown_op:{op}")),
    }
}

/// Validates the draft and fixes the exact plaintext the web seals and commits to.
fn create_plan(input: &Value) -> Decision {
    let id = |name: &str| -> Result<String, String> {
        let value = text_member(input, name)?;
        uuid::Uuid::parse_str(&value)
            .map(|parsed| parsed.to_string())
            .map_err(|_| format!("invalid_field:{name}"))
    };
    let (specification_id, revision_id) = (id("specification_id")?, id("revision_id")?);
    let document: SpecificationDocument =
        serde_json::from_value(member(input, "document")?.clone())
            .map_err(|error| format!("invalid_field:document ({error})"))?;
    if let Err(error) = document.validate() {
        return Ok(refusal(&error.to_string()));
    }
    let document_text = serde_json::to_string(&document)
        .map_err(|error| format!("invalid_field:document ({error})"))?;
    if document_text.len() > MAX_DOCUMENT_BYTES {
        return Ok(refusal("The Specification document is too large."));
    }
    Ok(json!({
        "specification_id": specification_id, "revision_id": revision_id,
        "content_hash": specification_content_hash(&document_text),
        "catalog_revision_id": DEFAULT_CATALOG_REVISION,
        "title": document.title.trim(), "summary": document.summary.trim(),
        "document_text": document_text,
    }))
}

fn text_member(input: &Value, name: &str) -> Result<String, String> {
    member(input, name)?
        .as_str()
        .map(str::to_owned)
        .ok_or_else(|| format!("invalid_field:{name}"))
}

const HEAD: &[(&str, Src)] = &[
    ("specification_id", Raw("specification_id")),
    ("title", Text("encrypted_title")),
    ("summary", Text("encrypted_summary")),
    ("status", Raw("status")),
    ("currentRevisionId", Or("current_revision_id", Null)),
    ("currentRevisionNumber", Or("current_revision_number", One)),
    ("version", Or("version", One)),
    ("createdAt", Raw("created_at")),
    ("updatedAt", Raw("updated_at")),
];

const REVISION: &[(&str, Src)] = &[
    ("revision_id", Raw("revision_id")),
    ("revisionNumber", Or("revision_number", One)),
    ("contentHash", Raw("content_hash")),
    ("approvalState", Or("approval_state", Null)),
    ("approvedAt", Or("approved_at", Null)),
    ("supersedesRevisionId", Or("supersedes_revision_id", Null)),
    ("title", Text("encrypted_title")),
    ("summary", Text("encrypted_summary")),
    ("createdAt", Raw("created_at")),
];
