//! Core-performed sign-in on `ViewModelCore`: the password login with an OTP
//! or backup code (`Client::login_password_second_factor`, then the v1→v2
//! migration in `view_login_migration`), the recovery-key login
//! (`Client::login_recovery_key`) and the pair login of this device as
//! receiver (`Client::begin_pair`, `poll_pair`, `submit_pair_pin`, then
//! `AcknowledgedCredentials::finish_pair_session`); the passkey login's
//! exports live in `view_login_passkey` and end in the same `Shared::login`. Each success ends in the
//! core hand-over (`begin_client_session`: new fence epoch, Keychain store
//! with acknowledgement) and the normal `start`. Outcomes are the core's own:
//! `Ok`, or a `CoreError` mapped 1:1 from `openmates_sdk::Error` (for example
//! `TwoFactorRequired`, `Authentication`). Secrets arrive only as call
//! arguments, are zeroized after the core call and never logged or stored
//! here. Plan `apple-client-core-migration` (A2 Apple login hand-over).
use crate::CoreError;
use crate::core::CoreCancellation;
use crate::view_core::{AppleHost, Shared, ViewModelCore};
use crate::view_login_migration::{LoginRecord, PasswordMigrationRecord, migrate_after_login};
use openmates_sdk::{
    Client,
    client::{PasskeyContinuation, PasswordLoginOptions},
    error::{Error, Result},
    view_model::{SessionEvent, ViewEvent, ViewSink},
    web_auth::TfaCodeType,
};
use std::sync::Arc;
use tokio_util::sync::CancellationToken;
use zeroize::Zeroizing;

