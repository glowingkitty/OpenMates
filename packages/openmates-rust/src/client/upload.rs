//! Native upload pipeline (npm uploadService `uploadFile` /
//! `transcribeUploadedAudio`) and draft-embed storage (npm client
//! `storeDraftEmbeds`). Upload AES keys returned by the upload server are kept
//! zeroizing and only travel to the transcribe skill and into client-encrypted
//! embed content, exactly as npm does. Errors carry npm's user-facing text.
use super::transport::{send, wait};
use super::*;
use zeroize::Zeroizing;

#[path = "toon_encode.rs"]
pub(crate) mod toon_encode;

const UPLOAD_MAX_ATTEMPTS: usize = 3;
const UPLOAD_RETRY_DELAY: Duration = Duration::from_secs(2);
const LONG_REQUEST: Duration = Duration::from_secs(10 * 60);
const RECEIPT_WAIT: Duration = Duration::from_secs(30);
const MAX_RESPONSE: usize = 8 * 1024 * 1024;
const MAX_ERROR_BODY: usize = 4096;

/// A typed client failure, or a server/upload rejection with npm's message.
#[derive(Debug)]
pub enum UploadError {
    Client(Error),
    Rejected(String),
}
impl From<Error> for UploadError {
    fn from(error: Error) -> Self {
        Self::Client(error)
    }
}
impl std::fmt::Display for UploadError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Self::Client(error) => error.fmt(f),
            Self::Rejected(message) => f.write_str(message),
        }
    }
}

/// npm `UploadFileResponse` fields this client relies on.
pub struct UploadFileResponse {
    pub embed_id: String,
    pub filename: String,
    pub content_type: String,
    pub content_hash: String,
    pub files: serde_json::Map<String, Value>,
    pub s3_base_url: String,
    pub(crate) aes_key: Zeroizing<String>,
    pub(crate) aes_nonce: Zeroizing<String>,
    pub(crate) vault_wrapped_aes_key: Zeroizing<String>,
    /// npm `ai_detection` metadata (null when absent).
    pub ai_detection: Value,
    /// npm `deduplicated` (undefined becomes null).
    pub deduplicated: Value,
}

#[derive(serde::Deserialize)]
struct RawUpload {
    embed_id: String,
    #[serde(default)]
    filename: String,
    content_type: String,
    content_hash: String,
    files: serde_json::Map<String, Value>,
    s3_base_url: String,
    aes_key: String,
    aes_nonce: String,
    vault_wrapped_aes_key: String,
    #[serde(default)]
    ai_detection: Value,
    #[serde(default)]
    deduplicated: Value,
}

/// Parse a successful upload body; required fields missing fail closed.
pub fn parse_upload_response(bytes: &[u8]) -> Result<UploadFileResponse> {
    let raw: RawUpload = serde_json::from_slice(bytes).map_err(|_| Error::Protocol)?;
    if raw.embed_id.is_empty() {
        return Err(Error::Protocol);
    }
    Ok(UploadFileResponse {
        embed_id: raw.embed_id,
        filename: raw.filename,
        content_type: raw.content_type,
        content_hash: raw.content_hash,
        files: raw.files,
        s3_base_url: raw.s3_base_url,
        aes_key: Zeroizing::new(raw.aes_key),
        aes_nonce: Zeroizing::new(raw.aes_nonce),
        vault_wrapped_aes_key: Zeroizing::new(raw.vault_wrapped_aes_key),
        ai_detection: raw.ai_detection,
        deduplicated: raw.deduplicated,
    })
}

/// npm uploadFile non-OK status messages.
pub fn upload_status_message(status: u16, body: &str) -> String {
    match status {
        401 => "Authentication failed. Run `openmates login` to re-authenticate.".into(),
        413 => "File too large (maximum 100 MB).".into(),
        415 => "Unsupported file type.".into(),
        422 if body.contains("malware") => "File rejected: malware detected.".into(),
        422 if body.contains("content_safety") => "File rejected: content safety violation.".into(),
        422 => format!("Upload validation failed: {body}"),
        429 => "Upload rate limit exceeded. Try again in a minute.".into(),
        _ => format!("Upload failed (HTTP {status})."),
    }
}

/// npm `getUploadUrl`: only a `localhost` API uses the local upload server.
pub fn upload_base_url(api: &url::Url) -> &'static str {
    if api.host_str() == Some("localhost") {
        "http://localhost:8001"
    } else {
        "https://upload.openmates.org"
    }
}

