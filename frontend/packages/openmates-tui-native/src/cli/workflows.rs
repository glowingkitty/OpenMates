//! Workflows use typed native SDK methods; files and terminal output remain app-owned.
mod add_to_project;
mod ask;
mod files;
mod project_links;
mod update;
mod yaml;
use super::{CliError, CliOutput, Invocation, task_input as input};
use crate::{client::Client, error::Error};
use openmates_sdk::{
    OpenMates,
    work::{
        RestoreState, WorkflowCreate, WorkflowFilters, WorkflowGraph, WorkflowInputOptions,
        WorkflowRetention, WorkflowRunMode, WorkflowRunOptions, WorkflowStepOptions,
        WorkflowWaitOptions, Workflows,
    },
};
use serde::de::DeserializeOwned;
use serde_json::{Value, json};
use std::collections::BTreeMap;
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
pub(super) fn supported(i: &Invocation) -> bool {
    matches!(
        i.command_path().as_str(),
        "workflows ask"
            | "workflows list"
            | "workflows capabilities"
            | "workflows help-app"
            | "workflows show"
            | "workflows create"
            | "workflows validate"
            | "workflows update"
            | "workflows history"
            | "workflows restore"
            | "workflows enable"
            | "workflows disable"
            | "workflows delete"
            | "workflows runs"
            | "workflows run"
            | "workflows run-once"
            | "workflows run-show"
            | "workflows run-delete"
            | "workflows run-cancel"
            | "workflows save-as-reusable"
            | "workflows step-preview"
            | "workflows step-test"
            | "workflows respond"
            | "workflows input"
            | "workflows input-show"
            | "workflows input-events"
            | "workflows input-follow-up"
            | "workflows input-stop"
            | "workflows input-undo"
            | "workflows export"
            | "workflows import"
            | "workflows remove-from-project"
            | "workflows add-to-project"
    )
}
fn check(i: &Invocation, allowed: &[&str]) -> Result<(), CliError> {
    for (key, value) in &i.flags {
        if !GLOBALS.contains(&key.as_str()) && !allowed.contains(&key.as_str()) {
            return Err(CliError::Unsupported {
                command: i.command_path(),
                reason: format!("Option --{key} is not ported for this native Workflow operation."),
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
fn json_input<T: DeserializeOwned>(i: &Invocation, name: &str) -> Result<Option<T>, CliError> {
    input::text(i, name)?
        .map(|text| {
            serde_json::from_str(text)
                .map_err(|_| CliError::Invalid(format!("--{name} requires valid typed JSON.")))
        })
        .transpose()
}
fn retention(i: &Invocation) -> Result<WorkflowRetention, CliError> {
    match input::text(i, "run-content-retention")?.unwrap_or("last_5") {
        "last_5" => Ok(WorkflowRetention::Last5),
        "none" => Ok(WorkflowRetention::None),
        _ => Err(CliError::Invalid(
            "--run-content-retention must be last_5 or none.".into(),
        )),
    }
}
fn create(i: &Invocation) -> Result<WorkflowCreate, CliError> {
    check(
        i,
        &["title", "graph", "slug", "enabled", "run-content-retention"],
    )?;
    Ok(WorkflowCreate {
        title: input::required(i, "title")?.trim().into(),
        graph: json_input(i, "graph")?.ok_or_else(|| {
            CliError::Invalid("Creating a Workflow requires --graph JSON or --file.".into())
        })?,
        slug: input::text(i, "slug")?.map(str::to_owned),
        enabled: i.boolean("enabled"),
        run_content_retention: retention(i)?,
        ..Default::default()
    })
}
fn run_options(i: &Invocation) -> Result<WorkflowRunOptions, CliError> {
    let mode = match input::text(i, "mode")?.unwrap_or("manual") {
        "manual" => WorkflowRunMode::Manual,
        "test" => WorkflowRunMode::Test,
        _ => return Err(CliError::Invalid("--mode must be manual or test.".into())),
    };
    Ok(WorkflowRunOptions {
        idempotency_key: input::required(i, "idempotency-key")?.into(),
        mode,
        input: json_input(i, "input")?.unwrap_or_default(),
        source_chat_id: input::text(i, "source-chat")?.map(str::to_owned),
        message_destination_overrides: json_input(i, "message-destination-overrides")?
            .unwrap_or_default(),
        return_outputs: json_input(i, "return-outputs")?.unwrap_or_default(),
    })
}
fn step_options(i: &Invocation) -> Result<WorkflowStepOptions, CliError> {
    Ok(WorkflowStepOptions {
        input: json_input(i, "input")?.unwrap_or_default(),
        node: json_input(i, "node")?,
        upstream_outputs: json_input(i, "upstream")?.unwrap_or_default(),
        confirmed: i.boolean("yes"),
    })
}
fn timezone(i: &Invocation) -> Result<String, CliError> {
    if let Some(zone) = input::text(i, "timezone")?.filter(|zone| !zone.is_empty()) {
        return Ok(zone.into());
    }
    if let Ok(zone) = std::env::var("TZ") {
        let zone = zone.trim();
        if zone == "UTC"
            || zone == "GMT"
            || zone.contains('/') && !zone.starts_with('/') && !zone.contains("..")
        {
            return Ok(zone.into());
        }
    }
    if let Ok(zone) = std::fs::read_to_string("/etc/timezone") {
        let zone = zone.trim();
        if !zone.is_empty() && zone.len() < 256 && !zone.chars().any(char::is_control) {
            return Ok(zone.into());
        }
    }
    if let Ok(zone) = std::fs::read_link("/etc/localtime")
        && let Some(zone) = zone
            .to_str()
            .and_then(|path| path.split_once("zoneinfo/").map(|(_, zone)| zone))
    {
        return Ok(zone.into());
    }
    Err(Error::Unavailable {
        code: "local_timezone_unavailable",
        reason: "PASS_EXPLICIT_TIMEZONE",
    }
    .into())
}
fn input_options(i: &Invocation) -> Result<WorkflowInputOptions, CliError> {
    check(
        i,
        &[
            "text",
            "workflow-id",
            "project-id",
            "timezone",
            "optimistic",
            "idempotency-key",
        ],
    )?;
    let positional = i.positionals.join(" ");
    let text = input::text(i, "text")?.unwrap_or(&positional).trim();
    if text.is_empty() {
        return Err(CliError::Invalid("Provide Workflow input text.".into()));
    }
    Ok(WorkflowInputOptions {
        text: Some(text.into()),
        selected_workflow_id: input::text(i, "workflow-id")?.map(str::to_owned),
        selected_project_id: input::text(i, "project-id")?.map(str::to_owned),
        timezone: Some(timezone(i)?),
        optimistic_save: i.boolean("optimistic"),
        idempotency_key: input::text(i, "idempotency-key")?.map(str::to_owned),
        ..Default::default()
    })
}
fn workflow_text(workflow: &Value) -> String {
    let mut text = format!(
        "{}\nID: {}\nStatus: {}\nEnabled: {}\nRun content: {}",
        workflow["title"].as_str().unwrap_or("Workflow"),
        workflow["id"].as_str().unwrap_or(""),
        workflow["status"].as_str().unwrap_or(""),
        workflow["enabled"].as_bool().unwrap_or(false),
        workflow["run_content_retention"]
            .as_str()
            .unwrap_or("last_5")
    );
    for (field, label) in [
        ("slug", "Slug"),
        ("category", "Category"),
        ("icon", "Icon"),
        ("trigger_summary", "Trigger"),
    ] {
        if let Some(value) = workflow[field].as_str().filter(|value| !value.is_empty()) {
            text.push_str(&format!("\n{label}: {value}"));
        }
    }
    if let Some(nodes) = workflow.pointer("/graph/nodes").and_then(Value::as_array) {
        text.push_str(&format!("\nNodes: {}", nodes.len()));
    }
    for warning in workflow["authoring_warnings"]
        .as_array()
        .into_iter()
        .flatten()
    {
        if let Some(message) = warning["message"].as_str() {
            text.push_str(&format!("\nWarning: {message}"));
        }
    }
    text
}
fn run_text(run: &Value) -> String {
    let mut text = format!(
        "Workflow Run {}\nStatus: {}\nTrigger: {}\nNodes: {}",
        run["id"].as_str().unwrap_or(""),
        run["status"].as_str().unwrap_or(""),
        run["trigger_type"].as_str().unwrap_or(""),
        run["node_runs"].as_array().map(Vec::len).unwrap_or(0)
    );
    if let Some(error) = run["error_summary"].as_str() {
        text.push_str(&format!("\nError: {error}"));
    }
    text
}
fn session_text(session: &Value) -> String {
    let mut text = format!(
        "Workflow Input {}\nStatus: {}\nEvents: {}\nUndo: {}",
        session["session_id"].as_str().unwrap_or(""),
        session["status"].as_str().unwrap_or(""),
        session["event_cursor"],
        if session["undo_available"] == true {
            "available"
        } else {
            "unavailable"
        }
    );
    for field in ["message", "error"] {
        if let Some(value) = session[field].as_str() {
            text.push_str(&format!("\n{field}: {value}"));
        }
    }
    for field in ["workflow", "preview_workflow"] {
        if let Some(title) = session[field]["title"].as_str() {
            text.push_str(&format!("\n{field}: {title}"));
        }
    }
    text
}
fn validation_text(value: &Value) -> String {
    let mut text = format!(
        "Draft valid: {}\nReady to enable: {}",
        value["draft_valid"] == true,
        value["enable_ready"] == true
    );
    for diagnostic in value["diagnostics"].as_array().into_iter().flatten() {
        text.push_str(&format!(
            "\n  - {}: {}",
            diagnostic["path"].as_str().unwrap_or("$"),
            diagnostic["message"]
                .as_str()
                .or(diagnostic["code"].as_str())
                .unwrap_or("invalid")
        ));
    }
    text
}
fn output(i: &Invocation, value: Value, text: String) -> Result<CliOutput, CliError> {
    super::handlers::output(i, value, text)
}
/// Runs a Workflows command; usage and validation errors exit 1 like the npm CLI
/// (which throws a plain `Error` for them) instead of the clap-style exit code 2.
pub(super) async fn execute(
    i: &Invocation,
    client: &mut Client,
    cancel: CancellationToken,
) -> Result<CliOutput, CliError> {
    match execute_routed(i, client, cancel).await {
        Err(CliError::Invalid(message)) => Err(CliError::Contract {
            code: "invalid_argument",
            message,
        }),
        other => other,
    }
}

async fn execute_routed(
    i: &Invocation,
    client: &mut Client,
    cancel: CancellationToken,
) -> Result<CliOutput, CliError> {
    if i.command_path() == "workflows update" {
        return update::execute(i, client, cancel).await;
    }
    if i.command_path() == "workflows ask" {
        return ask::execute_cookie(i, client, cancel).await;
    }
    if i.command_path() == "workflows remove-from-project" {
        return project_links::execute_cookie(i, client, cancel).await;
    }
    if i.command_path() == "workflows add-to-project" {
        return add_to_project::execute_cookie(i, client, cancel).await;
    }
    let team = client.session().and_then(|s| s.active_team_id.clone());
    execute_service(
        i,
        client.workflows().with_filters(WorkflowFilters {
            personal: i.boolean("personal"),
            team_id: team,
            ..Default::default()
        }),
        cancel,
    )
    .await
}
pub async fn execute_sdk_workflows(
    i: &Invocation,
    client: &mut OpenMates,
    cancel: CancellationToken,
) -> Result<CliOutput, CliError> {
    if i.boolean("personal") && i.has("team") {
        return Err(CliError::Invalid(
            "Choose --personal or --team, not both.".into(),
        ));
    }
    if i.command_path() == "workflows update" {
        return Err(CliError::Contract {code:"workflow_update_requires_cookie_session",message:"Workflow YAML update with bound Project synchronization requires an authenticated cookie session.".into()});
    }
    if i.command_path() == "workflows ask" {
        // Legacy askWorkflow requires a first-party cookie session; an API key
        // never discovers/promotes credentials from an installed CLI profile.
        return Err(CliError::Contract {
            code: "workflow_ask_requires_cookie_session",
            message: "Workflow ask requires an authenticated cookie session.".into(),
        });
    }
    if i.command_path() == "workflows remove-from-project" {
        return project_links::execute_api_key(i, client, cancel).await;
    }
    if i.command_path() == "workflows add-to-project" {
        return Err(CliError::Contract {
            code: "project_item_link_unavailable",
            message: "Workflow add-to-project requires an authenticated cookie session.".into(),
        });
    }
    client.set_operation_cancel(cancel.clone());
    execute_service(
        i,
        client.workflows().with_filters(WorkflowFilters {
            personal: i.boolean("personal"),
            team_id: input::text(i, "team")?.map(str::to_owned),
            ..Default::default()
        }),
        cancel,
    )
    .await
}
/// Runs a Workflow command and keeps the HTTP 404 class visible: the SDK folds
/// 404 into a generic "unavailable" error, while npm reports the HTTP status.
async fn execute_service(
    i: &Invocation,
    service: Workflows<'_>,
    cancel: CancellationToken,
) -> Result<CliOutput, CliError> {
    match execute_service_inner(i, service, cancel).await {
        Err(CliError::Client(Error::Invalid("The requested item is unavailable."))) => {
            Err(CliError::Contract {
                code: "workflow_not_found",
                message: "Workflow resource not found (HTTP 404).".into(),
            })
        }
        // npm reports "failed with HTTP 4xx" for rejected requests.
        Err(CliError::Client(Error::Invalid("The server rejected the requested operation."))) => {
            Err(CliError::Contract {
                code: "workflow_request_rejected",
                message: "Workflow request rejected by the server (HTTP 400).".into(),
            })
        }
        other => other,
    }
}
async fn execute_service_inner(
    i: &Invocation,
    mut service: Workflows<'_>,
    cancel: CancellationToken,
) -> Result<CliOutput, CliError> {
    if cancel.is_cancelled() {
        return Err(Error::Cancelled.into());
    }
    let id = || input::positional(i, 0, "Workflow ID");
    let second = || input::positional(i, 1, "run or step ID");
    let path = i.command_path();
    match path.as_str() {
        "workflows list" => {
            check(i, &[])?;
            let rows = service.list().await?;
            let text = if rows.is_empty() {
                "No workflows yet.".into()
            } else {
                rows.iter()
                    .map(|row| {
                        format!(
                            "{}  {}  [{}]",
                            row["slug"]
                                .as_str()
                                .filter(|s| !s.is_empty())
                                .or(row["id"].as_str())
                                .unwrap_or(""),
                            row["title"].as_str().unwrap_or(""),
                            row["status"].as_str().unwrap_or("")
                        )
                    })
                    .collect::<Vec<_>>()
                    .join("\n")
            };
            output(i, json!(rows), text)
        }
        "workflows capabilities" | "workflows help-app" => {
            check(i, &[])?;
            let rows = service.capabilities().await?;
            if path == "workflows help-app" {
                let selector = id()?.replace(':', ".");
                let row = rows
                    .into_iter()
                    .find(|row| row["id"] == selector)
                    .ok_or_else(|| CliError::Invalid("Workflow capability not found.".into()))?;
                let text = format!(
                    "{}\nID: {}\nEnabled: {}",
                    row["title"].as_str().unwrap_or(""),
                    row["id"].as_str().unwrap_or(""),
                    row["enabled"] == true
                );
                output(i, row, text)
            } else {
                let text = rows
                    .iter()
                    .map(|row| {
                        format!(
                            "{}  {}  {}",
                            row["id"].as_str().unwrap_or(""),
                            row["title"].as_str().unwrap_or(""),
                            if row["enabled"] == true {
                                "enabled"
                            } else {
                                "disabled"
                            }
                        )
                    })
                    .collect::<Vec<_>>()
                    .join("\n");
                output(i, json!(rows), text)
            }
        }
        "workflows show" | "workflows enable" | "workflows disable" => {
            check(i, &[])?;
            let row = match path.as_str() {
                "workflows show" => service.show(id()?).await?,
                "workflows enable" => service.enable(id()?).await?,
                _ => service.disable(id()?).await?,
            };
            let text = workflow_text(&row);
            output(i, row, text)
        }
        "workflows delete" => {
            check(i, &["yes"])?;
            if !i.boolean("yes") {
                // npm throws a plain Error (exit 1), not a usage error (exit 2).
                return Err(CliError::Contract {
                    code: "confirmation_required",
                    message: "Refusing to delete Workflow without --yes.".into(),
                });
            }
            let value = service.delete(id()?, true).await?;
            // npm prints only {deleted}; the server's history payload stays SDK-side.
            output(
                i,
                json!({"deleted": value["deleted"] == true}),
                "Workflow deleted.".into(),
            )
        }
        "workflows create" => {
            if i.has("file") {
                check(i, &["file"])?;
                let source = files::read(input::required(i, "file")?, false)?;
                let value = service.create_from_yaml(&source).await?;
                let text = format!(
                    "{}\n{}",
                    workflow_text(&value["workflow"]),
                    validation_text(&value["validation"])
                );
                output(i, value, text)
            } else {
                let row = service.create(create(i)?).await?;
                let text = workflow_text(&row);
                output(i, row, text)
            }
        }
        "workflows validate" => {
            check(i, &["file"])?;
            let source = files::read(input::required(i, "file")?, false)?;
            let value = service.validate_yaml(&source).await?;
            let text = validation_text(&value);
            let valid = value["draft_valid"] == true;
            let mut result = output(i, value, text)?;
            if !valid {
                result.exit_code = 1;
            }
            Ok(result)
        }
        "workflows export" => {
            check(i, &["output"])?;
            let workflow = service.show(id()?).await?;
            if workflow["lifecycle"] == "temporary" {
                return Err(CliError::Invalid(
                    "Save the Workflow before exporting it.".into(),
                ));
            }
            let document = openmates_sdk::work::build_workflow_export(&workflow)?;
            let path = input::text(i, "output")?
                .map(str::to_owned)
                .unwrap_or_else(|| files::filename(&document.workflow.title));
            files::write(&path, &document)?;
            output(
                i,
                json!({"workflow_id":workflow["id"],"file":path,"binding_requirements":document.binding_requirements}),
                format!("Workflow exported: {path}"),
            )
        }
        "workflows import" => {
            check(i, &["file"])?;
            let source = files::read(input::required(i, "file")?, true)?;
            let document = files::parse(&source)?;
            let row = service.import_file(document).await?;
            let text = format!(
                "Workflow imported: {} ({})\nDisabled until you review bindings and enable it.",
                row["title"].as_str().unwrap_or(""),
                row["id"].as_str().unwrap_or("")
            );
            output(i, json!({"workflow":row,"project_id":Value::Null}), text)
        }
        "workflows history" => {
            check(i, &["limit"])?;
            let limit = input::text(i, "limit")?
                .map(|v| {
                    v.parse::<u16>()
                        .ok()
                        .filter(|n| *n > 0 && *n <= 500)
                        .ok_or_else(|| CliError::Invalid("--limit must be from1 to500.".into()))
                })
                .transpose()?;
            super::history::output(i, service.history(id()?, limit).await?)
        }
        "workflows restore" => {
            check(i, &["entry", "entry-id", "state"])?;
            let state = match input::text(i, "state")?.unwrap_or("before") {
                "before" => RestoreState::Before,
                "after" => RestoreState::After,
                _ => return Err(CliError::Invalid("--state must be before or after.".into())),
            };
            let value = service
                .restore(id()?, super::history::entry(i)?, state)
                .await?;
            output(i, value, "Workflow restored.".into())
        }
        "workflows run" | "workflows run-once" => {
            check(
                i,
                &[
                    "idempotency-key",
                    "mode",
                    "input",
                    "source-chat",
                    "message-destination-overrides",
                    "return-outputs",
                    "wait",
                    "title",
                    "graph",
                    "file",
                ],
            )?;
            if path == "workflows run-once" && i.has("mode") {
                return Err(CliError::Invalid(
                    "--mode applies to an existing Workflow run; run-once does not accept it."
                        .into(),
                ));
            }
            let options = run_options(i)?;
            let idempotency_key = options.idempotency_key.clone();
            if path == "workflows run-once" {
                let (mut title, graph) = if let Some(file) = input::text(i, "file")? {
                    if i.has("graph") {
                        return Err(CliError::Invalid(
                            "Specify exactly one of --graph or --file.".into(),
                        ));
                    }
                    let document = files::parse(&files::read(file, true)?)?;
                    (document.workflow.title, document.workflow.graph)
                } else {
                    (
                        String::new(),
                        json_input::<WorkflowGraph>(i, "graph")?.ok_or_else(|| {
                            CliError::Invalid("Specify --graph or --file.".into())
                        })?,
                    )
                };
                if let Some(value) = input::text(i, "title")? {
                    title = value.into()
                }
                if title.trim().is_empty() {
                    return Err(CliError::Invalid("run-once requires --title.".into()));
                }
                let mut value = service.run_once(&title, graph, options).await?;
                if i.boolean("wait") {
                    let workflow = value["workflow"]["id"]
                        .as_str()
                        .ok_or(Error::Protocol)?
                        .to_owned();
                    value["run"] = wait(
                        &mut service,
                        &workflow,
                        &value["run"],
                        &idempotency_key,
                        cancel.clone(),
                    )
                    .await?;
                }
                let text = format!(
                    "{}\n{}",
                    workflow_text(&value["workflow"]),
                    run_text(&value["run"])
                );
                output(i, value, text)
            } else {
                if i.has("title") || i.has("graph") || i.has("file") {
                    return Err(CliError::Invalid(
                        "Definition options apply to run-once; run uses an existing Workflow."
                            .into(),
                    ));
                }
                let mut row = service.run(id()?, options).await?;
                if i.boolean("wait") {
                    row = wait(&mut service, id()?, &row, &idempotency_key, cancel.clone()).await?;
                }
                let text = run_text(&row);
                output(i, row, text)
            }
        }
        "workflows runs" => {
            check(i, &[])?;
            let rows = service.runs(id()?).await?;
            let text = if rows.is_empty() {
                "No workflow runs yet.".into()
            } else {
                rows.iter().map(run_text).collect::<Vec<_>>().join("\n\n")
            };
            output(i, json!(rows), text)
        }
        "workflows run-show" => {
            check(i, &[])?;
            let row = service.run_detail(id()?, second()?).await?;
            let text = run_text(&row);
            output(i, row, text)
        }
        "workflows run-delete" | "workflows run-cancel" => {
            check(
                i,
                if path == "workflows run-delete" {
                    &["yes"]
                } else {
                    &[]
                },
            )?;
            if path == "workflows run-delete" && !i.boolean("yes") {
                return Err(CliError::Invalid("Run deletion requires --yes.".into()));
            }
            let value = if path == "workflows run-delete" {
                service.delete_run(id()?, second()?).await?
            } else {
                service.cancel_run(id()?, second()?).await?
            };
            let text = format!(
                "Status: {}",
                value["status"].as_str().unwrap_or("acknowledged")
            );
            output(i, value, text)
        }
        "workflows save-as-reusable" => {
            check(i, &["idempotency-key"])?;
            let row = service
                .save_as_reusable(id()?, input::required(i, "idempotency-key")?)
                .await?;
            let text = workflow_text(&row);
            output(i, row, text)
        }
        "workflows step-preview" | "workflows step-test" => {
            check(i, &["input", "node", "upstream", "yes"])?;
            let options = step_options(i)?;
            if path == "workflows step-preview" && i.has("yes") {
                return Err(CliError::Invalid("Preview does not use --yes.".into()));
            }
            let row = if path == "workflows step-preview" {
                service.preview_step(id()?, second()?, options).await?
            } else {
                service.step_test(id()?, second()?, options).await?
            };
            let text = if path == "workflows step-preview" {
                row["text"]
                    .as_str()
                    .or(row["message"].as_str())
                    .or(row["body"].as_str())
                    .unwrap_or("")
                    .into()
            } else {
                run_text(&row)
            };
            output(i, row, text)
        }
        "workflows respond" => {
            check(i, &["input"])?;
            let values: BTreeMap<String, Value> = json_input(i, "input")?.unwrap_or_default();
            let row = service
                .respond(
                    id()?,
                    second()?,
                    input::positional(i, 2, "step ID")?,
                    values,
                )
                .await?;
            let text = run_text(&row);
            output(i, row, text)
        }
        "workflows input" => {
            let row = service.start_input(input_options(i)?).await?;
            let text = session_text(&row);
            output(i, row, text)
        }
        "workflows input-show" | "workflows input-stop" | "workflows input-undo" => {
            check(i, &[])?;
            let row = match path.as_str() {
                "workflows input-show" => service.input_session(id()?).await?,
                "workflows input-stop" => service.stop_input(id()?).await?,
                _ => service.undo_input(id()?).await?,
            };
            let text = session_text(&row);
            output(i, row, text)
        }
        "workflows input-events" => {
            check(i, &["after"])?;
            let after = input::text(i, "after")?
                .unwrap_or("0")
                .parse::<u64>()
                .map_err(|_| CliError::Invalid("--after must be a nonnegative event ID.".into()))?;
            let rows = service.input_events(id()?, after).await?;
            let text = rows
                .iter()
                .map(|row| {
                    format!(
                        "{}  {}  {}",
                        row["event_id"],
                        row["type"].as_str().unwrap_or(""),
                        row["status"].as_str().unwrap_or("")
                    )
                })
                .collect::<Vec<_>>()
                .join("\n");
            output(i, json!(rows), text)
        }
        "workflows input-follow-up" => {
            check(i, &["text"])?;
            let positional = i
                .positionals
                .iter()
                .skip(1)
                .cloned()
                .collect::<Vec<_>>()
                .join(" ");
            let text = input::text(i, "text")?.unwrap_or(&positional).trim();
            if text.is_empty() {
                return Err(CliError::Invalid("Provide follow-up text.".into()));
            }
            let row = service.follow_up_input(id()?, text).await?;
            let text = session_text(&row);
            output(i, row, text)
        }
        _ => Err(CliError::Unsupported {
            command: path,
            reason: "This native Workflow command has not been ported yet.".into(),
        }),
    }
}
async fn wait(
    service: &mut Workflows<'_>,
    workflow: &str,
    initial: &Value,
    idempotency_key: &str,
    cancel: CancellationToken,
) -> Result<Value, CliError> {
    service
        .wait_run(workflow, initial, WorkflowWaitOptions::default(), cancel)
        .await
        .map_err(|source| CliError::WorkflowWait {
            workflow_id: workflow.into(),
            accepted_run: initial.clone(),
            idempotency_key: idempotency_key.into(),
            source,
        })
}
#[cfg(test)]
mod tests {
    use super::*;
    #[tokio::test]
    async fn cancelled_wait_retains_accepted_run_and_never_dispatches_again() {
        let mut client = Client::new("http://127.0.0.1:1", None).unwrap();
        let cancel = CancellationToken::new();
        cancel.cancel();
        let initial = json!({"id":"22222222-2222-4222-8222-222222222222","status":"queued","input":{"private":"retained only in authorized JSON"}});
        let error = wait(
            &mut client.workflows(),
            "11111111-1111-4111-8111-111111111111",
            &initial,
            "same-key",
            cancel,
        )
        .await
        .err()
        .unwrap();
        assert_eq!(error.exit_code(), 130);
        let value = error.structured_error();
        assert_eq!(value["error"]["run_id"], initial["id"]);
        assert_eq!(value["error"]["accepted_run"], initial);
        assert_eq!(value["error"]["idempotency_key"], "same-key");
        assert_eq!(value["error"]["cause"], "cancelled");
        assert!(!error.to_string().contains("private"));
    }
    fn i(flags: &[(&str, Value)]) -> Invocation {
        Invocation {
            path: vec!["workflows".into(), "run".into()],
            positionals: vec![],
            flags: flags
                .iter()
                .map(|(k, v)| (k.to_string(), v.clone()))
                .collect(),
        }
    }
    #[tokio::test]
    async fn native_dispatch_keeps_idempotency_header_and_returns_raw_accepted_run() {
        use tokio::io::{AsyncReadExt, AsyncWriteExt};
        const WORKFLOW: &str = "11111111-1111-4111-8111-111111111111";
        const RUN: &str = "22222222-2222-4222-8222-222222222222";
        const KEY: &str = "33333333-3333-4333-8333-333333333333";
        for waiting in [false, true] {
            let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
            let base = format!("http://{}", listener.local_addr().unwrap());
            let server = tokio::spawn(async move {
                let (mut socket, _) = listener.accept().await.unwrap();
                let mut bytes = vec![];
                let mut part = [0; 4096];
                let (end, length) = loop {
                    let count = socket.read(&mut part).await.unwrap();
                    assert!(count > 0);
                    bytes.extend_from_slice(&part[..count]);
                    if let Some(end) = bytes.windows(4).position(|part| part == b"\r\n\r\n") {
                        let header = std::str::from_utf8(&bytes[..end]).unwrap();
                        let length = header
                            .lines()
                            .filter_map(|line| line.split_once(':'))
                            .find(|(key, _)| key.eq_ignore_ascii_case("content-length"))
                            .map(|(_, value)| value.trim().parse::<usize>().unwrap())
                            .unwrap_or(0);
                        break (end + 4, length);
                    }
                };
                while bytes.len() < end + length {
                    let count = socket.read(&mut part).await.unwrap();
                    assert!(count > 0);
                    bytes.extend_from_slice(&part[..count]);
                }
                let header = std::str::from_utf8(&bytes[..end]).unwrap();
                assert_eq!(
                    header.lines().next().unwrap(),
                    format!("POST /v1/workflows/{WORKFLOW}/run HTTP/1.1")
                );
                assert!(
                    header
                        .lines()
                        .filter_map(|line| line.split_once(':'))
                        .any(|(name, value)| name.eq_ignore_ascii_case("idempotency-key")
                            && value.trim() == KEY)
                );
                let body: Value = serde_json::from_slice(&bytes[end..end + length]).unwrap();
                assert_eq!(body["input"]["city"], "Berlin");
                assert_eq!(body["mode"], "test");
                assert!(body.get("idempotency_key").is_none());
                let body =
                json!({"run":{"id":RUN,"status":"queued","trigger_type":"manual","node_runs":[]}})
                    .to_string();
                let response = format!(
                    "HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: {}\r\nConnection: close\r\n\r\n{body}",
                    body.len()
                );
                socket.write_all(response.as_bytes()).await.unwrap();
                if waiting {
                    let (mut socket, _) = listener.accept().await.unwrap();
                    let mut header = vec![];
                    while !header.windows(4).any(|part| part == b"\r\n\r\n") {
                        let mut part = [0; 4096];
                        let count = socket.read(&mut part).await.unwrap();
                        assert!(count > 0);
                        header.extend_from_slice(&part[..count]);
                    }
                    assert_eq!(
                        std::str::from_utf8(&header)
                            .unwrap()
                            .lines()
                            .next()
                            .unwrap(),
                        format!("GET /v1/workflows/{WORKFLOW}/runs/{RUN} HTTP/1.1")
                    );
                    let body = json!({"run":{"id":RUN,"workflow_id":WORKFLOW,"status":"completed","output_summary":{"deliveries":{"selected":{"delivery_id":"44444444-4444-4444-8444-444444444444","chat_id":"55555555-5555-4555-8555-555555555555","message_id":"66666666-6666-4666-8666-666666666666","status":"acknowledged"}}}}}).to_string();
                    socket.write_all(format!("HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: {}\r\nConnection: close\r\n\r\n{body}",body.len()).as_bytes()).await.unwrap();
                }
            });
            let session = openmates_sdk::Session {
                api_url: base.clone(),
                session_id: "synthetic".into(),
                cookies: Default::default(),
                ws_token: None,
                master_key: zeroize::Zeroizing::new([7; 32]),
                hashed_email: "synthetic-owner".into(),
                user_email_salt: String::new(),
                email_encryption_key: None,
                created_at: 1,
                paired_session_expires_at: None,
                active_team_id: None,
            };
            let mut client = Client::new(&base, Some(session)).unwrap();
            let mut arguments = vec![
                "openmates",
                "workflows",
                "run",
                WORKFLOW,
                "--idempotency-key",
                KEY,
                "--mode",
                "test",
                "--input",
                r#"{"city":"Berlin"}"#,
                "--personal",
                "--json",
            ];
            if waiting {
                arguments.push("--wait");
            }
            let parsed = super::super::parse_from(arguments).ok().unwrap();
            let result = tokio::time::timeout(
                std::time::Duration::from_secs(3),
                super::super::execute(
                    parsed.invocation.as_ref().unwrap(),
                    &mut client,
                    CancellationToken::new(),
                ),
            )
            .await
            .unwrap()
            .ok()
            .expect("native accepted run");
            let value: Value = serde_json::from_str(&result.stdout).unwrap();
            assert_eq!(value["id"], RUN);
            assert_eq!(
                value["status"],
                if waiting { "completed" } else { "queued" }
            );
            assert!(value.get("run").is_none());
            tokio::time::timeout(std::time::Duration::from_secs(3), server)
                .await
                .unwrap()
                .unwrap();
        }
    }

    #[test]
    fn typed_run_requires_stable_key_and_accepts_delivery_aware_wait() {
        assert!(run_options(&i(&[])).is_err());
        let options = run_options(&i(&[
            (
                "idempotency-key",
                json!("11111111-1111-4111-8111-111111111111"),
            ),
            ("mode", json!("test")),
            ("input", json!("{\"city\":\"Berlin\"}")),
            (
                "return-outputs",
                json!("{\"report\":{\"node_id\":\"step\",\"output\":\"text\"}}"),
            ),
        ]))
        .ok()
        .unwrap();
        assert_eq!(options.input["city"], "Berlin");
        assert_eq!(serde_json::to_value(options.mode).unwrap(), "test");
        assert!(
            run_options(&i(&[
                ("wait", json!(true)),
                (
                    "idempotency-key",
                    json!("11111111-1111-4111-8111-111111111111")
                )
            ]))
            .is_ok()
        );
        assert!(
            run_options(&i(&[
                ("idempotency-key", json!("stable")),
                ("input", json!("[]"))
            ]))
            .is_err()
        );
    }
    #[test]
    fn create_and_step_inputs_are_typed_and_no_unrecognized_field_is_dropped() {
        let value=create(&i(&[("title",json!("Native")),("graph",json!("{\"nodes\":[{\"id\":\"manual\",\"type\":\"manual_trigger\",\"config\":{}}],\"edges\":[]}")),("run-content-retention",json!("last_5"))])).ok().unwrap();
        assert_eq!(
            serde_json::to_value(value.run_content_retention).unwrap(),
            "last_5"
        );
        assert!(
            create(&i(&[
                ("title", json!("Native")),
                ("graph", json!("{\"unknown\":1}"))
            ]))
            .is_err()
        );
        assert!(
            step_options(&i(&[(
                "node",
                json!("{\"id\":\"unknown\",\"type\":\"future_unsupported_node\"}")
            )]))
            .is_err()
        );
    }
    #[test]
    fn input_uses_explicit_timezone_and_keeps_selection_and_optimistic_options() {
        let mut command = i(&[
            ("timezone", json!("Europe/Berlin")),
            ("workflow-id", json!("work")),
            ("project-id", json!("engineering")),
            ("optimistic", json!(true)),
        ]);
        command.path = vec!["workflows".into(), "input".into()];
        command.positionals = vec!["Check weather".into()];
        let value = input_options(&command).ok().unwrap();
        assert_eq!(value.timezone.as_deref(), Some("Europe/Berlin"));
        assert_eq!(value.selected_project_id.as_deref(), Some("engineering"));
        assert!(value.optimistic_save);
    }
}
