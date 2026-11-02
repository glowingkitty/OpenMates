// contract-test: supporting surface=sdk assertions=sdk.library.explicit-headless,sdk.encryption.local-only
use super::*;
use futures_util::{SinkExt, StreamExt};
use std::sync::{Arc, Mutex};
use tokio::io::{AsyncReadExt, AsyncWriteExt};
const ID: &str = "11111111-1111-4111-8111-111111111111";
fn draft(version: u64) -> Value {
    json!({"id":ID,"user_id":"synthetic-owner","messages_v":7,"draft_v":version,"encrypted_draft_md":crypto::encrypt_combined("Synthetic passive draft",&[1;32]).unwrap(),"encrypted_draft_preview":null})
}
fn client(api: &str) -> Client {
    let mut session = crate::client::sdk_boundary_tests::session();
    session.api_url = api.into();
    session
        .cookies
        .insert("auth_refresh_token".into(), "synthetic-cookie".into());
    let mut c = Client::new(api, Some(session)).unwrap();
    c.user = json!({"id":"synthetic-owner"});
    c.chats.insert(ID.into(), draft(3));
    c.history.insert(
        ID.into(),
        vec![json!({"id":"saved-message","encrypted_content":"opaque-history"})],
    );
    c.active_chat = Some(ID.into());
    c
}
async fn request(stream: &mut tokio::net::TcpStream) -> String {
    let mut data = vec![];
    loop {
        let mut buf = [0; 4096];
        let n = stream.read(&mut buf).await.unwrap();
        assert!(n > 0 && data.len() + n <= 65536);
        data.extend_from_slice(&buf[..n]);
        if let Some(end) = data.windows(4).position(|v| v == b"\r\n\r\n") {
            let headers = String::from_utf8_lossy(&data[..end]);
            let len = headers
                .lines()
                .find_map(|line| {
                    line.to_ascii_lowercase()
                        .strip_prefix("content-length:")
                        .map(|v| v.trim().parse::<usize>().unwrap())
                })
                .unwrap_or(0);
            if data.len() == end + 4 + len {
                return String::from_utf8(data).unwrap();
            }
        }
    }
}
async fn respond(stream: &mut tokio::net::TcpStream, status: u16, body: Value) {
    let body = body.to_string();
    stream.write_all(format!("HTTP/1.1 {status} Fixture\r\nContent-Type: application/json\r\nContent-Length: {}\r\nConnection: close\r\n\r\n{body}",body.len()).as_bytes()).await.unwrap();
}
struct Peer {
    api: String,
    seen: Arc<Mutex<Vec<String>>>,
    ready: Arc<tokio::sync::Notify>,
    release: Arc<tokio::sync::Notify>,
    task: tokio::task::JoinHandle<()>,
}
impl Peer {
    // mode0 success,1 final version changed,2 foreign metadata owner,
    // mode3 cancellation barrier before final version; mode4 cold metadata list.
    async fn start(mode: u8) -> Self {
        let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
        let api = format!("http://{}", listener.local_addr().unwrap());
        let seen = Arc::new(Mutex::new(Vec::new()));
        let ready = Arc::new(tokio::sync::Notify::new());
        let release = Arc::new(tokio::sync::Notify::new());
        let (s, r, b) = (seen.clone(), ready.clone(), release.clone());
        let task = tokio::spawn(async move {
            if mode != 4 {
                let (mut stream, _) = listener.accept().await.unwrap();
                let req = request(&mut stream).await;
                assert!(req.starts_with(&format!("GET /v1/drafts/{ID} ")));
                s.lock().unwrap().push("draft-rest-network-failure".into());
                drop(stream);
            }
            let (mut stream, _) = listener.accept().await.unwrap();
            let req = request(&mut stream).await;
            assert!(req.starts_with("POST /v1/auth/session "));
            s.lock().unwrap().push("auth".into());
            respond(
                &mut stream,
                200,
                json!({"success":true,"ws_token":"synthetic","user":{"id":"synthetic-owner"}}),
            )
            .await;
            drop(stream);
            let (stream, _) = listener.accept().await.unwrap();
            let mut ws = tokio_tungstenite::accept_hdr_async(
                stream,
                |req: &tokio_tungstenite::tungstenite::handshake::server::Request, response| {
                    assert!(req.uri().path() == "/v1/ws");
                    let query = url::form_urlencoded::parse(req.uri().query().unwrap().as_bytes())
                        .collect::<BTreeMap<_, _>>();
                    let capabilities = query.get("client_capabilities").unwrap();
                    assert!(
                        !capabilities.contains("task_update_jobs")
                            && !capabilities.contains("chat_metadata_recovery")
                    );
                    assert!(req.headers().get("authorization").is_none());
                    Ok(response)
                },
            )
            .await
            .unwrap();
            s.lock().unwrap().push("ws".into());
            let mut versions = 0;
            while let Some(frame) = ws.next().await {
                let frame = match frame {
                    Ok(frame) => frame,
                    Err(_) => break,
                };
                if frame.is_close() {
                    break;
                }
                let Some(raw) = frame.to_text().ok() else {
                    continue;
                };
                let frame: Value = serde_json::from_str(raw).unwrap();
                let kind = frame["type"].as_str().unwrap();
                s.lock().unwrap().push(kind.into());
                match kind {
                    "native_client_lifecycle" => {}
                    "get_draft_versions" => {
                        versions += 1;
                        assert_eq!(
                            frame["payload"]["chats"],
                            json!([{"chat_id":ID,"client_draft_v":3}])
                        );
                        if mode == 3 && versions == 2 {
                            r.notify_one();
                            b.notified().await;
                        }
                        let version = if versions == 1 {
                            3
                        } else if mode == 1 {
                            5
                        } else {
                            4
                        };
                        let response = json!({"type":"draft_versions_response","payload":{"versions":{ID:version}}});
                        if ws
                            .send(tungstenite::Message::Text(response.to_string().into()))
                            .await
                            .is_err()
                        {
                            break;
                        }
                    }
                    "phased_sync_request" => {
                        let p = &frame["payload"];
                        assert_eq!(p["phase"], "phase2");
                        assert_eq!(p["client_chat_ids"], json!([]));
                        assert_eq!(p["client_chat_versions"], json!({}));
                        assert!(p.get("team_id").is_none());
                        if mode != 4 {
                            assert_eq!(p["refresh_chat_ids"], json!([ID]));
                        }
                        let epoch = p["context_epoch"].as_u64().unwrap();
                        assert!(epoch >= 2);
                        let mut row = draft(4);
                        if mode == 2 {
                            row["user_id"] = json!("other-owner");
                        }
                        let frames = [
                            json!({"type":"phased_sync_complete","payload":{"phase":"all","context_epoch":0}}),
                            json!({"type":"phase_2_last_20_chats_ready","payload":{"chats":[{"chat_details":row}],"phase":"phase2","context_epoch":epoch,"team_id":null}}),
                            json!({"type":"phased_sync_complete","payload":{"phase":"phase2","context_epoch":epoch,"team_id":null}}),
                        ];
                        for response in frames {
                            if ws
                                .send(tungstenite::Message::Text(response.to_string().into()))
                                .await
                                .is_err()
                            {
                                break;
                            }
                        }
                    }
                    other => panic!("Unexpected side effect or content request: {other}"),
                }
            }
            let _ = ws.close(None).await;
        });
        Self {
            api,
            seen,
            ready,
            release,
            task,
        }
    }
}
#[tokio::test]
async fn real_network_fallback_keeps_same_cookie_owner_one_socket_and_no_message_sync() {
    tokio::time::timeout(Duration::from_secs(8), async {
        let peer = Peer::start(0).await;
        let mut c = client(&peer.api);
        let old_history = c.history.clone();
        let old_wrappers = c.wrappers.clone();
        let d = c.get_draft(ID, true).await.unwrap().unwrap();
        assert_eq!(d.markdown, "Synthetic passive draft");
        assert_eq!(d.encrypted.draft_v, 4);
        assert_eq!(c.history, old_history);
        assert_eq!(c.wrappers, old_wrappers);
        assert_eq!(c.chats[ID]["messages_v"], 7);
        assert!(
            !c.ciphertext_snapshot()
                .to_string()
                .contains("Synthetic passive draft")
        );
        peer.task.await.unwrap();
        assert_eq!(
            *peer.seen.lock().unwrap(),
            vec![
                "draft-rest-network-failure",
                "auth",
                "ws",
                "native_client_lifecycle",
                "get_draft_versions",
                "phased_sync_request",
                "get_draft_versions"
            ]
        );
    })
    .await
    .unwrap();
}
#[tokio::test]
async fn remote_version_change_and_owner_mismatch_never_commit_metadata() {
    for mode in [1, 2] {
        tokio::time::timeout(Duration::from_secs(8), async {
            let peer = Peer::start(mode).await;
            let mut c = client(&peer.api);
            let before = c.chats.clone();
            let result = c.get_draft(ID, true).await;
            assert!(matches!(result, Err(Error::Conflict | Error::Forbidden)));
            assert_eq!(c.chats, before);
            peer.task.await.unwrap();
        })
        .await
        .unwrap();
    }
}
#[tokio::test]
async fn cancellation_between_metadata_and_final_version_never_publishes_draft() {
    tokio::time::timeout(Duration::from_secs(8),async{
        let peer=Peer::start(3).await;let mut c=client(&peer.api);let before=c.chats.clone();let cancel=CancellationToken::new();c.set_operation_cancel(cancel.clone());
        let result={let future=c.get_draft(ID,true);tokio::pin!(future);tokio::select!{_ = peer.ready.notified()=>{},result=&mut future=>panic!("Unexpected early result: {}",result.is_ok())};cancel.cancel();peer.release.notify_one();future.await};
        assert!(matches!(result,Err(Error::Cancelled)));assert_eq!(c.chats,before);peer.task.await.unwrap();
    }).await.unwrap();
}
#[tokio::test]
async fn cold_list_reads_only_phase2_and_never_mints_complete_chat_census() {
    tokio::time::timeout(Duration::from_secs(8), async {
        let peer = Peer::start(4).await;
        let mut c = client(&peer.api);
        c.chats.clear();
        let drafts = c.list_drafts(false).await.unwrap();
        assert_eq!(drafts.len(), 1);
        assert_eq!(drafts[0].encrypted.draft_v, 4);
        assert!(!c.may_read_cached_default_chat_inventory(false).unwrap());
        peer.task.await.unwrap();
        assert_eq!(
            *peer.seen.lock().unwrap(),
            vec![
                "auth",
                "ws",
                "native_client_lifecycle",
                "phased_sync_request"
            ]
        );
    })
    .await
    .unwrap();
}
#[test]
fn only_unobserved_network_offline_admits_passive_fallback() {
    assert!(draft_network_fallback(Error::Offline, None));
    for status in [400, 401, 403, 404, 409, 429, 500, 503] {
        assert!(!draft_network_fallback(Error::Offline, Some(status)));
    }
    for error in [
        Error::Expired,
        Error::Authentication,
        Error::Forbidden,
        Error::Cancelled,
        Error::Crypto,
        Error::Protocol,
        Error::Conflict,
    ] {
        assert!(!draft_network_fallback(error, None));
    }
}
#[test]
fn metadata_context_completion_and_sidecars_are_strict() {
    let mut read = DraftMetadataRead::new(23);
    read.accept(
        "phased_sync_complete",
        &json!({"phase":"all","context_epoch":0}),
    )
    .unwrap();
    assert!(!read.complete);
    assert!(
        read.accept(
            "phased_sync_complete",
            &json!({"phase":"phase2","context_epoch":23})
        )
        .is_err()
    );
    let frame = json!({"chats":[{"chat_details":draft(4)}],"phase":"phase2","context_epoch":23});
    read.accept("phase_2_last_20_chats_ready", &frame).unwrap();
    read.accept(
        "phased_sync_complete",
        &json!({"phase":"phase2","context_epoch":23}),
    )
    .unwrap();
    assert!(read.complete && read.rows.contains_key(ID));
    for bad in [
        json!({"phase":"phase2","context_epoch":23,"team_id":"foreign","chats":[]}),
        json!({"phase":"phase2","context_epoch":23,"chats":[],"messages":[{"private":"forbidden"}]}),
        json!({"phase":"phase2","context_epoch":23,"chats":[{"chat_details":draft(4),"messages":[{"private":"forbidden"}]}]}),
    ] {
        assert!(
            DraftMetadataRead::new(23)
                .accept("phase_2_last_20_chats_ready", &bad)
                .is_err()
        );
    }
}
#[test]
fn pure_cache_predicate_preserves_guards_without_decrypting_unrelated_chat() {
    let mut c = client("http://127.0.0.1:9");
    let clock = || CacheClockEvidence::from_platform("boot".into(), 1000, 1000).unwrap();
    c.set_chat_cache_clock_provider(Some(Arc::new(move || Some(clock()))));
    c.chats.insert("22222222-2222-4222-8222-222222222222".into(),json!({"id":"22222222-2222-4222-8222-222222222222","encrypted_title":"intentionally-corrupt-unrelated-title","encrypted_chat_key":"not-decrypted-for-drafts"}));
    c.record_complete_chat_list_at(Some(
        &CacheClockEvidence::from_platform("boot".into(), 1000, 1000).unwrap(),
    ));
    assert!(c.may_read_cached_default_chat_inventory(false).unwrap());
    assert!(!c.may_read_cached_default_chat_inventory(true).unwrap());
    assert_eq!(c.list_cached_drafts().unwrap().len(), 1);
    let fence = DraftReadFence::capture(&c).unwrap();
    c.user = json!({"id":"other-owner"});
    assert!(!c.may_read_cached_default_chat_inventory(false).unwrap());
    assert!(matches!(fence.check(&c), Err(Error::Cancelled)));
    c.user = json!({"id":"synthetic-owner"});
    c.generation += 1;
    assert!(matches!(fence.check(&c), Err(Error::Cancelled)));
}

