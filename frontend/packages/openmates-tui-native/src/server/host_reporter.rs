//! Host reporter lifecycle (`server host-reporter install|status|uninstall`).
//!
//! Contract: `specifications/architecture/security-monitoring`
//! (`host-reports.private-push`). The installed payload (reporter script, units,
//! apt hook) is `deployment/host_reporter/`, synchronized into
//! `assets/host_reporter/` by `scripts/sync_rust_cli_assets.py` and embedded
//! here; this module mirrors `deployment/host_reporter/install.sh` step by step
//! (same paths, modes, config keys, drop-in and key handling). No network
//! details are compiled in: the collector address comes from the operator.
use super::*;
use std::net::{IpAddr, Ipv4Addr, Ipv6Addr};
use std::os::unix::fs::{DirBuilderExt, PermissionsExt};
use std::time::Duration;

const SCRIPT: &str = include_str!("../../assets/host_reporter/openmates-host-reporter");
const README: &str = include_str!("../../assets/host_reporter/README.md");
const FACTS_UNIT: &str =
    include_str!("../../assets/host_reporter/systemd/openmates-host-facts-privileged.service");
const REPORTER_UNIT: &str =
    include_str!("../../assets/host_reporter/systemd/openmates-host-reporter.service");
const TIMER_UNIT: &str =
    include_str!("../../assets/host_reporter/systemd/openmates-host-reporter.timer");
const APT_HOOK: &str = include_str!("../../assets/host_reporter/systemd/99openmates-host-report");

const LIB_DIR: &str = "/usr/local/lib/openmates/host-reporter";
const ETC_DIR: &str = "/etc/openmates";
const CONF_DIR: &str = "/etc/openmates/host-reporter";
const CONF_FILE: &str = "/etc/openmates/host-reporter.conf";
const UNIT_DIR: &str = "/etc/systemd/system";
const DROPIN_DIR: &str = "/etc/systemd/system/openmates-host-reporter.service.d";
const DROPIN_FILE: &str = "collector-address.conf";
const APT_HOOK_FILE: &str = "/etc/apt/apt.conf.d/99openmates-host-report";
const KEY_FILE: &str = "/etc/openmates/host-reporter/host_ed25519";
/// Read by the reporter's `deployed_image_digests` field (`DEPLOYED_IMAGES_FILE`).
const IMAGES_DIR: &str = "/var/lib/openmates";
const IMAGES_FILE: &str = "/var/lib/openmates/deployed-images.json";
const COLLECTOR_PATH: &str = "/v1/host-report";
const TIMER: &str = "openmates-host-reporter.timer";
const SERVICE: &str = "openmates-host-reporter.service";
const UNITS: [(&str, &str); 3] = [
    ("openmates-host-facts-privileged.service", FACTS_UNIT),
    (SERVICE, REPORTER_UNIT),
    (TIMER, TIMER_UNIT),
];
const REQUIRED_TOOLS: [&str; 8] = [
    "python3",
    "ssh-keygen",
    "openssl",
    "curl",
    "dpkg-query",
    "apt-get",
    "ss",
    "systemctl",
];
const CERT_LIMIT: u64 = 64 * 1024;
const SYSTEMCTL_TIMEOUT: Duration = Duration::from_secs(30);

/// Filesystem root for every managed path; `/` in production, a temporary
/// directory in tests.
pub(super) struct Layout {
    root: PathBuf,
}
impl Layout {
    pub(super) fn system() -> Self {
        Self { root: "/".into() }
    }
    fn path(&self, absolute: &str) -> PathBuf {
        self.root.join(absolute.trim_start_matches('/'))
    }
    fn installed(&self) -> Result<bool> {
        Ok(self.path(CONF_FILE).try_exists()?)
    }
}

