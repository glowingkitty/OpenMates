//! Saves one voice-call source frame (camera or screen JPEG the server asked
//! for with `voice_source_frame`) as an owner-encrypted `images-image` embed of
//! the call's chat. Shared core for the native shells (Apple, CLI); mirrors
//! `frontend/packages/ui/src/services/voiceCallVisuals.ts`
//! (`persistCallSourceFrame` / `persistSource`). Spec: `client-core`.
//!
//! Invariants: the embed key is derived from the chat key
//! (`derive_embed_key`, HKDF) and wrapped twice (master + chat) exactly like
//! the web writer; type, content and preview are sealed with that key (empty
//! AAD); team and Direct chats are refused before any upload; the pure steps
//! (`validate_frame`, `refuse_chat`, `prepare_store`) hold every wire shape so
//! tests need no network.
use super::embed_write::keys::{self, NonceSource, OsNonces};
use super::transport::{send, wait};
use super::upload::{UploadError, UploadFileResponse, toon_encode};
use super::*;
use base64::{
    Engine as _,
    alphabet::STANDARD as STANDARD_ALPHABET,
    engine::{DecodePaddingMode, GeneralPurpose, GeneralPurposeConfig},
};
use zeroize::Zeroizing;

/// Longest accepted base64 `data` (characters), as the web writer.
const MAX_DATA_CHARS: usize = 6_000_000;
/// Longest accepted frame id.
const MAX_FRAME_ID: usize = 240;
/// Largest integer JavaScript represents exactly (`Number.isSafeInteger`).
const MAX_SAFE_INTEGER: i64 = 9_007_199_254_740_991;
/// How long a store receipt may take.
const RECEIPT_WAIT: Duration = Duration::from_secs(30);

/// Which source the frame came from; the wire value is `camera` or `screen`.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum CallSourceKind {
    /// The device camera (the web default when no source is given).
    Camera,
    /// A screen share.
    Screen,
}

impl CallSourceKind {
    /// The wire / embed-content value.
    pub fn as_str(self) -> &'static str {
        match self {
            Self::Camera => "camera",
            Self::Screen => "screen",
        }
    }
}

/// One `voice_source_frame` answer to persist.
#[derive(Clone, Debug, PartialEq)]
pub struct CallSourceFrame {
    /// Call the frame belongs to (non-empty).
    pub call_id: String,
    /// Chat that receives the image embed (non-empty).
    pub chat_id: String,
    /// Message the embed attaches to (non-empty; only its hash is sent).
    pub message_id: String,
    /// Frame id: 1..=240 characters of `A-Za-z0-9_-`.
    pub frame_id: String,
    /// Base64 JPEG exactly as the server sent it (at most 6,000,000 chars).
    pub data: String,
    /// Capture time in seconds (finite).
    pub captured_at: f64,
    /// Server creation time (safe integer; validated, not stored).
    pub created_at: i64,
    /// Camera or screen.
    pub source: CallSourceKind,
}

/// Reference the voice pipeline sends back so the model can cite the image
/// (`VoiceArtifactReference` of type `image`).
#[derive(Clone, Debug, PartialEq)]
pub struct CallSourceReference {
    /// Embed id assigned by the upload server.
    pub embed_id: String,
    /// Echo of the frame id.
    pub source_frame_id: String,
    /// Echo of the capture time.
    pub captured_at: f64,
    /// Echo of the call id.
    pub source_call_id: String,
    /// Echo of the source kind.
    pub source: CallSourceKind,
}

/// Why a source frame was not persisted.
#[derive(Debug, PartialEq)]
pub enum CallSourceError {
    /// Ids, base64, size, timestamps or the JPEG signature are invalid.
    InvalidFrame,
    /// Team, Direct, unknown or keyless chat (web: "Call source chat unavailable").
    ChatUnavailable,
    /// The deduplicated upload's existing embed key could not be read.
    ExistingKeyUnavailable,
    /// The server did not confirm the encrypted store (web: "awaiting encrypted sync").
    AwaitingSync,
    /// The upload server rejected the file; carries its user-facing message.
    Rejected(String),
    /// A typed core failure (session, transport, crypto, cancellation).
    Client(Error),
}

impl std::fmt::Display for CallSourceError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Self::InvalidFrame => f.write_str("Invalid call source frame"),
            Self::ChatUnavailable => f.write_str("Call source chat unavailable"),
            Self::ExistingKeyUnavailable => f.write_str("Existing call source key unavailable"),
            Self::AwaitingSync => f.write_str("Call source awaiting encrypted sync"),
            Self::Rejected(message) => f.write_str(message),
            Self::Client(error) => error.fmt(f),
        }
    }
}

impl From<Error> for CallSourceError {
    fn from(error: Error) -> Self {
        Self::Client(error)
    }
}

