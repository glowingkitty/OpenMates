//! UniFFI binding of the shared OpenMates client core (`openmates-sdk`) for the
//! Apple apps; generalises and replaces `apple/PairOpaqueBridge`. Bindings only
//! marshal: `OpenMatesCore` (runtime, client, credential snapshots, listener),
//! the OPAQUE pair-login steps and password-v2 derivation, batched chat
//! decryption (`chat_crypto`), the view-model actor `ViewModelCore` (cache
//! directory, Keychain `CredentialStore`, `ViewListener` events mirrored in
//! `view_records`, send in `view_send` (per-turn options and receipt in
//! `view_send_options`), core-performed password, backup-code,
//! recovery-key and pair login in `view_login` (password migration records in
//! `view_login_migration`, passkey login and device verification in
//! `view_login_passkey`); the user payload and device verification in
//! `view_account`; session ownership for un-migrated Swift code in
//! `view_session`, `view_http`, `view_adopt`, `view_legacy`), and one typed `CoreError`. Swift module
//! `OpenMatesCore`, C module `OpenMatesCoreFFI`.
//! Plan: `docs/plans/apple-client-core-migration` (A1, A3); spec: `specifications/architecture/client-core`.
uniffi::setup_scaffolding!();

mod chat_crypto;
mod core;
mod error;
mod pairing;
mod view_account;
mod view_adopt;
mod view_chat_actions;
mod view_consent;
#[cfg(test)]
mod view_consent_tests;
mod view_core;
mod view_draft_versions;
mod view_drafts;
mod view_embed_enhance;
mod view_embeds;
#[cfg(any(test, feature = "test-support"))]
mod view_fixture;
#[cfg(any(test, feature = "test-support"))]
mod view_fixture_ffi;
#[cfg(any(test, feature = "test-support"))]
mod view_fixture_rows;
mod view_http;
mod view_legacy;
mod view_login;
mod view_login_migration;
mod view_login_passkey;
mod view_memories;
mod view_record_details;
mod view_records;
mod view_region;
mod view_send;
mod view_send_attachments;
mod view_send_options;
mod view_send_stream;
mod view_unowned;
mod view_vault;
mod view_session;
mod view_upload;

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
pub use view_account::{DeviceVerificationMethodRecord, SessionVerificationRecord, UserProfileRecord};
pub use view_adopt::{AdoptedSessionRecord, SessionCookieRecord};
pub use view_core::{CredentialStore, ViewListener, ViewModelCore};
pub use view_draft_versions::{DraftVersionQueryRecord, ServerDraftVersionRecord};
pub use view_drafts::DraftViewRecord;
/// Image Enhance records and the socket-frame waker (`view_embed_enhance`).
pub use view_embed_enhance::{
    ImageEnhanceJobRecord, ImageEnhanceSavedRecord, ImageEnhanceStateRecord, ImageEnhanceWaker,
};
/// User-made embed versions, the embed-updated timeline and their typed error (`view_embeds`).
pub use view_embeds::{
    EmbedEditError, EmbedEventDeliveryRecord, EmbedKindRecord, EmbedNoticeReconcileRecord,
    EmbedRevisionOriginRecord, EmbedRevisionOutcomeRecord, EmbedScopeRecord,
    EmbedTimelineItemRecord, EmbedTimelineRowRecord, EmbedUpdateActionRecord,
    EmbedUpdateSurfaceRecord, EmbedUpdatedGroupRecord, EmbedVersionHistoryRecord,
    EmbedVersionRecord, embed_update_timeline,
};
pub use view_http::{HttpFieldRecord, HttpRequestRecord, HttpResponseRecord};
pub use view_legacy::LegacySocketGrantRecord;
pub use view_login::PairChallengeRecord;
pub use view_login_migration::{LoginRecord, PasswordMigrationRecord};
pub use view_login_passkey::PasskeyChallengeRecord;
/// Memory documents, assistant Memory writes and their notices (`view_memories`).
pub use view_memories::{
    ContextEntryActionRecord, ContextEntryKindRecord, ContextEntryNoticeRecord,
    MemoryDocumentRecord, MemoryFieldsRecord, MemoryLoadModeRecord, MemoryUndoOutcomeRecord,
    context_entry_notice,
};
#[cfg(any(test, feature = "test-support"))]
pub use view_fixture::test_support_seed_cached_account;
#[cfg(any(test, feature = "test-support"))]
pub use view_fixture_ffi::openmates_test_support_seed_chat_list;
pub use view_record_details::{ChatRowMetadataRecord, MessageMetadataRecord, PiiMappingRecord};
pub use view_records::{
    AccessDenialRecord, ChatListRowRecord, ChatRowStatusRecord, ChatWindowSourceRecord,
    ChatWindowViewRecord, EmbedRefRecord, ListCompletenessRecord, MessageRoleRecord,
    MessageStatusRecord, MessageViewRecord, PiiRestorationRecord, SendStateRecord,
    SessionEventRecord, StreamEventRecord, SyncPhaseRecord, ViewErrorKindRecord, ViewEventRecord,
};
/// Server region preference of sends (`view_region`).
pub use view_region::ServerRegionPreferenceRecord;
/// Per-turn send options and the delivery receipt (`view_send_options`).
pub use view_send_options::{
    SendOptionsRecord, SendQueueModeRecord, SendReceiptRecord, SendStatusRecord,
};
/// A composer attachment of a turn (`view_send_attachments`).
pub use view_send_attachments::SendEmbedRecord;
pub use view_session::SessionInfoRecord;
pub use view_upload::UploadRequestRecord;

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
mod view_account_tests;
#[cfg(test)]
mod view_chat_actions_tests;
#[cfg(test)]
mod view_core_tests;
#[cfg(test)]
mod view_draft_unowned_tests;
#[cfg(test)]
mod view_drafts_tests;
#[cfg(test)]
mod view_embeds_tests;
#[cfg(test)]
mod view_fixture_tests;
#[cfg(test)]
mod view_fixture_rows_tests;
#[cfg(test)]
mod view_login_tests;
#[cfg(test)]
mod view_login_methods_tests;
#[cfg(test)]
mod view_login_passkey_tests;
#[cfg(test)]
mod view_memories_tests;
#[cfg(test)]
mod view_pair_cancel_tests;
#[cfg(test)]
mod view_region_tests;
#[cfg(test)]
mod view_send_attachments_tests;
#[cfg(test)]
mod view_send_options_tests;
#[cfg(test)]
mod view_send_tests;
#[cfg(test)]
mod view_session_tests;
#[cfg(test)]
mod view_upload_tests;
#[cfg(test)]
mod view_profile_cache_tests;
#[cfg(test)]
mod view_window_tests;
