//! `openmates embeds enhance` and `openmates embeds restore`: user-made embed
//! versions (spec `feature.embed-user-edits`, assertions `enhance.faithful-2k`,
//! `edit.next-version`, `restore.creates-version`, `event.chat-notice`). CLI
//! shell only: it parses flags, asks the shared core for the server head
//! (`Client::embed_user_edit_head`), runs `Client::enhance_image` /
//! `save_image_enhance_result` / `restore_embed_version`, and words the result
//! and the core's stable error codes. Personal Cookie session only.
use super::{CliError, CliOutput, Invocation};
use crate::{client::Client, error::Error};
use openmates_sdk::client::embed_user_revision::{
    EmbedRevisionOutcome, EventDelivery, RevisionScope, UserRevisionError,
};
use openmates_sdk::client::image_enhance::{
    DEFAULT_ENHANCE_DEADLINE, ImageEnhanceError, ImageEnhanceSaved,
};
use serde_json::{Value, json};
use std::io::Write;
use tokio_util::sync::CancellationToken;

/// Credits one Enhance costs (`embed-user-edits.enhance.billed-once-refunded-on-failure`);
/// shown to the user only, the server prices the job.
const ENHANCE_CREDITS: u32 = 63;

/// True for the two user-edit commands this module owns.
pub fn supported(i: &Invocation) -> bool {
    matches!(
        i.command_path().as_str(),
        "embeds enhance" | "embeds restore"
    )
}

/// Where the user asked to save the version.
#[derive(Debug, PartialEq, Eq)]
pub(super) enum ScopeArg {
    /// The embed's chat: `--chat <id>`, else the chat the core finds for it.
    Chat(Option<String>),
    /// `--project <id>`: a Project that links the embed.
    Project(String),
}

/// Parsed arguments of one command.
#[derive(Debug, PartialEq, Eq)]
pub(super) struct Options {
    pub embed_id: String,
    pub scope: ScopeArg,
    /// `embeds restore --version <n>`.
    pub version: Option<i64>,
    /// `embeds enhance --resume <operation-id>`.
    pub resume: Option<String>,
}

fn argument(message: impl Into<String>) -> CliError {
    CliError::Contract {
        code: "command_failed",
        message: message.into(),
    }
}

fn refused(code: &'static str, message: impl Into<String>) -> CliError {
    CliError::Contract {
        code,
        message: message.into(),
    }
}

/// Parse and validate flags before any network or key access.
pub(super) fn parse(i: &Invocation) -> Result<Options, CliError> {
    let restore = i.command_path() == "embeds restore";
    if restore {
        super::handlers::flags(i, &["version", "chat", "project"])?;
    } else {
        super::handlers::flags(i, &["chat", "project", "resume"])?;
    }
    let usage = if restore {
        "Usage: openmates embeds restore <embed-id> --version <n> [--chat <chat-id> | --project <project-id>] [--json]"
    } else {
        "Usage: openmates embeds enhance <embed-id> [--chat <chat-id> | --project <project-id>] [--resume <operation-id>] [--json]"
    };
    let embed_id = i
        .positionals
        .first()
        .filter(|id| uuid::Uuid::parse_str(id).is_ok())
        .cloned()
        .ok_or_else(|| argument(format!("Missing or invalid full embed ID. {usage}")))?;
    let non_empty = |name: &str| -> Result<Option<String>, CliError> {
        match i.text(name) {
            None => Ok(None),
            Some(value) if uuid::Uuid::parse_str(value).is_ok() => Ok(Some(value.to_owned())),
            Some(_) => Err(argument(format!("--{name} requires a full ID. {usage}"))),
        }
    };
    let chat = non_empty("chat")?;
    let project = non_empty("project")?;
    let scope = match (chat, project) {
        (Some(_), Some(_)) => return Err(argument("Choose --chat or --project, not both.")),
        (chat, None) => ScopeArg::Chat(chat),
        (None, Some(project)) => ScopeArg::Project(project),
    };
    let version = if restore {
        Some(super::embed_commands::version(i)?)
    } else {
        None
    };
    let resume = if restore { None } else { non_empty("resume")? };
    Ok(Options {
        embed_id,
        scope,
        version,
        resume,
    })
}

/// The core scope for `arg`; `found_chat` is the chat the core matched to the
/// embed, `team` the active Team of the session.
pub(super) fn scope(
    arg: &ScopeArg,
    found_chat: Option<String>,
    team: Option<String>,
) -> Result<RevisionScope, CliError> {
    Ok(match arg {
        ScopeArg::Project(project_id) => RevisionScope::Project {
            project_id: project_id.clone(),
            team_id: team,
        },
        ScopeArg::Chat(chat) => RevisionScope::Chat {
            chat_id: chat.clone().or(found_chat).ok_or_else(|| {
                refused(
                    "chat_unknown",
                    "The chat of this embed is not on this device. Pass --chat <chat-id>, or --project <project-id> for a Project file.",
                )
            })?,
            team_id: team,
        },
    })
}

