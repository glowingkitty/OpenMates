//! Personal billing purchases (`settings billing ...`): buyer address,
//! SEPA bank-transfer credit and gift-card orders and their status,
//! purchased gift cards, invoice refunds and low-balance auto top-up, with
//! the npm handleSettings messages, confirmation and output. Invoice and
//! credit-note PDF downloads live in `transfers`.
use super::settings_more::{confirm, mutation, result, text_output};
use super::{CliError, CliOutput, Invocation, handlers, path};
use crate::client::Client;
use openmates_sdk::account::validate_buyer_address;
use serde_json::{Value, json};

const COMMANDS: &[&str] = &[
    "billing address show",
    "billing address set",
    "billing address clear",
    "billing buy-credits bank-transfer",
    "billing bank-transfer status",
    "billing invoices refund",
    "billing gift-card buy bank-transfer",
    "billing gift-card purchase-status",
    "billing gift-card purchased",
    "billing auto-topup low-balance set",
];
pub(super) fn supported(i: &Invocation) -> bool {
    COMMANDS.contains(&path(i).as_str())
}
fn fail(message: impl Into<String>) -> CliError {
    CliError::Invalid(message.into())
}
/// npm buyerAddressFromFlags.
pub(super) fn address_file(i: &Invocation) -> Result<Option<Value>, CliError> {
    if !i.has("billing-address-file") {
        return Ok(None);
    }
    let file = i
        .text("billing-address-file")
        .filter(|f| !f.is_empty())
        .ok_or_else(|| fail("Provide --billing-address-file <json-file>."))?;
    let value: Value = std::fs::read_to_string(file)
        .ok()
        .and_then(|text| serde_json::from_str(&text).ok())
        .ok_or_else(|| fail("Could not read billing address JSON file."))?;
    Ok(Some(validate_buyer_address(&value)?))
}
fn field(value: &Value, key: &str) -> String {
    match &value[key] {
        Value::String(s) => s.clone(),
        Value::Null => "undefined".into(),
        other => other.to_string(),
    }
}
/// npm printBankTransferOrder(order, giftCard).
pub(super) fn order_text(order: &Value, gift_card: bool) -> String {
    let mut out = format!("\x1b[1m{}\x1b[0m\nOrder ID: {}\nCredits: {}\nAmount: EUR {}\nReference: {}\nIBAN: {}\nBIC: {}\nBank: {}\nAccount holder: {}\n",
        if gift_card { "Gift Card Bank Transfer" } else { "Bank Transfer" },
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
    out.push_str(&format!("Expires: {}\n\nInclude the exact reference in your bank transfer. Missing or changed references require manual review.\n",
        field(order, "expires_at")));
    out.push_str(&if gift_card {
        format!("Gift-card code appears after payment is matched: openmates settings billing gift-card purchase-status {}\n", field(order, "order_id"))
    } else {
        format!("Check status: openmates settings billing bank-transfer status {}\n", field(order, "order_id"))
    });
    out
}
/// npm printBankTransferStatus(status, giftCard).
pub(super) fn status_text(status: &Value, gift_card: bool) -> String {
    let mut out = format!("\x1b[1m{}\x1b[0m\nOrder ID: {}\nStatus: {}\nCredits: {}\nAmount: EUR {}\nReference: {}\nExpires: {}\n",
        if gift_card { "Gift Card Purchase Status" } else { "Bank Transfer Status" },
        field(status, "order_id"), field(status, "status"), field(status, "credits_amount"),
        field(status, "amount_eur"), field(status, "reference"), field(status, "expires_at"));
    if gift_card {
        let code = status["gift_card_code"].as_str().filter(|c| !c.is_empty()).unwrap_or("available after payment is matched");
        out.push_str(&format!("Gift-card code: {code}\n"));
    }
    out
}
/// npm parseRequiredNumber.
fn number(i: &Invocation, flag: &str) -> Result<f64, CliError> {
    let raw = i.text(flag).ok_or_else(|| fail(format!("Missing --{flag}.")))?;
    let trimmed = raw.trim();
    let parsed = if trimmed.is_empty() { Some(0.0) } else { trimmed.parse::<f64>().ok() };
    parsed
        .filter(|v| v.is_finite())
        .ok_or_else(|| fail(format!("Invalid --{flag}: {raw}")))
}
fn positional(i: &Invocation) -> Option<&str> {
    i.positionals.first().map(String::as_str).filter(|v| !v.is_empty())
}
fn order_output(i: &Invocation, order: &Value, gift_card: bool) -> Result<CliOutput, CliError> {
    if i.boolean("json") {
        CliOutput::json(order)
    } else {
        Ok(text_output(order_text(order, gift_card)))
    }
}
fn status_output(i: &Invocation, status: &Value, gift_card: bool) -> Result<CliOutput, CliError> {
    if i.boolean("json") {
        CliOutput::json(status)
    } else {
        Ok(text_output(status_text(status, gift_card)))
    }
}

pub(super) async fn execute(i: &Invocation, client: &mut Client) -> Result<CliOutput, CliError> {
    run(i, client).await.map_err(|error| match error {
        CliError::Client(crate::error::Error::Invalid(message)) => CliError::Invalid(message.into()),
        other => other,
    })
}
async fn run(i: &Invocation, client: &mut Client) -> Result<CliOutput, CliError> {
    let command = path(i);
    let allowed: &[&str] = match command.as_str() {
        "billing address set" | "billing buy-credits bank-transfer" => &["billing-address-file", "credits"],
        "billing gift-card buy bank-transfer" => &["credits"],
        "billing invoices refund" => &["yes"],
        "billing auto-topup low-balance set" => &["enabled", "amount", "currency", "email"],
        _ => &[],
    };
    handlers::flags(i, allowed)?;
    let mut account = client.account();
    match command.as_str() {
        "billing address show" => CliOutput::json(&json!({"buyer_address":account.buyer_address(None).await?})),
        "billing address set" => {
            let address = address_file(i)?.ok_or_else(|| fail("Provide --billing-address-file <json-file>."))?;
            account.save_buyer_address(None, Some(address)).await?;
            Ok(text_output("Personal billing address saved.\n".into()))
        }
        "billing address clear" => {
            account.save_buyer_address(None, None).await?;
            Ok(text_output("Personal billing address cleared.\n".into()))
        }
        "billing buy-credits bank-transfer" => {
            let credits = number(i, "credits")?;
            let address = address_file(i)?;
            let order = account.create_bank_transfer_order(credits, address).await?;
            order_output(i, &order, false)
        }
        "billing bank-transfer status" => {
            let order = positional(i).ok_or_else(|| fail("Missing order ID."))?;
            let status = account.bank_transfer_status(order).await?;
            status_output(i, &status, false)
        }
        "billing gift-card buy bank-transfer" => {
            let credits = number(i, "credits")?;
            let order = account.create_gift_card_bank_transfer_order(credits).await?;
            order_output(i, &order, true)
        }
        "billing gift-card purchase-status" => {
            let order = positional(i).ok_or_else(|| fail("Missing order ID."))?;
            let status = account.gift_card_purchase_status(order).await?;
            status_output(i, &status, true)
        }
        "billing gift-card purchased" => result(i, &account.purchased_gift_cards().await?),
        "billing invoices refund" => {
            let invoice = positional(i).ok_or_else(|| fail("Missing invoice ID."))?.to_owned();
            if !confirm(i, &format!("Request refund for invoice {invoice}? [y/N] ")).await? {
                return Ok(text_output("Aborted.\n".into()));
            }
            mutation(i, &account.request_refund(&invoice).await?)
        }
        "billing auto-topup low-balance set" => {
            let enabled = super::settings_more::on_off(i.text("enabled").unwrap_or(""), "low-balance auto top-up")?;
            let amount = number(i, "amount")?;
            let currency = i.text("currency").unwrap_or("eur");
            let value = account.set_low_balance_auto_topup(enabled, amount, currency, i.text("email")).await?;
            mutation(i, &value)
        }
        _ => Err(CliError::Unsupported { command, reason: "This billing command is not ported.".into() }),
    }
}

#[cfg(test)]
#[path = "billing_tests.rs"]
mod tests;
