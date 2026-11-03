//! Strict, reviewable `.openmates/permissions.yml` definitions. Validation
//! order, defaults and messages follow npm `remoteCommandPermissions.ts`
//! exactly so both CLIs accept the same files and report the same errors.
use super::{RemoteCommandError, RemoteCommandResult as R, io_error};
use serde::Serialize;
use serde_yaml::{Mapping, Value as Yaml};
use std::io::Read;
use std::path::Path;

pub const REMOTE_COMMAND_PERMISSIONS_PATH: &str = ".openmates/permissions.yml";
const MAX_FILE_BYTES: usize = 256 * 1024;
const MAX_ARGV_ITEMS: usize = 128;
const MAX_ARGUMENT_BYTES: usize = 16 * 1024;
const MIN_DEADLINE_MS: i64 = 100;
const MAX_DEADLINE_MS: i64 = 24 * 60 * 60 * 1000;
const DEFAULT_DEADLINE_MS: i64 = 10 * 60 * 1000;
const MAX_SAFE_INTEGER: i64 = 9_007_199_254_740_991;

/// Field order matches the npm object literal (serialization order matters
/// for resource definition digests; preset digests sort keys).
#[derive(Clone, Debug, PartialEq, Eq, Serialize)]
pub struct RemoteCommandPolicy {
    pub argv: Vec<String>,
    pub cwd: String,
    pub mode: String,
    pub source_access: String,
    pub deadline_ms: i64,
    pub writable_profiles: Vec<String>,
    pub network_profile: Option<String>,
    pub credential_profiles: Vec<String>,
}
#[derive(Clone, Debug, PartialEq, Eq, Serialize)]
pub struct RemoteCommandPreset {
    pub id: String,
    pub label: String,
    pub commands: Vec<RemoteCommandPolicy>,
}
#[derive(Clone, Debug, PartialEq, Eq, Serialize)]
pub struct WritableProfile {
    pub id: String,
    pub purpose: String,
}
#[derive(Clone, Debug, PartialEq, Eq, Serialize)]
pub struct NetworkProfile {
    pub id: String,
    pub destinations: Vec<String>,
}
#[derive(Clone, Debug, PartialEq, Eq, Serialize)]
pub struct CredentialProfile {
    pub id: String,
    pub environment: Vec<String>,
}
#[derive(Clone, Debug, Default, PartialEq, Eq, Serialize)]
pub struct FileAccess {
    pub private_paths: Vec<String>,
}
#[derive(Clone, Debug, Default, PartialEq, Eq, Serialize)]
pub struct ResourceProfiles {
    pub writable: Vec<WritableProfile>,
    pub network: Vec<NetworkProfile>,
    pub credentials: Vec<CredentialProfile>,
}
#[derive(Clone, Debug, PartialEq, Eq, Serialize)]
pub struct RemoteCommandPermissions {
    pub schema_version: u8,
    pub file_access: FileAccess,
    pub presets: Vec<RemoteCommandPreset>,
    pub resource_profiles: ResourceProfiles,
}

fn fail<T>(message: impl Into<String>) -> R<T> {
    Err(RemoteCommandError::failed(message))
}

/// Load `<root>/.openmates/permissions.yml`; `Ok(None)` when it is absent.
/// The final component is opened without following symlinks and the
/// canonical file must stay inside the canonical Project root.
pub fn load_remote_command_permissions(project_root: &Path) -> R<Option<RemoteCommandPermissions>> {
    let root = std::fs::canonicalize(project_root)
        .map_err(|error| io_error("realpath", project_root, &error))?;
    let path = root.join(REMOTE_COMMAND_PERMISSIONS_PATH);
    let mut file = match open_no_follow(&path) {
        Ok(file) => file,
        Err(OpenFailure::Missing) => return Ok(None),
        Err(OpenFailure::Symlink) => {
            return fail(format!(
                "{REMOTE_COMMAND_PERMISSIONS_PATH} must be a regular file"
            ));
        }
        Err(OpenFailure::Io(error)) => return Err(io_error("open", &path, &error)),
    };
    let metadata = file
        .metadata()
        .map_err(|error| io_error("fstat", &path, &error))?;
    if !metadata.is_file() {
        return fail(format!(
            "{REMOTE_COMMAND_PERMISSIONS_PATH} must be a regular file"
        ));
    }
    if metadata.len() > MAX_FILE_BYTES as u64 {
        return fail(format!(
            "{REMOTE_COMMAND_PERMISSIONS_PATH} exceeds {MAX_FILE_BYTES} bytes"
        ));
    }
    let canonical =
        std::fs::canonicalize(&path).map_err(|error| io_error("realpath", &path, &error))?;
    if !canonical.starts_with(&root) {
        return fail(format!(
            "{REMOTE_COMMAND_PERMISSIONS_PATH} escapes the Project root"
        ));
    }
    let mut bytes = Vec::new();
    file.read_to_end(&mut bytes)
        .map_err(|error| io_error("read", &path, &error))?;
    // Node `readFileSync(fd, "utf8")` replaces invalid sequences.
    parse_remote_command_permissions(&String::from_utf8_lossy(&bytes)).map(Some)
}

