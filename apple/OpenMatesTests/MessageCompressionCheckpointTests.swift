// Synthetic checkpoint save/receipt and SwiftData serialization fixtures.
// No live sockets, provider inference, or personal account data.
import XCTest
import Foundation
import SwiftData
import CryptoKit
@testable import OpenMates

@MainActor
final class MessageCompressionCheckpointTests: XCTestCase {
    private func event() -> [String: Any] {
        ["chat_id": "synthetic-checkpoint-chat", "summary_message_id": "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
         "summary_content": "synthetic transient summary", "compressed_up_to_timestamp": 42,
         "compressed_up_to_message_id": "m-b", "covered_message_ids": ["m-a", "m-b"],
         // Counts may also include the preceding compression summary.
         "compressed_message_count": 3, "summary_token_estimate": 7]
    }
    private func prepared() throws -> MessageCompressionCheckpointPrepared {
        try .init(proposal: .init(fields: event()), encryptedSummary: "synthetic-exact-ciphertext",
                  requestID: "synthetic-request", keyVersion: 2, createdAt: 100)
    }
    private func receipt(_ payload: [String: Any]) -> [String: Any] {
        var row = payload
        row["id"] = row.removeValue(forKey: "checkpoint_id")
        row.removeValue(forKey: "request_id")
        return ["request_id": payload["request_id"]!, "chat_id": payload["chat_id"]!, "checkpoint": row]
    }

    // contract-test: supporting surface=gui.apple assertions=storage.surface.semantic-parity,storage.integrity.observable-reconcilable
    func testPreparedSavePreservesExactStableBoundaryAndManifest() throws {
        let value = try prepared(), payload = value.payload
        XCTAssertEqual(payload["compressed_up_to_message_id"] as? String, "m-b")
        XCTAssertEqual(payload["covered_message_ids"] as? [String], ["m-a", "m-b"])
        XCTAssertEqual(payload["compressed_message_count"] as? Int, 3)
        XCTAssertEqual(payload["request_id"] as? String, "synthetic-request")
        XCTAssertEqual(payload["encrypted_summary"] as? String, "synthetic-exact-ciphertext")
        XCTAssertNil(payload["summary_content"])
        XCTAssertEqual(try JSONDecoder().decode(MessageCompressionCheckpointPrepared.self,
                                               from: JSONEncoder().encode(value)), value)
    }

    // contract-test: supporting surface=gui.apple assertions=storage.integrity.observable-reconcilable,storage.surface.semantic-parity
    func testReceiptRequiresExactChatCheckpointCiphertextBoundaryManifestAndRejectsWrongOptionalRequest() throws {
        let value = try prepared(), exact = receipt(value.payload)
        XCTAssertNoThrow(try value.validatedReceipt(exact))
        for (key, changed): (String, Any) in [
            ("id", "another-checkpoint"), ("chat_id", "another-chat"),
            ("encrypted_summary", "different-ciphertext"), ("compressed_up_to_timestamp", 41),
            ("compressed_up_to_message_id", "m-a"), ("covered_message_ids", ["m-a"]),
            ("covered_message_ids", ["m-b", "m-a"]), ("covered_message_ids", ["m-a", "m-b", "m-c"]),
            ("compressed_message_count", 2), ("key_version", 1)
        ] {
            var wrong = exact, row = try XCTUnwrap(exact["checkpoint"] as? [String: Any])
            row[key] = changed; wrong["checkpoint"] = row
            XCTAssertThrowsError(try value.validatedReceipt(wrong), key)
        }
        for key in ["request_id", "chat_id"] {
            var wrong = exact; wrong[key] = "another-identity"
            XCTAssertThrowsError(try value.validatedReceipt(wrong))
            wrong.removeValue(forKey: key)
            if key == "request_id" { XCTAssertNoThrow(try value.validatedReceipt(wrong)) }
            else { XCTAssertThrowsError(try value.validatedReceipt(wrong)) }
        }
        for key in ["compressed_up_to_message_id", "covered_message_ids", "encrypted_summary"] {
            var wrong = exact, row = try XCTUnwrap(exact["checkpoint"] as? [String: Any])
            row.removeValue(forKey: key); wrong["checkpoint"] = row
            XCTAssertThrowsError(try value.validatedReceipt(wrong), key)
        }
    }

