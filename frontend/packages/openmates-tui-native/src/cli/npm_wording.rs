//! Unknown-id wording shared with the npm CLI (CLI adapter: chats, projects).
//! The shared SDK maps HTTP 404/410/403 to generic errors; npm names the missing object.
//! Mirrors the not-found messages in `frontend/packages/openmates-cli/src/` and is verified by
//! the differential specs `cli-native-chats.spec.ts`, `cli-native-projects.spec.ts` and
//! `cli-native-apps.spec.ts` (app skill not-found).

use super::CliError;
use crate::error::Error;

/// Commands whose first positional is a chat id and that npm reports as "Chat '<id>' not found".
const CHAT_ID_COMMANDS: &[&str] = &["chats show", "chats messages", "chats download"];

/// The SDK's generic not-found (and, for chats, forbidden) mapping.
fn is_unavailable(error: &CliError, include_forbidden: bool) -> bool {
    matches!(error, CliError::Client(Error::Invalid("The requested item is unavailable.")))
        || (include_forbidden && matches!(error, CliError::Client(Error::Forbidden)))
}

/// Build a not-found error with exit code 1 (`Invalid` would exit 2, the usage code).
fn not_found(code: &'static str, message: String) -> CliError {
    CliError::Contract { code, message }
}

/// Split a three-word `apps <app> <skill>` command path into app and skill.
///
/// `apps travel booking-link` and `apps design export-icon` are token/local routes
/// rather than backend skill runs, so they are excluded.
fn app_skill(command_path: &str) -> Option<(&str, &str)> {
    let parts: Vec<&str> = command_path.split_whitespace().collect();
    match parts[..] {
        ["apps", app, skill]
            if !matches!(command_path, "apps travel booking-link" | "apps design export-icon") =>
        {
            Some((app, skill))
        }
        _ => None,
    }
}

/// Rewrite a generic unavailable error into npm's not-found wording for known commands.
///
/// `apps <app> <skill>` says "<app>/<skill> failed: Skill execution failed: Not Found"
/// (keeps npm's stderr class).
///
/// `chats show|messages|download` (text mode only) say "Chat '<id>' not found";
/// `projects show` says "Project '<id>' not found"; `projects settings focus activate`
/// says "Chat '<chat>' not found"; `projects sources remove` says
/// "Project source delete failed: Source not found". Every other error, and every
/// other command, passes through untouched.
pub fn unknown_id(
    command_path: &str,
    first_positional: Option<&str>,
    chat_flag: Option<&str>,
    json: bool,
    error: CliError,
) -> CliError {
    match (command_path, first_positional) {
        (path, Some(id)) if CHAT_ID_COMMANDS.contains(&path) && !json && is_unavailable(&error, true) => not_found(
            "not_found",
            format!("Chat '{id}' not found. Try 'openmates chats search \"{id}\"' to browse matches."),
        ),
        ("projects show", Some(id)) if is_unavailable(&error, false) => {
            not_found("command_failed", format!("Project '{id}' not found."))
        }
        ("projects settings focus activate", _) if is_unavailable(&error, false) => match chat_flag {
            Some(chat) => not_found("chat_not_found", format!("Chat '{chat}' not found.")),
            None => error,
        },
        ("projects sources remove", _) if is_unavailable(&error, false) => not_found(
            "source_not_found",
            "Project source delete failed: Source not found".to_owned(),
        ),
        (path, _) if app_skill(path).is_some() && is_unavailable(&error, false) => {
            let (app, skill) = app_skill(path).expect("guard checked app_skill is Some");
            not_found("not_found", format!("{app}/{skill} failed: Skill execution failed: Not Found"))
        }
        _ => error,
    }
}
