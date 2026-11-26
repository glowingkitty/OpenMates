//! Exact encrypted row fallback when a native backward page exceeds its byte budget.
use super::*;

impl Client {
    pub(super) async fn fill_canonical_oversized_row(
        &mut self,
        chat: &str,
        page: &mut Value,
    ) -> Result<()> {
        let cursor = page["oversized_message_cursor"]
            .as_object()
            .ok_or(Error::Protocol)?;
        let id = cursor["message_id"]
            .as_str()
            .filter(|id| {
                crate::client::message_window::valid_message_id(id) && *id != "." && *id != ".."
            })
            .ok_or(Error::Protocol)?;
        let created = cursor["created_at"].as_i64().ok_or(Error::Protocol)?;
        if !page["messages"].as_array().is_some_and(Vec::is_empty)
            || page["has_more_before"] != true
        {
            return Err(Error::Protocol);
        }
        let path = self.scoped(&format!(
            "/v1/chats/{}/messages/{}",
            segment(chat),
            crate::client::saved_chat_read::exact_message_segment(id),
        ))?;
        let response = self.request(Method::GET, &path, None).await?;
        let row = response
            .get("message")
            .filter(|row| row.is_object())
            .ok_or(Error::Protocol)?;
        let bytes = crate::client::monitor::cached_view::bounded_bytes(
            row,
            crate::client::saved_chat_read::MAX_EXACT_BYTES,
        )
        .ok_or(Error::Protocol)?;
        if bytes == 0
            || crate::client::message_window::server_message_id(row)? != id
            || row["created_at"].as_i64() != Some(created)
        {
            return Err(Error::Protocol);
        }
        let cursor = page["oversized_message_cursor"].take();
        page["start_cursor"] = cursor;
        page["messages"] = json!([row]);
        Ok(())
    }
}
