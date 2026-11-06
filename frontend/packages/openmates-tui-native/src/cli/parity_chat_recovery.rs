//! npm-parity commands for saved-chat history edits (`chats fork|rewind|retry`),
//! chat media (`chats files|open|speak`) and the work-recovery projection
//! (`recovery [full-sync|validate|restore]`). Shared dispatchers call only this
//! module so each carries a single wiring line; behavior lives in the
//! submodules and reusable headless logic in `openmates_sdk`.
use super::{CliError, CliOutput, Invocation};
use crate::client::Client;
use tokio_util::sync::CancellationToken;

#[path = "chat_media.rs"]
mod chat_media;
#[path = "chat_rewrite.rs"]
mod chat_rewrite;
#[path = "recovery.rs"]
mod recovery;

pub(super) fn supported(invocation: &Invocation) -> bool {
    chat_rewrite::supported(invocation)
        || chat_media::supported(invocation)
        || recovery::supported(invocation)
}

/// Commands that need no credentials (npm prints them before any session use).
pub(super) fn is_public(invocation: &Invocation) -> bool {
    recovery::is_public(invocation)
}

/// Credential-free output, run before credential storage is opened.
pub(super) fn public(invocation: &Invocation) -> Option<Result<CliOutput, CliError>> {
    recovery::public(invocation)
}

pub(super) async fn execute(
    invocation: &Invocation,
    client: &mut Client,
    cancel: CancellationToken,
) -> Result<CliOutput, CliError> {
    if chat_rewrite::supported(invocation) {
        return Box::pin(chat_rewrite::execute(invocation, client, cancel)).await;
    }
    if chat_media::supported(invocation) {
        return Box::pin(chat_media::execute(invocation, client, cancel)).await;
    }
    Box::pin(recovery::execute(invocation, client, cancel)).await
}

/// Commands with an explicit `--api-key` route: `chats fork|rewind|retry|open`.
pub(super) fn key_supported(invocation: &Invocation) -> bool {
    chat_rewrite::supported(invocation) || invocation.command_path() == "chats open"
}

/// Runs a [`key_supported`] command over the API-key SDK only; no Cookie
/// profile is loaded, so credentials never mix.
pub(super) async fn execute_key(
    invocation: &Invocation,
    sdk: &mut openmates_sdk::sdk::OpenMates,
) -> Result<CliOutput, CliError> {
    if chat_rewrite::supported(invocation) {
        return Box::pin(chat_rewrite::execute_key(invocation, sdk)).await;
    }
    Box::pin(chat_media::execute_open_key(invocation, sdk)).await
}
