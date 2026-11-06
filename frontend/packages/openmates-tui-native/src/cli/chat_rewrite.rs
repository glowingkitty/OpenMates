//! `chats fork|rewind|retry` (npm parity). Parsing and rendering only; the
//! encrypted read, fork payload and rewind request live in shared Rust.
use super::super::{CliError, CliOutput, Invocation, handlers, send};
use crate::client::Client;
use openmates_sdk::client::{SendOptions, chat_rewrite::ChatRewriteState};
use serde_json::Value;
use tokio::sync::mpsc;
use tokio_util::sync::CancellationToken;

const FORK_USAGE: &str = "Missing fork target. Usage: openmates chats fork <chat-id> --from-message <message-id> [--title <title>] [--json]";
const REWIND_USAGE: &str = "Missing rewind target. Usage: openmates chats rewind <chat-id> --to-message <message-id> [--send <prompt>] [--dry-run] [--yes] [--json]";
const RETRY_USAGE: &str = "Missing chat ID. Usage: openmates chats retry <chat-id> [--dry-run] [--yes] [--json]";

pub(super) fn supported(invocation: &Invocation) -> bool {
    matches!(
        invocation.command_path().as_str(),
        "chats fork" | "chats rewind" | "chats retry"
    )
}

pub(super) async fn execute(
    invocation: &Invocation,
    client: &mut Client,
    cancel: CancellationToken,
) -> Result<CliOutput, CliError> {
    match invocation.command_path().as_str() {
        "chats fork" => fork(invocation, client).await,
        "chats rewind" => rewind(invocation, client, cancel).await,
        _ => retry(invocation, client, cancel).await,
    }
}

fn nonempty<'a>(value: Option<&'a str>) -> Option<&'a str> {
    value.filter(|s| !s.is_empty())
}
/// One-shot commands perform no account sync, so `last`, prefixes and slugs
/// (resolved by npm from its synced cache) are not selectors here.
fn chat_id<'a>(i: &'a Invocation, target: bool, usage: &str) -> Result<&'a str, CliError> {
    match nonempty(i.positionals.first().map(String::as_str)) {
        Some(id) if target => Ok(id),
        _ => Err(CliError::Invalid(usage.into())),
    }
}
fn admit(i: &Invocation, id: &str) -> Result<(), CliError> {
    if i.has("api-key") {
        // Explicit-key invocations are routed to `execute_key` by the runtime;
        // reaching the session adapter with a key must never mix credentials.
        return Err(CliError::Unsupported {
            command: i.command_path(),
            reason: "API-key chat fork, rewind and retry run only through the explicit-key route; Cookie credentials were not used as a fallback.".into(),
        });
    }
    canonical(id)
}
fn canonical(id: &str) -> Result<(), CliError> {
    if uuid::Uuid::parse_str(id)
        .ok()
        .is_none_or(|parsed| parsed.hyphenated().to_string() != id)
    {
        return Err(CliError::Invalid("A canonical full chat ID is required.".into()));
    }
    Ok(())
}
fn boundary(state: &ChatRewriteState, message_id: &str) -> Result<usize, CliError> {
    state
        .boundary_index(message_id)
        // Runtime lookup failure: exit 1 like npm's thrown error.
        .ok_or_else(|| CliError::Contract {
            code: "command_failed",
            message: format!("Message '{message_id}' was not found in the chat."),
        })
}
/// JavaScript `String(value)` for the scalar fields npm prints.
fn js(value: Option<&Value>) -> String {
    match value {
        None => "undefined".into(),
        Some(Value::String(s)) => s.clone(),
        Some(other) => other.to_string(),
    }
}
fn dry_run(i: &Invocation) -> bool {
    i.boolean("dry-run") || !i.boolean("yes")
}

/// Saved-chat send is not in the Rust API-key SDK, so a step that would resend
/// is refused before any server mutation instead of leaving a rewound chat.
const KEY_RESEND: &str = "needs saved-chat send, which the Rust API-key SDK does not implement yet; nothing was rewound and Cookie credentials were not used.";

/// `chats fork|rewind|retry` under an explicit `--api-key` (npm SDK
/// `chats.fork|rewind|retry` over `/v1/sdk/chats/{id}/...`).
pub(super) async fn execute_key(
    i: &Invocation,
    sdk: &mut openmates_sdk::sdk::OpenMates,
) -> Result<CliOutput, CliError> {
    match i.command_path().as_str() {
        "chats fork" => {
            handlers::flags(i, &["from-message", "title"])?;
            let from = nonempty(i.text("from-message"));
            let id = chat_id(i, from.is_some(), FORK_USAGE)?;
            canonical(id)?;
            let rewrite = sdk.chats().rewrite_state(id).await?;
            let index = boundary(rewrite.state(), from.unwrap_or_default())?;
            let result = sdk.chats().fork(&rewrite, index, i.text("title")).await?;
            let text = fork_text(&result);
            handlers::output(i, result, text)
        }
        "chats rewind" => {
            handlers::flags(i, &["to-message", "send", "dry-run", "yes"])?;
            let to = nonempty(i.text("to-message"));
            let id = chat_id(i, to.is_some(), REWIND_USAGE)?;
            canonical(id)?;
            let dry = dry_run(i);
            if !dry && nonempty(i.text("send")).is_some() {
                return Err(key_resend(i, "API-key rewind --send"));
            }
            let rewrite = sdk.chats().rewrite_state(id).await?;
            let index = boundary(rewrite.state(), to.unwrap_or_default())?;
            let result = sdk.chats().rewind(&rewrite, index, dry, i.boolean("yes")).await?;
            let text = rewind_text(&result);
            handlers::output(i, result, text)
        }
        _ => {
            handlers::flags(i, &["dry-run", "yes"])?;
            let id = chat_id(i, true, RETRY_USAGE)?;
            canonical(id)?;
            if !dry_run(i) {
                return Err(key_resend(i, "API-key retry --yes"));
            }
            let rewrite = sdk.chats().rewrite_state(id).await?;
            let (result, _) = sdk.chats().retry(&rewrite, true, i.boolean("yes")).await?;
            let text = rewind_text(&result);
            handlers::output(i, result, text)
        }
    }
}
fn key_resend(i: &Invocation, what: &str) -> CliError {
    CliError::Unsupported {
        command: i.command_path(),
        reason: format!("{what} {KEY_RESEND}"),
    }
}

