//! Typed view-model boundary of the shared client core: plain owned records,
//! commands and events that a shell (terminal UI, Apple through UniFFI, web)
//! exchanges with the core instead of `serde_json::Value`, the chat list
//! order, and (native) the actor that serves the commands.
//!
//! This is the shared-core side of the "View model" section in
//! `docs/plans/apple-client-core-migration/a2-design.md` (lanes L6a records
//! and events, L6b actor, L7 chat window). Conversions are fallible; the
//! actor serves `Start`, the boot sync, `RefreshChats`, `SwitchTeam`,
//! `Logout`, `OpenChat`, `LoadOlder`, `CloseChat`, `MarkRead` and live window
//! updates, and bridges `Send` and `Cancel` to its shell host
//! (`ViewHost::bridge`).
//!
//! Records contain only `String`, integers, `bool`, `Vec`, `Option` and enums so
//! they can be exported through UniFFI without redesign.
//!
//! Temporary strangler seam (removed when A5/A6 move the remaining features
//! into the core): socket frames the core does not own pass through to the
//! shell (`socket_frames.rs`, `socket_passthrough.rs`, `unowned_flows.rs`),
//! and a shell drafts sync asks the core for server draft versions
//! (`draft_versions.rs`).
#[cfg(not(target_arch = "wasm32"))]
mod actor;
#[cfg(not(target_arch = "wasm32"))]
mod actor_flows;
#[cfg(not(target_arch = "wasm32"))]
mod actor_host;
mod arrange;
mod convert;
#[cfg(not(target_arch = "wasm32"))]
mod enrich;
mod error;
mod events;
#[cfg(not(target_arch = "wasm32"))]
mod first_page;
mod metadata;
mod records;
#[cfg(not(target_arch = "wasm32"))]
mod send_flows;
#[cfg(not(target_arch = "wasm32"))]
mod send_turn;
#[cfg(not(target_arch = "wasm32"))]
mod draft_versions;
mod socket_frames;
mod socket_passthrough;
#[cfg(not(target_arch = "wasm32"))]
mod unowned_flows;
#[cfg(not(target_arch = "wasm32"))]
mod window;
#[cfg(not(target_arch = "wasm32"))]
mod window_flows;

#[cfg(not(target_arch = "wasm32"))]
pub use actor::{RevocationHandle, ViewCore};
#[cfg(not(target_arch = "wasm32"))]
pub use actor_flows::{boot_sync, handle, logout, refresh_chats, start, switch_team};
#[cfg(not(target_arch = "wasm32"))]
pub use actor_host::{ListRecovery, ViewHost, ViewSink};
pub use arrange::{
    SAVED_ITEM_ID_PREFIX, arrange_chat_list, arrange_chat_list_at, place_home_entries,
};
#[cfg(not(target_arch = "wasm32"))]
pub use draft_versions::{DraftVersionQuery, ServerDraftVersion, draft_versions};
pub use convert::{
    chat_list_row_from_item, chat_window_from_cached, chat_window_from_chat, embed_ref_from_item,
    message_record_from_message, stream_event_from_update,
};
pub use error::{ViewErrorKind, ViewModelError};
pub use events::{AccessDenial, RequestId, SessionEvent, SyncPhase, ViewCommand, ViewEvent};
pub use metadata::{ChatRowMetadata, MessageMetadata, PiiMapping};
pub use records::{
    ChatListRow, ChatRowStatus, ChatWindowRecord, ChatWindowSource, EmbedRef, ListCompleteness,
    MessageRecord, MessageRole, MessageStatus, PiiRestoration, SendState, StreamEvent,
};
#[cfg(not(target_arch = "wasm32"))]
pub use send_flows::{SendCancelHandle, cancel_send, send};
pub use socket_frames::{
    CORE_AND_SHELL_EVENT_TYPES, CORE_EVENT_TYPES, SocketEventOwner, classify_socket_event,
    forwards_to_shell, shell_may_send,
};
pub use socket_passthrough::{
    INBOUND_BYTE_LIMIT, INBOUND_FRAME_LIMIT, OUTBOUND_QUEUE_LIMIT, OUTBOUND_SETTLE_TIMEOUT,
    UnownedFrameError, UnownedSocketItem,
};
pub(crate) use socket_passthrough::{OutboundFrame, SocketPassthrough};
#[cfg(not(target_arch = "wasm32"))]
pub use unowned_flows::UnownedFrameSender;
#[cfg(not(target_arch = "wasm32"))]
pub use window_flows::{close_chat, load_older, mark_read, open_chat};

#[cfg(all(test, unix))]
mod actor_tests;
#[cfg(test)]
mod arrange_tests;
#[cfg(test)]
mod convert_tests;
#[cfg(all(test, unix))]
mod draft_versions_tests;
#[cfg(test)]
mod events_tests;
#[cfg(all(test, unix))]
mod send_tests;
#[cfg(test)]
mod socket_frames_tests;
#[cfg(all(test, unix))]
mod unowned_tests;
#[cfg(all(test, unix))]
mod window_tests;
