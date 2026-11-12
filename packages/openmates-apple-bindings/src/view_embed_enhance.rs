//! Image Enhance on `ViewModelCore` for the Apple shell (spec
//! `feature.embed-user-edits`, `enhance.*`): start a job on the head version
//! of an image embed, read or wait for it (WebSocket `image_enhance_ready` /
//! `image_enhance_failed` frames forwarded through `ImageEnhanceWaker` cut
//! the poll delay short), and save the ready result as the next version of
//! the same embed. The core (`Client::start_image_enhance`,
//! `wait_image_enhance`, `image_enhance_status`, `save_image_enhance_result`,
//! `enhance_image`) owns the job reads, backoff, keys and the commit; this
//! module only marshals and maps `ImageEnhanceError` to `EmbedEditError`.
//! Mirrors `browser_embed_user_edit.rs`; plan `apple-client-core-migration`.
use crate::CoreError;
use crate::core::CoreCancellation;
use crate::view_core::ViewModelCore;
use crate::view_embeds::{EmbedEditError, EmbedRevisionOutcomeRecord, EmbedScopeRecord};
use openmates_sdk::client::embed_user_revision::RevisionScope;
use openmates_sdk::client::image_enhance::{
    DEFAULT_ENHANCE_DEADLINE, EnhanceJob, EnhanceJobState, ImageEnhanceError, ImageEnhanceSaved,
    ImageEnhanceWaker as CoreWaker,
};
use std::sync::Arc;
use std::time::Duration;

impl From<ImageEnhanceError> for EmbedEditError {
    fn from(error: ImageEnhanceError) -> Self {
        match error {
            ImageEnhanceError::InsufficientCredits => Self::InsufficientCredits,
            ImageEnhanceError::TeamUnavailable => Self::TeamUnavailable,
            ImageEnhanceError::ProjectContextRequired => Self::ProjectContextRequired,
            ImageEnhanceError::ScopeMismatch => Self::ScopeMismatch,
            ImageEnhanceError::VersionConflict { current_version } => {
                Self::VersionConflict { current_version }
            }
            ImageEnhanceError::NotFound { code } => Self::NotFound { code: code.into() },
            ImageEnhanceError::InvalidSource { code } => Self::InvalidSource { code: code.into() },
            ImageEnhanceError::RateLimited => Self::RateLimited,
            ImageEnhanceError::Busy => Self::Busy,
            ImageEnhanceError::OperationConflict => Self::OperationConflict,
            ImageEnhanceError::Unavailable { code } => Self::Unavailable { code: code.into() },
            ImageEnhanceError::Failed { operation_id, code } => {
                Self::EnhanceFailed { operation_id, code }
            }
            ImageEnhanceError::Expired { operation_id } => Self::EnhanceExpired { operation_id },
            ImageEnhanceError::NotReady { operation_id } => Self::EnhanceNotReady { operation_id },
            ImageEnhanceError::Timeout { operation_id } => Self::EnhanceTimeout { operation_id },
            ImageEnhanceError::KeyUnavailable => Self::KeyUnavailable,
            ImageEnhanceError::Revision(error) => error.into(),
            ImageEnhanceError::Transport(error) => error.into(),
        }
    }
}

/// Forwards Enhance WebSocket frames into a running `waitImageEnhance` or
/// `enhanceImage`, so the next job read happens at once. Create one per
/// Enhance and feed it the `unownedSocketFrame` events (`type`, payload
/// JSON); safe to call from any thread while the wait runs.
#[derive(uniffi::Object)]
pub struct ImageEnhanceWaker {
    pub(crate) inner: CoreWaker,
}

#[uniffi::export]
impl ImageEnhanceWaker {
    /// A waker with no pending event.
    #[uniffi::constructor]
    pub fn new() -> Arc<Self> {
        Arc::new(Self {
            inner: CoreWaker::new(),
        })
    }

    /// Feed one socket frame: `true` when it was `image_enhance_ready` or
    /// `image_enhance_failed` with a valid payload and woke the wait, `false`
    /// for every other frame.
    ///
    /// # Errors
    /// `Invalid` when `payload_json` is not JSON.
    pub fn notify_frame(
        &self,
        event_type: String,
        payload_json: String,
    ) -> std::result::Result<bool, CoreError> {
        let payload: serde_json::Value =
            serde_json::from_str(&payload_json).map_err(|_| CoreError::Invalid {
                message: "The frame payload is not JSON.".to_owned(),
            })?;
        Ok(self.inner.notify_frame(&event_type, &payload))
    }
}

