//! Pure Proton Mail Bridge connector logic (npm protonBridgeConnector.ts
//! parity): Bridge info parsing, command resolution, credential hygiene,
//! IMAP/SMTP message building and parsing, and the delayed-send queue. No
//! sockets or processes live here so every rule is testable with fixtures.
use regex::Regex;
use serde_json::{Value, json};
use std::collections::BTreeMap;
use std::sync::OnceLock;
use std::time::{Duration, Instant};

pub(super) const PROVIDER_ID: &str = "protonmail_bridge";
pub(super) const APP_ID: &str = "mail";
pub(super) const WRITE_DELAY_SECONDS: u64 = 30;
pub(super) const DEFAULT_HEARTBEAT_MS: u64 = 25_000;
const PAID_PLAN: &str = "Proton Mail Bridge requires a paid Proton Mail plan; free Proton accounts cannot use Bridge IMAP/SMTP access.";
pub(super) const MACOS_BRIDGE: &str =
    "/Applications/Proton Mail Bridge.app/Contents/MacOS/Proton Mail Bridge";

#[derive(Clone, PartialEq, Eq)]
pub(super) struct Credentials {
    pub account_label: Option<String>,
    pub imap_host: String,
    pub imap_port: u16,
    pub imap_username: String,
    pub imap_password: String,
    pub smtp_host: Option<String>,
    pub smtp_port: Option<u16>,
    pub smtp_username: Option<String>,
    pub smtp_password: Option<String>,
}
impl std::fmt::Debug for Credentials {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str("Credentials(<redacted>)")
    }
}

#[derive(Debug, PartialEq, Eq)]
pub(super) struct BridgeCommand {
    pub command: String,
    pub args: Vec<&'static str>,
    pub should_start: bool,
    pub guidance: Option<String>,
}

fn re(cell: &'static OnceLock<Regex>, pattern: &str) -> &'static Regex {
    cell.get_or_init(|| Regex::new(pattern).expect("static pattern"))
}
const KEYS: &str = r"(?:bridge[_ -]?password|proton[_ -]?password|imap[_ -]?password|smtp[_ -]?password|access[_ -]?token|refresh[_ -]?token|password)";

/// npm rejectProtonCredentialFlags: the user-facing message for a refused flag.
pub(super) fn reject_credential_flags<'a>(
    flags: impl IntoIterator<Item = &'a str>,
) -> Result<(), String> {
    static CELL: OnceLock<Regex> = OnceLock::new();
    let flag = re(
        &CELL,
        r"^--(?:bridge-password|password|imap-password|smtp-password|proton-password|access-token|refresh-token)(?:=|$)",
    );
    for raw in flags {
        let dashed = format!("--{raw}");
        if flag.is_match(&dashed) {
            return Err(format!(
                "{dashed} is not allowed. Bridge credentials must be read privately from Proton Bridge or a hidden prompt."
            ));
        }
    }
    Ok(())
}
pub(super) fn redact_secrets(text: &str) -> String {
    static CELL: OnceLock<Regex> = OnceLock::new();
    re(&CELL, &format!(r"(?i)(\b{KEYS}\b\s*[:=]\s*)([^\s,;]+)"))
        .replace_all(text, "${1}<redacted>")
        .into_owned()
}
pub(super) fn contains_credential_key(value: &Value) -> bool {
    static CELL: OnceLock<Regex> = OnceLock::new();
    let key = re(&CELL, &format!(r"(?i)\b{KEYS}\b"));
    match value {
        Value::Array(items) => items.iter().any(contains_credential_key),
        Value::Object(map) => map
            .iter()
            .any(|(k, v)| key.is_match(k) || contains_credential_key(v)),
        _ => false,
    }
}

