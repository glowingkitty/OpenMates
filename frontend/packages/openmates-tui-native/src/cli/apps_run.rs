//! Baseline generic-run refusal and one bounded explicit-key generated command.
//! Requests/privacy/auth/cancellation stay in the existing shared Rust SDK.
use super::{CliError, CliOutput, Invocation};
use crate::error::Error;
use openmates_sdk::sdk::OpenMates;
use serde_json::{Value, json};
use tokio_util::sync::CancellationToken;
const REFUSAL: &str = "Generic app-skill CLI execution is not supported.\n\nUse an explicit typed command such as `openmates tasks ...`, `openmates workflows ...`, or another app-specific command.\nInspect app metadata with `openmates apps list`, `openmates apps info <app-id>`, or `openmates apps skill-info <app-id> <skill-id>`.\n\n";
pub(super) fn public(i: &Invocation) -> Option<Result<CliOutput, CliError>> {
    (i.command_path() == "apps run").then(|| {
        Ok(CliOutput {
            stdout: String::new(),
            stderr: REFUSAL.into(),
            exit_code: 1,
        })
    })
}
fn unsupported(i: &Invocation, reason: &str) -> CliError {
    CliError::Unsupported {
        command: i.command_path(),
        reason: reason.into(),
    }
}
fn argument(message: impl Into<String>) -> CliError {
    CliError::Contract {
        code: "command_failed",
        message: message.into(),
    }
}
fn input(i: &Invocation) -> Result<Value, CliError> {
    super::handlers::flags(i, &["input", "library", "question", "no-download"])?;
    if let Some(raw) = i.text("input") {
        let value: Value = serde_json::from_str(raw)
            .map_err(|_| argument("Invalid --input JSON: input must be a JSON object"))?;
        if !value.is_object() {
            return Err(argument(
                "Invalid --input JSON: input must be a JSON object",
            ));
        }
        return Ok(value);
    }
    // Maintained CLI positional values take precedence over named flags.
    let library = i
        .positionals
        .first()
        .map(String::as_str)
        .or_else(|| i.text("library"));
    let joined = i
        .positionals
        .iter()
        .skip(1)
        .cloned()
        .collect::<Vec<_>>()
        .join(" ");
    let question = if i.positionals.len() > 1 {
        Some(joined.as_str())
    } else {
        i.text("question")
    };
    let mut missing = vec![];
    if library.is_none_or(str::is_empty) {
        missing.push("--library");
    }
    if question.is_none_or(str::is_empty) {
        missing.push("--question");
    }
    if !missing.is_empty() {
        return Err(argument(format!(
            "Missing required option(s): {}\n\nRun: openmates apps code get_docs --help",
            missing.join(", ")
        )));
    }
    Ok(json!({"library":library.unwrap_or(""),"question":question.unwrap_or("")}))
}
pub async fn execute_sdk_apps(
    i: &Invocation,
    client: &mut OpenMates,
    cancel: CancellationToken,
) -> Result<CliOutput, CliError> {
    if let Some(result) = public(i) {
        return result;
    }
    if i.command_path() != "apps code get_docs" {
        return Err(unsupported(
            i,
            "Only the declared code/get_docs explicit-key JSON command is ported in this adapter; other app-skill routes remain required.",
        ));
    }
    if !i.boolean("json") {
        return Err(unsupported(
            i,
            "Explicit-key code/get_docs currently requires --json; full human rendering and generated-artifact handling remain required.",
        ));
    }
    let input = input(i)?;
    if cancel.is_cancelled() {
        return Err(Error::Cancelled.into());
    }
    client.set_operation_cancel(cancel.clone());
    let result = client.apps().code().get_docs(input).await;
    if cancel.is_cancelled() {
        return Err(Error::Cancelled.into());
    }
    CliOutput::json(&result?)
}
#[cfg(test)]
#[path = "apps_run_tests.rs"]
mod tests;
