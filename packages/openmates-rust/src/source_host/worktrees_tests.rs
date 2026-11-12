//! Chat worktrees on temporary Git repositories: creation, hidden ref, reuse, cleanup safety, id validation and dispatch root choice.
use super::HostResult;
use super::dispatch::{HostedSource, request_root};
use super::reads::HostRoot;
use super::worktrees::{
    IDLE_LIMIT_MS, KeptReason, Removal, WorktreeArea, WorktreeError, hidden_ref, record_head,
};
use super::writes::{WriteAuthority, WriteRequest, execute, validate};
use serde_json::json;
use std::fs;
use std::path::{Path, PathBuf};
use std::process::Command;

const DAY_MS: u64 = 24 * 60 * 60 * 1000;
const SOURCE: &str = "src_alpha";
const CHAT: &str = "0b7e2c1a-4f4e-4b8e-9a51-2f7d0d3c9e11";

struct Repo {
    _source: tempfile::TempDir,
    _state: tempfile::TempDir,
    _journal: tempfile::TempDir,
    root: PathBuf,
    state: PathBuf,
    journal: PathBuf,
}

impl Repo {
    fn area(&self) -> WorktreeArea {
        WorktreeArea::new(&self.state)
    }
}

fn git(dir: &Path, args: &[&str]) -> String {
    let out = Command::new("git")
        .args([
            "-c",
            "user.name=Test",
            "-c",
            "user.email=test@example.org",
            "-c",
            "commit.gpgsign=false",
            "-C",
        ])
        .arg(dir)
        .args(args)
        .output()
        .expect("git runs");
    assert!(
        out.status.success(),
        "git {args:?}: {}",
        String::from_utf8_lossy(&out.stderr)
    );
    String::from_utf8(out.stdout)
        .expect("utf8")
        .trim_end()
        .to_owned()
}

fn commit_file(dir: &Path, name: &str, content: &str, message: &str) -> String {
    fs::write(dir.join(name), content).expect("write");
    git(dir, &["add", name]);
    git(dir, &["commit", "-q", "-m", message]);
    git(dir, &["rev-parse", "HEAD"])
}

fn repo() -> Repo {
    let source = tempfile::tempdir().expect("tempdir");
    let state = tempfile::tempdir().expect("tempdir");
    let journal = tempfile::tempdir().expect("tempdir");
    let root = fs::canonicalize(source.path()).expect("canonical");
    git(&root, &["init", "-q", "-b", "dev"]);
    fs::write(root.join(".gitignore"), "ignored/\n").expect("write");
    git(&root, &["add", ".gitignore"]);
    commit_file(&root, "README.md", "hello\n", "initial");
    Repo {
        root,
        state: fs::canonicalize(state.path()).expect("canonical"),
        journal: journal.path().join("journal"),
        _source: source,
        _state: state,
        _journal: journal,
    }
}

fn branches(dir: &Path) -> String {
    git(dir, &["branch", "--list", "--format=%(refname)"])
}

#[test]
fn creates_a_detached_worktree_from_the_target_branch_without_a_branch() {
    let r = repo();
    let before = branches(&r.root);
    let dev = git(&r.root, &["rev-parse", "dev"]);
    let wt = r
        .area()
        .ensure(&r.root, SOURCE, CHAT, None, 0)
        .expect("ensure")
        .expect("git source");
    assert_eq!(wt.path, r.state.join("worktrees").join(SOURCE).join(CHAT));
    assert_eq!(wt.root, wt.path);
    assert_eq!(wt.target_branch, "dev");
    assert_eq!(git(&wt.path, &["rev-parse", "HEAD"]), dev);
    let symbolic = Command::new("git")
        .arg("-C")
        .arg(&wt.path)
        .args(["symbolic-ref", "-q", "HEAD"])
        .status()
        .expect("git");
    assert!(!symbolic.success(), "HEAD must be detached");
    assert_eq!(branches(&r.root), before, "no branch is created");
    assert_eq!(git(&r.root, &["rev-parse", &hidden_ref(CHAT)]), dev);
}

