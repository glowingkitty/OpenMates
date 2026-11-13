//! Personal Memory catalog of a send and the local answer to server Memory
//! requests, in the shared core (every shell; headers are read without a YAML
//! library by `memory_document_fields`).
//!
//! Mirrors `frontend/packages/ui/src/utils/memoryCatalog.ts` (`buildMemoryCatalog`),
//! `services/memoryDocumentRequest.ts` (`decideMemoryRequest`, `memory-<id>` keys)
//! and the header fields of `utils/ruleDocuments.ts` (`parseRuleDocument`,
//! `isMemoryActive`). Spec: `features.app-memories` (`app-memories.load-modes`).
pub(super) use super::memory_document_fields::MemoryLoadMode;
use super::memory_document_fields::{iso_millis, parse_memory_document};
use super::memory_documents::{
    MAX_CATALOG_CHARS, MAX_DOCUMENTS, MemoryDocumentError, MemoryResult, PersonalMemoryDocument,
    decode_memory_documents,
};
use crate::chat_state::js::utf16_len;
use serde::Serialize;
use serde_json::{Value, json};
use std::collections::BTreeSet;
use std::fmt;
use zeroize::Zeroizing;

/// Prefix of a requested Memory key (`memory-<id>`, client hyphen format of the
/// server's `memory:<id>`). Ids may contain hyphens; only this prefix is cut.
pub(super) const MEMORY_REQUEST_KEY_PREFIX: &str = "memory-";
/// `app_id` of a Memory document in `app_settings_memories_confirmed` entries
/// (`item_key` is the Memory id) and in response categories.
pub(super) const MEMORY_RESPONSE_APP_ID: &str = "memory";

/// Header fields the catalog and the request answer need. Title and
/// when-to-use are trimmed exactly like the web parser, so the server's
/// "body matches its catalog metadata" check accepts the answered document.
#[derive(Clone, PartialEq, Eq)]
pub(super) struct MemoryHeader {
    pub(super) title: String,
    /// Empty when absent ("always considered").
    pub(super) when_to_use: String,
    /// `AutoInclude` when the document names no load mode.
    pub(super) load_mode: MemoryLoadMode,
    pub(super) valid_from_ms: Option<i64>,
    pub(super) valid_until_ms: Option<i64>,
}

impl fmt::Debug for MemoryHeader {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        // Titles and when-to-use text are private Memory metadata.
        f.debug_struct("MemoryHeader")
            .field("load_mode", &self.load_mode)
            .finish_non_exhaustive()
    }
}

impl MemoryHeader {
    /// `isMemoryActive`: inside the optional window, both bounds inclusive.
    pub(super) fn is_active(&self, now_ms: i64) -> bool {
        self.valid_from_ms.is_none_or(|from| now_ms >= from)
            && self.valid_until_ms.is_none_or(|until| now_ms <= until)
    }
}

/// Header of a stored Memory document.
///
/// Reads the document with [`parse_memory_document`], the core's YAML-free
/// reader of the frontmatter subset Memory documents use, so every build
/// (native, browser wasm, Apple) offers the same catalog. Dates follow
/// JavaScript `Date.parse` for ISO 8601, except that a zone-less date-time
/// counts as UTC rather than device-local time.
///
/// # Errors
/// `InvalidDocument` for anything `parseRuleDocument` refuses.
pub(super) fn parse_memory_header(document: &str) -> MemoryResult<MemoryHeader> {
    let fields = parse_memory_document(document)?;
    // The reader already refused unparsable dates; a refusal here would be a
    // reader defect and still fails closed.
    let millis = |value: Option<&str>| -> MemoryResult<Option<i64>> {
        value
            .map(|date| iso_millis(date).ok_or(MemoryDocumentError::InvalidDocument))
            .transpose()
    };
    Ok(MemoryHeader {
        title: fields.title.clone(),
        when_to_use: fields.when_to_use.clone(),
        load_mode: fields.load_mode.unwrap_or(MemoryLoadMode::AutoInclude),
        valid_from_ms: millis(fields.valid_from.as_deref())?,
        valid_until_ms: millis(fields.valid_until.as_deref())?,
    })
}

/// One metadata-only catalog row (`MemoryCatalogEntry` of the backend). Field
/// order is the web object's order; bodies never appear here.
#[derive(Clone, PartialEq, Eq, Serialize)]
pub(super) struct MemoryCatalogEntry {
    pub(super) id: String,
    pub(super) title: String,
    pub(super) when_to_use: String,
    pub(super) load_mode: &'static str,
    pub(super) source: &'static str,
}

impl fmt::Debug for MemoryCatalogEntry {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.debug_struct("MemoryCatalogEntry")
            .field("id", &self.id)
            .field("load_mode", &self.load_mode)
            .finish_non_exhaustive()
    }
}

