// contract-test: supporting surface=cli assertions=chats.incognito.not-persisted,chats.messages.client-encrypted
use super::*;
use futures_util::{SinkExt, StreamExt};
use tokio::io::{AsyncReadExt, AsyncWriteExt};
use tokio_tungstenite::tungstenite::Message as Frame;

fn options() -> SendOptions {
    SendOptions {
        incognito: true,
        ..SendOptions::default()
    }
}
fn session(api: &str) -> Session {
    Session {
        api_url: api.into(),
        session_id: "explicit-session".into(),
        cookies: BTreeMap::from([("auth_refresh_token".into(), "private-cookie".into())]),
        ws_token: Some("private-token".into()),
        master_key: zeroize::Zeroizing::new([7; 32]),
        hashed_email: "owner".into(),
        user_email_salt: "salt".into(),
        email_encryption_key: None,
        created_at: 1,
        paired_session_expires_at: None,
        active_team_id: None,
    }
}
async fn read_http(stream: &mut tokio::net::TcpStream) -> (String, Value) {
    let mut bytes = vec![];
    let mut one = [0; 1024];
    let end = loop {
        let n = stream.read(&mut one).await.unwrap();
        assert!(n > 0);
        bytes.extend_from_slice(&one[..n]);
        if let Some(n) = bytes.windows(4).position(|v| v == b"\r\n\r\n") {
            break n + 4;
        }
    };
    let headers = String::from_utf8(bytes[..end].to_vec()).unwrap();
    let length = headers
        .lines()
        .find_map(|line| {
            line.to_ascii_lowercase()
                .strip_prefix("content-length:")
                .map(|v| v.trim().parse::<usize>().unwrap())
        })
        .unwrap_or(0);
    while bytes.len() < end + length {
        let n = stream.read(&mut one).await.unwrap();
        assert!(n > 0);
        bytes.extend_from_slice(&one[..n]);
    }
    let body = if length == 0 {
        Value::Null
    } else {
        serde_json::from_slice(&bytes[end..end + length]).unwrap()
    };
    (headers, body)
}
async fn response(stream: &mut tokio::net::TcpStream, status: &str, kind: &str, body: &str) {
    let header = format!(
        "HTTP/1.1 {status}\r\nContent-Type: {kind}\r\nContent-Length: {}\r\nConnection: close\r\n\r\n",
        body.len()
    );
    stream.write_all(header.as_bytes()).await.unwrap();
    stream.write_all(body.as_bytes()).await.unwrap();
}
async fn frame(
    ws: &mut tokio_tungstenite::WebSocketStream<tokio::net::TcpStream>,
    kind: &str,
    p: Value,
) {
    ws.send(Frame::Text(
        json!({"type":kind,"payload":p}).to_string().into(),
    ))
    .await
    .unwrap();
}
fn assert_no_account_headers(headers: &str) {
    let headers = headers.to_ascii_lowercase();
    for secret in [
        "\r\ncookie:",
        "\r\nauthorization:",
        "\r\norigin:",
        "\r\nx-openmates-device-id:",
    ] {
        assert!(!headers.contains(secret), "unexpected account header");
    }
    assert!(headers.contains("x-openmates-sdk: rust"));
    assert!(headers.contains("x-openmates-anonymous-id: anonymous-fixture"));
}
#[tokio::test]
#[allow(clippy::result_large_err)] // Upstream WebSocket handshake callback signature.
async fn cookie_volatile_stream_has_no_durable_frames_caches_or_drafts() {
    let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
    let api = format!("http://{}", listener.local_addr().unwrap());
    let server = tokio::spawn(async move {
        let (mut stream, _) = listener.accept().await.unwrap();
        let (head, body) = read_http(&mut stream).await;
        assert!(head.starts_with("POST /v1/auth/session "));
        assert_eq!(body["session_id"], "explicit-session");
        response(
            &mut stream,
            "200 OK",
            "application/json",
            r#"{"success":true,"ws_token":"fresh-token","user":{"id":"owner"}}"#,
        )
        .await;
        drop(stream);
        let (stream, _) = listener.accept().await.unwrap();
        let mut ws = tokio_tungstenite::accept_hdr_async(
            stream,
            |request: &tokio_tungstenite::tungstenite::handshake::server::Request,
             response: tokio_tungstenite::tungstenite::handshake::server::Response| {
                let uri = url::Url::parse(&format!("http://localhost{}", request.uri())).unwrap();
                assert_eq!(
                    uri.query_pairs()
                        .find(|(key, _)| key == "client_capabilities")
                        .unwrap()
                        .1,
                    ""
                );
                assert_eq!(request.headers()["x-openmates-sdk"], "rust");
                assert!(
                    request.headers()["cookie"]
                        .to_str()
                        .unwrap()
                        .contains("private-cookie")
                );
                Ok(response)
            },
        )
        .await
        .unwrap();
        let lifecycle: Value =
            serde_json::from_str(ws.next().await.unwrap().unwrap().to_text().unwrap()).unwrap();
        assert_eq!(lifecycle["type"], "native_client_lifecycle");
        assert_eq!(lifecycle["payload"]["is_foreground"], true);
        assert_eq!(lifecycle["payload"]["interactive"], false);
        let active: Value =
            serde_json::from_str(ws.next().await.unwrap().unwrap().to_text().unwrap()).unwrap();
        assert_eq!(active["type"], "set_active_chat");
        let turn: Value =
            serde_json::from_str(ws.next().await.unwrap().unwrap().to_text().unwrap()).unwrap();
        assert_eq!(turn["type"], "chat_message_added");
        let p = &turn["payload"];
        assert_eq!(p["is_incognito"], true);
        assert_eq!(p["client_capabilities"], json!([]));
        assert_eq!(p["message_history"], json!([p["message"]]));
        assert!(!turn.to_string().contains("alice@example.com"));
        for key in [
            "encrypted_chat_key",
            "recovery_public_key",
            "project_candidates",
            "personal_memories",
        ] {
            assert!(p.get(key).is_none());
        }
        let chat = p["chat_id"].clone();
        let user = p["message"]["message_id"].clone();
        frame(
            &mut ws,
            "ai_task_initiated",
            json!({"chat_id":chat,"user_message_id":user,"ai_task_id":"ai-task"}),
        )
        .await;
        // Exact authenticated typing wire intentionally has no task_id.
        frame(&mut ws,"ai_typing_started",json!({"chat_id":chat,"user_message_id":user,"message_id":"ai-task","category":"general_knowledge"})).await;
        frame(&mut ws,"ai_message_update",json!({"chat_id":"foreign","user_message_id":user,"task_id":"ai-task","message_id":"ai-task","full_content_so_far":"foreign","is_final_chunk":true})).await;
        frame(
            &mut ws,
            "thinking_chunk",
            json!({"chat_id":chat,"task_id":"ai-task","message_id":"ai-task","content":"Thinking"}),
        )
        .await;
        frame(&mut ws,"ai_message_update",json!({"chat_id":chat,"user_message_id":user,"task_id":"ai-task","message_id":"ai-task","full_content_so_far":p["message"]["content"],"is_final_chunk":true,"model_name":"observed-model"})).await;
        while let Some(next) = ws.next().await {
            match next.unwrap() {
                Frame::Close(_) => break,
                Frame::Ping(_) => {}
                other => panic!("unexpected post-stream persistence frame {other:?}"),
            }
        }
    });
    let mut client = Client::new(&api, Some(session(&api))).unwrap();
    let (updates, mut receiver) = mpsc::channel(32);
    let out = client
        .send(
            None,
            "Reply to alice@example.com",
            options(),
            updates,
            CancellationToken::new(),
        )
        .await
        .unwrap();
    assert_eq!(out.assistant, "Reply to alice@example.com");
    assert_eq!(out.chat.messages[1].thinking, "Thinking");
    assert_eq!(out.model_name.as_deref(), Some("observed-model"));
    assert!(out.pending_task_update_jobs.is_empty());
    assert!(client.is_ephemeral_chat(&out.chat_id));
    assert!(
        client.chats.is_empty()
            && client.history.is_empty()
            && client.embeds.is_empty()
            && client.embed_keys.is_empty()
            && client.wrappers.is_empty()
    );
    assert!(client.active_chat.is_none());
    assert!(matches!(
        client.save_draft(Some(&out.chat_id), "do not save").await,
        Err(Error::Invalid(_))
    ));
    assert!(matches!(
        client.open_chat(&out.chat_id).await,
        Err(Error::Invalid(_))
    ));
    assert!(matches!(
        client
            .mutate(Mutation::Delete {
                workspace: Workspace::Chats,
                id: out.chat_id.clone()
            })
            .await,
        Err(Error::Invalid(_))
    ));
    let (tx, _) = mpsc::channel(2);
    assert!(matches!(
        client
            .send(
                Some(&out.chat_id),
                "do not save",
                SendOptions::default(),
                tx,
                CancellationToken::new()
            )
            .await,
        Err(Error::Invalid(_))
    ));
    let snapshot = serde_json::to_string(&client.credential_snapshot().unwrap().session).unwrap();
    assert!(!snapshot.contains("alice@example.com"));
    assert!(!snapshot.contains(&out.chat_id));
    let mut admitted = false;
    while let Ok(update) = receiver.try_recv() {
        admitted |= matches!(update, StreamUpdate::Admitted { .. });
    }
    assert!(!admitted);
    server.await.unwrap();
}

