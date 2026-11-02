//! Synthetic AES/scope ownership proof only; actual browser/HTTP/WS/ACK remains unrun.
// contract-test: supporting surface=sdks.rust assertions=sdk.encryption.local-only,auth.session.isolation,auth.session.authoritative-enforcement
use super::*;
use crate::crypto::master::{MasterCrypto, MasterCryptoFuture};
use base64::Engine;
use std::sync::{
    Arc,
    atomic::{AtomicUsize, Ordering},
};
const CHAT: &str = "22222222-2222-4222-8222-222222222222";
struct Port {
    calls: Arc<AtomicUsize>,
    gate: Option<Arc<(tokio::sync::Notify, tokio::sync::Notify)>>,
}
impl MasterCrypto for Port {
    fn encrypt<'a>(&'a self, iv: &'a [u8; 12], bytes: &'a [u8]) -> MasterCryptoFuture<'a> {
        Box::pin(async move {
            crypto::encrypt_aead(bytes, &[7; 32], iv, &[]).map(zeroize::Zeroizing::new)
        })
    }
    fn decrypt<'a>(&'a self, iv: &'a [u8; 12], bytes: &'a [u8]) -> MasterCryptoFuture<'a> {
        Box::pin(async move {
            self.calls.fetch_add(1, Ordering::SeqCst);
            if let Some(gate) = &self.gate {
                gate.0.notify_one();
                gate.1.notified().await;
            }
            crypto::decrypt_aead(bytes, &[7; 32], iv, &[])
        })
    }
}
fn client(
    mode: &str,
    gate: Option<Arc<(tokio::sync::Notify, tokio::sync::Notify)>>,
) -> (Client, Arc<AtomicUsize>) {
    let mut client = Client::new(
        "https://api.example.org",
        Some(Session {
            api_url: "https://api.example.org".into(),
            session_id: "synthetic-recovery-session".into(),
            cookies: Default::default(),
            ws_token: Some("synthetic".into()),
            master_key: zeroize::Zeroizing::new([7; 32]),
            hashed_email: "synthetic-owner".into(),
            user_email_salt: String::new(),
            email_encryption_key: None,
            created_at: 1,
            paired_session_expires_at: None,
            active_team_id: None,
        }),
    )
    .unwrap();
    client.user = json!({"id":"11111111-1111-4111-8111-111111111111","username":"synthetic"});
    let calls = Arc::new(AtomicUsize::new(0));
    if mode != "native" {
        let mut credentials =
            credentials::BrowserCredentials::from_native_session(client.session.take().unwrap());
        if mode == "opaque" {
            credentials.master = MasterCapability::opaque_for_test(Arc::new(Port {
                calls: calls.clone(),
                gate,
            }));
        }
        client.browser_credentials = Some(credentials);
        client.browser_authority = Some(browser::BrowserAuthority {
            principal: "11111111-1111-4111-8111-111111111111".into(),
            persistence: browser::BrowserPersistence::MemoryOnly,
            owner_guards: true,
        });
        client.browser_transport = true;
    }
    (client, calls)
}

