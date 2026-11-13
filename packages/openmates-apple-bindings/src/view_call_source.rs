//! UniFFI export of `Client::persist_call_source_frame`: Apple answers the
//! server's `voice_source_frame` request by handing the base64 JPEG to the
//! core, which uploads it and stores it as an owner-encrypted image embed of
//! the call's chat. Marshalling only; validation, crypto and storage live in
//! `openmates_sdk::client::call_source_frame` (mirror of web
//! `voiceCallVisuals.ts`). Spec `client-core`.
use crate::CoreError;
use crate::core::CoreCancellation;
use crate::view_core::ViewModelCore;
use openmates_sdk::client::call_source_frame::{CallSourceFrame, CallSourceKind};
use openmates_sdk::error::Error;
use openmates_sdk::view_model::ViewHost;
use std::sync::Arc;

/// Where a call source frame was captured.
#[derive(Clone, Copy, Debug, PartialEq, Eq, uniffi::Enum)]
pub enum CallSourceKindRecord {
    /// The device camera.
    Camera,
    /// A screen share.
    Screen,
}

/// Reference to the saved image embed, sent back to the voice pipeline.
#[derive(Clone, Debug, PartialEq, uniffi::Record)]
pub struct CallSourceReferenceRecord {
    /// Embed id assigned by the upload server.
    pub embed_id: String,
    /// Echo of the frame id.
    pub source_frame_id: String,
    /// Echo of the capture time (seconds).
    pub captured_at: f64,
    /// Echo of the call id.
    pub source_call_id: String,
    /// Echo of the source kind.
    pub source: CallSourceKindRecord,
}

pub(crate) fn kind_in(kind: CallSourceKindRecord) -> CallSourceKind {
    match kind {
        CallSourceKindRecord::Camera => CallSourceKind::Camera,
        CallSourceKindRecord::Screen => CallSourceKind::Screen,
    }
}

pub(crate) fn kind_out(kind: CallSourceKind) -> CallSourceKindRecord {
    match kind {
        CallSourceKind::Camera => CallSourceKindRecord::Camera,
        CallSourceKind::Screen => CallSourceKindRecord::Screen,
    }
}

#[uniffi::export]
impl ViewModelCore {
    /// Save one call source frame as an encrypted image embed of `chat_id`
    /// and return its reference. `data` is the base64 JPEG exactly as the
    /// server's `voice_source_frame` message carries it. Team and Direct
    /// chats are refused.
    ///
    /// # Errors
    /// `Authentication` when signed out; `Invalid` for a malformed frame;
    /// `Forbidden` for a team/Direct/keyless chat or an unreadable existing
    /// key; `Offline` when the server did not confirm the store; `Protocol`
    /// for an upload rejection; transport and crypto errors; `Cancelled`.
    pub async fn persist_call_source_frame(
        &self,
        call_id: String,
        chat_id: String,
        user_message_id: String,
        frame_id: String,
        data: String,
        captured_at: f64,
        created_at: i64,
        source: CallSourceKindRecord,
        cancellation: Option<Arc<CoreCancellation>>,
    ) -> Result<CallSourceReferenceRecord, CoreError> {
        let frame = CallSourceFrame {
            call_id,
            chat_id,
            message_id: user_message_id,
            frame_id,
            data,
            captured_at,
            created_at,
            source: kind_in(source),
        };
        let (shared, token) = (self.shared.clone(), self.detached(cancellation));
        self.run(async move {
            shared
                .signed_in(token, move |host, _sink, cancel| {
                    Box::pin(async move {
                        let result = tokio::select! {
                            biased;
                            () = cancel.cancelled() => Err(Error::Cancelled),
                            result = host.core_mut().client_mut().persist_call_source_frame(frame) => {
                                result.map_err(Error::from)
                            }
                        };
                        host.core_mut().persist().await?;
                        result.map(|saved| CallSourceReferenceRecord {
                            embed_id: saved.embed_id,
                            source_frame_id: saved.source_frame_id,
                            captured_at: saved.captured_at,
                            source_call_id: saved.source_call_id,
                            source: kind_out(saved.source),
                        })
                    })
                })
                .await
        })
        .await
    }
}

#[cfg(test)]
#[path = "view_call_source_tests.rs"]
mod tests;
