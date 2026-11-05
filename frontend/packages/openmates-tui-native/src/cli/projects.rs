//! Project CLI authoring through the locally encrypted, typed SDK namespace.
mod ask;
mod command_settings;
mod files;
mod focus;
mod items;
mod sources;
use super::{CliError, CliOutput, Invocation, task_input as input};
use crate::{client::Client, error::Error, runtime_store::RuntimeStore};
use openmates_sdk::{
    OpenMates,
    work::{
        ProjectCreate, ProjectFilters, ProjectFocusActivationPolicy, ProjectPatch,
        ProjectSettingsPatch, ProjectWriteMode, Projects, RestoreState,
    },
};
use serde_json::{Value, json};
use tokio_util::sync::CancellationToken;
const GLOBALS: &[&str] = &[
    "json",
    "profile",
    "api-url",
    "api-key",
    "state-dir",
    "encrypted-vault",
    "demo",
    "personal",
    "team",
];
const FIELDS: &[&str] = &[
    "name",
    "description",
    "icon",
    "color",
    "slug",
    "pin",
    "unpin",
];
pub(super) fn supported(i: &Invocation) -> bool {
    matches!(
        i.command_path().as_str(),
        "projects list"
            | "projects ask"
            | "projects show"
            | "projects open"
            | "projects create"
            | "projects update"
            | "projects archive"
            | "projects unarchive"
            | "projects delete"
            | "projects history"
            | "projects restore"
            | "projects tasks"
            | "projects plans"
            | "projects settings"
            | "projects items list"
            | "projects items remove"
            | "projects sources list"
            | "projects sources remove"
            | "projects files list"
            | "projects files search"
            | "projects files read"
            | "projects settings focus activate"
            | "projects settings focus deactivate"
            | "projects settings command stop"
            | "projects settings command-presets list"
            | "projects settings command-presets disable"
            | "projects settings command-resources list"
            | "projects settings command-resources enable writable"
            | "projects settings command-resources enable network"
            | "projects settings command-resources enable credential"
            | "projects settings command-resources disable writable"
            | "projects settings command-resources disable network"
            | "projects settings command-resources disable credential"
    )
}
fn check(i: &Invocation, allowed: &[&str]) -> Result<(), CliError> {
    for (key, value) in &i.flags {
        if !GLOBALS.contains(&key.as_str()) && !allowed.contains(&key.as_str()) {
            return Err(CliError::Unsupported {
                command: i.command_path(),
                reason: format!("Option --{key} is not ported for this native Project operation."),
            });
        }
        if value.is_array() {
            return Err(CliError::Invalid(format!(
                "Option --{key} must be supplied once."
            )));
        }
    }
    Ok(())
}
fn create(i: &Invocation) -> Result<ProjectCreate, CliError> {
    check(
        i,
        &[
            "name",
            "description",
            "icon",
            "color",
            "slug",
            "pinned",
            "write-policy",
        ],
    )?;
    if i.positionals.len() > 1 {
        return Err(CliError::Invalid("Supply one quoted Project name.".into()));
    }
    let name = i
        .positionals
        .first()
        .map(String::as_str)
        .or(input::text(i, "name")?)
        .filter(|name| !name.trim().is_empty())
        .ok_or_else(|| CliError::Invalid("Provide a Project name.".into()))?;
    let write_mode = match input::text(i, "write-policy")?.ok_or_else(|| CliError::Contract {
        code: "write_policy_required",
        message: "Project creation requires --write-policy apply_and_show|always_ask.".into(),
    })? {
        "apply_and_show" => ProjectWriteMode::ApplyAndShow,
        "always_ask" => ProjectWriteMode::AlwaysAsk,
        _ => {
            return Err(CliError::Contract {
                code: "invalid_write_policy",
                message: "--write-policy must be apply_and_show or always_ask.".into(),
            });
        }
    };
    Ok(ProjectCreate {
        name: name.into(),
        description: input::text(i, "description")?.unwrap_or("").into(),
        icon: input::text(i, "icon")?.map(str::to_owned),
        color: input::text(i, "color")?.map(str::to_owned),
        slug: input::text(i, "slug")?.map(str::to_owned),
        pinned: i.boolean("pinned"),
        write_mode: Some(write_mode),
        ..Default::default()
    })
}
fn patch(i: &Invocation) -> Result<ProjectPatch, CliError> {
    check(i, FIELDS)?;
    if !FIELDS.iter().any(|flag| i.has(flag)) {
        return Err(CliError::Invalid(
            "Provide at least one Project field to update.".into(),
        ));
    }
    if i.boolean("pin") && i.boolean("unpin") {
        return Err(CliError::Invalid("Choose --pin or --unpin.".into()));
    }
    Ok(ProjectPatch {
        name: input::text(i, "name")?.map(str::to_owned),
        description: input::text(i, "description")?.map(str::to_owned),
        icon: input::text(i, "icon")?.map(str::to_owned),
        color: input::text(i, "color")?.map(str::to_owned),
        slug: input::text(i, "slug")?.map(str::to_owned),
        pinned: if i.boolean("pin") {
            Some(true)
        } else if i.boolean("unpin") {
            Some(false)
        } else {
            None
        },
        ..Default::default()
    })
}
fn settings_patch(i: &Invocation) -> Result<Option<ProjectSettingsPatch>, CliError> {
    check(i, &["write-policy", "auto-selection", "focus-activation"])?;
    let write_mode = input::text(i, "write-policy")?
        .map(|value| match value {
            "apply_and_show" => Ok(ProjectWriteMode::ApplyAndShow),
            "always_ask" => Ok(ProjectWriteMode::AlwaysAsk),
            _ => Err(CliError::Invalid(
                "--write-policy must be apply_and_show or always_ask.".into(),
            )),
        })
        .transpose()?;
    let auto_selection = input::text(i, "auto-selection")?
        .map(|value| match value {
            "on" => Ok(true),
            "off" => Ok(false),
            _ => Err(CliError::Invalid(
                "--auto-selection must be on or off.".into(),
            )),
        })
        .transpose()?;
    let focus_activation_policy = input::text(i, "focus-activation")?
        .map(|value| match value {
            "delayed" => Ok(ProjectFocusActivationPolicy::Delayed),
            "immediate" => Ok(ProjectFocusActivationPolicy::Immediate),
            "approval" => Ok(ProjectFocusActivationPolicy::Approval),
            _ => Err(CliError::Invalid(
                "--focus-activation must be delayed, immediate, or approval.".into(),
            )),
        })
        .transpose()?;
    if write_mode.is_none() && auto_selection.is_none() && focus_activation_policy.is_none() {
        Ok(None)
    } else {
        Ok(Some(ProjectSettingsPatch {
            write_mode,
            auto_selection,
            focus_activation_policy,
            ..Default::default()
        }))
    }
}
fn filters(i: &Invocation, team: Option<String>) -> ProjectFilters {
    ProjectFilters {
        personal: i.boolean("personal"),
        team_id: team,
        include_archived: i
            .has("include-archived")
            .then(|| i.boolean("include-archived")),
    }
}
fn project_json(project: &Value) -> Value {
    let mut value = json!({});
    for field in [
        "project_id",
        "name",
        "description",
        "icon",
        "color",
        "pinned",
        "archived",
        "version",
        "mutation_permissions",
    ] {
        value[field] = project[field].clone();
    }
    value["short_id"] = json!(
        project["project_id"]
            .as_str()
            .unwrap_or("")
            .chars()
            .take(8)
            .collect::<String>()
    );
    value["slug"] = project["slug"]
        .as_str()
        .filter(|slug| !slug.is_empty())
        .map(|slug| json!(slug))
        .unwrap_or(Value::Null);
    value
}
fn render(project: &Value) -> String {
    let mut text = format!(
        "{}\nProject: {}",
        project["name"].as_str().unwrap_or("Project"),
        project["project_id"].as_str().unwrap_or("")
    );
    for (field, label) in [
        ("description", "Description"),
        ("write_mode", "Write policy"),
        ("slug", "Slug"),
    ] {
        if let Some(value) = project[field].as_str().filter(|value| !value.is_empty()) {
            text.push_str(&format!("\n{label}: {value}"));
        }
    }
    if project["archived"] == true {
        text.push_str("\nArchived")
    }
    text
}
fn output(i: &Invocation, value: Value, text: String) -> Result<CliOutput, CliError> {
    super::handlers::output(i, value, text)
}
fn delegated(i: &Invocation, project: &Value) -> Result<Invocation, CliError> {
    let id = project["project_id"]
        .as_str()
        .ok_or(CliError::Client(Error::Protocol))?;
    let mut flags = i.flags.clone();
    flags.insert("project".into(), json!(id));
    Ok(Invocation {
        path: vec![i.path[1].clone(), "list".into()],
        positionals: vec![],
        flags,
    })
}
fn with_project(mut output: CliOutput, id: &str, json: bool) -> Result<CliOutput, CliError> {
    if json {
        let mut value: Value =
            serde_json::from_str(&output.stdout).map_err(|_| CliError::Client(Error::Protocol))?;
        value["project_id"] = json!(id);
        output = CliOutput::json(&value)?;
    }
    Ok(output)
}
pub(super) async fn execute(
    i: &Invocation,
    client: &mut Client,
    cancel: CancellationToken,
    store: Option<&RuntimeStore>,
) -> Result<CliOutput, CliError> {
    let team = client.session().and_then(|s| s.active_team_id.clone());
    if i.command_path() == "projects ask" {
        let (instruction, value) =
            ask::run(i, &mut client.projects().with_filters(filters(i, team))).await?;
        return super::tasks::workspace_ask_output(
            i,
            client,
            cancel,
            instruction,
            value,
            "project",
        )
        .await;
    }
    if ["projects tasks", "projects plans"].contains(&i.command_path().as_str()) {
        check(i, &[])?;
        let project = client
            .projects()
            .with_filters(filters(i, team))
            .show(input::positional(i, 0, "Project ID")?)
            .await?;
        let command = delegated(i, &project)?;
        let result = if i.path[1] == "tasks" {
            super::tasks::execute(&command, client, cancel, store).await?
        } else {
            super::plans::execute(&command, client, cancel, store).await?
        };
        return with_project(
            result,
            project["project_id"]
                .as_str()
                .ok_or(CliError::Client(Error::Protocol))?,
            i.boolean("json"),
        );
    }
    execute_service(i, client.projects().with_filters(filters(i, team)), cancel).await
}
pub async fn execute_sdk_projects_with_delivery(
    i: &Invocation,
    client: &mut OpenMates,
    cancel: CancellationToken,
    store: &RuntimeStore,
    api_url: &str,
) -> Result<CliOutput, CliError> {
    if i.boolean("personal") && i.has("team") {
        return Err(CliError::Invalid(
            "Choose --personal or --team, not both.".into(),
        ));
    }
    client.set_operation_cancel(cancel.clone());
    let team = input::text(i, "team")?.map(str::to_owned);
    if ["projects tasks", "projects plans"].contains(&i.command_path().as_str()) {
        check(i, &[])?;
        let project = client
            .projects()
            .with_filters(filters(i, team))
            .show(input::positional(i, 0, "Project ID")?)
            .await?;
        let command = delegated(i, &project)?;
        let result = if i.path[1] == "tasks" {
            super::tasks::execute_sdk_tasks_with_delivery(&command, client, cancel, store, api_url)
                .await?
        } else {
            super::plans::execute_sdk_plans_with_delivery(&command, client, cancel, store, api_url)
                .await?
        };
        return with_project(
            result,
            project["project_id"]
                .as_str()
                .ok_or(CliError::Client(Error::Protocol))?,
            i.boolean("json"),
        );
    }
    execute_service(i, client.projects().with_filters(filters(i, team)), cancel).await
}
async fn execute_service(
    i: &Invocation,
    mut service: Projects<'_>,
    cancel: CancellationToken,
) -> Result<CliOutput, CliError> {
    if cancel.is_cancelled() {
        return Err(Error::Cancelled.into());
    }
    if i.path.get(1).map(String::as_str) == Some("items") {
        return items::execute(i, &mut service).await;
    }
    if i.command_path() == "projects sources list" {
        return sources::execute(i, &mut service, &cancel).await;
    }
    if i.command_path().starts_with("projects files ") {
        return files::execute(i, &mut service).await;
    }
    if i.command_path().starts_with("projects settings command") {
        return command_settings::execute(i, &mut service).await;
    }
    if i.command_path().starts_with("projects settings focus ") {
        return focus::execute(i, &mut service).await;
    }
    if i.command_path() == "projects sources remove" {
        return sources::remove(i, &mut service, &cancel).await;
    }
    if i.command_path() == "projects ask" {
        let (_, value) = ask::run(i, &mut service).await?;
        if value["fallback_to_chat"] == true || value["outcome"] == "fallback_to_chat" {
            return Err(Error::Unavailable {
                code: "workspace_ask_chat_fallback_unavailable",
                reason: "API_KEY_CHAT_CONTINUATION_NOT_PORTED",
            }
            .into());
        }
        let text = super::tasks::ask_text(&value, "project");
        return output(i, value, text);
    }
    let id = || input::positional(i, 0, "Project ID");
    let project = match i.command_path().as_str() {
        "projects list" => {
            check(i, &["include-archived"])?;
            let projects = service.list().await?;
            let text = if projects.is_empty() {
                "No Projects found.".into()
            } else {
                projects
                    .iter()
                    .map(|project| {
                        format!(
                            "{}  {}{}",
                            project["project_id"].as_str().unwrap_or(""),
                            project["name"].as_str().unwrap_or(""),
                            if project["archived"] == true {
                                "  [archived]"
                            } else {
                                ""
                            }
                        )
                    })
                    .collect::<Vec<_>>()
                    .join("\n")
            };
            return output(
                i,
                json!({"projects":projects.iter().map(project_json).collect::<Vec<_>>()}),
                text,
            );
        }
        "projects show" => {
            check(i, &[])?;
            service.show(id()?).await?
        }
        "projects open" => {
            check(i, &[])?;
            service.open(id()?).await?
        }
        "projects create" => service.create(create(i)?).await?,
        "projects settings" => {
            let patch = settings_patch(i)?;
            let project = service.show(id()?).await?;
            let canonical = project["project_id"]
                .as_str()
                .ok_or(CliError::Client(Error::Protocol))?;
            let settings = if let Some(patch) = patch {
                service.update_settings(canonical, patch).await?
            } else {
                service.settings(canonical).await?
            };
            let text = format!(
                "Write policy: {}\nAutomatic focus selection: {}\nFocus activation: {}",
                settings["write_mode"]
                    .as_str()
                    .unwrap_or("selection required"),
                if settings["auto_selection"] == false {
                    "off"
                } else {
                    "on"
                },
                settings["focus_activation_policy"]
                    .as_str()
                    .unwrap_or("delayed")
            );
            return output(i, json!({"project_id":canonical,"settings":settings}), text);
        }
        "projects update" => service.update(id()?, patch(i)?).await?,
        "projects archive" | "projects unarchive" => {
            check(i, &[])?;
            if i.path[1] == "archive" {
                service.archive(id()?).await?
            } else {
                service.unarchive(id()?).await?
            }
        }
        "projects delete" => {
            check(i, &["confirm"])?;
            let project = service.show(id()?).await?;
            let canonical = project["project_id"]
                .as_str()
                .ok_or(CliError::Client(Error::Protocol))?;
            if input::text(i, "confirm")? != Some(canonical) {
                return Err(CliError::Contract {
                    code: "confirmation_required",
                    message: "Project deletion requires --confirm <exact-project-id>.".into(),
                });
            }
            service.delete(canonical, true).await?;
            return output(
                i,
                json!({"deleted":true,"project_id":canonical}),
                "Project deleted.".into(),
            );
        }
        "projects history" => {
            check(i, &["limit"])?;
            let limit = input::text(i, "limit")?
                .map(|value| {
                    value
                        .parse::<u16>()
                        .ok()
                        .filter(|v| *v > 0 && *v <= 500)
                        .ok_or_else(|| CliError::Invalid("--limit must be from 1 to 500.".into()))
                })
                .transpose()?;
            let entries = service.history(id()?, limit).await?;
            return super::history::output(i, entries);
        }
        "projects restore" => {
            check(i, &["entry", "entry-id", "state"])?;
            let entry = super::history::entry(i)?;
            let state = match input::text(i, "state")?.unwrap_or("before") {
                "before" => RestoreState::Before,
                "after" => RestoreState::After,
                _ => return Err(CliError::Invalid("--state must be before or after.".into())),
            };
            let value = service.restore(id()?, entry, state).await?;
            return output(i, value, "Project restored.".into());
        }
        _ => {
            return Err(CliError::Unsupported {
                command: i.command_path(),
                reason: "This Project operation is not ported to the native CLI.".into(),
            });
        }
    };
    let text = render(&project);
    output(i, json!({"project":project_json(&project)}), text)
}
#[cfg(test)]
mod tests {
    use super::*;
    fn i(flags: &[(&str, Value)]) -> Invocation {
        Invocation {
            path: vec!["projects".into(), "create".into()],
            positionals: vec!["Engineering".into()],
            flags: flags
                .iter()
                .map(|(k, v)| (k.to_string(), v.clone()))
                .collect(),
        }
    }
    #[test]
    fn project_json_keeps_legacy_short_id_and_permissions_without_unrequested_metadata() {
        let value = project_json(
            &json!({"project_id":"12345678-1234-4234-8234-123456789abc","slug":"","name":"Engineering","version":7,"mutation_permissions":{"can_edit":true},"created_at":123,"history":{"private_extra":"metadata"}}),
        );
        assert_eq!(value["short_id"], "12345678");
        assert!(value["slug"].is_null());
        assert_eq!(value["mutation_permissions"]["can_edit"], true);
        assert!(value.get("created_at").is_none());
        assert!(value.get("history").is_none());
    }
    #[test]
    fn parser_keeps_name_alternative_settings_and_legacy_restore_entry() {
        let parsed = super::super::parse_from([
            "openmates",
            "projects",
            "create",
            "--name",
            "Engineering",
            "--write-policy",
            "always_ask",
            "--pinned",
        ])
        .ok()
        .unwrap();
        let command = parsed.invocation.as_ref().unwrap();
        assert_eq!(create(command).ok().unwrap().name, "Engineering");
        let parsed = super::super::parse_from([
            "openmates",
            "projects",
            "settings",
            "engineering",
            "--auto-selection",
            "off",
            "--focus-activation",
            "approval",
        ])
        .ok()
        .unwrap();
        let patch = settings_patch(parsed.invocation.as_ref().unwrap())
            .ok()
            .unwrap()
            .unwrap();
        assert_eq!(patch.auto_selection, Some(false));
        assert_eq!(
            serde_json::to_value(patch.focus_activation_policy).unwrap(),
            "approval"
        );
        let parsed = super::super::parse_from([
            "openmates",
            "projects",
            "restore",
            "engineering",
            "history-entry",
            "--state",
            "after",
        ])
        .ok()
        .unwrap();
        assert_eq!(
            parsed.invocation.as_ref().unwrap().positionals,
            ["engineering", "history-entry"]
        );
    }
    #[test]
    fn creation_requires_explicit_write_policy_and_keeps_private_fields() {
        let missing = create(&i(&[])).err().unwrap();
        assert_eq!(missing.code(), "write_policy_required");
        assert_eq!(missing.exit_code(), 1);
        let value = create(&i(&[
            ("write-policy", json!("always_ask")),
            ("description", json!("Private instructions")),
            ("pinned", json!(true)),
        ]))
        .ok()
        .unwrap();
        assert_eq!(value.name, "Engineering");
        assert_eq!(value.description, "Private instructions");
        assert!(value.pinned);
        assert!(create(&i(&[("write-policy", json!("unknown"))])).is_err());
    }
    #[test]
    fn update_preserves_empty_description_and_does_not_accept_silent_fields() {
        let value = patch(&i(&[("description", json!("")), ("unpin", json!(true))]))
            .ok()
            .unwrap();
        assert_eq!(value.description.as_deref(), Some(""));
        assert_eq!(value.pinned, Some(false));
        assert!(value.name.is_none());
        assert!(patch(&i(&[("title", json!("Wrong API field"))])).is_err());
    }
    #[test]
    fn views_preserve_selected_scope_and_project_identity() {
        let mut command = i(&[("personal", json!(true)), ("json", json!(true))]);
        command.path = vec!["projects".into(), "tasks".into()];
        let delegated = delegated(&command, &json!({"project_id":"canonical"}))
            .ok()
            .unwrap();
        assert_eq!(delegated.path, ["tasks", "list"]);
        assert!(delegated.boolean("personal"));
        assert_eq!(delegated.text("project"), Some("canonical"));
        let output = with_project(
            CliOutput::json(&json!({"tasks":[]})).ok().unwrap(),
            "canonical",
            true,
        )
        .ok()
        .unwrap();
        assert_eq!(
            serde_json::from_str::<Value>(&output.stdout).unwrap()["project_id"],
            "canonical"
        );
    }
}
