//! Fills the `metadata` of chat list rows and window messages from the rows
//! the client holds (`Client::chat_row_metadata`, `message_metadata_by_id`).
//! Every record-building site of the actor calls these right before it
//! publishes, so all list and window events carry the same facts. Plan
//! `apple-client-core-migration` (a4 lane 0).
use super::{ChatListRow, ChatWindowRecord};
use crate::{client::Client, error::Result};

/// Set each row's metadata from its held chat row (all `None` without one).
///
/// # Errors
/// As `Client::chat_row_metadata`.
pub(super) fn enrich_rows(client: &Client, rows: &mut [ChatListRow]) -> Result<()> {
    for row in rows {
        row.metadata = client.chat_row_metadata(&row.id)?;
    }
    Ok(())
}

/// Set the metadata of every window message whose row the client holds.
/// Messages without a held row (provisional send messages, messages merged
/// from an older server page) keep the metadata they already carry.
///
/// # Errors
/// As `Client::message_metadata_by_id`.
pub(super) fn enrich_window(client: &Client, record: &mut ChatWindowRecord) -> Result<()> {
    let mut found = client.message_metadata_by_id(&record.chat_id)?;
    for message in &mut record.messages {
        if let Some(metadata) = found.remove(&message.id) {
            message.metadata = metadata;
        }
    }
    Ok(())
}
