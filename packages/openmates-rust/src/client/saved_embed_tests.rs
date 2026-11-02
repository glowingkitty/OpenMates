//! Authored synthetic in-process conformance; no backend/browser/runtime claim.
// contract-test: supporting surface=sdks.rust assertions=sdk.encryption.local-only,auth.session.isolation
use super::*;
use crate::crypto::master::MasterCapability;
use crate::crypto::master::{MasterCrypto, MasterCryptoFuture};
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
const OWNER: &str = "11111111-1111-4111-8111-111111111111";
fn response(id: &str, parent: Option<&str>, key: &[u8; 32]) -> Value {
    json!({"embed_id":id,"user_id":OWNER,"already_encrypted":true,"encryption_mode":"client",
        "chat_id":CHAT,"status":"finished","parent_embed_id":parent,
        "type":crypto::server_fields::encrypt_text("code",key,&[]).unwrap(),
        "content":crypto::server_fields::encrypt_text("{\"title\":\"Synthetic\",\"text\":\"Exact [EMAIL_1]\\nvalue\"}",key,&[]).unwrap(),
        "embed_keys":[{"hashed_embed_id":sha256(id),"hashed_user_id":sha256(OWNER),"key_type":"master",
          "encrypted_embed_key":crypto::server_fields::encrypt_bytes(key,&[9;32],&[]).unwrap()}],
        "embed_keys_has_more_after":false,"oversized_embed_key_id":null,"createdAt":12,"is_private":true})
}
async fn synthetic_read(client: &Client, response: &Value) -> Result<SavedEmbedRead> {
    let scope = VersionReadScope::begin(client)?;
    let (source, row, wrappers) = admit_row(client, &scope, response, EMBED, None)?;
    let staged = BTreeMap::from([(EMBED.to_owned(), row)]);
    let key = client
        .selected_embed_key(EMBED, &scope, &staged, &wrappers, false)
        .await?;
    scope.check(client)?;
    let value = decode(staged.get(EMBED).unwrap(), EMBED, &key)?;
    let read = SavedEmbedRead {
        scope,
        value,
        _key: key,
        source,
    };
    read.check(client)?;
    Ok(read)
}
#[tokio::test]
async fn native_raw_and_opaque_share_exact_decode_without_master_export_or_cache_mutation() {
    for mode in ["native", "raw", "opaque"] {
        let (client, calls) = client(mode, None);
        let read = synthetic_read(&client, &response(EMBED, None, &[7; 32]))
            .await
            .unwrap();
        let output: Value = serde_json::from_str(&read.json(&client).unwrap()).unwrap();
        assert_eq!(output["content"]["text"], "Exact [EMAIL_1]\nvalue");
        assert_eq!(output["type"], "code");
        assert_eq!(output["metadata"]["createdAt"], 12);
        assert_eq!(output["metadata"]["is_private"], true);
        assert!(output.get("embed_keys").is_none());
        assert!(output.get("key").is_none());
        assert!(client.embeds.is_empty());
        assert!(client.embed_keys.is_empty());
        if mode == "opaque" {
            assert!(client.native_master_key().is_err());
            assert_eq!(calls.load(Ordering::SeqCst), 1);
        }
    }
}
#[tokio::test]
async fn exact_owner_source_ciphertext_and_complete_key_page_are_required() {
    let (client, _) = client("opaque", None);
    for mode in [
        "owner",
        "embed",
        "plain",
        "encryption",
        "team",
        "direct",
        "chat",
        "window",
        "oversized",
        "foreign-wrapper",
        "foreign-chat-wrapper",
        "malformed-content",
        "bad-tag",
    ] {
        let mut row = response(EMBED, None, &[7; 32]);
        match mode {
            "owner" => row["user_id"] = json!(PARENT),
            "embed" => row["embed_id"] = json!(PARENT),
            "plain" => row["already_encrypted"] = json!(false),
            "encryption" => row["encryption_mode"] = json!("vault"),
            "team" => row["team_id"] = json!(PARENT),
            "direct" => row["chat_visibility"] = json!("direct"),
            "chat" => row["chat_id"] = json!("not-chat-authority"),
            "window" => row["embed_keys_has_more_after"] = json!(true),
            "oversized" => row["oversized_embed_key_id"] = json!("blocked"),
            "foreign-wrapper" => row["embed_keys"][0]["hashed_user_id"] = json!(sha256(PARENT)),
            "foreign-chat-wrapper" => {
                row["embed_keys"][0]["key_type"] = json!("chat");
                row["embed_keys"][0]["hashed_chat_id"] = json!(sha256(PARENT));
            }
            "malformed-content" => row["content"] = json!({"unexpected":"plain"}),
            _ => row["embed_keys"][0]["encrypted_embed_key"] = json!("bad-tag"),
        }
        assert!(synthetic_read(&client, &row).await.is_err(), "{mode}");
    }
}
#[tokio::test]
async fn sealed_read_cannot_release_after_owner_generation_key_denial_or_operation_change() {
    for mode in ["owner", "forget", "key", "denial", "operation"] {
        let (mut client, _) = client("opaque", None);
        let read = synthetic_read(&client, &response(EMBED, None, &[7; 32]))
            .await
            .unwrap();
        match mode {
            "owner" => client.user["id"] = json!(PARENT),
            "forget" => client.forget_session(),
            "key" => client.master_capability().unwrap().invalidate(),
            "denial" => client
                .task_watch_authority
                .deny_cached_chat(Some(CHAT))
                .unwrap(),
            _ => client.operation_cancel.cancel(),
        }
        assert!(read.json(&client).is_err(), "{mode}");
    }
}
#[tokio::test]
async fn late_opaque_crypto_rejection_keeps_original_scope_and_never_returns_plaintext() {
    for resource in [false, true] {
        let gate = Arc::new((tokio::sync::Notify::new(), tokio::sync::Notify::new()));
        let (client, _) = client("opaque", Some(gate.clone()));
        let row = response(EMBED, None, &[7; 32]);
        let decrypt = synthetic_read(&client, &row);
        let revoke = async {
            gate.0.notified().await;
            if resource {
                client.master_capability().unwrap().invalidate();
            } else {
                client.task_watch_authority.deny_cached_chat(None).unwrap();
            }
            gate.1.notify_one();
        };
        let result = tokio::time::timeout(Duration::from_secs(2), async {
            tokio::join!(decrypt, revoke).0
        })
        .await
        .unwrap();
        assert!(result.is_err());
    }
}
#[tokio::test]
async fn fresh_staged_policy_never_uses_old_cache_wrappers_but_parent_key_inheritance_is_shared() {
    let (mut client, _) = client("opaque", None);
    let scope = VersionReadScope::begin(&client).unwrap();
    let mut row = response(EMBED, Some(PARENT), &[7; 32]);
    row["embed_keys"] = json!([]);
    let (source, child, _) = admit_row(&client, &scope, &row, EMBED, None).unwrap();
    let parent_response = response(PARENT, None, &[7; 32]);
    let (_, parent, keys) =
        admit_row(&client, &scope, &parent_response, PARENT, Some(&source)).unwrap();
    client.embed_keys = keys.clone();
    client.embeds.insert(PARENT.into(), parent.clone());
    let child_only = BTreeMap::from([(EMBED.to_owned(), child.clone())]);
    assert!(
        client
            .selected_embed_key(EMBED, &scope, &child_only, &[], false)
            .await
            .is_err()
    );
    let staged = BTreeMap::from([(EMBED.to_owned(), child), (PARENT.to_owned(), parent)]);
    assert_eq!(
        client
            .selected_embed_key(EMBED, &scope, &staged, &keys, false)
            .await
            .unwrap()
            .as_ref(),
        &[7; 32]
    );
    let mut other = parent_response;
    other["chat_id"] = json!(PARENT);
    assert!(admit_row(&client, &scope, &other, PARENT, Some(&source)).is_err());
}
#[tokio::test]
async fn inherited_cycle_and_chain_bounds_fail_closed() {
    let (client, _) = client("opaque", None);
    let scope = VersionReadScope::begin(&client).unwrap();
    let staged = BTreeMap::from([
        (
            EMBED.into(),
            json!({"embed_id":EMBED,"parent_embed_id":PARENT}),
        ),
        (
            PARENT.into(),
            json!({"embed_id":PARENT,"parent_embed_id":EMBED}),
        ),
    ]);
    assert!(matches!(
        client
            .selected_embed_key(EMBED, &scope, &staged, &[], false)
            .await,
        Err(Error::Crypto)
    ));
    let mut row = response(EMBED, None, &[7; 32]);
    row["parent_embed_id"] = json!(EMBED);
    assert!(admit_row(&client, &scope, &row, EMBED, None).is_err());
    row = response(EMBED, None, &[7; 32]);
    row["embed_keys"] = json!(vec![row["embed_keys"][0].clone(); MAX_WRAPPERS + 1]);
    assert!(admit_row(&client, &scope, &row, EMBED, None).is_err());
}
#[tokio::test]
async fn short_ids_and_team_fail_before_any_socket() {
    let (mut client, _) = client("opaque", None);
    assert!(matches!(
        client.saved_embed("short").await,
        Err(Error::Invalid(_))
    ));
    client.browser_credentials.as_mut().unwrap().active_team_id = Some(PARENT.into());
    assert!(matches!(
        client.saved_embed(EMBED).await,
        Err(Error::Unavailable {
            code: "cookie_saved_embed_scope_unavailable",
            ..
        })
    ));
}
#[test]
fn common_fixture_declares_full_id_slice_and_explicit_gaps() {
    let fixture: Value = serde_json::from_str(include_str!(
        "../../tests/fixtures/session-saved-embed-read.json"
    ))
    .unwrap();
    assert_eq!(fixture["capability"], "session.embeds.saved-read.v1");
    assert_eq!(fixture["protocol"]["request_event"], "request_embed");
    assert_eq!(fixture["protocol"]["response_event"], "send_embed_data");
    assert_eq!(fixture["key_export"], false);
    for mode in [
        "prefix",
        "team",
        "direct",
        "local_profile",
        "key_window_continuation",
    ] {
        assert!(
            fixture["unsupported"]
                .as_array()
                .unwrap()
                .iter()
                .any(|v| v == mode)
        );
    }
}

