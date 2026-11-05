//! Synthetic crypto/projection cases, no product/network execution. Real full
//! read/native dispatch is separately authored in isolated protocol_smoke.
// contract-test-file: tooling
use super::*;
const ID: &str = "22222222-2222-4222-8222-222222222222";
fn fixture() -> Value {
    serde_json::from_str(include_str!(
        "../../tests/fixtures/full-chat-read-metadata.json"
    ))
    .unwrap()
}
fn client() -> Client {
    let endpoint = "http://127.0.0.1:9";
    let session:Session=serde_json::from_value(json!({"api_url":endpoint,"session_id":"synthetic","cookies":{},"ws_token":null,"master_key":"BwcHBwcHBwcHBwcHBwcHBwcHBwcHBwcHBwcHBwcHBwc=","hashed_email":"synthetic","user_email_salt":"synthetic","email_encryption_key":null,"created_at":1,"paired_session_expires_at":null,"active_team_id":null})).unwrap();
    let mut c = Client::new(endpoint, Some(session)).unwrap();
    c.user = json!({"id":"synthetic-owner"});
    c
}
fn row(encrypted: Value) -> Value {
    json!({"id":ID,"encrypted_chat_key":crypto::encrypt_bytes(&[9;32],&[7;32]).unwrap(),"encrypted_slug":encrypted})
}
fn chat() -> Plain<Chat> {
    Plain::new(serde_json::from_value(fixture()["chat"].clone()).unwrap())
}
// contract-test: supporting surface=sdks.rust assertions=sdk.encryption.local-only,cli.surface.semantic-parity
#[tokio::test]
async fn shared_vectors_decrypt_exact_saved_slug_and_preserve_legacy_chat_shape() {
    let suite = fixture();
    for vector in suite["vectors"].as_array().unwrap() {
        let mut c = client();
        let mut row = row(vector["encryptedSlug"].clone());
        if vector["present"] == false {
            row.as_object_mut().unwrap().remove("encrypted_slug");
        }
        c.chats.insert(ID.into(), row);
        let admission = c.full_chat_read_admission(ID);
        let scope = AsyncCryptoScope::begin(&c).unwrap();
        let read = c
            .full_chat_read_projection(ID, chat(), &scope, admission.unwrap())
            .await
            .unwrap();
        assert_eq!(serde_json::to_value(&read).unwrap(), vector["expected"]);
        assert_eq!(serde_json::to_value(&read.chat).unwrap(), suite["chat"]);
        assert!(read.chat.messages.is_empty());
        assert_eq!(c.chats[ID]["id"], ID);
    }
}
#[tokio::test]
async fn corrupt_wrong_key_wrong_id_and_wrong_field_type_fail_closed() {
    for change in 0..5 {
        let mut c = client();
        let mut value = row(fixture()["vectors"][0]["encryptedSlug"].clone());
        match change {
            0 => value["encrypted_slug"] = json!("not-ciphertext"),
            1 => {
                value["encrypted_slug"] =
                    json!(crypto::encrypt_combined("synthetic", &[8; 32]).unwrap())
            }
            2 => value["id"] = json!("different"),
            3 => value["encrypted_slug"] = json!(true),
            _ => {
                value["encrypted_slug"] =
                    json!(crypto::encrypt_combined(&"x".repeat(65537), &[9; 32]).unwrap())
            }
        }
        c.chats.insert(ID.into(), value);
        let admission = c.full_chat_read_admission(ID);
        let scope = AsyncCryptoScope::begin(&c).unwrap();
        assert!(
            c.full_chat_read_projection(ID, chat(), &scope, admission.unwrap())
                .await
                .is_err()
        );
    }
}
#[tokio::test]
async fn original_source_global_overflow_owner_context_and_cancellation_denials_prevent_projection()
{
    for change in 0..6 {
        let mut c = client();
        c.chats.insert(
            ID.into(),
            row(fixture()["vectors"][0]["encryptedSlug"].clone()),
        );
        let admission = c.full_chat_read_admission(ID);
        let scope = AsyncCryptoScope::begin(&c).unwrap();
        match change {
            0 => c.task_watch_authority.deny_cached_chat(Some(ID)).unwrap(),
            1 => c.task_watch_authority.deny_cached_chat(None).unwrap(),
            2 => {
                for n in 0..4097 {
                    c.task_watch_authority
                        .deny_cached_chat(Some(&format!("synthetic-denial-{n}")))
                        .unwrap();
                }
            }
            3 => c.operation_cancel.cancel(),
            4 => c.user = json!({"id":"other-owner"}),
            _ => c.generation += 1,
        }
        assert!(
            c.full_chat_read_projection(ID, chat(), &scope, admission.unwrap())
                .await
                .is_err()
        );
    }
    // Existing negatives BEFORE scope capture must also refuse (revision alone
    // cannot establish this resource is allowed).
    for source in [Some(ID), None] {
        let mut c = client();
        c.chats.insert(
            ID.into(),
            row(fixture()["vectors"][0]["encryptedSlug"].clone()),
        );
        c.task_watch_authority.deny_cached_chat(source).unwrap();
        assert!(c.full_chat_read_admission(ID).is_err());
    }
}
#[tokio::test]
async fn draft_without_established_chat_key_never_invents_slug_from_master_or_selector() {
    let mut c = client();
    c.chats.insert(ID.into(),json!({"id":ID,"encrypted_draft_md":"synthetic-draft","encrypted_slug":crypto::encrypt_combined("master-only-not-chat-slug",&[7;32]).unwrap()}));
    let admission = c.full_chat_read_admission(ID);
    let scope = AsyncCryptoScope::begin(&c).unwrap();
    let read = c
        .full_chat_read_projection(ID, chat(), &scope, admission.unwrap())
        .await
        .unwrap();
    assert!(read.slug.is_none());
    assert!(serde_json::to_value(&read).unwrap().get("slug").is_none());
}
#[test]
fn optional_flattened_read_deserializes_legacy_without_changing_chat_serialization() {
    let suite = fixture();
    let read: FullChatRead = serde_json::from_value(suite["chat"].clone()).unwrap();
    assert!(read.slug.is_none());
    assert_eq!(serde_json::to_value(&read).unwrap(), suite["chat"]);
}

