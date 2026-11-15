//! Project timeline and whole-commit restore on `ViewModelCore`. Bindings only
//! marshal over `openmates_sdk::view_model::project_timeline`; the per-file
//! `change` of a commit row is derived from the next older commit of the same
//! page. Plan `project-timeline`; the web twin is `ProjectTimeline.svelte`.
use crate::CoreError;
use crate::core::CoreCancellation;
use crate::view_core::ViewModelCore;
use openmates_sdk::view_model;
use openmates_sdk::work::{
    ProjectCommit, ProjectCommitAuthor, ProjectTimelineEntry, ProjectTimelineKind,
    ProjectTimelinePage,
};
use std::sync::Arc;

/// One file of a commit row.
#[derive(Clone, Debug, PartialEq, Eq, uniffi::Record)]
pub struct ProjectTimelineCommitFileRecord {
    /// Decrypted Project path; nil when the commit carried no path map.
    pub path: Option<String>,
    /// Embed version the commit recorded.
    pub version: u64,
    /// `added`, `modified` or `unchanged` against the next older commit of the
    /// page; nil when no older commit is known.
    pub change: Option<String>,
}

/// The commit of a commit row.
#[derive(Clone, Debug, PartialEq, Eq, uniffi::Record)]
pub struct ProjectTimelineCommitRecord {
    /// Commit id.
    pub commit_id: String,
    /// Decrypted commit message.
    pub message: String,
    /// Commit the restore came from, if any.
    pub restored_from_commit_id: Option<String>,
    /// Files of the snapshot.
    pub files: Vec<ProjectTimelineCommitFileRecord>,
}

/// One timeline row.
#[derive(Clone, Debug, PartialEq, Eq, uniffi::Record)]
pub struct ProjectTimelineEntryRecord {
    /// `commit`, `file_version` or `file_operation`.
    pub kind: String,
    /// Stable row id.
    pub id: String,
    /// Unix seconds.
    pub created_at: u64,
    /// `user` or `assistant`.
    pub author: String,
    /// File path; nil shows "Removed file".
    pub path: Option<String>,
    /// File version, when the row is a file version.
    pub version: Option<u64>,
    /// Server action (`create`, `update`, `restore`, `rename`, ...).
    pub action: Option<String>,
    /// Version a restore row came from.
    pub restored_from_version: Option<u64>,
    /// Set for `commit` rows.
    pub commit: Option<ProjectTimelineCommitRecord>,
}

/// One page of the timeline, newest first.
#[derive(Clone, Debug, PartialEq, Eq, uniffi::Record)]
pub struct ProjectTimelinePageRecord {
    /// Rows in the server's order.
    pub entries: Vec<ProjectTimelineEntryRecord>,
    /// Cursor for the next page; nil at the end.
    pub next_cursor: Option<String>,
}

/// Result of restoring a commit.
#[derive(Clone, Debug, PartialEq, Eq, uniffi::Record)]
pub struct ProjectCommitRestoreRecord {
    /// The commit that was restored.
    pub source_commit_id: String,
    /// The new commit recording the restore.
    pub commit_id: String,
    /// Files refused (conflicting path, unknown embed, ...); the rest was restored.
    pub refused_count: u64,
}

fn author_name(author: ProjectCommitAuthor) -> &'static str {
    match author {
        ProjectCommitAuthor::User => "user",
        ProjectCommitAuthor::Assistant => "assistant",
    }
}

fn commit_record(
    commit: &ProjectCommit,
    older: Option<&ProjectCommit>,
) -> ProjectTimelineCommitRecord {
    let files = commit
        .files
        .iter()
        .map(|file| {
            let change = older.map(|older| {
                match older
                    .files
                    .iter()
                    .find(|o| o.target_id_hash == file.target_id_hash)
                {
                    None => "added",
                    Some(o) if o.embed_version == file.embed_version => "unchanged",
                    Some(_) => "modified",
                }
                .to_owned()
            });
            ProjectTimelineCommitFileRecord {
                path: file.path.clone(),
                version: file.embed_version,
                change,
            }
        })
        .collect();
    ProjectTimelineCommitRecord {
        commit_id: commit.commit_id.clone(),
        message: commit.message.clone(),
        restored_from_commit_id: commit.restored_from_commit_id.clone(),
        files,
    }
}

