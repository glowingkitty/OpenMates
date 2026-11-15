//! Worker export of the Project Timeline tab (`projectTimeline` unit).
//! Marshalling only: the page of rows, path resolution and the presentation
//! JSON (`to_presentation_json`) are the core's, as is the whole-commit user
//! restore (`Client::restore_project_commit`). Spec: feature.projects
//! `projects.history.native-commits`.
use super::BrowserCoreClient;
use openmates_sdk::Error;
use openmates_sdk::client::{ProjectCommitFileOutcome, ProjectCommitUserRestore};
use openmates_sdk::work::ProjectFilters;
use wasm_bindgen::prelude::*;

/// Stable code of a core refusal; never internal text.
fn code(error: Error) -> JsValue {
    if let Some(code) = error.sdk_code() {
        return JsValue::from_str(code);
    }
    // Exhaustive on purpose: the Timeline tab shows this code, so a refusal must
    // keep its cause (`native_session_required`, `forbidden`, ...) instead of
    // collapsing into one generic "unavailable".
    JsValue::from_str(match error {
        Error::Invalid(_) => "invalid_request",
        Error::Locked => "locked",
        Error::Crypto => "crypto",
        Error::Protocol => "protocol",
        Error::Cancelled => "cancelled",
        Error::Unavailable { code, .. } => code,
        Error::Authentication => "authentication",
        Error::TwoFactorRequired => "two_factor_required",
        Error::SignupRequired => "signup_required",
        Error::Offline => "offline",
        Error::Forbidden => "forbidden",
        Error::Expired => "expired",
        Error::VerificationRequired => "verification_required",
        Error::Io => "io",
        Error::Conflict => "conflict",
    })
}

/// Presentation JSON of a user restore: `{commitId, files:[{path, outcome,
/// version?, reason?}]}`; `commitId` is the new restore commit.
fn restore_presentation(restore: &ProjectCommitUserRestore) -> serde_json::Value {
    let files: Vec<serde_json::Value> = restore
        .files
        .iter()
        .map(|file| {
            let mut row = serde_json::json!({ "path": file.path });
            let (outcome, version, reason) = match &file.outcome {
                ProjectCommitFileOutcome::Restored { version } => {
                    ("restored", Some(*version), None)
                }
                ProjectCommitFileOutcome::Unchanged => ("unchanged", None, None),
                ProjectCommitFileOutcome::Relinked { version } => {
                    ("relinked", Some(*version), None)
                }
                ProjectCommitFileOutcome::Refused { reason } => ("refused", None, Some(reason)),
            };
            row["outcome"] = outcome.into();
            if let Some(version) = version {
                row["version"] = version.into();
            }
            if let Some(reason) = reason {
                row["reason"] = reason.as_str().into();
            }
            row
        })
        .collect();
    serde_json::json!({ "commitId": restore.commit.commit_id, "files": files })
}

#[wasm_bindgen]
impl BrowserCoreClient {
    /// One newest-first page of the Project timeline as `{entries, nextCursor}`
    /// presentation JSON. `team` (a Team id) scopes the read to that Team;
    /// `before` is the previous page's `nextCursor`.
    pub async fn project_timeline_page(
        &mut self,
        handle: &str,
        generation: f64,
        selector: &str,
        limit: Option<u32>,
        before: Option<String>,
        team: Option<String>,
    ) -> Result<String, JsValue> {
        self.status(handle, generation)?;
        let filters = ProjectFilters {
            team_id: team,
            ..Default::default()
        };
        let page = self
            .client
            .projects()
            .with_filters(filters)
            .timeline(selector, limit.map(u64::from), before)
            .await
            .map_err(code)?;
        self.status(handle, generation)?;
        serde_json::to_string(&page.to_presentation_json())
            .map_err(|_| JsValue::from_str("protocol"))
    }

    /// Restore a whole Project commit as the signed-in user and return
    /// `{commitId, files}` presentation JSON (see `restore_presentation`).
    /// `team` scopes a Team Project; `message` overrides the default message.
    pub async fn project_commit_restore(
        &mut self,
        handle: &str,
        generation: f64,
        project_id: &str,
        team: Option<String>,
        commit_id: &str,
        message: Option<String>,
    ) -> Result<String, JsValue> {
        self.status(handle, generation)?;
        let restore = self
            .client
            .restore_project_commit(project_id, team.as_deref(), commit_id, message, None)
            .await
            .map_err(code)?;
        self.status(handle, generation)?;
        serde_json::to_string(&restore_presentation(&restore))
            .map_err(|_| JsValue::from_str("protocol"))
    }
}
