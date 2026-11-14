//! UniFFI export of the Memory draft diff: which fields an unsaved suggestion
//! changes compared with the saved Memory (banner and "current" quotes of the
//! Memory entry page). Marshals only; the comparison is
//! `client::memory_draft_diff` in the core. Mirrors web `MemoryEntryPage.svelte`;
//! spec `features.app-memories`.
use crate::view_memories::MemoryFieldsRecord;
use openmates_sdk::client::memory_document_fields::MemoryDocumentFields;
use openmates_sdk::client::memory_draft_diff::{MemoryDiffField, diff_memory_draft};

/// A field an unsaved suggestion can change (web test id `memory-draft-diff-{field}`).
#[derive(Clone, Copy, Debug, PartialEq, Eq, uniffi::Enum)]
pub enum MemoryDiffFieldRecord {
    /// `title`.
    Title,
    /// `when_to_use`.
    WhenToUse,
    /// `body`.
    Body,
}

/// One changed field with the saved text the suggestion would replace.
#[derive(Clone, PartialEq, Eq, uniffi::Record)]
pub struct MemoryFieldChangeRecord {
    /// Which field differs.
    pub field: MemoryDiffFieldRecord,
    /// The saved text (empty when the saved field is empty; the UI shows a dash).
    pub current: String,
}

fn core_fields(record: &MemoryFieldsRecord) -> MemoryDocumentFields {
    // No struct literal: the core type wipes itself on drop.
    let mut fields = MemoryDocumentFields::default();
    fields.title = record.title.clone();
    fields.when_to_use = record.when_to_use.clone();
    fields.body = record.body.clone();
    fields
}

/// The fields `draft` changes compared with the `saved` Memory, in display
/// order (title, when to use, text). Empty when nothing differs.
#[uniffi::export]
pub fn diff_memory_draft_fields(
    saved: MemoryFieldsRecord,
    draft: MemoryFieldsRecord,
) -> Vec<MemoryFieldChangeRecord> {
    diff_memory_draft(&core_fields(&saved), &core_fields(&draft))
        .into_iter()
        .map(|change| MemoryFieldChangeRecord {
            field: match change.field {
                MemoryDiffField::Title => MemoryDiffFieldRecord::Title,
                MemoryDiffField::WhenToUse => MemoryDiffFieldRecord::WhenToUse,
                MemoryDiffField::Body => MemoryDiffFieldRecord::Body,
            },
            current: change.current,
        })
        .collect()
}