/// `buildMemoryCatalog`: at most 24 rows and 64,000 UTF-16 units of documents;
/// Mention only and out-of-window Memories are left out.
///
/// # Errors
/// Any header error: like the web builder, one unreadable document makes the
/// whole catalog unavailable rather than silently shrinking it.
pub(super) fn build_memory_catalog(
    documents: &[PersonalMemoryDocument],
    now_ms: i64,
) -> MemoryResult<Vec<MemoryCatalogEntry>> {
    build_memory_catalog_sized(documents, now_ms).map(|(catalog, _)| catalog)
}

/// [`build_memory_catalog`] plus the UTF-16 units of the listed documents, so
/// Project rows can share the same budget.
pub(super) fn build_memory_catalog_sized(
    documents: &[PersonalMemoryDocument],
    now_ms: i64,
) -> MemoryResult<(Vec<MemoryCatalogEntry>, usize)> {
    let mut catalog = Vec::new();
    let mut chars = 0usize;
    for document in documents {
        if catalog.len() >= MAX_DOCUMENTS {
            break;
        }
        let header = parse_memory_header(&document.document)?;
        if header.load_mode == MemoryLoadMode::MentionOnly || !header.is_active(now_ms) {
            continue;
        }
        let size = utf16_len(&document.document);
        if chars + size > MAX_CATALOG_CHARS {
            continue;
        }
        chars += size;
        catalog.push(MemoryCatalogEntry {
            id: document.id.clone(),
            title: header.title,
            when_to_use: header.when_to_use,
            load_mode: header.load_mode.as_str(),
            source: "personal",
        });
    }
    Ok((catalog, chars))
}

/// Append Project catalog rows (each with a `size` field, removed here) to the
/// personal rows, within the same 24-row / [`MAX_CATALOG_CHARS`] bounds.
pub(super) fn merge_project_catalog(
    mut rows: Vec<Value>,
    mut chars: usize,
    project: Vec<Value>,
) -> Vec<Value> {
    for mut row in project {
        if rows.len() >= MAX_DOCUMENTS {
            break;
        }
        let size = row
            .as_object_mut()
            .and_then(|object| object.remove("size"))
            .and_then(|size| size.as_u64())
            .and_then(|size| usize::try_from(size).ok())
            .unwrap_or(usize::MAX);
        if chars.saturating_add(size) > MAX_CATALOG_CHARS {
            continue;
        }
        chars += size;
        rows.push(row);
    }
    rows
}

/// `memory_catalog` of a send from the decrypted account settings (`""` when
/// the account has none). The web sender (`collectMemoryCatalogForSend`)
/// sends no catalog when it cannot be built; so does this function, and the
/// turn then simply cannot select personal Memories.
pub(super) fn send_memory_catalog(
    settings_plaintext: &str,
    now_ms: i64,
) -> Vec<MemoryCatalogEntry> {
    send_memory_catalog_sized(settings_plaintext, now_ms).0
}

/// [`send_memory_catalog`] with the listed documents' UTF-16 units.
pub(super) fn send_memory_catalog_sized(
    settings_plaintext: &str,
    now_ms: i64,
) -> (Vec<MemoryCatalogEntry>, usize) {
    let plaintext = (!settings_plaintext.is_empty()).then_some(settings_plaintext);
    decode_memory_documents(plaintext)
        .and_then(|documents| build_memory_catalog_sized(&documents, now_ms))
        .unwrap_or_default()
}

/// A requested Memory this device may answer, with its stored document.
pub(super) struct ResolvedMemory {
    pub(super) id: String,
    pub(super) title: String,
    /// Canonical stored document; sent unchanged so title/when-to-use match.
    pub(super) document: Zeroizing<String>,
}

impl fmt::Debug for ResolvedMemory {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.debug_struct("ResolvedMemory")
            .field("id", &self.id)
            .finish_non_exhaustive()
    }
}

impl ResolvedMemory {
    /// The requested key of this Memory (`memory-<id>`).
    pub(super) fn key(&self) -> String {
        format!("{MEMORY_REQUEST_KEY_PREFIX}{}", self.id)
    }

    /// `memoryResponseEntry`: one `app_settings_memories_confirmed` entry.
    /// Referenced embeds are not appended (the web adds them; documented gap).
    pub(super) fn response_entry(&self) -> Value {
        json!({"app_id": MEMORY_RESPONSE_APP_ID, "item_key": self.id, "content": self.document.as_str()})
    }
}

