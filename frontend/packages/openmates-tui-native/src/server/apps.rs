//! Instance app packages: operator-installed providers for built-in app skills.
//! The CLI validates and stages package files only; package code runs solely
//! inside the app packages runner container. Layout and record formats follow
//! docs/architecture/apps/instance-app-packages.md.
use super::apps_archive::{self as archive, Manifest, Package};
use super::*;
use std::io::BufRead;
use std::os::unix::fs::{DirBuilderExt, PermissionsExt};

/// Services that load registry.json (api and every Celery worker build the
/// skill registry at startup; Celery beat does not) or execute package code
/// (the runner). Matches the package mounts in the core compose files.
pub(super) const RESTART_SERVICES: &[&str] = &[
    "api",
    "task-worker",
    "user-init-worker",
    "core-worker",
    "user-tasks-worker",
    "reminder-worker",
    "workflow-worker",
    "app-ai-worker",
    "app-images-worker",
    "app-music-worker",
    "app-videos-worker",
    "app-pdf-worker",
    "app-docs-worker",
    "app-code-worker",
    "app-social-media-worker",
    "app-packages-runner",
];
/// Mounts the package root in the source and current self-host compose files
/// only; restarted when the active compose file defines it.
const OPTIONAL_RESTART_SERVICES: &[&str] = &["app-ai-routing-worker"];
pub(super) const WARNING: &str = "App package code runs on this server inside the app packages runner container with internet access. Install only code from sources you trust; you are responsible for what it does.";
const ENABLE_NOTICE: &str = "App packages are disabled on this server. Enable them with `openmates server env set OPENMATES_APP_PACKAGES_ENABLED --value true` and restart the server.";
const ENABLED_KEY: &str = "OPENMATES_APP_PACKAGES_ENABLED";
const ROOT_KEY: &str = "OPENMATES_APP_PACKAGES_DIR";
const RECORD_LIMIT: u64 = 4 * 1024 * 1024;

#[derive(Serialize, Deserialize, Clone, PartialEq, Eq, Debug)]
#[serde(deny_unknown_fields)]
pub(super) struct ActiveVersion {
    pub version: String,
    pub sha256: String,
}
#[derive(Serialize, Deserialize, Debug)]
#[serde(deny_unknown_fields)]
pub(super) struct Registry {
    pub format: u32,
    pub revision: u64,
    pub active: BTreeMap<String, ActiveVersion>,
    pub installed: BTreeMap<String, Vec<String>>,
}
impl Default for Registry {
    fn default() -> Self {
        Self {
            format: 1,
            revision: 0,
            active: BTreeMap::new(),
            installed: BTreeMap::new(),
        }
    }
}
#[derive(Serialize, Deserialize, Debug)]
#[serde(deny_unknown_fields)]
pub(super) struct InstallRecord {
    pub package_id: String,
    pub version: String,
    pub archive_sha256: String,
    pub installed_at: u64,
    pub file_digests: BTreeMap<String, String>,
}

