//! Focused cached-view policy guards; synthetic encrypted data only.
//! These tests never contact an account, discover profiles or invoke inference.
//! The native integration cases separately use actual authenticated peers and
//! encrypted RuntimeStore publication before issuing the same SDK read lane.
//! Cached views remain presentation data with no durable/freshness authority.
use super::super::{Changes, ChatMonitorAccessDenial};
use super::*;
use crate::{crypto, session::Session};
use serde_json::json;
use std::sync::{Mutex, atomic::AtomicBool};
use zeroize::Zeroizing;
const CHAT: &str = "22222222-2222-4222-8222-222222222222";
fn fixture(count: usize) -> (Client, ChatMonitor) {
    fixture_at(count, "https://cached.example.invalid")
}
fn fixture_at(count: usize, api: &str) -> (Client, ChatMonitor) {
    let session = Session {
        api_url: api.into(),
        session_id: "synthetic-session".into(),
        cookies: BTreeMap::from([("auth_refresh_token".into(), "synthetic-cookie".into())]),
        ws_token: None,
        master_key: Zeroizing::new([7; 32]),
        hashed_email: "synthetic-owner".into(),
        user_email_salt: String::new(),
        email_encryption_key: None,
        created_at: 1,
        paired_session_expires_at: None,
        active_team_id: None,
    };
    let mut client = Client::new(&session.api_url, Some(session.clone())).unwrap();
    client.user = json!({"id":"synthetic-owner"});
    client.credentials_changed();
    let rows: Vec<Value> = (0..count).map(|n| json!({"id":format!("10000000-0000-4000-8000-{n:012}"),"chat_id":CHAT,"role":if n%2==0 {"user"}else{"assistant"},
        "created_at":n,"encrypted_content":crypto::encrypt_combined(&format!("cached-line-{n:03}"), &[9;32]).unwrap()})).collect();
    let row = json!({"id":CHAT,"messages_v":count,"last_edited_overall_timestamp":1,"encrypted_chat_key":crypto::encrypt_bytes(&[9;32], &[7;32]).unwrap(),
        "encrypted_title":crypto::encrypt_combined("Cached synthetic title", &[9;32]).unwrap()});
    let chats = BTreeMap::from([(CHAT.to_owned(), row)]);
    let history = BTreeMap::from([(CHAT.to_owned(), rows)]);
    client.restore_ciphertext_snapshot(&json!({"chats":chats,"wrappers":[],"history":history,"embeds":{},"embed_keys":[],"team_wrapped_key":null})).unwrap();
    client
        .acknowledge_credentials(client.credential_revision)
        .unwrap();
    let monitor = ChatMonitor {
        fence: Arc::new(MonitorFence {
            owner: client.task_watch_authority.clone(),
            generation: client.generation,
            team: None,
            expires_at: None,
            cancel: CancellationToken::new(),
            alive: AtomicBool::new(true),
            denial: Mutex::new(None),
        }),
        changes: Arc::new(Changes::default()),
    };
    (client, monitor)
}
#[test]
fn cached_tail_is_bounded_before_decoding_and_never_promotes_authority() {
    let (client, monitor) = fixture(70);
    let before = client.ciphertext_snapshot();
    let reader = client
        .stage_cached_chat_views(Some(&monitor), CancellationToken::new())
        .unwrap();
    let view = reader
        .publish(CHAT, CancellationToken::new())
        .unwrap()
        .unwrap()
        .into_window()
        .unwrap();
    assert_eq!(view.chat.messages.len(), MAX_CACHED_MESSAGES);
    assert_eq!(
        view.chat.messages.first().unwrap().content,
        "cached-line-040"
    );
    assert_eq!(
        view.chat.messages.last().unwrap().content,
        "cached-line-069"
    );
    assert_eq!(view.has_more_before, Some(true));
    assert!(view.cached && view.refreshing && !view.history_complete);
    assert_eq!(view.pii_restoration, "page_local");
    assert_eq!(client.ciphertext_snapshot(), before);
    assert!(
        client
            .try_cached_default_chat_list(false)
            .unwrap()
            .is_none()
    );
}
#[test]
fn missing_wrong_key_and_oversized_cache_are_not_synthetic_previews() {
    for change in ["missing", "wrong-key", "oversized", "wrong-chat"] {
        let (mut client, monitor) = fixture(2);
        match change {
            "missing" => {
                client.history.clear();
            }
            "wrong-key" => {
                client.chats.get_mut(CHAT).unwrap()["encrypted_chat_key"] =
                    json!(crypto::encrypt_bytes(&[8; 32], &[7; 32]).unwrap());
            }
            "oversized" => {
                client.history.get_mut(CHAT).unwrap()[0]["encrypted_content"] =
                    json!("x".repeat(MAX_WINDOW_BYTES + 1));
            }
            "wrong-chat" => {
                client.history.get_mut(CHAT).unwrap()[0]["chat_id"] =
                    json!("33333333-3333-4333-8333-333333333333");
            }
            _ => unreachable!(),
        }
        let reader = client
            .stage_cached_chat_views(Some(&monitor), CancellationToken::new())
            .unwrap();
        assert!(
            reader
                .publish(CHAT, CancellationToken::new())
                .unwrap()
                .is_none(),
            "{change}"
        );
    }
}
#[test]
fn no_host_credential_ack_is_created_by_staging() {
    let (mut client, monitor) = fixture(2);
    client.credential_ack = 0;
    assert!(matches!(
        client.stage_cached_chat_views(Some(&monitor), CancellationToken::new()),
        Err(Error::Cancelled)
    ));
    assert_eq!(client.credential_ack, 0);
}
#[test]
fn owner_reset_scope_and_monitor_denial_reject_queued_publication() {
    for change in ["owner", "key", "team", "monitor-denial"] {
        let (mut client, monitor) = fixture(2);
        let reader = client
            .stage_cached_chat_views(Some(&monitor), CancellationToken::new())
            .unwrap();
        let queued = reader
            .publish(CHAT, CancellationToken::new())
            .unwrap()
            .unwrap();
        match change {
            "owner" => {
                client.user = json!({"id":"other-owner"});
                client.credentials_changed();
            }
            "key" => {
                let mut session = client.clone_session().unwrap();
                session.master_key = Zeroizing::new([8; 32]);
                client
                    .reset("https://cached.example.invalid", Some(session))
                    .unwrap();
            }
            "team" => client
                .set_team(Some("33333333-3333-4333-8333-333333333333"))
                .unwrap(),
            "monitor-denial" => monitor.deny(ChatMonitorAccessDenial::ScopeRevoked).unwrap(),
            _ => unreachable!(),
        }
        assert!(
            matches!(queued.into_window(), Err(Error::Cancelled)),
            "{change}"
        );
    }
}
#[test]
fn reader_owns_a_child_lifetime_and_cancelled_requests_cannot_publish() {
    let (client, monitor) = fixture(2);
    let parent = CancellationToken::new();
    let reader = client
        .stage_cached_chat_views(Some(&monitor), parent.clone())
        .unwrap();
    let request = CancellationToken::new();
    let queued = reader.publish(CHAT, request.clone()).unwrap().unwrap();
    request.cancel();
    assert!(matches!(queued.into_window(), Err(Error::Cancelled)));
    reader.close();
    assert!(
        !parent.is_cancelled(),
        "closing preview cannot cancel foreground work"
    );
    assert!(matches!(
        reader.publish(CHAT, CancellationToken::new()),
        Err(Error::Cancelled)
    ));
    let reader = client
        .stage_cached_chat_views(Some(&monitor), parent.clone())
        .unwrap();
    let queued = reader
        .publish(CHAT, CancellationToken::new())
        .unwrap()
        .unwrap();
    parent.cancel();
    assert!(matches!(queued.into_window(), Err(Error::Cancelled)));
}
#[test]
fn only_loaded_user_mappings_restore_page_local_text() {
    let (mut client, monitor) = fixture(2);
    let rows = client.history.get_mut(CHAT).unwrap();
    for row in rows.iter_mut() {
        row["encrypted_content"] =
            json!(crypto::encrypt_combined("[known] [unknown]", &[9; 32]).unwrap());
    }
    rows[0]["encrypted_pii_mappings"] = json!(
        crypto::encrypt_combined(
            r#"[{"placeholder":"[known]","original":"Synthetic name"}]"#,
            &[9; 32]
        )
        .unwrap()
    );
    rows[1]["encrypted_pii_mappings"] = json!(
        crypto::encrypt_combined(
            r#"[{"placeholder":"[unknown]","original":"must not use assistant mapping"}]"#,
            &[9; 32]
        )
        .unwrap()
    );
    let reader = client
        .stage_cached_chat_views(Some(&monitor), CancellationToken::new())
        .unwrap();
    let view = reader
        .publish(CHAT, CancellationToken::new())
        .unwrap()
        .unwrap()
        .into_window()
        .unwrap();
    for message in view.chat.messages {
        assert_eq!(message.content, "Synthetic name [unknown]");
    }
}
#[test]
fn unrelated_monitor_data_traffic_does_not_claim_cached_freshness() {
    let (client, monitor) = fixture(2);
    let reader = client
        .stage_cached_chat_views(Some(&monitor), CancellationToken::new())
        .unwrap();
    client
        .inventory_network
        .fetch_add(1, std::sync::atomic::Ordering::SeqCst);
    let view = reader
        .publish(CHAT, CancellationToken::new())
        .unwrap()
        .unwrap()
        .into_window()
        .unwrap();
    assert!(view.cached && view.refreshing && !view.history_complete);
    assert!(
        client
            .try_cached_default_chat_list(false)
            .unwrap()
            .is_none()
    );
}

