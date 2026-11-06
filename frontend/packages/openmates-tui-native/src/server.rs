//! Native application self-host management. Only documented system tools are
//! spawned; application policy, configuration and validation execute in Rust.
mod backup;
mod bind_mounts;
mod brevo;
mod caddy;
mod chat_bootstrap;
mod cleanup;
mod configuration;
mod data;
mod fs;
mod host_reporter;
mod human;
pub use human::human_text;
mod local_models;
mod monitoring;
mod notifications;
mod operation;
mod overlay;
mod probes;
mod quick_test;
mod reports;
mod startup;
mod templates;
mod translations;
mod update;
mod updater;
use crate::error::{Error, Result};
pub use quick_test::{quick_test, quick_test_preflight};
use rand::RngCore;
use serde::{Deserialize, Serialize};
use serde_json::{Value, json};
use std::{
    collections::BTreeMap,
    io::{Read, Write},
    path::{Path, PathBuf},
    process::{Command, Stdio},
};
pub use updater::update_window_allows;
use zeroize::Zeroizing;
type Flags = BTreeMap<String, Value>;
struct SecretFlags(Flags);
impl std::ops::Deref for SecretFlags {
    type Target = Flags;
    fn deref(&self) -> &Flags {
        &self.0
    }
}
impl Drop for SecretFlags {
    fn drop(&mut self) {
        self.0.values_mut().for_each(local_models::erase);
    }
}
const CONFIG: &str = "server.json";
const WORKERS: &[&str] = &[
    "task-worker",
    "user-init-worker",
    "core-worker",
    "user-tasks-worker",
    "reminder-worker",
    "workflow-worker",
    "task-scheduler",
    "app-ai-worker",
    "app-images-worker",
    "app-music-worker",
    "app-videos-worker",
    "app-pdf-worker",
    "app-docs-worker",
    "app-code-worker",
    "app-social-media-worker",
];
const CORE: &[&str] = &[
    "api",
    "cms",
    "cms-database",
    "cache",
    "vault",
    "vault-setup",
    "cms-setup",
];

#[derive(Serialize, Deserialize, Clone)]
#[serde(rename_all = "camelCase")]
struct Configuration {
    install_path: PathBuf,
    installed_at: u64,
    compose_profile: String,
    #[serde(default = "default_role")]
    server_role: String,
    #[serde(default = "default_profile")]
    server_profile: String,
    #[serde(default = "default_mode")]
    install_mode: String,
    #[serde(default)]
    source_strategy: Option<String>,
    #[serde(default)]
    image_tag: Option<String>,
    #[serde(default)]
    image_channel: Option<String>,
    #[serde(default)]
    default_services: Option<Vec<String>>,
    #[serde(default)]
    api_url: Option<String>,
    #[serde(default)]
    app_url: Option<String>,
    #[serde(default = "overlay::default_mode")]
    deployment_mode: String,
    #[serde(default, rename = "openMatesCloudOverlayPath")]
    overlay_path: Option<PathBuf>,
}
fn default_role() -> String {
    "core".into()
}
fn default_profile() -> String {
    "production".into()
}
fn default_mode() -> String {
    "source".into()
}
fn now() -> u64 {
    std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .unwrap_or_default()
        .as_millis() as u64
}
fn text<'a>(flags: &'a Flags, key: &str) -> Option<&'a str> {
    flags
        .get(key)
        .and_then(Value::as_str)
        .filter(|s| !s.is_empty())
}
fn boolean(flags: &Flags, key: &str) -> bool {
    flags.get(key) == Some(&Value::Bool(true))
}
fn config(state: &Path) -> Result<Option<Configuration>> {
    let path = state.join(CONFIG);
    if !path.try_exists()? {
        return Ok(None);
    }
    Ok(Some(serde_json::from_slice(&fs::read(&path, 128 * 1024)?)?))
}
fn save_config(state: &Path, value: &Configuration) -> Result<()> {
    fs::write(
        &state.join(CONFIG),
        &serde_json::to_vec_pretty(value)?,
        0o600,
    )
}
pub fn installed_api(state: &Path) -> Result<Option<String>> {
    Ok(config(state)?.and_then(|c| c.api_url))
}
pub fn installed_app(state: &Path) -> Result<Option<String>> {
    Ok(config(state)?.and_then(|c| c.app_url))
}
fn normalized_path(value: &str) -> Result<PathBuf> {
    let path = PathBuf::from(value);
    let path = if path.is_absolute() {
        path
    } else {
        std::env::current_dir()?.join(path)
    };
    if path.components().any(|c| {
        matches!(
            c,
            std::path::Component::ParentDir | std::path::Component::CurDir
        )
    }) {
        return Err(Error::Invalid("Server paths must be normalized."));
    }
    Ok(path)
}
fn marker(role: &str, mode: &str) -> &'static str {
    match (role, mode) {
        ("core", "image") => "backend/core/docker-compose.selfhost.yml",
        ("core", _) => "backend/core/docker-compose.yml",
        ("upload", _) => "backend/upload/docker-compose.yml",
        _ => "backend/preview/docker-compose.preview.yml",
    }
}
fn role(value: &str) -> Result<&str> {
    if matches!(value, "core" | "upload" | "preview") {
        Ok(value)
    } else {
        Err(Error::Invalid(
            "Server role must be core, upload or preview.",
        ))
    }
}
fn profile(value: &str) -> Result<&str> {
    if matches!(value, "minimal" | "standard" | "production") {
        Ok(value)
    } else {
        Err(Error::Invalid(
            "Server profile must be minimal, standard or production.",
        ))
    }
}
fn installation(flags: &Flags, state: &Path) -> Result<Configuration> {
    let saved = config(state)?;
    let path = if let Some(path) = text(flags, "path") {
        normalized_path(path)?
    } else if let Some(c) = &saved {
        c.install_path.clone()
    } else {
        std::env::current_dir()?
    };
    fs::directory(&path, false)?;
    let mut selected = if let Some(c) = saved.filter(|c| c.install_path == path) {
        c
    } else {
        let selected_role = role(text(flags, "role").unwrap_or("core"))?;
        let mode = if path.join(marker(selected_role, "image")).is_file()
            && (selected_role != "core" || !path.join(marker(selected_role, "source")).is_file())
        {
            "image"
        } else {
            "source"
        };
        Configuration {
            install_path: path.clone(),
            installed_at: 0,
            compose_profile: "core".into(),
            server_role: selected_role.into(),
            server_profile: "production".into(),
            install_mode: mode.into(),
            source_strategy: None,
            image_tag: None,
            image_channel: None,
            default_services: None,
            api_url: None,
            app_url: None,
            deployment_mode: overlay::default_mode(),
            overlay_path: None,
        }
    };
    if let Some(requested) = text(flags, "role") {
        role(requested)?;
        if selected.server_role != requested {
            return Err(Error::Invalid(
                "Selected server role does not match the saved installation.",
            ));
        }
    }
    role(&selected.server_role)?;
    profile(&selected.server_profile)?;
    if !matches!(selected.install_mode.as_str(), "image" | "source")
        || !path
            .join(marker(&selected.server_role, &selected.install_mode))
            .is_file()
    {
        return Err(Error::Invalid(
            "Path is not an OpenMates server installation.",
        ));
    }
    fs::read(
        &path.join(marker(&selected.server_role, &selected.install_mode)),
        16 * 1024 * 1024,
    )?;
    overlay::resolve(&mut selected, &Flags::new(), &env(&path)?, false)?;
    chat_bootstrap::validate(&selected)?;
    if selected.compose_profile == "full" {
        fs::read(
            &path.join("backend/core/docker-compose.override.yml"),
            16 * 1024 * 1024,
        )?;
    }
    if let Some(p) = text(flags, "server-profile").or_else(|| text(flags, "profile")) {
        selected.server_profile = profile(p)?.into();
    }
    Ok(selected)
}
fn services(c: &Configuration, flags: &Flags) -> Result<Vec<String>> {
    let mut known: Vec<&str> = match c.server_role.as_str() {
        "core" => CORE
            .iter()
            .chain(WORKERS)
            .copied()
            .chain([
                "admin-sidecar",
                "webapp",
                "openobserve",
                "promtail",
                "prometheus",
                "cadvisor",
                "node-exporter",
                "alertmanager",
            ])
            .collect(),
        "upload" => vec![
            "app-uploads",
            "clamav",
            "vault",
            "vault-setup",
            "admin-sidecar",
        ],
        _ => vec!["preview", "admin-sidecar", "cache"],
    };
    let mut defaults = match c.server_role.as_str() {
        "core" => {
            let mut list: Vec<_> = CORE
                .iter()
                .chain(WORKERS)
                .copied()
                .chain(["admin-sidecar", "webapp"])
                .collect();
            if c.server_profile != "minimal" {
                list.extend(["openobserve", "promtail"])
            }
            if c.server_profile == "production" {
                list.extend(["prometheus", "cadvisor", "node-exporter"])
            }
            list
        }
        "upload" => known.clone(),
        _ => vec!["preview", "admin-sidecar"],
    };
    fn entries(flags: &Flags, key: &str) -> Result<Vec<String>> {
        let Some(value) = flags.get(key) else {
            return Ok(vec![]);
        };
        let values = match value {
            Value::String(v) => vec![v.as_str()],
            Value::Array(v) => v
                .iter()
                .map(|v| v.as_str().ok_or(Error::Invalid("Services must be names.")))
                .collect::<Result<Vec<_>>>()?,
            _ => return Err(Error::Invalid("Services must be names.")),
        };
        Ok(values
            .into_iter()
            .flat_map(|s| s.split(','))
            .map(str::trim)
            .filter(|s| !s.is_empty())
            .map(str::to_owned)
            .collect())
    }
    let selected = entries(flags, "services")?;
    if c.deployment_mode == "official_cloud" && selected.iter().any(|s| s == "webapp") {
        return Err(Error::Invalid(
            "Official-cloud overlays disable the local webapp service.",
        ));
    }
    let exclude = entries(flags, "exclude")?;
    for service in selected
        .iter()
        .chain(&exclude)
        .chain(c.default_services.iter().flatten())
    {
        if !known.contains(&service.as_str()) {
            return Err(Error::Invalid(
                "Unknown service for the selected server role.",
            ));
        }
    }
    if !selected.is_empty() {
        defaults = selected.iter().map(String::as_str).collect();
    } else if let Some(configured) = &c.default_services {
        defaults = configured.iter().map(String::as_str).collect();
    }
    defaults.retain(|s| !exclude.iter().any(|e| e == s));
    if c.deployment_mode == "official_cloud" {
        defaults.retain(|s| *s != "webapp");
    }
    known.clear();
    if defaults.is_empty() {
        return Err(Error::Invalid("No services selected."));
    }
    Ok(defaults.into_iter().map(str::to_owned).collect())
}
fn compose(c: &Configuration) -> Vec<String> {
    let mut args = vec![
        "compose".into(),
        "--env-file".into(),
        ".env".into(),
        "-f".into(),
        marker(&c.server_role, &c.install_mode).into(),
    ];
    if c.compose_profile == "full" && c.server_role == "core" {
        args.extend([
            "-f".into(),
            "backend/core/docker-compose.override.yml".into(),
        ]);
    }
    chat_bootstrap::append(c, &mut args);
    overlay::append(c, &mut args);
    args
}
/// Secret input is supplied on stdin, never appended to argv or errors.
fn run(
    program: &str,
    args: &[String],
    cwd: &Path,
    input: Option<&[u8]>,
) -> Result<Zeroizing<Vec<u8>>> {
    run_timeout(
        program,
        args,
        cwd,
        input,
        std::time::Duration::from_secs(30 * 60),
    )
}
fn run_timeout(
    program: &str,
    args: &[String],
    cwd: &Path,
    input: Option<&[u8]>,
    timeout: std::time::Duration,
) -> Result<Zeroizing<Vec<u8>>> {
    operation::check()?;
    #[cfg(test)]
    if let Some(result) = fake::run(program, args, cwd, input) {
        return result;
    }
    operation::run(program, args, cwd, input, timeout)
}
fn run_staged(
    program: &str,
    args: &[String],
    cwd: &Path,
    stages: &[operation::InputStage],
    timeout: std::time::Duration,
) -> Result<Zeroizing<Vec<u8>>> {
    operation::check()?;
    #[cfg(test)]
    if let Some(result) = fake::run(program, args, cwd, None) {
        let output = result?;
        operation::validate_staged_output(stages, &output)?;
        return Ok(output);
    }
    operation::run_staged(program, args, cwd, stages, timeout)
}

