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
const CAPABILITY: &str = "session.plans-workflows.v1";
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
            .arg(root.join("tests/sdk-conformance/session_plans_workflows_server.py"))
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
    serde_json::from_str(&result.map_err(|_| "native work operation")?)
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
    use openmates_sdk::work::{
        PlanCreate, PlanFilters, WorkflowCreate, WorkflowRunOptions, WorkflowWaitOptions,
    };
    let peer = Peer::start(root, fixture, vector["id"].as_str().ok_or("vector")?)?;
    let bridge=SessionBridge::new(&json!({"api_url":peer.endpoint,"app_url":null,"enhanced_privacy":false,"allow_private_operations":vector["allow_private"]}).to_string()).map_err(|_|"construct")?;
    let a = &suite["account"];
    bridge.import_session(json!({"api_url":peer.endpoint,"session_id":a["session_id"],"cookies":{"auth_refresh_token":a["cookie"]},"ws_token":null,"master_key":a["master_key"],"hashed_email":"synthetic-email-hash","user_email_salt":"synthetic-salt","email_encryption_key":null,"created_at":1,"paired_session_expires_at":null,"active_team_id":null}).to_string()).await.map_err(|_|"import")?;
    bridge
        .set_team(Some(
            suite["team"]["team_id"].as_str().ok_or("team")?.into(),
        ))
        .await
        .map_err(|_| "ambient team")?;
    let before = decoded(bridge.export_session(true).await)?;
    let mode = vector["mode"].as_str().ok_or("mode")?;
    let personal = json!({"personal":true});
    let f = if vector["team"] == true {
        json!({"team_id":suite["team"]["team_id"]})
    } else {
        personal.clone()
    };
    let flow = suite["workflow_id"].as_str().ok_or("flow")?.to_owned();
    let run = suite["run_id"].as_str().ok_or("run")?.to_owned();
    match mode {
        "crud" => {
            let plans = vector["family"] == "plans";
            let input = &suite["input"][if plans { "plan" } else { "workflow" }];
            let created = decoded(if plans {
                bridge.plans_create(parse(input)?, parse(&f)?).await
            } else {
                bridge.workflows_create(parse(input)?, parse(&f)?).await
            })?;
            let field = if plans { "plan_id" } else { "id" };
            let id = created[field].as_str().ok_or("created id")?.to_owned();
            require!(created["title"] == input["title"], "created title");
            if plans {
                require!(
                    created["goal"] == input["goal"]
                        && created["user_flows"] == input["user_flows"],
                    "encrypted plan roundtrip"
                );
            } else {
                require!(
                    created["slug"] == input["slug"] && created.get("encrypted_slug").is_none(),
                    "decrypted workflow slug"
                );
            }
            let rows = decoded(if plans {
                bridge.plans_list(parse(&f)?).await
            } else {
                bridge.workflows_list(parse(&f)?).await
            })?;
            require!(
                rows.as_array().is_some_and(|r| r.len() == 1) && rows[0][field] == id,
                "listed object"
            );
            let shown = decoded(if plans {
                bridge.plans_show(id.clone(), parse(&f)?).await
            } else {
                bridge.workflows_show(id.clone(), parse(&f)?).await
            })?;
            require!(shown["title"] == created["title"], "shown title");
            let patch = if plans {
                json!({"goal":"Synthetic revised private goal","planner_focus_id":null,"status":"active"})
            } else {
                json!({"title":"Synthetic revised Workflow","enabled":false})
            };
            let updated = decoded(if plans {
                bridge
                    .plans_update(id.clone(), parse(&patch)?, parse(&f)?)
                    .await
            } else {
                bridge
                    .workflows_update(id.clone(), parse(&patch)?, parse(&f)?)
                    .await
            })?;
            if plans {
                require!(
                    updated["goal"] == patch["goal"] && updated["planner_focus_id"].is_null(),
                    "plan patch"
                );
            } else {
                require!(
                    updated["title"] == patch["title"] && updated["enabled"] == false,
                    "workflow patch"
                );
            }
            let deleted = decoded(if plans {
                bridge.plans_delete(id, true, parse(&f)?).await
            } else {
                bridge.workflows_delete(id, true, parse(&f)?).await
            })?;
            require!(deleted["deleted"] == true, "delete result");
            let rows = decoded(if plans {
                bridge.plans_list(parse(&f)?).await
            } else {
                bridge.workflows_list(parse(&f)?).await
            })?;
            require!(
                rows.as_array().is_some_and(Vec::is_empty),
                "empty deleted list"
            );
        }
        "strict" => {
            require!(
                serde_json::from_value::<PlanCreate>(
                    json!({"title":"synthetic","model":"forbidden"})
                )
                .is_err(),
                "strict plan DTO"
            );
            require!(
                serde_json::from_value::<WorkflowRunOptions>(
                    json!({"idempotency_key":"intent","provider":"forbidden"})
                )
                .is_err(),
                "strict run DTO"
            );
            error_code(
                bridge
                    .plans_create(
                        PlanCreate {
                            title: "synthetic".into(),
                            goal: "private".into(),
                            ..Default::default()
                        },
                        parse(&personal)?,
                    )
                    .await,
                "invalid_argument",
            )?;
            error_code(
                bridge
                    .workflows_wait(
                        flow.clone(),
                        run.clone(),
                        WorkflowWaitOptions {
                            timeout_ms: 0,
                            ..Default::default()
                        },
                        parse(&personal)?,
                    )
                    .await,
                "invalid_argument",
            )?;
            let invalid: WorkflowCreate = parse(
                &json!({"title":"invalid","graph":{"nodes":[{"id":"start","type":"manual_trigger"}],"edges":[{"from":"start","to":"absent"}]}}),
            )?;
            error_code(
                bridge.workflows_create(invalid, parse(&personal)?).await,
                "invalid_argument",
            )?;
        }
        "scope" => {
            let team = json!({"team_id":suite["team"]["team_id"]});
            error_code(bridge.plans_list(parse(&team)?).await, "unavailable")?;
            error_code(
                bridge
                    .workflows_run(flow.clone(), parse(&suite["input"]["run"])?, parse(&team)?)
                    .await,
                "unavailable",
            )?;
            error_code(
                bridge.plans_list(PlanFilters::default()).await,
                "invalid_argument",
            )?;
            error_code(
                bridge
                    .workflows_list(parse(
                        &json!({"personal":true,"team_id":suite["team"]["team_id"]}),
                    )?)
                    .await,
                "invalid_argument",
            )?;
        }
        "consent" => {
            error_code(
                bridge
                    .workflows_create(parse(&suite["input"]["workflow"])?, parse(&personal)?)
                    .await,
                "forbidden",
            )?;
            error_code(
                bridge
                    .workflows_run(
                        flow.clone(),
                        parse(&suite["input"]["run"])?,
                        parse(&personal)?,
                    )
                    .await,
                "forbidden",
            )?;
        }
        "confirmation" => {
            error_code(
                bridge
                    .plans_delete(flow.clone(), false, parse(&personal)?)
                    .await,
                "invalid_argument",
            )?;
            error_code(
                bridge
                    .workflows_delete(flow.clone(), false, parse(&personal)?)
                    .await,
                "invalid_argument",
            )?;
        }
        "http_error" => {
            error_code(
                bridge
                    .workflows_run(
                        flow.clone(),
                        parse(&suite["input"]["run"])?,
                        parse(&personal)?,
                    )
                    .await,
                "forbidden",
            )?;
        }
        _ => {
            let accepted = decoded(
                bridge
                    .workflows_run(
                        flow.clone(),
                        parse(&suite["input"]["run"])?,
                        parse(&personal)?,
                    )
                    .await,
            )?;
            require!(
                accepted["id"] == run && accepted["status"] == "queued",
                "accepted run"
            );
            let mut options = WorkflowWaitOptions {
                timeout_ms: 5000,
                poll_interval_ms: 10,
                sync_interval_ms: 10,
            };
            if mode == "timeout" {
                options.timeout_ms = 30;
                options.poll_interval_ms = 1000;
            }
            if matches!(mode, "cancel" | "local_cancel") {
                options.poll_interval_ms = 10000;
                let client = bridge.clone();
                let waiting_flow = flow.clone();
                let waiting_run = run.clone();
                let waiting = tokio::spawn(async move {
                    client
                        .workflows_wait(
                            waiting_flow,
                            waiting_run,
                            options,
                            openmates_sdk::work::WorkflowFilters {
                                personal: true,
                                ..Default::default()
                            },
                        )
                        .await
                });
                let mut polled = false;
                for _ in 0..500 {
                    if peer.status()?["polls"] == 1 {
                        polled = true;
                        break;
                    }
                    tokio::time::sleep(Duration::from_millis(10)).await;
                }
                require!(polled, "wait poll admitted");
                tokio::time::sleep(Duration::from_millis(50)).await;
                if mode == "local_cancel" {
                    bridge.cancel().map_err(|_| "local cancel")?;
                    error_code(waiting.await.map_err(|_| "wait join")?, "cancelled")?;
                    require!(
                        peer.status()?["cancel_posts"] == 0,
                        "local observer cancel never posts"
                    );
                } else {
                    let requests = peer.status()?["requests"].clone();
                    error_code(
                        bridge
                            .workflows_cancel_run(
                                flow.clone(),
                                run.clone(),
                                openmates_sdk::work::WorkflowFilters {
                                    team_id: Some(
                                        suite["team"]["team_id"].as_str().ok_or("team id")?.into(),
                                    ),
                                    ..Default::default()
                                },
                            )
                            .await,
                        "unavailable",
                    )?;
                    require!(
                        !waiting.is_finished(),
                        "unsupported Team cancel preserves Personal observer"
                    );
                    require!(
                        peer.status()?["requests"] == requests
                            && peer.status()?["cancel_posts"] == 0,
                        "unsupported Team cancel makes no request"
                    );
                    let client = bridge.clone();
                    let unrelated = tokio::spawn(async move {
                        client
                            .plans_list(PlanFilters {
                                personal: true,
                                ..Default::default()
                            })
                            .await
                    });
                    tokio::time::sleep(Duration::from_millis(20)).await;
                    let client = bridge.clone();
                    let cancel_flow = flow.clone();
                    let cancel_run = run.clone();
                    let cancelling = tokio::spawn(async move {
                        client
                            .workflows_cancel_run(
                                cancel_flow,
                                cancel_run,
                                openmates_sdk::work::WorkflowFilters {
                                    personal: true,
                                    ..Default::default()
                                },
                            )
                            .await
                    });
                    error_code(waiting.await.map_err(|_| "wait join")?, "cancelled")?;
                    require!(
                        decoded(unrelated.await.map_err(|_| "unrelated join")?)?
                            .as_array()
                            .is_some_and(Vec::is_empty),
                        "unrelated operation survives scoped cancel"
                    );
                    require!(
                        decoded(cancelling.await.map_err(|_| "cancel join")?)?["status"]
                            == "cancellation_requested",
                        "canonical remote cancel"
                    );
                    require!(
                        decoded(
                            bridge
                                .workflows_run_detail(flow.clone(), run.clone(), parse(&personal)?)
                                .await
                        )?["status"]
                            == "cancelled",
                        "cancelled run reread"
                    );
                }
            } else if mode == "run" {
                let completed = decoded(
                    bridge
                        .workflows_wait(flow.clone(), run.clone(), options, parse(&personal)?)
                        .await,
                )?;
                require!(
                    completed["status"] == "completed"
                        && completed["output_summary"]["deliveries"]["end"]["status"]
                            == "acknowledged",
                    "canonical acknowledged completion"
                );
            } else {
                error_code(
                    bridge
                        .workflows_wait(flow.clone(), run.clone(), options, parse(&personal)?)
                        .await,
                    if mode == "bad_identity" {
                        "forbidden"
                    } else {
                        "invalid_argument"
                    },
                )?;
            }
        }
    }
    let report = peer.status()?;
    require!(report["failure"].is_null(), "peer protocol assertions");
    if matches!(mode, "strict" | "scope" | "consent" | "confirmation") {
        require!(
            report["requests"] == 0 && report["writes"] == 0 && report["run_posts"] == 0,
            "preflight zero requests"
        );
    } else {
        let after = decoded(bridge.export_session(true).await)?;
        require!(
            after["revision"].as_u64() > before["revision"].as_u64(),
            "credential revision"
        );
        require!(
            after["session"]["cookies"]["auth_refresh_token"] == report["cookie"],
            "final rotated cookie"
        );
        require!(
            report["checks"]
                .as_array()
                .is_some_and(|c| c.contains(&json!("cookie-only-identity-and-rotation"))),
            "cookie auth identity"
        );
        if mode == "crud" {
            require!(
                report["writes"] == 3 && report["run_posts"] == 0,
                "CRUD exact writes"
            );
            let checks = if vector["family"] == "plans" {
                vec![
                    "encrypted-plan-private-fields",
                    "plan-master-project-wrappers",
                    "typed-flow-roundtrip",
                ]
            } else {
                vec![
                    "canonical-server-visible-definition",
                    "encrypted-workflow-slug",
                    "opaque-variable-names-preserved",
                ]
            };
            for check in checks {
                require!(
                    report["checks"]
                        .as_array()
                        .is_some_and(|c| c.contains(&json!(check))),
                    "CRUD semantic assertion"
                );
            }
        } else {
            require!(
                report["run_posts"] == 1 && report["cancel_posts"] == u64::from(mode == "cancel"),
                "one accepted intent and scoped cancellation"
            );
            for check in ["stable-run-idempotency", "no-invented-routing"] {
                require!(
                    report["checks"]
                        .as_array()
                        .is_some_and(|c| c.contains(&json!(check))),
                    "run protocol assertion"
                );
            }
            if matches!(mode, "failed" | "bad_identity") {
                require!(report["polls"] == 1, "single rejected canonical reread");
            }
            if mode == "run" {
                require!(report["polls"] == 2, "canonical polling completion");
            }
            if mode == "http_error" {
                require!(report["polls"] == 0, "refused run never polled");
            }
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
            eprintln!("Rust Plans/Workflows protocol conformance failed");
            std::process::exit(1);
        }
    }
}