#[test]
fn shared_passive_protocol_vectors_exercise_real_admission_and_metadata_parser() {
    let fixture: Value = serde_json::from_str(include_str!(
        "../../tests/fixtures/native-drafts-passive-read.json"
    ))
    .unwrap();
    for vector in fixture["rest_failures"].as_array().unwrap() {
        let error = match vector["error"].as_str().unwrap() {
            "offline" => Error::Offline,
            "expired" => Error::Expired,
            "authentication" => Error::Authentication,
            "forbidden" => Error::Forbidden,
            "cancelled" => Error::Cancelled,
            "crypto" => Error::Crypto,
            "conflict" => Error::Conflict,
            "protocol" => Error::Protocol,
            _ => panic!("unknown fixture error"),
        };
        assert_eq!(
            draft_network_fallback(error, vector["http_status"].as_u64().map(|v| v as u16)),
            vector["fallback"].as_bool().unwrap()
        );
    }
    let epoch = fixture["metadata_epoch"].as_u64().unwrap();
    for vector in fixture["metadata_cases"].as_array().unwrap() {
        let mut read = DraftMetadataRead::new(epoch);
        let result = read.accept(vector["kind"].as_str().unwrap(), &vector["payload"]);
        match vector["expect"].as_str().unwrap() {
            "reject" => assert!(result.is_err()),
            "ignored" => {
                result.unwrap();
                assert!(!read.metadata_seen && !read.complete);
            }
            "metadata" => {
                result.unwrap();
                assert!(read.metadata_seen);
                let key = crypto::decode_key(fixture["key_b64"].as_str().unwrap()).unwrap();
                let text = crypto::decrypt_combined(
                    read.rows[ID]["encrypted_draft_md"].as_str().unwrap(),
                    &key,
                )
                .unwrap();
                assert_eq!(text, "Synthetic passive draft");
                assert!(
                    crypto::decrypt_combined(
                        read.rows[ID]["encrypted_draft_md"].as_str().unwrap(),
                        &[2; 32]
                    )
                    .is_err()
                );
            }
            _ => panic!("unknown fixture outcome"),
        }
    }
}

