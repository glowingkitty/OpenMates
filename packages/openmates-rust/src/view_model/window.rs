//! The open chat window of the core view-model actor: which chat is open
//! under which request, the last published `ChatWindowRecord`, the cursor of
//! the next older page, and the steps that change it (cached first page,
//! strict read with durable receipt, older page, live update, close). Moved
//! from the TUI `runtime.rs` (`open_chat`, the selected-chat half of
//! `live_update`); spec `a2-design.md` (View model, lane L7) and
//! `architecture.sync` (on-demand message pages).
//!
//! Invariants: a window is published only after its data is durable
//! (receipt from `persist_for`, or `persist` for read-only offline cache);
//! a moved queue generation publishes nothing; live data changes only the
//! open chat's window; a closed window receives no further updates.
use super::{
    ChatWindowRecord, ChatWindowSource, ListCompleteness, MessageRecord, PiiRestoration, RequestId,
    ViewEvent, ViewSink, actor::ViewCore, chat_window_from_cached, chat_window_from_chat,
    first_page::FirstPageEmitter, message_record_from_message,
};
use crate::{
    client::{
        ChatInvalidation, ChatModels, ChatSelectionUpdate, ChatViewRead,
        message_window::{MessageWindowCursor, MessageWindowDirection, MessageWindowOptions},
    },
    error::{Error, Result},
    local_cache::{ByteStore, GenerationGuard},
    model::Chat,
    shell_session::cache_key,
};
use futures_util::future::BoxFuture;
use std::collections::HashSet;
use tokio_util::sync::CancellationToken;
use zeroize::Zeroize;

/// The one open chat of the actor.
pub(super) struct OpenWindow {
    /// The `OpenChat` request whose window this is; live updates reuse it.
    pub(super) request: RequestId,
    pub(super) chat_id: String,
    /// Last published window; `None` before the first page.
    pub(super) record: Option<ChatWindowRecord>,
    /// Cursor of the oldest server page merged so far; `None` until the first
    /// `LoadOlder` (cached and strict reads carry no server cursor).
    pub(super) older: Option<MessageWindowCursor>,
}

/// Put `older` (oldest first) before `messages`, skipping every id already
/// shown or repeated inside the page. Returns how many messages were added.
pub(super) fn merge_older(messages: &mut Vec<MessageRecord>, older: Vec<MessageRecord>) -> usize {
    let mut known: HashSet<String> = messages.iter().map(|message| message.id.clone()).collect();
    let fresh: Vec<MessageRecord> = older
        .into_iter()
        .filter(|message| known.insert(message.id.clone()))
        .collect();
    let added = fresh.len();
    messages.splice(0..0, fresh);
    added
}

/// Append the messages of a latest page that the window does not show yet
/// (replies that arrived after the cached or first page). Returns how many.
pub(super) fn merge_latest(messages: &mut Vec<MessageRecord>, latest: Vec<MessageRecord>) -> usize {
    let mut known: HashSet<String> = messages.iter().map(|message| message.id.clone()).collect();
    let before = messages.len();
    messages.extend(
        latest
            .into_iter()
            .filter(|message| known.insert(message.id.clone())),
    );
    messages.len() - before
}

fn records(chat: &Chat) -> Result<Vec<MessageRecord>> {
    chat.messages
        .iter()
        .map(message_record_from_message)
        .collect::<std::result::Result<_, _>>()
        .map_err(|_| Error::Protocol)
}

fn current(generation: &GenerationGuard) -> Result<()> {
    if generation.is_current() {
        Ok(())
    } else {
        Err(Error::Cancelled)
    }
}

