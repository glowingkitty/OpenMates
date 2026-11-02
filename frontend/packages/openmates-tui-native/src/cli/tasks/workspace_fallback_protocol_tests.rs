//! Actual CLI entrypoints and SDK transport against a bounded synthetic peer.
//! No product backend, provider, model selection or actual AI is used.
use super::*;
use futures_util::{SinkExt, StreamExt};
use std::{
    future::Future,
    sync::{
        Arc,
        atomic::{AtomicBool, Ordering},
    },
    time::Duration,
};
use tokio::{
    io::{AsyncReadExt, AsyncWriteExt},
    net::{TcpListener, TcpStream},
};
use tokio_tungstenite::{
    WebSocketStream,
    tungstenite::{
        Message,
        handshake::server::{ErrorResponse, Request, Response},
    },
};
const OWNER: &str = "11111111-1111-4111-8111-111111111111";
const EMAIL: &str = "user@example.test";
async fn bounded<T>(future: impl Future<Output = T>) -> T {
    tokio::time::timeout(Duration::from_secs(2), future)
        .await
        .expect("bounded synthetic operation")
}
async fn suite(future: impl Future<Output = ()>) {
    tokio::time::timeout(Duration::from_secs(10), future)
        .await
        .expect("bounded workspace fallback suite");
}
struct Peer(tokio::task::JoinHandle<()>);
impl Drop for Peer {
    fn drop(&mut self) {
        self.0.abort();
    }
}
impl Peer {
    async fn join(mut self) {
        bounded(&mut self.0)
            .await
            .expect("synthetic peer assertions");
    }
}
async fn http(socket: &mut TcpStream) -> (String, Value) {
    let mut bytes = vec![];
    let mut part = [0; 4096];
    let (end, length) = loop {
        let count = bounded(socket.read(&mut part)).await.unwrap();
        assert!(count > 0);
        bytes.extend_from_slice(&part[..count]);
        assert!(bytes.len() < 131072);
        if let Some(end) = bytes.windows(4).position(|bytes| bytes == b"\r\n\r\n") {
            let header = std::str::from_utf8(&bytes[..end]).unwrap();
            let length = header
                .lines()
                .filter_map(|line| line.split_once(':'))
                .find(|(name, _)| name.eq_ignore_ascii_case("content-length"))
                .map(|(_, value)| value.trim().parse::<usize>().unwrap())
                .unwrap_or(0);
            break (end + 4, length);
        }
    };
    while bytes.len() < end + length {
        let count = bounded(socket.read(&mut part)).await.unwrap();
        assert!(count > 0);
        bytes.extend_from_slice(&part[..count]);
        assert!(bytes.len() < 131072);
    }
    let body = if length == 0 {
        Value::Null
    } else {
        serde_json::from_slice(&bytes[end..end + length]).unwrap()
    };
    (String::from_utf8(bytes[..end].to_vec()).unwrap(), body)
}
async fn respond(socket: &mut TcpStream, value: Value) {
    let body = value.to_string();
    bounded(socket.write_all(format!("HTTP/1.1 200 OK\r\ncontent-type: application/json\r\nconnection: close\r\ncontent-length: {}\r\n\r\n{body}",body.len()).as_bytes())).await.unwrap();
}
async fn frame(ws: &mut WebSocketStream<TcpStream>) -> Value {
    let message = bounded(ws.next()).await.expect("frame before EOF").unwrap();
    serde_json::from_str(message.to_text().unwrap()).unwrap()
}
async fn send(ws: &mut WebSocketStream<TcpStream>, kind: &str, payload: Value) {
    bounded(ws.send(Message::Text(
        json!({"type":kind,"payload":payload}).to_string().into(),
    )))
    .await
    .unwrap();
}
// tungstenite requires this concrete HTTP response error in its callback.
#[allow(clippy::result_large_err)]
fn handshake(request: &Request, response: Response) -> Result<Response, ErrorResponse> {
    let url = url::Url::parse(&format!("http://fixture{}", request.uri())).unwrap();
    assert_eq!(url.path(), "/v1/ws");
    let query: std::collections::BTreeMap<_, _> = url.query_pairs().into_owned().collect();
    assert_eq!(query["token"], "fixture-token");
    assert!(
        !query["client_capabilities"]
            .split(',')
            .any(|capability| capability == "task_update_jobs")
    );
    assert_eq!(
        request.headers().get("cookie").unwrap(),
        "auth_refresh_token=fixture-cookie"
    );
    assert!(request.headers().get("authorization").is_none());
    Ok(response)
}
fn session(api: &str) -> crate::storage::Session {
    crate::storage::Session {
        api_url: api.into(),
        session_id: "fixture-session".into(),
        cookies: std::collections::BTreeMap::from([(
            "auth_refresh_token".into(),
            "fixture-cookie".into(),
        )]),
        ws_token: None,
        master_key: zeroize::Zeroizing::new([7; 32]),
        hashed_email: "fixture-owner".into(),
        user_email_salt: String::new(),
        email_encryption_key: None,
        created_at: 1,
        paired_session_expires_at: None,
        active_team_id: None,
    }
}
#[derive(Clone, Copy, Default)]
struct Controls {
    subchats: bool,
    memories: bool,
    pii_off: bool,
}
fn command(family: &str, controls: Controls, json_output: bool) -> Invocation {
    let text = match family {
        "tasks" => format!("mark {EMAIL}"),
        "plans" => format!("archive {EMAIL}"),
        _ => format!("Organize {EMAIL}"),
    };
    let mut args = vec![
        "openmates".to_owned(),
        family.into(),
        "ask".into(),
        text,
        "--personal".into(),
        format!("--json={json_output}"),
        format!("--auto-approve={}", controls.subchats),
        format!("--auto-approve-memories={}", controls.memories),
        format!("--no-pii-detection={}", controls.pii_off),
        "--response-timeout-seconds".into(),
        "1".into(),
    ];
    if family == "projects" {
        args.extend(["--write-policy".into(), "always_ask".into()]);
    }
    crate::cli::parse_from(args)
        .ok()
        .unwrap()
        .invocation
        .unwrap()
}
#[derive(Clone, Copy)]
enum Ending {
    Queued,
    Cancel,
    Timeout,
    Privacy,
}
async fn peer(
    listener: TcpListener,
    family: &'static str,
    controls: Controls,
    ending: Ending,
    cancel: CancellationToken,
    allowed: Arc<AtomicBool>,
) {
    let (mut socket, _) = bounded(listener.accept()).await.unwrap();
    let (head, body) = http(&mut socket).await;
    let route = match family {
        "tasks" => "user-tasks",
        "plans" => "user-plans",
        other => other,
    };
    assert!(head.starts_with(&format!("POST /v1/{route}/ask HTTP/1.1")));
    assert!(
        head.to_lowercase()
            .contains("cookie: auth_refresh_token=fixture-cookie")
    );
    assert!(body["instruction"].as_str().unwrap().contains(EMAIL));
    if matches!(ending, Ending::Privacy) {
        allowed.store(false, Ordering::SeqCst);
    }
    respond(
        &mut socket,
        json!({"outcome":"fallback_to_chat","fallback_message":"Synthetic context required"}),
    )
    .await;
    drop(socket);
    if matches!(ending, Ending::Privacy) {
        assert!(
            tokio::time::timeout(Duration::from_millis(150), listener.accept())
                .await
                .is_err()
        );
        return;
    }
    let (mut socket, _) = bounded(listener.accept()).await.unwrap();
    let (head, _) = http(&mut socket).await;
    assert!(head.starts_with("POST /v1/auth/session HTTP/1.1"));
    respond(
        &mut socket,
        json!({"success":true,"ws_token":"fixture-token","user":{"user_id":OWNER}}),
    )
    .await;
    drop(socket);
    let (socket, _) = bounded(listener.accept()).await.unwrap();
    let mut ws = bounded(tokio_tungstenite::accept_hdr_async(socket, handshake))
        .await
        .unwrap();
    assert_eq!(frame(&mut ws).await["type"], "native_client_lifecycle");
    let active = frame(&mut ws).await;
    assert_eq!(active["type"], "set_active_chat");
    let snapshot = frame(&mut ws).await;
    assert_eq!(snapshot["type"], "personal_send_context_snapshot");
    let turn = snapshot["payload"]["turn_id"].clone();
    let memories = json!({"memories":[{"id":"fixture-memory","app_id":"fixture","item_type":"category","encrypted_item_json":
        openmates_sdk::crypto::encrypt_combined(r#"{"note":"synthetic preference"}"#,&[7;32]).unwrap()}]});
    send(&mut ws,"personal_send_context_snapshot_result",json!({"success":true,"unchanged":false,"request_id":snapshot["payload"]["request_id"],
        "turn_id":turn,"receipt_id":"fixture-receipt","privacy_generation":1,"project_candidates":[],"personal_memories":memories})).await;
    let admit = frame(&mut ws).await;
    assert_eq!(admit["type"], "chat_turn_admit");
    let p = &admit["payload"];
    let chat = p["chat_id"].clone();
    let user = p["message_id"].clone();
    assert!(user.as_str().is_some_and(|id| !id.is_empty()));
    assert_eq!(p["privacy_receipt_id"], "fixture-receipt");
    assert!(
        p["inference_request"]["client_capabilities"]
            .as_array()
            .unwrap()
            .iter()
            .all(|cap| cap != "task_update_jobs")
    );
    let text = p["inference_request"]["message"]["content"]
        .as_str()
        .unwrap();
    assert_eq!(
        text.contains(EMAIL),
        controls.pii_off,
        "false no-pii flag must retain privacy detection"
    );
    assert!(p["inference_request"].get("model").is_none());
    assert!(p["inference_request"].get("provider").is_none());
    if matches!(ending, Ending::Cancel) {
        cancel.cancel();
        return;
    }
    if matches!(ending, Ending::Timeout) {
        let closed = bounded(ws.next()).await;
        assert!(matches!(closed, None | Some(Ok(Message::Close(_)))));
        return;
    }
    send(
        &mut ws,
        "chat_turn_preflight_ack",
        json!({"turn_id":turn,"preflight_id":"fixture-preflight","committed_messages_v":1}),
    )
    .await;
    send(
        &mut ws,
        "chat_message_confirmed",
        json!({"chat_id":chat,"message_id":user,"new_messages_v":1}),
    )
    .await;
    send(
        &mut ws,
        "ai_task_initiated",
        json!({"chat_id":chat,"user_message_id":user,"task_id":"fixture-task"}),
    )
    .await;
    send(&mut ws,"ai_message_update",json!({"chat_id":chat,"user_message_id":user,"task_id":"fixture-task","message_id":"fixture-answer",
        "full_content_so_far":"Synthetic streamed prefix\n","is_final_chunk":false})).await;
    send(
        &mut ws,
        "sub_chat_confirmation_required",
        json!({"chat_id":chat,"task_id":"fixture-task","sub_chats":[{}]}),
    )
    .await;
    let consent = frame(&mut ws).await;
    assert_eq!(consent["type"], "sub_chat_confirmation");
    assert_eq!(
        consent["payload"]["action"],
        if controls.subchats {
            "approve"
        } else {
            "cancel"
        }
    );
    send(&mut ws,"request_app_settings_memories",json!({"chat_id":chat,"message_id":user,"request_id":"fixture-memory-request","requested_keys":["fixture-category"]})).await;
    let system = frame(&mut ws).await;
    assert_eq!(system["type"], "chat_system_message_added");
    send(
        &mut ws,
        "system_message_confirmed",
        json!({"message_id":system["payload"]["message"]["message_id"]}),
    )
    .await;
    let memory = frame(&mut ws).await;
    assert_eq!(memory["type"], "app_settings_memories_confirmed");
    assert_eq!(
        memory["payload"]["app_settings_memories"]
            .as_array()
            .unwrap()
            .len(),
        usize::from(controls.memories)
    );
    let system = frame(&mut ws).await;
    assert_eq!(system["type"], "chat_system_message_added");
    send(
        &mut ws,
        "system_message_confirmed",
        json!({"message_id":system["payload"]["message"]["message_id"]}),
    )
    .await;
    send(&mut ws,"message_queued",json!({"chat_id":chat,"user_message_id":user,"recovery_turn_id":turn,"queue_mode":"follow_up","queue_revision":1})).await;
}
async fn run_case(family: &'static str, controls: Controls, json_output: bool, ending: Ending) {
    let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
    let api = format!("http://{}", listener.local_addr().unwrap());
    let cancel = CancellationToken::new();
    let allowed = Arc::new(AtomicBool::new(true));
    let mut client = Client::new(&api, Some(session(&api))).unwrap();
    let privacy = allowed.clone();
    client.set_private_operation_gate(Some(Arc::new(move || {
        if privacy.load(Ordering::SeqCst) {
            Ok(())
        } else {
            Err(Error::Forbidden)
        }
    })));
    let peer = Peer(tokio::spawn(peer(
        listener,
        family,
        controls,
        ending,
        cancel.clone(),
        allowed,
    )));
    let result = tokio::time::timeout(
        Duration::from_secs(4),
        crate::cli::execute(&command(family, controls, json_output), &mut client, cancel),
    )
    .await
    .expect("bounded actual ask entrypoint");
    peer.join().await;
    match ending {
        Ending::Queued => {
            let output = result.unwrap_or_else(|error| {
                panic!(
                    "{family} queued fallback failed: {}",
                    error.structured_error()
                )
            });
            assert_eq!(output.exit_code, 0);
            if json_output {
                let value: Value = serde_json::from_str(&output.stdout).unwrap();
                assert_eq!(value["status"], "queued");
                assert_eq!(
                    value["workspace_ask_fallback"]["namespace"],
                    family.trim_end_matches('s')
                );
                assert_eq!(value["acceptedTaskProposals"], json!([]));
            } else {
                assert!(!output.stdout.contains("workspace_ask_fallback"));
            }
        }
        Ending::Cancel => assert_eq!(result.err().unwrap().exit_code(), 130),
        Ending::Timeout => {
            let error = result.err().unwrap();
            assert!(matches!(
                error,
                CliError::PendingTurn {
                    source: Error::Offline,
                    ..
                }
            ));
        }
        Ending::Privacy => assert_eq!(result.err().unwrap().code(), "forbidden"),
    }
}
// contract-test: supporting surface=cli assertions=cli.surface.semantic-parity,cli.runtime.native-rust
#[tokio::test]
async fn every_ask_entrypoint_reaches_stream_and_preserves_true_false_consent_privacy() {
    suite(async {
        for family in ["tasks", "plans", "projects", "workflows"] {
            for controls in [
                Controls::default(),
                Controls {
                    subchats: true,
                    ..Default::default()
                },
                Controls {
                    memories: true,
                    ..Default::default()
                },
                Controls {
                    pii_off: true,
                    ..Default::default()
                },
                Controls {
                    subchats: true,
                    memories: true,
                    pii_off: true,
                },
            ] {
                let json_output = controls.subchats == controls.memories;
                run_case(family, controls, json_output, Ending::Queued).await;
            }
        }
    })
    .await;
}
// contract-test: supporting surface=cli assertions=cli.surface.semantic-parity
#[tokio::test]
async fn every_ask_entrypoint_cancels_fallback_without_task_jobs() {
    suite(async {
        for family in ["tasks", "plans", "projects", "workflows"] {
            run_case(family, Controls::default(), true, Ending::Cancel).await;
        }
    })
    .await;
}
// contract-test: supporting surface=cli assertions=cli.surface.semantic-parity
#[tokio::test]
async fn every_ask_entrypoint_preserves_one_second_response_timeout() {
    suite(async {
        for family in ["tasks", "plans", "projects", "workflows"] {
            run_case(family, Controls::default(), true, Ending::Timeout).await;
        }
    })
    .await;
}
// contract-test: supporting surface=cli assertions=cli.surface.semantic-parity
#[tokio::test]
async fn every_ask_entrypoint_rechecks_privacy_before_fallback_socket() {
    suite(async {
        for family in ["tasks", "plans", "projects", "workflows"] {
            run_case(family, Controls::default(), true, Ending::Privacy).await;
        }
    })
    .await;
}
// contract-test: supporting surface=cli assertions=cli.surface.semantic-parity
#[tokio::test]
async fn ask_admission_does_not_widen_crud_or_allow_wrong_auth_and_context() {
    suite(async {
        for family in ["tasks", "plans", "projects", "workflows"] {
            let mut client =
                Client::new("http://127.0.0.1:1", Some(session("http://127.0.0.1:1"))).unwrap();
            let mut i = command(family, Controls::default(), true);
            i.flags.insert("confirm".into(), json!(true));
            assert_eq!(
                crate::cli::execute(&i, &mut client, CancellationToken::new())
                    .await
                    .err()
                    .unwrap()
                    .code(),
                "native_command_unsupported"
            );
            let mut i = command(family, Controls::default(), true);
            i.flags.insert("auto-approve".into(), json!([true, false]));
            assert_eq!(
                crate::cli::execute(&i, &mut client, CancellationToken::new())
                    .await
                    .err()
                    .unwrap()
                    .code(),
                "invalid_argument"
            );
            let mut i = command(family, Controls::default(), true);
            i.flags.insert("team".into(), json!(OWNER));
            assert_eq!(
                crate::cli::execute(&i, &mut client, CancellationToken::new())
                    .await
                    .err()
                    .unwrap()
                    .code(),
                "invalid_argument"
            );
            let mut client = Client::new("http://127.0.0.1:1", None).unwrap();
            assert_eq!(
                crate::cli::execute(
                    &command(family, Controls::default(), true),
                    &mut client,
                    CancellationToken::new()
                )
                .await
                .err()
                .unwrap()
                .code(),
                "authentication_required"
            );
        }
    })
    .await;
}
