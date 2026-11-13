// Tests of the composer's encrypted read-back copy (DraftService): it holds
// Format D ciphertext only, never canonical plaintext, restores text and
// attachments, and never publishes a snapshot cleared or replaced meanwhile.
// Repository and master-key provider dependencies are injectable; production
// SwiftData coverage verifies the same ciphertext-only contract. The server
// draft (sync, versions, tombstones) is the core's, see CoreDraftsTests.

import CryptoKit
import SwiftData
import XCTest
@testable import OpenMates

@MainActor
final class NativeComposerDraftEncryptionTests: XCTestCase {
    private let chatId = "synthetic-chat.composer-fixture.invalid"

    // contract-test: supporting surface=gui.apple assertions=drafts.draft-only.presentation,message-input.drafts.preview-persistence
    @MainActor
    func testCachedStructuredTextRemainsLiteralInFormattedSearchRow() throws {
        let literal = #"{"type":"doc","content":[{"type":"paragraph","content":[{"type":"text","text":"Literal nested JSON"}]}]}"#
        let document: [String: Any] = ["type": "doc", "content": [
            ["type": "paragraph", "content": [["type": "text", "text": literal]]]
        ]]
        let serialized = String(decoding: try JSONSerialization.data(withJSONObject: document), as: UTF8.self)
        let service = DraftService(repository: RecordingComposerDraftRepository(),
            masterKeyProvider: { nil }, coreDrafts: CoreDrafts())
        service.seedUITestDraftPreview(chatId: "literal-json-draft", preview: serialized)
        let cached = try XCTUnwrap(service.displayDraftPreviews["literal-json-draft"])
        XCTAssertEqual(cached, literal)
        let chat = Chat(id: "literal-json-draft", title: nil, lastMessageAt: nil,
            createdAt: "2026-10-14T12:00:00Z", updatedAt: nil, isArchived: false, isPinned: false,
            appId: nil, encryptedTitle: nil, encryptedChatKey: nil, messagesV: 0, hasNonEmptyDraft: true)
        // ChatSearchView's production row receives this same formatted cache.
        let row = ChatListRow(chat: chat, suppliedDraftPreview: cached, previewIsFormatted: true)
        XCTAssertEqual(row.formattedDraftPreview, literal)
        XCTAssertNotEqual(ChatDraftPreviewFormatter.format(cached), literal,
            "This fixture detects accidental second parsing of a literal JSON text node")
    }


    // contract-test: supporting surface=gui.apple assertions=drafts.persistence.local-first-encrypted,message-input.drafts.preview-persistence
    func testContentPolicyRejectsEmptyEditorFormatsAndPreservesAttachments() {
        for empty in [" \n\t", "```swift\n  \n```", #"{"type":"doc","content":[{"type":"paragraph"}]}"#, #"{"version":1,"nodes":[{"kind":"hardBreak"}]}"#] {
            XCTAssertFalse(ComposerDraftContentPolicy.hasContent(empty))
        }
        for content in ["#", "*", "---", "** **", "hello", "@mate", "```swift\nlet x = 1\n```", #"{"type":"doc","content":[{"type":"embed","attrs":{"type":"audio"}}]}"#, "```json\n{\"type\":\"image\",\"embed_id\":\"synthetic\"}\n```"] {
            XCTAssertTrue(ComposerDraftContentPolicy.hasContent(content))
        }
    }

    // contract-test: supporting surface=gui.apple assertions=drafts.persistence.local-first-encrypted,drafts.sync.version-authoritative
    func testUnlockedWhitespaceDraftIsRemovedWithoutPublishingBlankPreview() async throws {
        let key = try masterKey(loadFixture())
        let repository = RecordingComposerDraftRepository()
        let markdown = try await CryptoManager.shared.encryptWithMasterKey(" \n\t ", masterKey: key)
        let preview = try await CryptoManager.shared.encryptWithMasterKey(" ", masterKey: key)
        try await repository.upsert(.init(chatId: chatId, encryptedMarkdown: markdown,
            encryptedPreview: preview, revision: 4, draftVersion: 7))
        let service = DraftService(repository: repository, masterKeyProvider: { key }, coreDrafts: CoreDrafts())
        let loaded = try await service.loadDraft(chatId: chatId)
        XCTAssertNil(loaded)
        XCTAssertNil(service.draftPreview(chatId: chatId))
        let cleared = await repository.record(chatId: chatId)
        XCTAssertNil(cleared, "The verified empty copy is removed")
    }

