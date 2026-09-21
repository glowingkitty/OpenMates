// Cross-runtime chat completion recovery cryptographic vector tests.
// Values mirror backend/tests/fixtures/chat_completion_recovery_vectors.json.
// The fixture is encoded here because it is outside the Apple test resources.
// All values are deterministic synthetic test material, never production data.
// Exact byte matching guards HKDF, X25519, AES-GCM, base64url, and AAD parity.

import CryptoKit
import XCTest
@testable import OpenMates

final class ChatCompletionRecoveryTests: XCTestCase {
    // contract-test: supporting surface=gui.apple assertions=chats.persistence.client-encrypted
    @MainActor
    func testSavedChatCommitsTheExactPreflightInferencePayload() async throws {
        let transport = RecoveryRecordingTransport(responses: [
            "chat_turn_preflight_ack": [["turn_id": "turn-1", "preflight_id": "preflight-1", "state": "PREPARED"]]
        ])
        let historyKey = SymmetricKey(data: Data(repeating: 9, count: 32))
        let encryptedAnswer = try await CryptoManager.shared.encryptContent("Osaka is a city.", key: historyKey)
        let first = historyFixture(id: "previous-user", role: .user, content: "Tell me about Osaka", timestamp: 1)
        let answer = historyFixture(id: "previous-assistant", role: .assistant, content: nil, encrypted: encryptedAnswer, timestamp: 2)
        let current = historyFixture(id: "message-1", role: .user, content: "Which city?", timestamp: 3)
        let placeholder = historyFixture(id: "pending-assistant", role: .assistant, content: "", timestamp: 4, streaming: true)
        let history = try await ChatSendPipeline().savedChatHistoryPayload(
            [current, answer, first, current, placeholder], chatId: "chat-1", key: historyKey)
        XCTAssertEqual(history.compactMap { $0["message_id"] as? String }, ["previous-user", "previous-assistant", "message-1"])
        XCTAssertEqual(history.compactMap { $0["content"] as? String }, ["Tell me about Osaka", "Osaka is a city.", "Which city?"])
        let inferenceRequest: [String: Any] = [
            "chat_id": "chat-1",
            "message": ["message_id": "message-1", "content": "plaintext"],
            "turn_id": "turn-1",
            "recovery_public_key": "public-key",
            "chat_key_version": 1,
            "message_history": history,
        ]
        let preflight = ChatSendPipeline().savedChatPreflightPayload(
            chatId: "chat-1",
            turnId: "turn-1",
            messageId: "message-1",
            encryptedChatKey: "wrapped-key",
            recoveryPublicKey: "public-key",
            expectedMessagesVersion: 1,
            encryptedUserMessage: ["client_message_id": "message-1"],
            inferenceRequest: inferenceRequest,
            encryptedTitle: nil,
            createdAt: 1
        )
        try await ChatSendPipeline().sendSavedChatTurn(
            turnId: "turn-1",
            preflightPayload: preflight,
            outboundPayload: inferenceRequest,
            transport: transport
        )

        XCTAssertEqual(transport.sentTypes, ["chat_turn_preflight", "chat_message_added"])
        let committed = transport.sentPayloads[1]
        XCTAssertEqual(committed["preflight_id"] as? String, "preflight-1")
        XCTAssertEqual(committed["turn_id"] as? String, "turn-1")
        var committedInference = committed
        committedInference.removeValue(forKey: "protocol_version")
        committedInference.removeValue(forKey: "preflight_id")
        XCTAssertTrue(
            NSDictionary(dictionary: transport.sentPayloads[0]["inference_request"] as? [String: Any] ?? [:])
                .isEqual(to: committedInference)
        )
    }

    // contract-test: supporting surface=gui.apple assertions=chats.persistence.client-encrypted
    @MainActor
    func testSavedHistoryRejectsUndecryptableRequiredContent() async {
        do {
            _ = try await ChatSendPipeline().savedChatHistoryPayload(
                [historyFixture(id: "old-user", role: .user, content: nil, encrypted: "invalid", timestamp: 1)],
                chatId: "chat-1", key: SymmetricKey(data: Data(repeating: 9, count: 32)))
            XCTFail("Do not commit blank historical content when decryption fails")
        } catch { }
    }

    private func historyFixture(
        id: String, role: MessageRole, content: String?, encrypted: String? = nil,
        timestamp: Int, streaming: Bool = false
    ) -> Message {
        Message(id: id, chatId: "chat-1", role: role, content: content,
                encryptedContent: encrypted, createdAt: "2026-01-01T00:00:0\(timestamp)Z",
                updatedAt: nil, appId: nil, isStreaming: streaming, embedRefs: nil)
    }

    // contract-test: supporting surface=gui.apple assertions=chats.persistence.client-encrypted
    @MainActor
    func testNewChatPreflightIncludesRequiredEncryptedTitleMetadata() {
        let payload = ChatSendPipeline().savedChatPreflightPayload(
            chatId: "chat-1",
            turnId: "turn-1",
            messageId: "message-1",
            encryptedChatKey: "wrapped-key",
            recoveryPublicKey: "public-key",
            expectedMessagesVersion: 1,
            encryptedUserMessage: ["client_message_id": "message-1"],
            inferenceRequest: ["chat_id": "chat-1", "turn_id": "turn-1"],
            encryptedTitle: "encrypted-title",
            createdAt: 123
        )

        let metadata = payload["encrypted_chat_metadata"] as? [String: Any]
        XCTAssertEqual(Set(metadata?.keys.map { $0 } ?? []), Set(["encrypted_title", "encrypted_chat_key", "created_at", "updated_at"]))
        XCTAssertEqual(metadata?["encrypted_title"] as? String, "encrypted-title")
        XCTAssertEqual(metadata?["encrypted_chat_key"] as? String, "wrapped-key")
    }

    // contract-test: direct surface=gui.apple assertions=chats.persistence.client-encrypted,chats.message.identity-idempotent
    @MainActor
    func testUntitledExistingConversationDoesNotSendNewChatMetadata() {
        XCTAssertFalse(ChatSendPipeline.shouldIncludeInitialChatMetadata(
            messagesVersion: 2, titleVersion: 0, existingMessageCount: 2))
        XCTAssertFalse(ChatSendPipeline.shouldIncludeInitialChatMetadata(
            messagesVersion: nil, titleVersion: nil, existingMessageCount: 2))
        XCTAssertTrue(ChatSendPipeline.shouldIncludeInitialChatMetadata(
            messagesVersion: 0, titleVersion: 0, existingMessageCount: 0))
    }

    // contract-test: supporting surface=gui.apple assertions=chats.persistence.client-encrypted
    @MainActor
    func testExistingChatPreflightDoesNotRewriteMetadata() {
        let payload = ChatSendPipeline().savedChatPreflightPayload(
            chatId: "chat-1",
            turnId: "turn-1",
            messageId: "message-1",
            encryptedChatKey: "wrapped-key",
            recoveryPublicKey: "public-key",
            expectedMessagesVersion: 7,
            encryptedUserMessage: ["client_message_id": "message-1"],
            inferenceRequest: ["chat_id": "chat-1", "turn_id": "turn-1"],
            encryptedTitle: nil,
            createdAt: 123
        )

        XCTAssertNil(payload["encrypted_chat_metadata"])
        XCTAssertEqual(payload["expected_messages_v"] as? Int, 7)
        XCTAssertEqual(payload["recovery_public_key"] as? String, "public-key")
    }

    // contract-test: supporting surface=gui.apple assertions=chats.sync.key-gated-recovery
    @MainActor
    func testRecoveryAvailabilityClaimsOnlyWithUnlockedKeyAndEligibleDevice() async throws {
        let fixture = try await makeRecoveryFixture()
        await fixture.coordinator.markInitialSyncReady()
        await fixture.coordinator.handleAvailableJobs(fixture.availability)
        XCTAssertEqual(fixture.transport.sentTypes, ["recovery_job_claim", "recovery_job_persist"])
        XCTAssertEqual(fixture.persisted.messages.count, 1)
    }

