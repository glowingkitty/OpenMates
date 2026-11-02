//! Actual shared send helpers/protocol with synthetic explicit credentials and AES.
//! No product/account/AI execution and no real CryptoKey claim from native ports.
// contract-test: supporting surface=sdks.rust assertions=sdk.surface.semantic-parity
use super::*;
use crate::crypto::master::{MasterCrypto, MasterCryptoFuture};
use base64::Engine as _;
use futures_util::{SinkExt, StreamExt};
use std::sync::Arc;
use std::{
    future::{Future, poll_fn},
    task::Poll,
};
use tokio_tungstenite::tungstenite::Message as Frame;
const OWNER: &str = "11111111-1111-4111-8111-111111111111";
const CHAT: &str = "22222222-2222-4222-8222-222222222222";
const TURN: &str = "33333333-3333-4333-8333-333333333333";
const MESSAGE: &str = "44444444-4444-4444-8444-444444444444";
struct Port;
impl MasterCrypto for Port {
    fn encrypt<'a>(&'a self, iv: &'a [u8; 12], plain: &'a [u8]) -> MasterCryptoFuture<'a> {
        Box::pin(async move {
            crypto::encrypt_aead(plain, &[7; 32], iv, &[]).map(zeroize::Zeroizing::new)
        })
    }
    fn decrypt<'a>(&'a self, iv: &'a [u8; 12], cipher: &'a [u8]) -> MasterCryptoFuture<'a> {
        Box::pin(async move { crypto::decrypt_aead(cipher, &[7; 32], iv, &[]) })
    }
}
fn client(mode: &str, team: bool) -> Client {
    let mut session = super::super::sdk_boundary_tests::session();
    session.api_url = "http://127.0.0.1:1".into();
    session.master_key = zeroize::Zeroizing::new([7; 32]);
    session.active_team_id = team.then(|| CHAT.into());
    let mut c = Client::new("http://127.0.0.1:1", Some(session)).unwrap();
    c.user = json!({"id":OWNER});
    if mode != "native" {
        let mut credentials = super::super::credentials::BrowserCredentials::from_native_session(
            c.session.take().unwrap(),
        );
        if mode == "opaque" {
            credentials.master = MasterCapability::opaque_for_test(Arc::new(Port));
        }
        c.browser_credentials = Some(credentials);
        c.browser_authority = Some(super::super::browser::BrowserAuthority {
            principal: OWNER.into(),
            persistence: super::super::browser::BrowserPersistence::MemoryOnly,
            owner_guards: true,
        });
        c.browser_transport = true;
    }
    if team {
        c.team_key = Some((CHAT.into(), zeroize::Zeroizing::new([7; 32])));
    }
    c
}
#[tokio::test]
async fn actual_turn_factory_native_raw_and_opaque_never_reuse_master_and_emit_legacy_wrappers() {
    let fixture: Value = serde_json::from_str(include_str!(
        "../../tests/fixtures/send-opaque-capability.json"
    ))
    .unwrap();
    assert_eq!(fixture["cases"].as_array().unwrap().len(), 10);
    for mode in ["native", "raw_browser", "opaque"] {
        let c = client(mode, false);
        let cap = c.cached_wrapping_capability().unwrap();
        let (key, wire) = c
            .turn_chat_material_with_capability(None, &cap)
            .await
            .unwrap();
        assert_ne!(*key, [7; 32]);
        assert_eq!(
            &*super::super::workspaces::server_field_tests::strict_legacy(&wire, &[7; 32]),
            key.as_ref()
        );
    }
}
#[tokio::test]
async fn metadata_keeps_raw_team_index_bytes_and_message_codec_but_opaque_default_is_id_only() {
    for mode in ["native", "raw_browser", "opaque"] {
        for team in [false, true] {
            let mut c = client(mode, team);
            let options = SendOptions::default();
            let value = c
                .turn_chat_metadata(
                    CHAT,
                    "Synthetic input",
                    &[9; 32],
                    "synthetic-wrapper",
                    1,
                    team.then_some(CHAT),
                    true,
                    &options,
                )
                .await
                .unwrap();
            let id_only = mode == "opaque" && !team;
            assert_eq!(value.get("encrypted_slug").is_none(), id_only);
            assert_eq!(value.get("slug_lookup_hash").is_none(), id_only);
            if !id_only {
                // TypeScript parity: message prefix plus the chat ID, never the bare message.
                let slug = crypto::normalize_object_slug(&format!("synthetic-input-{}", CHAT.to_lowercase())).unwrap();
                assert_eq!(
                    value["slug_lookup_hash"],
                    crypto::object_slug_lookup_hash(&slug, &[7; 32]).unwrap()
                );
                assert_eq!(
                    crypto::decrypt_combined(value["encrypted_slug"].as_str().unwrap(), &[9; 32])
                        .unwrap(),
                    slug
                );
            }
            let title = base64::engine::general_purpose::STANDARD
                .decode(value["encrypted_title"].as_str().unwrap())
                .unwrap();
            assert!(title.starts_with(b"OM"));
            assert_eq!(
                crypto::decrypt_combined(value["encrypted_title"].as_str().unwrap(), &[9; 32])
                    .unwrap(),
                ""
            );
        }
    }
}
#[tokio::test]
async fn explicit_opaque_slug_public_send_refuses_before_http_or_callbacks() {
    let mut c = client("opaque", false);
    let before = c
        .inventory_network
        .load(std::sync::atomic::Ordering::SeqCst);
    let (tx, mut rx) = mpsc::channel(4);
    let options = SendOptions {
        slug: Some("explicit-slug".into()),
        ..Default::default()
    };
    assert!(matches!(
        c.send(
            None,
            "synthetic input",
            options,
            tx,
            CancellationToken::new()
        )
        .await,
        Err(Error::Unavailable {
            code: "opaque_slug_index_unavailable",
            ..
        })
    ));
    assert_eq!(
        c.inventory_network
            .load(std::sync::atomic::Ordering::SeqCst),
        before
    );
    assert!(rx.try_recv().is_err());
}
#[tokio::test]
async fn plaintext_queue_reservation_never_commits_after_cancel_owner_key_or_denial() {
    for event in ["user", "operation", "owner", "master", "denial"] {
        let mut c = client("opaque", false);
        let operation = CancellationToken::new();
        c.set_operation_cancel(operation.clone());
        let cancel = CancellationToken::new();
        let owner = c.task_watch_authority.clone();
        let master = c.master_capability().unwrap();
        let scope = AsyncCryptoScope::begin(&c).unwrap();
        let (tx, mut rx) = mpsc::channel(1);
        tx.try_send(StreamUpdate::Status("prefill".into()))
            .unwrap_or_else(|_| panic!("fixture queue"));
        let mut call = Box::pin(c.deliver_turn_update(
            &scope,
            CHAT,
            &tx,
            &cancel,
            StreamUpdate::Content {
                content: "private pending content".into(),
                thinking: "private pending thought".into(),
                mate: String::new(),
            },
        ));
        poll_fn(|cx| match call.as_mut().poll(cx) {
            Poll::Pending => Poll::Ready(()),
            Poll::Ready(_) => panic!("must reserve behind prefill"),
        })
        .await;
        match event {
            "user" => cancel.cancel(),
            "operation" => operation.cancel(),
            "owner" => owner.cancel.cancel(),
            "master" => master.invalidate(),
            "denial" => {
                owner.deny_cached_chat(Some(CHAT)).unwrap();
                let _ = rx.recv().await;
            }
            _ => unreachable!(),
        }
        assert!(matches!(
            crate::platform::time::timeout(Duration::from_secs(3), call.as_mut())
                .await
                .unwrap(),
            Err(Error::Cancelled)
        ));
        drop(call);
        if event != "denial" {
            assert!(matches!(rx.recv().await, Some(StreamUpdate::Status(_))));
        }
        assert!(rx.try_recv().is_err());
    }
}
async fn emit(
    ws: &mut tokio_tungstenite::WebSocketStream<tokio::net::TcpStream>,
    kind: &str,
    payload: Value,
) {
    ws.send(Frame::Text(
        json!({"type":kind,"payload":payload}).to_string().into(),
    ))
    .await
    .unwrap();
}
#[tokio::test]
async fn real_core_queued_protocol_decrypts_master_memories_without_leaking_them_or_forcing_routing()
 {
    for mode in ["native", "opaque"] {
        let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
        let address = listener.local_addr().unwrap();
        let peer = tokio::spawn(async move {
            let (stream, _) = listener.accept().await.unwrap();
            let mut ws = tokio_tungstenite::accept_async(stream).await.unwrap();
            let mut admitted = None;
            while let Some(raw) = ws.next().await {
                let raw = raw.unwrap();
                if matches!(raw, Frame::Close(_)) {
                    return admitted.expect("actual admission");
                }
                let event: Value = serde_json::from_str(&raw.into_text().unwrap()).unwrap();
                match event["type"].as_str().unwrap() {
                    "set_active_chat" => assert_eq!(event["payload"]["chat_id"], CHAT),
                    "personal_send_context_snapshot" => {
                        let memory = crypto::server_fields::encrypt_text(
                            "{\"private\":\"never-auto-share-memo\"}",
                            &[7; 32],
                            &[],
                        )
                        .unwrap();
                        let settings=crypto::server_fields::encrypt_text("{\"rule_documents\":[{\"id\":\"rule\",\"document\":\"never-auto-share-rule\",\"source\":\"personal\"}]}",&[7;32],&[]).unwrap();
                        emit(&mut ws,"personal_send_context_snapshot_result",json!({"success":true,"unchanged":false,"request_id":event["payload"]["request_id"],"turn_id":TURN,"receipt_id":"synthetic-receipt","privacy_generation":1,"project_candidates":[],"personal_memories":{"memories":[{"id":"memory","app_id":"synthetic","item_type":"profile","encrypted_item_json":memory}],"encrypted_settings":settings}})).await;
                    }
                    "chat_turn_admit" => {
                        let body = event["payload"].clone();
                        let wire = body.to_string();
                        assert!(!wire.contains("never-auto-share-memo"));
                        assert!(!wire.contains("never-auto-share-rule"));
                        assert!(body["inference_request"].get("model").is_none());
                        assert!(body["inference_request"].get("provider").is_none());
                        emit(&mut ws,"chat_turn_preflight_ack",json!({"turn_id":TURN,"preflight_id":"synthetic-preflight","committed_messages_v":1})).await;
                        emit(
                            &mut ws,
                            "chat_message_confirmed",
                            json!({"chat_id":CHAT,"message_id":MESSAGE,"new_messages_v":1}),
                        )
                        .await;
                        emit(&mut ws,"message_queued",json!({"chat_id":CHAT,"message_id":MESSAGE,"user_message_id":MESSAGE,"turn_id":TURN,"recovery_turn_id":TURN,"queue_mode":"follow_up","queue_revision":1})).await;
                        admitted = Some(body);
                    }
                    _ => panic!("unexpected protocol effect"),
                }
            }
            panic!("missing cleanup close")
        });
        let (inner, _) = tokio_tungstenite::connect_async(format!("ws://{address}"))
            .await
            .unwrap();
        let mut socket = transport::test_socket(inner);
        let mut c = client(mode, false);
        let cap = c.cached_wrapping_capability().unwrap();
        let (key, wrapped) = c
            .turn_chat_material_with_capability(None, &cap)
            .await
            .unwrap();
        let mut chat = Chat {
            id: CHAT.into(),
            ..Default::default()
        };
        let (tx, _rx) = mpsc::channel(16);
        let options = SendOptions {
            pii_detection: false,
            task_update_jobs: false,
            response_timeout_ms: Some(2_000),
            ..Default::default()
        };
        let generation = c.generation;
        let mut trace = SendTrace::new();
        let result = c
            .send_on_socket(
                &mut socket,
                CHAT,
                TURN,
                MESSAGE,
                "synthetic input",
                &key,
                &wrapped,
                0,
                true,
                &[],
                &mut chat,
                &tx,
                &CancellationToken::new(),
                generation,
                None,
                &options,
                &mut trace,
            )
            .await
            .unwrap();
        assert!(matches!(result.status, SendStatus::Queued));
        assert_eq!(result.chat.messages[0].content, "synthetic input");
        let _ = socket.close(None).await;
        let body = crate::platform::time::timeout(Duration::from_secs(3), peer)
            .await
            .unwrap()
            .unwrap();
        assert_eq!(
            body["encrypted_chat_metadata"]
                .get("slug_lookup_hash")
                .is_none(),
            mode == "opaque"
        );
        assert_eq!(
            &*super::super::workspaces::server_field_tests::strict_legacy(
                body["encrypted_chat_key"].as_str().unwrap(),
                &[7; 32]
            ),
            key.as_ref()
        );
    }
}
#[test]
fn accepted_outcome_release_rechecks_generation_owner_credentials_and_negative_scope() {
    for event in [
        "generation",
        "owner",
        "credentials",
        "denial",
        "master",
        "caller",
    ] {
        let mut c = client("opaque", false);
        let scope = AsyncCryptoScope::begin(&c).unwrap();
        let caller = CancellationToken::new();
        let outcome = Plain::new(SendObservations::default().finish(
            Chat {
                id: CHAT.into(),
                title: "private completed title".into(),
                ..Default::default()
            },
            MESSAGE,
            None,
            SendStatus::Queued,
        ));
        match event {
            "generation" => c.generation += 1,
            "owner" => c.user["id"] = json!(CHAT),
            "credentials" => c.forget_session(),
            "denial" => c.task_watch_authority.deny_cached_chat(Some(CHAT)).unwrap(),
            "master" => c.master_capability().unwrap().invalidate(),
            "caller" => caller.cancel(),
            _ => unreachable!(),
        };
        assert!(
            c.release_send_outcome(&scope, CHAT, &caller, outcome)
                .is_err()
        );
    }
}
#[test]
fn owned_send_model_wipers_erase_nested_private_text_without_public_destructor_changes() {
    let mut prepared = crate::privacy::PreparedPrivacy {
        text: "private input".into(),
        mappings: vec![json!({"value":"private mapping"})],
    };
    prepared.wipe();
    assert!(prepared.text.is_empty());
    assert_eq!(prepared.mappings[0], Value::Null);
    let mut observations = SendObservations::default();
    observations
        .proposals
        .push(json!({"text":"private proposal"}));
    observations.memories.push(SendMemoryRequest {
        request_id: Some("private request".into()),
        requested_keys: vec!["private key".into()],
        approved_keys: vec![],
        entry_count: 1,
    });
    let mut outcome = observations.finish(
        Chat {
            id: CHAT.into(),
            title: "private title".into(),
            ..Default::default()
        },
        MESSAGE,
        None,
        SendStatus::Queued,
    );
    outcome.wipe();
    assert!(outcome.chat.title.is_empty());
    assert!(outcome.chat_id.is_empty());
    assert_eq!(outcome.task_proposals[0], Value::Null);
    assert!(outcome.app_settings_memory_requests[0].requested_keys[0].is_empty());
    assert_eq!(outcome.app_settings_memory_requests[0].entry_count, 0);
}

