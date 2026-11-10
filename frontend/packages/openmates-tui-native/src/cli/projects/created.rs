//! `projects created` and `projects undo-create`: the Project an assistant turn
//! created for a chat (`openmates.project_create_request` v1), CLI adapter only.
//! The core finds the record again from the chat's active focus and the
//! Project's encrypted settings and performs the undo; this file parses flags
//! and renders the card. Spec assertion: `projects.creation.assistant-inferred`.
use super::*;

/// Render the "Created project" card the way a chat turn prints it.
pub(in crate::cli) fn card_text(card: &Value) -> String {
    let field = |name: &str| super::super::terminal_text(card[name].as_str().unwrap_or(""));
    let chat = field("chatId");
    match card["status"].as_str() {
        Some("created") => format!(
            "Created project {} (files go to {}/). Undo: openmates projects undo-create --chat {chat}\n",
            field("name"),
            field("subfolder")
        ),
        Some("undone") => format!("Project {} was removed again (undone).\n", field("name")),
        _ => format!(
            "No project was created ({}); the assistant answered in the chat.\n",
            field("errorCode")
        ),
    }
}

fn chat_id(i: &Invocation) -> Result<String, CliError> {
    let target = i
        .text("chat")
        .map(str::trim)
        .filter(|chat| !chat.is_empty())
        .ok_or_else(|| CliError::Invalid("Missing --chat <chat-id>.".into()))?;
    uuid::Uuid::parse_str(target)
        .ok()
        .filter(|id| id.to_string() == target.to_ascii_lowercase())
        .map(|id| id.to_string())
        .ok_or_else(|| CliError::Unsupported {
            command: i.command_path(),
            reason: "Use the full hyphenated chat UUID.".into(),
        })
}

pub(super) async fn execute(
    i: &Invocation,
    service: &mut Projects<'_>,
) -> Result<CliOutput, CliError> {
    check(i, &["chat"])?;
    if !i.positionals.is_empty() {
        return Err(CliError::Invalid(
            "Use --chat <chat-id>; no positional arguments.".into(),
        ));
    }
    let chat = chat_id(i)?;
    if i.command_path() == "projects undo-create" {
        let mut card = serde_json::to_value(service.undo_created(&chat).await?)
            .map_err(|_| CliError::Client(Error::Protocol))?;
        card["status"] = json!("undone");
        card["undoAvailable"] = json!(false);
        let text = card_text(&card);
        return output(i, json!({"project": card}), text.trim_end().to_owned());
    }
    let Some(record) = service.created_for_chat(&chat).await? else {
        return Err(CliError::Contract {
            code: "no_created_project",
            message: format!("Chat {chat} has no assistant-created Project with an active focus."),
        });
    };
    let mut card = serde_json::to_value(record).map_err(|_| CliError::Client(Error::Protocol))?;
    card["status"] = json!("created");
    let text = card_text(&card);
    output(i, json!({"project": card}), text.trim_end().to_owned())
}

#[cfg(test)]
#[path = "created_tests.rs"]
mod tests;
