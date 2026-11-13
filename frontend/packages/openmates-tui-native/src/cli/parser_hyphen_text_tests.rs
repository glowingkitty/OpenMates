//! `--text` on `projects hosted create|update` accepts dash-leading bodies and diffs; other commands keep strict option parsing.
use super::*;

#[test]
fn hosted_update_accepts_a_unified_diff_as_text() {
    let diff = "--- a/f.txt\n+++ b/f.txt\n@@ -1 +1 @@\n-a\n+b\n";
    let parsed = parse_from([
        "openmates",
        "projects",
        "hosted",
        "update",
        "p",
        "f.txt",
        "base",
        "--chat",
        "c",
        "--text",
        diff,
    ])
    .unwrap();
    let invocation = parsed.invocation.unwrap();
    assert_eq!(invocation.command_path(), "projects hosted update");
    assert_eq!(invocation.text("text"), Some(diff));
    assert_eq!(invocation.text("chat"), Some("c"));
    assert_eq!(invocation.positionals, ["p", "f.txt", "base"]);
}

#[test]
fn hosted_create_accepts_a_dash_leading_body() {
    let parsed = parse_from([
        "openmates",
        "projects",
        "hosted",
        "create",
        "p",
        "notes.md",
        "--text",
        "- item",
        "--chat",
        "c",
        "--json",
    ])
    .unwrap();
    let invocation = parsed.invocation.unwrap();
    assert_eq!(invocation.text("text"), Some("- item"));
    assert_eq!(invocation.text("chat"), Some("c"));
}

#[test]
fn other_project_commands_keep_rejecting_a_dash_leading_text() {
    assert!(
        parse_from([
            "openmates",
            "projects",
            "hosted",
            "read",
            "p",
            "f.txt",
            "--text",
            "--x"
        ])
        .is_err()
    );
}
