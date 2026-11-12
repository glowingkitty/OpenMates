//! Image Enhance in the shared client core (spec `feature.embed-user-edits`,
//! assertions `enhance.faithful-2k`, `enhance.billed-once-refunded-on-failure`).
//! Builds `POST /v1/images/enhance` from the decrypted head of an image embed,
//! reads the job (`GET /v1/images/enhance/{operation_id}`) with backoff, an
//! overall deadline and WebSocket wake-ups, and turns a ready result into
//! version N+1 of the same embed, committed by `embed_user_revision` with
//! action `enhance`. Server contract: `backend/core/api/app/routes/images_enhance.py`.
use super::embed_updated_event::EmbedUpdateAction;
use super::embed_user_revision::{
    EmbedHead, EmbedRevisionOutcome, RevisionFiles, RevisionScope, UserRevisionError,
    UserRevisionRequest,
};
use super::embed_write::payload::decode_object;
use crate::error::Error;
use serde::Serialize;
use serde_json::{Map, Value, json};
use std::fmt;
use std::sync::{Arc, Mutex, PoisonError};
use std::time::Duration;
use tokio_util::sync::CancellationToken;
use zeroize::Zeroizing;

#[path = "image_enhance_client.rs"]
mod client_io;
#[path = "image_enhance_job.rs"]
mod job;
#[path = "image_enhance_refusal.rs"]
pub(crate) mod refusal;
use job::failure_code;
pub use job::{EnhanceJob, EnhanceJobState, EnhancedImage};
pub(crate) use job::{media_index_of, parse_job};

#[cfg(not(target_arch = "wasm32"))]
use super::upload::toon_encode;
// `upload` is native-only (file IO); the encoder itself is pure, so the web
// build compiles the same file here.
#[cfg(target_arch = "wasm32")]
#[allow(dead_code)] // Only `encode_fields` is used by this module; the rest serves `upload`.
#[path = "toon_encode.rs"]
mod toon_encode;

/// How long [`Client::enhance_image`](crate::client::Client::enhance_image)
/// waits for a result before it returns [`ImageEnhanceError::Timeout`]. The
/// job keeps running on the server; resume with the operation id.
pub const DEFAULT_ENHANCE_DEADLINE: Duration = Duration::from_secs(180);
/// Poll delays between job reads; the last one repeats. A WebSocket
/// `image_enhance_ready`/`image_enhance_failed` event cuts a delay short.
const POLL_DELAYS_MS: [u64; 5] = [1_500, 2_000, 3_000, 5_000, 8_000];
/// Per-variant marker of nonce-prefixed media ciphertext (no shared nonce).
const MEDIA_ENCRYPTION_V2: &str = "aes-gcm-nonce-prefixed-v1";
/// Largest source side the route accepts.
const MAX_SOURCE_SIDE: i64 = 8192;
/// Bucket of image variants that do not name one.
const IMAGE_BUCKET: &str = "chatfiles";

/// Why an Enhance did not produce a saved version. [`code`](Self::code) is
/// stable and equals the server's code where the server named one.
#[derive(Clone, Debug, PartialEq, Eq)]
pub enum ImageEnhanceError {
    /// The balance is below the price (402); nothing was charged.
    InsufficientCredits,
    /// Team images cannot be enhanced yet (403 `team_enhance_unavailable`).
    TeamUnavailable,
    /// The image belongs to a Project: start (and save) it in Project scope.
    ProjectContextRequired,
    /// The result is saved in another scope than the one it was started in.
    ScopeMismatch,
    /// The image changed since the Enhance started (no charge on start).
    VersionConflict {
        /// The server's (or the cached head's) current version, when known.
        current_version: Option<i64>,
    },
    /// The embed, chat, Project link or job does not exist for this account.
    NotFound {
        /// Server code (`embed_not_found`, `enhance_not_found`, ...).
        code: &'static str,
    },
    /// The head cannot be enhanced (not an image, unsupported file, bad key).
    InvalidSource {
        /// Stable code (`not_an_image`, `unsupported_format`, `source_not_owned`, ...).
        code: &'static str,
    },
    /// Too many Enhance requests (10 per minute, 100 per day).
    RateLimited,
    /// The job row is being updated; retry the same call.
    Busy,
    /// The operation id belongs to another embed or account.
    OperationConflict,
    /// The service is temporarily unavailable (`*_unavailable`).
    Unavailable {
        /// Server code.
        code: &'static str,
    },
    /// The job failed on the server; nothing was charged.
    Failed {
        /// The job's operation id.
        operation_id: String,
        /// Server `error_code` (`[a-z0-9_]`, else `enhance_failed`).
        code: String,
    },
    /// The result was not saved within 24 hours and is gone.
    Expired {
        /// The job's operation id.
        operation_id: String,
    },
    /// The job is still pending.
    NotReady {
        /// The job's operation id.
        operation_id: String,
    },
    /// The wait ended before the job settled; the job keeps running. Resume
    /// with [`Client::save_image_enhance_result`](crate::client::Client::save_image_enhance_result).
    Timeout {
        /// The job's operation id.
        operation_id: String,
    },
    /// The embed key is not available on this device.
    KeyUnavailable,
    /// The version commit was refused (see [`UserRevisionError`]).
    Revision(UserRevisionError),
    /// Transport, session or protocol failure.
    Transport(Error),
}

