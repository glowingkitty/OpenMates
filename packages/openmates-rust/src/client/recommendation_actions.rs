//! Accept actions of the Chat Recommendations card: the billed Memory draft
//! requests and the "resolved" write-back, shared by every shell.
//!
//! Mirrors the web `recommendationDrafts.ts` (draft requests) and
//! `chatRecommendationsPersistence.ts` (`resolveChatRecommendation`). The
//! latest turn text is decrypted on this device and sent only as the body of
//! the billed request; the resolved state is re-encrypted with the chat key.
//! Spec: `specifications/features/app-memories/specification.yml`
//! (`app-memories.suggestions.*`); plan: `docs/plans/chat-recommendations/plan.yml`.
use super::recommendations::{ChatRecommendation, ChatRecommendationsState};
use super::{Client, transport};
use crate::error::{Error, Result};
use reqwest::Method;
use serde_json::{Value, json};
use std::time::Duration;

/// Billed draft route for a new Memory.
pub const CREATE_DRAFT_PATH: &str = "/v1/memory-suggestions/create-draft";
/// Billed draft route for an update of an existing Memory.
pub const UPDATE_PREVIEW_PATH: &str = "/v1/memory-suggestions/update-preview";
/// Pause before the single retry of a request that got no response.
pub const NETWORK_RETRY_DELAY: Duration = Duration::from_millis(1_500);
/// Longest turn text sent to a draft request.
const MAX_TURN_TEXT: usize = 8_000;
/// Most messages the update preview accepts.
/// Most titles kept in the resolved list (web `MAX_TITLE_LIST`).
const MAX_TITLE_LIST: usize = 200;
const MAX_PREVIEW_MESSAGES: usize = 24;

/// Why a draft could not be produced (the web `RecommendationDraftFailure`).
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum RecommendationDraftFailure {
    /// HTTP 402: the account cannot pay for the draft.
    InsufficientCredits,
    /// The Memory an update targets no longer exists.
    MemoryNotFound,
    /// The server refused or answered with something unusable.
    RequestFailed,
    /// No response twice, or the retried request id was already received (409).
    NetworkUnavailable,
}

/// An unsaved Memory draft produced by a recommendation.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct RecommendationMemoryDraft {
    /// Canonical Markdown document (frontmatter + body).
    pub document: String,
    /// App the server chose for a new Memory, when well-formed.
    pub app_id: Option<String>,
    /// Id of the Memory an update edits; `None` for a new Memory.
    pub existing_id: Option<String>,
}

/// Result of accepting a Memory recommendation.
#[derive(Clone, Debug, PartialEq, Eq)]
pub enum RecommendationDraftOutcome {
    /// Open this draft in the Memory editor.
    Draft(RecommendationMemoryDraft),
    /// The update changes nothing ("already up to date").
    UpToDate,
    /// The request failed in a way the card shows as text.
    Failed(RecommendationDraftFailure),
}

/// One user or assistant message of the chat, text only.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct TurnMessage {
    /// `user` or `assistant`.
    pub role: String,
    /// Text without embed reference blocks.
    pub text: String,
    /// Message id.
    pub id: String,
}

/// Removes fenced JSON blocks that reference embeds; they are never draft input.
pub fn strip_embed_blocks(content: &str) -> String {
    let mut out = String::with_capacity(content.len());
    let mut rest = content;
    while let Some(start) = rest.find("```json") {
        let after = &rest[start + 7..];
        let Some(end) = after.find("```") else { break };
        let block = &after[..end];
        out.push_str(&rest[..start]);
        if !(block.contains("\"embed_id\"") && block.trim_start().starts_with('{')) {
            out.push_str(&rest[start..start + 7 + end + 3]);
        }
        rest = &after[end + 3..];
    }
    out.push_str(rest);
    out.trim().to_owned()
}

fn truncate_chars(text: &str, max: usize) -> String {
    text.chars().take(max).collect()
}

/// User/assistant messages with text, oldest first (input order).
pub fn turn_messages(messages: &[crate::model::Message]) -> Vec<TurnMessage> {
    messages
        .iter()
        .filter(|m| m.role == "user" || m.role == "assistant")
        .filter_map(|m| {
            let text = strip_embed_blocks(&m.content);
            (!text.is_empty()).then(|| TurnMessage {
                role: m.role.clone(),
                text,
                id: m.id.clone(),
            })
        })
        .collect()
}

/// Last assistant response, the user message right before it and that user
/// message's id (the id the server bills the draft to).
pub fn latest_turn(messages: &[TurnMessage]) -> (String, String, Option<String>) {
    let assistant = messages.iter().rposition(|m| m.role == "assistant");
    let response = assistant.map_or("", |i| messages[i].text.as_str());
    let before = assistant.map_or(messages, |i| &messages[..i]);
    let user = before.iter().rev().find(|m| m.role == "user");
    (
        truncate_chars(user.map_or("", |m| m.text.as_str()), MAX_TURN_TEXT),
        truncate_chars(response, MAX_TURN_TEXT),
        user.map(|m| m.id.clone()).filter(|id| !id.is_empty()),
    )
}

