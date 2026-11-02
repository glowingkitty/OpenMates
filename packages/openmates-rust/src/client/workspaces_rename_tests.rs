// contract-test: supporting surface=cli assertions=chats.messages.client-encrypted
use super::*;
use futures_util::{SinkExt, StreamExt};
use tokio::io::{AsyncReadExt, AsyncWriteExt};
use tokio_tungstenite::tungstenite::Message as Frame;
const ID: &str = "11111111-1111-4111-8111-111111111111";
const TEAM: &str = "22222222-2222-4222-8222-222222222222";
const OWNER: &str = "33333333-3333-4333-8333-333333333333";

fn row(messages: u64, team: bool) -> Value {
    let wrapped = crypto::encrypt_bytes(&[8; 32], &[7; 32]).unwrap();
    let mut row = json!({"id":ID,"hashed_user_id":sha256(OWNER),"messages_v":messages,"title_v":2,"metadata_v":3,
        "encrypted_chat_key":wrapped,"encrypted_title":crypto::encrypt_combined("Original title",&[8;32]).unwrap(),
        "encrypted_icon":crypto::encrypt_combined("Existing icon",&[8;32]).unwrap(),
        "encrypted_chat_category":crypto::encrypt_combined("Existing category",&[8;32]).unwrap(),
        "encrypted_chat_summary":crypto::encrypt_combined("Existing summary",&[8;32]).unwrap(),
        "unrelated_metadata":{"keep":true}});
    if team {
        row["hashed_team_id"] = json!(sha256(TEAM));
        row["chat_key_wrappers"] = json!([{"hashed_chat_id":sha256(ID),"key_type":"team","hashed_team_id":sha256(TEAM),"encrypted_chat_key":wrapped}]);
    }
    row
}
fn client(api: &str, row: &Value, team: bool) -> Client {
    let mut session = super::super::sdk_boundary_tests::session();
    session.api_url = api.into();
    session.master_key = zeroize::Zeroizing::new([7; 32]);
    session.active_team_id = team.then(|| TEAM.into());
    session.cookies = BTreeMap::from([("auth_refresh_token".into(), "before".into())]);
    let mut client = Client::new(api, Some(session)).unwrap();
    client.user = json!({"id":OWNER});
    if team {
        client.team_key = Some((TEAM.into(), zeroize::Zeroizing::new([7; 32])));
    }
    client.chats.insert(ID.into(), row.clone());
    client
}
async fn request(stream: &mut tokio::net::TcpStream) -> (String, Value) {
    let mut bytes = vec![];
    let mut chunk = [0; 4096];
    let end = loop {
        let n = stream.read(&mut chunk).await.unwrap();
        assert!(n > 0);
        bytes.extend_from_slice(&chunk[..n]);
        if let Some(n) = bytes.windows(4).position(|v| v == b"\r\n\r\n") {
            break n + 4;
        }
    };
    let head = String::from_utf8(bytes[..end].to_vec()).unwrap();
    let length = head
        .lines()
        .find_map(|line| {
            line.to_ascii_lowercase()
                .strip_prefix("content-length:")
                .map(|v| v.trim().parse::<usize>().unwrap())
        })
        .unwrap_or(0);
    while bytes.len() < end + length {
        let n = stream.read(&mut chunk).await.unwrap();
        assert!(n > 0);
        bytes.extend_from_slice(&chunk[..n]);
    }
    let body = if length == 0 {
        Value::Null
    } else {
        serde_json::from_slice(&bytes[end..end + length]).unwrap()
    };
    (head, body)
}
async fn peer(
    row: Value,
    team: bool,
    receipt: Value,
    cancel: Option<CancellationToken>,
) -> (String, tokio::task::JoinHandle<()>) {
    let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
    let api = format!("http://{}", listener.local_addr().unwrap());
    let task = tokio::spawn(async move {
        for step in 0..3 {
            let (mut stream, _) = listener.accept().await.unwrap();
            let (head, body) = request(&mut stream).await;
            assert!(
                head.to_ascii_lowercase()
                    .contains("auth_refresh_token=before")
            );
            let result = match step {
                0 => {
                    assert!(head.starts_with("POST /v1/chats/metadata/batch"));
                    assert_eq!(body, json!({"chat_ids":[ID]}));
                    if team {
                        assert!(head.contains(&format!("team_id={TEAM}")));
                    }
                    json!({"chats":[row.clone()]})
                }
                1 => {
                    assert!(head.starts_with(&format!("GET /v1/chats/{ID}/messages/window")));
                    json!({"messages":[],"has_more_before":false})
                }
                _ => {
                    assert!(head.starts_with("POST /v1/auth/session "));
                    json!({"success":true,"ws_token":"fresh-token","user":{"id":OWNER}})
                }
            }
            .to_string();
            let cookie = if step == 2 {
                "Set-Cookie: auth_refresh_token=rotated; HttpOnly\r\n"
            } else {
                ""
            };
            stream.write_all(format!("HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: {}\r\n{cookie}Connection: close\r\n\r\n{result}",result.len()).as_bytes()).await.unwrap();
        }
        let (stream, _) = listener.accept().await.unwrap();
        let mut ws = tokio_tungstenite::accept_async(stream).await.unwrap();
        let mutation = loop {
            let frame: Value =
                serde_json::from_str(ws.next().await.unwrap().unwrap().to_text().unwrap()).unwrap();
            if frame["type"] == "update_post_processing_metadata" {
                break frame;
            }
            assert!(matches!(
                frame["type"].as_str(),
                Some("native_client_lifecycle" | "set_active_chat")
            ));
        };
        let body = &mutation["payload"];
        assert_eq!(body["chat_id"], ID);
        assert_eq!(body["manual_update"], true);
        assert_eq!(body["title_changed"], true);
        assert_eq!(body["encrypted_chat_key"], row["encrypted_chat_key"]);
        assert_eq!(
            body["versions"],
            json!({"messages_v":row["messages_v"],"title_v":2,"metadata_v":3})
        );
        assert_eq!(
            crypto::decrypt_combined(body["encrypted_title"].as_str().unwrap(), &[8; 32]).unwrap(),
            "Renamed title"
        );
        assert_eq!(body.as_object().unwrap().len(), if team { 7 } else { 6 });
        if team {
            assert_eq!(body["team_id"], TEAM);
        }
        for field in [
            "encrypted_icon",
            "encrypted_chat_category",
            "encrypted_chat_summary",
            "unrelated_metadata",
        ] {
            assert!(body.get(field).is_none());
        }
        if let Some(cancel) = cancel {
            cancel.cancel();
        }
        ws.send(Frame::Text(
            json!({"type":"post_processing_metadata_stored","payload":receipt})
                .to_string()
                .into(),
        ))
        .await
        .unwrap();
        let _ = ws.close(None).await;
    });
    (api, task)
}
fn receipt(messages: u64) -> Value {
    json!({"chat_id":ID,"status":"stored","versions":{"messages_v":messages,"title_v":8,"metadata_v":11}})
}