    // contract-test: supporting surface=gui.apple assertions=chats.completion.recovery-takeover
    @MainActor
    func testClaimedSealedCompletionIsReencryptedPersistedOnceAndAcknowledged() async throws {
        let fixture = try await makeRecoveryFixture()
        await fixture.coordinator.markInitialSyncReady()
        await fixture.coordinator.handleAvailableJobs(fixture.availability)

        let message = try XCTUnwrap(fixture.persisted.messages.first)
        XCTAssertEqual(message.content, "Recovered hello")
        XCTAssertNotNil(message.encryptedContent)
        XCTAssertNotEqual(message.encryptedContent, message.content)
        let persistPayload = fixture.transport.sentPayloads[1]
        XCTAssertEqual(persistPayload["lease_generation"] as? Int, 2)
        XCTAssertEqual(persistPayload["lease_token"] as? String, "synthetic-lease-token")
        XCTAssertEqual(fixture.persisted.committedMessagesVersions, [8])
        let encrypted = try XCTUnwrap(persistPayload["encrypted_assistant_message"] as? [String: Any])
        XCTAssertNil(encrypted["content"])
        XCTAssertNotNil(encrypted["encrypted_content"])
    }

    // contract-test: supporting surface=gui.apple assertions=chats.message.identity-idempotent
    @MainActor
    func testDuplicateRecoveryAvailabilityIsIdempotent() async throws {
        let fixture = try await makeRecoveryFixture()
        await fixture.coordinator.markInitialSyncReady()
        await fixture.coordinator.handleAvailableJobs(fixture.availability)
        await fixture.coordinator.handleAvailableJobs(fixture.availability)
        XCTAssertEqual(fixture.transport.sentTypes.filter { $0 == "recovery_job_claim" }.count, 1)
        XCTAssertEqual(fixture.persisted.messages.count, 1)
    }

    // contract-test: supporting surface=gui.apple assertions=chats.completion.recovery-takeover
    @MainActor
    func testRevokedDeviceDoesNotClaimRecoveryJob() async throws {
        let fixture = try await makeRecoveryFixture(isEligible: false)
        await fixture.coordinator.handleAvailableJobs(fixture.availability)
        XCTAssertTrue(fixture.transport.sentTypes.isEmpty)
    }

    // contract-test: supporting surface=gui.apple assertions=chats.sync.key-gated-recovery
    @MainActor
    func testLockedChatKeyDoesNotClaimRecoveryJob() async throws {
        let fixture = try await makeRecoveryFixture(hasKey: false)
        await fixture.coordinator.markInitialSyncReady()
        await fixture.coordinator.handleAvailableJobs(fixture.availability)
        XCTAssertTrue(fixture.transport.sentTypes.isEmpty)
    }

    // contract-test: supporting surface=gui.apple assertions=chats.sync.key-gated-recovery
    @MainActor
    func testRecoveryReceivedBeforeInitialSyncQueuesUntilReady() async throws {
        let fixture = try await makeRecoveryFixture()
        await fixture.coordinator.handleAvailableJobs(fixture.availability)
        XCTAssertTrue(fixture.transport.sentTypes.isEmpty)

        await fixture.coordinator.markInitialSyncReady()
        XCTAssertEqual(fixture.transport.sentTypes, ["recovery_job_claim", "recovery_job_persist"])
    }

    // contract-test: supporting surface=gui.apple assertions=chats.completion.recovery-takeover
    @MainActor
    func testTerminalRecoveryStreamRoutesToCoordinatorPersistence() async throws {
        let fixture = try await makeRecoveryFixture()
        fixture.coordinator.handleTerminalStream([
            "is_final_chunk": true,
            "recovery_protocol_version": 1,
            "recovery_job_id": RecoveryVector.shared.jobId,
            "chat_id": RecoveryVector.shared.chatId,
            "message_id": RecoveryVector.shared.assistantMessageId,
        ])
        XCTAssertTrue(fixture.coordinator.ownsRecoveryPersistence(messageId: RecoveryVector.shared.assistantMessageId))
        XCTAssertTrue(fixture.transport.sentTypes.isEmpty)

        await fixture.coordinator.markInitialSyncReady()
        XCTAssertEqual(fixture.transport.sentTypes, ["recovery_job_claim", "recovery_job_persist"])
    }

    // contract-test: supporting surface=gui.apple assertions=chats.persistence.client-encrypted,chats.message.identity-idempotent
    @MainActor
    func testOriginRecoveryAcknowledgementUpgradesTheExistingPlaintextRow() async throws {
        let fixture = try await makeRecoveryFixture()
        let streamed = streamedRecoveryFixtureMessage()
        fixture.persisted.messages = [streamed]
        fixture.coordinator.handleTerminalStream(terminalRecoveryFixturePayload())
        await fixture.coordinator.markInitialSyncReady()

        XCTAssertEqual(fixture.transport.sentTypes, ["recovery_job_claim", "recovery_job_persist"])
        XCTAssertEqual(fixture.persisted.messages.count, 1)
        XCTAssertEqual(fixture.persisted.upsertCount, 1)
        let saved = try XCTUnwrap(fixture.persisted.messages.first)
        let encrypted = try XCTUnwrap(saved.encryptedContent)
        let key = SymmetricKey(data: try decodeBase64URL(RecoveryVector.shared.chatKey))
        let restored = try await CryptoManager.shared.decryptContent(base64String: encrypted, key: key)
        XCTAssertEqual(restored, "Recovered hello")
        XCTAssertEqual(saved.id, streamed.id)
        XCTAssertEqual(saved.createdAt, streamed.createdAt, "Acknowledgement must not reorder an already rendered response")
        XCTAssertEqual(saved.thinkingContent, streamed.thinkingContent)
        XCTAssertNotNil(saved.encryptedSenderName)
        XCTAssertEqual(fixture.persisted.committedMessagesVersions, [8])
    }

    // contract-test: supporting surface=gui.apple assertions=chats.completion.recovery-takeover,chats.persistence.client-encrypted,chats.message.identity-idempotent
    @MainActor
    func testColdRecoveryRepairsPlaintextAfterOriginPersistenceReceiptWasInterrupted() async throws {
        let origin = try await makeRecoveryFixture(persistReceiptInterrupted: true)
        origin.persisted.messages = [streamedRecoveryFixtureMessage()]
        origin.coordinator.handleTerminalStream(terminalRecoveryFixturePayload())
        await origin.coordinator.markInitialSyncReady()
        XCTAssertEqual(origin.transport.sentTypes, ["recovery_job_claim", "recovery_job_persist"])
        XCTAssertEqual(origin.persisted.upsertCount, 0, "An interrupted receipt cannot be marked committed")
        XCTAssertTrue(origin.persisted.committedMessagesVersions.isEmpty)
        XCTAssertNil(origin.persisted.messages.first?.encryptedContent)
        origin.coordinator.reset()

        // A fresh runtime restores the plaintext row from disk. It must still
        // claim an available job, then replace that row after the encrypted ack.
        let cold = try await makeRecoveryFixture()
        cold.persisted.messages = origin.persisted.messages
        await cold.coordinator.markInitialSyncReady()
        await cold.coordinator.handleAvailableJobs(cold.availability)
        await cold.coordinator.handleAvailableJobs(cold.availability)
        XCTAssertEqual(cold.transport.sentTypes, ["recovery_job_claim", "recovery_job_persist"])
        XCTAssertEqual(cold.persisted.messages.count, 1)
        XCTAssertEqual(cold.persisted.upsertCount, 1)
        XCTAssertNotNil(cold.persisted.messages.first?.encryptedContent)
        XCTAssertEqual(cold.persisted.committedMessagesVersions, [8])
    }

