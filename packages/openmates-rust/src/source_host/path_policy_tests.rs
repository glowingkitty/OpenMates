//! Path policy: gitignore chain, nested scopes, private paths and sticky state.
use super::path_policy::{PathPolicy, PolicyOptions, private_rg_globs};
use std::fs;
use std::path::Path;

fn load(root: &Path, state: &Path, targets: &[&str], nested: bool) -> PathPolicy {
    PathPolicy::load(
        root,
        &PolicyOptions {
            state_dir: state,
            trusted_private: &[],
            targets,
            discover_nested: nested,
            policy_source: None,
        },
    )
    .expect("policy loads")
}

fn setup() -> (tempfile::TempDir, tempfile::TempDir, std::path::PathBuf) {
    let source = tempfile::tempdir().expect("tempdir");
    let state = tempfile::tempdir().expect("tempdir");
    let root = fs::canonicalize(source.path()).expect("canonical");
    fs::create_dir(root.join(".git")).expect("git dir");
    (source, state, root)
}

#[test]
fn builtin_credentials_are_private_case_insensitively() {
    let (_s, state, root) = setup();
    let policy = load(&root, state.path(), &[], false);
    for path in [".env", "app/.env.local", "keys/server.PEM", ".ssh/id_rsa", "x/credentials.json"] {
        assert!(policy.is_private(path, false).expect("valid"), "{path}");
    }
    assert!(policy.is_private(".ssh", true).expect("valid"), "subtree protects its dir");
    assert!(!policy.is_private("src/main.rs", false).expect("valid"));
    assert_eq!(
        policy.assert_readable(".env", false).expect_err("private").code,
        "protected_path"
    );
}

#[test]
fn root_and_target_gitignores_apply() {
    let (_s, state, root) = setup();
    fs::write(root.join(".gitignore"), "dist/\n*.tmp\n").expect("write");
    fs::create_dir_all(root.join("pkg/sub")).expect("dirs");
    fs::write(root.join("pkg/.gitignore"), "local.txt\n").expect("write");
    let policy = load(&root, state.path(), &["pkg/sub/file.txt"], false);
    assert!(policy.is_ignored("dist", true).expect("valid"));
    assert!(policy.is_ignored("a/b.tmp", false).expect("valid"));
    assert!(policy.is_ignored("pkg/local.txt", false).expect("valid"));
    assert!(!policy.is_ignored("local.txt", false).expect("valid"));
    assert_eq!(
        policy.assert_readable("x.tmp", false).expect_err("ignored").code,
        "ignored_path_requires_approval"
    );
    assert!(policy.assert_readable("x.tmp", true).is_ok());
    assert_eq!(policy.assert_writable("x.tmp").expect_err("ignored").code, "protected_path");
}

#[test]
fn nested_ignore_inside_ignored_directory_is_never_read() {
    let (_s, state, root) = setup();
    fs::write(root.join(".gitignore"), "vendor/\n").expect("write");
    fs::create_dir_all(root.join("vendor")).expect("dir");
    fs::write(root.join("vendor/.gitignore"), "!keep.txt\n").expect("write");
    fs::create_dir_all(root.join("app")).expect("dir");
    fs::write(root.join("app/.gitignore"), "*.gen\n").expect("write");
    let policy = load(&root, state.path(), &[], true);
    assert!(policy.is_ignored("vendor/keep.txt", false).expect("valid"));
    assert!(policy.is_ignored("app/x.gen", false).expect("valid"));
}

#[test]
fn source_below_git_root_uses_the_repository_gitignore() {
    let (_s, state, root) = setup();
    fs::write(root.join(".gitignore"), "/sub/secret-build/\n").expect("write");
    fs::create_dir_all(root.join("sub/secret-build")).expect("dirs");
    let policy = load(&root.join("sub"), state.path(), &[], false);
    assert!(policy.is_ignored("secret-build", true).expect("valid"));
}

#[test]
fn configured_private_paths_are_sticky() {
    let (_s, state, root) = setup();
    fs::create_dir_all(root.join(".openmates")).expect("dir");
    fs::write(
        root.join(".openmates/permissions.yml"),
        "schema_version: 1\nfile_access:\n  private_paths:\n    - secrets/**\npresets: []\n",
    )
    .expect("write");
    let policy = load(&root, state.path(), &[], false);
    assert!(policy.is_private("secrets/a.txt", false).expect("valid"));
    assert!(policy.is_private(".openmates/permissions.yml", false).expect("valid"));
    fs::remove_file(root.join(".openmates/permissions.yml")).expect("remove");
    let policy = load(&root, state.path(), &[], false);
    assert!(policy.is_private("secrets/a.txt", false).expect("valid"), "sticky");
    assert!(policy.rg_exclusion_globs().contains(&"secrets/**".to_owned()));
}

#[test]
fn invalid_relative_paths_are_refused() {
    let (_s, state, root) = setup();
    let policy = load(&root, state.path(), &[], false);
    for path in ["", "/abs", "a//b", "a/../b", "./a", "a\\b"] {
        assert!(policy.is_ignored(path, false).is_err(), "{path:?}");
    }
}

#[test]
fn private_rg_globs_follow_npm() {
    assert_eq!(private_rg_globs("id_rsa"), vec!["id_rsa", "**/id_rsa"]);
    assert_eq!(private_rg_globs("/top/"), vec!["top", "top/**"]);
    assert_eq!(private_rg_globs("a/b"), vec!["a/b"]);
}
