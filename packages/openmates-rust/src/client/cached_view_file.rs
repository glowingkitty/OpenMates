//! One selected transcript from the native sectioned cache under its admitted
//! owner, key, workspace, and request. Stores and decoders remain core-owned.
//! Implements the cached first paint in architecture.sync and client-core.cache.
use super::*;
use crate::{
    client::{draft_clear, snapshot_sections, sync, sync_windows},
    crypto::{self, master::MasterCapability},
    local_cache::{ByteStore, CacheKey, CacheStore, GenerationGuard},
};
use futures_util::future::BoxFuture;

type ReadSection =
    dyn Fn(String, CacheKey) -> BoxFuture<'static, Result<Option<Value>>> + Send + Sync;

/// A selected-file, read-only lane for a native shell. It cannot use server
/// credentials, write cache, or publish across the original owner's revocation.
pub struct CachedChatFileReader {
    fence: Arc<CachedOwnerFence>,
    denial_revision: u64,
    lifetime: CancellationToken,
    generation: GenerationGuard,
    master: MasterCapability,
    privacy: Option<Arc<dyn Fn() -> Result<()> + Send + Sync>>,
    read_section: Box<ReadSection>,
    scope: (String, String),
    offline_personal: bool,
    headers: BTreeMap<String, Value>,
    wrappers: Vec<Value>,
}

/// A selected file result fenced through the shell's final paint.
pub struct CachedChatFilePublication {
    reader: Arc<CachedChatFileReader>,
    publication: CachedChatPublication,
}

impl CachedChatFilePublication {
    /// Reveal the bounded window only while file and owner authority still hold.
    pub fn into_window(self) -> Result<CachedChatWindow> {
        if !self.reader.is_owner_current() {
            return Err(Error::Cancelled);
        }
        let mut window = self.publication.into_window()?;
        if !self.reader.is_owner_current() {
            window.zeroize();
            return Err(Error::Cancelled);
        }
        Ok(window)
    }
}

impl CachedChatFileReader {
    /// Whether the original owner's admission is still usable for local display.
    pub fn is_owner_current(&self) -> bool {
        !self.lifetime.is_cancelled()
            && self.generation.is_current()
            && cached_owner_valid(&self.fence)
            && self.master.ensure_current().is_ok()
            && self.fence.owner.cached_denial_revision() == Ok(self.denial_revision)
            && self.privacy.as_ref().is_none_or(|gate| gate().is_ok())
    }

    fn check(&self, id: &str, request: &CancellationToken) -> Result<()> {
        if request.is_cancelled()
            || self.lifetime.is_cancelled()
            || !self.is_owner_current()
            || !self.fence.owner.cached_chat_allowed(id)
        {
            return Err(Error::Cancelled);
        }
        Ok(())
    }

    /// Release a bounded cached view for the selected full ID. The underlying
    /// blocking file operation may drain after cancellation; its data cannot
    /// reach the UI. A missing or undecodable selection leaves canonical open
    /// responsible for the final result.
    ///
    /// # Errors
    /// Invalid chat identifiers, revoked access, stale scope, or storage errors.
    pub async fn read(
        self: Arc<Self>,
        id: String,
        request: CancellationToken,
    ) -> Result<Option<CachedChatFilePublication>> {
        if !uuid::Uuid::parse_str(&id).is_ok_and(|uuid| uuid.hyphenated().to_string() == id) {
            return Err(Error::Invalid("A canonical full chat ID is required."));
        }
        self.check(&id, &request)?;
        if !self.headers.contains_key(&id) {
            return Ok(None);
        }
        let read = (self.read_section)(id.clone(), self.master.native_key()?.clone());
        let section = tokio::select! {
            biased;
            _ = self.lifetime.cancelled() => return Err(Error::Cancelled),
            _ = self.fence.owner.cancel.cancelled() => return Err(Error::Cancelled),
            _ = self.master.cancelled() => return Err(Error::Cancelled),
            _ = request.cancelled() => return Err(Error::Cancelled),
            section = read => section?,
        };
        self.check(&id, &request)?;
        let reader = self.clone();
        let selected_request = request.clone();
        let decode =
            tokio::task::spawn_blocking(move || reader.project(id, section, selected_request));
        let result = tokio::select! {
            biased;
            _ = self.lifetime.cancelled() => return Err(Error::Cancelled),
            _ = self.fence.owner.cancel.cancelled() => return Err(Error::Cancelled),
            _ = self.master.cancelled() => return Err(Error::Cancelled),
            _ = request.cancelled() => return Err(Error::Cancelled),
            result = decode => result.map_err(|_| Error::Io)??,
        };
        if !self.is_owner_current() || request.is_cancelled() || self.lifetime.is_cancelled() {
            return Err(Error::Cancelled);
        }
        Ok(result.map(|publication| CachedChatFilePublication {
            reader: self,
            publication,
        }))
    }

