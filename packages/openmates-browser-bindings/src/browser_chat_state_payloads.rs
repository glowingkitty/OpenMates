//! Stateless chat-state exports: highlights, chat management frames, forks
//! and Project placement plans. JSON in, JSON out; chat keys are raw 32-byte
//! arrays the web client already holds (ChatKeyManager).
use super::{chat_key, error_code};
use openmates_sdk::chat_state::{fork, highlights, management, projects};
use serde_json::{Value, json};
use wasm_bindgen::prelude::*;

fn frame_json(frame_type: &str, payload: &Value) -> String {
    json!({"type": frame_type, "payload": payload}).to_string()
}

fn highlight_write_json(write: &highlights::HighlightWrite) -> String {
    let record = write
        .record
        .as_ref()
        .map(|r| serde_json::to_value(r).expect("highlight serialization is infallible"));
    json!({"type": write.frame_type, "payload": write.payload, "record": record}).to_string()
}

fn inbound_json(inbound: highlights::HighlightInbound) -> String {
    match inbound {
        highlights::HighlightInbound::Store(record) => json!({"store": *record}).to_string(),
        highlights::HighlightInbound::Drop(reason) => {
            let reason = match reason {
                highlights::HighlightDrop::Undecryptable => "undecryptable",
                highlights::HighlightDrop::MissingAnchor => "missing_anchor",
                highlights::HighlightDrop::MissingEmbed => "missing_embed",
                highlights::HighlightDrop::UnknownKind => "unknown_kind",
            };
            json!({"drop": reason}).to_string()
        }
    }
}

/// `add_message_highlight` frame + optimistic row: `{type, payload, record}`.
#[wasm_bindgen]
pub fn chat_state_highlight_add(
    record_json: &str,
    chat_key_bytes: &[u8],
) -> Result<String, JsValue> {
    let record = highlights::HighlightRecord::parse(record_json).map_err(error_code)?;
    let write =
        highlights::add_highlight(&record, &*chat_key(chat_key_bytes)?).map_err(error_code)?;
    Ok(highlight_write_json(&write))
}

#[wasm_bindgen]
pub fn chat_state_highlight_update(
    record_json: &str,
    chat_key_bytes: &[u8],
    now_seconds: f64,
) -> Result<String, JsValue> {
    let record = highlights::HighlightRecord::parse(record_json).map_err(error_code)?;
    let write =
        highlights::update_highlight(&record, &*chat_key(chat_key_bytes)?, now_seconds as u64)
            .map_err(error_code)?;
    Ok(highlight_write_json(&write))
}

#[wasm_bindgen]
pub fn chat_state_highlight_remove(chat_id: &str, message_id: &str, id: &str) -> String {
    highlight_write_json(&highlights::remove_highlight(chat_id, message_id, id))
}

/// Inbound `message_highlight_added`: `{store: row}` or `{drop: reason}`.
#[wasm_bindgen]
pub fn chat_state_highlight_decode_added(
    payload_json: &str,
    chat_key_bytes: &[u8],
) -> Result<String, JsValue> {
    Ok(inbound_json(
        highlights::decode_added(payload_json, &*chat_key(chat_key_bytes)?).map_err(error_code)?,
    ))
}

#[wasm_bindgen]
pub fn chat_state_highlight_decode_updated(
    payload_json: &str,
    chat_key_bytes: &[u8],
    cached_json: Option<String>,
) -> Result<String, JsValue> {
    let cached = cached_json
        .as_deref()
        .map(highlights::HighlightRecord::parse)
        .transpose()
        .map_err(error_code)?;
    let inbound =
        highlights::decode_updated(payload_json, &*chat_key(chat_key_bytes)?, cached.as_ref())
            .map_err(error_code)?;
    Ok(inbound_json(inbound))
}

