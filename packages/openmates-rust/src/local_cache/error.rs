//! Typed failures of the byte layer, with the mapping to the public SDK error.
use crate::error::Error;

/// Why a byte-store operation failed. Details of the OS error are dropped on
/// purpose: file names and paths never reach user-visible messages.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum ByteStoreError {
    /// Operating-system I/O failure.
    Io,
    /// A file or directory is not private (owner, mode, type or link count).
    NotPrivate,
    /// The record name is not a single plain path component.
    InvalidName,
    /// A stored record is larger than `MAX_LOCAL_RECORD_BYTES`.
    TooLarge,
    /// The store directory path is not absolute.
    RelativePath,
    /// The store directory path contains `.` or `..` components.
    NonNormalizedPath,
    /// A lock is held by someone else (non-blocking or timed lock attempt).
    WouldBlock,
}

impl From<std::io::Error> for ByteStoreError {
    fn from(_: std::io::Error) -> Self {
        Self::Io
    }
}

impl From<ByteStoreError> for Error {
    fn from(error: ByteStoreError) -> Self {
        match error {
            ByteStoreError::Io | ByteStoreError::NotPrivate | ByteStoreError::InvalidName => {
                Error::Io
            }
            ByteStoreError::TooLarge => Error::Invalid("The local record is too large."),
            ByteStoreError::RelativePath => {
                Error::Invalid("The state directory must be an absolute path.")
            }
            ByteStoreError::NonNormalizedPath => {
                Error::Invalid("The state directory must use a normalized absolute path.")
            }
            ByteStoreError::WouldBlock => {
                Error::Invalid("This state directory is busy with another native client.")
            }
        }
    }
}