/// npm `getUploadOrigin`.
pub fn upload_origin(api: &url::Url) -> String {
    match api.host_str() {
        Some("localhost") => "http://localhost:5173".into(),
        // npm uses `url.hostname`, so a port is not carried over.
        Some(host) if host.starts_with("api.") => format!("{}://app.{}", api.scheme(), &host[4..]),
        _ => "https://app.openmates.org".into(),
    }
}

/// One `file` part, encoded like the WHATWG FormData serializer.
pub fn multipart_body(boundary: &str, filename: &str, mime: &str, bytes: &[u8]) -> Vec<u8> {
    let name = filename
        .replace('"', "%22")
        .replace('\r', "%0D")
        .replace('\n', "%0A");
    let mut body = format!(
        "--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"{name}\"\r\nContent-Type: {mime}\r\n\r\n"
    )
    .into_bytes();
    body.extend_from_slice(bytes);
    body.extend_from_slice(format!("\r\n--{boundary}--\r\n").as_bytes());
    body
}

/// npm `AudioTranscriptionData`; each field is the server value or null.
#[derive(Clone, Debug, PartialEq)]
pub struct AudioTranscription {
    pub transcript: Value,
    pub transcript_original: Value,
    pub transcript_corrected: Value,
    pub use_corrected: Value,
    pub correction_model: Value,
    pub model: Value,
    pub waveform: Value,
}

fn message_or(value: &Value, fallback: &str) -> String {
    value
        .as_str()
        .map(str::to_owned)
        .unwrap_or_else(|| fallback.to_owned())
}

/// npm transcription result selection and error messages.
pub fn parse_transcription(
    data: &Value,
    request_id: &str,
) -> std::result::Result<AudioTranscription, String> {
    if data["success"] == Value::Bool(false) {
        return Err(message_or(&data["error"], "Transcription failed."));
    }
    let groups = data["data"]["results"].as_array();
    let group = groups
        .and_then(|g| {
            g.iter()
                .find(|item| item["id"].as_str() == Some(request_id))
        })
        .or_else(|| groups.and_then(|g| g.first()));
    let result = group
        .and_then(|g| g["results"].as_array())
        .and_then(|r| r.first());
    let Some(result) = result else {
        let fallback = "Transcription response did not include a result.";
        return Err(group
            .map(|g| message_or(&g["error"], fallback))
            .unwrap_or_else(|| fallback.into()));
    };
    if let Some(error) = result["error"].as_str().filter(|e| !e.is_empty()) {
        return Err(error.to_owned());
    }
    let field = |name: &str| result.get(name).cloned().unwrap_or(Value::Null);
    Ok(AudioTranscription {
        transcript: field("transcript"),
        transcript_original: field("transcript_original"),
        transcript_corrected: field("transcript_corrected"),
        use_corrected: field("use_corrected"),
        correction_model: field("correction_model"),
        model: field("model"),
        waveform: field("waveform"),
    })
}

/// npm non-OK transcription message: `detail ?? error ?? status text`.
pub fn transcription_error(status: u16, body: &[u8]) -> String {
    let fallback = format!("Transcription failed (HTTP {status}).");
    match serde_json::from_slice::<Value>(body) {
        Ok(data) => data["detail"]
            .as_str()
            .or_else(|| data["error"].as_str())
            .map(str::to_owned)
            .unwrap_or(fallback),
        Err(_) => fallback,
    }
}

/// npm: `files.original.s3_key ?? Object.values(files)[0].s3_key`.
pub fn audio_s3_key(files: &serde_json::Map<String, Value>) -> Option<&str> {
    files
        .get("original")
        .and_then(|f| f["s3_key"].as_str())
        .or_else(|| files.values().next().and_then(|f| f["s3_key"].as_str()))
}

/// A prepared client-side embed stored before the draft references it.
pub struct DraftEmbed {
    pub embed_id: String,
    pub kind: String,
    pub content: Zeroizing<String>,
    pub text_preview: String,
    pub status: String,
    pub content_hash: Option<String>,
}

async fn read_body(response: &mut reqwest::Response, limit: usize) -> Result<Zeroizing<Vec<u8>>> {
    let mut bytes = Zeroizing::new(Vec::new());
    while let Some(chunk) = response.chunk().await.map_err(|_| Error::Offline)? {
        if bytes.len() + chunk.len() > limit {
            return Err(Error::Protocol);
        }
        bytes.extend_from_slice(&chunk);
    }
    Ok(bytes)
}

