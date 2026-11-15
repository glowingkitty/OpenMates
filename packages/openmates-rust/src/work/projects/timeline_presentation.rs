//! Presentation JSON of a Project timeline page for the web Timeline tab.
//! The shape matches `ProjectTimeline.types.ts` (camelCase, Unix seconds); the
//! browser binding only forwards it. Spec: docs/plans/project-timeline/plan.yml.

use super::*;
use serde_json::json;

fn author(value: ProjectCommitAuthor) -> &'static str {
    match value {
        ProjectCommitAuthor::User => "user",
        ProjectCommitAuthor::Assistant => "assistant",
    }
}

fn kind(value: ProjectTimelineKind) -> &'static str {
    match value {
        ProjectTimelineKind::Commit => "commit",
        ProjectTimelineKind::FileVersion => "file_version",
        ProjectTimelineKind::FileOperation => "file_operation",
    }
}

fn path_source(value: ProjectTimelinePathSource) -> &'static str {
    match value {
        ProjectTimelinePathSource::Live => "live",
        ProjectTimelinePathSource::Commit => "commit",
        ProjectTimelinePathSource::Unknown => "unknown",
    }
}

fn commit_json(commit: &ProjectCommit) -> Value {
    // Files without a recorded path cannot be opened or named, so they are not
    // listed; a commit stores no per-file change kind, so none is reported.
    let files: Vec<Value> = commit
        .files
        .iter()
        .filter_map(|file| {
            file.path
                .as_deref()
                .map(|path| json!({"path": path, "version": file.embed_version}))
        })
        .collect();
    json!({
        "id": commit.commit_id,
        "message": commit.message,
        "author": author(commit.author),
        "restoredFrom": commit.restored_from_commit_id,
        "files": files,
    })
}

impl ProjectTimelinePage {
    /// The page as `{entries, nextCursor}` presentation JSON.
    pub fn to_presentation_json(&self) -> Value {
        let entries: Vec<Value> = self
            .entries
            .iter()
            .map(|entry| {
                json!({
                    "kind": kind(entry.kind),
                    "id": entry.id,
                    "createdAt": entry.created_at,
                    "author": author(entry.author),
                    "path": entry.path,
                    "pathSource": path_source(entry.path_source),
                    "version": entry.version,
                    "action": entry.action,
                    "restoredFromVersion": entry.restored_from_version,
                    "commit": entry.commit.as_ref().map(commit_json),
                })
            })
            .collect();
        json!({"entries": entries, "nextCursor": self.next_cursor})
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn maps_commit_entries_and_cursor() {
        let commit = ProjectCommit {
            commit_id: "c1".into(),
            message: "Add notes".into(),
            author: ProjectCommitAuthor::Assistant,
            chat_id_hash: None,
            files: vec![
                ProjectCommitEntry {
                    target_id_hash: "h1".into(),
                    path: Some("a/notes.md".into()),
                    target_id: None,
                    embed_version: 3,
                },
                ProjectCommitEntry {
                    target_id_hash: "h2".into(),
                    path: None,
                    target_id: None,
                    embed_version: 1,
                },
            ],
            restored_from_commit_id: Some("c0".into()),
            created_at: 10,
        };
        let page = ProjectTimelinePage {
            entries: vec![ProjectTimelineEntry {
                kind: ProjectTimelineKind::Commit,
                id: "c1".into(),
                created_at: 10,
                author: ProjectCommitAuthor::Assistant,
                target_id_hash: None,
                path: None,
                path_source: ProjectTimelinePathSource::Unknown,
                version: None,
                action: None,
                restored_from_version: None,
                commit: Some(commit),
            }],
            next_cursor: Some("cur".into()),
        };
        let out = page.to_presentation_json();
        assert_eq!(out["nextCursor"], "cur");
        let entry = &out["entries"][0];
        assert_eq!(entry["kind"], "commit");
        assert_eq!(entry["pathSource"], "unknown");
        assert_eq!(entry["author"], "assistant");
        assert_eq!(entry["createdAt"], 10);
        assert_eq!(entry["commit"]["restoredFrom"], "c0");
        assert_eq!(entry["commit"]["files"].as_array().map(Vec::len), Some(1));
        assert_eq!(entry["commit"]["files"][0]["path"], "a/notes.md");
        assert_eq!(entry["commit"]["files"][0]["version"], 3);
        assert!(entry["commit"]["files"][0].get("change").is_none());
    }

    #[test]
    fn maps_file_version_entry_without_commit() {
        let page = ProjectTimelinePage {
            entries: vec![ProjectTimelineEntry {
                kind: ProjectTimelineKind::FileVersion,
                id: "e1".into(),
                created_at: 5,
                author: ProjectCommitAuthor::User,
                target_id_hash: Some("h".into()),
                path: Some("x.md".into()),
                path_source: ProjectTimelinePathSource::Live,
                version: Some(2),
                action: Some("edit".into()),
                restored_from_version: Some(1),
                commit: None,
            }],
            next_cursor: None,
        };
        let out = page.to_presentation_json();
        assert!(out["nextCursor"].is_null());
        assert!(out["entries"][0]["commit"].is_null());
        assert_eq!(out["entries"][0]["kind"], "file_version");
        assert_eq!(out["entries"][0]["restoredFromVersion"], 1);
    }
}