#[tokio::test]
async fn explicit_anonymous_sse_strips_existing_cookie_and_restores_local_privacy() {
    let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
    let api = format!("http://{}", listener.local_addr().unwrap());
    let server = tokio::spawn(async move {
        let (mut stream, _) = listener.accept().await.unwrap();
        let (head, _) = read_http(&mut stream).await;
        assert!(head.starts_with("GET /v1/anonymous/free-usage/status "));
        assert_no_account_headers(&head);
        response(
            &mut stream,
            "200 OK",
            "application/json",
            r#"{"active":true,"can_send_text":true}"#,
        )
        .await;
        drop(stream);
        let (mut stream, _) = listener.accept().await.unwrap();
        let (head, body) = read_http(&mut stream).await;
        assert_no_account_headers(&head);
        assert!(head.starts_with("POST /v1/anonymous/chat/stream "));
        assert_eq!(body["anonymous_id"], "anonymous-fixture");
        assert_eq!(body["message_history"], json!([]));
        assert!(!body.to_string().contains("alice@example.com"));
        for key in [
            "task_update_jobs",
            "model",
            "provider",
            "encrypted_chat_key",
        ] {
            assert!(body.get(key).is_none());
        }
        let chat = &body["client_chat_id"];
        let user = &body["client_message_id"];
        let events = vec![
            json!({"type":"ai_task_initiated","chat_id":chat,"user_message_id":user,"ai_task_id":"task"}),
            json!({"type":"ai_typing_started","chat_id":chat,"user_message_id":user,"task_id":"task","message_id":"answer"}),
            json!({"type":"ai_message_chunk","chat_id":chat,"user_message_id":user,"task_id":"task","message_id":"answer","sequence":1,"full_content_so_far":body["plaintext_message"],"is_final_chunk":true}),
            json!({"type":"ai_task_ended","chatId":chat,"taskId":"task","status":"completed"}),
            json!({"type":"post_processing_completed","chat_id":chat,"task_id":"task","follow_up_request_suggestions":["Next question"]}),
        ];
        let data = events
            .into_iter()
            .map(|v| format!("data: {v}\r\n\r\n"))
            .collect::<String>();
        response(
            &mut stream,
            "200 OK",
            "text/event-stream; charset=utf-8",
            &data,
        )
        .await;
    });
    let mut client = Client::new(&api, Some(session(&api))).unwrap();
    let revision = client.credential_revision;
    let (tx, _) = mpsc::channel(32);
    let result = client
        .send_anonymous(
            "anonymous-fixture",
            "Reply to alice@example.com",
            SendOptions::default(),
            tx,
            CancellationToken::new(),
        )
        .await
        .unwrap();
    assert_eq!(result.assistant, "Reply to alice@example.com");
    assert_eq!(result.follow_up_suggestions, vec!["Next question"]);
    assert!(result.chat_id.starts_with("anonymous-"));
    assert!(client.is_ephemeral_chat(&result.chat_id));
    assert_eq!(client.credential_revision, revision);
    assert!(client.chats.is_empty() && client.history.is_empty());
    assert_eq!(
        client.session().unwrap().cookies["auth_refresh_token"],
        "private-cookie"
    );
    server.await.unwrap();
}

