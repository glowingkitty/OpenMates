// contract-test: supporting surface=cli assertions=chats.messages.client-encrypted,cli.output.actionable-readable
use super::*;
use futures_util::{SinkExt, StreamExt};
use tokio::{
    io::{AsyncReadExt, AsyncWriteExt},
    sync::oneshot,
};
use tokio_tungstenite::tungstenite::{
    Message as Frame,
    handshake::server::{ErrorResponse, Request, Response},
};

const ID: &str = "11111111-1111-4111-8111-111111111111";
const OTHER: &str = "22222222-2222-4222-8222-222222222222";

fn invocation(args: &[&str]) -> Invocation {
    parse_from(args.iter().copied())
        .unwrap_or_else(|error| panic!("{error}"))
        .invocation
        .unwrap()
}
fn client(api: &str) -> Client {
    Client::with_options(
        api,
        Some(openmates_sdk::Session {
            api_url: api.into(),
            session_id: "draft-cli-fixture".into(),
            cookies: std::collections::BTreeMap::from([(
                "auth_refresh_token".into(),
                "before".into(),
            )]),
            ws_token: None,
            master_key: zeroize::Zeroizing::new([7; 32]),
            hashed_email: "fixture".into(),
            user_email_salt: String::new(),
            email_encryption_key: None,
            created_at: 1,
            paired_session_expires_at: None,
            active_team_id: None,
        }),
        openmates_sdk::ClientOptions {
            identity: openmates_sdk::ClientIdentity::Cli,
            ..Default::default()
        },
    )
    .unwrap()
}
fn seed(client: &mut Client, shell: bool) -> Value {
    let mut row = json!({"id":ID,"user_id":"owner","draft_v":2,
        "encrypted_draft_md":crate::crypto::encrypt_combined("Unsaved private draft", &[7;32]).unwrap(),
        "encrypted_draft_preview":crate::crypto::encrypt_combined("Private preview", &[7;32]).unwrap()});
    if !shell {
        row["messages_v"] = json!(1);
        row["title_v"] = json!(1);
        row["encrypted_chat_key"] =
            json!(crate::crypto::encrypt_bytes(&[8; 32], &[7; 32]).unwrap());
        row["encrypted_title"] =
            json!(crate::crypto::encrypt_combined("Retained saved title", &[8; 32]).unwrap());
    }
    let history = if shell {
        json!([])
    } else {
        json!([{"id":"retained-message","role":"user","encrypted_content":crate::crypto::encrypt_combined("Retained saved message", &[8;32]).unwrap()}])
    };
    let snapshot = json!({"chats":{ID:row,OTHER:{"id":OTHER,"encrypted_chat_key":"unrelated-wrapper"}},"wrappers":[],"history":{ID:history,OTHER:[{"encrypted_content":"unrelated-ciphertext"}]}});
    client.restore_ciphertext_snapshot(&snapshot).unwrap();
    client.ciphertext_snapshot()
}

struct Peer {
    api: String,
    requested: oneshot::Receiver<()>,
    reply: oneshot::Sender<()>,
    task: tokio::task::JoinHandle<()>,
}

#[allow(clippy::result_large_err)] // Required upstream WebSocket handshake callback signature.
fn verify_handshake(request: &Request, response: Response) -> Result<Response, ErrorResponse> {
    assert!(request.uri().query().unwrap().contains("token=fresh-token"));
    assert!(
        request.headers()["cookie"]
            .to_str()
            .unwrap()
            .contains("auth_refresh_token=rotated")
    );
    Ok(response)
}