#[test]
fn explicit_target_branch_sets_the_start_commit() {
    let r = repo();
    git(&r.root, &["branch", "release"]);
    let release = git(&r.root, &["rev-parse", "release"]);
    commit_file(&r.root, "later.txt", "x\n", "dev moves on");
    let wt = r
        .area()
        .ensure(&r.root, SOURCE, CHAT, Some("release"), 0)
        .expect("ensure")
        .expect("git");
    assert_eq!(wt.target_branch, "release");
    assert_eq!(git(&wt.path, &["rev-parse", "HEAD"]), release);
    let missing = r
        .area()
        .ensure(&r.root, SOURCE, "other-chat", Some("nope"), 0);
    assert!(matches!(
        missing,
        Err(WorktreeError::TargetBranchUnavailable(_))
    ));
}

#[test]
fn hidden_ref_follows_commits_in_the_worktree() {
    let r = repo();
    let wt = r
        .area()
        .ensure(&r.root, SOURCE, CHAT, None, 0)
        .expect("ensure")
        .expect("git");
    let head = commit_file(&wt.path, "feature.txt", "new\n", "chat work");
    assert_eq!(record_head(&wt).expect("record"), head);
    assert_eq!(git(&r.root, &["rev-parse", &hidden_ref(CHAT)]), head);
    let second = commit_file(&wt.path, "feature.txt", "newer\n", "more chat work");
    r.area()
        .ensure(&r.root, SOURCE, CHAT, None, 1)
        .expect("reuse");
    assert_eq!(
        git(&r.root, &["rev-parse", &hidden_ref(CHAT)]),
        second,
        "ensure records the moved HEAD"
    );
}

#[test]
fn second_ensure_for_the_same_workspace_chat_reuses_the_worktree() {
    let r = repo();
    let first = r
        .area()
        .ensure(&r.root, SOURCE, CHAT, None, 0)
        .expect("ensure")
        .expect("git");
    fs::write(first.path.join("scratch.txt"), "keep\n").expect("write");
    let second = r
        .area()
        .ensure(&r.root, SOURCE, CHAT, None, 5)
        .expect("ensure")
        .expect("git");
    assert_eq!(first, second);
    assert_eq!(
        fs::read_to_string(second.path.join("scratch.txt")).expect("read"),
        "keep\n"
    );
    let existing = r
        .area()
        .resolve_existing(&r.root, SOURCE, CHAT, 6)
        .expect("resolve")
        .expect("exists");
    assert_eq!(existing, first);
    let other = r
        .area()
        .ensure(&r.root, SOURCE, "sibling-chat", None, 0)
        .expect("ensure")
        .expect("git");
    assert_ne!(
        other.path, first.path,
        "another workspace chat gets its own worktree"
    );
}

#[test]
fn recreates_a_deleted_worktree_from_its_hidden_ref() {
    let r = repo();
    let wt = r
        .area()
        .ensure(&r.root, SOURCE, CHAT, None, 0)
        .expect("ensure")
        .expect("git");
    let head = commit_file(&wt.path, "work.txt", "w\n", "chat work");
    record_head(&wt).expect("record");
    fs::remove_dir_all(&wt.path).expect("user deletes the folder");
    let again = r
        .area()
        .ensure(&r.root, SOURCE, CHAT, None, 1)
        .expect("ensure")
        .expect("git");
    assert_eq!(
        git(&again.path, &["rev-parse", "HEAD"]),
        head,
        "unlanded commits survive"
    );
}

#[test]
fn plain_folder_gets_no_worktree() {
    let source = tempfile::tempdir().expect("tempdir");
    let state = tempfile::tempdir().expect("tempdir");
    let root = fs::canonicalize(source.path()).expect("canonical");
    let area = WorktreeArea::new(state.path());
    assert_eq!(
        area.ensure(&root, SOURCE, CHAT, None, 0).expect("ensure"),
        None
    );
    assert_eq!(
        area.resolve_existing(&root, SOURCE, CHAT, 0)
            .expect("resolve"),
        None
    );
    assert!(!state.path().join("worktrees").exists());
}

