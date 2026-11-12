//! Memories on `ViewModelCore`: the personal Memory documents of Settings >
//! Memories (list, read, create, update, delete, expiry sweep) and the
//! assistant's Memory writes in a chat (opt-in, notices, Undo), exported to
//! Swift. Logic lives in the core (`client::memory_documents`,
//! `client::memory_document_fields`, `client::memory_write_jobs`); this module
//! only marshals plaintext presentation records, never keys or ciphertext.
//! Mirrors the web `ruleDocumentService.ts`; spec `features.app-memories`.
use crate::CoreError;
use crate::core::CoreCancellation;
use crate::view_core::{Shared, ViewModelCore};
use futures_util::future::BoxFuture;
use openmates_sdk::{
    Client,
    client::{
        memory_document_fields::{
            MemoryDocumentFields, MemoryLoadMode, is_memory_expired, parse_memory_document,
            serialize_memory_document, stamp_memory_save,
        },
        memory_documents::{
            MemoryDocumentError, MemoryWriteMode, PersonalMemoryDocument, new_memory_id,
        },
        memory_write_jobs::MemoryUndoOutcome,
        recommendations::{
            ContextEntryAction, ContextEntryHistoryEvent, ContextEntrySource, RecommendationKind,
            parse_context_entry_event,
        },
    },
    error::Error,
    view_model::ViewHost,
};
use std::sync::Arc;
use std::sync::atomic::Ordering;
use std::time::{SystemTime, UNIX_EPOCH};
use tokio_util::sync::CancellationToken;

type Memory<T> = std::result::Result<T, MemoryDocumentError>;

/// When the assistant loads a Memory (`load_mode`).
#[derive(Clone, Copy, Debug, PartialEq, Eq, uniffi::Enum)]
pub enum MemoryLoadModeRecord {
    /// `auto_include`: loaded whenever it applies (the web default).
    AutoInclude,
    /// `ask_first`: the user is asked before it is loaded.
    AskFirst,
    /// `mention_only`: only when the user mentions it.
    MentionOnly,
}

/// The editable fields of one Memory page (web `RuleDocumentFields` without
/// the save times, which the core stamps).
#[derive(Clone, PartialEq, Eq, uniffi::Record)]
pub struct MemoryFieldsRecord {
    /// Title, at most 180 characters once trimmed; required.
    pub title: String,
    /// Legacy summary; keep what was read, new Memories pass `nil`.
    pub description: Option<String>,
    /// When the assistant should use it (at most 1,200 characters); empty
    /// means always considered.
    pub when_to_use: String,
    /// Markdown body (at most 20,000 characters); required.
    pub body: String,
    /// `nil` stores no load mode (the web editor writes `AutoInclude`).
    pub load_mode: Option<MemoryLoadModeRecord>,
    /// Start of the validity window, ISO 8601 (the web writes
    /// `YYYY-MM-DDT00:00:00.000Z`).
    pub valid_from: Option<String>,
    /// Expiry, ISO 8601 (the web writes `YYYY-MM-DDT23:59:59.000Z`); the
    /// Memory is deleted once it passed (`deleteExpiredMemoryDocuments`).
    pub valid_until: Option<String>,
    /// Embed ids the body references; keep what was read.
    pub references: Vec<String>,
    /// Optional app the Memory belongs to (icon and colour only).
    pub app_id: Option<String>,
}

/// One stored personal Memory, decrypted.
#[derive(Clone, PartialEq, Eq, uniffi::Record)]
pub struct MemoryDocumentRecord {
    /// Stored id (`personal:<uuid>`); pass it to read, update and delete.
    pub id: String,
    /// The parsed fields; `nil` when this client cannot read the document
    /// (then show `document` read-only; delete still works).
    pub fields: Option<MemoryFieldsRecord>,
    /// Unix seconds of the first save (`nil` for older Memories).
    pub created_at: Option<u64>,
    /// Unix seconds of the latest save; sort "modified" by `updatedAt ??
    /// createdAt`, untimed Memories last, later stored first.
    pub updated_at: Option<u64>,
    /// `validUntil` has passed (the web hides and deletes such Memories).
    pub expired: bool,
    /// The canonical Markdown document as stored.
    pub document: String,
}

