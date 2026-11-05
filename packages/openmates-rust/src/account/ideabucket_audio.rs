//! IdeaBucket voice capture (npm `addIdeaBucketAudio`): classify the local
//! file like npm `processFiles`, strip container metadata, upload, transcribe,
//! store the client-encrypted `audio-recording` embed (master-key wrapper
//! only) and add the idea to the bucket's encrypted draft. The upload AES key
//! material only enters the encrypted embed content, never output or logs.
use super::Account;
use super::ideabucket::{PreparedIdea, ideabucket_chat_id};
use crate::Error;
use crate::client::upload::{
    AudioTranscription, DraftEmbed, UploadError, UploadFileResponse, toon_encode,
};
use crate::upload_privacy::{js_extname, prepare_audio_upload};
use serde_json::{Value, json};
use sha2::{Digest, Sha256};
use std::path::Path;
use zeroize::Zeroizing;

const MAX_FILE_BYTES: u64 = 100 * 1024 * 1024;
const NOT_AUDIO: &str = "IdeaBucket audio requires one supported local audio file.";
const BLOCKED_EXTENSIONS: &[&str] = &[
    "pem",
    "key",
    "p12",
    "pfx",
    "keystore",
    "kdbx",
    "credentials",
];
const BLOCKED_NAMES: &[&str] = &[
    "id_rsa",
    "id_ed25519",
    "id_dsa",
    "id_ecdsa",
    "authorized_keys",
    "known_hosts",
    ".git-credentials",
    ".netrc",
    ".pgpass",
    ".my.cnf",
];
const AUDIO_EXTENSIONS: &[&str] = &["mp3", "m4a", "mp4", "wav", "webm", "ogg", "oga", "aac"];
/// Types npm `processFiles` accepts but which are not audio.
const OTHER_SUPPORTED: &[&str] = &[
    "csv",
    "tsv",
    "pdf",
    "jpg",
    "jpeg",
    "png",
    "webp",
    "gif",
    "heic",
    "heif",
    "bmp",
    "tiff",
    "tif",
    "svg",
    "py",
    "js",
    "ts",
    "html",
    "css",
    "json",
    "svelte",
    "java",
    "cpp",
    "c",
    "h",
    "hpp",
    "rs",
    "go",
    "rb",
    "php",
    "swift",
    "kt",
    "txt",
    "md",
    "xml",
    "yaml",
    "yml",
    "sh",
    "bash",
    "sql",
    "vue",
    "jsx",
    "tsx",
    "scss",
    "less",
    "sass",
    "dockerfile",
    "toml",
    "ini",
    "cfg",
    "conf",
    "env",
    "envrc",
    "graphql",
    "gql",
    "r",
    "m",
    "pl",
    "lua",
    "ex",
    "exs",
    "erl",
    "hs",
    "scala",
    "dart",
    "tf",
];

/// Voice capture input (npm addIdeaBucketAudio params).
#[derive(Clone, Default)]
pub struct IdeaBucketAudio<'a> {
    pub chat_id: Option<&'a str>,
    pub bucket_id: Option<&'a str>,
    pub scheduled_send_at: Option<i64>,
    pub prompt: Option<&'a str>,
}

/// A local file that npm `processFiles` would classify as audio.
pub struct AudioFile {
    pub path: std::path::PathBuf,
    pub filename: String,
}

/// Local-file rejections, upload/transcription rejections (npm text) or a
/// typed client failure.
#[derive(Debug)]
pub enum AudioCaptureError {
    Client(Error),
    File(String),
    Rejected(String),
}
impl From<Error> for AudioCaptureError {
    fn from(error: Error) -> Self {
        Self::Client(error)
    }
}
impl From<UploadError> for AudioCaptureError {
    fn from(error: UploadError) -> Self {
        match error {
            UploadError::Client(error) => Self::Client(error),
            UploadError::Rejected(message) => Self::Rejected(message),
        }
    }
}
impl std::fmt::Display for AudioCaptureError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Self::Client(error) => error.fmt(f),
            Self::File(message) | Self::Rejected(message) => f.write_str(message),
        }
    }
}

/// The npm result plus whether container metadata was removed before upload.
pub struct AudioCaptureOutcome {
    pub result: Value,
    pub metadata_removed: bool,
}

