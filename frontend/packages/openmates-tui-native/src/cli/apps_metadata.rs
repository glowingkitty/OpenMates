//! `apps list|info|skill-info --json`: print the backend metadata responses unchanged,
//! exactly like the npm CLI (`printJson(await client.listApps())` and friends). Human
//! output keeps the typed `Item` view in `handlers.rs`.
use super::{CliError, CliOutput, Invocation};
use crate::client::Client;

/// True for the metadata reads whose JSON output is the raw backend response.
pub(super) fn handles(invocation: &Invocation) -> bool {
    invocation.boolean("json")
        && matches!(
            invocation.command_path().as_str(),
            "apps list" | "apps info" | "apps skill-info"
        )
}

pub(super) async fn execute(
    invocation: &Invocation,
    client: &mut Client,
) -> Result<CliOutput, CliError> {
    let value = match invocation.command_path().as_str() {
        "apps list" => {
            super::handlers::flags(invocation, &[])?;
            client.apps_metadata_json().await?
        }
        "apps info" => {
            super::handlers::flags(invocation, &[])?;
            client
                .app_metadata_json(positional(invocation, 0, "app ID")?)
                .await?
        }
        _ => {
            super::handlers::flags(invocation, &[])?;
            client
                .app_skill_metadata_json(
                    positional(invocation, 0, "app ID")?,
                    positional(invocation, 1, "skill ID")?,
                )
                .await?
        }
    };
    CliOutput::json(&value)
}

fn positional<'a>(
    invocation: &'a Invocation,
    index: usize,
    label: &str,
) -> Result<&'a str, CliError> {
    invocation
        .positionals
        .get(index)
        .map(String::as_str)
        .filter(|s| !s.trim().is_empty())
        .ok_or_else(|| CliError::Invalid(format!("Missing {label}.")))
}
