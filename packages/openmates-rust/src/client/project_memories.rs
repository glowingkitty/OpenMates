//! Project Memories for one send in a chat with an active Project focus.
//!
//! Shared core (CLI/TUI, web Worker, Apple). Mirrors the web
//! `listProjectRuleDocuments` + `collectCustomRuleDocuments`
//! (`frontend/packages/ui/src/services/ruleDocumentService.ts`): every Markdown
//! file in `.openmates/memories/` (and the legacy `.openmates/rules/`) is sent
//! in full as a `custom_memory_documents` row with `source: "project"`.
//! Implements `feature.app-memories` Project Memories and `feature.projects`
//! Project focus context.
use super::memory_document_fields::{is_memory_expired, parse_memory_document};
use super::plaintext::Plain;
use super::sync_capability::AsyncCryptoScope;
use super::*;

/// At most this many Project Memories per send (web `collectCustomRuleDocuments`).
pub(super) const MAX_PROJECT_MEMORIES: usize = 24;
/// Character budget of all Project Memory bodies in one send.
pub(super) const MAX_PROJECT_MEMORY_CHARS: usize = 64_000;
/// A single Project Memory larger than this is not sent (same as a personal one).
pub(super) const MAX_PROJECT_MEMORY_DOCUMENT_CHARS: usize = 24_000;

/// One Project Memory file found in the Project detail, before its body is read.
pub(super) struct ProjectMemoryRow {
    /// `project_item_id`, the id the server checks against the Project.
    pub(super) item_id: String,
    /// The Project item row (holds `target_id_encrypted`).
    pub(super) row: Value,
    /// Revision of the row (same hash as every Project context document).
    pub(super) revision: String,
    /// Display path, used only for the deterministic order.
    pub(super) path: String,
}

impl Drop for ProjectMemoryRow {
    fn drop(&mut self) {
        crate::model::zeroize_json(&mut self.row);
    }
}

/// True for `.openmates/memories/<name>.md` and `.openmates/rules/<name>.md`
/// with a plain file name (web regex `^\.openmates\/(?:memories|rules)\/[a-zA-Z0-9_-]+\.md$`).
pub(super) fn is_project_memory_path(path: &str) -> bool {
    let Some(rest) = path
        .strip_prefix(".openmates/memories/")
        .or_else(|| path.strip_prefix(".openmates/rules/"))
    else {
        return false;
    };
    let Some(name) = rest.strip_suffix(".md") else {
        return false;
    };
    !name.is_empty()
        && name
            .bytes()
            .all(|c| c.is_ascii_alphanumeric() || c == b'_' || c == b'-')
}

/// Whether a read Project Memory body is sent: it must parse as a Memory
/// document, fit the per-document limit and not be past its `valid_until`.
/// Unreadable documents are skipped one by one (the web drops the whole
/// collection instead); either way the send itself continues.
pub(super) fn keep_project_memory(document: &str, now_ms: i64) -> bool {
    if document.len() > MAX_PROJECT_MEMORY_DOCUMENT_CHARS {
        return false;
    }
    match parse_memory_document(document) {
        Ok(fields) => !is_memory_expired(&fields, now_ms),
        Err(_) => false,
    }
}

impl Client {
    /// Read the bodies of the active Project's Memory files for this send.
    ///
    /// Rows are read in path order until 24 documents or 64,000 characters.
    /// The caller has already checked that `project_id` is the chat's active
    /// Project focus and re-checks it (and every row revision) after this
    /// returns, so a Project switch mid-read sends nothing stale.
    ///
    /// # Errors
    /// Transport, decryption and scope errors; a chat or account switch
    /// returns [`Error::Cancelled`] through the scope check.
    pub(super) async fn project_memory_documents(
        &mut self,
        scope: &AsyncCryptoScope,
        chat_id: &str,
        project_id: &str,
        mut rows: Vec<ProjectMemoryRow>,
        key: &[u8; 32],
    ) -> Result<Vec<Value>> {
        rows.sort_by(|a, b| a.path.cmp(&b.path));
        let now = i64::try_from(now_ms()).unwrap_or(i64::MAX);
        let mut out = Plain::new(Vec::new());
        let mut chars = 0usize;
        for memory in rows.iter() {
            if out.len() >= MAX_PROJECT_MEMORIES {
                break;
            }
            let embed = zeroize::Zeroizing::new(crypto::decrypt_combined(
                required(&memory.row, "target_id_encrypted")?,
                key,
            )?);
            scope.check_chat(self, chat_id)?;
            let read = self.read_project_document(project_id, &embed, key).await;
            scope.check_chat(self, chat_id)?;
            let content = Plain::new(read?);
            let Some(document) = ["content", "markdown", "text", "code"]
                .into_iter()
                .find_map(|k| content[k].as_str())
            else {
                continue;
            };
            if !keep_project_memory(document, now) || chars + document.len() > MAX_PROJECT_MEMORY_CHARS {
                continue;
            }
            chars += document.len();
            out.push(json!({"id":memory.item_id,"source":"project","project_id":project_id,"document":document,"item_revision":memory.revision}));
        }
        Ok(out.into_inner())
    }
}

#[cfg(all(test, not(target_arch = "wasm32")))]
#[path = "project_memories_tests.rs"]
mod tests;
