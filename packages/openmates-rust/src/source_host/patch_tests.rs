//! Exact unified-diff application and create-diff output (npm `projectFilePatch`).
use super::patch::{apply, create_diff};

#[test]
fn applies_a_single_hunk_update() {
    let original = "one\ntwo\nthree\n";
    let diff = "--- a/notes.txt\n+++ b/notes.txt\n@@ -1,3 +1,3 @@\n one\n-two\n+TWO\n three\n";
    assert_eq!(apply(original, diff, "notes.txt").expect("applies"), "one\nTWO\nthree\n");
}

#[test]
fn applies_multiple_hunks_and_appends() {
    let original = "a\nb\nc\nd\ne\nf\n";
    let diff = "--- a/f\n+++ b/f\n@@ -1,2 +1,2 @@\n-a\n+A\n b\n@@ -6 +6,2 @@\n f\n+g\n";
    assert_eq!(apply(original, diff, "f").expect("applies"), "A\nb\nc\nd\ne\nf\ng\n");
}

#[test]
fn rejects_context_mismatch() {
    let diff = "--- a/f\n+++ b/f\n@@ -1 +1 @@\n-nope\n+yes\n";
    assert!(apply("actual\n", diff, "f").is_err());
}

#[test]
fn rejects_a_patch_for_another_path() {
    let diff = "--- a/other\n+++ b/other\n@@ -1 +1 @@\n-x\n+y\n";
    assert!(apply("x\n", diff, "f").is_err());
}

#[test]
fn rejects_malformed_hunk_headers() {
    for header in ["@@ -x +1 @@", "@@ -1 +1@@", "@@ -1,a +1 @@"] {
        let diff = format!("--- a/f\n+++ b/f\n{header}\n-x\n+y\n");
        assert!(apply("x\n", &diff, "f").is_err(), "{header}");
    }
}

#[test]
fn honours_missing_trailing_newline_markers() {
    let original = "x";
    let diff = "--- a/f\n+++ b/f\n@@ -1 +1 @@\n-x\n\\ No newline at end of file\n+y\n\\ No newline at end of file\n";
    assert_eq!(apply(original, diff, "f").expect("applies"), "y");
}

#[test]
fn update_patches_cannot_create_files() {
    let diff = create_diff("new.txt", "x\n");
    assert!(apply("", &diff, "new.txt").is_err());
}

#[test]
fn create_diff_matches_npm_output() {
    assert_eq!(
        create_diff("dir/new.txt", "hello\nworld\n"),
        "--- /dev/null\n+++ b/dir/new.txt\n@@ -0,0 +1,2 @@\n+hello\n+world\n"
    );
    assert_eq!(
        create_diff("a", "tail"),
        "--- /dev/null\n+++ b/a\n@@ -0,0 +1,1 @@\n+tail\n\\ No newline at end of file\n"
    );
    assert_eq!(create_diff("a", ""), "--- /dev/null\n+++ b/a\n");
}
