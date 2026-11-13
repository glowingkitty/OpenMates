//! `openmates ideabucket audio <file>` adapter: local path resolution, the
//! npm error/exit mapping (a missing or unreadable file is a runtime failure,
//! exit 1, like npm; not a usage error) and the metadata-removal warning on stderr. The
//! capture itself (classification, upload, transcription, encryption) is
//! shared Rust in `openmates_sdk::account::ideabucket_audio`.
use super::{CliError, CliOutput, Invocation};
use openmates_sdk::account::Account;
use openmates_sdk::account::ideabucket_audio::{
    AudioCaptureError, IdeaBucketAudio, classify_audio_file,
};
use std::path::PathBuf;

const METADATA_WARNING: &str =
    "Warning: Could not remove embedded file metadata; uploading the original file.\n";

/// npm fileEmbed `resolvePath`: `~/` is the home directory, others resolve
/// against the working directory.
fn resolve(raw: &str) -> Result<PathBuf, CliError> {
    if let Some(rest) = raw.strip_prefix("~/") {
        let home = std::env::var_os("HOME")
            .ok_or_else(|| file_error(format!("{raw}: File not found")))?;
        return Ok(PathBuf::from(home).join(rest));
    }
    std::path::absolute(raw).map_err(|_| file_error(format!("{raw}: File not found")))
}

fn file_error(message: String) -> CliError {
    CliError::Contract { code: "command_failed", message }
}

fn cli_error(error: AudioCaptureError) -> CliError {
    match error {
        AudioCaptureError::File(message) => file_error(message),
        AudioCaptureError::Rejected(message) => CliError::Contract {
            code: "ideabucket_audio_failed",
            message,
        },
        AudioCaptureError::Client(error) => CliError::Client(error),
    }
}

pub(super) async fn execute(
    i: &Invocation,
    raw_path: &str,
    scheduled_send_at: Option<i64>,
    account: &mut Account<'_>,
) -> Result<CliOutput, CliError> {
    let file = classify_audio_file(raw_path, &resolve(raw_path)?).map_err(cli_error)?;
    let outcome = account
        .add_ideabucket_audio(
            &file,
            IdeaBucketAudio {
                chat_id: i.text("chat"),
                bucket_id: i.text("bucket"),
                scheduled_send_at,
                prompt: i.text("prompt"),
            },
        )
        .await
        .map_err(cli_error)?;
    let mut output = CliOutput::json(&outcome.result)?;
    if !outcome.metadata_removed {
        output.stderr.push_str(METADATA_WARNING);
    }
    Ok(output)
}
