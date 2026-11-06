//! CLI adapter for durable Task actions (block/unblock/skip/start/reorder/
//! restore/project membership/dependencies/Activity delete): parses npm flags,
//! asks the shared core (`openmates_sdk::work::Tasks::prepare_*`) for the
//! encrypted intent, and renders the receipt with npm's JSON/text shape.
//! Mirrors npm `cli.ts handleTasks`; the journal lives in `task_queue.rs`.
use super::{CliError, Invocation, task_input as input};
use openmates_sdk::work::{
    DependencyTarget, RestoreState, TaskDelivery, TaskMove, TaskMutationKind, Tasks, WorkKind,
};
use serde_json::{Value, json};

/// Commands whose mutation is delivered through the encrypted journal here.
/// `tasks resume` is absent on purpose: it launches the local Codex thread and
/// performs no OpenMates backend mutation.
pub(super) const COMMANDS: [&str; 11] = [
    "tasks block",
    "tasks unblock",
    "tasks skip",
    "tasks start",
    "tasks reorder",
    "tasks restore",
    "tasks add-to-project",
    "tasks remove-from-project",
    "tasks dependencies add",
    "tasks dependencies remove",
    "tasks activity delete",
];

/// Whether `path` is prepared by [`prepare`].
pub(super) fn handles(path: &str) -> bool {
    COMMANDS.contains(&path)
}

/// `--reason-code` (or legacy `--reason`) plus optional `--reason-text`.
pub(super) fn block_args(invocation: &Invocation) -> Result<(&str, Option<&str>), CliError> {
    let reason = input::text(invocation, "reason-code")?
        .or(input::text(invocation, "reason")?)
        .ok_or_else(|| CliError::Invalid("Blocking a Task requires --reason-code.".into()))?;
    Ok((reason, input::text(invocation, "reason-text")?))
}
/// `--entry`/`--entry-id` and `--state before|after` (default before).
pub(super) fn restore_args(invocation: &Invocation) -> Result<(&str, RestoreState), CliError> {
    let entry = super::history::entry(invocation)?;
    let state = match input::text(invocation, "state")?.unwrap_or("before") {
        "before" => RestoreState::Before,
        "after" => RestoreState::After,
        _ => return Err(CliError::Invalid("--state must be before or after.".into())),
    };
    Ok((entry, state))
}
/// One reorder move from `--before`/`--after`/`--status`/`--position`.
pub(super) fn task_move(invocation: &Invocation) -> Result<TaskMove, CliError> {
    Ok(TaskMove {
        before_task_id: input::text(invocation, "before")?.map(str::to_owned),
        after_task_id: input::text(invocation, "after")?.map(str::to_owned),
        status: input::text(invocation, "status")?
            .map(input::status)
            .transpose()?,
        position: input::text(invocation, "position")?
            .map(|value| {
                value
                    .parse::<i64>()
                    .map_err(|_| CliError::Invalid("--position must be an integer.".into()))
            })
            .transpose()?,
    })
}
/// `--target task:<id>|plan:<id>` or the second positional.
pub(super) fn target(invocation: &Invocation) -> Result<DependencyTarget, CliError> {
    let invalid = || CliError::Invalid("Dependency target must be task:<id> or plan:<id>.".into());
    let value = input::text(invocation, "target")?
        .or(invocation.positionals.get(1).map(String::as_str))
        .ok_or_else(|| CliError::Invalid("Provide --target task:<id> or plan:<id>.".into()))?;
    let (kind, id) = value.split_once(':').ok_or_else(invalid)?;
    let kind = match kind {
        "task" => WorkKind::Task,
        "plan" => WorkKind::Plan,
        _ => return Err(invalid()),
    };
    if id.trim().is_empty() {
        return Err(CliError::Invalid("Dependency target is empty.".into()));
    }
    Ok(DependencyTarget {
        kind,
        id: id.into(),
    })
}

/// Build the encrypted durable intent for one action command.
pub(super) async fn prepare(
    invocation: &Invocation,
    service: &mut Tasks<'_>,
    delivery_id: &str,
) -> Result<TaskDelivery, CliError> {
    let path = invocation.command_path();
    let id = input::positional(invocation, 0, "Task ID")?;
    let result = match path.as_str() {
        "tasks block" => {
            input::check_flags(
                invocation,
                &["delivery-id", "reason-code", "reason", "reason-text"],
            )?;
            let (reason, text) = block_args(invocation)?;
            service.prepare_block(id, reason, text, delivery_id).await
        }
        "tasks unblock" | "tasks skip" => {
            input::check_flags(invocation, &["delivery-id"])?;
            let kind = if path == "tasks unblock" {
                TaskMutationKind::Unblock
            } else {
                TaskMutationKind::Skip
            };
            service.prepare_transition(id, kind, delivery_id).await
        }
        "tasks start" => {
            input::check_flags(invocation, &["delivery-id"])?;
            service.prepare_start(id, delivery_id).await
        }
        "tasks reorder" => {
            input::check_flags(invocation, &["delivery-id", "before", "after", "position"])?;
            service
                .prepare_reorder(id, task_move(invocation)?, delivery_id)
                .await
        }
        "tasks restore" => {
            input::check_flags(invocation, &["delivery-id", "entry", "entry-id", "state"])?;
            let (entry, state) = restore_args(invocation)?;
            service.prepare_restore(id, entry, state, delivery_id).await
        }
        "tasks add-to-project" | "tasks remove-from-project" => {
            input::check_flags(invocation, &["delivery-id"])?;
            let project = input::positional(invocation, 1, "Project ID")?;
            service
                .prepare_project_membership(
                    id,
                    project,
                    path == "tasks add-to-project",
                    delivery_id,
                )
                .await
        }
        "tasks dependencies add" | "tasks dependencies remove" => {
            input::check_flags(invocation, &["delivery-id", "target"])?;
            service
                .prepare_dependency(
                    id,
                    &target(invocation)?,
                    path == "tasks dependencies add",
                    delivery_id,
                )
                .await
        }
        "tasks activity delete" => {
            input::check_flags(invocation, &["delivery-id"])?;
            let entry = input::positional(invocation, 1, "Activity entry ID")?;
            service
                .prepare_activity_delete(id, entry, delivery_id)
                .await
        }
        _ => {
            return Err(CliError::Unsupported {
                command: path,
                reason: "This operation has no typed encrypted delivery preparation.".into(),
            });
        }
    };
    result.map_err(CliError::from)
}

/// npm output shape for receipts that are not a single Task. `Err` hands the
/// value back so the caller renders `{"task": …}` like other Task mutations.
pub(super) fn render(path: &str, value: Value) -> Result<(Value, String), Value> {
    Ok(match path {
        "tasks reorder" => (json!({"tasks":value}), "Task reordered.".into()),
        "tasks restore" => (value, "Task restored.".into()),
        "tasks dependencies add" | "tasks dependencies remove" => {
            (value, "Task dependency saved.".into())
        }
        "tasks activity delete" => (json!({"entry":value}), "Task Activity deleted.".into()),
        _ => return Err(value),
    })
}

#[cfg(test)]
#[path = "task_queue_actions_tests.rs"]
mod tests;
