//! Phased-sync decisions of the web chat sync (mirrors `chatSyncPhasedRetry.ts`
//! and the pure helpers of `chatSyncServiceHandlersPhasedSync.ts`): retry and
//! backoff of `phased_sync_retryable_error`, key admission of synced chats,
//! the authoritative-deletion plan and metadata-only chat records.
//!
//! Invariant: a synced chat without any usable key wrapper is never stored
//! (it could not be decrypted and would shadow a later keyed copy), except the
//! key-optional shells the TS service admits (demo/legal, anonymous, master-key
//! draft-only).
use serde_json::{json, Map, Value};

use super::{field, nullish, num_or, number, or, parse, strict_eq, truthy, PROTOCOL};

/// Retries before the client stops and keeps cached chats (`PHASED_SYNC_RETRY_MAX_ATTEMPTS`).
pub const RETRY_MAX_ATTEMPTS: u64 = 5;
const DEFAULT_RETRY_AFTER_MS: f64 = 3_000.0;
const MAX_BACKOFF_MS: f64 = 30_000.0;

/// `computePhasedSyncRetryDelayMs`: the server hint (finite, positive) or 3 s,
/// doubled per attempt and capped at 30 s.
pub fn retry_delay_ms(attempt: f64, retry_after_ms: Option<&Value>) -> f64 {
    let base = retry_after_ms
        .and_then(Value::as_f64)
        .filter(|ms| ms.is_finite() && *ms > 0.0)
        .unwrap_or(DEFAULT_RETRY_AFTER_MS);
    (base * 2f64.powf((attempt - 1.0).max(0.0))).min(MAX_BACKOFF_MS)
}

/// Next step for one retryable-error frame: `ignore` (not retryable), `pending`
/// (a retry is already scheduled), `exhausted` (stop, keep cached chats) or
/// `schedule` with the new attempt number and delay. Every step but `ignore`
/// clears the phased-sync timeout.
///
/// Input: `{retryable, timerPending, attempt, retryAfterMs?}`.
///
/// # Errors
/// `protocol` when `timerPending`/`attempt` are missing or mistyped.
pub fn retry_json(input: &str) -> Result<String, String> {
    let input = parse(input)?;
    let timer_pending = field(&input, "timerPending")
        .and_then(Value::as_bool)
        .ok_or_else(|| PROTOCOL.to_string())?;
    let attempt = field(&input, "attempt")
        .and_then(Value::as_u64)
        .ok_or_else(|| PROTOCOL.to_string())?;
    // `payload.retryable !== true`: only the boolean true retries.
    if field(&input, "retryable") != Some(&Value::Bool(true)) {
        return Ok(json!({"kind": "ignore"}).to_string());
    }
    if timer_pending {
        return Ok(json!({"kind": "pending"}).to_string());
    }
    if attempt >= RETRY_MAX_ATTEMPTS {
        return Ok(json!({"kind": "exhausted", "maxAttempts": RETRY_MAX_ATTEMPTS}).to_string());
    }
    let next = attempt + 1;
    let delay = retry_delay_ms(next as f64, field(&input, "retryAfterMs"));
    Ok(json!({"kind": "schedule", "attempt": next, "delayMs": number(delay), "maxAttempts": RETRY_MAX_ATTEMPTS}).to_string())
}

/// `isKeyOptionalSyncedChat`: chats that may be stored without a chat key.
pub fn key_optional(chat_id: &str, chat: &Value, local: Option<&Value>) -> bool {
    let c = |k: &str| field(chat, k);
    let messages_zero = |v: Option<&Value>| strict_eq(v, Some(&json!(0)));
    let draft_only = truthy(c("encrypted_draft_md"))
        && c("encrypted_draft_md").and_then(Value::as_str) != Some("null")
        && num_or(c("draft_v"), 0.0) > 0.0
        && messages_zero(c("messages_v"))
        && !truthy(c("encrypted_title"))
        && local.is_none_or(|l| {
            messages_zero(field(l, "messages_v")) && !truthy(field(l, "encrypted_title"))
        });
    chat_id.starts_with("demo-")
        || chat_id.starts_with("legal-")
        || truthy(c("is_anonymous"))
        || truthy(c("anonymous_encrypted_chat_key"))
        || draft_only
}

