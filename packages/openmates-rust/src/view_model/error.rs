//! Typed errors of the view-model boundary: conversion failures for malformed
//! core values and a payload-free mirror of the core `Error` for events.
use crate::error::Error;
use std::fmt;

/// A core value could not be turned into a view-model record. Required fields
/// are never defaulted: a missing or mistyped field is reported by name.
#[derive(Clone, Debug, PartialEq, Eq)]
pub enum ViewModelError {
    /// A required field is empty or absent.
    MissingField {
        /// Record kind, e.g. `chat_row`.
        record: &'static str,
        /// Field name inside the core value.
        field: &'static str,
    },
    /// A field is present but has the wrong JSON type or an out-of-range value.
    InvalidField {
        /// Record kind, e.g. `chat_row`.
        record: &'static str,
        /// Field name inside the core value.
        field: &'static str,
    },
    /// A closed vocabulary (role, status, restoration mode) held an unknown word.
    UnknownVariant {
        /// Record kind, e.g. `message`.
        record: &'static str,
        /// Field name inside the core value.
        field: &'static str,
    },
}

impl fmt::Display for ViewModelError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::MissingField { record, field } => write!(f, "{record}: missing field `{field}`"),
            Self::InvalidField { record, field } => write!(f, "{record}: invalid field `{field}`"),
            Self::UnknownVariant { record, field } => {
                write!(f, "{record}: unknown value in `{field}`")
            }
        }
    }
}

impl std::error::Error for ViewModelError {}

/// Payload-free classification of a core `Error`, safe to ship in an event.
#[derive(Clone, Debug, PartialEq, Eq)]
pub enum ViewErrorKind {
    /// Caller supplied an invalid request.
    Invalid,
    /// Cryptographic operation failed.
    Crypto,
    /// Credentials were refused.
    Authentication,
    /// A second factor is required.
    TwoFactorRequired,
    /// The account does not exist yet and signup is required.
    SignupRequired,
    /// A capability is unavailable, with the stable core error code.
    Unavailable {
        /// Stable code of the refusal.
        code: String,
    },
    /// Local data is locked.
    Locked,
    /// No network.
    Offline,
    /// Access is forbidden.
    Forbidden,
    /// The session expired.
    Expired,
    /// The operation was cancelled.
    Cancelled,
    /// Local I/O failed.
    Io,
    /// The server answered outside the protocol.
    Protocol,
    /// A concurrent change conflicted.
    Conflict,
}

impl From<&Error> for ViewErrorKind {
    fn from(error: &Error) -> Self {
        match error {
            Error::Invalid(_) => Self::Invalid,
            Error::Crypto => Self::Crypto,
            Error::Authentication => Self::Authentication,
            Error::TwoFactorRequired => Self::TwoFactorRequired,
            Error::SignupRequired => Self::SignupRequired,
            Error::Unavailable { code, .. } => Self::Unavailable {
                code: (*code).to_owned(),
            },
            Error::Locked => Self::Locked,
            Error::Offline => Self::Offline,
            Error::Forbidden => Self::Forbidden,
            Error::Expired => Self::Expired,
            Error::Cancelled => Self::Cancelled,
            Error::Io => Self::Io,
            Error::Protocol => Self::Protocol,
            Error::Conflict => Self::Conflict,
        }
    }
}
