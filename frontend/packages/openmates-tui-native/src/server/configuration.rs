//! Server environment and feature editing. Secret values never enter output.
use super::*;
use zeroize::Zeroize;
fn key(value: &str) -> Result<&str> {
    if value.is_empty()
        || value.len() > 256
        || !value.as_bytes()[0].is_ascii_uppercase()
        || !value
            .bytes()
            .all(|b| b.is_ascii_uppercase() || b.is_ascii_digit() || b == b'_')
    {
        return Err(Error::Invalid(
            "Environment keys use uppercase letters, digits and underscores.",
        ));
    }
    Ok(value)
}
fn secret(key: &str, value: &str) -> bool {
    key.starts_with("SECRET__")
        || [
            "PASSWORD",
            "TOKEN",
            "SECRET",
            "API_KEY",
            "PRIVATE_KEY",
            "WEBHOOK",
            "CREDENTIAL",
            "AUTHORIZATION",
        ]
        .iter()
        .any(|s| key.contains(s))
        || url::Url::parse(value).ok().is_some_and(|u| {
            u.password().is_some()
                || u.query_pairs().any(|(k, _)| {
                    ["key", "api_key", "token", "secret", "password", "signature"]
                        .contains(&k.to_lowercase().as_str())
                })
        })
}
fn redacted(key: &str, value: &str) -> Value {
    json!(
        if !value.is_empty() && value != "IMPORTED_TO_VAULT" && secret(key, value) {
            "<redacted>"
        } else {
            value
        }
    )
}
fn category(key: &str) -> &'static str {
    if key.starts_with("OPENOBSERVE_") || key.starts_with("DISCORD_WEBHOOK_") {
        "observability"
    } else if key.starts_with("CELERY_")
        || key.ends_with("_CONCURRENCY")
        || key.ends_with("_MEMORY_LIMIT")
        || matches!(key, "GIT_WORK_DIR" | "DOCKER_GID" | "TUNNEL_TRIGGER_SECRET")
    {
        "advanced"
    } else if key.starts_with("SECRET__GOOGLE__OAUTH_")
        || [
            "SECRET__PROTONMAIL__",
            "SECRET__ADMIN_DEBUG_CLI__",
            "SECRET__UPLOAD_SERVER__",
            "SECRET__PREVIEW_SERVER__",
            "SECRET__STRIPE__",
            "SECRET__REVOLUT_BUSINESS__",
            "SECRET__INVOICE_",
        ]
        .iter()
        .any(|s| key.starts_with(s))
        || matches!(
            key,
            "GOOGLE_CALENDAR_OAUTH_REDIRECT_URI"
                | "PROD_CORE_API_URL"
                | "PROD_INTERNAL_API_SHARED_TOKEN"
                | "DEV_CORE_API_URL"
                | "DEV_INTERNAL_API_SHARED_TOKEN"
                | "PREVIEW_CORS_ORIGINS"
                | "PREVIEW_ALLOWED_REFERERS"
                | "REPORT_ISSUE_EMAIL"
                | "ADMIN_NOTIFY_EMAIL"
                | "DAILY_MEETING_NOTIFY_EMAIL"
        )
    {
        "integrations"
    } else if key.starts_with("SECRET__") {
        "providers"
    } else {
        "runtime"
    }
}
fn entries(content: &str) -> Vec<Value> {
    let mut entries = vec![];
    for line in content.lines() {
        let line = line.trim();
        if line.starts_with('#') {
            continue;
        }
        let Some((name, value)) = line.split_once('=') else {
            continue;
        };
        let name = name.trim();
        if key(name).is_err() {
            continue;
        }
        let value = value.trim().trim_matches('"').trim_matches('\'');
        let redacted = redacted(name, value);
        entries.push(json!({"key":name,"value":redacted,"redactedValue":redacted,"secret":secret(name,value),"category":category(name)}));
    }
    entries.sort_by_key(|v| {
        (
            v["category"].as_str().unwrap_or_default().to_owned(),
            v["key"].as_str().unwrap_or_default().to_owned(),
        )
    });
    entries
}
fn erase(value: &mut Value) {
    match value {
        Value::String(s) => s.zeroize(),
        Value::Array(v) => v.iter_mut().for_each(erase),
        Value::Object(v) => v.values_mut().for_each(erase),
        _ => {}
    }
}
#[derive(Serialize)]
#[serde(transparent)]
struct PrivateValue(Value);
impl std::ops::Deref for PrivateValue {
    type Target = Value;
    fn deref(&self) -> &Value {
        &self.0
    }
}
impl std::ops::DerefMut for PrivateValue {
    fn deref_mut(&mut self) -> &mut Value {
        &mut self.0
    }
}
impl Drop for PrivateValue {
    fn drop(&mut self) {
        erase(&mut self.0)
    }
}
fn vault_presence(c: &Configuration, keys: &[String]) -> BTreeMap<String, &'static str> {
    let mut result = BTreeMap::new();
    if keys.is_empty() {
        return result;
    }
    let container = match c.server_role.as_str() {
        "core" => "api",
        "upload" => "app-uploads",
        _ => return keys.iter().map(|k| (k.clone(), "unavailable")).collect(),
    };
    let mut args = compose(c);
    args.extend([
        "exec".into(),
        "-T".into(),
        container.into(),
        "cat".into(),
        "/vault-data/api.token".into(),
    ]);
    let token = match run_timeout(
        "docker",
        &args,
        &c.install_path,
        None,
        std::time::Duration::from_secs(5),
    ) {
        Ok(value) => value,
        Err(_) => return keys.iter().map(|k| (k.clone(), "unavailable")).collect(),
    };
    let token = match std::str::from_utf8(&token) {
        Ok(token) => token.trim(),
        Err(_) => return keys.iter().map(|k| (k.clone(), "unavailable")).collect(),
    };
    if token.len() > 4096
        || token.is_empty()
        || !token
            .bytes()
            .all(|b| b.is_ascii_alphanumeric() || b"._-".contains(&b))
    {
        return keys.iter().map(|k| (k.clone(), "unavailable")).collect();
    }
    let header = Zeroizing::new(format!("X-Vault-Token: {token}\n"));
    for name in keys {
        let Some((provider, field)) = name
            .strip_prefix("SECRET__")
            .and_then(|s| s.split_once("__"))
        else {
            result.insert(name.clone(), "unavailable");
            continue;
        };
        if key(name).is_err() {
            result.insert(name.clone(), "unavailable");
            continue;
        }
        let mut args = compose(c);
        args.extend([
            "exec".into(),
            "-T".into(),
            container.into(),
            "curl".into(),
            "--silent".into(),
            "--show-error".into(),
            "--max-time".into(),
            "3".into(),
            "--max-filesize".into(),
            "1048576".into(),
            "--header".into(),
            "@-".into(),
            "--write-out".into(),
            "\n%{http_code}".into(),
            format!(
                "http://vault:8200/v1/kv/data/providers/{}",
                provider.to_lowercase()
            ),
        ]);
        let state = run_timeout(
            "docker",
            &args,
            &c.install_path,
            Some(header.as_bytes()),
            std::time::Duration::from_secs(5),
        )
        .ok()
        .and_then(|bytes| {
            let text = std::str::from_utf8(&bytes).ok()?;
            let (body, status) = text.rsplit_once('\n')?;
            if status == "404" {
                return Some("missing");
            }
            if status != "200" {
                return Some("unavailable");
            }
            let mut body: Value = serde_json::from_str(body).ok()?;
            let present = body["data"]["data"][field.to_lowercase()]
                .as_str()
                .is_some_and(|s| !s.is_empty());
            erase(&mut body);
            Some(if present { "present" } else { "missing" })
        })
        .unwrap_or("unavailable");
        result.insert(name.clone(), state);
    }
    result
}
pub(super) fn preflight(c: &Configuration) -> Result<Value> {
    let content = env(&c.install_path)?;
    let mut inline: Vec<String> = vec![];
    let mut imported: Vec<String> = vec![];
    let mut empty: Vec<String> = vec![];
    let mut seen = std::collections::BTreeSet::new();
    for line in content.lines() {
        let Some((name, _)) = line.split_once('=') else {
            continue;
        };
        let name = name.trim();
        if !name.starts_with("SECRET__") || !seen.insert(name.to_owned()) {
            continue;
        }
        let value = env_get(&content, name).unwrap_or_default();
        if value == "IMPORTED_TO_VAULT" {
            imported.push(name.into());
        } else if value.is_empty() || value == "<PLACEHOLDER>" {
            empty.push(name.into());
        } else {
            inline.push(name.into());
        }
    }
    let presence = vault_presence(c, &imported);
    let mut present = vec![];
    let mut missing = vec![];
    let mut unavailable = vec![];
    for name in &imported {
        match presence.get(name).copied().unwrap_or("unavailable") {
            "present" => present.push(name.clone()),
            "missing" => missing.push(name.clone()),
            _ => unavailable.push(name.clone()),
        }
    }
    let required: &[&str] = match c.server_role.as_str() {
        "core" => &[
            "DATABASE_ADMIN_EMAIL",
            "DATABASE_ADMIN_PASSWORD",
            "DATABASE_NAME",
            "DATABASE_USERNAME",
            "DATABASE_PASSWORD",
            "DIRECTUS_TOKEN",
            "DIRECTUS_SECRET",
            "DRAGONFLY_PASSWORD",
            "INTERNAL_API_SHARED_TOKEN",
        ],
        "upload" => &[
            "PROD_CORE_API_URL",
            "PROD_INTERNAL_API_SHARED_TOKEN",
            "DEV_CORE_API_URL",
            "DEV_INTERNAL_API_SHARED_TOKEN",
        ],
        _ => &["PREVIEW_CORS_ORIGINS", "PREVIEW_ALLOWED_REFERERS"],
    };
    let runtime = required
        .iter()
        .filter(|k| env_get(&content, k).is_none())
        .copied()
        .collect::<Vec<_>>();
    let blocked = !runtime.is_empty() || !missing.is_empty() || !unavailable.is_empty();
    Ok(
        json!({"command":"preflight","status":if blocked{"blocked"}else{"ok"},"path":c.install_path,"role":c.server_role,"profile":c.server_profile,"missingRequiredEnvKeys":runtime,"blocked":blocked,"secretPreflight":{"inlineSecretEnvKeys":inline,"importedSecretEnvKeys":imported,"emptySecretEnvKeys":empty,"importedVaultPresent":present,"importedVaultMissing":missing,"importedVaultUnavailable":unavailable,"vaultChecked":unavailable.is_empty(),"vaultUnavailableReason":if unavailable.is_empty(){Value::Null}else{json!("vault_presence_unavailable")}}}),
    )
}
pub(super) fn prompt() -> Result<Zeroizing<String>> {
    use crossterm::event::{Event, KeyCode, KeyEventKind, KeyModifiers};
    use std::io::IsTerminal;
    if !std::io::stdin().is_terminal() {
        return Err(Error::Invalid(
            "Provide --value for noninteractive environment editing.",
        ));
    }
    eprint!("Value (hidden): ");
    std::io::stderr().flush()?;
    crossterm::terminal::enable_raw_mode()?;
    struct Raw;
    impl Drop for Raw {
        fn drop(&mut self) {
            let _ = crossterm::terminal::disable_raw_mode();
            eprintln!();
        }
    }
    let _raw = Raw;
    let mut value = Zeroizing::new(String::new());
    loop {
        match crossterm::event::read()? {
            Event::Key(event) if event.kind == KeyEventKind::Press => match event.code {
                KeyCode::Enter => return Ok(value),
                KeyCode::Esc => return Err(Error::Cancelled),
                KeyCode::Char('c') if event.modifiers.contains(KeyModifiers::CONTROL) => {
                    return Err(Error::Cancelled);
                }
                KeyCode::Backspace => {
                    value.pop();
                }
                KeyCode::Char(ch) if !ch.is_control() && value.len() < 65536 => value.push(ch),
                _ => {}
            },
            _ => {}
        }
    }
}
struct Edit(PathBuf);
impl Drop for Edit {
    fn drop(&mut self) {
        let _ = std::fs::remove_file(&self.0);
    }
}
pub(super) fn environment(
    action: &str,
    c: &Configuration,
    args: &[String],
    flags: &Flags,
) -> Result<Value> {
    let mut content = env(&c.install_path)?;
    let path = c.install_path.join(".env");
    match action {
        "env" | "env list" => {
            let category = text(flags, "category").or_else(|| args.first().map(String::as_str));
            if category.is_some_and(|v| {
                !matches!(
                    v,
                    "providers" | "integrations" | "observability" | "advanced" | "runtime"
                )
            }) {
                return Err(Error::Invalid("Unknown environment category."));
            }
            let entries = entries(&content)
                .into_iter()
                .filter(|v| category.is_none_or(|s| v["category"] == s))
                .collect::<Vec<_>>();
            Ok(json!({"command":"env list","path":path,"entries":entries}))
        }
        "env get" => {
            let name = key(args
                .first()
                .ok_or(Error::Invalid("Provide an environment key."))?)?;
            Ok(
                json!({"command":action,"key":name,"value":env_get(&content,name).map(|value|redacted(name,value))}),
            )
        }
        "env set" => {
            let name = key(args
                .first()
                .ok_or(Error::Invalid("Provide an environment key."))?)?;
            let value = match flags.get("value").and_then(Value::as_str) {
                Some(value) => Zeroizing::new(value.to_owned()),
                None => prompt()?,
            };
            if value.len() > 65536 || value.contains(['\n', '\r', '\0']) {
                return Err(Error::Invalid(
                    "Environment values must be a bounded single line.",
                ));
            }
            env_set(&mut content, name, &value);
            fs::write(&path, content.as_bytes(), 0o600)?;
            Ok(json!({"command":action,"status":"success","key":name}))
        }
        "env unset" => {
            if !boolean(flags, "yes") {
                return Err(Error::Invalid(
                    "Removing an environment value requires --yes.",
                ));
            }
            let name = key(args
                .first()
                .ok_or(Error::Invalid("Provide an environment key."))?)?;
            let mut next = Zeroizing::new(String::new());
            for line in content.lines() {
                if !line
                    .trim_start()
                    .split_once('=')
                    .is_some_and(|(k, _)| k == name)
                {
                    next.push_str(line);
                    next.push('\n');
                }
            }
            fs::write(&path, next.as_bytes(), 0o600)?;
            Ok(json!({"command":action,"status":"success","key":name}))
        }
        "env check" | "env doctor" => {
            // npm prints exactly {command, role, missingRuntime, secretPreflight, ok}.
            let result = preflight(c)?;
            let ok = !result["blocked"].as_bool().unwrap_or(true)
                && result["secretPreflight"]["emptySecretEnvKeys"]
                    .as_array()
                    .is_some_and(Vec::is_empty);
            Ok(json!({
                "command": action,
                "role": result["role"],
                "missingRuntime": result["missingRequiredEnvKeys"],
                "secretPreflight": result["secretPreflight"],
                "ok": ok,
            }))
        }
        "env edit" => {
            let edit = Edit(
                c.install_path
                    .join(format!(".openmates/env-edit-{}.tmp", uuid::Uuid::new_v4())),
            );
            fs::write(&edit.0, content.as_bytes(), 0o600)?;
            let editor = std::env::var("EDITOR").unwrap_or_else(|_| "nano".into());
            if editor.is_empty() || editor.contains(['\n', '\r', '\0']) {
                return Err(Error::Invalid("EDITOR must name an executable."));
            }
            operation::interactive(
                &editor,
                &[edit.0.to_string_lossy().into_owned()],
                &c.install_path,
            )?;
            operation::check()?;
            let edited = Zeroizing::new(fs::read(&edit.0, 4 * 1024 * 1024)?);
            std::str::from_utf8(&edited)
                .map_err(|_| Error::Invalid("Edited environment must be UTF-8."))?;
            fs::write(&path, &edited, 0o600)?;
            Ok(json!({"command":action,"status":"success"}))
        }
        _ => Err(Error::Invalid("Unknown environment action.")),
    }
}
const KNOWN: &[(&str, &str)] = &[
    (
        "embed:code:application",
        "Application previews are still unstable",
    ),
    ("app:workflows", "Workflow app is not ready by default"),
    (
        "platform:projects",
        "Projects workspace is not ready by default",
    ),
    ("platform:plans", "Plans workspace is not ready by default"),
    (
        "platform:workflows",
        "Workflows workspace is off by default",
    ),
    ("platform:tasks", "Tasks workspace is not implemented yet"),
];
pub(super) fn register(flags: &Flags, state: &Path) -> Result<Value> {
    let path = match text(flags, "path") {
        Some(value) => normalized_path(value)?,
        None => std::env::current_dir()?,
    };
    let _source = fs::source_scope(&path)?;
    let selected_role = role(text(flags, "role").unwrap_or("core"))?;
    let selected_profile = profile(
        text(flags, "server-profile")
            .or_else(|| text(flags, "profile"))
            .unwrap_or("production"),
    )?;
    fs::read(
        &path.join(marker(selected_role, "source")),
        16 * 1024 * 1024,
    )?;
    let content = env(&path)?;
    let root = run_timeout(
        "git",
        &["rev-parse".into(), "--show-toplevel".into()],
        &path,
        None,
        std::time::Duration::from_secs(10),
    )?;
    if normalized_path(
        std::str::from_utf8(&root)
            .map_err(|_| Error::Protocol)?
            .trim(),
    )? != path
    {
        return Err(Error::Invalid(
            "Registration path must be the Git checkout root.",
        ));
    }
    let existing = config(state)?;
    if existing.as_ref().is_some_and(|c| c.install_path != path) && !boolean(flags, "yes") {
        return Err(Error::Invalid(
            "Another installation is registered. Use --yes to replace only the local registration.",
        ));
    }
    let mut c = Configuration {
        install_path: path.clone(),
        installed_at: existing
            .filter(|c| c.install_path == path)
            .map(|c| c.installed_at)
            .unwrap_or_else(now),
        compose_profile: if boolean(flags, "with-overrides") {
            "full"
        } else {
            "core"
        }
        .into(),
        server_role: selected_role.into(),
        server_profile: selected_profile.into(),
        install_mode: "source".into(),
        source_strategy: Some("working_tree".into()),
        image_tag: None,
        image_channel: None,
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
    overlay::resolve(&mut c, flags, &content, false)?;
    c.default_services = Some(services(&c, flags)?);
    if c.compose_profile == "full" {
        fs::read(
            &path.join("backend/core/docker-compose.override.yml"),
            16 * 1024 * 1024,
        )?;
    }
    if c.server_role != "core" {
        c.server_profile = "production".into();
    }
    save_config(state, &c)?;
    Ok(
        json!({"command":"register","status":"success","path":path,"mode":"source","sourceStrategy":"working_tree","role":c.server_role,"apiUrl":c.api_url,"appUrl":c.app_url,"deploymentMode":c.deployment_mode,"openMatesCloudOverlayPath":c.overlay_path,"nativeCloudVerificationAvailable":false}),
    )
}
pub(super) fn features(action: &str, c: &Configuration, args: &[String]) -> Result<Value> {
    let path = c.install_path.join(if c.install_mode == "image" {
        "config/backend_config.yml"
    } else {
        "backend/config/backend_config.yml"
    });
    let (bytes, mode) = fs::read_with_mode(&path, 4 * 1024 * 1024)?;
    let bytes = Zeroizing::new(bytes);
    let mut config = PrivateValue(
        serde_yaml::from_slice(&bytes)
            .map_err(|_| Error::Invalid("Backend configuration YAML is invalid."))?,
    );
    if !config.is_object() {
        return Err(Error::Protocol);
    }
    fn list(config: &Value, name: &str) -> Result<Vec<String>> {
        match config["feature_overrides"].get(name) {
            None | Some(Value::Null) => Ok(vec![]),
            Some(Value::Array(v)) => v
                .iter()
                .map(|v| v.as_str().map(str::to_owned).ok_or(Error::Protocol))
                .collect(),
            _ => Err(Error::Protocol),
        }
    }
    let mut enabled = list(&config, "enabled")?;
    let mut disabled = list(&config, "disabled")?;
    if let Some(legacy) = config["disabled_apps"].as_array() {
        for value in legacy {
            let name = value.as_str().ok_or(Error::Protocol)?;
            let name = if name.starts_with("app:") {
                name.into()
            } else {
                format!("app:{name}")
            };
            if !disabled.contains(&name) {
                disabled.push(name)
            }
        }
    }
    if matches!(action, "features" | "features list") {
        return Ok(
            json!({"command":"features list","enabled":enabled,"disabled":disabled,"knownOffByDefault":KNOWN.iter().map(|(id,reason)|json!({"id":id,"reason":reason})).collect::<Vec<_>>()}),
        );
    }
    let id = args
        .first()
        .filter(|s| !s.is_empty() && s.len() <= 256 && !s.contains(['\n', '\r', '\0']))
        .ok_or(Error::Invalid("Provide a feature identifier."))?;
    if action == "features explain" {
        let reason = KNOWN
            .iter()
            .find(|(name, _)| name == id)
            .map(|(_, reason)| *reason);
        let over = if enabled.contains(id) {
            "enabled"
        } else if disabled.contains(id) {
            "disabled"
        } else {
            "none"
        };
        let effective = if over != "none" {
            over
        } else if reason.is_some() {
            "disabled"
        } else {
            "enabled"
        };
        return Ok(
            json!({"command":action,"feature":id,"default":if reason.is_some(){"off"}else{"on"},"reason":reason,"override":over,"effectiveAfterRestart":effective}),
        );
    }
    enabled.retain(|v| v != id);
    disabled.retain(|v| v != id);
    match action {
        "features enable" => enabled.push(id.clone()),
        "features disable" => disabled.push(id.clone()),
        "features reset" => {}
        _ => return Err(Error::Invalid("Unknown feature action.")),
    }
    enabled.sort();
    enabled.dedup();
    disabled.sort();
    disabled.dedup();
    config["feature_overrides"] = json!({"enabled":enabled,"disabled":disabled});
    config
        .as_object_mut()
        .ok_or(Error::Protocol)?
        .remove("disabled_apps");
    let bytes = Zeroizing::new(serde_yaml::to_string(&config).map_err(|_| Error::Protocol)?);
    fs::write(&path, bytes.as_bytes(), mode)?;
    Ok(json!({"command":action,"status":"success","feature":id,"restartRequired":true,"path":path}))
}
#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn every_environment_output_field_redacts_secrets_and_embedded_credentials() {
        let output = json!(entries(
            "DATABASE_PASSWORD=private\nCELERY_BROKER_URL=redis://user:private@cache:6379\nDISCORD_WEBHOOK_URL=https://discord.com/api/webhooks/private\nPRODUCTION_URL=https://example.org\nSECRET__GOOGLE_AI_STUDIO__API_KEY=IMPORTED_TO_VAULT\n"
        ));
        let serialized = output.to_string();
        assert!(!serialized.contains("private"));
        assert!(serialized.contains("IMPORTED_TO_VAULT"));
        assert!(serialized.contains("https://example.org"));
        assert!(key("BAD\nKEY").is_err());
    }
    #[test]
    fn feature_edits_preserve_unrelated_configuration_and_require_restart() {
        use std::os::unix::fs::PermissionsExt;
        let root = tempfile::Builder::new()
            .permissions(std::fs::Permissions::from_mode(0o700))
            .tempdir()
            .unwrap();
        let mut c = super::super::tests::c();
        c.install_path = root.path().to_path_buf();
        let path = root.path().join("config/backend_config.yml");
        fs::write(&path,b"custom:\n  preserved: true\ndisabled_apps:\n  - music\nfeature_overrides:\n  enabled: []\n  disabled: []\n",0o600).unwrap();
        let result = features("features enable", &c, &["platform:projects".into()]).unwrap();
        assert_eq!(result["restartRequired"], true);
        let config: Value = serde_yaml::from_slice(&fs::read(&path, 10000).unwrap()).unwrap();
        assert_eq!(config["custom"]["preserved"], true);
        assert_eq!(
            config["feature_overrides"]["disabled"],
            json!(["app:music"])
        );
        assert_eq!(
            config["feature_overrides"]["enabled"],
            json!(["platform:projects"])
        );
        assert!(config.get("disabled_apps").is_none());
        assert_eq!(
            std::fs::metadata(&path).unwrap().permissions().mode() & 0o777,
            0o600
        );
    }
    #[test]
    fn registration_preserves_shared_source_permissions_and_native_service_defaults() {
        use std::os::unix::fs::PermissionsExt;
        let root = tempfile::Builder::new()
            .permissions(std::fs::Permissions::from_mode(0o700))
            .tempdir()
            .unwrap();
        let repo = root.path().join("repo");
        std::fs::create_dir(&repo).unwrap();
        std::fs::set_permissions(&repo, std::fs::Permissions::from_mode(0o775)).unwrap();
        if rustix::process::geteuid().is_root() {
            assert!(fs::source_scope(&repo).is_err());
            return;
        }
        {
            let _source = fs::source_scope(&repo).unwrap();
            fs::write(
                &repo.join(marker("core", "source")),
                b"services: {}\n",
                0o644,
            )
            .unwrap();
            fs::write(
                &repo.join(".env"),
                b"DATABASE_PASSWORD=fixture\nVITE_API_URL=http://localhost:8000\n",
                0o600,
            )
            .unwrap();
        }
        let flags = Flags::from([
            ("path".into(), json!(repo)),
            ("services".into(), json!("api")),
            ("profile".into(), json!("minimal")),
        ]);
        let state = root.path().join("native");
        let call = super::super::fake::Call {
            program: "git",
            args: vec!["rev-parse".into(), "--show-toplevel".into()],
            output: Ok(format!("{}\n", repo.display()).into_bytes()),
        };
        super::super::fake::with(vec![call], || register(&flags, &state).unwrap());
        let saved = config(&state).unwrap().unwrap();
        assert_eq!(saved.source_strategy.as_deref(), Some("working_tree"));
        assert_eq!(saved.server_profile, "minimal");
        assert_eq!(saved.default_services, Some(vec!["api".into()]));
        assert_eq!(services(&saved, &Flags::new()).unwrap(), vec!["api"]);
        assert_eq!(
            std::fs::metadata(repo).unwrap().permissions().mode() & 0o777,
            0o775
        );
    }
}
