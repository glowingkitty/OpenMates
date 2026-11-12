//! The admitted account on `ViewModelCore` for the Apple shell: the server's
//! user payload (`userProfile` / `userProfileJson`, refreshed by every
//! admission and announced by `Session(Admitted)`; before the server answers
//! a restored session, the payload cached at the last admission, flagged not
//! fresh; Swift decodes it with its `UserProfile`, the same seam as the web
//! shell) and the server's verification requests
//! (`Session(VerificationRequired)`, `pendingVerification`,
//! `verifyDevice2fa`). Policy lives in the core
//! (`openmates_sdk::client::SessionVerification`, shared with the web
//! classifier); this module only marshals. Plan `apple-client-core-migration`
//! (auth session); spec `architecture.client-core`.
use crate::CoreError;
use crate::core::CoreCancellation;
use crate::view_core::{AppleHost, Shared, ViewModelCore};
use openmates_sdk::{
    client::{DeviceVerificationMethod, SessionVerification},
    error::{Error, Result},
    view_model::{SessionEvent, ViewEvent, ViewHost, ViewSink},
};
use std::sync::Arc;
use zeroize::Zeroizing;

/// The account's user payload and where it came from.
#[derive(Clone, PartialEq, Eq, uniffi::Record)]
pub struct UserProfileRecord {
    /// UTF-8 JSON object exactly as the server sent it (secret-bearing:
    /// never log it).
    pub json: Vec<u8>,
    /// `true`: admitted by the server in this run. `false`: cached from the
    /// last admission of this account while the restored session is not
    /// admitted yet (offline start); replaced by the next admission.
    pub fresh: bool,
}

/// The factor the server asks for (core `DeviceVerificationMethod`).
#[derive(Clone, Copy, Debug, PartialEq, Eq, uniffi::Enum)]
pub enum DeviceVerificationMethodRecord {
    /// A code from the authenticator app: answer with `verifyDevice2fa`.
    TwoFactor,
    /// A passkey assertion. The ceremony is Swift's (`ASAuthorization`); the
    /// core does not finish passkey device verification yet.
    Passkey,
}

/// What the server asks before it admits the session (core
/// `SessionVerification`). Holds no secret.
#[derive(Clone, Debug, PartialEq, Eq, uniffi::Enum)]
pub enum SessionVerificationRecord {
    /// Verify this device with `method`.
    Device {
        /// The factor to use.
        method: DeviceVerificationMethodRecord,
        /// Why (`new_device`, `location_change`, `session_verification`).
        reason: String,
        /// A passkey check may also be answered with the password.
        password_fallback_available: bool,
    },
    /// Sign in again (`logout`, then a new login); no factor approves this
    /// session.
    ReAuth {
        /// Why, as the server named it.
        reason: String,
    },
}

impl From<SessionVerification> for SessionVerificationRecord {
    fn from(value: SessionVerification) -> Self {
        match value {
            SessionVerification::Device {
                method,
                reason,
                password_fallback_available,
            } => Self::Device {
                method: match method {
                    DeviceVerificationMethod::TwoFactor => {
                        DeviceVerificationMethodRecord::TwoFactor
                    }
                    DeviceVerificationMethod::Passkey => DeviceVerificationMethodRecord::Passkey,
                },
                reason,
                password_fallback_available,
            },
            SessionVerification::ReAuth { reason } => Self::ReAuth { reason },
        }
    }
}

impl Shared {
    /// A command ended in `VerificationRequired` (admission at start, login,
    /// adoption, team switch, or a later session check): announce what the
    /// server asks as `Session(VerificationRequired)`. The session and its
    /// stored credentials stay (the server kept the session). Called by
    /// `settle_auth`, so every command path announces exactly once.
    ///
    /// # Errors
    /// The listener failure.
    pub(crate) async fn announce_verification(&self, host: &Option<AppleHost>) -> Result<()> {
        let pending = host
            .as_ref()
            .and_then(|current| current.core().client().session_verification().cloned());
        match pending {
            Some(verification) => {
                let event = SessionEvent::VerificationRequired(verification);
                self.sink.emit(ViewEvent::Session(event)).await
            }
            None => Ok(()),
        }
    }