#[test]
fn metadata_deletion_and_failed_multirow_prepare_are_owner_fenced_and_atomic() {
    let c = client("http://127.0.0.1:9");
    let before = c.chats.clone();
    let foreign = BTreeMap::from([(
        ID.into(),
        json!({"id":ID,"user_id":"other-owner","draft_v":0}),
    )]);
    assert!(matches!(
        c.prepare_draft_metadata(&foreign),
        Err(Error::Forbidden)
    ));
    assert_eq!(c.chats, before);
    let mut rows = BTreeMap::from([(ID.into(), draft(4))]);
    rows.insert("22222222-2222-4222-8222-222222222222".into(),json!({"id":"22222222-2222-4222-8222-222222222222","draft_v":4,"encrypted_draft_md":"cipher","user_id":"other-owner"}));
    assert!(c.prepare_draft_metadata(&rows).is_err());
    assert_eq!(c.chats, before);
    let requested = vec![(ID.into(), 3)];
    let staged = c
        .prepare_draft_versions(
            &requested,
            &BTreeMap::from([(ID.into(), 0)]),
            &BTreeMap::from([(ID.into(), 5)]),
        )
        .unwrap();
    assert!(staged[ID].get("encrypted_draft_md").is_none());
    assert_eq!(staged[ID]["draft_v"], 5);
    assert_eq!(c.chats, before);
}

