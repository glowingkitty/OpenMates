// contract-test: supporting surface=cli assertions=cli.surface.semantic-parity
use super::*;
use super::super::settings_more::tests::{mock, parsed};

#[tokio::test]
async fn ideabucket_commands_route_validate_and_print_json() {
    for args in [
        vec!["openmates", "ideabucket", "add", "buy", "milk", "--bucket", "2026-11-02"],
        vec!["openmates", "ideabucket", "status"],
        vec!["openmates", "ideabucket", "status", "2026-11-02"],
        vec!["openmates", "ideabucket", "settings", "set", "--times", "09:00,18:00"],
        vec!["openmates", "ideabucket", "process", "2026-11-02", "--now"],
    ] {
        let invocation = parsed(&args);
        assert!(supported(&invocation), "{args:?}");
        assert!(super::super::super::handlers::requirements(&invocation).supported, "{args:?}");
    }
    assert_eq!(unix_seconds("1700000000000").ok(), Some(1_700_000_000));
    let (mut client, server) = mock(vec![serde_json::json!({"status":"queued"})]).await;
    let output = execute(&parsed(&["openmates", "ideabucket", "process", "2026-11-02", "--now"]), &mut client).await.ok().unwrap();
    assert_eq!(serde_json::from_str::<serde_json::Value>(&output.stdout).unwrap()["status"], "queued");
    for (args, message) in [
        (vec!["openmates", "ideabucket", "process"], "Missing IdeaBucket bucket ID for process."),
        (vec!["openmates", "ideabucket", "settings", "set", "--times", "25:00"], "Invalid IdeaBucket processing time '25:00'. Expected HH:MM in 24-hour format."),
        (vec!["openmates", "ideabucket", "add", "x", "--scheduled-at", "soon"], "Invalid --scheduled-at; expected Unix seconds."),
    ] {
        match execute(&parsed(&args), &mut client).await {
            Err(CliError::Invalid(actual)) => assert_eq!(actual, message, "{args:?}"),
            _ => panic!("expected invalid input for {args:?}"),
        }
    }
    assert!(server.await.unwrap()[0].starts_with("POST /v1/ideabucket/buckets/2026-11-02/process "));
}
