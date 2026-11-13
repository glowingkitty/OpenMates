//! Server/local chat record merge of the web phased sync (mirrors
//! `chatSyncMerge.ts`: `hasEncryptedChatKeyMismatch` decision part,
//! `isDraftUpdateBlockedByLocalDeletion`, `mergeServerChatWithLocal`).
//!
//! Invariant: a merged record never pairs one `encrypted_chat_key` with
//! ciphertext preserved from a different key. When the keys differ the local
//! key and ciphertext win, the server key becomes a recovery candidate and
//! `messages_v` drops to 0 so content is re-fetched under the right key.
use serde_json::{Map, Value, json};

use super::{field, nullish, num, num_or, number, or, parse, strict_eq, truthy};

/// Bounded recovery-candidate list kept per chat (`MAX_CANDIDATE_KEYS`).
const MAX_CANDIDATE_KEYS: usize = 5;

/// How the page must settle whether the server and local chat keys differ.
#[derive(Debug, PartialEq, Eq)]
pub enum KeyMismatchPlan {
    /// Decided from fingerprints/wrappers alone.
    Decided(bool),
    /// Unwrap both Team/direct wrappers and compare the raw keys (an unwrap failure is a mismatch).
    CompareDirect,
    /// Unwrap both master-key wrappers and compare the raw keys (a failed unwrap is a mismatch).
    CompareMaster,
}

impl KeyMismatchPlan {
    fn to_json(&self) -> Value {
        match self {
            Self::Decided(mismatch) => json!({"kind": "decided", "mismatch": mismatch}),
            Self::CompareDirect => json!({"kind": "direct"}),
            Self::CompareMaster => json!({"kind": "master"}),
        }
    }
}

fn starts_with(value: Option<&Value>, prefix: &str) -> bool {
    value
        .and_then(Value::as_str)
        .is_some_and(|s| s.starts_with(prefix))
}

/// Decision part of `hasEncryptedChatKeyMismatch`: fingerprints win, equal or
/// missing wrappers never mismatch, direct/Team wrappers need a matching Team.
pub fn key_mismatch_plan(server: &Value, local: Option<&Value>) -> KeyMismatchPlan {
    let local_field = |key: &str| local.and_then(|l| field(l, key));
    if truthy(field(server, "key_fingerprint")) && truthy(local_field("key_fingerprint")) {
        return KeyMismatchPlan::Decided(!strict_eq(
            field(server, "key_fingerprint"),
            local_field("key_fingerprint"),
        ));
    }
    let server_key = field(server, "encrypted_chat_key");
    let local_key = local_field("encrypted_chat_key");
    if !truthy(server_key) || !truthy(local_key) || strict_eq(server_key, local_key) {
        return KeyMismatchPlan::Decided(false);
    }
    let direct = |v: Option<&Value>| v.and_then(Value::as_str) == Some("direct");
    if direct(field(server, "chat_visibility"))
        || direct(local_field("chat_visibility"))
        || starts_with(server_key, "OMDM1.")
        || starts_with(local_key, "OMDM1.")
    {
        let (server_team, local_team) = (field(server, "team_id"), local_field("team_id"));
        if !truthy(server_team) || !truthy(local_team) || !strict_eq(server_team, local_team) {
            return KeyMismatchPlan::Decided(true);
        }
        return KeyMismatchPlan::CompareDirect;
    }
    KeyMismatchPlan::CompareMaster
}

/// `isDraftUpdateBlockedByLocalDeletion`: a local draft deletion fences every
/// incoming draft at or below the cleared version.
pub fn draft_update_blocked(local: &Value, incoming_draft_v: f64) -> bool {
    let draft_zero = match nullish(field(local, "draft_v")) {
        None => true,
        Some(Value::Number(n)) => n.as_f64() == Some(0.0),
        Some(_) => false,
    };
    let cleared = num_or(field(local, "cleared_draft_v"), 0.0);
    draft_zero
        && !truthy(field(local, "encrypted_draft_md"))
        && !truthy(field(local, "encrypted_draft_preview"))
        && cleared > 0.0
        && cleared >= incoming_draft_v
}

