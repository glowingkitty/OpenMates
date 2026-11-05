// contract-test-file: tooling
// Actual target-only stability primitives. No fake Boundary/owner/result grant.
// Authored UNRUN; full driver tests require the genuine recovery fixture.
use super::*;
const CHAT: &str = "22222222-2222-4222-8222-222222222222";
const OTHER: &str = "11111111-1111-4111-8111-111111111111";
// contract-test: supporting surface=sdks.rust assertions=sdk.encryption.local-only
#[test]
fn streaming_stamp_matches_actual_serialization_without_a_full_client_snapshot() {
    let value =
        json!({"messages":[{"encrypted_content":"ciphertext","id":"actual-row"}],"nullable":null});
    assert_eq!(
        stamp(&value).unwrap(),
        sha256(&serde_json::to_string(&value).unwrap())
    );
}
// contract-test: supporting surface=sdks.rust assertions=sdk.encryption.local-only,sdk.surface.semantic-parity
#[test]
fn history_stability_is_target_only_and_observes_same_target_change() {
    let mut client = Client::new("http://127.0.0.1:9", None).unwrap();
    let before = history_stamp(&client, CHAT).unwrap();
    client
        .history
        .insert(OTHER.into(), vec![json!({"id":"unrelated"})]);
    assert_eq!(history_stamp(&client, CHAT).unwrap(), before);
    client.history.insert(
        CHAT.into(),
        vec![json!({"id":"actual-ciphertext-row","encrypted_content":"one"})],
    );
    let after = history_stamp(&client, CHAT).unwrap();
    assert_ne!(after, before);
    client.history.get_mut(CHAT).unwrap()[0]["encrypted_content"] = json!("changed");
    assert_ne!(history_stamp(&client, CHAT).unwrap(), after);
}
// contract-test: supporting surface=sdks.rust assertions=auth.session.isolation,sdk.encryption.local-only
#[test]
fn wrapper_stability_never_freezes_or_restores_other_chat_rows() {
    let mut client = Client::new("http://127.0.0.1:9", None).unwrap();
    let before = wrappers_stamp(&client, CHAT).unwrap();
    client
        .wrappers
        .push(json!({"hashed_chat_id":sha256(OTHER),"encrypted_chat_key":"unrelated"}));
    assert_eq!(wrappers_stamp(&client, CHAT).unwrap(), before);
    client
        .wrappers
        .push(json!({"hashed_chat_id":sha256(CHAT),"encrypted_chat_key":"actual"}));
    assert_ne!(wrappers_stamp(&client, CHAT).unwrap(), before);
}

