//! `openmates projects timeline`: thin CLI adapter over the core `Projects::timeline`.
//! Parses flags, calls the core and renders one line per entry, newest first.

use super::*;
use openmates_sdk::work::{
    ProjectCommitAuthor, ProjectTimelineEntry, ProjectTimelineKind, ProjectTimelinePathSource,
};

fn present(entry: &ProjectTimelineEntry) -> Value {
    json!({
        "kind": match entry.kind {
            ProjectTimelineKind::Commit => "commit",
            ProjectTimelineKind::FileVersion => "file_version",
            ProjectTimelineKind::FileOperation => "file_operation",
        },
        "id": entry.id,
        "created_at": entry.created_at,
        "author": entry.author,
        "target_id_hash": entry.target_id_hash,
        "path": entry.path,
        "path_source": match entry.path_source {
            ProjectTimelinePathSource::Live => "live",
            ProjectTimelinePathSource::Commit => "commit",
            ProjectTimelinePathSource::Unknown => "unknown",
        },
        "version": entry.version,
        "action": entry.action,
        "restored_from_version": entry.restored_from_version,
        "commit_message": entry.commit.as_ref().map(|c| c.message.clone()),
        "commit_id": entry.commit.as_ref().map(|c| c.commit_id.clone()),
    })
}

fn line(entry: &ProjectTimelineEntry) -> String {
    let author = match entry.author {
        ProjectCommitAuthor::User => "user",
        ProjectCommitAuthor::Assistant => "assistant",
    };
    let what = match (&entry.kind, &entry.action) {
        (ProjectTimelineKind::Commit, _) => "commit".to_owned(),
        (ProjectTimelineKind::FileVersion, action) => {
            format!("version {}", action.as_deref().unwrap_or("update"))
        }
        (ProjectTimelineKind::FileOperation, action) => {
            format!("file {}", action.as_deref().unwrap_or("change"))
        }
    };
    let path = match &entry.commit {
        Some(commit) => commit.message.lines().next().unwrap_or("").to_owned(),
        None => entry.path.clone().unwrap_or_else(|| "Removed file".into()),
    };
    let version = entry.version.map(|v| format!(" v{v}")).unwrap_or_default();
    format!("{}  {author}  {what}{version}  {path}", entry.created_at)
}

/// `projects timeline <project> [--limit <n>] [--before <cursor>]`
pub(super) async fn execute(
    i: &Invocation,
    service: &mut Projects<'_>,
) -> Result<CliOutput, CliError> {
    check(i, &["limit", "before"])?;
    let limit = match input::text(i, "limit")? {
        None => None,
        Some(raw) => Some(
            raw.parse::<u64>()
                .ok()
                .filter(|value| (1..=100).contains(value))
                .ok_or_else(|| CliError::Contract {
                    code: "invalid_limit",
                    message: "--limit must be between 1 and 100.".into(),
                })?,
        ),
    };
    let before = input::text(i, "before")?.map(str::to_owned);
    let page = service
        .timeline(input::positional(i, 0, "Project")?, limit, before)
        .await?;
    let text = if page.entries.is_empty() {
        "No Project timeline entries.".to_owned()
    } else {
        page.entries.iter().map(line).collect::<Vec<_>>().join("\n")
    };
    let value = json!({"entries": page.entries.iter().map(present).collect::<Vec<_>>(),
        "next_cursor": page.next_cursor});
    output(i, value, text)
}
