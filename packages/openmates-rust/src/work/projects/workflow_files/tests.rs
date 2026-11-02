use super::*;
// contract-test: supporting surface=sdks.rust assertions=workflows.authoring.atomic-update,cli.surface.semantic-parity
#[test]
fn replacement_preserves_exact_lines_and_absent_final_newlines() {
    assert_eq!(
        replacement("a.workflow.yml", "old", "new\n"),
        "--- a/a.workflow.yml\n+++ b/a.workflow.yml\n@@ -1,1 +1,1 @@\n-old\n\\ No newline at end of file\n+new\n"
    );
    assert_eq!(
        replacement("a.workflow.yml", "", ""),
        "--- a/a.workflow.yml\n+++ b/a.workflow.yml\n@@ -0,0 +0,0 @@\n"
    );
}
// contract-test: supporting surface=sdks.rust assertions=workflows.authoring.atomic-update,auth.secrets.lifecycle
#[test]
fn bound_folder_hash_and_payload_limits_refuse_before_write() {
    for folder in ["../escape", "/absolute", "a//b", "a\\b", "a/./b", "a\n"] {
        assert!(file_path(&json!({"folder_path":folder}), "x.workflow.yml").is_err());
    }
    assert!(
        file_path(
            &json!({"folder_path":"safe","file_path":17}),
            "x.workflow.yml"
        )
        .is_err()
    );
    assert_eq!(
        file_path(&json!({"folder_path":"."}), "x.workflow.yml").unwrap(),
        "x.workflow.yml"
    );
    assert!(
        file_path(
            &json!({"folder_path":"safe","file_path":"else/x.workflow.yml"}),
            "x.workflow.yml"
        )
        .is_err()
    );
    assert!(mutation(&json!({"saved_content":"old"}), "x.workflow.yml", "next").is_err());
    assert!(
        mutation(
            &json!({"base_hash":"0".repeat(64),"saved_content":"old"}),
            "x.workflow.yml",
            "next"
        )
        .is_err()
    );
    assert!(mutation(&json!({}), "x.workflow.yml", &"a".repeat(200 * 1024 + 1)).is_err());
    let prepared = mutation(
        &json!({"base_hash":hash("old"),"saved_content":"old"}),
        "x.workflow.yml",
        "next",
    )
    .unwrap();
    assert_eq!(prepared["operation"], "update_file");
    assert_eq!(prepared["expected_base"], hash("old"));
    assert!(prepared.get("content").is_none());
}
// contract-test: supporting surface=sdks.rust assertions=auth.session.authoritative-enforcement,auth.secrets.lifecycle
#[test]
fn commitment_binds_project_chat_operation_path_and_content() {
    let value = json!({"operation":"create_file","operation_id":"op","path":"x.workflow.yml","expected_base":null,"content":"private"});
    let digest = commitment(&[1; 32], "project", "chat", &value).unwrap();
    assert_eq!(
        digest,
        "76a1113777c1f1b40e5d0bdd8757d33810ef2406d3efc5e559f70d7f13d3f2a0"
    );
    assert_ne!(
        digest,
        commitment(&[1; 32], "other", "chat", &value).unwrap()
    );
    assert_ne!(
        digest,
        commitment(&[1; 32], "project", "other", &value).unwrap()
    );
    let mut changed = value.clone();
    changed["content"] = json!("other");
    assert_ne!(
        digest,
        commitment(&[1; 32], "project", "chat", &changed).unwrap()
    );
    assert_eq!(classify("file_changed"), ("conflict", "file_changed"));
    assert_eq!(classify("source_offline"), ("pending", "source_offline"));
    assert_eq!(
        classify("untrusted private text"),
        ("failed", "workflow_file_write_failed")
    );
}
