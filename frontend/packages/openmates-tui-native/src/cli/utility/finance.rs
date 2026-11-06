//! `finance check-accounts|check_accounts` (npm handleFinance): the read-only
//! Finance Check accounts skill over a Revolut Business connected account
//! and/or local canonical CSV/TSV statements. Connected-account decryption and
//! the skill request live in the shared SDK; this adapter reads files, builds
//! the input and renders the result.
use super::super::{CliError, CliOutput, Invocation, handlers};
use super::js_number;
use crate::client::Client;
use serde_json::{Map, Value, json};

const PROVIDER: &str = "revolut_business";
const FLAGS: &[&str] = &[
    "connected-account",
    "csv",
    "csv-only",
    "period",
    "projection-horizon",
    "from",
    "to",
    "start-date",
    "end-date",
    "account",
    "source",
    "category",
    "categories",
    "state",
    "states",
    "placeholder",
    "placeholders",
    "direction",
];

pub(super) fn supported(i: &Invocation) -> bool {
    matches!(
        i.command_path().as_str(),
        "finance check-accounts" | "finance check_accounts"
    )
}
fn fail(message: impl Into<String>) -> CliError {
    CliError::Invalid(message.into())
}
fn text_flag<'a>(i: &'a Invocation, key: &str) -> Option<&'a str> {
    i.text(key).filter(|v| !v.is_empty())
}
/// npm parseCsvFlag.
pub(super) fn csv_list(value: Option<&str>) -> Option<Vec<String>> {
    let items = value?
        .split(',')
        .map(str::trim)
        .filter(|s| !s.is_empty())
        .map(str::to_owned)
        .collect::<Vec<_>>();
    (!items.is_empty()).then_some(items)
}
fn statements(i: &Invocation) -> Result<Vec<Value>, CliError> {
    csv_list(text_flag(i, "csv"))
        .unwrap_or_default()
        .into_iter()
        .map(|path| {
            let content = std::fs::read_to_string(&path)
                .map_err(|_| fail(format!("ENOENT: no such file or directory, open '{path}'")))?;
            let filename = std::path::Path::new(&path)
                .file_name()
                .map(|n| n.to_string_lossy().into_owned())
                .unwrap_or_default();
            Ok(json!({"filename": filename, "content": content}))
        })
        .collect()
}
/// npm buildFinanceCheckAccountsInput (with the prompt-injection option off).
pub(super) fn input(i: &Invocation, csv: &[Value], account: Option<&Value>) -> Value {
    let mut input = Map::new();
    input.insert(
        "period".into(),
        json!(text_flag(i, "period").unwrap_or("monthly")),
    );
    input.insert(
        "projection_horizon".into(),
        json!(text_flag(i, "projection-horizon").unwrap_or("monthly")),
    );
    if let Some(start) = text_flag(i, "from").or(text_flag(i, "start-date")) {
        input.insert("start_date".into(), json!(start));
    }
    if let Some(end) = text_flag(i, "to").or(text_flag(i, "end-date")) {
        input.insert("end_date".into(), json!(end));
    }
    for (key, flag, alias) in [
        ("account_filters", "account", None),
        ("source_filters", "source", None),
        ("category_filters", "category", Some("categories")),
        ("state_filters", "state", Some("states")),
        ("placeholder_filters", "placeholder", Some("placeholders")),
    ] {
        let raw = i.text(flag).or_else(|| alias.and_then(|a| i.text(a)));
        if let Some(items) = csv_list(raw) {
            input.insert(key.into(), json!(items));
        }
    }
    if let Some(direction) = text_flag(i, "direction") {
        input.insert("direction_filter".into(), json!(direction));
    }
    if !csv.is_empty() {
        input.insert("csv_statements".into(), json!(csv));
    }
    if let Some(account) = account {
        let environment = if account["refresh_token_bundle"]["environment"] == "sandbox" {
            "sandbox"
        } else {
            "production"
        };
        let reference = account["account_ref"]
            .as_str()
            .filter(|r| !r.is_empty())
            .or(account["id"].as_str())
            .unwrap_or_default();
        input.insert(
            "connected_account_requests".into(),
            json!([{"source_ref": format!("{PROVIDER}:{reference}"), "environment": environment}]),
        );
    }
    input.insert(
        "security".into(),
        json!({"prompt_injection_protection": "disabled"}),
    );
    Value::Object(input)
}
/// npm decryptConnectedAccountForSkill selection over decrypted candidates.
pub(super) fn select(candidates: Vec<Value>, account_id: Option<&str>) -> Result<Value, CliError> {
    if candidates.is_empty() {
        return Err(fail(match account_id {
            Some(id) => format!("Connected account {id} was not found for {PROVIDER}."),
            None => format!(
                "No {PROVIDER} connected account found. Run `openmates connect-account revolut-business` first."
            ),
        }));
    }
    if candidates.len() > 1 && account_id.is_none() {
        return Err(fail(format!(
            "Multiple {PROVIDER} accounts found. Re-run with --connected-account <id>."
        )));
    }
    Ok(candidates.into_iter().next().unwrap_or(Value::Null))
}
/// JavaScript `String(value)`; `fallback` mirrors `?? 0` for absent/null.
fn js(value: Option<&Value>, fallback: Option<&str>) -> String {
    match (value, fallback) {
        (None | Some(Value::Null), Some(fallback)) => fallback.into(),
        (None, None) => "undefined".into(),
        (Some(Value::Null), None) => "null".into(),
        (Some(Value::String(s)), _) => s.clone(),
        (Some(Value::Number(n)), _) => n.as_f64().map(js_number).unwrap_or_default(),
        (Some(Value::Bool(b)), _) => b.to_string(),
        (Some(Value::Array(items)), _) => items
            .iter()
            .map(|item| js(Some(item), Some("")))
            .collect::<Vec<_>>()
            .join(","),
        (Some(Value::Object(_)), _) => "[object Object]".into(),
    }
}
fn kv(out: &mut String, key: &str, value: &str) {
    out.push_str(&format!("  \x1b[2m{key:<16}\x1b[0m {value}\n"));
}
/// npm printFinanceCheckAccountsResult.
pub(super) fn result_text(result: &Value) -> String {
    let overview = result.get("overview").filter(|v| v.is_object());
    let summaries = overview
        .and_then(|o| o.get("summaries"))
        .filter(|v| v.is_object());
    let summary = |key: &str| js(summaries.and_then(|s| s.get(key)), Some("0"));
    let mut out = String::from("\x1b[1mFinance › Check accounts\x1b[0m\n");
    kv(
        &mut out,
        "Accounts",
        &js(result.get("account_count"), Some("0")),
    );
    kv(
        &mut out,
        "Transactions",
        &js(result.get("transaction_count"), Some("0")),
    );
    kv(&mut out, "Income", &summary("income_total"));
    kv(&mut out, "Expenses", &summary("expense_total"));
    kv(&mut out, "Net", &summary("net_total"));
    let series = summaries
        .and_then(|s| s.get("time_series"))
        .and_then(Value::as_array)
        .cloned()
        .unwrap_or_default();
    if !series.is_empty() {
        out.push_str("\nTime series\n");
        for bucket in &series {
            out.push_str(&format!(
                "  {}  income {}  expenses {}  net {}\n",
                js(bucket.get("bucket"), None),
                js(bucket.get("income"), Some("0")),
                js(bucket.get("expense"), Some("0")),
                js(bucket.get("net"), Some("0")),
            ));
        }
    }
    let transactions = overview
        .and_then(|o| o.get("transactions"))
        .and_then(Value::as_array)
        .cloned()
        .unwrap_or_default();
    if !transactions.is_empty() {
        out.push_str("\nTransactions\n");
        for t in transactions.iter().take(25) {
            out.push_str(&format!(
                "  {}  {}  {} {}  {}  {}\n",
                js(t.get("posted_at"), None),
                js(t.get("direction"), None),
                js(t.get("amount"), None),
                js(t.get("currency"), None),
                js(t.get("category"), None),
                js(t.get("counterparty_placeholder"), None),
            ));
        }
        if transactions.len() > 25 {
            out.push_str(&format!("  ... {} more\n", transactions.len() - 25));
        }
    }
    for warning in result["warnings"].as_array().into_iter().flatten() {
        let message = warning
            .get("message")
            .filter(|v| !v.is_null())
            .or_else(|| warning.get("code").filter(|v| !v.is_null()));
        out.push_str(&format!("\nWarning: {}\n", js(message, Some("unknown"))));
    }
    out
}
/// Explicit `--api-key` check. The skill route accepts API keys, but
/// connected-account discovery (`GET /v1/connected-accounts`) accepts only
/// Cookie sessions, so a key runs CSV statements only and must say so with
/// `--csv-only` rather than silently skipping a connected account.
pub(super) async fn execute_key(
    i: &Invocation,
    sdk: &openmates_sdk::sdk::OpenMates,
) -> Result<CliOutput, CliError> {
    handlers::flags(i, FLAGS)?;
    if !i.boolean("csv-only") || text_flag(i, "connected-account").is_some() {
        return Err(CliError::Unsupported {
            command: i.command_path(),
            reason: KEY_CSV_ONLY.into(),
        });
    }
    let csv = statements(i)?;
    if csv.is_empty() {
        return Err(fail(
            "Check accounts requires a Revolut Business connected account or --csv <file.csv>.",
        ));
    }
    let options = openmates_sdk::sdk_finance::CheckAccountsOptions {
        chat_id: Some(format!("cli-finance-{}", uuid::Uuid::new_v4())),
        message_id: Some(format!("cli-finance-message-{}", uuid::Uuid::new_v4())),
        ..Default::default()
    };
    let result = sdk.finance().check_accounts(input(i, &csv, None), options).await?;
    if i.boolean("json") {
        return CliOutput::json(&result);
    }
    Ok(CliOutput::text(result_text(&result)))
}
pub(super) const KEY_CSV_ONLY: &str = "API-key Finance checks run only with --csv-only and --csv <file>: connected-account selection reads GET /v1/connected-accounts, which accepts only Cookie sessions. Cookie credentials were not used.";
pub(super) async fn execute(i: &Invocation, client: &mut Client) -> Result<CliOutput, CliError> {
    handlers::flags(i, FLAGS)?;
    if i.has("api-key") {
        return Err(CliError::Unsupported {
            command: i.command_path(),
            reason: "Finance account checks require an authenticated native session; --api-key is not supported yet.".into(),
        });
    }
    let csv = statements(i)?;
    let wanted = text_flag(i, "connected-account");
    let mut account = None;
    if !i.boolean("csv-only") {
        let found = client
            .account()
            .connected_accounts_for_skill(wanted, "finance", PROVIDER)
            .await
            .map_err(CliError::from)
            .and_then(|candidates| select(candidates, wanted));
        match found {
            Ok(selected) => account = Some(selected),
            Err(error) if csv.is_empty() || wanted.is_some() => return Err(error),
            Err(_) => {}
        }
    }
    if account.is_none() && csv.is_empty() {
        return Err(fail(
            "Check accounts requires a Revolut Business connected account or --csv <file.csv>.",
        ));
    }
    let token_refs = account.as_ref().map_or_else(Vec::new, |a| {
        vec![json!({
            "connected_account_id": a["id"], "app_id": "finance", "provider_id": PROVIDER,
            "allowed_actions": ["read"], "action_scope": {"provider": PROVIDER},
            "refresh_token_envelope": a["refresh_token_bundle"],
        })]
    });
    let body = json!({
        "input": input(i, &csv, account.as_ref()),
        "connected_account_token_ref_inputs": token_refs,
        "chat_id": format!("cli-finance-{}", uuid::Uuid::new_v4()),
        "message_id": format!("cli-finance-message-{}", uuid::Uuid::new_v4()),
    });
    let result = client
        .account()
        .run_connected_account_skill("finance", "check_accounts", body)
        .await?;
    if i.boolean("json") {
        return CliOutput::json(&result);
    }
    Ok(CliOutput::text(result_text(&result)))
}
