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
    Cancelled,
    Io,
    Protocol,
    Conflict,
}
pub type Result<T> = std::result::Result<T, Error>;
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
