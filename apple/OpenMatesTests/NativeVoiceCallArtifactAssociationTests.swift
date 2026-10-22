// Injected production outbox/controller coverage; no provider, microphone,
// server embed commit, physical route or cross-client execution is claimed.
import XCTest
import CryptoKit
@testable import OpenMates

@MainActor
final class NativeVoiceCallArtifactAssociationTests: XCTestCase {
    private let scope = NativeVoiceCallScope(accountID: "artifact-owner", profileID: "development",
        workspaceGeneration: UUID(), chatID: "12345678-1234-4123-8123-123456789012", mateCategory: "general")

    // contract-test: supporting surface=gui.apple assertions=video-call.chat.skill-integration,video-call.privacy
    func testReferenceValidationRejectsUnknownChildMismatchAndOversizedMetadata() throws {
        let valid: NativeVoiceCallFrame = ["embed_id": .string("artifact-parent"), "type": .string("code"), "title": .string("Synthetic title")]
        let parsed = try NativeVoiceCallArtifactReference(validating: valid, expectedID: "artifact-parent")
        XCTAssertEqual(parsed.embedID, "artifact-parent")
        XCTAssertTrue(try parsed.markdown.hasPrefix("```json\n"))
        XCTAssertThrowsError(try NativeVoiceCallArtifactReference(validating: valid, expectedID: "other"))
        let invalid: [NativeVoiceCallFrame] = [
            ["embed_id": .string("artifact-parent"), "type": .string("unknown")],
            ["embed_id": .string("artifact-parent\n"), "type": .string("code")],
            ["embed_id": .string("artifact-parent"), "type": .string("code"), "parent_embed_id": .string("other")],
            ["embed_id": .string("artifact-parent"), "type": .string("code"), "title": .string(String(repeating: "x", count: 16_001))]
        ]
        for fields in invalid { XCTAssertThrowsError(try NativeVoiceCallArtifactReference(validating: fields)) }
        let child = try NativeVoiceCallArtifactReference.fromPayload(["embed_id": .string("child"), "type": .string("code"), "parent_embed_id": .string("parent")])
        XCTAssertNil(child)
    }

    // contract-test: supporting surface=gui.apple assertions=video-call.chat.skill-integration,video-call.chat.transcripts,video-call.privacy
    func testCommittedCardSurvivesFinalCorrectionAndIsEncryptedWithCanonicalContent() async throws {
        let (outbox, storage, crypto) = makeOutbox()
        try await outbox.transcript(scope: scope, value: speech("Original spoken answer", final: true))
        let associated = try await outbox.associateArtifact(scope: scope, value: association())
        XCTAssertEqual(associated.embedReferences.map(\.embedID), ["artifact-parent"])
        XCTAssertTrue(associated.text.contains("Original spoken answer"))
        try await outbox.transcript(scope: scope, value: speech("Corrected spoken answer", final: true))
        try await outbox.transcript(scope: scope, value: speech("Stale interim", final: false))
        let rows = await storage.rows
        let latest = try await outbox.publishedTranscript(scope: scope, callID: "artifact-call", messageID: "assistant")
        XCTAssertEqual(rows.first?.revision, 3)
        XCTAssertTrue(latest.text.hasPrefix("Corrected spoken answer"))
        XCTAssertEqual(latest.embedReferences.map(\.embedID), ["artifact-parent"])
        XCTAssertEqual(latest.text.components(separatedBy: "```json").count - 1, 1)
        XCTAssertFalse(latest.text.contains("Stale interim"))
        let frames = try await outbox.pendingFrames(scope: scope)
        XCTAssertEqual(frames.map { $0["revision"]?.number }, [1, 2, 3])
        XCTAssertTrue(frames.allSatisfy { $0["user_message_id"]?.string == "user" })
        let body = try await crypto.decrypt(try XCTUnwrap(frames.last?["encrypted_content"]?.string), scope: scope)
        XCTAssertEqual(body, latest.text)
        let raw = String(decoding: try JSONEncoder().encode(rows), as: UTF8.self)
        XCTAssertFalse(raw.contains("Private artifact title"))
        XCTAssertFalse(raw.contains("Corrected spoken answer"))
        XCTAssertNotNil(rows.first?.encryptedArtifactReferences)
    }