/// Marshal a core page. Pure so it is tested natively.
pub(crate) fn page_record(page: &ProjectTimelinePage) -> ProjectTimelinePageRecord {
    let commits: Vec<&ProjectCommit> = page
        .entries
        .iter()
        .filter_map(|entry| entry.commit.as_ref())
        .collect();
    let mut commit_index = 0;
    let entries = page
        .entries
        .iter()
        .map(|entry| entry_record(entry, &commits, &mut commit_index))
        .collect();
    ProjectTimelinePageRecord {
        entries,
        next_cursor: page.next_cursor.clone(),
    }
}

fn entry_record(
    entry: &ProjectTimelineEntry,
    commits: &[&ProjectCommit],
    commit_index: &mut usize,
) -> ProjectTimelineEntryRecord {
    let kind = match entry.kind {
        ProjectTimelineKind::Commit => "commit",
        ProjectTimelineKind::FileVersion => "file_version",
        ProjectTimelineKind::FileOperation => "file_operation",
    };
    let commit = entry.commit.as_ref().map(|commit| {
        let older = commits.get(*commit_index + 1).copied();
        *commit_index += 1;
        commit_record(commit, older)
    });
    ProjectTimelineEntryRecord {
        kind: kind.to_owned(),
        id: entry.id.clone(),
        created_at: entry.created_at,
        author: author_name(entry.author).to_owned(),
        path: entry.path.clone(),
        version: entry.version,
        action: entry.action.clone(),
        restored_from_version: entry.restored_from_version,
        commit,
    }
}

#[uniffi::export]
impl ViewModelCore {
    /// One page of the Project timeline, newest first (`limit` 1..=100).
    /// `before` is the previous page's `next_cursor`; `team_id` is the Team of
    /// a Team Project, nil for Personal. Runs on the actor.
    ///
    /// # Errors
    /// `Authentication` when signed out; `Invalid`; `Forbidden`; `Offline`;
    /// `Cancelled`.
    pub async fn project_timeline(
        &self,
        project_id: String,
        team_id: Option<String>,
        limit: Option<u64>,
        before: Option<String>,
        cancellation: Option<Arc<CoreCancellation>>,
    ) -> Result<ProjectTimelinePageRecord, CoreError> {
        let (shared, token) = (self.shared.clone(), self.detached(cancellation));
        self.run(async move {
            let page = shared
                .signed_in(token, move |host, _sink, cancel| {
                    view_model::project_timeline(host, project_id, team_id, limit, before, cancel)
                })
                .await?;
            Ok::<_, openmates_sdk::error::Error>(page_record(&page))
        })
        .await
    }

    /// Restore every file of `commit_id` as new versions; later history is
    /// kept. `operation_id` is a UUID that makes a retry idempotent.
    ///
    /// # Errors
    /// `Authentication` when signed out; `Invalid` when nothing could be
    /// restored; `Forbidden`; `Offline`; `Cancelled`.
    pub async fn restore_project_commit(
        &self,
        project_id: String,
        team_id: Option<String>,
        commit_id: String,
        operation_id: String,
        cancellation: Option<Arc<CoreCancellation>>,
    ) -> Result<ProjectCommitRestoreRecord, CoreError> {
        let (shared, token) = (self.shared.clone(), self.detached(cancellation));
        self.run(async move {
            let restored = shared
                .signed_in(token, move |host, _sink, cancel| {
                    view_model::restore_project_commit(
                        host,
                        project_id,
                        team_id,
                        commit_id,
                        operation_id,
                        cancel,
                    )
                })
                .await?;
            let refused = restored
                .files
                .iter()
                .filter(|file| {
                    matches!(
                        file.outcome,
                        openmates_sdk::client::ProjectCommitFileOutcome::Refused { .. }
                    )
                })
                .count();
            Ok::<_, openmates_sdk::error::Error>(ProjectCommitRestoreRecord {
                source_commit_id: restored.source_commit_id,
                commit_id: restored.commit.commit_id,
                refused_count: refused as u64,
            })
        })
        .await
    }
}

#[cfg(test)]
#[path = "view_project_timeline_tests.rs"]
mod tests;
