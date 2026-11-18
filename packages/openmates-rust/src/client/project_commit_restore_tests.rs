//! User commit restore orchestration against an in-memory fake: user revision
//! writes, unchanged skip, relink, path/embed refusals, Team scope, recorded commit.
use super::*;
use crate::work::{ProjectCommitRestoreFile, ProjectCommitRestorePlan, UserRestoreInputs};

const A: &str = "aaaaaaaa-1111-4111-8111-aabbccddeeff";
const B: &str = "bbbbbbbb-1111-4111-8111-aabbccddeeff";
const TEAM: &str = "99999999-1111-4111-8111-aabbccddeeff";

#[derive(Default)]
struct Fake {
    plan: Vec<ProjectCommitRestoreFile>,
    linked: Vec<(String, String)>,
    known_embeds: Vec<String>,
    heads: Vec<(String, u64)>,
    written: Vec<(String, u64)>,
    relinked: Vec<(String, String)>,
    recorded: Option<(String, ProjectCommitCreate)>,
}

fn planned(
    target: Option<&str>,
    hash: &str,
    path: &str,
    from: u64,
    now: Option<u64>,
) -> ProjectCommitRestoreFile {
    ProjectCommitRestoreFile {
        target_id: target.map(str::to_owned),
        target_id_hash: hash.into(),
        path: Some(path.into()),
        restore_version: from,
        current_version: now,
        unchanged: now == Some(from),
        committed_target_id: None,
    }
}

impl RestoreIo for Fake {
    async fn inputs(&mut self, commit_id: &str) -> Result<UserRestoreInputs> {
        Ok(UserRestoreInputs {
            project_id: "project".into(),
            plan: ProjectCommitRestorePlan {
                commit_id: commit_id.into(),
                files: self.plan.clone(),
            },
            message: "Add recipe search".into(),
            linked: self.linked.clone(),
        })
    }
    fn resolve_embed(&self, hash: &str) -> Option<String> {
        self.known_embeds
            .iter()
            .find(|id| crate::work::hash(id) == hash)
            .cloned()
    }
    async fn relink(&mut self, embed: &str, path: &str) -> std::result::Result<(), StepError> {
        self.relinked.push((embed.into(), path.into()));
        Ok(())
    }
    async fn write_version(
        &mut self,
        embed: &str,
        version: u64,
    ) -> std::result::Result<u64, StepError> {
        let head = self
            .heads
            .iter()
            .find(|(id, _)| id == embed)
            .map_or(1, |(_, v)| *v);
        self.written.push((embed.into(), version));
        Ok(head + 1)
    }
    async fn head_version(&mut self, embed: &str) -> Result<u64> {
        Ok(self
            .heads
            .iter()
            .find(|(id, _)| id == embed)
            .map_or(1, |(_, v)| *v))
    }
    async fn record(&mut self, source: &str, input: ProjectCommitCreate) -> Result<ProjectCommit> {
        let commit = ProjectCommit {
            commit_id: "dddddddd-1111-4111-8111-aabbccddeeff".into(),
            message: input.message.clone(),
            author: input.author,
            chat_id_hash: None,
            files: vec![],
            restored_from_commit_id: Some(source.into()),
            created_at: 1,
        };
        self.recorded = Some((source.into(), input));
        Ok(commit)
    }
}

const SOURCE: &str = "cccccccc-1111-4111-8111-aabbccddeeff";

#[tokio::test]
async fn changed_file_is_written_and_unchanged_file_is_skipped() {
    let mut fake = Fake {
        plan: vec![
            planned(Some(A), &crate::work::hash(A), "src/a.rs", 2, Some(5)),
            planned(Some(B), &crate::work::hash(B), "src/b.rs", 3, Some(3)),
        ],
        linked: vec![(A.into(), "src/a.rs".into()), (B.into(), "src/b.rs".into())],
        heads: vec![(A.into(), 5)],
        ..Default::default()
    };
    let result = run_restore(&mut fake, SOURCE, None, None).await.unwrap();
    assert_eq!(fake.written, vec![(A.to_owned(), 2)]);
    assert_eq!(
        result.files[0].outcome,
        ProjectCommitFileOutcome::Restored { version: 6 }
    );
    assert_eq!(result.files[1].outcome, ProjectCommitFileOutcome::Unchanged);
}

#[tokio::test]
async fn restore_commit_is_recorded_as_user_with_source_and_default_message() {
    let mut fake = Fake {
        plan: vec![planned(
            Some(A),
            &crate::work::hash(A),
            "src/a.rs",
            2,
            Some(5),
        )],
        linked: vec![(A.into(), "src/a.rs".into())],
        heads: vec![(A.into(), 5)],
        ..Default::default()
    };
    let result = run_restore(&mut fake, SOURCE, None, None).await.unwrap();
    let (source, input) = fake.recorded.unwrap();
    assert_eq!(source, SOURCE);
    assert_eq!(input.author, ProjectCommitAuthor::User);
    assert_eq!(input.chat_id, None);
    assert_eq!(input.message, "Restore \"Add recipe search\"");
    assert_eq!(input.files.len(), 1);
    assert_eq!(
        (
            input.files[0].target_id.as_str(),
            input.files[0].path.as_str(),
            input.files[0].embed_version
        ),
        (A, "src/a.rs", 6)
    );
    assert_eq!(
        result.commit.restored_from_commit_id.as_deref(),
        Some(SOURCE)
    );
}

