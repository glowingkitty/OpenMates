//! Source-authored supporting proof. Synthetic real AES port; no browser key,
//! account association, server ACK, real transport or persistence proof.
// contract-test: supporting surface=sdks.rust assertions=sdk.encryption.local-only,auth.session.isolation,auth.session.authoritative-enforcement
use super::*;
use crate::crypto::master::{MasterCrypto, MasterCryptoFuture};
use base64::Engine;
use std::sync::atomic::{AtomicUsize, Ordering};
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
    client.set_foreground_completion_recovery(true).unwrap();
    (client, calls)
}
#[tokio::test]
async fn native_browser_raw_and_genuine_opaque_unwrap_same_legacy_child_without_export() {
    for mode in ["native", "raw", "opaque"] {
        let (client, calls) = client(mode, None);
        let cancel = CancellationToken::new();
        let fence = client.recovery_fence(&cancel).unwrap();
        let scope = AsyncCryptoScope::begin(&client).unwrap();
        let master = client.master_capability().unwrap();
        let wire = crypto::server_fields::encrypt_bytes(&[8; 32], &[7; 32], &[]).unwrap();
        let key = client
            .recovery_unwrap_key(&wire, &master, &fence, &scope, CHAT)
            .await
            .unwrap();
        assert_eq!(key.as_ref(), &[8; 32]);
        if mode == "opaque" {
            assert!(matches!(
                client.native_master_key(),
                Err(Error::Unavailable {
                    code: "master_key_extraction_unavailable",
                    ..
                })
            ));
            assert_eq!(calls.load(Ordering::SeqCst), 1);
        }
        assert!(client.chats.is_empty() && client.wrappers.is_empty());
    }
}
#[tokio::test]
async fn strict_legacy_om_looking_iv_and_native_framed_semantics_remain_separate() {
    let (client, _) = client("opaque", None);
    let fence = client.recovery_fence(&CancellationToken::new()).unwrap();
    let scope = AsyncCryptoScope::begin(&client).unwrap();
    let master = client.master_capability().unwrap();
    let iv = [b'O', b'M', 1, 0, 0, 0, 4, 5, 6, 7, 8, 9];
    let mut bytes = iv.to_vec();
    bytes.extend(crypto::encrypt_aead(&[8; 32], &[7; 32], &iv, &[]).unwrap());
    let wire = base64::engine::general_purpose::STANDARD.encode(bytes);
    assert_eq!(
        client
            .recovery_unwrap_key(&wire, &master, &fence, &scope, CHAT)
            .await
            .unwrap()
            .as_ref(),
        &[8; 32]
    );
    let framed = crypto::encrypt_bytes(&[8; 32], &[7; 32]).unwrap();
    assert!(matches!(
        client
            .recovery_unwrap_key(&framed, &master, &fence, &scope, CHAT)
            .await,
        Err(Error::Crypto)
    ));
    let (native, _) = self::client("native", None);
    let fence = native.recovery_fence(&CancellationToken::new()).unwrap();
    let scope = AsyncCryptoScope::begin(&native).unwrap();
    assert_eq!(
        native
            .recovery_unwrap_key(
                &framed,
                &native.master_capability().unwrap(),
                &fence,
                &scope,
                CHAT
            )
            .await
            .unwrap()
            .as_ref(),
        &[8; 32]
    );
}
#[tokio::test]
async fn malformed_authentication_and_non_32byte_children_never_publish_key() {
    let (client, _) = client("opaque", None);
    let fence = client.recovery_fence(&CancellationToken::new()).unwrap();
    let scope = AsyncCryptoScope::begin(&client).unwrap();
    let master = client.master_capability().unwrap();
    for length in [0, 31, 33] {
        let wire = crypto::server_fields::encrypt_bytes(&vec![8; length], &[7; 32], &[]).unwrap();
        assert!(
            client
                .recovery_unwrap_key(&wire, &master, &fence, &scope, CHAT)
                .await
                .is_err()
        );
    }
    let wrong = crypto::server_fields::encrypt_bytes(&[8; 32], &[9; 32], &[]).unwrap();
    assert!(matches!(
        client
            .recovery_unwrap_key(&wrong, &master, &fence, &scope, CHAT)
            .await,
        Err(Error::Crypto)
    ));
    assert!(
        client
            .recovery_unwrap_key("malformed", &master, &fence, &scope, CHAT)
            .await
            .is_err()
    );
    assert!(client.chats.is_empty() && client.wrappers.is_empty());
}
#[tokio::test]
async fn blocked_opaque_decrypt_rejects_late_caller_cancel_resource_revocation_and_negative_acl() {
    for condition in ["caller", "resource", "denial"] {
        let gate = Arc::new((tokio::sync::Notify::new(), tokio::sync::Notify::new()));
        let (client, _) = client("opaque", Some(gate.clone()));
        let caller = CancellationToken::new();
        let fence = client.recovery_fence(&caller).unwrap();
        let scope = AsyncCryptoScope::begin(&client).unwrap();
        let master = client.master_capability().unwrap();
        let wire = crypto::server_fields::encrypt_bytes(&[8; 32], &[7; 32], &[]).unwrap();
        let result = tokio::time::timeout(Duration::from_secs(2), async {
            let decrypt = client.recovery_unwrap_key(&wire, &master, &fence, &scope, CHAT);
            let revoke = async {
                gate.0.notified().await;
                match condition {
                    "caller" => caller.cancel(),
                    "resource" => master.invalidate(),
                    _ => client
                        .task_watch_authority
                        .deny_cached_chat(Some(CHAT))
                        .unwrap(),
                };
                gate.1.notify_one();
            };
            tokio::join!(decrypt, revoke).0
        })
        .await
        .unwrap();
        assert!(matches!(result, Err(Error::Cancelled)));
        assert!(client.chats.is_empty() && client.wrappers.is_empty());
    }
}
#[test]
fn continuation_binds_key_credentials_generation_and_foreground_but_allows_fresh_call_child() {
    for changed in ["master", "session", "generation", "foreground", "expiry"] {
        let (mut client, _) = client("opaque", None);
        let caller = CancellationToken::new();
        let fence = client.recovery_fence(&caller).unwrap();
        match changed {
            "master" => {
                client.browser_credentials.as_mut().unwrap().master =
                    MasterCapability::opaque_for_test(Arc::new(Port {
                        calls: Arc::new(AtomicUsize::new(0)),
                        gate: None,
                    }))
            }
            "session" => client.browser_credentials.as_mut().unwrap().session_id = "other".into(),
            "generation" => client.generation += 1,
            "foreground" => {
                client.set_foreground_completion_recovery(false).unwrap();
            }
            _ => {
                client
                    .browser_credentials
                    .as_mut()
                    .unwrap()
                    .paired_session_expires_at = Some(1)
            }
        }
        assert!(fence.check_client(&client).is_err());
    }
    let (mut client, _) = client("opaque", None);
    let caller = CancellationToken::new();
    let mut fence = client.recovery_fence(&caller).unwrap();
    fence.operation = caller.clone();
    client.operation_cancel = CancellationToken::new();
    assert!(fence.check_client(&client).is_ok());
    assert!(AsyncCryptoScope::begin(&client).is_ok());
    caller.cancel();
    assert!(matches!(fence.check_client(&client), Err(Error::Cancelled)));
}
#[test]
fn opaque_does_not_grant_direct_team_or_local_profile_authority() {
    let (mut client, calls) = client("opaque", None);
    assert!(client.native_master_key().is_err());
    let team = "33333333-3333-4333-8333-333333333333";
    let row = json!({"id":CHAT,"chat_key_wrappers":[{"hashed_chat_id":sha256(CHAT),"key_type":"team","hashed_team_id":sha256(team),"team_key_epoch":2,"wrapper_version":1,"encrypted_chat_key":"not-decrypted"}]});
    assert!(matches!(
        validate_selected_team_recovery_wrapper(&row, CHAT, Some(team)),
        Err(Error::Conflict)
    ));
    assert_eq!(calls.load(Ordering::SeqCst), 0);
    client.browser_local_read_only = true;
    assert!(matches!(
        client.recovery_fence(&CancellationToken::new()),
        Err(Error::Unavailable {
            code: "local_profile_read_only",
            ..
        })
    ));
}

