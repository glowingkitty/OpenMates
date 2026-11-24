//! Sandbox host tree: heads in, operations, revisions out, merge, scan.
use super::tests_support::*;
use super::*;
use crate::work::projects::{content_hash, replacement_patch};

fn tree_with(files: &[(&str, &str)]) -> (tempfile::TempDir, ProjectTree) {
    let dir = tempfile::tempdir().unwrap();
    let mut tree = new_tree(dir.path());
    let heads: Vec<Value> = files.iter().map(|(p, t)| head(p, t, 1)).collect();
    let report = tree.apply_heads(&heads);
    assert_eq!(report.failed, Vec::<(String, String)>::new());
    (dir, tree)
}

fn read(dir: &tempfile::TempDir, path: &str) -> String {
    std::fs::read_to_string(dir.path().join(path)).unwrap()
}

#[test]
fn apply_heads_writes_files_and_reports() {
    let (dir, _tree) = tree_with(&[("src/a.txt", "hello"), ("b.txt", "world!")]);
    assert_eq!(read(&dir, "src/a.txt"), "hello");
    let mut tree = new_tree(dir.path());
    let report = tree.apply_heads(&[head("b.txt", "world!", 1)]);
    assert_eq!((report.written, report.bytes), (1, 6));
}

#[test]
fn bad_paths_and_wrong_project_are_refused() {
    let dir = tempfile::tempdir().unwrap();
    let mut tree = new_tree(dir.path());
    for bad in ["../escape.txt", "/etc/passwd", "a/../../x"] {
        let report = tree.apply_heads(&[head(bad, "x", 1)]);
        assert_eq!(report.written, 0, "{bad}");
        assert_eq!(report.failed.len(), 1);
        assert!(tree.resolve(bad).is_err(), "{bad}");
    }
    assert!(!dir.path().parent().unwrap().join("escape.txt").exists());
    let mut other = head("ok.txt", "x", 1);
    other["embed_keys"][0]["hashed_project_id"] = json!(hash("someone-else"));
    assert_eq!(tree.apply_heads(&[other]).written, 0);
}

#[test]
fn read_list_search_have_the_device_shapes() {
    let (_dir, mut tree) = tree_with(&[("a.txt", "alpha\nbeta"), ("b.txt", "gamma")]);
    let read = tree.run_op("read_text", &json!({"path": "a.txt"})).unwrap();
    assert!(read.revisions.is_empty());
    let r = &read.result;
    assert_eq!(r["content"], "alpha\nbeta");
    assert_eq!(r["expected_base"], content_hash("alpha\nbeta"));
    assert_eq!(
        (r["revision"].as_u64(), r["size_bytes"].as_u64()),
        (Some(1), Some(10))
    );
    assert_eq!(
        (r["truncated"].clone(), r["embed_id"].clone()),
        (json!(false), json!(embed_id("a.txt")))
    );
    let list = tree.run_op("list", &json!({})).unwrap().result;
    assert_eq!(list["entries"].as_array().unwrap().len(), 2);
    assert_eq!(list["truncated"], false);
    let found = tree
        .run_op("search", &json!({"query": "beta", "target": "content"}))
        .unwrap()
        .result;
    assert_eq!(found["matches"][0]["path"], "a.txt");
    assert_eq!(found["matches"][0]["line"], 2);
    assert_eq!(found["truncated"], false);
    let by_name = tree
        .run_op("search", &json!({"query": "b.t", "target": "files"}))
        .unwrap()
        .result;
    assert_eq!(by_name["matches"][0]["path"], "b.txt");
}

#[test]
fn unsupported_operation_and_protected_paths_are_refused() {
    let (_dir, mut tree) = tree_with(&[("a.txt", "x")]);
    assert_eq!(
        tree.run_op("project_commit", &json!({})).err(),
        Some(HostedFileError::Refused("unsupported_operation"))
    );
    assert!(
        tree.run_op("read_text", &json!({"path": "../a.txt"}))
            .is_err()
    );
    assert!(
        tree.run_op("create_file", &json!({"path": ".env", "content": "S=1"}))
            .is_err()
    );
}

