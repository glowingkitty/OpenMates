//! `chats files|open|speak` (npm parity). Shared Rust owns the selected-chat
//! read, embed walk, file projection, speech projection and speech protocol;
//! this adapter parses flags, renders the preserved output and opens the
//! browser. All three require an authenticated native session.
use super::super::{CliError, CliOutput, Invocation, handlers, terminal_text};
use crate::{client::Client, error::Error, model::Workspace};
use openmates_sdk::client::{
    assistant_speech::{AssistantSpeechSummary, SpeechSelection},
    chat_files::ChatFiles,
};
use serde_json::{Value, json};
use tokio_util::sync::CancellationToken;

const COMMANDS: &[&str] = &["chats files", "chats open", "chats speak"];

pub(super) fn supported(invocation: &Invocation) -> bool {
    COMMANDS.contains(&invocation.command_path().as_str())
}

pub(super) async fn execute(
    invocation: &Invocation,
    client: &mut Client,
    cancel: CancellationToken,
) -> Result<CliOutput, CliError> {
    client.set_operation_cancel(cancel.clone());
    match invocation.command_path().as_str() {
        "chats files" => {
            handlers::flags(invocation, &[])?;
            let chat_id = chat_id(
                invocation,
                "Missing chat ID. Usage: openmates chats files <chat-id> [--json]",
            )?;
            if invocation.has("api-key") {
                return Err(CliError::Invalid("Chat file listing through --api-key is not supported; use an authenticated CLI session so encrypted chat embeds can be decrypted locally.".into()));
            }
            canonical(invocation, &chat_id)?;
            let files = cancellable(&cancel, client.chat_files(&chat_id)).await?;
            files_output(invocation, &files)
        }
        "chats speak" => {
            handlers::flags(invocation, &["message", "all"])?;
            if invocation.has("api-key") {
                return Err(CliError::Invalid("Chat speech through --api-key is not supported; use an authenticated CLI session.".into()));
            }
            let chat_id = chat_id(invocation, "Missing <chat-id>.")?;
            canonical(invocation, &chat_id)?;
            let selection = SpeechSelection {
                message_id: invocation.text("message").map(str::to_owned),
                all: invocation.boolean("all"),
            };
            let summary = cancellable(
                &cancel,
                client.generate_existing_assistant_speech(&chat_id, &selection),
            )
            .await?;
            speak_output(invocation, &summary)
        }
        _ => {
            handlers::flags(invocation, &[])?;
            if invocation.has("api-key") {
                return Err(CliError::Unsupported {
                    command: invocation.command_path(),
                    reason: "API-key chat open is not ported; Cookie credentials were not used as a fallback.".into(),
                });
            }
            let position = open_position(invocation)?;
            let items = open_inventory(client, &cancel).await?;
            let target = open_target(&items, position)?;
            let url = format!(
                "{}/#chat-id={}",
                client.application_url().trim_end_matches('/'),
                target.id
            );
            let opened = open_browser(&url);
            open_output(invocation, position, &target, &url, opened)
        }
    }
}

async fn cancellable<T>(
    cancel: &CancellationToken,
    future: impl Future<Output = Result<T, Error>>,
) -> Result<T, CliError> {
    tokio::select! {
        () = cancel.cancelled() => Err(CliError::Client(Error::Cancelled)),
        result = future => result.map_err(CliError::Client),
    }
}

fn chat_id(invocation: &Invocation, missing: &str) -> Result<String, CliError> {
    match invocation.positionals.as_slice() {
        [] => Err(CliError::Invalid(missing.into())),
        [id] if id.trim().is_empty() => Err(CliError::Invalid(missing.into())),
        [id] => Ok(id.trim().to_owned()),
        _ => Err(CliError::Invalid(format!(
            "Unexpected arguments for openmates {}.",
            invocation.command_path()
        ))),
    }
}

/// Only full canonical chat IDs are admitted; `last`, prefixes and titles
/// would need the cached census resolver, which is not ported.
fn canonical(invocation: &Invocation, id: &str) -> Result<(), CliError> {
    if uuid::Uuid::parse_str(id).is_ok_and(|parsed| parsed.hyphenated().to_string() == id) {
        return Ok(());
    }
    Err(CliError::Unsupported {
        command: invocation.command_path(),
        reason: "Only a canonical full chat ID is supported natively; `last`, short IDs and titles are not ported.".into(),
    })
}

