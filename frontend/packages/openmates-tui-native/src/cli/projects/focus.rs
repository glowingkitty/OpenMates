//! `projects settings <project> focus activate|deactivate --chat <chat-id>`
//! (npm projects settings focus branch). Full chat UUIDs only.
use super::*;

pub(super) async fn execute(
    i: &Invocation,
    service: &mut Projects<'_>,
) -> Result<CliOutput, CliError> {
    check(i, &["chat"])?;
    let contract = |code: &'static str, message: String| CliError::Contract { code, message };
    let project = input::positional(i, 0, "Project ID")?;
    let chat_target = i
        .text("chat")
        .map(str::trim)
        .filter(|chat| !chat.is_empty())
        .ok_or_else(|| CliError::Invalid("Missing --chat <chat-id>.".into()))?;
    let chat = uuid::Uuid::parse_str(chat_target)
        .ok()
        .filter(|id| id.to_string() == chat_target.to_ascii_lowercase())
        .map(|id| id.to_string())
        .ok_or_else(|| CliError::Unsupported {
            command: i.command_path(),
            reason: "Use the full hyphenated chat UUID. Short IDs, slugs and titles are not ported for this command.".into(),
        })?;
    if i.path.last().map(String::as_str) == Some("deactivate") {
        let project_id = service.show(project).await?["project_id"]
            .as_str()
            .ok_or(CliError::Client(Error::Protocol))?
            .to_owned();
        let active = service.active_focus(&chat).await?;
        if active.is_object() && active["project_id"] != project_id.as_str() {
            return Err(contract(
                "project_focus_conflict",
                format!("Chat '{chat_target}' has a different Project focus active."),
            ));
        }
        service.deactivate_focus(&chat).await?;
        return output(
            i,
            json!({"active":false,"project_id":project_id,"chat_id":chat}),
            format!("Project focus deactivated for chat {chat}."),
        );
    }
    let name = service.show(project).await?["name"]
        .as_str()
        .unwrap_or("")
        .to_owned();
    let focus = service.activate_focus(project, &chat).await?;
    output(
        i,
        json!({"focus":focus}),
        format!("Project focus activated for {name} in chat {chat}."),
    )
}

#[cfg(test)]
#[path = "focus_tests.rs"]
mod tests;