/// Validate a collector URL with the reporter's rules (`validate_collector_url`):
/// `https://<RFC 1918 or ULA address>[:port]/v1/host-report`, no names,
/// credentials, query or fragment. Returns the address for `IPAddressAllow=`.
pub(super) fn collector_address(url: &str) -> Result<IpAddr> {
    const SHAPE: &str =
        "Collector URL must be https://<collector-private-ip>:<port>/v1/host-report.";
    let rest = url.strip_prefix("https://").ok_or(Error::Invalid(SHAPE))?;
    let (authority, path) = rest.split_at(rest.find('/').ok_or(Error::Invalid(SHAPE))?);
    if path != COLLECTOR_PATH || authority.is_empty() || authority.contains('@') {
        return Err(Error::Invalid(SHAPE));
    }
    let (host, port) = if let Some(bracketed) = authority.strip_prefix('[') {
        let (host, tail) = bracketed.split_once(']').ok_or(Error::Invalid(SHAPE))?;
        let port = match tail {
            "" => None,
            _ => Some(tail.strip_prefix(':').ok_or(Error::Invalid(SHAPE))?),
        };
        let address = host
            .parse::<Ipv6Addr>()
            .map_err(|_| Error::Invalid("Collector URL host must be an IP address, not a name."))?;
        (IpAddr::V6(address), port)
    } else {
        let (host, port) = match authority.split_once(':') {
            Some((host, port)) => (host, Some(port)),
            None => (authority, None),
        };
        let address = host
            .parse::<Ipv4Addr>()
            .map_err(|_| Error::Invalid("Collector URL host must be an IP address, not a name."))?;
        (IpAddr::V4(address), port)
    };
    if let Some(port) = port
        && !(!port.is_empty()
            && port.bytes().all(|b| b.is_ascii_digit())
            && port.parse::<u16>().is_ok_and(|p| p > 0))
    {
        return Err(Error::Invalid(SHAPE));
    }
    if !is_private_network(host) {
        return Err(Error::Invalid(
            "Collector URL must use a private-network (RFC 1918 or IPv6 ULA) address.",
        ));
    }
    Ok(host)
}

/// RFC 1918 or IPv6 ULA (fc00::/7) only: never loopback, link-local,
/// unspecified, mapped or public addresses.
pub(super) fn is_private_network(address: IpAddr) -> bool {
    match address {
        IpAddr::V4(v4) => {
            let [a, b, ..] = v4.octets();
            a == 10 || (a == 172 && (16..=31).contains(&b)) || (a == 192 && b == 168)
        }
        IpAddr::V6(v6) => v6.segments()[0] & 0xfe00 == 0xfc00,
    }
}

fn render_conf(role: &str, url: &str) -> String {
    format!(
        "# Written by `openmates server host-reporter install`; re-run it to change values.\nROLE={role}\nCOLLECTOR_URL={url}\nDEPLOYED_IMAGES_FILE={IMAGES_FILE}\n"
    )
}

fn render_dropin(address: IpAddr) -> String {
    let prefix = if address.is_ipv6() { 128 } else { 32 };
    format!(
        "# Generated by `openmates server host-reporter` from --collector-url: the reporter may reach only the collector.\n[Service]\nIPAddressAllow={address}/{prefix}\n"
    )
}

/// Script, README, units and apt hook: everything `server update` refreshes.
fn payload(layout: &Layout) -> Vec<(PathBuf, &'static str, u32)> {
    let mut files = vec![
        (
            layout.path(&format!("{LIB_DIR}/openmates-host-reporter")),
            SCRIPT,
            0o755,
        ),
        (layout.path(&format!("{LIB_DIR}/README.md")), README, 0o644),
    ];
    for (name, content) in UNITS {
        files.push((layout.path(&format!("{UNIT_DIR}/{name}")), content, 0o644));
    }
    files.push((layout.path(APT_HOOK_FILE), APT_HOOK, 0o644));
    files
}

/// Parse `KEY=VALUE` lines exactly like the reporter's `read_conf`.
fn parse_conf(text: &str) -> BTreeMap<String, String> {
    text.lines()
        .map(str::trim)
        .filter(|line| !line.is_empty() && !line.starts_with('#'))
        .filter_map(|line| line.split_once('='))
        .map(|(key, value)| {
            (
                key.trim().to_owned(),
                value.trim().trim_matches(['"', '\'']).to_owned(),
            )
        })
        .collect()
}

fn read_conf(layout: &Layout) -> Result<(String, String)> {
    let snapshot = fs::host_snapshot(&layout.path(CONF_FILE), 64 * 1024)?;
    let text = std::str::from_utf8(&snapshot.bytes)
        .map_err(|_| Error::Invalid("Host reporter configuration must be UTF-8."))?;
    let conf = parse_conf(text);
    let role = role(conf.get("ROLE").map(String::as_str).unwrap_or_default())?.to_owned();
    let url = conf.get("COLLECTOR_URL").cloned().unwrap_or_default();
    collector_address(&url)?;
    Ok((role, url))
}

