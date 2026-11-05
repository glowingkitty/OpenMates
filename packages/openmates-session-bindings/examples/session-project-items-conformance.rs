//! Actual Rust bridge against the shared test-only synthetic loopback peer.
//! Only this developer conformance executable starts a fixture service; SDK
//! production code never launches a CLI or any child process.
// contract-test: supporting surface=cli assertions=cli.surface.semantic-parity
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
const CAPABILITY: &str = "session.project-items.v1";
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
            .arg(root.join("tests/sdk-conformance/session_project_items_server.py"))
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

fn parse<T: serde::de::DeserializeOwned>(value: &Value) -> Check<T> {
    serde_json::from_value(value.clone()).map_err(|_| "typed fixture input")
}
fn decoded(result: Result<String, BindingError>) -> Check<Value> {
    serde_json::from_str(&result.map_err(|error| {
        eprintln!("Native error code: {}", error.code);
        "native work operation"
    })?)
    .map_err(|_| "native work JSON")
}
fn error_code<T>(result: Result<T, BindingError>, expected: &str) -> Check<()> {
    match result {
        Err(error)
            if error.code == expected
                && !error
                    .message
                    .contains("synthetic-private-server-diagnostic") =>
        {
            Ok(())
        }
        _ => Err("native work error mismatch"),
    }
}
async fn run_vector(root: &Path, fixture: &Path, suite: &Value, vector: &Value) -> Check<Value> {
    use openmates_sdk::work::{ProjectFilters, ProjectItemType};
    let peer = Peer::start(root, fixture, vector["id"].as_str().ok_or("vector id")?)?;
    let bridge = SessionBridge::new(&json!({"api_url":peer.endpoint,"app_url":peer.endpoint,"enhanced_privacy":false,"allow_private_operations":false}).to_string()).map_err(|_|"construct")?;
    let account = &suite["account"];
    bridge.import_session(json!({"api_url":peer.endpoint,"session_id":account["session_id"],"cookies":{"auth_refresh_token":account["cookie"]},"ws_token":null,"master_key":account["master_key"],"hashed_email":"synthetic-email-hash","user_email_salt":"synthetic-salt","email_encryption_key":null,"created_at":1,"paired_session_expires_at":null,"active_team_id":null}).to_string()).await.map_err(|_|"import")?;
    bridge
        .set_team(Some(
            suite["team"]["team_id"].as_str().ok_or("team id")?.into(),
        ))
        .await
        .map_err(|_| "ambient team")?;
    let before = decoded(bridge.export_session(true).await)?;
    let f = if vector["team"] == true {
        json!({"team_id":suite["team"]["team_id"]})
    } else {
        json!({"personal":true})
    };
    let mode = vector["mode"].as_str().ok_or("mode")?;
    let id = suite["project_id"].as_str().ok_or("project id")?.to_owned();
    let target = suite["target_id"].as_str().ok_or("target id")?.to_owned();
    let kind: ProjectItemType = parse(vector.get("item_type").unwrap_or(&json!("chat")))?;
    match mode {
        "projection" => require!(
            decoded(bridge.projects_items(id, parse(&f)?).await)? == suite["expected"],
            "decrypted scoped projection"
        ),
        "unlink" | "noop" => {
            let result = decoded(
                bridge
                    .projects_unlink_item(id.clone(), kind, target.clone(), true, parse(&f)?)
                    .await,
            )?;
            require!(
                result
                    == json!({"project_id":id,"target_id":target,"deleted":mode!="noop","deleted_count":if mode=="noop"{0}else{1}}),
                "exact unlink receipt"
            );
        }
        "confirmation" => {
            error_code(
                bridge
                    .projects_unlink_item(id.clone(), kind, target, false, parse(&f)?)
                    .await,
                "invalid_argument",
            )?;
            error_code(
                bridge
                    .projects_unlink_item(id, kind, String::new(), true, parse(&f)?)
                    .await,
                "invalid_argument",
            )?;
            require!(
                serde_json::from_value::<ProjectItemType>(json!("upload")).is_err(),
                "unsupported unlink kind"
            );
        }
        "scope" => {
            error_code(
                bridge
                    .projects_items(id.clone(), ProjectFilters::default())
                    .await,
                "invalid_argument",
            )?;
            error_code(
                bridge
                    .projects_unlink_item(
                        id,
                        kind,
                        target,
                        true,
                        parse(&json!({"personal":true,"team_id":suite["team"]["team_id"]}))?,
                    )
                    .await,
                "invalid_argument",
            )?;
            require!(
                serde_json::from_value::<ProjectFilters>(
                    json!({"personal":true,"unexpected":true})
                )
                .is_err(),
                "strict filters"
            );
        }
        "tamper" => error_code(bridge.projects_items(id, parse(&f)?).await, "forbidden")?,
        "permission" | "receipt" => error_code(
            bridge
                .projects_unlink_item(id, kind, target, true, parse(&f)?)
                .await,
            if mode == "permission" {
                "forbidden"
            } else {
                "protocol"
            },
        )?,
        "cancel" => {
            let client = bridge.clone();
            let first_id = id.clone();
            let first = tokio::spawn(async move {
                client
                    .projects_items(
                        first_id,
                        ProjectFilters {
                            personal: true,
                            ..Default::default()
                        },
                    )
                    .await
            });
            let mut blocked = false;
            for _ in 0..500 {
                if peer.status()?["blocked"] == true {
                    blocked = true;
                    break;
                }
                tokio::time::sleep(Duration::from_millis(10)).await;
            }
            require!(blocked, "held list");
            let client = bridge.clone();
            let queued_id = id.clone();
            let queued = tokio::spawn(async move {
                client
                    .projects_unlink_item(
                        queued_id,
                        kind,
                        target,
                        true,
                        ProjectFilters {
                            personal: true,
                            ..Default::default()
                        },
                    )
                    .await
            });
            tokio::time::sleep(Duration::from_millis(30)).await;
            bridge.cancel().map_err(|_| "cancel")?;
            let address = peer.endpoint.strip_prefix("http://").ok_or("address")?;
            let mut socket = TcpStream::connect(address).map_err(|_| "release")?;
            socket.write_all(format!("GET /__test/release HTTP/1.1\r\nHost: {address}\r\nConnection: close\r\n\r\n").as_bytes()).map_err(|_|"release")?;
            let mut response = String::new();
            socket
                .read_to_string(&mut response)
                .map_err(|_| "release")?;
            error_code(first.await.map_err(|_| "first join")?, "cancelled")?;
            error_code(queued.await.map_err(|_| "queued join")?, "cancelled")?;
            require!(
                decoded(bridge.projects_items(id, parse(&f)?).await)? == suite["expected"],
                "fresh operation after cancellation"
            );
        }
        _ => return Err("unknown project item vector"),
    }
    let report = peer.status()?;
    require!(report["failure"].is_null(), "peer assertions");
    let targets: Vec<Value> = suite["expected"]["items"]
        .as_array()
        .ok_or("items")?
        .iter()
        .map(|item| item["target_id"].clone())
        .collect();
    require!(
        report["targets"] == json!(targets),
        "underlying targets retained"
    );
    require!(
        report["writes"]
            == if matches!(mode, "unlink" | "noop" | "receipt") {
                1
            } else {
                0
            },
        "link-only write count"
    );
    require!(
        report["deleted_links"] == if mode == "unlink" { 1 } else { 0 },
        "link delete count"
    );
    if matches!(mode, "confirmation" | "scope") {
        require!(report["requests"] == 0, "refusal before transport");
    } else {
        let after = decoded(bridge.export_session(true).await)?;
        require!(
            after["revision"].as_u64() > before["revision"].as_u64(),
            "credential revision advanced"
        );
        require!(
            after["session"]["cookies"]["auth_refresh_token"] == report["cookie"],
            "rotated credentials retained on success or error"
        );
        let expected = if vector["team"] == true { 2 } else { 1 }
            + if matches!(mode, "unlink" | "noop" | "receipt" | "cancel") {
                1
            } else {
                0
            };
        require!(
            report["requests"] == expected,
            "no retry or underlying deletion"
        );
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
        results.push(
            run_vector(&root, &fixture, suite, vector)
                .await
                .inspect_err(|reason| {
                    eprintln!("Project-item vector {} failed: {reason}", vector["id"]);
                })?,
        );
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
            eprintln!("Rust work protocol conformance failed");
            std::process::exit(1);
        }
    }
}
