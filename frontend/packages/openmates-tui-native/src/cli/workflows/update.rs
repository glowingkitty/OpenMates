//! Local authoring input and terminal policy; encrypted binding effects are SDK-owned.
use super::*;
use openmates_sdk::work::{ProjectFilters, WorkflowPatch};
use std::io::{IsTerminal, Write};

pub(super) async fn approve(i: &Invocation, path: String, cancel: CancellationToken) -> Result<bool, Error> {
    if cancel.is_cancelled() {
        return Err(Error::Cancelled);
    }
    if i.boolean("yes") {
        return Ok(true);
    }
    if i.boolean("json") || !std::io::stdin().is_terminal() {
        return Ok(false);
    }
    // Await cancellation and native events, without spawning std::stdin reads.
    // The terminal stays in its original mode.
    use crossterm::event::{Event, EventStream, KeyCode, KeyEventKind, KeyModifiers};
    use futures_util::StreamExt;
    eprint!("Write Workflow YAML to {path}? [y/N] ");
    std::io::stderr().flush().map_err(|_| Error::Io)?;
    let mut events = EventStream::new();
    let mut answer = String::new();
    loop {
        tokio::select! {biased;
            _=cancel.cancelled()=>return Err(Error::Cancelled),
            event=events.next()=>match event{
                Some(Ok(Event::Key(key))) if key.kind!=KeyEventKind::Release=>match key.code{
                    KeyCode::Char('c') if key.modifiers.contains(KeyModifiers::CONTROL)=>{cancel.cancel();return Err(Error::Cancelled)},
                    KeyCode::Enter=>return Ok(matches!(answer.trim().to_ascii_lowercase().as_str(),"y"|"yes")),
                    KeyCode::Esc=>return Ok(false),
                    KeyCode::Backspace=>{answer.pop();},
                    KeyCode::Char(c) if !c.is_control()&&answer.len()<32=>answer.push(c),
                    _=>{},
                },
                Some(Ok(_))=>{},Some(Err(_))=>return Err(Error::Io),None=>return Ok(false),
            },
        }
    }
}
pub(super) async fn execute(
    i: &Invocation,
    client: &mut Client,
    cancel: CancellationToken,
) -> Result<CliOutput, CliError> {
    check(i, &["file", "slug", "source-chat", "yes"])?;
    if i.boolean("personal") && i.has("team") {
        return Err(CliError::Invalid(
            "Choose --personal or --team, not both.".into(),
        ));
    }
    let id = input::positional(i, 0, "Workflow ID")?;
    if i.positionals.len() != 1 {
        return Err(CliError::Invalid(
            "Use workflows update <id> --file workflow.yml.".into(),
        ));
    }
    let source = zeroize::Zeroizing::new(files::read(input::required(i, "file")?, false)?);
    if cancel.is_cancelled() {
        return Err(Error::Cancelled.into());
    }
    let team = if i.boolean("personal") {
        None
    } else {
        input::text(i, "team")?
            .map(str::to_owned)
            .or_else(|| client.session().and_then(|s| s.active_team_id.clone()))
    };
    client.set_operation_cancel(cancel.clone());
    let mut result = client
        .workflows()
        .with_filters(WorkflowFilters {
            personal: i.boolean("personal"),
            team_id: team.clone(),
            ..Default::default()
        })
        .update_from_yaml(id, &source)
        .await?;
    if let Some(slug) = input::text(i, "slug")? {
        let id = result["workflow"]["id"]
            .as_str()
            .ok_or(Error::Protocol)?
            .to_owned();
        let workflow = client
            .workflows()
            .with_filters(WorkflowFilters {
                personal: i.boolean("personal"),
                team_id: team.clone(),
                ..Default::default()
            })
            .update(
                &id,
                WorkflowPatch {
                    slug: Some(slug.into()),
                    ..Default::default()
                },
            )
            .await?;
        result["workflow"] = workflow;
    }
    if cancel.is_cancelled() {
        return Err(Error::Cancelled.into());
    }
    let flow = &result["workflow"];
    let id = flow["id"].as_str().ok_or(Error::Protocol)?;
    let version = flow["current_version_id"].as_str().ok_or(Error::Protocol)?;
    let saves = client
        .projects()
        .with_filters(ProjectFilters {
            personal: i.boolean("personal"),
            team_id: team,
            ..Default::default()
        })
        .sync_workflow_files(
            id,
            version,
            input::text(i, "source-chat")?,
            openmates_sdk::work::serialize_workflow_file,
            |path| approve(i, path, cancel.clone()),
        )
        .await?;
    result["remote_file_saves"] = serde_json::to_value(&saves).map_err(|_| Error::Protocol)?;
    let text = render(&result);
    output(i, result, text)
}
fn render(result: &Value) -> String {
    let mut text = format!(
        "{}\nReady to enable: {}",
        workflow_text(&result["workflow"]),
        if result["validation"]["enable_ready"] == true {
            "yes"
        } else {
            "no"
        }
    );
    for warning in result["warnings"].as_array().into_iter().flatten() {
        text.push_str(&format!(
            "\nWarning: {}",
            warning["message"]
                .as_str()
                .or(warning["code"].as_str())
                .unwrap_or("Workflow authoring warning")
        ));
    }
    for save in result["remote_file_saves"].as_array().into_iter().flatten() {
        text.push_str(&format!(
            "\nRemote YAML {}: {}{}",
            save["status"].as_str().unwrap_or("failed"),
            save["project_id"].as_str().unwrap_or(""),
            save["error"]
                .as_str()
                .map(|v| format!(" ({v})"))
                .unwrap_or_default()
        ));
    }
    for diagnostic in result["validation"]["diagnostics"]
        .as_array()
        .into_iter()
        .flatten()
    {
        text.push_str(&format!(
            "\n  - {}: {}",
            diagnostic["path"].as_str().unwrap_or("$"),
            diagnostic["message"]
                .as_str()
                .or(diagnostic["code"].as_str())
                .unwrap_or("input required")
        ));
    }
    text
}

#[cfg(test)]
mod tests;