#[tokio::test]
async fn shared_static_wire_fixture_decodes_on_all_explicit_master_capability_modes() {
    let fixture: Value = serde_json::from_str(include_str!(
        "../../tests/fixtures/session-saved-embed-read.json"
    ))
    .unwrap();
    let vector = &fixture["vectors"][0];
    for mode in ["native", "raw", "opaque"] {
        let (client, _) = client(mode, None);
        let read = synthetic_read(&client, &vector["wire"]).await.unwrap();
        let value: Value = serde_json::from_str(&read.json(&client).unwrap()).unwrap();
        assert_eq!(value["content"], vector["content"]);
        assert_eq!(value["type"], vector["type"]);
    }
}
#[tokio::test]
async fn selected_wrapper_expiry_version_and_cached_direct_scope_stay_closed() {
    let (mut client, _) = client("opaque", None);
    for field in ["expires_at", "wrapper_version"] {
        let mut row = response(EMBED, None, &[7; 32]);
        row["embed_keys"][0][field] = json!(0);
        assert!(synthetic_read(&client, &row).await.is_err());
    }
    client
        .chats
        .insert(CHAT.into(), json!({"id":CHAT,"chat_visibility":"direct"}));
    assert!(matches!(
        synthetic_read(&client, &response(EMBED, None, &[7; 32])).await,
        Err(Error::Unavailable {
            code: "cookie_saved_embed_scope_unavailable",
            ..
        })
    ));
}

