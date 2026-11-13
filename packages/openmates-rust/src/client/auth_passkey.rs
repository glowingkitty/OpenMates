//! Native passkey sign-in and passkey device verification on `Client` (shared
//! core, used by the Apple binding). The shell only runs the platform WebAuthn
//! ceremony: the core asks the server for the request options
//! (`/v1/auth/passkey/assertion/initiate`), keeps the continuation, then
//! checks and posts the assertion, derives the passkey wrapping key and lookup
//! hash from the PRF output, unwraps the master key and signs in with
//! `login_method: passkey` (mirrors web `Login.svelte`
//! `processPasskeyAssertion` and `VerifyDevicePasskey.svelte`, and the Swift
//! `PasskeyLoginView.login` it replaces). Spec: `specifications/features/auth`.
use super::*;
use base64::engine::general_purpose::URL_SAFE_NO_PAD;
use sha2::{Digest, Sha256};

/// `Error::Invalid` reason when the ceremony returned no usable PRF output
/// (the passkey or the platform does not support the PRF extension, or the
/// output is outside the 16..=64 bytes the web accepts). Same words as the
/// Swift `PasskeyError.missingPRF` it replaces; nothing was sent.
pub const PASSKEY_PRF_UNAVAILABLE: &str =
    "This passkey does not support OpenMates encryption. Please use another login method.";
/// `Error::Invalid` reason when the chosen passkey belongs to another account
/// than the one the sign-in or device verification is for. Byte-identical to
/// the server's `PASSKEY_WRONG_ACCOUNT_MESSAGE`, which the core recognises.
pub const PASSKEY_WRONG_ACCOUNT: &str = "This passkey belongs to a different OpenMates account. Choose the passkey for this account and try again.";
/// `Error::Invalid` reason for an assertion that does not answer this
/// continuation (another challenge, another session or the other purpose).
pub const PASSKEY_OTHER_REQUEST: &str =
    "This passkey answer belongs to another passkey request. Start again.";
/// `Error::Invalid` reason for an assertion the core cannot read.
const MALFORMED_ASSERTION: &str = "The passkey answer is incomplete. Please try again.";

/// Longest encoded assertion field the core forwards (authenticator data,
/// client data and signatures are far smaller).
const MAX_FIELD: usize = 16 * 1024;
/// Longest assertion document the core parses.
const MAX_ASSERTION: usize = 64 * 1024;

/// What a passkey continuation is for.
#[derive(Clone, Copy, PartialEq, Eq)]
enum Purpose {
    Login,
    Device,
}

/// The request options of one passkey ceremony plus the core's continuation.
pub struct PasskeyChallenge {
    /// The server's `/v1/auth/passkey/assertion/initiate` reply exactly as
    /// sent (UTF-8 JSON: `challenge`, `rp`, `timeout`, `allowCredentials`,
    /// `userVerification`, `extensions.prf.eval.first`). Holds no secret.
    pub options_json: Vec<u8>,
    /// Hand back to the matching finish call; the shell never sees it.
    pub continuation: PasskeyContinuation,
}

/// Core state between a passkey begin and its finish: the challenge the
/// assertion must answer, the login session id the server binds its proof
/// to, the account it is for and the API origin. Opaque and single use
/// (finish consumes it); it holds no secret.
pub struct PasskeyContinuation {
    purpose: Purpose,
    api: String,
    challenge: String,
    session_id: String,
    hashed_email: Option<String>,
}

/// One WebAuthn assertion as the shell's ceremony returned it. Wire format of
/// `assertion_json` (snake_case, unknown fields refused): `credential_id`
/// base64url without padding (the raw credential id), `client_data_json`,
/// `authenticator_data`, `signature` and optional `user_handle` standard
/// base64 of the raw bytes.
#[derive(serde::Deserialize)]
#[serde(deny_unknown_fields)]
struct Assertion {
    credential_id: String,
    client_data_json: String,
    authenticator_data: String,
    signature: String,
    #[serde(default)]
    user_handle: Option<String>,
}

#[derive(serde::Deserialize)]
struct ClientData {
    #[serde(rename = "type")]
    kind: String,
    challenge: String,
}