/// The credential of one core-performed sign-in (secrets zeroized on drop).
pub(crate) enum LoginMethod {
    /// Email password, optionally with a second factor of this kind.
    Password {
        email: String,
        password: Zeroizing<String>,
        tfa: Option<(Zeroizing<String>, TfaCodeType)>,
    },
    /// The account recovery key (no second factor).
    RecoveryKey {
        email: String,
        recovery_key: Zeroizing<String>,
    },
    /// A finished passkey ceremony answering the core's `continuation`
    /// (`view_login_passkey.rs`); the PRF output is secret.
    Passkey {
        continuation: PasskeyContinuation,
        assertion_json: Vec<u8>,
        prf_output: Zeroizing<Vec<u8>>,
    },
}

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

    /// One core-performed sign-in, its hand-over and the cancel-after-store
    /// wipe, shared by every login method.
    pub(crate) async fn login(
        &self,
        method: LoginMethod,
        stay_logged_in: bool,
        cancel: CancellationToken,
    ) -> Result<LoginRecord> {
        // The actor lock is held throughout, so no command interleaves with
        // the login and its hand-over (terminal app: same refusal).
        let mut host = self.host.lock().await;
        Self::refuse_signed_in(&host)?;
        let mut client = Client::with_options(&self.api_url, None, self.options())?;
        let options = PasswordLoginOptions { stay_logged_in };
        let (password_migration, remaining_backup_codes) = match method {
            LoginMethod::Password {
                email,
                password,
                tfa,
            } => {
                let tfa_code = tfa.as_ref().map(|(code, kind)| (code.as_str(), *kind));
                let report = client
                    .login_password_second_factor(&email, &password, tfa_code, options)
                    .await;
                drop(tfa);
                let report = report?;
                // Before the hand-over, while the password is still here: the
                // core never stores it, so this is the only moment it can run.
                let migration = migrate_after_login(&client, &report, &password, &cancel).await;
                (migration, report.remaining_backup_codes)
            }
            LoginMethod::RecoveryKey {
                email,
                recovery_key,
            } => {
                let login = client
                    .login_recovery_key(&email, &recovery_key, options)
                    .await;
                drop(recovery_key);
                login?;
                (PasswordMigrationRecord::NotNeeded, None)
            }
            LoginMethod::Passkey {
                continuation,
                assertion_json,
                prf_output,
            } => {
                let login = client
                    .passkey_login_finish(continuation, &assertion_json, &prf_output, options)
                    .await;
                drop(prf_output);
                login?;
                (PasswordMigrationRecord::NotNeeded, None)
            }
        };
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
        self.start_locked(&mut host, cancel).await?;
        Ok(LoginRecord {
            password_migration,
            remaining_backup_codes,
        })
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
        // `begin_client_session` checks the cancel only before its epoch:
        // `Cancelled` (and the `Invalid` refusal of another stored session)
        // means nothing of this pairing was stored; any other outcome of a
        // prepared pairing may have stored it.
        let stored = pending.prepared
            && !matches!(
                finished,
                Ok(false) | Err(Error::Cancelled | Error::Invalid(_))
            );
        if cancel.is_cancelled() && stored {
            // Cancelled after the Keychain store: as password login, wipe
            // the stored session, log the paired server session out and
            // delete the code, so nothing of the abandoned pairing stays.
            let mut abandoned = pairing.take().ok_or(NO_PAIRING)?;
            drop(pairing);
            self.ops.advance();
            let wiped = self
                .credentials
                .abandon_client_session(&mut abandoned.client)
                .await;
            // Best effort: the local wipe is the guarantee.
            let _remote = abandoned.client.cancel_pair().await;
            self.sink
                .emit(ViewEvent::Session(SessionEvent::SignedOut))
                .await?;
            wiped?;
            return Err(Error::Cancelled);
        }
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

impl ViewModelCore {
    async fn login_with(
        &self,
        method: LoginMethod,
        stay_logged_in: bool,
        cancellation: Option<Arc<CoreCancellation>>,
    ) -> std::result::Result<LoginRecord, CoreError> {
        let (shared, token) = (self.shared.clone(), self.foreground(cancellation));
        self.run(async move { shared.login(method, stay_logged_in, token).await })
            .await
    }
}

#[uniffi::export]
impl ViewModelCore {
    /// Sign in with email and password in the core, then begin the session on
    /// this profile (Keychain store and `acknowledgeCredentials`) and `start`
    /// from it: `Session(Restored)`, `ChatList(Cached)`, `Session(Admitted)`.
    /// Run `bootSync` afterwards for the network chat list. After a legacy
    /// (v1) password unlocked the account, the core migrates it to v2 before
    /// the hand-over; the result is `passwordMigration` and never fails the
    /// login. `password` and `tfaCode` are zeroized after the core call; the
    /// binding never stores or logs them. `stayLoggedIn` is the server cookie
    /// lifetime only.
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
    ) -> std::result::Result<LoginRecord, CoreError> {
        let method = LoginMethod::Password {
            email,
            password: Zeroizing::new(password),
            tfa: tfa_code.map(|code| (Zeroizing::new(code), TfaCodeType::Otp)),
        };
        self.login_with(method, stay_logged_in, cancellation).await
    }

    /// `loginPassword` with a backup code as the second factor (the server
    /// consumes it; `remainingBackupCodes` reports what is left). Same
    /// hand-over, migration and cancel behaviour.
    ///
    /// # Errors
    /// As `loginPassword`, except that a refused backup code (or password)
    /// is `Authentication`, never `TwoFactorRequired`.
    pub async fn login_backup_code(
        &self,
        email: String,
        password: String,
        backup_code: String,
        stay_logged_in: bool,
        cancellation: Option<Arc<CoreCancellation>>,
    ) -> std::result::Result<LoginRecord, CoreError> {
        let method = LoginMethod::Password {
            email,
            password: Zeroizing::new(password),
            tfa: Some((Zeroizing::new(backup_code), TfaCodeType::Backup)),
        };
        self.login_with(method, stay_logged_in, cancellation).await
    }

    /// Sign in with email and the account recovery key in the core (no
    /// second factor; the master key is unwrapped from the recovery-key
    /// wrapper). Same hand-over and cancel behaviour as `loginPassword`;
    /// `passwordMigration` is `NotNeeded`. `recoveryKey` is zeroized after
    /// the core call and never stored or logged.
    ///
    /// # Errors
    /// `Authentication` for a wrong key or unknown account (the server does
    /// not tell them apart); `Crypto` when the returned wrapper does not open
    /// (the new server session is logged out); `Invalid` while signed in or
    /// for an oversized key; then as `loginPassword`.
    pub async fn login_recovery_key(
        &self,
        email: String,
        recovery_key: String,
        stay_logged_in: bool,
        cancellation: Option<Arc<CoreCancellation>>,
    ) -> std::result::Result<LoginRecord, CoreError> {
        let method = LoginMethod::RecoveryKey {
            email,
            recovery_key: Zeroizing::new(recovery_key),
        };
        self.login_with(method, stay_logged_in, cancellation).await
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
    /// store; then as `start`. `Cancelled` when `cancellation` fired; a cancel
    /// after the Keychain store wipes the stored session, logs the paired
    /// server session out, ends the pairing and emits `Session(SignedOut)`
    /// (as `loginPassword`).
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
