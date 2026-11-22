//! Applied-change card of a hosted Project sandbox commit (shared core, all shells).
//! The server's `embed_revision_committed` event (`source: project_sandbox`)
//! names only ids; this device checks the chat's Project focus, reads the
//! committed head with its own Project key and returns the change the shell
//! shows like a device-path write (web `recordProjectFileChange`). Spec:
//! `projects.files.write-policy-enforcement` (Apply and show changes).
use super::project_sandbox_key::KeyLookup;
use super::*;

/// Event `kind` values that leave a file with readable text.
const SHOWN_KINDS: [(&str, &str); 2] = [("create", "create_file"), ("update", "update_file")];

/// The ids of one sandbox commit event the core needs.
pub(super) struct SandboxCommitEvent<'e> {
    pub(super) embed_id: &'e str,
    pub(super) chat_id: &'e str,
    pub(super) project_id: &'e str,
    pub(super) operation_id: &'e str,
    /// Wire operation of the card (`create_file` / `update_file`).
    pub(super) operation: &'static str,
}

/// Parses the event; `None` for events that are not a shown sandbox file write
/// (another source, a delete or move, or missing ids).
pub(super) fn parse_event(event: &Value) -> Option<SandboxCommitEvent<'_>> {
    if event["source"] != "project_sandbox" {
        return None;
    }
    let text = |name: &str| event[name].as_str().filter(|v| !v.is_empty());
    let kind = text("kind")?;
    let operation = SHOWN_KINDS.iter().find(|(k, _)| *k == kind)?.1;
    Some(SandboxCommitEvent {
        embed_id: text("embed_id")?,
        chat_id: text("chat_id")?,
        project_id: text("project_id")?,
        operation_id: text("operation_id")?,
        operation,
    })
}

/// The `ProjectWriteApprovalRequest` shape the web change card takes. One
/// operation can write several files, so the card id adds the embed id.
pub(super) fn change_card(event: &SandboxCommitEvent<'_>, path: &str, content: &str) -> Value {
    json!({
        "projectId": event.project_id,
        "chatId": event.chat_id,
        "mutation": {
            "operation": event.operation,
            "operation_id": format!("{}:{}", event.operation_id, event.embed_id),
            "path": path,
            "expected_base": null,
            "content": content,
        },
    })
}

impl Client {
    /// The applied-change card for one `embed_revision_committed` payload of a
    /// sandbox write: `{projectId, chatId, mutation}` with the decrypted path
    /// and text. `None` when the event is not a sandbox create/update, the chat
    /// is not focused on that Project, this device lacks the Project key, or
    /// the file is no longer linked. The text stays in memory for the card.
    ///
    /// # Errors
    /// Cancellation, transport and decryption failures; the shell shows no card.
    pub async fn describe_project_sandbox_commit(
        &mut self,
        event: &Value,
    ) -> Result<Option<Value>> {
        let Some(commit) = parse_event(event) else {
            return Ok(None);
        };
        let (key, filters) = match self
            .project_key_for_chat(commit.chat_id, commit.project_id)
            .await?
        {
            (KeyLookup::Key(key), filters) => (key, filters),
            (KeyLookup::NoKey | KeyLookup::Invalid, _) => return Ok(None),
        };
        let change = self
            .projects()
            .with_filters(filters)
            .sandbox_change(commit.project_id, key, commit.embed_id)
            .await?;
        Ok(change.map(|change| change_card(&commit, &change.path, &change.content)))
    }
}

#[cfg(test)]
#[path = "project_sandbox_commit_tests.rs"]
mod tests;
