//! Host Caddy operations preserve local edits and validate before publishing.
use super::*;
use sha2::{Digest, Sha256};
use std::time::Duration;
fn hash(bytes: &[u8]) -> String {
    format!("{:x}", Sha256::digest(bytes))
}
fn template(role: &str) -> &'static str {
    match role {
        "core" => include_str!("../../assets/selfhost/caddy/core/Caddyfile"),
        "upload" => include_str!("../../assets/selfhost/caddy/upload/Caddyfile"),
        _ => include_str!("../../assets/selfhost/caddy/preview/Caddyfile"),
    }
}
struct Temporary(PathBuf);
impl Temporary {
    fn new() -> Result<Self> {
        let root = std::env::temp_dir().join(format!("openmates-caddy-{}", uuid::Uuid::new_v4()));
        fs::directory(&root, true)?;
        Ok(Self(root))
    }
}
impl Drop for Temporary {
    fn drop(&mut self) {
        let _ = std::fs::remove_dir_all(&self.0);
    }
}
fn validate(content: &str) -> Result<()> {
    let temp = Temporary::new()?;
    let file = temp.0.join("Caddyfile");
    fs::write(&file, content.as_bytes(), 0o600)?;
    run(
        "caddy",
        &[
            "validate".into(),
            "--adapter".into(),
            "caddyfile".into(),
            "--config".into(),
            file.to_string_lossy().into_owned(),
        ],
        &temp.0,
        None,
    )?;
    Ok(())
}
struct Applied {
    _critical: operation::Critical,
    _lock: fs::HostLock,
    before: Option<fs::Snapshot>,
    published: fs::Snapshot,
    backup: Option<PathBuf>,
}
impl Applied {
    fn rollback(&self, path: &Path) -> Result<()> {
        let current = fs::host_snapshot(path, 4 * 1024 * 1024)?;
        if !current.matches(&self.published) {
            return Err(Error::Invalid(
                "Caddy changed after publication; rollback was refused and the operator's newer file was preserved.",
            ));
        }
        if let Some(before) = &self.before {
            fs::write_identity(path, &before.bytes, Some(before))?;
        } else {
            std::fs::remove_file(path)?;
        }
        run(
            "systemctl",
            &["reload".into(), "caddy".into()],
            path.parent().ok_or(Error::Io)?,
            None,
        ).map_err(|_| Error::Invalid("Previous Caddy configuration was restored, but its reload failed; operator recovery is required."))?;
        Ok(())
    }
}
fn snapshot(path: &Path) -> Result<Option<fs::Snapshot>> {
    if path.try_exists()? {
        Ok(Some(fs::host_snapshot(path, 4 * 1024 * 1024)?))
    } else {
        Ok(None)
    }
}
fn apply(path: &Path, expected: Option<&fs::Snapshot>, content: &str) -> Result<Applied> {
    let lock = fs::HostLock::acquire(path)?;
    validate(content)?;
    let current = snapshot(path)?;
    let unchanged = match (expected, current.as_ref()) {
        (None, None) => true,
        (Some(expected), Some(current)) => expected.matches(current),
        _ => false,
    };
    if !unchanged {
        return Err(Error::Invalid(
            "Caddy configuration or ownership changed during this operation; existing content was preserved.",
        ));
    }
    let backup = if let Some(before) = &current {
        let backup = path.with_file_name(format!(
            "{}.openmates-backup-{}",
            path.file_name().ok_or(Error::Io)?.to_string_lossy(),
            uuid::Uuid::new_v4()
        ));
        fs::write(&backup, &before.bytes, 0o600)?;
        Some(backup)
    } else {
        None
    };
    let critical = operation::critical()?;
    fs::write_identity(path, content.as_bytes(), current.as_ref())?;
    let receipt = Applied {
        _critical: critical,
        _lock: lock,
        before: current,
        published: fs::host_snapshot(path, 4 * 1024 * 1024)?,
        backup,
    };
    if run(
        "systemctl",
        &["reload".into(), "caddy".into()],
        path.parent().ok_or(Error::Io)?,
        None,
    )
    .is_err()
    {
        receipt.rollback(path)?;
        return Err(Error::Invalid(
            "Caddy reload failed; previous configuration was restored.",
        ));
    }
    Ok(receipt)
}
pub(super) fn basic(action: &str, selected_role: &str, flags: &Flags) -> Result<Value> {
    let _strict = fs::strict_scope();
    role(selected_role)?;
    let path = normalized_path(text(flags, "config").unwrap_or("/etc/caddy/Caddyfile"))?;
    let target = template(selected_role);
    let applied = snapshot(&path)?;
    let wanted = hash(target.as_bytes());
    let current = applied.as_ref().map(|snapshot| hash(&snapshot.bytes));
    let steps = match action {
        "check" => vec!["render-template", "validate"],
        "status" => vec!["hash-template", "hash-applied", "validate"],
        "diff" => vec!["hash-template", "hash-applied", "diff"],
        "apply" => vec![
            "render-template",
            "validate",
            "backup-applied",
            "write",
            "reload",
        ],
        _ => return Err(Error::Invalid("Unknown Caddy action.")),
    };
    let mut payload = json!({"command":format!("caddy {action}"),"role":selected_role,"action":action,"templatePath":format!("bundled:caddy/{selected_role}/Caddyfile"),"appliedPath":path,"templateHash":wanted,"appliedHash":current,"drift":current.as_deref()!=Some(&wanted),"steps":steps});
    // The baseline --json reports a plan for basic commands. Explicit --dry-run
    // provides the same policy in both output formats.
    if boolean(flags, "json") || boolean(flags, "dry-run") {
        payload["status"] = json!("planned");
        return Ok(payload);
    }
    match action {
        "check" => {
            validate(target)?;
            payload["status"] = json!("valid");
        }
        "status" => {
            payload["status"] = json!(if applied.is_some() {
                "installed"
            } else {
                "not_installed"
            });
        }
        "diff" => {
            let applied = applied.ok_or(Error::Invalid("Applied Caddyfile does not exist."))?;
            let text = std::str::from_utf8(&applied.bytes).map_err(|_| Error::Protocol)?;
            payload["diff"] = json!(diff_lines(text, target));
        }
        "apply" => {
            if !boolean(flags, "yes") {
                return Err(Error::Invalid(
                    "Replacing the host Caddyfile requires --yes.",
                ));
            }
            let receipt = apply(&path, applied.as_ref(), target)?;
            payload["backupPath"] = json!(receipt.backup);
            payload["status"] = json!("updated");
        }
        _ => unreachable!(),
    }
    Ok(payload)
}
fn diff_lines(old: &str, new: &str) -> String {
    if old == new {
        return String::new();
    }
    // Bounded explicit full replacement view; apply never relies on parsing it.
    let mut output = String::from("--- applied\n+++ target\n");
    for line in old.lines() {
        output.push('-');
        output.push_str(line);
        output.push('\n');
    }
    for line in new.lines() {
        output.push('+');
        output.push_str(line);
        output.push('\n');
    }
    output
}
#[derive(Clone)]
struct Matcher {
    line: usize,
    prefix: String,
    suffix: String,
    paths: Vec<String>,
}
fn matchers(content: &str) -> Result<BTreeMap<String, Matcher>> {
    let named = regex::Regex::new(r"^\s*(@[\w-]+)\s+(.*)$").map_err(|_| Error::Protocol)?;
    let path =
        regex::Regex::new(r"^(.*?\bpath\s+)([^#]*?)(\s*(?:#.*)?)$").map_err(|_| Error::Protocol)?;
    let lines = content.lines().collect::<Vec<_>>();
    let mut result = BTreeMap::new();
    for (index, line) in lines.iter().enumerate() {
        let Some(name) = named.captures(line) else {
            continue;
        };
        let mut selected = Some(index);
        if name[2].trim() == "{" {
            selected = None;
            for (j, line) in lines.iter().enumerate().skip(index + 1) {
                if line.trim() == "}" {
                    break;
                }
                if line.trim_start().starts_with("path ") && selected.replace(j).is_some() {
                    return Err(Error::Invalid("Caddy path matcher is ambiguous."));
                }
            }
        }
        let Some(index) = selected else { continue };
        let Some(parts) = path.captures(lines[index]) else {
            continue;
        };
        let paths = parts[2]
            .split_whitespace()
            .map(str::to_owned)
            .collect::<Vec<_>>();
        if paths.is_empty()
            || paths
                .iter()
                .any(|p| !p.starts_with('/') || p.contains(['{', '}', '\'', '"', '\\']))
        {
            return Err(Error::Invalid("Caddy path matcher is unsupported."));
        }
        if result
            .insert(
                name[1].into(),
                Matcher {
                    line: index,
                    prefix: parts[1].into(),
                    suffix: parts[3].into(),
                    paths,
                },
            )
            .is_some()
        {
            return Err(Error::Invalid(
                "Caddy path matcher is ambiguous across sites. Select a managed site migration.",
            ));
        }
    }
    Ok(result)
}
fn adopt(current: &str, target: &str) -> Result<(String, BTreeMap<String, Vec<String>>)> {
    let existing = matchers(current)?;
    let wanted = matchers(target)?;
    if wanted.is_empty() {
        return Err(Error::Invalid("Release Caddyfile has no managed matchers."));
    }
    let mut lines = current.split('\n').map(str::to_owned).collect::<Vec<_>>();
    let mut owned = BTreeMap::new();
    for (name, target) in wanted {
        let live = existing.get(&name).ok_or(Error::Invalid(
            "New Caddy matcher requires a reviewed host migration.",
        ))?;
        let mut merged = target.paths.clone();
        for route in &live.paths {
            if !merged.contains(route) {
                merged.push(route.clone());
            }
        }
        owned.insert(name, target.paths);
        if merged.len() == live.paths.len() && merged.iter().all(|p| live.paths.contains(p)) {
            continue;
        }
        lines[live.line] = format!("{}{}{}", live.prefix, merged.join(" "), live.suffix);
    }
    Ok((lines.join("\n"), owned))
}
fn merge(current: &str, previous: &str, target: &str) -> Result<String> {
    if previous == target {
        return Ok(current.into());
    }
    if current == previous {
        return Ok(target.into());
    }
    let temp = Temporary::new()?;
    let mut args = vec!["-m".into()];
    for (name, data) in [
        ("current", current),
        ("previous", previous),
        ("target", target),
    ] {
        let path = temp.0.join(name);
        fs::write(&path, data.as_bytes(), 0o600)?;
        args.push(path.to_string_lossy().into_owned());
    }
    let output = run("diff3", &args, &temp.0, None).map_err(|_| {
        Error::Invalid("Caddy release changes overlap local edits; configuration was preserved.")
    })?;
    String::from_utf8(output.to_vec()).map_err(|_| Error::Protocol)
}
fn active_path(c: &Configuration, flags: &Flags) -> Result<PathBuf> {
    if let Some(explicit) = text(flags, "caddy-config") {
        let path = normalized_path(explicit)?;
        if !path.try_exists()? {
            return Err(Error::Invalid("Explicit host Caddyfile does not exist."));
        }
        return Ok(path);
    }
    if let Ok(pid) = run(
        "systemctl",
        &[
            "show".into(),
            "caddy".into(),
            "--property=MainPID".into(),
            "--value".into(),
        ],
        &c.install_path,
        None,
    ) {
        let pid = std::str::from_utf8(&pid)
            .map_err(|_| Error::Protocol)?
            .trim();
        if pid.parse::<u32>().is_ok_and(|p| p > 0) {
            // /proc is kernel-owned and cmdline contains no application secrets
            // from this program. Only --config is retained.
            let command = std::fs::read(format!("/proc/{pid}/cmdline")).map_err(|_| {
                Error::Invalid("Running Caddy config cannot be detected; supply --caddy-config.")
            })?;
            let args = command
                .split(|b| *b == 0)
                .filter_map(|b| std::str::from_utf8(b).ok())
                .collect::<Vec<_>>();
            for (index, arg) in args.iter().enumerate() {
                let value = if *arg == "--config" {
                    args.get(index + 1).copied()
                } else {
                    arg.strip_prefix("--config=")
                };
                if let Some(value) = value {
                    if !Path::new(value).is_absolute() {
                        return Err(Error::Invalid(
                            "Running Caddy config is relative; supply --caddy-config.",
                        ));
                    }
                    return normalized_path(value);
                }
            }
            return Err(Error::Invalid(
                "Running Caddy config cannot be detected; supply --caddy-config.",
            ));
        }
    }
    Ok("/etc/caddy/Caddyfile".into())
}
fn fetch_text(url: &str) -> Result<String> {
    tokio::runtime::Handle::current().block_on(async {
        let mut response = reqwest::Client::builder()
            .redirect(reqwest::redirect::Policy::none())
            .timeout(Duration::from_secs(15))
            .build()?
            .get(url)
            .send()
            .await?;
        if !response.status().is_success() {
            return Err(Error::Offline);
        }
        let mut bytes = Zeroizing::new(Vec::new());
        while let Some(chunk) = response.chunk().await? {
            if bytes.len() + chunk.len() > 4 * 1024 * 1024 {
                return Err(Error::Protocol);
            }
            bytes.extend_from_slice(&chunk);
        }
        String::from_utf8(bytes.to_vec()).map_err(|_| Error::Protocol)
    })
}
fn verify_routes(c: &Configuration, endpoint: &str) -> Result<()> {
    let endpoint = url::Url::parse(endpoint)
        .map_err(|_| Error::Invalid("Caddy public endpoint is invalid."))?;
    if !matches!(endpoint.scheme(), "https" | "http")
        || endpoint.password().is_some()
        || !endpoint.username().is_empty()
    {
        return Err(Error::Invalid("Caddy public endpoint is invalid."));
    }
    tokio::runtime::Handle::current().block_on(async {
        let client = reqwest::Client::builder()
            .redirect(reqwest::redirect::Policy::none())
            .timeout(Duration::from_secs(5))
            .build()?;
        if !client
            .get(endpoint.join("/health").map_err(|_| Error::Protocol)?)
            .send()
            .await?
            .status()
            .is_success()
        {
            return Err(Error::Invalid("Caddy public health verification failed."));
        }
        if c.server_role == "core" {
            let origin = c.app_url.as_deref().unwrap_or("http://localhost:5173");
            let origin = url::Url::parse(origin)
                .map_err(|_| Error::Protocol)?
                .origin()
                .ascii_serialization();
            for (path, method) in [
                (
                    "/v1/embeds/chats/00000000-0000-4000-8000-000000000000/references/availability",
                    "POST",
                ),
                ("/v1/account/chat-encryption-key", "GET"),
            ] {
                let response = client
                    .request(
                        reqwest::Method::OPTIONS,
                        endpoint.join(path).map_err(|_| Error::Protocol)?,
                    )
                    .header("origin", &origin)
                    .header("access-control-request-method", method)
                    .header("access-control-request-headers", "content-type")
                    .send()
                    .await?;
                if !response.status().is_success()
                    || response
                        .headers()
                        .get("access-control-allow-origin")
                        .and_then(|v| v.to_str().ok())
                        != Some(&origin)
                    || response
                        .headers()
                        .get("access-control-allow-credentials")
                        .and_then(|v| v.to_str().ok())
                        != Some("true")
                {
                    return Err(Error::Invalid(
                        "Caddy first-party route CORS verification failed.",
                    ));
                }
            }
        }
        Ok(())
    })
}
pub(super) fn release(c: &Configuration, flags: &Flags) -> Result<Value> {
    let _strict = fs::strict_scope();
    let path = active_path(c, flags)?;
    if !path.try_exists()? {
        return Ok(json!({"command":"caddy update","status":"not_installed","configPath":path}));
    }
    if boolean(flags, "dry-run") {
        return Ok(
            json!({"command":"caddy update","status":"planned","role":c.server_role,"configPath":path,"mode":c.install_mode}),
        );
    }
    if text(flags, "caddy-profile").is_some() {
        return Err(Error::Invalid(
            "Official-upload Caddy migration requires scoped origin validation; native port remains open.",
        ));
    }
    let before = fs::host_snapshot(&path, 4 * 1024 * 1024)?;
    let live =
        Zeroizing::new(String::from_utf8(before.bytes.to_vec()).map_err(|_| Error::Protocol)?);
    if live.contains("@prod_origin") || live.contains("@dev_origin") {
        return Err(Error::Invalid(
            "Official-upload Caddyfile requires an explicit scoped migration; existing configuration was preserved.",
        ));
    }
    let content = env(&c.install_path)?;
    let tag = env_get(&content, "OPENMATES_IMAGE_TAG")
        .or(c.image_tag.as_deref())
        .unwrap_or("source");
    let revision = update::provenance(c, tag)?;
    let relative = format!(
        "frontend/packages/openmates-cli/templates/caddy/{}/Caddyfile",
        c.server_role
    );
    let target = if c.install_mode == "source" {
        String::from_utf8(fs::read(&c.install_path.join(&relative), 4 * 1024 * 1024)?)
            .map_err(|_| Error::Protocol)?
    } else {
        fetch_text(&format!(
            "https://raw.githubusercontent.com/glowingkitty/OpenMates/{revision}/{relative}"
        ))?
    };
    let state_path = c
        .install_path
        .join(format!(".openmates/caddy/{}.json", c.server_role));
    let (merged, paths) = if state_path.try_exists()? {
        let previous: Value = serde_json::from_slice(&fs::read(&state_path, 8 * 1024 * 1024)?)?;
        if previous["version"] != 1
            || previous["configPath"].as_str() != path.to_str()
            || previous["site"] != Value::Null
            || previous["profile"] != "self-host"
        {
            return Err(Error::Invalid(
                "Caddy release state is invalid or belongs to a different host configuration.",
            ));
        }
        let prior = previous["template"].as_str().ok_or(Error::Protocol)?;
        let merged = merge(&live, prior, &target)?;
        let paths = matchers(&target)?
            .into_iter()
            .map(|(key, value)| (key, value.paths))
            .collect();
        (merged, paths)
    } else {
        adopt(&live, &target)?
    };
    let domain_key = format!("DEPLOY_{}_DOMAIN", c.server_role.to_uppercase());
    let domain = env_get(&content, &domain_key)
        .map(str::to_owned)
        .or_else(|| {
            live.lines().find_map(|line| {
                let line = line.trim();
                line.strip_suffix(" {")
                    .filter(|s| !s.is_empty() && !s.contains(['{', ' ', '\t', '$', '*']))
                    .map(str::to_owned)
            })
        })
        .ok_or(Error::Invalid(
            "Public Caddy hostname is unavailable; set the role's DEPLOY domain.",
        ))?;
    let endpoint = if domain.contains("://") {
        domain
    } else {
        format!("https://{domain}")
    };
    let receipt = apply(&path, Some(&before), &merged)?;
    if let Err(error) = verify_routes(c, &endpoint) {
        receipt.rollback(&path)?;
        return Err(error);
    }
    let state = json!({"version":1,"configPath":path,"site":null,"revision":revision,"paths":paths,"template":target,"profile":"self-host"});
    fs::write(&state_path, &serde_json::to_vec(&state)?, 0o600)?;
    Ok(
        json!({"command":"caddy update","status":if live.as_str()==merged{"unchanged"}else{"updated"},"revision":revision,"backupPath":receipt.backup}),
    )
}

