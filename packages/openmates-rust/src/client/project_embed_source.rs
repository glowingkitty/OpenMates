//! Embed key resolution for explicit Project adoption (restore relink and the
//! repair path), compiled on every target. Turn adoption stays in
//! `project_embed_adoption`.
use super::transport::{send, wait};
use super::*;

impl Client {
    /// The raw key of one owned chat, resolved from its server metadata row
    /// with the current Personal/Team wrapping capability. It works for both
    /// credential kinds: a native session holds the raw master, the web Worker
    /// only a non-extractable WebCrypto master, so the unwrap goes through
    /// [`Client::wrapping_capability`] and never asks for raw master bytes.
    ///
    /// The returned key is zeroized on drop and never leaves the core.
    ///
    /// # Errors
    /// `Invalid` for a non-UUID id, `Forbidden` when the chat is not visible in
    /// the active context, and the key-unwrap errors of
    /// [`Client::chat_key_with_capability`].
    pub(crate) async fn hosted_file_chat_key(&mut self, chat_id: &str) -> Result<Key> {
        crate::work::uuid(chat_id)?;
        self.require_credentials()?;
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
        let wrapping = self.wrapping_capability().await?;
        self.verify_private_operation()?;
        self.chat_key_with_capability(&row, &wrapping).await
    }

    /// The key, decrypted type and decoded content of one existing embed of
    /// `chat`, for the explicit adoption repair. The key comes from the
    /// embed's chat wrapper (or master wrapper in Personal scope), else from
    /// its parent chain; a wrapperless root is derived from the chat key like
    /// `persist_stream_artifacts` derives it. The key never leaves the core.
    ///
    /// # Errors
    /// `Forbidden` for a foreign or mismatched embed, `Crypto` when no key
    /// opens it, and transport errors.
    pub(crate) async fn adoption_embed_source(
        &mut self,
        chat: &str,
        embed: &str,
    ) -> Result<(Key, String, Value)> {
        crate::work::uuid(chat)?;
        crate::work::uuid(embed)?;
        let chat_key = self.hosted_file_chat_key(chat).await?;
        let mut ws = self.socket_with_task_jobs(false).await?;
        let fetched = self.adoption_rows(&mut ws, chat, embed, &chat_key).await;
        let _ = ws.close(None).await;
        self.verify_private_operation()?;
        let (key, row) = fetched?;
        let embed_type = crypto::decrypt_combined(required(&row, "type")?, &key)?;
        let content =
            super::toon::decode(&crypto::decrypt_combined(required(&row, "content")?, &key)?)?;
        Ok((key, embed_type, content))
    }

    async fn adoption_rows(
        &mut self,
        ws: &mut super::transport::Socket,
        chat: &str,
        embed: &str,
        chat_key: &[u8; 32],
    ) -> Result<(Key, Value)> {
        let mut wanted = embed.to_owned();
        let mut first: Option<Value> = None;
        for _ in 0..8 {
            let mut payload = json!({"embed_id": wanted});
            if let Some(team) = self.team()? {
                payload["team_id"] = json!(team);
                payload["chat_id"] = json!(chat);
            }
            send(ws, "request_embed", payload).await?;
            let response = wait(ws, "send_embed_data", "embed_id", &wanted).await?;
            let row = response.get("payload").unwrap_or(&response).clone();
            if row["already_encrypted"] != true || text(&row, "embed_id") != wanted {
                return Err(Error::Forbidden);
            }
            let found = self.wrapper_key(&row, &wanted, chat, chat_key)?;
            let parent = text(&row, "parent_embed_id").to_owned();
            let row_for_embed = first.get_or_insert_with(|| row.clone()).clone();
            if let Some(key) = found {
                return Ok((key, row_for_embed));
            }
            if parent.is_empty() {
                return Ok((crypto::derive_embed_key(chat_key, &wanted)?, row_for_embed));
            }
            wanted = parent;
        }
        Err(Error::Crypto)
    }

    fn wrapper_key(
        &self,
        row: &Value,
        embed: &str,
        chat: &str,
        chat_key: &[u8; 32],
    ) -> Result<Option<Key>> {
        let embed_hash = sha256(embed);
        let chat_hash = sha256(chat);
        for wrapper in row["embed_keys"].as_array().into_iter().flatten() {
            if text(wrapper, "hashed_embed_id") != embed_hash {
                return Err(Error::Forbidden);
            }
            let cipher = required(wrapper, "encrypted_embed_key")?;
            match text(wrapper, "key_type") {
                "chat" if text(wrapper, "hashed_chat_id") == chat_hash => {
                    return Ok(Some(key_from_bytes(&crypto::decrypt_bytes(
                        cipher, chat_key,
                    )?)?));
                }
                "master" if self.team()?.is_none() => {
                    let master = &self.require_session()?.master_key;
                    return Ok(Some(key_from_bytes(&crypto::decrypt_bytes(
                        cipher, master,
                    )?)?));
                }
                _ => {}
            }
        }
        Ok(None)
    }
}
