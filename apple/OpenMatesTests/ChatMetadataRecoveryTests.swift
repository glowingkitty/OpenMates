import CryptoKit
import XCTest
@testable import OpenMates

@MainActor
final class ChatMetadataRecoveryTests: XCTestCase {
    private func vector() throws -> [String: Any] {
        let root = URL(fileURLWithPath: #filePath).deletingLastPathComponent()
            .deletingLastPathComponent().deletingLastPathComponent()
        let data = try Data(contentsOf: root.appendingPathComponent("backend/tests/fixtures/chat_metadata_recovery_vectors.json"))
        return try XCTUnwrap(JSONSerialization.jsonObject(with: data) as? [String: Any])
    }

    private func key(_ vector: [String: Any]) throws -> SymmetricKey {
        let raw = try XCTUnwrap(vector["chat_key"] as? String)
        return SymmetricKey(data: try XCTUnwrap(Data(base64Encoded: raw + "=")))
    }

    // contract-test: supporting surface=gui.apple assertions=chats.persistence.client-encrypted
    func testPythonVectorOpensWithExactPurposeAndAllMetadata() async throws {
        let v = try vector()
        let jobFields = try XCTUnwrap(v["job"] as? [String: Any])
        let job = try ChatMetadataRecoveryCoordinator.Job(fields: jobFields)
        let identity = try XCTUnwrap(v["identity"] as? [String: Any])
        let owner = try XCTUnwrap(identity["owner_id"] as? String)
        let aad = try ChatMetadataRecoveryCoordinator.associatedData(job: job, ownerId: owner)
        XCTAssertEqual(aad.map { String(format: "%02x", $0) }.joined(), v["associated_data_hex"] as? String)
        let metadata = try await ChatMetadataRecoveryCoordinator.open(sealed: XCTUnwrap(jobFields["sealed_payload"] as? String),
            job: job, ownerId: owner, key: key(v))
        XCTAssertEqual(metadata, ["title": "Synthetic title", "summary": "Synthetic summary", "category": "technology", "icon": "cpu"])
    }

    // contract-test: supporting surface=gui.apple assertions=chats.persistence.client-encrypted
    func testEveryIdentityAndStageBindingRejectsTampering() async throws {
        let v = try vector()
        let original = try XCTUnwrap(v["job"] as? [String: Any])
        let sealed = try XCTUnwrap(original["sealed_payload"] as? String)
        let owner = "11111111-1111-4111-8111-111111111111"
        for (field, value) in [("job_id", "99999999-9999-4999-8999-999999999999" as Any),
                               ("chat_id", "99999999-9999-4999-8999-999999999999" as Any),
                               ("task_id", "99999999-9999-4999-8999-999999999999" as Any),
                               ("stage", "initial" as Any), ("chat_key_version", 2 as Any)] {
            var altered = original; altered[field] = value
            let job = try ChatMetadataRecoveryCoordinator.Job(fields: altered)
            await assertOpenFails { try await ChatMetadataRecoveryCoordinator.open(sealed: sealed, job: job, ownerId: owner, key: key(v)) }
        }
        await assertOpenFails { try await ChatMetadataRecoveryCoordinator.open(sealed: sealed,
            job: ChatMetadataRecoveryCoordinator.Job(fields: original), ownerId: "99999999-9999-4999-8999-999999999999", key: key(v)) }
        await assertOpenFails { try await ChatMetadataRecoveryCoordinator.open(sealed: sealed,
            job: ChatMetadataRecoveryCoordinator.Job(fields: original), ownerId: owner,
            key: SymmetricKey(data: Data(repeating: 7, count: 32))) }
    }

    // contract-test: supporting surface=gui.apple assertions=chats.sync.key-gated-recovery,chats.message.identity-idempotent
    func testMissingShellAndKeyRemainPendingThenPersistOnlyAcceptedMetadata() async throws {
        let v = try vector(), transport = MetadataTestTransport()
        let fields = try XCTUnwrap(v["job"] as? [String: Any]), chatKey = try key(v)
        var shell = false, unlocked = false
        let applied = expectation(description: "accepted metadata applied")
        let coordinator = ChatMetadataRecoveryCoordinator(transport: transport,
            owner: { "11111111-1111-4111-8111-111111111111" }, chatKey: { _ in unlocked ? chatKey : nil },
            wrappedKey: { _ in "wrapped" }, hasShell: { _ in shell }, apply: { _, encrypted, plaintext, metadataV, titleV in
                XCTAssertEqual(Set(encrypted.keys), ["encrypted_chat_summary"])
                XCTAssertEqual(plaintext["encrypted_chat_summary"], "Synthetic summary")
                XCTAssertNil(plaintext["encrypted_title"])
                XCTAssertEqual(metadataV, 2); XCTAssertEqual(titleV, 1)
                applied.fulfill()
            })
        transport.claimFields = fields
        transport.acceptedFields = ["encrypted_chat_summary"]
        coordinator.available(["jobs": [fields]])
        await coordinator.syncReady()
        XCTAssertFalse(transport.sent.contains { $0.type == "metadata_job_claim" })
        shell = true; coordinator.keysChanged()
        XCTAssertFalse(transport.sent.contains { $0.type == "metadata_job_claim" })
        unlocked = true; coordinator.keysChanged()
        await fulfillment(of: [applied], timeout: 5)
        XCTAssertEqual(transport.sent.filter { $0.type == "metadata_job_persist" }.count, 1)
        coordinator.reset()
    }

    // contract-test: supporting surface=gui.apple assertions=chats.message.identity-idempotent
    func testLostAcknowledgementReconnectResendsExactCiphertextWithoutResealing() async throws {
        let v = try vector(), transport = MetadataTestTransport()
        let fields = try XCTUnwrap(v["job"] as? [String: Any]), chatKey = try key(v)
        let failed = expectation(description: "first ACK lost"), applied = expectation(description: "retry committed")
        transport.claimFields = fields; transport.firstPersistFailure = { failed.fulfill() }
        let coordinator = ChatMetadataRecoveryCoordinator(transport: transport,
            owner: { "11111111-1111-4111-8111-111111111111" }, chatKey: { _ in chatKey },
            wrappedKey: { _ in "wrapped" }, hasShell: { _ in true }, apply: { _, _, _, _, _ in applied.fulfill() })
        coordinator.available(["jobs": [fields]]); await coordinator.syncReady()
        await fulfillment(of: [failed], timeout: 5)
        coordinator.disconnected(); await coordinator.connectedToTransport()
        await fulfillment(of: [applied], timeout: 5)
        let writes = transport.sent.filter { $0.type == "metadata_job_persist" }
        XCTAssertEqual(writes.count, 2)
        let firstPayload = try XCTUnwrap(try XCTUnwrap(writes.first).payload, "First persist requires payload")
        let secondPayload = try XCTUnwrap(try XCTUnwrap(writes.dropFirst().first).payload, "Retry persist requires payload")
        XCTAssertEqual(try XCTUnwrap(firstPayload["encrypted_metadata"]?.value as? [String: String]),
                       try XCTUnwrap(secondPayload["encrypted_metadata"]?.value as? [String: String]))
        XCTAssertEqual(transport.sent.filter { $0.type == "metadata_job_claim" }.count, 1)
        coordinator.reset()
    }

    // contract-test: supporting surface=gui.apple assertions=chats.persistence.client-encrypted
    func testAccountSwitchWhileClaimWaitsCannotCommitOldOwnerMetadata() async throws {
        let v = try vector(), transport = MetadataTestTransport()
        let fields = try XCTUnwrap(v["job"] as? [String: Any]), chatKey = try key(v)
        var owner = "11111111-1111-4111-8111-111111111111"
        let waiting = expectation(description: "claim awaiting response")
        transport.claimFields = fields; transport.waitOnClaim = { waiting.fulfill() }
        let coordinator = ChatMetadataRecoveryCoordinator(transport: transport, owner: { owner },
            chatKey: { _ in chatKey }, wrappedKey: { _ in "wrapped" }, hasShell: { _ in true },
            apply: { _, _, _, _, _ in XCTFail("Old owner must not mutate current account") })
        coordinator.available(["jobs": [fields]]); await coordinator.syncReady()
        await fulfillment(of: [waiting], timeout: 5)
        owner = "99999999-9999-4999-8999-999999999999"; coordinator.reset()
        transport.resumeClaim()
        for _ in 0..<20 { await Task.yield() }
        XCTAssertFalse(transport.sent.contains { $0.type == "metadata_job_persist" })
    }

    // contract-test: supporting surface=gui.apple assertions=chats.message.identity-idempotent
    func testSupersededReceiptNeverAppliesProposedTitle() async throws {
        let v = try vector(), transport = MetadataTestTransport()
        let fields = try XCTUnwrap(v["job"] as? [String: Any]), chatKey = try key(v)
        let settled = expectation(description: "superseded receipt")
        transport.claimFields = fields; transport.superseded = true; transport.onPersist = { settled.fulfill() }
        let coordinator = ChatMetadataRecoveryCoordinator(transport: transport,
            owner: { "11111111-1111-4111-8111-111111111111" }, chatKey: { _ in chatKey },
            wrappedKey: { _ in "wrapped" }, hasShell: { _ in true },
            apply: { _, _, _, _, _ in XCTFail("Superseded fields must not apply") })
        coordinator.available(["jobs": [fields]]); await coordinator.syncReady()
        await fulfillment(of: [settled], timeout: 5)
        for _ in 0..<20 { await Task.yield() }
        coordinator.reset()
    }
    // contract-test: supporting surface=gui.apple assertions=chats.message.identity-idempotent,sync.surface.semantic-parity
    func testShippingManagerTokenRefreshRetainsPendingCiphertextButNewSessionClearsIt() async throws {
        let v = try vector(), transport = MetadataTestTransport(), manager = WebSocketManager()
        manager.debugConnectionAttempt = {}
        XCTAssertTrue(manager.advertisedClientCapabilities.isEmpty)
        manager.connect(sessionId: "same-session", token: "old")
        let fields = try XCTUnwrap(v["job"] as? [String: Any]), chatKey = try key(v)
        let failed = expectation(description: "lost ACK"), applied = expectation(description: "reconnect applied")
        transport.claimFields = fields; transport.firstPersistFailure = { failed.fulfill() }
        let coordinator = ChatMetadataRecoveryCoordinator(transport: transport,
            owner: { "11111111-1111-4111-8111-111111111111" }, chatKey: { _ in chatKey },
            wrappedKey: { _ in "wrapped" }, hasShell: { _ in true }, apply: { _, _, _, _, _ in applied.fulfill() })
        manager.configureMetadataRecovery(coordinator)
        XCTAssertEqual(manager.advertisedClientCapabilities, ["chat_metadata_recovery"])
        coordinator.available(["jobs": [fields]]); await coordinator.syncReady()
        await fulfillment(of: [failed], timeout: 5)
        manager.connect(sessionId: "same-session", token: "rotated")
        await manager.debugMetadataTransportOpened()
        await fulfillment(of: [applied], timeout: 5)
        let writes = transport.sent.filter { $0.type == "metadata_job_persist" }
        XCTAssertEqual(writes.count, 2)
        let firstPayload = try XCTUnwrap(try XCTUnwrap(writes.first).payload, "First persist requires payload")
        let secondPayload = try XCTUnwrap(try XCTUnwrap(writes.dropFirst().first).payload, "Retry persist requires payload")
        XCTAssertEqual(try XCTUnwrap(firstPayload["encrypted_metadata"]?.value as? [String: String]),
                       try XCTUnwrap(secondPayload["encrypted_metadata"]?.value as? [String: String]))
        XCTAssertEqual(transport.sent.filter { $0.type == "metadata_job_claim" }.count, 1)
        // A separate session resets a still-pending job before a new transport opens.
        transport.firstPersistFailure = {}
        coordinator.available(["jobs": [fields]])
        for _ in 0..<40 { await Task.yield() }
        manager.connect(sessionId: "different-session", token: "new")
        let before = transport.sent.filter { $0.type == "metadata_job_persist" }.count
        await manager.debugMetadataTransportOpened(); await coordinator.syncReady()
        for _ in 0..<40 { await Task.yield() }
        XCTAssertEqual(transport.sent.filter { $0.type == "metadata_job_persist" }.count, before)
        manager.disconnect()
    }

    // contract-test: supporting surface=gui.apple assertions=chats.sync.key-gated-recovery
    func testStoreShellAndSharedKeyNotificationWakeOnlyPendingIdentity() async throws {
        let v = try vector(), transport = MetadataTestTransport(), store = ChatStore()
        let fields = try XCTUnwrap(v["job"] as? [String: Any]), chatKey = try key(v)
        let chatId = try XCTUnwrap(fields["chat_id"] as? String)
        var unlocked = false
        let applied = expectation(description: "store and key readiness recovered")
        transport.claimFields = fields
        let coordinator = ChatMetadataRecoveryCoordinator(transport: transport,
            owner: { "11111111-1111-4111-8111-111111111111" }, chatKey: { _ in unlocked ? chatKey : nil },
            wrappedKey: { store.chat(for: $0)?.encryptedChatKey }, hasShell: { store.chat(for: $0) != nil },
            apply: { _, _, _, _, _ in applied.fulfill() })
        coordinator.observeReadiness(chatStore: store)
        coordinator.available(["jobs": [fields]]); await coordinator.syncReady()
        store.upsertChat(makeChat(id: "unrelated"))
        for _ in 0..<20 { await Task.yield() }
        XCTAssertFalse(transport.sent.contains { $0.type == "metadata_job_claim" })
        store.upsertChat(makeChat(id: chatId))
        for _ in 0..<20 { await Task.yield() }
        XCTAssertFalse(transport.sent.contains { $0.type == "metadata_job_claim" })
        unlocked = true
        NotificationCenter.default.post(name: .chatKeyMaterialAvailable, object: nil,
            userInfo: ["accountScope": OfflineStore.shared.scopeGeneration])
        await fulfillment(of: [applied], timeout: 5)
        XCTAssertEqual(transport.sent.filter { $0.type == "metadata_job_claim" }.count, 1)
        coordinator.reset()
    }

    // contract-test: supporting surface=gui.apple assertions=chats.persistence.client-encrypted
    func testStoreRejectsEqualRevisionConflictsAndHydratesMatchingCiphertext() {
        let store = ChatStore()
        store.upsertChat(makeChat(id: "chat", encryptedTitle: "current-title", encryptedSummary: "current-summary", revision: 3))
        store.applyRecoveredMetadata(chatId: "chat",
            encrypted: ["encrypted_title": "different-title", "encrypted_chat_summary": "different-summary"],
            plaintext: ["encrypted_title": "Wrong title", "encrypted_chat_summary": "Wrong summary"], metadataVersion: 3, titleVersion: 3)
        XCTAssertNil(store.chat(for: "chat")?.title); XCTAssertNil(store.chat(for: "chat")?.chatSummary)
        XCTAssertEqual(store.chat(for: "chat")?.encryptedTitle, "current-title")
        store.applyRecoveredMetadata(chatId: "chat",
            encrypted: ["encrypted_title": "current-title", "encrypted_chat_summary": "current-summary"],
            plaintext: ["encrypted_title": "Hydrated title", "encrypted_chat_summary": "Hydrated summary"], metadataVersion: 3, titleVersion: 3)
        XCTAssertEqual(store.chat(for: "chat")?.title, "Hydrated title")
        XCTAssertEqual(store.chat(for: "chat")?.chatSummary, "Hydrated summary")
        store.applyRecoveredMetadata(chatId: "chat",
            encrypted: ["encrypted_title": "old-title", "encrypted_chat_summary": "new-summary"],
            plaintext: ["encrypted_title": "Old title", "encrypted_chat_summary": "New summary"], metadataVersion: 4, titleVersion: 2)
        XCTAssertEqual(store.chat(for: "chat")?.title, "Hydrated title")
        XCTAssertEqual(store.chat(for: "chat")?.chatSummary, "New summary")
        XCTAssertEqual(store.chat(for: "chat")?.titleV, 3)
        store.applyRecoveredMetadata(chatId: "chat",
            encrypted: ["encrypted_chat_summary": "old-summary"], plaintext: ["encrypted_chat_summary": "Old summary"],
            metadataVersion: 3, titleVersion: 3)
        XCTAssertEqual(store.chat(for: "chat")?.chatSummary, "New summary")
        XCTAssertEqual(store.chat(for: "chat")?.metadataV, 3)
    }

    // contract-test: supporting surface=gui.apple assertions=chats.persistence.client-encrypted
    func testSummaryOnlyReceiptDoesNotAdvanceUnreceivedTitleRevision() {
        let store = ChatStore()
        store.upsertChat(makeChat(id: "chat", encryptedTitle: "title", revision: 1))
        store.applyRecoveredMetadata(chatId: "chat", encrypted: ["encrypted_chat_summary": "summary"],
            plaintext: ["encrypted_chat_summary": "Summary"], metadataVersion: 4, titleVersion: 3)
        XCTAssertEqual(store.chat(for: "chat")?.titleV, 1)
        XCTAssertEqual(store.chat(for: "chat")?.metadataV, 1)
        XCTAssertEqual(store.chat(for: "chat")?.encryptedTitle, "title")
        store.applyRecoveredMetadata(chatId: "chat", encrypted: ["encrypted_title": "new-title"],
            plaintext: ["encrypted_title": "New title"], metadataVersion: 4, titleVersion: 3)
        XCTAssertEqual(store.chat(for: "chat")?.title, "New title")
        XCTAssertEqual(store.chat(for: "chat")?.titleV, 3)
        XCTAssertEqual(store.chat(for: "chat")?.chatSummary, "Summary")
    }

    // contract-test: supporting surface=gui.apple assertions=chats.persistence.client-encrypted,chats.sync.key-gated-recovery
    func testPartialReceiptKeepsCompleteSyncVersionUntilAuthoritativeMetadataBatch() {
        let store = ChatStore()
        let id = "22222222-2222-4222-8222-222222222222"
        store.upsertChat(makeChat(id: id, revision: 1, encryptedCategory: "old-category", encryptedIcon: "old-icon"))
        store.applyRecoveredMetadata(chatId: id, encrypted: ["encrypted_chat_summary": "accepted-summary"],
            plaintext: ["encrypted_chat_summary": "Accepted summary"], metadataVersion: 4, titleVersion: 3)
        XCTAssertEqual(store.chat(for: id)?.chatSummary, "Accepted summary")
        XCTAssertEqual(store.chat(for: id)?.metadataV, 1)
        XCTAssertEqual(store.makeSyncClientState(clientSuggestionsCount: 0).clientChatVersions[id]?["metadata_v"], 1)
        // Hydration and partial individual/list updates are not complete snapshots.
        store.upsertChat(makeChat(id: id, encryptedSummary: "old-summary", revision: 2))
        store.upsertChats([makeChat(id: id, encryptedSummary: "accepted-summary", revision: 4)])
        XCTAssertEqual(store.chat(for: id)?.chatSummary, "Accepted summary")
        XCTAssertEqual(store.chat(for: id)?.encryptedCategory, "old-category")
        XCTAssertEqual(store.chat(for: id)?.encryptedIcon, "old-icon")
        XCTAssertEqual(store.chat(for: id)?.metadataV, 1)
        store.upsertChats([makeChat(id: id, encryptedSummary: "accepted-summary", revision: 4,
            encryptedCategory: "new-category", encryptedIcon: "new-icon")], authoritativeMetadata: true)
        XCTAssertEqual(store.chat(for: id)?.encryptedCategory, "new-category")
        XCTAssertEqual(store.chat(for: id)?.encryptedIcon, "new-icon")
        XCTAssertEqual(store.chat(for: id)?.chatSummary, "Accepted summary")
        XCTAssertEqual(store.makeSyncClientState(clientSuggestionsCount: 0).clientChatVersions[id]?["metadata_v"], 4)
        store.clearInMemory()
        store.upsertChats([makeChat(id: id, revision: 5)])
        XCTAssertEqual(store.chat(for: id)?.metadataV, 5)
    }

    // contract-test: supporting surface=gui.apple assertions=chats.persistence.client-encrypted,chats.sync.key-gated-recovery
    func testNewerAuthoritativeCiphertextInvalidatesOldPlaintextThenHydratesExactRevision() {
        let store = ChatStore()
        let id = "22222222-2222-4222-8222-222222222222"
        var first = makeChat(id: id, encryptedTitle: "T1", revision: 1,
            encryptedCategory: "C1", encryptedIcon: "I1")
        first.title = "Title one"; first.category = "Category one"; first.icon = "Icon one"
        store.upsertChat(first)
        store.applyRecoveredMetadata(chatId: id, encrypted: ["encrypted_chat_summary": "S4"],
            plaintext: ["encrypted_chat_summary": "Summary four"], metadataVersion: 4, titleVersion: 1)
        let fifth = makeChat(id: id, encryptedTitle: "T5", encryptedSummary: "S5", revision: 5,
            encryptedCategory: "C5", encryptedIcon: "I5")
        store.upsertChats([fifth], authoritativeMetadata: true)
        XCTAssertNil(store.chat(for: id)?.chatSummary)
        XCTAssertNil(store.chat(for: id)?.title)
        XCTAssertNil(store.chat(for: id)?.category)
        XCTAssertNil(store.chat(for: id)?.icon)
        var hydrated = fifth
        hydrated.chatSummary = "Summary five"; hydrated.title = "Title five"
        hydrated.category = "Category five"; hydrated.icon = "Icon five"
        store.upsertChats([hydrated])
        XCTAssertEqual(store.chat(for: id)?.chatSummary, "Summary five")
        XCTAssertEqual(store.chat(for: id)?.title, "Title five")
        XCTAssertEqual(store.chat(for: id)?.category, "Category five")
        XCTAssertEqual(store.chat(for: id)?.icon, "Icon five")
        XCTAssertEqual(store.makeSyncClientState(clientSuggestionsCount: 0).clientChatVersions[id]?["metadata_v"], 5)
        // An older full snapshot cannot replace newer accepted local fields.
        store.upsertChats([first], authoritativeMetadata: true)
        XCTAssertEqual(store.chat(for: id)?.chatSummary, "Summary five")
        XCTAssertEqual(store.chat(for: id)?.category, "Category five")
        XCTAssertEqual(store.chat(for: id)?.icon, "Icon five")
        XCTAssertEqual(store.chat(for: id)?.title, "Title five")
    }

    // contract-test: supporting surface=gui.apple assertions=chats.persistence.client-encrypted,chats.surface.semantic-parity
    func testUnversionedFocusCiphertextChangesAtSameMetadataRevisionThenHydrates() {
        let store = ChatStore()
        let id = "22222222-2222-4222-8222-222222222222"
        var first = makeChat(id: id, revision: 1, encryptedFocus: "F1")
        first.activeFocusId = "Focus A"
        store.upsertChat(first)
        let second = makeChat(id: id, revision: 1, encryptedFocus: "F2")
        store.upsertChats([second], authoritativeMetadata: true)
        XCTAssertEqual(store.chat(for: id)?.encryptedActiveFocusId, "F2")
        XCTAssertNil(store.chat(for: id)?.activeFocusId)
        var hydrated = second; hydrated.activeFocusId = "Focus B"
        store.upsertChats([hydrated])
        XCTAssertEqual(store.chat(for: id)?.activeFocusId, "Focus B")
        XCTAssertEqual(store.chat(for: id)?.metadataV, 1)
    }

    private func assertOpenFails(_ operation: () async throws -> [String: String]) async {
        do { _ = try await operation(); XCTFail("Tampered metadata must not decrypt") }
        catch { }
    }

    private func makeChat(id: String, encryptedTitle: String? = nil,
                          encryptedSummary: String? = nil, revision: Int = 0,
                          encryptedCategory: String? = nil, encryptedIcon: String? = nil,
                          encryptedFocus: String? = nil) -> Chat {
        Chat(id: id, title: nil, lastMessageAt: nil, createdAt: "2026-01-01T00:00:00Z",
            updatedAt: nil, isArchived: nil, isPinned: nil, appId: nil,
            encryptedTitle: encryptedTitle, encryptedCategory: encryptedCategory, encryptedIcon: encryptedIcon,
            encryptedChatSummary: encryptedSummary,
            encryptedChatKey: "wrapped", titleV: revision, metadataV: revision, encryptedActiveFocusId: encryptedFocus)
    }

}

@MainActor
private final class MetadataTestTransport: ChatWebSocketTransport {
    var sent: [WSOutboundMessage] = []
    var claimFields: [String: Any] = [:]
    var acceptedFields: Set<String>?
    var firstPersistFailure: (() -> Void)?
    var waitOnClaim: (() -> Void)?
    var onPersist: (() -> Void)?
    var superseded = false
    private var claimContinuation: CheckedContinuation<Void, Never>?