/// `shouldSkipSyncedChatWithoutKey`: true when no key wrapper can decrypt the chat.
pub fn skip_without_key(chat_id: &str, server: &Value, local: Option<&Value>) -> bool {
    let l = |k: &str| local.and_then(|l| field(l, k));
    !(truthy(field(server, "encrypted_chat_key"))
        || truthy(l("encrypted_chat_key"))
        || truthy(l("anonymous_encrypted_chat_key"))
        || truthy(l("is_anonymous"))
        || key_optional(chat_id, server, local))
}

fn chat_input(input: &Value) -> Result<(&str, &Value, Option<&Value>), String> {
    let chat_id = field(input, "chatId")
        .and_then(Value::as_str)
        .ok_or_else(|| PROTOCOL.to_string())?;
    let server = field(input, "server")
        .filter(|v| v.is_object())
        .ok_or_else(|| PROTOCOL.to_string())?;
    let local = match field(input, "local") {
        None | Some(Value::Null) => None,
        Some(local @ Value::Object(_)) => Some(local),
        Some(_) => return Err(PROTOCOL.to_string()),
    };
    Ok((chat_id, server, local))
}

/// Key admission of one synced chat: `{skip}` for `{chatId, server, local}`.
///
/// # Errors
/// `protocol` when the input is not that shape.
pub fn admission_json(input: &str) -> Result<String, String> {
    let input = parse(input)?;
    let (chat_id, server, local) = chat_input(&input)?;
    Ok(json!({"skip": skip_without_key(chat_id, server, local)}).to_string())
}

/// `buildMetadataOnlyChatFromDetails` (absent keys are `undefined` for the adapter).
pub fn metadata_only_chat(
    details: &Value,
    existing: Option<&Value>,
    now: f64,
) -> Map<String, Value> {
    let d = |k: &str| field(details, k);
    let e = |k: &str| existing.and_then(|x| field(x, k));
    let now = number(now);
    let or_null = |v: Option<&Value>| or(v).cloned().unwrap_or(Value::Null);
    let mut out = Map::new();
    let mut put = |key: &str, value: Option<Value>| {
        if let Some(value) = value {
            out.insert(key.to_string(), value);
        }
    };
    put("chat_id", d("id").cloned());
    put("encrypted_title", Some(or_null(d("encrypted_title"))));
    put("title", Some(Value::Null));
    put(
        "messages_v",
        Some(or(d("messages_v")).cloned().unwrap_or(json!(0))),
    );
    put(
        "title_v",
        Some(or(d("title_v")).cloned().unwrap_or(json!(0))),
    );
    put("metadata_v", d("metadata_v").cloned());
    put("draft_v", Some(json!(0)));
    put("encrypted_draft_md", Some(Value::Null));
    put("encrypted_draft_preview", Some(Value::Null));
    for key in [
        "ideabucket",
        "ideabucket_processing_window_id",
        "ideabucket_triggered_at",
    ] {
        put(key, d(key).cloned());
    }
    let edited = or(d("last_edited_overall_timestamp"))
        .or(or(d("updated_at")))
        .cloned()
        .unwrap_or(now.clone());
    put("last_edited_overall_timestamp", Some(edited));
    put(
        "unread_count",
        Some(or(d("unread_count")).cloned().unwrap_or(json!(0))),
    );
    put(
        "created_at",
        Some(or(d("created_at")).cloned().unwrap_or(now.clone())),
    );
    put(
        "updated_at",
        Some(or(d("updated_at")).cloned().unwrap_or(now)),
    );
    put("processing_metadata", Some(json!(false)));
    put("waiting_for_metadata", Some(json!(false)));
    put("encrypted_category", Some(or_null(d("encrypted_category"))));
    put("encrypted_icon", Some(or_null(d("encrypted_icon"))));
    put(
        "encrypted_chat_key",
        Some(
            or(d("encrypted_chat_key"))
                .or(or(e("encrypted_chat_key")))
                .cloned()
                .unwrap_or(Value::Null),
        ),
    );
    for key in ["chat_visibility", "participant_user_hashes"] {
        put(
            key,
            Some(
                nullish(d(key))
                    .or(nullish(e(key)))
                    .cloned()
                    .unwrap_or(Value::Null),
            ),
        );
    }
    put(
        "anonymous_encrypted_chat_key",
        Some(
            or(d("anonymous_encrypted_chat_key"))
                .or(or(e("anonymous_encrypted_chat_key")))
                .cloned()
                .unwrap_or(Value::Null),
        ),
    );
    for key in [
        "encrypted_chat_summary",
        "encrypted_share_cta_text",
        "encrypted_chat_tags",
        "encrypted_follow_up_request_suggestions",
        "encrypted_suggested_followup_message",
        "encrypted_active_focus_id",
        "encrypted_focus_phase_state",
        "encrypted_auto_speak_response",
    ] {
        put(key, Some(or_null(d(key))));
    }
    put(
        "pinned",
        Some(or(d("pinned")).cloned().unwrap_or(json!(false))),
    );
    put(
        "is_shared",
        Some(nullish(d("is_shared")).cloned().unwrap_or(json!(false))),
    );
    put(
        "is_private",
        Some(nullish(d("is_private")).cloned().unwrap_or(json!(false))),
    );
    put(
        "is_anonymous",
        Some(
            nullish(d("is_anonymous"))
                .or(nullish(e("is_anonymous")))
                .cloned()
                .unwrap_or(json!(false)),
        ),
    );
    put(
        "share_pii",
        Some(nullish(d("share_pii")).cloned().unwrap_or(json!(false))),
    );
    put(
        "share_highlights",
        Some(
            nullish(d("share_highlights"))
                .cloned()
                .unwrap_or(json!(true)),
        ),
    );
    put("is_metadata_only", Some(json!(true)));
    out
}