    // contract-test: supporting surface=gui.apple assertions=chats.message.identity-idempotent
    @MainActor
    func testAvailableRecoverySkipsAnAlreadyEncryptedAssistant() async throws {
        let fixture = try await makeRecoveryFixture()
        let encrypted = try await CryptoManager.shared.encryptContent("Recovered hello",
            key: SymmetricKey(data: try decodeBase64URL(RecoveryVector.shared.chatKey)))
        fixture.persisted.messages = [streamedRecoveryFixtureMessage(encryptedContent: encrypted)]
        await fixture.coordinator.markInitialSyncReady()
        await fixture.coordinator.handleAvailableJobs(fixture.availability)
        XCTAssertTrue(fixture.transport.sentTypes.isEmpty)
        XCTAssertEqual(fixture.persisted.upsertCount, 0)
    }

    // contract-test: supporting surface=gui.apple assertions=chats.persistence.client-encrypted,chats.message.identity-idempotent
    @MainActor
    func testDirectusIdempotentTerminalAcknowledgementReconcilesVersionWithoutRepeatingWrite() async throws {
        let fixture = try await makeRecoveryFixture(idempotentPersistWithoutVersion: true)
        await fixture.coordinator.markInitialSyncReady()
        await fixture.coordinator.handleAvailableJobs(fixture.availability)
        XCTAssertEqual(fixture.transport.sentTypes, ["recovery_job_claim", "recovery_job_persist", "recovery_job_claim", "request_chat_content_batch"])
        XCTAssertEqual(fixture.persisted.upsertCount, 1)
        XCTAssertNotNil(fixture.persisted.messages.first?.encryptedContent)
        XCTAssertEqual(fixture.persisted.committedMessagesVersions, [8])
    }

    // contract-test: supporting surface=gui.apple assertions=chats.persistence.client-encrypted
    @MainActor
    func testConflictingOptionalLeaseGenerationDoesNotCommitLocally() async throws {
        let fixture = try await makeRecoveryFixture(persistAcknowledgementLeaseGeneration: 99)
        await fixture.coordinator.markInitialSyncReady()
        await fixture.coordinator.handleAvailableJobs(fixture.availability)
        XCTAssertEqual(fixture.transport.sentTypes, ["recovery_job_claim", "recovery_job_persist"])
        XCTAssertEqual(fixture.persisted.upsertCount, 0)
        XCTAssertTrue(fixture.persisted.committedMessagesVersions.isEmpty)
    }

    // contract-test: supporting surface=gui.apple assertions=chats.persistence.client-encrypted,chats.completion.recovery-takeover
    @MainActor
    func testTerminalClaimWithoutLocalCiphertextKeepsSyncVersionUntilTheMessageArrives() async throws {
        let fixture = try await makeRecoveryFixture(initialClaimTerminal: true)
        await fixture.coordinator.markInitialSyncReady()
        await fixture.coordinator.handleAvailableJobs(fixture.availability)
        XCTAssertEqual(fixture.transport.sentTypes, ["recovery_job_claim", "request_chat_content_batch"])
        XCTAssertEqual(fixture.persisted.upsertCount, 0)
        XCTAssertTrue(fixture.persisted.committedMessagesVersions.isEmpty,
                      "A remote terminal job cannot advertise a local message we have not fetched")

        let encrypted = try await CryptoManager.shared.encryptContent("Recovered hello",
            key: SymmetricKey(data: try decodeBase64URL(RecoveryVector.shared.chatKey)))
        fixture.persisted.messages = [streamedRecoveryFixtureMessage(encryptedContent: encrypted)]
        fixture.transport.appendResponse(try await committedBatchFixture(ciphertext: encrypted), type: "chat_content_batch_response")
        await fixture.coordinator.handleTransportConnected()
        XCTAssertEqual(fixture.transport.sentTypes, ["recovery_job_claim", "request_chat_content_batch", "recovery_job_claim", "request_chat_content_batch"])
        XCTAssertEqual(fixture.persisted.committedMessagesVersions, [8],
                       "A missing local message must not prematurely mark the job reconciled")
    }

    // contract-test: supporting surface=gui.apple assertions=chats.completion.recovery-takeover,chats.message.identity-idempotent
    @MainActor
    func testLeaseConflictRetriesAfterTheLeaseWindowWithoutAnotherBroadcast() async throws {
        let clock = RecoveryManualScheduler()
        let fixture = try await makeRecoveryFixture(
            claimFailures: Array(repeating: .remote(code: "lease_conflict"), count: 5), scheduler: clock)
        await fixture.coordinator.markInitialSyncReady()
        await fixture.coordinator.handleAvailableJobs(fixture.availability)
        XCTAssertEqual(fixture.transport.sentTypes, ["recovery_job_claim"])
        await fixture.coordinator.handleAvailableJobs(fixture.availability)
        XCTAssertEqual(fixture.transport.sentTypes.count, 1, "Duplicate availability must respect the scheduled lease retry")
        for _ in 0..<5 { await clock.advanceNext() }
        XCTAssertEqual(clock.delays, [1, 3, 10, 20, 30])
        XCTAssertGreaterThanOrEqual(clock.delays.reduce(0, +), 60)
        XCTAssertEqual(fixture.transport.sentTypes.filter { $0 == "recovery_job_claim" }.count, 6)
        XCTAssertEqual(fixture.transport.sentTypes.filter { $0 == "recovery_job_persist" }.count, 1)
        XCTAssertEqual(fixture.persisted.committedMessagesVersions, [8])
        XCTAssertEqual(clock.activeCount, 0)
        XCTAssertFalse(fixture.transport.sentTypes.contains("chat_message_added"), "Recovery must never restart inference")
    }

    // contract-test: supporting surface=gui.apple assertions=chats.completion.recovery-takeover,chats.persistence.client-encrypted
    @MainActor
    func testVersionConflictRefreshesEncryptedHistoryBeforeAReclaimedPersist() async throws {
        let clock = RecoveryManualScheduler()
        let fixture = try await makeRecoveryFixture(scheduler: clock,
            committedBatch: try await committedBatchFixture(assistantId: "previous-assistant", version: 7))
        fixture.persisted.currentMessagesVersion = 6
        fixture.transport.responseErrors["recovery_job_persisted"] = [WebSocketError.remote(code: "version_conflict")]
        fixture.transport.replaceSecondClaimWithNewLease()
        await fixture.coordinator.markInitialSyncReady()
        await fixture.coordinator.handleAvailableJobs(fixture.availability)
        XCTAssertEqual(fixture.transport.sentTypes, ["recovery_job_claim", "recovery_job_persist"])
        await clock.advanceNext()
        XCTAssertEqual(fixture.transport.sentTypes,
                       ["recovery_job_claim", "recovery_job_persist", "request_chat_content_batch", "recovery_job_claim", "recovery_job_persist"])
        XCTAssertEqual(fixture.transport.sentPayloads.last?["expected_messages_v"] as? Int, 7)
        XCTAssertEqual(fixture.transport.sentPayloads.last?["lease_generation"] as? Int, 3)
        XCTAssertEqual(fixture.persisted.committedMessagesVersions, [7, 8])
        XCTAssertEqual(fixture.persisted.messages.count, 2)
        XCTAssertFalse(fixture.transport.sentTypes.contains("chat_message_added"))
    }