/// Kind of entry a `context_entry` chat notice announces.
#[derive(Clone, Copy, Debug, PartialEq, Eq, uniffi::Enum)]
pub enum ContextEntryKindRecord {
    /// A Memory.
    Memory,
    /// A workflow.
    Workflow,
}

/// What happened to the announced entry.
#[derive(Clone, Copy, Debug, PartialEq, Eq, uniffi::Enum)]
pub enum ContextEntryActionRecord {
    /// A new entry was created.
    Created,
    /// An existing entry was updated.
    Updated,
}

/// A `context_entry` system message of a chat ("Memory saved"), as shown.
#[derive(Clone, Debug, PartialEq, Eq, uniffi::Record)]
pub struct ContextEntryNoticeRecord {
    /// Memory or workflow.
    pub kind: ContextEntryKindRecord,
    /// Created or updated.
    pub action: ContextEntryActionRecord,
    /// Id of the saved entry (a Memory id opens its Settings page).
    pub entry_id: String,
    /// Title shown in the history line.
    pub title: String,
    /// Unix seconds.
    pub created_at: i64,
    /// The assistant wrote the entry during a turn (no review step).
    pub from_assistant: bool,
    /// Job id to pass to `undoAssistantMemoryWrite`; `nil` when the notice
    /// carries no Undo data.
    pub undo_job_id: Option<String>,
}

/// What an Undo did.
#[derive(Clone, Copy, Debug, PartialEq, Eq, uniffi::Enum)]
pub enum MemoryUndoOutcomeRecord {
    /// The Memory the assistant created was deleted.
    Deleted,
    /// The Memory the assistant updated holds its previous document again.
    Restored,
}

impl From<MemoryLoadMode> for MemoryLoadModeRecord {
    fn from(mode: MemoryLoadMode) -> Self {
        match mode {
            MemoryLoadMode::AutoInclude => Self::AutoInclude,
            MemoryLoadMode::AskFirst => Self::AskFirst,
            MemoryLoadMode::MentionOnly => Self::MentionOnly,
        }
    }
}

impl From<MemoryLoadModeRecord> for MemoryLoadMode {
    fn from(mode: MemoryLoadModeRecord) -> Self {
        match mode {
            MemoryLoadModeRecord::AutoInclude => Self::AutoInclude,
            MemoryLoadModeRecord::AskFirst => Self::AskFirst,
            MemoryLoadModeRecord::MentionOnly => Self::MentionOnly,
        }
    }
}

fn fields_record(fields: &MemoryDocumentFields) -> MemoryFieldsRecord {
    MemoryFieldsRecord {
        title: fields.title.clone(),
        description: fields.description.clone(),
        when_to_use: fields.when_to_use.clone(),
        body: fields.body.clone(),
        load_mode: fields.load_mode.map(Into::into),
        valid_from: fields.valid_from.clone(),
        valid_until: fields.valid_until.clone(),
        references: fields.references.clone(),
        app_id: fields.app_id.clone(),
    }
}

fn core_fields(record: MemoryFieldsRecord) -> MemoryDocumentFields {
    // No struct literal: the core type wipes itself on drop.
    let mut fields = MemoryDocumentFields::default();
    fields.title = record.title;
    fields.description = record.description;
    fields.when_to_use = record.when_to_use;
    fields.body = record.body;
    fields.load_mode = record.load_mode.map(Into::into);
    fields.valid_from = record.valid_from;
    fields.valid_until = record.valid_until;
    fields.references = record.references;
    fields.app_id = record.app_id;
    fields
}

fn now_ms() -> i64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map_or(0, |elapsed| {
            i64::try_from(elapsed.as_millis()).unwrap_or(i64::MAX)
        })
}

/// The presentation record of a stored Memory at `now_ms`.
pub(crate) fn document_record(
    document: &PersonalMemoryDocument,
    now_ms: i64,
) -> MemoryDocumentRecord {
    let parsed = parse_memory_document(&document.document).ok();
    MemoryDocumentRecord {
        id: document.id.clone(),
        fields: parsed.as_ref().map(fields_record),
        created_at: parsed.as_ref().and_then(|f| f.created_at),
        updated_at: parsed.as_ref().and_then(|f| f.updated_at),
        expired: parsed
            .as_ref()
            .is_some_and(|f| is_memory_expired(f, now_ms)),
        document: document.document.to_string(),
    }
}

