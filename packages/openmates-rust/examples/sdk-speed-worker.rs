//! Rust arm of the cross-SDK speed check (`tests/sdk-conformance/benchmark_sdk_speed.py`).
//!
//! A warmed, long-lived worker: line 1 on stdin is `{api_url, api_key, device_id}`,
//! each further line is `{op, args, iterations}`. The worker runs the real public
//! `openmates::sdk` operation `iterations` times on one explicit API-key client and
//! answers one JSON line with a language-neutral digest of the last result, so the
//! orchestrator can confirm every SDK did comparable work. CPU and wall time are
//! measured by the orchestrator from outside the process. No CLI state, profile or
//! fallback credentials are read.
// contract-test-file: tooling
use openmates_sdk::sdk_history::HistoryListOptions;
use openmates_sdk::sdk_wikipedia::{WikipediaOptions, WikipediaSearchOptions};
use openmates_sdk::{ApiKey, ClientOptions, Error, OpenMates, SdkCredentials, SdkOptions};
use serde_json::{Value, json};
use sha2::{Digest, Sha256};
use std::io::{BufRead, Write};

fn text<'a>(value: &'a Value, key: &str) -> Result<&'a str, String> {
    value[key]
        .as_str()
        .ok_or_else(|| format!("missing string field {key}"))
}

fn sha(value: &str) -> String {
    Sha256::digest(value.as_bytes())
        .iter()
        .map(|byte| format!("{byte:02x}"))
        .collect()
}

fn code(error: &Error) -> &'static str {
    match error {
        Error::Authentication => "authentication",
        Error::Forbidden => "forbidden",
        Error::Conflict => "conflict",
        Error::Invalid(_) => "invalid",
        Error::Offline => "offline",
        Error::Cancelled => "cancelled",
        Error::Crypto => "crypto",
        _ => "protocol",
    }
}

/// Digest shared by all SDK arms: sorted keys/ids and content hashes only, never plaintext.
async fn invoke(client: &mut OpenMates, op: &str, args: &Value) -> Result<Value, Error> {
    let language = || args["language"].as_str().map(str::to_owned);
    Ok(match op {
        "drafts.list" => {
            let mut rows = client
                .drafts()
                .list()
                .await?
                .into_iter()
                .map(|draft| json!([draft.encrypted.chat_id, sha(&draft.markdown)]))
                .collect::<Vec<_>>();
            rows.sort_by_key(|row| row[0].as_str().unwrap_or_default().to_owned());
            json!({"count": rows.len(), "rows": rows})
        }
        "drafts.get" => {
            let id = args["chat_id"].as_str().unwrap_or_default();
            match client.drafts().get(id).await? {
                Some(draft) => json!({"found": true, "markdown": sha(&draft.markdown)}),
                None => json!({"found": false}),
            }
        }
        "history.list" => {
            let rows = client
                .history()
                .list(HistoryListOptions {
                    limit: args["limit"].as_i64(),
                    ..Default::default()
                })
                .await?;
            json!({"count": rows.len()})
        }
        "wikipedia.search" => {
            let value = client
                .wikipedia()
                .search(
                    args["query"].as_str().unwrap_or_default(),
                    WikipediaSearchOptions {
                        language: language(),
                        limit: args["limit"].as_i64(),
                    },
                )
                .await?;
            json!({"count": value["results"].as_array().map_or(0, Vec::len)})
        }
        "wikipedia.summary" => {
            let value = client
                .wikipedia()
                .summary(
                    args["title"].as_str().unwrap_or_default(),
                    WikipediaOptions {
                        language: language(),
                    },
                )
                .await?;
            json!({"title": value["title"]})
        }
        _ => return Err(Error::Invalid("unknown benchmark operation")),
    })
}

#[tokio::main]
async fn main() -> Result<(), String> {
    let stdin = std::io::stdin();
    let mut lines = stdin.lock().lines();
    let mut next = || -> Result<Option<Value>, String> {
        match lines.next() {
            None => Ok(None),
            Some(line) => serde_json::from_str(&line.map_err(|e| e.to_string())?)
                .map(Some)
                .map_err(|e| e.to_string()),
        }
    };
    let init = next()?.ok_or("missing init line")?;
    let mut client = OpenMates::new(SdkOptions {
        api_url: text(&init, "api_url")?.into(),
        credentials: SdkCredentials::ApiKey(
            ApiKey::new(text(&init, "api_key")?).map_err(|_| "invalid API key".to_string())?,
        ),
        device_id: text(&init, "device_id")?.into(),
        client_options: ClientOptions::default(),
    })
    .map_err(|_| "client options".to_string())?;
    let mut stdout = std::io::stdout().lock();
    writeln!(stdout, "{}", json!({"ready": true})).map_err(|e| e.to_string())?;
    stdout.flush().map_err(|e| e.to_string())?;
    while let Some(request) = next()? {
        let op = text(&request, "op")?.to_owned();
        let iterations = request["iterations"]
            .as_u64()
            .filter(|n| (1..=1000).contains(n))
            .ok_or("iterations")?;
        let mut answer = json!({"ok": true});
        for _ in 0..iterations {
            match invoke(&mut client, &op, &request["args"]).await {
                Ok(digest) => answer = json!({"ok": true, "digest": digest}),
                Err(error) => {
                    // Public SDK errors never carry URLs, bodies or secrets, so the
                    // Debug form is a safe diagnostic for the orchestrator report.
                    answer =
                        json!({"ok": false, "error": code(&error), "detail": format!("{error:?}")});
                    break;
                }
            }
        }
        writeln!(stdout, "{answer}").map_err(|e| e.to_string())?;
        stdout.flush().map_err(|e| e.to_string())?;
    }
    Ok(())
}