impl Assertion {
    /// Parse and bound `json`, and check its client data answers `challenge`
    /// with a `webauthn.get` ceremony. Nothing is sent before this passes.
    fn parse(json: &[u8], challenge: &str) -> Result<Self> {
        if json.len() > MAX_ASSERTION {
            return Err(Error::Invalid(MALFORMED_ASSERTION));
        }
        let assertion: Self =
            serde_json::from_slice(json).map_err(|_| Error::Invalid(MALFORMED_ASSERTION))?;
        let fields = [
            &assertion.credential_id,
            &assertion.client_data_json,
            &assertion.authenticator_data,
            &assertion.signature,
        ];
        if fields
            .iter()
            .any(|field| field.is_empty() || field.len() > MAX_FIELD)
            || assertion
                .user_handle
                .as_ref()
                .is_some_and(|handle| handle.len() > MAX_FIELD)
            || URL_SAFE_NO_PAD.decode(&assertion.credential_id).is_err()
        {
            return Err(Error::Invalid(MALFORMED_ASSERTION));
        }
        let raw = STANDARD
            .decode(&assertion.client_data_json)
            .map_err(|_| Error::Invalid(MALFORMED_ASSERTION))?;
        let data: ClientData =
            serde_json::from_slice(&raw).map_err(|_| Error::Invalid(MALFORMED_ASSERTION))?;
        if data.kind != "webauthn.get" || data.challenge != challenge {
            return Err(Error::Invalid(PASSKEY_OTHER_REQUEST));
        }
        Ok(assertion)
    }

    /// The assertion fields of the server's verify request (both the login
    /// verify and the device verify read this shape).
    fn verify_body(&self, session_id: &str) -> Value {
        json!({
            "credential_id": self.credential_id,
            "assertion_response": {
                "authenticatorData": self.authenticator_data,
                "clientDataJSON": self.client_data_json,
                "signature": self.signature,
                "userHandle": self.user_handle,
            },
            "client_data_json": self.client_data_json,
            "authenticator_data": self.authenticator_data,
            "session_id": session_id,
        })
    }
}

/// The PRF output after the web's bounds check (`getPRFSignatureFromCredential`
/// accepts 16..=64 bytes), copied into a zeroizing buffer.
fn checked_prf(prf_output: &[u8]) -> Result<zeroize::Zeroizing<Vec<u8>>> {
    if !(16..=64).contains(&prf_output.len()) {
        return Err(Error::Invalid(PASSKEY_PRF_UNAVAILABLE));
    }
    Ok(zeroize::Zeroizing::new(prf_output.to_vec()))
}

/// Passkey lookup hash: base64(SHA-256(PRF output || user_email_salt)), web
/// `cryptoService.hashKeyFromPRF` and Swift `hashKeyFromPRF` byte for byte.
/// The concatenation is zeroized; the hash is the server-side credential id.
fn passkey_lookup_hash(prf_output: &[u8], email_salt: &[u8]) -> zeroize::Zeroizing<String> {
    let mut input =
        zeroize::Zeroizing::new(Vec::with_capacity(prf_output.len() + email_salt.len()));
    input.extend_from_slice(prf_output);
    input.extend_from_slice(email_salt);
    zeroize::Zeroizing::new(STANDARD.encode(Sha256::digest(input.as_slice())))
}

/// Classify an unsuccessful verify reply: the server's wrong-account refusal
/// is typed, every other refusal is a failed sign-in.
fn refused(reply: &Value) -> Error {
    if text(reply, "message") == PASSKEY_WRONG_ACCOUNT {
        Error::Invalid(PASSKEY_WRONG_ACCOUNT)
    } else {
        Error::Authentication
    }
}

/// The normalized email of an optional sign-in hint, as `login_lookup` does.
fn hinted_hash(email: Option<&str>) -> Result<Option<String>> {
    let Some(email) = email else { return Ok(None) };
    let email = email.trim().to_lowercase();
    if email.len() > 512 || !email.contains('@') {
        return Err(Error::Authentication);
    }
    Ok(Some(crypto::hash_email(&email)))
}

impl Client {
    async fn passkey_initiate(
        &mut self,
        purpose: Purpose,
        session_id: String,
        hashed_email: Option<String>,
    ) -> Result<PasskeyChallenge> {
        let body = match &hashed_email {
            Some(hash) => json!({"hashed_email": hash}),
            None => json!({}),
        };
        let reply = self
            .request(
                Method::POST,
                "/v1/auth/passkey/assertion/initiate",
                Some(body),
            )
            .await?;
        if reply.get("success") != Some(&Value::Bool(true)) {
            return Err(Error::Authentication);
        }
        let challenge = required(&reply, "challenge")?.to_owned();
        if challenge.len() > 512 || URL_SAFE_NO_PAD.decode(&challenge).is_err() {
            return Err(Error::Protocol);
        }
        required(&reply["rp"], "id")?;
        Ok(PasskeyChallenge {
            options_json: serde_json::to_vec(&reply)?,
            continuation: PasskeyContinuation {
                purpose,
                api: self.base.to_string(),
                challenge,
                session_id,
                hashed_email,
            },
        })
    }

