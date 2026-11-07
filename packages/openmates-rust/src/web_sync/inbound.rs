//! Inbound chat-update decisions of the web chat sync (mirrors the pure helpers
//! of `chatSyncServiceHandlersChatUpdates.ts`): whether a draft-only chat shell
//! must lose its draft because the first message version of the chat arrived
//! (`clearDraftOnlyShellForMessages`). The assistant notification preview lives
//! in `updates.rs`.
//!
//! spec: specifications/architecture/sync#sync.client.shared-rust-policy
use serde_json::json;

use super::{field, num, parse, truthy, PROTOCOL};

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
