//! Outcome records of a core-performed sign-in on `ViewModelCore` and the
//! password v1→v2 migration step the login runs before the hand-over
//! (`Client::migrate_legacy_password`). Marshalling only: the protocol, the
//! resume rule (server-side staged state, nothing stored here) and the key
//! checks live in `openmates-sdk` (`client/password_migration.rs`). A failed
//! migration never fails the login; it is reported as `Failed`.
//! Plan `apple-client-core-migration` (A2 Apple login hand-over).
use crate::view_records::ViewErrorKindRecord;
use openmates_sdk::{
    Client,
    client::{PasswordLoginReport, PasswordMigrationOutcome},
    view_model::ViewErrorKind,
};
use tokio_util::sync::CancellationToken;
use zeroize::Zeroizing;

/// What a successful sign-in reports to Swift besides the started session.
#[derive(Clone, Debug, PartialEq, Eq, uniffi::Record)]
pub struct LoginRecord {
    /// The password v1→v2 migration the core ran after this login.
    pub password_migration: PasswordMigrationRecord,
    /// Backup codes left after a backup-code login; `None` otherwise.
    pub remaining_backup_codes: Option<u32>,
}

/// Outcome of the password v1→v2 migration (core `PasswordMigrationOutcome`).
/// Every value but `Completed` leaves the old password working; the core
/// resumes a `PendingConfirmation` at the next password login by itself.
#[derive(Clone, Debug, PartialEq, Eq, uniffi::Enum)]
pub enum PasswordMigrationRecord {
    /// Not a legacy password login (v2 password, recovery key): nothing ran.
    NotNeeded,
    /// The v2 credential is live and the legacy one retired.
    Completed,
    /// v2 installed; the server keeps the legacy credential too.
    LegacyRetained,
    /// v2 staged, not confirmed yet; the next password login resumes it.
    PendingConfirmation,
    /// The account's legacy credentials must be bound first; nothing staged.
    DeferredLegacyCredentials,
    /// The server asks for a recent strong verification first.
    DeferredRecentVerification,
    /// The server asks for a fresh password login first.
    DeferredFreshLogin,
    /// The server does not offer the staged migration protocol.
    Unsupported,
    /// The attempt failed (network, malformed reply, wrapper mismatch, or
    /// cancelled); the login itself succeeded.
    Failed {
        /// Payload-free failure class.
        kind: ViewErrorKindRecord,
    },
}

impl From<PasswordMigrationOutcome> for PasswordMigrationRecord {
    fn from(value: PasswordMigrationOutcome) -> Self {
        match value {
            PasswordMigrationOutcome::Completed => Self::Completed,
            PasswordMigrationOutcome::LegacyRetained => Self::LegacyRetained,
            PasswordMigrationOutcome::PendingConfirmation => Self::PendingConfirmation,
            PasswordMigrationOutcome::DeferredLegacyCredentials => Self::DeferredLegacyCredentials,
            PasswordMigrationOutcome::DeferredRecentVerification => {
                Self::DeferredRecentVerification
            }
            PasswordMigrationOutcome::DeferredFreshLogin => Self::DeferredFreshLogin,
            PasswordMigrationOutcome::Unsupported => Self::Unsupported,
        }
    }
}

impl From<openmates_sdk::Error> for PasswordMigrationRecord {
    fn from(error: openmates_sdk::Error) -> Self {
        Self::Failed {
            kind: ViewErrorKind::from(&error).into(),
        }
    }
}

/// Run the core migration on the freshly signed-in `client` when `report`
/// says a legacy (v1) password unlocked it. A cancel stops the attempt (the
/// server keeps any staged state for the next login) and reports `Failed`
/// with `Cancelled`; the caller's own cancel check then ends the login.
pub(crate) async fn migrate_after_login(
    client: &Client,
    report: &PasswordLoginReport,
    password: &Zeroizing<String>,
    cancel: &CancellationToken,
) -> PasswordMigrationRecord {
    if report.credential_version != 1 {
        return PasswordMigrationRecord::NotNeeded;
    }
    tokio::select! {
        biased;
        () = cancel.cancelled() => openmates_sdk::Error::Cancelled.into(),
        outcome = client.migrate_legacy_password(password) => match outcome {
            Ok(outcome) => outcome.into(),
            Err(error) => error.into(),
        },
    }
}
