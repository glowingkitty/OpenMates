//! Actual synthetic loopback HTTP/WebSocket peer and real SessionBridge calls.
//! Authored for isolated CI; these are not fake-native facade forwarding tests.
use _native::{SessionBridge, BindingError};
use serde_json::{json, Value};
use sha2::{Sha256, Digest};
use std::{io::{BufRead, BufReader, Write}, path::{Path, PathBuf}, process::{Child, Command, Stdio}, sync::mpsc, time::Duration};
const CAP: &str = "session.cache-preferred-settlement.v1";
struct Peer { child: Child, endpoint: String }
impl Peer {
    fn start(root: &Path, fixture: &Path, vector: &str) -> Self {
        let mut child = Command::new(std::env::var("OPENMATES_SDK_CONFORMANCE_PYTHON").unwrap_or_else(|_| "python3".into()))
            .arg(root.join("tests/sdk-conformance/cache_settlement_peer.py"))
            .args(["--fixture", fixture.to_str().unwrap(), "--capability", CAP, "--vector", vector, "--identity", "rust"])
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
    async fn new(fixture: &Path, vector: &str) -> Self {
        let root = Path::new(env!("CARGO_MANIFEST_DIR")).parent().unwrap().parent().unwrap();
        let data: Value = serde_json::from_slice(&std::fs::read(fixture).unwrap()).unwrap();
        let suite = &data["capabilities"][CAP];
        let peer = Peer::start(root, fixture, vector);
        let bridge = SessionBridge::new(&json!({"api_url":peer.endpoint,"app_url":suite["protocol"]["app_origin"],"enhanced_privacy":false,"allow_private_operations":true}).to_string()).unwrap_or_else(|e| panic!("construct {}",e.code));
        bridge.import_session(json!({"api_url":peer.endpoint,"session_id":suite["account"]["session_id"],"cookies":{"auth_refresh_token":suite["account"]["cookie"]},"ws_token":null,"master_key":suite["account"]["master_key"],"hashed_email":"synthetic-email-hash","user_email_salt":"synthetic-salt","email_encryption_key":null,"created_at":1,"paired_session_expires_at":null,"active_team_id":null}).to_string()).await.unwrap_or_else(|e|panic!("import {}",e.code));
        bridge.validate_session().await.unwrap_or_else(|e|panic!("validate {}",e.code));
        Self { bridge, chat: suite["protocol"]["initial_chat_id"].as_str().unwrap().to_owned(), _peer: peer }
    }
    async fn stage(&self) -> Value { decode(self.bridge.cache_chat_stage(self.chat.clone(), true).await) }
    async fn commit(&self, stage: &Value) -> Value {
        let store = Store::new(); let receipt = store.exact_receipt(stage);
        decode(self.bridge.cache_chat_commit(stage["id"].as_str().unwrap().into(), receipt).await)
    }
    async fn seed(&self) {
        let stage = self.stage().await; assert_eq!(stage["source"], "canonical");
        assert_eq!(self.commit(&stage).await["source"], "canonical");
    }
}
fn decode(value: Result<String, BindingError>) -> Value {
    serde_json::from_str(&value.unwrap_or_else(|e|panic!("actual bridge {}",e.code))).unwrap()
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
fn output(value: &Value, canonical: bool) {
    assert_eq!(value["source"],if canonical {"canonical"} else {"cache_settled"});
    assert_eq!(value["history_complete"],canonical);assert_eq!(value["cached"],!canonical);
    assert_eq!(value["refreshing"],false);
    assert_eq!(value["pii_restoration"],if canonical {"all_user_rows"} else {"all_cached_user_rows"});
    assert!(!value["chat"]["messages"].as_array().unwrap().is_empty());
    assert_owned_rows(&value["chat"]);
    if !canonical {assert!(value["has_more_before"].is_null());}
}
fn code(result: Result<String,BindingError>, expected: &str) {
    assert_eq!(result.err().expect("expected native refusal").code,expected);
}
async fn vector(fixture: &Path, entry: &Value) -> Value {
    let id=entry["id"].as_str().unwrap();let mode=entry["mode"].as_str().unwrap();
    let f=Fixture::new(fixture,id).await;
    let seed=f.stage().await;assert_eq!(seed["source"],"canonical");output(&f.commit(&seed).await,true);
    if mode=="explicit-consent" {
        let error=f.bridge.cache_chat_stage(f.chat.clone(),false).await.err().expect("explicit consent refused");
        assert!(error.code == "invalid_argument");
    } else if mode=="selected-denied" {
        // Explicit synthetic loopback peer control; never a product endpoint.
        use std::io::Read;
        let address=f._peer.endpoint.strip_prefix("http://").unwrap();
        let mut stream=std::net::TcpStream::connect(address).unwrap();
        stream.set_read_timeout(Some(Duration::from_secs(2))).unwrap();
        stream.set_write_timeout(Some(Duration::from_secs(2))).unwrap();
        write!(stream,"GET /__test/control?action=deny HTTP/1.1\r\nHost: {}\r\nConnection: close\r\n\r\n",address).unwrap();
        let mut response=String::new();stream.take(65536).read_to_string(&mut response).unwrap();
        assert!(response.starts_with("HTTP/1.0 200") || response.starts_with("HTTP/1.1 200"));
        code(f.bridge.cache_chat_stage(f.chat.clone(),true).await,"forbidden");
    } else if mode=="monitor-exact-ack" {
        let opened=decode(f.bridge.chat_monitor_open().await);let monitor=opened["id"].as_str().unwrap().to_owned();
        decode(f.bridge.chat_monitor_next(monitor.clone()).await);
        let stage=decode(f.bridge.chat_monitor_stage_prefer_cache(monitor.clone(),Some(f.chat.clone()),true).await);
        let store=Store::new();let receipt=store.exact_receipt(&stage);
        let value=decode(f.bridge.chat_monitor_commit(monitor.clone(),stage["id"].as_str().unwrap().into(),receipt).await);
        assert_eq!(value["selection"]["kind"],"cache_settled");assert_eq!(value["selection"]["history_complete"],false);
        assert_eq!(value["selection"]["pii_restoration"],"all_cached_user_rows");
        assert_owned_rows(&value["selection"]["chat"]);
        f.bridge.chat_monitor_close(monitor).unwrap_or_else(|_|panic!("close monitor"));
    } else {
        let mut stage=f.stage().await;assert_eq!(stage["source"],"cache_settled");
        let store=Store::new();let mut receipt=store.exact_receipt(&stage);
        let mut successor_store=None;
        if mode.starts_with("selected-wrong-") {
            let mut wrong:Value=serde_json::from_str(&receipt).unwrap();
            if mode.ends_with("hash") {wrong["ciphertext_sha256"]=json!("0".repeat(64));}
            else {wrong["credential_revision"]=json!(wrong["credential_revision"].as_u64().unwrap()+1);}
            code(f.bridge.cache_chat_commit(stage["id"].as_str().unwrap().into(),wrong.to_string()).await,"conflict");
        } else if mode=="stale-a-active-b" {
            let other=f.stage().await;
            code(f.bridge.cache_chat_commit(stage["id"].as_str().unwrap().into(),receipt).await,"cancelled");
            successor_store=Some(Store::new());receipt=successor_store.as_ref().unwrap().exact_receipt(&other);stage=other;
        } else if mode=="discarded-stage" {
            f.bridge.cache_chat_discard(stage["id"].as_str().unwrap().into()).unwrap_or_else(|_|panic!("discard stage"));
            code(f.bridge.cache_chat_commit(stage["id"].as_str().unwrap().into(),receipt).await,"conflict");
            f.bridge.close().await.unwrap_or_else(|_|panic!("close client"));
            return json!({"id":id,"status":"passed"});
        }
        let _retain_successor_store = &successor_store;
        output(&decode(f.bridge.cache_chat_commit(stage["id"].as_str().unwrap().into(),receipt.clone()).await),false);
        code(f.bridge.cache_chat_commit(stage["id"].as_str().unwrap().into(),receipt).await,"conflict");
    }
    f.bridge.close().await.unwrap_or_else(|_|panic!("close client"));
    json!({"id":id,"status":"passed"})
}
#[tokio::main]
async fn main() {
    let result=tokio::time::timeout(Duration::from_secs(200),async {
        let args:Vec<String>=std::env::args().collect();
        let option=|name:&str| args[args.iter().position(|v|v==name).expect("required option")+1].clone();
        assert_eq!(option("--capability"),CAP);let fixture=PathBuf::from(option("--fixture"));
        let raw=std::fs::read(&fixture).unwrap();let data:Value=serde_json::from_slice(&raw).unwrap();
        let mut results=Vec::new();
        for entry in data["capabilities"][CAP]["vectors"].as_array().unwrap() {
            results.push(tokio::time::timeout(Duration::from_secs(25),vector(&fixture,entry)).await.expect("bounded cache vector"));
        }
        println!("{}",json!({"capability":CAP,"language":"rust","status":"passed","fixtureSha256":format!("{:x}",Sha256::digest(&raw)),"results":results}));
    }).await;
    if result.is_err(){eprintln!("Cache settlement Rust conformance failed");std::process::exit(1);}
}
