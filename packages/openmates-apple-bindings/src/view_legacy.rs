//! Frozen remainders for Swift code that is not migrated yet: the two
//! session secrets the core must not otherwise hand out. `legacySocketGrant`
//! (session id and `ws_token` for `WebSocketManager`'s own socket; removed
//! when the core's transport serves the Apple shell, plan
//! `apple-client-core-migration` step A4a) and `legacyMasterKey` (for the
//! remaining `CryptoManager` callers; removed with step A3b). Both are
//! refused while signed out. Nothing new may start using them. Spec `client-core`.
use crate::CoreError;
use crate::view_core::{Shared, ViewModelCore};
use openmates_sdk::{
    error::{Error, Result},
    session::Session,
    view_model::ViewHost,
};

/// What `WebSocketManager` needs to open its socket for the core's session.
#[derive(uniffi::Record)]
pub struct LegacySocketGrantRecord {
    /// The session id (`session_id` query parameter of the socket URL).
    pub session_id: String,
    /// The current `ws_token` (secret; rotated by every admission), `nil`
    /// before the first admission handed one out.
    pub ws_token: Option<String>,
}

impl Shared {
    async fn with_session<T>(&self, read: impl FnOnce(&Session) -> T) -> Result<T> {
        let host = self.host.lock().await;
        let session = host
            .as_ref()
            .and_then(|current| current.core().client().session())
            .ok_or(Error::Authentication)?;
        if session.is_expired() {
            return Err(Error::Expired);
        }
        Ok(read(session))
    }
}

#[uniffi::export]
impl ViewModelCore {
    /// FROZEN REMAINDER (removed with plan step A4a). The session id and
    /// current `ws_token` for Swift's own WebSocket. The server keys sockets
    /// by account and device, so a second socket of this app replaces the
    /// first: valid only while the core opens no socket of its own (today
    /// the Apple host runs no core monitor). Ask again after every
    /// `Session(Admitted)`, the token rotates.
    ///
    /// # Errors
    /// `Authentication` while signed out; `Expired` for a lapsed pairing.
    pub async fn legacy_socket_grant(
        &self,
    ) -> std::result::Result<LegacySocketGrantRecord, CoreError> {
        let shared = self.shared.clone();
        self.run(async move {
            shared
                .with_session(|session| LegacySocketGrantRecord {
                    session_id: session.session_id.clone(),
                    ws_token: session.ws_token.clone(),
                })
                .await
        })
        .await
    }

    /// FROZEN REMAINDER (removed with plan step A3b). The 32-byte master key
    /// for the remaining Swift `CryptoManager` callers. Swift keeps it in
    /// memory only (never in its own Keychain item) and drops it on
    /// `Session(SignedOut)` or `Session(Expired)`.
    ///
    /// # Errors
    /// `Authentication` while signed out; `Expired` for a lapsed pairing.
    pub async fn legacy_master_key(&self) -> std::result::Result<Vec<u8>, CoreError> {
        let shared = self.shared.clone();
        self.run(async move {
            shared
                .with_session(|session| session.master_key.to_vec())
                .await
        })
        .await
    }
}