    func send(_ message: WSOutboundMessage) async throws { sent.append(message) }
    func resumeClaim() { claimContinuation?.resume(); claimContinuation = nil }
    func waitForMessage(_ type: String, timeout: Duration, matching predicate: @escaping ([String: Any]) -> Bool) async throws -> WebSocketResponse {
        throw WebSocketError.messageTimeout
    }
    func sendAndWait(_ message: WSOutboundMessage, responseType: String, timeout: Duration,
                     matching predicate: @escaping ([String: Any]) -> Bool) async throws -> WebSocketResponse {
        sent.append(message)
        var fields = claimFields
        let payload = try XCTUnwrap(message.payload, "Metadata exchange requires payload")
        fields["request_id"] = try XCTUnwrap(payload["request_id"]?.value as? String,
                                            "Metadata exchange requires a request identity")
        if message.type == "metadata_job_claim" {
            if let waitOnClaim { await withCheckedContinuation { claimContinuation = $0; waitOnClaim() } }
            fields["state"] = "AVAILABLE"
        } else {
            if let failure = firstPersistFailure { firstPersistFailure = nil; failure(); throw WebSocketError.messageTimeout }
            fields["state"] = superseded ? "SUPERSEDED" : "TERMINAL"
            let encrypted = try XCTUnwrap(payload["encrypted_metadata"]?.value as? [String: String],
                                          "Persist requires client encrypted metadata")
            fields["encrypted_metadata"] = superseded ? [:] : encrypted.filter { acceptedFields?.contains($0.key) ?? true }
            fields["versions"] = ["metadata_v": 2, "title_v": 1]
            onPersist?()
        }
        XCTAssertTrue(predicate(fields), "Synthetic response must match request correlation")
        return WebSocketResponse(fields: fields, type: responseType)
    }
}
