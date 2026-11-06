//! Offline SDK conformance harness for the shared API-key fixtures: wire vectors
//! (operations, domains-B) through the public `OpenMates` client against a
//! loopback recorder, plus pure helper, key-management and model vectors. Argument
//! and file handling live here, outside the SDK library.
// contract-test-file: tooling
mod dispatch;
mod helpers;
mod server;

use openmates_sdk::{ApiKey, ClientOptions, OpenMates, SdkCredentials, SdkOptions};
use serde_json::{Value, json};
use sha2::{Digest, Sha256};
use std::process::ExitCode;

// Setup suffix must be ASCII alphanumeric (ApiKey::new); it never leaves the client.
const KEY: &str = "sk-api-sharedwire.syntheticLocalSetupSecret";

async fn wire_case(vector: &Value) -> Result<(), String> {
    let (url, server) = server::serve_once()?;
    let client = OpenMates::new(SdkOptions {
        api_url: url,
        credentials: SdkCredentials::ApiKey(ApiKey::new(KEY).map_err(|_| "synthetic key")?),
        device_id: "shared-wire-device".into(),
        client_options: ClientOptions::default(),
    })
    .map_err(|_| "client options")?;
    let args = vector["args"].as_array().ok_or("args")?;
    let op = vector["operation"].as_str().ok_or("operation")?;
    let confirmed = vector["confirmed"].as_bool().unwrap_or(false);
    dispatch::dispatch(&client, op, args, &vector["kwargs"], confirmed)
        .await?
        .map_err(|error| format!("{}: SDK error {error}", vector["id"]))?;
    let seen = server.join().map_err(|_| "server thread")??;
    let expected = &vector["expect"];
    let matches = expected["method"] == seen.method.as_str()
        && expected["path"] == seen.path.as_str()
        && expected["body"] == seen.body
        // Only the public key id travels; the local setup secret never leaves.
        && seen.authorization.as_deref() == Some("Bearer sk-api-sharedwire");
    matches
        .then_some(())
        .ok_or_else(|| format!("wire mismatch: {}", vector["id"]))
}

async fn run(capability: &str, raw: &[u8]) -> Result<Value, String> {
    let fixture: Value = serde_json::from_slice(raw).map_err(|_| "fixture JSON")?;
    let vectors = fixture["capabilities"][capability]["vectors"]
        .as_array()
        .ok_or("capability vectors")?;
    let mut results = Vec::with_capacity(vectors.len());
    for vector in vectors {
        match capability {
            "sdk.api-key-operations.v1" | "sdk.api-key-domains-b.v1" => wire_case(vector).await?,
            "sdk.public-utilities-helpers.v1" => helpers::helper_case(vector)?,
            "sdk.key-management.primitives.v1" => helpers::key_case(vector)?,
            "sdk.models.layout.v1" => helpers::model_case(vector)?,
            _ => return Err("unsupported capability".into()),
        }
        results.push(json!({"id": vector["id"], "status": "passed"}));
    }
    if results.is_empty() {
        return Err("no vectors".into());
    }
    Ok(json!({
        "capability": capability, "language": "rust", "status": "passed",
        "fixtureSha256": format!("{:x}", Sha256::digest(raw)), "results": results,
    }))
}

#[tokio::main(flavor = "current_thread")]
async fn main() -> ExitCode {
    let args: Vec<String> = std::env::args().collect();
    let option = |name: &str| {
        args.iter()
            .position(|a| a == name)
            .and_then(|i| args.get(i + 1))
    };
    let (Some(fixture), Some(capability)) = (option("--fixture"), option("--capability")) else {
        eprintln!("usage: --fixture <path> --capability <id>");
        return ExitCode::FAILURE;
    };
    let outcome = match std::fs::read(fixture) {
        Ok(raw) => run(capability, &raw).await,
        Err(_) => Err("fixture read".into()),
    };
    match outcome {
        Ok(result) => {
            println!("{result}");
            ExitCode::SUCCESS
        }
        Err(error) => {
            eprintln!("Rust SDK conformance failed {capability}: {error}");
            ExitCode::FAILURE
        }
    }
}