pub(super) struct Store {
    pub root: PathBuf,
}
fn missing(path: &Path) -> Result<bool> {
    match std::fs::symlink_metadata(path) {
        Ok(meta) if meta.file_type().is_symlink() => Err(Error::Invalid(
            "App package storage must not contain symbolic links.",
        )),
        Ok(_) => Ok(false),
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => Ok(true),
        Err(_) => Err(Error::Io),
    }
}
impl Store {
    /// Resolve the package root without creating it.
    pub(super) fn open(root: PathBuf) -> Result<Self> {
        if !missing(&root)? {
            fs::directory(&root, false)?;
        }
        Ok(Self { root })
    }
    /// Create the root and packages directory with container-readable 0755 modes.
    fn create(&self) -> Result<()> {
        fs::public_directory(&self.root)?;
        fs::public_directory(&self.root.join("packages"))?;
        Ok(())
    }
    fn lock(&self) -> Result<fs::HostLock> {
        fs::HostLock::acquire(&self.root.join("registry.json"))
    }
    fn package_dir(&self, id: &str) -> PathBuf {
        self.root.join("packages").join(id)
    }
    fn version_dir(&self, id: &str, version: &str) -> PathBuf {
        self.package_dir(id).join(version)
    }
    pub(super) fn registry(&self) -> Result<Registry> {
        let path = self.root.join("registry.json");
        if missing(&self.root)? || missing(&path)? {
            return Ok(Registry::default());
        }
        let registry: Registry = serde_json::from_slice(&fs::read(&path, RECORD_LIMIT)?)
            .map_err(|_| Error::Invalid("registry.json is not a valid app package registry."))?;
        if registry.format != 1 {
            return Err(Error::Invalid(
                "registry.json uses an unsupported registry format.",
            ));
        }
        Ok(registry)
    }
    /// Atomic replacement (temporary file + rename) with the next revision.
    fn save(&self, registry: &mut Registry) -> Result<()> {
        registry.revision += 1;
        let mut bytes = serde_json::to_vec_pretty(registry)?;
        bytes.push(b'\n');
        fs::write(&self.root.join("registry.json"), &bytes, 0o644)
    }
    pub(super) fn record(&self, id: &str, version: &str) -> Result<Option<InstallRecord>> {
        let dir = self.version_dir(id, version);
        if missing(&self.root)? || missing(&self.package_dir(id))? || missing(&dir)? {
            return Ok(None);
        }
        let record: InstallRecord =
            serde_json::from_slice(&fs::read(&dir.join("install.json"), RECORD_LIMIT)?)
                .map_err(|_| Error::Invalid("An installed package record is invalid."))?;
        if record.package_id != id || record.version != version {
            return Err(Error::Invalid(
                "An installed package record does not match its directory.",
            ));
        }
        Ok(Some(record))
    }
    fn manifest(&self, id: &str, version: &str) -> Result<Manifest> {
        let raw = fs::read(
            &self.version_dir(id, version).join("manifest.yml"),
            archive::MAX_MANIFEST_BYTES,
        )?;
        let manifest = archive::parse_manifest(&raw)?;
        if manifest.id != id || manifest.version != version {
            return Err(Error::Invalid(
                "An installed manifest does not match its directory.",
            ));
        }
        Ok(manifest)
    }
    /// Recheck every recorded file digest before (re)activating a version.
    fn verify(&self, record: &InstallRecord) -> Result<()> {
        use sha2::{Digest, Sha256};
        let files = self
            .version_dir(&record.package_id, &record.version)
            .join("files");
        for (path, digest) in &record.file_digests {
            if !archive::valid_path(path) {
                return Err(Error::Invalid("An installed package record is invalid."));
            }
            let bytes = fs::read(&files.join(path), archive::MAX_EXPANDED_BYTES)?;
            if format!("{:x}", Sha256::digest(&bytes)) != *digest {
                return Err(Error::Invalid(
                    "Installed package files no longer match their recorded digests; remove and reinstall the package.",
                ));
            }
        }
        Ok(())
    }
    /// Stage into a fresh hidden directory, then rename it into place.
    fn stage(&self, bytes: &[u8], package: &Package) -> Result<()> {
        let m = &package.manifest;
        let parent = self.package_dir(&m.id);
        fs::public_directory(&parent)?;
        let target = self.version_dir(&m.id, &m.version);
        if !missing(&target)? {
            return Err(Error::Invalid(
                "This package version directory already exists without a valid record.",
            ));
        }
        let staging = parent.join(format!(".staging-{}", uuid::Uuid::new_v4()));
        std::fs::DirBuilder::new()
            .mode(0o755)
            .create(&staging)
            .map_err(|_| Error::Io)?;
        let result = (|| -> Result<()> {
            std::fs::set_permissions(&staging, std::fs::Permissions::from_mode(0o755))?;
            let files = staging.join("files");
            std::fs::DirBuilder::new().mode(0o755).create(&files)?;
            std::fs::set_permissions(&files, std::fs::Permissions::from_mode(0o755))?;
            let file_digests = archive::extract(bytes, package, &files)?;
            archive::write_new(&staging.join("manifest.yml"), &package.manifest_raw, 0o644)?;
            let record = InstallRecord {
                package_id: m.id.clone(),
                version: m.version.clone(),
                archive_sha256: package.sha256.clone(),
                installed_at: now() / 1000,
                file_digests,
            };
            let mut raw = serde_json::to_vec_pretty(&record)?;
            raw.push(b'\n');
            archive::write_new(&staging.join("install.json"), &raw, 0o644)?;
            std::fs::rename(&staging, &target)?;
            std::fs::File::open(&parent)?.sync_all()?;
            Ok(())
        })();
        if result.is_err() {
            let _ = std::fs::remove_dir_all(&staging);
        }
        result
    }
}

