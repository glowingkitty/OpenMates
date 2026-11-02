//! UNRUN private regression: actual Bridge+SDK recovery stage against the
//! independent synthetic loopback peer; no server/product/AI requests.
use super::*;
use std::{
    io::{BufRead, BufReader, Read, Write},
    net::{SocketAddr, TcpStream},
    path::Path,
    process::{Child, Command, Stdio},
    sync::mpsc as std_mpsc,
    time::{Duration, Instant},
};
type R<T> = std::result::Result<T, &'static str>;
fn need(value: bool) -> R<()> {
    if value {
        Ok(())
    } else {
        Err("reclamation assertion")
    }
}
fn field<'a>(value: &'a Value, key: &str) -> R<&'a str> {
    value[key].as_str().ok_or("typed fixture field")
}
struct Peer {
    process: Child,
    endpoint: String,
}
impl Peer {
    fn start(root: &Path, fixture: &Path, cap: &str, vector: &str) -> R<Self> {
        let mut process = Command::new(
            std::env::var("OPENMATES_SDK_CONFORMANCE_PYTHON").unwrap_or_else(|_| "python3".into()),
        )
        .arg(root.join("tests/sdk-conformance/essential_session_server.py"))
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
        let stdout = process.stdout.take().ok_or("peer output")?;
        let (tx, rx) = std_mpsc::sync_channel(1);
        std::thread::spawn(move || {
            let mut line = String::new();
            let result = BufReader::new(stdout).read_line(&mut line).map(|_| line);
            let _ = tx.send(result);
        });
        let mut peer = Self {
            process,
            endpoint: String::new(),
        };
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

#[tokio::test]
async fn expired_actual_stage_reaper_removes_registry_closes_claimed_socket_and_frees_work_admission()
-> R<()> {
    tokio::time::timeout(Duration::from_secs(10), async {
        let root = Path::new(env!("CARGO_MANIFEST_DIR")).parent().and_then(Path::parent).ok_or("fixture root")?;
        let fixture = root.join("tests/sdk-conformance/fixtures/session-foreground-completion-recovery.json");
        let suite: Value = serde_json::from_slice(&std::fs::read(&fixture).map_err(|_|"fixture bytes")?).map_err(|_|"fixture JSON")?;
        let suite = &suite["capabilities"]["session.foreground-completion-recovery.v1"];
        let peer = Peer::start(root, &fixture, "session.foreground-completion-recovery.v1", "foreground-expired-stage-reclaimed")?;
        let bridge=SessionBridge::new(&json!({"api_url":peer.endpoint,"app_url":suite["protocol"]["app_origin"],"enhanced_privacy":false,"allow_private_operations":true}).to_string()).map_err(|_|"Bridge")?;
        bridge.import_session(json!({"api_url":peer.endpoint,"session_id":suite["account"]["session_id"],"cookies":{"auth_refresh_token":suite["account"]["cookie"]},"ws_token":null,"master_key":suite["account"]["master_key"],"hashed_email":"synthetic-email-hash","user_email_salt":"synthetic-salt","email_encryption_key":null,"created_at":1,"paired_session_expires_at":null,"active_team_id":null}).to_string()).await.map_err(|_|"explicit synthetic import")?;
        bridge.completion_recovery_enable(true).await.map_err(|_|"explicit foreground")?;
        let probe = Arc::new(ReaperProbe::default());
        *bridge.state.essential.reaper_probe.lock().map_err(|_|"probe lock")? = Some(probe.clone());
        let jobs: Value=serde_json::from_str(&bridge.completion_recovery_jobs().await.map_err(|_|"actual jobs")?).map_err(|_|"jobs JSON")?;
        need(jobs.as_array().is_some_and(|items| items.len()==1))?;
        let output=bridge.completion_recovery_stage(field(&jobs[0],"id")?.into()).await.map_err(|_|"actual opaque stage")?;
        let stage:Value=serde_json::from_str(&output).map_err(|_|"stage JSON")?;
        need(stage["kind"]=="ready")?;
        let id=field(&stage,"id")?.to_owned();
        // Only ciphertext is retained by the caller. This test NEVER calls
        // commit/discard/reset: none can account for the subsequent removal.
        need(!field(&stage,"checkpoint_json")?.is_empty())?;
        probe.entered.notified().await;
        let (retained, token) = {
            let entries=bridge.state.essential.recovery.lock().map_err(|_|"stage lock")?;
            let entry=entries.get(&id).ok_or("retained stage")?;
            (Arc::downgrade(&entry.guard), entry.guard.token())
        };
        need(bridge.state.work_operations.lock().map_err(|_|"work lock")?.len()==1)?;
        let mut other_work=Vec::new();
        for _ in 0..31 { other_work.push(bridge.admit_work().map_err(|_|"fill real work admission")?); }
        need(bridge.admit_work().is_err())?;
        need(peer.get("/__test/status")?["claimed_socket_disconnects"]==0)?;
        // Core uses wall-clock lease expiry, so pausing Tokio's clock would
        // not expire authority. Wait for the ACTUAL typed fence while the
        // reaper is held at an explicit gate, rather than assume sleep means
        // expired. All polling and the full test have bounded deadlines.
        tokio::time::timeout(Duration::from_secs(3), async {
            loop {
                let expired={
                    let entries=bridge.state.essential.recovery.lock().map_err(|_|"expiry lock")?;
                    let entry=entries.get(&id).ok_or("stage removed before reaper gate")?;
                    entry.value.checkpoint().is_err()
                };
                if expired { return Ok::<(), &'static str>(()); }
                tokio::time::sleep(Duration::from_millis(10)).await;
            }
        }).await.map_err(|_|"actual lease expiry deadline")??;
        need(bridge.state.essential.recovery.lock().map_err(|_|"retention lock")?.contains_key(&id))?;
        need(retained.upgrade().is_some())?;
        need(bridge.state.work_operations.lock().map_err(|_|"saturated lock")?.len()==32)?;
        probe.inspect.notify_one();
        probe.removed.notified().await;
        need(!bridge.state.essential.recovery.lock().map_err(|_|"removed lock")?.contains_key(&id))?;
        need(retained.upgrade().is_none())?;
        need(token.is_cancelled())?;
        need(bridge.state.work_operations.lock().map_err(|_|"released lock")?.len()==31)?;
        let fresh=bridge.admit_work().map_err(|_|"reclaimed real work admission")?;
        need(other_work.iter().all(|guard|!guard.token().is_cancelled()))?;
        peer.wait(|status| status["claimed_socket_disconnects"]==1).await?;
        let status=peer.get("/__test/status")?;
        need(status["claims"]==1 && status["persists"]==0 && status["admissions"]==0 && status["failure"].is_null())?;
        drop(fresh);
        drop(other_work);
        bridge.close().await.map_err(|_|"close fixture client")?;
        Ok(())
    }).await.map_err(|_|"bounded reclamation suite")?
}
