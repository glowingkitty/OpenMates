//! Native ports of the remaining npm-only utility commands: Design icon
//! export and the dev-only E2E account provisioning. Each lives in its own
//! module; this file only registers and dispatches them.
use super::{CliError, CliOutput, Invocation};
use crate::{client::Client, runtime_store::RuntimeStore};
use tokio_util::sync::CancellationToken;
use zeroize::Zeroizing;

mod design_icon;
mod e2e_provision;

/// A thrown npm `Error`: the message on stderr and exit 1.
pub(super) fn failed(message: impl Into<String>) -> CliError {
    CliError::Contract {
        code: "command_failed",
        message: message.into(),
    }
}

pub(super) fn supported(i: &Invocation) -> bool {
    matches!(
        i.command_path().as_str(),
        design_icon::COMMAND | e2e_provision::COMMAND
    )
}

/// Authenticated commands that run on an opened session client.
pub(super) async fn execute(i: &Invocation, client: &mut Client) -> Result<CliOutput, CliError> {
    match i.command_path().as_str() {
        design_icon::COMMAND => design_icon::execute(i, design_icon::SvgSource::Session(client)).await,
        _ => Err(CliError::Unsupported {
            command: i.command_path(),
            reason: "This command runs on a credential-free profile.".into(),
        }),
    }
}

/// `apps design export-icon` under an explicit `--api-key`.
pub(super) fn key_supported(i: &Invocation) -> bool {
    i.command_path() == design_icon::COMMAND
}
pub(super) async fn execute_key(
    i: &Invocation,
    sdk: &openmates_sdk::sdk::OpenMates,
) -> Result<CliOutput, CliError> {
    design_icon::execute(i, design_icon::SvgSource::ApiKey(sdk)).await
}

/// True for the command that creates its own account and session.
pub fn is_provisioning(i: &Invocation) -> bool {
    i.command_path() == e2e_provision::COMMAND
}

/// `e2e provision-auth-accounts` on a credential-free profile (like signup).
pub async fn execute_provisioning(
    i: &Invocation,
    client: &mut Client,
    store: &RuntimeStore,
    passphrase: Option<Zeroizing<String>>,
    api: &str,
    cancel: &CancellationToken,
) -> Result<CliOutput, CliError> {
    e2e_provision::execute(i, client, store, passphrase, api, cancel).await
}
