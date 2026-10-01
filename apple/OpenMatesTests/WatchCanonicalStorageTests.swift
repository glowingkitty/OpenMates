// Synthetic Watch storage contracts: no provider, real account, or live socket.
import XCTest
@testable import OpenMates

@MainActor
final class WatchCanonicalStorageTests: XCTestCase {
    private func turn() throws -> WatchPendingTextSend {
        let inference: [String: Any] = ["chat_id": "chat", "turn_id": "turn",
            "message": ["message_id": "user", "content": "transient inference text"]]
        let preflight: [String: Any] = ["chat_id": "chat", "turn_id": "turn", "message_id": "user",
            "inference_request": inference, "expected_messages_v": 0,
            "encrypted_user_message": ["encrypted_content": "cipher-user", "created_at": 1],
            "encrypted_chat_metadata": ["encrypted_title": "cipher-title", "encrypted_chat_key": "wrapped"]]
        return .init(id: "turn", chatId: "chat", messageId: "user", encryptedContent: "cipher-user",
            encryptedChatKey: "wrapped", createdAt: "2026-01-01T00:00:00Z",
            preflightJSON: try JSONSerialization.data(withJSONObject: preflight),
            inferenceJSON: try JSONSerialization.data(withJSONObject: inference))
    }

    // contract-test: supporting surface=gui.apple assertions=apple-watch.chats.new-text-reply
    func testLegacyAdmissionMustStoreEncryptedUserPackageBeforeRetiringTurn() async throws {
        var calls: [String] = []
        try await WatchCanonicalStorage.sendTurn(turn(), request: { type, payload, responses, matches in
            calls.append(type)
            switch type {
            case "chat_turn_preflight": return ["turn_id": "turn", "preflight_id": "preflight", "state": "LEGACY"]
            case "chat_message_added": return ["chat_id": "chat", "user_message_id": "user", "ai_task_id": "assistant"]
            case "": return ["chat_id": "chat", "user_message_id": "user", "category": "ai", "title": "Generated title", "icon_names": ["sparkles"]]
            default:
                XCTAssertEqual(type, "encrypted_chat_metadata")
                XCTAssertEqual(payload["encrypted_content"] as? String, "cipher-user")
                XCTAssertEqual(payload["encrypted_title"] as? String, "cipher-Generated title")
                XCTAssertEqual(payload["task_id"] as? String, "assistant")
                XCTAssertEqual(payload["encrypted_icon"] as? String, "cipher-sparkles")
                XCTAssertEqual(payload["encrypted_chat_category"] as? String, "cipher-ai")
                XCTAssertEqual(payload["encrypted_sender_name"] as? String, "cipher-user")
                XCTAssertNil(payload["content"])
                let ack: [String: Any] = ["chat_id": "chat", "message_id": "user", "versions": ["messages_v": 1]]
                XCTAssertTrue(matches(ack))
                return ack
            }
        }, encryptMetadata: { "cipher-" + $0 }, validate: {})
        XCTAssertEqual(calls, ["chat_turn_preflight", "chat_message_added", "", "encrypted_chat_metadata"])
    }

    // contract-test: supporting surface=gui.apple assertions=apple-watch.chats.new-text-reply
    func testReplayedLegacyAdmissionWithoutTypingStillStoresUserWithoutPlaceholderTitle() async throws {
        var stored = false
        try await WatchCanonicalStorage.sendTurn(turn(), request: { type, payload, _, _ in
            switch type {
            case "chat_turn_preflight": return ["turn_id": "turn", "preflight_id": "preflight", "state": "LEGACY"]
            case "chat_message_added": return ["chat_id": "chat", "user_message_id": "user", "ai_task_id": "assistant"]
            case "": throw WatchChatRuntimeError.socketUnavailable
            default:
                XCTAssertEqual(type, "encrypted_chat_metadata")
                XCTAssertEqual(payload["encrypted_content"] as? String, "cipher-user")
                XCTAssertNil(payload["encrypted_title"])
                XCTAssertNil(payload["encrypted_icon"])
                XCTAssertEqual((payload["versions"] as? [String: Any])?["title_v"] as? Int, 0)
                stored = true
                return ["chat_id": "chat", "message_id": "user", "versions": ["messages_v": 1]]
            }
        }, encryptMetadata: { "cipher-" + $0 }, validate: {})
        XCTAssertTrue(stored)
    }

