// contract-test: supporting surface=cli assertions=cli.surface.semantic-parity
use super::*;
use openmates_sdk::Session;
use std::collections::BTreeMap;
use tokio::io::{AsyncReadExt, AsyncWriteExt};

pub(in crate::cli::account) fn parsed(args: &[&str]) -> Invocation {
    super::super::super::parse_from(args.iter().copied())
        .unwrap_or_else(|e| panic!("{e}"))
        .invocation
        .unwrap()
}
/// Loopback HTTP double: never a real account. Answers in order and records.
pub(in crate::cli::account) async fn mock(
    responses: Vec<Value>,
) -> (Client, tokio::task::JoinHandle<Vec<String>>) {
    let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
    let api = format!("http://{}", listener.local_addr().unwrap());
    let handle = tokio::spawn(async move {
        let mut requests = vec![];
        for body in responses {
            let (mut socket, _) = listener.accept().await.unwrap();
            let mut buf = Vec::new();
            loop {
                let mut bytes = [0; 4096];
                let n = socket.read(&mut bytes).await.unwrap();
                assert!(n > 0);
                buf.extend_from_slice(&bytes[..n]);
                if let Some(end) = buf.windows(4).position(|w| w == b"\r\n\r\n") {
                    let head = String::from_utf8_lossy(&buf[..end]).to_ascii_lowercase();
                    let size = head
                        .lines()
                        .find_map(|l| {
                            l.strip_prefix("content-length:")
                                .and_then(|n| n.trim().parse::<usize>().ok())
                        })
                        .unwrap_or(0);
                    if buf.len() >= end + 4 + size {
                        break;
                    }
                }
            }
            requests.push(String::from_utf8(buf).unwrap());
            let body = body.to_string();
            socket.write_all(format!("HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: {}\r\nConnection: close\r\n\r\n{body}", body.len()).as_bytes()).await.unwrap();
        }
        requests
    });
    let session = Session {
        api_url: api.clone(),
        session_id: "synthetic-cli-settings".into(),
        cookies: BTreeMap::from([("auth_refresh_token".into(), "fixture".into())]),
        ws_token: None,
        master_key: zeroize::Zeroizing::new([7; 32]),
        hashed_email: "synthetic".into(),
        user_email_salt: "c2FsdA==".into(),
        email_encryption_key: Some("synthetic-email-key".into()),
        created_at: 0,
        paired_session_expires_at: None,
        active_team_id: None,
    };
    (Client::new(&api, Some(session)).unwrap(), handle)
}

#[test]
fn legacy_syntax_routes_every_ported_settings_command() {
    for args in [
        vec![
            "openmates",
            "settings",
            "reminders",
            "update",
            "rem-1",
            "--enabled",
            "false",
        ],
        vec![
            "openmates",
            "settings",
            "reminders",
            "delete",
            "rem-1",
            "--yes",
        ],
        vec!["openmates", "settings", "gift-card", "redeem", "CODE"],
        vec!["openmates", "settings", "gift-card", "list"],
        vec![
            "openmates",
            "settings",
            "billing",
            "gift-card",
            "redeem",
            "CODE",
        ],
        vec!["openmates", "settings", "billing", "gift-card", "list"],
        vec![
            "openmates",
            "settings",
            "billing",
            "invoices",
            "list",
            "--json",
        ],
        vec!["openmates", "settings", "billing", "bank-transfer", "list"],
        vec![
            "openmates",
            "settings",
            "account",
            "export",
            "status",
            "exp-1",
        ],
        vec!["openmates", "account", "export", "manifest"],
        vec![
            "openmates",
            "settings",
            "account",
            "export",
            "data",
            "exp-1",
        ],
        vec![
            "openmates",
            "settings",
            "account",
            "export",
            "cancel",
            "exp-1",
        ],
        vec!["openmates", "settings", "account", "delete", "preview"],
        vec![
            "openmates",
            "settings",
            "account",
            "storage",
            "delete",
            "file-1",
            "--yes",
        ],
        vec![
            "openmates",
            "account",
            "storage",
            "delete",
            "--all",
            "--yes",
        ],
    ] {
        let invocation = parsed(&args);
        assert!(supported(&invocation), "{args:?}");
        assert!(
            super::super::super::handlers::requirements(&invocation).supported,
            "{args:?}"
        );
    }
    assert!(answered_yes(" Y\n") && !answered_yes("yes\n") && !answered_yes(""));
}