#[cfg(test)]
mod tests {
    use super::*;
    fn fixture() -> tempfile::TempDir {
        use std::os::unix::fs::PermissionsExt;
        tempfile::Builder::new()
            .permissions(std::fs::Permissions::from_mode(0o700))
            .tempdir()
            .unwrap()
    }
    fn validation() -> fake::Call {
        fake::Call {
            program: "caddy",
            args: vec![
                "validate",
                "--adapter",
                "caddyfile",
                "--config",
                "@CADDY_TEMP@",
            ]
            .into_iter()
            .map(str::to_owned)
            .collect(),
            output: Ok(vec![]),
        }
    }
    fn reload(output: Result<Vec<u8>>) -> fake::Call {
        fake::Call {
            program: "systemctl",
            args: vec!["reload".into(), "caddy".into()],
            output,
        }
    }
    #[test]
    fn transaction_preserves_private_mode_and_lock_covers_rollback() {
        let dir = fixture();
        let path = dir.path().join("Caddyfile");
        fs::write(&path, b"before", 0o600).unwrap();
        let before = fs::host_snapshot(&path, 64).unwrap();
        fake::with(
            vec![validation(), reload(Ok(vec![])), reload(Ok(vec![]))],
            || {
                let receipt = apply(&path, Some(&before), "after").unwrap();
                assert_eq!(receipt.published.mode, 0o600);
                assert_eq!(receipt.published.uid, before.uid);
                assert_eq!(receipt.published.gid, before.gid);
                assert!(matches!(fs::HostLock::acquire(&path), Err(Error::Locked)));
                receipt.rollback(&path).unwrap();
                let restored = fs::host_snapshot(&path, 64).unwrap();
                assert_eq!(&*restored.bytes, b"before");
                assert_eq!(restored.mode, 0o600);
            },
        );
        assert!(fs::HostLock::acquire(&path).is_ok());
    }
    #[test]
    fn reload_failure_restores_private_mode_and_newer_operator_file_blocks_rollback() {
        let dir = fixture();
        let path = dir.path().join("Caddyfile");
        fs::write(&path, b"before", 0o600).unwrap();
        let before = fs::host_snapshot(&path, 64).unwrap();
        fake::with(
            vec![validation(), reload(Err(Error::Io)), reload(Ok(vec![]))],
            || assert!(apply(&path, Some(&before), "after").is_err()),
        );
        let restored = fs::host_snapshot(&path, 64).unwrap();
        assert_eq!(&*restored.bytes, b"before");
        assert_eq!(restored.mode, 0o600);
        fake::with(vec![validation(), reload(Ok(vec![]))], || {
            let receipt = apply(&path, Some(&restored), "after").unwrap();
            fs::write(&path, b"operator newer", 0o600).unwrap();
            assert!(receipt.rollback(&path).is_err());
            assert_eq!(
                &*fs::host_snapshot(&path, 64).unwrap().bytes,
                b"operator newer"
            );
        });
    }
    #[test]
    fn replaced_inode_with_identical_bytes_is_detected_before_publish() {
        let dir = fixture();
        let path = dir.path().join("Caddyfile");
        fs::write(&path, b"same", 0o600).unwrap();
        let before = fs::host_snapshot(&path, 64).unwrap();
        fs::write(&path, b"same", 0o600).unwrap();
        fake::with(vec![validation()], || {
            assert!(apply(&path, Some(&before), "after").is_err())
        });
        assert_eq!(&*fs::host_snapshot(&path, 64).unwrap().bytes, b"same");
    }
    #[test]
    fn first_adoption_preserves_custom_paths_and_unrelated_host_bytes() {
        let current = "example.com {\n  @health path /health /custom # keep\n  reverse_proxy localhost:9999\n}\n";
        let target = "localhost {\n @health path /health /v1/status\n}\n";
        let (merged, paths) = adopt(current, target).unwrap();
        assert_eq!(
            merged,
            "example.com {\n  @health path /health /v1/status /custom # keep\n  reverse_proxy localhost:9999\n}\n"
        );
        assert_eq!(paths["@health"], vec!["/health", "/v1/status"]);
        assert!(adopt(current, "localhost {\n @missing path /new\n}\n").is_err());
    }
    #[test]
    fn ambiguous_matchers_and_unsupported_paths_fail_closed() {
        assert!(matchers("one {\n @health path /one\n}\ntwo {\n @health path /two\n}\n").is_err());
        assert!(matchers("@health path \"/quoted\"").is_err());
        assert_eq!(merge("operator", "release", "release").unwrap(), "operator");
        assert_eq!(merge("old", "old", "new").unwrap(), "new");
    }
}
