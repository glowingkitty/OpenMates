//! Connected-account row planning for the Apple shell
//! (`specifications/architecture/connected-accounts`,
//! `connected-accounts.connection.private-reusable`): the core decides every
//! plaintext the shell encrypts for a new or updated account row and guards
//! the finished row against plaintext fields. Marshalling only; the rules
//! live in `openmates_sdk::web_connected_accounts::oauth` (shared with the
//! web Worker unit `connectedAccountsUnit.ts`). The shell keeps master-key
//! encryption, SHA-256 and the claimed refresh-token bundle, as on web.

use crate::CoreError;
use openmates_sdk::web_connected_accounts::oauth;

fn protocol(code: String) -> CoreError {
    CoreError::Invalid { message: code }
}

/// Ordered encrypt/hash steps of a new connected-account row from an OAuth
/// handoff (`oauth_row_plan_json`; input and output JSON as documented there).
///
/// # Errors
/// `Invalid { message: "protocol" }` for a malformed envelope.
#[uniffi::export]
pub fn connected_account_oauth_row_plan(input_json: String) -> Result<String, CoreError> {
    oauth::oauth_row_plan_json(&input_json).map_err(protocol)
}

/// Merge plan of an update that adds an app to an existing account row
/// (`merge_account_update_json`): the plaintext texts to re-encrypt.
///
/// # Errors
/// `Invalid { message: "protocol" }` for a malformed envelope or plaintext.
#[uniffi::export]
pub fn connected_account_merge_update(input_json: String) -> Result<String, CoreError> {
    oauth::merge_account_update_json(&input_json).map_err(protocol)
}

/// Storage guard over the finished row's serialized JSON: `{"kind":"ok"}` or
/// the `forbidden` outcome when a plaintext-only field would be stored.
///
/// # Errors
/// None today; the `Result` keeps the binding signature uniform.
#[uniffi::export]
pub fn connected_account_storage_guard(serialized: String) -> Result<String, CoreError> {
    oauth::storage_guard_json(&serialized).map_err(protocol)
}
