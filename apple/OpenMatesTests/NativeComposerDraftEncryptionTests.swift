// Red tests for the intended encrypted native composer draft service seam.
// Draft persistence must contain Format D ciphertext, never canonical plaintext.
// Legacy UserDefaults drafts migrate only after unlock and decrypt verification.
// Repository, legacy store, and master-key provider dependencies are injectable.
// The production seam intentionally does not exist yet, so this file must not compile.

import CryptoKit
import XCTest
@testable import OpenMates

@MainActor
final class NativeComposerDraftEncryptionTests: XCTestCase {
    private let chatId = "synthetic-chat.composer-fixture.invalid"

    func testSaveAndUpdatePersistOnlyFormatDCiphertext() async throws {
        let fixture = try loadFixture()
        let repository = RecordingComposerDraftRepository()
        let legacyStore = RecordingLegacyComposerDraftStore()
        let service = makeService(
            repository: repository,
            legacyStore: legacyStore,
            masterKey: try masterKey(fixture)
        )

        try await service.saveDraft(
            canonicalMarkdown: fixture.plaintext.canonicalDraftMarkdown,
            preview: fixture.plaintext.draftPreview,
            chatId: chatId,
            revision: 13,
            draftVersion: 1
        )

        let savedRecord = await repository.record(chatId: chatId)
        let saved = try XCTUnwrap(savedRecord)
        XCTAssertEqual(saved.chatId, chatId)
        XCTAssertEqual(saved.revision, 13)
        XCTAssertEqual(saved.draftVersion, 1)
        XCTAssertNotEqual(saved.encryptedMarkdown, fixture.plaintext.canonicalDraftMarkdown)
        XCTAssertNotEqual(saved.encryptedPreview, fixture.plaintext.draftPreview)
        XCTAssertNotNil(Data(base64Encoded: saved.encryptedMarkdown))
        XCTAssertNotNil(Data(base64Encoded: saved.encryptedPreview))
        let decryptedMarkdown = try await CryptoManager.shared.decryptContent(
            base64String: saved.encryptedMarkdown,
            key: try masterKey(fixture)
        )
        XCTAssertEqual(decryptedMarkdown, fixture.plaintext.canonicalDraftMarkdown)

        let updatedMarkdown = fixture.plaintext.canonicalDraftMarkdown + "\n\nSynthetic update at https://composer-fixture.invalid/update."
        try await service.saveDraft(
            canonicalMarkdown: updatedMarkdown,
            preview: "Updated synthetic preview for composer-fixture.invalid.",
            chatId: chatId,
            revision: 14,
            draftVersion: 1
        )
        let updatedRecord = await repository.record(chatId: chatId)
        let updated = try XCTUnwrap(updatedRecord)
        XCTAssertEqual(updated.revision, 14)
        XCTAssertFalse(String(reflecting: updated).contains(updatedMarkdown))
    }

    func testLoadDecryptsRepositoryRecordBackToCanonicalDraft() async throws {
        let fixture = try loadFixture()
        let repository = RecordingComposerDraftRepository()
        let service = makeService(
            repository: repository,
            legacyStore: RecordingLegacyComposerDraftStore(),
            masterKey: try masterKey(fixture)
        )

        try await service.saveDraft(
            canonicalMarkdown: fixture.plaintext.canonicalDraftMarkdown,
            preview: fixture.plaintext.draftPreview,
            chatId: chatId,
            revision: 13,
            draftVersion: 1
        )
        let loadedDraft = try await service.loadDraft(chatId: chatId)
        let loaded = try XCTUnwrap(loadedDraft)

        XCTAssertEqual(loaded.canonicalMarkdown, fixture.plaintext.canonicalDraftMarkdown)
        XCTAssertEqual(loaded.preview, fixture.plaintext.draftPreview)
        XCTAssertEqual(loaded.revision, 13)
        XCTAssertEqual(loaded.draftVersion, 1)
    }

    func testUnlockedMigrationEncryptsVerifiesThenRemovesLegacyPlaintext() async throws {
        let fixture = try loadFixture()
        let repository = RecordingComposerDraftRepository()
        let legacyStore = RecordingLegacyComposerDraftStore(drafts: [
            chatId: fixture.plaintext.canonicalDraftMarkdown,
        ])
        let service = makeService(
            repository: repository,
            legacyStore: legacyStore,
            masterKey: try masterKey(fixture)
        )

        try await service.migrateLegacyDraftsAfterUnlock()

        let migratedRecord = await repository.record(chatId: chatId)
        let migrated = try XCTUnwrap(migratedRecord)
        XCTAssertFalse(migrated.encryptedMarkdown.contains(fixture.plaintext.canonicalDraftMarkdown))
        let decryptedMarkdown = try await CryptoManager.shared.decryptContent(
            base64String: migrated.encryptedMarkdown,
            key: try masterKey(fixture)
        )
        XCTAssertEqual(decryptedMarkdown, fixture.plaintext.canonicalDraftMarkdown)
        let remainingLegacyDrafts = await legacyStore.drafts()
        XCTAssertNil(remainingLegacyDrafts[chatId])
    }

