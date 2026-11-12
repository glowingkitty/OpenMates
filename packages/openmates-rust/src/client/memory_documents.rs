//! Personal Memory documents: list, create, update and delete in the shared core.
//!
//! Mirrors `frontend/packages/ui/src/services/ruleDocumentService.ts`
//! (`listPersonalRuleDocuments`, `savePersonalRuleDocument`,
//! `deletePersonalRuleDocument`) byte for byte at the plaintext level: Memories
//! live as `[{id, document}]` under `memory_documents` (legacy `rule_documents`
//! is read and kept) inside the master-key encrypted account settings posted
//! to `/v1/settings/encrypted-account`. Spec: `features.app-memories`.
use super::plaintext::Plain;
use super::*;
use crate::chat_state::bookmarks::OrderedObject;
use crate::chat_state::js::{js_trim, json_string, utf16_len};
use crate::crypto::master::MasterCapability;
use serde_json::value::RawValue;
use std::fmt;
use zeroize::Zeroizing;

/// Settings key the web client writes (`PERSONAL_SETTINGS_KEY`).
pub const MEMORY_DOCUMENTS_KEY: &str = "memory_documents";
/// Legacy settings key; read, kept on write, filtered on delete.
pub const LEGACY_RULE_DOCUMENTS_KEY: &str = "rule_documents";
/// `MAX_RULE_DOCUMENT_CHARS` (UTF-16 units).
pub const MAX_DOCUMENT_CHARS: usize = 24_000;
/// `MAX_RULE_DOCUMENTS`.
pub const MAX_DOCUMENTS: usize = 24;
/// `MAX_RULE_CATALOG_CHARS` (UTF-16 units over every document).
pub const MAX_CATALOG_CHARS: usize = 64_000;
const MAX_BODY_CHARS: usize = 20_000;
const MAX_ID_CHARS: usize = 240;
// `created_at`/`updated_at` (unix seconds) and `app_id` are optional display
// metadata the web editor writes; old documents without them stay valid.
const HEADER_KEYS: [&str; 10] = [
    "title",
    "description",
    "when_to_use",
    "load_mode",
    "valid_from",
    "valid_until",
    "references",
    "created_at",
    "updated_at",
    "app_id",
];
const SETTINGS_ROUTE: &str = "/v1/settings/encrypted-account";

/// Refusal of a Memory document operation. [`MemoryDocumentError::code`] returns
/// the web client's error codes (`ruleDocumentService.ts`) so every shell and
/// the `memory_write_job_result.error_code` report the same values.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum MemoryDocumentError {
    /// The Memory to update or delete does not exist (`rule_not_found`).
    NotFound,
    /// A create named an id that already exists (`rule_exists`).
    AlreadyExists,
    /// The Memory changed since the write that Undo would revert (`rule_changed`).
    Changed,
    /// The history event carries no valid assistant Undo data (`rule_not_undoable`).
    NotUndoable,
    /// A document or the stored list is not a valid Memory (`invalid_rule_document`).
    InvalidDocument,
    /// More than 24 Memories or 64,000 characters in total (`rule_catalog_limit`).
    CatalogLimit,
    /// The encrypted settings cannot be decrypted or parsed (`rule_settings_unavailable`).
    SettingsUnavailable,
    /// The server refused or did not confirm the settings write (`rule_save_failed`).
    SaveFailed,
    /// Session, transport or cancellation failure from the core.
    Core(Error),
}

impl MemoryDocumentError {
    /// Stable lowercase code (`[a-z0-9_]`), also valid as a job `error_code`.
    pub fn code(&self) -> &'static str {
        match self {
            Self::NotFound => "rule_not_found",
            Self::AlreadyExists => "rule_exists",
            Self::Changed => "rule_changed",
            Self::NotUndoable => "rule_not_undoable",
            Self::InvalidDocument => "invalid_rule_document",
            Self::CatalogLimit => "rule_catalog_limit",
            Self::SettingsUnavailable => "rule_settings_unavailable",
            Self::SaveFailed => "rule_save_failed",
            Self::Core(Error::Authentication | Error::Expired) => "rule_auth_required",
            Self::Core(Error::Offline) => "offline",
            Self::Core(Error::Cancelled) => "cancelled",
            Self::Core(_) => "rule_save_failed",
        }
    }
}

