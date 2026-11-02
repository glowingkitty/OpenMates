//! Actual typed Bridge + owned synthetic peer, authored UNRUN for isolated CI.
//! No inference, real account or local product execution.
use super::*;
use std::{
    io::{BufRead, BufReader, Write},
    path::{Path, PathBuf},
    process::{Child, Command, Stdio},
    sync::mpsc as sync_mpsc,
};
const CAPABILITY: &str = "session.cache-preferred-settlement.v1";
struct Fixture {
    bridge: SessionBridge,
    chat: String,
    child: Child,
    root: PathBuf,
    log: PathBuf,
}
impl Drop for Fixture {
    fn drop(&mut self) {
        let _ = self.child.kill();
        let _ = self.child.wait();
        let _ = std::fs::remove_dir_all(&self.root);
    }
}
fn decode(value: Result<String>) -> Value {
    serde_json::from_str(&value.unwrap_or_else(|error| panic!("{}", error.code))).unwrap()
}
impl Fixture {
    async fn new() -> Self {
        Self::new_mode("uuid").await
    }
    async fn new_mode(message_id_mode: &str) -> Self {
        let repository = Path::new(env!("CARGO_MANIFEST_DIR"))
            .parent()
            .unwrap()
            .parent()
            .unwrap();
        let root =
            std::env::temp_dir().join(format!("openmates-first-page-{}", uuid::Uuid::new_v4()));
        std::fs::create_dir(&root).unwrap();
        #[cfg(unix)]
        {
            use std::os::unix::fs::PermissionsExt;
            std::fs::set_permissions(&root, std::fs::Permissions::from_mode(0o700)).unwrap();
        }
        let log = root.join("requests.jsonl");
        let fixture = repository
            .join("tests/sdk-conformance/fixtures/session-cache-preferred-settlement.json");
        let data: Value = serde_json::from_slice(&std::fs::read(&fixture).unwrap()).unwrap();
        let suite = &data["capabilities"][CAPABILITY];
        let mut child = Command::new(
            std::env::var("OPENMATES_SDK_CONFORMANCE_PYTHON").unwrap_or_else(|_| "python3".into()),
        )
        .arg(repository.join("tests/sdk-conformance/first_page_continuation_peer.py"))
        .arg("--fixture")
        .arg(&fixture)
        .arg("--request-log")
        .arg(&log)
        .args(["--identity", "rust", "--message-id-mode", message_id_mode])
        .current_dir(repository)
        .stdin(Stdio::null())
        .stdout(Stdio::piped())
        .stderr(Stdio::null())
        .spawn()
        .unwrap();
        let stdout = child.stdout.take().unwrap();
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
            child,
            root,
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
            let path = self.root.join(format!("{id}-{field}"));
            let mut file = options.open(&path).unwrap();
            file.write_all(stage[field].as_str().unwrap().as_bytes())
                .unwrap();
            file.sync_all().unwrap();
            assert_eq!(
                std::fs::read_to_string(path).unwrap(),
                stage[field].as_str().unwrap()
            );
        }
        std::fs::File::open(&self.root).unwrap().sync_all().unwrap();
        let stored = std::fs::read(self.root.join(format!("{id}-checkpoint_json"))).unwrap();
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
// contract-test: supporting surface=sdk assertions=sdk.library.explicit-headless,sdk.encryption.local-only
#[tokio::test]
async fn actual_driver_cold_first_page_exact_ack_and_pull_continue_original_history() {
    tokio::time::timeout(Duration::from_secs(25), async {
        let f = Fixture::new().await;
        let id = f.open().await;
        f.accept_capacity(&id).await;
        let stage = f.next(&id).await;
        assert_eq!(stage["kind"], "stage");
        assert_eq!(stage["source"], "first_page");
        let checkpoint: Value =
            serde_json::from_str(stage["checkpoint_json"].as_str().unwrap()).unwrap();
        assert!(checkpoint["history"].get(&f.chat).is_none());
        assert_eq!(
            checkpoint["selected_first_pages"][&f.chat]["messages"]
                .as_array()
                .unwrap()
                .len(),
            100
        );
        assert_eq!(
            f.requests(),
            vec![json!({"direction":"latest","limit":100})]
        );
        let bridge = f.bridge.clone();
        let operation = id.clone();
        let mut pending = tokio::spawn(async move { bridge.first_page_next(operation).await });
        assert!(
            tokio::time::timeout(Duration::from_millis(20), &mut pending)
                .await
                .is_err(),
            "no private page before exact host write ACK"
        );
        f.ack(&id, &stage);
        let first = decode(pending.await.unwrap());
        assert_eq!(first["kind"], "first_page");
        assert_eq!(first["history_complete"], false);
        assert_eq!(first["refreshing"], true);
        assert_eq!(first["pii_restoration"], "page_local");
        assert_eq!(first["chat"]["messages"].as_array().unwrap().len(), 100);
        assert_eq!(
            f.requests(),
            vec![json!({"direction":"latest","limit":100})],
            "first page returned, no older IO until NEXT pull"
        );
        let final_stage = f.next(&id).await;
        assert_eq!(final_stage["source"], "canonical");
        let checkpoint: Value =
            serde_json::from_str(final_stage["checkpoint_json"].as_str().unwrap()).unwrap();
        assert_eq!(
            checkpoint["history"][&f.chat].as_array().unwrap().len(),
            140
        );
        assert!(
            checkpoint
                .get("selected_first_pages")
                .is_none_or(|windows| windows.get(&f.chat).is_none())
        );
        f.ack(&id, &final_stage);
        let done = f.next(&id).await;
        assert_eq!(done["kind"], "completed");
        assert_eq!(done["source"], "canonical");
        assert_eq!(done["history_complete"], true);
        assert_eq!(done["refreshing"], false);
        assert_eq!(done["chat"]["messages"].as_array().unwrap().len(), 140);
        assert_eq!(
            done["chat"]["messages"][0]["content"],
            "Synthetic first-page row 001 雪"
        );
        assert_eq!(
            done["chat"]["messages"][139]["content"],
            "Synthetic first-page row 140 雪"
        );
        assert_eq!(
            f.requests(),
            vec![
                json!({"direction":"latest","limit":100}),
                json!({"direction":"before","limit":100})
            ],
            "same latest response, no duplicate IO"
        );
    })
    .await
    .unwrap();
}
// contract-test: supporting surface=sdk assertions=sdk.library.explicit-headless,sdk.encryption.local-only
#[tokio::test]
async fn actual_driver_stale_close_a_preserves_b_without_resuming_a_older_io() {
    tokio::time::timeout(Duration::from_secs(25),async {
        let f=Fixture::new().await;let a=f.open().await;f.accept_capacity(&a).await;let stage=f.next(&a).await;f.ack(&a,&stage);let first=f.next(&a).await;assert_eq!(first["kind"],"first_page");
        f.bridge.first_page_close(a.clone()).unwrap_or_else(|e|panic!("{}",e.code));
        let b=f.open().await;let stage_b=f.next(&b).await;assert_eq!(stage_b["source"],"cache_settled");
        assert_eq!(f.bridge.first_page_close(a.clone()).err().unwrap().code,"conflict");
        assert_eq!(f.bridge.first_page_receipt(a,stage["id"].as_str().unwrap().into(),json!({"ciphertext_sha256":stage["ciphertext_sha256"],"credential_revision":stage["credential_revision"]}).to_string()).err().unwrap().code,"conflict");
        f.ack(&b,&stage_b);let final_b=f.next(&b).await;assert_eq!(final_b["source"],"cache_settled");assert_eq!(final_b["history_complete"],false);assert_eq!(final_b["chat"]["messages"].as_array().unwrap().len(),100);
        assert_eq!(f.requests(),vec![json!({"direction":"latest","limit":100})]);
    }).await.unwrap();
}

fn logical_id(chat: &str, mode: &str, index: usize) -> String {
    match mode {
        "composite" => format!(
            "{}-10000000-0000-4000-8000-{index:012}",
            &chat.replace("-", "")[..10]
        ),
        "opaque" => format!("legacy_msg_{index:04}"),
        _ => unreachable!(),
    }
}
// contract-test: supporting surface=sdk assertions=sdk.library.explicit-headless,sdk.encryption.local-only
#[tokio::test]
async fn actual_driver_composite_and_opaque_ids_preserve_first_hundred_and_full_hundred_forty_with_exact_cursor()
 {
    tokio::time::timeout(Duration::from_secs(35),async {
        for mode in ["composite","opaque"] {
            let f=Fixture::new_mode(mode).await;let id=f.open().await;f.accept_capacity(&id).await;let stage=f.next(&id).await;
            assert_eq!(stage["source"],"first_page");let checkpoint:Value=serde_json::from_str(stage["checkpoint_json"].as_str().unwrap()).unwrap();let saved=&checkpoint["selected_first_pages"][&f.chat];
            assert_eq!(saved["messages"].as_array().unwrap().len(),100);assert_eq!(saved["start_cursor"]["message_id"],logical_id(&f.chat,mode,41));assert_eq!(saved["messages"][0]["client_message_id"],logical_id(&f.chat,mode,41));assert_eq!(saved["messages"][0]["id"],"10000000-0000-4000-8000-000000000041");
            assert_eq!(f.requests(),vec![json!({"direction":"latest","limit":100})]);
            f.ack(&id,&stage);let first=f.next(&id).await;assert_eq!(first["kind"],"first_page");assert_eq!(first["chat"]["messages"].as_array().unwrap().len(),100);assert_eq!(first["chat"]["messages"][0]["id"],logical_id(&f.chat,mode,41));assert_eq!(first["chat"]["messages"][99]["id"],logical_id(&f.chat,mode,140));assert_eq!(first["history_complete"],false);assert_eq!(first["refreshing"],true);assert_eq!(f.requests().len(),1,"no older IO until next pull");
            let final_stage=f.next(&id).await;assert_eq!(final_stage["source"],"canonical");f.ack(&id,&final_stage);let done=f.next(&id).await;assert_eq!(done["source"],"canonical");assert_eq!(done["history_complete"],true);assert_eq!(done["chat"]["messages"].as_array().unwrap().len(),140);assert_eq!(done["chat"]["messages"][0]["id"],logical_id(&f.chat,mode,1));assert_eq!(done["chat"]["messages"][139]["id"],logical_id(&f.chat,mode,140));
            assert_eq!(f.requests(),vec![json!({"direction":"latest","limit":100}),json!({"direction":"before","limit":100,"cursor_message_id":logical_id(&f.chat,mode,41)})],"exact logical before cursor, no DB substitution or duplicate latest");
        }
    }).await.unwrap();
}