#[tokio::test]
async fn deleted_link_is_relinked_at_the_committed_path() {
    let mut fake = Fake {
        plan: vec![planned(None, &crate::work::hash(A), "src/a.rs", 2, None)],
        known_embeds: vec![A.into()],
        heads: vec![(A.into(), 2)],
        ..Default::default()
    };
    let result = run_restore(&mut fake, SOURCE, Some("Back".into()), None)
        .await
        .unwrap();
    assert_eq!(fake.relinked, vec![(A.to_owned(), "src/a.rs".to_owned())]);
    assert!(fake.written.is_empty());
    assert_eq!(
        result.files[0].outcome,
        ProjectCommitFileOutcome::Relinked { version: 2 }
    );
    assert_eq!(fake.recorded.unwrap().1.message, "Back");
}

#[tokio::test]
async fn manifest_v2_commit_relinks_an_embed_this_client_never_cached() {
    let mut file = planned(None, &crate::work::hash(A), "src/a.rs", 2, None);
    file.committed_target_id = Some(A.into());
    let mut fake = Fake {
        plan: vec![file],
        heads: vec![(A.into(), 2)],
        ..Default::default()
    };
    let result = run_restore(&mut fake, SOURCE, None, None).await.unwrap();
    assert_eq!(fake.relinked, vec![(A.to_owned(), "src/a.rs".to_owned())]);
    assert_eq!(
        result.files[0].outcome,
        ProjectCommitFileOutcome::Relinked { version: 2 }
    );
}

#[tokio::test]
async fn relinked_file_with_newer_head_gets_the_committed_content_written() {
    let mut fake = Fake {
        plan: vec![planned(None, &crate::work::hash(A), "src/a.rs", 2, None)],
        known_embeds: vec![A.into()],
        heads: vec![(A.into(), 4)],
        ..Default::default()
    };
    let result = run_restore(&mut fake, SOURCE, None, None).await.unwrap();
    assert_eq!(fake.written, vec![(A.to_owned(), 2)]);
    assert_eq!(
        result.files[0].outcome,
        ProjectCommitFileOutcome::Relinked { version: 5 }
    );
}

#[tokio::test]
async fn taken_path_is_refused_with_path_conflict_and_other_files_continue() {
    let mut fake = Fake {
        plan: vec![
            planned(None, &crate::work::hash(A), "src/a.rs", 2, None),
            planned(Some(B), &crate::work::hash(B), "src/b.rs", 3, Some(4)),
        ],
        linked: vec![
            (B.into(), "src/b.rs".into()),
            ("other".into(), "src/a.rs".into()),
        ],
        known_embeds: vec![A.into()],
        heads: vec![(B.into(), 4)],
        ..Default::default()
    };
    let result = run_restore(&mut fake, SOURCE, None, None).await.unwrap();
    assert_eq!(
        result.files[0].outcome,
        ProjectCommitFileOutcome::Refused {
            reason: "path_conflict".into()
        }
    );
    assert!(fake.relinked.is_empty());
    assert_eq!(
        result.files[1].outcome,
        ProjectCommitFileOutcome::Restored { version: 5 }
    );
    assert_eq!(fake.recorded.unwrap().1.files.len(), 1);
}

#[tokio::test]
async fn unknown_embed_is_refused_with_embed_missing() {
    let mut fake = Fake {
        plan: vec![
            planned(None, &crate::work::hash(A), "src/a.rs", 2, None),
            planned(Some(B), &crate::work::hash(B), "src/b.rs", 3, Some(3)),
        ],
        linked: vec![(B.into(), "src/b.rs".into())],
        ..Default::default()
    };
    let result = run_restore(&mut fake, SOURCE, None, None).await.unwrap();
    assert_eq!(
        result.files[0].outcome,
        ProjectCommitFileOutcome::Refused {
            reason: "embed_missing".into()
        }
    );
    assert_eq!(result.files[1].outcome, ProjectCommitFileOutcome::Unchanged);
}

#[tokio::test]
async fn restore_with_no_restorable_file_records_nothing() {
    let mut fake = Fake {
        plan: vec![planned(None, &crate::work::hash(A), "src/a.rs", 2, None)],
        ..Default::default()
    };
    assert!(run_restore(&mut fake, SOURCE, None, None).await.is_err());
    assert!(fake.recorded.is_none());
}

#[test]
fn team_project_passes_team_id_to_filters_and_revision_scope() {
    let filters = restore_filters(Some(TEAM));
    assert!(!filters.personal);
    assert_eq!(filters.team_id.as_deref(), Some(TEAM));
    assert!(restore_filters(None).personal);
    match restore_scope("project", Some(TEAM)) {
        RevisionScope::Project {
            project_id,
            team_id,
        } => {
            assert_eq!(
                (project_id.as_str(), team_id.as_deref()),
                ("project", Some(TEAM))
            );
        }
        RevisionScope::Chat { .. } => panic!("project scope expected"),
    }
}

#[test]
fn derived_ids_are_stable_valid_uuids_per_label() {
    let one = derived_uuid(SOURCE, A);
    assert_eq!(one, derived_uuid(SOURCE, A));
    assert_ne!(one, derived_uuid(SOURCE, B));
    assert!(uuid::Uuid::parse_str(&one).is_ok());
}

#[test]
fn nothing_restored_keeps_the_first_refusal_code_for_the_shell() {
    let row = |reason: &str| refuse(Some("web-app/app.js".into()), "h".into(), reason);
    assert!(matches!(
        nothing_restored(&[row("key_unavailable"), row("path_conflict")]),
        Error::Unavailable {
            code: "key_unavailable",
            ..
        }
    ));
    assert!(matches!(
        nothing_restored(&[row("revision_route_refusal")]),
        Error::Unavailable {
            code: "restore_refused",
            ..
        }
    ));
    assert!(matches!(nothing_restored(&[]), Error::Invalid(_)));
}
