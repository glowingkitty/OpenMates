import XCTest
import CryptoKit
import SwiftData
@testable import OpenMates

@MainActor
final class NativeAssistantSpeechTests: XCTestCase {
    // contract-test: supporting surface=gui.apple assertions=assistant-speech.surface.semantic-parity
    func testDraftTransferReadsPreferenceWithoutMountedControllerAndKeepsEnabledIntent() async throws {
        let source = AssistantSpeechScope(accountID: "a", serverID: "dev", chatID: "draft")
        let target = AssistantSpeechScope(accountID: "a", serverID: "dev", chatID: "created")
        let adapter = AssistantSpeechPreferenceAdapter(dependencies: .init(isCurrent: { _ in true },
            metadata: { _ in nil }, chatKey: { _ in XCTFail("Draft transfer must not request a key"); throw CancellationError() },
            sendMetadataAndWait: { _, _, _ in XCTFail("Draft transfer must not send metadata"); return 1 },
            storeCiphertext: { _, _, _ in XCTFail("Draft transfer must not store ciphertext") }))
        // No UI controller is constructed. Preserve a real opted-in draft intent.
        try await adapter.write(source, enabled: true)
        try await adapter.transferDraft(from: source, to: target)
        let sourceValue = try await adapter.read(source), targetValue = try await adapter.read(target)
        XCTAssertTrue(sourceValue); XCTAssertTrue(targetValue)
        XCTAssertTrue(adapter.hasIntent(source)); XCTAssertTrue(adapter.hasIntent(target))
    }

    // contract-test: supporting surface=gui.apple assertions=assistant-speech.surface.semantic-parity
    func testDraftTransferRejectsOwnershipChangeBeforeDestinationWrite() async throws {
        let source = AssistantSpeechScope(accountID: "a", serverID: "dev", chatID: "draft")
        let target = AssistantSpeechScope(accountID: "a", serverID: "dev", chatID: "created")
        var current = true
        let adapter = AssistantSpeechPreferenceAdapter(dependencies: .init(isCurrent: { _ in current },
            metadata: { _ in current = false; return nil },
            chatKey: { _ in throw CancellationError() }, sendMetadataAndWait: { _, _, _ in XCTFail("Stale write"); return 1 },
            storeCiphertext: { _, _, _ in XCTFail("Stale store") }))
        do { try await adapter.transferDraft(from: source, to: target); XCTFail("Stale transfer accepted") }
        catch is CancellationError {} catch { XCTFail("Unexpected error type") }
        XCTAssertFalse(adapter.hasIntent(target))
    }

    // contract-test: supporting surface=gui.apple assertions=assistant-speech.surface.semantic-parity
    func testDraftTransferRejectsPendingToggleWithoutLosingItsIntent() async throws {
        let source = AssistantSpeechScope(accountID: "a", serverID: "dev", chatID: "draft")
        let target = AssistantSpeechScope(accountID: "a", serverID: "dev", chatID: "created")
        let suspended = expectation(description: "toggle suspended")
        var resume: CheckedContinuation<AssistantSpeechMetadata?, Never>?
        let adapter = AssistantSpeechPreferenceAdapter(dependencies: .init(isCurrent: { _ in true },
            metadata: { _ in await withCheckedContinuation { resume = $0; suspended.fulfill() } },
            chatKey: { _ in throw CancellationError() }, sendMetadataAndWait: { _, _, _ in XCTFail("Unexpected send"); return 1 },
            storeCiphertext: { _, _, _ in XCTFail("Unexpected store") }))
        let write = Task { try await adapter.write(source, enabled: true) }
        await fulfillment(of: [suspended], timeout: 1)
        do { try await adapter.transferDraft(from: source, to: target); XCTFail("Pending toggle was bypassed") }
        catch AssistantSpeechFailure.preferenceBusy {} catch { XCTFail("Unexpected error type") }
        XCTAssertFalse(adapter.hasIntent(target))
        resume?.resume(returning: nil)
        try await write.value
        XCTAssertTrue(adapter.hasIntent(source))
    }

