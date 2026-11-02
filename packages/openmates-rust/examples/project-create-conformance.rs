//! Actual direct Rust API-key SDK against the shared test-only creation peer.
use openmates_sdk::{
    ApiKey, ClientOptions, OpenMates, SdkCredentials, SdkOptions,
    work::{ProjectCreate, ProjectFilters, ProjectWriteMode},
};
use serde_json::{Value, json};
use sha2::{Digest, Sha256};
use std::{
    io::{BufRead, BufReader, Read, Write},
    net::TcpStream,
    path::PathBuf,
    process::{Child, Command, Stdio},
    time::Duration,
};
const CAPABILITY: &str = "protocol.project-create.v1";
type Check<T> = Result<T, &'static str>;
macro_rules! require {
    ($condition:expr,$message:literal) => {
        if !$condition {
            return Err($message);
        }
    };
}
struct Peer {
    child: Child,
    endpoint: String,
}
impl Drop for Peer {
    fn drop(&mut self) {
        let _ = self.child.kill();
        let _ = self.child.wait();
    }
}
impl Peer {
    fn start(fixture: &str, vector: &str) -> Check<Self> {
        let root = PathBuf::from(env!("CARGO_MANIFEST_DIR"))
            .parent()
            .and_then(|p| p.parent())
            .ok_or("workspace path")?
            .to_owned();
        let mut child = Command::new(
            std::env::var("OPENMATES_SDK_CONFORMANCE_PYTHON").unwrap_or_else(|_| "python3".into()),
        )
        .arg(root.join("tests/sdk-conformance/project_create_server.py"))
        .args([
            "--fixture",
            fixture,
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
        let output = child.stdout.take().ok_or("fixture output")?;
        let mut peer = Self {
            child,
            endpoint: String::new(),
        };
        let mut line = String::new();
        BufReader::new(output)
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
            .ok_or("fixture non-loopback address")?
            .parse::<u16>()
            .map_err(|_| "fixture port")?;
        require!(port > 0, "fixture ephemeral port");
        Ok(peer)
    }
    fn status(&self) -> Check<Value> {
        let address = self
            .endpoint
            .strip_prefix("http://")
            .ok_or("fixture address")?;
        let mut socket = TcpStream::connect(address).map_err(|_| "fixture status")?;
        socket
            .set_read_timeout(Some(Duration::from_secs(3)))
            .map_err(|_| "fixture timeout")?;
        socket
            .write_all(
                format!(
                    "GET /__test/status HTTP/1.1\r\nHost: {address}\r\nConnection: close\r\n\r\n"
                )
                .as_bytes(),
            )
            .map_err(|_| "fixture request")?;
        let mut raw = String::new();
        socket
            .read_to_string(&mut raw)
            .map_err(|_| "fixture response")?;
        serde_json::from_str(raw.split_once("\r\n\r\n").ok_or("fixture HTTP")?.1)
            .map_err(|_| "fixture status JSON")
    }
}
async fn vector(suite: &Value, vector: &Value, fixture: &str) -> Check<Value> {
    let peer = Peer::start(fixture, vector["id"].as_str().ok_or("vector id")?)?;
    let mut client = OpenMates::new(SdkOptions {
        api_url: peer.endpoint.clone(),
        credentials: SdkCredentials::ApiKey(
            ApiKey::new(
                suite["account"]["api_key"]
                    .as_str()
                    .ok_or("API key fixture")?,
            )
            .map_err(|_| "API key configuration")?,
        ),
        device_id: "synthetic-project-fixture".into(),
        client_options: ClientOptions::default(),
    })
    .map_err(|_| "SDK configuration")?;
    for _ in 0..vector["repetitions"].as_u64().ok_or("repetitions")? {
        let mut input: ProjectCreate =
            serde_json::from_value(vector["input"].clone()).map_err(|_| "create input fixture")?;
        input.write_mode = Some(ProjectWriteMode::AlwaysAsk);
        let filters = ProjectFilters {
            personal: vector["team"] != true,
            team_id: if vector["team"] == true {
                Some(
                    suite["team"]["team_id"]
                        .as_str()
                        .ok_or("Team fixture")?
                        .to_owned(),
                )
            } else {
                None
            },
            ..Default::default()
        };
        let output = client.projects().with_filters(filters).create(input).await;
        if vector["error"] == true {
            require!(
                matches!(output, Err(openmates_sdk::Error::Invalid(_))),
                "invalid input accepted"
            );
        } else {
            let output = output.map_err(|_| "actual Project create failed")?;
            for (key, expected) in vector["expected"].as_object().ok_or("expected fields")? {
                require!(&output[key] == expected, "created public value mismatch");
            }
            require!(
                output["project_id"]
                    .as_str()
                    .is_some_and(|id| id.len() == 36),
                "project identity missing"
            );
        }
    }
    let report = peer.status()?;
    require!(report["failure"].is_null(), "fixture protocol assertion");
    require!(
        report["posts"]
            == if vector["error"] == true {
                json!(0)
            } else {
                vector["repetitions"].clone()
            },
        "unexpected project dispatch count"
    );
    let checks = report["checks"].as_array().ok_or("fixture observations")?;
    require!(
        checks.iter().any(|v| v == "bearer-only-transport"),
        "bearer boundary not exercised"
    );
    if vector["error"] != true {
        for check in [
            "backend-required-fields",
            "fresh-project-key-and-focus",
            "canonical-encrypted-default-focus",
            "encrypted-private-fields",
            "scope-bound-key-wrapper",
            "secret-free-wire",
            "safe-write-policy",
        ] {
            require!(
                checks.iter().any(|v| v == check),
                "required create check missing"
            );
        }
    }
    Ok(json!({"id":vector["id"],"status":"passed"}))
}
async fn run() -> Check<Value> {
    let args: Vec<String> = std::env::args().collect();
    let option = |name| {
        args.iter()
            .position(|v| v == name)
            .and_then(|i| args.get(i + 1))
            .ok_or("argument missing")
    };
    require!(
        option("--capability")? == CAPABILITY,
        "unsupported capability"
    );
    let fixture = std::fs::canonicalize(option("--fixture")?).map_err(|_| "fixture path")?;
    let raw = std::fs::read(&fixture).map_err(|_| "fixture read")?;
    let parsed: Value = serde_json::from_slice(&raw).map_err(|_| "fixture JSON")?;
    let suite = &parsed["capabilities"][CAPABILITY];
    let mut results = vec![];
    for item in suite["vectors"].as_array().ok_or("fixture vectors")? {
        results.push(
            vector(
                suite,
                item,
                fixture.to_str().ok_or("fixture path encoding")?,
            )
            .await?,
        );
    }
    require!(!results.is_empty(), "empty fixture");
    Ok(
        json!({"capability":CAPABILITY,"language":"rust","status":"passed","fixtureSha256":format!("{:x}",Sha256::digest(&raw)),"results":results}),
    )
}
#[tokio::main]
async fn main() {
    match tokio::time::timeout(Duration::from_secs(60), run()).await {
        Ok(Ok(result)) => println!("{result}"),
        _ => {
            eprintln!("Rust Project creation conformance failed");
            std::process::exit(1);
        }
    }
}
