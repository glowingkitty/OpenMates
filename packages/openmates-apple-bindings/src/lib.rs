//! UniFFI binding of the shared OpenMates client core (`openmates-sdk`) for the
//! Apple apps; generalises and replaces `apple/PairOpaqueBridge`. Bindings only
//! marshal: `OpenMatesCore` (runtime, client, credential snapshots, listener),
//! the OPAQUE pair-login steps and password-v2 derivation, batched chat
//! decryption (`chat_crypto`), the view-model actor `ViewModelCore` (cache
//! directory, Keychain `CredentialStore`, `ViewListener` events mirrored in
//! `view_records`, send in `view_send`, core-performed password and pair
//! login in `view_login`; session ownership for un-migrated Swift code in
//! `view_session`, `view_http`, `view_adopt`, `view_legacy`), and one typed `CoreError`. Swift module
//! `OpenMatesCore`, C module `OpenMatesCoreFFI`.
//! Plan: `docs/plans/apple-client-core-migration` (A1, A3); spec: `specifications/architecture/client-core`.
uniffi::setup_scaffolding!();

mod chat_crypto;
mod core;
mod error;
mod pairing;
mod view_adopt;
mod view_core;
#[cfg(any(test, feature = "test-support"))]
mod view_fixture;
mod view_http;
mod view_legacy;
mod view_login;
mod view_record_details;
mod view_records;
mod view_send;
mod view_session;

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
pub use view_adopt::{AdoptedSessionRecord, SessionCookieRecord};
pub use view_core::{CredentialStore, ViewListener, ViewModelCore};
pub use view_http::{HttpFieldRecord, HttpRequestRecord, HttpResponseRecord};
pub use view_legacy::LegacySocketGrantRecord;
pub use view_login::PairChallengeRecord;
#[cfg(any(test, feature = "test-support"))]
pub use view_fixture::test_support_seed_cached_account;
pub use view_record_details::{ChatRowMetadataRecord, MessageMetadataRecord, PiiMappingRecord};
pub use view_records::{
    AccessDenialRecord, ChatListRowRecord, ChatRowStatusRecord, ChatWindowSourceRecord,
    ChatWindowViewRecord, EmbedRefRecord, ListCompletenessRecord, MessageRoleRecord,
    MessageStatusRecord, MessageViewRecord, PiiRestorationRecord, SendStateRecord,
    SessionEventRecord, StreamEventRecord, SyncPhaseRecord, ViewErrorKindRecord, ViewEventRecord,
};
pub use view_session::SessionInfoRecord;

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
mod test_api;
#[cfg(test)]
mod view_core_tests;
#[cfg(test)]
mod view_fixture_tests;
#[cfg(test)]
mod view_login_tests;
#[cfg(test)]
mod view_pair_cancel_tests;
#[cfg(test)]
mod view_send_tests;
#[cfg(test)]
mod view_session_tests;
#[cfg(test)]
mod view_window_tests;
