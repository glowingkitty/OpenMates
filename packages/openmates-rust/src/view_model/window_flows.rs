//! The view-model actor's chat window commands: `OpenChat` (cached first page
//! before any network, selected-chat recovery, strict read), `LoadOlder`,
//! `CloseChat` and `MarkRead`. Moved from the TUI `runtime.rs` (`open_chat`,
//! `mark_read`); spec `a2-design.md` (View model, lane L7) and
//! `feature.chat-unread@1` (read receipts).
//!
//! Ordering invariant of `OpenChat`: the cached window (when one can be shown)
//! is emitted before the host's recovery hook and before any network request;
//! the strict window follows only after its durable receipt.
use super::{
    RequestId, ViewEvent,
    actor_host::{ViewHost, ViewSink},
};
use crate::{
    error::{Error, Result},
    local_cache::ByteStore,
};
use futures_util::future::BoxFuture;
use tokio_util::sync::CancellationToken;

/// Open `chat_id` as the window of `request`: emit the cached window when
/// one exists, run the host's selected-chat recovery, then read, persist and
/// emit the strict window (a cold chat's first page may come in between).
/// Replaces any other open window. A failed open keeps the window only when
/// a page was already shown.
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
        host.core_mut().begin_window(request, &chat_id);
        let result = open_window(host, request, &chat_id, sink, cancel).await;
        if result.is_err() && host.core().open_window().is_none() {
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
    if let Some(record) = core.cached_window(chat_id, cancel).await?
        && let Some(event) = core.publish_window(request, record)
    {
        sink.emit(event).await?;
    }
    host.recover_before_open(sink, chat_id).await?;
    let offline_allowed = host.offline_cache_allowed();
    let core = host.core_mut();
    let record = core
        .read_window(request, chat_id, sink, cancel, offline_allowed)
        .await?;
    let event = core
        .publish_window(request, record)
        .ok_or(Error::Cancelled)?;
    sink.emit(event).await
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
        core.client_mut().set_operation_cancel(cancel.clone());
        core.client_mut().mark_chat_read(&chat_id).await?;
        core.persist().await
    })
}
