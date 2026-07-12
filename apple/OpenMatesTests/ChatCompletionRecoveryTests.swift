// Cross-runtime chat completion recovery cryptographic vector tests.
// Values mirror backend/tests/fixtures/chat_completion_recovery_vectors.json.
// The fixture is encoded here because it is outside the Apple test resources.
// All values are deterministic synthetic test material, never production data.
// Exact byte matching guards HKDF, X25519, AES-GCM, base64url, and AAD parity.

import CryptoKit
import XCTest
@testable import OpenMates

final class ChatCompletionRecoveryTests: XCTestCase {
    @MainActor
    func testSavedChatCommitsTheExactPreflightInferencePayload() async throws {
        let transport = RecoveryRecordingTransport(responses: [
            "chat_turn_preflight_ack": [["turn_id": "turn-1", "preflight_id": "preflight-1", "state": "PREPARED"]]
        ])
        let inferenceRequest: [String: Any] = [
            "chat_id": "chat-1",
            "message": ["message_id": "message-1", "content": "plaintext"],
            "turn_id": "turn-1",
            "recovery_public_key": "public-key",
            "chat_key_version": 1,
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

    @MainActor
    func testRecoveryAvailabilityClaimsOnlyWithUnlockedKeyAndEligibleDevice() async throws {
        let fixture = try makeRecoveryFixture()
        await fixture.coordinator.markInitialSyncReady()
        await fixture.coordinator.handleAvailableJobs(fixture.availability)
        XCTAssertEqual(fixture.transport.sentTypes, ["recovery_job_claim", "recovery_job_persist"])
        XCTAssertEqual(fixture.persisted.messages.count, 1)
    }

    @MainActor
    func testClaimedSealedCompletionIsReencryptedPersistedOnceAndAcknowledged() async throws {
        let fixture = try makeRecoveryFixture()
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

    @MainActor
    func testDuplicateRecoveryAvailabilityIsIdempotent() async throws {
        let fixture = try makeRecoveryFixture()
        await fixture.coordinator.markInitialSyncReady()
        await fixture.coordinator.handleAvailableJobs(fixture.availability)
        await fixture.coordinator.handleAvailableJobs(fixture.availability)
        XCTAssertEqual(fixture.transport.sentTypes.filter { $0 == "recovery_job_claim" }.count, 1)
        XCTAssertEqual(fixture.persisted.messages.count, 1)
    }

    @MainActor
    func testRevokedDeviceDoesNotClaimRecoveryJob() async throws {
        let fixture = try makeRecoveryFixture(isEligible: false)
        await fixture.coordinator.handleAvailableJobs(fixture.availability)
        XCTAssertTrue(fixture.transport.sentTypes.isEmpty)
    }

    @MainActor
    func testLockedChatKeyDoesNotClaimRecoveryJob() async throws {
        let fixture = try makeRecoveryFixture(hasKey: false)
        await fixture.coordinator.markInitialSyncReady()
        await fixture.coordinator.handleAvailableJobs(fixture.availability)
        XCTAssertTrue(fixture.transport.sentTypes.isEmpty)
    }

    @MainActor
    func testRecoveryReceivedBeforeInitialSyncQueuesUntilReady() async throws {
        let fixture = try makeRecoveryFixture()
        await fixture.coordinator.handleAvailableJobs(fixture.availability)
        XCTAssertTrue(fixture.transport.sentTypes.isEmpty)

        await fixture.coordinator.markInitialSyncReady()
        XCTAssertEqual(fixture.transport.sentTypes, ["recovery_job_claim", "recovery_job_persist"])
    }

    @MainActor
    func testTerminalRecoveryStreamRoutesToCoordinatorPersistence() async throws {
        let fixture = try makeRecoveryFixture()
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

    @MainActor
    func testRecoveryEnvelopeRejectsUnknownFields() async throws {
        let fixture = try makeRecoveryFixture(hasUnknownEnvelopeField: true)
        await fixture.coordinator.markInitialSyncReady()
        await fixture.coordinator.handleAvailableJobs(fixture.availability)

        XCTAssertEqual(fixture.transport.sentTypes, ["recovery_job_claim"])
        XCTAssertTrue(fixture.persisted.messages.isEmpty)
    }

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
        hasUnknownEnvelopeField: Bool = false
    ) throws -> RecoveryFixture {
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
        let transport = RecoveryRecordingTransport(responses: [
            "recovery_job_claimed": [[
                "job_id": vector.jobId,
                "state": "LEASED",
                "lease_token": "synthetic-lease-token",
                "lease_generation": 2,
                "chat_id": vector.chatId,
                "turn_id": vector.turnId,
                "assistant_message_id": vector.assistantMessageId,
                "chat_key_version": Int(vector.keyVersion),
                "sealed_payload": sealedPayload,
            ]],
            "recovery_job_persisted": [[
                "job_id": vector.jobId,
                "state": "TERMINAL",
                "lease_generation": 2,
                "committed_messages_v": 8,
            ]],
        ])
        let persisted = RecoveryMessageRecorder()
        let key = SymmetricKey(data: try decodeBase64URL(vector.chatKey))
        let coordinator = ChatCompletionRecoveryCoordinator(
            transport: transport,
            authenticatedOwnerId: { vector.ownerId },
            isDeviceEligible: { isEligible },
            chatKey: { _ in hasKey ? key : nil },
            isChatKeyReady: { true },
            chatVersion: { _ in 7 },
            containsMessage: { chatId, messageId in
                persisted.messages.contains { $0.chatId == chatId && $0.id == messageId }
            },
            persistMessage: { persisted.messages.append($0) },
            applyCommittedMessagesVersion: { _, version in
                persisted.committedMessagesVersions.append(version)
            }
        )
        return RecoveryFixture(
            coordinator: coordinator,
            transport: transport,
            persisted: persisted,
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
    private(set) var sentTypes: [String] = []
    private(set) var sentPayloads: [[String: Any]] = []

    init(responses: [String: [[String: Any]]]) {
        self.responses = responses
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
    ) async throws -> [String: Any] {
        try await send(message)
        return try await waitForMessage(responseType, timeout: timeout, matching: predicate)
    }

    func waitForMessage(
        _ type: String,
        timeout: Duration,
        matching predicate: @escaping ([String: Any]) -> Bool
    ) async throws -> [String: Any] {
        guard let index = responses[type]?.firstIndex(where: predicate),
              let response = responses[type]?.remove(at: index) else {
            throw RecoveryTestError.missingResponse(type)
        }
        return response
    }
}

@MainActor
private final class RecoveryMessageRecorder {
    var messages: [Message] = []
    var committedMessagesVersions: [Int] = []
}

@MainActor
private struct RecoveryFixture {
    let coordinator: ChatCompletionRecoveryCoordinator
    let transport: RecoveryRecordingTransport
    let persisted: RecoveryMessageRecorder
    let availability: [String: Any]
}

private enum RecoveryTestError: Error {
    case missingResponse(String)
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
