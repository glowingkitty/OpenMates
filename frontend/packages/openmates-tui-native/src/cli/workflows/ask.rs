//! Exact CLI natural syntax over the shared Workflow ask operation.
use super::*;
use openmates_sdk::work::{
    WorkflowAction, WorkflowAskAction, WorkflowAskOptions, WorkflowAskUpdate, WorkflowPatch,
};
use regex::Regex;
fn pattern(value: &str) -> Regex {
    Regex::new(value).expect("constant Workflow ask syntax")
}
fn unquote(value: &str) -> &str {
    let value = value.trim();
    if value.len() >= 2
        && ((value.starts_with('"') && value.ends_with('"'))
            || (value.starts_with('\'') && value.ends_with('\'')))
    {
        &value[1..value.len() - 1]
    } else {
        value
    }
}
fn target(instruction: &str) -> Option<String> {
    let regex = pattern(r#"(?i)@workflow:("[^"]+"|'[^']+'|[^\s,;]+)"#);
    let captures = regex.captures(instruction)?;
    let value = unquote(captures.get(1)?.as_str())
        .trim_end_matches(['.', ')', '!', '?'])
        .trim();
    (!value.is_empty()).then(|| value.to_owned())
}
fn action(instruction: &str) -> Option<WorkflowAction> {
    if pattern(r"(?i)\bdelete\b|\bremove\s+@workflow:").is_match(instruction) {
        Some(WorkflowAction::Delete)
    } else if pattern(r"(?i)\b(disable|turn\s+off|switch\s+off|pause)\b").is_match(instruction) {
        Some(WorkflowAction::Disable)
    } else if pattern(r"(?i)\b(enable|turn\s+on|switch\s+on|resume)\b").is_match(instruction) {
        Some(WorkflowAction::Enable)
    } else {
        None
    }
}
fn rename(instruction: &str) -> Option<String> {
    if !pattern(r"(?i)\b(rename|retitle|title|name|call)\b").is_match(instruction) {
        return None;
    }
    let regex = pattern(r"(?i)\bto\s+(.+)$");
    let captures = regex.captures(instruction)?;
    let value = unquote(captures.get(1)?.as_str())
        .trim_end_matches('.')
        .trim();
    (!value.is_empty()).then(|| value.to_owned())
}
fn normalize(value: &str) -> String {
    value
        .split_whitespace()
        .collect::<Vec<_>>()
        .join(" ")
        .to_lowercase()
}
fn unique(rows: &[&Value]) -> Result<Option<String>, CliError> {
    match rows {
        [] => Ok(None),
        [row] => Ok(Some(row["id"].as_str().ok_or(Error::Protocol)?.to_owned())),
        _ => Err(CliError::Contract {
            code: "ambiguous_workflow",
            message: "Workflow selector is ambiguous.".into(),
        }),
    }
}
fn lookup(rows: &[Value], selector: &str) -> Result<Option<String>, CliError> {
    if let Some(row) = rows.iter().find(|row| row["id"] == selector) {
        return unique(&[row]);
    }
    if selector.len() >= 8 {
        let matches: Vec<_> = rows
            .iter()
            .filter(|row| {
                row["id"]
                    .as_str()
                    .is_some_and(|id| id.to_lowercase().starts_with(&selector.to_lowercase()))
            })
            .collect();
        if !matches.is_empty() {
            return unique(&matches);
        }
    }
    let slug = openmates_sdk::crypto::normalize_object_slug(selector).ok();
    let matches: Vec<_> = rows
        .iter()
        .filter(|row| {
            row["slug"]
                .as_str()
                .is_some_and(|value| Some(value) == slug.as_deref())
        })
        .collect();
    if !matches.is_empty() {
        return unique(&matches);
    }
    let matches: Vec<_> = rows
        .iter()
        .filter(|row| {
            row["title"]
                .as_str()
                .is_some_and(|title| normalize(title) == normalize(selector))
        })
        .collect();
    // Legacy title lookup is unresolved unless exactly one title matches.
    if matches.len() == 1 {
        unique(&matches)
    } else {
        Ok(None)
    }
}
fn input(i: &Invocation) -> Result<String, CliError> {
    check(
        i,
        &[
            "text",
            "graph",
            "description",
            "enabled",
            "run-content-retention",
            "auto-approve",
            "auto-approve-memories",
            "no-pii-detection",
            "response-timeout-seconds",
        ],
    )?;
    let positional = i.positionals.join(" ");
    let instruction = input::text(i, "text")?.unwrap_or(&positional).trim();
    if instruction.is_empty() {
        return Err(CliError::Invalid(
            "Missing ask instruction. Example: openmates workflows ask \"alert me if it rains\"."
                .into(),
        ));
    }
    Ok(instruction.into())
}
fn create_options(i: &Invocation, instruction: &str) -> Result<WorkflowAskOptions, CliError> {
    if !["graph", "description", "enabled", "run-content-retention"]
        .iter()
        .any(|flag| i.has(flag) && (*flag != "enabled" || i.boolean("enabled")))
    {
        return Ok(Default::default());
    }
    let graph = json_input(i,"graph")?.unwrap_or(serde_json::from_value(json!({"version":1,"trigger_node_id":"manual-trigger",
        "nodes":[{"id":"manual-trigger","type":"manual_trigger","title":"Manual trigger"},{"id":"end","type":"end","title":"End"}],
        "edges":[{"from":"manual-trigger","to":"end"}]})).map_err(|_|Error::Protocol)?);
    Ok(WorkflowAskOptions {
        create: Some(WorkflowCreate {
            title: instruction.chars().take(200).collect(),
            description: input::text(i, "description")?.map(str::to_owned),
            graph,
            enabled: i.boolean("enabled"),
            run_content_retention: retention(i)?,
            source: Some("cli_ask".into()),
            created_by_assistant: true,
            ..Default::default()
        }),
        ..Default::default()
    })
}
async fn options(
    i: &Invocation,
    service: &mut Workflows<'_>,
    instruction: &str,
) -> Result<WorkflowAskOptions, CliError> {
    let Some(selector) = target(instruction) else {
        return create_options(i, instruction);
    };
    let rows = service.list().await?;
    let Some(id) = lookup(&rows, &selector)? else {
        // SDK resolves this original selector canonically before transport; a
        // UUID absent from the reusable library remains an explicit selection.
        return Ok(WorkflowAskOptions {
            selected_object_id: Some(selector),
            ..Default::default()
        });
    };
    if let Some(action) = action(instruction) {
        return Ok(WorkflowAskOptions {
            exact_action: Some(WorkflowAskAction {
                workflow_id: id,
                action,
                confirmed: true,
            }),
            ..Default::default()
        });
    }
    if let Some(title) = rename(instruction) {
        return Ok(WorkflowAskOptions {
            exact_update: Some(WorkflowAskUpdate {
                workflow_id: id,
                patch: WorkflowPatch {
                    title: Some(title),
                    ..Default::default()
                },
            }),
            ..Default::default()
        });
    }
    Ok(WorkflowAskOptions {
        selected_object_id: Some(id),
        ..Default::default()
    })
}
pub(super) async fn execute_cookie(
    i: &Invocation,
    client: &mut Client,
    cancel: CancellationToken,
) -> Result<CliOutput, CliError> {
    let instruction = input(i)?;
    if cancel.is_cancelled() {
        return Err(Error::Cancelled.into());
    }
    if client.session().is_none() {
        return Err(Error::Authentication.into());
    }
    if i.boolean("personal") && i.has("team") {
        return Err(CliError::Invalid(
            "Choose --personal or --team, not both.".into(),
        ));
    }
    let team = if i.boolean("personal") {
        None
    } else {
        input::text(i, "team")?.map(str::to_owned).or_else(|| {
            client
                .session()
                .and_then(|session| session.active_team_id.clone())
        })
    };
    // /workflows/ask is Personal-only. Do not list Team content and later fall
    // through into a Personal request or a different-context fallback chat.
    if team.is_some() {
        return Err(Error::Unavailable {
            code: "workflow_unavailable",
            reason: "TEAM_WORKFLOW_OPERATION_UNAVAILABLE",
        }
        .into());
    }
    client.set_operation_cancel(cancel.clone());
    let value = {
        let mut service = client.workflows().with_filters(WorkflowFilters {
            personal: true,
            ..Default::default()
        });
        let options = options(i, &mut service, &instruction).await?;
        if cancel.is_cancelled() {
            return Err(Error::Cancelled.into());
        }
        service.ask(&instruction, options).await?
    };
    super::super::tasks::workspace_ask_output(i, client, cancel, instruction, value, "workflow")
        .await
}
#[cfg(test)]
mod tests;
