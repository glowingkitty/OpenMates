// contract-test: supporting surface=cli assertions=cli.surface.semantic-parity
//! Vectors ported from the existing CLI's work-recovery tests plus the exact
//! error texts the native CLI must preserve. No network or account access.
use super::*;

fn document() -> Value {
    json!({
        "schema_version": 1,
        "project": {"project_id": "project-1"},
        "plans": [{"plan_id": "plan-1", "linked_project_ids": ["project-1"], "goal": "Ship it", "user_flows": []}],
        "tasks": [{"task_id": "task-1", "plan_id": "plan-1", "linked_project_ids": ["project-1"]}],
        "dependencies": [{"source_ref": "task:task-1", "target_ref": "plan:plan-1"}],
        "assumptions": [{"plan_id": "plan-1", "assumption_id": "A-1", "sources": [{"kind": "url", "url": "https://example.com"}]}],
        "revisions": [{"plan_id": "plan-1", "revision_id": "R-1", "snapshot": {"plan_id": "plan-1", "goal": "Ship it"}}],
    })
}

fn error(value: &Value) -> String {
    validate_document(value).unwrap_err().to_string()
}

#[test]
fn recovery_validates_typed_pointerless_plan_projections() {
    let value = document();
    validate_document(&value).unwrap();
    assert!(find_conflicts(&value, "project-1", &[], &[]).is_empty());
}

#[test]
fn recovery_rejects_ciphertext_and_cyclic_dependencies() {
    let mut ciphertext = document();
    ciphertext["plans"][0]["encrypted_goal"] = json!("ciphertext");
    assert_eq!(error(&ciphertext), "Recovery projection must not contain ciphertext field encrypted_goal.");
    let mut cyclic = document();
    cyclic["dependencies"].as_array_mut().unwrap().push(json!({"source_ref": "plan:plan-1", "target_ref": "task:task-1"}));
    assert_eq!(error(&cyclic), "Work recovery dependency cycle includes task:task-1.");
}

#[test]
fn recovery_reports_exact_schema_and_reference_errors() {
    assert_eq!(error(&json!("text")), "Work recovery document must be an object.");
    assert_eq!(error(&json!({"schema_version": 2})), "Unsupported work recovery schema_version.");
    assert_eq!(error(&json!({"schema_version": 1, "project": {}})), "Work recovery document requires project.project_id.");
    let mut missing = document();
    missing.as_object_mut().unwrap().remove("revisions");
    assert_eq!(error(&missing), "Work recovery document requires revisions.");
    let mut duplicate = document();
    let plan = duplicate["plans"][0].clone();
    duplicate["plans"].as_array_mut().unwrap().push(plan);
    assert_eq!(error(&duplicate), "Recovery document has duplicate plan ID plan-1.");
    let mut scoped = document();
    scoped["tasks"][0]["linked_project_ids"] = json!(["project-1", "project-2"]);
    assert_eq!(error(&scoped), "Recovery task must be scoped only to project project-1.");
    let mut orphan = document();
    orphan["tasks"][0]["plan_id"] = json!("plan-9");
    assert_eq!(error(&orphan), "Task references missing plan plan-9.");
    let mut no_id = document();
    no_id["assumptions"][0]["assumption_id"] = json!("");
    assert_eq!(error(&no_id), "Recovery assumption requires assumption_id.");
    let mut sources = document();
    sources["assumptions"][0]["sources"] = json!("text");
    assert_eq!(error(&sources), "Assumption sources must be a typed cleartext proof list.");
    let mut snapshot = document();
    snapshot["revisions"][0]["snapshot"] = json!([]);
    assert_eq!(error(&snapshot), "Revision requires a canonical plan snapshot.");
    let mut dangling = document();
    dangling["dependencies"][0]["target_ref"] = json!("plan:plan-9");
    assert_eq!(error(&dangling), "Work recovery dependency references missing object plan:plan-9.");
    let mut half = document();
    half["dependencies"][0]["target_ref"] = json!("");
    assert_eq!(error(&half), "Work recovery dependencies require source_ref and target_ref.");
}

#[test]
fn recovery_ignores_server_generated_metadata_during_semantic_comparison() {
    let mut restored = document();
    restored["plans"][0]["version"] = json!(2);
    restored["tasks"][0]["position"] = json!(10);
    restored["revisions"][0]["revision_id"] = json!("R-2");
    assert!(semantically_equal(&document(), &restored));
    restored["plans"][0]["goal"] = json!("Changed");
    restored["tasks"][0]["extra"] = json!(true);
    restored["assumptions"].as_array_mut().unwrap().clear();
    assert_eq!(
        semantic_mismatch_paths(&document(), &restored),
        vec!["$.assumptions.length", "$.plans[0].goal", "$.tasks[0].extra"]
    );
    let mut float = document();
    float["schema_version"] = json!(1.0);
    assert!(semantically_equal(&document(), &float));
}

#[test]
fn recovery_conflicts_name_existing_and_wrong_project_objects() {
    let value = document();
    let conflicts = find_conflicts(&value, "project-1", &["plan-1".into()], &["task-1".into()]);
    assert_eq!(
        serde_json::to_string(&conflicts).unwrap(),
        r#"[{"kind":"plan","id":"plan-1","reason":"already_exists"},{"kind":"task","id":"task-1","reason":"already_exists"}]"#
    );
    let wrong = find_conflicts(&value, "project-2", &[], &[]);
    assert_eq!(wrong, vec![RecoveryConflict { kind: "plan", id: "project-1".into(), reason: "wrong_project" }]);
    let report = dry_run_report(&value, "project-1", &[]);
    assert_eq!(report["would_restore"], json!({"plans":1,"tasks":1,"assumptions":1,"dependencies":1,"revisions":1}));
    assert_eq!(dry_run_report(&value, "project-2", &wrong)["would_restore"], Value::Null);
}

