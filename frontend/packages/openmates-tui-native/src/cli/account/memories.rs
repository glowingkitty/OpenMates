//! `settings memories` commands over the SDK's locally encrypted Personal
//! Memories, with the legacy CLI's flags, messages, JSON and human output.
use super::settings_more::text_output;
use super::{CliError, CliOutput, Invocation, handlers, path};
use crate::client::Client;
use openmates_sdk::account::{memory_types, validate_memory};
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
fn flag<'a>(i: &'a Invocation, name: &str) -> Option<&'a str> {
    i.text(name).filter(|v| !v.is_empty())
}
fn fail(message: &str) -> CliError {
    CliError::Invalid(message.into())
}
/// Legacy `JSON.parse(--data)` input.
fn data(i: &Invocation) -> Result<Value, CliError> {
    let raw = flag(i, "data").ok_or_else(|| {
        fail("Missing --data '<json>'. Provide the memory field values as a JSON object.\n\nExample: --data '{\"name\":\"Python\",\"proficiency\":\"advanced\"}'")
    })?;
    serde_json::from_str(raw).map_err(|_| fail("--data must be valid JSON."))
}
fn types_json(app: Option<&str>) -> Value {
    Value::Array(
        memory_types()
            .iter()
            .filter(|t| app.is_none_or(|app| t.app_id == app))
            .map(|t| {
                json!({"key":t.key,"app_id":t.app_id,"item_type":t.item_type,"entry_type":t.entry_type,
                    "required":t.required,"properties":t.properties.iter().map(|p| p.name.as_str()).collect::<Vec<_>>()})
            })
            .collect(),
    )
}
fn kv(out: &mut String, key: &str, value: &str, width: usize) {
    out.push_str(&format!(
        "  \x1b[2m{:<width$}\x1b[0m {}\n",
        key,
        super::super::terminal_text(value)
    ));
}
fn types_text(types: &[Value]) -> String {
    if types.is_empty() {
        return "No memory types found.\n".into();
    }
    let mut out = format!("\x1b[1mMemory types  ({})\n\x1b[0m\n", types.len());
    let mut last = "";
    for t in types {
        let app = t["app_id"].as_str().unwrap_or("");
        if app != last {
            if !last.is_empty() {
                out.push('\n');
            }
            out.push_str(&format!("\x1b[1m{app}\x1b[0m\n"));
            last = app;
        }
        out.push_str(&format!(
            "  \x1b[36m{}\x1b[0m  \x1b[2m{}\x1b[0m\n",
            t["item_type"].as_str().unwrap_or(""),
            t["entry_type"].as_str().unwrap_or("")
        ));
        let join = |field: &str| {
            t[field]
                .as_array()
                .into_iter()
                .flatten()
                .filter_map(Value::as_str)
                .collect::<Vec<_>>()
                .join(", ")
        };
        let required = join("required");
        kv(
            &mut out,
            "required",
            if required.is_empty() {
                "none"
            } else {
                &required
            },
            12,
        );
        kv(&mut out, "fields", &join("properties"), 12);
    }
    out.push_str("\n\x1b[2mCreate: openmates settings memories create --app-id <id> --item-type <type> --data '<json>'\x1b[0m\n");
    out
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
        "memories types" => {
            handlers::flags(i, &["app-id"])?;
            let types = types_json(flag(i, "app-id"));
            if json_output {
                CliOutput::json(&types)
            } else {
                Ok(text_output(types_text(
                    types.as_array().map(Vec::as_slice).unwrap_or(&[]),
                )))
            }
        }
        "memories create" | "memories update" => {
            let update = command == "memories update";
            handlers::flags(i, &["app-id", "item-type", "data", "id", "version"])?;
            let app = flag(i, "app-id").unwrap_or("");
            let item_type = flag(i, "item-type").unwrap_or("");
            let id = flag(i, "id").unwrap_or("");
            if app.is_empty() || item_type.is_empty() || (update && id.is_empty()) {
                return Err(fail(if update {
                    "Missing required flags.\n\nUsage: openmates settings memories update --id <entry-id> --app-id <id> --item-type <type> --data '<json>' [--version <n>]"
                } else {
                    "Missing required flags.\n\nUsage: openmates settings memories create --app-id <id> --item-type <type> --data '<json>'\n\nRun 'openmates settings memories types' to see all available types."
                }));
            }
            let value = if update {
                let raw = flag(i, "data").ok_or_else(|| fail("Missing --data '<json>'."))?;
                serde_json::from_str(raw).map_err(|_| fail("--data must be valid JSON."))?
            } else {
                data(i)?
            };
            if update && id.starts_with("account-memory-") {
                return Err(CliError::Unsupported {
                    command: i.command_path(),
                    reason:
                        "Editing account Memory documents is not ported; edit it in the web app."
                            .into(),
                });
            }
            validate_memory(app, item_type, &value).map_err(CliError::Invalid)?;
            let result = if update {
                // Legacy parseInt(--version, 10) with default 1.
                let version = match flag(i, "version") {
                    None => 1,
                    Some(raw) => raw
                        .trim()
                        .chars()
                        .take_while(char::is_ascii_digit)
                        .collect::<String>()
                        .parse::<u64>()
                        .map_err(|_| fail("--version must be a whole number."))?,
                };
                client
                    .account()
                    .update_memory(id, app, item_type, &value, version)
                    .await?
            } else {
                client
                    .account()
                    .create_memory(app, item_type, &value)
                    .await?
            };
            if json_output {
                CliOutput::json(&result)
            } else {
                Ok(text_output(format!(
                    "\x1b[32m✓\x1b[0m Memory {}  \x1b[2mid: {}\x1b[0m\n",
                    if update { "updated" } else { "created" },
                    result["id"].as_str().unwrap_or("")
                )))
            }
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