#[tokio::test]
async fn denied_budget_never_dispatches_inference_and_redirect_never_attaches_credentials() {
    for status in ["429 Too Many Requests", "302 Found"] {
        let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
        let api = format!("http://{}", listener.local_addr().unwrap());
        let server = tokio::spawn(async move {
            let (mut stream, _) = listener.accept().await.unwrap();
            let (head, _) = read_http(&mut stream).await;
            assert_no_account_headers(&head);
            response(
                &mut stream,
                status,
                "application/json",
                r#"{"private":"never echo"}"#,
            )
            .await;
            assert!(
                tokio::time::timeout(Duration::from_millis(40), listener.accept())
                    .await
                    .is_err()
            );
        });
        let mut client = Client::new(&api, None).unwrap();
        let (tx, _) = mpsc::channel(8);
        let error = client
            .send_anonymous(
                "anonymous-fixture",
                "Hello",
                options(),
                tx,
                CancellationToken::new(),
            )
            .await
            .err()
            .unwrap();
        assert_eq!(
            error,
            if status.starts_with("429") {
                Error::SignupRequired
            } else {
                Error::Forbidden
            }
        );
        assert!(!error.to_string().contains("never echo"));
        server.await.unwrap();
    }
}

#[tokio::test]
async fn preflight_fails_closed_without_auth_fallback_or_private_disclosure() {
    let mut client = Client::new("http://127.0.0.1:1", None).unwrap();
    let large = "x".repeat(20_001);
    let literal = SendOptions {
        pii_detection: false,
        ..options()
    };
    assert!(client.ephemeral_preflight(&large, &literal, false).is_ok());
    assert!(matches!(
        client.ephemeral_preflight(&large, &literal, true),
        Err(Error::Invalid(_))
    ));
    let (tx, _) = mpsc::channel(8);
    assert!(matches!(
        client
            .send(None, "hello", options(), tx, CancellationToken::new())
            .await,
        Err(Error::Authentication)
    ));
    let (tx, _) = mpsc::channel(8);
    assert!(matches!(
        client
            .send_anonymous(
                "unsafe\r\nCookie: secret",
                "hello",
                options(),
                tx,
                CancellationToken::new()
            )
            .await,
        Err(Error::Invalid(_))
    ));
    client.options.privacy.enhanced = true;
    let (tx, _) = mpsc::channel(8);
    assert!(matches!(
        client
            .send_anonymous(
                "anonymous-fixture",
                "hello",
                SendOptions {
                    pii_detection: false,
                    ..options()
                },
                tx,
                CancellationToken::new()
            )
            .await,
        Err(Error::Invalid(_))
    ));
    client.options.privacy.enhanced = false;
    let cancel = CancellationToken::new();
    cancel.cancel();
    let (tx, _) = mpsc::channel(8);
    assert_eq!(
        client
            .send_anonymous("anonymous-fixture", "hello", options(), tx, cancel)
            .await
            .err(),
        Some(Error::Cancelled)
    );
    let (tx, _) = mpsc::channel(8);
    assert!(matches!(
        client
            .send(
                None,
                "hello",
                SendOptions {
                    slug: Some("saved".into()),
                    ..options()
                },
                tx,
                CancellationToken::new()
            )
            .await,
        Err(Error::Invalid(_))
    ));
    let (tx, _) = mpsc::channel(8);
    assert!(matches!(
        client
            .send_anonymous(
                "anonymous-fixture",
                "hello",
                SendOptions {
                    memory_consent: SendConsentPolicy::ApproveRequested,
                    ..options()
                },
                tx,
                CancellationToken::new()
            )
            .await,
        Err(Error::Invalid(_))
    ));
    client.ephemeral_chats.insert("volatile-id".into());
    client.reset("http://127.0.0.1:1", None).unwrap();
    assert!(client.is_ephemeral_chat("volatile-id"));
}