    // contract-test: supporting surface=gui.apple assertions=storage.privacy.ciphertext-boundary,storage.surface.semantic-parity
    func testActualOfflineStoreKeepsExactMetadataAcrossSavedSupplementalJSONRoundTrip() throws {
        let schema = Schema([PersistedChat.self, PersistedMessage.self, PersistedEmbed.self,
                             PersistedEmbedKey.self, PersistedCodeRunOutput.self, PendingOfflineAction.self])
        let container = try ModelContainer(for: schema, configurations: [ModelConfiguration(
            "Checkpoint-\(UUID().uuidString)", schema: schema, isStoredInMemoryOnly: true)])
        let chat = Chat(id: "synthetic-checkpoint-chat", title: nil, lastMessageAt: nil,
            createdAt: "2026-01-01T00:00:00Z", updatedAt: nil, isArchived: false, isPinned: false,
            appId: "ai", encryptedTitle: nil, encryptedChatKey: nil)
        let context = container.mainContext
        context.insert(PersistedChat(from: chat)); try context.save()
        let store = OfflineStore(modelContainer: container)
        let exact = try prepared()
        var row = try exact.validatedReceipt(receipt(exact.payload))
        row["summary"] = "must not reach disk"; row["summary_content"] = "must not reach disk"
        try store.storeCompressionCheckpoint(row, chatID: chat.id, scope: store.scopeGeneration)
        let rereadContext = ModelContext(container)
        let persisted = try XCTUnwrap(rereadContext.fetch(FetchDescriptor<PersistedChat>()).first)
        let bytes = try XCTUnwrap(persisted.offlineSupplementalContentJSON)
        let fields = try XCTUnwrap(JSONSerialization.jsonObject(with: bytes) as? [String: Any])
        let byChat = try XCTUnwrap(fields["compression_checkpoints_by_chat_id"] as? [String: Any])
        let checkpoints = try XCTUnwrap(byChat[chat.id] as? [[String: Any]])
        XCTAssertEqual(checkpoints.count, 1)
        XCTAssertEqual(checkpoints.first?["compressed_up_to_message_id"] as? String, "m-b")
        XCTAssertEqual(checkpoints.first?["covered_message_ids"] as? [String], ["m-a", "m-b"])
        XCTAssertEqual(checkpoints.first?["encrypted_summary"] as? String, "synthetic-exact-ciphertext")
        XCTAssertNil(checkpoints.first?["summary"]); XCTAssertNil(checkpoints.first?["summary_content"])
        XCTAssertEqual(store.compressionBoundary(chatID: chat.id), 42)
        XCTAssertThrowsError(try store.storeCompressionCheckpoint(row, chatID: "absent-chat", scope: store.scopeGeneration))
        XCTAssertThrowsError(try store.storeCompressionCheckpoint(row, chatID: chat.id, scope: UUID()))
    }