    // contract-test: supporting surface=gui.apple assertions=apple-watch.chats.new-text-reply
    func testCurrentPreflightStoresUserWithoutLegacyDuplicateWriteAndRejectsChangedAccount() async throws {
        var calls: [String] = []
        try await WatchCanonicalStorage.sendTurn(turn(), request: { type, _, _, _ in
            calls.append(type)
            return type == "chat_turn_preflight" ? ["preflight_id": "preflight", "state": "PREPARED"] : ["ai_task_id": "assistant"]
        }, encryptMetadata: { "cipher-" + $0 }, validate: {})
        XCTAssertEqual(calls, ["chat_turn_preflight", "chat_message_added"])
        calls = []
        var current = true
        do {
            try await WatchCanonicalStorage.sendTurn(turn(), request: { type, _, _, _ in
                calls.append(type); current = false
                return ["preflight_id": "preflight", "state": "PREPARED"]
            }, encryptMetadata: { "cipher-" + $0 }, validate: { if !current { throw CancellationError() } })
            XCTFail("Stale account cannot send inference after preflight")
        } catch is CancellationError { }
        XCTAssertEqual(calls, ["chat_turn_preflight"])
    }

    // contract-test: supporting surface=gui.apple assertions=chats.persistence.client-encrypted,apple-watch.chats.new-text-reply
    func testEmbedStorageAcknowledgementCannotRetireWrongRequestOrPartialKeys() throws {
        let payload: [String: Any] = ["keys": [["encrypted_embed_key": "cipher"]]]
        XCTAssertNoThrow(try WatchCanonicalStorage.validateEmbedStorageAcknowledgement(type: "store_embed_keys", payload: payload,
            acknowledgement: ["request_id": "request", "created_count": 1, "failed_count": 0], requestID: "request"))
        for ack: [String: Any] in [["request_id": "other", "created_count": 1, "failed_count": 0],
                                  ["request_id": "request", "created_count": 0, "failed_count": 1]] {
            XCTAssertThrowsError(try WatchCanonicalStorage.validateEmbedStorageAcknowledgement(type: "store_embed_keys", payload: payload,
                acknowledgement: ack, requestID: "request"))
        }
        XCTAssertThrowsError(try WatchCanonicalStorage.validateEmbedStorageAcknowledgement(type: "store_embed", payload: ["embed_id": "embed"],
            acknowledgement: ["request_id": "request", "embed_id": "other"], requestID: "request"))
    }

    private var job: WatchRecoveryJob { .init(id: "job", chatId: "chat", messageId: "assistant", turnId: "turn", keyVersion: 1) }

    // contract-test: supporting surface=gui.apple assertions=apple-watch.chats.new-text-reply,chats.persistence.client-encrypted
    func testCorrelatedServerRejectionReportsStageWithoutStartingCommit() async throws {
        var calls: [String] = []
        var inbox: [(type: String, payload: [String: Any])] = [
            ("error", ["turn_id": "other-turn", "code": "preflight_mismatch"]),
            ("error", ["turn_id": "turn", "code": "version_conflict"]),
        ]
        do {
            try await WatchCanonicalStorage.sendTurn(turn(), request: { type, _, responseTypes, matching in
                calls.append(type)
                let response = try WatchSocketResponses.takeMatchingResponse(from: &inbox,
                    requestType: type, responseTypes: responseTypes, matching: matching)
                return try XCTUnwrap(response)
            }, encryptMetadata: { "cipher-" + $0 }, validate: {})
            XCTFail("Rejected preflight must not authorize inference")
        } catch WatchChatRuntimeError.turnAdmissionFailure(let diagnostic) {
            XCTAssertEqual(diagnostic.stage, .preflight)
            XCTAssertEqual(diagnostic.reason, "version_conflict")
            XCTAssertFalse(diagnostic.invalidAcknowledgement)
        }
        XCTAssertEqual(calls, ["chat_turn_preflight"])
        XCTAssertEqual(inbox.count, 1)
        XCTAssertEqual(inbox.first?.payload["turn_id"] as? String, "other-turn")
    }

    // contract-test: supporting surface=gui.apple assertions=apple-watch.chats.new-text-reply
    func testWrongTurnErrorCannotSupplyResponseForCurrentAdmission() throws {
        var inbox: [(type: String, payload: [String: Any])] = [
            ("error", ["turn_id": "other-turn", "code": "version_conflict"]),
        ]
        let response = try WatchSocketResponses.takeMatchingResponse(from: &inbox,
            requestType: "chat_turn_preflight", responseTypes: ["chat_turn_preflight_ack"],
            matching: { $0["turn_id"] as? String == "turn" })
        XCTAssertNil(response)
        XCTAssertEqual(inbox.count, 1, "Other-turn errors remain queued for their own request")
    }

