//! `openmates teams billing address|bank-transfer`, `teams export` and
//! `teams import` (npm handleTeams), over the SDK Team billing/export
//! routes. Declared from account.rs so it shares the account dispatch.
use super::{CliError, CliOutput, Invocation, handlers};
use crate::client::Client;
use openmates_sdk::{account::validate_buyer_address, work::TeamCreate};
use serde_json::{Value, json};
use std::path::Path;

const COMMANDS: &[&str] = &[
    "teams billing address",
    "teams billing bank-transfer create",
    "teams billing bank-transfer status",
    "teams billing bank-transfer list",
    "teams export",
    "teams import",
];
pub(super) fn supported(i: &Invocation) -> bool {
    COMMANDS.contains(&i.command_path().as_str())
}
fn fail(message: impl Into<String>) -> CliError {
    CliError::Invalid(message.into())
}
/// npm requiredStringFlag.
fn required<'a>(value: Option<&'a str>, label: &str) -> Result<&'a str, CliError> {
    value
        .map(str::trim)
        .filter(|v| !v.is_empty())
        .ok_or_else(|| fail(format!("Missing {label}.")))
}
/// npm requireTeamId over the positionals that follow the action.
fn team<'a>(i: &'a Invocation, at: usize) -> Result<&'a str, CliError> {
    required(
        i.text("team")
            .or(i.text("team-id"))
            .or(i.positionals.get(at).map(String::as_str)),
        "--team <team-id>",
    )
}
/// npm buyerAddressFromFlags.
fn address_file(i: &Invocation) -> Result<Option<Value>, CliError> {
    if !i.has("billing-address-file") {
        return Ok(None);
    }
    let file = required(i.text("billing-address-file"), "")
        .map_err(|_| fail("Provide --billing-address-file <json-file>."))?;
    let value: Value = std::fs::read_to_string(file)
        .ok()
        .and_then(|text| serde_json::from_str(&text).ok())
        .ok_or_else(|| fail("Could not read billing address JSON file."))?;
    Ok(Some(validate_buyer_address(&value)?))
}
fn pretty(value: &Value) -> Result<CliOutput, CliError> {
    CliOutput::json(value)
}
fn field(value: &Value, key: &str) -> String {
    match &value[key] {
        Value::String(s) => s.clone(),
        Value::Null => "undefined".into(),
        other => other.to_string(),
    }
}
/// npm printBankTransferOrder(order, false).
fn order_text(order: &Value) -> String {
    let mut out = format!("\x1b[1mBank Transfer\x1b[0m\nOrder ID: {}\nCredits: {}\nAmount: EUR {}\nReference: {}\nIBAN: {}\nBIC: {}\nBank: {}\nAccount holder: {}\n",
        field(order, "order_id"), field(order, "credits_amount"), field(order, "amount_eur"), field(order, "reference"),
        field(order, "iban"), field(order, "bic"), field(order, "bank_name"), field(order, "account_holder_name"));
    let text = |key: &str| order[key].as_str().filter(|v| !v.is_empty());
    if let Some(line) = text("account_holder_address_line1") {
        out.push_str(&format!("Address: {line}\n"));
    }
    if let Some(line) = text("account_holder_address_line2") {
        out.push_str(&format!("         {line}\n"));
    }
    let city = [text("account_holder_postal_code"), text("account_holder_city")]
        .into_iter()
        .flatten()
        .collect::<Vec<_>>();
    if !city.is_empty() {
        out.push_str(&format!("         {}\n", city.join(" ")));
    }
    if let Some(country) = text("account_holder_country") {
        out.push_str(&format!("         {country}\n"));
    }
    out.push_str(&format!("Expires: {}\n\nInclude the exact reference in your bank transfer. Missing or changed references require manual review.\nCheck status: openmates settings billing bank-transfer status {}\n",
        field(order, "expires_at"), field(order, "order_id")));
    out
}
/// npm printBankTransferStatus(status, false).
fn status_text(status: &Value) -> String {
    format!("\x1b[1mBank Transfer Status\x1b[0m\nOrder ID: {}\nStatus: {}\nCredits: {}\nAmount: EUR {}\nReference: {}\nExpires: {}\n",
        field(status, "order_id"), field(status, "status"), field(status, "credits_amount"),
        field(status, "amount_eur"), field(status, "reference"), field(status, "expires_at"))
}
fn plain(stdout: String) -> CliOutput {
    CliOutput {
        stdout: super::super::terminal_text(&stdout),
        stderr: String::new(),
        exit_code: 0,
    }
}
/// Owner-only (0600) file write like npm writeFileSync(..., {mode: 0o600}).
fn write_private(path: &str, bytes: &[u8]) -> Result<(), CliError> {
    use std::io::Write;
    let mut options = std::fs::OpenOptions::new();
    options.write(true).create(true).truncate(true);
    #[cfg(unix)]
    std::os::unix::fs::OpenOptionsExt::mode(&mut options, 0o600);
    options
        .open(Path::new(path))
        .and_then(|mut file| file.write_all(bytes))
        .map_err(|_| fail(format!("Could not write {path}.")))
}

