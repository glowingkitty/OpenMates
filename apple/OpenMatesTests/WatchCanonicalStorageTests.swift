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
            acknowledgement: ["request_id": "request", "created_count": 1, "requested_count": 1, "failed_count": 0], requestID: "request"))
        for ack: [String: Any] in [["request_id": "other", "created_count": 1, "failed_count": 0],
                                  ["request_id": "request", "created_count": 0, "failed_count": 1]] {
            XCTAssertThrowsError(try WatchCanonicalStorage.validateEmbedStorageAcknowledgement(type: "store_embed_keys", payload: payload,
                acknowledgement: ack, requestID: "request"))
        }
        XCTAssertThrowsError(try WatchCanonicalStorage.validateEmbedStorageAcknowledgement(type: "store_embed", payload: ["embed_id": "embed"],
            acknowledgement: ["request_id": "request", "embed_id": "other"], requestID: "request"))
    }

    // contract-test: supporting surface=gui.apple assertions=chats.persistence.client-encrypted,storage.surface.semantic-parity
    func testCanonicalCapabilityAndStrictReceiptsArePairedOnlyForExactVerifiedProfileOnEverySocket() throws {
        let profile = ServerProfile.custom(domain: "canonical-synthetic.example")
        let paired = CanonicalEmbedStorageConfiguration(verifiedServerProfile: profile)
        XCTAssertEqual(paired.receiptPolicy(for: profile), .requireCanonicalDigest)
        for sessionID in ["first", "reconnected"] {
            let url = try XCTUnwrap(paired.socketURL(profile: profile, sessionID: sessionID, token: "synthetic-token"))
            let query = URLComponents(url: url, resolvingAgainstBaseURL: false)?.queryItems
            XCTAssertEqual(query?.first { $0.name == "client_capabilities" }?.value, "canonical_embed_receipts_v1")
            XCTAssertFalse(url.absoluteString.contains("typed_recovery_outputs_v2"))
        }
        for oldProfile in [ServerProfile.production, .development, .custom(domain: "other-synthetic.example")] {
            XCTAssertEqual(paired.receiptPolicy(for: oldProfile), .allowLegacyReceipt)
            XCTAssertTrue(paired.capabilities(for: oldProfile).isEmpty)
        }
        var headReceipt = bundleHeadReceipt()
        headReceipt.removeValue(forKey: "canonical_digest")
        XCTAssertThrowsError(try CanonicalEmbedStorageReceipts.validateHead(payload: bundleHead(), receipt: headReceipt,
            requestID: "head-request", policy: paired.receiptPolicy(for: profile)))
    }

    // contract-test: supporting surface=gui.apple assertions=chats.persistence.client-encrypted,storage.surface.semantic-parity
    func testDeployedWatchCanonicalStoragePairsExactDevelopmentProfileAndStrictReceipts() throws {
        let config = CanonicalEmbedStorageConfiguration.deployed
        XCTAssertEqual(ServerProfile.from(configuration: ServerProfile.development.endpointConfiguration), .development)
        let altered = try XCTUnwrap(ServerProfile.fromPayload(id: ServerProfile.development.id,
            webBaseURLString: ServerProfile.development.webBaseURL.absoluteString,
            apiBaseURLString: "https://unverified-synthetic.example",
            uploadBaseURLString: ServerProfile.development.uploadBaseURL.absoluteString))
        for profile in [ServerProfile.development, .production,
                        .custom(domain: ServerProfile.development.displayDomain), altered] {
            let verified = profile == .development
            XCTAssertEqual(config.receiptPolicy(for: profile), verified ? .requireCanonicalDigest : .allowLegacyReceipt)
            XCTAssertEqual(config.capabilities(for: profile), verified ? ["canonical_embed_receipts_v1"] : [])
            for sessionID in ["watch-first", "watch-reconnect"] {
                let url = try XCTUnwrap(config.socketURL(profile: profile, sessionID: sessionID, token: nil))
                let query = URLComponents(url: url, resolvingAgainstBaseURL: false)?.queryItems
                XCTAssertEqual(query?.first { $0.name == "client_capabilities" }?.value,
                               verified ? "canonical_embed_receipts_v1" : nil)
                XCTAssertEqual(query?.first { $0.name == "sessionId" }?.value, sessionID)
                XCTAssertFalse(url.absoluteString.contains("typed_recovery_outputs_v2"))
            }
        }
        let policy = config.receiptPolicy(for: .development)
        XCTAssertNoThrow(try WatchCanonicalStorage.validateEmbedStorageAcknowledgement(type: "store_embed",
            payload: bundleHead(), acknowledgement: bundleHeadReceipt(), requestID: "head-request", policy: policy))
        var legacyHead = bundleHeadReceipt()
        legacyHead.removeValue(forKey: "canonical_digest")
        XCTAssertThrowsError(try WatchCanonicalStorage.validateEmbedStorageAcknowledgement(type: "store_embed",
            payload: bundleHead(), acknowledgement: legacyHead, requestID: "head-request", policy: policy))
        let keys: [String: Any] = ["keys": [["encrypted_embed_key": "synthetic-wrapped-key"]]]
        let legacyKeys: [String: Any] = ["request_id": "keys-request", "created_count": 1, "failed_count": 0]
        XCTAssertThrowsError(try WatchCanonicalStorage.validateEmbedStorageAcknowledgement(type: "store_embed_keys",
            payload: keys, acknowledgement: legacyKeys, requestID: "keys-request", policy: policy))
    }

    // contract-test: supporting surface=gui.apple assertions=chats.persistence.client-encrypted,storage.privacy.ciphertext-boundary
    func testWatchBundleWritesHeadBeforeWrappersAndRetriesIdenticalCiphertextAfterLostReceipt() async throws {
        for failure in ["store_embed", "store_embed_keys"] {
            let bundle = try WatchCanonicalStorage.embedBundle(chatID: "chat", head: bundleHead(), keys: bundleKeys())
            let retained = try JSONDecoder().decode(WatchPendingCompletion.self, from: JSONEncoder().encode(bundle))
            XCTAssertEqual(retained.encryptedPayload, bundle.encryptedPayload, "Restart retains the exact encrypted attempt")
            var failOnce = true
            var calls: [(String, Data)] = []
            let request: WatchCanonicalStorage.Request = { type, payload, _, matches in
                calls.append((type, try JSONSerialization.data(withJSONObject: payload, options: [.sortedKeys])))
                if type == failure, failOnce { failOnce = false; throw WatchChatRuntimeError.socketUnavailable }
                let receipt = type == "store_embed" ? self.bundleHeadReceipt() : self.bundleKeyReceipt()
                XCTAssertTrue(matches(receipt))
                return receipt
            }
            do {
                try await WatchCanonicalStorage.persistEmbedBundle(retained, policy: .requireCanonicalDigest, request: request, validate: {})
                XCTFail("The missing receipt cannot retire this bundle")
            } catch WatchChatRuntimeError.socketUnavailable { }
            if failure == "store_embed" { XCTAssertEqual(calls.map { $0.0 }, ["store_embed"]) }
            try await WatchCanonicalStorage.persistEmbedBundle(retained, policy: .requireCanonicalDigest, request: request, validate: {})
            XCTAssertEqual(Array(calls.suffix(2)).map { $0.0 }, ["store_embed", "store_embed_keys"])
            XCTAssertEqual(calls.first?.1, calls.dropFirst().first { $0.0 == "store_embed" }?.1)
            if failure == "store_embed_keys" {
                XCTAssertEqual(calls.first { $0.0 == "store_embed_keys" }?.1, calls.last?.1)
            }
        }
    }

    // contract-test: supporting surface=gui.apple assertions=chats.persistence.client-encrypted,storage.surface.semantic-parity
    func testWatchHeadRejectionSendsNoWrappersAndCapabilityRejectionRemainsUpdateRequired() async throws {
        let changes: [[String: Any]] = [["request_id": "other"], ["embed_id": "other"],
            ["canonical_digest": "wrong"], ["canonical_digest": (bundleHeadReceipt()["canonical_digest"] as! String).uppercased()],
            ["canonical_source": "version_row"], ["canonical_digest": NSNull()], ["canonical_source": NSNull()],
            ["code": "client_capability_required"]]
        for change in changes {
            var calls: [String] = []
            let bundle = try WatchCanonicalStorage.embedBundle(chatID: "chat", head: bundleHead(), keys: bundleKeys())
            do {
                try await WatchCanonicalStorage.persistEmbedBundle(bundle, policy: .requireCanonicalDigest, request: { type, _, _, _ in
                    calls.append(type)
                    return self.bundleHeadReceipt().merging(change) { _, new in new }
                }, validate: {})
                XCTFail("Rejected head cannot count as saved")
            } catch CanonicalEmbedStorageReceiptError.updateRequired {
                XCTAssertEqual(change["code"] as? String, "client_capability_required")
            } catch { XCTAssertNil(change["code"]) }
            XCTAssertEqual(calls, ["store_embed"])
            XCTAssertEqual(try WatchCanonicalStorage.object(bundle.encryptedPayload)["head"] as? NSDictionary, bundleHead() as NSDictionary)
        }
    }

    // contract-test: supporting surface=gui.apple assertions=chats.persistence.client-encrypted,storage.surface.semantic-parity
    func testWatchStrictWrapperReceiptsRejectMissingPartialBooleanAndFloatingCounts() throws {
        for field in ["created_count", "failed_count", "requested_count"] {
            var missing = bundleKeyReceipt(); missing.removeValue(forKey: field)
            XCTAssertThrowsError(try WatchCanonicalStorage.validateEmbedStorageAcknowledgement(type: "store_embed_keys",
                payload: bundleKeys(), acknowledgement: missing, requestID: "key-request"))
            for value: Any in [true, 2.0, "2", NSNull(), -1, 1] {
                var invalid = bundleKeyReceipt(); invalid[field] = value
                XCTAssertThrowsError(try WatchCanonicalStorage.validateEmbedStorageAcknowledgement(type: "store_embed_keys",
                    payload: bundleKeys(), acknowledgement: invalid, requestID: "key-request"))
            }
        }
        var legacy = bundleKeyReceipt(); legacy.removeValue(forKey: "requested_count")
        XCTAssertNoThrow(try WatchCanonicalStorage.validateEmbedStorageAcknowledgement(type: "store_embed_keys",
            payload: bundleKeys(), acknowledgement: legacy, requestID: "key-request", policy: .allowLegacyReceipt))
    }

    // contract-test: supporting surface=gui.apple assertions=chats.persistence.client-encrypted,storage.privacy.ciphertext-boundary
    func testWatchMigratesKeysFirstJournalIntoImmutableBundleAndRetainsOrphans() throws {
        let head = WatchPendingCompletion(id: "head-request", chatId: "chat", eventType: "store_embed",
            encryptedPayload: try JSONSerialization.data(withJSONObject: bundleHead()))
        let keys = WatchPendingCompletion(id: "key-request", chatId: "chat", eventType: "store_embed_keys",
            encryptedPayload: try JSONSerialization.data(withJSONObject: bundleKeys()))
        let migrated = try WatchCanonicalStorage.migratedEmbedBundles([keys, head])
        XCTAssertEqual(migrated.count, 1)
        XCTAssertEqual(migrated.first?.eventType, "store_embed_bundle")
        let object = try WatchCanonicalStorage.object(try XCTUnwrap(migrated.first?.encryptedPayload))
        XCTAssertEqual(object["head"] as? NSDictionary, bundleHead() as NSDictionary)
        XCTAssertEqual(object["keys"] as? NSDictionary, bundleKeys() as NSDictionary)
        XCTAssertEqual(try WatchCanonicalStorage.migratedEmbedBundles([keys]), [keys])
    }

    // contract-test: supporting surface=gui.apple assertions=chats.persistence.client-encrypted,storage.privacy.ciphertext-boundary
    func testMalformedLegacyEmbedRetainsCiphertextWithoutBlockingUnrelatedCompletions() throws {
        let orphan = WatchPendingCompletion(id: "orphan", chatId: "chat", eventType: "store_embed",
            encryptedPayload: Data("invalid encrypted journal envelope".utf8))
        let message = WatchPendingCompletion(id: "message", chatId: "chat", eventType: "ai_response_completed",
            encryptedPayload: Data("cipher-message".utf8))
        let metadata = WatchPendingCompletion(id: "metadata", chatId: "other", eventType: "encrypted_chat_metadata",
            encryptedPayload: Data("cipher-metadata".utf8))
        let sameChatBundle = try WatchCanonicalStorage.embedBundle(chatID: "chat", head: bundleHead(), keys: bundleKeys())
        let otherChatBundle = try WatchCanonicalStorage.embedBundle(chatID: "other", head: bundleHead(), keys: bundleKeys())
        let entries = [orphan, message, sameChatBundle, metadata, otherChatBundle]
        let migrated = try WatchCanonicalStorage.migratedEmbedBundles(entries)
        XCTAssertEqual(migrated, entries, "Malformed legacy ciphertext stays retained unchanged")
        XCTAssertEqual(WatchCanonicalStorage.completionDrainCandidates(migrated), [message, metadata, otherChatBundle])
    }

    // contract-test: supporting surface=gui.apple assertions=chats.persistence.client-encrypted
    func testWatchBundleScopeInvalidationAfterHeadCannotWriteWrappers() async throws {
        let bundle = try WatchCanonicalStorage.embedBundle(chatID: "chat", head: bundleHead(), keys: bundleKeys())
        var current = true
        var calls: [String] = []
        do {
            try await WatchCanonicalStorage.persistEmbedBundle(bundle, policy: .requireCanonicalDigest, request: { type, _, _, _ in
                calls.append(type); current = false
                return self.bundleHeadReceipt()
            }, validate: { if !current { throw CancellationError() } })
            XCTFail("Invalidated account/server/deletion context cannot send wrappers")
        } catch is CancellationError { }
        XCTAssertEqual(calls, ["store_embed"])
    }

    // contract-test: supporting surface=gui.apple assertions=chats.persistence.client-encrypted
    func testWatchCapabilityErrorIsCorrelatedAndNeverSuccessfulStorageReceipt() throws {
        var inbox: [(type: String, payload: [String: Any])] = [("error", ["request_id": "other", "code": "client_capability_required"]),
            ("error", ["request_id": "head-request", "code": "client_capability_required"])]
        XCTAssertThrowsError(try WatchSocketResponses.takeMatchingResponse(from: &inbox, requestType: "store_embed",
            responseTypes: ["store_embed_confirmed"], matching: { $0["request_id"] as? String == "head-request" })) { error in
                guard case CanonicalEmbedStorageReceiptError.updateRequired = error else { return XCTFail("Must be update-required") }
        }
        XCTAssertEqual(inbox.count, 1)
        XCTAssertEqual(inbox.first?.payload["request_id"] as? String, "other")
    }

    // contract-test: supporting surface=gui.apple assertions=chats.persistence.client-encrypted,storage.privacy.ciphertext-boundary
    func testWatchBundleCreationRejectsEmptyMissingAndMalformedWrappers() {
        let invalid: [Any?] = [nil, [[String: Any]](), "malformed", [NSNull()]]
        for value in invalid {
            var keys = bundleKeys()
            if let value { keys["keys"] = value } else { keys.removeValue(forKey: "keys") }
            XCTAssertThrowsError(try WatchCanonicalStorage.embedBundle(chatID: "chat", head: bundleHead(), keys: keys))
        }
        XCTAssertNoThrow(try WatchCanonicalStorage.embedBundle(chatID: "chat", head: bundleHead(), keys: bundleKeys()))
    }

    // contract-test: supporting surface=gui.apple assertions=chats.persistence.client-encrypted,storage.surface.semantic-parity
    func testRestoredInvalidWrapperBundlesCannotWriteHeadOrRetireUnderEitherPolicy() async throws {
        let invalid: [Any?] = [nil, [[String: Any]](), "malformed", [NSNull()]]
        for policy in [CanonicalEmbedReceiptPolicy.requireCanonicalDigest, .allowLegacyReceipt] {
            for value in invalid {
                var keys = bundleKeys()
                if let value { keys["keys"] = value } else { keys.removeValue(forKey: "keys") }
                // Bypass the newly guarded factory to model a malformed older journal.
                let bytes = try JSONSerialization.data(withJSONObject: ["head": bundleHead(), "keys": keys], options: [.sortedKeys])
                let entry = WatchPendingCompletion(id: "head-request", chatId: "chat", eventType: "store_embed_bundle", encryptedPayload: bytes)
                var requests: [String] = []
                var retired = false
                do {
                    try await WatchCanonicalStorage.persistEmbedBundle(entry, policy: policy, request: { type, _, _, _ in
                        requests.append(type)
                        return type == "store_embed" ? self.bundleHeadReceipt() : self.bundleKeyReceipt()
                    }, validate: {})
                    retired = true
                    XCTFail("A head receipt cannot authorize retirement of missing wrappers")
                } catch WatchChatRuntimeError.invalidPendingTurn { }
                XCTAssertTrue(requests.isEmpty, "Malformed retained wrappers must fail before any canonical head is written")
                XCTAssertFalse(retired)
                XCTAssertEqual(entry.encryptedPayload, bytes, "Rejected retry retains the original ciphertext and request identity")
            }
        }
    }

    private func bundleHead() -> [String: Any] {
        ["request_id": "head-request", "embed_id": "synthetic-embed", "encrypted_content": "synthetic-cipher+/=",
         "encrypted_type": "synthetic-type", "status": "finished", "version_number": 1]
    }
    private func bundleKeys() -> [String: Any] {
        ["request_id": "key-request", "keys": [
            ["hashed_embed_id": CanonicalEmbedStorageReceipts.digest("synthetic-embed"), "key_type": "master", "encrypted_embed_key": "master-cipher"],
            ["hashed_embed_id": CanonicalEmbedStorageReceipts.digest("synthetic-embed"), "key_type": "chat", "encrypted_embed_key": "chat-cipher"]]]
    }
    private func bundleHeadReceipt() -> [String: Any] {
        ["request_id": "head-request", "embed_id": "synthetic-embed", "canonical_source": "head",
         "canonical_digest": CanonicalEmbedStorageReceipts.digest(bundleHead()["encrypted_content"] as! String)]
    }
    private func bundleKeyReceipt() -> [String: Any] {
        ["request_id": "key-request", "created_count": 2, "requested_count": 2, "failed_count": 0]
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
