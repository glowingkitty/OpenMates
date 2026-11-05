//! `teams move`: npm handleTeams "move" over the shared Rust workspace move.
//! Validation, wording and exit codes follow the npm handler; npm thrown
//! errors become `command_failed` (exit 1).
use super::{CliError, CliOutput, Invocation, handlers};
use crate::{client::Client, error::Error};
use openmates_sdk::work::{WorkspaceMoveError, WorkspaceMoveType};

pub(super) const COMMANDS: &[&str] = &["teams move"];

fn failed(message: impl Into<String>) -> CliError {
    CliError::Contract {
        code: "command_failed",
        message: message.into(),
    }
}
/// npm requiredStringFlag.
fn required<'a>(value: Option<&'a str>, label: &str) -> Result<&'a str, CliError> {
    value
        .map(str::trim)
        .filter(|v| !v.is_empty())
        .ok_or_else(|| failed(format!("Missing {label}.")))
}
fn positional(i: &Invocation, index: usize) -> Option<&str> {
    i.positionals.get(index).map(String::as_str)
}
/// npm parseWorkspaceMoveType.
pub(super) fn move_type(value: Option<&str>) -> Result<WorkspaceMoveType, CliError> {
    let name = required(value, "--type <chat|project|task|plan|workflow>")?;
    WorkspaceMoveType::parse(name)
        .ok_or_else(|| failed("Workspace type must be chat, project, task, plan, or workflow."))
}
/// Parsed `teams move` input: npm requireTeamId, then `--type`/`rest[1]`,
/// `--id`/`rest[2]` (positions are fixed even when `--team` is supplied).
pub(super) fn move_input(i: &Invocation) -> Result<(String, WorkspaceMoveType, String), CliError> {
    let team = required(
        i.text("team").or(i.text("team-id")).or(positional(i, 0)),
        "--team <team-id>",
    )?;
    let kind = move_type(i.text("type").or(positional(i, 1)))?;
    let id = required(i.text("id").or(positional(i, 2)), "--id <resource-id>")?;
    if !i.boolean("yes") && !i.boolean("confirm") {
        return Err(failed("Moving a workspace resource requires --yes."));
    }
    Ok((team.to_owned(), kind, id.to_owned()))
}

pub(super) async fn execute(i: &Invocation, client: &mut Client) -> Result<CliOutput, CliError> {
    handlers::flags(i, &["team", "team-id", "type", "id", "yes", "confirm"])?;
    let (team, kind, id) = move_input(i)?;
    if kind == WorkspaceMoveType::Chat {
        return Err(CliError::Unsupported {
            command: i.command_path(),
            reason: "Moving a chat needs its chat key from a synced personal chat cache, which the native one-shot CLI does not load; project, task, plan and workflow moves are ported.".into(),
        });
    }
    let result = client
        .move_workspace_to_team(kind, &id, &team)
        .await
        .map_err(|error| match error {
            WorkspaceMoveError::TeamKeyUnavailable => failed(format!(
                "Team key not available locally for team '{team}'. Run 'openmates teams show {team}' and try again."
            )),
            WorkspaceMoveError::Http(status) => {
                failed(format!("{} move failed with HTTP {status}", kind.as_str()))
            }
            WorkspaceMoveError::Sdk(Error::Invalid(message)) => failed(message),
            WorkspaceMoveError::Sdk(other) => CliError::Client(other),
        })?;
    if i.boolean("json") {
        CliOutput::json(&result)
    } else {
        Ok(CliOutput::text(format!(
            "{} moved to team {team}: {id}",
            kind.as_str()
        )))
    }
}

#[cfg(test)]
#[path = "teams_workspace_tests.rs"]
mod tests;
