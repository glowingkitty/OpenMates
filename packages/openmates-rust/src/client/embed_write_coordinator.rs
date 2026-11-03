//! Per-embed canonical write serialization (`canonicalEmbedWriteCoordinator`).
//! A lease is the only way to prepare/publish a canonical head and its wrapper
//! receipts; waiting writers resume in FIFO order once the holder drops it.
use crate::error::{Error, Result};
use std::collections::HashMap;
use std::sync::{Arc, Mutex};
use tokio::sync::{Mutex as AsyncMutex, OwnedMutexGuard};

#[derive(Default)]
pub struct EmbedWriteCoordinator {
    tails: Mutex<HashMap<String, Arc<AsyncMutex<()>>>>,
    acknowledged: Mutex<HashMap<String, (String, i64)>>,
}
/// Exclusive canonical write authority for one embed; not Clone/serializable.
pub struct EmbedWriteLease {
    embed_id: String,
    _guard: OwnedMutexGuard<()>,
}
impl EmbedWriteLease {
    pub fn embed_id(&self) -> &str {
        &self.embed_id
    }
}
impl EmbedWriteCoordinator {
    pub fn new() -> Self {
        Self::default()
    }
    /// `withCanonicalEmbedWrite`: wait for earlier writers of this embed.
    pub async fn lease(&self, embed_id: &str) -> Result<EmbedWriteLease> {
        if embed_id.is_empty() {
            return Err(Error::Invalid("Canonical embed write requires an embed ID."));
        }
        let tail = {
            let mut tails = self.tails.lock().map_err(|_| Error::Cancelled)?;
            // Drop idle tails (only the map holds them) so the map stays bounded.
            tails.retain(|id, lock| id == embed_id || Arc::strong_count(lock) > 1);
            tails.entry(embed_id.to_owned()).or_default().clone()
        };
        let guard = tail.lock_owned().await;
        Ok(EmbedWriteLease { embed_id: embed_id.to_owned(), _guard: guard })
    }
    /// `markAcknowledgedRecoveredEmbed`: keep the newest acknowledged version.
    pub fn mark_acknowledged(&self, lease: &EmbedWriteLease, chat_id: &str, version: i64) -> Result<()> {
        let mut acknowledged = self.acknowledged.lock().map_err(|_| Error::Cancelled)?;
        let replace = acknowledged
            .get(&lease.embed_id)
            .is_none_or(|(chat, known)| chat != chat_id || *known < version);
        if replace {
            acknowledged.insert(lease.embed_id.clone(), (chat_id.to_owned(), version));
        }
        Ok(())
    }
    /// `hasAcknowledgedRecoveredEmbed`: same chat and at least this version.
    pub fn has_acknowledged(&self, lease: &EmbedWriteLease, chat_id: &str, version: i64) -> Result<bool> {
        let acknowledged = self.acknowledged.lock().map_err(|_| Error::Cancelled)?;
        Ok(acknowledged
            .get(&lease.embed_id)
            .is_some_and(|(chat, known)| chat == chat_id && *known >= version))
    }
}
