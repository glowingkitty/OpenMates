//! Offline synthetic direct-facade adapter. Only this test harness spawns Python;
//! production SDK code never launches a CLI or discovers installed credentials.
use openmates_sdk::{ApiKey, ClientOptions, Error, OpenMates, Result, SdkCredentials, SdkOptions};
use serde_json::{Value, json};
use std::{
    io::Read,
    path::PathBuf,
    process::{Command, ExitCode},
};
fn field<'a>(value: &'a Value, key: &str) -> std::result::Result<&'a str, &'static str> {
    value[key].as_str().ok_or("Missing synthetic fixture field")
}
fn code(error: Error) -> &'static str {
    match error {
        Error::Crypto => "crypto",
        Error::Authentication => "authentication",
        Error::Forbidden => "forbidden",
        Error::Conflict => "conflict",
        Error::Offline => "offline",
        Error::Cancelled => "cancelled",
        Error::Invalid(_) => "invalid",
        _ => "protocol",
    }
}
async fn record_case(client: &mut OpenMates, vector: &Value) -> Result<Value> {
    let raw = &vector["draft"];
    let id = raw["chat_id"].as_str().ok_or(Error::Protocol)?;
    let listed = client.drafts().list_encrypted().await?;
    let loaded = client
        .drafts()
        .get_encrypted(id)
        .await?
        .ok_or(Error::Protocol)?;
    if serde_json::to_value(&listed)? != json!([raw]) || serde_json::to_value(&loaded)? != *raw {
        return Err(Error::Protocol);
    }
    let listed = client.drafts().list().await?;
    let loaded = client.drafts().get(id).await?.ok_or(Error::Protocol)?;
    if listed.len() != 1
        || serde_json::to_value(&listed[0])? != serde_json::to_value(&loaded)?
        || client.drafts().get("missing").await?.is_some()
    {
        return Err(Error::Protocol);
    }
    Ok(json!({"markdown":loaded.markdown,"preview":loaded.preview}))
}
async fn run_case() -> std::result::Result<(), &'static str> {
    let mut raw = Vec::new();
    std::io::stdin()
        .take(1024 * 1024 + 1)
        .read_to_end(&mut raw)
        .map_err(|_| "Synthetic input IO")?;
    if raw.len() > 1024 * 1024 {
        return Err("Synthetic input bound");
    }
    let case: Value = serde_json::from_slice(&raw).map_err(|_| "Synthetic JSON")?;
    let endpoint = field(&case, "endpoint")?;
    let url = url::Url::parse(endpoint).map_err(|_| "Synthetic URL")?;
    if url.scheme() != "http"
        || url.host_str() != Some("127.0.0.1")
        || url.port().is_none()
        || url.path() != "/"
        || url.query().is_some()
        || url.fragment().is_some()
        || !url.username().is_empty()
        || url.password().is_some()
    {
        return Err("Only bounded loopback synthetic endpoints are accepted");
    }
    if field(&case, "credential")? != "sk-api-synthetic.synthetic" {
        return Err("Synthetic credential required");
    }
    let vector = &case["vector"];
    let kind = field(vector, "kind")?;
    let credentials = if kind == "anonymous" {
        SdkCredentials::Anonymous {
            anonymous_id: "synthetic-anonymous".into(),
        }
    } else {
        SdkCredentials::ApiKey(
            ApiKey::new(field(&case, "credential")?).map_err(|_| "Synthetic credential")?,
        )
    };
    let mut client = OpenMates::new(SdkOptions {
        api_url: endpoint.into(),
        credentials,
        device_id: "synthetic-device".into(),
        client_options: ClientOptions::default(),
    })
    .map_err(|_| "Synthetic client")?;
    let result: Result<Value> = match kind {
        "record" => record_case(&mut client, vector).await,
        "empty-list" => client
            .drafts()
            .list()
            .await
            .and_then(|v| serde_json::to_value(v).map_err(Error::from)),
        "missing" => client
            .drafts()
            .get("missing")
            .await
            .and_then(|v| serde_json::to_value(v).map_err(Error::from)),
        "open-parity-limit" => {
            let id = field(&vector["draft"], "chat_id")?;
            client
                .drafts()
                .get(id)
                .await
                .and_then(|v| v.ok_or(Error::Protocol))
                .map(|v| json!({"markdown":v.markdown,"preview":v.preview}))
        }
        "wrong-account-key"
        | "project-grant-not-account-key"
        | "corrupt-markdown"
        | "anonymous"
        | "http-error" => {
            let id = field(&case["base_draft"], "chat_id")?;
            client
                .drafts()
                .get(id)
                .await
                .and_then(|v| serde_json::to_value(v).map_err(Error::from))
        }
        _ => return Err("Unknown synthetic draft scenario"),
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
            eprintln!("Rust draft fixture failed");
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
        .arg(root.join("tests/sdk-conformance/api_key_drafts_rust_peer.py"))
        .arg("--rust-executable")
        .arg(executable)
        .args(args)
        .current_dir(root)
        .status();
    if status.is_ok_and(|status| status.success()) {
        ExitCode::SUCCESS
    } else {
        eprintln!("Rust draft conformance failed");
        ExitCode::FAILURE
    }
}
