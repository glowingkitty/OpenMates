//! Session state of `ViewModelCore` for the Apple shell: who is signed in
//! (`sessionInfo`: user id, email hash, team, expiry, admitted) and the auth
//! loss rule. When the server rejected the session during a command (the
//! core client forgot it and returned `Expired`), the core signs this
//! profile out locally (durable revocation, cache and Keychain wipe, no
//! remote logout: the server already ended it) and emits `Session(Expired)`
//! through the listener. Bindings only marshal. Plan
//! `apple-client-core-migration` (session ownership); spec `client-core`.
use crate::CoreError;
use crate::view_core::{AppleHost, Shared, ViewModelCore, lock};
use openmates_sdk::{
    error::{Error, Result},
    view_model::{SessionEvent, ViewEvent, ViewHost, ViewSink},
};

/// The signed-in session as Swift may know it. Holds no secret.
#[derive(Clone, Debug, PartialEq, Eq, uniffi::Record)]
pub struct SessionInfoRecord {
    /// Account id once the server admitted the session (`nil` before).
    pub user_id: Option<String>,
    /// The core's email hash of the account (stable account identity).
    pub hashed_email: String,
    /// Active team (`nil`: personal).
    pub active_team_id: Option<String>,
    /// Absolute expiry in unix milliseconds for paired sessions, else `nil`.
    pub expires_at: Option<u64>,
    /// Whether the server admitted the session in this run.
    pub admitted: bool,
}

impl Shared {
    /// Apply the auth loss rule to the outcome of a command on the actor:
    /// `Expired` while the client holds no session any more means the server
    /// rejected it; the profile is then signed out locally and
    /// `Session(Expired)` is emitted. Other outcomes pass through.
    ///
    /// # Errors
    /// The local sign-out error, else `result`'s error.
    pub(crate) async fn settle_auth<T>(
        &self,
        host: &mut Option<AppleHost>,
        result: Result<T>,
    ) -> Result<T> {
        let rejected = matches!(result, Err(Error::Expired))
            && host
                .as_ref()
                .is_some_and(|current| current.core().client().session().is_none());
        if !rejected {
            return result;
        }
        let Some(current) = host.take() else {
            return result;
        };
        *lock(&self.revocation) = None;
        *lock(&self.send_cancel) = None;
        // Generation advanced and revocation durable before the wipe
        // (`ShellSession::clear_credentials`); writes prepared for the
        // rejected session refuse from here on.
        let wiped = current.core().clear_credentials().await;
        drop(current);
        self.sink
            .emit(ViewEvent::Session(SessionEvent::Expired))
            .await?;
        wiped?;
        result
    }

    async fn session_info(&self) -> Result<Option<SessionInfoRecord>> {
        let host = self.host.lock().await;
        let Some(client) = host.as_ref().map(|current| current.core().client()) else {
            return Ok(None);
        };
        let Some(session) = client.session() else {
            return Ok(None);
        };
        let user_id = ["id", "user_id"]
            .into_iter()
            .filter_map(|key| client.user()[key].as_str())
            .find(|id| !id.is_empty())
            .map(str::to_owned);
        Ok(Some(SessionInfoRecord {
            admitted: user_id.is_some(),
            user_id,
            hashed_email: session.hashed_email.clone(),
            active_team_id: session.active_team_id.clone(),
            expires_at: session.paired_session_expires_at,
        }))
    }
}

#[uniffi::export]
impl ViewModelCore {
    /// The signed-in session (`nil` while signed out). Waits for a running
    /// command (a send holds the actor). Auth loss is reported as the
    /// listener event `Session(Expired)` (the profile is then signed out and
    /// wiped), sign-out as `Session(SignedOut)`.
    ///
    /// # Errors
    /// `Internal` for a binding failure only.
    pub async fn session_info(&self) -> std::result::Result<Option<SessionInfoRecord>, CoreError> {
        let shared = self.shared.clone();
        self.run(async move { shared.session_info().await }).await
    }
}
