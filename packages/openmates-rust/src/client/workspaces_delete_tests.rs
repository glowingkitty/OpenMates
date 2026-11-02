// contract-test: supporting surface=cli assertions=chats.messages.client-encrypted
use super::*;
use futures_util::{SinkExt, StreamExt};
use tokio::io::{AsyncReadExt, AsyncWriteExt};
use tokio_tungstenite::tungstenite::Message as Frame;

const ID: &str = "11111111-1111-4111-8111-111111111111";
const OTHER: &str = "22222222-2222-4222-8222-222222222222";

pub(in crate::client) fn client(api: &str, team: bool, draft: bool) -> Client {
    let mut session = super::super::sdk_boundary_tests::session();
    session.api_url = api.into();
    session.master_key = zeroize::Zeroizing::new([7; 32]);
    session.active_team_id = team.then(|| OTHER.into());
    session.cookies = BTreeMap::from([("auth_refresh_token".into(), "before".into())]);
    let mut client = Client::new(api, Some(session)).unwrap();
    client.user = json!({"id":"owner"});
    let row = if draft {
        json!({"id":ID,"draft_v":2,"encrypted_draft_md":crypto::encrypt_combined("Private draft",&[7;32]).unwrap()})
    } else {
        json!({"id":ID,"messages_v":1,"encrypted_chat_key":"opaque-existing-wrapper"})
    };
    client.chats.insert(ID.into(), row);
    client.history.insert(
        ID.into(),
        if draft {
            vec![]
        } else {
            vec![json!({"id":"opaque-message","encrypted_content":"existing-ciphertext"})]
        },
    );
    client.active_chat = Some(ID.into());
    client
}

async fn peer(team: bool, frames: Vec<Value>) -> (String, tokio::task::JoinHandle<()>) {
    peer_operation(team, "delete_chat", frames).await
}
async fn peer_operation(
    team: bool,
    operation: &'static str,
    frames: Vec<Value>,
) -> (String, tokio::task::JoinHandle<()>) {
    peer_control(team, operation, frames, None).await
}
pub(in crate::client) async fn peer_control(
    team: bool,
    operation: &'static str,
    frames: Vec<Value>,
    cancel_before_receipt: Option<CancellationToken>,
) -> (String, tokio::task::JoinHandle<()>) {
    let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
    let api = format!("http://{}", listener.local_addr().unwrap());
    let server = tokio::spawn(async move {
        let (mut stream, _) = listener.accept().await.unwrap();
        let mut bytes = vec![];
        let mut chunk = [0; 4096];
        let end = loop {
            let n = stream.read(&mut chunk).await.unwrap();
            assert!(n > 0);
            bytes.extend_from_slice(&chunk[..n]);
            if let Some(end) = bytes.windows(4).position(|w| w == b"\r\n\r\n") {
                break end + 4;
            }
        };
        let header = String::from_utf8(bytes[..end].to_vec()).unwrap();
        assert!(header.starts_with("POST /v1/auth/session "));
        assert!(
            header
                .to_ascii_lowercase()
                .contains("auth_refresh_token=before")
        );
        let length = header
            .lines()
            .find_map(|line| {
                line.to_ascii_lowercase()
                    .strip_prefix("content-length:")
                    .map(|v| v.trim().parse::<usize>().unwrap())
            })
            .unwrap();
        while bytes.len() < end + length {
            let n = stream.read(&mut chunk).await.unwrap();
            assert!(n > 0);
            bytes.extend_from_slice(&chunk[..n]);
        }
        let body =
            json!({"success":true,"ws_token":"fresh-token","user":{"id":"owner"}}).to_string();
        stream.write_all(format!("HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: {}\r\nSet-Cookie: auth_refresh_token=rotated; HttpOnly\r\nConnection: close\r\n\r\n{body}",body.len()).as_bytes()).await.unwrap();
        drop(stream);
        let (stream, _) = listener.accept().await.unwrap();
        let mut ws = tokio_tungstenite::accept_async(stream).await.unwrap();
        let mut deletion = None;
        for _ in 0..3 {
            let frame: Value =
                serde_json::from_str(ws.next().await.unwrap().unwrap().to_text().unwrap()).unwrap();
            if frame["type"] == operation {
                deletion = Some(frame);
                break;
            }
            assert!(matches!(
                frame["type"].as_str(),
                Some("native_client_lifecycle" | "set_active_chat")
            ));
        }
        // Saved-chat deletion and user-specific draft tombstones are distinct
        // canonical protocols. A draft-only row has no recovery-delete fence.
        let deletion = deletion.unwrap();
        if operation == "delete_chat" {
            let expected = if team {
                json!({"chatId":ID,"chat_id":ID,"team_id":OTHER})
            } else {
                json!({"chatId":ID,"chat_id":ID})
            };
            assert_eq!(deletion["payload"], expected);
        } else if operation == "delete_draft" {
            assert_eq!(deletion["payload"], json!({"chat_id":ID}));
        } else {
            let payload = &deletion["payload"];
            assert_eq!(payload.as_object().unwrap().len(), 3);
            assert_eq!(payload["chat_id"], ID);
            for field in ["encrypted_draft_md", "encrypted_draft_preview"] {
                assert_eq!(
                    crypto::decrypt_combined(payload[field].as_str().unwrap(), &[7; 32]).unwrap(),
                    "Updated private draft"
                );
            }
        }
        if let Some(cancel) = cancel_before_receipt {
            cancel.cancel();
        }
        for frame in frames {
            ws.send(Frame::Text(frame.to_string().into()))
                .await
                .unwrap();
        }
        // Deliberately drop on errors: no second delete/retry is permitted.
        let _ = ws.close(None).await;
    });
    (api, server)
}

