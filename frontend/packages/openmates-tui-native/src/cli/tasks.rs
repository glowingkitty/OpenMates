//! Typed Task command routing over the shared Rust SDK namespace.
use super::{CliError, CliOutput, Invocation, codex, task_input as input};
use crate::{client::Client, error::Error};
use openmates_sdk::{
    OpenMates,
    work::{
        TaskActivityInput, TaskActivityQuery, TaskAskOptions, TaskCaller, Tasks,
    },
};
use serde_json::{Value, json};
use tokio_util::sync::CancellationToken;
pub(super) fn supported(invocation: &Invocation) -> bool {
    matches!(
        invocation.command_path().as_str(),
        "tasks ask"
            | "tasks list"
            | "tasks status"
            | "tasks board"
            | "tasks show"
            | "tasks create"
            | "tasks edit"
            | "tasks start"
            | "tasks done"
            | "tasks block"
            | "tasks unblock"
            | "tasks skip"
            | "tasks delete"
            | "tasks history"
            | "tasks restore"
            | "tasks reorder"
            | "tasks add-to-project"
            | "tasks remove-from-project"
            | "tasks activity list"
            | "tasks activity search"
            | "tasks activity add"
            | "tasks activity delete"
            | "tasks activity flush"
            | "tasks dependencies list"
            | "tasks dependencies add"
            | "tasks dependencies remove"
            | "tasks connect"
            | "tasks connection"
            | "tasks resume"
            | "tasks release"
    )
}
pub(super) async fn execute(
    invocation: &Invocation,
    client: &mut Client,
    cancel: CancellationToken,
    store: Option<&crate::runtime_store::RuntimeStore>,
) -> Result<CliOutput, CliError> {
    if invocation.command_path() == "tasks ask" {
        return ask_cookie(invocation, client, cancel).await;
    }
    let journal = store
        .map(|store| {
            crate::task_delivery::CookieJournalContext::capture(client)
                .and_then(|context| context.journal(store))
                .map_err(CliError::from)
        })
        .transpose()?;
    if let Some(journal) = journal.as_ref() {
        super::task_legacy_outbox::drain(client, journal, &cancel).await?;
    }
    let team = client
        .session()
        .and_then(|session| session.active_team_id.clone());
    execute_service(invocation, client.tasks(), team, cancel, journal).await
}
pub async fn execute_sdk_tasks(
    invocation: &Invocation,
    client: &mut OpenMates,
    cancel: CancellationToken,
) -> Result<CliOutput, CliError> {
    execute_sdk_inner(invocation, client, cancel, None, None).await
}
pub async fn execute_sdk_tasks_with_delivery(
    invocation: &Invocation,
    client: &mut OpenMates,
    cancel: CancellationToken,
    store: &crate::runtime_store::RuntimeStore,
    api_url: &str,
) -> Result<CliOutput, CliError> {
    execute_sdk_inner(invocation, client, cancel, Some(store), Some(api_url)).await
}
async fn execute_sdk_inner(
    invocation: &Invocation,
    client: &mut OpenMates,
    cancel: CancellationToken,
    store: Option<&crate::runtime_store::RuntimeStore>,
    api_url: Option<&str>,
) -> Result<CliOutput, CliError> {
    if invocation.boolean("personal") && invocation.has("team") {
        return Err(CliError::Invalid(
            "Choose --personal or --team, not both.".into(),
        ));
    }
    client.set_operation_cancel(cancel.clone());
    let team = input::text(invocation, "team")?.map(str::to_owned);
    let journal = if let Some(store) = store {
        use sha2::{Digest, Sha256};
        let session = client.sdk_session().await?;
        let owner = session
            .pointer("/user/id")
            .and_then(Value::as_str)
            .ok_or(CliError::Client(Error::Protocol))?;
        let owner = format!("{:x}", Sha256::digest(owner.as_bytes()));
        let key = client.master_key().await?;
        let origin = url::Url::parse(api_url.ok_or(CliError::Client(Error::Protocol))?)
            .map_err(|_| CliError::Client(Error::Protocol))?
            .origin()
            .ascii_serialization();
        Some(crate::task_delivery::Journal::new(
            store.clone(),
            owner,
            serde_json::to_string(&(origin, &team))
                .map_err(|_| CliError::Client(Error::Protocol))?,
            key,
        ))
    } else {
        None
    };
    execute_service(invocation, client.tasks(), team, cancel, journal).await
}

