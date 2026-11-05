//! Synthetic focused acceptance; execute in isolated CI, never real profiles.
use super::*;
use crate::client::{ChatFirstPageCandidate, ChatFirstPagePublication, ChatFirstPageSink};
use std::sync::atomic::{AtomicUsize, Ordering};

struct Sink {
    calls: Arc<AtomicUsize>,
    expected_rows: usize,
    publication: Option<ChatFirstPagePublication>,
    request: CancellationToken,
    change: &'static str,
}
impl ChatFirstPageSink for Sink {
    fn admit_checkpoint<'a>(
        &'a mut self,
        _client: &'a Client,
        _checkpoint_json_bytes: usize,
    ) -> std::pin::Pin<Box<dyn std::future::Future<Output = Result<bool>> + Send + 'a>> {
        // Explicit synthetic capacity policy. Real adapters report their own
        // total encoded checkpoint/storage capacity before retaining the page.
        Box::pin(async { Ok(true) })
    }
    fn first_page<'a>(
        &'a mut self,
        client: &'a mut Client,
        candidate: ChatFirstPageCandidate,
    ) -> std::pin::Pin<Box<dyn std::future::Future<Output = Result<()>> + Send + 'a>> {
        Box::pin(async move {
            assert!(
                !client.history.contains_key(CHAT),
                "interim rows never become complete history"
            );
            assert_eq!(
                client.selected_first_pages[CHAT].messages.len(),
                self.expected_rows
            );
            let mut receipt = crate::client::ChatRefreshDurableReceipt {
                ciphertext_sha256: candidate.ciphertext_sha256()?,
                credential_revision: candidate.credential_revision(),
            };
            client.acknowledge_credentials(candidate.credential_revision())?;
            if self.change == "wrong-receipt" {
                receipt.ciphertext_sha256 = "00".repeat(32);
            }
            let publication = client.commit_chat_first_page(candidate, receipt)?;
            self.calls.fetch_add(1, Ordering::SeqCst);
            let original_epoch = client.fresh_auth.operation_epoch();
            let original_revision = client.credential_revision;
            let original_operation = client.operation_cancel.clone();
            let original_digest =
                crate::client::sha256(&serde_json::to_string(&client.ciphertext_snapshot())?);
            match self.change {
                "request" => self.request.cancel(),
                "operation" => client.set_operation_cancel(CancellationToken::new()),
                "owner-key" => {
                    let mut session = client.clone_session().unwrap();
                    session.master_key = Zeroizing::new([8; 32]);
                    let api = session.api_url.clone();
                    client.reset(&api, Some(session))?;
                }
                "denial" => client.task_watch_authority.deny_cached_chat(Some(CHAT))?,
                "snapshot" => {
                    client.embeds.insert("new".into(), json!({"id":"new"}));
                }
                "identity" => client.set_identity(crate::client::ClientIdentity::Npm),
                "interactive" => client.set_interactive(!client.options().interactive),
                "app-origin" => {
                    client.set_app_origin(Some("https://changed.example.test".into()))?
                }
                "none" => {}
                _ => unreachable!(),
            }
            if matches!(self.change, "identity" | "interactive" | "app-origin") {
                // These regressions specifically bypass the previous token,
                // crypto/revision and ciphertext continuation restrictions.
                assert_ne!(client.fresh_auth.operation_epoch(), original_epoch);
                assert_eq!(client.credential_revision, original_revision);
                assert!(client.operation_cancel == original_operation);
                assert!(!original_operation.is_cancelled());
                assert_eq!(
                    crate::client::sha256(&serde_json::to_string(&client.ciphertext_snapshot())?),
                    original_digest
                );
            }
            self.publication = Some(publication);
            Ok(())
        })
    }
}
fn cold_responses(client: &mut Client, finish: bool) -> Vec<(String, u16, Value)> {
    let rows = client.history[CHAT].clone();
    let mut responses = vec![
        settlement_metadata(client),
        settlement_metadata(client),
        (
            format!(
                "GET /v1/chats/{CHAT}/messages/window?direction=latest&limit=100&respect_compression_boundary=false HTTP/1.1"
            ),
            200,
            json!({"messages":[rows[1].clone()],"server_message_count":2,"has_more_before":true,
                "start_cursor":{"created_at":1,"message_id":rows[1]["id"]}}),
        ),
    ];
    if finish {
        responses.push((format!("GET /v1/chats/{CHAT}/messages/window?direction=before&limit=100&respect_compression_boundary=false&before_timestamp=1&before_message_id=10000000-0000-4000-8000-000000000001 HTTP/1.1"),200,
        json!({"messages":[rows[0].clone()],"has_more_before":false})));
    }
    responses
}
// contract-test: supporting surface=sdk assertions=sdk.library.explicit-headless,sdk.encryption.local-only
#[tokio::test]
async fn cold_first_page_is_committed_before_older_request_and_canonical_final_stays_complete() {
    tokio::time::timeout(std::time::Duration::from_secs(10), async {
        let calls = Arc::new(AtomicUsize::new(0));
        let observed = calls.clone();
        let (mut client, monitor, server) = settlement_fixture_observed(
            2,
            2,
            |client| cold_responses(client, true),
            move |_| {
                Some(Arc::new(move |path| {
                    if path.contains("direction=before") {
                        assert_eq!(observed.load(Ordering::SeqCst), 1);
                    }
                }))
            },
        )
        .await;
        client.history.remove(CHAT);
        let request = CancellationToken::new();
        let mut sink = Sink {
            expected_rows: 1,
            calls: calls.clone(),
            publication: None,
            request: request.clone(),
            change: "none",
        };
        let read = client
            .read_chat_view_prefer_cache_with_first_page(Some(&monitor), CHAT, request, &mut sink)
            .await
            .unwrap();
        assert_eq!(calls.load(Ordering::SeqCst), 1);
        let interim = sink.publication.take().unwrap().into_window().unwrap();
        assert!(interim.cached && interim.refreshing && !interim.history_complete);
        assert_eq!(interim.has_more_before, Some(true));
        assert_eq!(interim.pii_restoration, "page_local");
        assert_eq!(interim.chat.messages.len(), 1);
        assert_eq!(interim.chat.messages[0].content, "cached-line-001");
        let ChatViewRead::Canonical(candidate) = read else {
            panic!("cold read must finish canonically")
        };
        let receipt = exact_candidate_receipt(&candidate);
        client
            .acknowledge_credentials(candidate.credential_revision())
            .unwrap();
        let chat = client
            .commit_chat_view(candidate, receipt)
            .unwrap()
            .into_chat()
            .unwrap();
        assert_eq!(chat.messages.len(), 2);
        assert_eq!(client.history[CHAT].len(), 2);
        assert!(!client.sync_message_windows.contains_key(CHAT));
        assert!(!client.selected_first_pages.contains_key(CHAT));
        assert_eq!(
            server.await.unwrap(),
            4,
            "same latest response, no duplicate latest fetch"
        );
    })
    .await
    .unwrap();
}
// contract-test: supporting surface=sdk assertions=sdk.library.explicit-headless,sdk.encryption.local-only
#[tokio::test]
async fn cold_callback_cancellation_key_denial_snapshot_and_wrong_receipt_stop_before_older_io() {
    tokio::time::timeout(std::time::Duration::from_secs(10), async {
        for change in [
            "request",
            "operation",
            "owner-key",
            "denial",
            "snapshot",
            "wrong-receipt",
        ] {
            let (mut client, monitor, server) =
                settlement_fixture(2, 2, |client| cold_responses(client, false)).await;
            client.history.remove(CHAT);
            let request = CancellationToken::new();
            let mut sink = Sink {
                expected_rows: 1,
                calls: Arc::new(AtomicUsize::new(0)),
                publication: None,
                request: request.clone(),
                change,
            };
            assert!(
                client
                    .read_chat_view_prefer_cache_with_first_page(
                        Some(&monitor),
                        CHAT,
                        request,
                        &mut sink
                    )
                    .await
                    .is_err(),
                "{change}"
            );
            assert_eq!(server.await.unwrap(), 3, "{change}");
            if matches!(change, "request" | "operation" | "owner-key" | "denial") {
                assert!(
                    sink.publication.take().unwrap().into_window().is_err(),
                    "{change}"
                );
            }
        }
    })
    .await
    .unwrap();
}
// contract-test: supporting surface=sdk assertions=sdk.library.explicit-headless,sdk.encryption.local-only
#[tokio::test]
async fn opt_in_keeps_warm_cache_and_single_terminal_page_on_their_existing_paths() {
    tokio::time::timeout(std::time::Duration::from_secs(10),async {
        for cold in [false,true] {
            let (mut client,monitor,server)=settlement_fixture(2,2,|client| {
                if !cold {return vec![settlement_metadata(client)];}
                vec![settlement_metadata(client),settlement_metadata(client),
                    (format!("GET /v1/chats/{CHAT}/messages/window?direction=latest&limit=100&respect_compression_boundary=false HTTP/1.1"),200,
                        json!({"messages":client.history[CHAT],"has_more_before":false}))]
            }).await;
            if cold {client.history.remove(CHAT);}
            let request=CancellationToken::new();let mut sink=Sink{expected_rows:1,calls:Arc::new(AtomicUsize::new(0)),publication:None,request:request.clone(),change:"none"};
            let result=client.read_chat_view_prefer_cache_with_first_page(Some(&monitor),CHAT,request,&mut sink).await.unwrap();
            assert_eq!(sink.calls.load(Ordering::SeqCst),0);
            assert!(if cold {matches!(result,ChatViewRead::Canonical(_))} else {matches!(result,ChatViewRead::CacheSettled(_))});
            assert_eq!(server.await.unwrap(),if cold {3}else{1});
        }
    }).await.unwrap();
}
// contract-test: supporting surface=sdk assertions=sdk.library.explicit-headless,sdk.encryption.local-only
#[tokio::test]
async fn first_page_restores_only_loaded_user_mappings_without_claiming_older_history() {
    tokio::time::timeout(std::time::Duration::from_secs(10),async {
        let (mut client,monitor,server)=settlement_fixture(3,3,|client| {
            let rows=client.history.get_mut(CHAT).unwrap();
            for (index,placeholder,original) in [(0,"[older]","Old user"),(1,"[assistant]","Ignored assistant"),(2,"[known]","Current user")] {
                rows[index]["encrypted_pii_mappings"]=json!(crypto::encrypt_combined(&json!([{"placeholder":placeholder,"original":original}]).to_string(),&[9;32]).unwrap());
            }
            rows[2]["encrypted_content"]=json!(crypto::encrypt_combined("[older] [known] [assistant]",&[9;32]).unwrap());
            let rows=rows.clone();
            vec![settlement_metadata(client),settlement_metadata(client),
                (format!("GET /v1/chats/{CHAT}/messages/window?direction=latest&limit=100&respect_compression_boundary=false HTTP/1.1"),200,
                    json!({"messages":[rows[1].clone(),rows[2].clone()],"server_message_count":3,"has_more_before":true,"start_cursor":{"created_at":1,"message_id":rows[1]["id"]}})),
                (format!("GET /v1/chats/{CHAT}/messages/window?direction=before&limit=100&respect_compression_boundary=false&before_timestamp=1&before_message_id=10000000-0000-4000-8000-000000000001 HTTP/1.1"),200,
                    json!({"messages":[rows[0].clone()],"has_more_before":false}))]
        }).await;
        client.history.remove(CHAT);
        let request=CancellationToken::new();let mut sink=Sink{expected_rows:2,calls:Arc::new(AtomicUsize::new(0)),publication:None,request:request.clone(),change:"none"};
        let result=client.read_chat_view_prefer_cache_with_first_page(Some(&monitor),CHAT,request,&mut sink).await.unwrap();
        let interim=sink.publication.take().unwrap().into_window().unwrap();
        assert_eq!(interim.chat.messages[1].content,"[older] Current user [assistant]");
        assert_eq!(interim.pii_restoration,"page_local");assert!(!interim.history_complete);
        assert!(matches!(result,ChatViewRead::Canonical(_)));assert_eq!(client.history[CHAT].len(),3);
        assert_eq!(server.await.unwrap(),4);
    }).await.unwrap();
}

