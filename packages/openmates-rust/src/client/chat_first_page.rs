//! Optional first usable cold-history display, independent of final authority.
//! No callback is made for a terminal first page: canonical publication follows.
use super::*;
use crate::client::{ChatRefreshDurableReceipt, sync_capability::AsyncCryptoScope};
use std::{future::Future, pin::Pin};

/// An adapter may persist the exact candidate, ACK credentials, and publish the
/// committed preview. It must not rebind Client operations or start another read.
/// The strict reader resumes only after success and original-scope revalidation.
pub trait ChatFirstPageSink: Send {
    /// Explicit platform/store capacity for the TOTAL prospective ciphertext
    /// checkpoint. This performs no write/ACK. Unknown capacity refuses only
    /// this optional preview; errors retain their normal fail-closed meaning.
    fn admit_checkpoint<'a>(
        &'a mut self,
        _client: &'a Client,
        _checkpoint_json_bytes: usize,
    ) -> Pin<Box<dyn Future<Output = Result<bool>> + Send + 'a>> {
        Box::pin(async { Ok(false) })
    }
    fn first_page<'a>(
        &'a mut self,
        client: &'a mut Client,
        candidate: ChatFirstPageCandidate,
    ) -> Pin<Box<dyn Future<Output = Result<()>> + Send + 'a>>;
}
pub struct ChatFirstPageCandidate {
    inner: CacheSettlementCandidate,
    has_more_before: bool,
}
pub struct ChatFirstPagePublication {
    inner: CacheSettlementPublication,
    has_more_before: bool,
}
impl ChatFirstPageCandidate {
    pub fn credential_revision(&self) -> u64 {
        self.inner.credential_revision()
    }
    pub fn ciphertext_sha256(&self) -> Result<String> {
        self.inner.ciphertext_sha256()
    }
}
impl ChatFirstPagePublication {
    pub fn is_valid(&self) -> bool {
        self.inner.is_valid()
    }
    /// Keep the ORIGINAL publication alive through adapter encoding. Rejection
    /// after the callback drops its zeroizing output instead of returning it.
    pub fn with_chat<T>(&self, render: impl FnOnce(&Chat) -> Result<T>) -> Result<T> {
        self.inner.with_window(|window| render(&window.chat))
    }
    pub fn into_window(self) -> Result<CachedChatWindow> {
        let mut window = self.inner.into_window()?;
        window.refreshing = true;
        window.pii_restoration = "page_local";
        window.has_more_before = Some(self.has_more_before);
        // Existing inner commit already sets history_complete=false.
        Ok(window)
    }
}
pub(in crate::client) struct FirstPageRead<'a> {
    sink: &'a mut dyn ChatFirstPageSink,
    fence: Arc<CachedOwnerFence>,
    request: CancellationToken,
    denial_revision: u64,
}
impl<'a> FirstPageRead<'a> {
    pub(super) fn new(
        sink: &'a mut dyn ChatFirstPageSink,
        fence: Arc<CachedOwnerFence>,
        request: CancellationToken,
        denial_revision: u64,
    ) -> Self {
        Self {
            sink,
            fence,
            request,
            denial_revision,
        }
    }
}
impl Client {
    pub fn validate_chat_first_page(&self, candidate: &ChatFirstPageCandidate) -> Result<()> {
        self.validate_cache_settlement(&candidate.inner)
    }
    /// Check a delayed original first-page publication under the same Client
    /// lock; this restricts saved output and grants no replacement admission.
    pub fn validate_chat_first_page_publication(
        &self,
        publication: &ChatFirstPagePublication,
    ) -> Result<()> {
        self.validate_cache_settlement_publication(&publication.inner)
    }