    // contract-test: supporting surface=gui.apple assertions=drafts.persistence.local-first-encrypted,drafts.sync.version-authoritative
    func testEmptySnapshotCleanupRejectsReplacementAndNewerMetadata() {
        let old = ComposerDraftRecord(chatId: chatId, encryptedMarkdown: "old", encryptedPreview: "preview", revision: 1, draftVersion: 7)
        let replacement = ComposerDraftRecord(chatId: chatId, encryptedMarkdown: "new", encryptedPreview: "preview", revision: 2, draftVersion: 7)
        XCTAssertFalse(ComposerDraftMutation.verifiedEmptyDeletion(old).applying(to: replacement).applied)
        XCTAssertFalse(ComposerDraftMutation.verifiedEmptyDeletion(old).applying(to: old, knownVersion: 8).applied)
        let cleared = ComposerDraftMutation.verifiedEmptyDeletion(old).applying(to: old)
        XCTAssertTrue(cleared.applied); XCTAssertEqual(cleared.record?.clearedDraftVersion, 7)
    }

    // contract-test: supporting surface=gui.apple assertions=drafts.persistence.local-first-encrypted,message-input.drafts.preview-persistence
    func testStructuredAttachmentWithBlankPreviewRemainsRecoverable() async throws {
        let key = try masterKey(loadFixture())
        let repository = RecordingComposerDraftRepository()
        let source = "```json\n{\"type\":\"audio\",\"embed_id\":\"synthetic-audio\"}\n```"
        let markdown = try await CryptoManager.shared.encryptWithMasterKey(source, masterKey: key)
        let preview = try await CryptoManager.shared.encryptWithMasterKey(" ", masterKey: key)
        try await repository.upsert(.init(chatId: chatId, encryptedMarkdown: markdown,
            encryptedPreview: preview, revision: 1, draftVersion: 1))
        let service = DraftService(repository: repository, masterKeyProvider: { key }, coreDrafts: CoreDrafts())
        let loaded = try await service.loadDraft(chatId: chatId)
        XCTAssertEqual(loaded?.canonicalMarkdown, source)
        XCTAssertEqual(ChatDraftPreviewFormatter.format(loaded?.preview), "[Audio]")
        XCTAssertEqual(service.displayDraftPreviews[chatId], "[Audio]")
        let retained = await repository.record(chatId: chatId)
        XCTAssertNotNil(retained, "An attachment-only draft is not empty")
    }

    // contract-test: supporting surface=gui.apple assertions=drafts.draft-only.presentation
    func testReconnectHydratesSavedPreviewAfterMasterKeyBecomesAvailable() async throws {
        let key = try masterKey(loadFixture())
        let gate = DraftPreviewUnlockKey()
        let repository = RecordingComposerDraftRepository()
        let markdown = try await CryptoManager.shared.encryptWithMasterKey("Saved synthetic draft", masterKey: key)
        let preview = try await CryptoManager.shared.encryptWithMasterKey("Saved synthetic preview", masterKey: key)
        try await repository.upsert(.init(chatId: chatId, encryptedMarkdown: markdown,
            encryptedPreview: preview, revision: 2, draftVersion: 5))
        let service = DraftService(repository: repository, masterKeyProvider: { await gate.current() }, coreDrafts: CoreDrafts())
        do { _ = try await service.loadDraft(chatId: chatId); XCTFail("Locked draft must stay encrypted") }
        catch ComposerDraftError.masterKeyUnavailable { }
        XCTAssertNil(service.draftPreview(chatId: chatId))
        await gate.unlock(key)
        await service.refreshLocalPreviews()
        XCTAssertEqual(service.draftPreview(chatId: chatId), "Saved synthetic preview")
        XCTAssertEqual(service.displayDraftPreviews[chatId], "Saved synthetic preview")
        let stored = try await repository.record(chatId: chatId)
        XCTAssertEqual(stored?.encryptedMarkdown, markdown)
        XCTAssertEqual(stored?.draftVersion, 5)
    }

