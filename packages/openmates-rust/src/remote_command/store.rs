//! Private preset/resource grant stores (npm `remoteCommandClient.ts`
//! preset grants and `remoteCommandResourceGrants.ts`). Owner-only files,
//! atomic replace, refusal of symlinks and group/other-accessible stores.
use super::digest::{remote_command_preset_digest, resource_definition_digest};
use super::permissions::{
    RemoteCommandPermissions, environment_name, load_remote_command_permissions, profile_identifier,
};
use super::{RemoteCommandError, RemoteCommandResult as R, io_error};
use serde::Serialize;
use serde_json::{Map, Value, json};
use std::io::Write;
use std::path::{Path, PathBuf};

pub const PRESET_GRANTS_FILE: &str = "remote-command-preset-grants.json";
pub const RESOURCE_GRANTS_FILE: &str = "remote-command-resource-grants.json";

fn fail<T>(message: impl Into<String>) -> R<T> {
    Err(RemoteCommandError::failed(message))
}

/// Field order matches the npm grant object literal.
#[derive(Clone, Debug, PartialEq, Eq, Serialize)]
pub struct PresetGrant {
    pub project_id: String,
    pub preset_id: String,
    pub definition_digest: String,
    pub enabled: bool,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum ResourceKind {
    Writable,
    Network,
    Credential,
}
impl ResourceKind {
    pub fn parse(value: &str) -> Option<Self> {
        match value {
            "writable" => Some(Self::Writable),
            "network" => Some(Self::Network),
            "credential" => Some(Self::Credential),
            _ => None,
        }
    }
    pub fn as_str(self) -> &'static str {
        match self {
            Self::Writable => "writable",
            Self::Network => "network",
            Self::Credential => "credential",
        }
    }
}

#[derive(Serialize)]
struct StoreFile<'a, T: Serialize> {
    version: u8,
    grants: &'a [T],
}

#[cfg(unix)]
fn owner_only(metadata: &std::fs::Metadata) -> bool {
    use std::os::unix::fs::PermissionsExt;
    metadata.permissions().mode() & 0o077 == 0
}
/// Node reports group/world mode bits on non-Unix hosts, so npm refuses them too.
#[cfg(not(unix))]
fn owner_only(_: &std::fs::Metadata) -> bool {
    false
}
#[cfg(unix)]
fn set_mode(path: &Path, mode: u32) -> R<()> {
    use std::os::unix::fs::PermissionsExt;
    std::fs::set_permissions(path, std::fs::Permissions::from_mode(mode))
        .map_err(|error| io_error("chmod", path, &error))
}
#[cfg(not(unix))]
fn set_mode(_: &Path, _: u32) -> R<()> {
    Ok(())
}
fn private_directory(directory: &Path) -> R<()> {
    let mut builder = std::fs::DirBuilder::new();
    builder.recursive(true);
    #[cfg(unix)]
    {
        use std::os::unix::fs::DirBuilderExt;
        builder.mode(0o700);
    }
    builder
        .create(directory)
        .map_err(|error| io_error("mkdir", directory, &error))?;
    set_mode(directory, 0o700)
}

/// `Ok(None)` when absent (a dangling symlink counts as absent, like `existsSync`).
fn read_private_json(path: &Path, not_private: &str) -> R<Option<Value>> {
    if !path.exists() {
        return Ok(None);
    }
    let metadata =
        std::fs::symlink_metadata(path).map_err(|error| io_error("lstat", path, &error))?;
    if !metadata.file_type().is_file() || !owner_only(&metadata) {
        return fail(not_private);
    }
    let bytes = std::fs::read(path).map_err(|error| io_error("open", path, &error))?;
    serde_json::from_str(&String::from_utf8_lossy(&bytes))
        .map(Some)
        .map_err(|error| RemoteCommandError::failed(error.to_string()))
}

fn write_private_json<T: Serialize>(
    directory: &Path,
    file: &str,
    symlink_message: &str,
    grants: &[T],
) -> R<()> {
    private_directory(directory)?;
    let path = directory.join(file);
    if path.exists()
        && std::fs::symlink_metadata(&path)
            .map_err(|error| io_error("lstat", &path, &error))?
            .file_type()
            .is_symlink()
    {
        return fail(symlink_message);
    }
    let mut body = serde_json::to_string_pretty(&StoreFile { version: 1, grants })
        .map_err(|error| RemoteCommandError::failed(error.to_string()))?;
    body.push('\n');
    let mut temporary = path.clone().into_os_string();
    temporary.push(format!(".{}.tmp", std::process::id()));
    let temporary = PathBuf::from(temporary);
    let mut options = std::fs::OpenOptions::new();
    options.write(true).create_new(true);
    #[cfg(unix)]
    {
        use std::os::unix::fs::OpenOptionsExt;
        options.mode(0o600);
    }
    let mut handle = options
        .open(&temporary)
        .map_err(|error| io_error("open", &temporary, &error))?;
    handle
        .write_all(body.as_bytes())
        .and_then(|()| handle.sync_all())
        .map_err(|error| io_error("write", &temporary, &error))?;
    drop(handle);
    std::fs::rename(&temporary, &path).map_err(|error| io_error("rename", &temporary, &error))?;
    set_mode(&path, 0o600)
}