impl fmt::Display for MemoryDocumentError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::Core(error) => error.fmt(f),
            Self::NotFound => f.write_str("That Memory does not exist."),
            Self::AlreadyExists => f.write_str("A Memory with that id already exists."),
            Self::Changed => f.write_str("The Memory changed since; it was left as it is."),
            Self::NotUndoable => f.write_str("This Memory change cannot be undone here."),
            Self::InvalidDocument => f.write_str("The Memory document is not valid."),
            Self::CatalogLimit => {
                f.write_str("Memory limit reached (24 Memories, 64,000 characters).")
            }
            Self::SettingsUnavailable => f.write_str("Account settings are unavailable."),
            Self::SaveFailed => f.write_str("The Memory could not be saved."),
        }
    }
}

impl std::error::Error for MemoryDocumentError {}

impl From<Error> for MemoryDocumentError {
    fn from(error: Error) -> Self {
        Self::Core(error)
    }
}

/// Result alias of this module.
pub type MemoryResult<T> = std::result::Result<T, MemoryDocumentError>;

/// One personal Memory: its id (`personal:<uuid>` for new ones) and the
/// canonical Markdown document. The document is private and wiped on drop.
#[derive(Clone, PartialEq, Eq)]
pub struct PersonalMemoryDocument {
    /// Stored id; the web opens it in Settings > Memories.
    pub id: String,
    /// Markdown with YAML frontmatter (`title`, `when_to_use`, ...).
    pub document: Zeroizing<String>,
}

impl fmt::Debug for PersonalMemoryDocument {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        // Never print private Memory text.
        f.debug_struct("PersonalMemoryDocument")
            .field("id", &self.id)
            .finish_non_exhaustive()
    }
}

/// How a write treats the target id.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum MemoryWriteMode {
    /// The id must not exist yet.
    Create,
    /// The id must exist; its document is replaced in place.
    Update,
}

/// Next settings plaintext plus the document it replaced or removed.
pub struct SettingsChange {
    /// `JSON.stringify` of the new account settings, unrelated keys untouched.
    pub plaintext: Zeroizing<String>,
    /// Previous document of an update or delete; `None` for a create.
    pub previous: Option<Zeroizing<String>>,
}

/// New settings ciphertext to post, plus the replaced/removed document.
pub struct PreparedMemorySettings {
    /// Master-key ciphertext (IV||ciphertext||tag, base64), as the web writes it.
    pub encrypted_settings: String,
    /// See [`SettingsChange::previous`].
    pub previous: Option<Zeroizing<String>>,
}

/// A fresh id in the web format (`personal:<uuid>`).
pub fn new_memory_id() -> String {
    format!("personal:{}", uuid::Uuid::new_v4())
}

/// Lowercase hex SHA-256 of a document (Undo's "unchanged since" check).
pub fn document_sha256(document: &str) -> String {
    use sha2::{Digest, Sha256};
    Sha256::digest(document.as_bytes())
        .iter()
        .map(|b| format!("{b:02x}"))
        .collect()
}

/// Structural check of `parseRuleDocument`: size, `---` frontmatter fence,
/// a `title` key, only known top-level keys and a non-empty body of at most
/// 20,000 characters. It does not re-run the full YAML grammar: the server
/// (`memory_document.py`) and the web parser validate that; this check only
/// refuses what the web parser certainly refuses.
///
/// # Errors
/// [`MemoryDocumentError::InvalidDocument`].
pub fn validate_memory_document(document: &str) -> MemoryResult<()> {
    static FENCE: std::sync::OnceLock<regex::Regex> = std::sync::OnceLock::new();
    static KEY: std::sync::OnceLock<regex::Regex> = std::sync::OnceLock::new();
    let fence = FENCE.get_or_init(|| {
        regex::Regex::new(r"(?s)\A---\r?\n(.*?)\r?\n---(?:\r?\n|\z)(.*)\z")
            .expect("static frontmatter expression")
    });
    let key = KEY.get_or_init(|| {
        regex::Regex::new(r"\A([A-Za-z_][A-Za-z0-9_-]*)[ \t]*:").expect("static key expression")
    });
    if utf16_len(document) > MAX_DOCUMENT_CHARS {
        return Err(MemoryDocumentError::InvalidDocument);
    }
    let source = document.strip_prefix('\u{FEFF}').unwrap_or(document);
    let captures = fence
        .captures(source)
        .ok_or(MemoryDocumentError::InvalidDocument)?;
    let (header, body) = (&captures[1], js_trim(&captures[2]));
    let mut keys = Vec::new();
    for line in header.lines() {
        if let Some(found) = key.captures(line) {
            let name = found[1].to_owned();
            if !HEADER_KEYS.contains(&name.as_str()) || keys.contains(&name) {
                return Err(MemoryDocumentError::InvalidDocument);
            }
            keys.push(name);
        }
    }
    if !keys.iter().any(|k| k == "title") || body.is_empty() || utf16_len(body) > MAX_BODY_CHARS {
        return Err(MemoryDocumentError::InvalidDocument);
    }
    Ok(())
}

