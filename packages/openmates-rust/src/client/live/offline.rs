//! Offline merge on reconnect: send the outbox, or keep a private copy when edit access
//! was lost while offline.

use super::LiveError;
use super::engine::{LiveItem, SealedUpdate};

/// Edit access as the server reports it on reconnect.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum EditAccess {
    /// Still allowed to edit.
    HasEdit,
    /// Edit access was removed while offline.
    Lost,
}

/// What to do with the offline work.
#[derive(Clone, Debug, PartialEq, Eq)]
pub enum OfflineMerge {
    /// Send these sealed updates, oldest first; the server merges them with everyone else's.
    Send(Vec<SealedUpdate>),
    /// Nothing is sent; the user's text becomes a private copy.
    AccessLost {
        /// The local text form to save as a private copy.
        private_copy_text: String,
    },
}

/// Decides what happens to `item`'s offline changes on reconnect.
///
/// # Errors
/// [`LiveError::Empty`] when access was lost and the item has no text form.
pub fn merge_offline(item: &LiveItem, access: EditAccess) -> Result<OfflineMerge, LiveError> {
    match access {
        EditAccess::HasEdit => Ok(OfflineMerge::Send(item.outbox().to_vec())),
        EditAccess::Lost if item.outbox().is_empty() => Ok(OfflineMerge::Send(Vec::new())),
        EditAccess::Lost => Ok(OfflineMerge::AccessLost {
            private_copy_text: item.text_form()?,
        }),
    }
}