    private let scope = AssistantSpeechScope(accountID: "a", serverID: "dev", chatID: "c")
    private func dependencies() -> NativeAssistantSpeech.Dependencies {
        var value = false
        return .init(readPreference: { _ in value }, writePreference: { _,new in value = new },
              resolveAudio: { _,_ in Data() }, play: { _ in }, stopPlayback: {},
              cancelResponse: { _,_ in })
    }
    // contract-test: supporting surface=gui.apple assertions=assistant-speech.surface.semantic-parity
    func testTogglePersistsAndAddsActualPreflightMessageFields() async {
        var writes: [Bool] = []
        var deps = dependencies(); deps.readPreference = { _ in writes.last ?? false }; deps.writePreference = { _,value in writes.append(value) }
        let speech = NativeAssistantSpeech(dependencies: deps)
        await speech.activate(scope); await speech.toggle()
        XCTAssertEqual(writes, [true])
        XCTAssertEqual(speech.messageFields(for: scope)["auto_speak_response"] as? Bool, true)
        XCTAssertEqual(speech.messageFields(for: scope)["assistant_response_source_revision"] as? Int, 1)
        let foreign = AssistantSpeechScope(accountID: "b", serverID: "dev", chatID: "c")
        XCTAssertTrue(speech.messageFields(for: foreign).isEmpty)
        await speech.toggle(); XCTAssertTrue(speech.messageFields(for: scope).isEmpty)
        speech.reset()
    }
    // contract-test: supporting surface=gui.apple assertions=assistant-speech.surface.semantic-parity
    func testPersistenceFailureRollsBackAndShowsError() async {
        var deps = dependencies(); deps.writePreference = { _,_ in throw URLError(.notConnectedToInternet) }
        let speech = NativeAssistantSpeech(dependencies: deps)
        await speech.activate(scope); await speech.toggle()
        XCTAssertFalse(speech.enabled); XCTAssertNotNil(speech.error)
        XCTAssertTrue(speech.messageFields(for: scope).isEmpty); speech.reset()
    }
    // contract-test: supporting surface=gui.apple assertions=assistant-speech.surface.semantic-parity
    func testReadyAssetsPlayInCanonicalOrderOnceAndForeignScopeCannotPlay() async {
        let finished = expectation(description: "two provider assets played")
        finished.expectedFulfillmentCount = 2
        var resolved: [String] = []
        var deps = dependencies(); deps.readPreference = { _ in true }
        deps.resolveAudio = { _,id in resolved.append(id); return Data(id.utf8) }
        deps.play = { _ in finished.fulfill() }
        let speech = NativeAssistantSpeech(dependencies: deps)
        await speech.activate(scope); speech.expectResponse("m", in: scope)
        let later = event(id: "second", sequence: 1)
        speech.receive(later, in: scope)
        XCTAssertTrue(resolved.isEmpty)
        speech.receive(event(id: "first", sequence: 0), in: .init(accountID: "foreign", serverID: "dev", chatID: "c"))
        XCTAssertTrue(resolved.isEmpty)
        speech.receive(event(id: "first", sequence: 0), in: scope)
        await fulfillment(of: [finished], timeout: 1)
        XCTAssertEqual(resolved, ["first", "second"])
        speech.receive(later, in: scope)
        XCTAssertEqual(resolved.count, 2); speech.reset()
    }
    // contract-test: supporting surface=gui.apple assertions=assistant-speech.surface.semantic-parity
    func testFeedbackUses1800MillisecondsAndInitialLoadIsQuiet() async {
        let slept = expectation(description: "feedback delay")
        var delay: UInt64?
        var deps = dependencies(); deps.sleep = { ns in delay = ns; slept.fulfill() }
        let speech = NativeAssistantSpeech(dependencies: deps)
        await speech.activate(scope); XCTAssertNil(speech.feedback)
        await speech.toggle(); await fulfillment(of: [slept], timeout: 1)
        XCTAssertEqual(delay, 1_800_000_000); XCTAssertNil(speech.feedback)
        speech.reset()
    }
    // contract-test: supporting surface=gui.apple assertions=assistant-speech.surface.semantic-parity
    func testChatKeyCiphertextContainsNoPlaintextAndRoundTrips() async throws {
        let key = SymmetricKey(size: .bits256)
        let value = try await AssistantSpeechPreferenceAdapter.encrypt("true", key: key)
        XCTAssertNotEqual(value, "true")
        let plain = try await AssistantSpeechPreferenceAdapter.decrypt(value, key: key)
        XCTAssertEqual(plain, "true")
        XCTAssertEqual(Data(base64Encoded: value)?.prefix(2), Data("OM".utf8))
        do { _ = try await AssistantSpeechPreferenceAdapter.decrypt(value, key: SymmetricKey(size: .bits256)); XCTFail("Wrong key accepted") }
        catch {}
        let legacy = try AES.GCM.seal(Data("false".utf8), using: key).combined!.base64EncodedString()
        let legacyPlain = try await AssistantSpeechPreferenceAdapter.decrypt(legacy, key: key)
        XCTAssertEqual(legacyPlain, "false")
    }
    // contract-test: supporting surface=gui.apple assertions=assistant-speech.surface.semantic-parity
    func testSavedPreferenceTransportSendsCiphertextAndPersistsAcknowledgedVersion() async throws {
        let key = SymmetricKey(size: .bits256)
        var payload: [String: Any] = [:]
        var storedVersion: Int?
        var storedCiphertext: String?
        let adapter = AssistantSpeechPreferenceAdapter(dependencies: .init(
            isCurrent: { [scope = self.scope] in $0 == scope },
            metadata: { _ in .init(encryptedPreference: nil, encryptedChatKey: "wrapped",
                teamID: nil, messagesVersion: 2, titleVersion: 1, metadataVersion: 4, lastEditedTimestamp: 100) },
            chatKey: { _ in key },
            sendMetadataAndWait: { _, fields, minimum in
                payload = fields; XCTAssertEqual(minimum, 5); return 7
            }, storeCiphertext: { _, ciphertext, version in storedCiphertext = ciphertext; storedVersion = version }))
        try await adapter.write(scope, enabled: true)
        XCTAssertEqual(payload["chat_id"] as? String, scope.chatID)
        XCTAssertNil(payload["auto_speak_response"])
        XCTAssertEqual((payload["versions"] as? [String: Int])?["metadata_v"], 4)
        let ciphertext = try XCTUnwrap(payload["encrypted_auto_speak_response"] as? String)
        let plaintext = try await AssistantSpeechPreferenceAdapter.decrypt(ciphertext, key: key)
        XCTAssertEqual(plaintext, "true")
        XCTAssertEqual(storedCiphertext, ciphertext); XCTAssertEqual(storedVersion, 7)
    }
    // contract-test: supporting surface=gui.apple assertions=assistant-speech.surface.semantic-parity
    func testChangedAccountAfterACKCannotPersistCiphertext() async throws {
        let key = SymmetricKey(size: .bits256)
        var current = true
        var persisted = false
        let adapter = AssistantSpeechPreferenceAdapter(dependencies: .init(isCurrent: { _ in current },
            metadata: { _ in .init(encryptedPreference: nil, encryptedChatKey: nil,
                teamID: nil, messagesVersion: 2, titleVersion: 1, metadataVersion: 4, lastEditedTimestamp: 100) },
            chatKey: { _ in key }, sendMetadataAndWait: { _,_,_ in current = false; return 5 },
            storeCiphertext: { _,_,_ in persisted = true }))
        do { try await adapter.write(scope, enabled: true); XCTFail("stale ACK accepted") }
        catch is CancellationError {} catch { XCTFail("unexpected error") }
        XCTAssertFalse(persisted)
    }
    // contract-test: supporting surface=gui.apple assertions=assistant-speech.surface.semantic-parity
    func testSpeechCiphertextSurvivesDecodeOfflineAndChatCopies() throws {
        let decoder = JSONDecoder(); decoder.keyDecodingStrategy = .convertFromSnakeCase
        let chat = try decoder.decode(Chat.self, from: Data(#"{"id":"c","created_at":"2026-09-12T12:00:00Z","encrypted_auto_speak_response":"cipher","metadata_v":5}"#.utf8))
        XCTAssertEqual(chat.encryptedAutoSpeakResponse, "cipher")
        XCTAssertEqual(PersistedChat(from: chat).toChat().encryptedAutoSpeakResponse, "cipher")
        let store = ChatStore()
        let schema = Schema([PersistedChat.self, PersistedMessage.self])
        let configuration = ModelConfiguration("SpeechMergeTests", schema: schema, isStoredInMemoryOnly: true)
        let offline = OfflineStore(modelContainer: try ModelContainer(for: schema, configurations: [configuration]))
        store.setBridge(OfflineSyncBridge(chatStore: store, offlineStore: offline))
        store.upsertChat(chat)
        store.advanceMessagesVersion(chatId: "c", to: 4)
        XCTAssertEqual(store.chat(for: "c")?.encryptedAutoSpeakResponse, "cipher")
        XCTAssertEqual(store.chat(for: "c")?.messagesV, 4)
        let stale = chat.withSpeechPreference("old", metadataVersion: 3)
        store.upsertChat(stale)
        XCTAssertEqual(store.chat(for: "c")?.encryptedAutoSpeakResponse, "cipher")
        XCTAssertEqual(store.chat(for: "c")?.metadataV, 5)
        XCTAssertEqual(offline.loadChat(id: "c")?.encryptedAutoSpeakResponse, "cipher")
        XCTAssertEqual(offline.loadChat(id: "c")?.metadataV, 5)
        // A second late page must still compare against version five, both in
        // memory and after persistence; lowering the fence accepts stale audio.
        store.upsertChats([chat.withSpeechPreference("also-old", metadataVersion: 4)])
        XCTAssertEqual(store.chat(for: "c")?.encryptedAutoSpeakResponse, "cipher")
        XCTAssertEqual(offline.loadChat(id: "c")?.encryptedAutoSpeakResponse, "cipher")
        XCTAssertEqual(offline.loadChat(id: "c")?.metadataV, 5)
        XCTAssertEqual(offline.loadChat(id: "c")?.messagesV, 4)
    }
    // contract-test: supporting surface=gui.apple assertions=assistant-speech.surface.semantic-parity
    func testLoadFailureRetryLoadsPreferenceInsteadOfTryingPlayback() async {
        var attempts = 0
        var deps = dependencies()
        deps.readPreference = { _ in
            attempts += 1
            if attempts == 1 { throw URLError(.notConnectedToInternet) }
            return true
        }
        let speech = NativeAssistantSpeech(dependencies: deps)
        await speech.activate(scope)
        XCTAssertFalse(speech.ready); XCTAssertTrue(speech.canRetry)
        await speech.retry()
        XCTAssertEqual(attempts, 2); XCTAssertTrue(speech.ready); XCTAssertTrue(speech.enabled)
        XCTAssertNil(speech.error); speech.reset()
    }

    // contract-test: supporting surface=gui.apple assertions=assistant-speech.surface.semantic-parity
    func testFailedToggleRetryRetriesTheRequestedValue() async {
        var writes: [Bool] = []
        var deps = dependencies()
        deps.readPreference = { _ in writes.count > 1 }
        deps.writePreference = { _, value in
            writes.append(value)
            if writes.count == 1 { throw URLError(.networkConnectionLost) }
        }
        let speech = NativeAssistantSpeech(dependencies: deps)
        await speech.activate(scope); await speech.toggle()
        XCTAssertFalse(speech.enabled)
        await speech.retry()
        XCTAssertEqual(writes, [true, true]); XCTAssertTrue(speech.enabled); XCTAssertNil(speech.error)
        speech.reset()
    }

    // contract-test: supporting surface=gui.apple assertions=assistant-speech.surface.semantic-parity
    func testMuteStopsBeforePreferenceACKAndIgnoresLateProviderStatus() async {
        let writeStarted = expectation(description: "mute write suspended")
        var completeWrite: CheckedContinuation<Void, Never>?
        var stops = 0, plays = 0
        var deps = dependencies(); deps.readPreference = { _ in true }
        deps.stopPlayback = { stops += 1 }
        deps.play = { _ in plays += 1 }
        deps.writePreference = { _, _ in await withCheckedContinuation { completeWrite = $0; writeStarted.fulfill() } }
        let speech = NativeAssistantSpeech(dependencies: deps)
        await speech.activate(scope); speech.expectResponse("m", in: scope)
        let before = stops
        let write = Task { await speech.toggle() }
        await fulfillment(of: [writeStarted], timeout: 1)
        XCTAssertGreaterThan(stops, before); XCTAssertFalse(speech.enabled)
        speech.receive(event(id: "late", sequence: 0), in: scope)
        XCTAssertEqual(plays, 0)
        completeWrite?.resume(); await write.value; speech.reset()
    }

    // contract-test: supporting surface=gui.apple assertions=assistant-speech.surface.semantic-parity
    func testPlaybackWaitsForCompletionBeforeResolvingNextAsset() async {
        let firstStarted = expectation(description: "first player started")
        let secondStarted = expectation(description: "second player started")
        var finishFirst: CheckedContinuation<Void, Never>?
        var resolved: [String] = []
        var deps = dependencies(); deps.readPreference = { _ in true }
        deps.resolveAudio = { _, id in resolved.append(id); return Data(id.utf8) }
        deps.play = { bytes in
            if bytes == Data("first".utf8) {
                await withCheckedContinuation { finishFirst = $0; firstStarted.fulfill() }
            } else { secondStarted.fulfill() }
        }
        let speech = NativeAssistantSpeech(dependencies: deps)
        await speech.activate(scope); speech.expectResponse("m", in: scope)
        speech.receive(event(id: "first", sequence: 0), in: scope)
        speech.receive(event(id: "second", sequence: 1), in: scope)
        await fulfillment(of: [firstStarted], timeout: 1)
        XCTAssertEqual(resolved, ["first"])
        finishFirst?.resume()
        await fulfillment(of: [secondStarted], timeout: 1)
        XCTAssertEqual(resolved, ["first", "second"]); speech.reset()
    }

    // contract-test: supporting surface=gui.apple assertions=assistant-speech.surface.semantic-parity
    func testSameAccountNewSessionRejectsLateAudioAndOldProviderEvents() async {
        let resolving = expectation(description: "old asset suspended")
        let newPlayed = expectation(description: "new session asset played")
        var resumeOld: CheckedContinuation<Data, Never>?
        var played: [Data] = []
        var deps = dependencies(); deps.readPreference = { _ in true }
        deps.resolveAudio = { _, id in
            if id == "old" { return await withCheckedContinuation { resumeOld = $0; resolving.fulfill() } }
            return Data(id.utf8)
        }
        deps.play = { value in played.append(value); newPlayed.fulfill() }
        let speech = NativeAssistantSpeech(dependencies: deps)
        var old = scope; old.sessionID = UUID()
        var new = scope; new.sessionID = UUID()
        await speech.activate(old); speech.expectResponse("m", in: old)
        speech.receive(event(id: "old", sequence: 0), in: old)
        await fulfillment(of: [resolving], timeout: 1)
        await speech.activate(new); speech.expectResponse("m", in: new)
        resumeOld?.resume(returning: Data("old".utf8))
        speech.receive(event(id: "foreign", sequence: 0), in: old)
        speech.receive(event(id: "new", sequence: 0), in: new)
        await fulfillment(of: [newPlayed], timeout: 1)
        XCTAssertEqual(played, [Data("new".utf8)]); speech.reset()
    }

    // contract-test: supporting surface=gui.apple assertions=assistant-speech.surface.semantic-parity
    func testSegmentFailureIsVisibleAndDoesNotOfferFakeProviderRetry() async {
        var deps = dependencies(); deps.readPreference = { _ in true }
        let speech = NativeAssistantSpeech(dependencies: deps)
        await speech.activate(scope); speech.expectResponse("m", in: scope)
        speech.receive(.init(chat_id: "c", message_id: "m", status: "error", segment_id: "s",
                             sequence: 0, generated_asset_id: nil, segments: nil), in: scope)
        XCTAssertNotNil(speech.error); XCTAssertFalse(speech.canRetry)
        await speech.retry(); XCTAssertNotNil(speech.error); speech.reset()
    }

    // contract-test: supporting surface=gui.apple assertions=assistant-speech.surface.semantic-parity
    func testClearFencesSuspendedPreferenceWriteEvenWhenAccountMatchesAgain() async throws {
        let suspended = expectation(description: "old metadata read")
        var resumeOld: CheckedContinuation<AssistantSpeechMetadata?, Never>?
        var persisted = 0
        let adapter = AssistantSpeechPreferenceAdapter(dependencies: .init(isCurrent: { _ in true },
            metadata: { _ in await withCheckedContinuation { resumeOld = $0; suspended.fulfill() } },
            chatKey: { _ in SymmetricKey(size: .bits256) }, sendMetadataAndWait: { _,_,_ in 3 },
            storeCiphertext: { _,_,_ in persisted += 1 }))
        let old = Task { try await adapter.write(scope, enabled: true) }
        await fulfillment(of: [suspended], timeout: 1)
        adapter.clear()
        resumeOld?.resume(returning: .init(encryptedPreference: nil, encryptedChatKey: nil,
            teamID: nil, messagesVersion: 1, titleVersion: 0, metadataVersion: 2, lastEditedTimestamp: 1))
        do { try await old.value; XCTFail("old session write resumed") } catch is CancellationError {} catch { XCTFail("unexpected error") }
        XCTAssertEqual(persisted, 0); XCTAssertFalse(adapter.hasIntent(scope))
    }

    // contract-test: supporting surface=gui.apple assertions=assistant-speech.surface.semantic-parity
    func testFailedSavedWriteDoesNotLeaveDraftIntentToPromoteSilently() async {
        let adapter = AssistantSpeechPreferenceAdapter(dependencies: .init(isCurrent: { _ in true },
            metadata: { _ in .init(encryptedPreference: nil, encryptedChatKey: nil, teamID: nil,
                messagesVersion: 1, titleVersion: 0, metadataVersion: 0, lastEditedTimestamp: 0) },
            chatKey: { _ in SymmetricKey(size: .bits256) },
            sendMetadataAndWait: { _,_,_ in throw URLError(.networkConnectionLost) }, storeCiphertext: { _,_,_ in }))
        do { try await adapter.write(scope, enabled: true); XCTFail("write unexpectedly succeeded") } catch {}
        XCTAssertFalse(adapter.hasIntent(scope))
    }

    // contract-test: supporting surface=gui.apple assertions=assistant-speech.surface.semantic-parity
    func testDraftPromotesOnceAfterMessagesExistAndPreservesRemoteCiphertext() async throws {
        let key = SymmetricKey(size: .bits256)
        var version = 0, writes = 0
        var ciphertext: String?
        let adapter = AssistantSpeechPreferenceAdapter(dependencies: .init(isCurrent: { _ in true },
            metadata: { _ in .init(encryptedPreference: ciphertext, encryptedChatKey: nil, teamID: nil,
                messagesVersion: version, titleVersion: 0, metadataVersion: writes, lastEditedTimestamp: 0) },
            chatKey: { _ in key }, sendMetadataAndWait: { _,_,minimum in writes += 1; return minimum },
            storeCiphertext: { _,cipher,_ in ciphertext = cipher }))
        try await adapter.write(scope, enabled: true); try await adapter.promote(scope)
        XCTAssertEqual(writes, 0); XCTAssertTrue(adapter.hasIntent(scope))
        version = 1; try await adapter.promote(scope); try await adapter.promote(scope)
        XCTAssertEqual(writes, 1); XCTAssertFalse(adapter.hasIntent(scope))
        version = 0; ciphertext = nil; try await adapter.write(scope, enabled: true)
        version = 2; ciphertext = try await AssistantSpeechPreferenceAdapter.encrypt("false", key: key)
        try await adapter.promote(scope)
        let enabled = try await adapter.read(scope)
        XCTAssertFalse(enabled); XCTAssertEqual(writes, 1)
    }

    // contract-test: supporting surface=gui.apple assertions=assistant-speech.surface.semantic-parity
    func testExactGeneratedEmbedNormalizesEncryptedResponseAndRejectsForeignChat() throws {
        let fields: [String: Any] = ["embed_id": "asset", "chat_id": "c", "status": "finished",
            "already_encrypted": true, "type": "encrypted-type", "content": "encrypted-content", "embed_keys": []]
        let asset = try AssistantSpeechEmbedPayload.decode(fields, assetID: "asset", chatID: "c")
        XCTAssertEqual(asset.record.encryptedContent, "encrypted-content")
        XCTAssertEqual(asset.record.encryptedType, "encrypted-type"); XCTAssertNil(asset.record.rawData)
        var legacy = fields; legacy["type"] = "app_skill_use"
        let legacyAsset = try AssistantSpeechEmbedPayload.decode(legacy, assetID: "asset", chatID: "c")
        XCTAssertNil(legacyAsset.record.encryptedType)
        XCTAssertEqual(legacyAsset.record.encryptedContent, "encrypted-content")
        XCTAssertThrowsError(try AssistantSpeechEmbedPayload.decode(fields, assetID: "asset", chatID: "other"))
        XCTAssertThrowsError(try AssistantSpeechEmbedPayload.decode(fields, assetID: "different", chatID: "c"))
    }

    // contract-test: supporting surface=gui.apple assertions=assistant-speech.surface.semantic-parity
    func testSpeechMediaCacheSeparatesAccountSessionAndEncryptionMaterial() {
        func key(_ namespace: String?, _ encryptionKey: String = "key") -> String {
            S3MediaClient.cacheKey(s3Url: "url", aesKey: encryptionKey, nonce: nil,
                encryption: nil, s3Key: "same-object", namespace: namespace)
        }
        XCTAssertEqual(key(nil), "same-object")
        XCTAssertNotEqual(key("account-a:session-1"), key("account-b:session-1"))
        XCTAssertNotEqual(key("account-a:session-1"), key("account-a:session-2"))
        XCTAssertNotEqual(key("account-a:session-1"), key("account-a:session-1", "rotated"))
    }

    // contract-test: supporting surface=gui.apple assertions=assistant-speech.surface.semantic-parity
    func testEarlySpeechBufferKeepsFirstReadySegmentAcrossLifecycleBurst() {
        var buffer = AssistantSpeechEarlyEvents()
        for sequence in 0..<30 {
            for status in ["queued", "generating", "ready"] {
                buffer.append(.init(chat_id: "c", message_id: "m", status: status,
                    segment_id: "s\(sequence)", sequence: sequence, generated_asset_id: "a\(sequence)", segments: nil))
            }
        }
        XCTAssertEqual(buffer.events.count, 30)
        XCTAssertEqual(buffer.events.first?.sequence, 0)
        XCTAssertTrue(buffer.events.allSatisfy { $0.status == "ready" })
        buffer.append(.init(chat_id: "c", message_id: "m", status: "queued",
            segment_id: "s0", sequence: 0, generated_asset_id: nil, segments: nil))
        XCTAssertEqual(buffer.events.first?.status, "ready")
    }

    // contract-test: supporting surface=gui.apple assertions=assistant-speech.surface.semantic-parity
    func testSpeechBindsOnlyToExactOutgoingTurnAndRealAssistantIdentity() {
        let fields: [String: Any] = ["chat_id": "c", "user_message_id": "user", "message_id": "assistant"]
        func match(_ type: String, _ chat: String = "c", _ user: String? = "user") -> String? {
            AssistantSpeechAppRuntime.correlatedAssistantMessageID(type: type, fields: fields, chatID: chat, expectedUserMessageID: user)
        }
        XCTAssertEqual(match("ai_typing_started"), "assistant")
        XCTAssertEqual(match("ai_message_update"), "assistant")
        XCTAssertNil(match("assistant_speech_status")); XCTAssertNil(match("ai_message_update", "foreign"))
        XCTAssertNil(match("ai_message_update", "c", "other-turn")); XCTAssertNil(match("ai_message_update", "c", nil))
    }

    // contract-test: supporting surface=gui.apple assertions=assistant-speech.surface.semantic-parity
    func testPreferenceACKRequiresAuthoritativeVersionAndExcludesUserStorageACK() {
        let ack: [String: Any] = ["chat_id": "c", "message_id": NSNull(),
            "status": "queued_for_storage", "versions": ["metadata_v": 5]]
        XCTAssertEqual(AssistantSpeechMetadataAcknowledgement.version(ack, chatID: "c", minimum: 5), 5)
        XCTAssertNil(AssistantSpeechMetadataAcknowledgement.version(ack, chatID: "c", minimum: 6))
        XCTAssertNil(AssistantSpeechMetadataAcknowledgement.version(ack, chatID: "other", minimum: 5))
        var userACK = ack; userACK["message_id"] = "stored-user-message"
        XCTAssertNil(AssistantSpeechMetadataAcknowledgement.version(userACK, chatID: "c", minimum: 5))
        var missingVersion = ack; missingVersion.removeValue(forKey: "versions")
        XCTAssertNil(AssistantSpeechMetadataAcknowledgement.version(missingVersion, chatID: "c", minimum: 5))
    }

    // contract-test: supporting surface=gui.apple assertions=assistant-speech.surface.semantic-parity
    func testEarlyReadyAssetWaitsForItsComposerToOwnPlayback() async {
        var ownsPlayback = false, resolutions = 0
        let played = expectation(description: "asset plays after destination composer mounts")
        var deps = dependencies(); deps.readPreference = { _ in true }
        deps.canPlay = { _ in ownsPlayback }
        deps.resolveAudio = { _,_ in resolutions += 1; return Data() }
        deps.play = { _ in played.fulfill() }
        let speech = NativeAssistantSpeech(dependencies: deps)
        await speech.activate(scope); speech.expectResponse("m", in: scope)
        speech.receive(event(id: "first", sequence: 0), in: scope)
        XCTAssertEqual(resolutions, 0)
        ownsPlayback = true; speech.resumePlaybackIfReady()
        await fulfillment(of: [played], timeout: 1)
        XCTAssertEqual(resolutions, 1); speech.reset()
    }

    private func event(id: String, sequence: Int) -> AssistantSpeechStatus {
        .init(chat_id: "c", message_id: "m", status: "ready", segment_id: id,
              sequence: sequence, generated_asset_id: id, segments: nil)
    }
}