enum OpenFailure {
    Missing,
    Symlink,
    Io(std::io::Error),
}
#[cfg(unix)]
fn open_no_follow(path: &Path) -> Result<std::fs::File, OpenFailure> {
    use rustix::fs::{Mode, OFlags};
    match rustix::fs::open(
        path,
        OFlags::RDONLY | OFlags::NOFOLLOW | OFlags::CLOEXEC,
        Mode::empty(),
    ) {
        Ok(descriptor) => Ok(std::fs::File::from(descriptor)),
        Err(errno) if errno == rustix::io::Errno::NOENT => Err(OpenFailure::Missing),
        Err(errno) if errno == rustix::io::Errno::LOOP => Err(OpenFailure::Symlink),
        Err(errno) => Err(OpenFailure::Io(std::io::Error::from_raw_os_error(
            errno.raw_os_error(),
        ))),
    }
}
#[cfg(not(unix))]
fn open_no_follow(path: &Path) -> Result<std::fs::File, OpenFailure> {
    match std::fs::symlink_metadata(path) {
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => {
            return Err(OpenFailure::Missing);
        }
        Err(error) => return Err(OpenFailure::Io(error)),
        Ok(metadata) if metadata.file_type().is_symlink() => return Err(OpenFailure::Symlink),
        Ok(_) => {}
    }
    std::fs::File::open(path).map_err(OpenFailure::Io)
}

/// Parse and validate a permissions document (npm `parseRemoteCommandPermissions`).
pub fn parse_remote_command_permissions(source: &str) -> R<RemoteCommandPermissions> {
    if source.len() > MAX_FILE_BYTES {
        return fail(format!(
            "Permissions definition exceeds {MAX_FILE_BYTES} bytes"
        ));
    }
    let document: Yaml = serde_yaml::from_str(source).map_err(|error| {
        RemoteCommandError::failed(format!("Invalid permissions YAML: {error}"))
    })?;
    validate_root(&document)
}

fn validate_root(value: &Yaml) -> R<RemoteCommandPermissions> {
    let root = record(Some(value), "permissions")?;
    exact_keys(
        root,
        &[
            "schema_version",
            "file_access",
            "presets",
            "resource_profiles",
        ],
        "permissions",
    )?;
    if !number_equals(root.get("schema_version"), 1) {
        return fail("schema_version must be 1");
    }
    let file_access = match root.get("file_access") {
        None => FileAccess::default(),
        Some(value) => validate_file_access(value)?,
    };
    let resources = match root.get("resource_profiles") {
        None => ResourceProfiles::default(),
        Some(value) => validate_resources(value)?,
    };
    let presets = array(root.get("presets"), "presets")?
        .iter()
        .enumerate()
        .map(|(index, item)| validate_preset(item, index))
        .collect::<R<Vec<_>>>()?;
    assert_unique(presets.iter().map(|p| p.id.as_str()), "preset")?;
    validate_references(&presets, &resources)?;
    Ok(RemoteCommandPermissions {
        schema_version: 1,
        file_access,
        presets,
        resource_profiles: resources,
    })
}