#[test]
fn create_round_trips_through_the_client_decode() {
    let (dir, mut tree) = tree_with(&[("a.txt", "x")]);
    let out = tree
        .run_op(
            "create_file",
            &json!({"path": "src/new.rs", "content": "fn main() {}\n"}),
        )
        .unwrap();
    assert_eq!(read(&dir, "src/new.rs"), "fn main() {}\n");
    assert_eq!(out.result["created"], true);
    let rev = &out.revisions[0];
    assert_eq!((rev.kind, rev.base_version), (RevisionKind::Create, None));
    assert!(rev.transaction["proposal_digest"].is_string());
    assert_eq!(rev.transaction["chat_id"], CHAT);
    let kinds: Vec<&str> = rev.transaction["create"]["key_wrappers"]
        .as_array()
        .unwrap()
        .iter()
        .map(|w| w["key_type"].as_str().unwrap())
        .collect();
    assert_eq!(kinds, ["project", "chat"]);
    // A second device opens the committed head with the same Project key.
    let other_dir = tempfile::tempdir().unwrap();
    let mut other = new_tree(other_dir.path());
    let report = other.apply_heads(&[head_of(rev, 1)]);
    assert_eq!(report.written, 1);
    assert_eq!(
        std::fs::read_to_string(other_dir.path().join("src/new.rs")).unwrap(),
        "fn main() {}\n"
    );
}

#[test]
fn create_without_chat_key_leaves_the_chat_wrapper_out() {
    let (_dir, mut tree) = tree_with(&[("a.txt", "x")]);
    tree.set_chat(CHAT, None);
    let out = tree
        .run_op("create_file", &json!({"path": "n.txt", "content": "n"}))
        .unwrap();
    let rows = out.revisions[0].transaction["create"]["key_wrappers"]
        .as_array()
        .unwrap();
    assert_eq!(rows.len(), 1);
    assert_eq!(rows[0]["key_type"], "project");
}

#[test]
fn update_patch_commits_new_content_and_old_base_is_stale() {
    let (dir, mut tree) = tree_with(&[("a.txt", "one\ntwo\nthree")]);
    let patch = replacement_patch("a.txt", "one\ntwo\nthree", "one\n2\nthree");
    let args =
        json!({"path": "a.txt", "expected_base": content_hash("one\ntwo\nthree"), "patch": patch});
    let out = tree.run_op("update_file", &args).unwrap();
    assert_eq!(read(&dir, "a.txt"), "one\n2\nthree");
    let rev = &out.revisions[0];
    assert_eq!(
        (rev.kind, rev.base_version),
        (RevisionKind::Update, Some(1))
    );
    assert_eq!(rev.transaction["expected_revision"], 1);
    let other_dir = tempfile::tempdir().unwrap();
    let mut other = new_tree(other_dir.path());
    other.apply_heads(&[head_of(rev, 2)]);
    assert_eq!(
        std::fs::read_to_string(other_dir.path().join("a.txt")).unwrap(),
        "one\n2\nthree"
    );
    assert_eq!(
        tree.run_op("update_file", &args).err(),
        Some(HostedFileError::Refused("stale_base"))
    );
}

#[test]
fn rename_and_delete_move_files_and_emit_link_revisions() {
    let (dir, mut tree) = tree_with(&[("a.txt", "x"), ("b.txt", "y")]);
    let moved = tree
        .run_op(
            "rename_file",
            &json!({"path": "a.txt", "new_path": "docs/c.txt"}),
        )
        .unwrap();
    assert_eq!(moved.result["renamed"], true);
    assert_eq!(read(&dir, "docs/c.txt"), "x");
    assert!(!dir.path().join("a.txt").exists());
    let rev = &moved.revisions[0];
    assert_eq!(
        (rev.kind, rev.path.as_str(), rev.base_version),
        (RevisionKind::Move, "docs/c.txt", Some(1))
    );
    assert_eq!(rev.transaction["action"], "rename");
    let gone = tree
        .run_op("delete_file", &json!({"path": "b.txt"}))
        .unwrap();
    assert_eq!(gone.result["deleted"], true);
    assert_eq!(gone.revisions[0].kind, RevisionKind::Delete);
    assert!(!dir.path().join("b.txt").exists());
    assert_eq!(tree.paths(), ["docs/c.txt"]);
}

