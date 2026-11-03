//! `workflows <workflow-id> add-to-project <project-id>`: flag policy and
//! terminal output only; the encrypted link and bound YAML save are SDK-owned.
use super::*;
use openmates_sdk::work::{
    ProjectFilters, WorkflowAttachOptions, WorkflowAttachResult, WorkflowStorageMode,
};

const FLAGS: &[&str] = &[
    "folder",
    "source",
    "remote-folder",
    "source-chat",
    "yes",
    "openmates-only",
    "repo-copy",
    "remote-cache-copy",
    "remote-copy",
];

fn failed(message: &str) -> CliError {
    CliError::Contract {
        code: "command_failed",
        message: message.into(),
    }
}

/// Legacy `resolveAddToProjectStorageChoice` flag rules (Workflow variant).
fn storage(i: &Invocation) -> Result<WorkflowStorageMode, CliError> {
    let (repo, cache, remote) = (
        i.boolean("repo-copy"),
        i.boolean("remote-cache-copy"),
        i.boolean("remote-copy"),
    );
    if i.boolean("openmates-only") && (remote || repo || cache) {
        return Err(failed(
            "Choose either --openmates-only or a remote-copy mode, not both.",
        ));
    }
    if repo && cache {
        return Err(failed(
            "Choose only one remote-copy mode: --repo-copy or --remote-cache-copy.",
        ));
    }
    Ok(if repo || remote {
        WorkflowStorageMode::RemoteRepoCopy
    } else if cache {
        WorkflowStorageMode::RemoteCacheCopy
    } else {
        WorkflowStorageMode::SaveOnlyInOpenMates
    })
}

/// Legacy string flags: a bare boolean flag is treated as absent.
fn string_flag(i: &Invocation, key: &str) -> Option<String> {
    i.flags.get(key).and_then(Value::as_str).map(str::to_owned)
}

pub(super) async fn execute_cookie(
    i: &Invocation,
    client: &mut Client,
    cancel: CancellationToken,
) -> Result<CliOutput, CliError> {
    check(i, FLAGS)?;
    if i.boolean("personal") && i.has("team") {
        return Err(CliError::Invalid(
            "Choose --personal or --team, not both.".into(),
        ));
    }
    let selector = input::positional(i, 0, "Workflow ID")?;
    let project = i
        .positionals
        .get(1)
        .map(|value| value.trim())
        .filter(|value| !value.is_empty())
        .ok_or_else(|| failed("Missing <project-id>."))?
        .to_owned();
    let storage = storage(i)?;
    let personal = i.boolean("personal");
    let team = if personal {
        None
    } else {
        input::text(i, "team")?.map(str::to_owned).or_else(|| {
            client
                .session()
                .and_then(|session| session.active_team_id.clone())
        })
    };
    client.set_operation_cancel(cancel.clone());
    let workflow_id = if uuid::Uuid::parse_str(selector).is_ok() {
        selector.to_owned()
    } else {
        let workflow = client
            .workflows()
            .with_filters(WorkflowFilters {
                personal,
                team_id: team.clone(),
                ..Default::default()
            })
            .get(selector)
            .await?;
        workflow["id"].as_str().ok_or(Error::Protocol)?.to_owned()
    };
    if cancel.is_cancelled() {
        return Err(Error::Cancelled.into());
    }
    let options = WorkflowAttachOptions {
        storage,
        openmates_only: i.boolean("openmates-only"),
        folder_id: string_flag(i, "folder"),
        source_id: string_flag(i, "source"),
        remote_folder: string_flag(i, "remote-folder"),
        source_chat: string_flag(i, "source-chat"),
    };
    let result = client
        .projects()
        .with_filters(ProjectFilters {
            personal,
            team_id: team,
            ..Default::default()
        })
        .attach_workflow(
            &workflow_id,
            &project,
            options,
            openmates_sdk::work::serialize_workflow_file,
            |path| update::approve(i, path, cancel.clone()),
        )
        .await
        .map_err(|error| match error {
            Error::Invalid(message) => failed(message),
            other => other.into(),
        })?;
    render(i, result)
}

