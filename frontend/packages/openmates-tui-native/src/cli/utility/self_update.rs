//! `update` / `upgrade` for the native Rust CLI (npm handleSelfUpdate).
//!
//! The Rust CLI is installed with `cargo install openmates`, so it updates
//! through cargo into its own installation path. It never runs npm, pnpm,
//! yarn or bun and never replaces the separately installed npm `openmates`
//! command (see .claude/rules/cli-sdk.md). Version availability comes from the
//! crates.io registry; OPENMATES_CLI_LATEST_VERSION overrides it like npm.
use super::super::{CliError, CliOutput, Invocation, handlers};
use serde_json::{Value, json};
use std::path::PathBuf;

const PACKAGE: &str = "openmates";
const REGISTRY: &str = "https://crates.io/api/v1/crates/openmates";
const LOGO: &str = " ██████  ██████  ███████ ███    ██ ███    ███  █████  ████████ ███████ ███████\n██    ██ ██   ██ ██      ████   ██ ████  ████ ██   ██    ██    ██      ██     \n██    ██ ██████  █████   ██ ██  ██ ██ ████ ██ ███████    ██    █████   ███████\n██    ██ ██      ██      ██  ██ ██ ██  ██  ██ ██   ██    ██    ██           ██\n ██████  ██      ███████ ██   ████ ██      ██ ██   ██    ██    ███████ ███████\nOPENMATES";

pub(super) fn supported(i: &Invocation) -> bool {
    matches!(i.command_path().as_str(), "update" | "upgrade")
}
fn fail(message: impl Into<String>) -> CliError {
    CliError::Invalid(message.into())
}

#[derive(Clone, Copy, PartialEq, Eq, Debug)]
pub(super) enum Channel {
    Dev,
    Stable,
}
impl Channel {
    fn name(self) -> &'static str {
        match self {
            Channel::Dev => "dev",
            Channel::Stable => "stable",
        }
    }
}
pub(super) fn parse_channel(value: &str) -> Result<Channel, CliError> {
    match value {
        "dev" => Ok(Channel::Dev),
        "stable" | "main" => Ok(Channel::Stable),
        _ => Err(fail(
            "--channel must be dev, stable, or main (alias for stable)",
        )),
    }
}
fn update_dir() -> Result<PathBuf, CliError> {
    if let Some(dir) = std::env::var_os("OPENMATES_UPDATE_DIR").filter(|v| !v.is_empty()) {
        return Ok(PathBuf::from(dir));
    }
    Ok(directories::BaseDirs::new()
        .ok_or(crate::error::Error::Io)?
        .home_dir()
        .join(".openmates"))
}
/// The release channel file is shared with the npm CLI (`updates.json`).
fn saved_channel(current: &str) -> Result<Channel, CliError> {
    let path = update_dir()?.join("updates.json");
    match std::fs::read_to_string(&path) {
        Ok(raw) => {
            let value: Value =
                serde_json::from_str(&raw).map_err(|_| fail("Invalid release channel file."))?;
            parse_channel(value["channel"].as_str().unwrap_or(""))
        }
        Err(e) if e.kind() == std::io::ErrorKind::NotFound => Ok(if current.contains('-') {
            Channel::Dev
        } else {
            Channel::Stable
        }),
        Err(_) => Err(fail("Could not read the release channel file.")),
    }
}
fn persist_channel(channel: Channel) -> Result<(), CliError> {
    let dir = update_dir()?;
    std::fs::create_dir_all(&dir).map_err(|_| fail("Could not save the release channel."))?;
    let path = dir.join("updates.json");
    let temporary = dir.join(format!("updates.json.{}.tmp", std::process::id()));
    let body = format!("{}\n", json!({"channel": channel.name()}));
    {
        use std::io::Write;
        let mut options = std::fs::OpenOptions::new();
        options.write(true).create(true).truncate(true);
        #[cfg(unix)]
        std::os::unix::fs::OpenOptionsExt::mode(&mut options, 0o600);
        let mut file = options
            .open(&temporary)
            .map_err(|_| fail("Could not save the release channel."))?;
        file.write_all(body.as_bytes())
            .map_err(|_| fail("Could not save the release channel."))?;
    }
    std::fs::rename(&temporary, &path).map_err(|_| fail("Could not save the release channel."))
}

/// npm parseTarget (SAFE_TARGET_RE).
pub(super) fn parse_target(value: &str) -> Result<String, CliError> {
    if value.is_empty() {
        return Err(fail("--version requires a version or npm dist-tag"));
    }
    if !value
        .bytes()
        .all(|b| b.is_ascii_alphanumeric() || b"._@+~:-".contains(&b))
    {
        return Err(fail("--version contains unsupported characters"));
    }
    Ok(value.to_owned())
}
fn exact_version(target: &str) -> bool {
    parse_version(target.split('+').next().unwrap_or(target)).is_some()
}