fn host_target() -> Result<&'static str> {
    match std::env::consts::ARCH {
        "x86_64" => Ok("x86_64"),
        "aarch64" => Ok("aarch64"),
        _ => Err(Error::Invalid(
            "App packages support only aarch64 and x86_64 servers.",
        )),
    }
}
pub(super) fn enabled(content: &str) -> bool {
    env_get(content, ENABLED_KEY).is_some_and(|v| v.eq_ignore_ascii_case("true"))
}
pub(super) fn secret_variable(provider: &str, name: &str) -> String {
    format!(
        "SECRET__{}__{}",
        provider.to_ascii_uppercase(),
        name.to_ascii_uppercase()
    )
}
/// Create the package root before Compose starts so Docker never creates the
/// bind-mount source itself (root-owned), which would block later installs.
pub(super) fn prepare_root(c: &Configuration) -> Result<()> {
    if c.server_role != "core" {
        return Ok(());
    }
    // Without a server .env no OPENMATES_APP_PACKAGES_DIR override can exist yet.
    let content = if missing(&c.install_path.join(".env"))? {
        Zeroizing::new(String::new())
    } else {
        env(&c.install_path)?
    };
    Store::open(root(c, &content)?)?.create()
}
/// The shell environment takes precedence over the server .env, like Compose.
fn root(c: &Configuration, content: &str) -> Result<PathBuf> {
    let process = std::env::var(ROOT_KEY).ok().filter(|v| !v.is_empty());
    let configured = process.or_else(|| env_get(content, ROOT_KEY).map(str::to_owned));
    match configured {
        Some(value) => {
            if !Path::new(&value).is_absolute() {
                return Err(Error::Invalid(
                    "OPENMATES_APP_PACKAGES_DIR must be an absolute path.",
                ));
            }
            normalized_path(&value)
        }
        None => Ok(c.install_path.join(".openmates/app-packages")),
    }
}
fn package_argument(args: &[String]) -> Result<&str> {
    args.first()
        .map(String::as_str)
        .filter(|id| archive::package_id(id))
        .ok_or(Error::Invalid(
            "Provide a valid app package id such as my.events.",
        ))
}
fn confirm(question: &str, non_interactive: &'static str, flags: &Flags) -> Result<()> {
    use std::io::IsTerminal;
    if boolean(flags, "json") || !std::io::stdin().is_terminal() {
        return Err(Error::Invalid(non_interactive));
    }
    eprint!("{question} [y/N]: ");
    std::io::stderr().flush()?;
    let mut answer = String::new();
    std::io::stdin().lock().take(64).read_line(&mut answer)?;
    if matches!(answer.trim().to_ascii_lowercase().as_str(), "y" | "yes") {
        Ok(())
    } else {
        Err(Error::Invalid("Not confirmed; nothing was changed."))
    }
}
fn restart(c: &Configuration, flags: &Flags) -> Result<Value> {
    if boolean(flags, "no-restart") {
        return Ok(json!(false));
    }
    let _critical = operation::critical()?;
    let services = restart_services(c)?;
    docker(
        c,
        std::iter::once("restart".to_owned()).chain(services.iter().cloned()),
    )?;
    Ok(json!(services))
}
/// Fixed consumers plus optional ones the server's compose file defines
/// (a restart request for an undefined service is rejected).
pub(super) fn restart_services(c: &Configuration) -> Result<Vec<String>> {
    let compose = c.install_path.join(marker(&c.server_role, &c.install_mode));
    let defined = if missing(&compose)? {
        String::new()
    } else {
        String::from_utf8_lossy(&fs::read(&compose, 8 * 1024 * 1024)?).into_owned()
    };
    let mut services = RESTART_SERVICES
        .iter()
        .map(|s| (*s).to_owned())
        .collect::<Vec<_>>();
    for optional in OPTIONAL_RESTART_SERVICES {
        if defined.contains(&format!("\n  {optional}:\n")) {
            services.push((*optional).to_owned());
        }
    }
    Ok(services)
}
fn summary(m: &Manifest) -> Value {
    json!({"id":m.id,"version":m.version,"name":m.name,"description":m.description,"providers":m.providers})
}
fn notice(content: &str) -> Option<&'static str> {
    if enabled(content) {
        None
    } else {
        eprintln!("{ENABLE_NOTICE}");
        Some(ENABLE_NOTICE)
    }
}
fn read_archive(path: &Path) -> Result<Vec<u8>> {
    let file = std::fs::File::open(path)
        .map_err(|_| Error::Invalid("The package archive could not be opened."))?;
    let meta = file.metadata()?;
    if !meta.is_file() || meta.len() == 0 || meta.len() > archive::MAX_ARCHIVE_BYTES {
        return Err(Error::Invalid(
            "The package archive must be a file between 1 byte and 64 MiB.",
        ));
    }
    let mut bytes = Vec::new();
    file.take(archive::MAX_ARCHIVE_BYTES + 1)
        .read_to_end(&mut bytes)?;
    if bytes.len() as u64 > archive::MAX_ARCHIVE_BYTES {
        return Err(Error::Invalid(
            "The package archive must be a file between 1 byte and 64 MiB.",
        ));
    }
    Ok(bytes)
}
/// Provider ids used by built-in code: every app's providers and the provider
/// configuration names. Installed providers share their secret namespace, so
/// these ids are refused; the server loader re-checks a wider derived set
/// (backend/shared/app_packages/reserved_ids.py).
fn builtin_provider_ids(
    install_path: &std::path::Path,
) -> Result<std::collections::HashSet<String>> {
    let normalize = |value: &str| value.trim().to_lowercase().replace([' ', '-'], "_");
    let mut ids = std::collections::HashSet::new();
    for entry in std::fs::read_dir(install_path.join("backend/apps"))? {
        let path = entry?.path().join("app.yml");
        if !path.is_file() {
            continue;
        }
        let definition: serde_yaml::Value =
            serde_yaml::from_slice(&fs::read(&path, 4 * 1024 * 1024)?)
                .map_err(|_| Error::Protocol)?;
        let skills = definition
            .get("skills")
            .and_then(serde_yaml::Value::as_sequence)
            .into_iter()
            .flatten();
        for provider in skills
            .filter_map(|s| s.get("providers").and_then(serde_yaml::Value::as_sequence))
            .flatten()
        {
            ids.extend(provider.as_str().map(normalize));
            for key in ["id", "name"] {
                ids.extend(
                    provider
                        .get(key)
                        .and_then(serde_yaml::Value::as_str)
                        .map(normalize),
                );
            }
        }
    }
    if let Ok(entries) = std::fs::read_dir(install_path.join("backend/providers")) {
        for path in entries.flatten().map(|entry| entry.path()) {
            if path.extension().is_some_and(|ext| ext == "yml") {
                ids.extend(
                    path.file_stem()
                        .and_then(|stem| stem.to_str())
                        .map(normalize),
                );
            }
        }
    }
    Ok(ids)
}

