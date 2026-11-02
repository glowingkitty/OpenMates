//! Synthetic AES primitive and owned bounded-row regressions, authored UNRUN.
//! These tests do not claim real CryptoKey, backend, browser or account proof.
//! The loopback endpoint is inert; no test invokes product HTTP or sockets.
//! Actual capability bytes are known synthetic keys, never placeholder Session
//! material used as an opaque master or a fabricated authentication receipt.
// contract-test-file: tooling
use super::*;
use super::super::message_window::{MessageWindowDirection,MessageWindowOptions};
use super::super::saved_chat_read::{SavedChatContentMode,SavedChatReadOptions};
use crate::crypto::master::{MasterCrypto, MasterCryptoFuture};
use std::sync::Arc;
use tokio::sync::Notify;
const CHAT: &str = "22222222-2222-4222-8222-222222222222";
const FIRST: &str = "33333333-3333-4333-8333-333333333333";
const LAST: &str = "44444444-4444-4444-8444-444444444444";
struct AesPort {
    key: Key,
    gate: Option<Arc<Gate>>,
}
struct Gate {
    entered: Notify,
    release: Notify,
}
impl MasterCrypto for AesPort {
    fn encrypt<'a>(&'a self, iv: &'a [u8; 12], plain: &'a [u8]) -> MasterCryptoFuture<'a> {
        Box::pin(async move {
            crypto::encrypt_aead(plain, &self.key, iv, &[]).map(zeroize::Zeroizing::new)
        })
    }
    fn decrypt<'a>(&'a self, iv: &'a [u8; 12], cipher: &'a [u8]) -> MasterCryptoFuture<'a> {
        Box::pin(async move {
            if let Some(gate) = &self.gate {
                gate.entered.notify_one();
                gate.release.notified().await;
            }
            crypto::decrypt_aead(cipher, &self.key, iv, &[])
        })
    }
}
fn legacy(plain: &[u8], key: &[u8; 32]) -> String {
    use base64::Engine;
    let iv = [5; 12];
    let mut bytes = iv.to_vec();
    bytes.extend(crypto::encrypt_aead(plain, key, &iv, &[]).unwrap());
    base64::engine::general_purpose::STANDARD.encode(bytes)
}
fn fixture(opaque: bool, gate: Option<Arc<Gate>>) -> Client {
    let session = Session {
        api_url: "http://127.0.0.1:9".into(),
        session_id: "synthetic-local".into(),
        cookies: Default::default(),
        ws_token: None,
        master_key: zeroize::Zeroizing::new([7; 32]),
        hashed_email: "synthetic".into(),
        user_email_salt: String::new(),
        email_encryption_key: None,
        created_at: 1,
        paired_session_expires_at: None,
        active_team_id: None,
    };
    let mut client = Client::new("http://127.0.0.1:9", Some(session)).unwrap();
    client.user = json!({"username":"Synthetic local"});
    if opaque {
        let mut credentials =
            credentials::BrowserCredentials::from_native_session(client.session.take().unwrap());
        credentials.master = MasterCapability::opaque_for_test(Arc::new(AesPort {
            key: zeroize::Zeroizing::new([7; 32]),
            gate,
        }));
        client.browser_credentials = Some(credentials);
        client.browser_authority = Some(browser::BrowserAuthority {
            principal: "synthetic-local-profile".into(),
            persistence: browser::BrowserPersistence::MemoryOnly,
            owner_guards: true,
        });
        client.browser_local_read_only = true;
    }
    client
}
fn input() -> local_cached_read::LocalEncryptedWindowInput {
    serde_json::from_value(json!({"chat_metadata":{"id":CHAT,"encrypted_chat_key":legacy(&[9;32],&[7;32]),"encrypted_title":crypto::encrypt_combined("Synthetic title",&[9;32]).unwrap()},"wrappers":[],"boundary":{"has_more_before":true,"has_more_after":null,"compression_boundary_timestamp":null},"messages":[
 {"id":FIRST,"chat_id":CHAT,"created_at":1,"role":"user","content":"NEVER_CLEAR_EXTENSION","encrypted_content":crypto::encrypt_combined("[PERSON_1] [PERSON_2]",&[9;32]).unwrap(),"encrypted_pii_mappings":crypto::encrypt_combined(&json!([{"placeholder":"[PERSON_1]","original":"SYNTHETIC_NAME"}]).to_string(),&[9;32]).unwrap(),"queue_revision":0},
 {"id":LAST,"chat_id":CHAT,"created_at":2,"role":"assistant","encrypted_content":crypto::encrypt_combined("[PERSON_1]",&[9;32]).unwrap()}
 ]})).unwrap()
}
#[tokio::test]
async fn genuine_native_and_opaque_legacy_wrappers_unwrap_identical_child_keys() {
    for opaque in [false, true] {
        let client = fixture(opaque, None);
        let input = input();
        let wrapping = client.cached_wrapping_capability().unwrap();
        let key = client
            .chat_key_with_capability_from(&input.chat_metadata, &wrapping, &[])
            .await
            .unwrap();
        assert_eq!(*key, [9; 32]);
        assert_eq!(client.credential_ack, 0);
        assert!(client.history.is_empty());
    }
}
#[tokio::test]
async fn local_profile_page_has_explicit_provenance_no_new_salt_or_server_receipts() {
    let client = fixture(true, None);
    let before = client.ciphertext_snapshot();
    let page = client
        .local_cached_message_window(CHAT, MessageWindowOptions::default(), input())
        .await
        .unwrap();
    assert_eq!(page.source, "local_profile");
    assert!(page.cached && page.read_only && !page.fresh && !page.history_complete);
    assert_eq!(page.coverage, "retained_only");
    assert_eq!(page.has_more_before, Some(true));
    assert_eq!(page.has_more_after, None);
    assert_eq!(page.chat.messages.len(), 2);
    assert_eq!(page.chat.messages[0].content, "SYNTHETIC_NAME [PERSON_2]");
    assert_eq!(page.chat.messages[1].content, "SYNTHETIC_NAME");
    assert_eq!(page.pii_restoration, "page_local");
    let value = serde_json::to_value(&page).unwrap();
    assert!(value.get("serverMessageCount").is_none() && value.get("messagesVersion").is_none());
    assert!(!value.to_string().contains("NEVER_CLEAR_EXTENSION"));
    assert_eq!(client.ciphertext_snapshot(), before);
    assert!(client.history.is_empty() && client.chats.is_empty());
    assert_eq!(client.credential_ack, 0);
    assert!(client.native_master_key().is_err());
    assert!(
        client
            .browser_credentials
            .as_ref()
            .unwrap()
            .user_email_salt
            .is_empty()
    );
}
#[tokio::test]
async fn saved_local_read_keeps_stored_tokens_mappings_and_zero_network_pages() {
    let client = fixture(true, None);
    let before = client.ciphertext_snapshot();
    let saved = client
        .local_cached_saved_chat_read(CHAT, SavedChatReadOptions::default(), input())
        .await
        .unwrap();
    assert_eq!(saved.window.source, "local_profile");
    assert_eq!(saved.pages_read, 0);
    assert_eq!(saved.content_mode, SavedChatContentMode::Stored);
    assert_eq!(
        saved.window.chat.messages[0].content,
        "[PERSON_1] [PERSON_2]"
    );
    assert_eq!(saved.window.chat.messages[1].content, "[PERSON_1]");
    assert_eq!(saved.pii_mappings_by_message_id[FIRST].len(), 1);
    assert_eq!(saved.message_metadata[0]["queueRevision"], 0);
    assert_eq!(client.ciphertext_snapshot(), before);
}
#[tokio::test]
async fn local_cursors_cannot_cross_source_chat_generation_or_selector() {
    let mut client = fixture(true, None);
    let page = client
        .local_cached_message_window(
            CHAT,
            MessageWindowOptions {
                limit: 1,
                ..Default::default()
            },
            input(),
        )
        .await
        .unwrap();
    let cursor = page.start_cursor.clone().unwrap();
    let options = MessageWindowOptions {
        direction: MessageWindowDirection::Before,
        cursor: Some(cursor.clone()),
        ..Default::default()
    };
    let previous = client
        .local_cached_message_window(CHAT, options.clone(), input())
        .await
        .unwrap();
    assert_eq!(previous.chat.messages[0].id, FIRST);
    assert_eq!(previous.has_more_after, Some(true));
    let mut wrong = options.clone();
    wrong.cursor.as_mut().unwrap().chat_id = FIRST.into();
    assert!(
        client
            .local_cached_message_window(CHAT, wrong, input())
            .await
            .is_err()
    );
    let mut wrong = options.clone();
    wrong.cursor.as_mut().unwrap().scope = client.message_window_scope().unwrap();
    assert!(
        client
            .local_cached_message_window(CHAT, wrong, input())
            .await
            .is_err()
    );
    client.generation += 1;
    assert!(
        client
            .local_cached_message_window(CHAT, options, input())
            .await
            .is_err()
    );
}
#[tokio::test]
async fn local_bundle_wrong_chat_key_row_order_duplicate_and_closed_unknowns_refuse() {
    let client = fixture(true, None);
    for change in 0..6 {
        let mut bundle = input();
        match change {
            0 => bundle.chat_metadata["id"] = json!(FIRST),
            1 => bundle.chat_metadata["encrypted_chat_key"] = json!(legacy(&[9; 32], &[8; 32])),
            2 => bundle.messages[1]["chat_id"] = json!(FIRST),
            3 => bundle.messages.reverse(),
            4 => bundle.messages.push(bundle.messages[0].clone()),
            _ => bundle.messages[0]["created_at"] = json!(-1),
        };
        assert!(
            client
                .local_cached_message_window(CHAT, MessageWindowOptions::default(), bundle)
                .await
                .is_err()
        );
    }
    assert!(serde_json::from_value::<local_cached_read::LocalEncryptedWindowInput>(json!({"chat_metadata":{},"messages":[],"wrappers":[],"boundary":null,"authenticated":true})).is_err());
}
#[tokio::test]
async fn local_mode_known_denial_expiry_and_nonlocal_profile_never_use_fallback() {
    for change in 0..4 {
        let mut client = fixture(true, None);
        match change {
            0 => client.browser_local_read_only = false,
            1 => client.browser_authority = None,
            2 => {
                client
                    .browser_credentials
                    .as_mut()
                    .unwrap()
                    .paired_session_expires_at = Some(0)
            }
            _ => client
                .task_watch_authority
                .deny_cached_chat(Some(CHAT))
                .unwrap(),
        };
        assert!(
            client
                .local_cached_message_window(CHAT, MessageWindowOptions::default(), input())
                .await
                .is_err()
        );
        assert!(client.history.is_empty());
        assert_eq!(client.credential_ack, 0);
    }
}
#[tokio::test]
async fn actual_pending_opaque_decrypt_denial_cancellation_owner_and_key_revocation_refuse() {
    for change in 0..4 {
        let gate = Arc::new(Gate {
            entered: Notify::new(),
            release: Notify::new(),
        });
        let client = fixture(true, Some(gate.clone()));
        let before = client.ciphertext_snapshot();
        let owner = client.task_watch_authority.clone();
        let operation = client.operation_cancel.clone();
        let master = client.master_capability().unwrap();
        let mut read = Box::pin(client.local_cached_message_window(
            CHAT,
            MessageWindowOptions::default(),
            input(),
        ));
        tokio::select! {biased;result=&mut read=>{let _=result;panic!("real primitive must be pending");},_=gate.entered.notified()=>{}}
        match change {
            0 => operation.cancel(),
            1 => owner.deny_cached_chat(Some(CHAT)).unwrap(),
            2 => owner.cancel.cancel(),
            _ => master.invalidate(),
        };
        gate.release.notify_one();
        assert!(read.await.is_err());
        assert_eq!(client.ciphertext_snapshot(), before);
        assert_eq!(client.credential_ack, 0);
    }
}
#[test]
fn async_scope_rejects_generation_owner_credential_team_and_key_aba() {
    for change in 0..6 {
        let mut client = fixture(true, None);
        let scope = AsyncCryptoScope::begin(&client).unwrap();
        match change {
            0 => client.generation += 1,
            1 => client.user = json!({"username":"Different local profile"}),
            2 => client.browser_credentials.as_mut().unwrap().session_id = "different".into(),
            3 => client.browser_credentials.as_mut().unwrap().active_team_id = Some(CHAT.into()),
            4 => {
                client.browser_credentials.as_mut().unwrap().master =
                    MasterCapability::opaque_for_test(Arc::new(AesPort {
                        key: zeroize::Zeroizing::new([7; 32]),
                        gate: None,
                    }))
            }
            _ => {
                client
                    .task_watch_authority
                    .deny_cached_chat(Some(CHAT))
                    .unwrap();
                let revision = client
                    .task_watch_authority
                    .cached_denial_revision()
                    .unwrap();
                client
                    .task_watch_authority
                    .commit_cached_chat_recovery(CHAT, false, revision)
                    .unwrap();
            }
        };
        assert!(scope.check(&client).is_err());
    }
}
#[tokio::test]
async fn opaque_direct_and_om_framed_master_inputs_remain_explicit_unsupported_without_substitution()
 {
    let client = fixture(true, None);
    let wrapping = client.cached_wrapping_capability().unwrap();
    let mut row = input().chat_metadata;
    row["chat_visibility"] = json!("direct");
    assert!(matches!(
        client.chat_key_with_capability(&row, &wrapping).await,
        Err(Error::Unavailable { .. })
    ));
    row.as_object_mut().unwrap().remove("chat_visibility");
    row["encrypted_chat_key"] = json!(crypto::encrypt_bytes(&[9; 32], &[7; 32]).unwrap());
    assert!(matches!(
        client.chat_key_with_capability(&row, &wrapping).await,
        Err(Error::Crypto)
    ));
    assert_eq!(client.credential_ack, 0);
}