#[tokio::test]
async fn canonical_delete_or_draft_clear_removes_only_the_confirmed_scope() {
    for (team, draft) in [(false, true), (false, false), (true, false)] {
        let (api, server) = peer_operation(team,
            if draft {"delete_draft"} else {"delete_chat"},
            if draft {vec![json!({"type":"draft_delete_receipt","payload":{"chat_id":ID,"success":true,"draft_v":3}})]}
            else {vec![json!({"type":"chat_deleted","payload":{"chat_id":ID,"tombstone":true}})]},
        )
        .await;
        let mut client = client(&api, team, draft);
        let result = tokio::time::timeout(
            Duration::from_secs(5),
            client.mutate(Mutation::Delete {
                workspace: Workspace::Chats,
                id: ID.into(),
            }),
        )
        .await
        .unwrap()
        .unwrap();
        assert!(result.is_none());
        assert!(!client.chats.contains_key(ID));
        assert!(!client.history.contains_key(ID));
        assert!(client.active_chat.is_none());
        assert_eq!(
            client.session().unwrap().cookies["auth_refresh_token"],
            "rotated"
        );
        server.await.unwrap();
    }
}

#[tokio::test]
async fn rejected_or_unrelated_delete_ack_preserves_original_ciphertext_without_retry() {
    for frames in [
        vec![json!({"type":"error","payload":{"message":"synthetic-private-diagnostic"}})],
        vec![json!({"type":"chat_deleted","payload":{"chat_id":OTHER,"tombstone":true}})],
    ] {
        let (api, server) = peer(false, frames).await;
        let mut client = client(&api, false, false);
        let chats = client.chats.clone();
        let history = client.history.clone();
        assert!(
            tokio::time::timeout(
                Duration::from_secs(5),
                client.mutate(Mutation::Delete {
                    workspace: Workspace::Chats,
                    id: ID.into()
                })
            )
            .await
            .unwrap()
            .is_err()
        );
        assert_eq!(client.chats, chats);
        assert_eq!(client.history, history);
        assert_eq!(client.active_chat.as_deref(), Some(ID));
        assert_eq!(
            client.session().unwrap().cookies["auth_refresh_token"],
            "rotated"
        );
        server.await.unwrap();
    }
}

#[tokio::test]
async fn cancelled_delete_does_not_open_transport_or_erase_cache() {
    let mut client = client("http://127.0.0.1:1", false, true);
    let chats = client.chats.clone();
    let cancel = CancellationToken::new();
    cancel.cancel();
    client.set_operation_cancel(cancel);
    assert!(matches!(
        client
            .mutate(Mutation::Delete {
                workspace: Workspace::Chats,
                id: ID.into()
            })
            .await,
        Err(Error::Cancelled)
    ));
    assert_eq!(client.chats, chats);
    assert_eq!(client.active_chat.as_deref(), Some(ID));
}

#[tokio::test]
async fn canonical_draft_receipt_publishes_only_confirmed_current_ciphertext() {
    let (api, server) = peer_operation(false,"update_draft",vec![json!({"type":"draft_update_receipt","payload":{"chat_id":ID,"success":true,"draft_v":3}})]).await;
    let mut client = client(&api, false, true);
    assert_eq!(
        client
            .save_draft(Some(ID), "Updated private draft")
            .await
            .unwrap(),
        ID
    );
    assert_eq!(client.chats[ID]["draft_v"], 3);
    assert_eq!(
        crypto::decrypt_combined(
            client.chats[ID]["encrypted_draft_md"].as_str().unwrap(),
            &[7; 32]
        )
        .unwrap(),
        "Updated private draft"
    );
    server.await.unwrap();
}

