//! The view-model actor's command handling: `Start` (credentials → cached
//! index → cached chat list → admission), the background boot sync, chat
//! list refresh, team switch and logout, plus routing of the chat window
//! commands (`window_flows.rs`) and of `Send`/`Cancel` (`send_flows.rs`).
//! Moved from the TUI `runtime.rs` actor
//! (`boot`, `boot_sync`, `Refresh`, `SwitchTeam`, `Logout`); spec
//! `a2-design.md` (View model) and `architecture.sync@2` (bounded start).
//!
//! Ordering invariants: the cached chat list is emitted before any network
//! request (only the shell's account check may precede it); every list read
//! is persisted before its `ChatList` event; a superseded request (cancelled
//! token or moved queue generation) publishes nothing.
use super::{
    ListCompleteness, SessionEvent, ViewCommand, ViewEvent,
    actor_host::{ListRecovery, ViewHost, ViewSink},
    send_flows, window_flows,
};
use crate::{
    error::{Error, Result},
    local_cache::ByteStore,
    model::Workspace,
    session::Session,
};
use futures_util::future::BoxFuture;
use tokio_util::sync::CancellationToken;

/// Handle one command; every command runs in the core. `Send` returns the
/// sent chat only through its events here (use [`send_flows::send`] for the
/// record); a queued `Cancel` cancels a running send, if any.
/// The background boot sync is not a command: the shell schedules
/// [`boot_sync`] after a successful `Start` when it is idle.
///
/// # Errors
/// The failed step's error; `Cancelled` for a superseded request.
pub fn handle<'a, S: ByteStore + 'static, H: ViewHost<S>>(
    host: &'a mut H,
    command: ViewCommand,
    sink: &'a H::Sink,
    cancel: &'a CancellationToken,
) -> BoxFuture<'a, Result<()>> {
    match command {
        ViewCommand::Start { credentials } => start(host, *credentials, sink, cancel),
        ViewCommand::RefreshChats => refresh_chats(host, sink, cancel),
        ViewCommand::SwitchTeam { team_id } => switch_team(host, team_id, sink, cancel),
        ViewCommand::Logout => logout(host, sink),
        ViewCommand::OpenChat { request, chat_id } => {
            window_flows::open_chat(host, request, chat_id, sink, cancel)
        }
        ViewCommand::LoadOlder { request, chat_id } => {
            window_flows::load_older(host, request, chat_id, sink, cancel)
        }
        ViewCommand::CloseChat { chat_id } => {
            Box::pin(async move { window_flows::close_chat(host, &chat_id) })
        }
        ViewCommand::MarkRead { chat_id } => window_flows::mark_read(host, chat_id, cancel),
        ViewCommand::Send {
            request,
            chat_id,
            text,
        } => Box::pin(async move {
            send_flows::send(host, request, chat_id, text, sink, cancel)
                .await
                .map(drop)
        }),
        ViewCommand::Cancel => Box::pin(async move {
            send_flows::cancel_send(host);
            Ok(())
        }),
        ViewCommand::SendUnownedFrame {
            event_type,
            payload_json,
        } => Box::pin(async move {
            let sender = host.core().unowned_frame_sender();
            sender
                .send(&event_type, &payload_json)
                .await
                .map_err(Error::from)
        }),
    }
}

fn superseded<S: ByteStore + 'static, H: ViewHost<S>>(
    host: &H,
    cancel: &CancellationToken,
    generation: &crate::local_cache::GenerationGuard,
) -> Result<()> {
    if cancel.is_cancelled() || !generation.is_current() || host.core().client().session().is_none()
    {
        return Err(Error::Cancelled);
    }
    Ok(())
}

/// Start with shell-loaded credentials: reset the client, let the shell
/// verify the account, restore only the cached index and emit
/// `Session(Restored)` plus `ChatList` (`Cached`) before any network request,
/// then load the remaining cached content (when eager) and admit the session.
///
/// # Errors
/// Profile, account-check, cache and admission errors. A failed restore
/// forgets the client's session, so nothing of it is persisted.
pub fn start<'a, S: ByteStore + 'static, H: ViewHost<S>>(
    host: &'a mut H,
    credentials: Session,
    sink: &'a H::Sink,
    cancel: &'a CancellationToken,
) -> BoxFuture<'a, Result<()>> {
    Box::pin(async move {
        let api = host.prepare_start(&credentials)?;
        host.core_mut().retire_window();
        host.core_mut()
            .client_mut()
            .reset(&api, Some(credentials.clone()))?;
        host.verify_start().await?;
        let core = host.core_mut();
        if core.restore_index(&credentials, cancel).await? {
            let display_name = core.client().display_name_hint();
            sink.emit(ViewEvent::Session(SessionEvent::Restored { display_name }))
                .await?;
            let items = core.client().cached_chat_items()?;
            let event = core.chat_list_event(items, ListCompleteness::Cached)?;
            sink.emit(event).await?;
            if core.eager_cached_content() {
                core.client_mut().ensure_cached_content_loaded()?;
            }
        }
        host.admit(sink).await
    })
}