#[test]
fn positive_observations_and_phase2_cleared_floors_never_regress() {
    let mut c = client("http://127.0.0.1:9");
    let requested = vec![(ID.into(), 3)];
    let observed = BTreeMap::from([(ID.into(), 5)]);
    let floors = observed_draft_floors(&requested, &observed, &BTreeMap::new());
    let before = c.chats.clone();
    assert_eq!(floors[ID], 5);
    assert!(matches!(
        c.prepare_draft_metadata_at(&BTreeMap::from([(ID.into(), draft(4))]), &floors, &observed),
        Err(Error::Conflict)
    ));
    assert_eq!(c.chats, before);
    let raised = requested
        .iter()
        .map(|(id, _)| (id.clone(), floors[id]))
        .collect::<Vec<_>>();
    assert!(
        parse_versions(
            &json!({"versions":{ID:4}}),
            &raised,
            &mut BTreeMap::new(),
            &mut BTreeMap::new()
        )
        .is_err()
    );
    let cleared = BTreeMap::from([(
        ID.into(),
        json!({"id":ID,"user_id":"synthetic-owner","draft_v":0,"cleared_draft_v":5}),
    )]);
    let updates = c.prepare_draft_metadata(&cleared).unwrap();
    assert_eq!(updates[ID]["draft_v"], 5);
    assert!(updates[ID].get("encrypted_draft_md").is_none());
    c.chats.extend(updates);
    assert!(matches!(
        c.check_draft_regression(c.chats.get(ID), &draft(4)),
        Err(Error::Conflict)
    ));
    assert!(matches!(
        c.check_draft_regression(c.chats.get(ID), &draft(5)),
        Err(Error::Conflict)
    ));
    assert!(c.check_draft_regression(c.chats.get(ID), &draft(6)).is_ok());
    let retained = BTreeMap::from([(ID.into(), json!({"id":ID,"draft_v":0,"cleared_draft_v":7}))]);
    c.chats.extend(retained);
    assert!(matches!(
        c.check_draft_regression(c.chats.get(ID), &draft(6)),
        Err(Error::Conflict)
    ));
}
#[test]
fn final_plaintext_release_wipes_on_late_cancel_or_identity_change() {
    let mut c = client("http://127.0.0.1:9");
    let cancel = CancellationToken::new();
    c.set_operation_cancel(cancel.clone());
    let fence = DraftReadFence::capture(&c).unwrap();
    let admission = c.draft_read_admission().unwrap();
    let mut decoded = c.render_cached_drafts().unwrap();
    assert!(!decoded[0].markdown.is_empty());
    cancel.cancel();
    assert!(matches!(
        validate_draft_release(&c, &fence, &mut decoded),
        Err(Error::Cancelled)
    ));
    assert!(decoded.iter().all(
        |draft| draft.markdown.is_empty() && draft.preview.as_deref().is_none_or(str::is_empty)
    ));
    assert!(admission.check(&c).is_err());
    assert!(admission.check_credential_scope(&c).is_ok());
    c.set_operation_cancel(CancellationToken::new());
    let fence = DraftReadFence::capture(&c).unwrap();
    let mut decoded = c.render_cached_drafts().unwrap();
    c.user = json!({"id":"other-owner"});
    assert!(validate_draft_release(&c, &fence, &mut decoded).is_err());
    assert!(decoded[0].markdown.is_empty());
}

