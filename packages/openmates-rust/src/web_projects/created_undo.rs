//! Undo guard for an assistant-created Project (Rust-only decision, no TS twin).
//!
//! spec: specifications/surfaces/sdk#sdk.client.thin-platform-boundary
//! The web shell reads the chat's active focus and the Project's decrypted
//! settings and sends them here; the core applies the same rule as
//! `Projects::undo_created` (the Project must be the chat's active-focus
//! Project and carry this chat's assistant creation record), so a Project the
//! assistant did not create for the chat is never deleted. The shell then
//! deactivates the focus and deletes the Project.

use super::{Outcome, throw};
use crate::work::is_creation_record;
use serde_json::{Value, json};

/// `projectUndoCreatedGuard`: `{undo: true}` or the `Forbidden` refusal.
///
/// Input: `chatId`, `projectId` (from the embed), `activeProjectId` (the chat's
/// active focus Project, or null) and `settings` (the decrypted Project settings).
pub(super) fn guard(input: &Value) -> Outcome {
    let chat_id = input["chatId"].as_str().unwrap_or_default();
    let project_id = input["projectId"].as_str().unwrap_or_default();
    let focused = input["activeProjectId"].as_str() == Some(project_id) && !project_id.is_empty();
    if focused && !chat_id.is_empty() && is_creation_record(&input["settings"]["creation"], chat_id)
    {
        Ok(json!({ "undo": true }))
    } else {
        Err(throw("Forbidden"))
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn input(active: Value, origin: &str, chat: &str) -> Value {
        json!({"chatId": "c1", "projectId": "p1", "activeProjectId": active,
            "settings": {"creation": {"origin": origin, "chat_id": chat}}})
    }

    #[test]
    fn allows_only_the_chats_own_assistant_created_focused_project() {
        assert_eq!(
            guard(&input(json!("p1"), "assistant_request", "c1")).unwrap(),
            json!({"undo": true})
        );
        for bad in [
            input(json!("p2"), "assistant_request", "c1"),
            input(Value::Null, "assistant_request", "c1"),
            input(json!("p1"), "manual", "c1"),
            input(json!("p1"), "assistant_request", "c2"),
        ] {
            assert!(matches!(guard(&bad), Err(super::super::Fault::Throw(m)) if m == "Forbidden"));
        }
    }
}