    // contract-test: supporting surface=gui.apple assertions=video-call.chat.skill-integration,video-call.chat.transcripts
    func testArtifactBeforeSpeechPersistsThenAcceptsRealSpeechTimestampWithoutLosingCard() async throws {
        let (outbox, storage, _) = makeOutbox()
        _ = try await outbox.associateArtifact(scope: scope, value: association(createdAt: 200))
        let artifactOnly = try await outbox.pendingFrames(scope: scope)
        XCTAssertEqual(artifactOnly.count, 1, "Committed artifact is durable even if speech never begins")
        try await outbox.transcript(scope: scope, value: speech("Progressive words", final: false, createdAt: 100))
        try await outbox.transcript(scope: scope, value: speech("Final words", final: true, createdAt: 100))
        let frames = try await outbox.pendingFrames(scope: scope)
        XCTAssertEqual(frames.map { $0["revision"]?.number }, [1, 2])
        let rows = await storage.rows
        XCTAssertEqual(rows.first?.createdAt, 200, "The already-persisted canonical timestamp stays stable")
        XCTAssertEqual(rows.first?.sourceCreatedAt, 100, "Provider timing remains a separate identity fence")
        let latest = try await outbox.publishedTranscript(scope: scope, callID: "artifact-call", messageID: "assistant")
        XCTAssertTrue(latest.text.hasPrefix("Final words"))
        XCTAssertEqual(latest.embedReferences.count, 1)
    }

    // contract-test: supporting surface=gui.apple assertions=video-call.chat.transcripts,video-call.lifecycle.recovery-and-billing,video-call.chat.skill-integration
    func testLateAssociationUsesNewExactRevisionAndReplayPreservesCiphertextAfterRelaunch() async throws {
        let (outbox, storage, crypto) = makeOutbox()
        try await outbox.transcript(scope: scope, value: speech("Saved spoken answer", final: true))
        let originalFrames = try await outbox.pendingFrames(scope: scope)
        let original = try XCTUnwrap(originalFrames.first)
        let accepted = try await outbox.acknowledge(scope: scope, frame: acknowledgement(original))
        XCTAssertTrue(accepted)
        _ = try await outbox.associateArtifact(scope: scope, value: association())
        let first = try await outbox.pendingFrames(scope: scope)
        _ = try await outbox.associateArtifact(scope: scope, value: association())
        let repeated = try await outbox.pendingFrames(scope: scope)
        XCTAssertEqual(first, repeated, "Duplicate delivery creates no new request, revision or randomized ciphertext")
        XCTAssertEqual(first.first?["revision"]?.number, 2)
        let oldACK = try await outbox.acknowledge(scope: scope, frame: acknowledgement(original))
        XCTAssertFalse(oldACK)
        let reopened = NativeVoiceCallOutbox(crypto: crypto, storage: storage, isCurrent: { _ in true }, checkpoint: { _, _, _ in throw NativeVoiceCallError.persistenceFailed })
        let replay = try await reopened.pendingFrames(scope: scope)
        XCTAssertEqual(replay, first)
        let restored = try await reopened.publishedTranscript(scope: scope, callID: "artifact-call", messageID: "assistant")
        XCTAssertEqual(restored.embedReferences.map(\.embedID), ["artifact-parent"])
        XCTAssertEqual(restored.modelName, "synthetic-model")
        let newACK = try await reopened.acknowledge(scope: scope, frame: acknowledgement(try XCTUnwrap(first.first)))
        XCTAssertTrue(newACK)
        let proof = try await reopened.confirmedProof(scope: scope, callID: "artifact-call", messageID: "assistant", revision: 2)
        XCTAssertEqual(proof?.ciphertext, first.first?["encrypted_content"]?.string)
    }

    // contract-test: supporting surface=gui.apple assertions=video-call.chat.transcripts,video-call.chat.skill-integration
    func testOlderStoredRowsDecodeAndGainAssociationWithoutChangingOriginalIdentity() async throws {
        let (outbox, storage, crypto) = makeOutbox()
        let ciphertext = try await crypto.encrypt("Legacy spoken answer", scope: scope)
        let legacy: NativeVoiceCallFrame = ["callID": .string("artifact-call"), "messageID": .string("assistant"),
            "role": .string("assistant"), "createdAt": .number(100), "userMessageID": .string("user"),
            "revision": .number(1), "ciphertext": .string(ciphertext), "final": .bool(true),
            "interrupted": .bool(false), "typedPending": .bool(false), "pending": .array([])]
        let row = try JSONDecoder().decode(NativeVoiceCallStoredRow.self, from: JSONEncoder().encode(legacy))
        XCTAssertNil(row.encryptedArtifactReferences)
        await storage.save([row], scope: scope)
        let result = try await outbox.associateArtifact(scope: scope, value: association())
        XCTAssertTrue(result.text.hasPrefix("Legacy spoken answer"))
        XCTAssertEqual(result.embedReferences.count, 1)
        let frames = try await outbox.pendingFrames(scope: scope)
        XCTAssertEqual(frames.first?["revision"]?.number, 2)
        XCTAssertEqual(frames.first?["user_message_id"]?.string, "user")
        XCTAssertEqual(frames.first?["created_at"]?.number, 100)
    }