#[tokio::test]
async fn changed_owner_or_call_child_rejects_old_scope_before_decrypt() {
    for condition in ["owner", "operation"] {
        let (mut client, calls) = client("opaque", None);
        let caller = CancellationToken::new();
        let fence = client.recovery_fence(&caller).unwrap();
        let scope = AsyncCryptoScope::begin(&client).unwrap();
        let master = client.master_capability().unwrap();
        let wire = crypto::server_fields::encrypt_bytes(&[8; 32], &[7; 32], &[]).unwrap();
        if condition == "owner" {
            client.user = json!({"id":"44444444-4444-4444-8444-444444444444","username":"other"});
        } else {
            client.operation_cancel = CancellationToken::new();
        }
        assert!(matches!(
            client
                .recovery_unwrap_key(&wire, &master, &fence, &scope, CHAT)
                .await,
            Err(Error::Cancelled)
        ));
        assert_eq!(calls.load(Ordering::SeqCst), 0);
    }
}

#[tokio::test]
async fn selected_personal_and_team_wrapper_expiry_during_aes_never_releases_key_or_cache() {
    for team in [false, true] {
        let gate = Arc::new((tokio::sync::Notify::new(), tokio::sync::Notify::new()));
        let (client, calls) = client("opaque", Some(gate.clone()));
        let caller = CancellationToken::new();
        let fence = client.recovery_fence(&caller).unwrap();
        let scope = AsyncCryptoScope::begin(&client).unwrap();
        let master = client.master_capability().unwrap();
        let encrypted = crypto::server_fields::encrypt_bytes(&[8; 32], &[7; 32], &[]).unwrap();
        let expires_at = now_ms() / 1000 + 2;
        let wrapper = json!({"wrapper_version":1,"team_key_epoch":1,"expires_at":expires_at});
        let result = tokio::time::timeout(Duration::from_secs(4), async {
            let decrypt = client.recovery_unwrap_selected_key(
                &encrypted, &master, &fence, &scope, CHAT, &wrapper, team,
            );
            let expire = async {
                gate.0.notified().await;
                tokio::time::sleep(Duration::from_millis(
                    (expires_at * 1000).saturating_sub(now_ms()) + 1,
                ))
                .await;
                gate.1.notify_one();
            };
            tokio::join!(decrypt, expire).0
        })
        .await
        .unwrap();
        assert!(matches!(result, Err(Error::Conflict)));
        assert_eq!(calls.load(Ordering::SeqCst), 1);
        assert!(client.chats.is_empty() && client.wrappers.is_empty());
    }
}
struct TrackedPlain {
    text: String,
    wiped: Arc<std::sync::atomic::AtomicBool>,
}
impl super::super::plaintext::Wipe for TrackedPlain {
    fn wipe(&mut self) {
        use zeroize::Zeroize;
        self.text.zeroize();
        self.wiped.store(self.text.is_empty(), Ordering::SeqCst);
    }
}
#[test]
fn parsed_plaintext_is_guarded_before_partial_validation_failure() {
    let wiped = Arc::new(std::sync::atomic::AtomicBool::new(false));
    let value = TrackedPlain {
        text: "synthetic private parsed field".into(),
        wiped: wiped.clone(),
    };
    let result = admit_recovery_plain(value, |plain| {
        assert!(!plain.text.is_empty());
        Err(Error::Protocol)
    });
    assert!(matches!(result, Err(Error::Protocol)));
    assert!(wiped.load(Ordering::SeqCst));
}
#[tokio::test]
async fn final_fence_revocation_wipes_successful_plaintext_before_caller_can_adopt_it() {
    for resource in [false, true] {
        let (client, _) = client("opaque", None);
        let caller = CancellationToken::new();
        let fence = client.recovery_fence(&caller).unwrap();
        let master = client.master_capability().unwrap();
        let wiped = Arc::new(std::sync::atomic::AtomicBool::new(false));
        let result = fence
            .run_plain(async {
                let value = TrackedPlain {
                    text: "synthetic successful private result".into(),
                    wiped: wiped.clone(),
                };
                if resource {
                    master.invalidate();
                } else {
                    caller.cancel();
                }
                Ok(value)
            })
            .await;
        assert!(matches!(result, Err(Error::Cancelled)));
        assert!(wiped.load(Ordering::SeqCst));
    }
}
