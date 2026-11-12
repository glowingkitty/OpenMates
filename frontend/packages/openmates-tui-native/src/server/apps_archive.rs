//! Non-executing validation of instance app package archives.
//! Nothing in this module runs, imports or installs package code.
use crate::error::{Error, Result};
use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};
use std::{
    cmp::Ordering,
    collections::{BTreeMap, BTreeSet},
    io::{Cursor, Read, Write},
    os::unix::fs::{DirBuilderExt, OpenOptionsExt, PermissionsExt},
    path::Path,
};

pub(super) const FORMAT: &str = "openmates-app-package";
pub(super) const MAX_ARCHIVE_BYTES: u64 = 64 * 1024 * 1024;
pub(super) const MAX_EXPANDED_BYTES: u64 = 256 * 1024 * 1024;
pub(super) const MAX_ENTRIES: usize = 2000;
pub(super) const MAX_MANIFEST_BYTES: u64 = 256 * 1024;
pub(super) const TARGETS: &[&str] = &["aarch64", "x86_64"];
const MAX_PROVIDERS: usize = 32;
const MAX_PROVIDER_REGIONS: usize = 60;
const MAX_PATH_CHARS: usize = 240;

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct RawManifest {
    format: String,
    format_version: u64,
    id: String,
    version: String,
    name: String,
    #[serde(default)]
    description: Option<String>,
    contributes: serde_yaml::Mapping,
}

#[derive(Deserialize, Serialize, Clone, Debug)]
#[serde(deny_unknown_fields)]
pub(super) struct Provider {
    pub app: String,
    pub skill: String,
    pub contract: String,
    pub id: String,
    pub name: String,
    pub runtime: String,
    pub entrypoint: String,
    #[serde(default)]
    pub secrets: Option<Vec<String>>,
    #[serde(default)]
    pub optional_secrets: Option<Vec<String>>,
    #[serde(default)]
    pub skill_hint: Option<String>,
    /// ISO 3166-1 alpha-2 codes the provider covers; absent means worldwide.
    #[serde(default)]
    pub regions: Option<Vec<String>>,
}
impl Provider {
    pub(super) fn secret_names(&self) -> &[String] {
        self.secrets.as_deref().unwrap_or_default()
    }
    pub(super) fn optional_secret_names(&self) -> &[String] {
        self.optional_secrets.as_deref().unwrap_or_default()
    }
}

#[derive(Serialize, Clone, Debug)]
pub(super) struct Manifest {
    pub id: String,
    pub version: String,
    pub name: String,
    pub description: Option<String>,
    pub providers: Vec<Provider>,
}

pub(super) struct Entry {
    pub index: usize,
    pub path: String,
    pub size: u64,
}

pub(super) struct Package {
    pub sha256: String,
    pub manifest: Manifest,
    pub manifest_raw: Vec<u8>,
    pub files: Vec<Entry>,
    /// Resolved entrypoints present in the archive, staged as 0755.
    pub executables: BTreeSet<String>,
}

fn lower_alnum(b: u8) -> bool {
    b.is_ascii_lowercase() || b.is_ascii_digit()
}
/// `[a-z0-9]+(\.[a-z0-9_-]+)+`, at most 64 characters.
pub(super) fn package_id(value: &str) -> bool {
    if value.is_empty() || value.len() > 64 {
        return false;
    }
    let mut parts = value.split('.');
    let first = parts.next().unwrap_or_default();
    if first.is_empty() || !first.bytes().all(lower_alnum) {
        return false;
    }
    let mut rest = 0;
    for part in parts {
        if part.is_empty()
            || !part
                .bytes()
                .all(|b| lower_alnum(b) || b == b'_' || b == b'-')
        {
            return false;
        }
        rest += 1;
    }
    rest > 0
}
/// `[a-z0-9_]{2,40}`.
pub(super) fn provider_id(value: &str) -> bool {
    (2..=40).contains(&value.len()) && value.bytes().all(|b| lower_alnum(b) || b == b'_')
}
fn target_id(value: &str) -> bool {
    (1..=64).contains(&value.len())
        && value.bytes().next().is_some_and(|b| b.is_ascii_lowercase())
        && value
            .bytes()
            .all(|b| lower_alnum(b) || b == b'_' || b == b'-')
}
fn secret_name(value: &str) -> bool {
    (1..=64).contains(&value.len())
        && value.bytes().next().is_some_and(|b| b.is_ascii_lowercase())
        && value.bytes().all(|b| lower_alnum(b) || b == b'_')
}
/// An ISO 3166-1 alpha-2 country code in upper case.
fn region_code(value: &str) -> bool {
    value.len() == 2 && value.bytes().all(|b| b.is_ascii_uppercase())
}
/// Generic contract served to any built-in skill that is paused for lack of a provider.
pub(super) const GENERIC_CONTRACT: &str = "skill.requests@1";
/// `<app>.<skill>@<n>` for the contribution's own target skill, or the generic contract.
fn contract(value: &str, app: &str, skill: &str) -> bool {
    if value == GENERIC_CONTRACT {
        return true;
    }
    let Some((name, number)) = value.split_once('@') else {
        return false;
    };
    name == format!("{app}.{skill}")
        && (1..=6).contains(&number.len())
        && number.bytes().all(|b| b.is_ascii_digit())
        && !number.starts_with('0')
}
fn display_text(value: &str, max: usize) -> bool {
    !value.trim().is_empty()
        && value.chars().count() <= max
        && !value.chars().any(|c| c.is_control() && c != '\n')
}