    func testMigrationPreservesNewerEncryptedDraftAndLegacyConflict() async throws {
        let fixture = try loadFixture()
        let repository = RecordingComposerDraftRepository()
        let legacyMarkdown = "Older synthetic legacy draft at https://composer-fixture.invalid/legacy."
        let legacyStore = RecordingLegacyComposerDraftStore(drafts: [chatId: legacyMarkdown])
        let service = makeService(
            repository: repository,
            legacyStore: legacyStore,
            masterKey: try masterKey(fixture)
        )
        try await service.saveDraft(
            canonicalMarkdown: fixture.plaintext.canonicalDraftMarkdown,
            preview: fixture.plaintext.draftPreview,
            chatId: chatId,
            revision: 14,
            draftVersion: 1
        )

        await assertComposerDraftError(.migrationConflict) {
            try await service.migrateLegacyDraftsAfterUnlock()
        }

        let storedRecord = await repository.record(chatId: chatId)
        let encryptedRecord = try XCTUnwrap(storedRecord)
        let encryptedMarkdown = try await CryptoManager.shared.decryptContent(
            base64String: encryptedRecord.encryptedMarkdown,
            key: try masterKey(fixture)
        )
        XCTAssertEqual(encryptedMarkdown, fixture.plaintext.canonicalDraftMarkdown)
        let remainingLegacyDrafts = await legacyStore.drafts()
        XCTAssertEqual(remainingLegacyDrafts[chatId], legacyMarkdown)
    }

    func testUnavailableKeyPreservesLegacyDraftAndReturnsTypedError() async throws {
        let fixture = try loadFixture()
        let repository = RecordingComposerDraftRepository()
        let legacyStore = RecordingLegacyComposerDraftStore(drafts: [
            chatId: fixture.plaintext.canonicalDraftMarkdown,
        ])
        let service = DraftService(
            repository: repository,
            legacyStore: legacyStore,
            masterKeyProvider: { nil }
        )

        await assertComposerDraftError(.masterKeyUnavailable) {
            try await service.migrateLegacyDraftsAfterUnlock()
        }
        let encryptedRecord = await repository.record(chatId: chatId)
        XCTAssertNil(encryptedRecord)
        let remainingLegacyDrafts = await legacyStore.drafts()
        XCTAssertEqual(
            remainingLegacyDrafts[chatId],
            fixture.plaintext.canonicalDraftMarkdown
        )
    }

    func testFailedWriteOrVerificationPreservesRecoverableLegacyPlaintext() async throws {
        let fixture = try loadFixture()
        let legacyStore = RecordingLegacyComposerDraftStore(drafts: [
            chatId: fixture.plaintext.canonicalDraftMarkdown,
        ])
        let failingRepository = RecordingComposerDraftRepository(writeError: .syntheticWriteFailure)
        let writeFailureService = makeService(
            repository: failingRepository,
            legacyStore: legacyStore,
            masterKey: try masterKey(fixture)
        )

        await assertComposerDraftError(.encryptedWriteFailed) {
            try await writeFailureService.migrateLegacyDraftsAfterUnlock()
        }
        var remainingLegacyDrafts = await legacyStore.drafts()
        XCTAssertEqual(remainingLegacyDrafts[chatId], fixture.plaintext.canonicalDraftMarkdown)

        let corruptingRepository = RecordingComposerDraftRepository(corruptReads: true)
        let verificationService = makeService(
            repository: corruptingRepository,
            legacyStore: legacyStore,
            masterKey: try masterKey(fixture)
        )
        await assertComposerDraftError(.verificationFailed) {
            try await verificationService.migrateLegacyDraftsAfterUnlock()
        }
        remainingLegacyDrafts = await legacyStore.drafts()
        XCTAssertEqual(remainingLegacyDrafts[chatId], fixture.plaintext.canonicalDraftMarkdown)
    }