fn docker(
    c: &Configuration,
    suffix: impl IntoIterator<Item = String>,
) -> Result<Zeroizing<Vec<u8>>> {
    let mut args = compose(c);
    args.extend(suffix);
    run("docker", &args, &c.install_path, None)
}
fn env(path: &Path) -> Result<Zeroizing<String>> {
    let bytes = Zeroizing::new(fs::private_read(&path.join(".env"), 4 * 1024 * 1024)?);
    Ok(Zeroizing::new(String::from_utf8(bytes.to_vec()).map_err(
        |_| Error::Invalid("Server environment must be UTF-8."),
    )?))
}
fn env_get<'a>(content: &'a str, name: &str) -> Option<&'a str> {
    content
        .lines()
        .find_map(|line| {
            let (k, v) = line.split_once('=')?;
            if k.trim() == name {
                Some(v.trim().trim_matches('"').trim_matches('\''))
            } else {
                None
            }
        })
        .filter(|s| !s.is_empty())
}
fn env_set(content: &mut String, name: &str, value: &str) {
    use zeroize::Zeroize;
    let replacement = Zeroizing::new(format!("{name}={value}"));
    let mut found = false;
    let mut updated = Zeroizing::new(String::with_capacity(content.len() + replacement.len() + 1));
    for line in content.lines() {
        if line.split_once('=').is_some_and(|(key, _)| key == name) {
            found = true;
            updated.push_str(&replacement);
        } else {
            updated.push_str(line);
        }
        updated.push('\n');
    }
    if !found {
        updated.push_str(&replacement);
        updated.push('\n');
    }
    content.zeroize();
    *content = std::mem::take(&mut *updated);
}
fn random_hex(bytes: usize) -> String {
    let mut value = Zeroizing::new(vec![0u8; bytes]);
    rand::rngs::OsRng.fill_bytes(&mut value);
    value.iter().map(|b| format!("{b:02x}")).collect()
}
fn write_environment(path: &Path, tag: Option<&str>, source: bool) -> Result<()> {
    let mut content = if path.join(".env").try_exists()? {
        env(path)?
    } else if source {
        Zeroizing::new(
            String::from_utf8(fs::read(&path.join(".env.example"), 4 * 1024 * 1024)?)
                .map_err(|_| Error::Io)?,
        )
    } else {
        Zeroizing::new(templates::MINIMAL_ENV_TEMPLATE.to_owned())
    };
    for (key, value) in [
        ("DATABASE_ADMIN_EMAIL", "admin@example.com"),
        ("DATABASE_NAME", "directus"),
        ("DATABASE_USERNAME", "directus"),
        ("PRODUCTION_URL", "http://localhost:5173"),
        ("CELERY_AUTOSCALE_MAX", "3"),
        ("CELERY_AUTOSCALE_MIN", "1"),
        ("TASK_WORKER_CONCURRENCY", "3"),
        ("APP_AI_WORKER_CONCURRENCY", "3"),
        ("APP_IMAGES_WORKER_CONCURRENCY", "3"),
        ("APP_MUSIC_WORKER_CONCURRENCY", "2"),
    ] {
        if env_get(&content, key).is_none() {
            env_set(&mut content, key, value);
        }
    }
    for (key, bytes) in [
        ("DATABASE_ADMIN_PASSWORD", 12),
        ("DATABASE_PASSWORD", 12),
        ("DIRECTUS_TOKEN", 32),
        ("DIRECTUS_SECRET", 32),
        ("DRAGONFLY_PASSWORD", 12),
        ("OPENOBSERVE_ROOT_PASSWORD", 32),
        ("INTERNAL_API_SHARED_TOKEN", 32),
    ] {
        if env_get(&content, key).is_none() {
            let secret = Zeroizing::new(random_hex(bytes));
            env_set(&mut content, key, &secret);
        }
    }
    if env_get(&content, "SELF_HOST_FIRST_INVITE_CODE").is_none() {
        let mut digits = String::new();
        use rand::Rng;
        for index in 0..12 {
            if index == 4 || index == 8 {
                digits.push('-')
            }
            digits.push(char::from(b'0' + rand::rngs::OsRng.gen_range(0..10)));
        }
        env_set(&mut content, "SELF_HOST_FIRST_INVITE_CODE", &digits);
    }
    if let Some(tag) = tag {
        env_set(&mut content, "OPENMATES_IMAGE_TAG", tag);
        env_set(
            &mut content,
            "OPENMATES_IMAGE_REGISTRY",
            "ghcr.io/glowingkitty",
        );
    }
    let absolute = path.to_str().ok_or(Error::Io)?;
    if absolute.contains(['\n', '\r', '"', '\0', '$', '`']) {
        return Err(Error::Invalid(
            "Install path contains unsupported environment characters.",
        ));
    }
    env_set(&mut content, "GIT_WORK_DIR", &format!("\"{absolute}\""));
    fs::write(&path.join(".env"), content.as_bytes(), 0o600)
}
fn image_files(path: &Path, role: &str) -> Result<()> {
    let data = match role {
        "core" => include_str!("../assets/selfhost/core/docker-compose.selfhost.yml"),
        "upload" => include_str!("../assets/selfhost/upload/docker-compose.yml"),
        _ => include_str!("../assets/selfhost/preview/docker-compose.preview.yml"),
    };
    let template = match role {
        "core" => "core/docker-compose.selfhost.yml",
        "upload" => "upload/docker-compose.yml",
        _ => "preview/docker-compose.preview.yml",
    };
    let data = if let Some(root) = std::env::var_os("OPENMATES_SELFHOST_TEMPLATE_DIR") {
        String::from_utf8(fs::read(
            &PathBuf::from(root).join(template),
            8 * 1024 * 1024,
        )?)
        .map_err(|_| Error::Io)?
    } else {
        data.to_owned()
    };
    fs::write(&path.join(marker(role, "image")), data.as_bytes(), 0o600)?;
    fs::public_directory(&path.join("config/providers"))?;
    if !path.join("config/backend_config.yml").try_exists()? {
        fs::public_write(
            &path.join("config/backend_config.yml"),
            b"feature_overrides:\n  enabled: []\n  disabled: []\n",
        )?;
    }
    fs::public_write(
        &path.join(format!("backend/{role}/vault/config/vault.hcl")),
        templates::VAULT_CONFIG_TEMPLATE.as_bytes(),
    )?;
    if role == "core" {
        fs::public_write(
            &path.join("backend/core/docker-compose.no-webapp.yml"),
            include_bytes!("../assets/selfhost/core/docker-compose.no-webapp.yml"),
        )?;
        for (name, content) in [
            (
                "backend/core/monitoring/promtail/promtail-config.yaml",
                templates::SELFHOST_PROMTAIL_CONFIG_TEMPLATE,
            ),
            (
                "backend/core/monitoring/prometheus/prometheus.yml",
                include_str!("../assets/selfhost/core/monitoring/prometheus/prometheus.yml"),
            ),
            (
                "backend/core/monitoring/prometheus/alert_rules.yml",
                include_str!("../assets/selfhost/core/monitoring/prometheus/alert_rules.yml"),
            ),
            (
                "backend/core/monitoring/alertmanager/alertmanager.yml",
                include_str!("../assets/selfhost/core/monitoring/alertmanager/alertmanager.yml"),
            ),
        ] {
            fs::public_write(&path.join(name), content.as_bytes())?;
        }
    }
    fs::metrics(path)?;
    Ok(())
}
fn image_tag(flags: &Flags, current: Option<&str>) -> Result<String> {
    let tag = text(flags, "image-tag")
        .or_else(|| text(flags, "channel"))
        .or(current)
        .unwrap_or("stable");
    if tag.len() > 128
        || !tag
            .bytes()
            .all(|b| b.is_ascii_alphanumeric() || b"_.-".contains(&b))
        || tag.starts_with(['-', '.'])
    {
        return Err(Error::Invalid("Invalid image tag."));
    }
    if let Some(channel) = text(flags, "channel")
        && !matches!(channel, "dev" | "main" | "stable")
    {
        return Err(Error::Invalid("Image channel must be stable, main or dev."));
    }
    if text(flags, "channel").is_some() && text(flags, "image-tag").is_some() {
        return Err(Error::Invalid("Choose either an image tag or channel."));
    }
    Ok(tag.into())
}
fn install(flags: &Flags, state: &Path) -> Result<Value> {
    let role = role(text(flags, "role").unwrap_or("core"))?;
    let server_profile = profile(
        text(flags, "server-profile")
            .or_else(|| text(flags, "profile"))
            .unwrap_or("production"),
    )?;
    let source = boolean(flags, "from-source") || text(flags, "source-path").is_some();
    if source && (text(flags, "image-tag").is_some() || text(flags, "channel").is_some()) {
        return Err(Error::Invalid(
            "--image-tag and --channel only apply to image-mode installs.",
        ));
    }
    let path = if let Some(path) = text(flags, "path") {
        normalized_path(path)?
    } else {
        directories::BaseDirs::new()
            .ok_or(Error::Io)?
            .home_dir()
            .join("openmates")
    };
    if path.try_exists()? && std::fs::read_dir(&path)?.next().is_some() {
        return Err(Error::Invalid(
            "Install path must be empty. Existing files were preserved.",
        ));
    }
    // Both modes prepare a private root; Git accepts an existing empty target.
    if source {
        let from = if let Some(from) = text(flags, "source-path") {
            normalized_path(from)?.to_string_lossy().into_owned()
        } else {
            "https://github.com/glowingkitty/OpenMates.git".into()
        };
        if from.starts_with('-') {
            return Err(Error::Invalid("Invalid source repository."));
        }
        let branch = text(flags, "branch");
        if branch.is_some_and(|b| !matches!(b, "dev" | "main")) {
            return Err(Error::Invalid("Source branch must be dev or main."));
        }
        clone_source(&path, from, branch, |args, cwd| {
            run("git", args, cwd, None).map(|_| ())
        })?;
        harden_clone_directories(&path)?;
        if !path.join(marker(role, "source")).is_file() {
            return Err(Error::Invalid(
                "Source checkout does not contain the requested server role.",
            ));
        }
        // A source copy may provide generated locale data. Never execute the
        // legacy JavaScript translation application from the native CLI.
        prepare_locales(&path, text(flags, "source-path").map(Path::new))?;
    } else {
        fs::directory(&path, true)?;
    }
    let _lock = fs::Lock::acquire(&path)?;
    if !source {
        image_files(&path, role)?;
    }
    if let Some(env) = text(flags, "env-path") {
        let bytes = Zeroizing::new(fs::read(&normalized_path(env)?, 4 * 1024 * 1024)?);
        fs::write(&path.join(".env"), &bytes, 0o600)?;
    }
    let tag = if source {
        None
    } else {
        Some(image_tag(flags, None)?)
    };
    write_environment(&path, tag.as_deref(), source)?;
    fs::metrics(&path)?;
    let content = env(&path)?;
    let mut c = Configuration {
        install_path: path.clone(),
        installed_at: now(),
        compose_profile: if boolean(flags, "with-overrides") {
            "full"
        } else {
            "core"
        }
        .into(),
        server_role: role.into(),
        server_profile: server_profile.into(),
        install_mode: if source { "source" } else { "image" }.into(),
        source_strategy: source.then(|| "managed_clone".into()),
        image_tag: tag.clone(),
        image_channel: text(flags, "channel").map(str::to_owned),
        default_services: None,
        api_url: Some(
            env_get(&content, "VITE_API_URL")
                .unwrap_or("http://127.0.0.1:8000")
                .split(',')
                .next()
                .unwrap_or_default()
                .trim()
                .into(),
        ),
        app_url: Some(
            env_get(&content, "PRODUCTION_URL")
                .unwrap_or("http://localhost:5173")
                .into(),
        ),
        deployment_mode: overlay::default_mode(),
        overlay_path: None,
    };
    overlay::resolve(&mut c, flags, &content, true)?;
    overlay::write_environment(&c)?;
    chat_bootstrap::prepare(&c)?;
    // Inspect-before-create distinguishes an existing shared network from an
    // actual daemon or permission error; such failures never become success.
    if run(
        "docker",
        &["network".into(), "inspect".into(), "openmates".into()],
        &path,
        None,
    )
    .is_err()
    {
        run(
            "docker",
            &["network".into(), "create".into(), "openmates".into()],
            &path,
            None,
        )?;
    }
    save_config(state, &c)?;
    Ok(
        json!({"command":"install","status":"success","path":path,"role":role,"mode":c.install_mode,"imageTag":tag,"apiUrl":c.api_url,"appUrl":c.app_url,"deploymentMode":c.deployment_mode,"openMatesCloudOverlayPath":c.overlay_path,"nativeCloudVerificationAvailable":false,"runtimeMonitoringDeferred":c.deployment_mode=="official_cloud"}),
    )
}
/// Keep Git inside the validated install root, including when its parent is a
/// shared sticky directory such as /tmp. Never weaken the final-root policy to
/// admit that shared parent as a working directory.
fn clone_source(
    path: &Path,
    from: String,
    branch: Option<&str>,
    clone: impl FnOnce(&[String], &Path) -> Result<()>,
) -> Result<()> {
    let _root = fs::directory(path, true)?;
    let mut args = vec!["clone".into()];
    if let Some(branch) = branch {
        args.extend(["--branch".into(), branch.into()]);
    }
    args.extend(["--".into(), from, path.to_string_lossy().into_owned()]);
    clone(&args, path)
}
fn prepare_locales(path: &Path, source: Option<&Path>) -> Result<()> {
    let relative = "frontend/packages/ui/src/i18n/locales";
    if path.join(relative).join("en.json").is_file() {
        return Ok(());
    }
    if let Some(source) = source.filter(|p| p.join(relative).join("en.json").is_file()) {
        for entry in std::fs::read_dir(source.join(relative))? {
            let entry = entry?;
            if entry.file_type()?.is_file() && entry.path().extension().is_some_and(|s| s == "json")
            {
                let bytes = std::fs::read(entry.path())?;
                if bytes.len() > 16 * 1024 * 1024 {
                    return Err(Error::Io);
                }
                fs::write(&path.join(relative).join(entry.file_name()), &bytes, 0o600)?;
            }
        }
        return Ok(());
    }
    translations::generate(path)
}
fn harden_clone_directories(root: &Path) -> Result<()> {
    use std::os::unix::fs::PermissionsExt;
    fn children(root: &Path) -> Result<()> {
        use std::os::unix::fs::PermissionsExt;
        for entry in std::fs::read_dir(root)? {
            let entry = entry?;
            if entry.file_type()?.is_dir() {
                std::fs::set_permissions(entry.path(), std::fs::Permissions::from_mode(0o755))?;
                children(&entry.path())?;
            }
        }
        Ok(())
    }
    std::fs::set_permissions(root, std::fs::Permissions::from_mode(0o700))?;
    children(root)?;
    Ok(())
}
fn lifecycle(action: &str, c: &Configuration, flags: &Flags) -> Result<Value> {
    let selected = services(c, flags)?;
    let filtered = flags.contains_key("services")
        || flags.contains_key("exclude")
        || c.default_services.as_ref().is_some_and(|v| !v.is_empty());
    match action {
        "start" => {
            startup::start(c, selected)?;
        }
        "stop" => {
            let _critical = operation::critical()?;
            if filtered {
                docker(c, std::iter::once("stop".into()).chain(selected))?;
            } else {
                docker(c, ["down".into()])?;
            }
        }
        "restart" => {
            if c.deployment_mode == "official_cloud" && boolean(flags, "rebuild") {
                return Err(Error::Invalid(
                    "Official-cloud rebuilds require the remaining native cloud update verification.",
                ));
            }
            if boolean(flags, "rebuild") {
                data::rebuild(c, flags)?;
            } else {
                if boolean(flags, "reset-cache") {
                    return Err(Error::Invalid("--reset-cache requires --rebuild."));
                }
                let _critical = operation::critical()?;
                docker(c, std::iter::once("restart".into()).chain(selected))?;
            }
        }
        "status" => {
            let mut args = vec!["ps".into(), "--format".into(), "json".into()];
            if filtered {
                args.extend(selected);
            }
            let out = docker(c, args)?;
            let containers = if out.is_empty() {
                json!([])
            } else if let Ok(v) = serde_json::from_slice::<Value>(&out) {
                if v.is_array() { v } else { json!([v]) }
            } else {
                let values = std::str::from_utf8(&out)
                    .map_err(|_| Error::Protocol)?
                    .lines()
                    .filter(|s| !s.trim().is_empty())
                    .map(serde_json::from_str::<Value>)
                    .collect::<std::result::Result<Vec<_>, _>>()?;
                json!(values)
            };
            return Ok(
                json!({"command":"status","status":"success","path":c.install_path,"role":c.server_role,"mode":c.install_mode,"apiUrl":c.api_url,"appUrl":c.app_url,"containers":containers,"deploymentMode":c.deployment_mode,"openMatesCloudOverlayPath":c.overlay_path}),
            );
        }
        "logs" => {
            let mut args = compose(c);
            args.push("logs".into());
            for key in ["tail", "since", "until"] {
                if let Some(value) = text(flags, key) {
                    args.extend([format!("--{key}"), value.into()]);
                }
            }
            if boolean(flags, "follow") {
                args.push("--follow".into());
            }
            if boolean(flags, "timestamps") {
                args.push("--timestamps".into());
            }
            if let Some(service) = text(flags, "container") {
                if !services(c, &BTreeMap::from([("services".into(), json!(service))]))?
                    .contains(&service.to_owned())
                {
                    return Err(Error::Invalid("Unknown service."));
                }
                args.push(service.into());
            } else if filtered {
                args.extend(selected);
            }
            // Logs are explicitly requested operational output; stream directly
            // without retaining secrets in an application error or JSON object.
            operation::inherit(
                "docker",
                &args,
                &c.install_path,
                if boolean(flags, "follow") {
                    std::time::Duration::MAX
                } else {
                    std::time::Duration::from_secs(30 * 60)
                },
            )?;
        }
        _ => return Err(Error::Invalid("Unsupported lifecycle command.")),
    }
    Ok(json!({"command":action,"status":"success","path":c.install_path,"role":c.server_role}))
}
fn destructive(action: &str, c: &Configuration, flags: &Flags, state: &Path) -> Result<Value> {
    if !boolean(flags, "yes") {
        return Err(Error::Invalid("This destructive operation requires --yes."));
    }
    let home = directories::BaseDirs::new()
        .ok_or(Error::Io)?
        .home_dir()
        .to_path_buf();
    if c.install_path == Path::new("/")
        || c.install_path == home
        || c.install_path == state
        || state.starts_with(&c.install_path)
    {
        return Err(Error::Invalid(
            "Refusing destructive operation on a protected directory.",
        ));
    }
    let _critical = operation::critical()?;
    match action {
        "reset" => {
            data::reset(c, boolean(flags, "delete-user-data-only"))?;
        }
        "uninstall" => {
            // Inventory every unlink before stopping the runtime. A foreign
            // non-writable bind directory must not cause a partial uninstall
            // that has already erased the installation's private environment.
            let cleanup = match cleanup::Plan::prepare(&c.install_path) {
                Ok(plan) => plan,
                Err(failure) => return Ok(failure.output(c, false)),
            };
            let mut args = vec!["down".into(), "--rmi".into(), "local".into()];
            if !boolean(flags, "keep-data") {
                args.push("--volumes".into());
            }
            docker(c, args)?;
            if let Err(failure) = cleanup.remove() {
                return Ok(failure.output(c, true));
            }
            if config(state)?.is_some_and(|saved| saved.install_path == c.install_path) {
                std::fs::remove_file(state.join(CONFIG))?;
            }
        }
        _ => return Err(Error::Invalid("Unknown destructive command.")),
    }
    Ok(json!({"command":action,"status":"success","path":c.install_path}))
}
fn validate_options(action: &str, args: &[String], flags: &Flags) -> Result<()> {
    let allowed: &[&str] = match action {
        "register" => &[
            "official-cloud",
            "deployment-mode",
            "openmatescloud-path",
            "openmates-cloud-path",
            "role",
            "server-profile",
            "services",
            "exclude",
            "with-overrides",
            "yes",
        ],
        "install" => &[
            "official-cloud",
            "deployment-mode",
            "openmatescloud-path",
            "openmates-cloud-path",
            "role",
            "server-profile",
            "from-source",
            "source-path",
            "env-path",
            "image-tag",
            "channel",
            "branch",
            "with-overrides",
        ],
        "start" | "stop" | "status" => &[
            "role",
            "server-profile",
            "services",
            "exclude",
            "with-overrides",
        ],
        "restart" => &[
            "role",
            "server-profile",
            "services",
            "exclude",
            "rebuild",
            "reset-cache",
            "with-overrides",
        ],
        "logs" => &[
            "role",
            "services",
            "exclude",
            "container",
            "tail",
            "since",
            "until",
            "follow",
            "timestamps",
        ],
        "update" => &[
            "role",
            "server-profile",
            "services",
            "exclude",
            "image-tag",
            "channel",
            "dry-run",
            "skip-backup",
            "yes",
            "caddy-config",
            "caddy-profile",
            "continuous",
            "interval",
            "window",
            "continuous-update",
            "reuse-completed-setup",
        ],
        "update status" => &["role"],
        "update install-service" => &[
            "role",
            "continuous",
            "interval",
            "window",
            "channel",
            "dry-run",
        ],
        "backup" => &["role", "output"],
        "backup list" => &["role"],
        "restore" => &["role", "file", "yes"],
        "reset" => &["role", "yes", "delete-user-data-only"],
        "uninstall" => &["role", "yes", "keep-data"],
        "make-admin" => &["role"],
        "caddy" | "caddy check" | "caddy status" | "caddy diff" | "caddy apply" => {
            &["role", "config", "dry-run", "yes"]
        }
        "caddy update" => &["role", "caddy-config", "caddy-profile", "dry-run"],
        "verify" | "monitoring status" => &["role"],
        "monitoring run" => &["role", "watchdog"],
        "monitoring install-service" => &["role", "dry-run"],
        "monitoring report-watchdog" => &["role"],
        "monitoring digest" => &["role", "channel", "test"],
        "host-reporter" | "host-reporter status" => &[],
        "host-reporter install" => &[
            "role",
            "collector-url",
            "collector-cert",
            "collector-tls-cert",
            "no-enable",
            "dry-run",
        ],
        "host-reporter uninstall" => &["yes"],
        "notifications test" => &["role", "channel", "event-kind", "compact"],
        "env" | "env list" => &["role", "category"],
        "env get" => &["role"],
        "env set" => &["role", "value"],
        "env unset" => &["role", "yes"],
        "env check" | "env doctor" => &["role"],
        "env edit" => &["role"],
        "features" | "features list" | "features explain" | "features enable"
        | "features disable" | "features reset" => &["role"],
        "preflight" => &["role", "server-profile", "services", "exclude"],
        "test" => &[
            "role",
            "quick",
            "quick-test",
            "confirm-spend-credits",
            "skip-quick-test",
        ],
        "ai models" | "ai models list" | "ai models test" | "ai models remove" => &["role"],
        "ai models add" => &[
            "role",
            "runtime",
            "base-url",
            "api-key",
            "model",
            "creator",
            "id",
            "name",
            "images",
            "image",
            "vision",
            "tools",
            "tool-use",
            "context-window",
            "skip-test",
        ],
        _ => {
            return Err(Error::Invalid(
                "This server subcommand has not been ported to the native CLI.",
            ));
        }
    };
    for (key, value) in flags {
        if matches!(
            key.as_str(),
            "path" | "json" | "profile" | "api-url" | "state-dir" | "help"
        ) {
            continue;
        }
        if !allowed.contains(&key.as_str()) {
            return Err(Error::Invalid(
                "This option is not supported by the selected native server command; no operation was performed.",
            ));
        }
        let switch = matches!(
            key.as_str(),
            "from-source"
                | "official-cloud"
                | "with-overrides"
                | "rebuild"
                | "reset-cache"
                | "follow"
                | "timestamps"
                | "dry-run"
                | "skip-backup"
                | "yes"
                | "delete-user-data-only"
                | "keep-data"
                | "continuous"
                | "continuous-update"
                | "reuse-completed-setup"
                | "watchdog"
                | "compact"
                | "images"
                | "image"
                | "vision"
                | "tools"
                | "tool-use"
                | "skip-test"
                | "quick"
                | "quick-test"
                | "confirm-spend-credits"
                | "skip-quick-test"
                | "test"
        );
        if switch && !value.is_boolean()
            || !switch
                && !value.is_string()
                && !(matches!(key.as_str(), "services" | "exclude") && value.is_array())
        {
            return Err(Error::Invalid("Server option has an invalid value type."));
        }
    }
    if matches!(
        action,
        "make-admin"
            | "env get"
            | "env set"
            | "env unset"
            | "features explain"
            | "features enable"
            | "features disable"
            | "features reset"
            | "ai models test"
            | "ai models remove"
    ) {
        if args.len() != 1 {
            return Err(Error::Invalid(
                "This server command requires exactly one value.",
            ));
        }
    } else if matches!(action, "env" | "env list" | "env edit") {
        if args.len() > 1 {
            return Err(Error::Invalid("Provide at most one environment category."));
        }
    } else if !args.is_empty() {
        return Err(Error::Invalid(
            "Unexpected positional values for this server command.",
        ));
    }
    Ok(())
}
pub async fn execute(
    action: &str,
    positionals: &[String],
    flags: &Flags,
    state_dir: &Path,
) -> Result<Value> {
    execute_cancellable(
        action,
        positionals,
        flags,
        state_dir,
        &tokio_util::sync::CancellationToken::new(),
    )
    .await
}
pub async fn execute_cancellable(
    action: &str,
    positionals: &[String],
    flags: &Flags,
    state_dir: &Path,
    cancel: &tokio_util::sync::CancellationToken,
) -> Result<Value> {
    let cancel = cancel.child_token();
    let action = action.to_owned();
    let positionals = positionals.to_vec();
    let flags = SecretFlags(flags.clone());
    let state = state_dir.to_path_buf();
    // A cancelled front-end future cannot stop a half-finished durable command;
    // the blocking operation retains its installation lock through completion.
    tokio::task::spawn_blocking(move || {
        let _scope = operation::Scope::new(&cancel);
        operation::check()?;
        fs::directory(&state, true)?;
        let result = (|| {
            let _positionals = zeroize::Zeroizing::new(positionals);
            validate_options(&action, &_positionals, &flags)?;
            if matches!(
                action.as_str(),
                "caddy" | "caddy check" | "caddy status" | "caddy diff" | "caddy apply"
            ) {
                overlay::reject_cloud_caddy(&flags, &state)?;
                let selected_role = if let Some(value) = text(&flags, "role") {
                    role(value)?.to_owned()
                } else {
                    config(&state)?
                        .map(|c| c.server_role)
                        .unwrap_or_else(default_role)
                };
                return caddy::basic(
                    action.strip_prefix("caddy ").unwrap_or("status"),
                    &selected_role,
                    &flags,
                );
            }
            if action == "install" {
                let output = install(&flags, &state)?;
                if std::env::var("OPENMATES_SKIP_RUNTIME_MONITORING").as_deref() != Ok("1") {
                    let installed = installation(&flags, &state)?;
                    if installed.deployment_mode != "official_cloud" {
                        monitoring::execute(
                            "monitoring install-service",
                            &installed,
                            &Flags::new(),
                        )?;
                    }
                }
                return Ok(output);
            }
            if action == "register" {
                return configuration::register(&flags, &state);
            }
            // Host-level systemd service; independent of any server.json installation.
            if action == "host-reporter" || action.starts_with("host-reporter ") {
                return host_reporter::execute(&action, &flags);
            }
            let saved = config(&state)?;
            let selected_path = match text(&flags, "path") {
                Some(path) => normalized_path(path)?,
                None => saved
                    .as_ref()
                    .map(|c| c.install_path.clone())
                    .unwrap_or(std::env::current_dir()?),
            };
            let _source_scope = if saved.as_ref().is_some_and(|c| {
                c.install_path == selected_path
                    && c.install_mode == "source"
                    && c.source_strategy.as_deref() == Some("working_tree")
            }) {
                Some(fs::source_scope(&selected_path)?)
            } else {
                None
            };
            let mut c = installation(&flags, &state)?;
            overlay::supported_action(&c, &action)?;
            let _lock = fs::Lock::acquire(&c.install_path)?;
            if boolean(&flags, "with-overrides") {
                if c.server_role != "core" {
                    return Err(Error::Invalid(
                        "Compose overrides apply only to the core server role.",
                    ));
                }
                fs::read(
                    &c.install_path
                        .join("backend/core/docker-compose.override.yml"),
                    8 * 1024 * 1024,
                )?;
                c.compose_profile = "full".into();
                save_config(&state, &c)?;
            }
            match action.as_str() {
                "start" | "stop" | "restart" | "status" | "logs" => lifecycle(&action, &c, &flags),
                "update" | "update status" => update::execute(&action, &c, &flags, &state),
                "update install-service" => updater::install_service(&c, &flags, &state),
                "reset" | "uninstall" => destructive(&action, &c, &flags, &state),
                "backup" => backup::create(&c, &flags),
                "backup list" => backup::list(&c),
                "restore" => backup::restore(&c, &flags),
                "make-admin" => make_admin(&c, &_positionals),
                "caddy update" => caddy::release(&c, &flags),
                "verify"
                | "monitoring run"
                | "monitoring status"
                | "monitoring install-service" => monitoring::execute(&action, &c, &flags),
                "notifications test" => notifications::test(&c, &flags),
                "monitoring report-watchdog" => reports::watchdog(&c),
                "monitoring digest" => reports::digest(&c, &flags),
                "env" | "env list" | "env get" | "env set" | "env unset" | "env check"
                | "env doctor" | "env edit" => {
                    configuration::environment(&action, &c, &_positionals, &flags)
                }
                "features" | "features list" | "features explain" | "features enable"
                | "features disable" | "features reset" => {
                    configuration::features(&action, &c, &_positionals)
                }
                "preflight" => configuration::preflight(&c),
                "ai models" | "ai models list" | "ai models add" | "ai models test"
                | "ai models remove" => local_models::execute(&action, &c, &_positionals, &flags),
                _ => Err(Error::Invalid(
                    "This server subcommand has not been ported to the native CLI.",
                )),
            }
        })();
        operation::finish(&action, &state, result)
    })
    .await
    .map_err(|_| Error::Io)?
}