impl Client {
    pub(super) fn refresh_cookie(&self) -> Result<Option<Zeroizing<String>>> {
        self.require_session()?;
        match self.cookies.get("auth_refresh_token") {
            Some(value) => {
                let single = BTreeMap::from([("auth_refresh_token".to_owned(), value.clone())]);
                Ok(Some(Zeroizing::new(transport::cookie_header(&single)?)))
            }
            None => Ok(None),
        }
    }
    fn check_not_cancelled(&self) -> Result<()> {
        if self.operation_cancel.is_cancelled() {
            Err(Error::Cancelled)
        } else {
            Ok(())
        }
    }

    /// npm `uploadFile` with already prepared (sanitized) bytes.
    pub async fn upload_file_bytes(
        &mut self,
        filename: &str,
        bytes: &[u8],
        mime: &str,
    ) -> std::result::Result<UploadFileResponse, UploadError> {
        let cookie = self.refresh_cookie()?;
        let url = format!("{}/v1/upload/file", upload_base_url(&self.base));
        let origin = upload_origin(&self.base);
        let boundary = format!("----OpenMatesFormBoundary{}", uuid::Uuid::new_v4().simple());
        let body = Zeroizing::new(multipart_body(&boundary, filename, mime, bytes));
        let mut response = None;
        for attempt in 1..=UPLOAD_MAX_ATTEMPTS {
            self.check_not_cancelled()?;
            let mut request = self
                .http
                .post(&url)
                .timeout(LONG_REQUEST)
                .header("Origin", &origin)
                .header(
                    "Content-Type",
                    format!("multipart/form-data; boundary={boundary}"),
                )
                .body(body.to_vec());
            if let Some(cookie) = &cookie {
                request = request.header(reqwest::header::COOKIE, cookie.as_str());
            }
            match request.send().await {
                Ok(sent) => {
                    response = Some(sent);
                    break;
                }
                Err(_) if attempt < UPLOAD_MAX_ATTEMPTS => {
                    tokio::time::sleep(UPLOAD_RETRY_DELAY).await
                }
                Err(_) => {}
            }
        }
        let mut response = response.ok_or(Error::Offline)?;
        let status = response.status();
        if !status.is_success() {
            let text = if status.as_u16() == 422 {
                // npm `response.text().catch(() => "")`: an unreadable 422 body
                // still yields the validation message, just without detail.
                let raw = read_body(&mut response, MAX_RESPONSE)
                    .await
                    .unwrap_or_default();
                let raw = &raw[..raw.len().min(MAX_ERROR_BODY)];
                String::from_utf8_lossy(raw).into_owned()
            } else {
                String::new()
            };
            return Err(UploadError::Rejected(upload_status_message(
                status.as_u16(),
                &text,
            )));
        }
        let bytes = read_body(&mut response, MAX_RESPONSE).await?;
        Ok(parse_upload_response(&bytes)?)
    }

    /// npm `transcribeUploadedAudio` (`POST /v1/apps/audio/skills/transcribe`).
    pub async fn transcribe_uploaded_audio(
        &mut self,
        upload: &UploadFileResponse,
        filename: &str,
        chat_id: Option<&str>,
        request_id: &str,
    ) -> std::result::Result<AudioTranscription, UploadError> {
        let s3_key = audio_s3_key(&upload.files).ok_or_else(|| {
            UploadError::Rejected("Upload succeeded but no audio file key was returned.".into())
        })?;
        let cookie = self.refresh_cookie()?;
        let mut item = json!({
            "id": request_id,
            "embed_id": upload.embed_id,
            "s3_key": s3_key,
            "s3_base_url": upload.s3_base_url,
            "aes_key": upload.aes_key.as_str(),
            "aes_nonce": upload.aes_nonce.as_str(),
            "vault_wrapped_aes_key": upload.vault_wrapped_aes_key.as_str(),
            "filename": filename,
            "mime_type": upload.content_type,
        });
        if let Some(chat) = chat_id {
            item["chat_id"] = json!(chat);
        }
        let body = Zeroizing::new(json!({"requests":[item]}).to_string());
        self.check_not_cancelled()?;
        let mut request = self
            .http
            .post(self.url("/v1/apps/audio/skills/transcribe")?)
            .timeout(LONG_REQUEST)
            .header("Accept", "application/json")
            .header("Content-Type", "application/json")
            .body(body.as_bytes().to_vec());
        if let Some(cookie) = &cookie {
            request = request.header(reqwest::header::COOKIE, cookie.as_str());
        }
        let mut response = request.send().await.map_err(|_| Error::Offline)?;
        let status = response.status();
        let bytes = read_body(&mut response, MAX_RESPONSE).await?;
        if !status.is_success() {
            return Err(UploadError::Rejected(transcription_error(
                status.as_u16(),
                &bytes,
            )));
        }
        let data: Value = serde_json::from_slice(&bytes).map_err(|_| Error::Protocol)?;
        parse_transcription(&data, request_id).map_err(UploadError::Rejected)
    }