fn validate_file_access(value: &Yaml) -> R<FileAccess> {
    let file_access = record(Some(value), "file_access")?;
    exact_keys(file_access, &["private_paths"], "file_access")?;
    let private_paths = optional_array(
        file_access.get("private_paths"),
        "file_access.private_paths",
    )?
    .iter()
    .enumerate()
    .map(|(index, item)| project_private_path(item, &format!("file_access.private_paths[{index}]")))
    .collect::<R<Vec<_>>>()?;
    assert_unique(
        private_paths.iter().map(String::as_str),
        "file_access.private_paths",
    )?;
    Ok(FileAccess { private_paths })
}

fn validate_resources(value: &Yaml) -> R<ResourceProfiles> {
    let resources = record(Some(value), "resource_profiles")?;
    exact_keys(
        resources,
        &["writable", "network", "credentials"],
        "resource_profiles",
    )?;
    let mut writable = vec![];
    for (index, item) in optional_array(resources.get("writable"), "resource_profiles.writable")?
        .iter()
        .enumerate()
    {
        let context = format!("writable[{index}]");
        let profile = record(Some(item), &context)?;
        exact_keys(profile, &["id", "purpose"], &context)?;
        let id = identifier(profile.get("id"), &format!("{context}.id"))?;
        let purpose = one_of(
            profile.get("purpose"),
            &["cache", "output"],
            &format!("{context}.purpose"),
        )?;
        writable.push(WritableProfile { id, purpose });
    }
    let mut network = vec![];
    for (index, item) in optional_array(resources.get("network"), "resource_profiles.network")?
        .iter()
        .enumerate()
    {
        let context = format!("network[{index}]");
        let profile = record(Some(item), &context)?;
        exact_keys(profile, &["id", "destinations"], &context)?;
        let destinations = array(
            profile.get("destinations"),
            &format!("{context}.destinations"),
        )?
        .iter()
        .enumerate()
        .map(|(position, destination)| {
            network_destination(destination, &format!("{context}.destinations[{position}]"))
        })
        .collect::<R<Vec<_>>>()?;
        if destinations.is_empty() {
            return fail(format!("{context}.destinations cannot be empty"));
        }
        assert_unique(
            destinations.iter().map(String::as_str),
            &format!("{context}.destinations"),
        )?;
        let id = identifier(profile.get("id"), &format!("{context}.id"))?;
        network.push(NetworkProfile { id, destinations });
    }
    let mut credentials = vec![];
    for (index, item) in optional_array(
        resources.get("credentials"),
        "resource_profiles.credentials",
    )?
    .iter()
    .enumerate()
    {
        let context = format!("credentials[{index}]");
        let profile = record(Some(item), &context)?;
        exact_keys(profile, &["id", "environment"], &context)?;
        let mut environment = vec![];
        for (position, name) in array(
            profile.get("environment"),
            &format!("{context}.environment"),
        )?
        .iter()
        .enumerate()
        {
            let name = string(Some(name), &format!("{context}.environment[{position}]"))?;
            if !environment_name(&name) {
                return fail(format!("Invalid environment name: {name}"));
            }
            environment.push(name);
        }
        if environment.is_empty() {
            return fail(format!("{context}.environment cannot be empty"));
        }
        assert_unique(
            environment.iter().map(String::as_str),
            &format!("{context}.environment"),
        )?;
        let id = identifier(profile.get("id"), &format!("{context}.id"))?;
        credentials.push(CredentialProfile { id, environment });
    }
    assert_unique(writable.iter().map(|p| p.id.as_str()), "writable profile")?;
    assert_unique(network.iter().map(|p| p.id.as_str()), "network profile")?;
    assert_unique(
        credentials.iter().map(|p| p.id.as_str()),
        "credential profile",
    )?;
    Ok(ResourceProfiles {
        writable,
        network,
        credentials,
    })
}

fn validate_preset(value: &Yaml, index: usize) -> R<RemoteCommandPreset> {
    let context = format!("presets[{index}]");
    let preset = record(Some(value), &context)?;
    exact_keys(preset, &["id", "label", "commands"], &context)?;
    let commands = array(preset.get("commands"), &format!("{context}.commands"))?
        .iter()
        .enumerate()
        .map(|(position, command)| {
            validate_policy(command, &format!("{context}.commands[{position}]"))
        })
        .collect::<R<Vec<_>>>()?;
    if commands.is_empty() {
        return fail(format!("{context}.commands cannot be empty"));
    }
    Ok(RemoteCommandPreset {
        id: identifier(preset.get("id"), &format!("{context}.id"))?,
        label: bounded_string(preset.get("label"), &format!("{context}.label"), 1, 120)?,
        commands,
    })
}