    func testClearAndLogoutDeleteEncryptedRecordsWithoutPlaintextFallback() async throws {
        let fixture = try loadFixture()
        let repository = RecordingComposerDraftRepository()
        let service = makeService(
            repository: repository,
            legacyStore: RecordingLegacyComposerDraftStore(),
            masterKey: try masterKey(fixture)
        )
        let secondChatId = "second-chat.composer-fixture.invalid"

        for id in [chatId, secondChatId] {
            try await service.saveDraft(
                canonicalMarkdown: fixture.plaintext.canonicalDraftMarkdown,
                preview: fixture.plaintext.draftPreview,
                chatId: id,
                revision: 13,
                draftVersion: 1
            )
        }

        try await service.clearDraft(chatId: chatId)
        let clearedRecord = await repository.record(chatId: chatId)
        let retainedRecord = await repository.record(chatId: secondChatId)
        XCTAssertNil(clearedRecord)
        XCTAssertNotNil(retainedRecord)

        try await service.clearAll()
        let remainingRecords = await repository.allRecords()
        XCTAssertTrue(remainingRecords.isEmpty)
        XCTAssertFalse(
            String(reflecting: remainingRecords)
                .contains(fixture.plaintext.canonicalDraftMarkdown)
        )
    }

    private func makeService(
        repository: RecordingComposerDraftRepository,
        legacyStore: RecordingLegacyComposerDraftStore,
        masterKey: SymmetricKey
    ) -> DraftService {
        DraftService(
            repository: repository,
            legacyStore: legacyStore,
            masterKeyProvider: { masterKey }
        )
    }

    private func assertComposerDraftError(
        _ expected: ComposerDraftError,
        operation: () async throws -> Void
    ) async {
        do {
            try await operation()
            XCTFail("Expected ComposerDraftError.\(expected)")
        } catch let error as ComposerDraftError {
            XCTAssertEqual(error, expected)
        } catch {
            XCTFail("Expected ComposerDraftError.\(expected), got \(type(of: error))")
        }
    }

    private func masterKey(_ fixture: DraftEncryptionFixture) throws -> SymmetricKey {
        SymmetricKey(data: try XCTUnwrap(Data(base64Encoded: fixture.keys.masterKeyBase64)))
    }

    private func loadFixture() throws -> DraftEncryptionFixture {
        let repositoryRoot = URL(fileURLWithPath: #filePath)
            .deletingLastPathComponent()
            .deletingLastPathComponent()
            .deletingLastPathComponent()
        let fixtureURL = repositoryRoot
            .appendingPathComponent("shared/composer/fixtures/apple-composer-encryption-v1.json")
        return try JSONDecoder().decode(DraftEncryptionFixture.self, from: Data(contentsOf: fixtureURL))
    }
}

private actor RecordingComposerDraftRepository: ComposerDraftRepository {
    private var records: [String: ComposerDraftRecord] = [:]
    private let writeError: RepositoryError?
    private let corruptReads: Bool

    init(writeError: RepositoryError? = nil, corruptReads: Bool = false) {
        self.writeError = writeError
        self.corruptReads = corruptReads
    }

    func upsert(_ record: ComposerDraftRecord) async throws {
        if let writeError {
            throw writeError
        }
        records[record.chatId] = record
    }

    func record(chatId: String) async -> ComposerDraftRecord? {
        guard var record = records[chatId] else { return nil }
        if corruptReads {
            record.encryptedPreview = "corrupt-synthetic-ciphertext.invalid"
        }
        return record
    }

    func remove(chatId: String) async throws {
        records.removeValue(forKey: chatId)
    }

    func removeAll() async throws {
        records.removeAll()
    }

    func allRecords() -> [ComposerDraftRecord] {
        Array(records.values)
    }

    enum RepositoryError: Error {
        case syntheticWriteFailure
    }
}

private actor RecordingLegacyComposerDraftStore: LegacyComposerDraftStore {
    private var values: [String: String]

    init(drafts: [String: String] = [:]) {
        values = drafts
    }

    func drafts() async -> [String: String] {
        values
    }

    func removeDraft(chatId: String) async {
        values.removeValue(forKey: chatId)
    }
}

private struct DraftEncryptionFixture: Decodable {
    let keys: DraftFixtureKeys
    let plaintext: DraftFixturePlaintext
}

private struct DraftFixtureKeys: Decodable {
    let masterKeyBase64: String

    enum CodingKeys: String, CodingKey {
        case masterKeyBase64 = "master_key_base64"
    }
}

private struct DraftFixturePlaintext: Decodable {
    let canonicalDraftMarkdown: String
    let draftPreview: String

    enum CodingKeys: String, CodingKey {
        case canonicalDraftMarkdown = "canonical_draft_markdown"
        case draftPreview = "draft_preview"
    }
}
