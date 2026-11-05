//! `newchatsuggestions [--limit <n>]`: the home-screen suggestions with the
//! legacy CLI's JSON array and ANSI text layout.
use super::settings_more::text_output;
use super::{CliError, CliOutput, Invocation, handlers};
use crate::client::Client;
use openmates_sdk::client::new_chat_suggestions::{NewChatSuggestion, js_parse_int};
use serde_json::Value;

pub(super) fn supported(invocation: &Invocation) -> bool {
    invocation.command_path() == "newchatsuggestions"
}
/// Legacy default 10; a string is `parseInt`-ed (NaN means no limit).
fn limit(i: &Invocation) -> Option<i64> {
    match i.flags.get("limit").and_then(Value::as_str) {
        Some(raw) => js_parse_int(raw),
        None => Some(10),
    }
}
fn text(suggestions: &[NewChatSuggestion]) -> String {
    if suggestions.is_empty() {
        return "No new chat suggestions available.\n\x1b[2mSuggestions are generated after your first few conversations.\x1b[0m\n".into();
    }
    let mut out = format!(
        "\x1b[1mNew Chat Suggestions  \x1b[2m({})\x1b[0m\n\x1b[0m\n",
        suggestions.len()
    );
    for (index, suggestion) in suggestions.iter().enumerate() {
        let body = super::super::terminal_text(&suggestion.body);
        out.push_str(&format!(
            "\x1b[1m{}.\x1b[0m {body}\n   \x1b[2mopenmates chats new \"{}\"\x1b[0m\n\n",
            index + 1,
            body.replace('"', "\\\"")
        ));
    }
    out.push_str("\x1b[2mStart a chat: openmates chats new \"<suggestion text>\"\x1b[0m\n");
    out
}
pub(super) async fn execute(i: &Invocation, client: &mut Client) -> Result<CliOutput, CliError> {
    handlers::flags(i, &["limit"])?;
    let suggestions = client.new_chat_suggestions(limit(i)).await?;
    if i.boolean("json") {
        CliOutput::json(
            &serde_json::to_value(&suggestions).map_err(|_| openmates_sdk::Error::Protocol)?,
        )
    } else {
        Ok(text_output(text(&suggestions)))
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    // contract-test: supporting surface=cli assertions=cli.runtime.native-rust
    #[test]
    fn text_matches_the_legacy_layout() {
        assert_eq!(
            text(&[]),
            "No new chat suggestions available.\n\x1b[2mSuggestions are generated after your first few conversations.\x1b[0m\n"
        );
        let rows = [NewChatSuggestion {
            id: "a".into(),
            chat_id: None,
            body: "Say \"hi\"".into(),
            created_at: 1.into(),
        }];
        assert_eq!(
            text(&rows),
            "\x1b[1mNew Chat Suggestions  \x1b[2m(1)\x1b[0m\n\x1b[0m\n\x1b[1m1.\x1b[0m Say \"hi\"\n   \x1b[2mopenmates chats new \"Say \\\"hi\\\"\"\x1b[0m\n\n\x1b[2mStart a chat: openmates chats new \"<suggestion text>\"\x1b[0m\n"
        );
    }

    // contract-test: supporting surface=cli assertions=cli.runtime.native-rust
    #[test]
    fn limit_defaults_to_ten_and_parses_like_js() {
        let with = |flags: &[(&str, Value)]| Invocation {
            path: vec!["newchatsuggestions".into()],
            positionals: vec![],
            flags: flags
                .iter()
                .map(|(k, v)| ((*k).to_owned(), v.clone()))
                .collect(),
        };
        assert_eq!(limit(&with(&[])), Some(10));
        assert_eq!(limit(&with(&[("limit", serde_json::json!("3x"))])), Some(3));
        assert_eq!(limit(&with(&[("limit", serde_json::json!("abc"))])), None);
    }
}