#[tokio::test]
async fn rejected_superseded_and_malformed_draft_receipts_preserve_cache_without_retry() {
    for (receipt, error) in [
        (json!({"success":false,"draft_v":3}), Error::Protocol),
        (json!({"draft_v":3}), Error::Protocol),
        (
            json!({"success":true,"draft_v":3,"superseded":true}),
            Error::Conflict,
        ),
        (json!({"success":true,"draft_v":2}), Error::Conflict),
        (json!({"success":true,"draft_v":1}), Error::Conflict),
        (json!({"success":true,"draft_v":0}), Error::Protocol),
        (json!({"success":true,"draft_v":"3"}), Error::Protocol),
        (
            json!({"success":true,"draft_v":3,"team_id":OTHER}),
            Error::Forbidden,
        ),
    ] {
        let mut receipt = receipt;
        receipt["chat_id"] = json!(ID);
        let (api, server) = peer_operation(
            false,
            "update_draft",
            vec![json!({"type":"draft_update_receipt","payload":receipt})],
        )
        .await;
        let mut client = client(&api, false, true);
        let chats = client.chats.clone();
        assert_eq!(
            client
                .save_draft(Some(ID), "Updated private draft")
                .await
                .unwrap_err(),
            error
        );
        assert_eq!(client.chats, chats);
        assert_eq!(
            client.session().unwrap().cookies["auth_refresh_token"],
            "rotated"
        );
        server.await.unwrap();
    }
}

#[tokio::test]
async fn cancelled_draft_receipt_retains_rotated_credentials_without_publishing_ciphertext() {
    let cancel = CancellationToken::new();
    let (api, server) = peer_control(false,"update_draft",vec![json!({"type":"draft_update_receipt","payload":{"chat_id":ID,"success":true,"draft_v":3}})],Some(cancel.clone())).await;
    let mut client = client(&api, false, true);
    client.set_operation_cancel(cancel);
    let chats = client.chats.clone();
    assert!(matches!(
        client.save_draft(Some(ID), "Updated private draft").await,
        Err(Error::Cancelled)
    ));
    assert_eq!(client.chats, chats);
    assert_eq!(
        client.session().unwrap().cookies["auth_refresh_token"],
        "rotated"
    );
    server.await.unwrap();
}

#[tokio::test]
async fn saved_draft_new_row_appends_once_and_existing_row_keeps_known_arrival_rank() {
    for existing in [false,true] {
        let (api,server)=peer_operation(false,"update_draft",vec![json!({"type":"draft_update_receipt","payload":{"chat_id":ID,"success":true,"draft_v":3}})]).await;
        let mut client=client(&api,false,true);
        client.chat_arrival_order=Some(vec![ID.into()]);
        if !existing {client.remove_chat_row(ID);}
        client.insert_chat_row(OTHER.into(),json!({"id":OTHER,"untouched":"local"}));
        let before=client.chat_arrival_order.clone().unwrap();
        client.save_draft(Some(ID),"Updated private draft").await.unwrap();
        let expected=if existing {before.clone()}else{let mut ids=before.clone();ids.push(ID.into());ids};
        assert_eq!(client.chat_arrival_order,Some(expected));
        assert_eq!(client.chats[OTHER],json!({"id":OTHER,"untouched":"local"}));
        assert_eq!(client.chats[ID]["draft_v"],3);
        assert_eq!(crypto::decrypt_combined(client.chats[ID]["encrypted_draft_md"].as_str().unwrap(),&[7;32]).unwrap(),"Updated private draft");
        server.await.unwrap();
    }
}

// Retain through the actual ciphertext-window builder, not a mocked deletion
// callback. The third row is a child: deleting its parent must not erase it.
const DELETE_WINDOW_CHILD: &str = "33333333-3333-4333-8333-333333333333";
fn retained_delete_windows(client: &mut Client) {
    let wrapped = crypto::encrypt_combined("01234567890123456789012345678901", &[7; 32])
        .expect("synthetic chat key encryption");
    let team = client.session().unwrap().active_team_id.clone();
    for id in [ID, OTHER, DELETE_WINDOW_CHILD] {
        let mut row = json!({"id":id,"messages_v":1,"encrypted_chat_key":wrapped});
        if id == DELETE_WINDOW_CHILD {
            row["parent_chat_id"] = json!(ID);
        }
        client.chats.insert(id.into(), row);
        if let Some(team) = &team {
            client.wrappers.push(json!({"hashed_chat_id":sha256(id),"key_type":"team",
                "hashed_team_id":sha256(team),"encrypted_chat_key":wrapped}));
        }
    }
    for id in [ID, OTHER, DELETE_WINDOW_CHILD] {
        let row = client.chats[id].clone();
        let page = json!({"messages":[{"id":id,"chat_id":id,"created_at":1,"role":"user",
            "encrypted_content":crypto::encrypt_combined("Retained synthetic delete window",
                b"01234567890123456789012345678901").unwrap()}],
            "server_message_count":1,"has_more_before":false,
            "start_cursor":{"created_at":1,"message_id":id}});
        client.retain_settlement_page(&row, &page).unwrap();
    }
}