/// Source installations carry the built-in app definitions on the host; check
/// targets there. Image installations are checked again when the server loads.
fn check_targets(c: &Configuration, m: &Manifest) -> Result<()> {
    if c.install_mode != "source" {
        return Ok(());
    }
    let builtin_ids = builtin_provider_ids(&c.install_path)?;
    for p in &m.providers {
        let path = c
            .install_path
            .join("backend/apps")
            .join(&p.app)
            .join("app.yml");
        if !path.is_file() {
            return Err(Error::Invalid(
                "A provider targets an app that does not exist on this server.",
            ));
        }
        let definition: serde_yaml::Value =
            serde_yaml::from_slice(&fs::read(&path, 4 * 1024 * 1024)?)
                .map_err(|_| Error::Protocol)?;
        let skill = definition
            .get("skills")
            .and_then(serde_yaml::Value::as_sequence)
            .into_iter()
            .flatten()
            .find(|s| s.get("id").and_then(serde_yaml::Value::as_str) == Some(p.skill.as_str()))
            .ok_or(Error::Invalid(
                "A provider targets a skill that does not exist on this server.",
            ))?;
        let declared = skill
            .get("provider_contract")
            .and_then(serde_yaml::Value::as_str);
        let has_providers = skill
            .get("providers")
            .and_then(serde_yaml::Value::as_sequence)
            .is_some_and(|list| !list.is_empty());
        let accepted = if p.contract == archive::GENERIC_CONTRACT {
            // Generic contract: only a paused skill that waits for a provider.
            skill
                .get("provider_required")
                .and_then(serde_yaml::Value::as_bool)
                == Some(true)
                && declared.is_none()
                && !has_providers
        } else {
            declared == Some(p.contract.as_str())
        };
        if !accepted {
            return Err(Error::Invalid(
                "The target skill does not accept installed providers with this contract.",
            ));
        }
        let collides = skill
            .get("providers")
            .and_then(serde_yaml::Value::as_sequence)
            .into_iter()
            .flatten()
            .any(|b| b.get("id").and_then(serde_yaml::Value::as_str) == Some(p.id.as_str()));
        if collides || builtin_ids.contains(&p.id) {
            return Err(Error::Invalid(
                "A provider id collides with a built-in provider id.",
            ));
        }
    }
    Ok(())
}