    /// The admitted payload, else the cached one of a restored session that
    /// is not admitted yet and has no verification pending.
    async fn user_profile(&self) -> Result<UserProfileRecord> {
        let host = self.host.lock().await;
        let current = host.as_ref().ok_or(Error::Authentication)?;
        let client = current.core().client();
        if client.session().is_none() {
            return Err(Error::Authentication);
        }
        let user = client.user();
        // Admitted means the server named the account in this run.
        let admitted = ["id", "user_id"]
            .into_iter()
            .any(|key| user[key].as_str().is_some_and(|id| !id.is_empty()));
        if admitted {
            return Ok(UserProfileRecord {
                json: serde_json::to_vec(user)?,
                fresh: true,
            });
        }
        // The server answered and did not admit: no stale account is shown.
        if client.session_verification().is_some() {
            return Err(Error::Authentication);
        }
        let cached = current.core().shell().cached_user(client).await?;
        let user = cached.ok_or(Error::Authentication)?;
        Ok(UserProfileRecord {
            json: serde_json::to_vec(&user)?,
            fresh: false,
        })
    }

    async fn pending_verification(&self) -> Option<SessionVerificationRecord> {
        let host = self.host.lock().await;
        host.as_ref()
            .and_then(|current| current.core().client().session_verification().cloned())
            .map(Into::into)
    }
}

#[uniffi::export]
impl ViewModelCore {
    /// The account's user payload exactly as the server sent it (UTF-8 JSON
    /// object; decode it with `UserProfile`): the admitted one, or for a
    /// restored session the server has not admitted yet (offline start) the
    /// one cached at this account's last admission. `userProfile` tells the
    /// two apart. Replaced by every admission (login, restore, adoption, team
    /// switch), each announced by `Session(Admitted)`; gone after sign-out.
    /// It contains what the server payload contains (among it the wrapped
    /// master key fields), so never log it. Waits for a running command.
    ///
    /// # Errors
    /// As `userProfile`.
    pub async fn user_profile_json(&self) -> std::result::Result<Vec<u8>, CoreError> {
        let shared = self.shared.clone();
        self.run(async move { shared.user_profile().await.map(|profile| profile.json) })
            .await
    }

    /// The account's user payload with `fresh` (admitted in this run) or not
    /// (cached at the last admission, the server not reached yet). Waits for
    /// a running command.
    ///
    /// # Errors
    /// `Authentication` while signed out, while a verification is pending,
    /// or before the first admission of this account on this profile (no
    /// cached payload); `Protocol` or `Io` for an unreadable cached record.
    pub async fn user_profile(&self) -> std::result::Result<UserProfileRecord, CoreError> {
        let shared = self.shared.clone();
        self.run(async move { shared.user_profile().await }).await
    }

    /// The verification the server asked for at the last session check, or
    /// `nil` (also announced as `Session(VerificationRequired)`). Waits for a
    /// running command.
    ///
    /// # Errors
    /// `Internal` for a binding failure only.
    pub async fn pending_verification(
        &self,
    ) -> std::result::Result<Option<SessionVerificationRecord>, CoreError> {
        let shared = self.shared.clone();
        self.run(async move { Ok(shared.pending_verification().await) })
            .await
    }

    /// Answer a pending two-factor device verification with the
    /// authenticator `code` (zeroized after the call; never stored or
    /// logged), then admit the session again (`Session(Admitted)`). Run
    /// `bootSync` afterwards for the network chat list.
    ///
    /// # Errors
    /// `Authentication` while signed out or when the server refused the code
    /// (the verification stays pending; ask again); `Invalid` without a
    /// pending two-factor verification or for a malformed code (nothing
    /// sent); `Expired` when the server ended the session (the profile is
    /// then signed out and wiped, `Session(Expired)`); `VerificationRequired`
    /// when the server still asks; `Offline`, `Protocol`; `Cancelled` when
    /// `cancellation` fired.
    pub async fn verify_device_2fa(
        &self,
        code: String,
        cancellation: Option<Arc<CoreCancellation>>,
    ) -> std::result::Result<(), CoreError> {
        let code = Zeroizing::new(code);
        let (shared, token) = (self.shared.clone(), self.foreground(cancellation));
        self.run(async move {
            shared
                .signed_in(token, move |host, sink, _cancel| {
                    Box::pin(async move {
                        let verified = host.core_mut().client_mut().verify_device_2fa(&code).await;
                        drop(code);
                        verified?;
                        host.admit(sink).await
                    })
                })
                .await
        })
        .await
    }
}