/// The server record plus the own keys whose value is `undefined` (JSON drops them).
struct Server<'a> {
    chat: &'a Value,
    undefined_keys: Vec<&'a str>,
}

impl<'a> Server<'a> {
    fn get(&self, key: &str) -> Option<&'a Value> {
        field(self.chat, key)
    }
    /// `Object.prototype.hasOwnProperty.call(serverChat, key)`.
    fn has(&self, key: &str) -> bool {
        self.chat.as_object().is_some_and(|o| o.contains_key(key))
            || self.undefined_keys.contains(&key)
    }
}

/// Record under construction: `None` is `undefined` (the adapter restores the key).
struct Out(Map<String, Value>);

impl Out {
    fn set(&mut self, key: &str, value: Option<Value>) {
        match value {
            Some(v) => {
                self.0.insert(key.to_string(), v);
            }
            None => {
                self.0.remove(key);
            }
        }
    }
}

fn first<'a>(values: &[Option<&'a Value>]) -> Option<&'a Value> {
    values.iter().copied().find_map(nullish)
}

/// `a ?? b ?? …` without a literal fallback: the first non-nullish operand, else
/// the last operand as it is (so a stored `null` stays `null`, absent stays absent).
fn coalesce<'a>(values: &[Option<&'a Value>]) -> Option<&'a Value> {
    first(values).or_else(|| values.last().copied().flatten())
}

fn cloned(value: Option<&Value>) -> Option<Value> {
    value.cloned()
}

/// `newestTimestamp`: max of the present (non-nullish) timestamps.
fn newest(values: &[Option<&Value>]) -> Option<f64> {
    values
        .iter()
        .copied()
        .filter_map(nullish)
        .map(|v| num(Some(v)))
        .reduce(js_max)
}

/// `Math.max` for two numbers (NaN is contagious).
fn js_max(a: f64, b: f64) -> f64 {
    if a.is_nan() || b.is_nan() {
        f64::NAN
    } else {
        a.max(b)
    }
}

/// Fields that only pass through (`server.x` for a new chat).
const NEW_CHAT_PASSTHROUGH: &[&str] = &[
    "message_window_has_more_before",
    "message_window_start_cursor",
    "embed_window_has_more_before",
    "embed_window_start_cursor",
    "metadata_v",
    "encrypted_draft_md",
    "encrypted_draft_preview",
    "ideabucket",
    "ideabucket_processing_window_id",
    "ideabucket_triggered_at",
    "encrypted_chat_key",
    "anonymous_encrypted_chat_key",
    "candidate_encrypted_keys",
    "encrypted_icon",
    "encrypted_category",
    "last_visible_message_id",
    "pinned",
    "encrypted_follow_up_request_suggestions",
    "encrypted_suggested_followup_message",
    "encrypted_chat_summary",
    "encrypted_share_cta_text",
    "encrypted_shared_short_url",
    "encrypted_chat_tags",
    "encrypted_top_recommended_apps_for_chat",
    "encrypted_recommendations",
    "encrypted_active_focus_id",
    "encrypted_focus_phase_state",
    "encrypted_auto_speak_response",
    "is_shared",
    "is_private",
    "is_anonymous",
    "share_pii",
    "share_highlights",
];

/// `server.x ?? local.x` fields of an existing chat.
const SERVER_FIRST: &[&str] = &[
    "message_window_has_more_before",
    "message_window_start_cursor",
    "embed_window_has_more_before",
    "embed_window_start_cursor",
    "metadata_v",
    "ideabucket",
    "ideabucket_processing_window_id",
    "ideabucket_triggered_at",
    "anonymous_encrypted_chat_key",
    "candidate_encrypted_keys",
    "last_visible_message_id",
    "pinned",
    "is_shared",
    "is_private",
    "is_anonymous",
    "share_pii",
    "share_highlights",
];

