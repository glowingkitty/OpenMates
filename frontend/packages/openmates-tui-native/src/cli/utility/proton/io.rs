//! Process and loopback-TCP adapters for the Proton Bridge connector. These
//! stay in the CLI adapter layer: they spawn the user's local Bridge, speak
//! IMAP/SMTP to localhost only, and never log credentials.
use super::logic::{self, Credentials};
use serde_json::{Value, json};
use std::time::Duration;
use tokio::io::{AsyncBufReadExt, AsyncWriteExt, BufReader};
use tokio::net::TcpStream;
use tokio::process::{Child, Command};

const IMAP_TIMEOUT: Duration = Duration::from_secs(15);
const SMTP_TIMEOUT: Duration = Duration::from_secs(15);
const CONNECT_TIMEOUT: Duration = Duration::from_secs(5);

pub(super) struct Bridge(Option<Child>);
impl Bridge {
    pub fn spawn(command: &str, args: &[&str]) -> Result<Self, String> {
        Command::new(command)
            .args(args)
            .stdin(std::process::Stdio::null())
            .stdout(std::process::Stdio::null())
            .stderr(std::process::Stdio::null())
            .kill_on_drop(true)
            .spawn()
            .map(|c| Self(Some(c)))
            .map_err(|e| logic::redact_secrets(&format!("Could not start Proton Bridge: {e}")))
    }
    pub async fn stop(mut self) {
        if let Some(mut child) = self.0.take() {
            let _ = child.start_kill();
            let _ = tokio::time::timeout(Duration::from_secs(2), child.wait()).await;
        }
    }
}

/// `info` over the Bridge CLI; the caller falls back to a hidden prompt on error.
pub(super) async fn capture_info(command: &str, args: &[&str]) -> Result<String, String> {
    let mut child = Command::new(command)
        .args(args)
        .stdin(std::process::Stdio::piped())
        .stdout(std::process::Stdio::piped())
        .stderr(std::process::Stdio::piped())
        .kill_on_drop(true)
        .spawn()
        .map_err(|e| logic::redact_secrets(&e.to_string()))?;
    if let Some(mut stdin) = child.stdin.take() {
        let _ = stdin.write_all(b"info\nquit\n").await;
    }
    let output = tokio::time::timeout(Duration::from_secs(10), child.wait_with_output())
        .await
        .map_err(|_| "Timed out reading Proton Bridge info.".to_owned())?
        .map_err(|e| logic::redact_secrets(&e.to_string()))?;
    let text = String::from_utf8_lossy(&output.stdout).into_owned();
    if text.trim().is_empty() {
        let err = String::from_utf8_lossy(&output.stderr);
        return Err(logic::redact_secrets(if err.trim().is_empty() {
            "Proton Bridge info produced no output."
        } else {
            err.trim()
        }));
    }
    Ok(text)
}

pub(super) async fn validate_imap(c: &Credentials) -> Result<(), String> {
    logic::validate(c)?;
    tokio::time::timeout(
        CONNECT_TIMEOUT,
        TcpStream::connect((c.imap_host.as_str(), c.imap_port)),
    )
    .await
    .map_err(|_| "Timed out connecting to local Proton Bridge IMAP.".to_owned())?
    .map(drop)
    .map_err(|e| {
        format!(
            "Could not connect to local Proton Bridge IMAP: {}",
            logic::redact_secrets(&e.to_string())
        )
    })
}

struct Text {
    reader: BufReader<TcpStream>,
    timeout: Duration,
    tag: u32,
}
impl Text {
    async fn open(host: &str, port: u16, timeout: Duration) -> Result<Self, String> {
        let stream = tokio::time::timeout(timeout, TcpStream::connect((host, port)))
            .await
            .map_err(|_| format!("Timed out connecting to {host}:{port}."))?
            .map_err(|e| logic::redact_secrets(&e.to_string()))?;
        Ok(Self {
            reader: BufReader::new(stream),
            timeout,
            tag: 0,
        })
    }
    /// Read lines until `done(accumulated)`.
    async fn read_until(&mut self, done: impl Fn(&str) -> bool) -> Result<String, String> {
        let mut text = String::new();
        let deadline = tokio::time::Instant::now() + self.timeout;
        while !done(&text) {
            let mut line = String::new();
            let read = tokio::time::timeout_at(deadline, self.reader.read_line(&mut line))
                .await
                .map_err(|_| "Timed out waiting for local mail server response.".to_owned())?
                .map_err(|e| logic::redact_secrets(&e.to_string()))?;
            if read == 0 {
                return Err("Local mail server closed the connection.".to_owned());
            }
            text.push_str(&line);
        }
        Ok(text)
    }
    async fn send(&mut self, line: &str) -> Result<(), String> {
        let stream = self.reader.get_mut();
        stream
            .write_all(format!("{line}\r\n").as_bytes())
            .await
            .map_err(|e| logic::redact_secrets(&e.to_string()))?;
        stream
            .flush()
            .await
            .map_err(|e| logic::redact_secrets(&e.to_string()))
    }
    async fn imap(&mut self, command: &str) -> Result<String, String> {
        self.tag += 1;
        let tag = format!("A{:04}", self.tag);
        self.send(&format!("{tag} {command}")).await?;
        let prefix = format!("{tag} ");
        let response = self
            .read_until(|t| t.lines().any(|l| l.starts_with(&prefix)))
            .await?;
        let status = response
            .lines()
            .find(|l| l.starts_with(&prefix))
            .unwrap_or("");
        let bad =
            status[prefix.len()..].starts_with("NO") || status[prefix.len()..].starts_with("BAD");
        if bad {
            let tail: Vec<&str> = response.lines().rev().take(2).collect();
            return Err(format!(
                "Local mail command failed: {}",
                logic::redact_secrets(&tail.into_iter().rev().collect::<Vec<_>>().join(" "))
            ));
        }
        Ok(response)
    }
    /// Send a raw line and require a reply whose final line starts with `code`.
    async fn expect(&mut self, line: Option<&str>, code: &str) -> Result<String, String> {
        if let Some(line) = line {
            self.send(line).await?;
        }
        let space = format!("{code} ");
        let dash = format!("{code}-");
        let response = self
            .read_until(|t| {
                t.lines().last().is_some_and(|l| l.starts_with(&space)) && t.ends_with('\n')
            })
            .await?;
        if !response
            .lines()
            .any(|l| l.starts_with(&space) || l.starts_with(&dash))
        {
            return Err(format!(
                "Local mail command failed: {}",
                logic::redact_secrets(response.lines().last().unwrap_or(""))
            ));
        }
        Ok(response)
    }
}

