//! Actual typed Bridge + owned synthetic peer, authored UNRUN for isolated CI.
//! No inference, real account or local product execution.
use _native::{BindingError, SessionBridge};
use serde_json::{Value, json};
use sha2::{Digest, Sha256};
use std::time::Duration;
type Result<T> = std::result::Result<T, BindingError>;
use std::{
    io::{BufRead, BufReader, Write},
    path::{Path, PathBuf},
    process::{Child, Command, Stdio},
    sync::mpsc as sync_mpsc,
};
const CAPABILITY: &str = "session.chat-first-page-continuation.v1";
struct Fixture {
    bridge: SessionBridge,
    chat: String,
    peer: PeerGuard,
    log: PathBuf,
}
// Own the directory before spawn and the child before any readiness parsing or
// async import/validation. Cancellation/panic/error at any construction step
// therefore drops the same guard; no fully constructed Fixture is required.
struct PeerGuard {
    child: Option<Child>,
    root: PathBuf,
}
impl Drop for PeerGuard {
    fn drop(&mut self) {
        if let Some(child) = &mut self.child {
            let _ = child.kill();
            let _ = child.wait();
        }
        let _ = std::fs::remove_dir_all(&self.root);
    }
}
fn decode(value: Result<String>) -> Value {
    serde_json::from_str(&value.unwrap_or_else(|error| panic!("{}", error.code))).unwrap()
}
impl Fixture {
    async fn new_mode(fixture: &Path, message_id_mode: &str) -> Self {
        let repository = Path::new(env!("CARGO_MANIFEST_DIR"))
            .parent()
            .unwrap()
            .parent()
            .unwrap();
        let root =
            std::env::temp_dir().join(format!("openmates-first-page-{}", uuid::Uuid::new_v4()));
        std::fs::create_dir(&root).unwrap();
        let mut owned = PeerGuard {
            child: None,
            root: root.clone(),
        };
        #[cfg(unix)]
        {
            use std::os::unix::fs::PermissionsExt;
            std::fs::set_permissions(&root, std::fs::Permissions::from_mode(0o700)).unwrap();
        }
        let log = root.join("requests.jsonl");
        let data: Value = serde_json::from_slice(&std::fs::read(&fixture).unwrap()).unwrap();
        let suite = &data["capabilities"][CAPABILITY];
        owned.child = Some(
            Command::new(
                std::env::var("OPENMATES_SDK_CONFORMANCE_PYTHON")
                    .unwrap_or_else(|_| "python3".into()),
            )
            .arg(repository.join("tests/sdk-conformance/first_page_continuation_peer.py"))
            .arg("--fixture")
            .arg(fixture)
            .args(["--capability", CAPABILITY])
            .arg("--request-log")
            .arg(&log)
            .args(["--identity", "rust", "--message-id-mode", message_id_mode])
            .current_dir(repository)
            .stdin(Stdio::null())
            .stdout(Stdio::piped())
            .stderr(Stdio::null())
            .spawn()
            .unwrap(),
        );
        let stdout = owned.child.as_mut().unwrap().stdout.take().unwrap();
        let (tx, rx) = sync_mpsc::sync_channel(1);
        std::thread::spawn(move || {
            let mut line = String::new();
            let _ = BufReader::new(stdout).read_line(&mut line);
            let _ = tx.send(line);
        });
        let ready: Value =
            serde_json::from_str(&rx.recv_timeout(Duration::from_secs(5)).unwrap()).unwrap();
        let endpoint = ready["endpoint"].as_str().unwrap();
        assert!(endpoint.starts_with("http://127.0.0.1:"));
        let bridge=SessionBridge::new(&json!({"api_url":endpoint,"app_url":suite["protocol"]["app_origin"],"enhanced_privacy":false,"allow_private_operations":true}).to_string()).unwrap_or_else(|e|panic!("{}",e.code));
        bridge.import_session(json!({"api_url":endpoint,"session_id":suite["account"]["session_id"],"cookies":{"auth_refresh_token":suite["account"]["cookie"]},"ws_token":null,"master_key":suite["account"]["master_key"],"hashed_email":"synthetic-email-hash","user_email_salt":"synthetic-salt","email_encryption_key":null,"created_at":1,"paired_session_expires_at":null,"active_team_id":null}).to_string()).await.unwrap_or_else(|e|panic!("{}",e.code));
        bridge
            .validate_session()
            .await
            .unwrap_or_else(|e| panic!("{}", e.code));
        Self {
            bridge,
            chat: suite["protocol"]["initial_chat_id"]
                .as_str()
                .unwrap()
                .into(),
            peer: owned,
            log,
        }
    }
    async fn open(&self) -> String {
        decode(
            self.bridge
                .first_page_open(self.chat.clone(), true, true)
                .await,
        )["id"]
            .as_str()
            .unwrap()
            .into()
    }
    async fn accept_capacity(&self, id: &str) {
        let capacity = self.next(id).await;
        assert_eq!(capacity["kind"], "capacity");
        assert!(capacity["checkpoint_json_bytes"].as_u64().unwrap() > 0);
        self.bridge
            .first_page_capacity(id.into(), capacity["id"].as_str().unwrap().into(), true)
            .unwrap_or_else(|e| panic!("{}", e.code));
    }
    async fn next(&self, id: &str) -> Value {
        decode(self.bridge.first_page_next(id.into()).await)
    }
    fn requests(&self) -> Vec<Value> {
        std::fs::read_to_string(&self.log)
            .unwrap_or_default()
            .lines()
            .map(|line| serde_json::from_str(line).unwrap())
            .collect()
    }
    fn exact_receipt(&self, stage: &Value) -> String {
        let id = stage["id"].as_str().unwrap();
        for field in ["checkpoint_json", "credentials_json"] {
            let mut options = std::fs::OpenOptions::new();
            options.write(true).create_new(true);
            #[cfg(unix)]
            {
                use std::os::unix::fs::OpenOptionsExt;
                options.mode(0o600);
            }
            let path = self.peer.root.join(format!("{id}-{field}"));
            let mut file = options.open(&path).unwrap();
            file.write_all(stage[field].as_str().unwrap().as_bytes())
                .unwrap();
            file.sync_all().unwrap();
            assert_eq!(
                std::fs::read_to_string(path).unwrap(),
                stage[field].as_str().unwrap()
            );
        }
        std::fs::File::open(&self.peer.root)
            .unwrap()
            .sync_all()
            .unwrap();
        let stored = std::fs::read(self.peer.root.join(format!("{id}-checkpoint_json"))).unwrap();
        let actual = format!("{:x}", Sha256::digest(stored));
        assert_eq!(actual, stage["ciphertext_sha256"]);
        json!({"ciphertext_sha256":actual,"credential_revision":stage["credential_revision"]})
            .to_string()
    }
    fn ack(&self, id: &str, stage: &Value) {
        self.bridge
            .first_page_receipt(
                id.into(),
                stage["id"].as_str().unwrap().into(),
                self.exact_receipt(stage),
            )
            .unwrap_or_else(|e| panic!("{}", e.code));
    }
}
fn logical(chat: &str, mode: &str, index: usize) -> String {
    let physical = format!("10000000-0000-4000-8000-{index:012}");
    match mode {
        "uuid" => physical,
        "composite" => format!("{}-{physical}", &chat.replace('-', "")[..10]),
        "opaque" => format!("legacy_msg_{index:04}"),
        _ => panic!("unregistered ID mode"),
    }
}
fn rows(value: &Value, f: &Fixture, id_mode: &str, start: usize, count: usize) {
    assert_eq!(value["chat"]["id"], f.chat);
    let messages = value["chat"]["messages"].as_array().unwrap();
    assert_eq!(messages.len(), count);
    for (offset, row) in messages.iter().enumerate() {
        let index = start + offset;
        assert_eq!(row["id"], logical(&f.chat, id_mode, index));
        assert_eq!(
            row["content"],
            format!("Synthetic first-page row {index:03} 雪")
        );
        assert_eq!(
            row["role"],
            if index % 2 == 1 { "user" } else { "assistant" }
        );
        assert_eq!(row["sender"], "Fixture sender");
        assert_eq!(row["thinking"], "");
        assert_eq!(row["embeds"], json!([]));
    }
}
fn final_output(value: &Value, f: &Fixture, id_mode: &str, canonical: bool, count: usize) {
    assert_eq!(
        value["source"],
        if canonical {
            "canonical"
        } else {
            "cache_settled"
        }
    );
    assert_eq!(value["history_complete"], canonical);
    assert_eq!(value["cached"], !canonical);
    assert_eq!(value["refreshing"], false);
    assert_eq!(
        value["pii_restoration"],
        if canonical {
            "all_user_rows"
        } else {
            "all_cached_user_rows"
        }
    );
    rows(value, f, id_mode, 141 - count, count);
}
struct OwnedRead {
    bridge: SessionBridge,
    id: String,
}
impl Drop for OwnedRead {
    fn drop(&mut self) {
        let _ = self.bridge.first_page_close(self.id.clone());
    }
}
#[derive(Default)]
struct Metrics {
    callbacks: usize,
    capacities: usize,
    stages: Vec<String>,
    stage_ids: Vec<String>,
    closed: Option<(String, Value)>,
}
// This is the direct Rust host adapter. A host callback/store failure closes its
// exact owned read, just as the shipped npm/Python facades do; no other read is cancelled.
async fn read(
    f: &Fixture,
    mode: &str,
    id_mode: &str,
    metrics: &mut Metrics,
) -> std::result::Result<Value, String> {
    let id = f.open().await;
    let _owned = OwnedRead {
        bridge: f.bridge.clone(),
        id: id.clone(),
    };
    loop {
        let event = f.next(&id).await;
        match event["kind"].as_str().unwrap() {
            "capacity" => {
                metrics.capacities += 1;
                assert!(event["checkpoint_json_bytes"].as_u64().unwrap() > 0);
                assert!(event["scope"]["account_id"].is_string());
                assert_eq!(
                    f.requests(),
                    vec![json!({"direction":"latest","limit":100})]
                );
                if mode == "capacity-error" {
                    return Err("capacity-io".into());
                }
                f.bridge
                    .first_page_capacity(
                        id.clone(),
                        event["id"].as_str().unwrap().into(),
                        mode != "capacity-false",
                    )
                    .unwrap_or_else(|e| panic!("{}", e.code));
                // Admission is NOT a persistence receipt/ACK.
                assert_eq!(
                    f.bridge
                        .first_page_receipt(
                            id.clone(),
                            event["id"].as_str().unwrap().into(),
                            json!({"ciphertext_sha256":"0".repeat(64),"credential_revision":0})
                                .to_string()
                        )
                        .err()
                        .unwrap()
                        .code,
                    "conflict"
                );
            }
            "stage" => {
                let source = event["source"].as_str().unwrap();
                metrics.stages.push(source.into());
                metrics.stage_ids.push(event["id"].as_str().unwrap().into());
                let checkpoint: Value =
                    serde_json::from_str(event["checkpoint_json"].as_str().unwrap()).unwrap();
                if source == "first_page" {
                    assert_eq!(
                        checkpoint["selected_first_pages"][&f.chat]["messages"]
                            .as_array()
                            .unwrap()
                            .len(),
                        100
                    );
                    assert!(checkpoint["history"].get(&f.chat).is_none());
                    assert!(
                        !event["checkpoint_json"]
                            .as_str()
                            .unwrap()
                            .contains("Synthetic first-page row")
                    );
                    assert_eq!(
                        f.requests(),
                        vec![json!({"direction":"latest","limit":100})]
                    );
                } else if source == "canonical" {
                    assert_eq!(
                        checkpoint["history"][&f.chat].as_array().unwrap().len(),
                        140
                    );
                }
                metrics.closed = Some((id.clone(), event.clone()));
                if mode == "cas-refused" {
                    return Err("conflict".into());
                }
                let receipt = f.exact_receipt(&event);
                if ["wrong-hash", "wrong-revision", "wrong-purpose"].contains(&mode) {
                    let mut wrong: Value = serde_json::from_str(&receipt).unwrap();
                    match mode {
                        "wrong-hash" => wrong["ciphertext_sha256"] = json!("0".repeat(64)),
                        "wrong-revision" => {
                            wrong["credential_revision"] =
                                json!(wrong["credential_revision"].as_u64().unwrap() + 1)
                        }
                        "wrong-purpose" => {
                            wrong["ciphertext_sha256"] = json!(format!(
                                "{:x}",
                                Sha256::digest(
                                    event["credentials_json"].as_str().unwrap().as_bytes()
                                )
                            ))
                        }
                        _ => unreachable!(),
                    }
                    assert_eq!(
                        f.bridge
                            .first_page_receipt(
                                id.clone(),
                                event["id"].as_str().unwrap().into(),
                                wrong.to_string()
                            )
                            .err()
                            .unwrap()
                            .code,
                        "conflict"
                    );
                    return Err("conflict".into());
                }
                f.bridge
                    .first_page_receipt(
                        id.clone(),
                        event["id"].as_str().unwrap().into(),
                        receipt.clone(),
                    )
                    .unwrap_or_else(|e| panic!("{}", e.code));
                assert_eq!(
                    f.bridge
                        .first_page_receipt(
                            id.clone(),
                            event["id"].as_str().unwrap().into(),
                            receipt
                        )
                        .err()
                        .unwrap()
                        .code,
                    "conflict"
                );
            }
            "first_page" => {
                metrics.callbacks += 1;
                assert_eq!(event["source"], "first_page");
                assert_eq!(event["cached"], true);
                assert_eq!(event["refreshing"], true);
                assert_eq!(event["history_complete"], false);
                assert_eq!(event["has_more_before"], true);
                assert_eq!(event["pii_restoration"], "page_local");
                rows(&event, f, id_mode, 41, 100);
                assert_eq!(
                    f.requests(),
                    vec![json!({"direction":"latest","limit":100})]
                );
                tokio::task::yield_now().await;
                assert_eq!(
                    f.requests(),
                    vec![json!({"direction":"latest","limit":100})]
                );
                if mode == "callback-failure" {
                    return Err("callback".into());
                }
                if mode == "callback-cancel" || mode == "stale-a-b" {
                    return Err("cancelled".into());
                }
            }
            "completed" => return Ok(event),
            _ => panic!("unsupported first-page event"),
        }
    }
}
async fn vector(fixture: &Path, entry: &Value) -> Value {
    let mode = entry["mode"].as_str().unwrap();
    let id_mode = entry["message_id_mode"].as_str().unwrap();
    assert!(
        [
            "admit",
            "capacity-false",
            "capacity-error",
            "wrong-hash",
            "wrong-revision",
            "wrong-purpose",
            "cas-refused",
            "callback-failure",
            "callback-cancel",
            "stale-a-b",
            "no-secrets",
            "no-private",
            "warm",
            "strict"
        ]
        .contains(&mode),
        "unregistered mode"
    );
    let f = Fixture::new_mode(fixture, id_mode).await;
    let mut metrics = Metrics::default();
    if mode == "no-secrets" || mode == "no-private" {
        assert_eq!(
            f.bridge
                .first_page_open(f.chat.clone(), mode != "no-secrets", mode != "no-private")
                .await
                .err()
                .unwrap()
                .code,
            "invalid_argument"
        );
        assert!(f.requests().is_empty());
    } else if mode == "strict" {
        let stage = decode(f.bridge.cache_chat_stage(f.chat.clone(), true).await);
        assert_eq!(stage["source"], "canonical");
        let receipt = f.exact_receipt(&stage);
        let done = decode(
            f.bridge
                .cache_chat_commit(stage["id"].as_str().unwrap().into(), receipt)
                .await,
        );
        final_output(&done, &f, id_mode, true, 140);
    } else if [
        "capacity-error",
        "wrong-hash",
        "wrong-revision",
        "wrong-purpose",
        "cas-refused",
        "callback-failure",
        "callback-cancel",
        "stale-a-b",
    ]
    .contains(&mode)
    {
        let expected = match mode {
            "capacity-error" => "capacity-io",
            "callback-failure" => "callback",
            "callback-cancel" | "stale-a-b" => "cancelled",
            _ => "conflict",
        };
        assert_eq!(
            read(&f, mode, id_mode, &mut metrics).await.err().unwrap(),
            expected
        );
        assert_eq!(
            metrics.callbacks,
            usize::from(["callback-failure", "callback-cancel", "stale-a-b"].contains(&mode))
        );
        assert_eq!(
            f.requests(),
            vec![json!({"direction":"latest","limit":100})]
        );
        if mode == "stale-a-b" {
            let (a, stage_a) = metrics.closed.take().unwrap();
            let b = f.open().await;
            let stage = f.next(&b).await;
            assert_eq!(stage["source"], "cache_settled");
            assert_eq!(
                f.bridge.first_page_close(a.clone()).err().unwrap().code,
                "conflict"
            );
            assert_eq!(f.bridge.first_page_receipt(a,stage_a["id"].as_str().unwrap().into(),json!({"ciphertext_sha256":stage_a["ciphertext_sha256"],"credential_revision":stage_a["credential_revision"]}).to_string()).err().unwrap().code,"conflict");
            f.ack(&b, &stage);
            let done = f.next(&b).await;
            final_output(&done, &f, id_mode, false, 100);
            assert_eq!(
                f.requests(),
                vec![json!({"direction":"latest","limit":100})]
            );
        }
    } else {
        let done = read(&f, mode, id_mode, &mut metrics).await.unwrap();
        final_output(&done, &f, id_mode, true, 140);
        assert_eq!(metrics.capacities, 1);
        assert_eq!(metrics.callbacks, usize::from(mode != "capacity-false"));
        assert_eq!(
            metrics.stages,
            if mode == "capacity-false" {
                vec!["canonical"]
            } else {
                vec!["first_page", "canonical"]
            }
        );
        let mut ids = metrics.stage_ids.clone();
        ids.sort();
        ids.dedup();
        assert_eq!(
            ids.len(),
            metrics.stage_ids.len(),
            "separate first-page/final ACK purposes"
        );
        if mode == "warm" {
            let mut warm = Metrics::default();
            let before = f.requests();
            let done = read(&f, "warm", id_mode, &mut warm).await.unwrap();
            final_output(&done, &f, id_mode, false, 140);
            assert_eq!(warm.callbacks, 0);
            assert_eq!(warm.capacities, 0);
            assert_eq!(f.requests(), before);
        }
    }
    if ["admit", "capacity-false", "warm", "strict"].contains(&mode) {
        let mut before = json!({"direction":"before","limit":100});
        if id_mode != "uuid" {
            before["cursor_message_id"] = json!(logical(&f.chat, id_mode, 41));
        }
        assert_eq!(
            f.requests(),
            vec![json!({"direction":"latest","limit":100}), before]
        );
    }
    f.bridge
        .close()
        .await
        .unwrap_or_else(|e| panic!("{}", e.code));
    json!({"id":entry["id"],"status":"passed"})
}
#[tokio::main]
async fn main() {
    let args: Vec<String> = std::env::args().collect();
    let option = |name: &str| {
        args[args
            .iter()
            .position(|v| v == name)
            .expect("required option")
            + 1]
        .clone()
    };
    assert_eq!(option("--capability"), CAPABILITY);
    let fixture = PathBuf::from(option("--fixture"));
    let raw = std::fs::read(&fixture).unwrap();
    let data: Value = serde_json::from_slice(&raw).unwrap();
    let mut results = Vec::new();
    for entry in data["capabilities"][CAPABILITY]["vectors"]
        .as_array()
        .unwrap()
    {
        results.push(
            tokio::time::timeout(Duration::from_secs(25), vector(&fixture, entry))
                .await
                .expect("bounded first-page vector"),
        );
    }
    println!(
        "{}",
        json!({"capability":CAPABILITY,"language":"rust","status":"passed","fixtureSha256":format!("{:x}",Sha256::digest(raw)),"results":results})
    );
}