#[test]
fn recovery_projections_match_existing_cli_shapes() {
    let plan = json!({"plan_id": "p", "short_id": "PLAN-1", "slug": "", "approval_state": "draft", "title": "T", "user_flows": []});
    let projected = plan_projection(&plan);
    assert_eq!(projected["slug"], Value::Null);
    assert!(projected.get("approval_state").is_none());
    assert_eq!(projected.as_object().unwrap().len(), 23);
    let task = json!({"task_id": "t", "slug": "s", "blocked_reason": "", "created_at": 1, "read_only": false,
        "external_chat": {"provider": "github", "id": "9"}});
    let projected = task_projection(&task);
    assert_eq!(projected["blocked_reason"], Value::Null);
    assert_eq!(projected["external_chat"], json!({"provider": "github", "id": "9", "title": ""}));
    assert!(projected.get("created_at").is_none() && projected.get("read_only").is_none());
    assert_eq!(projected.as_object().unwrap().len(), 25);
    let assumption = json!({"assumption_id": "A", "text": "Known", "sources": r#"[{"kind":"file","path":"a.rs"}]"#});
    let projected = assumption_projection("p", &assumption).unwrap();
    assert_eq!(projected["sources"], json!([{"kind": "file", "path": "a.rs"}]));
    assert_eq!(projected["linked_criterion_ids"], json!([]));
    assert_eq!(projected["category"], Value::Null);
    let bad = json!({"assumption_id": "A", "sources": r#"[{"kind":"url"}]"#});
    assert_eq!(
        assumption_projection("p", &bad).unwrap_err().to_string(),
        "Assumption encrypted_sources must contain typed proof records."
    );
    let revision = json!({"revision_id": "R", "fingerprint": "f", "created_at": 5});
    assert_eq!(revision_projection("p", &revision, "").unwrap_err().to_string(), "Revision R could not be decrypted.");
    assert_eq!(
        revision_projection("p", &revision, r#"{"encrypted_goal":"x"}"#).unwrap_err().to_string(),
        "Recovery projection must not contain ciphertext field encrypted_goal."
    );
    assert_eq!(revision_projection("p", &revision, r#"{"goal":"x"}"#).unwrap()["snapshot"], json!({"goal": "x"}));
}

#[test]
fn recovery_restore_inputs_require_existing_cli_fields() {
    let project = "00000000-0000-4000-8000-000000000001";
    let mut plan = json!({"plan_id": "p", "title": "T", "goal": "G", "scope_in": "", "scope_out": "", "user_flows": [],
        "assumptions": "", "open_questions": "", "constraints": "", "decisions": "", "risks": "",
        "reference_patterns": "", "context": "", "status": "draft", "slug": null, "primary_chat_id": null});
    let input = plan_create_input(&plan, project).unwrap();
    assert_eq!(input.linked_project_ids, vec![project.to_owned()]);
    assert!(input.slug.is_none() && input.primary_chat_id.is_none());
    plan.as_object_mut().unwrap().remove("risks");
    assert_eq!(plan_create_input(&plan, project).err().unwrap().to_string(), "Recovery record requires risks.");
    let mut task = json!({"task_id": "t", "title": "T", "description": "", "labels": ["a"], "status": "todo",
        "assignee_type": "user", "assignee_hash": null, "priority": 2, "due_at": null});
    let input = task_create_input(&task, project).unwrap();
    assert_eq!((input.assign.as_deref(), input.priority, input.due_at), (Some("user"), Some(2), None));
    task["labels"] = json!([1]);
    assert_eq!(task_create_input(&task, project).err().unwrap().to_string(), "Recovery record requires labels string array.");
    assert_eq!(projection_path("/tmp/root/", "id"), "/tmp/root/id.yml");
    assert_eq!(projection_path("/tmp/root", "id"), "/tmp/root/id.yml");
}

#[cfg(feature = "workflow-yaml")]
#[test]
fn recovery_yaml_round_trips_sorted_and_rejects_invalid_documents() {
    let source = serialize_document(&document()).unwrap();
    assert!(source.find("assumptions:").unwrap() < source.find("dependencies:").unwrap());
    assert!(source.find("plans:").unwrap() < source.find("project:").unwrap());
    assert_eq!(parse_document(&source).unwrap(), document());
    assert_eq!(parse_document("a: [").unwrap_err().to_string(), "Recovery projection is not valid YAML.");
    let mut cyclic = document();
    cyclic["dependencies"].as_array_mut().unwrap().push(json!({"source_ref": "plan:plan-1", "target_ref": "task:task-1"}));
    assert!(serialize_document(&cyclic).is_err());
}

#[cfg(all(feature = "workflow-yaml", unix))]
#[test]
fn recovery_atomic_write_uses_private_permissions_and_leaves_no_temporary_file() {
    use std::os::unix::fs::PermissionsExt;
    let root = std::env::temp_dir().join(format!("openmates-recovery-{}", uuid::Uuid::new_v4()));
    let path = root.join("nested").join("project-1.yml");
    write_document_atomically(&path, &document()).unwrap();
    let mode = std::fs::metadata(&path).unwrap().permissions().mode() & 0o777;
    assert_eq!(mode, 0o600);
    assert!(!root.join("nested").join("project-1.yml.tmp").exists());
    assert_eq!(parse_document(&std::fs::read_to_string(&path).unwrap()).unwrap(), document());
    std::fs::remove_dir_all(root).unwrap();
}