/// `install -d -m MODE`: create missing ancestors 0755, then force the
/// target directory's mode. Symlinks and non-directories are rejected.
fn ensure_dir(path: &Path, mode: u32) -> Result<()> {
    match std::fs::symlink_metadata(path) {
        Ok(meta) if meta.file_type().is_dir() => {}
        Ok(_) => {
            return Err(Error::Invalid(
                "A host reporter directory path exists but is not a directory.",
            ));
        }
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => {
            if let Some(parent) = path.parent()
                && !parent.try_exists()?
            {
                ensure_dir(parent, 0o755)?;
            }
            std::fs::DirBuilder::new().mode(mode).create(path)?;
        }
        Err(error) => return Err(error.into()),
    }
    std::fs::set_permissions(path, std::fs::Permissions::from_mode(mode))?;
    Ok(())
}

fn read_certificate(path: &str) -> Result<Vec<u8>> {
    let meta = std::fs::metadata(path)?;
    if !meta.is_file() || meta.len() > CERT_LIMIT {
        return Err(Error::Invalid(
            "Collector certificates must be regular PEM files under 64 KiB.",
        ));
    }
    let bytes = std::fs::read(path)?;
    if !bytes
        .windows(27)
        .any(|w| w == b"-----BEGIN CERTIFICATE-----")
    {
        return Err(Error::Invalid(
            "Collector certificate is not a PEM certificate.",
        ));
    }
    Ok(bytes)
}

fn system(program: &str, args: &[&str], input: Option<&[u8]>) -> Result<Zeroizing<Vec<u8>>> {
    let args = args.iter().map(|a| (*a).to_owned()).collect::<Vec<_>>();
    run_timeout(program, &args, Path::new("/"), input, SYSTEMCTL_TIMEOUT)
}

fn path_text(path: &Path) -> Result<&str> {
    path.to_str().ok_or(Error::Io)
}

fn public_key(layout: &Layout) -> Result<String> {
    let output = system(
        "ssh-keygen",
        &["-y", "-f", path_text(&layout.path(KEY_FILE))?],
        None,
    )?;
    let line = std::str::from_utf8(&output)
        .map_err(|_| Error::Protocol)?
        .trim();
    if !line.starts_with("ssh-ed25519 ") || line.contains(['\n', '"']) {
        return Err(Error::Invalid(
            "Host signing key did not yield an ed25519 public key.",
        ));
    }
    Ok(line.to_owned())
}

fn register_command(role: &str, public_key: &str) -> String {
    format!(
        "python3 scripts/security_monitoring/host_collector.py register-host --role {role} --pubkey \"{public_key}\""
    )
}

struct Install<'a> {
    role: &'a str,
    url: &'a str,
    address: IpAddr,
    collector_cert: Vec<u8>,
    collector_tls_cert: Vec<u8>,
    enable: bool,
}

fn write_payload(layout: &Layout, address: IpAddr) -> Result<()> {
    ensure_dir(&layout.path(LIB_DIR), 0o755)?;
    ensure_dir(&layout.path(ETC_DIR), 0o755)?;
    ensure_dir(&layout.path(DROPIN_DIR), 0o755)?;
    for (path, content, mode) in payload(layout) {
        if let Some(parent) = path.parent()
            && !parent.try_exists()?
        {
            ensure_dir(parent, 0o755)?;
        }
        fs::write(&path, content.as_bytes(), mode)?;
    }
    fs::write(
        &layout.path(&format!("{DROPIN_DIR}/{DROPIN_FILE}")),
        render_dropin(address).as_bytes(),
        0o644,
    )
}