/// Body of a `create-draft` request.
pub fn create_draft_body(
    chat_id: &str,
    recommendation: &ChatRecommendation,
    messages: &[TurnMessage],
    request_id: &str,
) -> Value {
    let (user, assistant, message_id) = latest_turn(messages);
    let mut body = json!({
        "chat_id": chat_id,
        "title": recommendation.title,
        "summary": recommendation.summary,
        "user_message": user,
        "assistant_response": assistant,
        "request_id": request_id,
    });
    if let Some(id) = message_id {
        body["message_id"] = json!(id);
    }
    body
}

/// Body of an `update-preview` request.
pub fn update_preview_body(
    chat_id: &str,
    memory_id: &str,
    memory_markdown: &str,
    messages: &[TurnMessage],
    request_id: &str,
) -> Value {
    let (_, _, message_id) = latest_turn(messages);
    let skip = messages.len().saturating_sub(MAX_PREVIEW_MESSAGES);
    let rows: Vec<Value> = messages[skip..]
        .iter()
        .map(|m| json!({"role": m.role, "text": truncate_chars(&m.text, MAX_TURN_TEXT)}))
        .collect();
    let mut body = json!({
        "chat_id": chat_id,
        "memory_id": memory_id,
        "memory_markdown": memory_markdown,
        "messages": rows,
        "request_id": request_id,
    });
    if let Some(id) = message_id {
        body["message_id"] = json!(id);
    }
    body
}

fn valid_app_id(value: &str) -> bool {
    let mut chars = value.chars();
    value.len() <= 64
        && chars.next().is_some_and(|c| c.is_ascii_lowercase())
        && chars.all(|c| c.is_ascii_lowercase() || c.is_ascii_digit() || c == '_')
}

/// Canonical document and well-formed app id of a `create-draft` response, or
/// `None` when the body is missing or not a parseable Memory document.
pub fn parse_create_draft_response(raw: &Value) -> Option<(String, Option<String>)> {
    let body = raw.get("body")?.as_str().filter(|b| !b.trim().is_empty())?;
    super::memory_document_fields::parse_memory_document(body).ok()?;
    let app = raw
        .get("app_id")
        .and_then(Value::as_str)
        .filter(|id| valid_app_id(id))
        .map(str::to_owned);
    Some((body.to_owned(), app))
}

/// `Some(Some(document))` for an update, `Some(None)` for "unchanged", `None`
/// for anything else.
pub fn parse_update_preview_response(raw: &Value) -> Option<Option<String>> {
    match raw.get("status")?.as_str()? {
        "updated" => {
            let body = raw.get("body")?.as_str().filter(|b| !b.trim().is_empty())?;
            super::memory_document_fields::parse_memory_document(body).ok()?;
            Some(Some(body.to_owned()))
        }
        "unchanged" => Some(None),
        _ => None,
    }
}

/// Failure for an HTTP status the draft routes answer with; `None` when the
/// status gives no verdict (no response).
pub fn failure_for_status(status: Option<u16>) -> RecommendationDraftFailure {
    match status {
        Some(402) => RecommendationDraftFailure::InsufficientCredits,
        Some(409) | None => RecommendationDraftFailure::NetworkUnavailable,
        Some(_) => RecommendationDraftFailure::RequestFailed,
    }
}

/// The state after the user saved the entry: the item is removed and its
/// title is remembered so it is never proposed again in this chat.
/// `None` when the item is not open (nothing to write).
pub fn state_with_resolved(
    state: &ChatRecommendationsState,
    id: &str,
    now: i64,
) -> Option<ChatRecommendationsState> {
    let item = state.items.iter().find(|item| item.id == id)?;
    let title = item.title.clone();
    let mut next = state.clone();
    next.items.retain(|item| item.id != id);
    if !next.resolved.contains(&title) {
        next.resolved.push(title);
    }
    let excess = next.resolved.len().saturating_sub(MAX_TITLE_LIST);
    next.resolved.drain(..excess);
    next.updated_at = now;
    Some(next)
}

fn now_seconds() -> i64 {
    std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .map_or(0, |d| i64::try_from(d.as_secs()).unwrap_or(i64::MAX))
}

impl Client {
    /// One billed POST. A request that never got a response is retried once
    /// with the same `request_id` (the server accepts an id once, so the retry
    /// is never billed twice); HTTP failures are never retried.
    async fn post_billed(
        &mut self,
        path: &str,
        body: Value,
    ) -> Result<std::result::Result<Value, RecommendationDraftFailure>> {
        for attempt in 0..2 {
            let mut status = None;
            match self
                .request_task_headers_observed(
                    Method::POST,
                    path,
                    Some(body.clone()),
                    None,
                    None,
                    None,
                    &mut status,
                )
                .await
            {
                Ok(value) => return Ok(Ok(value)),
                Err(Error::Offline) if status.is_none() && attempt == 0 => {
                    crate::platform::time::sleep(NETWORK_RETRY_DELAY).await;
                }
                Err(Error::Offline) if status.is_none() => break,
                Err(error) => match status {
                    Some(code) if code != 401 && code != 403 => {
                        return Ok(Err(failure_for_status(status)));
                    }
                    _ => return Err(error),
                },
            }
        }
        Ok(Err(RecommendationDraftFailure::NetworkUnavailable))
    }