impl ImageEnhanceError {
    /// Stable code for shells and bindings.
    pub fn code(&self) -> &'static str {
        match self {
            Self::InsufficientCredits => "insufficient_credits",
            Self::TeamUnavailable => "team_enhance_unavailable",
            Self::ProjectContextRequired => "project_context_required",
            Self::ScopeMismatch => "enhance_scope_mismatch",
            Self::VersionConflict { .. } => "embed_version_conflict",
            Self::NotFound { code } | Self::InvalidSource { code } | Self::Unavailable { code } => {
                code
            }
            Self::RateLimited => "rate_limited",
            Self::Busy => "enhance_job_busy",
            Self::OperationConflict => "operation_id_conflict",
            Self::Failed { .. } => "enhance_failed",
            Self::Expired { .. } => "enhance_result_expired",
            Self::NotReady { .. } => "enhance_result_not_ready",
            Self::Timeout { .. } => "enhance_timeout",
            Self::KeyUnavailable => "embed_key_unavailable",
            Self::Revision(error) => error.code(),
            Self::Transport(error) => UserRevisionError::Transport(*error).code(),
        }
    }

    /// True when the same call may succeed later without user action.
    pub fn is_retryable(&self) -> bool {
        matches!(
            self,
            Self::RateLimited
                | Self::Busy
                | Self::Unavailable { .. }
                | Self::NotReady { .. }
                | Self::Timeout { .. }
                | Self::Transport(Error::Offline)
                | Self::Revision(UserRevisionError::Transport(Error::Offline))
        )
    }
}

impl fmt::Display for ImageEnhanceError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::InsufficientCredits => f.write_str("Not enough credits to enhance this image."),
            Self::TeamUnavailable => f.write_str("Enhance is not available for Team images yet."),
            Self::VersionConflict { .. } => {
                f.write_str("The image changed on another device. Reload it and try again.")
            }
            Self::Timeout { .. } => f.write_str(
                "Enhance is taking longer than expected. It continues in the background.",
            ),
            Self::Revision(error) => write!(f, "{error}"),
            Self::Transport(error) => write!(f, "{error}"),
            other => write!(f, "The image was not enhanced ({}).", other.code()),
        }
    }
}

impl std::error::Error for ImageEnhanceError {}

impl From<Error> for ImageEnhanceError {
    fn from(error: Error) -> Self {
        Self::Transport(error)
    }
}

impl From<UserRevisionError> for ImageEnhanceError {
    fn from(error: UserRevisionError) -> Self {
        match error {
            UserRevisionError::ProjectContextRequired => Self::ProjectContextRequired,
            UserRevisionError::VersionConflict {
                current_revision, ..
            } => Self::VersionConflict {
                current_version: current_revision,
            },
            UserRevisionError::Refused {
                code: "enhance_scope_mismatch",
            } => Self::ScopeMismatch,
            UserRevisionError::Refused {
                code: "enhance_version_mismatch",
            } => Self::VersionConflict {
                current_version: None,
            },
            UserRevisionError::KeyUnavailable => Self::KeyUnavailable,
            other => Self::Revision(other),
        }
    }
}

