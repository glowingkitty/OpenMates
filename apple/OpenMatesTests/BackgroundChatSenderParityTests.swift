// Unit coverage for Apple background chat sender parity.
// The notification and share-extension paths run outside the foreground chat UI,
// so these tests keep coverage at the deterministic payload-contract layer. They
// avoid network calls, credentials, plaintext chat content, and raw encryption
// keys while guarding the storage package sent after assistant task startup.

import CoreFoundation
import XCTest
@testable import OpenMates

final class BackgroundChatSenderParityTests: XCTestCase {
    // contract-test: supporting surface=gui.apple assertions=sync.surface.semantic-parity
    func testRecentDestinationsDecodeKeyBearingPhaseOneAndOrderParentsByRecency() throws {
        let data = Data(#"""
        {"type":"phase_1_last_chat_ready","payload":{
          "chat_details":{"id":"older","created_at":100,"last_message_timestamp":100,"encrypted_chat_key":"wrapped-older"},
          "recent_chat_metadata":[
            {"id":"newer","created_at":200,"last_message_timestamp":200,"encrypted_chat_key":"wrapped-newer","encrypted_title":"ciphertext"},
            {"id":"child","created_at":300,"parent_id":"newer","is_sub_chat":true},
            {"id":"newer","created_at":200}
          ]}}
        """#.utf8)
        let chats = try XCTUnwrap(BackgroundChatSender.recentChats(from: data, limit: 12))
        XCTAssertEqual(chats.map(\.id), ["newer", "older"])
        XCTAssertEqual(chats.first?.encryptedChatKey, "wrapped-newer")
        XCTAssertEqual(chats.first?.encryptedTitle, "ciphertext")
        XCTAssertEqual(try BackgroundChatSender.recentChats(from: data, limit: 1)?.map(\.id), ["newer"])
    }

    // contract-test: supporting surface=gui.apple assertions=sync.surface.semantic-parity
    func testRecentDestinationsDistinguishEmptySnapshotFromUnrelatedMetadataOnlyEvents() throws {
        let empty = Data(#"{"type":"phase_1_last_chat_ready","payload":{"chat_details":null,"recent_chat_metadata":[]}}"#.utf8)
        XCTAssertEqual(try BackgroundChatSender.recentChats(from: empty, limit: 12)?.count, 0)
        let metadataOnly = Data(#"{"type":"phase_2_last_20_chats_ready","payload":{"chats":[{"chat_details":{"id":"chat"}}]}}"#.utf8)
        XCTAssertNil(try BackgroundChatSender.recentChats(from: metadataOnly, limit: 12))
        let unrelated = Data(#"{"type":"phased_sync_complete","payload":{"phase":"phase1"}}"#.utf8)
        XCTAssertNil(try BackgroundChatSender.recentChats(from: unrelated, limit: 12))
    }

    // contract-test: supporting surface=gui.apple assertions=sync.surface.semantic-parity
    func testRecentDestinationsRejectMalformedSnapshotInsteadOfReportingEmptySuccess() {
        let malformed = Data(#"{"type":"phase_1_last_chat_ready","payload":{"recent_chat_metadata":[{"encrypted_title":"ciphertext"}]}}"#.utf8)
        XCTAssertThrowsError(try BackgroundChatSender.recentChats(from: malformed, limit: 12))
    }

    // contract-test: supporting surface=gui.apple assertions=sync.surface.semantic-parity
    func testDeadlineClosesTransportWhoseReceiveIgnoresTaskCancellation() async throws {
        let transport = SuspendedBackgroundTransport()
        let startedAt = Date()
        let data: Data? = try await BackgroundChatDeadline.run(before: Date().addingTimeInterval(0.05), operation: {
            try await transport.receive()
        }, cancel: { transport.close() })
        XCTAssertNil(data)
        XCTAssertTrue(transport.isClosed)
        XCTAssertLessThan(Date().timeIntervalSince(startedAt), 2)
    }

    // contract-test: supporting surface=gui.apple assertions=sync.surface.semantic-parity
    func testCallerCancellationClosesPendingBackgroundReceive() async {
        let transport = SuspendedBackgroundTransport()
        let operation = Task {
            try await BackgroundChatDeadline.run(before: Date().addingTimeInterval(30), operation: {
                try await transport.receive()
            }, cancel: { transport.close() })
        }
        try? await Task.sleep(nanoseconds: 20_000_000)
        operation.cancel()
        do { _ = try await operation.value; XCTFail("Cancelled receive must fail") }
        catch { XCTAssertTrue(error is CancellationError || transport.isClosed) }
        XCTAssertTrue(transport.isClosed)
    }

    // contract-test: supporting surface=gui.apple assertions=sync.surface.semantic-parity
    func testSuccessfulBackgroundReceiveKeepsTransportOpen() async throws {
        let transport = SuspendedBackgroundTransport()
        let data: Data? = try await BackgroundChatDeadline.run(before: Date().addingTimeInterval(1), operation: {
            Data([1, 2, 3])
        }, cancel: { transport.close() })
        XCTAssertEqual(data, Data([1, 2, 3]))
        XCTAssertFalse(transport.isClosed)
    }

    // contract-test: supporting surface=gui.apple assertions=sync.access.first-party-authenticated,sync.surface.semantic-parity
    func testBackgroundSocketIdentityCannotReplaceForegroundOrAnotherExtensionSocket() throws {
        let nativeSessionId = "logical-native-session"
        let first = BackgroundChatSocketIdentity.routingSessionId(nativeSessionId: nativeSessionId)
        let second = BackgroundChatSocketIdentity.routingSessionId(nativeSessionId: nativeSessionId)
        XCTAssertNotEqual(first, nativeSessionId)
        XCTAssertNotEqual(second, nativeSessionId)
        XCTAssertNotEqual(first, second)
        XCTAssertTrue(first.hasPrefix(nativeSessionId + ":background:"))
        // The authenticated HTTP request still uses the original logical ID.
        let request = SessionProbe(sessionId: nativeSessionId,
            deviceInfo: DeviceInfoProbe(os: "iOS", deviceModel: "iPhone", appVersion: "1.0"))
        let payload = try XCTUnwrap(JSONSerialization.jsonObject(with: BackgroundChatHTTPContract.makeEncoder().encode(request)) as? [String: Any])
        XCTAssertEqual(payload["session_id"] as? String, nativeSessionId)
    }

    // contract-test: supporting surface=gui.apple assertions=sync.access.first-party-authenticated,sync.surface.semantic-parity
    func testRecentChatSyncRequestIncludesRequiredPersonalContextEpochOnTheWire() throws {
        let request = BackgroundChatSyncContract.recentChatsRequest
        let data = try JSONSerialization.data(withJSONObject: request)
        let payload = try XCTUnwrap(JSONSerialization.jsonObject(with: data) as? [String: Any])
        XCTAssertEqual(payload["phase"] as? String, "phase1")
        XCTAssertEqual(payload["context_epoch"] as? Int, 0)
        let contextEpoch = try XCTUnwrap(request["context_epoch"])
        XCTAssertTrue(type(of: contextEpoch) == Int.self, "Context epoch must be an integer rather than a Boolean")
        XCTAssertNil(payload["team_id"])
        XCTAssertEqual((payload["client_chat_versions"] as? [String: Int])?.count, 0)
        XCTAssertEqual(payload["client_chat_ids"] as? [String], [])
        XCTAssertEqual(payload["client_embed_ids"] as? [String], [])
        XCTAssertEqual(payload["client_suggestions_count"] as? Int, 0)
    }

    // contract-test: supporting surface=gui.apple assertions=sync.surface.semantic-parity
    func testRecentChatServerRejectionFailsImmediatelyWithoutExposingDiagnosticText() {
        let rejection = Data(#"{"type":"error","payload":{"message":"context_epoch must be a non-negative integer; private diagnostic detail"}}"#.utf8)
        XCTAssertThrowsError(try BackgroundChatSender.recentChats(from: rejection, limit: 12)) { error in
            guard case BackgroundChatSendError.recentChatsRejected = error else {
                return XCTFail("Server rejection must use the bounded recent-chat error")
            }
            XCTAssertEqual(error.localizedDescription, "Recent chats could not load. Please try again or send to New Chat.")
            XCTAssertFalse(error.localizedDescription.contains("private diagnostic"))
        }
    }

    // contract-test: supporting surface=gui.apple assertions=chats.persistence.client-encrypted,chats.surface.semantic-parity
    func testAcceptedExistingTaskCommitsStorageBeforeAnyMetadataTimeoutClosesSocket() async throws {
        let accepted = Data(#"{"type":"ai_task_initiated","payload":{"chat_id":"existing","user_message_id":"message","ai_task_id":"accepted-task"}}"#.utf8)
        let transport = AssistantStartTransport(frames: [accepted])
        let sender = BackgroundChatSender()
        let result = try await sender.waitForAssistantStart(chatId: "existing", userMessageId: "message",
            requiresCompleteNewChatMetadata: false, receive: { deadline in try await transport.receive(before: deadline) })
        let storage = try XCTUnwrap(result)
        XCTAssertEqual(storage.taskId, "accepted-task")
        XCTAssertNil(storage.metadata.title)
        try await transport.sendEncryptedStorage(taskId: storage.taskId)
        let state = await transport.state
        XCTAssertEqual(state.receives, 1, "An accepted existing task must not wait for optional metadata")
        XCTAssertEqual(state.storedTaskId, "accepted-task")
        XCTAssertFalse(state.closed, "Storage must use the still-open socket")
    }

    // contract-test: supporting surface=gui.apple assertions=chats.persistence.client-encrypted,chats.surface.semantic-parity
    func testAcceptedNewTaskStillWaitsForCompleteMetadataBeforeStorage() async throws {
        let accepted = Data(#"{"type":"ai_task_initiated","payload":{"chat_id":"new","user_message_id":"message","ai_task_id":"accepted-task"}}"#.utf8)
        let metadata = Data(#"{"type":"ai_typing_started","payload":{"chat_id":"new","user_message_id":"message","title":"Public article summary","category":"web"}}"#.utf8)
        let transport = AssistantStartTransport(frames: [accepted, metadata])
        let sender = BackgroundChatSender()
        let result = try await sender.waitForAssistantStart(chatId: "new", userMessageId: "message",
            requiresCompleteNewChatMetadata: true, receive: { deadline in try await transport.receive(before: deadline) })
        let storage = try XCTUnwrap(result)
        XCTAssertEqual(storage.metadata.title, "Public article summary")
        XCTAssertEqual(storage.metadata.category, "web")
        try await transport.sendEncryptedStorage(taskId: storage.taskId)
        let state = await transport.state
        XCTAssertEqual(state.receives, 2)
        XCTAssertFalse(state.closed)
        XCTAssertEqual(state.storedTaskId, "accepted-task")
    }

    // contract-test: supporting surface=gui.apple assertions=chats.persistence.client-encrypted,chats.surface.semantic-parity
    func testAcceptedNewTaskWithoutMetadataFailsInsteadOfPersistingIncompleteChat() async {
        let accepted = Data(#"{"type":"ai_task_initiated","payload":{"chat_id":"new","user_message_id":"message","ai_task_id":"accepted-task"}}"#.utf8)
        let transport = AssistantStartTransport(frames: [accepted])
        let sender = BackgroundChatSender()
        do {
            _ = try await sender.waitForAssistantStart(chatId: "new", userMessageId: "message",
                requiresCompleteNewChatMetadata: true, receive: { deadline in try await transport.receive(before: deadline) })
            XCTFail("New chats require complete metadata before storage")
        } catch {
            guard case BackgroundChatSendError.incompleteNewChatMetadata = error else {
                return XCTFail("Expected bounded incomplete metadata failure")
            }
        }
        let state = await transport.state
        XCTAssertNil(state.storedTaskId)
        XCTAssertTrue(state.closed)
    }

    // contract-test: supporting surface=gui.apple assertions=chats.persistence.client-encrypted,chats.surface.semantic-parity
    func testGlobalCutoverRejectionStopsAssistantWaitImmediatelyWithActionableError() async {
        let frame = Data(#"{"type":"error","payload":{"code":"client_update_required","message":"untrusted server diagnostic"}}"#.utf8)
        let transport = AssistantStartTransport(frames: [frame])
        let sender = BackgroundChatSender()
        do {
            _ = try await sender.waitForAssistantStart(chatId: "new", userMessageId: "message",
                requiresCompleteNewChatMetadata: true, receive: { deadline in try await transport.receive(before: deadline) })
            XCTFail("Cutover rejection must not wait for an assistant timeout")
        } catch {
            guard case BackgroundChatSendError.serverRejected(.updateRequired) = error else {
                return XCTFail("Expected bounded client update rejection")
            }
            XCTAssertEqual(error.localizedDescription, "Update OpenMates before sending to a saved chat.")
            XCTAssertFalse(error.localizedDescription.contains("untrusted"))
        }
        let state = await transport.state
        XCTAssertEqual(state.receives, 1)
        XCTAssertNil(state.storedTaskId)
        XCTAssertFalse(state.closed)
    }

    // contract-test: supporting surface=gui.apple assertions=chats.surface.semantic-parity
    func testAssistantWaitIgnoresRejectionForDifferentChatAndMessage() async throws {
        let otherChat = Data(#"{"type":"error","payload":{"code":"ai_dispatch_failed","chat_id":"other","message_id":"message"}}"#.utf8)
        let otherMessage = Data(#"{"type":"error","payload":{"code":"ai_dispatch_failed","chat_id":"existing","message_id":"other"}}"#.utf8)
        let accepted = Data(#"{"type":"ai_task_initiated","payload":{"chat_id":"existing","user_message_id":"message","ai_task_id":"accepted-task"}}"#.utf8)
        let transport = AssistantStartTransport(frames: [otherChat, otherMessage, accepted])
        let sender = BackgroundChatSender()
        let result = try await sender.waitForAssistantStart(chatId: "existing", userMessageId: "message",
            requiresCompleteNewChatMetadata: false, receive: { deadline in try await transport.receive(before: deadline) })
        XCTAssertEqual(result?.taskId, "accepted-task")
        let state = await transport.state
        XCTAssertEqual(state.receives, 3)
        XCTAssertFalse(state.closed)
    }

    // contract-test: supporting surface=gui.apple assertions=chats.persistence.client-encrypted,chats.surface.semantic-parity
    func testStorageWaitPropagatesGlobalPauseInsteadOfIgnoringMissingChatIDs() async {
        let frame = Data(#"{"type":"error","payload":{"code":"inference_temporarily_paused","message":"untrusted server detail"}}"#.utf8)
        let transport = AssistantStartTransport(frames: [frame])
        let sender = BackgroundChatSender()
        do {
            try await sender.waitForStorageConfirmation(chatId: "chat", messageId: "message",
                receive: { deadline in try await transport.receive(before: deadline) })
            XCTFail("Global rejection cannot become a successful storage acknowledgement")
        } catch {
            guard case BackgroundChatSendError.serverRejected(.inferencePaused) = error else {
                return XCTFail("Expected bounded pause rejection")
            }
            XCTAssertEqual(error.localizedDescription, "Saved-chat sending is temporarily paused. Please retry shortly.")
        }
        let state = await transport.state
        XCTAssertEqual(state.receives, 1)
    }

    // contract-test: supporting surface=gui.apple assertions=chats.persistence.client-encrypted,chats.surface.semantic-parity
    func testStorageWaitIgnoresUnrelatedRejectionAndRequiresExactDurabilityAck() async throws {
        let unrelated = Data(#"{"type":"error","payload":{"code":"ai_dispatch_failed","chat_id":"other","message_id":"message"}}"#.utf8)
        let wrongAck = Data(#"{"type":"encrypted_metadata_stored","payload":{"chat_id":"chat","message_id":"other"}}"#.utf8)
        let stored = Data(#"{"type":"encrypted_metadata_stored","payload":{"chat_id":"chat","message_id":"message"}}"#.utf8)
        let transport = AssistantStartTransport(frames: [unrelated, wrongAck, stored])
        let sender = BackgroundChatSender()
        try await sender.waitForStorageConfirmation(chatId: "chat", messageId: "message",
            receive: { deadline in try await transport.receive(before: deadline) })
        let state = await transport.state
        XCTAssertEqual(state.receives, 3)
        XCTAssertFalse(state.closed)
    }

    // contract-test: supporting surface=gui.apple assertions=chats.persistence.client-encrypted
    func testBackgroundDiagnosticsNeverReturnArbitraryEventTypesOrErrorCodes() {
        XCTAssertEqual(BackgroundChatSendDiagnostics.safeEventType("private chat title"), "other")
        XCTAssertEqual(BackgroundChatSendDiagnostics.safeErrorCode("private server diagnostic"), "other")
        XCTAssertEqual(BackgroundChatSendDiagnostics.safeEventType("ai_task_initiated"), "ai_task_initiated")
        XCTAssertEqual(BackgroundChatSendDiagnostics.safeErrorCode("client_update_required"), "client_update_required")
        XCTAssertEqual(BackgroundChatSendDiagnostics.safeEventType(nil), "none")
        XCTAssertEqual(BackgroundChatSendDiagnostics.safeErrorCode(nil), "none")
        XCTAssertEqual(BackgroundChatServerRejection.from(code: "private server diagnostic"), .other)
    }


    // contract-test: supporting surface=gui.apple assertions=chats.persistence.client-encrypted,chats.surface.semantic-parity
    func testPreparedTurnPersistsCiphertextBeforeExactInferenceCommitAndRequiresTaskInitiated() async throws {
        let turn = try Self.preparedTurnFixture()
        let transport = PreparedTurnTransport(frames: [
            Self.preflightAck("PREPARED"),
            Self.frame("message_queued", ["chat_id": "chat", "user_message_id": "message", "task_id": "queued"]),
            Self.frame("ai_task_initiated", ["chat_id": "other", "user_message_id": "message", "ai_task_id": "other"]),
            Self.frame("ai_task_initiated", ["chat_id": "chat", "user_message_id": "message", "ai_task_id": "accepted"])
        ])
        let admission = try await BackgroundChatSender().sendPreparedTurn(turn, requiresLegacyMetadata: true,
            send: { try await transport.send($0) }, receive: { try await transport.receive(before: $0) })
        XCTAssertEqual(admission, .durable, "PREPARED already durably stores the encrypted user message")
        let state = await transport.state
        XCTAssertEqual(state.receives, 4, "Queued and unrelated events cannot substitute for matching task admission")
        XCTAssertFalse(state.closed)
        let writes = try state.writes.map(Self.decodeWrite)
        XCTAssertEqual(writes.map { $0["type"] as? String }, ["chat_turn_preflight", "chat_message_added"])
        let preflight = try XCTUnwrap(writes[0]["payload"] as? [String: Any])
        let encrypted = try XCTUnwrap(preflight["encrypted_user_message"] as? [String: Any])
        XCTAssertEqual(encrypted["encrypted_content"] as? String, "ciphertext")
        XCTAssertEqual(encrypted["encrypted_pii_mappings"] as? String, "encrypted-pii")
        XCTAssertNil(encrypted["content"])
        XCTAssertNil(encrypted["plaintext"])
        XCTAssertEqual(preflight["expected_messages_v"] as? Int, 7)
        XCTAssertEqual(preflight["recovery_public_key"] as? String, "recovery-public-key")
        let shell = try XCTUnwrap(preflight["encrypted_chat_metadata"] as? [String: Any])
        XCTAssertEqual(shell["encrypted_title"] as? String, "encrypted-empty-title")
        var commit = try XCTUnwrap(writes[1]["payload"] as? [String: Any])
        XCTAssertEqual(commit.removeValue(forKey: "protocol_version") as? Int, 1)
        XCTAssertEqual(commit.removeValue(forKey: "preflight_id") as? String, "preflight")
        let objects = try BackgroundChatTurnContract.objects(turn)
        XCTAssertTrue(NSDictionary(dictionary: commit).isEqual(to: objects.inference),
            "Commit must retain exact IDs, title versions, encrypted PII and attachment objects committed by preflight")
    }

    // contract-test: supporting surface=gui.apple assertions=chats.persistence.client-encrypted,chats.surface.semantic-parity
    func testLegacyPreflightRequiresCompleteNewMetadataAndLeavesSocketOpenForStorageAck() async throws {
        let transport = PreparedTurnTransport(frames: [Self.preflightAck("LEGACY"),
            Self.frame("ai_task_initiated", ["chat_id": "chat", "user_message_id": "message", "ai_task_id": "accepted"]),
            Self.frame("ai_typing_started", ["chat_id": "chat", "user_message_id": "message", "title": "Article summary", "category": "web"]),
            Self.frame("encrypted_metadata_stored", ["chat_id": "chat", "message_id": "message"])
        ])
        let sender = BackgroundChatSender()
        let admission = try await sender.sendPreparedTurn(Self.preparedTurnFixture(), requiresLegacyMetadata: true,
            send: { try await transport.send($0) }, receive: { try await transport.receive(before: $0) })
        guard case .legacy(let taskId, let metadata) = admission else { return XCTFail("Epoch zero needs encrypted storage") }
        XCTAssertEqual(taskId, "accepted")
        XCTAssertEqual(metadata.title, "Article summary")
        XCTAssertEqual(metadata.category, "web")
        try await transport.send("encrypted storage write")
        try await sender.waitForStorageConfirmation(chatId: "chat", messageId: "message",
            receive: { try await transport.receive(before: $0) })
        let state = await transport.state
        XCTAssertFalse(state.closed)
        XCTAssertEqual(state.receives, 4)
        XCTAssertEqual(state.writes.count, 3)
    }

    // contract-test: supporting surface=gui.apple assertions=chats.persistence.client-encrypted,chats.surface.semantic-parity
    func testPreflightReplayNeverCommitsAnotherInferenceOrRequiresLegacyStorage() async throws {
        for replay in ["ENQUEUED", "RUNNING", "TERMINAL"] {
            let transport = PreparedTurnTransport(frames: [Self.preflightAck(replay)])
            let admission = try await BackgroundChatSender().sendPreparedTurn(Self.preparedTurnFixture(), requiresLegacyMetadata: true,
                send: { try await transport.send($0) }, receive: { try await transport.receive(before: $0) })
            XCTAssertEqual(admission, .replayed)
            let state = await transport.state
            XCTAssertEqual(state.writes.count, 1, "Accepted turn replay must never enqueue duplicate inference")
            XCTAssertEqual(state.receives, 1)
        }
    }

    // contract-test: supporting surface=gui.apple assertions=chats.persistence.client-encrypted,chats.surface.semantic-parity
    func testFailedAndInvalidPreflightStatesCannotDispatchInference() async throws {
        for stateName in ["FAILED", "UNRECOGNIZED"] {
            let transport = PreparedTurnTransport(frames: [Self.preflightAck(stateName)])
            do {
                _ = try await BackgroundChatSender().sendPreparedTurn(Self.preparedTurnFixture(), requiresLegacyMetadata: false,
                    send: { try await transport.send($0) }, receive: { try await transport.receive(before: $0) })
                XCTFail("Rejected preflight cannot dispatch inference")
            } catch {
                if stateName == "FAILED" {
                    guard case BackgroundChatSendError.serverRejected(.turnFailed) = error else { return XCTFail("Expected failed turn") }
                } else {
                    guard case BackgroundChatSendError.invalidPreflightAcknowledgement = error else { return XCTFail("Expected invalid state") }
                }
            }
            let state = await transport.state
            XCTAssertEqual(state.writes.count, 1)
        }
    }

    // contract-test: supporting surface=gui.apple assertions=chats.persistence.client-encrypted,chats.surface.semantic-parity
    func testPreflightIgnoresOtherTurnChatAndMessageAcknowledgementsAndErrors() async throws {
        let transport = PreparedTurnTransport(frames: [
            Self.preflightAck("PREPARED", turnId: "other"),
            Self.frame("chat_turn_preflight_ack", ["turn_id": "turn", "chat_id": "other", "state": "PREPARED", "preflight_id": "wrong"]),
            Self.frame("chat_turn_preflight_ack", ["turn_id": "turn", "message_id": "other", "state": "PREPARED", "preflight_id": "wrong"]),
            Self.frame("error", ["turn_id": "other", "code": "durable_preflight_failed"]),
            Self.preflightAck("PREPARED"),
            Self.frame("ai_task_initiated", ["turn_id": "other", "chat_id": "chat", "user_message_id": "message", "ai_task_id": "other"]),
            Self.frame("ai_task_initiated", ["chat_id": "chat", "user_message_id": "message", "ai_task_id": "accepted"])
        ])
        let admission = try await BackgroundChatSender().sendPreparedTurn(Self.preparedTurnFixture(), requiresLegacyMetadata: false,
            send: { try await transport.send($0) }, receive: { try await transport.receive(before: $0) })
        XCTAssertEqual(admission, .durable)
        let state = await transport.state
        XCTAssertEqual(state.receives, 7)
        let commit = try Self.decodeWrite(state.writes[1])["payload"] as? [String: Any]
        XCTAssertEqual(commit?["preflight_id"] as? String, "preflight")
    }

    // contract-test: supporting surface=gui.apple assertions=chats.persistence.client-encrypted,chats.surface.semantic-parity
    func testMatchingPreflightRejectionAndMissingAcknowledgementCannotCommit() async throws {
        for frames in [[Self.frame("error", ["turn_id": "turn", "code": "durable_preflight_failed", "message": "private server detail"])], []] {
            let transport = PreparedTurnTransport(frames: frames)
            do {
                _ = try await BackgroundChatSender().sendPreparedTurn(Self.preparedTurnFixture(), requiresLegacyMetadata: false,
                    send: { try await transport.send($0) }, receive: { try await transport.receive(before: $0) })
                XCTFail("Preflight failure cannot become successful admission")
            } catch {
                if frames.isEmpty {
                    guard case BackgroundChatSendError.preflightTimedOut = error else { return XCTFail("Expected bounded timeout") }
                } else {
                    guard case BackgroundChatSendError.serverRejected(.durablePreflightFailed) = error else { return XCTFail("Expected bounded rejection") }
                }
                XCTAssertFalse(error.localizedDescription.contains("private server detail"))
            }
            let state = await transport.state
            XCTAssertEqual(state.writes.count, 1)
        }
    }

    // contract-test: supporting surface=gui.apple assertions=chats.persistence.client-encrypted,chats.surface.semantic-parity
    func testAmbiguousCommitRetryReusesPreparedIDsAndInferenceWithoutDuplicateDispatch() async throws {
        let turn = try Self.preparedTurnFixture()
        let first = PreparedTurnTransport(frames: [Self.preflightAck("PREPARED")])
        let sender = BackgroundChatSender()
        do {
            _ = try await sender.sendPreparedTurn(turn, requiresLegacyMetadata: false,
                send: { try await first.send($0) }, receive: { try await first.receive(before: $0) })
            XCTFail("An unacknowledged commit must remain retryable")
        } catch {
            guard case BackgroundChatSendError.network = error else { return XCTFail("Expected ambiguous commit failure") }
        }
        let retry = PreparedTurnTransport(frames: [Self.preflightAck("ENQUEUED")])
        let replay = try await sender.sendPreparedTurn(turn, requiresLegacyMetadata: false,
            send: { try await retry.send($0) }, receive: { try await retry.receive(before: $0) })
        XCTAssertEqual(replay, .replayed)
        let firstState = await first.state
        let retryState = await retry.state
        XCTAssertEqual(firstState.writes.count, 2)
        XCTAssertEqual(retryState.writes.count, 1)
        XCTAssertEqual(firstState.writes[0], retryState.writes[0], "Retry must preserve exact durable ciphertext and turn/message/chat identities")
    }

    // contract-test: supporting surface=gui.apple assertions=sync.access.first-party-authenticated,chats.persistence.client-encrypted
    func testScopeChangeAfterPreflightPreventsInferenceCommit() async throws {
        let transport = PreparedTurnTransport(frames: [Self.preflightAck("PREPARED")])
        let fence = PreparedTurnScopeFence()
        do {
            _ = try await BackgroundChatSender().sendPreparedTurn(Self.preparedTurnFixture(), requiresLegacyMetadata: false,
                send: { try await transport.send($0) }, receive: { try await transport.receive(before: $0) },
                validate: { try await fence.validate() })
            XCTFail("Account/server changes cannot send committed plaintext inference")
        } catch {
            guard case BackgroundChatSendError.notAuthenticated = error else { return XCTFail("Expected scope fence") }
        }
        let state = await transport.state
        XCTAssertEqual(state.writes.count, 1)
    }

    // contract-test: supporting surface=gui.apple assertions=sync.access.first-party-authenticated,chats.persistence.client-encrypted
    func testPreparedTurnRetryFingerprintChangesForEditsDestinationsAndAttachments() throws {
        let request = BackgroundChatSender.SendRequest(content: "Summarize the public article", destination: nil)
        let initial = try BackgroundChatTurnContract.fingerprint(request)
        XCTAssertEqual(initial, try BackgroundChatTurnContract.fingerprint(request))
        XCTAssertNotEqual(initial, try BackgroundChatTurnContract.fingerprint(.init(content: "Edited instruction", destination: nil)))
        let embed = BackgroundPreparedEmbed(id: "attachment", type: "docs-doc", referenceType: "file", status: "finished", content: ["filename": "article.txt"], textPreview: "article.txt")
        XCTAssertNotEqual(initial, try BackgroundChatTurnContract.fingerprint(.init(content: request.content, destination: nil, embeds: [embed])))
        let scope = BackgroundPreparedTurnScope(userId: "user", server: URL(string: "https://example.invalid")!, nativeSessionId: "native", requestFingerprint: initial)
        XCTAssertNotEqual(scope, BackgroundPreparedTurnScope(userId: "other", server: scope.server, nativeSessionId: scope.nativeSessionId, requestFingerprint: initial))
        XCTAssertNotEqual(scope, BackgroundPreparedTurnScope(userId: scope.userId, server: URL(string: "https://other.invalid")!, nativeSessionId: scope.nativeSessionId, requestFingerprint: initial))
        XCTAssertNotEqual(scope, BackgroundPreparedTurnScope(userId: scope.userId, server: scope.server, nativeSessionId: "other", requestFingerprint: initial))
    }


    // contract-test: supporting surface=gui.apple assertions=chats.persistence.client-encrypted,chats.surface.semantic-parity
    func testMalformedPreflightAndMatchingCommitRejectionRemainFailures() async throws {
        let malformed = PreparedTurnTransport(frames: [Self.frame("chat_turn_preflight_ack", ["turn_id": "turn", "state": "PREPARED", "preflight_id": ""])])
        do {
            _ = try await BackgroundChatSender().sendPreparedTurn(Self.preparedTurnFixture(), requiresLegacyMetadata: false,
                send: { try await malformed.send($0) }, receive: { try await malformed.receive(before: $0) })
            XCTFail("A missing durable identity cannot commit")
        } catch {
            guard case BackgroundChatSendError.invalidPreflightAcknowledgement = error else { return XCTFail("Expected invalid acknowledgement") }
        }
        let malformedState = await malformed.state
        XCTAssertEqual(malformedState.writes.count, 1)
        let rejected = PreparedTurnTransport(frames: [Self.preflightAck("PREPARED"),
            Self.frame("error", ["turn_id": "turn", "code": "inference_temporarily_paused", "message": "untrusted detail"])])
        do {
            _ = try await BackgroundChatSender().sendPreparedTurn(Self.preparedTurnFixture(), requiresLegacyMetadata: false,
                send: { try await rejected.send($0) }, receive: { try await rejected.receive(before: $0) })
            XCTFail("Durable user storage alone is not assistant admission")
        } catch {
            guard case BackgroundChatSendError.serverRejected(.inferencePaused) = error else { return XCTFail("Expected matching commit rejection") }
            XCTAssertFalse(error.localizedDescription.contains("untrusted detail"))
        }
        let rejectedState = await rejected.state
        XCTAssertEqual(rejectedState.writes.count, 2)
        XCTAssertEqual(rejectedState.receives, 2)
    }


    // contract-test: supporting surface=gui.apple assertions=sync.access.first-party-authenticated,sync.surface.semantic-parity
    func testProductionSenderRetainsRoutingIdentityAcrossReconnectsAndIsolatesOtherSenders() async {
        let first = BackgroundChatSender()
        let second = BackgroundChatSender()
        let original = await first.socketRoutingSessionId(nativeSessionId: "native")
        let retry = await first.socketRoutingSessionId(nativeSessionId: "native")
        let other = await second.socketRoutingSessionId(nativeSessionId: "native")
        let changedSession = await first.socketRoutingSessionId(nativeSessionId: "replacement")
        let recent = await first.recentChatsRoutingSessionId(nativeSessionId: "native")
        let otherRecent = await first.recentChatsRoutingSessionId(nativeSessionId: "native")
        XCTAssertNotEqual(original, recent, "A cancelled loader cannot unregister the newly opened send socket")
        XCTAssertNotEqual(recent, otherRecent)
        XCTAssertEqual(original, retry, "Same prepared turn retry must retain the transport device identity")
        XCTAssertNotEqual(original, other)
        XCTAssertNotEqual(original, "native")
        XCTAssertNotEqual(original, changedSession)
    }

    // contract-test: supporting surface=gui.apple assertions=chats.persistence.client-encrypted,chats.surface.semantic-parity
    func testShareAttachmentRetryRetainsDraftUploadsAndSenderFingerprint() async throws {
        let cache = BackgroundSharedAttachmentPreparation()
        let uploader = ShareAttachmentUploadProbe()
        let scope = Self.attachmentScope()
        let inputs = [Self.attachmentInput("first")]
        let first = try await cache.prepare(content: "Summarize", selectedDestination: nil, attachments: inputs, scope: scope,
            upload: { try await uploader.upload($0, chatId: $1) })
        let retry = try await cache.prepare(content: "Summarize", selectedDestination: nil, attachments: inputs, scope: scope,
            upload: { try await uploader.upload($0, chatId: $1) })
        let state = await uploader.state
        XCTAssertEqual(state.count, 1, "Ambiguous send retry cannot upload the same unchanged attachment again")
        XCTAssertEqual(first.destination?.id, retry.destination?.id)
        XCTAssertNotNil(UUID(uuidString: try XCTUnwrap(first.destination?.id)))
        XCTAssertEqual(first.embeds.map(\.id), retry.embeds.map(\.id))
        XCTAssertEqual(first.destination?.authenticatedUserId, scope.userId)
        XCTAssertEqual(first.destination?.authenticatedServer, scope.server)
        XCTAssertEqual(try BackgroundChatTurnContract.fingerprint(.init(content: "Summarize", destination: first.destination, embeds: first.embeds)),
            try BackgroundChatTurnContract.fingerprint(.init(content: "Summarize", destination: retry.destination, embeds: retry.embeds)))
    }

    // contract-test: supporting surface=gui.apple assertions=chats.persistence.client-encrypted,chats.surface.semantic-parity
    func testShareAttachmentPreparationRetainsCompletedUploadAfterPartialFailure() async throws {
        let cache = BackgroundSharedAttachmentPreparation()
        let uploader = ShareAttachmentUploadProbe(failOnceId: "second")
        let inputs = [Self.attachmentInput("first"), Self.attachmentInput("second")]
        do {
            _ = try await cache.prepare(content: "Summarize", selectedDestination: nil, attachments: inputs, scope: Self.attachmentScope(),
                upload: { try await uploader.upload($0, chatId: $1) })
            XCTFail("Expected partial upload failure")
        } catch {
            guard case BackgroundChatSendError.network = error else { return XCTFail("Expected upload failure") }
        }
        let retry = try await cache.prepare(content: "Summarize", selectedDestination: nil, attachments: inputs, scope: Self.attachmentScope(),
            upload: { try await uploader.upload($0, chatId: $1) })
        let state = await uploader.state
        XCTAssertEqual(state.ids, ["first", "second", "second"])
        XCTAssertEqual(Set(state.chatIds).count, 1, "Partial retry retains the original draft")
        XCTAssertEqual(retry.embeds.count, 2)
    }

    // contract-test: supporting surface=gui.apple assertions=sync.access.first-party-authenticated,chats.surface.semantic-parity
    func testShareAttachmentEditsAndScopeChangesInvalidatePreparation() async throws {
        let cache = BackgroundSharedAttachmentPreparation()
        let uploader = ShareAttachmentUploadProbe()
        let input = Self.attachmentInput("first")
        let first = try await cache.prepare(content: "Summarize", selectedDestination: nil, attachments: [input], scope: Self.attachmentScope(),
            upload: { try await uploader.upload($0, chatId: $1) })
        let edited = try await cache.prepare(content: "Translate", selectedDestination: nil, attachments: [input], scope: Self.attachmentScope(),
            upload: { try await uploader.upload($0, chatId: $1) })
        let changedAccount = try await cache.prepare(content: "Translate", selectedDestination: nil, attachments: [input], scope: Self.attachmentScope(userId: "other"),
            upload: { try await uploader.upload($0, chatId: $1) })
        XCTAssertNotEqual(first.destination?.id, edited.destination?.id)
        XCTAssertNotEqual(edited.destination?.id, changedAccount.destination?.id)
        XCTAssertEqual(changedAccount.destination?.authenticatedUserId, "other")
        let selected = try await cache.prepare(content: "Translate", selectedDestination: first.destination,
            attachments: [input], scope: Self.attachmentScope(), upload: { try await uploader.upload($0, chatId: $1) })
        XCTAssertEqual(selected.destination?.id, first.destination?.id)
        let changedFile = BackgroundSharedAttachmentPreparation.Input(id: input.id, data: Data("changed attachment".utf8),
            filename: input.filename, contentType: input.contentType)
        let changed = try await cache.prepare(content: "Translate", selectedDestination: first.destination,
            attachments: [changedFile], scope: Self.attachmentScope(), upload: { try await uploader.upload($0, chatId: $1) })
        XCTAssertNotEqual(selected.embeds.map(\.id), changed.embeds.map(\.id))
        let state = await uploader.state
        XCTAssertEqual(state.count, 5)
    }

    private static func attachmentScope(userId: String = "user") -> BackgroundPreparedTurnScope {
        .init(userId: userId, server: URL(string: "https://example.invalid")!, nativeSessionId: "native", requestFingerprint: Data())
    }

    private static func attachmentInput(_ id: String) -> BackgroundSharedAttachmentPreparation.Input {
        .init(id: id, data: Data("public attachment".utf8), filename: "\(id).txt", contentType: "text/plain")
    }


    // contract-test: supporting surface=gui.apple assertions=chats.persistence.client-encrypted,chats.surface.semantic-parity
    func testPreparedWirePreservesNumericProtocolAndZeroOneVersionsWithoutBooleanBridging() async throws {
        let objects = try BackgroundChatTurnContract.objects(Self.preparedTurnFixture())
        var inference = objects.inference
        var message = try XCTUnwrap(inference["message"] as? [String: Any])
        message["created_at"] = 0
        message["current_chat_title_v"] = 1
        message["chat_has_title"] = true
        inference["message"] = message
        var encryptedUser = try XCTUnwrap(objects.preflight["encrypted_user_message"] as? [String: Any])
        encryptedUser["created_at"] = 0
        let turn = try BackgroundChatTurnContract.prepare(chatId: "chat", messageId: "message", turnId: "turn",
            encryptedChatKey: "wrapped-key", recoveryPublicKey: "recovery-public-key", expectedMessagesVersion: 0,
            encryptedUserMessage: encryptedUser, inferenceRequest: inference, encryptedInitialTitle: nil, createdAt: 0)
        let transport = PreparedTurnTransport(frames: [Self.preflightAck("PREPARED"),
            Self.frame("ai_task_initiated", ["chat_id": "chat", "user_message_id": "message", "ai_task_id": "accepted"])])
        let admission = try await BackgroundChatSender().sendPreparedTurn(turn, requiresLegacyMetadata: false,
            send: { try await transport.send($0) }, receive: { try await transport.receive(before: $0) })
        XCTAssertEqual(admission, .durable)
        let state = await transport.state
        let writes = try state.writes.map(Self.decodeWrite)
        let preflight = try XCTUnwrap(writes[0]["payload"] as? [String: Any])
        let commit = try XCTUnwrap(writes[1]["payload"] as? [String: Any])
        func assertNumber(_ value: Any?, _ expected: Int, file: StaticString = #filePath, line: UInt = #line) throws {
            let number = try XCTUnwrap(value as? NSNumber, file: file, line: line)
            XCTAssertNotEqual(CFGetTypeID(number), CFBooleanGetTypeID(), "JSON numeric values must never become booleans", file: file, line: line)
            XCTAssertEqual(number.intValue, expected, file: file, line: line)
        }
        try assertNumber(preflight["protocol_version"], 1)
        try assertNumber(preflight["chat_key_version"], 1)
        try assertNumber(preflight["expected_messages_v"], 0)
        try assertNumber(commit["protocol_version"], 1)
        try assertNumber(commit["chat_key_version"], 1)
        let durable = try XCTUnwrap(preflight["encrypted_user_message"] as? [String: Any])
        try assertNumber(durable["created_at"], 0)
        for payload in [try XCTUnwrap(preflight["inference_request"] as? [String: Any]), commit] {
            let emitted = try XCTUnwrap(payload["message"] as? [String: Any])
            try assertNumber(emitted["created_at"], 0)
            try assertNumber(emitted["current_chat_title_v"], 1)
            let boolean = try XCTUnwrap(emitted["chat_has_title"] as? NSNumber)
            XCTAssertEqual(CFGetTypeID(boolean), CFBooleanGetTypeID(), "Real JSON booleans remain booleans")
            XCTAssertTrue(boolean.boolValue)
        }
    }

    private static func frame(_ type: String, _ payload: [String: Any]) -> Data {
        try! JSONSerialization.data(withJSONObject: ["type": type, "payload": payload], options: [.sortedKeys])
    }

    private static func preflightAck(_ state: String, turnId: String = "turn") -> Data {
        frame("chat_turn_preflight_ack", ["turn_id": turnId, "preflight_id": "preflight", "state": state])
    }

    private static func decodeWrite(_ text: String) throws -> [String: Any] {
        try XCTUnwrap(JSONSerialization.jsonObject(with: Data(text.utf8)) as? [String: Any])
    }

    private static func preparedTurnFixture() throws -> BackgroundPreparedTurn {
        let inference: [String: Any] = ["chat_id": "chat", "turn_id": "turn", "chat_key_version": 1,
            "recovery_public_key": "recovery-public-key", "encrypted_chat_key": "wrapped-key",
            "message": ["message_id": "message", "content": "Public article [EMAIL_1]", "role": "user",
                "current_chat_title_v": 3, "current_chat_metadata_v": 4],
            "encrypted_pii_mappings": "encrypted-pii",
            "embeds": [["embed_id": "attachment", "content": "transient-file-data"]],
            "encrypted_embeds": [["embed_id": "attachment", "encrypted_content": "encrypted-file-data"]]]
        return try BackgroundChatTurnContract.prepare(chatId: "chat", messageId: "message", turnId: "turn",
            encryptedChatKey: "wrapped-key", recoveryPublicKey: "recovery-public-key", expectedMessagesVersion: 7,
            encryptedUserMessage: ["client_message_id": "message", "chat_id": "chat", "encrypted_content": "ciphertext",
                "role": "user", "created_at": 123, "updated_at": 123, "encrypted_pii_mappings": "encrypted-pii"],
            inferenceRequest: inference, encryptedInitialTitle: "encrypted-empty-title", createdAt: 123)
    }

    private struct SessionProbe: Encodable {
        let sessionId: String
        let deviceInfo: DeviceInfoProbe
    }

    private struct DeviceInfoProbe: Encodable {
        let os: String
        let deviceModel: String
        let appVersion: String
    }

    func testBackgroundHTTPEncoderUsesBackendSnakeCaseContract() throws {
        let probe = SessionProbe(
            sessionId: "session-1",
            deviceInfo: DeviceInfoProbe(os: "iOS", deviceModel: "iPhone", appVersion: "1.0")
        )
        let data = try BackgroundChatHTTPContract.makeEncoder().encode(probe)
        let payload = try XCTUnwrap(JSONSerialization.jsonObject(with: data) as? [String: Any])
        let deviceInfo = try XCTUnwrap(payload["device_info"] as? [String: String])

        XCTAssertEqual(payload["session_id"] as? String, "session-1")
        XCTAssertNil(payload["sessionId"])
        XCTAssertEqual(deviceInfo["device_model"], "iPhone")
        XCTAssertEqual(deviceInfo["app_version"], "1.0")
        XCTAssertNil(deviceInfo["deviceModel"])
    }

    func testEncryptedStoragePayloadContainsOnlyEncryptedDurableContentAndVersions() throws {
        let payload = BackgroundChatStoragePayload(
            chatId: "chat-1",
            messageId: "user-1",
            encryptedContent: "encrypted-user-message",
            createdAtUnix: 1_780_000_000,
            encryptedChatKey: "encrypted-chat-key",
            messagesV: 7,
            titleV: 3,
            taskId: "task-1",
            encryptedSenderName: "encrypted-user",
            encryptedPIIMappings: "encrypted-pii-mappings",
            encryptedTitle: "encrypted-title",
            encryptedIcon: "encrypted-icon",
            encryptedChatCategory: "encrypted-chat-category",
            encryptedUserCategory: "encrypted-user-category"
        ).dictionary

        XCTAssertEqual(payload["chat_id"] as? String, "chat-1")
        XCTAssertEqual(payload["message_id"] as? String, "user-1")
        XCTAssertEqual(payload["encrypted_content"] as? String, "encrypted-user-message")
        XCTAssertEqual(payload["encrypted_chat_key"] as? String, "encrypted-chat-key")
        XCTAssertEqual(payload["task_id"] as? String, "task-1")
        XCTAssertEqual(payload["encrypted_sender_name"] as? String, "encrypted-user")
        XCTAssertEqual(payload["encrypted_pii_mappings"] as? String, "encrypted-pii-mappings")
        XCTAssertEqual(payload["encrypted_title"] as? String, "encrypted-title")
        XCTAssertEqual(payload["encrypted_icon"] as? String, "encrypted-icon")
        XCTAssertEqual(payload["encrypted_chat_category"] as? String, "encrypted-chat-category")
        XCTAssertEqual(payload["encrypted_category"] as? String, "encrypted-user-category")
        XCTAssertNil(payload["content"])
        XCTAssertNil(payload["plaintext"])
        XCTAssertNil(payload["sender_name"])

        let versions = try XCTUnwrap(payload["versions"] as? [String: Int])
        XCTAssertEqual(versions["messages_v"], 7)
        XCTAssertEqual(versions["title_v"], 3)
        XCTAssertEqual(versions["last_edited_overall_timestamp"], 1_780_000_000)
    }

    func testBackgroundSendsRedactPII() throws {
        let openAIKey = "sk-proj-abcdefghijklmnopqrstuvwxyz1234567890"
        let result = try BackgroundChatSendContract.redactedContentForSend(
            text: "Summarize for max@posteo.de, call +49 170 1234567, and use \(openAIKey)",
            embeds: []
        )

        XCTAssertFalse(result.content.contains("max@posteo.de"))
        XCTAssertFalse(result.content.contains("+49 170 1234567"))
        XCTAssertFalse(result.content.contains(openAIKey))
        XCTAssertTrue(result.content.contains("[EMAIL_"))
        XCTAssertTrue(result.content.contains("[PHONE_"))
        XCTAssertTrue(result.content.contains("[OPENAI_KEY_"))
        XCTAssertEqual(result.piiMappings.count, 3)
        XCTAssertTrue(result.piiMappings.contains { $0.original == "max@posteo.de" && $0.type == "EMAIL" })
        XCTAssertTrue(result.piiMappings.contains { $0.original == openAIKey && $0.type == "OPENAI_KEY" })
    }

    func testQueuedBackgroundEventTriggersEncryptedStoragePackage() {
        XCTAssertTrue(
            BackgroundChatStorageContract.shouldSendEncryptedStoragePackage(afterInboundEventType: "message_queued")
        )
        XCTAssertTrue(
            BackgroundChatStorageContract.shouldSendEncryptedStoragePackage(afterInboundEventType: "ai_typing_started")
        )
        XCTAssertTrue(
            BackgroundChatStorageContract.shouldSendEncryptedStoragePackage(afterInboundEventType: "ai_task_initiated")
        )
    }

    func testNewAuthenticatedBackgroundChatIdIsLowercaseUUID() {
        let chatId = BackgroundChatID.makeAuthenticatedChatId()

        XCTAssertEqual(chatId, chatId.lowercased())
        XCTAssertNotNil(UUID(uuidString: chatId))
    }

    func testExistingBackgroundChatRequiresWrappedChatKey() throws {
        XCTAssertThrowsError(
            try BackgroundChatSendContract.chatKeyIntent(
                isExistingChat: true,
                encryptedChatKey: nil
            )
        ) { error in
            guard case BackgroundChatSendError.missingChatKey = error else {
                return XCTFail("Expected missingChatKey, got \(type(of: error))")
            }
        }

        XCTAssertEqual(
            try BackgroundChatSendContract.chatKeyIntent(
                isExistingChat: true,
                encryptedChatKey: "wrapped-existing-key"
            ),
            .loadExisting("wrapped-existing-key")
        )
        XCTAssertEqual(
            try BackgroundChatSendContract.chatKeyIntent(
                isExistingChat: false,
                encryptedChatKey: nil
            ),
            .createNew
        )
    }

    func testQueuedStorageAcceptsBackendActiveTaskId() {
        let taskId = BackgroundChatStorageContract.storageTaskId(
            taskId: nil,
            aiTaskId: nil,
            activeTaskId: "active-task-1"
        )

        XCTAssertEqual(taskId, "active-task-1")
    }

    func testNewChatMetadataRequiresTitleAndCategoryBeforeStorage() {
        XCTAssertTrue(BackgroundChatStorageContract.hasCompleteNewChatMetadata(
            title: "Trip plan",
            category: "travel"
        ))
        XCTAssertFalse(BackgroundChatStorageContract.hasCompleteNewChatMetadata(
            title: "Trip plan",
            category: nil
        ))
        XCTAssertFalse(BackgroundChatStorageContract.hasCompleteNewChatMetadata(
            title: "   ",
            category: "travel"
        ))
        XCTAssertFalse(BackgroundChatStorageContract.hasCompleteNewChatMetadata(
            title: "Trip plan",
            category: "   "
        ))
    }

    func testBackgroundAttachmentClassificationMatchesComposerSupportedTypes() {
        XCTAssertEqual(BackgroundAttachmentClassifier.classification(filename: "photo.png", contentType: "image/png")?.embedType, "images-image")
        XCTAssertEqual(BackgroundAttachmentClassifier.classification(filename: "brief.pdf", contentType: "application/pdf")?.embedType, "pdf")
        XCTAssertEqual(BackgroundAttachmentClassifier.classification(filename: "notes.md", contentType: "text/markdown")?.embedType, "docs-doc")
        XCTAssertEqual(BackgroundAttachmentClassifier.classification(filename: "voice.m4a", contentType: "audio/mp4")?.embedType, "audio-recording")
        XCTAssertNil(BackgroundAttachmentClassifier.classification(filename: "archive.zip", contentType: "application/zip"))
    }

    func testBackgroundAudioEmbedPreservesFullTranscriptMetadata() throws {
        let upload = BackgroundUploadFileResponse.testFixture(
            embedId: "audio-embed-1",
            filename: "voice.m4a",
            contentType: "audio/mp4"
        )
        let metadata = BackgroundAudioTranscriptionMetadata(
            transcript: "Corrected transcript",
            transcriptOriginal: "Raw transcript",
            transcriptCorrected: "Corrected transcript",
            useCorrected: true,
            correctionModel: "gemini-3.5-flash",
            model: "voxtral-mini-2602"
        )

        let embed = try BackgroundPreparedEmbed.from(upload: upload, audioMetadata: metadata, durationSeconds: 2.5)

        XCTAssertEqual(embed.type, "audio-recording")
        XCTAssertEqual(embed.referenceType, "audio-recording")
        XCTAssertEqual(embed.textPreview, "Corrected transcript")
        XCTAssertEqual(embed.content["transcript"] as? String, "Corrected transcript")
        XCTAssertEqual(embed.content["transcript_original"] as? String, "Raw transcript")
        XCTAssertEqual(embed.content["transcript_corrected"] as? String, "Corrected transcript")
        XCTAssertEqual(embed.content["use_corrected"] as? Bool, true)
        XCTAssertEqual(embed.content["correction_model"] as? String, "gemini-3.5-flash")
        XCTAssertEqual(embed.content["model"] as? String, "voxtral-mini-2602")
        XCTAssertTrue(embed.markdownReference.contains("audio-embed-1"))
    }

    func testBackgroundSendContentAllowsEmbedOnlyMessages() throws {
        let upload = BackgroundUploadFileResponse.testFixture(
            embedId: "image-embed-1",
            filename: "screenshot.png",
            contentType: "image/png"
        )
        let embed = try BackgroundPreparedEmbed.from(upload: upload)

        XCTAssertNoThrow(try BackgroundChatSendContract.contentForSend(text: "", embeds: [embed]))
        let content = try BackgroundChatSendContract.contentForSend(text: "Please inspect this", embeds: [embed])

        XCTAssertTrue(content.hasPrefix("Please inspect this"))
        XCTAssertTrue(content.contains("image-embed-1"))
        XCTAssertThrowsError(try BackgroundChatSendContract.contentForSend(text: "", embeds: []))
    }

    func testBackgroundPdfEmbedUsesProcessingUntilOcrDedupCompletes() throws {
        let processingUpload = BackgroundUploadFileResponse.testFixture(
            embedId: "pdf-embed-1",
            filename: "brief.pdf",
            contentType: "application/pdf",
            deduplicated: false
        )
        let finishedUpload = BackgroundUploadFileResponse.testFixture(
            embedId: "pdf-embed-2",
            filename: "brief.pdf",
            contentType: "application/pdf",
            deduplicated: true
        )

        let processingEmbed = try BackgroundPreparedEmbed.from(upload: processingUpload)
        let finishedEmbed = try BackgroundPreparedEmbed.from(upload: finishedUpload)

        XCTAssertEqual(processingEmbed.status, "processing")
        XCTAssertEqual(processingEmbed.content["status"] as? String, "processing")
        XCTAssertEqual(finishedEmbed.status, "finished")
        XCTAssertEqual(finishedEmbed.content["status"] as? String, "finished")
    }
}

private extension BackgroundUploadFileResponse {
    static func testFixture(
        embedId: String,
        filename: String,
        contentType: String,
        deduplicated: Bool = true
    ) -> BackgroundUploadFileResponse {
        BackgroundUploadFileResponse(
            embedId: embedId,
            filename: filename,
            contentType: contentType,
            contentHash: "hash-1",
            files: [
                "original": BackgroundUploadedFileVariant(
                    s3Key: "uploads/\(filename)",
                    sizeBytes: 123,
                    width: contentType.hasPrefix("image/") ? 100 : nil,
                    height: contentType.hasPrefix("image/") ? 80 : nil,
                    format: (filename as NSString).pathExtension
                )
            ],
            s3BaseUrl: "https://example.invalid/files",
            aesKey: "aes-key",
            aesNonce: "aes-nonce",
            vaultWrappedAesKey: "wrapped-key",
            pageCount: contentType == "application/pdf" ? 1 : nil,
            deduplicated: deduplicated
        )
    }
}

// Models a native receive callback that resumes only after the transport closes.
// Cooperative Task.sleep would hide the original cancellation/drain defect.
private final class SuspendedBackgroundTransport: @unchecked Sendable {
    private let lock = NSLock()
    private var continuation: CheckedContinuation<Data, Error>?
    private var closed = false

    var isClosed: Bool { lock.withLock { closed } }

    func receive() async throws -> Data {
        try await withCheckedThrowingContinuation { continuation in
            let wasClosed = lock.withLock {
                if closed { return true }
                self.continuation = continuation
                return false
            }
            if wasClosed { continuation.resume(throwing: CancellationError()) }
        }
    }

    func close() {
        let waiting = lock.withLock {
            closed = true
            let waiting = continuation
            continuation = nil
            return waiting
        }
        waiting?.resume(throwing: CancellationError())
    }
}

// A second receive after the supplied frames models the production deadline:
// transport closure follows a metadata wait, making a later storage write fail.
private actor AssistantStartTransport {
    private var frames: [Data]
    private var receiveCount = 0
    private var closed = false
    private var storedTaskId: String?

    init(frames: [Data]) { self.frames = frames }

    func receive(before _: Date) throws -> Data? {
        receiveCount += 1
        guard !frames.isEmpty else { closed = true; return nil }
        return frames.removeFirst()
    }

    func sendEncryptedStorage(taskId: String) throws {
        guard !closed else { throw CancellationError() }
        storedTaskId = taskId
    }

    var state: (receives: Int, closed: Bool, storedTaskId: String?) {
        (receiveCount, closed, storedTaskId)
    }
}


private actor PreparedTurnTransport {
    private var frames: [Data]
    private var writes: [String] = []
    private var receives = 0
    private var closed = false

    init(frames: [Data]) { self.frames = frames }

    func send(_ text: String) throws {
        guard !closed else { throw CancellationError() }
        writes.append(text)
    }

    func receive(before _: Date) throws -> Data? {
        receives += 1
        guard !frames.isEmpty else { closed = true; return nil }
        return frames.removeFirst()
    }

    var state: (writes: [String], receives: Int, closed: Bool) { (writes, receives, closed) }
}

private actor PreparedTurnScopeFence {
    private var checks = 0
    func validate() throws {
        checks += 1
        if checks > 1 { throw BackgroundChatSendError.notAuthenticated }
    }
}


private actor ShareAttachmentUploadProbe {
    private var ids: [String] = []
    private var chatIds: [String] = []
    private var failOnceId: String?

    init(failOnceId: String? = nil) { self.failOnceId = failOnceId }

    func upload(_ input: BackgroundSharedAttachmentPreparation.Input, chatId: String) throws -> BackgroundPreparedEmbed {
        ids.append(input.id)
        chatIds.append(chatId)
        if input.id == failOnceId {
            failOnceId = nil
            throw BackgroundChatSendError.network
        }
        return BackgroundPreparedEmbed(id: "uploaded-\(input.id)-\(ids.count)", type: "docs-doc", referenceType: "file", status: "finished",
            content: ["filename": input.filename], textPreview: input.filename)
    }

    var state: (count: Int, ids: [String], chatIds: [String]) { (ids.count, ids, chatIds) }
}