async fn peer(receipt: Option<Value>) -> Peer {
    let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
    let api = format!("http://{}", listener.local_addr().unwrap());
    let (requested, request_seen) = oneshot::channel();
    let (reply, allow_reply) = oneshot::channel();
    let task = tokio::spawn(async move {
        tokio::time::timeout(std::time::Duration::from_secs(5),async move {
            let (mut http,_)=listener.accept().await.unwrap();
            let mut data=vec![];
            loop {
                let mut chunk=[0;4096];let n=http.read(&mut chunk).await.unwrap();assert!(n>0);data.extend_from_slice(&chunk[..n]);
                if let Some(end)=data.windows(4).position(|v|v==b"\r\n\r\n") {
                    let head=std::str::from_utf8(&data[..end]).unwrap();
                    let length=head.lines().find_map(|line|line.to_ascii_lowercase().strip_prefix("content-length:").map(|value|value.trim().parse::<usize>().unwrap())).unwrap();
                    if data.len()>=end+4+length {
                        assert!(head.starts_with("POST /v1/auth/session "));
                        assert!(head.to_ascii_lowercase().contains("x-openmates-sdk: cli"));
                        assert!(head.contains("auth_refresh_token=before"));
                        break;
                    }
                }
            }
            let body=json!({"success":true,"ws_token":"fresh-token","user":{"id":"owner"}}).to_string();
            http.write_all(format!("HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: {}\r\nSet-Cookie: auth_refresh_token=rotated; HttpOnly\r\nConnection: close\r\n\r\n{body}",body.len()).as_bytes()).await.unwrap();drop(http);
            let (stream,_)=listener.accept().await.unwrap();
            let mut ws=tokio_tungstenite::accept_hdr_async(stream, verify_handshake).await.unwrap();
            let lifecycle:Value=serde_json::from_str(ws.next().await.unwrap().unwrap().to_text().unwrap()).unwrap();
            assert_eq!(lifecycle["type"],"native_client_lifecycle");
            let mutation:Value=serde_json::from_str(ws.next().await.unwrap().unwrap().to_text().unwrap()).unwrap();
            assert_eq!(mutation,json!({"type":"delete_draft","payload":{"chat_id":ID}}));
            requested.send(()).unwrap();allow_reply.await.unwrap();
            // An unrelated receipt cannot confirm this invocation.
            ws.send(Frame::Text(json!({"type":"draft_delete_receipt","payload":{"chat_id":OTHER,"success":true,"draft_v":999}}).to_string().into())).await.unwrap();
            if let Some(receipt)=receipt {ws.send(Frame::Text(json!({"type":"draft_delete_receipt","payload":receipt}).to_string().into())).await.unwrap();}
            let _ = ws.close(None).await;
            // Never accept a second HTTP request or mutation after an uncertain receipt.
            assert!(tokio::time::timeout(std::time::Duration::from_millis(30),listener.accept()).await.is_err());
        }).await.unwrap();
    });
    Peer {
        api,
        requested: request_seen,
        reply,
        task,
    }
}

#[test]
fn parser_and_admission_keep_one_id_noninteractive_cookie_contract() {
    for json in [false, true] {
        let mut args = vec!["openmates", "drafts", "clear", ID];
        if json {
            args.push("--json");
        }
        let i = invocation(&args);
        assert_eq!(i.positionals, [ID]);
        assert_eq!(i.boolean("json"), json);
        let r = requirements(&i);
        assert!(r.supported && r.authenticated && !r.interactive);
        assert!(execute_public(&i).is_none());
    }
    assert!(parse_from(["openmates", "drafts", "clear"]).is_err());
    assert!(parse_from(["openmates", "drafts", "clear", ID, OTHER]).is_err());
    assert!(parse_from(["openmates", "drafts", "clear", ID, "--refresh"]).is_err());
    assert!(parse_from(["openmates", "drafts", "clear", ID, "--refresh", "true"]).is_err());
}

#[tokio::test]
async fn invalid_flags_ids_scope_keys_and_precancel_never_use_cookie_transport() {
    for (args, code) in [
        (
            vec!["openmates", "drafts", "clear", "not-a-uuid"],
            "invalid_argument",
        ),
        (
            vec![
                "openmates",
                "drafts",
                "clear",
                ID,
                "--api-key",
                "synthetic-key",
            ],
            "native_command_unsupported",
        ),
        (
            vec!["openmates", "drafts", "clear", ID, "--refresh", "true"],
            "native_command_unsupported",
        ),
    ] {
        let mut c = client("http://127.0.0.1:1");
        let before = seed(&mut c, false);
        // The parser rejects --refresh. Inject it only to exercise the
        // handler's independent no-transport defense with a valid invocation.
        let i = if args.contains(&"--refresh") {
            let mut i = invocation(&["openmates", "drafts", "clear", ID]);
            i.flags.insert("refresh".into(), json!(true));
            i
        } else {
            invocation(&args)
        };
        let error = execute(&i, &mut c, CancellationToken::new())
            .await
            .err()
            .expect("must refuse");
        assert_eq!(error.code(), code);
        assert_eq!(c.ciphertext_snapshot(), before);
        assert_eq!(c.session().unwrap().cookies["auth_refresh_token"], "before");
    }
    let i = invocation(&["openmates", "drafts", "clear", ID]);
    let mut absent = Client::new("http://127.0.0.1:1", None).unwrap();
    assert!(matches!(
        execute(&i, &mut absent, CancellationToken::new()).await,
        Err(CliError::Client(Error::Authentication))
    ));
    let mut c = client("http://127.0.0.1:1");
    c.set_team(Some(OTHER)).unwrap();
    assert!(matches!(
        execute(&i, &mut c, CancellationToken::new()).await,
        Err(CliError::Client(Error::Unavailable {
            code: "team_draft_clear_unavailable",
            ..
        }))
    ));
    for (field, value) in [
        ("chat_visibility", json!("direct")),
        ("team_id", json!(OTHER)),
    ] {
        let mut c = client("http://127.0.0.1:1");
        let mut snapshot = seed(&mut c, false);
        snapshot["chats"][ID][field] = value;
        c.restore_ciphertext_snapshot(&snapshot).unwrap();
        assert!(matches!(
            execute(&i, &mut c, CancellationToken::new()).await,
            Err(CliError::Client(Error::Forbidden))
        ));
        assert_eq!(c.ciphertext_snapshot(), snapshot);
    }
    let mut c = client("http://127.0.0.1:1");
    let before = seed(&mut c, false);
    let cancel = CancellationToken::new();
    cancel.cancel();
    let error = execute(&i, &mut c, cancel).await.err().unwrap();
    assert_eq!(error.exit_code(), 130);
    assert_eq!(c.ciphertext_snapshot(), before);
}