// contract-test: supporting surface=sdk assertions=sdk.library.explicit-headless,sdk.encryption.local-only
#[tokio::test]
async fn setters_after_legitimate_first_page_commit_cannot_rebind_strict_continuation() {
    tokio::time::timeout(std::time::Duration::from_secs(10), async {
        for change in ["identity", "interactive", "app-origin"] {
            let (mut client, monitor, server) =
                settlement_fixture(2, 2, |client| cold_responses(client, false)).await;
            client.history.remove(CHAT);
            let request = CancellationToken::new();
            let calls = Arc::new(AtomicUsize::new(0));
            let mut sink = Sink {
                expected_rows: 1,
                calls: calls.clone(),
                publication: None,
                request: request.clone(),
                change,
            };
            let result = client
                .read_chat_view_prefer_cache_with_first_page(
                    Some(&monitor),
                    CHAT,
                    request,
                    &mut sink,
                )
                .await;
            assert!(
                matches!(result, Err(Error::Cancelled)),
                "{change}: original operation must be rejected"
            );
            assert_eq!(
                calls.load(Ordering::SeqCst),
                1,
                "{change}: sink legitimately committed BEFORE setter"
            );
            assert!(
                sink.publication.is_some(),
                "{change}: regression must reach post-commit remainder"
            );
            assert!(
                !client.history.contains_key(CHAT),
                "{change}: cannot mint new canonical history"
            );
            assert_eq!(client.selected_first_pages[CHAT].messages.len(), 1);
            assert_eq!(
                server.await.unwrap(),
                3,
                "{change}: metadata+metadata+latest only, no older IO"
            );
        }
    })
    .await
    .unwrap();
}
// contract-test: supporting surface=sdk assertions=sdk.library.explicit-headless,sdk.encryption.local-only
#[tokio::test]
async fn strict_real_hundred_row_first_page_uses_distinct_checkpoint_without_widening_startup() {
    tokio::time::timeout(std::time::Duration::from_secs(10),async {
        let (mut client,monitor,server)=settlement_fixture(140,140,|client| {
            let rows=client.history[CHAT].clone();
            vec![settlement_metadata(client),settlement_metadata(client),
                (format!("GET /v1/chats/{CHAT}/messages/window?direction=latest&limit=100&respect_compression_boundary=false HTTP/1.1"),200,
                    json!({"messages":rows[40..].to_vec(),"server_message_count":140,"has_more_before":true,"start_cursor":{"created_at":40,"message_id":rows[40]["id"]},"end_cursor":{"created_at":139,"message_id":rows[139]["id"]}})),
                (format!("GET /v1/chats/{CHAT}/messages/window?direction=before&limit=100&respect_compression_boundary=false&before_timestamp=40&before_message_id=10000000-0000-4000-8000-000000000040 HTTP/1.1"),200,
                    json!({"messages":rows[..40].to_vec(),"has_more_before":false}))]
        }).await;
        client.history.remove(CHAT);let request=CancellationToken::new();
        let mut sink=Sink{expected_rows:100,calls:Arc::new(AtomicUsize::new(0)),publication:None,request:request.clone(),change:"none"};
        let result=client.read_chat_view_prefer_cache_with_first_page(Some(&monitor),CHAT,request,&mut sink).await.unwrap();
        assert_eq!(sink.calls.load(Ordering::SeqCst),1,"real strict100 must NOT silently skip the first page");
        let window=sink.publication.take().unwrap().into_window().unwrap();assert_eq!(window.chat.messages.len(),100);assert_eq!(window.chat.messages[0].content,"cached-line-040");assert_eq!(window.chat.messages[99].content,"cached-line-139");assert!(!window.history_complete&&window.refreshing);
        let ChatViewRead::Canonical(candidate)=result else{panic!("final must remain canonical")};
        let receipt=exact_candidate_receipt(&candidate);client.acknowledge_credentials(candidate.credential_revision()).unwrap();assert_eq!(client.commit_chat_view(candidate,receipt).unwrap().into_chat().unwrap().messages.len(),140);
        assert!(!client.selected_first_pages.contains_key(CHAT));assert_eq!(server.await.unwrap(),4);
    }).await.unwrap();
}

