//! Enhance job views (shared core; spec `feature.embed-user-edits`,
//! `enhance.billed-once-refunded-on-failure`): the typed job of
//! `GET /v1/images/enhance/{operation_id}` and its result, checked against the
//! job (same embed, base version N, only the job's files), plus the image
//! index shared with restore. Mirrors `enhance_jobs.public_view`.
use super::{IMAGE_BUCKET, ImageEnhanceError, ImageEnhanceResult};
use crate::client::embed_user_revision::FileRef;
use crate::error::Error;
use serde::Serialize;
use serde_json::{Map, Value, json};
use std::fmt;
use zeroize::Zeroizing;

/// Server state of an Enhance job.
#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum EnhanceJobState {
    /// Running.
    Pending,
    /// A result exists and may be saved (until `expires_at`).
    Ready,
    /// The result was saved as version `target_version`.
    Committed,
    /// The job failed; nothing was charged.
    Failed,
    /// The result was never saved and was deleted.
    Expired,
}

impl EnhanceJobState {
    fn parse(value: &str) -> Option<Self> {
        Some(match value {
            "pending" => Self::Pending,
            "ready" => Self::Ready,
            "committed" => Self::Committed,
            "failed" => Self::Failed,
            "expired" => Self::Expired,
            _ => return None,
        })
    }
}

/// The enhanced files of a ready job. Holds the new file key in plaintext
/// (zeroized on drop; never printed by `Debug`): it goes only into the
/// embed-key encrypted content of version N+1.
#[derive(Clone)]
pub struct EnhancedImage {
    pub(super) aes_key: Zeroizing<String>,
    /// Content fields of the new version except `aes_key`.
    pub(super) fields: Map<String, Value>,
    file_keys: Vec<FileRef>,
    pub(super) media_index: Value,
}

impl EnhancedImage {
    /// S3 objects of the result (the server adds them to the embed's files).
    pub fn file_keys(&self) -> &[FileRef] {
        &self.file_keys
    }

    /// Server-readable image index the commit repoints (no plaintext key).
    pub fn media_index(&self) -> &Value {
        &self.media_index
    }
}

impl fmt::Debug for EnhancedImage {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.debug_struct("EnhancedImage")
            .field("file_keys", &self.file_keys)
            .finish_non_exhaustive()
    }
}

/// One Enhance job as the server reports it. Serializes (for bindings) as
/// its plain job fields; the result with its plaintext file key is never
/// serialized, it stays in the core until the commit seals it.
#[derive(Clone, Debug, Serialize)]
pub struct EnhanceJob {
    /// Idempotency key of the job (a UUID).
    pub operation_id: String,
    /// The enhanced embed.
    pub embed_id: String,
    /// Job state.
    pub state: EnhanceJobState,
    /// Version N the job enhances.
    pub base_version: i64,
    /// Version N+1 the result becomes.
    pub target_version: i64,
    /// Quoted price.
    pub credits: i64,
    /// Whether the price was charged.
    pub charged: bool,
    /// Unix seconds the job was created.
    pub created_at: i64,
    /// Unix seconds after which an unsaved result is deleted.
    pub expires_at: i64,
    /// Failure code of a failed job.
    pub error_code: Option<String>,
    #[serde(skip)]
    result: Option<EnhancedImage>,
}

impl EnhanceJob {
    /// The result, while the job is ready (or committed and still delivered).
    pub fn result(&self) -> Option<&EnhancedImage> {
        self.result.as_ref()
    }

    /// True once the job will not change by itself any more.
    pub fn is_settled(&self) -> bool {
        self.state != EnhanceJobState::Pending
    }
}

/// A server failure code if it is `[a-z0-9_]{1,64}`, else `enhance_failed`.
pub(super) fn failure_code(value: &Value) -> String {
    value
        .as_str()
        .filter(|code| {
            (1..=64).contains(&code.len())
                && code
                    .bytes()
                    .all(|b| b.is_ascii_lowercase() || b.is_ascii_digit() || b == b'_')
        })
        .unwrap_or("enhance_failed")
        .to_owned()
}

fn file_ref(bucket: Option<&Value>, key: Option<&Value>) -> Option<FileRef> {
    let bucket = bucket.map_or(Some(IMAGE_BUCKET), Value::as_str)?;
    let key = key?.as_str()?;
    (!bucket.is_empty() && !key.is_empty()).then(|| FileRef {
        bucket: bucket.to_owned(),
        key: key.to_owned(),
    })
}