    // contract-test: supporting surface=gui.apple assertions=storage.privacy.ciphertext-boundary,storage.surface.semantic-parity
    func testCheckpointStableBoundaryAndManifestSurvivePhysicalStoreReopen() throws {
        let schema = Schema([PersistedChat.self, PersistedMessage.self, PersistedEmbed.self,
                             PersistedEmbedKey.self, PersistedCodeRunOutput.self, PendingOfflineAction.self])
        // Unique synthetic test storage, independent of every personal account store.
        let directory = FileManager.default.temporaryDirectory.appendingPathComponent("SyntheticCheckpoint-\(UUID().uuidString)", isDirectory: true)
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
        defer { try? FileManager.default.removeItem(at: directory) }
        let url = directory.appendingPathComponent("checkpoint.store")
        let chat = Chat(id: "synthetic-checkpoint-chat", title: nil, lastMessageAt: nil,
            createdAt: "2026-01-01T00:00:00Z", updatedAt: nil, isArchived: false, isPinned: false,
            appId: "ai", encryptedTitle: nil, encryptedChatKey: nil)
        let exact = try prepared()
        func writeSyntheticStore() throws {
            let container = try ModelContainer(for: schema, configurations: [ModelConfiguration(schema: schema, url: url)])
            container.mainContext.insert(PersistedChat(from: chat)); try container.mainContext.save()
            let store = OfflineStore(modelContainer: container)
            try store.storeCompressionCheckpoint(exact.validatedReceipt(receipt(exact.payload)),
                                                chatID: chat.id, scope: store.scopeGeneration)
        }
        try writeSyntheticStore()
        let reopened = try ModelContainer(for: schema, configurations: [ModelConfiguration(schema: schema, url: url)])
        let row = try XCTUnwrap(reopened.mainContext.fetch(FetchDescriptor<PersistedChat>()).first)
        let bytes = try XCTUnwrap(row.offlineSupplementalContentJSON)
        let fields = try XCTUnwrap(JSONSerialization.jsonObject(with: bytes) as? [String: Any])
        let byChat = try XCTUnwrap(fields["compression_checkpoints_by_chat_id"] as? [String: Any])
        let checkpoints = try XCTUnwrap(byChat[chat.id] as? [[String: Any]])
        XCTAssertEqual(checkpoints.first?["compressed_up_to_message_id"] as? String, exact.boundaryMessageID)
        XCTAssertEqual(checkpoints.first?["covered_message_ids"] as? [String], exact.coveredMessageIDs)
        XCTAssertEqual(checkpoints.first?["encrypted_summary"] as? String, exact.encryptedSummary)
        XCTAssertNil(checkpoints.first?["summary"]); XCTAssertNil(checkpoints.first?["summary_content"])
    }

