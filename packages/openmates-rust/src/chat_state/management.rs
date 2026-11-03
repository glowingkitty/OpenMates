//! Chat management frames and local policy (`sendersChatManagement.ts`,
//! `chatMenuActionService.ts`, `pendingChatDeletions.ts`). Rust encrypts
//! titles/summaries with the chat key (OM-framed chat-key format) and builds
//! the socket frames; the adapter owns the socket, IndexedDB, notifications,
//! the deletion-confirm dialog and the write-safety guard
//! (`ensureChatKeySafeForWrite`), which it must pass before calling in here.
use crate::crypto;
use crate::{Error, Result};
use serde::Deserialize;
use serde_json::{Value, json};

/// One socket frame: `webSocketService.sendMessage(frame_type, payload)`.
#[derive(Debug, PartialEq)]
pub struct ChatFrame {
    pub frame_type: &'static str,
    pub payload: Value,
}

/// `update_title` plus the local row changes applied after sending.
pub struct TitleUpdate {
    pub frame: ChatFrame,
    pub encrypted_title: String,
    pub title_v: u64,
    pub updated_at: u64,
}

/// `sendUpdateTitleImpl`. `encrypted_chat_key` is the stored wrapper sent for
/// server-side key validation (OPE-314); the chat must exist locally.
pub fn update_title(
    chat_id: &str,
    title: &str,
    chat_key: &[u8; 32],
    encrypted_chat_key: Option<&str>,
    title_v: Option<u64>,
    now_seconds: u64,
) -> Result<TitleUpdate> {
    let encrypted_title = crypto::encrypt_combined(title, chat_key)?;
    let mut payload = json!({"chat_id": chat_id, "encrypted_title": encrypted_title});
    if let Some(wrapper) = encrypted_chat_key.filter(|w| !w.is_empty()) {
        payload["encrypted_chat_key"] = Value::from(wrapper);
    }
    Ok(TitleUpdate {
        frame: ChatFrame {
            frame_type: "update_title",
            payload,
        },
        encrypted_title,
        title_v: title_v.unwrap_or(0) + 1,
        updated_at: now_seconds,
    })
}

/// Stored component versions (`chat.x_v || 0`).
#[derive(Clone, Copy, Debug, Default)]
pub struct ComponentVersions {
    pub messages_v: Option<u64>,
    pub title_v: Option<u64>,
    pub metadata_v: Option<u64>,
    pub draft_v: Option<u64>,
}

pub struct SummaryUpdate {
    pub frame: ChatFrame,
    pub encrypted_chat_summary: String,
    pub metadata_v: u64,
    pub updated_at: u64,
}

/// `sendUpdateSummaryImpl`: a manual summary edit through
/// `update_post_processing_metadata`.
pub fn update_summary(
    chat_id: &str,
    summary: &str,
    chat_key: &[u8; 32],
    encrypted_chat_key: &str,
    encrypted_title: Option<&str>,
    versions: ComponentVersions,
    now_seconds: u64,
) -> Result<SummaryUpdate> {
    if encrypted_chat_key.is_empty() {
        return Err(Error::Invalid(
            "Chat summary update failed: encrypted chat key unavailable",
        ));
    }
    let encrypted_chat_summary = crypto::encrypt_combined(summary, chat_key)?;
    let title_v = versions.title_v.unwrap_or(0);
    let metadata_v = versions.metadata_v.unwrap_or(0).max(title_v);
    let mut payload = json!({
        "chat_id": chat_id,
        "encrypted_chat_summary": encrypted_chat_summary,
        "encrypted_chat_key": encrypted_chat_key,
        "manual_update": true,
        "title_changed": false,
        "versions": {
            "messages_v": versions.messages_v.unwrap_or(0),
            "title_v": title_v,
            "metadata_v": metadata_v,
            "draft_v": versions.draft_v.unwrap_or(0),
        },
    });
    if let Some(title) = encrypted_title.filter(|t| !t.is_empty()) {
        payload["encrypted_title"] = Value::from(title);
    }
    Ok(SummaryUpdate {
        frame: ChatFrame {
            frame_type: "update_post_processing_metadata",
            payload,
        },
        encrypted_chat_summary,
        metadata_v: metadata_v + 1,
        updated_at: now_seconds,
    })
}

/// Pin/unpin (`update_chat`), sent only while connected.
pub fn pin_frame(chat_id: &str, pinned: bool) -> ChatFrame {
    ChatFrame {
        frame_type: "update_chat",
        payload: json!({"chat_id": chat_id, "pinned": pinned}),
    }
}

#[derive(Deserialize)]
struct DeletionPrecheck {
    #[serde(default)]
    requires_decision: Option<Value>,
    #[serde(default)]
    protected_embed_ids: Option<Value>,
}