/// Load-more/metadata-sync record for `{chatId, server, local, now}`:
/// `{kind:'skip'}` (no usable key) or `{kind:'chat', chat}`.
///
/// # Errors
/// `protocol` when the input is not that shape.
pub fn metadata_chat_json(input: &str) -> Result<String, String> {
    let input = parse(input)?;
    let (chat_id, server, local) = chat_input(&input)?;
    let now = field(&input, "now")
        .and_then(Value::as_f64)
        .ok_or_else(|| PROTOCOL.to_string())?;
    if skip_without_key(chat_id, server, local) {
        return Ok(json!({"kind": "skip"}).to_string());
    }
    Ok(json!({"kind": "chat", "chat": metadata_only_chat(server, local, now)}).to_string())
}

/// `applyAuthoritativeDeletedChats` plan for `{deleted?, explicit?}`: the unique
/// truthy ids in order, each marked explicit (tombstone) or inferred (absence,
/// which must not erase a chat with a pending turn). An absent `explicit` list
/// is a legacy server: every id is explicit; `null` means none is.
///
/// # Errors
/// `protocol` when a present list is not an array.
pub fn deletion_plan_json(input: &str) -> Result<String, String> {
    let input = parse(input)?;
    let list = |key: &str| -> Result<Option<Vec<Value>>, String> {
        match field(&input, key) {
            None => Ok(None),
            Some(Value::Null) => Ok(Some(Vec::new())),
            Some(Value::Array(items)) => Ok(Some(items.clone())),
            Some(_) => Err(PROTOCOL.to_string()),
        }
    };
    let deleted = list("deleted")?.unwrap_or_default();
    let explicit = list("explicit")?;
    let mut unique: Vec<Value> = Vec::new();
    for id in deleted {
        if !unique.iter().any(|u| strict_eq(Some(u), Some(&id))) {
            unique.push(id);
        }
    }
    let plan: Vec<Value> = unique
        .into_iter()
        .filter(|id| truthy(Some(id)))
        .map(|id| {
            let is_explicit = explicit
                .as_ref()
                .is_none_or(|ids| ids.iter().any(|e| strict_eq(Some(e), Some(&id))));
            json!({"chatId": id, "explicit": is_explicit})
        })
        .collect();
    Ok(Value::Array(plan).to_string())
}