/// `{type, payload, encryptedTitle, titleV, updatedAt}`.
#[wasm_bindgen]
pub fn chat_state_update_title(
    chat_id: &str,
    title: &str,
    chat_key_bytes: &[u8],
    encrypted_chat_key: Option<String>,
    title_v: Option<f64>,
    now_seconds: f64,
) -> Result<String, JsValue> {
    let update = management::update_title(
        chat_id,
        title,
        &*chat_key(chat_key_bytes)?,
        encrypted_chat_key.as_deref(),
        title_v.map(|v| v as u64),
        now_seconds as u64,
    )
    .map_err(error_code)?;
    Ok(json!({"type": update.frame.frame_type, "payload": update.frame.payload, "encryptedTitle": update.encrypted_title,
        "titleV": update.title_v, "updatedAt": update.updated_at})
    .to_string())
}

/// `{type, payload, encryptedChatSummary, metadataV, updatedAt}`. `versions_json`
/// is `{messages_v, title_v, metadata_v, draft_v}` (any may be absent).
#[wasm_bindgen]
pub fn chat_state_update_summary(
    chat_id: &str,
    summary: &str,
    chat_key_bytes: &[u8],
    encrypted_chat_key: &str,
    encrypted_title: Option<String>,
    versions_json: &str,
    now_seconds: f64,
) -> Result<String, JsValue> {
    let versions: Value =
        serde_json::from_str(versions_json).map_err(|_| JsValue::from_str("protocol"))?;
    let field = |name: &str| {
        versions
            .get(name)
            .and_then(Value::as_f64)
            .filter(|v| *v > 0.0)
            .map(|v| v as u64)
    };
    let versions = management::ComponentVersions {
        messages_v: field("messages_v"),
        title_v: field("title_v"),
        metadata_v: field("metadata_v"),
        draft_v: field("draft_v"),
    };
    let update = management::update_summary(
        chat_id,
        summary,
        &*chat_key(chat_key_bytes)?,
        encrypted_chat_key,
        encrypted_title.as_deref(),
        versions,
        now_seconds as u64,
    )
    .map_err(error_code)?;
    Ok(json!({"type": update.frame.frame_type, "payload": update.frame.payload,
        "encryptedChatSummary": update.encrypted_chat_summary, "metadataV": update.metadata_v, "updatedAt": update.updated_at})
    .to_string())
}

#[wasm_bindgen]
pub fn chat_state_pin_frame(chat_id: &str, pinned: bool) -> String {
    let frame = management::pin_frame(chat_id, pinned);
    frame_json(frame.frame_type, &frame.payload)
}

#[wasm_bindgen]
pub fn chat_state_delete_chat_frame(
    chat_id: &str,
    remove_project_embeds: bool,
    embed_ids_to_delete: Vec<String>,
) -> String {
    let frame = management::delete_chat_frame(chat_id, remove_project_embeds, &embed_ids_to_delete);
    frame_json(frame.frame_type, &frame.payload)
}

#[wasm_bindgen]
pub fn chat_state_delete_message_frame(
    chat_id: &str,
    message_id: &str,
    embed_ids_to_delete: Vec<String>,
) -> String {
    let frame = management::delete_message_frame(chat_id, message_id, &embed_ids_to_delete);
    frame_json(frame.frame_type, &frame.payload)
}

/// Protected project embed count needing a decision, or `undefined`.
#[wasm_bindgen]
pub fn chat_state_deletion_decision(precheck_json: &str) -> Result<Option<u32>, JsValue> {
    Ok(management::deletion_decision(precheck_json)
        .map_err(error_code)?
        .map(|n| n as u32))
}

/// `{skip: true}` or `{skip: false, persistLastOpened, type, payload}`.
#[wasm_bindgen]
pub fn chat_state_active_chat_plan(
    chat_id: Option<String>,
    authenticated: bool,
    is_public_chat: bool,
) -> String {
    match management::active_chat_plan(chat_id.as_deref(), authenticated, is_public_chat) {
        management::ActiveChatPlan::Skip => json!({"skip": true}).to_string(),
        management::ActiveChatPlan::Send { persist_last_opened, frame } => {
            json!({"skip": false, "persistLastOpened": persist_last_opened, "type": frame.frame_type, "payload": frame.payload}).to_string()
        }
    }
}

