//! Legacy Workflow unlink output over the existing typed SDK operation.
use super::*;
use openmates_sdk::work::ProjectFilters;

fn selectors<'a>(
    i: &'a Invocation,
    cancel: &CancellationToken,
) -> Result<(&'a str, &'a str), CliError> {
    check(i, &[])?;
    if cancel.is_cancelled() {
        return Err(Error::Cancelled.into());
    }
    if i.boolean("personal") && i.has("team") {
        return Err(CliError::Invalid(
            "Choose --personal or --team, not both.".into(),
        ));
    }
    if i.positionals.len() != 2 {
        return Err(CliError::Invalid(
            "Use workflows <workflow-id> remove-from-project <project-id>.".into(),
        ));
    }
    Ok((
        input::positional(i, 0, "Workflow ID")?,
        input::positional(i, 1, "Project ID")?,
    ))
}
fn filters(i: &Invocation, team: Option<String>) -> (ProjectFilters, WorkflowFilters) {
    let personal = i.boolean("personal");
    let team_id = if personal { None } else { team };
    (
        ProjectFilters {
            personal,
            team_id: team_id.clone(),
            ..Default::default()
        },
        WorkflowFilters {
            personal,
            team_id,
            ..Default::default()
        },
    )
}
pub(super) async fn execute_cookie(
    i: &Invocation,
    client: &mut Client,
    cancel: CancellationToken,
) -> Result<CliOutput, CliError> {
    let (_, project) = selectors(i, &cancel)?;
    let team = input::text(i, "team")?.map(str::to_owned).or_else(|| {
        client
            .session()
            .and_then(|session| session.active_team_id.clone())
    });
    let (projects, workflows) = filters(i, team);
    client.set_operation_cancel(cancel.clone());
    // Resolve through the canonical typed namespace so slugs stay local and
    // legacy output contains the actual ID, even for a Project name selector.
    let project = client
        .projects()
        .with_filters(projects)
        .show(project)
        .await?;
    remove(
        i,
        client.workflows().with_filters(workflows),
        project,
        &cancel,
    )
    .await
}
pub(super) async fn execute_api_key(
    i: &Invocation,
    client: &mut OpenMates,
    cancel: CancellationToken,
) -> Result<CliOutput, CliError> {
    let (_, project) = selectors(i, &cancel)?;
    let (projects, workflows) = filters(i, input::text(i, "team")?.map(str::to_owned));
    client.set_operation_cancel(cancel.clone());
    let project = client
        .projects()
        .with_filters(projects)
        .show(project)
        .await?;
    remove(
        i,
        client.workflows().with_filters(workflows),
        project,
        &cancel,
    )
    .await
}
async fn remove(
    i: &Invocation,
    mut service: Workflows<'_>,
    project: Value,
    cancel: &CancellationToken,
) -> Result<CliOutput, CliError> {
    let (workflow, _) = selectors(i, cancel)?;
    let project_id = project["project_id"].as_str().ok_or(Error::Protocol)?;
    let workflow = service.get(workflow).await?;
    let workflow_id = workflow["id"].as_str().ok_or(Error::Protocol)?;
    if cancel.is_cancelled() {
        return Err(Error::Cancelled.into());
    }
    let removed = service.remove_from_project(workflow_id, project_id).await?;
    render(i, workflow_id, project_id, removed)
}
fn render(
    i: &Invocation,
    workflow_id: &str,
    project_id: &str,
    ack: Value,
) -> Result<CliOutput, CliError> {
    let deleted = ack["deleted"].as_bool().ok_or(Error::Protocol)?;
    let count = ack["deleted_count"].as_u64().ok_or(Error::Protocol)?;
    if deleted != (count > 0) {
        return Err(Error::Protocol.into());
    }
    output(
        i,
        json!({"objectType":"workflow","objectId":workflow_id,"projectId":project_id,
        "deleted":deleted,"deletedCount":count}),
        if deleted {
            format!("workflow removed from Project: {project_id}")
        } else {
            format!("workflow was not linked to Project: {project_id}")
        },
    )
}

#[cfg(test)]
mod tests;
