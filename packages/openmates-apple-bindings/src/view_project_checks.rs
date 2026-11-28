use crate::CoreError;
use crate::core::CoreCancellation;
use crate::view_core::ViewModelCore;
use openmates_sdk::error::Error;
use openmates_sdk::view_model;
use serde_json::Value;
use std::sync::Arc;

/// One Check in a Project's list.
#[derive(Clone, Debug, PartialEq, Eq, uniffi::Record)]
pub struct ProjectCheckHeadRecord {
    /// Check id.
    pub check_id: String,
    /// `active` or `archived`.
    pub status: String,
    /// Id of the current revision.
    pub current_revision_id: String,
    /// Number of the current revision (1-based).
    pub current_revision_number: u64,
    /// Decrypted title.
    pub title: String,
    /// Decrypted description, if any.
    pub description: Option<String>,
}

/// One source of a revision.
#[derive(Clone, Debug, PartialEq, Eq, uniffi::Record)]
pub struct ProjectCheckSourceRecord {
    /// Stable id of the source inside the Check (`s1`, ...).
    pub binding_id: String,
    /// `e2e`, `static_analysis`, `ai_evaluation`, `human_confirmation`, ...
    pub kind: String,
    /// `required` or `supporting`.
    pub role: String,
    /// Decrypted source title.
    pub title: String,
    /// Test path, selector, AI question or human instruction.
    pub reference: String,
}

/// The current revision of a Check.
#[derive(Clone, Debug, PartialEq, Eq, uniffi::Record)]
pub struct ProjectCheckRevisionRecord {
    /// Revision id.
    pub revision_id: String,
    /// Revision number (1-based).
    pub revision_number: u64,
    /// Whether a pass needs a deterministic source.
    pub requires_deterministic: bool,
    /// Sources in definition order.
    pub sources: Vec<ProjectCheckSourceRecord>,
}

/// The result of one source in a run.
#[derive(Clone, Debug, PartialEq, Eq, uniffi::Record)]
pub struct ProjectCheckSourceResultRecord {
    /// Source this result belongs to.
    pub binding_id: String,
    /// Server status: `pending`, `passed`, `failed`, `waived`, ...
    pub status: String,
    /// Status to show: pending becomes `waiting_for_confirmation` (human
    /// source) or `queued`, waived `passed`, skipped `cancelled`, blocked
    /// `error`; otherwise the server status.
    pub display_status: String,
    /// Human decision (`confirmed`, `rejected`, `blocked`, `waived`), if any.
    pub human_decision: Option<String>,
    /// Decrypted detail or note.
    pub detail: Option<String>,
    /// Embed holding the test result, if any.
    pub test_result_embed_id: Option<String>,
}

/// The latest run of a Check.
#[derive(Clone, Debug, PartialEq, Eq, uniffi::Record)]
pub struct ProjectCheckRunRecord {
    /// Run id.
    pub run_id: String,
    /// Revision the run was made against.
    pub check_revision_id: String,
    /// Server run status.
    pub status: String,
    /// Aggregate of the source results (`passed`, `failed`,
    /// `waiting_for_confirmation`, ...); equals `status` when unknown.
    pub aggregate_status: String,
    /// True when a passed run no longer matches the current revision.
    pub stale: bool,
    /// Unix seconds.
    pub created_at: u64,
    /// Unix seconds; nil while running.
    pub finished_at: Option<u64>,
    /// Decrypted run summary, if any.
    pub summary: Option<String>,
    /// One result per reported source.
    pub source_results: Vec<ProjectCheckSourceResultRecord>,
}

/// One Check with its current revision and latest run.
#[derive(Clone, Debug, PartialEq, Eq, uniffi::Record)]
pub struct ProjectCheckDetailRecord {
    /// Head of the Check.
    pub check: ProjectCheckHeadRecord,
    /// Current revision.
    pub revision: ProjectCheckRevisionRecord,
    /// Latest run; nil when never run.
    pub latest_run: Option<ProjectCheckRunRecord>,
    /// Aggregate of the latest run when it is for the current revision, else
    /// `never_run`.
    pub aggregate: String,
    /// True when runs exist but none for the current revision, or the core
    /// flags the latest run as stale.
    pub stale: bool,
}