/// `decideMemoryRequest`, from this device's documents only: the server's
/// claimed mode is never an input.
#[derive(Debug, Default)]
pub(super) struct MemoryRequestDecision {
    /// Auto include, in window: answered without asking.
    pub(super) auto: Vec<ResolvedMemory>,
    /// Ask first, in window: answered only after approval.
    pub(super) ask: Vec<ResolvedMemory>,
    /// Requested but never answered (Mention only, out of window, unknown or
    /// unreadable).
    pub(super) withheld: Vec<String>,
}

impl super::plaintext::Wipe for MemoryRequestDecision {
    fn wipe(&mut self) {
        use zeroize::Zeroize;
        for memory in self.auto.iter_mut().chain(self.ask.iter_mut()) {
            memory.title.zeroize();
            memory.document.zeroize();
        }
    }
}

/// Memory ids of the requested keys, first occurrence order.
pub(super) fn memory_request_ids<'a>(keys: impl IntoIterator<Item = &'a String>) -> Vec<String> {
    let mut seen = BTreeSet::new();
    keys.into_iter()
        .filter_map(|key| key.strip_prefix(MEMORY_REQUEST_KEY_PREFIX))
        .filter(|id| !id.is_empty() && seen.insert(*id))
        .map(str::to_owned)
        .collect()
}

/// True for a `memory-<id>` key.
pub(super) fn is_memory_request_key(key: &str) -> bool {
    key.strip_prefix(MEMORY_REQUEST_KEY_PREFIX)
        .is_some_and(|id| !id.is_empty())
}

/// Decide each requested id from the stored document's load mode and window.
/// An unreadable document is withheld (the web handler would fail the whole
/// request; withholding answers the turn without private content).
pub(super) fn decide_memory_request(
    ids: &[String],
    documents: &[PersonalMemoryDocument],
    now_ms: i64,
) -> MemoryRequestDecision {
    let mut decision = MemoryRequestDecision::default();
    for id in ids {
        let Some(document) = documents.iter().find(|d| &d.id == id) else {
            decision.withheld.push(id.clone());
            continue;
        };
        let Ok(header) = parse_memory_header(&document.document) else {
            decision.withheld.push(id.clone());
            continue;
        };
        if !header.is_active(now_ms) {
            decision.withheld.push(id.clone());
            continue;
        }
        let resolved = ResolvedMemory {
            id: id.clone(),
            title: header.title,
            document: document.document.clone(),
        };
        match header.load_mode {
            MemoryLoadMode::AutoInclude => decision.auto.push(resolved),
            MemoryLoadMode::AskFirst => decision.ask.push(resolved),
            MemoryLoadMode::MentionOnly => decision.withheld.push(id.clone()),
        }
    }
    decision
}

/// Consent item of one Ask first Memory (id `memory-<id>`, its title). The
/// body stays out of the dialog, like the web dialog that lists the title only.
pub(super) fn ask_first_item(memory: &ResolvedMemory) -> crate::model::Item {
    crate::model::Item {
        id: memory.key(),
        title: memory.title.clone(),
        description: "Ask first Memory".into(),
        fields: json!({"entries": []}),
        ..crate::model::Item::default()
    }
}

impl super::Client {
    /// Decision for the `memory-<id>` keys of one server request, read from the
    /// account's current Memories (a fresh settings read, like the web
    /// `loadLocalMemoryDocuments`). No Memory key means no read.
    ///
    /// # Errors
    /// Session, transport and cancellation errors. Unreadable stored Memories
    /// withhold every requested Memory instead (answering without content).
    pub(super) async fn memory_request_decision(
        &mut self,
        chat_id: &str,
        keys: &BTreeSet<String>,
    ) -> super::Result<MemoryRequestDecision> {
        let ids = memory_request_ids(keys);
        if ids.is_empty() {
            return Ok(MemoryRequestDecision::default());
        }
        let mut documents = match self.personal_memory_documents().await {
            Ok(documents) => documents,
            Err(MemoryDocumentError::Core(error)) => return Err(error),
            Err(_) => Vec::new(),
        };
        // Ids that are not personal may be the active Project's Memories; they
        // are decided from their own stored load mode like personal ones.
        let unknown: Vec<String> = ids
            .iter()
            .filter(|id| !documents.iter().any(|d| &d.id == *id))
            .cloned()
            .collect();
        if !unknown.is_empty() {
            documents.extend(self.project_memory_request_documents(chat_id, &unknown).await?);
        }
        let now = i64::try_from(super::now_ms()).unwrap_or(i64::MAX);
        Ok(decide_memory_request(&ids, &documents, now))
    }
}

#[cfg(test)]
#[path = "memory_catalog_tests.rs"]
mod tests;

// Real-socket tests; the browser build has no tokio test socket.
#[cfg(all(test, not(target_arch = "wasm32")))]
#[path = "memory_consent_tests.rs"]
mod consent_tests;
