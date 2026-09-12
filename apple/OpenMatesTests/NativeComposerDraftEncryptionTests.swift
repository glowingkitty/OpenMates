// Red tests for the intended encrypted native composer draft service seam.
// Draft persistence must contain Format D ciphertext, never canonical plaintext.
// Legacy UserDefaults drafts migrate only after unlock and decrypt verification.
// Repository, legacy store, and master-key provider dependencies are injectable.
// Production SwiftData coverage verifies the same ciphertext-only contract.

import CryptoKit
import SwiftData
import XCTest
@testable import OpenMates

@MainActor
final class NativeComposerDraftEncryptionTests: XCTestCase {
    private let chatId = "synthetic-chat.composer-fixture.invalid"

    // contract-test: supporting surface=gui.apple assertions=drafts.sync.version-authoritative
    func testExistingPreviewLoadDoesNotPublishDraftDeletedDuringUnlock() async throws {
        let fixture = try loadFixture()
        let key = try masterKey(fixture)
        let target = "synthetic-existing-preview-delete"
        let md = try await CryptoManager.shared.encryptWithMasterKey("Synthetic old draft", masterKey: key)
        let preview = try await CryptoManager.shared.encryptWithMasterKey("Synthetic old preview", masterKey: key)
        let repository = RecordingComposerDraftRepository()
        try await repository.upsert(ComposerDraftRecord(chatId: target, encryptedMarkdown: md,
            encryptedPreview: preview, revision: 1, draftVersion: 7))
        let service = DraftService(repository: repository, legacyStore: RecordingLegacyComposerDraftStore(),
            masterKeyProvider: {
                _ = try await repository.apply(.deletion(chatId: target, version: 8),
                    knownVersion: 7, knownClearedVersion: 0, expectedScope: nil)
                return key
            })
        do { _ = try await service.loadDraft(chatId: target); XCTFail("Deleted snapshot must not publish") }
        catch ComposerDraftError.verificationFailed { }
        XCTAssertTrue(service.currentDraft.isEmpty)
        XCTAssertNil(service.draftPreviews[target])
        let deletions = try await repository.allDeletionVersions()
        XCTAssertEqual(deletions[target], 8)
    }

    // contract-test: supporting surface=gui.apple assertions=drafts.sync.version-authoritative
    func testExistingPreviewLoadDoesNotPublishDraftReplacedDuringUnlock() async throws {
        let fixture = try loadFixture()
        let key = try masterKey(fixture)
        let target = "synthetic-existing-preview-replace"
        let md = try await CryptoManager.shared.encryptWithMasterKey("Synthetic old draft", masterKey: key)
        let preview = try await CryptoManager.shared.encryptWithMasterKey("Synthetic old preview", masterKey: key)
        let replacement = ComposerDraftRecord(chatId: target, encryptedMarkdown: "newer-cipher",
            encryptedPreview: "newer-preview-cipher", revision: 2, draftVersion: 8)
        let repository = RecordingComposerDraftRepository()
        try await repository.upsert(ComposerDraftRecord(chatId: target, encryptedMarkdown: md,
            encryptedPreview: preview, revision: 1, draftVersion: 7))
        let service = DraftService(repository: repository, legacyStore: RecordingLegacyComposerDraftStore(),
            masterKeyProvider: {
                try await repository.upsert(replacement)
                return key
            })
        do { _ = try await service.loadDraft(chatId: target); XCTFail("Replaced snapshot must not publish") }
        catch ComposerDraftError.verificationFailed { }
        XCTAssertTrue(service.currentDraft.isEmpty)
        XCTAssertNil(service.draftPreviews[target])
        let active = await repository.record(chatId: target)
        XCTAssertEqual(active?.encryptedMarkdown, replacement.encryptedMarkdown)
    }