#[cfg(not(target_arch = "wasm32"))]
mod original_boundary_flow {
    use super::*;
    use crate::client::browser::owned_recovery_phase_tests::genuine_canonical_boundary_for_test;
    use std::cell::RefCell;
    use tokio::time::{Duration, timeout};
    async fn complete(
        driver: &mut OwnedCanonicalChatDriver,
        client: &RefCell<Client>,
    ) -> Result<OriginalCanonicalChatReadResult> {
        loop {
            match driver.next().await? {
                OwnedCanonicalChatStep::Apply(apply) => {
                    let resume = apply.run(&mut client.borrow_mut())?;
                    driver.resume(resume)?;
                }
                OwnedCanonicalChatStep::Io(io) => {
                    let actual = io.drive();
                    // The real future owns no Client borrow. Preserve an unrelated
                    // chat write while actual network/crypto work is outstanding.
                    client.borrow_mut().insert_chat_row(
                        OTHER.into(),
                        json!({"id":OTHER,"unrelated":"preserve actual sibling"}),
                    );
                    driver.resume(actual.await?)?;
                }
                OwnedCanonicalChatStep::Ready(result) => return Ok(result),
            }
        }
    }
    // contract-test: supporting surface=sdks.rust assertions=auth.session.isolation,sync.client.shared-rust-policy,chats.persistence.client-encrypted
    #[tokio::test]
    async fn genuine_boundary_full_canonical_result_retains_fresh_key_and_actual_artifacts_without_focus_rollback()
     {
        let (mut client, pending, scope, handoff, boundary, _server) =
            genuine_canonical_boundary_for_test().await;
        client.active_chat = Some(OTHER.into());
        let before = client.chats.get(&handoff.job().chat_id).cloned();
        assert_eq!(&before, boundary.before_row());
        let prepared = client
            .prepare_original_canonical_chat_read(scope.clone(), handoff.clone(), boundary.clone())
            .unwrap();
        let client = RefCell::new(client);
        let mut driver = prepared.into_driver().unwrap();
        let result = timeout(Duration::from_secs(10), complete(&mut driver, &client))
            .await
            .unwrap()
            .unwrap();
        drop(driver);
        let current = client.borrow();
        result
            .check_original(&current, &scope, &handoff, &boundary)
            .unwrap();
        let (chat, key, transition, artifacts) = result
            .take_parts(&current, &scope, &handoff, &boundary)
            .unwrap();
        assert_eq!(chat.id, handoff.job().chat_id);
        assert_eq!(chat.messages.len(), 1);
        assert_eq!(chat.messages[0].content, chat.title);
        assert_eq!(key.as_ref(), &[8; 32]);
        assert_eq!(current.active_chat.as_deref(), Some(OTHER));
        assert_eq!(current.chats[OTHER]["unrelated"], "preserve actual sibling");
        assert_eq!(transition.before_row(), &before);
        assert_eq!(
            transition.after_row().unwrap(),
            current.chats.get(&chat.id).cloned()
        );
        transition
            .check_original(&current, &scope, &handoff, &boundary)
            .unwrap();
        let rows = artifacts
            .checked_ciphertext_rows(&current, &scope, &handoff, &boundary)
            .unwrap();
        assert_eq!(rows.len(), 1);
        assert!(rows[0]["encrypted_content"].is_string());
        assert!(chat.messages[0].embeds.is_empty());
        assert!(matches!(
            artifacts.coverage(),
            CanonicalArtifactScope::TranscriptCiphertextRowsOnly
        ));
        drop(current);
        drop(pending);
        assert!(
            artifacts
                .checked_ciphertext_rows(&client.borrow(), &scope, &handoff, &boundary)
                .is_err()
        );
    }
    // contract-test: supporting surface=sdks.rust assertions=auth.session.isolation,sync.client.shared-rust-policy
    #[tokio::test]
    async fn real_boundary_claim_is_one_use_and_another_real_scope_cannot_replace_original() {
        let (client, _pending, scope, handoff, boundary, _server) =
            genuine_canonical_boundary_for_test().await;
        let foreign =
            Arc::new(OwnedOperationScope::capture(&client, CancellationToken::new()).unwrap());
        assert!(
            client
                .prepare_original_canonical_chat_read(foreign, handoff.clone(), boundary.clone())
                .is_err()
        );
        let prepared = client
            .prepare_original_canonical_chat_read(scope.clone(), handoff.clone(), boundary.clone())
            .unwrap();
        assert!(
            client
                .prepare_original_canonical_chat_read(
                    scope.clone(),
                    handoff.clone(),
                    boundary.clone()
                )
                .is_err()
        );
        drop(prepared);
        scope.check(&client).unwrap();
        boundary.negative().unwrap();
    }
    // contract-test: supporting surface=sdks.rust assertions=auth.session.isolation,sync.client.shared-rust-policy
    #[tokio::test]
    async fn actual_dispatched_headers_reach_apply_after_local_cancel_without_a_body_or_plaintext_grant()
     {
        let (mut client, _pending, scope, handoff, boundary, _server) =
            genuine_canonical_boundary_for_test().await;
        let mut driver = client
            .prepare_original_canonical_chat_read(scope, handoff, boundary)
            .unwrap()
            .into_driver()
            .unwrap();
        let OwnedCanonicalChatStep::Apply(start) = driver.next().await.unwrap() else {
            panic!("prepare")
        };
        driver.resume(start.run(&mut client).unwrap()).unwrap();
        let OwnedCanonicalChatStep::Io(io) = driver.next().await.unwrap() else {
            panic!("actual headers")
        };
        let actual = io.drive().await.unwrap();
        driver.context.cancel.cancel();
        driver.resume(actual).unwrap();
        let OwnedCanonicalChatStep::Apply(headers) = driver.next().await.unwrap() else {
            panic!("actual cookie control plane must drain")
        };
        assert!(matches!(
            headers.kind.as_ref(),
            Some(ApplyKind::Headers(_, _))
        ));
        driver.resume(headers.run(&mut client).unwrap()).unwrap();
        assert!(matches!(driver.next().await, Err(Error::Cancelled)));
    }
    // contract-test: supporting surface=sdks.rust assertions=auth.session.isolation,sync.client.shared-rust-policy
    #[tokio::test]
    async fn foreign_target_write_after_actual_body_never_gets_adopted_or_rolled_back() {
        let (mut client, _pending, scope, handoff, boundary, _server) =
            genuine_canonical_boundary_for_test().await;
        let id = handoff.job().chat_id.clone();
        let mut driver = client
            .prepare_original_canonical_chat_read(scope, handoff, boundary)
            .unwrap()
            .into_driver()
            .unwrap();
        loop {
            match driver.next().await.unwrap() {
                OwnedCanonicalChatStep::Apply(apply) => {
                    if matches!(
                        apply.kind.as_ref(),
                        Some(ApplyKind::Body(Target::Metadata, _))
                    ) {
                        client.chats.get_mut(&id).unwrap()["foreign_write"] = json!("must remain");
                        driver.resume(apply.run(&mut client).unwrap()).unwrap();
                        assert!(matches!(driver.next().await, Err(Error::Conflict)));
                        assert_eq!(client.chats[&id]["foreign_write"], "must remain");
                        break;
                    }
                    driver.resume(apply.run(&mut client).unwrap()).unwrap();
                }
                OwnedCanonicalChatStep::Io(io) => driver.resume(io.drive().await.unwrap()).unwrap(),
                OwnedCanonicalChatStep::Ready(_) => panic!("foreign row cannot finish"),
            }
        }
    }
}
