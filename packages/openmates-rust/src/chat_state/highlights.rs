//! Message highlights (`sendersMessageHighlights.ts`,
//! `handlersMessageHighlights.ts`). Each highlight row carries only routing
//! metadata in plaintext; its semantic payload (anchor or embed id, comment,
//! author display name, timestamps) is encrypted with the chat key in the
//! existing OM-framed chat-key format. DOM anchor capture/resolution and
//! on-screen ordering stay in the web renderer.
use super::js::js_trim_nonempty;
use crate::crypto;
use crate::{Error, Result};
use serde::{Deserialize, Serialize};
use serde_json::{Number, Value, json};

#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum HighlightKind {
    Text,
    Embed,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub struct HighlightAnchor {
    pub exact: String,
    pub prefix: String,
    pub suffix: String,
}

/// The web `MessageHighlight` row as stored in IndexedDB.
#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct HighlightRecord {
    pub id: String,
    pub kind: HighlightKind,
    pub chat_id: String,
    pub message_id: String,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub anchor: Option<HighlightAnchor>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub embed_id: Option<String>,
    /// In-memory render hints; never persisted in the encrypted payload.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub start: Option<Number>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub end: Option<Number>,
    pub author_user_id: String,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub author_display_name: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub comment: Option<String>,
    pub created_at: Number,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub updated_at: Option<Number>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub key_version: Option<Value>,
}

/// `MessageHighlightPayload` in the exact `JSON.stringify` field order.
#[derive(Serialize)]
struct Payload<'a> {
    kind: HighlightKind,
    #[serde(skip_serializing_if = "Option::is_none")]
    anchor: Option<&'a HighlightAnchor>,
    #[serde(skip_serializing_if = "Option::is_none")]
    embed_id: Option<&'a str>,
    #[serde(skip_serializing_if = "Option::is_none")]
    comment: Option<&'a str>,
    #[serde(skip_serializing_if = "Option::is_none")]
    author_display_name: Option<&'a str>,
    created_at: &'a Number,
    #[serde(skip_serializing_if = "Option::is_none")]
    updated_at: Option<&'a Number>,
}

impl HighlightRecord {
    pub fn parse(json: &str) -> Result<Self> {
        let record: Self =
            serde_json::from_str(json).map_err(|_| Error::Invalid("Invalid highlight."))?;
        let consistent = match record.kind {
            HighlightKind::Text => record.anchor.is_some(),
            HighlightKind::Embed => record.embed_id.as_deref().is_some_and(|id| !id.is_empty()),
        };
        if !consistent
            || record.id.is_empty()
            || record.chat_id.is_empty()
            || record.message_id.is_empty()
        {
            return Err(Error::Invalid("Invalid highlight."));
        }
        Ok(record)
    }
    pub fn to_json(&self) -> String {
        serde_json::to_string(self).expect("highlight serialization is infallible")
    }
    /// Plaintext that is encrypted into `encrypted_payload`.
    pub fn payload_plaintext(&self, updated_at: Option<&Number>) -> String {
        let payload = Payload {
            kind: self.kind,
            anchor: if self.kind == HighlightKind::Text {
                self.anchor.as_ref()
            } else {
                None
            },
            embed_id: if self.kind == HighlightKind::Embed {
                self.embed_id.as_deref()
            } else {
                None
            },
            comment: self.comment.as_deref(),
            author_display_name: self.author_display_name.as_deref(),
            created_at: &self.created_at,
            updated_at,
        };
        serde_json::to_string(&payload).expect("payload serialization is infallible")
    }
}

/// A socket frame the adapter sends verbatim, plus the row to store locally.
pub struct HighlightWrite {
    pub frame_type: &'static str,
    pub payload: Value,
    /// Row to upsert optimistically (`None` for removals).
    pub record: Option<HighlightRecord>,
}

/// `sendAddMessageHighlightImpl`: encrypt and build `add_message_highlight`.
pub fn add_highlight(record: &HighlightRecord, chat_key: &[u8; 32]) -> Result<HighlightWrite> {
    let encrypted_payload = crypto::encrypt_combined(&record.payload_plaintext(None), chat_key)?;
    Ok(HighlightWrite {
        frame_type: "add_message_highlight",
        payload: json!({
            "chat_id": record.chat_id,
            "message_id": record.message_id,
            "id": record.id,
            "author_user_id": record.author_user_id,
            "key_version": record.key_version.clone().unwrap_or(Value::Null),
            "encrypted_payload": encrypted_payload,
            "created_at": record.created_at,
        }),
        record: Some(record.clone()),
    })
}

/// `sendUpdateMessageHighlightImpl`: stamp `updated_at = now` (seconds).
pub fn update_highlight(
    record: &HighlightRecord,
    chat_key: &[u8; 32],
    now_seconds: u64,
) -> Result<HighlightWrite> {
    let now = Number::from(now_seconds);
    let mut merged = record.clone();
    merged.updated_at = Some(now.clone());
    let encrypted_payload =
        crypto::encrypt_combined(&merged.payload_plaintext(Some(&now)), chat_key)?;
    Ok(HighlightWrite {
        frame_type: "update_message_highlight",
        payload: json!({
            "chat_id": merged.chat_id,
            "message_id": merged.message_id,
            "id": merged.id,
            "encrypted_payload": encrypted_payload,
            "updated_at": now,
        }),
        record: Some(merged),
    })
}