/// Encrypted fields that keep the local ciphertext when the chat keys differ.
const KEY_BOUND: &[&str] = &[
    "encrypted_chat_key",
    "encrypted_icon",
    "encrypted_category",
    "encrypted_follow_up_request_suggestions",
    "encrypted_suggested_followup_message",
    "encrypted_chat_summary",
    "encrypted_share_cta_text",
    "encrypted_shared_short_url",
    "encrypted_chat_tags",
    "encrypted_top_recommended_apps_for_chat",
    "encrypted_recommendations",
    "encrypted_focus_phase_state",
    "encrypted_active_focus_id",
    "encrypted_auto_speak_response",
];

fn new_chat(server: &Server, now: f64, current_user_id: Option<&Value>) -> Map<String, Value> {
    let s = |k: &str| server.get(k);
    let mut out = Out(Map::new());
    out.set("chat_id", cloned(s("id")));
    for (key, fallback) in [
        ("team_id", Value::Null),
        ("chat_visibility", Value::Null),
        ("participant_user_hashes", Value::Null),
        ("encrypted_title", Value::Null),
        ("messages_v", json!(0)),
        ("title_v", json!(0)),
        ("draft_v", json!(0)),
        ("unread_count", json!(0)),
        ("created_at", number(now)),
        ("updated_at", number(now)),
        ("parent_id", Value::Null),
        ("is_sub_chat", json!(false)),
        ("budget_limit", Value::Null),
        ("budget_spent", json!(0)),
    ] {
        out.set(key, Some(nullish(s(key)).cloned().unwrap_or(fallback)));
    }
    out.set(
        "last_edited_overall_timestamp",
        Some(
            first(&[s("last_edited_overall_timestamp"), s("updated_at")])
                .cloned()
                .unwrap_or(number(now)),
        ),
    );
    for key in NEW_CHAT_PASSTHROUGH {
        out.set(key, cloned(s(key)));
    }
    out.set("user_id", cloned(current_user_id));
    out.0
}

fn merge_candidate_keys(lists: &[Option<&Value>]) -> Option<Vec<Value>> {
    let mut merged: Vec<Value> = Vec::new();
    for keys in lists.iter().copied().filter_map(nullish) {
        for key in keys.as_array().into_iter().flatten() {
            if !merged.iter().any(|m| strict_eq(Some(m), Some(key))) {
                merged.push(key.clone());
            }
        }
    }
    (!merged.is_empty()).then(|| tail(merged))
}

fn tail(mut keys: Vec<Value>) -> Vec<Value> {
    let skip = keys.len().saturating_sub(MAX_CANDIDATE_KEYS);
    keys.drain(..skip);
    keys
}

fn append_candidate_key(
    existing: Option<Vec<Value>>,
    encrypted_key: Option<&Value>,
) -> Option<Vec<Value>> {
    let Some(key) = encrypted_key.filter(|k| truthy(Some(k))) else {
        return existing;
    };
    let mut candidates = existing.unwrap_or_default();
    if candidates.iter().any(|c| strict_eq(Some(c), Some(key))) {
        return Some(candidates);
    }
    candidates.push(key.clone());
    Some(tail(candidates))
}