fn result(invocation: &Invocation, value: Value, human: String) -> Result<CliOutput, CliError> {
    if invocation.boolean("json") {
        CliOutput::json(&value)
    } else {
        Ok(CliOutput::text(human))
    }
}
fn task_json(task: &Value) -> Value {
    let mut value = json!({});
    for field in [
        "task_id",
        "short_id",
        "title",
        "description",
        "labels",
        "tags",
        "latest_instruction",
        "status",
        "assignee_type",
        "assignee_identity",
        "assignee_hash",
        "primary_chat_id",
        "external_chat",
        "linked_project_ids",
        "plan_id",
        "due_at",
        "priority",
        "priority_level",
        "position",
        "queue_state",
        "blocked_reason_code",
        "ai_execution_state",
        "version",
    ] {
        value[field] = task[field].clone();
    }
    // npm tasksCli `queueState: record.queue_state ?? "none"`.
    if value["queue_state"].is_null() {
        value["queue_state"] = json!("none");
    }
    for field in ["slug", "blocked_reason"] {
        value[field] = task[field]
            .as_str()
            .filter(|text| !text.is_empty())
            .map(|text| json!(text))
            .unwrap_or(Value::Null);
    }
    value
}
fn task_result(i: &Invocation, task: Value) -> Result<CliOutput, CliError> {
    let text = render_task(&task);
    result(i, json!({"task":task_json(&task)}), text)
}
fn render_task(task: &Value) -> String {
    let id = task["short_id"]
        .as_str()
        .or(task["task_id"].as_str())
        .unwrap_or("Task");
    let title = task["title"].as_str().unwrap_or("");
    let status = task["status"].as_str().unwrap_or("");
    let mut output = format!("{id}: {title}\nStatus: {status}");
    if let Some(id) = task["task_id"].as_str() {
        output.push_str(&format!("\nID: {id}"));
    }
    for (field, label) in [
        ("description", "Description"),
        ("latest_instruction", "Latest instruction"),
        ("blocked_reason", "Blocked reason"),
    ] {
        if let Some(text) = task[field].as_str().filter(|text| !text.is_empty()) {
            output.push_str(&format!("\n{label}: {text}"));
        }
    }
    output
}
fn render_list(tasks: &[Value]) -> String {
    if tasks.is_empty() {
        "No tasks found.".into()
    } else {
        tasks
            .iter()
            .map(|task| {
                format!(
                    "{}  {}  [{}]",
                    task["short_id"]
                        .as_str()
                        .or(task["task_id"].as_str())
                        .unwrap_or("Task"),
                    task["title"].as_str().unwrap_or(""),
                    task["status"].as_str().unwrap_or("")
                )
            })
            .collect::<Vec<_>>()
            .join("\n")
    }
}
fn render_board(tasks: &[Value]) -> Result<String, CliError> {
    let mut tasks = tasks.to_vec();
    crate::task_order::for_host()?.sort_tasks(&mut tasks)?;
    let mut output = String::new();
    for status in ["backlog", "todo", "in_progress", "blocked", "done"] {
        output.push_str(&format!("{}\n", status.replace('_', " ")));
        let selected = tasks
            .iter()
            .filter(|task| task["status"] == status)
            .cloned()
            .collect::<Vec<_>>();
        output.push_str(&render_list(&selected));
        output.push_str("\n\n");
    }
    Ok(output)
}
fn number(invocation: &Invocation, name: &str, default: u16, max: u16) -> Result<u16, CliError> {
    match input::text(invocation, name)? {
        None => Ok(default),
        Some(value) => value
            .parse::<u16>()
            .ok()
            .filter(|value| *value > 0 && *value <= max)
            .ok_or_else(|| CliError::Invalid(format!("--{name} must be from 1 to {max}."))),
    }
}
pub(super) async fn verify_external(
    external: &mut Option<openmates_sdk::work::ExternalChat>,
    cancel: &CancellationToken,
) -> Result<(), CliError> {
    if let Some(external) = external {
        codex::claim_external(external, cancel).await?;
    }
    Ok(())
}
fn ask_input(invocation: &Invocation) -> Result<(String, TaskAskOptions), CliError> {
    input::check_flags(
        invocation,
        &[
            "text",
            "assign",
            "assignee",
            "projects",
            "due",
            "slug",
            "auto-approve",
            "auto-approve-memories",
            "no-pii-detection",
            "response-timeout-seconds",
        ],
    )?;
    let instruction = input::text(invocation, "text")?
        .map(str::to_owned)
        .unwrap_or_else(|| invocation.positionals.join(" "))
        .trim()
        .to_owned();
    if instruction.is_empty() {
        // npm requiredAskInstruction: a runtime failure (exit 1), not a usage error.
        return Err(CliError::Contract {
            code: "command_failed",
            message: "Missing ask instruction. Example: openmates tasks ask \"Prepare launch copy\"".into(),
        });
    }
    let mut fields = invocation.flags.clone();
    fields.insert("title".into(), json!("Task proposal"));
    fields.remove("external-chat");
    fields.remove("external-chat-title");
    let defaults = Invocation {
        path: invocation.path.clone(),
        positionals: vec![],
        flags: fields,
    };
    Ok((
        instruction,
        TaskAskOptions {
            create: input::create(&defaults)?,
        },
    ))
}
fn fallback(value: &Value) -> bool {
    value["fallback_to_chat"] == true || value["outcome"] == "fallback_to_chat"
}
pub(super) fn ask_text(value: &Value, namespace: &str) -> String {
    let mut text = value["summary"]
        .as_str()
        .filter(|text| !text.trim().is_empty())
        .map(str::to_owned)
        .unwrap_or_else(|| format!("Applied {namespace} ask changes."));
    let change = value["change_set_id"].as_str().filter(|id| !id.is_empty());
    if let Some(change) = change {
        text.push_str(&format!("\nChange set: {change}"));
    }
    let history = value.get("history").filter(|history| history.is_object());
    let undo = history
        .and_then(|history| history["undo_all_command"].as_str())
        .filter(|text| !text.is_empty())
        .or_else(|| {
            if history.is_none() {
                value["undo_all_command"]
                    .as_str()
                    .filter(|text| !text.is_empty())
            } else {
                None
            }
        });
    let history_change = if let Some(history) = history {
        history
            .pointer("/change_set/change_set_id")
            .and_then(Value::as_str)
    } else {
        change
    };
    let undo = undo.map(str::to_owned).or_else(|| {
        history_change
            .filter(|id| !id.is_empty())
            .map(|id| format!("openmates history undo {id}"))
    });
    if let Some(undo) = undo {
        text.push_str(&format!("\nUndo all: {undo}"));
        let entries = if let Some(history) = history {
            history.get("undo_entry_commands")
        } else {
            value.get("undo_entry_commands")
        };
        for command in entries
            .and_then(Value::as_array)
            .into_iter()
            .flatten()
            .filter_map(Value::as_str)
        {
            text.push_str(&format!("\nUndo part: {command}"));
        }
    }
    text
}

