//! Session adoption on `ViewModelCore`: a sign-in the core does not perform
//! yet (passkey, recovery key, backup code, device 2FA verification) finishes
//! in Swift, which then hands the resulting session to the core once. The
//! core validates the fields strictly, builds its `Session` and runs the same
//! hand-over as its own login (`AcknowledgedCredentials::begin_client_session`:
//! fence epoch, Keychain store with acknowledgement; a cancel after the store
//! wipes it), then `start`. From then on the core alone owns the session;
//! Swift deletes its own cookies and stops calling `/v1/auth/session`.
//! Temporary: removed when the core performs those logins (plan
//! `apple-client-core-migration` step A3, auth session). Spec `client-core`.
use crate::CoreError;
use crate::core::CoreCancellation;
use crate::view_core::{Shared, ViewModelCore};
use openmates_sdk::{
    Client,
    error::{Error, Result},
    session::Session,
    view_model::{SessionEvent, ViewEvent, ViewSink},
};
use std::collections::BTreeMap;
use std::sync::Arc;
use tokio_util::sync::CancellationToken;
use zeroize::Zeroizing;

/// Name of the cookie that authenticates the session.
const REFRESH_COOKIE: &str = "auth_refresh_token";
const MAX_COOKIES: usize = 8;
const MAX_TOKEN: usize = 4096;
const MAX_HASH: usize = 128;

/// One cookie of the Swift-held session (name and value, no attributes).
#[derive(uniffi::Record)]
pub struct SessionCookieRecord {
    /// Cookie name (letters, digits, `_`, `-`).
    pub name: String,
    /// Cookie value (secret).
    pub value: String,
}

/// The fields a Swift-completed login holds. All of them are secret or
/// account-identifying; the core zeroizes them after use.
#[derive(uniffi::Record)]
pub struct AdoptedSessionRecord {
    /// Session id the login was performed with (8 to 128 of letters,
    /// digits, `_`, `-`).
    pub session_id: String,
    /// The API host's session cookies; must contain `auth_refresh_token`.
    /// At most 8.
    pub cookies: Vec<SessionCookieRecord>,
    /// The login response's `ws_token`, if any.
    pub ws_token: Option<String>,
    /// The unwrapped 32-byte master key.
    pub master_key: Vec<u8>,
    /// The account's email hash (base64, as the core computes it).
    pub hashed_email: String,
    /// The account's email salt (base64; empty when unknown).
    pub user_email_salt: String,
    /// The derived email encryption key (base64), if known.
    pub email_encryption_key: Option<String>,
    /// Pair session deadline in unix milliseconds, for paired sessions.
    pub paired_session_expires_at: Option<u64>,
}

fn base64ish(text: &str, max: usize) -> bool {
    text.len() <= max
        && text
            .bytes()
            .all(|byte| byte.is_ascii_alphanumeric() || b"+/=_-".contains(&byte))
}

fn now_ms() -> Result<u64> {
    let elapsed = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .map_err(|_| Error::Protocol)?;
    u64::try_from(elapsed.as_millis()).map_err(|_| Error::Protocol)
}