#[tokio::test]
async fn title_only_rename_preserves_metadata_for_early_established_and_team_chats() {
    for (messages, team) in [(0, false), (1, false), (9, false), (1, true)] {
        let original = row(messages, team);
        let (api, server) = peer(original.clone(), team, receipt(messages + 1), None).await;
        let mut client = client(&api, &original, team);
        let item = tokio::time::timeout(
            Duration::from_secs(5),
            client.mutate(Mutation::Update {
                workspace: Workspace::Chats,
                id: ID.into(),
                fields: json!({"title":"Renamed title"}),
            }),
        )
        .await
        .unwrap()
        .unwrap()
        .unwrap();
        assert_eq!(item.title, "Renamed title");
        let updated = &client.chats[ID];
        assert_eq!(updated["title_v"], 8);
        assert_eq!(updated["metadata_v"], 11);
        assert_eq!(updated["messages_v"], messages);
        for field in [
            "encrypted_icon",
            "encrypted_chat_category",
            "encrypted_chat_summary",
            "unrelated_metadata",
            "encrypted_chat_key",
            "chat_key_wrappers",
        ] {
            assert_eq!(updated[field], original[field]);
        }
        assert_eq!(
            client.session().unwrap().cookies["auth_refresh_token"],
            "rotated"
        );
        server.await.unwrap();
    }
}