/// npm `processFiles([raw])` followed by the audio-recording check. `resolved`
/// is the caller-resolved path (`~/` and relative paths are adapter concerns).
pub fn classify_audio_file(raw: &str, resolved: &Path) -> Result<AudioFile, AudioCaptureError> {
    let reject = |message: String| AudioCaptureError::File(format!("{raw}: {message}"));
    let filename = resolved
        .file_name()
        .map(|name| name.to_string_lossy().into_owned())
        .unwrap_or_default();
    let ext = js_extname(&filename)
        .trim_start_matches('.')
        .to_ascii_lowercase();
    // npm existsSync: any stat failure reads as a missing file.
    let metadata = std::fs::metadata(resolved).map_err(|_| reject("File not found".into()))?;
    if metadata.is_dir() {
        return Err(reject("Is a directory, not a file".into()));
    }
    if metadata.len() > MAX_FILE_BYTES {
        let megabytes = (metadata.len() as f64 / 1024.0 / 1024.0).round();
        return Err(reject(format!(
            "File too large ({megabytes}MB > 100MB limit)"
        )));
    }
    if BLOCKED_EXTENSIONS.contains(&ext.as_str()) {
        return Err(reject(format!(
            "Blocked: .{ext} files may contain private keys. Use --allow-sensitive to override."
        )));
    }
    if BLOCKED_NAMES.contains(&filename.as_str()) {
        return Err(reject(format!(
            "Blocked: '{filename}' typically contains credentials. Use --allow-sensitive to override."
        )));
    }
    let lower = filename.to_ascii_lowercase();
    let env_file = lower == ".env" || lower.starts_with(".env.") || lower == ".envrc";
    if ext == "docx" || ext == "xlsx" {
        return Err(reject(format!(
            "Office file .{ext} requires async processing; use processFilesAsync()."
        )));
    }
    if lower == "dockerfile" || env_file || OTHER_SUPPORTED.contains(&ext.as_str()) {
        return Err(AudioCaptureError::File(NOT_AUDIO.into()));
    }
    if !AUDIO_EXTENSIONS.contains(&ext.as_str()) {
        return Err(reject(format!(
            "Unsupported file type: .{ext}. Supported: code/text, images, PDFs, audio."
        )));
    }
    Ok(AudioFile {
        path: resolved.to_path_buf(),
        filename,
    })
}

/// npm `createEmbedRef(type, source)`.
pub fn create_embed_ref(kind: &str, source: &str) -> String {
    let lower = source.to_lowercase();
    let stripped = lower
        .strip_prefix("https://")
        .or_else(|| lower.strip_prefix("http://"))
        .unwrap_or(&lower);
    let mut slug = String::new();
    for c in stripped.chars() {
        if c.is_ascii_lowercase() || c.is_ascii_digit() {
            slug.push(c);
        } else if !slug.ends_with('-') {
            slug.push('-');
        }
    }
    let trimmed: String = slug.trim_matches('-').chars().take(40).collect();
    let prefix = if trimmed.is_empty() {
        kind.to_owned()
    } else {
        trimmed
    };
    let digest = Sha256::digest(format!("{kind}:{source}").as_bytes());
    let hex: String = digest.iter().take(3).map(|b| format!("{b:02x}")).collect();
    format!("{prefix}-{hex}")
}

/// npm `createEmbedJsonReferenceBlock` (`JSON.stringify({ type, embed_id })`).
pub fn embed_json_reference_block(kind: &str, embed_id: &str) -> String {
    format!(
        "```json\n{{\"type\":{},\"embed_id\":{}}}\n```",
        json!(kind),
        json!(embed_id)
    )
}

/// npm: `transcript_corrected ?? transcript ?? transcript_original ?? ""`.
pub fn selected_transcript(t: &AudioTranscription) -> String {
    [
        &t.transcript_corrected,
        &t.transcript,
        &t.transcript_original,
    ]
    .into_iter()
    .find(|value| !value.is_null())
    .map(|value| {
        value
            .as_str()
            .map(str::to_owned)
            .unwrap_or_else(|| value.to_string())
    })
    .unwrap_or_default()
}

/// The idea markdown (`Audio:` line, JSON embed reference, optional transcript).
pub fn audio_idea_markdown(filename: &str, embed_id: &str, transcript: &str) -> String {
    let mut lines = vec![
        format!("Audio: {filename}"),
        embed_json_reference_block("audio-recording", embed_id),
    ];
    if !transcript.is_empty() {
        lines.push(format!("Transcript: {transcript}"));
    }
    lines.join("\n")
}

