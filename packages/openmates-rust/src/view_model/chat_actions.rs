//! The view-model actor's chat and message actions: delete a chat or a
//! message, edit a user message (truncate, then send the new text), retry the
//! last unanswered turn, fork a chat, save and clear drafts and stop a running
//! reply. Each flow calls one core operation (`client::message_actions`,
//! `client::chat_rewrite`, `Client::mutate`, `save_draft`, `clear_draft`),
//! persists, then republishes what changed (the chat list, the open window).
//! Mirrors the web chat and message menus and the TUI `chats` commands; plan
//! `apple-client-core-migration` step A5, spec `client-core`.
use super::{
    ChatWindowRecord, ListCompleteness, RequestId, ViewEvent,
    actor_flows::refresh_chats,
    actor_host::{ViewHost, ViewSink},
    send_flows::send,
    window_flows::open_chat,
};
use crate::{
    error::{Error, Result},
    local_cache::ByteStore,
    model::{Mutation, Workspace},
};
use futures_util::future::BoxFuture;
use tokio_util::sync::CancellationToken;

/// Delete chat `chat_id` on every device (a draft-only chat clears its
/// draft), close its window when open, persist and emit the chat list.
///
/// # Errors
/// As `Client::mutate` (`Invalid` for a volatile chat, `Protocol` for an
/// error answer, `Offline`); persistence and sink errors.
pub fn delete_chat<'a, S: ByteStore + 'static, H: ViewHost<S>>(
    host: &'a mut H,
    chat_id: String,
    sink: &'a H::Sink,
    cancel: &'a CancellationToken,
) -> BoxFuture<'a, Result<()>> {
    Box::pin(async move {
        uuid::Uuid::parse_str(&chat_id).map_err(|_| Error::Invalid("Invalid chat ID."))?;
        host.core_mut().begin_client_operation(cancel);
        let client = host.core_mut().client_mut();
        client
            .mutate(Mutation::Delete {
                workspace: Workspace::Chats,
                id: chat_id.clone(),
            })
            .await?;
        host.core_mut().close_chat(&chat_id);
        host.core_mut().persist().await?;
        emit_local_list(host, sink).await
    })
}

/// Delete one message of personal chat `chat_id`, persist, then re-read the
/// open window of that chat as `request` (no window event otherwise).
///
/// # Errors
/// As `Client::delete_message`; open, persistence and sink errors.
pub fn delete_message<'a, S: ByteStore + 'static, H: ViewHost<S>>(
    host: &'a mut H,
    request: RequestId,
    chat_id: String,
    message_id: String,
    sink: &'a H::Sink,
    cancel: &'a CancellationToken,
) -> BoxFuture<'a, Result<()>> {
    Box::pin(async move {
        host.core_mut().begin_client_operation(cancel);
        let client = host.core_mut().client_mut();
        client.delete_message(&chat_id, &message_id).await?;
        host.core_mut().persist().await?;
        reopen_if_open(host, request, chat_id, sink, cancel).await
    })
}

/// Edit user message `message_id`: remove it and every later message
/// (`Client::truncate_for_edit`), re-read the open window, then send `text`
/// as the next turn of `request` exactly like [`send`] (same events, same
/// cancel). The truncation is not undone when the send fails.
///
/// # Errors
/// As `Client::truncate_for_edit` (`Invalid` for an assistant or unknown
/// message, `Forbidden` in a team scope) and as [`send`].
pub fn edit_message<'a, S: ByteStore + 'static, H: ViewHost<S>>(
    host: &'a mut H,
    request: RequestId,
    chat_id: String,
    message_id: String,
    text: String,
    sink: &'a H::Sink,
    cancel: &'a CancellationToken,
) -> BoxFuture<'a, Result<ChatWindowRecord>> {
    Box::pin(async move {
        if text.trim().is_empty() {
            return Err(Error::Invalid("Message text is required."));
        }
        host.core_mut().begin_client_operation(cancel);
        let client = host.core_mut().client_mut();
        client.truncate_for_edit(&chat_id, &message_id).await?;
        host.core_mut().persist().await?;
        reopen_if_open(host, request, chat_id.clone(), sink, cancel).await?;
        send(host, request, Some(chat_id), text, sink, cancel).await
    })
}

/// Retry the newest unanswered user turn of `chat_id`: rewind to the message
/// before it (`Client::retry_chat`), re-read the open window, then send its
/// text again as `request` like [`send`].
///
/// # Errors
/// `Invalid` when no turn is retryable or it is the first message; as
/// `Client::chat_rewrite_state`, `Client::rewind_chat` and [`send`].
pub fn retry_turn<'a, S: ByteStore + 'static, H: ViewHost<S>>(
    host: &'a mut H,
    request: RequestId,
    chat_id: String,
    sink: &'a H::Sink,
    cancel: &'a CancellationToken,
) -> BoxFuture<'a, Result<ChatWindowRecord>> {
    Box::pin(async move {
        uuid::Uuid::parse_str(&chat_id).map_err(|_| Error::Invalid("Invalid chat ID."))?;
        host.core_mut().begin_client_operation(cancel);
        let client = host.core_mut().client_mut();
        let state = client.chat_rewrite_state(&chat_id).await?;
        let (_, prompt) = client.retry_chat(&state, false, true).await?;
        drop(state);
        let prompt = prompt.ok_or(Error::Protocol)?;
        host.core_mut().persist().await?;
        reopen_if_open(host, request, chat_id.clone(), sink, cancel).await?;
        // The send owns its text; the zeroizing prompt is wiped on drop.
        send(
            host,
            request,
            Some(chat_id),
            prompt.as_str().to_owned(),
            sink,
            cancel,
        )
        .await
    })
}