    // contract-test: supporting surface=gui.apple assertions=video-call.chat.fixed-binding,video-call.privacy,video-call.chat.skill-integration
    func testAssociationCannotRetargetUserCallRoleOrInvalidatedScope() async throws {
        let (outbox, storage, _) = makeOutbox()
        try await outbox.transcript(scope: scope, value: speech("Original", final: true))
        let wrongCall = try association(callID: "other-call"), wrongUser = try association(userID: "other-user")
        for value in [wrongCall, wrongUser] {
            do { _ = try await outbox.associateArtifact(scope: scope, value: value); XCTFail("Foreign association must fail") }
            catch { XCTAssertEqual(error as? NativeVoiceCallError, .persistenceFailed) }
        }
        try await outbox.stageTyped(scope: scope, callID: "artifact-call", messageID: "typed-user", text: "Unsent", createdAt: 100)
        do {
            _ = try await outbox.associateArtifact(scope: scope, value: association(assistantID: "typed-user")); XCTFail("User row cannot become assistant artifact")
        } catch { XCTAssertEqual(error as? NativeVoiceCallError, .persistenceFailed) }
        let denied = NativeVoiceCallOutbox(crypto: ArtifactCryptoFixture(), storage: storage, isCurrent: { _ in false }, checkpoint: { _, _, _ in throw NativeVoiceCallError.persistenceFailed })
        do { _ = try await denied.associateArtifact(scope: scope, value: association()); XCTFail("Revoked scope must fail") }
        catch { XCTAssertEqual(error as? NativeVoiceCallError, .scopeChanged) }
        let rows = await storage.rows
        XCTAssertEqual(rows.first?.revision, 1)
        XCTAssertNil(rows.first?.encryptedArtifactReferences)
    }

    // contract-test: supporting surface=gui.apple assertions=video-call.chat.skill-integration,video-call.chat.fixed-binding,video-call.privacy
    func testControllerRequiresIssuedExactOriginAndAllowsAdmittedCompletionAfterHangup() async throws {
        let transport = ArtifactTransportFixture(), audio = ArtifactAudioFixture()
        let (outbox, storage, _) = makeOutbox()
        let live = expectation(description: "Live synthetic call"), issued = expectation(description: "Actual broker frame forwarded")
        let controller = NativeVoiceCallController(environment: environment(), audio: audio, persistence: outbox,
            transportFactory: { transport }, eventHandler: { event in
                if case .state(let state) = event, state.status == .live { live.fulfill() }
                if case .tool(let frame) = event, frame["type"]?.string == "voice_embed" { issued.fulfill() }
            })
        try await controller.start(scope: scope)
        try await transport.push(["type": .string("ready"), "call_id": .string("artifact-call"), "provider": .string("mistral"), "model": .string("voxtral-mini-transcribe-realtime-3-0"),
            "mate_category": .string("general"), "input_sample_rate": .number(16_000), "output_sample_rate": .number(24_000), "billing_basis": .string("speech_duration_and_chat_usage"), "rates": .object(["stt_credits_per_started_minute": .number(10)])])
        await fulfillment(of: [live], timeout: 2)
        do {
            try await controller.associateCommittedArtifact(scope: scope, callID: "artifact-call", functionCallID: "function", assistantMessageID: "assistant", userMessageID: "user", reference: reference())
            XCTFail("A reference alone is not an issued broker event")
        } catch { XCTAssertEqual(error as? NativeVoiceCallError, .scopeChanged) }
        try await transport.push(["type": .string("voice_embed"), "call_id": .string("artifact-call"), "function_call_id": .string("function"),
            "assistant_message_id": .string("assistant"), "user_message_id": .string("user"), "created_at": .number(100),
            "payload": .object(reference().merging(["chat_id": .string(scope.chatID), "message_id": .string("assistant"), "content": .string("synthetic payload")]) { _, next in next })])
        await fulfillment(of: [issued], timeout: 2)
        let beforeCommit = await storage.rows
        XCTAssertTrue(beforeCommit.isEmpty, "Receiving a processing/reference event never certifies a commit")
        do {
            try await controller.associateCommittedArtifact(scope: scope, callID: "artifact-call", functionCallID: "function", assistantMessageID: "assistant", userMessageID: "foreign-user", reference: reference())
            XCTFail("Committed callback cannot change causal user")
        } catch { XCTAssertEqual(error as? NativeVoiceCallError, .scopeChanged) }
        await controller.hangup()
        // Injected callback stands in only for the app's separately tested actual
        // durable-embed receipt. This test does not prove a server commit.
        try await controller.associateCommittedArtifact(scope: scope, callID: "artifact-call", functionCallID: "function", assistantMessageID: "assistant", userMessageID: "user", reference: reference())
        let rows = await storage.rows
        XCTAssertEqual(rows.count, 1)
        XCTAssertEqual(rows.first?.callID, "artifact-call")
        XCTAssertEqual(rows.first?.userMessageID, "user")
        XCTAssertEqual(rows.first?.revision, 1)
    }