fn settings(plaintext: Option<&str>) -> MemoryResult<OrderedObject> {
    match plaintext {
        None => Ok(OrderedObject::empty()),
        Some(text) => {
            OrderedObject::parse(text).map_err(|_| MemoryDocumentError::SettingsUnavailable)
        }
    }
}

/// Entries of one settings key: `null`/absent is empty, a non-array is invalid.
fn raw_entries(settings: &OrderedObject, key: &str) -> MemoryResult<Vec<Box<RawValue>>> {
    let Some(raw) = settings.get(key) else {
        return Ok(Vec::new());
    };
    if raw.get() == "null" {
        return Ok(Vec::new());
    }
    serde_json::from_str::<Vec<Box<RawValue>>>(raw.get())
        .map_err(|_| MemoryDocumentError::InvalidDocument)
}

/// `{id, document}` of one stored entry; any other key or type is invalid.
fn entry(raw: &RawValue) -> MemoryResult<PersonalMemoryDocument> {
    let mut value = Plain::new(
        serde_json::from_str::<Value>(raw.get())
            .map_err(|_| MemoryDocumentError::InvalidDocument)?,
    );
    let object = value
        .as_object_mut()
        .ok_or(MemoryDocumentError::InvalidDocument)?;
    if object.keys().any(|k| k != "id" && k != "document") {
        return Err(MemoryDocumentError::InvalidDocument);
    }
    let (Some(Value::String(id)), Some(Value::String(document))) =
        (object.get("id"), object.get("document"))
    else {
        return Err(MemoryDocumentError::InvalidDocument);
    };
    Ok(PersonalMemoryDocument {
        id: id.clone(),
        document: Zeroizing::new(document.clone()),
    })
}

/// `personalDocuments`: legacy then canonical entries, merged by id (a later
/// entry replaces the value but keeps the first position, like `Map.set`),
/// then `validateRuleCatalog`.
fn documents(settings: &OrderedObject) -> MemoryResult<Vec<PersonalMemoryDocument>> {
    let mut merged: Vec<PersonalMemoryDocument> = Vec::new();
    for key in [LEGACY_RULE_DOCUMENTS_KEY, MEMORY_DOCUMENTS_KEY] {
        for raw in raw_entries(settings, key)? {
            let next = entry(&raw)?;
            match merged.iter_mut().find(|d| d.id == next.id) {
                Some(slot) => *slot = next,
                None => merged.push(next),
            }
        }
    }
    validate_catalog(&merged)?;
    Ok(merged)
}

/// `validateRuleCatalog` for personal documents.
fn validate_catalog(documents: &[PersonalMemoryDocument]) -> MemoryResult<()> {
    if documents.len() > MAX_DOCUMENTS {
        return Err(MemoryDocumentError::CatalogLimit);
    }
    let mut size = 0usize;
    for (index, document) in documents.iter().enumerate() {
        if document.id.is_empty()
            || utf16_len(&document.id) > MAX_ID_CHARS
            || document.id.starts_with("app:")
            || documents[..index].iter().any(|d| d.id == document.id)
        {
            return Err(MemoryDocumentError::InvalidDocument);
        }
        validate_memory_document(&document.document)?;
        size += utf16_len(&document.document);
    }
    if size > MAX_CATALOG_CHARS {
        return Err(MemoryDocumentError::CatalogLimit);
    }
    Ok(())
}

fn canonical_json(documents: &[PersonalMemoryDocument]) -> Zeroizing<String> {
    let entries: Vec<String> = documents
        .iter()
        .map(|d| {
            format!(
                "{{\"id\":{},\"document\":{}}}",
                json_string(&d.id),
                json_string(&d.document)
            )
        })
        .collect();
    Zeroizing::new(format!("[{}]", entries.join(",")))
}

fn finish(settings: OrderedObject) -> Zeroizing<String> {
    Zeroizing::new(settings.to_json())
}

