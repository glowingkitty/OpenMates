//! Shared exact legacy full-history accumulation; never a retained-window proof.
use super::super::plaintext::Plain;
use super::decrypt_optional;
use super::super::*;

pub(super) struct CanonicalPage {
    page: Value,
    decoded: Plain<Vec<Message>>,
    encrypted: Vec<Value>,
    first: bool,
}
impl CanonicalPage {
    pub(super) fn page(&self) -> &Value {
        &self.page
    }
    pub(super) fn decoded(&self) -> &[Message] {
        &self.decoded
    }
    pub(super) fn encrypted(&self) -> &[Value] {
        &self.encrypted
    }
    pub(super) fn first(&self) -> bool {
        self.first
    }
    pub(super) fn more(&self) -> bool {
        self.page["has_more_before"] == true
    }
}
struct CanonicalChunk {
    decoded: Plain<Vec<Message>>,
    encrypted: Vec<Value>,
}
pub(super) struct CanonicalHistory {
    id: String,
    // Pages arrive newest to oldest. Retain only the decoded/normalized rows,
    // without retaining the original response object or repeatedly moving all
    // previous rows. Plain still clears every retained page on cancellation.
    chunks: Vec<CanonicalChunk>,
    seen: std::collections::HashSet<String>,
    cursor: Option<Value>,
    pages: usize,
    finished: bool,
    explicit_terminal: bool,
}
impl CanonicalHistory {
    pub(super) fn new(id: &str) -> Self {
        Self {
            id: id.into(),
            chunks: vec![],
            seen: Default::default(),
            cursor: None,
            pages: 0,
            finished: false,
            explicit_terminal: false,
        }
    }
    pub(super) fn cursor(&self) -> Option<&Value> {
        self.cursor.as_ref()
    }
    pub(super) fn before_request(&self) -> Result<()> {
        if self.finished {
            return Err(Error::Protocol);
        }
        if self.pages >= 100 {
            return Err(Error::Invalid(
                "Chat history exceeds the supported window limit.",
            ));
        }
        Ok(())
    }
    pub(super) fn decode_page(&mut self, page: Value, key: &[u8; 32]) -> Result<CanonicalPage> {
        self.before_request()?;
        self.pages += 1;
        let mut decoded = Plain::new(Vec::<Message>::new());
        let mut encrypted = vec![];
        for raw in page["messages"].as_array().ok_or(Error::Protocol)? {
            // SAME canonical content/chat/identity/duplicate/crypto decoder.
            let (raw, message) = super::decode_chat_message(raw, &self.id, key, &mut self.seen)?;
            encrypted.push(raw);
            decoded.push(message);
        }
        Ok(CanonicalPage {
            first: self.cursor.is_none(),
            page,
            decoded,
            encrypted,
        })
    }
    pub(super) fn append_page(&mut self, page: CanonicalPage) -> Result<bool> {
        self.chunks.push(CanonicalChunk {
            decoded: page.decoded,
            encrypted: page.encrypted,
        });
        if page.page["has_more_before"] != true {
            self.finished = true;
            self.explicit_terminal = page.page["has_more_before"].as_bool() == Some(false);
            return Ok(true);
        }
        let next = page
            .page
            .get("start_cursor")
            .filter(|v| v.is_object())
            .ok_or(Error::Protocol)?
            .clone();
        if self.cursor.as_ref() == Some(&next) {
            return Err(Error::Protocol);
        }
        self.cursor = Some(next);
        Ok(false)
    }
    pub(super) fn into_parts(self) -> Result<(Plain<Vec<Message>>, Vec<Value>, bool)> {
        if !self.finished {
            return Err(Error::Protocol);
        }
        // Each row moves into the final chronological vector once. Checking
        // aggregate capacity preserves refusal rather than integer wrap for an
        // impossible oversized response; no partial history is published.
        let (message_count, encrypted_count) = self.chunks.iter().try_fold(
            (0usize, 0usize),
            |(messages, encrypted), chunk| -> Result<(usize, usize)> {
                Ok((
                    messages.checked_add(chunk.decoded.len()).ok_or(Error::Protocol)?,
                    encrypted.checked_add(chunk.encrypted.len()).ok_or(Error::Protocol)?,
                ))
            },
        )?;
        let mut messages = Plain::new(Vec::with_capacity(message_count));
        let mut encrypted = Vec::with_capacity(encrypted_count);
        for mut chunk in self.chunks.into_iter().rev() {
            messages.append(&mut *chunk.decoded);
            encrypted.append(&mut chunk.encrypted);
        }
        Ok((messages, encrypted, self.explicit_terminal))
    }
}

/// Exact non-draft Item crypto projection, usable without a Client borrow.
pub(super) fn saved_item(row: &Value, key: &[u8; 32]) -> Result<Item> {
    let mut item = Plain::new(Item {
        id: required(row, "id")?.into(),
        ..Item::default()
    });
    item.title = decrypt_optional(row, "encrypted_title", key)?;
    item.fields = json!({"created_at":row["created_at"],"updated_at":row["updated_at"],"pinned":row["pinned"],"messages_v":row["messages_v"],"chat_list_title":if row.get("encrypted_title").and_then(Value::as_str).is_some_and(|v|!v.is_empty()){Value::String(item.title.clone())}else{Value::Null}});
    item.description = decrypt_optional(row, "encrypted_chat_summary", key)?;
    item.category = decrypt_optional(row, "encrypted_category", key)?;
    Ok(item.into_inner())
}

#[cfg(test)]
#[path = "canonical_history_tests.rs"]
mod tests;