async fn ask_cookie(
    invocation: &Invocation,
    client: &mut Client,
    cancel: CancellationToken,
) -> Result<CliOutput, CliError> {
    let (instruction, options) = ask_input(invocation)?;
    let team = client
        .session()
        .and_then(|session| session.active_team_id.clone());
    let filters = input::filters(invocation, team, false)?;
    let value = client
        .tasks()
        .with_filters(filters)
        .with_caller(TaskCaller {
            codex_thread_id: std::env::var("CODEX_THREAD_ID").ok(),
            as_assignee: false,
        })
        .ask(&instruction, options)
        .await?;
    workspace_ask_output(invocation, client, cancel, instruction, value, "task").await
}
fn workspace_fallback_invocation(invocation: &Invocation, instruction: String) -> Invocation {
    let mut flags = std::collections::BTreeMap::new();
    for key in [
        "json",
        "auto-approve",
        "auto-approve-memories",
        "no-pii-detection",
        "response-timeout-seconds",
    ] {
        if let Some(value) = invocation.flags.get(key) {
            flags.insert(key.into(), value.clone());
        }
    }
    // A workspace ask fallback is an ordinary new chat, with this capability
    // deliberately disabled exactly as in the retained CLI. Never infer work
    // execution or task-update permission from the ask response itself.
    flags.insert("no-task-update-jobs".into(), json!(true));
    Invocation {
        path: vec!["chats".into(), "new".into()],
        positionals: vec![instruction],
        flags,
    }
}
pub(super) async fn workspace_ask_output(
    invocation: &Invocation,
    client: &mut Client,
    cancel: CancellationToken,
    instruction: String,
    value: Value,
    namespace: &str,
) -> Result<CliOutput, CliError> {
    if !fallback(&value) {
        let text = ask_text(&value, namespace);
        return result(invocation, value, text);
    }
    let message = value["fallback_message"]
        .as_str()
        .or(value["summary"].as_str())
        .unwrap_or("Workspace ask needs more context.")
        .to_owned();
    if !invocation.boolean("json") {
        use std::io::Write;
        let mut stderr = std::io::stderr();
        let _ = writeln!(
            stderr,
            "Workspace ask needs chat context: {}\nStarting a new chat...",
            super::terminal_text(&message)
        )
        .and_then(|()| stderr.flush());
    }
    let chat = workspace_fallback_invocation(invocation, instruction);
    let output = super::send::send(&chat, client, cancel).await?;
    if invocation.boolean("json") {
        let mut response: Value =
            serde_json::from_str(&output.stdout).map_err(|_| CliError::Client(Error::Protocol))?;
        response["workspace_ask_fallback"] =
            json!({"outcome":"fallback_to_chat","fallback_message":message,"namespace":namespace});
        CliOutput::json(&response)
    } else {
        Ok(output)
    }
}
async fn execute_service(
    invocation: &Invocation,
    service: Tasks<'_>,
    team: Option<String>,
    cancel: CancellationToken,
    journal: Option<crate::task_delivery::Journal>,
) -> Result<CliOutput, CliError> {
    if cancel.is_cancelled() {
        return Err(Error::Cancelled.into());
    }
    let path = invocation.command_path();
    let filters = input::filters(
        invocation,
        team,
        matches!(
            path.as_str(),
            "tasks create" | "tasks edit" | "tasks reorder"
        ),
    )?;
    let caller = TaskCaller {
        codex_thread_id: std::env::var("CODEX_THREAD_ID").ok(),
        as_assignee: invocation.boolean("as-assignee"),
    };
    let mut service = service.with_filters(filters).with_caller(caller.clone());
    if super::task_queue::supported(invocation) {
        if let Some(journal) = journal.as_ref() {
            let value = match super::task_queue::deliver(
                invocation,
                &mut service,
                journal,
                &cancel,
                &caller,
            )
            .await
            {
                Ok(value) => value,
                Err(error) => return super::task_queue::pending_output(invocation, error),
            };
            let value = match super::task_queue_actions::render(&path, value) {
                Ok((value, text)) => return result(invocation, value, text),
                Err(value) => value,
            };
            let text = if path == "tasks activity add" {
                value["message"]
                    .as_str()
                    .unwrap_or("Task Activity saved.")
                    .to_owned()
            } else if path == "tasks delete" {
                "Task deleted.".into()
            } else if path == "tasks activity flush" {
                format!(
                    "Activity delivery: {} sent, {} pending.",
                    value["delivered"], value["pending"]
                )
            } else {
                render_task(&value)
            };
            let value = if path == "tasks activity add" {
                json!({"entry":value})
            } else if path != "tasks delete" && !path.starts_with("tasks activity") {
                json!({"task":task_json(&value)})
            } else {
                value
            };
            return result(invocation, value, text);
        }
        if invocation.has("delivery-id") || std::env::var_os("CODEX_THREAD_ID").is_some() {
            return Err(CliError::Unsupported{command:path,reason:"This Task operation requires the native encrypted delivery journal; use the application command runtime.".into()});
        }
    }
    execute_command(invocation, service, path, cancel, journal).await
}