    // contract-test: supporting surface=gui.apple assertions=storage.privacy.ciphertext-boundary,storage.integrity.observable-reconcilable,storage.surface.semantic-parity
    func testEncryptedPendingJournalSurvivesRestartAndExactRetryRetiresItAtomically() async throws {
        let schema = Schema([PersistedChat.self, PersistedMessage.self, PersistedEmbed.self,
                             PersistedEmbedKey.self, PersistedCodeRunOutput.self, PendingOfflineAction.self])
        let directory = FileManager.default.temporaryDirectory.appendingPathComponent("SyntheticCheckpointJournal-\(UUID().uuidString)", isDirectory: true)
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
        defer { try? FileManager.default.removeItem(at: directory) }
        let url = directory.appendingPathComponent("checkpoint.store")
        let chat = Chat(id: "synthetic-checkpoint-chat", title: nil, lastMessageAt: nil,
            createdAt: "2026-01-01T00:00:00Z", updatedAt: nil, isArchived: false, isPinned: false,
            appId: "ai", encryptedTitle: nil, encryptedChatKey: nil)
        let key = SymmetricKey(data: Data(repeating: 0x17, count: 32))
        let binding = MessageCompressionCheckpointJournalBinding(accountID: "synthetic-owner", server: "https://checkpoint.invalid", teamID: "synthetic-team")
        let original = try prepared()
        let sealed = try MessageCompressionCheckpointJournal(binding: binding, prepared: original).sealed(using: key)
        func retainBeforeRestart() throws {
            let container = try ModelContainer(for: schema, configurations: [ModelConfiguration(schema: schema, url: url)])
            container.mainContext.insert(PersistedChat(from: chat)); try container.mainContext.save()
            let store = OfflineStore(modelContainer: container)
            try store.retainCompressionCheckpointJournal(sealed, chatID: chat.id,
                checkpointID: original.checkpointID, scope: store.scopeGeneration)
        }
        try retainBeforeRestart()
        let reopened = try ModelContainer(for: schema, configurations: [ModelConfiguration(schema: schema, url: url)])
        let store = OfflineStore(modelContainer: reopened)
        let record = try XCTUnwrap(store.loadCompressionCheckpointJournals(scope: store.scopeGeneration).first)
        XCTAssertEqual(record.encryptedJournal, sealed)
        let raw = try XCTUnwrap(reopened.mainContext.fetch(FetchDescriptor<PersistedChat>()).first?.checkpointPendingWritesJSON)
        XCTAssertFalse(String(decoding: raw, as: UTF8.self).contains(original.encryptedSummary))
        XCTAssertFalse(String(decoding: raw, as: UTF8.self).contains(binding.accountID))
        let journal = try MessageCompressionCheckpointJournal.open(record.encryptedJournal, using: key, binding: binding,
            chatID: record.chatID, checkpointID: record.checkpointID)
        XCTAssertEqual(journal.prepared, original)
        let writer = MessageCompressionCheckpointWriter(prepared: journal.prepared)
        try await writer.retry(request: { payload, matches in
            XCTAssertEqual(try JSONSerialization.data(withJSONObject: payload, options: [.sortedKeys]),
                           try JSONSerialization.data(withJSONObject: original.payload, options: [.sortedKeys]))
            // Match the actual backend contract: no request_id in the echo.
            var exact = self.receipt(payload); exact.removeValue(forKey: "request_id")
            XCTAssertTrue(matches(exact)); return exact
        }, validate: {}, retain: { candidate in
            XCTAssertEqual(candidate, original)
            try store.retainCompressionCheckpointJournal(sealed, chatID: chat.id,
                checkpointID: original.checkpointID, scope: store.scopeGeneration)
        }, persist: {
            try store.storeCompressionCheckpoint($0, chatID: chat.id, scope: store.scopeGeneration,
                clearingPendingCheckpointID: original.checkpointID)
        })
        XCTAssertTrue(writer.isPersisted)
        XCTAssertNil(try store.loadCompressionCheckpointJournal(chatID: chat.id,
            checkpointID: original.checkpointID, scope: store.scopeGeneration))
        let persisted = try XCTUnwrap(ModelContext(reopened).fetch(FetchDescriptor<PersistedChat>()).first)
        XCTAssertNil(persisted.checkpointPendingWritesJSON)
        XCTAssertNotNil(persisted.offlineSupplementalContentJSON)
    }

    // contract-test: supporting surface=gui.apple assertions=storage.privacy.ciphertext-boundary,storage.integrity.observable-reconcilable
    func testJournalRejectsWrongAccountServerTeamChatCheckpointAndKeyWithoutAdoption() throws {
        let key = SymmetricKey(data: Data(repeating: 0x17, count: 32)), exact = try prepared()
        let binding = MessageCompressionCheckpointJournalBinding(accountID: "synthetic-owner", server: "https://checkpoint.invalid", teamID: "synthetic-team")
        let sealed = try MessageCompressionCheckpointJournal(binding: binding, prepared: exact).sealed(using: key)
        for wrong in [
            MessageCompressionCheckpointJournalBinding(accountID: "other-owner", server: binding.server, teamID: binding.teamID),
            .init(accountID: binding.accountID, server: "https://other.invalid", teamID: binding.teamID),
            .init(accountID: binding.accountID, server: binding.server, teamID: "another-team")
        ] {
            XCTAssertThrowsError(try MessageCompressionCheckpointJournal.open(sealed, using: key, binding: wrong,
                chatID: exact.chatID, checkpointID: exact.checkpointID))
        }
        XCTAssertThrowsError(try MessageCompressionCheckpointJournal.open(sealed, using: key, binding: binding,
            chatID: "another-chat", checkpointID: exact.checkpointID))
        XCTAssertThrowsError(try MessageCompressionCheckpointJournal.open(sealed, using: key, binding: binding,
            chatID: exact.chatID, checkpointID: "another-checkpoint"))
        XCTAssertThrowsError(try MessageCompressionCheckpointJournal.open(sealed,
            using: SymmetricKey(data: Data(repeating: 0x18, count: 32)), binding: binding,
            chatID: exact.chatID, checkpointID: exact.checkpointID))
    }