/// The slow half of `Start`: global recovery (which may yield a complete
/// inventory), then the chat list, persisted before it is emitted. Shells run
/// it only while idle and cancel `cancel` to let a chat open or send go first;
/// a cancelled sync publishes nothing and can simply run again.
///
/// # Errors
/// Recovery, sync and persistence errors; `Cancelled` when superseded.
pub fn boot_sync<'a, S: ByteStore + 'static, H: ViewHost<S>>(
    host: &'a mut H,
    sink: &'a H::Sink,
    cancel: &'a CancellationToken,
) -> BoxFuture<'a, Result<()>> {
    Box::pin(async move {
        if host.core().client().session().is_none() {
            return Ok(());
        }
        let generation = host.core().shell().ops().guard();
        // Reuse only the same-batch complete inventory returned after actual
        // recovery admission and its durable save; no cache is promoted.
        let proof = host
            .recover_before_list(sink, ListRecovery::BootSync)
            .await?;
        superseded(host, cancel, &generation)?;
        let client = host.core_mut().client_mut();
        let (items, complete) = match proof {
            Some(proof) => {
                client
                    .list_with_fresh_chat_inventory_marked(Workspace::Chats, proof, cancel)
                    .await?
            }
            None => (client.list(Workspace::Chats).await?, false),
        };
        host.core_mut().persist().await?;
        superseded(host, cancel, &generation)?;
        let event = host
            .core()
            .chat_list_event(items, network_list_completeness(complete))?;
        sink.emit(event).await
    })
}

/// Re-read the chat list. With a sync-feed cursor and no pending recovery,
/// one feed catch-up over the cached index replaces recovery discovery and
/// the phased sync (`architecture.sync@2`); otherwise forced recovery runs
/// first and the full list follows.
///
/// # Errors
/// Recovery, sync and persistence errors.
pub fn refresh_chats<'a, S: ByteStore + 'static, H: ViewHost<S>>(
    host: &'a mut H,
    sink: &'a H::Sink,
    cancel: &'a CancellationToken,
) -> BoxFuture<'a, Result<()>> {
    Box::pin(async move {
        let client = host.core().client();
        let feed = client.has_chat_sync_cursor() && client.supports_cached_default_chat_list();
        if feed && host.recovery_idle().await {
            let client = host.core_mut().client_mut();
            client.set_operation_cancel(cancel.clone());
            if let Some(items) = client.chat_list_from_feed().await? {
                host.core_mut().persist().await?;
                return sink.emit(list_event(host, items)?).await;
            }
        }
        host.recover_before_list(sink, ListRecovery::Refresh)
            .await?;
        let items = host.core_mut().client_mut().list(Workspace::Chats).await?;
        host.core_mut().persist().await?;
        sink.emit(list_event(host, items)?).await
    })
}

/// Switch the active scope (`None`: personal), persist it, admit the session
/// in the new scope and publish its chat list. The open window and the live
/// monitor are retired first; the shell retires its own scope-bound state
/// (cached views, monitor lifetime) before calling.
///
/// # Errors
/// Scope, persistence, admission and sync errors.
pub fn switch_team<'a, S: ByteStore + 'static, H: ViewHost<S>>(
    host: &'a mut H,
    team_id: Option<String>,
    sink: &'a H::Sink,
    _cancel: &'a CancellationToken,
) -> BoxFuture<'a, Result<()>> {
    Box::pin(async move {
        // Scope-bound state: the old scope's window and monitor never see
        // data of the new scope.
        host.core_mut().retire_window();
        host.core_mut().set_chat_monitor(None);
        host.core_mut().client_mut().set_team(team_id.as_deref())?;
        host.core_mut().persist().await?;
        host.admit(sink).await?;
        let items = host.core_mut().client_mut().list(Workspace::Chats).await?;
        host.core_mut().persist().await?;
        sink.emit(list_event(host, items)?).await
    })
}

/// Sign out: durable local revocation and cleanup concurrently with remote
/// logout, then `Session(SignedOut)`. The event is sent even when cleanup or
/// remote logout failed; the local error wins over the remote one.
///
/// # Errors
/// The sink's error first, then the local, then the remote error.
pub fn logout<'a, S: ByteStore + 'static, H: ViewHost<S>>(
    host: &'a mut H,
    sink: &'a H::Sink,
) -> BoxFuture<'a, Result<()>> {
    Box::pin(async move {
        host.core_mut().retire_window();
        host.core_mut().set_chat_monitor(None);
        let result = host.core_mut().logout().await;
        sink.emit(ViewEvent::Session(SessionEvent::SignedOut))
            .await?;
        result
    })
}

/// Completeness of a network-read list: `Complete` only when the rows are the
/// whole inventory of the scope, proven by a current recovery inventory.
pub(super) fn network_list_completeness(inventory_proven: bool) -> ListCompleteness {
    if inventory_proven {
        ListCompleteness::Complete
    } else {
        ListCompleteness::Partial
    }
}

/// `items` as a network-read chat list. `Partial`: the core cannot yet tell
/// a phased or feed read from the offline fallback inside `list`, so it never
/// claims `Complete`.
fn list_event<S: ByteStore + 'static, H: ViewHost<S>>(
    host: &H,
    items: Vec<crate::model::Item>,
) -> Result<ViewEvent> {
    host.core()
        .chat_list_event(items, ListCompleteness::Partial)
}
