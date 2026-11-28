use crate::CoreError;
use crate::core::CoreCancellation;
use crate::view_core::ViewModelCore;
use openmates_sdk::error::Error;
use openmates_sdk::view_model;
use serde_json::Value;
use std::sync::Arc;

/// One Specification card in a Project's list.
#[derive(Clone, Debug, PartialEq, Eq, uniffi::Record)]
pub struct ProjectSpecificationListItemRecord {
    /// Specification id.
    pub specification_id: String,
    /// Decrypted head title.
    pub title: String,
    /// Document category, `""` when unset.
    pub kind: String,
    /// `approved` when the current revision is approved, else `draft`.
    pub status: String,
    /// Number of the current revision.
    pub revision_number: u64,
    /// Unix seconds, 0 when unknown.
    pub updated_at: u64,
    /// Number of requirements of the current revision.
    pub requirement_count: u64,
    /// Requirements with proof state `passed`.
    pub proof_passed: u64,
    /// Requirements with proof state `open`.
    pub proof_open: u64,
    /// Requirements with proof state `stale`.
    pub proof_stale: u64,
}

/// One chapter of a document.
#[derive(Clone, Debug, PartialEq, Eq, uniffi::Record)]
pub struct ProjectSpecificationChapterRecord {
    pub id: String,
    pub title: String,
    pub introduction: String,
    pub requirement_ids: Vec<String>,
    pub flow_ids: Vec<String>,
    pub model_ids: Vec<String>,
}

/// One requirement with its optional proof projection.
#[derive(Clone, Debug, PartialEq, Eq, uniffi::Record)]
pub struct ProjectSpecificationRequirementRecord {
    pub id: String,
    pub statement: String,
    pub applies_to: Vec<String>,
    pub example: String,
    /// `passed`, `open` or `stale`, nil without a proof projection.
    pub proof_state: Option<String>,
    pub proof_title: Option<String>,
    pub proof_explanation: Option<String>,
}

/// One flow or edge case.
#[derive(Clone, Debug, PartialEq, Eq, uniffi::Record)]
pub struct ProjectSpecificationFlowRecord {
    pub id: String,
    pub title: String,
    pub kind: String,
    pub steps: Vec<String>,
    pub required_check_refs: Vec<String>,
}

/// One field of a data model.
#[derive(Clone, Debug, PartialEq, Eq, uniffi::Record)]
pub struct ProjectSpecificationFieldRecord {
    pub name: String,
    pub field_type: String,
    pub description: String,
}

/// One data model.
#[derive(Clone, Debug, PartialEq, Eq, uniffi::Record)]
pub struct ProjectSpecificationModelRecord {
    pub id: String,
    pub description: String,
    pub fields: Vec<ProjectSpecificationFieldRecord>,
}

/// A link to another Specification of the same split project.
#[derive(Clone, Debug, PartialEq, Eq, uniffi::Record)]
pub struct ProjectSpecificationRelatedRecord {
    pub title: String,
    pub role: String,
    pub relation: String,
}

/// The readable document of one revision.
#[derive(Clone, Debug, PartialEq, Eq, uniffi::Record)]
pub struct ProjectSpecificationDocumentRecord {
    pub title: String,
    pub project: String,
    pub category: String,
    pub summary: String,
    pub outcome: String,
    /// `product`, `design`, `technical` or `""`.
    pub role: String,
    pub scope_included: Vec<String>,
    pub scope_excluded: Vec<String>,
    pub assumptions: Vec<String>,
    pub design_decisions: Vec<String>,
    pub chapters: Vec<ProjectSpecificationChapterRecord>,
    pub requirements: Vec<ProjectSpecificationRequirementRecord>,
    pub flows: Vec<ProjectSpecificationFlowRecord>,
    pub models: Vec<ProjectSpecificationModelRecord>,
    pub related: Vec<ProjectSpecificationRelatedRecord>,
}

/// One entry of the revision history.
#[derive(Clone, Debug, PartialEq, Eq, uniffi::Record)]
pub struct ProjectSpecificationRevisionRecord {
    pub revision_id: String,
    pub revision_number: u64,
    /// Unix seconds, 0 when unknown.
    pub created_at: u64,
    pub summary: String,
    /// `approved`, `draft` (current, unapproved) or `superseded`.
    pub status: String,
    /// Commitment to the exact document text.
    pub content_hash: String,
}

/// One Specification opened at a revision, with its history.
#[derive(Clone, Debug, PartialEq, Eq, uniffi::Record)]
pub struct ProjectSpecificationOpenedRecord {
    pub specification_id: String,
    pub document: ProjectSpecificationDocumentRecord,
    /// Newest first.
    pub revisions: Vec<ProjectSpecificationRevisionRecord>,
    pub current_revision_id: String,
    pub viewed_revision_id: String,
    pub viewed_content_hash: String,
    /// `draft` (never approved), `approved` (current revision approved) or
    /// `stale` (an older revision is the approved one).
    pub approval_state: String,
    pub approved_revision_id: Option<String>,
    /// Unix seconds of the latest approval.
    pub approved_at: Option<u64>,
}