    /// Begin a passkey sign-in: fetch the WebAuthn request options for the
    /// shell's ceremony. Without `email` the request is for a discoverable
    /// credential (any account on this device, as web and Apple do today);
    /// with it the server limits `allowCredentials` to that account and
    /// [`Self::passkey_login_finish`] refuses another account's passkey. A
    /// fresh login session id is bound to the continuation.
    ///
    /// # Errors
    /// `Authentication` for a malformed email or a refused initiation;
    /// `Protocol` for options without a challenge or relying party;
    /// transport errors unchanged.
    pub async fn passkey_login_begin(&mut self, email: Option<&str>) -> Result<PasskeyChallenge> {
        let hashed_email = hinted_hash(email)?;
        let session_id = uuid::Uuid::new_v4().to_string();
        self.passkey_initiate(Purpose::Login, session_id, hashed_email)
            .await
    }

    /// Finish a passkey sign-in with the ceremony's assertion and PRF output.
    /// Posts the verification, derives the wrapping key
    /// (HKDF-SHA256, `crypto::web_formats::passkey_wrapping_key`) and the
    /// lookup hash from `prf_output` and the account email salt, unwraps the
    /// master key, decrypts the account email with it, signs in with
    /// `login_method: passkey` and installs the session like the password and
    /// recovery-key logins. The previous credentials are restored after any
    /// failure. `prf_output` is copied into a zeroizing buffer, never sent and
    /// never logged; the derived keys are zeroized on drop.
    ///
    /// # Errors
    /// `Invalid(PASSKEY_PRF_UNAVAILABLE)` without a usable PRF output,
    /// `Invalid(PASSKEY_OTHER_REQUEST)` for an assertion of another request or
    /// a device-verification continuation, an unreadable assertion is
    /// `Invalid` too (nothing sent for these); `Invalid(PASSKEY_WRONG_ACCOUNT)`
    /// for a passkey of another account than the begin email;
    /// `Authentication` when the server refused the assertion or the login;
    /// `Crypto` when the wrapper does not open with the PRF-derived key;
    /// `Protocol` for a reply without the wrapper, email, refresh cookie or a
    /// matching account (the new server session is then logged out);
    /// transport errors unchanged.
    pub async fn passkey_login_finish(
        &mut self,
        continuation: PasskeyContinuation,
        assertion_json: &[u8],
        prf_output: &[u8],
        options: PasswordLoginOptions,
    ) -> Result<()> {
        if continuation.purpose != Purpose::Login || continuation.api != self.base.as_str() {
            return Err(Error::Invalid(PASSKEY_OTHER_REQUEST));
        }
        let prf = checked_prf(prf_output)?;
        let assertion = Assertion::parse(assertion_json, &continuation.challenge)?;
        let backup = self.begin_signin();
        let result = self
            .passkey_login_inner(continuation, assertion, &prf, options)
            .await;
        self.finish_signin(backup, result.is_ok())?;
        result
    }

    async fn passkey_login_inner(
        &mut self,
        continuation: PasskeyContinuation,
        assertion: Assertion,
        prf: &[u8],
        options: PasswordLoginOptions,
    ) -> Result<()> {
        let PasskeyContinuation {
            session_id,
            hashed_email: hint,
            ..
        } = continuation;
        let mut body = assertion.verify_body(&session_id);
        body["stay_logged_in"] = json!(options.stay_logged_in);
        if let Some(hash) = &hint {
            body["hashed_email"] = json!(hash);
        }
        let verified = self
            .request(
                Method::POST,
                "/v1/auth/passkey/assertion/verify",
                Some(body),
            )
            .await?;
        if verified.get("success") != Some(&Value::Bool(true)) {
            return Err(refused(&verified));
        }
        let user_email_salt = required(&verified, "user_email_salt")?.to_owned();
        let salt = STANDARD
            .decode(&user_email_salt)
            .map_err(|_| Error::Protocol)?;
        if salt.len() < 16 || salt.len() > 128 {
            return Err(Error::Protocol);
        }
        // No server session exists yet (the verify reply carries none without
        // a lookup hash), so a local unlock failure needs no remote logout.
        let master = crypto::web_formats::unwrap_passkey_master_key(
            prf,
            &salt,
            required(&verified, "encrypted_master_key")?,
            required(&verified, "key_iv")?,
        )?;
        let email = match text(&verified, "user_email") {
            "" => {
                let raw = crypto::decrypt_bytes(required(&verified, "encrypted_email")?, &master)?;
                zeroize::Zeroizing::new(
                    std::str::from_utf8(&raw)
                        .map_err(|_| Error::Protocol)?
                        .to_owned(),
                )
            }
            email => zeroize::Zeroizing::new(email.to_owned()),
        };
        if email.is_empty() || email.len() > 512 || !email.contains('@') {
            return Err(Error::Protocol);
        }
        let hashed_email = crypto::hash_email(&email);
        if hint.as_ref().is_some_and(|hash| *hash != hashed_email) {
            return Err(Error::Invalid(PASSKEY_WRONG_ACCOUNT));
        }
        // The server names the account it verified; it must be this email's.
        let named = text(&verified, "hashed_email");
        if !named.is_empty() && named != hashed_email {
            return Err(Error::Protocol);
        }
        let email_key = crypto::derive_email_key(&email, &user_email_salt)?;
        let lookup_hash = passkey_lookup_hash(prf, &salt);
        let login = self
            .request_plaintext(
                Method::POST,
                "/v1/auth/login",
                json!({"hashed_email": hashed_email, "lookup_hash": lookup_hash.as_str(),
                    "login_method": "passkey", "credential_id": assertion.credential_id,
                    "email_encryption_key": email_key, "stay_logged_in": options.stay_logged_in,
                    "session_id": session_id}),
            )
            .await?;
        drop(lookup_hash);
        if login.get("success") != Some(&Value::Bool(true))
            || login.get("tfa_required") == Some(&Value::Bool(true))
        {
            return Err(Error::Authentication);
        }
        let owner = login.get("user").ok_or(Error::Protocol).and_then(|user| {
            self.check_login_owner(user, &user_email_salt)?;
            // The login must name the account the passkey verified.
            if text(user, "id") != text(&verified, "user_id") {
                return Err(Error::Protocol);
            }
            Ok(())
        });
        if let Err(error) = owner {
            self.revoke_unlocked_login().await;
            return Err(error);
        }
        let lookup = LoginLookup {
            email: email.to_string(),
            hashed_email,
            user_email_salt,
            salt,
            email_key,
        };
        self.admit_login(&login, lookup, session_id, master)
    }

