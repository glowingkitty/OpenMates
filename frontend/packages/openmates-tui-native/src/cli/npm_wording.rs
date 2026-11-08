//! Unknown-chat-id wording shared with the npm CLI (CLI adapter, `chats show|messages|download`).
//! The shared SDK maps HTTP 404/410/403 to generic errors; npm reports "Chat '<id>' not found".
//! Mirrors the not-found message in `frontend/packages/openmates-cli/src/client.ts`; verified by
//! the differential spec `cli-native-chats.spec.ts`.

use crate::error::Error;

use super::CliError;

/// Commands whose first positional is a chat id and that npm reports as "Chat '<id>' not found".
const CHAT_ID_COMMANDS: &[&str] = &["chats show", "chats messages", "chats download"];

/// Rewrite a generic unavailable/forbidden error into npm's chat-not-found wording.
///
/// Only applies to the commands in [`CHAT_ID_COMMANDS`] and only for the SDK's
/// not-found (`Invalid("The requested item is unavailable.")`) and `Forbidden`
/// mappings; every other error passes through untouched.
pub fn chat_not_found(command_path: &str, chat_id: Option<&str>, error: CliError) -> CliError {
    let (true, Some(id)) = (CHAT_ID_COMMANDS.contains(&command_path), chat_id) else {
        return error;
    };
    match error {
        CliError::Client(Error::Invalid("The requested item is unavailable."))
        | CliError::Client(Error::Forbidden) => CliError::Contract {
            // Contract (not Invalid) so the exit code is 1 like npm, not the usage code 2.
            code: "not_found",
            message: format!(
                "Chat '{id}' not found. Try 'openmates chats search \"{id}\"' to browse matches."
            ),
        },
        other => other,
    }
}
