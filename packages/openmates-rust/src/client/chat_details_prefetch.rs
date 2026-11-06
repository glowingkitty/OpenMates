//! Concurrent first-page requests and list-neutral row retention for the
//! selected rich read. No new route, credential, cache field or authority.
use super::*;

/// The HTTP watch projection stringifies these; `read_details` carries the
/// authorized row's original values (same rule as the browser bootstrap).
const CLOCK_FIELDS: &[&str] = &["created_at", "updated_at", "last_edited_overall_timestamp"];

fn present_text<'a>(row: &'a Value, field: &str) -> Option<&'a str> {
    row.get(field).and_then(Value::as_str).filter(|value| !value.is_empty())
}
fn draft_version(row: &Value) -> u64 {
    row.get("draft_v").and_then(Value::as_u64).unwrap_or(0)
}
/// The selected read replaces the saved row, so the server unread count from
/// `read_details` becomes the row's `unread_count`; without it `chats list`
/// would lose the badge after a chat is opened (feature.chat-unread@1). A
/// server that omits it keeps the count the saved row already had.
pub(super) fn with_selected_unread(
    row: &Value,
    details: &Value,
    cached_count: Option<u64>,
) -> Result<Value> {
    let mut selected = row.clone();
    match details.get("unread_count") {
        None | Some(Value::Null) => {
            if let Some(count) = cached_count {
                selected["unread_count"] = json!(count);
            }
        }
        Some(value) => {
            let count = value.as_u64().ok_or(Error::Protocol)?;
            selected["unread_count"] = json!(count);
        }
    }
    Ok(selected)
}
impl Client {
    /// True only when the server's selected row renders exactly the cached
    /// row's list output (title, summary, category, clocks, pin, versions and
    /// recency order) under the same wrapped chat key, with the same draft
    /// presence/version. Then the existing canonical (sync-shaped) row is kept,
    /// so an unchanged server state leaves every list input byte-identical.
    /// Any difference, Direct/draft-only row, missing canonical clock or
    /// unknown shape returns false: the server row replaces it as before, the
    /// list digest changes, and the next list resyncs.
    pub(super) fn selected_row_list_equivalent(
        &self,
        cached: &Value,
        server: &Value,
        key: &[u8; 32],
    ) -> Result<bool> {
        let Some(details) = server.get("read_details").and_then(Value::as_object) else {
            return Ok(false);
        };
        let mut canonical = server.clone();
        for field in CLOCK_FIELDS {
            let Some(value) = details.get(*field) else {
                return Ok(false);
            };
            canonical[*field] = value.clone();
        }
        let direct = |row: &Value| row.get("chat_visibility").and_then(Value::as_str) == Some("direct");
        if direct(cached)
            || direct(&canonical)
            || sync::draft_only(cached)
            || sync::draft_only(&canonical)
            || present_text(cached, "encrypted_chat_key").is_none()
            || present_text(cached, "encrypted_chat_key") != present_text(&canonical, "encrypted_chat_key")
            || present_text(cached, "encrypted_draft_md").is_some()
                != present_text(&canonical, "encrypted_draft_md").is_some()
            || draft_version(cached) != draft_version(&canonical)
            || cached["last_edited_overall_timestamp"] != canonical["last_edited_overall_timestamp"]
        {
            return Ok(false);
        }
        // Undecryptable/malformed rows are simply not equivalent: the server
        // row then replaces the cached row exactly as before.
        let render = |row: &Value| match self.chat_item(row, key) {
            Ok(item) => Ok(Some(item)),
            Err(Error::Crypto | Error::Protocol | Error::Forbidden) => Ok(None),
            Err(error) => Err(error),
        };
        let mut items = super::super::sync_capability::PlainItems(Vec::with_capacity(2));
        for row in [cached, &canonical] {
            match render(row)? {
                Some(item) => items.0.push(item),
                None => return Ok(false),
            }
        }
        let (a, b) = (&items.0[0], &items.0[1]);
        Ok(a.id == b.id
            && a.title == b.title
            && a.description == b.description
            && a.category == b.category
            && a.status == b.status
            && a.fields == b.fields)
    }
    pub(super) fn chat_details_messages_path(
        &self,
        id: &str,
        requested: usize,
        bounded: bool,
        cursor: Option<&Value>,
    ) -> Result<String> {
        let mut url = self.url(&format!("/v1/chats/{}/messages/window", segment(id)))?;
        {
            let mut q = url.query_pairs_mut();
            q.append_pair("direction", if cursor.is_some() { "before" } else { "latest" })
                .append_pair("limit", &requested.to_string())
                .append_pair(
                    "respect_compression_boundary",
                    if bounded { "true" } else { "false" },
                );
            if let Some(cursor) = cursor {
                q.append_pair("before_timestamp", &cursor["created_at"].to_string())
                    .append_pair("before_message_id", required(cursor, "message_id")?);
            }
        }
        self.scoped(&format!("{}?{}", self.request_route_path(&url)?, url.query().unwrap_or("")))
    }
    pub(super) fn chat_details_embeds_path(&self, id: &str, cursor: Option<&Value>) -> Result<String> {
        let mut url = self.url(&format!("/v1/embeds/chats/{}/window", segment(id)))?;
        if let Some(cursor) = cursor {
            url.query_pairs_mut()
                .append_pair("before_created_at", &cursor["created_at"].to_string())
                .append_pair("before_id", required(cursor, "id")?);
        }
        self.scoped(&format!(
            "{}{}",
            self.request_route_path(&url)?,
            url.query()
                .filter(|v| !v.is_empty())
                .map(|v| format!("?{v}"))
                .unwrap_or_default()
        ))
    }
}