    // contract-test: supporting surface=gui.apple assertions=drafts.persistence.local-first-encrypted,drafts.sync.version-authoritative
    func testPreviewRepairCannotResurrectDraftDeletedDuringUnlock() async throws {
        let fixture = try loadFixture()
        let key = try masterKey(fixture)
        let target = "synthetic-preview-race"
        let ciphertext = try await CryptoManager.shared.encryptWithMasterKey("Synthetic draft", masterKey: key)
        let repository = RecordingComposerDraftRepository()
        try await repository.upsert(ComposerDraftRecord(chatId: target, encryptedMarkdown: ciphertext,
            encryptedPreview: "", revision: 1, draftVersion: 7))
        let service = DraftService(repository: repository, legacyStore: RecordingLegacyComposerDraftStore(),
            masterKeyProvider: {
                _ = try await repository.apply(.deletion(chatId: target, version: 8),
                    knownVersion: 7, knownClearedVersion: 0, expectedScope: nil)
                return key
            })
        do { _ = try await service.loadDraft(chatId: target); XCTFail("A stale preview repair must fail") }
        catch ComposerDraftError.verificationFailed { }
        let active = await repository.record(chatId: target)
        let deletions = try await repository.allDeletionVersions()
        XCTAssertNil(active)
        XCTAssertEqual(deletions[target], 8)
        XCTAssertTrue(service.currentDraft.isEmpty)
        XCTAssertNil(service.draftPreviews[target])
    }

    // contract-test: supporting surface=gui.apple assertions=drafts.persistence.local-first-encrypted,drafts.sync.version-authoritative
    func testPreviewRepairFillsOnlyTheSameActiveDraftWithoutChangingItsVersion() async throws {
        let fixture = try loadFixture()
        let key = try masterKey(fixture)
        let target = "synthetic-preview-current"
        let plaintext = "Synthetic draft preview"
        let ciphertext = try await CryptoManager.shared.encryptWithMasterKey(plaintext, masterKey: key)
        let repository = RecordingComposerDraftRepository()
        try await repository.upsert(ComposerDraftRecord(chatId: target, encryptedMarkdown: ciphertext,
            encryptedPreview: "", revision: 5, draftVersion: 7))
        let service = DraftService(repository: repository, legacyStore: RecordingLegacyComposerDraftStore(),
            masterKeyProvider: { key })
        let loaded = try await service.loadDraft(chatId: target)
        let repaired = await repository.record(chatId: target)
        XCTAssertEqual(loaded?.preview, plaintext)
        XCTAssertEqual(repaired?.draftVersion, 7)
        XCTAssertEqual(repaired?.revision, 5)
        XCTAssertFalse(repaired?.encryptedPreview.isEmpty ?? true)
        XCTAssertEqual(repaired?.encryptedMarkdown, ciphertext)
    }

    // contract-test: supporting surface=gui.apple assertions=drafts.persistence.local-first-encrypted
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

    // contract-test: supporting surface=gui.apple assertions=drafts.persistence.local-first-encrypted
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

    // contract-test: supporting surface=gui.apple assertions=drafts.sync.version-authoritative
    func testOlderSynchronizedDraftVersionCannotOverwriteNewerCiphertext() async throws {
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
            revision: 20,
            draftVersion: 2
        )