/// Relative UTF-8 path without absolute, empty, `.` or `..` segments.
pub(super) fn valid_path(value: &str) -> bool {
    !value.is_empty()
        && value.chars().count() <= MAX_PATH_CHARS
        && !value.starts_with('/')
        && !value.contains(['\\', '\0', ':'])
        && !value.chars().any(char::is_control)
        && value
            .split('/')
            .all(|part| !part.is_empty() && part != "." && part != "..")
}
fn entrypoint_template(value: &str) -> bool {
    let probe = value.replace("{target}", "x86_64");
    !probe.contains(['{', '}']) && valid_path(&probe)
}
pub(super) fn resolve_entrypoint(value: &str, target: &str) -> String {
    value.replace("{target}", target)
}

#[derive(PartialEq, Eq)]
enum Identifier {
    Numeric(u64),
    Text(String),
}
struct Version {
    core: [u64; 3],
    pre: Vec<Identifier>,
}
fn numeric(part: &str) -> Option<u64> {
    if part.is_empty()
        || !part.bytes().all(|b| b.is_ascii_digit())
        || (part.len() > 1 && part.starts_with('0'))
    {
        return None;
    }
    part.parse().ok()
}
fn identifiers(value: &str) -> bool {
    value.split('.').all(|part| {
        !part.is_empty() && part.bytes().all(|b| b.is_ascii_alphanumeric() || b == b'-')
    })
}
fn parse_version(value: &str) -> Option<Version> {
    if value.is_empty() || value.len() > 64 {
        return None;
    }
    let (rest, build) = match value.split_once('+') {
        Some((rest, build)) => (rest, Some(build)),
        None => (value, None),
    };
    if build.is_some_and(|b| !identifiers(b)) {
        return None;
    }
    let (core, pre) = match rest.split_once('-') {
        Some((core, pre)) => (core, Some(pre)),
        None => (rest, None),
    };
    let numbers = core.split('.').map(numeric).collect::<Option<Vec<_>>>()?;
    let &[major, minor, patch] = numbers.as_slice() else {
        return None;
    };
    let mut parsed = Vec::new();
    if let Some(pre) = pre {
        if !identifiers(pre) {
            return None;
        }
        for part in pre.split('.') {
            if part.bytes().all(|b| b.is_ascii_digit()) {
                parsed.push(Identifier::Numeric(numeric(part)?));
            } else {
                parsed.push(Identifier::Text(part.to_owned()));
            }
        }
    }
    Some(Version {
        core: [major, minor, patch],
        pre: parsed,
    })
}
pub(super) fn semantic_version(value: &str) -> bool {
    parse_version(value).is_some()
}
/// Semantic-version precedence; build metadata and invalid input fall back to text order.
pub(super) fn compare_versions(a: &str, b: &str) -> Ordering {
    let (Some(left), Some(right)) = (parse_version(a), parse_version(b)) else {
        return a.cmp(b);
    };
    let pre = match (left.pre.is_empty(), right.pre.is_empty()) {
        (true, true) => Ordering::Equal,
        (true, false) => Ordering::Greater,
        (false, true) => Ordering::Less,
        (false, false) => {
            let mut result = Ordering::Equal;
            for (x, y) in left.pre.iter().zip(&right.pre) {
                result = match (x, y) {
                    (Identifier::Numeric(x), Identifier::Numeric(y)) => x.cmp(y),
                    (Identifier::Numeric(_), Identifier::Text(_)) => Ordering::Less,
                    (Identifier::Text(_), Identifier::Numeric(_)) => Ordering::Greater,
                    (Identifier::Text(x), Identifier::Text(y)) => x.cmp(y),
                };
                if result != Ordering::Equal {
                    break;
                }
            }
            result.then(left.pre.len().cmp(&right.pre.len()))
        }
    };
    left.core.cmp(&right.core).then(pre).then_with(|| a.cmp(b))
}