    fn project(
        &self,
        id: String,
        section: Option<Value>,
        request: CancellationToken,
    ) -> Result<Option<CachedChatPublication>> {
        self.check(&id, &request)?;
        let row = self.headers.get(&id).ok_or(Error::Cancelled)?;
        let Some(window) = self.decode(&id, row, section.as_ref()).ok() else {
            self.check(&id, &request)?;
            return Ok(None);
        };
        let window = Plain::new(window);
        self.check(&id, &request)?;
        let publication = CachedChatPublication {
            denial_revision: self.denial_revision,
            fence: self.fence.clone(),
            lifetime: self.lifetime.clone(),
            request,
            window: Arc::new(CachedWindowData {
                window: Mutex::new(Some(window.into_inner())),
            }),
            id,
        };
        if !publication.is_valid() || !self.is_owner_current() {
            return Err(Error::Cancelled);
        }
        Ok(Some(publication))
    }

    fn decode(&self, id: &str, row: &Value, section: Option<&Value>) -> Result<CachedChatWindow> {
        if row["id"].as_str() != Some(id) {
            return Err(Error::Protocol);
        }
        let partial = section
            .map(|value| snapshot_sections::chat_partial_snapshot(id, value))
            .transpose()?;
        let windows = sync_windows::restore_windows(
            partial
                .as_ref()
                .and_then(|value| value.get(sync_windows::SNAPSHOT_FIELD)),
        )?;
        let history = partial
            .as_ref()
            .and_then(|value| value["history"][id].as_array())
            .map(Vec::as_slice);
        let master = self.master.native_key()?;
        if draft_clear::is_cached_draft_shell(row, id, history, &self.wrappers)? {
            let preview =
                zeroize::Zeroizing::new(decrypt_optional(row, "encrypted_draft_preview", master)?);
            let item = Plain::new(crate::model::Item {
                title: if preview.is_empty() {
                    "Draft".to_owned()
                } else {
                    preview.to_string()
                },
                ..Default::default()
            });
            return decode_cached_draft(id, row, item).map(|(window, _)| window);
        }
        let selected = Client::select_chat_key_ciphertext(row, false, &self.wrappers, None)?;
        let synced = match windows.get(id) {
            Some(window)
                if window.matches_metadata(
                    row,
                    &self.wrappers,
                    &self.scope.0,
                    &self.scope.1,
                )? && window.matches_key(selected.ciphertext) =>
            {
                Some(window)
            }
            _ => None,
        };
        let mut limit = MAX_WINDOW_BYTES;
        let inputs = if self.offline_personal && let Some(history) = history {
            // Authenticated native sections already apply this same file cap.
            // Render all retained text when it fits; no coverage is inferred.
            limit = crate::local_cache::MAX_LOCAL_RECORD_BYTES;
            CachedRows { rows: history, has_more_before: None }
        } else {
            cached_rows(row, synced, history)?
        };
        let key =
            crate::client::key_from_bytes(&crypto::decrypt_bytes(selected.ciphertext, master)?)?;
        let mut item = Plain::new(sync::canonical_history::saved_item(row, &key)?);
        if sync::has_draft(row) {
            sync::draft_projection(row, master, &mut item)?;
        }
        decode_cached_rows(id, inputs, &key, item, limit).map(|(window, _)| window)
    }

    /// Retire this reader and any queued result, without cancelling actor work.
    pub fn close(&self) {
        self.lifetime.cancel();
    }
}

impl Drop for CachedChatFileReader {
    fn drop(&mut self) {
        self.close();
    }
}

