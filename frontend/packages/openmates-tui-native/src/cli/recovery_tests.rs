// contract-test: supporting surface=cli assertions=cli.surface.semantic-parity
//! Native `recovery` parity: usage, file-only validation, refusals before any
//! request, and an empty-Project full-sync against a loopback double.
use super::super::super::parity_test_support::{mock, parsed};
use super::*;
use openmates_sdk::crypto;

const PROJECT: &str = "11111111-1111-4111-8111-111111111111";

fn scratch(name: &str) -> std::path::PathBuf {
    let dir = std::env::temp_dir().join(format!("openmates-recovery-cli-{}-{name}", std::process::id()));
    std::fs::create_dir_all(&dir).unwrap();
    dir
}

fn sample(project: &str) -> Value {
    json!({"schema_version": 1, "project": {"project_id": project},
        "plans": [{"plan_id": "plan-1", "linked_project_ids": [project], "user_flows": []}],
        "tasks": [], "dependencies": [], "assumptions": [], "revisions": []})
}

fn write_yaml(dir: &std::path::Path, document: &Value) -> String {
    let path = dir.join("projection.yml");
    std::fs::write(&path, serde_yaml::to_string(document).unwrap()).unwrap();
    path.display().to_string()
}

fn message(result: Result<CliOutput, CliError>) -> String {
    match result {
        Err(CliError::Invalid(message) | CliError::Contract { message, .. }) => message,
        Err(_) => panic!("unexpected error kind"),
        Ok(out) => panic!("unexpected success: {}", out.stdout),
    }
}

#[test]
fn supports_the_recovery_family_and_keeps_only_credential_free_paths_public() {
    for args in [&["openmates", "recovery"][..], &["openmates", "recovery", "full-sync"], &["openmates", "recovery", "validate"], &["openmates", "recovery", "restore"]] {
        assert!(supported(&parsed(args)), "{args:?}");
    }
    assert!(is_public(&parsed(&["openmates", "recovery"])));
    assert!(is_public(&parsed(&["openmates", "recovery", "validate"])));
    assert!(!is_public(&parsed(&["openmates", "recovery", "full-sync"])));
    assert!(!is_public(&parsed(&["openmates", "recovery", "restore"])));
    assert!(public(&parsed(&["openmates", "recovery", "restore"])).is_none());
}

#[test]
fn bare_recovery_prints_npm_usage_and_rejects_unknown_subcommands() {
    let out = public(&parsed(&["openmates", "recovery"])).unwrap().ok().unwrap();
    assert_eq!(out.stdout, format!("{USAGE}\n"));
    assert_eq!(out.exit_code, 0);
    // The parser already refuses undeclared subcommands; a stray positional
    // that reaches the handler keeps the existing CLI's wording.
    let stray = Invocation { path: vec!["recovery".into()], positionals: vec!["bogus".into()], flags: Default::default() };
    assert_eq!(
        message(public(&stray).unwrap()),
        "Unknown recovery command. Use full-sync, validate, or restore."
    );
}

#[test]
fn validate_reads_only_the_file_and_reports_exact_errors() {
    let dir = scratch("validate");
    let path = write_yaml(&dir, &sample("project-1"));
    let out = public(&parsed(&["openmates", "recovery", "validate", "--file", path.as_str()])).unwrap().ok().unwrap();
    assert_eq!(out.stdout, "Recovery projection is valid; no data was changed.\n");
    let out = public(&parsed(&["openmates", "recovery", "validate", path.as_str(), "--json"])).unwrap().ok().unwrap();
    assert_eq!(serde_json::from_str::<Value>(&out.stdout).unwrap(), json!({"valid": true}));
    let missing = dir.join("absent.yml").display().to_string();
    assert_eq!(
        message(public(&parsed(&["openmates", "recovery", "validate", "--file", missing.as_str()])).unwrap()),
        format!("Recovery projection does not exist: {missing}")
    );
    assert_eq!(
        message(public(&parsed(&["openmates", "recovery", "validate"])).unwrap()),
        "Missing --file <projection.yml>."
    );
    let mut cyclic = sample("project-1");
    cyclic["tasks"] = json!([{"task_id": "task-1", "plan_id": null, "linked_project_ids": ["project-1"]}]);
    cyclic["dependencies"] = json!([{"source_ref": "plan:plan-1", "target_ref": "task:task-1"},
        {"source_ref": "task:task-1", "target_ref": "plan:plan-1"}]);
    let path = write_yaml(&dir, &cyclic);
    assert_eq!(
        message(public(&parsed(&["openmates", "recovery", "validate", "--file", path.as_str()])).unwrap()),
        "Work recovery dependency cycle includes plan:plan-1."
    );
    std::fs::remove_dir_all(dir).unwrap();
}

#[tokio::test]
async fn full_sync_and_restore_refuse_missing_inputs_before_any_request() {
    let (mut client, server) = mock(vec![]).await;
    if std::env::var(ROOT_ENV).is_err() {
        let result = execute(&parsed(&["openmates", "recovery", "full-sync", "--project", PROJECT]), &mut client, CancellationToken::new()).await;
        assert_eq!(message(result), "Recovery full-sync requires --root <external-root> or OPENMATES_WORK_RECOVERY_ROOT.");
    }
    let result = execute(&parsed(&["openmates", "recovery", "full-sync", "--root", "/tmp/unused"]), &mut client, CancellationToken::new()).await;
    assert_eq!(message(result), "Missing --project <project-id>.");
    let dir = scratch("restore-refusal");
    let path = write_yaml(&dir, &sample(PROJECT));
    let result = execute(&parsed(&["openmates", "recovery", "restore", "--file", path.as_str(), "--dry-run"]), &mut client, CancellationToken::new()).await;
    assert_eq!(message(result), "Missing --project <project-id>.");
    std::fs::remove_dir_all(dir).unwrap();
    server.abort();
}

#[tokio::test]
async fn full_sync_writes_only_the_named_project_projection() {
    let project = json!({"project": {"project_id": PROJECT,
        "encrypted_project_key": crypto::encrypt_bytes(&[2; 32], &[7; 32]).unwrap(),
        "encrypted_name": crypto::encrypt_combined("Fixture Project", &[2; 32]).unwrap()}});
    let (mut client, server) = mock(vec![project, json!({"plans": []}), json!({"tasks": [], "complete": true})]).await;
    let dir = scratch("full-sync");
    let root = format!("{}/", dir.join("root").display());
    let out = execute(
        &parsed(&["openmates", "recovery", "full-sync", "--project", PROJECT, "--root", root.as_str(), "--json"]),
        &mut client,
        CancellationToken::new(),
    )
    .await
    .ok()
    .unwrap();
    let path = format!("{}{PROJECT}.yml", root);
    assert_eq!(serde_json::from_str::<Value>(&out.stdout).unwrap(), json!({"project_id": PROJECT, "path": path}));
    let written = projection::parse_document(&std::fs::read_to_string(&path).unwrap()).unwrap();
    assert_eq!(written, projection::document(PROJECT, vec![], vec![], vec![], vec![], vec![]));
    let requests = server.await.unwrap();
    assert!(requests[0].starts_with(&format!("GET /v1/projects/{PROJECT} ")));
    assert!(requests[1].starts_with("GET /v1/user-plans?project_id="));
    assert!(requests[2].starts_with("GET /v1/user-tasks?"));
    assert!(requests.iter().all(|request| !request.contains("/v1/chats")));
    std::fs::remove_dir_all(dir).unwrap();
}