pub(super) fn resolve_bridge_command(
    platform: &str,
    arch: &str,
    exists: impl Fn(&str) -> bool,
    find: impl Fn(&str) -> Option<String>,
    has_homebrew: bool,
) -> Result<BridgeCommand, String> {
    let blocked = |command: &str, guidance: String| BridgeCommand {
        command: command.to_owned(),
        args: vec!["-c"],
        should_start: false,
        guidance: Some(guidance),
    };
    match platform {
        "macos" => {
            if exists(MACOS_BRIDGE) {
                return Ok(BridgeCommand {
                    command: MACOS_BRIDGE.to_owned(),
                    args: vec!["-c"],
                    should_start: true,
                    guidance: None,
                });
            }
            Ok(blocked(MACOS_BRIDGE, install_guidance(true, has_homebrew)))
        }
        "linux" => {
            if arch != "x86_64" {
                return Ok(blocked(
                    "protonmail-bridge",
                    unsupported_arch_guidance(arch),
                ));
            }
            Ok(match find("protonmail-bridge") {
                Some(path) => BridgeCommand {
                    command: path,
                    args: vec!["-c"],
                    should_start: true,
                    guidance: None,
                },
                None => blocked("protonmail-bridge", install_guidance(false, false)),
            })
        }
        _ => Err("Proton Bridge connector supports macOS and Linux only.".to_owned()),
    }
}
fn unsupported_arch_guidance(arch: &str) -> String {
    [
        format!("Proton Mail Bridge is not supported by OpenMates on Linux {arch}."),
        "Proton's official Bridge requirements say Linux ARM devices are not supported; Apple silicon Macs are the only ARM exception.".to_owned(),
        "OpenMates will not use community Linux ARM Bridge packages for Proton accounts because Bridge handles Proton login, mailbox access, and Bridge-generated IMAP/SMTP credentials.".to_owned(),
        "Use an official amd64 Linux Bridge install, a Mac with the official Bridge app, or GitHub Actions' amd64 runner for live Proton Bridge tests.".to_owned(),
    ].join("\n")
}
fn install_guidance(macos: bool, homebrew: bool) -> String {
    let mut lines = vec![
        "Proton Mail Bridge is required for local Proton Mail access.".to_owned(),
        PAID_PLAN.to_owned(),
    ];
    if macos {
        lines.push(if homebrew {
            "Run: brew install --cask proton-mail-bridge".to_owned()
        } else {
            "Install Homebrew or download Proton Mail Bridge from Proton's official website."
                .to_owned()
        });
    } else {
        lines.extend([
            "For Debian/Ubuntu, follow Proton's official DEB instructions: https://proton.me/support/installing-bridge-linux-deb-file".to_owned(),
            "For RPM or Arch/PKGBUILD systems, use Proton's current Bridge download/support page and verify the package before installing.".to_owned(),
            "Package versions change, so prefer Proton's current support page over hardcoded stale package names.".to_owned(),
            "Bridge also requires a supported Linux keychain such as secret-service/GNOME Keyring or pass.".to_owned(),
        ]);
    }
    lines.push("After installing, run `openmates connect-account proton` again.".to_owned());
    lines.join("\n")
}
pub(super) fn write_warning() -> String {
    format!(
        "Write mode warning: OpenMates can submit outbound Proton Mail through local Bridge while this connector runs.\nEvery send is queued for {WRITE_DELAY_SECONDS} seconds so you can undo before delivery. After delivery, OpenMates cannot recall the email."
    )
}
pub(super) fn startup_message(write: bool) -> String {
    let mut lines = vec![
        "Proton Mail Bridge connector starting in read-only mode by default.".to_owned(),
        PAID_PLAN.to_owned(),
        "OpenMates Proton access is active only while this command keeps running.".to_owned(),
        "For long-lived use, run this command inside screen, tmux, or zellij.".to_owned(),
    ];
    if write {
        lines.push(write_warning());
    }
    lines.join("\n")
}