        do {
            try await service.saveDraft(
                canonicalMarkdown: "Stale synthetic draft",
                preview: "Stale preview",
                chatId: chatId,
                revision: 21,
                draftVersion: 1
            )
            XCTFail("Expected the stale synchronized draft version to be rejected")
        } catch {
            XCTAssertEqual(error as? ComposerDraftError, .versionConflict)
        }
        let retainedRecord = await repository.record(chatId: chatId)
        let retained = try XCTUnwrap(retainedRecord)
        XCTAssertEqual(retained.draftVersion, 2)
    }

    // contract-test: supporting surface=gui.apple assertions=drafts.boundaries.session-and-incognito
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

    // contract-test: supporting surface=gui.apple assertions=drafts.boundaries.session-and-incognito
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

    // contract-test: supporting surface=gui.apple assertions=drafts.boundaries.session-and-incognito
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

    // contract-test: supporting surface=gui.apple assertions=drafts.boundaries.session-and-incognito
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

    // contract-test: supporting surface=gui.apple assertions=drafts.boundaries.session-and-incognito
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

    // contract-test: supporting surface=gui.apple assertions=drafts.boundaries.session-and-incognito
    func testLogoutRemovesLegacyPlaintextEvenWhenEncryptedRepositoryCleanupFails() async throws {
        let fixture = try loadFixture()
        let repository = RecordingComposerDraftRepository(removeAllError: .syntheticRemoveFailure)
        let legacyStore = RecordingLegacyComposerDraftStore(drafts: [
            chatId: fixture.plaintext.canonicalDraftMarkdown,
        ])
        let service = makeService(
            repository: repository,
            legacyStore: legacyStore,
            masterKey: try masterKey(fixture)
        )

        do {
            try await service.clearAll()
            XCTFail("Expected encrypted repository cleanup to fail")
        } catch RecordingComposerDraftRepository.RepositoryError.syntheticRemoveFailure {
            // The encrypted record can remain recoverable, but plaintext must not.
        }

        let remainingLegacyDrafts = await legacyStore.drafts()
        XCTAssertTrue(remainingLegacyDrafts.isEmpty)
    }

    // contract-test: supporting surface=gui.apple assertions=drafts.persistence.local-first-encrypted
    func testProductionSwiftDataRepositoryPersistsCiphertextOnlyAndSupportsCRUD() async throws {
        let schema = Schema([PersistedComposerDraft.self])
        let configuration = ModelConfiguration(
            "ComposerDraftRepositoryTests",
            schema: schema,
            isStoredInMemoryOnly: true
        )
        let container = try ModelContainer(for: schema, configurations: [configuration])
        let repository = OfflineStore(modelContainer: container)
        let canonicalMarkdown = "Synthetic private draft that must never be stored."
        let initial = ComposerDraftRecord(
            chatId: chatId,
            encryptedMarkdown: "format-d-ciphertext-markdown",
            encryptedPreview: "format-d-ciphertext-preview",
            revision: 13,
            draftVersion: 1
        )

        try await repository.upsert(initial)
        let initialRecord = try await repository.record(chatId: chatId)
        var stored = try XCTUnwrap(initialRecord)
        XCTAssertEqual(stored.encryptedMarkdown, initial.encryptedMarkdown)
        XCTAssertFalse(String(reflecting: stored).contains(canonicalMarkdown))

        stored.encryptedMarkdown = "updated-format-d-ciphertext"
        try await repository.upsert(stored)
        let updatedRecord = try await repository.record(chatId: chatId)
        let updated = try XCTUnwrap(updatedRecord)
        XCTAssertEqual(updated.encryptedMarkdown, "updated-format-d-ciphertext")
        let updatedRecords = try await repository.allRecords()
        XCTAssertEqual(updatedRecords.count, 1)

        let persisted = try container.mainContext.fetch(FetchDescriptor<PersistedComposerDraft>())
        XCTAssertEqual(persisted.count, 1)
        XCTAssertFalse(String(reflecting: persisted).contains(canonicalMarkdown))

        try await repository.remove(chatId: chatId)
        let removedRecord = try await repository.record(chatId: chatId)
        XCTAssertNil(removedRecord)

        try await repository.upsert(initial)
        try await repository.removeAll()
        let remainingRecords = try await repository.allRecords()
        XCTAssertTrue(remainingRecords.isEmpty)
    }

    // contract-test: direct surface=gui.apple assertions=drafts.sync.version-authoritative
    func testClearDraftInvalidatesSaveSuspendedForMasterKey() async throws {
        let repository = RecordingComposerDraftRepository()
        let gate = SuspendedDraftMasterKey()
        let service = DraftService(
            repository: repository,
            legacyStore: RecordingLegacyComposerDraftStore(),
            masterKeyProvider: { await gate.waitForKey() }
        )
        let pendingSave = Task { @MainActor in
            try await service.saveDraft(
                canonicalMarkdown: "Synthetic unsent text", preview: "Synthetic preview",
                chatId: chatId, revision: 1, draftVersion: 0
            )
        }
        await gate.waitUntilRequested()
        try await service.clearDraft(chatId: chatId)
        await gate.release(SymmetricKey(size: .bits256))
        do {
            try await pendingSave.value
            XCTFail("A cleared draft must cancel its earlier pending save")
        } catch is CancellationError {
            // Expected: the delayed crypto continuation cannot restore the draft.
        }
        let record = await repository.record(chatId: chatId)
        XCTAssertNil(record)
        XCTAssertNil(service.draftPreview(chatId: chatId))
        XCTAssertEqual(service.currentDraft, "")
    }

    // contract-test: direct surface=gui.apple assertions=drafts.sync.version-authoritative
    func testLocalSaveAndClearNotifySidebarWithoutReloadingComposer() async throws {
        let repository = RecordingComposerDraftRepository()
        let service = makeService(
            repository: repository, legacyStore: RecordingLegacyComposerDraftStore(),
            masterKey: SymmetricKey(size: .bits256)
        )
        let notification = expectation(description: "Local save and clear publish non-reloading updates")
        notification.expectedFulfillmentCount = 2
        let targetId = "local-origin-fixture.invalid"
        let observer = NotificationCenter.default.addObserver(
            forName: .composerDraftDidChange, object: nil, queue: nil
        ) { event in
            guard event.userInfo?["chatId"] as? String == targetId else { return }
            XCTAssertEqual(event.userInfo?["reloadComposer"] as? Bool, false)
            notification.fulfill()
        }
        defer { NotificationCenter.default.removeObserver(observer) }
        try await service.saveDraft(
            canonicalMarkdown: "Synthetic typing", preview: "Synthetic typing",
            chatId: targetId, revision: 1, draftVersion: 0
        )
        try await service.clearDraft(chatId: targetId)
        await fulfillment(of: [notification], timeout: 1)
    }

    // contract-test: supporting surface=gui.apple assertions=drafts.persistence.local-first-encrypted,drafts.sync.version-authoritative
    func testSwiftDataTombstoneSurvivesNewRepositoryAndDraftOnlyShellRemoval() async throws {
        let schema = Schema([PersistedChat.self, PersistedMessage.self, PersistedEmbed.self,
            PersistedEmbedKey.self, PersistedComposerDraft.self, PendingOfflineAction.self])
        let configuration = ModelConfiguration("DraftTombstoneTests", schema: schema, isStoredInMemoryOnly: true)
        let container = try ModelContainer(for: schema, configurations: [configuration])
        let first = OfflineStore(modelContainer: container)
        let current = ComposerDraftRecord(chatId: "draft-only", encryptedMarkdown: "cipher-seven",
            encryptedPreview: "preview-seven", revision: 1, draftVersion: 7)
        try await first.upsert(current)
        let deletion = try await first.apply(.deletion(chatId: current.chatId, version: 8),
            knownVersion: 7, knownClearedVersion: 0, expectedScope: first.scopeGeneration)
        XCTAssertTrue(deletion.applied)
        let beforeCleanup = try container.mainContext.fetch(FetchDescriptor<PersistedComposerDraft>())
        XCTAssertEqual(beforeCleanup.count, 1)
        XCTAssertEqual(beforeCleanup.first?.isDraftTombstone, true)
        XCTAssertEqual(beforeCleanup.first?.clearedDraftVersion, 8)
        let activeBeforeCleanup = try await first.record(chatId: current.chatId)
        XCTAssertNil(activeBeforeCleanup, "A semantic tombstone is not a live draft or a deleted SwiftData object")
        first.deleteChat(current.chatId, preservingDraftTombstone: true)
        let afterCleanup = try container.mainContext.fetch(FetchDescriptor<PersistedComposerDraft>())
        XCTAssertEqual(afterCleanup.count, 1)
        XCTAssertEqual(afterCleanup.first?.isDraftTombstone, true)
        XCTAssertEqual(afterCleanup.first?.clearedDraftVersion, 8)
        let cold = OfflineStore(modelContainer: container)
        let late = try await cold.apply(.content(current), knownVersion: 0, knownClearedVersion: 0,
                                        expectedScope: cold.scopeGeneration)
        XCTAssertFalse(late.applied)
        XCTAssertEqual(late.record?.clearedDraftVersion, 8)
        let active = try await cold.record(chatId: current.chatId)
        let allActive = try await cold.allRecords()
        XCTAssertNil(active)
        XCTAssertTrue(allActive.isEmpty)
        let rows = try container.mainContext.fetch(FetchDescriptor<PersistedComposerDraft>())
        XCTAssertEqual(rows.count, 1)
        XCTAssertEqual(rows.first?.encryptedMarkdown, "")
        XCTAssertEqual(rows.first?.encryptedPreview, "")
        let newer = ComposerDraftRecord(chatId: current.chatId, encryptedMarkdown: "cipher-nine",
            encryptedPreview: "preview-nine", revision: 2, draftVersion: 9)
        let accepted = try await cold.apply(.content(newer), knownVersion: 0, knownClearedVersion: 0,
                                            expectedScope: cold.scopeGeneration)
        XCTAssertTrue(accepted.applied)
        cold.deleteChat(current.chatId)
        let removed = try container.mainContext.fetch(FetchDescriptor<PersistedComposerDraft>())
        XCTAssertTrue(removed.isEmpty, "An actual chat deletion still removes its entire draft state")
    }

    // contract-test: supporting surface=gui.apple assertions=drafts.persistence.local-first-encrypted
    func testProductionDraftMutationRejectsForeignCacheScopeBeforeWriting() async throws {
        let schema = Schema([PersistedComposerDraft.self])
        let config = ModelConfiguration("DraftScopeTests", schema: schema, isStoredInMemoryOnly: true)
        let container = try ModelContainer(for: schema, configurations: [config])
        let repository = OfflineStore(modelContainer: container)
        let mutation = ComposerDraftMutation.content(ComposerDraftRecord(chatId: "foreign-chat",
            encryptedMarkdown: "cipher", encryptedPreview: "preview", revision: 1, draftVersion: 7))
        do {
            _ = try await repository.apply(mutation, knownVersion: 0, knownClearedVersion: 0, expectedScope: UUID())
            XCTFail("A previous account's request must not write into the current cache")
        } catch OfflineStoreDraftError.staleSession { }
        let records = try await repository.allRecords()
        XCTAssertTrue(records.isEmpty)
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
    private let removeAllError: RepositoryError?
    private let corruptReads: Bool

    init(
        writeError: RepositoryError? = nil,
        removeAllError: RepositoryError? = nil,
        corruptReads: Bool = false
    ) {
        self.writeError = writeError
        self.removeAllError = removeAllError
        self.corruptReads = corruptReads
    }

    func upsert(_ record: ComposerDraftRecord) async throws {
        if let writeError {
            throw writeError
        }
        var resolved = record
        resolved.clearedDraftVersion = max(records[record.chatId]?.clearedDraftVersion ?? 0, record.clearedDraftVersion)
        records[record.chatId] = resolved
    }

    func record(chatId: String) async -> ComposerDraftRecord? {
        guard var record = records[chatId], !record.isDeleted else { return nil }
        if corruptReads {
            record.encryptedPreview = "corrupt-synthetic-ciphertext.invalid"
        }
        return record
    }

    func remove(chatId: String) async throws {
        records.removeValue(forKey: chatId)
    }

    func removeAll() async throws {
        if let removeAllError {
            throw removeAllError
        }
        records.removeAll()
    }

    func allRecords() -> [ComposerDraftRecord] {
        records.values.filter { !$0.isDeleted }
    }

    func allDeletionVersions() async throws -> [String: Int] {
        Dictionary(uniqueKeysWithValues: records.values.filter { $0.isDeleted }
            .map { ($0.chatId, $0.clearedDraftVersion) })
    }
    func apply(_ mutation: ComposerDraftMutation, knownVersion: Int, knownClearedVersion: Int,
               expectedScope: UUID?) async throws -> ComposerDraftApplication {
        if let writeError { throw writeError }
        let result = mutation.applying(to: records[mutation.chatId], knownVersion: knownVersion,
                                      knownClearedVersion: knownClearedVersion)
        if result.applied { records[mutation.chatId] = result.record }
        return result
    }

    enum RepositoryError: Error {
        case syntheticWriteFailure
        case syntheticRemoveFailure
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

// Explicit suspension makes clear-before-save ordering deterministic without sleeps.
private actor SuspendedDraftMasterKey {
    private var keyContinuation: CheckedContinuation<SymmetricKey?, Never>?
    private var requestContinuation: CheckedContinuation<Void, Never>?

    func waitForKey() async -> SymmetricKey? {
        await withCheckedContinuation { continuation in
            keyContinuation = continuation
            requestContinuation?.resume()
            requestContinuation = nil
        }
    }

    func waitUntilRequested() async {
        guard keyContinuation == nil else { return }
        await withCheckedContinuation { requestContinuation = $0 }
    }

    func release(_ key: SymmetricKey) {
        keyContinuation?.resume(returning: key)
        keyContinuation = nil
    }
}
