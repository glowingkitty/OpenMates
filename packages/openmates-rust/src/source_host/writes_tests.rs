//! Write semantics: validation, proposal digest, create/update, replay, conflicts and authority.
use super::writes::{Mutation, WriteAuthority, WriteRequest, digest, execute, validate};
use super::{HostError, HostResult, sha256_hex};
use serde_json::{Value, json};
use std::fs;
use std::path::{Path, PathBuf};

struct Counting {
    calls: usize,
    deny_after: Option<usize>,
}

impl WriteAuthority for Counting {
    async fn authorize(&mut self) -> HostResult<()> {
        self.calls += 1;
        if self.deny_after.is_some_and(|limit| self.calls > limit) {
            return Err(HostError::new("write_authorization_denied", "revoked"));
        }
        Ok(())
    }
}

fn allow() -> Counting {
    Counting {
        calls: 0,
        deny_after: None,
    }
}

struct Fixture {
    _source: tempfile::TempDir,
    _state: tempfile::TempDir,
    _journal: tempfile::TempDir,
    root: PathBuf,
    state: PathBuf,
    journal: PathBuf,
}

fn fixture() -> Fixture {
    let source = tempfile::tempdir().expect("tempdir");
    let state = tempfile::tempdir().expect("tempdir");
    let journal = tempfile::tempdir().expect("tempdir");
    let root = fs::canonicalize(source.path()).expect("canonical");
    fs::create_dir(root.join(".git")).expect("git");
    fs::write(root.join(".gitignore"), "ignored/\n").expect("write");
    fs::create_dir(root.join("docs")).expect("dir");
    fs::write(root.join("docs/note.txt"), "one\ntwo\n").expect("write");
    Fixture {
        root,
        state: state.path().to_path_buf(),
        journal: journal.path().join("journal"),
        _source: source,
        _state: state,
        _journal: journal,
    }
}

async fn run(f: &Fixture, mutation: &Value, authority: &mut Counting) -> HostResult<Value> {
    let mutation = validate(mutation)?;
    execute(
        WriteRequest {
            root: &f.root,
            state_dir: &f.state,
            policy_source: None,
            mutation: &mutation,
            scope: "project:p1/source:s1/chat:c1",
            journal_root: Some(f.journal.clone()),
        },
        authority,
    )
    .await
}

fn create(path: &str, op: &str, content: &str) -> Value {
    json!({"operation": "create_file", "operation_id": op, "path": path, "expected_base": null, "content": content})
}

fn update(path: &str, op: &str, base: &str, patch: &str) -> Value {
    json!({"operation": "update_file", "operation_id": op, "path": path, "expected_base": base, "patch": patch})
}

const NOTE_PATCH: &str = "--- a/docs/note.txt\n+++ b/docs/note.txt\n@@ -1,2 +1,2 @@\n one\n-two\n+TWO\n";

fn read(root: &Path, path: &str) -> String {
    fs::read_to_string(root.join(path)).expect("read")
}

#[test]
fn validation_matches_the_npm_shape() {
    assert!(validate(&create("a.txt", "op-1", "x")).is_ok());
    let base = "0".repeat(64);
    assert!(validate(&update("a.txt", "op-1", &base, "p")).is_ok());
    let bad = [
        json!({"operation": "create_file", "operation_id": "op", "path": "a", "content": "x"}),
        json!({"operation": "update_file", "operation_id": "op", "path": "a", "expected_base": "short", "patch": "p"}),
        json!({"operation": "update_file", "operation_id": "op", "path": "a", "expected_base": base, "patch": ""}),
        json!({"operation": "delete_file", "operation_id": "op", "path": "a"}),
        json!({"operation": "create_file", "operation_id": "bad id", "path": "a", "expected_base": null, "content": "x"}),
        json!({"operation": "create_file", "operation_id": "op", "path": "a", "expected_base": null, "content": "x", "extra": 1}),
    ];
    for value in bad {
        assert_eq!(validate(&value).expect_err("invalid").code, "operation_failed", "{value}");
    }
}

#[test]
fn digest_is_hmac_over_the_npm_message() {
    use hmac::{Hmac, Mac};
    use sha2::Sha256;
    let key = [7u8; 32];
    let m: Mutation = validate(&create("a.txt", "op-1", "hi")).expect("valid");
    let message = r#"["openmates-project-file-proposal-v1","p1","c1","create_file","op-1","a.txt",null,"hi",null]"#;
    let mut mac = <Hmac<Sha256> as Mac>::new_from_slice(&key).expect("key");
    mac.update(message.as_bytes());
    let expected: String = mac.finalize().into_bytes().iter().map(|b| format!("{b:02x}")).collect();
    assert_eq!(digest(&key, "p1", "c1", &m).expect("digest"), expected);
    assert!(digest(&key, "", "c1", &m).is_err());
}