fn validate_policy(value: &Yaml, context: &str) -> R<RemoteCommandPolicy> {
    let policy = record(Some(value), context)?;
    exact_keys(
        policy,
        &[
            "argv",
            "cwd",
            "mode",
            "source_access",
            "deadline_ms",
            "writable_profiles",
            "network_profile",
            "credential_profiles",
        ],
        context,
    )?;
    let argv = array(policy.get("argv"), &format!("{context}.argv"))?
        .iter()
        .enumerate()
        .map(|(index, arg)| {
            bounded_string(
                Some(arg),
                &format!("{context}.argv[{index}]"),
                1,
                MAX_ARGUMENT_BYTES,
            )
        })
        .collect::<R<Vec<_>>>()?;
    if argv.is_empty() || argv.len() > MAX_ARGV_ITEMS {
        return fail(format!(
            "{context}.argv must contain 1-{MAX_ARGV_ITEMS} items"
        ));
    }
    if argv.iter().any(|argument| argument.contains('\0')) {
        return fail(format!("{context}.argv cannot contain NUL bytes"));
    }
    let mode = match policy.get("mode") {
        None => "foreground".to_owned(),
        value => one_of(
            value,
            &["foreground", "background"],
            &format!("{context}.mode"),
        )?,
    };
    let source_access = match policy.get("source_access") {
        None => "read_only".to_owned(),
        value => one_of(
            value,
            &["read_only", "read_write"],
            &format!("{context}.source_access"),
        )?,
    };
    if mode == "background" && source_access != "read_only" {
        return fail(format!(
            "{context}: background commands must use read_only source access"
        ));
    }
    let deadline_ms = match policy.get("deadline_ms") {
        None => DEFAULT_DEADLINE_MS,
        value => integer(value, &format!("{context}.deadline_ms"))?,
    };
    if !(MIN_DEADLINE_MS..=MAX_DEADLINE_MS).contains(&deadline_ms) {
        return fail(format!(
            "{context}.deadline_ms must be {MIN_DEADLINE_MS}-{MAX_DEADLINE_MS}"
        ));
    }
    let writable_profiles = identifiers(
        policy.get("writable_profiles"),
        &format!("{context}.writable_profiles"),
    )?;
    let credential_profiles = identifiers(
        policy.get("credential_profiles"),
        &format!("{context}.credential_profiles"),
    )?;
    assert_unique(
        writable_profiles.iter().map(String::as_str),
        &format!("{context}.writable_profiles"),
    )?;
    assert_unique(
        credential_profiles.iter().map(String::as_str),
        &format!("{context}.credential_profiles"),
    )?;
    // npm `policy.cwd ?? "."`: a YAML null also selects the default.
    let cwd = match policy.get("cwd") {
        None | Some(Yaml::Null) => ".".to_owned(),
        Some(value) => project_relative_path(value, &format!("{context}.cwd"))?,
    };
    let network_profile = match policy.get("network_profile") {
        None | Some(Yaml::Null) => None,
        value => Some(identifier(value, &format!("{context}.network_profile"))?),
    };
    Ok(RemoteCommandPolicy {
        argv,
        cwd,
        mode,
        source_access,
        deadline_ms,
        writable_profiles,
        network_profile,
        credential_profiles,
    })
}

fn identifiers(value: Option<&Yaml>, context: &str) -> R<Vec<String>> {
    optional_array(value, context)?
        .iter()
        .enumerate()
        .map(|(index, id)| identifier(Some(id), &format!("{context}[{index}]")))
        .collect()
}