/// `mergeServerChatWithLocal` for an existing local chat with the settled key decision.
fn merge_existing(
    server: &Server,
    local: &Value,
    key_mismatch: bool,
    now: f64,
    current_user_id: Option<&Value>,
) -> Map<String, Value> {
    let s = |k: &str| server.get(k);
    let l = |k: &str| field(local, k);
    let local_draft_version = nullish(l("draft_v")).cloned().unwrap_or(json!(0));
    let server_draft_version = js_max(num_or(s("draft_v"), 0.0), num_or(s("cleared_draft_v"), 0.0));
    let server_draft_current = server_draft_version >= num(Some(&local_draft_version));
    let server_deletes_draft = s("encrypted_draft_md") == Some(&Value::Null)
        || s("encrypted_draft_preview") == Some(&Value::Null)
        || (server.has("draft_v")
            && num_or(s("messages_v"), 0.0) > 0.0
            && strict_eq(s("draft_v"), Some(&json!(0))));
    let draft_only_shell = num_or(s("messages_v"), 0.0) > 0.0
        && num_or(l("messages_v"), 0.0) == 0.0
        && (truthy(l("encrypted_draft_md")) || truthy(l("encrypted_draft_preview")));
    let fence = draft_update_blocked(local, num_or(s("draft_v"), 0.0));
    let pending_team_draft = if strict_eq(s("team_id"), l("team_id")) && !key_mismatch {
        l("team_draft_pending_sync")
    } else {
        None
    };
    let pending = truthy(pending_team_draft);
    let clears = (!pending && fence)
        || (server_draft_current && !pending && (server_deletes_draft || draft_only_shell));

    let mut out = Out(Map::new());
    out.set("chat_id", cloned(s("id")));
    for key in ["team_id", "chat_visibility", "participant_user_hashes"] {
        out.set(
            key,
            Some(first(&[s(key), l(key)]).cloned().unwrap_or(Value::Null)),
        );
    }
    let team_commit = truthy(s("team_id")) && num_or(s("messages_v"), 0.0) > 0.0;
    out.set(
        "team_chat_pending_commit",
        if team_commit {
            Some(json!(false))
        } else {
            cloned(l("team_chat_pending_commit"))
        },
    );
    out.set("team_draft_pending_sync", cloned(or(pending_team_draft)));
    out.set(
        "user_id",
        cloned(first(&[l("user_id")]).or(current_user_id)),
    );
    let title = if key_mismatch {
        first(&[l("encrypted_title")])
    } else {
        first(&[s("encrypted_title"), l("encrypted_title")])
    };
    out.set(
        "encrypted_title",
        Some(title.cloned().unwrap_or(Value::Null)),
    );
    out.set(
        "messages_v",
        Some(
            first(&[s("messages_v"), l("messages_v")])
                .cloned()
                .unwrap_or(json!(0)),
        ),
    );
    out.set(
        "title_v",
        Some(
            first(&[s("title_v"), l("title_v")])
                .cloned()
                .unwrap_or(json!(0)),
        ),
    );
    for key in SERVER_FIRST {
        out.set(key, cloned(coalesce(&[s(key), l(key)])));
    }
    let draft_v = if pending {
        local_draft_version.clone()
    } else if clears {
        json!(0)
    } else if server_draft_current {
        nullish(s("draft_v"))
            .cloned()
            .unwrap_or(local_draft_version.clone())
    } else {
        local_draft_version.clone()
    };
    out.set("draft_v", Some(draft_v));
    let cleared = if pending {
        cloned(l("cleared_draft_v"))
    } else if clears {
        Some(number(js_max(
            js_max(num_or(l("cleared_draft_v"), 0.0), num_or(l("draft_v"), 0.0)),
            num_or(s("cleared_draft_v"), 0.0),
        )))
    } else {
        cloned(l("cleared_draft_v"))
    };
    out.set("cleared_draft_v", cleared);
    out.set(
        "unread_count",
        Some(
            first(&[s("unread_count"), l("unread_count")])
                .cloned()
                .unwrap_or(json!(0)),
        ),
    );
    for key in ["created_at", "updated_at"] {
        out.set(
            key,
            Some(first(&[s(key), l(key)]).cloned().unwrap_or(number(now))),
        );
    }
    let edited = newest(&[
        s("last_edited_overall_timestamp"),
        l("last_edited_overall_timestamp"),
    ])
    .or_else(|| newest(&[s("updated_at"), l("updated_at")]))
    .or_else(|| newest(&[s("created_at"), l("created_at")]))
    .unwrap_or(now);
    out.set("last_edited_overall_timestamp", Some(number(edited)));
    for key in ["encrypted_draft_md", "encrypted_draft_preview"] {
        let value = if pending {
            cloned(l(key))
        } else if clears {
            None
        } else if server.has(key) && server_draft_current {
            cloned(nullish(s(key)))
        } else if key_mismatch {
            None
        } else {
            cloned(l(key))
        };
        out.set(key, value);
    }
    for key in KEY_BOUND {
        out.set(
            key,
            if key_mismatch {
                cloned(l(key))
            } else {
                cloned(coalesce(&[s(key), l(key)]))
            },
        );
    }
    out.set(
        "parent_id",
        Some(
            first(&[s("parent_id"), l("parent_id")])
                .cloned()
                .unwrap_or(Value::Null),
        ),
    );
    out.set(
        "is_sub_chat",
        Some(
            first(&[s("is_sub_chat"), l("is_sub_chat")])
                .cloned()
                .unwrap_or(json!(false)),
        ),
    );
    out.set(
        "budget_limit",
        Some(
            first(&[s("budget_limit"), l("budget_limit")])
                .cloned()
                .unwrap_or(Value::Null),
        ),
    );
    out.set(
        "budget_spent",
        Some(
            first(&[s("budget_spent"), l("budget_spent")])
                .cloned()
                .unwrap_or(json!(0)),
        ),
    );

    if key_mismatch {
        let candidates = append_candidate_key(
            merge_candidate_keys(&[l("candidate_encrypted_keys"), s("candidate_encrypted_keys")]),
            s("encrypted_chat_key"),
        );
        out.set("candidate_encrypted_keys", candidates.map(Value::Array));
        out.set("messages_v", Some(json!(0)));
        out.set("metadata_v", cloned(l("metadata_v")));
        return out.0;
    }

    merge_metadata(server, local, &mut out);

    let local_draft_v = num(Some(or(l("draft_v")).unwrap_or(&json!(0))));
    let server_draft_v = num(Some(or(s("draft_v")).unwrap_or(&json!(0))));
    if !clears && local_draft_v >= server_draft_v {
        for key in ["encrypted_draft_md", "encrypted_draft_preview"] {
            if truthy(l(key)) {
                out.set(key, cloned(l(key)));
            }
        }
        out.set("draft_v", cloned(l("draft_v")));
    }
    let local_messages_v = num(Some(or(l("messages_v")).unwrap_or(&json!(0))));
    let server_messages_v = num(Some(or(s("messages_v")).unwrap_or(&json!(0))));
    if local_messages_v > server_messages_v {
        out.set("messages_v", cloned(l("messages_v")));
    }
    out.0
}