/// The presentation record of a parsed `context_entry` event.
pub(crate) fn notice_record(event: &ContextEntryHistoryEvent) -> ContextEntryNoticeRecord {
    ContextEntryNoticeRecord {
        kind: match event.kind {
            RecommendationKind::Memory => ContextEntryKindRecord::Memory,
            RecommendationKind::Workflow => ContextEntryKindRecord::Workflow,
        },
        action: match event.action {
            ContextEntryAction::Created => ContextEntryActionRecord::Created,
            ContextEntryAction::Updated => ContextEntryActionRecord::Updated,
        },
        entry_id: event.entry_id.clone(),
        title: event.title.clone(),
        created_at: event.created_at,
        from_assistant: event.source == Some(ContextEntrySource::Assistant),
        undo_job_id: event.undo.as_ref().map(|undo| undo.job_id.clone()),
    }
}

/// Create (`existing: None`) or update one Memory from Swift's fields; the
/// core stamps the save times like the web editor (`stampMemorySave`).
async fn save(
    client: &mut Client,
    existing: Option<String>,
    fields: MemoryFieldsRecord,
) -> Memory<MemoryDocumentRecord> {
    let mut fields = core_fields(fields);
    let (id, mode, previous) = match existing {
        None => (new_memory_id(), MemoryWriteMode::Create, None),
        Some(id) => {
            let documents = client.personal_memory_documents().await?;
            let stored = documents
                .iter()
                .find(|d| d.id == id)
                .ok_or(MemoryDocumentError::NotFound)?;
            let previous = parse_memory_document(&stored.document).ok();
            (id, MemoryWriteMode::Update, previous)
        }
    };
    let now = now_ms();
    let now_s = u64::try_from(now / 1000).unwrap_or(0);
    stamp_memory_save(&mut fields, previous.as_ref(), now_s);
    let document = serialize_memory_document(&fields)?;
    client
        .save_personal_memory_document(&id, &document, mode)
        .await?;
    let saved = PersonalMemoryDocument { id, document };
    Ok(document_record(&saved, now))
}

async fn undo(
    client: &mut Client,
    chat_id: String,
    job_id: String,
) -> Memory<MemoryUndoOutcomeRecord> {
    let events = client.assistant_memory_writes(&chat_id).await?;
    let event = events
        .iter()
        .find(|event| {
            event
                .undo
                .as_ref()
                .is_some_and(|undo| undo.job_id == job_id)
        })
        .ok_or(MemoryDocumentError::NotUndoable)?;
    Ok(match client.undo_assistant_memory_write(event).await? {
        MemoryUndoOutcome::Deleted => MemoryUndoOutcomeRecord::Deleted,
        MemoryUndoOutcome::Restored => MemoryUndoOutcomeRecord::Restored,
    })
}

impl Shared {
    /// Run one Memory operation on the signed-in client and persist rotated
    /// credentials before answering. A refusal becomes `CoreError::Memory`
    /// with its web code; session errors keep their own case (an expired
    /// session signs out as after every core command).
    async fn memory<T, F>(&self, cancel: CancellationToken, work: F) -> Result<T, CoreError>
    where
        T: Send + 'static,
        F: for<'a> FnOnce(&'a mut Client) -> BoxFuture<'a, Memory<T>> + Send + 'static,
    {
        let outcome = self
            .signed_in(cancel, move |host, _sink, cancel| {
                Box::pin(async move {
                    let result = tokio::select! {
                        biased;
                        () = cancel.cancelled() => Err(MemoryDocumentError::Core(Error::Cancelled)),
                        result = work(host.core_mut().client_mut()) => result,
                    };
                    // Rotated cookies are durable before Swift sees the result.
                    host.core_mut().persist().await?;
                    match result {
                        Err(MemoryDocumentError::Core(error)) => Err(error),
                        other => Ok(other),
                    }
                })
            })
            .await?;
        outcome.map_err(|refusal| CoreError::Memory {
            code: refusal.code().to_owned(),
        })
    }
}

