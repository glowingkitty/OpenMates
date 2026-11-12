//! Git operations on chat worktrees against real temporary repositories: status, commit, landing fast path, rebase, conflicts and refusals.
use super::dispatch::HostedSource;
use super::git_ops::{self, GitProposal};
use super::reads::HostRoot;
use super::worktrees::{ChatWorktree, WorktreeArea, hidden_ref};
use serde_json::{Value, json};
use std::fs;
use std::path::{Path, PathBuf};
use std::process::Command;

const SOURCE: &str = "src_alpha";
const CHAT: &str = "0b7e2c1a-4f4e-4b8e-9a51-2f7d0d3c9e11";

struct Fixture {
    _source: tempfile::TempDir,
    _state: tempfile::TempDir,
    root: PathBuf,
    state: PathBuf,
}

fn git(dir: &Path, args: &[&str]) -> String {
    let out = Command::new("git")
        .args(["-c", "commit.gpgsign=false", "-C"])
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

fn commit_file(dir: &Path, name: &str, content: &str) -> String {
    fs::write(dir.join(name), content).expect("write");
    git(dir, &["add", name]);
    git(dir, &["commit", "-q", "-m", name]);
    git(dir, &["rev-parse", "HEAD"])
}

fn fixture() -> Fixture {
    let source = tempfile::tempdir().expect("tempdir");
    let state = tempfile::tempdir().expect("tempdir");
    let root = fs::canonicalize(source.path()).expect("canonical");
    git(&root, &["init", "-q", "-b", "dev"]);
    // Local identity: the host reads the repository's own configuration.
    git(&root, &["config", "user.name", "Test"]);
    git(&root, &["config", "user.email", "test@example.org"]);
    commit_file(&root, "README.md", "hello\n");
    Fixture {
        root,
        state: fs::canonicalize(state.path()).expect("canonical"),
        _source: source,
        _state: state,
    }
}

impl Fixture {
    fn area(&self) -> WorktreeArea {
        WorktreeArea::new(&self.state)
    }
    fn worktree(&self) -> ChatWorktree {
        self.area()
            .ensure(&self.root, SOURCE, CHAT, None, 0)
            .expect("ensure")
            .expect("git source")
    }
    fn hosted(&self) -> HostedSource {
        HostedSource {
            project_id: "p1".into(),
            source_id: SOURCE.into(),
            team_id: None,
            root: HostRoot {
                root: self.root.clone(),
                state_dir: self.state.clone(),
                policy_source: None,
            },
            target_branch: None,
        }
    }
}

fn code(result: Result<Value, super::HostError>) -> &'static str {
    result.expect_err("refused").code
}

// contract-test: supporting surface=cli assertions=projects.sources.chat-worktrees
#[test]
fn commit_stages_everything_and_moves_the_hidden_ref() {
    let f = fixture();
    let wt = f.worktree();
    fs::write(wt.path.join("new.txt"), "x\n").expect("write");
    fs::write(wt.path.join("README.md"), "changed\n").expect("write");
    let answer = git_ops::commit(&wt, "Add feature").expect("commit");
    let head = git(&wt.path, &["rev-parse", "HEAD"]);
    assert_eq!(answer["commit"], head.as_str());
    assert_eq!(answer["ahead"], 1);
    assert_eq!(git(&f.root, &["rev-parse", &hidden_ref(CHAT)]), head);
    assert_eq!(
        git(&wt.path, &["log", "-1", "--format=%an <%ae>|%s"]),
        "Test <test@example.org>|Add feature"
    );
    assert_eq!(git(&wt.path, &["status", "--porcelain"]), "");
    assert_eq!(code(git_ops::commit(&wt, "Again")), "nothing_to_commit");
}

// contract-test: supporting surface=cli assertions=projects.sources.chat-worktrees
#[test]
fn commit_without_a_configured_identity_is_refused_and_changes_nothing() {
    let f = fixture();
    let wt = f.worktree();
    git(&f.root, &["config", "user.name", ""]);
    fs::write(wt.path.join("new.txt"), "x\n").expect("write");
    let before = git(&wt.path, &["rev-parse", "HEAD"]);
    assert_eq!(code(git_ops::commit(&wt, "msg")), "identity_missing");
    assert_eq!(git(&wt.path, &["rev-parse", "HEAD"]), before);
    assert!(
        git(&wt.path, &["status", "--porcelain"]).contains("new.txt"),
        "nothing was staged"
    );
}

