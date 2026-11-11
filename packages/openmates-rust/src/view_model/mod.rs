//! Typed view-model boundary of the shared client core: plain owned records,
//! commands and events that a shell (terminal UI, Apple through UniFFI, web)
//! exchanges with the core instead of `serde_json::Value`.
//!
//! This is the shared-core side of the "View model" section in
//! `docs/plans/apple-client-core-migration/a2-design.md` (lane L6a). It holds
//! only data and fallible conversions from the shapes the core produces today
//! (`model::Item`, `model::Message`, `CachedChatWindow`, `StreamUpdate`); the
//! actor that emits these events arrives in later lanes.
//!
//! Records contain only `String`, integers, `bool`, `Vec`, `Option` and enums so
//! they can be exported through UniFFI without redesign.
mod convert;
mod error;
mod events;
mod records;

pub use convert::{
    chat_list_row_from_item, chat_window_from_cached, chat_window_from_chat, embed_ref_from_item,
    message_record_from_message, stream_event_from_update,
};
pub use error::{ViewErrorKind, ViewModelError};
pub use events::{AccessDenial, RequestId, SessionEvent, SyncPhase, ViewCommand, ViewEvent};
pub use records::{
    ChatListRow, ChatRowStatus, ChatWindowRecord, ChatWindowSource, EmbedRef, ListCompleteness,
    MessageRecord, MessageRole, MessageStatus, PiiRestoration, StreamEvent,
};

#[cfg(test)]
mod convert_tests;
#[cfg(test)]
mod events_tests;