/// `/^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$/` (npm remoteCommandClient IDENTIFIER).
fn client_identifier(value: &str) -> bool {
    let bytes = value.as_bytes();
    !bytes.is_empty()
        && bytes.len() <= 128
        && bytes[0].is_ascii_alphanumeric()
        && bytes[1..]
            .iter()
            .all(|b| b.is_ascii_alphanumeric() || b"._:-".contains(b))
}
fn require_client_identifier<'a>(value: Option<&'a Value>, name: &str) -> R<&'a str> {
    value
        .and_then(Value::as_str)
        .filter(|value| client_identifier(value))
        .ok_or_else(|| RemoteCommandError::failed(format!("invalid {name}")))
}

pub fn list_preset_grants(state_dir: &Path) -> R<Vec<PresetGrant>> {
    let Some(store) = read_private_json(
        &state_dir.join(PRESET_GRANTS_FILE),
        "Remote command preset grant store is not private",
    )?
    else {
        return Ok(vec![]);
    };
    let Some(grants) = store.get("grants").and_then(Value::as_array) else {
        return fail("Invalid remote command preset grant store");
    };
    grants
        .iter()
        .map(|value| {
            let item = value
                .as_object()
                .ok_or_else(|| RemoteCommandError::failed("invalid remote command preset grant"))?;
            let project_id = require_client_identifier(item.get("project_id"), "project_id")?;
            let preset_id = require_client_identifier(item.get("preset_id"), "preset_id")?;
            let digest = item
                .get("definition_digest")
                .and_then(Value::as_str)
                .filter(|digest| {
                    digest.len() == 64 && digest.bytes().all(|b| b.is_ascii_hexdigit())
                })
                .ok_or_else(|| RemoteCommandError::failed("invalid preset definition digest"))?;
            if item.get("enabled") != Some(&Value::Bool(true)) {
                return fail("invalid preset grant state");
            }
            Ok(PresetGrant {
                project_id: project_id.to_owned(),
                preset_id: preset_id.to_owned(),
                definition_digest: digest.to_owned(),
                enabled: true,
            })
        })
        .collect()
}

fn write_preset_grants(state_dir: &Path, grants: &[PresetGrant]) -> R<()> {
    write_private_json(
        state_dir,
        PRESET_GRANTS_FILE,
        "Remote command preset grant store cannot be a symbolic link",
        grants,
    )
}

fn require_identity(project_id: &str, preset_id: &str) -> R<()> {
    if !client_identifier(project_id) {
        return fail("invalid project_id");
    }
    if !client_identifier(preset_id) {
        return fail("invalid preset_id");
    }
    Ok(())
}

/// Bind the preset's current definition digest for this Project.
pub fn enable_preset_grant(
    state_dir: &Path,
    project_id: &str,
    project_root: &Path,
    preset_id: &str,
) -> R<PresetGrant> {
    require_identity(project_id, preset_id)?;
    let permissions = load_remote_command_permissions(project_root)?.ok_or_else(|| {
        RemoteCommandError::failed("This Project source has no .openmates/permissions.yml file")
    })?;
    let grant = PresetGrant {
        project_id: project_id.to_owned(),
        preset_id: preset_id.to_owned(),
        definition_digest: remote_command_preset_digest(&permissions, preset_id)?,
        enabled: true,
    };
    let mut grants = list_preset_grants(state_dir)?
        .into_iter()
        .filter(|item| item.project_id != project_id || item.preset_id != preset_id)
        .collect::<Vec<_>>();
    grants.push(grant.clone());
    write_preset_grants(state_dir, &grants)?;
    Ok(grant)
}

pub fn disable_preset_grant(state_dir: &Path, project_id: &str, preset_id: &str) -> R<()> {
    require_identity(project_id, preset_id)?;
    let grants = list_preset_grants(state_dir)?
        .into_iter()
        .filter(|item| item.project_id != project_id || item.preset_id != preset_id)
        .collect::<Vec<_>>();
    write_preset_grants(state_dir, &grants)
}