/// The finished `audio-recording` embed content (TOON, npm field order).
pub(crate) fn audio_embed_content(
    filename: &str,
    embed_ref: &str,
    upload: &UploadFileResponse,
    t: &AudioTranscription,
) -> crate::Result<Zeroizing<String>> {
    let fields = [
        ("app_id", json!("audio")),
        ("skill_id", json!("transcribe")),
        ("type", json!("audio-recording")),
        ("status", json!("finished")),
        ("filename", json!(filename)),
        ("embed_ref", json!(embed_ref)),
        ("mime_type", json!(upload.content_type)),
        ("transcript", t.transcript.clone()),
        ("transcript_original", t.transcript_original.clone()),
        ("transcript_corrected", t.transcript_corrected.clone()),
        ("use_corrected", t.use_corrected.clone()),
        ("correction_model", t.correction_model.clone()),
        ("model", t.model.clone()),
        ("waveform", t.waveform.clone()),
        ("s3_base_url", json!(upload.s3_base_url)),
        ("files", Value::Object(upload.files.clone())),
        ("aes_key", json!(upload.aes_key.as_str())),
        ("aes_nonce", json!(upload.aes_nonce.as_str())),
        (
            "vault_wrapped_aes_key",
            json!(upload.vault_wrapped_aes_key.as_str()),
        ),
    ];
    let mut fields = fields;
    let encoded = toon_encode::encode_fields(&fields).map(Zeroizing::new);
    for (_, value) in fields.iter_mut() {
        if let Value::String(text) = value {
            zeroize::Zeroize::zeroize(text);
        }
    }
    encoded
}

/// The server-processable idea payload (npm `payload` for type `audio`).
pub fn audio_idea_payload(
    filename: &str,
    embed_ref: &str,
    transcript: &str,
    t: &AudioTranscription,
) -> Value {
    json!({
        "type": "audio",
        "filename": filename,
        "embed_ref": embed_ref,
        "transcript": transcript,
        "transcript_original": t.transcript_original,
        "transcript_corrected": t.transcript_corrected,
        "use_corrected": t.use_corrected,
        "correction_model": t.correction_model,
        "model": t.model,
        "waveform": t.waveform,
    })
}

impl Account<'_> {
    /// Upload, transcribe and capture one audio file into the IdeaBucket draft.
    pub async fn add_ideabucket_audio(
        &mut self,
        file: &AudioFile,
        input: IdeaBucketAudio<'_>,
    ) -> Result<AudioCaptureOutcome, AudioCaptureError> {
        let chat_id = ideabucket_chat_id(input.chat_id)?;
        let filename = file.filename.as_str();
        let bytes = std::fs::read(&file.path).map_err(|_| Error::Io)?;
        let local_embed_id = uuid::Uuid::new_v4().to_string();
        let embed_ref = format!(
            "{}-{local_embed_id}",
            create_embed_ref("audio-recording", filename)
        );
        let prepared = prepare_audio_upload(bytes, filename)
            .map_err(|_| AudioCaptureError::File(NOT_AUDIO.into()))?;
        let upload = self
            .client
            .upload_file_bytes(filename, &prepared.bytes, &prepared.mime_type)
            .await?;
        // npm adoptUploadEmbedId: the upload server's ID is authoritative.
        let embed_id = upload.embed_id.clone();
        let transcription = self
            .client
            .transcribe_uploaded_audio(&upload, filename, Some(&chat_id), &embed_id)
            .await?;
        let transcript = selected_transcript(&transcription);
        let content = audio_embed_content(filename, &embed_ref, &upload, &transcription)?;
        let idea = PreparedIdea {
            content: audio_idea_markdown(filename, &embed_id, &transcript),
            preview: if transcript.is_empty() {
                filename.to_owned()
            } else {
                transcript.clone()
            },
            payload: audio_idea_payload(filename, &embed_ref, &transcript, &transcription),
        };
        let (draft, result) = self
            .prepare_ideabucket_draft(
                &[idea],
                &chat_id,
                input.bucket_id,
                input.scheduled_send_at,
                input.prompt,
            )
            .await?;
        let embed = DraftEmbed {
            embed_id,
            kind: "audio-recording".into(),
            content,
            text_preview: filename.to_owned(),
            status: "finished".into(),
            content_hash: Some(upload.content_hash.clone()),
        };
        self.client.store_draft_embeds(&chat_id, &[embed]).await?;
        let result = self.save_ideabucket_draft(&chat_id, draft, result).await?;
        Ok(AudioCaptureOutcome {
            result,
            metadata_removed: prepared.sanitized,
        })
    }
}

#[cfg(test)]
#[path = "ideabucket_audio_tests.rs"]
mod tests;