#[test]
fn rejects_hostile_chat_and_source_ids() {
    let r = repo();
    let long = "a".repeat(129);
    for chat in [
        "",
        "../escape",
        "a/b",
        ".hidden",
        "-rf",
        "a b",
        "x..y",
        "ref~1",
        "a\nb",
        long.as_str(),
    ] {
        assert_eq!(
            r.area().ensure(&r.root, SOURCE, chat, None, 0),
            Err(WorktreeError::InvalidChatId),
            "{chat:?}"
        );
        assert_eq!(
            r.area().resolve_existing(&r.root, SOURCE, chat, 0),
            Err(WorktreeError::InvalidChatId)
        );
    }
    for source in ["", "..", "a/b", ".git", "--force", "s:1"] {
        assert_eq!(
            r.area().ensure(&r.root, source, CHAT, None, 0),
            Err(WorktreeError::InvalidSourceId),
            "{source:?}"
        );
    }
    for branch in ["-x", "a..b", "a b", "/abs", "x.lock", "a/.b", "HEAD@{1}"] {
        assert_eq!(
            r.area().ensure(&r.root, SOURCE, CHAT, Some(branch), 0),
            Err(WorktreeError::InvalidTargetBranch),
            "{branch:?}"
        );
    }
    assert!(!r.state.join("worktrees").join(SOURCE).join(CHAT).exists());
}

#[test]
fn remove_keeps_uncommitted_changes() {
    let r = repo();
    let wt = r
        .area()
        .ensure(&r.root, SOURCE, CHAT, None, 0)
        .expect("ensure")
        .expect("git");
    fs::write(wt.path.join("draft.txt"), "untracked\n").expect("write");
    assert_eq!(
        r.area().remove_if_safe(SOURCE, CHAT),
        Ok(Removal::Kept(KeptReason::UncommittedChanges))
    );
    fs::remove_file(wt.path.join("draft.txt")).expect("remove");
    fs::write(wt.path.join("README.md"), "edited\n").expect("write");
    assert_eq!(
        r.area().remove_if_safe(SOURCE, CHAT),
        Ok(Removal::Kept(KeptReason::UncommittedChanges))
    );
    assert!(wt.path.exists());
}

#[test]
fn remove_keeps_unlanded_commits_and_succeeds_after_landing() {
    let r = repo();
    let wt = r
        .area()
        .ensure(&r.root, SOURCE, CHAT, None, 0)
        .expect("ensure")
        .expect("git");
    let head = commit_file(&wt.path, "feature.txt", "new\n", "chat work");
    let state = r.area().state(SOURCE, CHAT).expect("state");
    assert_eq!(
        (state.head.as_str(), state.ahead, state.landed, state.dirty),
        (head.as_str(), 1, false, false)
    );
    assert_eq!(
        r.area().remove_if_safe(SOURCE, CHAT),
        Ok(Removal::Kept(KeptReason::UnlandedCommits { ahead: 1 }))
    );
    assert_eq!(
        git(&r.root, &["rev-parse", &hidden_ref(CHAT)]),
        head,
        "kept removal records the head"
    );
    git(&r.root, &["merge", "-q", "--ff-only", &head]);
    assert!(r.area().state(SOURCE, CHAT).expect("state").landed);
    assert_eq!(r.area().remove_if_safe(SOURCE, CHAT), Ok(Removal::Removed));
    assert!(!wt.path.exists());
    let refs = git(&r.root, &["for-each-ref", "refs/openmates/"]);
    assert!(refs.is_empty(), "hidden ref removed: {refs}");
    assert_eq!(r.area().list(SOURCE).expect("list"), Vec::new());
    assert_eq!(
        r.area().remove_if_safe(SOURCE, CHAT),
        Err(WorktreeError::NotFound)
    );
}

#[test]
fn idle_sweep_removes_landed_and_keeps_unlanded_and_recent() {
    let r = repo();
    let area = r.area();
    area.ensure(&r.root, SOURCE, "landed-chat", None, 0)
        .expect("ensure")
        .expect("git");
    let busy = area
        .ensure(&r.root, SOURCE, "busy-chat", None, 0)
        .expect("ensure")
        .expect("git");
    commit_file(&busy.path, "busy.txt", "b\n", "unlanded");
    area.ensure(&r.root, SOURCE, "recent-chat", None, 13 * DAY_MS)
        .expect("ensure")
        .expect("git");
    assert_eq!(IDLE_LIMIT_MS, 14 * DAY_MS);
    let outcomes = area.sweep_idle(14 * DAY_MS, IDLE_LIMIT_MS).expect("sweep");
    assert!(outcomes.iter().all(|o| o.source_id == SOURCE));
    let summary: Vec<(String, Removal)> = outcomes
        .into_iter()
        .map(|o| (o.chat_id, o.result.expect("entry")))
        .collect();
    assert_eq!(
        summary,
        vec![
            (
                "busy-chat".to_owned(),
                Removal::Kept(KeptReason::UnlandedCommits { ahead: 1 })
            ),
            ("landed-chat".to_owned(), Removal::Removed),
        ]
    );
    let left: Vec<String> = area
        .list(SOURCE)
        .expect("list")
        .into_iter()
        .map(|s| s.chat_id)
        .collect();
    assert_eq!(left, vec!["busy-chat".to_owned(), "recent-chat".to_owned()]);
}

