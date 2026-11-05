//! Ciphertext-only recent phase1b windows, separate from complete history.
//! Existing server/context admission owns every row; this module grants none.
//! Content admits at most20 parents and20 new rows/window with byte bounds.
//! All received metadata stays separate, within the existing global frame budget.
//! Keys use the existing scoped wrapper policy; unavailable keys defer content.
//! Metadata, pins, drafts and subchat discovery keep their existing policies.
//! Reconnects merge encrypted IDs; older cached rows are never deletion proof.
//! Snapshot restoration carries no auth, full-history or current-read proof.
//! Plaintext decryption is temporary validation and is erased before retention.
use super::*;
use std::collections::BTreeSet;
use serde::{Deserialize, Serialize};
use zeroize::Zeroizing;

pub(super) const SNAPSHOT_FIELD: &str = "sync_message_windows";
pub(super) const REQUEST_CONTEXT_EPOCH: u64 = 0;
const MAX_PARENTS: usize = 20;
const MAX_ROWS: usize = super::message_window::MAX_MESSAGES;
const MAX_WINDOW_BYTES: usize = super::message_window::MAX_MESSAGE_BYTES;
// Projection retains a subset of each raw row, copies at most ONE logical ID
// already serialized in that row, and adds message_id/chat_id field framing.
// Count serialized JSON, including control escapes: the copied ID is bounded
// by the whole raw window, not an invented per-ID length or ASCII multiplier.
const MAX_CANONICAL_CHAT_ID_BYTES: usize = 36;
const PROJECTED_FIELD_FRAMING_BYTES: usize = ("message_id".len() + 6)
    + ("chat_id".len() + 6 + MAX_CANONICAL_CHAT_ID_BYTES);
pub(super) const MAX_NORMALIZED_BYTES: usize = 2 * MAX_WINDOW_BYTES + MAX_ROWS * PROJECTED_FIELD_FRAMING_BYTES;
// Each complete cursor JSON uses the existing whole-window byte budget. Two
// cursors can repeat IDs outside the normalized rows; fixed framing retains its
// former 4096-byte reserve. Lifetime retained rows remain separately bounded.
const MAX_FIXED_DESCRIPTOR_BYTES: usize = 4096;
const MAX_WINDOW_DESCRIPTOR_BYTES: usize = 2 * MAX_WINDOW_BYTES + MAX_FIXED_DESCRIPTOR_BYTES;
const MAX_WINDOW_RECORD_BYTES: usize = MAX_NORMALIZED_BYTES + MAX_WINDOW_DESCRIPTOR_BYTES;
const MAX_PHASE_RECORD_BYTES: usize = MAX_PARENTS * MAX_WINDOW_RECORD_BYTES;
const ENCRYPTED_FIELDS: [&str; 7] = [
    "encrypted_content",
    "encrypted_sender_name",
    "encrypted_category",
    "encrypted_model_name",
    "encrypted_thinking_content",
    "encrypted_thinking_signature",
    "encrypted_pii_mappings",
];