    // contract-test: supporting surface=gui.apple assertions=drafts.draft-only.presentation,message-input.drafts.preview-persistence
    func testBlankAttachmentPreviewIsFormattedBeforeLegacyPreviewTruncation() async throws {
        let key = try masterKey(loadFixture())
        let repository = RecordingComposerDraftRepository()
        let source = "```json\n{\"embed_id\":\"" + String(repeating: "a", count: 180) + "\",\"type\":\"image\"}\n```"
        let markdown = try await CryptoManager.shared.encryptWithMasterKey(source, masterKey: key)
        let preview = try await CryptoManager.shared.encryptWithMasterKey(" ", masterKey: key)
        try await repository.upsert(.init(chatId: chatId, encryptedMarkdown: markdown,
            encryptedPreview: preview, revision: 1, draftVersion: 2))
        let service = DraftService(repository: repository, masterKeyProvider: { key }, coreDrafts: CoreDrafts())
        let loaded = try await service.loadDraft(chatId: chatId)
        XCTAssertEqual(loaded?.canonicalMarkdown, source)
        XCTAssertEqual(loaded?.preview, AppStrings.draftEmbedPreviewLabel(type: "image"))
        let stored = try await repository.record(chatId: chatId)
        XCTAssertEqual(stored?.encryptedMarkdown, markdown)
        XCTAssertEqual(stored?.encryptedPreview, preview)
    }