async fn fork(i: &Invocation, client: &mut Client) -> Result<CliOutput, CliError> {
    handlers::flags(i, &["from-message", "title"])?;
    let from = nonempty(i.text("from-message"));
    let id = chat_id(i, from.is_some(), FORK_USAGE)?;
    let from = from.unwrap_or_default();
    admit(i, id)?;
    let state = client.chat_rewrite_state(id).await?;
    let index = boundary(&state, from)?;
    let result = client.fork_chat(&state, index, i.text("title")).await?;
    let text = fork_text(&result);
    handlers::output(i, result, text)
}
pub(super) fn fork_text(result: &Value) -> String {
    format!(
        "Forked chat {} ({} messages copied)",
        js(result.get("chat_id")),
        js(result.get("copied_message_count"))
    )
}

async fn rewind(i: &Invocation, client: &mut Client, cancel: CancellationToken) -> Result<CliOutput, CliError> {
    handlers::flags(i, &["to-message", "send", "dry-run", "yes"])?;
    let to = nonempty(i.text("to-message"));
    let id = chat_id(i, to.is_some(), REWIND_USAGE)?;
    let to = to.unwrap_or_default();
    admit(i, id)?;
    let dry = dry_run(i);
    let prompt = i.text("send").filter(|s| !dry && !s.is_empty());
    let prompt = match prompt {
        Some(text) => {
            let resolved = client.resolve_mentions(text).await?;
            if let Some(message) = send::unresolved_mentions_message(&resolved.unresolved) {
                return Err(CliError::Contract { code: "unknown_mention", message });
            }
            Some(zeroize::Zeroizing::new(resolved.processed_message))
        }
        None => None,
    };
    let state = client.chat_rewrite_state(id).await?;
    let index = boundary(&state, to)?;
    let mut result = client.rewind_chat(&state, index, dry, i.boolean("yes")).await?;
    if let Some(prompt) = prompt {
        result["response"] = resend(client, state.chat_id(), &prompt, cancel).await?;
    }
    let text = rewind_text(&result);
    handlers::output(i, result, text)
}

async fn retry(i: &Invocation, client: &mut Client, cancel: CancellationToken) -> Result<CliOutput, CliError> {
    handlers::flags(i, &["dry-run", "yes"])?;
    let id = chat_id(i, true, RETRY_USAGE)?;
    admit(i, id)?;
    let state = client.chat_rewrite_state(id).await?;
    let (mut result, prompt) = client.retry_chat(&state, dry_run(i), i.boolean("yes")).await?;
    if let Some(prompt) = prompt {
        result["response"] = resend(client, state.chat_id(), &prompt, cancel).await?;
    }
    let text = rewind_text(&result);
    handlers::output(i, result, text)
}

/// The follow-up turn after a confirmed rewind; its JSON matches `chats send`.
async fn resend(client: &mut Client, chat_id: &str, prompt: &str, cancel: CancellationToken) -> Result<Value, CliError> {
    let (tx, mut updates) = mpsc::channel(64);
    let operation = client.send(Some(chat_id), prompt, SendOptions::default(), tx, cancel);
    tokio::pin!(operation);
    let mut open = true;
    loop {
        tokio::select! {
            result = &mut operation => return send::outcome_json(&result?),
            event = updates.recv(), if open => open = event.is_some(),
        }
    }
}

/// printChatRewindResult without ANSI styling.
pub(super) fn rewind_text(result: &Value) -> String {
    let dry = result.get("dry_run") == Some(&Value::Bool(true));
    let (count, ids) = if dry {
        ("planned_deleted_message_count", "planned_deleted_message_ids")
    } else {
        ("deleted_message_count", "deleted_message_ids")
    };
    let count = match result.get(count) {
        None | Some(Value::Null) => "0".to_owned(),
        Some(value) => js(Some(value)),
    };
    let chat = match result.get("chat_id") {
        None | Some(Value::Null) => String::new(),
        Some(value) => js(Some(value)),
    };
    let mut out = format!(
        "{} chat {chat}\n{} {count} message{}.\n",
        if dry { "Dry run" } else { "Rewound" },
        if dry { "Would delete" } else { "Deleted" },
        if count == "1" { "" } else { "s" },
    );
    if let Some(ids) = result.get(ids).and_then(Value::as_array).filter(|ids| !ids.is_empty()) {
        let ids: Vec<String> = ids.iter().map(|id| js(Some(id))).collect();
        out.push_str(&ids.join(", "));
        out.push('\n');
    }
    if let Some(response) = result.get("response").filter(|r| r.is_object())
        && let Some(assistant) = response.get("assistant")
    {
        let assistant = match assistant {
            Value::Null => String::new(),
            value => js(Some(value)),
        };
        out.push_str(&format!("\n{assistant}\n"));
    }
    if dry {
        out.push_str("\nRun again with --yes to apply this rewind.\n");
    }
    out
}

#[cfg(test)]
#[path = "chat_rewrite_tests.rs"]
mod tests;