    /// Begin a pending passkey device verification (session check answered
    /// `re_auth_required: passkey`): fetch the request options for the
    /// signed-in account (`hashed_email` of the session, so the server lists
    /// its credentials). The session stays as it is.
    ///
    /// # Errors
    /// `Invalid` without a pending passkey device verification;
    /// `Authentication` without a session or for a refused initiation;
    /// `Protocol`, transport errors unchanged.
    pub async fn passkey_device_verification_begin(&mut self) -> Result<PasskeyChallenge> {
        self.require_passkey_verification()?;
        let session = self.session.as_ref().ok_or(Error::Authentication)?;
        let (session_id, hashed_email) = (session.session_id.clone(), session.hashed_email.clone());
        self.passkey_initiate(Purpose::Device, session_id, Some(hashed_email))
            .await
    }

    /// Answer a pending passkey device verification with the ceremony's
    /// assertion (`POST /v1/auth/passkey/verify/device`; no PRF output is
    /// needed). On success the pending verification is cleared; the caller
    /// validates the session again to admit it (as
    /// [`Self::verify_device_2fa`]).
    ///
    /// # Errors
    /// `Invalid` without a pending passkey verification, for an unreadable
    /// assertion or `Invalid(PASSKEY_OTHER_REQUEST)` for another request or
    /// session (nothing sent); `Invalid(PASSKEY_WRONG_ACCOUNT)` for another
    /// account's passkey and `Authentication` for any other refusal (the
    /// verification stays pending); `Offline`, `Protocol`.
    pub async fn passkey_device_verification_finish(
        &mut self,
        continuation: PasskeyContinuation,
        assertion_json: &[u8],
    ) -> Result<()> {
        self.require_passkey_verification()?;
        let session = self.session.as_ref().ok_or(Error::Authentication)?;
        if continuation.purpose != Purpose::Device
            || continuation.api != self.base.as_str()
            || continuation.session_id != session.session_id
        {
            return Err(Error::Invalid(PASSKEY_OTHER_REQUEST));
        }
        let assertion = Assertion::parse(assertion_json, &continuation.challenge)?;
        let reply = self
            .request(
                Method::POST,
                "/v1/auth/passkey/verify/device",
                Some(assertion.verify_body(&continuation.session_id)),
            )
            .await?;
        if reply.get("success") != Some(&Value::Bool(true)) {
            return Err(refused(&reply));
        }
        self.session_verification = None;
        // The next validation must reach the server: its answer admits.
        self.recent_validation = None;
        Ok(())
    }

    fn require_passkey_verification(&self) -> Result<()> {
        if matches!(
            self.session_verification,
            Some(SessionVerification::Device {
                method: DeviceVerificationMethod::Passkey,
                ..
            })
        ) {
            return Ok(());
        }
        Err(Error::Invalid("No passkey device verification is pending."))
    }
}

#[cfg(all(test, not(target_arch = "wasm32")))]
#[path = "auth_passkey_tests.rs"]
mod tests;
