//! Key-owning embed write session. Chat and embed keys enter only as
//! ciphertext (master-wrapped chat key, embed key wrapper rows, child-by-parent
//! wrappers) and never leave as raw bytes; callers receive ciphertext and rows.
//!
//! Async work is split so browser adapters never hold a `RefCell` borrow across
//! an await: `*_adoption` / `plan_*` are synchronous, the returned owned value
//! resolves/finishes asynchronously, and `install` is synchronous again.
use super::keys::{
    NonceSource, OsNonces, derive_embed_key, generate_embed_key, hash_id, unwrap_key, unwrap_key_with_master,
    wrap_key_with_master,
};
use super::payload::{
    PreparedEmbedWrite, ProcessingEmbedUpdate, StreamedEmbedData, WriteKeys, build_processing_update,
    build_stream_completion,
};
use crate::crypto::{Key, master::MasterCapability};
use crate::error::{Error, Result};
use serde_json::Value;
use std::collections::HashMap;

#[path = "embed_write_resolve.rs"]
mod resolve;
pub use resolve::KeyLookup;

const PARENT_KEY_PENDING: Error = Error::Unavailable {
    code: "embed_parent_key_pending",
    reason: "PARENT_EMBED_KEY_NOT_YET_AVAILABLE",
};
const CHAT_KEY_UNAVAILABLE: Error = Error::Unavailable {
    code: "embed_chat_key_unavailable",
    reason: "CHAT_KEY_REQUIRED_FOR_EMBED_WRITE",
};

pub struct EmbedWriteSession {
    master: MasterCapability,
    chat_keys: HashMap<String, Key>,
    /// embed id -> (key, owning chat id).
    embed_keys: HashMap<String, (Key, String)>,
}

enum Target {
    Chat(String),
    Embed { embed_id: String, chat_id: String },
}
enum Wrapping {
    Master(MasterCapability),
    Key(Key),
}
/// Owned pending unwrap; resolving it needs no session borrow.
pub struct KeyAdoption {
    target: Target,
    wrapped: String,
    wrapping: Wrapping,
}
impl KeyAdoption {
    pub async fn resolve(self) -> Result<AdoptedKey> {
        let key = match &self.wrapping {
            Wrapping::Master(master) => unwrap_key_with_master(&self.wrapped, master).await?,
            Wrapping::Key(wrapping) => unwrap_key(&self.wrapped, wrapping)?,
        };
        Ok(AdoptedKey { target: self.target, key })
    }
}
/// Verified key ready to install; opaque to callers.
pub struct AdoptedKey {
    target: Target,
    key: Key,
}

enum PlannedKind {
    Completion(StreamedEmbedData),
    Update(ProcessingEmbedUpdate),
}
/// A planned write owning its key material; `finish` encrypts and wraps.
pub struct PlannedEmbedWrite {
    kind: PlannedKind,
    embed_key: Key,
    chat_key: Option<Key>,
    master: Option<MasterCapability>,
}
impl PlannedEmbedWrite {
    pub async fn finish(self, now_ms: i64) -> Result<PreparedEmbedWrite> {
        self.finish_with(now_ms, &mut OsNonces).await
    }
    /// Deterministic-nonce variant used by the TypeScript vector tests.
    pub(crate) async fn finish_with(self, now_ms: i64, nonces: &mut impl NonceSource) -> Result<PreparedEmbedWrite> {
        let master_wrapper = match &self.master {
            Some(master) => Some(wrap_key_with_master(&self.embed_key, master).await?),
            None => None,
        };
        let keys = WriteKeys { embed_key: &self.embed_key, chat_key: self.chat_key.as_deref(), master_wrapper };
        match &self.kind {
            PlannedKind::Completion(data) => build_stream_completion(data, keys, now_ms, nonces),
            PlannedKind::Update(update) => build_processing_update(update, keys, now_ms, nonces),
        }
    }
}