fn text(value: &Value, field: &str) -> Result<String, Error> {
    value[field]
        .as_str()
        .map(str::to_owned)
        .ok_or(Error::Protocol)
}

fn opt_text(value: &Value, field: &str) -> Option<String> {
    value[field].as_str().map(str::to_owned)
}

/// Marshal one head view of the core. Pure so it is tested natively.
pub(crate) fn head_record(head: &Value) -> Result<ProjectCheckHeadRecord, Error> {
    Ok(ProjectCheckHeadRecord {
        check_id: text(head, "check_id")?,
        status: text(head, "status")?,
        current_revision_id: text(head, "current_revision_id")?,
        current_revision_number: head["current_revision_number"].as_u64().unwrap_or(0),
        title: text(head, "title")?,
        description: opt_text(head, "description"),
    })
}

fn revision_record(revision: &Value) -> Result<ProjectCheckRevisionRecord, Error> {
    let sources = revision["definition"]["sources"]
        .as_array()
        .ok_or(Error::Protocol)?
        .iter()
        .map(|source| {
            Ok(ProjectCheckSourceRecord {
                binding_id: text(source, "source_binding_id")?,
                kind: text(source, "source_kind")?,
                role: text(source, "role")?,
                title: opt_text(source, "title").unwrap_or_default(),
                reference: opt_text(source, "ref").unwrap_or_default(),
            })
        })
        .collect::<Result<Vec<_>, Error>>()?;
    Ok(ProjectCheckRevisionRecord {
        revision_id: text(revision, "revision_id")?,
        revision_number: revision["revision_number"].as_u64().unwrap_or(0),
        requires_deterministic: revision["requires_deterministic"]
            .as_bool()
            .unwrap_or(false),
        sources,
    })
}

/// Status to show for a source result, as the web's `resultStatus`.
pub(crate) fn display_status(kind: &str, status: &str) -> String {
    match status {
        "pending" if kind == "human_confirmation" => "waiting_for_confirmation",
        "pending" => "queued",
        "waived" => "passed",
        "skipped" => "cancelled",
        "blocked" => "error",
        other => other,
    }
    .to_owned()
}

fn run_record(
    run: &Value,
    sources: &[ProjectCheckSourceRecord],
) -> Result<ProjectCheckRunRecord, Error> {
    let source_results = run["source_results"]
        .as_array()
        .map(Vec::as_slice)
        .unwrap_or_default()
        .iter()
        .map(|result| {
            let binding_id = text(result, "source_binding_id")?;
            let status = text(result, "status")?;
            let kind = sources
                .iter()
                .find(|s| s.binding_id == binding_id)
                .map_or("", |s| s.kind.as_str());
            Ok(ProjectCheckSourceResultRecord {
                display_status: display_status(kind, &status),
                binding_id,
                status,
                human_decision: opt_text(result, "human_decision"),
                detail: opt_text(result, "detail"),
                test_result_embed_id: opt_text(result, "test_result_embed_id"),
            })
        })
        .collect::<Result<Vec<_>, Error>>()?;
    let status = text(run, "status")?;
    Ok(ProjectCheckRunRecord {
        run_id: text(run, "run_id")?,
        check_revision_id: text(run, "check_revision_id")?,
        aggregate_status: opt_text(run, "aggregate_status").unwrap_or_else(|| status.clone()),
        status,
        stale: run["stale"].as_bool().unwrap_or(false),
        created_at: run["created_at"].as_u64().unwrap_or(0),
        finished_at: run["finished_at"].as_u64(),
        summary: opt_text(run, "summary"),
        source_results,
    })
}

