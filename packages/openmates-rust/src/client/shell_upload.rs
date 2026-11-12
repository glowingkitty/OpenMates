//! Authenticated multipart upload for shell code that is not migrated yet
//! (Apple file, Project file and profile image uploads): the shell names an
//! allow-listed upload endpoint, a local file and the form fields; the core
//! builds the multipart body around the file (streamed from disk, never held
//! whole in memory), adds ITS refresh cookie and returns the buffered answer.
//! Same three phases as `shell_http.rs` (prepare, send without the client,
//! finish). The upload host only reads the refresh cookie and rotates none,
//! so no response cookie is applied. Temporary: plan
//! `apple-client-core-migration` step A6 deletes it. Native only. Spec
//! `client-core`.
use super::profile_upload::field_part;
use super::shell_http::{Binding, Received, invalid_text, read, response_headers};
use super::upload::{file_part_head, multipart_tail, upload_base_url};
use super::*;
use futures_util::{StreamExt, stream};
use reqwest::header::{CONTENT_LENGTH, CONTENT_TYPE, COOKIE};
use std::path::PathBuf;
use tokio::io::AsyncReadExt;

/// Largest uploaded file (the upload server's own limit, 100 MB).
pub const SHELL_UPLOAD_MAX_FILE: u64 = 100 * 1024 * 1024;
/// How long one upload may take, as the core's own uploads.
const UPLOAD_TIMEOUT: Duration = Duration::from_secs(10 * 60);
/// Read size of one streamed file chunk.
const CHUNK: usize = 64 * 1024;
/// Longest accepted filename, content type and field value (bytes).
const MAX_FILENAME: usize = 1024;
const MAX_CONTENT_TYPE: usize = 255;
const MAX_FIELD_VALUE: usize = 64 * 1024;

/// Endpoints of the upload service a shell may call.
const UPLOAD_PATHS: [&str; 3] = [
    "/v1/upload/file",
    "/v1/upload/profile-image",
    "/v1/upload/team-profile-image",
];

/// Text form fields the upload endpoints read; the file part is the core's.
const UPLOAD_FIELDS: [&str; 3] = ["chat_id", "encrypted_profile_image_metadata", "team_id"];

/// One shell upload. Nothing here is secret; the file stays on disk.
pub struct ShellUploadRequest {
    /// Absolute upload URL: an allow-listed endpoint on the configured API
    /// origin (self-hosted servers) or on the official upload host when the
    /// API is an `openmates.org` host (`localhost`: the local upload server).
    pub url: String,
    /// Absolute path of the file to send; read when the request is sent.
    pub file_path: PathBuf,
    /// Filename of the `file` part.
    pub filename: String,
    /// Content type of the `file` part.
    pub content_type: String,
    /// Text fields (`chat_id`, `team_id`, `encrypted_profile_image_metadata`),
    /// each at most once, sent before the file part.
    pub fields: Vec<(String, String)>,
}

/// An upload built from the current session; send it without the client.
pub struct PreparedShellUpload {
    request: crate::platform::http::RequestBuilder,
    file_path: PathBuf,
    head: Vec<u8>,
    tail: Vec<u8>,
    binding: Binding,
}

/// A sent upload; hand it back to [`Client::finish_shell_upload`].
pub struct SentShellUpload {
    binding: Binding,
    received: Result<Received>,
}

/// Origins a shell upload may go to: the API origin itself, and the
/// official upload host only for official API hosts, so a self-hosted
/// session's cookie never travels to another operator's host.
fn upload_origins(api: &url::Url) -> Vec<url::Origin> {
    let mut origins = vec![api.origin()];
    let host = api.host_str().unwrap_or_default();
    let official =
        host == "localhost" || host == "openmates.org" || host.ends_with(".openmates.org");
    if official && let Ok(upload) = url::Url::parse(upload_base_url(api)) {
        origins.push(upload.origin());
    }
    origins
}

