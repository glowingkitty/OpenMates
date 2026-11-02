//! Actual synthetic loopback HTTP/WebSocket peer and real SessionBridge calls.
//! Authored for isolated CI; these are not fake-native facade forwarding tests.
use super::*;
use std::{io::{BufRead, BufReader, Write}, path::{Path, PathBuf}, process::{Child, Command, Stdio}, sync::mpsc, time::Duration};
const CAP: &str = "session.cache-preferred-settlement.v1";
struct Peer { child: Child, endpoint: String }
impl Peer {
    fn start(root: &Path) -> Self {
        let mut child = Command::new(std::env::var("OPENMATES_SDK_CONFORMANCE_PYTHON").unwrap_or_else(|_| "python3".into()))
            .arg(root.join("tests/sdk-conformance/cache_settlement_peer.py"))
            .args(["--fixture", root.join("tests/sdk-conformance/fixtures/session-cache-preferred-settlement.json").to_str().unwrap(), "--capability", CAP, "--vector", "selected-exact-ack", "--identity", "rust"])
            .current_dir(root).stdin(Stdio::null()).stdout(Stdio::piped()).stderr(Stdio::null()).spawn().unwrap();
        let stdout = child.stdout.take().unwrap();
        let (tx, rx) = mpsc::sync_channel(1);
        std::thread::spawn(move || { let mut line = String::new(); let _ = BufReader::new(stdout).read_line(&mut line); let _ = tx.send(line); });
        let mut peer = Self { child, endpoint: String::new() };
        let ready: Value = serde_json::from_str(&rx.recv_timeout(Duration::from_secs(5)).expect("bounded synthetic peer startup")).expect("synthetic peer readiness");
        peer.endpoint = ready["endpoint"].as_str().unwrap().to_owned();
        assert!(peer.endpoint.starts_with("http://127.0.0.1:"));
        peer
    }
}
impl Drop for Peer { fn drop(&mut self) { let _ = self.child.kill(); let _ = self.child.wait(); } }
struct Fixture { bridge: SessionBridge, chat: String, _peer: Peer }
impl Fixture {
    async fn new() -> Self {
        let root = Path::new(env!("CARGO_MANIFEST_DIR")).parent().unwrap().parent().unwrap();
        let data: Value = serde_json::from_slice(&std::fs::read(root.join("tests/sdk-conformance/fixtures/session-cache-preferred-settlement.json")).unwrap()).unwrap();
        let suite = &data["capabilities"][CAP];
        let peer = Peer::start(root);
        let bridge = SessionBridge::new(&json!({"api_url":peer.endpoint,"app_url":suite["protocol"]["app_origin"],"enhanced_privacy":false,"allow_private_operations":true}).to_string()).unwrap_or_else(|e| panic!("construct {}",e.code));
        bridge.import_session(json!({"api_url":peer.endpoint,"session_id":suite["account"]["session_id"],"cookies":{"auth_refresh_token":suite["account"]["cookie"]},"ws_token":null,"master_key":suite["account"]["master_key"],"hashed_email":"synthetic-email-hash","user_email_salt":"synthetic-salt","email_encryption_key":null,"created_at":1,"paired_session_expires_at":null,"active_team_id":null}).to_string()).await.unwrap_or_else(|e|panic!("import {}",e.code));
        bridge.validate_session().await.unwrap_or_else(|e|panic!("validate {}",e.code));
        Self { bridge, chat: suite["protocol"]["initial_chat_id"].as_str().unwrap().to_owned(), _peer: peer }
    }
    async fn stage(&self) -> Value { decode(self.bridge.cache_chat_stage(self.chat.clone(), true).await) }
    async fn commit(&self, stage: &Value) -> Value {
        let store = Store::new(); let receipt = store.exact_receipt(stage);
        let value = decode(self.bridge.cache_chat_commit(stage["id"].as_str().unwrap().into(), receipt).await);
        assert_owned_rows(&value["chat"]);
        value
    }
    async fn seed(&self) {
        let stage = self.stage().await; assert_eq!(stage["source"], "canonical");
        let output = self.commit(&stage).await;
        assert_eq!(output["source"], "canonical");
        assert_owned_rows(&output["chat"]);
    }
}
fn decode(value: Result<String>) -> Value {
    serde_json::from_str(&value.unwrap_or_else(|e|panic!("actual bridge {}",e.code))).unwrap()
}
fn assert_owned_rows(chat: &Value) {
    let rows = chat["messages"].as_array().expect("owned synthetic rows");
    assert_eq!(rows.len(), 40, "all owned rows, including older-than-latest20");
    for (offset, row) in rows.iter().enumerate() {
        let index = offset + 1;
        assert_eq!(row["id"], format!("10000000-0000-4000-8000-{index:012}"));
        assert_eq!(row["content"], format!("Synthetic cache row {index:03} 雪"));
        assert_eq!(row["role"], if index % 2 == 1 { "user" } else { "assistant" });
        assert_eq!(row["sender"], "Fixture sender");
        assert_eq!(row["thinking"], "");
        assert_eq!(row["embeds"], json!([]));
    }
}
fn assert_latest20_checkpoint(stage: &Value, chat_id: &str) {
    let checkpoint: Value = serde_json::from_str(stage["checkpoint_json"].as_str().unwrap()).unwrap();
    assert_eq!(checkpoint["history"][chat_id].as_array().unwrap().len(), 40);
    let window = &checkpoint["sync_message_windows"][chat_id];
    let rows = window["messages"].as_array().expect("cache branch latest20 window");
    assert_eq!(rows.len(), 20); assert_eq!(window["server_message_count"], 40);
    assert_eq!(window["has_more_before"], true);
    for (offset, row) in rows.iter().enumerate() {
        assert_eq!(row["client_message_id"], format!("10000000-0000-4000-8000-{:012}", offset + 21));
    }
}
struct Store(PathBuf);
impl Store {
    fn new() -> Self {
        let path = std::env::temp_dir().join(format!("openmates-cache-sdk-test-{}",uuid::Uuid::new_v4()));
        std::fs::create_dir(&path).unwrap();
        #[cfg(unix)] { use std::os::unix::fs::PermissionsExt; std::fs::set_permissions(&path,std::fs::Permissions::from_mode(0o700)).unwrap(); }
        Self(path)
    }
    fn exact_receipt(&self, stage: &Value) -> String {
        for (name,field) in [("ciphertext","checkpoint_json"),("credentials","credentials_json")] {
            let bytes = stage[field].as_str().unwrap().as_bytes();
            let mut options = std::fs::OpenOptions::new(); options.write(true).create_new(true);
            #[cfg(unix)] { use std::os::unix::fs::OpenOptionsExt; options.mode(0o600); }
            let mut file = options.open(self.0.join(name)).unwrap(); file.write_all(bytes).unwrap(); file.sync_all().unwrap();
            assert_eq!(std::fs::read(self.0.join(name)).unwrap(),bytes);
        }
        std::fs::File::open(&self.0).unwrap().sync_all().unwrap();
        let bytes = std::fs::read(self.0.join("ciphertext")).unwrap();
        let actual = format!("{:x}",Sha256::digest(&bytes)); assert_eq!(actual,stage["ciphertext_sha256"]);
        json!({"ciphertext_sha256":actual,"credential_revision":stage["credential_revision"]}).to_string()
    }
}
impl Drop for Store { fn drop(&mut self) { let _ = std::fs::remove_dir_all(&self.0); } }
#[tokio::test]
async fn actual_cache_bridge_correct_exact_store_ack_publishes_original_operation() {
    tokio::time::timeout(Duration::from_secs(20),async {
        let f = Fixture::new().await; f.seed().await;
        let stage = f.stage().await; assert_eq!(stage["source"],"cache_settled");
        let output = f.commit(&stage).await;
        assert_eq!(output["source"],"cache_settled"); assert_eq!(output["cached"],true);
        assert_eq!(output["history_complete"],false); assert!(output["has_more_before"].is_null());
        assert_eq!(output["pii_restoration"],"all_cached_user_rows");
        assert!(!output["chat"]["messages"].as_array().unwrap().is_empty());
        assert_owned_rows(&output["chat"]);
        let repeat = f.bridge.cache_chat_commit(stage["id"].as_str().unwrap().into(),json!({"ciphertext_sha256":stage["ciphertext_sha256"],"credential_revision":stage["credential_revision"]}).to_string()).await.err().unwrap();
        assert_eq!(repeat.code,"conflict");
    }).await.expect("bounded actual cache positive path");
}
#[tokio::test]
async fn actual_stale_stage_a_exact_ack_never_cancels_active_stage_b() {
    tokio::time::timeout(Duration::from_secs(20),async {
        let f = Fixture::new().await; f.seed().await;
        let a = f.stage().await; let b = f.stage().await;
        let store = Store::new();let receipt = store.exact_receipt(&a);
        let error = f.bridge.cache_chat_commit(a["id"].as_str().unwrap().into(),receipt).await.err().expect("stale A rejected");
        assert_eq!(error.code,"cancelled");
        let output = f.commit(&b).await; assert_eq!(output["source"],"cache_settled");
    }).await.expect("bounded stale A / active B isolation");
}
#[tokio::test]
async fn actual_cache_bridge_wrong_ack_preserves_stage_for_correct_exact_ack() {
    tokio::time::timeout(Duration::from_secs(20),async {
        let f = Fixture::new().await; f.seed().await;let stage = f.stage().await;
        let wrong = json!({"ciphertext_sha256":"wrong","credential_revision":stage["credential_revision"]}).to_string();
        assert_eq!(f.bridge.cache_chat_commit(stage["id"].as_str().unwrap().into(),wrong).await.err().unwrap().code,"conflict");
        assert_eq!(f.commit(&stage).await["source"],"cache_settled");
    }).await.expect("bounded correct ACK recovery");
}
#[tokio::test]
async fn actual_cache_monitor_stage_exact_store_ack_commits_without_child_replacement() {
    tokio::time::timeout(Duration::from_secs(25),async {
        let f = Fixture::new().await; f.seed().await;
        let opened = decode(f.bridge.chat_monitor_open().await);let id = opened["id"].as_str().unwrap().to_owned();
        decode(f.bridge.chat_monitor_next(id.clone()).await);
        let stage = decode(f.bridge.chat_monitor_stage_prefer_cache(id.clone(),Some(f.chat.clone()),true).await);
        assert_latest20_checkpoint(&stage, &f.chat);
        let store = Store::new();let receipt = store.exact_receipt(&stage);
        let output = decode(f.bridge.chat_monitor_commit(id.clone(),stage["id"].as_str().unwrap().into(),receipt).await);
        assert_eq!(output["selection"]["kind"],"cache_settled");
        assert_eq!(output["selection"]["history_complete"],false);
        assert_eq!(output["selection"]["pii_restoration"],"all_cached_user_rows");
        assert_owned_rows(&output["selection"]["chat"]);
        f.bridge.chat_monitor_close(id).unwrap_or_else(|e|panic!("close {}",e.code));
    }).await.expect("bounded actual monitor positive path");
}