fn make_admin(c: &Configuration, args: &[String]) -> Result<Value> {
    use base64::Engine;
    use sha2::{Digest, Sha256};
    if c.server_role != "core" {
        return Err(Error::Invalid("make-admin requires a core installation."));
    }
    let email = args
        .first()
        .filter(|s| s.len() <= 320 && s.contains('@') && !s.contains(['\n', '\r', '\0']))
        .ok_or(Error::Invalid("Usage: server make-admin EMAIL"))?;
    let hash = base64::engine::general_purpose::STANDARD
        .encode(Sha256::digest(email.trim().to_lowercase().as_bytes()));
    // Only a base64 hash is interpolated, never user-supplied SQL. The exact
    // principal remains private. Transactional grant mirrors Directus policy.
    let sql = Zeroizing::new(format!(
        "BEGIN;\nDO $$ BEGIN IF (SELECT count(*) FROM directus_users WHERE hashed_email='{hash}') != 1 THEN RAISE EXCEPTION 'account not found'; END IF; END $$;\nINSERT INTO server_admins (id, hashed_user_id, granted_at, is_active) SELECT gen_random_uuid(), encode(sha256(convert_to(id::text,'UTF8')),'hex'), now(), true FROM directus_users WHERE hashed_email='{hash}' ON CONFLICT (hashed_user_id) DO UPDATE SET is_active=true, revoked_at=NULL;\nUPDATE directus_users SET is_admin=true WHERE hashed_email='{hash}' RETURNING id;\nCOMMIT;\n"
    ));
    let content = env(&c.install_path)?;
    let user = env_get(&content, "DATABASE_USERNAME").unwrap_or("directus");
    let database = env_get(&content, "DATABASE_NAME").unwrap_or("directus");
    let mut args = compose(c);
    args.extend([
        "exec".into(),
        "-T".into(),
        "cms-database".into(),
        "psql".into(),
        "-v".into(),
        "ON_ERROR_STOP=1".into(),
        "-qAt".into(),
        "-U".into(),
        user.into(),
        "--dbname".into(),
        database.into(),
    ]);
    let _critical = operation::critical()?;
    let result = run("docker", &args, &c.install_path, Some(sql.as_bytes()))?;
    let id = std::str::from_utf8(&result)
        .map_err(|_| Error::Protocol)?
        .lines()
        .find_map(|line| uuid::Uuid::parse_str(line.trim()).ok())
        .ok_or(Error::Protocol)?;
    // Invalidate only this user's shared auth profile, retaining sessions/TTL.
    // REDISCLI_AUTH is passed over stdin via redis-cli -x AUTH followed by
    // commands in an interactive RESP stream, never via process arguments.
    let password = env_get(&content, "DRAGONFLY_PASSWORD")
        .ok_or(Error::Invalid("Cache password is missing."))?;
    let channel = format!("user_updates::{id}");
    let payload=json!({"event_for_client":"user_admin_status_updated","user_id_uuid":id.to_string(),"payload":{"is_admin":true}}).to_string();
    fn resp(out: &mut String, args: &[&str]) {
        out.push_str(&format!("*{}\r\n", args.len()));
        for arg in args {
            out.push_str(&format!("${}\r\n{}\r\n", arg.len(), arg));
        }
    }
    let mut stream = Zeroizing::new(String::new());
    resp(&mut stream, &["AUTH", password]);
    resp(&mut stream, &["DEL", &format!("user_profile:{id}")]);
    resp(&mut stream, &["PUBLISH", &channel, &payload]);
    let mut args = compose(c);
    args.extend([
        "exec".into(),
        "-T".into(),
        "cache".into(),
        "redis-cli".into(),
        "--pipe".into(),
    ]);
    run("docker", &args, &c.install_path, Some(stream.as_bytes()))?;
    Ok(json!({"command":"make-admin","status":"success"}))
}

