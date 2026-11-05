//! `mentions list` / `mentions search` option catalog.
//!
//! Pure port of `openmates-cli/src/mentions.ts::listMentionOptions` plus the
//! fuzzy filter in `cli.ts::handleMentions`. No I/O: callers supply the
//! `MentionContext` (see `Client::mention_options`).
use crate::mentions::{
    is_available_chat_model, AppInfo, MentionContext, MentionType, MODEL_ALIASES, NamedEntry,
};
use serde::Serialize;

/// One selectable `@mention`. Serialises with the npm field names.
#[derive(Clone, Debug, PartialEq, Eq, Serialize)]
pub struct MentionOption {
    #[serde(rename = "type")]
    pub kind: MentionType,
    #[serde(rename = "displayName")]
    pub display_name: String,
    pub description: String,
}

/// Types accepted by `mentions list --type`, in npm order.
pub const LISTABLE_TYPES: &[&str] =
    &["model", "model_alias", "mate", "skill", "focus_mode", "settings_memory"];

/// Parse a `--type` value; `None` for anything outside [`LISTABLE_TYPES`].
pub fn parse_listable_type(value: &str) -> Option<MentionType> {
    Some(match value {
        "model" => MentionType::Model,
        "model_alias" => MentionType::ModelAlias,
        "mate" => MentionType::Mate,
        "skill" => MentionType::Skill,
        "focus_mode" => MentionType::FocusMode,
        "settings_memory" => MentionType::SettingsMemory,
        _ => return None,
    })
}

/// mentions.ts `capitalize`: split on whitespace/underscore runs, upper-case each first letter.
fn capitalize(value: &str) -> String {
    value
        .split(|c: char| c.is_whitespace() || c == '_')
        .map(|word| {
            let mut chars = word.chars();
            chars
                .next()
                .map(|first| first.to_uppercase().chain(chars).collect::<String>())
                .unwrap_or_default()
        })
        .collect::<Vec<_>>()
        .join(" ")
}

fn dashed(value: &str) -> String {
    capitalize(value).split_whitespace().collect::<Vec<_>>().join("-")
}

/// Every mention the current catalog offers, optionally restricted to one type.
pub fn list_mention_options(
    context: &MentionContext,
    filter: Option<MentionType>,
    today: &str,
) -> Vec<MentionOption> {
    let wants = |kind: MentionType| filter.is_none_or(|f| f == kind);
    let mut options = vec![];
    if wants(MentionType::ModelAlias) {
        for (alias, model_id) in MODEL_ALIASES {
            let name = context
                .models
                .iter()
                .find(|m| m.id == *model_id && is_available_chat_model(m, today))
                .map_or(*model_id, |m| m.name.as_str());
            let mut chars = alias.chars();
            let head: String = chars
                .next()
                .map(|c| c.to_uppercase().chain(chars).collect())
                .unwrap_or_default();
            options.push(MentionOption {
                kind: MentionType::ModelAlias,
                display_name: format!("@{head}"),
                description: format!("Alias \u{2192} {name}"),
            });
        }
    }
    if wants(MentionType::Model) {
        for model in context.models.iter().filter(|m| is_available_chat_model(m, today)) {
            options.push(MentionOption {
                kind: MentionType::Model,
                display_name: format!("@{}", model.name.split_whitespace().collect::<Vec<_>>().join("-")),
                description: format!("Model: {}", model.name),
            });
        }
    }
    if wants(MentionType::Mate) {
        for (category, name) in &context.mates {
            options.push(MentionOption {
                kind: MentionType::Mate,
                display_name: format!("@{name}"),
                description: format!("Mate: {}", capitalize(&category.replace('_', " "))),
            });
        }
    }
    let per_app = |kind: MentionType,
                   label: &str,
                   pick: fn(&AppInfo) -> &Vec<NamedEntry>,
                   skip_ai_ask: bool,
                   options: &mut Vec<MentionOption>| {
        if !wants(kind) {
            return;
        }
        for app in &context.apps {
            for entry in pick(app) {
                if skip_ai_ask && app.id == "ai" && entry.id == "ask" {
                    continue;
                }
                options.push(MentionOption {
                    kind,
                    display_name: format!("@{}-{}", capitalize(&app.name), dashed(&entry.name)),
                    description: format!(
                        "{label}: {} \u{2192} {}",
                        capitalize(&app.name),
                        capitalize(&entry.name)
                    ),
                });
            }
        }
    };
    per_app(MentionType::Skill, "Skill", skills, true, &mut options);
    per_app(MentionType::FocusMode, "Focus", focus_modes, false, &mut options);
    per_app(MentionType::SettingsMemory, "Memory", memories, false, &mut options);
    options
}

fn skills(app: &AppInfo) -> &Vec<NamedEntry> {
    &app.skills
}
fn focus_modes(app: &AppInfo) -> &Vec<NamedEntry> {
    &app.focus_modes
}
fn memories(app: &AppInfo) -> &Vec<NamedEntry> {
    &app.settings_and_memories
}

/// `mentions search`: case-insensitive match of the query against display name or
/// description with `[\s_-]` removed (and `@` from names), first 15 hits.
pub fn search_mention_options(options: Vec<MentionOption>, query: &str) -> Vec<MentionOption> {
    let strip = |s: &str, at: bool| -> String {
        s.to_lowercase()
            .chars()
            .filter(|c| !(c.is_whitespace() || *c == '_' || *c == '-' || (at && *c == '@')))
            .collect()
    };
    let needle = strip(query, false);
    options
        .into_iter()
        .filter(|o| strip(&o.display_name, true).contains(&needle) || strip(&o.description, false).contains(&needle))
        .take(15)
        .collect()
}

#[cfg(test)]
#[path = "mentions_list_tests.rs"]
mod tests;
