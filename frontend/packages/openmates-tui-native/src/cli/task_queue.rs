//! Task mutation delivery: prepare once, durably publish exact ciphertext,
//! mark uncertainty before dispatch, reconcile that same intent after restart.
use super::{CliError, Invocation, codex, task_input as input};
use crate::{error::Error, task_delivery::Journal};
use openmates_sdk::work::{
    ExternalChat, TaskActivityInput, TaskCaller, TaskDelivery, TaskMutationKind, Tasks,
};
use rand::RngCore;
use serde_json::{Value, json};
use tokio_util::sync::CancellationToken;
pub(super) fn supported(invocation: &Invocation) -> bool {
    matches!(
        invocation.command_path().as_str(),
        "tasks create"
            | "tasks edit"
            | "tasks done"
            | "tasks delete"
            | "tasks connect"
            | "tasks release"
            | "tasks activity add"
            | "tasks activity flush"
    )
}
pub(crate) fn retryable(error: &CliError) -> bool {
    matches!(
        error,
        CliError::PendingTask {
            source: Error::Offline | Error::Io | Error::Protocol,
            ..
        }
    )
}
pub(super) fn pending_output(
    invocation: &Invocation,
    error: CliError,
) -> Result<super::CliOutput, CliError> {
    if !retryable(&error) {
        return Err(error);
    }
    if let CliError::PendingTask {
        delivery_id,
        task_id,
        retry_at,
        persistent,
        ..
    } = error
    {
        if invocation.boolean("json") {
            let mut value = json!({"delivery":{"status":"pending","delivery_id":delivery_id,"task_id":task_id,"persistent":persistent}});
            if let Some(retry_at) = retry_at {
                value["delivery"]["retry_at"] = json!(retry_at);
            }
            super::CliOutput::json(&value)
        } else {
            Ok(super::CliOutput::text(format!(
                "{}\nTask ID: {task_id}\nDelivery ID: {delivery_id}",
                if persistent {
                    "Task sync remains unavailable; the queued update is retained."
                } else {
                    "Task update queued; the original encrypted operation is retained."
                }
            )))
        }
    } else {
        Err(error)
    }
}
fn pending(delivery: &TaskDelivery, source: Error) -> CliError {
    CliError::PendingTask {
        delivery_id: delivery.delivery_id.clone(),
        task_id: delivery.task_id.clone(),
        source,
        retry_at: None,
        persistent: false,
    }
}
async fn dispatch(
    service: &mut Tasks<'_>,
    journal: &Journal,
    id: &str,
    intent: &str,
    cancel: &CancellationToken,
) -> Result<Value, CliError> {
    dispatch_with(journal,id,intent,cancel,move |delivery,uncertain| async move {service.execute_delivery(&delivery,uncertain).await}).await
}
async fn dispatch_with<F, Fut>(
    journal: &Journal,
    id: &str,
    intent: &str,
    cancel: &CancellationToken,
    send: F,
) -> Result<Value, CliError>
where
    F: FnOnce(TaskDelivery, bool) -> Fut,
    Fut: std::future::Future<Output = Result<Value, Error>>,
{
    let dispatch = journal.begin(id, intent).await?;
    complete_dispatch(journal, id, intent, cancel, dispatch, send).await
}
async fn complete_dispatch<F, Fut>(
    journal: &Journal,
    id: &str,
    intent: &str,
    cancel: &CancellationToken,
    dispatch: crate::task_delivery::Dispatch,
    send: F,
) -> Result<Value, CliError>
where
    F: FnOnce(TaskDelivery, bool) -> Fut,
    Fut: std::future::Future<Output = Result<Value, Error>>,
{
    if let Some(value) = dispatch_preflight(&dispatch, cancel)? {
        return Ok(value);
    }
    let result = send(dispatch.delivery.clone(), dispatch.uncertain).await;
    complete_transport(journal, id, intent, &dispatch.delivery, result).await
}
fn dispatch_preflight(
    dispatch: &crate::task_delivery::Dispatch,
    cancel: &CancellationToken,
) -> Result<Option<Value>, CliError> {
    if let Some(value) = &dispatch.completed {
        return Ok(Some(value.clone()));
    }
    if let Some(retry) = &dispatch.deferred {
        let mut error = pending(&dispatch.delivery, Error::Offline);
        if let CliError::PendingTask {
            retry_at,
            persistent,
            ..
        } = &mut error
        {
            *retry_at = Some(retry.retry_at);
            *persistent = retry.persistent;
        }
        return Err(error);
    }
    if cancel.is_cancelled() {
        return Err(pending(&dispatch.delivery, Error::Cancelled));
    }
    Ok(None)
}
async fn complete_transport(
    journal: &Journal,
    id: &str,
    intent: &str,
    delivery: &TaskDelivery,
    result: Result<Value, Error>,
) -> Result<Value, CliError> {
    let value = match result {
        Ok(value) => value,
        Err(source) => {
            let mut error = pending(delivery, source);
            if retryable(&error) {
                let retry = journal
                    .defer(id, intent)
                    .await
                    .map_err(|source| pending(delivery, source))?;
                if let CliError::PendingTask {
                    retry_at,
                    persistent,
                    ..
                } = &mut error
                {
                    *retry_at = Some(retry.retry_at);
                    *persistent = retry.persistent;
                }
            }
            return Err(error);
        }
    };
    journal
        .acknowledge(id, intent, value.clone())
        .await
        .map_err(|error| pending(delivery, error))?;
    Ok(value)
}
pub(super) async fn flush(
    service: &mut Tasks<'_>,
    journal: &Journal,
    selector: &str,
    as_assignee: bool,
    cancel: &CancellationToken,
) -> Result<Value, CliError> {
    let task = service.show(selector).await?;
    let task_id = task["task_id"]
        .as_str()
        .ok_or(CliError::Client(Error::Protocol))?;
    let rows = journal
        .pending()
        .await?
        .into_iter()
        .filter(|row| {
            row.delivery.kind == TaskMutationKind::Activity
                && row.delivery.task_id == task_id
                && row.delivery.actor_assignee == as_assignee
        })
        .collect::<Vec<_>>();
    let mut remaining = rows.len();
    let mut delivered = 0usize;
    let mut attempted = 0usize;
    for row in rows {
        if attempted >= 3 {
            break;
        }
        attempted += 1;
        match dispatch(
            service,
            journal,
            &row.delivery.delivery_id,
            &row.intent,
            cancel,
        )
        .await
        {
            Ok(_) => {
                delivered += 1;
                remaining -= 1;
            }
            Err(error) if retryable(&error) => break,
            Err(error) => return Err(error),
        }
    }
    Ok(json!({"delivered":delivered,"pending":remaining,"attempted":attempted,"rejected":0}))
}
pub(super) async fn deliver(
    invocation: &Invocation,
    service: &mut Tasks<'_>,
    journal: &Journal,
    cancel: &CancellationToken,
    caller: &TaskCaller,
) -> Result<Value, CliError> {
    if invocation.command_path() == "tasks activity flush" {
        input::check_flags(invocation, &["as-assignee"])?;
        return flush(
            service,
            journal,
            input::positional(invocation, 0, "Task ID")?,
            invocation.boolean("as-assignee"),
            cancel,
        )
        .await;
    }
    let delivery_id = match input::text(invocation, "delivery-id")? {
        Some(id) => id.to_owned(),
        None => {
            let mut bytes = [0u8; 32];
            rand::thread_rng().fill_bytes(&mut bytes);
            bytes.iter().map(|byte| format!("{byte:02x}")).collect()
        }
    };
    if delivery_id.len() != 64
        || !delivery_id
            .bytes()
            .all(|byte| byte.is_ascii_digit() || (b'a'..=b'f').contains(&byte))
    {
        return Err(CliError::Invalid(
            "Task delivery ID must contain 64 lowercase hexadecimal characters.".into(),
        ));
    }
    let intent = journal.intent(invocation)?;
    if journal.lookup(&delivery_id, &intent).await?.is_none() {
        let delivery = prepare(invocation, service, &delivery_id, cancel).await?;
        journal
            .insert_for_caller(delivery, intent.clone(), caller)
            .await?;
    }
    // stderr carries a recoverable operation identity even if an outer runtime
    // deadline interrupts the waiting process after durable dispatch admission.
    {
        use std::io::Write;
        let mut stderr = std::io::stderr();
        let _ = writeln!(stderr, "Task delivery: {delivery_id}").and_then(|()| stderr.flush());
    }
    dispatch(service, journal, &delivery_id, &intent, cancel).await
}
async fn prepare(
    invocation: &Invocation,
    service: &mut Tasks<'_>,
    delivery_id: &str,
    cancel: &CancellationToken,
) -> Result<TaskDelivery, CliError> {
    let id = || input::positional(invocation, 0, "Task ID");
    let result = match invocation.command_path().as_str() {
        "tasks create" => {
            input::check_flags(
                invocation,
                &[
                    "delivery-id",
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
            super::tasks::verify_external(&mut payload.external_chat, cancel).await?;
            service.prepare_create(payload, delivery_id).await
        }
        "tasks edit" => {
            input::check_flags(
                invocation,
                &[
                    "delivery-id",
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
                super::tasks::verify_external(external, cancel).await?;
            }
            service.prepare_update(id()?, payload, delivery_id).await
        }
        "tasks done" => {
            input::check_flags(invocation, &["delivery-id"])?;
            service.prepare_complete(id()?, delivery_id).await
        }
        "tasks delete" => {
            input::check_flags(invocation, &["delivery-id", "confirm"])?;
            if !invocation.boolean("confirm") {
                return Err(CliError::Invalid(
                    "Deleting a Task requires --confirm.".into(),
                ));
            }
            service.prepare_delete(id()?, delivery_id, true).await
        }
        "tasks activity add" => {
            input::check_flags(invocation, &["delivery-id", "message", "as-assignee"])?;
            let message = input::text(invocation, "message")?
                .map(str::to_owned)
                .unwrap_or_else(|| invocation.positionals.get(1..).unwrap_or(&[]).join(" "));
            if message.trim().is_empty() {
                return Err(CliError::Invalid(
                    "Provide an Activity comment with --message or positional text.".into(),
                ));
            }
            service
                .prepare_activity(
                    id()?,
                    TaskActivityInput {
                        message,
                        entry_id: Some(delivery_id.into()),
                        ..Default::default()
                    },
                    delivery_id,
                )
                .await
        }
        "tasks connect" => {
            input::check_flags(invocation, &["delivery-id", "thread"])?;
            let thread = input::required(invocation, "thread")?;
            codex::assert_caller(thread)?;
            let connection = codex::read(thread, cancel).await?;
            service
                .prepare_connect(
                    id()?,
                    ExternalChat {
                        provider: "codex".into(),
                        id: connection.id,
                        title: connection.title,
                    },
                    delivery_id,
                )
                .await
        }
        "tasks release" => {
            input::check_flags(invocation, &["delivery-id"])?;
            super::codex::guard_release(service, id()?).await?;
            service.prepare_release(id()?, delivery_id).await
        }
        _ => {
            return Err(CliError::Unsupported {
                command: invocation.command_path(),
                reason: "This operation has no typed encrypted delivery preparation.".into(),
            });
        }
    };
    result.map_err(CliError::from)
}

/// Prepared outside the Client lane; only the exact original durable intent.
pub(crate) struct PreparedReplay {
    id: String,
    intent: String,
    dispatch: crate::task_delivery::Dispatch,
    caller: TaskCaller,
}
/// Journal selection/admission may fsync. Never borrow Client for this stage.
pub(crate) async fn prepare_replay(
    journal: &Journal,
    cancel: &CancellationToken,
) -> Result<Option<PreparedReplay>, CliError> {
    if cancel.is_cancelled() {
        return Err(Error::Cancelled.into());
    }
    let queue = journal.pending_replay().await?;
    if !queue.quarantined.is_empty() {
        return Err(Error::Unavailable {
            code: "task_delivery_replay_quarantined",
            reason: "ORIGINAL_CALLER_OR_FIFO_ORDER_UNVERIFIED",
        }
        .into());
    }
    let Some(row) = queue.ordered.first() else {
        return Ok(None);
    };
    let dispatch = journal
        .begin_replay(&row.delivery.delivery_id, &row.intent)
        .await?;
    if dispatch_preflight(&dispatch, cancel)?.is_some() {
        return Ok(None);
    }
    let caller = dispatch
        .replay
        .as_ref()
        .ok_or(Error::Protocol)?
        .task_caller()?;
    Ok(Some(PreparedReplay {
        id: row.delivery.delivery_id.clone(),
        intent: row.intent.clone(),
        dispatch,
        caller,
    }))
}
/// Only context/lease recheck and actual SDK transport borrow Client.
pub(crate) async fn send_replay(
    client: &mut crate::client::Client,
    context: &crate::task_delivery::CookieJournalContext,
    prepared: &PreparedReplay,
    cancel: &CancellationToken,
) -> Result<Value, Error> {
    context.check(client)?;
    if cancel.is_cancelled() {
        return Err(Error::Cancelled);
    }
    client.set_operation_cancel(cancel.clone());
    client
        .tasks()
        .with_filters(context.task_filters())
        .with_caller(prepared.caller.clone())
        .execute_delivery(&prepared.dispatch.delivery, prepared.dispatch.uncertain)
        .await
}
/// Ack/backoff descriptor transactions run only after dropping Client guard.
pub(crate) async fn finish_replay(
    journal: &Journal,
    prepared: PreparedReplay,
    result: Result<Value, Error>,
) -> Result<(), CliError> {
    complete_transport(
        journal,
        &prepared.id,
        &prepared.intent,
        &prepared.dispatch.delivery,
        result,
    )
    .await?;
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::runtime_store::RuntimeStore;
    use zeroize::Zeroizing;
    fn directory() -> tempfile::TempDir {
        let mut builder = tempfile::Builder::new();
        #[cfg(unix)]
        {
            use std::os::unix::fs::PermissionsExt;
            builder.permissions(std::fs::Permissions::from_mode(0o700));
        }
        builder.tempdir().unwrap()
    }
    fn delivery() -> TaskDelivery {
        TaskDelivery {
            protocol_version: 1,
            delivery_id: "a".repeat(64),
            task_id: "00000000-0000-4000-8000-000000000001".into(),
            team_id: None,
            scope: "synthetic scope".into(),
            kind: TaskMutationKind::Create,
            input: json!({"encrypted_title":"stable original ciphertext","version":1}),
            expected_owner_hash: None,
            creator: false,
            actor_assignee: false,
        }
    }
    #[tokio::test]
    async fn lost_ack_reuses_ciphertext_after_uncertainty_and_cached_success_never_dispatches() {
        let directory = directory();
        let store = RuntimeStore::new(Some(directory.path().to_path_buf()), true)
            .await
            .unwrap();
        let journal = Journal::new(
            store,
            "owner".into(),
            "context".into(),
            Zeroizing::new([42; 32]),
        );
        let payload = delivery();
        let id = payload.delivery_id.clone();
        let intent = "logical intent";
        journal
            .insert(payload.clone(), intent.into())
            .await
            .unwrap();
        let cancel = CancellationToken::new();
        let expected = &payload;
        let journal_ref = &journal;
        let id_ref = &id;
        let error = dispatch_with(
            &journal,
            &id,
            intent,
            &cancel,
            move |actual, uncertain| async move {
                assert!(!uncertain);
                assert_eq!(actual.input, expected.input);
                assert!(journal_ref.begin(id_ref, intent).await.unwrap().uncertain);
                Err(Error::Offline)
            },
        )
        .await
        .err()
        .unwrap();
        assert_eq!(error.code(), "task_delivery_pending");
        assert_eq!(error.structured_error()["error"]["delivery_id"], id);
        let retry_at = match error {
            CliError::PendingTask {
                retry_at: Some(retry_at),
                ..
            } => retry_at,
            _ => panic!("Retry metadata must be persisted"),
        };
        let deferred = dispatch_with(&journal, &id, intent, &cancel, |_, _| async {
            panic!("Backoff must defer transport")
        })
        .await
        .err()
        .unwrap();
        assert!(retryable(&deferred));
        let now = std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .unwrap()
            .as_millis() as u64;
        tokio::time::sleep(std::time::Duration::from_millis(
            retry_at.saturating_sub(now) + 1,
        ))
        .await;
        let receipt = json!({"task_id":payload.task_id,"title":"decrypted receipt"});
        let receipt_ref = &receipt;
        let actual = dispatch_with(
            &journal,
            &id,
            intent,
            &cancel,
            move |actual, uncertain| async move {
                assert!(uncertain);
                assert_eq!(actual.input, expected.input);
                Ok(receipt_ref.clone())
            },
        )
        .await
        .ok()
        .unwrap();
        assert_eq!(actual, receipt);
        let cached = dispatch_with(&journal, &id, intent, &cancel, |_, _| async {
            panic!("A cached acknowledgement must not perform transport")
        })
        .await
        .ok()
        .unwrap();
        assert_eq!(cached, receipt);
    }
    #[test]
    fn queued_outcomes_preserve_legacy_stdout_and_terminal_rejections_stay_errors() {
        let invocation = Invocation {
            path: vec!["tasks".into(), "create".into()],
            positionals: vec![],
            flags: std::collections::BTreeMap::from([("json".into(), Value::Bool(true))]),
        };
        for source in [Error::Offline, Error::Io, Error::Protocol] {
            let mut error = pending(&delivery(), source);
            if let CliError::PendingTask {
                retry_at,
                persistent,
                ..
            } = &mut error
            {
                *retry_at = Some(123456);
                *persistent = true;
            }
            let output = pending_output(&invocation, error).ok().unwrap();
            assert_eq!(output.exit_code, 0);
            let value: Value = serde_json::from_str(&output.stdout).unwrap();
            assert_eq!(value["delivery"]["status"], "pending");
            assert_eq!(value["delivery"]["retry_at"], 123456);
            assert_eq!(value["delivery"]["persistent"], true);
            assert!(value.get("task").is_none());
        }
        for source in [
            Error::Invalid("Rejected"),
            Error::Forbidden,
            Error::Conflict,
            Error::Crypto,
            Error::Cancelled,
        ] {
            let error = pending_output(&invocation, pending(&delivery(), source))
                .err()
                .unwrap();
            assert_ne!(error.exit_code(), 0);
            let expected = match source {
                Error::Invalid(_) => "invalid_argument",
                Error::Forbidden => "forbidden",
                Error::Conflict => "task_delivery_conflict",
                Error::Crypto => "decryption_failed",
                Error::Cancelled => "cancelled",
                _ => unreachable!(),
            };
            let structured = error.structured_error();
            assert_eq!(structured["error"]["code"], expected);
            assert!(structured["error"]["delivery_id"].is_string());
            assert!(structured["error"]["task_id"].is_string());
            if source == Error::Cancelled {
                assert_eq!(error.exit_code(), 130);
            }
        }
    }
}

#[cfg(test)]
mod foreground_replay_tests {
    use super::*;
    use crate::runtime_store::RuntimeStore;
    use zeroize::Zeroizing;

    // contract-test: supporting surface=cli assertions=projects.remote-access.task-sync
    #[tokio::test]
    async fn foreground_dispatch_preserves_original_caller_fifo_uncertainty_and_backoff() {
        let mut builder = tempfile::Builder::new();
        #[cfg(unix)]
        {
            use std::os::unix::fs::PermissionsExt;
            builder.permissions(std::fs::Permissions::from_mode(0o700));
        }
        let root = builder.tempdir().unwrap();
        let store = RuntimeStore::new(Some(root.path().to_owned()), true)
            .await
            .unwrap();
        let journal = Journal::new(
            store,
            "owner".into(),
            "context".into(),
            Zeroizing::new([42; 32]),
        );
        let make = |id: &str| TaskDelivery {
            protocol_version: 1,
            delivery_id: id.repeat(64),
            task_id: "00000000-0000-4000-8000-000000000001".into(),
            team_id: None,
            scope: "original caller scope".into(),
            kind: TaskMutationKind::Update,
            input: json!({"encrypted_title":"original ciphertext","version":1}),
            expected_owner_hash: Some("original owner".into()),
            creator: false,
            actor_assignee: false,
        };
        let caller = TaskCaller {
            codex_thread_id: Some("00000000-0000-4000-8000-000000000002".into()),
            as_assignee: false,
        };
        let first = make("a");
        let second = make("b");
        journal
            .insert_for_caller(first.clone(), "first".into(), &caller)
            .await
            .unwrap();
        journal
            .insert_for_caller(second.clone(), "second".into(), &TaskCaller::default())
            .await
            .unwrap();
        assert!(
            journal
                .begin_replay(&second.delivery_id, "second")
                .await
                .is_err()
        );
        let admission = journal
            .begin_replay(&first.delivery_id, "first")
            .await
            .unwrap();
        assert_eq!(
            admission
                .replay
                .as_ref()
                .unwrap()
                .task_caller()
                .unwrap()
                .codex_thread_id,
            caller.codex_thread_id
        );
        let original = first.input.clone();
        let error = complete_dispatch(
            &journal,
            &first.delivery_id,
            "first",
            &CancellationToken::new(),
            admission,
            move |delivery, uncertain| async move {
                assert!(!uncertain);
                assert_eq!(delivery.input, original);
                assert_eq!(
                    delivery.expected_owner_hash.as_deref(),
                    Some("original owner")
                );
                Err(Error::Offline)
            },
        )
        .await
        .err()
        .unwrap();
        assert!(retryable(&error));
        let repeat = journal
            .begin_replay(&first.delivery_id, "first")
            .await
            .unwrap();
        assert!(repeat.uncertain);
        assert!(repeat.deferred.is_some());
        let error = complete_dispatch(
            &journal,
            &first.delivery_id,
            "first",
            &CancellationToken::new(),
            repeat,
            |_, _| async { panic!("durable context cooldown must prevent transport") },
        )
        .await
        .err()
        .unwrap();
        assert!(retryable(&error));
        let queue = journal.pending_replay().await.unwrap();
        assert_eq!(queue.ordered[0].delivery.delivery_id, first.delivery_id);
        assert_eq!(queue.ordered[1].delivery.delivery_id, second.delivery_id);
    }
    // contract-test: supporting surface=cli assertions=projects.remote-access.task-sync
    #[tokio::test]
    async fn split_replay_journal_stages_retain_exact_head_on_mutation_403_without_client() {
        let mut builder = tempfile::Builder::new();
        #[cfg(unix)]
        {
            use std::os::unix::fs::PermissionsExt;
            builder.permissions(std::fs::Permissions::from_mode(0o700));
        }
        let root = builder.tempdir().unwrap();
        let store = RuntimeStore::new(Some(root.path().to_owned()), true)
            .await
            .unwrap();
        let journal = Journal::new(
            store,
            "owner".into(),
            "context".into(),
            Zeroizing::new([42; 32]),
        );
        let delivery = TaskDelivery {
            protocol_version: 1,
            delivery_id: "c".repeat(64),
            task_id: "00000000-0000-4000-8000-000000000001".into(),
            team_id: None,
            scope: "original caller scope".into(),
            kind: TaskMutationKind::Update,
            input: json!({"encrypted_title":"exact immutable ciphertext","version":1}),
            expected_owner_hash: Some("original owner".into()),
            creator: false,
            actor_assignee: false,
        };
        let caller = TaskCaller {
            codex_thread_id: Some("00000000-0000-4000-8000-000000000002".into()),
            as_assignee: false,
        };
        journal
            .insert_for_caller(delivery.clone(), "exact intent".into(), &caller)
            .await
            .unwrap();
        let cancel = CancellationToken::new();
        let prepared = prepare_replay(&journal, &cancel)
            .await
            .ok()
            .unwrap()
            .unwrap();
        assert_eq!(prepared.caller.codex_thread_id, caller.codex_thread_id);
        assert_eq!(prepared.dispatch.delivery.input, delivery.input);
        let error = finish_replay(&journal, prepared, Err(Error::Forbidden))
            .await
            .err()
            .unwrap();
        assert!(matches!(
            error,
            CliError::PendingTask {
                source: Error::Forbidden,
                ..
            }
        ));
        let prepared = prepare_replay(&journal, &cancel)
            .await
            .ok()
            .unwrap()
            .unwrap();
        assert!(prepared.dispatch.uncertain);
        assert_eq!(prepared.dispatch.delivery.input, delivery.input);
        finish_replay(&journal, prepared, Ok(json!({"task_id":delivery.task_id})))
            .await
            .ok()
            .unwrap();
        assert!(journal.pending_replay().await.unwrap().ordered.is_empty());
    }
}