impl EmbedWriteSession {
    pub fn new(master: MasterCapability) -> Self {
        Self { master, chat_keys: HashMap::new(), embed_keys: HashMap::new() }
    }
    /// Adopt a chat key from its master-wrapped `encrypted_chat_key`. The
    /// adapter only offers keys its chat-key manager already marks write-safe.
    pub fn chat_key_adoption(&self, chat_id: &str, encrypted_chat_key: &str) -> Result<KeyAdoption> {
        if chat_id.is_empty() || encrypted_chat_key.is_empty() {
            return Err(Error::Invalid("Chat key adoption requires a chat ID and wrapped key."));
        }
        Ok(KeyAdoption {
            target: Target::Chat(chat_id.to_owned()),
            wrapped: encrypted_chat_key.to_owned(),
            wrapping: Wrapping::Master(self.master.clone()),
        })
    }
    /// Adopt an embed key from an `embed_keys` row (master or chat wrapper).
    pub fn embed_wrapper_adoption(&self, embed_id: &str, chat_id: &str, row: &Value) -> Result<KeyAdoption> {
        let field = |name: &str| row.get(name).and_then(Value::as_str);
        if embed_id.is_empty() || field("hashed_embed_id") != Some(hash_id(embed_id).as_str()) {
            return Err(Error::Protocol);
        }
        let wrapped = field("encrypted_embed_key").filter(|w| !w.is_empty()).ok_or(Error::Protocol)?;
        let wrapping = match field("key_type") {
            Some("master") => Wrapping::Master(self.master.clone()),
            Some("chat") => {
                if field("hashed_chat_id") != Some(hash_id(chat_id).as_str()) {
                    return Err(Error::Protocol);
                }
                let chat_key = self.chat_keys.get(chat_id).ok_or(CHAT_KEY_UNAVAILABLE)?;
                Wrapping::Key(chat_key.clone())
            }
            _ => return Err(Error::Protocol),
        };
        Ok(KeyAdoption {
            target: Target::Embed { embed_id: embed_id.to_owned(), chat_id: chat_id.to_owned() },
            wrapped: wrapped.to_owned(),
            wrapping,
        })
    }
    pub fn install(&mut self, adopted: AdoptedKey) {
        match adopted.target {
            Target::Chat(chat_id) => {
                self.chat_keys.insert(chat_id, adopted.key);
            }
            Target::Embed { embed_id, chat_id } => {
                self.embed_keys.insert(embed_id, (adopted.key, chat_id));
            }
        }
    }
    /// Shared child: key wrapped by its parent embed key.
    pub fn adopt_child_key(&mut self, child_id: &str, parent_id: &str, wrapped_by_parent: &str) -> Result<()> {
        let (parent_key, chat_id) = self.embed_keys.get(parent_id).ok_or(PARENT_KEY_PENDING)?;
        let key = unwrap_key(wrapped_by_parent, parent_key)?;
        let chat_id = chat_id.clone();
        self.embed_keys.insert(child_id.to_owned(), (key, chat_id));
        Ok(())
    }
    pub fn has_chat_key(&self, chat_id: &str) -> bool {
        self.chat_keys.contains_key(chat_id)
    }
    pub fn has_embed_key(&self, embed_id: &str) -> bool {
        self.embed_keys.contains_key(embed_id)
    }
    /// Run `f` with an embed key (history/restore helpers); never returned.
    pub fn with_embed_key<R>(&self, embed_id: &str, f: impl FnOnce(&[u8; 32]) -> Result<R>) -> Result<R> {
        let (key, _) = self.embed_keys.get(embed_id).ok_or(Error::Unavailable {
            code: "embed_key_unavailable",
            reason: "EMBED_KEY_NOT_LOADED",
        })?;
        f(key)
    }
    fn cache(&mut self, targets: Vec<String>, key: &Key, chat_id: &str) {
        for target in targets {
            self.embed_keys.insert(target, (key.clone(), chat_id.to_owned()));
        }
    }
    /// Finalized `send_embed_data`: child inherits the parent key (adapter
    /// retries `embed_parent_key_pending` with backoff); parent uses its cached
    /// key or the HKDF chat-key derivation every tab agrees on.
    pub fn plan_stream_completion(&mut self, data: StreamedEmbedData) -> Result<PlannedEmbedWrite> {
        let chat_id = data.chat_id().to_owned();
        if let Some(parent_id) = data.parent_embed_id() {
            let (key, _) = self.embed_keys.get(parent_id).ok_or(PARENT_KEY_PENDING)?;
            let key = key.clone();
            self.cache(vec![data.embed_id().to_owned()], &key, &chat_id);
            return Ok(PlannedEmbedWrite { kind: PlannedKind::Completion(data), embed_key: key, chat_key: None, master: None });
        }
        let chat_key = self.chat_keys.get(&chat_id).ok_or(CHAT_KEY_UNAVAILABLE)?.clone();
        let key = match self.embed_keys.get(data.embed_id()) {
            Some((cached, _)) => cached.clone(),
            None => derive_embed_key(&chat_key, data.embed_id())?,
        };
        self.cache(data.key_cache_targets(), &key, &chat_id);
        let master = (!data.local_only()).then(|| self.master.clone());
        Ok(PlannedEmbedWrite { kind: PlannedKind::Completion(data), embed_key: key, chat_key: Some(chat_key), master })
    }
    /// Processing->finished `embed_update`. Parents keep the legacy cached-or-
    /// random key; children without an inherited key are refused (never a
    /// random key that would make the child undecryptable).
    pub fn plan_processing_update(&mut self, update: ProcessingEmbedUpdate) -> Result<PlannedEmbedWrite> {
        let embed_id = update.embed_id().to_owned();
        let cached = self.embed_keys.get(&embed_id).map(|(key, _)| key.clone());
        if update.is_child() {
            let key = cached.ok_or(PARENT_KEY_PENDING)?;
            return Ok(PlannedEmbedWrite { kind: PlannedKind::Update(update), embed_key: key, chat_key: None, master: None });
        }
        let chat_key = self.chat_keys.get(&update.chat_id).ok_or(CHAT_KEY_UNAVAILABLE)?.clone();
        let key = cached.unwrap_or_else(generate_embed_key);
        let chat_id = update.chat_id.clone();
        self.cache(update.key_cache_targets(), &key, &chat_id);
        let master = Some(self.master.clone());
        Ok(PlannedEmbedWrite { kind: PlannedKind::Update(update), embed_key: key, chat_key: Some(chat_key), master })
    }
    /// Drop a chat's keys (chat deleted/hidden or key rotated).
    pub fn forget_chat(&mut self, chat_id: &str) {
        self.chat_keys.remove(chat_id);
        self.embed_keys.retain(|_, (_, owner)| owner != chat_id);
    }
    pub fn clear(&mut self) {
        self.chat_keys.clear();
        self.embed_keys.clear();
    }
}