impl From<UploadError> for CallSourceError {
    fn from(error: UploadError) -> Self {
        match error {
            UploadError::Client(error) => Self::Client(error),
            UploadError::Rejected(message) => Self::Rejected(message),
        }
    }
}

impl From<CallSourceError> for Error {
    /// Collapse to the shell error envelope: bad frames are `Invalid`, chat
    /// and key refusals `Forbidden`, an unconfirmed store `Offline`, an
    /// upload rejection `Protocol`.
    fn from(error: CallSourceError) -> Self {
        match error {
            CallSourceError::InvalidFrame => Error::Invalid("Invalid call source frame"),
            CallSourceError::ChatUnavailable | CallSourceError::ExistingKeyUnavailable => {
                Error::Forbidden
            }
            CallSourceError::AwaitingSync => Error::Offline,
            CallSourceError::Rejected(_) => Error::Protocol,
            CallSourceError::Client(error) => error,
        }
    }
}

/// Check every frame field and return the decoded JPEG bytes.
///
/// # Errors
/// `InvalidFrame` for an empty id, a frame id outside `A-Za-z0-9_-{1,240}`,
/// a non-finite capture time, an unsafe `created_at`, empty/oversized/
/// non-base64 data or bytes that do not start with the JPEG signature.
pub fn validate_frame(frame: &CallSourceFrame) -> std::result::Result<Zeroizing<Vec<u8>>, CallSourceError> {
    let id_ok = (1..=MAX_FRAME_ID).contains(&frame.frame_id.len())
        && frame
            .frame_id
            .bytes()
            .all(|byte| byte.is_ascii_alphanumeric() || byte == b'_' || byte == b'-');
    let trimmed = frame.data.trim_end_matches('=');
    let pad = frame.data.len() - trimmed.len();
    let data_ok = !trimmed.is_empty()
        && frame.data.len() <= MAX_DATA_CHARS
        && pad <= 2
        && trimmed
            .bytes()
            .all(|byte| byte.is_ascii_alphanumeric() || byte == b'+' || byte == b'/');
    if frame.call_id.is_empty()
        || frame.chat_id.is_empty()
        || frame.message_id.is_empty()
        || !id_ok
        || !frame.captured_at.is_finite()
        || frame.created_at.abs() > MAX_SAFE_INTEGER
        || !data_ok
    {
        return Err(CallSourceError::InvalidFrame);
    }
    // `atob` accepts missing padding and stray trailing bits; match it.
    let engine = GeneralPurpose::new(
        &STANDARD_ALPHABET,
        GeneralPurposeConfig::new()
            .with_decode_padding_mode(DecodePaddingMode::Indifferent)
            .with_decode_allow_trailing_bits(true),
    );
    let bytes = Zeroizing::new(
        engine
            .decode(trimmed)
            .map_err(|_| CallSourceError::InvalidFrame)?,
    );
    if bytes.len() < 3 || bytes[..3] != [0xff, 0xd8, 0xff] {
        return Err(CallSourceError::InvalidFrame);
    }
    Ok(bytes)
}

/// Refuse team and Direct chat rows (and anything else the web refuses).
///
/// # Errors
/// `ChatUnavailable` for a row with a team id, or `chat_visibility: direct`.
pub fn refuse_chat(row: &Value) -> std::result::Result<(), CallSourceError> {
    let team = ["team_id", "hashed_team_id"]
        .iter()
        .any(|field| row.get(*field).and_then(Value::as_str).is_some_and(|v| !v.is_empty()));
    if team || text(row, "chat_visibility") == "direct" {
        return Err(CallSourceError::ChatUnavailable);
    }
    Ok(())
}

/// TOON content of the image embed (field order as the web `encode` call).
///
/// # Errors
/// `Protocol` when a field cannot be encoded.
pub fn source_content(
    upload: &UploadFileResponse,
    frame: &CallSourceFrame,
    filename: &str,
    byte_len: usize,
) -> Result<Zeroizing<String>> {
    let source = frame.source.as_str();
    let fields = [
        ("app_id", json!("images")),
        ("skill_id", json!("upload")),
        ("type", json!("image")),
        ("status", json!("finished")),
        ("filename", json!(filename)),
        ("file_size", json!(byte_len)),
        ("file_type", json!("image/jpeg")),
        ("content_hash", json!(upload.content_hash)),
        ("s3_base_url", json!(upload.s3_base_url)),
        ("files", Value::Object(upload.files.clone())),
        ("aes_key", json!(upload.aes_key.as_str())),
        ("aes_nonce", json!(upload.aes_nonce.as_str())),
        ("vault_wrapped_aes_key", json!(upload.vault_wrapped_aes_key.as_str())),
        ("ai_detection", upload.ai_detection.clone()),
        ("source_frame_id", json!(frame.frame_id)),
        ("captured_at", json!(frame.captured_at)),
        ("source", json!(source)),
        ("source_call_id", json!(frame.call_id)),
    ];
    toon_encode::encode_fields(&fields).map(Zeroizing::new)
}

