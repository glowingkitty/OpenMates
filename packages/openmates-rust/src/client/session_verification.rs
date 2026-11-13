//! Server-requested verification of a still-valid session: device
//! verification (`re_auth_required` `2fa` or `passkey`, with its reason) and
//! a plain re-authentication request (`re_auth_reason` without a factor the
//! client can answer). One classifier serves the web restore decision
//! (`web_auth::classify_session`) and the native `Client` validation, so both
//! read the `/v1/auth/session` body the same way. The native client keeps its
//! session and stored credentials for these outcomes (the server did not end
//! the session) and answers a two-factor device check with
//! `/v1/auth/2fa/verify/device`. Spec: `architecture.client-core`
//! (`client-core.shell.allowed-responsibilities`: auth policy in the core).
use super::Client;
use crate::error::{Error, Result};
use reqwest::Method;
use serde_json::{Value, json};

/// Longest one-time code the core forwards (TOTP codes are 6 digits).
const MAX_DEVICE_CODE: usize = 32;

/// The factor the server asks for before it admits a session on this device.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum DeviceVerificationMethod {
    /// A one-time code from the authenticator app (`re_auth_required: "2fa"`).
    TwoFactor,
    /// A passkey assertion (`re_auth_required: "passkey"`); the ceremony is a
    /// platform API, so it stays in the shell.
    Passkey,
}

impl DeviceVerificationMethod {
    /// The server's word for the method (`2fa`, `passkey`).
    pub fn wire(self) -> &'static str {
        match self {
            Self::TwoFactor => "2fa",
            Self::Passkey => "passkey",
        }
    }
}

/// Why an unsuccessful session check is not a lost session. Reasons are the
/// server's fixed vocabulary (`new_device`, `location_change`,
/// `session_verification`); they carry no secret.
#[derive(Clone, Debug, PartialEq, Eq)]
pub enum SessionVerification {
    /// Verify this device with `method` to continue.
    Device {
        /// The factor the server asks for.
        method: DeviceVerificationMethod,
        /// Why (`new_device` when the server named none).
        reason: String,
        /// A passkey check may also be answered with the password.
        password_fallback_available: bool,
    },
    /// The server wants a fresh sign-in; no factor can approve this session.
    ReAuth {
        /// Why, as the server named it.
        reason: String,
    },
}

fn text<'a>(data: &'a Value, key: &str) -> Option<&'a str> {
    data.get(key)
        .and_then(Value::as_str)
        .filter(|value| !value.is_empty())
}

impl SessionVerification {
    /// Classify the body of an unsuccessful `/v1/auth/session` reply. `None`
    /// means a plain rejection (the session is gone). The device branch is
    /// the deployed web rule byte for byte: `2fa`/`passkey`, reason default
    /// `new_device`, password fallback only for passkey and only for a literal
    /// `true`.
    pub fn of_unsuccessful_session(data: &Value) -> Option<Self> {
        let method = match data.get("re_auth_required").and_then(Value::as_str) {
            Some("2fa") => Some(DeviceVerificationMethod::TwoFactor),
            Some("passkey") => Some(DeviceVerificationMethod::Passkey),
            _ => None,
        };
        if let Some(method) = method {
            return Some(Self::Device {
                method,
                reason: text(data, "re_auth_reason")
                    .unwrap_or("new_device")
                    .to_owned(),
                password_fallback_available: method == DeviceVerificationMethod::Passkey
                    && data.get("password_fallback_available") == Some(&Value::Bool(true)),
            });
        }
        text(data, "re_auth_reason")
            .or_else(|| text(data, "re_auth_required"))
            .map(|reason| Self::ReAuth {
                reason: reason.to_owned(),
            })
    }
}

impl Client {
    /// The verification the last session check asked for, while it is
    /// pending. Cleared by the next session check, a sign-in, a sign-out and
    /// a successful [`Self::verify_device_2fa`].
    pub fn session_verification(&self) -> Option<&SessionVerification> {
        self.session_verification.as_ref()
    }

    /// A native session check found `data` unsuccessful: record a requested
    /// verification and keep the session (`true`), or report a plain
    /// rejection (`false`, the caller forgets the session). Browser lanes keep
    /// their own restore rules and always get `false`.
    pub(super) fn hold_for_verification(&mut self, data: &Value) -> bool {
        let native = !self.browser_cookies()
            && self.browser_authority.is_none()
            && self.browser_credentials.is_none()
            && self.session.is_some();
        self.session_verification = native
            .then(|| SessionVerification::of_unsuccessful_session(data))
            .flatten();
        self.session_verification.is_some()
    }

    /// Answer a pending two-factor device verification with `code`
    /// (`POST /v1/auth/2fa/verify/device`). The code is sent through the
    /// wiping plaintext transport and never stored. On success the pending
    /// verification is cleared; the caller validates the session again to
    /// admit it.
    ///
    /// # Errors
    /// `Invalid` without a pending two-factor verification or for a malformed
    /// code (nothing is sent); `Authentication` when the server refused the
    /// code (the verification stays pending); `Expired` when the server ended
    /// the session (the client forgot it); `Offline`, `Protocol`.
    pub async fn verify_device_2fa(&mut self, code: &str) -> Result<()> {
        if !matches!(
            self.session_verification,
            Some(SessionVerification::Device {
                method: DeviceVerificationMethod::TwoFactor,
                ..
            })
        ) {
            return Err(Error::Invalid(
                "No two-factor device verification is pending.",
            ));
        }
        let code = code.trim();
        if code.is_empty()
            || code.len() > MAX_DEVICE_CODE
            || !code.bytes().all(|byte| byte.is_ascii_alphanumeric())
        {
            return Err(Error::Invalid(
                "Enter the code from your authenticator app.",
            ));
        }
        let reply = self
            .request_plaintext(
                Method::POST,
                "/v1/auth/2fa/verify/device",
                json!({"tfa_code": code}),
            )
            .await?;
        if reply.get("success") != Some(&Value::Bool(true)) {
            return Err(Error::Authentication);
        }
        self.session_verification = None;
        // The next validation must reach the server: its answer admits.
        self.recent_validation = None;
        Ok(())
    }
}

#[cfg(all(test, not(target_arch = "wasm32")))]
#[path = "session_verification_tests.rs"]
mod tests;
