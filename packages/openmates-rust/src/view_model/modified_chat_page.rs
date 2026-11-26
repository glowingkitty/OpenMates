//! Explicit pages of older modified-chat metadata for native chat lists.
use super::{ViewSink, actor_host::ViewHost};
use crate::{
    error::{Error, Result},
    local_cache::ByteStore,
};
use futures_util::future::BoxFuture;
use tokio_util::sync::CancellationToken;

/// Fetch one 20-chat metadata page in the current workspace and emit the
/// merged list. This command never runs from startup or reconnect.
///
/// # Errors
/// Authorization, cancellation or malformed response.
pub fn load_more_chat_metadata<'a, S: ByteStore + 'static, H: ViewHost<S>>(
    host: &'a mut H,
    offset: usize,
    sink: &'a H::Sink,
    cancel: &'a CancellationToken,
) -> BoxFuture<'a, Result<()>> {
    Box::pin(async move {
        let core = host.core_mut();
        let generation = core.shell().ops().guard();
        core.begin_client_operation(cancel);
        let offset = if offset == 0 {
            core.client().modified_chat_metadata_offset()
        } else {
            offset
        };
        let items = core
            .client_mut()
            .load_modified_chat_metadata_page(offset)
            .await?;
        if cancel.is_cancelled() || !generation.is_current() {
            return Err(Error::Cancelled);
        }
        // Paging is an explicit metadata read, not an archive-cache or
        // transcript retention grant.
        let event = core.chat_list_event(items, super::ListCompleteness::Partial)?;
        sink.emit(event).await
    })
}