/// Parse and validate a manifest. Shared by install and installed-version reads.
pub(super) fn parse_manifest(raw: &[u8]) -> Result<Manifest> {
    if raw.len() as u64 > MAX_MANIFEST_BYTES {
        return Err(Error::Invalid("manifest.yml exceeds its size limit."));
    }
    let text =
        std::str::from_utf8(raw).map_err(|_| Error::Invalid("manifest.yml must be UTF-8."))?;
    let raw: RawManifest = serde_yaml::from_str(text)
        .map_err(|_| Error::Invalid("manifest.yml is not a valid app package manifest."))?;
    if raw.format != FORMAT {
        return Err(Error::Invalid(
            "Unsupported package format; manifest format must be openmates-app-package.",
        ));
    }
    if raw.format_version != 1 {
        return Err(Error::Invalid(
            "Unsupported package format_version; this CLI supports format_version 1.",
        ));
    }
    if !package_id(&raw.id) {
        return Err(Error::Invalid(
            "Invalid package id; use a lowercase dotted identifier such as my.events.",
        ));
    }
    if !semantic_version(&raw.version) {
        return Err(Error::Invalid(
            "Invalid package version; use a semantic version such as 1.0.0.",
        ));
    }
    if !display_text(&raw.name, 120)
        || raw
            .description
            .as_deref()
            .is_some_and(|d| d.chars().count() > 2000 || d.contains('\0'))
    {
        return Err(Error::Invalid("Invalid package name or description."));
    }
    let mut providers = None;
    for (key, value) in raw.contributes {
        match key.as_str() {
            Some("providers") => {
                providers = Some(serde_yaml::from_value::<Vec<Provider>>(value).map_err(|_| {
                    Error::Invalid("contributes.providers contains an invalid provider.")
                })?);
            }
            _ => {
                return Err(Error::Invalid(
                    "Unsupported contribution kind; format 1 supports only contributes.providers.",
                ));
            }
        }
    }
    let providers = providers.ok_or(Error::Invalid(
        "The package must contribute at least one provider.",
    ))?;
    if providers.is_empty() || providers.len() > MAX_PROVIDERS {
        return Err(Error::Invalid(
            "The package must contribute between one and 32 providers.",
        ));
    }
    let mut ids = BTreeSet::new();
    for p in &providers {
        if !target_id(&p.app) || !target_id(&p.skill) {
            return Err(Error::Invalid("Invalid provider target app or skill id."));
        }
        if !contract(&p.contract, &p.app, &p.skill) {
            return Err(Error::Invalid(
                "Invalid provider contract; use <app>.<skill>@<version> for the target skill or skill.requests@1.",
            ));
        }
        // One id may serve several skills (one service, one set of secrets), once per skill.
        if !provider_id(&p.id) || !ids.insert((p.app.as_str(), p.skill.as_str(), p.id.as_str())) {
            return Err(Error::Invalid(
                "Invalid or duplicate provider id; use 2-40 characters of a-z, 0-9 and _.",
            ));
        }
        if !display_text(&p.name, 120) {
            return Err(Error::Invalid("Invalid provider name."));
        }
        if p.runtime != "executable" {
            return Err(Error::Invalid(
                "Unsupported provider runtime; format 1 supports only executable.",
            ));
        }
        if !entrypoint_template(&p.entrypoint) {
            return Err(Error::Invalid("Invalid provider entrypoint path."));
        }
        let secrets = p.secret_names();
        if secrets.len() > 16
            || !secrets.iter().all(|s| secret_name(s))
            || secrets.iter().collect::<BTreeSet<_>>().len() != secrets.len()
        {
            return Err(Error::Invalid(
                "Invalid provider secrets; use unique lowercase names such as api_key.",
            ));
        }
        let optional = p.optional_secret_names();
        if optional.len() > 16
            || !optional.iter().all(|s| secret_name(s))
            || optional.iter().collect::<BTreeSet<_>>().len() != optional.len()
            || optional.iter().any(|name| secrets.contains(name))
        {
            return Err(Error::Invalid(
                "Invalid provider optional_secrets; use unique lowercase names that are not also in secrets.",
            ));
        }
        // Same rule as the server loader: a declared list is never empty.
        if p.regions.as_deref().is_some_and(|regions| {
            regions.is_empty()
                || regions.len() > MAX_PROVIDER_REGIONS
                || !regions.iter().all(|code| region_code(code))
                || regions.iter().collect::<BTreeSet<_>>().len() != regions.len()
        }) {
            return Err(Error::Invalid(
                "Invalid provider regions; use 1-60 unique ISO 3166-1 alpha-2 codes such as DE.",
            ));
        }
        if p.skill_hint
            .as_deref()
            .is_some_and(|h| !display_text(h, 1000))
        {
            return Err(Error::Invalid(
                "Invalid provider skill_hint; it may contain at most 1000 characters.",
            ));
        }
    }
    Ok(Manifest {
        id: raw.id,
        version: raw.version,
        name: raw.name,
        description: raw.description,
        providers,
    })
}

