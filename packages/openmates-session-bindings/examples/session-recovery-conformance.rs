//! Actual Rust bridge against the shared test-only synthetic loopback peer.
//! Only this developer conformance executable starts a fixture service; SDK
//! production code never launches a CLI or any child process.
use _native::{BindingError, SessionBridge};
use serde_json::{Value, json};
use sha2::{Digest, Sha256};
use std::{
    io::{BufRead, BufReader, Read, Write},
    net::TcpStream,
    path::{Path, PathBuf},
    process::{Child, Command, Stdio},
    time::Duration,
};
const CAPABILITY: &str = "session.recovery-replay.v1";
type Check<T> = Result<T, &'static str>;
macro_rules! require {
    ($condition:expr,$message:literal) => {
        if !$condition {
            return Err($message);
        }
    };
}
struct Peer {
    process: Child,
    endpoint: String,
}
impl Peer {
    fn start(root: &Path, fixture: &Path, vector: &str) -> Check<Self> {
        let python =
            std::env::var("OPENMATES_SDK_CONFORMANCE_PYTHON").unwrap_or_else(|_| "python3".into());
        let process = Command::new(python)
            .arg(root.join("tests/sdk-conformance/recovery_server.py"))
            .args([
                "--fixture",
                fixture.to_str().ok_or("fixture path")?,
                "--vector",
                vector,
                "--identity",
                "rust",
            ])
            .current_dir(root)
            .stdin(Stdio::null())
            .stdout(Stdio::piped())
            .stderr(Stdio::null())
            .spawn()
            .map_err(|_| "fixture launch")?;
        let mut peer = Self {
            process,
            endpoint: String::new(),
        };
        let mut line = String::new();
        BufReader::new(peer.process.stdout.take().ok_or("fixture stdout")?)
            .read_line(&mut line)
            .map_err(|_| "fixture readiness")?;
        let ready: Value = serde_json::from_str(&line).map_err(|_| "fixture readiness JSON")?;
        peer.endpoint = ready["endpoint"]
            .as_str()
            .ok_or("fixture endpoint")?
            .to_owned();
        let port = peer
            .endpoint
            .strip_prefix("http://127.0.0.1:")
            .ok_or("non-loopback fixture endpoint")?
            .parse::<u16>()
            .map_err(|_| "fixture port")?;
        require!(port > 0, "fixture ephemeral port");
        Ok(peer)
    }
    fn status(&self) -> Check<Value> {
        status(&self.endpoint)
    }
}
impl Drop for Peer {
    fn drop(&mut self) {
        let _ = self.process.kill();
        let _ = self.process.wait();
    }
}
fn status(endpoint: &str) -> Check<Value> {
    let address = endpoint.strip_prefix("http://").ok_or("fixture address")?;
    let mut socket = TcpStream::connect(address).map_err(|_| "fixture status connect")?;
    socket
        .set_read_timeout(Some(Duration::from_secs(3)))
        .map_err(|_| "fixture status timeout")?;
    socket
        .write_all(
            format!("GET /__test/status HTTP/1.1\r\nHost: {address}\r\nConnection: close\r\n\r\n")
                .as_bytes(),
        )
        .map_err(|_| "fixture status request")?;
    let mut response = String::new();
    socket
        .read_to_string(&mut response)
        .map_err(|_| "fixture status response")?;
    let body = response
        .split_once("\r\n\r\n")
        .ok_or("fixture status HTTP")?
        .1;
    serde_json::from_str(body).map_err(|_| "fixture status JSON")
}
fn construct(suite: &Value, endpoint: &str) -> Check<SessionBridge> {
    SessionBridge::new(&json!({"api_url":endpoint,"app_url":suite["protocol"]["app_origin"],"enhanced_privacy":false,"allow_private_operations":true}).to_string()).map_err(|_|"construct native bridge")
}
fn session(suite: &Value, endpoint: &str) -> Value {
    let account = &suite["account"];
    json!({"api_url":endpoint,"session_id":account["session_id"],"cookies":{"auth_refresh_token":account["cookie"]},"ws_token":null,"master_key":account["master_key"],"hashed_email":"synthetic-email-hash","user_email_salt":"synthetic-salt","email_encryption_key":null,"created_at":1,"paired_session_expires_at":null,"active_team_id":null})
}
fn outcome(result: Result<(), BindingError>, expected: Option<&str>) -> Check<()> {
    match (result, expected) {
        (Ok(()), None) => Ok(()),
        (Err(error), Some(code))
            if error.code == code
                && !error
                    .message
                    .contains("synthetic-private-server-diagnostic") =>
        {
            Ok(())
        }
        _ => Err("native recovery outcome mismatch"),
    }
}
async fn run_vector(root: &Path, fixture: &Path, suite: &Value, vector: &Value) -> Check<Value> {
    let peer = Peer::start(
        root,
        fixture,
        vector["id"].as_str().ok_or("fixture vector id")?,
    )?;
    let mut bridge = construct(suite, &peer.endpoint)?;
    bridge
        .import_session(session(suite, &peer.endpoint).to_string())
        .await
        .map_err(|_| "session import")?;
    let mut seen = std::collections::BTreeSet::new();
    let mut completed = None;
    let mut cancellation = None;
    let result = if vector["mode"] == "bad_digest" {
        bridge.list("chats".into()).await.map(|_| ())
    } else {
        if vector["mode"] == "cancel" {
            let client = bridge.clone();
            let endpoint = peer.endpoint.clone();
            cancellation = Some(tokio::spawn(async move {
                for _ in 0..500 {
                    if status(&endpoint)?["claims"] == 1 {
                        client.cancel().map_err(|_| "cancel")?;
                        return Ok(());
                    }
                    tokio::time::sleep(Duration::from_millis(10)).await;
                }
                Err("test lease claim timeout")
            }));
        }
        let id = bridge
            .start_send(
                suite["protocol"]["input"]
                    .as_str()
                    .ok_or("fixture input")?
                    .to_owned(),
                None,
            )
            .await
            .map_err(|_| "native start send")?;
        loop {
            let raw = bridge
                .next_event(id.clone())
                .await
                .map_err(|_| "native stream event")?;
            let event: Value = serde_json::from_str(&raw).map_err(|_| "native event JSON")?;
            if event["type"] == "update" {
                seen.extend(
                    event["update"]
                        .as_object()
                        .ok_or("native update shape")?
                        .keys()
                        .cloned(),
                );
            }
            if event["type"] == "completed" {
                completed = Some(event["chat"].clone());
                break Ok(());
            }
            if event["type"] == "error" {
                let error: Value = event["error"].clone();
                require!(
                    error["code"].as_str() == vector["error"].as_str(),
                    "stream error code mismatch"
                );
                require!(
                    !error["message"]
                        .as_str()
                        .ok_or("error message missing")?
                        .contains("synthetic-private-server-diagnostic"),
                    "private diagnostic leak"
                );
                break Err(BindingError {
                    code: match vector["error"].as_str() {
                        Some("offline") => "offline",
                        Some("crypto") => "crypto",
                        Some("cancelled") => "cancelled",
                        _ => "protocol",
                    },
                    message: "Synthetic native error verified.",
                });
            }
        }
    };
    if let Some(task) = cancellation {
        task.await.map_err(|_| "cancel task")??;
    }
    outcome(result, vector["error"].as_str())?;
    if !vector["error"].is_null() {
        require!(
            completed.is_none() && !seen.contains("Completed"),
            "failed operation reported completion"
        );
    } else {
        let field = if vector["mode"] == "terminal" {
            "canonical_content"
        } else {
            "sealed_content"
        };
        let chat = completed.ok_or("completion missing")?;
        require!(
            chat["messages"]
                .as_array()
                .and_then(|m| m.last())
                .map(|m| &m["content"])
                == Some(&suite["protocol"][field]),
            "completion did not use authoritative content"
        );
        require!(seen.contains("Completed"), "completion update missing");
    }
    if vector["reconnect"] == true {
        let exported: Value = serde_json::from_str(
            &bridge
                .export_session(true)
                .await
                .map_err(|_| "session export")?,
        )
        .map_err(|_| "session export JSON")?;
        bridge.close().await.map_err(|_| "first client close")?;
        bridge = construct(suite, &peer.endpoint)?;
        bridge
            .import_session(exported["session"].to_string())
            .await
            .map_err(|_| "fresh session import")?;
        let rows: Value = serde_json::from_str(
            &bridge
                .list("chats".into())
                .await
                .map_err(|_| "reconnect discovery")?,
        )
        .map_err(|_| "discovery JSON")?;
        require!(
            rows.as_array().is_some_and(|r| r.len() == 1),
            "reconnect rows mismatch"
        );
        let chat: Value = serde_json::from_str(
            &bridge
                .open_chat(
                    rows[0]["id"]
                        .as_str()
                        .ok_or("reconnect chat id")?
                        .to_owned(),
                )
                .await
                .map_err(|_| "canonical open")?,
        )
        .map_err(|_| "canonical chat JSON")?;
        require!(
            chat["messages"]
                .as_array()
                .and_then(|m| m.last())
                .map(|m| &m["content"])
                == Some(&suite["protocol"]["sealed_content"]),
            "reconnect content mismatch"
        );
    }
    bridge.close().await.map_err(|_| "client close")?;
    let mut report = peer.status()?;
    for _ in 0..100 {
        if report["checks"]
            .as_array()
            .is_some_and(|c| c.iter().any(|v| v == "socket-closed"))
        {
            break;
        }
        tokio::time::sleep(Duration::from_millis(10)).await;
        report = peer.status()?;
    }
    require!(report["failure"].is_null(), "fixture protocol assertion");
    require!(
        report["persists"] == vector["expected_persists"],
        "unexpected persist count"
    );
    let admitted = u64::from(vector["mode"] != "bad_digest");
    require!(
        report["admissions"] == admitted && report["claims"] == admitted,
        "unexpected admission/claim count"
    );
    require!(
        report["connections"] == if vector["reconnect"] == true { 2 } else { 1 },
        "unexpected socket count"
    );
    for check in vector["required_checks"]
        .as_array()
        .ok_or("required checks missing")?
    {
        require!(
            report["checks"]
                .as_array()
                .is_some_and(|c| c.contains(check)),
            "required protocol check missing"
        );
    }
    Ok(json!({"id":vector["id"],"status":"passed"}))
}
async fn run() -> Check<Value> {
    let args: Vec<String> = std::env::args().collect();
    let option = |name| {
        args.iter()
            .position(|arg| arg == name)
            .and_then(|i| args.get(i + 1))
            .ok_or("argument missing")
    };
    require!(
        option("--capability")? == CAPABILITY,
        "unsupported capability"
    );
    let root = PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .parent()
        .and_then(Path::parent)
        .ok_or("repository path")?
        .to_owned();
    let fixture = std::fs::canonicalize(option("--fixture")?).map_err(|_| "fixture path")?;
    let raw = std::fs::read(&fixture).map_err(|_| "fixture read")?;
    let fixture_json: Value = serde_json::from_slice(&raw).map_err(|_| "fixture JSON")?;
    let suite = &fixture_json["capabilities"][CAPABILITY];
    let vectors = suite["vectors"].as_array().ok_or("fixture vectors")?;
    require!(!vectors.is_empty(), "empty suite");
    let mut results = vec![];
    for vector in vectors {
        results.push(run_vector(&root, &fixture, suite, vector).await?);
    }
    Ok(
        json!({"capability":CAPABILITY,"language":"rust","status":"passed","fixtureSha256":format!("{:x}",Sha256::digest(&raw)),"results":results}),
    )
}
#[tokio::main]
async fn main() {
    match tokio::time::timeout(Duration::from_secs(180), run()).await {
        Ok(Ok(result)) => println!("{result}"),
        _ => {
            eprintln!("Rust recovery protocol conformance failed");
            std::process::exit(1);
        }
    }
}
