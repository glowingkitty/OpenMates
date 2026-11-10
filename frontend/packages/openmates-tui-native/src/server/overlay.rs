//! Official-cloud Compose selection. Overlay code is an explicit trusted input;
//! it never grants permission to mutate privileged host configuration.
use super::*;
const NO_WEBAPP: &str = "backend/core/docker-compose.no-webapp.yml";
const COMPOSE: &str = "docker-compose.openmatescloud.yml";
pub(super) fn default_mode() -> String {
    "self_host".into()
}
fn mode(value: &str) -> Result<&'static str> {
    match value {
        "self_host" | "self-host" => Ok("self_host"),
        "official_cloud" | "official-cloud" => Ok("official_cloud"),
        _ => Err(Error::Invalid(
            "Deployment mode must be self-host or official-cloud.",
        )),
    }
}
fn setting<'a>(content: &'a str, name: &str) -> Result<Option<&'a str>> {
    if content
        .lines()
        .filter(|line| {
            line.trim_start()
                .split_once('=')
                .is_some_and(|(key, _)| key.trim() == name)
        })
        .count()
        > 1
    {
        return Err(Error::Invalid(
            "Duplicate deployment environment settings are ambiguous.",
        ));
    }
    Ok(env_get(content, name))
}
pub(super) fn resolve(
    c: &mut Configuration,
    flags: &Flags,
    content: &str,
    installing: bool,
) -> Result<()> {
    let explicit = text(flags, "deployment-mode").map(mode).transpose()?;
    if boolean(flags, "official-cloud") && explicit == Some("self_host") {
        return Err(Error::Invalid("Conflicting deployment mode options."));
    }
    let requested = if boolean(flags, "official-cloud") {
        Some("official_cloud")
    } else {
        explicit
    };
    let enabled = match setting(content, "OPENMATES_CLOUD_OVERLAY_ENABLED")? {
        Some("true") => Some("official_cloud"),
        Some("false") => Some("self_host"),
        None | Some("") => None,
        _ => {
            return Err(Error::Invalid(
                "Cloud overlay enabled setting must be true or false.",
            ));
        }
    };
    let declared = setting(content, "OPENMATES_DEPLOYMENT_MODE")?
        .filter(|s| !s.is_empty())
        .map(mode)
        .transpose()?;
    if enabled.zip(declared).is_some_and(|(a, b)| a != b) {
        return Err(Error::Invalid(
            "Conflicting deployment mode environment settings.",
        ));
    }
    let effective = if installing {
        requested.unwrap_or("self_host")
    } else {
        let effective = enabled.or(declared).unwrap_or(mode(&c.deployment_mode)?);
        if requested.is_some_and(|v| v != effective) {
            return Err(Error::Invalid(
                "Registration does not change deployment mode; update the private installation environment first.",
            ));
        }
        effective
    };
    let first = text(flags, "openmatescloud-path");
    let second = text(flags, "openmates-cloud-path");
    if first.zip(second).is_some_and(|(a, b)| a != b) {
        return Err(Error::Invalid("Conflicting cloud overlay paths."));
    }
    if effective == "self_host" {
        if first.or(second).is_some() {
            return Err(Error::Invalid(
                "An overlay path requires official-cloud mode.",
            ));
        }
        c.deployment_mode = effective.into();
        c.overlay_path = None;
        return Ok(());
    }
    if c.server_role != "core" {
        return Err(Error::Invalid(
            "Official-cloud overlays require the core server role.",
        ));
    }
    let configured = setting(content, "OPENMATES_CLOUD_OVERLAY_PATH")?.filter(|s| !s.is_empty());
    if !installing
        && setting(content, "OPENMATES_CLOUD_OVERLAY_PACKAGE")?
            .is_some_and(|s| !s.is_empty() && s != "OpenMatesCloud")
    {
        return Err(Error::Invalid(
            "Official-cloud overlay package must be OpenMatesCloud.",
        ));
    }
    let selected = first.or(second).or(configured);
    let path = if let Some(value) = selected {
        normalized_path(value)?
    } else if let Some(path) = &c.overlay_path {
        path.clone()
    } else {
        c.install_path
            .parent()
            .ok_or(Error::Io)?
            .join("OpenMatesCloud")
    };
    // Compose expands env-file interpolation: prevent paths from introducing
    // extra assignments or interpolated values. No shell is involved.
    if path
        .to_str()
        .is_none_or(|s| s.contains(['\n', '\r', '\0', '"', '\'', '$', '`', '\\']))
    {
        return Err(Error::Invalid(
            "Cloud overlay path contains unsupported environment characters.",
        ));
    }
    if let Some(configured) = configured
        && !installing
        && normalized_path(configured)? != path
    {
        return Err(Error::Invalid(
            "Cloud overlay path conflicts with the installation environment.",
        ));
    }
    fs::directory(&path, false)?;
    if fs::snapshot(&path.join(COMPOSE), 16 * 1024 * 1024)?.mode & 0o022 != 0 {
        return Err(Error::Invalid(
            "Cloud overlay Compose file must not be writable by other users.",
        ));
    }
    fs::read(&c.install_path.join(NO_WEBAPP), 1024 * 1024)?;
    c.deployment_mode = effective.into();
    c.overlay_path = Some(path);
    Ok(())
}
pub(super) fn append(c: &Configuration, args: &mut Vec<String>) {
    if c.deployment_mode == "official_cloud"
        && let Some(path) = &c.overlay_path
    {
        args.extend([
            "-f".into(),
            path.join(COMPOSE).to_string_lossy().into_owned(),
            "-f".into(),
            NO_WEBAPP.into(),
        ]);
    }
}
pub(super) fn write_environment(c: &Configuration) -> Result<()> {
    let mut content = env(&c.install_path)?;
    // Normalize these assignments together, including whitespace forms, so
    // Compose and our reader cannot select different duplicate values.
    let filtered = Zeroizing::new(
        content
            .lines()
            .filter(|line| {
                !line.split_once('=').is_some_and(|(key, _)| {
                    matches!(
                        key.trim(),
                        "OPENMATES_DEPLOYMENT_MODE"
                            | "OPENMATES_CLOUD_OVERLAY_ENABLED"
                            | "OPENMATES_CLOUD_OVERLAY_PACKAGE"
                            | "OPENMATES_CLOUD_OVERLAY_PATH"
                    )
                })
            })
            .collect::<Vec<_>>()
            .join("\n"),
    );
    content.clear();
    content.push_str(&filtered);
    content.push('\n');
    env_set(
        &mut content,
        "OPENMATES_DEPLOYMENT_MODE",
        &c.deployment_mode,
    );
    let cloud = c.deployment_mode == "official_cloud";
    env_set(
        &mut content,
        "OPENMATES_CLOUD_OVERLAY_ENABLED",
        if cloud { "true" } else { "false" },
    );
    env_set(
        &mut content,
        "OPENMATES_CLOUD_OVERLAY_PACKAGE",
        if cloud { "OpenMatesCloud" } else { "" },
    );
    if let Some(path) = &c.overlay_path {
        env_set(
            &mut content,
            "OPENMATES_CLOUD_OVERLAY_PATH",
            &format!("\"{}\"", path.display()),
        );
    }
    fs::write(&c.install_path.join(".env"), content.as_bytes(), 0o600)
}
pub(super) fn supported_action(c: &Configuration, action: &str) -> Result<()> {
    // App package commands only change the package root and restart services,
    // both of which the cloud lifecycle already supports. They stay limited to
    // the development environment: packaged providers are not billed.
    let app_packages = (action == "apps" || action.starts_with("apps "))
        && c.install_path.join(".env").exists()
        && env_get(&env(&c.install_path)?, "SERVER_ENVIRONMENT") == Some("development");
    if c.deployment_mode == "official_cloud"
        && !app_packages
        && !matches!(
            action,
            "start"
                | "stop"
                | "restart"
                | "status"
                | "logs"
                | "env"
                | "env list"
                | "env get"
                | "env check"
                | "env doctor"
                | "features"
                | "features list"
                | "features explain"
        )
    {
        return Err(Error::Invalid(
            "Official-cloud lifecycle is supported; this management action still requires native cloud verification and host-origin parity. No operation was performed.",
        ));
    }
    Ok(())
}
pub(super) fn reject_cloud_caddy(flags: &Flags, state: &Path) -> Result<()> {
    let saved = config(state)?;
    let selected = text(flags, "path")
        .map(normalized_path)
        .transpose()?
        .or_else(|| saved.as_ref().map(|c| c.install_path.clone()));
    let cloud = saved.as_ref().is_some_and(|c| {
        c.deployment_mode == "official_cloud"
            && selected.as_ref().is_none_or(|p| *p == c.install_path)
    }) || if let Some(path) = selected.filter(|p| p.join(".env").exists()) {
        let content = env(&path)?;
        env_get(&content, "OPENMATES_CLOUD_OVERLAY_ENABLED") == Some("true")
            || env_get(&content, "OPENMATES_DEPLOYMENT_MODE")
                .is_some_and(|s| matches!(mode(s), Ok("official_cloud")))
    } else {
        false
    };
    if cloud {
        return Err(Error::Invalid(
            "Official-cloud Caddy origins require the remaining native host-origin port.",
        ));
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    fn fixture() -> (tempfile::TempDir, Configuration) {
        use std::os::unix::fs::PermissionsExt;
        let dir = tempfile::Builder::new()
            .permissions(std::fs::Permissions::from_mode(0o700))
            .tempdir()
            .unwrap();
        let mut c = super::super::tests::c();
        c.install_path = dir.path().join("OpenMates");
        fs::write(&c.install_path.join(NO_WEBAPP), b"services: {}", 0o600).unwrap();
        fs::write(
            &dir.path().join("OpenMatesCloud").join(COMPOSE),
            b"services: {}",
            0o600,
        )
        .unwrap();
        fs::write(
            &c.install_path.join(".env"),
            b"SECRET__FIXTURE=private\n",
            0o600,
        )
        .unwrap();
        (dir, c)
    }
    #[test]
    fn validates_modes_before_enabling_overlay() {
        let mut c = super::super::tests::c();
        assert!(
            resolve(
                &mut c,
                &Flags::new(),
                "OPENMATES_CLOUD_OVERLAY_ENABLED=maybe",
                false
            )
            .is_err()
        );
        assert!(
            resolve(
                &mut c,
                &Flags::new(),
                "OPENMATES_CLOUD_OVERLAY_ENABLED=false\nOPENMATES_DEPLOYMENT_MODE=official_cloud",
                false
            )
            .is_err()
        );
        let flags = Flags::from([
            ("official-cloud".into(), json!(true)),
            ("deployment-mode".into(), json!("self-host")),
        ]);
        assert!(resolve(&mut c, &flags, "", true).is_err());
        assert!(
            resolve(
                &mut c,
                &Flags::from([("deployment-mode".into(), json!("other"))]),
                "",
                true
            )
            .is_err()
        );
        assert_eq!(c.deployment_mode, "self_host");
        assert!(
            resolve(
                &mut c,
                &Flags::new(),
                "OPENMATES_CLOUD_OVERLAY_ENABLED=false\nOPENMATES_CLOUD_OVERLAY_ENABLED=true",
                false
            )
            .is_err()
        );
        assert_eq!(compose(&c).len(), 5);
    }
    #[test]
    fn cloud_compose_order_and_local_webapp_scope() {
        let (_dir, mut c) = fixture();
        c.compose_profile = "full".into();
        resolve(
            &mut c,
            &Flags::from([("official-cloud".into(), json!(true))]),
            "",
            true,
        )
        .unwrap();
        let args = compose(&c);
        assert_eq!(
            args[5..7],
            ["-f", "backend/core/docker-compose.override.yml"]
        );
        assert!(args[8].ends_with("OpenMatesCloud/docker-compose.openmatescloud.yml"));
        assert_eq!(args[9..11], ["-f", NO_WEBAPP]);
        assert!(
            !services(&c, &Flags::new())
                .unwrap()
                .contains(&"webapp".into())
        );
        assert!(services(&c, &Flags::from([("services".into(), json!("webapp"))])).is_err());
        assert!(supported_action(&c, "status").is_ok());
        assert!(supported_action(&c, "apps install").is_err());
        let env_path = c.install_path.join(".env");
        fs::write(&env_path, b"SERVER_ENVIRONMENT=production\n", 0o600).unwrap();
        assert!(supported_action(&c, "apps install").is_err());
        fs::write(&env_path, b"SERVER_ENVIRONMENT=development\n", 0o600).unwrap();
        assert!(supported_action(&c, "apps install").is_ok());
        assert!(supported_action(&c, "apps").is_ok());
        assert!(supported_action(&c, "appsx").is_err());
        for action in [
            "update",
            "verify",
            "monitoring run",
            "caddy update",
            "restore",
            "test",
        ] {
            assert!(supported_action(&c, action).is_err());
        }
    }
    #[test]
    fn registration_observes_env_without_changing_it() {
        let (dir, mut c) = fixture();
        let overlay = dir.path().join("OpenMatesCloud");
        let content = format!(
            "OPENMATES_CLOUD_OVERLAY_ENABLED=true\nOPENMATES_DEPLOYMENT_MODE=official_cloud\nOPENMATES_CLOUD_OVERLAY_PATH=\"{}\"\n",
            overlay.display()
        );
        fs::write(&c.install_path.join(".env"), content.as_bytes(), 0o600).unwrap();
        resolve(&mut c, &Flags::new(), &content, false).unwrap();
        assert_eq!(c.overlay_path.as_deref(), Some(overlay.as_path()));
        assert_eq!(&*env(&c.install_path).unwrap(), &content);
        let conflict = Flags::from([("deployment-mode".into(), json!("self-host"))]);
        assert!(resolve(&mut c, &conflict, &content, false).is_err());
        c.server_role = "upload".into();
        assert!(resolve(&mut c, &Flags::new(), &content, false).is_err());
    }
    #[test]
    fn rejects_untrusted_or_missing_overlay_and_invalid_path() {
        use std::os::unix::fs::{PermissionsExt, symlink};
        let (dir, mut c) = fixture();
        let cloud = dir.path().join("OpenMatesCloud");
        let file = cloud.join(COMPOSE);
        std::fs::remove_file(&file).unwrap();
        let flags = Flags::from([("official-cloud".into(), json!(true))]);
        assert!(resolve(&mut c, &flags, "", true).is_err());
        let outside = dir.path().join("outside.yml");
        fs::write(&outside, b"services: {}", 0o600).unwrap();
        symlink(&outside, &file).unwrap();
        assert!(resolve(&mut c, &flags, "", true).is_err());
        std::fs::remove_file(&file).unwrap();
        fs::write(&file, b"services: {}", 0o600).unwrap();
        std::fs::set_permissions(&file, std::fs::Permissions::from_mode(0o666)).unwrap();
        assert!(resolve(&mut c, &flags, "", true).is_err());
        let mut flags = flags;
        flags.insert("openmatescloud-path".into(), json!("/tmp/$UNTRUSTED"));
        assert!(resolve(&mut c, &flags, "", true).is_err());
    }
    #[test]
    fn environment_write_is_private_and_clears_stale_overlay() {
        use std::os::unix::fs::PermissionsExt;
        let (_dir, mut c) = fixture();
        resolve(
            &mut c,
            &Flags::from([("official-cloud".into(), json!(true))]),
            "",
            true,
        )
        .unwrap();
        fs::write(&c.install_path.join(".env"), b"SECRET__FIXTURE=private\n OPENMATES_CLOUD_OVERLAY_ENABLED =false\nOPENMATES_CLOUD_OVERLAY_PATH = /stale\n", 0o600).unwrap();
        write_environment(&c).unwrap();
        let content = env(&c.install_path).unwrap();
        assert_eq!(
            setting(&content, "OPENMATES_CLOUD_OVERLAY_ENABLED").unwrap(),
            Some("true")
        );
        assert_eq!(env_get(&content, "SECRET__FIXTURE"), Some("private"));
        assert_eq!(
            env_get(&content, "OPENMATES_CLOUD_OVERLAY_PACKAGE"),
            Some("OpenMatesCloud")
        );
        assert_eq!(
            std::fs::metadata(c.install_path.join(".env"))
                .unwrap()
                .permissions()
                .mode()
                & 0o777,
            0o600
        );
        resolve(&mut c, &Flags::new(), &content, true).unwrap();
        write_environment(&c).unwrap();
        let content = env(&c.install_path).unwrap();
        assert_eq!(
            env_get(&content, "OPENMATES_CLOUD_OVERLAY_ENABLED"),
            Some("false")
        );
        assert!(env_get(&content, "OPENMATES_CLOUD_OVERLAY_PATH").is_none());
        assert_eq!(compose(&c).len(), 5);
    }
    #[test]
    fn registered_cloud_lifecycle_uses_overlay_and_blocks_host_mutations() {
        let (dir, mut c) = fixture();
        let state = dir.path().join("native-state");
        fs::write(
            &c.install_path.join(marker("core", "image")),
            b"services: {}",
            0o600,
        )
        .unwrap();
        resolve(
            &mut c,
            &Flags::from([("official-cloud".into(), json!(true))]),
            "",
            true,
        )
        .unwrap();
        write_environment(&c).unwrap();
        save_config(&state, &c).unwrap();
        let loaded = installation(&Flags::new(), &state).unwrap();
        let mut args = compose(&loaded);
        args.extend(["ps".into(), "--format".into(), "json".into()]);
        super::super::fake::with(
            vec![super::super::fake::Call {
                program: "docker",
                args,
                output: Ok(b"[]".to_vec()),
            }],
            || {
                let result = lifecycle("status", &loaded, &Flags::new()).unwrap();
                assert_eq!(result["deploymentMode"], "official_cloud");
            },
        );
        assert!(reject_cloud_caddy(&Flags::new(), &state).is_err());
        // Also detect a cloud installation before it has a native registration.
        assert!(
            reject_cloud_caddy(
                &Flags::from([("path".into(), json!(c.install_path))]),
                &dir.path().join("unregistered-state")
            )
            .is_err()
        );
        assert!(
            lifecycle(
                "restart",
                &loaded,
                &Flags::from([("rebuild".into(), json!(true))])
            )
            .is_err()
        );
        // Legacy state documents load with an explicit self-host default.
        let mut value = serde_json::to_value(&c).unwrap();
        value.as_object_mut().unwrap().remove("deploymentMode");
        value
            .as_object_mut()
            .unwrap()
            .remove("openMatesCloudOverlayPath");
        let old: Configuration = serde_json::from_value(value).unwrap();
        assert_eq!(old.deployment_mode, "self_host");
    }
}
