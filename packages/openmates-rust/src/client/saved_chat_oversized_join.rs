//! Joins the explicit exact read of an omitted oversized row into one bounded
//! saved-chat viewing page (shared core; called by the browser saved-read adapter).
//! Mirrors the oversized-cursor branch of `fetchAuthenticatedMessageWindow` in
//! `frontend/packages/ui/src/services/authenticatedChatMessageWindow.ts`.
//! Spec: `specifications/architecture/storage-lifecycle` (storage.cold.independent-message-pages).
use super::*;

impl Client {
    /// Resolve a viewing page whose only selected row was omitted for size.
    ///
    /// The server signals this with `oversized_message: true`, a cursor and no
    /// rows: the newest (or anchored) row alone exceeds the page byte budget.
    /// This performs exactly one exact-row read for that cursor (never a
    /// full-history replay) and joins the decrypted row into `read`. A page
    /// that is not oversized, or that already carries rows, is left unchanged.
    ///
    /// # Errors
    /// Every exact-read error (`Forbidden`, `Protocol`, `Cancelled`, ...) is
    /// returned unchanged; on error `read` keeps its original omitted shape and
    /// the caller must not publish it as resolved.
    pub(in crate::client) async fn resolve_oversized_saved_row(
        &mut self,
        id: &str,
        read: &mut SavedChatRead,
    ) -> Result<()> {
        if !read.window.oversized_message || !read.window.chat.messages.is_empty() {
            return Ok(());
        }
        let cursor = read
            .window
            .oversized_message_cursor
            .clone()
            .ok_or(Error::Protocol)?;
        let exact = self
            .saved_chat_exact_message(
                id,
                SavedChatExactOptions {
                    cursor,
                    content_mode: read.content_mode,
                },
            )
            .await?;
        join_exact_row(read, exact)
    }
}

/// Insert the exact row for the page's oversized cursor and mark it resolved.
///
/// Invariants: the exact row must be the cursor's row (id and `created_at`),
/// use the page's content mode and never claim complete history. After the
/// join the row is the page's only row, so it becomes both paging cursors and
/// the oversized marker is cleared: nothing on this page is omitted any more.
///
/// # Errors
/// `Error::Protocol` when the page is not an empty oversized page or the exact
/// row does not match its cursor; `read` is unchanged in that case.
pub(in crate::client) fn join_exact_row(
    read: &mut SavedChatRead,
    exact: SavedChatExactMessage,
) -> Result<()> {
    let exact = Plain::new(exact);
    let cursor = read
        .window
        .oversized_message_cursor
        .as_ref()
        .ok_or(Error::Protocol)?;
    if !read.window.oversized_message
        || !read.window.chat.messages.is_empty()
        || !read.message_metadata.is_empty()
        || exact.history_complete
        || exact.content_mode != read.content_mode
        || (exact.content_mode == SavedChatContentMode::PageLocal
            && exact.pii_restoration != "page_local")
        || exact.message.id != cursor.message_id
        || exact.message_metadata.id != cursor.message_id
        || exact.message_metadata.created_at != cursor.created_at
    {
        return Err(Error::Protocol);
    }
    let payload_bytes = read
        .window
        .payload_bytes
        .checked_add(exact.payload_bytes)
        .ok_or(Error::Protocol)?;
    let SavedChatExactMessage {
        message,
        chat_metadata,
        message_metadata,
        pii_mappings,
        ..
    } = exact.into_inner();
    // The page already carries this chat's metadata; the exact read's copy is
    // only authorization evidence and is wiped here instead of published.
    drop(Plain::new(chat_metadata));
    let cursor = read
        .window
        .oversized_message_cursor
        .take()
        .ok_or(Error::Protocol)?;
    if let Some(mappings) = pii_mappings {
        read.pii_mappings_by_message_id
            .insert(message.id.clone(), mappings);
    }
    read.window.chat.messages.push(message);
    read.message_metadata.push(message_metadata);
    read.window.payload_bytes = payload_bytes;
    read.window.start_cursor = Some(cursor.clone());
    read.window.end_cursor = Some(cursor);
    read.window.oversized_message = false;
    Ok(())
}

#[cfg(test)]
#[path = "saved_chat_oversized_join_tests.rs"]
mod tests;
