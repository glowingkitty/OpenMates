//! Fixed synthetic direct-SDK adapter. Production SDK never launches a CLI.
use openmates_sdk::{ApiKey, ClientOptions, Error, OpenMates, SdkCredentials, SdkOptions};
use serde_json::{Value, json};
use std::{
    io::Read,
    path::PathBuf,
    process::{Command, ExitCode},
};
async fn run_case() -> Result<(), &'static str> {
    let mut bytes = Vec::new();
    std::io::stdin()
        .take(1024 * 1024 + 1)
        .read_to_end(&mut bytes)
        .map_err(|_| "input")?;
    if bytes.len() > 1024 * 1024 {
        return Err("inputbound");
    }
    let c: Value = serde_json::from_slice(&bytes).map_err(|_| "json")?;
    let endpoint = c["endpoint"].as_str().ok_or("endpoint")?;
    let port = endpoint
        .strip_prefix("http://127.0.0.1:")
        .ok_or("literal loopback")?
        .parse::<u16>()
        .map_err(|_| "port")?;
    if port == 0 {
        return Err("port");
    }
    let s = &c["suite"];
    let v = &c["vector"];
    if s["api_key"] != "sk-api-embedOwnerA.localSetupSuffix"
        || s["device_id"] != "synthetic-embed-device"
    {
        return Err("syntheticonly");
    }
    let key = ApiKey::new(s["api_key"].as_str().ok_or("key")?).map_err(|_| "credential")?;
    let mut client = OpenMates::new(SdkOptions {
        api_url: endpoint.into(),
        credentials: SdkCredentials::ApiKey(key),
        device_id: s["device_id"].as_str().ok_or("device")?.into(),
        client_options: ClientOptions::default(),
    })
    .map_err(|_| "client")?;
    let result = client
        .embeds()
        .version_content(
            v["embed_id"].as_str().ok_or("embed")?,
            v["version"].as_i64().ok_or("version")?,
        )
        .await;
    let out = match result {
        Ok(value) => json!({"ok":true,"value":value}),
        Err(e) => {
            json!({"ok":false,"error":match e{Error::Invalid(_)=>"invalid_argument",Error::Crypto=>"crypto",Error::Authentication=>"authentication",Error::Forbidden=>"forbidden",Error::Conflict=>"conflict",Error::Offline=>"offline",Error::Cancelled=>"cancelled",_=>"protocol"}})
        }
    };
    println!("{out}");
    Ok(())
}
#[tokio::main]
async fn main() -> ExitCode {
    let args = std::env::args().skip(1).collect::<Vec<_>>();
    if args.len() == 1 && args[0] == "--case" {
        return if run_case().await.is_ok() {
            ExitCode::SUCCESS
        } else {
            eprintln!("Version fixture refused");
            ExitCode::FAILURE
        };
    }
    let root = PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../..");
    let executable = match std::env::current_exe() {
        Ok(p) => p,
        Err(_) => return ExitCode::FAILURE,
    };
    let result = Command::new(
        std::env::var("OPENMATES_SDK_CONFORMANCE_PYTHON").unwrap_or_else(|_| "python3".into()),
    )
    .arg(root.join("tests/sdk-conformance/runners/sdk-embed-version-content.py"))
    .args(["--language", "rust", "--rust-executable"])
    .arg(executable)
    .args(args)
    .current_dir(root)
    .status();
    if result.is_ok_and(|r| r.success()) {
        ExitCode::SUCCESS
    } else {
        ExitCode::FAILURE
    }
}