pub(super) fn execute(
    action: &str,
    c: &Configuration,
    args: &[String],
    flags: &Flags,
) -> Result<Value> {
    if c.server_role != "core" {
        return Err(Error::Invalid(
            "App packages require a core server installation.",
        ));
    }
    let content = env(&c.install_path)?;
    let store = Store::open(root(c, &content)?)?;
    match action {
        "apps" | "apps list" => list(&store, &content),
        "apps install" => install(c, &store, &content, args, flags),
        "apps inspect" => inspect(&store, &content, args),
        "apps rollback" => rollback(c, &store, &content, args, flags),
        "apps remove" => remove(c, &store, &content, args, flags),
        _ => Err(Error::Invalid("Unknown app package command.")),
    }
}

fn install(
    c: &Configuration,
    store: &Store,
    content: &str,
    args: &[String],
    flags: &Flags,
) -> Result<Value> {
    let source = args
        .first()
        .ok_or(Error::Invalid("Usage: server apps install <zip>"))?;
    let bytes = read_archive(Path::new(source))?;
    let package = archive::inspect(&bytes, host_target()?)?;
    let m = &package.manifest;
    check_targets(c, m)?;
    let conflict = |store: &Store| -> Result<Option<InstallRecord>> {
        match store.record(&m.id, &m.version)? {
            Some(existing) if existing.archive_sha256 != package.sha256 => Err(Error::Invalid(
                "This package version is already installed from a different archive; publish a new version instead.",
            )),
            other => Ok(other),
        }
    };
    conflict(store)?;
    eprintln!("App package {} ({}) version {}", m.name, m.id, m.version);
    for p in &m.providers {
        eprintln!(
            "  adds provider {} ({}) to {}.{} [{}]",
            p.name, p.id, p.app, p.skill, p.contract
        );
    }
    eprintln!("Warning: {WARNING}");
    if !boolean(flags, "accept-server-execution") {
        confirm(
            "Install this package and allow its code to run on this server?",
            "Non-interactive installation requires --accept-server-execution; nothing was changed.",
            flags,
        )?;
    }
    store.create()?;
    let _lock = store.lock()?;
    let mut registry = store.registry()?;
    let status = match conflict(store)? {
        Some(_)
            if registry
                .active
                .get(&m.id)
                .is_some_and(|a| a.version == m.version && a.sha256 == package.sha256) =>
        {
            "unchanged"
        }
        Some(existing) => {
            store.verify(&existing)?;
            "activated"
        }
        None => {
            store.stage(&bytes, &package)?;
            "installed"
        }
    };
    let restarted = if status == "unchanged" {
        json!(false)
    } else {
        let _critical = operation::critical()?;
        let versions = registry.installed.entry(m.id.clone()).or_default();
        if !versions.contains(&m.version) {
            versions.push(m.version.clone());
            versions.sort_by(|a, b| archive::compare_versions(a, b));
        }
        registry.active.insert(
            m.id.clone(),
            ActiveVersion {
                version: m.version.clone(),
                sha256: package.sha256.clone(),
            },
        );
        store.save(&mut registry)?;
        restart(c, flags)?
    };
    Ok(
        json!({"command":"apps install","status":status,"package":summary(m),"archiveSha256":package.sha256,"revision":registry.revision,"restarted":restarted,"warning":WARNING,"notice":notice(content)}),
    )
}