/// Server state of an Enhance job.
#[derive(Clone, Copy, Debug, PartialEq, Eq, uniffi::Enum)]
pub enum ImageEnhanceStateRecord {
    /// Running.
    Pending,
    /// A result exists; save it before `expires_at`.
    Ready,
    /// Saved as version `target_version`.
    Committed,
    /// Failed; nothing was charged.
    Failed,
    /// Never saved and deleted.
    Expired,
}

/// One Enhance job (no result bytes or keys: those stay in the core until
/// the save seals them).
#[derive(Clone, Debug, PartialEq, Eq, uniffi::Record)]
pub struct ImageEnhanceJobRecord {
    /// The job's idempotency key; keep it to resume.
    pub operation_id: String,
    /// The enhanced embed.
    pub embed_id: String,
    /// Job state.
    pub state: ImageEnhanceStateRecord,
    /// Version N the job enhances.
    pub base_version: i64,
    /// Version N+1 the result becomes.
    pub target_version: i64,
    /// Quoted price in credits.
    pub credits: i64,
    /// Whether the price was charged.
    pub charged: bool,
    /// Unix seconds the job was created.
    pub created_at: i64,
    /// Unix seconds after which an unsaved result is deleted.
    pub expires_at: i64,
    /// Failure code of a failed job.
    pub error_code: Option<String>,
}

impl From<EnhanceJob> for ImageEnhanceJobRecord {
    fn from(job: EnhanceJob) -> Self {
        Self {
            state: match job.state {
                EnhanceJobState::Pending => ImageEnhanceStateRecord::Pending,
                EnhanceJobState::Ready => ImageEnhanceStateRecord::Ready,
                EnhanceJobState::Committed => ImageEnhanceStateRecord::Committed,
                EnhanceJobState::Failed => ImageEnhanceStateRecord::Failed,
                EnhanceJobState::Expired => ImageEnhanceStateRecord::Expired,
            },
            operation_id: job.operation_id,
            embed_id: job.embed_id,
            base_version: job.base_version,
            target_version: job.target_version,
            credits: job.credits,
            charged: job.charged,
            created_at: job.created_at,
            expires_at: job.expires_at,
            error_code: job.error_code,
        }
    }
}

/// What saving an Enhance result did.
#[derive(Clone, Debug, PartialEq, Eq, uniffi::Enum)]
pub enum ImageEnhanceSavedRecord {
    /// Saved now as the next version (its chat event is `outcome.event`).
    Committed {
        /// The job's operation id.
        operation_id: String,
        /// The committed version.
        outcome: EmbedRevisionOutcomeRecord,
    },
    /// An earlier attempt or another device already saved it: reload the
    /// embed (its chat event comes from the pending-notice reconcile).
    AlreadyCommitted {
        /// The job's operation id.
        operation_id: String,
        /// The version the result became.
        version: i64,
    },
}

impl From<ImageEnhanceSaved> for ImageEnhanceSavedRecord {
    fn from(value: ImageEnhanceSaved) -> Self {
        match value {
            ImageEnhanceSaved::Committed {
                operation_id,
                outcome,
            } => Self::Committed {
                operation_id,
                outcome: (*outcome).into(),
            },
            ImageEnhanceSaved::AlreadyCommitted {
                operation_id,
                version,
            } => Self::AlreadyCommitted {
                operation_id,
                version,
            },
        }
    }
}

fn deadline(deadline_ms: Option<u64>) -> Duration {
    deadline_ms.map_or(DEFAULT_ENHANCE_DEADLINE, Duration::from_millis)
}

#[uniffi::export]
impl ViewModelCore {
    /// Start Enhance of the head version of image `embed_id` in `scope` (or
    /// replay the job `operation_id`; `nil`: a fresh UUID). Returns the job;
    /// keep its `operation_id` to wait, read and save. Waits for a running
    /// command.
    ///
    /// # Errors
    /// `TeamUnavailable`, `ProjectContextRequired`, `InsufficientCredits`,
    /// `VersionConflict` (no charge), `InvalidSource`, `NotFound`,
    /// `RateLimited`, `Busy`, `OperationConflict`, `Unavailable`,
    /// `KeyUnavailable`, `Offline`, `SessionExpired`, `Cancelled`.
    pub async fn start_image_enhance(
        &self,
        embed_id: String,
        scope: EmbedScopeRecord,
        operation_id: Option<String>,
        cancellation: Option<Arc<CoreCancellation>>,
    ) -> std::result::Result<ImageEnhanceJobRecord, EmbedEditError> {
        let scope: RevisionScope = scope.into();
        self.embed_command(cancellation, move |client| {
            Box::pin(async move {
                let (head, _) = client.embed_user_edit_head(&embed_id).await?;
                let job = client
                    .start_image_enhance(&head, &scope, operation_id.as_deref())
                    .await?;
                Ok(job.into())
            })
        })
        .await
    }