    pub fn commit_chat_first_page(
        &self,
        candidate: ChatFirstPageCandidate,
        receipt: ChatRefreshDurableReceipt,
    ) -> Result<ChatFirstPagePublication> {
        Ok(ChatFirstPagePublication {
            inner: self.commit_cache_settlement(candidate.inner, receipt)?,
            has_more_before: candidate.has_more_before,
        })
    }
    pub(in crate::client) async fn publish_chat_first_page(
        &mut self,
        read: &mut FirstPageRead<'_>,
        row: &Value,
        page: &Value,
        decoded: &[crate::model::Message],
        encrypted_rows: &[Value],
        key: &[u8; 32],
    ) -> Result<()> {
        let id = row["id"].as_str().ok_or(Error::Protocol)?;
        self.check_cached_view_owner(&read.fence)?;
        let scope = AsyncCryptoScope::begin(self)?;
        scope.check_chat(self, id)?;
        if read.request.is_cancelled()
            || read.fence.owner.cached_denial_revision()? != read.denial_revision
        {
            return Err(Error::Cancelled);
        }
        // Cache-miss fallback also handles rotation/unusable warm cache. Leave
        // those paths untouched; never rebind old rows under fresh metadata.
        if decoded.is_empty()
            || self.history.get(id).is_some_and(|rows| !rows.is_empty())
            || self.sync_message_windows.contains_key(id)
            || self.selected_first_pages.contains_key(id)
        {
            return Ok(());
        }
        // This distinct checkpoint retains ALL strict-page rows; startup20
        // windows and their byte/row policies are never widened or fabricated.
        let selected = match self.prepare_selected_first_page(row, page) {
            Ok(selected) => selected,
            Err(Error::Offline | Error::Protocol) => return Ok(()),
            Err(error) => return Err(error),
        };
        let prospective = Plain::new(self.prospective_selected_checkpoint(id, &selected)?);
        let checkpoint_json_bytes =
            bounded_bytes(&*prospective, usize::MAX).ok_or(Error::Protocol)?;
        let operation_epoch = self.fresh_auth.operation_epoch();
        let operation_binding = zeroize::Zeroizing::new(self.fresh_auth_binding()?);
        let admitted = read
            .sink
            .admit_checkpoint(self, checkpoint_json_bytes)
            .await?;
        self.verify_private_operation()?;
        self.require_canonical_read_profile()?;
        self.check_cached_view_owner(&read.fence)?;
        scope.check_chat(self, id)?;
        if read.request.is_cancelled()
            || self.fresh_auth.operation_epoch() != operation_epoch
            || self.fresh_auth_binding()? != *operation_binding
            || read.fence.owner.cached_denial_revision()? != read.denial_revision
            || read
                .fence
                .monitor
                .as_ref()
                .is_some_and(|monitor| !monitor.valid())
        {
            return Err(Error::Cancelled);
        }
        // Declared capacity refusal is the ONLY normal skip after this await.
        // No Client cache entry has changed, no prior ciphertext is evicted.
        if !admitted {
            return Ok(());
        }
        self.selected_first_pages.insert(id.to_owned(), selected);
        let current = Plain::new(self.ciphertext_snapshot());
        if *current != *prospective {
            self.selected_first_pages.remove(id);
            return Err(Error::Cancelled);
        }
        drop(current);
        drop(prospective);

        let mut item = Plain::new(self.chat_item(row, key)?);
        let mut chat = Plain::new(Chat {
            id: id.into(),
            title: std::mem::take(&mut item.title),
            category: std::mem::take(&mut item.category),
            messages: decoded.to_vec(),
        });
        // Only loaded USER rows contribute interim mappings. Older mappings
        // remain unknown until the unchanged strict final history completes.
        let rows = encrypted_rows
            .iter()
            .filter(|row| row["role"] == "user")
            .cloned()
            .collect::<Vec<_>>();
        crate::client::sync::restore_chat_tokens_from_rows(&mut chat, key, &rows)?;
        let candidate = self.capture_cache_settlement(
            read.fence.clone(),
            read.request.clone(),
            id,
            read.denial_revision,
            chat.into_inner(),
        )?;
        let ciphertext_sha256 = candidate.ciphertext_sha256()?;
        let revision = candidate.credential_revision();
        // Preserve the SAME original epoch/zeroizing binding captured before
        // capacity admission through the complete first-page callback too.
        read.sink
            .first_page(
                self,
                ChatFirstPageCandidate {
                    inner: candidate,
                    has_more_before: true,
                },
            )
            .await?;
        self.verify_private_operation()?;
        self.require_canonical_read_profile()?;
        self.check_cached_view_owner(&read.fence)?;
        scope.check_chat(self, id)?;
        if read.request.is_cancelled()
            || self.fresh_auth.operation_epoch() != operation_epoch
            || self.fresh_auth_binding()? != *operation_binding
            || self.credential_revision != revision
            || self.credential_ack != revision
            || crate::client::sha256(&serde_json::to_string(&self.ciphertext_snapshot())?)
                != ciphertext_sha256
            || read.fence.owner.cached_denial_revision()? != read.denial_revision
            || read
                .fence
                .monitor
                .as_ref()
                .is_some_and(|monitor| !monitor.valid())
        {
            return Err(Error::Cancelled);
        }
        Ok(())
    }
}
