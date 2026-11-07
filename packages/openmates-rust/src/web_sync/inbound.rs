//! Inbound chat-update decisions of the web chat sync (mirrors the pure helpers
//! of `chatSyncServiceHandlersChatUpdates.ts`): whether a draft-only chat shell
//! must lose its draft because the first message version of the chat arrived
//! (`clearDraftOnlyShellForMessages`). The assistant notification preview lives
//! in `updates.rs`. Also the frame admission of `chat_title_updated` /
//! `chat_draft_updated` (`updateFrameInvalid`) and the stale/cleared-version
//! decision of the draft apply (`draftApply`).
//!
//! spec: specifications/architecture/sync#sync.client.shared-rust-policy
use serde_json::{json, Value};

use super::merge::draft_update_blocked;
use super::{field, nullish, num, parse, truthy, PROTOCOL};

/// `clearDraftOnlyShellForMessages`: whether the chat is a draft-only shell
/// (no messages yet, a draft present) that must lose its draft because
/// `messagesV > 0` arrived. Input `{messagesV, chat: {messages_v?, encrypted_draft_md?, encrypted_draft_preview?}}`;
/// output `{"clear": bool}`.
///
/// # Errors
/// `protocol` when `messagesV` is missing or the chat is not an object.
pub fn draft_shell_json(input: &str) -> Result<String, String> {
    let input = parse(input)?;
    let messages_v = field(&input, "messagesV").ok_or_else(|| PROTOCOL.to_string())?;
    let chat = field(&input, "chat")
        .filter(|c| c.is_object())
        .ok_or_else(|| PROTOCOL.to_string())?;
    let has_messages_v = !(num(Some(messages_v)) <= 0.0);
    let local_v = truthy(field(chat, "messages_v"))
        .then(|| num(field(chat, "messages_v")))
        .unwrap_or(0.0);
    let has_draft =
        truthy(field(chat, "encrypted_draft_md")) || truthy(field(chat, "encrypted_draft_preview"));
    Ok(json!({"clear": has_messages_v && local_v == 0.0 && has_draft}).to_string())
}

/// Admission of a `chat_title_updated` (`kind` `title`) or `chat_draft_updated`
/// (`kind` `draft`) frame, in the order of the handlers' checks. Input
/// `{kind, payload}` where `payload` is `null` or `{chat_id?, data?, versions?}`
/// (absent field = `undefined`); output `{"invalid": null | "chat_id" | "data" | "versions"}`.
///
/// # Errors
/// `protocol` when `kind` is not `title` or `draft`.
pub fn update_frame_json(input: &str) -> Result<String, String> {
    let input = parse(input)?;
    let (data_key, version_key) = match field(&input, "kind").and_then(Value::as_str) {
        Some("title") => ("encrypted_title", "title_v"),
        Some("draft") => ("encrypted_draft_md", "draft_v"),
        _ => return Err(PROTOCOL.to_string()),
    };
    let payload = field(&input, "payload").unwrap_or(&Value::Null);
    let defined = |container: &str, key: &str| {
        let value = field(payload, container);
        truthy(value) && value.is_some_and(|v| field(v, key).is_some())
    };
    let invalid = if !truthy(Some(payload)) || !truthy(field(payload, "chat_id")) {
        Some("chat_id")
    } else if !defined("data", data_key) {
        Some("data")
    } else if !defined("versions", version_key) {
        Some("versions")
    } else {
        None
    };
    Ok(json!({"invalid": invalid}).to_string())
}

