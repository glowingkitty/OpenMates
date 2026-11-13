//! A pair login cancelled through `finishPairLogin`'s own cancellation after the Keychain store ends signed out with nothing stored, against a loopback relay whose synthetic authorizer runs the real OPAQUE server role and seals the key bundle.
use crate::test_api::{LoopbackApi, Reply, serve};
use crate::view_core_tests::{Events, Keychain, NAME, SIGNED_OUT, private_dir};
use crate::*;
use aes_gcm::{
    Aes256Gcm, KeyInit, Nonce,
    aead::{Aead, Payload},
};
use base64::{Engine as _, engine::general_purpose::URL_SAFE_NO_PAD};
use openmates_sdk::{
    crypto::{encode_key, encrypt_combined, hash_email, hkdf_sha256, random_key},
    pairing::{
        OpaqueIdentifiers, PairContextFields, create_pair_context,
        create_server_registration_response, create_server_setup, finish_client_registration,
        finish_server_login, start_client_registration, start_server_login,
    },
    session::Session,
};
use serde_json::{Value, json};
use sha2::{Digest, Sha256};
use std::sync::{Arc, Mutex};

const USER: &str = "synthetic-user";
const PAIR_TOKEN: &str = "SYNTH4";
const PIN: &str = "W4P3KQ";
const EMAIL: &str = "user@example.org";

/// Ten minutes from now in unix seconds (the core refuses codes valid for
/// more than an hour).
fn expires() -> u64 {
    std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .unwrap()
        .as_secs()
        + 600
}

/// Relay state of the one pairing.
#[derive(Default)]
struct Relay {
    session_id: Value,
    receiver_token_hash: Value,
    context: String,
    server_login_state: String,
    login_response: String,
    sealed: Option<(String, String)>,
}

impl Relay {
    fn identifiers(&self) -> OpaqueIdentifiers {
        OpaqueIdentifiers {
            client: format!("openmates-pair-v2/client/{}", self.context),
            server: format!("openmates-pair-v2/server/{}", self.context),
        }
    }

    fn state(&self, status: &str) -> Value {
        json!({"status": status, "session_id": self.session_id,
            "receiver_token_hash": self.receiver_token_hash,
            "authorizer_user_id": USER, "auto_logout_minutes": null,
            "expires_at": expires()})
    }

    /// The authorizer's OPAQUE server answer (KE2) to the receiver's KE1,
    /// over a registration of the PIN it showed.
    fn answer(&mut self, request: &str) {
        let fields = PairContextFields {
            token: PAIR_TOKEN.into(),
            session_id: self.session_id.as_str().unwrap().into(),
            receiver_token_hash: self.receiver_token_hash.as_str().unwrap().into(),
            authorizer_user_id: USER.into(),
            auto_logout_minutes: None,
        };
        self.context = create_pair_context(&fields).unwrap();
        let ids = self.identifiers();
        let setup = create_server_setup();
        let registration = start_client_registration(PIN).unwrap();
        let response =
            create_server_registration_response(&setup, USER, &registration.registration_request)
                .unwrap();
        let record = finish_client_registration(
            PIN,
            &registration.client_registration_state,
            &response,
            &ids,
        )
        .unwrap();
        let started = start_server_login(&setup, &record, request, USER, &ids).unwrap();
        self.server_login_state = started.server_login_state.to_string();
        self.login_response = started.login_response;
    }

    /// Finish the server login (KE3) and seal the synthetic account bundle
    /// with the key both sides derive from the OPAQUE session key.
    fn seal(&mut self, finish: &str) {
        let session_key =
            finish_server_login(&self.server_login_state, finish, &self.identifiers()).unwrap();
        let session_key = URL_SAFE_NO_PAD.decode(session_key.as_str()).unwrap();
        let salt = Sha256::digest(self.context.as_bytes());
        let key = hkdf_sha256(&session_key, &salt, b"openmates-pair-v2/bundle").unwrap();
        let master = random_key();
        let bundle = json!({
            "protocol_version": 2,
            "master_key_exported": encode_key(&master),
            "grant_secret": URL_SAFE_NO_PAD.encode([5u8; 32]),
            "user_email_salt": "AAECAwQFBgcICQoLDA0ODw==",
            "hashed_email": hash_email(EMAIL),
            "user_id": USER,
            "account_context": {
                "encrypted_email_with_master_key": encrypt_combined(EMAIL, &master).unwrap()
            },
        });
        let iv = [3u8; 12];
        let ciphertext = Aes256Gcm::new_from_slice(key.as_slice())
            .unwrap()
            .encrypt(
                Nonce::from_slice(&iv),
                Payload {
                    msg: bundle.to_string().as_bytes(),
                    aad: self.context.as_bytes(),
                },
            )
            .unwrap();
        self.sealed = Some((
            URL_SAFE_NO_PAD.encode(ciphertext),
            URL_SAFE_NO_PAD.encode(iv),
        ));
    }
}