/// The `store_embed` payload and its two key wrappers, ready to send.
pub struct PreparedSourceStore {
    /// `store_embed` payload (no `request_id` yet).
    pub payload: Value,
    /// Master and chat wrappers for `store_embed_keys`.
    pub keys: Vec<Value>,
}

/// Seal the embed fields with the chat-derived key and build the wrappers.
/// `master_wrapped` is the embed key wrapped with the master key (async, so
/// the caller supplies it).
///
/// # Errors
/// `Crypto` on derivation or sealing failure; `Protocol` for unencodable content.
#[allow(clippy::too_many_arguments)] // every value is a distinct wire input
pub fn prepare_store(
    upload: &UploadFileResponse,
    frame: &CallSourceFrame,
    byte_len: usize,
    chat_key: &[u8; 32],
    master_wrapped: impl FnOnce(&[u8; 32]) -> Result<String>,
    owner_id: &str,
    now_seconds: i64,
    nonces: &mut impl NonceSource,
) -> Result<PreparedSourceStore> {
    let filename = format!("call-source-{}.jpg", frame.frame_id);
    let content = source_content(upload, frame, &filename, byte_len)?;
    let key = keys::derive_embed_key(chat_key, &upload.embed_id)?;
    let (chat_hash, user_hash, embed_hash) = (
        keys::hash_id(&frame.chat_id),
        keys::hash_id(owner_id),
        keys::hash_id(&upload.embed_id),
    );
    let master = master_wrapped(&key)?;
    let chat_wrapped = keys::wrap_key(&key, chat_key, nonces)?;
    let wrapper = |kind: &str, chat: Option<&str>, wrapped: String| {
        json!({"hashed_embed_id": embed_hash, "key_type": kind, "hashed_chat_id": chat,
            "encrypted_embed_key": wrapped, "hashed_user_id": user_hash, "created_at": now_seconds})
    };
    let payload = json!({
        "embed_id": upload.embed_id,
        "chat_id": frame.chat_id,
        "encrypted_type": keys::encrypt_text("images-image", &key, None, nonces)?,
        "encrypted_content": keys::encrypt_text(&content, &key, None, nonces)?,
        "encrypted_text_preview": keys::encrypt_text(&filename, &key, None, nonces)?,
        "status": "finished",
        "hashed_chat_id": chat_hash,
        "hashed_message_id": keys::hash_id(&frame.message_id),
        "hashed_user_id": user_hash,
        "content_hash": upload.content_hash,
        "is_private": true,
        "is_shared": false,
        "created_at": now_seconds,
        "updated_at": now_seconds,
    });
    Ok(PreparedSourceStore {
        payload,
        keys: vec![
            wrapper("master", None, master),
            wrapper("chat", Some(&chat_hash), chat_wrapped),
        ],
    })
}

/// Send `payload` as `kind`, wait for its `request_id` receipt.
async fn send_confirmed(
    ws: &mut transport::Socket,
    kind: &str,
    receipt: &str,
    mut payload: Value,
) -> Result<Value> {
    let request = uuid::Uuid::new_v4().to_string();
    payload["request_id"] = json!(request);
    send(ws, kind, payload).await?;
    let answer = crate::platform::time::timeout(
        RECEIPT_WAIT,
        wait(ws, receipt, "request_id", &request),
    )
    .await
    .map_err(|_| Error::Offline)??;
    Ok(answer.get("payload").unwrap_or(&answer).clone())
}

/// True when a `store_embed_keys_confirmed` receipt confirms `count` wrappers.
fn keys_confirmed(receipt: &Value, count: u64) -> bool {
    receipt["failed_count"] == 0 && receipt["created_count"].as_u64() == Some(count)
}

