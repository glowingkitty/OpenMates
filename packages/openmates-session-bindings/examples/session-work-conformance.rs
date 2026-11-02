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
#[path = "support/saved_stream.rs"]
mod saved_stream;
const CAPABILITY: &str = "session.work-crud.v1";
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
            .arg(root.join("tests/sdk-conformance/session_work_server.py"))
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
        eprintln!("work_native_error code={}", error.code);
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
    if vector["mode"].as_str().is_some_and(|mode| mode.starts_with("saved_")) {
        return saved_stream::run(root,fixture,suite,vector).await;
    }
    use openmates_sdk::work::{
        ProjectCreate, ProjectFilters, ProjectPatch, TaskCreate, TaskFilters, TaskPatch,
    };
    let peer = Peer::start(root, fixture, vector["id"].as_str().ok_or("vector id")?)?;
    let bridge = SessionBridge::new(&json!({"api_url":peer.endpoint,"app_url":null,"enhanced_privacy":false,"allow_private_operations":false}).to_string()).map_err(|_|"construct")?;
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
    match mode {
        "crud" => {
            let tasks = vector["family"] == "tasks";
            let input = &suite["input"][if tasks { "tasks" } else { "projects" }];
            let created = decoded(if tasks {
                bridge.tasks_create(parse(input)?, parse(&f)?).await
            } else {
                bridge.projects_create(parse(input)?, parse(&f)?).await
            })?;
            let name = if tasks { "title" } else { "name" };
            let id_field = if tasks { "task_id" } else { "project_id" };
            require!(created[name] == input[name], "created private name");
            let id = created[id_field]
                .as_str()
                .ok_or("created object id")?
                .to_owned();
            let rows = decoded(if tasks {
                bridge.tasks_list(parse(&f)?).await
            } else {
                bridge.projects_list(parse(&f)?).await
            })?;
            require!(
                rows.as_array().is_some_and(|r| r.len() == 1) && rows[0][id_field] == id,
                "list created object"
            );
            let shown = decoded(if tasks {
                bridge.tasks_show(id.clone(), parse(&f)?).await
            } else {
                bridge.projects_show(id.clone(), parse(&f)?).await
            })?;
            require!(shown[name] == created[name], "show decrypt");
            let patch = if tasks {
                json!({"title":"Synthetic updated private text","due_at":null,"status":"in_progress"})
            } else {
                json!({"name":"Synthetic updated private text","archived":true})
            };
            let updated = decoded(if tasks {
                bridge
                    .tasks_update(id.clone(), parse(&patch)?, parse(&f)?)
                    .await
            } else {
                bridge
                    .projects_update(id.clone(), parse(&patch)?, parse(&f)?)
                    .await
            })?;
            require!(
                updated[name] == "Synthetic updated private text",
                "updated private name"
            );
            if tasks {
                require!(
                    updated["due_at"].is_null() && updated["status"] == "in_progress",
                    "nullable task patch"
                );
            } else {
                require!(updated["archived"] == true, "archive patch");
            }
            let deleted = decoded(if tasks {
                bridge.tasks_delete(id, true, parse(&f)?).await
            } else {
                bridge.projects_delete(id, true, parse(&f)?).await
            })?;
            require!(deleted["deleted"] == true, "delete result");
            let rows = decoded(if tasks {
                bridge.tasks_list(parse(&f)?).await
            } else {
                bridge.projects_list(parse(&f)?).await
            })?;
            require!(rows.as_array().is_some_and(Vec::is_empty), "deleted list");
        }
        "unknown" => {
            require!(
                serde_json::from_value::<TaskCreate>(
                    json!({"title":"synthetic","model":"forbidden"})
                )
                .is_err(),
                "strict task DTO"
            );
            require!(
                serde_json::from_value::<ProjectCreate>(
                    json!({"name":"synthetic","provider":"forbidden"})
                )
                .is_err(),
                "strict project DTO"
            );
            require!(
                serde_json::from_value::<TaskPatch>(json!({"provider":"forbidden"})).is_err(),
                "strict task patch"
            );
            require!(
                serde_json::from_value::<ProjectPatch>(json!({"model":"forbidden"})).is_err(),
                "strict project patch"
            );
        }
        "confirmation" => {
            error_code(
                bridge
                    .tasks_delete(
                        "11111111-1111-4111-8111-111111111111".into(),
                        false,
                        parse(&f)?,
                    )
                    .await,
                "invalid_argument",
            )?;
            error_code(
                bridge
                    .projects_delete(
                        "11111111-1111-4111-8111-111111111111".into(),
                        false,
                        parse(&f)?,
                    )
                    .await,
                "invalid_argument",
            )?;
        }
        "scope" => {
            error_code(
                bridge.tasks_list(TaskFilters::default()).await,
                "invalid_argument",
            )?;
            error_code(
                bridge
                    .projects_list(ProjectFilters {
                        personal: true,
                        team_id: Some(suite["team"]["team_id"].as_str().ok_or("team")?.into()),
                        ..Default::default()
                    })
                    .await,
                "invalid_argument",
            )?;
        }
        "policy" => {
            error_code(
                bridge
                    .tasks_create(
                        TaskCreate {
                            title: "Synthetic private AI Task".into(),
                            assign: Some("openmates".into()),
                            ..Default::default()
                        },
                        parse(&f)?,
                    )
                    .await,
                "forbidden",
            )?;
            error_code(
                bridge
                    .projects_create(
                        ProjectCreate {
                            name: "Synthetic no write policy".into(),
                            ..Default::default()
                        },
                        parse(&f)?,
                    )
                    .await,
                "invalid_argument",
            )?;
        }
        "close" => {
            bridge.close().await.map_err(|_| "close")?;
            error_code(bridge.tasks_list(parse(&f)?).await, "cancelled")?;
            error_code(bridge.projects_list(parse(&f)?).await, "cancelled")?;
        }
        "cancel" => {
            let first_error = vector["expected_first_error"]
                .as_str()
                .ok_or("missing in-flight cancellation oracle")?;
            require!(
                first_error == "cancelled",
                "canonical in-flight cancellation oracle"
            );
            let client = bridge.clone();
            let first = tokio::spawn(async move {
                client
                    .tasks_list(TaskFilters {
                        personal: true,
                        ..Default::default()
                    })
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
            require!(blocked, "test blocked request");
            let client = bridge.clone();
            let queued = tokio::spawn(async move {
                client
                    .projects_list(ProjectFilters {
                        personal: true,
                        ..Default::default()
                    })
                    .await
            });
            tokio::time::sleep(Duration::from_millis(30)).await;
            bridge.cancel().map_err(|_| "cancel")?;
            let address = peer.endpoint.strip_prefix("http://").ok_or("address")?;
            let mut socket = TcpStream::connect(address).map_err(|_| "release connect")?;
            socket.write_all(format!("GET /__test/release HTTP/1.1\r\nHost: {address}\r\nConnection: close\r\n\r\n").as_bytes()).map_err(|_|"release write")?;
            let mut body = String::new();
            socket
                .read_to_string(&mut body)
                .map_err(|_| "release response")?;
            error_code(first.await.map_err(|_| "first join")?, first_error)?;
            error_code(queued.await.map_err(|_| "queued join")?, "cancelled")?;
            require!(
                decoded(bridge.projects_list(parse(&f)?).await)?
                    .as_array()
                    .is_some_and(Vec::is_empty),
                "fresh operation after cancellation"
            );
        }
        _ => return Err("unknown work vector"),
    }
    let report = peer.status()?;
    require!(report["failure"].is_null(), "peer assertions");
    if matches!(mode, "crud" | "cancel") {
        let after = decoded(bridge.export_session(true).await)?;
        require!(
            after["revision"].as_u64() > before["revision"].as_u64(),
            "credential revision advanced"
        );
        require!(
            after["session"]["cookies"]["auth_refresh_token"] == report["cookie"],
            "rotated credential snapshot"
        );
    }
    if mode == "crud" {
        require!(report["writes"] == 3, "CRUD writes");
        for check in [
            "encrypted-private-fields",
            "scope-bound-wrapper",
            "fresh-object-key",
            "versioned-encrypted-update",
            "canonical-confirmed-delete",
            "cookie-only-identity-and-rotation",
        ] {
            require!(
                report["checks"]
                    .as_array()
                    .is_some_and(|c| c.contains(&json!(check))),
                "protocol check"
            );
        }
    } else if mode == "cancel" {
        require!(
            report["requests"] == 2 && report["writes"] == 0,
            "queued request fenced"
        );
    } else {
        require!(
            report["requests"] == 0 && report["writes"] == 0,
            "negative zero network"
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
        let result = run_vector(&root, &fixture, suite, vector)
            .await
            .map_err(|error| {
                let case = match vector["id"].as_str() {
                    Some(
                        id @ ("tasks-personal-crud"
                        | "tasks-team-crud"
                        | "projects-personal-crud"
                        | "projects-team-crud"
                        | "unknown-boundary"
                        | "confirmation-boundary"
                        | "scope-boundary"
                        | "policy-boundary"
                        | "close-boundary"
                        | "cancel-boundary"),
                    ) => id,
                    _ => "unknown",
                };
                eprintln!("work_case={case} failure={error}");
                error
            })?;
        results.push(result);
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
