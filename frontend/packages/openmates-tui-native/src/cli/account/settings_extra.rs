//! Remaining npm `settings` write commands: mates, report-issue, chat
//! auto-delete, debug-log sharing and AI model defaults. Routes live in the
//! shared SDK (`Account::report_issue` and friends); this adapter parses
//! flags and prints the npm layouts.
use super::settings_more::{confirm, mutation, result, text_output};
use super::{CliError, CliOutput, Invocation, handlers, path};
use crate::client::Client;
use openmates_sdk::mentions::MATE_NAMES;
use serde_json::{Value, json};

const COMMANDS: &[&str] = &[
    "mates list",
    "mates info",
    "mates consent",
    "report-issue create",
    "report-issue status",
    "privacy auto-delete chats set",
    "privacy debug-logs share",
    "ai models set-defaults",
];
pub(super) fn supported(i: &Invocation) -> bool {
    COMMANDS.contains(&path(i).as_str())
}
fn missing(message: &str) -> CliError {
    CliError::Invalid(message.into())
}
fn positional(i: &Invocation, index: usize) -> Option<&str> {
    i.positionals.get(index).map(String::as_str).filter(|v| !v.trim().is_empty())
}
fn mate_json(id: &str, name: &str) -> Value {
    json!({"id":id,"name":name,"mention":format!("@mate:{id}")})
}
fn mates_list(json_output: bool) -> Result<CliOutput, CliError> {
    let mates: Vec<Value> = MATE_NAMES.iter().map(|(id, name)| mate_json(id, name)).collect();
    if json_output {
        return CliOutput::json(&Value::Array(mates));
    }
    let mut out = "\x1b[1mMates\x1b[0m\n".to_owned();
    for (id, name) in MATE_NAMES {
        out.push_str(&format!("{id:<28} {name:<10} @mate:{id}\n"));
    }
    Ok(text_output(out))
}
fn mate_info(id: &str, json_output: bool) -> Result<CliOutput, CliError> {
    let name = MATE_NAMES
        .iter()
        .find(|(candidate, _)| *candidate == id)
        .map(|(_, name)| *name)
        .ok_or_else(|| missing(&format!("Unknown mate '{id}'. Run 'openmates settings mates list'.")))?;
    if json_output {
        return CliOutput::json(&mate_json(id, name));
    }
    Ok(text_output(format!(
        "\x1b[1m{name} ({id})\x1b[0m\nMention: @mate:{id}\nUse: openmates chats send \"@mate:{id} <message>\"\n"
    )))
}
/// printReportIssueCreateResult
fn report_created(i: &Invocation, value: &Value) -> Result<CliOutput, CliError> {
    if i.boolean("json") {
        return CliOutput::json(value);
    }
    let text = |key: &str| value.get(key).and_then(Value::as_str).unwrap_or_default();
    let (issue, short) = (text("issue_id"), text("short_issue_id"));
    let mut out = "\x1b[32m✓\x1b[0m Issue reported\n".to_owned();
    if !short.is_empty() || !issue.is_empty() {
        out.push_str(&format!("Issue reference: {}\n", if short.is_empty() { issue } else { short }));
    }
    if !issue.is_empty() && !short.is_empty() && issue != short {
        out.push_str(&format!("Internal issue ID: {issue}\n"));
    }
    if let Some(message) = value.get("message").and_then(Value::as_str) {
        out.push_str(&format!("{message}\n"));
    }
    Ok(text_output(out))
}
/// parseModelDefaultFlag: `auto`/`null` clear the default.
fn model_default(i: &Invocation, flag: &str) -> Result<Option<Option<String>>, CliError> {
    match i.flags.get(flag) {
        None => Ok(None),
        Some(Value::String(value)) if !value.is_empty() => {
            Ok(Some((value != "auto" && value != "null").then(|| value.clone())))
        }
        Some(_) => Err(missing(&format!("Missing value for --{flag}. Use a provider/model-id or auto."))),
    }
}

fn borrowed(value: &Option<Option<String>>) -> Option<Option<&str>> {
    value.as_ref().map(|inner| inner.as_deref())
}

pub(super) async fn execute(i: &Invocation, client: &mut Client) -> Result<CliOutput, CliError> {
    let command = path(i);
    let allowed: &[&str] = match command.as_str() {
        "mates consent" => &["yes"],
        "report-issue create" => &["title", "body"],
        "privacy debug-logs share" => &["yes", "confirm", "duration"],
        "ai models set-defaults" => &["simple", "complex", "most-demanding"],
        _ => &[],
    };
    handlers::flags(i, allowed)?;
    match command.as_str() {
        "mates list" => mates_list(i.boolean("json")),
        "mates info" => mate_info(
            positional(i, 0).ok_or_else(|| {
                missing("Missing mate ID. Example: openmates settings mates info software_development")
            })?,
            i.boolean("json"),
        ),
        "mates consent" => {
            if !confirm(i, "Record consent for mate settings? [y/N] ").await? {
                return Ok(text_output("Aborted.\n".into()));
            }
            mutation(i, &client.account().record_mates_consent().await?)
        }
        "report-issue create" => {
            let (Some(title), Some(body)) = (i.text("title"), i.text("body")) else {
                return Err(missing("Provide --title and --body."));
            };
            if title.is_empty() || body.is_empty() {
                return Err(missing("Provide --title and --body."));
            }
            report_created(i, &client.account().report_issue(title, body).await?)
        }
        "report-issue status" => {
            let id = positional(i, 0).ok_or_else(|| missing("Missing issue ID."))?;
            result(i, &client.account().report_issue_status(id).await?)
        }
        "privacy auto-delete chats set" => {
            let period = positional(i, 0).ok_or_else(|| {
                missing("Missing period. Example: openmates settings privacy auto-delete chats set 90d")
            })?;
            mutation(i, &client.account().set_chat_auto_delete(period).await?)
        }
        "privacy debug-logs share" => {
            if !i.boolean("confirm")
                && !confirm(i, "Share debug logs with OpenMates support? [y/N] ").await?
            {
                return Ok(text_output("Aborted.\n".into()));
            }
            let duration = i.text("duration").unwrap_or("1h");
            mutation(i, &client.account().share_debug_logs(duration).await?)
        }
        _ => {
            let simple = model_default(i, "simple")?;
            let complex = model_default(i, "complex")?;
            let demanding = model_default(i, "most-demanding")?;
            mutation(
                i,
                &client
                    .account()
                    .set_ai_model_defaults(borrowed(&simple), borrowed(&complex), borrowed(&demanding))
                    .await?,
            )
        }
    }
}

#[cfg(test)]
#[path = "settings_extra_tests.rs"]
mod tests;
