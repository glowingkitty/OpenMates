//! Edit a user message with per-turn options: the same truncation as
//! `edit_message`, then the turn is admitted like `begin_send_with` so the
//! reply streams beside the actor. Options that only make sense for a new chat
//! (incognito, slug, reserved chat id) are refused before anything changes.
use super::{
    RequestId,
    actor_host::ViewHost,
    chat_actions::reopen_if_open,
    send_flows::ClientDispatch,
    send_request::SendTurnOptions,
    send_stream::{TurnStream, ViewLease},
};
use crate::{
    error::{Error, Result},
    local_cache::ByteStore,
};
use futures_util::future::BoxFuture;
use std::sync::Arc;
use tokio_util::sync::CancellationToken;

/// Edit user message `message_id` of `chat_id`: validate `options`, remove the
/// message and every later one (`Client::truncate_for_edit`), re-read the open
/// window, then admit `text` as the next turn of `request` with `options`
/// (embeds, PII exclusions and mappings, Project) exactly like
/// `begin_send_with`. The truncation is not undone when the send fails.
///
/// # Errors
/// `Invalid` for incognito, a slug or a reserved chat id, a non-canonical
/// Project id, malformed attachments, exclusions or mappings, or empty text
/// without embeds (all before anything changes); as `Client::truncate_for_edit`
/// (`Invalid` for an assistant or unknown message, `Forbidden` in a team
/// scope) and as `begin_send_with`.
#[allow(clippy::too_many_arguments)]
pub fn begin_edit_with<'a, S: ByteStore + 'static, H: ViewHost<S>>(
    host: &'a mut H,
    request: RequestId,
    chat_id: String,
    message_id: String,
    text: String,
    options: SendTurnOptions,
    sink: H::Sink,
    cancel: &'a CancellationToken,
    lease: Arc<dyn ViewLease<S>>,
) -> BoxFuture<'a, Result<TurnStream<S, H::Sink>>>
where
    H::Sink: Clone + 'static,
{
    Box::pin(async move {
        check_edit(&chat_id, &text, &options)?;
        host.core_mut().begin_client_operation(cancel);
        host.core_mut()
            .client_mut()
            .truncate_for_edit(&chat_id, &message_id)
            .await?;
        host.core_mut().persist().await?;
        reopen_if_open(host, request, chat_id.clone(), &sink, cancel).await?;
        let mut dispatch = ClientDispatch::new(host.core(), options);
        host.core_mut()
            .admit_turn(
                request,
                Some(chat_id),
                text,
                sink,
                cancel,
                lease,
                &mut dispatch,
            )
            .await
    })
}

/// Refuse an edit before anything changes: empty text without embeds, and
/// every option `SendTurnOptions::check` refuses for an existing chat
/// (incognito, slug, reserved chat id, bad Project id, bad attachments).
pub(super) fn check_edit(chat_id: &str, text: &str, options: &SendTurnOptions) -> Result<()> {
    if text.trim().is_empty() && options.embeds.is_empty() {
        return Err(Error::Invalid("Message text is required."));
    }
    options.check(Some(chat_id))
}