    // contract-test: supporting surface=gui.apple assertions=chats.sync.key-gated-recovery,chats.message.identity-idempotent
    @MainActor
    func testResetFencesAnInFlightClaimAndItsPreviouslyScheduledCallback() async throws {
        let clock = RecoveryManualScheduler()
        let fixture = try await makeRecoveryFixture(claimFailures: [.remote(code: "lease_conflict")], scheduler: clock)
        await fixture.coordinator.markInitialSyncReady()
        await fixture.coordinator.handleAvailableJobs(fixture.availability)
        fixture.coordinator.reset()
        await clock.advanceNext(includingCancelled: true)
        XCTAssertEqual(fixture.transport.sentTypes, ["recovery_job_claim"])

        let inFlight = try await makeRecoveryFixture()
        inFlight.transport.beforeResponse = { type in
            if type == "recovery_job_claimed" { inFlight.coordinator.handleTransportDisconnected() }
        }
        await inFlight.coordinator.markInitialSyncReady()
        await inFlight.coordinator.handleAvailableJobs(inFlight.availability)
        inFlight.transport.beforeResponse = nil
        XCTAssertEqual(inFlight.transport.sentTypes, ["recovery_job_claim"])
        XCTAssertTrue(inFlight.persisted.messages.isEmpty)
        XCTAssertTrue(inFlight.persisted.committedMessagesVersions.isEmpty)
    }

    // contract-test: supporting surface=gui.apple assertions=chats.completion.recovery-takeover
    @MainActor
    func testRepeatedLeaseConflictsHaveAFiniteRetryBudget() async throws {
        let clock = RecoveryManualScheduler()
        let fixture = try await makeRecoveryFixture(
            claimFailures: Array(repeating: .remote(code: "lease_conflict"), count: 7), scheduler: clock)
        await fixture.coordinator.markInitialSyncReady()
        await fixture.coordinator.handleAvailableJobs(fixture.availability)
        for _ in ChatCompletionRecoveryCoordinator.retryDelays { await clock.advanceNext() }
        XCTAssertEqual(clock.delays, ChatCompletionRecoveryCoordinator.retryDelays)
        XCTAssertEqual(clock.activeCount, 0)
        XCTAssertEqual(fixture.transport.sentTypes.count, 7)
        XCTAssertTrue(fixture.persisted.committedMessagesVersions.isEmpty)
    }

    // contract-test: supporting surface=gui.apple assertions=chats.completion.recovery-takeover,chats.sync.key-gated-recovery
    @MainActor
    func testDisconnectCancelsRetryAndReconnectClaimsTheSameJobOnce() async throws {
        let clock = RecoveryManualScheduler()
        let fixture = try await makeRecoveryFixture(claimFailures: [.remote(code: "lease_conflict")], scheduler: clock)
        await fixture.coordinator.markInitialSyncReady()
        await fixture.coordinator.handleAvailableJobs(fixture.availability)
        fixture.coordinator.handleTransportDisconnected()
        XCTAssertEqual(clock.activeCount, 0)
        await clock.advanceNext(includingCancelled: true)
        XCTAssertEqual(fixture.transport.sentTypes, ["recovery_job_claim"], "A late cancelled callback cannot write to a replaced socket")
        await fixture.coordinator.handleTransportConnected()
        XCTAssertEqual(fixture.transport.sentTypes, ["recovery_job_claim", "recovery_job_claim", "recovery_job_persist"])
        XCTAssertEqual(fixture.persisted.committedMessagesVersions, [8])
    }

    // contract-test: supporting surface=gui.apple assertions=chats.sync.key-gated-recovery
    @MainActor
    func testAccountSwitchDuringMultiJobFlushCannotRepopulateTheNewOwnerQueue() async throws {
        let fixture = try await makeRecoveryFixture()
        var jobs = try XCTUnwrap(fixture.availability["jobs"] as? [[String: Any]])
        var second = jobs[0]
        second["job_id"] = "66666666-6666-4666-8666-666666666666"
        second["assistant_message_id"] = "77777777-7777-4777-8777-777777777777"
        jobs.append(second)
        await fixture.coordinator.handleAvailableJobs(["jobs": jobs])
        fixture.transport.beforeResponse = { _ in
            fixture.coordinator.reset()
            fixture.identity.ownerId = "another-account"
            XCTAssertTrue(fixture.coordinator.pendingAssistantMessageIds(in: RecoveryVector.shared.chatId).isEmpty)
        }
        await fixture.coordinator.markInitialSyncReady()
        fixture.transport.beforeResponse = nil
        XCTAssertEqual(fixture.transport.sentTypes, ["recovery_job_claim"])
        XCTAssertTrue(fixture.coordinator.pendingAssistantMessageIds(in: RecoveryVector.shared.chatId).isEmpty,
                      "The remainder of the old owner's flush snapshot must not leak into the new runtime")
        XCTAssertTrue(fixture.persisted.messages.isEmpty)
    }

    // contract-test: supporting surface=gui.apple assertions=chats.persistence.client-encrypted,chats.message.identity-idempotent
    @MainActor
    func testIdempotentPersistFetchesCanonicalCiphertextAndAllRowsBeforeAdvancingVersion() async throws {
        var batch = try await committedBatchFixture(version: 10)
        let vector = RecoveryVector.shared
        var messages = try XCTUnwrap((batch["messages_by_chat_id"] as? [String: [String]])?[vector.chatId])
        let later = try await committedBatchFixture(assistantId: "later-assistant", version: 10)
        messages += try XCTUnwrap((later["messages_by_chat_id"] as? [String: [String]])?[vector.chatId])
        batch["messages_by_chat_id"] = [vector.chatId: messages]
        let fixture = try await makeRecoveryFixture(persistWasAlreadyCommitted: true,
                                             committedMessagesVersion: 10, committedBatch: batch)
        fixture.persisted.onVersionCommitted = { [weak recorder = fixture.persisted] in
            XCTAssertEqual(recorder?.messages.count, 2, "All fetched rows must precede the advertised server version")
        }
        await fixture.coordinator.markInitialSyncReady()
        await fixture.coordinator.handleAvailableJobs(fixture.availability)
        XCTAssertEqual(fixture.transport.sentTypes, ["recovery_job_claim", "recovery_job_persist", "request_chat_content_batch"])
        XCTAssertEqual(fixture.persisted.committedMessagesVersions, [10])
        let encoded = try XCTUnwrap(messages.first?.data(using: .utf8))
        let canonical = try XCTUnwrap(JSONSerialization.jsonObject(with: encoded) as? [String: Any])
        XCTAssertEqual(fixture.persisted.messages.first(where: { $0.id == vector.assistantMessageId })?.encryptedContent,
                       canonical["encrypted_content"] as? String)
    }

    // contract-test: supporting surface=gui.apple assertions=chats.sync.key-gated-recovery
    @MainActor
    func testAccountChangePreventsQueuedRetryAndLatePersistenceAcknowledgement() async throws {
        let clock = RecoveryManualScheduler()
        let fixture = try await makeRecoveryFixture(claimFailures: [.remote(code: "lease_conflict")], scheduler: clock)
        await fixture.coordinator.markInitialSyncReady()
        await fixture.coordinator.handleAvailableJobs(fixture.availability)
        fixture.identity.ownerId = "another-account"
        await clock.advanceNext()
        XCTAssertEqual(fixture.transport.sentTypes, ["recovery_job_claim"])
        XCTAssertTrue(fixture.coordinator.pendingAssistantMessageIds(in: RecoveryVector.shared.chatId).isEmpty)

        let inFlight = try await makeRecoveryFixture()
        inFlight.transport.beforeResponse = { type in
            if type == "recovery_job_persisted" { inFlight.identity.ownerId = "another-account" }
        }
        await inFlight.coordinator.markInitialSyncReady()
        await inFlight.coordinator.handleAvailableJobs(inFlight.availability)
        inFlight.transport.beforeResponse = nil
        XCTAssertEqual(inFlight.transport.sentTypes, ["recovery_job_claim", "recovery_job_persist"])
        XCTAssertEqual(inFlight.persisted.upsertCount, 0)
        XCTAssertTrue(inFlight.persisted.committedMessagesVersions.isEmpty,
                      "A response from the previous account cannot update the active store")
    }