/// Title/summary revision choice (metadata_v first, title_v for legacy records).
fn merge_metadata(server: &Server, local: &Value, out: &mut Out) {
    let s = |k: &str| server.get(k);
    let l = |k: &str| field(local, k);
    let zero = json!(0);
    let local_title_v = or(l("title_v")).unwrap_or(&zero);
    let server_title_v = or(s("title_v")).unwrap_or(&zero);
    let has_metadata_version =
        num_or(l("metadata_v"), 0.0) > 0.0 || num_or(s("metadata_v"), 0.0) > 0.0;
    let local_metadata_v = num(Some(or(l("metadata_v")).unwrap_or(local_title_v)));
    let server_metadata_v = num(Some(or(s("metadata_v")).unwrap_or(server_title_v)));
    let has_title = server.has("encrypted_title");
    let has_summary = server.has("encrypted_chat_summary");
    let carries_revision = num_or(s("metadata_v"), 0.0) > 0.0;
    if has_metadata_version
        && carries_revision
        && server_metadata_v >= local_metadata_v
        && (has_title || has_summary)
    {
        let title = if has_title {
            nullish(s("encrypted_title"))
        } else {
            nullish(l("encrypted_title"))
        };
        out.set(
            "encrypted_title",
            Some(title.cloned().unwrap_or(Value::Null)),
        );
        out.set(
            "encrypted_chat_summary",
            cloned(if has_summary {
                s("encrypted_chat_summary")
            } else {
                l("encrypted_chat_summary")
            }),
        );
        out.set("title_v", cloned(coalesce(&[s("title_v"), l("title_v")])));
        out.set("metadata_v", cloned(s("metadata_v")));
    } else if local_metadata_v >= server_metadata_v {
        out.set(
            "encrypted_title",
            cloned(coalesce(&[l("encrypted_title"), s("encrypted_title")])),
        );
        out.set(
            "encrypted_chat_summary",
            cloned(coalesce(&[
                l("encrypted_chat_summary"),
                s("encrypted_chat_summary"),
            ])),
        );
        out.set("title_v", cloned(l("title_v")));
        out.set("metadata_v", cloned(l("metadata_v")));
    } else if has_metadata_version {
        out.set(
            "encrypted_title",
            Some(
                nullish(s("encrypted_title"))
                    .cloned()
                    .unwrap_or(Value::Null),
            ),
        );
        out.set(
            "encrypted_chat_summary",
            cloned(s("encrypted_chat_summary")),
        );
        out.set(
            "title_v",
            Some(nullish(s("title_v")).cloned().unwrap_or(json!(0))),
        );
        out.set("metadata_v", cloned(s("metadata_v")));
    } else if num(Some(local_title_v)) >= num(Some(server_title_v)) && truthy(l("encrypted_title"))
    {
        out.set("encrypted_title", cloned(l("encrypted_title")));
        out.set(
            "encrypted_chat_summary",
            cloned(coalesce(&[
                l("encrypted_chat_summary"),
                s("encrypted_chat_summary"),
            ])),
        );
        out.set("title_v", cloned(l("title_v")));
    }
}

