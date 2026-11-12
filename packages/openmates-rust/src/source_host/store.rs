//! Local remote-source association store, byte-compatible with the npm CLI's
//! `<state>/remote-sources.json` (`remoteAccess.ts` `startRemoteAccessSource`,
//! `listRemoteAccessSources`, `saveRemoteAccessSources`): `{"sources":[...]}`
//! pretty-printed with two spaces, the state directory `0700` and the file
//! `0600`. Records keep npm's camelCase keys and field order; unknown fields
//! are preserved so either CLI can rewrite the file. The core never reads
//! environment variables: callers pass the resolved state directory.

use super::{HostError, HostResult};
use serde::{Deserialize, Serialize};
use serde_json::{Map, Value};
use std::os::unix::fs::PermissionsExt;
use std::path::{Path, PathBuf};

const STORE_FILE: &str = "remote-sources.json";
const SETTINGS_FILE: &str = "host-settings.json";
const MAX_SOURCE_ID_LENGTH: usize = 128;
const MAX_PROFILE_LENGTH: usize = 64;

/// One attached local source (npm `RemoteAccessSourceRecord`).
#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct StoredRemoteSource {
    /// Opaque source ID shared with the backend.
    pub source_id: String,
    /// Owning Project, when bound.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub project_id: Option<String>,
    /// `local_folder`, `local_git_repository`, `remote_folder` or `remote_git_repository`.
    pub source_type: String,
    /// Canonical approved root.
    pub root_path: String,
    /// Local display name (the basename by default).
    pub display_name: String,
    /// Private cache directory for this source.
    pub cache_path: String,
    /// `connected`, `offline`, `permission_required` or `revoked`.
    pub status: String,
    /// Unix seconds.
    pub created_at: u64,
    /// Unix seconds.
    pub updated_at: u64,
    /// Fields written by newer CLIs, kept verbatim.
    #[serde(flatten)]
    pub extra: Map<String, Value>,
}

/// npm `resolveStateDir`: an absolute `OPENMATES_STATE_DIR`, else
/// `~/.openmates` or `~/.openmates/profiles/<profile>`. Callers read the
/// environment; this function only applies the rule.
///
/// # Errors
/// `operation_failed` for a relative state dir, a missing home or an invalid profile.
pub fn npm_state_dir(
    state_dir: Option<&str>,
    profile: Option<&str>,
    home: Option<&Path>,
) -> HostResult<PathBuf> {
    if let Some(dir) = state_dir.map(str::trim).filter(|d| !d.is_empty()) {
        if !Path::new(dir).is_absolute() {
            return Err(HostError::failed(
                "The state directory must be an absolute path.",
            ));
        }
        return Ok(PathBuf::from(dir));
    }
    let home = home.ok_or_else(|| {
        HostError::failed("The home directory is unavailable; set an explicit state directory.")
    })?;
    let Some(profile) = profile.map(str::trim).filter(|p| !p.is_empty()) else {
        return Ok(home.join(".openmates"));
    };
    let bytes = profile.as_bytes();
    let valid = bytes.len() <= MAX_PROFILE_LENGTH
        && (bytes[0].is_ascii_lowercase() || bytes[0].is_ascii_digit())
        && bytes[1..]
            .iter()
            .all(|b| b.is_ascii_lowercase() || b.is_ascii_digit() || *b == b'-');
    if !valid {
        return Err(HostError::failed(
            "Profile names use lowercase letters, digits and hyphens (max 64).",
        ));
    }
    Ok(home.join(".openmates").join("profiles").join(profile))
}

/// npm `assertSafeSourceId`.
///
/// # Errors
/// `operation_failed` for an unsafe ID.
pub(crate) fn assert_safe_source_id(id: &str) -> HostResult<()> {
    let mut chars = id.chars();
    let first_ok = chars.next().is_some_and(|c| c.is_ascii_alphanumeric());
    if !first_ok
        || id.len() > MAX_SOURCE_ID_LENGTH
        || !chars.all(|c| c.is_ascii_alphanumeric() || matches!(c, '.' | '_' | '-'))
    {
        return Err(HostError::failed(
            "Remote source ID must be 1-128 characters and contain only letters, numbers, dot, underscore, or hyphen",
        ));
    }
    Ok(())
}

