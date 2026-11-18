//! Per-chat wellbeing score history, kept client-encrypted like the focus phase state.
//! Shared-core module (client core, not a shell): validates the server's
//! `wellbeing_scores_updated` event, encrypts it into `encrypted_wellbeing_scores`
//! and returns the decrypted list for the next message's `inference.wellbeing_scores`.
//! Contract: `docs/plans/safety-decisions-build/wellbeing-contract.md`;
//! spec `specifications/features/wellbeing-support/`. Score values are never logged.
use super::{sync::decrypt_optional, *};

/// Event kind the server uses to replace (or, when empty, clear) a chat's history.
pub(super) const EVENT_KIND: &str = "wellbeing_scores_updated";
/// Chat field holding the encrypted score list.
pub(super) const FIELD: &str = "encrypted_wellbeing_scores";
const MAX_ENTRIES: usize = 8;
const SIGNALS: [&str; 10] = [
    "suicidal",
    "method_or_means",
    "plan_or_timeline",
    "self_harm",
    "self_injury_now",
    "hopelessness_isolation",
    "eating_disorder",
    "reality_loss",
    "mania",
    "danger_from_others",
];

/// Validates a score list: at most 8 entries `{t: unix seconds, s: {known signal: 0..1}}`.
///
/// # Errors
/// `Error::Protocol` for any other shape, unknown signal or out-of-range value.
pub(super) fn validate_scores(scores: &Value) -> Result<()> {
    let list = scores.as_array().ok_or(Error::Protocol)?;
    if list.len() > MAX_ENTRIES {
        return Err(Error::Protocol);
    }
    for entry in list {
        let object = entry.as_object().ok_or(Error::Protocol)?;
        if object.len() != 2 || entry["t"].as_u64().is_none() {
            return Err(Error::Protocol);
        }
        let signals = entry["s"].as_object().ok_or(Error::Protocol)?;
        for (name, value) in signals {
            let score = value.as_f64().ok_or(Error::Protocol)?;
            if !SIGNALS.contains(&name.as_str()) || !(0.0..=1.0).contains(&score) {
                return Err(Error::Protocol);
            }
        }
    }
    Ok(())
}

/// Validates a server event for `chat` and returns its ciphertext, or `None`
/// when the list is empty (the stored field is then cleared).
///
/// # Errors
/// `Error::Forbidden` for a foreign chat, `Error::Protocol` for a malformed list.
pub(super) fn encrypt_event(event: &Value, chat: &str, key: &[u8; 32]) -> Result<Option<String>> {
    if text(event, "chat_id") != chat {
        return Err(Error::Forbidden);
    }
    let scores = &event["scores"];
    validate_scores(scores)?;
    if scores.as_array().is_some_and(Vec::is_empty) {
        return Ok(None);
    }
    Ok(Some(crypto::encrypt_combined(&scores.to_string(), key)?))
}

/// Wire payload of the metadata write; `None` ciphertext clears the field.
pub(super) fn metadata_payload(chat: &str, encrypted: Option<&str>) -> Value {
    json!({"chat_id": chat, FIELD: encrypted})
}

impl Client {
    /// Decrypted score history of `chat`, or `None` when there is none.
    ///
    /// # Errors
    /// Decryption failure or a stored value that is not a valid list.
    pub(super) fn current_wellbeing_scores(
        &self,
        chat: &str,
        key: &[u8; 32],
    ) -> Result<Option<Value>> {
        let Some(row) = self.chats.get(chat) else {
            return Ok(None);
        };
        let plain = decrypt_optional(row, FIELD, key)?;
        if plain.is_empty() {
            return Ok(None);
        }
        let scores: Value = serde_json::from_str(&plain)?;
        validate_scores(&scores)?;
        Ok((!scores.as_array().is_some_and(Vec::is_empty)).then_some(scores))
    }
}
