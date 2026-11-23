//! Whether a server frame ends a retained user turn in the web outbox.
//!
//! The web shell resends every user row that still carries its sealed turn
//! preflight on each connect. Two server answers mean that turn must never be
//! resent: the "this turn already completed" confirmation (spec assertion
//! `chats.message.identity-idempotent`, matched exactly like the core's saved-turn
//! send in `client/send_finished_turn.rs`) and an `error` frame for exactly this
//! chat, user message and (when the frame names one) turn that says
//! `retryable: false` (for example a changed request for an immutable turn
//! binding). Anything else leaves the turn retained, so a transient or unrelated
//! failure keeps the ordinary retry.
use super::protocol;
use serde_json::{Value, json};

fn text<'a>(value: &'a Value, key: &str) -> &'a str {
    value.get(key).and_then(Value::as_str).unwrap_or("")
}

/// `"finished"`, `"rejected"` or `"none"` for one frame and one retained turn.
pub fn turn_outbox_outcome(kind: &str, payload: &Value, chat: &str, message: &str, turn: &str) -> &'static str {
    if crate::client::finished_turn_assistant_id(kind, payload, chat, message, turn).is_some() {
        return "finished";
    }
    if kind != "error" || payload.get("retryable") != Some(&Value::Bool(false)) || text(payload, "chat_id") != chat {
        return "none";
    }
    let named = [text(payload, "message_id"), text(payload, "user_message_id")];
    if !named.contains(&message) || named.iter().any(|id| !id.is_empty() && *id != message) {
        return "none";
    }
    let frame_turn = text(payload, "turn_id");
    if !frame_turn.is_empty() && frame_turn != turn {
        return "none";
    }
    "rejected"
}

/// `{kind, payload, chatId, messageId, turnId}` -> `{outcome}`.
///
/// # Errors
/// `protocol` for malformed JSON, a non-object payload or a missing identity.
pub fn turn_outbox_outcome_json(input: &str) -> Result<String, String> {
    let value: Value = serde_json::from_str(input).map_err(protocol)?;
    let field = |key: &str| value.get(key).and_then(Value::as_str).filter(|s| !s.is_empty()).ok_or("protocol");
    let (kind, chat, message, turn) = (field("kind")?, field("chatId")?, field("messageId")?, field("turnId")?);
    let payload = value.get("payload").filter(|p| p.is_object()).ok_or("protocol")?;
    Ok(json!({"outcome": turn_outbox_outcome(kind, payload, chat, message, turn)}).to_string())
}

#[cfg(test)]
mod tests {
    use super::*;

    fn outcome(kind: &str, payload: Value) -> String {
        let input = json!({"kind": kind, "payload": payload, "chatId": "c1", "messageId": "m1", "turnId": "t1"});
        let out: Value = serde_json::from_str(&turn_outbox_outcome_json(&input.to_string()).expect("valid")).expect("json");
        out["outcome"].as_str().expect("outcome").to_string()
    }

    #[test]
    fn non_retryable_rejection_of_this_turn_ends_it() {
        // Production frame of a resent turn whose immutable binding was rejected.
        let frame = json!({"code": "inference_temporarily_paused", "chat_id": "c1", "message_id": "m1",
            "user_message_id": "m1", "turn_id": "t1", "retryable": false,
            "message": "This turn is already processing or its request changed. Wait for the earlier result."});
        assert_eq!(outcome("error", frame), "rejected");
        // Servers that omit turn_id still name the exact message.
        assert_eq!(outcome("error", json!({"chat_id": "c1", "user_message_id": "m1", "retryable": false})), "rejected");
    }

    #[test]
    fn retryable_or_foreign_errors_keep_the_turn() {
        for frame in [
            json!({"chat_id": "c1", "message_id": "m1", "turn_id": "t1", "retryable": true}),
            json!({"chat_id": "c1", "message_id": "m1", "turn_id": "t1"}),
            json!({"chat_id": "c1", "message_id": "m1", "turn_id": "t1", "retryable": "false"}),
            json!({"chat_id": "c2", "message_id": "m1", "turn_id": "t1", "retryable": false}),
            json!({"chat_id": "c1", "message_id": "m2", "turn_id": "t1", "retryable": false}),
            json!({"chat_id": "c1", "message_id": "m1", "user_message_id": "m2", "retryable": false}),
            json!({"chat_id": "c1", "message_id": "m1", "turn_id": "t2", "retryable": false}),
            json!({"chat_id": "c1", "retryable": false}),
        ] {
            assert_eq!(outcome("error", frame.clone()), "none", "{frame}");
        }
        assert_eq!(outcome("chat_turn_preflight_ack", json!({"chat_id": "c1", "message_id": "m1", "retryable": false})), "none");
    }

    #[test]
    fn already_completed_confirmation_finishes_the_turn() {
        // committed version need not match the retained preflight's expected one.
        let frame = json!({"chat_id": "c1", "message_id": "m1", "turn_already_completed": true,
            "turn_id": "t1", "new_messages_v": 4});
        assert_eq!(outcome("chat_message_confirmed", frame), "finished");
        assert_eq!(outcome("chat_message_confirmed",
            json!({"chat_id": "c1", "message_id": "m1", "turn_already_completed": true})), "finished");
        assert_eq!(outcome("chat_message_confirmed",
            json!({"chat_id": "c1", "message_id": "m1", "new_messages_v": 4})), "none");
        assert_eq!(outcome("chat_message_confirmed",
            json!({"chat_id": "c1", "message_id": "m1", "turn_already_completed": true, "turn_id": "t2"})), "none");
    }

    #[test]
    fn malformed_input_is_a_protocol_error() {
        assert_eq!(turn_outbox_outcome_json("{").unwrap_err(), "protocol");
        assert_eq!(turn_outbox_outcome_json(&json!({"kind": "error", "payload": [], "chatId": "c1",
            "messageId": "m1", "turnId": "t1"}).to_string()).unwrap_err(), "protocol");
        assert_eq!(turn_outbox_outcome_json(&json!({"kind": "error", "payload": {}, "chatId": "c1",
            "messageId": "m1"}).to_string()).unwrap_err(), "protocol");
    }
}
