use super::{actor_host::ViewHost, send_request::SendTurnOptions};
use crate::{
    client::{QueuedRevisionMode, QueuedRevisionReceipt},
    error::{Error, Result},
    local_cache::ByteStore,
};
use futures_util::future::BoxFuture;
use tokio_util::sync::CancellationToken;

/// Revise queued follow-up `message_id` of `chat_id` and/or switch its queue
/// `mode` (`Client::revise_queued_message`). `expected_revision` is the
/// revision the queued turn last reported (`SendReceipt::queue_revision`).
/// `options` carries the PII choices (detection, exclusions, mappings) of a
/// changed `text`; its attachments, Project and id fields do not apply.
///
/// # Errors
/// `Invalid` for options that do not apply to an existing chat, nothing to
/// change, empty text or a malformed id; `Conflict` for a stale revision;
/// otherwise as `Client::revise_queued_message`.
#[allow(clippy::too_many_arguments)]
pub fn revise_queued_message<'a, S: ByteStore + 'static, H: ViewHost<S>>(
    host: &'a mut H,
    chat_id: String,
    message_id: String,
    expected_revision: u64,
    mode: Option<QueuedRevisionMode>,
    text: Option<String>,
    options: SendTurnOptions,
    cancel: &'a CancellationToken,
) -> BoxFuture<'a, Result<QueuedRevisionReceipt>> {
    Box::pin(async move {
        options.check(Some(&chat_id))?;
        if !options.embeds.is_empty() {
            return Err(Error::Invalid("A queued revision takes no attachments."));
        }
        host.core_mut().begin_client_operation(cancel);
        let receipt = host
            .core_mut()
            .client_mut()
            .revise_queued_message(
                &chat_id,
                &message_id,
                expected_revision,
                mode,
                text.as_deref(),
                options.send_options(),
            )
            .await?;
        host.core_mut().persist().await?;
        Ok(receipt)
    })
}