#[test]
fn two_devices_edit_different_lines_and_both_survive() {
    let base = ten_lines();
    let (dir, mut tree) = tree_with(&[("f.txt", &base)]);
    std::fs::write(
        dir.path().join("f.txt"),
        base.replace("line 1\n", "mine 1\n"),
    )
    .unwrap();
    let theirs = base.replace("line 10", "theirs 10");
    let outcome = tree
        .merge_with_head("f.txt", &head("f.txt", &theirs, 2))
        .unwrap();
    let MergeOutcome::Merged {
        revision: Some(rev),
    } = outcome
    else {
        panic!("expected a clean merge with a revision");
    };
    let merged = read(&dir, "f.txt");
    assert!(merged.starts_with("mine 1\n") && merged.ends_with("theirs 10"));
    assert_eq!(
        (rev.kind, rev.base_version),
        (RevisionKind::Update, Some(2))
    );
    let other_dir = tempfile::tempdir().unwrap();
    let mut other = new_tree(other_dir.path());
    other.apply_heads(&[head_of(&rev, 3)]);
    assert_eq!(
        std::fs::read_to_string(other_dir.path().join("f.txt")).unwrap(),
        merged
    );
    tree.mark_committed("f.txt", &rev.embed_id, 3).unwrap();
    assert!(tree.scan_changes().is_empty());
}

#[test]
fn same_line_edit_is_a_conflict_that_loses_nothing() {
    let base = ten_lines();
    let (dir, mut tree) = tree_with(&[("f.txt", &base)]);
    let ours = base.replace("line 5", "ours 5");
    std::fs::write(dir.path().join("f.txt"), &ours).unwrap();
    let theirs = base.replace("line 5", "theirs 5");
    let outcome = tree
        .merge_with_head("f.txt", &head("f.txt", &theirs, 2))
        .unwrap();
    let MergeOutcome::Conflict { conflict_text } = outcome else {
        panic!("expected a conflict");
    };
    assert_eq!(read(&dir, "f.txt"), ours);
    assert!(conflict_text.contains("ours 5") && conflict_text.contains("theirs 5"));
    assert!(conflict_text.contains("<<<<<<<"));
}

#[test]
fn untouched_local_file_takes_the_head_without_a_revision() {
    let (dir, mut tree) = tree_with(&[("f.txt", "old")]);
    let outcome = tree
        .merge_with_head("f.txt", &head("f.txt", "new", 2))
        .unwrap();
    assert_eq!(outcome, MergeOutcome::Merged { revision: None });
    assert_eq!(read(&dir, "f.txt"), "new");
}

#[test]
fn scan_picks_up_disk_changes_and_skips_ignored_paths() {
    let (dir, mut tree) = tree_with(&[
        ("a.txt", "one"),
        ("gone.txt", "bye"),
        (".gitignore", "build/\n"),
    ]);
    std::fs::write(dir.path().join("a.txt"), "one\ntwo").unwrap();
    std::fs::remove_file(dir.path().join("gone.txt")).unwrap();
    std::fs::write(dir.path().join("fresh.txt"), "fresh").unwrap();
    for ignored in ["build/out.js", "node_modules/p/i.js", ".git/config"] {
        let target = dir.path().join(ignored);
        std::fs::create_dir_all(target.parent().unwrap()).unwrap();
        std::fs::write(target, "x").unwrap();
    }
    let revs = tree.scan_changes();
    let mut seen: Vec<(String, RevisionKind)> =
        revs.iter().map(|r| (r.path.clone(), r.kind)).collect();
    seen.sort_by(|a, b| a.0.cmp(&b.0));
    assert_eq!(
        seen,
        [
            ("a.txt".to_owned(), RevisionKind::Update),
            ("fresh.txt".to_owned(), RevisionKind::Create),
            ("gone.txt".to_owned(), RevisionKind::Delete),
        ]
    );
    assert!(
        tree.scan_changes().is_empty(),
        "scanned changes are not reported twice"
    );
}