    /// Read the job `operation_id` now (after an Enhance frame or on
    /// resume). Reading a ready result counts as its delivery: it stays
    /// charged and saveable until `expires_at`.
    ///
    /// # Errors
    /// `NotFound { enhance_not_found }`, `Busy`, `Offline`, `Cancelled`.
    pub async fn image_enhance_status(
        &self,
        operation_id: String,
        cancellation: Option<Arc<CoreCancellation>>,
    ) -> std::result::Result<ImageEnhanceJobRecord, EmbedEditError> {
        self.embed_command(cancellation, move |client| {
            Box::pin(async move { Ok(client.image_enhance_status(&operation_id).await?.into()) })
        })
        .await
    }

    /// Wait until the job `operation_id` is ready or committed, for at most
    /// `deadline_ms` (`nil`: 180 s). The wait holds the actor, so other
    /// commands queue behind it: wait in short slices (for example 15 s,
    /// then `waitImageEnhance` again) or cancel it when the user leaves the
    /// image. Frames fed to `waker` make the next read happen at once.
    ///
    /// # Errors
    /// `EnhanceFailed` (nothing charged), `EnhanceExpired`, `EnhanceTimeout`
    /// (the job keeps running), and the errors of `imageEnhanceStatus`.
    pub async fn wait_image_enhance(
        &self,
        operation_id: String,
        deadline_ms: Option<u64>,
        waker: Option<Arc<ImageEnhanceWaker>>,
        cancellation: Option<Arc<CoreCancellation>>,
    ) -> std::result::Result<ImageEnhanceJobRecord, EmbedEditError> {
        let waker = waker.map(|waker| waker.inner.clone());
        let deadline = deadline(deadline_ms);
        self.embed_command(cancellation, move |client| {
            Box::pin(async move {
                let job = client
                    .wait_image_enhance(&operation_id, waker.as_ref(), deadline)
                    .await?;
                Ok(job.into())
            })
        })
        .await
    }

    /// Save the result of job `operation_id` as the next version of
    /// `embed_id` in the scope it was started in. The head is the core's
    /// cached head, which must still be the version the job started from.
    /// Safe to repeat: a result already saved (here or on another device)
    /// returns `AlreadyCommitted` instead of a second version.
    ///
    /// # Errors
    /// `EnhanceNotReady`, `EnhanceFailed`, `EnhanceExpired`, `VersionConflict`
    /// (the head moved), `ScopeMismatch`, `ProjectContextRequired`,
    /// `KeyUnavailable`, and the commit's refusals.
    pub async fn save_image_enhance_result(
        &self,
        embed_id: String,
        scope: EmbedScopeRecord,
        operation_id: String,
        cancellation: Option<Arc<CoreCancellation>>,
    ) -> std::result::Result<ImageEnhanceSavedRecord, EmbedEditError> {
        let scope: RevisionScope = scope.into();
        self.embed_command(cancellation, move |client| {
            Box::pin(async move {
                let (head, _) = client.embed_user_edit_head(&embed_id).await?;
                let saved = client
                    .save_image_enhance_result(head, scope, &operation_id, None)
                    .await?;
                Ok(saved.into())
            })
        })
        .await
    }

    /// Enhance the head version of image `embed_id` and save the result as
    /// its next version in one call: start, wait up to 180 s, commit with
    /// action `enhance`, write the chat event. `operation_id` is the job's
    /// UUID chosen by Swift (keep it: on `EnhanceTimeout`, a lost answer or a
    /// cancel, resume with `saveImageEnhanceResult`; nothing is charged
    /// twice). Holds the actor for the whole run; prefer
    /// `startImageEnhance` + sliced `waitImageEnhance` + save when other
    /// commands must stay responsive.
    ///
    /// # Errors
    /// The errors of `startImageEnhance`, `waitImageEnhance` and
    /// `saveImageEnhanceResult`.
    pub async fn enhance_image(
        &self,
        embed_id: String,
        scope: EmbedScopeRecord,
        operation_id: String,
        waker: Option<Arc<ImageEnhanceWaker>>,
        cancellation: Option<Arc<CoreCancellation>>,
    ) -> std::result::Result<ImageEnhanceSavedRecord, EmbedEditError> {
        let scope: RevisionScope = scope.into();
        let waker = waker.map(|waker| waker.inner.clone());
        self.embed_command(cancellation, move |client| {
            Box::pin(async move {
                let (head, _) = client.embed_user_edit_head(&embed_id).await?;
                let saved = client
                    .enhance_image(head, scope, Some(&operation_id), None, waker.as_ref())
                    .await?;
                Ok(saved.into())
            })
        })
        .await
    }
}
