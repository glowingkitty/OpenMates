//! Core-performed passkey login and passkey device verification on
//! `ViewModelCore`. Swift runs only the system WebAuthn ceremony
//! (`ASAuthorizationController`) with the options JSON the core hands out and
//! returns the assertion and PRF output; the core keeps the continuation
//! (`openmates_sdk::client::PasskeyContinuation`) and performs verification,
//! key derivation, unwrap, login and admission (`Client::passkey_login_*`,
//! `Client::passkey_device_verification_*`). The login ends in the shared
//! `Shared::login` hand-over, so its cancel semantics equal the other logins.
//! Plan `apple-client-core-migration` (A2 Apple login hand-over).
use crate::CoreError;
use crate::core::CoreCancellation;
use crate::view_core::{Shared, ViewModelCore};
use crate::view_login::LoginMethod;
use crate::view_login_migration::LoginRecord;
use openmates_sdk::{
    Client,
    client::PasskeyChallenge,
    error::{Error, Result},
    view_model::ViewHost,
};
use std::sync::Arc;
use tokio_util::sync::CancellationToken;
use zeroize::Zeroizing;

/// A finish step without a begun passkey request.
const NO_PASSKEY: Error = Error::Invalid("Begin a passkey request first.");

/// The WebAuthn request options for the system passkey ceremony.
#[derive(Clone, Debug, PartialEq, Eq, uniffi::Record)]
pub struct PasskeyChallengeRecord {
    /// The server's `/v1/auth/passkey/assertion/initiate` reply as UTF-8 JSON
    /// (`challenge` base64url, `rp.id`, `timeout`, `allowCredentials`,
    /// `userVerification`, `extensions.prf.eval.first` base64url salt). Holds
    /// no secret; the continuation stays in the core.
    pub options_json: Vec<u8>,
}

impl Shared {
    /// Keep `challenge`'s continuation (replacing an earlier one) and hand
    /// out its options, unless `cancel` fired meanwhile.
    async fn keep_passkey(
        &self,
        challenge: PasskeyChallenge,
        cancel: &CancellationToken,
    ) -> Result<PasskeyChallengeRecord> {
        if cancel.is_cancelled() {
            return Err(Error::Cancelled);
        }
        *self.passkey.lock().await = Some(challenge.continuation);
        Ok(PasskeyChallengeRecord {
            options_json: challenge.options_json,
        })
    }

    async fn begin_passkey_login(
        &self,
        email: Option<String>,
        cancel: CancellationToken,
    ) -> Result<PasskeyChallengeRecord> {
        let host = self.host.lock().await;
        if host.is_some() {
            return Err(Error::Invalid(
                "Sign out before signing in to another account.",
            ));
        }
        let mut client = Client::with_options(&self.api_url, None, self.options())?;
        let challenge = client.passkey_login_begin(email.as_deref()).await?;
        drop(host);
        self.keep_passkey(challenge, &cancel).await
    }

    async fn begin_passkey_device_verification(
        &self,
        cancel: CancellationToken,
    ) -> Result<PasskeyChallengeRecord> {
        let challenge = self
            .signed_in(cancel.clone(), |host, _sink, _cancel| {
                Box::pin(async move {
                    host.core_mut()
                        .client_mut()
                        .passkey_device_verification_begin()
                        .await
                })
            })
            .await?;
        self.keep_passkey(challenge, &cancel).await
    }

    async fn finish_passkey_device_verification(
        &self,
        assertion_json: Vec<u8>,
        cancel: CancellationToken,
    ) -> Result<()> {
        let continuation = self.passkey.lock().await.take().ok_or(NO_PASSKEY)?;
        self.signed_in(cancel, move |host, sink, _cancel| {
            Box::pin(async move {
                host.core_mut()
                    .client_mut()
                    .passkey_device_verification_finish(continuation, &assertion_json)
                    .await?;
                host.admit(sink).await
            })
        })
        .await
    }
}

#[uniffi::export]
impl ViewModelCore {
    /// Begin a passkey sign-in: returns the options for the system passkey
    /// ceremony; the core keeps the continuation (a new begin replaces it).
    /// Without `email` any passkey of this device may answer (discoverable
    /// credential, the current Apple and web flow); with `email` the server
    /// lists only that account's passkeys and the core refuses another
    /// account's passkey at finish.
    ///
    /// # Errors
    /// `Invalid` while signed in; `Authentication` for a malformed email or a
    /// refused request; `Offline`, `Protocol`; `Cancelled` when
    /// `cancellation` fired (nothing kept).
    pub async fn begin_passkey_login(
        &self,
        email: Option<String>,
        cancellation: Option<Arc<CoreCancellation>>,
    ) -> std::result::Result<PasskeyChallengeRecord, CoreError> {
        let (shared, token) = (self.shared.clone(), self.foreground(cancellation));
        self.run(async move { shared.begin_passkey_login(email, token).await })
            .await
    }

