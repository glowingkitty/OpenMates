//! Actual Rust SessionBridge, shared synthetic task-only HTTP/WS peer.
//! PRIVATE UNRUN. Only this development executable starts a Python fixture;
//! the SDK and bindings never launch processes or discover local profiles.
use _native::{BindingError, SessionBridge};
use openmates_sdk::work::ProjectFilters;
use serde_json::{Value, json};
use sha2::{Digest, Sha256};
use std::{
    collections::BTreeMap,
    fs::{self, OpenOptions},
    io::{BufRead, BufReader, Read, Write},
    net::TcpStream,
    os::unix::fs::OpenOptionsExt,
    path::{Path, PathBuf},
    process::{Child, Command, Stdio},
    sync::Arc,
    time::Duration,
};
const CAPABILITY: &str = "session.project-task-watch.v1";
const DEADLINE: Duration = Duration::from_secs(10);
type Check<T> = Result<T, &'static str>;
macro_rules! require {
    ($condition:expr, $message:literal) => {
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
        _ => Err("expected typed refusal"),
    }
}
fn session(suite: &Value, endpoint: &str) -> Value {
    json!({"api_url":endpoint,"session_id":suite["account"]["session_id"],"cookies":{"auth_refresh_token":suite["account"]["cookie"]},"ws_token":"synthetic-watch-ws","master_key":suite["account"]["master_key"],"hashed_email":"synthetic-email-hash","user_email_salt":"synthetic-salt","email_encryption_key":null,"created_at":1,"paired_session_expires_at":null,"active_team_id":null})
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
        eprintln!("watch_peer http_status={status} failure_code={code}");
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
                .arg(root.join("tests/sdk-conformance/session_project_task_watch_server.py"))
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
struct Scenario {
    bridge: Arc<SessionBridge>,
    suite: Value,
    vector: Value,
    endpoint: String,
    watches: BTreeMap<String, String>,
    snapshots: BTreeMap<String, Value>,
    saved: BTreeMap<String, Value>,
    bindings: BTreeMap<String, Value>,
    directory: PathBuf,
}
impl Drop for Scenario {
    fn drop(&mut self) {
        for id in self.watches.values() {
            let _ = self.bridge.project_task_watch_close(id.clone());
        }
        let _ = fs::remove_dir_all(&self.directory);
    }
}
impl Scenario {
    fn filters(&self) -> ProjectFilters {
        ProjectFilters {
            personal: self.vector["team"] != true,
            team_id: (self.vector["team"] == true).then(|| {
                self.suite["team"]["team_id"]
                    .as_str()
                    .unwrap_or("")
                    .to_owned()
            }),
            ..Default::default()
        }
    }
    fn scope(&self) -> Value {
        if self.vector["team"] == true {
            json!({"team_id":self.suite["team"]["team_id"]})
        } else {
            json!({"personal":true})
        }
    }
    async fn raw_control(&self, command: Value) -> Check<Value> {
        let endpoint = self.endpoint.clone();
        let report = tokio::task::spawn_blocking(move || http(&endpoint, Some(&command)))
            .await
            .map_err(|_| "peer control task")??;
        require!(report["failure"].is_null(), "peer rejected transport");
        Ok(report)
    }
    async fn bind(&mut self, name: &str) -> Check<u64> {
        let binding = self
            .bindings
            .get(name)
            .ok_or("pending logical binding")?
            .clone();
        let report = self
            .raw_control(json!({"op":"beacon","key":"subscriptions","minimum":0}))
            .await?;
        if let Some(generation) = binding["generation"].as_u64() {
            if report["active_generations"]
                .as_array()
                .ok_or("active generations")?
                .contains(&json!(generation))
            {
                return Ok(generation);
            }
        }
        let after = binding["generation"]
            .as_u64()
            .or(binding["after"].as_u64())
            .ok_or("binding baseline")?;
        let report=self.raw_control(json!({"op":"bind_watch","watch":name,"after":after,"source_id":self.suite["source_id"]})).await?;
        require!(
            report["source_id"] == self.suite["source_id"]
                && report["project_id"] == self.suite["project_id"],
            "observed source binding"
        );
        let generation = report["generation"]
            .as_u64()
            .ok_or("observed connection generation")?;
        require!(generation > after, "fresh connection generation");
        self.bindings
            .get_mut(name)
            .ok_or("pending logical binding")?["generation"] = json!(generation);
        Ok(generation)
    }
    async fn bind_pending(&mut self) -> Check<()> {
        let pending = self
            .bindings
            .iter()
            .filter(|(_, v)| v["generation"].is_null())
            .map(|(name, _)| name.clone())
            .collect::<Vec<_>>();
        for name in pending {
            self.bind(&name).await?;
        }
        Ok(())
    }
    async fn control(&mut self, mut command: Value) -> Check<Value> {
        if let Some(name) = command["watch"].as_str().map(str::to_owned) {
            let generation = if command["op"] == "closed" || command["op"] == "late_force_logout" {
                self.bindings
                    .get(&name)
                    .and_then(|v| v["generation"].as_u64())
                    .ok_or("observed prior connection required")?
            } else {
                self.bind(&name).await?
            };
            command["generation"] = json!(generation);
        }
        self.raw_control(command).await
    }
    async fn open(&mut self, name: &str, checkpoint: Option<Value>) -> Check<()> {
        self.bind_pending().await?;
        let report = self
            .raw_control(json!({"op":"beacon","key":"subscriptions","minimum":0}))
            .await?;
        let after = report["subscriptions"]
            .as_u64()
            .ok_or("open generation baseline")?;
        let input = json!({"source_id":self.suite["source_id"],"checkpoint":checkpoint});
        let opened = decoded(
            self.bridge
                .project_task_watch_open(
                    string(&self.suite, "project_id")?.into(),
                    input.to_string(),
                    self.scope().to_string(),
                )
                .await,
        )?;
        self.watches
            .insert(name.into(), string(&opened, "id")?.into());
        self.bindings.insert(name.into(), json!({"after":after}));
        Ok(())
    }
    fn id(&self, name: &str) -> Check<String> {
        self.watches.get(name).cloned().ok_or("watch handle")
    }
    async fn event(&mut self, name: &str, target: &str, terminal: bool) -> Check<Value> {
        for _ in 0..32 {
            let result = tokio::time::timeout(
                DEADLINE,
                self.bridge.project_task_watch_next(self.id(name)?),
            )
            .await
            .map_err(|_| "next deadline")?;
            let value = match result {
                Err(e) if terminal && ["cancelled", "forbidden", "expired"].contains(&e.code) => {
                    if self
                        .bindings
                        .get(name)
                        .is_some_and(|v| v["generation"].is_null())
                    {
                        self.bindings.remove(name);
                    }
                    return Ok(json!({"kind":"state","state":"closed"}));
                }
                other => decoded(other)?,
            };
            if terminal {
                require!(value["kind"] != "snapshot", "stale plaintext after control");
                if ["revoked", "expired", "closed", "failed"]
                    .contains(&value["state"].as_str().unwrap_or(""))
                {
                    if self
                        .bindings
                        .get(name)
                        .is_some_and(|v| v["generation"].is_null())
                    {
                        self.bindings.remove(name);
                    }
                    return Ok(value);
                }
            } else if target == "refused"
                && value["kind"] == "state"
                && ["reconnecting", "failed", "revoked", "expired", "closed"]
                    .contains(&value["state"].as_str().unwrap_or(""))
            {
                return Ok(value);
            } else if value["kind"] == target || value["state"] == target {
                return Ok(value);
            } else {
                if let Some(terminal_state) = value["state"]
                    .as_str()
                    .filter(|v| ["revoked", "expired", "closed", "failed"].contains(v))
                {
                    eprintln!("watch_terminal state={terminal_state}");
                    return Err("unexpected terminal");
                }
            }
        }
        Err("bounded state transitions")
    }
    fn snapshot(&mut self, name: &str, value: Value, count: usize, cursor: &Value) -> Check<()> {
        require!(value["cursor"] == *cursor, "snapshot cursor");
        let rows = value["tasks"].as_array().ok_or("snapshot tasks")?;
        require!(rows.len() == count, "snapshot count");
        let expected = json!({"api_url":self.endpoint,"account_id":self.suite["owner_id"],"workspace":if self.vector["team"]==true {json!({"team":self.suite["team"]["team_id"]})} else {json!("personal")},"project_id":self.suite["project_id"],"source_id":self.suite["source_id"]});
        require!(value["scope"] == expected, "exact authenticated scope");
        let mut ids = std::collections::BTreeSet::new();
        let mut numeric_ids = std::collections::BTreeSet::new();
        for row in rows {
            let id = string(row, "task_id")?;
            require!(ids.insert(id), "unique tasks");
            let index = uuid::Uuid::parse_str(id)
                .map_err(|_| "task UUID")?
                .as_u128()
                - 1;
            numeric_ids.insert(index + 1);
            require!(
                row["task"]["title"] == format!("Synthetic watch Task {index}"),
                "decrypted task title"
            );
            require!(
                row["task"]["description"] == "Synthetic private description",
                "decrypted task description"
            );
            require!(
                row["task"].get("encrypted_title").is_none(),
                "no raw ciphertext public Task"
            );
        }
        let start = if cursor == "epoch:2" { 2 } else { 1 };
        require!(
            numeric_ids == (start..start + count as u128).collect(),
            "exact replacement/removal inventory"
        );
        require!(
            value["checkpoint"]["cursor"] == *cursor && value["checkpoint"]["scope"] == expected,
            "checkpoint scope cursor"
        );
        let encrypted = value["checkpoint"]["tasks"]
            .as_array()
            .ok_or("checkpoint tasks")?;
        require!(
            encrypted.len() == count
                && encrypted
                    .iter()
                    .all(|r| r["opaque_fixture_metadata"]["preserved"] == true),
            "opaque encrypted metadata retained"
        );
        require!(
            !value["checkpoint"]
                .to_string()
                .contains("Synthetic watch Task"),
            "checkpoint no private plaintext"
        );
        self.snapshots.insert(name.into(), value);
        Ok(())
    }
    async fn ordinary(&self) -> Check<()> {
        require!(
            decoded(self.bridge.projects_list(self.filters()).await)? == json!([]),
            "ordinary typed read"
        );
        Ok(())
    }
    async fn execute(&mut self, step: &Value) -> Check<()> {
        let op = string(step, "op")?;
        let name = step["watch"].as_str().unwrap_or("a");
        match op {
            "open" => {
                let cp = step["checkpoint"]
                    .as_str()
                    .map(|s| self.snapshots[s]["checkpoint"].clone());
                self.open(name, cp).await?;
            }
            "send" | "beacon" | "closed" | "drop" | "revoke" | "force_logout"
            | "late_force_logout" | "ttl_elapsed" | "hold_upgrade" | "release_upgrade"
            | "deny_source" | "rotate" | "idle_flood" => {
                self.control(step.clone()).await?;
            }
            "multipart_snapshot" => {
                let bridge = self.bridge.clone();
                let id = self.id(name)?;
                let mut pending = tokio::spawn(async move {
                    loop {
                        let raw = bridge.project_task_watch_next(id.clone()).await?;
                        let value: Value =
                            serde_json::from_str(&raw).map_err(|_| BindingError {
                                code: "protocol",
                                message: "fixture JSON",
                            })?;
                        if value["kind"] == "snapshot" {
                            return Ok::<Value, BindingError>(value);
                        }
                        if ["failed", "expired", "revoked", "closed"]
                            .contains(&value["state"].as_str().unwrap_or(""))
                        {
                            return Err(BindingError {
                                code: "protocol",
                                message: "fixture terminal",
                            });
                        }
                    }
                });
                require!(
                    tokio::time::timeout(Duration::from_millis(100), &mut pending)
                        .await
                        .is_err(),
                    "partial multipart publication"
                );
                self.control(json!({"op":"send","watch":name,"kind":"final"}))
                    .await?;
                let value = pending
                    .await
                    .map_err(|_| "multipart next join")?
                    .map_err(|_| "multipart next")?;
                self.snapshot(
                    name,
                    value,
                    step["count"].as_u64().ok_or("count")? as usize,
                    &step["cursor"],
                )?;
            }
            "reject_current_commit" => {
                refused(
                    self.bridge
                        .project_task_watch_commit(
                            self.id(name)?,
                            self.snapshots[name]["receipt"].to_string(),
                        )
                        .await,
                    &["conflict"],
                )?;
            }
            "snapshot" => {
                let value = self.event(name, "snapshot", false).await?;
                self.snapshot(
                    name,
                    value,
                    step["count"].as_u64().ok_or("count")? as usize,
                    &step["cursor"],
                )?;
            }
            "state" => {
                let value = self.event(name, string(step, "state")?, false).await?;
                require!(
                    value["cursor"] == self.snapshots[name]["receipt"]["cursor"],
                    "connected exact cursor"
                );
            }
            "terminal" => {
                self.event(name, "", true).await?;
            }
            "commit" => {
                let value = &self.snapshots[name];
                let path = self.directory.join(format!("{name}.json"));
                let mut file = OpenOptions::new()
                    .create(true)
                    .truncate(true)
                    .write(true)
                    .mode(0o600)
                    .open(&path)
                    .map_err(|_| "durable checkpoint create")?;
                file.write_all(value["checkpoint"].to_string().as_bytes())
                    .map_err(|_| "durable checkpoint write")?;
                file.sync_all().map_err(|_| "durable checkpoint sync")?;
                let loaded: Value =
                    serde_json::from_slice(&fs::read(path).map_err(|_| "durable checkpoint read")?)
                        .map_err(|_| "durable checkpoint JSON")?;
                require!(loaded == value["checkpoint"], "durable checkpoint equality");
                self.bridge
                    .project_task_watch_commit(self.id(name)?, value["receipt"].to_string())
                    .await
                    .map_err(|_| "exact local commit")?;
            }
            "reject_commit" => {
                for field in ["batch_id", "cursor"] {
                    let mut bad = self.snapshots[name]["receipt"].clone();
                    bad[field] = json!(if field == "cursor" {
                        "epoch:999"
                    } else {
                        "wrong"
                    });
                    refused(
                        self.bridge
                            .project_task_watch_commit(self.id(name)?, bad.to_string())
                            .await,
                        &["conflict"],
                    )?;
                }
            }
            "reject_expired_commit" => {
                refused(
                    self.bridge
                        .project_task_watch_commit(
                            self.id(name)?,
                            self.snapshots[name]["receipt"].to_string(),
                        )
                        .await,
                    &["expired", "cancelled", "conflict"],
                )?;
            }
            "set_team" => {
                self.bind_pending().await?;
                self.bridge
                    .set_team(Some(string(&self.suite["team"], "team_id")?.into()))
                    .await
                    .map_err(|_| "explicit Team switch")?;
            }
            "close_client" => {
                self.bind_pending().await?;
                self.bridge
                    .close()
                    .await
                    .map_err(|_| "explicit session close")?;
            }
            "save_receipt" => {
                self.saved
                    .insert(name.into(), self.snapshots[name]["receipt"].clone());
            }
            "reject_saved_commit" => {
                refused(
                    self.bridge
                        .project_task_watch_commit(self.id(name)?, self.saved[name].to_string())
                        .await,
                    &["conflict"],
                )?;
            }
            "assert_resume" => {
                let report = self
                    .control(json!({"op":"beacon","key":"subscriptions","minimum":1}))
                    .await?;
                require!(
                    report["resumes"].as_array().and_then(|v| v.last()) == Some(&step["cursor"]),
                    "durable reconnect cursor"
                );
            }
            "ordinary_read" => {
                self.ordinary().await?;
            }
            "close" | "iterator_close" => {
                self.bridge
                    .project_task_watch_close(self.id(name)?)
                    .map_err(|_| "selected close")?;
                if self
                    .bindings
                    .get(name)
                    .is_some_and(|v| v["generation"].is_null())
                {
                    self.bindings.remove(name);
                }
            }
            "close_pending" => {
                let bridge = self.bridge.clone();
                let id = self.id(name)?;
                let task = tokio::spawn(async move { bridge.project_task_watch_next(id).await });
                self.ordinary().await?;
                self.bridge
                    .project_task_watch_close(self.id(name)?)
                    .map_err(|_| "selected priority close")?;
                let result = task.await.map_err(|_| "pending next join")?;
                match result {
                    Ok(raw) => {
                        let value: Value = serde_json::from_str(&raw).map_err(|_| "closed JSON")?;
                        require!(
                            value["kind"] == "state" && value["state"] == "closed",
                            "closed no plaintext"
                        );
                    }
                    Err(e) => require!(e.code == "cancelled", "closed typed error"),
                }
            }
            "reset" => {
                self.bind_pending().await?;
                self.bridge
                    .import_session(session(&self.suite, &self.endpoint).to_string())
                    .await
                    .map_err(|_| "explicit session reset")?;
            }
            "assert_session" => {
                let exported = decoded(self.bridge.export_session(true).await)?;
                require!(
                    exported["session"]["session_id"] == self.suite["account"]["session_id"],
                    "new identity retained"
                );
            }
            "assert_logged_out" => {
                refused(self.bridge.export_session(true).await, &["authentication"])?;
            }
            "assert_rotation" => {
                let exported = decoded(self.bridge.export_session(true).await)?;
                require!(
                    exported["session"]["cookies"]["auth_refresh_token"]
                        == "synthetic-watch-rotated",
                    "rotated credentials retained"
                );
            }
            "tampered_checkpoint" => {
                for kind in ["source", "ciphertext"] {
                    let mut cp = self.snapshots["a"]["checkpoint"].clone();
                    if kind == "source" {
                        cp["scope"]["source_id"] = json!("foreign-source");
                    } else {
                        cp["tasks"][0]["encrypted_title"] = json!("invalid-ciphertext");
                    }
                    self.open("bad", Some(cp)).await?;
                    self.event("bad", "", true).await?;
                }
            }
            "negative_scope" => {
                for (index, kind) in ["owner", "project", "team", "ciphertext", "expired"]
                    .iter()
                    .enumerate()
                {
                    self.open("a", None).await?;
                    self.control(json!({"op":"beacon","key":"subscriptions","minimum":index+1}))
                        .await?;
                    self.control(json!({"op":"send","watch":"a","kind":format!("bad-{kind}")}))
                        .await?;
                    self.event("a", "refused", false).await?;
                    self.bridge
                        .project_task_watch_close(self.id("a")?)
                        .map_err(|_| "negative selected close")?;
                    self.control(json!({"op":"closed","watch":"a"})).await?;
                }
            }
            "cap" => {
                for i in 0..16 {
                    self.open(&i.to_string(), None).await?;
                }
                self.control(json!({"op":"beacon","key":"subscriptions","minimum":16}))
                    .await?;
                let excess = self
                    .bridge
                    .project_task_watch_open(
                        string(&self.suite, "project_id")?.into(),
                        json!({"source_id":self.suite["source_id"]}).to_string(),
                        self.scope().to_string(),
                    )
                    .await;
                refused(excess, &["conflict"])?;
                self.bridge
                    .project_task_watch_close(self.id("0")?)
                    .map_err(|_| "free watch slot")?;
                self.open("replacement", None).await?;
            }
            "busy_finish" => {
                self.control(json!({"op":"hold_list"})).await?;
                let bridge = self.bridge.clone();
                let filters = self.filters();
                let pending = tokio::spawn(async move { bridge.projects_list(filters).await });
                self.control(json!({"op":"beacon","key":"list_entered","minimum":1}))
                    .await?;
                self.control(json!({"op":"send","watch":"a","kind":"baseline"}))
                    .await?;
                self.event("a", "reconnecting", false).await?;
                self.control(json!({"op":"release_list"})).await?;
                require!(
                    decoded(pending.await.map_err(|_| "ordinary join")?)? == json!([]),
                    "ordinary request survived contention"
                );
            }
            "commit_flood_close" => {
                // A completed native conflict is an admission observation; the
                // concurrent batch does not prove capacity4 pressure.
                refused(
                    self.bridge
                        .project_task_watch_commit(
                            self.id(name)?,
                            json!({"batch_id":"wrong","cursor":"epoch:999"}).to_string(),
                        )
                        .await,
                    &["conflict"],
                )?;
                let mut pending = vec![];
                for _ in 0..32 {
                    let bridge = self.bridge.clone();
                    let id = self.id(name)?;
                    pending.push(tokio::spawn(async move {
                        bridge
                            .project_task_watch_commit(
                                id,
                                json!({"batch_id":"wrong","cursor":"epoch:999"}).to_string(),
                            )
                            .await
                    }));
                }
                self.ordinary().await?;
                self.bridge
                    .project_task_watch_close(self.id(name)?)
                    .map_err(|_| "commit flood priority close")?;
                for task in pending {
                    refused(
                        task.await.map_err(|_| "commit task")?,
                        &["conflict", "cancelled"],
                    )?;
                }
                self.ordinary().await?;
            }
            "api_key_refusal" => {
                use openmates_sdk::{ApiKey, ClientOptions, OpenMates, SdkCredentials, SdkOptions};
                let mut api = OpenMates::new(SdkOptions {
                    api_url: self.endpoint.clone(),
                    credentials: SdkCredentials::ApiKey(
                        ApiKey::new("sk-api-syntheticwatch").map_err(|_| "explicit API key")?,
                    ),
                    device_id: "synthetic-watch-device".into(),
                    client_options: ClientOptions::default(),
                })
                .map_err(|_| "explicit API SDK")?;
                match api
                    .projects()
                    .with_filters(ProjectFilters {
                        personal: true,
                        ..Default::default()
                    })
                    .task_source(
                        string(&self.suite, "project_id")?,
                        string(&self.suite, "source_id")?,
                    )
                    .await
                {
                    Err(openmates_sdk::Error::Unavailable { code, reason }) => require!(
                        code == "project_task_watch_unavailable"
                            && reason == "PROJECT_TASK_WATCH_REQUIRES_COOKIE_SESSION",
                        "API unavailable identity"
                    ),
                    _ => return Err("API-key watch must refuse"),
                }
            }
            _ => return Err("unrecognized fixed fixture action"),
        }
        Ok(())
    }
}
async fn run_vector(root: &Path, fixture: &Path, suite: &Value, vector: &Value) -> Check<Value> {
    let peer = tokio::time::timeout(
        DEADLINE,
        Peer::start(root.into(), fixture.into(), string(vector, "id")?.into()),
    )
    .await
    .map_err(|_| "peer startup deadline")??;
    let bridge=Arc::new(SessionBridge::new(&json!({"api_url":peer.endpoint,"app_url":"https://app.example.invalid","enhanced_privacy":false,"allow_private_operations":false}).to_string()).map_err(|_|"native constructor")?);
    bridge
        .import_session(session(suite, &peer.endpoint).to_string())
        .await
        .map_err(|_| "explicit session import")?;
    let directory =
        std::env::temp_dir().join(format!("sdk-watch-durable-{}", uuid::Uuid::new_v4()));
    fs::create_dir(&directory).map_err(|_| "private tempdir")?;
    use std::os::unix::fs::PermissionsExt;
    fs::set_permissions(&directory, fs::Permissions::from_mode(0o700))
        .map_err(|_| "private tempdir mode")?;
    let mut scenario = Scenario {
        bridge,
        suite: suite.clone(),
        vector: vector.clone(),
        endpoint: peer.endpoint.clone(),
        watches: BTreeMap::new(),
        snapshots: BTreeMap::new(),
        saved: BTreeMap::new(),
        bindings: BTreeMap::new(),
        directory,
    };
    for step in vector["steps"].as_array().ok_or("fixture steps")? {
        let case = string(vector, "id")?;
        let operation = string(step, "op")?;
        require!(
            case.len() <= 80
                && operation.len() <= 40
                && case
                    .bytes()
                    .chain(operation.bytes())
                    .all(|b| b.is_ascii_lowercase()
                        || b == b'-'
                        || b == b'_'
                        || b.is_ascii_digit()),
            "static fixture labels"
        );
        let outcome =
            tokio::time::timeout(DEADLINE + Duration::from_secs(2), scenario.execute(step))
                .await
                .map_err(|_| "vector step deadline")
                .and_then(|v| v);
        if let Err(code) = outcome {
            eprintln!("watch_case case={case} operation={operation} failure={code}");
            let endpoint = peer.endpoint.clone();
            if let Ok(Ok(report)) = tokio::task::spawn_blocking(move || http(&endpoint, None)).await
            {
                let failure = report["failure"]
                    .as_str()
                    .filter(|v| {
                        v.len() <= 64 && v.bytes().all(|b| b.is_ascii_alphanumeric() || b == b'_')
                    })
                    .unwrap_or("none");
                eprintln!(
                    "watch_peer_state failure_code={failure} subscriptions={} requests={} list_entered={}",
                    report["subscriptions"].as_u64().unwrap_or(0),
                    report["requests"].as_u64().unwrap_or(0),
                    report["list_entered"].as_u64().unwrap_or(0)
                );
            }
            return Err(code);
        }
    }
    let endpoint = peer.endpoint.clone();
    let report = tokio::task::spawn_blocking(move || http(&endpoint, None))
        .await
        .map_err(|_| "status task")??;
    require!(
        report["failure"].is_null() && report["client_messages"] == 0,
        "no peer rejection or invented ACK"
    );
    if vector["id"] == "api-key-refusal-before-transport" {
        require!(
            report["requests"] == 0 && report["upgrades"] == 0,
            "API-key refusal before transport"
        );
    }
    scenario.bridge.close().await.map_err(|_| "native close")?;
    Ok(json!({"id":vector["id"],"status":"passed"}))
}
// Pure selection policy: a diagnostic subset can never claim full conformance.
fn case_selection(args: &[String], available: &[&str]) -> Check<(Vec<usize>, &'static str)> {
    if available.len() != 25
        || available
            .iter()
            .collect::<std::collections::BTreeSet<_>>()
            .len()
            != 25
    {
        return Err("exact25 fixture cases required");
    }
    let positions = args
        .iter()
        .enumerate()
        .filter(|(_, v)| v.as_str() == "--case")
        .map(|(i, _)| i)
        .collect::<Vec<_>>();
    if positions.is_empty() {
        return Ok(((0..available.len()).collect(), "passed"));
    }
    if positions.len() != 1 {
        return Err("one diagnostic case only");
    }
    let chosen = args
        .get(positions[0] + 1)
        .map(String::as_str)
        .ok_or("missing diagnostic case")?;
    if chosen != "busy-finish-suspend" {
        return Err("unsupported diagnostic case");
    }
    let index = available
        .iter()
        .position(|id| *id == chosen)
        .ok_or("diagnostic case absent")?;
    Ok((vec![index], "partial"))
}
#[cfg(test)]
mod selection_tests {
    use super::case_selection;
    fn ids() -> Vec<String> {
        std::iter::once("busy-finish-suspend".into())
            .chain((1..25).map(|i| format!("fixture-{i}")))
            .collect()
    }
    #[test]
    fn no_flag_keeps_full25_passed_path() {
        let names = ids();
        let borrowed = names.iter().map(String::as_str).collect::<Vec<_>>();
        let (index, status) = case_selection(&[], &borrowed).unwrap();
        assert_eq!(status, "passed");
        assert_eq!(index, (0..25).collect::<Vec<_>>());
    }
    #[test]
    fn selected_case_is_always_partial() {
        let names = ids();
        let borrowed = names.iter().map(String::as_str).collect::<Vec<_>>();
        let (index, status) =
            case_selection(&["--case".into(), "busy-finish-suspend".into()], &borrowed).unwrap();
        assert_eq!(status, "partial");
        assert_eq!(index, vec![0]);
    }
    #[test]
    fn malformed_missing_duplicate_and_non25_refuse() {
        let names = ids();
        let borrowed = names.iter().map(String::as_str).collect::<Vec<_>>();
        for args in [
            vec!["--case".into()],
            vec!["--case".into(), "unknown".into()],
            vec![
                "--case".into(),
                "busy-finish-suspend".into(),
                "--case".into(),
                "busy-finish-suspend".into(),
            ],
        ] {
            assert!(case_selection(&args, &borrowed).is_err());
        }
        assert!(case_selection(&[], &borrowed[..24]).is_err());
    }
}
// End pure selection policy/tests.

#[tokio::main]
async fn main() {
    if let Err(error) = run().await {
        eprintln!("{error}");
        std::process::exit(1);
    }
}
async fn run() -> Check<()> {
    let args = std::env::args().skip(1).collect::<Vec<_>>();
    let option = |name: &str| {
        args.iter()
            .position(|v| v == name)
            .and_then(|i| args.get(i + 1))
            .cloned()
            .ok_or("missing runner option")
    };
    require!(option("--capability")? == CAPABILITY, "capability identity");
    let fixture = PathBuf::from(option("--fixture")?);
    let raw = fs::read(&fixture).map_err(|_| "fixture read")?;
    let document: Value = serde_json::from_slice(&raw).map_err(|_| "fixture JSON")?;
    let suite = &document["capabilities"][CAPABILITY];
    let root = Path::new(env!("CARGO_MANIFEST_DIR"))
        .parent()
        .and_then(Path::parent)
        .ok_or("source root")?;
    let vectors = suite["vectors"].as_array().ok_or("fixture vectors")?;
    let ids = vectors
        .iter()
        .map(|v| string(v, "id"))
        .collect::<Check<Vec<_>>>()?;
    let (selected, status) = case_selection(&args, &ids)?;
    let selected_ids = selected.iter().map(|i| ids[*i]).collect::<Vec<_>>();
    let mut results = vec![];
    for index in selected.iter().copied() {
        match run_vector(root, &fixture, suite, &vectors[index]).await {
            Ok(result) => results.push(result),
            Err(code) => {
                if status == "partial" {
                    println!(
                        "{}",
                        json!({"capability":CAPABILITY,"language":"rust","status":"partial","selectedIds":selected_ids,"selectedCount":selected.len(),"fixtureSha256":format!("{:x}",Sha256::digest(&raw)),"results":[{"id":ids[index],"status":"failed","errorCode":code}]})
                    );
                }
                return Err(code);
            }
        }
    }
    let mut report = json!({"capability":CAPABILITY,"language":"rust","status":status,"fixtureSha256":format!("{:x}",Sha256::digest(&raw)),"results":results});
    if status == "partial" {
        report["selectedIds"] = json!(selected_ids);
        report["selectedCount"] = json!(selected.len());
    }
    println!("{report}");
    Ok(())
}
