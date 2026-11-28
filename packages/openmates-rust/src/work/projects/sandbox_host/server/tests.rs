//! HTTP-level tests of the sandbox host daemon: bearer on every endpoint, key
//! handover with a synthetic key, file-ids, sync-in, op, merge and scan over a
//! real socket, and that no response leaks the key or file plaintext.
use super::*;
use crate::work::projects::sandbox_host::tests_support::*;
use crate::work::projects::sandbox_host::{HostedIdentityKind, hosted_file_identity, seal};
use crate::work::sandbox_key::{SandboxKeyRequest, seal_project_key_grant};
use base64::Engine;
use base64::engine::general_purpose::STANDARD;
use serde_json::{Value, json};
use tokio::io::{AsyncReadExt, AsyncWriteExt};

const TOKEN: &str = "test-bearer-token";
const SANDBOX: &str = "sbx-1";
const JOB: &str = "job-1";

struct Server {
    addr: std::net::SocketAddr,
    dir: tempfile::TempDir,
    bodies: std::sync::Mutex<Vec<String>>,
}

async fn start() -> Server {
    let dir = tempfile::tempdir().unwrap();
    let host = Arc::new(Host::new(HostConfig {
        token: zeroize::Zeroizing::new(TOKEN.to_owned()),
        sandbox_id: SANDBOX.into(),
        job_id: JOB.into(),
        project_id: PROJECT.into(),
        chat_id: CHAT.into(),
        team_id: None,
        project_dir: dir.path().join("project"),
        run_user: None,
    }));
    let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
    let addr = listener.local_addr().unwrap();
    tokio::spawn(serve(listener, host));
    Server {
        addr,
        dir,
        bodies: Default::default(),
    }
}

impl Server {
    async fn call(
        &self,
        method: &str,
        path: &str,
        token: Option<&str>,
        body: &Value,
    ) -> (u16, Value) {
        let mut stream = tokio::net::TcpStream::connect(self.addr).await.unwrap();
        let payload = body.to_string();
        let auth = token.map_or(String::new(), |t| format!("Authorization: Bearer {t}\r\n"));
        let request = format!(
            "{method} {path} HTTP/1.1\r\nHost: x\r\n{auth}Content-Type: application/json\r\nContent-Length: {}\r\n\r\n{payload}",
            payload.len()
        );
        stream.write_all(request.as_bytes()).await.unwrap();
        let mut raw = Vec::new();
        stream.read_to_end(&mut raw).await.unwrap();
        let text = String::from_utf8(raw).unwrap();
        let status = text[9..12].parse().unwrap();
        let body = text.split("\r\n\r\n").nth(1).unwrap_or("{}").to_owned();
        self.bodies.lock().unwrap().push(body.clone());
        (status, serde_json::from_str(&body).unwrap_or(Value::Null))
    }

    async fn ok(&self, method: &str, path: &str, body: Value) -> Value {
        let (status, value) = self.call(method, path, Some(TOKEN), &body).await;
        assert_eq!(status, 200, "{path}: {value}");
        value
    }

    fn project_file(&self, path: &str) -> std::path::PathBuf {
        self.dir.path().join("project").join(path)
    }
}

fn raw_head(path: &str, text: &str, version: u64) -> Value {
    let mut value = head(path, text, version);
    let object = value.as_object_mut().unwrap();
    object.remove("path");
    object.remove("project_item_id");
    value
}

fn item(path: &str) -> Value {
    let key = project_key();
    json!({
        "item_type": "embed",
        "project_item_id": hosted_file_identity(&key, path, HostedIdentityKind::Item).unwrap(),
        "target_id_encrypted": seal(&embed_id(path), &key).unwrap(),
        "encrypted_metadata": seal(&json!({"path": path, "source": "hosted"}).to_string(), &key).unwrap(),
    })
}

fn key_request(public_key: &str, job: &str) -> SandboxKeyRequest {
    SandboxKeyRequest {
        request_id: "req-1".into(),
        job_id: job.into(),
        sandbox_id: SANDBOX.into(),
        project_id: PROJECT.into(),
        chat_id: CHAT.into(),
        sandbox_public_key: public_key.into(),
        expires_at: std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .unwrap()
            .as_secs() as i64
            + 600,
    }
}

const ENDPOINTS: [(&str, &str); 9] = [
    ("GET", "/v1/hello"),
    ("POST", "/v1/key"),
    ("POST", "/v1/file-ids"),
    ("POST", "/v1/sync-in"),
    ("POST", "/v1/baseline"),
    ("POST", "/v1/op"),
    ("POST", "/v1/scan"),
    ("POST", "/v1/committed"),
    ("POST", "/v1/merge"),
];

#[tokio::test]
async fn every_endpoint_requires_the_bearer_token() {
    let server = start().await;
    for (method, path) in ENDPOINTS {
        for token in [None, Some("wrong"), Some("test-bearer-toke")] {
            let (status, body) = server.call(method, path, token, &json!({})).await;
            assert_eq!(
                (status, body["error"].as_str()),
                (401, Some("unauthorized")),
                "{path}"
            );
        }
    }
}