/// Result type of this module.
pub type ImageEnhanceResult<T> = std::result::Result<T, ImageEnhanceError>;

/// What [`Client::save_image_enhance_result`](crate::client::Client::save_image_enhance_result)
/// and [`Client::enhance_image`](crate::client::Client::enhance_image) did.
#[derive(Clone, Debug, PartialEq, Eq, Serialize)]
#[serde(tag = "state", rename_all = "snake_case")]
pub enum ImageEnhanceSaved {
    /// Saved now as the next version; the chat event is in `outcome.event`.
    Committed {
        /// The Enhance job's operation id.
        operation_id: String,
        /// The committed version and its chat event.
        outcome: Box<EmbedRevisionOutcome>,
    },
    /// An earlier attempt (this or another device) already saved it. Reload
    /// the embed; its chat event is written by the pending-notice reconcile.
    AlreadyCommitted {
        /// The Enhance job's operation id.
        operation_id: String,
        /// The version the result became.
        version: i64,
    },
}

impl ImageEnhanceSaved {
    /// The version the result is saved as.
    pub fn version(&self) -> i64 {
        match self {
            Self::Committed { outcome, .. } => outcome.commit.committed.version,
            Self::AlreadyCommitted { version, .. } => *version,
        }
    }
}

/// A WebSocket `image_enhance_ready` / `image_enhance_failed` event. It only
/// says "re-check now": the job read stays authoritative.
#[derive(Clone, Debug, PartialEq, Eq, Serialize)]
pub struct ImageEnhanceEvent {
    /// The job's operation id.
    pub operation_id: String,
    /// The enhanced embed.
    pub embed_id: String,
    /// True for `image_enhance_ready`.
    pub ready: bool,
    /// Failure code of `image_enhance_failed`.
    pub error_code: Option<String>,
}

fn bounded_id(value: &Value, max: usize) -> Option<String> {
    value
        .as_str()
        .filter(|id| (1..=max).contains(&id.len()))
        .map(str::to_owned)
}

/// Read a WebSocket frame `{type, payload}`; `None` for any other event or a
/// malformed payload.
pub fn parse_image_enhance_event(event_type: &str, payload: &Value) -> Option<ImageEnhanceEvent> {
    let ready = match event_type {
        "image_enhance_ready" => true,
        "image_enhance_failed" => false,
        _ => return None,
    };
    Some(ImageEnhanceEvent {
        operation_id: bounded_id(&payload["operation_id"], 128)?,
        embed_id: bounded_id(&payload["embed_id"], 512)?,
        ready,
        error_code: (!ready).then(|| failure_code(&payload["error_code"])),
    })
}

#[derive(Debug, Default)]
struct WakerState {
    token: CancellationToken,
    last: Option<ImageEnhanceEvent>,
}

/// Lets a shell forward Enhance WebSocket events into a running wait: each
/// [`notify`](Self::notify) ends the current poll delay at once. Cheap to
/// clone and safe to call from any task while the client is busy waiting.
#[derive(Clone, Debug, Default)]
pub struct ImageEnhanceWaker {
    inner: Arc<Mutex<WakerState>>,
}

impl ImageEnhanceWaker {
    /// A waker with no pending event.
    pub fn new() -> Self {
        Self::default()
    }

    fn state(&self) -> std::sync::MutexGuard<'_, WakerState> {
        // The state is a token and the last event; a panic while holding the
        // lock cannot leave it half-written, so a poisoned lock is reused.
        self.inner.lock().unwrap_or_else(PoisonError::into_inner)
    }

    /// Wake the wait (the next job read happens now).
    pub fn notify(&self, event: ImageEnhanceEvent) {
        let mut state = self.state();
        state.last = Some(event);
        state.token.cancel();
    }

    /// [`parse_image_enhance_event`] then [`notify`](Self::notify); false for
    /// other frames.
    pub fn notify_frame(&self, event_type: &str, payload: &Value) -> bool {
        match parse_image_enhance_event(event_type, payload) {
            Some(event) => {
                self.notify(event);
                true
            }
            None => false,
        }
    }

    /// The last event forwarded, if any.
    pub fn last_event(&self) -> Option<ImageEnhanceEvent> {
        self.state().last.clone()
    }

    /// Token of the next delay. A wake that came while no delay was running
    /// is returned once (already cancelled) and then replaced, so it ends
    /// exactly one delay.
    pub(crate) fn signal(&self) -> CancellationToken {
        let mut state = self.state();
        let token = state.token.clone();
        if token.is_cancelled() {
            state.token = CancellationToken::new();
        }
        token
    }
}

