// Memory draft diff presentation and the core diff behind it.
// Specification: specifications/features/app-memories/specification.yml
// Assertions: app-memories.suggestions.post-processor

import XCTest
@testable import OpenMates

@MainActor
final class MemoryDraftDiffTests: XCTestCase {
    private func fields(title: String, whenToUse: String, body: String) -> MemoryFieldsRecord {
        MemoryFieldsRecord(
            title: title, description: nil, whenToUse: whenToUse, body: body,
            loadMode: .autoInclude, validFrom: nil, validUntil: nil, references: [], appId: nil)
    }

    // contract-test: supporting surface=gui.apple assertions=app-memories.suggestions.post-processor
    func testCoreDiffListsOnlyChangedFieldsWithSavedText() {
        let saved = fields(title: "Tea", whenToUse: "Evenings", body: "Green tea")
        let draft = fields(title: "Tea time", whenToUse: "Evenings", body: "Green or black tea")
        let changes = diffMemoryDraftFields(saved: saved, draft: draft)
        XCTAssertEqual(changes.map(\.field), [.title, .body])
        XCTAssertEqual(changes.map(\.current), ["Tea", "Green tea"])
        XCTAssertTrue(diffMemoryDraftFields(saved: saved, draft: saved).isEmpty)
    }

    // contract-test: supporting surface=gui.apple assertions=app-memories.suggestions.post-processor
    func testDiffItemUsesWebTestIdAndDashForEmptySavedText() {
        let item = MemoryDraftDiffItem(MemoryFieldChangeRecord(field: .whenToUse, current: ""))
        XCTAssertEqual(item.identifier, "memory-draft-diff-when_to_use")
        XCTAssertEqual(item.quote, "—")
        let body = MemoryDraftDiffItem(MemoryFieldChangeRecord(field: .body, current: "Saved text"))
        XCTAssertEqual(body.identifier, "memory-draft-diff-body")
        XCTAssertEqual(body.quote, "Saved text")
        XCTAssertTrue(body.heading.hasSuffix(AppStrings.memoriesDraftCurrent))
    }

    // contract-test: supporting surface=gui.apple assertions=app-memories.references.embeds
    func testReferencesHintAndBannerStringsResolve() {
        XCTAssertFalse(AppStrings.memoriesReferencesHint.isEmpty)
        XCTAssertNotEqual(AppStrings.memoriesReferencesHint, "memories.references_hint")
        XCTAssertNotEqual(AppStrings.memoriesDraftUnsaved, "memories.draft_unsaved")
    }
}
