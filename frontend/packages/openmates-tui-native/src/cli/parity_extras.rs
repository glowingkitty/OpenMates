//! Small npm-parity commands: bare command-group help, `help [command...]`,
//! `inspirations` and `apps travel booking-link`.
use super::{CliError, CliOutput, Invocation, handlers};
use crate::client::Client;
use serde_json::{Value, json};

/// Roots whose usage is the bare name (no `[--help]`), so `group_help.rs`
/// does not cover them; the generic group help in `execute_public` serves them.
const GROUPS: &[&str] = &["account", "e2e"];
const COMMANDS: &[&str] = &["inspirations", "apps travel booking-link"];

pub(super) fn is_public(i: &Invocation) -> bool {
    let path = i.command_path();
    path == "help" || (i.positionals.is_empty() && GROUPS.contains(&path.as_str()))
}
pub(super) fn supported(i: &Invocation) -> bool {
    is_public(i) || COMMANDS.contains(&i.command_path().as_str())
}

/// `help` prints the root help, `help <group> [sub]` the matching subcommand.
pub(super) fn help(i: &Invocation) -> Option<Result<CliOutput, CliError>> {
    if i.command_path() != "help" {
        return None;
    }
    let mut root = super::parser::command();
    let mut current = &mut root;
    for segment in &i.positionals {
        current = match current.find_subcommand_mut(segment) {
            Some(next) => next,
            None => {
                return Some(Err(CliError::Invalid(format!("Unknown command '{segment}'. Run 'openmates help'."))));
            }
        };
    }
    Some(Ok(CliOutput::text(current.render_long_help().to_string())))
}

pub(super) async fn execute(i: &Invocation, client: &mut Client) -> Result<CliOutput, CliError> {
    match i.command_path().as_str() {
        "inspirations" => inspirations(i, client).await,
        _ => booking_link(i, client).await,
    }
}

async fn inspirations(i: &Invocation, client: &mut Client) -> Result<CliOutput, CliError> {
    handlers::flags(i, &["lang"])?;
    let lang = i.text("lang").unwrap_or("en");
    let rows = client.daily_inspirations(lang).await?;
    let value = Value::Array(
        rows.iter()
            .map(|r| {
                json!({"id": r.id, "phrase": r.phrase, "title": r.title, "category": r.category,
                       "feature": r.feature_title.as_ref().map(|t| json!({"title": t})), "surface": r.surface})
            })
            .collect(),
    );
    handlers::output(i, value, inspirations_text(&rows, lang))
}

pub(super) fn inspirations_text(
    rows: &[openmates_sdk::client::overview::inspirations::Inspiration],
    lang: &str,
) -> String {
    if rows.is_empty() {
        return "No inspirations available for today.".into();
    }
    let suffix = if lang == "en" { String::new() } else { format!(", {lang}") };
    let mut out = format!("Daily Inspirations  (personalized{suffix})\n\n");
    for (n, r) in rows.iter().enumerate() {
        let label = if r.title.is_empty() { &r.phrase } else { &r.title };
        let category = if r.category.is_empty() { String::new() } else { format!(" [{}]", r.category) };
        out.push_str(&format!("{}. {label}{category}\n", n + 1));
        if !r.title.is_empty() && !r.phrase.is_empty() {
            out.push_str(&format!("   {}\n", r.phrase));
        }
        out.push('\n');
    }
    out
}

async fn booking_link(i: &Invocation, client: &mut Client) -> Result<CliOutput, CliError> {
    handlers::flags(i, &["token", "context"])?;
    if i.has("api-key") {
        return Err(CliError::Unsupported {
            command: i.command_path(),
            reason: "Booking links require an authenticated native session; --api-key is not supported yet.".into(),
        });
    }
    let token = i.text("token").ok_or_else(|| {
        CliError::Invalid("Missing --token flag. Usage: openmates apps travel booking-link --token \"<booking_token>\" [--context '<json>']".into())
    })?;
    let context = i
        .text("context")
        .map(|raw| {
            serde_json::from_str::<Value>(raw)
                .ok()
                .filter(Value::is_object)
                .ok_or_else(|| CliError::Invalid("Invalid --context JSON.".into()))
        })
        .transpose()?;
    let result = client.travel_booking_link(token, context).await?;
    render_booking(i, result)
}

pub(super) fn render_booking(i: &Invocation, result: Value) -> Result<CliOutput, CliError> {
    let url = result.get("booking_url").and_then(Value::as_str);
    if result.get("success") == Some(&Value::Bool(true)) && url.is_some() {
        let mut text = String::from("Travel > Booking Link");
        if let Some(c) = result.get("credits_charged").and_then(Value::as_u64).filter(|c| *c > 0) {
            text.push_str(&format!("  ({c} credits)"));
        }
        text.push_str(&format!("\nURL: {}\n", url.unwrap_or_default()));
        if let Some(p) = result.get("booking_provider").and_then(Value::as_str) {
            text.push_str(&format!("Provider: {p}\n"));
        }
        text.push_str("\nOpen this URL in your browser to complete the booking.");
        return handlers::output(i, result, text);
    }
    if i.boolean("json") {
        return CliOutput::json(&result);
    }
    let reason = result.get("error").and_then(Value::as_str).unwrap_or("no booking URL available for this flight");
    Err(CliError::Invalid(format!("Booking link not found: {reason}")))
}

#[cfg(test)]
#[path = "parity_extras_tests.rs"]
mod tests;