#[tokio::test]
async fn volatile_cancel_and_sensitive_error_close_socket_without_saved_writes() {
    for refusal in [false, true] {
        let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
        let api = format!("http://{}", listener.local_addr().unwrap());
        let server = tokio::spawn(async move {
            let (mut http, _) = listener.accept().await.unwrap();
            read_http(&mut http).await;
            response(
                &mut http,
                "200 OK",
                "application/json",
                r#"{"success":true,"ws_token":"fresh-token","user":{"id":"owner"}}"#,
            )
            .await;
            drop(http);
            let (stream, _) = listener.accept().await.unwrap();
            let mut ws = tokio_tungstenite::accept_async(stream).await.unwrap();
            let _lifecycle = ws.next().await.unwrap().unwrap();
            let _active = ws.next().await.unwrap().unwrap();
            let turn: Value =
                serde_json::from_str(ws.next().await.unwrap().unwrap().to_text().unwrap()).unwrap();
            assert_eq!(turn["type"], "chat_message_added");
            let p = &turn["payload"];
            let chat = &p["chat_id"];
            let user = &p["message"]["message_id"];
            frame(
                &mut ws,
                "ai_task_initiated",
                json!({"chat_id":chat,"user_message_id":user,"ai_task_id":"task"}),
            )
            .await;
            if refusal {
                frame(&mut ws,"request_app_settings_memories",json!({"chat_id":chat,"message_id":user,"request_id":"private-request","requested_categories":["personal_data"]})).await;
            } else {
                frame(
                    &mut ws,
                    "ai_typing_started",
                    json!({"chat_id":chat,"user_message_id":user,"message_id":"task"}),
                )
                .await;
                frame(&mut ws,"ai_message_update",json!({"chat_id":chat,"user_message_id":user,"message_id":"task","task_id":"task","full_content_so_far":"partial","is_final_chunk":false})).await;
                let cancel: Value =
                    serde_json::from_str(ws.next().await.unwrap().unwrap().to_text().unwrap())
                        .unwrap();
                assert_eq!(cancel["type"], "cancel_ai_task");
                assert_eq!(cancel["payload"]["task_id"], "task");
                assert_eq!(cancel["payload"]["chat_id"], *chat);
            }
            assert!(matches!(ws.next().await.unwrap().unwrap(), Frame::Close(_)));
        });
        let mut client = Client::new(&api, Some(session(&api))).unwrap();
        let cancel = CancellationToken::new();
        let trigger = cancel.clone();
        let (tx, mut rx) = mpsc::channel(32);
        let watcher = tokio::spawn(async move {
            while let Some(update) = rx.recv().await {
                if matches!(update, StreamUpdate::Content { .. }) {
                    trigger.cancel();
                    break;
                }
            }
        });
        let result = client.send(None, "private", options(), tx, cancel).await;
        assert_eq!(
            result.err(),
            Some(if refusal {
                Error::Protocol
            } else {
                Error::Cancelled
            })
        );
        watcher.await.unwrap();
        server.await.unwrap();
        assert!(client.chats.is_empty() && client.history.is_empty());
    }
}