/// `chat_draft_updated` against an existing local chat: whether the frame is
/// stale (`draft_v` ahead of it, or fenced by a local deletion) and, for a draft
/// deletion, the new `cleared_draft_v` (`Math.max(cleared ?? 0, draft_v ?? 0, incoming)`).
/// Input `{local: {draft_v?, cleared_draft_v?, encrypted_draft_md?, encrypted_draft_preview?},
/// incomingDraftV, deletion}`; output `{"stale": bool, "clearedDraftV": number | null}`.
///
/// # Errors
/// `protocol` when `local` is not an object or `incomingDraftV` is missing.
pub fn draft_apply_json(input: &str) -> Result<String, String> {
    let input = parse(input)?;
    let local = field(&input, "local")
        .filter(|c| c.is_object())
        .ok_or_else(|| PROTOCOL.to_string())?;
    let incoming = field(&input, "incomingDraftV").ok_or_else(|| PROTOCOL.to_string())?;
    let incoming_v = num(Some(incoming));
    let local_v = nullish(field(local, "draft_v")).map_or(0.0, |v| num(Some(v)));
    let stale = local_v > incoming_v || draft_update_blocked(local, incoming_v);
    let cleared = (!stale && truthy(field(&input, "deletion"))).then(|| {
        let cleared_v = nullish(field(local, "cleared_draft_v")).map_or(0.0, |v| num(Some(v)));
        [cleared_v, local_v, incoming_v]
            .into_iter()
            .fold(f64::NEG_INFINITY, |max, v| if max.is_nan() || v.is_nan() { f64::NAN } else { max.max(v) })
    });
    Ok(json!({"stale": stale, "clearedDraftV": cleared.map(super::number)}).to_string())
}

#[cfg(test)]
mod tests {
    use serde_json::Value;

    use super::*;

    fn vectors() -> Value {
        serde_json::from_str(include_str!("inbound_vectors.json"))
            .expect("committed vectors are valid JSON")
    }

    // contract-test: supporting surface=sdks.rust assertions=sync.client.shared-rust-policy
    #[test]
    fn draft_shell_matches_typescript_vectors() {
        for case in vectors()["draft"].as_array().unwrap() {
            let input = json!({"messagesV": case["messagesV"], "chat": case["chat"]});
            let out = parse(&draft_shell_json(&input.to_string()).unwrap()).unwrap();
            assert_eq!(out["clear"], case["clear"], "case {case}");
        }
    }

    // contract-test: supporting surface=sdks.rust assertions=sync.client.shared-rust-policy
    #[test]
    fn update_frame_matches_typescript_vectors() {
        for case in vectors()["frame"].as_array().unwrap() {
            let input = json!({"kind": case["kind"], "payload": case["payload"]});
            let out = parse(&update_frame_json(&input.to_string()).unwrap()).unwrap();
            assert_eq!(out["invalid"], case["invalid"], "case {case}");
        }
    }

    // contract-test: supporting surface=sdks.rust assertions=sync.client.shared-rust-policy
    #[test]
    fn draft_apply_matches_typescript_vectors() {
        for case in vectors()["apply"].as_array().unwrap() {
            let input = json!({"local": case["local"], "incomingDraftV": case["incomingDraftV"], "deletion": case["deletion"]});
            let out = parse(&draft_apply_json(&input.to_string()).unwrap()).unwrap();
            assert_eq!(out["stale"], case["stale"], "case {case}");
            assert_eq!(out["clearedDraftV"], case["clearedDraftV"], "case {case}");
        }
    }

    #[test]
    fn malformed_update_input_is_a_protocol_refusal() {
        assert_eq!(update_frame_json(r#"{"kind":"x"}"#), Err(PROTOCOL.to_string()));
        assert_eq!(draft_apply_json(r#"{"local":1,"incomingDraftV":1}"#), Err(PROTOCOL.to_string()));
        assert_eq!(draft_apply_json(r#"{"local":{}}"#), Err(PROTOCOL.to_string()));
    }

    #[test]
    fn malformed_input_is_a_protocol_refusal() {
        assert_eq!(
            draft_shell_json(r#"{"chat":{}}"#),
            Err(PROTOCOL.to_string())
        );
        assert_eq!(
            draft_shell_json(r#"{"messagesV":1,"chat":3}"#),
            Err(PROTOCOL.to_string())
        );
    }
}
