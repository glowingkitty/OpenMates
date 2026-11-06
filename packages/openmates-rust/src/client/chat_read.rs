use super::transport::send;
use super::*;

const READ_CONFIRM_ATTEMPTS: u32 = if cfg!(test) { 3 } else { 20 };
const READ_CONFIRM_INTERVAL: std::time::Duration = std::time::Duration::from_millis(if cfg!(test) { 20 } else { 500 });

impl Client {
    /// Mark a saved chat read on every device (`feature.chat-unread@1`).
    ///
    /// Call once the newest assistant reply's last line has been on screen, or
    /// when the user answers it (a follow-up implies the reply was read). The
    /// server stores `unread_count = 0` and broadcasts `chat_read_status_updated`
    /// to the user's other devices; the cached row is patched locally so lists
    /// stop showing the counter without waiting for a refresh. Volatile and
    /// chats whose cached row says the count is already 0 send nothing. A row
    /// without a count (for example one created locally by `chats new`) is not
    /// known to be read, so the write is sent.
    pub async fn mark_chat_read(&mut self, chat_id: &str) -> Result<()> {
        self.require_session()?;
        uuid::Uuid::parse_str(chat_id).map_err(|_| Error::Invalid("Invalid chat ID."))?;
        if self.is_ephemeral_chat(chat_id) {
            return Ok(());
        }
        if self.operation_cancel.is_cancelled() {
            return Err(Error::Cancelled);
        }
        if self
            .chats
            .get(chat_id)
            .is_some_and(|row| row["unread_count"].as_u64() == Some(0))
        {
            return Ok(());
        }
        let mut ws = self.socket_with_task_jobs(false).await?;
        let sent = send(
            &mut ws,
            "chat_read_status_update",
            json!({"chat_id":chat_id,"unread_count":0}),
        )
        .await;
        // The write is fire-and-forget (no receipt reaches the sender), so the
        // server is polled until it stores the counter before a follow-up turn
        // can be dispatched. The socket stays open meanwhile: closing right
        // after the write can drop the frame before the handler runs.
        let stored = match sent {
            Ok(()) => self.await_stored_read(chat_id).await,
            Err(error) => Err(error),
        };
        let _ = ws.close(None).await;
        stored?;
        if let Some(row) = self.chats.get_mut(chat_id) {
            row["unread_count"] = json!(0);
        }
        Ok(())
    }
}

impl Client {
    /// Poll the server's selected chat row until it reports a zero counter.
    async fn await_stored_read(&mut self, chat_id: &str) -> Result<()> {
        for attempt in 0..READ_CONFIRM_ATTEMPTS {
            if attempt > 0 {
                crate::platform::time::sleep(READ_CONFIRM_INTERVAL).await;
            }
            if self.operation_cancel.is_cancelled() {
                return Err(Error::Cancelled);
            }
            if self.request_chat_unread_count(chat_id).await? == Some(0) {
                return Ok(());
            }
        }
        Err(Error::Offline)
    }

    /// A metadata refetch (opening a chat) carries no `unread_count`, so a
    /// replaced row would silently lose the counter the list sync stored and
    /// the cached list would stop showing the chat as unread. Keep the cached
    /// count until a server row states a new one.
    pub(super) fn carry_cached_unread_count(&self, id: &str, row: &mut Value) {
        if row.get("unread_count").is_some_and(|count| !count.is_null()) {
            return;
        }
        if let Some(count) = self.chats.get(id).and_then(|old| old.get("unread_count")).filter(|count| !count.is_null()) {
            row["unread_count"] = count.clone();
        }
    }
}

#[cfg(test)]
#[path = "chat_read_tests.rs"]
mod tests;