/// `/v1/projects/deletion-precheck/chat` response: the number of project
/// embeds the user must decide about (`None` = no dialog). Unparseable
/// bodies are a protocol error; the adapter keeps the web behaviour of
/// continuing without the dialog when the precheck is unavailable.
pub fn deletion_decision(precheck_json: &str) -> Result<Option<usize>> {
    let precheck: DeletionPrecheck =
        serde_json::from_str(precheck_json).map_err(|_| Error::Protocol)?;
    let truthy = match precheck.requires_decision {
        Some(Value::Bool(b)) => b,
        Some(Value::Number(n)) => n.as_f64().is_some_and(|v| v != 0.0),
        Some(Value::String(s)) => !s.is_empty(),
        Some(Value::Array(_) | Value::Object(_)) => true,
        Some(Value::Null) | None => false,
    };
    // `protected_embed_ids?.length`
    let count = match precheck.protected_embed_ids {
        Some(Value::Array(ids)) => ids.len(),
        Some(Value::String(s)) => super::js::utf16_len(&s),
        _ => 0,
    };
    Ok((truthy && count > 0).then_some(count))
}

/// `delete_chat` (`sendDeleteChatImpl`).
pub fn delete_chat_frame(
    chat_id: &str,
    remove_project_embeds: bool,
    embed_ids_to_delete: &[String],
) -> ChatFrame {
    let mut payload = json!({"chatId": chat_id, "removeProjectEmbeds": remove_project_embeds});
    if !embed_ids_to_delete.is_empty() {
        payload["embed_ids_to_delete"] = json!(embed_ids_to_delete);
    }
    ChatFrame {
        frame_type: "delete_chat",
        payload,
    }
}

/// `delete_message` (`sendDeleteMessageImpl`).
pub fn delete_message_frame(
    chat_id: &str,
    message_id: &str,
    embed_ids_to_delete: &[String],
) -> ChatFrame {
    let mut payload = json!({"chatId": chat_id, "messageId": message_id});
    if !embed_ids_to_delete.is_empty() {
        payload["embedIdsToDelete"] = json!(embed_ids_to_delete);
    }
    ChatFrame {
        frame_type: "delete_message",
        payload,
    }
}

/// `sendSetActiveChatImpl` decision.
#[derive(Debug, PartialEq)]
pub enum ActiveChatPlan {
    /// Unauthenticated, or a public/demo/legal chat: nothing is written.
    Skip,
    /// Optionally persist `last_opened` locally (never for the new-chat
    /// window), then send the frame when connected.
    Send {
        persist_last_opened: Option<String>,
        frame: ChatFrame,
    },
}

pub fn active_chat_plan(
    chat_id: Option<&str>,
    authenticated: bool,
    is_public_chat: bool,
) -> ActiveChatPlan {
    if !authenticated || (chat_id.is_some() && is_public_chat) {
        return ActiveChatPlan::Skip;
    }
    ActiveChatPlan::Send {
        persist_last_opened: chat_id.map(str::to_owned),
        frame: ChatFrame {
            frame_type: "set_active_chat",
            payload: json!({"chat_id": chat_id}),
        },
    }
}

/// Deleting a demo/example chat hides it in the profile instead. `None` when
/// it is already hidden (no write).
pub fn hide_demo_chat(current: &[String], chat_id: &str) -> Option<Vec<String>> {
    if current.iter().any(|id| id == chat_id) {
        return None;
    }
    let mut updated = current.to_vec();
    updated.push(chat_id.to_owned());
    Some(updated)
}

pub const PENDING_DELETIONS_KEY: &str = "openmates_pending_chat_deletions";

/// The reconnect deletion queue in localStorage. Corrupt or non-array values
/// read as empty; non-string entries are carried through like the web code.
#[derive(Clone, Debug, Default, PartialEq)]
pub struct PendingDeletions(Vec<Value>);

/// localStorage write for the queue: `None` removes the key.
pub type PendingDeletionsWrite = Option<String>;

impl PendingDeletions {
    pub fn decode(raw: Option<&str>) -> Self {
        let parsed = raw
            .filter(|r| !r.is_empty())
            .and_then(|r| serde_json::from_str::<Value>(r).ok());
        match parsed {
            Some(Value::Array(items)) => Self(items),
            _ => Self::default(),
        }
    }
    pub fn contains(&self, chat_id: &str) -> bool {
        self.0.iter().any(|v| v.as_str() == Some(chat_id))
    }
    /// Chat ids to retry on reconnect (string entries, queue order).
    pub fn chat_ids(&self) -> Vec<String> {
        self.0
            .iter()
            .filter_map(|v| v.as_str().map(str::to_owned))
            .collect()
    }
    fn encode(&self) -> String {
        serde_json::to_string(&self.0).expect("JSON array serialization is infallible")
    }
    /// `addPendingChatDeletion`: `None` when already queued (no write).
    pub fn add(&mut self, chat_id: &str) -> Option<String> {
        if self.contains(chat_id) {
            return None;
        }
        self.0.push(Value::from(chat_id));
        Some(self.encode())
    }
    /// `removePendingChatDeletion`: always writes; empty removes the key.
    pub fn remove(&mut self, chat_id: &str) -> PendingDeletionsWrite {
        self.0.retain(|v| v.as_str() != Some(chat_id));
        (!self.0.is_empty()).then(|| self.encode())
    }
}

#[cfg(all(test, not(target_arch = "wasm32")))]
#[path = "management_tests.rs"]
mod tests;