fn validate_references(presets: &[RemoteCommandPreset], resources: &ResourceProfiles) -> R<()> {
    for preset in presets {
        for command in &preset.commands {
            for id in &command.writable_profiles {
                if !resources.writable.iter().any(|profile| &profile.id == id) {
                    return fail(format!("Unknown writable profile: {id}"));
                }
            }
            if let Some(id) = &command.network_profile
                && !resources.network.iter().any(|profile| &profile.id == id)
            {
                return fail(format!("Unknown network profile: {id}"));
            }
            for id in &command.credential_profiles {
                if !resources
                    .credentials
                    .iter()
                    .any(|profile| &profile.id == id)
                {
                    return fail(format!("Unknown credential profile: {id}"));
                }
            }
        }
    }
    Ok(())
}

/// Node `path.posix.normalize` for relative inputs (trailing slash kept).
pub(super) fn posix_normalize(path: &str) -> String {
    if path.is_empty() {
        return ".".into();
    }
    let absolute = path.starts_with('/');
    let trailing = path.ends_with('/');
    let mut segments: Vec<&str> = vec![];
    for segment in path.split('/') {
        match segment {
            "" | "." => {}
            ".." => {
                if segments.last().is_some_and(|last| *last != "..") {
                    segments.pop();
                } else if !absolute {
                    segments.push("..");
                }
            }
            other => segments.push(other),
        }
    }
    let mut result = segments.join("/");
    if result.is_empty() && !absolute {
        result.push('.');
    }
    if !result.is_empty() && trailing {
        result.push('/');
    }
    if absolute {
        format!("/{result}")
    } else {
        result
    }
}

fn project_relative_path(value: &Yaml, context: &str) -> R<String> {
    let path = string(Some(value), context)?.replace('\\', "/");
    if path == "." {
        return Ok(path);
    }
    if path.is_empty() || path.contains('\0') || path.starts_with('/') {
        return fail(format!("{context} must be Project-relative"));
    }
    let normalized = posix_normalize(&path);
    let stripped = path.strip_prefix("./").unwrap_or(&path);
    if normalized == ".." || normalized.starts_with("../") || normalized != stripped {
        return fail(format!(
            "{context} must be a normalized Project-relative path"
        ));
    }
    Ok(normalized)
}

fn project_private_path(value: &Yaml, context: &str) -> R<String> {
    let mut path = bounded_string(Some(value), context, 1, 1_024)?;
    if let Some(rest) = path.strip_prefix("./") {
        path = rest.to_owned();
    }
    if path.trim().is_empty()
        || path.starts_with('!')
        || path.starts_with('#')
        || path.starts_with("//")
        || path.contains('\\')
        || path.chars().any(|c| (c as u32) < 32 || c as u32 == 127)
    {
        return fail(format!(
            "{context} must be an additive Project-relative path glob"
        ));
    }
    let bytes = path.as_bytes();
    if bytes.len() >= 2 && bytes[0].is_ascii_alphabetic() && bytes[1] == b':' {
        return fail(format!("{context} must be Project-relative"));
    }
    let inner = path.strip_prefix('/').unwrap_or(&path);
    let inner = inner.strip_suffix('/').unwrap_or(inner);
    let segments = inner.split('/').collect::<Vec<_>>();
    if segments.contains(&"..") {
        return fail(format!("{context} cannot contain a parent path segment"));
    }
    if segments.iter().all(|segment| segment.is_empty()) {
        return fail(format!("{context} must identify a Project path"));
    }
    Ok(path)
}

fn network_destination(value: &Yaml, context: &str) -> R<String> {
    let destination = string(Some(value), context)?.to_lowercase();
    let pattern = regex::Regex::new(
        r"^(?:\[[0-9a-f:]+\]|[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?)(?::[1-9][0-9]{0,4})?$",
    )
    .map_err(|_| RemoteCommandError::failed("network destination pattern is invalid"))?;
    if destination.encode_utf16().count() > 253 || !pattern.is_match(&destination) {
        return fail(format!(
            "{context} must be an exact hostname or hostname:port"
        ));
    }
    Ok(destination)
}

/// `/^[a-z][a-z0-9-]{0,63}$/`
pub(super) fn profile_identifier(value: &str) -> bool {
    let bytes = value.as_bytes();
    !bytes.is_empty()
        && bytes.len() <= 64
        && bytes[0].is_ascii_lowercase()
        && bytes[1..]
            .iter()
            .all(|b| b.is_ascii_lowercase() || b.is_ascii_digit() || *b == b'-')
}
/// `/^[A-Z_][A-Z0-9_]{0,127}$/`
pub(super) fn environment_name(value: &str) -> bool {
    let bytes = value.as_bytes();
    !bytes.is_empty()
        && bytes.len() <= 128
        && (bytes[0].is_ascii_uppercase() || bytes[0] == b'_')
        && bytes[1..]
            .iter()
            .all(|b| b.is_ascii_uppercase() || b.is_ascii_digit() || *b == b'_')
}