/// `<state>/remote-cache/<source_id>`.
///
/// # Errors
/// `operation_failed` for an unsafe source ID.
pub fn remote_cache_path(state_dir: &Path, source_id: &str) -> HostResult<PathBuf> {
    assert_safe_source_id(source_id)?;
    Ok(state_dir.join("remote-cache").join(source_id))
}

/// npm `remoteAccessSourceType`.
pub fn remote_source_type(root: &Path) -> &'static str {
    if root.join(".git").exists() {
        "local_git_repository"
    } else {
        "local_folder"
    }
}

/// Read every record, validating like npm `assertRemoteAccessSourceRecord`.
///
/// # Errors
/// `operation_failed` naming the store path for unreadable or invalid content.
pub fn load_remote_sources(state_dir: &Path) -> HostResult<Vec<StoredRemoteSource>> {
    let path = state_dir.join(STORE_FILE);
    let text = match std::fs::read_to_string(&path) {
        Ok(text) => text,
        Err(e) if e.kind() == std::io::ErrorKind::NotFound => return Ok(Vec::new()),
        Err(e) => return Err(store_error(&path, &e.to_string())),
    };
    let parsed: Value = serde_json::from_str(&text).map_err(|e| store_error(&path, &e.to_string()))?;
    let rows = parsed["sources"]
        .as_array()
        .ok_or_else(|| store_error(&path, "Remote source store is missing the sources array"))?;
    let mut sources = Vec::with_capacity(rows.len());
    for (index, row) in rows.iter().enumerate() {
        let record: StoredRemoteSource = serde_json::from_value(row.clone()).map_err(|_| {
            store_error(&path, &format!("Remote source record {index} is invalid"))
        })?;
        let valid = matches!(
            record.status.as_str(),
            "connected" | "offline" | "permission_required" | "revoked"
        ) && matches!(
            record.source_type.as_str(),
            "local_folder" | "local_git_repository" | "remote_folder" | "remote_git_repository"
        );
        if !valid {
            return Err(store_error(
                &path,
                &format!("Remote source record {index} is invalid"),
            ));
        }
        assert_safe_source_id(&record.source_id).map_err(|e| store_error(&path, &e.message))?;
        sources.push(record);
    }
    Ok(sources)
}

fn store_error(path: &Path, detail: &str) -> HostError {
    HostError::failed(format!(
        "Failed to read remote source store at {}: {detail}",
        path.display()
    ))
}

/// Rewrite the store (`0600`) inside a `0700` state directory.
///
/// # Errors
/// `operation_failed` on IO failure.
pub fn save_remote_sources(state_dir: &Path, sources: &[StoredRemoteSource]) -> HostResult<()> {
    private_directory(state_dir)?;
    let body = serde_json::to_string_pretty(&serde_json::json!({ "sources": sources }))
        .map_err(|e| HostError::failed(e.to_string()))?;
    write_private_file(&state_dir.join(STORE_FILE), format!("{body}\n").as_bytes())
}

/// npm `startRemoteAccessSource`: replace the record with this source ID and
/// create its `0700` cache directory.
///
/// # Errors
/// `operation_failed` for an unsafe ID or IO failure.
pub fn upsert_remote_source(
    state_dir: &Path,
    record: StoredRemoteSource,
) -> HostResult<StoredRemoteSource> {
    assert_safe_source_id(&record.source_id)?;
    let mut sources = load_remote_sources(state_dir)?;
    sources.retain(|s| s.source_id != record.source_id);
    sources.push(record.clone());
    save_remote_sources(state_dir, &sources)?;
    let cache = PathBuf::from(&record.cache_path);
    std::fs::create_dir_all(&cache).map_err(|e| HostError::failed(e.to_string()))?;
    std::fs::set_permissions(&cache, std::fs::Permissions::from_mode(0o700))
        .map_err(|e| HostError::failed(e.to_string()))?;
    Ok(record)
}

/// `mkdir -p` then `chmod 0700`.
///
/// # Errors
/// `operation_failed` on IO failure or when the path is not a directory.
pub(crate) fn private_directory(path: &Path) -> HostResult<()> {
    std::fs::create_dir_all(path).map_err(|e| HostError::failed(e.to_string()))?;
    std::fs::set_permissions(path, std::fs::Permissions::from_mode(0o700))
        .map_err(|e| HostError::failed(e.to_string()))?;
    if !std::fs::metadata(path).is_ok_and(|m| m.is_dir()) {
        return Err(HostError::failed("Private state path is not a directory"));
    }
    Ok(())
}