/// The checked upload URL.
fn checked_url(api: &url::Url, raw: &str) -> Result<url::Url> {
    let url = url::Url::parse(raw).map_err(|_| Error::Invalid("Supply an absolute upload URL."))?;
    let shaped = matches!(url.scheme(), "http" | "https")
        && url.username().is_empty()
        && url.password().is_none()
        && url.query().is_none()
        && url.fragment().is_none();
    if !shaped {
        return Err(Error::Invalid(
            "Supply an upload URL without credentials, query or fragment.",
        ));
    }
    if !upload_origins(api).contains(&url.origin()) || !UPLOAD_PATHS.contains(&url.path()) {
        return Err(Error::Forbidden);
    }
    Ok(url)
}

/// Text fields first (sorted by name for a stable body), then the head of
/// the file part.
fn checked_head(request: &ShellUploadRequest, boundary: &str) -> Result<Vec<u8>> {
    if invalid_text(&request.filename, MAX_FILENAME) {
        return Err(Error::Invalid("Invalid upload filename."));
    }
    let content_type = &request.content_type;
    if invalid_text(content_type, MAX_CONTENT_TYPE) || !content_type.is_ascii() {
        return Err(Error::Invalid("Invalid upload content type."));
    }
    if !request.file_path.is_absolute() {
        return Err(Error::Invalid("The upload file path must be absolute."));
    }
    let mut fields: Vec<&(String, String)> = request.fields.iter().collect();
    fields.sort_by(|a, b| a.0.cmp(&b.0));
    if fields.windows(2).any(|pair| pair[0].0 == pair[1].0) {
        return Err(Error::Invalid("An upload field is repeated."));
    }
    let mut head = Vec::new();
    for (name, value) in fields {
        if !UPLOAD_FIELDS.contains(&name.as_str()) {
            return Err(Error::Invalid("This upload field is not supported."));
        }
        if value.len() > MAX_FIELD_VALUE || value.chars().any(char::is_control) {
            return Err(Error::Invalid("Invalid upload field value."));
        }
        head.extend_from_slice(field_part(boundary, name, value).as_bytes());
    }
    head.extend_from_slice(file_part_head(boundary, &request.filename, content_type).as_bytes());
    Ok(head)
}

impl Client {
    /// Build `request` with this client's session: only the refresh cookie
    /// is sent (as the core's own uploads), plus `Origin`, client identity
    /// and expected principal; the multipart body is fixed except the file
    /// bytes, which [`PreparedShellUpload::send`] streams. Invalidates the
    /// chat-list freshness proof as every shell write does.
    ///
    /// # Errors
    /// `Authentication` without a session, `Expired` for a lapsed pairing,
    /// `Forbidden` for browser credentials, an endpoint or host outside the
    /// allow-list, `Invalid` for a malformed URL, filename, content type,
    /// path or field, `Protocol` for unusable stored cookies.
    pub fn prepare_shell_upload(
        &mut self,
        request: ShellUploadRequest,
    ) -> Result<PreparedShellUpload> {
        if self.browser_cookies() {
            return Err(Error::Forbidden);
        }
        let binding = Binding::current(self)?;
        let url = checked_url(&self.base, &request.url)?;
        let boundary = format!("----OpenMatesFormBoundary{}", uuid::Uuid::new_v4().simple());
        let head = checked_head(&request, &boundary)?;
        let cookie = self.refresh_cookie()?;
        self.invalidate_chat_inventory_proofs();
        self.chat_list_freshness.invalidate();
        let mut builder = self
            .http
            .post(url)
            .timeout(UPLOAD_TIMEOUT)
            .header("X-OpenMates-SDK", self.options.identity.header())
            .header("Origin", self.app_url())
            .header("Accept", "application/json")
            .header(
                CONTENT_TYPE,
                format!("multipart/form-data; boundary={boundary}"),
            );
        if let Some(expected) = self.expected_request_principal()? {
            builder = builder.header("X-OpenMates-Expected-Principal", expected);
        }
        if let Some(cookie) = &cookie {
            builder = builder.header(COOKIE, cookie.as_str());
        }
        Ok(PreparedShellUpload {
            request: builder,
            file_path: request.file_path,
            head,
            tail: multipart_tail(&boundary).into_bytes(),
            binding,
        })
    }

