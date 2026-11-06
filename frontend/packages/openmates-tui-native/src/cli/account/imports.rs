//! `account import <claude|chatgpt|openmates|opencode|generic>` and
//! `account import-chat` (also under `settings account ...`): the npm
//! handleSettings branches with the same flags, messages, `[y/N]` confirmation
//! and output. This adapter reads the local file and opens archives; parsing,
//! the batched import flow and chat encryption live in the shared core.
use super::imports_zip::{ZipArchive, decrypt_openmates_zip, is_zip};
use super::settings_more::{confirm, mutation, text_output};
use super::{CliError, CliOutput, Invocation, handlers, path};
use crate::client::Client;
use openmates_sdk::OpenMates;
use openmates_sdk::account::AccountImportPlan;
use openmates_sdk::account::imports_chat::parse_chat_import_payload;
use openmates_sdk::account::imports_parse::{
    ImportParser, ImportSource, ParsedAccountImport, parse_chatgpt_import, parse_claude_import,
    parse_generic_import, parse_opencode_import, parse_openmates_import,
};
use serde_json::Value;

const FORMATS: &[&str] = &["claude", "chatgpt", "openmates", "opencode", "generic"];

pub(super) fn supported(i: &Invocation) -> bool {
    let path = path(i);
    path == "account import-chat"
        || path
            .strip_prefix("account import ")
            .is_some_and(|format| FORMATS.contains(&format))
}

fn invalid(message: impl Into<String>) -> CliError {
    CliError::Invalid(message.into())
}
/// npm throws a plain `Error` for unusable chat-import content: `command_failed`, exit 1.
fn failed(message: impl Into<String>) -> CliError {
    CliError::Contract {
        code: "command_failed",
        message: message.into(),
    }
}

pub(super) async fn execute(i: &Invocation, client: &mut Client) -> Result<CliOutput, CliError> {
    let path = path(i);
    match path.strip_prefix("account import ") {
        Some(format) => import(i, client, format).await,
        None if i.has("api-key") => Err(chat_import_requires_session(i)),
        None => import_chat(i, client).await,
    }
}

fn chat_import_requires_session(i: &Invocation) -> CliError {
    CliError::Unsupported {
        command: i.command_path(),
        reason: "Chat import requires an authenticated native session; the server route does not accept --api-key credentials.".into(),
    }
}

fn read(file: &str) -> Result<Vec<u8>, CliError> {
    std::fs::read(file).map_err(|e| invalid(format!("Could not read import file {file}: {e}")))
}

async fn import_chat(i: &Invocation, client: &mut Client) -> Result<CliOutput, CliError> {
    handlers::flags(i, &[])?;
    let file = i.positionals.first().ok_or_else(|| {
        invalid("Missing import file. Example: openmates settings account import-chat ./chat.yml")
    })?;
    let raw = read(file)?;
    let payload = parse_chat_import_payload(&String::from_utf8_lossy(&raw)).map_err(failed)?;
    let result = client.account().import_chat_export(payload).await?;
    mutation(i, &result)
}

/// npm `parseAccountImportFile`.
pub(super) fn parse_file(
    parser: ImportParser,
    payload: Vec<u8>,
    source_name: &str,
    requested_source: Option<&str>,
    password: Option<&str>,
) -> Result<ParsedAccountImport, String> {
    let requested = requested_source.unwrap_or(parser.as_str());
    let selected = ImportSource::parse(requested)
        .ok_or_else(|| format!("Unsupported account import source: {requested}"))?;
    let text = |label: &str, payload: &[u8]| -> Result<String, String> {
        if is_zip(payload) {
            ZipArchive::open(payload)
                .and_then(|zip| zip.find_text("conversations.json"))
                .map_err(|e| format!("{label} export could not be parsed: {e}"))
        } else {
            Ok(String::from_utf8_lossy(payload).into_owned())
        }
    };
    match parser {
        ImportParser::Generic => {
            if !matches!(selected, ImportSource::Gemini | ImportSource::Other) {
                return Err(
                    "Generic account import requires --source gemini or --source other.".into(),
                );
            }
            parse_generic_import(&String::from_utf8_lossy(&payload), source_name, selected)
        }
        ImportParser::Claude => {
            parse_claude_import(&text("Claude", &payload)?, source_name, selected)
        }
        ImportParser::ChatGpt => {
            parse_chatgpt_import(&text("ChatGPT", &payload)?, source_name, selected)
        }
        ImportParser::OpenCode => {
            parse_opencode_import(&String::from_utf8_lossy(&payload), source_name, selected)
        }
        ImportParser::OpenMates => {
            let plain = decrypt_openmates_zip(payload, password)?;
            let zip = ZipArchive::open(&plain)?;
            let manifest = zip.exact_text("manifest.yml")?;
            parse_openmates_import(manifest.as_deref(), &zip.names(), source_name, selected)
        }
    }
}

