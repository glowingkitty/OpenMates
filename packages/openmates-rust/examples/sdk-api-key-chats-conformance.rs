//! Synthetic developer harness only. Production SDK code never starts a process.
//! Default mode runs the independent shared oracle with this compiled executable;
//! --case calls the real Rust library with one pipe-provided synthetic credential.
// contract-test-file: tooling
use openmates_sdk::{
    ApiKey, ClientOptions, Error, OpenMates, SdkCredentials, SdkOptions, sdk_chats::ChatListOptions,
};
use serde_json::{Value, json};
use std::{
    io::Read,
    path::PathBuf,
    process::{Command, ExitCode},
};
fn field<'a>(value: &'a Value, key: &str) -> Result<&'a str, &'static str> {
    value[key].as_str().ok_or("synthetic field")
}
fn code(error: Error) -> &'static str {
    match error {
        Error::Authentication => "authentication",
        Error::Forbidden => "forbidden",
        Error::Conflict => "conflict",
        Error::Invalid(_) => "invalid",
        Error::Offline => "offline",
        Error::Cancelled => "cancelled",
        _ => "protocol",
    }
}
async fn run_case() -> Result<(), &'static str> {
    let mut bytes = vec![];
    std::io::stdin()
        .take(1024 * 1024 + 1)
        .read_to_end(&mut bytes)
        .map_err(|_| "fixture input")?;
    if bytes.len() > 1024 * 1024 {
        return Err("fixture bound");
    }
    let case: Value = serde_json::from_slice(&bytes).map_err(|_| "fixture JSON")?;
    let endpoint = field(&case, "endpoint")?;
    let url = url::Url::parse(endpoint).map_err(|_| "loopback URL")?;
    if url.scheme() != "http"
        || url.host_str() != Some("127.0.0.1")
        || url.port().is_none()
        || url.path() != "/"
        || url.query().is_some()
        || url.fragment().is_some()
        || !url.username().is_empty()
        || url.password().is_some()
    {
        return Err("loopback endpoint");
    }
    let key = field(&case, "api_key")?;
    if key != "sk-api-chatOwnerA.localSetupSuffix"
        || field(&case, "device_id")? != "synthetic-chat-device"
    {
        return Err("synthetic identity");
    }
    let mut client = OpenMates::new(SdkOptions {
        api_url: endpoint.into(),
        credentials: SdkCredentials::ApiKey(ApiKey::new(key).map_err(|_| "synthetic key")?),
        device_id: field(&case, "device_id")?.into(),
        client_options: ClientOptions::default(),
    })
    .map_err(|_| "client options")?;
    let v = &case["vector"];
    let a = &v["arguments"];
    let page = |name: &str, default: u32| -> Result<u32, &'static str> {
        match &a[name] {
            Value::Null => Ok(default),
            value => value.as_u64().and_then(|n| u32::try_from(n).ok()).ok_or("synthetic page"),
        }
    };
    let options = ChatListOptions { limit: page("limit", 10)?, offset: page("offset", 0)? };
    let result = match field(v, "operation")? {
        "list" => client.chats().list(options).await.map(Value::from),
        "search" => client.chats().search(field(a, "query")?, options).await.map(Value::from),
        "load" => client.chats().load(field(a, "chat_id")?).await,
        _ => return Err("chats operation"),
    };
    let output = match result {
        Ok(value) => json!({"ok":true,"value":value}),
        Err(error) => json!({"ok":false,"error":code(error)}),
    };
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
            eprintln!("Rust chats fixture failed");
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
        .arg(root.join("tests/sdk-conformance/runners/sdk-api-key-chats.py"))
        .args(["--language", "rust", "--rust-executable"])
        .arg(executable)
        .args(args)
        .current_dir(root)
        .status();
    if status.is_ok_and(|status| status.success()) {
        ExitCode::SUCCESS
    } else {
        eprintln!("Rust chats conformance failed");
        ExitCode::FAILURE
    }
}
