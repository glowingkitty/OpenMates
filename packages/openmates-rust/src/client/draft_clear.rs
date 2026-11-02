//! Personal draft tombstones are independent of saved-chat deletion and keys.
use super::transport::{send, wait};
use super::*;

impl Client {
    /// Clear an explicit Personal chat's draft using its versioned tombstone.
    /// Saved metadata and history are preserved, including uncached chats;
    /// Team/direct draft clearing requires a future explicitly scoped flow.
    pub async fn clear_draft(&mut self, chat_id: &str) -> Result<()> {
        self.require_session()?;
        let cancel = self.operation_cancel.clone();
        let generation = self.generation;
        let session_id = self.require_session()?.session_id.clone();
        if cancel.is_cancelled() {
            return Err(Error::Cancelled);
        }
        if self.team()?.is_some() {
            return Err(Error::Unavailable {
                code: "team_draft_clear_unavailable",
                reason: "Team draft clearing requires an explicitly scoped native flow.",
            });
        }
        uuid::Uuid::parse_str(chat_id).map_err(|_| Error::Invalid("Invalid chat ID."))?;
        if self.is_ephemeral_chat(chat_id) {
            return Err(Error::Invalid("Volatile chats do not have saved drafts."));
        }
        let row = self.chats.get(chat_id).cloned();
        let previous_owner = clear_owner(&self.user).map(str::to_owned);
        if let Some(row) = &row {
            validate_clear_scope(row, chat_id, previous_owner.as_deref())?;
        }
        let old_version = match row.as_ref().and_then(|row| row.get("draft_v")) {
            None | Some(Value::Null) => 0,
            Some(value) => value.as_u64().ok_or(Error::Protocol)?,
        };
        let remove_shell = self.cached_draft_shell(chat_id)?;
        let mut ws = self.socket_with_task_jobs(false).await?;
        let owner = clear_owner(&self.user).ok_or(Error::Protocol)?.to_owned();
        self.draft_clear_current(generation, &session_id, previous_owner.as_deref(), &cancel)?;
        if let Some(row) = &row {
            validate_clear_scope(row, chat_id, Some(&owner))?;
        }
        send(&mut ws, "delete_draft", json!({"chat_id":chat_id})).await?;
        // Complete the receipt turn without cancellation dropping an admitted
        // mutation. Cancellation still fences every local cache publication.
        let receipt = wait(&mut ws, "draft_delete_receipt", "chat_id", chat_id).await;
        let _ = ws.close(None).await;
        let receipt = receipt?;
        self.draft_clear_current(generation, &session_id, Some(&owner), &cancel)?;
        if receipt["success"] != true {
            return Err(Error::Protocol);
        }
        if ["team_id", "hashed_team_id"].iter().any(|field| {
            receipt
                .get(*field)
                .is_some_and(|team| !team.is_null() && team != "")
        }) {
            return Err(Error::Forbidden);
        }
        let version = receipt["draft_v"]
            .as_u64()
            .filter(|version| *version > 0)
            .ok_or(Error::Protocol)?;
        if version <= old_version || receipt["superseded"] == true {
            return Err(Error::Conflict);
        }
        if self.chats.get(chat_id) != row.as_ref() {
            return Err(Error::Conflict);
        }
        if let Some(row) = &row {
            validate_clear_scope(row, chat_id, Some(&owner))?;
        }
        if remove_shell {
            self.remove_chat_row(chat_id);
            self.history.remove(chat_id);
            self.selected_first_pages.remove(chat_id);
            if self.active_chat.as_deref() == Some(chat_id) {
                self.active_chat = None;
            }
        } else if let Some(row) = self.chats.get_mut(chat_id) {
            let fields = row.as_object_mut().ok_or(Error::Protocol)?;
            fields.remove("encrypted_draft_md");
            fields.remove("encrypted_draft_preview");
            fields.insert("draft_v".into(), json!(version));
        }
        Ok(())
    }

    fn draft_clear_current(
        &self,
        generation: u64,
        session_id: &str,
        owner: Option<&str>,
        cancel: &CancellationToken,
    ) -> Result<()> {
        if cancel.is_cancelled()
            || self.generation != generation
            || self.require_session()?.session_id != session_id
            || self.team()?.is_some()
            || owner.is_some_and(|owner| clear_owner(&self.user) != Some(owner))
        {
            return Err(Error::Cancelled);
        }
        Ok(())
    }

    pub(super) fn cached_draft_shell(&self, id: &str) -> Result<bool> {
        let Some(row) = self.chats.get(id) else {
            return Ok(false);
        };
        if !super::sync::draft_only(row) {
            return Ok(false);
        }
        if text(row, "id") != id {
            return Err(Error::Forbidden);
        }
        for field in ["encrypted_chat_key", "encrypted_draft_md"] {
            if row
                .get(field)
                .is_some_and(|value| !value.is_null() && !value.is_string())
            {
                return Err(Error::Protocol);
            }
        }
        let messages = match row.get("messages_v") {
            None | Some(Value::Null) => 0,
            Some(value) => value.as_u64().ok_or(Error::Protocol)?,
        };
        Ok(messages == 0
            && self.history.get(id).is_none_or(Vec::is_empty)
            && !self
                .wrappers
                .iter()
                .chain(row["chat_key_wrappers"].as_array().into_iter().flatten())
                .any(|wrapper| text(wrapper, "hashed_chat_id") == sha256(id)))
    }
}

fn clear_owner(user: &Value) -> Option<&str> {
    user["id"]
        .as_str()
        .filter(|owner| !owner.is_empty())
        .or_else(|| user["user_id"].as_str().filter(|owner| !owner.is_empty()))
}
fn validate_clear_scope(row: &Value, id: &str, owner: Option<&str>) -> Result<()> {
    if !row.is_object() || row["id"] != id {
        return Err(Error::Forbidden);
    }
    for field in ["team_id", "hashed_team_id"] {
        if row
            .get(field)
            .is_some_and(|value| !value.is_null() && value != "")
        {
            return Err(Error::Forbidden);
        }
    }
    if row
        .get("chat_visibility")
        .is_some_and(|value| !value.is_null() && value != "" && value != "personal")
    {
        return Err(Error::Forbidden);
    }
    for field in ["user_id", "owner_id", "hashed_user_id"] {
        if let Some(value) = row
            .get(field)
            .filter(|value| !value.is_null() && *value != "")
        {
            let value = value.as_str().ok_or(Error::Forbidden)?;
            if let Some(owner) = owner
                && value
                    != if field == "hashed_user_id" {
                        sha256(owner)
                    } else {
                        owner.to_owned()
                    }
            {
                return Err(Error::Forbidden);
            }
        }
    }
    Ok(())
}

#[cfg(test)]
#[path = "draft_clear_tests.rs"]
mod tests;