fn invalid_source(code: &'static str) -> ImageEnhanceError {
    ImageEnhanceError::InvalidSource { code }
}

fn image_content(head_content: &str) -> ImageEnhanceResult<Map<String, Value>> {
    let content = decode_object(head_content).ok_or(invalid_source("invalid_head_content"))?;
    let text = |name: &str| content.get(name).and_then(Value::as_str);
    // A finished generated image carries the skill that made it; the
    // `generated_image` id is only on the placeholder written while it runs.
    if text("app_id") != Some("images")
        || !matches!(
            text("skill_id"),
            Some("generate" | "generate_draft" | "modify" | "generated_image" | "upload")
        )
    {
        return Err(invalid_source("not_an_image"));
    }
    Ok(content)
}

fn valid_job_operation_id(value: &str) -> bool {
    uuid::Uuid::parse_str(value).is_ok_and(|id| {
        id.hyphenated().to_string() == value
            && (1..=8).contains(&id.get_version_num())
            && id.get_variant() == uuid::Variant::RFC4122
    })
}

/// The `POST /v1/images/enhance` body for the head version of an image.
///
/// The source is the `original` variant (else `full`) of the decrypted head
/// content, with its file key: the server needs it to read the picture and
/// never stores it. A V2 variant (`encryption: aes-gcm-nonce-prefixed-v1`)
/// sends no nonce; a legacy one sends the content's shared `aes_nonce`.
///
/// # Errors
/// `TeamUnavailable` for a Team scope; `InvalidSource` for a non-image head,
/// a missing or unsupported source file, or a malformed key/nonce;
/// `InvalidSource { code: "invalid_operation_id" }` for a non-UUID id.
pub(crate) fn start_body(
    head: &EmbedHead,
    head_content: &str,
    scope: &RevisionScope,
    operation_id: &str,
) -> ImageEnhanceResult<Value> {
    let team = match scope {
        RevisionScope::Chat { team_id, .. } | RevisionScope::Project { team_id, .. } => team_id,
    };
    if team.is_some() {
        return Err(ImageEnhanceError::TeamUnavailable);
    }
    if !valid_job_operation_id(operation_id) {
        return Err(invalid_source("invalid_operation_id"));
    }
    let content = image_content(head_content)?;
    let files = content.get("files").and_then(Value::as_object);
    let variant = files
        .and_then(|files| files.get("original").or_else(|| files.get("full")))
        .and_then(Value::as_object)
        .ok_or(invalid_source("source_missing"))?;
    let s3_key = variant
        .get("s3_key")
        .and_then(Value::as_str)
        .filter(|key| (1..=512).contains(&key.len()))
        .ok_or(invalid_source("source_missing"))?;
    let format = variant
        .get("format")
        .or_else(|| content.get("output_filetype"))
        .and_then(Value::as_str)
        .map(str::to_ascii_lowercase)
        .filter(|format| matches!(format.as_str(), "png" | "jpg" | "jpeg" | "webp"))
        .ok_or(invalid_source("unsupported_format"))?;
    let side = |name: &str| {
        variant
            .get(name)
            .and_then(Value::as_i64)
            .filter(|side| (1..=MAX_SOURCE_SIDE).contains(side))
            .ok_or(invalid_source("unsupported_size"))
    };
    let (width, height) = (side("width")?, side("height")?);
    let aes_key = content
        .get("aes_key")
        .and_then(Value::as_str)
        .filter(|key| key.len() == 44)
        .ok_or(invalid_source("invalid_source_key"))?;
    let mut source = json!({
        "s3_key": s3_key, "aes_key": aes_key, "format": format, "width": width, "height": height,
    });
    if variant.get("encryption").and_then(Value::as_str) == Some(MEDIA_ENCRYPTION_V2) {
        source["encryption"] = json!(MEDIA_ENCRYPTION_V2);
    } else {
        let nonce = content
            .get("aes_nonce")
            .and_then(Value::as_str)
            .filter(|nonce| nonce.len() == 16)
            .ok_or(invalid_source("invalid_source_nonce"))?;
        source["aes_nonce"] = json!(nonce);
    }
    Ok(json!({
        "operation_id": operation_id,
        "embed_id": head.embed_id,
        "scope": scope.wire(),
        "expected_version": head.version,
        "source": source,
    }))
}