// Select the command before polling it. Keeping each command's locals in its
// own heap future avoids allocating every branch's debug poll temporaries on
// the caller's stack, even for a simple list operation.
fn execute_command<'a>(
    invocation: &'a Invocation,
    mut service: Tasks<'a>,
    path: String,
    cancel: CancellationToken,
    journal: Option<crate::task_delivery::Journal>,
) -> std::pin::Pin<Box<dyn std::future::Future<Output = Result<CliOutput, CliError>> + Send + 'a>> {
    let id = || input::positional(invocation, 0, "Task ID");
    match path.as_str() {
        "tasks ask" => Box::pin(async move {
            let (instruction, options) = ask_input(invocation)?;
            let value = service.ask(&instruction, options).await?;
            if fallback(&value) {
                return Err(CliError::Client(Error::Unavailable {
                    code: "workspace_ask_chat_fallback_unavailable",
                    reason: "API_KEY_CHAT_CONTINUATION_NOT_PORTED",
                }));
            }
            let text = ask_text(&value, "task");
            result(invocation, value, text)
        }),
        "tasks list" | "tasks board" | "tasks status" => Box::pin(async move {
            input::check_flags(invocation, &[])?;
            if path == "tasks status" && !invocation.positionals.is_empty() {
                let task = service.show(id()?).await?;
                return task_result(invocation, task);
            }
            let tasks = service.list().await?;
            let human = if path == "tasks board" && !invocation.boolean("json") {
                render_board(&tasks)?
            } else {
                render_list(&tasks)
            };
            result(
                invocation,
                json!({"tasks":tasks.iter().map(task_json).collect::<Vec<_>>(),"complete":true}),
                human,
            )
        }),
        "tasks show" => Box::pin(async move {
            input::check_flags(invocation, &[])?;
            let task = service.show(id()?).await?;
            task_result(invocation, task)
        }),
        "tasks create" => Box::pin(async move {
            input::check_flags(
                invocation,
                &[
                    "title",
                    "description",
                    "slug",
                    "assign",
                    "assignee",
                    "projects",
                    "due",
                    "as-assignee",
                ],
            )?;
            let mut payload = input::create(invocation)?;
            verify_external(&mut payload.external_chat, &cancel).await?;
            let task = service.create(payload).await?;
            task_result(invocation, task)
        }),
        "tasks edit" => Box::pin(async move {
            input::check_flags(
                invocation,
                &[
                    "title",
                    "description",
                    "slug",
                    "assign",
                    "assignee",
                    "projects",
                    "due",
                    "add-label",
                    "add-labels",
                    "add-tag",
                    "add-tags",
                    "remove-label",
                    "remove-labels",
                    "remove-tag",
                    "remove-tags",
                ],
            )?;
            let mut payload = input::patch(invocation)?;
            if let Some(external) = payload.external_chat.as_mut() {
                verify_external(external, &cancel).await?;
            }
            let task = service.update(id()?, payload).await?;
            task_result(invocation, task)
        }),
        "tasks start" | "tasks done" | "tasks unblock" | "tasks skip" | "tasks release" => {
            Box::pin(async move {
                input::check_flags(invocation, &[])?;
                let task = match path.as_str() {
                    "tasks start" => service.start(id()?).await?,
                    "tasks done" => service.done(id()?).await?,
                    "tasks unblock" => service.unblock(id()?).await?,
                    "tasks skip" => service.skip(id()?).await?,
                    _ => {
                        codex::guard_release(&mut service, id()?).await?;
                        service.release(id()?).await?
                    }
                };
                task_result(invocation, task)
            })
        }
        "tasks block" => Box::pin(async move {
            input::check_flags(invocation, &["reason-code", "reason", "reason-text"])?;
            let (reason, text) = super::task_queue_actions::block_args(invocation)?;
            let task = service.block(id()?, reason, text).await?;
            task_result(invocation, task)
        }),
        "tasks delete" => Box::pin(async move {
            input::check_flags(invocation, &["confirm"])?;
            if !invocation.boolean("confirm") {
                return Err(CliError::Invalid(
                    "Deleting a Task requires --confirm.".into(),
                ));
            }
            let value = service.delete(id()?, true).await?;
            result(invocation, value, "Task deleted.".into())
        }),
        "tasks history" => Box::pin(async move {
            input::check_flags(invocation, &["limit"])?;
            let value = service
                .history(id()?, Some(number(invocation, "limit", 50, 500)?))
                .await?;
            super::history::output(invocation, value)
        }),
        "tasks restore" => Box::pin(async move {
            input::check_flags(invocation, &["entry", "entry-id", "state"])?;
            let (entry, state) = super::task_queue_actions::restore_args(invocation)?;
            let value = service.restore(id()?, entry, state).await?;
            result(invocation, value, "Task restored.".into())
        }),
        "tasks reorder" => Box::pin(async move {
            input::check_flags(invocation, &["before", "after", "position"])?;
            let movement = super::task_queue_actions::task_move(invocation)?;
            let value = service.reorder(id()?, movement).await?;
            result(invocation, json!({"tasks":value}), "Task reordered.".into())
        }),
        "tasks add-to-project" | "tasks remove-from-project" => Box::pin(async move {
            input::check_flags(invocation, &[])?;
            let project = input::positional(invocation, 1, "Project ID")?;
            let task = if path == "tasks add-to-project" {
                service.add_to_project(id()?, project).await?
            } else {
                service.remove_from_project(id()?, project).await?
            };
            task_result(invocation, task)
        }),
        "tasks dependencies list" => Box::pin(async move {
            input::check_flags(invocation, &[])?;
            let value = service.dependencies().list(id()?).await?;
            let text = serde_json::to_string_pretty(&value)
                .map_err(|_| CliError::Client(Error::Protocol))?;
            result(invocation, value, text)
        }),
        "tasks dependencies add" | "tasks dependencies remove" => Box::pin(async move {
            input::check_flags(invocation, &["target"])?;
            let target = super::task_queue_actions::target(invocation)?;
            let value = if path == "tasks dependencies add" {
                service.dependencies().add(id()?, &target).await?
            } else {
                service.dependencies().remove(id()?, &target).await?
            };
            result(invocation, value, "Task dependency saved.".into())
        }),
        "tasks activity list" | "tasks activity search" => Box::pin(async move {
            input::check_flags(
                invocation,
                &[
                    "limit",
                    "max-entries",
                    "query",
                    "cursor",
                    "newest-first",
                    "flush-pending",
                    "as-assignee",
                ],
            )?;
            let query = if path == "tasks activity search" {
                Some(input::required(invocation, "query")?.to_owned())
            } else {
                None
            };
            let max_entries = if invocation.has("max-entries") {
                Some(number(invocation, "max-entries", 200, 200)?)
            } else {
                query.as_ref().map(|_| 200)
            };
            let delivery = if invocation.boolean("flush-pending") {
                let journal = journal.as_ref().ok_or_else(|| CliError::Unsupported {
                    command: path.clone(),
                    reason: "Flushing requires the native encrypted Task delivery journal.".into(),
                })?;
                Some(
                    super::task_queue::flush(
                        &mut service,
                        journal,
                        id()?,
                        invocation.boolean("as-assignee"),
                        &cancel,
                    )
                    .await?,
                )
            } else {
                None
            };
            let mut history = service
                .activity_history(
                    id()?,
                    TaskActivityQuery {
                        cursor: input::text(invocation, "cursor")?.map(str::to_owned),
                        limit: Some(number(invocation, "limit", 100, 200)?),
                        max_entries,
                        newest_first: invocation.boolean("newest-first"),
                        query,
                    },
                )
                .await?;
            if let Some(delivery) = delivery {
                history["delivery"] = delivery;
            }
            let entries = history["entries"]
                .as_array()
                .ok_or(CliError::Client(Error::Protocol))?;
            let mut text = if entries.is_empty() {
                "No Task activity found.".into()
            } else {
                entries
                    .iter()
                    .map(|entry| {
                        format!(
                            "{}  {}",
                            entry["entry_id"].as_str().unwrap_or("Activity"),
                            entry["message"].as_str().unwrap_or("")
                        )
                    })
                    .collect::<Vec<_>>()
                    .join("\n")
            };
            if history["truncated"] == true {
                text.push_str("\nActivity history truncated. Use tasks activity search to search the full history.");
            }
            if let Some(cursor) = history["next_cursor"].as_str() {
                text.push_str(&format!("\nNext cursor: {cursor}"));
            }
            result(invocation, history, text)
        }),
        "tasks activity add" => Box::pin(async move {
            input::check_flags(invocation, &["message", "as-assignee"])?;
            let message = input::text(invocation, "message")?
                .map(str::to_owned)
                .unwrap_or_else(|| invocation.positionals.get(1..).unwrap_or(&[]).join(" "));
            if message.trim().is_empty() {
                return Err(CliError::Invalid(
                    "Provide an Activity comment with --message or positional text.".into(),
                ));
            }
            let value = service
                .add_activity_comment(
                    id()?,
                    TaskActivityInput {
                        message,
                        ..Default::default()
                    },
                )
                .await?;
            let text = value["message"]
                .as_str()
                .unwrap_or("Activity saved.")
                .to_owned();
            result(invocation, json!({"entry":value}), text)
        }),
        "tasks activity delete" => Box::pin(async move {
            input::check_flags(invocation, &[])?;
            let entry = input::positional(invocation, 1, "Activity entry ID")?;
            let value = service.delete_activity_comment(id()?, entry).await?;
            result(
                invocation,
                json!({"entry":value}),
                "Task Activity deleted.".into(),
            )
        }),
        "tasks connect" => Box::pin(async move {
            input::check_flags(invocation, &["thread"])?;
            let thread = input::required(invocation, "thread")?;
            codex::assert_caller(thread)?;
            let connection = codex::read(thread, &cancel).await?;
            let task = service
                .connect(
                    id()?,
                    openmates_sdk::work::ExternalChat {
                        provider: "codex".into(),
                        id: connection.id,
                        title: connection.title,
                    },
                )
                .await?;
            task_result(invocation, task)
        }),
        "tasks connection" | "tasks resume" => Box::pin(async move {
            input::check_flags(invocation, &[])?;
            let task = service.show(id()?).await?;
            let thread = codex::connection_thread(&task)?;
            if path == "tasks resume" {
                return codex::resume(thread, &cancel).await;
            }
            let connection = codex::read(thread, &cancel).await?;
            let text = format!(
                "{}: Codex {} — {}",
                task["short_id"].as_str().unwrap_or("Task"),
                connection.status,
                connection.url
            );
            result(
                invocation,
                json!({"task_id":task["task_id"],"connection":connection}),
                text,
            )
        }),
        _ => Box::pin(async move {
            Err(CliError::Unsupported {
                command: path,
                reason: "This native Task operation is not ported.".into(),
            })
        }),
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn human_board_sorts_positions_without_changing_scripting_or_list_order() {
        let tasks = vec![
            json!({"task_id":"a","short_id":"TASK-1","title":"Later Task","status":"todo","position":200}),
            json!({"task_id":"z","short_id":"TASK-2","title":"Earlier Task","status":"todo","position":100}),
        ];
        let before = tasks.clone();
        let board = render_board(&tasks).ok().unwrap();
        assert!(
            board.find("TASK-2  Earlier Task").unwrap() < board.find("TASK-1  Later Task").unwrap()
        );
        assert!(board.contains("backlog\n"));
        assert!(board.contains("in progress\n"));
        assert_eq!(tasks, before);
        assert!(
            render_list(&tasks).find("TASK-1").unwrap()
                < render_list(&tasks).find("TASK-2").unwrap()
        );
        let invocation = Invocation {
            path: vec!["tasks".into(), "board".into()],
            positionals: vec![],
            flags: std::collections::BTreeMap::from([("json".into(), json!(true))]),
        };
        let output = result(
            &invocation,
            json!({"tasks":tasks.iter().map(task_json).collect::<Vec<_>>(),"complete":true}),
            String::new(),
        )
        .ok()
        .unwrap();
        let output: Value = serde_json::from_str(&output.stdout).unwrap();
        assert_eq!(output["tasks"][0]["task_id"], "a");
        assert_eq!(output["tasks"][1]["task_id"], "z");
        assert_eq!(output["tasks"][0]["position"], 200);
    }
    #[test]
    fn single_task_outputs_keep_legacy_envelope_and_canonical_empty_values() {
        let i = Invocation {
            path: vec!["tasks".into(), "show".into()],
            positionals: vec!["TASK-42".into()],
            flags: std::collections::BTreeMap::from([("json".into(), json!(true))]),
        };
        let output=task_result(&i,json!({"task_id":"canonical","short_id":"TASK-42","title":"Native","slug":"","blocked_reason":"","version":3,"history":{"extra":true}})).ok().unwrap();
        let value: Value = serde_json::from_str(&output.stdout).unwrap();
        assert_eq!(value["task"]["task_id"], "canonical");
        assert_eq!(value["task"]["version"], 3);
        assert!(value.get("task_id").is_none());
        assert!(value["task"]["slug"].is_null());
        assert!(value["task"]["blocked_reason"].is_null());
        assert!(value["task"].get("history").is_none());
    }
    #[test]
    fn task_ask_maps_instruction_and_scoped_defaults_without_inventing_a_saved_result() {
        let invocation = Invocation {
            path: vec!["tasks".into(), "ask".into()],
            positionals: vec![],
            flags: std::collections::BTreeMap::from([
                ("text".into(), json!("Prepare launch copy")),
                ("priority".into(), json!("high")),
                ("project".into(), json!("engineering")),
                ("label".into(), json!(["release", "writing"])),
            ]),
        };
        let (instruction, options) = ask_input(&invocation).ok().unwrap();
        assert_eq!(instruction, "Prepare launch copy");
        assert_eq!(options.create.priority, Some(3));
        assert_eq!(options.create.linked_project_ids, ["engineering"]);
        assert_eq!(options.create.labels, ["release", "writing"]);
        assert!(fallback(&json!({"outcome":"fallback_to_chat"})));
        assert!(!fallback(&json!({"outcome":"applied"})));
        assert!(
            ask_text(&json!({"summary":"Needs clarification"}), "task")
                .contains("Needs clarification")
        );
    }
}