/// Updated `hidden_demo_chats`, or `undefined` when already hidden.
#[wasm_bindgen]
pub fn chat_state_hide_demo_chat(current: Vec<String>, chat_id: &str) -> Option<Vec<String>> {
    management::hide_demo_chat(&current, chat_id)
}

/// Pending-deletion queue edit: `{write: string|null, changed}` where a null
/// write removes the storage key.
#[wasm_bindgen]
pub fn chat_state_pending_deletions_edit(
    stored: Option<String>,
    chat_id: &str,
    add: bool,
) -> String {
    let mut queue = management::PendingDeletions::decode(stored.as_deref());
    if add {
        let write = queue.add(chat_id);
        json!({"changed": write.is_some(), "write": write}).to_string()
    } else {
        json!({"changed": true, "write": queue.remove(chat_id)}).to_string()
    }
}

#[wasm_bindgen]
pub fn chat_state_pending_deletion_ids(stored: Option<String>) -> Vec<String> {
    management::PendingDeletions::decode(stored.as_deref()).chat_ids()
}

fn parse_sources(messages_json: &str) -> Result<Vec<fork::ForkSourceMessage>, JsValue> {
    serde_json::from_str(messages_json).map_err(|_| JsValue::from_str("protocol"))
}

/// Ids of the messages to copy, in fork order (stable `created_at` sort,
/// sliced at the fork point).
#[wasm_bindgen]
pub fn chat_state_fork_select(
    messages_json: &str,
    up_to_message_id: &str,
) -> Result<Vec<String>, JsValue> {
    let selected = fork::messages_to_copy(parse_sources(messages_json)?, up_to_message_id)
        .map_err(error_code)?;
    Ok(selected.into_iter().map(|m| m.message_id).collect())
}

/// Re-encrypt one batch for the new chat: JSON array of message rows.
#[wasm_bindgen]
pub fn chat_state_fork_reencrypt_batch(
    messages_json: &str,
    new_chat_id: &str,
    chat_key_bytes: &[u8],
) -> Result<String, JsValue> {
    let rows = fork::reencrypt_batch(
        &parse_sources(messages_json)?,
        new_chat_id,
        &*chat_key(chat_key_bytes)?,
    )
    .map_err(error_code)?;
    serde_json::to_string(&rows).map_err(|_| JsValue::from_str("protocol"))
}

/// Category/icon copy; `undefined` when skipped.
#[wasm_bindgen]
pub fn chat_state_fork_copy_field(
    source_ciphertext: Option<String>,
    source_key: &[u8],
    new_key: &[u8],
) -> Result<Option<String>, JsValue> {
    fork::copy_chat_field(
        source_ciphertext.as_deref(),
        &*chat_key(source_key)?,
        &*chat_key(new_key)?,
    )
    .map_err(error_code)
}

#[wasm_bindgen]
pub fn chat_state_fork_encrypt_title(
    title: &str,
    chat_key_bytes: &[u8],
) -> Result<String, JsValue> {
    fork::encrypt_fork_title(title, &*chat_key(chat_key_bytes)?).map_err(error_code)
}

/// `{record, payload}`: the new chat row and the `encrypted_chat_metadata`
/// payload. `chat_json` = `{chat_id, encrypted_chat_key, encrypted_title,
/// encrypted_category?, encrypted_icon?, user_id?, message_count, now_seconds}`.
#[wasm_bindgen]
pub fn chat_state_fork_finalize(chat_json: &str, rows_json: &str) -> Result<String, JsValue> {
    let chat: Value = serde_json::from_str(chat_json).map_err(|_| JsValue::from_str("protocol"))?;
    let rows: Vec<Value> =
        serde_json::from_str(rows_json).map_err(|_| JsValue::from_str("protocol"))?;
    let text = |name: &str| chat.get(name).and_then(Value::as_str);
    let required = |name: &str| text(name).ok_or_else(|| JsValue::from_str("protocol"));
    let messages = rows.iter().map(fork_row).collect::<Result<Vec<_>, _>>()?;
    let summary = fork::ForkChat {
        chat_id: required("chat_id")?,
        encrypted_chat_key: required("encrypted_chat_key")?,
        encrypted_title: required("encrypted_title")?,
        encrypted_category: text("encrypted_category"),
        encrypted_icon: text("encrypted_icon"),
        user_id: text("user_id"),
        message_count: chat
            .get("message_count")
            .and_then(Value::as_u64)
            .ok_or_else(|| JsValue::from_str("protocol"))? as usize,
        now_seconds: chat
            .get("now_seconds")
            .and_then(Value::as_u64)
            .ok_or_else(|| JsValue::from_str("protocol"))?,
    };
    Ok(json!({"record": fork::fork_chat_record(&summary), "payload": fork::fork_metadata_payload(&summary, &messages)}).to_string())
}