#[tokio::test]
async fn metadata_reservation_cancels_without_waiting_for_receiver_drain() {
    for update in [
        StreamUpdate::Started {
            chat_id: CHAT.into(),
            message_id: MESSAGE.into(),
            expects_reply: true,
        },
        StreamUpdate::Submitted {
            chat_id: CHAT.into(),
            message_id: MESSAGE.into(),
        },
        StreamUpdate::Admitted {
            chat_id: CHAT.into(),
            message_id: MESSAGE.into(),
        },
        StreamUpdate::Status("queued static status".into()),
    ] {
        let c = client("opaque", false);
        let scope = AsyncCryptoScope::begin(&c).unwrap();
        let cancel = CancellationToken::new();
        let (tx, mut rx) = mpsc::channel(1);
        tx.try_send(StreamUpdate::Status("prefill".into()))
            .unwrap_or_else(|_| panic!("fixturequeue"));
        let mut call = Box::pin(c.deliver_turn_update(&scope, CHAT, &tx, &cancel, update));
        poll_fn(|cx| match call.as_mut().poll(cx) {
            Poll::Pending => Poll::Ready(()),
            Poll::Ready(_) => panic!("must reserve"),
        })
        .await;
        cancel.cancel();
        assert!(matches!(
            crate::platform::time::timeout(Duration::from_secs(3), call.as_mut())
                .await
                .unwrap(),
            Err(Error::Cancelled)
        ));
        drop(call);
        assert!(matches!(rx.recv().await, Some(StreamUpdate::Status(_))));
        assert!(rx.try_recv().is_err());
    }
}
#[test]
fn unpolled_owned_update_future_cannot_publish_to_channel() {
    let c = client("opaque", false);
    let scope = AsyncCryptoScope::begin(&c).unwrap();
    let cancel = CancellationToken::new();
    let (tx, mut rx) = mpsc::channel(1);
    let future = c.deliver_turn_update(
        &scope,
        CHAT,
        &tx,
        &cancel,
        StreamUpdate::Content {
            content: "private unpolled".into(),
            thinking: String::new(),
            mate: String::new(),
        },
    );
    drop(future);
    assert_eq!(tx.capacity(), 1);
    assert!(rx.try_recv().is_err());
}