impl Client {
    /// Save one call source frame as an owner-encrypted image embed of
    /// `frame.chat_id` and return the reference for the voice pipeline.
    ///
    /// Order (as the web): validate, resolve the chat key and refuse team and
    /// Direct chats, upload the JPEG, then either store a fresh embed
    /// (`store_embed` + master/chat wrappers, each receipt awaited) or, when
    /// the upload was deduplicated, re-wrap the existing embed key for this
    /// chat (`store_embed_keys`) without touching its ciphertext. The web also
    /// re-sends its locally cached ciphertext in that branch; the core keeps
    /// no unsynced local embed rows, so it relies on the server copy.
    ///
    /// # Errors
    /// `InvalidFrame`, `ChatUnavailable`, `ExistingKeyUnavailable`,
    /// `AwaitingSync`, `Rejected` (upload refusal) and `Client` (session,
    /// transport, crypto, `Cancelled`). Nothing is stored locally on failure.
    pub async fn persist_call_source_frame(
        &mut self,
        frame: CallSourceFrame,
    ) -> std::result::Result<CallSourceReference, CallSourceError> {
        let bytes = validate_frame(&frame)?;
        let owner = self
            .user
            .get("id")
            .or_else(|| self.user.get("user_id"))
            .and_then(Value::as_str)
            .filter(|id| !id.is_empty())
            .map(str::to_owned)
            .ok_or(CallSourceError::ChatUnavailable)?;
        if self.team()?.is_some() {
            return Err(CallSourceError::ChatUnavailable);
        }
        if !self.chats.contains_key(&frame.chat_id) {
            self.open_chat(&frame.chat_id).await?;
        }
        let row = self
            .chats
            .get(&frame.chat_id)
            .cloned()
            .ok_or(CallSourceError::ChatUnavailable)?;
        refuse_chat(&row)?;
        let chat_key = self.edit_chat_key(&frame.chat_id).await?;
        let filename = format!("call-source-{}.jpg", frame.frame_id);
        let upload = self
            .upload_file_bytes(&filename, &bytes, "image/jpeg")
            .await
            .map_err(CallSourceError::from)?;
        let reference = CallSourceReference {
            embed_id: upload.embed_id.clone(),
            source_frame_id: frame.frame_id.clone(),
            captured_at: frame.captured_at,
            source_call_id: frame.call_id.clone(),
            source: frame.source,
        };
        let now = i64::try_from(now_ms() / 1000).map_err(|_| Error::Protocol)?;
        let wrappers = if upload.deduplicated == Value::Bool(true) {
            // Upload deduplication can return an image another chat owns:
            // keep its key and ciphertext, add only this chat's wrapper.
            self.edit_fetch_embed(&upload.embed_id)
                .await
                .map_err(|_| CallSourceError::ExistingKeyUnavailable)?;
            let existing = self
                .edit_embed_key(&upload.embed_id)
                .await
                .map_err(|_| CallSourceError::ExistingKeyUnavailable)?;
            let wrapped = keys::wrap_key(&existing, &chat_key, &mut OsNonces)?;
            vec![json!({"hashed_embed_id": keys::hash_id(&upload.embed_id), "key_type": "chat",
                "hashed_chat_id": keys::hash_id(&frame.chat_id), "encrypted_embed_key": wrapped,
                "hashed_user_id": keys::hash_id(&owner), "created_at": now})]
        } else {
            let master = self.master_capability()?;
            let master_wrapped = {
                let key = keys::derive_embed_key(&chat_key, &upload.embed_id)?;
                keys::wrap_key_with_master(&key, &master).await?
            };
            let prepared = prepare_store(
                &upload,
                &frame,
                bytes.len(),
                &chat_key,
                |_| Ok(master_wrapped),
                &owner,
                now,
                &mut OsNonces,
            )?;
            let mut ws = self.socket_with_task_jobs(false).await?;
            let stored = send_confirmed(&mut ws, "store_embed", "store_embed_confirmed", prepared.payload).await;
            let stored = match stored {
                Ok(receipt) if receipt["embed_id"].as_str() == Some(upload.embed_id.as_str()) => Ok(()),
                Ok(_) => Err(Error::Protocol),
                Err(error) => Err(error),
            };
            let result = match stored {
                Ok(()) => self.store_wrappers(&mut ws, &prepared.keys).await,
                Err(error) => Err(error.into()),
            };
            let _ = ws.close(None).await;
            result?;
            prepared.keys
        };
        if upload.deduplicated == Value::Bool(true) {
            let mut ws = self.socket_with_task_jobs(false).await?;
            let result = self.store_wrappers(&mut ws, &wrappers).await;
            let _ = ws.close(None).await;
            result?;
        }
        self.embed_keys.extend(wrappers);
        Ok(reference)
    }

    /// Send `store_embed_keys` for `wrappers` and require every one stored.
    async fn store_wrappers(
        &mut self,
        ws: &mut transport::Socket,
        wrappers: &[Value],
    ) -> std::result::Result<(), CallSourceError> {
        let receipt = send_confirmed(
            ws,
            "store_embed_keys",
            "store_embed_keys_confirmed",
            json!({ "keys": wrappers }),
        )
        .await?;
        if keys_confirmed(&receipt, wrappers.len() as u64) {
            Ok(())
        } else {
            Err(CallSourceError::AwaitingSync)
        }
    }
}

#[cfg(test)]
#[path = "call_source_frame_tests.rs"]
mod tests;