#[tokio::test]
async fn phase1b_opaque_window_uses_actual_capability_without_full_history_or_count_version_alias()
{
    let mut client = fixture(true, None);
    client.user = json!({"id":"11111111-1111-4111-8111-111111111111"});
    let input = input();
    let mut row = input.chat_metadata;
    row["messages_v"] = json!(2);
    let mut batch = super::super::sync_windows::Phase1Windows::default();
    batch
        .metadata(
            &json!({"chat_details":row.clone(),"team_id":null,"context_epoch":0}),
            None,
        )
        .unwrap();
    batch.content(&json!({"team_id":null,"context_epoch":0,"chats":[{"chat_id":CHAT,"messages":input.messages,"server_message_count":5,"message_window":{"has_more_before":true,"start_cursor":{"created_at":1,"message_id":FIRST},"oversized_message":false,"oversized_message_cursor":null}}]}),None).unwrap();
    let before = client.ciphertext_snapshot();
    let windows = client
        .finish_sync_windows_with_capability(batch, &BTreeMap::from([(CHAT.into(), row)]), &[])
        .await
        .unwrap();
    assert_eq!(windows.len(), 1);
    let value = serde_json::to_value(&windows).unwrap();
    assert_eq!(value[CHAT]["messages"].as_array().unwrap().len(), 2);
    assert_eq!(value[CHAT]["metadata_messages_v"], 2);
    assert_eq!(value[CHAT]["server_message_count"], 5);
    assert!(client.history.is_empty());
    assert_eq!(client.ciphertext_snapshot(), before);
    assert_eq!(client.credential_ack, 0);
}
#[tokio::test]
async fn local_large_payload_selector_never_fabricates_content_or_fetches_exact_body() {
    let client = fixture(true, None);
    let before = client.ciphertext_snapshot();
    let mut input = input();
    input.messages[1]
        .as_object_mut()
        .unwrap()
        .remove("encrypted_content");
    input.messages[1]["large_payload"] = json!({"object_key":"synthetic/opaque-selector","checksum":"a".repeat(64),"size_bytes":300_000});
    assert!(matches!(
        client
            .local_cached_message_window(CHAT, MessageWindowOptions::default(), input)
            .await,
        Err(Error::Offline)
    ));
    assert_eq!(client.ciphertext_snapshot(), before);
    assert_eq!(client.credential_ack, 0);
}