    // contract-test: supporting surface=gui.apple assertions=storage.integrity.observable-reconcilable,storage.privacy.ciphertext-boundary
    func testJournalWriteFailurePreventsNetworkSendAndRetainsPreparedCandidate() async throws {
        let writer = MessageCompressionCheckpointWriter()
        do {
            try await writer.save(proposal: .init(fields: event()), summary: "synthetic transient summary",
                encrypt: { _ in "synthetic-ciphertext" }, request: { _, _ in XCTFail("Cannot send before durable retain"); return [:] },
                validate: {}, retain: { _ in throw URLError(.cannotWriteToFile) }, persist: { _ in XCTFail("Cannot publish before durable retain") })
            XCTFail("Failed journal must block send")
        } catch is URLError { }
        XCTAssertNotNil(writer.prepared); XCTAssertFalse(writer.isPersisted)
    }

    // contract-test: supporting surface=gui.apple assertions=storage.integrity.observable-reconcilable,storage.surface.semantic-parity
    func testLostReceiptRetryPreservesRequestCiphertextAndCreatedAtWithoutReencryption() async throws {
        let writer = MessageCompressionCheckpointWriter(), proposal = try MessageCompressionCheckpointProposal(fields: event())
        var encrypted = 0, saved = 0, firstPayload: Data?
        do {
            try await writer.save(proposal: proposal, summary: "synthetic transient summary", requestID: "same-request", createdAt: 1,
                encrypt: { _ in encrypted += 1; return "randomized-ciphertext-\(encrypted)" },
                request: { payload, _ in
                    firstPayload = try JSONSerialization.data(withJSONObject: payload, options: [.sortedKeys])
                    throw URLError(.networkConnectionLost)
                }, validate: {}, persist: { _ in saved += 1 })
            XCTFail("Lost receipt cannot mark persisted")
        } catch is URLError { }
        XCTAssertFalse(writer.isPersisted); XCTAssertNotNil(writer.prepared)
        try await writer.retry(request: { payload, matches in
            XCTAssertEqual(try JSONSerialization.data(withJSONObject: payload, options: [.sortedKeys]), firstPayload)
            let exact = self.receipt(payload); XCTAssertTrue(matches(exact)); return exact
        }, validate: {}, persist: { _ in saved += 1 })
        XCTAssertEqual(encrypted, 1); XCTAssertEqual(saved, 1); XCTAssertTrue(writer.isPersisted)
        try await writer.retry(request: { _, _ in XCTFail("Saved retry must not send"); return [:] }, validate: {}, persist: { _ in saved += 1 })
        XCTAssertEqual(saved, 1)
    }

    // contract-test: supporting surface=gui.apple assertions=storage.integrity.observable-reconcilable,storage.surface.semantic-parity
    func testMismatchedReceiptCannotMarkPendingWritePersisted() async throws {
        let writer = MessageCompressionCheckpointWriter()
        var saves = 0
        do {
            try await writer.save(proposal: .init(fields: event()), summary: "synthetic transient summary",
                encrypt: { _ in "synthetic-ciphertext" }, request: { payload, matches in
                    var wrong = self.receipt(payload)
                    var canonical = try XCTUnwrap(wrong["checkpoint"] as? [String: Any])
                    canonical["encrypted_summary"] = "another-candidate-ciphertext"; wrong["checkpoint"] = canonical
                    XCTAssertFalse(matches(wrong)); return wrong
                }, validate: {}, persist: { _ in saves += 1 })
            XCTFail("Mismatched receipt cannot retire a pending write")
        } catch MessageCompressionCheckpointError.invalidReceipt { }
        XCTAssertFalse(writer.isPersisted); XCTAssertNotNil(writer.prepared); XCTAssertEqual(saves, 0)
    }