/// Atomic `0600` write: exclusive no-follow temp file, fsync, rename.
///
/// # Errors
/// `operation_failed` on IO failure.
pub(crate) fn write_private_file(path: &Path, bytes: &[u8]) -> HostResult<()> {
    use rustix::fs::{Mode, OFlags};
    use std::io::Write;
    let temp = path.with_extension(format!(
        "{}.{}.tmp",
        std::process::id(),
        uuid::Uuid::new_v4().simple()
    ));
    let fd = rustix::fs::open(
        &temp,
        OFlags::CREATE | OFlags::EXCL | OFlags::WRONLY | OFlags::NOFOLLOW | OFlags::CLOEXEC,
        Mode::from_raw_mode(0o600),
    )
    .map_err(|e| HostError::failed(format!("Private write failed: {e}")))?;
    let mut file = std::fs::File::from(fd);
    let result = file
        .write_all(bytes)
        .and_then(|()| file.sync_all())
        .and_then(|()| std::fs::set_permissions(&temp, std::fs::Permissions::from_mode(0o600)))
        .and_then(|()| std::fs::rename(&temp, path));
    if let Err(error) = result {
        // The rename did not consume the temp file; remove it before reporting.
        let _ = std::fs::remove_file(&temp);
        return Err(HostError::failed(format!("Private write failed: {error}")));
    }
    Ok(())
}

/// The machine owner's "new Projects" folder from `<state>/host-settings.json`
/// (`{"new_projects_dir": "/abs/path"}`), or `None` when unset. Unset means the
/// host does not advertise `create_source`.
///
/// # Errors
/// `operation_failed` for an unreadable or malformed settings file or a
/// relative path.
pub fn load_new_projects_dir(state_dir: &Path) -> HostResult<Option<PathBuf>> {
    let path = state_dir.join(SETTINGS_FILE);
    let text = match std::fs::read_to_string(&path) {
        Ok(text) => text,
        Err(e) if e.kind() == std::io::ErrorKind::NotFound => return Ok(None),
        Err(e) => return Err(HostError::failed(format!("Host settings unreadable: {e}"))),
    };
    let parsed: Value = serde_json::from_str(&text)
        .map_err(|e| HostError::failed(format!("Host settings are invalid: {e}")))?;
    match parsed.get("new_projects_dir") {
        None | Some(Value::Null) => Ok(None),
        Some(Value::String(dir)) if Path::new(dir).is_absolute() => Ok(Some(PathBuf::from(dir))),
        Some(_) => Err(HostError::failed(
            "The new-Projects folder must be an absolute path.",
        )),
    }
}

/// Set (`Some`) or clear (`None`) the new-Projects folder, keeping any other
/// settings keys. Only the machine owner calls this (CLI configuration); a
/// requester can never change it.
///
/// # Errors
/// `operation_failed` for a relative path or IO failure.
pub fn save_new_projects_dir(state_dir: &Path, dir: Option<&Path>) -> HostResult<()> {
    if dir.is_some_and(|d| !d.is_absolute()) {
        return Err(HostError::failed(
            "The new-Projects folder must be an absolute path.",
        ));
    }
    let path = state_dir.join(SETTINGS_FILE);
    let mut settings: Map<String, Value> = match std::fs::read_to_string(&path) {
        Ok(text) => serde_json::from_str(&text)
            .map_err(|e| HostError::failed(format!("Host settings are invalid: {e}")))?,
        Err(e) if e.kind() == std::io::ErrorKind::NotFound => Map::new(),
        Err(e) => return Err(HostError::failed(format!("Host settings unreadable: {e}"))),
    };
    match dir {
        Some(dir) => {
            settings.insert(
                "new_projects_dir".into(),
                Value::String(dir.to_string_lossy().into_owned()),
            );
        }
        None => {
            settings.remove("new_projects_dir");
        }
    }
    private_directory(state_dir)?;
    let body = serde_json::to_string_pretty(&Value::Object(settings))
        .map_err(|e| HostError::failed(e.to_string()))?;
    write_private_file(&path, format!("{body}\n").as_bytes())
}
