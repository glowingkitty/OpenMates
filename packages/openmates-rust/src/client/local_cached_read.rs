//! Explicit local-profile reads reuse encrypted-row decoding without granting
//! canonical account/key association, server permission, freshness or completeness.
//! Input is existing caller-owned encrypted IDB data, not a fabricated Snapshot.
//! Only a currently admitted read-only local browser profile may use this seam.
//! No network, cache insertion, ACK, write, salt requirement or fallback enrollment
//! occurs; known denial, expiry, cancellation and key replacement still refuse.
use super::message_window::{MessageWindowCursor, MessageWindowDirection, MessageWindowOptions};
use super::plaintext::{Plain, replace_text};
use super::saved_chat_read::{SavedChatContentMode, SavedChatReadOptions};
use super::sync_capability::AsyncCryptoScope;
use super::*;

use serde::{Deserialize, Serialize};
#[path = "local_storage_wire.rs"]
pub(super) mod wire;
#[path = "local_checkpoint_presentation.rs"]
pub(in crate::client) mod checkpoint_presentation;

#[derive(Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub(super) struct LocalEncryptedWindowInput {
    pub(super) chat_metadata: Value,
    pub(super) messages: Vec<Value>,
    pub(super) wrappers: Vec<Value>,
    #[serde(default)]
    pub(super) compression_checkpoints: Vec<Value>,
    pub(super) boundary: Option<LocalCachedBoundary>,
}
#[derive(Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub(super) struct LocalCachedBoundary {
    pub(super) has_more_before: Option<bool>,
    pub(super) has_more_after: Option<bool>,
    pub(super) compression_boundary_timestamp: Option<i64>,
}
#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
pub(super) struct LocalCachedWindow {
    pub(super) source: &'static str,
    pub(super) read_only: bool,
    pub(super) cached: bool,
    pub(super) fresh: bool,
    pub(super) history_complete: bool,
    pub(super) coverage: &'static str,
    pub(super) chat: Chat,
    pub(super) has_more_before: Option<bool>,
    pub(super) has_more_after: Option<bool>,
    pub(super) anchor_found: bool,
    pub(super) start_cursor: Option<MessageWindowCursor>,
    pub(super) end_cursor: Option<MessageWindowCursor>,
    pub(super) payload_bytes: usize,
    pub(super) pii_restoration: &'static str,
}
impl Drop for LocalCachedWindow {
    fn drop(&mut self) {
        crate::client::monitor::cached_view::wipe_chat(&mut self.chat);
    }
}
#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
pub(super) struct LocalCachedSavedRead {
    #[serde(flatten)]
    pub(super) window: LocalCachedWindow,
    pub(super) chat_metadata: Value,
    pub(super) message_metadata: Vec<Value>,
    pub(super) pii_mappings_by_message_id: BTreeMap<String, Vec<Value>>,
    pub(super) content_mode: SavedChatContentMode,
    pub(super) pages_read: usize,
    pub(super) checkpoint_presentation: checkpoint_presentation::Presentation,
}
impl Drop for LocalCachedSavedRead {
    fn drop(&mut self) {
        crate::model::zeroize_json(&mut self.chat_metadata);
        for value in &mut self.message_metadata {
            crate::model::zeroize_json(value);
        }
        for values in self.pii_mappings_by_message_id.values_mut() {
            for value in values {
                crate::model::zeroize_json(value);
            }
        }
    }
}
fn position(row: &Value) -> Result<(i64, &str)> {
    wire::position(row)
}
fn local_cursor(row: Option<&Value>, id: &str, scope: &str) -> Result<Option<MessageWindowCursor>> {
    row.map(|row| {
        let (created_at, message_id) = position(row)?;
        Ok(MessageWindowCursor {
            chat_id: id.into(),
            scope: scope.into(),
            created_at,
            message_id: message_id.into(),
        })
    })
    .transpose()
}
/// Which admitted session reads retained rows: the offline local profile, or
/// an online browser session rendering its own cache before server reconcile.
/// Output provenance stays `local_profile` (retained, incomplete) in both modes.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub(crate) enum CachedViewMode {
    LocalProfile,
    OnlineCache,
}
impl Client {
    pub(super) fn cached_view_admitted(&self, view: CachedViewMode) -> bool {
        match view {
            CachedViewMode::LocalProfile => self.is_local_browser_profile(),
            CachedViewMode::OnlineCache => self.is_online_browser_cache_profile(),
        }
    }
    pub(super) fn local_cached_scope(&self) -> Result<String> {
        self.local_cached_scope_for(CachedViewMode::LocalProfile)
    }
    pub(super) fn local_cached_scope_for(&self, view: CachedViewMode) -> Result<String> {
        self.require_credentials()?;
        if !self.cached_view_admitted(view) {
            return Err(Error::Forbidden);
        }
        Ok(sha256(&serde_json::to_string(&(
            match view {
                CachedViewMode::LocalProfile => "local_profile",
                CachedViewMode::OnlineCache => "online_cache",
            },
            &self.message_window_nonce,
            self.generation,
            self.team()?,
        ))?))
    }
    pub(super) async fn local_cached_message_window(
        &self,
        id: &str,
        options: MessageWindowOptions,
        input: LocalEncryptedWindowInput,
    ) -> Result<LocalCachedWindow> {
        let result = self
            .local_cached_page(
                id,
                options,
                input,
                SavedChatContentMode::PageLocal,
                false,
                CachedViewMode::LocalProfile,
            )
            .await?;
        // Retained local models stay Drop-wiped until their final owned move.
        Ok(result.into_window())
    }
    pub(super) async fn local_cached_saved_chat_read(
        &self,
        id: &str,
        options: SavedChatReadOptions,
        input: LocalEncryptedWindowInput,
    ) -> Result<LocalCachedSavedRead> {
        self.local_cached_saved_chat_read_in(CachedViewMode::LocalProfile, id, options, input)
            .await
    }
    pub(super) async fn local_cached_saved_chat_read_in(
        &self,
        view: CachedViewMode,
        id: &str,
        options: SavedChatReadOptions,
        input: LocalEncryptedWindowInput,
    ) -> Result<LocalCachedSavedRead> {
        if !(1..=100).contains(&options.limit)
            || !(1..=5).contains(&options.max_pages)
            || usize::from(options.before.is_some())
                + usize::from(options.after.is_some())
                + usize::from(options.anchor_message_id.is_some())
                > 1
        {
            return Err(Error::Invalid("Invalid saved chat local selector."));
        }
        let direction = if options.before.is_some() {
            MessageWindowDirection::Before
        } else if options.after.is_some() {
            MessageWindowDirection::After
        } else if options.anchor_message_id.is_some() {
            MessageWindowDirection::Around
        } else {
            MessageWindowDirection::Latest
        };
        let selector = MessageWindowOptions {
            direction,
            limit: options.limit.min(super::message_window::MAX_MESSAGES),
            cursor: options.before.or(options.after),
            anchor_message_id: options.anchor_message_id,
            respect_compression_boundary: options.respect_compression_boundary,
        };
        let result = self
            .local_cached_page(id, selector, input, options.content_mode, true, view)
            .await?;
        let mut output = result.into_saved(options.content_mode);
        const FRAME_LIMIT:usize=checkpoint_presentation::MAX_PRESENTATION_FRAME_BYTES;
        if crate::client::monitor::cached_view::bounded_bytes(&output,FRAME_LIMIT).is_none(){output.checkpoint_presentation.omit_summary();}
        if crate::client::monitor::cached_view::bounded_bytes(&output,FRAME_LIMIT).is_none(){return Err(Error::Protocol);}
        if crate::client::monitor::cached_view::bounded_bytes(
            &output,
            super::saved_chat_read::MAX_OUTPUT_BYTES,
        )
        .is_none()
        {
            return Err(Error::Protocol);
        }
        Ok(output)
    }
    async fn local_cached_page(
        &self,
        id: &str,
        options: MessageWindowOptions,
        input: LocalEncryptedWindowInput,
        mode: SavedChatContentMode,
        include_checkpoints: bool,
        view: CachedViewMode,
    ) -> Result<LocalPage> {
        let mut input = Plain::new(input);
        if crate::client::monitor::cached_view::bounded_bytes(
            &*input,
            super::message_window::MAX_MESSAGE_BYTES,
        )
        .is_none()
        {
            return Err(Error::Protocol);
        }
        let scope = self.local_cached_scope_for(view)?;
        let admission = AsyncCryptoScope::begin(self)?;
        admission.check_chat(self, id)?;
        uuid::Uuid::parse_str(id).map_err(|_| Error::Invalid("A full chat ID is required."))?;
        wire::validate_options(&options, id, &scope)?;
        if required(&input.chat_metadata, "id")? != id {
            return Err(Error::Forbidden);
        }
        if crate::client::monitor::cached_view::bounded_bytes(
            &input.chat_metadata,
            super::message_window::MAX_MESSAGE_BYTES,
        )
        .is_none()
            || crate::client::monitor::cached_view::bounded_bytes(
                &input.wrappers,
                super::message_window::MAX_MESSAGE_BYTES,
            )
            .is_none()
        {
            return Err(Error::Protocol);
        }
        let normalized = Plain::new(wire::message_rows(&input.messages, id)?);
        let checkpoint_timestamp = wire::compression_timestamp(&input.compression_checkpoints, id)?;
        let boundary_timestamp = input
            .boundary
            .as_ref()
            .and_then(|b| b.compression_boundary_timestamp);
        if checkpoint_timestamp.is_some()
            && boundary_timestamp.is_some()
            && checkpoint_timestamp != boundary_timestamp
        {
            return Err(Error::Protocol);
        }
        let wrapping = self.cached_wrapping_capability()?;
        let key = self
            .chat_key_with_capability_from(&input.chat_metadata, &wrapping, &input.wrappers)
            .await?;
        admission.check_chat(self, id)?;
        if self.local_cached_scope_for(view)? != scope {
            return Err(Error::Cancelled);
        }
        let checkpoint_presentation = if include_checkpoints {
            Some(checkpoint_presentation::project(
                &input.compression_checkpoints,
                id,
                &key,
                None,
                || {
                    admission.check_chat(self, id)?;
                    if self.local_cached_scope_for(view)? != scope {
                        return Err(Error::Cancelled);
                    }
                    Ok(())
                },
            )?)
        } else {
            None
        };
        let boundary = input.boundary.take();
        if boundary
            .as_ref()
            .and_then(|b| b.compression_boundary_timestamp)
            .is_some_and(|v| v < 0)
        {
            return Err(Error::Protocol);
        }
        let mut retained = normalized.iter().collect::<Vec<_>>();
        if options.direction != MessageWindowDirection::Around
            && options.respect_compression_boundary
            && let Some(timestamp) = checkpoint_timestamp.or(boundary
                .as_ref()
                .and_then(|b| b.compression_boundary_timestamp))
        {
            retained.retain(|row| {
                row["created_at"].as_i64().is_some_and(|value| {
                    if checkpoint_timestamp.is_some() {
                        value > timestamp
                    } else {
                        value >= timestamp
                    }
                })
            });
        }
        if options.direction == MessageWindowDirection::Around {
            if let Some(anchor_position) = normalized.iter().find_map(|row| {
                position(row)
                    .ok()
                    .filter(|(_, physical)| Some(*physical) == options.anchor_message_id.as_deref())
            }) {
                let cutoff = if options.respect_compression_boundary {
                    checkpoint_timestamp.or(boundary
                        .as_ref()
                        .and_then(|b| b.compression_boundary_timestamp))
                } else {
                    None
                };
                // Deployed around has a compression-bounded older leg, an
                // explicit anchor, and a timestamp-open newer leg.
                retained.retain(|row| {
                    position(row).is_ok_and(|p| {
                        p == anchor_position
                            || p.0 > anchor_position.0
                            || wire::position_cmp(p, anchor_position).is_lt() && cutoff.is_none_or(|time| p.0 > time)
                    })
                });
            }
        }
        let all_len = retained.len();
        let mut anchor_found = false;
        let (start, end) = match options.direction {
            MessageWindowDirection::Latest => (all_len.saturating_sub(options.limit), all_len),
            MessageWindowDirection::Before => {
                let c = options.cursor.as_ref().ok_or(Error::Protocol)?;
                let end = retained.partition_point(|row| {
                    position(row).is_ok_and(|p| wire::position_cmp(p, (c.created_at, c.message_id.as_str())).is_lt())
                });
                (end.saturating_sub(options.limit), end)
            }
            MessageWindowDirection::After => {
                let c = options.cursor.as_ref().ok_or(Error::Protocol)?;
                let start = retained.partition_point(|row| {
                    position(row).is_ok_and(|p| !wire::position_cmp(p, (c.created_at, c.message_id.as_str())).is_gt())
                });
                (start, (start + options.limit).min(all_len))
            }
            MessageWindowDirection::Around => {
                if let Some(index) = retained.iter().position(|row| {
                    position(row).is_ok_and(|(_, physical)| {
                        Some(physical) == options.anchor_message_id.as_deref()
                    })
                }) {
                    anchor_found = true;
                    let before = (options.limit - 1) / 2;
                    let after = options.limit - 1 - before;
                    let start = index.saturating_sub(before);
                    (start, (index + 1 + after).min(all_len))
                } else {
                    (0, 0)
                }
            }
        };
        let selected = &retained[start..end];
        let start_cursor = local_cursor(selected.first().copied(), id, &scope)?;
        let end_cursor = local_cursor(selected.last().copied(), id, &scope)?;
        let mut item = Plain::new(self.chat_item(&input.chat_metadata, &key)?);
        let mut output = LocalPage {
            checkpoint_presentation,
            window: Some(LocalCachedWindow {
                source: "local_profile",
                read_only: true,
                cached: true,
                fresh: false,
                history_complete: false,
                coverage: "retained_only",
                chat: Chat {
                    id: id.into(),
                    title: std::mem::take(&mut item.title),
                    category: std::mem::take(&mut item.category),
                    messages: vec![],
                },
                has_more_before: if start > 0 {
                    Some(true)
                } else {
                    boundary.as_ref().and_then(|b| b.has_more_before)
                },
                has_more_after: if end < all_len {
                    Some(true)
                } else {
                    boundary.as_ref().and_then(|b| b.has_more_after)
                },
                anchor_found,
                start_cursor,
                end_cursor,
                payload_bytes: 0,
                pii_restoration: if mode == SavedChatContentMode::Stored {
                    "stored"
                } else {
                    "page_local"
                },
            }),
            chat_metadata: Value::Null,
            message_metadata: vec![],
            mappings: BTreeMap::new(),
        };
        let metadata = Plain::new(super::saved_chat_read::metadata::chat(
            &input.chat_metadata,
            id,
            &key,
        )?);
        output.chat_metadata = serde_json::to_value(&*metadata)?;
        let mut seen = std::collections::HashSet::new();
        for row in selected {
            if row.get("large_payload").is_some()
                && row
                    .get("encrypted_content")
                    .is_none_or(|value| value.is_null() || value.as_str() == Some(""))
            {
                return Err(Error::Offline);
            }
            // Shared decode owns ordinary clones on both success and error.
            // Rich raw IDB extensions remain solely in the guarded source rows.
            let closed = wire::decode_projection(row)?;
            let (raw, message) = super::sync::decode_chat_message(&closed, id, &key, &mut seen)?;
            output.window_mut().chat.messages.push(message);
            let message = output
                .window
                .as_ref()
                .expect("local window remains owned until final move")
                .chat
                .messages
                .last()
                .expect("decoded local message was just retained");
            let value = zeroize::Zeroizing::new(super::sync::decrypt_optional(
                &raw,
                "encrypted_pii_mappings",
                &key,
            )?);
            let values = Plain::new(if value.is_empty() {
                vec![]
            } else {
                serde_json::from_str::<Vec<Value>>(&value)?
            });
            if raw.get("encrypted_pii_mappings").is_some() {
                output
                    .mappings
                    .insert(message.id.clone(), values.into_inner());
            }
            // Closed source metadata keeps existing IDB flags/aliases; clear
            // extension fields never enter content or ciphertext persistence.
            let metadata = Plain::new(super::saved_chat_read::metadata::message(
                row, message, id, &key,
            )?);
            output
                .message_metadata
                .push(serde_json::to_value(&*metadata)?);
            let payload_bytes = output
                .window
                .as_ref()
                .expect("local window remains owned until final move")
                .payload_bytes
                .checked_add(
                    crate::client::monitor::cached_view::bounded_bytes(&raw, usize::MAX)
                        .ok_or(Error::Protocol)?,
                )
                .ok_or(Error::Protocol)?;
            output.window_mut().payload_bytes = payload_bytes;
        }
        if mode == SavedChatContentMode::PageLocal {
            let mappings = Plain::new(
                output
                    .window
                    .as_ref()
                    .expect("local window remains owned until final move")
                    .chat
                    .messages
                    .iter()
                    .filter(|message| message.role == "user")
                    .filter_map(|message| output.mappings.get(&message.id))
                    .flatten()
                    .cloned()
                    .collect::<Vec<Value>>(),
            );
            for message in &mut output.window_mut().chat.messages {
                let restored = crate::privacy::restore_page(&message.content, &mappings)?;
                replace_text(&mut message.content, restored);
                let restored = crate::privacy::restore_page(&message.thinking, &mappings)?;
                replace_text(&mut message.thinking, restored);
            }
        }
        if crate::client::monitor::cached_view::bounded_bytes(
            &output.window,
            super::saved_chat_read::MAX_OUTPUT_BYTES,
        )
        .is_none()
        {
            return Err(Error::Protocol);
        }
        admission.check_chat(self, id)?;
        if self.local_cached_scope_for(view)? != scope {
            return Err(Error::Cancelled);
        }
        // This is one local retained page, not network pages or a full census.
        Ok(output)
    }
}
struct LocalPage {
    checkpoint_presentation: Option<checkpoint_presentation::Presentation>,
    window: Option<LocalCachedWindow>,
    chat_metadata: Value,
    message_metadata: Vec<Value>,
    mappings: BTreeMap<String, Vec<Value>>,
}
impl LocalPage {
    fn window_mut(&mut self) -> &mut LocalCachedWindow {
        self.window
            .as_mut()
            .expect("local window remains owned until final move")
    }
    fn into_window(mut self) -> LocalCachedWindow {
        self.window
            .take()
            .expect("local window remains owned until final move")
    }
    fn into_saved(mut self, mode: SavedChatContentMode) -> LocalCachedSavedRead {
        LocalCachedSavedRead {
            checkpoint_presentation:self.checkpoint_presentation.take().expect("saved read retains checkpoint presentation"),
            window: self
                .window
                .take()
                .expect("local window remains owned until final move"),
            chat_metadata: std::mem::take(&mut self.chat_metadata),
            message_metadata: std::mem::take(&mut self.message_metadata),
            pii_mappings_by_message_id: std::mem::take(&mut self.mappings),
            content_mode: mode,
            pages_read: 0,
        }
    }
}
impl Drop for LocalPage {
    fn drop(&mut self) {
        crate::model::zeroize_json(&mut self.chat_metadata);
        for value in &mut self.message_metadata {
            crate::model::zeroize_json(value);
        }
        for values in self.mappings.values_mut() {
            for value in values {
                crate::model::zeroize_json(value);
            }
        }
    }
}