    /// Accept the outcome of `sent`: every status except a redirect is
    /// returned as is, including 401 and 403 (the upload host's refusal does
    /// not sign the session out; the API's own session check does). No
    /// response cookie is applied (`credentials_changed` is always false).
    ///
    /// # Errors
    /// `Cancelled` when the session or generation changed since prepare or
    /// the send was cancelled; `Io` when the file could not be opened,
    /// `Invalid` when it is not a regular file or over
    /// [`SHELL_UPLOAD_MAX_FILE`]; `Offline` without a response (also when
    /// the file changed size while it was sent); `Forbidden` for a redirect;
    /// `Protocol` for an oversized response body.
    pub fn finish_shell_upload(&self, sent: SentShellUpload) -> Result<ShellHttpResponse> {
        let SentShellUpload { binding, received } = sent;
        if !binding.is_current(self) {
            return Err(Error::Cancelled);
        }
        let received = received?;
        if (300..400).contains(&received.status) {
            return Err(Error::Forbidden);
        }
        let headers = response_headers(&received.headers);
        Ok(ShellHttpResponse {
            status: received.status,
            headers,
            body: received.body?,
            credentials_changed: false,
        })
    }
}

/// The file as body chunks of exactly `length` bytes: a file that shrank
/// fails the body (the request then fails), one that grew is cut at the
/// announced length, so the body always matches its `Content-Length`.
fn file_chunks(
    file: tokio::fs::File,
    length: u64,
) -> impl futures_util::Stream<Item = std::io::Result<Vec<u8>>> {
    stream::try_unfold((file, length), |(mut file, remaining)| async move {
        if remaining == 0 {
            return Ok(None);
        }
        let size = usize::try_from(remaining).map_or(CHUNK, |left| left.min(CHUNK));
        let mut chunk = vec![0; size];
        let read = file.read(&mut chunk).await?;
        if read == 0 {
            return Err(std::io::Error::from(std::io::ErrorKind::UnexpectedEof));
        }
        chunk.truncate(read);
        Ok(Some((chunk, (file, remaining - read as u64))))
    })
}

impl PreparedShellUpload {
    /// Open the file, stream the body and read the whole response. `cancel`
    /// stops the upload at any point (opening, sending, reading).
    pub async fn send(self, cancel: &CancellationToken) -> SentShellUpload {
        let Self {
            request,
            file_path,
            head,
            tail,
            binding,
        } = self;
        let upload = async {
            let file = tokio::fs::File::open(&file_path)
                .await
                .map_err(|_| Error::Io)?;
            let metadata = file.metadata().await.map_err(|_| Error::Io)?;
            if !metadata.is_file() {
                return Err(Error::Invalid("The upload path is not a regular file."));
            }
            if metadata.len() > SHELL_UPLOAD_MAX_FILE {
                return Err(Error::Invalid("The upload file is too large."));
            }
            let total = head.len() as u64 + metadata.len() + tail.len() as u64;
            let body = stream::once(async move { Ok(head) })
                .chain(file_chunks(file, metadata.len()))
                .chain(stream::once(async move { Ok(tail) }));
            let response = request
                .header(CONTENT_LENGTH, total)
                .body(reqwest::Body::wrap_stream(body))
                .send()
                .await
                .map_err(|_| Error::Offline)?;
            Ok(read(response, cancel).await)
        };
        let received = tokio::select! {
            biased;
            () = cancel.cancelled() => Err(Error::Cancelled),
            received = upload => received,
        };
        SentShellUpload { binding, received }
    }
}