#[tokio::test]
async fn cached_original_personal_chat_wrapper_uses_opaque_master_without_cache_writes() {
    let (mut client, _) = client("opaque", None);
    let mut row = response(EMBED, None, &[7; 32]);
    row["embed_keys"] = json!([{"hashed_embed_id":sha256(EMBED),"hashed_chat_id":sha256(CHAT),"hashed_user_id":null,"key_type":"chat",
        "encrypted_embed_key":crypto::server_fields::encrypt_bytes(&[7;32],&[8;32],&[]).unwrap()}]);
    assert!(matches!(
        synthetic_read(&client, &row).await,
        Err(Error::Unavailable {
            code: "cookie_embed_version_key_cache_unavailable",
            ..
        })
    ));
    client.chats.insert(CHAT.into(),json!({"id":CHAT,"encrypted_chat_key":crypto::server_fields::encrypt_bytes(&[8;32],&[9;32],&[]).unwrap()}));
    let read = synthetic_read(&client, &row).await.unwrap();
    assert!(read.json(&client).is_ok());
    assert!(client.embeds.is_empty());
    assert!(client.embed_keys.is_empty());
}
#[tokio::test]
async fn ninth_parent_exceeds_the_shared_engine_bound_even_with_present_rows() {
    let (client, _) = client("opaque", None);
    let scope = VersionReadScope::begin(&client).unwrap();
    let ids = (1..=9)
        .map(|n| uuid::Uuid::from_u128(n).to_string())
        .collect::<Vec<_>>();
    let staged = ids
        .iter()
        .enumerate()
        .map(|(at, id)| {
            (
                id.clone(),
                json!({"embed_id":id,"parent_embed_id":ids.get(at+1)}),
            )
        })
        .collect();
    assert!(matches!(
        client
            .selected_embed_key(&ids[0], &scope, &staged, &[], false)
            .await,
        Err(Error::Crypto)
    ));
}