fn load(i: &Invocation, format: &str) -> Result<(ImportParser, ParsedAccountImport), CliError> {
    handlers::flags(
        i,
        &["dry-run", "source", "password", "select", "yes", "domain"],
    )?;
    let parser =
        ImportParser::parse(format).ok_or_else(|| invalid("Unsupported account import format."))?;
    let file = i.positionals.first().ok_or_else(|| {
        invalid(format!(
            "Missing import file. Example: openmates account import {format} ./export.zip --dry-run"
        ))
    })?;
    if parser == ImportParser::Generic && i.text("source").is_none() {
        return Err(invalid(
            "Generic account import requires --source gemini or --source other.",
        ));
    }
    let source_name = std::path::Path::new(file)
        .file_name()
        .map_or_else(|| file.clone(), |n| n.to_string_lossy().into_owned());
    let parsed = parse_file(
        parser,
        read(file)?,
        &source_name,
        i.text("source"),
        i.text("password"),
    )
    .map_err(invalid)?;
    if parser == ImportParser::OpenMates && i.has("domain") && i.text("domain") != Some("chats") {
        return Err(invalid(
            "Account Import V1 only supports --domain chats for OpenMates archives.",
        ));
    }
    Ok((parser, parsed))
}

/// Dry run, blocked and confirmation gates shared by both credentials. `None`
/// means the import is confirmed and should run.
async fn gate(i: &Invocation, plan: &AccountImportPlan) -> Result<Option<CliOutput>, CliError> {
    if i.boolean("dry-run") {
        return print(i, &plan.result).map(Some);
    }
    if !plan.can_import() {
        return Err(invalid(format!(
            "Account import blocked: {}",
            plan.blocked_reason()
        )));
    }
    if plan.selected_count <= 0 {
        return Err(invalid("No chats are selected for import."));
    }
    let question = format!(
        "Import {} chat(s) into new encrypted OpenMates chats? [y/N] ",
        plan.selected_count
    );
    if !confirm(i, &question).await? {
        return Ok(Some(text_output("Aborted.\n".into())));
    }
    Ok(None)
}

async fn import(i: &Invocation, client: &mut Client, format: &str) -> Result<CliOutput, CliError> {
    let (_, parsed) = load(i, format)?;
    let plan = client
        .account()
        .preview_account_import(&parsed, i.text("select") == Some("all"))
        .await?;
    if let Some(output) = gate(i, &plan).await? {
        return Ok(output);
    }
    let result = client.account().run_account_import(&parsed, &plan).await?;
    print(i, &result)
}

/// `--api-key` variant: the same flow signed with the explicit API key and
/// encrypted with the API-key-wrapped account key. `import-chat` stays
/// session-only because its backend route only accepts cookie credentials.
pub(super) async fn execute_key(
    i: &Invocation,
    client: &mut OpenMates,
) -> Result<CliOutput, CliError> {
    let path = path(i);
    let Some(format) = path.strip_prefix("account import ") else {
        return Err(chat_import_requires_session(i));
    };
    let (_, parsed) = load(i, format)?;
    let plan = client
        .preview_account_import(&parsed, i.text("select") == Some("all"))
        .await?;
    if let Some(output) = gate(i, &plan).await? {
        return Ok(output);
    }
    let result = client.run_account_import(&parsed, &plan).await?;
    print(i, &result)
}

fn js(value: &Value, fallback: &str) -> String {
    match value {
        Value::Null => fallback.into(),
        Value::String(s) => s.clone(),
        other => other.to_string(),
    }
}

/// npm `printAccountImportPreview`.
pub(super) fn print(i: &Invocation, result: &Value) -> Result<CliOutput, CliError> {
    if i.boolean("json") {
        return CliOutput::json(result);
    }
    let parsed = &result["parsed"];
    let preview = &result["preview"];
    let mut out = format!(
        "Account import preview ({}): {} chat(s) parsed\n",
        js(&result["source"], "undefined"),
        js(&parsed["chat_count"], "0")
    );
    out.push_str(&format!(
        "Default selection: {} / max {}\n",
        js(&preview["default_selection_count"], "0"),
        js(&preview["max_batch_count"], "0")
    ));
    if let Some(domains) = parsed["skipped_domains"]
        .as_array()
        .filter(|d| !d.is_empty())
    {
        let names: Vec<String> = domains.iter().map(|d| js(d, "")).collect();
        out.push_str(&format!(
            "Skipped unsupported domains: {}\n",
            names.join(", ")
        ));
    }
    if let Some(duplicates) = preview["duplicate_fingerprints"]
        .as_array()
        .filter(|d| !d.is_empty())
    {
        out.push_str(&format!("Duplicate warnings: {}\n", duplicates.len()));
    }
    if preview["can_import"] == Value::Bool(false) {
        out.push_str(&format!(
            "Import blocked: {}\n",
            js(&preview["reason"], "unknown")
        ));
    }
    Ok(text_output(out))
}

#[cfg(test)]
#[path = "imports_tests.rs"]
mod tests;