fn encode_like(head_content: &str, content: Map<String, Value>) -> ImageEnhanceResult<String> {
    if !head_content.trim_start().starts_with('{') {
        let entries: Vec<(&str, Value)> = content
            .iter()
            .map(|(name, value)| (name.as_str(), value.clone()))
            .collect();
        if let Ok(toon) = toon_encode::encode_fields(&entries) {
            return Ok(toon);
        }
        // Deliberate: this TOON encoder has no tabular arrays. JSON is the
        // documented fallback format every content decoder reads first.
    }
    serde_json::to_string(&Value::Object(content)).map_err(|_| Error::Protocol.into())
}

/// Content of version N+1: the head content with the enhanced files, key,
/// model and `enhanced_from` of `image`. Everything else of the head (ref,
/// prompt, filename, provenance) is kept; `revised_from` of an assistant
/// revision is dropped because N+1 was not made from N-1. Encoded in the
/// head's own format (TOON, or JSON for a JSON head).
///
/// # Errors
/// `InvalidSource` for a head that is not an image.
pub(crate) fn enhanced_content(
    head_content: &str,
    image: &EnhancedImage,
) -> ImageEnhanceResult<Zeroizing<String>> {
    let mut content = image_content(head_content)?;
    content.remove("revised_from");
    for (name, value) in &image.fields {
        content.insert(name.clone(), value.clone());
    }
    content.insert("aes_key".into(), json!(image.aes_key.as_str()));
    content.insert("status".into(), json!("finished"));
    Ok(Zeroizing::new(encode_like(head_content, content)?))
}

/// Operation id of the version commit of Enhance job `operation_id`. It is
/// derived, not random, so every save attempt of one result names the same
/// commit and a second commit is recognised (`operation_payload_mismatch`).
pub fn enhance_revision_operation_id(operation_id: &str) -> String {
    format!("enhance-{operation_id}")
}

/// The user-revision request that saves a ready job as version N+1.
///
/// # Errors
/// `NotReady`/`Failed`/`Expired` for a job without a result; `VersionConflict`
/// when `head` is not the job's base version; `InvalidSource` for a non-image head.
pub(crate) fn enhance_revision_request(
    head: EmbedHead,
    head_content: &str,
    scope: RevisionScope,
    job: &EnhanceJob,
) -> ImageEnhanceResult<UserRevisionRequest> {
    let image = match (job.state, job.result()) {
        (EnhanceJobState::Ready, Some(image)) => image,
        _ => return Err(unsaved_job_error(job)),
    };
    if head.embed_id != job.embed_id {
        return Err(Error::Protocol.into());
    }
    if head.version != job.base_version {
        return Err(ImageEnhanceError::VersionConflict {
            current_version: Some(head.version),
        });
    }
    let content = enhanced_content(head_content, image)?;
    Ok(UserRevisionRequest {
        head,
        scope,
        action: EmbedUpdateAction::Enhance,
        content,
        text_preview: None,
        restored_from: None,
        files: Some(RevisionFiles::Enhance {
            operation_id: job.operation_id.clone(),
        }),
        media_index: Some(image.media_index.clone()),
        operation_id: Some(enhance_revision_operation_id(&job.operation_id)),
    })
}

/// The error for a job that cannot be saved now (not `ready`).
pub(crate) fn unsaved_job_error(job: &EnhanceJob) -> ImageEnhanceError {
    let operation_id = job.operation_id.clone();
    match job.state {
        EnhanceJobState::Failed => ImageEnhanceError::Failed {
            operation_id,
            code: job
                .error_code
                .clone()
                .unwrap_or_else(|| "enhance_failed".into()),
        },
        EnhanceJobState::Pending => ImageEnhanceError::NotReady { operation_id },
        _ => ImageEnhanceError::Expired { operation_id },
    }
}