/// Raw stored resource grants, preserved verbatim like npm `readStore`.
fn read_resource_store(state_dir: &Path) -> R<Vec<Value>> {
    let Some(store) = read_private_json(
        &state_dir.join(RESOURCE_GRANTS_FILE),
        "Remote command resource grant store is not private",
    )?
    else {
        return Ok(vec![]);
    };
    match store.get("grants") {
        Some(Value::Array(grants)) => Ok(grants.clone()),
        _ => fail("Invalid remote command resource grant store"),
    }
}
fn write_resource_store(state_dir: &Path, grants: &[Value]) -> R<()> {
    write_private_json(
        state_dir,
        RESOURCE_GRANTS_FILE,
        "Remote command resource grant store cannot be a symbolic link",
        grants,
    )
}
/// A string property of a stored grant. npm reads properties of a `null`
/// entry and throws, so that entry fails here too.
fn text_field<'a>(grant: &'a Value, name: &str) -> R<Option<&'a str>> {
    if grant.is_null() {
        return fail("Invalid remote command resource grant store");
    }
    Ok(grant.get(name).and_then(Value::as_str))
}
fn same_identity(
    grant: &Value,
    project_id: &str,
    source_id: &str,
    kind: &str,
    profile_id: &str,
) -> R<bool> {
    Ok(text_field(grant, "project_id")? == Some(project_id)
        && text_field(grant, "source_id")? == Some(source_id)
        && text_field(grant, "kind")? == Some(kind)
        && text_field(grant, "profile_id")? == Some(profile_id))
}

/// npm `listRemoteCommandResourceGrants`: credential mappings are reduced to
/// their sorted target names; local source variable names never leave here.
pub fn list_resource_grants(
    state_dir: &Path,
    project_id: Option<&str>,
    source_id: Option<&str>,
) -> R<Vec<Value>> {
    let mut result = vec![];
    for mut grant in read_resource_store(state_dir)? {
        if let Some(id) = project_id
            && text_field(&grant, "project_id")? != Some(id)
        {
            continue;
        }
        if let Some(id) = source_id
            && text_field(&grant, "source_id")? != Some(id)
        {
            continue;
        }
        if let Some(object) = grant.as_object_mut()
            && let Some(sources) = object.remove("environment_sources")
            && let Some(sources) = sources.as_object()
        {
            let mut names = sources.keys().cloned().collect::<Vec<_>>();
            names.sort();
            object.insert("environment_names".into(), json!(names));
        }
        result.push(grant);
    }
    Ok(result)
}

/// `!projectId || length > 128 || !sourceId || length > 128 || !ID.test(profileId)`
/// (lengths in UTF-16 code units, like JavaScript).
fn validate_resource_identity(project_id: &str, source_id: &str, profile_id: &str) -> R<()> {
    let too_long = |value: &str| value.is_empty() || value.encode_utf16().count() > 128;
    if too_long(project_id) || too_long(source_id) || !profile_identifier(profile_id) {
        return fail("Invalid remote command resource grant identity");
    }
    Ok(())
}
fn upsert(
    state_dir: &Path,
    grant: Map<String, Value>,
    project_id: &str,
    source_id: &str,
    kind: ResourceKind,
    profile_id: &str,
) -> R<()> {
    validate_resource_identity(project_id, source_id, profile_id)?;
    let mut grants = vec![];
    for item in read_resource_store(state_dir)? {
        if !same_identity(&item, project_id, source_id, kind.as_str(), profile_id)? {
            grants.push(item);
        }
    }
    grants.push(Value::Object(grant));
    write_resource_store(state_dir, &grants)
}
fn base_grant(
    project_id: &str,
    source_id: &str,
    kind: ResourceKind,
    profile_id: &str,
    digest: String,
) -> Map<String, Value> {
    let mut grant = Map::new();
    grant.insert("project_id".into(), json!(project_id));
    grant.insert("source_id".into(), json!(source_id));
    grant.insert("kind".into(), json!(kind.as_str()));
    grant.insert("profile_id".into(), json!(profile_id));
    grant.insert("definition_digest".into(), json!(digest));
    grant
}

/// `relative(parent, child)` is non-empty, not `..`-prefixed and not absolute.
fn is_inside(parent: &Path, child: &Path) -> bool {
    child.strip_prefix(parent).is_ok_and(|rest| {
        let rest = rest.to_string_lossy();
        !rest.is_empty() && !rest.starts_with("..")
    })
}
fn paths_overlap(left: &Path, right: &Path) -> bool {
    left == right || is_inside(left, right) || is_inside(right, left)
}
fn canonical(path: &Path) -> R<PathBuf> {
    std::fs::canonicalize(path).map_err(|error| io_error("realpath", path, &error))
}