struct Version {
    core: [u64; 3],
    pre: Option<Vec<String>>,
}
fn parse_version(value: &str) -> Option<Version> {
    let value = value.split('+').next()?;
    let (core, pre) = match value.split_once('-') {
        Some((core, pre)) if !pre.is_empty() => (core, Some(pre)),
        Some(_) => return None,
        None => (value, None),
    };
    let parts: Vec<u64> = core
        .split('.')
        .map(|p| p.parse().ok())
        .collect::<Option<_>>()?;
    let core: [u64; 3] = parts.try_into().ok()?;
    Some(Version {
        core,
        pre: pre.map(|p| p.split('.').map(str::to_owned).collect()),
    })
}
/// npm compareVersions (SemVer precedence).
pub(super) fn compare_versions(left: &str, right: &str) -> Result<std::cmp::Ordering, CliError> {
    use std::cmp::Ordering;
    let (Some(a), Some(b)) = (parse_version(left), parse_version(right)) else {
        let bad = if parse_version(left).is_none() {
            left
        } else {
            right
        };
        return Err(fail(format!("Cannot compare CLI version '{bad}'")));
    };
    if a.core != b.core {
        return Ok(a.core.cmp(&b.core));
    }
    let (ap, bp) = match (&a.pre, &b.pre) {
        (None, None) => return Ok(Ordering::Equal),
        (Some(_), None) => return Ok(Ordering::Less),
        (None, Some(_)) => return Ok(Ordering::Greater),
        (Some(a), Some(b)) => (a, b),
    };
    for index in 0..ap.len().max(bp.len()) {
        let (Some(x), Some(y)) = (ap.get(index), bp.get(index)) else {
            return Ok(if ap.len() < bp.len() {
                Ordering::Less
            } else {
                Ordering::Greater
            });
        };
        if x == y {
            continue;
        }
        let numeric = |s: &str| !s.is_empty() && s.bytes().all(|b| b.is_ascii_digit());
        return Ok(match (numeric(x), numeric(y)) {
            (true, true) => {
                let (x, y) = (x.trim_start_matches('0'), y.trim_start_matches('0'));
                x.len().cmp(&y.len()).then_with(|| x.cmp(y))
            }
            (true, false) => Ordering::Less,
            (false, true) => Ordering::Greater,
            _ => x.as_str().cmp(y.as_str()),
        });
    }
    Ok(Ordering::Equal)
}

/// crates.io metadata → the version a target (exact, `latest` or `alpha`) names.
pub(super) fn resolve_from_registry(target: &str, registry: &Value) -> Result<String, String> {
    let field = match target {
        "latest" => "max_stable_version",
        "alpha" | "next" => "max_version",
        other => {
            return Err(format!(
                "crates.io has no '{other}' release tag for {PACKAGE}"
            ));
        }
    };
    registry["crate"][field]
        .as_str()
        .filter(|v| !v.is_empty())
        .map(str::to_owned)
        .ok_or_else(|| format!("crates.io did not return a {target} version for {PACKAGE}"))
}
async fn resolve_target(target: &str) -> Result<String, String> {
    if let Ok(forced) = std::env::var("OPENMATES_CLI_LATEST_VERSION") {
        if !forced.trim().is_empty() {
            return Ok(forced.trim().to_owned());
        }
    }
    if exact_version(target) {
        return Ok(target.to_owned());
    }
    let client = reqwest::Client::builder()
        .user_agent(concat!("openmates-cli/", env!("CARGO_PKG_VERSION")))
        .timeout(std::time::Duration::from_secs(30))
        .build()
        .map_err(|e| e.to_string())?;
    let response = client
        .get(REGISTRY)
        .send()
        .await
        .map_err(|e| e.to_string())?;
    let status = response.status();
    if status == reqwest::StatusCode::NOT_FOUND {
        return Err(format!("{PACKAGE} is not published on crates.io"));
    }
    if !status.is_success() {
        return Err(format!("crates.io returned HTTP {}", status.as_u16()));
    }
    let body: Value = response.json().await.map_err(|e| e.to_string())?;
    resolve_from_registry(target, &body)
}

