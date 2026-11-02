//! Actual Rust bridge against the shared test-only synthetic loopback peer.
//! Only this developer conformance executable starts a fixture service; SDK
//! production code never launches a CLI or any child process.
use _native::SessionBridge;
use serde_json::{Value, json};
use sha2::{Digest, Sha256};
use std::{
    io::{BufRead, BufReader, Read, Write},
    net::TcpStream,
    path::{Path, PathBuf},
    process::{Child, Command, Stdio},
    time::Duration,
};
const CAPABILITY: &str = "session.anonymous-stream.v1";
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
            .arg(root.join("tests/sdk-conformance/session_anonymous_server.py"))
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

struct Terminal {
    event: Value,
    seen: std::collections::BTreeSet<String>,
}
async fn collect(bridge: &SessionBridge, id: String) -> Check<Terminal> {
    let mut seen = std::collections::BTreeSet::new();
    for _ in 0..32 {
        let raw = bridge
            .next_event(id.clone())
            .await
            .map_err(|_| "stream event")?;
        let event: Value = serde_json::from_str(&raw).map_err(|_| "event JSON")?;
        if event["type"] == "update" {
            seen.extend(
                event["update"]
                    .as_object()
                    .ok_or("update shape")?
                    .keys()
                    .cloned(),
            );
        } else {
            return Ok(Terminal { event, seen });
        }
    }
    Err("bounded event count")
}
async fn attempt(
    bridge: &SessionBridge,
    suite: &Value,
    id: &str,
    options: openmates_sdk::SendOptions,
) -> Check<Terminal> {
    match bridge
        .start_anonymous(
            id.into(),
            suite["text"].as_str().ok_or("input")?.into(),
            options,
        )
        .await
    {
        Ok(id) => collect(bridge, id).await,
        Err(error) => Ok(Terminal {
            event: json!({"type":"error","error":{"code":error.code,"message":error.message}}),
            seen: Default::default(),
        }),
    }
}
fn refused(value: &Terminal, expected: &str) -> Check<()> {
    require!(
        value.event["type"] == "error" && value.event["error"]["code"] == expected,
        "anonymous rejection mismatch"
    );
    require!(
        !value
            .event
            .to_string()
            .contains("synthetic-private-server-diagnostic"),
        "private diagnostic redaction"
    );
    Ok(())
}
fn outcome(terminal: &Terminal, suite: &Value) -> Check<()> {
    let value = &terminal.event["outcome"];
    let chat = &terminal.event["chat"];
    require!(
        terminal.event["type"] == "completed"
            && value["status"] == "completed"
            && value["assistant"] == suite["text"],
        "completed anonymous result"
    );
    require!(
        value["chatId"]
            .as_str()
            .is_some_and(|id| id.starts_with("anonymous-")),
        "ephemeral chat identifier"
    );
    require!(
        value["followUpSuggestions"] == json!(["Synthetic follow-up"]),
        "observed follow-up suggestions"
    );
    for field in [
        "pendingTaskUpdateJobs",
        "taskEvents",
        "subChatEvents",
        "appSettingsMemoryRequests",
    ] {
        require!(value[field] == json!([]), "no durable private work");
    }
    require!(
        chat["id"] == value["chatId"] && chat["messages"].as_array().is_some_and(|v| v.len() == 2),
        "ephemeral Chat result"
    );
    for message in chat["messages"].as_array().ok_or("messages")? {
        require!(
            message["content"] == suite["text"],
            "local privacy restoration"
        );
    }
    require!(
        value["userMessageId"] == chat["messages"][0]["id"]
            && value["userMessageId"]
                .as_str()
                .is_some_and(|id| id.starts_with("anonymous-message-")),
        "caller-owned volatile user identity"
    );
    require!(
        !terminal.seen.contains("Admitted") && !terminal.seen.contains("Consent"),
        "no saved receipt or private context"
    );
    Ok(())
}
fn release(endpoint: &str) -> Check<()> {
    let address = endpoint.strip_prefix("http://").ok_or("loopback address")?;
    let mut socket = TcpStream::connect(address).map_err(|_| "release connect")?;
    socket
        .set_read_timeout(Some(Duration::from_secs(3)))
        .map_err(|_| "release timeout")?;
    socket
        .write_all(
            format!("GET /__test/release HTTP/1.1\r\nHost: {address}\r\nConnection: close\r\n\r\n")
                .as_bytes(),
        )
        .map_err(|_| "release request")?;
    let mut response = String::new();
    socket
        .read_to_string(&mut response)
        .map_err(|_| "release response")?;
    Ok(())
}
async fn run_vector(root: &Path, fixture: &Path, suite: &Value, vector: &Value) -> Check<Value> {
    use openmates_sdk::SendOptions;
    let peer = Peer::start(root, fixture, vector["id"].as_str().ok_or("vector id")?)?;
    let bridge=SessionBridge::new(&json!({"api_url":peer.endpoint,"app_url":"https://app.example.invalid","enhanced_privacy":false,"allow_private_operations":vector["allow_private"]}).to_string()).map_err(|_|"construct")?;
    let mut before = None;
    if vector["signed"] == true {
        let a = &suite["account"];
        bridge.import_session(json!({"api_url":peer.endpoint,"session_id":a["session_id"],"cookies":{"auth_refresh_token":a["cookie"]},"ws_token":null,"master_key":a["master_key"],"hashed_email":"synthetic-email","user_email_salt":"synthetic-salt","email_encryption_key":null,"created_at":1,"paired_session_expires_at":null,"active_team_id":null}).to_string()).await.map_err(|_|"import")?;
        before = Some(
            bridge
                .export_session(true)
                .await
                .map_err(|_| "before snapshot")?,
        );
    }
    let mode = vector["mode"].as_str().ok_or("mode")?;
    let anonymous = suite["anonymous_id"].as_str().ok_or("anonymous id")?;
    match mode {
        "sse" => {
            for _ in 0..vector["repetitions"].as_u64().ok_or("repetitions")? {
                let terminal = attempt(&bridge, suite, anonymous, SendOptions::default()).await?;
                outcome(&terminal, suite)?;
                for kind in ["Started", "Submitted", "Content", "Completed"] {
                    require!(terminal.seen.contains(kind), "stream observations");
                }
            }
        }
        "cancel" => {
            let id = bridge
                .start_anonymous(
                    anonymous.into(),
                    suite["text"].as_str().ok_or("input")?.into(),
                    SendOptions::default(),
                )
                .await
                .map_err(|_| "start")?;
            let mut content = false;
            for _ in 0..16 {
                let event: Value = serde_json::from_str(
                    &bridge
                        .next_event(id.clone())
                        .await
                        .map_err(|_| "cancel event")?,
                )
                .map_err(|_| "cancel JSON")?;
                if event["update"].get("Content").is_some() {
                    content = true;
                    break;
                }
                require!(event["type"] == "update", "unexpected early terminal");
            }
            require!(content, "partial anonymous content");
            bridge
                .cancel_stream(id.clone())
                .map_err(|_| "scoped cancellation")?;
            refused(&collect(&bridge, id).await?, "cancelled")?;
            release(&peer.endpoint)?;
            outcome(
                &attempt(&bridge, suite, anonymous, SendOptions::default()).await?,
                suite,
            )?;
        }
        "preflight" => {
            for id in [String::new(), "invalid id".into(), "x".repeat(129)] {
                refused(
                    &attempt(&bridge, suite, &id, SendOptions::default()).await?,
                    "invalid_argument",
                )?;
            }
            require!(
                serde_json::from_value::<SendOptions>(json!({"model":"forbidden"})).is_err(),
                "typed routing refusal"
            );
            for options in [
                SendOptions {
                    project_id: Some("11111111-1111-4111-8111-111111111111".into()),
                    ..Default::default()
                },
                SendOptions {
                    response_timeout_ms: Some(0),
                    ..Default::default()
                },
            ] {
                refused(
                    &attempt(&bridge, suite, anonymous, options).await?,
                    "invalid_argument",
                )?;
            }
        }
        _ => {
            let code = match mode {
                "budget" => "signup_required",
                "redirect" | "policy" => "forbidden",
                "malformed" | "private" => "protocol",
                _ => return Err("unknown vector"),
            };
            refused(
                &attempt(&bridge, suite, anonymous, SendOptions::default()).await?,
                code,
            )?;
        }
    }
    if let Some(before) = before {
        require!(
            bridge
                .export_session(true)
                .await
                .map_err(|_| "after snapshot")?
                == before,
            "anonymous session unchanged"
        );
    } else {
        require!(
            bridge
                .export_session(true)
                .await
                .err()
                .is_some_and(|e| e.code == "authentication"),
            "anonymous never creates credentials"
        );
    }
    let report = peer.status()?;
    require!(
        report["failure"].is_null() && report["redirects"] == 0,
        "peer checks and no redirect"
    );
    if matches!(mode, "preflight" | "policy") {
        require!(
            report["status_gets"] == 0 && report["posts"] == 0,
            "predispatch refusal"
        );
    } else {
        let expected = if mode == "cancel" {
            2
        } else {
            vector["repetitions"].as_u64().ok_or("repeat")?
        };
        require!(
            report["status_gets"] == expected,
            "bounded public status requests"
        );
        require!(
            report["posts"]
                == if matches!(mode, "budget" | "redirect") {
                    0
                } else {
                    expected
                },
            "bounded public inference posts"
        );
        require!(
            report["checks"]
                .as_array()
                .is_some_and(|v| v.contains(&json!("public-headers-without-account-identity"))),
            "account headers absent"
        );
        if report["posts"].as_u64().unwrap_or(0) > 0 {
            for check in [
                "local-pii-redaction",
                "empty-history-fresh-ephemeral-identities",
                "no-routing-or-durable-capabilities",
            ] {
                require!(
                    report["checks"]
                        .as_array()
                        .is_some_and(|v| v.contains(&json!(check))),
                    "public payload check"
                );
            }
            require!(
                report["chat_ids"]
                    .as_array()
                    .is_some_and(|v| v.len() as u64 == expected),
                "fresh ephemeral chat ids"
            );
        }
    }
    bridge.close().await.map_err(|_| "close")?;
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
            eprintln!("Rust anonymous stream conformance failed");
            std::process::exit(1);
        }
    }
}