#[tokio::test]
async fn preexisting_uncached_source_global_and_overflow_denials_reject_before_decryption() {
    for hashed_source in [false, true] {
        for denial in ["source", "global", "overflow", "oversized-denial"] {
            let (client, calls) = client("opaque", None);
            match denial {
                "source" => client
                    .task_watch_authority
                    .deny_cached_chat(Some(CHAT))
                    .unwrap(),
                "global" => client.task_watch_authority.deny_cached_chat(None).unwrap(),
                "overflow" => {
                    for n in 0..4097 {
                        client
                            .task_watch_authority
                            .deny_cached_chat(Some(&format!("synthetic-denied-{n}")))
                            .unwrap();
                    }
                }
                _ => client
                    .task_watch_authority
                    .deny_cached_chat(Some(&"x".repeat(257)))
                    .unwrap(),
            }
            assert!(client.chats.is_empty());
            let mut row = response(EMBED, None, &[7; 32]);
            if hashed_source {
                row["chat_id"] = json!(sha256(CHAT));
            }
            assert!(
                matches!(synthetic_read(&client, &row).await, Err(Error::Forbidden)),
                "{denial}/{hashed_source}"
            );
            assert_eq!(calls.load(Ordering::SeqCst), 0);
            assert!(client.embeds.is_empty());
            assert!(client.embed_keys.is_empty());
        }
    }
}
#[tokio::test]
async fn preexisting_unrelated_denial_does_not_mint_or_remove_source_authority() {
    for hashed_source in [false, true] {
        let (client, _) = client("opaque", None);
        client
            .task_watch_authority
            .deny_cached_chat(Some(PARENT))
            .unwrap();
        let mut row = response(EMBED, None, &[7; 32]);
        if hashed_source {
            row["chat_id"] = json!(sha256(CHAT));
        }
        let read = synthetic_read(&client, &row).await.unwrap();
        assert_eq!(
            read.source.canonical_id.as_deref(),
            if hashed_source { None } else { Some(CHAT) }
        );
        assert!(read.json(&client).is_ok());
        // A later denial still fences the exact original scope, independently
        // of whether the source is cached or represented by a hash on the wire.
        client
            .task_watch_authority
            .deny_cached_chat(Some(CHAT))
            .unwrap();
        assert!(read.json(&client).is_err());
    }
}
#[tokio::test]
async fn cached_unknown_visibility_and_any_nonnull_participant_metadata_fail_closed() {
    for (field, value) in [
        ("chat_visibility", json!("direct")),
        ("chat_visibility", json!("unknown")),
        ("chat_visibility", json!("personal")),
        ("chat_visibility", json!(false)),
        ("participant_user_hashes", json!([])),
        ("participant_user_hashes", json!(false)),
        ("participant_key_envelopes", json!({})),
        ("participant_key_envelopes", json!("")),
        ("hashed_team_id", json!("")),
        ("team_id", json!(PARENT)),
    ] {
        let (mut client, calls) = client("opaque", None);
        let mut cached = json!({"id":CHAT});
        cached[field] = value;
        client.chats.insert(CHAT.into(), cached);
        assert!(
            matches!(
                synthetic_read(&client, &response(EMBED, None, &[7; 32])).await,
                Err(Error::Unavailable {
                    code: "cookie_saved_embed_scope_unavailable",
                    ..
                })
            ),
            "{field}"
        );
        assert_eq!(calls.load(Ordering::SeqCst), 0);
    }
    // Missing/null generic metadata and the backend's ordinary "team" label
    // alone do not redefine a Personal source as a Team workspace.
    for visibility in [Value::Null, json!("team")] {
        let (mut client, _) = client("opaque", None);
        client.chats.insert(
            CHAT.into(),
            json!({"id":CHAT,"chat_visibility":visibility,
            "participant_user_hashes":null,"participant_key_envelopes":null,"hashed_team_id":null}),
        );
        assert!(
            synthetic_read(&client, &response(EMBED, None, &[7; 32]))
                .await
                .is_ok()
        );
    }
}

