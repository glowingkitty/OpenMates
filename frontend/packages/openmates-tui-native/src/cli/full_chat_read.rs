//! Native `chats show --json` projection. Selection and wire formatting stay
//! in this adapter; fetching, decryption, PII and the original admission stay
//! in shared Rust. The historical module name does not imply full history.
use super::*;
use openmates_sdk::client::{
    chat_details::{ChatDetailsHistory, ChatDetailsOptions, ChatDetailsRead},
    full_chat_read::FullChatReadAdmission,
    saved_chat_read::SavedChatContentMode,
};
pub(crate) fn is_full_json(invocation: &Invocation) -> bool {
    invocation.command_path() == "chats show" && invocation.boolean("json")
}
pub(crate) fn options(invocation: &Invocation) -> ChatDetailsOptions {
    ChatDetailsOptions {
        history: if invocation.boolean("all") {
            ChatDetailsHistory::Full
        } else {
            // One source-compatible request. The server may return fewer
            // rows; this is not a target count to fill with older pages.
            ChatDetailsHistory::Latest { limit: 30 }
        },
        // The preserved JSON command exposes stored content plus optional
        // local mappings. It does not implicitly restore private values.
        content_mode: SavedChatContentMode::Stored,
    }
}
pub(super) async fn execute_admitted(
    invocation: &Invocation,
    client: &mut openmates_sdk::Client,
    cancel: &tokio_util::sync::CancellationToken,
    inventory: Option<openmates_sdk::client::FreshChatInventory>,
) -> Result<(CliOutput, FullChatReadAdmission), CliError> {
    super::handlers::saved_show_flags(invocation)?;
    let id = invocation
        .positionals
        .first()
        .ok_or_else(|| CliError::Invalid("Missing chat ID.".into()))?;
    let mut read = match inventory {
        Some(proof) => client
            .read_chat_details_and_fresh_inventory(id, options(invocation), proof, cancel)
            .await?,
        None => client.read_chat_details(id, options(invocation)).await?,
    };
    let mut output = output(&read, client)?;
    match read.take_admission(client) {
        Ok(admission) => Ok((output, admission)),
        Err(error) => {
            use zeroize::Zeroize;
            output.stdout.zeroize();
            output.stderr.zeroize();
            Err(error.into())
        }
    }
}
pub(super) fn output(
    read: &ChatDetailsRead,
    client: &openmates_sdk::Client,
) -> Result<CliOutput, CliError> {
    read.check(client)?;
    let output = serialize_parts(
        &read.chat, &read.messages, &read.follow_up_suggestions, read.has_more_before,
    )?;
    // Restrict both before and AFTER serialization; refused bytes are wiped.
    let mut stdout = zeroize::Zeroizing::new(output.stdout);
    read.check(client)?;
    Ok(CliOutput {
        stdout: std::mem::take(&mut *stdout),
        stderr: String::new(),
        exit_code: 0,
    })
}
fn serialize_parts(
    chat: &impl serde::Serialize,
    messages: &impl serde::Serialize,
    follow_up_suggestions: &impl serde::Serialize,
    has_more_before: Option<bool>,
) -> Result<CliOutput, CliError> {
    // The SDK result remains headless. The installed command's snake_case
    // wrapper and conditional paging key belong solely to the CLI.
    #[derive(serde::Serialize)]
    struct MachineOutput<'a, C, M, S> {
        chat: &'a C,
        messages: &'a M,
        follow_up_suggestions: &'a S,
        #[serde(skip_serializing_if = "Option::is_none")]
        has_more_before: Option<bool>,
    }
    // Borrow the admitted headless data; no cloned plaintext JSON tree.
    let value = MachineOutput { chat, messages, follow_up_suggestions, has_more_before };
    let mut stdout = serde_json::to_string_pretty(&value)
        .map_err(|_| CliError::Client(Error::Protocol))?;
    stdout.push('\n');
    Ok(CliOutput { stdout, stderr: String::new(), exit_code: 0 })
}
#[cfg(test)]
#[path = "full_chat_read_tests.rs"]
mod tests;