#[tokio::test]
async fn reminder_update_matches_parse_data_or_flags_and_mutation_output() {
    let (mut client, server) =
        mock(vec![json!({"success":true,"reminder":{"enabled":false}})]).await;
    let output = execute(
        &parsed(&[
            "openmates",
            "settings",
            "reminders",
            "update",
            "rem-1",
            "--enabled",
            "off",
        ]),
        &mut client,
    )
    .await
    .ok()
    .unwrap();
    assert!(
        output
            .stdout
            .starts_with("\x1b[32m✓\x1b[0m Settings updated\n")
    );
    let requests = server.await.unwrap();
    assert!(requests[0].starts_with("PATCH /v1/settings/reminders/rem-1 "));
    assert!(requests[0].ends_with(r#"{"enabled":false}"#));
    let (mut client, _server) = mock(vec![]).await;
    for (args, message) in [
        (
            vec!["openmates", "settings", "reminders", "update", "rem-1"],
            "Provide --data '<json>' or a supported flag.",
        ),
        (
            vec![
                "openmates",
                "settings",
                "reminders",
                "update",
                "rem-1",
                "--enabled",
                "maybe",
            ],
            "Invalid enabled value 'maybe'. Use on/off or true/false.",
        ),
        (
            vec!["openmates", "settings", "reminders", "update"],
            "Missing reminder ID.",
        ),
        (
            vec!["openmates", "settings", "account", "export", "status"],
            "Missing export ID. Example: openmates settings account export status <export-id>",
        ),
        (
            vec![
                "openmates",
                "settings",
                "account",
                "storage",
                "delete",
                "--yes",
            ],
            "Missing file ID.",
        ),
    ] {
        match execute(&parsed(&args), &mut client).await {
            Err(CliError::Invalid(actual)) => assert_eq!(actual, message, "{args:?}"),
            _ => panic!("expected invalid input for {args:?}"),
        }
    }
}

#[tokio::test]
async fn gift_cards_billing_and_storage_delete_use_legacy_output() {
    let (mut client, server) = mock(vec![
        json!({"success":true,"credits_added":500,"current_credits":1200,"message":"ok"}),
        json!({"success":false,"credits_added":0,"current_credits":0,"message":"Code already used"}),
        json!({"invoices":[]}),
        json!({"success":true,"deleted":2}),
    ])
    .await;
    let ok = execute(
        &parsed(&["openmates", "settings", "gift-card", "redeem", "CODE"]),
        &mut client,
    )
    .await
    .ok()
    .unwrap();
    assert_eq!(
        ok.stdout,
        "\x1b[32m✓\x1b[0m Gift card redeemed! +500 credits\n  Balance: 1200 credits\n"
    );
    let failed = execute(
        &parsed(&[
            "openmates",
            "settings",
            "billing",
            "gift-card",
            "redeem",
            "CODE",
        ]),
        &mut client,
    )
    .await
    .ok()
    .unwrap();
    assert_eq!(
        (failed.stdout.as_str(), failed.exit_code),
        ("\x1b[31m✗\x1b[0m Code already used\n", 0)
    );
    let invoices = execute(
        &parsed(&[
            "openmates",
            "settings",
            "billing",
            "invoices",
            "list",
            "--json",
        ]),
        &mut client,
    )
    .await
    .ok()
    .unwrap();
    assert_eq!(
        serde_json::from_str::<Value>(&invoices.stdout).unwrap(),
        json!({"invoices":[]})
    );
    execute(
        &parsed(&[
            "openmates",
            "account",
            "storage",
            "delete",
            "--category",
            "images",
            "--yes",
        ]),
        &mut client,
    )
    .await
    .ok()
    .unwrap();
    let requests = server.await.unwrap();
    assert!(requests[0].starts_with("POST /v1/payments/redeem-gift-card "));
    assert!(requests[0].contains(r#""email_encryption_key":"synthetic-email-key""#));
    assert!(requests[2].starts_with("GET /v1/payments/invoices "));
    assert!(requests[3].starts_with("DELETE /v1/settings/storage/files "));
    assert!(
        requests[3].ends_with(r#"{"category":"images","scope":"category"}"#)
            || requests[3].ends_with(r#"{"scope":"category","category":"images"}"#)
    );
}

fn bare(path: &str) -> Invocation {
    Invocation {
        path: path.split(' ').map(str::to_owned).collect(),
        positionals: vec![],
        flags: BTreeMap::new(),
    }
}
#[test]
fn informational_settings_need_no_account_and_keep_top_level_commands() {
    for entry in super::super::INFO {
        let command = format!("settings {}", entry.0);
        let mut i = bare(&command);
        i.flags.insert("json".into(), json!(true));
        assert!(
            super::super::is_info(&i) && super::super::super::docs::is_public(&i),
            "{command}"
        );
        let output = super::super::web_only(&i, "https://app.example")
            .unwrap()
            .ok()
            .unwrap();
        let value: Value = serde_json::from_str(&output.stdout).unwrap();
        assert_eq!(value["supported_in_cli"], false);
        assert_eq!(value["web_url"].is_null(), entry.2.is_none(), "{command}");
    }
    let alias = bare("account email");
    assert!(super::super::is_info(&alias));
    for top_level in [vec!["support"], vec!["server"], vec!["security"]] {
        let i = bare(&top_level.join(" "));
        assert!(!super::super::is_info(&i), "{top_level:?}");
    }
}