pub(super) fn files_output(
    invocation: &Invocation,
    result: &ChatFiles,
) -> Result<CliOutput, CliError> {
    let errors: Vec<Value> = result
        .errors
        .iter()
        .map(|e| json!({"embed_id": e.embed_id, "message": e.message}))
        .collect();
    if invocation.boolean("json") {
        return CliOutput::json(&json!({
            "chat_id": result.chat_id,
            "title": (!result.title.is_empty()).then_some(&result.title),
            "source": "chat",
            "count": result.files.len(),
            "files": result.files.iter().map(|f| f.to_json()).collect::<Vec<_>>(),
            "errors": errors,
        }));
    }
    let title = if result.title.is_empty() {
        &result.chat_id
    } else {
        &result.title
    };
    let mut text = format!("Files for {title}\n");
    if result.files.is_empty() {
        text.push_str("No files found for this chat.\n");
    }
    for file in &result.files {
        let app_skill = [file.app_id.as_deref(), file.skill_id.as_deref()]
            .into_iter()
            .flatten()
            .filter(|v| !v.is_empty())
            .collect::<Vec<_>>()
            .join("/");
        let suffix = if app_skill.is_empty() {
            String::new()
        } else {
            format!("  {app_skill}")
        };
        text.push_str(&format!("  {}  {}{suffix}\n", file.title, file.metadata));
        let url = file
            .url
            .as_deref()
            .map(|u| format!("  {u}"))
            .unwrap_or_default();
        text.push_str(&format!("    {}{url}\n", file.content_ref));
    }
    let mut output = CliOutput::text(text);
    output.stderr = result
        .errors
        .iter()
        .map(|e| {
            terminal_text(&format!(
                "Warning: could not inspect embed {}: {}\n",
                e.embed_id, e.message
            ))
        })
        .collect();
    Ok(output)
}

pub(super) fn speak_output(
    invocation: &Invocation,
    summary: &AssistantSpeechSummary,
) -> Result<CliOutput, CliError> {
    let value = serde_json::to_value(summary).map_err(|_| CliError::Client(Error::Protocol))?;
    let mut output = handlers::output(
        invocation,
        value,
        format!(
            "Assistant speech saved for {} message(s).\nGenerated {}, reused {}, failed {}.",
            summary.messages,
            summary.generated_segments,
            summary.reused_segments,
            summary.failed_segments
        ),
    )?;
    if summary.failed_segments > 0 {
        output.exit_code = 1;
    }
    Ok(output)
}

/// `[n]` like the preserved `parseInt`: leading digits, default 1, at least 1.
/// architecture.sync: a cached feed cursor replays only the changes since the
/// last sync (its first page was prefetched during session admission); a
/// missing/expired cursor keeps the ordinary bounded chat sync.
async fn open_inventory(
    client: &mut Client,
    cancel: &CancellationToken,
) -> Result<Vec<crate::model::Item>, CliError> {
    if client.has_chat_sync_cursor() {
        if let Some(items) = cancellable(cancel, client.chat_list_from_feed()).await? {
            return Ok(items);
        }
    }
    let items = cancellable(cancel, client.list(Workspace::Chats)).await?;
    Ok(client.order_chat_list_items_now(items))
}

pub(super) fn open_position(invocation: &Invocation) -> Result<usize, CliError> {
    let raw = match invocation.positionals.as_slice() {
        [] => return Ok(1),
        [raw] => raw,
        _ => {
            return Err(CliError::Invalid(
                "Unexpected arguments for openmates chats open.".into(),
            ));
        }
    };
    let trimmed = raw.trim_start();
    let unsigned = trimmed.strip_prefix('+').unwrap_or(trimmed);
    let digits: String = unsigned.chars().take_while(char::is_ascii_digit).collect();
    match digits.parse::<usize>() {
        Ok(n) if n >= 1 => Ok(n),
        _ => Err(CliError::Invalid(format!(
            "Invalid position '{raw}'. Must be a positive integer (1 = most recent, 2 = second most recent, ...)."
        ))),
    }
}

