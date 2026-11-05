//! Synthetic developer harness only. Production SDK code never starts a process.
//! Default mode runs the independent shared oracle with this compiled executable;
//! --case calls the real Rust library with one pipe-provided synthetic credential.
// contract-test-file: tooling
use openmates_sdk::{ApiKey, ClientOptions, Error, OpenMates, SdkCredentials, SdkOptions};
use serde_json::{Value, json};
use std::io::{self, BufRead, Write};
fn field<'a>(value: &'a Value, key: &str) -> Result<&'a str, &'static str> {
    value[key].as_str().ok_or("synthetic field")
}
fn code(error: Error) -> &'static str {
    match error {
        Error::Unavailable {
            code: "preview_timeout",
            ..
        } => "preview-timeout",
        Error::Authentication => "authentication",
        Error::Forbidden => "forbidden",
        Error::Conflict => "conflict",
        Error::Invalid(_) => "invalid",
        Error::Offline => "offline",
        Error::Cancelled => "cancelled",
        _ => "protocol",
    }
}
async fn invoke(case: &Value) -> Result<Value, &'static str> {
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
    if !matches!(
        key,
        "sk-api-embedOwnerA.localSetupSuffix" | "sk-api-embedOwnerB.localSetupSuffix"
    ) || field(&case, "device_id")? != "synthetic-embed-device"
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
    let result = match field(v, "operation")? {
        "show" => client.embeds().show(field(v, "embed_id")?).await,
        "versions" => client.embeds().versions(field(v, "embed_id")?).await,
        "version" => {
            client
                .embeds()
                .version(
                    field(v, "embed_id")?,
                    v["version"].as_i64().ok_or("version")?,
                )
                .await
        }
        "restore_version" => {
            client
                .embeds()
                .restore_version(
                    field(v, "embed_id")?,
                    v["version"].as_i64().ok_or("version")?,
                    v["confirmed"] == true,
                )
                .await
        }
        "preview_start" => {
            let o = &v["options"];
            match client
                .embeds()
                .preview()
                .start(
                    field(v, "embed_id")?,
                    field(v, "chat_id")?,
                    openmates_sdk::sdk_embeds::PreviewStartOptions {
                        shared_context: o["shared_context"].as_str().map(str::to_owned),
                        requested_runtime: o["requested_runtime"].as_str().map(str::to_owned),
                        source_message_id: o["source_message_id"].as_str().map(str::to_owned),
                        wait: v["wait"] == true,
                        timeout: if v["local_timeout"] == true {
                            Some(std::time::Duration::ZERO)
                        } else {
                            None
                        },
                        ..Default::default()
                    },
                )
                .await
            {
                Ok(value) => Ok(value),
                Err(openmates_sdk::sdk_embeds::PreviewStartError::ClientError(error)) => Err(error),
                Err(openmates_sdk::sdk_embeds::PreviewStartError::LocalDeadline) => {
                    Err(Error::Unavailable {
                        code: "preview_timeout",
                        reason: "LOCAL_PREVIEW_TIMEOUT",
                    })
                }
            }
        }
        "preview_status" => {
            client
                .embeds()
                .preview()
                .status(field(v, "session_id")?)
                .await
        }
        "preview_open" => {
            client
                .embeds()
                .preview()
                .open(field(v, "session_id")?)
                .await
        }
        "preview_stop" => {
            client
                .embeds()
                .preview()
                .stop(field(v, "session_id")?)
                .await
        }
        "share" => {
            client
                .embeds()
                .share(
                    field(v, "embed_id")?,
                    v["expires"].as_i64().ok_or("duration")?,
                    field(v, "password")?,
                )
                .await
        }
        "add_to_project" => {
            client
                .embeds()
                .add_to_project(
                    field(v, "embed_id")?,
                    field(v, "project_id")?,
                    v["folder"].as_str(),
                )
                .await
        }
        "remove_from_project" => {
            client
                .embeds()
                .remove_from_project(field(v, "embed_id")?, field(v, "project_id")?)
                .await
        }
        _ => return Err("embeds operation"),
    };
    let mut output = match result {
        Ok(value) => json!({"ok":true,"value":value}),
        Err(error) => {
            json!({"ok":false,"error":if v["wrong_hash"]==true && error==Error::Forbidden {"key-unavailable"} else {code(error)}})
        }
    };
    if v["local_timeout"] == true && output["error"] == "preview-timeout" {
        output["timeout_source"] = json!("local");
        output["semantic_status"] = json!(408);
        output["http_observed"] = json!(false);
    }
    Ok(output)
}
fn read_line(input: &mut impl BufRead) -> String {
    let mut line = String::new();
    input.read_line(&mut line).expect("bounded worker pipe");
    assert!(line.len() <= 2 * 1024 * 1024);
    line
}
#[tokio::main]
async fn main() {
    let stdin = io::stdin();
    let mut input = stdin.lock();
    let case: Value = serde_json::from_str(&read_line(&mut input)).expect("synthetic input");
    let n = case["iterations"].as_u64().expect("iterations");
    assert!((100..=1000000).contains(&n));
    println!("{}", json!({"ready":true}));
    io::stdout().flush().unwrap();
    assert_eq!(read_line(&mut input).trim(), "start");
    let mut results = Vec::new();
    for i in 0..n {
        let result = invoke(&case["case"])
            .await
            .expect("synthetic direct SDK operation");
        let v = &case["case"]["vector"];
        if !v["expected_error"].is_null() {
            assert_eq!(result["ok"], false);
            assert_eq!(result["error"], v["expected_error"]);
        } else if v["operation"] != "share" {
            assert_eq!(result, json!({"ok":true,"value":v["response"]}));
        }
        if v["operation"] == "share" || i == n - 1 {
            results.push(result);
        }
    }
    println!("{}", json!({"done":true,"iterations":n,"results":results}));
    io::stdout().flush().unwrap();
    assert_eq!(read_line(&mut input).trim(), "release");
}
