//! Host side of new-folder creation: hash matching of pending placeholders,
//! creation-only binding, and completion called once after a created folder,
//! never after a refusal, with the folder kept when completion fails.
// contract-test: supporting surface=cli assertions=projects.creation.machine-folder
use super::create_source::CreatedSource;
use super::creation_host::{
    COMPLETION_FAILED, CompleteCreation, CreationAdapter, HostState, Planned, finish_creation,
    plan_pending,
};
use super::dispatch::HostedSource;
use super::reads::HostRoot;
use super::runner::{SourceHostRun, SourceHostRunSource};
use super::store::{StoredRemoteSource, load_remote_sources};
use super::{HostError, HostResult};
use crate::client::{SourceHostAdapter, SourceHostOperation};
use crate::work::{PendingSourceCreation, ProjectSourceCapability};
use std::collections::BTreeSet;
use std::path::{Path, PathBuf};

fn pending(source_id: &str, project_id: &str) -> PendingSourceCreation {
    PendingSourceCreation {
        source_id: source_id.to_owned(),
        hashed_project_id: crate::work::hash(project_id),
        host_device_hash: "a".repeat(64),
    }
}

fn record(source_id: &str, project_id: &str, root: &Path) -> StoredRemoteSource {
    StoredRemoteSource {
        source_id: source_id.to_owned(),
        project_id: Some(project_id.to_owned()),
        source_type: "local_git_repository".into(),
        root_path: root.to_string_lossy().into_owned(),
        display_name: "kitchen".into(),
        cache_path: "/unused".into(),
        status: "offline".into(),
        created_at: 1,
        updated_at: 1,
        extra: serde_json::Map::new(),
    }
}

fn visible() -> Vec<String> {
    vec!["project-1".to_owned(), "project-2".to_owned()]
}

// contract-test: supporting surface=cli assertions=projects.creation.machine-folder
#[test]
fn pending_placeholders_match_visible_projects_by_hash_when_configured() {
    let rows = [
        pending("src_a", "project-2"),
        pending("src_b", "unknown-project"),
    ];
    let plan = plan_pending(&rows, &visible(), &BTreeSet::new(), &[], true, 16);
    assert_eq!(
        plan,
        vec![Planned::Bind {
            project_id: "project-2".into(),
            source_id: "src_a".into()
        }]
    );
}

// contract-test: supporting surface=cli assertions=projects.creation.machine-folder
#[test]
fn placeholders_are_not_bound_without_a_new_projects_folder() {
    let rows = [pending("src_a", "project-1")];
    assert!(plan_pending(&rows, &visible(), &BTreeSet::new(), &[], false, 16).is_empty());
}

// contract-test: supporting surface=cli assertions=projects.creation.machine-folder
#[test]
fn known_placeholders_are_skipped_and_the_room_is_respected() {
    let rows = [
        pending("src_a", "project-1"),
        pending("src_b", "project-1"),
        pending("src_c", "project-2"),
    ];
    let known: BTreeSet<String> = ["src_a".to_owned()].into();
    let plan = plan_pending(&rows, &visible(), &known, &[], true, 1);
    assert_eq!(plan.len(), 1);
    assert!(matches!(&plan[0], Planned::Bind { source_id, .. } if source_id == "src_b"));
}

// contract-test: supporting surface=cli assertions=projects.creation.machine-folder
#[test]
fn an_existing_local_record_recovers_instead_of_binding_even_unconfigured() {
    let tmp = tempfile::tempdir().expect("tempdir");
    let rows = [pending("src_a", "project-1")];
    let stored = [record("src_a", "project-1", tmp.path())];
    let plan = plan_pending(&rows, &visible(), &BTreeSet::new(), &stored, false, 16);
    assert_eq!(
        plan,
        vec![Planned::Recover {
            project_id: "project-1".into(),
            source_id: "src_a".into(),
            root: tmp.path().to_path_buf()
        }]
    );
}

// contract-test: supporting surface=cli assertions=projects.creation.machine-folder
#[test]
fn a_placeholder_binding_serves_only_the_creation_operation() {
    let adapter = CreationAdapter;
    assert!(adapter.implemented_capabilities() == vec![ProjectSourceCapability::CreateSource]);
    assert!(adapter.supports_operation(SourceHostOperation::CreateSource));
    assert!(!adapter.supports_operation(SourceHostOperation::ReadText));
    assert!(!adapter.supports_operation(SourceHostOperation::GitCommit));
}

fn run_with(sources: Vec<SourceHostRunSource>) -> SourceHostRun {
    SourceHostRun {
        sources,
        source_session_id: "session".into(),
        confirmed_takeover: false,
        state_dir: PathBuf::from("/state"),
        credential_sync: None,
    }
}

fn run_source(source_id: &str) -> SourceHostRunSource {
    SourceHostRunSource {
        project_id: "project-1".into(),
        source_id: source_id.into(),
        team_id: None,
        root: PathBuf::from("/work/shop"),
    }
}