fn scope_flags(arg: &ScopeArg) -> String {
    match arg {
        ScopeArg::Chat(Some(chat)) => format!(" --chat {chat}"),
        ScopeArg::Chat(None) => String::new(),
        ScopeArg::Project(project) => format!(" --project {project}"),
    }
}

/// User wording for a refused or failed version commit (restore).
pub(super) fn revision_error(error: UserRevisionError) -> CliError {
    let code = error.code();
    let message = match &error {
        UserRevisionError::VersionConflict {
            current_revision, ..
        } => format!(
            "The embed changed on another device{}. Run the command again.",
            current_revision
                .map(|v| format!(" (now version {v})"))
                .unwrap_or_default()
        ),
        UserRevisionError::ProjectContextRequired => {
            "This embed belongs to a Project. Run the command again with --project <project-id>.".into()
        }
        UserRevisionError::Validation {
            code: "invalid_restored_from",
        } => "Choose a version below the current version; the current version is already the default.".into(),
        UserRevisionError::Refused {
            code: "restore_source_missing",
        } => "That version is not stored for this embed.".into(),
        UserRevisionError::AccessDenied {
            code: "embed_type_not_editable",
        } => "This kind of embed cannot be edited.".into(),
        UserRevisionError::KeyUnavailable => {
            "The embed key is not available on this device. Open its chat first.".into()
        }
        UserRevisionError::Transport(error) => return CliError::Client(*error),
        other => format!("The version was not saved ({}).", other.code()),
    };
    refused(code, message)
}

/// User wording for an Enhance that produced no saved version. `resume` is the
/// command that saves an already finished result later.
pub(super) fn enhance_error(error: ImageEnhanceError, resume: &str) -> CliError {
    let code = error.code();
    let message = match error {
        ImageEnhanceError::InsufficientCredits => format!(
            "Not enough credits to enhance this image ({ENHANCE_CREDITS} credits). Nothing was charged."
        ),
        ImageEnhanceError::TeamUnavailable => "Enhance is not available for Team images yet.".into(),
        ImageEnhanceError::InvalidSource { code: "not_an_image" } => {
            "This embed is not an image; only images can be enhanced.".into()
        }
        ImageEnhanceError::InvalidSource { code } => {
            format!("This image cannot be enhanced ({code}). Nothing was charged.")
        }
        ImageEnhanceError::VersionConflict { current_version } => format!(
            "The image changed since it was loaded{}. Nothing was charged; run the command again.",
            current_version
                .map(|v| format!(" (now version {v})"))
                .unwrap_or_default()
        ),
        ImageEnhanceError::ProjectContextRequired => {
            "This image belongs to a Project. Run the command again with --project <project-id>.".into()
        }
        ImageEnhanceError::ScopeMismatch => {
            "This Enhance was started in another place. Resume it with the same --chat or --project.".into()
        }
        ImageEnhanceError::Failed { operation_id, code } => {
            format!("Enhance failed ({code}); nothing was charged. Operation: {operation_id}")
        }
        ImageEnhanceError::Expired { operation_id } => format!(
            "The Enhance result was not saved within 24 hours and is gone. Operation: {operation_id}"
        ),
        ImageEnhanceError::NotReady { operation_id } | ImageEnhanceError::Timeout { operation_id } => {
            format!(
                "Enhance is still running (operation {operation_id}). Save the result when it is ready with:\n  {resume} --resume {operation_id}"
            )
        }
        ImageEnhanceError::RateLimited => {
            "Too many Enhance requests (10 per minute, 100 per day). Try again later.".into()
        }
        ImageEnhanceError::Busy => "The Enhance job is being updated. Run the command again.".into(),
        ImageEnhanceError::KeyUnavailable => {
            "The image key is not available on this device. Open its chat first.".into()
        }
        ImageEnhanceError::Revision(error) => return revision_error(error),
        ImageEnhanceError::Transport(error) => return CliError::Client(error),
        other => format!("The image was not enhanced ({}).", other.code()),
    };
    refused(code, message)
}

fn event_text(event: &EventDelivery) -> String {
    match event {
        EventDelivery::Written => "written".into(),
        EventDelivery::AlreadyWritten => "already shown".into(),
        EventDelivery::NoChat => "none (the embed has no chat)".into(),
        EventDelivery::Deferred { code } => {
            format!("deferred ({code}); it appears the next time the chat is opened")
        }
    }
}

fn event_json(event: &EventDelivery) -> Result<Value, CliError> {
    serde_json::to_value(event).map_err(|_| CliError::Client(Error::Protocol))
}

fn render(json_mode: bool, value: Value, text: String) -> Result<CliOutput, CliError> {
    if json_mode {
        CliOutput::json(&value)
    } else {
        Ok(CliOutput::text(text))
    }
}

