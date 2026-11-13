//! User-edit key access with a web (opaque master) and a native credential.
// contract-test: supporting surface=sdks.rust assertions=edit.next-version,sdk.encryption.local-only
use crate::client::*;
use crate::crypto::master::{MasterCapability, MasterCrypto, MasterCryptoFuture};
use crate::session::Session;
use std::sync::Arc;

const EMBED: &str = "33333333-3333-4333-8333-333333333333";
const CHAT: &str = "22222222-2222-4222-8222-222222222222";

/// Synthetic WebCrypto stand-in: AES with a fixed master that never leaves it.
struct Port;
impl MasterCrypto for Port {
    fn encrypt<'a>(&'a self, iv: &'a [u8; 12], bytes: &'a [u8]) -> MasterCryptoFuture<'a> {
        Box::pin(async move {
            crypto::encrypt_aead(bytes, &[9; 32], iv, &[]).map(zeroize::Zeroizing::new)
        })
    }
    fn decrypt<'a>(&'a self, iv: &'a [u8; 12], bytes: &'a [u8]) -> MasterCryptoFuture<'a> {
        Box::pin(async move { crypto::decrypt_aead(bytes, &[9; 32], iv, &[]) })
    }
}

fn client(web: bool) -> Client {
    let mut client = Client::new(
        "https://api.example.org",
        Some(Session {
            api_url: "https://api.example.org".into(),
            session_id: "synthetic-edit-session".into(),
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
    if web {
        let mut credentials =
            credentials::BrowserCredentials::from_native_session(client.session.take().unwrap());
        credentials.master = MasterCapability::opaque_for_test(Arc::new(Port));
        client.browser_credentials = Some(credentials);
        client.browser_authority = Some(browser::BrowserAuthority {
            principal: "11111111-1111-4111-8111-111111111111".into(),
            persistence: browser::BrowserPersistence::MemoryOnly,
            owner_guards: true,
        });
        client.browser_transport = true;
    }
    client.embeds.insert(
        EMBED.into(),
        json!({"embed_id":EMBED,"parent_embed_id":null}),
    );
    client
        .embed_keys
        .push(json!({"hashed_embed_id":sha256(EMBED),"key_type":"master",
        "encrypted_embed_key":crypto::server_fields::encrypt_bytes(&[7;32],&[9;32],&[]).unwrap()}));
    client
}

#[tokio::test]
async fn web_session_opens_the_embed_key_without_native_session_material() {
    let mut web = client(true);
    assert!(matches!(
        web.require_session(),
        Err(Error::Unavailable {
            code: "native_session_required",
            ..
        })
    ));
    let key = web.edit_embed_key(EMBED).await.unwrap();
    assert_eq!(key.as_ref(), &[7; 32]);
    assert!(web.native_master_key().is_err());
}

#[tokio::test]
async fn native_session_keeps_the_raw_master_embed_key_path() {
    let mut native = client(false);
    let key = native.edit_embed_key(EMBED).await.unwrap();
    assert_eq!(key.as_ref(), &[7; 32]);
}

#[tokio::test]
async fn web_session_opens_the_event_chat_key_with_its_opaque_master() {
    let mut web = client(true);
    web.chats.insert(
        CHAT.into(),
        json!({"id":CHAT,
        "encrypted_chat_key":crypto::server_fields::encrypt_bytes(&[5;32],&[9;32],&[]).unwrap()}),
    );
    let key = web.edit_chat_key(CHAT).await.unwrap();
    assert_eq!(key.as_ref(), &[5; 32]);
}

#[test]
fn a_written_event_reaches_the_saving_page_as_its_chat_row() {
    // The server broadcasts the stored system message to the user's other
    // devices only; the outcome carries the row the saving page shows.
    let notice = super::super::EventNotice {
        chat_id: CHAT.into(),
        message_id: "embed-updated-message".into(),
        created_at: 1,
        content: "{\"type\":\"embed_updated\"}".into(),
    };
    let value = serde_json::to_value(&notice).unwrap();
    assert_eq!(value["chat_id"], CHAT);
    assert_eq!(value["content"], "{\"type\":\"embed_updated\"}");
}
