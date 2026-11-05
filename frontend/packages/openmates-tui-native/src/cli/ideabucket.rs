//! `openmates ideabucket ...` (npm handleIdeaBucket): every result is printed
//! as JSON, like npm. Declared from account.rs so it shares account dispatch.
use super::{CliError, CliOutput, Invocation, handlers};
use crate::client::Client;
use openmates_sdk::account::IdeaBucketText;

const COMMANDS: &[&str] = &[
    "ideabucket add",
    "ideabucket audio",
    "ideabucket status",
    "ideabucket settings get",
    "ideabucket settings set",
    "ideabucket process",
];
pub(super) fn supported(i: &Invocation) -> bool {
    COMMANDS.contains(&i.command_path().as_str())
}
fn fail(message: impl Into<String>) -> CliError {
    CliError::Invalid(message.into())
}
/// npm parseUnixSecondsFlag (milliseconds are accepted and floored).
fn unix_seconds(raw: &str) -> Result<i64, CliError> {
    let parsed: f64 = raw
        .trim()
        .parse()
        .map_err(|_| fail("Invalid --scheduled-at; expected Unix seconds."))?;
    if !parsed.is_finite() || parsed <= 0.0 {
        return Err(fail("Invalid --scheduled-at; expected Unix seconds."));
    }
    Ok(if parsed > 10_000_000_000.0 {
        (parsed / 1000.0).floor()
    } else {
        parsed.floor()
    } as i64)
}

pub(super) async fn execute(i: &Invocation, client: &mut Client) -> Result<CliOutput, CliError> {
    let command = i.command_path();
    let allowed: &[&str] = match command.as_str() {
        "ideabucket add" | "ideabucket audio" => &["chat", "bucket", "scheduled-at", "prompt"],
        "ideabucket status" => &["bucket"],
        "ideabucket settings set" => &["prompt", "times"],
        "ideabucket process" => &["bucket", "now"],
        _ => &[],
    };
    handlers::flags(i, allowed)?;
    let bucket_arg = || i.positionals.first().map(String::as_str).or(i.text("bucket"));
    let mut account = client.account();
    let value = match command.as_str() {
        "ideabucket add" => {
            let text = i.positionals.join(" ");
            if text.trim().is_empty() {
                return Err(fail("Missing IdeaBucket text for add."));
            }
            let scheduled = i.text("scheduled-at").map(unix_seconds).transpose()?;
            account
                .add_ideabucket_text(IdeaBucketText {
                    text: text.trim(),
                    chat_id: i.text("chat"),
                    bucket_id: i.text("bucket"),
                    scheduled_send_at: scheduled,
                    prompt: i.text("prompt"),
                })
                .await?
        }
        "ideabucket audio" => {
            let path = i.positionals.first().filter(|p| !p.is_empty());
            let path = path.ok_or_else(|| fail("Missing audio file path for IdeaBucket audio."))?;
            let scheduled = i.text("scheduled-at").map(unix_seconds).transpose()?;
            return audio::execute(i, path, scheduled, &mut account).await;
        }
        "ideabucket status" => account.ideabucket_status(bucket_arg()).await?,
        "ideabucket settings get" => account.ideabucket_settings().await?,
        "ideabucket settings set" => {
            if let Some(times) = i.text("times") {
                openmates_sdk::account::normalize_processing_times(&serde_json::json!(times))
                    .map_err(fail)?;
            }
            account
                .save_ideabucket_settings(i.text("prompt"), i.text("times"))
                .await?
        }
        "ideabucket process" => {
            let bucket =
                bucket_arg().ok_or_else(|| fail("Missing IdeaBucket bucket ID for process."))?;
            account.process_ideabucket(bucket, i.boolean("now")).await?
        }
        _ => {
            return Err(CliError::Unsupported {
                command,
                reason: "Unknown ideabucket subcommand.".into(),
            });
        }
    };
    CliOutput::json(&value)
}

#[path = "ideabucket_audio.rs"]
mod audio;
#[cfg(test)]
#[path = "ideabucket_tests.rs"]
mod tests;
