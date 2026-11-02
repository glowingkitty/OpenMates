//! `settings notifications ...` and `settings newsletter ...` with npm flags,
//! messages and printSettingsResult/printSettingsMutationResult output.
use super::reminders::ordinary;
use super::settings_more::text_output;
use super::{CliError, CliOutput, Invocation, handlers, path};
use crate::client::Client;
use serde_json::{Map, Value, json};

const COMMANDS: &[&str] = &[
    "notifications status",
    "notifications email get",
    "notifications list",
    "notifications email set",
    "notifications backup set",
    "newsletter categories",
    "newsletter categories set",
    "newsletter subscribe",
    "newsletter confirm",
    "newsletter unsubscribe",
];
pub(super) fn supported(i: &Invocation) -> bool {
    i.path.first().is_some_and(|p| p == "settings") && COMMANDS.contains(&path(i).as_str())
}
fn fail(message: impl Into<String>) -> CliError {
    CliError::Invalid(message.into())
}
/// npm parseOnOff.
fn on_off(value: &str, label: &str) -> Result<bool, CliError> {
    match value {
        "on" | "true" | "1" => Ok(true),
        "off" | "false" | "0" => Ok(false),
        _ => Err(fail(format!(
            "Invalid {label} value '{value}'. Use on/off or true/false."
        ))),
    }
}
/// String form of a flag as npm sees it (`String(flags[x])`).
fn flag_text(i: &Invocation, name: &str) -> Option<String> {
    i.flags.get(name).map(|value| match value {
        Value::String(text) => text.clone(),
        other => other.to_string(),
    })
}
/// npm parseOptionalBoolean.
fn optional_bool(
    i: &Invocation,
    name: &str,
    fallback: bool,
    label: &str,
) -> Result<bool, CliError> {
    match i.flags.get(name) {
        None => Ok(fallback),
        Some(Value::Bool(value)) => Ok(*value),
        Some(_) => on_off(&flag_text(i, name).unwrap_or_default(), label),
    }
}
/// npm parseRequiredNumber.
fn number(i: &Invocation, name: &str) -> Result<f64, CliError> {
    let raw = i
        .text(name)
        .ok_or_else(|| fail(format!("Missing --{name}.")))?;
    raw.trim()
        .parse::<f64>()
        .ok()
        .filter(|v| v.is_finite())
        .ok_or_else(|| fail(format!("Invalid --{name}: {raw}")))
}
fn result(i: &Invocation, value: &Value) -> Result<CliOutput, CliError> {
    if i.boolean("json") {
        CliOutput::json(value)
    } else {
        Ok(text_output(ordinary(value)?))
    }
}
fn mutation(i: &Invocation, value: &Value) -> Result<CliOutput, CliError> {
    if i.boolean("json") {
        return CliOutput::json(value);
    }
    let mut stdout = "\x1b[32m✓\x1b[0m Settings updated\n".to_owned();
    if value.is_object() || value.is_array() {
        stdout.push_str(&ordinary(value)?);
    }
    Ok(text_output(stdout))
}
fn json_number(value: f64) -> Value {
    if value.fract() == 0.0 && value.abs() < 9_007_199_254_740_992.0 {
        json!(value as i64)
    } else {
        json!(value)
    }
}

pub(super) async fn execute(i: &Invocation, client: &mut Client) -> Result<CliOutput, CliError> {
    let command = path(i);
    let allowed: &[&str] = match command.as_str() {
        "notifications list" => &["limit"],
        "notifications email set" => &[
            "enabled",
            "email",
            "ai-responses",
            "workflow-runs",
            "include-content",
            "backup-reminder",
            "webhook-chats",
        ],
        "notifications backup set" => &["enabled", "email", "interval"],
        "newsletter categories set" => &["updates", "tips", "daily"],
        "newsletter subscribe" => &["language", "darkmode"],
        _ => &[],
    };
    handlers::flags(i, allowed)?;
    let positional = |index: usize| {
        i.positionals
            .get(index)
            .map(String::as_str)
            .filter(|v| !v.is_empty())
    };
    let mut account = client.account();
    match command.as_str() {
        "notifications status" | "notifications email get" => {
            result(i, &account.email_notification_settings().await?)
        }
        "notifications list" => {
            let limit = if i.has("limit") {
                number(i, "limit")?
            } else {
                50.0
            };
            result(i, &account.notifications(limit as i64).await?)
        }
        "notifications email set" => {
            let enabled = match flag_text(i, "enabled") {
                Some(value) => Some(on_off(&value, "email notifications")?),
                None => None,
            };
            let mut preferences = Map::new();
            for (flag, key, label) in [
                ("ai-responses", "aiResponses", "AI response notifications"),
                ("workflow-runs", "workflowRuns", "workflow run digest"),
                (
                    "include-content",
                    "includeContent",
                    "email content previews",
                ),
                (
                    "backup-reminder",
                    "backupReminder",
                    "backup reminder notifications",
                ),
                (
                    "webhook-chats",
                    "webhookChats",
                    "webhook chat notifications",
                ),
            ] {
                if let Some(value) = flag_text(i, flag) {
                    preferences.insert(key.into(), json!(on_off(&value, label)?));
                }
            }
            if enabled.is_none() && preferences.is_empty() {
                return Err(fail(
                    "Provide --enabled or at least one email category flag.",
                ));
            }
            let mut update = json!({"preferences":preferences});
            if let Some(enabled) = enabled {
                update["enabled"] = json!(enabled);
            }
            if let Some(email) = i.text("email") {
                update["email"] = json!(email);
            }
            mutation(
                i,
                &account.update_email_notification_settings(update).await?,
            )
        }
        "notifications backup set" => {
            let enabled = on_off(
                &flag_text(i, "enabled").unwrap_or_default(),
                "backup reminders",
            )?;
            let interval = number(i, "interval")?;
            let mut update = json!({"preferences":{"backupReminder":enabled},"backup_reminder_interval_days":json_number(interval)});
            if let Some(email) = i.text("email") {
                update["email"] = json!(email);
            }
            mutation(
                i,
                &account.update_email_notification_settings(update).await?,
            )
        }
        "newsletter categories" => result(i, &account.newsletter_categories().await?),
        "newsletter categories set" => {
            let categories = json!({
                "updates_and_announcements":optional_bool(i, "updates", true, "updates newsletter")?,
                "tips_and_tricks":optional_bool(i, "tips", true, "tips newsletter")?,
                "daily_inspirations":optional_bool(i, "daily", true, "daily inspirations newsletter")?,
            });
            mutation(i, &account.update_newsletter_categories(categories).await?)
        }
        "newsletter subscribe" => {
            let email = positional(0).ok_or_else(|| fail("Missing email. Example: openmates settings newsletter subscribe you@example.com"))?;
            let language = i.text("language").unwrap_or("en");
            let darkmode = optional_bool(i, "darkmode", false, "newsletter dark mode")?;
            mutation(
                i,
                &account
                    .subscribe_newsletter(email, language, darkmode)
                    .await?,
            )
        }
        "newsletter confirm" => {
            let token = positional(0).ok_or_else(|| fail("Missing confirmation token."))?;
            mutation(i, &account.confirm_newsletter(token).await?)
        }
        "newsletter unsubscribe" => {
            let token = positional(0).ok_or_else(|| fail("Missing unsubscribe token."))?;
            mutation(i, &account.unsubscribe_newsletter(token).await?)
        }
        _ => Err(CliError::Unsupported {
            command: i.command_path(),
            reason: "This notifications command is not ported.".into(),
        }),
    }
}

#[cfg(test)]
#[path = "notifications_tests.rs"]
mod tests;