// contract-test: supporting surface=cli assertions=projects.creation.machine-folder
#[test]
fn an_adopted_folder_is_served_at_its_new_root_with_normal_capabilities() {
    let mut state = HostState::new(&run_with(vec![run_source("src_a"), run_source("src_new")]));
    state.placeholders.insert("src_new".into());
    assert!(
        state.adapter("src_new").implemented_capabilities()
            == vec![ProjectSourceCapability::CreateSource]
    );
    let created = hosted("src_new", Path::new("/work/Kitchen renovation"));
    state.adopt(&created);
    assert!(state.placeholders.is_empty());
    assert!(
        !state
            .adapter("src_new")
            .implemented_capabilities()
            .contains(&ProjectSourceCapability::CreateSource)
    );
    let served = state.hosted(Path::new("/state"));
    let entry = served
        .iter()
        .find(|s| s.source_id == "src_new")
        .expect("served");
    assert_eq!(entry.root.root, PathBuf::from("/work/Kitchen renovation"));
}

fn hosted(source_id: &str, root: &Path) -> HostedSource {
    HostedSource {
        project_id: "project-1".into(),
        source_id: source_id.into(),
        team_id: None,
        root: HostRoot {
            root: root.to_path_buf(),
            state_dir: PathBuf::from("/state"),
            policy_source: None,
        },
        target_branch: None,
    }
}

#[derive(Default)]
struct FakeCompletion {
    calls: Vec<(String, String, PathBuf)>,
    fail: bool,
}

impl CompleteCreation for FakeCompletion {
    async fn complete(&mut self, project_id: &str, source_id: &str, root: &Path) -> HostResult<()> {
        self.calls.push((
            project_id.to_owned(),
            source_id.to_owned(),
            root.to_path_buf(),
        ));
        if self.fail {
            Err(HostError::new(COMPLETION_FAILED, "backend unavailable"))
        } else {
            Ok(())
        }
    }
}

fn created_in(base: &Path) -> CreatedSource {
    let path = base.join("Kitchen renovation");
    std::fs::create_dir(&path).expect("folder");
    CreatedSource {
        path,
        folder_name: "Kitchen renovation".into(),
        head: "abc123".into(),
        branch: "main",
    }
}

// contract-test: supporting surface=cli assertions=projects.creation.machine-folder
#[tokio::test]
async fn completion_is_called_once_after_a_created_folder_and_the_new_source_is_served() {
    let tmp = tempfile::tempdir().expect("tempdir");
    let state = tmp.path().join("state");
    let created = created_in(tmp.path());
    let expected = created.path.clone();
    let mut completion = FakeCompletion::default();
    let (result, served) = finish_creation(
        &mut completion,
        &hosted("src_new", Path::new("")),
        Ok(created),
        &state,
    )
    .await
    .expect("finished");
    assert_eq!(completion.calls.len(), 1);
    assert_eq!(completion.calls[0].1, "src_new");
    assert_eq!(completion.calls[0].2, expected);
    assert_eq!(result["branch"], "main");
    assert_eq!(served.root.root, expected);
    let stored = load_remote_sources(&state).expect("records");
    assert_eq!(stored.len(), 1);
    assert_eq!(stored[0].source_id, "src_new");
}

// contract-test: supporting surface=cli assertions=projects.creation.machine-folder
#[tokio::test]
async fn a_refusal_never_calls_completion_and_keeps_its_code() {
    let tmp = tempfile::tempdir().expect("tempdir");
    let state = tmp.path().join("state");
    let mut completion = FakeCompletion::default();
    let refused = Err(HostError::new("target_exists", "exists"));
    let error = finish_creation(
        &mut completion,
        &hosted("src_new", Path::new("")),
        refused,
        &state,
    )
    .await
    .expect_err("refused");
    assert_eq!(error.code, "target_exists");
    assert!(completion.calls.is_empty());
    assert!(load_remote_sources(&state).expect("records").is_empty());
}

// contract-test: supporting surface=cli assertions=projects.creation.machine-folder
#[tokio::test]
async fn a_failed_completion_answers_a_stable_code_and_keeps_the_folder_and_record() {
    let tmp = tempfile::tempdir().expect("tempdir");
    let state = tmp.path().join("state");
    let created = created_in(tmp.path());
    let folder = created.path.clone();
    let mut completion = FakeCompletion {
        fail: true,
        ..Default::default()
    };
    let error = finish_creation(
        &mut completion,
        &hosted("src_new", Path::new("")),
        Ok(created),
        &state,
    )
    .await
    .expect_err("completion failed");
    assert_eq!(error.code, "creation_completion_failed");
    assert!(folder.is_dir());
    // The record lets the next discovery finish the placeholder without a new request.
    let stored = load_remote_sources(&state).expect("records");
    assert_eq!(stored[0].source_id, "src_new");
    assert_eq!(stored[0].root_path, folder.to_string_lossy());
}