impl Client {
    /// Bind an on-demand file reader to a genuinely authenticated native
    /// session with durably acknowledged credentials. Only an encrypted index
    /// is staged. The transcript file is read when a chat is selected.
    ///
    /// # Errors
    /// As the original owner and credential gate, or a revoked cache scope.
    pub fn stage_cached_chat_file_reader<S: ByteStore + 'static>(
        &self,
        monitor: Option<&ChatMonitor>,
        store: CacheStore<S>,
        lifetime: CancellationToken,
    ) -> Result<CachedChatFileReader> {
        let fence = self.cached_view_owner(monitor)?;
        self.verify_private_operation()?;
        if self.credential_ack != self.credential_revision || lifetime.is_cancelled() {
            return Err(Error::Cancelled);
        }
        let session = self.require_session()?;
        let owner = session.hashed_email.clone();
        let key = crate::shell_session::cache_key(session);
        let generation = store.ops().guard();
        let supported = self.supports_cached_default_chat_list();
        let reader = CachedChatFileReader {
            denial_revision: fence.owner.cached_denial_revision()?,
            fence,
            lifetime: lifetime.child_token(),
            generation,
            master: self.master_capability()?,
            privacy: self.options.private_operation_gate.clone(),
            read_section: Box::new(move |id, master| {
                store.cached_chat(owner.clone(), key.clone(), master, id)
            }),
            scope: self.sync_window_scope()?,
            offline_personal: false,
            headers: if supported {
                self.chats.clone()
            } else {
                BTreeMap::new()
            },
            wrappers: if supported {
                self.wrappers.clone()
            } else {
                Vec::new()
            },
        };
        if !reader.is_owner_current() {
            return Err(Error::Cancelled);
        }
        Ok(reader)
    }
}

impl Client {
    /// Stage a strictly local Personal-chat reader. The shell must supply a
    /// receipt authenticated by its existing vault record and restore the
    /// protected cache index before this call. It leaves live auth unchanged.
    ///
    /// # Errors
    /// A revoked, expired or mismatched vault profile or invalid local cache.
    #[doc(hidden)]
    pub fn stage_native_personal_offline_cache<S: ByteStore + 'static>(
        &self,
        receipt: &crate::client::NativePersonalOfflineReceipt,
        store: CacheStore<S>,
        lifetime: CancellationToken,
    ) -> Result<(CachedChatFileReader, Vec<crate::model::Item>, Option<String>)> {
        use crate::client::native_personal_offline::personal_saved_row;
        self.verify_private_operation()?;
        if lifetime.is_cancelled() || self.operation_cancel.is_cancelled() {
            return Err(Error::Cancelled);
        }
        let scope = receipt.cache_scope(self)?;
        let session = self.require_session()?;
        let owner = session.hashed_email.clone();
        let key = crate::shell_session::cache_key(session);
        let generation = store.ops().guard();
        let fence = Arc::new(CachedOwnerFence {
            owner: self.task_watch_authority.clone(),
            generation: self.generation,
            team: None,
            expires_at: Some(receipt.expires_at()),
            monitor: None,
        });
        let mut items = Plain::new(Vec::new());
        let mut headers = BTreeMap::new();
        for row in self.sidebar_chat_rows().filter(|row| personal_saved_row(row)) {
            let id = crate::client::required(row, "id")?;
            if self.is_deleted_chat(id) || !fence.owner.cached_chat_allowed(id) {
                continue;
            }
            let Ok(chat_key) = self.chat_key(row, &session.master_key) else { continue };
            items.push(self.chat_item(row, &chat_key)?);
            headers.insert(id.to_owned(), row.clone());
        }
        let selected = self.cached_startup_chat_id();
        // The last-opened chat and retained offline IDs can be older than
        // the metadata sidebar. They remain exact local selections only.
        for id in selected.as_deref().into_iter().chain(self.offline_cached_chat_ids()) {
            if self.is_deleted_chat(id) || !fence.owner.cached_chat_allowed(id) {
                continue;
            }
            if let Some(row) = self.chats.get(id).filter(|row| personal_saved_row(row)) {
                headers.entry(id.to_owned()).or_insert_with(|| row.clone());
            }
        }
        let initial = selected.filter(|id| headers.contains_key(id));
        let reader = CachedChatFileReader {
            denial_revision: fence.owner.cached_denial_revision()?,
            fence,
            lifetime: lifetime.child_token(),
            generation,
            master: self.master_capability()?,
            privacy: self.options.private_operation_gate.clone(),
            read_section: Box::new(move |id, master| {
                store.cached_chat(owner.clone(), key.clone(), master, id)
            }),
            scope,
            offline_personal: true,
            headers,
            wrappers: self.wrappers.clone(),
        };
        if !reader.is_owner_current() {
            return Err(Error::Cancelled);
        }
        Ok((reader, items.into_inner(), initial))
    }
}