    // contract-test: supporting surface=gui.apple assertions=chats.completion.recovery-takeover,chats.persistence.client-encrypted
    @MainActor
    func testColdLaunchRestoresLeasedJobAwarenessBeforeSyncAndRecoversWithoutDiscovery() async throws {
        let suite = "OpenMatesRecoveryTests.\(UUID().uuidString)"
        let defaults = try XCTUnwrap(UserDefaults(suiteName: suite))
        defer { defaults.removePersistentDomain(forName: suite) }
        let clock = RecoveryManualScheduler()
        let queue = PendingAssistantResponseQueue.recovery(ownerId: RecoveryVector.shared.ownerId,
            apiBaseURL: URL(string: "https://recovery.invalid")!, defaults: defaults, now: { clock.now })
        let origin = try await makeRecoveryFixture(claimFailures: [.remote(code: "lease_conflict")], scheduler: clock, queue: queue)
        var terminal = terminalRecoveryFixturePayload()
        terminal["full_content_so_far"] = "Recovered hello"
        origin.coordinator.handleTerminalStream(terminal)
        XCTAssertEqual(queue.all().count, 1, "Routing identifiers must be durable before an asynchronous claim")
        await origin.coordinator.markInitialSyncReady()
        XCTAssertNotNil(origin.persisted.messages.first?.encryptedContent)
        XCTAssertTrue(origin.persisted.committedMessagesVersions.isEmpty)
        origin.coordinator.reset()

        let coldClock = RecoveryManualScheduler()
        let cold = try await makeRecoveryFixture(initialClaimTerminal: true,
            claimFailures: [.remote(code: "lease_conflict")], scheduler: coldClock,
            queue: queue, recorder: origin.persisted, committedBatch: try await committedBatchFixture())
        XCTAssertEqual(cold.coordinator.pendingAssistantMessageIds(in: RecoveryVector.shared.chatId),
                       [RecoveryVector.shared.assistantMessageId], "Cold initial sync must preserve the pending streamed row")
        await cold.coordinator.markInitialSyncReady()
        XCTAssertEqual(cold.transport.sentTypes, ["recovery_job_claim"])
        XCTAssertFalse(queue.all().isEmpty)
        await coldClock.advanceNext()
        XCTAssertEqual(cold.transport.sentTypes, ["recovery_job_claim", "recovery_job_claim", "request_chat_content_batch"])
        XCTAssertEqual(cold.persisted.committedMessagesVersions, [8])
        XCTAssertTrue(queue.all().isEmpty)
        XCTAssertTrue(cold.coordinator.pendingAssistantMessageIds(in: RecoveryVector.shared.chatId).isEmpty)
    }

    // contract-test: supporting surface=gui.apple assertions=chats.completion.recovery-takeover,chats.message.identity-idempotent
    @MainActor
    func testCompetingSaversRetainBothStreamsAndLoserConvergesToWinnerCiphertext() async throws {
        let winner = try await makeRecoveryFixture()
        let clock = RecoveryManualScheduler()
        let loser = try await makeRecoveryFixture(initialClaimTerminal: true,
            claimFailures: [.remote(code: "lease_conflict")], scheduler: clock)
        var terminal = terminalRecoveryFixturePayload()
        terminal["full_content_so_far"] = "Recovered hello"
        // The independent stream renderer has materialized the same response
        // on both devices before either one acquires the final-save lease.
        winner.persisted.messages = [streamedRecoveryFixtureMessage()]
        loser.persisted.messages = [streamedRecoveryFixtureMessage()]
        winner.coordinator.handleTerminalStream(terminal)
        loser.coordinator.handleTerminalStream(terminal)
        XCTAssertEqual(winner.persisted.messages.first?.content, "Recovered hello")
        XCTAssertEqual(loser.persisted.messages.first?.content, "Recovered hello")
        await loser.coordinator.markInitialSyncReady()
        XCTAssertNotNil(loser.persisted.messages.first?.encryptedContent,
                        "Format A ciphertext must be retained even while another device owns the save lease")
        XCTAssertTrue(loser.persisted.committedMessagesVersions.isEmpty)
        XCTAssertEqual(loser.coordinator.pendingAssistantMessageIds(in: RecoveryVector.shared.chatId),
                       [RecoveryVector.shared.assistantMessageId])
        winner.persisted.onVersionCommitted = { [weak coordinator = winner.coordinator] in
            XCTAssertTrue(coordinator?.pendingAssistantMessageIds(in: RecoveryVector.shared.chatId).isEmpty ?? false,
                          "The version publication must already expose the recovery job as committed")
        }
        await winner.coordinator.markInitialSyncReady()
        let winnerCiphertext = try XCTUnwrap(winner.persisted.messages.first?.encryptedContent)
        loser.transport.appendResponse(try await committedBatchFixture(ciphertext: winnerCiphertext), type: "chat_content_batch_response")
        await clock.advanceNext()
        XCTAssertEqual(winner.transport.sentTypes.filter { $0 == "recovery_job_persist" }.count, 1)
        XCTAssertFalse(loser.transport.sentTypes.contains("recovery_job_persist"))
        XCTAssertEqual(loser.persisted.messages.count, 1)
        XCTAssertEqual(loser.persisted.messages.first?.encryptedContent, winnerCiphertext)
        XCTAssertEqual(loser.persisted.messages.first?.content, "Recovered hello")
        XCTAssertEqual(loser.persisted.committedMessagesVersions, [8])
        XCTAssertTrue(loser.coordinator.pendingAssistantMessageIds(in: RecoveryVector.shared.chatId).isEmpty)
        XCTAssertFalse((winner.transport.sentTypes + loser.transport.sentTypes).contains("chat_message_added"))
    }

    // contract-test: supporting surface=gui.apple assertions=chats.persistence.client-encrypted,chats.message.identity-idempotent
    @MainActor
    func testTerminalReconciliationRejectsBatchWithoutTheExactAssistant() async throws {
        let fixture = try await makeRecoveryFixture(initialClaimTerminal: true,
            committedBatch: try await committedBatchFixture(assistantId: "different-assistant"))
        await fixture.coordinator.markInitialSyncReady()
        await fixture.coordinator.handleAvailableJobs(fixture.availability)
        XCTAssertEqual(fixture.transport.sentTypes, ["recovery_job_claim", "request_chat_content_batch"])
        XCTAssertTrue(fixture.persisted.messages.isEmpty)
        XCTAssertTrue(fixture.persisted.committedMessagesVersions.isEmpty)
    }

