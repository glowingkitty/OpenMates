// contract-test: supporting surface=cli assertions=cli.surface.semantic-parity
use super::super::super::parity_test_support::{mock, parsed};
use super::*;

#[test]
fn routes_every_ported_command_and_nothing_else() {
    for args in [
        vec!["openmates", "settings", "mates", "list"],
        vec!["openmates", "settings", "mates", "info", "finance"],
        vec!["openmates", "settings", "mates", "consent", "--yes"],
        vec!["openmates", "settings", "report-issue", "create", "--title", "T", "--body", "B"],
        vec!["openmates", "settings", "report-issue", "status", "i-1"],
        vec!["openmates", "settings", "privacy", "auto-delete", "chats", "set", "90d"],
        vec!["openmates", "settings", "privacy", "debug-logs", "share", "--confirm"],
        vec!["openmates", "settings", "ai", "models", "set-defaults", "--simple", "auto"],
    ] {
        let invocation = parsed(&args);
        assert!(supported(&invocation), "{args:?}");
        assert!(super::super::super::handlers::requirements(&invocation).supported, "{args:?}");
    }
    assert!(!supported(&parsed(&["openmates", "settings", "billing", "overview"])));
}

#[tokio::test]
async fn mates_render_npm_text_and_json() {
    let (mut client, _server) = mock(vec![]).await;
    let out = execute(&parsed(&["openmates", "settings", "mates", "list"]), &mut client).await.ok().unwrap();
    assert!(out.stdout.starts_with("\x1b[1mMates\x1b[0m\n"));
    assert!(out.stdout.contains(&format!("{:<28} {:<10} @mate:finance", "finance", "Finn")));
    let out = execute(&parsed(&["openmates", "settings", "mates", "info", "finance", "--json"]), &mut client)
        .await
        .ok()
        .unwrap();
    assert_eq!(
        serde_json::from_str::<Value>(&out.stdout).unwrap(),
        json!({"id":"finance","name":"Finn","mention":"@mate:finance"})
    );
    let out = execute(&parsed(&["openmates", "settings", "mates", "info", "finance"]), &mut client)
        .await
        .ok()
        .unwrap();
    assert_eq!(
        out.stdout,
        "\x1b[1mFinn (finance)\x1b[0m\nMention: @mate:finance\nUse: openmates chats send \"@mate:finance <message>\"\n"
    );
    match execute(&parsed(&["openmates", "settings", "mates", "info", "nope"]), &mut client).await {
        Err(CliError::Invalid(m)) => assert_eq!(m, "Unknown mate 'nope'. Run 'openmates settings mates list'."),
        _ => panic!("expected unknown mate"),
    }
}

#[tokio::test]
async fn report_issue_and_defaults_post_the_npm_payloads() {
    let (mut client, server) = mock(vec![
        json!({"issue_id":"long-id","short_issue_id":"OM-7","message":"Thanks"}),
        json!({"success":true}),
        json!({"success":true}),
    ])
    .await;
    let out = execute(
        &parsed(&["openmates", "settings", "report-issue", "create", "--title", "T", "--body", "B"]),
        &mut client,
    )
    .await
    .ok()
    .unwrap();
    assert_eq!(
        out.stdout,
        "\x1b[32m✓\x1b[0m Issue reported\nIssue reference: OM-7\nInternal issue ID: long-id\nThanks\n"
    );
    execute(
        &parsed(&["openmates", "settings", "ai", "models", "set-defaults", "--simple", "auto", "--complex", "a/b", "--json"]),
        &mut client,
    )
    .await
    .ok()
    .unwrap();
    execute(
        &parsed(&["openmates", "settings", "privacy", "debug-logs", "share", "--confirm", "--duration", "2h", "--json"]),
        &mut client,
    )
    .await
    .ok()
    .unwrap();
    let requests = server.await.unwrap();
    assert!(requests[0].starts_with("POST /v1/settings/issues "));
    assert!(requests[1].contains(r#""default_ai_model_simple":null"#));
    assert!(requests[1].contains(r#""default_ai_model_complex":"a/b""#));
    assert!(requests[2].contains(r#""duration":"2h""#));
}

#[tokio::test]
async fn missing_arguments_use_npm_messages_before_network() {
    let (mut client, _server) = mock(vec![]).await;
    for (args, message) in [
        (vec!["openmates", "settings", "report-issue", "create", "--title", "T"], "Provide --title and --body."),
        (vec!["openmates", "settings", "report-issue", "status"], "Missing issue ID."),
    ] {
        match execute(&parsed(&args), &mut client).await {
            Err(CliError::Invalid(m)) => assert_eq!(m, message, "{args:?}"),
            _ => panic!("expected failure for {args:?}"),
        }
    }
    assert!(
        execute(&parsed(&["openmates", "settings", "ai", "models", "set-defaults"]), &mut client)
            .await
            .is_err()
    );
}