#[tokio::test]
async fn create_writes_a_new_file_and_replays_idempotently() {
    let f = fixture();
    let mut authority = allow();
    let first = run(&f, &create("docs/new.txt", "op-create", "hello\n"), &mut authority).await.expect("creates");
    assert_eq!(read(&f.root, "docs/new.txt"), "hello\n");
    assert_eq!(first["operation"], "create_file");
    assert_eq!(first["before_hash"], Value::Null);
    assert_eq!(first["after_hash"], sha256_hex(b"hello\n").as_str());
    assert_eq!(authority.calls, 2, "checked before and under the locks");
    let replay = run(&f, &create("docs/new.txt", "op-create", "hello\n"), &mut authority).await.expect("replays");
    assert_eq!(replay["replayed"], true);
    assert_eq!(replay["already_applied"], true);
    let conflict = run(&f, &create("docs/other.txt", "op-create", "x"), &mut authority).await.expect_err("conflict");
    assert_eq!(conflict.code, "operation_conflict");
}

#[tokio::test]
async fn create_refuses_existing_targets() {
    let f = fixture();
    let error = run(&f, &create("docs/note.txt", "op-2", "x"), &mut allow()).await.expect_err("exists");
    assert_eq!(error.code, "target_exists");
    assert_eq!(read(&f.root, "docs/note.txt"), "one\ntwo\n");
}

#[tokio::test]
async fn update_applies_a_patch_against_the_expected_base() {
    let f = fixture();
    let base = sha256_hex(b"one\ntwo\n");
    let result = run(&f, &update("docs/note.txt", "op-up", &base, NOTE_PATCH), &mut allow()).await.expect("updates");
    assert_eq!(read(&f.root, "docs/note.txt"), "one\nTWO\n");
    assert_eq!(result["before_hash"], base.as_str());
    assert_eq!(result["applied_diff"], NOTE_PATCH);
}

#[tokio::test]
async fn update_preserves_the_original_mode() {
    use std::os::unix::fs::PermissionsExt;
    let f = fixture();
    fs::set_permissions(f.root.join("docs/note.txt"), fs::Permissions::from_mode(0o640)).expect("chmod");
    let base = sha256_hex(b"one\ntwo\n");
    run(&f, &update("docs/note.txt", "op-mode", &base, NOTE_PATCH), &mut allow()).await.expect("updates");
    let mode = fs::metadata(f.root.join("docs/note.txt")).expect("stat").permissions().mode() & 0o777;
    assert_eq!(mode, 0o640);
}

#[tokio::test]
async fn stale_bases_and_bad_patches_never_land() {
    let f = fixture();
    let stale = run(&f, &update("docs/note.txt", "op-s", &"a".repeat(64), NOTE_PATCH), &mut allow()).await;
    assert_eq!(stale.expect_err("stale").code, "file_changed");
    let base = sha256_hex(b"one\ntwo\n");
    let wrong = NOTE_PATCH.replace(" one", " uno");
    let invalid = run(&f, &update("docs/note.txt", "op-p", &base, &wrong), &mut allow()).await;
    assert_eq!(invalid.expect_err("bad patch").code, "invalid_patch");
    let missing = run(&f, &update("docs/gone.txt", "op-g", &base, NOTE_PATCH), &mut allow()).await;
    assert!(missing.is_err());
    assert_eq!(read(&f.root, "docs/note.txt"), "one\ntwo\n");
}

#[tokio::test]
async fn protected_and_escaping_paths_are_refused() {
    let f = fixture();
    for path in [".env", ".git/config", "ignored/x.txt", ".openmates/permissions.yml"] {
        let error = run(&f, &create(path, "op-p", "x"), &mut allow()).await.expect_err("protected");
        assert_eq!(error.code, "protected_path", "{path}");
    }
    for path in ["../out.txt", "/abs.txt", "a//b.txt", "./a.txt"] {
        assert!(run(&f, &create(path, "op-e", "x"), &mut allow()).await.is_err(), "{path}");
    }
    let outside = tempfile::tempdir().expect("tempdir");
    std::os::unix::fs::symlink(outside.path(), f.root.join("link")).expect("symlink");
    assert!(run(&f, &create("link/x.txt", "op-l", "x"), &mut allow()).await.is_err());
    assert!(!outside.path().join("x.txt").exists());
}

#[tokio::test]
async fn revoked_authority_under_the_locks_stops_the_write() {
    let f = fixture();
    let mut authority = Counting {
        calls: 0,
        deny_after: Some(1),
    };
    let error = run(&f, &create("docs/late.txt", "op-late", "x"), &mut authority).await.expect_err("denied");
    assert_eq!(error.code, "write_authorization_denied");
    assert!(!f.root.join("docs/late.txt").exists());
}
