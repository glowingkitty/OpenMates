//! `openmates mentions list|search` (npm handleMentions). Catalog building and
//! filtering live in the shared SDK (`openmates_sdk::mentions_list`); this
//! adapter only parses flags and renders the npm text layout.
use super::{CliError, CliOutput, Invocation, handlers};
use crate::client::Client;
use openmates_sdk::mentions::{self, MentionType};
use openmates_sdk::mentions_list::{
    LISTABLE_TYPES, MentionOption, list_mention_options, parse_listable_type, search_mention_options,
};

pub(super) fn supported(i: &Invocation) -> bool {
    matches!(i.command_path().as_str(), "mentions list" | "mentions search")
}

fn type_label(kind: MentionType) -> &'static str {
    match kind {
        MentionType::ModelAlias => "Model Aliases",
        MentionType::Model => "AI Models",
        MentionType::Mate => "Mates",
        MentionType::Skill => "Skills",
        MentionType::FocusMode => "Focus Modes",
        MentionType::SettingsMemory => "Memories",
        MentionType::SettingsMemoryEntry => "Memory Entries",
    }
}

/// Grouped by type in first-seen order, `displayName` padded to 35 columns.
fn list_text(options: &[MentionOption]) -> String {
    let mut order: Vec<MentionType> = vec![];
    for option in options {
        if !order.contains(&option.kind) {
            order.push(option.kind);
        }
    }
    let mut text = String::new();
    for kind in order {
        text.push_str(&format!("\n{}\n", type_label(kind)));
        for option in options.iter().filter(|o| o.kind == kind) {
            text.push_str(&format!("  {:<35} {}\n", option.display_name, option.description));
        }
    }
    text
}

fn search_text(query: &str, matches: &[MentionOption]) -> String {
    let mut text = format!("\nMatches for '{query}':\n");
    for m in matches {
        let label = type_label_raw(m.kind);
        text.push_str(&format!("  {:<35} {} ({label})\n", m.display_name, m.description));
    }
    text
}

/// npm prints `type.replace("_", " ")` (first underscore only).
fn type_label_raw(kind: MentionType) -> String {
    let value = serde_json::to_value(kind).ok().and_then(|v| v.as_str().map(String::from)).unwrap_or_default();
    value.replacen('_', " ", 1)
}

pub(super) async fn execute(i: &Invocation, client: &mut Client) -> Result<CliOutput, CliError> {
    let search = i.command_path() == "mentions search";
    handlers::flags(i, if search { &[] } else { &["type"] })?;
    let today = mentions::today_utc();
    if search {
        let query = i.positionals.join(" ");
        let query = query.trim();
        if query.is_empty() {
            return Err(CliError::Invalid(
                "Missing search query. Usage: openmates mentions search <query>".into(),
            ));
        }
        let context = client.mention_catalog().await?;
        let matches = search_mention_options(list_mention_options(&context, None, &today), query);
        if i.boolean("json") {
            return CliOutput::json(&serde_json::to_value(&matches).map_err(|_| crate::error::Error::Protocol)?);
        }
        if matches.is_empty() {
            return Ok(CliOutput::text(format!("No mentions matching '{query}'.")));
        }
        return Ok(CliOutput::text(search_text(query, &matches)));
    }
    let filter = match i.text("type") {
        Some(value) => Some(parse_listable_type(value).ok_or_else(|| {
            CliError::Invalid(format!("Invalid type '{value}'. Valid types: {}", LISTABLE_TYPES.join(", ")))
        })?),
        None => None,
    };
    let context = client.mention_catalog().await?;
    let options = list_mention_options(&context, filter, &today);
    if i.boolean("json") {
        return CliOutput::json(&serde_json::to_value(&options).map_err(|_| crate::error::Error::Protocol)?);
    }
    if options.is_empty() {
        let suffix = i.text("type").map(|t| format!(" for type '{t}'")).unwrap_or_default();
        return Ok(CliOutput::text(format!("No mentions available{suffix}.")));
    }
    Ok(CliOutput::text(list_text(&options)))
}

#[cfg(test)]
#[path = "mentions_cmd_tests.rs"]
mod tests;