    /// npm `storeDraftEmbeds`: each embed key is wrapped with the master key
    /// only (no chat key yet), then embed and key wrapper receipts are awaited.
    pub async fn store_draft_embeds(
        &mut self,
        chat_id: &str,
        embeds: &[DraftEmbed],
    ) -> std::result::Result<(), UploadError> {
        let master = self.require_session()?.master_key.clone();
        self.check_not_cancelled()?;
        let mut ws = self.socket_with_task_jobs(false).await?;
        let owner = self
            .user
            .get("id")
            .or_else(|| self.user.get("user_id"))
            .and_then(Value::as_str)
            .filter(|id| !id.is_empty())
            .map(str::to_owned);
        let result = match owner {
            None => Err(UploadError::Client(Error::Invalid(
                "Authenticated user identity is required to store IdeaBucket embeds.",
            ))),
            Some(owner) => store_each(&mut ws, chat_id, &owner, &master, embeds).await,
        };
        let _ = ws.close(None).await;
        result
    }
}

async fn store_each(
    ws: &mut transport::Socket,
    chat_id: &str,
    owner: &str,
    master: &[u8; 32],
    embeds: &[DraftEmbed],
) -> std::result::Result<(), UploadError> {
    let message_id = uuid::Uuid::new_v4().to_string();
    let (chat_hash, message_hash, user_hash) =
        (sha256(chat_id), sha256(&message_id), sha256(owner));
    for embed in embeds {
        let key = crypto::random_key();
        let seconds = now_ms() / 1000;
        let request = uuid::Uuid::new_v4().to_string();
        let mut payload = json!({
            "request_id": request,
            "embed_id": embed.embed_id,
            "encrypted_type": crypto::server_fields::encrypt_text(&embed.kind, &key, &[])?,
            "encrypted_content": crypto::server_fields::encrypt_text(&embed.content, &key, &[])?,
            "encrypted_text_preview": crypto::server_fields::encrypt_text(&embed.text_preview, &key, &[])?,
            "status": embed.status,
            "hashed_chat_id": chat_hash,
            "hashed_message_id": message_hash,
            "hashed_user_id": user_hash,
            "created_at": seconds,
            "updated_at": seconds,
        });
        if let Some(hash) = &embed.content_hash {
            payload["content_hash"] = json!(hash);
        }
        send(ws, "store_embed", payload).await?;
        let stored = crate::platform::time::timeout(
            RECEIPT_WAIT,
            wait(ws, "store_embed_confirmed", "request_id", &request),
        )
        .await
        .map_err(|_| Error::Offline)??;
        let stored = stored.get("payload").unwrap_or(&stored);
        if stored["embed_id"].as_str() != Some(embed.embed_id.as_str()) {
            return Err(Error::Protocol.into());
        }
        let keys_request = uuid::Uuid::new_v4().to_string();
        let wrapper = json!([{
            "hashed_embed_id": sha256(&embed.embed_id),
            "key_type": "master",
            "hashed_chat_id": null,
            "encrypted_embed_key": crypto::server_fields::encrypt_bytes(key.as_ref(), master, &[])?,
            "hashed_user_id": user_hash,
            "created_at": seconds,
        }]);
        send(
            ws,
            "store_embed_keys",
            json!({"request_id": keys_request, "keys": wrapper}),
        )
        .await?;
        let receipt = crate::platform::time::timeout(
            RECEIPT_WAIT,
            wait(
                ws,
                "store_embed_keys_confirmed",
                "request_id",
                &keys_request,
            ),
        )
        .await
        .map_err(|_| Error::Offline)??;
        let receipt = receipt.get("payload").unwrap_or(&receipt);
        if receipt["failed_count"] != 0 || receipt["created_count"] != 1 {
            return Err(UploadError::Rejected(format!(
                "IdeaBucket embed {} key wrappers were not durably stored.",
                embed.embed_id
            )));
        }
    }
    Ok(())
}

#[cfg(test)]
#[path = "upload_tests.rs"]
mod tests;
