//! `settings memories` commands over the SDK's locally encrypted Personal
//! Memories, with the legacy CLI's flags, messages, JSON and human output.
use super::settings_more::text_output;
use super::{CliError, CliOutput, Invocation, handlers, path};
use crate::client::Client;
use serde_json::{Value, json};

pub(super) fn supported(invocation: &Invocation) -> bool {
    invocation.path.first().is_some_and(|p| p == "settings")
        && matches!(
            path(invocation).as_str(),
            "memories list"
                | "memories types"
                | "memories create"
                | "memories update"
                | "memories delete"
        )
}
/// Typed app memories were replaced by Memories (personal documents).
const TYPED_MEMORIES_REMOVED: &str = "Typed app memories were replaced by Memories (personal documents). Manage them in the web app under Settings > Memories.";
fn flag<'a>(i: &'a Invocation, name: &str) -> Option<&'a str> {
    i.text(name).filter(|v| !v.is_empty())
}
fn fail(message: &str) -> CliError {
    CliError::Invalid(message.into())
}
fn kv(out: &mut String, key: &str, value: &str, width: usize) {
    out.push_str(&format!(
        "  \x1b[2m{:<width$}\x1b[0m {}\n",
        key,
        super::super::terminal_text(value)
    ));
}
/// Legacy formatTimestamp layout ("—" for 0). The native crate renders UTC;
/// the legacy CLI used the host time zone.
fn timestamp(seconds: i64) -> String {
    if seconds == 0 {
        return "—".into();
    }
    let Ok(local) = time::OffsetDateTime::from_unix_timestamp(seconds) else {
        return "—".into();
    };
    format!(
        "{}-{:02}-{:02} {:02}:{:02}",
        local.year(),
        u8::from(local.month()),
        local.day(),
        local.hour(),
        local.minute()
    )
}
/// JavaScript `String(value)` for memory fields.
fn js_text(value: &Value) -> String {
    match value {
        Value::String(text) => text.clone(),
        Value::Array(items) => items.iter().map(js_text).collect::<Vec<_>>().join(","),
        Value::Object(_) => "[object Object]".into(),
        other => other.to_string(),
    }
}
fn list_text(memories: &[Value]) -> String {
    if memories.is_empty() {
        return "No memories found.\n".into();
    }
    let mut out = format!("\x1b[1mMemories  ({})\n\x1b[0m\n", memories.len());
    for memory in memories {
        let id = memory["id"].as_str().unwrap_or("");
        out.push_str(&format!(
            "\x1b[1m{}/{}\x1b[0m  \x1b[2mv{}  {}  id:{}\x1b[0m\n",
            super::super::terminal_text(memory["app_id"].as_str().unwrap_or("")),
            super::super::terminal_text(memory["item_type"].as_str().unwrap_or("")),
            js_text(&memory["item_version"]),
            timestamp(memory["updated_at"].as_i64().unwrap_or(0)),
            super::super::terminal_text(&id.chars().take(8).collect::<String>())
        ));
        for (key, value) in memory["data"].as_object().into_iter().flatten() {
            if !key.starts_with('_') && !value.is_null() {
                kv(&mut out, key, &js_text(value), 20);
            }
        }
        out.push('\n');
    }
    out
}

pub(super) async fn execute(i: &Invocation, client: &mut Client) -> Result<CliOutput, CliError> {
    let command = path(i);
    let json_output = i.boolean("json");
    match command.as_str() {
        "memories list" => {
            handlers::flags(i, &["app-id", "item-type"])?;
            let app = flag(i, "app-id");
            let item_type = flag(i, "item-type");
            let memories = client
                .account()
                .memories()
                .await?
                .into_iter()
                .filter(|m| app.is_none_or(|app| m["app_id"] == app))
                .filter(|m| item_type.is_none_or(|t| m["item_type"] == t))
                .collect::<Vec<_>>();
            if json_output {
                CliOutput::json(&Value::Array(memories))
            } else {
                Ok(text_output(list_text(&memories)))
            }
        }
        "memories types" | "memories create" | "memories update" => {
            handlers::flags(i, &["app-id", "item-type", "data", "id", "version"])?;
            let id = flag(i, "id").unwrap_or("");
            if command == "memories update" && id.starts_with("account-memory-") {
                return Err(CliError::Unsupported {
                    command: i.command_path(),
                    reason:
                        "Editing account Memory documents is not ported; edit it in the web app."
                            .into(),
                });
            }
            Err(fail(TYPED_MEMORIES_REMOVED))
        }
        "memories delete" => {
            handlers::flags(i, &["id"])?;
            let id = flag(i, "id")
                .or_else(|| i.positionals.first().map(String::as_str).filter(|v| !v.is_empty()))
                .ok_or_else(|| fail("Missing entry ID.\n\nUsage: openmates settings memories delete --id <entry-id>"))?;
            if id.starts_with("account-memory-") {
                return Err(CliError::Unsupported {
                    command: i.command_path(),
                    reason:
                        "Deleting account Memory documents is not ported; delete it in the web app."
                            .into(),
                });
            }
            let result = client.account().delete_memory(id).await?;
            if json_output {
                CliOutput::json(&result)
            } else {
                Ok(text_output("\x1b[32m✓\x1b[0m Memory deleted\n".into()))
            }
        }
        _ => Err(CliError::Unsupported {
            command: i.command_path(),
            reason: "Unknown memories action.".into(),
        }),
    }
}

#[cfg(test)]
#[path = "memories_tests.rs"]
mod tests;
