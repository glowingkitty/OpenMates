//! `settings account export [start]` (npm runAccountExport): start the job,
//! download and secret-scan every chunk (cancelling the job on failure),
//! complete it (accepting a partial export only with --accept-partial) and
//! write the local archive.
use super::export_archive;
use super::settings_more::text_output;
use super::{CliError, CliOutput, Invocation, handlers, path};
use crate::client::Client;
use openmates_sdk::account::AccountExportStart;
use serde_json::{Value, json};

pub(super) fn supported(i: &Invocation) -> bool {
    matches!(path(i).as_str(), "account export" | "account export start")
        && i.positionals.is_empty()
}
fn fail(message: impl Into<String>) -> CliError {
    CliError::Invalid(message.into())
}

pub(super) async fn execute(i: &Invocation, client: &mut Client) -> Result<CliOutput, CliError> {
    handlers::flags(
        i,
        &[
            "domains",
            "filters",
            "format",
            "include-advanced-metadata",
            "accept-partial",
            "password",
            "output",
        ],
    )?;
    let filters = match i.text("filters") {
        Some(raw) => serde_json::from_str::<Value>(raw)
            .map_err(|e| fail(format!("Invalid JSON for --filters: {e}")))?,
        None => json!({}),
    };
    let domains = i.text("domains").and_then(|raw| {
        let items = raw
            .split(',')
            .map(str::trim)
            .filter(|s| !s.is_empty())
            .map(str::to_owned)
            .collect::<Vec<_>>();
        (!items.is_empty()).then_some(items)
    });
    let directory = i.text("format") == Some("directory");
    let password = i.text("password").filter(|p| !p.is_empty());
    if password.is_some() && directory {
        return Err(fail(
            "Password-protected account export is only supported for zip format.",
        ));
    }
    let mut account = client.account();
    let started = account
        .start_account_export(AccountExportStart {
            domains,
            filters,
            directory_format: directory,
            include_advanced_metadata: i.boolean("include-advanced-metadata"),
        })
        .await?;
    let export_id = started["export"]["export_id"]
        .as_str()
        .map(str::to_owned)
        .unwrap_or_default();
    let manifest = account.account_export_manifest(Some(&export_id)).await?;
    let listed = account.account_export_chunks(&export_id).await?;
    let mut chunks = vec![];
    for chunk in listed["chunks"].as_array().cloned().unwrap_or_default() {
        let chunk_id = match &chunk["chunk_id"] {
            Value::String(id) => id.clone(),
            Value::Null => String::new(),
            other => other.to_string(),
        };
        let downloaded = if chunk_id.is_empty() {
            Ok(chunk.clone())
        } else {
            account
                .account_export_chunk(&export_id, &chunk_id)
                .await
                .map_err(CliError::from)
        };
        match downloaded.and_then(|d| {
            export_archive::assert_payload_safe(&d, "$export")
                .map(|()| d)
                .map_err(fail)
        }) {
            Ok(downloaded) => chunks.push(downloaded),
            Err(error) => {
                // npm cancels the server job before surfacing the failure.
                let _ = account.cancel_account_export(&export_id).await;
                return Err(error);
            }
        }
    }
    let mut completed = account.complete_account_export(&export_id).await?;
    if completed["export"]["status"] == "partial" {
        if !i.boolean("accept-partial") {
            return Err(fail(format!(
                "Account export {export_id} is partial. Re-run with --accept-partial to accept it, or inspect/cancel the job first."
            )));
        }
        completed = account.accept_partial_account_export(&export_id).await?;
    }
    let mut bundle = json!({
        "export":completed["export"],
        "manifest":export_archive::sanitize_manifest(&manifest["manifest"]).map_err(fail)?,
        "chunks":chunks,
    });
    let archive =
        export_archive::write(&bundle, directory, password, i.text("output")).map_err(fail)?;
    if i.boolean("json") {
        bundle["archive"] = archive;
        return CliOutput::json(&bundle);
    }
    let mut stdout = format!(
        "Account export {} {}\n",
        bundle["export"]["export_id"].as_str().unwrap_or(""),
        bundle["export"]["status"].as_str().unwrap_or("unknown")
    );
    if let Some(output) = archive["output"].as_str() {
        stdout.push_str(&format!("Wrote {output}\n"));
    }
    Ok(text_output(stdout))
}

#[cfg(test)]
#[path = "export_start_tests.rs"]
mod tests;
