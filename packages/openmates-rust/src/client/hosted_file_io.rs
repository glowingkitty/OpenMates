//! Session-only transport seams for the hosted Project file writer
//! (`work::projects::hosted`): the one-shot `commit_embed_revision` WebSocket
//! round trip and the chat key that wraps a new hosted file's embed key.
//! Mirrors the npm CLI `commitHostedProjectFileRevision` and
//! `getChatEncryptionKey`. Spec: `projects.files.hosted-ciphertext-commit`.
use super::transport::{send, wait};
use super::*;

impl Client {
    /// Publish one client-encrypted hosted file revision and return the
    /// server's `commit_embed_revision_result` payload unchanged.
    ///
    /// The payload is the exact transaction the web executor builds; only the
    /// transport `request_id` is added here. The result is correlated by that
    /// id, so a result for another request never settles this one. The socket
    /// carries no job capabilities.
    ///
    /// # Errors
    /// Session/private-operation fences, `Offline` when the socket fails, and
    /// the transport's receive errors.
    pub(crate) async fn commit_embed_revision(&mut self, mut payload: Value) -> Result<Value> {
        self.require_session()?;
        self.verify_private_operation()?;
        if !payload.is_object() {
            return Err(Error::Protocol);
        }
        let request = uuid::Uuid::new_v4().to_string();
        payload["request_id"] = json!(request);
        let mut ws = self.socket_with_task_jobs(false).await?;
        send(&mut ws, "commit_embed_revision", payload).await?;
        let result = wait(
            &mut ws,
            "commit_embed_revision_result",
            "request_id",
            &request,
        )
        .await;
        let _ = ws.close(None).await;
        self.verify_private_operation()?;
        result
    }

    /// The raw key of one owned chat, resolved from its server metadata row
    /// with the current Personal/Team wrapping key.
    ///
    /// The returned key is zeroized on drop and never leaves the core.
    ///
    /// # Errors
    /// `Invalid` for a non-UUID id, `Forbidden` when the chat is not visible in
    /// the active context, and the key-unwrap errors of [`Client::chat_key`].
    pub(crate) async fn hosted_file_chat_key(&mut self, chat_id: &str) -> Result<Key> {
        crate::work::uuid(chat_id)?;
        self.require_session()?;
        let path = self.scoped("/v1/chats/metadata/batch")?;
        let data = self
            .request(Method::POST, &path, Some(json!({"chat_ids": [chat_id]})))
            .await?;
        let row = data["chats"]
            .as_array()
            .ok_or(Error::Protocol)?
            .iter()
            .find(|row| text(row, "id") == chat_id)
            .ok_or(Error::Forbidden)?
            .clone();
        let wrapping = self.wrapping_key().await?;
        self.verify_private_operation()?;
        self.chat_key(&row, &wrapping)
    }

    /// GET whose 404 is absence (`None`) and every other failure keeps the
    /// generic mapping. Used for the exact-operation revision receipt.
    ///
    /// # Errors
    /// As [`Client::request_task_headers_observed`] for non-404 failures.
    pub(crate) async fn hosted_file_optional_get(&mut self, path: &str) -> Result<Option<Value>> {
        let mut status = None;
        match self
            .request_task_headers_observed(Method::GET, path, None, None, None, None, &mut status)
            .await
        {
            Ok(value) => Ok(Some(value)),
            Err(_) if status == Some(404) => Ok(None),
            Err(error) => Err(error),
        }
    }
}