#[derive(Clone, Serialize, Deserialize, PartialEq, Eq)]
#[serde(deny_unknown_fields)]
struct WindowCursor {
    created_at: i64,
    message_id: String,
}
#[derive(Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub(super) struct CiphertextMessageWindow {
    chat_id: String,
    metadata_sha256: String,
    owner_sha256: String,
    scope_sha256: String,
    key_ciphertext_sha256: String,
    wrappers_sha256: String,
    pub(super) messages: Vec<Value>,
    // Previously received rows stay encrypted and outside complete history.
    // This is ID-based retention, not permission/completeness or a new fetch.
    #[serde(default, skip_serializing_if = "BTreeMap::is_empty")]
    retained_rows: BTreeMap<String, Value>,
    // Scheduling only: the backend's current bounded parent order, not a clock
    // or a read/auth/freshness grant. Older ciphertext stays retained unranked.
    #[serde(default)]
    pub(super) source_rank: Option<u8>,
    server_message_count: u64,
    metadata_messages_v: u64,
    pub(super) has_more_before: bool,
    start_cursor: Option<WindowCursor>,
    oversized_message: bool,
    oversized_message_cursor: Option<WindowCursor>,
}
#[derive(Default)]
pub(super) struct Phase1Windows {
    metadata: BTreeMap<String, Value>,
    metadata_order: Vec<String>,
    expanded_metadata: BTreeMap<String, Value>,
    expanded_order: Vec<String>,
    // Parser DATA only, deliberately absent from merge_metadata and snapshots.
    // Existing older pagination is memory-only; an EOF is never hint/IO proof.
    older_metadata_pages: BTreeMap<String, Value>,
    windows: BTreeMap<String, PendingWindow>,
    order: Vec<String>,
    selected: Vec<String>,
}
struct PendingWindow {
    messages: Vec<Value>,
    count: u64,
    has_more_before: bool,
    start: Option<WindowCursor>,
    oversized: bool,
    oversized_cursor: Option<WindowCursor>,
}
fn canonical_id(id: &str) -> Result<()> {
    let parsed = uuid::Uuid::parse_str(id).map_err(|_| Error::Protocol)?;
    if parsed.hyphenated().to_string() != id {
        return Err(Error::Protocol);
    }
    Ok(())
}
fn scoped(payload: &Value, team: Option<&str>, expected_epoch: u64) -> Result<bool> {
    // Older producers omit this context/bounded-window protocol. Preserve the
    // existing metadata reader without accepting their content as a new cache
    // window. Explicit wrong current context is still a hard refusal.
    if payload.get("context_epoch").is_none_or(Value::is_null) || payload.get("team_id").is_none() {
        return Ok(false);
    }
    if payload.get("context_epoch").and_then(Value::as_u64) != Some(expected_epoch)
        || payload.get("team_id").and_then(Value::as_str) != team
        || (team.is_none() && !payload.get("team_id").is_some_and(Value::is_null))
    {
        return Err(Error::Forbidden);
    }
    Ok(true)
}
fn parent(row: &Value) -> bool {
    !row.get("is_sub_chat")
        .and_then(Value::as_bool)
        .unwrap_or(false)
        && row
            .get("parent_id")
            .is_none_or(|v| v.is_null() || v.as_str() == Some(""))
}
fn parse_cursor(value: Option<&Value>) -> Result<Option<WindowCursor>> {
    let Some(value) = value.filter(|v| !v.is_null()) else {
        return Ok(None);
    };
    if super::monitor::cached_view::bounded_bytes(value, MAX_WINDOW_BYTES).is_none() {
        return Err(Error::Protocol);
    }
    let cursor: WindowCursor = serde_json::from_value(value.clone())?;
    if !super::message_window::valid_message_id(&cursor.message_id) { return Err(Error::Protocol); }
    if cursor.created_at < 0 {
        return Err(Error::Protocol);
    }
    Ok(Some(cursor))
}
fn row_cursor(row: &Value) -> Result<WindowCursor> {
    let id = super::message_window::server_message_id(row)?;
    Ok(WindowCursor {
        created_at: row
            .get("created_at")
            .and_then(Value::as_i64)
            .filter(|n| *n >= 0)
            .ok_or(Error::Protocol)?,
        message_id: id.into(),
    })
}
// Deliberately project only ciphertext and non-private addressing/order fields.
// Plain content, rendered embeds and other server extensions are not retained.
fn large_payload_reference(value: &Value) -> Result<Value> {
    // Existing backend bounded_message_window reference schema; an exact body
    // is fetched only through its normal owner-authorized API, never this key.
    let size = value["size_bytes"]
        .as_u64()
        .filter(|size| *size > 0 && *size <= super::saved_chat_read::MAX_EXACT_BYTES as u64)
        .ok_or(Error::Protocol)?;
    let checksum = required(value, "checksum")?;
    if checksum.len() != 64
        || !checksum
            .bytes()
            .all(|byte| byte.is_ascii_digit() || (b'a'..=b'f').contains(&byte))
    {
        return Err(Error::Protocol);
    }
    Ok(json!({"object_key":required(value,"object_key")?,"checksum":checksum,"size_bytes":size}))
}
// Preserve the reviewed ordinary-window helper and its unchanged test oracle.
// Selected strict pages choose their distinct raw byte policy below.
fn encrypted_row(raw: &Value, id: &str) -> Result<Value> {
    encrypted_row_with_limit(raw, id, MAX_WINDOW_BYTES)
}
fn encrypted_row_with_limit(raw: &Value, id: &str, raw_bytes: usize) -> Result<Value> {
    let raw = super::plaintext::Plain::new(if let Some(text) = raw.as_str() {
        if text.len() > raw_bytes {
            return Err(Error::Protocol);
        }
        serde_json::from_str::<Value>(text)?
    } else {
        raw.clone()
    });
    let object = raw.as_object().ok_or(Error::Protocol)?;
    if object
        .get("chat_id")
        .and_then(Value::as_str)
        .is_some_and(|v| v != id)
    {
        return Err(Error::Forbidden);
    }
    let cursor = row_cursor(&raw)?;
    let role = required(&raw, "role")?;
    if role.is_empty() || role.len() > 32 {
        return Err(Error::Protocol);
    }
    let mut out = serde_json::Map::new();
    for field in ["id", "message_id", "client_message_id"] {
        if let Some(value) = object.get(field).filter(|v| !v.is_null()) {
            // row_cursor already validated every alias without normalizing it.
            out.insert(field.into(), value.clone());
        }
    }
    out.insert("message_id".into(), json!(cursor.message_id));
    out.insert("chat_id".into(), json!(id));
    out.insert("created_at".into(), json!(cursor.created_at));
    out.insert("role".into(), json!(role));
    for field in ENCRYPTED_FIELDS {
        if let Some(value) = object.get(field).filter(|v| !v.is_null()) {
            if !value.is_string() {
                return Err(Error::Protocol);
            }
            out.insert(field.into(), value.clone());
        }
    }
    // Retain the opaque exact-body selector without fetching it or pretending
    // its absent content is a decoded message. Presentation defers separately.
    if let Some(reference) = object.get("large_payload").filter(|value| !value.is_null()) {
        out.insert("large_payload".into(), large_payload_reference(reference)?);
    }
    Ok(Value::Object(out))
}
pub(super) fn message_rows(input: &[Value], id: &str, limit: usize) -> Result<Vec<Value>> {
    let rows = projected_rows(input, id, limit, MAX_ROWS, MAX_WINDOW_BYTES)?;
    // Enforce the source-derived normalized20-window budget at this wrapper.
    // Selected strict pages have their OWN100-row/16MiB record validator.
    normalized_rows_bytes(&rows)?;
    Ok(rows)
}
/// Selected strict first pages opt in to their own100-row/16MiB policy. The
/// existing startup/window wrapper above retains its unchanged20-row bound.
pub(super) fn projected_rows(input: &[Value], id: &str, limit: usize, max_rows: usize, raw_bytes: usize) -> Result<Vec<Value>> {
    if input.len() > max_rows {
        return Err(Error::Protocol);
    }
    let mut rows = Vec::new();
    let mut seen = std::collections::BTreeSet::new();
    let mut previous = None;
    let mut bytes = 0usize;
    for raw in input {
        bytes = bytes
            .checked_add(
                raw.as_str().map_or_else(|| super::monitor::cached_view::bounded_bytes(raw, limit).ok_or(Error::Protocol), |v| Ok(v.len()))?,
            )
            .ok_or(Error::Protocol)?;
        if bytes > limit {
            return Err(Error::Protocol);
        }
        let row = if raw_bytes == MAX_WINDOW_BYTES {
            encrypted_row(raw, id)?
        } else {
            encrypted_row_with_limit(raw, id, raw_bytes)?
        };
        let cursor = row_cursor(&row)?;
        let position = (cursor.created_at, cursor.message_id.clone());
        if !seen.insert(cursor.message_id) || previous.as_ref().is_some_and(|p| p >= &position) {
            return Err(Error::Protocol);
        }
        previous = Some(position);
        rows.push(row);
    }
    // No ownership/retention authority here. The20-window wrapper above and
    // selected strict-page validator each enforce their distinct normalized
    // output/record budget; never apply the20-row budget to100 selected rows.
    Ok(rows)
}
fn normalized_rows_bytes(rows: &[Value]) -> Result<usize> {
    let mut bytes = 0usize;
    for row in rows {
        bytes = bytes.checked_add(serde_json::to_vec(row)?.len()).ok_or(Error::Protocol)?;
        if bytes > MAX_NORMALIZED_BYTES { return Err(Error::Protocol); }
    }
    Ok(bytes)
}
fn cursor_bytes(cursor: Option<&WindowCursor>) -> Result<usize> {
    let bytes = serde_json::to_vec(&cursor)?.len();
    if bytes > MAX_WINDOW_BYTES { return Err(Error::Protocol); }
    Ok(bytes)
}
fn viewport_record_bytes(window: &CiphertextMessageWindow) -> Result<usize> {
    // Serialize only fixed descriptor fields, without cloning lifetime-retained
    // ciphertext. The roundtrip test independently compares the full struct's
    // serialization with only retained_rows cleared, catching field omissions.
    let descriptor = json!({
        "chat_id":window.chat_id,"metadata_sha256":window.metadata_sha256,
        "owner_sha256":window.owner_sha256,"scope_sha256":window.scope_sha256,
        "key_ciphertext_sha256":window.key_ciphertext_sha256,"wrappers_sha256":window.wrappers_sha256,
        "messages":[],"source_rank":window.source_rank,
        "server_message_count":window.server_message_count,"metadata_messages_v":window.metadata_messages_v,
        "has_more_before":window.has_more_before,"start_cursor":window.start_cursor,
        "oversized_message":window.oversized_message,"oversized_message_cursor":window.oversized_message_cursor,
    });
    let descriptor_bytes = serde_json::to_vec(&descriptor)?.len();
    // Empty [] is already in descriptor; each row and n-1 commas fill it.
    let framing = window.messages.len().saturating_sub(1);
    let cursors = cursor_bytes(window.start_cursor.as_ref())?
        .checked_add(cursor_bytes(window.oversized_message_cursor.as_ref())?).ok_or(Error::Protocol)?;
    let fixed = descriptor_bytes.checked_sub(cursors).and_then(|n| n.checked_add(framing)).ok_or(Error::Protocol)?;
    if fixed > MAX_FIXED_DESCRIPTOR_BYTES
        || descriptor_bytes.checked_add(framing).ok_or(Error::Protocol)? > MAX_WINDOW_DESCRIPTOR_BYTES {
        return Err(Error::Protocol);
    }
    let row_bytes = normalized_rows_bytes(&window.messages)?;
    let bytes = descriptor_bytes.checked_add(framing).and_then(|bytes| bytes.checked_add(row_bytes))
        .ok_or(Error::Protocol)?;
    if bytes > MAX_WINDOW_RECORD_BYTES { return Err(Error::Protocol); }
    Ok(bytes)
}
// Count retained metadata across phase1, expanded search, older pages and
// phase2 together; each may be below16MiB while their aggregate is not.
fn metadata_response_budget(metadata: &impl Serialize, expanded: &impl Serialize,
    older: &impl Serialize, chats: &BTreeMap<String, Value>) -> Result<()> {
    super::monitor::cached_view::bounded_bytes(&(metadata, expanded, older, chats), super::transport::MAX_BODY)
        .map(|_| ()).ok_or(Error::Protocol)
}
impl Phase1Windows {
    pub(super) fn metadata(&mut self, payload: &Value, team: Option<&str>) -> Result<()> {
        self.metadata_with_expected_epoch(payload, team, REQUEST_CONTEXT_EPOCH)
    }
    /// Request correlation only. The immutable original actor/context owns the
    /// expected epoch; equality cannot mint auth, freshness, recovery or IO proof.
    pub(super) fn metadata_with_expected_epoch(&mut self, payload: &Value, team: Option<&str>, expected_epoch: u64) -> Result<()> {
        if !scoped(payload, team, expected_epoch)? {
            return Ok(());
        }
        let mut rows = Vec::new();
        if let Some(row) = payload.get("chat_details").filter(|v| !v.is_null()) {
            rows.push(row);
        }
        if let Some(recent) = payload.get("recent_chat_metadata").filter(|v| !v.is_null()) {
            rows.extend(recent.as_array().ok_or(Error::Protocol)?);
        }
        // Metadata coverage is independent of the20-parent CONTENT budget.
        // The actual Phase1a producer includes extra candidates/pins and direct
        // child metadata. Keep every received row and its original order.
        // Preserve the existing changed-duplicate refusal; identical replay
        // adds no work and Phase2 still wins overlaps during the final merge.
        let mut additions=BTreeMap::<&str,&Value>::new();
        let mut addition_order=Vec::new();
        let mut used=super::monitor::cached_view::bounded_bytes(&self.metadata,super::transport::MAX_BODY).ok_or(Error::Protocol)?;
        let mut entries=self.metadata.len();
        for row in rows {
            let id=required(row,"id")?;canonical_id(id)?;
            if let Some(old)=self.metadata.get(id) {
                if old!=row{return Err(Error::Protocol)}
            } else if let Some(old)=additions.get(id) {
                if *old!=row{return Err(Error::Protocol)}
            } else {
                // Exact JSON map-entry accounting before cloning a new row.
                // Canonical UUID keys are ASCII, but use the maintained byte
                // counter so neither framing nor future escaping is guessed.
                let key=super::monitor::cached_view::bounded_bytes(&id,super::transport::MAX_BODY).ok_or(Error::Protocol)?;
                let value=super::monitor::cached_view::bounded_bytes(row,super::transport::MAX_BODY.saturating_sub(used)).ok_or(Error::Protocol)?;
                let extra=key.checked_add(1).and_then(|n|n.checked_add(value)).and_then(|n|n.checked_add(usize::from(entries!=0))).ok_or(Error::Protocol)?;
                used=used.checked_add(extra).filter(|n|*n<=super::transport::MAX_BODY).ok_or(Error::Protocol)?;
                entries=entries.checked_add(1).ok_or(Error::Protocol)?;
                additions.insert(id,row);addition_order.push(id);
            }
        }
        let mut staged=super::plaintext::Plain::new(self.metadata.clone());
        let mut order=super::plaintext::Plain::new(self.metadata_order.clone());
        for id in addition_order {staged.insert(id.to_owned(),(**additions.get(id).ok_or(Error::Protocol)?).clone());order.push(id.to_owned());}
        if super::monitor::cached_view::bounded_bytes(&*staged,super::transport::MAX_BODY)!=Some(used){return Err(Error::Protocol)}
        metadata_response_budget(&*staged, &self.expanded_metadata, &self.older_metadata_pages, &BTreeMap::new())?;
        // Commit only after full duplicate and aggregate-budget validation.
        drop(super::plaintext::Plain::new(std::mem::replace(&mut self.metadata,staged.into_inner())));
        drop(super::plaintext::Plain::new(std::mem::replace(&mut self.metadata_order,order.into_inner())));
        Ok(())
    }
    /// Final actor parser ownership transfer. All validation/replay checks have
    /// completed; move canonical metadata once rather than retaining duplicates.
    pub(super) fn take_metadata_ordered(&mut self,chats:&mut BTreeMap<String,Value>,order:&mut Vec<String>)->Result<()> {
        fn transfer(rows:&mut BTreeMap<String,Value>,ids:&mut Vec<String>,chats:&mut BTreeMap<String,Value>,order:&mut Vec<String>)->Result<()> {
            let mut rows=crate::client::plaintext::Plain::new(std::mem::take(rows));
            let ids=crate::client::plaintext::Plain::new(std::mem::take(ids));
            for id in ids.iter(){
                let row=rows.remove(id).ok_or(Error::Protocol)?;
                if let std::collections::btree_map::Entry::Vacant(entry)=chats.entry(id.clone()){order.push(id.clone());entry.insert(row);}
                else{drop(crate::client::plaintext::Plain::new(row));}
            }
            if !rows.is_empty(){return Err(Error::Protocol)}Ok(())
        }
        transfer(&mut self.metadata,&mut self.metadata_order,chats,order)?;
        transfer(&mut self.expanded_metadata,&mut self.expanded_order,chats,order)
    }
    pub(super) fn retained_navigation_bytes(&self,limit:usize)->Result<usize>{
        // Count every remaining owned navigation copy and unknown field. The
        // fixed known message-window collections are a separate bounded facet.
        super::monitor::cached_view::bounded_bytes(&(&self.metadata,&self.metadata_order,&self.expanded_metadata,&self.expanded_order,&self.older_metadata_pages),limit).ok_or(Error::Protocol)
    }
    pub(super) fn merge_metadata_ordered(&self, chats: &mut BTreeMap<String, Value>, order: &mut Vec<String>) {
        for (ids, rows) in [(&self.metadata_order, &self.metadata), (&self.expanded_order, &self.expanded_metadata)] {
            for id in ids {
                if let std::collections::btree_map::Entry::Vacant(entry) = chats.entry(id.clone()) {
                    order.push(id.clone());
                    entry.insert(rows[id].clone());
                }
            }
        }
    }
    pub(super) fn merge_metadata(&self, chats: &mut BTreeMap<String, Value>) {
        // The backend already selected these bounded Phase1a parents/pins.
        // Keep Phase2's later exact-ID row on overlap; no new IDs are fetched.
        for (id, row) in self.metadata.iter().chain(&self.expanded_metadata) {
            chats.entry(id.clone()).or_insert_with(|| row.clone());
        }
    }
    /// Existing backend wrappers only, on the original request context. This
    /// is opaque ingestion, not a native commit, key capability or full hint ACK.
    pub(super) fn metadata_response_with_expected_epoch(&mut self, kind: &str, payload: &Value,
        team: Option<&str>, expected_epoch: u64, chats: &BTreeMap<String, Value>) -> Result<()> {
        if !scoped(payload, team, expected_epoch)? { return Ok(()); }
        let older = kind == "load_more_chats_response";
        if !older && kind != "sync_metadata_chats_response" { return Err(Error::Protocol); }
        // Expanded-sync error is not an empty successful replacement. Older
        // errors are retained as page DATA for the eventual memory-only adapter.
        if let Some(error) = payload.get("error").filter(|v| !v.is_null()) {
            if !error.is_string() { return Err(Error::Protocol); }
            if !older { return Ok(()); }
        }
        let rows = payload["chats"].as_array().ok_or(Error::Protocol)?;
        if payload["total_count"].as_u64().is_none() { return Err(Error::Protocol); }
        if super::monitor::cached_view::bounded_bytes(payload, super::transport::MAX_BODY).is_none() { return Err(Error::Protocol); }
        let mut incoming = BTreeMap::<&str, &Value>::new();
        let mut order = Vec::new();
        for wrapper in rows {
            let row = wrapper.get("chat_details").ok_or(Error::Protocol)?;
            let id = required(row, "id")?; canonical_id(id)?;
            if let Some(old) = incoming.insert(id, row) {
                if old != row { return Err(Error::Protocol); }
            } else { order.push(id); }
        }
        if older {
            let offset = payload["offset"].as_u64().ok_or(Error::Protocol)?.to_string();
            if payload["has_more"].as_bool().is_none() { return Err(Error::Protocol); }
            if let Some(old) = self.older_metadata_pages.get(&offset) {
                return if old == payload { Ok(()) } else { Err(Error::Protocol) };
            }
            // Count every page plus already retained metadata BEFORE cloning.
            let mut pages = self.older_metadata_pages.iter().map(|(id,row)|(id.as_str(),row)).collect::<BTreeMap<_,_>>();
            pages.insert(offset.as_str(), payload);
            metadata_response_budget(&self.metadata, &self.expanded_metadata, &pages, chats)?;
            self.older_metadata_pages.insert(offset, payload.clone());
        } else {
            let mut staged = self.expanded_metadata.iter().map(|(id,row)|(id.as_str(),row)).collect::<BTreeMap<_,_>>();
            for id in &order {
                let row = incoming[id];
                if let Some(old) = staged.insert(id, row) {
                    if old != row { return Err(Error::Protocol); }
                }
            }
            metadata_response_budget(&self.metadata, &staged, &self.older_metadata_pages, chats)?;
            for id in order {
                if !self.expanded_metadata.contains_key(id) {
                    self.expanded_metadata.insert(id.to_owned(), incoming[id].clone());
                    self.expanded_order.push(id.to_owned());
                }
            }
        }
        Ok(())
    }
    // Provenance classification DATA from genuinely retained parser resources,
    // not a caller row flag. Used only to preserve older expanded/full-row policy.
    pub(super) fn expanded_only_ids(&self,phase2:&BTreeMap<String,Value>)->BTreeSet<String>{
        self.expanded_metadata.keys().filter(|id|!self.metadata.contains_key(*id)&&!phase2.contains_key(*id)).cloned().collect()
    }
    pub(super) fn validate_metadata_budget(&self, chats: &BTreeMap<String, Value>) -> Result<()> {
        metadata_response_budget(&self.metadata, &self.expanded_metadata, &self.older_metadata_pages, chats)
    }
    /// No serialization/persistence adapter is supplied for older page DATA.
    pub(in crate::client) fn older_metadata_pages(&self) -> &BTreeMap<String, Value> { &self.older_metadata_pages }
    pub(super) fn content(&mut self, payload: &Value, team: Option<&str>) -> Result<()> {
        self.content_with_expected_epoch(payload, team, REQUEST_CONTEXT_EPOCH)
    }
    /// Request correlation only. The immutable original actor/context owns the
    /// expected epoch; equality cannot mint auth, freshness, recovery or IO proof.
    pub(super) fn content_with_expected_epoch(&mut self, payload: &Value, team: Option<&str>, expected_epoch: u64) -> Result<()> {
        if !scoped(payload, team, expected_epoch)? {
            return Ok(());
        }
        let Some(chats) = payload.get("chats").and_then(Value::as_array) else {
            return Ok(());
        };
        if !chats.iter().any(|chat| {
            chat.get("message_window")
                .is_some_and(|value| !value.is_null())
        }) {
            // No bounded marker means unsupported legacy content, never full
            // history or an alternate authority source. Keep the normal read.
            return Ok(());
        }
        if chats.len() > MAX_PARENTS {
            return Err(Error::Protocol);
        }
        for chat in chats {
            let id = required(chat, "chat_id")?;
            canonical_id(id)?;
            if !self.selected.iter().any(|selected| selected == id) {
                if self.selected.len() >= MAX_PARENTS {
                    return Err(Error::Protocol);
                }
                self.selected.push(id.into());
            }
            let Some(messages) = chat.get("messages").filter(|value| !value.is_null()) else {
                continue;
            };
            let Some(window) = chat.get("message_window").filter(|value| !value.is_null()) else {
                continue;
            };
            let count = chat["server_message_count"]
                .as_u64()
                .ok_or(Error::Protocol)?;
            let messages = message_rows(
                messages.as_array().ok_or(Error::Protocol)?,
                id,
                MAX_WINDOW_BYTES,
            )?;
            if u64::try_from(messages.len()).map_err(|_| Error::Protocol)? > count {
                return Err(Error::Protocol);
            }
            let has_more = window["has_more_before"].as_bool().ok_or(Error::Protocol)?;
            let start = parse_cursor(window.get("start_cursor"))?;
            let oversized = window["oversized_message"]
                .as_bool()
                .ok_or(Error::Protocol)?;
            let oversized_cursor = parse_cursor(window.get("oversized_message_cursor"))?;
            if oversized != oversized_cursor.is_some() {
                return Err(Error::Protocol);
            }
            if start != messages.first().map(row_cursor).transpose()? {
                return Err(Error::Protocol);
            }
            // An empty compression-boundary window can truthfully have older
            // rows but no cursor. It is retained as partial/unpageable, never
            // fabricated into a full or cursor-authorized transcript.
            if !has_more && count > messages.len() as u64 {
                return Err(Error::Protocol);
            }
            let pending = PendingWindow {
                messages,
                count,
                has_more_before: has_more,
                start,
                oversized,
                oversized_cursor,
            };
            if let Some(old) = self.windows.get(id) {
                if serde_json::to_value((
                    &old.messages,
                    old.count,
                    old.has_more_before,
                    &old.start,
                    old.oversized,
                    &old.oversized_cursor,
                ))? != serde_json::to_value((
                    &pending.messages,
                    pending.count,
                    pending.has_more_before,
                    &pending.start,
                    pending.oversized,
                    &pending.oversized_cursor,
                ))? {
                    return Err(Error::Protocol);
                }
            } else {
                if self.windows.len() >= MAX_PARENTS {
                    return Err(Error::Protocol);
                }
                self.order.push(id.into());
                self.windows.insert(id.into(), pending);
            }
        }
        Ok(())
    }
}
impl Client {
    #[cfg(test)]
    pub(super) fn finish_sync_windows(&self,batch:Phase1Windows,chats:&BTreeMap<String,Value>,wrappers:&[Value])->Result<BTreeMap<String,CiphertextMessageWindow>>{
        // Preserve existing synchronous raw-key fixture assertions. The
        // async production path below never requests opaque master bytes.
        self.require_session()?;let wrapping=self.cached_wrapping_key()?;let mut keys=BTreeMap::new();
        for id in &batch.order {let Some(row)=chats.get(id)else{continue};
            let key=if text(row,"chat_visibility")=="direct"{self.direct_chat_key(row)}else{self.chat_key_ciphertext_from(row,false,wrappers).and_then(|selected|crypto::decrypt_bytes(selected.ciphertext,&wrapping)).and_then(|bytes|key_from_bytes(&bytes))};
            match key {Ok(key)=>{keys.insert(id.clone(),key);},Err(error@(Error::Expired|Error::Cancelled|Error::Authentication))=>return Err(error),Err(_)=>{}}
        }
        self.finish_sync_windows_with_keys(batch,chats,wrappers,&keys)
    }
    pub(super) async fn finish_sync_windows_with_capability(&self,batch:Phase1Windows,chats:&BTreeMap<String,Value>,wrappers:&[Value])->Result<BTreeMap<String,CiphertextMessageWindow>>{
        let scope=super::sync_capability::AsyncCryptoScope::begin(self)?;let wrapping=self.cached_wrapping_capability()?;let mut keys=BTreeMap::new();
        for id in &batch.order {let Some(row)=chats.get(id)else{continue};
            if !parent(row)||!self.task_watch_authority.cached_chat_allowed(id){continue}
            match self.chat_key_with_capability_from(row,&wrapping,wrappers).await {Ok(key)=>{keys.insert(id.clone(),key);},Err(error@(Error::Expired|Error::Cancelled|Error::Authentication))=>return Err(error),Err(_)=>{}}
            scope.check(self)?;
        }
        scope.check(self)?;self.finish_sync_windows_with_keys(batch,chats,wrappers,&keys)
    }
    fn finish_sync_windows_with_keys(
        &self,
        batch: Phase1Windows,
        chats: &BTreeMap<String, Value>,
        wrappers: &[Value],
        keys: &BTreeMap<String, Key>,
    ) -> Result<BTreeMap<String, CiphertextMessageWindow>> {
        self.require_credentials()?;
        if self.operation_cancel.is_cancelled() || self.task_watch_authority.cancel.is_cancelled() {
            return Err(Error::Cancelled);
        }
        let result=self.finish_sync_windows_verified_keys(batch,chats,wrappers,keys)?;
        if self.operation_cancel.is_cancelled() || self.task_watch_authority.cancel.is_cancelled() {
            return Err(Error::Cancelled);
        }
        self.require_credentials()?;
        Ok(result)
    }
    // Single-source policy loop for ordinary and genuine owned sibling phases.
    // All owner/key/negative checks remain on their actual calling resources.
    fn finish_sync_windows_verified_keys(&self,batch:Phase1Windows,chats:&BTreeMap<String,Value>,wrappers:&[Value],keys:&BTreeMap<String,Key>)->Result<BTreeMap<String,CiphertextMessageWindow>> {
        let (owner_sha256, scope_sha256) = self.sync_window_scope()?;
        let mut result = BTreeMap::new();
        let mut used = 0usize;
        for id in &batch.order {
            let pending = &batch.windows[id];
            let Some(row) = chats.get(id) else { continue };
            if !parent(row) || !self.task_watch_authority.cached_chat_allowed(id) {
                continue;
            }
            let Some(version) = row.get("messages_v").and_then(Value::as_u64) else {
                continue;
            };
            // This is the observed metadata version, not an invented message
            // window version. The server's independent count may legitimately
            // differ; never rewrite metadata or call this full/read authority.
            let Some(key)=keys.get(id) else {continue};
            let ciphertext=if text(row,"chat_visibility")=="direct" {required(row,"encrypted_chat_key")?}
                else{self.chat_key_ciphertext_from(row,false,wrappers)?.ciphertext};
            let key_ciphertext_sha256=sha256(ciphertext);
            // Match the web sync key guard: one bounded encrypted sample proves
            // this device can unwrap the chat key. Full decryption belongs to
            // the existing window decoder at view time, not eager sync work.
            let sample = pending.messages.iter().find_map(|message| {
                ENCRYPTED_FIELDS.iter().find_map(|field| {
                    message
                        .get(*field)
                        .and_then(Value::as_str)
                        .filter(|value| !value.is_empty())
                })
            });
            if let Some(cipher) = sample {
                match crypto::decrypt_combined(cipher, key) {
                    Ok(clear) => drop(Zeroizing::new(clear)),
                    Err(_) => continue,
                }
            }
            // With no encrypted message field there is no sample to decrypt;
            // the actual chat-key unwrap still succeeded. Preserve server
            // selectors/empty records as TS does, without content authority.
            let window = CiphertextMessageWindow {
                chat_id: id.clone(),
                metadata_sha256: sha256(&serde_json::to_string(row)?),
                owner_sha256: owner_sha256.clone(),
                scope_sha256: scope_sha256.clone(),
                key_ciphertext_sha256,
                wrappers_sha256: sha256(&serde_json::to_string(wrappers)?),
                messages: pending.messages.clone(),
                retained_rows: BTreeMap::new(),
                source_rank: batch
                    .selected
                    .iter()
                    .position(|selected| selected == id)
                    .map(|rank| rank as u8),
                server_message_count: pending.count,
                metadata_messages_v: version,
                has_more_before: pending.has_more_before,
                start_cursor: pending.start.clone(),
                oversized_message: pending.oversized,
                oversized_message_cursor: pending.oversized_cursor.clone(),
            };
            let bytes = viewport_record_bytes(&window)?;
            if bytes > MAX_WINDOW_RECORD_BYTES
                || bytes > MAX_PHASE_RECORD_BYTES.saturating_sub(used)
            {
                return Err(Error::Protocol);
            }
            used += bytes;
            result.insert(id.clone(), window);
        }
        // Match encrypted IDB row merges: receiving another recent viewport
        // cannot silently evict a different chat or previously received rows.
        // The20-parent budget bounds this phase's NEW work, not a hidden
        // lifetime offline quota. Existing platform capacity guards stay in
        // force; no data is deleted to make a persistence operation succeed.
        for (id, old) in &self.sync_message_windows {
            if old.owner_sha256 != owner_sha256 || old.scope_sha256 != scope_sha256 {
                continue;
            }
            if let Some(window) = result.get_mut(id) {
                let mut retained = old.retained_rows.clone();
                for row in &old.messages {
                    retained.insert(row_cursor(row)?.message_id, row.clone());
                }
                for row in &window.messages {
                    retained.remove(&row_cursor(row)?.message_id);
                }
                window.retained_rows = retained;
            } else {
                let mut retained = old.clone();
                if !batch.selected.is_empty() {
                    retained.source_rank = batch
                        .selected
                        .iter()
                        .position(|selected| selected == id)
                        .map(|rank| rank as u8);
                }
                result.insert(id.clone(), retained);
            }
        }
        Ok(result)
    }
    pub(super) fn snapshot_sync_windows(&self) -> &BTreeMap<String, CiphertextMessageWindow> {
        // Retention is independent of current display admission. A metadata/key
        // update may defer a window, but must not delete its owned ciphertext.
        &self.sync_message_windows
    }
    pub(super) fn sync_window_scope(&self) -> Result<(String, String)> {
        let session = self.require_credentials()?;
        let owner = self.user["id"]
            .as_str()
            .filter(|id| !id.is_empty())
            .or_else(|| self.user["user_id"].as_str().filter(|id| !id.is_empty()))
            .ok_or(Error::Authentication)?;
        Ok((
            sha256(owner),
            sha256(&serde_json::to_string(&(
                self.base.as_str(),
                &session.hashed_email,
                &session.active_team_id,
            ))?),
        ))
    }
    pub(super) fn sync_window_matches(
        &self,
        window: &CiphertextMessageWindow,
        row: &Value,
        wrappers: &[Value],
    ) -> Result<bool> {
        let id = required(row, "id")?;
        let (owner, scope) = self.sync_window_scope()?;
        if owner != window.owner_sha256 || scope != window.scope_sha256 {
            return Ok(false);
        }
        if window.wrappers_sha256 != sha256(&serde_json::to_string(wrappers)?) {
            return Ok(false);
        }
        if !self.task_watch_authority.cached_chat_allowed(id)
            || sha256(&serde_json::to_string(row)?) != window.metadata_sha256
            || row.get("messages_v").and_then(Value::as_u64) != Some(window.metadata_messages_v)
        {
            return Ok(false);
        }
        let ciphertext = if text(row, "chat_visibility") == "direct" {
            if self.direct_chat_key(row).is_err() {
                return Ok(false);
            }
            required(row, "encrypted_chat_key")?
        } else {
            match self.chat_key_ciphertext_from(row, false, wrappers) {
                Ok(value) => value.ciphertext,
                Err(_) => return Ok(false),
            }
        };
        Ok(sha256(ciphertext) == window.key_ciphertext_sha256)
    }
    /// All ciphertext already owned for this chat, sorted by canonical cursor.
    /// Cache retention is not current-message or complete-history authority.
    pub(super) fn owned_settlement_rows(&self, row: &Value) -> Result<Vec<Value>> {
        let id = required(row, "id")?;
        let mut rows = BTreeMap::new();
        if let Some(history) = self.history.get(id) {
            for raw in history {
                let raw = if let Some(text) = raw.as_str() { serde_json::from_str(text)? } else { raw.clone() };
                rows.insert(row_cursor(&raw)?.message_id, raw);
            }
        }
        if let Some(page) = self.selected_first_pages.get(id) {
            if !self.selected_first_page_owned(page, row)? { return Err(Error::Offline); }
            for raw in &page.messages { rows.insert(row_cursor(raw)?.message_id, raw.clone()); }
        }
        if let Some(window) = self.sync_message_windows.get(id) {
            let (owner, scope) = self.sync_window_scope()?;
            let key = if text(row, "chat_visibility") == "direct" { required(row, "encrypted_chat_key")? }
                else { self.chat_key_ciphertext_from(row, false, &self.wrappers)?.ciphertext };
            if owner != window.owner_sha256 || scope != window.scope_sha256
                || window.key_ciphertext_sha256 != sha256(key)
                || window.wrappers_sha256 != sha256(&serde_json::to_string(&self.wrappers)?)
                || row["messages_v"].as_u64().unwrap_or(0) < window.metadata_messages_v {
                return Err(Error::Offline);
            }
            for raw in window.retained_rows.values().chain(&window.messages) {
                rows.insert(row_cursor(raw)?.message_id, raw.clone());
            }
        }
        let mut ordered = rows.into_values().map(|row| {
            let cursor = row_cursor(&row)?;
            Ok(((cursor.created_at, cursor.message_id), row))
        }).collect::<Result<Vec<_>>>()?;
        ordered.sort_by(|a, b| a.0.cmp(&b.0));
        Ok(ordered.into_iter().map(|(_, row)| row).collect())
    }
    pub(super) fn retain_settlement_page(&mut self, row: &Value, page: &Value) -> Result<()> {
        let id = required(row, "id")?;
        let messages = message_rows(page["messages"].as_array().ok_or(Error::Protocol)?, id, MAX_NORMALIZED_BYTES)?;
        if messages.iter().any(|raw| raw.get("large_payload").is_some()
            && raw.get("encrypted_content").is_none_or(Value::is_null)) { return Err(Error::Offline); }
        let count = page["server_message_count"].as_u64().unwrap_or(row["messages_v"].as_u64().unwrap_or(0));
        let has_more = page["has_more_before"].as_bool().ok_or(Error::Protocol)?;
        let start = parse_cursor(page.get("start_cursor"))?;
        if messages.len() as u64 > count || start != messages.first().map(row_cursor).transpose()?
            || (!has_more && count > messages.len() as u64) { return Err(Error::Protocol); }
        let (owner, scope) = self.sync_window_scope()?;
        let key = if text(row, "chat_visibility") == "direct" { required(row, "encrypted_chat_key")? }
            else { self.chat_key_ciphertext_from(row, false, &self.wrappers)?.ciphertext };
        let mut retained_rows = BTreeMap::new();
        if let Some(old) = self.sync_message_windows.get(id) {
            retained_rows = old.retained_rows.clone();
            for raw in &old.messages { retained_rows.insert(row_cursor(raw)?.message_id, raw.clone()); }
        }
        for raw in &messages { retained_rows.remove(&row_cursor(raw)?.message_id); }
        let window = CiphertextMessageWindow {
            chat_id: id.into(), metadata_sha256: sha256(&serde_json::to_string(row)?),
            owner_sha256: owner, scope_sha256: scope, key_ciphertext_sha256: sha256(key),
            wrappers_sha256: sha256(&serde_json::to_string(&self.wrappers)?),
            source_rank: self.sync_message_windows.get(id).and_then(|window| window.source_rank),
            messages, retained_rows,
            server_message_count: count,
            metadata_messages_v: row["messages_v"].as_u64().unwrap_or(0),
            has_more_before: has_more,
            start_cursor: start, oversized_message: false,
            oversized_message_cursor: None,
        };
        viewport_record_bytes(&window)?;
        self.sync_message_windows.insert(id.into(), window);
        Ok(())
    }
    pub(super) fn synced_window(&self, row: &Value) -> Result<Option<&CiphertextMessageWindow>> {
        let Some(window) = self.sync_message_windows.get(required(row, "id")?) else {
            return Ok(None);
        };
        Ok(self
            .sync_window_matches(window, row, &self.wrappers)?
            .then_some(window))
    }
}