pub(super) async fn execute(i: &Invocation, client: &mut Client) -> Result<CliOutput, CliError> {
    let command = i.command_path();
    let allowed: &[&str] = match command.as_str() {
        "teams billing address" => &["team", "team-id", "billing-address-file"],
        "teams billing bank-transfer create" => &["team", "team-id", "credits", "billing-address-file"],
        "teams billing bank-transfer status" => &["team", "team-id", "order"],
        "teams billing bank-transfer list" | "teams export" => &["team", "team-id", "output"],
        "teams import" => &["file", "team", "destination-team", "new-team-name"],
        _ => &[],
    };
    handlers::flags(i, allowed)?;
    let json = i.boolean("json");
    match command.as_str() {
        "teams billing address" => {
            let action = i.positionals.first().map(String::as_str).unwrap_or("show");
            let team = team(i, 1)?;
            match action {
                "show" => pretty(&json!({"buyer_address":client.account().buyer_address(Some(team)).await?})),
                "set" => {
                    let address = address_file(i)?.ok_or_else(|| fail("Provide --billing-address-file <json-file>."))?;
                    client.account().save_buyer_address(Some(team), Some(address)).await?;
                    Ok(plain("Team billing address saved.\n".into()))
                }
                "clear" => {
                    client.account().save_buyer_address(Some(team), None).await?;
                    Ok(plain("Team billing address cleared.\n".into()))
                }
                _ => Err(fail("Use teams billing address show, set or clear.")),
            }
        }
        "teams billing bank-transfer create" => {
            let team = team(i, 0)?;
            let raw = required(i.text("credits"), "--credits <amount>")?;
            let credits = raw.parse::<f64>().ok().filter(|v| v.is_finite() && *v > 0.0)
                .ok_or_else(|| fail(format!("Invalid --credits <amount>: {raw}")))?;
            let address = address_file(i)?;
            let order = client.teams().create_bank_transfer(team, credits, address).await?;
            if json { pretty(&order) } else { Ok(plain(order_text(&order))) }
        }
        "teams billing bank-transfer status" => {
            let team = team(i, 0)?;
            let order = required(i.text("order").or(i.positionals.get(1).map(String::as_str)), "<order-id>")?;
            let status = client.teams().bank_transfer_status(team, order).await?;
            if json { pretty(&status) } else { Ok(plain(status_text(&status))) }
        }
        "teams billing bank-transfer list" => {
            let orders = client.teams().bank_transfer_orders(team(i, 0)?).await?;
            if json { pretty(&json!({"orders":orders})) } else { pretty(&orders) }
        }
        "teams export" => {
            let team = team(i, 0)?;
            let output = required(i.text("output"), "--output <path>")?;
            let result = client.teams().export(team).await?;
            let artifact = if result["artifact"].is_object() { &result["artifact"] } else { &result };
            let mut text = serde_json::to_string_pretty(artifact).map_err(|_| fail("Team export is not JSON."))?;
            text.push('\n');
            write_private(output, text.as_bytes())?;
            if json {
                let mut value = result.clone();
                if let Some(object) = value.as_object_mut() {
                    object.insert("output".into(), json!(output));
                }
                pretty(&value)
            } else {
                Ok(plain(format!("Team export written: {output}\n")))
            }
        }
        "teams import" => {
            let file = required(i.text("file").or(i.positionals.first().map(String::as_str)), "--file <path>")?;
            let artifact: Value = std::fs::read_to_string(file)
                .map_err(|_| fail(format!("Could not read {file}.")))
                .and_then(|text| serde_json::from_str(&text).map_err(|_| fail(format!("{file} is not valid JSON."))))?;
            let mut team = i.text("team").or(i.text("destination-team")).map(str::to_owned);
            if team.is_none() && let Some(name) = i.text("new-team-name") {
                let created = client.teams().create(TeamCreate { name, ..Default::default() }).await?;
                team = created["team_id"].as_str().or(created["id"].as_str()).map(str::to_owned);
            }
            let team = team.ok_or_else(|| fail("Team import requires --team <team-id> or --new-team-name <name>."))?;
            pretty(&client.teams().import(&team, artifact).await?)
        }
        _ => Err(CliError::Unsupported { command, reason: "This Team command is not ported.".into() }),
    }
    .map_err(|error| match error {
        CliError::Client(crate::error::Error::Invalid(message)) => CliError::Invalid(message.into()),
        other => other,
    })
}

#[cfg(test)]
#[path = "teams_billing_tests.rs"]
mod tests;
