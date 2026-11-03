//! Shared chat read-state and chat-management policy (web units U11/U12).
//!
//! Pure, platform-free logic mirrored from the deployed web TypeScript:
//! visible-message receipts, encrypted message bookmarks, message highlight
//! payloads, hidden-chat key wrapping, chat-management socket payloads, chat
//! forks and chat-to-Project placement plans. Platform adapters keep IO (socket
//! send, HTTP, IndexedDB, localStorage, DOM) and pass explicit clocks/inputs.
//! Unread counters belong to `client::chat_read` and are not handled here.
pub mod bookmarks;
pub mod fork;
pub mod hidden;
pub mod highlights;
mod js;
pub mod management;
pub mod projects;
pub mod receipts;