    // contract-test: supporting surface=gui.apple assertions=storage.integrity.observable-reconcilable,storage.surface.semantic-parity
    func testFailedDiskSaveAndStaleScopeRetainPreparedWriteForExactRetry() async throws {
        let writer = MessageCompressionCheckpointWriter()
        do {
            try await writer.save(proposal: .init(fields: event()), summary: "synthetic transient summary",
                encrypt: { _ in "synthetic-ciphertext" }, request: { payload, _ in self.receipt(payload) },
                validate: {}, persist: { _ in throw URLError(.cannotWriteToFile) })
            XCTFail("Failed local persistence cannot retire pending write")
        } catch is URLError { }
        let original = writer.prepared
        do {
            try await writer.retry(request: { _, _ in XCTFail("Stale scope must not send"); return [:] },
                validate: { throw CancellationError() }, persist: { _ in XCTFail("Stale scope must not save") })
            XCTFail("Stale scope must fail")
        } catch is CancellationError { }
        XCTAssertEqual(writer.prepared, original); XCTAssertFalse(writer.isPersisted)
        try await writer.retry(request: { payload, _ in self.receipt(payload) }, validate: {}, persist: { _ in })
        XCTAssertTrue(writer.isPersisted)
    }

    // contract-test: supporting surface=gui.apple assertions=storage.integrity.observable-reconcilable,storage.surface.semantic-parity
    func testScopeInvalidatedWhileAwaitingExactReceiptCannotPublishRow() async throws {
        let writer = MessageCompressionCheckpointWriter()
        var current = true, saves = 0
        do {
            try await writer.save(proposal: .init(fields: event()), summary: "synthetic transient summary",
                encrypt: { _ in "synthetic-ciphertext" }, request: { payload, _ in
                    current = false; return self.receipt(payload)
                }, validate: { if !current { throw CancellationError() } }, persist: { _ in saves += 1 })
            XCTFail("Late receipt cannot cross invalidated scope")
        } catch is CancellationError { }
        XCTAssertEqual(saves, 0); XCTAssertFalse(writer.isPersisted); XCTAssertNotNil(writer.prepared)
    }

    // contract-test: supporting surface=gui.apple assertions=storage.integrity.observable-reconcilable,storage.surface.semantic-parity
    func testConcurrentDuplicateCannotPrepareSecondRandomizedCiphertext() async throws {
        let writer = MessageCompressionCheckpointWriter(), gate = CheckpointEncryptionGate()
        let proposal = try MessageCompressionCheckpointProposal(fields: event())
        let first = Task { @MainActor in
            try await writer.save(proposal: proposal, summary: "synthetic transient summary",
                encrypt: { _ in await gate.encrypt() }, request: { payload, _ in self.receipt(payload) },
                validate: {}, persist: { _ in })
        }
        await gate.waitUntilEntered()
        do {
            try await writer.save(proposal: proposal, summary: "synthetic transient summary",
                encrypt: { _ in XCTFail("Concurrent duplicate must not encrypt"); return "second" },
                request: { _, _ in XCTFail("Concurrent duplicate must not send"); return [:] }, validate: {}, persist: { _ in })
            XCTFail("Concurrent duplicate must wait for its first prepared save")
        } catch MessageCompressionCheckpointError.writeInProgress { }
        gate.resume()
        try await first.value
        XCTAssertEqual(writer.prepared?.encryptedSummary, "first-randomized-ciphertext")
        XCTAssertTrue(writer.isPersisted)
    }