#[test]
fn expired_session_refuses_staging_and_close_erases_queued_plaintext() {
    let (mut client, monitor) = fixture(2);
    let reader = client
        .stage_cached_chat_views(Some(&monitor), CancellationToken::new())
        .unwrap();
    let queued = reader
        .publish(CHAT, CancellationToken::new())
        .unwrap()
        .unwrap();
    reader.close();
    assert!(queued.window.window.lock().unwrap().is_none());
    assert!(matches!(queued.into_window(), Err(Error::Cancelled)));
    client.session.as_mut().unwrap().paired_session_expires_at = Some(1);
    assert!(matches!(
        client.stage_cached_chat_views(Some(&monitor), CancellationToken::new()),
        Err(Error::Expired)
    ));
}

#[test]
fn cached_preview_eligibility_does_not_widen_team_or_direct_scope() {
    for scope in ["team", "direct"] {
        let (mut client, mut monitor) = fixture(2);
        if scope == "team" {
            let team = "33333333-3333-4333-8333-333333333333".to_owned();
            client.session.as_mut().unwrap().active_team_id = Some(team.clone());
            Arc::get_mut(&mut monitor.fence).unwrap().team = Some(team);
        } else {
            client.chats.get_mut(CHAT).unwrap()["chat_visibility"] = json!("direct");
        }
        let reader = client
            .stage_cached_chat_views(Some(&monitor), CancellationToken::new())
            .unwrap();
        assert!(
            reader
                .publish(CHAT, CancellationToken::new())
                .unwrap()
                .is_none()
        );
    }
}

async fn cached_read_peer(
    status: u16,
    requests: usize,
) -> (String, tokio::task::JoinHandle<usize>) {
    use tokio::io::{AsyncReadExt, AsyncWriteExt};
    let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
    let api = format!("http://{}", listener.local_addr().unwrap());
    let server = tokio::spawn(async move {
        for _ in 0..requests {
            let (mut socket, _) = listener.accept().await.unwrap();
            let mut bytes = Vec::new();
            loop {
                let mut chunk = [0; 1024];
                let n = socket.read(&mut chunk).await.unwrap();
                assert!(n > 0);
                bytes.extend_from_slice(&chunk[..n]);
                assert!(bytes.len() < 16384);
                if let Some(end) = bytes.windows(4).position(|part| part == b"\r\n\r\n") {
                    let headers = std::str::from_utf8(&bytes[..end]).unwrap();
                    let length = headers
                        .lines()
                        .find_map(|line| {
                            line.to_ascii_lowercase()
                                .strip_prefix("content-length:")
                                .map(|n| n.trim().parse::<usize>().unwrap())
                        })
                        .unwrap_or(0);
                    if bytes.len() >= end + 4 + length {
                        break;
                    }
                }
            }
            let request = String::from_utf8(bytes).unwrap();
            assert!(request.starts_with("POST /v1/chats/metadata/batch HTTP/1.1\r\n"));
            assert!(
                request
                    .to_ascii_lowercase()
                    .contains("cookie: auth_refresh_token=synthetic-cookie")
            );
            let body = "{}";
            socket.write_all(format!("HTTP/1.1 {status} Synthetic\r\nContent-Type: application/json\r\nContent-Length: {}\r\nConnection: close\r\n\r\n{body}",body.len()).as_bytes()).await.unwrap();
        }
        requests
    });
    (api, server)
}
#[tokio::test]
async fn source_tagged_offline_keeps_original_open_chat_contract_without_duplicate_fetch() {
    tokio::time::timeout(std::time::Duration::from_secs(5), async {
        let (api, server) = cached_read_peer(503, 2).await;
        let (mut client, monitor) = fixture_at(6, &api);
        let before = client.ciphertext_snapshot();
        let old = client.open_chat(CHAT).await.unwrap();
        assert_eq!(old.messages.len(), 6, "original SDK fallback is unchanged");
        let read = client
            .read_chat_view(Some(&monitor), CHAT, CancellationToken::new())
            .await
            .unwrap();
        let ChatViewRead::CachedOffline(publication) = read else {
            panic!("Offline cannot be canonical")
        };
        let window = publication.into_window().unwrap();
        assert_eq!(window.chat.messages.len(), 6);
        assert!(window.cached && !window.refreshing && !window.history_complete);
        assert_eq!(client.ciphertext_snapshot(), before);
        assert_eq!(
            server.await.unwrap(),
            2,
            "one metadata request per operation, no fallback refetch"
        );
    })
    .await
    .unwrap();
}
#[tokio::test]
async fn actual_metadata_owner_denial_rejects_offline_and_queued_cached_data() {
    tokio::time::timeout(std::time::Duration::from_secs(5), async {
        let (api, server) = cached_read_peer(401, 1).await;
        let (mut client, monitor) = fixture_at(6, &api);
        let reader = client
            .stage_cached_chat_views(Some(&monitor), CancellationToken::new())
            .unwrap();
        let queued = reader
            .publish(CHAT, CancellationToken::new())
            .unwrap()
            .unwrap();
        assert!(matches!(
            client
                .read_chat_view(Some(&monitor), CHAT, CancellationToken::new())
                .await,
            Err(Error::Authentication | Error::Expired | Error::Forbidden)
        ));
        assert!(matches!(queued.into_window(), Err(Error::Cancelled)));
        assert!(client.task_watch_authority.cancel.is_cancelled());
        assert!(
            client
                .stage_cached_chat_views(None, CancellationToken::new())
                .is_err(),
            "discarding monitor cannot erase known owner denial"
        );
        assert_eq!(server.await.unwrap(), 1);
    })
    .await
    .unwrap();
}
#[test]
fn raw_session_and_cache_data_do_not_establish_an_authenticated_owner() {
    let (mut client, _monitor) = fixture(2);
    client.user = Value::Null;
    client.task_watch_owner = None;
    assert!(matches!(
        client.stage_cached_chat_views(None, CancellationToken::new()),
        Err(Error::Authentication)
    ));
}
#[test]
fn transport_close_alone_keeps_owned_cached_data_read_only() {
    let (client, monitor) = fixture(2);
    let reader = client
        .stage_cached_chat_views(Some(&monitor), CancellationToken::new())
        .unwrap();
    monitor.close();
    let window = reader
        .publish(CHAT, CancellationToken::new())
        .unwrap()
        .unwrap()
        .into_window()
        .unwrap();
    assert!(window.cached && !window.history_complete);
    assert!(
        client
            .try_cached_default_chat_list(false)
            .unwrap()
            .is_none()
    );
}