pub(super) fn restore_windows(
    value: Option<&Value>,
) -> Result<BTreeMap<String, CiphertextMessageWindow>> {
    let Some(value) = value.filter(|v| !v.is_null()) else {
        return Ok(BTreeMap::new());
    };
    let object = value.as_object().ok_or(Error::Protocol)?;
    let mut result = BTreeMap::new();
    let mut ranks = std::collections::BTreeSet::new();
    for (id, raw) in object {
        canonical_id(id)?;
        let window: CiphertextMessageWindow = serde_json::from_value(raw.clone())?;
        if window.chat_id != *id {
            return Err(Error::Protocol);
        }
        if let Some(rank) = window.source_rank {
            if usize::from(rank) >= MAX_PARENTS || !ranks.insert(rank) {
                return Err(Error::Protocol);
            }
        }
        for digest in [
            &window.wrappers_sha256,
            &window.metadata_sha256,
            &window.owner_sha256,
            &window.scope_sha256,
            &window.key_ciphertext_sha256,
        ] {
            if digest.len() != 64 || !digest.bytes().all(|byte| byte.is_ascii_hexdigit()) {
                return Err(Error::Protocol);
            }
        }
        for cursor in [&window.start_cursor, &window.oversized_message_cursor]
            .into_iter()
            .flatten()
        {
            if !super::message_window::valid_message_id(&cursor.message_id) { return Err(Error::Protocol); }
            if cursor.created_at < 0 {
                return Err(Error::Protocol);
            }
        }
        viewport_record_bytes(&window)?;
        let rows = message_rows(&window.messages, id, MAX_NORMALIZED_BYTES)?;
        if rows != window.messages
            || rows.len() as u64 > window.server_message_count
            || window.start_cursor != rows.first().map(row_cursor).transpose()?
            || window.oversized_message != window.oversized_message_cursor.is_some()
            || (!window.has_more_before && window.server_message_count > rows.len() as u64)
        {
            return Err(Error::Protocol);
        }
        let latest_ids = rows
            .iter()
            .map(row_cursor)
            .collect::<Result<Vec<_>>>()?
            .into_iter()
            .map(|cursor| cursor.message_id)
            .collect::<std::collections::BTreeSet<_>>();
        for (message_id, row) in &window.retained_rows {
            if latest_ids.contains(message_id) {
                return Err(Error::Protocol);
            }
            if !super::message_window::valid_message_id(message_id) { return Err(Error::Protocol); }
            let normalized = message_rows(std::slice::from_ref(row), id, MAX_NORMALIZED_BYTES)?;
            if normalized.first() != Some(row) || row_cursor(row)?.message_id != *message_id {
                return Err(Error::Protocol);
            }
        }
        result.insert(id.clone(), window);
    }
    Ok(result)
}