/// Steps of install.sh after argument validation, in the same order.
fn apply(layout: &Layout, install: &Install) -> Result<Value> {
    for cert in [&install.collector_cert, &install.collector_tls_cert] {
        system("openssl", &["x509", "-noout"], Some(cert)).map_err(|_| {
            Error::Invalid("Collector certificate is not a valid PEM X.509 certificate.")
        })?;
    }
    let _critical = operation::critical()?;
    ensure_dir(&layout.path(CONF_DIR), 0o700)?;
    write_payload(layout, install.address)?;
    fs::write(
        &layout.path(&format!("{CONF_DIR}/collector.crt")),
        &install.collector_cert,
        0o644,
    )?;
    fs::write(
        &layout.path(&format!("{CONF_DIR}/collector-tls.crt")),
        &install.collector_tls_cert,
        0o644,
    )?;
    fs::write(
        &layout.path(CONF_FILE),
        render_conf(install.role, install.url).as_bytes(),
        0o644,
    )?;
    let key = layout.path(KEY_FILE);
    let generated = !key.try_exists()?;
    if generated {
        let comment = format!("openmates-host-report-{}", install.role);
        system(
            "ssh-keygen",
            &[
                "-q",
                "-t",
                "ed25519",
                "-N",
                "",
                "-C",
                &comment,
                "-f",
                path_text(&key)?,
            ],
            None,
        )?;
        match std::fs::remove_file(layout.path(&format!("{KEY_FILE}.pub"))) {
            Err(error) if error.kind() != std::io::ErrorKind::NotFound => return Err(error.into()),
            _ => {}
        }
    }
    if rustix::process::geteuid().is_root() {
        std::os::unix::fs::chown(&key, Some(0), Some(0))?;
    }
    std::fs::set_permissions(&key, std::fs::Permissions::from_mode(0o600))?;
    system("systemctl", &["daemon-reload"], None)?;
    if install.enable {
        system("systemctl", &["enable", "--now", TIMER], None)?;
    }
    let public_key = public_key(layout)?;
    Ok(json!({
        "command": "host-reporter install",
        "status": "installed",
        "role": install.role,
        "timerEnabled": install.enable,
        "signingKeyGenerated": generated,
        "publicKey": public_key,
        "registerCommand": register_command(install.role, &public_key),
        "deployedImagesFile": IMAGES_FILE,
        "next": [
            "Run registerCommand on the dev server in the OpenMates checkout.",
            "Send a first report: systemctl start openmates-host-reporter.service",
            "Check the result: openmates server host-reporter status",
            "deployed-images.json is written by the next `openmates server update`."
        ],
    }))
}

/// `server update`: refresh script, units and hook of an installed reporter
/// and record running image digests. Never installs an unconfigured reporter.
pub(super) fn after_update(c: &Configuration) -> Result<Value> {
    let layout = Layout::system();
    if !layout.installed()? {
        return Ok(json!({"status":"not_installed"}));
    }
    if !rustix::process::geteuid().is_root() {
        return Ok(json!({"status":"skipped_requires_root"}));
    }
    let refreshed = refresh(&layout)?;
    let images = write_deployed_images(c, &layout)?;
    Ok(json!({"status":refreshed,"deployedImages":{"status":"written","count":images}}))
}

fn refresh(layout: &Layout) -> Result<&'static str> {
    let (_, url) = read_conf(layout)?;
    let _critical = operation::critical()?;
    write_payload(layout, collector_address(&url)?)?;
    system("systemctl", &["daemon-reload"], None)?;
    Ok("refreshed")
}

fn compose_rows(output: &[u8]) -> Result<Vec<Value>> {
    if output.iter().all(u8::is_ascii_whitespace) {
        return Ok(vec![]);
    }
    if let Ok(value) = serde_json::from_slice::<Value>(output) {
        return Ok(match value {
            Value::Array(rows) => rows,
            row => vec![row],
        });
    }
    Ok(std::str::from_utf8(output)
        .map_err(|_| Error::Protocol)?
        .lines()
        .filter(|line| !line.trim().is_empty())
        .map(serde_json::from_str::<Value>)
        .collect::<std::result::Result<Vec<_>, _>>()?)
}

/// `registry/name:tag@sha256:..` -> `registry/name` (a registry port is kept).
fn repository(image: &str) -> &str {
    let image = image.split('@').next().unwrap_or(image);
    match image.rfind(':') {
        Some(colon) if !image[colon..].contains('/') => &image[..colon],
        _ => image,
    }
}

/// Prefer the registry digest of the image's own repository; locally built
/// images have none, so their content-addressed image ID is recorded.
fn image_digest(image: &str, inspect: &str) -> Result<String> {
    let (digests, id) = inspect.trim().split_once('|').ok_or(Error::Protocol)?;
    let digests: Vec<String> = serde_json::from_str::<Option<Vec<String>>>(digests)
        .map_err(|_| Error::Protocol)?
        .unwrap_or_default();
    let wanted = repository(image);
    let selected = digests
        .iter()
        .find(|d| d.split_once('@').is_some_and(|(repo, _)| repo == wanted))
        .or_else(|| digests.first())
        .and_then(|d| d.split_once('@').map(|(_, digest)| digest.to_owned()));
    let digest = selected.unwrap_or_else(|| id.trim().to_owned());
    if !digest.starts_with("sha256:") || digest.len() != 71 {
        return Err(Error::Invalid(
            "Docker returned an unexpected image digest.",
        ));
    }
    Ok(digest)
}

