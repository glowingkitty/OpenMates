//! Authenticated multipart upload on `ViewModelCore` for Swift uploads that
//! are not migrated yet (chat file, Project file, account and team profile
//! image): Swift prepares the (metadata-stripped) file on disk and names the
//! endpoint and form fields; the core sends it with its own session
//! (`Client::prepare_shell_upload` / `finish_shell_upload`, refresh cookie
//! only, allow-listed hosts) and returns the buffered answer. The actor lock
//! is held only to prepare and to check the session afterwards. Temporary
//! transport: plan `apple-client-core-migration` step A6 deletes it. Spec
//! `client-core`.
use crate::CoreError;
use crate::core::CoreCancellation;
use crate::view_core::{Shared, ViewModelCore};
use crate::view_http::{HttpFieldRecord, HttpResponseRecord, response_record};
use openmates_sdk::{
    client::{ShellHttpResponse, ShellUploadRequest},
    error::{Error, Result},
    view_model::ViewHost,
};
use std::path::PathBuf;
use std::sync::Arc;
use tokio_util::sync::CancellationToken;

/// One upload of a local file to the upload service.
#[derive(Clone, Debug, PartialEq, Eq, uniffi::Record)]
pub struct UploadRequestRecord {
    /// Absolute URL of `/v1/upload/file`, `/v1/upload/profile-image` or
    /// `/v1/upload/team-profile-image` on the configured API origin or, for
    /// an official API host, on the official upload host. Other hosts or
    /// paths are refused.
    pub url: String,
    /// Absolute path of the file to send (at most 100 MB). The core reads it
    /// while sending; Swift keeps it until the call returns, then deletes it.
    pub file_path: String,
    /// Filename of the `file` part (exact, including relative Project paths).
    pub filename: String,
    /// Content type of the `file` part.
    pub content_type: String,
    /// `chat_id`, `team_id`, `encrypted_profile_image_metadata`, each at most
    /// once.
    pub fields: Vec<HttpFieldRecord>,
}

impl Shared {
    async fn upload_file(
        &self,
        request: ShellUploadRequest,
        cancel: CancellationToken,
    ) -> Result<ShellHttpResponse> {
        let prepared = {
            let mut host = self.host.lock().await;
            let host = host.as_mut().ok_or(Error::Authentication)?;
            host.core_mut().client_mut().prepare_shell_upload(request)?
        };
        let sent = prepared.send(&cancel).await;
        let mut guard = self.host.lock().await;
        // Signed out meanwhile: the answer belongs to no session any more.
        let host = guard.as_mut().ok_or(Error::Authentication)?;
        let finished = host.core().client().finish_shell_upload(sent);
        self.settle_auth(&mut guard, finished).await
    }
}

#[uniffi::export]
impl ViewModelCore {
    /// Upload `request`'s file with the core's session and return the
    /// server's answer (non-2xx statuses, including 401, are returned, not
    /// thrown, and do not sign out). Several uploads may run at once; each
    /// waits for a running command only to prepare and to finish. No
    /// progress is reported.
    ///
    /// # Errors
    /// `Authentication` while signed out (also when signed out during the
    /// upload); `Forbidden` for a host or endpoint outside the allow-list or
    /// a redirect; `Invalid` for a malformed URL, filename, content type,
    /// field, a relative path, a file that is not a regular file or is over
    /// 100 MB; `Io` when the file cannot be opened; `Offline` without a
    /// response; `Protocol` for an oversized response; `Cancelled` when
    /// `cancellation` fired or the session changed meanwhile.
    pub async fn upload_file(
        &self,
        request: UploadRequestRecord,
        cancellation: Option<Arc<CoreCancellation>>,
    ) -> std::result::Result<HttpResponseRecord, CoreError> {
        let UploadRequestRecord {
            url,
            file_path,
            filename,
            content_type,
            fields,
        } = request;
        let request = ShellUploadRequest {
            url,
            file_path: PathBuf::from(file_path),
            filename,
            content_type,
            fields: fields.into_iter().map(|f| (f.name, f.value)).collect(),
        };
        let (shared, token) = (self.shared.clone(), self.detached(cancellation));
        let response = self
            .run(async move { shared.upload_file(request, token).await })
            .await?;
        Ok(response_record(response))
    }
}