pub(super) struct OpenTarget {
    pub(super) id: String,
    pub(super) title: Option<String>,
}

pub(super) fn open_target(
    items: &[crate::model::Item],
    position: usize,
) -> Result<OpenTarget, CliError> {
    if items.is_empty() {
        return Err(CliError::Invalid(
            "No chats found. Run 'openmates chats list' to sync.".into(),
        ));
    }
    let Some(item) = items.get(position - 1) else {
        return Err(CliError::Invalid(format!(
            "Only {} chat(s) available — cannot open chat #{position}.",
            items.len()
        )));
    };
    let title = match item.fields.get("chat_list_title") {
        Some(Value::String(title)) if !title.is_empty() => Some(title.clone()),
        _ => None,
    };
    Ok(OpenTarget {
        id: item.id.clone(),
        title,
    })
}

/// `chats open [n]` under an explicit `--api-key`: the n-th owned chat from
/// the server's `/v1/sdk/chats` order (pinned, then most recently updated),
/// with its locally decrypted title. Only signed-in positions are supported.
pub(super) async fn execute_open_key(
    invocation: &Invocation,
    sdk: &mut openmates_sdk::sdk::OpenMates,
) -> Result<CliOutput, CliError> {
    handlers::flags(invocation, &[])?;
    let position = open_position(invocation)?;
    let limit = u32::try_from(position)
        .ok()
        .filter(|n| *n <= 1000)
        .ok_or_else(|| CliError::Invalid(format!("Chat position #{position} is beyond the 1000-chat server window.")))?;
    let chats = sdk
        .chats()
        .list(openmates_sdk::sdk_chats::ChatListOptions { limit, offset: 0 })
        .await?;
    let target = key_open_target(&chats, position)?;
    let url = format!("{}/#chat-id={}", sdk.web_origin().trim_end_matches('/'), target.id);
    let opened = open_browser(&url);
    open_output(invocation, position, &target, &url, opened)
}

/// Same "no chats" / "only N" wording as the session `open_target`.
pub(super) fn key_open_target(chats: &[Value], position: usize) -> Result<OpenTarget, CliError> {
    if chats.is_empty() {
        return Err(CliError::Invalid(
            "No chats found. Run 'openmates chats list' to sync.".into(),
        ));
    }
    let Some(chat) = chats.get(position - 1) else {
        return Err(CliError::Invalid(format!(
            "Only {} chat(s) available — cannot open chat #{position}.",
            chats.len()
        )));
    };
    let id = chat["id"].as_str().filter(|id| !id.is_empty()).ok_or(CliError::Client(Error::Protocol))?;
    Ok(OpenTarget {
        id: id.to_owned(),
        title: chat["title"].as_str().filter(|t| !t.is_empty()).map(str::to_owned),
    })
}

/// Same validated opener as the TUI: http(s) only, no embedded credentials.
fn open_browser(url: &str) -> bool {
    url::Url::parse(url).ok().is_some_and(|parsed| {
        matches!(parsed.scheme(), "https" | "http")
            && parsed.username().is_empty()
            && parsed.password().is_none()
    }) && webbrowser::open(url).is_ok()
}

pub(super) fn open_output(
    invocation: &Invocation,
    position: usize,
    target: &OpenTarget,
    url: &str,
    opened: bool,
) -> Result<CliOutput, CliError> {
    let json_mode = invocation.boolean("json");
    let mut output = if json_mode {
        CliOutput::json(
            &json!({"url": url, "chat_id": target.id, "position": position, "title": target.title}),
        )?
    } else if opened {
        CliOutput {
            stdout: String::new(),
            stderr: String::new(),
            exit_code: 0,
        }
    } else {
        // The browser could not be started: print the URL to open manually.
        CliOutput::text(url)
    };
    let label = match &target.title {
        Some(title) => format!("\"{title}\""),
        None => target.id.chars().take(8).collect(),
    };
    if !json_mode {
        output.stderr = terminal_text(&format!("Opening chat #{position}: {label}\n"));
    } else if !opened {
        output.stderr = terminal_text(&format!(
            "Could not open a browser. Open this URL manually: {url}\n"
        ));
    }
    Ok(output)
}

#[cfg(test)]
#[path = "chat_media_tests.rs"]
mod tests;