// contract-test: supporting surface=cli assertions=projects.sources.chat-worktrees
#[test]
fn status_reports_changes_ahead_count_and_head() {
    let f = fixture();
    let wt = f.worktree();
    let clean = git_ops::status(&f.area(), &wt).expect("status");
    assert_eq!(clean["dirty"], false);
    assert_eq!(clean["ahead"], 0);
    assert_eq!(clean["changed_files"], json!([]));
    fs::write(wt.path.join("new.txt"), "x\n").expect("write");
    git_ops::commit(&wt, "one").expect("commit");
    fs::write(wt.path.join("README.md"), "edit\n").expect("write");
    fs::write(wt.path.join("other.txt"), "y\n").expect("write");
    let state = git_ops::status(&f.area(), &wt).expect("status");
    assert_eq!(state["ahead"], 1);
    assert_eq!(state["landed"], false);
    assert_eq!(state["target_branch"], "dev");
    assert_eq!(
        state["head"],
        git(&wt.path, &["rev-parse", "HEAD"]).as_str()
    );
    assert_eq!(
        state["changed_files"],
        json!([{"path": "README.md", "status": " M"}, {"path": "other.txt", "status": "??"}])
    );
}

// contract-test: supporting surface=cli assertions=projects.sources.chat-worktrees
#[test]
fn land_fast_forwards_a_clean_checked_out_target_with_its_working_tree() {
    let f = fixture();
    let wt = f.worktree();
    fs::write(wt.path.join("feature.txt"), "x\n").expect("write");
    let commit = git_ops::commit(&wt, "feature").expect("commit")["commit"].clone();
    let answer = git_ops::land(&wt).expect("land");
    assert_eq!(answer["landed"], true);
    assert_eq!(answer["commit"], commit);
    assert_eq!(answer["commits"], 1);
    assert_eq!(answer["checked_out"], true);
    assert_eq!(
        git(&f.root, &["rev-parse", "dev"]),
        commit.as_str().expect("str")
    );
    assert_eq!(
        fs::read_to_string(f.root.join("feature.txt")).expect("read"),
        "x\n"
    );
    let again = git_ops::land(&wt).expect("land again");
    assert_eq!(
        (again["landed"].clone(), again["commits"].clone()),
        (json!(true), json!(0))
    );
}

// contract-test: supporting surface=cli assertions=projects.sources.chat-worktrees
#[test]
fn land_rebases_onto_a_moved_target_and_updates_an_unchecked_out_branch() {
    let f = fixture();
    let wt = f.worktree();
    fs::write(wt.path.join("feature.txt"), "x\n").expect("write");
    git_ops::commit(&wt, "feature").expect("commit");
    commit_file(&f.root, "other.txt", "y\n");
    // Leave dev so it is not checked out anywhere: landing moves only the ref.
    git(&f.root, &["checkout", "-q", "-b", "elsewhere"]);
    let answer = git_ops::land(&wt).expect("land");
    assert_eq!(answer["landed"], true);
    assert_eq!(answer["checked_out"], false);
    let dev = git(&f.root, &["rev-parse", "dev"]);
    assert_eq!(answer["commit"], dev.as_str());
    assert_eq!(git(&wt.path, &["rev-parse", "HEAD"]), dev);
    assert_eq!(git(&f.root, &["rev-parse", &hidden_ref(CHAT)]), dev);
    assert_eq!(git(&f.root, &["show", "dev:other.txt"]), "y");
    assert_eq!(git(&f.root, &["show", "dev:feature.txt"]), "x");
    assert_eq!(
        git(&f.root, &["rev-parse", "--abbrev-ref", "HEAD"]),
        "elsewhere"
    );
}

