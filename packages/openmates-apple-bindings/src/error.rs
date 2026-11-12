//! The one typed error that crosses the UniFFI boundary to Swift. Each variant
//! maps exactly one `openmates_sdk::Error` kind (no string matching, no silent
//! fallback); `Internal` is only for binding-level failures such as a panicked or
//! shut-down runtime task. Messages never contain secrets, URLs or bodies.
//! Spec: `specifications/architecture/client-core` (typed errors across bindings).
use openmates_sdk::Error as SdkError;

/// Error returned by every fallible Apple binding call. Swift sees an `enum
/// CoreError: Error` with these cases. `Cancelled` covers both a call stopped
/// through its `CoreCancellation` (Swift task cancelled) and a core refusal such
/// as a stale credential revision passed to `acknowledge_credentials`; the Swift
/// glue maps the former to `CancellationError` when `Task.isCancelled`.
#[derive(Debug, Clone, PartialEq, Eq, thiserror::Error, uniffi::Error)]
pub enum CoreError {
    /// Malformed caller input; `message` is the core's fixed English reason.
    #[error("{message}")]
    Invalid {
        /// Fixed, non-secret reason from the core.
        message: String,
    },
    /// Authenticated decryption, key derivation or OPAQUE verification failed.
    #[error("Encrypted data could not be authenticated.")]
    Crypto,
    /// Sign-in failed or no session is loaded.
    #[error("Sign-in failed.")]
    Authentication,
    /// The account needs a two-factor code.
    #[error("Two-factor authentication code required.")]
    TwoFactorRequired,
    /// The anonymous allowance is used up.
    #[error("Signup required.")]
    SignupRequired,
    /// A capability is unavailable; `code`/`reason` are stable identifiers.
    #[error("Unavailable: {code}")]
    Unavailable {
        /// Stable machine code.
        code: String,
        /// Stable machine reason.
        reason: String,
    },
    /// A local store or resource is locked.
    #[error("Locked.")]
    Locked,
    /// No network connection to the server.
    #[error("Offline.")]
    Offline,
    /// The operation is not allowed for this account, team or session kind.
    #[error("Forbidden.")]
    Forbidden,
    /// The session expired.
    #[error("Session expired.")]
    Expired,
    /// The server kept the session but asks to verify this device or to sign
    /// in again; the detail is the event `Session(VerificationRequired)` and
    /// `ViewModelCore.pendingVerification()`. Stored credentials stay.
    #[error("Device verification or a new sign-in is required.")]
    VerificationRequired,
    /// The core aborted the operation (also: stale credential revision).
    #[error("Cancelled.")]
    Cancelled,
    /// A local I/O operation failed.
    #[error("Local I/O failed.")]
    Io,
    /// The server or a stored payload had an invalid or unsupported shape.
    /// Swift name `ProtocolError` (uniffi.toml rename: `Protocol` is reserved).
    #[error("Invalid or unsupported response.")]
    Protocol,
    /// The object changed; read its latest state before retrying.
    #[error("Conflict.")]
    Conflict,
    /// A Memory operation was refused (`view_memories.rs`). `code` is the web
    /// client's stable code (`ruleDocumentService.ts`): `rule_not_found`,
    /// `rule_exists`, `rule_changed`, `rule_not_undoable`,
    /// `invalid_rule_document`, `rule_catalog_limit`,
    /// `rule_settings_unavailable` or `rule_save_failed`.
    #[error("Memory refused: {code}")]
    Memory {
        /// Stable lowercase code.
        code: String,
    },
    /// Binding failure (runtime task panicked or the core was shut down).
    #[error("Internal binding failure: {reason}")]
    Internal {
        /// Fixed, non-secret reason.
        reason: String,
    },
}

impl From<SdkError> for CoreError {
    fn from(error: SdkError) -> Self {
        match error {
            SdkError::Invalid(message) => Self::Invalid {
                message: message.to_owned(),
            },
            SdkError::Crypto => Self::Crypto,
            SdkError::Authentication => Self::Authentication,
            SdkError::TwoFactorRequired => Self::TwoFactorRequired,
            SdkError::SignupRequired => Self::SignupRequired,
            SdkError::Unavailable { code, reason } => Self::Unavailable {
                code: code.to_owned(),
                reason: reason.to_owned(),
            },
            SdkError::Locked => Self::Locked,
            SdkError::Offline => Self::Offline,
            SdkError::Forbidden => Self::Forbidden,
            SdkError::Expired => Self::Expired,
            SdkError::VerificationRequired => Self::VerificationRequired,
            SdkError::Cancelled => Self::Cancelled,
            SdkError::Io => Self::Io,
            SdkError::Protocol => Self::Protocol,
            SdkError::Conflict => Self::Conflict,
        }
    }
}

/// A Swift callback (credential store, listener) failed outside its declared
/// error type (for example it threw a foreign error): a binding failure.
impl From<uniffi::UnexpectedUniFFICallbackError> for CoreError {
    fn from(_: uniffi::UnexpectedUniFFICallbackError) -> Self {
        Self::internal("Swift callback failed unexpectedly")
    }
}

impl CoreError {
    pub(crate) fn internal(reason: &'static str) -> Self {
        Self::Internal {
            reason: reason.to_owned(),
        }
    }
}