    // contract-test: supporting surface=gui.apple assertions=drafts.persistence.local-first-encrypted,drafts.sync.version-authoritative
    func testFailedDecryptNeverDeletesStoredDraft() async throws {
        let key = try masterKey(loadFixture())
        let repository = RecordingComposerDraftRepository()
        try await repository.upsert(.init(chatId: chatId, encryptedMarkdown: "invalid-ciphertext",
            encryptedPreview: "invalid-preview", revision: 1, draftVersion: 7))
        let service = DraftService(repository: repository, masterKeyProvider: { key }, coreDrafts: CoreDrafts())
        do { _ = try await service.loadDraft(chatId: chatId); XCTFail("Invalid ciphertext must fail") }
        catch ComposerDraftError.verificationFailed { }
        let stored = await repository.record(chatId: chatId)
        XCTAssertEqual(stored?.draftVersion, 7)
    }

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
        let service = DraftService(repository: repository, masterKeyProvider: {
                _ = try await repository.apply(.localDeletion(chatId: target),
                    knownVersion: 0, knownClearedVersion: 0, expectedScope: nil)
                return key
            }, coreDrafts: CoreDrafts())
        do { _ = try await service.loadDraft(chatId: target); XCTFail("Deleted snapshot must not publish") }
        catch ComposerDraftError.verificationFailed { }
        XCTAssertTrue(service.currentDraft.isEmpty)
        XCTAssertNil(service.draftPreviews[target])
        let active = await repository.record(chatId: target)
        XCTAssertNil(active)
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
        let service = DraftService(repository: repository, masterKeyProvider: {
                try await repository.upsert(replacement)
                return key
            }, coreDrafts: CoreDrafts())
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
        let service = DraftService(repository: repository, masterKeyProvider: {
                _ = try await repository.apply(.localDeletion(chatId: target),
                    knownVersion: 0, knownClearedVersion: 0, expectedScope: nil)
                return key
            }, coreDrafts: CoreDrafts())
        do { _ = try await service.loadDraft(chatId: target); XCTFail("A stale preview repair must fail") }
        catch ComposerDraftError.verificationFailed { }
        let active = await repository.record(chatId: target)
        XCTAssertNil(active)
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
        let service = DraftService(repository: repository, masterKeyProvider: { key }, coreDrafts: CoreDrafts())
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
        let service = makeService(
            repository: repository,
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

    // contract-test: direct surface=gui.apple assertions=message-input.recording.lifecycle,message-input.drafts.preview-persistence
    func testRecordingSnapshotIsEncryptedAndRestoresOnlyWhenMarkdownReferencesIt() async throws {
        let fixture = try loadFixture()
        let key = try masterKey(fixture)
        let schema = Schema([PersistedComposerDraft.self])
        let configuration = ModelConfiguration(
            "ComposerRecordingDraftTests",
            schema: schema,
            isStoredInMemoryOnly: true
        )
        let container = try ModelContainer(for: schema, configurations: [configuration])
        let repository = OfflineStore(modelContainer: container)
        let service = DraftService(
            repository: repository,
            masterKeyProvider: { key }, coreDrafts: CoreDrafts()
        )
        let referenced = recordingFixture(
            id: "recording-referenced",
            aesKey: "synthetic-private-aes-key",
            transcript: "Synthetic private transcript"
        )
        let unreferenced = recordingFixture(
            id: "recording-unreferenced",
            aesKey: "synthetic-unused-aes-key",
            transcript: "Synthetic unused transcript"
        )
        let markdown = """
        ```json
        {"type":"audio-recording","embed_id":"recording-referenced"}
        ```
        """

        try await service.saveDraft(
            canonicalMarkdown: markdown,
            preview: "Recording",
            chatId: chatId,
            revision: 21,
            draftVersion: 1,
            recordings: [referenced, unreferenced]
        )

        let storedRecord = try await repository.record(chatId: chatId)
        let stored = try XCTUnwrap(storedRecord)
        let encryptedPayload = try XCTUnwrap(stored.encryptedRecordingPayload)
        XCTAssertNotNil(Data(base64Encoded: encryptedPayload))
        XCTAssertFalse(String(reflecting: stored).contains("synthetic-private-aes-key"))
        XCTAssertFalse(String(reflecting: stored).contains("Synthetic private transcript"))
        let rows = try container.mainContext.fetch(FetchDescriptor<PersistedComposerDraft>())
        let row = try XCTUnwrap(rows.first)
        XCTAssertEqual(row.encryptedRecordingPayload, encryptedPayload)
        XCTAssertFalse(String(reflecting: row).contains("synthetic-private-aes-key"))
        XCTAssertFalse(String(reflecting: row).contains("Synthetic private transcript"))

        let loadedDraft = try await service.loadDraft(chatId: chatId)
        let loaded = try XCTUnwrap(loadedDraft)
        XCTAssertEqual(loaded.attachments.map(\.embedRecord.id), ["recording-referenced"],
                       "Decryption must retain only the attachment referenced by canonical markdown")
        XCTAssertEqual(loaded.attachments.map(\.embedRecord.type), ["audio-recording"],
                       "Encrypted snapshot round trips preserve the public recording type")
        XCTAssertEqual(loaded.recordings.map(\.id), ["recording-referenced"])
        XCTAssertEqual(loaded.recordings.first?.rawData?["aes_key"]?.value as? String,
                       "synthetic-private-aes-key")
        XCTAssertEqual(loaded.recordings.first?.rawData?["transcript_corrected"]?.value as? String,
                       "Synthetic private transcript")
    }

    // contract-test: direct surface=gui.apple assertions=message-input.drafts.preview-persistence,message-input.embeds.gated-send,drafts.persistence.local-first-encrypted
    func testImageAttachmentBytesAreEncryptedAndRestoreAcrossDraftServiceRelaunch() async throws {
        let repository = RecordingComposerDraftRepository()
        let key = SymmetricKey(size: .bits256)
        let imageData = Data("synthetic-private-image-bytes".utf8)
        let record = EmbedRecord(
            id: "draft-image",
            type: "images-image",
            status: .finished,
            data: .raw([
                "app_id": AnyCodable("images"),
                "filename": AnyCodable("draft-photo.png"),
                "title": AnyCodable("draft-photo.png"),
                "type": AnyCodable("image"),
                "status": AnyCodable("finished")
            ]),
            parentEmbedId: nil,
            appId: "images",
            skillId: nil,
            embedIds: nil,
            createdAt: "1760000000"
        )
        let markdown = """
        ```json
        {"type":"image","embed_id":"draft-image"}
        ```
        """
        let savingService = DraftService(
            repository: repository,
            masterKeyProvider: { key }, coreDrafts: CoreDrafts()
        )

        try await savingService.saveDraft(
            canonicalMarkdown: markdown,
            preview: "Photo draft",
            chatId: chatId,
            revision: 22,
            draftVersion: 1,
            attachments: [ComposerDraftAttachment(embedRecord: record, localData: imageData)]
        )

        let storedRecord = await repository.record(chatId: chatId)
        let stored = try XCTUnwrap(storedRecord)
        let encryptedPayload = try XCTUnwrap(stored.encryptedRecordingPayload)
        XCTAssertFalse(encryptedPayload.contains(imageData.base64EncodedString()))
        XCTAssertFalse(String(reflecting: stored).contains("synthetic-private-image-bytes"))

        let relaunchedService = DraftService(
            repository: repository,
            masterKeyProvider: { key }, coreDrafts: CoreDrafts()
        )
        let restoredDraft = try await relaunchedService.loadDraft(chatId: chatId)
        let restored = try XCTUnwrap(restoredDraft)
        XCTAssertEqual(restored.attachments.map { $0.embedRecord.id }, ["draft-image"])
        XCTAssertEqual(restored.attachments.first?.localData, imageData)
        XCTAssertTrue(restored.recordings.isEmpty)
    }

    // contract-test: supporting surface=gui.apple assertions=drafts.persistence.local-first-encrypted
    func testLoadDecryptsRepositoryRecordBackToCanonicalDraft() async throws {
        let fixture = try loadFixture()
        let repository = RecordingComposerDraftRepository()
        let service = makeService(
            repository: repository,
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

    // contract-test: supporting surface=gui.apple assertions=drafts.boundaries.session-and-incognito
    func testClearAndLogoutDeleteEncryptedRecordsWithoutPlaintextFallback() async throws {
        let fixture = try loadFixture()
        let repository = RecordingComposerDraftRepository()
        let service = makeService(
            repository: repository,
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
            encryptedRecordingPayload: "format-d-ciphertext-recording",
            revision: 13,
            draftVersion: 1
        )

        try await repository.upsert(initial)
        let initialRecord = try await repository.record(chatId: chatId)
        var stored = try XCTUnwrap(initialRecord)
        XCTAssertEqual(stored.encryptedMarkdown, initial.encryptedMarkdown)
        XCTAssertEqual(stored.encryptedRecordingPayload, initial.encryptedRecordingPayload)
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
        XCTAssertEqual(persisted.first?.encryptedRecordingPayload, initial.encryptedRecordingPayload)
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
            masterKeyProvider: { await gate.waitForKey() }, coreDrafts: CoreDrafts()
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
            repository: repository,             masterKey: SymmetricKey(size: .bits256)
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

    // contract-test: supporting surface=gui.apple assertions=drafts.persistence.local-first-encrypted
    func testProductionDraftMutationRejectsForeignCacheScopeBeforeWriting() async throws {
        let schema = Schema([PersistedComposerDraft.self])
        let config = ModelConfiguration("DraftScopeTests", schema: schema, isStoredInMemoryOnly: true)
        let container = try ModelContainer(for: schema, configurations: [config])
        let repository = OfflineStore(modelContainer: container)
        let mutation = ComposerDraftMutation.localDeletion(chatId: "foreign-chat")
        do {
            _ = try await repository.apply(mutation, knownVersion: 0, knownClearedVersion: 0, expectedScope: UUID())
            XCTFail("A previous account's request must not write into the current cache")
        } catch OfflineStoreDraftError.staleSession { }
        let records = try await repository.allRecords()
        XCTAssertTrue(records.isEmpty)
    }

    private func makeService(
        repository: RecordingComposerDraftRepository,
        masterKey: SymmetricKey
    ) -> DraftService {
        DraftService(
            repository: repository,
            masterKeyProvider: { masterKey }, coreDrafts: CoreDrafts()
        )
    }

    private func recordingFixture(id: String, aesKey: String, transcript: String) -> EmbedRecord {
        EmbedRecord(
            id: id,
            type: "audio-recording",
            status: .finished,
            data: .raw([
                "aes_key": AnyCodable(aesKey),
                "aes_nonce": AnyCodable("synthetic-nonce"),
                "filename": AnyCodable("synthetic-recording.m4a"),
                "s3_url": AnyCodable("https://media.invalid/synthetic-recording.m4a"),
                "title": AnyCodable(transcript),
                "transcript_corrected": AnyCodable(transcript),
            ]),
            parentEmbedId: nil,
            appId: "audio",
            skillId: "transcribe",
            embedIds: nil,
            createdAt: "1"
        )
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

    func upsert(_ record: ComposerDraftRecord) async throws {
        var resolved = record
        resolved.clearedDraftVersion = max(records[record.chatId]?.clearedDraftVersion ?? 0, record.clearedDraftVersion)
        records[record.chatId] = resolved
    }

    func record(chatId: String) async -> ComposerDraftRecord? {
        guard let record = records[chatId], !record.isDeleted else { return nil }
        return record
    }

    func remove(chatId: String) async throws {
        records.removeValue(forKey: chatId)
    }

    func removeAll() async throws {
        records.removeAll()
    }

    func allRecords() -> [ComposerDraftRecord] {
        records.values.filter { !$0.isDeleted }
    }

    func apply(_ mutation: ComposerDraftMutation, knownVersion: Int, knownClearedVersion: Int,
               expectedScope: UUID?) async throws -> ComposerDraftApplication {
        let result = mutation.applying(to: records[mutation.chatId], knownVersion: knownVersion,
                                      knownClearedVersion: knownClearedVersion)
        if result.applied { records[mutation.chatId] = result.record }
        return result
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

private actor DraftPreviewUnlockKey {
    private var key: SymmetricKey?
    func current() -> SymmetricKey? { key }
    func unlock(_ key: SymmetricKey) { self.key = key }
}
