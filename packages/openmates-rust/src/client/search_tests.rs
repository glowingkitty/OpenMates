// contract-test: supporting surface=cli assertions=chats.messages.client-encrypted
use super::*;
use futures_util::{SinkExt, StreamExt};
use tokio::io::{AsyncReadExt, AsyncWriteExt};
use tokio_tungstenite::tungstenite::Message as Frame;
const ID: &str = "11111111-1111-4111-8111-111111111111";
const OTHER: &str = "22222222-2222-4222-8222-222222222222";
const TEAM: &str = "33333333-3333-4333-8333-333333333333";

fn client(api: &str, team: bool) -> Client {
    let mut session = super::super::sdk_boundary_tests::session();
    session.api_url = api.into();
    session.master_key = zeroize::Zeroizing::new([7; 32]);
    session.cookies = BTreeMap::from([("auth_refresh_token".into(), "before".into())]);
    session.active_team_id = team.then(|| TEAM.into());
    let mut client = Client::new(api, Some(session)).unwrap();
    client.user = json!({"id":"owner"});
    if team {
        client.team_key = Some((TEAM.into(), zeroize::Zeroizing::new([9; 32])));
    }
    client
}
fn row(id: &str, title: &str, updated: u64) -> Value {
    json!({"id":id,"encrypted_chat_key":crypto::encrypt_bytes(&[8;32],&[7;32]).unwrap(),
        "encrypted_title":crypto::encrypt_combined(title,&[8;32]).unwrap(),
        "encrypted_chat_summary":crypto::encrypt_combined("Résumé across Madrid",&[8;32]).unwrap(),
        "encrypted_category":crypto::encrypt_combined("software_development",&[8;32]).unwrap(),
        "encrypted_slug":crypto::encrypt_combined("not-a-cookie-search-field",&[8;32]).unwrap(),
        "encrypted_active_focus_id":crypto::encrypt_combined("focus-fixture",&[8;32]).unwrap(),
        "last_edited_overall_timestamp":updated,"created_at":100,"updated_at":"1700000000123",
        "messages":[{"content":"unsearched body needle"}],"pinned":true})
}
#[test]
fn cookie_fields_match_case_insensitively_without_message_slug_or_placeholder_search() {
    let client = client("http://127.0.0.1:1", false);
    let row = row(ID, "Rocket notes", 200);
    let item = client.search_chat_row(&row, &[7; 32]).unwrap();
    for q in [
        "rocket",
        "résumé",
        "madrid",
        "software_development",
        "sophia",
        &ID[..8],
    ] {
        assert!(matches_query(&item, q), "{q}");
    }
    for q in [
        "unsearched body needle",
        "not-a-cookie-search-field",
        "locked chat",
    ] {
        assert!(!matches_query(&item, q));
    }
    assert_eq!(item["shortId"], &ID[..8]);
    assert_eq!(item["mateName"], "Sophia");
    assert_eq!(item["metadataUpdatedAt"], 1700000000.0);
    assert_eq!(item["updatedAt"], 200);
    assert_eq!(item["activeFocusId"], "focus-fixture");
    assert_eq!(item["slug"], "not-a-cookie-search-field");
    assert!(item.get("participantUserHashes").is_none());
    assert!(client.chats.is_empty());
    assert!(client.history.is_empty());
}
#[test]
fn drafts_and_locked_rows_expose_real_null_metadata_and_never_fall_back_to_master() {
    let client = client("http://127.0.0.1:1", false);
    let draft = json!({"id":ID,"encrypted_draft_md":crypto::encrypt_combined("Private draft contents",&[7;32]).unwrap(),"encrypted_draft_preview":crypto::encrypt_combined("  Private\n draft\u{feff}preview  ",&[7;32]).unwrap()});
    let item = client.search_chat_row(&draft, &[7; 32]).unwrap();
    assert_eq!(item["title"], Value::Null);
    assert_eq!(item["draftPreview"], "Private draft preview");
    assert_eq!(item["hasDraft"], true);
    assert!(!matches_query(&item, "private draft"));
    assert!(matches_query(&item, &ID[..8]));
    let mut locked = row(ID, "Unavailable", 200);
    locked["encrypted_chat_key"] = json!(crypto::encrypt_bytes(&[8; 32], &[6; 32]).unwrap());
    locked["encrypted_title"] =
        json!(crypto::encrypt_combined("Master-key decoy", &[7; 32]).unwrap());
    locked["encrypted_draft_md"] = draft["encrypted_draft_md"].clone();
    let item = client.search_chat_row(&locked, &[7; 32]).unwrap();
    assert_eq!(item["isHiddenCandidate"], true);
    assert_eq!(item["draftPreview"], Value::Null);
    for field in ["title", "summary", "category", "mateName"] {
        assert_eq!(item[field], Value::Null);
    }
    assert!(!matches_query(&item, "master-key decoy"));
    assert!(matches_query(&item, &ID[..8]));
}
#[test]
fn scope_mismatches_fail_before_any_id_or_plaintext_result() {
    let personal = client("http://127.0.0.1:1", false);
    let team = client("http://127.0.0.1:1", true);
    let mut row = row(ID, "Foreign", 200);
    row["hashed_team_id"] = json!(sha256(TEAM));
    assert!(matches!(
        personal.search_chat_row(&row, &[7; 32]),
        Err(Error::Forbidden)
    ));
    row["hashed_team_id"] = json!(sha256(OTHER));
    assert!(matches!(
        team.search_chat_row(&row, &[9; 32]),
        Err(Error::Forbidden)
    ));
    assert!(draft_preview(&"🙂".repeat(101)).encode_utf16().count() <= 200);
    row["hashed_team_id"] = json!(sha256(TEAM));
    row["team_id"] = json!(TEAM);
    row["chat_visibility"] = json!("direct");
    row["participant_user_hashes"] = json!([sha256("outsider"), sha256("other")]);
    assert!(matches!(
        team.search_chat_row(&row, &[9; 32]),
        Err(Error::Forbidden)
    ));
    row["participant_user_hashes"] = json!([sha256("owner"), sha256("other")]);
    let locked = team.search_chat_row(&row, &[9; 32]).unwrap();
    assert_eq!(locked["title"], Value::Null);
    assert_eq!(locked["chatVisibility"], "direct");
}
async fn read_http(stream: &mut tokio::net::TcpStream) -> (String, Value) {
    let mut data = vec![];
    let mut chunk = [0; 4096];
    let end = loop {
        let n = stream.read(&mut chunk).await.unwrap();
        assert!(n > 0);
        data.extend_from_slice(&chunk[..n]);
        if let Some(end) = data.windows(4).position(|v| v == b"\r\n\r\n") {
            break end + 4;
        }
    };
    let head = String::from_utf8(data[..end].to_vec()).unwrap();
    let length = head
        .lines()
        .find_map(|l| {
            l.to_ascii_lowercase()
                .strip_prefix("content-length:")
                .map(|v| v.trim().parse::<usize>().unwrap())
        })
        .unwrap_or(0);
    while data.len() < end + length {
        let n = stream.read(&mut chunk).await.unwrap();
        assert!(n > 0);
        data.extend_from_slice(&chunk[..n]);
    }
    (
        head,
        if length == 0 {
            Value::Null
        } else {
            serde_json::from_slice(&data[end..end + length]).unwrap()
        },
    )
}
async fn http(listener: &tokio::net::TcpListener, path: &str, result: Value) {
    let (mut stream, _) = listener.accept().await.unwrap();
    let (head, _) = read_http(&mut stream).await;
    assert!(head.starts_with(path));
    assert!(head.to_ascii_lowercase().contains("x-openmates-sdk: rust"));
    let result = result.to_string();
    stream.write_all(format!("HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: {}\r\nSet-Cookie: auth_refresh_token=rotated; HttpOnly\r\nConnection: close\r\n\r\n{result}",result.len()).as_bytes()).await.unwrap();
}
async fn peer(
    team: bool,
    rows: Vec<Value>,
    hydrate: Option<Vec<Value>>,
    cancel: Option<CancellationToken>,
) -> (String, tokio::task::JoinHandle<()>) {
    let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
    let api = format!("http://{}", listener.local_addr().unwrap());
    let task = tokio::spawn(async move {
        let auth = json!({"success":true,"ws_token":"token","user":{"id":"owner"}});
        if team {
            http(&listener, "POST /v1/auth/session ", auth.clone()).await;
            http(
                &listener,
                "GET /v1/account/chat-encryption-key ",
                json!({"key":null}),
            )
            .await;
        }
        http(&listener, "POST /v1/auth/session ", auth).await;
        let (stream, _) = listener.accept().await.unwrap();
        let mut ws = tokio_tungstenite::accept_async(stream).await.unwrap();
        let lifecycle: Value =
            serde_json::from_str(ws.next().await.unwrap().unwrap().to_text().unwrap()).unwrap();
        assert_eq!(lifecycle["type"], "native_client_lifecycle");
        let sync: Value =
            serde_json::from_str(ws.next().await.unwrap().unwrap().to_text().unwrap()).unwrap();
        assert_eq!(sync["type"], "phased_sync_request");
        assert_eq!(sync["payload"]["phase"], "all");
        assert_eq!(
            sync["payload"]["team_id"],
            if team { json!(TEAM) } else { Value::Null }
        );
        ws.send(Frame::Text(json!({"type":"phase_2_last_20_chats_ready","payload":{"chats":rows.into_iter().map(|row|json!({"chat_details":row})).collect::<Vec<_>>()}}).to_string().into())).await.unwrap();
        if let Some(cancel) = cancel {
            cancel.cancel();
            return;
        }
        for (kind, payload) in [
            ("phased_sync_complete", json!({"phase":"all"})),
            (
                "recovery_outputs_discovery_complete",
                json!({"status":"completed"}),
            ),
        ] {
            ws.send(Frame::Text(
                json!({"type":kind,"payload":payload}).to_string().into(),
            ))
            .await
            .unwrap();
        }
        assert!(matches!(ws.next().await.unwrap().unwrap(), Frame::Close(_)));
        if let Some(hydrated) = hydrate {
            let (mut stream, _) = listener.accept().await.unwrap();
            let (head, body) = read_http(&mut stream).await;
            assert!(head.starts_with(&format!("POST /v1/chats/metadata/batch?team_id={TEAM} ")));
            assert!(
                head.to_ascii_lowercase()
                    .contains("auth_refresh_token=rotated")
            );
            assert_eq!(body, json!({"chat_ids":[ID,OTHER]}));
            let body = json!({"chats":hydrated}).to_string();
            stream.write_all(format!("HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: {}\r\nConnection: close\r\n\r\n{body}",body.len()).as_bytes()).await.unwrap();
        }
    });
    (api, task)
}
#[tokio::test]
async fn search_uses_authenticated_metadata_only_ordering_and_rotated_cookies() {
    let rows = vec![row(ID, "Madrid first", 1), row(OTHER, "MADRID latest", 9)];
    let (api, server) = peer(false, rows, None, None).await;
    let mut client = client(&api, false);
    let result = tokio::time::timeout(
        Duration::from_secs(5),
        client.search_chats("\u{feff}  MaDRid \u{feff}"),
    )
    .await
    .unwrap()
    .unwrap();
    assert_eq!(
        result.iter().map(|r| text(r, "id")).collect::<Vec<_>>(),
        vec![OTHER, ID]
    );
    assert_eq!(
        client.session().unwrap().cookies["auth_refresh_token"],
        "rotated"
    );
    assert!(
        !client
            .ciphertext_snapshot()
            .to_string()
            .contains("Madrid first")
    );
    assert!(client.history.is_empty());
    server.await.unwrap();
}
#[tokio::test]
async fn team_search_hydrates_only_matching_team_wrappers_and_omits_revoked_rows() {
    let rows = vec![row(ID, "Madrid Team", 1), row(OTHER, "Madrid revoked", 9)];
    let mut hydrated = rows[0].clone();
    hydrated["team_id"] = json!(TEAM);
    hydrated["encrypted_chat_key"] = json!(crypto::encrypt_bytes(&[8; 32], &[9; 32]).unwrap());
    hydrated["chat_key_wrappers"] = json!([{"hashed_chat_id":sha256(ID),"key_type":"team","hashed_team_id":sha256(TEAM),"encrypted_chat_key":hydrated["encrypted_chat_key"]}]);
    let (api, server) = peer(true, rows, Some(vec![hydrated]), None).await;
    let mut client = client(&api, true);
    let result = tokio::time::timeout(Duration::from_secs(5), client.search_chats("madrid"))
        .await
        .unwrap()
        .unwrap();
    assert_eq!(result.len(), 1);
    assert_eq!(result[0]["id"], ID);
    assert_eq!(result[0]["title"], "Madrid Team");
    assert_eq!(result[0]["chatVisibility"], "team");
    server.await.unwrap();
}
#[tokio::test]
async fn cancellation_after_metadata_preserves_prior_snapshot_and_rotated_credentials() {
    let cancel = CancellationToken::new();
    let (api, server) = peer(
        false,
        vec![row(ID, "New private row", 1)],
        None,
        Some(cancel.clone()),
    )
    .await;
    let mut client = client(&api, false);
    client
        .chats
        .insert(OTHER.into(), row(OTHER, "Old private row", 2));
    let snapshot = client.ciphertext_snapshot();
    client.set_operation_cancel(cancel);
    assert!(matches!(
        client.search_chats("private").await,
        Err(Error::Cancelled)
    ));
    assert_eq!(client.ciphertext_snapshot(), snapshot);
    assert_eq!(
        client.session().unwrap().cookies["auth_refresh_token"],
        "rotated"
    );
    server.await.unwrap();
}
#[tokio::test]
async fn empty_query_and_pre_cancelled_search_do_not_open_transport() {
    let mut client = client("http://127.0.0.1:1", false);
    assert!(matches!(
        client.search_chats(" \n ").await,
        Err(Error::Invalid(_))
    ));
    let cancel = CancellationToken::new();
    cancel.cancel();
    client.set_operation_cancel(cancel);
    assert!(matches!(
        client.search_chats("valid").await,
        Err(Error::Cancelled)
    ));
}
