//! PRIVATE UNRUN: actual SessionBridge calls; fixture subprocess belongs only to this developer executable.
use _native::{BindingError, SessionBridge};
use serde_json::{Value, json};
use sha2::{Digest, Sha256};
#[cfg(unix)]
use std::os::unix::fs::{OpenOptionsExt, PermissionsExt};
use std::{
    future::Future,
    io::{BufRead, BufReader, Read, Write},
    net::{SocketAddr, TcpStream},
    path::{Path, PathBuf},
    process::{Child, Command, Stdio},
    sync::mpsc,
    time::{Duration, Instant},
};
type R<T> = Result<T, &'static str>;
// Per-vector local context: no shared tracing state survives an await.
#[derive(Clone, Copy)]
enum Phase {
    Open,
    Next,
    Stage,
    DurableSave,
    Commit,
    Close,
    PeerControl,
    PeerStatus,
    Assertion,
    List,
    Discard,
    DurableRead,
    PeerStart,
    StorageSetup,
    ClientSetup,
}
impl Phase {
    fn label(self) -> &'static str {
        match self {
            Self::Open => "open",
            Self::Next => "next",
            Self::Stage => "stage",
            Self::DurableSave => "durable_save",
            Self::Commit => "commit",
            Self::Close => "close",
            Self::PeerControl => "peer_control",
            Self::PeerStatus => "peer_status",
            Self::Assertion => "assertion",
            Self::List => "list",
            Self::Discard => "discard",
            Self::DurableRead => "durable_read",
            Self::PeerStart => "peer_start",
            Self::StorageSetup => "storage_setup",
            Self::ClientSetup => "client_setup",
        }
    }
}
fn native_code(error: BindingError) -> &'static str {
    match error.code {
        "cancelled" => "cancelled",
        "conflict" => "conflict",
        "forbidden" => "forbidden",
        "expired" => "expired",
        "authentication" => "authentication",
        "invalid_argument" => "invalid",
        "crypto" => "crypto",
        "protocol" => "protocol",
        "offline" => "offline",
        "unavailable" => "unavailable",
        _ => "unclassified",
    }
}
fn closed_code(error: &'static str) -> &'static str {
    match error {
        "cancelled" | "conflict" | "forbidden" | "expired" | "authentication" | "invalid"
        | "protocol" | "offline" | "unavailable" | "unclassified" | "timeout" | "crypto" => error,
        "native JSON" => "protocol",
        "peer launch"
        | "peer output"
        | "bounded peer readiness"
        | "peer readiness"
        | "peer JSON"
        | "loopback"
        | "address"
        | "peer connect"
        | "peer timeout"
        | "peer write"
        | "peer read"
        | "peer HTTP"
        | "peer status"
        | "bounded peer state" => "peer_protocol",
        "essential assertion" | "required refusal" => "assertion",
        "owned fixture directory"
        | "private fixture"
        | "fixture file"
        | "fixture write"
        | "fixture fsync"
        | "durable pointer"
        | "pointer JSON"
        | "durable generation"
        | "durable generation fsync"
        | "durable CAS pointer"
        | "durable pointer fsync"
        | "exact durable bytes"
        | "stored bytes" => "storage_io",
        _ => "unclassified",
    }
}
fn need(ok: bool) -> R<()> {
    if ok {
        Ok(())
    } else {
        Err("essential assertion")
    }
}
fn hash(bytes: &[u8]) -> String {
    format!("{:x}", Sha256::digest(bytes))
}
fn field<'a>(value: &'a Value, name: &str) -> R<&'a str> {
    value[name].as_str().ok_or("typed field")
}
async fn decode(future: impl Future<Output = Result<String, BindingError>>) -> R<Value> {
    serde_json::from_str(&future.await.map_err(|_| "native operation")?).map_err(|_| "native JSON")
}
async fn decode_monitor(future: impl Future<Output = Result<String, BindingError>>) -> R<Value> {
    serde_json::from_str(&future.await.map_err(native_code)?).map_err(|_| "native JSON")
}
fn refused<T>(result: Result<T, BindingError>, codes: &[&str]) -> R<()> {
    match result {
        Err(error) => need(codes.contains(&error.code)),
        Ok(_) => Err("required refusal"),
    }
}
struct Peer {
    process: Child,
    endpoint: String,
}
impl Peer {
    fn start(root: &Path, fixture: &Path, cap: &str, vector: &str) -> R<Self> {
        let process = Command::new(
            std::env::var("OPENMATES_SDK_CONFORMANCE_PYTHON").unwrap_or_else(|_| "python3".into()),
        )
        .arg(root.join(if cap == "session.initial-startup-sync.v1" { "tests/sdk-conformance/startup_sync_server.py" } else { "tests/sdk-conformance/essential_session_server.py" }))
        .args([
            "--fixture",
            fixture.to_str().ok_or("fixture path")?,
            "--capability",
            cap,
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
        .map_err(|_| "peer launch")?;
        // Own the child before any fallible stdout/readiness/import work.
        let mut peer = Self { process, endpoint: String::new() };
        let stdout = peer.process.stdout.take().ok_or("peer output")?;
        let (tx, rx) = mpsc::sync_channel(1);
        std::thread::spawn(move || {
            let mut line = String::new();
            let result = BufReader::new(stdout).read_line(&mut line).map(|_| line);
            let _ = tx.send(result);
        });
        let line = rx
            .recv_timeout(Duration::from_secs(3))
            .map_err(|_| "bounded peer readiness")?
            .map_err(|_| "peer readiness")?;
        let ready: Value = serde_json::from_str(&line).map_err(|_| "peer JSON")?;
        peer.endpoint = field(&ready, "endpoint")?.to_owned();
        need(peer.endpoint.starts_with("http://127.0.0.1:"))?;
        Ok(peer)
    }
    fn get(&self, route: &str) -> R<Value> {
        let address: SocketAddr = self
            .endpoint
            .strip_prefix("http://")
            .ok_or("loopback")?
            .parse()
            .map_err(|_| "address")?;
        let mut socket = TcpStream::connect_timeout(&address, Duration::from_secs(2))
            .map_err(|_| "peer connect")?;
        socket
            .set_read_timeout(Some(Duration::from_secs(2)))
            .map_err(|_| "peer timeout")?;
        socket
            .set_write_timeout(Some(Duration::from_secs(2)))
            .map_err(|_| "peer timeout")?;
        socket
            .write_all(
                format!("GET {route} HTTP/1.1\r\nHost: {address}\r\nConnection: close\r\n\r\n")
                    .as_bytes(),
            )
            .map_err(|_| "peer write")?;
        let mut bytes = String::new();
        socket
            .take(1024 * 1024)
            .read_to_string(&mut bytes)
            .map_err(|_| "peer read")?;
        serde_json::from_str(bytes.split_once("\r\n\r\n").ok_or("peer HTTP")?.1)
            .map_err(|_| "peer status")
    }
    async fn wait(&self, predicate: impl Fn(&Value) -> bool) -> R<()> {
        let deadline = Instant::now() + Duration::from_secs(2);
        while Instant::now() < deadline {
            if predicate(&self.get("/__test/status")?) {
                return Ok(());
            }
            tokio::time::sleep(Duration::from_millis(10)).await;
        }
        Err("bounded peer state")
    }
}
impl Drop for Peer {
    fn drop(&mut self) {
        let _ = self.process.kill();
        let deadline = Instant::now() + Duration::from_secs(2);
        while Instant::now() < deadline {
            if self.process.try_wait().ok().flatten().is_some() {
                break;
            }
            std::thread::sleep(Duration::from_millis(10));
        }
    }
}
struct Directory(PathBuf);
impl Directory {
    fn new() -> R<Self> {
        let path = std::env::temp_dir().join(format!(
            "openmates-essential-conformance-{}",
            uuid::Uuid::new_v4()
        ));
        std::fs::create_dir(&path).map_err(|_| "owned fixture directory")?;
        #[cfg(unix)]
        std::fs::set_permissions(&path, std::fs::Permissions::from_mode(0o700))
            .map_err(|_| "private fixture")?;
        Ok(Self(path))
    }
    fn write(&self, name: &str, bytes: &[u8]) -> R<()> {
        let mut options = std::fs::OpenOptions::new();
        options.write(true).create_new(true);
        #[cfg(unix)]
        options.mode(0o600);
        let mut file = options
            .open(self.0.join(name))
            .map_err(|_| "fixture file")?;
        file.write_all(bytes).map_err(|_| "fixture write")?;
        file.sync_all().map_err(|_| "fixture fsync")
    }
}
impl Drop for Directory {
    fn drop(&mut self) {
        let _ = std::fs::remove_dir_all(&self.0);
    }
}
struct Store<'a>(&'a Directory);
impl Store<'_> {
    fn generation(&self) -> R<Option<String>> {
        let pointer = self.0.0.join("current");
        if !pointer.exists() {
            return Ok(None);
        }
        let value: Value =
            serde_json::from_slice(&std::fs::read(pointer).map_err(|_| "durable pointer")?)
                .map_err(|_| "pointer JSON")?;
        Ok(Some(field(&value, "version")?.to_owned()))
    }
    fn save(&self, stage: &Value, expected: Option<&str>) -> R<Option<String>> {
        if self.generation()?.as_deref() != expected {
            return Ok(None);
        }
        let id = field(stage, "id")?;
        need(uuid::Uuid::parse_str(id).is_ok())?;
        std::fs::create_dir(self.0.0.join(id)).map_err(|_| "durable generation")?;
        self.0.write(
            &format!("{id}/checkpoint"),
            field(stage, "checkpoint_json")?.as_bytes(),
        )?;
        self.0.write(
            &format!("{id}/credentials"),
            field(stage, "credentials_json")?.as_bytes(),
        )?;
        std::fs::File::open(self.0.0.join(id))
            .and_then(|file| file.sync_all())
            .map_err(|_| "durable generation fsync")?;
        let next = format!("pointer-{id}");
        self.0.write(
            &next,
            json!({"version":id,"scope":stage["scope"]})
                .to_string()
                .as_bytes(),
        )?;
        std::fs::rename(self.0.0.join(next), self.0.0.join("current"))
            .map_err(|_| "durable CAS pointer")?;
        std::fs::File::open(&self.0.0)
            .and_then(|file| file.sync_all())
            .map_err(|_| "durable pointer fsync")?;
        let bytes = std::fs::read(self.0.0.join(id).join("checkpoint"))
            .map_err(|_| "exact durable bytes")?;
        Ok(Some(monitor_receipt(stage, hash(&bytes))))
    }
}
fn session(suite: &Value, endpoint: &str) -> Value {
    json!({"api_url":endpoint,"session_id":suite["account"]["session_id"],"cookies":{"auth_refresh_token":suite["account"]["cookie"]},"ws_token":null,"master_key":suite["account"]["master_key"],"hashed_email":"synthetic-email-hash","user_email_salt":"synthetic-salt","email_encryption_key":null,"created_at":1,"paired_session_expires_at":null,"active_team_id":null})
}
async fn client(suite: &Value, peer: &Peer) -> R<SessionBridge> {
    let bridge=SessionBridge::new(&json!({"api_url":peer.endpoint,"app_url":suite["protocol"]["app_origin"],"enhanced_privacy":false,"allow_private_operations":true}).to_string()).map_err(|_|"actual Bridge")?;
    bridge
        .import_session(session(suite, &peer.endpoint).to_string())
        .await
        .map_err(|_| "explicit synthetic session")?;
    Ok(bridge)
}
fn monitor_receipt(stage: &Value, digest: String) -> String {
    json!({"ciphertext_sha256":digest,"credential_revision":stage["credential_revision"]})
        .to_string()
}
async fn stage_monitor(bridge: &SessionBridge, id: &str) -> R<Value> {
    decode_monitor(bridge.chat_monitor_stage(id.into(), None, true)).await
}
async fn monitor_commit(
    bridge: &SessionBridge,
    id: &str,
    stage: &Value,
    digest: String,
) -> R<Value> {
    decode_monitor(bridge.chat_monitor_commit(
        id.into(),
        field(stage, "id")?.into(),
        monitor_receipt(stage, digest),
    ))
    .await
}
async fn vector(
    root: &Path,
    fixture: &Path,
    cap: &str,
    suite: &Value,
    vector: &Value,
    phase: &mut Phase,
) -> R<Value> {
    *phase = Phase::PeerStart;
    let peer = Peer::start(root, fixture, cap, field(vector, "id")?)?;
    *phase = Phase::StorageSetup;
    let directory = Directory::new()?;
    *phase = Phase::ClientSetup;
    let bridge = client(suite, &peer).await?;
    let mode = field(vector, "mode")?;
    if mode.starts_with("startup_") {
        startup_sync::run(&bridge, suite, vector, &peer).await?;
    } else if mode.starts_with("selected_") {
        selected_recovery::run(&bridge, suite, vector, &peer, &directory).await?;
    } else if mode.starts_with("monitor") {
        *phase = Phase::Open;
        let mut opened = decode_monitor(bridge.chat_monitor_open()).await?;
        if mode == "monitor_read_cancel" {
            let initial_id = field(&opened, "id")?;
            *phase = Phase::Next;
            decode_monitor(bridge.chat_monitor_next(initial_id.into())).await?;
            *phase = Phase::Stage;
            let first = stage_monitor(&bridge, initial_id).await?;
            let store = Store(&directory);
            *phase = Phase::DurableSave;
            let receipt = store.save(&first, None)?.ok_or("initial durable refresh")?;
            *phase = Phase::Commit;
            decode_monitor(bridge.chat_monitor_commit(
                initial_id.into(),
                field(&first, "id")?.into(),
                receipt,
            ))
            .await?;
            let old_id = field(&opened, "id")?.to_owned();
            let worker = bridge.clone();
            let read_id = old_id.clone();
            *phase = Phase::Next;
            let pending = tokio::spawn(async move { worker.chat_monitor_next(read_id).await });
            tokio::time::sleep(Duration::from_millis(20)).await;
            *phase = Phase::Close;
            bridge
                .chat_monitor_close(old_id)
                .map_err(|_| "priority read close")?;
            *phase = Phase::Next;
            refused(pending.await.map_err(|_| "read join")?, &["cancelled"])?;
            *phase = Phase::Open;
            opened = decode_monitor(bridge.chat_monitor_open()).await?;
            *phase = Phase::PeerControl;
            peer.get("/__test/control?action=burst")?;
        }
        let id = field(&opened, "id")?;
        *phase = Phase::Next;
        let notice = decode_monitor(bridge.chat_monitor_next(id.into())).await?;
        *phase = Phase::Assertion;
        need(notice["kind"] == "invalidation")?;
        if mode == "monitor_phase1b_context" {
            *phase = Phase::Stage;
            refused(bridge.chat_monitor_stage(id.into(), None, true).await, &["forbidden"])?;
            need(!directory.0.join("checkpoint").exists())?;
        } else if mode == "monitor_denial" {
            *phase = Phase::PeerControl;
            peer.get("/__test/control?action=deny")?;
            *phase = Phase::Stage;
            refused(
                bridge
                    .chat_monitor_stage(
                        id.into(),
                        Some(field(&suite["protocol"], "initial_chat_id")?.into()),
                        true,
                    )
                    .await,
                &["forbidden"],
            )?;
            *phase = Phase::Stage;
            let value: Value = serde_json::from_str(
                &bridge
                    .chat_monitor_access_denial(id.into())
                    .map_err(|_| "safe denial")?,
            )
            .map_err(|_| "denial JSON")?;
            need(
                value["reason"] == "chat_unavailable"
                    && value["chat_id"] == suite["protocol"]["initial_chat_id"],
            )?;
            need(!directory.0.join("checkpoint").exists())?;
        } else if mode == "monitor_store_failure" {
            *phase = Phase::Stage;
            let stage = stage_monitor(&bridge, id).await?;
            *phase = Phase::DurableSave;
            need(
                directory
                    .write(
                        "missing/checkpoint",
                        field(&stage, "checkpoint_json")?.as_bytes(),
                    )
                    .is_err(),
            )?;
            *phase = Phase::Discard;
            bridge
                .chat_monitor_discard(id.into(), field(&stage, "id")?.into())
                .map_err(|_| "failed storage discard")?;
            *phase = Phase::Next;
            decode_monitor(bridge.chat_monitor_next(id.into())).await?;
            *phase = Phase::Stage;
            let next = stage_monitor(&bridge, id).await?;
            let store = Store(&directory);
            *phase = Phase::DurableSave;
            let receipt = store.save(&next, None)?.ok_or("retry durable store")?;
            *phase = Phase::Commit;
            let models = decode_monitor(bridge.chat_monitor_commit(
                id.into(),
                field(&next, "id")?.into(),
                receipt,
            ))
            .await?;
            need(models["items"].is_array())?;
        } else if mode == "monitor_revoke" {
            *phase = Phase::PeerControl;
            peer.get("/__test/control?action=burst")?;
            *phase = Phase::PeerControl;
            peer.get("/__test/control?action=revoke")?;
            *phase = Phase::PeerControl;
            peer.wait(|s| s["monitor_disconnects"].as_u64().is_some_and(|v| v >= 1))
                .await?;
            *phase = Phase::Stage;
            refused(
                bridge.chat_monitor_stage(id.into(), None, true).await,
                &["cancelled", "forbidden"],
            )?;
        } else if mode == "monitor_data_changed" {
            *phase = Phase::Stage;
            let stage = stage_monitor(&bridge, id).await?;
            *phase = Phase::DurableSave;
            directory.write("checkpoint", field(&stage, "checkpoint_json")?.as_bytes())?;
            *phase = Phase::DurableSave;
            directory.write("credentials", field(&stage, "credentials_json")?.as_bytes())?;
            *phase = Phase::PeerControl;
            peer.get("/__test/control?action=advance")?;
            *phase = Phase::List;
            decode_monitor(bridge.list("chats".into())).await?;
            *phase = Phase::DurableRead;
            let stored =
                std::fs::read(directory.0.join("checkpoint")).map_err(|_| "stored bytes")?;
            *phase = Phase::Commit;
            refused(
                bridge
                    .chat_monitor_commit(
                        id.into(),
                        field(&stage, "id")?.into(),
                        monitor_receipt(&stage, hash(&stored)),
                    )
                    .await,
                &["cancelled"],
            )?;
        } else if mode == "monitor_cas" {
            let store = Store(&directory);
            *phase = Phase::DurableRead;
            let expected = store.generation()?;
            *phase = Phase::Stage;
            let old = stage_monitor(&bridge, id).await?;
            *phase = Phase::PeerControl;
            peer.get("/__test/control?action=advance")?;
            *phase = Phase::List;
            decode_monitor(bridge.list("chats".into())).await?;
            *phase = Phase::ClientSetup;
            let newer = client(suite, &peer).await?;
            *phase = Phase::Open;
            let opened = decode_monitor(newer.chat_monitor_open()).await?;
            let fresh_id = field(&opened, "id")?;
            *phase = Phase::Next;
            decode_monitor(newer.chat_monitor_next(fresh_id.into())).await?;
            *phase = Phase::Stage;
            let fresh = stage_monitor(&newer, fresh_id).await?;
            *phase = Phase::DurableRead;
            let expected_fresh = store.generation()?;
            *phase = Phase::DurableSave;
            let receipt = store
                .save(&fresh, expected_fresh.as_deref())?
                .ok_or("fresh durable CAS")?;
            *phase = Phase::Commit;
            decode_monitor(newer.chat_monitor_commit(
                fresh_id.into(),
                field(&fresh, "id")?.into(),
                receipt,
            ))
            .await?;
            *phase = Phase::DurableRead;
            let before =
                std::fs::read(directory.0.join("current")).map_err(|_| "durable pointer")?;
            *phase = Phase::DurableSave;
            need(store.save(&old, expected.as_deref())?.is_none())?;
            *phase = Phase::DurableRead;
            need(
                std::fs::read(directory.0.join("current")).map_err(|_| "durable pointer")?
                    == before,
            )?;
            *phase = Phase::Discard;
            bridge
                .chat_monitor_discard(id.into(), field(&old, "id")?.into())
                .map_err(|_| "stale writer discard")?;
            *phase = Phase::Close;
            newer
                .chat_monitor_close(fresh_id.into())
                .map_err(|_| "priority close")?;
            *phase = Phase::Close;
            newer.close().await.map_err(|_| "close")?;
        } else {
            *phase = Phase::Stage;
            let stage = stage_monitor(&bridge, id).await?;
            *phase = Phase::DurableSave;
            let raw = field(&stage, "checkpoint_json")?;
            if mode.starts_with("monitor_phase1b") {
                let snapshot: Value = serde_json::from_str(raw).map_err(|_| "window checkpoint")?;
                let chat_id = field(&suite["protocol"], "initial_chat_id")?;
                let window = &snapshot["sync_message_windows"][chat_id];
                need(window["messages"].as_array().is_some_and(|rows|rows.len()==2))?;
                need(window["server_message_count"]==5 && window["has_more_before"]==true)?;
                need(snapshot["history"].get(chat_id).is_none() && window.get("history_complete").is_none())?;
                for message in window["messages"].as_array().ok_or("window rows")? {
                    need(message["chat_id"]==chat_id && message["encrypted_content"].is_string() && message.get("content").is_none())?;
                }
                if matches!(mode,"monitor_phase1b_metadata_coverage"|"monitor_phase1b_metadata_responses") {
                    let mut parents=vec![chat_id.to_owned()];parents.extend((1..25).map(|index|format!("30000000-0000-4000-8000-{index:012}")));
                    let child="60000000-0000-4000-8000-000000000000";let mut expected=parents.clone();expected.push(child.into());
                    if mode=="monitor_phase1b_metadata_responses" {
                        expected.extend(["70000000-0000-4000-8000-000000000001".into(),"70000000-0000-4000-8000-000000000002".into()]);
                        need(snapshot["chats"].get("80000000-0000-4000-8000-000000000001").is_none()&&snapshot.get("older_metadata_pages").is_none())?;
                        need(snapshot["chats"][expected[27].as_str()]["parent_id"]==expected[26]&&snapshot["chats"][expected[27].as_str()]["is_sub_chat"]==true)?;
                        need(expected[26..].iter().all(|id|snapshot["history"].get(id).is_none()))?;
                    }
                    need(snapshot["chats"].as_object().is_some_and(|rows|rows.len()==expected.len()&&expected.iter().all(|id|rows.contains_key(id))))?;
                    need(snapshot["chat_arrival_order_v1"]["ids"]==json!(expected))?;
                    need(snapshot["sync_message_windows"].as_object().is_some_and(|windows|windows.len()==20&&parents[..20].iter().all(|id|windows.contains_key(id))))?;
                    need(snapshot["chats"][child]["parent_id"]==chat_id && snapshot["chats"][child]["is_sub_chat"]==true && snapshot["history"].get(child).is_none())?;
                    for(index,id)in expected.iter().enumerate(){let row=&snapshot["chats"][id.as_str()];need(row["id"].as_str()==Some(id.as_str())&&row["encrypted_title"].is_string()&&row["pinned"]==json!(index<25&&index%2==0||mode=="monitor_phase1b_metadata_responses"&&index==26))?;need(row["opaqueUserMetadata"]==json!({"linkedProjectIds":["雪","😀"],"camelCase":{"sourceId":"preserve-verbatim"}}))?;}
                }
            }
            need(raw.contains("linkedProjectIds") && raw.contains('雪'))?;
            let mut bytes = raw.as_bytes().to_vec();
            if mode == "monitor_byte" {
                bytes.push(b' ')
            }
            *phase = Phase::DurableSave;
            directory.write("checkpoint", &bytes)?;
            *phase = Phase::DurableSave;
            directory.write("credentials", field(&stage, "credentials_json")?.as_bytes())?;
            if mode == "monitor_byte" {
                *phase = Phase::Commit;
                refused(
                    bridge
                        .chat_monitor_commit(
                            id.into(),
                            field(&stage, "id")?.into(),
                            monitor_receipt(&stage, hash(&bytes)),
                        )
                        .await,
                    &["conflict"],
                )?;
            } else {
                *phase = Phase::Commit;
                let models = monitor_commit(&bridge, id, &stage, hash(&bytes)).await?;
                need(models["items"].is_array())?;
            }
        }
        *phase = Phase::Close;
        bridge
            .chat_monitor_close(id.into())
            .map_err(|_| "priority close")?;
    } else {
        refused(bridge.completion_recovery_jobs().await, &["unavailable"])?;
        bridge
            .completion_recovery_enable(true)
            .await
            .map_err(|_| "explicit foreground")?;
        if mode != "disabled" {
            let jobs = decode(bridge.completion_recovery_jobs()).await?;
            let jobs = jobs.as_array().ok_or("typed jobs")?;
            need(jobs.len() == 1)?;
            let job_id = field(&jobs[0], "id")?;
            if mode == "main_legacy_created_at" {
                let staged=decode(bridge.completion_recovery_stage(job_id.into())).await?;
                need(staged["kind"]=="ready")?;
                let raw=field(&staged,"checkpoint_json")?;
                let needle=format!(",\"created_at\":{}}},\"encrypted_candidate\"",vector["created_at"]);
                need(raw.matches(&needle).count()==1)?;
                let legacy=raw.replace(&needle,"},\"encrypted_candidate\"");
                let decoded:Value=serde_json::from_str(&legacy).map_err(|_|"legacy checkpoint")?;
                need(decoded["job"].get("created_at").is_none())?;
                directory.write("legacy-checkpoint",legacy.as_bytes())?;
                bridge.close().await.map_err(|_|"close legacy owner")?;
                tokio::time::sleep(Duration::from_millis(1200)).await;
                let reopened=client(suite,&peer).await?;
                reopened.completion_recovery_enable(true).await.map_err(|_|"legacy foreground")?;
                let authentic=decode(reopened.completion_recovery_jobs()).await?;
                need(authentic[0]["job"]["created_at"]==vector["created_at"])?;
                let resumed=decode(reopened.completion_recovery_resume(legacy.clone())).await?;
                need(resumed["kind"]=="ready" && resumed["checkpoint_json"]==legacy)?;
                let receipt=decode(reopened.completion_recovery_commit(field(&resumed,"id")?.into(),json!({"checkpoint_sha256":hash(legacy.as_bytes())}).to_string())).await?;
                need(receipt["state"]=="TERMINAL")?;
                reopened.close().await.map_err(|_|"close resumed legacy")?;
            } else if mode == "main_cancel" {
                let worker = bridge.clone();
                let job_id = job_id.to_owned();
                let pending =
                    tokio::spawn(async move { worker.completion_recovery_stage(job_id).await });
                peer.wait(|s| s["claims"] == 1).await?;
                bridge.cancel().map_err(|_| "cancel")?;
                refused(pending.await.map_err(|_| "stage join")?, &["cancelled"])?;
            } else {
                let stage = decode(bridge.completion_recovery_stage(job_id.into())).await?;
                need(stage["kind"] == "ready")?;
                if mode == "main_created_at" {
                    let checkpoint:Value=serde_json::from_str(field(&stage,"checkpoint_json")?).map_err(|_|"created time checkpoint")?;
                    need(checkpoint["encrypted_candidate"]["created_at"] == vector["created_at"])?;
                }
                let raw = field(&stage, "checkpoint_json")?;
                let mut bytes = raw.as_bytes().to_vec();
                if mode == "main_byte" {
                    bytes.push(b' ')
                }
                directory.write("checkpoint", &bytes)?;
                need(peer.get("/__test/status")?["persists"] == 0)?;
                if mode == "main_expiry" {
                    tokio::time::sleep(Duration::from_millis(2300)).await;
                }
                if mode == "main_reset" {
                    bridge
                        .import_session(session(suite, &peer.endpoint).to_string())
                        .await
                        .map_err(|_| "owner replacement")?;
                }
                if mode == "main_owner" {
                    let before = peer.get("/__test/status")?["claims"].clone();
                    let forged = raw.replace(
                        field(&suite["account"], "owner_id")?,
                        "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
                    );
                    refused(
                        bridge.completion_recovery_resume(forged).await,
                        &["forbidden"],
                    )?;
                    need(peer.get("/__test/status")?["claims"] == before)?;
                } else {
                    let result = bridge
                        .completion_recovery_commit(
                            field(&stage, "id")?.into(),
                            json!({"checkpoint_sha256":hash(&bytes)}).to_string(),
                        )
                        .await;
                    if matches!(mode, "main_byte" | "main_reset" | "main_expiry") {
                        refused(result, &["conflict", "cancelled"])?;
                    } else if mode == "main_cas_exhausted" {
                        refused(result, &["conflict"])?;
                    } else if mode == "main_lost_ack" {
                        refused(result, &["offline"])?;
                        bridge.close().await.map_err(|_| "close sender")?;
                        let reopened = client(suite, &peer).await?;
                        reopened
                            .completion_recovery_enable(true)
                            .await
                            .map_err(|_| "foreground reopen")?;
                        let outcome =
                            decode(reopened.completion_recovery_resume(raw.into())).await?;
                        need(
                            outcome["kind"] == "canonical"
                                && outcome["receipt"]["assistant_message_id"]
                                    == suite["protocol"]["assistant_id"],
                        )?;
                        reopened.close().await.map_err(|_| "close reader")?;
                    } else {
                        let result: Value =
                            serde_json::from_str(&result.map_err(|_| "canonical persist")?)
                                .map_err(|_| "receipt JSON")?;
                        need(
                            result["state"] == "TERMINAL"
                                && result["assistant_message_id"]
                                    == suite["protocol"]["assistant_id"],
                        )?;
                    }
                }
            }
        }
    }
    *phase = Phase::Close;
    bridge.close().await.map_err(|_| "close")?;
    *phase = Phase::PeerStatus;
    let status = peer.get("/__test/status")?;
    need(status["failure"].is_null() && status["admissions"] == 0)?;
    if mode == "main_legacy_created_at" { need(status["claims"] == 2)?; }
    if mode.starts_with("main_cas_") { need(status["persist_attempts"] == 4 && status["claims"] == 1)?; }
    need(
        status["persists"]
            == if matches!(mode, "main" | "main_lost_ack" | "selected_main" | "main_created_at" | "main_cas_retry" | "main_legacy_created_at") {
                1
            } else {
                0
            },
    )?;
    Ok(json!({"id":vector["id"],"status":"passed"}))
}
fn monitor_vector_id(input: &Value) -> R<&str> {
    let id = field(input, "id")?;
    match id {
        "monitor-durable-opaque"
        | "monitor-one-byte-refusal"
        | "monitor-data-cas-race"
        | "monitor-priority-revoke"
        | "monitor-personal-chat-403-scoped"
        | "monitor-store-failure-requeues-no-publish"
        | "monitor-pending-read-close-reopen"
        | "monitor-stage-data-mutation-refusal" => Ok(id),
        _ => Err("reviewed monitor vector required"),
    }
}
pub async fn main(capability: &str) -> R<()> {
    let args = std::env::args().collect::<Vec<_>>();
    let option = |name: &str| {
        args.iter()
            .position(|arg| arg == name)
            .and_then(|i| args.get(i + 1))
            .map(String::as_str)
            .ok_or("argument")
    };
    need(option("--capability")? == capability)?;
    let root = Path::new(env!("CARGO_MANIFEST_DIR")).join("../..");
    let fixture = PathBuf::from(option("--fixture")?)
        .canonicalize()
        .map_err(|_| "fixture path")?;
    let raw = std::fs::read(&fixture).map_err(|_| "fixture")?;
    let suite: Value = serde_json::from_slice(&raw).map_err(|_| "fixture JSON")?;
    let suite = &suite["capabilities"][capability];
    let mut results = vec![];
    for input in suite["vectors"].as_array().ok_or("vectors")? {
        let mut phase = Phase::Open;
        let result = tokio::time::timeout(
            Duration::from_secs(15),
            vector(&root, &fixture, capability, suite, input, &mut phase),
        )
        .await
        .map_err(|_| "timeout")
        .and_then(|value| value);
        match result {
            Ok(value) => results.push(value),
            Err(error) => {
                if capability == "session.chat-change-monitor.v1" {
                    let id = monitor_vector_id(input)?;
                    println!(
                        "{}",
                        json!({"capability":capability,"language":"rust","status":"failed",
                        "fixtureSha256":hash(&raw),"results":[{"id":id,"status":"failed"}],
                        "diagnostic":{"vectorId":id,"phase":phase.label(),"errorCode":closed_code(error)}})
                    );
                }
                return Err(error);
            }
        }
    }
    println!(
        "{}",
        json!({"capability":capability,"language":"rust","status":"passed","fixtureSha256":hash(&raw),"results":results})
    );
    Ok(())
}

#[path = "selected_recovery.rs"]
mod selected_recovery;
#[path = "startup_sync.rs"]
mod startup_sync;