#[tokio::test]
async fn needs_the_key_before_tree_endpoints() {
    let server = start().await;
    let hello = server.ok("GET", "/v1/hello", json!({})).await;
    assert_eq!(hello["has_key"], false);
    assert_eq!(hello["project_id"], PROJECT);
    for path in [
        "/v1/op",
        "/v1/file-ids",
        "/v1/sync-in",
        "/v1/baseline",
        "/v1/scan",
    ] {
        let (status, body) = server.call("POST", path, Some(TOKEN), &json!({})).await;
        assert_eq!(
            (status, body["error"].as_str()),
            (409, Some("no_key")),
            "{path}"
        );
    }
}

#[tokio::test]
async fn full_flow_never_leaks_key_or_plaintext() {
    let server = start().await;
    let hello = server.ok("GET", "/v1/hello", json!({})).await;
    let public = hello["sandbox_public_key"].as_str().unwrap().to_owned();
    let now = key_request(&public, JOB).expires_at - 600;

    let wrong =
        seal_project_key_grant(&key_request(&public, "other-job"), &project_key(), now).unwrap();
    let (status, body) = server
        .call(
            "POST",
            "/v1/key",
            Some(TOKEN),
            &json!({"sealed_grant": wrong}),
        )
        .await;
    assert_eq!(
        (status, body["error"].as_str()),
        (409, Some("binding_mismatch"))
    );
    let (status, body) = server
        .call(
            "POST",
            "/v1/key",
            Some(TOKEN),
            &json!({"sealed_grant": "AAAA"}),
        )
        .await;
    assert_eq!((status, body["error"].as_str()), (400, Some("open_failed")));

    let grant = seal_project_key_grant(&key_request(&public, JOB), &project_key(), now).unwrap();
    assert_eq!(
        server
            .ok("POST", "/v1/key", json!({"sealed_grant": grant}))
            .await["ok"],
        true
    );
    let (status, body) = server
        .call(
            "POST",
            "/v1/key",
            Some(TOKEN),
            &json!({"sealed_grant": grant}),
        )
        .await;
    assert_eq!((status, body["error"].as_str()), (409, Some("already_set")));
    assert_eq!(
        server.ok("GET", "/v1/hello", json!({})).await["has_key"],
        true
    );

    let base = ten_lines();
    let ids = server
        .ok(
            "POST",
            "/v1/file-ids",
            json!({"items": [item("f.txt"), item("g.txt")]}),
        )
        .await;
    assert_eq!(
        ids["embed_ids"],
        json!([embed_id("f.txt"), embed_id("g.txt")])
    );
    let synced = server
        .ok("POST", "/v1/sync-in", json!({"heads": [
            raw_head("f.txt", &base, 1), raw_head("g.txt", "gee", 1), raw_head("stray.txt", "SECRET-PLAINTEXT", 1)]}))
        .await;
    assert_eq!(
        (
            synced["written"].as_u64(),
            synced["failed"][0]["reason"].as_str()
        ),
        (Some(2), Some("unknown_embed"))
    );
    assert_eq!(
        std::fs::read_to_string(server.project_file("f.txt")).unwrap(),
        base
    );
    let baseline = server.ok("POST", "/v1/baseline", json!({})).await;
    assert_eq!(baseline["files"], 2);
    assert!(server.project_file(".git").exists());

    let created = server
        .ok("POST", "/v1/op", json!({"operation": "create_file", "arguments": {"path": "new.txt", "content": "SECRET-PLAINTEXT"}}))
        .await;
    let revisions = created["revisions"].as_array().unwrap();
    assert_eq!(
        (revisions.len(), revisions[0]["kind"].as_str()),
        (1, Some("create"))
    );
    let refused = server
        .ok(
            "POST",
            "/v1/op",
            json!({"operation": "read_text", "arguments": {"path": "missing.txt"}}),
        )
        .await;
    assert_eq!(refused["result"]["code"], "file_not_found");
    let embed = revisions[0]["embed_id"].as_str().unwrap();
    server
        .ok(
            "POST",
            "/v1/committed",
            json!({"path": "new.txt", "embed_id": embed, "version_number": 1}),
        )
        .await;

    std::fs::write(
        server.project_file("f.txt"),
        base.replace("line 1\n", "mine 1\n"),
    )
    .unwrap();
    let theirs = base.replace("line 10", "theirs 10");
    let merged = server
        .ok(
            "POST",
            "/v1/merge",
            json!({"path": "f.txt", "head": raw_head("f.txt", &theirs, 2)}),
        )
        .await;
    assert_eq!(merged["status"], "merged");
    assert!(merged["revision"]["transaction"].is_object());
    std::fs::write(server.project_file("g.txt"), "gee changed").unwrap();
    let scan = server.ok("POST", "/v1/scan", json!({})).await;
    assert_eq!(scan["revisions"][0]["path"], "g.txt");

    let key = project_key();
    let needles = [
        STANDARD.encode(key),
        key.iter().map(|b| format!("{b:02x}")).collect::<String>(),
        grant,
    ];
    for body in server.bodies.lock().unwrap().iter() {
        for needle in &needles {
            assert!(
                !body.contains(needle.as_str()),
                "key material in a response"
            );
        }
        assert!(
            !body.contains("SECRET-PLAINTEXT"),
            "plaintext in a response"
        );
    }
}