fn fork_row(row: &Value) -> Result<fork::ForkMessage, JsValue> {
    let text = |name: &str| row.get(name).and_then(Value::as_str).map(str::to_owned);
    Ok(fork::ForkMessage {
        message_id: text("message_id").ok_or_else(|| JsValue::from_str("protocol"))?,
        chat_id: text("chat_id").unwrap_or_default(),
        role: row.get("role").cloned().unwrap_or(Value::Null),
        created_at: match row.get("created_at") {
            Some(Value::Number(n)) => Some(n.clone()),
            _ => None,
        },
        status: "synced",
        encrypted_content: text("encrypted_content"),
        encrypted_sender_name: text("encrypted_sender_name"),
        encrypted_category: text("encrypted_category"),
        encrypted_model_name: text("encrypted_model_name"),
    })
}

#[wasm_bindgen]
pub fn chat_state_normalize_explain_selection(selected: &str) -> String {
    fork::normalize_explain_selection(selected)
}

/// Ordered project calls: `[{op: move_item|add_chat|remove_from_project, ...}]`.
#[wasm_bindgen]
pub fn chat_state_plan_placement(
    index_json: &str,
    project_id: &str,
    folder_id: Option<String>,
    chat_ids: Vec<String>,
    move_mode: bool,
) -> Result<String, JsValue> {
    let index: Vec<projects::SidebarProject> =
        serde_json::from_str(index_json).map_err(|_| JsValue::from_str("protocol"))?;
    let mode = if move_mode {
        projects::PlacementMode::Move
    } else {
        projects::PlacementMode::Add
    };
    let ops = projects::plan_placement(&index, project_id, folder_id.as_deref(), &chat_ids, mode)
        .map_err(error_code)?;
    let ops: Vec<Value> = ops
        .into_iter()
        .map(|op| match op {
            projects::PlacementOp::MoveItem { item_id, chat_id } => {
                json!({"op": "move_item", "itemId": item_id, "chatId": chat_id})
            }
            projects::PlacementOp::AddChat { chat_id } => {
                json!({"op": "add_chat", "chatId": chat_id})
            }
            projects::PlacementOp::RemoveFromProject {
                project_id,
                chat_id,
            } => {
                json!({"op": "remove_from_project", "projectId": project_id, "chatId": chat_id})
            }
        })
        .collect();
    Ok(Value::from(ops).to_string())
}

/// `chats_json` = `[{chat_id, is_incognito, is_shared_by_others, is_static, team_id}]`.
#[wasm_bindgen]
pub fn chat_state_assert_organizable(
    chats_json: &str,
    active_team_id: Option<String>,
) -> Result<(), JsValue> {
    let chats: Vec<projects::OrganizableChat> =
        serde_json::from_str(chats_json).map_err(|_| JsValue::from_str("protocol"))?;
    projects::assert_organizable(&chats, active_team_id.as_deref()).map_err(error_code)
}

#[wasm_bindgen]
pub fn chat_state_project_naming_titles(titles: Vec<String>) -> Vec<String> {
    projects::naming_titles(&titles)
}

#[wasm_bindgen]
pub fn chat_state_validate_project_name(proposed: Option<String>) -> Result<String, JsValue> {
    projects::validate_project_name(proposed.as_deref()).map_err(error_code)
}