    /// Finish the begun passkey sign-in with the ceremony's result, then hand
    /// over and `start` exactly as `loginPassword` (`passwordMigration` is
    /// `NotNeeded`, `remainingBackupCodes` nil). `assertionJson` is UTF-8
    /// JSON `{"credential_id": base64url raw id, "client_data_json",
    /// "authenticator_data", "signature", "user_handle"?: standard base64 of
    /// the raw bytes}`; `prfOutput` is the raw PRF `first` output (16..=64
    /// bytes), zeroized after the core call, never sent, stored or logged.
    /// The continuation is used up by this call: begin again to retry.
    ///
    /// # Errors
    /// `Invalid` without a begun passkey login, while signed in, for an
    /// unreadable assertion or one of another request
    /// (`PASSKEY_OTHER_REQUEST`), without a usable PRF output
    /// (`PASSKEY_PRF_UNAVAILABLE`: the passkey or OS lacks PRF support) or for
    /// another account's passkey (`PASSKEY_WRONG_ACCOUNT`); the message is the
    /// core's fixed English reason. `Authentication` when the server refused
    /// the passkey or the login; `Crypto` when the master key does not
    /// unwrap; then as `loginPassword`, including `Cancelled` and the
    /// cancel-after-store wipe (`Session(SignedOut)`).
    pub async fn finish_passkey_login(
        &self,
        assertion_json: Vec<u8>,
        prf_output: Vec<u8>,
        stay_logged_in: bool,
        cancellation: Option<Arc<CoreCancellation>>,
    ) -> std::result::Result<LoginRecord, CoreError> {
        let prf_output = Zeroizing::new(prf_output);
        let (shared, token) = (self.shared.clone(), self.foreground(cancellation));
        self.run(async move {
            let continuation = shared.passkey.lock().await.take().ok_or(NO_PASSKEY)?;
            let method = LoginMethod::Passkey {
                continuation,
                assertion_json,
                prf_output,
            };
            shared.login(method, stay_logged_in, token).await
        })
        .await
    }

    /// Forget a begun passkey login or device verification (none: no-op). The
    /// server challenge simply lapses; nothing was signed in yet.
    pub async fn cancel_passkey_login(&self) {
        self.shared.passkey.lock().await.take();
    }

    /// Begin answering a pending passkey device verification
    /// (`pendingVerification` is `Device(method: Passkey)`): returns the
    /// options for the system ceremony for this account; the core keeps the
    /// continuation.
    ///
    /// # Errors
    /// `Authentication` while signed out or for a refused request; `Invalid`
    /// without a pending passkey verification; `Offline`, `Protocol`;
    /// `Cancelled` when `cancellation` fired (nothing kept).
    pub async fn begin_passkey_device_verification(
        &self,
        cancellation: Option<Arc<CoreCancellation>>,
    ) -> std::result::Result<PasskeyChallengeRecord, CoreError> {
        let (shared, token) = (self.shared.clone(), self.foreground(cancellation));
        self.run(async move { shared.begin_passkey_device_verification(token).await })
            .await
    }

    /// Answer the pending passkey device verification with the ceremony's
    /// assertion (same `assertionJson` shape as `finishPasskeyLogin`; no PRF
    /// output is needed), then admit the session again (`Session(Admitted)`),
    /// as `verifyDevice2fa`. The continuation is used up: begin again to retry.
    ///
    /// # Errors
    /// `Invalid` without a begun device verification, for an unreadable
    /// assertion or one of another request, or `PASSKEY_WRONG_ACCOUNT` for
    /// another account's passkey; `Authentication` while signed out or when
    /// the server refused it (the verification stays pending); then as
    /// `verifyDevice2fa` (`Expired`, `VerificationRequired`, `Offline`,
    /// `Protocol`, `Cancelled`).
    pub async fn finish_passkey_device_verification(
        &self,
        assertion_json: Vec<u8>,
        cancellation: Option<Arc<CoreCancellation>>,
    ) -> std::result::Result<(), CoreError> {
        let (shared, token) = (self.shared.clone(), self.foreground(cancellation));
        self.run(async move {
            shared
                .finish_passkey_device_verification(assertion_json, token)
                .await
        })
        .await
    }
}