fn invalid_archive() -> Error {
    Error::Invalid("The package is not a valid ZIP archive.")
}

/// Validate every entry and the manifest without extracting or running anything.
pub(super) fn inspect(bytes: &[u8], target: &str) -> Result<Package> {
    if bytes.is_empty() || bytes.len() as u64 > MAX_ARCHIVE_BYTES {
        return Err(Error::Invalid(
            "The package archive must be between 1 byte and 64 MiB.",
        ));
    }
    let mut zip = zip::ZipArchive::new(Cursor::new(bytes)).map_err(|_| invalid_archive())?;
    if zip.len() > MAX_ENTRIES {
        return Err(Error::Invalid(
            "The package archive contains more than 2000 entries.",
        ));
    }
    let mut files = Vec::new();
    let mut file_paths = BTreeSet::new();
    let mut directories = BTreeSet::new();
    let mut seen = BTreeSet::new();
    let mut expanded = 0_u64;
    let mut manifest_index = None;
    for index in 0..zip.len() {
        let entry = zip.by_index_raw(index).map_err(|_| invalid_archive())?;
        let name = std::str::from_utf8(entry.name_raw())
            .map_err(|_| Error::Invalid("Invalid package path; archive paths must be UTF-8."))?
            .to_owned();
        let directory = name.ends_with('/');
        let path = name.strip_suffix('/').unwrap_or(&name).to_owned();
        if !valid_path(&path) {
            return Err(Error::Invalid(
                "Invalid package path; archive paths must be relative without .. segments or backslashes.",
            ));
        }
        if !seen.insert(path.clone()) {
            return Err(Error::Invalid(
                "Invalid package path; the archive contains a duplicate path.",
            ));
        }
        let kind = entry.unix_mode().unwrap_or(0) & 0o170000;
        if !matches!(kind, 0 | 0o100000 | 0o040000) {
            return Err(Error::Invalid(
                "Invalid package entry; symlinks and device files are not allowed.",
            ));
        }
        if entry.encrypted() {
            return Err(Error::Invalid(
                "Invalid package entry; encrypted entries are not supported.",
            ));
        }
        if directory != (kind == 0o040000) && kind != 0 {
            return Err(Error::Invalid(
                "Invalid package entry; file type and path do not match.",
            ));
        }
        if directory {
            directories.insert(path);
            continue;
        }
        if !matches!(
            entry.compression(),
            zip::CompressionMethod::Stored | zip::CompressionMethod::Deflated
        ) {
            return Err(Error::Invalid(
                "Invalid package entry; only stored and deflated entries are supported.",
            ));
        }
        expanded = expanded
            .checked_add(entry.size())
            .filter(|total| *total <= MAX_EXPANDED_BYTES)
            .ok_or(Error::Invalid("The package expands to more than 256 MiB."))?;
        if path == "manifest.yml" {
            if entry.size() > MAX_MANIFEST_BYTES {
                return Err(Error::Invalid("manifest.yml exceeds its size limit."));
            }
            manifest_index = Some(index);
        }
        file_paths.insert(path.clone());
        files.push(Entry {
            index,
            path,
            size: entry.size(),
        });
    }
    // A file may not also be an ancestor directory of another entry.
    for path in file_paths.iter().chain(&directories) {
        let mut ancestor = path.as_str();
        while let Some((parent, _)) = ancestor.rsplit_once('/') {
            if file_paths.contains(parent) {
                return Err(Error::Invalid(
                    "Invalid package path; a file is also used as a directory.",
                ));
            }
            ancestor = parent;
        }
    }
    let index = manifest_index.ok_or(Error::Invalid(
        "The package must contain manifest.yml at the archive root.",
    ))?;
    let manifest_raw = {
        let entry = zip.by_index(index).map_err(|_| invalid_archive())?;
        let declared = entry.size();
        let mut raw = Vec::new();
        entry
            .take(declared + 1)
            .read_to_end(&mut raw)
            .map_err(|_| invalid_archive())?;
        if raw.len() as u64 != declared {
            return Err(invalid_archive());
        }
        raw
    };
    let manifest = parse_manifest(&manifest_raw)?;
    let mut executables = BTreeSet::new();
    for provider in &manifest.providers {
        if !file_paths.contains(&resolve_entrypoint(&provider.entrypoint, target)) {
            return Err(Error::Invalid(
                "The package has no provider entrypoint for this server's CPU architecture.",
            ));
        }
        for candidate in TARGETS {
            let resolved = resolve_entrypoint(&provider.entrypoint, candidate);
            if file_paths.contains(&resolved) {
                executables.insert(resolved);
            }
        }
    }
    Ok(Package {
        sha256: format!("{:x}", Sha256::digest(bytes)),
        manifest,
        manifest_raw,
        files,
        executables,
    })
}