/// Decoded personal Memories of decrypted settings (`None` = no settings).
///
/// # Errors
/// `SettingsUnavailable` for non-object settings, `InvalidDocument` /
/// `CatalogLimit` for a stored list the web client would refuse too.
pub fn decode_memory_documents(
    plaintext: Option<&str>,
) -> MemoryResult<Vec<PersonalMemoryDocument>> {
    documents(&settings(plaintext)?)
}

/// `savePersonalRuleDocument` on decrypted settings: validates `document`,
/// creates or replaces `id` and rewrites `memory_documents` as the merged list.
///
/// # Errors
/// `InvalidDocument`, `CatalogLimit`, `NotFound` (update of a missing id),
/// `AlreadyExists` (create of an existing id), `SettingsUnavailable`.
pub fn write_memory_plaintext(
    plaintext: Option<&str>,
    id: &str,
    document: &str,
    mode: MemoryWriteMode,
) -> MemoryResult<SettingsChange> {
    validate_memory_document(document)?;
    let mut value = settings(plaintext)?;
    let mut list = documents(&value)?;
    let next = PersonalMemoryDocument {
        id: id.to_owned(),
        document: Zeroizing::new(document.to_owned()),
    };
    let previous = match (list.iter_mut().find(|d| d.id == id), mode) {
        (Some(slot), MemoryWriteMode::Update) => {
            Some(std::mem::replace(&mut slot.document, next.document))
        }
        (None, MemoryWriteMode::Create) => {
            list.push(next);
            None
        }
        (Some(_), MemoryWriteMode::Create) => return Err(MemoryDocumentError::AlreadyExists),
        (None, MemoryWriteMode::Update) => return Err(MemoryDocumentError::NotFound),
    };
    validate_catalog(&list)?;
    value
        .set(MEMORY_DOCUMENTS_KEY, canonical_json(&list).to_string())
        .map_err(|_| MemoryDocumentError::SettingsUnavailable)?;
    Ok(SettingsChange {
        plaintext: finish(value),
        previous,
    })
}

/// `deletePersonalRuleDocument` on decrypted settings: removes `id` from both
/// keys and keeps every other entry's original JSON text.
///
/// # Errors
/// `NotFound`, plus the decode errors of [`decode_memory_documents`].
pub fn delete_memory_plaintext(plaintext: Option<&str>, id: &str) -> MemoryResult<SettingsChange> {
    let mut value = settings(plaintext)?;
    let previous = documents(&value)?
        .into_iter()
        .find(|d| d.id == id)
        .map(|d| d.document)
        .ok_or(MemoryDocumentError::NotFound)?;
    for key in [MEMORY_DOCUMENTS_KEY, LEGACY_RULE_DOCUMENTS_KEY] {
        if value.get(key).is_none_or(|raw| raw.get() == "null") {
            continue;
        }
        let kept: Vec<String> = raw_entries(&value, key)?
            .into_iter()
            .filter(|raw| entry(raw).map(|d| d.id != id).unwrap_or(true))
            .map(|raw| raw.get().to_owned())
            .collect();
        let joined = Zeroizing::new(format!("[{}]", kept.join(",")));
        value
            .set(key, joined.to_string())
            .map_err(|_| MemoryDocumentError::SettingsUnavailable)?;
    }
    Ok(SettingsChange {
        plaintext: finish(value),
        previous: Some(previous),
    })
}

async fn decrypt(
    master: &MasterCapability,
    ciphertext: Option<&str>,
) -> MemoryResult<Option<Zeroizing<String>>> {
    match ciphertext.filter(|c| !c.is_empty()) {
        None => Ok(None),
        Some(ciphertext) => match master.decrypt_text(ciphertext).await {
            Ok(plaintext) => Ok(Some(Zeroizing::new(plaintext))),
            Err(Error::Crypto) => Err(MemoryDocumentError::SettingsUnavailable),
            Err(other) => Err(other.into()),
        },
    }
}

async fn seal(
    master: &MasterCapability,
    change: SettingsChange,
) -> MemoryResult<PreparedMemorySettings> {
    let encrypted_settings = master
        .encrypt_server_bytes(change.plaintext.as_bytes())
        .await?;
    Ok(PreparedMemorySettings {
        encrypted_settings,
        previous: change.previous,
    })
}

/// Personal Memories of the current `encrypted_settings` ciphertext.
///
/// # Errors
/// See [`decode_memory_documents`]; undecryptable settings are `SettingsUnavailable`.
pub async fn read_memory_documents(
    master: &MasterCapability,
    ciphertext: Option<&str>,
) -> MemoryResult<Vec<PersonalMemoryDocument>> {
    decode_memory_documents(
        decrypt(master, ciphertext)
            .await?
            .as_deref()
            .map(|s| s.as_str()),
    )
}

