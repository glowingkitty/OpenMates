//! Settings, billing-read and account-export commands that mirror the legacy
//! CLI's handleSettings branches: printSettingsResult/printSettingsMutationResult
//! output, the same confirmations (`--yes` or an interactive `[y/N]`) and the
//! same missing-argument messages. Core owns every route and payload.
use super::reminders::ordinary;
use super::{CliError, CliOutput, Invocation, handlers, path};
use crate::client::Client;
use openmates_sdk::account::StoredFileDeletion;
use serde_json::{Value, json};

pub(super) fn supported(invocation: &Invocation) -> bool {
    COMMANDS.contains(&path(invocation).as_str())
}
const COMMANDS: &[&str] = &[
    "reminders update",
    "reminders delete",
    "gift-card redeem",
    "gift-card list",
    "billing gift-card redeem",
    "billing gift-card list",
    "billing invoices list",
    "billing bank-transfer list",
    "account export status",
    "account export manifest",
    "account export chunks",
    "account export data",
    "account export accept-partial",
    "account export cancel",
    "account delete preview",
    "account delete",
    "account storage delete",
];
pub(super) fn text_output(stdout: String) -> CliOutput {
    CliOutput {
        stdout,
        stderr: String::new(),
        exit_code: 0,
    }
}
/// printSettingsResult: JSON, else the generic object rendering.
fn result(i: &Invocation, value: &Value) -> Result<CliOutput, CliError> {
    if i.boolean("json") {
        CliOutput::json(value)
    } else {
        Ok(text_output(ordinary(value)?))
    }
}
/// printSettingsMutationResult: JSON, else a success line and the response.
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
fn missing(message: &str) -> CliError {
    CliError::Invalid(message.into())
}
fn positional<'a>(i: &'a Invocation, index: usize) -> Option<&'a str> {
    i.positionals
        .get(index)
        .map(String::as_str)
        .filter(|v| !v.trim().is_empty())
}
/// Legacy parseOnOff with its exact message.
fn on_off(value: &str, label: &str) -> Result<bool, CliError> {
    match value {
        "on" | "true" | "1" => Ok(true),
        "off" | "false" | "0" => Ok(false),
        _ => Err(CliError::Invalid(format!(
            "Invalid {label} value '{value}'. Use on/off or true/false."
        ))),
    }
}
/// Legacy parseDataOrFlags(flags, ["enabled"]).
fn reminder_body(i: &Invocation) -> Result<Value, CliError> {
    if let Some(data) = i.text("data") {
        return serde_json::from_str(data)
            .map_err(|_| CliError::Invalid("--data must be valid JSON.".into()));
    }
    match i.flags.get("enabled") {
        Some(Value::String(value)) => Ok(json!({"enabled":on_off(value, "enabled")?})),
        Some(Value::Bool(true)) => Ok(json!({"enabled":on_off("", "enabled")?})),
        _ => Err(missing("Provide --data '<json>' or a supported flag.")),
    }
}
/// Legacy confirmOrExit: `--yes` skips; otherwise the question is asked on
/// stdout and one stdin line is read. Anything but `y` aborts with exit 0.
pub(super) async fn confirm(i: &Invocation, question: &str) -> Result<bool, CliError> {
    if i.boolean("yes") {
        return Ok(true);
    }
    use std::io::Write;
    let mut stdout = std::io::stdout();
    write!(stdout, "{question}")
        .and_then(|()| stdout.flush())
        .map_err(|_| CliError::Client(crate::error::Error::Io))?;
    let answer = tokio::task::spawn_blocking(|| {
        let mut line = String::new();
        std::io::stdin().read_line(&mut line).map(|_| line)
    })
    .await
    .map_err(|_| CliError::Client(crate::error::Error::Io))?
    .map_err(|_| CliError::Client(crate::error::Error::Io))?;
    Ok(answered_yes(&answer))
}
fn answered_yes(answer: &str) -> bool {
    answer.trim().to_lowercase() == "y"
}
fn aborted() -> CliOutput {
    text_output("Aborted.\n".into())
}
fn gift_card_text(value: &Value) -> String {
    let field = |name: &str| match &value[name] {
        Value::String(text) => text.clone(),
        Value::Null => "undefined".into(),
        other => other.to_string(),
    };
    if value["success"].as_bool().unwrap_or(false) {
        format!(
            "\x1b[32m✓\x1b[0m Gift card redeemed! +{} credits\n  Balance: {} credits\n",
            field("credits_added"),
            field("current_credits")
        )
    } else {
        format!("\x1b[31m✗\x1b[0m {}\n", field("message"))
    }
}

