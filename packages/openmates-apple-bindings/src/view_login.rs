//! Core-performed sign-in on `ViewModelCore`: the password login
//! (`Client::login_password_with_options`) and the pair login of this device
//! as receiver (`Client::begin_pair`, `poll_pair`, `submit_pair_pin`, then
//! `AcknowledgedCredentials::finish_pair_session`). Each success ends in the
//! core hand-over (`begin_client_session`: new fence epoch, Keychain store
//! with acknowledgement) and the normal `start`. Outcomes are the core's own:
//! `Ok`, or a `CoreError` mapped 1:1 from `openmates_sdk::Error` (for example
//! `TwoFactorRequired`, `Authentication`). Secrets arrive only as call
//! arguments, are zeroized after the core call and never logged or stored
//! here. Plan `apple-client-core-migration` (A2 Apple login hand-over).
use crate::CoreError;
use crate::core::CoreCancellation;
use crate::view_core::{AppleHost, Shared, ViewModelCore};
use openmates_sdk::{
    Client,
    client::PasswordLoginOptions,
    error::{Error, Result},
    view_model::{SessionEvent, ViewEvent, ViewSink},
};
use std::sync::Arc;
use tokio_util::sync::CancellationToken;
use zeroize::Zeroizing;

/// What a signed-out core refuses to replace.
const SIGNED_IN: Error = Error::Invalid("Sign out before signing in to another account.");
/// Pair steps without a running pair login.
const NO_PAIRING: Error = Error::Invalid("Begin a pair login first.");

/// The pair login code to show (core `PairChallenge`).
#[derive(Clone, Debug, PartialEq, Eq, uniffi::Record)]
pub struct PairChallengeRecord {
    /// Code the authorizing device enters (upper-case letters and digits).
    pub token: String,
    /// Web app link that opens the authorization of `token` (QR code).
    pub login_url: String,
    /// Expiry in unix seconds.
    pub expires_at: u64,
}

/// The client of a running pair login.
pub(crate) struct PendingPair {
    client: Client,
    /// The core prepared the paired session (its `finish_pair` succeeded),
    /// so its credentials may already be in the Keychain (terminal app:
    /// `pair_phase == 4`).
    prepared: bool,
}

impl Shared {
    fn refuse_signed_in(host: &Option<AppleHost>) -> Result<()> {
        if host.is_some() {
            return Err(SIGNED_IN);
        }
        Ok(())
    }

    async fn login_password(
        &self,
        email: String,
        password: Zeroizing<String>,
        tfa_code: Option<Zeroizing<String>>,
        stay_logged_in: bool,
        cancel: CancellationToken,
    ) -> Result<()> {
        // The actor lock is held throughout, so no command interleaves with
        // the login and its hand-over (terminal app: same refusal).
        let mut host = self.host.lock().await;
        Self::refuse_signed_in(&host)?;
        let mut client = Client::with_options(&self.api_url, None, self.options())?;
        let options = PasswordLoginOptions { stay_logged_in };
        let login = client
            .login_password_with_options(
                &email,
                &password,
                tfa_code.as_ref().map(|code| code.as_str()),
                options,
            )
            .await;
        drop((password, tfa_code));
        login?;
        let begun = if cancel.is_cancelled() {
            Err(Error::Cancelled)
        } else {
            self.credentials
                .begin_client_session(&mut client, &cancel)
                .await
        };
        if let Err(error) = begun {
            // As the terminal app: the server session nobody stored is
            // revoked remotely; that best-effort result never hides `error`.
            let _remote = client.logout().await;
            return Err(error);
        }
        if cancel.is_cancelled() {
            // Cancelled after the Keychain store: as the terminal app, wipe
            // the stored session and log the new server session out, so
            // nothing of the abandoned login stays behind.
            self.ops.advance();
            let wiped = self.credentials.abandon_client_session(&mut client).await;
            self.sink
                .emit(ViewEvent::Session(SessionEvent::SignedOut))
                .await?;
            wiped?;
            return Err(Error::Cancelled);
        }
        drop(client);
        self.start_locked(&mut host, cancel).await
    }

    async fn begin_pair(&self) -> Result<PairChallengeRecord> {
        let host = self.host.lock().await;
        Self::refuse_signed_in(&host)?;
        let mut pairing = self.pairing.lock().await;
        if let Some(mut previous) = pairing.take() {
            // A new code replaces the old one; the core deletes it remotely.
            previous.client.cancel_pair().await?;
        }
        let mut client = Client::with_options(&self.api_url, None, self.options())?;
        let challenge = client.begin_pair().await?;
        *pairing = Some(PendingPair {
            client,
            prepared: false,
        });
        Ok(PairChallengeRecord {
            token: challenge.token,
            login_url: challenge.login_url,
            expires_at: challenge.expires_at,
        })
    }

    async fn poll_pair(&self) -> Result<String> {
        let mut pairing = self.pairing.lock().await;
        pairing.as_mut().ok_or(NO_PAIRING)?.client.poll_pair().await
    }

    async fn submit_pair_pin(&self, pin: Zeroizing<String>) -> Result<()> {
        let mut pairing = self.pairing.lock().await;
        let pending = pairing.as_mut().ok_or(NO_PAIRING)?;
        pending.client.submit_pair_pin(&pin).await
    }