pub(super) struct Plan {
    pub channel: Channel,
    pub persist_channel: bool,
    pub allow_downgrade: bool,
    pub target: String,
    pub current: String,
    pub dry_run: bool,
}
impl Plan {
    pub(super) fn run(&self) -> Vec<String> {
        [
            "cargo",
            "install",
            PACKAGE,
            "--version",
            &self.target,
            "--locked",
        ]
        .map(str::to_owned)
        .to_vec()
    }
    fn package(&self) -> String {
        format!("{PACKAGE}@{}", self.target)
    }
}
pub(super) fn plan(i: &Invocation, current: &str) -> Result<Plan, CliError> {
    if let Some(manager) = i.text("package-manager") {
        if manager != "cargo" {
            return Err(fail(
                "--package-manager must be cargo for the native Rust CLI; npm, pnpm, yarn and bun manage the separate npm CLI",
            ));
        }
    }
    let channel = match i.text("channel") {
        Some(value) => parse_channel(value)?,
        None => saved_channel(current)?,
    };
    let target = match i.text("version") {
        Some(value) => parse_target(value)?,
        None => (if channel == Channel::Dev {
            "alpha"
        } else {
            "latest"
        })
        .to_owned(),
    };
    Ok(Plan {
        channel,
        persist_channel: i.has("channel"),
        allow_downgrade: i.boolean("allow-downgrade"),
        target,
        current: current.to_owned(),
        dry_run: i.boolean("dry-run"),
    })
}
fn update_available(plan: &Plan, latest: &str) -> Result<bool, CliError> {
    let order = compare_versions(latest, &plan.current)?;
    Ok(order.is_gt() || (plan.allow_downgrade && order.is_ne()))
}
fn install(plan: &Plan, verbose: bool, stderr: &mut String) -> Result<(), CliError> {
    let run = plan.run();
    let result = std::process::Command::new(&run[0])
        .args(&run[1..])
        .stdin(std::process::Stdio::null())
        .output()
        .map_err(|e| fail(format!("Unable to run cargo: {e}")))?;
    let out = String::from_utf8_lossy(&result.stdout).into_owned();
    let err = String::from_utf8_lossy(&result.stderr).into_owned();
    if verbose {
        stderr.push_str(&out);
        stderr.push_str(&err);
    }
    if !result.status.success() {
        let output = [out.trim(), err.trim()]
            .into_iter()
            .filter(|s| !s.is_empty())
            .collect::<Vec<_>>()
            .join("\n");
        let code = result
            .status
            .code()
            .map_or_else(|| "unknown".to_owned(), |c| c.to_string());
        let suffix = if output.is_empty() {
            String::new()
        } else {
            format!("\n{output}")
        };
        return Err(fail(format!(
            "{} failed with exit code {code}{suffix}",
            run.join(" ")
        )));
    }
    Ok(())
}
pub(super) async fn execute(i: &Invocation) -> Result<CliOutput, CliError> {
    handlers::flags(
        i,
        &[
            "version",
            "package-manager",
            "dry-run",
            "verbose",
            "channel",
            "allow-downgrade",
        ],
    )?;
    let command = i.command_path();
    let mut plan = plan(i, env!("CARGO_PKG_VERSION"))?;
    let latest = resolve_target(&plan.target)
        .await
        .map_err(|e| fail(format!("Update check failed: {e}")))?;
    let available = update_available(&plan, &latest)?;
    if !plan.dry_run && available {
        plan.target = parse_target(&latest)?;
    }
    let mut stderr = String::new();
    let verbose = i.boolean("verbose");
    if i.boolean("json") {
        if !plan.dry_run && available {
            install(&plan, verbose, &mut stderr)?;
        }
        if !plan.dry_run && plan.persist_channel {
            persist_channel(plan.channel)?;
        }
        let status = if !available {
            "up_to_date"
        } else if plan.dry_run {
            "planned"
        } else {
            "success"
        };
        let mut output = CliOutput::json(&json!({
            "command": command, "channel": plan.channel.name(), "status": status,
            "current_version": plan.current, "latest_version": latest,
            "update_available": available, "check_error": null, "package_manager": "cargo",
            "package": plan.package(), "run": plan.run(), "dry_run": plan.dry_run,
            "implementation": "rust",
        }))?;
        output.stderr = stderr;
        return Ok(output);
    }
    let mut out = format!(
        "{LOGO}\n\nChecking for updates...\n\nRelease channel: {}\nCurrent version: {}\nLatest version:  {latest}\n\n",
        plan.channel.name(),
        plan.current
    );
    if !available {
        if !plan.dry_run && plan.persist_channel {
            persist_channel(plan.channel)?;
        }
        out.push_str("OpenMates CLI is already up to date.");
    } else if plan.dry_run {
        out.push_str(&format!("Would run: {}", plan.run().join(" ")));
    } else {
        out.push_str("Updating OpenMates CLI with cargo...\n");
        install(&plan, verbose, &mut stderr)?;
        if plan.persist_channel {
            persist_channel(plan.channel)?;
        }
        out.push_str(&format!(
            "Installed OpenMates CLI {latest}.\n\nOpenMates CLI is up to date."
        ));
    }
    let mut output = CliOutput::text(out);
    output.stderr = stderr;
    Ok(output)
}
