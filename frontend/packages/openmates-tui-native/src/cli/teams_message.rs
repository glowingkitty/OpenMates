//! CLI adapter for `openmates teams member(s) message <team-id> <member-hash> [text]`,
//! mirroring npm cli.ts handleTeams: parse, open (or create) the OMDM1 Direct chat
//! in shared Rust, then send the optional text through the ordinary saved-chat
//! send path in that Team. The caller's previous Team/Personal context is always
//! restored. Implements `feature.teams` teams.direct-chat.* within `surface.cli`.
use super::{CliError, CliOutput, Invocation, handlers, send};
use crate::{client::Client, error::Error};
use serde_json::{Value, json};
use tokio_util::sync::CancellationToken;

pub(super) fn supported(invocation: &Invocation) -> bool {
    matches!(
        invocation.command_path().as_str(),
        "teams member message" | "teams members message"
    )
}

/// Validated `<team-id> <member-hash> [text]`; npm joins the remaining words.
pub(super) fn arguments(invocation: &Invocation) -> Result<(String, String, String), CliError> {
    handlers::flags(invocation, &[])?;
    let team = invocation
        .positionals
        .first()
        .filter(|value| !value.trim().is_empty())
        .ok_or_else(|| CliError::Invalid("Missing required <team-id>.".into()))?;
    let member = invocation
        .positionals
        .get(1)
        .filter(|value| !value.trim().is_empty())
        .ok_or_else(|| CliError::Invalid("Missing required <member-hash>.".into()))?;
    uuid::Uuid::parse_str(team)
        .map_err(|_| CliError::Invalid("A Team ID and member hash are required.".into()))?;
    if member.len() != 64
        || !member
            .bytes()
            .all(|byte| byte.is_ascii_digit() || (b'a'..=b'f').contains(&byte))
    {
        return Err(CliError::Invalid(
            "A Team ID and member hash are required.".into(),
        ));
    }
    let text = invocation.positionals.get(2..).unwrap_or(&[]).join(" ");
    Ok((team.clone(), member.clone(), text.trim().to_owned()))
}

pub(super) async fn execute(
    invocation: &Invocation,
    client: &mut Client,
    cancel: CancellationToken,
) -> Result<CliOutput, CliError> {
    let (team, member, text) = arguments(invocation)?;
    let original = client
        .session()
        .and_then(|session| session.active_team_id.clone());
    client.set_team(Some(&team))?;
    client.set_operation_cancel(cancel.clone());
    let result = Box::pin(message(invocation, client, cancel, &member, &text)).await;
    if client.session().is_some() {
        client.set_team(original.as_deref())?;
    }
    result
}

async fn message(
    invocation: &Invocation,
    client: &mut Client,
    cancel: CancellationToken,
    member: &str,
    text: &str,
) -> Result<CliOutput, CliError> {
    let chat = client.open_team_direct_chat(member).await?;
    let chat_value = serde_json::to_value(&chat).map_err(|_| CliError::Client(Error::Protocol))?;
    let response = if text.is_empty() {
        None
    } else {
        // npm sendMessage is non-streaming: suppress content, keep the result.
        let send = Invocation {
            path: vec!["chats".into(), "send".into()],
            positionals: vec![text.to_owned()],
            flags: [
                ("chat".to_owned(), Value::String(chat.id.clone())),
                ("json".to_owned(), Value::Bool(true)),
            ]
            .into_iter()
            .collect(),
        };
        let observed = send::observe_saved(&send, client, cancel).await?;
        Some(send::outcome_json(&observed.outcome)?)
    };
    if invocation.boolean("json") {
        let mut value = json!({"chat_id":chat.id,"chat":chat_value});
        if let Some(response) = response {
            value["response"] = response;
        }
        return CliOutput::json(&value);
    }
    Ok(CliOutput::text(if text.is_empty() {
        format!("Direct chat: {}", chat.id)
    } else {
        format!("Message sent in direct chat {}", chat.id)
    }))
}

#[cfg(test)]
#[path = "teams_message_tests.rs"]
mod tests;