#[tokio::test]
async fn acknowledged_chat_delete_retires_only_its_window_from_serialized_and_restored_snapshot() {
    for team in [false, true] {
        let (api, server) = peer(team, vec![json!({"type":"chat_deleted",
            "payload":{"chat_id":ID,"tombstone":true}})]).await;
        let mut client = client(&api, team, false);
        retained_delete_windows(&mut client);
        let before = client.ciphertext_snapshot();
        assert_eq!(before["sync_message_windows"].as_object().unwrap().len(), 3);
        let result = tokio::time::timeout(Duration::from_secs(5), client.mutate(Mutation::Delete {
            workspace: Workspace::Chats, id: ID.into(),
        })).await.unwrap().unwrap();
        assert!(result.is_none());
        let mut expected = before;
        for field in ["chats", "history", "sync_message_windows"] {
            expected[field].as_object_mut().unwrap().remove(ID);
        }
        let mut snapshot = client.ciphertext_snapshot();
        // The acknowledged deletion leaves only a local display tombstone.
        let tombstones = snapshot.as_object_mut().unwrap()
            .remove(super::super::chat_tombstones::SNAPSHOT_FIELD).unwrap();
        assert!(tombstones[ID].as_u64().is_some());
        assert_eq!(tombstones.as_object().unwrap().len(), 1);
        assert_eq!(snapshot, expected);
        assert!(snapshot["sync_message_windows"].get(ID).is_none());
        assert!(client.active_chat.is_none());
        assert_eq!(snapshot["chats"][DELETE_WINDOW_CHILD]["parent_chat_id"], ID);
        for id in [OTHER, DELETE_WINDOW_CHILD] {
            assert!(snapshot["sync_message_windows"].get(id).is_some());
        }
        // The exact serialized payload persisted by the application has no
        // deleted window; normal snapshot restoration cannot resurrect it.
        let encoded = serde_json::to_vec(&snapshot).unwrap();
        let decoded: Value = serde_json::from_slice(&encoded).unwrap();
        let mut restored = self::client(&api, team, false);
        restored.restore_ciphertext_snapshot(&decoded).unwrap();
        assert_eq!(restored.ciphertext_snapshot(), expected);
        assert_eq!(client.session().unwrap().cookies["auth_refresh_token"], "rotated");
        server.await.unwrap();
    }
}

#[tokio::test]
async fn declined_unknown_and_foreign_delete_outcomes_preserve_all_retained_windows() {
    for frames in [
        vec![json!({"type":"error","payload":{"message":"synthetic declined deletion"}})],
        vec![],
        vec![json!({"type":"chat_deleted","payload":{"chat_id":OTHER,"tombstone":true}})],
    ] {
        let (api, server) = peer(false, frames).await;
        let mut client = client(&api, false, false);
        retained_delete_windows(&mut client);
        let before = client.ciphertext_snapshot();
        assert!(tokio::time::timeout(Duration::from_secs(5), client.mutate(Mutation::Delete {
            workspace: Workspace::Chats, id: ID.into(),
        })).await.unwrap().is_err());
        assert_eq!(client.ciphertext_snapshot(), before);
        assert_eq!(client.active_chat.as_deref(), Some(ID));
        assert_eq!(client.session().unwrap().cookies["auth_refresh_token"], "rotated");
        server.await.unwrap();
    }
}

#[tokio::test]
async fn cancelled_delete_receipt_cannot_retire_the_original_retained_window() {
    let cancel = CancellationToken::new();
    let (api, server) = peer_control(false, "delete_chat", vec![json!({"type":"chat_deleted",
        "payload":{"chat_id":ID,"tombstone":true}})], Some(cancel.clone())).await;
    let mut client = client(&api, false, false);
    retained_delete_windows(&mut client);
    client.set_operation_cancel(cancel);
    let before = client.ciphertext_snapshot();
    assert!(matches!(tokio::time::timeout(Duration::from_secs(5), client.mutate(Mutation::Delete {
        workspace: Workspace::Chats, id: ID.into(),
    })).await.unwrap(), Err(Error::Cancelled)));
    assert_eq!(client.ciphertext_snapshot(), before);
    assert_eq!(client.active_chat.as_deref(), Some(ID));
    assert_eq!(client.session().unwrap().cookies["auth_refresh_token"], "rotated");
    server.await.unwrap();
}