    // contract-test: supporting surface=gui.apple assertions=apple-watch.chats.new-text-reply
    func testMalformedPreflightAcknowledgementsHaveStaticReasonsAndDoNotCommit() async throws {
        let cases: [([String: Any], WatchTurnAcknowledgementIssue)] = [
            (["preflight_id": "preflight"], .missingState),
            (["state": "PREPARED"], .missingPreflightID),
            (["state": "untrusted-state-with-private-data", "preflight_id": "preflight"], .unexpectedState),
        ]
        for (ack, issue) in cases {
            var calls: [String] = []
            do {
                try await WatchCanonicalStorage.sendTurn(turn(), request: { type, _, _, _ in
                    calls.append(type); return ack
                }, encryptMetadata: { "cipher-" + $0 }, validate: {})
                XCTFail("Malformed acknowledgement cannot authorize inference")
            } catch WatchChatRuntimeError.turnAdmissionFailure(let diagnostic) {
                XCTAssertEqual(diagnostic.stage, .preflight)
                XCTAssertEqual(diagnostic.reason, issue.rawValue)
                XCTAssertTrue(diagnostic.invalidAcknowledgement)
            }
            XCTAssertEqual(calls, ["chat_turn_preflight"])
        }
    }

    // contract-test: supporting surface=gui.apple assertions=apple-watch.chats.new-text-reply
    func testCommitRejectionAndMalformedReceiptRemainDistinctFromPreflight() async throws {
        for malformed in [false, true] {
            var calls: [String] = []
            do {
                try await WatchCanonicalStorage.sendTurn(turn(), request: { type, _, responseTypes, matching in
                    calls.append(type)
                    if type == "chat_turn_preflight" { return ["state": "PREPARED", "preflight_id": "preflight"] }
                    if malformed { return ["turn_id": "turn"] }
                    var inbox: [(type: String, payload: [String: Any])] = [
                        ("error", ["turn_id": "turn", "code": "preflight_expired"]),
                    ]
                    let response = try WatchSocketResponses.takeMatchingResponse(from: &inbox,
                        requestType: type, responseTypes: responseTypes, matching: matching)
                    return try XCTUnwrap(response)
                }, encryptMetadata: { "cipher-" + $0 }, validate: {})
                XCTFail("Rejected or malformed commit must not retire a pending turn")
            } catch WatchChatRuntimeError.turnAdmissionFailure(let diagnostic) {
                XCTAssertEqual(diagnostic.stage, .commit)
                XCTAssertEqual(diagnostic.reason, malformed ? "missing_task_id" : "preflight_expired")
                XCTAssertEqual(diagnostic.invalidAcknowledgement, malformed)
            }
            XCTAssertEqual(calls, ["chat_turn_preflight", "chat_message_added"])
        }
    }

    // contract-test: supporting surface=gui.apple assertions=apple-watch.chats.new-text-reply,chats.persistence.client-encrypted
    func testAdmissionDiagnosticsAllowlistCodesAndExcludeAllServerPayloadData() throws {
        let sequence = NativeClientLogCollector.shared.entriesSnapshot(limit: 1).last?.sequence ?? 0
        let privateValue = "synthetic-private-payload-value"
        for rawCode: Any in [privateValue, "version_conflict " + privateValue, ["private": privateValue], 7] {
            var inbox: [(type: String, payload: [String: Any])] = [
                ("error", ["turn_id": "turn", "code": rawCode, "message": privateValue,
                           "chat_id": privateValue, "token": privateValue]),
            ]
            XCTAssertThrowsError(try WatchSocketResponses.takeMatchingResponse(from: &inbox,
                requestType: "chat_turn_preflight", responseTypes: ["chat_turn_preflight_ack"],
                matching: { $0["turn_id"] as? String == "turn" })) { error in
                guard case WatchChatRuntimeError.turnAdmissionFailure(let diagnostic) = error else { return XCTFail("Missing static diagnostic") }
                XCTAssertEqual(diagnostic.reason, "unrecognized_server_code")
                XCTAssertEqual(error.localizedDescription, "Message could not be saved")
            }
        }
        let entries = NativeClientLogCollector.shared.entriesAfter(sequence: sequence, limit: 20)
        XCTAssertEqual(entries.count, 4)
        for entry in entries {
            XCTAssertTrue(entry.message.contains("stage_preflight=true"))
            XCTAssertTrue(entry.message.contains("reason_unrecognized_server_code=true"))
            XCTAssertFalse(entry.message.contains(privateValue))
            XCTAssertFalse(entry.message.contains("turn_id"))
            XCTAssertFalse(entry.message.contains("chat_id"))
            XCTAssertFalse(entry.message.contains("token"))
        }
    }
    private var chat: WatchChatSummary { .init(id: "chat", title: nil, lastMessageAt: nil, preview: nil, isPinned: false,
        encryptedTitle: "cipher-title", encryptedPreview: nil, encryptedChatKey: "wrapped", messagesV: 7) }
    private var claim: [String: Any] { ["job_id": "job", "chat_id": "chat", "assistant_message_id": "assistant",
        "turn_id": "turn", "chat_key_version": 1, "state": "LEASED", "lease_token": "synthetic-lease",
        "lease_generation": 2, "sealed_payload": "synthetic-sealed"] }

