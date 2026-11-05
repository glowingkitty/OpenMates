//! PRIVATE UNRUN: actual Rust source DTOs/SessionBridge, independent shared peer.
//! Child Python is only a developer fixture; SDK production never spawns it.
// contract-test-file: tooling
use _native::{BindingError, SessionBridge};
use openmates_sdk::work::{ProjectFilters, ProjectSourceCapabilitiesPatch, ProjectSourceCreate};
use serde_json::{Value, json};
use sha2::{Digest, Sha256};
use std::{
    io::{BufRead, BufReader, Read, Write},
    net::TcpStream,
    path::{Path, PathBuf},
    process::{Child, Command, Stdio},
    sync::Arc,
    time::{Duration, SystemTime, UNIX_EPOCH},
};
const CAPABILITY: &str = "session.project-source-authoring.v1";
const DEADLINE: Duration = Duration::from_secs(12);
type Check<T> = Result<T, &'static str>;
macro_rules! require {
    ($condition:expr,$message:literal) => {
        if !$condition {
            return Err($message);
        }
    };
}
fn string<'a>(v: &'a Value, key: &str) -> Check<&'a str> {
    v[key].as_str().ok_or("fixture string")
}
fn decoded(v: Result<String, BindingError>) -> Check<Value> {
    serde_json::from_str(&v.map_err(|_| "actual native operation")?).map_err(|_| "native JSON")
}
fn refused<T>(v: Result<T, BindingError>, codes: &[&str]) -> Check<()> {
    match v {
        Err(e) if codes.is_empty() || codes.contains(&e.code) => Ok(()),
        Err(e) => {
            eprintln!("source_error code={}", e.code);
            Err("unexpected typed refusal")
        }
        Ok(_) => Err("expected typed refusal"),
    }
}
fn session(suite: &Value, endpoint: &str) -> Value {
    json!({"api_url":endpoint,"session_id":suite["account"]["session_id"],"cookies":{"auth_refresh_token":suite["account"]["cookie"]},"ws_token":"synthetic-source-ws","master_key":suite["account"]["master_key"],"hashed_email":"synthetic-email-hash","user_email_salt":"synthetic-salt","email_encryption_key":null,"created_at":1,"paired_session_expires_at":null,"active_team_id":null})
}
fn http(endpoint: &str, operation: Option<&Value>) -> Check<Value> {
    let address = endpoint
        .strip_prefix("http://127.0.0.1:")
        .ok_or("loopback endpoint")?;
    let port: u16 = address.parse().map_err(|_| "loopback port")?;
    require!(port > 0, "ephemeral port");
    let mut socket = TcpStream::connect(("127.0.0.1", port)).map_err(|_| "peer connect")?;
    socket
        .set_read_timeout(Some(DEADLINE))
        .map_err(|_| "peer timeout")?;
    socket
        .set_write_timeout(Some(DEADLINE))
        .map_err(|_| "peer write timeout")?;
    let request = if let Some(op) = operation {
        let raw = op.to_string();
        format!(
            "POST /__test/control HTTP/1.1\r\nHost: 127.0.0.1\r\nContent-Type: application/json\r\nContent-Length: {}\r\nConnection: close\r\n\r\n{}",
            raw.len(),
            raw
        )
    } else {
        "GET /__test/status HTTP/1.1\r\nHost: 127.0.0.1\r\nConnection: close\r\n\r\n".into()
    };
    socket
        .write_all(request.as_bytes())
        .map_err(|_| "peer request")?;
    let mut raw = Vec::new();
    socket
        .take(1024 * 1024)
        .read_to_end(&mut raw)
        .map_err(|_| "peer response")?;
    let raw = String::from_utf8(raw).map_err(|_| "peer UTF8")?;
    if !(raw.starts_with("HTTP/1.0 200") || raw.starts_with("HTTP/1.1 200")) {
        let status = raw
            .lines()
            .next()
            .and_then(|line| line.split_whitespace().nth(1))
            .and_then(|v| v.parse::<u16>().ok())
            .unwrap_or(0);
        let diagnostic: Value = raw
            .split_once("\r\n\r\n")
            .and_then(|(_, body)| serde_json::from_str(body).ok())
            .unwrap_or(Value::Null);
        let code = diagnostic["failure_code"]
            .as_str()
            .filter(|v| v.len() <= 64 && v.bytes().all(|b| b.is_ascii_alphanumeric() || b == b'_'))
            .unwrap_or("unknown");
        eprintln!("source_peer http_status={status} failure_code={code}");
        return Err("peer status");
    }
    serde_json::from_str(raw.split_once("\r\n\r\n").ok_or("peer headers")?.1)
        .map_err(|_| "peer JSON")
}
struct Peer {
    child: Child,
    endpoint: String,
}
impl Peer {
    async fn start(root: PathBuf, fixture: PathBuf, vector: String) -> Check<Self> {
        tokio::task::spawn_blocking(move || {
            let python = std::env::var("OPENMATES_SDK_CONFORMANCE_PYTHON")
                .unwrap_or_else(|_| "python3".into());
            let mut child = Command::new(python)
                .arg(root.join("tests/sdk-conformance/session_project_sources_server.py"))
                .arg("--fixture")
                .arg(fixture)
                .args(["--vector", &vector, "--identity", "rust"])
                .current_dir(root)
                .stdin(Stdio::null())
                .stdout(Stdio::piped())
                .stderr(Stdio::null())
                .spawn()
                .map_err(|_| "peer launch")?;
            let stdout = child.stdout.take().ok_or("peer stdout")?;
            let mut peer = Self {
                child,
                endpoint: String::new(),
            };
            let (tx, rx) = std::sync::mpsc::sync_channel(1);
            std::thread::spawn(move || {
                let mut raw = String::new();
                let result = BufReader::new(stdout)
                    .take(65536)
                    .read_line(&mut raw)
                    .map(|_| raw);
                let _ = tx.send(result);
            });
            let raw = rx
                .recv_timeout(Duration::from_secs(8))
                .map_err(|_| "peer readiness deadline")?
                .map_err(|_| "peer readiness")?;
            let ready: Value = serde_json::from_str(&raw).map_err(|_| "peer readiness JSON")?;
            peer.endpoint = string(&ready, "endpoint")?.into();
            require!(
                peer.endpoint.starts_with("http://127.0.0.1:"),
                "loopback peer only"
            );
            Ok(peer)
        })
        .await
        .map_err(|_| "peer launch task")?
    }
}
impl Drop for Peer {
    fn drop(&mut self) {
        let _ = self.child.kill();
        let _ = self.child.wait();
    }
}
fn parse<T: serde::de::DeserializeOwned>(value: &Value) -> Result<T, BindingError> {
    serde_json::from_value(value.clone()).map_err(|_| BindingError {
        code: "invalid_argument",
        message: "Invalid typed source input.",
    })
}
async fn operation(
    bridge: &SessionBridge,
    suite: &Value,
    case: &Value,
    filters: ProjectFilters,
) -> Result<String, BindingError> {
    let project = suite["project_id"]
        .as_str()
        .ok_or(BindingError {
            code: "invalid_argument",
            message: "Project fixture.",
        })?
        .to_owned();
    if case["operation"] == "list-raw" {
        bridge.projects_list_sources_raw(project, filters).await
    } else if case["operation"] == "list-names" {
        bridge.projects_list_sources_decoded_names(project, filters).await
    } else if case["operation"] == "create" {
        bridge
            .projects_create_source(
                project,
                parse::<ProjectSourceCreate>(&case["input"])?,
                filters,
            )
            .await
    } else {
        bridge
            .projects_update_source_capabilities(
                project,
                case["source_id"]
                    .as_str()
                    .ok_or(BindingError {
                        code: "invalid_argument",
                        message: "Source fixture.",
                    })?
                    .into(),
                parse::<ProjectSourceCapabilitiesPatch>(&case["input"])?,
                filters,
            )
            .await
    }
}
async fn control(peer: &Peer, command: Value) -> Check<Value> {
    let endpoint = peer.endpoint.clone();
    let report = tokio::task::spawn_blocking(move || http(&endpoint, Some(&command)))
        .await
        .map_err(|_| "fixture control task")??;
    require!(report["failure"].is_null(), "peer source protocol rejected");
    Ok(report)
}
async fn status(peer: &Peer) -> Check<Value> {
    let endpoint = peer.endpoint.clone();
    let report = tokio::task::spawn_blocking(move || http(&endpoint, None))
        .await
        .map_err(|_| "fixture status task")??;
    require!(report["failure"].is_null(), "peer source protocol rejected");
    Ok(report)
}
async fn run_vector(root: &Path, fixture: &Path, suite: &Value, vector: &Value) -> Check<Value> {
    let peer = tokio::time::timeout(
        DEADLINE,
        Peer::start(root.into(), fixture.into(), string(vector, "id")?.into()),
    )
    .await
    .map_err(|_| "peer startup deadline")??;
    let bridge=Arc::new(SessionBridge::new(&json!({"api_url":peer.endpoint,"app_url":"https://app.example.invalid","enhanced_privacy":false,"allow_private_operations":false}).to_string()).map_err(|_|"native explicit source constructor")?);
    let mut imported = session(suite, &peer.endpoint);
    if vector["mode"] == "expired" || vector["mode"] == "read-expired" {
        imported["paired_session_expires_at"] = json!(
            SystemTime::now()
                .duration_since(UNIX_EPOCH)
                .map_err(|_| "fixture clock")?
                .as_millis() as u64
                + 2000
        );
    }
    if vector["mode"] == "read-unrelated-master" { imported["master_key"] = json!("KioqKioqKioqKioqKioqKioqKioqKioqKioqKioqKio="); }
    if vector["mode"] != "read-api-key" {
        bridge
            .import_session(imported.to_string())
            .await
            .map_err(|_| "explicit source session")?;
        bridge
            .set_team(Some(string(&suite["team"], "team_id")?.into()))
            .await
            .map_err(|_| "explicit ambient Team")?;
    }
    if vector["mode"] == "expired" || vector["mode"] == "read-expired" {
        control(
            &peer,
            json!({"op":"await_expiry","deadline_ms":imported["paired_session_expires_at"]}),
        )
        .await?;
    }
    let filters = ProjectFilters {
        personal: vector["team"] != true,
        team_id: if vector["team"] == true {
            Some(string(&suite["team"], "team_id")?.into())
        } else {
            None
        },
        ..Default::default()
    };
    for (index, case) in vector["cases"]
        .as_array()
        .ok_or("fixture cases")?
        .iter()
        .enumerate()
    {
        let label = string(vector, "id")?;
        require!(
            label.len() <= 80
                && label
                    .bytes()
                    .all(|b| b.is_ascii_lowercase() || b == b'-' || b.is_ascii_digit()),
            "static source case label"
        );
        let op = if case["operation"] == "list-raw" { "list-raw" } else if case["operation"] == "list-names" { "list-names" } else if case["operation"] == "create" {
            "create"
        } else {
            "patch"
        };
        eprintln!("source_phase case={label} index={index} operation={op}");
        control(&peer, json!({"op":"case","index":index})).await?;
        let before = status(&peer).await?;
        if vector["mode"] == "read-api-key" {
            use openmates_sdk::{ApiKey, ClientOptions, OpenMates, SdkCredentials, SdkOptions};
            let sdk = OpenMates::new(SdkOptions {
                api_url:peer.endpoint.clone(),
                credentials:SdkCredentials::ApiKey(ApiKey::new("sk-api-syntheticsources").map_err(|_|"explicit source read API key")?),
                device_id:"synthetic-source-read-device".into(),client_options:ClientOptions::default(),
            }).map_err(|_|"explicit API-key source read SDK")?;
            let result = tokio::time::timeout(DEADLINE, sdk.list_project_sources_raw(string(suite,"project_id")?,filters.clone())).await.map_err(|_|"source raw read deadline")?;
            if let Some(code) = case["expected_error"].as_str() {
                refused(result.map_err(BindingError::from), &[code])?;
            } else {
                require!(json!(result.map_err(|_|"actual API-key raw read")?) == case["expected"], "complete API-key raw rows retained");
            }
        } else if vector["mode"] == "api-key" {
            use openmates_sdk::{
                ApiKey, ClientOptions, Error, OpenMates, SdkCredentials, SdkOptions,
            };
            let mut sdk = OpenMates::new(SdkOptions {
                api_url: peer.endpoint.clone(),
                credentials: SdkCredentials::ApiKey(
                    ApiKey::new("sk-api-syntheticsources")
                        .map_err(|_| "explicit source API key")?,
                ),
                device_id: "synthetic-source-device".into(),
                client_options: ClientOptions::default(),
            })
            .map_err(|_| "explicit API-key SDK")?;
            let result = if case["operation"] == "create" {
                sdk.projects()
                    .with_filters(filters.clone())
                    .create_source(
                        string(suite, "project_id")?,
                        parse(&case["input"]).map_err(|_| "typed source fixture")?,
                    )
                    .await
            } else {
                sdk.projects()
                    .with_filters(filters.clone())
                    .update_source_capabilities(
                        string(suite, "project_id")?,
                        string(case, "source_id")?,
                        parse(&case["input"]).map_err(|_| "typed patch fixture")?,
                    )
                    .await
            };
            match result {
                Err(Error::Unavailable { code, reason }) => require!(
                    code == "project_source_authoring_unavailable"
                        && reason == "PROJECT_SOURCE_AUTHORING_REQUIRES_COOKIE_SESSION",
                    "API-key exact unavailable reason"
                ),
                _ => return Err("API-key source authoring must refuse before transport"),
            }
        } else if (vector["mode"] == "cancel" || vector["mode"] == "read-cancel") && index == 0 {
            let call_bridge = bridge.clone();
            let call_suite = suite.clone();
            let call_case = case.clone();
            let f = filters.clone();
            let pending =
                tokio::spawn(
                    async move { operation(&call_bridge, &call_suite, &call_case, f).await },
                );
            control(&peer, json!({"op":"entered"})).await?;
            bridge
                .cancel()
                .map_err(|_| "explicit source cancellation")?;
            control(&peer, json!({"op":"release"})).await?;
            refused(
                tokio::time::timeout(DEADLINE, pending)
                    .await
                    .map_err(|_| "source cancel deadline")?
                    .map_err(|_| "source cancel task")?,
                &["cancelled"],
            )?;
        } else {
            let result =
                tokio::time::timeout(DEADLINE, operation(&bridge, suite, case, filters.clone()))
                    .await
                    .map_err(|_| "source operation deadline")?;
            if let Some(code) = case["expected_error"].as_str() {
                refused(result, &[code])?;
            } else {
                let decoded = decoded(result)?;
                if case["operation"] == "list-raw" || case["operation"] == "list-names" {
                    require!(decoded == case["expected"], "complete raw/name-only result exact, no lost unknown metadata/order");
                } else {
                let mut expected = if case["operation"] == "create" {
                    case["input"].clone()
                } else {
                    suite["seed"].clone()
                };
                if case["operation"] == "patch" {
                    expected["source_id"] = case["source_id"].clone();
                    for (k, v) in case["input"].as_object().ok_or("patch fixture")? {
                        expected[k] = v.clone();
                    }
                }
                require!(
                    decoded == expected,
                    "full exact source metadata/name/capabilities DTO"
                );
                }
            }
        }
        let after = status(&peer).await?;
        let expected = if vector["mode"] == "api-key" {
            0
        } else {
            case["expected_mutation_attempts"]
                .as_u64()
                .ok_or("expected attempts")?
        };
        require!(
            after["mutation_attempts"].as_u64().ok_or("attempts")?
                - before["mutation_attempts"]
                    .as_u64()
                    .ok_or("before attempts")?
                == expected,
            "exact source mutation attempts/no retry"
        );
        if case["operation"] == "list-raw" || case["operation"] == "list-names" {
            for (counter, expected) in [("source_reads","expected_read_attempts"),("project_reads","expected_project_attempts"),("team_reads","expected_team_attempts")] {
                require!(after[counter].as_u64().ok_or("source read counter")? - before[counter].as_u64().ok_or("prior source read counter")? == case[expected].as_u64().ok_or("expected exact read counter")?, "exact original source/Project/Team reads, no retry or hidden key setup");
            }
        }
        if case["zero_transport"] == true {
            require!(
                after["requests"] == before["requests"],
                "source refusal before transport"
            );
        }
        if vector["mode"] != "read-api-key" && after["requests"].as_u64() > before["requests"].as_u64() {
            let exported = decoded(bridge.export_session(true).await)?;
            require!(
                exported["session"]["cookies"]["auth_refresh_token"] == after["cookie"],
                "retain latest final cookie after error/cancel"
            );
            require!(
                exported["session"]["active_team_id"] == suite["team"]["team_id"],
                "source never changes selected Team"
            );
        }
    }
    bridge.close().await.map_err(|_| "source client close")?;
    Ok(json!({"id":vector["id"],"status":"passed"}))
}
async fn run() -> Check<()> {
    let args = std::env::args().skip(1).collect::<Vec<_>>();
    let option = |name: &str| {
        args.iter()
            .position(|v| v == name)
            .and_then(|i| args.get(i + 1))
            .cloned()
            .ok_or("runner argument")
    };
    require!(
        option("--capability")? == CAPABILITY,
        "source capability identity"
    );
    let fixture = PathBuf::from(option("--fixture")?);
    let raw = std::fs::read(&fixture).map_err(|_| "source fixture read")?;
    let document: Value = serde_json::from_slice(&raw).map_err(|_| "source fixture JSON")?;
    let suite = &document["capabilities"][CAPABILITY];
    let root = Path::new(env!("CARGO_MANIFEST_DIR"))
        .parent()
        .and_then(Path::parent)
        .ok_or("source root")?;
    let mut results = vec![];
    for vector in suite["vectors"].as_array().ok_or("source vectors")? {
        match tokio::time::timeout(
            Duration::from_secs(120),
            run_vector(root, &fixture, suite, vector),
        )
        .await
        {
            Ok(Ok(result)) => results.push(result),
            _ => {
                let id = string(vector, "id")?;
                if id.len() <= 80
                    && id
                        .bytes()
                        .all(|b| b.is_ascii_lowercase() || b == b'-' || b.is_ascii_digit())
                {
                    eprintln!("source_case_failed:{id}");
                }
                return Err("actual source conformance failed");
            }
        }
    }
    println!(
        "{}",
        json!({"capability":CAPABILITY,"language":"rust","status":"passed","fixtureSha256":format!("{:x}",Sha256::digest(&raw)),"results":results})
    );
    Ok(())
}
#[tokio::main]
async fn main() {
    if let Err(reason) = run().await {
        eprintln!("{reason}");
        std::process::exit(1);
    }
}