// contract-test: supporting surface=cli assertions=projects.sources.chat-worktrees
#[test]
fn land_conflict_aborts_the_rebase_and_leaves_everything_as_before() {
    let f = fixture();
    let wt = f.worktree();
    fs::write(wt.path.join("README.md"), "chat\n").expect("write");
    git_ops::commit(&wt, "chat edit").expect("commit");
    commit_file(&f.root, "README.md", "main\n");
    let head = git(&wt.path, &["rev-parse", "HEAD"]);
    let dev = git(&f.root, &["rev-parse", "dev"]);
    let answer = git_ops::land(&wt).expect("conflict is an answer");
    assert_eq!(answer["landed"], false);
    assert_eq!(answer["code"], "land_conflict");
    assert_eq!(answer["conflicting_paths"], json!(["README.md"]));
    assert_eq!(git(&wt.path, &["rev-parse", "HEAD"]), head);
    assert_eq!(git(&wt.path, &["status", "--porcelain"]), "");
    assert!(!wt.path.join(".git").is_dir());
    assert_eq!(git(&f.root, &["rev-parse", "dev"]), dev);
    assert_eq!(git(&f.root, &["rev-parse", &hidden_ref(CHAT)]), head);
    assert_eq!(
        code(git_ops::commit(&wt, "none")),
        "nothing_to_commit",
        "no rebase is left in progress"
    );
}

// contract-test: supporting surface=cli assertions=projects.sources.chat-worktrees
#[test]
fn land_is_refused_for_a_dirty_checked_out_target_and_a_dirty_worktree() {
    let f = fixture();
    let wt = f.worktree();
    fs::write(wt.path.join("feature.txt"), "x\n").expect("write");
    git_ops::commit(&wt, "feature").expect("commit");
    let head = git(&wt.path, &["rev-parse", "HEAD"]);
    let dev = git(&f.root, &["rev-parse", "dev"]);
    fs::write(f.root.join("scratch.txt"), "user work\n").expect("write");
    assert_eq!(code(git_ops::land(&wt)), "target_checked_out_dirty");
    assert_eq!(git(&f.root, &["rev-parse", "dev"]), dev);
    assert_eq!(git(&wt.path, &["rev-parse", "HEAD"]), head);
    assert_eq!(
        fs::read_to_string(f.root.join("scratch.txt")).expect("read"),
        "user work\n"
    );
    fs::remove_file(f.root.join("scratch.txt")).expect("remove");
    fs::write(wt.path.join("wip.txt"), "wip\n").expect("write");
    assert_eq!(code(git_ops::land(&wt)), "worktree_dirty");
    assert_eq!(git(&f.root, &["rev-parse", "dev"]), dev);
}

// contract-test: supporting surface=cli assertions=projects.sources.chat-worktrees
#[test]
fn git_operations_need_an_existing_worktree() {
    let f = fixture();
    let none = git_ops::existing_worktree(&f.hosted(), None, 0).expect_err("no chat");
    assert_eq!(none.code, "no_worktree");
    let missing = git_ops::existing_worktree(&f.hosted(), Some(CHAT), 0).expect_err("no worktree");
    assert_eq!(missing.code, "no_worktree");
    f.worktree();
    let (_, found) = git_ops::existing_worktree(&f.hosted(), Some(CHAT), 1).expect("exists");
    assert_eq!(found.chat_id, CHAT);
}

// contract-test: supporting surface=cli assertions=projects.sources.chat-worktrees
#[test]
fn proposals_validate_strictly_and_the_digest_binds_the_message() {
    let commit = git_ops::validate(
        &json!({"operation_id": "op-1", "message": "Add feature"}),
        true,
    )
    .expect("valid");
    assert_eq!(commit.message.as_deref(), Some("Add feature"));
    for bad in [
        json!({"operation_id": "op-1"}),
        json!({"operation_id": "op-1", "message": "  "}),
        json!({"operation_id": "op-1", "message": "m", "force": true}),
        json!({"operation_id": "bad id", "message": "m"}),
    ] {
        assert_eq!(
            code(git_ops::validate(&bad, true).map(|_| Value::Null)),
            "invalid_request",
            "{bad}"
        );
    }
    assert_eq!(
        code(
            git_ops::validate(&json!({"operation_id": "op-1", "message": "m"}), false)
                .map(|_| Value::Null)
        ),
        "invalid_request"
    );
    let key = [7u8; 32];
    let land = GitProposal {
        operation_id: "op-1".into(),
        message: None,
    };
    let a = git_ops::digest(&key, "p1", CHAT, "git_commit", &commit).expect("digest");
    let other = GitProposal {
        message: Some("Other".into()),
        ..commit.clone()
    };
    assert_ne!(
        a,
        git_ops::digest(&key, "p1", CHAT, "git_commit", &other).expect("digest")
    );
    assert_ne!(
        a,
        git_ops::digest(&key, "p1", CHAT, "git_land", &land).expect("digest")
    );
    assert_eq!(a.len(), 64);
}