/// Marshal the core's `show` view. Pure so it is tested natively.
pub(crate) fn detail_record(view: &Value) -> Result<ProjectCheckDetailRecord, Error> {
    let check = head_record(&view["check"])?;
    let revision = revision_record(&view["revision"])?;
    let latest_run = if view["latest_run"].is_null() {
        None
    } else {
        Some(run_record(&view["latest_run"], &revision.sources)?)
    };
    let (aggregate, stale) = match &latest_run {
        Some(run) if run.check_revision_id == check.current_revision_id => {
            (run.aggregate_status.clone(), run.stale)
        }
        Some(_) => ("never_run".to_owned(), true),
        None => ("never_run".to_owned(), false),
    };
    Ok(ProjectCheckDetailRecord {
        check,
        revision,
        latest_run,
        aggregate,
        stale,
    })
}

#[uniffi::export]
impl ViewModelCore {
    /// The Checks of a Project as full records (one call). `team_id` is the Team of a Team Project, nil
    /// for Personal. Runs on the actor.
    ///
    /// # Errors
    /// `Authentication` when signed out; `Forbidden`; `Offline`; `Cancelled`.
    pub async fn project_checks_list(
        &self,
        project_id: String,
        team_id: Option<String>,
        cancellation: Option<Arc<CoreCancellation>>,
    ) -> Result<Vec<ProjectCheckDetailRecord>, CoreError> {
        let (shared, token) = (self.shared.clone(), self.detached(cancellation));
        self.run(async move {
            let views = shared
                .signed_in(token, move |host, _sink, cancel| {
                    view_model::project_checks_list(host, project_id, team_id, cancel)
                })
                .await?;
            views
                .iter()
                .map(detail_record)
                .collect::<Result<Vec<_>, _>>()
        })
        .await
    }

    /// One Check with its current revision, latest run, per-source results and
    /// stale flag.
    ///
    /// # Errors
    /// `Authentication` when signed out; `Forbidden`; `Offline`; `Cancelled`.
    pub async fn project_check_show(
        &self,
        project_id: String,
        team_id: Option<String>,
        check_id: String,
        cancellation: Option<Arc<CoreCancellation>>,
    ) -> Result<ProjectCheckDetailRecord, CoreError> {
        let (shared, token) = (self.shared.clone(), self.detached(cancellation));
        self.run(async move {
            let view = shared
                .signed_in(token, move |host, _sink, cancel| {
                    view_model::project_check_show(host, project_id, team_id, check_id, cancel)
                })
                .await?;
            detail_record(&view)
        })
        .await
    }

    /// Start a run on the Check's current revision; returns the run id.
    ///
    /// # Errors
    /// `Authentication` when signed out; `Forbidden`; `Offline`; `Cancelled`.
    pub async fn project_check_start_run(
        &self,
        project_id: String,
        team_id: Option<String>,
        check_id: String,
        cancellation: Option<Arc<CoreCancellation>>,
    ) -> Result<String, CoreError> {
        let (shared, token) = (self.shared.clone(), self.detached(cancellation));
        self.run(async move {
            shared
                .signed_in(token, move |host, _sink, cancel| {
                    view_model::project_check_start_run(host, project_id, team_id, check_id, cancel)
                })
                .await
        })
        .await
    }

    /// Record the human decision (`confirmed`, `rejected`, `blocked`,
    /// `waived`) of a pending human source, with an optional note.
    ///
    /// # Errors
    /// `Authentication` when signed out; `Invalid` for an unknown decision;
    /// `Forbidden`; `Offline`; `Cancelled`.
    pub async fn project_check_confirm_human(
        &self,
        project_id: String,
        team_id: Option<String>,
        check_id: String,
        run_id: String,
        binding_id: String,
        decision: String,
        note: Option<String>,
        cancellation: Option<Arc<CoreCancellation>>,
    ) -> Result<(), CoreError> {
        let (shared, token) = (self.shared.clone(), self.detached(cancellation));
        self.run(async move {
            shared
                .signed_in(token, move |host, _sink, cancel| {
                    view_model::project_check_confirm_human(
                        host, project_id, team_id, check_id, run_id, binding_id, decision, note,
                        cancel,
                    )
                })
                .await
        })
        .await
    }
}

#[cfg(test)]
#[path = "view_project_checks_tests.rs"]
mod tests;