fn record<'a>(value: Option<&'a Yaml>, context: &str) -> R<&'a Mapping> {
    match value {
        Some(Yaml::Mapping(mapping)) => Ok(mapping),
        _ => fail(format!("{context} must be a mapping")),
    }
}
fn array<'a>(value: Option<&'a Yaml>, context: &str) -> R<&'a [Yaml]> {
    match value {
        Some(Yaml::Sequence(items)) => Ok(items.as_slice()),
        _ => fail(format!("{context} must be a list")),
    }
}
fn optional_array<'a>(value: Option<&'a Yaml>, context: &str) -> R<&'a [Yaml]> {
    match value {
        None => Ok(&[][..]),
        value => array(value, context),
    }
}
/// JavaScript `toJS` object key spelling for scalar YAML keys.
fn key_name(key: &Yaml) -> String {
    match key {
        Yaml::String(value) => value.clone(),
        Yaml::Number(value) => value.to_string(),
        Yaml::Bool(value) => value.to_string(),
        Yaml::Null => String::new(),
        _ => "[object Object]".into(),
    }
}
fn exact_keys(value: &Mapping, allowed: &[&str], context: &str) -> R<()> {
    for key in value.keys() {
        let name = key_name(key);
        if !allowed.contains(&name.as_str()) {
            return fail(format!("{context} contains unknown key: {name}"));
        }
    }
    Ok(())
}
fn string(value: Option<&Yaml>, context: &str) -> R<String> {
    match value {
        Some(Yaml::String(value)) => Ok(value.clone()),
        _ => fail(format!("{context} must be a string")),
    }
}
fn bounded_string(
    value: Option<&Yaml>,
    context: &str,
    minimum: usize,
    maximum: usize,
) -> R<String> {
    let result = string(value, context)?;
    if result.len() < minimum || result.len() > maximum {
        return fail(format!("{context} must be {minimum}-{maximum} bytes"));
    }
    Ok(result)
}
fn identifier(value: Option<&Yaml>, context: &str) -> R<String> {
    let result = string(value, context)?;
    if !profile_identifier(&result) {
        return fail(format!("{context} is not a valid identifier"));
    }
    Ok(result)
}
/// `Number.isSafeInteger`: integral finite numbers within +/-(2^53 - 1),
/// including integral floats such as `1e3`.
fn safe_integer(value: Option<&Yaml>) -> Option<i64> {
    let Some(Yaml::Number(number)) = value else {
        return None;
    };
    if let Some(integer) = number.as_i64() {
        return (integer.abs() <= MAX_SAFE_INTEGER).then_some(integer);
    }
    if number.as_u64().is_some() {
        return None;
    }
    let float = number.as_f64()?;
    (float.is_finite() && float.fract() == 0.0 && float.abs() <= MAX_SAFE_INTEGER as f64)
        .then_some(float as i64)
}
fn integer(value: Option<&Yaml>, context: &str) -> R<i64> {
    safe_integer(value)
        .ok_or_else(|| RemoteCommandError::failed(format!("{context} must be an integer")))
}
fn number_equals(value: Option<&Yaml>, expected: i64) -> bool {
    safe_integer(value) == Some(expected)
}
fn one_of(value: Option<&Yaml>, choices: &[&str], context: &str) -> R<String> {
    match value {
        Some(Yaml::String(value)) if choices.contains(&value.as_str()) => Ok(value.clone()),
        _ => fail(format!("{context} must be one of {}", choices.join(", "))),
    }
}
fn assert_unique<'a>(values: impl Iterator<Item = &'a str>, context: &str) -> R<()> {
    let mut seen = std::collections::BTreeSet::new();
    for value in values {
        if !seen.insert(value) {
            return fail(format!("{context} contains duplicate values"));
        }
    }
    Ok(())
}
