//! Synthetic AES/cached-key tests; actual Cookie/WS/native runtime remains unrun.
// contract-test: supporting surface=sdks.rust assertions=sdk.encryption.local-only,auth.session.isolation
use super::*;
use crate::crypto::master::MasterCapability;
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
            crypto::encrypt_aead(bytes, &[9; 32], iv, &[]).map(zeroize::Zeroizing::new)
        })
    }
    fn decrypt<'a>(&'a self, iv: &'a [u8; 12], bytes: &'a [u8]) -> MasterCryptoFuture<'a> {
        Box::pin(async move {
            self.calls.fetch_add(1, Ordering::SeqCst);
            if let Some(gate) = &self.gate {
                gate.0.notify_one();
                gate.1.notified().await;
            }
            crypto::decrypt_aead(bytes, &[9; 32], iv, &[])
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
            master_key: zeroize::Zeroizing::new([9; 32]),
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

const EMBED: &str = "33333333-3333-4333-8333-333333333333";
const PARENT: &str = "44444444-4444-4444-8444-444444444444";
fn cached(client: &mut Client, id: &str, key: &[u8; 32]) {
    client
        .embeds
        .insert(id.into(), json!({"embed_id":id,"parent_embed_id":null}));
    client.embed_keys.push(json!({"hashed_embed_id":sha256(id),"key_type":"master","encrypted_embed_key":crypto::server_fields::encrypt_bytes(key,&[9;32],&[]).unwrap()}));
}
#[tokio::test]
async fn personal_native_raw_and_opaque_reuse_cached_master_and_shared_reconstruction() {
    for mode in ["native", "raw", "opaque"] {
        let (mut client, calls) = client(mode, None);
        cached(&mut client, EMBED, &[7; 32]);
        let scope = VersionReadScope::begin(&client).unwrap();
        let key = client
            .cached_version_embed_key(EMBED, &scope, &BTreeMap::new(), &[])
            .await
            .unwrap();
        assert_eq!(key.as_ref(), &[7; 32]);
        if mode == "opaque" {
            assert!(client.native_master_key().is_err());
            assert_eq!(calls.load(Ordering::SeqCst), 1);
        }
        let fixture: Value = serde_json::from_str(include_str!(
            "../../tests/fixtures/session-embed-version-content.json"
        ))
        .unwrap();
        let vector = &fixture["capabilities"]["session.embeds.version-content.v1"]["vectors"][1];
        let content = crate::sdk_embeds::reconstruct_version_rows_with_cancel(
            vector["response"]["rows"].as_array().unwrap(),
            &key,
            &client.operation_cancel,
        )
        .unwrap();
        assert_eq!(
            content.as_str(),
            vector["expected"]["content"].as_str().unwrap()
        );
    }
}
#[tokio::test]
async fn bad_master_can_use_existing_owning_chat_then_parent_without_master_export() {
    let (mut client, _) = client("opaque", None);
    cached(&mut client, EMBED, &[7; 32]);
    client.embed_keys[0]["encrypted_embed_key"] = json!("bad-tag");
    client.chats.insert(CHAT.into(),json!({"id":CHAT,"encrypted_chat_key":crypto::server_fields::encrypt_bytes(&[8;32],&[9;32],&[]).unwrap()}));
    client.embed_keys.push(json!({"hashed_embed_id":sha256(EMBED),"key_type":"chat","hashed_chat_id":sha256(CHAT),"encrypted_embed_key":crypto::server_fields::encrypt_bytes(&[7;32],&[8;32],&[]).unwrap()}));
    let scope = VersionReadScope::begin(&client).unwrap();
    assert_eq!(
        client
            .cached_version_embed_key(EMBED, &scope, &BTreeMap::new(), &[])
            .await
            .unwrap()
            .as_ref(),
        &[7; 32]
    );
    client.embed_keys.clear();
    client.embeds.get_mut(EMBED).unwrap()["parent_embed_id"] = json!(PARENT);
    cached(&mut client, PARENT, &[7; 32]);
    let scope = VersionReadScope::begin(&client).unwrap();
    assert_eq!(
        client
            .cached_version_embed_key(EMBED, &scope, &BTreeMap::new(), &[])
            .await
            .unwrap()
            .as_ref(),
        &[7; 32]
    );
}
#[tokio::test]
async fn late_master_revocation_and_negative_acl_discard_opaque_key() {
    for resource in [false, true] {
        let gate = Arc::new((tokio::sync::Notify::new(), tokio::sync::Notify::new()));
        let (mut client, _) = client("opaque", Some(gate.clone()));
        cached(&mut client, EMBED, &[7; 32]);
        let scope = VersionReadScope::begin(&client).unwrap();
        let master = client.master_capability().unwrap();
        let staged = BTreeMap::new();
        let result = tokio::time::timeout(Duration::from_secs(2), async {
            let decrypt = client.cached_version_embed_key(EMBED, &scope, &staged, &[]);
            let revoke = async {
                gate.0.notified().await;
                if resource {
                    master.invalidate();
                } else {
                    client.task_watch_authority.deny_cached_chat(None).unwrap();
                }
                gate.1.notify_one();
            };
            tokio::join!(decrypt, revoke).0
        })
        .await
        .unwrap();
        assert!(matches!(result, Err(Error::Cancelled)));
    }
}
#[test]
fn final_admission_retains_wrapper_expiry_and_current_core_forget_not_bridge_epochs() {
    let (mut client, _) = client("opaque", None);
    let scope = VersionReadScope::begin(&client).unwrap();
    let admission = EmbedVersionReadAdmission { scope };
    assert!(admission.check(&client).is_ok());
    *admission.scope.wrapper_expiry.lock().unwrap() = Some(0);
    assert!(matches!(admission.check(&client), Err(Error::Conflict)));
    let admission = EmbedVersionReadAdmission {
        scope: VersionReadScope::begin(&client).unwrap(),
    };
    client.forget_session();
    assert!(admission.check(&client).is_err());
}
#[tokio::test]
async fn personal_scope_short_ids_and_invalid_versions_fail_before_io() {
    let (mut client, _) = client("opaque", None);
    assert!(matches!(
        client.embed_version_content("short", 1).await,
        Err(Error::Invalid(_))
    ));
    assert!(matches!(
        client.embed_version_content(EMBED, 0).await,
        Err(Error::Invalid(_))
    ));
    client.browser_credentials.as_mut().unwrap().active_team_id = Some(PARENT.into());
    assert!(matches!(
        client.embed_version_content(EMBED, 1).await,
        Err(Error::Unavailable {
            code: "cookie_embed_version_scope_unavailable",
            ..
        })
    ));
}

#[test]
fn validated_server_text_and_empty_move_the_original_allocation_without_overwrite() {
    for content in ["synthetic existing server plaintext", ""] {
        let (client, _) = client("opaque", None);
        let scope = VersionReadScope::begin(&client).unwrap();
        let response = Plain::new(
            json!({"embed_id":EMBED,"version_number":1,"content":content,"opaque":{"kept":true}}),
        );
        let original = response["content"].as_str().unwrap().as_ptr();
        let (value, admission) = release_server_content(response, scope, &client).unwrap();
        assert_eq!(value["content"].as_str().unwrap().as_ptr(), original);
        assert_eq!(value["content"], content);
        assert_eq!(value["opaque"], json!({"kept":true}));
        assert!(admission.check(&client).is_ok());
    }
}
#[tokio::test]
async fn withheld_io_observes_operation_master_negative_and_wrapper_expiry_without_frames() {
    for condition in ["operation", "master", "negative", "wrapper"] {
        let (client, _) = client("opaque", None);
        let scope = VersionReadScope::begin(&client).unwrap();
        let master = client.master_capability().unwrap();
        let result = tokio::time::timeout(Duration::from_millis(500), async {
            let blocked = scope.run_io(std::future::pending::<Result<()>>());
            let revoke = async {
                tokio::task::yield_now().await;
                match condition {
                    "operation" => client.operation_cancel.cancel(),
                    "master" => master.invalidate(),
                    "negative" => client.task_watch_authority.deny_cached_chat(None).unwrap(),
                    _ => *scope.wrapper_expiry.lock().unwrap() = Some(0),
                }
            };
            tokio::join!(blocked, revoke).0
        })
        .await
        .unwrap();
        assert!(matches!(result, Err(Error::Cancelled | Error::Conflict)));
    }
}
#[tokio::test]
async fn one_total_deadline_does_not_reset_when_unmatched_work_keeps_arriving() {
    let (client, _) = client("opaque", None);
    let scope =
        VersionReadScope::begin_until(&client, Instant::now() + Duration::from_millis(60)).unwrap();
    let progress = Arc::new(AtomicUsize::new(0));
    let seen = progress.clone();
    async fn unmatched_progress(seen: Arc<AtomicUsize>) -> Result<()> {
        loop {
            crate::platform::time::sleep(Duration::from_millis(5)).await;
            seen.fetch_add(1, Ordering::SeqCst);
        }
    }
    let result = tokio::time::timeout(
        Duration::from_millis(500),
        scope.run_io(unmatched_progress(seen)),
    )
    .await
    .unwrap();
    assert!(matches!(result, Err(Error::Offline)));
    assert!(progress.load(Ordering::SeqCst) > 0);
}
