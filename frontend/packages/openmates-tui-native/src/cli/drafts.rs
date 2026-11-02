//! Thin draft command formatting. Cookie headless/cache/version policy lives in
//! the shared Client; explicit API keys use only the shared API-key SDK facade.
use super::{CliError, CliOutput, Invocation};
use crate::{client::Client, error::Error};
use openmates_sdk::{sdk::OpenMates, sdk_drafts::DraftRecord};
use serde_json::{Value, json};
use tokio_util::sync::CancellationToken;

const HELP: &str = "Draft commands:\n  openmates drafts create <text> [--chat <uuid>] [--preview <text>] [--json]\n  openmates drafts update <chat-id> <text> [--preview <text>] [--json]\n  openmates drafts list [--refresh] [--json]\n  openmates drafts get <chat-id> [--refresh] [--json]\n  openmates drafts clear <chat-id> [--json]\n  openmates drafts sync [--json]\n\nDraft plaintext is encrypted locally with the account master key. Only Format-D\nciphertext and version metadata are sent to the server or written to CLI cache.";
pub(super) fn supported(i: &Invocation) -> bool {
    matches!(
        i.command_path().as_str(),
        "drafts" | "drafts list" | "drafts get" | "drafts sync"
    )
}
/// Preserve the maintained parser's separated scalar syntax without letting
/// Clap consume a following --option as the optional refresh value. Scoped to
/// Drafts only; other command families retain their existing refresh arity.
pub(super) fn normalize_refresh_arguments(arguments: &mut Vec<std::ffi::OsString>) {
    let mut at = 1;
    while at < arguments.len() {
        let Some(token) = arguments[at].to_str() else { return; };
        if token == "--" { return; }
        if let Some(option) = token.strip_prefix("--") {
            let key = option.split('=').next().unwrap_or("");
            if !super::catalog().global_flags.iter().any(|name| name == key) { return; }
            let switch = super::catalog().flags.iter().find(|flag| flag.long == key)
                .is_some_and(|flag| flag.arity == "switch");
            at += if !option.contains('=') && !switch { 2 } else { 1 };
        } else if token == "drafts" { break; }
        else { return; }
    }
    if at >= arguments.len() { return; }
    at += 1;
    while at < arguments.len() {
        if arguments[at] == "--" { break; }
        if arguments[at] == "--refresh" {
            if let Some(value) = arguments.get(at + 1).and_then(|value| value.to_str())
                .filter(|value| !value.is_empty() && !value.starts_with("--")) {
                // Separated scalar values retain any equals signs verbatim.
                let value = value.to_owned();
                arguments[at] = format!("--refresh={value}").into();
                arguments.remove(at + 1);
            }
        } else if let Some(value) = arguments[at].to_str().and_then(|arg| arg.strip_prefix("--refresh=")) {
            let value = value.split('=').next().unwrap_or("").to_owned();
            arguments[at] = format!("--refresh={value}").into();
        }
        at += 1;
    }
}
fn force_refresh(i: &Invocation) -> bool { i.flags.get("refresh") == Some(&Value::Bool(true)) }
fn legacy_error(message: impl Into<String>) -> CliError {
    CliError::Contract {
        code: "command_failed",
        message: message.into(),
    }
}
pub(super) fn public(i: &Invocation) -> Option<Result<CliOutput, CliError>> {
    if i.command_path() == "drafts" {
        return Some(if let Some(sub) = i.positionals.first() {
            Err(legacy_error(format!("Unknown drafts subcommand '{sub}'.")))
        } else {
            Ok(CliOutput::text(HELP))
        });
    }
    None
}
fn id(i: &Invocation) -> Result<&str, CliError> {
    i.positionals
        .first()
        .map(String::as_str)
        .filter(|v| !v.is_empty())
        .ok_or_else(|| legacy_error("Missing chat ID for draft get."))
}
fn validate(i: &Invocation, cancel: &CancellationToken) -> Result<(), CliError> {
    super::handlers::flags(i, &["refresh", "personal", "team"])?;
    if cancel.is_cancelled() {
        return Err(Error::Cancelled.into());
    }
    Ok(())
}
/// Match the existing CLI's camelCase draft fields regardless of --json. SDK
/// records retain their language-appropriate wire shape outside this adapter.
fn record(d: DraftRecord) -> Value {
    json!({"chatId":d.encrypted.chat_id,"encryptedDraftMd":d.encrypted.encrypted_draft_md,"encryptedDraftPreview":d.encrypted.encrypted_draft_preview,"draftV":d.encrypted.draft_v,"markdown":d.markdown,"preview":d.preview})
}
fn finish(
    result: Result<CliOutput, CliError>,
    cancel: &CancellationToken,
) -> Result<CliOutput, CliError> {
    if cancel.is_cancelled() {
        if let Ok(mut output) = result {
            use zeroize::Zeroize;
            output.stdout.zeroize();
            output.stderr.zeroize();
        }
        return Err(Error::Cancelled.into());
    }
    result.map_err(|error| match error {
        CliError::Client(Error::Crypto) => legacy_error("Failed to decrypt draft markdown."),
        other => other,
    })
}
pub(super) async fn execute(
    i: &Invocation,
    client: &mut Client,
    cancel: CancellationToken,
) -> Result<CliOutput, CliError> {
    validate(i, &cancel)?;
    if let Some(output) = public(i) {
        return output;
    }
    client.set_operation_cancel(cancel.clone());
    let result=async { match i.command_path().as_str(){
        "drafts list"=>CliOutput::json(&json!({"drafts":client.list_drafts(force_refresh(i)).await?.into_iter().map(record).collect::<Vec<_>>()})),
        "drafts get"=>CliOutput::json(&json!({"draft":client.get_draft(id(i)?,force_refresh(i)).await?.map(record)})),
        "drafts sync"=>CliOutput::json(&json!({"versions":client.reconcile_draft_versions().await?})),
        _=>Err(legacy_error("Unknown drafts subcommand.")),
    }}.await;
    finish(result, &cancel)
}
/// No Cookie session/profile fallback is permitted once an API key is selected.
pub async fn execute_sdk_drafts(
    i: &Invocation,
    client: &mut OpenMates,
    cancel: CancellationToken,
) -> Result<CliOutput, CliError> {
    validate(i, &cancel)?;
    if let Some(output) = public(i) {
        return output;
    }
    client.set_operation_cancel(cancel.clone());
    let result=async { match i.command_path().as_str(){
        "drafts list"=>CliOutput::json(&json!({"drafts":client.drafts().list().await?.into_iter().map(record).collect::<Vec<_>>()})),
        "drafts get"=>CliOutput::json(&json!({"draft":client.drafts().get(id(i)?).await?.map(record)})),
        "drafts sync"=>Err(CliError::Client(Error::Unavailable{code:"api_key_draft_sync_unavailable",reason:"API-key credentials do not expose cached Cookie draft version reconciliation; use drafts list or get."})),
        _=>Err(legacy_error("Unknown drafts subcommand.")),
    }}.await;
    finish(result, &cancel)
}

#[cfg(test)]
#[path = "drafts_tests.rs"]
mod tests;
