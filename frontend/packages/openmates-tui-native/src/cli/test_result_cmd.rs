//! `openmates embeds test-result <embed-id> [--version <n>] [--json]`: prints one
//! Code test result embed in full (current content without `--version`). CLI/TUI
//! adapter only: the decrypted content comes from the shared SDK read (same path
//! as `embeds show` / `embeds versions show`),
//! decoding and the render model live in `openmates_sdk::test_result_embed`.
//! Spec: `code-run.tests.recorded-evidence`.
use super::{CliError, CliOutput};
use openmates_sdk::test_result_embed::TestResultEmbed;
use serde_json::{json, Value};

/// Render a decrypted embed version read (`embed_id`, `version_number`, `content`).
///
/// With `--json` the output carries the typed result, the render model and the
/// evidence references (paths and asset ids, never bytes). Text output escapes
/// terminal control characters in every sandbox-produced field.
pub(super) fn output(json_mode: bool, value: &Value) -> Result<CliOutput, CliError> {
    let content = value["content"]
        .as_str()
        .ok_or_else(|| CliError::Contract {
            code: "command_failed",
            message: "Embed version content was not available after local reconstruction.".into(),
        })?;
    let embed = TestResultEmbed::decode_content(content).map_err(|error| CliError::Contract {
        code: error.code(),
        message: format!("This embed is not a test result: {error}"),
    })?;
    let view = embed.render_model();
    if json_mode {
        return CliOutput::json(&json!({
            "embed_id": value["embed_id"],
            "version_number": value["version_number"],
            "test_result": embed,
            "render": view,
        }));
    }
    let id = super::terminal_text(value["embed_id"].as_str().unwrap_or(""));
    Ok(CliOutput {
        stdout: format!(
            "\n\x1b[1mTest result\x1b[0m {id} v{}\n{}",
            value["version_number"],
            super::terminal_text(&view.render_full())
        ),
        stderr: String::new(),
        exit_code: 0,
    })
}

#[cfg(test)]
#[path = "test_result_cmd_tests.rs"]
mod tests;