#[tokio::test]
async fn actual_cache_selected_late_original_cancellation_wipes_encoded_plaintext() {
    tokio::time::timeout(Duration::from_secs(20),async {
        let f = Fixture::new().await; f.seed().await;let stage = f.stage().await;
        assert_eq!(stage["source"], "cache_settled");
        let store = Store::new();let receipt = store.exact_receipt(&stage);
        f.bridge.state.essential.cache_reads.cancel_after_encode.store(true,Ordering::Release);
        let error = f.bridge.cache_chat_commit(stage["id"].as_str().unwrap().into(),receipt).await.err().unwrap();
        assert_eq!(error.code,"cancelled");
        assert!(f.bridge.state.essential.cache_reads.output_wiped.load(Ordering::Acquire));
    }).await.expect("bounded final selected output wiping");
}
#[tokio::test]
async fn actual_cache_monitor_late_original_cancellation_wipes_borrowed_encoded_plaintext() {
    tokio::time::timeout(Duration::from_secs(25),async {
        let f = Fixture::new().await; f.seed().await;
        let opened = decode(f.bridge.chat_monitor_open().await);let id = opened["id"].as_str().unwrap().to_owned();
        decode(f.bridge.chat_monitor_next(id.clone()).await);
        let stage = decode(f.bridge.chat_monitor_stage_prefer_cache(id.clone(),Some(f.chat.clone()),true).await);
        assert_latest20_checkpoint(&stage, &f.chat);
        let store = Store::new();let receipt = store.exact_receipt(&stage);
        f.bridge.state.essential.cache_reads.cancel_monitor_after_encode.store(true,Ordering::Release);
        let error = f.bridge.chat_monitor_commit(id,stage["id"].as_str().unwrap().into(),receipt).await.err().unwrap();
        assert_eq!(error.code,"cancelled");
        assert!(f.bridge.state.essential.cache_reads.monitor_output_wiped.load(Ordering::Acquire));
    }).await.expect("bounded final monitor output wiping");
}
