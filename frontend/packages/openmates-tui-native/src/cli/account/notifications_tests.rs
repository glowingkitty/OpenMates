// contract-test: supporting surface=cli assertions=cli.surface.semantic-parity
use super::super::settings_more::tests::{mock, parsed};
use super::*;

#[tokio::test]
async fn newsletter_and_notification_reads_route_and_validate_like_npm() {
    for args in [
        vec!["openmates", "settings", "notifications", "status"],
        vec![
            "openmates",
            "settings",
            "notifications",
            "list",
            "--limit",
            "10",
        ],
        vec![
            "openmates",
            "settings",
            "notifications",
            "email",
            "set",
            "--ai-responses",
            "off",
        ],
        vec![
            "openmates",
            "settings",
            "notifications",
            "backup",
            "set",
            "--enabled",
            "on",
            "--interval",
            "30",
        ],
        vec![
            "openmates",
            "settings",
            "newsletter",
            "categories",
            "set",
            "--tips",
            "off",
        ],
        vec![
            "openmates",
            "settings",
            "newsletter",
            "subscribe",
            "me@example.org",
        ],
        vec!["openmates", "settings", "newsletter", "confirm", "tok"],
    ] {
        let invocation = parsed(&args);
        assert!(supported(&invocation), "{args:?}");
        assert!(
            super::super::super::handlers::requirements(&invocation).supported,
            "{args:?}"
        );
    }
    let (mut client, server) = mock(vec![json!({"items":[]}), json!({"success":true})]).await;
    execute(
        &parsed(&[
            "openmates",
            "settings",
            "notifications",
            "list",
            "--limit",
            "10",
            "--json",
        ]),
        &mut client,
    )
    .await
    .ok()
    .unwrap();
    let updated = execute(
        &parsed(&[
            "openmates",
            "settings",
            "newsletter",
            "categories",
            "set",
            "--tips",
            "off",
        ]),
        &mut client,
    )
    .await
    .ok()
    .unwrap();
    assert!(
        updated
            .stdout
            .starts_with("\x1b[32m✓\x1b[0m Settings updated\n")
    );
    for (args, message) in [
        (
            vec!["openmates", "settings", "notifications", "email", "set"],
            "Provide --enabled or at least one email category flag.",
        ),
        (
            vec![
                "openmates",
                "settings",
                "notifications",
                "email",
                "set",
                "--enabled",
                "maybe",
            ],
            "Invalid email notifications value 'maybe'. Use on/off or true/false.",
        ),
        (
            vec![
                "openmates",
                "settings",
                "notifications",
                "backup",
                "set",
                "--enabled",
                "on",
            ],
            "Missing --interval.",
        ),
        (
            vec!["openmates", "settings", "newsletter", "subscribe"],
            "Missing email. Example: openmates settings newsletter subscribe you@example.com",
        ),
    ] {
        match execute(&parsed(&args), &mut client).await {
            Err(CliError::Invalid(actual)) => assert_eq!(actual, message, "{args:?}"),
            _ => panic!("expected invalid input for {args:?}"),
        }
    }
    let requests = server.await.unwrap();
    assert!(requests[0].starts_with("GET /v1/notifications?limit=10 "));
    assert!(requests[1].ends_with(r#"{"categories":{"daily_inspirations":true,"tips_and_tricks":false,"updates_and_announcements":true}}"#));
}

#[tokio::test]
async fn newsletter_actions_run_signed_out_through_the_public_channel() {
    let (mut client, server) = mock(vec![json!({"success":true})]).await;
    let api = client.session().unwrap().api_url.clone();
    client = Client::new(&api, None).unwrap();
    let subscribe = parsed(&["openmates", "settings", "newsletter", "subscribe", "you@example.com", "--json"]);
    assert!(is_public(&subscribe) && super::super::super::docs::is_public(&subscribe));
    assert!(!is_public(&parsed(&["openmates", "settings", "newsletter", "categories"])));
    let output = execute(&subscribe, &mut client).await.ok().unwrap();
    assert_eq!(serde_json::from_str::<Value>(&output.stdout).unwrap()["success"], true);
    let request = &server.await.unwrap()[0];
    assert!(request.starts_with("POST /v1/newsletter/subscribe ") && !request.to_ascii_lowercase().contains("cookie:"));
}
