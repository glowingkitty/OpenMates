//! The fixed public error envelope shared by every binding (NAPI, PyO3, WASM).
//! Only fixed codes/messages cross the boundary; no server diagnostics.
use openmates_sdk::Error;
use serde::Serialize;

#[derive(Debug, Serialize)]
pub struct BindingError {
    pub code: &'static str,
    pub message: &'static str,
}
impl BindingError {
    pub fn json(&self) -> String {
        serde_json::to_string(self).unwrap_or_else(|_| {
            r#"{"code":"protocol","message":"The native operation failed."}"#.into()
        })
    }
}
impl From<Error> for BindingError {
    fn from(error: Error) -> Self {
        let (code, message) = match error {
            Error::Invalid(message) => ("invalid_argument", message),
            Error::Crypto => ("crypto", "Encrypted data could not be authenticated."),
            Error::Authentication => (
                "authentication",
                "Sign-in is required or credentials were rejected.",
            ),
            Error::TwoFactorRequired => (
                "two_factor_required",
                "Enter your two-factor authentication code.",
            ),
            Error::SignupRequired => ("signup_required", "Create an account to continue."),
            Error::Unavailable { .. } => ("unavailable", "The requested operation is unavailable."),
            Error::Locked => ("locked", "The credential store is locked."),
            Error::Offline => ("offline", "The service could not be reached."),
            Error::Forbidden => (
                "forbidden",
                "The operation is not allowed by the account or explicit policy.",
            ),
            Error::Expired => ("expired", "The session expired."),
            Error::VerificationRequired => (
                "verification_required",
                "Verify this device or sign in again to continue.",
            ),
            Error::Cancelled => ("cancelled", "The operation was cancelled."),
            Error::Io => ("io", "The local operation could not be completed."),
            Error::Protocol => ("protocol", "The service returned an invalid response."),
            Error::Conflict => (
                "conflict",
                "Another operation or state change conflicts with this request.",
            ),
        };
        Self { code, message }
    }
}