fn render(i: &Invocation, result: WorkflowAttachResult) -> Result<CliOutput, CliError> {
    let line = match &result.remote_file {
        Some(file) if file.status == "saved" => format!(
            "Remote YAML saved: {}",
            file.path.as_deref().unwrap_or("undefined")
        ),
        Some(file) => format!(
            "Remote YAML {}: {}",
            file.status,
            file.error.unwrap_or("Retry the file save.")
        ),
        None => "Storage: encrypted OpenMates Project link only".into(),
    };
    let text = format!("Workflow linked to Project: {}\n{line}", result.project_id);
    output(
        i,
        json!({
            "objectType": "workflow",
            "objectId": result.workflow_id,
            "projectId": result.project_id,
            "item": result.item,
            "remote_file": result.remote_file,
        }),
        text,
    )
}

#[cfg(test)]
mod tests {
    use super::*;
    use openmates_sdk::work::WorkflowRemoteFileResult;

    fn invocation(flags: &[(&str, Value)]) -> Invocation {
        Invocation {
            path: vec!["workflows".into(), "add-to-project".into()],
            positionals: vec!["wf".into(), "project".into()],
            flags: flags
                .iter()
                .map(|(key, value)| ((*key).to_owned(), value.clone()))
                .collect(),
        }
    }

    // contract-test: supporting surface=cli assertions=cli.runtime.native-rust
    #[test]
    fn storage_flags_follow_the_legacy_rules() {
        let mode = |flags: &[(&str, Value)]| storage(&invocation(flags));
        assert_eq!(
            mode(&[]).ok().unwrap(),
            WorkflowStorageMode::SaveOnlyInOpenMates
        );
        assert_eq!(
            mode(&[("remote-copy", json!(true))]).ok().unwrap(),
            WorkflowStorageMode::RemoteRepoCopy
        );
        assert_eq!(
            mode(&[("remote-cache-copy", json!(true))]).ok().unwrap(),
            WorkflowStorageMode::RemoteCacheCopy
        );
        let message = |error: CliError| match error {
            CliError::Contract { code, message } => (code, message),
            _ => panic!("unexpected error kind"),
        };
        assert_eq!(
            message(
                mode(&[("openmates-only", json!(true)), ("repo-copy", json!(true))])
                    .err()
                    .unwrap()
            ),
            (
                "command_failed",
                "Choose either --openmates-only or a remote-copy mode, not both.".into()
            )
        );
        assert_eq!(
            message(
                mode(&[
                    ("repo-copy", json!(true)),
                    ("remote-cache-copy", json!(true))
                ])
                .err()
                .unwrap()
            )
            .1,
            "Choose only one remote-copy mode: --repo-copy or --remote-cache-copy."
        );
    }

    // contract-test: supporting surface=cli assertions=cli.runtime.native-rust
    #[test]
    fn output_matches_the_legacy_text_and_json() {
        let result = |remote_file| WorkflowAttachResult {
            project_id: "project".into(),
            workflow_id: "wf".into(),
            item: json!({"project_item_id":"item"}),
            remote_file,
        };
        let text = |remote_file| {
            render(&invocation(&[]), result(remote_file))
                .ok()
                .unwrap()
                .stdout
        };
        assert_eq!(
            text(None),
            "Workflow linked to Project: project\nStorage: encrypted OpenMates Project link only\n"
        );
        assert_eq!(
            text(Some(WorkflowRemoteFileResult {
                status: "saved",
                path: Some("flows/a.workflow.yml".into()),
                error: None
            })),
            "Workflow linked to Project: project\nRemote YAML saved: flows/a.workflow.yml\n"
        );
        assert_eq!(
            text(Some(WorkflowRemoteFileResult {
                status: "pending",
                path: None,
                error: Some("project_focus_required")
            })),
            "Workflow linked to Project: project\nRemote YAML pending: project_focus_required\n"
        );
        let json = render(&invocation(&[("json", json!(true))]), result(None))
            .ok()
            .unwrap();
        let value: Value = serde_json::from_str(&json.stdout).ok().unwrap();
        assert_eq!(
            value,
            json!({"objectType":"workflow","objectId":"wf","projectId":"project",
                "item":{"project_item_id":"item"},"remote_file":null})
        );
    }
}