    // contract-test: supporting surface=gui.apple assertions=chats.sync.key-gated-recovery,chats.persistence.client-encrypted
    @MainActor
    func testRecoveryMetadataQueueIsAccountAndServerScopedBoundedAndExpires() throws {
        let suite = "OpenMatesRecoveryTests.\(UUID().uuidString)"
        let defaults = try XCTUnwrap(UserDefaults(suiteName: suite))
        defer { defaults.removePersistentDomain(forName: suite) }
        let clock = RecoveryManualScheduler()
        let url = URL(string: "https://recovery.invalid")!
        let queue = PendingAssistantResponseQueue.recovery(ownerId: "owner-a", apiBaseURL: url,
                                                           defaults: defaults, now: { clock.now })
        let foreign = PendingAssistantResponseQueue.recovery(ownerId: "owner-b", apiBaseURL: url,
                                                             defaults: defaults, now: { clock.now })
        let otherServer = PendingAssistantResponseQueue.recovery(ownerId: "owner-a",
            apiBaseURL: URL(string: "https://other.invalid")!, defaults: defaults, now: { clock.now })
        let legacy = PendingAssistantResponseQueue(defaults: defaults)
        for index in 0...PendingAssistantResponseQueue.recoveryCapacity {
            queue.addRecovery(jobId: "job-\(index)", messageId: "message-\(index)", chatId: "chat")
        }
        XCTAssertEqual(queue.all().count, PendingAssistantResponseQueue.recoveryCapacity)
        XCTAssertEqual(queue.all().first?.recoveryJobId, "job-1")
        XCTAssertTrue(foreign.all().isEmpty)
        XCTAssertTrue(otherServer.all().isEmpty)
        XCTAssertTrue(legacy.all().isEmpty, "Legacy retry must never send a sealed-recovery entry")
        let data = try JSONEncoder().encode(queue.all())
        let entries = try XCTUnwrap(JSONSerialization.jsonObject(with: data) as? [[String: Any]])
        XCTAssertEqual(Set(entries[0].keys), Set(["chatId", "messageId", "recoveryJobId", "queuedAt"]),
                       "Only routing identifiers and expiry metadata may be stored in this queue")
        clock.now.addTimeInterval(PendingAssistantResponseQueue.recoveryLifetime)
        XCTAssertTrue(queue.all().isEmpty)
    }

    @MainActor
    private func committedBatchFixture(ciphertext: String? = nil, assistantId: String? = nil, version: Int = 8) async throws -> [String: Any] {
        let vector = RecoveryVector.shared
        let key = SymmetricKey(data: try decodeBase64URL(vector.chatKey))
        let encrypted: String
        if let ciphertext { encrypted = ciphertext }
        else { encrypted = try await CryptoManager.shared.encryptContent("Recovered hello", key: key) }
        let message: [String: Any] = [
            "id": assistantId ?? vector.assistantMessageId, "chat_id": vector.chatId, "role": "assistant",
            "encrypted_content": encrypted,
            "created_at": "2026-01-01T00:00:00Z",
        ]
        let encoded = try XCTUnwrap(String(data: JSONSerialization.data(withJSONObject: message), encoding: .utf8))
        return ["messages_by_chat_id": [vector.chatId: [encoded]],
                "versions_by_chat_id": [vector.chatId: ["messages_v": version]],
                "embeds": [], "embed_keys": [], "chat_key_wrappers": []]
    }

    private func streamedRecoveryFixtureMessage(encryptedContent: String? = nil) -> Message {
        Message(id: RecoveryVector.shared.assistantMessageId, chatId: RecoveryVector.shared.chatId,
                role: .assistant, content: "Recovered hello", encryptedContent: encryptedContent,
                createdAt: "2026-01-01T00:00:00Z", updatedAt: nil, appId: "web",
                isStreaming: false, embedRefs: nil, thinkingContent: "Synthetic reasoning already rendered")
    }

    private func terminalRecoveryFixturePayload() -> [String: Any] {
        ["is_final_chunk": true, "recovery_protocol_version": 1,
         "recovery_job_id": RecoveryVector.shared.jobId, "chat_id": RecoveryVector.shared.chatId,
         "message_id": RecoveryVector.shared.assistantMessageId]
    }

    // contract-test: supporting surface=gui.apple assertions=chats.completion.recovery-takeover
    @MainActor
    func testRecoveryEnvelopeRejectsUnknownFields() async throws {
        let fixture = try await makeRecoveryFixture(hasUnknownEnvelopeField: true)
        await fixture.coordinator.markInitialSyncReady()
        await fixture.coordinator.handleAvailableJobs(fixture.availability)

        XCTAssertEqual(fixture.transport.sentTypes, ["recovery_job_claim"])
        XCTAssertTrue(fixture.persisted.messages.isEmpty)
    }

    // contract-test: supporting surface=gui.apple assertions=chats.persistence.client-encrypted
    @MainActor
    func testLegacyPreflightAcknowledgementPreservesSendWithoutRecoveryClaim() async throws {
        let transport = RecoveryRecordingTransport(responses: [
            "chat_turn_preflight_ack": [["turn_id": "turn-legacy", "preflight_id": "legacy-id", "state": "LEGACY"]]
        ])
        try await ChatSendPipeline().sendSavedChatTurn(
            turnId: "turn-legacy",
            preflightPayload: [
                "turn_id": "turn-legacy",
                "inference_request": ["chat_id": "chat-1", "turn_id": "turn-legacy"],
            ],
            outboundPayload: ["chat_id": "chat-1", "turn_id": "turn-legacy"],
            transport: transport
        )
        XCTAssertEqual(transport.sentTypes, ["chat_turn_preflight", "chat_message_added"])
        XCTAssertFalse(transport.sentTypes.contains("recovery_job_claim"))
    }

    // contract-test: supporting surface=gui.apple assertions=chats.completion.recovery-takeover
    func testSharedCryptoVectors() async throws {
        let vector = RecoveryVector.shared
        let chatKey = SymmetricKey(data: try decodeBase64URL(vector.chatKey))

        let keyPair = try await CryptoManager.shared.deriveRecoveryKeyPair(
            chatKey: chatKey,
            chatId: vector.chatId,
            keyVersion: vector.keyVersion
        )
        XCTAssertEqual(keyPair.privateKey, vector.recoveryPrivateKey)
        XCTAssertEqual(keyPair.publicKey, vector.recoveryPublicKey)

        let associatedData = try await CryptoManager.shared.buildRecoveryAssociatedData(
            ownerId: vector.ownerId,
            chatId: vector.chatId,
            turnId: vector.turnId,
            jobId: vector.jobId,
            assistantMessageId: vector.assistantMessageId,
            keyVersion: vector.keyVersion
        )
        XCTAssertEqual(encodeBase64URL(associatedData), vector.associatedData)

        let envelope = try await CryptoManager.shared.sealRecoveryPayload(
            Data(vector.plaintext.utf8),
            recoveryPublicKey: vector.recoveryPublicKey,
            ownerId: vector.ownerId,
            chatId: vector.chatId,
            turnId: vector.turnId,
            jobId: vector.jobId,
            assistantMessageId: vector.assistantMessageId,
            keyVersion: vector.keyVersion,
            ephemeralPrivateKey: vector.ephemeralPrivateKey,
            nonce: vector.nonce
        )
        XCTAssertEqual(envelope.v, 1)
        XCTAssertEqual(envelope.epk, vector.ephemeralPublicKey)
        XCTAssertEqual(envelope.nonce, vector.nonce)
        XCTAssertEqual(envelope.ciphertext, vector.ciphertext)

        let plaintext = try await CryptoManager.shared.openRecoveryEnvelope(
            envelope,
            recoveryPrivateKey: keyPair.privateKey,
            ownerId: vector.ownerId,
            chatId: vector.chatId,
            turnId: vector.turnId,
            jobId: vector.jobId,
            assistantMessageId: vector.assistantMessageId,
            keyVersion: vector.keyVersion
        )
        XCTAssertEqual(plaintext, Data(vector.plaintext.utf8))
    }