#[test]
fn metadata_only_recent_rows_do_not_hide_an_older_available_cached_transcript() {
    let (mut client, monitor) = fixture(2);
    let template = client.chats[CHAT].clone();
    for index in 0..MAX_CACHED_CHATS {
        let id = format!("30000000-0000-4000-8000-{index:012}");
        let mut row = template.clone();
        row["id"] = json!(id);
        row["last_edited_overall_timestamp"] = json!(100 + index);
        client.chats.insert(id, row);
    }
    let reader = client
        .stage_cached_chat_views(Some(&monitor), CancellationToken::new())
        .unwrap();
    assert!(
        reader
            .publish(CHAT, CancellationToken::new())
            .unwrap()
            .is_some()
    );
}

#[test]
fn omitted_monitor_cannot_erase_a_known_expired_owner_epoch() {
    let (client, monitor) = fixture(2);
    let reader = client
        .stage_cached_chat_views(Some(&monitor), CancellationToken::new())
        .unwrap();
    let queued = reader
        .publish(CHAT, CancellationToken::new())
        .unwrap()
        .unwrap();
    client.task_watch_authority.cancel.cancel();
    assert!(matches!(queued.into_window(), Err(Error::Cancelled)));
    assert!(matches!(
        client.stage_cached_chat_views(None, CancellationToken::new()),
        Err(Error::Cancelled)
    ));
}