const SUBJECT: &str = "33333333-3333-4333-8333-333333333333";
fn wrappers() -> Value {
    json!([{"key_type":"master","hashed_embed_id":sha256(SUBJECT),"hashed_user_id":"owner-hash","encrypted_embed_key":crypto::server_fields::encrypt_bytes(&[8;32],&[7;32],&[]).unwrap()},
    {"key_type":"chat","hashed_embed_id":sha256(SUBJECT),"hashed_user_id":"owner-hash","hashed_chat_id":sha256(CHAT),"encrypted_embed_key":crypto::server_fields::encrypt_bytes(&[8;32],&[9;32],&[]).unwrap()}])
}
fn output() -> Value {
    json!({"root_chat_id":CHAT,"target_chat_id":CHAT})
}
#[tokio::test]
async fn native_raw_and_opaque_verify_same_owner_chat_wrappers_without_master_export() {
    for mode in ["native", "raw", "opaque"] {
        let (client, calls) = client(mode, None);
        let scope = ReplayScope::begin(&client).unwrap();
        let rows = wrappers();
        let actual = verify_wrappers_with_capability(
            &client,
            &scope,
            &rows,
            SUBJECT,
            CHAT,
            &[8; 32],
            &[9; 32],
            &client.master_capability().unwrap(),
            "owner-hash",
        )
        .await
        .unwrap();
        assert_eq!(
            actual,
            verify_wrappers(
                &rows,
                SUBJECT,
                CHAT,
                &[8; 32],
                &[9; 32],
                &[7; 32],
                "owner-hash"
            )
            .unwrap()
        );
        assert_eq!(actual.len(), 2);
        if mode == "opaque" {
            assert_eq!(calls.load(Ordering::SeqCst), 1);
            assert!(client.native_master_key().is_err());
        }
    }
}
#[tokio::test]
async fn wrong_owner_hash_subject_chat_duplicates_and_bad_child_never_validate() {
    for field in [
        "hashed_user_id",
        "hashed_embed_id",
        "hashed_chat_id",
        "duplicate",
        "wrong-key",
        "short-key",
    ] {
        let (client, calls) = client("opaque", None);
        let scope = ReplayScope::begin(&client).unwrap();
        let mut rows = wrappers();
        match field {
            "duplicate" => {
                let first = rows[0].clone();
                rows.as_array_mut().unwrap().push(first);
            }
            "wrong-key" => {
                rows[0]["encrypted_embed_key"] =
                    json!(crypto::server_fields::encrypt_bytes(&[6; 32], &[7; 32], &[]).unwrap())
            }
            "short-key" => {
                rows[0]["encrypted_embed_key"] =
                    json!(crypto::server_fields::encrypt_bytes(&[8; 31], &[7; 32], &[]).unwrap())
            }
            "hashed_chat_id" => rows[1][field] = json!("foreign"),
            _ => rows[0][field] = json!("foreign"),
        }
        assert!(matches!(
            verify_wrappers_with_capability(
                &client,
                &scope,
                &rows,
                SUBJECT,
                CHAT,
                &[8; 32],
                &[9; 32],
                &client.master_capability().unwrap(),
                "owner-hash"
            )
            .await,
            Err(Error::Crypto)
        ));
        if ["hashed_user_id", "hashed_embed_id"].contains(&field) {
            assert_eq!(calls.load(Ordering::SeqCst), 0);
        }
        assert!(client.embed_keys.is_empty());
    }
}
#[tokio::test]
async fn expiry_crossing_real_opaque_aes_restricts_every_later_publication_gate() {
    let gate = Arc::new((tokio::sync::Notify::new(), tokio::sync::Notify::new()));
    let (client, _) = client("opaque", Some(gate.clone()));
    let scope = ReplayScope::begin(&client).unwrap();
    let mut rows = wrappers();
    let at = now_ms() / 1000 + 2;
    rows[0]["expires_at"] = json!(at);
    let master = client.master_capability().unwrap();
    let result = tokio::time::timeout(Duration::from_secs(4), async {
        let verify = verify_wrappers_with_capability(
            &client,
            &scope,
            &rows,
            SUBJECT,
            CHAT,
            &[8; 32],
            &[9; 32],
            &master,
            "owner-hash",
        );
        let expire = async {
            gate.0.notified().await;
            tokio::time::sleep(Duration::from_millis(
                (at * 1000).saturating_sub(now_ms()) + 1,
            ))
            .await;
            gate.1.notify_one();
        };
        tokio::join!(verify, expire).0
    })
    .await
    .unwrap();
    assert!(matches!(result, Err(Error::Conflict)));
    assert!(matches!(
        check_replay_scope(&client, &scope, &output()),
        Err(Error::Conflict)
    ));
    assert!(client.embed_keys.is_empty());
}
#[tokio::test]
async fn blocked_opaque_resource_or_negative_owner_revocation_never_validates() {
    for resource in [false, true] {
        let gate = Arc::new((tokio::sync::Notify::new(), tokio::sync::Notify::new()));
        let (client, _) = client("opaque", Some(gate.clone()));
        let scope = ReplayScope::begin(&client).unwrap();
        let rows = wrappers();
        let master = client.master_capability().unwrap();
        let result = tokio::time::timeout(Duration::from_secs(2), async {
            let verify = verify_wrappers_with_capability(
                &client,
                &scope,
                &rows,
                SUBJECT,
                CHAT,
                &[8; 32],
                &[9; 32],
                &master,
                "owner-hash",
            );
            let revoke = async {
                gate.0.notified().await;
                if resource {
                    master.invalidate();
                } else {
                    client
                        .task_watch_authority
                        .deny_cached_chat(Some(CHAT))
                        .unwrap();
                }
                gate.1.notify_one();
            };
            tokio::join!(verify, revoke).0
        })
        .await
        .unwrap();
        assert!(matches!(result, Err(Error::Cancelled)));
        assert!(client.embed_keys.is_empty());
    }
}
#[tokio::test]
async fn opaque_writes_are_exact_legacy_fields_and_om_looking_iv_is_not_a_frame() {
    let (client, _) = client("opaque", None);
    let master = client.master_capability().unwrap();
    let cipher = master.encrypt_server_bytes(&[8; 32]).await.unwrap();
    let bytes = base64::engine::general_purpose::STANDARD
        .decode(cipher)
        .unwrap();
    assert_eq!(bytes.len(), 12 + 32 + 16);
    assert_eq!(
        crypto::decrypt_aead(&bytes[12..], &[7; 32], &bytes[..12], &[])
            .unwrap()
            .as_slice(),
        &[8; 32]
    );
    let iv = [b'O', b'M', 1, 0, 0, 0, 4, 5, 6, 7, 8, 9];
    let mut combined = iv.to_vec();
    combined.extend(crypto::encrypt_aead(&[8; 32], &[7; 32], &iv, &[]).unwrap());
    let mut rows = wrappers();
    rows[0]["encrypted_embed_key"] =
        json!(base64::engine::general_purpose::STANDARD.encode(combined));
    let scope = ReplayScope::begin(&client).unwrap();
    assert!(
        verify_wrappers_with_capability(
            &client,
            &scope,
            &rows,
            SUBJECT,
            CHAT,
            &[8; 32],
            &[9; 32],
            &master,
            "owner-hash"
        )
        .await
        .is_ok()
    );
}
#[test]
fn prepared_plaintext_wiper_covers_partial_json_and_child_key_without_recovery_ack() {
    let mut prepared = Prepared {
        identity: json!({"record_id":"private"}),
        ready: json!({"nested":["private"]}),
        content: json!({"content":"private","nested":[{"more":"private"}]}),
        key: zeroize::Zeroizing::new([8; 32]),
    };
    prepared.wipe();
    assert_eq!(prepared.identity, Value::Null);
    assert_eq!(prepared.ready, Value::Null);
    assert_eq!(prepared.content, Value::Null);
    assert!(prepared.key.iter().all(|b| *b == 0));
}
#[test]
fn owner_operation_local_mode_and_wrapper_epoch_restrict_without_new_grants() {
    for kind in ["owner", "operation", "local"] {
        let (mut client, _) = client("opaque", None);
        let scope = ReplayScope::begin(&client).unwrap();
        match kind {
            "owner" => client.user = json!({"id":"foreign"}),
            "operation" => client.operation_cancel = CancellationToken::new(),
            _ => client.browser_local_read_only = true,
        };
        assert!(check_replay_scope(&client, &scope, &output()).is_err());
    }
    let (client, _) = client("opaque", None);
    let scope = ReplayScope::begin(&client).unwrap();
    for row in [
        json!({"wrapper_version":2}),
        json!({"team_key_epoch":2}),
        json!({"expires_at":1}),
    ] {
        assert!(matches!(scope.remember_wrapper(&row), Err(Error::Conflict)));
    }
}

