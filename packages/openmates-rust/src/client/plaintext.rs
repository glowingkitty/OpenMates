//! Owned plaintext scratch is wiped on rejection and dropped futures.
//! Public models remain movable/serializable and gain no destructor contract.
//! Only an accepted result or immediate guarded transfer disarms this wrapper.
//! This module changes allocation cleanup, not authentication or view authority.
//! Shared typed wipers include nested embeds, metadata and PII mapping values.
//! No plaintext clone or test-only runtime hook is needed for cleanup.
use super::message_window::{ChatMessageWindow, MessageWindowCursor};
use super::saved_chat_read::{
    SavedChatExactMessage, SavedChatMessageMetadata, SavedChatRead, SavedChatReadMetadata,
    SavedChatReadPage,
};
use super::*;
use std::ops::{Deref, DerefMut};
use zeroize::Zeroize;
pub(super) trait Wipe {
    fn wipe(&mut self);
}
pub(super) struct Plain<T: Wipe>(Option<T>);
impl<T: Wipe> Plain<T> {
    pub(super) fn new(value: T) -> Self {
        Self(Some(value))
    }
    pub(super) fn into_inner(mut self) -> T {
        self.0.take().expect("owned plaintext moves once")
    }
}
impl<T: Wipe> Deref for Plain<T> {
    type Target = T;
    fn deref(&self) -> &T {
        self.0.as_ref().expect("owned plaintext remains guarded")
    }
}
impl<T: Wipe> DerefMut for Plain<T> {
    fn deref_mut(&mut self) -> &mut T {
        self.0.as_mut().expect("owned plaintext remains guarded")
    }
}
impl<T: Wipe> Drop for Plain<T> {
    fn drop(&mut self) {
        if let Some(value) = &mut self.0 {
            value.wipe();
        }
    }
}
impl Wipe for String {
    fn wipe(&mut self) {
        self.zeroize();
    }
}
impl Wipe for Value {
    fn wipe(&mut self) {
        crate::model::zeroize_json(self);
    }
}
impl<T: Wipe> Wipe for Vec<T> {
    fn wipe(&mut self) {
        for value in self {
            value.wipe();
        }
    }
}
impl<T: Wipe> Wipe for Option<T> {
    fn wipe(&mut self) {
        if let Some(value) = self {
            value.wipe();
        }
    }
}
impl<T: Wipe> Wipe for BTreeMap<String, T> {
    fn wipe(&mut self) {
        for (mut key, mut value) in std::mem::take(self) {
            key.wipe();
            value.wipe();
        }
    }
}
impl Wipe for Item {
    fn wipe(&mut self) {
        super::sync_capability::wipe_item(self);
    }
}
impl Wipe for Message {
    fn wipe(&mut self) {
        let Message {
            id,
            role,
            content,
            sender,
            thinking,
            embeds,
        } = self;
        id.wipe();
        role.wipe();
        content.wipe();
        sender.wipe();
        thinking.wipe();
        embeds.wipe();
    }
}
impl Wipe for Chat {
    fn wipe(&mut self) {
        crate::client::monitor::cached_view::wipe_chat(self);
    }
}
impl Wipe for MessageWindowCursor {
    fn wipe(&mut self) {
        self.chat_id.wipe();
        self.scope.wipe();
        self.message_id.wipe();
    }
}
impl Wipe for ChatMessageWindow {
    fn wipe(&mut self) {
        self.chat.wipe();
        self.start_cursor.wipe();
        self.end_cursor.wipe();
        self.oversized_message_cursor.wipe();
        self.pii_restoration.wipe();
    }
}
impl Wipe for SavedChatReadMetadata {
    fn wipe(&mut self) {
        self.id.wipe();
        self.title.wipe();
        self.summary.wipe();
        self.category.wipe();
        self.slug.wipe();
        self.active_focus_id.wipe();
        self.parent_id.wipe();
        self.chat_visibility.wipe();
        self.participant_user_hashes.wipe();
        self.follow_up_suggestions.wipe();
    }
}
impl Wipe for SavedChatMessageMetadata {
    fn wipe(&mut self) {
        self.id.wipe();
        self.storage_id.wipe();
        self.source_message_id.wipe();
        self.client_message_id.wipe();
        self.chat_id.wipe();
        self.raw_status.wipe();
        self.sender_name.wipe();
        self.category.wipe();
        self.model_name.wipe();
        self.thinking_signature.wipe();
        self.hashed_user_id.wipe();
        self.user_message_id.wipe();
        self.queue_mode.wipe();
        self.queue_dispatch_status.wipe();
        self.queue_dispatch_mode.wipe();
        self.queue_dispatch_task_id.wipe();
        self.embed_ids.wipe();
    }
}
impl Wipe for SavedChatReadPage {
    fn wipe(&mut self) {
        self.chat.wipe();
        self.start_cursor.wipe();
        self.end_cursor.wipe();
        self.oversized_message_cursor.wipe();
        self.pii_restoration.wipe();
    }
}
impl Wipe for SavedChatRead {
    fn wipe(&mut self) {
        self.window.wipe();
        self.chat_metadata.wipe();
        self.message_metadata.wipe();
        self.pii_mappings_by_message_id.wipe();
    }
}
impl Wipe for SavedChatExactMessage {
    fn wipe(&mut self) {
        self.message.wipe();
        self.chat_metadata.wipe();
        self.message_metadata.wipe();
        self.pii_mappings.wipe();
        self.pii_restoration.wipe();
    }
}
impl Wipe for super::message_window::MessagePageData {
    fn wipe(&mut self) {
        self.incoming.take();
        self.window.wipe();
        self.mappings.wipe();
        self.metadata_stamp.wipe();
        self.chat_metadata.wipe();
        self.message_metadata.wipe();
    }
}
impl Wipe for super::local_cached_read::LocalEncryptedWindowInput {
    fn wipe(&mut self) {
        self.chat_metadata.wipe();
        self.messages.wipe();
        self.wrappers.wipe();
        self.compression_checkpoints.wipe();
    }
}
impl Wipe for super::monitor::cached_view::CachedChatWindow {
    fn wipe(&mut self) {
        self.chat.wipe();
    }
}
impl Wipe for super::monitor::ChatSelectionUpdate {
    fn wipe(&mut self) {
        match self {
            super::monitor::ChatSelectionUpdate::Updated(chat)
            | super::monitor::ChatSelectionUpdate::CacheSettled(chat) => chat.wipe(),
            super::monitor::ChatSelectionUpdate::Unavailable { chat_id } => chat_id.wipe(),
            super::monitor::ChatSelectionUpdate::Unchanged => {},
        }
    }
}
impl Wipe for super::monitor::ChatModels {
    fn wipe(&mut self) { self.items.wipe(); self.selection.wipe(); }
}
/// Replacing restored text must wipe its old allocation before freeing it.
pub(super) fn replace_text(target: &mut String, replacement: String) {
    target.wipe();
    *target = replacement;
}
#[cfg(all(test, not(target_arch = "wasm32")))]
#[path = "plaintext_tests.rs"]
mod tests;