    // contract-test: supporting surface=gui.apple assertions=storage.integrity.observable-reconcilable,storage.surface.semantic-parity
    func testDuplicateCompletionReusesPreparedIdentityAndRejectsChangedCoverage() async throws {
        let writer = MessageCompressionCheckpointWriter()
        var encryptions = 0, writes = 0
        let proposal = try MessageCompressionCheckpointProposal(fields: event())
        try await writer.save(proposal: proposal, summary: "synthetic transient summary",
            encrypt: { _ in encryptions += 1; return "synthetic-ciphertext" },
            request: { payload, _ in writes += 1; return self.receipt(payload) }, validate: {}, persist: { _ in })
        try await writer.save(proposal: proposal, summary: "synthetic transient summary",
            encrypt: { _ in XCTFail("Duplicate must not encrypt"); return "other" },
            request: { _, _ in XCTFail("Duplicate must not send"); return [:] }, validate: {}, persist: { _ in })
        var changed = event(); changed["compressed_up_to_timestamp"] = 43
        do {
            try await writer.save(proposal: .init(fields: changed), summary: "synthetic transient summary",
                encrypt: { _ in XCTFail("Changed proposal must not encrypt"); return "other" },
                request: { _, _ in XCTFail("Changed proposal must not send"); return [:] }, validate: {}, persist: { _ in })
            XCTFail("Changed coverage must reject")
        } catch MessageCompressionCheckpointError.changedBoundary { }
        XCTAssertEqual(encryptions, 1); XCTAssertEqual(writes, 1)
    }

    // contract-test: supporting surface=gui.apple assertions=storage.surface.semantic-parity,storage.integrity.observable-reconcilable
    func testMalformedManifestFailsWithoutSortingTruncationOrPartialCoverage() throws {
        for manifest: Any in [["m-b", "m-a"], ["m-a", "m-a"], ["m-a"], [], "not-an-array"] {
            var fields = event(); fields["covered_message_ids"] = manifest
            XCTAssertThrowsError(try MessageCompressionCheckpointProposal(fields: fields))
        }
        XCTAssertFalse(MessageCompressionCheckpointProposal.validManifest((0..<20_001).map { String(format: "m%05d", $0) }))
        XCTAssertFalse(MessageCompressionCheckpointProposal.validManifest([String(repeating: "x", count: 256)]))
    }

    // contract-test: supporting surface=gui.apple assertions=storage.surface.semantic-parity,storage.integrity.observable-reconcilable
    func testLegacyMissingCoverageRemainsMissingAndDoesNotInventArchiveEligibility() throws {
        var fields = event()
        fields.removeValue(forKey: "compressed_up_to_message_id"); fields.removeValue(forKey: "covered_message_ids")
        let value = try MessageCompressionCheckpointPrepared(proposal: .init(fields: fields), encryptedSummary: "cipher",
            requestID: "legacy-request", keyVersion: nil, createdAt: 1)
        XCTAssertTrue(value.payload["covered_message_ids"] is NSNull)
        let row = try value.validatedReceipt(receipt(value.payload))
        XCTAssertNil(row["compressed_up_to_message_id"]); XCTAssertNil(row["covered_message_ids"])
        for key in ["compressed_up_to_message_id", "covered_message_ids", "key_version"] {
            var malformed = receipt(value.payload)
            var canonical = try XCTUnwrap(malformed["checkpoint"] as? [String: Any])
            canonical[key] = ["malformed": true]; malformed["checkpoint"] = canonical
            XCTAssertThrowsError(try value.validatedReceipt(malformed), key)
        }
    }
}

@MainActor
private final class CheckpointEncryptionGate {
    private var pending: CheckedContinuation<String, Never>?
    private var entry: CheckedContinuation<Void, Never>?
    func encrypt() async -> String {
        await withCheckedContinuation { continuation in
            pending = continuation
            entry?.resume(); entry = nil
        }
    }
    func waitUntilEntered() async {
        if pending != nil { return }
        await withCheckedContinuation { entry = $0 }
    }
    func resume() { pending?.resume(returning: "first-randomized-ciphertext"); pending = nil }
}