/// Loopback relay of an authorizer that approved at once.
async fn relay_api() -> LoopbackApi {
    let relay = Arc::new(Mutex::new(Relay::default()));
    serve(move |line, body| {
        let mut relay = relay.lock().unwrap();
        let receiver = format!("/v1/auth/pair/v2/receiver/{PAIR_TOKEN}");
        let path = line.split(' ').nth(1).unwrap_or_default();
        match (line.split(' ').next().unwrap_or_default(), path) {
            ("POST", "/v1/auth/pair/v2/initiate") => {
                relay.session_id = body["session_id"].clone();
                relay.receiver_token_hash = body["receiver_token_hash"].clone();
                Reply::Json(json!({"protocol_version": 2, "token": PAIR_TOKEN,
                    "expires_at": expires()}))
            }
            ("GET", path) if path == receiver => {
                if let Some((bundle, iv)) = relay.sealed.clone() {
                    let mut state = relay.state("ready");
                    state["encrypted_bundle"] = json!(bundle);
                    state["iv"] = json!(iv);
                    Reply::Json(state)
                } else if !relay.login_response.is_empty() {
                    let mut state = relay.state("response");
                    state["message"] = json!(relay.login_response);
                    Reply::Json(state)
                } else {
                    Reply::Json(relay.state("approved"))
                }
            }
            ("POST", path) if path == format!("{receiver}/message") => {
                let message = body["message"].as_str().unwrap();
                match body["stage"].as_str() {
                    Some("request") => relay.answer(message),
                    Some("finish") => relay.seal(message),
                    _ => return Reply::Close,
                }
                Reply::Json(json!({"success": true}))
            }
            ("POST", path) if path == format!("/v1/auth/pair/v2/complete/{PAIR_TOKEN}") => {
                Reply::JsonWithCookie(json!({"success": true, "ws_token": "synthetic",
                    "user": {"id": USER}}))
            }
            ("POST", path) if path == format!("/v1/auth/pair/v2/acknowledge/{PAIR_TOKEN}") => {
                Reply::Json(json!({"success": true}))
            }
            ("POST", "/v1/auth/logout") => Reply::Json(json!({"success": true})),
            ("DELETE", path) if path == format!("/v1/auth/pair/v2/{PAIR_TOKEN}") => {
                Reply::Json(json!({}))
            }
            _ => Reply::Close,
        }
    })
    .await
}

/// Cancels the `CoreCancellation` when the store arrives, then stores and
/// acknowledges a little later (the cancel lands after the store began).
struct CancellingKeychain {
    inner: Arc<Keychain>,
    cancel: Arc<CoreCancellation>,
}

impl CredentialStore for CancellingKeychain {
    fn load(&self) -> std::result::Result<Option<Vec<u8>>, CoreError> {
        self.inner.load()
    }
    fn credentials_changed(&self, snapshot: CredentialSnapshotRecord) {
        self.cancel.cancel();
        let inner = self.inner.clone();
        std::thread::spawn(move || {
            std::thread::sleep(std::time::Duration::from_millis(50));
            inner.credentials_changed(snapshot);
        });
    }
    fn delete(&self) -> std::result::Result<(), CoreError> {
        self.inner.delete()
    }
}

fn stored(keychain: &Keychain) -> Option<Session> {
    let payload = keychain.payload.lock().unwrap().clone()?;
    Some(serde_json::from_slice(&payload).unwrap())
}

#[tokio::test(flavor = "multi_thread")]
async fn a_pair_login_cancelled_after_the_keychain_store_leaves_nothing_stored() {
    let dir = private_dir();
    let api = relay_api().await;
    let inner = Arc::new(Keychain {
        acknowledge: true,
        ..Keychain::default()
    });
    let (events, cancel) = (Arc::new(Events::default()), CoreCancellation::new());
    let store = Arc::new(CancellingKeychain {
        inner: inner.clone(),
        cancel: cancel.clone(),
    });
    let config = CoreConfig {
        api_url: api.url.clone(),
        app_url: None,
        cache_container: Some(dir.path().to_str().unwrap().to_owned()),
        cache_directory_name: Some(NAME.into()),
    };
    let core = ViewModelCore::build(
        config,
        store,
        events.clone(),
        std::time::Duration::from_secs(5),
    )
    .unwrap();
    inner.core.set(Arc::downgrade(&core)).unwrap();
    core.begin_pair_login().await.unwrap();
    assert_eq!(core.poll_pair_login().await.unwrap(), "approved");
    core.submit_pair_pin(PIN.into()).await.unwrap();
    // The authorizer answered the PIN request: the finish message goes out.
    assert_eq!(core.finish_pair_login(None).await, Ok(false));
    // The bundle arrives; the cancel fires once the store began.
    assert_eq!(
        core.finish_pair_login(Some(cancel)).await,
        Err(CoreError::Cancelled)
    );
    // Stored once, then wiped; the paired server session was logged out.
    assert_eq!(inner.changed.lock().unwrap().len(), 1);
    assert!(stored(&inner).is_none());
    assert!(api.count("POST /v1/auth/logout ") >= 1);
    assert_eq!(events.all(), [SIGNED_OUT]);
    // The pairing is over, and a later start finds nothing to restore.
    assert!(matches!(
        core.finish_pair_login(None).await,
        Err(CoreError::Invalid { .. })
    ));
    core.start(None).await.unwrap();
    assert_eq!(events.all().last(), Some(&SIGNED_OUT));
}