fn norm(key: &str) -> String {
    key.split_whitespace()
        .collect::<Vec<_>>()
        .join(" ")
        .to_lowercase()
        .replace('_', " ")
}
fn first(map: &BTreeMap<String, String>, keys: &[&str]) -> Option<String> {
    keys.iter()
        .find_map(|k| map.get(&norm(k)).filter(|v| !v.is_empty()).cloned())
}
fn port(value: Option<String>, label: &str) -> Result<u16, String> {
    let text = value.ok_or_else(|| format!("Missing Bridge {label} port."))?;
    let digits: String = text
        .trim()
        .chars()
        .take_while(char::is_ascii_digit)
        .collect();
    digits
        .parse::<u32>()
        .map_err(|_| format!("Bridge {label} port is invalid."))
        .and_then(|p| {
            u16::try_from(p)
                .ok()
                .filter(|p| *p > 0)
                .ok_or_else(|| format!("Bridge {label} port must be a valid TCP port."))
        })
}
pub(super) fn parse_bridge_info(output: &str) -> Result<Credentials, String> {
    let mut sections: BTreeMap<String, BTreeMap<String, String>> = BTreeMap::new();
    sections.insert("all".into(), BTreeMap::new());
    let mut current = "all".to_owned();
    for raw in output.lines() {
        let line = raw.trim();
        if line.is_empty() {
            continue;
        }
        let head = line.trim_end_matches(':');
        if matches!(
            head.to_lowercase().as_str(),
            "imap" | "imap settings" | "smtp" | "smtp settings"
        ) {
            current = norm(head);
            sections.entry(current.clone()).or_default();
            continue;
        }
        let Some(sep) = line.find(':').or_else(|| line.find('=')).filter(|s| *s > 0) else {
            continue;
        };
        let key = norm(&line[..sep]);
        let value = line[sep + 1..].trim().to_owned();
        sections
            .entry(current.clone())
            .or_default()
            .insert(key.clone(), value.clone());
        sections.entry("all".into()).or_default().insert(key, value);
    }
    let empty = BTreeMap::new();
    let get = |a: &str, b: &str| {
        sections
            .get(a)
            .or_else(|| sections.get(b))
            .unwrap_or(&empty)
    };
    let (imap, smtp, all) = (
        get("imap", "imap settings"),
        get("smtp", "smtp settings"),
        &sections["all"],
    );
    let imap_host = first(imap, &["address", "host", "server"])
        .or_else(|| first(all, &["imap address", "imap host"]));
    let imap_port = port(
        first(imap, &["port"]).or_else(|| first(all, &["imap port"])),
        "IMAP",
    )?;
    let imap_username =
        first(imap, &["username", "login"]).or_else(|| first(all, &["imap username", "username"]));
    let imap_password =
        first(imap, &["password"]).or_else(|| first(all, &["imap password", "password"]));
    let (Some(imap_host), Some(imap_username), Some(imap_password)) =
        (imap_host, imap_username, imap_password)
    else {
        return Err(
            "Could not read Bridge IMAP credentials from Proton Bridge info output.".to_owned(),
        );
    };
    let smtp_port_text = first(smtp, &["port"]).or_else(|| first(all, &["smtp port"]));
    let credentials = Credentials {
        account_label: first(all, &["email", "address", "account", "username"]),
        imap_host,
        imap_port,
        imap_username,
        imap_password,
        smtp_host: first(smtp, &["address", "host", "server"])
            .or_else(|| first(all, &["smtp address", "smtp host"])),
        smtp_port: smtp_port_text.map(|t| port(Some(t), "SMTP")).transpose()?,
        smtp_username: first(smtp, &["username", "login"])
            .or_else(|| first(all, &["smtp username"])),
        smtp_password: first(smtp, &["password"]).or_else(|| first(all, &["smtp password"])),
    };
    validate(&credentials)?;
    Ok(credentials)
}
fn local_host(host: &str, label: &str) -> Result<(), String> {
    let normalized = host.to_lowercase();
    let normalized = normalized.trim_start_matches('[').trim_end_matches(']');
    if matches!(normalized, "localhost" | "127.0.0.1" | "::1") {
        Ok(())
    } else {
        Err(format!(
            "Bridge {label} host must be localhost, not {host}."
        ))
    }
}
pub(super) fn validate(c: &Credentials) -> Result<(), String> {
    local_host(&c.imap_host, "IMAP")?;
    if let Some(host) = &c.smtp_host {
        local_host(host, "SMTP")?;
    }
    Ok(())
}
pub(super) fn registration(instance: &str, c: &Credentials, write: bool) -> Result<Value, String> {
    validate(c)?;
    let caps = if write {
        json!(["read", "write"])
    } else {
        json!(["read"])
    };
    let mut metadata = json!({
        "bridge_host": "localhost", "bridge_transport": "imap_smtp", "capabilities": caps,
    });
    if write {
        metadata["write_delay_seconds"] = json!(WRITE_DELAY_SECONDS);
    }
    Ok(json!({
        "provider_id": PROVIDER_ID, "app_id": APP_ID, "connector_instance_id": instance,
        "label": c.account_label.clone().filter(|l| !l.is_empty()).unwrap_or_else(|| "Proton Mail".into()),
        "capabilities": caps, "execution_mode": "local_connector", "status": "online",
        "metadata": metadata,
    }))
}