/// Fork personal chat `chat_id` up to and including `message_id` into a new
/// encrypted chat (`Client::fork_chat`; `title` `None`: "Fork of …"), then
/// refresh and emit the chat list. Returns the new chat's id.
///
/// # Errors
/// As `Client::chat_rewrite_state` and `Client::fork_chat`; `Invalid` for an
/// unknown message; `Protocol` when the answer carries no new chat id.
pub fn fork_chat<'a, S: ByteStore + 'static, H: ViewHost<S>>(
    host: &'a mut H,
    chat_id: String,
    message_id: String,
    title: Option<String>,
    sink: &'a H::Sink,
    cancel: &'a CancellationToken,
) -> BoxFuture<'a, Result<String>> {
    Box::pin(async move {
        uuid::Uuid::parse_str(&chat_id).map_err(|_| Error::Invalid("Invalid chat ID."))?;
        host.core_mut().begin_client_operation(cancel);
        let client = host.core_mut().client_mut();
        let state = client.chat_rewrite_state(&chat_id).await?;
        let boundary = state
            .boundary_index(&message_id)
            .ok_or(Error::Invalid("The message is not in this chat."))?;
        let result = client.fork_chat(&state, boundary, title.as_deref()).await?;
        let new_chat = result["chat_id"]
            .as_str()
            .filter(|id| uuid::Uuid::parse_str(id).is_ok())
            .ok_or(Error::Protocol)?
            .to_owned();
        refresh_chats(host, sink, cancel).await?;
        Ok(new_chat)
    })
}

/// Save `markdown` as the encrypted draft of `chat_id` (`None`: a new chat),
/// persist and emit the chat list. Returns the draft's chat id.
///
/// # Errors
/// As `Client::save_draft`: `Invalid` for a bad id, a volatile chat or an
/// oversized draft, `Forbidden` in a team scope, `Offline`.
pub fn save_draft<'a, S: ByteStore + 'static, H: ViewHost<S>>(
    host: &'a mut H,
    chat_id: Option<String>,
    markdown: String,
    sink: &'a H::Sink,
    cancel: &'a CancellationToken,
) -> BoxFuture<'a, Result<String>> {
    Box::pin(async move {
        host.core_mut().begin_client_operation(cancel);
        let client = host.core_mut().client_mut();
        let id = client.save_draft(chat_id.as_deref(), &markdown).await?;
        host.core_mut().persist().await?;
        emit_local_list(host, sink).await?;
        Ok(id)
    })
}

/// Clear the draft of `chat_id` with its versioned tombstone (a draft-only
/// chat disappears), persist and emit the chat list.
///
/// # Errors
/// As `Client::clear_draft` (`Unavailable` in a team scope).
pub fn clear_draft<'a, S: ByteStore + 'static, H: ViewHost<S>>(
    host: &'a mut H,
    chat_id: String,
    sink: &'a H::Sink,
    cancel: &'a CancellationToken,
) -> BoxFuture<'a, Result<()>> {
    Box::pin(async move {
        host.core_mut().begin_client_operation(cancel);
        let client = host.core_mut().client_mut();
        client.clear_draft(&chat_id).await?;
        host.core_mut().persist().await?;
        emit_local_list(host, sink).await
    })
}

/// Stop assistant task `task_id` in `chat_id` (`Client::cancel_ai_task`).
/// A turn into `chat_id` that streams beside the actor (`begin_send`) is
/// cancelled first and ends `Cancelled`. A joined send (`send`) keeps the
/// actor, so this flow queues behind it; use `SendCancelHandle` there.
///
/// # Errors
/// As `Client::cancel_ai_task`; persistence errors.
pub fn stop_reply<'a, S: ByteStore + 'static, H: ViewHost<S>>(
    host: &'a mut H,
    chat_id: String,
    task_id: String,
    cancel: &'a CancellationToken,
) -> BoxFuture<'a, Result<()>> {
    Box::pin(async move {
        // A reply streaming beside the actor ends at once: its turn withdraws
        // the task on its own socket and ends `Cancelled`.
        host.core().foreground.cancel_chat(&chat_id);
        host.core_mut().begin_client_operation(cancel);
        let client = host.core_mut().client_mut();
        client.cancel_ai_task(&chat_id, &task_id).await?;
        host.core_mut().persist().await
    })
}

/// Re-read `chat_id` as `request` when it is the open window, so a changed
/// server history replaces the shown one.
async fn reopen_if_open<S: ByteStore + 'static, H: ViewHost<S>>(
    host: &mut H,
    request: RequestId,
    chat_id: String,
    sink: &H::Sink,
    cancel: &CancellationToken,
) -> Result<()> {
    if host.core().open_chat_id() != Some(chat_id.as_str()) {
        return Ok(());
    }
    open_chat(host, request, chat_id, sink, cancel).await
}

/// The chat list from the client's current rows, without network. `Partial`:
/// a local change never proves the whole inventory.
async fn emit_local_list<S: ByteStore + 'static, H: ViewHost<S>>(
    // `&mut`: a shared `&H` is not `Send`, since hosts are only `Send`.
    host: &mut H,
    sink: &H::Sink,
) -> Result<()> {
    let event: ViewEvent = {
        let core = host.core();
        let items = core.client().cached_chat_items()?;
        core.chat_list_event(items, ListCompleteness::Partial)?
    };
    sink.emit(event).await
}
