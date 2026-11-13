// Settings > Memories view model over a fake core store: list sort and search
// (web memoryListEntries.ts), the expiry sweep on open, core refusal codes
// mapped to the web messages, and documents the client cannot parse.
// Synthetic values only; no core, account, network or encryption key.

import Foundation
import XCTest
@testable import OpenMates

@MainActor
private final class FakeMemoryStore: SettingsMemoryDocumentStore {
    var documents: [MemoryDocumentRecord] = []
    var calls: [String] = []
    var listError: Error?
    var writeError: Error?
    var sweepError: Error?
    var lastFields: MemoryFieldsRecord?

    func listMemoryDocuments() async throws -> [MemoryDocumentRecord] {
        calls.append("list")
        if let listError { throw listError }
        return documents
    }

    func createMemoryDocument(fields: MemoryFieldsRecord) async throws -> MemoryDocumentRecord {
        calls.append("create"); lastFields = fields
        if let writeError { throw writeError }
        let record = MemoryDocumentRecord(id: "personal:new", fields: fields, createdAt: 50, updatedAt: 50,
                                          expired: false, document: "# \(fields.title)")
        documents.append(record)
        return record
    }

    func updateMemoryDocument(id: String, fields: MemoryFieldsRecord) async throws -> MemoryDocumentRecord {
        calls.append("update:\(id)"); lastFields = fields
        if let writeError { throw writeError }
        return documents.first { $0.id == id }!
    }

    func deleteMemoryDocument(id: String) async throws {
        calls.append("delete:\(id)")
        if let writeError { throw writeError }
        documents.removeAll { $0.id == id }
    }

    func deleteExpiredMemoryDocuments() async throws -> UInt32 {
        calls.append("sweep")
        if let sweepError { throw sweepError }
        return 0
    }
}

@MainActor
final class SettingsMemoryDocumentsModelTests: XCTestCase {
    private func fields(_ title: String, whenToUse: String = "", appId: String? = nil,
                        loadMode: MemoryLoadModeRecord? = .autoInclude, validUntil: String? = nil) -> MemoryFieldsRecord {
        MemoryFieldsRecord(title: title, description: nil, whenToUse: whenToUse, body: "Body of \(title)",
                           loadMode: loadMode, validFrom: nil, validUntil: validUntil, references: [], appId: appId)
    }

    private func record(_ id: String, _ fields: MemoryFieldsRecord?, created: UInt64?, updated: UInt64?,
                        expired: Bool = false, document: String = "stored") -> MemoryDocumentRecord {
        MemoryDocumentRecord(id: id, fields: fields, createdAt: created, updatedAt: updated, expired: expired, document: document)
    }

    private func rows(_ records: [MemoryDocumentRecord]) -> [SettingsMemoryRow] {
        records.enumerated().map { SettingsMemoryRow(record: $0.element, index: $0.offset) }
    }

    // contract-test: supporting surface=gui.apple assertions=app-memories.surface.semantic-parity
    func testModifiedSortUsesUpdatedThenCreatedAndPutsUntimedLastNewestStoredFirst() {
        let list = rows([
            record("personal:a", fields("Alpha"), created: 10, updated: nil),     // modified 10
            record("personal:b", fields("Bravo"), created: 5, updated: 30),       // modified 30
            record("personal:c", fields("Charlie"), created: nil, updated: nil),  // untimed, stored 3rd
            record("personal:d", fields("Delta"), created: 20, updated: nil),     // modified 20
            record("personal:e", nil, created: nil, updated: nil),                // untimed, stored 5th
        ])
        let sorted = SettingsMemoryDocumentsModel.sorted(list, by: .modified, locale: Locale(identifier: "en"))
        XCTAssertEqual(sorted.map(\.id), ["personal:b", "personal:d", "personal:a", "personal:e", "personal:c"])

        let added = SettingsMemoryDocumentsModel.sorted(list, by: .added, locale: Locale(identifier: "en"))
        XCTAssertEqual(added.map(\.id), ["personal:d", "personal:a", "personal:b", "personal:e", "personal:c"])
    }

    // contract-test: supporting surface=gui.apple assertions=app-memories.surface.semantic-parity
    func testTitleSortAndSearchMatchWebRules() {
        let list = rows([
            record("personal:1", fields("banana"), created: 1, updated: 1),
            record("personal:2", fields("Apple", whenToUse: "When cooking"), created: 2, updated: 2),
            record("personal:3", fields("apple"), created: 3, updated: 3),
        ])
        let sorted = SettingsMemoryDocumentsModel.sorted(list, by: .title, locale: Locale(identifier: "en"))
        XCTAssertEqual(sorted.map(\.id), ["personal:3", "personal:2", "personal:1"], "Equal titles keep newest stored first")
        XCTAssertEqual(SettingsMemoryDocumentsModel.filtered(list, query: "  COOK ").map(\.id), ["personal:2"])
        XCTAssertEqual(SettingsMemoryDocumentsModel.filtered(list, query: "").count, 3)
    }

    // contract-test: supporting surface=gui.apple assertions=app-memories.lifecycle.encrypted-crud
    func testCoreRefusalCodesMapToWebMessages() {
        let message = SettingsMemoryDocumentsModel.message(for:)
        XCTAssertEqual(message(CoreError.Memory(code: "invalid_rule_document")), AppStrings.memoriesInvalidDocument)
        XCTAssertEqual(message(CoreError.Memory(code: "rule_changed")), AppStrings.memoriesDraftConflict)
        XCTAssertEqual(message(CoreError.Memory(code: "rule_not_found")), AppStrings.memoriesNotFound)
        for code in ["rule_exists", "rule_not_undoable", "rule_catalog_limit", "rule_settings_unavailable", "rule_save_failed"] {
            XCTAssertEqual(message(CoreError.Memory(code: code)), AppStrings.memoriesSaveFailed, code)
        }
        XCTAssertEqual(message(CoreError.Offline), AppStrings.memoriesSaveFailed)
        XCTAssertEqual(message(CoreError.Authentication), AppStrings.memoryAuthenticationRequired)
        XCTAssertNil(message(CoreError.Cancelled))
        XCTAssertNil(message(CancellationError()))
    }

