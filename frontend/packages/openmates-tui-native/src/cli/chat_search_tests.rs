// contract-test: supporting surface=cli assertions=chats.messages.client-encrypted
use super::*;
use futures_util::{SinkExt, StreamExt};
use tokio::io::{AsyncReadExt, AsyncWriteExt};
use tokio_tungstenite::tungstenite::Message as Frame;

fn invocation(args: &[&str]) -> Invocation {
    parse_from(args.iter().map(|a| a.to_string()))
        .unwrap_or_else(|error| panic!("{error}"))
        .invocation
        .expect("search invocation")
}
#[test]
fn parser_preserves_multiword_query_double_dash_and_shared_context_without_adding_limits() {
    let i = invocation(&[
        "openmates",
        "chats",
        "search",
        "résumé",
        "Madrid",
        "--team",
        "33333333-3333-4333-8333-333333333333",
        "--json",
    ]);
    assert_eq!(i.positionals, vec!["résumé", "Madrid"]);
    assert!(i.boolean("json"));
    assert!(requirements(&i).supported);
    assert!(requirements(&i).authenticated);
    let literal = invocation(&["openmates", "chats", "search", "--", "--literal"]);
    assert_eq!(literal.positionals, vec!["--literal"]);
    assert!(parse_from(["openmates", "chats", "search"]).is_err());
}
#[tokio::test]
async fn unsupported_flags_api_keys_and_invalid_queries_never_fall_back_to_cookie_transport() {
    for (args, unsupported) in [
        (
            vec![
                "openmates",
                "chats",
                "search",
                "needle",
                "--api-key",
                "synthetic-credential",
            ],
            true,
        ),
        (
            vec!["openmates", "chats", "search", "needle", "--limit", "1"],
            true,
        ),
        (
            vec!["openmates", "chats", "search", "needle", "--page", "2"],
            true,
        ),
        (vec!["openmates", "chats", "search", " "], false),
    ] {
        let i = invocation(&args);
        let mut client = Client::new("http://127.0.0.1:1", None).unwrap();
        let result = execute(&i, &mut client, CancellationToken::new()).await;
        assert!(if unsupported {
            matches!(result, Err(CliError::Unsupported { .. }))
        } else {
            matches!(result, Err(CliError::Invalid(_)))
        });
        assert!(client.session().is_none());
    }
}
#[tokio::test]
async fn cli_search_runs_real_shared_metadata_filter_and_returns_raw_script_array() {
    let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
    let api = format!("http://{}", listener.local_addr().unwrap());
    let id = "11111111-1111-4111-8111-111111111111";
    let row = json!({"id":id,"encrypted_chat_key":crate::crypto::encrypt_bytes(&[8;32],&[7;32]).unwrap(),
        "encrypted_title":crate::crypto::encrypt_combined("Madrid Rust fixture",&[8;32]).unwrap(),"last_edited_overall_timestamp":10});
    let server = tokio::spawn(async move {
        let (mut http, _) = listener.accept().await.unwrap();
        let mut data = vec![];
        let mut chunk = [0; 4096];
        loop {
            let n = http.read(&mut chunk).await.unwrap();
            assert!(n > 0);
            data.extend_from_slice(&chunk[..n]);
            if let Some(end) = data.windows(4).position(|v| v == b"\r\n\r\n") {
                let head = std::str::from_utf8(&data[..end]).unwrap();
                let length = head
                    .lines()
                    .find_map(|l| {
                        l.to_ascii_lowercase()
                            .strip_prefix("content-length:")
                            .map(|v| v.trim().parse::<usize>().unwrap())
                    })
                    .unwrap();
                if data.len() >= end + 4 + length {
                    assert!(head.starts_with("POST /v1/auth/session "));
                    break;
                }
            }
        }
        assert!(!String::from_utf8_lossy(&data).contains("mAdRiD"));
        let body = json!({"success":true,"ws_token":"token","user":{"id":"owner"}}).to_string();
        http.write_all(format!("HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: {}\r\nSet-Cookie: auth_refresh_token=rotated; HttpOnly\r\nConnection: close\r\n\r\n{body}",body.len()).as_bytes()).await.unwrap();
        drop(http);
        let (stream, _) = listener.accept().await.unwrap();
        let mut ws = tokio_tungstenite::accept_async(stream).await.unwrap();
        let lifecycle: Value =
            serde_json::from_str(ws.next().await.unwrap().unwrap().to_text().unwrap()).unwrap();
        assert_eq!(lifecycle["type"], "native_client_lifecycle");
        let sync: Value =
            serde_json::from_str(ws.next().await.unwrap().unwrap().to_text().unwrap()).unwrap();
        assert_eq!(sync["type"], "phased_sync_request");
        assert!(!sync.to_string().contains("mAdRiD"));
        for frame in [
            json!({"type":"phase_2_last_20_chats_ready","payload":{"chats":[{"chat_details":row}]}}),
            json!({"type":"phased_sync_complete","payload":{"phase":"all"}}),
            json!({"type":"recovery_outputs_discovery_complete","payload":{"status":"completed"}}),
        ] {
            ws.send(Frame::Text(frame.to_string().into()))
                .await
                .unwrap();
        }
        assert!(matches!(ws.next().await.unwrap().unwrap(), Frame::Close(_)));
    });
    let mut client = Client::new(
        &api,
        Some(openmates_sdk::Session {
            api_url: api.clone(),
            session_id: "fixture".into(),
            cookies: Default::default(),
            ws_token: None,
            master_key: zeroize::Zeroizing::new([7; 32]),
            hashed_email: "fixture".into(),
            user_email_salt: String::new(),
            email_encryption_key: None,
            created_at: 1,
            paired_session_expires_at: None,
            active_team_id: None,
        }),
    )
    .unwrap();
    let i = invocation(&["openmates", "chats", "search", "mAdRiD", "--json"]);
    let out = tokio::time::timeout(
        std::time::Duration::from_secs(5),
        execute(&i, &mut client, CancellationToken::new()),
    )
    .await
    .unwrap()
    .unwrap_or_else(|e| panic!("{e}"));
    let result: Value = serde_json::from_str(&out.stdout).unwrap();
    assert!(result.is_array());
    assert_eq!(result[0]["id"], id);
    assert_eq!(result[0]["title"], "Madrid Rust fixture");
    assert!(result[0]["summary"].is_null());
    assert_eq!(out.exit_code, 0);
    assert!(out.stderr.is_empty());
    assert!(
        !client
            .ciphertext_snapshot()
            .to_string()
            .contains("Madrid Rust fixture")
    );
    assert_eq!(
        client.session().unwrap().cookies["auth_refresh_token"],
        "rotated"
    );
    server.await.unwrap();
}