pub(super) async fn execute(i: &Invocation, client: &mut Client) -> Result<CliOutput, CliError> {
    let command = path(i);
    let flags: &[&str] = match command.as_str() {
        "reminders update" => &["enabled", "data"],
        "reminders delete" => &["yes"],
        "account storage delete" => &["yes", "category", "all"],
        "account delete" => &["yes", "email-code", "totp-code"],
        _ => &[],
    };
    handlers::flags(i, flags)?;
    let mut account = client.account();
    match command.as_str() {
        "reminders update" => {
            let id = positional(i, 0).ok_or_else(|| missing("Missing reminder ID."))?;
            let body = reminder_body(i)?;
            mutation(i, &account.update_reminder(id, body).await?)
        }
        "reminders delete" => {
            let id = positional(i, 0).ok_or_else(|| missing("Missing reminder ID."))?;
            if !confirm(i, &format!("Delete reminder {id}? [y/N] ")).await? {
                return Ok(aborted());
            }
            mutation(i, &account.delete_reminder(id).await?)
        }
        "gift-card redeem" | "billing gift-card redeem" => {
            let code = positional(i, 0).ok_or_else(|| missing("Missing gift card code."))?;
            let value = account.redeem_gift_card(code).await?;
            if i.boolean("json") {
                CliOutput::json(&value)
            } else {
                Ok(text_output(gift_card_text(&value)))
            }
        }
        "gift-card list" | "billing gift-card list" => {
            result(i, &account.redeemed_gift_cards().await?)
        }
        "billing invoices list" => result(i, &account.invoices().await?),
        "billing bank-transfer list" => result(i, &account.bank_transfer_orders().await?),
        "account export manifest" => {
            result(i, &account.account_export_manifest(positional(i, 0)).await?)
        }
        "account export data" => match positional(i, 0) {
            None => result(i, &account.account_export_data().await?),
            Some(id) => {
                let listed = account.account_export_chunks(id).await?;
                let mut chunks = vec![];
                for chunk in listed["chunks"].as_array().into_iter().flatten() {
                    let chunk_id = match &chunk["chunk_id"] {
                        Value::String(text) => text.clone(),
                        Value::Null => String::new(),
                        other => other.to_string(),
                    };
                    chunks.push(if chunk_id.is_empty() {
                        chunk.clone()
                    } else {
                        account.account_export_chunk(id, &chunk_id).await?
                    });
                }
                result(i, &json!({"chunks":chunks}))
            }
        },
        "account export status"
        | "account export chunks"
        | "account export accept-partial"
        | "account export cancel" => {
            let action = command.rsplit(' ').next().unwrap_or_default();
            let id = positional(i, 0).ok_or_else(|| {
                missing(&format!(
                    "Missing export ID. Example: openmates settings account export {action} <export-id>"
                ))
            })?;
            let value = match action {
                "status" => account.account_export(id).await?,
                "chunks" => account.account_export_chunks(id).await?,
                "accept-partial" => account.accept_partial_account_export(id).await?,
                _ => account.cancel_account_export(id).await?,
            };
            result(i, &value)
        }
        "account delete preview" => result(i, &account.delete_account_preview().await?),
        "account delete" => delete_account(i, &mut account).await,
        "account storage delete" => {
            let category = i.text("category");
            let (scope, label) = if i.boolean("all") {
                (StoredFileDeletion::All, "all")
            } else if let Some(category) = category {
                (StoredFileDeletion::Category(category), "category")
            } else {
                let id = positional(i, 0).ok_or_else(|| missing("Missing file ID."))?;
                (StoredFileDeletion::Single(id), "single")
            };
            if !confirm(
                i,
                &format!("Delete stored file data ({label})? This cannot be undone. [y/N] "),
            )
            .await?
            {
                return Ok(aborted());
            }
            mutation(i, &account.delete_stored_files(scope).await?)
        }
        _ => Err(CliError::Unsupported {
            command: i.command_path(),
            reason: "This account settings command is not ported.".into(),
        }),
    }
}

/// npm `settings account delete`: preview, confirmation, emailed code, 2FA
/// code when enabled, then deletion. Codes are only ever read interactively.
async fn delete_account(
    i: &Invocation,
    account: &mut openmates_sdk::account::Account<'_>,
) -> Result<CliOutput, CliError> {
    use openmates_sdk::account::VerifiedAction;
    if i.has("email-code") || i.has("totp-code") {
        return Err(CliError::Invalid(
            "Deletion verification codes must be entered through interactive prompts, not command-line flags.".into(),
        ));
    }
    let preview = account.delete_account_preview().await?;
    if !i.boolean("json") {
        use std::io::Write;
        let mut stdout = std::io::stdout();
        write!(stdout, "\x1b[1mDelete Account Preview\x1b[0m\n{}", ordinary(&preview)?)
            .and_then(|()| stdout.flush())
            .map_err(|_| CliError::Client(crate::error::Error::Io))?;
    }
    if !confirm(i, "Delete this account and all associated data? [y/N] ").await? {
        return Ok(aborted());
    }
    account
        .request_action_email_code(VerifiedAction::DeleteAccount)
        .await?;
    let email_code = prompt_line("Enter email verification code: ").await?;
    account
        .verify_action_email_code(VerifiedAction::DeleteAccount, email_code.trim())
        .await?;
    let totp = if account.auth_methods().await?["has_2fa"] == true {
        Some(prompt_line("Enter 2FA code: ").await?.trim().to_owned())
    } else {
        None
    };
    let result = account.delete_account(totp.as_deref()).await?;
    if i.boolean("json") {
        CliOutput::json(&result)
    } else {
        Ok(text_output(
            "\x1b[32m✓\x1b[0m Account deletion requested and local CLI session cleared\n".into(),
        ))
    }
}
/// npm promptLine (question on stdout, one stdin line).
async fn prompt_line(question: &str) -> Result<String, CliError> {
    use std::io::Write;
    let mut stdout = std::io::stdout();
    write!(stdout, "{question}")
        .and_then(|()| stdout.flush())
        .map_err(|_| CliError::Client(crate::error::Error::Io))?;
    tokio::task::spawn_blocking(|| {
        let mut line = String::new();
        std::io::stdin().read_line(&mut line).map(|_| line)
    })
    .await
    .map_err(|_| CliError::Client(crate::error::Error::Io))?
    .map_err(|_| CliError::Client(crate::error::Error::Io))
}

#[cfg(test)]
#[path = "settings_delete_tests.rs"]
mod delete_tests;

#[cfg(test)]
#[path = "settings_more_tests.rs"]
pub(super) mod tests;
