//! `apps examples <app-id> [skill-id]` over the embedded example-chat index
//! (generated from the shared registry by
//! scripts/generate_cli_example_chat_index.py). Local, no account.
use super::super::{CliError, CliOutput, Invocation, handlers};
use serde::Deserialize;
use serde_json::{Value, json};
use std::sync::OnceLock;

#[derive(Deserialize)]
pub(super) struct ExampleChat {
    pub id: String,
    pub slug: String,
    pub title: Option<String>,
    pub summary: Option<String>,
    pub updated_at: Option<i64>,
    pub category: Option<String>,
    pub app_skill_examples: Vec<String>,
}
#[derive(Deserialize)]
struct Index {
    chats: Vec<ExampleChat>,
}
fn index() -> &'static [ExampleChat] {
    static INDEX: OnceLock<Index> = OnceLock::new();
    &INDEX
        .get_or_init(|| {
            serde_json::from_str(include_str!("../../../assets/example-chat-index.json"))
                .expect("generated example-chat index must be valid")
        })
        .chats
}
/// npm listExampleChatsForSkill / listExampleChatsForApp.
pub(super) fn matching<'a>(
    chats: &'a [ExampleChat],
    app: &str,
    skill: Option<&str>,
) -> Vec<&'a ExampleChat> {
    let key = skill.map(|skill| format!("{app}.{skill}"));
    let prefix = format!("{app}.");
    chats
        .iter()
        .filter(|chat| match &key {
            Some(key) => chat.app_skill_examples.iter().any(|k| k == key),
            None => chat
                .app_skill_examples
                .iter()
                .any(|k| k.starts_with(&prefix)),
        })
        .collect()
}
fn to_json(chat: &ExampleChat) -> Value {
    json!({
        "chat_id": chat.id, "short_id": chat.id, "slug": chat.slug, "title": chat.title,
        "summary": chat.summary, "updated_at": chat.updated_at, "category": chat.category,
        "source": "example", "linked_app_skills": chat.app_skill_examples,
        "commands": {
            "show": format!("openmates chats show {}", chat.id),
            "open": format!("openmates chats open {}", chat.slug),
        },
    })
}
/// npm printExampleChatsForSkill (full listing).
pub(super) fn text(app: &str, skill: Option<&str>, examples: &[&ExampleChat]) -> String {
    let label = skill.map_or_else(|| app.to_owned(), |skill| format!("{app}/{skill}"));
    let mut out = format!("\x1b[1mExample chats for {label}\x1b[0m\n");
    if examples.is_empty() {
        out.push_str(&format!("\nNo example chats are linked to {label} yet.\n"));
        match skill {
            Some(skill) => out.push_str(&format!(
                "\nInspect the skill:\n  openmates apps skill-info {app} {skill}\n"
            )),
            None => out.push_str(&format!(
                "\nInspect available skills:\n  openmates apps {app}\n"
            )),
        }
        return out;
    }
    out.push('\n');
    let prefix = format!("{app}.");
    for (n, chat) in examples.iter().enumerate() {
        out.push_str(&format!(
            "{}. {}\n",
            n + 1,
            chat.title.as_deref().unwrap_or(&chat.id)
        ));
        out.push_str(&format!("   {}\n", chat.id));
        if let Some(summary) = chat.summary.as_deref().filter(|s| !s.is_empty()) {
            out.push_str(&format!("   {summary}\n"));
        }
        if skill.is_none() {
            let linked = chat
                .app_skill_examples
                .iter()
                .filter(|k| k.starts_with(&prefix))
                .cloned()
                .collect::<Vec<_>>()
                .join(", ");
            out.push_str(&format!("   Skills: {linked}\n"));
        }
        out.push_str(&format!("   Show: openmates chats show {}\n", chat.id));
        out.push_str(&format!("   Open: openmates chats open {}\n", chat.slug));
    }
    out
}
pub(super) fn execute(i: &Invocation) -> Result<CliOutput, CliError> {
    handlers::flags(i, &[])?;
    let Some(app) = i.positionals.first().filter(|v| !v.is_empty()) else {
        return Err(CliError::Invalid(
            "Missing app ID.\n\nUsage: openmates apps examples <app-id> [skill-id] [--json]".into(),
        ));
    };
    let skill = i.positionals.get(1).map(String::as_str);
    let examples = matching(index(), app, skill);
    if i.boolean("json") {
        return CliOutput::json(&json!({
            "app_id": app, "skill_id": skill,
            "examples": examples.iter().map(|c| to_json(c)).collect::<Vec<_>>(),
        }));
    }
    Ok(CliOutput::text(text(app, skill, &examples)))
}

#[cfg(test)]
pub(super) fn embedded() -> &'static [ExampleChat] {
    index()
}