fn text(value: &Value, field: &str) -> Result<String, Error> {
    value[field]
        .as_str()
        .map(str::to_owned)
        .ok_or(Error::Protocol)
}

fn text_or_empty(value: &Value, field: &str) -> String {
    value[field].as_str().unwrap_or_default().to_owned()
}

fn opt_text(value: &Value, field: &str) -> Option<String> {
    value[field].as_str().map(str::to_owned)
}

fn texts(value: &Value) -> Vec<String> {
    value
        .as_array()
        .map(Vec::as_slice)
        .unwrap_or_default()
        .iter()
        .filter_map(|item| item.as_str().map(str::to_owned))
        .collect()
}

fn items(value: &Value) -> &[Value] {
    value.as_array().map(Vec::as_slice).unwrap_or_default()
}

fn proof_count(requirements: &[Value], state: &str) -> u64 {
    requirements
        .iter()
        .filter(|r| r["proof"]["state"] == state)
        .count() as u64
}

/// Marshal one `show` view into a list card. Pure so it is tested natively.
pub(crate) fn list_item_record(view: &Value) -> Result<ProjectSpecificationListItemRecord, Error> {
    let head = &view["specification"];
    let revision = &view["revision"];
    let requirements = items(&revision["document"]["requirements"]);
    Ok(ProjectSpecificationListItemRecord {
        specification_id: text(head, "specification_id")?,
        title: text(head, "title")?,
        kind: text_or_empty(&revision["document"], "category"),
        status: if revision["approval_state"] == "approved" {
            "approved"
        } else {
            "draft"
        }
        .to_owned(),
        revision_number: head["current_revision_number"].as_u64().unwrap_or(0),
        updated_at: head["updated_at"].as_u64().unwrap_or(0),
        requirement_count: requirements.len() as u64,
        proof_passed: proof_count(requirements, "passed"),
        proof_open: proof_count(requirements, "open"),
        proof_stale: proof_count(requirements, "stale"),
    })
}

fn document_record(doc: &Value) -> ProjectSpecificationDocumentRecord {
    ProjectSpecificationDocumentRecord {
        title: text_or_empty(doc, "title"),
        project: text_or_empty(doc, "project"),
        category: text_or_empty(doc, "category"),
        summary: text_or_empty(doc, "summary"),
        outcome: text_or_empty(doc, "outcome"),
        role: text_or_empty(doc, "role"),
        scope_included: texts(&doc["scope"]["included"]),
        scope_excluded: texts(&doc["scope"]["excluded"]),
        assumptions: texts(&doc["assumptions"]),
        design_decisions: texts(&doc["designDecisions"]),
        chapters: items(&doc["chapters"])
            .iter()
            .map(|c| ProjectSpecificationChapterRecord {
                id: text_or_empty(c, "id"),
                title: text_or_empty(c, "title"),
                introduction: text_or_empty(c, "introduction"),
                requirement_ids: texts(&c["requirementIds"]),
                flow_ids: texts(&c["flowIds"]),
                model_ids: texts(&c["modelIds"]),
            })
            .collect(),
        requirements: items(&doc["requirements"])
            .iter()
            .map(|r| ProjectSpecificationRequirementRecord {
                id: text_or_empty(r, "id"),
                statement: text_or_empty(r, "statement"),
                applies_to: texts(&r["appliesTo"]),
                example: text_or_empty(r, "example"),
                proof_state: opt_text(&r["proof"], "state"),
                proof_title: opt_text(&r["proof"], "title"),
                proof_explanation: opt_text(&r["proof"], "explanation"),
            })
            .collect(),
        flows: items(&doc["flows"])
            .iter()
            .map(|f| ProjectSpecificationFlowRecord {
                id: text_or_empty(f, "id"),
                title: text_or_empty(f, "title"),
                kind: text_or_empty(f, "kind"),
                steps: texts(&f["steps"]),
                required_check_refs: texts(&f["requiredCheckRefs"]),
            })
            .collect(),
        models: items(&doc["models"])
            .iter()
            .map(|m| ProjectSpecificationModelRecord {
                id: text_or_empty(m, "id"),
                description: text_or_empty(m, "description"),
                fields: items(&m["fields"])
                    .iter()
                    .map(|f| ProjectSpecificationFieldRecord {
                        name: text_or_empty(f, "name"),
                        field_type: text_or_empty(f, "type"),
                        description: text_or_empty(f, "description"),
                    })
                    .collect(),
            })
            .collect(),
        related: items(&doc["relatedSpecifications"])
            .iter()
            .map(|r| ProjectSpecificationRelatedRecord {
                title: text_or_empty(r, "title"),
                role: text_or_empty(r, "role"),
                relation: text_or_empty(r, "relation"),
            })
            .collect(),
    }
}