fn deployed_images(c: &Configuration) -> Result<BTreeMap<String, String>> {
    let rows = compose_rows(&docker(c, ["ps".into(), "--format".into(), "json".into()])?)?;
    let mut images = BTreeMap::new();
    for row in rows {
        let image = row["Image"].as_str().ok_or(Error::Protocol)?;
        if image.is_empty() || image.len() > 512 || image.starts_with('-') {
            return Err(Error::Protocol);
        }
        if images.contains_key(image) {
            continue;
        }
        let inspect = run(
            "docker",
            &[
                "image".into(),
                "inspect".into(),
                "--format".into(),
                "{{json .RepoDigests}}|{{.Id}}".into(),
                image.into(),
            ],
            &c.install_path,
            None,
        )?;
        let inspect = std::str::from_utf8(&inspect).map_err(|_| Error::Protocol)?;
        images.insert(image.to_owned(), image_digest(image, inspect)?);
    }
    Ok(images)
}

fn write_deployed_images(c: &Configuration, layout: &Layout) -> Result<usize> {
    let images = deployed_images(c)?;
    ensure_dir(&layout.path(IMAGES_DIR), 0o755)?;
    let body = serde_json::to_vec_pretty(&json!({"images": images}))?;
    fs::write(&layout.path(IMAGES_FILE), &body, 0o644)?;
    Ok(images.len())
}

fn show(unit: &str, properties: &str) -> Result<BTreeMap<String, String>> {
    let output = system("systemctl", &["show", unit, "--property", properties], None)?;
    Ok(std::str::from_utf8(&output)
        .map_err(|_| Error::Protocol)?
        .lines()
        .filter_map(|line| line.split_once('='))
        .map(|(k, v)| (k.to_owned(), v.to_owned()))
        .collect())
}

/// Classify the reporter's latest journal outcome without echoing raw log text.
fn push_outcome(journal: &str) -> Value {
    for line in journal.lines().rev() {
        let line = line.trim();
        if line.ends_with("host report delivered") {
            return json!({"outcome":"delivered"});
        }
        if let Some(rest) = line.split("collector delivery failed (curl exit ").nth(1) {
            let code = rest.trim_end_matches(')').parse::<u16>().ok();
            return json!({"outcome":"delivery_failed","curlExit":code});
        }
        if line.starts_with("openmates-host-reporter: ") {
            return json!({"outcome":"reporter_error"});
        }
    }
    json!({"outcome":"unknown"})
}

fn status(layout: &Layout) -> Result<Value> {
    if !layout.installed()? {
        return Ok(json!({"command":"host-reporter status","status":"not_installed"}));
    }
    let (role, _) = read_conf(layout)?;
    let timer = show(
        TIMER,
        "ActiveState,UnitFileState,LastTriggerUSec,NextElapseUSecRealtime",
    )?;
    let service = show(SERVICE, "Result,ExecMainStatus,ExecMainExitTimestamp")?;
    let journal = system(
        "journalctl",
        &["-u", SERVICE, "-n", "50", "-o", "cat", "--no-pager"],
        None,
    )?;
    let outcome = push_outcome(std::str::from_utf8(&journal).unwrap_or_default());
    let field =
        |map: &BTreeMap<String, String>, key: &str| map.get(key).filter(|v| !v.is_empty()).cloned();
    let public_key = if rustix::process::geteuid().is_root() {
        Some(public_key(layout)?)
    } else {
        None
    };
    let active = timer.get("ActiveState").is_some_and(|s| s == "active");
    Ok(json!({
        "command": "host-reporter status",
        "status": if active { "active" } else { "degraded" },
        "role": role,
        "timer": {
            "active": active,
            "enabled": timer.get("UnitFileState").is_some_and(|s| s == "enabled"),
            "lastTrigger": field(&timer, "LastTriggerUSec"),
            "nextRun": field(&timer, "NextElapseUSecRealtime"),
        },
        "lastRun": {
            "result": field(&service, "Result"),
            "exitStatus": field(&service, "ExecMainStatus"),
            "finishedAt": field(&service, "ExecMainExitTimestamp"),
        },
        "lastPush": outcome,
        "publicKey": public_key,
    }))
}

fn remove(path: &Path, directory: bool) -> Result<bool> {
    let result = if directory {
        std::fs::remove_dir_all(path)
    } else {
        std::fs::remove_file(path)
    };
    match result {
        Ok(()) => Ok(true),
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => Ok(false),
        Err(error) => Err(error.into()),
    }
}