#[test]
fn shared_version_floor_regressions_are_not_just_cache_version_comparisons() {
    let fixture: Value = serde_json::from_str(include_str!(
        "../../tests/fixtures/native-drafts-passive-read.json"
    ))
    .unwrap();
    for v in fixture["version_floor_cases"].as_array().unwrap() {
        let mut c = client("http://127.0.0.1:9");
        let cached = v["cached"].as_u64().unwrap();
        c.chats.insert(ID.into(), draft(cached));
        if v["cached_absent"] == true {
            c.chats.remove(ID);
        }
        if v["cached_clear"] == true {
            clear_ciphertext(c.chats.get_mut(ID).unwrap()).unwrap();
        }
        if let Some(cleared) = v["cleared"].as_u64() {
            let rows = BTreeMap::from([(
                ID.into(),
                json!({"id":ID,"user_id":"synthetic-owner","draft_v":0,"cleared_draft_v":cleared}),
            )]);
            let updates = c.prepare_draft_metadata(&rows).unwrap();
            c.chats.extend(updates);
        }
        let observed = v["observed"]
            .as_u64()
            .map(|v| BTreeMap::from([(ID.into(), v)]))
            .unwrap_or_default();
        let floors = observed_draft_floors(
            &[(ID.into(), cached_draft_floor(&c.chats[ID]).unwrap())],
            &observed,
            &BTreeMap::new(),
        );
        let rows = BTreeMap::from([(ID.into(), draft(v["metadata"].as_u64().unwrap()))]);
        assert_eq!(
            c.prepare_draft_metadata_at(&rows, &floors, &observed)
                .is_err(),
            v["reject"].as_bool().unwrap()
        );
    }
}