/// Marshal the open view, applying the web's status and approval rules.
/// Pure so it is tested natively.
pub(crate) fn opened_record(view: &Value) -> Result<ProjectSpecificationOpenedRecord, Error> {
    let head = &view["specification"];
    let viewed = &view["revision"];
    let viewed_revision_id = text(viewed, "revision_id")?;
    let current_revision_id =
        opt_text(head, "current_revision_id").unwrap_or_else(|| viewed_revision_id.clone());
    let raw = items(&view["revisions"]);
    let revisions = raw
        .iter()
        .map(|r| {
            let revision_id = text(r, "revision_id")?;
            let status = if r["approval_state"] == "approved" {
                "approved"
            } else if revision_id == current_revision_id {
                "draft"
            } else {
                "superseded"
            };
            Ok(ProjectSpecificationRevisionRecord {
                revision_number: r["revision_number"].as_u64().unwrap_or(0),
                created_at: r["created_at"].as_u64().unwrap_or(0),
                summary: text_or_empty(r, "summary"),
                status: status.to_owned(),
                content_hash: text_or_empty(r, "content_hash"),
                revision_id,
            })
        })
        .collect::<Result<Vec<_>, Error>>()?;
    let approved = raw
        .iter()
        .filter(|r| r["approval_state"] == "approved")
        .max_by_key(|r| r["revision_number"].as_u64().unwrap_or(0));
    let (approval_state, approved_revision_id, approved_at) = match approved {
        None => ("draft", None, None),
        Some(r) => {
            let id = text(r, "revision_id")?;
            let state = if id == current_revision_id {
                "approved"
            } else {
                "stale"
            };
            (state, Some(id), r["approved_at"].as_u64())
        }
    };
    Ok(ProjectSpecificationOpenedRecord {
        specification_id: text(head, "specification_id")?,
        document: document_record(&viewed["document"]),
        revisions,
        current_revision_id,
        viewed_revision_id,
        viewed_content_hash: text(viewed, "content_hash")?,
        approval_state: approval_state.to_owned(),
        approved_revision_id,
        approved_at,
    })
}

#[uniffi::export]
impl ViewModelCore {
    /// The Specifications of a Project as list cards. `team_id` is the Team of
    /// a Team Project, nil for Personal. Runs on the actor.
    ///
    /// # Errors
    /// `Authentication` when signed out; `Forbidden`; `Offline`; `Cancelled`.
    pub async fn project_specifications_list(
        &self,
        project_id: String,
        team_id: Option<String>,
        cancellation: Option<Arc<CoreCancellation>>,
    ) -> Result<Vec<ProjectSpecificationListItemRecord>, CoreError> {
        let (shared, token) = (self.shared.clone(), self.detached(cancellation));
        self.run(async move {
            let views = shared
                .signed_in(token, move |host, _sink, cancel| {
                    view_model::project_specifications_list(host, project_id, team_id, cancel)
                })
                .await?;
            views
                .iter()
                .map(list_item_record)
                .collect::<Result<Vec<_>, _>>()
        })
        .await
    }

    /// One Specification at a revision (`revision_id` nil: the current one)
    /// with its revision history and approval state.
    ///
    /// # Errors
    /// `Authentication` when signed out; `Forbidden`; `Offline`; `Cancelled`.
    pub async fn project_specification_open(
        &self,
        project_id: String,
        team_id: Option<String>,
        specification_id: String,
        revision_id: Option<String>,
        cancellation: Option<Arc<CoreCancellation>>,
    ) -> Result<ProjectSpecificationOpenedRecord, CoreError> {
        let (shared, token) = (self.shared.clone(), self.detached(cancellation));
        self.run(async move {
            let view = shared
                .signed_in(token, move |host, _sink, cancel| {
                    view_model::project_specification_open(
                        host,
                        project_id,
                        team_id,
                        specification_id,
                        revision_id,
                        cancel,
                    )
                })
                .await?;
            opened_record(&view)
        })
        .await
    }

    /// Approve exactly one revision; refused when `content_hash` is not the
    /// commitment of that revision.
    ///
    /// # Errors
    /// `Authentication` when signed out; `Conflict` on a hash mismatch;
    /// `Forbidden`; `Offline`; `Cancelled`.
    pub async fn project_specification_approve(
        &self,
        project_id: String,
        team_id: Option<String>,
        specification_id: String,
        revision_id: String,
        content_hash: String,
        cancellation: Option<Arc<CoreCancellation>>,
    ) -> Result<(), CoreError> {
        let (shared, token) = (self.shared.clone(), self.detached(cancellation));
        self.run(async move {
            shared
                .signed_in(token, move |host, _sink, cancel| {
                    view_model::project_specification_approve(
                        host,
                        project_id,
                        team_id,
                        specification_id,
                        revision_id,
                        content_hash,
                        cancel,
                    )
                })
                .await
        })
        .await
    }
}

#[cfg(test)]
#[path = "view_project_specifications_tests.rs"]
mod tests;
