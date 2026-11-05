//! New-chat suggestions for the home screen (web `NewChatSuggestions.svelte`,
//! TS CLI `listNewChatSuggestions`).
//!
//! The server delivers these only inside the Phase 1 sync frame
//! (`phase_1_last_chat_ready.new_chat_suggestions`). This read requests the
//! `phase1` window on its own socket, takes the suggestions from the first
//! Phase 1 frame and closes; it never writes chat caches, cursors or drafts,
//! and every other frame on that socket is ignored. Rows are master-key
//! encrypted; undecryptable rows are skipped like the TS CLI does.
use super::transport::{receive, send};
use crate::client::*;
use serde::Serialize;

/// One decrypted suggestion, serialized with the TS CLI field names.
#[derive(Clone, Debug, PartialEq, Eq, Serialize)]
pub struct NewChatSuggestion {
    pub id: String,
    #[serde(rename = "chatId")]
    pub chat_id: Option<String>,
    pub body: String,
    /// The server number unchanged (`0` when absent), as the TS CLI prints it.
    #[serde(rename = "createdAt")]
    pub created_at: serde_json::Number,
}

/// JS `parseInt(value, 10)`: leading whitespace, optional sign, leading
/// digits. `None` is NaN, which the TS CLI treats as "no limit".
pub fn js_parse_int(value: &str) -> Option<i64> {
    let trimmed = value.trim_start();
    let (sign, rest) = match trimmed.as_bytes().first() {
        Some(b'-') => (-1i64, &trimmed[1..]),
        Some(b'+') => (1, &trimmed[1..]),
        _ => (1, trimmed),
    };
    let digits: String = rest.chars().take_while(char::is_ascii_digit).collect();
    if digits.is_empty() {
        return None;
    }
    Some(sign * digits.parse::<i64>().unwrap_or(i64::MAX))
}

/// Decrypt raw rows exactly like the TS CLI: rows without a string
/// `encrypted_suggestion` or that do not decrypt are skipped, collection stops
/// once `limit` rows are kept (`None` never stops), then newest first.
pub(crate) fn decrypt_new_chat_suggestions(
    rows: &[Value],
    master: &[u8; 32],
    limit: Option<i64>,
) -> Vec<NewChatSuggestion> {
    let mut results = Vec::new();
    for row in rows {
        let Some(ciphertext) = row.get("encrypted_suggestion").and_then(Value::as_str) else {
            continue;
        };
        let Ok(plaintext) = crypto::decrypt_combined(ciphertext, master) else {
            continue;
        };
        if plaintext.is_empty() {
            continue;
        }
        results.push(NewChatSuggestion {
            id: match row.get("id") {
                Some(Value::String(id)) => id.clone(),
                Some(Value::Null) | None => String::new(),
                Some(other) => other.to_string(),
            },
            chat_id: row
                .get("chat_id")
                .and_then(Value::as_str)
                .map(str::to_owned),
            body: super::chat_details::strip_suggestion(&plaintext).to_owned(),
            created_at: match row.get("created_at") {
                Some(Value::Number(number)) => number.clone(),
                _ => 0.into(),
            },
        });
        if limit.is_some_and(|limit| results.len() as i64 >= limit) {
            break;
        }
    }
    let at = |s: &NewChatSuggestion| s.created_at.as_f64().unwrap_or(0.0);
    // Stable like JS Array.prototype.sort.
    results.sort_by(|a, b| at(b).total_cmp(&at(a)));
    results
}

impl Client {
    /// Read the account's new-chat suggestions from a Phase 1 sync frame.
    pub async fn new_chat_suggestions(
        &mut self,
        limit: Option<i64>,
    ) -> Result<Vec<NewChatSuggestion>> {
        self.require_canonical_read_profile()?;
        let master = self.require_session()?.master_key.clone();
        let team = self.team()?.map(str::to_owned);
        let cancel = self.operation_cancel.clone();
        let mut ws = self.ephemeral_socket().await?;
        let mut payload = json!({"phase":"phase1","context_epoch":super::sync_windows::REQUEST_CONTEXT_EPOCH,"client_chat_versions":{},"client_chat_ids":[],"client_embed_ids":[]});
        if let Some(team) = &team {
            payload["team_id"] = json!(team);
        }
        send(&mut ws, "phased_sync_request", payload).await?;
        let deadline = crate::platform::time::Instant::now() + Duration::from_secs(60);
        loop {
            let (kind, frame) = tokio::select! {
                biased;
                _ = cancel.cancelled() => return Err(Error::Cancelled),
                result = crate::platform::time::timeout_at(deadline, receive(&mut ws)) => result.map_err(|_| Error::Offline)??,
            };
            if kind != "phase_1_last_chat_ready" || frame["phase"] != "phase1" {
                continue;
            }
            if frame["team_id"].as_str() != team.as_deref() {
                return Err(Error::Protocol);
            }
            let rows = match frame.get("new_chat_suggestions") {
                Some(Value::Array(rows)) => rows.as_slice(),
                Some(Value::Null) | None => &[],
                Some(_) => return Err(Error::Protocol),
            };
            return Ok(decrypt_new_chat_suggestions(rows, &master, limit));
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    // contract-test: supporting surface=cli assertions=cli.runtime.native-rust
    #[test]
    fn rows_decrypt_strip_prefix_limit_then_sort_newest_first() {
        let key = [7u8; 32];
        let enc = |text: &str| crypto::encrypt_combined(text, &key).unwrap();
        let rows = vec![
            json!({"id":"a","chat_id":"c1","encrypted_suggestion":enc("[Travel] Plan a trip"),"created_at":1}),
            json!({"id":"b","encrypted_suggestion":"not-ciphertext","created_at":9}),
            json!({"id":"c","created_at":9}),
            json!({"id":7,"encrypted_suggestion":enc("  Learn Rust  "),"created_at":5}),
            json!({"id":"d","encrypted_suggestion":enc("Third"),"created_at":10}),
        ];
        let all = decrypt_new_chat_suggestions(&rows, &key, None);
        assert_eq!(
            all.iter().map(|s| s.body.as_str()).collect::<Vec<_>>(),
            ["Third", "Learn Rust", "Plan a trip"]
        );
        assert_eq!(all[1].id, "7");
        assert_eq!(all[2].chat_id.as_deref(), Some("c1"));
        let limited = decrypt_new_chat_suggestions(&rows, &key, Some(2));
        assert_eq!(
            limited.iter().map(|s| s.body.as_str()).collect::<Vec<_>>(),
            ["Learn Rust", "Plan a trip"]
        );
        assert_eq!(decrypt_new_chat_suggestions(&rows, &key, Some(0)).len(), 1);
        assert_eq!(
            serde_json::to_value(&all[2]).unwrap(),
            json!({"id":"a","chatId":"c1","body":"Plan a trip","createdAt":1})
        );
    }

    // contract-test: supporting surface=cli assertions=cli.runtime.native-rust
    #[test]
    fn limit_parses_like_js_parse_int() {
        assert_eq!(js_parse_int("5"), Some(5));
        assert_eq!(js_parse_int(" 12abc"), Some(12));
        assert_eq!(js_parse_int("-3"), Some(-3));
        assert_eq!(js_parse_int("abc"), None);
        assert_eq!(js_parse_int(""), None);
    }
}
