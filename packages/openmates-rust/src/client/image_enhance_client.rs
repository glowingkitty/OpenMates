//! Signed-in [`Client`] adapters of Image Enhance (shared core; spec
//! `feature.embed-user-edits`, `enhance.*`): the authenticated job routes with
//! typed refusals, the poll delay with WebSocket wake-ups, and the save of a
//! ready result through [`Client::commit_embed_user_revision`] (which writes
//! the chat event). Shells call [`Client::enhance_image`]; the lower steps
//! resume a job after a restart or a timeout.
use super::{
    DEFAULT_ENHANCE_DEADLINE, EnhanceIo, EnhanceJob, EnhanceJobState, ImageEnhanceError,
    ImageEnhanceResult, ImageEnhanceSaved, ImageEnhanceWaker, enhance_revision_request,
    may_be_already_saved, start_body, start_job, unsaved_job_error, wait_job,
};
use crate::client::embed_updated_event::EmbedEventIdentity;
use crate::client::embed_user_revision::{EmbedHead, RevisionScope};
use crate::client::embed_write::keys::decrypt_text;
use crate::client::{Client, now_ms, segment};
use crate::error::Error;
use reqwest::Method;
use serde_json::Value;
use std::time::Duration;
use zeroize::Zeroizing;

const START_PATH: &str = "/v1/images/enhance";

/// Job transport of the signed-in client.
struct ClientEnhanceIo<'a> {
    client: &'a mut Client,
}

impl ClientEnhanceIo<'_> {
    async fn send(
        &mut self,
        method: Method,
        path: &str,
        body: Option<Value>,
    ) -> ImageEnhanceResult<Value> {
        // The transport records a refusal for these routes only; clear an
        // older one so a network failure is never read as a refusal.
        self.client.image_enhance_refusal = None;
        let result = self.client.request(method, path, body).await;
        result.map_err(|error| match self.client.image_enhance_refusal.take() {
            Some(refusal) => refusal.into_error(),
            None => match error {
                Error::Invalid(_) => ImageEnhanceError::InvalidSource {
                    code: "invalid_request",
                },
                other => ImageEnhanceError::Transport(other),
            },
        })
    }
}

impl EnhanceIo for ClientEnhanceIo<'_> {
    async fn post_enhance(&mut self, body: &Value) -> ImageEnhanceResult<Value> {
        self.send(Method::POST, START_PATH, Some(body.clone()))
            .await
    }

    async fn get_enhance(&mut self, operation_id: &str) -> ImageEnhanceResult<Value> {
        let path = format!("{START_PATH}/{}", segment(operation_id));
        self.send(Method::GET, &path, None).await
    }

    async fn pause(&mut self, delay: Duration, waker: Option<&ImageEnhanceWaker>) {
        let sleep = crate::platform::time::sleep(delay);
        match waker {
            None => sleep.await,
            Some(waker) => {
                let token = waker.signal();
                let woken = token.cancelled();
                futures_util::future::select(std::pin::pin!(sleep), std::pin::pin!(woken)).await;
            }
        }
    }

    fn now_ms(&self) -> i64 {
        i64::try_from(now_ms()).unwrap_or(i64::MAX)
    }
}

impl Client {
    /// Plaintext of the cached head ciphertext, opened with the embed key.
    async fn enhance_head_content(
        &mut self,
        head: &EmbedHead,
    ) -> ImageEnhanceResult<Zeroizing<String>> {
        let key = match self.edit_embed_key(&head.embed_id).await {
            Ok(key) => key,
            Err(Error::Forbidden | Error::Protocol) => {
                return Err(ImageEnhanceError::KeyUnavailable);
            }
            Err(error) => return Err(error.into()),
        };
        Ok(decrypt_text(&head.encrypted_content, &key, None)?)
    }

    fn enhance_session(&self) -> ImageEnhanceResult<()> {
        // Both credential kinds: a web session has no native master key.
        self.require_credentials()?;
        self.verify_private_operation()?;
        Ok(())
    }

    /// Start Enhance of the head version of an image embed (or replay the job
    /// of `operation_id`). The source file and its key come from the cached,
    /// decrypted head; open the embed first. A fresh UUID is used when
    /// `operation_id` is `None`; keep the returned job's id to resume.
    ///
    /// # Errors
    /// [`ImageEnhanceError`]: `TeamUnavailable`, `ProjectContextRequired`
    /// (start it in Project scope), `InsufficientCredits`, `VersionConflict`
    /// (no charge), `InvalidSource`, `NotFound`, `RateLimited`, `Busy`,
    /// `OperationConflict`, `Unavailable`, `KeyUnavailable`, `Transport`.
    pub async fn start_image_enhance(
        &mut self,
        head: &EmbedHead,
        scope: &RevisionScope,
        operation_id: Option<&str>,
    ) -> ImageEnhanceResult<EnhanceJob> {
        self.enhance_session()?;
        let operation_id = operation_id
            .map(str::to_owned)
            .unwrap_or_else(|| uuid::Uuid::new_v4().to_string());
        let content = self.enhance_head_content(head).await?;
        let body = start_body(head, &content, scope, &operation_id)?;
        drop(content);
        start_job(
            &mut ClientEnhanceIo { client: self },
            &body,
            &operation_id,
            &head.embed_id,
        )
        .await
    }

