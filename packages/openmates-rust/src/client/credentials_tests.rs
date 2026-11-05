//! Explicit native serialization and browser resource-separation regressions.
// contract-test-file: tooling
use super::*;
use crate::crypto::master::{MasterCrypto, MasterCryptoFuture};
use std::sync::Arc;
struct SyntheticAesPort {
    key: Key,
}
impl MasterCrypto for SyntheticAesPort {
    fn encrypt<'a>(&'a self, iv: &'a [u8; 12], plain: &'a [u8]) -> MasterCryptoFuture<'a> {
        Box::pin(async move {
            crypto::encrypt_aead(plain, &self.key, iv, &[]).map(zeroize::Zeroizing::new)
        })
    }
    fn decrypt<'a>(&'a self, iv: &'a [u8; 12], cipher: &'a [u8]) -> MasterCryptoFuture<'a> {
        Box::pin(async move { crypto::decrypt_aead(cipher, &self.key, iv, &[]) })
    }
}
fn native() -> Client {
    let mut session = crate::client::sdk_boundary_tests::session();
    session.api_url = "http://127.0.0.1:9".into();
    let mut c = Client::new("http://127.0.0.1:9", Some(session)).unwrap();
    c.user = json!({"id":"11111111-1111-4111-8111-111111111111"});
    c
}
fn opaque() -> MasterCapability {
    MasterCapability::opaque_for_test(Arc::new(SyntheticAesPort {
        key: zeroize::Zeroizing::new([1; 32]),
    }))
}
fn browser() -> Client {
    let mut c = native();
    let session = c.session.take().unwrap();
    let mut browser = BrowserCredentials::from_native_session(session);
    browser.master = opaque();
    c.browser_credentials = Some(browser);
    c.browser_authority = Some(browser::BrowserAuthority {
        principal: "11111111-1111-4111-8111-111111111111".into(),
        persistence: browser::BrowserPersistence::MemoryOnly,
        owner_guards: true,
    });
    c
}
#[test]
fn native_public_session_bytes_and_exact_fresh_binding_stay_unchanged() {
    let c = native();
    let before = serde_json::to_vec(c.session().unwrap()).unwrap();
    let _scope = c.require_credentials().unwrap();
    let _capability = c.master_capability().unwrap();
    assert_eq!(serde_json::to_vec(c.session().unwrap()).unwrap(), before);
    let principal = c.user["id"].as_str().unwrap();
    let encoded = zeroize::Zeroizing::new(
        serde_json::to_vec(&(
            c.require_session().unwrap(),
            &c.cookies,
            principal,
            c.base.as_str(),
            c.app_url(),
            c.options.identity.header(),
            c.options.interactive,
        ))
        .unwrap(),
    );
    use sha2::Digest;
    let expected: [u8; 32] = sha2::Sha256::digest(encoded.as_slice()).into();
    assert_eq!(c.fresh_auth_binding().unwrap(), expected);
}
#[test]
fn browser_credentials_have_no_native_session_raw_key_snapshot_or_ack() {
    let c = browser();
    assert!(c.session.is_none());
    assert!(c.session().is_none());
    assert!(c.credential_snapshot().is_none());
    assert_eq!(c.credential_ack, 0);
    assert_eq!(
        c.require_credentials().unwrap().session_id.as_str(),
        "fixture"
    );
    assert!(matches!(
        c.native_master_key(),
        Err(Error::Unavailable {
            code: "master_key_extraction_unavailable",
            ..
        })
    ));
    assert!(matches!(
        c.require_session(),
        Err(Error::Unavailable {
            code: "native_session_required",
            ..
        })
    ));
}
#[tokio::test]
async fn browser_binding_changes_on_same_material_replacement_and_forget_revokes_old_instance() {
    let mut c = browser();
    let old = c.master_capability().unwrap();
    let binding = c.master_binding().unwrap();
    let context = c.fresh_auth_binding().unwrap();
    assert!(binding.check(&c).is_ok());
    c.browser_credentials.as_mut().unwrap().master = opaque();
    assert!(!old.same_instance(&c.master_capability().unwrap()));
    assert!(matches!(binding.check(&c), Err(Error::Cancelled)));
    assert_ne!(context, c.fresh_auth_binding().unwrap());
    let current = c.master_capability().unwrap();
    c.forget_session();
    assert!(matches!(
        current.encrypt_bytes(b"private").await,
        Err(Error::Cancelled)
    ));
    assert!(c.require_credentials().is_err());
    assert!(c.credential_snapshot().is_none());
    assert_eq!(c.credential_ack, 0);
}
#[test]
fn local_instance_identity_cannot_authorize_snapshot_owner_or_native_ack() {
    let mut c = browser();
    c.browser_authority.as_mut().unwrap().persistence = browser::BrowserPersistence::Persisted;
    c.user = json!({"id":"22222222-2222-4222-8222-222222222222"});
    assert!(
        c.begin_browser_credential_cas(
            serde_json::from_value(json!({"lifecycleGeneration":1,"workspaceEpoch":0})).unwrap()
        )
        .is_err()
    );
    assert!(c.acknowledge_credentials(c.credential_revision).is_err());
    assert_eq!(c.credential_ack, 0);
}
