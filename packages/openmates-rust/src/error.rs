//! Public errors never include transport URLs, response bodies or secrets.
use std::fmt;
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Error {
    Invalid(&'static str),
    Crypto,
    Authentication,
    TwoFactorRequired,
    SignupRequired,
    Unavailable {
        code: &'static str,
        reason: &'static str,
    },
    Locked,
    Offline,
    Forbidden,
    Expired,
    /// The server kept the session but asks to verify this device or to sign
    /// in again; the detail is `Client::session_verification`. Stored
    /// credentials stay (the session is not gone).
    VerificationRequired,
    Cancelled,
    Io,
    Protocol,
    Conflict,
}
pub type Result<T> = std::result::Result<T, Error>;

/// Stable code of the public SDK missing-API-key refusal, byte-identical to npm
/// `SDK_API_KEY_REQUIRED_CODE` and Python `SDK_API_KEY_REQUIRED_CODE`
/// (`OpenMatesApiKeyRequiredError.code`). Spec: `sdk.auth.api-key-only`; shared
/// vector `tests/sdk-conformance/fixtures/sdk-api-key-required.json`.
pub const SDK_API_KEY_REQUIRED_CODE: &str = "OPENMATES_SDK_API_KEY_REQUIRED";
/// Fixed message that identifies the missing-API-key `Error::Invalid` refusal.
pub(crate) const SDK_API_KEY_REQUIRED_MESSAGE: &str = "The OpenMates SDK requires an explicit API key. Create an API key in Settings → Developers and pass it explicitly; the SDK never uses the CLI login.";

impl Error {
    /// Stable cross-SDK code of a typed refusal that npm/Python expose as
    /// `error.code`, or `None` when the error has no such code. It is kept as an
    /// accessor rather than a new variant so existing exhaustive matches and the
    /// fixed binding error envelope stay unchanged.
    pub fn sdk_code(&self) -> Option<&'static str> {
        match self {
            Self::Invalid(message) if *message == SDK_API_KEY_REQUIRED_MESSAGE => {
                Some(SDK_API_KEY_REQUIRED_CODE)
            }
            _ => None,
        }
    }
}

impl fmt::Display for Error {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str(match self {
            Self::Invalid(message) => message,
            Self::Crypto => "Encrypted data could not be authenticated.",
            Self::Authentication => "Sign-in failed. Check your credentials and try again.",
            Self::Unavailable { .. } => "This App skill is unavailable.",
            Self::SignupRequired => "Create an account to continue after the anonymous allowance.",
            Self::TwoFactorRequired => "Enter your two-factor authentication code.",
            Self::Locked => "Unlock the existing credential store; its storage mode was preserved.",
            Self::Offline => "Offline. Showing available encrypted local data.",
            Self::Forbidden => "This operation is not available for the current account or Team.",
            Self::Expired => "This session expired. Sign in again.",
            Self::VerificationRequired => "Verify this device or sign in again to continue.",
            Self::Cancelled => "The operation was cancelled.",
            Self::Io => "The local operation could not be completed.",
            Self::Conflict => "The object changed. Read its latest state before retrying.",
            Self::Protocol => "The server returned an invalid or unsupported response.",
        })
    }
}
impl std::error::Error for Error {}
impl From<std::io::Error> for Error {
    fn from(_: std::io::Error) -> Self {
        Self::Io
    }
}
impl From<serde_json::Error> for Error {
    fn from(_: serde_json::Error) -> Self {
        Self::Protocol
    }
}
impl From<reqwest::Error> for Error {
    fn from(_: reqwest::Error) -> Self {
        Self::Offline
    }
}