    private func reference() -> NativeVoiceCallFrame {
        ["embed_id": .string("artifact-parent"), "type": .string("code"), "title": .string("Private artifact title"), "status": .string("finished")]
    }
    private func association(callID: String = "artifact-call", assistantID: String = "assistant", userID: String = "user", createdAt: Int = 100) throws -> NativeVoiceCallArtifactAssociation {
        .init(callID: callID, assistantMessageID: assistantID, userMessageID: userID,
            reference: try NativeVoiceCallArtifactReference(validating: reference()), createdAt: createdAt,
            modelName: "synthetic-model", mateCategory: "general", mateName: "Synthetic Mate")
    }
    private func speech(_ text: String, final: Bool, createdAt: Int = 100) -> NativeVoiceCallTranscript {
        .init(callID: "artifact-call", messageID: "assistant", role: .assistant, text: text, final: final, interrupted: false,
            userMessageID: "user", createdAt: createdAt, modelName: "synthetic-model", mateCategory: "general", mateName: "Synthetic Mate")
    }
    private func acknowledgement(_ frame: NativeVoiceCallFrame) -> NativeVoiceCallFrame {
        var value = frame; value["type"] = .string("call_message_confirmed"); value["outcome"] = .string("created"); return value
    }
    private func makeOutbox() -> (NativeVoiceCallOutbox, ArtifactStorageFixture, NativeVoiceCallChatCryptography) {
        let key = SymmetricKey(size: .bits256), storage = ArtifactStorageFixture()
        let crypto = NativeVoiceCallChatCryptography(key: { _ in key }, isCurrent: { _ in true })
        return (NativeVoiceCallOutbox(crypto: crypto, storage: storage, isCurrent: { _ in true }, checkpoint: { _, _, _ in [:] }), storage, crypto)
    }
    private func environment() -> NativeVoiceCallEnvironment {
        .init(isCurrent: { _ in true }, ensureConsent: { _ in }, authentication: { _ in
            .init(apiBaseURL: URL(string: "https://api.example.invalid")!, webOrigin: "https://example.invalid", sessionID: "synthetic", webSocketToken: "synthetic", nativeHeaders: [:])
        }, context: { _ in try .init(messages: [], mateCategory: "general", canonicalRangeComplete: true) }, now: { Date(timeIntervalSince1970: 100) })
    }
}

private actor ArtifactStorageFixture: NativeVoiceCallOutboxStorage {
    private(set) var rows: [NativeVoiceCallStoredRow] = []
    func load(scope: NativeVoiceCallScope) -> [NativeVoiceCallStoredRow] { rows }
    func save(_ rows: [NativeVoiceCallStoredRow], scope: NativeVoiceCallScope) { self.rows = rows }
}
private struct ArtifactCryptoFixture: NativeVoiceCallCryptography {
    func encrypt(_ text: String, scope: NativeVoiceCallScope) -> String { Data(text.utf8).base64EncodedString() }
    func decrypt(_ ciphertext: String, scope: NativeVoiceCallScope) throws -> String { throw NativeVoiceCallError.persistenceFailed }
}
private actor ArtifactTransportFixture: NativeVoiceCallTransport {
    private var queued: [String] = []
    private var waiter: CheckedContinuation<String, Error>?
    func connect(_ request: URLRequest) {}
    func send(_ text: String) {}
    func receive() async throws -> String {
        if !queued.isEmpty { return queued.removeFirst() }
        return try await withCheckedThrowingContinuation { waiter = $0 }
    }
    func close() { let pending = waiter; waiter = nil; pending?.resume(throwing: NativeVoiceCallError.connectionLost) }
    func push(_ frame: NativeVoiceCallFrame) throws {
        let text = try NativeVoiceCallWire.encode(frame)
        if let pending = waiter { waiter = nil; pending.resume(returning: text) } else { queued.append(text) }
    }
}
private actor ArtifactAudioFixture: NativeVoiceCallAudio {
    func reserve(scope: NativeVoiceCallScope) {}
    func start(input: @escaping @Sendable (Data) async -> Void, failure: @escaping @Sendable (NativeVoiceCallError) async -> Void) {}
    func setMicrophoneEnabled(_ enabled: Bool) {}
    func play(_ pcm16: Data, sampleRate: Int) {}
    func interruptPlayback() {}
    func stop() {}
}
