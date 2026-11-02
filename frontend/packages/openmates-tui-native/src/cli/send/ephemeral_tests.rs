// contract-test: supporting surface=cli assertions=chats.incognito.not-persisted,chats.messages.client-encrypted
use super::*;
use serde_json::{Value, json};
use tokio::io::{AsyncReadExt, AsyncWriteExt};

fn invocation(args: &[&str]) -> Invocation {
    super::super::parse_from(args.iter().copied())
        .unwrap_or_else(|e| panic!("{e}"))
        .invocation
        .unwrap()
}
async fn read_http(stream: &mut tokio::net::TcpStream) -> (String, Value) {
    let mut bytes = vec![];
    let mut part = [0; 2048];
    let end = loop {
        let n = stream.read(&mut part).await.unwrap();
        assert!(n > 0);
        bytes.extend_from_slice(&part[..n]);
        if let Some(end) = bytes.windows(4).position(|v| v == b"\r\n\r\n") {
            break end + 4;
        }
    };
    let head = String::from_utf8(bytes[..end].to_vec()).unwrap();
    let length = head
        .lines()
        .filter_map(|line| line.split_once(':'))
        .find(|(key, _)| key.eq_ignore_ascii_case("content-length"))
        .map(|(_, value)| value.trim().parse::<usize>().unwrap())
        .unwrap_or(0);
    while bytes.len() < end + length {
        let n = stream.read(&mut part).await.unwrap();
        assert!(n > 0);
        bytes.extend_from_slice(&part[..n]);
    }
    let body = if length == 0 {
        Value::Null
    } else {
        serde_json::from_slice(&bytes[end..end + length]).unwrap()
    };
    (head, body)
}
async fn response(stream: &mut tokio::net::TcpStream, kind: &str, body: &str) {
    stream.write_all(format!("HTTP/1.1 200 OK\r\nContent-Type: {kind}\r\nContent-Length: {}\r\nConnection: close\r\n\r\n{body}",body.len()).as_bytes()).await.unwrap();
}
fn session(api: &str) -> openmates_sdk::Session {
    openmates_sdk::Session {
        api_url: api.into(),
        session_id: "explicit-cookie".into(),
        cookies: Default::default(),
        ws_token: None,
        master_key: Zeroizing::new([7; 32]),
        hashed_email: "synthetic-owner".into(),
        user_email_salt: String::new(),
        email_encryption_key: None,
        created_at: 1,
        paired_session_expires_at: None,
        active_team_id: None,
    }
}
#[tokio::test]
async fn anonymous_aliases_stream_safe_text_or_one_json_result_without_saved_state() {
    for (command, json_output) in [("new", false), ("send", true), ("incognito", true)] {
        let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
        let api = format!("http://{}", listener.local_addr().unwrap());
        let server = tokio::spawn(async move {
            let (mut socket, _) = listener.accept().await.unwrap();
            let (head, _) = read_http(&mut socket).await;
            assert!(head.starts_with("GET /v1/anonymous/free-usage/status "));
            assert_public_headers(&head);
            response(
                &mut socket,
                "application/json",
                r#"{"active":true,"can_send_text":true}"#,
            )
            .await;
            drop(socket);
            let (mut socket, _) = listener.accept().await.unwrap();
            let (head, body) = read_http(&mut socket).await;
            assert!(head.starts_with("POST /v1/anonymous/chat/stream "));
            assert_public_headers(&head);
            assert_eq!(body["message_history"], json!([]));
            assert_eq!(body["plaintext_message"], "synthetic question");
            for key in [
                "model",
                "provider",
                "task_update_jobs",
                "encrypted_chat_key",
            ] {
                assert!(body.get(key).is_none());
            }
            let chat = &body["client_chat_id"];
            let user = &body["client_message_id"];
            let data = [
                json!({"type":"ai_task_initiated","chat_id":chat,"user_message_id":user,"ai_task_id":"task"}),
                json!({"type":"ai_message_chunk","chat_id":chat,"user_message_id":user,"task_id":"task","message_id":"answer","sequence":1,"full_content_so_far":"Hello 界","is_final_chunk":false}),
                json!({"type":"ai_message_chunk","chat_id":chat,"user_message_id":user,"task_id":"task","message_id":"answer","sequence":2,"full_content_so_far":"Hello 界\u{1b}[31m!","is_final_chunk":true,"model_name":"observed-model"}),
                json!({"type":"ai_task_ended","chatId":chat,"taskId":"task","status":"completed"}),
            ].into_iter().map(|event| format!("data: {event}\n\n")).collect::<String>();
            response(&mut socket, "text/event-stream", &data).await;
        });
        let mut args = vec!["openmates", "chats", command, "synthetic question"];
        if json_output {
            args.push("--json");
        }
        let inv = invocation(&args);
        let mut client = Client::new(&api, None).unwrap();
        let mut out = vec![];
        let mut err = vec![];
        let result = tokio::time::timeout(
            std::time::Duration::from_secs(5),
            send_with_writers_mode(
                &inv,
                &mut client,
                Some("anonymous-fixture"),
                CancellationToken::new(),
                &mut out,
                &mut err,
            ),
        )
        .await
        .unwrap()
        .unwrap_or_else(|e| panic!("{e}"));
        if json_output {
            assert!(out.is_empty());
            let result: Value = serde_json::from_str(&result.stdout).unwrap();
            assert_eq!(result["status"], "completed");
            assert_eq!(result["assistant"], "Hello 界\u{1b}[31m!");
            assert!(result["chatId"].as_str().unwrap().starts_with("anonymous-"));
            assert_eq!(result["taskEvents"], json!([]));
            assert_eq!(result["pendingTaskUpdateJobs"], json!([]));
        } else {
            assert_eq!(String::from_utf8(out).unwrap(), "Hello 界\\u001b[31m!");
            assert!(result.stdout.contains("Chat (not stored): anonymous-"));
        }
        assert!(client.session().is_none());
        server.await.unwrap();
    }
}
fn assert_public_headers(head: &str) {
    let head = head.to_ascii_lowercase();
    assert!(head.contains("x-openmates-anonymous-id: anonymous-fixture"));
    for key in [
        "\r\ncookie:",
        "\r\nauthorization:",
        "\r\norigin:",
        "\r\nx-openmates-device-id:",
    ] {
        assert!(!head.contains(key));
    }
}
#[tokio::test]
async fn cookie_incognito_aliases_dispatch_volatile_frames_and_close_without_saved_state() {
    use futures_util::{SinkExt, StreamExt};
    use tokio_tungstenite::tungstenite::{
        Message,
        handshake::server::{Callback, ErrorResponse, Request, Response},
    };
    struct VolatileHandshake;
    impl Callback for VolatileHandshake {
        fn on_request(
            self,
            request: &Request,
            response: Response,
        ) -> Result<Response, ErrorResponse> {
            let url = url::Url::parse(&format!("http://synthetic{}", request.uri())).unwrap();
            assert_eq!(
                url.query_pairs()
                    .find(|(key, _)| key == "client_capabilities")
                    .unwrap()
                    .1,
                ""
            );
            Ok(response)
        }
    }
    for explicit_flag in [false, true] {
        let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
        let api = format!("http://{}", listener.local_addr().unwrap());
        let server = tokio::spawn(async move {
            let (mut socket, _) = listener.accept().await.unwrap();
            let (head, body) = read_http(&mut socket).await;
            assert!(head.starts_with("POST /v1/auth/session "));
            assert_eq!(body["session_id"], "explicit-cookie");
            response(
                &mut socket,
                "application/json",
                r#"{"success":true,"ws_token":"fresh","user":{"id":"synthetic-owner"}}"#,
            )
            .await;
            drop(socket);
            let (socket, _) = listener.accept().await.unwrap();
            let mut ws = tokio_tungstenite::accept_hdr_async(socket, VolatileHandshake)
                .await
                .unwrap();
            for expected in ["native_client_lifecycle", "set_active_chat"] {
                let frame: Value =
                    serde_json::from_str(ws.next().await.unwrap().unwrap().to_text().unwrap())
                        .unwrap();
                assert_eq!(frame["type"], expected);
            }
            let turn: Value =
                serde_json::from_str(ws.next().await.unwrap().unwrap().to_text().unwrap()).unwrap();
            assert_eq!(turn["type"], "chat_message_added");
            let p = &turn["payload"];
            assert_eq!(p["is_incognito"], true);
            assert_eq!(p["client_capabilities"], json!([]));
            assert_eq!(p["message_history"], json!([p["message"]]));
            for key in [
                "encrypted_chat_key",
                "recovery_public_key",
                "personal_memories",
                "project_candidates",
            ] {
                assert!(p.get(key).is_none());
            }
            for (kind, payload) in [
                (
                    "ai_task_initiated",
                    json!({"chat_id":p["chat_id"],"user_message_id":p["message"]["message_id"],"ai_task_id":"answer"}),
                ),
                (
                    "ai_message_update",
                    json!({"chat_id":p["chat_id"],"user_message_id":p["message"]["message_id"],"task_id":"answer","message_id":"answer","full_content_so_far":"Volatile response","is_final_chunk":true}),
                ),
            ] {
                ws.send(Message::Text(
                    json!({"type":kind,"payload":payload}).to_string().into(),
                ))
                .await
                .unwrap();
            }
            while let Some(next) = ws.next().await {
                match next.unwrap() {
                    Message::Close(_) => break,
                    Message::Ping(_) => {}
                    other => panic!("unexpected persistence frame {other:?}"),
                }
            }
        });
        let mut args = vec![
            "openmates",
            "chats",
            if explicit_flag { "send" } else { "incognito" },
            "synthetic question",
            "--json",
        ];
        if explicit_flag {
            args.push("--incognito");
        }
        let inv = invocation(&args);
        let mut client = Client::new(&api, Some(session(&api))).unwrap();
        let mut out = vec![];
        let result = tokio::time::timeout(
            std::time::Duration::from_secs(5),
            send_with_writers(
                &inv,
                &mut client,
                CancellationToken::new(),
                &mut out,
                &mut vec![],
            ),
        )
        .await
        .unwrap()
        .unwrap_or_else(|e| panic!("{e}"));
        let result: Value = serde_json::from_str(&result.stdout).unwrap();
        assert_eq!(result["assistant"], "Volatile response");
        assert_eq!(result["taskEvents"], json!([]));
        assert_eq!(result["pendingTaskUpdateJobs"], json!([]));
        assert!(out.is_empty());
        assert!(client.is_ephemeral_chat(result["chatId"].as_str().unwrap()));
        server.await.unwrap();
    }
}
#[tokio::test]
async fn ephemeral_unsupported_options_and_cookie_downgrades_fail_before_transport() {
    for flags in [
        vec!["--chat", "saved"],
        vec!["--slug", "saved"],
        vec!["--auto-approve"],
        vec!["--auto-approve-memories"],
        vec!["--project", "project"],
    ] {
        let mut args = vec!["openmates", "chats", "send", "hello"];
        args.extend(flags);
        let inv = invocation(&args);
        let mut client = Client::new("http://127.0.0.1:1", None).unwrap();
        let result = send_with_writers_mode(
            &inv,
            &mut client,
            Some("anonymous-fixture"),
            CancellationToken::new(),
            &mut vec![],
            &mut vec![],
        )
        .await;
        assert!(matches!(result, Err(CliError::Unsupported { .. })));
    }
    let api = "http://127.0.0.1:1";
    let mut client = Client::new(api, Some(session(api))).unwrap();
    let inv = invocation(&["openmates", "chats", "send", "hello"]);
    assert!(matches!(
        send_with_writers_mode(
            &inv,
            &mut client,
            Some("anonymous-fixture"),
            CancellationToken::new(),
            &mut vec![],
            &mut vec![]
        )
        .await,
        Err(CliError::Client(Error::Authentication))
    ));
    let mut client = Client::new(api, None).unwrap();
    let inv = invocation(&["openmates", "chats", "incognito", "hello"]);
    assert!(matches!(
        send_with_writers(
            &inv,
            &mut client,
            CancellationToken::new(),
            &mut vec![],
            &mut vec![]
        )
        .await,
        Err(CliError::Client(Error::Authentication))
    ));
}
#[test]
fn dispatched_volatile_cancellation_never_becomes_saved_history_recovery() {
    let mut state = Presentation {
        ephemeral: true,
        ..Default::default()
    };
    let (consent, _) = mpsc::unbounded_channel();
    state.event(
        StreamUpdate::Submitted {
            chat_id: "volatile".into(),
            message_id: "human".into(),
        },
        true,
        &mut vec![],
        &mut vec![],
        &consent,
    );
    let error = state.failure(Error::Cancelled);
    assert!(matches!(error, CliError::Client(Error::Cancelled)));
    assert_eq!(error.exit_code(), 130);
    assert!(!error.to_string().contains("history"));
}