#[tokio::test]
async fn malformed_stale_or_cancelled_rename_receipt_does_not_publish_new_title() {
    for (kind, error) in [
        ("missing", Error::Protocol),
        ("stale", Error::Conflict),
        ("status", Error::Protocol),
        ("cancel", Error::Cancelled),
    ] {
        let original = row(1, false);
        let mut ack = receipt(1);
        match kind {
            "missing" => {
                ack["versions"] = Value::Null;
            }
            "stale" => {
                ack["versions"]["title_v"] = json!(2);
            }
            "status" => {
                ack["status"] = json!("queued_for_storage");
            }
            _ => {}
        }
        let cancel = CancellationToken::new();
        let (api, server) = peer(
            original.clone(),
            false,
            ack,
            (kind == "cancel").then(|| cancel.clone()),
        )
        .await;
        let mut client = client(&api, &original, false);
        client.set_operation_cancel(cancel);
        assert_eq!(
            client
                .mutate(Mutation::Update {
                    workspace: Workspace::Chats,
                    id: ID.into(),
                    fields: json!({"title":"Renamed title"})
                })
                .await
                .unwrap_err(),
            error
        );
        assert_eq!(client.chats[ID], original);
        assert_eq!(
            client.session().unwrap().cookies["auth_refresh_token"],
            "rotated"
        );
        server.await.unwrap();
    }
}

#[test]
fn accepted_versions_are_authoritative_and_never_mark_unseen_history_synchronized() {
    let row = row(4, false);
    assert_eq!(
        accepted_rename_versions(&row, &receipt(7)).unwrap(),
        (8, 11)
    );
    for versions in [
        json!({"messages_v":3,"title_v":8,"metadata_v":11}),
        json!({"messages_v":4,"title_v":8,"metadata_v":3}),
    ] {
        assert_eq!(
            accepted_rename_versions(&row, &json!({"status":"stored","versions":versions})),
            Err(Error::Conflict)
        );
    }
    for versions in [
        json!({"messages_v":4,"title_v":0,"metadata_v":11}),
        json!({"messages_v":4,"title_v":8}),
        json!({"messages_v":"4","title_v":8,"metadata_v":11}),
    ] {
        assert_eq!(
            accepted_rename_versions(&row, &json!({"status":"stored","versions":versions})),
            Err(Error::Protocol)
        );
    }
}

#[test]
fn metadata_version_uses_canonical_positive_value_and_only_then_legacy_title_fallback() {
    let mut row = row(0, false);
    row["title_v"] = json!(10);
    row["metadata_v"] = json!(2);
    assert_eq!(
        accepted_rename_versions(
            &row,
            &json!({"status":"stored","versions":{"messages_v":0,"title_v":11,"metadata_v":3}})
        )
        .unwrap(),
        (11, 3)
    );
    for legacy in [Value::Null, json!(0)] {
        row["metadata_v"] = legacy;
        assert_eq!(
            accepted_rename_versions(
                &row,
                &json!({"status":"stored","versions":{"messages_v":0,"title_v":11,"metadata_v":11}})
            )
            .unwrap(),
            (11, 11)
        );
        assert_eq!(
            accepted_rename_versions(
                &row,
                &json!({"status":"stored","versions":{"messages_v":0,"title_v":11,"metadata_v":10}})
            ),
            Err(Error::Conflict)
        );
    }
}