fn list(store: &Store, content: &str) -> Result<Value> {
    let registry = store.registry()?;
    let packages = registry
        .installed
        .iter()
        .map(|(id, versions)| -> Result<Value> {
            let active = registry.active.get(id);
            let name = active
                .map(|a| store.manifest(id, &a.version).map(|m| m.name))
                .transpose()?;
            Ok(json!({"id":id,"name":name,"activeVersion":active.map(|a| &a.version),"versions":versions}))
        })
        .collect::<Result<Vec<_>>>()?;
    Ok(
        json!({"command":"apps list","status":"success","enabled":enabled(content),"root":store.root,"revision":registry.revision,"packages":packages}),
    )
}

fn inspect(store: &Store, content: &str, args: &[String]) -> Result<Value> {
    let id = package_argument(args)?;
    let registry = store.registry()?;
    let versions = registry
        .installed
        .get(id)
        .ok_or(Error::Invalid("This app package is not installed."))?;
    let active = registry.active.get(id);
    let shown = active
        .map(|a| a.version.as_str())
        .or_else(|| versions.last().map(String::as_str))
        .ok_or(Error::Invalid("This app package has no installed version."))?;
    let manifest = store.manifest(id, shown)?;
    let mut missing_secrets = 0;
    let providers = manifest
        .providers
        .iter()
        .map(|p| {
            let secrets = p
                .secret_names()
                .iter()
                .map(|name| {
                    let variable = secret_variable(&p.id, name);
                    let configured = env_get(content, &variable).is_some();
                    if !configured {
                        missing_secrets += 1;
                    }
                    json!({"name":name,"variable":variable,"configured":configured})
                })
                .collect::<Vec<_>>();
            let optional_secrets = p
                .optional_secret_names()
                .iter()
                .map(|name| {
                    let variable = secret_variable(&p.id, name);
                    json!({"name":name,"variable":variable,"configured":env_get(content, &variable).is_some()})
                })
                .collect::<Vec<_>>();
            json!({"app":p.app,"skill":p.skill,"contract":p.contract,"id":p.id,"name":p.name,"runtime":p.runtime,"entrypoint":p.entrypoint,"skillHint":p.skill_hint,"available":secrets.iter().all(|s| s["configured"] == true),"secrets":secrets,"optionalSecrets":optional_secrets})
        })
        .collect::<Vec<_>>();
    let versions = versions
        .iter()
        .map(|v| json!({"version":v,"active":active.is_some_and(|a| &a.version == v)}))
        .collect::<Vec<_>>();
    Ok(
        json!({"command":"apps inspect","status":"success","enabled":enabled(content),"id":id,"name":manifest.name,"description":manifest.description,"activeVersion":active.map(|a| &a.version),"archiveSha256":active.map(|a| &a.sha256),"versions":versions,"providers":providers,"missingSecrets":missing_secrets}),
    )
}