fn create_directory(path: &Path) -> Result<()> {
    std::fs::DirBuilder::new().mode(0o755).create(path)?;
    std::fs::set_permissions(path, std::fs::Permissions::from_mode(0o755))?;
    Ok(())
}
/// Write one new private-to-owner file inside a freshly created staging tree.
pub(super) fn write_new(path: &Path, bytes: &[u8], mode: u32) -> Result<()> {
    let mut file = std::fs::OpenOptions::new()
        .write(true)
        .create_new(true)
        .mode(mode)
        .open(path)?;
    file.write_all(bytes)?;
    file.sync_all()?;
    std::fs::set_permissions(path, std::fs::Permissions::from_mode(mode))?;
    Ok(())
}

/// Extract validated entries into `destination` (a new, empty, owner-only
/// writable directory) and return the SHA-256 of every regular file.
pub(super) fn extract(
    bytes: &[u8],
    package: &Package,
    destination: &Path,
) -> Result<BTreeMap<String, String>> {
    let mut zip = zip::ZipArchive::new(Cursor::new(bytes)).map_err(|_| invalid_archive())?;
    let mut digests = BTreeMap::new();
    let mut buffer = vec![0_u8; 64 * 1024];
    for entry in &package.files {
        let mut target = destination.to_path_buf();
        let segments = entry.path.split('/').collect::<Vec<_>>();
        let (name, parents) = segments.split_last().ok_or_else(invalid_archive)?;
        for segment in parents {
            target.push(segment);
            match std::fs::symlink_metadata(&target) {
                Ok(meta) if meta.is_dir() && !meta.file_type().is_symlink() => {}
                Ok(_) => return Err(invalid_archive()),
                Err(error) if error.kind() == std::io::ErrorKind::NotFound => {
                    create_directory(&target)?
                }
                Err(_) => return Err(Error::Io),
            }
        }
        target.push(name);
        let mode = if package.executables.contains(&entry.path) {
            0o755
        } else {
            0o644
        };
        let mut file = std::fs::OpenOptions::new()
            .write(true)
            .create_new(true)
            .mode(mode)
            .open(&target)?;
        let mut reader = zip.by_index(entry.index).map_err(|_| invalid_archive())?;
        let mut hasher = Sha256::new();
        let mut total = 0_u64;
        loop {
            let read = reader.read(&mut buffer).map_err(|_| invalid_archive())?;
            if read == 0 {
                break;
            }
            total += read as u64;
            if total > entry.size {
                return Err(invalid_archive());
            }
            hasher.update(&buffer[..read]);
            file.write_all(&buffer[..read])?;
        }
        if total != entry.size {
            return Err(invalid_archive());
        }
        file.sync_all()?;
        drop(file);
        std::fs::set_permissions(&target, std::fs::Permissions::from_mode(mode))?;
        digests.insert(entry.path.clone(), format!("{:x}", hasher.finalize()));
    }
    Ok(digests)
}
