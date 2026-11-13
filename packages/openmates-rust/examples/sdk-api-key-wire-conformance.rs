//! Synthetic developer harness only (gate capabilities `sdk.billing`, `sdk.memories`).
//! Default mode runs the independent shared driver
//! `tests/sdk-conformance/runners/sdk-api-key-wire.py` with this compiled executable;
//! `--case` calls the real Rust library once with one pipe-provided synthetic vector
//! and prints the language-neutral projection. Production SDK code never starts a process.
// contract-test-file: tooling
use base64::Engine as _;
use openmates_sdk::{
    ApiKey, ClientOptions, Error, OpenMates, SdkCredentials, SdkOptions, sdk_ops::RawDownload,
};
use serde_json::{Value, json};
use std::{
    io::Read,
    path::PathBuf,
    process::{Command, ExitCode},
};

type Fixture<T> = Result<T, &'static str>;

fn field<'a>(value: &'a Value, key: &str) -> Fixture<&'a str> {
    value[key].as_str().ok_or("synthetic field")
}
fn arg(vector: &Value, index: usize) -> Fixture<&str> {
    vector["args"][index].as_str().ok_or("synthetic argument")
}
fn optional<'a>(kwargs: &'a Value, key: &str) -> Option<&'a str> {
    kwargs[key].as_str()
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
fn raw(download: RawDownload) -> Value {
    json!({
        "content_type": download.content_type,
        "filename": download.filename,
        "data_b64": base64::engine::general_purpose::STANDARD.encode(download.data),
    })
}
/// The vector's ordered `query` pairs (absent means none).
fn pairs(vector: &Value) -> Fixture<Vec<(String, String)>> {
    let Some(query) = vector.get("query") else {
        return Ok(vec![]);
    };
    query
        .as_array()
        .ok_or("synthetic query")?
        .iter()
        .map(|pair| Ok((field_at(pair, 0)?.to_owned(), field_at(pair, 1)?.to_owned())))
        .collect()
}
fn field_at(pair: &Value, index: usize) -> Fixture<&str> {
    pair[index].as_str().ok_or("synthetic query pair")
}

async fn billing(client: &OpenMates, method: &str, v: &Value) -> Fixture<Result<Value, Error>> {
    let b = client.billing();
    let k = &v["kwargs"];
    let query = pairs(v)?;
    let query: Vec<(&str, &str)> = query
        .iter()
        .map(|(a, b)| (a.as_str(), b.as_str()))
        .collect();
    let confirmed = v["confirmed"].as_bool().unwrap_or(false);
    let credits = || v["args"][0].as_i64().ok_or("synthetic credits");
    Ok(match method {
        "overview" => b.overview().await,
        "buyer_address" => b.buyer_address().await,
        "save_buyer_address" => b.save_buyer_address(Some(v["args"][0].clone())).await,
        "usage" => b.usage(&query).await,
        "usage_overview" => b.usage_overview(&query).await,
        "usage_details" => {
            b.usage_details(
                field(k, "type")?,
                field(k, "identifier")?,
                field(k, "year_month")?,
            )
            .await
        }
        "chat_total" => b.chat_total(arg(v, 0)?).await,
        "usage_summaries" => b.usage_summaries().await,
        "usage_daily" => b.usage_daily().await,
        "usage_export" => {
            let months = k["months"].as_u64().map(u32::try_from).transpose();
            b.usage_export(months.map_err(|_| "synthetic months")?)
                .await
                .map(raw)
        }
        "create_bank_transfer_order" => {
            b.create_bank_transfer_order(
                credits()?,
                optional(k, "email_encryption_key"),
                k.get("buyer_address").cloned(),
            )
            .await
        }
        "bank_transfer_status" => b.bank_transfer_status(arg(v, 0)?).await,
        "list_bank_transfer_orders" => b.list_bank_transfer_orders().await,
        "list_invoices" => b.list_invoices().await,
        "download_invoice" => b.download_invoice(arg(v, 0)?).await.map(raw),
        "download_credit_note" => b.download_credit_note(arg(v, 0)?).await.map(raw),
        "request_refund" => {
            b.request_refund(arg(v, 0)?, confirmed, optional(k, "email_encryption_key"))
                .await
        }
        "redeem_gift_card" => b.redeem_gift_card(arg(v, 0)?).await,
        "list_redeemed_gift_cards" => b.list_redeemed_gift_cards().await,
        "create_gift_card_bank_transfer_order" => {
            b.create_gift_card_bank_transfer_order(
                credits()?,
                optional(k, "email_encryption_key"),
                k.get("buyer_address").cloned(),
            )
            .await
        }
        "gift_card_purchase_status" => b.gift_card_purchase_status(arg(v, 0)?).await,
        "list_purchased_gift_cards" => b.list_purchased_gift_cards().await,
        "set_low_balance_auto_topup" => b.set_low_balance_auto_topup(v["args"][0].clone()).await,
        _ => return Err("billing operation"),
    })
}

async fn memories(
    client: &mut OpenMates,
    method: &str,
    v: &Value,
) -> Fixture<Result<Value, Error>> {
    let confirmed = v["confirmed"].as_bool().unwrap_or(false);
    Ok(match method {
        "list" => {
            let query = pairs(v)?;
            let query: Vec<(&str, Option<String>)> = query
                .iter()
                .map(|(a, b)| (a.as_str(), Some(b.clone())))
                .collect();
            client.memories().list(&query).await
        }
        "published" => {
            client
                .memories()
                .published(optional(&v["kwargs"], "app_id"))
                .await
        }
        "delete" => client.memories().delete(arg(v, 0)?, confirmed).await,
        _ => return Err("memories operation"),
    })
}

async fn run_case() -> Fixture<()> {
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
    if key != "sk-api-wireOwner.localSetupSuffix"
        || field(&case, "device_id")? != "synthetic-wire-device"
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
    let result = match field(v, "operation")?.split_once('.') {
        Some(("billing", method)) => billing(&client, method, v).await?,
        Some(("memories", method)) => memories(&mut client, method, v).await?,
        _ => return Err("wire operation"),
    };
    let output = match result {
        Ok(value) => json!({"ok": true, "value": value}),
        Err(error) => json!({"ok": false, "error": code(error)}),
    };
    println!("{output}");
    Ok(())
}

#[tokio::main]
async fn main() -> ExitCode {
    let args = std::env::args().skip(1).collect::<Vec<_>>();
    if args.len() == 1 && args[0] == "--case" {
        return match run_case().await {
            Ok(()) => ExitCode::SUCCESS,
            Err(reason) => {
                eprintln!("Rust API-key wire fixture failed: {reason}");
                ExitCode::FAILURE
            }
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
        .arg(root.join("tests/sdk-conformance/runners/sdk-api-key-wire.py"))
        .args(["--language", "rust", "--rust-executable"])
        .arg(executable)
        .args(args)
        .current_dir(root)
        .status();
    if status.is_ok_and(|status| status.success()) {
        ExitCode::SUCCESS
    } else {
        eprintln!("Rust API-key wire conformance failed");
        ExitCode::FAILURE
    }
}