pub fn enable_writable_grant(
    state_dir: &Path,
    project_id: &str,
    source_id: &str,
    project_root: &Path,
    permissions: &RemoteCommandPermissions,
    profile_id: &str,
    host_path: &str,
) -> R<()> {
    let definition = permissions
        .resource_profiles
        .writable
        .iter()
        .find(|item| item.id == profile_id)
        .ok_or_else(|| {
            RemoteCommandError::failed(format!("Unknown writable profile: {profile_id}"))
        })?;
    if !Path::new(host_path).is_absolute() {
        return fail("--host-path must be absolute");
    }
    let root = canonical(project_root)?;
    let host = canonical(Path::new(host_path))?;
    let metadata = std::fs::metadata(&host).map_err(|error| io_error("stat", &host, &error))?;
    if !metadata.is_dir() {
        return fail("Writable profile host path must be a directory");
    }
    if paths_overlap(&host, &root) {
        return fail("Writable profile cannot overlap the Project source");
    }
    private_directory(state_dir)?;
    if paths_overlap(&host, &canonical(state_dir)?) {
        return fail("Writable profile cannot overlap OpenMates private state");
    }
    let host_text = host
        .to_str()
        .ok_or_else(|| {
            RemoteCommandError::failed("Writable profile host path must be valid UTF-8")
        })?
        .to_owned();
    let mut grant = base_grant(
        project_id,
        source_id,
        ResourceKind::Writable,
        &definition.id,
        resource_definition_digest("writable", definition)?,
    );
    grant.insert("host_path".into(), json!(host_text));
    upsert(
        state_dir,
        grant,
        project_id,
        source_id,
        ResourceKind::Writable,
        &definition.id,
    )
}

pub fn enable_network_grant(
    state_dir: &Path,
    project_id: &str,
    source_id: &str,
    permissions: &RemoteCommandPermissions,
    profile_id: &str,
) -> R<()> {
    let definition = permissions
        .resource_profiles
        .network
        .iter()
        .find(|item| item.id == profile_id)
        .ok_or_else(|| {
            RemoteCommandError::failed(format!("Unknown network profile: {profile_id}"))
        })?;
    let grant = base_grant(
        project_id,
        source_id,
        ResourceKind::Network,
        &definition.id,
        resource_definition_digest("network", definition)?,
    );
    upsert(
        state_dir,
        grant,
        project_id,
        source_id,
        ResourceKind::Network,
        &definition.id,
    )
}

/// `environment_sources` maps each target variable NAME to a local variable
/// NAME. Values are never read or stored.
pub fn enable_credential_grant(
    state_dir: &Path,
    project_id: &str,
    source_id: &str,
    permissions: &RemoteCommandPermissions,
    profile_id: &str,
    environment_sources: &[(String, String)],
) -> R<()> {
    let definition = permissions
        .resource_profiles
        .credentials
        .iter()
        .find(|item| item.id == profile_id)
        .ok_or_else(|| {
            RemoteCommandError::failed(format!("Unknown credential profile: {profile_id}"))
        })?;
    let mut expected = definition.environment.clone();
    expected.sort();
    let mut supplied = environment_sources
        .iter()
        .map(|(target, _)| target.clone())
        .collect::<Vec<_>>();
    supplied.sort();
    if expected != supplied {
        return fail(format!(
            "Credential profile requires mappings for: {}",
            expected.join(", ")
        ));
    }
    if environment_sources
        .iter()
        .any(|(target, local)| !environment_name(target) || !environment_name(local))
    {
        return fail("Credential environment names must use uppercase shell variable syntax");
    }
    let mut sources = Map::new();
    for (target, local) in environment_sources {
        sources.insert(target.clone(), json!(local));
    }
    let mut grant = base_grant(
        project_id,
        source_id,
        ResourceKind::Credential,
        &definition.id,
        resource_definition_digest("credential", definition)?,
    );
    grant.insert("environment_sources".into(), Value::Object(sources));
    upsert(
        state_dir,
        grant,
        project_id,
        source_id,
        ResourceKind::Credential,
        &definition.id,
    )
}

pub fn disable_resource_grant(
    state_dir: &Path,
    project_id: &str,
    source_id: &str,
    kind: ResourceKind,
    profile_id: &str,
) -> R<()> {
    validate_resource_identity(project_id, source_id, profile_id)?;
    let mut grants = vec![];
    for item in read_resource_store(state_dir)? {
        if !same_identity(&item, project_id, source_id, kind.as_str(), profile_id)? {
            grants.push(item);
        }
    }
    write_resource_store(state_dir, &grants)
}
