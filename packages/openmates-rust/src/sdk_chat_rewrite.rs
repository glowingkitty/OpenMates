//! Explicit API-key personal-chat fork, rewind and retry (npm/Python
//! `chats.fork|rewind|retry` parity). The selected chat is read once from the
//! owner-scoped `GET /v1/sdk/chats/{id}`, decoded by the same authenticated row
//! decoder as the session path, and the fork/rewind request bodies come from the
//! shared `client::chat_rewrite` builders. Only the transport (`/v1/sdk/...`) and
//! the key that wraps a fork's new chat key (the API-key-unwrapped account key)
//! differ. Saved-chat send is not part of the Rust API-key SDK, so `retry`
//! returns the prompt for the caller to resend, exactly like the session API.
use crate::client::chat_rewrite::{self, ChatRewriteState};
use crate::sdk_chats::Chats;
use crate::{Error, Result, crypto};
use reqwest::Method;
use serde_json::Value;
use zeroize::Zeroizing;

/// The decoded chat plus the opened source chat key a fork re-encrypts from.
/// Both are wiped on drop.
pub struct ApiKeyChatRewrite {
    state: ChatRewriteState,
    source_key: crypto::Key,
}
impl ApiKeyChatRewrite {
    pub fn state(&self) -> &ChatRewriteState {
        &self.state
    }
}

impl Chats<'_> {
    /// Read exactly one owned personal chat (full history) for a rewrite.
    /// Team, Direct and key-less chats are refused before any mutation.
    pub async fn rewrite_state(&mut self, chat_id: &str) -> Result<ApiKeyChatRewrite> {
        let resolved = self.resolve_id(chat_id).await?;
        let mut payload = self.read(format!("/v1/sdk/chats/{resolved}")).await?;
        let chat = payload["chat"].take();
        if !chat.is_object() {
            return Err(Error::Protocol);
        }
        if chat["chat_visibility"] == "direct" || chat["hashed_team_id"].as_str().is_some_and(|t| !t.is_empty()) {
            return Err(Error::Invalid(chat_rewrite::PERSONAL_ONLY));
        }
        let wrappers = match (&payload["chat_key_wrappers"], &chat["chat_key_wrappers"]) {
            (Value::Array(rows), _) | (_, Value::Array(rows)) => rows.clone(),
            _ => vec![],
        };
        let source_key = self
            .chat_key(&chat, &wrappers)
            .await?
            .ok_or(Error::Invalid("Saved chat does not include encrypted chat key material."))?;
        let rows = match payload["messages"].take() {
            Value::Array(rows) => rows,
            Value::Null => vec![],
            _ => return Err(Error::Protocol),
        };
        let state = ChatRewriteState::from_encrypted_rows(&resolved, &chat, &rows, &source_key)?;
        Ok(ApiKeyChatRewrite { state, source_key })
    }
    /// Copy messages through `boundary_index` into a new encrypted chat whose
    /// key is wrapped with the API-key-unwrapped account key.
    pub async fn fork(
        &mut self,
        rewrite: &ApiKeyChatRewrite,
        boundary_index: usize,
        title: Option<&str>,
    ) -> Result<Value> {
        rewrite.state.server_message_id(boundary_index)?;
        self.client.verify_private_operation()?;
        let master = self.client.master_key().await?;
        let key = crypto::random_key();
        let wrapped = crypto::encrypt_bytes(&key[..], &master)?;
        let body = chat_rewrite::fork_request(
            &rewrite.state,
            boundary_index,
            title,
            &rewrite.source_key,
            &key,
            wrapped,
        )?;
        self.client.verify_private_operation()?;
        let path = format!("/v1/sdk/chats/{}/fork", rewrite.state.chat_id());
        self.client.task_request(Method::POST, &path, Some(body), false, None).await
    }
    /// Delete server rows after `boundary_index`; a dry run only reports the plan.
    pub async fn rewind(
        &mut self,
        rewrite: &ApiKeyChatRewrite,
        boundary_index: usize,
        dry_run: bool,
        confirm_destructive: bool,
    ) -> Result<Value> {
        let body = chat_rewrite::rewind_request(&rewrite.state, boundary_index, dry_run, confirm_destructive)?;
        self.client.verify_private_operation()?;
        let path = format!("/v1/sdk/chats/{}/rewind", rewrite.state.chat_id());
        self.client.task_request(Method::POST, &path, Some(body), false, None).await
    }
    /// Rewind before the newest unanswered user turn. Returns the server result
    /// and, unless dry-run, the prompt the caller must resend in the same chat.
    pub async fn retry(
        &mut self,
        rewrite: &ApiKeyChatRewrite,
        dry_run: bool,
        confirm_destructive: bool,
    ) -> Result<(Value, Option<Zeroizing<String>>)> {
        let target = chat_rewrite::retry_plan(&rewrite.state, dry_run, confirm_destructive)?;
        let result = self
            .rewind(rewrite, target.boundary_index, dry_run, confirm_destructive)
            .await?;
        Ok((result, (!dry_run).then_some(target.prompt)))
    }
}

#[cfg(test)]
#[path = "sdk_chat_rewrite_tests.rs"]
mod tests;