/// True for a commit refusal that may mean "this result is already saved"
/// (a previous attempt committed it): the caller re-reads the job to decide.
pub(crate) fn may_be_already_saved(error: &UserRevisionError, job: &EnhanceJob) -> bool {
    match error {
        UserRevisionError::Refused { code } => matches!(
            *code,
            "operation_payload_mismatch" | "enhance_result_not_ready" | "enhance_version_mismatch"
        ),
        UserRevisionError::VersionConflict {
            current_revision, ..
        } => current_revision.is_none_or(|v| v == job.target_version),
        _ => false,
    }
}

/// IO of the job reads: the authenticated routes, the delay and the clock.
#[allow(async_fn_in_trait)] // Crate-internal seam; callers are generic, never `dyn`.
pub(crate) trait EnhanceIo {
    /// POST `body` to `/v1/images/enhance` (202 new job, 200 replay).
    async fn post_enhance(&mut self, body: &Value) -> ImageEnhanceResult<Value>;
    /// GET `/v1/images/enhance/{operation_id}`.
    async fn get_enhance(&mut self, operation_id: &str) -> ImageEnhanceResult<Value>;
    /// Wait `delay`, or less when `waker` is notified.
    async fn pause(&mut self, delay: Duration, waker: Option<&ImageEnhanceWaker>);
    /// Unix milliseconds.
    fn now_ms(&self) -> i64;
}

/// Start (or replay) the job. A lost answer is resent once: the server keys
/// the job by `operation_id`, so the resend returns the same job.
pub(crate) async fn start_job<I: EnhanceIo>(
    io: &mut I,
    body: &Value,
    operation_id: &str,
    embed_id: &str,
) -> ImageEnhanceResult<EnhanceJob> {
    let response = match io.post_enhance(body).await {
        Err(ImageEnhanceError::Transport(Error::Offline)) => io.post_enhance(body).await?,
        other => other?,
    };
    parse_job(&response, operation_id, Some(embed_id))
}

fn transient(error: &ImageEnhanceError) -> bool {
    matches!(
        error,
        ImageEnhanceError::Busy
            | ImageEnhanceError::RateLimited
            | ImageEnhanceError::Unavailable { .. }
            | ImageEnhanceError::Transport(Error::Offline)
    )
}

/// Read the job until it is ready or committed, within `deadline`.
///
/// Order: read now when `read_first` (resume), else pause first (right
/// after a start) -> pause with backoff (1.5 s, 2 s, 3 s, 5 s, then 8 s; a
/// waker notification ends a pause early) -> read. Busy, rate-limited,
/// unavailable and offline reads are retried until the deadline.
///
/// # Errors
/// `Failed`/`Expired` for a settled job without a result, `Timeout` at the
/// deadline (the job keeps running), any other read error at once.
pub(crate) async fn wait_job<I: EnhanceIo>(
    io: &mut I,
    operation_id: &str,
    embed_id: Option<&str>,
    waker: Option<&ImageEnhanceWaker>,
    deadline: Duration,
    read_first: bool,
) -> ImageEnhanceResult<EnhanceJob> {
    let deadline_ms = io
        .now_ms()
        .saturating_add(i64::try_from(deadline.as_millis()).unwrap_or(i64::MAX));
    let mut attempt = 0usize;
    let mut read = read_first;
    loop {
        if read {
            match io.get_enhance(operation_id).await {
                Ok(value) => {
                    let job = parse_job(&value, operation_id, embed_id)?;
                    match job.state {
                        EnhanceJobState::Ready | EnhanceJobState::Committed => return Ok(job),
                        EnhanceJobState::Failed | EnhanceJobState::Expired => {
                            return Err(unsaved_job_error(&job));
                        }
                        EnhanceJobState::Pending => {}
                    }
                }
                Err(error) if transient(&error) => {}
                Err(error) => return Err(error),
            }
        }
        read = true;
        let left = deadline_ms - io.now_ms();
        if left <= 0 {
            return Err(ImageEnhanceError::Timeout {
                operation_id: operation_id.to_owned(),
            });
        }
        let delay = POLL_DELAYS_MS[attempt.min(POLL_DELAYS_MS.len() - 1)].min(left as u64);
        attempt += 1;
        io.pause(Duration::from_millis(delay), waker).await;
    }
}

#[cfg(test)]
#[path = "image_enhance_tests.rs"]
mod tests;