#[tokio::test]
async fn actual_403_without_monitor_rejects_queued_and_reminted_cached_windows() {
    tokio::time::timeout(std::time::Duration::from_secs(5), async {
        let (api, server) = cached_read_peer(403, 1).await;
        let (mut client, _monitor) = fixture_at(6, &api);
        let reader = client
            .stage_cached_chat_views(None, CancellationToken::new())
            .unwrap();
        let queued = reader
            .publish(CHAT, CancellationToken::new())
            .unwrap()
            .unwrap();
        assert!(matches!(
            client
                .read_chat_view(None, CHAT, CancellationToken::new())
                .await,
            Err(Error::Forbidden)
        ));
        assert!(matches!(queued.into_window(), Err(Error::Cancelled)));
        assert!(matches!(
            reader.publish(CHAT, CancellationToken::new()),
            Err(Error::Cancelled)
        ));
        let reminted = client
            .stage_cached_chat_views(None, CancellationToken::new())
            .unwrap();
        assert!(
            reminted
                .publish(CHAT, CancellationToken::new())
                .unwrap()
                .is_none()
        );
        assert!(
            !client.task_watch_authority.cancel.is_cancelled(),
            "chat denial does not revoke the account"
        );
        assert_eq!(server.await.unwrap(), 1);
    })
    .await
    .unwrap();
}
// Actual canonical metadata+history wire exchange, not a constructed candidate.
async fn canonical_fixture() -> (Client, ChatMonitor, tokio::task::JoinHandle<()>) {
    canonical_fixture_with_followup(false).await
}
async fn canonical_fixture_with_followup(
    deny_after: bool,
) -> (Client, ChatMonitor, tokio::task::JoinHandle<()>) {
    use tokio::io::{AsyncReadExt, AsyncWriteExt};
    let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
    let api = format!("http://{}", listener.local_addr().unwrap());
    let (client, monitor) = fixture_at(2, &api);
    let mut replies = vec![
        json!({"chats":[client.chats[CHAT].clone()]}),
        json!({"messages":client.history[CHAT].clone(),"has_more_before":false}),
    ];
    if deny_after {
        replies.push(json!({"detail":"synthetic chat access denied"}));
    }
    let server = tokio::spawn(async move {
        for (index, response) in replies.into_iter().enumerate() {
            let (mut socket, _) = listener.accept().await.unwrap();
            let mut bytes = Vec::new();
            loop {
                let mut byte = [0; 1];
                socket.read_exact(&mut byte).await.unwrap();
                bytes.push(byte[0]);
                assert!(bytes.len() < 16384);
                if bytes.ends_with(b"\r\n\r\n") {
                    break;
                }
            }
            let headers = String::from_utf8(bytes).unwrap();
            let length = headers
                .lines()
                .find_map(|line| {
                    line.to_ascii_lowercase()
                        .strip_prefix("content-length:")
                        .map(|value| value.trim().parse::<usize>().unwrap())
                })
                .unwrap_or(0);
            let mut body = vec![0; length];
            socket.read_exact(&mut body).await.unwrap();
            assert!(
                headers
                    .to_ascii_lowercase()
                    .contains("cookie: auth_refresh_token=synthetic-cookie")
            );
            if index != 1 {
                assert!(headers.starts_with("POST /v1/chats/metadata/batch HTTP/1.1\r\n"));
                assert_eq!(
                    serde_json::from_slice::<Value>(&body).unwrap(),
                    json!({"chat_ids":[CHAT]})
                );
            } else {
                assert!(headers.starts_with(&format!("GET /v1/chats/{CHAT}/messages/window?direction=latest&limit=100&respect_compression_boundary=false HTTP/1.1\r\n")));
            }
            let body = response.to_string();
            let status = if index == 2 { 403 } else { 200 };
            socket.write_all(format!("HTTP/1.1 {status} Synthetic\r\nContent-Type: application/json\r\nContent-Length: {}\r\nConnection: close\r\n\r\n{body}",body.len()).as_bytes()).await.unwrap();
        }
    });
    (client, monitor, server)
}
async fn actual_canonical(
    client: &mut Client,
    request: CancellationToken,
) -> CanonicalChatCandidate {
    let ChatViewRead::Canonical(candidate) =
        client.read_chat_view(None, CHAT, request).await.unwrap()
    else {
        panic!("successful owned wire read must remain canonical");
    };
    candidate
}
fn exact_candidate_receipt(
    candidate: &CanonicalChatCandidate,
) -> super::super::ChatRefreshDurableReceipt {
    super::super::ChatRefreshDurableReceipt {
        ciphertext_sha256: candidate.ciphertext_sha256().unwrap(),
        credential_revision: candidate.credential_revision(),
    }
}
#[tokio::test]
async fn actual_canonical_candidate_checks_ack_owner_key_cancel_and_exact_saved_snapshot() {
    tokio::time::timeout(std::time::Duration::from_secs(15), async {
        for change in [
            "cancel",
            "owner",
            "key",
            "snapshot",
            "missing-ack",
            "wrong-receipt",
            "denial",
        ] {
            let (mut client, monitor, server) = canonical_fixture().await;
            let request = CancellationToken::new();
            let candidate = actual_canonical(&mut client, request.clone()).await;
            let mut receipt = exact_candidate_receipt(&candidate);
            client.validate_chat_view(&candidate).unwrap();
            match change {
                "cancel" => request.cancel(),
                "owner" => client.clear_account_cache(),
                "key" => {
                    let mut session = client.clone_session().unwrap();
                    session.master_key = Zeroizing::new([8; 32]);
                    let api = session.api_url.clone();
                    client.reset(&api, Some(session)).unwrap();
                }
                "snapshot" => {
                    client.history.remove(CHAT);
                }
                "missing-ack" => client.credential_ack = 0,
                "wrong-receipt" => receipt.ciphertext_sha256 = "0".repeat(64),
                "denial" => monitor
                    .deny(ChatMonitorAccessDenial::ChatUnavailable {
                        chat_id: CHAT.into(),
                    })
                    .unwrap(),
                _ => unreachable!(),
            }
            assert!(
                client.commit_chat_view(candidate, receipt).is_err(),
                "{change}"
            );
            server.await.unwrap();
        }
    })
    .await
    .unwrap();
}
#[tokio::test]
async fn committed_canonical_queue_keeps_request_owner_and_monitorless_denial_fences() {
    tokio::time::timeout(std::time::Duration::from_secs(15), async {
        for change in ["cancel", "owner", "key", "denial", "newer-denial", "none"] {
            let (mut client, monitor, server) = canonical_fixture().await;
            let request = CancellationToken::new();
            let candidate = actual_canonical(&mut client, request.clone()).await;
            let receipt = exact_candidate_receipt(&candidate);
            client
                .acknowledge_credentials(candidate.credential_revision())
                .unwrap();
            let publication = client.commit_chat_view(candidate, receipt).unwrap();
            match change {
                "cancel" => request.cancel(),
                "owner" => client.clear_account_cache(),
                "key" => {
                    let mut session = client.clone_session().unwrap();
                    session.master_key = Zeroizing::new([8; 32]);
                    let api = session.api_url.clone();
                    client.reset(&api, Some(session)).unwrap();
                }
                "denial" => monitor
                    .deny(ChatMonitorAccessDenial::ChatUnavailable {
                        chat_id: CHAT.into(),
                    })
                    .unwrap(),
                "newer-denial" => {
                    client
                        .task_watch_authority
                        .deny_cached_chat(Some(CHAT))
                        .unwrap();
                }
                "none" => {}
                _ => unreachable!(),
            }
            if change == "none" {
                assert_eq!(publication.into_chat().unwrap().messages.len(), 2);
            } else {
                assert!(
                    matches!(publication.into_chat(), Err(Error::Cancelled)),
                    "{change}"
                );
            }
            server.await.unwrap();
        }
    })
    .await
    .unwrap();
}
#[tokio::test]
async fn only_current_durable_canonical_success_can_recover_a_retained_chat_denial() {
    tokio::time::timeout(std::time::Duration::from_secs(5), async {
        let (mut client, _monitor, server) = canonical_fixture().await;
        client
            .task_watch_authority
            .deny_cached_chat(Some(CHAT))
            .unwrap();
        let candidate = actual_canonical(&mut client, CancellationToken::new()).await;
        assert!(!client.task_watch_authority.cached_chat_allowed(CHAT));
        let receipt = exact_candidate_receipt(&candidate);
        client
            .acknowledge_credentials(candidate.credential_revision())
            .unwrap();
        let publication = client.commit_chat_view(candidate, receipt).unwrap();
        assert!(client.task_watch_authority.cached_chat_allowed(CHAT));
        assert_eq!(publication.into_chat().unwrap().messages.len(), 2);
        server.await.unwrap();
    })
    .await
    .unwrap();
}

#[tokio::test]
async fn actual_monitorless_403_after_commit_rejects_queued_canonical_and_old_cached_views() {
    tokio::time::timeout(std::time::Duration::from_secs(5), async {
        let (mut client, _monitor, server) = canonical_fixture_with_followup(true).await;
        let reader = client
            .stage_cached_chat_views(None, CancellationToken::new())
            .unwrap();
        let old_cached = reader
            .publish(CHAT, CancellationToken::new())
            .unwrap()
            .unwrap();
        let candidate = actual_canonical(&mut client, CancellationToken::new()).await;
        let receipt = exact_candidate_receipt(&candidate);
        client
            .acknowledge_credentials(candidate.credential_revision())
            .unwrap();
        let queued = client.commit_chat_view(candidate, receipt).unwrap();
        assert!(matches!(
            client
                .read_chat_view(None, CHAT, CancellationToken::new())
                .await,
            Err(Error::Forbidden)
        ));
        assert!(matches!(queued.into_chat(), Err(Error::Cancelled)));
        assert!(matches!(old_cached.into_window(), Err(Error::Cancelled)));
        let reminted = client
            .stage_cached_chat_views(None, CancellationToken::new())
            .unwrap();
        assert!(
            reminted
                .publish(CHAT, CancellationToken::new())
                .unwrap()
                .is_none()
        );
        server.await.unwrap();
    })
    .await
    .unwrap();
}