#[cfg(test)]
mod fake {
    use super::*;
    use std::{cell::RefCell, collections::VecDeque};
    pub(super) struct Call {
        pub program: &'static str,
        pub args: Vec<String>,
        pub output: Result<Vec<u8>>,
    }
    type InputChecker = fn(&[String], Option<&[u8]>);
    thread_local! {
        static CALLS:RefCell<Option<VecDeque<Call>>>=const{RefCell::new(None)};
        static INPUT_CHECKER:RefCell<Option<InputChecker>>=const{RefCell::new(None)};
    }
    pub(super) fn run(
        program: &str,
        args: &[String],
        _cwd: &Path,
        input: Option<&[u8]>,
    ) -> Option<Result<Zeroizing<Vec<u8>>>> {
        CALLS.with(|calls| {
            let mut calls = calls.borrow_mut();
            let calls = calls.as_mut()?;
            let expected = calls.pop_front().expect("unexpected system command");
            assert_eq!(program, expected.program);
            assert_eq!(args.len(), expected.args.len());
            for (actual, wanted) in args.iter().zip(&expected.args) {
                if wanted == "@CADDY_TEMP@" {
                    let path = Path::new(actual);
                    assert_eq!(path.file_name().unwrap(), "Caddyfile");
                    assert!(
                        path.parent()
                            .unwrap()
                            .file_name()
                            .unwrap()
                            .to_string_lossy()
                            .starts_with("openmates-caddy-")
                    );
                } else {
                    assert_eq!(actual, wanted);
                }
            }
            INPUT_CHECKER.with(|checker| {
                if let Some(checker) = *checker.borrow() {
                    checker(args, input);
                }
            });
            Some(expected.output.map(Zeroizing::new))
        })
    }
    pub(super) fn with_input_checker<T>(
        calls: Vec<Call>,
        checker: InputChecker,
        body: impl FnOnce() -> T,
    ) -> T {
        struct Reset;
        impl Drop for Reset {
            fn drop(&mut self) {
                INPUT_CHECKER.with(|checker| *checker.borrow_mut() = None);
            }
        }
        INPUT_CHECKER.with(|slot| {
            assert!(slot.borrow().is_none());
            *slot.borrow_mut() = Some(checker);
        });
        let _reset = Reset;
        with(calls, body)
    }
    pub(super) fn with<T>(calls: Vec<Call>, body: impl FnOnce() -> T) -> T {
        struct Reset;
        impl Drop for Reset {
            fn drop(&mut self) {
                CALLS.with(|c| *c.borrow_mut() = None)
            }
        }
        CALLS.with(|c| {
            assert!(c.borrow().is_none());
            *c.borrow_mut() = Some(calls.into());
        });
        let _reset = Reset;
        let result = body();
        CALLS.with(|c| {
            assert!(
                c.borrow().as_ref().unwrap().is_empty(),
                "expected system commands were not executed"
            )
        });
        result
    }
}
#[cfg(test)]
mod tests {
    use super::*;
    pub(super) fn c() -> Configuration {
        Configuration {
            install_path: "/isolated".into(),
            installed_at: 0,
            compose_profile: "core".into(),
            server_role: "core".into(),
            server_profile: "minimal".into(),
            install_mode: "image".into(),
            source_strategy: None,
            image_tag: Some("v1".into()),
            image_channel: None,
            default_services: None,
            api_url: None,
            app_url: None,
            deployment_mode: overlay::default_mode(),
            overlay_path: None,
        }
    }
    const ADMIN_FIXTURE_ID: &str = "02f1c86e-1e69-46a3-81de-d1b4d6e2b534";
    fn check_admin_transaction_and_cache_input(args: &[String], input: Option<&[u8]>) {
        let input = std::str::from_utf8(input.expect("admin commands need private stdin")).unwrap();
        assert!(!input.contains("Fixture.Admin@example.test"));
        assert!(!input.contains("fixture.admin@example.test"));
        assert!(args.iter().all(|arg| !arg.contains("fixture-password")));
        if args.iter().any(|arg| arg == "psql") {
            // Model the canonical schema, not Directus's /users HTTP alias.
            // Every queried/updated relation must exist in this schema.
            let words: Vec<_> = input.split_whitespace().collect();
            let mut relations = Vec::new();
            for pair in words.windows(2) {
                if pair[0] == "FROM"
                    || pair[0] == "INTO"
                    || (pair[0] == "UPDATE" && pair[1] != "SET")
                {
                    assert!(matches!(pair[1], "directus_users" | "server_admins"));
                    relations.push(pair[1]);
                }
            }
            assert_eq!(
                relations,
                [
                    "directus_users",
                    "server_admins",
                    "directus_users",
                    "directus_users"
                ]
            );
            let statements: Vec<_> = input.lines().collect();
            assert_eq!(statements.len(), 5);
            assert_eq!(statements[0], "BEGIN;");
            assert!(statements[1].contains("SELECT count(*) FROM directus_users"));
            assert!(statements[1].contains("!= 1 THEN RAISE EXCEPTION"));
            assert!(statements[2].starts_with("INSERT INTO server_admins "));
            assert!(statements[2].contains("encode(sha256(convert_to(id::text,'UTF8')),'hex')"));
            assert!(statements[2].ends_with(
                "ON CONFLICT (hashed_user_id) DO UPDATE SET is_active=true, revoked_at=NULL;"
            ));
            assert!(statements[3].starts_with("UPDATE directus_users SET is_admin=true "));
            assert!(statements[3].ends_with("RETURNING id;"));
            assert_eq!(statements[4], "COMMIT;");
            // Independent known-answer hash of the normalized fixture email.
            assert_eq!(
                input
                    .matches("WHERE hashed_email='AWVKCZ/+GtLeXqs6Fi5Yt/JiET6KS4Z7ayMM+miIGFQ='")
                    .count(),
                3
            );
            return;
        }
        let mut parts = input.split("\r\n");
        let mut commands = Vec::new();
        while let Some(header) = parts.next() {
            if header.is_empty() {
                assert!(parts.next().is_none());
                break;
            }
            let count: usize = header.strip_prefix('*').unwrap().parse().unwrap();
            let mut command = Vec::new();
            for _ in 0..count {
                let len: usize = parts
                    .next()
                    .unwrap()
                    .strip_prefix('$')
                    .unwrap()
                    .parse()
                    .unwrap();
                let argument = parts.next().unwrap();
                assert_eq!(argument.len(), len);
                command.push(argument);
            }
            commands.push(command);
        }
        assert_eq!(commands.len(), 3);
        assert_eq!(commands[0], ["AUTH", "fixture-password"]);
        assert_eq!(
            commands[1],
            ["DEL", &format!("user_profile:{ADMIN_FIXTURE_ID}")]
        );
        assert_eq!(commands[2].len(), 3);
        assert_eq!(commands[2][0], "PUBLISH");
        assert_eq!(commands[2][1], format!("user_updates::{ADMIN_FIXTURE_ID}"));
        assert_eq!(
            serde_json::from_str::<Value>(commands[2][2]).unwrap(),
            json!({"event_for_client":"user_admin_status_updated","user_id_uuid":ADMIN_FIXTURE_ID,"payload":{"is_admin":true}})
        );
    }
    fn admin_command(c: &Configuration, tail: &[&str], output: Result<Vec<u8>>) -> fake::Call {
        let mut args = compose(c);
        args.extend(tail.iter().map(|arg| (*arg).to_owned()));
        fake::Call {
            program: "docker",
            args,
            output,
        }
    }
    const ADMIN_PSQL: &[&str] = &[
        "exec",
        "-T",
        "cms-database",
        "psql",
        "-v",
        "ON_ERROR_STOP=1",
        "-qAt",
        "-U",
        "fixture-db-user",
        "--dbname",
        "fixture-db",
    ];
    #[test]
    fn make_admin_uses_canonical_schema_transaction_before_targeted_cache_event() {
        use std::os::unix::fs::PermissionsExt;
        let root = tempfile::Builder::new()
            .permissions(std::fs::Permissions::from_mode(0o700))
            .tempdir()
            .unwrap();
        let mut c = c();
        c.install_path = root.path().into();
        fs::write(&root.path().join(".env"), b"DATABASE_USERNAME=fixture-db-user\nDATABASE_NAME=fixture-db\nDRAGONFLY_PASSWORD=fixture-password\n", 0o600).unwrap();
        let calls = vec![
            admin_command(
                &c,
                ADMIN_PSQL,
                Ok(format!("{ADMIN_FIXTURE_ID}\n").into_bytes()),
            ),
            admin_command(
                &c,
                &["exec", "-T", "cache", "redis-cli", "--pipe"],
                Ok(Vec::new()),
            ),
        ];
        let result =
            fake::with_input_checker(calls, check_admin_transaction_and_cache_input, || {
                make_admin(&c, &["  Fixture.Admin@example.test  ".into()])
            })
            .unwrap();
        assert_eq!(result, json!({"command":"make-admin","status":"success"}));
    }
    #[test]
    fn make_admin_failed_transaction_or_invalid_uuid_never_touches_cache() {
        use std::os::unix::fs::PermissionsExt;
        let root = tempfile::Builder::new()
            .permissions(std::fs::Permissions::from_mode(0o700))
            .tempdir()
            .unwrap();
        let mut c = c();
        c.install_path = root.path().into();
        fs::write(&root.path().join(".env"), b"DATABASE_USERNAME=fixture-db-user\nDATABASE_NAME=fixture-db\nDRAGONFLY_PASSWORD=fixture-password\n", 0o600).unwrap();
        // A schema/cardinality rejection is a nonzero psql result; no cache
        // command is permitted. Successful SQL with no valid UUID is also closed.
        for output in [Err(Error::Io), Ok(b"not-a-user-uuid\n".to_vec())] {
            let sql_failed = output.is_err();
            let result = fake::with_input_checker(
                vec![admin_command(&c, ADMIN_PSQL, output)],
                check_admin_transaction_and_cache_input,
                || make_admin(&c, &["Fixture.Admin@example.test".into()]),
            );
            if sql_failed {
                assert!(matches!(result, Err(Error::Io)));
            } else {
                assert!(matches!(result, Err(Error::Protocol)));
            }
        }
    }
    #[test]
    fn plans_service_scope_without_shell_expansion() {
        let c = c();
        assert!(
            services(
                &c,
                &Flags::from([("services".into(), json!("api; touch /tmp/unsafe"))])
            )
            .is_err()
        );
        let selected = services(
            &c,
            &Flags::from([
                ("services".into(), json!(["api", "cms"])),
                ("exclude".into(), json!("cms")),
            ]),
        )
        .unwrap();
        assert_eq!(selected, vec!["api"]);
        assert!(
            !services(&c, &Flags::new())
                .unwrap()
                .contains(&"prometheus".into())
        );
        assert_eq!(compose(&c)[4], "backend/core/docker-compose.selfhost.yml");
        assert!(
            validate_options(
                "backup",
                &[],
                &Flags::from([("include-observability".into(), json!(true))])
            )
            .is_err()
        );
        assert!(
            validate_options(
                "start",
                &[],
                &Flags::from([
                    ("path".into(), json!("/isolated")),
                    ("services".into(), json!("api"))
                ])
            )
            .is_ok()
        );
    }
    #[test]
    fn source_clone_uses_private_target_instead_of_shared_temporary_parent() {
        use std::os::unix::fs::{MetadataExt, PermissionsExt};
        let target = tempfile::Builder::new()
            .permissions(std::fs::Permissions::from_mode(0o700))
            .tempdir_in("/tmp")
            .unwrap();
        let parent_before = std::fs::metadata("/tmp").unwrap();
        let mut invoked = false;
        clone_source(
            target.path(),
            "/fixture/source".into(),
            Some("dev"),
            |args, cwd| {
                invoked = true;
                assert_eq!(cwd, target.path());
                assert_ne!(cwd, target.path().parent().unwrap());
                assert_eq!(
                    args,
                    [
                        "clone",
                        "--branch",
                        "dev",
                        "--",
                        "/fixture/source",
                        target.path().to_str().unwrap()
                    ]
                );
                let root = std::fs::symlink_metadata(cwd).unwrap();
                assert!(root.is_dir());
                assert_eq!(root.uid(), rustix::process::geteuid().as_raw());
                assert_eq!(root.mode() & 0o777, 0o700);
                assert!(std::fs::read_dir(cwd).unwrap().next().is_none());
                Ok(())
            },
        )
        .unwrap();
        assert!(invoked);
        let parent_after = std::fs::metadata("/tmp").unwrap();
        assert_eq!(parent_before.mode(), parent_after.mode());
        assert_eq!(parent_before.uid(), parent_after.uid());
    }
    #[test]
    fn source_clone_creates_missing_target_and_preserves_argument_boundaries() {
        use std::os::unix::fs::PermissionsExt;
        let root = tempfile::Builder::new()
            .permissions(std::fs::Permissions::from_mode(0o700))
            .tempdir()
            .unwrap();
        let target = root.path().join("new install");
        let mut invoked = false;
        clone_source(
            &target,
            "/fixture/source with spaces".into(),
            None,
            |args, cwd| {
                invoked = true;
                assert_eq!(cwd, target);
                assert_eq!(
                    args,
                    [
                        "clone",
                        "--",
                        "/fixture/source with spaces",
                        target.to_str().unwrap()
                    ]
                );
                assert_eq!(
                    std::fs::metadata(cwd).unwrap().permissions().mode() & 0o777,
                    0o700
                );
                Ok(())
            },
        )
        .unwrap();
        assert!(invoked);
    }
    #[test]
    fn source_clone_rejects_symlink_and_writable_target_before_launch() {
        use std::os::unix::fs::PermissionsExt;
        let root = tempfile::Builder::new()
            .permissions(std::fs::Permissions::from_mode(0o700))
            .tempdir()
            .unwrap();
        let target = root.path().join("target");
        std::os::unix::fs::symlink(root.path(), &target).unwrap();
        assert!(
            clone_source(&target, "/fixture/source".into(), None, |_, _| {
                panic!("Git must not run for a symlink target")
            })
            .is_err()
        );
        std::fs::remove_file(&target).unwrap();
        std::fs::create_dir(&target).unwrap();
        std::fs::set_permissions(&target, std::fs::Permissions::from_mode(0o777)).unwrap();
        assert!(
            clone_source(&target, "/fixture/source".into(), None, |_, _| {
                panic!("Git must not run for a writable target")
            })
            .is_err()
        );
    }
    #[test]
    fn environment_preserves_custom_secret_and_generates_missing() {
        let mut content =
            "SECRET__GOOGLE_AI_STUDIO__API_KEY=private\nDATABASE_PASSWORD=existing\n".to_string();
        env_set(&mut content, "OPENMATES_IMAGE_TAG", "fixture");
        assert_eq!(env_get(&content, "DATABASE_PASSWORD"), Some("existing"));
        assert_eq!(
            env_get(&content, "SECRET__GOOGLE_AI_STUDIO__API_KEY"),
            Some("private")
        );
        assert_eq!(env_get(&content, "OPENMATES_IMAGE_TAG"), Some("fixture"));
        assert!(image_tag(&Flags::from([("image-tag".into(), json!("$(id)"))]), None).is_err());
    }
    #[test]
    fn atomic_files_reject_symlinks_and_keep_secrets_private() {
        use std::os::unix::fs::PermissionsExt;
        let root = tempfile::Builder::new()
            .permissions(std::fs::Permissions::from_mode(0o700))
            .tempdir()
            .unwrap();
        let file = root.path().join(".env");
        fs::write(&file, b"secret", 0o600).unwrap();
        assert_eq!(
            std::fs::metadata(&file).unwrap().permissions().mode() & 0o777,
            0o600
        );
        let target = root.path().join("link");
        std::os::unix::fs::symlink(&file, &target).unwrap();
        assert!(fs::write(&target, b"changed", 0o600).is_err());
        assert_eq!(fs::read(&file, 32).unwrap(), b"secret");
        let _lock = fs::Lock::acquire(root.path()).unwrap();
        assert!(matches!(fs::Lock::acquire(root.path()), Err(Error::Locked)));
    }
    #[test]
    fn selfhost_contract_environment_preserves_optional_api_override() {
        use std::os::unix::fs::PermissionsExt;
        for source in [false, true] {
            for override_value in [None, Some(""), Some("https://api.fixture.invalid")] {
                let root = tempfile::Builder::new()
                    .permissions(std::fs::Permissions::from_mode(0o700))
                    .tempdir()
                    .unwrap();
                let initial = override_value
                    .map(|value| format!("VITE_API_URL={value}\n"))
                    .unwrap_or_default();
                fs::write(&root.path().join(".env"), initial.as_bytes(), 0o600).unwrap();
                write_environment(root.path(), Some("fixture-tag"), source).unwrap();
                let content = env(root.path()).unwrap();
                assert_eq!(
                    content
                        .lines()
                        .find_map(|line| line.strip_prefix("VITE_API_URL=")),
                    override_value
                );
                assert_eq!(
                    env_get(&content, "VITE_API_URL"),
                    override_value.filter(|s| !s.is_empty())
                );
            }
        }
    }
    #[test]
    fn image_install_writes_private_secrets_and_native_defaults_without_a_service_mutation() {
        use std::os::unix::fs::PermissionsExt;
        let root = tempfile::Builder::new()
            .permissions(std::fs::Permissions::from_mode(0o700))
            .tempdir()
            .unwrap();
        let install_path = root.path().join("install");
        let state = root.path().join("native");
        let flags = Flags::from([
            ("path".into(), json!(install_path)),
            ("image-tag".into(), json!("fixture-tag")),
            ("server-profile".into(), json!("minimal")),
        ]);
        fake::with(
            vec![fake::Call {
                program: "docker",
                args: vec!["network".into(), "inspect".into(), "openmates".into()],
                output: Ok(b"[]".to_vec()),
            }],
            || install(&flags, &state).unwrap(),
        );
        let content = env(&install_path).unwrap();
        assert_eq!(
            env_get(&content, "VITE_API_URL"),
            None,
            "frontend API autodetection must remain the default"
        );
        assert!(
            !content
                .lines()
                .any(|line| line.starts_with("VITE_API_URL="))
        );
        assert_eq!(
            env_get(&content, "OPENMATES_IMAGE_TAG"),
            Some("fixture-tag")
        );
        assert_eq!(env_get(&content, "DATABASE_PASSWORD").unwrap().len(), 24);
        assert_eq!(
            std::fs::metadata(install_path.join("config/providers"))
                .unwrap()
                .permissions()
                .mode()
                & 0o7777,
            0o755
        );
        assert_eq!(
            std::fs::metadata(&install_path)
                .unwrap()
                .permissions()
                .mode()
                & 0o7777,
            0o700
        );
        assert_eq!(
            std::fs::metadata(install_path.join(".openmates"))
                .unwrap()
                .permissions()
                .mode()
                & 0o7777,
            0o700
        );
        assert_eq!(
            std::fs::metadata(install_path.join(".env"))
                .unwrap()
                .permissions()
                .mode()
                & 0o777,
            0o600
        );
        let public = install_path.join("backend/core/monitoring/prometheus/prometheus.yml");
        assert_eq!(
            std::fs::metadata(&public).unwrap().permissions().mode() & 0o777,
            0o644
        );
        assert_eq!(
            std::fs::metadata(public.parent().unwrap())
                .unwrap()
                .permissions()
                .mode()
                & 0o777,
            0o755
        );
        assert_eq!(
            installed_api(&state).unwrap().as_deref(),
            Some("http://127.0.0.1:8000")
        );
        assert!(!root.path().join(".openmates/server.json").exists());
        assert!(
            install(&flags, &state).is_err(),
            "existing installation must remain intact"
        );
    }
}
