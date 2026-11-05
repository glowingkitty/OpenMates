//! AUTHORED UNRUN direct Rust SessionBridge; subprocess exists only in this fixture.
use _native::SessionBridge;
use openmates_sdk::work::ProjectFilters;
use serde_json::{Value, json};
use std::{
    io::{Read, Write},
    net::TcpStream,
    path::PathBuf,
    process::{Command, ExitCode},
    time::Duration,
};
type Check<T> = Result<T, &'static str>;
fn text<'a>(v: &'a Value, k: &str) -> Check<&'a str> {
    v[k].as_str().ok_or("Synthetic fixture field")
}
fn control(endpoint: &str, release: bool) -> Check<Value> {
    let port = endpoint
        .strip_prefix("http://127.0.0.1:")
        .ok_or("Literal loopback")?
        .parse::<u16>()
        .map_err(|_| "Loopback port")?;
    if port == 0 {
        return Err("Ephemeral port");
    }
    let mut socket = TcpStream::connect(("127.0.0.1", port)).map_err(|_| "Control connect")?;
    socket
        .set_read_timeout(Some(Duration::from_secs(2)))
        .map_err(|_| "Control timeout")?;
    socket
        .set_write_timeout(Some(Duration::from_secs(2)))
        .map_err(|_| "Control timeout")?;
    let request = if release {
        "POST /__test/release HTTP/1.1\r\nHost: 127.0.0.1\r\nContent-Length: 2\r\nConnection: close\r\n\r\n{}"
    } else {
        "GET /__test/status HTTP/1.1\r\nHost: 127.0.0.1\r\nConnection: close\r\n\r\n"
    };
    socket
        .write_all(request.as_bytes())
        .map_err(|_| "Control write")?;
    let mut raw = String::new();
    socket
        .take(1024 * 1024)
        .read_to_string(&mut raw)
        .map_err(|_| "Control body")?;
    if !(raw.starts_with("HTTP/1.0 200") || raw.starts_with("HTTP/1.1 200")) {
        return Err("Control status");
    }
    serde_json::from_str(raw.split_once("\r\n\r\n").ok_or("Control headers")?.1)
        .map_err(|_| "Control JSON")
}
async fn run_case() -> Check<()> {
    let mut bytes = Vec::new();
    std::io::stdin()
        .take(1024 * 1024 + 1)
        .read_to_end(&mut bytes)
        .map_err(|_| "Fixture stdin")?;
    if bytes.len() > 1024 * 1024 {
        return Err("Fixture bound");
    }
    let case: Value = serde_json::from_slice(&bytes).map_err(|_| "Fixture JSON")?;
    let endpoint = text(&case, "endpoint")?;
    let port = endpoint
        .strip_prefix("http://127.0.0.1:")
        .ok_or("Literal loopback")?
        .parse::<u16>()
        .map_err(|_| "Loopback port")?;
    if port == 0 {
        return Err("Ephemeral port");
    }
    let s = &case["suite"];
    let v = &case["vector"];
    if s["account"]["cookie"] != "synthetic-cookie"
        || s["account"]["session_id"] != "synthetic-session"
    {
        return Err("Synthetic credentials only");
    }
    let bridge=SessionBridge::new(&json!({"api_url":endpoint,"app_url":s["app_origin"],"enhanced_privacy":false,"allow_private_operations":v["mode"]!="policy-denied"}).to_string()).map_err(|_|"Bridge construct")?;
    if v["mode"] != "noauth" {
        bridge.import_session(json!({"api_url":endpoint,"session_id":s["account"]["session_id"],"cookies":{"auth_refresh_token":s["account"]["cookie"]},"ws_token":null,"master_key":if v["mode"]=="wrong-master"{json!("AgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgI=")}else{s["account"]["master_key"].clone()},"hashed_email":s["account"]["hashed_email"],"user_email_salt":"","email_encryption_key":null,"created_at":1,"paired_session_expires_at":null,"active_team_id":null}).to_string()).await.map_err(|_|"Explicit import")?;
    }
    let approved: Vec<String> = serde_json::from_value(
        v.get("approved_paths")
            .cloned()
            .unwrap_or_else(|| json!([s["path"]])),
    )
    .map_err(|_| "Approval fixture")?;
    let filters = ProjectFilters {
        personal: true,
        team_id: if v["mode"] == "bad-scope" {
            Some(text(s, "team_id")?.into())
        } else {
            None
        },
        ..Default::default()
    };
    let owned = bridge.clone();
    let id = text(s, "workflow_id")?.to_owned();
    let version = text(s, "expected_version")?.to_owned();
    let pending = tokio::spawn(async move {
        owned
            .projects_sync_workflow_files(id, version, None, approved, filters)
            .await
    });
    if v["mode"] == "cancel-held" {
        let deadline = tokio::time::Instant::now() + Duration::from_secs(5);
        while control(endpoint, false)?["blocked"] != true {
            if tokio::time::Instant::now() >= deadline {
                return Err("Held beacon deadline");
            };
            tokio::time::sleep(Duration::from_millis(20)).await;
        }
        bridge.cancel().map_err(|_| "Original cancellation")?;
        control(endpoint, true)?;
    }
    let result = pending.await.map_err(|_| "Actual original task")?;
    let observed = match result {
        Ok(raw) => {
            json!({"ok":true,"value":serde_json::from_str::<Value>(&raw).map_err(|_|"Native JSON")?})
        }
        Err(error) => json!({"ok":false,"error":error.code}),
    };
    bridge.close().await.map_err(|_| "Bridge close")?;
    println!("{observed}");
    Ok(())
}
#[tokio::main]
async fn main() -> ExitCode {
    let args = std::env::args().skip(1).collect::<Vec<_>>();
    if args.len()==1 && args[0]=="--case" {
        return if run_case().await.is_ok() {
            ExitCode::SUCCESS
        } else {
            eprintln!("Workflow file fixture failed");
            ExitCode::FAILURE
        };
    }
    let root = PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../..");
    let executable = match std::env::current_exe() {
        Ok(v) => v,
        Err(_) => return ExitCode::FAILURE,
    };
    let python =
        std::env::var("OPENMATES_SDK_CONFORMANCE_PYTHON").unwrap_or_else(|_| "python3".into());
    let status = Command::new(python)
        .arg(root.join("tests/sdk-conformance/runners/workflow-file-sync.py"))
        .args(["--language", "rust", "--rust-executable"])
        .arg(executable)
        .args(args)
        .current_dir(root)
        .status();
    if status.is_ok_and(|v| v.success()) {
        ExitCode::SUCCESS
    } else {
        eprintln!("Workflow file conformance failed");
        ExitCode::FAILURE
    }
}