    /// Accepts a Memory recommendation: the billed draft (create) or update
    /// preview, built from the latest turn of `chat_id`.
    ///
    /// # Errors
    /// Session, chat-read and cancellation errors; request failures are
    /// reported as [`RecommendationDraftOutcome::Failed`].
    pub async fn recommendation_memory_draft(
        &mut self,
        chat_id: &str,
        recommendation: &ChatRecommendation,
    ) -> Result<RecommendationDraftOutcome> {
        let chat = self.open_chat(chat_id).await?;
        let messages = turn_messages(&chat.messages);
        let request_id = uuid::Uuid::new_v4().to_string();
        if let (super::recommendations::RecommendationAction::Update, Some(target)) =
            (recommendation.action, recommendation.target_id.as_deref())
        {
            let documents = self
                .personal_memory_documents()
                .await
                .map_err(|_| Error::Protocol)?;
            let Some(found) = documents
                .iter()
                .find(|d| d.id == target || d.id == format!("personal:{target}"))
            else {
                return Ok(RecommendationDraftOutcome::Failed(
                    RecommendationDraftFailure::MemoryNotFound,
                ));
            };
            let body =
                update_preview_body(chat_id, &found.id, &found.document, &messages, &request_id);
            let id = found.id.clone();
            return Ok(match self.post_billed(UPDATE_PREVIEW_PATH, body).await? {
                Err(failure) => RecommendationDraftOutcome::Failed(failure),
                Ok(raw) => match parse_update_preview_response(&raw) {
                    Some(None) => RecommendationDraftOutcome::UpToDate,
                    Some(Some(document)) => {
                        RecommendationDraftOutcome::Draft(RecommendationMemoryDraft {
                            document,
                            app_id: None,
                            existing_id: Some(id),
                        })
                    }
                    None => {
                        RecommendationDraftOutcome::Failed(RecommendationDraftFailure::RequestFailed)
                    }
                },
            });
        }
        let body = create_draft_body(chat_id, recommendation, &messages, &request_id);
        Ok(match self.post_billed(CREATE_DRAFT_PATH, body).await? {
            Err(failure) => RecommendationDraftOutcome::Failed(failure),
            Ok(raw) => match parse_create_draft_response(&raw) {
                Some((document, app_id)) => {
                    RecommendationDraftOutcome::Draft(RecommendationMemoryDraft {
                        document,
                        app_id,
                        existing_id: None,
                    })
                }
                None => {
                    RecommendationDraftOutcome::Failed(RecommendationDraftFailure::RequestFailed)
                }
            },
        })
    }

    /// Marks `recommendation_id` resolved after its entry was saved: the state
    /// is re-encrypted with the chat key and written with
    /// `update_post_processing_metadata` (ciphertext only). No-op when the item
    /// is no longer open.
    ///
    /// # Errors
    /// Chat read, key and socket errors; `Protocol` for an unreadable state.
    pub async fn resolve_chat_recommendation(
        &mut self,
        chat_id: &str,
        recommendation_id: &str,
    ) -> Result<()> {
        self.open_chat(chat_id).await?;
        let row = self.chats.get(chat_id).ok_or(Error::Offline)?.clone();
        let Some(ciphertext) = row
            .get("encrypted_recommendations")
            .and_then(Value::as_str)
            .filter(|value| !value.is_empty())
        else {
            return Ok(());
        };
        let wrapping = self.wrapping_capability().await?;
        let key = self.chat_key_with_capability(&row, &wrapping).await?;
        let plaintext = zeroize::Zeroizing::new(crate::crypto::decrypt_combined(ciphertext, &key)?);
        let state: ChatRecommendationsState =
            serde_json::from_str(&plaintext).map_err(|_| Error::Protocol)?;
        if state.schema_version != 1 {
            return Err(Error::Protocol);
        }
        let Some(next) = state_with_resolved(&state, recommendation_id, now_seconds()) else {
            return Ok(());
        };
        let encrypted = crate::crypto::encrypt_combined(
            &serde_json::to_string(&next).map_err(|_| Error::Protocol)?,
            &key,
        )?;
        let mut body = json!({"chat_id": chat_id, "encrypted_recommendations": encrypted});
        if let Some(wrapped) = row.get("encrypted_chat_key").filter(|v| v.is_string()) {
            body["encrypted_chat_key"] = wrapped.clone();
        }
        let mut ws = self.socket().await?;
        transport::send(&mut ws, "update_post_processing_metadata", body).await?;
        transport::wait(&mut ws, "post_processing_metadata_stored", "chat_id", chat_id).await?;
        let _ = ws.close(None).await;
        if let Some(row) = self.chats.get_mut(chat_id) {
            row["encrypted_recommendations"] = json!(encrypted);
        }
        Ok(())
    }
}

#[cfg(test)]
#[path = "recommendation_actions_tests.rs"]
mod tests;
