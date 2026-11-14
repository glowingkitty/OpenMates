//! Per-field diff between a saved Memory and an unsaved suggested draft.
//!
//! The Memory entry page shows, for an unsaved suggestion, the current text of
//! every field the draft changes (web `MemoryEntryPage.svelte`, test ids
//! `memory-draft-diff-{field}`). The comparison lives here so every shell
//! shows the same set in the same order. Spec: `features.app-memories`
//! (`app-memories.suggestions.post-processor`).
use super::memory_document_fields::MemoryDocumentFields;

/// A field of a Memory that a suggested draft can change.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum MemoryDiffField {
    /// The title.
    Title,
    /// When the assistant should use the Memory.
    WhenToUse,
    /// The Memory text (body).
    Body,
}

impl MemoryDiffField {
    /// The web test-id suffix of the field (`title`, `when_to_use`, `body`).
    pub fn as_str(self) -> &'static str {
        match self {
            Self::Title => "title",
            Self::WhenToUse => "when_to_use",
            Self::Body => "body",
        }
    }
}

/// One changed field: the saved (current) text the draft would replace.
/// Private text; deliberately not `Debug`.
#[derive(Clone, PartialEq, Eq)]
pub struct MemoryFieldChange {
    /// Which field differs.
    pub field: MemoryDiffField,
    /// The saved text of the field (may be empty).
    pub current: String,
}

/// The fields `draft` changes compared with the `saved` Memory, in display
/// order (title, when to use, text). Equal fields are not listed; comparison is
/// exact, like the web `!==`.
pub fn diff_memory_draft(
    saved: &MemoryDocumentFields,
    draft: &MemoryDocumentFields,
) -> Vec<MemoryFieldChange> {
    let pairs = [
        (MemoryDiffField::Title, &saved.title, &draft.title),
        (
            MemoryDiffField::WhenToUse,
            &saved.when_to_use,
            &draft.when_to_use,
        ),
        (MemoryDiffField::Body, &saved.body, &draft.body),
    ];
    pairs
        .into_iter()
        .filter(|(_, before, after)| before != after)
        .map(|(field, before, _)| MemoryFieldChange {
            field,
            current: before.clone(),
        })
        .collect()
}