#[tokio::test]
async fn success_is_unconditional_legacy_json_and_only_clears_acknowledged_draft_state() {
    for shell in [false, true] {
        for json_flag in [false, true] {
            let p = peer(Some(json!({"chat_id":ID,"success":true,"draft_v":3}))).await;
            let mut c = client(&p.api);
            let mut expected = seed(&mut c, shell);
            if shell {
                expected["chats"].as_object_mut().unwrap().remove(ID);
                expected["history"].as_object_mut().unwrap().remove(ID);
            } else {
                let row = &mut expected["chats"][ID];
                row.as_object_mut().unwrap().remove("encrypted_draft_md");
                row.as_object_mut()
                    .unwrap()
                    .remove("encrypted_draft_preview");
                row["draft_v"] = json!(3);
            }
            let mut args = vec!["openmates", "drafts", "clear", ID];
            if json_flag {
                args.push("--json");
            }
            let i = invocation(&args);
            p.reply.send(()).unwrap();
            let output = execute(&i, &mut c, CancellationToken::new())
                .await
                .unwrap_or_else(|e| panic!("{e}"));
            assert_eq!(
                serde_json::from_str::<Value>(&output.stdout).unwrap(),
                json!({"success":true,"chat_id":ID})
            );
            assert_eq!(output.exit_code, 0);
            assert!(output.stderr.is_empty());
            assert_eq!(c.ciphertext_snapshot(), expected);
            assert_eq!(
                c.session().unwrap().cookies["auth_refresh_token"],
                "rotated"
            );
            p.task.await.unwrap();
        }
    }
}

#[tokio::test]
async fn no_success_before_receipt_and_cancelled_receipt_preserves_ciphertext_and_rotation() {
    for cancel_after_request in [false, true] {
        let p = peer(Some(json!({"chat_id":ID,"success":true,"draft_v":3}))).await;
        let mut c = client(&p.api);
        let before = seed(&mut c, false);
        let i = invocation(&["openmates", "drafts", "clear", ID]);
        let cancel = CancellationToken::new();
        let mut operation = Box::pin(execute(&i, &mut c, cancel.clone()));
        let mut requested = p.requested;
        tokio::select! {r=&mut requested=>r.unwrap(),r=&mut operation=>panic!("completed before admission: {}",r.is_ok())};
        assert!(
            tokio::time::timeout(std::time::Duration::from_millis(20), &mut operation)
                .await
                .is_err()
        );
        if cancel_after_request {
            cancel.cancel();
        }
        p.reply.send(()).unwrap();
        let result = operation.as_mut().await;
        if cancel_after_request {
            let error = result.err().unwrap();
            assert_eq!(error.code(), "cancelled");
            assert_eq!(error.exit_code(), 130);
        } else {
            assert!(result.is_ok());
        }
        p.task.await.unwrap();
        // Drop the completed future before inspecting its borrowed client.
        drop(operation);
        if cancel_after_request {
            assert_eq!(c.ciphertext_snapshot(), before);
        }
        assert_eq!(
            c.session().unwrap().cookies["auth_refresh_token"],
            "rotated"
        );
    }
}

#[tokio::test]
async fn refused_or_missing_receipts_fail_without_cache_publication_or_retry() {
    for receipt in [
        Some(json!({"chat_id":ID,"success":false,"draft_v":3})),
        Some(json!({"chat_id":ID,"success":true,"draft_v":2})),
        None,
    ] {
        let p = peer(receipt).await;
        let mut c = client(&p.api);
        let before = seed(&mut c, false);
        p.reply.send(()).unwrap();
        let error = execute(
            &invocation(&["openmates", "drafts", "clear", ID, "--json"]),
            &mut c,
            CancellationToken::new(),
        )
        .await
        .err()
        .expect("no success without a valid receipt");
        assert_ne!(error.exit_code(), 0);
        assert_eq!(c.ciphertext_snapshot(), before);
        assert_eq!(
            c.session().unwrap().cookies["auth_refresh_token"],
            "rotated"
        );
        p.task.await.unwrap();
    }
}