impl<S: ByteStore + 'static> ViewCore<S> {
    /// Make `chat_id` the open chat of `request`, replacing any other window.
    pub(super) fn begin_window(&mut self, request: RequestId, chat_id: &str) {
        self.window = Some(OpenWindow {
            request,
            chat_id: chat_id.to_owned(),
            record: None,
            older: None,
        });
    }

    /// Forget the open window (session reset, logout, team switch).
    pub(super) fn retire_window(&mut self) {
        self.window = None;
    }

    /// Store `record` as the window of `request` and return its event;
    /// `None` when another open (or a close) superseded `request`.
    pub(super) fn publish_window(
        &mut self,
        request: RequestId,
        record: ChatWindowRecord,
    ) -> Option<ViewEvent> {
        let window = self
            .window
            .as_mut()
            .filter(|window| window.request == request && window.chat_id == record.chat_id)?;
        window.record = Some(record.clone());
        Some(ViewEvent::ChatWindow {
            request,
            window: record,
        })
    }

    /// Make the chat a send created or continued the open window of
    /// `request`, so live updates follow it (send stays shell-bridged until
    /// lane L9). Older history is unknown; paging starts from the latest page.
    ///
    /// # Errors
    /// `Protocol` for a malformed chat.
    pub fn track_sent_chat(&mut self, request: RequestId, chat: &Chat) -> Result<()> {
        let record = chat_window_from_chat(
            chat,
            ChatWindowSource::Canonical,
            None,
            false,
            false,
            PiiRestoration::PageLocal,
        )
        .map_err(|_| Error::Protocol)?;
        self.window = Some(OpenWindow {
            request,
            chat_id: chat.id.clone(),
            record: Some(record),
            older: None,
        });
        Ok(())
    }

    /// Close the window of `chat_id`; later live data for it changes nothing.
    /// Returns whether that chat was open. Shells call it for `CloseChat` and
    /// when access to the chat was denied.
    pub fn close_chat(&mut self, chat_id: &str) -> bool {
        if self.open_chat_id() == Some(chat_id) {
            self.window = None;
            return true;
        }
        false
    }

    /// The cached first page of `chat_id`, read without any network request.
    /// A partially restored client first decrypts the chat's cache section
    /// through the unqueued `CacheStore::cached_chat` fast path.
    ///
    /// # Errors
    /// Cache read and restore errors. A cached window that cannot be shown
    /// under the owner fences (not yet authenticated, unacknowledged
    /// credentials, denied chat) is `Ok(None)`: it is an optional preview and
    /// the strict read that follows reports the real outcome.
    pub(super) async fn cached_window(
        &mut self,
        chat_id: &str,
        cancel: &CancellationToken,
    ) -> Result<Option<ChatWindowRecord>> {
        let unloaded = self
            .client
            .partially_restored_chats()
            .is_some_and(|loaded| !loaded.iter().any(|id| id == chat_id));
        if unloaded {
            let credentials = self.client.session().ok_or(Error::Authentication)?;
            let section = self
                .session
                .cache()
                .cached_chat(
                    credentials.hashed_email.clone(),
                    cache_key(credentials),
                    credentials.master_key.clone(),
                    chat_id.to_owned(),
                )
                .await?;
            self.client
                .restore_cached_chat_content(chat_id, section.as_ref())?;
        }
        let publication = match self.client.cached_chat_publication(
            self.monitor.as_ref(),
            chat_id,
            cancel.clone(),
        ) {
            Ok(Some(publication)) => publication,
            Ok(None) | Err(_) => return Ok(None),
        };
        let Ok(mut window) = publication.into_window() else {
            return Ok(None);
        };
        let record = chat_window_from_cached(&window, ChatWindowSource::Cached);
        window.zeroize();
        record.map(Some).map_err(|_| Error::Protocol)
    }

    /// The strict read of `chat_id` (cache-preferred, cold first page through
    /// [`FirstPageEmitter`]), made durable and committed. A first page that
    /// was emitted stays the window even when the strict read then fails.
    ///
    /// # Errors
    /// Read, persistence and commit errors; `Forbidden` for offline cache when
    /// `offline_allowed` is false; `Cancelled` when the generation moved.
    pub(super) async fn read_window<K: ViewSink>(
        &mut self,
        request: RequestId,
        chat_id: &str,
        sink: &K,
        cancel: &CancellationToken,
        offline_allowed: bool,
    ) -> Result<ChatWindowRecord> {
        let generation = self.session.ops().guard();
        let mut first = FirstPageEmitter {
            session: &self.session,
            credentials: &*self.credentials,
            generation: generation.clone(),
            sink,
            request,
            published: None,
        };
        let read = self
            .client
            .read_chat_view_prefer_cache_with_first_page(
                self.monitor.as_ref(),
                chat_id,
                cancel.clone(),
                &mut first,
            )
            .await;
        let published = first.published.take();
        if let Some(record) = published {
            let _ = self.publish_window(request, record);
        }
        let read = read?;
        current(&generation)?;
        let (client, session, credentials) = (&mut self.client, &self.session, &*self.credentials);
        match read {
            ChatViewRead::Canonical(candidate) => {
                client.validate_chat_view(&candidate)?;
                let receipt = session.persist_for(client, credentials, &candidate).await?;
                current(&generation)?;
                let chat = client.commit_chat_view(candidate, receipt)?.into_chat()?;
                // A strict read carries the complete history.
                chat_window_from_chat(
                    &chat,
                    ChatWindowSource::Canonical,
                    Some(false),
                    true,
                    false,
                    PiiRestoration::AllCachedUserRows,
                )
                .map_err(|_| Error::Protocol)
            }
            ChatViewRead::CacheSettled(candidate) => {
                client.validate_cache_settlement(&candidate)?;
                let receipt = session.persist_for(client, credentials, &candidate).await?;
                current(&generation)?;
                let mut window = client
                    .commit_cache_settlement(candidate, receipt)?
                    .into_window()?;
                let record = chat_window_from_cached(&window, ChatWindowSource::CacheSettled);
                window.zeroize();
                record.map_err(|_| Error::Protocol)
            }
            ChatViewRead::CachedOffline(publication) => {
                if !offline_allowed {
                    return Err(Error::Forbidden);
                }
                session.persist(client, credentials).await?;
                current(&generation)?;
                let mut window = publication.into_window()?;
                let record = chat_window_from_cached(&window, ChatWindowSource::CachedOffline);
                window.zeroize();
                record.map_err(|_| Error::Protocol)
            }
        }
    }

    /// The open window of `chat_id` with the next older server page merged in
    /// front (oldest first, de-duplicated by message id). Without a cursor
    /// yet, the latest page is read first to obtain one. A window that is
    /// already complete is returned unchanged without network.
    ///
    /// # Errors
    /// `Invalid` when `chat_id` is not open or has no page yet, page read
    /// errors, `Protocol` when the server reports more history without a
    /// cursor, persistence errors.
    pub(super) async fn older_page(
        &mut self,
        chat_id: &str,
        cancel: &CancellationToken,
    ) -> Result<ChatWindowRecord> {
        let window = self
            .window
            .as_ref()
            .filter(|window| window.chat_id == chat_id)
            .ok_or(Error::Invalid("This chat is not open."))?;
        let mut record = window
            .record
            .clone()
            .ok_or(Error::Invalid("This chat window has no messages yet."))?;
        if record.history_complete || record.has_more_before == Some(false) {
            return Ok(record);
        }
        let mut cursor = window.older.clone();
        self.client.set_operation_cancel(cancel.clone());
        if cursor.is_none() {
            let latest = self
                .client
                .chat_message_window(chat_id, MessageWindowOptions::default())
                .await?;
            merge_latest(&mut record.messages, records(&latest.chat)?);
            record.has_more_before = Some(latest.has_more_before);
            cursor = latest.start_cursor;
        }
        if record.has_more_before == Some(true) {
            let before = cursor.take().ok_or(Error::Protocol)?;
            let page = self
                .client
                .chat_message_window(
                    chat_id,
                    MessageWindowOptions {
                        direction: MessageWindowDirection::Before,
                        cursor: Some(before),
                        ..MessageWindowOptions::default()
                    },
                )
                .await?;
            merge_older(&mut record.messages, records(&page.chat)?);
            record.has_more_before = Some(page.has_more_before);
            cursor = page.start_cursor;
        }
        // Server pages restore personal data from their own mappings only.
        record.pii_restoration = PiiRestoration::PageLocal;
        self.persist().await?;
        let window = self
            .window
            .as_mut()
            .filter(|window| window.chat_id == chat_id)
            .ok_or(Error::Cancelled)?;
        window.record = Some(record.clone());
        window.older = cursor;
        Ok(record)
    }

    /// One live read for the admitted monitor's pending invalidation `hint`
    /// (the open chat is the selected chat), made durable, committed and
    /// published through [`Self::apply_live_models`]. The shell keeps owning
    /// `hint` so a dropped or failed read can requeue it.
    ///
    /// # Errors
    /// `Cancelled` without a valid monitor, a cancelled `cancel` or a moved
    /// generation; read, persistence and commit errors unchanged (the shell
    /// tells denial, cancellation and offline apart).
    pub fn refresh_live<'a, K: ViewSink>(
        &'a mut self,
        hint: &'a ChatInvalidation,
        sink: &'a K,
        cancel: &'a CancellationToken,
    ) -> BoxFuture<'a, Result<()>> {
        Box::pin(async move {
            let generation = self.session.ops().guard();
            let selected = self.open_chat_id().map(str::to_owned);
            self.client.set_operation_cancel(cancel.clone());
            let monitor = self
                .monitor
                .as_ref()
                .filter(|monitor| monitor.is_valid())
                .ok_or(Error::Cancelled)?;
            let refresh = self
                .client
                .refresh_chat_monitor_prefer_cache(monitor, hint, selected.as_deref())
                .await?;
            self.client.validate_chat_refresh(&refresh)?;
            let receipt = self
                .session
                .persist_for(&mut self.client, &*self.credentials, &refresh)
                .await?;
            current(&generation)?;
            let publication = self.client.commit_chat_refresh(refresh, receipt)?;
            if cancel.is_cancelled() {
                return Err(Error::Cancelled);
            }
            let models = publication.into_models()?;
            self.apply_live_models(models, sink).await
        })
    }

    /// Publish the models of a committed live read: the chat list, then the
    /// open chat's window when the selection is the open chat
    /// (`ChatUnavailable` and a closed window when it became unreadable).
    /// Live data for any other chat changes only the list.
    ///
    /// # Errors
    /// `Protocol` for a malformed model, sink errors.
    pub(super) async fn apply_live_models<K: ViewSink>(
        &mut self,
        models: ChatModels,
        sink: &K,
    ) -> Result<()> {
        let ChatModels { items, selection } = models;
        let list = self.chat_list_event(items, ListCompleteness::Partial)?;
        sink.emit(list).await?;
        let (chat, source) = match selection {
            ChatSelectionUpdate::Updated(chat) => (chat, ChatWindowSource::Live),
            ChatSelectionUpdate::CacheSettled(chat) => (chat, ChatWindowSource::LiveSettled),
            ChatSelectionUpdate::Unavailable { chat_id } => {
                if self.close_chat(&chat_id) {
                    sink.emit(ViewEvent::ChatUnavailable { chat_id }).await?;
                }
                return Ok(());
            }
            ChatSelectionUpdate::Unchanged => return Ok(()),
        };
        let Some(window) = self
            .window
            .as_mut()
            .filter(|window| window.chat_id == chat.id)
        else {
            return Ok(());
        };
        // A live read keeps cached older rows plus the latest page: whether
        // more history exists is unknown, and paging restarts from the latest.
        let record =
            chat_window_from_chat(&chat, source, None, false, false, PiiRestoration::PageLocal)
                .map_err(|_| Error::Protocol)?;
        window.record = Some(record.clone());
        window.older = None;
        let request = window.request;
        sink.emit(ViewEvent::ChatWindow {
            request,
            window: record,
        })
        .await
    }
}