fn rollback(
    c: &Configuration,
    store: &Store,
    content: &str,
    args: &[String],
    flags: &Flags,
) -> Result<Value> {
    let id = package_argument(args)?.to_owned();
    if missing(&store.root)? {
        return Err(Error::Invalid("This app package is not installed."));
    }
    let _lock = store.lock()?;
    let mut registry = store.registry()?;
    let versions = registry
        .installed
        .get(&id)
        .ok_or(Error::Invalid("This app package is not installed."))?;
    let current = registry.active.get(&id).map(|a| a.version.clone());
    let target = match text(flags, "to") {
        Some(requested) => versions
            .iter()
            .find(|v| v.as_str() == requested)
            .cloned()
            .ok_or(Error::Invalid(
                "The requested version is not installed for this package.",
            ))?,
        None => {
            let current = current.as_deref().ok_or(Error::Invalid(
                "This app package has no active version; use --to <version>.",
            ))?;
            versions
                .iter()
                .filter(|v| archive::compare_versions(v, current).is_lt())
                .max_by(|a, b| archive::compare_versions(a, b))
                .cloned()
                .ok_or(Error::Invalid(
                    "No earlier installed version is available to roll back to.",
                ))?
        }
    };
    if current.as_deref() == Some(target.as_str()) {
        return Ok(
            json!({"command":"apps rollback","status":"unchanged","id":id,"activeVersion":target,"revision":registry.revision,"restarted":false}),
        );
    }
    let record = store.record(&id, &target)?.ok_or(Error::Invalid(
        "The requested version is recorded but its files are missing.",
    ))?;
    store.verify(&record)?;
    let _critical = operation::critical()?;
    registry.active.insert(
        id.clone(),
        ActiveVersion {
            version: target.clone(),
            sha256: record.archive_sha256,
        },
    );
    store.save(&mut registry)?;
    let restarted = restart(c, flags)?;
    Ok(
        json!({"command":"apps rollback","status":"success","id":id,"previousVersion":current,"activeVersion":target,"revision":registry.revision,"restarted":restarted,"notice":notice(content)}),
    )
}

fn remove(
    c: &Configuration,
    store: &Store,
    content: &str,
    args: &[String],
    flags: &Flags,
) -> Result<Value> {
    let id = package_argument(args)?.to_owned();
    if missing(&store.root)? {
        return Err(Error::Invalid("This app package is not installed."));
    }
    if !store.registry()?.installed.contains_key(&id) {
        return Err(Error::Invalid("This app package is not installed."));
    }
    if !boolean(flags, "yes") {
        confirm(
            &format!("Remove app package {id} and all of its installed versions?"),
            "Non-interactive removal requires --yes; nothing was changed.",
            flags,
        )?;
    }
    let _lock = store.lock()?;
    let mut registry = store.registry()?;
    let versions = registry
        .installed
        .remove(&id)
        .ok_or(Error::Invalid("This app package is not installed."))?;
    let _critical = operation::critical()?;
    registry.active.remove(&id);
    // Deactivate first so a partially deleted directory is never active.
    store.save(&mut registry)?;
    let dir = store.package_dir(&id);
    if !missing(&dir)? {
        if !std::fs::symlink_metadata(&dir)?.is_dir() {
            return Err(Error::Invalid(
                "App package storage contains an unexpected file.",
            ));
        }
        std::fs::remove_dir_all(&dir)?;
    }
    let restarted = restart(c, flags)?;
    Ok(
        json!({"command":"apps remove","status":"success","id":id,"removedVersions":versions,"revision":registry.revision,"restarted":restarted,"notice":notice(content)}),
    )
}