pub(super) async fn search_imap(c: &Credentials, arguments: &Value) -> Result<Vec<Value>, String> {
    let text = |key: &str| arguments[key].as_str().map(str::trim).unwrap_or("");
    let mailbox = Some(text("mailbox"))
        .filter(|m| !m.is_empty())
        .unwrap_or("INBOX");
    let limit = logic::clamp_limit(&arguments["limit"]);
    let mut imap = Text::open(&c.imap_host, c.imap_port, IMAP_TIMEOUT).await?;
    let result = async {
        imap.read_until(|t| t.lines().any(|l| l.starts_with("* OK"))).await?;
        imap.imap(&format!("LOGIN {} {}", logic::quote_imap(&c.imap_username), logic::quote_imap(&c.imap_password))).await?;
        imap.imap(&format!("SELECT {}", logic::quote_imap(mailbox))).await?;
        let found = imap.imap(&logic::search_command(text("query"), text("start_date"), text("end_date"))).await?;
        let ids = logic::parse_search_ids(&found);
        let mut messages = Vec::new();
        for id in ids.iter().rev().take(limit) {
            let fetched = imap
                .imap(&format!("FETCH {id} (BODY.PEEK[HEADER.FIELDS (FROM SUBJECT DATE MESSAGE-ID)] BODY.PEEK[TEXT]<0.500>)"))
                .await?;
            messages.push(logic::parse_fetch(&fetched, id, c));
        }
        Ok::<_, String>(messages)
    }
    .await;
    let _ = imap.imap("LOGOUT").await;
    result
}

pub(super) async fn send_smtp(c: &Credentials, payload: &Value) -> Result<Value, String> {
    let (Some(host), Some(port)) = (c.smtp_host.as_deref(), c.smtp_port) else {
        return Err("Bridge SMTP settings are required for Proton write mode.".to_owned());
    };
    let to = logic::recipients(&payload["to"]);
    if to.is_empty() {
        return Err("SMTP send requires at least one recipient.".to_owned());
    }
    let subject: String = payload["subject"]
        .as_str()
        .unwrap_or("")
        .chars()
        .take(300)
        .collect();
    let body = payload["body_text"]
        .as_str()
        .or(payload["body"].as_str())
        .unwrap_or("");
    let user = c.smtp_username.as_deref().unwrap_or(&c.imap_username);
    let pass = c.smtp_password.as_deref().unwrap_or(&c.imap_password);
    let message_id = format!("<om-{}@local.openmates>", uuid::Uuid::new_v4());
    let date = time::OffsetDateTime::now_utc()
        .format(&time::format_description::well_known::Rfc2822)
        .unwrap_or_default();
    let mut smtp = Text::open(host, port, SMTP_TIMEOUT).await?;
    smtp.expect(None, "220").await?;
    smtp.expect(Some("EHLO openmates.local"), "250").await?;
    use base64::Engine;
    let auth = base64::engine::general_purpose::STANDARD.encode(format!("\0{user}\0{pass}"));
    smtp.expect(Some(&format!("AUTH PLAIN {auth}")), "235")
        .await
        .map_err(|_| "Local SMTP authentication failed.".to_owned())?;
    smtp.expect(Some(&format!("MAIL FROM:<{user}>")), "250")
        .await?;
    for recipient in &to {
        smtp.expect(Some(&format!("RCPT TO:<{recipient}>")), "250")
            .await?;
    }
    smtp.expect(Some("DATA"), "354").await?;
    let message = logic::smtp_message(user, &to, &subject, body, &message_id, &date);
    smtp.expect(Some(&format!("{message}\r\n.")), "250").await?;
    let _ = smtp.expect(Some("QUIT"), "221").await;
    Ok(json!({"provider": logic::PROVIDER_ID, "message_id": message_id, "delivered": true}))
}
