//! Selected strict-first-page ciphertext DATA, independent of startup20 windows.
//! This optional checkpoint grants no auth, complete history or recovery proof.
//! Admission requires explicit adapter capacity policy BEFORE Client mutation.
use super::monitor::cached_view::bounded_bytes;
use super::*;
use serde::{Deserialize, Serialize};
use zeroize::Zeroize;
pub(super) const SNAPSHOT_FIELD: &str = "selected_first_pages";
const MAX_ROWS: usize = 100;
const MAX_BYTES: usize = super::transport::MAX_BODY;
#[derive(Clone, Serialize, Deserialize, PartialEq, Eq)]
#[serde(deny_unknown_fields)]
struct Cursor {
    created_at: i64,
    message_id: String,
}
#[derive(Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub(super) struct SelectedFirstPage {
    version: u8,
    chat_id: String,
    owner_sha256: String,
    scope_sha256: String,
    metadata_sha256: String,
    key_ciphertext_sha256: String,
    wrappers_sha256: String,
    pub(super) messages: Vec<Value>,
    metadata_messages_v: u64,
    server_message_count: Option<u64>,
    start_cursor: Cursor,
    end_cursor: Option<Cursor>,
    has_more_before: bool,
    history_complete: bool,
}
impl Drop for SelectedFirstPage {
    fn drop(&mut self) {
        self.chat_id.zeroize();
        self.owner_sha256.zeroize();
        self.scope_sha256.zeroize();
        self.metadata_sha256.zeroize();
        self.key_ciphertext_sha256.zeroize();
        self.wrappers_sha256.zeroize();
        for row in &mut self.messages {
            crate::model::zeroize_json(row);
        }
        self.start_cursor.message_id.zeroize();
        if let Some(cursor) = &mut self.end_cursor {
            cursor.message_id.zeroize();
        }
    }
}
fn json_digest(value: &impl Serialize) -> Result<String> {
    let encoded = zeroize::Zeroizing::new(serde_json::to_string(value)?);
    Ok(sha256(&encoded))
}
fn cursor(raw: &Value) -> Result<Cursor> {
    // Reuse the pinned bounded READ-ID policy and exact logical alias
    // preference; independent database UUIDs never replace client/message IDs.
    let id = super::message_window::server_message_id(raw)?;
    let created_at = raw["created_at"]
        .as_i64()
        .filter(|value| *value >= 0)
        .ok_or(Error::Protocol)?;
    Ok(Cursor {
        created_at,
        message_id: id.into(),
    })
}
fn page_cursor(value: &Value) -> Result<Cursor> {
    let cursor = Cursor::deserialize(value)?;
    if !super::message_window::valid_message_id(&cursor.message_id) || cursor.created_at < 0 {
        return Err(Error::Protocol);
    }
    Ok(cursor)
}
fn validate(page: &SelectedFirstPage) -> Result<()> {
    let parsed = uuid::Uuid::parse_str(&page.chat_id).map_err(|_| Error::Protocol)?;
    if parsed.hyphenated().to_string() != page.chat_id
        || page.version != 1
        || page.history_complete
        || !page.has_more_before
        || page.messages.is_empty()
    {
        return Err(Error::Protocol);
    }
    for stamp in [
        &page.owner_sha256,
        &page.scope_sha256,
        &page.metadata_sha256,
        &page.key_ciphertext_sha256,
        &page.wrappers_sha256,
    ] {
        if stamp.len() != 64
            || !stamp
                .bytes()
                .all(|byte| byte.is_ascii_digit() || (b'a'..=b'f').contains(&byte))
        {
            return Err(Error::Protocol);
        }
    }
    let rows = super::sync_windows::projected_rows(
        &page.messages,
        &page.chat_id,
        MAX_BYTES,
        MAX_ROWS,
        MAX_BYTES,
    )?;
    if rows != page.messages
        || rows.first().map(cursor).transpose()?.as_ref() != Some(&page.start_cursor)
        || page.end_cursor.as_ref().is_some_and(|end| {
            rows.last().map(cursor).transpose().ok().flatten().as_ref() != Some(end)
        })
        || page
            .server_message_count
            .is_some_and(|count| count <= rows.len() as u64)
        || bounded_bytes(page, MAX_BYTES).is_none()
    {
        return Err(Error::Protocol);
    }
    Ok(())
}
impl Client {
    pub(super) fn prepare_selected_first_page(
        &self,
        row: &Value,
        page: &Value,
    ) -> Result<SelectedFirstPage> {
        let id = required(row, "id")?;
        bounded_bytes(page, MAX_BYTES).ok_or(Error::Protocol)?;
        let messages = super::sync_windows::projected_rows(
            page["messages"].as_array().ok_or(Error::Protocol)?,
            id,
            MAX_BYTES,
            MAX_ROWS,
            MAX_BYTES,
        )?;
        if messages.iter().any(|raw| {
            raw.get("large_payload").is_some()
                && raw.get("encrypted_content").is_none_or(Value::is_null)
        }) {
            return Err(Error::Offline);
        }
        let (owner_sha256, scope_sha256) = self.sync_window_scope()?;
        let key = if text(row, "chat_visibility") == "direct" {
            required(row, "encrypted_chat_key")?
        } else {
            self.chat_key_ciphertext_from(row, false, &self.wrappers)?
                .ciphertext
        };
        let selected = SelectedFirstPage {
            version: 1,
            chat_id: id.into(),
            owner_sha256,
            scope_sha256,
            metadata_sha256: json_digest(row)?,
            key_ciphertext_sha256: sha256(key),
            wrappers_sha256: json_digest(&self.wrappers)?,
            messages,
            metadata_messages_v: row["messages_v"].as_u64().unwrap_or(0),
            server_message_count: page
                .get("server_message_count")
                .filter(|value| !value.is_null())
                .map(|value| value.as_u64().ok_or(Error::Protocol))
                .transpose()?,
            start_cursor: page_cursor(page.get("start_cursor").ok_or(Error::Protocol)?)?,
            end_cursor: page
                .get("end_cursor")
                .filter(|value| !value.is_null())
                .map(page_cursor)
                .transpose()?,
            has_more_before: page["has_more_before"].as_bool().ok_or(Error::Protocol)?,
            history_complete: false,
        };
        validate(&selected)?;
        Ok(selected)
    }
    pub(super) fn selected_first_page_owned(
        &self,
        page: &SelectedFirstPage,
        row: &Value,
    ) -> Result<bool> {
        let id = required(row, "id")?;
        let (owner, scope) = self.sync_window_scope()?;
        let key = if text(row, "chat_visibility") == "direct" {
            required(row, "encrypted_chat_key")?
        } else {
            self.chat_key_ciphertext_from(row, false, &self.wrappers)?
                .ciphertext
        };
        Ok(id == page.chat_id
            && self.task_watch_authority.cached_chat_allowed(id)
            && owner == page.owner_sha256
            && scope == page.scope_sha256
            && sha256(key) == page.key_ciphertext_sha256
            && json_digest(&self.wrappers)? == page.wrappers_sha256
            && row["messages_v"].as_u64().unwrap_or(0) >= page.metadata_messages_v)
    }
    pub(super) fn snapshot_selected_first_pages(&self) -> BTreeMap<&String, &SelectedFirstPage> {
        self.selected_first_pages
            .iter()
            .filter(|(id, _)| self.task_watch_authority.cached_chat_allowed(id))
            .collect()
    }
    pub(super) fn prospective_selected_checkpoint(
        &self,
        id: &str,
        page: &SelectedFirstPage,
    ) -> Result<Value> {
        let mut snapshot = super::plaintext::Plain::new(self.ciphertext_snapshot());
        if snapshot.get(SNAPSHOT_FIELD).is_none() {
            snapshot[SNAPSHOT_FIELD] = json!({});
        }
        snapshot[SNAPSHOT_FIELD][id] = serde_json::to_value(page)?;
        Ok(snapshot.into_inner())
    }
}
pub(super) fn restore(value: Option<&Value>) -> Result<BTreeMap<String, SelectedFirstPage>> {
    let Some(value) = value.filter(|value| !value.is_null()) else {
        return Ok(BTreeMap::new());
    };
    let object = value.as_object().ok_or(Error::Protocol)?;
    let mut pages = BTreeMap::new();
    for (id, raw) in object {
        // Validate each strict-page envelope independently; adapters enforce
        // their existing TOTAL checkpoint/store quota, never an invented cap.
        bounded_bytes(raw, MAX_BYTES).ok_or(Error::Protocol)?;
        let messages = raw["messages"].as_array().ok_or(Error::Protocol)?;
        let projected =
            super::sync_windows::projected_rows(messages, id, MAX_BYTES, MAX_ROWS, MAX_BYTES)?;
        if &projected != messages {
            return Err(Error::Protocol);
        }
        let page = SelectedFirstPage::deserialize(raw)?;
        if id != &page.chat_id {
            return Err(Error::Protocol);
        }
        validate(&page)?;
        pages.insert(id.clone(), page);
    }
    Ok(pages)
}