    async fn finish_pair(&self, cancel: CancellationToken) -> Result<bool> {
        let mut host = self.host.lock().await;
        Self::refuse_signed_in(&host)?;
        let mut pairing = self.pairing.lock().await;
        let pending = pairing.as_mut().ok_or(NO_PAIRING)?;
        let finished = self
            .credentials
            .finish_pair_session(&mut pending.client, &cancel)
            .await;
        // The fresh pair client holds a session only once the core prepared
        // the paired session; a later store or relay step may have failed.
        pending.prepared |= pending.client.session().is_some();
        if !finished? {
            return Ok(false);
        }
        *pairing = None;
        drop(pairing);
        self.start_locked(&mut host, cancel).await?;
        Ok(true)
    }

    async fn cancel_pair(&self) -> Result<()> {
        let pending = self.pairing.lock().await.take();
        let Some(mut pending) = pending else {
            return Ok(());
        };
        // The core revokes a prepared paired session remotely and deletes
        // the code.
        let remote = pending.client.cancel_pair().await;
        if pending.prepared {
            // Its credentials may already be in the Keychain: sign out
            // locally too, so the next start never restores a revoked session.
            self.logout().await?;
        }
        remote
    }
}

#[uniffi::export]
impl ViewModelCore {
    /// Sign in with email and password in the core, then begin the session on
    /// this profile (Keychain store and `acknowledgeCredentials`) and `start`
    /// from it: `Session(Restored)`, `ChatList(Cached)`, `Session(Admitted)`.
    /// Run `bootSync` afterwards for the network chat list. `password` and
    /// `tfaCode` are zeroized after the core call; the binding never stores
    /// or logs them. `stayLoggedIn` is the server cookie lifetime only.
    ///
    /// # Errors
    /// The core's login outcome: `TwoFactorRequired` (call again with
    /// `tfaCode`), `Authentication` (wrong email, password or code),
    /// `Offline`, `Protocol`; `Invalid` while signed in; then as the
    /// hand-over (`Invalid` while another session is stored, `Locked` for an
    /// unacknowledged Keychain store; the new server session is then logged
    /// out) and as `start`. `Cancelled` when `cancellation` fired; a cancel
    /// after the Keychain store wipes the stored session, logs the new server
    /// session out and emits `Session(SignedOut)`.
    pub async fn login_password(
        &self,
        email: String,
        password: String,
        tfa_code: Option<String>,
        stay_logged_in: bool,
        cancellation: Option<Arc<CoreCancellation>>,
    ) -> std::result::Result<(), CoreError> {
        let (password, tfa_code) = (Zeroizing::new(password), tfa_code.map(Zeroizing::new));
        let (shared, token) = (self.shared.clone(), self.foreground(cancellation));
        self.run(async move {
            shared
                .login_password(email, password, tfa_code, stay_logged_in, token)
                .await
        })
        .await
    }

    /// Begin a pair login of this device: returns the code (and link) the
    /// authorizing device enters. Replaces a running pair login.
    ///
    /// # Errors
    /// `Invalid` while signed in; `Offline`, `Protocol`, `Expired` from the core.
    pub async fn begin_pair_login(&self) -> std::result::Result<PairChallengeRecord, CoreError> {
        let shared = self.shared.clone();
        self.run(async move { shared.begin_pair().await }).await
    }

    /// Poll the running pair login once; returns the relay status as the core
    /// reports it (`"approved"`: ask for the PIN and call `submitPairPin`;
    /// other values: keep polling).
    ///
    /// # Errors
    /// `Invalid` without a running pair login; `Expired` when the code
    /// failed, was cancelled or lapsed; `Offline`, `Protocol`.
    pub async fn poll_pair_login(&self) -> std::result::Result<String, CoreError> {
        let shared = self.shared.clone();
        self.run(async move { shared.poll_pair().await }).await
    }

    /// Send the 6-character PIN shown on the authorizing device (zeroized
    /// after the call). Then call `finishPairLogin` until it returns `true`.
    ///
    /// # Errors
    /// `Invalid` without a running pair login; `Protocol` before approval;
    /// `Crypto` for a malformed PIN; `Authentication` when the relay refused.
    pub async fn submit_pair_pin(&self, pin: String) -> std::result::Result<(), CoreError> {
        let pin = Zeroizing::new(pin);
        let shared = self.shared.clone();
        self.run(async move { shared.submit_pair_pin(pin).await })
            .await
    }

    /// One finish step: `false` while the authorizer has not delivered the
    /// key bundle yet (call again); `true` once the paired session is stored
    /// through the Keychain, the relay acknowledged and `start` ran (same
    /// events as `loginPassword`). After a failed Keychain store or relay
    /// acknowledgement the pairing stays open, so calling again retries.
    ///
    /// # Errors
    /// `Invalid` while signed in or without a running pair login; `Expired`
    /// for a failed or lapsed pairing; `Authentication`/`Crypto` for a wrong
    /// PIN or a bundle of another account; `Locked` for an unacknowledged
    /// store; then as `start`.
    pub async fn finish_pair_login(
        &self,
        cancellation: Option<Arc<CoreCancellation>>,
    ) -> std::result::Result<bool, CoreError> {
        let (shared, token) = (self.shared.clone(), self.foreground(cancellation));
        self.run(async move { shared.finish_pair(token).await })
            .await
    }

    /// Abandon the running pair login (nothing running: no-op). The core
    /// deletes the code remotely; when the paired session was already
    /// prepared (it may be in the Keychain), the profile is signed out
    /// locally as by `logout` (`Session(SignedOut)`).
    ///
    /// # Errors
    /// The local sign-out error, else the core's cancel error.
    pub async fn cancel_pair_login(&self) -> std::result::Result<(), CoreError> {
        let shared = self.shared.clone();
        self.run(async move { shared.cancel_pair().await }).await
    }
}