/// Parse the plaintext of a chat's `role: system` message: the notice record
/// when it is a valid `context_entry` event ("Memory saved", "Workflow
/// updated"), else `nil`. Pure; for rendering chat history rows.
#[uniffi::export]
pub fn context_entry_notice(content: String) -> Option<ContextEntryNoticeRecord> {
    parse_context_entry_event(&content)
        .as_ref()
        .map(notice_record)
}

#[uniffi::export]
impl ViewModelCore {
    /// The personal Memories in storage order (later entries were stored
    /// later), read fresh from the encrypted account settings. Sorting and
    /// filtering are view state (web `memoryListEntries.ts`).
    ///
    /// Commands run on the actor one at a time; `cancellation` stops the
    /// call (a cancel after a write was sent may still store it).
    ///
    /// # Errors
    /// `Authentication` when signed out; `Memory` with
    /// `rule_settings_unavailable`, `invalid_rule_document` or
    /// `rule_catalog_limit` for settings the web refuses too; `Offline`,
    /// `Expired`, `Cancelled`.
    pub async fn list_memory_documents(
        &self,
        cancellation: Option<Arc<CoreCancellation>>,
    ) -> Result<Vec<MemoryDocumentRecord>, CoreError> {
        let (shared, token) = (self.shared.clone(), self.detached(cancellation));
        self.run(async move {
            Ok(shared
                .memory(token, |client| {
                    Box::pin(async move {
                        let now = now_ms();
                        let documents = client.personal_memory_documents().await?;
                        Ok(documents.iter().map(|d| document_record(d, now)).collect())
                    })
                })
                .await)
        })
        .await?
    }

    /// One personal Memory by id, read fresh.
    ///
    /// # Errors
    /// `Memory(rule_not_found)` for an unknown id, else as `listMemoryDocuments`.
    pub async fn memory_document(
        &self,
        id: String,
        cancellation: Option<Arc<CoreCancellation>>,
    ) -> Result<MemoryDocumentRecord, CoreError> {
        let (shared, token) = (self.shared.clone(), self.detached(cancellation));
        self.run(async move {
            Ok(shared
                .memory(token, move |client| {
                    Box::pin(async move {
                        let now = now_ms();
                        let documents = client.personal_memory_documents().await?;
                        documents
                            .iter()
                            .find(|d| d.id == id)
                            .map(|d| document_record(d, now))
                            .ok_or(MemoryDocumentError::NotFound)
                    })
                })
                .await)
        })
        .await?
    }

    /// Create a Memory (new id `personal:<uuid>`, `createdAt` and `updatedAt`
    /// set to now) and return it as stored.
    ///
    /// # Errors
    /// `Memory` with `invalid_rule_document` (blank title or body, a field
    /// over its limit, a bad date), `rule_catalog_limit` (24 Memories or
    /// 64,000 characters), `rule_save_failed` (server refused); else as
    /// `listMemoryDocuments`.
    pub async fn create_memory_document(
        &self,
        fields: MemoryFieldsRecord,
        cancellation: Option<Arc<CoreCancellation>>,
    ) -> Result<MemoryDocumentRecord, CoreError> {
        let (shared, token) = (self.shared.clone(), self.detached(cancellation));
        self.run(async move {
            Ok(shared
                .memory(token, move |client| Box::pin(save(client, None, fields)))
                .await)
        })
        .await?
    }

    /// Replace Memory `id` with `fields` (its `createdAt` is kept,
    /// `updatedAt` set to now) and return it as stored. The settings endpoint
    /// has no compare-and-swap token: the last write wins, like on the web.
    ///
    /// # Errors
    /// `Memory(rule_not_found)` for an unknown id, else as `createMemoryDocument`.
    pub async fn update_memory_document(
        &self,
        id: String,
        fields: MemoryFieldsRecord,
        cancellation: Option<Arc<CoreCancellation>>,
    ) -> Result<MemoryDocumentRecord, CoreError> {
        let (shared, token) = (self.shared.clone(), self.detached(cancellation));
        self.run(async move {
            Ok(shared
                .memory(token, move |client| {
                    Box::pin(save(client, Some(id), fields))
                })
                .await)
        })
        .await?
    }

