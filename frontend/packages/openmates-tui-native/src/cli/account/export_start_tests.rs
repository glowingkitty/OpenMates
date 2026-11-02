// contract-test: supporting surface=cli assertions=cli.surface.semantic-parity
use super::super::settings_more::tests::{mock, parsed};
use super::*;

#[tokio::test]
async fn export_downloads_scans_completes_and_writes_the_archive() {
    let directory = tempfile::tempdir().unwrap();
    let output = directory.path().join("export.zip");
    let (mut client, server) = mock(vec![
        json!({"export":{"export_id":"exp-1","status":"running"}}),
        json!({"manifest":{"selected_domains":["settings"],"report":{"redactions":["x"]}}}),
        json!({"chunks":[{"chunk_id":"c1"}]}),
        json!({"chunk":{"chunk_id":"c1","domain":"settings","payload":{"language":"en"}}}),
        json!({"export":{"export_id":"exp-1","status":"completed"}}),
    ])
    .await;
    let invocation = parsed(&[
        "openmates",
        "settings",
        "account",
        "export",
        "--domains",
        "settings",
        "--output",
        output.to_str().unwrap(),
        "--json",
    ]);
    assert!(supported(&invocation));
    let result = execute(&invocation, &mut client).await.ok().unwrap();
    let value: Value = serde_json::from_str(&result.stdout).unwrap();
    assert_eq!(value["archive"]["format"], "zip");
    assert!(output.is_file());
    let requests = server.await.unwrap();
    assert!(requests[0].starts_with("POST /v1/account-exports "));
    assert!(requests[0].contains(r#""domains":["settings"]"#));
    assert!(requests[4].starts_with("POST /v1/account-exports/exp-1/complete "));
}

#[tokio::test]
async fn secret_chunks_cancel_the_job_and_partial_exports_need_acceptance() {
    let (mut client, server) = mock(vec![
        json!({"export":{"export_id":"exp-1"}}),
        json!({"manifest":{}}),
        json!({"chunks":[{"chunk_id":"c1"}]}),
        json!({"chunk":{"chunk_id":"c1","payload":{"refresh_token":"x"}}}),
        json!({"export":{"status":"cancelled"}}),
    ])
    .await;
    let result = execute(
        &parsed(&["openmates", "settings", "account", "export", "start"]),
        &mut client,
    )
    .await;
    assert!(
        matches!(result, Err(CliError::Invalid(m)) if m.contains("forbidden secret field 'refresh_token'"))
    );
    assert!(server.await.unwrap()[4].starts_with("POST /v1/account-exports/exp-1/cancel "));
    let (mut client, _server) = mock(vec![
        json!({"export":{"export_id":"exp-2"}}),
        json!({"manifest":{}}),
        json!({"chunks":[]}),
        json!({"export":{"export_id":"exp-2","status":"partial"}}),
    ])
    .await;
    let result = execute(&parsed(&["openmates", "account", "export"]), &mut client).await;
    assert!(
        matches!(result, Err(CliError::Invalid(m)) if m == "Account export exp-2 is partial. Re-run with --accept-partial to accept it, or inspect/cancel the job first.")
    );
}