pub fn remove_highlight(chat_id: &str, message_id: &str, id: &str) -> HighlightWrite {
    HighlightWrite {
        frame_type: "remove_message_highlight",
        payload: json!({"chat_id": chat_id, "message_id": message_id, "id": id}),
        record: None,
    }
}

/// Why an inbound highlight is not stored (the web client drops the row).
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum HighlightDrop {
    Undecryptable,
    MissingAnchor,
    MissingEmbed,
    UnknownKind,
}

#[derive(Debug, PartialEq)]
pub enum HighlightInbound {
    Store(Box<HighlightRecord>),
    Drop(HighlightDrop),
}

#[derive(Deserialize)]
struct InboundFrame {
    chat_id: String,
    message_id: String,
    id: String,
    #[serde(default)]
    author_user_id: Option<String>,
    encrypted_payload: String,
    #[serde(default)]
    created_at: Option<Number>,
    #[serde(default)]
    updated_at: Option<Number>,
    #[serde(default)]
    key_version: Option<Value>,
}

fn optional_string(plain: &Value, key: &str) -> Option<String> {
    plain.get(key).and_then(Value::as_str).map(str::to_owned)
}

fn decrypt_into(
    frame: &InboundFrame,
    author_user_id: String,
    created_at: Option<Number>,
    updated_at: Option<Number>,
    key_version: Option<Value>,
    chat_key: &[u8; 32],
) -> HighlightInbound {
    let Ok(plaintext) = crypto::decrypt_combined(&frame.encrypted_payload, chat_key) else {
        return HighlightInbound::Drop(HighlightDrop::Undecryptable);
    };
    let Ok(plain) = serde_json::from_str::<Value>(&plaintext) else {
        return HighlightInbound::Drop(HighlightDrop::Undecryptable);
    };
    let comment = optional_string(&plain, "comment").filter(|comment| js_trim_nonempty(comment));
    let mut record = HighlightRecord {
        id: frame.id.clone(),
        kind: HighlightKind::Text,
        chat_id: frame.chat_id.clone(),
        message_id: frame.message_id.clone(),
        anchor: None,
        embed_id: None,
        start: None,
        end: None,
        author_user_id,
        author_display_name: optional_string(&plain, "author_display_name"),
        comment,
        created_at: created_at.unwrap_or_else(|| Number::from(0)),
        updated_at,
        key_version: Some(key_version.unwrap_or(Value::Null)),
    };
    match plain.get("kind").and_then(Value::as_str) {
        Some("text") => {
            let anchor = plain.get("anchor").filter(|anchor| anchor.is_object());
            let Some(exact) = anchor
                .and_then(|anchor| anchor.get("exact"))
                .and_then(Value::as_str)
            else {
                return HighlightInbound::Drop(HighlightDrop::MissingAnchor);
            };
            let side = |key| {
                anchor
                    .and_then(|a| a.get(key))
                    .and_then(Value::as_str)
                    .unwrap_or_default()
                    .to_owned()
            };
            record.anchor = Some(HighlightAnchor {
                exact: exact.to_owned(),
                prefix: side("prefix"),
                suffix: side("suffix"),
            });
        }
        Some("embed") => {
            let Some(embed_id) = optional_string(&plain, "embed_id").filter(|id| !id.is_empty())
            else {
                return HighlightInbound::Drop(HighlightDrop::MissingEmbed);
            };
            record.kind = HighlightKind::Embed;
            record.embed_id = Some(embed_id);
        }
        _ => return HighlightInbound::Drop(HighlightDrop::UnknownKind),
    }
    HighlightInbound::Store(Box::new(record))
}

fn frame(payload: &str) -> Result<InboundFrame> {
    serde_json::from_str(payload).map_err(|_| Error::Protocol)
}

/// `handleMessageHighlightAddedImpl`: `updated_at` mirrors `created_at`.
pub fn decode_added(payload: &str, chat_key: &[u8; 32]) -> Result<HighlightInbound> {
    let frame = frame(payload)?;
    let author = frame.author_user_id.clone().unwrap_or_default();
    let (created, key_version) = (frame.created_at.clone(), frame.key_version.clone());
    Ok(decrypt_into(
        &frame,
        author,
        created.clone(),
        created,
        key_version,
        chat_key,
    ))
}

/// `handleMessageHighlightUpdatedImpl`: author, creation time and key version
/// come from the cached row when present.
pub fn decode_updated(
    payload: &str,
    chat_key: &[u8; 32],
    cached: Option<&HighlightRecord>,
) -> Result<HighlightInbound> {
    let frame = frame(payload)?;
    let author = cached
        .map(|row| row.author_user_id.clone())
        .unwrap_or_default();
    let created = cached
        .map(|row| row.created_at.clone())
        .or_else(|| frame.updated_at.clone());
    let key_version = cached
        .and_then(|row| row.key_version.clone())
        .filter(|v| !v.is_null());
    Ok(decrypt_into(
        &frame,
        author,
        created,
        frame.updated_at.clone(),
        key_version,
        chat_key,
    ))
}

#[cfg(all(test, not(target_arch = "wasm32")))]
#[path = "highlights_tests.rs"]
mod tests;
