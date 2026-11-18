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
use super::history::EncryptedDiffRow;
use super::payload::{
    PreparedEmbedWrite, ProcessingEmbedUpdate, StreamedEmbedData, WriteKeys, build_processing_update,
    build_stream_completion,
};
use super::revision::{ChildRevision, REVISION_HEAD_REQUIRED, StoredChildHead, build_child_revision};
use super::revision_recovery::RevisionRecoveryReceipt;
use crate::crypto::{Key, master::MasterCapability};
use crate::error::{Error, Result};
use serde_json::Value;
use std::collections::HashMap;
use zeroize::Zeroizing;

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

const MASTER_UNAVAILABLE: Error = Error::Unavailable {
    code: "embed_master_unavailable",
    reason: "LOCAL_ONLY_SESSION_HAS_NO_MASTER_KEY",
};
const LOCAL_ONLY_REQUIRED: Error = Error::Unavailable {
    code: "embed_local_only_required",
    reason: "SESSION_WITHOUT_MASTER_KEY_WRITES_LOCAL_ONLY",
};

/// Per-session embed key store and write planner. A session either holds the
/// account master capability or is local-only (signed-out guest): a local-only
/// session can adopt chat-wrapped keys and write local-only embeds, and can
/// never produce a master wrapper or a server payload.
pub struct EmbedWriteSession {
    master: Option<MasterCapability>,
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
    ChildRevision { data: StreamedEmbedData, revision: ChildRevision, head: StoredChildHead, existing: Vec<EncryptedDiffRow> },
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
            PlannedKind::ChildRevision { data, revision, head, existing } => {
                build_child_revision(data, revision, head, existing, &self.embed_key, now_ms, nonces)
            }
        }
    }
}

