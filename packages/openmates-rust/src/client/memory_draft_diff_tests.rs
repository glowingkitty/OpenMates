//! Draft diff: unchanged fields, display order, empty saved text.
use super::memory_document_fields::MemoryDocumentFields;
use super::memory_draft_diff::*;

fn fields(title: &str, when: &str, body: &str) -> MemoryDocumentFields {
    let mut f = MemoryDocumentFields::default();
    f.title = title.into();
    f.when_to_use = when.into();
    f.body = body.into();
    f
}

#[test]
fn identical_fields_have_no_changes() {
    let a = fields("Tea", "", "Green tea");
    assert!(diff_memory_draft(&a, &a.clone()).is_empty());
}

#[test]
fn changed_fields_list_saved_text_in_display_order() {
    let saved = fields("Tea", "Evenings", "Green tea");
    let draft = fields("Tea time", "Evenings", "Green or black tea");
    let changes = diff_memory_draft(&saved, &draft);
    assert_eq!(changes.len(), 2);
    assert!(changes[0].field == MemoryDiffField::Title && changes[0].current == "Tea");
    assert!(changes[1].field == MemoryDiffField::Body && changes[1].current == "Green tea");
}

#[test]
fn cleared_saved_field_reports_empty_current() {
    let saved = fields("Tea", "", "x");
    let draft = fields("Tea", "Mornings", "x");
    let changes = diff_memory_draft(&saved, &draft);
    assert_eq!(changes.len(), 1);
    assert!(changes[0].field == MemoryDiffField::WhenToUse && changes[0].current.is_empty());
    assert_eq!(changes[0].field.as_str(), "when_to_use");
}
