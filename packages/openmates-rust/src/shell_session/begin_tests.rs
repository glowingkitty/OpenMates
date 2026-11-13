//! Fresh session after logout over `AcknowledgedCredentials` and a real cache directory: new unrevoked epoch, stale records and vault wiped, revoked contexts refused, signed-in profile protected, retry and cancellation.
use super::*;
use crate::{
    client::CredentialSnapshot,
    local_cache::{
        ByteStore, CacheEngine, Durability, FileByteStore, REVOCATION_FILE, RevocationFence,
        publish_record,
    },
};
use std::os::unix::fs::PermissionsExt;
use std::sync::{Arc, Mutex, OnceLock, Weak};
use tokio_util::sync::CancellationToken;

type Credentials = AcknowledgedCredentials<FileByteStore>;

fn session(id: &str) -> Session {
    Session {
        api_url: "https://never-contact.example.invalid".into(),
        session_id: id.into(),
        cookies: Default::default(),
        ws_token: None,
        master_key: Zeroizing::new([7; 32]),
        hashed_email: "synthetic-owner".into(),
        user_email_salt: String::new(),
        email_encryption_key: None,
        created_at: 1,
        paired_session_expires_at: None,
        active_team_id: None,
    }
}

fn snapshot(id: &str) -> CredentialSnapshot {
    CredentialSnapshot {
        revision: 1,
        session: session(id),
    }
}

/// In-memory Keychain that stores and acknowledges at once.
#[derive(Default)]
struct Vault {
    payload: Mutex<Option<Vec<u8>>>,
    credentials: OnceLock<Weak<Credentials>>,
}

impl CredentialVault for Vault {
    fn load(&self) -> Result<Option<Zeroizing<Vec<u8>>>> {
        Ok(self.payload.lock().unwrap().clone().map(Zeroizing::new))
    }
    fn credentials_changed(&self, revision: u64, payload: &[u8]) {
        *self.payload.lock().unwrap() = Some(payload.to_vec());
        if let Some(credentials) = self.credentials.get().and_then(Weak::upgrade) {
            credentials.acknowledge(revision).unwrap();
        }
    }
    fn delete(&self) -> Result<()> {
        *self.payload.lock().unwrap() = None;
        Ok(())
    }
}

struct Profile {
    _dir: tempfile::TempDir,
    engine: Arc<CacheEngine<FileByteStore>>,
    vault: Arc<Vault>,
    credentials: Arc<Credentials>,
}

fn profile() -> Profile {
    let mut builder = tempfile::Builder::new();
    builder.permissions(std::fs::Permissions::from_mode(0o700));
    let dir = builder.tempdir().unwrap();
    let bytes = FileByteStore::open_in(dir.path(), "core-cache").unwrap();
    let engine = Arc::new(CacheEngine::new(bytes));
    let vault = Arc::new(Vault::default());
    let credentials = Arc::new(Credentials::new(vault.clone(), engine.clone()));
    vault.credentials.set(Arc::downgrade(&credentials)).unwrap();
    Profile {
        _dir: dir,
        engine,
        vault,
        credentials,
    }
}

impl Profile {
    fn fence(&self) -> RevocationFence {
        RevocationFence::load(self.engine.bytes()).unwrap()
    }
    async fn sign_out(&self) {
        self.credentials.revoke().await.unwrap();
        self.credentials.clear().await.unwrap();
    }
}

#[tokio::test]
async fn begin_after_logout_opens_a_new_unrevoked_epoch_and_stores_the_session() {
    let p = profile();
    let cancel = CancellationToken::new();
    p.credentials
        .begin_session(snapshot("first"), &cancel)
        .await
        .unwrap();
    p.sign_out().await;
    let revoked = p.fence();
    assert!(revoked.revoked);
    // Signed out: nothing is handed out and stores are refused.
    assert!(p.credentials.load(0).await.unwrap().is_none());
    assert!(matches!(
        p.credentials.store(snapshot("second"), 0).await,
        Err(Error::Locked)
    ));

    p.credentials
        .begin_session(snapshot("second"), &cancel)
        .await
        .unwrap();
    let fresh = p.fence();
    assert!(!fresh.revoked);
    assert_ne!(fresh.epoch, revoked.epoch);
    let context = session_cache_context(&session("second")).unwrap().context;
    assert_eq!(fresh.context.as_deref(), Some(context.as_str()));
    assert_eq!(fresh.admitted.as_deref(), Some(context.as_str()));
    let loaded = p.credentials.load(0).await.unwrap().unwrap();
    assert_eq!(loaded.session_id, "second");
    // A write prepared for the revoked epoch never lands.
    let late = publish_record(
        p.engine.bytes(),
        "cache-late.json",
        &revoked.epoch,
        b"{}",
        |name, bytes| Ok(p.engine.bytes().put(name, bytes, Durability::Now)?),
    );
    assert!(matches!(late, Err(Error::Cancelled)));
}

#[tokio::test]
async fn begin_wipes_records_and_credentials_a_failed_cleanup_left_behind() {
    let p = profile();
    let cancel = CancellationToken::new();
    p.credentials
        .begin_session(snapshot("first"), &cancel)
        .await
        .unwrap();
    let bytes = p.engine.bytes();
    bytes
        .put("cache-stale.json", b"{}", Durability::Now)
        .unwrap();
    // Revoked, but cleanup never ran (the app was killed in between).
    p.credentials.revoke().await.unwrap();
    p.credentials
        .begin_session(snapshot("second"), &cancel)
        .await
        .unwrap();
    assert!(bytes.get("cache-stale.json").unwrap().is_none());
    let stored: Session =
        serde_json::from_slice(&p.vault.payload.lock().unwrap().clone().unwrap()).unwrap();
    assert_eq!(stored.session_id, "second");
}

#[tokio::test]
async fn a_revoked_session_never_begins_again() {
    let p = profile();
    let cancel = CancellationToken::new();
    p.credentials
        .begin_session(snapshot("first"), &cancel)
        .await
        .unwrap();
    p.sign_out().await;
    assert!(matches!(
        p.credentials
            .begin_session(snapshot("first"), &cancel)
            .await,
        Err(Error::Authentication)
    ));
    assert!(p.fence().revoked);
}

#[tokio::test]
async fn a_signed_in_profile_is_not_replaced_without_sign_out() {
    let p = profile();
    let cancel = CancellationToken::new();
    p.credentials
        .begin_session(snapshot("first"), &cancel)
        .await
        .unwrap();
    let epoch = p.fence().epoch;
    // The same session again is a retry: same epoch, still stored.
    p.credentials
        .begin_session(snapshot("first"), &cancel)
        .await
        .unwrap();
    assert_eq!(p.fence().epoch, epoch);
    assert!(matches!(
        p.credentials
            .begin_session(snapshot("other"), &cancel)
            .await,
        Err(Error::Invalid(_))
    ));
    assert_eq!(p.fence().epoch, epoch);
}

#[tokio::test]
async fn a_cancelled_begin_leaves_the_revoked_fence_in_place() {
    let p = profile();
    p.sign_out().await;
    let before = p.fence();
    let cancel = CancellationToken::new();
    cancel.cancel();
    assert!(matches!(
        p.credentials
            .begin_session(snapshot("second"), &cancel)
            .await,
        Err(Error::Cancelled)
    ));
    let after = p.fence();
    assert!(after.revoked);
    assert_eq!(after.epoch, before.epoch);
    assert!(p.engine.bytes().get(REVOCATION_FILE).unwrap().is_some());
}