    // contract-test: supporting surface=gui.apple assertions=chats.completion.recovery-takeover
    func testSharedCryptoVectorsRejectTampering() async throws {
        let vector = RecoveryVector.shared
        let fields = ["ciphertext", "nonce", "epk"]

        for field in fields {
            let envelope = CryptoManager.RecoveryEnvelope(
                v: 1,
                epk: field == "epk" ? tamper(vector.ephemeralPublicKey) : vector.ephemeralPublicKey,
                nonce: field == "nonce" ? tamper(vector.nonce) : vector.nonce,
                ciphertext: field == "ciphertext" ? tamper(vector.ciphertext) : vector.ciphertext
            )
            do {
                _ = try await CryptoManager.shared.openRecoveryEnvelope(
                    envelope,
                    recoveryPrivateKey: vector.recoveryPrivateKey,
                    ownerId: vector.ownerId,
                    chatId: vector.chatId,
                    turnId: vector.turnId,
                    jobId: vector.jobId,
                    assistantMessageId: vector.assistantMessageId,
                    keyVersion: vector.keyVersion
                )
                XCTFail("Expected \(field) tampering to fail")
            } catch {
                // Authentication or strict input validation must reject the envelope.
            }
        }

        let validEnvelope = CryptoManager.RecoveryEnvelope(
            v: 1,
            epk: vector.ephemeralPublicKey,
            nonce: vector.nonce,
            ciphertext: vector.ciphertext
        )
        do {
            _ = try await CryptoManager.shared.openRecoveryEnvelope(
                validEnvelope,
                recoveryPrivateKey: vector.recoveryPrivateKey,
                ownerId: vector.ownerId,
                chatId: vector.chatId,
                turnId: "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
                jobId: vector.jobId,
                assistantMessageId: vector.assistantMessageId,
                keyVersion: vector.keyVersion
            )
            XCTFail("Expected associated-data tampering to fail")
        } catch {
            // Authentication must bind the stable recovery identities.
        }
    }

    private func encodeBase64URL(_ data: Data) -> String {
        data.base64EncodedString()
            .replacingOccurrences(of: "+", with: "-")
            .replacingOccurrences(of: "/", with: "_")
            .replacingOccurrences(of: "=", with: "")
    }

    private func decodeBase64URL(_ value: String) throws -> Data {
        var base64 = value
            .replacingOccurrences(of: "-", with: "+")
            .replacingOccurrences(of: "_", with: "/")
        base64.append(String(repeating: "=", count: (4 - base64.count % 4) % 4))
        return try XCTUnwrap(Data(base64Encoded: base64))
    }

    private func tamper(_ value: String) -> String {
        let replacement = value.first == "A" ? "B" : "A"
        return replacement + String(value.dropFirst())
    }

    @MainActor
    private func makeRecoveryFixture(
        isEligible: Bool = true,
        hasKey: Bool = true,
        hasUnknownEnvelopeField: Bool = false,
        persistReceiptInterrupted: Bool = false,
        idempotentPersistWithoutVersion: Bool = false,
        persistAcknowledgementLeaseGeneration: Int? = nil,
        initialClaimTerminal: Bool = false,
        persistWasAlreadyCommitted: Bool = false,
        committedMessagesVersion: Int = 8,
        claimFailures: [WebSocketError] = [],
        scheduler: RecoveryManualScheduler? = nil,
        queue: PendingAssistantResponseQueue? = nil,
        recorder: RecoveryMessageRecorder? = nil,
        identity: RecoveryIdentity? = nil,
        committedBatch: [String: Any]? = nil
    ) async throws -> RecoveryFixture {
        let vector = RecoveryVector.shared
        var envelope: [String: Any] = [
            "v": 1,
            "epk": vector.ephemeralPublicKey,
            "nonce": vector.nonce,
            "ciphertext": vector.ciphertext,
        ]
        if hasUnknownEnvelopeField {
            envelope["unexpected"] = true
        }
        let sealedPayload = try XCTUnwrap(String(data: JSONSerialization.data(withJSONObject: envelope), encoding: .utf8))
        // Actual Directus persistTerminal response schema: lease_generation is
        // validated on the request, but never echoed in a normal response.
        var persistedAcknowledgement: [String: Any] = [
            "job_id": vector.jobId, "state": "TERMINAL", "idempotent": idempotentPersistWithoutVersion || persistWasAlreadyCommitted
        ]
        if !idempotentPersistWithoutVersion { persistedAcknowledgement["committed_messages_v"] = committedMessagesVersion }
        if let persistAcknowledgementLeaseGeneration {
            persistedAcknowledgement["lease_generation"] = persistAcknowledgementLeaseGeneration
        }
        let leasedClaim: [String: Any] = [
                "job_id": vector.jobId,
                "state": "LEASED",
                "lease_token": "synthetic-lease-token",
                "lease_generation": 2,
                "chat_id": vector.chatId,
                "turn_id": vector.turnId,
                "assistant_message_id": vector.assistantMessageId,
                "chat_key_version": Int(vector.keyVersion),
                "sealed_payload": sealedPayload,
            ]
        let terminalClaim: [String: Any] = [
                "job_id": vector.jobId,
                "state": "TERMINAL",
                "chat_id": vector.chatId,
                "turn_id": vector.turnId,
                "assistant_message_id": vector.assistantMessageId,
                "chat_key_version": Int(vector.keyVersion),
                "committed_messages_v": 8,
            ]
        let batchResponses: [[String: Any]]
        if let committedBatch {
            batchResponses = [committedBatch]
        } else if idempotentPersistWithoutVersion || persistWasAlreadyCommitted {
            batchResponses = [try await committedBatchFixture()]
        } else {
            batchResponses = []
        }
        let transport = RecoveryRecordingTransport(responses: [
            "recovery_job_claimed": [initialClaimTerminal ? terminalClaim : leasedClaim, terminalClaim],
            "recovery_job_persisted": [persistedAcknowledgement],
            "chat_content_batch_response": batchResponses,
        ], persistReceiptInterrupted: persistReceiptInterrupted)
        transport.responseErrors["recovery_job_claimed"] = claimFailures
        let persisted = recorder ?? RecoveryMessageRecorder()
        let identity = identity ?? RecoveryIdentity(ownerId: vector.ownerId, eligible: isEligible)
        let key = SymmetricKey(data: try decodeBase64URL(vector.chatKey))
        let coordinator = ChatCompletionRecoveryCoordinator(
            transport: transport,
            authenticatedOwnerId: { identity.ownerId },
            isDeviceEligible: { identity.eligible },
            chatKey: { _ in hasKey ? key : nil },
            isChatKeyReady: { true },
            chatVersion: { _ in persisted.currentMessagesVersion },
            containsPersistedMessage: { chatId, messageId in
                persisted.messages.contains {
                    $0.chatId == chatId && $0.id == messageId && !($0.encryptedContent?.isEmpty ?? true)
                }
            },
            persistMessage: { recovered in
                persisted.upsertCount += 1
                let index = persisted.messages.firstIndex { $0.chatId == recovered.chatId && $0.id == recovered.id }
                let existing = index.map { persisted.messages[$0] }
                let message = ChatCompletionRecoveryCoordinator.mergingRecoveredMessage(recovered, preserving: existing)
                if let index { persisted.messages[index] = message } else { persisted.messages.append(message) }
            },
            applyCommittedMessagesVersion: { _, version in
                persisted.committedMessagesVersions.append(version)
                persisted.currentMessagesVersion = max(persisted.currentMessagesVersion, version)
                persisted.onVersionCommitted?()
            },
            currentOwnerSnapshot: { identity.ownerId },
            recoveryQueue: { $0 == vector.ownerId ? queue : nil },
            now: { scheduler?.now ?? Date(timeIntervalSince1970: 1_780_000_000) },
            scheduleRetry: { delay, operation in scheduler?.schedule(after: delay, operation: operation) ?? {} }
        )
        return RecoveryFixture(
            coordinator: coordinator,
            transport: transport,
            persisted: persisted,
            identity: identity,
            availability: ["jobs": [[
                "job_id": vector.jobId,
                "chat_id": vector.chatId,
                "turn_id": vector.turnId,
                "assistant_message_id": vector.assistantMessageId,
                "chat_key_version": Int(vector.keyVersion),
            ]]]
        )
    }
}

