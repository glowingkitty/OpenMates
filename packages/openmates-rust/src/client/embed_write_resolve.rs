//! Embed key resolution inside the key-owning [`EmbedWriteSession`]: the
//! shared-Rust port of the web `embedStore.getEmbedKey` decision order (cached
//! key, first master wrapper, the chat wrapper of the requested chat, any other
//! chat wrapper, then legacy parent inheritance) plus the early HKDF parent key
//! of a still-processing streamed embed (`deriveEmbedKeyFromChatKey`). Keys stay
//! in the session; adapters receive only decisions and ciphertext results.
use super::{EmbedWriteSession, KeyAdoption, Target, Wrapping};
use crate::client::embed_write::keys::{derive_embed_key, hash_id, key_from};
use crate::crypto::Key;
use crate::error::{Error, Result};
use serde_json::Value;

/// What the adapter must do next to load one embed key.
pub enum KeyLookup {
    /// The session already holds the key (cached, derived or inherited earlier).
    Loaded,
    /// Stored wrapper rows exist: try `candidates` in order and install the first
    /// that unwraps. `pending_chat_hashes` are wrapper chats whose chat key the
    /// session does not hold yet (TS `markEmbedKeyPendingForChat`). When no
    /// candidate opens, the embed key is unavailable: direct wrappers define a
    /// key's authority, so a parent key is never substituted (TS negative cache).
    Wrappers {
        candidates: Vec<KeyAdoption>,
        pending_chat_hashes: Vec<String>,
    },
    /// No wrapper rows: a legacy child inherits its parent's key, if any.
    NoWrappers,
}

fn field<'a>(row: &'a Value, name: &str) -> Option<&'a str> {
    row.get(name)
        .and_then(Value::as_str)
        .filter(|value| !value.is_empty())
}

impl EmbedWriteSession {
    /// Installs a chat key the page's chat-key write guard already validated
    /// (TS `ensureChatKeySafeForWrite`). This is the exact key the legacy writer
    /// would use, including team/direct/anonymous chats whose stored
    /// `encrypted_chat_key` is not master-wrapped. The bytes move page -> Worker
    /// only and are never returned.
    ///
    /// # Errors
    /// `Invalid` for an empty chat id, `Crypto` for a key that is not 32 bytes.
    pub fn install_chat_key(&mut self, chat_id: &str, key: &[u8]) -> Result<()> {
        if chat_id.is_empty() {
            return Err(Error::Invalid("Chat key installation requires a chat ID."));
        }
        let key = key_from(key)?;
        self.chat_keys.insert(chat_id.to_owned(), key);
        Ok(())
    }

    fn chat_key_for_hash(&self, hashed_chat_id: &str) -> Option<(String, Key)> {
        self.chat_keys
            .iter()
            .find(|(chat_id, _)| hash_id(chat_id) == hashed_chat_id)
            .map(|(chat_id, key)| (chat_id.clone(), key.clone()))
    }

    /// Plans the key lookup for `embed_id` from its `embed_keys` rows (TS order:
    /// first master row, then the chat row of `hashed_chat_id`, then every other
    /// chat row). Rows without a wrapped key are ignored, as the TS unwrap
    /// returns null for them.
    pub fn plan_key_lookup(
        &self,
        embed_id: &str,
        hashed_chat_id: Option<&str>,
        rows: &[Value],
    ) -> KeyLookup {
        if self.embed_keys.contains_key(embed_id) {
            return KeyLookup::Loaded;
        }
        if rows.is_empty() {
            return KeyLookup::NoWrappers;
        }
        let owner = hashed_chat_id
            .and_then(|hash| self.chat_key_for_hash(hash))
            .map(|(chat_id, _)| chat_id)
            .unwrap_or_default();
        let mut candidates = Vec::new();
        let mut pending_chat_hashes = Vec::new();
        if let Some(wrapped) = rows
            .iter()
            .find(|row| field(row, "key_type") == Some("master"))
            .and_then(|row| field(row, "encrypted_embed_key"))
        {
            candidates.push(KeyAdoption {
                target: Target::Embed {
                    embed_id: embed_id.to_owned(),
                    chat_id: owner,
                },
                wrapped: wrapped.to_owned(),
                wrapping: Wrapping::Master(self.master.clone()),
            });
        }
        let chat_rows: Vec<(usize, &Value)> = rows
            .iter()
            .enumerate()
            .filter(|(_, row)| field(row, "key_type") == Some("chat"))
            .collect();
        // TS tries the requested chat's first row, then every chat row in stored order.
        let preferred = hashed_chat_id.and_then(|hash| {
            chat_rows
                .iter()
                .find(|(_, row)| field(row, "hashed_chat_id") == Some(hash))
                .map(|(index, _)| *index)
        });
        let ordered = preferred.into_iter().chain(
            chat_rows
                .iter()
                .map(|(index, _)| *index)
                .filter(|index| Some(*index) != preferred),
        );
        for index in ordered {
            let row = &rows[index];
            let (Some(hash), Some(wrapped)) = (
                field(row, "hashed_chat_id"),
                field(row, "encrypted_embed_key"),
            ) else {
                continue;
            };
            match self.chat_key_for_hash(hash) {
                Some((chat_id, chat_key)) => candidates.push(KeyAdoption {
                    target: Target::Embed {
                        embed_id: embed_id.to_owned(),
                        chat_id,
                    },
                    wrapped: wrapped.to_owned(),
                    wrapping: Wrapping::Key(chat_key),
                }),
                None if !pending_chat_hashes.iter().any(|pending| pending == hash) => {
                    pending_chat_hashes.push(hash.to_owned())
                }
                None => {}
            }
        }
        KeyLookup::Wrappers {
            candidates,
            pending_chat_hashes,
        }
    }

    /// Legacy child without wrappers: share the parent's loaded key (TS
    /// `getEmbedKey` parent fallback). Returns false when the parent key is not
    /// loaded; a self-reference is refused so lookup cycles cannot alias keys.
    pub fn inherit_parent_key(&mut self, child_id: &str, parent_id: &str) -> bool {
        if child_id == parent_id {
            return false;
        }
        let Some((key, chat_id)) = self.embed_keys.get(parent_id).cloned() else {
            return false;
        };
        self.embed_keys.insert(child_id.to_owned(), (key, chat_id));
        true
    }

    /// Early parent key of a still-processing streamed embed: HKDF(chat key,
    /// embed id), the derivation every tab agrees on, cached so children that
    /// finalize first inherit it. Returns false when the chat key is not loaded
    /// (the key is then derived at finalization). An already loaded key is kept.
    ///
    /// # Errors
    /// Propagates a derivation failure (`Crypto`).
    pub fn derive_early_parent_key(&mut self, embed_id: &str, chat_id: &str) -> Result<bool> {
        if self.embed_keys.contains_key(embed_id) {
            return Ok(true);
        }
        let Some(chat_key) = self.chat_keys.get(chat_id) else {
            return Ok(false);
        };
        let key = derive_embed_key(chat_key, embed_id)?;
        self.embed_keys
            .insert(embed_id.to_owned(), (key, chat_id.to_owned()));
        Ok(true)
    }

    /// Copy of a loaded embed key for the platform AEAD import that opens stored
    /// rows (WebCrypto handle in the Worker). Zeroizing; the binding never
    /// marshals it to JavaScript.
    ///
    /// # Errors
    /// `Unavailable { code: "embed_key_unavailable" }` when the key is not loaded.
    pub fn embed_key_material(&self, embed_id: &str) -> Result<Key> {
        self.with_embed_key(embed_id, |key| Ok(Key::new(*key)))
    }
}