impl EmbedWriteSession {
    /// Session bound to the account master capability (server-synced writes).
    pub fn new(master: MasterCapability) -> Self {
        Self { master: Some(master), chat_keys: HashMap::new(), embed_keys: HashMap::new() }
    }
    /// Signed-out guest session without a master key: embeds are encrypted
    /// with the guest chat key and stay on the device (`local_only`).
    pub fn local_only() -> Self {
        Self { master: None, chat_keys: HashMap::new(), embed_keys: HashMap::new() }
    }
    fn master(&self) -> Result<MasterCapability> {
        self.master.clone().ok_or(MASTER_UNAVAILABLE)
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
            wrapping: Wrapping::Master(self.master()?),
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
            Some("master") => Wrapping::Master(self.master()?),
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
    ///
    /// # Errors
    /// `embed_revision_head_required` for a child revision payload (it must
    /// go through [`Self::plan_child_revision`]); `Error::Protocol` for a
    /// malformed `revision`; key availability errors as above.
    pub fn plan_stream_completion(&mut self, data: StreamedEmbedData) -> Result<PlannedEmbedWrite> {
        // A guest session must never yield a master wrapper or server payload.
        if self.master.is_none() && !data.local_only() {
            return Err(LOCAL_ONLY_REQUIRED);
        }
        if data.child_revision()?.is_some() {
            return Err(REVISION_HEAD_REQUIRED);
        }
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
        let master = if data.local_only() { None } else { Some(self.master()?) };
        Ok(PlannedEmbedWrite { kind: PlannedKind::Completion(data), embed_key: key, chat_key: Some(chat_key), master })
    }
    /// Version N+1 of a generated child (`payload.revision`): keeps the parent's
    /// key (never re-keyed or re-parented) and the stored head's identity.
    /// `stored_head` is the child's local `embeds` row (`None` when absent);
    /// `existing_rows` are its local `embed_diffs` rows, reused when they hold
    /// the same plaintext so a replay sends identical ciphertext.
    /// `finish` returns `child_revision.steps` in the contract order.
    ///
    /// # Errors
    /// `embed_parent_key_pending` without the parent key; `Error::Conflict`
    /// when a different key is already cached for the child; the typed
    /// `embed_revision_*` refusals of `StoredChildHead::check`;
    /// `Error::Protocol` for rows of another embed or a malformed revision;
    /// `Error::Invalid` for a non-revision or local-only payload.
    pub fn plan_child_revision(
        &mut self,
        data: StreamedEmbedData,
        stored_head: Option<&Value>,
        existing_rows: Vec<EncryptedDiffRow>,
    ) -> Result<PlannedEmbedWrite> {
        if self.master.is_none() {
            return Err(LOCAL_ONLY_REQUIRED);
        }
        let revision = data.child_revision()?.ok_or(Error::Invalid("Payload is not a child revision."))?;
        if data.local_only() {
            return Err(Error::Invalid("A child revision is never local-only."));
        }
        let parent_id = data.parent_embed_id().ok_or(Error::Protocol)?;
        let (key, _) = self.embed_keys.get(parent_id).ok_or(PARENT_KEY_PENDING)?;
        let key = key.clone();
        // A different cached child key means the child was re-keyed somewhere:
        // writing with either key would leave one version undecryptable.
        if self.embed_keys.get(data.embed_id()).is_some_and(|(own, _)| own[..] != key[..]) {
            return Err(Error::Conflict);
        }
        let head = StoredChildHead::check(stored_head, &data, &revision, &key)?;
        if existing_rows.iter().any(|row| row.embed_id != data.embed_id()) {
            return Err(Error::Protocol);
        }
        let chat_id = data.chat_id().to_owned();
        self.cache(vec![data.embed_id().to_owned()], &key, &chat_id);
        Ok(PlannedEmbedWrite {
            kind: PlannedKind::ChildRevision { data, revision, head, existing: existing_rows },
            embed_key: key,
            chat_key: None,
            master: None,
        })
    }
    /// Adopt the canonical row after a `store_embed_diff` conflict on a child
    /// revision step (see [`super::revision::adopt_conflicting_row`]); uses the
    /// child's cached (parent-inherited) key from `plan_child_revision`.
    ///
    /// # Errors
    /// `embed_key_unavailable` when the key is not loaded; the errors of
    /// `adopt_conflicting_row`.
    pub fn adopt_child_revision_row(&self, local_row: &EncryptedDiffRow, page: &Value, now_seconds: i64) -> Result<EncryptedDiffRow> {
        self.with_embed_key(&local_row.embed_id, |key| super::revision::adopt_conflicting_row(page, local_row, key, now_seconds))
    }
    /// Content of version `version` of `embed_id`
    /// (`images-generate.revision.message-shows-its-version`): the head when it
    /// is the head version, else the `embed_diffs` snapshot row, opened with the
    /// key owner's key (the parent's for a child, from `head.parent_embed_id`).
    ///
    /// # Errors
    /// `embed_key_unavailable` when that key is not loaded; the errors of
    /// [`super::pinned::version_content`].
    pub fn embed_version_content(&self, embed_id: &str, version: i64, head: &Value, rows: &[Value]) -> Result<Zeroizing<String>> {
        let owner = head.get("parent_embed_id").and_then(Value::as_str).filter(|id| !id.is_empty()).unwrap_or(embed_id);
        self.with_embed_key(owner, |key| super::pinned::version_content(embed_id, version, head, rows, key))
    }
    /// Cache a fetched bounded-v1 page as local `embed_diffs` rows, validated
    /// with the key owner's key (the parent's for a child, from
    /// `head.parent_embed_id`).
    ///
    /// # Errors
    /// `embed_key_unavailable` when that key is not loaded; the errors of
    /// [`super::pinned::cache_version_page`].
    pub fn cache_version_page(&self, embed_id: &str, head: &Value, page: &Value, now_seconds: i64) -> Result<Vec<EncryptedDiffRow>> {
        let owner = head.get("parent_embed_id").and_then(Value::as_str).filter(|id| !id.is_empty()).unwrap_or(embed_id);
        self.with_embed_key(owner, |key| super::pinned::cache_version_page(embed_id, head, page, key, now_seconds))
    }
    /// Receipt of a sealed `(embed, N+1)` child revision output (see
    /// [`super::revision_recovery::embed_receipt`]), checked with the parent's
    /// key, the key the revision was written with.
    ///
    /// # Errors
    /// `embed_parent_key_pending` without the parent key; `Error::Protocol`
    /// for a payload without `revision`; the errors of `embed_receipt`.
    pub fn child_revision_embed_receipt(
        &self,
        sealed: &StreamedEmbedData,
        canonical_head: &Value,
        page: Option<&Value>,
        stored_head: Option<&Value>,
    ) -> Result<RevisionRecoveryReceipt> {
        let parent_id = sealed.parent_embed_id().ok_or(Error::Protocol)?;
        let (key, _) = self.embed_keys.get(parent_id).ok_or(PARENT_KEY_PENDING)?;
        super::revision_recovery::embed_receipt(sealed, canonical_head, page, stored_head, key)
    }
    /// Receipt of a sealed `(diff, N+1)` child revision row (see
    /// [`super::revision_recovery::row_receipt`]), checked with the key of the
    /// canonical head's parent.
    ///
    /// # Errors
    /// `embed_revision_head_mismatch` for a root head; `embed_key_unavailable`
    /// when the parent key is not loaded; the errors of `row_receipt`.
    pub fn child_revision_row_receipt(&self, row: &Value, canonical_head: &Value, page: Option<&Value>) -> Result<RevisionRecoveryReceipt> {
        let owner = canonical_head
            .get("parent_embed_id")
            .and_then(Value::as_str)
            .filter(|id| !id.is_empty())
            .ok_or(super::revision::REVISION_HEAD_MISMATCH)?;
        self.with_embed_key(owner, |key| super::revision_recovery::row_receipt(row, canonical_head, page, key))
    }
    /// Processing->finished `embed_update`. Parents keep the legacy cached-or-
    /// random key; children without an inherited key are refused (never a
    /// random key that would make the child undecryptable).
    pub fn plan_processing_update(&mut self, update: ProcessingEmbedUpdate) -> Result<PlannedEmbedWrite> {
        if self.master.is_none() {
            return Err(LOCAL_ONLY_REQUIRED);
        }
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
        let master = Some(self.master()?);
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
