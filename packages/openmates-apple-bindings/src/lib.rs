//! UniFFI binding of the shared OpenMates client core (`openmates-sdk`) for the
//! Apple apps; generalises and replaces `apple/PairOpaqueBridge`. Bindings only
//! marshal: `OpenMatesCore` (runtime, client, credential snapshots, listener),
//! the OPAQUE pair-login steps and password-v2 derivation, batched chat
//! decryption (`chat_crypto`), the view-model actor `ViewModelCore` (cache
//! directory, Keychain `CredentialStore`, `ViewListener` events mirrored in
//! `view_records`), and one typed `CoreError`. Swift module
//! `OpenMatesCore`, C module `OpenMatesCoreFFI`.
//! Plan: `docs/plans/apple-client-core-migration` (A1, A3); spec: `specifications/architecture/client-core`.
uniffi::setup_scaffolding!();

mod chat_crypto;
mod core;
mod error;
mod pairing;
mod view_core;
mod view_records;

pub use crate::core::{
    CoreCancellation, CoreConfig, CoreListener, CredentialSnapshotRecord, OpenMatesCore,
    ProbeRecord, test_support_synthetic_credentials_payload,
};
pub use chat_crypto::{
    ChatKeyUnwrapOutcome, ChatMetadataRecord, DecryptFailure, EncryptedChatMetadataRecord,
    EncryptedMessageRecord, FieldDecryptOutcome, MessageFieldsRecord, UnwrappedChatKeyRecord,
    WrappedChatKeyRecord, batch_decrypt_chat_metadata, batch_decrypt_messages,
    batch_unwrap_chat_keys,
};
pub use error::CoreError;
pub use pairing::{
    ClientLoginFinishRecord, ClientLoginStartRecord, ClientRegistrationStartRecord,
    OpaqueIdentifiersRecord, PasswordV2KeysRecord, ServerLoginStartRecord,
    create_server_registration_response, create_server_setup, derive_password_v2,
    finish_client_login, finish_client_registration, finish_server_login, start_client_login,
    start_client_registration, start_server_login,
};
pub use view_core::{CredentialStore, ViewListener, ViewModelCore};
pub use view_records::{
    AccessDenialRecord, ChatListRowRecord, ChatRowStatusRecord, ChatWindowSourceRecord,
    ChatWindowViewRecord, EmbedRefRecord, ListCompletenessRecord, MessageRoleRecord,
    MessageStatusRecord, MessageViewRecord, PiiRestorationRecord, SessionEventRecord,
    StreamEventRecord, SyncPhaseRecord, ViewErrorKindRecord, ViewEventRecord,
};

/// Version of this binding crate, so Swift can check that the framework and the
/// generated Swift come from one build.
#[uniffi::export]
pub fn core_version() -> String {
    env!("CARGO_PKG_VERSION").to_owned()
}

#[cfg(test)]
mod chat_crypto_tests;
#[cfg(test)]
mod core_tests;
#[cfg(test)]
mod pairing_tests;
#[cfg(test)]
mod view_core_tests;