#[tokio::test]
async fn monitorless_cached_publication_cannot_resurrect_after_genuine_canonical_recovery() {
    tokio::time::timeout(std::time::Duration::from_secs(5), async {
        let (mut client, _monitor, server) = canonical_fixture().await;
        let reader = client
            .stage_cached_chat_views(None, CancellationToken::new())
            .unwrap();
        let old = reader
            .publish(CHAT, CancellationToken::new())
            .unwrap()
            .unwrap();
        client
            .task_watch_authority
            .deny_cached_chat(Some(CHAT))
            .unwrap();
        assert!(!old.is_valid());
        let candidate = actual_canonical(&mut client, CancellationToken::new()).await;
        let receipt = exact_candidate_receipt(&candidate);
        client
            .acknowledge_credentials(candidate.credential_revision())
            .unwrap();
        assert_eq!(
            client
                .commit_chat_view(candidate, receipt)
                .unwrap()
                .into_chat()
                .unwrap()
                .messages
                .len(),
            2
        );
        assert!(client.task_watch_authority.cached_chat_allowed(CHAT));
        assert!(matches!(old.into_window(), Err(Error::Cancelled)));
        assert!(matches!(
            reader.publish(CHAT, CancellationToken::new()),
            Err(Error::Cancelled)
        ));
        let replacement = client
            .stage_cached_chat_views(None, CancellationToken::new())
            .unwrap();
        assert!(
            replacement
                .publish(CHAT, CancellationToken::new())
                .unwrap()
                .is_some()
        );
        server.await.unwrap();
    })
    .await
    .unwrap();
}

#[test]
fn owner_negative_observer_does_not_extend_a_closed_reader_or_survive_owner_denial() {
    let (client, monitor) = fixture(2);
    let reader = client
        .stage_cached_chat_views(Some(&monitor), CancellationToken::new())
        .unwrap();
    assert!(reader.is_owner_current());
    reader.close();
    assert!(
        reader.is_owner_current(),
        "reader close is not account revocation"
    );
    assert!(!reader.is_valid());
    assert!(reader.publish(CHAT, CancellationToken::new()).is_err());
    monitor
        .deny(ChatMonitorAccessDenial::ChatUnavailable {
            chat_id: CHAT.into(),
        })
        .unwrap();
    assert!(
        !reader.is_owner_current(),
        "negative owner/context history cannot be erased by reader close"
    );
}