    /// Delete Memory `id` (from the canonical and the legacy settings key).
    ///
    /// # Errors
    /// `Memory(rule_not_found)` for an unknown id, `Memory(rule_save_failed)`
    /// when the server refused, else as `listMemoryDocuments`.
    pub async fn delete_memory_document(
        &self,
        id: String,
        cancellation: Option<Arc<CoreCancellation>>,
    ) -> Result<(), CoreError> {
        let (shared, token) = (self.shared.clone(), self.detached(cancellation));
        self.run(async move {
            Ok(shared
                .memory(token, move |client| {
                    Box::pin(
                        async move { client.delete_personal_memory_document(&id).await.map(drop) },
                    )
                })
                .await)
        })
        .await?
    }

    /// The web expiry sweep: delete every Memory whose `validUntil` passed
    /// (unreadable documents are never deleted); returns how many. Call when
    /// Settings > Memories opens and when the app returns to the foreground.
    ///
    /// # Errors
    /// As `deleteMemoryDocument`; Memories deleted before a failure stay deleted.
    pub async fn delete_expired_memory_documents(
        &self,
        cancellation: Option<Arc<CoreCancellation>>,
    ) -> Result<u32, CoreError> {
        let (shared, token) = (self.shared.clone(), self.detached(cancellation));
        self.run(async move {
            Ok(shared
                .memory(token, |client| {
                    Box::pin(client.delete_expired_personal_memories(now_ms()))
                })
                .await)
        })
        .await?
    }

    /// Opt this device's sends in (or out) to assistant Memory writes. On,
    /// each `send` advertises `memory_write_jobs`; when the assistant saves
    /// a Memory during the turn, the core claims the job, stores the Memory
    /// encrypted and writes the encrypted `context_entry` notice (with Undo
    /// data) into the chat before the turn ends. Off by default; switch it on
    /// only once the chat shows that notice and its Undo. Kept across
    /// sign-ins of this core; applies from the next `send`.
    pub fn set_assistant_memory_writes(&self, enabled: bool) {
        self.shared
            .memory_write_jobs
            .store(enabled, Ordering::SeqCst);
    }

    /// The assistant's Memory writes in `chat_id` that carry Undo data,
    /// oldest first, read from the chat's history on the server.
    ///
    /// # Errors
    /// `Authentication` when signed out; chat read errors (`Forbidden`,
    /// `Offline`, `Crypto`, `Expired`); `Cancelled`.
    pub async fn assistant_memory_writes(
        &self,
        chat_id: String,
        cancellation: Option<Arc<CoreCancellation>>,
    ) -> Result<Vec<ContextEntryNoticeRecord>, CoreError> {
        let (shared, token) = (self.shared.clone(), self.detached(cancellation));
        self.run(async move {
            Ok(shared
                .memory(token, move |client| {
                    Box::pin(async move {
                        let events = client.assistant_memory_writes(&chat_id).await?;
                        Ok(events.iter().map(notice_record).collect())
                    })
                })
                .await)
        })
        .await?
    }

    /// Undo the assistant's Memory write `job_id` of `chat_id`: delete the
    /// Memory it created or restore the document it replaced. Refused when
    /// the Memory was edited since the assistant wrote it.
    ///
    /// # Errors
    /// `Memory` with `rule_not_undoable` (no such undoable write in the
    /// chat), `rule_not_found` (already deleted), `rule_changed` (edited
    /// since), `rule_settings_unavailable` (the previous document cannot be
    /// opened), `rule_save_failed`; else as `assistantMemoryWrites`.
    pub async fn undo_assistant_memory_write(
        &self,
        chat_id: String,
        job_id: String,
        cancellation: Option<Arc<CoreCancellation>>,
    ) -> Result<MemoryUndoOutcomeRecord, CoreError> {
        let (shared, token) = (self.shared.clone(), self.detached(cancellation));
        self.run(async move {
            Ok(shared
                .memory(token, move |client| Box::pin(undo(client, chat_id, job_id)))
                .await)
        })
        .await?
    }
}