#[cfg(test)]
#[path = "sync_windows_tests.rs"]
mod tests;

// Pending phase data can hold server metadata extensions; wipe even rejected
// parser/actor work. This grants no canonical window or output admission.
impl crate::client::plaintext::Wipe for Phase1Windows {
    fn wipe(&mut self){
        use crate::client::plaintext::Wipe;
        self.metadata.wipe();self.metadata_order.wipe();
        self.expanded_metadata.wipe();self.expanded_order.wipe();self.older_metadata_pages.wipe();
        for window in self.windows.values_mut(){window.messages.wipe();}
        self.windows.clear();self.order.wipe();self.selected.wipe();
    }
}

#[path="sync_windows_owned.rs"]
mod owned;
pub(in crate::client) use owned::{PreparedOwnedSyncWindows,CompletedOwnedSyncWindows};
#[cfg(test)]mod startup_transfer_budget_tests {
 use super::*;
 fn id(n:u32)->String{format!("{n:08x}-1111-4111-8111-111111111111")}
 // contract-test: supporting surface=sdks.rust assertions=sync.client.shared-rust-policy,sync.startup.bounded-phases
 #[test]fn final_metadata_transfer_removes_duplicates_without_changing_twenty_parent_heavy_content_limits(){
  let mut batch=Phase1Windows::default();
  // Retain12MiB of legitimate unknown metadata below the unchanged16MiB
  // navigation budget. Together with the independent heavy-content windows
  // below, the owned phase exceeds16MiB without oversizing either facet.
  let metadata=(1..=20).map(|n|json!({"id":id(n),"opaqueUserMetadata":{"unknown":"retained","payload":"M".repeat(12*1024*1024/MAX_PARENTS)}})).collect::<Vec<_>>();
  for row in &metadata {
   let frame=json!({"context_epoch":0,"team_id":null,"recent_chat_metadata":[row]});
   assert!(serde_json::to_vec(&frame).unwrap().len()<1024*1024);
   batch.metadata(&frame,None).unwrap();
  }
  let navigation=batch.retained_navigation_bytes(crate::client::transport::MAX_BODY).unwrap();
  assert!(navigation<crate::client::transport::MAX_BODY);
  for n in 1..=20 {
   let message=id(100+n);let mut row=json!({"id":message,"chat_id":id(n),"created_at":1,"role":"user","encrypted_content":""});
   // Exercise the exact existing256KiB raw-window limit, including JSON
   // framing, for every one of the20 independently bounded parent windows.
   let framing=serde_json::to_vec(&row).unwrap().len();
   row["encrypted_content"]=json!("A".repeat(MAX_WINDOW_BYTES-framing));
   assert_eq!(serde_json::to_vec(&row).unwrap().len(),MAX_WINDOW_BYTES);
   let payload=json!({"context_epoch":0,"team_id":null,"chats":[{"chat_id":id(n),"messages":[row],"server_message_count":1,"message_window":{"has_more_before":false,"start_cursor":{"created_at":1,"message_id":message},"oversized_message":false}}]});
   assert!(serde_json::to_vec(&payload).unwrap().len()<crate::client::transport::MAX_BODY);
   if n==1 {
    let mut oversized=payload.clone();let content=oversized["chats"][0]["messages"][0]["encrypted_content"].as_str().unwrap().to_owned()+"A";oversized["chats"][0]["messages"][0]["encrypted_content"]=json!(content);
    let mut rejected=Phase1Windows::default();assert!(matches!(rejected.content(&oversized,None),Err(Error::Protocol)));assert!(rejected.windows.is_empty());
   }
   batch.content(&payload,None).unwrap();
  }
  // Projection adds a52-byte message_id alias; the array adds two brackets.
  assert_eq!(batch.windows.len(),20);let content=batch.windows.values().map(|w|serde_json::to_vec(&w.messages).unwrap().len()).sum::<usize>();assert_eq!(content,MAX_PARENTS*(MAX_WINDOW_BYTES+54));assert!(navigation+content>crate::client::transport::MAX_BODY);
  assert!(matches!(batch.content(&json!({"context_epoch":0,"team_id":null,"chats":[{"chat_id":id(21),"messages":[],"server_message_count":0,"message_window":{"has_more_before":false,"start_cursor":null,"oversized_message":false}}]}),None),Err(Error::Protocol)));
  let retained_content=content;
  let mut chats=BTreeMap::new();let mut order=Vec::new();batch.take_metadata_ordered(&mut chats,&mut order).unwrap();
  assert!(batch.metadata.is_empty()&&batch.expanded_metadata.is_empty()&&batch.metadata_order.is_empty()&&batch.expanded_order.is_empty());assert_eq!(chats.len(),20);assert_eq!(batch.windows.len(),20);assert!(batch.retained_navigation_bytes(crate::client::transport::MAX_BODY).unwrap()<1024);
  assert_eq!(batch.windows.values().map(|window|serde_json::to_vec(&window.messages).unwrap().len()).sum::<usize>(),retained_content);
  assert_eq!(order,metadata.iter().map(|row|row["id"].as_str().unwrap().to_owned()).collect::<Vec<_>>());
  for row in metadata { assert_eq!(chats[row["id"].as_str().unwrap()],row); }
 }
}