/// README "Remove": disable the timer, delete units, drop-ins, apt hook,
/// configuration, signing key and script.
fn uninstall(layout: &Layout) -> Result<Value> {
    let _critical = operation::critical()?;
    if layout.path(&format!("{UNIT_DIR}/{TIMER}")).try_exists()? {
        system("systemctl", &["disable", "--now", TIMER], None)?;
    }
    let mut removed = vec![];
    let mut targets = UNITS
        .iter()
        .map(|(name, _)| (format!("{UNIT_DIR}/{name}"), false))
        .collect::<Vec<_>>();
    targets.extend([
        (DROPIN_DIR.to_owned(), true),
        (APT_HOOK_FILE.to_owned(), false),
        (CONF_FILE.to_owned(), false),
        (CONF_DIR.to_owned(), true),
        (LIB_DIR.to_owned(), true),
    ]);
    for (target, directory) in targets {
        if remove(&layout.path(&target), directory)? {
            removed.push(target);
        }
    }
    system("systemctl", &["daemon-reload"], None)?;
    Ok(json!({
        "command": "host-reporter uninstall",
        "status": "uninstalled",
        "removed": removed,
        "note": "The host signing key was deleted; a reinstall generates a new key that must be registered again.",
    }))
}

fn on_path(tool: &str) -> bool {
    std::env::var_os("PATH").is_some_and(|paths| {
        std::env::split_paths(&paths).any(|dir| {
            std::fs::metadata(dir.join(tool))
                .is_ok_and(|m| m.is_file() && m.permissions().mode() & 0o111 != 0)
        })
    })
}

fn required<'a>(flags: &'a Flags, key: &str, message: &'static str) -> Result<&'a str> {
    text(flags, key).ok_or(Error::Invalid(message))
}

pub(super) fn execute(action: &str, flags: &Flags) -> Result<Value> {
    if !cfg!(target_os = "linux") {
        return Err(Error::Invalid("The host reporter requires Linux systemd."));
    }
    let layout = Layout::system();
    let root = rustix::process::geteuid().is_root();
    match action {
        "host-reporter install" => {
            let role = role(required(
                flags,
                "role",
                "--role core|upload|preview is required.",
            )?)?;
            let url = required(flags, "collector-url", "--collector-url is required.")?;
            let address = collector_address(url)?;
            let install = Install {
                role,
                url,
                address,
                collector_cert: read_certificate(required(
                    flags,
                    "collector-cert",
                    "--collector-cert is required.",
                )?)?,
                collector_tls_cert: read_certificate(required(
                    flags,
                    "collector-tls-cert",
                    "--collector-tls-cert is required.",
                )?)?,
                enable: !boolean(flags, "no-enable"),
            };
            if boolean(flags, "dry-run") {
                let mut files = payload(&layout)
                    .into_iter()
                    .map(|(path, _, mode)| json!({"path":path,"mode":format!("{mode:o}")}))
                    .collect::<Vec<_>>();
                files.push(json!({"path":layout.path(CONF_FILE),"mode":"644","content":render_conf(role, url)}));
                files.push(json!({"path":layout.path(&format!("{DROPIN_DIR}/{DROPIN_FILE}")),"mode":"644","content":render_dropin(address)}));
                return Ok(json!({"command":action,"status":"planned","role":role,"files":files}));
            }
            if !root {
                return Err(Error::Invalid(
                    "Host reporter installation must run as root.",
                ));
            }
            if !REQUIRED_TOOLS.iter().all(|tool| on_path(tool)) {
                return Err(Error::Invalid(
                    "Missing a required host tool (python3, ssh-keygen, openssl, curl, dpkg-query, apt-get, ss, systemctl).",
                ));
            }
            apply(&layout, &install)
        }
        "host-reporter" | "host-reporter status" => status(&layout),
        "host-reporter uninstall" => {
            if !boolean(flags, "yes") {
                return Err(Error::Invalid(
                    "Removing the host reporter deletes its signing key; pass --yes to confirm.",
                ));
            }
            if !root {
                return Err(Error::Invalid("Host reporter removal must run as root."));
            }
            uninstall(&layout)
        }
        _ => Err(Error::Invalid("Unknown host-reporter action.")),
    }
}

#[cfg(test)]
#[path = "host_reporter_tests.rs"]
mod tests;
