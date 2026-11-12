//! Personal Memory catalog of a send and the local answer to server Memory
//! requests, in the shared core (CLI/TUI today; Apple and web bind it later).
//!
//! Mirrors `frontend/packages/ui/src/utils/memoryCatalog.ts` (`buildMemoryCatalog`),
//! `services/memoryDocumentRequest.ts` (`decideMemoryRequest`, `memory-<id>` keys)
//! and the header fields of `utils/ruleDocuments.ts` (`parseRuleDocument`,
//! `isMemoryActive`). Spec: `features.app-memories` (`app-memories.load-modes`).
use super::memory_documents::{
    MAX_CATALOG_CHARS, MAX_DOCUMENTS, MemoryDocumentError, MemoryResult, PersonalMemoryDocument,
    decode_memory_documents, validate_memory_document,
};
use crate::chat_state::js::{js_trim, utf16_len};
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

/// The Memory's `load_mode` header (absent means `AutoInclude`).
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub(super) enum MemoryLoadMode {
    /// Offered in the catalog and answered without asking.
    AutoInclude,
    /// Offered in the catalog; answered only after the user approves.
    AskFirst,
    /// Never offered or answered; only an explicit mention loads it.
    MentionOnly,
}

impl MemoryLoadMode {
    fn wire(self) -> &'static str {
        match self {
            Self::AutoInclude => "auto_include",
            Self::AskFirst => "ask_first",
            Self::MentionOnly => "mention_only",
        }
    }
}

/// Header fields the catalog and the request answer need. Title and
/// when-to-use are trimmed exactly like the web parser, so the server's
/// "body matches its catalog metadata" check accepts the answered document.
#[derive(Clone, PartialEq, Eq)]
pub(super) struct MemoryHeader {
    pub(super) title: String,
    /// Empty when absent ("always considered").
    pub(super) when_to_use: String,
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
/// Parses the YAML frontmatter with the crate's YAML parser (`workflow-yaml`
/// feature, enabled by the native CLI/TUI). Dates follow JavaScript
/// `Date.parse` except that a zone-less date-time counts as UTC rather than
/// device-local time.
///
/// # Errors
/// `InvalidDocument` for anything `parseRuleDocument` refuses; without the
/// `workflow-yaml` feature every document is `Core(Error::Invalid)`.
pub(super) fn parse_memory_header(document: &str) -> MemoryResult<MemoryHeader> {
    validate_memory_document(document)?;
    let header = frontmatter(document).ok_or(MemoryDocumentError::InvalidDocument)?;
    header_fields(&yaml_mapping(header)?)
}

fn frontmatter(document: &str) -> Option<&str> {
    static FENCE: std::sync::OnceLock<regex::Regex> = std::sync::OnceLock::new();
    // Same expression as `validate_memory_document` and the web parser.
    let fence = FENCE.get_or_init(|| {
        regex::Regex::new(r"(?s)\A---\r?\n(.*?)\r?\n---(?:\r?\n|\z)(.*)\z")
            .expect("static frontmatter expression")
    });
    let source = document.strip_prefix('\u{FEFF}').unwrap_or(document);
    fence
        .captures(source)
        .map(|c| c.get(1).map_or("", |m| m.as_str()))
}

#[cfg(feature = "workflow-yaml")]
fn yaml_mapping(header: &str) -> MemoryResult<serde_json::Map<String, Value>> {
    match serde_yaml::from_str::<Value>(header) {
        Ok(Value::Object(map)) => Ok(map),
        _ => Err(MemoryDocumentError::InvalidDocument),
    }
}

#[cfg(not(feature = "workflow-yaml"))]
fn yaml_mapping(_header: &str) -> MemoryResult<serde_json::Map<String, Value>> {
    Err(MemoryDocumentError::Core(super::Error::Invalid(
        "Memory headers need the workflow-yaml feature of the client core.",
    )))
}

fn header_fields(record: &serde_json::Map<String, Value>) -> MemoryResult<MemoryHeader> {
    let text = |field: &str, max: usize| -> MemoryResult<Option<String>> {
        match record.get(field) {
            None => Ok(None),
            Some(Value::String(value)) => {
                let trimmed = js_trim(value);
                if trimmed.is_empty() || utf16_len(trimmed) > max {
                    return Err(MemoryDocumentError::InvalidDocument);
                }
                Ok(Some(trimmed.to_owned()))
            }
            Some(_) => Err(MemoryDocumentError::InvalidDocument),
        }
    };
    let title = text("title", 180)?.ok_or(MemoryDocumentError::InvalidDocument)?;
    let when_to_use = text("when_to_use", 1200)?.unwrap_or_default();
    text("description", 1200)?;
    let load_mode = match record.get("load_mode") {
        None => MemoryLoadMode::AutoInclude,
        Some(Value::String(mode)) => match mode.as_str() {
            "auto_include" => MemoryLoadMode::AutoInclude,
            "ask_first" => MemoryLoadMode::AskFirst,
            "mention_only" => MemoryLoadMode::MentionOnly,
            _ => return Err(MemoryDocumentError::InvalidDocument),
        },
        Some(_) => return Err(MemoryDocumentError::InvalidDocument),
    };
    let date = |field: &str| -> MemoryResult<Option<i64>> {
        match record.get(field) {
            None => Ok(None),
            Some(value @ Value::String(_)) => super::overview::parse_time(Some(value), 0)
                .map(Some)
                .ok_or(MemoryDocumentError::InvalidDocument),
            Some(_) => Err(MemoryDocumentError::InvalidDocument),
        }
    };
    let (valid_from_ms, valid_until_ms) = (date("valid_from")?, date("valid_until")?);
    if let (Some(from), Some(until)) = (valid_from_ms, valid_until_ms)
        && from > until
    {
        return Err(MemoryDocumentError::InvalidDocument);
    }
    Ok(MemoryHeader {
        title,
        when_to_use,
        load_mode,
        valid_from_ms,
        valid_until_ms,
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
            load_mode: header.load_mode.wire(),
            source: "personal",
        });
    }
    Ok(catalog)
}

/// `memory_catalog` of a send from the decrypted account settings (`""` when
/// the account has none). The web sender (`collectMemoryCatalogForSend`)
/// sends no catalog when it cannot be built; so does this function, and the
/// turn then simply cannot select personal Memories.
pub(super) fn send_memory_catalog(
    settings_plaintext: &str,
    now_ms: i64,
) -> Vec<MemoryCatalogEntry> {
    let plaintext = (!settings_plaintext.is_empty()).then_some(settings_plaintext);
    decode_memory_documents(plaintext)
        .and_then(|documents| build_memory_catalog(&documents, now_ms))
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
        keys: &BTreeSet<String>,
    ) -> super::Result<MemoryRequestDecision> {
        let ids = memory_request_ids(keys);
        if ids.is_empty() {
            return Ok(MemoryRequestDecision::default());
        }
        let documents = match self.personal_memory_documents().await {
            Ok(documents) => documents,
            Err(MemoryDocumentError::Core(error)) => return Err(error),
            Err(_) => Vec::new(),
        };
        let now = i64::try_from(super::now_ms()).unwrap_or(i64::MAX);
        Ok(decide_memory_request(&ids, &documents, now))
    }
}

#[cfg(test)]
#[path = "memory_catalog_tests.rs"]
mod tests;

// The consent flow reads Memory headers, which need the YAML parser.
#[cfg(all(test, feature = "workflow-yaml", not(target_arch = "wasm32")))]
#[path = "memory_consent_tests.rs"]
mod consent_tests;