/// The image index `{files, aes_nonce, vault_wrapped_aes_key, content_type?}`
/// of a version's decrypted content fields; `None` when a field is missing.
/// Shared by Enhance and restore.
pub(crate) fn media_index_of(fields: &Map<String, Value>) -> Option<(Vec<FileRef>, Value)> {
    let files = fields.get("files")?.as_object().filter(|f| !f.is_empty())?;
    let mut keys: Vec<FileRef> = Vec::with_capacity(files.len());
    for variant in files.values() {
        let reference = file_ref(variant.get("bucket"), variant.get("s3_key"))?;
        if !keys.contains(&reference) {
            keys.push(reference);
        }
    }
    let nonce = fields.get("aes_nonce")?.as_str()?;
    let wrapped = fields
        .get("vault_wrapped_aes_key")?
        .as_str()
        .filter(|key| key.starts_with("vault:"))?;
    let mut index = json!({"files": files, "aes_nonce": nonce, "vault_wrapped_aes_key": wrapped});
    if let Some(mime) = files
        .get("original")
        .and_then(|original| original.get("mime_type"))
        .and_then(Value::as_str)
        .filter(|mime| mime.starts_with("image/"))
    {
        index["content_type"] = json!(mime);
    }
    Some((keys, index))
}

/// Validate a job's `result` against the job: the result was made from the
/// job's base version of the same embed and names only files of the job.
fn parse_result(value: &Value, embed_id: &str, base_version: i64) -> Option<EnhancedImage> {
    let object = value.as_object()?;
    let origin = object.get("enhanced_from")?;
    if origin.get("embed_id")?.as_str()? != embed_id
        || origin.get("version")?.as_i64()? != base_version
    {
        return None;
    }
    let aes_key = object.get("aes_key")?.as_str().filter(|k| k.len() == 44)?;
    let file_keys = object
        .get("s3_file_keys")?
        .as_array()
        .filter(|keys| (1..=64).contains(&keys.len()))?
        .iter()
        .map(|reference| file_ref(Some(reference.get("bucket")?), reference.get("key")))
        .collect::<Option<Vec<_>>>()?;
    // The display and the next Enhance read the `original` variant.
    object.get("files")?.get("original")?;
    let fields: Map<String, Value> = object
        .iter()
        .filter(|(name, _)| !matches!(name.as_str(), "aes_key" | "s3_file_keys"))
        .map(|(name, value)| (name.clone(), value.clone()))
        .collect();
    let (variant_keys, media_index) = media_index_of(&fields)?;
    if !variant_keys.iter().all(|key| file_keys.contains(key)) {
        return None;
    }
    Some(EnhancedImage {
        aes_key: Zeroizing::new(aes_key.to_owned()),
        fields,
        file_keys,
        media_index,
    })
}

fn int(object: &Map<String, Value>, name: &str) -> Option<i64> {
    object.get(name).and_then(Value::as_i64)
}

/// Read a job view `{operation_id, embed_id, state, base_version,
/// target_version, credits, charged, created_at, expires_at, error_code?,
/// result?}`. A `ready` view without a result is reported as `Expired`: the
/// server withholds the result only once it can no longer be saved.
///
/// # Errors
/// `Transport(Protocol)` for another operation or embed, unknown states,
/// versions that are not N -> N+1, or a malformed result.
pub(crate) fn parse_job(
    value: &Value,
    operation_id: &str,
    embed_id: Option<&str>,
) -> ImageEnhanceResult<EnhanceJob> {
    let protocol = || ImageEnhanceError::Transport(Error::Protocol);
    let object = value.as_object().ok_or_else(protocol)?;
    let text = |name: &str| object.get(name).and_then(Value::as_str);
    if text("operation_id") != Some(operation_id) {
        return Err(protocol());
    }
    let job_embed = text("embed_id")
        .filter(|id| !id.is_empty() && embed_id.is_none_or(|wanted| wanted == *id))
        .ok_or_else(protocol)?;
    let mut state = text("state")
        .and_then(EnhanceJobState::parse)
        .ok_or_else(protocol)?;
    let base_version = int(object, "base_version")
        .filter(|v| *v >= 1)
        .ok_or_else(protocol)?;
    let target_version = int(object, "target_version")
        .filter(|v| *v == base_version + 1)
        .ok_or_else(protocol)?;
    let result = match object.get("result") {
        None | Some(Value::Null) => None,
        Some(result) => Some(parse_result(result, job_embed, base_version).ok_or_else(protocol)?),
    };
    if state == EnhanceJobState::Ready && result.is_none() {
        state = EnhanceJobState::Expired;
    }
    Ok(EnhanceJob {
        operation_id: operation_id.to_owned(),
        embed_id: job_embed.to_owned(),
        state,
        base_version,
        target_version,
        credits: int(object, "credits")
            .filter(|c| *c >= 0)
            .ok_or_else(protocol)?,
        charged: object
            .get("charged")
            .and_then(Value::as_bool)
            .ok_or_else(protocol)?,
        created_at: int(object, "created_at").ok_or_else(protocol)?,
        expires_at: int(object, "expires_at").ok_or_else(protocol)?,
        error_code: (state == EnhanceJobState::Failed).then(|| failure_code(&object["error_code"])),
        result,
    })
}
