//! The view-model actor's chat window commands: `OpenChat` (cached first page
//! before any network, scoped recovery and fenced reads), `LoadOlder`,
//! `CloseChat` and `MarkRead`. Moved from the TUI `runtime.rs` (`open_chat`,
//! `mark_read`); spec `a2-design.md` (View model, lane L7) and
//! `feature.chat-unread@1` (read receipts).
//!
//! Ordering invariant of `OpenChat`: the cached window (when one can be shown)
//! is emitted before any network request. A cold window can show an
//! authenticated preview before recovery, with final settlement after it.
use super::{
    ChatWindowSource, RequestId, ViewEvent,
    actor_host::{ViewHost, ViewSink},
};
use crate::{
    error::{Error, Result},
    local_cache::ByteStore,
};
use futures_util::future::BoxFuture;
use tokio_util::sync::CancellationToken;

/// Open `chat_id` as the window of `request`: emit the cached window when
/// one exists, run the host's selected-chat recovery, and settle the strict
/// window. A cold chat can publish an authenticated read-only preview before
/// recovery when the host supports it.
/// Replaces any other open window. A transient failure can retain a page
/// already shown. An authentication or access denial retires the window.
///
/// # Errors
/// `Invalid` for a malformed or volatile chat id; recovery, read and
/// persistence errors; `Cancelled` when superseded.
pub fn open_chat<'a, S: ByteStore + 'static, H: ViewHost<S>>(
    host: &'a mut H,
    request: RequestId,
    chat_id: String,
    sink: &'a H::Sink,
    cancel: &'a CancellationToken,
) -> BoxFuture<'a, Result<()>> {
    Box::pin(async move {
        uuid::Uuid::parse_str(&chat_id)
            .map_err(|_| Error::Invalid("A full chat ID is required."))?;
        if host.core().client().is_ephemeral_chat(&chat_id) {
            return Err(Error::Invalid(
                "Volatile chats have no saved recovery history.",
            ));
        }
        if host.core().recently_opened_enabled {
            host.core_mut().explicit_startup_navigation = true;
        }
        host.core_mut().begin_window(request, &chat_id);
        let result = open_window(host, request, &chat_id, sink, cancel).await;
        if result.is_err()
            && (matches!(result, Err(Error::Expired | Error::Authentication | Error::Forbidden))
                || host.core().client().session().is_none()
                || host.core().open_window().is_none())
        {
            host.core_mut().close_chat(&chat_id);
        }
        result
    })
}

async fn open_window<S: ByteStore + 'static, H: ViewHost<S>>(
    host: &mut H,
    request: RequestId,
    chat_id: &str,
    sink: &H::Sink,
    cancel: &CancellationToken,
) -> Result<()> {
    let core = host.core_mut();
    core.begin_client_operation(cancel);
    let cached = core
        .cached_window(chat_id, cancel)
        .await?
        .and_then(|record| core.publish_window(request, record));
    let has_cached_window = cached.is_some();
    if let Some(event) = cached {
        sink.emit(event).await?;
    }
    let record = if has_cached_window || !host.read_cold_window_before_recovery() {
        host.recover_before_open(sink, chat_id).await?;
        let offline_allowed = host.offline_cache_allowed();
        host.core_mut().read_window(request, chat_id, sink, cancel, offline_allowed).await?
    } else {
        let mut record = host.core_mut().read_window(request, chat_id, sink, cancel, false).await?;
        // For longer chats, read_window already emitted the admitted first
        // page. Short chats settle in one round, so derive a read-only preview
        // from that exact authenticated and durable record before recovery.
        if host.core().open_window().is_none() && !record.messages.is_empty() {
            let mut preview = record.clone();
            preview.source = ChatWindowSource::FirstPage;
            preview.refreshing = true;
            let event = host.core_mut().publish_window(request, preview).ok_or(Error::Cancelled)?;
            sink.emit(event).await?;
        }
        if host.recover_after_cold_open(sink, chat_id).await? {
            // Recovery may have written canonical data, or observed a denial
            // before its own operation was interrupted. Do not fall back to
            // an offline grant when reading the window again.
            record = host.core_mut().read_window(request, chat_id, sink, cancel, false).await?;
        }
        record
    };
    if cancel.is_cancelled() {
        return Err(Error::Cancelled);
    }
    let core = host.core_mut();
    let event = core
        .publish_window(request, record)
        .ok_or(Error::Cancelled)?;
    sink.emit(event).await?;
    if host.core().recently_opened_enabled {
        let evict = host.recovery_idle().await;
        let core = host.core_mut();
        if cancel.is_cancelled() || core.open_chat_id() != Some(chat_id) {
            return Err(Error::Cancelled);
        }
        core.client_mut().remember_user_chat_open(chat_id)?;
        core.client_mut().retain_opened_history(chat_id, evict);
        core.persist().await?;
        match core.client_mut().submit_user_chat_open(chat_id).await {
            Ok(recorded) => {
                core.persist().await?;
                if recorded && !cancel.is_cancelled() {
                    crate::startup_diagnostics::StartupPhase::OpenedRecorded.record(&Ok(()));
                }
            }
            Err(Error::Offline) => {},
            Err(error) => return Err(error),
        }
    }
    // embed-user-edits.event.project-edit-reaches-chat: after the window is
    // shown, write the chat events of edits made elsewhere (deferred offline).
    host.core_mut()
        .client_mut()
        .reconcile_embed_update_notices_on_open(chat_id)
        .await
        .map(drop)
}