/// `{kind:'merged', chat}` or, when the key decision needs unwrapping, `{kind:'compareKeys', plan}`.
///
/// Input: `{server, serverUndefined, local, keyMismatch, now, currentUserId?}` where
/// `serverUndefined` lists the server's own keys whose value is `undefined` and
/// `keyMismatch` is `null` until the page settled a `direct`/`master` plan.
///
/// # Errors
/// `protocol` when the input is not that shape.
pub fn merge_json(input: &str) -> Result<String, String> {
    let input = parse(input)?;
    let chat = field(&input, "server")
        .filter(|v| v.is_object())
        .ok_or_else(|| super::PROTOCOL.to_string())?;
    let undefined_keys = field(&input, "serverUndefined")
        .and_then(Value::as_array)
        .ok_or_else(|| super::PROTOCOL.to_string())?
        .iter()
        .map(|v| v.as_str().ok_or_else(|| super::PROTOCOL.to_string()))
        .collect::<Result<Vec<_>, _>>()?;
    let now = field(&input, "now")
        .and_then(Value::as_f64)
        .ok_or_else(|| super::PROTOCOL.to_string())?;
    let server = Server {
        chat,
        undefined_keys,
    };
    let user = field(&input, "currentUserId");
    let local = field(&input, "local").filter(|v| !v.is_null());
    if local.is_some_and(|l| !l.is_object()) {
        return Err(super::PROTOCOL.to_string());
    }
    let Some(local) = local else {
        return Ok(json!({"kind": "merged", "chat": new_chat(&server, now, user)}).to_string());
    };
    let settled = field(&input, "keyMismatch");
    if settled.is_some_and(|v| !v.is_null() && !v.is_boolean()) {
        return Err(super::PROTOCOL.to_string());
    }
    let mismatch = match (settled, key_mismatch_plan(chat, Some(local))) {
        (_, KeyMismatchPlan::Decided(mismatch)) => mismatch,
        (Some(Value::Bool(settled)), _) => *settled,
        (Some(Value::Null) | None, plan) => {
            return Ok(json!({"kind": "compareKeys", "plan": plan.to_json()}).to_string());
        }
        _ => return Err(super::PROTOCOL.to_string()),
    };
    Ok(
        json!({"kind": "merged", "chat": merge_existing(&server, local, mismatch, now, user)})
            .to_string(),
    )
}

/// `hasEncryptedChatKeyMismatch` decision for `{server, local}` as `{kind:'decided',mismatch}|{kind:'direct'}|{kind:'master'}`.
///
/// # Errors
/// `protocol` when the input is not that shape.
pub fn key_mismatch_json(input: &str) -> Result<String, String> {
    let input = parse(input)?;
    let server = field(&input, "server")
        .filter(|v| v.is_object())
        .ok_or_else(|| super::PROTOCOL.to_string())?;
    let local = field(&input, "local").filter(|v| v.is_object());
    Ok(key_mismatch_plan(server, local).to_json().to_string())
}