    // contract-test: supporting surface=gui.apple assertions=apple-watch.chats.new-text-reply,chats.completion.recovery-takeover
    func testCurrentCompletionClaimsLeaseAndOnlySendsCanonicalCiphertextPersist() async throws {
        var calls: [String] = []
        let result = try await WatchCanonicalStorage.recover(job, chat: chat, ownerID: "owner",
            request: { type, payload, _, _ in
                calls.append(type)
                if type == "recovery_job_claim" { return self.claim }
                XCTAssertEqual(type, "recovery_job_persist")
                XCTAssertEqual(payload["lease_token"] as? String, "synthetic-lease")
                XCTAssertEqual(payload["lease_generation"] as? Int, 2)
                XCTAssertEqual(payload["expected_messages_v"] as? Int, 7)
                let encrypted = try XCTUnwrap(payload["encrypted_assistant_message"] as? [String: Any])
                XCTAssertEqual(encrypted["client_message_id"] as? String, "assistant")
                XCTAssertEqual(encrypted["encrypted_content"] as? String, "ciphertext")
                XCTAssertNil(encrypted["content"])
                return ["job_id": "job", "chat_id": "chat", "assistant_message_id": "assistant",
                        "state": "TERMINAL", "committed_messages_v": 8]
            }, open: { _, bound, owner in
                XCTAssertEqual(bound.turnId, "turn"); XCTAssertEqual(owner, "owner")
                return .init(content: "private response", category: "ai", modelName: "model")
            }, encrypt: { _ in "ciphertext" }, validate: {})
        XCTAssertEqual(calls, ["recovery_job_claim", "recovery_job_persist"])
        XCTAssertEqual(result.message?.content, "private response")
        XCTAssertEqual(result.version, 8)
        XCTAssertFalse(result.requiresHydration)
    }

    // contract-test: supporting surface=gui.apple assertions=chats.completion.recovery-takeover
    func testRecoveryRejectsStaleAccountBeforePersistAndWrongLeaseAcknowledgement() async throws {
        var valid = true
        var calls: [String] = []
        do {
            _ = try await WatchCanonicalStorage.recover(job, chat: chat, ownerID: "owner", request: { type, _, _, _ in
                calls.append(type); return self.claim
            }, open: { _, _, _ in
                valid = false
                return .init(content: "private", category: nil, modelName: nil)
            }, encrypt: { _ in XCTFail("Stale account must not encrypt or persist completion"); return "cipher" },
                validate: { if !valid { throw CancellationError() } })
            XCTFail("Account replacement must retire claim")
        } catch is CancellationError { }
        XCTAssertEqual(calls, ["recovery_job_claim"])
        do {
            _ = try await WatchCanonicalStorage.recover(job, chat: chat, ownerID: "owner", request: { type, _, _, _ in
                if type == "recovery_job_claim" { return self.claim }
                return ["job_id": "job", "state": "TERMINAL", "committed_messages_v": 8, "lease_generation": 3]
            }, open: { _, _, _ in .init(content: "private", category: nil, modelName: nil) },
                encrypt: { _ in "ciphertext" }, validate: {})
            XCTFail("Conflicting lease generation cannot fabricate completion")
        } catch WatchChatRuntimeError.preflightRejected { }
    }

    // contract-test: supporting surface=gui.apple assertions=chats.completion.recovery-takeover
    func testTerminalLeaseFromAnotherDeviceRequiresAuthoritativeHydration() async throws {
        let result = try await WatchCanonicalStorage.recover(job, chat: chat, ownerID: "owner", request: { type, _, _, _ in
            XCTAssertEqual(type, "recovery_job_claim")
            return ["job_id": "job", "state": "TERMINAL", "committed_messages_v": 8]
        }, open: { _, _, _ in XCTFail("Terminal claim does not contain sealed content"); throw CancellationError() },
            encrypt: { _ in XCTFail("No duplicate encrypted write"); return "cipher" }, validate: {})
        XCTAssertNil(result.message)
        XCTAssertTrue(result.requiresHydration)
        XCTAssertEqual(result.version, 8)
    }
}