/// Output of a committed restore.
pub(super) fn restore_output(
    json_mode: bool,
    outcome: &EmbedRevisionOutcome,
) -> Result<CliOutput, CliError> {
    let c = &outcome.commit.committed;
    let from = c.restored_from.unwrap_or_default();
    let mut text = format!(
        "Restored version {from} of {} as new version {}.\nChat notice: {}",
        c.embed_id,
        c.version,
        event_text(&outcome.event)
    );
    if !outcome.commit.cache_synchronized {
        text.push_str("\nReload the embed before the next edit.");
    }
    render(
        json_mode,
        json!({
            "embed_id": c.embed_id, "action": "restore", "version": c.version,
            "base_version": c.base_version, "restored_from": c.restored_from,
            "revision_origin": "user", "idempotent": c.idempotent,
            "chat_event": event_json(&outcome.event)?,
        }),
        text,
    )
}

/// Output of a saved (or earlier saved) Enhance result.
pub(super) fn enhance_output(
    json_mode: bool,
    embed_id: &str,
    saved: &ImageEnhanceSaved,
) -> Result<CliOutput, CliError> {
    match saved {
        ImageEnhanceSaved::Committed {
            operation_id,
            outcome,
        } => {
            let c = &outcome.commit.committed;
            let text = format!(
                "Image enhanced: saved as version {} of {embed_id} (about 2K, same picture).\nChat notice: {}",
                c.version,
                event_text(&outcome.event)
            );
            render(
                json_mode,
                json!({
                    "embed_id": embed_id, "operation_id": operation_id, "state": "committed",
                    "action": "enhance", "version": c.version, "base_version": c.base_version,
                    "revision_origin": "user", "idempotent": c.idempotent,
                    "chat_event": event_json(&outcome.event)?,
                }),
                text,
            )
        }
        ImageEnhanceSaved::AlreadyCommitted {
            operation_id,
            version,
        } => render(
            json_mode,
            json!({
                "embed_id": embed_id, "operation_id": operation_id, "state": "already_committed",
                "action": "enhance", "version": version, "revision_origin": "user",
                "chat_event": {"state": "deferred", "code": "already_committed"},
            }),
            format!(
                "This Enhance result was already saved as version {version} of {embed_id}.\nChat notice: written by the next chat open"
            ),
        ),
    }
}

/// Run `embeds enhance` / `embeds restore` on the signed-in Personal session.
///
/// # Errors
/// Argument errors before any request; the core's user-revision and Enhance
/// refusals as `CliError::Contract` with the core's stable code.
pub(super) async fn execute(
    i: &Invocation,
    client: &mut Client,
    cancel: CancellationToken,
) -> Result<CliOutput, CliError> {
    let options = parse(i)?;
    if cancel.is_cancelled() {
        return Err(Error::Cancelled.into());
    }
    let team = client
        .session()
        .ok_or(Error::Expired)?
        .active_team_id
        .clone();
    client.set_operation_cancel(cancel.clone());
    let (head, found_chat) = client
        .embed_user_edit_head(&options.embed_id)
        .await
        .map_err(revision_error)?;
    let scope = scope(&options.scope, found_chat, team)?;
    let json_mode = i.boolean("json");
    if let Some(from) = options.version {
        let outcome = client
            .restore_embed_version(head, scope, from, None)
            .await
            .map_err(revision_error)?;
        return restore_output(json_mode, &outcome);
    }
    let resume_command = format!(
        "openmates embeds enhance {}{}",
        options.embed_id,
        scope_flags(&options.scope)
    );
    let saved = match options.resume.as_deref() {
        Some(operation_id) => {
            progress(&format!("Saving Enhance result {operation_id}…"));
            client
                .save_image_enhance_result(head, scope, operation_id, None)
                .await
        }
        None => {
            // The shell keeps the job id so a timeout can name it for --resume.
            let operation_id = uuid::Uuid::new_v4().to_string();
            progress(&format!(
                "Enhancing image (version {}, {ENHANCE_CREDITS} credits, up to {} minutes)… operation {operation_id}",
                head.version,
                DEFAULT_ENHANCE_DEADLINE.as_secs() / 60
            ));
            client
                .enhance_image(head, scope, Some(&operation_id), None, None)
                .await
        }
    }
    .map_err(|error| enhance_error(error, &resume_command))?;
    enhance_output(json_mode, &options.embed_id, &saved)
}

/// A boxed command future built outside the caller's poll frame.
pub(super) type CliFuture<'a, T> =
    std::pin::Pin<Box<dyn std::future::Future<Output = T> + Send + 'a>>;

/// [`execute`] boxed in its own frame: the dispatcher's future stays within
/// its stack bound (the Enhance future is large and must not be built on the
/// dispatcher's stack first).
#[inline(never)]
pub(super) fn execute_boxed<'a>(
    i: &'a Invocation,
    client: &'a mut Client,
    cancel: CancellationToken,
) -> CliFuture<'a, Result<CliOutput, CliError>> {
    Box::pin(execute(i, client, cancel))
}

fn progress(line: &str) {
    // Progress goes to stderr so --json stdout stays one JSON document.
    let mut stderr = std::io::stderr();
    let _ = writeln!(stderr, "{line}");
    let _ = stderr.flush();
}

#[cfg(test)]
#[path = "embed_user_edit_cmd_tests.rs"]
mod tests;
