//! Actual direct SessionBridge draft conformance; only this developer harness
//! starts the independent peer coordinator. Production SDKs never spawn a CLI.
use _native::SessionBridge;
use base64::{Engine, engine::general_purpose::STANDARD};
use serde_json::{Value, json};
use std::{
    io::Read,
    path::PathBuf,
    process::{Command, ExitCode},
};
fn field<'a>(v: &'a Value, key: &str) -> Result<&'a str, &'static str> {
    v[key].as_str().ok_or("Synthetic input field")
}
async fn run_case() -> Result<(), &'static str> {
    let mut bytes = Vec::new();
    std::io::stdin()
        .take(1024 * 1024 + 1)
        .read_to_end(&mut bytes)
        .map_err(|_| "Synthetic input IO")?;
    if bytes.len() > 1024 * 1024 {
        return Err("Synthetic input bound");
    }
    let case: Value = serde_json::from_slice(&bytes).map_err(|_| "Synthetic JSON")?;
    let endpoint = field(&case, "endpoint")?;
    let port = endpoint
        .strip_prefix("http://127.0.0.1:")
        .ok_or("Literal loopback required")?
        .parse::<u16>()
        .map_err(|_| "Loopback port")?;
    if port == 0 {
        return Err("Loopback port required");
    }
    let suite = &case["suite"];
    let v = &case["vector"];
    if suite["account"]["cookie"] != "synthetic-cookie"
        || suite["account"]["session_id"] != "synthetic-session"
    {
        return Err("Synthetic session only");
    }
    let bridge=SessionBridge::new(&json!({"api_url":endpoint,"app_url":suite["protocol"]["app_origin"],"enhanced_privacy":false,"allow_private_operations":v["mode"]!="policy-denied"}).to_string()).map_err(|_|"Bridge construct")?;
    if v["mode"] != "noauth" {
        let master = if v["mode"] == "wrong-key" {
            json!(STANDARD.encode([2; 32]))
        } else {
            suite["account"]["master_key"].clone()
        };
        let session = json!({"api_url":endpoint,"session_id":suite["account"]["session_id"],"cookies":{"auth_refresh_token":suite["account"]["cookie"]},"ws_token":null,"master_key":master,"hashed_email":suite["account"]["hashed_email"],"user_email_salt":"","email_encryption_key":null,"created_at":1,"paired_session_expires_at":null,"active_team_id":if v["mode"]=="team"{suite["protocol"]["team_id"].clone()}else{Value::Null}});
        bridge
            .import_session(session.to_string())
            .await
            .map_err(|_| "Explicit synthetic import")?;
    }
    let id = field(&suite["protocol"], "chat_id")?.to_owned();
    if v["preflight_get"] == true {
        let raw = bridge
            .drafts_get(id.clone(), r#"{"force_refresh":true}"#.into())
            .await
            .map_err(|_| "Preflight get")?;
        let actual: Value = serde_json::from_str(&raw).map_err(|_| "Preflight JSON")?;
        if actual != suite["records"]["base"] {
            return Err("Preflight exact draft");
        }
    }
    let options = v["options"].to_string();
    let result = match field(v, "operation")? {
        "cached-list" => bridge.drafts_list_cached().await,
        "get" => bridge.drafts_get(id, options).await,
        "list" => bridge.drafts_list(options).await,
        "sync" => bridge.drafts_sync().await,
        _ => return Err("Unknown draft operation"),
    };
    let output = match result {
        Ok(raw) => {
            json!({"ok":true,"value":serde_json::from_str::<Value>(&raw).map_err(|_|"Draft JSON")?})
        }
        Err(error) => json!({"ok":false,"error":error.code}),
    };
    bridge.close().await.map_err(|_| "Bridge close")?;
    println!("{output}");
    Ok(())
}
#[tokio::main]
async fn main() -> ExitCode {
    let args = std::env::args().skip(1).collect::<Vec<_>>();
    if args.len() == 1 && args[0] == "--case" {
        return if run_case().await.is_ok() {
            ExitCode::SUCCESS
        } else {
            eprintln!("Session draft fixture failed");
            ExitCode::FAILURE
        };
    }
    let root = PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../..");
    let executable = match std::env::current_exe() {
        Ok(path) => path,
        Err(_) => return ExitCode::FAILURE,
    };
    let python =
        std::env::var("OPENMATES_SDK_CONFORMANCE_PYTHON").unwrap_or_else(|_| "python3".into());
    let status = Command::new(python)
        .arg(root.join("tests/sdk-conformance/runners/session-drafts.py"))
        .args(["--language", "rust", "--rust-executable"])
        .arg(executable)
        .args(args)
        .current_dir(root)
        .status();
    if status.is_ok_and(|v| v.success()) {
        ExitCode::SUCCESS
    } else {
        eprintln!("Session draft conformance failed");
        ExitCode::FAILURE
    }
}