/// Encrypted settings after a create/update; the caller posts them.
///
/// # Errors
/// See [`write_memory_plaintext`].
pub async fn prepare_memory_write(
    master: &MasterCapability,
    ciphertext: Option<&str>,
    id: &str,
    document: &str,
    mode: MemoryWriteMode,
) -> MemoryResult<PreparedMemorySettings> {
    let plaintext = decrypt(master, ciphertext).await?;
    let change =
        write_memory_plaintext(plaintext.as_deref().map(|s| s.as_str()), id, document, mode)?;
    seal(master, change).await
}

/// Encrypted settings after a delete; the caller posts them.
///
/// # Errors
/// See [`delete_memory_plaintext`].
pub async fn prepare_memory_delete(
    master: &MasterCapability,
    ciphertext: Option<&str>,
    id: &str,
) -> MemoryResult<PreparedMemorySettings> {
    let plaintext = decrypt(master, ciphertext).await?;
    let change = delete_memory_plaintext(plaintext.as_deref().map(|s| s.as_str()), id)?;
    seal(master, change).await
}

impl Client {
    /// Fresh `encrypted_settings` of the signed-in user (a server round trip).
    pub(super) async fn settings_ciphertext(&mut self) -> MemoryResult<Option<String>> {
        self.require_session()?;
        self.validate_session().await?;
        match self.user.get("encrypted_settings") {
            None | Some(Value::Null) => Ok(None),
            Some(Value::String(text)) => Ok(Some(text.clone())),
            Some(_) => Err(Error::Protocol.into()),
        }
    }

    /// Post new settings ciphertext and keep the local profile in step.
    ///
    /// The endpoint replaces the whole record and has no compare-and-swap
    /// token (like the web client); the read-modify-write window is one call.
    pub(super) async fn post_settings(
        &mut self,
        prepared: &PreparedMemorySettings,
    ) -> MemoryResult<()> {
        let response = self
            .request(
                Method::POST,
                SETTINGS_ROUTE,
                Some(json!({"encrypted_settings": prepared.encrypted_settings})),
            )
            .await
            .map_err(|error| match error {
                Error::Offline | Error::Cancelled | Error::Authentication | Error::Expired => {
                    MemoryDocumentError::Core(error)
                }
                _ => MemoryDocumentError::SaveFailed,
            })?;
        if response.get("success") != Some(&Value::Bool(true)) {
            return Err(MemoryDocumentError::SaveFailed);
        }
        self.user["encrypted_settings"] = json!(prepared.encrypted_settings);
        Ok(())
    }

    /// Decrypted personal Memories of the signed-in user.
    ///
    /// # Errors
    /// Session/transport errors and the decode errors of [`decode_memory_documents`].
    pub async fn personal_memory_documents(&mut self) -> MemoryResult<Vec<PersonalMemoryDocument>> {
        let ciphertext = self.settings_ciphertext().await?;
        read_memory_documents(&self.master_capability()?, ciphertext.as_deref()).await
    }

    /// Create or update one personal Memory; returns the replaced document
    /// (`None` for a create).
    ///
    /// # Errors
    /// See [`write_memory_plaintext`]; `SaveFailed` when the server refuses.
    pub async fn save_personal_memory_document(
        &mut self,
        id: &str,
        document: &str,
        mode: MemoryWriteMode,
    ) -> MemoryResult<Option<Zeroizing<String>>> {
        let ciphertext = self.settings_ciphertext().await?;
        let master = self.master_capability()?;
        let prepared =
            prepare_memory_write(&master, ciphertext.as_deref(), id, document, mode).await?;
        self.post_settings(&prepared).await?;
        Ok(prepared.previous)
    }

    /// Delete one personal Memory; returns its last document.
    ///
    /// # Errors
    /// `NotFound`, decode errors, `SaveFailed` when the server refuses.
    pub async fn delete_personal_memory_document(
        &mut self,
        id: &str,
    ) -> MemoryResult<Zeroizing<String>> {
        let ciphertext = self.settings_ciphertext().await?;
        let master = self.master_capability()?;
        let prepared = prepare_memory_delete(&master, ciphertext.as_deref(), id).await?;
        self.post_settings(&prepared).await?;
        prepared.previous.ok_or(MemoryDocumentError::NotFound)
    }
}

#[cfg(test)]
#[path = "memory_documents_tests.rs"]
mod tests;
