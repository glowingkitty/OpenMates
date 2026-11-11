//! Typed view-model boundary of the shared client core: plain owned records,
//! commands and events that a shell (terminal UI, Apple through UniFFI, web)
//! exchanges with the core instead of `serde_json::Value`, the chat list
//! order, and (native) the actor that serves the commands.
//!
//! This is the shared-core side of the "View model" section in
//! `docs/plans/apple-client-core-migration/a2-design.md` (lanes L6a records
//! and events, L6b actor). Conversions are fallible; the actor serves
//! `Start`, the boot sync, `RefreshChats`, `SwitchTeam` and `Logout` and
//! bridges the remaining commands to its shell host (`ViewHost::bridge`).
//!
//! Records contain only `String`, integers, `bool`, `Vec`, `Option` and enums so
//! they can be exported through UniFFI without redesign.
#[cfg(not(target_arch = "wasm32"))]
mod actor;
#[cfg(not(target_arch = "wasm32"))]
mod actor_flows;
#[cfg(not(target_arch = "wasm32"))]
mod actor_host;
mod arrange;
mod convert;
mod error;
mod events;
mod records;

#[cfg(not(target_arch = "wasm32"))]
pub use actor::{RevocationHandle, ViewCore};
#[cfg(not(target_arch = "wasm32"))]
pub use actor_flows::{boot_sync, handle, logout, refresh_chats, start, switch_team};
#[cfg(not(target_arch = "wasm32"))]
pub use actor_host::{ListRecovery, ViewHost, ViewSink};
pub use arrange::{arrange_chat_list, arrange_chat_list_at, place_home_entries};
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

#[cfg(all(test, unix))]
mod actor_tests;
#[cfg(test)]
mod arrange_tests;
#[cfg(test)]
mod convert_tests;
#[cfg(test)]
mod events_tests;