#[tokio::test]
async fn public_full_read_rejects_preexisting_source_global_and_overflow_before_any_io() {
    for change in 0..3 {
        let mut c = client();
        match change {
            0 => c.task_watch_authority.deny_cached_chat(Some(ID)).unwrap(),
            1 => c.task_watch_authority.deny_cached_chat(None).unwrap(),
            _ => {
                for n in 0..4097 {
                    c.task_watch_authority
                        .deny_cached_chat(Some(&format!("synthetic-preexisting-{n}")))
                        .unwrap();
                }
            }
        }
        assert!(c.chats.is_empty());
        assert!(matches!(
            c.open_chat_with_metadata(ID).await,
            Err(Error::Forbidden)
        ));
    }
}

#[tokio::test]
async fn original_gate_survives_replacement_through_projection_and_final_native_check() {
    use std::sync::{
        Arc,
        atomic::{AtomicBool, Ordering},
    };
    let mut c = client();
    c.chats.insert(
        ID.into(),
        row(fixture()["vectors"][0]["encryptedSlug"].clone()),
    );
    let allowed = Arc::new(AtomicBool::new(true));
    let captured = allowed.clone();
    c.set_private_operation_gate(Some(Arc::new(move || {
        if captured.load(Ordering::Acquire) {
            Ok(())
        } else {
            Err(Error::Forbidden)
        }
    })));
    let admission = c.full_chat_read_admission(ID).unwrap();
    let scope = AsyncCryptoScope::begin(&c).unwrap();
    let read = c
        .full_chat_read_projection(ID, chat(), &scope, admission)
        .await
        .unwrap();
    assert!(read.check(&c).is_ok());
    c.set_private_operation_gate(Some(Arc::new(|| Ok(()))));
    assert!(read.check(&c).is_ok()); // Ordinary still-permitted replacement.
    allowed.store(false, Ordering::Release);
    assert!(matches!(read.check(&c), Err(Error::Forbidden)));
}
#[test]
fn captured_and_current_privacy_are_both_required_without_current_relaxation_fallback() {
    let mut c = client();
    // A public admission may never begin under the restrictive original policy.
    c.set_privacy_options(crate::privacy::PrivacyOptions { enhanced: true });
    assert!(c.full_chat_read_admission(ID).is_err());
    c.set_privacy_options(crate::privacy::PrivacyOptions::default());
    let ordinary = c.full_chat_read_admission(ID).unwrap();
    assert!(ordinary.check(&c).is_ok());
    c.set_privacy_options(crate::privacy::PrivacyOptions { enhanced: true });
    assert!(ordinary.check(&c).is_err());
    c.set_privacy_options(crate::privacy::PrivacyOptions::default());
    // Negative-only internal invariant: even if a retained policy snapshot is
    // restrictive while current policy is relaxed, it must never authorize.
    let restrictive = FullChatReadAdmission {
        saved: c.original_full_chat_read_admission().unwrap(),
        privacy: crate::privacy::PrivacyOptions { enhanced: true },
        original_gate: None,
        chat_id: zeroize::Zeroizing::new(ID.into()),
        original_identity: FullReadIdentity::capture(&c).unwrap(),
        restored_scope: None,
    };
    assert!(restrictive.check(&c).is_err());
    assert!(ordinary.check(&c).is_ok());
}

