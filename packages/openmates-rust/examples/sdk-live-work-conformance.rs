//! Live-backend Rust driver for the cross-language API-key SDK harness
//! (`frontend/apps/web_app/tests/sdk-live-work-crud.spec.ts`). It reads one
//! bounded JSON batch of public `openmates::sdk` operations on stdin, runs them
//! sequentially against the real isolated CI backend with the explicitly
//! supplied API key and prints one JSON result per operation. It never reads
//! CLI state and mirrors `tests/sdk-conformance/runners/sdk-live-work.{mjs,py}`.
use openmates_sdk::sdk_chats::ChatListOptions;
use openmates_sdk::sdk_history::HistoryListOptions;
use openmates_sdk::work::{
    PlanCreate, PlanPatch, ProjectCreate, ProjectPatch, TaskCreate, TaskPatch,
};
use openmates_sdk::{ApiKey, ClientOptions, Error, OpenMates, SdkCredentials, SdkOptions};
use serde_json::{Value, json};
use std::{io::Read, process::ExitCode};

/// Upper bound for one stdin batch; the harness sends a few kilobytes.
const MAX_BATCH_BYTES: u64 = 1024 * 1024;
/// Exact Rust `Invalid` text the SDK transport uses for HTTP 404/410.
const NOT_FOUND_TEXT: &str = "The requested item is unavailable.";

/// Stable cross-language error class; npm/Python drivers map HTTP statuses to
/// the same names so the spec can compare outcomes without language details.
fn class(error: Error) -> &'static str {
    match error {
        Error::Invalid(message) if message == NOT_FOUND_TEXT => "not_found",
        Error::Invalid(_) => "invalid",
        Error::Authentication => "unauthorized",
        Error::Forbidden => "forbidden",
        Error::Conflict => "conflict",
        Error::Offline => "offline",
        Error::Crypto => "crypto",
        _ => "protocol",
    }
}

fn text<'a>(op: &'a Value, key: &str) -> Result<&'a str, Error> {
    op[key]
        .as_str()
        .ok_or(Error::Invalid("operation field missing"))
}

fn input<T: serde::de::DeserializeOwned>(op: &Value) -> Result<T, Error> {
    serde_json::from_value(op["input"].clone())
        .map_err(|_| Error::Invalid("operation input rejected"))
}

/// Runs one operation; every SDK failure is returned, never retried here.
async fn run(client: &mut OpenMates, op: &Value) -> Result<Value, Error> {
    let family = text(op, "family")?;
    let action = text(op, "op")?;
    let id = || text(op, "id");
    let list = |rows: Vec<Value>| Value::Array(rows);
    match (family, action) {
        ("probe", "chats") => client
            .chats()
            .list(ChatListOptions {
                limit: 1,
                offset: 0,
            })
            .await
            .map(|rows| json!({ "count": rows.len() })),
        ("projects", "create") => client.projects().create(input::<ProjectCreate>(op)?).await,
        ("projects", "show") => client.projects().show(id()?).await,
        ("projects", "list") => client.projects().list().await.map(list),
        ("projects", "update") => {
            client
                .projects()
                .update(id()?, input::<ProjectPatch>(op)?)
                .await
        }
        ("projects", "delete") => client.projects().delete(id()?, true).await,
        ("tasks", "create") => client.tasks().create(input::<TaskCreate>(op)?).await,
        ("tasks", "show") => client.tasks().show(id()?).await,
        ("tasks", "list") => client.tasks().list().await.map(list),
        ("tasks", "update") => client.tasks().update(id()?, input::<TaskPatch>(op)?).await,
        ("tasks", "delete") => client.tasks().delete(id()?, true).await,
        ("plans", "create") => client.plans().create(input::<PlanCreate>(op)?).await,
        ("plans", "show") => client.plans().show(id()?).await,
        ("plans", "list") => client.plans().list().await.map(list),
        ("plans", "update") => client.plans().update(id()?, input::<PlanPatch>(op)?).await,
        ("plans", "delete") => client.plans().delete(id()?, true).await,
        ("history", "list") => {
            let filters = &op["input"];
            let options = HistoryListOptions {
                object_type: filters["object_type"].as_str().map(str::to_owned),
                object_id: filters["object_id"].as_str().map(str::to_owned),
                limit: filters["limit"].as_i64(),
            };
            client.history().list(options).await.map(list)
        }
        ("docs", "list") => client.docs().list().await,
        _ => Err(Error::Invalid("unsupported live operation")),
    }
}

async fn main_batch() -> Result<(), &'static str> {
    let mut bytes = vec![];
    std::io::stdin()
        .take(MAX_BATCH_BYTES + 1)
        .read_to_end(&mut bytes)
        .map_err(|_| "batch input")?;
    if bytes.len() as u64 > MAX_BATCH_BYTES {
        return Err("batch bound");
    }
    let batch: Value = serde_json::from_slice(&bytes).map_err(|_| "batch JSON")?;
    let operations = batch["operations"].as_array().ok_or("batch operations")?;
    // Credentials come only from the explicit environment of this process.
    let key = std::env::var("OPENMATES_API_KEY").map_err(|_| "OPENMATES_API_KEY")?;
    let api_url = std::env::var("OPENMATES_API_URL").map_err(|_| "OPENMATES_API_URL")?;
    let device_id = std::env::var("OPENMATES_DEVICE_ID").map_err(|_| "OPENMATES_DEVICE_ID")?;
    let mut client = OpenMates::new(SdkOptions {
        api_url,
        credentials: SdkCredentials::ApiKey(ApiKey::new(&key).map_err(|_| "API key format")?),
        device_id,
        client_options: ClientOptions::default(),
    })
    .map_err(|_| "client options")?;
    let mut results = Vec::with_capacity(operations.len());
    for op in operations {
        results.push(match run(&mut client, op).await {
            Ok(value) => json!({ "ok": true, "value": value }),
            // `Invalid` carries a static, non-secret SDK message; it explains
            // Rust-only input rules (for example an explicit Project write mode).
            Err(Error::Invalid(message)) if message != NOT_FOUND_TEXT => {
                json!({ "ok": false, "error": "invalid", "detail": message })
            }
            Err(error) => json!({ "ok": false, "error": class(error) }),
        });
    }
    println!("{}", Value::Array(results));
    Ok(())
}

#[tokio::main]
async fn main() -> ExitCode {
    match main_batch().await {
        Ok(()) => ExitCode::SUCCESS,
        Err(reason) => {
            eprintln!("Rust live SDK driver failed: {reason}");
            ExitCode::FAILURE
        }
    }
}