pub(super) fn quote_imap(value: &str) -> String {
    format!("\"{}\"", value.replace('\\', "\\\\").replace('"', "\\\""))
}
fn imap_date(value: &str, add_days: i64) -> Option<String> {
    let mut parts = value.split('-');
    let (y, m, d) = (parts.next()?, parts.next()?, parts.next()?);
    if parts.next().is_some() || y.len() != 4 || m.len() != 2 || d.len() != 2 {
        return None;
    }
    let month = time::Month::try_from(m.parse::<u8>().ok()?).ok()?;
    let date = time::Date::from_calendar_date(y.parse().ok()?, month, d.parse().ok()?).ok()?
        + time::Duration::days(add_days);
    let months = [
        "Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec",
    ];
    Some(format!(
        "{:02}-{}-{}",
        date.day(),
        months[date.month() as usize - 1],
        date.year()
    ))
}
pub(super) fn search_command(query: &str, start: &str, end: &str) -> String {
    let mut parts = vec!["SEARCH".to_owned()];
    if !query.is_empty() {
        parts.extend(["CHARSET".into(), "UTF-8".into()]);
    }
    parts.push("ALL".into());
    if let Some(since) = imap_date(start, 0) {
        parts.extend(["SINCE".into(), since]);
    }
    if let Some(before) = imap_date(end, 1) {
        parts.extend(["BEFORE".into(), before]);
    }
    if !query.is_empty() {
        parts.extend(["TEXT".into(), quote_imap(query)]);
    }
    parts.join(" ")
}
pub(super) fn clamp_limit(value: &Value) -> usize {
    let parsed = value
        .as_f64()
        .or_else(|| value.as_str().and_then(|s| s.trim().parse().ok()))
        .unwrap_or(10.0);
    parsed.floor().clamp(1.0, 50.0) as usize
}
pub(super) fn parse_search_ids(response: &str) -> Vec<String> {
    response
        .lines()
        .find_map(|l| l.strip_prefix("* SEARCH"))
        .map(|rest| {
            rest.split_whitespace()
                .filter(|id| id.bytes().all(|b| b.is_ascii_digit()))
                .map(str::to_owned)
                .collect()
        })
        .unwrap_or_default()
}
fn header(response: &str, name: &str) -> Option<String> {
    let prefix = format!("{}:", name.to_lowercase());
    response.lines().find_map(|l| {
        l.to_lowercase()
            .starts_with(&prefix)
            .then(|| l[prefix.len()..].trim().to_owned())
    })
}
fn scrub(value: &str, c: &Credentials) -> String {
    let mut out = value.to_owned();
    for secret in [
        Some(&c.imap_password),
        c.smtp_password.as_ref(),
        Some(&c.imap_username),
        c.smtp_username.as_ref(),
    ]
    .into_iter()
    .flatten()
    .filter(|s| !s.is_empty())
    {
        out = out.replace(
            secret.as_str(),
            if secret.contains('@') {
                "<account>"
            } else {
                "<redacted>"
            },
        );
    }
    out
}
pub(super) fn parse_fetch(response: &str, id: &str, c: &Credentials) -> Value {
    let from = scrub(&header(response, "From").unwrap_or_default(), c);
    let subject: String = scrub(&header(response, "Subject").unwrap_or_default(), c)
        .chars()
        .take(300)
        .collect();
    let snippet: String = scrub(&snippet(response), c).chars().take(1000).collect();
    json!({
        "uid": id, "from": from, "receiver": from, "subject": subject,
        "date": header(response, "Date"), "message_id": header(response, "Message-ID"),
        "snippet": snippet, "content": snippet,
    })
}
fn snippet(response: &str) -> String {
    let skip = |l: &str| {
        let t = l.trim();
        let lower = t.to_lowercase();
        t.starts_with('*')
            || (t.starts_with('A') && t[1..].starts_with(|c: char| c.is_ascii_digit()))
            || ["from:", "subject:", "date:", "message-id:"]
                .iter()
                .any(|p| lower.starts_with(p))
    };
    response
        .lines()
        .filter(|l| !skip(l))
        .collect::<Vec<_>>()
        .join(" ")
        .split_whitespace()
        .collect::<Vec<_>>()
        .join(" ")
}
pub(super) fn recipients(value: &Value) -> Vec<String> {
    static CELL: OnceLock<Regex> = OnceLock::new();
    let ok = re(&CELL, r"^[^\s@<>]+@[^\s@<>]+\.[^\s@<>]+$");
    let items: Vec<&Value> = match value {
        Value::Array(a) => a.iter().collect(),
        Value::String(_) => vec![value],
        _ => vec![],
    };
    items
        .into_iter()
        .filter_map(Value::as_str)
        .map(str::trim)
        .filter(|s| ok.is_match(s))
        .take(20)
        .map(str::to_owned)
        .collect()
}
pub(super) fn smtp_message(
    from: &str,
    to: &[String],
    subject: &str,
    body: &str,
    id: &str,
    date: &str,
) -> String {
    let stuffed = body.replace("\r\n", "\n").replace('\n', "\r\n");
    let stuffed = stuffed
        .split("\r\n")
        .map(|l| {
            if l.starts_with('.') {
                format!(".{l}")
            } else {
                l.to_owned()
            }
        })
        .collect::<Vec<_>>()
        .join("\r\n");
    let headers = [
        format!("Message-ID: {id}"),
        format!("Date: {date}"),
        format!("From: {from}"),
        format!("To: {}", to.join(", ")),
        format!("Subject: {}", subject.replace(['\r', '\n'], " ")),
        "MIME-Version: 1.0".into(),
        "Content-Type: text/plain; charset=utf-8".into(),
    ];
    format!("{}\r\n\r\n{stuffed}", headers.join("\r\n"))
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub(super) enum JobStatus {
    Queued,
    Cancelled,
    Delivered,
}
pub(super) struct Job {
    pub id: String,
    pub status: JobStatus,
    pub deliver_at: Instant,
    pub payload: Option<Value>,
    pub request_id: String,
}
/// npm ProtonDelayedSendQueue: payloads are cleared once delivered/cancelled.
pub(super) struct SendQueue {
    delay: Duration,
    jobs: Vec<Job>,
}
impl SendQueue {
    pub fn new(delay: Duration) -> Self {
        Self {
            delay,
            jobs: Vec::new(),
        }
    }
    pub fn queue(&mut self, request_id: &str, payload: Value, now: Instant) -> String {
        let id = uuid::Uuid::new_v4().to_string();
        self.jobs.push(Job {
            id: id.clone(),
            status: JobStatus::Queued,
            deliver_at: now + self.delay,
            payload: Some(payload),
            request_id: request_id.to_owned(),
        });
        id
    }
    /// Undo before delivery; a delivered job is never recalled.
    pub fn undo(&mut self, id: &str) -> Result<JobStatus, &'static str> {
        let job = self
            .jobs
            .iter_mut()
            .find(|j| j.id == id)
            .ok_or("Delayed send job was not found.")?;
        if job.status == JobStatus::Queued {
            job.status = JobStatus::Cancelled;
            job.payload = None;
        }
        Ok(job.status)
    }
    pub fn status(&self, id: &str) -> Option<JobStatus> {
        self.jobs.iter().find(|j| j.id == id).map(|j| j.status)
    }
    /// Take the payload of every queued job whose delay elapsed.
    pub fn take_due(&mut self, now: Instant) -> Vec<(String, String, Value)> {
        let mut due = Vec::new();
        for job in &mut self.jobs {
            if job.status == JobStatus::Queued && job.deliver_at <= now {
                if let Some(payload) = job.payload.take() {
                    due.push((job.id.clone(), job.request_id.clone(), payload));
                }
                job.status = JobStatus::Delivered;
            }
        }
        due
    }
    pub fn mark_failed(&mut self, id: &str) {
        if let Some(job) = self.jobs.iter_mut().find(|j| j.id == id) {
            job.status = JobStatus::Cancelled;
        }
    }
    pub fn clear(&mut self) {
        self.jobs.clear();
    }
}