#[cfg(test)]
mod workspace_fallback_tests {
    use super::*;
    #[test]
    fn fallback_forwards_each_workspace_consent_privacy_timeout_without_task_jobs() {
        for namespace in ["tasks", "plans", "projects", "workflows"] {
            let flags = std::collections::BTreeMap::from([
                ("json".into(), json!(true)),
                ("auto-approve".into(), json!(true)),
                ("auto-approve-memories".into(), json!(true)),
                ("no-pii-detection".into(), json!(true)),
                ("response-timeout-seconds".into(), json!("12")),
                ("description".into(), json!("do not forward")),
            ]);
            let original = Invocation {
                path: vec![namespace.into(), "ask".into()],
                positionals: vec![],
                flags,
            };
            let chat = workspace_fallback_invocation(&original, "original instruction".into());
            assert_eq!(chat.command_path(), "chats new");
            assert_eq!(chat.positionals, vec!["original instruction"]);
            for key in [
                "json",
                "auto-approve",
                "auto-approve-memories",
                "no-pii-detection",
                "response-timeout-seconds",
            ] {
                assert_eq!(chat.flags[key], original.flags[key]);
            }
            assert!(chat.boolean("no-task-update-jobs"));
            assert!(!chat.has("description"));
        }
    }
    #[test]
    fn ask_history_uses_legacy_precedence_and_synthesizes_undo_from_change_set() {
        assert_eq!(
            ask_text(
                &json!({"change_set_id":"change","undo_entry_commands":["part"]}),
                "workflow"
            ),
            "Applied workflow ask changes.\nChange set: change\nUndo all: openmates history undo change\nUndo part: part"
        );
        assert_eq!(
            ask_text(
                &json!({"summary":"Ready","history":{},"undo_all_command":"ignored","undo_entry_commands":["ignored"]}),
                "workflow"
            ),
            "Ready"
        );
    }
}

#[cfg(test)]
#[path = "tasks/workspace_fallback_protocol_tests.rs"]
mod workspace_fallback_protocol_tests;
