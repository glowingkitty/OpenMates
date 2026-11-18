use super::*;
use openmates_sdk::work::{ProjectCommitEntry, ProjectTimelinePathSource};

fn files(items: &[(&str, u64)]) -> Vec<ProjectCommitEntry> {
    items
        .iter()
        .map(|(path, version)| ProjectCommitEntry {
            target_id_hash: format!("hash-{path}"),
            path: Some((*path).to_owned()),
            target_id: None,
            embed_version: *version,
        })
        .collect()
}

fn commit(id: &str, items: &[(&str, u64)]) -> ProjectCommit {
    ProjectCommit {
        commit_id: id.into(),
        message: format!("message {id}"),
        author: ProjectCommitAuthor::Assistant,
        chat_id_hash: None,
        files: files(items),
        restored_from_commit_id: None,
        created_at: 10,
    }
}

fn entry(
    kind: ProjectTimelineKind,
    id: &str,
    commit: Option<ProjectCommit>,
) -> ProjectTimelineEntry {
    ProjectTimelineEntry {
        kind,
        id: id.into(),
        created_at: 100,
        author: ProjectCommitAuthor::User,
        target_id_hash: None,
        path: None,
        path_source: ProjectTimelinePathSource::Unknown,
        version: Some(2),
        action: Some("delete".into()),
        restored_from_version: None,
        commit,
    }
}

#[test]
fn timeline_page_marshals_rows_and_derives_commit_changes() {
    let page = ProjectTimelinePage {
        entries: vec![
            entry(
                ProjectTimelineKind::Commit,
                "c2",
                Some(commit("c2", &[("a.md", 3), ("b.md", 1), ("c.md", 1)])),
            ),
            entry(ProjectTimelineKind::FileOperation, "op", None),
            entry(
                ProjectTimelineKind::Commit,
                "c1",
                Some(commit("c1", &[("a.md", 2), ("b.md", 1)])),
            ),
        ],
        next_cursor: Some("next".into()),
    };
    let record = page_record(&page);
    assert_eq!(record.next_cursor.as_deref(), Some("next"));
    assert_eq!(record.entries[1].kind, "file_operation");
    assert_eq!(record.entries[1].path, None);
    assert_eq!(record.entries[1].author, "user");
    let first = record.entries[0].commit.as_ref().unwrap();
    let changes: Vec<_> = first.files.iter().map(|f| f.change.as_deref()).collect();
    assert_eq!(
        changes,
        [Some("modified"), Some("unchanged"), Some("added")]
    );
    let oldest = record.entries[2].commit.as_ref().unwrap();
    assert!(oldest.files.iter().all(|f| f.change.is_none()));
}