#[test]
fn reducer_refuses_wrong_task_sensitive_requests_failure_and_duplicate_sequence() {
    let (tx, _) = mpsc::channel(32);
    let mut stream = VolatileStream::new("chat", "user", "private", &[]);
    stream
        .accept(
            "ai_task_initiated",
            &json!({"chat_id":"chat","user_message_id":"user","ai_task_id":"task"}),
            true,
            &tx,
        )
        .unwrap();
    stream.accept("ai_message_chunk",&json!({"chat_id":"chat","user_message_id":"other","task_id":"task","message_id":"wrong","is_final_chunk":true}),true,&tx).unwrap();
    assert!(!stream.final_chunk);
    let frame = json!({"chat_id":"chat","user_message_id":"user","task_id":"task","message_id":"answer","sequence":1,"full_content_so_far":"hello"});
    stream
        .accept("ai_message_chunk", &frame, true, &tx)
        .unwrap();
    assert_eq!(
        stream.accept("ai_message_chunk", &frame, true, &tx),
        Err(Error::Protocol)
    );
    assert_eq!(
        stream.accept(
            "request_app_settings_memories",
            &json!({"chat_id":"chat","message_id":"user"}),
            false,
            &tx
        ),
        Err(Error::Protocol)
    );
    assert_eq!(stream.accept("ai_message_chunk",&json!({"chat_id":"chat","task_id":"task","message_id":"answer","sequence":2,"signup_required":true}),true,&tx),Err(Error::SignupRequired));
    assert_eq!(
        stream.accept(
            "ai_task_ended",
            &json!({"chatId":"chat","taskId":"task","status":"completed"}),
            true,
            &tx
        ),
        Err(Error::Protocol)
    );
}
#[test]
fn sse_handles_fragmented_unicode_multiline_comments_and_bounds() {
    let mut sse = Sse::default();
    let encoded = "data: {\"text\":\"é\"}\r\n\r\n: ping\n\ndata: one\ndata: two\n\n".as_bytes();
    let mut frames = vec![];
    for byte in encoded {
        frames.extend(sse.push(&[*byte]).unwrap());
    }
    assert_eq!(
        frames,
        vec!["{\"text\":\"é\"}".as_bytes().to_vec(), b"one\ntwo".to_vec()]
    );
    assert!(sse.pending.is_empty());
    assert!(Sse::default().push(&vec![b'x'; MAX_EVENT + 1]).is_err());
}