    /// Read the job of `operation_id` now (after an `image_enhance_ready` or
    /// `image_enhance_failed` event, or on resume). Reading a ready result
    /// counts as its delivery on the server: it stays charged and can be
    /// saved until `expires_at`.
    ///
    /// # Errors
    /// `NotFound { code: "enhance_not_found" }`, `Busy`, `Transport`.
    pub async fn image_enhance_status(
        &mut self,
        operation_id: &str,
    ) -> ImageEnhanceResult<EnhanceJob> {
        self.enhance_session()?;
        let mut io = ClientEnhanceIo { client: self };
        let value = io.get_enhance(operation_id).await?;
        super::parse_job(&value, operation_id, None)
    }

    /// Wait until the job of `operation_id` is ready or committed, reading it
    /// with backoff until `deadline`. Forwarding the job's WebSocket events to
    /// `waker` makes the next read happen at once.
    ///
    /// # Errors
    /// `Failed` (nothing charged), `Expired`, `Timeout` (the job keeps
    /// running), and the read errors of [`Self::image_enhance_status`].
    pub async fn wait_image_enhance(
        &mut self,
        operation_id: &str,
        waker: Option<&ImageEnhanceWaker>,
        deadline: Duration,
    ) -> ImageEnhanceResult<EnhanceJob> {
        self.enhance_session()?;
        let mut io = ClientEnhanceIo { client: self };
        wait_job(&mut io, operation_id, None, waker, deadline, true).await
    }

    /// Save the result of Enhance job `operation_id` as version N+1 of the
    /// embed, where `head` is version N (the version the job started from)
    /// and `scope` the scope it was started in. Safe to repeat: the commit's
    /// operation id is derived from the job, and a result that an earlier
    /// attempt (or another device) already saved returns
    /// [`ImageEnhanceSaved::AlreadyCommitted`] instead of a second version.
    ///
    /// # Errors
    /// `NotReady`, `Failed`, `Expired`, `VersionConflict` (the head moved),
    /// `ScopeMismatch`, `ProjectContextRequired`, `KeyUnavailable`, and the
    /// commit's other refusals as `Revision`.
    pub async fn save_image_enhance_result(
        &mut self,
        head: EmbedHead,
        scope: RevisionScope,
        operation_id: &str,
        identity: Option<EmbedEventIdentity>,
    ) -> ImageEnhanceResult<ImageEnhanceSaved> {
        let job = self.image_enhance_status(operation_id).await?;
        self.save_enhance_job(head, scope, job, identity).await
    }

    async fn save_enhance_job(
        &mut self,
        head: EmbedHead,
        scope: RevisionScope,
        job: EnhanceJob,
        identity: Option<EmbedEventIdentity>,
    ) -> ImageEnhanceResult<ImageEnhanceSaved> {
        let already = |job: &EnhanceJob| ImageEnhanceSaved::AlreadyCommitted {
            operation_id: job.operation_id.clone(),
            version: job.target_version,
        };
        match job.state {
            EnhanceJobState::Committed => return Ok(already(&job)),
            EnhanceJobState::Ready => {}
            _ => return Err(unsaved_job_error(&job)),
        }
        if head.embed_id != job.embed_id {
            return Err(Error::Protocol.into());
        }
        let content = self.enhance_head_content(&head).await?;
        let request = enhance_revision_request(head, &content, scope, &job)?;
        drop(content);
        match self.commit_embed_user_revision(request, identity).await {
            Ok(outcome) => Ok(ImageEnhanceSaved::Committed {
                operation_id: job.operation_id,
                outcome: Box::new(outcome),
            }),
            Err(error) if may_be_already_saved(&error, &job) => {
                // Only the job knows whether an earlier attempt saved it.
                let latest = self.image_enhance_status(&job.operation_id).await?;
                if latest.state == EnhanceJobState::Committed {
                    Ok(already(&latest))
                } else {
                    Err(error.into())
                }
            }
            Err(error) => Err(error.into()),
        }
    }

    /// Enhance the head version of an image embed and save the result as the
    /// next version of the same embed: start -> wait (up to
    /// [`DEFAULT_ENHANCE_DEADLINE`]; forward the job's WebSocket events to
    /// `waker`) -> commit with action `enhance` -> chat event. `head` is the
    /// cached head row ([`EmbedHead::from_cached_row`]); `scope` is where the
    /// user pressed Enhance (Project scope for a Project file).
    /// `operation_id` is the job's idempotency key (a UUID): pass one the
    /// shell keeps (bindings do, since their errors carry only a code), or
    /// `None` for a fresh one.
    ///
    /// On `Timeout` or a lost save, keep the operation id (the one passed in,
    /// the one in the error, or from [`Self::start_image_enhance`]) and call
    /// [`Self::save_image_enhance_result`] later: a delivered result stays
    /// saveable for 24 hours and is never charged twice.
    ///
    /// # Errors
    /// The errors of [`Self::start_image_enhance`],
    /// [`Self::wait_image_enhance`] and [`Self::save_image_enhance_result`].
    pub async fn enhance_image(
        &mut self,
        head: EmbedHead,
        scope: RevisionScope,
        operation_id: Option<&str>,
        identity: Option<EmbedEventIdentity>,
        waker: Option<&ImageEnhanceWaker>,
    ) -> ImageEnhanceResult<ImageEnhanceSaved> {
        let started = self
            .start_image_enhance(&head, &scope, operation_id)
            .await?;
        let job = if started.is_settled() {
            started
        } else {
            let mut io = ClientEnhanceIo { client: self };
            wait_job(
                &mut io,
                &started.operation_id,
                Some(&started.embed_id),
                waker,
                DEFAULT_ENHANCE_DEADLINE,
                false,
            )
            .await?
        };
        self.save_enhance_job(head, scope, job, identity).await
    }
}
