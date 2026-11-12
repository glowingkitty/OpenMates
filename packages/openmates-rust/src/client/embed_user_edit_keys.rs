//! Key access of user-made embed versions for both credential kinds (shared
//! core; spec `feature.embed-user-edits`). A native session (CLI, Apple) keeps
//! the raw-master path (`wrapping_key` → `embed_key`/`chat_key`); a web
//! session holds only an opaque WebCrypto master capability, so its head read,
//! embed key and chat key go through the Personal version-read scope
//! (`VersionReadScope`, `version_embed_key`, `chat_key_with_capability`).
//! Neither path ever asks a browser session for native key material.
use crate::client::embed_version::VersionReadScope;
use crate::client::transport::{send, wait};
use crate::client::{Client, Item, sha256, text};
use crate::crypto::Key;
use crate::error::{Error, Result};
use serde_json::json;
use std::collections::HashSet;
use std::time::Duration;

impl Client {
    /// True when this client holds browser credentials: an opaque master
    /// capability that never yields raw key bytes.
    fn edit_uses_browser_master(&self) -> bool {
        self.browser_credentials.is_some()
    }

    /// Key of `embed_id` from the cached rows and wrappers (master, owning
    /// chat, then parent). The browser path may fetch missing rows first.
    ///
    /// # Errors
    /// `Forbidden`/`Protocol` when no wrapper opens the key; for browser
    /// credentials `Unavailable { cookie_embed_version_scope_unavailable }` in
    /// a Team scope, and the version-read scope's IO errors.
    pub(in crate::client) async fn edit_embed_key(&mut self, embed_id: &str) -> Result<Key> {
        if self.edit_uses_browser_master() {
            let scope = VersionReadScope::begin(self)?;
            return self.version_embed_key(embed_id, &scope).await;
        }
        let wrapping = self.wrapping_key().await?;
        self.embed_key(embed_id, &wrapping, &mut HashSet::new())
    }

    /// Decrypted cached embed `embed_id`, its key resolved as in
    /// [`Self::edit_embed_key`].
    pub(in crate::client) async fn edit_embed_item(&mut self, embed_id: &str) -> Result<Item> {
        let key = self.edit_embed_key(embed_id).await?;
        self.decrypt_embed_row(embed_id, &key)
    }

    /// Key of chat `chat_id` for the `embed_updated` system message. A browser
    /// session (Personal only) opens it with its opaque master from the cached
    /// chat row, else from the chat's saved metadata row; a native session
    /// opens an uncached chat first.
    ///
    /// # Errors
    /// `Crypto` (reported as `chat_key_unavailable`) when neither row carries
    /// a saved chat key; `Unavailable` in a browser Team scope; the metadata
    /// read's errors; key errors.
    pub(in crate::client) async fn edit_chat_key(&mut self, chat_id: &str) -> Result<Key> {
        if self.edit_uses_browser_master() {
            if self.team()?.is_some() {
                return Err(Error::Unavailable {
                    code: "cookie_embed_version_scope_unavailable",
                    reason: "PERSONAL_EMBED_EDIT_EVENT_ONLY",
                });
            }
            let master = self.master_capability()?;
            if let Some(row) = self.chats.get(chat_id).cloned() {
                match self.chat_key_with_capability(&row, &master).await {
                    Ok(key) => return Ok(key),
                    // A chat created on this page after the Worker loaded its
                    // list is cached as a draft row or not at all; its saved
                    // key is in the server's metadata row, read below.
                    Err(Error::Crypto | Error::Forbidden | Error::Protocol) => {}
                    Err(error) => return Err(error),
                }
            }
            let metadata = self
                .request_chat_metadata(chat_id)
                .await?
                .ok_or(Error::Crypto)?;
            let row = metadata["chats"]
                .as_array()
                .and_then(|rows| rows.iter().find(|row| text(row, "id") == chat_id))
                .cloned()
                .ok_or(Error::Crypto)?;
            return match self.chat_key_with_capability(&row, &master).await {
                Err(Error::Protocol | Error::Forbidden) => Err(Error::Crypto),
                result => result,
            };
        }
        match self.chats.get(chat_id).cloned() {
            Some(row) => {
                let wrapping = self.wrapping_key().await?;
                self.chat_key(&row, &wrapping)
            }
            None => self.work_chat_key(chat_id).await,
        }
    }

    /// Read the current server row of `embed_id` with its key wrappers into
    /// the client cache and check that its key opens. The row keeps
    /// `version_number` and `updated_at`, which the edit head needs.
    ///
    /// # Errors
    /// `Invalid` for a malformed id; `Forbidden` for a row that is not the
    /// requested embed; transport and key errors.
    pub(in crate::client) async fn edit_fetch_embed(&mut self, embed_id: &str) -> Result<()> {
        if !self.edit_uses_browser_master() {
            return self.embed_detail(embed_id).await.map(|_| ());
        }
        uuid::Uuid::parse_str(embed_id)
            .map_err(|_| Error::Invalid("A full embed ID is required."))?;
        let scope = VersionReadScope::begin(self)?;
        let mut ws = scope.run_io(self.socket_with_task_jobs(false)).await?;
        let read = async {
            scope
                .run_io(send(
                    &mut ws,
                    "request_embed",
                    json!({"embed_id": embed_id}),
                ))
                .await?;
            scope
                .run_io(wait(&mut ws, "send_embed_data", "embed_id", embed_id))
                .await
        }
        .await;
        let _ = crate::platform::time::timeout(Duration::from_millis(100), ws.close(None)).await;
        let response = read?;
        scope.check(self)?;
        let row = response.get("payload").unwrap_or(&response);
        if row["already_encrypted"] != true || text(row, "embed_id") != embed_id {
            return Err(Error::Forbidden);
        }
        let chat = text(row, "chat_id");
        let chat_hash = if chat.len() == 64 && chat.bytes().all(|c| c.is_ascii_hexdigit()) {
            chat.to_owned()
        } else {
            sha256(chat)
        };
        let wrappers = row["embed_keys"]
            .as_array()
            .filter(|rows| rows.len() <= 1024)
            .ok_or(Error::Protocol)?;
        let hash = sha256(embed_id);
        if wrappers.iter().any(|w| text(w, "hashed_embed_id") != hash) {
            return Err(Error::Forbidden);
        }
        // Same cached row shape as `embed_detail`, so `EmbedHead::from_cached_row`
        // reads the fresh server head (version and timestamp) on both paths.
        let cached = json!({"embed_id": embed_id, "encrypted_type": row["type"],
            "encrypted_content": row["content"],
            "encrypted_text_preview": row["encrypted_text_preview"],
            "hashed_chat_id": chat_hash, "parent_embed_id": row["parent_embed_id"],
            "status": row["status"], "version_number": row["version_number"],
            "updated_at": row["updatedAt"]});
        self.embed_keys.extend(wrappers.iter().cloned());
        self.embeds.insert(embed_id.to_owned(), cached);
        self.edit_embed_key(embed_id).await.map(|_| ())
    }
}

#[cfg(test)]
#[path = "embed_user_edit_keys_tests.rs"]
mod tests;