/// Refresh a specific already-open chat on an external notification. This
/// cannot select a different chat or record user activity.
///
/// # Errors
/// Authorization, cancellation, storage or exact chat read errors.
pub fn refresh_open_chat<'a, S: ByteStore + 'static, H: ViewHost<S>>(
    host: &'a mut H,
    request: RequestId,
    chat_id: String,
    sink: &'a H::Sink,
    cancel: &'a CancellationToken,
) -> BoxFuture<'a, Result<()>> {
    Box::pin(async move {
        let offline_allowed = host.offline_cache_allowed();
        let core = host.core_mut();
        if core.open_chat_id() != Some(chat_id.as_str()) || cancel.is_cancelled() {
            return Err(Error::Cancelled);
        }
        core.begin_client_operation(cancel);
        core.begin_window(request, &chat_id);
        match core.read_window_policy(request, &chat_id, sink, cancel, offline_allowed, false, None).await {
            Ok(window) if !cancel.is_cancelled() => {
                sink.emit(core.publish_window(request, window).ok_or(Error::Cancelled)?).await
            }
            Err(Error::Forbidden) => {
                core.close_chat(&chat_id);
                sink.emit(ViewEvent::ChatUnavailable { chat_id }).await
            }
            Ok(_) => Err(Error::Cancelled),
            Err(error) => Err(error),
        }
    })
}

/// Merge the next older page into the open window of `chat_id` and emit it
/// for `request` (unchanged and without network when the history is
/// already complete).
///
/// # Errors
/// As `ViewCore::older_page`: `Invalid` when the chat is not open.
pub fn load_older<'a, S: ByteStore + 'static, H: ViewHost<S>>(
    host: &'a mut H,
    request: RequestId,
    chat_id: String,
    sink: &'a H::Sink,
    cancel: &'a CancellationToken,
) -> BoxFuture<'a, Result<()>> {
    Box::pin(async move {
        let window = host.core_mut().older_page(&chat_id, cancel).await?;
        sink.emit(ViewEvent::ChatWindow { request, window }).await
    })
}

/// Close the window of `chat_id`; later live data for it changes only the
/// chat list. Closing a chat that is not open does nothing.
///
/// # Errors
/// None today; the signature matches the other commands.
pub fn close_chat<S: ByteStore + 'static, H: ViewHost<S>>(
    host: &mut H,
    chat_id: &str,
) -> Result<()> {
    host.core_mut().close_chat(chat_id);
    Ok(())
}

/// Mark `chat_id` read on every device (`Client::mark_chat_read`), then
/// persist the patched cached row and any rotated credentials.
///
/// # Errors
/// `Invalid` for a malformed id, network and persistence errors.
pub fn mark_read<'a, S: ByteStore + 'static, H: ViewHost<S>>(
    host: &'a mut H,
    chat_id: String,
    cancel: &'a CancellationToken,
) -> BoxFuture<'a, Result<()>> {
    Box::pin(async move {
        let core = host.core_mut();
        core.begin_client_operation(cancel);
        core.client_mut().mark_chat_read(&chat_id).await?;
        core.persist().await
    })
}
