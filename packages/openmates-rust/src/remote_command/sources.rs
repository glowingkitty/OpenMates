//! Read-only view of the attached local source store written by the npm
//! `remote-access` command (`remote-sources.json`, npm `listRemoteAccessSources`).
//! This module never creates, attaches or modifies sources.
use super::{RemoteCommandError, RemoteCommandResult as R, io_error};
use serde_json::Value;
use std::path::Path;

pub const REMOTE_SOURCES_FILE: &str = "remote-sources.json";
const MAX_SOURCE_ID_LENGTH: usize = 128;

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct RemoteAccessSource {
    pub source_id: String,
    pub project_id: Option<String>,
    pub source_type: String,
    pub root_path: String,
    pub display_name: String,
    pub status: String,
}

pub fn list_remote_access_sources(state_dir: &Path) -> R<Vec<RemoteAccessSource>> {
    let path = state_dir.join(REMOTE_SOURCES_FILE);
    if !path.exists() {
        return Ok(vec![]);
    }
    read_sources(&path).map_err(|error| {
        RemoteCommandError::failed(format!(
            "Failed to read remote source store at {}: {}",
            path.display(),
            error.message
        ))
    })
}

fn read_sources(path: &Path) -> R<Vec<RemoteAccessSource>> {
    let bytes = std::fs::read(path).map_err(|error| io_error("open", path, &error))?;
    let parsed: Value = serde_json::from_str(&String::from_utf8_lossy(&bytes))
        .map_err(|error| RemoteCommandError::failed(error.to_string()))?;
    let Some(Value::Array(sources)) = parsed.get("sources") else {
        return Err(RemoteCommandError::failed(
            "Remote source store is missing the sources array",
        ));
    };
    sources
        .iter()
        .enumerate()
        .map(|(index, source)| source_record(source, index))
        .collect()
}

fn source_record(value: &Value, index: usize) -> R<RemoteAccessSource> {
    let Some(source) = value.as_object() else {
        return Err(RemoteCommandError::failed(format!(
            "Remote source record {index} is not an object"
        )));
    };
    let text = |name: &str| source.get(name).and_then(Value::as_str);
    let invalid = || RemoteCommandError::failed(format!("Remote source record {index} is invalid"));
    let project_id = match source.get("projectId") {
        None => None,
        Some(Value::String(id)) => Some(id.clone()),
        Some(_) => return Err(invalid()),
    };
    let source_type = text("sourceType").filter(|kind| {
        [
            "local_folder",
            "local_git_repository",
            "remote_folder",
            "remote_git_repository",
        ]
        .contains(kind)
    });
    let status = text("status").filter(|status| {
        ["connected", "offline", "permission_required", "revoked"].contains(status)
    });
    let numbers = ["createdAt", "updatedAt"]
        .iter()
        .all(|name| source.get(*name).is_some_and(Value::is_number));
    let (
        Some(source_id),
        Some(source_type),
        Some(root_path),
        Some(display_name),
        Some(_cache_path),
        Some(status),
        true,
    ) = (
        text("sourceId"),
        source_type,
        text("rootPath"),
        text("displayName"),
        text("cachePath"),
        status,
        numbers,
    )
    else {
        return Err(invalid());
    };
    if !safe_source_id(source_id) {
        return Err(RemoteCommandError::failed(
            "Remote source ID must be 1-128 characters and contain only letters, numbers, dot, underscore, or hyphen",
        ));
    }
    Ok(RemoteAccessSource {
        source_id: source_id.to_owned(),
        project_id,
        source_type: source_type.to_owned(),
        root_path: root_path.to_owned(),
        display_name: display_name.to_owned(),
        status: status.to_owned(),
    })
}

/// `/^[A-Za-z0-9][A-Za-z0-9._-]*$/`, at most 128 characters.
fn safe_source_id(value: &str) -> bool {
    let bytes = value.as_bytes();
    !bytes.is_empty()
        && bytes.len() <= MAX_SOURCE_ID_LENGTH
        && bytes[0].is_ascii_alphanumeric()
        && bytes[1..]
            .iter()
            .all(|b| b.is_ascii_alphanumeric() || b"._-".contains(b))
}

/// Exactly one attached source of this Project, optionally narrowed by an
/// exact source ID and/or exact stored root path (npm candidate filter).
pub fn select_remote_command_source(
    sources: Vec<RemoteAccessSource>,
    project_id: &str,
    source_id: Option<&str>,
    root_path: Option<&str>,
) -> R<RemoteAccessSource> {
    let mut candidates = sources
        .into_iter()
        .filter(|source| {
            source.project_id.as_deref() == Some(project_id)
                && source_id.is_none_or(|id| source.source_id == id)
                && root_path.is_none_or(|path| source.root_path == path)
        })
        .collect::<Vec<_>>();
    if candidates.len() != 1 {
        return Err(RemoteCommandError::contract(
            "source_selection_required",
            "Select one attached local source with --source <source-id> or --path <folder>.",
        ));
    }
    candidates
        .pop()
        .ok_or_else(|| RemoteCommandError::failed("Source selection failed."))
}