#[test]
fn first_seen_authoritative_tombstones_retain_floor_without_ciphertext_or_census() {
    let mut c = client("http://127.0.0.1:9");
    c.chats.remove(ID);
    let rows = BTreeMap::from([(
        ID.into(),
        json!({"id":ID,"user_id":"synthetic-owner","messages_v":7,"draft_v":0,"cleared_draft_v":6,"encrypted_draft_md":null}),
    )]);
    let updates = c.prepare_draft_metadata(&rows).unwrap();
    assert_eq!(updates[ID]["draft_v"], 6);
    assert_eq!(updates[ID]["messages_v"], 7);
    assert!(updates[ID].get("encrypted_draft_md").is_none());
    c.chats.extend(updates);
    assert!(matches!(
        c.check_draft_regression(c.chats.get(ID), &draft(5)),
        Err(Error::Conflict)
    ));
    assert!(!c.may_read_cached_default_chat_inventory(false).unwrap());
    c.chats.remove(ID);
    let requested = vec![(ID.into(), 0)];
    let updates = c
        .prepare_draft_versions_at(
            &requested,
            &BTreeMap::from([(ID.into(), 0)]),
            &BTreeMap::from([(ID.into(), 7)]),
            &BTreeMap::from([(ID.into(), 5)]),
        )
        .unwrap();
    assert_eq!(updates[ID]["draft_v"], 7);
    assert!(updates[ID].get("encrypted_draft_md").is_none());
}

#[test]
fn malformed_or_foreign_first_seen_tombstone_never_creates_cache_rows() {
    let mut c = client("http://127.0.0.1:9");
    c.chats.remove(ID);
    let before = c.chats.clone();
    for bad in [
        json!({"id":ID,"user_id":"foreign-owner","draft_v":0,"cleared_draft_v":6}),
        json!({"id":ID,"user_id":"synthetic-owner","draft_v":0,"cleared_draft_v":-1}),
        json!({"id":ID,"user_id":"synthetic-owner","draft_v":0,"cleared_draft_v":"6"}),
    ] {
        assert!(
            c.prepare_draft_metadata(&BTreeMap::from([(ID.into(), bad)]))
                .is_err()
        );
        assert_eq!(c.chats, before);
    }
}