    // contract-test: supporting surface=gui.apple assertions=app-memories.expiry.client-enforced,app-memories.lifecycle.encrypted-crud
    func testOpenSweepsExpiredFirstThenListsAndShowsSweepFailure() async {
        let store = FakeMemoryStore()
        store.documents = [record("personal:a", fields("Alpha"), created: 1, updated: 1)]
        let model = SettingsMemoryDocumentsModel(store: store, locale: { Locale(identifier: "en") })
        await model.open()
        XCTAssertEqual(store.calls, ["sweep", "list"])
        XCTAssertEqual(model.state, .loaded)
        XCTAssertNil(model.errorMessage)
        XCTAssertEqual(model.visibleRows.map(\.id), ["personal:a"])

        store.calls = []; store.sweepError = CoreError.Memory(code: "rule_save_failed")
        await model.open()
        XCTAssertEqual(store.calls, ["sweep", "list"], "A failed sweep still loads the list")
        XCTAssertEqual(model.errorMessage, AppStrings.memoriesSaveFailed)
        XCTAssertEqual(model.state, .loaded)

        store.listError = CoreError.Offline
        await model.reload()
        XCTAssertEqual(model.state, .failed)
        XCTAssertEqual(model.errorMessage, AppStrings.memoriesSaveFailed)
    }

    // contract-test: supporting surface=gui.apple assertions=app-memories.compatibility.legacy-documents
    func testUnparseableDocumentIsListedTitledFromItsTextAndDeletable() async {
        let store = FakeMemoryStore()
        store.documents = [
            record("personal:bad", nil, created: nil, updated: nil, document: "\n  Old note heading\nmore"),
            record("personal:ok", fields("Readable"), created: 5, updated: 5),
        ]
        let model = SettingsMemoryDocumentsModel(store: store, locale: { Locale(identifier: "en") })
        await model.open()
        let bad = model.row(for: "bad")
        XCTAssertNotNil(bad, "Deep links may omit the personal: prefix")
        XCTAssertEqual(bad?.isReadable, false)
        XCTAssertEqual(bad?.title, "Old note heading")
        XCTAssertEqual(model.visibleRows.map(\.id), ["personal:ok", "personal:bad"])

        let deleted = await model.delete(id: "personal:bad")
        XCTAssertTrue(deleted)
        XCTAssertEqual(store.calls.suffix(2), ["delete:personal:bad", "list"])
        XCTAssertEqual(model.rows.map(\.id), ["personal:ok"])
    }

    // contract-test: supporting surface=gui.apple assertions=app-memories.lifecycle.encrypted-crud,app-memories.load-modes
    func testSaveSendsDraftFieldsWithWebDateTimesAndReportsRefusal() async {
        let store = FakeMemoryStore()
        let model = SettingsMemoryDocumentsModel(store: store, locale: { Locale(identifier: "en") })
        await model.open()
        var draft = SettingsMemoryDraft()
        draft.title = "Kitchen renovation"; draft.body = "Prefer oak"; draft.loadMode = .askFirst
        draft.validFrom = "2026-11-01"; draft.validUntil = "2026-12-31"
        let created = await model.save(draft, existingID: nil)
        XCTAssertTrue(created)
        XCTAssertEqual(store.lastFields?.validFrom, "2026-11-01T00:00:00.000Z")
        XCTAssertEqual(store.lastFields?.validUntil, "2026-12-31T23:59:59.000Z")
        XCTAssertEqual(store.lastFields?.loadMode, .askFirst)
        XCTAssertEqual(model.savedNotice, AppStrings.memoriesSaved)
        XCTAssertEqual(model.rows.map(\.id), ["personal:new"])

        store.writeError = CoreError.Memory(code: "invalid_rule_document")
        let refused = await model.save(draft, existingID: "personal:new")
        XCTAssertFalse(refused)
        XCTAssertEqual(model.errorMessage, AppStrings.memoriesInvalidDocument)
        XCTAssertFalse(model.saving)
    }

    // contract-test: supporting surface=gui.apple assertions=app-memories.surface.semantic-parity
    func testMemoryPageRoutesMatchWebSettingsPaths() {
        XCTAssertEqual(SettingsMemoryPage(path: "settings_memories"), .list)
        XCTAssertEqual(SettingsMemoryPage(path: "settings_memories/create"), .create)
        XCTAssertEqual(SettingsMemoryPage(path: "settings_memories/personal%3Aabc"), .entry("personal:abc"))
        XCTAssertEqual(SettingsMemoryPage(path: "memories/abc"), .entry("abc"))
        XCTAssertNil(SettingsMemoryPage(path: "memories/create"))
        XCTAssertNil(SettingsMemoryPage(path: "settings_memories/a/b"))
        XCTAssertNil(SettingsMemoryPage(path: "apps/travel/settings_memories/preferred_activities"))
        XCTAssertEqual(SettingsDeepLinkRoute("settings_memories/create").requiresAuthentication, true)
        XCTAssertEqual(SettingsDeepLinkRoute("settings_memories").requiresAuthentication, false)
        XCTAssertTrue(SettingsDeepLinkRoute("memories/abc").hasNativeChild)
    }
}