#[test]
fn actual_embed_publication_boundary_refuses_expiry_resource_and_acl_without_cache_or_ack() {
    for condition in ["expired-wrapper", "revoked-resource", "negative-acl"] {
        let (mut client, _) = client("opaque", None);
        let scope = ReplayScope::begin(&client).unwrap();
        client.embeds.insert(
            "existing".into(),
            json!({"encrypted_content":"synthetic retained ciphertext"}),
        );
        let before = client.embeds.clone();
        match condition {
            // A deterministic already-observed expired deadline at the final
            // boundary; the earlier gated AES test covers actual wall crossing.
            "expired-wrapper" => *scope.wrapper_expiry.lock().unwrap() = Some(0),
            "revoked-resource" => client.master_capability().unwrap().invalidate(),
            _ => client
                .task_watch_authority
                .deny_cached_chat(Some(CHAT))
                .unwrap(),
        }
        let mut ack_continuations = 0;
        let result: Result<()> = (|| {
            // Calls the exact production insertion helper; its failure must
            // short-circuit the same immediately following ACK continuation.
            client.publish_recovered_embed(
                &scope,
                &output(),
                SUBJECT,
                &json!({"encrypted_content":"synthetic rejected ciphertext"}),
            )?;
            ack_continuations += 1;
            Ok(())
        })();
        assert!(result.is_err());
        assert_eq!(client.embeds, before);
        assert!(!client.embeds.contains_key(SUBJECT));
        assert_eq!(ack_continuations, 0);
    }
}