// contract-test: supporting surface=sdk assertions=sdk.library.explicit-headless,sdk.encryption.local-only
// Cache-preferred settlement never changes the existing strict reader contract.
async fn settlement_fixture(
    count: usize, reported: usize,
    responses: impl FnOnce(&mut Client) -> Vec<(String, u16, Value)>,
) -> (Client, ChatMonitor, tokio::task::JoinHandle<usize>) {
    settlement_fixture_observed(count, reported, responses, |_| None).await
}
async fn settlement_fixture_observed(
    count: usize, reported: usize,
    responses: impl FnOnce(&mut Client) -> Vec<(String, u16, Value)>,
    observer: impl FnOnce(&Client) -> Option<Arc<dyn Fn(&str) + Send + Sync>>,
) -> (Client, ChatMonitor, tokio::task::JoinHandle<usize>) {
    use tokio::io::{AsyncReadExt, AsyncWriteExt};
    let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
    let api = format!("http://{}", listener.local_addr().unwrap());
    let (mut client, monitor) = fixture_at(count, &api);
    client.chats.get_mut(CHAT).unwrap()["messages_v"] = json!(reported);
    let replies = responses(&mut client);
    let observer = observer(&client);
    let server = tokio::spawn(async move {
        let count = replies.len();
        for (expected, status, response) in replies {
            let (mut socket, _) = listener.accept().await.unwrap();
            let mut bytes = Vec::new();
            loop {
                let mut byte = [0; 1];
                socket.read_exact(&mut byte).await.unwrap();
                bytes.push(byte[0]);
                assert!(bytes.len() < 16384);
                if bytes.ends_with(b"\r\n\r\n") { break; }
            }
            let headers = String::from_utf8(bytes).unwrap();
            assert_eq!(headers.lines().next().unwrap(), expected);
            assert!(headers.to_ascii_lowercase().contains("cookie: auth_refresh_token=synthetic-cookie"));
            let length = headers.lines().find_map(|line| line.to_ascii_lowercase()
                .strip_prefix("content-length:").map(|value|value.trim().parse::<usize>().unwrap())).unwrap_or(0);
            let mut body = vec![0;length]; socket.read_exact(&mut body).await.unwrap();
            if expected.starts_with("POST ") {
                assert_eq!(serde_json::from_slice::<Value>(&body).unwrap(),json!({"chat_ids":[CHAT]}));
            }
            if let Some(observer) = &observer { observer(&expected); }
            let body=response.to_string();
            socket.write_all(format!("HTTP/1.1 {status} Synthetic\r\nContent-Type: application/json\r\nContent-Length: {}\r\nConnection: close\r\n\r\n{body}",body.len()).as_bytes()).await.unwrap();
        }
        count
    });
    (client, monitor, server)
}
fn settlement_metadata(client: &Client) -> (String, u16, Value) {
    ("POST /v1/chats/metadata/batch HTTP/1.1".into(),200,json!({"chats":[client.chats[CHAT].clone()]}))
}
async fn actual_settlement(client: &mut Client, monitor: &ChatMonitor, request: CancellationToken) -> CacheSettlementCandidate {
    let ChatViewRead::CacheSettled(candidate) = client.read_chat_view_prefer_cache(Some(monitor),CHAT,request).await.unwrap()
        else {panic!("nonempty owned cache must settle without all-history IO")};
    candidate
}
fn settlement_receipt(candidate: &CacheSettlementCandidate) -> super::super::ChatRefreshDurableReceipt {
    super::super::ChatRefreshDurableReceipt { ciphertext_sha256:candidate.ciphertext_sha256().unwrap(),credential_revision:candidate.credential_revision() }
}
#[tokio::test]
async fn cache_settlement_keeps_all_older_rows_sorted_and_all_cached_user_pii_without_completeness_claim() {
    tokio::time::timeout(std::time::Duration::from_secs(10),async {
        for reported in [140,900] {
            let (mut client,monitor,server)=settlement_fixture(140,reported,|client| {
                let rows=client.history.get_mut(CHAT).unwrap();
                rows[0]["encrypted_pii_mappings"]=json!(crypto::encrypt_combined(r#"[{"placeholder":"[known]","original":"Synthetic name"}]"#,&[9;32]).unwrap());
                rows[1]["encrypted_pii_mappings"]=json!(crypto::encrypt_combined(r#"[{"placeholder":"[unknown]","original":"unused assistant mapping"}]"#,&[9;32]).unwrap());
                rows[139]["encrypted_content"]=json!(crypto::encrypt_combined("[known] [unknown]",&[9;32]).unwrap());
                rows.reverse();
                vec![settlement_metadata(client)]
            }).await;
            let before=client.ciphertext_snapshot();
            let candidate=actual_settlement(&mut client,&monitor,CancellationToken::new()).await;
            let receipt=settlement_receipt(&candidate);
            client.validate_cache_settlement(&candidate).unwrap();
            // Stand-in for platform exact durable save, not implicit method ACK.
            client.acknowledge_credentials(candidate.credential_revision()).unwrap();
            let publication=client.commit_cache_settlement(candidate,receipt).unwrap();
            client.validate_cache_settlement_publication(&publication).unwrap();
            let window=publication.into_window().unwrap();
            assert_eq!(window.chat.messages.len(),140);
            assert_eq!(window.chat.messages[0].content,"cached-line-000");
            assert_eq!(window.chat.messages[139].content,"Synthetic name [unknown]");
            assert!(!window.history_complete && window.cached && !window.refreshing);
            assert_eq!(window.pii_restoration,"all_cached_user_rows");
            assert_eq!(client.ciphertext_snapshot(),before);
            assert!(client.try_cached_default_chat_list(false).unwrap().is_none(),"cache settlement cannot mint inventory/recovery authority");
            assert_eq!(server.await.unwrap(),1,"nonempty cache never fetches history windows");
        }
    }).await.unwrap();
}
#[tokio::test]
async fn cache_settlement_requires_exact_ack_snapshot_request_owner_key_private_gate_and_negative_history() {
    tokio::time::timeout(std::time::Duration::from_secs(15),async {
        for change in ["request","operation","owner-key","snapshot","ack","receipt","private","denial","monitor"] {
            let (mut client,monitor,server)=settlement_fixture(2,100,|client|vec![settlement_metadata(client)]).await;
            let request=CancellationToken::new();
            let candidate=actual_settlement(&mut client,&monitor,request.clone()).await;
            let mut receipt=settlement_receipt(&candidate);
            match change {
                "request"=>request.cancel(),
                "operation"=>client.set_operation_cancel(CancellationToken::new()),
                "owner-key"=>{let mut session=client.clone_session().unwrap();session.master_key=Zeroizing::new([8;32]);let api=session.api_url.clone();client.reset(&api,Some(session)).unwrap();},
                "snapshot"=>{client.history.remove(CHAT);},
                "ack"=>client.credential_ack=0,
                "receipt"=>receipt.ciphertext_sha256="0".repeat(64),
                "private"=>client.set_private_operation_gate(Some(Arc::new(||Err(Error::Forbidden)))),
                "denial"=>monitor.deny(ChatMonitorAccessDenial::ChatUnavailable{chat_id:CHAT.into()}).unwrap(),
                "monitor"=>monitor.fence.alive.store(false,std::sync::atomic::Ordering::Release),
                _=>unreachable!(),
            }
            assert!(client.commit_cache_settlement(candidate,receipt).is_err(),"{change}");
            assert_eq!(server.await.unwrap(),1);
        }
    }).await.unwrap();
}
#[tokio::test]
async fn queued_cache_settlement_rechecks_owner_denial_request_live_monitor_and_private_gate() {
    tokio::time::timeout(std::time::Duration::from_secs(15),async {
        for change in ["request","owner-key","denial","monitor","private","none"] {
            let (mut client,monitor,server)=settlement_fixture(2,100,|client|vec![settlement_metadata(client)]).await;
            let allowed=Arc::new(AtomicBool::new(true));let gate=allowed.clone();
            client.set_private_operation_gate(Some(Arc::new(move||if gate.load(std::sync::atomic::Ordering::SeqCst){Ok(())}else{Err(Error::Forbidden)})));
            let request=CancellationToken::new();let candidate=actual_settlement(&mut client,&monitor,request.clone()).await;
            let receipt=settlement_receipt(&candidate);client.acknowledge_credentials(candidate.credential_revision()).unwrap();
            let publication=client.commit_cache_settlement(candidate,receipt).unwrap();
            match change {
                "request"=>request.cancel(),
                "owner-key"=>{let mut session=client.clone_session().unwrap();session.master_key=Zeroizing::new([8;32]);let api=session.api_url.clone();client.reset(&api,Some(session)).unwrap();},
                "denial"=>monitor.deny(ChatMonitorAccessDenial::ChatUnavailable{chat_id:CHAT.into()}).unwrap(),
                "monitor"=>monitor.fence.alive.store(false,std::sync::atomic::Ordering::Release),
                "private"=>allowed.store(false,std::sync::atomic::Ordering::SeqCst),
                "none"=>{},_=>unreachable!(),
            }
            assert_eq!(publication.into_window().is_ok(),change=="none","{change}");
            server.await.unwrap();
        }
    }).await.unwrap();
}
#[tokio::test]
async fn empty_cache_preference_preserves_strict_full_history_paging_and_canonical_commit() {
    tokio::time::timeout(std::time::Duration::from_secs(10),async {
        let (mut client,monitor,server)=settlement_fixture(2,2,|client| {
            let rows=client.history[CHAT].clone();
            vec![settlement_metadata(client),settlement_metadata(client),
                (format!("GET /v1/chats/{CHAT}/messages/window?direction=latest&limit=100&respect_compression_boundary=false HTTP/1.1"),200,json!({"messages":[rows[1].clone()],"has_more_before":true,"start_cursor":{"created_at":1,"message_id":rows[1]["id"]}})),
                (format!("GET /v1/chats/{CHAT}/messages/window?direction=before&limit=100&respect_compression_boundary=false&before_timestamp=1&before_message_id=10000000-0000-4000-8000-000000000001 HTTP/1.1"),200,json!({"messages":[rows[0].clone()],"has_more_before":false}))]
        }).await;
        client.history.remove(CHAT);
        let read=client.read_chat_view_prefer_cache(Some(&monitor),CHAT,CancellationToken::new()).await.unwrap();
        let ChatViewRead::Canonical(candidate)=read else {panic!("empty cache must finish the unchanged strict reader")};
        let receipt=exact_candidate_receipt(&candidate);client.acknowledge_credentials(candidate.credential_revision()).unwrap();
        let chat=client.commit_chat_view(candidate,receipt).unwrap().into_chat().unwrap();
        assert_eq!(chat.messages.len(),2);assert_eq!(chat.messages[0].content,"cached-line-000");
        assert_eq!(client.history[CHAT].len(),2);assert_eq!(server.await.unwrap(),4);
        // First-page cold interim remains REQUIRED follow-up; this test proves
        // only unchanged strict pagination, cancellation and final admission.
    }).await.unwrap();
}
#[tokio::test]
async fn cache_preference_denial_cannot_fall_back_to_online_controls_or_erase_negative_history() {
    tokio::time::timeout(std::time::Duration::from_secs(10),async {
        let (mut client,monitor,server)=settlement_fixture(2,100,|_|vec![("POST /v1/chats/metadata/batch HTTP/1.1".into(),403,json!({"detail":"denied"}))]).await;
        assert!(matches!(client.read_chat_view_prefer_cache(Some(&monitor),CHAT,CancellationToken::new()).await,Err(Error::Forbidden)));
        assert!(!client.task_watch_authority.cached_chat_allowed(CHAT));
        assert_eq!(server.await.unwrap(),1);
    }).await.unwrap();
}
#[tokio::test]
async fn partial_selected_live_refresh_merges_latest_twenty_and_retains_all_older_cache_and_strict_export() {
    tokio::time::timeout(std::time::Duration::from_secs(10),async {
        let (mut client,monitor,server)=settlement_fixture(70,900,|client| {
            let next=json!({"id":"10000000-0000-4000-8000-000000000070","chat_id":CHAT,"role":"assistant","created_at":70,"encrypted_content":crypto::encrypt_combined("new persisted response",&[9;32]).unwrap()});
            let full=client.history[CHAT].iter().cloned().chain(std::iter::once(next.clone())).collect::<Vec<_>>();
            vec![settlement_metadata(client),settlement_metadata(client),
                (format!("GET /v1/chats/{CHAT}/messages/window?direction=latest&limit=20&respect_compression_boundary=false HTTP/1.1"),200,json!({"messages":[next.clone()],"server_message_count":900,"has_more_before":true,"start_cursor":{"created_at":70,"message_id":next["id"]}})),
                settlement_metadata(client),
                (format!("GET /v1/chats/{CHAT}/messages/window?direction=latest&limit=100&respect_compression_boundary=false HTTP/1.1"),200,json!({"messages":full,"has_more_before":false}))]
        }).await;
        let hint=super::super::ChatInvalidation{fence:monitor.fence.clone(),pending:Default::default()};
        let refresh=client.refresh_chat_monitor_prefer_cache(&monitor,&hint,Some(CHAT)).await.unwrap();
        let receipt=super::super::ChatRefreshDurableReceipt{ciphertext_sha256:refresh.ciphertext_sha256().unwrap(),credential_revision:refresh.credential_revision()};
        client.acknowledge_credentials(refresh.credential_revision()).unwrap();
        let publication=client.commit_chat_refresh(refresh,receipt).unwrap();
        let models=publication.into_models().unwrap();
        let super::super::ChatSelectionUpdate::CacheSettled(chat)=models.selection else {panic!("partial cache may not become canonical history")};
        assert_eq!(chat.messages.len(),71);assert_eq!(chat.messages[0].content,"cached-line-000");assert_eq!(chat.messages[70].content,"new persisted response");
        assert_eq!(client.history[CHAT].len(),70,"latest page must not overwrite complete-history storage");
        let snapshot=client.ciphertext_snapshot();
        super::super::super::sync_windows::restore_windows(snapshot.get("sync_message_windows")).unwrap();
        // Download deliberately re-enters strict history even after settlement.
        let directory=tempfile::tempdir().unwrap();let output=directory.path().join("chat.md");
        client.download(crate::model::Workspace::Chats,CHAT,&output,false).await.unwrap();
        let text=std::fs::read_to_string(output).unwrap();assert!(text.contains("cached-line-000")&&text.contains("new persisted response"));
        assert_eq!(server.await.unwrap(),5);
    }).await.unwrap();
}
#[tokio::test]
async fn cache_settlement_includes_older_retained_sync_rows_alongside_full_local_history() {
    tokio::time::timeout(std::time::Duration::from_secs(10),async {
        let (mut client,monitor,server)=settlement_fixture(70,900,|client| {
            let row=client.chats[CHAT].clone();
            for index in [70,71] {
                let message=json!({"id":format!("10000000-0000-4000-8000-{index:012}"),"chat_id":CHAT,"role":"assistant","created_at":index,"encrypted_content":crypto::encrypt_combined(&format!("retained-{index}"),&[9;32]).unwrap()});
                client.retain_settlement_page(&row,&json!({"messages":[message.clone()],"server_message_count":900,"has_more_before":true,"start_cursor":{"created_at":index,"message_id":message["id"]}})).unwrap();
            }
            vec![settlement_metadata(client)]
        }).await;
        let snapshot=client.ciphertext_snapshot();
        super::super::super::sync_windows::restore_windows(snapshot.get("sync_message_windows")).unwrap();
        let candidate=actual_settlement(&mut client,&monitor,CancellationToken::new()).await;
        let receipt=settlement_receipt(&candidate);client.acknowledge_credentials(candidate.credential_revision()).unwrap();
        let window=client.commit_cache_settlement(candidate,receipt).unwrap().into_window().unwrap();
        assert_eq!(window.chat.messages.len(),72);
        assert_eq!(window.chat.messages[0].content,"cached-line-000");
        assert_eq!(window.chat.messages[70].content,"retained-70");
        assert_eq!(window.chat.messages[71].content,"retained-71");
        assert!(!window.history_complete);assert_eq!(server.await.unwrap(),1);
    }).await.unwrap();
}
#[tokio::test]
async fn empty_cache_partial_history_failure_never_publishes_a_settlement_or_partial_complete_history() {
    tokio::time::timeout(std::time::Duration::from_secs(10),async {
        let (mut client,monitor,server)=settlement_fixture(2,2,|client| {
            let row=client.history[CHAT][1].clone();
            vec![settlement_metadata(client),settlement_metadata(client),
                (format!("GET /v1/chats/{CHAT}/messages/window?direction=latest&limit=100&respect_compression_boundary=false HTTP/1.1"),200,json!({"messages":[row.clone()],"has_more_before":true,"start_cursor":{"created_at":1,"message_id":row["id"]}})),
                (format!("GET /v1/chats/{CHAT}/messages/window?direction=before&limit=100&respect_compression_boundary=false&before_timestamp=1&before_message_id=10000000-0000-4000-8000-000000000001 HTTP/1.1"),403,json!({"detail":"denied"}))]
        }).await;
        client.history.remove(CHAT);
        assert!(matches!(client.read_chat_view_prefer_cache(Some(&monitor),CHAT,CancellationToken::new()).await,Err(Error::Forbidden)));
        assert!(!client.history.contains_key(CHAT));assert!(!client.task_watch_authority.cached_chat_allowed(CHAT));
        assert_eq!(server.await.unwrap(),4);
    }).await.unwrap();
}

fn cache_monitor_replies(client: &Client) -> Vec<(String,u16,Value)> {
    let last=client.history[CHAT].last().unwrap().clone();
    vec![settlement_metadata(client),settlement_metadata(client),
        (format!("GET /v1/chats/{CHAT}/messages/window?direction=latest&limit=20&respect_compression_boundary=false HTTP/1.1"),200,
         json!({"messages":[last.clone()],"server_message_count":900,"has_more_before":true,"start_cursor":{"created_at":last["created_at"],"message_id":last["id"]}}))]
}
#[tokio::test]
async fn monitor_cache_scope_survives_staging_ack_and_commit_without_rebinding_child_master_or_denial_ledger() {
    tokio::time::timeout(std::time::Duration::from_secs(15),async {
        for change in ["owner-ledger","child","master","ack","receipt"] {
            let (mut client,monitor,server)=settlement_fixture(70,900,|client|cache_monitor_replies(client)).await;
            let hint=super::super::ChatInvalidation{fence:monitor.fence.clone(),pending:Default::default()};
            let refresh=client.refresh_chat_monitor_prefer_cache(&monitor,&hint,Some(CHAT)).await.unwrap();
            let mut receipt=super::super::ChatRefreshDurableReceipt{ciphertext_sha256:refresh.ciphertext_sha256().unwrap(),credential_revision:refresh.credential_revision()};
            client.acknowledge_credentials(refresh.credential_revision()).unwrap();
            match change {
                "owner-ledger"=>{
                    client.task_watch_authority.deny_cached_chat(Some(CHAT)).unwrap();
                    assert!(monitor.is_valid(),"direct owner ledger refusal must be independent of monitor.deny");
                },
                "child"=>{
                    let epoch=client.fresh_auth.operation_epoch();let parent=client.operation_parent.clone();
                    client.set_operation_cancel(parent);
                    assert_eq!(client.fresh_auth.operation_epoch(),epoch,"same-parent replacement is still live plumbing");
                },
                "master"=>{client.session.as_mut().unwrap().master_key=Zeroizing::new([8;32]);assert!(monitor.is_valid());},
                "ack"=>client.credential_ack=0,
                "receipt"=>receipt.ciphertext_sha256="0".repeat(64),_=>unreachable!(),
            }
            assert!(client.commit_chat_refresh(refresh,receipt).is_err(),"original restrictive read scope lost at {change}");
            assert_eq!(server.await.unwrap(),3);
        }
    }).await.unwrap();
}
#[tokio::test]
async fn queued_monitor_cache_publication_rechecks_direct_owner_ledger_and_live_child_replacement() {
    tokio::time::timeout(std::time::Duration::from_secs(15),async {
        for change in ["owner-ledger","child","none"] {
            let (mut client,monitor,server)=settlement_fixture(70,900,|client|cache_monitor_replies(client)).await;
            let hint=super::super::ChatInvalidation{fence:monitor.fence.clone(),pending:Default::default()};
            let refresh=client.refresh_chat_monitor_prefer_cache(&monitor,&hint,Some(CHAT)).await.unwrap();
            let receipt=super::super::ChatRefreshDurableReceipt{ciphertext_sha256:refresh.ciphertext_sha256().unwrap(),credential_revision:refresh.credential_revision()};
            client.acknowledge_credentials(refresh.credential_revision()).unwrap();
            let publication=client.commit_chat_refresh(refresh,receipt).unwrap();
            match change {
                "owner-ledger"=>{client.task_watch_authority.deny_cached_chat(Some(CHAT)).unwrap();assert!(monitor.is_valid());},
                "child"=>{let parent=client.operation_parent.clone();client.set_operation_cancel(parent);},
                "none"=>{},_=>unreachable!(),
            }
            assert_eq!(client.validate_chat_publication(&publication).is_ok(),change=="none");
            assert_eq!(publication.models().is_ok(),change=="none");
            assert_eq!(publication.into_models().is_ok(),change=="none");
            assert_eq!(server.await.unwrap(),3);
        }
    }).await.unwrap();
}
#[tokio::test]
async fn monitor_captures_negative_revision_before_first_metadata_and_never_recaptures_after_live_read() {
    tokio::time::timeout(std::time::Duration::from_secs(10),async {
        let (mut client,monitor,server)=settlement_fixture_observed(70,900,|client|cache_monitor_replies(client),|client|{
            let owner=client.task_watch_authority.clone();let once=AtomicBool::new(false);
            Some(Arc::new(move|request|{
                if request.starts_with("POST ") && !once.swap(true,std::sync::atomic::Ordering::SeqCst) {
                    // A separately observed denial need not close this socket.
                    // The selected chat remains allowed, so only the ORIGINAL
                    // whole-read revision can catch this event at final stage.
                    owner.deny_cached_chat(Some("33333333-3333-4333-8333-333333333333")).unwrap();
                }
            }))
        }).await;
        let hint=super::super::ChatInvalidation{fence:monitor.fence.clone(),pending:Default::default()};
        assert!(client.refresh_chat_monitor_prefer_cache(&monitor,&hint,Some(CHAT)).await.is_err());
        assert!(monitor.is_valid());assert!(client.task_watch_authority.cached_chat_allowed(CHAT));
        assert_eq!(server.await.unwrap(),3);
    }).await.unwrap();
}

struct EncodedWindowProbe {
    json: String,
    wiped: Arc<AtomicBool>,
}
impl zeroize::Zeroize for EncodedWindowProbe {
    fn zeroize(&mut self) { self.json.zeroize(); }
}
impl Drop for EncodedWindowProbe {
    fn drop(&mut self) { self.wiped.store(self.json.is_empty(),std::sync::atomic::Ordering::SeqCst); }
}
fn encoded_probe(chat: &Chat, wiped: Arc<AtomicBool>) -> zeroize::Zeroizing<EncodedWindowProbe> {
    zeroize::Zeroizing::new(EncodedWindowProbe{json:serde_json::to_string(chat).unwrap(),wiped})
}
#[tokio::test]
async fn original_cache_settlement_fence_rechecks_after_json_encoding_without_plaintext_copy() {
    tokio::time::timeout(std::time::Duration::from_secs(10),async {
        let (mut client,monitor,server)=settlement_fixture(140,900,|client|vec![settlement_metadata(client)]).await;
        let candidate=actual_settlement(&mut client,&monitor,CancellationToken::new()).await;
        let receipt=settlement_receipt(&candidate);client.acknowledge_credentials(candidate.credential_revision()).unwrap();
        let publication=client.commit_cache_settlement(candidate,receipt).unwrap();
        let owner=client.task_watch_authority.clone();let wiped=Arc::new(AtomicBool::new(false));
        let result=publication.with_window(|window| {
            assert_eq!(window.chat.messages.len(),140);
            let output=encoded_probe(&window.chat,wiped.clone());
            owner.deny_cached_chat(Some(CHAT))?;
            assert!(monitor.is_valid(),"the original selected denial fence must catch this independently");
            Ok(output)
        });
        assert!(matches!(result,Err(Error::Cancelled)));assert!(wiped.load(std::sync::atomic::Ordering::SeqCst));
        assert!(!publication.is_valid());assert_eq!(server.await.unwrap(),1);
    }).await.unwrap();
}
#[tokio::test]
async fn canonical_fallback_original_fence_rechecks_after_json_encoding() {
    tokio::time::timeout(std::time::Duration::from_secs(10),async {
        let (mut client,_monitor,server)=canonical_fixture().await;
        let candidate=actual_canonical(&mut client,CancellationToken::new()).await;
        let receipt=exact_candidate_receipt(&candidate);client.acknowledge_credentials(candidate.credential_revision()).unwrap();
        let publication=client.commit_chat_view(candidate,receipt).unwrap();
        let owner=client.task_watch_authority.clone();let wiped=Arc::new(AtomicBool::new(false));
        let result=publication.with_chat(|chat| {
            let output=encoded_probe(chat,wiped.clone());owner.deny_cached_chat(Some(CHAT))?;Ok(output)
        });
        assert!(matches!(result,Err(Error::Cancelled)));assert!(wiped.load(std::sync::atomic::Ordering::SeqCst));
        server.await.unwrap();
    }).await.unwrap();
}
#[test]
fn offline_cache_fallback_original_fence_rechecks_after_json_encoding() {
    let (client,monitor)=fixture(2);
    let reader=client.stage_cached_chat_views(Some(&monitor),CancellationToken::new()).unwrap();
    let publication=reader.publish(CHAT,CancellationToken::new()).unwrap().unwrap();
    let owner=client.task_watch_authority.clone();let wiped=Arc::new(AtomicBool::new(false));
    let result=publication.with_window(|window| {
        let output=encoded_probe(&window.chat,wiped.clone());owner.deny_cached_chat(Some(CHAT))?;Ok(output)
    });
    assert!(matches!(result,Err(Error::Cancelled)));assert!(wiped.load(std::sync::atomic::Ordering::SeqCst));
}

#[path = "chat_first_page_tests.rs"]
mod first_page_tests;