struct CapacitySink {
    mode: &'static str,
    called: Arc<AtomicUsize>,
}
impl ChatFirstPageSink for CapacitySink {
    fn admit_checkpoint<'a>(
        &'a mut self,
        client: &'a Client,
        bytes: usize,
    ) -> std::pin::Pin<Box<dyn std::future::Future<Output = Result<bool>> + Send + 'a>> {
        Box::pin(async move {
            assert!(
                client.selected_first_pages.is_empty(),
                "quota decision precedes retention"
            );
            assert!(
                bytes
                    > serde_json::to_vec(&client.ciphertext_snapshot())
                        .unwrap()
                        .len()
            );
            self.called.fetch_add(1, Ordering::SeqCst);
            match self.mode {
                "quota" => Ok(false),
                "io" => Err(Error::Io),
                _ => unreachable!(),
            }
        })
    }
    fn first_page<'a>(
        &'a mut self,
        _client: &'a mut Client,
        _candidate: ChatFirstPageCandidate,
    ) -> std::pin::Pin<Box<dyn std::future::Future<Output = Result<()>> + Send + 'a>> {
        Box::pin(async { panic!("refused/error capacity must never publish or fabricate ACK") })
    }
}
// contract-test: supporting surface=sdk assertions=sdk.library.explicit-headless,sdk.encryption.local-only
#[tokio::test]
async fn declared_quota_alone_skips_optional_preview_while_io_errors_fail_closed_without_retention()
{
    tokio::time::timeout(std::time::Duration::from_secs(10), async {
        for mode in ["quota", "io"] {
            let (mut client, monitor, server) =
                settlement_fixture(2, 2, |client| cold_responses(client, mode == "quota")).await;
            client.history.remove(CHAT);
            let mut sink = CapacitySink {
                mode,
                called: Arc::new(AtomicUsize::new(0)),
            };
            let result = client
                .read_chat_view_prefer_cache_with_first_page(
                    Some(&monitor),
                    CHAT,
                    CancellationToken::new(),
                    &mut sink,
                )
                .await;
            assert_eq!(sink.called.load(Ordering::SeqCst), 1);
            assert!(client.selected_first_pages.is_empty());
            if mode == "quota" {
                assert!(matches!(result, Ok(ChatViewRead::Canonical(_))));
                assert_eq!(client.history[CHAT].len(), 2);
            } else {
                assert!(matches!(result, Err(Error::Io)));
                assert!(!client.history.contains_key(CHAT));
            }
            assert_eq!(server.await.unwrap(), if mode == "quota" { 4 } else { 3 });
        }
    })
    .await
    .unwrap();
}
// contract-test: supporting surface=sdk assertions=sdk.library.explicit-headless,sdk.encryption.local-only
#[test]
fn selected_checkpoint_hundred_rows_roundtrips_while_old_missing_map_and_downgrade_stay_incomplete()
{
    let (mut client, _) = fixture(140);
    let row = client.chats[CHAT].clone();
    let rows = client.history[CHAT][40..].to_vec();
    assert!(
        crate::client::sync_windows::message_rows(&rows, CHAT, 16 * 1024 * 1024).is_err(),
        "startup/window20 policy stays unchanged"
    );
    let mut input = rows.clone();
    input[0]["content"] = json!("NEVER_CLEAR_EXTENSION");
    input[0]["unknown_extension"] = json!({"private":"NEVER_CLEAR_EXTENSION"});
    let page = json!({"messages":input,"server_message_count":140,"has_more_before":true,"start_cursor":{"created_at":40,"message_id":rows[0]["id"]},"end_cursor":{"created_at":139,"message_id":rows[99]["id"]}});
    let selected = client.prepare_selected_first_page(&row, &page).unwrap();
    assert_eq!(selected.messages.len(), 100);
    client.history.remove(CHAT);
    client.selected_first_pages.insert(CHAT.into(), selected);
    let snapshot = client.ciphertext_snapshot();
    let encoded = serde_json::to_string(&snapshot).unwrap();
    assert!(!encoded.contains("NEVER_CLEAR_EXTENSION"));
    assert!(snapshot["sync_message_windows"].is_null());
    let restored =
        crate::client::selected_first_page::restore(snapshot.get("selected_first_pages")).unwrap();
    assert_eq!(restored[CHAT].messages.len(), 100);
    assert!(snapshot["history"].get(CHAT).is_none());
    let cached = client.owned_settlement_rows(&row).unwrap();
    assert_eq!(
        cached.len(),
        100,
        "all owned cached rows participate in warm settlement"
    );
    let mut older = snapshot.clone();
    older
        .as_object_mut()
        .unwrap()
        .remove("selected_first_pages");
    client.restore_ciphertext_snapshot(&older).unwrap();
    assert!(client.selected_first_pages.is_empty());
    assert!(!client.history.contains_key(CHAT));
    assert!(
        client
            .ciphertext_snapshot()
            .get("selected_first_pages")
            .is_none(),
        "empty optional map must not alter old snapshot shape"
    );
    client.restore_ciphertext_snapshot(&snapshot).unwrap();
    assert_eq!(client.selected_first_pages[CHAT].messages.len(), 100);
    let startup = client
        .stage_cached_chat_views(None, CancellationToken::new())
        .unwrap();
    assert!(
        startup
            .publish(CHAT, CancellationToken::new())
            .unwrap()
            .is_none(),
        "new selected map is excluded from startup projection"
    );
    for (field, value) in [
        ("history_complete", json!(true)),
        ("server_message_count", json!(99)),
        (
            "start_cursor",
            json!({"created_at":1,"message_id":rows[0]["id"]}),
        ),
    ] {
        let mut corrupt = snapshot["selected_first_pages"].clone();
        corrupt[CHAT][field] = value;
        assert!(
            crate::client::selected_first_page::restore(Some(&corrupt)).is_err(),
            "{field}"
        );
    }
    client.set_team(None).unwrap();
    assert!(client.selected_first_pages.is_empty());
    client.restore_ciphertext_snapshot(&snapshot).unwrap();
    let session = client.clone_session().unwrap();
    let api = session.api_url.clone();
    client.reset(&api, Some(session)).unwrap();
    assert!(client.selected_first_pages.is_empty());
    client.restore_ciphertext_snapshot(&snapshot).unwrap();
    client.forget_session();
    assert!(client.selected_first_pages.is_empty());
}
// contract-test: supporting surface=sdk assertions=sdk.library.explicit-headless,sdk.encryption.local-only
#[tokio::test]
async fn warm_selected_hundred_retains_all_rows_and_older_user_pii_without_history_authority() {
    tokio::time::timeout(std::time::Duration::from_secs(10),async {
        let (mut client,monitor,server)=settlement_fixture(140,140,|client|vec![settlement_metadata(client)]).await;
        let row=client.chats[CHAT].clone();let mut rows=client.history[CHAT][40..].to_vec();
        rows[0]["encrypted_pii_mappings"]=json!(crypto::encrypt_combined(r#"[{"placeholder":"[older_known]","original":"Older cached user"}]"#,&[9;32]).unwrap());
        rows[99]["encrypted_content"]=json!(crypto::encrypt_combined("[older_known]",&[9;32]).unwrap());
        let page=json!({"messages":rows,"server_message_count":140,"has_more_before":true,"start_cursor":{"created_at":40,"message_id":"10000000-0000-4000-8000-000000000040"}});
        let selected=client.prepare_selected_first_page(&row,&page).unwrap();client.history.remove(CHAT);client.selected_first_pages.insert(CHAT.into(),selected);
        let ChatViewRead::CacheSettled(candidate)=client.read_chat_view_prefer_cache(Some(&monitor),CHAT,CancellationToken::new()).await.unwrap()else{panic!("owned selected rows must take existing warm settlement")};
        let receipt=settlement_receipt(&candidate);client.acknowledge_credentials(candidate.credential_revision()).unwrap();let window=client.commit_cache_settlement(candidate,receipt).unwrap().into_window().unwrap();
        assert_eq!(window.chat.messages.len(),100);assert_eq!(window.chat.messages[99].content,"Older cached user");assert!(!window.history_complete);assert_eq!(window.pii_restoration,"all_cached_user_rows");assert!(!client.history.contains_key(CHAT));assert_eq!(server.await.unwrap(),1);
        monitor.deny(ChatMonitorAccessDenial::ChatUnavailable{chat_id:CHAT.into()}).unwrap();assert!(client.ciphertext_snapshot().get("selected_first_pages").is_none(),"known denial never serializes a new usable selected checkpoint");
    }).await.unwrap();
}
struct UnknownCapacitySink;
impl ChatFirstPageSink for UnknownCapacitySink {
    fn first_page<'a>(
        &'a mut self,
        _client: &'a mut Client,
        _candidate: ChatFirstPageCandidate,
    ) -> std::pin::Pin<Box<dyn std::future::Future<Output = Result<()>> + Send + 'a>> {
        Box::pin(async {
            panic!("unknown adapter capacity must conservatively skip optional retention")
        })
    }
}
// contract-test: supporting surface=sdk assertions=sdk.library.explicit-headless,sdk.encryption.local-only
#[tokio::test]
async fn unknown_adapter_capacity_keeps_original_strict_history_without_partial_retention() {
    tokio::time::timeout(std::time::Duration::from_secs(10), async {
        let (mut client, monitor, server) =
            settlement_fixture(2, 2, |client| cold_responses(client, true)).await;
        client.history.remove(CHAT);
        let result = client
            .read_chat_view_prefer_cache_with_first_page(
                Some(&monitor),
                CHAT,
                CancellationToken::new(),
                &mut UnknownCapacitySink,
            )
            .await
            .unwrap();
        assert!(matches!(result, ChatViewRead::Canonical(_)));
        assert_eq!(client.history[CHAT].len(), 2);
        assert!(client.selected_first_pages.is_empty());
        assert_eq!(server.await.unwrap(), 4);
    })
    .await
    .unwrap();
}
// contract-test: supporting surface=sdk assertions=sdk.library.explicit-headless,sdk.encryption.local-only
#[test]
fn selected_strict_page_rejects_hundred_and_first_row_and_sixteen_mib_envelope_overflow() {
    let (client, _) = fixture(101);
    let row = client.chats[CHAT].clone();
    let rows = client.history[CHAT].clone();
    let page = json!({"messages":rows,"server_message_count":102,"has_more_before":true,"start_cursor":{"created_at":0,"message_id":"10000000-0000-4000-8000-000000000000"}});
    assert!(
        matches!(
            client.prepare_selected_first_page(&row, &page),
            Err(Error::Protocol)
        ),
        "never truncate101 rows pretending100 were checkpointed"
    );
    let page = json!({"messages":[client.history[CHAT][0].clone()],"server_message_count":101,"has_more_before":true,"start_cursor":{"created_at":0,"message_id":"10000000-0000-4000-8000-000000000000"},"unknown_extension":"x".repeat(16*1024*1024)});
    assert!(
        matches!(
            client.prepare_selected_first_page(&row, &page),
            Err(Error::Protocol)
        ),
        "strict response envelope cap stays16MiB"
    );
    assert!(client.selected_first_pages.is_empty());
    assert_eq!(
        client.history[CHAT].len(),
        101,
        "no cache eviction on optional admission failure"
    );
}
fn supported_read_id(mode: &str, index: usize) -> String {
    match mode {
        "composite" => format!("2222222222-10000000-0000-4000-8000-{index:012}"),
        "opaque" => format!("legacy_msg_{index:04}"),
        _ => unreachable!(),
    }
}
// contract-test: supporting surface=sdk assertions=sdk.library.explicit-headless,sdk.encryption.local-only
#[tokio::test]
async fn composite_and_opaque_hundred_row_first_page_keep_logical_ids_and_full_hundred_forty_completion()
 {
    tokio::time::timeout(std::time::Duration::from_secs(15),async {
        for mode in ["composite","opaque"] {
            let (mut client,monitor,server)=settlement_fixture(140,140,|client| {
                let rows=client.history.get_mut(CHAT).unwrap();
                for (index,row) in rows.iter_mut().enumerate(){
                    // Keep independent DB UUID alias; it must NOT replace the
                    // deployed logical client ID merely because it is UUID.
                    row["client_message_id"]=json!(supported_read_id(mode,index));
                    row["message_id"]=json!(supported_read_id(mode,index));
                }
                let rows=rows.clone();let first=supported_read_id(mode,40);let last=supported_read_id(mode,139);
                vec![settlement_metadata(client),settlement_metadata(client),
                    (format!("GET /v1/chats/{CHAT}/messages/window?direction=latest&limit=100&respect_compression_boundary=false HTTP/1.1"),200,
                        json!({"messages":rows[40..].to_vec(),"server_message_count":140,"has_more_before":true,"start_cursor":{"created_at":40,"message_id":first},"end_cursor":{"created_at":139,"message_id":last}})),
                    (format!("GET /v1/chats/{CHAT}/messages/window?direction=before&limit=100&respect_compression_boundary=false&before_timestamp=40&before_message_id={first} HTTP/1.1"),200,
                        json!({"messages":rows[..40].to_vec(),"has_more_before":false}))]
            }).await;
            client.history.remove(CHAT);let request=CancellationToken::new();
            let mut sink=Sink{expected_rows:100,calls:Arc::new(AtomicUsize::new(0)),publication:None,request:request.clone(),change:"none"};
            let result=client.read_chat_view_prefer_cache_with_first_page(Some(&monitor),CHAT,request,&mut sink).await.unwrap();
            assert_eq!(sink.calls.load(Ordering::SeqCst),1,"{mode}: first_page may not silently skip100 rows");
            let window=sink.publication.take().unwrap().into_window().unwrap();assert_eq!(window.chat.messages.len(),100);assert_eq!(window.chat.messages[0].id,supported_read_id(mode,40));assert_eq!(window.chat.messages[99].id,supported_read_id(mode,139));assert_eq!(window.chat.messages[0].content,"cached-line-040");assert!(!window.history_complete&&window.refreshing);
            let ChatViewRead::Canonical(candidate)=result else{panic!("{mode}: original full-history result must stay canonical")};let receipt=exact_candidate_receipt(&candidate);client.acknowledge_credentials(candidate.credential_revision()).unwrap();let chat=client.commit_chat_view(candidate,receipt).unwrap().into_chat().unwrap();
            assert_eq!(chat.messages.len(),140);assert_eq!(chat.messages[0].id,supported_read_id(mode,0));assert_eq!(chat.messages[139].id,supported_read_id(mode,139));assert!(!client.selected_first_pages.contains_key(CHAT));assert_eq!(server.await.unwrap(),4,"same latest response, no duplicate fetch");
        }
    }).await.unwrap();
}
// contract-test: supporting surface=sdk assertions=sdk.library.explicit-headless,sdk.encryption.local-only
#[test]
fn selected_cursor_uses_shared_opaque_id_vectors_and_rejects_alias_or_chat_mismatch() {
    let (client, _) = fixture(2);
    let row = client.chats[CHAT].clone();
    let base = client.history[CHAT][1].clone();
    let vectors: Value = serde_json::from_str(include_str!("../../tests/fixtures/message-id-compatibility.json"))
    .unwrap();
    for vector in vectors["cases"].as_array().unwrap() {
        let logical = &vector["value"];
        let valid = vector["valid"].as_bool().unwrap();
        let mut message = base.clone();
        message["client_message_id"] = logical.clone();
        message["message_id"] = logical.clone();
        let page = json!({"messages":[message],"server_message_count":2,"has_more_before":true,"start_cursor":{"created_at":1,"message_id":logical},"end_cursor":{"created_at":1,"message_id":logical}});
        let admitted = client.prepare_selected_first_page(&row, &page);
        assert_eq!(
            admitted.is_ok(),
            valid,
            "{}: helper/cursor acceptance drift",
            vector["id"]
        );
        if let Ok(page) = admitted {
            assert_eq!(&page.messages[0]["client_message_id"], logical);
            assert_eq!(
                page.messages[0]["id"], base["id"],
                "independent DB alias stays untouched"
            );
        }
    }
    let logical = "legacy_msg_0001";
    let mut message = base.clone();
    message["client_message_id"] = json!(logical);
    message["message_id"] = json!(logical);
    let page = json!({"messages":[message],"server_message_count":2,"has_more_before":true,"start_cursor":{"created_at":1,"message_id":logical}});
    for field in ["client_message_id", "message_id", "id"] {
        let mut corrupt = page.clone();
        corrupt["messages"][0][field] = json!(7);
        assert!(
            client.prepare_selected_first_page(&row, &corrupt).is_err(),
            "non-string {field}"
        );
    }
    let mut conflicting = page.clone();
    conflicting["messages"][0]["message_id"] = json!("different-logical-id");
    assert!(
        client
            .prepare_selected_first_page(&row, &conflicting)
            .is_err()
    );
    let mut long_cursor = page.clone();
    long_cursor["start_cursor"]["message_id"] =
        json!("x".repeat(257)); // valid opaque ID, but NOT the first row's ID
    assert!(
        client
            .prepare_selected_first_page(&row, &long_cursor)
            .is_err()
    );
    let mut wrong_chat = page.clone();
    wrong_chat["messages"][0]["chat_id"] = json!("33333333-3333-4333-8333-333333333333");
    assert!(matches!(
        client.prepare_selected_first_page(&row, &wrong_chat),
        Err(Error::Forbidden)
    ));
    let mut wrong_chat_row = row.clone();
    wrong_chat_row["id"] = json!("legacy-chat-not-a-uuid");
    assert!(
        client
            .prepare_selected_first_page(&wrong_chat_row, &page)
            .is_err(),
        "Chat UUID rule remains strict"
    );
    for empty in [Value::Null, json!("")] {
        let mut legacy = page.clone();
        legacy["messages"][0]["client_message_id"] = empty;
        assert!(
            client.prepare_selected_first_page(&row, &legacy).is_ok(),
            "empty/null client alias falls through to same message ID"
        );
    }
}
// contract-test: supporting surface=sdk assertions=sdk.library.explicit-headless,sdk.encryption.local-only
#[test]
fn selected_hundred_row_normalized_budget_remains_distinct_from_startup_twenty_window_budget() {
    let (client, _) = fixture(101);
    let row = client.chats[CHAT].clone();
    let mut rows = client.history[CHAT][..100].to_vec();
    for (index, message) in rows.iter_mut().enumerate() {
        message["client_message_id"] = json!(supported_read_id("opaque", index));
        message["message_id"] = json!(supported_read_id("opaque", index));
        message["encrypted_content"] =
            json!(crypto::encrypt_combined(&"x".repeat(4096), &[9; 32]).unwrap());
    }
    let page = json!({"messages":rows,"server_message_count":101,"has_more_before":true,"start_cursor":{"created_at":0,"message_id":supported_read_id("opaque",0)},"end_cursor":{"created_at":99,"message_id":supported_read_id("opaque",99)}});
    assert!(
        serde_json::to_vec(&page).unwrap().len()
            > crate::client::sync_windows::MAX_NORMALIZED_BYTES,
        "fixture must exceed20-window normalized budget"
    );
    let selected = client.prepare_selected_first_page(&row, &page).unwrap();
    assert_eq!(selected.messages.len(), 100);
    let mut serialized = json!({});
    serialized[CHAT] = serde_json::to_value(&selected).unwrap();
    let restored = crate::client::selected_first_page::restore(Some(&serialized)).unwrap();
    assert_eq!(
        restored[CHAT].messages.len(),
        100,
        "selected100 restore has the same independent16MiB bound"
    );
    assert!(
        crate::client::sync_windows::message_rows(
            page["messages"].as_array().unwrap(),
            CHAT,
            16 * 1024 * 1024
        )
        .is_err(),
        "startup20 row cap was not widened"
    );
}