#[tokio::test]
async fn prior_chat_denial_blocks_local_display_without_blocking_internal_canonical_recovery_decode()
 {
    let client = fixture(true, None);
    client
        .task_watch_authority
        .deny_cached_chat(Some(CHAT))
        .unwrap();
    let input = input();
    let wrapping = client.cached_wrapping_capability().unwrap();
    let key = client
        .chat_key_with_capability_from(&input.chat_metadata, &wrapping, &input.wrappers)
        .await
        .unwrap();
    assert_eq!(*key, [9; 32]);
    assert!(!client.task_watch_authority.cached_chat_allowed(CHAT));
    assert!(matches!(
        client
            .local_cached_message_window(CHAT, MessageWindowOptions::default(), input)
            .await,
        Err(Error::Forbidden)
    ));
    assert_eq!(client.credential_ack, 0);
}

// contract-test: supporting surface=sdks.rust assertions=sdk.library.explicit-headless,sdk.encryption.local-only
#[tokio::test]
async fn local_profile_cannot_publish_untagged_canonical_or_offline_chat() {
    let mut client = fixture(true, None);
    // Real retained ciphertext makes the old Offline fallback eligible. The
    // closed profile guard must run before transport or cache decryption.
    let rows = input();
    client.chats.insert(CHAT.into(), rows.chat_metadata.clone());
    client.history.insert(CHAT.into(), rows.messages.clone());
    let snapshot = client.ciphertext_snapshot();
    assert!(matches!(
        client.open_chat(CHAT).await,
        Err(Error::Unavailable {
            code: "local_profile_read_only",
            ..
        })
    ));
    assert!(matches!(
        client.cached_chat_with_capability(CHAT).await,
        Err(Error::Unavailable {
            code: "local_profile_read_only",
            ..
        })
    ));
    assert!(matches!(
        client.cached_chats_with_capability().await,
        Err(Error::Unavailable {
            code: "local_profile_read_only",
            ..
        })
    ));
    assert!(matches!(
        client
            .chat_message_window(CHAT, MessageWindowOptions::default())
            .await,
        Err(Error::Unavailable {
            code: "local_profile_read_only",
            ..
        })
    ));
    assert!(matches!(
        client
            .saved_chat_read(CHAT, SavedChatReadOptions::default())
            .await,
        Err(Error::Unavailable {
            code: "local_profile_read_only",
            ..
        })
    ));
    assert!(matches!(
        client.saved_chat_read_admission(),
        Err(Error::Unavailable {
            code: "local_profile_read_only",
            ..
        })
    ));
    let page = client
        .local_cached_message_window(CHAT, MessageWindowOptions::default(), input())
        .await
        .unwrap();
    assert_eq!(page.source, "local_profile");
    assert!(page.read_only && page.cached && !page.fresh && !page.history_complete);
    assert_eq!(client.ciphertext_snapshot(), snapshot);
    assert_eq!(client.credential_ack, 0);
}
// contract-test: supporting surface=sdks.rust assertions=sdk.library.explicit-headless,sdk.encryption.local-only
#[tokio::test]
async fn native_offline_cached_fallback_keeps_original_chat_shape() {
    let mut client = fixture(false, None);
    let rows = input();
    client.chats.insert(CHAT.into(), rows.chat_metadata);
    client.history.insert(CHAT.into(), rows.messages);
    assert!(client.require_canonical_read_profile().is_ok());
    let expected = client.cached_chat(CHAT).unwrap();
    let actual = client.cached_chat_with_capability(CHAT).await.unwrap();
    assert_eq!(
        serde_json::to_value(actual).unwrap(),
        serde_json::to_value(expected).unwrap()
    );
    assert_eq!(client.credential_ack, 0);
}
// contract-test: supporting surface=sdks.rust assertions=sdk.library.explicit-headless,sdk.encryption.local-only
#[test]
fn saved_output_admission_never_reopens_after_cancel_or_negative_recovery_aba() {
    for change in 0..5 {
        let mut client = fixture(false, None);
        let admission = client.saved_chat_read_admission().unwrap();
        assert!(admission.check(&client).is_ok());
        match change {
            0 => {
                client.operation_cancel.cancel();
                client.operation_cancel = CancellationToken::new();
            }
            1 => {
                client.operation_cancel = CancellationToken::new();
            }
            2 => {
                client
                    .task_watch_authority
                    .deny_cached_chat(Some(CHAT))
                    .unwrap();
            }
            3 => {
                client
                    .task_watch_authority
                    .deny_cached_chat(Some(CHAT))
                    .unwrap();
                let revision = client
                    .task_watch_authority
                    .cached_denial_revision()
                    .unwrap();
                client
                    .task_watch_authority
                    .commit_cached_chat_recovery(CHAT, false, revision)
                    .unwrap();
                assert!(client.task_watch_authority.cached_chat_allowed(CHAT));
            }
            _ => {
                client.task_watch_authority =
                    Arc::new(client.task_watch_authority.revoke_transport_grant());
            }
        }
        assert!(admission.check(&client).is_err());
        // Fresh capture is restrictive current-context evidence only; the old
        // retained admission remains invalid after a genuine later recovery.
        if !client.task_watch_authority.cancel.is_cancelled() {
            assert!(
                client
                    .saved_chat_read_admission()
                    .unwrap()
                    .check(&client)
                    .is_ok()
            );
            assert!(admission.check(&client).is_err());
        }
        assert_eq!(client.credential_ack, 0);
    }
}
// contract-test: supporting surface=sdks.rust assertions=sdk.library.explicit-headless,sdk.encryption.local-only
#[test]
fn saved_output_admission_rejects_transition_to_local_profile() {
    let mut client = fixture(true, None);
    client.browser_local_read_only = false;
    let admission = client.saved_chat_read_admission().unwrap();
    assert!(admission.check(&client).is_ok());
    client.browser_local_read_only = true;
    assert!(matches!(
        admission.check(&client),
        Err(Error::Unavailable {
            code: "local_profile_read_only",
            ..
        })
    ));
}

// contract-test: supporting surface=sdks.rust assertions=sdk.library.explicit-headless,sdk.encryption.local-only
#[tokio::test]
async fn optional_master_fields_preserve_existing_shapes_and_crypto_revocation() {
    for opaque in [false, true] {
        let client = fixture(opaque, None);
        let key = client.master_capability().unwrap();
        for row in [json!({}), json!({"field":null}), json!({"field":""})] {
            assert_eq!(
                client
                    .decrypt_optional_with_capability(&row, "field", &key)
                    .await
                    .unwrap(),
                ""
            );
        }
        assert!(matches!(
            client
                .decrypt_optional_with_capability(&json!({"field":7}), "field", &key)
                .await,
            Err(Error::Protocol)
        ));
        let row = json!({"field":legacy(b"Synthetic optional",&[7;32])});
        assert_eq!(
            client
                .decrypt_optional_with_capability(&row, "field", &key)
                .await
                .unwrap(),
            "Synthetic optional"
        );
        key.invalidate();
        assert!(matches!(
            client
                .decrypt_optional_with_capability(&row, "field", &key)
                .await,
            Err(Error::Cancelled)
        ));
        assert_eq!(client.credential_ack, 0);
    }
}
