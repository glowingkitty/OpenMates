//! Revise or steer a queued follow-up on `ViewModelCore`, over the core flow
//! `openmates_sdk::view_model::revise_queued_message`. Bindings only marshal.
//! Spec `client-core` and `features/chat-queued-followups`.
use crate::CoreError;
use crate::core::CoreCancellation;
use crate::view_core::ViewModelCore;
use crate::view_send_options::{SendOptionsRecord, SendQueueModeRecord};
use openmates_sdk::client::QueuedRevisionMode;
use openmates_sdk::view_model;
use std::sync::Arc;

/// The server's confirmation of a queued-message revision.
#[derive(Clone, Debug, PartialEq, Eq, uniffi::Record)]
pub struct QueuedRevisionReceiptRecord {
    /// The chat of the queued message.
    pub chat_id: String,
    /// The unchanged id of the queued message.
    pub message_id: String,
    /// The mode now in force.
    pub queue_mode: SendQueueModeRecord,
    /// The revision now in force; use it as the next `expected_revision`.
    pub queue_revision: u64,
}

fn mode(record: SendQueueModeRecord) -> QueuedRevisionMode {
    match record {
        SendQueueModeRecord::FollowUp => QueuedRevisionMode::FollowUp,
        SendQueueModeRecord::Steer => QueuedRevisionMode::Steer,
    }
}

#[uniffi::export]
impl ViewModelCore {
    /// Revise queued follow-up `message_id` of `chat_id` (new `text`, a new
    /// `mode`, or both). `revision` is the queue revision the turn last
    /// reported (`SendReceiptRecord.queueRevision` or the receipt of the
    /// previous revision). `options` carries the PII choices of a changed
    /// text; attachments are refused. Runs on the actor.
    ///
    /// # Errors
    /// `Authentication` when signed out; `Invalid` for a malformed id, nothing
    /// to change, empty text or options that do not apply; `Conflict` is
    /// `Conflict` for a stale revision; `Forbidden`
    /// in a Team scope; `Unavailable` (`queued_revision`: `not_queued`,
    /// `inactive`, `busy`, ...) for other server rejections; `Offline`;
    /// `Cancelled`.
    #[allow(clippy::too_many_arguments)]
    pub async fn revise_queued_message(
        &self,
        chat_id: String,
        message_id: String,
        revision: u64,
        text: Option<String>,
        mode_change: Option<SendQueueModeRecord>,
        options: SendOptionsRecord,
        cancellation: Option<Arc<CoreCancellation>>,
    ) -> Result<QueuedRevisionReceiptRecord, CoreError> {
        let (shared, token) = (self.shared.clone(), self.detached(cancellation));
        let options = options.into();
        self.run(async move {
            let receipt = shared
                .signed_in(token, move |host, _sink, cancel| {
                    view_model::revise_queued_message(
                        host,
                        chat_id,
                        message_id,
                        revision,
                        mode_change.map(mode),
                        text,
                        options,
                        cancel,
                    )
                })
                .await?;
            Ok::<_, openmates_sdk::error::Error>(QueuedRevisionReceiptRecord {
                chat_id: receipt.chat_id,
                message_id: receipt.message_id,
                queue_mode: match receipt.queue_mode {
                    QueuedRevisionMode::FollowUp => SendQueueModeRecord::FollowUp,
                    QueuedRevisionMode::Steer => SendQueueModeRecord::Steer,
                },
                queue_revision: receipt.queue_revision,
            })
        })
        .await
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::view_send_options_tests::options;

    #[test]
    fn mode_records_map_to_the_core_modes() {
        assert_eq!(mode(SendQueueModeRecord::Steer), QueuedRevisionMode::Steer);
        assert_eq!(
            mode(SendQueueModeRecord::FollowUp),
            QueuedRevisionMode::FollowUp
        );
    }

    #[tokio::test(flavor = "multi_thread")]
    async fn a_signed_out_core_refuses_with_authentication() {
        use crate::view_core_tests::{Events, Keychain, private_dir};
        use crate::view_window_tests::{CHAT, core};
        let dir = private_dir();
        let (keychain, events) = (Arc::new(Keychain::default()), Arc::new(Events::default()));
        let core = core(dir.path(), "http://127.0.0.1:9", &keychain, &events);
        core.start(None).await.unwrap();
        let result = core
            .revise_queued_message(
                CHAT.into(),
                "m".into(),
                1,
                None,
                Some(SendQueueModeRecord::Steer),
                options(),
                None,
            )
            .await;
        assert_eq!(result, Err(CoreError::Authentication));
    }
}
