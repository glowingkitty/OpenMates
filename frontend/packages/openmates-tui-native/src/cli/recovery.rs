//! `recovery [full-sync|validate|restore]` work-recovery projection (npm parity).
//! Projects one explicitly named Project's Plans/Tasks into `<root>/<id>.yml`,
//! validates such a file, and restores it into an empty Project. This never
//! triggers chat or account sync. Document rules and network operations live in
//! `openmates_sdk::work::recovery` and the Plans namespace; this adapter owns
//! flags, file IO and output.
use super::super::{CliError, CliOutput, Invocation, handlers};
use crate::client::Client;
use openmates_sdk::work::recovery::{self as projection, RecoveryError};
use serde_json::{Value, json};
use tokio_util::sync::CancellationToken;

const USAGE: &str = "Usage: openmates recovery full-sync --project <project-id> --root <external-root>; openmates recovery validate --file <path>; openmates recovery restore --file <path> --dry-run|--confirm-restore";
const UNKNOWN: &str = "Unknown recovery command. Use full-sync, validate, or restore.";
const FLAGS: &[&str] = &["project", "root", "recovery-root", "file", "dry-run", "confirm-restore"];
const ROOT_ENV: &str = "OPENMATES_WORK_RECOVERY_ROOT";

pub(super) fn supported(invocation: &Invocation) -> bool {
    matches!(
        invocation.command_path().as_str(),
        "recovery" | "recovery full-sync" | "recovery validate" | "recovery restore"
    )
}

/// Bare `recovery` (usage or unknown-subcommand error) and the file-only
/// `recovery validate` need no credentials.
pub(super) fn is_public(invocation: &Invocation) -> bool {
    matches!(invocation.command_path().as_str(), "recovery" | "recovery validate")
}

pub(super) fn public(invocation: &Invocation) -> Option<Result<CliOutput, CliError>> {
    match invocation.command_path().as_str() {
        "recovery" => Some(bare(invocation)),
        "recovery validate" => Some(validate(invocation)),
        _ => None,
    }
}

pub(super) async fn execute(
    invocation: &Invocation,
    client: &mut Client,
    cancel: CancellationToken,
) -> Result<CliOutput, CliError> {
    let operation = async {
        match invocation.command_path().as_str() {
            "recovery full-sync" => full_sync(invocation, client).await,
            "recovery restore" => restore(invocation, client).await,
            "recovery validate" => validate(invocation),
            _ => bare(invocation),
        }
    };
    tokio::select! {
        result = operation => result,
        () = cancel.cancelled() => Err(CliError::Client(openmates_sdk::Error::Cancelled)),
    }
}

fn bare(invocation: &Invocation) -> Result<CliOutput, CliError> {
    handlers::flags(invocation, FLAGS)?;
    if invocation.positionals.is_empty() {
        Ok(CliOutput::text(USAGE))
    } else {
        Err(CliError::Invalid(UNKNOWN.into()))
    }
}

fn failure(error: RecoveryError) -> CliError {
    match error {
        RecoveryError::Invalid(message) => failed(message),
        RecoveryError::Client(error) => CliError::Client(error),
    }
}

/// Runtime failures exit 1 like npm's thrown errors; usage errors stay Invalid.
fn failed(message: String) -> CliError {
    CliError::Contract { code: "command_failed", message }
}

/// npm `requiredStringFlag`: a trimmed nonempty value or `Missing <label>.`.
fn required(value: Option<&str>, label: &str) -> Result<String, CliError> {
    value
        .map(str::trim)
        .filter(|value| !value.is_empty())
        .map(str::to_owned)
        .ok_or_else(|| CliError::Invalid(format!("Missing {label}.")))
}

fn first_positional(invocation: &Invocation) -> Option<&str> {
    invocation.positionals.first().map(String::as_str)
}

/// Read, parse and validate a projection file without any credentials.
fn read_document(invocation: &Invocation) -> Result<Value, CliError> {
    let path = required(
        invocation.text("file").or_else(|| first_positional(invocation)),
        "--file <projection.yml>",
    )?;
    if !std::path::Path::new(&path).exists() {
        return Err(failed(format!("Recovery projection does not exist: {path}")));
    }
    let source = std::fs::read_to_string(&path)
        .map_err(|error| failed(format!("Recovery projection could not be read: {path}: {error}")))?;
    let document = projection::parse_document(&source).map_err(failure)?;
    projection::validate_document(&document).map_err(failure)?;
    Ok(document)
}

fn validate(invocation: &Invocation) -> Result<CliOutput, CliError> {
    handlers::flags(invocation, FLAGS)?;
    read_document(invocation)?;
    handlers::output(
        invocation,
        json!({"valid": true}),
        "Recovery projection is valid; no data was changed.".into(),
    )
}

async fn resolve_project(client: &mut Client, selector: &str) -> Result<String, CliError> {
    let project = client.projects().show(selector).await?;
    project["project_id"]
        .as_str()
        .map(str::to_owned)
        .ok_or(CliError::Client(openmates_sdk::Error::Protocol))
}

async fn full_sync(invocation: &Invocation, client: &mut Client) -> Result<CliOutput, CliError> {
    handlers::flags(invocation, FLAGS)?;
    let root = invocation
        .text("root")
        .or_else(|| invocation.text("recovery-root"))
        .map(str::to_owned)
        .or_else(|| std::env::var(ROOT_ENV).ok())
        .filter(|root| !root.is_empty())
        .ok_or_else(|| {
            CliError::Invalid(format!(
                "Recovery full-sync requires --root <external-root> or {ROOT_ENV}."
            ))
        })?;
    let selector = required(
        invocation.text("project").or_else(|| first_positional(invocation)),
        "--project <project-id>",
    )?;
    let project_id = resolve_project(client, &selector).await?;
    let document = client.plans().recovery_document(&project_id).await.map_err(failure)?;
    let path = projection::projection_path(&root, &project_id);
    projection::write_document_atomically(std::path::Path::new(&path), &document).map_err(failure)?;
    handlers::output(
        invocation,
        json!({"project_id": project_id, "path": path}),
        format!("Recovery projection synced: {path}"),
    )
}

async fn restore(invocation: &Invocation, client: &mut Client) -> Result<CliOutput, CliError> {
    handlers::flags(invocation, FLAGS)?;
    let document = read_document(invocation)?;
    let selector = required(invocation.text("project"), "--project <project-id>")?;
    let project_id = resolve_project(client, &selector).await?;
    if document["project"]["project_id"].as_str() != Some(project_id.as_str()) {
        return Err(failed(
            "Recovery restore --project must exactly match document.project.project_id.".into(),
        ));
    }
    if invocation.boolean("dry-run") {
        let report = client.plans().recovery_dry_run(&document, &project_id).await.map_err(failure)?;
        return CliOutput::json(&report);
    }
    if !invocation.boolean("confirm-restore") {
        return Err(CliError::Invalid(
            "Recovery restore requires --confirm-restore and an explicit --project. Use --dry-run first.".into(),
        ));
    }
    let applied = client.plans().recovery_restore(&document, &project_id).await.map_err(failure)?;
    handlers::output(
        invocation,
        json!({"restored": true, "project_id": project_id, "applied": applied}),
        format!("Recovery restored and verified: {project_id}"),
    )
}

#[cfg(test)]
#[path = "recovery_tests.rs"]
mod tests;
