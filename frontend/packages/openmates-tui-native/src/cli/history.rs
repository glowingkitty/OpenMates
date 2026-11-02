//! Preserve the shared legacy object-history output and restore selector contract.
use super::{CliError, CliOutput, Invocation, task_input as input};
use serde_json::{Value, json};
/// Search scripting output is the original raw ChatListItem array, rather
/// than the paginated `chats` envelope used by list commands.
pub(super) fn chat_search_output(i: &Invocation, rows: Vec<Value>) -> Result<CliOutput, CliError> {
    if i.boolean("json") {
        return CliOutput::json(&json!(rows));
    }
    if rows.is_empty() {
        return Ok(CliOutput::text("No chats found."));
    }
    let count = rows.len();
    let mut out = format!("Chats 1–{count} of {count}  (page 1/1)\n\n");
    for row in rows {
        let timestamp = row["updatedAt"]
            .as_f64()
            .filter(|v| v.is_finite() && *v != 0.0)
            .and_then(|v| {
                time::OffsetDateTime::from_unix_timestamp_nanos((v * 1_000_000_000.0) as i128).ok()
            })
            .map(|d| {
                format!(
                    "{:04}-{:02}-{:02} {:02}:{:02} UTC",
                    d.year(),
                    u8::from(d.month()),
                    d.day(),
                    d.hour(),
                    d.minute()
                )
            })
            .unwrap_or_else(|| "—".into());
        out.push_str(&format!(
            "    {timestamp}\n{}\n",
            row["title"].as_str().unwrap_or("(no title)")
        ));
        if let Some(summary) = row["summary"].as_str().filter(|s| !s.is_empty()) {
            out.push_str(summary);
            out.push('\n');
        }
        let handle = row["slug"]
            .as_str()
            .filter(|s| !s.is_empty())
            .or(row["shortId"].as_str())
            .ok_or(CliError::Client(crate::error::Error::Protocol))?;
        out.push_str(&format!(
            "→ openmates chats show {handle}\n{}\n",
            "─".repeat(60)
        ));
    }
    Ok(CliOutput::text(out))
}
pub(super) fn output(i: &Invocation, entries: Vec<Value>) -> Result<CliOutput, CliError> {
    if i.boolean("json") {
        return CliOutput::json(&json!({"entries":entries}));
    }
    if entries.is_empty() {
        return Ok(CliOutput::text("No history entries found."));
    }
    fn value(entry: &Value, key: &str) -> String {
        match &entry[key] {
            Value::String(value) => value.clone(),
            Value::Null => "-".into(),
            value => value.to_string(),
        }
    }
    Ok(CliOutput::text(
        entries
            .iter()
            .map(|entry| {
                format!(
                    "{}  {}  {}  v{} -> v{}",
                    value(entry, "entry_id"),
                    value(entry, "object_type"),
                    value(entry, "operation"),
                    value(entry, "version_before"),
                    value(entry, "version_after")
                )
            })
            .collect::<Vec<_>>()
            .join("\n"),
    ))
}
pub(super) fn entry(i: &Invocation) -> Result<&str, CliError> {
    input::text(i, "entry")?
        .or(input::text(i, "entry-id")?)
        .or(i.positionals.get(1).map(String::as_str))
        .filter(|v| !v.is_empty())
        .ok_or_else(|| CliError::Invalid("Provide --entry <history-entry-id>.".into()))
}
#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn chat_search_keeps_raw_array_nulls_and_legacy_table_structure_without_terminal_injection() {
        let mut i = Invocation {
            path: vec!["chats".into(), "search".into()],
            positionals: vec!["query".into()],
            flags: Default::default(),
        };
        let rows = vec![
            json!({"id":"fixture","shortId":"fixture","slug":"fixture-handle","title":"Private\u{1b}[31m title","summary":"Full summary","updatedAt":1,"category":null}),
        ];
        i.flags.insert("json".into(), json!(true));
        let output = chat_search_output(&i, rows.clone()).ok().unwrap();
        assert_eq!(
            serde_json::from_str::<Value>(&output.stdout).unwrap(),
            json!(rows)
        );
        assert!(output.stderr.is_empty());
        i.flags.remove("json");
        let output = chat_search_output(&i, rows).ok().unwrap();
        assert!(output.stdout.starts_with("Chats 1–1 of 1  (page 1/1)\n\n"));
        assert!(output.stdout.contains("1970-01-01 00:00 UTC"));
        assert!(
            output
                .stdout
                .contains("Full summary\n→ openmates chats show fixture-handle")
        );
        assert!(!output.stdout.contains('\u{1b}'));
        assert!(output.stdout.contains("\\u001b"));
        assert_eq!(
            chat_search_output(&i, vec![]).ok().unwrap().stdout,
            "No chats found.\n"
        );
    }
    #[test]
    fn history_uses_entries_envelope_and_human_version_metadata() {
        let mut i = Invocation {
            path: vec!["tasks".into(), "history".into()],
            positionals: vec![],
            flags: Default::default(),
        };
        let entries = vec![
            json!({"entry_id":"history-a","object_type":"task","operation":"update","version_before":2,"version_after":3}),
        ];
        assert_eq!(
            output(&i, entries.clone()).ok().unwrap().stdout,
            "history-a  task  update  v2 -> v3\n"
        );
        i.flags.insert("json".into(), json!(true));
        let value: Value =
            serde_json::from_str(&output(&i, entries.clone()).ok().unwrap().stdout).unwrap();
        assert_eq!(value["entries"], json!(entries));
        assert!(value.get("history").is_none());
        i.flags.insert("entry-id".into(), json!("retained-id"));
        assert_eq!(entry(&i).ok(), Some("retained-id"));
    }
}
