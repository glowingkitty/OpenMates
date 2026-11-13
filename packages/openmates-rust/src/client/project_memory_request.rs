//! Reads the active Project's Memory documents to answer a `memory-<id>` request.
//!
//! Shared core (CLI/TUI, web Worker, Apple). The server asks for a Project
//! Memory by its Project item id; the answer is decided from the stored
//! document's own load mode (see `memory_catalog::decide_memory_request`),
//! never from the server's claim. Only the chat's active Project focus is read.
use super::context::revision;
use super::memory_documents::PersonalMemoryDocument;
use super::plaintext::Plain;
use super::project_memories::{ProjectMemoryRow, is_project_memory_path, keep_project_memory};
use super::sync_capability::AsyncCryptoScope;
use super::*;

impl Client {
    /// Stored documents of the requested Project Memory item ids.
    ///
    /// Empty without an active Project focus. Rows are matched by
    /// `project_item_id`; focus and every row revision are re-checked after the
    /// reads, so a Project switch or edit mid-read answers nothing stale.
    ///
    /// # Errors
    /// Transport, decryption and scope errors; a chat or account switch
    /// returns [`Error::Cancelled`].
    pub(super) async fn project_memory_request_documents(
        &mut self,
        chat_id: &str,
        wanted: &[String],
    ) -> Result<Vec<PersonalMemoryDocument>> {
        self.require_canonical_read_profile()?;
        let scope = AsyncCryptoScope::begin(self)?;
        scope.check_chat(self, chat_id)?;
        let active = self.current_project_focus(&scope, chat_id).await?;
        if active.is_null() {
            return Ok(Vec::new());
        }
        let project = required(&active, "project_id")?.to_owned();
        if active.get("team_id").and_then(Value::as_str) != self.team()? {
            return Err(Error::Forbidden);
        }
        let detail_path = self.scoped(&format!("/v1/projects/{}", segment(&project)))?;
        let detail = self
            .context_request(&scope, Some(chat_id), Method::GET, &detail_path, None)
            .await?;
        let wrapping = self.wrapping_capability().await;
        scope.check_chat(self, chat_id)?;
        let key = self
            .object_key_with_capability(Workspace::Projects, &detail["project"], &wrapping?, &scope)
            .await?;
        scope.check_chat(self, chat_id)?;
        let rows = requested_rows(&detail, &key, wanted)?;
        let now = i64::try_from(now_ms()).unwrap_or(i64::MAX);
        let mut found: Vec<(PersonalMemoryDocument, String)> = Vec::new();
        for memory in &rows {
            let embed = zeroize::Zeroizing::new(crypto::decrypt_combined(
                required(&memory.row, "target_id_encrypted")?,
                &key,
            )?);
            scope.check_chat(self, chat_id)?;
            let read = self.read_project_document(&project, &embed, &key).await;
            scope.check_chat(self, chat_id)?;
            let content = Plain::new(read?);
            let Some(document) = ["content", "markdown", "text", "code"]
                .into_iter()
                .find_map(|k| content[k].as_str())
            else {
                continue;
            };
            if keep_project_memory(document, now) {
                found.push((
                    PersonalMemoryDocument {
                        id: memory.item_id.clone(),
                        document: zeroize::Zeroizing::new(document.to_owned()),
                    },
                    memory.revision.clone(),
                ));
            }
        }
        if found.is_empty() {
            return Ok(Vec::new());
        }
        if self.current_project_focus(&scope, chat_id).await? != active {
            return Err(Error::Cancelled);
        }
        let fresh = Plain::new(
            self.context_request(&scope, Some(chat_id), Method::GET, &detail_path, None)
                .await?,
        );
        let unchanged = |id: &str, rev: &str| {
            fresh["items"]
                .as_array()
                .into_iter()
                .flatten()
                .any(|row| text(row, "project_item_id") == id && revision(row) == rev)
        };
        scope.check_chat(self, chat_id)?;
        Ok(found
            .into_iter()
            .filter(|(document, rev)| unchanged(&document.id, rev))
            .map(|(document, _)| document)
            .collect())
    }
}

/// Project Memory files of the detail whose item id was requested.
fn requested_rows(
    detail: &Value,
    key: &[u8; 32],
    wanted: &[String],
) -> Result<Vec<ProjectMemoryRow>> {
    let mut rows = Vec::new();
    for row in detail["items"].as_array().ok_or(Error::Protocol)? {
        if !["embed", "upload"].contains(&text(row, "item_type"))
            || text(row, "encrypted_metadata").is_empty()
            || !row["deleted_target_state"].is_null()
            || !wanted.iter().any(|id| id == text(row, "project_item_id"))
        {
            continue;
        }
        let plaintext = zeroize::Zeroizing::new(crypto::decrypt_combined(
            required(row, "encrypted_metadata")?,
            key,
        )?);
        let metadata = Plain::new(serde_json::from_str::<Value>(&plaintext)?);
        let path = metadata
            .get("path")
            .or_else(|| metadata.get("display_path"))
            .and_then(Value::as_str)
            .unwrap_or("");
        if !is_project_memory_path(path) {
            continue;
        }
        rows.push(ProjectMemoryRow {
            item_id: required(row, "project_item_id")?.to_owned(),
            row: row.clone(),
            revision: revision(row),
            path: path.to_owned(),
        });
    }
    Ok(rows)
}
