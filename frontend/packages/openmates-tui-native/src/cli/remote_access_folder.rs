//! `openmates remote-access new-projects-folder set|show|clear`: the machine
//! owner's one folder inside which this remote-access host may create new
//! Project folders. Thin CLI shell: it validates the path shape and calls the
//! core store (`openmates_sdk::source_host::{load,save}_new_projects_dir`).
//! Local only (no login). Unset means the host does not offer creation.
use super::{CliError, CliOutput, Invocation};
use openmates_sdk::source_host::{load_new_projects_dir, save_new_projects_dir};
use serde_json::json;
use std::path::{Path, PathBuf};

const FLAGS: &[&str] = &["json", "profile"];

fn contract(code: &'static str, message: impl Into<String>) -> CliError {
    CliError::Contract {
        code,
        message: message.into(),
    }
}

/// True for the three `remote-access new-projects-folder` commands.
pub(super) fn supported(i: &Invocation) -> bool {
    matches!(
        i.command_path().as_str(),
        "remote-access new-projects-folder set"
            | "remote-access new-projects-folder show"
            | "remote-access new-projects-folder clear"
    )
}

/// Absolute path of an existing directory that is not a symlink.
fn validated_folder(raw: &str) -> Result<PathBuf, CliError> {
    let path = Path::new(raw);
    if !path.is_absolute() {
        return Err(contract(
            "invalid_new_projects_folder",
            "The folder must be an absolute path.",
        ));
    }
    let meta = std::fs::symlink_metadata(path)
        .map_err(|_| contract("invalid_new_projects_folder", "The folder does not exist."))?;
    if meta.file_type().is_symlink() {
        return Err(contract(
            "invalid_new_projects_folder",
            "The folder must not be a symlink.",
        ));
    }
    if !meta.is_dir() {
        return Err(contract(
            "invalid_new_projects_folder",
            "The path is not a directory.",
        ));
    }
    Ok(path.to_path_buf())
}

fn folder_output(
    i: &Invocation,
    folder: Option<&Path>,
    changed: &str,
) -> Result<CliOutput, CliError> {
    let shown = folder.map(|p| p.to_string_lossy().into_owned());
    if i.boolean("json") {
        return CliOutput::json(&json!({"new_projects_folder": shown}));
    }
    Ok(CliOutput::text(match (changed, shown) {
        ("", Some(path)) => path,
        ("", None) => "Not set. This host does not create new Project folders.".to_owned(),
        (action, Some(path)) => format!("New-Projects folder {action}: {path}"),
        (action, None) => format!(
            "New-Projects folder {action}. This host no longer creates new Project folders."
        ),
    }))
}

/// Runs before credentials are opened: the setting is a local host file.
pub(super) fn public(i: &Invocation) -> Option<Result<CliOutput, CliError>> {
    supported(i).then(|| run(i))
}

fn run(i: &Invocation) -> Result<CliOutput, CliError> {
    if let Some(flag) = i.flags.keys().find(|k| !FLAGS.contains(&k.as_str())) {
        return Err(CliError::Invalid(format!(
            "Unknown option --{flag} for remote-access new-projects-folder."
        )));
    }
    let state = super::remote_access::state_dir(i)?;
    let store = |e: openmates_sdk::source_host::HostError| CliError::Invalid(e.message);
    match i.command_path().rsplit(' ').next().unwrap_or_default() {
        "set" => {
            let raw = i
                .positionals
                .first()
                .map(String::as_str)
                .filter(|v| !v.trim().is_empty());
            let folder = validated_folder(raw.ok_or_else(|| {
                contract("command_failed", "Missing <absolute path>. Use: remote-access new-projects-folder set <absolute path>")
            })?)?;
            save_new_projects_dir(&state, Some(&folder)).map_err(store)?;
            folder_output(i, Some(&folder), "set")
        }
        "clear" => {
            save_new_projects_dir(&state, None).map_err(store)?;
            folder_output(i, None, "cleared")
        }
        _ => folder_output(
            i,
            load_new_projects_dir(&state).map_err(store)?.as_deref(),
            "",
        ),
    }
}

#[cfg(test)]
#[path = "remote_access_folder_tests.rs"]
mod tests;