// contract-test: supporting surface=sdks.rust assertions=sdk.encryption.local-only,cli.surface.semantic-parity
#[tokio::test]
async fn completed_full_read_restoration_preserves_exact_original_policy_and_rejects_intervening_changes()
 {
    use std::sync::{
        Arc,
        atomic::{AtomicBool, Ordering},
    };
    const TEAM: &str = "33333333-3333-4333-8333-333333333333";
    for change in 0..15 {
        let mut c = client();
        let parent = CancellationToken::new();
        c.set_operation_cancel(parent.clone());
        let allowed = Arc::new(AtomicBool::new(true));
        let gate = allowed.clone();
        c.set_private_operation_gate(Some(Arc::new(move || {
            if gate.load(Ordering::Acquire) {
                Ok(())
            } else {
                Err(Error::Forbidden)
            }
        })));
        c.chats.insert(
            ID.into(),
            row(fixture()["vectors"][0]["encryptedSlug"].clone()),
        );
        let original = c.full_chat_read_admission(ID).unwrap();
        let scope = AsyncCryptoScope::begin(&c).unwrap();
        let mut read = c
            .full_chat_read_projection(ID, chat(), &scope, original)
            .await
            .unwrap();
        let mut admission = read.take_admission(&c).unwrap();
        assert!(read.check(&c).is_err()); // Exact one-use transfer, not recapture.
        c.set_private_operation_gate(Some(Arc::new(|| Ok(()))));
        if change >= 8 {
            match change {
                8 => c.set_operation_cancel(CancellationToken::new()),
                9 => allowed.store(false, Ordering::Release),
                10 => parent.cancel(),
                11 => c.set_privacy_options(crate::privacy::PrivacyOptions { enhanced: true }),
                12 => c.forget_session(),
                13 => {
                    let session = c.clone_session();
                    let api = c.session().unwrap().api_url.clone();
                    c.reset(&api, session).unwrap();
                }
                14 => c.task_watch_authority.deny_cached_chat(Some(ID)).unwrap(),
                _ => unreachable!(),
            }
            let before = c.session().map(|s| s.active_team_id.clone());
            assert!(admission.restore_team(&mut c, Some(TEAM)).is_err());
            assert_eq!(
                c.session().map(|s| s.active_team_id.clone()),
                before,
                "refused transition never blesses Team restoration"
            );
            continue;
        }
        admission.restore_team(&mut c, Some(TEAM)).unwrap();
        assert!(admission.check(&c).is_ok());
        match change {
            0 => {}
            1 => allowed.store(false, Ordering::Release),
            2 => parent.cancel(),
            3 => c.set_privacy_options(crate::privacy::PrivacyOptions { enhanced: true }),
            4 => c.forget_session(),
            5 => c.task_watch_authority.deny_cached_chat(Some(ID)).unwrap(),
            6 => admission
                .original_identity
                .authority
                .deny_cached_chat(Some(ID))
                .unwrap(),
            7 => {
                c.set_team(None).unwrap();
                c.set_team(Some(TEAM)).unwrap();
            }
            _ => unreachable!(),
        }
        if change == 0 {
            assert!(admission.check(&c).is_ok());
            assert!(admission.restore_team(&mut c, None).is_err());
        } else {
            assert!(admission.check(&c).is_err());
        }
    }
}