/// Validate `record` and build the core session for `api_url`. The record's
/// secrets end up in the `Session` (zeroized on drop) or are zeroized here.
///
/// # Errors
/// `Invalid` for any malformed field; `Expired` for a lapsed deadline.
fn adopted_session(api_url: &str, record: AdoptedSessionRecord) -> Result<Session> {
    let AdoptedSessionRecord {
        session_id,
        cookies,
        ws_token,
        master_key,
        hashed_email,
        user_email_salt,
        email_encryption_key,
        paired_session_expires_at,
    } = record;
    // Wrapped first, so every early return below zeroizes them. The jar is
    // built only after every check passed.
    let master_key = Zeroizing::new(master_key);
    let session_id = Zeroizing::new(session_id);
    let (hashed_email, user_email_salt) = (
        Zeroizing::new(hashed_email),
        Zeroizing::new(user_email_salt),
    );
    let cookies: Vec<(Zeroizing<String>, Zeroizing<String>)> = cookies
        .into_iter()
        .map(|c| (Zeroizing::new(c.name), Zeroizing::new(c.value)))
        .collect();
    let (ws_token, email_encryption_key) = (
        ws_token.map(Zeroizing::new),
        email_encryption_key.map(Zeroizing::new),
    );
    let id_ok = (8..=128).contains(&session_id.len())
        && session_id
            .bytes()
            .all(|byte| byte.is_ascii_alphanumeric() || b"_-".contains(&byte));
    if !id_ok {
        return Err(Error::Invalid("Invalid session id."));
    }
    if cookies.is_empty() || cookies.len() > MAX_COOKIES {
        return Err(Error::Invalid("Supply the session cookies."));
    }
    let cookie_ok = |(name, value): &(Zeroizing<String>, Zeroizing<String>)| {
        (1..=64).contains(&name.len())
            && name
                .bytes()
                .all(|byte| byte.is_ascii_alphanumeric() || b"_-".contains(&byte))
            && (1..=MAX_TOKEN).contains(&value.len())
            && value
                .bytes()
                .all(|byte| byte > 32 && byte < 127 && byte != b';' && byte != b',')
    };
    if !cookies.iter().all(cookie_ok) {
        return Err(Error::Invalid("Invalid session cookie."));
    }
    let names: std::collections::BTreeSet<&str> =
        cookies.iter().map(|(name, _)| name.as_str()).collect();
    if names.len() != cookies.len() {
        return Err(Error::Invalid("Duplicate session cookie."));
    }
    if !names.contains(REFRESH_COOKIE) {
        return Err(Error::Invalid(
            "The session cookie auth_refresh_token is missing.",
        ));
    }
    let token_ok = ws_token.as_ref().is_none_or(|token| {
        (1..=MAX_TOKEN).contains(&token.len()) && token.bytes().all(|b| b.is_ascii_graphic())
    });
    let key_ok = email_encryption_key
        .as_ref()
        .is_none_or(|key| !key.is_empty() && base64ish(key, MAX_HASH));
    let shape_ok = token_ok
        && key_ok
        && master_key.len() == 32
        && !hashed_email.is_empty()
        && base64ish(&hashed_email, MAX_HASH)
        && base64ish(&user_email_salt, MAX_HASH);
    if !shape_ok {
        return Err(Error::Invalid("Invalid session fields."));
    }
    let now = now_ms()?;
    if paired_session_expires_at.is_some_and(|deadline| deadline <= now) {
        return Err(Error::Expired);
    }
    let mut key = Zeroizing::new([0u8; 32]);
    key.copy_from_slice(&master_key);
    // `Session` zeroizes these copies on drop; the wrapped originals are
    // zeroized when this function returns.
    let jar: BTreeMap<String, String> = cookies
        .iter()
        .map(|(name, value)| (name.to_string(), value.to_string()))
        .collect();
    Ok(Session {
        api_url: api_url.to_owned(),
        session_id: session_id.to_string(),
        cookies: jar,
        ws_token: ws_token.as_ref().map(|token| token.to_string()),
        master_key: key,
        hashed_email: hashed_email.to_string(),
        user_email_salt: user_email_salt.to_string(),
        email_encryption_key: email_encryption_key.as_ref().map(|key| key.to_string()),
        created_at: now,
        paired_session_expires_at,
        active_team_id: None,
    })
}

impl Shared {
    async fn adopt_session(
        &self,
        record: AdoptedSessionRecord,
        cancel: CancellationToken,
    ) -> Result<()> {
        // The actor lock is held throughout, as for the core login.
        let mut host = self.host.lock().await;
        if host.is_some() {
            return Err(Error::Invalid(
                "Sign out before signing in to another account.",
            ));
        }
        let session = adopted_session(&self.api_url, record)?;
        let mut client = Client::with_options(&self.api_url, Some(session), self.options())?;
        let begun = if cancel.is_cancelled() {
            Err(Error::Cancelled)
        } else {
            self.credentials
                .begin_client_session(&mut client, &cancel)
                .await
        };
        if let Err(error) = begun {
            // As the core login: the server session nobody stored is revoked
            // remotely (best effort); Swift signs in again.
            let _remote = client.logout().await;
            return Err(error);
        }
        if cancel.is_cancelled() {
            // Cancelled after the Keychain store: wipe it and revoke remotely.
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
}

#[uniffi::export]
impl ViewModelCore {
    /// TEMPORARY (removed with plan step A3, auth session). Hand a session that Swift
    /// signed in (passkey, recovery key, backup code, device verification)
    /// to the core: validated, stored through the Keychain with
    /// `acknowledgeCredentials`, then `start` (`Session(Admitted)` after the
    /// server admitted it). Afterwards Swift deletes its own copies of the
    /// cookies and master key and uses `httpRequest` and the legacy grants.
    ///
    /// # Errors
    /// `Invalid` while signed in or for a malformed field (nothing is sent or
    /// stored); `Expired` for a lapsed pair deadline; then as the core login
    /// hand-over (`Locked` for an unacknowledged store, the server session is
    /// then logged out) and as `start` (`Expired`/`Authentication` when the
    /// server rejects it, the profile is then wiped). `Cancelled` when
    /// `cancellation` fired; after the store this wipes it, logs the server
    /// session out and emits `Session(SignedOut)`.
    pub async fn adopt_session(
        &self,
        session: AdoptedSessionRecord,
        cancellation: Option<Arc<CoreCancellation>>,
    ) -> std::result::Result<(), CoreError> {
        let (shared, token) = (self.shared.clone(), self.foreground(cancellation));
        self.run(async move { shared.adopt_session(session, token).await })
            .await
    }
}
