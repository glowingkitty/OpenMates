//! Thin settings/reminders presentation. Core owns auth, decoding and its one
//! cancellable 61-second HTTP-429 retry; this module never performs transport.
use super::super::{global_history::{js_number_string, js_string}, handlers, terminal_text};
use super::{CliError, CliOutput, Invocation};
use crate::client::Client;
use serde::{Serialize, Serializer, ser::{SerializeMap, SerializeSeq}};
use serde_json::Value;
use std::fmt::Write;

pub(super) fn supported(invocation: &Invocation) -> bool {
    invocation.command_path() == "settings reminders list"
}
pub(super) async fn execute(
    invocation: &Invocation,
    client: &mut Client,
) -> Result<CliOutput, CliError> {
    // No reminders-specific flags or filters. Legacy matches() ignores trailing
    // positionals; do not reinterpret them as reminder IDs or request parameters.
    handlers::flags(invocation, &[])?;
    let response = client
        .account()
        .reminders_ordered()
        .await
        .map_err(settings_error)?;
    if invocation.boolean("json") {
        let mut stdout = serde_json::to_string_pretty(&JavascriptJson::root(response.value(), response.root_keys()))
            .map_err(|_| CliError::Client(crate::error::Error::Protocol))?;
        stdout.push('\n');
        return Ok(CliOutput {
            stdout,
            stderr: String::new(),
            exit_code: 0,
        });
    }
    Ok(CliOutput {
        stdout: ordinary_with_root_keys(response.value(), Some(response.root_keys()))?,
        stderr: String::new(),
        exit_code: 0,
    })
}
// Keep the operation's precise safety refusal without changing generic Core or
// other App-skill error presentation. Core remains the only response decoder.
fn settings_error(error: openmates_sdk::account::SettingsReadError) -> CliError {
    if error.http_status().is_some() {
        CliError::Contract {
            code: "command_failed",
            message: error.to_string(),
        }
    } else if let crate::error::Error::Unavailable {
        code: "settings_json_unsupported",
        ..
    } = error.core_error()
    {
        CliError::Contract {
            code: "settings_json_unsupported",
            message: error.to_string(),
        }
    } else {
        CliError::Client(error.core_error())
    }
}
// A borrowed presentation view leaves the canonical SDK Value untouched. serde
// owns all JSON structure/escaping; RawValue emits only our finite number token.
// RawValue is already enabled by the direct shared Rust SDK dependency.
struct JavascriptJson<'a> {
    value: &'a Value,
    root_keys: Option<&'a [String]>,
}
impl<'a> JavascriptJson<'a> {
    fn root(value: &'a Value, root_keys: &'a [String]) -> Self {
        Self { value, root_keys: Some(root_keys) }
    }
    fn nested(value: &'a Value) -> Self { Self { value, root_keys: None } }
}
impl Serialize for JavascriptJson<'_> {
    fn serialize<S: Serializer>(&self, serializer: S) -> Result<S::Ok, S::Error> {
        match self.value {
            Value::Null => serializer.serialize_unit(),
            Value::Bool(value) => serializer.serialize_bool(*value),
            Value::String(value) => serializer.serialize_str(value),
            Value::Number(value) => {
                let number = value.as_f64().filter(|number| number.is_finite())
                    .ok_or_else(|| serde::ser::Error::custom("Unsupported presentation number"))?;
                let token = serde_json::value::RawValue::from_string(js_number_string(number))
                    .map_err(serde::ser::Error::custom)?;
                token.serialize(serializer)
            }
            Value::Array(values) => {
                let mut sequence = serializer.serialize_seq(Some(values.len()))?;
                for value in values { sequence.serialize_element(&Self::nested(value))?; }
                sequence.end()
            }
            Value::Object(values) => {
                let mut object = serializer.serialize_map(Some(values.len()))?;
                if let Some(keys) = self.root_keys {
                    for key in keys {
                        if let Some(value) = values.get(key) {
                            object.serialize_entry(key, &Self::nested(value))?;
                        }
                    }
                } else {
                    for (key, value) in values { object.serialize_entry(key, &Self::nested(value))?; }
                }
                object.end()
            }
        }
    }
}
// Object.entries puts canonical array-index keys before other string keys.
// Core supplies original root order. Nested Value maps retain existing behavior.
fn entries<'a>(
    object: &'a serde_json::Map<String, Value>,
    root_keys: Option<&[String]>,
) -> Vec<(&'a String, &'a Value)> {
    if let Some(keys) = root_keys {
        return keys
            .iter()
            .filter_map(|key| object.get_key_value(key))
            .collect();
    }
    fn index(key: &str) -> Option<u32> {
        key.parse::<u32>()
            .ok()
            .filter(|v| *v != u32::MAX && v.to_string() == key)
    }
    let mut values = object.iter().collect::<Vec<_>>();
    values.sort_by(|(a, _), (b, _)| match (index(a), index(b)) {
        (Some(a), Some(b)) => a.cmp(&b),
        (Some(_), None) => std::cmp::Ordering::Less,
        (None, Some(_)) => std::cmp::Ordering::Greater,
        (None, None) => std::cmp::Ordering::Equal,
    });
    values
}
fn padded(key: &str, width: usize) -> String {
    format!(
        "{}{}",
        terminal_text(key),
        " ".repeat(width.saturating_sub(key.encode_utf16().count()))
    )
}
fn scalar(value: &Value) -> String {
    terminal_text(&js_string(value))
}
fn truthy(value: &Value) -> bool {
    match value {
        Value::Null => false,
        Value::Bool(v) => *v,
        Value::Number(v) => v.as_f64().is_some_and(|v| v != 0.0),
        Value::String(v) => !v.is_empty(),
        _ => true,
    }
}
fn string(value: &Value) -> Option<String> {
    value
        .as_str()
        .map(str::trim)
        .filter(|v| !v.is_empty())
        .map(terminal_text)
}
fn kv(out: &mut String, key: &str, value: &str, width: usize) {
    let _ = writeln!(out, "  \x1b[2m{}\x1b[0m {value}", padded(key, width));
}
fn invoices(out: &mut String, values: &[Value]) -> Result<(), CliError> {
    let _ = writeln!(
        out,
        "\n  \x1b[1mInvoices\x1b[0m  \x1b[2m({})\x1b[0m",
        values.len()
    );
    if values.is_empty() {
        return Ok(());
    }
    out.push('\n');
    for value in values {
        if value.is_null() {
            return Err(CliError::Contract {
                code: "command_failed",
                message: "Cannot read properties of null (reading 'date')".into(),
            });
        }
        let date = string(&value["date"]).unwrap_or_else(|| "—".into());
        let amount = string(&value["amount"]).unwrap_or_else(|| "—".into());
        let credits = if value["credits_purchased"].is_null() {
            "—".into()
        } else {
            scalar(&value["credits_purchased"])
        };
        let refund = string(&value["refund_status"])
            .filter(|v| v != "none")
            .map(|v| format!("  \x1b[33m[{v}]\x1b[0m"))
            .unwrap_or_default();
        let gift = if truthy(&value["is_gift_card"]) {
            "  \x1b[35m[gift card]\x1b[0m"
        } else {
            ""
        };
        let transfer = string(&value["transaction_status"])
            .map(|v| format!("  \x1b[36m[{v}]\x1b[0m"))
            .unwrap_or_default();
        let _ = writeln!(
            out,
            "    {date}  \x1b[2m€{amount}\x1b[0m  {credits} credits{refund}{gift}{transfer}"
        );
        if let Some(reference) = string(&value["bank_transfer_reference"]) {
            kv(out, "      Bank transfer reference", &reference, 30);
        }
    }
    Ok(())
}
fn billing(
    out: &mut String,
    value: &serde_json::Map<String, Value>,
    root_keys: Option<&[String]>,
) -> Result<(), CliError> {
    out.push_str("\x1b[1mBilling\n\x1b[0m\n");
    let credits = value
        .get("credits")
        .filter(|v| !v.is_null())
        .or_else(|| value.get("current_credits"));
    if let Some(v) = credits {
        kv(out, "Credits", &scalar(v), 16);
    }
    if let Some(v) = value.get("payment_tier") {
        kv(out, "Payment tier", &scalar(v), 16);
    }
    if let Some(v) = value.get("auto_topup_enabled") {
        kv(
            out,
            "Auto top-up",
            if truthy(v) { "enabled" } else { "disabled" },
            16,
        );
        if truthy(v) {
            for (key, label, suffix) in [
                ("auto_topup_threshold", "  Threshold", " credits"),
                ("auto_topup_amount", "  Amount", " credits"),
                ("auto_topup_currency", "  Currency", ""),
            ] {
                if let Some(v) = value.get(key) {
                    let text = if key == "auto_topup_currency" {
                        scalar(v).to_uppercase()
                    } else {
                        format!("{}{suffix}", scalar(v))
                    };
                    kv(out, label, &text, 16);
                }
            }
        }
    }
    if let Some(v) = value
        .get("invoices")
        .and_then(Value::as_array)
        .filter(|v| !v.is_empty())
    {
        invoices(out, v)?;
    }
    for (key, v) in entries(value, root_keys) {
        if matches!(
            key.as_str(),
            "credits"
                | "current_credits"
                | "payment_tier"
                | "auto_topup_enabled"
                | "auto_topup_threshold"
                | "auto_topup_amount"
                | "auto_topup_currency"
                | "invoices"
        ) || v.is_null()
        {
            continue;
        }
        let text = if v.is_object() || v.is_array() {
            terminal_text(&serde_json::to_string(&JavascriptJson::nested(v))
                .map_err(|_| CliError::Client(crate::error::Error::Protocol))?)
        } else {
            scalar(v)
        };
        kv(out, key, &text, 16);
    }
    Ok(())
}
fn render(
    out: &mut String,
    value: &Value,
    indent: usize,
    root_keys: Option<&[String]>,
) -> Result<(), CliError> {
    let pad = "  ".repeat(indent);
    match value {
        Value::Null => {
            let _ = writeln!(out, "{pad}(empty)");
        }
        Value::Array(items) => {
            if items.is_empty() {
                let _ = writeln!(out, "{pad}(empty list)");
            }
            for (index, item) in items.iter().enumerate() {
                if item.is_object() || item.is_array() {
                    render(out, item, indent, None)?;
                    if index + 1 < items.len() {
                        let _ = writeln!(out, "{pad}\x1b[2m{}\x1b[0m", "─".repeat(40));
                    }
                } else {
                    let _ = writeln!(out, "{pad}{}", scalar(item));
                }
            }
        }
        Value::Object(object) => {
            if object.contains_key("payment_tier") && object.contains_key("invoices") {
                return billing(out, object, root_keys);
            }
            if let Some(items) = object.get("invoices").and_then(Value::as_array) {
                return invoices(out, items);
            }
            for (key, v) in entries(object, root_keys) {
                if v.is_null() {
                    continue;
                }
                match v {
                    Value::Array(items) if items.is_empty() => {
                        let _ = writeln!(out, "{pad}  \x1b[2m{}\x1b[0m (none)", padded(key, 20));
                    }
                    Value::Array(items)
                        if items[0].is_object() || items[0].is_array() || items[0].is_null() =>
                    {
                        let _ = writeln!(
                            out,
                            "\n{pad}  \x1b[1m{}\x1b[0m  \x1b[2m({})\x1b[0m",
                            terminal_text(key),
                            items.len()
                        );
                        render(out, v, indent + 1, None)?;
                    }
                    Value::Array(items) => {
                        let joined = items
                            .iter()
                            .map(|v| {
                                if v.is_null() {
                                    String::new()
                                } else {
                                    scalar(v)
                                }
                            })
                            .collect::<Vec<_>>()
                            .join(", ");
                        let _ = writeln!(out, "{pad}  \x1b[2m{}\x1b[0m {joined}", padded(key, 20));
                    }
                    Value::Object(_) => {
                        let _ = writeln!(out, "{pad}  \x1b[1m{}\x1b[0m", terminal_text(key));
                        render(out, v, indent + 1, None)?;
                    }
                    _ => {
                        let _ = writeln!(
                            out,
                            "{pad}  \x1b[2m{}\x1b[0m {}",
                            padded(key, 20),
                            scalar(v)
                        );
                    }
                }
            }
        }
        _ => {
            let _ = writeln!(out, "{pad}{}", scalar(value));
        }
    }
    Ok(())
}
fn ordinary_with_root_keys(
    value: &Value,
    root_keys: Option<&[String]>,
) -> Result<String, CliError> {
    let mut out = String::new();
    render(&mut out, value, 0, root_keys)?;
    Ok(out)
}
/// The legacy `printGenericObject` rendering (printSettingsResult) for any
/// settings/billing response, shared by the other account settings commands.
pub(super) fn ordinary(value: &Value) -> Result<String, CliError> {
    ordinary_with_root_keys(value, None)
}
#[cfg(test)]
#[path = "reminders_tests.rs"]
mod tests;
