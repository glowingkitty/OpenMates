// contract-test: supporting surface=cli assertions=chats.messages.client-encrypted
use super::*;
use tokio::io::{AsyncReadExt, AsyncWriteExt};

const ID: &str = "11111111-1111-4111-8111-111111111111";
const OWNER: &str = "22222222-2222-4222-8222-222222222222";

fn draft() -> Value {
    json!({"chat_id":ID,"draft_v":2,
        "encrypted_draft_md":crypto::encrypt_combined("Private full draft", &[7;32]).unwrap(),
        "encrypted_draft_preview":crypto::encrypt_combined("Private preview", &[7;32]).unwrap()})
}
fn row(draft: &Value) -> Value {
    json!({"id":ID,"type":"new_chat","messages_v":0,"user_id":OWNER,
        "draft_v":draft["draft_v"],"encrypted_draft_md":draft["encrypted_draft_md"],
        "encrypted_draft_preview":draft["encrypted_draft_preview"]})
}
fn make_client(api: &str, draft: &Value) -> Client {
    let mut client = Client::new(
        api,
        Some(Session {
            api_url: api.into(),
            session_id: "fixture-session".into(),
            cookies: BTreeMap::from([("auth_refresh_token".into(), "fixture-cookie".into())]),
            ws_token: None,
            master_key: zeroize::Zeroizing::new([7; 32]),
            hashed_email: "fixture-owner".into(),
            user_email_salt: String::new(),
            email_encryption_key: None,
            created_at: 1,
            paired_session_expires_at: None,
            active_team_id: None,
        }),
    )
    .unwrap();
    client.user = json!({"id":OWNER});
    client.chats.insert(ID.into(), row(draft));
    client
}
type Reply = (&'static str, u16, Value);
async fn spawn_server(replies: Vec<Reply>) -> (String, tokio::task::JoinHandle<()>) {
    spawn_server_inner(replies, None).await
}
async fn spawn_server_inner(
    replies: Vec<Reply>,
    mut delay: Option<(
        tokio::sync::oneshot::Sender<()>,
        tokio::sync::oneshot::Receiver<()>,
    )>,
) -> (String, tokio::task::JoinHandle<()>) {
    let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
    let api = format!("http://{}", listener.local_addr().unwrap());
    let task = tokio::spawn(async move {
        for (index, (expected, status, body)) in replies.into_iter().enumerate() {
            let (mut socket, _) = tokio::time::timeout(Duration::from_secs(5), listener.accept())
                .await
                .unwrap()
                .unwrap();
            let mut bytes = vec![];
            let mut chunk = [0; 4096];
            let end = loop {
                let n = socket.read(&mut chunk).await.unwrap();
                assert!(n > 0);
                bytes.extend_from_slice(&chunk[..n]);
                if let Some(end) = bytes.windows(4).position(|w| w == b"\r\n\r\n") {
                    break end + 4;
                }
            };
            let head = String::from_utf8(bytes[..end].to_vec()).unwrap();
            assert!(
                head.starts_with(expected),
                "Unexpected request: {}",
                head.lines().next().unwrap()
            );
            let lower = head.to_ascii_lowercase();
            assert!(lower.contains(if index == 0 {
                "auth_refresh_token=fixture-cookie"
            } else {
                "auth_refresh_token=rotated-cookie"
            }));
            assert!(lower.contains("x-openmates-sdk: rust"));
            let length = head
                .lines()
                .find_map(|line| {
                    line.to_ascii_lowercase()
                        .strip_prefix("content-length:")
                        .map(|v| v.trim().parse::<usize>().unwrap())
                })
                .unwrap_or(0);
            while bytes.len() < end + length {
                let n = socket.read(&mut chunk).await.unwrap();
                assert!(n > 0);
                bytes.extend_from_slice(&chunk[..n]);
            }
            if expected.starts_with("POST") {
                let request: Value = serde_json::from_slice(&bytes[end..end + length]).unwrap();
                assert_eq!(request, json!({"chat_ids":[ID]}));
            }
            let body = body.to_string();
            let delayed = if expected.starts_with("GET /v1/drafts/") {
                delay.take()
            } else {
                None
            };
            let cookie = if delayed.is_some() {
                "canonical-rotated-cookie"
            } else {
                "rotated-cookie"
            };
            socket.write_all(format!("HTTP/1.1 {status} Fixture\r\nContent-Type: application/json\r\nContent-Length: {}\r\nSet-Cookie: auth_refresh_token={cookie}; HttpOnly\r\nConnection: close\r\n\r\n",body.len()).as_bytes()).await.unwrap();
            if let Some((headers_sent, release_body)) = delayed {
                headers_sent.send(()).unwrap();
                release_body.await.unwrap();
            }
            let written = socket.write_all(body.as_bytes()).await;
            // Session rejection is authoritative at headers; the client may
            // close without consuming its deliberately delayed body.
            if status != 401 {
                written.unwrap();
            }
        }
    });
    (api, task)
}
fn metadata(status: u16) -> Reply {
    (
        "POST /v1/chats/metadata/batch ",
        status,
        json!({"detail":"not available"}),
    )
}
fn canonical(draft: Value) -> Reply {
    (
        "GET /v1/drafts/11111111-1111-4111-8111-111111111111 ",
        200,
        json!({"draft":draft}),
    )
}

#[tokio::test]
async fn orphan_draft_opens_with_rotated_credentials_without_any_object_key_or_history_read() {
    let draft = draft();
    let (api, server) = spawn_server(vec![metadata(404), canonical(draft.clone())]).await;
    let mut client = make_client(&api, &draft);
    let chat = client.open_chat(ID).await.unwrap();
    assert_eq!(chat.id, ID);
    assert_eq!(chat.title, "Private preview");
    assert!(chat.messages.is_empty());
    assert_eq!(
        client.session().unwrap().cookies["auth_refresh_token"],
        "rotated-cookie"
    );
    assert!(client.chat_key(&client.chats[ID], &[7; 32]).is_err());
    assert!(client.wrappers.is_empty());
    let snapshot = client.ciphertext_snapshot().to_string();
    assert!(!snapshot.contains("Private preview"));
    assert!(!snapshot.contains("Private full draft"));
    server.await.unwrap();
}

#[tokio::test]
async fn metadata_errors_other_than_exact_404_never_read_a_draft() {
    for status in [400, 401, 403, 410, 422] {
        let draft = draft();
        let (api, server) = spawn_server(vec![metadata(status)]).await;
        let mut client = make_client(&api, &draft);
        let error = client.open_chat(ID).await.unwrap_err();
        match status {
            401 => {
                assert!(matches!(error, Error::Expired));
                assert!(client.session().is_none());
            }
            403 => assert!(matches!(error, Error::Forbidden)),
            _ => assert!(matches!(error, Error::Invalid(_))),
        }
        server.await.unwrap();
    }
}

#[tokio::test]
async fn known_draft_scope_and_owner_are_required_before_canonical_draft_read() {
    for case in [
        "unknown",
        "owner",
        "team-row",
        "direct",
        "saved-key",
        "messages",
        "wrapper",
        "owner-type",
        "team-type",
        "visibility",
        "key-type",
    ] {
        let draft = draft();
        let (api, server) = spawn_server(vec![metadata(404)]).await;
        let mut client = make_client(&api, &draft);
        match case {
            "unknown" => {
                client.chats.clear();
            }
            "owner" => client.chats.get_mut(ID).unwrap()["user_id"] = json!("another-owner"),
            "team-row" => {
                client.chats.get_mut(ID).unwrap()["hashed_team_id"] = json!(sha256("team"))
            }
            "direct" => client.chats.get_mut(ID).unwrap()["chat_visibility"] = json!("direct"),
            "saved-key" => {
                client.chats.get_mut(ID).unwrap()["encrypted_chat_key"] = json!("not-a-draft")
            }
            "messages" => client.chats.get_mut(ID).unwrap()["messages_v"] = json!(1),
            "wrapper" => client
                .wrappers
                .push(json!({"hashed_chat_id":sha256(ID),"key_type":"master"})),
            "owner-type" => client.chats.get_mut(ID).unwrap()["user_id"] = json!(42),
            "team-type" => client.chats.get_mut(ID).unwrap()["team_id"] = json!(false),
            "visibility" => client.chats.get_mut(ID).unwrap()["chat_visibility"] = json!("team"),
            "key-type" => client.chats.get_mut(ID).unwrap()["encrypted_chat_key"] = json!(42),
            _ => unreachable!(),
        }
        assert!(client.open_chat(ID).await.is_err(), "{case}");
        server.await.unwrap();
    }
    let draft = draft();
    let (api, server) = spawn_server(vec![(
        "POST /v1/chats/metadata/batch?team_id=33333333-3333-4333-8333-333333333333 ",
        404,
        json!({}),
    )])
    .await;
    let mut client = make_client(&api, &draft);
    client.session.as_mut().unwrap().active_team_id =
        Some("33333333-3333-4333-8333-333333333333".into());
    assert!(matches!(client.open_chat(ID).await, Err(Error::Invalid(_))));
    server.await.unwrap();
}

#[tokio::test]
async fn canonical_draft_identity_version_and_all_ciphertexts_are_validated() {
    for case in [
        "id",
        "owner",
        "team",
        "key",
        "version-zero",
        "version-type",
        "version-old",
        "same-version-change",
        "markdown",
        "preview",
        "preview-type",
        "owner-type",
        "visibility",
        "key-type",
    ] {
        let draft = draft();
        let mut response = draft.clone();
        match case {
            "id" => response["chat_id"] = json!(OWNER),
            "owner" => response["user_id"] = json!("another-owner"),
            "team" => response["team_id"] = json!(OWNER),
            "key" => response["encrypted_chat_key"] = json!("unexpected-key"),
            "version-zero" => response["draft_v"] = json!(0),
            "version-type" => response["draft_v"] = json!("2"),
            "version-old" => response["draft_v"] = json!(1),
            "same-version-change" => {
                response["encrypted_draft_md"] =
                    json!(crypto::encrypt_combined("other", &[7; 32]).unwrap())
            }
            "markdown" => {
                response["draft_v"] = json!(3);
                response["encrypted_draft_md"] =
                    json!(crypto::encrypt_combined("wrong key", &[9; 32]).unwrap());
            }
            "preview" => {
                response["draft_v"] = json!(3);
                response["encrypted_draft_preview"] =
                    json!(crypto::encrypt_combined("wrong key", &[9; 32]).unwrap())
            }
            "preview-type" => response["encrypted_draft_preview"] = json!(42),
            "owner-type" => response["user_id"] = json!(42),
            "visibility" => response["chat_visibility"] = json!("team"),
            "key-type" => response["encrypted_chat_key"] = json!(42),
            _ => unreachable!(),
        }
        let (api, server) = spawn_server(vec![metadata(404), canonical(response)]).await;
        let mut client = make_client(&api, &draft);
        let before = client.ciphertext_snapshot();
        assert!(client.open_chat(ID).await.is_err(), "{case}");
        assert_eq!(client.ciphertext_snapshot(), before);
        server.await.unwrap();
    }
}

#[tokio::test]
async fn same_version_preview_change_or_removal_is_a_conflict_but_absent_and_null_agree() {
    for case in ["changed", "null", "omitted"] {
        let draft = draft();
        let mut response = draft.clone();
        match case {
            "changed" => {
                response["encrypted_draft_preview"] =
                    json!(crypto::encrypt_combined("Different valid preview", &[7; 32]).unwrap())
            }
            "null" => response["encrypted_draft_preview"] = Value::Null,
            "omitted" => {
                response
                    .as_object_mut()
                    .unwrap()
                    .remove("encrypted_draft_preview");
            }
            _ => unreachable!(),
        }
        let (api, server) = spawn_server(vec![metadata(404), canonical(response)]).await;
        let mut client = make_client(&api, &draft);
        let before = client.ciphertext_snapshot();
        assert!(
            matches!(client.open_chat(ID).await, Err(Error::Conflict)),
            "{case}"
        );
        assert_eq!(client.ciphertext_snapshot(), before);
        server.await.unwrap();
    }
    for omitted_cache in [false, true] {
        let mut draft = draft();
        draft["encrypted_draft_preview"] = Value::Null;
        let mut response = draft.clone();
        if !omitted_cache {
            response
                .as_object_mut()
                .unwrap()
                .remove("encrypted_draft_preview");
        }
        let (api, server) = spawn_server(vec![metadata(404), canonical(response)]).await;
        let mut client = make_client(&api, &draft);
        if omitted_cache {
            client
                .chats
                .get_mut(ID)
                .unwrap()
                .as_object_mut()
                .unwrap()
                .remove("encrypted_draft_preview");
        }
        assert_eq!(
            client.open_chat(ID).await.unwrap().title,
            "Private full draft"
        );
        server.await.unwrap();
    }
}

#[tokio::test]
async fn cancellation_during_canonical_body_never_decrypts_publishes_or_deletes_a_draft() {
    for case in ["draft", "deleted", "expired"] {
        let draft = draft();
        let response = if case == "draft" {
            draft.clone()
        } else {
            Value::Null
        };
        let (headers_sent, headers_received) = tokio::sync::oneshot::channel();
        let (release_body, body_released) = tokio::sync::oneshot::channel();
        let mut reply = canonical(response);
        if case == "expired" {
            reply.1 = 401;
        }
        let (api, server) = spawn_server_inner(
            vec![metadata(404), reply],
            Some((headers_sent, body_released)),
        )
        .await;
        let mut client = make_client(&api, &draft);
        client.history.insert(ID.into(), vec![]);
        client.active_chat = Some(ID.into());
        let before = client.ciphertext_snapshot();
        let cancel = CancellationToken::new();
        client.set_operation_cancel(cancel.clone());
        let operation = tokio::spawn(async move {
            let result = client.open_chat(ID).await;
            (client, result)
        });
        tokio::time::timeout(Duration::from_secs(5), headers_received)
            .await
            .unwrap()
            .unwrap();
        cancel.cancel();
        release_body.send(()).unwrap();
        let (client, result) = operation.await.unwrap();
        if case == "expired" {
            assert!(matches!(result, Err(Error::Expired)));
            assert!(client.session().is_none());
            assert!(client.chats.is_empty());
            assert!(client.history.is_empty());
            assert!(client.active_chat.is_none());
        } else {
            assert!(matches!(result, Err(Error::Cancelled)));
            assert_eq!(client.ciphertext_snapshot(), before);
            assert_eq!(client.active_chat.as_deref(), Some(ID));
            assert_eq!(
                client.session().unwrap().cookies["auth_refresh_token"],
                "canonical-rotated-cookie"
            );
        }
        server.await.unwrap();
    }
}

#[tokio::test]
async fn canonical_unauthorized_response_clears_session_and_cached_drafts() {
    let draft = draft();
    let (api, server) = spawn_server(vec![
        metadata(404),
        (canonical(Value::Null).0, 401, json!({})),
    ])
    .await;
    let mut client = make_client(&api, &draft);
    assert!(matches!(client.open_chat(ID).await, Err(Error::Expired)));
    assert!(client.session().is_none());
    assert!(client.chats.is_empty());
    assert!(client.history.is_empty());
    server.await.unwrap();
}

#[tokio::test]
async fn deleted_draft_is_removed_and_newer_canonical_ciphertext_replaces_stale_ciphertext() {
    let draft = draft();
    let (api, server) = spawn_server(vec![metadata(404), canonical(Value::Null)]).await;
    let mut client = make_client(&api, &draft);
    client.history.insert(ID.into(), vec![]);
    client.active_chat = Some(ID.into());
    assert!(client.open_chat(ID).await.is_err());
    assert!(!client.chats.contains_key(ID));
    assert!(!client.history.contains_key(ID));
    assert!(client.active_chat.is_none());
    server.await.unwrap();
    let mut newer = draft.clone();
    newer["draft_v"] = json!(3);
    newer["encrypted_draft_md"] = json!(crypto::encrypt_combined("new body", &[7; 32]).unwrap());
    newer["encrypted_draft_preview"] = Value::Null;
    let (api, server) = spawn_server(vec![metadata(404), canonical(newer.clone())]).await;
    let mut client = make_client(&api, &draft);
    assert_eq!(client.open_chat(ID).await.unwrap().title, "new body");
    assert_eq!(client.chats[ID]["draft_v"], 3);
    server.await.unwrap();
}

#[tokio::test]
async fn concurrent_promotion_uses_canonical_object_key_and_messages_not_the_draft_fallback() {
    let draft = draft();
    let key = [8; 32];
    let saved = json!({"id":ID,"messages_v":1,"encrypted_chat_key":crypto::encrypt_bytes(&key,&[7;32]).unwrap(),"encrypted_title":crypto::encrypt_combined("Saved title",&key).unwrap()});
    let message = json!({"id":OWNER,"chat_id":ID,"role":"user","encrypted_content":crypto::encrypt_combined("Saved message",&key).unwrap()});
    let (api, server) = spawn_server(vec![
        (
            "POST /v1/chats/metadata/batch ",
            200,
            json!({"chats":[saved]}),
        ),
        (
            "GET /v1/chats/11111111-1111-4111-8111-111111111111/messages/window?",
            200,
            json!({"messages":[message],"has_more_before":false}),
        ),
    ])
    .await;
    let mut client = make_client(&api, &draft);
    let opened = client.open_chat(ID).await.unwrap();
    assert_eq!(opened.title, "Saved title");
    assert_eq!(opened.messages.len(), 1);
    assert_eq!(opened.messages[0].content, "Saved message");
    assert_eq!(*client.chat_key(&client.chats[ID], &[7; 32]).unwrap(), key);
    server.await.unwrap();
}