struct Allow;

impl WriteAuthority for Allow {
    async fn authorize(&mut self) -> HostResult<()> {
        Ok(())
    }
}

fn hosted(r: &Repo) -> HostedSource {
    HostedSource {
        project_id: "p1".into(),
        source_id: SOURCE.into(),
        team_id: None,
        root: HostRoot {
            root: r.root.clone(),
            state_dir: r.state.clone(),
            policy_source: None,
        },
        target_branch: None,
    }
}

async fn write_file(
    r: &Repo,
    root: &HostRoot,
    op: &str,
    path: &str,
) -> HostResult<serde_json::Value> {
    let mutation = validate(&json!({
        "operation": "create_file", "operation_id": op, "path": path, "expected_base": null, "content": "chat\n"
    }))?;
    execute(
        WriteRequest {
            root: &root.root,
            state_dir: &root.state_dir,
            policy_source: root.policy_source.as_deref(),
            mutation: &mutation,
            scope: "project:p1/source:src_alpha/chat:c1",
            journal_root: Some(r.journal.clone()),
        },
        &mut Allow,
    )
    .await
}

#[tokio::test]
async fn dispatch_write_lands_in_the_chat_worktree_not_the_source_root() {
    let r = repo();
    let source = hosted(&r);
    let read_before = request_root(&source, Some(CHAT), false, 0).expect("read root");
    assert_eq!(
        read_before.root, r.root,
        "reads before the first write use the source root"
    );
    let legacy = request_root(&source, None, true, 0).expect("legacy root");
    assert_eq!(
        (legacy.root.clone(), legacy.policy_source.clone()),
        (r.root.clone(), None)
    );
    let root = request_root(&source, Some(CHAT), true, 0).expect("write root");
    let worktree = r.state.join("worktrees").join(SOURCE).join(CHAT);
    assert_eq!(
        (root.root.clone(), root.policy_source.clone()),
        (worktree.clone(), Some(r.root.clone()))
    );
    write_file(&r, &root, "op-1", "plan.md")
        .await
        .expect("write");
    assert_eq!(
        fs::read_to_string(worktree.join("plan.md")).expect("read"),
        "chat\n"
    );
    assert!(!r.root.join("plan.md").exists(), "source root is untouched");
    let read_after = request_root(&source, Some(CHAT), false, 1).expect("read root");
    assert_eq!(
        read_after.root, worktree,
        "reads use the worktree once it exists"
    );
    assert!(request_root(&source, Some("../x"), true, 0).is_err());
}

#[tokio::test]
async fn source_private_paths_and_protections_apply_inside_the_worktree() {
    let r = repo();
    // Untracked in the source, so the worktree has no copy of the config.
    fs::create_dir_all(r.root.join(".openmates")).expect("dir");
    fs::write(
        r.root.join(".openmates/permissions.yml"),
        "schema_version: 1\nfile_access:\n  private_paths:\n    - secrets/**\npresets: []\n",
    )
    .expect("write");
    let root = request_root(&hosted(&r), Some(CHAT), true, 0).expect("write root");
    assert!(!root.root.join(".openmates/permissions.yml").exists());
    for (op, path) in [
        ("op-a", "secrets/key.txt"),
        ("op-b", ".git"),
        ("op-c", ".env"),
        ("op-d", "ignored/x.txt"),
    ] {
        let error = write_file(&r, &root, op, path)
            .await
            .expect_err("protected");
        assert_eq!(error.code, "protected_path", "{path}");
    }
}

#[test]
fn worktree_root_outside_the_area_is_refused() {
    let r = repo();
    let forged = HostRoot {
        root: r.root.clone(),
        state_dir: r.state.clone(),
        policy_source: Some(r.root.clone()),
    };
    assert_eq!(
        forged.canonical().expect_err("outside area").code,
        "protected_path"
    );
}