@MainActor
private final class RecoveryRecordingTransport: ChatWebSocketTransport {
    private var responses: [String: [[String: Any]]]
    private let persistReceiptInterrupted: Bool
    var responseErrors: [String: [Error]] = [:]
    var beforeResponse: ((String) -> Void)?
    func appendResponse(_ response: [String: Any], type: String) { responses[type, default: []].append(response) }
    func replaceSecondClaimWithNewLease() {
        guard var next = responses["recovery_job_claimed"]?.first else { return }
        next["lease_generation"] = 3
        next["lease_token"] = "synthetic-next-lease"
        responses["recovery_job_claimed"] = [responses["recovery_job_claimed"]![0], next]
    }
    private(set) var sentTypes: [String] = []
    private(set) var sentPayloads: [[String: Any]] = []

    init(responses: [String: [[String: Any]]], persistReceiptInterrupted: Bool = false) {
        self.responses = responses
        self.persistReceiptInterrupted = persistReceiptInterrupted
    }

    func send(_ message: WSOutboundMessage) async throws {
        let data = try JSONEncoder().encode(message)
        let object = try XCTUnwrap(JSONSerialization.jsonObject(with: data) as? [String: Any])
        sentTypes.append(try XCTUnwrap(object["type"] as? String))
        sentPayloads.append((object["payload"] as? [String: Any]) ?? [:])
    }

    func sendAndWait(
        _ message: WSOutboundMessage,
        responseType: String,
        timeout: Duration,
        matching predicate: @escaping ([String: Any]) -> Bool
    ) async throws -> WebSocketResponse {
        try await send(message)
        return try await waitForMessage(responseType, timeout: timeout, matching: predicate)
    }

    func waitForMessage(
        _ type: String,
        timeout: Duration,
        matching predicate: @escaping ([String: Any]) -> Bool
    ) async throws -> WebSocketResponse {
        beforeResponse?(type)
        if !(responseErrors[type]?.isEmpty ?? true), let error = responseErrors[type]?.removeFirst() { throw error }
        if type == "recovery_job_persisted", persistReceiptInterrupted {
            throw RecoveryTestError.interruptedReceipt
        }
        guard let index = responses[type]?.firstIndex(where: predicate),
              let response = responses[type]?.remove(at: index) else {
            throw RecoveryTestError.missingResponse(type)
        }
        return WebSocketResponse(fields: response)
    }
}

@MainActor
private final class RecoveryMessageRecorder {
    var messages: [Message] = []
    var upsertCount = 0
    var committedMessagesVersions: [Int] = []
    var currentMessagesVersion = 7
    var onVersionCommitted: (() -> Void)?
}

@MainActor
private struct RecoveryFixture {
    let coordinator: ChatCompletionRecoveryCoordinator
    let transport: RecoveryRecordingTransport
    let persisted: RecoveryMessageRecorder
    let identity: RecoveryIdentity
    let availability: [String: Any]
}

@MainActor
private final class RecoveryIdentity {
    var ownerId: String?
    var eligible: Bool
    init(ownerId: String?, eligible: Bool = true) { self.ownerId = ownerId; self.eligible = eligible }
}

@MainActor
private final class RecoveryManualScheduler {
    struct Scheduled {
        let id: UUID
        let delay: TimeInterval
        let operation: @MainActor () async -> Void
    }
    var now = Date(timeIntervalSince1970: 1_780_000_000)
    var delays: [TimeInterval] = []
    private var pending: [Scheduled] = []
    private var cancelled = Set<UUID>()
    var activeCount: Int { pending.filter { !cancelled.contains($0.id) }.count }

    func schedule(after delay: TimeInterval, operation: @escaping @MainActor () async -> Void) -> () -> Void {
        let item = Scheduled(id: UUID(), delay: delay, operation: operation)
        pending.append(item)
        delays.append(delay)
        return { [weak self] in _ = self?.cancelled.insert(item.id) }
    }

    func advanceNext(includingCancelled: Bool = false) async {
        while !pending.isEmpty {
            let item = pending.removeFirst()
            guard includingCancelled || !cancelled.contains(item.id) else { continue }
            now.addTimeInterval(item.delay)
            await item.operation()
            return
        }
    }
}

private enum RecoveryTestError: Error {
    case missingResponse(String)
    case interruptedReceipt
}

private struct RecoveryVector {
    let chatKey: String
    let ownerId: String
    let chatId: String
    let turnId: String
    let jobId: String
    let assistantMessageId: String
    let keyVersion: UInt32
    let recoveryPrivateKey: String
    let recoveryPublicKey: String
    let ephemeralPrivateKey: String
    let ephemeralPublicKey: String
    let associatedData: String
    let nonce: String
    let plaintext: String
    let ciphertext: String

    // Source: backend/tests/fixtures/chat_completion_recovery_vectors.json,
    // vector "sequential-key-existing-chat-v1".
    static let shared = RecoveryVector(
        chatKey: "AAECAwQFBgcICQoLDA0ODxAREhMUFRYXGBkaGxwdHh8",
        ownerId: "11111111-1111-4111-8111-111111111111",
        chatId: "22222222-2222-4222-8222-222222222222",
        turnId: "33333333-3333-4333-8333-333333333333",
        jobId: "44444444-4444-4444-8444-444444444444",
        assistantMessageId: "55555555-5555-4555-8555-555555555555",
        keyVersion: 7,
        recoveryPrivateKey: "gpeKnanRKoU2GGJGmwWqkaJGbdENwoYEB-juL6eHGQw",
        recoveryPublicKey: "52h8oPfO4CzxXUVGx6abkertndIuIwYD6xGwerS9dAc",
        ephemeralPrivateKey: "ICEiIyQlJicoKSorLC0uLzAxMjM0NTY3ODk6Ozw9Pj8",
        ephemeralPublicKey: "NYBy1jZYgNGu6jKa35EhODhR7SGijjt16WXQ0s0WYlQ",
        associatedData: "T01DUjEAAAAkMTExMTExMTEtMTExMS00MTExLTgxMTEtMTExMTExMTExMTExAAAAJDIyMjIyMjIyLTIyMjItNDIyMi04MjIyLTIyMjIyMjIyMjIyMgAAACQzMzMzMzMzMy0zMzMzLTQzMzMtODMzMy0zMzMzMzMzMzMzMzMAAAAkNDQ0NDQ0NDQtNDQ0NC00NDQ0LTg0NDQtNDQ0NDQ0NDQ0NDQ0AAAAJDU1NTU1NTU1LTU1NTUtNDU1NS04NTU1LTU1NTU1NTU1NTU1NQAAAAc",
        nonce: "AAECAwQFBgcICQoL",
        plaintext: "{\"assistant_message_id\":\"55555555-5555-4555-8555-555555555555\",\"chat_id\":\"22222222-2222-4222-8222-222222222222\",\"content\":\"Recovered hello\",\"job_id\":\"44444444-4444-4444-8444-444444444444\",\"key_version\":7,\"turn_id\":\"33333333-3333-4333-8333-333333333333\"}",
        ciphertext: "I-wuvO5hWgfrssqM8SYZ7Ah8j2VaKaG9k4dXSnECLD7H07S2odaMlDIl1p5BwUUn0_qOoBoLPzdPiPttqTTNN7aD43Fwebbzt-Ol8kxBVuwGfBwYQFVfVrjgMokd6aMPJlhhT8tV91ugFSeYyzW4IWl7rpgDWUbhFc4bOu84fxABXBWumc2DApYuXb-4iieU7fawubxy0e2tBvHWLP9UQSS5-NxoXfNVqgM29kxHaJtZJrENGlptRyiiIbaSZBfdJMoJF8o7nC7DQq_dzTw-yeegyejjgGQvllYWtVLKM_QAtkCF3pQ3MqiEy-d1CeBgQ1mXcaQFhq3oTLT9VJ3DXM8a0_ZwtVE6KQvqodE"
    )
}