fn open_share_bytes(encoded: &str, password: &[u8], salt: &[u8]) -> zeroize::Zeroizing<Vec<u8>> {
    use base64::{Engine, engine::general_purpose::URL_SAFE_NO_PAD};
    let bytes = URL_SAFE_NO_PAD.decode(encoded).unwrap();
    let mut key = zeroize::Zeroizing::new([0u8; 32]);
    pbkdf2::pbkdf2_hmac::<sha2::Sha256>(password, salt, 100_000, key.as_mut());
    let iv: [u8; 12] = bytes[..12].try_into().unwrap();
    crypto::decrypt_aead(&bytes[12..], &key, &iv, &[]).unwrap()
}
#[tokio::test]
async fn admitted_share_vectors_preserve_fragment_protocol_without_raw_master_export() {
    let fixture: Value = serde_json::from_str(include_str!(
        "../../tests/fixtures/session-embed-admitted-share.json"
    ))
    .unwrap();
    for mode in ["native", "raw", "opaque"] {
        let (client, calls) = client(mode, None);
        let read = synthetic_read(&client, &response(EMBED, None, &[7; 32]))
            .await
            .unwrap();
        let original_calls = calls.load(Ordering::SeqCst);
        for vector in fixture["vectors"].as_array().unwrap() {
            let password = vector["password"].as_str().unwrap();
            let output = read
                .share_url(&client, vector["expires"].as_i64().unwrap(), password)
                .unwrap();
            assert!(output.starts_with(fixture["url_prefix"].as_str().unwrap()));
            let blob = output.split("#key=").nth(1).unwrap();
            let plaintext = open_share_bytes(blob, EMBED.as_bytes(), b"openmates-share-v1");
            let fields: std::collections::BTreeMap<_, _> = url::form_urlencoded::parse(&plaintext)
                .into_owned()
                .collect();
            assert_eq!(fields.len(), 4);
            assert_eq!(fields["duration_seconds"], vector["expires"].to_string());
            assert!(fields["generated_at"].parse::<u64>().unwrap() > 0);
            assert_eq!(fields["pwd"], if password.is_empty() { "0" } else { "1" });
            let key = if password.is_empty() {
                fields["embed_encryption_key"].clone()
            } else {
                let decoded = open_share_bytes(
                    &fields["embed_encryption_key"],
                    password.as_bytes(),
                    format!("openmates-pwd-{EMBED}").as_bytes(),
                );
                String::from_utf8(decoded.to_vec()).unwrap()
            };
            assert_eq!(key, crypto::encode_key(&[7; 32]));
        }
        assert_eq!(calls.load(Ordering::SeqCst), original_calls);
        assert!(client.embeds.is_empty() && client.embed_keys.is_empty());
        if mode == "opaque" {
            assert!(client.native_master_key().is_err());
        }
    }
}
#[tokio::test]
async fn admitted_share_rechecks_source_denial_forget_privacy_owner_key_and_cancellation() {
    for denial in ["source", "forget", "privacy", "owner", "key", "cancel"] {
        let (mut client, _) = client("opaque", None);
        let gate = Arc::new(std::sync::atomic::AtomicBool::new(true));
        let captured = gate.clone();
        client.options.private_operation_gate = Some(Arc::new(move || {
            if captured.load(Ordering::SeqCst) {
                Ok(())
            } else {
                Err(Error::Forbidden)
            }
        }));
        let read = synthetic_read(&client, &response(EMBED, None, &[7; 32]))
            .await
            .unwrap();
        match denial {
            "source" => client
                .task_watch_authority
                .deny_cached_chat(Some(CHAT))
                .unwrap(),
            "forget" => client.forget_session(),
            "owner" => client.user["id"] = json!(PARENT),
            "key" => client.master_capability().unwrap().invalidate(),
            "cancel" => client.operation_cancel.cancel(),
            "privacy" => gate.store(false, Ordering::SeqCst),
            _ => unreachable!(),
        }
        assert!(read.share_url(&client, 0, "").is_err(), "{denial}");
    }
}
