// Unit coverage for the portable Watch chat runtime and offline cache.
// These tests avoid network, credentials, and message plaintext from real users.
// They lock down deterministic cache persistence, offline fallback behavior, and
// local pending message snapshots before watchOS UI tests exercise the shell.

import XCTest
import CryptoKit
@testable import OpenMates

@MainActor
final class WatchChatRuntimeTests: XCTestCase {
    // contract-test: supporting surface=gui.apple assertions=apple-watch.offline.recent-cohort,apple-watch.embeds.read-only-fullscreen
    func testUnopenedCohortMediaReopensEncryptedDiskIntoNormalOfflineThumbnailAndAudioModels() async throws {
        let directory = temporaryDirectory()
        defer { try? FileManager.default.removeItem(at: directory) }
        let mediaDirectory = directory.appendingPathComponent("media")
        let cache = WatchChatOfflineCache(directory: directory)
        let media = WatchHubOfflineCache(directory: mediaDirectory, cohortPartition: true, entryLimit: WatchAudioSource.maximumBytes)
        let crypto = WatchOfflineFixtureCrypto()
        let transport = WatchOfflineFixtureTransport(crypto: crypto); transport.includesMedia = true
        let runtime = WatchChatRuntime(currentUserId: WatchOfflineFixtureTransport.accountID,
            api: transport, cache: cache, crypto: crypto, syncSocket: transport, mediaCache: media)
        await runtime.setForeground(true); await runtime.refresh(); await runtime.waitForRecentOfflineSync()
        await runtime.waitForRecentMediaSync()
        XCTAssertNil(runtime.selectedChatId)
        XCTAssertTrue(runtime.messagesByChatId.isEmpty, "Unvisited media maintenance never publishes transcripts")
        XCTAssertEqual(runtime.offlineMediaStatus, WatchOfflineMediaStatus(requested: 2, retained: 2, failed: 0, finished: true))
        XCTAssertEqual(transport.thumbnailReads, 1); XCTAssertEqual(transport.audioReads, 1)
        await runtime.refresh(); await runtime.waitForRecentOfflineSync(); await runtime.waitForRecentMediaSync()
        XCTAssertEqual(transport.thumbnailReads, 1, "Repeated sync deduplicates already retained current content")
        XCTAssertEqual(transport.audioReads, 1)
        for entry in try FileManager.default.contentsOfDirectory(at: mediaDirectory, includingPropertiesForKeys: nil) {
            let bytes = try Data(contentsOf: entry)
            XCTAssertNil(bytes.range(of: WatchOfflineFixtureTransport.thumbnail))
            XCTAssertNil(bytes.range(of: Data("RIFF".utf8)))
            XCTAssertFalse(entry.lastPathComponent.contains("offline"))
        }
        runtime.stopRealtimeSync(); transport.offline = true
        let reopenedMedia = WatchHubOfflineCache(directory: mediaDirectory, cohortPartition: true, entryLimit: WatchAudioSource.maximumBytes)
        let reopened = WatchChatRuntime(currentUserId: WatchOfflineFixtureTransport.accountID,
            api: transport, cache: cache, crypto: WatchOfflineFixtureCrypto(key: crypto.key), syncSocket: nil, mediaCache: reopenedMedia)
        await reopened.loadCachedSnapshot()
        await reopened.openChat(try XCTUnwrap(reopened.chats.first { $0.id == "watch-offline-20" }))
        XCTAssertTrue(reopened.isOffline)
        let image = WatchEmbedPreviewMapper.makeModel(for: try XCTUnwrap(reopened.hydratedEmbedPreviews["offline-image"]), chatId: "watch-offline-20")
        let audio = WatchEmbedPreviewMapper.makeModel(for: try XCTUnwrap(reopened.hydratedEmbedPreviews["offline-audio"]), chatId: "watch-offline-20")
        let thumbnail = try await reopened.retainedThumbnailData(for: image.detailContent)
        let recording = try await reopened.audioPlaybackData(for: audio)
        XCTAssertEqual(thumbnail, WatchOfflineFixtureTransport.thumbnail)
        XCTAssertEqual(recording, WatchOfflineFixtureTransport.audio)
        XCTAssertEqual(transport.thumbnailReads, 1); XCTAssertEqual(transport.audioReads, 1, "Offline playback performs no presign or media request")
        reopened.stopRealtimeSync()
    }

    // contract-test: supporting surface=gui.apple assertions=apple-watch.offline.recent-cohort,apple-watch.embeds.read-only-fullscreen
    func testSuspendedRetainedMediaReadsRejectSameChatRemovalAndVersionReplacement() async throws {
        let directory = temporaryDirectory()
        defer { try? FileManager.default.removeItem(at: directory) }
        let cache = WatchChatOfflineCache(directory: directory)
        let media = WatchHubOfflineCache(directory: directory.appendingPathComponent("media"),
            cohortPartition: true, entryLimit: WatchAudioSource.maximumBytes)
        let crypto = WatchOfflineFixtureCrypto()
        let transport = WatchOfflineFixtureTransport(crypto: crypto); transport.includesMedia = true
        let warming = WatchChatRuntime(currentUserId: WatchOfflineFixtureTransport.accountID,
            api: transport, cache: cache, crypto: crypto, syncSocket: transport, mediaCache: media)
        await warming.setForeground(true); await warming.refresh()
        await warming.waitForRecentOfflineSync(); await warming.waitForRecentMediaSync()
        XCTAssertTrue(warming.offlineMediaStatus.complete)
        warming.stopRealtimeSync(); transport.offline = true
        let chatID = "watch-offline-20"
        for suspension in ["key", "cache"] {
          for kind in ["thumbnail", "audio"] {
            for mutation in ["remove", "version"] {
                let gate = WatchChatFetchGate()
                let beforeCacheLoad: (@Sendable () async -> Void)? = suspension == "cache"
                    ? { @Sendable in await gate.suspendFetch() } : nil
                let reopenedMedia = WatchHubOfflineCache(directory: directory.appendingPathComponent("media"),
                    cohortPartition: true, entryLimit: WatchAudioSource.maximumBytes, beforeLoad: beforeCacheLoad)
                let reopenedCrypto = WatchOfflineFixtureCrypto(key: crypto.key)
                let reopened = WatchChatRuntime(currentUserId: WatchOfflineFixtureTransport.accountID,
                    api: transport, cache: cache, crypto: reopenedCrypto, syncSocket: nil, mediaCache: reopenedMedia)
                await reopened.loadCachedSnapshot()
                await reopened.openChat(try XCTUnwrap(reopened.chats.first { $0.id == chatID }))
                let embedID = kind == "thumbnail" ? "offline-image" : "offline-audio"
                let ref = try XCTUnwrap(reopened.hydratedEmbedPreviews[embedID])
                let model = WatchEmbedPreviewMapper.makeModel(for: ref, chatId: chatID)
                if suspension == "key" { reopenedCrypto.beforeOfflineMediaKey = { await gate.suspendFetch() } }
                let pending = Task<Data?, Error> {
                    if kind == "thumbnail" { return try await reopened.retainedThumbnailData(for: model.detailContent) }
                    return try await reopened.audioPlaybackData(for: model)
                }
                await gate.waitUntilStarted()
                reopenedCrypto.beforeOfflineMediaKey = nil
                if mutation == "remove" {
                    await reopened.loadOfflinePage(0)
                    XCTAssertNil(reopened.hydratedEmbedPreviews[embedID])
                } else {
                    // A real current encrypted embed update supersedes the model
                    // while the same selected-chat read is waiting for its key.
                    var fields = try XCTUnwrap(ref.data).mapValues(\.value)
                    fields["version_number"] = 2
                    let key = SymmetricKey(size: .bits256)
                    let content = String(decoding: try JSONSerialization.data(withJSONObject: fields, options: [.sortedKeys]), as: UTF8.self)
                    await reopened.handleEmbedEvent(type: "send_embed_data", payload: [
                        "embed_id": embedID, "chat_id": chatID, "user_id": WatchOfflineFixtureTransport.accountID,
                        "type": try ComposerEmbedCrypto.encryptContent(ref.type, using: key),
                        "content": try ComposerEmbedCrypto.encryptContent(content, using: key),
                        "status": "finished", "version_number": 2, "already_encrypted": true, "encryption_mode": "client",
                        "embed_keys": [["hashed_embed_id": WatchChatKeyWrapperRecord.hashedChatId(for: embedID),
                            "key_type": "master", "hashed_user_id": WatchChatKeyWrapperRecord.hashedChatId(for: WatchOfflineFixtureTransport.accountID),
                            "encrypted_embed_key": try ComposerEmbedCrypto.wrapKey(key, using: crypto.key)]]
                    ])
                    let replacement = WatchEmbedPreviewMapper.makeModel(for: try XCTUnwrap(reopened.hydratedEmbedPreviews[embedID]), chatId: chatID)
                    XCTAssertNotEqual(replacement.detailContent.retainedMediaKey, model.detailContent.retainedMediaKey)
                }
                XCTAssertEqual(reopened.selectedChatId, chatID)
                await gate.release()
                do { _ = try await pending.value; XCTFail("Suspended \(suspension) \(kind) read returned stale bytes after same-chat \(mutation)") }
                catch { XCTAssertTrue(error is CancellationError) }
                reopened.stopRealtimeSync()
            }
          }
        }
        XCTAssertEqual(transport.thumbnailReads, 1); XCTAssertEqual(transport.audioReads, 1)
    }

    // contract-test: supporting surface=gui.apple assertions=apple-watch.offline.recent-cohort,apple-watch.embeds.read-only-fullscreen
    func testMediaFailureIsPartialAndCohortChangeCancelsHeldFetchWithoutRecreatingPrunedBytes() async throws {
        let directory = temporaryDirectory()
        defer { try? FileManager.default.removeItem(at: directory) }
        let mediaDirectory = directory.appendingPathComponent("media")
        let media = WatchHubOfflineCache(directory: mediaDirectory, cohortPartition: true, entryLimit: WatchAudioSource.maximumBytes)
        let crypto = WatchOfflineFixtureCrypto()
        let transport = WatchOfflineFixtureTransport(crypto: crypto)
        transport.includesMedia = true; transport.failAudio = true
        let runtime = WatchChatRuntime(currentUserId: WatchOfflineFixtureTransport.accountID, api: transport,
            cache: WatchChatOfflineCache(directory: directory), crypto: crypto, syncSocket: transport, mediaCache: media)
        await runtime.setForeground(true); await runtime.refresh(); await runtime.waitForRecentOfflineSync(); await runtime.waitForRecentMediaSync()
        XCTAssertEqual(runtime.offlineMediaStatus.requested, 2)
        XCTAssertEqual(runtime.offlineMediaStatus.retained, 1)
        XCTAssertEqual(runtime.offlineMediaStatus.failed, 1)
        XCTAssertFalse(runtime.offlineMediaStatus.complete)
        // Remove the current cohort receipt's assets, forcing a real held request.
        let scope = WatchWorkflowDetailScope.capture(accountID: WatchOfflineFixtureTransport.accountID)
        _ = try await media.retainCohort(keys: [], scope: scope)
        transport.holdMedia = true
        await runtime.refresh(); await runtime.waitForRecentOfflineSync()
        let deadline = ContinuousClock.now.advanced(by: .seconds(3))
        while transport.thumbnailReads < 2, ContinuousClock.now < deadline { try await Task.sleep(for: .milliseconds(5)) }
        XCTAssertEqual(transport.thumbnailReads, 2)
        transport.excludeNewest = true
        await runtime.refresh(); await runtime.waitForRecentOfflineSync(); await runtime.waitForRecentMediaSync()
        transport.holdMedia = false
        XCTAssertTrue(runtime.offlineMediaStatus.complete)
        XCTAssertEqual(runtime.offlineMediaStatus.requested, 0)
        let entries = (try? FileManager.default.contentsOfDirectory(at: mediaDirectory, includingPropertiesForKeys: nil)) ?? []
        XCTAssertTrue(entries.isEmpty, "A cancelled old media request cannot resurrect the chat removed from the cohort")
        runtime.stopRealtimeSync()
    }

    // contract-test: supporting surface=gui.apple assertions=apple-watch.chats.new-text-reply,apple-watch.chats.browse-search-open
    func testLocalFirstTurnSkipsMissingCanonicalRowBeforeDuringAndAfterRejectedAdmission() async throws {
        let directory = temporaryDirectory()
        defer { try? FileManager.default.removeItem(at: directory) }
        let cache = WatchChatOfflineCache(directory: directory)
        let api = FakeWatchChatAPI()
        api.messageWindowError = APIError.httpError(status: 404, message: "Chat not found")
        let socket = FakeWatchChatSyncSocket(shouldRejectSend: true)
        let runtime = WatchChatRuntime(api: api, cache: cache, crypto: FakeWatchChatCrypto(),
            syncSocket: socket, syncSession: WatchSyncSession(sessionId: "synthetic", token: "synthetic"))
        await runtime.createNewChat()
        let identity = try XCTUnwrap(runtime.selectedChat)
        await runtime.refreshSelectedChat()
        await runtime.openChat(identity)
        XCTAssertNil(runtime.errorMessage)
        XCTAssertEqual(api.fetchMessageWindowCallCount, 0)
        socket.beforeTurnResult = { [weak runtime] in
            let runtime = try XCTUnwrap(runtime)
            await runtime.refreshSelectedChat()
            await runtime.openChat(try XCTUnwrap(runtime.selectedChat))
            XCTAssertEqual(api.fetchMessageWindowCallCount, 0, "An in-flight first turn has no canonical ACK")
        }
        let queued = await runtime.sendText("Synthetic first turn")
        XCTAssertTrue(queued, "Rejected admission retains the durable turn for retry")
        let saved = await cache.loadSnapshot()
        XCTAssertEqual(saved.pendingTextSends.count, 1)
        let admissionError = runtime.errorMessage
        await runtime.refreshSelectedChat()
        await runtime.openChat(try XCTUnwrap(runtime.selectedChat))
        XCTAssertEqual(api.fetchMessageWindowCallCount, 0)
        XCTAssertEqual(runtime.errorMessage, admissionError, "Navigation cannot replace admission diagnostics with a premature 404")
        XCTAssertEqual(runtime.selectedChatId, identity.id)
        runtime.stopRealtimeSync()
    }

    // contract-test: supporting surface=gui.apple assertions=apple-watch.chats.new-text-reply,apple-watch.chats.browse-search-open
    func testFirstCanonicalACKReleasesReadFenceForSameChatAndWrappedKey() async throws {
        let directory = temporaryDirectory()
        defer { try? FileManager.default.removeItem(at: directory) }
        let cache = WatchChatOfflineCache(directory: directory)
        let api = FakeWatchChatAPI()
        let socket = FakeWatchChatSyncSocket()
        let runtime = WatchChatRuntime(api: api, cache: cache, crypto: FakeWatchChatCrypto(),
            syncSocket: socket, syncSession: WatchSyncSession(sessionId: "synthetic", token: "synthetic"))
        await runtime.createNewChat()
        let identity = try XCTUnwrap(runtime.selectedChat)
        socket.beforeTurnResult = { [weak runtime] in
            await runtime?.refreshSelectedChat()
            XCTAssertEqual(api.fetchMessageWindowCallCount, 0, "Dispatch alone cannot release the fence")
        }
        let sent = await runtime.sendText("Synthetic acknowledged turn")
        XCTAssertTrue(sent)
        let saved = await cache.loadSnapshot()
        XCTAssertTrue(saved.pendingTextSends.isEmpty)
        XCTAssertEqual(socket.sentTurns.count, 1)
        XCTAssertEqual(runtime.selectedChatId, identity.id)
        XCTAssertEqual(runtime.selectedChat?.encryptedChatKey, identity.encryptedChatKey)
        XCTAssertEqual(api.fetchMessageWindowCallCount, 1, "Successful canonical admission resumes the normal read")
        await runtime.openChat(try XCTUnwrap(runtime.selectedChat))
        XCTAssertEqual(api.fetchMessageWindowCallCount, 2)
        runtime.stopRealtimeSync()
    }

    // contract-test: supporting surface=gui.apple assertions=apple-watch.chats.new-text-reply,apple-watch.offline.recent-cohort
    func testColdRelaunchFirstTurnFencePreservesExactEncryptedReplayThenResumesReads() async throws {
        let directory = temporaryDirectory()
        defer { try? FileManager.default.removeItem(at: directory) }
        let cache = WatchChatOfflineCache(directory: directory)
        let failingSocket = FakeWatchChatSyncSocket(shouldRejectSend: true)
        let chatKey = SymmetricKey(size: .bits256)
        let original = WatchChatRuntime(api: FakeWatchChatAPI(), cache: cache, crypto: FakeWatchChatCrypto(textKey: chatKey),
            syncSocket: failingSocket, syncSession: WatchSyncSession(sessionId: "synthetic", token: "synthetic"))
        await original.createNewChat()
        let identity = try XCTUnwrap(original.selectedChat)
        let queued = await original.sendText("Synthetic durable first turn")
        XCTAssertTrue(queued)
        let before = await cache.loadSnapshot()
        let pending = try XCTUnwrap(before.pendingTextSends.first)
        let savedCiphertext = try XCTUnwrap(pending.encryptedPreparedTurn)
        // The retained outbox really uses AES-GCM. Replaying must preserve this
        // exact ciphertext/nonce, while transport JSON objects may reorder keys.
        let savedPlaintext = try ComposerEmbedCrypto.decryptContent(savedCiphertext, using: chatKey)
        let savedPrepared = try WatchCanonicalStorage.object(Data(savedPlaintext.utf8))
        func canonicalJSON(_ object: Any) throws -> Data {
            try JSONSerialization.data(withJSONObject: object, options: [.sortedKeys])
        }
        let expectedPreflight = try canonicalJSON(try XCTUnwrap(savedPrepared["preflight"] as? [String: Any]))
        let expectedInference = try canonicalJSON(try XCTUnwrap(savedPrepared["inference"] as? [String: Any]))
        XCTAssertEqual(try ComposerEmbedCrypto.decryptContent(pending.encryptedContent, using: chatKey), "Synthetic durable first turn")
        XCTAssertTrue(pending.preflightJSON.isEmpty)
        XCTAssertTrue(pending.inferenceJSON.isEmpty)
        original.stopRealtimeSync()

        let api = FakeWatchChatAPI()
        api.messageWindowError = APIError.httpError(status: 404, message: "Chat not found")
        let socket = FakeWatchChatSyncSocket(shouldRejectSend: true)
        let restored = WatchChatRuntime(api: api, cache: cache, crypto: FakeWatchChatCrypto(textKey: chatKey),
            syncSocket: socket, syncSession: WatchSyncSession(sessionId: "synthetic", token: "synthetic"))
        await restored.loadCachedSnapshot()
        await restored.openChat(try XCTUnwrap(restored.chats.first { $0.id == identity.id }))
        await restored.refreshSelectedChat()
        XCTAssertEqual(api.fetchMessageWindowCallCount, 0, "Recovered pending authority fences REST without an in-memory transient identity")
        await restored.startRealtimeSync()
        let rejected = await cache.loadSnapshot()
        XCTAssertEqual(rejected.pendingTextSends, [pending])
        XCTAssertEqual(api.fetchMessageWindowCallCount, 0)
        XCTAssertFalse(socket.attemptedTurns.isEmpty)
        XCTAssertTrue(socket.attemptedTurns.allSatisfy { $0.id == pending.id && $0.messageId == pending.messageId
            && $0.encryptedContent == pending.encryptedContent && $0.encryptedPreparedTurn == pending.encryptedPreparedTurn })
        socket.shouldRejectSend = false
        api.messageWindowError = nil
        await restored.refresh()
        let acknowledged = await cache.loadSnapshot()
        XCTAssertTrue(acknowledged.pendingTextSends.isEmpty)
        XCTAssertEqual(socket.sentTurns.count, 1)
        let originalAttempt = try XCTUnwrap(failingSocket.attemptedTurns.first)
        let committedReplay = try XCTUnwrap(socket.sentTurns.first)
        for attempt in [originalAttempt] + socket.attemptedTurns {
            XCTAssertEqual(attempt.id, pending.id)
            XCTAssertEqual(attempt.chatId, pending.chatId)
            XCTAssertEqual(attempt.messageId, pending.messageId)
            XCTAssertEqual(attempt.createdAt, pending.createdAt)
            XCTAssertEqual(attempt.encryptedChatKey, pending.encryptedChatKey)
            XCTAssertEqual(attempt.encryptedContent, pending.encryptedContent)
            XCTAssertEqual(attempt.encryptedPreparedTurn, savedCiphertext)
            // Production admission reparses these objects and the backend commits
            // canonical JSON. Compare every field to the persisted authority;
            // dictionary serialization order is not a transport identity.
            XCTAssertEqual(try canonicalJSON(WatchCanonicalStorage.object(attempt.preflightJSON)), expectedPreflight)
            XCTAssertEqual(try canonicalJSON(WatchCanonicalStorage.object(attempt.inferenceJSON)), expectedInference)
        }
        XCTAssertEqual(committedReplay.encryptedPreparedTurn, savedCiphertext)
        XCTAssertEqual(committedReplay.encryptedContent, pending.encryptedContent)
        XCTAssertEqual(restored.selectedChatId, identity.id)
        XCTAssertEqual(restored.selectedChat?.encryptedChatKey, identity.encryptedChatKey)
        await restored.refreshSelectedChat()
        XCTAssertEqual(api.fetchMessageWindowCallCount, 1)
        restored.stopRealtimeSync()
    }

    // contract-test: supporting surface=gui.apple assertions=apple-watch.chats.browse-search-open
    func testUnknownZeroVersionRemoteChatStillReadsCanonicalWindow() async throws {
        let directory = temporaryDirectory()
        defer { try? FileManager.default.removeItem(at: directory) }
        let api = FakeWatchChatAPI()
        let runtime = WatchChatRuntime(api: api, cache: WatchChatOfflineCache(directory: directory),
            crypto: FakeWatchChatCrypto(), syncSocket: nil)
        let chat = WatchChatSummary(id: "unknown-zero", title: nil, lastMessageAt: nil, preview: nil,
            isPinned: false, encryptedTitle: nil, encryptedPreview: nil, encryptedChatKey: "wrapped-chat-key")
        await runtime.openChat(chat)
        XCTAssertEqual(api.fetchMessageWindowCallCount, 1, "Zero versions alone do not establish local draft authority")
        runtime.stopRealtimeSync()
    }

    // contract-test: supporting surface=gui.apple assertions=apple-watch.chats.browse-search-open
    func testListRefreshPreservesSelectedChatAndReplacesVisibleMetadata() async {
        let directory = temporaryDirectory()
        defer { try? FileManager.default.removeItem(at: directory) }
        let api = FakeWatchChatAPI(chats: [Self.remoteChat(id: "selected", title: "Before", lastMessageAt: "1800000000")])
        let runtime = WatchChatRuntime(api: api, cache: WatchChatOfflineCache(directory: directory),
            crypto: FakeWatchChatCrypto(), syncSocket: nil)
        await runtime.refresh()
        runtime.selectedChatId = "selected"
        api.chats = [Self.remoteChat(id: "selected", title: "After", lastMessageAt: "1800000001")]
        await runtime.refresh()
        XCTAssertEqual(runtime.selectedChatId, "selected")
        XCTAssertEqual(runtime.chats.first?.title, "After")
        XCTAssertEqual(api.fetchRecentChatsCallCount, 2)
    }

    // contract-test: supporting surface=gui.apple assertions=apple-watch.chats.browse-search-open,apple-watch.offline.recent-cohort
    func testForegroundWindowsPageWithPairedTieCursorAndRetainFullEncryptedSnapshotAndPending() async throws {
        let directory = temporaryDirectory()
        defer { try? FileManager.default.removeItem(at: directory) }
        let cache = WatchChatOfflineCache(directory: directory)
        let chat = Self.chat(id: "window-chat", title: "Synthetic", lastMessageAt: "1800000001")
        let messages = (0..<120).map { index in
            WatchRemoteMessage(id: String(format: "message-%03d", index), chatId: chat.id, role: .assistant,
                content: nil, encryptedContent: "encrypted:Message \(index)", createdAt: "1800000000")
        }
        let pending = WatchChatMessage(id: "pending-local", chatId: chat.id, role: .user, content: nil,
            encryptedContent: "encrypted:Pending reply", createdAt: "1800000001", isPending: true)
        let stored = messages.map { WatchChatMessage(id: $0.id, chatId: $0.chatId, role: $0.role, content: nil,
            encryptedContent: $0.encryptedContent, createdAt: $0.createdAt, isPending: false) }
        try await cache.saveSnapshot(WatchChatSnapshot(chats: [chat], messagesByChatId: [chat.id: stored + [pending]], savedAt: .distantPast))
        let api = FakeWatchChatAPI(messagesByChatId: [chat.id: messages])
        let runtime = WatchChatRuntime(api: api, cache: cache, crypto: FakeWatchChatCrypto(), syncSocket: nil)
        await runtime.loadCachedSnapshot()
        await runtime.openChat(chat)
        XCTAssertEqual(api.fetchMessagesCallCount, 0, "Foreground does not fetch full-history REST")
        XCTAssertEqual(api.windowQueries.map(\.direction), [.latest])
        XCTAssertEqual(api.windowQueries.first?.limit, 20)
        XCTAssertEqual(runtime.selectedMessages.count, 21)
        XCTAssertEqual(runtime.selectedMessages.first?.id, "message-100")
        XCTAssertEqual(runtime.selectedMessages.last?.id, pending.id)
        XCTAssertTrue(runtime.selectedMessages.last?.isPending == true)
        XCTAssertTrue(runtime.hasMoreRemoteMessages)
        let firstPageSnapshot = await cache.loadSnapshot()
        XCTAssertEqual(firstPageSnapshot.messagesByChatId[chat.id]?.count, 121,
                       "A partial foreground page retains every older encrypted snapshot row")
        XCTAssertTrue(firstPageSnapshot.messagesByChatId[chat.id, default: []].contains { $0.id == "message-000" })
        XCTAssertEqual(runtime.chats.first?.messagesV, 0, "Viewing pages never advance full-content synchronization")
        await runtime.loadOlderMessages()
        XCTAssertEqual(api.windowQueries.last?.before, WatchMessageWindowCursor(createdAt: 1_800_000_000, messageId: "message-100"))
        XCTAssertEqual(runtime.selectedMessages.first?.id, "message-080")
        XCTAssertEqual(runtime.selectedMessages.count, 41)
        for _ in 0..<4 { await runtime.loadOlderMessages() }
        XCTAssertFalse(runtime.hasMoreRemoteMessages)
        XCTAssertEqual(runtime.selectedMessages.map(\.id), stored.map(\.id) + [pending.id])
        await runtime.refreshSelectedChat()
        XCTAssertEqual(api.windowQueries.last?.direction, .latest)
        XCTAssertEqual(runtime.selectedMessages.map(\.id), stored.map(\.id) + [pending.id],
                       "Foreground refresh updates IDs without dropping older pages or local pending messages")
        XCTAssertFalse(runtime.hasMoreRemoteMessages)
        let preserved = await cache.loadSnapshot()
        XCTAssertEqual(Set(preserved.messagesByChatId[chat.id, default: []].map(\.id)), Set(stored.map(\.id) + [pending.id]))
        XCTAssertTrue(preserved.messagesByChatId[chat.id, default: []].allSatisfy { $0.content == nil })
        let conversation = await cache.loadConversation(chatID: chat.id, accountID: nil, serverScope: WatchChatRuntime.currentServerScope)
        XCTAssertNil(conversation, "Partial viewing pages never mint a complete cohort receipt")
    }

    // contract-test: supporting surface=gui.apple assertions=storage.cold.independent-message-pages,storage.compression.incremental-archive
    func testWatchCoveredAndOversizedPagesValidateWithoutAdvancingCorruptCursor() throws {
        let query = WatchMessageWindowQuery(direction: .before, before: .init(createdAt: 100, messageId: "later"))
        XCTAssertFalse(query.respectCompressionBoundary)
        var page = WatchMessageWindow(chatId: "child", messages: [], hasMoreBefore: true, hasMoreAfter: true,
            respectCompressionBoundary: false, oversizedMessage: true, oversizedMessageCursor: .init(createdAt: 99, messageId: "large"), payloadBytes: 0)
        XCTAssertNoThrow(try page.validated(chatID: "child", query: query))
        page.oversizedMessageCursor = .init(createdAt: 100, messageId: "later")
        XCTAssertThrowsError(try page.validated(chatID: "child", query: query))
        page.oversizedMessageCursor = .init(createdAt: 99, messageId: "large")
        page.payloadBytes = 256 * 1024 + 1
        XCTAssertThrowsError(try page.validated(chatID: "child", query: query))
        XCTAssertThrowsError(try page.validated(chatID: "another-child", query: query))
    }

    // contract-test: supporting surface=gui.apple assertions=storage.cold.independent-message-pages,apple-watch.offline.recent-cohort
    func testWatchForegroundEvictionPreservesOfflineAuthorityPendingAndRefreshContinuation() async throws {
        let directory = temporaryDirectory()
        defer { try? FileManager.default.removeItem(at: directory) }
        let chat = Self.chat(id: "bounded-window", title: "Synthetic", lastMessageAt: "1800000001")
        let remote = (0..<300).map { index in
            WatchRemoteMessage(id: String(format: "bounded-%03d", index), chatId: chat.id, role: .assistant,
                content: nil, encryptedContent: "encrypted:Body \(index)", createdAt: "1800000000")
        }
        let stored = remote.map { WatchChatMessage(id: $0.id, chatId: $0.chatId, role: $0.role, content: nil,
            encryptedContent: $0.encryptedContent, createdAt: $0.createdAt, isPending: false) }
        let pending = WatchChatMessage(id: "pending", chatId: chat.id, role: .user, content: nil,
            encryptedContent: "encrypted:Unsent", createdAt: "1800000001", isPending: true)
        let cache = WatchChatOfflineCache(directory: directory)
        try await cache.saveSnapshot(WatchChatSnapshot(chats: [chat], messagesByChatId: [chat.id: stored + [pending]], savedAt: .distantPast))
        let api = FakeWatchChatAPI(messagesByChatId: [chat.id: remote])
        let runtime = WatchChatRuntime(api: api, cache: cache, crypto: FakeWatchChatCrypto(), syncSocket: nil)
        await runtime.loadCachedSnapshot()
        await runtime.openChat(chat)
        for _ in 0..<11 { await runtime.loadOlderMessages() }
        XCTAssertEqual(runtime.selectedMessages.filter { !$0.isPending }.count, 200)
        XCTAssertEqual(runtime.selectedMessages.first?.id, "bounded-060")
        XCTAssertEqual(runtime.selectedMessages.last?.id, pending.id)
        let offline = await cache.loadSnapshot()
        XCTAssertEqual(offline.messagesByChatId[chat.id]?.count, 301, "Eviction only releases foreground memory")
        await runtime.refreshSelectedChat()
        XCTAssertEqual(runtime.selectedMessages.first?.id, "bounded-280")
        XCTAssertEqual(runtime.selectedMessages.count, 21)
        XCTAssertTrue(runtime.hasMoreRemoteMessages)
        await runtime.loadOlderMessages()
        XCTAssertEqual(runtime.selectedMessages.first?.id, "bounded-260")
        XCTAssertEqual(Set(runtime.selectedMessages.map(\.id)).count, 41)
    }

    // contract-test: supporting surface=gui.apple assertions=storage.cold.independent-message-pages,storage.warm.bounded-chat-tail
    func testWatchByteEvictionKeepsPendingWithoutMutatingInput() {
        let ordinary = (0..<4).map { index in
            WatchChatMessage(id: "byte-\(index)", chatId: "child", role: .assistant, content: "body",
                encryptedContent: "cipher", createdAt: "1800000000", isPending: false)
        }
        let pending = WatchChatMessage(id: "pending", chatId: "child", role: .user, content: "Unsent",
            encryptedContent: "retained", createdAt: "1800000001", isPending: true)
        let source = ordinary + [pending]
        let result = WatchChatRuntime.retainedForeground(source, newest: false, maximumBytes: 20)
        XCTAssertEqual(result.map(\.id), ["byte-0", "byte-1", "pending"])
        XCTAssertEqual(result.last?.encryptedContent, "retained")
        XCTAssertEqual(source.count, 5)
    }

    // contract-test: supporting surface=gui.apple assertions=apple-watch.chats.browse-search-open
    func testLateForegroundWindowCannotPublishAfterSelectionOrLifecycleChange() async throws {
        for stopsRuntime in [false, true] {
            let directory = temporaryDirectory()
            defer { try? FileManager.default.removeItem(at: directory) }
            let gate = WatchChatFetchGate()
            let chat = Self.chat(id: "late-window", title: "Synthetic", lastMessageAt: "2026-07-06T10:00:00Z")
            let api = FakeWatchChatAPI(messagesByChatId: [chat.id: [Self.remoteMessage(id: "late-message", chatId: chat.id, content: "Late")]])
            api.windowFetchGate = gate
            let runtime = WatchChatRuntime(api: api, cache: WatchChatOfflineCache(directory: directory), crypto: FakeWatchChatCrypto(), syncSocket: nil)
            let opening = Task { await runtime.openChat(chat) }
            await gate.waitUntilStarted()
            if stopsRuntime { runtime.stopRealtimeSync() } else { runtime.selectedChatId = "another-chat" }
            await gate.release()
            await opening.value
            XCTAssertFalse(runtime.messagesByChatId[chat.id, default: []].contains { $0.id == "late-message" })
            XCTAssertFalse(runtime.hasMoreRemoteMessages)
        }
    }

    // contract-test: supporting surface=gui.apple assertions=apple-watch.chats.browse-search-open
    func testWindowQueryAndNumericEnvelopeKeepPairedCursorsAndCompressionMetadata() throws {
        let cursor = WatchMessageWindowCursor(createdAt: 1_800_000_000, messageId: "tie+id")
        let path = try WatchMessageWindowQuery(direction: .before, before: cursor).path(chatID: "synthetic")
        let query = try XCTUnwrap(URLComponents(string: path)?.queryItems)
        XCTAssertEqual(query.first { $0.name == "before_timestamp" }?.value, "1800000000")
        XCTAssertEqual(query.first { $0.name == "before_message_id" }?.value, "tie+id")
        XCTAssertThrowsError(try WatchMessageWindowQuery(direction: .before).path(chatID: "synthetic"))
        XCTAssertThrowsError(try WatchMessageWindowQuery(limit: 101).path(chatID: "synthetic"))
        let wire = Data(#"{"chat_id":"synthetic","messages":[{"id":"storage-row","message_id":"tie-a","chat_id":"synthetic","role":"assistant","encrypted_content":"cipher","created_at":1800000000}],"has_more_before":true,"has_more_after":false,"start_cursor":{"created_at":1800000000,"message_id":"tie-a"},"end_cursor":{"created_at":1800000000,"message_id":"tie-a"},"anchor_found":true,"messages_v":400,"server_message_count":400,"compression_boundary_timestamp":1799999000,"compression_checkpoints":[{"id":"checkpoint","chat_id":"synthetic","encrypted_summary":"summary-cipher","compressed_up_to_timestamp":1799999000,"compressed_message_count":350,"summary_token_estimate":10,"key_version":1}],"respect_compression_boundary":true}"#.utf8)
        let decoder = JSONDecoder(); decoder.keyDecodingStrategy = .convertFromSnakeCase
        let page = try decoder.decode(WatchMessageWindowEnvelope.self, from: wire).window
        XCTAssertEqual(page.messages.first?.createdAt, "1800000000")
        XCTAssertEqual(page.startCursor?.messageId, "tie-a")
        XCTAssertEqual(page.compressionCheckpoints.first?.encryptedSummary, "summary-cipher")
        XCTAssertEqual(page.messagesV, 400)
    }

    // contract-test: supporting surface=gui.apple assertions=apple-notifications.delivery.idempotent-visible
    func testWatchForegroundPresenceCoversHubAndClearsOnBackgroundThenReconnects() async {
        let socket = WatchNotificationTestSocket()
        let runtime = WatchChatRuntime(currentUserId: "account", api: FakeWatchChatAPI(),
            crypto: FakeWatchChatCrypto(), syncSocket: socket,
            syncSession: WatchSyncSession(sessionId: "session", token: "token"))
        await runtime.startRealtimeSync()
        await runtime.setForeground(true)
        XCTAssertTrue(socket.events.contains { $0.0 == "native_client_lifecycle"
            && $0.1["is_foreground"] as? Bool == true })
        XCTAssertNil(runtime.selectedChatId, "Hub presence must not require an open chat")

        await runtime.setForeground(false)
        XCTAssertEqual(socket.events.last(where: { $0.0 == "native_client_lifecycle" })?.1["is_foreground"] as? Bool, false)
        let backgroundCount = socket.events.count
        await runtime.foregroundHeartbeat()
        XCTAssertEqual(socket.events.count, backgroundCount)

        socket.dropConnection()
        await runtime.setForeground(true)
        await waitForWatchNotificationRequests { socket.events.filter {
            $0.0 == "native_client_lifecycle" && $0.1["is_foreground"] as? Bool == true
        }.count >= 2 }
        XCTAssertGreaterThanOrEqual(socket.connectCount, 2)
        runtime.stopRealtimeSync()
    }

    // contract-test: supporting surface=gui.apple assertions=apple-notifications.delivery.idempotent-visible
    func testWatchVisibleCommittedReceiptRetriesNegativeAckAndStopsAfterPositiveAck() async {
        let directory = temporaryDirectory()
        defer { try? FileManager.default.removeItem(at: directory) }
        let socket = WatchNotificationTestSocket(viewedResponses: [false, true])
        let chat = Self.chat(id: "chat-a", title: "Alpha", lastMessageAt: "2026-07-06T10:00:00Z")
        let runtime = WatchChatRuntime(currentUserId: "account",
            api: FakeWatchChatAPI(messagesByChatId: ["chat-a": [
                Self.remoteMessage(id: "message-a", chatId: "chat-a", content: "Fixture")
            ]]), cache: WatchChatOfflineCache(directory: directory), crypto: FakeWatchChatCrypto(),
            syncSocket: socket, syncSession: WatchSyncSession(sessionId: "session", token: "token"))
        await runtime.startRealtimeSync()
        await runtime.setForeground(true)
        await runtime.openChat(chat)
        runtime.setVisibleChatID(chat.id)
        runtime.updateVisibleMessages(["offscreen"], chatID: chat.id)
        XCTAssertTrue(socket.receiptRequests.isEmpty)
        runtime.updateVisibleMessages(["message-a"], chatID: chat.id)
        await waitForWatchNotificationRequests { socket.receiptRequests.count >= 1 }
        XCTAssertEqual(socket.receiptRequests.count, 1)
        XCTAssertEqual(socket.receiptRequests[0]["chat_id"] as? String, chat.id)
        XCTAssertEqual(socket.receiptRequests[0]["message_id"] as? String, "message-a")

        await runtime.setForeground(false)
        runtime.updateVisibleMessages(["message-a"], chatID: chat.id)
        XCTAssertEqual(socket.receiptRequests.count, 1, "Background viewing cannot send receipts")
        await runtime.setForeground(true)
        await waitForWatchNotificationRequests { socket.receiptRequests.count >= 2 }
        XCTAssertEqual(socket.receiptRequests.count, 2, "A negative ACK must retry after foreground return")
        await runtime.foregroundHeartbeat()
        XCTAssertEqual(socket.receiptRequests.count, 2, "A positive ACK must prevent further sends")
        runtime.stopRealtimeSync()
    }

    private func waitForWatchNotificationRequests(_ condition: () -> Bool) async {
        for _ in 0..<100 {
            if condition() { break }
            await Task.yield()
        }
        XCTAssertTrue(condition())
        for _ in 0..<4 { await Task.yield() }
    }

    // contract-test: supporting surface=gui.apple assertions=apple-notifications.action.routing-coherent
    func testNotificationJoinsInflightRefreshBeforeResolvingUncachedTarget() async throws {
        let directory = temporaryDirectory()
        defer { try? FileManager.default.removeItem(at: directory) }
        let gate = WatchChatFetchGate()
        let api = FakeWatchChatAPI(chats: [
            Self.remoteChat(id: "target", title: "Target", lastMessageAt: "2026-07-01T10:00:00Z"),
        ], chatFetchGate: gate)
        let runtime = WatchChatRuntime(api: api, cache: WatchChatOfflineCache(directory: directory),
                                       crypto: FakeWatchChatCrypto(), syncSocket: nil)
        let refresh = Task { await runtime.refresh() }
        await gate.waitUntilStarted()
        let open = Task { await runtime.openNotificationChat(chatID: "target") }
        await Task.yield()
        XCTAssertTrue(runtime.isSyncing)
        XCTAssertFalse(runtime.chatLoadFailed)
        XCTAssertNil(runtime.selectedChatId)
        await gate.release()
        let result = await open.value
        await refresh.value
        XCTAssertEqual(result, .opened)
        XCTAssertEqual(runtime.selectedChatId, "target")
        XCTAssertEqual(api.fetchRecentChatsCallCount, 1)
        XCTAssertEqual(api.fetchMessageWindowCallCount, 1)
    }

    // contract-test: supporting surface=gui.apple assertions=apple-notifications.action.routing-coherent
    func testNotificationTransientResolutionFailureRemainsRetryable() async throws {
        let directory = temporaryDirectory()
        defer { try? FileManager.default.removeItem(at: directory) }
        let api = FakeWatchChatAPI(chats: [
            Self.remoteChat(id: "target", title: "Target", lastMessageAt: "2026-07-01T10:00:00Z"),
        ], chatFetchError: APIError.httpError(status: 503, message: "fixture temporary outage"))
        let runtime = WatchChatRuntime(api: api, cache: WatchChatOfflineCache(directory: directory),
                                       crypto: FakeWatchChatCrypto(), syncSocket: nil)
        let failed = await runtime.openNotificationChat(chatID: "target")
        XCTAssertEqual(failed, .retry)
        XCTAssertNil(runtime.selectedChatId)
        api.chatFetchError = nil
        let retried = await runtime.openNotificationChat(chatID: "target")
        XCTAssertEqual(retried, .opened)
        XCTAssertEqual(runtime.selectedChatId, "target")
    }

    // contract-test: supporting surface=gui.apple assertions=apple-notifications.action.routing-coherent
    func testNotificationHydratesExactTargetAndMissingTargetNeverOpensAnotherChat() async throws {
        let directory = temporaryDirectory()
        defer { try? FileManager.default.removeItem(at: directory) }
        let api = FakeWatchChatAPI(chats: [
            Self.remoteChat(id: "latest", title: "Latest", lastMessageAt: "2026-07-05T10:00:00Z"),
            Self.remoteChat(id: "target", title: "Target", lastMessageAt: "2026-07-01T10:00:00Z"),
        ])
        let runtime = WatchChatRuntime(api: api, cache: WatchChatOfflineCache(directory: directory),
                                       crypto: FakeWatchChatCrypto(), syncSocket: nil)
        let opened = await runtime.openNotificationChat(chatID: "target")
        XCTAssertEqual(opened, .opened)
        XCTAssertEqual(runtime.selectedChatId, "target")
        XCTAssertEqual(api.fetchMessageWindowCallCount, 1)
        let missing = await runtime.openNotificationChat(chatID: "missing")
        XCTAssertEqual(missing, .unavailable)
        XCTAssertNil(runtime.selectedChatId)
        XCTAssertTrue(runtime.chatLoadFailed)
        XCTAssertEqual(api.fetchMessageWindowCallCount, 1)
        WatchChatAccountLifecycle.invalidate()
        let stale = await runtime.openNotificationChat(chatID: "latest")
        XCTAssertEqual(stale, .stale)
        XCTAssertNil(runtime.selectedChatId)
    }

    // contract-test: supporting surface=gui.apple assertions=apple-watch.chats.browse-search-open,apple-watch.chats.new-text-reply
    func testWatchInitialSyncIncludesRequiredPersonalContextEpoch() {
        let state = WatchSyncClientState(
            clientChatVersions: [:], clientChatIds: ["fixture-chat"],
            clientSuggestionsCount: 0, clientEmbedIds: []
        )
        let payload = state.phasedSyncPayload
        XCTAssertEqual(payload["context_epoch"] as? Int, 0)
        XCTAssertEqual(payload["phase"] as? String, "all")
        XCTAssertEqual(payload["client_chat_ids"] as? [String], ["fixture-chat"])
    }

    // contract-test: supporting surface=gui.apple assertions=apple-watch.chats.new-text-reply,apple-watch.chats.audio-reply
    func testWatchSocketReadinessWaitsForDelayedOpenAndStopsAfterClosure() async {
        var attempts = 0
        let opened = await WatchSocketReadiness.wait(maxAttempts: 6, interval: .milliseconds(1)) {
            attempts += 1
            return attempts == 4 ? .open : .retry
        }
        XCTAssertTrue(opened)
        XCTAssertEqual(attempts, 4)

        var closedAttempts = 0
        let closed = await WatchSocketReadiness.wait(maxAttempts: 6, interval: .milliseconds(1)) {
            closedAttempts += 1
            return .closed
        }
        XCTAssertFalse(closed)
        XCTAssertEqual(closedAttempts, 1)
    }

    // contract-test: supporting surface=gui.apple assertions=apple-watch.chats.new-text-reply,apple-watch.chats.audio-reply
    func testCancelledWatchSocketReadinessDoesNotProbeOrPublishReady() async {
        var probes = 0
        let attempt = Task { @MainActor in
            await WatchSocketReadiness.wait(maxAttempts: 6, interval: .milliseconds(1)) {
                probes += 1
                return .open
            }
        }
        attempt.cancel()
        let ready = await attempt.value
        XCTAssertFalse(ready)
        XCTAssertEqual(probes, 0)

        let gate = WatchChatFetchGate()
        let delayed = Task { @MainActor in
            await WatchSocketReadiness.wait(maxAttempts: 6, interval: .milliseconds(1)) {
                await gate.suspendFetch()
                return .open
            }
        }
        await gate.waitUntilStarted()
        delayed.cancel()
        await gate.release()
        let lateReady = await delayed.value
        XCTAssertFalse(lateReady, "A successful late probe cannot publish readiness after cancellation")
    }

    // contract-test: supporting surface=gui.apple assertions=apple-watch.chats.new-text-reply,apple-watch.chats.audio-reply
    func testWatchSocketTimeoutStagesPreserveStaticUserReasons() {
        XCTAssertEqual(WatchSocketTimeoutStage(requestType: "chat_turn_preflight", responseTypes: []), .preflight)
        XCTAssertEqual(WatchSocketTimeoutStage(requestType: "chat_message_added", responseTypes: []), .commit)
        XCTAssertEqual(WatchSocketTimeoutStage(requestType: "encrypted_chat_metadata", responseTypes: []), .storage)
        XCTAssertEqual(WatchSocketTimeoutStage(requestType: "", responseTypes: ["phased_sync_complete"]), .sync)
        XCTAssertEqual(WatchSocketTimeoutStage(requestType: "unknown-private-value", responseTypes: []), .response)
        let reasons = [WatchSocketTimeoutStage.connection, .sync, .preflight, .commit, .storage, .response]
            .map { WatchChatRuntimeError.socketTimedOut($0).localizedDescription }
        XCTAssertEqual(Set(reasons).count, 6)
        XCTAssertTrue(reasons.allSatisfy { !$0.contains("unknown-private-value") })
    }

    // contract-test: supporting surface=gui.apple assertions=apple-watch.chats.browse-search-open,apple-watch.pairing.private-session
    func testLivePersonalWatchSocketReadinessUsesVerifiedSessionWithoutInference() async throws {
        let env = ProcessInfo.processInfo.environment
        guard env["OPENMATES_TEST_WATCH_SOCKET_READ_ONLY"] == "1" else {
            throw XCTSkip("Real Watch socket validation is explicitly opt-in")
        }
        guard env["OPENMATES_TEST_PERSONAL_READ_ONLY"] == "1",
              let identityHash = env["OPENMATES_TEST_PERSONAL_IDENTITY_HASH"], identityHash.count == 64,
              let accountHash = env["OPENMATES_TEST_PERSONAL_ACCOUNT_HASH"], accountHash.count == 64,
              let email = env["OPENMATES_TEST_ACCOUNT_EMAIL"],
              Self.watchSocketIdentityHash(email.trimmingCharacters(in: .whitespacesAndNewlines).lowercased()) == identityHash,
              ServerProfile.current() == .development,
              let accountID = AuthManager.notificationAccountId,
              Self.watchSocketIdentityHash(accountID) == accountHash else {
            XCTFail("Opted-in Watch socket validation requires the approved recovered personal identity and exact development profile")
            return
        }
        let profile = ServerProfile.current()
        let context = WatchChatRequestContext(accountID: accountID, profile: profile,
            accountGeneration: WatchChatAccountLifecycle.generation, validate: {
                guard AuthManager.notificationAccountId == accountID else { throw CancellationError() }
            })
        // A fresh connection ID avoids replacing the main app's existing socket.
        // No login, default/session-ID mutation, message send, or recovery claim.
        let connectionID = UUID().uuidString
        let socket = WatchRealtimeSyncSocket()
        defer { socket.disconnect() }
        var stage = "session_restore"
        do {
            let restored = try await WatchSessionTransport.loadSession(
                body: SessionRequest(sessionId: connectionID, deviceInfo: WatchCompatibleSession.makeNativeDeviceInfo()),
                context: context)
            try context.check()
            guard restored.isAuthenticated, restored.user?.id == accountID,
                  let token = restored.wsToken, !token.isEmpty else {
                XCTFail("Verified Watch session did not restore the approved account and socket credential")
                return
            }
            stage = "socket_sync"
            socket.connect(session: WatchSyncSession(sessionId: connectionID, token: token),
                syncState: WatchSyncClientState(clientChatVersions: [:], clientChatIds: [],
                    clientSuggestionsCount: 0, clientEmbedIds: []))
            let response = try await socket.requestEvent(type: "", payload: [:],
                responseTypes: ["phased_sync_complete"], matching: {
                    ($0["context_epoch"] as? Int) == 0 && $0["phase"] as? String == "all"
                        && ($0["team_id"] == nil || $0["team_id"] is NSNull)
                })
            try context.check()
            XCTAssertTrue(socket.isConnected)
            XCTAssertEqual(response["context_epoch"] as? Int, 0)
            socket.disconnect()
            XCTAssertFalse(socket.isConnected)
            let receipt = XCTAttachment(string: "verified_personal=true;development=true;production_watch_socket=true;phased_sync_complete=true;disconnected=true;inference=false")
            receipt.name = "Watch real socket read-only readiness receipt"
            receipt.lifetime = .keepAlways
            add(receipt)
        } catch {
            // XCTest must never interpolate a transport URL, token, body or ID.
            let nsError = error as NSError
            let safeReason = (error as? WatchChatRuntimeError)?.localizedDescription ?? "transport_failure"
            XCTFail("Watch read-only readiness stage=\(stage) reason=\(safeReason) error_type=\(String(reflecting: type(of: error))) error_code=\(nsError.code)")
        }
    }

    private static func watchSocketIdentityHash(_ value: String) -> String {
        SHA256.hash(data: Data(value.utf8)).map { String(format: "%02x", $0) }.joined()
    }

    // contract-test: direct surface=gui.apple assertions=apple-watch.chats.browse-search-open
    func testNonemptyChatResponseDecodesMasterWrappersAndSelectsReplyKey() async throws {
        let chatId = "fixture-chat"
        let masterKey = SymmetricKey(size: .bits256)
        let chatKey = SymmetricKey(size: .bits256)
        let staleKey = SymmetricKey(size: .bits256)
        let selectedWrapper = try await CryptoManager.shared.wrapChatKey(chatKey, masterKey: masterKey)
        let staleWrapper = try await CryptoManager.shared.wrapChatKey(staleKey, masterKey: masterKey)
        let payload: [String: Any] = ["chats": [[
            "id": chatId, "encrypted_title": "ciphertext", "messages_v": 2,
            "encrypted_chat_key": staleWrapper,
            "chat_key_wrappers": [
                ["id": "older", "hashed_chat_id": WatchChatKeyWrapperRecord.hashedChatId(for: chatId),
                 "key_type": "master", "encrypted_chat_key": staleWrapper, "wrapper_version": 1,
                 "created_at": 1_777_777_777],
                ["id": "current", "hashed_chat_id": WatchChatKeyWrapperRecord.hashedChatId(for: chatId),
                 "key_type": "master", "encrypted_chat_key": selectedWrapper, "wrapper_version": 2,
                 "created_at": 1_777_777_778],
            ],
        ]]]
        let decoder = JSONDecoder()
        decoder.keyDecodingStrategy = .convertFromSnakeCase
        let response = try decoder.decode(WatchChatListEnvelope.self, from: JSONSerialization.data(withJSONObject: payload))
        let chat = try XCTUnwrap(response.chats.first.map(WatchRemoteChat.init(dto:)))

        XCTAssertEqual(response.chats.count, 1)
        XCTAssertEqual(chat.messagesV, 2)
        XCTAssertEqual(chat.chatKeyWrappers.count, 2)
        XCTAssertEqual(chat.chatKeyWrappers.map(\.createdAt), ["1777777777", "1777777778"])
        let resolution = await WatchChatKeyResolver.resolve(
            chatId: chat.id, wrappers: chat.chatKeyWrappers,
            encryptedChatKey: chat.encryptedChatKey, masterKey: masterKey
        )
        let resolved = try XCTUnwrap(resolution)
        XCTAssertEqual(resolved.wrapped, selectedWrapper)
        XCTAssertNil(resolved.outboundWrapped, "A stale row wrapper must disable replies rather than send a mismatched key")
        let selectedBytes = resolved.key.withUnsafeBytes { Data($0) }
        XCTAssertEqual(selectedBytes, chatKey.withUnsafeBytes { Data($0) })
    }

    // contract-test: direct surface=gui.apple assertions=apple-watch.chats.browse-search-open
    func testChatListWrapperTimestampAcceptsLegacyStringAndMissingValues() throws {
        let hash = WatchChatKeyWrapperRecord.hashedChatId(for: "fixture-chat")
        let payload: [String: Any] = ["chats": [[
            "id": "fixture-chat",
            "chat_key_wrappers": [
                ["hashed_chat_id": hash, "key_type": "master", "encrypted_chat_key": "wrapped-a",
                 "wrapper_version": 1, "created_at": "1777777777"],
                ["hashed_chat_id": hash, "key_type": "master", "encrypted_chat_key": "wrapped-b",
                 "wrapper_version": 2],
            ],
        ]]]
        let decoder = JSONDecoder()
        decoder.keyDecodingStrategy = .convertFromSnakeCase
        let response = try decoder.decode(WatchChatListEnvelope.self, from: JSONSerialization.data(withJSONObject: payload))

        XCTAssertEqual(response.chats.count, 1)
        XCTAssertEqual(response.chats[0].chatKeyWrappers.map(\.createdAt), ["1777777777", nil])
    }

    // contract-test: supporting surface=gui.apple assertions=apple-watch.chats.browse-search-open
    func testChatKeyResolverFallsBackToLegacyKeyWhenWrapperCannotUnwrap() async throws {
        let masterKey = SymmetricKey(size: .bits256)
        let legacyKey = SymmetricKey(size: .bits256)
        let legacyWrapper = try await CryptoManager.shared.wrapChatKey(legacyKey, masterKey: masterKey)
        let invalidWrapper = WatchChatKeyWrapperRecord(
            id: nil, hashedChatId: WatchChatKeyWrapperRecord.hashedChatId(for: "chat"),
            keyType: "master", encryptedChatKey: "invalid", wrapperVersion: 2, createdAt: nil
        )

        let resolution = await WatchChatKeyResolver.resolve(
            chatId: "chat", wrappers: [invalidWrapper], encryptedChatKey: legacyWrapper,
            masterKey: masterKey
        )
        let resolved = try XCTUnwrap(resolution)
        XCTAssertEqual(resolved.wrapped, legacyWrapper)
        XCTAssertEqual(resolved.outboundWrapped, legacyWrapper)
    }

    // contract-test: direct surface=gui.apple assertions=apple-watch.chats.new-text-reply
    func testChatKeyResolverPreservesExactRowWrapperForReplies() async throws {
        let masterKey = SymmetricKey(size: .bits256)
        let chatKey = SymmetricKey(size: .bits256)
        let rowWrapper = try await CryptoManager.shared.wrapChatKey(chatKey, masterKey: masterKey)
        let newerWrapper = try await CryptoManager.shared.wrapChatKey(chatKey, masterKey: masterKey)
        let wrapper = WatchChatKeyWrapperRecord(
            id: "newer", hashedChatId: WatchChatKeyWrapperRecord.hashedChatId(for: "chat"),
            keyType: "master", encryptedChatKey: newerWrapper, wrapperVersion: 2, createdAt: nil
        )

        let resolution = await WatchChatKeyResolver.resolve(
            chatId: "chat", wrappers: [wrapper], encryptedChatKey: rowWrapper,
            masterKey: masterKey
        )
        let resolved = try XCTUnwrap(resolution)
        XCTAssertEqual(resolved.wrapped, newerWrapper)
        XCTAssertEqual(resolved.outboundWrapped, rowWrapper)
    }

    // contract-test: supporting surface=gui.apple assertions=apple-watch.chats.browse-search-open
    func testLiveReservedAccountLoginLoadsAndOpensWatchChat() async throws {
        let credentials = try WatchLiveAccountCredentials.fromEnvironment(preferredReservedSlot: 14)
        ServerConfiguration.current = ServerProfile.development.endpointConfiguration

        let authManager = AuthManager()
        let lookup = try await authManager.lookup(email: credentials.email, stayLoggedIn: true)
        do {
            try await authManager.loginWithPassword(
                email: credentials.email,
                password: credentials.password,
                userEmailSalt: lookup.userEmailSalt,
                stayLoggedIn: true
            )
        } catch AuthError.tfaRequired {
            var lastOTPError: Error?
            for offset in [0, -1, 1, 0, -1] {
                WatchLiveTOTP.waitPastBoundaryIfNeeded()
                do {
                    try await authManager.loginWithPassword(
                        email: credentials.email,
                        password: credentials.password,
                        userEmailSalt: lookup.userEmailSalt,
                        tfaCode: WatchLiveTOTP.generate(secret: credentials.otpKey, windowOffset: offset),
                        codeType: "otp",
                        stayLoggedIn: true
                    )
                    lastOTPError = nil
                    break
                } catch AuthError.invalidTwoFactorCode {
                    lastOTPError = AuthError.invalidTwoFactorCode
                    try await Task.sleep(nanoseconds: 3_000_000_000)
                }
            }
            if let lastOTPError {
                throw lastOTPError
            }
        }

        XCTAssertEqual(authManager.state, .authenticated)
        let loggedInUser = try XCTUnwrap(authManager.currentUser)
        let masterKey = try await CryptoManager.shared.loadMasterKey(for: loggedInUser.id)
        XCTAssertNotNil(masterKey)

        let watchSession: SessionResponse = try await APIClient.shared.request(
            .post,
            path: "/v1/auth/session",
            body: SessionRequest(
                sessionId: WatchCompatibleSession.nativeSessionId,
                deviceInfo: WatchCompatibleSession.makeNativeDeviceInfo()
            )
        )
        XCTAssertTrue(watchSession.isAuthenticated)
        XCTAssertEqual(watchSession.user?.id, loggedInUser.id)

        let runtime = WatchChatRuntime(
            currentUserId: loggedInUser.id,
            syncSocket: nil,
            syncSession: nil
        )
        await runtime.refresh()

        XCTAssertFalse(runtime.isOffline, runtime.errorMessage ?? "Watch chat refresh unexpectedly went offline")
        XCTAssertFalse(runtime.chats.isEmpty, "Real Apple test account must keep at least one decryptable saved chat for Watch smoke coverage")

        var openedMessageCount = 0
        for chat in runtime.chats.prefix(5) {
            await runtime.openChat(chat)
            XCTAssertEqual(runtime.selectedChatId, chat.id)
            if !runtime.selectedMessages.isEmpty {
                openedMessageCount = runtime.selectedMessages.count
                break
            }
        }

        XCTAssertGreaterThan(openedMessageCount, 0, "Opening a Watch chat must load at least one message from the real account")
        XCTAssertFalse(runtime.isOffline, runtime.errorMessage ?? "Watch chat open unexpectedly went offline")
    }

    // contract-test: supporting surface=gui.apple assertions=apple-watch.chats.browse-search-open
    func testWatchCryptoCanOmitHiddenChatCandidates() async throws {
        let directory = temporaryDirectory()
        defer { try? FileManager.default.removeItem(at: directory) }
        let cache = WatchChatOfflineCache(directory: directory)
        var visible = Self.remoteChat(id: "visible", title: nil,
            lastMessageAt: "2026-07-06T10:00:00Z", encryptedTitle: "encrypted:Visible")
        visible.lastEditedOverallTimestamp = "2026-07-06T12:00:00Z"
        let hidden = Self.remoteChat(id: "hidden", title: "Hidden fallback must not appear",
            lastMessageAt: "2026-07-06T11:00:00Z", encryptedTitle: "unavailable-ciphertext")
        let crypto: any WatchChatCrypto = FakeWatchChatCrypto(omittedChatIds: [hidden.id])
        let hiddenCandidate = await crypto.decryptChat(hidden)
        XCTAssertNil(hiddenCandidate, "An unavailable key must permit omitting the whole candidate, including its fallback title")
        let runtime = WatchChatRuntime(api: FakeWatchChatAPI(chats: [hidden, visible]),
            cache: cache, crypto: crypto, syncSocket: nil)

        await runtime.refresh()

        XCTAssertEqual(runtime.chats.map(\.id), [visible.id])
        XCTAssertEqual(runtime.chats.first?.title, "Visible")
        XCTAssertEqual(runtime.chats.first?.lastEditedOverallTimestamp, visible.lastEditedOverallTimestamp)
        XCTAssertEqual(runtime.unavailableChatCount, 1)
        XCTAssertFalse(runtime.isOffline)
        let snapshot = await cache.loadSnapshot()
        XCTAssertEqual(snapshot.chats.map(\.id), [visible.id], "An omitted encrypted candidate must not enter the persisted chat list")
        XCTAssertEqual(snapshot.chats.first?.encryptedTitle, visible.encryptedTitle)
        XCTAssertNil(snapshot.messagesByChatId[hidden.id])
    }

    // contract-test: supporting surface=gui.apple assertions=apple-watch.chats.browse-search-open
    func testOfflineCacheRoundTripsSnapshot() async throws {
        let directory = temporaryDirectory()
        defer { try? FileManager.default.removeItem(at: directory) }
        let cache = WatchChatOfflineCache(directory: directory)
        let snapshot = WatchChatSnapshot(
            chats: [Self.chat(id: "chat-a", title: "Alpha", lastMessageAt: "2026-07-06T10:00:00Z")],
            messagesByChatId: ["chat-a": [Self.message(id: "msg-a", chatId: "chat-a", content: "Cached")]],
            pendingTextSends: [],
            savedAt: Date(timeIntervalSince1970: 1_783_337_600)
        )

        try await cache.saveSnapshot(snapshot)
        let loaded = await cache.loadSnapshot()

        XCTAssertEqual(loaded, snapshot)
    }

    // contract-test: direct surface=gui.apple assertions=apple-watch.chats.browse-search-open
    func testRefreshFetchesChatsAndPersistsSortedSnapshot() async throws {
        let directory = temporaryDirectory()
        defer { try? FileManager.default.removeItem(at: directory) }
        let cache = WatchChatOfflineCache(directory: directory)
        let api = FakeWatchChatAPI(
            chats: [
                Self.remoteChat(id: "older", title: "Older", lastMessageAt: "2026-07-05T10:00:00Z"),
                Self.remoteChat(id: "pinned", title: "Pinned", lastMessageAt: "2026-07-01T10:00:00Z", isPinned: true),
            ]
        )
        let runtime = WatchChatRuntime(api: api, cache: cache, crypto: FakeWatchChatCrypto())

        await runtime.refresh()

        XCTAssertEqual(runtime.chats.map(\.id), ["pinned", "older"])
        XCTAssertNil(runtime.selectedChatId, "Chat list should remain visible until a chat is opened")
        let cached = await cache.loadSnapshot()
        XCTAssertEqual(cached.chats.map(\.id), ["pinned", "older"])
    }

    // contract-test: direct surface=gui.apple assertions=apple-watch.chats.browse-search-open
    func testRefreshKeepsChatsBeyondFormerTwentyItemLimitForSearch() async throws {
        let directory = temporaryDirectory()
        defer { try? FileManager.default.removeItem(at: directory) }
        let api = FakeWatchChatAPI(chats: (1...26).map { index in
            Self.remoteChat(id: "chat-\(index)", title: "Chat \(index)",
                            lastMessageAt: String(format: "2026-07-%02dT10:00:00Z", index))
        })
        let runtime = WatchChatRuntime(api: api, cache: WatchChatOfflineCache(directory: directory),
                                       crypto: FakeWatchChatCrypto())
        await runtime.refresh()
        XCTAssertEqual(api.lastRequestedChatLimit, 100)
        XCTAssertEqual(runtime.chats.count, 26)
        XCTAssertEqual(runtime.chats.filter { $0.title?.localizedCaseInsensitiveContains("Chat 26") == true }.map(\.id), ["chat-26"])
    }

    // contract-test: direct surface=gui.apple assertions=apple-watch.chats.browse-search-open
    func testRefreshPagesOlderChatsForSearch() async throws {
        let directory = temporaryDirectory()
        defer { try? FileManager.default.removeItem(at: directory) }
        let api = FakeWatchChatAPI(chats: (1...126).map { index in
            Self.remoteChat(id: "chat-\(index)", title: "Chat \(index)",
                            lastMessageAt: "2026-07-01T10:00:00Z")
        })
        let runtime = WatchChatRuntime(api: api, cache: WatchChatOfflineCache(directory: directory),
                                       crypto: FakeWatchChatCrypto())

        await runtime.refresh()

        XCTAssertEqual(api.requestedChatOffsets, [0, 20, 120])
        XCTAssertEqual(runtime.chats.count, 126)
        XCTAssertEqual(runtime.chats.filter { $0.title == "Chat 126" }.map(\.id), ["chat-126"])
    }

    // contract-test: direct surface=gui.apple assertions=apple-watch.chats.browse-search-open
    func testRefreshStopsWhenServerRepeatsPageAndKeepsFirstHundredChats() async throws {
        let directory = temporaryDirectory()
        defer { try? FileManager.default.removeItem(at: directory) }
        let api = FakeWatchChatAPI(chats: (1...126).map { index in
            Self.remoteChat(id: "chat-\(index)", title: "Chat \(index)", lastMessageAt: "2026-07-01T10:00:00Z")
        }, ignoresChatOffset: true)
        let runtime = WatchChatRuntime(api: api, cache: WatchChatOfflineCache(directory: directory),
                                       crypto: FakeWatchChatCrypto())

        await runtime.refresh()

        XCTAssertEqual(api.requestedChatOffsets, [0, 20, 120])
        XCTAssertEqual(runtime.chats.count, 100)
        XCTAssertFalse(runtime.isOffline)
    }

    // contract-test: direct surface=gui.apple assertions=apple-watch.chats.browse-search-open
    func testRefreshFallsBackToSmallPagesWhenLargePageFails() async throws {
        let directory = temporaryDirectory()
        defer { try? FileManager.default.removeItem(at: directory) }
        let api = FakeWatchChatAPI(chats: (1...26).map { index in
            Self.remoteChat(id: "chat-\(index)", title: "Chat \(index)", lastMessageAt: "2026-07-01T10:00:00Z")
        }, maxAcceptedChatLimit: 20)
        let runtime = WatchChatRuntime(api: api, cache: WatchChatOfflineCache(directory: directory),
                                       crypto: FakeWatchChatCrypto())

        await runtime.refresh()

        XCTAssertEqual(api.requestedChatOffsets, [0, 20, 20])
        XCTAssertEqual(runtime.chats.count, 26)
        XCTAssertFalse(runtime.isOffline)
        XCTAssertFalse(runtime.chatLoadFailed)
    }

    // contract-test: supporting surface=gui.apple assertions=apple-watch.chats.browse-search-open
    func testRefreshRetainsCachedOlderChatWithUnsentTurn() async throws {
        let directory = temporaryDirectory()
        defer { try? FileManager.default.removeItem(at: directory) }
        let cache = WatchChatOfflineCache(directory: directory)
        let older = Self.chat(id: "older-pending", title: "Older pending", lastMessageAt: "2026-06-01T10:00:00Z")
        try await cache.saveSnapshot(WatchChatSnapshot(
            chats: [older], messagesByChatId: [older.id: []],
            pendingTextSends: [WatchPendingTextSend(
                id: "turn", chatId: older.id, messageId: "message", encryptedContent: "encrypted",
                encryptedChatKey: "wrapped-chat-key", createdAt: "2026-06-01T10:00:00Z"
            )], savedAt: Date()
        ))
        let runtime = WatchChatRuntime(
            api: FakeWatchChatAPI(chats: [Self.remoteChat(id: "newer", title: "Newer", lastMessageAt: "2026-07-01T10:00:00Z")]),
            cache: cache, crypto: FakeWatchChatCrypto()
        )
        await runtime.refresh()
        XCTAssertEqual(Set(runtime.chats.map(\.id)), Set(["newer", "older-pending"]))
    }

    // contract-test: supporting surface=gui.apple assertions=apple-watch.chats.browse-search-open
    func testRefreshRetriesTransientNetworkLoss() async throws {
        let directory = temporaryDirectory()
        defer { try? FileManager.default.removeItem(at: directory) }
        let api = FakeWatchChatAPI(
            chats: [Self.remoteChat(id: "chat-a", title: "Alpha", lastMessageAt: "2026-07-06T10:00:00Z")],
            transientChatFetchFailures: 1
        )
        let runtime = WatchChatRuntime(
            api: api,
            cache: WatchChatOfflineCache(directory: directory),
            crypto: FakeWatchChatCrypto()
        )

        await runtime.refresh()

        XCTAssertFalse(runtime.isOffline)
        XCTAssertEqual(runtime.chats.map(\.id), ["chat-a"])
        XCTAssertEqual(api.fetchRecentChatsCallCount, 2)
    }

    // contract-test: direct surface=gui.apple assertions=apple-watch.chats.browse-search-open
    func testRefreshExcludesChatsThatNormalMasterKeyCannotDecrypt() async throws {
        let directory = temporaryDirectory()
        defer { try? FileManager.default.removeItem(at: directory) }
        let runtime = WatchChatRuntime(
            api: FakeWatchChatAPI(chats: [
                Self.remoteChat(id: "visible", title: "Visible", lastMessageAt: "2026-07-06T10:00:00Z"),
                Self.remoteChat(id: "hidden", title: nil, lastMessageAt: "2026-07-06T11:00:00Z"),
            ]),
            cache: WatchChatOfflineCache(directory: directory),
            crypto: FakeWatchChatCrypto(omittedChatIds: ["hidden"])
        )

        await runtime.refresh()

        XCTAssertEqual(runtime.chats.map(\.id), ["visible"])
        XCTAssertEqual(runtime.unavailableChatCount, 1)
    }

    // contract-test: direct surface=gui.apple assertions=apple-watch.chats.browse-search-open
    func testRefreshFallsBackToCachedChatsWhenAPIThrows() async throws {
        let directory = temporaryDirectory()
        defer { try? FileManager.default.removeItem(at: directory) }
        let cache = WatchChatOfflineCache(directory: directory)
        try await cache.saveSnapshot(
            WatchChatSnapshot(
                chats: [Self.chat(id: "cached", title: "Cached", lastMessageAt: "2026-07-06T10:00:00Z")],
                messagesByChatId: [:],
                pendingTextSends: [],
                savedAt: Date()
            )
        )
        let runtime = WatchChatRuntime(api: FakeWatchChatAPI(shouldThrow: true), cache: cache, crypto: FakeWatchChatCrypto())

        await runtime.refresh()

        XCTAssertTrue(runtime.isOffline)
        XCTAssertEqual(runtime.chats.map(\.id), ["cached"])
    }

    // contract-test: direct surface=gui.apple assertions=apple-watch.chats.browse-search-open
    func testChatHTTPFailureDoesNotClaimDeviceIsOffline() async throws {
        let directory = temporaryDirectory()
        defer { try? FileManager.default.removeItem(at: directory) }
        let runtime = WatchChatRuntime(
            api: FakeWatchChatAPI(chatFetchError: APIError.httpError(status: 503, message: "Unavailable")),
            cache: WatchChatOfflineCache(directory: directory), crypto: FakeWatchChatCrypto()
        )

        await runtime.refresh()

        XCTAssertFalse(runtime.isOffline)
        XCTAssertTrue(runtime.chatLoadFailed)
    }

    // contract-test: direct surface=gui.apple assertions=apple-watch.chats.new-text-reply
    func testFailedPreflightKeepsExactEncryptedTurnForRetry() async throws {
        let directory = temporaryDirectory()
        defer { try? FileManager.default.removeItem(at: directory) }
        let cache = WatchChatOfflineCache(directory: directory)
        let chat = Self.chat(id: "chat-a", title: "Alpha", lastMessageAt: "2026-07-06T10:00:00Z")
        let socket = FakeWatchChatSyncSocket(shouldRejectSend: true, rejectionCode: "version_conflict")
        let runtime = WatchChatRuntime(
            api: FakeWatchChatAPI(
                chats: [Self.remoteChat(id: "chat-a", title: "Alpha", lastMessageAt: "2026-07-06T10:00:00Z")],
                messagesByChatId: ["chat-a": []]
            ),
            cache: cache, crypto: FakeWatchChatCrypto(), syncSocket: socket,
            syncSession: WatchSyncSession(sessionId: "session", token: "token")
        )
        await runtime.refresh()
        await runtime.openChat(chat)
        await runtime.sendText("  Pending reply  ")
        XCTAssertEqual(runtime.selectedMessages.last?.content, "Pending reply")
        XCTAssertEqual(runtime.selectedMessages.last?.isPending, true)
        let snapshot = await cache.loadSnapshot()
        let saved = try XCTUnwrap(snapshot.pendingTextSends.first)
        XCTAssertTrue(saved.preflightJSON.isEmpty)
        XCTAssertTrue(saved.inferenceJSON.isEmpty)
        let encryptedPrepared = try XCTUnwrap(saved.encryptedPreparedTurn)
        let plaintext = try await FakeWatchChatCrypto().decryptText(encryptedPrepared, for: chat)
        let prepared = try XCTUnwrap(JSONSerialization.jsonObject(with: Data(plaintext.utf8)) as? [String: Any])
        let preflight = try XCTUnwrap(prepared["preflight"] as? [String: Any])
        let inference = try XCTUnwrap(prepared["inference"] as? [String: Any])
        XCTAssertEqual(preflight["turn_id"] as? String, saved.id)
        XCTAssertEqual(preflight["expected_messages_v"] as? Int, 0)
        XCTAssertEqual((preflight["encrypted_user_message"] as? [String: Any])?["encrypted_content"] as? String, "encrypted:Pending reply")
        XCTAssertEqual((inference["message"] as? [String: Any])?["content"] as? String, "Pending reply")
        XCTAssertNil(preflight["encrypted_chat_metadata"], "Existing titled chats do not resend initial metadata")
        let anotherSend = await runtime.sendText("Blocked new text")
        XCTAssertFalse(anotherSend)
        let afterRejectedReplay = await cache.loadSnapshot()
        XCTAssertEqual(afterRejectedReplay.pendingTextSends, [saved], "Admission diagnostics cannot change the persisted encrypted turn")
        XCTAssertEqual(socket.attemptedTurns.map(\.id), [saved.id, saved.id])
        XCTAssertTrue(socket.sentTurns.isEmpty)
    }

    // contract-test: supporting surface=gui.apple assertions=apple-watch.chats.new-text-reply,apple-watch.chats.audio-reply
    func testSocketTimeoutKeepsExactEncryptedTurnAndRetriesWithoutNewIdentity() async throws {
        let directory = temporaryDirectory()
        defer { try? FileManager.default.removeItem(at: directory) }
        let cache = WatchChatOfflineCache(directory: directory)
        let chat = Self.chat(id: "timeout-chat", title: "Synthetic", lastMessageAt: "2026-07-06T10:00:00Z")
        let socket = FakeWatchChatSyncSocket()
        socket.sendFailure = .socketTimedOut(.preflight)
        let api = FakeWatchChatAPI(chats: [Self.remoteChat(id: chat.id,
            title: "Synthetic", lastMessageAt: "2026-07-06T10:00:00Z")])
        let runtime = WatchChatRuntime(api: api, cache: cache,
            crypto: FakeWatchChatCrypto(), syncSocket: socket,
            syncSession: WatchSyncSession(sessionId: "synthetic-session", token: "synthetic-token"))
        await runtime.refresh()
        await runtime.openChat(chat)
        XCTAssertEqual(runtime.selectedChatId, chat.id)
        XCTAssertEqual(runtime.chats.map(\.id), [chat.id], "Sending requires a selected chat in the authorized inventory")
        let queued = await runtime.sendText("Public retry fixture")
        XCTAssertTrue(queued)
        XCTAssertEqual(runtime.errorMessage, WatchChatRuntimeError.socketTimedOut(.preflight).localizedDescription)
        let saved = await cache.loadSnapshot()
        let original = try XCTUnwrap(saved.pendingTextSends.first)
        XCTAssertNotNil(original.encryptedPreparedTurn)
        XCTAssertTrue(original.preflightJSON.isEmpty)
        XCTAssertTrue(original.inferenceJSON.isEmpty)
        XCTAssertTrue(runtime.selectedMessages.last?.isPending == true)
        let blockedNewTurn = await runtime.sendText("Blocked new synthetic text")
        XCTAssertFalse(blockedNewTurn)
        XCTAssertEqual(runtime.errorMessage, WatchChatRuntimeError.socketTimedOut(.preflight).localizedDescription)
        let retained = await cache.loadSnapshot()
        XCTAssertEqual(retained.pendingTextSends, [original])
        socket.sendFailure = nil
        await runtime.refresh()
        let retried = try XCTUnwrap(socket.sentTurns.first)
        XCTAssertEqual(retried.id, original.id)
        XCTAssertEqual(retried.messageId, original.messageId)
        XCTAssertEqual(retried.encryptedContent, original.encryptedContent)
        XCTAssertEqual(retried.encryptedPreparedTurn, original.encryptedPreparedTurn)
        let completed = await cache.loadSnapshot()
        XCTAssertTrue(completed.pendingTextSends.isEmpty)
        XCTAssertFalse(runtime.selectedMessages.contains { $0.id == original.messageId && $0.isPending })
    }

    // contract-test: direct surface=gui.apple assertions=apple-watch.chats.new-text-reply
    func testNextSendRetriesPersistedTurnBeforeSendingNewText() async throws {
        let directory = temporaryDirectory()
        defer { try? FileManager.default.removeItem(at: directory) }
        let cache = WatchChatOfflineCache(directory: directory)
        let chat = Self.chat(id: "chat-a", title: "Alpha", lastMessageAt: "2026-07-06T10:00:00Z")
        let socket = FakeWatchChatSyncSocket(shouldRejectSend: true, rejectionCode: "preflight_mismatch")
        let runtime = WatchChatRuntime(
            api: FakeWatchChatAPI(chats: [Self.remoteChat(id: chat.id, title: "Alpha", lastMessageAt: "2026-07-06T10:00:00Z")]),
            cache: cache, crypto: FakeWatchChatCrypto(), syncSocket: socket,
            syncSession: WatchSyncSession(sessionId: "session", token: "token")
        )
        await runtime.refresh()
        await runtime.openChat(chat)
        let firstQueued = await runtime.sendText("First")
        let queued = await cache.loadSnapshot()
        let original = try XCTUnwrap(queued.pendingTextSends.first)
        let blockedNewSend = await runtime.sendText("Second")
        XCTAssertTrue(firstQueued)
        XCTAssertFalse(blockedNewSend)
        XCTAssertNotEqual(runtime.errorMessage, WatchChatRuntimeError.sendInProgress.localizedDescription)
        let stillQueued = await cache.loadSnapshot()
        XCTAssertEqual(stillQueued.pendingTextSends, [original])
        XCTAssertEqual(socket.attemptedTurns.map(\.id), [original.id, original.id])

        socket.shouldRejectSend = false
        let secondSent = await runtime.sendText("Second")
        XCTAssertTrue(secondSent)
        XCTAssertEqual(socket.sentTurns.count, 2)
        XCTAssertEqual(socket.sentTurns[0].id, original.id)
        XCTAssertEqual(socket.sentTurns[0].encryptedContent, original.encryptedContent)
        XCTAssertNotEqual(socket.sentTurns[1].id, original.id)
        XCTAssertEqual(socket.sentTurns[1].encryptedContent, "encrypted:Second")
        let saved = await cache.loadSnapshot()
        XCTAssertTrue(saved.pendingTextSends.isEmpty)
        XCTAssertEqual(runtime.selectedMessages.filter(\.isPending).count, 0)
    }

    // contract-test: direct surface=gui.apple assertions=apple-watch.chats.new-text-reply
    func testFirstNewChatTurnIncludesEncryptedInitialMetadata() async throws {
        let directory = temporaryDirectory()
        defer { try? FileManager.default.removeItem(at: directory) }
        let socket = FakeWatchChatSyncSocket()
        let runtime = WatchChatRuntime(
            api: FakeWatchChatAPI(), cache: WatchChatOfflineCache(directory: directory),
            crypto: FakeWatchChatCrypto(), syncSocket: socket,
            syncSession: WatchSyncSession(sessionId: "session", token: "token")
        )
        await runtime.createNewChat()
        await runtime.sendText("First message")
        let turn = try XCTUnwrap(socket.sentTurns.first)
        let preflight = try XCTUnwrap(JSONSerialization.jsonObject(with: turn.preflightJSON) as? [String: Any])
        let metadata = try XCTUnwrap(preflight["encrypted_chat_metadata"] as? [String: Any])
        XCTAssertEqual(metadata["encrypted_title"] as? String, "encrypted:")
        XCTAssertEqual(preflight["expected_messages_v"] as? Int, 0)
        XCTAssertEqual(preflight["encrypted_chat_key"] as? String, "wrapped-new-key")
    }

    // contract-test: supporting surface=gui.apple assertions=apple-watch.chats.browse-search-open
    func testOpenChatRetriesTransientNetworkLoss() async throws {
        let directory = temporaryDirectory()
        defer { try? FileManager.default.removeItem(at: directory) }
        let chat = Self.chat(id: "chat-a", title: "Alpha", lastMessageAt: "2026-07-06T10:00:00Z")
        let api = FakeWatchChatAPI(
            messagesByChatId: ["chat-a": [Self.remoteMessage(id: "msg-a", chatId: "chat-a", content: "Remote")]],
            transientMessageFetchFailures: 1
        )
        let runtime = WatchChatRuntime(
            api: api,
            cache: WatchChatOfflineCache(directory: directory),
            crypto: FakeWatchChatCrypto()
        )

        await runtime.openChat(chat)

        XCTAssertFalse(runtime.isOffline)
        XCTAssertEqual(runtime.selectedMessages.map(\.content), ["Remote"])
        XCTAssertEqual(api.fetchMessageWindowCallCount, 2)
    }

    // contract-test: direct surface=gui.apple assertions=apple-watch.chats.new-text-reply
    func testTextSendUsesPreflightAndInferenceSocket() async throws {
        let directory = temporaryDirectory()
        defer { try? FileManager.default.removeItem(at: directory) }
        let cache = WatchChatOfflineCache(directory: directory)
        let socket = FakeWatchChatSyncSocket()
        let chat = Self.chat(id: "chat-a", title: "Alpha", lastMessageAt: "2026-07-06T10:00:00Z")
        let runtime = WatchChatRuntime(
            api: FakeWatchChatAPI(
                chats: [Self.remoteChat(id: "chat-a", title: "Alpha", lastMessageAt: "2026-07-06T10:00:00Z")],
                messagesByChatId: ["chat-a": []]
            ),
            cache: cache, crypto: FakeWatchChatCrypto(), syncSocket: socket,
            syncSession: WatchSyncSession(sessionId: "session", token: "token")
        )
        await runtime.refresh()
        await runtime.openChat(chat)
        await runtime.sendText("Reply")
        XCTAssertEqual(socket.sentTurns.count, 1)
        XCTAssertEqual(runtime.selectedMessages.last?.isPending, false)
        let snapshot = await cache.loadSnapshot()
        XCTAssertTrue(snapshot.pendingTextSends.isEmpty)
    }

    // contract-test: direct surface=gui.apple assertions=apple-watch.chats.new-text-reply
    func testCreateNewChatSelectsTransientComposerWithoutSavingEmptyChat() async throws {
        let directory = temporaryDirectory()
        defer { try? FileManager.default.removeItem(at: directory) }
        let runtime = WatchChatRuntime(
            api: FakeWatchChatAPI(), cache: WatchChatOfflineCache(directory: directory),
            crypto: FakeWatchChatCrypto()
        )
        await runtime.refresh()
        XCTAssertNil(runtime.selectedChatId)
        await runtime.createNewChat()
        XCTAssertTrue(runtime.chats.isEmpty)
        XCTAssertEqual(runtime.selectedChat?.id, "new-chat")
        XCTAssertEqual(runtime.selectedChatId, "new-chat")
        XCTAssertTrue(runtime.selectedMessages.isEmpty)
    }

    // contract-test: direct surface=gui.apple assertions=apple-watch.chats.browse-search-open
    func testEncryptedRemoteFieldsAreDecryptedBeforeDisplay() async throws {
        let directory = temporaryDirectory()
        defer { try? FileManager.default.removeItem(at: directory) }
        let cache = WatchChatOfflineCache(directory: directory)
        let api = FakeWatchChatAPI(
            chats: [
                Self.remoteChat(
                    id: "chat-a",
                    title: nil,
                    lastMessageAt: "2026-07-06T10:00:00Z",
                    encryptedTitle: "enc-title",
                    encryptedSummary: "enc-summary"
                )
            ],
            messagesByChatId: [
                "chat-a": [Self.remoteMessage(id: "msg-a", chatId: "chat-a", content: nil, encryptedContent: "enc-message")]
            ]
        )
        let crypto = FakeWatchChatCrypto(decryptedValues: [
            "enc-title": "Decrypted title",
            "enc-summary": "Decrypted summary",
            "enc-message": "Decrypted message",
        ])
        let runtime = WatchChatRuntime(api: api, cache: cache, crypto: crypto)

        await runtime.refresh()
        guard let chat = runtime.chats.first else {
            XCTFail("Expected decrypted chat")
            return
        }
        await runtime.openChat(chat)

        XCTAssertEqual(runtime.chats.first?.title, "Decrypted title")
        XCTAssertEqual(runtime.chats.first?.preview, "Decrypted summary")
        XCTAssertEqual(runtime.selectedMessages.first?.content, "Decrypted message")
        XCTAssertEqual(api.fetchMessageWindowCallCount, 1, "An omitted message version must not suppress transcript fetching")
    }

    // contract-test: supporting surface=gui.apple assertions=apple-watch.chats.compact-layout
    func testOpenChatPreservesEmbedRefsForWatchPreviews() async throws {
        let directory = temporaryDirectory()
        defer { try? FileManager.default.removeItem(at: directory) }
        let chat = Self.chat(id: "chat-a", title: "Alpha", lastMessageAt: "2026-07-06T10:00:00Z")
        let embedRef = WatchEmbedRef(
            id: "embed-web-1",
            type: EmbedType.webWebsite.rawValue,
            status: "finished",
            data: [
                "title": AnyCodable("Watch-sized preview"),
                "url": AnyCodable("https://example.invalid/post"),
            ]
        )
        let api = FakeWatchChatAPI(
            messagesByChatId: [
                "chat-a": [Self.remoteMessage(
                    id: "msg-a",
                    chatId: "chat-a",
                    content: "```json\n{\"type\":\"web-website\",\"embed_id\":\"embed-web-1\"}\n```",
                    embedRefs: [embedRef]
                )]
            ]
        )
        let runtime = WatchChatRuntime(
            api: api,
            cache: WatchChatOfflineCache(directory: directory),
            crypto: FakeWatchChatCrypto()
        )

        await runtime.openChat(chat)

        let message = try XCTUnwrap(runtime.selectedMessages.first)
        XCTAssertEqual(message.embedRefs, [embedRef])
        XCTAssertNil(message.watchDisplayContent)
        XCTAssertEqual(message.watchEmbedRecords.first?.id, "embed-web-1")
        let preview = try XCTUnwrap(message.watchEmbedRecords.first.map {
            WatchEmbedPreviewMapper.makeModel(for: $0, chatId: message.chatId)
        })
        XCTAssertEqual(preview.title, "Watch-sized preview")
        XCTAssertEqual(preview.continuation.chatId, "chat-a")
    }

    // contract-test: supporting surface=gui.apple assertions=apple-watch.chats.compact-layout
    func testOpenChatBuildsWatchEmbedRefsFromInlineJsonWhenApiOmitsRefs() async throws {
        let directory = temporaryDirectory()
        defer { try? FileManager.default.removeItem(at: directory) }
        let chat = Self.chat(id: "chat-a", title: "Alpha", lastMessageAt: "2026-07-06T10:00:00Z")
        let api = FakeWatchChatAPI(
            messagesByChatId: [
                "chat-a": [Self.remoteMessage(
                    id: "msg-a",
                    chatId: "chat-a",
                    content: "```json\n{\"type\":\"web-website\",\"embed_id\":\"embed-web-1\",\"title\":\"Inline preview\"}\n```"
                )]
            ]
        )
        let runtime = WatchChatRuntime(
            api: api,
            cache: WatchChatOfflineCache(directory: directory),
            crypto: FakeWatchChatCrypto()
        )

        await runtime.openChat(chat)

        let message = try XCTUnwrap(runtime.selectedMessages.first)
        XCTAssertNil(message.watchDisplayContent)
        let ref = try XCTUnwrap(message.embedRefs?.first)
        XCTAssertEqual(ref.id, "embed-web-1")
        XCTAssertEqual(ref.type, EmbedType.webWebsite.rawValue)
        XCTAssertEqual(ref.data?["title"]?.value as? String, "Inline preview")
        XCTAssertEqual(message.watchEmbedRecords.first?.id, "embed-web-1")
    }

    // contract-test: supporting surface=gui.apple assertions=apple-watch.chats.compact-layout
    func testWatchRuntimeDisplayMergeKeepsMarkersWithEmptyAPIReferenceArray() async throws {
        let directory = temporaryDirectory()
        defer { try? FileManager.default.removeItem(at: directory) }
        let runtime = WatchChatRuntime(api: FakeWatchChatAPI(), cache: WatchChatOfflineCache(directory: directory), crypto: FakeWatchChatCrypto())
        let message = WatchChatMessage(id: "synthetic", chatId: "fixture-chat", role: .assistant,
            content: "Hello Watch\n[!](embed:sheet-marker)", encryptedContent: nil, embedRefs: [],
            createdAt: "2026-10-03T12:00:00Z", isPending: false)
        let displayed = runtime.messageWithHydratedEmbeds(message)
        XCTAssertEqual(displayed.embedRefs?.map(\.id), ["sheet-marker"])
        XCTAssertEqual(displayed.watchEmbedRecords.map(\.id), ["sheet-marker"])
        XCTAssertEqual(displayed.watchDisplayContent, "Hello Watch")
        XCTAssertEqual(WatchEmbedPreviewMapper.makeModel(for: try XCTUnwrap(displayed.watchEmbedRecords.first), chatId: "fixture-chat").state, .unavailable)
    }

    // contract-test: supporting surface=gui.apple assertions=apple-watch.chats.browse-search-open
    func testRealtimeSyncUsesCachedWatchClientStateWithoutIncognitoChats() async throws {
        let directory = temporaryDirectory()
        defer { try? FileManager.default.removeItem(at: directory) }
        let cache = WatchChatOfflineCache(directory: directory)
        let socket = FakeWatchChatSyncSocket()
        try await cache.saveSnapshot(
            WatchChatSnapshot(
                chats: [
                    Self.chat(id: "chat-a", title: "Alpha", lastMessageAt: "2026-07-06T10:00:00Z"),
                    Self.chat(id: "incognito-local", title: "Private", lastMessageAt: "2026-07-06T11:00:00Z"),
                ],
                messagesByChatId: [:],
                pendingTextSends: [],
                savedAt: Date()
            )
        )
        let runtime = WatchChatRuntime(
            api: FakeWatchChatAPI(),
            cache: cache,
            crypto: FakeWatchChatCrypto(),
            syncSocket: socket,
            syncSession: WatchSyncSession(sessionId: "watch-session", token: "watch-ws-token")
        )

        await runtime.loadCachedSnapshot()
        await runtime.startRealtimeSync()

        XCTAssertEqual(socket.connectedSession, WatchSyncSession(sessionId: "watch-session", token: "watch-ws-token"))
        XCTAssertEqual(socket.connectedSyncState?.clientChatIds, ["chat-a"])
        XCTAssertEqual(socket.connectedSyncState?.clientChatVersions, ["chat-a": ["messages_v": 0, "title_v": 0, "metadata_v": 0, "draft_v": 0]])
        XCTAssertEqual(socket.connectedSyncState?.clientEmbedIds, [])
    }

    // contract-test: direct surface=gui.apple assertions=apple-watch.chats.audio-reply
    func testAudioRecordingUploadsTranscribesAndSendsEncryptedEmbedTurn() async throws {
        let directory = temporaryDirectory()
        defer { try? FileManager.default.removeItem(at: directory) }
        let cache = WatchChatOfflineCache(directory: directory)
        let chat = Self.chat(id: "chat-a", title: "Alpha", lastMessageAt: "2026-07-06T10:00:00Z")
        let api = FakeWatchChatAPI(
            chats: [Self.remoteChat(id: "chat-a", title: "Alpha", lastMessageAt: "2026-07-06T10:00:00Z")],
            messagesByChatId: ["chat-a": []], uploadedAudio: Self.uploadedAudio()
        )
        let socket = FakeWatchChatSyncSocket()
        let runtime = WatchChatRuntime(api: api, cache: cache, crypto: FakeWatchChatCrypto(),
                                       syncSocket: socket, syncSession: WatchSyncSession(sessionId: "s", token: "t"))
        await runtime.refresh()
        await runtime.openChat(chat)
        await runtime.sendAudioRecording(data: Data([0, 1, 2, 3]), filename: "watch-recording.m4a", duration: 4.2)
        XCTAssertEqual(api.uploadedAudioRequests.first?.chatId, "chat-a")
        XCTAssertEqual(api.transcribedAudioIds, ["watch-audio-embed"])
        XCTAssertEqual(socket.sentTurns.count, 1)
        XCTAssertTrue(runtime.pendingAudioEmbeds.isEmpty)
        let turn = try XCTUnwrap(socket.sentTurns.first)
        let inference = try XCTUnwrap(JSONSerialization.jsonObject(with: turn.inferenceJSON) as? [String: Any])
        XCTAssertEqual((inference["embeds"] as? [[String: Any]])?.first?["embed_id"] as? String, "watch-audio-embed")
        let audioContent = try XCTUnwrap((inference["embeds"] as? [[String: Any]])?.first?["content"] as? String)
        let audioMetadata = try XCTUnwrap(JSONSerialization.jsonObject(with: Data(audioContent.utf8)) as? [String: Any])
        XCTAssertEqual(audioMetadata["transcription"] as? String, "Watch transcript")
        XCTAssertEqual(audioMetadata["transcript_original"] as? String, "Watch transcript")
        XCTAssertEqual(audioMetadata["model"] as? String, "test-model")
        XCTAssertNotNil((inference["encrypted_embeds"] as? [[String: Any]])?.first?["encrypted_content"])
        XCTAssertEqual(runtime.selectedMessages.last?.embedRefs?.first?.id, "watch-audio-embed")
    }

    // contract-test: direct surface=gui.apple assertions=apple-watch.chats.audio-reply
    func testAudioStaysInOriginalChatWhenSelectionChangesDuringUpload() async throws {
        let directory = temporaryDirectory()
        defer { try? FileManager.default.removeItem(at: directory) }
        let gate = WatchAudioUploadGate()
        let api = FakeWatchChatAPI(
            chats: [
                Self.remoteChat(id: "chat-a", title: "Alpha", lastMessageAt: "2026-07-06T10:00:00Z"),
                Self.remoteChat(id: "chat-b", title: "Beta", lastMessageAt: "2026-07-06T10:00:00Z"),
            ],
            messagesByChatId: ["chat-a": [], "chat-b": []],
            uploadedAudio: Self.uploadedAudio(), uploadGate: gate
        )
        let socket = FakeWatchChatSyncSocket()
        let runtime = WatchChatRuntime(api: api, cache: WatchChatOfflineCache(directory: directory),
                                       crypto: FakeWatchChatCrypto(), syncSocket: socket,
                                       syncSession: WatchSyncSession(sessionId: "s", token: "t"))
        await runtime.refresh()
        await runtime.openChat(Self.chat(id: "chat-a", title: "Alpha", lastMessageAt: "2026-07-06T10:00:00Z"))
        let sendTask = Task {
            await runtime.sendAudioRecording(data: Data([0, 1, 2, 3]), filename: "watch-recording.m4a", duration: 4.2)
        }
        await gate.waitUntilStarted()
        runtime.selectedChatId = "chat-b"
        await gate.resumeUpload()
        _ = await sendTask.value

        XCTAssertEqual(socket.sentTurns.map(\.chatId), ["chat-a"])
        XCTAssertTrue(runtime.selectedMessages.isEmpty, "The newly selected chat must not receive the recording")
    }

    // contract-test: supporting surface=gui.apple assertions=apple-offline.recent-cohort,apple-offline.interruption-isolation
    func testUnvisitedChatCohortStartsWhenHubNavigationSettlesAndAlsoDuringBackgroundGrant() async throws {
        let directory = temporaryDirectory()
        defer { try? FileManager.default.removeItem(at: directory) }
        let cache = WatchChatOfflineCache(directory: directory)
        let crypto = WatchOfflineFixtureCrypto()
        let transport = WatchOfflineFixtureTransport(crypto: crypto)
        let runtime = WatchChatRuntime(currentUserId: WatchOfflineFixtureTransport.accountID,
            api: transport, cache: cache, crypto: crypto, syncSocket: transport)
        runtime.setForegroundNavigationBusy(true)
        await runtime.setForeground(true)
        await runtime.refresh()
        await runtime.waitForRecentOfflineSync()
        XCTAssertTrue(transport.requestedIDs.isEmpty, "The former Tasks/Workflows lifetime latch prevents the entire cohort")
        runtime.setForegroundNavigationBusy(false)
        await runtime.waitForRecentOfflineSync()
        XCTAssertEqual(transport.requestedIDs.count, 20, "No conversation was opened to start maintenance")
        XCTAssertNil(runtime.selectedChatId)
        XCTAssertTrue(runtime.messagesByChatId.isEmpty)
        await runtime.setForeground(false)
        try await cache.removeSnapshot()
        runtime.setForegroundNavigationBusy(true)
        await runtime.performBackgroundOfflineSync()
        XCTAssertEqual(transport.requestedIDs.count, 40, "OS background work must ignore an offscreen selected hub section")
        let saved = await cache.loadConversation(chatID: "watch-offline-20", accountID: WatchOfflineFixtureTransport.accountID, serverScope: WatchChatRuntime.currentServerScope)
        XCTAssertEqual(saved?.messageCount, 101)
        runtime.stopRealtimeSync()
    }

    // contract-test: direct surface=gui.apple assertions=apple-watch.offline.recent-cohort
    func testRecentWatchCohortIgnoresPinnedOrderAndHasStableTimestampTies() {
        var records: [WatchChatSummary] = (0..<25).map { index -> WatchChatSummary in
            Self.offlineChat(id: String(format: "chat-%02d", index), lastMessageAt: String(100 + index), isPinned: index == 0)
        }
        records[1].lastEditedOverallTimestamp = "500"
        var tied = Self.offlineChat(id: "chat-a", lastMessageAt: "500")
        tied.lastEditedOverallTimestamp = "500"
        var child = Self.offlineChat(id: "child", lastMessageAt: "999")
        child.parentID = "parent"; child.isSubChat = true
        records += [tied, child, Self.offlineChat(id: "incognito-test", lastMessageAt: "999")]
        let cohort = WatchRecentOfflinePolicy.cohort(records)
        XCTAssertEqual(cohort.count, 20)
        XCTAssertEqual(Array(cohort.prefix(2)).map(\.id), ["chat-01", "chat-a"])
        XCTAssertFalse(cohort.contains { $0.id == "chat-00" || $0.id == "child" || $0.id == "incognito-test" })
        XCTAssertEqual(cohort.map(\.id), WatchRecentOfflinePolicy.cohort(Array(records.reversed())).map(\.id))
    }

    // contract-test: direct surface=gui.apple assertions=apple-watch.offline.recent-cohort,apple-watch.chats.compact-layout
    func testLatestTwentyWatchConversationsPersistThenReopenOfflineWithPagedEmbeds() async throws {
        let directory = temporaryDirectory()
        defer { try? FileManager.default.removeItem(at: directory) }
        let cache = WatchChatOfflineCache(directory: directory)
        let crypto = WatchOfflineFixtureCrypto()
        let transport = WatchOfflineFixtureTransport(crypto: crypto)
        let runtime = WatchChatRuntime(currentUserId: WatchOfflineFixtureTransport.accountID,
            api: transport, cache: cache, crypto: crypto, syncSocket: transport)
        await runtime.setForeground(true)
        await runtime.refresh()
        await runtime.waitForRecentOfflineSync()
        XCTAssertEqual(transport.requestedIDs, (1...20).reversed().map { "watch-offline-\($0)" })
        XCTAssertEqual(crypto.decryptedMessageCount, 0, "Maintenance must never decrypt/publish twenty transcripts")
        XCTAssertTrue(runtime.messagesByChatId.isEmpty)
        for id in 1...20 {
            let value = await cache.loadConversation(chatID: "watch-offline-\(id)", accountID: WatchOfflineFixtureTransport.accountID, serverScope: WatchChatRuntime.currentServerScope)
            XCTAssertNotNil(value)
        }
        let storedRecent = await cache.loadConversation(chatID: "watch-offline-20", accountID: WatchOfflineFixtureTransport.accountID, serverScope: WatchChatRuntime.currentServerScope)
        let recent = try XCTUnwrap(storedRecent)
        XCTAssertEqual(recent.messageCount, 101)
        XCTAssertEqual(recent.messagePages.count, 3)
        XCTAssertFalse(recent.messagePages.contains { $0.contains("Last offline response") })
        let pinnedOld = await cache.loadConversation(chatID: "watch-offline-0", accountID: WatchOfflineFixtureTransport.accountID, serverScope: WatchChatRuntime.currentServerScope)
        XCTAssertNil(pinnedOld)
        transport.offline = true
        runtime.stopRealtimeSync()
        let restored = WatchChatRuntime(currentUserId: WatchOfflineFixtureTransport.accountID,
            api: transport, cache: cache, crypto: crypto, syncSocket: nil)
        await restored.loadCachedSnapshot()
        XCTAssertTrue(restored.messagesByChatId.isEmpty, "Cold startup keeps complete transcripts on disk")
        await restored.openChat(try XCTUnwrap(restored.chats.first { $0.id == "watch-offline-20" }))
        XCTAssertTrue(restored.isOffline)
        XCTAssertEqual(transport.windowReadCount, 4, "Cold open follows the existing four-attempt connectivity retry budget using only bounded windows")
        XCTAssertEqual(transport.fullMessageReadCount, 0, "Offline fallback must retain the complete cohort instead of requesting full REST history")
        XCTAssertEqual(restored.selectedMessages.map(\.id), ["offline-message-100"])
        XCTAssertEqual(restored.hydratedEmbedPreviews["offline-sheet"]?.data?["title"]?.value as? String, "offline.xls")
        await restored.loadOfflinePage(0)
        XCTAssertEqual(restored.selectedMessages.count, 50)
        XCTAssertEqual(restored.selectedMessages.first?.id, "offline-message-0")
        XCTAssertTrue(restored.hydratedEmbedPreviews.isEmpty)
        await restored.loadOfflinePage(1)
        XCTAssertEqual(restored.selectedMessages.count, 50)
        XCTAssertEqual(restored.selectedMessages.first?.id, "offline-message-50")
        await restored.loadOfflinePage(2)
        XCTAssertNotNil(restored.hydratedEmbedPreviews["offline-sheet"])
        XCTAssertEqual(restored.offlinePageCount, 3)
        let other = WatchChatRuntime(currentUserId: "another-owner", api: transport, cache: cache, crypto: crypto, syncSocket: nil)
        await other.loadCachedSnapshot()
        XCTAssertTrue(other.chats.isEmpty)
        let wrongOwner = await cache.loadConversation(chatID: "watch-offline-20", accountID: "another-owner", serverScope: WatchChatRuntime.currentServerScope)
        XCTAssertNil(wrongOwner)
        try await cache.removeSnapshot()
        let removed = await cache.loadConversation(chatID: "watch-offline-20", accountID: WatchOfflineFixtureTransport.accountID, serverScope: WatchChatRuntime.currentServerScope)
        XCTAssertNil(removed, "Logout removes ciphertext cohort files as well as metadata")
    }

    // contract-test: direct surface=gui.apple assertions=apple-watch.offline.recent-cohort
    func testWatchCompleteReceiptRejectsPartialResponseAndCountMismatch() async throws {
        let cache = WatchChatOfflineCache(directory: temporaryDirectory())
        let crypto = WatchOfflineFixtureCrypto()
        let transport = WatchOfflineFixtureTransport(crypto: crypto)
        for mismatch in [false, true] {
            transport.partialBatch = !mismatch; transport.wrongCount = mismatch
            let fields = try await transport.requestEvent(type: "request_chat_content_batch", payload: ["chat_ids": ["watch-offline-20"]], responseTypes: ["chat_content_batch_response"], matching: { _ in true })
            do {
                _ = try await cache.prepareConversation(JSONSerialization.data(withJSONObject: fields), chatID: "watch-offline-20")
                XCTFail("Incomplete response must never become a complete receipt")
            } catch WatchChatRuntimeError.historyUnavailable { }
        }
    }

    // contract-test: direct surface=gui.apple assertions=apple-watch.offline.recent-cohort
    func testWatchNavigationPreemptsMaintenanceAndCanResumeWithoutLateWrites() async throws {
        let directory = temporaryDirectory()
        defer { try? FileManager.default.removeItem(at: directory) }
        let cache = WatchChatOfflineCache(directory: directory)
        let crypto = WatchOfflineFixtureCrypto()
        let transport = WatchOfflineFixtureTransport(crypto: crypto)
        transport.holdBatch = true
        let runtime = WatchChatRuntime(currentUserId: WatchOfflineFixtureTransport.accountID,
            api: transport, cache: cache, crypto: crypto, syncSocket: transport)
        await runtime.setForeground(true)
        await runtime.refresh()
        let clock = ContinuousClock()
        let requestDeadline = clock.now.advanced(by: .seconds(3))
        while transport.requestedIDs.isEmpty && clock.now < requestDeadline {
            try await Task.sleep(for: .milliseconds(5))
        }
        XCTAssertEqual(transport.requestedIDs, ["watch-offline-20"])
        runtime.setForegroundNavigationBusy(true)
        transport.holdBatch = false
        for _ in 0..<20 { await Task.yield() }
        let beforeResume = await cache.loadConversation(chatID: "watch-offline-20", accountID: WatchOfflineFixtureTransport.accountID, serverScope: WatchChatRuntime.currentServerScope)
        XCTAssertNil(beforeResume)
        runtime.setForegroundNavigationBusy(false)
        await runtime.waitForRecentOfflineSync()
        let resumed = await cache.loadConversation(chatID: "watch-offline-20", accountID: WatchOfflineFixtureTransport.accountID, serverScope: WatchChatRuntime.currentServerScope)
        XCTAssertEqual(resumed?.messageCount, 101)
        runtime.stopRealtimeSync()
    }

    // contract-test: direct surface=gui.apple assertions=apple-watch.offline.recent-cohort
    func testWatchCohortCommitRejectsAccountGenerationRaceAndOtherServer() async throws {
        let directory = temporaryDirectory()
        defer { try? FileManager.default.removeItem(at: directory) }
        let cache = WatchChatOfflineCache(directory: directory)
        let generation = WatchChatAccountLifecycle.generation
        let scope = WatchChatRuntime.currentServerScope
        let chat = Self.offlineChat(id: "race-chat", lastMessageAt: "100", encryptedTitle: "cipher-title")
        let receipt = WatchOfflineConversation(chat: chat, accountID: "owner", serverScope: scope,
            revision: "1|100", messagesVersion: 1, messageCount: 1,
            messagePages: ["sealed-original"], embedPages: [], supplemental: "sealed-supplemental")
        try await cache.saveConversation(receipt, accountGeneration: generation)
        WatchChatAccountLifecycle.invalidate()
        do {
            try await cache.saveConversation(receipt, accountGeneration: generation)
            XCTFail("A late response from the old account lifecycle must not write")
        } catch is CancellationError { }
        let retained = await cache.loadConversation(chatID: chat.id, accountID: "owner", serverScope: scope)
        XCTAssertEqual(retained?.messagePages, ["sealed-original"])
        let wrongServer = await cache.loadConversation(chatID: chat.id, accountID: "owner", serverScope: "https://another.example")
        XCTAssertNil(wrongServer)
    }

    // contract-test: direct surface=gui.apple assertions=apple-watch.offline.recent-cohort
    func testColdWatchReceiptRecoversRealWrappedKeysWithoutImmutableOutboundRow() async throws {
        let directory = temporaryDirectory()
        defer { try? FileManager.default.removeItem(at: directory) }
        let account = "watch-offline-unit-" + UUID().uuidString
        let master = SymmetricKey(size: .bits256)
        let chatKey = SymmetricKey(size: .bits256)
        let embedKey = SymmetricKey(size: .bits256)
        try await CryptoManager.shared.saveMasterKey(master, for: account)
        do {
            let wrapped = try await CryptoManager.shared.wrapChatKey(chatKey, masterKey: master)
            let encryptedTitle = try await CryptoManager.shared.encryptContent("Synthetic cold chat", key: chatKey)
            let encryptedBody = try await CryptoManager.shared.encryptContent("Cold offline answer\n[!](embed:cold-sheet)", key: chatKey)
            let message = ["id": "cold-message", "chat_id": "cold-chat", "role": "assistant", "encrypted_content": encryptedBody, "created_at": "100"]
            let messagePage = try await CryptoManager.shared.encryptContent(String(decoding: JSONSerialization.data(withJSONObject: [message]), as: UTF8.self), key: chatKey)
            let hash = WatchChatKeyWrapperRecord.hashedChatId
            let embed: [String: Any] = ["embed_id": "cold-sheet", "chat_id": "cold-chat", "user_id": account,
                "already_encrypted": true, "encryption_mode": "client", "status": "finished",
                "type": try ComposerEmbedCrypto.encryptContent("sheet", using: embedKey),
                "content": try ComposerEmbedCrypto.encryptContent("{\"title\":\"cold.xls\",\"cell_count\":2,\"table\":\"|Name|Value|\\n|---|---|\\n|Cold|7|\"}", using: embedKey),
                "embed_keys": [["hashed_embed_id": hash("cold-sheet"), "hashed_user_id": hash(account), "key_type": "master",
                    "encrypted_embed_key": try ComposerEmbedCrypto.wrapKey(embedKey, using: master)]]]
            let embedPage = try await CryptoManager.shared.encryptContent(String(decoding: JSONSerialization.data(withJSONObject: [embed]), as: UTF8.self), key: chatKey)
            let cache = WatchChatOfflineCache(directory: directory)
            var storedChat = Self.offlineChat(id: "cold-chat", lastMessageAt: "100", encryptedTitle: encryptedTitle)
            storedChat.encryptedChatKey = nil // Only the independently validated master wrapper is available.
            var receipt = WatchOfflineConversation(chat: storedChat, accountID: account, serverScope: WatchChatRuntime.currentServerScope,
                revision: "1|100", messagesVersion: 1, messageCount: 1, messagePages: [messagePage], embedPages: [embedPage],
                supplemental: try await CryptoManager.shared.encryptContent("{}", key: chatKey))
            receipt.wrappedRecoveryChatKey = wrapped
            try await cache.saveConversation(receipt, accountGeneration: WatchChatAccountLifecycle.generation)
            let restored = WatchChatRuntime(currentUserId: account, api: FakeWatchChatAPI(shouldThrow: true), cache: cache, syncSocket: nil)
            await restored.loadCachedSnapshot() // No legacy metadata file and a fresh production crypto/key map.
            XCTAssertEqual(restored.chats.first?.title, "Synthetic cold chat")
            XCTAssertNil(restored.chats.first?.encryptedChatKey, "Read-only recovery must not replace the immutable outbound row wrapper")
            XCTAssertTrue(restored.messagesByChatId.isEmpty)
            await restored.openChat(try XCTUnwrap(restored.chats.first))
            XCTAssertEqual(restored.selectedMessages.first?.content, "Cold offline answer\n[!](embed:cold-sheet)")
            XCTAssertEqual(restored.hydratedEmbedPreviews["cold-sheet"]?.data?["title"]?.value as? String, "cold.xls")
            try await CryptoManager.shared.deleteMasterKey(for: account)
        } catch {
            try? await CryptoManager.shared.deleteMasterKey(for: account)
            throw error
        }
    }

    private static func offlineChat(id: String, lastMessageAt: String, isPinned: Bool = false,
                                    encryptedTitle: String? = nil) -> WatchChatSummary {
        WatchChatSummary(id: id, title: nil, lastMessageAt: lastMessageAt, preview: nil,
            isPinned: isPinned, encryptedTitle: encryptedTitle, encryptedPreview: nil,
            encryptedChatKey: "wrapped-chat-key")
    }

    private func temporaryDirectory() -> URL {
        FileManager.default.temporaryDirectory
            .appendingPathComponent("watch-chat-runtime-tests-\(UUID().uuidString)", isDirectory: true)
    }

    private static func chat(
        id: String,
        title: String,
        lastMessageAt: String,
        isPinned: Bool = false
    ) -> WatchChatSummary {
        WatchChatSummary(
            id: id,
            title: title,
            lastMessageAt: lastMessageAt,
            preview: nil,
            isPinned: isPinned,
            encryptedTitle: nil,
            encryptedPreview: nil,
            encryptedChatKey: "wrapped-chat-key"
        )
    }

    private static func message(id: String, chatId: String, content: String) -> WatchChatMessage {
        return WatchChatMessage(
            id: id,
            chatId: chatId,
            role: .assistant,
            content: content,
            encryptedContent: nil,
            embedRefs: nil,
            createdAt: "2026-07-06T10:00:00Z",
            isPending: false
        )
    }

    private static func remoteChat(
        id: String,
        title: String?,
        lastMessageAt: String,
        isPinned: Bool = false,
        encryptedTitle: String? = nil,
        encryptedSummary: String? = nil
    ) -> WatchRemoteChat {
        WatchRemoteChat(
            id: id,
            title: title,
            lastMessageAt: lastMessageAt,
            updatedAt: nil,
            chatSummary: nil,
            isPinned: isPinned,
            encryptedTitle: encryptedTitle,
            encryptedChatSummary: encryptedSummary,
            encryptedChatKey: "wrapped-chat-key"
        )
    }

    private static func remoteMessage(
        id: String,
        chatId: String,
        content: String?,
        encryptedContent: String? = nil,
        embedRefs: [WatchEmbedRef]? = nil
    ) -> WatchRemoteMessage {
        WatchRemoteMessage(
            id: id,
            chatId: chatId,
            role: .assistant,
            content: content,
            encryptedContent: encryptedContent,
            embedRefs: embedRefs,
            createdAt: "2026-07-06T10:00:00Z"
        )
    }

    private static func uploadedAudio() -> WatchUploadedAudio {
        WatchUploadedAudio(
            embedId: "watch-audio-embed",
            filename: "watch-recording.m4a",
            contentType: "audio/mp4",
            contentHash: "audio-hash",
            files: [
                "original": WatchUploadedFileVariant(
                    s3Key: "recordings/watch-recording.m4a",
                    sizeBytes: 4,
                    width: nil,
                    height: nil,
                    format: "m4a"
                )
            ],
            s3BaseUrl: "https://files.example.invalid",
            aesKey: "redacted-aes-key",
            aesNonce: "redacted-aes-nonce",
            vaultWrappedAesKey: "redacted-wrapped-key"
        )
    }
}

private struct FakeAudioUploadRequest: Equatable {
    let data: Data
    let filename: String
    let chatId: String
}

private actor WatchAudioUploadGate {
    private var started = false
    private var startedWaiter: CheckedContinuation<Void, Never>?
    private var resumeWaiter: CheckedContinuation<Void, Never>?

    func suspendUpload() async {
        started = true
        startedWaiter?.resume()
        startedWaiter = nil
        await withCheckedContinuation { resumeWaiter = $0 }
    }

    func waitUntilStarted() async {
        if started { return }
        await withCheckedContinuation { startedWaiter = $0 }
    }

    func resumeUpload() {
        resumeWaiter?.resume()
        resumeWaiter = nil
    }
}

private actor WatchChatFetchGate {
    private var started = false
    private var startedWaiter: CheckedContinuation<Void, Never>?
    private var releaseWaiter: CheckedContinuation<Void, Never>?

    func waitUntilStarted() async {
        if started { return }
        await withCheckedContinuation { startedWaiter = $0 }
    }

    func suspendFetch() async {
        started = true
        startedWaiter?.resume()
        startedWaiter = nil
        await withCheckedContinuation { releaseWaiter = $0 }
    }

    func release() {
        releaseWaiter?.resume()
        releaseWaiter = nil
    }
}

private final class FakeWatchChatAPI: WatchChatAPI, @unchecked Sendable {
    private let shouldThrow: Bool
    var chatFetchError: Error?
    private let chatFetchGate: WatchChatFetchGate?
    private let ignoresChatOffset: Bool
    private let maxAcceptedChatLimit: Int?
    var chats: [WatchRemoteChat]
    private let messagesByChatId: [String: [WatchRemoteMessage]]
    private let uploadedAudio: WatchUploadedAudio?
    private let uploadGate: WatchAudioUploadGate?
    private var transientChatFetchFailures: Int
    private var transientMessageFetchFailures: Int
    private(set) var fetchRecentChatsCallCount = 0
    private(set) var lastRequestedChatLimit: Int?
    private(set) var requestedChatOffsets: [Int] = []
    private(set) var fetchMessagesCallCount = 0
    private(set) var fetchMessageWindowCallCount = 0
    private(set) var windowQueries: [WatchMessageWindowQuery] = []
    var windowFetchGate: WatchChatFetchGate?
    var messageWindowError: Error?
    private(set) var uploadedAudioRequests: [FakeAudioUploadRequest] = []
    private(set) var transcribedAudioIds: [String] = []

    init(
        chats: [WatchRemoteChat] = [],
        messagesByChatId: [String: [WatchRemoteMessage]] = [:],
        shouldThrow: Bool = false,
        chatFetchError: Error? = nil,
        ignoresChatOffset: Bool = false,
        maxAcceptedChatLimit: Int? = nil,
        transientChatFetchFailures: Int = 0,
        transientMessageFetchFailures: Int = 0,
        uploadedAudio: WatchUploadedAudio? = nil,
        uploadGate: WatchAudioUploadGate? = nil,
        chatFetchGate: WatchChatFetchGate? = nil
    ) {
        self.chats = chats
        self.messagesByChatId = messagesByChatId
        self.shouldThrow = shouldThrow
        self.chatFetchError = chatFetchError
        self.ignoresChatOffset = ignoresChatOffset
        self.maxAcceptedChatLimit = maxAcceptedChatLimit
        self.transientChatFetchFailures = transientChatFetchFailures
        self.transientMessageFetchFailures = transientMessageFetchFailures
        self.uploadedAudio = uploadedAudio
        self.uploadGate = uploadGate
        self.chatFetchGate = chatFetchGate
    }

    func fetchRecentChats(limit: Int, offset: Int, context: WatchChatRequestContext) async throws -> [WatchRemoteChat] {
        await chatFetchGate?.suspendFetch()
        fetchRecentChatsCallCount += 1
        lastRequestedChatLimit = limit
        requestedChatOffsets.append(offset)
        if transientChatFetchFailures > 0 {
            transientChatFetchFailures -= 1
            throw URLError(.networkConnectionLost)
        }
        if let chatFetchError { throw chatFetchError }
        if let maxAcceptedChatLimit, limit > maxAcceptedChatLimit {
            throw APIError.httpError(status: 503, message: "Page too large")
        }
        if shouldThrow { throw URLError(.notConnectedToInternet) }
        return Array(chats.dropFirst(ignoresChatOffset ? 0 : offset).prefix(limit))
    }

    func fetchMessagesVersion(chatId: String, context: WatchChatRequestContext) async throws -> Int? {
        messagesByChatId[chatId]?.count
    }

    func fetchMessageWindow(chatId: String, query: WatchMessageWindowQuery, context: WatchChatRequestContext) async throws -> WatchMessageWindow {
        fetchMessageWindowCallCount += 1
        windowQueries.append(query)
        await windowFetchGate?.suspendFetch()
        if let messageWindowError { throw messageWindowError }
        if transientMessageFetchFailures > 0 {
            transientMessageFetchFailures -= 1
            throw URLError(.networkConnectionLost)
        }
        if shouldThrow { throw URLError(.notConnectedToInternet) }
        let formatter = ISO8601DateFormatter()
        func cursor(_ message: WatchRemoteMessage) -> WatchMessageWindowCursor {
            WatchMessageWindowCursor(createdAt: Int(Double(message.createdAt) ?? formatter.date(from: message.createdAt)?.timeIntervalSince1970 ?? 0), messageId: message.id)
        }
        let all = (messagesByChatId[chatId] ?? []).sorted {
            let lhs = cursor($0), rhs = cursor($1)
            return lhs.createdAt == rhs.createdAt ? lhs.messageId < rhs.messageId : lhs.createdAt < rhs.createdAt
        }
        var eligible = all
        if let before = query.before { eligible = all.filter { let c = cursor($0); return c.createdAt < before.createdAt || (c.createdAt == before.createdAt && c.messageId < before.messageId) } }
        if let after = query.after { eligible = all.filter { let c = cursor($0); return c.createdAt > after.createdAt || (c.createdAt == after.createdAt && c.messageId > after.messageId) } }
        if let anchor = query.anchorMessageId { eligible = all.filter { $0.id == anchor } }
        let page = Array(query.direction == .after ? eligible.prefix(query.limit) : eligible.suffix(query.limit))
        return WatchMessageWindow(chatId: chatId, messages: page,
            hasMoreBefore: query.direction != .around && query.direction != .after && eligible.count > page.count,
            hasMoreAfter: query.direction == .before || (query.direction == .after && eligible.count > page.count),
            startCursor: page.first.map(cursor), endCursor: page.last.map(cursor),
            anchorFound: query.direction != .around || !page.isEmpty,
            messagesV: all.count, serverMessageCount: all.count)
    }

    func fetchMessages(chatId: String, context: WatchChatRequestContext) async throws -> [WatchRemoteMessage] {
        fetchMessagesCallCount += 1
        if transientMessageFetchFailures > 0 {
            transientMessageFetchFailures -= 1
            throw URLError(.networkConnectionLost)
        }
        if shouldThrow { throw URLError(.notConnectedToInternet) }
        return messagesByChatId[chatId] ?? []
    }

    func uploadAudioRecording(data: Data, filename: String, chatId: String, context: WatchChatRequestContext) async throws -> WatchUploadedAudio {
        if shouldThrow { throw URLError(.notConnectedToInternet) }
        uploadedAudioRequests.append(FakeAudioUploadRequest(data: data, filename: filename, chatId: chatId))
        if let uploadGate { await uploadGate.suspendUpload() }
        guard let uploadedAudio else { throw WatchChatRuntimeError.audioUploadFailed }
        return uploadedAudio
    }

    func transcribeAudioRecording(_ upload: WatchUploadedAudio, chatId: String, context: WatchChatRequestContext) async throws -> WatchTranscriptionMetadata? {
        if shouldThrow { throw URLError(.notConnectedToInternet) }
        transcribedAudioIds.append(upload.embedId)
        return WatchTranscriptionMetadata(
            title: nil, transcript: "Watch transcript", transcriptOriginal: "Watch transcript",
            transcriptCorrected: nil, useCorrected: false, model: "test-model",
            correctionModel: nil, waveform: nil
        )
    }
}

private struct WatchLiveAccountCredentials {
    let email: String
    let password: String
    let otpKey: String

    static func fromEnvironment(preferredReservedSlot slot: Int) throws -> WatchLiveAccountCredentials {
        let environment = ProcessInfo.processInfo.environment
        if let credentials = read(environment: environment, prefix: "OPENMATES_TEST_ACCOUNT_\(slot)") {
            return credentials
        }
        for fallbackSlot in 1...20 where fallbackSlot != slot {
            if let credentials = read(environment: environment, prefix: "OPENMATES_TEST_ACCOUNT_\(fallbackSlot)") {
                return credentials
            }
        }
        if let credentials = read(environment: environment, prefix: "OPENMATES_TEST_ACCOUNT") {
            return credentials
        }
        let fileEnvironment = readCredentialFile()
        if let credentials = read(environment: fileEnvironment, prefix: "OPENMATES_TEST_ACCOUNT_\(slot)") {
            return credentials
        }
        for fallbackSlot in 1...20 where fallbackSlot != slot {
            if let credentials = read(environment: fileEnvironment, prefix: "OPENMATES_TEST_ACCOUNT_\(fallbackSlot)") {
                return credentials
            }
        }
        if let credentials = read(environment: fileEnvironment, prefix: "OPENMATES_TEST_ACCOUNT") {
            return credentials
        }
        throw XCTSkip("Missing OPENMATES_TEST_ACCOUNT or reserved Apple slot \(slot) credentials")
    }

    private static func read(environment: [String: String], prefix: String) -> WatchLiveAccountCredentials? {
        guard let email = environment["\(prefix)_EMAIL"], !email.isEmpty,
              let password = environment["\(prefix)_PASSWORD"], !password.isEmpty,
              let otpKey = environment["\(prefix)_OTP_KEY"], !otpKey.isEmpty else {
            return nil
        }
        return WatchLiveAccountCredentials(email: email, password: password, otpKey: otpKey)
    }

    private static func readCredentialFile() -> [String: String] {
        let sourceFileURL = URL(fileURLWithPath: #filePath)
        let credentialFileURL = sourceFileURL
            .deletingLastPathComponent()
            .deletingLastPathComponent()
            .appendingPathComponent(".openmates-live-test-account.env")
        guard let contents = try? String(contentsOf: credentialFileURL, encoding: .utf8) else {
            return [:]
        }

        var values: [String: String] = [:]
        for rawLine in contents.split(separator: "\n") {
            let line = rawLine.trimmingCharacters(in: .whitespacesAndNewlines)
            guard !line.isEmpty, !line.hasPrefix("#") else { continue }
            let parts = line.split(separator: "=", maxSplits: 1, omittingEmptySubsequences: false)
            guard parts.count == 2 else { continue }
            values[String(parts[0])] = String(parts[1])
        }
        return values
    }
}

private enum WatchLiveTOTP {
    static func waitPastBoundaryIfNeeded(date: Date = Date()) {
        let secondsIntoWindow = Int(date.timeIntervalSince1970) % 30
        guard secondsIntoWindow >= 25 else { return }
        Thread.sleep(forTimeInterval: TimeInterval(30 - secondsIntoWindow + 2))
    }

    static func generate(secret: String, windowOffset: Int = 0, date: Date = Date()) -> String {
        let key = SymmetricKey(data: base32Decode(secret))
        let counter = UInt64(Int64(floor(date.timeIntervalSince1970 / 30.0)) + Int64(windowOffset))
        var counterBigEndian = counter.bigEndian
        let counterData = Data(bytes: &counterBigEndian, count: MemoryLayout<UInt64>.size)
        let hash = HMAC<Insecure.SHA1>.authenticationCode(for: counterData, using: key)
        let bytes = Array(hash)
        let offset = Int(bytes[19] & 0x0f)
        let code = (UInt32(bytes[offset] & 0x7f) << 24)
            | (UInt32(bytes[offset + 1]) << 16)
            | (UInt32(bytes[offset + 2]) << 8)
            | UInt32(bytes[offset + 3])
        return String(format: "%06u", code % 1_000_000)
    }

    private static func base32Decode(_ value: String) -> Data {
        let alphabet = Array("ABCDEFGHIJKLMNOPQRSTUVWXYZ234567")
        let lookup = Dictionary(uniqueKeysWithValues: alphabet.enumerated().map { ($1, $0) })
        var bits = 0
        var bitBuffer = 0
        var output = Data()

        for character in value.uppercased() where character != "=" && character != " " {
            guard let index = lookup[character] else { continue }
            bitBuffer = (bitBuffer << 5) | index
            bits += 5
            if bits >= 8 {
                bits -= 8
                output.append(UInt8((bitBuffer >> bits) & 0xff))
            }
        }

        return output
    }
}

@MainActor
private final class FakeWatchChatSyncSocket: WatchChatSyncSocket {
    var becomesReadyOnConnect = false
    var artifactRequest: (@MainActor (String, [String: Any]) async throws -> [String: Any])?
    private(set) var artifactRequests: [(type: String, payload: Data)] = []
    private(set) var isConnected = false
    private(set) var connectedSession: WatchSyncSession?
    private(set) var connectedSyncState: WatchSyncClientState?
    private(set) var didDisconnect = false
    private(set) var sentTurns: [WatchPendingTextSend] = []
    private(set) var attemptedTurns: [WatchPendingTextSend] = []
    var shouldRejectSend: Bool
    var rejectionCode: String?
    var sendFailure: WatchChatRuntimeError?
    var beforeTurnResult: (@MainActor () async throws -> Void)?

    init(shouldRejectSend: Bool = false, rejectionCode: String? = nil) {
        self.shouldRejectSend = shouldRejectSend
        self.rejectionCode = rejectionCode
    }

    func connect(session: WatchSyncSession, syncState: WatchSyncClientState) {
        connectedSession = session
        connectedSyncState = syncState
        if becomesReadyOnConnect { isConnected = true }
    }

    func requestEvent(type: String, payload: [String: Any], responseTypes: Set<String>,
        matching: @escaping @MainActor ([String: Any]) -> Bool,
        beforeSend: @escaping @MainActor () throws -> Void) async throws -> [String: Any] {
        try beforeSend()
        artifactRequests.append((type, try JSONSerialization.data(withJSONObject: payload, options: [.sortedKeys])))
        guard let artifactRequest else { throw WatchChatRuntimeError.socketUnavailable }
        let response = try await artifactRequest(type, payload)
        guard matching(response) else { throw WatchChatRuntimeError.socketUnavailable }
        return response
    }

    func disconnect() { didDisconnect = true }
    func setChangeHandler(_ handler: (@MainActor () -> Void)?) {}
    func sendTurn(_ pending: WatchPendingTextSend) async throws {
        attemptedTurns.append(pending)
        try await beforeTurnResult?()
        if let sendFailure { throw sendFailure }
        if shouldRejectSend {
            if let rejectionCode { throw WatchTurnAdmissionDiagnostic.serverRejection(stage: .preflight, code: rejectionCode) }
            throw WatchChatRuntimeError.preflightRejected
        }
        sentTurns.append(pending)
    }
}

@MainActor
private final class WatchNotificationTestSocket: WatchChatSyncSocket {
    private(set) var generation = 0
    private(set) var isConnected = false
    private(set) var connectCount = 0
    private(set) var events: [(String, [String: Any])] = []
    private(set) var receiptRequests: [[String: Any]] = []
    private var readyHandler: (@MainActor () -> Void)?
    private var viewedResponses: [Bool]

    init(viewedResponses: [Bool] = []) { self.viewedResponses = viewedResponses }

    func connect(session: WatchSyncSession, syncState: WatchSyncClientState) {
        generation += 1
        connectCount += 1
        isConnected = true
        readyHandler?()
    }

    func disconnect() { dropConnection() }
    func dropConnection() { generation += 1; isConnected = false }
    func setChangeHandler(_ handler: (@MainActor () -> Void)?) {}
    func setReadyHandler(_ handler: (@MainActor () -> Void)?) { readyHandler = handler }
    func sendTurn(_ pending: WatchPendingTextSend) async throws { throw WatchChatRuntimeError.socketUnavailable }

    func sendEvent(type: String, payload: [String: Any]) async throws {
        guard isConnected else { throw WatchChatRuntimeError.socketUnavailable }
        events.append((type, payload))
    }

    func requestEvent(type: String, payload: [String: Any], responseTypes: Set<String>,
        matching: @escaping @MainActor ([String: Any]) -> Bool,
        beforeSend: @escaping @MainActor () throws -> Void) async throws -> [String: Any] {
        try beforeSend()
        guard isConnected else { throw WatchChatRuntimeError.socketUnavailable }
        receiptRequests.append(payload)
        let viewed = viewedResponses.isEmpty ? true : viewedResponses.removeFirst()
        let response: [String: Any] = [
            "request_id": payload["request_id"] ?? "",
            "chat_id": payload["chat_id"] ?? "",
            "message_id": payload["message_id"] ?? "",
            "viewed": viewed,
        ]
        guard responseTypes.contains("notification_message_viewed_ack"), matching(response) else {
            throw WatchChatRuntimeError.socketUnavailable
        }
        return response
    }
}

@MainActor
private final class FakeWatchChatCrypto: WatchChatCrypto {
    private let decryptedValues: [String: String]
    private let omittedChatIds: Set<String>
    private let textKey: SymmetricKey?
    private let draftKey = SymmetricKey(size: .bits256)
    private(set) var artifactPreparationCount = 0
    private var artifactKeys: [String: SymmetricKey] = [:]

    init(decryptedValues: [String: String] = [:], omittedChatIds: Set<String> = [], textKey: SymmetricKey? = nil) {
        self.decryptedValues = decryptedValues
        self.omittedChatIds = omittedChatIds
        self.textKey = textKey
    }

    private func openedText(_ ciphertext: String) -> String? {
        if let value = decryptedValues[ciphertext] { return value }
        if let textKey, let value = try? ComposerEmbedCrypto.decryptContent(ciphertext, using: textKey) { return value }
        guard ciphertext.hasPrefix("encrypted:") else { return nil }
        return String(ciphertext.dropFirst("encrypted:".count))
    }

    func decryptChat(_ chat: WatchRemoteChat) async -> WatchChatSummary? {
        guard !omittedChatIds.contains(chat.id) else { return nil }
        return WatchChatSummary(
            id: chat.id,
            title: chat.encryptedTitle.flatMap(openedText) ?? chat.title,
            lastMessageAt: chat.lastMessageAt ?? chat.updatedAt,
            preview: chat.encryptedChatSummary.flatMap(openedText) ?? chat.chatSummary,
            isPinned: chat.isPinned,
            encryptedTitle: chat.encryptedTitle,
            encryptedPreview: chat.encryptedChatSummary,
            encryptedChatKey: chat.encryptedChatKey,
            messagesV: chat.messagesV, titleV: chat.titleV, metadataV: chat.metadataV
        )
    }

    func decryptMessage(_ message: WatchRemoteMessage) async -> WatchChatMessage {
        let content = message.encryptedContent.flatMap(openedText) ?? message.content
        let embedRefs = message.embedRefs ?? WatchMessageContentSanitizer.inlineEmbedRefs(content: content)
        return WatchChatMessage(
            id: message.id,
            chatId: message.chatId,
            role: message.role,
            content: content,
            encryptedContent: message.encryptedContent,
            embedRefs: embedRefs.isEmpty ? nil : embedRefs,
            createdAt: message.createdAt,
            isPending: false
        )
    }

    func encryptText(_ text: String, for chat: WatchChatSummary) async throws -> String {
        if let textKey { return try ComposerEmbedCrypto.encryptContent(text, using: textKey) }
        return "encrypted:\(text)"
    }
    func decryptText(_ ciphertext: String, for chat: WatchChatSummary) async throws -> String {
        guard let value = openedText(ciphertext) else { throw WatchChatRuntimeError.missingChatKey }
        return value
    }
    func encryptDraft(_ text: String) async throws -> String {
        try await CryptoManager.shared.encryptWithMasterKey(text, masterKey: draftKey)
    }
    func decryptDraft(_ ciphertext: String) async throws -> String {
        try await CryptoManager.shared.decryptContent(base64String: ciphertext, key: draftKey)
    }
    func createChat(withID id: String) async throws -> WatchChatSummary {
        WatchChatSummary(id: id, title: nil, lastMessageAt: nil, preview: nil,
                         isPinned: false, encryptedTitle: "encrypted:", encryptedPreview: nil,
                         encryptedChatKey: "wrapped-new-key")
    }
    func createChat() async throws -> WatchChatSummary {
        WatchChatSummary(id: "new-chat", title: nil, lastMessageAt: nil, preview: nil,
                         isPinned: false, encryptedTitle: "encrypted:", encryptedPreview: nil,
                         encryptedChatKey: "wrapped-new-key")
    }
    func hydrateEmbed(payload: [String: Any], chat: WatchChatSummary) async throws -> WatchEmbedRef {
        guard let id = payload["embed_id"] as? String, let owner = payload["user_id"] as? String else {
            throw WatchChatRuntimeError.missingChatKey
        }
        let preview = try WatchEmbedHydration.open(payload: payload, embedID: id, chatID: chat.id,
            accountID: owner, masterKey: draftKey, chatKey: draftKey)
        if payload["already_encrypted"] as? Bool == true || payload["encryption_mode"] as? String == "client" {
            artifactKeys[chat.id + ":" + id] = try WatchEmbedHydration.versionKey(payload: payload, embedID: id,
                chatID: chat.id, accountID: owner, masterKey: draftKey, chatKey: draftKey)
        }
        return preview
    }
    func decryptArtifactVersion(_ ciphertext: String, embedID: String, chat: WatchChatSummary) async throws -> String {
        guard let key = artifactKeys[chat.id + ":" + embedID] else { throw WatchChatRuntimeError.missingChatKey }
        return try ComposerEmbedCrypto.decryptContent(ciphertext, using: key)
    }
    func prepareEmbedStorage(payload: [String: Any], chat: WatchChatSummary, messageID: String) async throws -> (keys: [String: Any], embed: [String: Any]) {
        artifactPreparationCount += 1
        guard let id = payload["embed_id"] as? String, let owner = payload["user_id"] as? String else {
            throw WatchChatRuntimeError.missingChatKey
        }
        return try WatchEmbedHydration.prepareStorage(payload: payload, embedID: id, chatID: chat.id,
            messageID: messageID, accountID: owner, masterKey: draftKey, chatKey: draftKey)
    }
    func recoveryPublicKey(for chat: WatchChatSummary) async throws -> String { "recovery-public-key" }
    func encryptedAudioEmbed(_ embed: WatchPendingAudioEmbed, chat: WatchChatSummary, messageId: String) async throws -> [[String: Any]] {
        [["embed_id": embed.id, "encrypted_content": "encrypted-embed-content"]]
    }
}

@MainActor
extension WatchChatRuntimeTests {
    // contract-test: direct surface=gui.apple assertions=drafts.persistence.local-first-encrypted,drafts.draft-only.lifecycle,apple-watch.chats.new-text-reply
    func testWatchDraftPromotesOnContentRestoresSameIdentityAndClearsUnsavedShell() async throws {
        let directory = temporaryDirectory()
        defer { try? FileManager.default.removeItem(at: directory) }
        let cache = WatchChatOfflineCache(directory: directory)
        let crypto = FakeWatchChatCrypto()
        let runtime = WatchChatRuntime(currentUserId: "synthetic-owner", api: FakeWatchChatAPI(), cache: cache, crypto: crypto, syncSocket: nil)
        await runtime.createNewChat()
        XCTAssertTrue(runtime.chats.isEmpty)
        let emptySnapshot = await cache.loadSnapshot()
        XCTAssertTrue(emptySnapshot.chats.isEmpty)
        runtime.updateComposerDraft("Public fixture draft", chatId: "new-chat")
        await runtime.leaveChat() // Flush debounce through the real persistence path.
        let snapshot = await cache.loadSnapshot()
        XCTAssertEqual(snapshot.chats.map(\.id), ["new-chat"])
        XCTAssertEqual(snapshot.accountID, "synthetic-owner")
        let encrypted = try XCTUnwrap(snapshot.encryptedDrafts["new-chat"]?.encryptedMarkdown)
        XCTAssertNotEqual(encrypted, "Public fixture draft")
        let decryptedDraft = try await crypto.decryptDraft(encrypted)
        XCTAssertEqual(decryptedDraft, "Public fixture draft")
        XCTAssertFalse(String(decoding: try JSONEncoder().encode(snapshot), as: UTF8.self).contains("Public fixture draft"))
        let draftAPI = FakeWatchChatAPI(shouldThrow: true)
        let reopened = WatchChatRuntime(currentUserId: "synthetic-owner", api: draftAPI, cache: cache, crypto: crypto, syncSocket: nil)
        await reopened.loadCachedSnapshot()
        XCTAssertEqual(reopened.composerDrafts["new-chat"], "Public fixture draft")
        await reopened.openChat(try XCTUnwrap(reopened.chats.first))
        XCTAssertEqual(draftAPI.fetchMessageWindowCallCount, 0, "A known unsent draft opens locally without a server transcript")
        XCTAssertNil(reopened.errorMessage)
        reopened.updateComposerDraft("", chatId: "new-chat")
        await reopened.leaveChat()
        let cleared = await cache.loadSnapshot()
        XCTAssertTrue(cleared.chats.isEmpty)
        XCTAssertNil(cleared.encryptedDrafts["new-chat"]?.encryptedMarkdown)
        XCTAssertTrue(cleared.encryptedDrafts["new-chat"]?.needsSync == true)
    }

    // contract-test: direct surface=gui.apple assertions=drafts.access.first-party-encrypted,drafts.sync.version-authoritative
    func testWatchDraftCacheRejectsAnotherAccountAndStoppedGenerationCannotWrite() async throws {
        let directory = temporaryDirectory()
        defer { try? FileManager.default.removeItem(at: directory) }
        let cache = WatchChatOfflineCache(directory: directory)
        let crypto = FakeWatchChatCrypto()
        let first = WatchChatRuntime(currentUserId: "owner-a", api: FakeWatchChatAPI(), cache: cache, crypto: crypto, syncSocket: nil)
        await first.createNewChat()
        first.updateComposerDraft("Synthetic account draft", chatId: "new-chat")
        await first.leaveChat()
        let second = WatchChatRuntime(currentUserId: "owner-b", api: FakeWatchChatAPI(), cache: cache, crypto: crypto, syncSocket: nil)
        await second.loadCachedSnapshot()
        XCTAssertTrue(second.chats.isEmpty)
        XCTAssertTrue(second.composerDrafts.isEmpty)
        first.stopRealtimeSync()
        first.updateComposerDraft("Late changed draft", chatId: "new-chat")
        await first.leaveChat()
        let stored = await cache.loadSnapshot()
        let text = try await crypto.decryptDraft(try XCTUnwrap(stored.encryptedDrafts["new-chat"]?.encryptedMarkdown))
        XCTAssertEqual(text, "Synthetic account draft")
    }
}

@MainActor
private final class WatchDraftTestSocket: WatchChatSyncSocket {
    var generation = 1
    var events: [(String, [String: Any])] = []
    func connect(session: WatchSyncSession, syncState: WatchSyncClientState) {}
    func disconnect() { generation += 1 }
    func setChangeHandler(_ handler: (@MainActor () -> Void)?) {}
    func sendTurn(_ pending: WatchPendingTextSend) async throws { throw WatchChatRuntimeError.socketUnavailable }
    func sendEvent(type: String, payload: [String: Any]) async throws { events.append((type, payload)) }
}

@MainActor
extension WatchChatRuntimeTests {
    // contract-test: direct surface=gui.apple assertions=drafts.sync.version-authoritative,drafts.persistence.local-first-encrypted
    func testWatchSupersededCurrentDraftReceiptAcceptsRemoteWinnerAndNeverReplaysAfterReconnect() async throws {
        let directory = temporaryDirectory()
        defer { try? FileManager.default.removeItem(at: directory) }
        let cache = WatchChatOfflineCache(directory: directory)
        let crypto = FakeWatchChatCrypto()
        let socket = WatchDraftTestSocket()
        let runtime = WatchChatRuntime(api: FakeWatchChatAPI(), cache: cache, crypto: crypto, syncSocket: socket)
        await runtime.createNewChat()
        runtime.updateComposerDraft("Superseded public draft", chatId: "new-chat")
        await runtime.leaveChat()
        let staleCiphertext = try XCTUnwrap(socket.events.first?.1["encrypted_draft_md"] as? String)
        runtime.handleDraftSyncEvent(type: "draft_update_receipt", payload: [
            "chat_id": "new-chat", "draft_v": 1, "success": true, "superseded": true
        ])
        await waitForWatchDraft { socket.events.last?.0 == "phased_sync_request" }
        XCTAssertEqual(socket.events.last?.1["refresh_chat_ids"] as? [String], ["new-chat"])
        XCTAssertEqual(runtime.composerDrafts["new-chat"], "Superseded public draft", "The receipt does not invent replacement content")
        let retired = await cache.loadSnapshot()
        XCTAssertEqual(retired.encryptedDrafts["new-chat"]?.needsSync, false)
        XCTAssertEqual(retired.encryptedDrafts["new-chat"]?.serverVersion, 0, "The lost write's allocated version does not acknowledge ciphertext")
        await runtime.openChat(try XCTUnwrap(runtime.chats.first))
        await runtime.leaveChat() // Back before the winning content arrives must not requeue stale text.
        socket.generation += 1
        await runtime.replayPendingDrafts()
        XCTAssertEqual(socket.events.filter { $0.0 == "update_draft" }.count, 1)
        let winner = try await crypto.encryptDraft("Winning public draft")
        runtime.handleDraftSyncEvent(type: "chat_draft_updated", payload: [
            "chat_id": "new-chat", "data": ["encrypted_draft_md": winner], "versions": ["draft_v": 2]
        ])
        await waitForWatchDraft { runtime.composerDrafts["new-chat"] == "Winning public draft" }
        XCTAssertEqual(runtime.composerDrafts["new-chat"], "Winning public draft")
        socket.generation += 1
        await runtime.replayPendingDrafts()
        XCTAssertEqual(socket.events.filter { $0.0 == "update_draft" }.count, 1)
        let restoredSocket = WatchDraftTestSocket()
        let restored = WatchChatRuntime(api: FakeWatchChatAPI(), cache: cache, crypto: crypto, syncSocket: restoredSocket)
        await restored.loadCachedSnapshot()
        await restored.replayPendingDrafts()
        XCTAssertEqual(restored.composerDrafts["new-chat"], "Winning public draft")
        XCTAssertFalse(restoredSocket.events.contains { $0.1["encrypted_draft_md"] as? String == staleCiphertext })
        XCTAssertTrue(restoredSocket.events.isEmpty)
    }

    // contract-test: direct surface=gui.apple assertions=drafts.sync.version-authoritative
    func testWatchBackDoesNotRequeueAcknowledgedDraftAfterEditingAnotherChat() async throws {
        let directory = temporaryDirectory()
        defer { try? FileManager.default.removeItem(at: directory) }
        let cache = WatchChatOfflineCache(directory: directory)
        let crypto = FakeWatchChatCrypto()
        let socket = WatchDraftTestSocket()
        let runtime = WatchChatRuntime(api: FakeWatchChatAPI(), cache: cache, crypto: crypto, syncSocket: socket)
        for chatID in ["draft-a", "draft-b"] {
            let ciphertext = try await crypto.encryptDraft("Original public draft")
            runtime.handleDraftSyncEvent(type: "chat_draft_updated", payload: [
                "chat_id": chatID, "data": ["encrypted_draft_md": ciphertext], "versions": ["draft_v": 1]
            ])
            await waitForWatchDraft { runtime.composerDrafts[chatID] == "Original public draft" }
            await runtime.openChat(try XCTUnwrap(runtime.chats.first { $0.id == chatID }))
            runtime.updateComposerDraft("Edited public \(chatID)", chatId: chatID)
            await runtime.leaveChat()
            runtime.handleDraftSyncEvent(type: "draft_update_receipt", payload: ["chat_id": chatID, "draft_v": 2, "success": true])
        }
        XCTAssertEqual(socket.events.filter { $0.0 == "update_draft" }.count, 2)
        let acknowledgedCiphertext = try XCTUnwrap(socket.events.first?.1["encrypted_draft_md"] as? String)
        await runtime.openChat(try XCTUnwrap(runtime.chats.first { $0.id == "draft-a" }))
        await runtime.leaveChat()
        socket.generation += 1
        await runtime.replayPendingDrafts()
        XCTAssertEqual(socket.events.filter { $0.0 == "update_draft" }.count, 2, "A different chat's revision cannot turn an unchanged acknowledged draft into a new write")
        let snapshot = await cache.loadSnapshot()
        XCTAssertEqual(snapshot.encryptedDrafts["draft-a"]?.needsSync, false)
        XCTAssertEqual(snapshot.encryptedDrafts["draft-a"]?.encryptedMarkdown, acknowledgedCiphertext)
    }

    // contract-test: direct surface=gui.apple assertions=drafts.sync.version-authoritative
    func testWatchSupersededReceiptRetiresCacheAcrossImmediateSocketReconnect() async throws {
        let directory = temporaryDirectory()
        defer { try? FileManager.default.removeItem(at: directory) }
        let cache = WatchChatOfflineCache(directory: directory)
        let crypto = FakeWatchChatCrypto()
        let socket = WatchDraftTestSocket()
        let runtime = WatchChatRuntime(api: FakeWatchChatAPI(), cache: cache, crypto: crypto, syncSocket: socket)
        await runtime.createNewChat()
        runtime.updateComposerDraft("Superseded reconnect draft", chatId: "new-chat")
        await runtime.leaveChat()
        runtime.handleDraftSyncEvent(type: "draft_update_receipt", payload: [
            "chat_id": "new-chat", "draft_v": 1, "success": true, "superseded": true
        ])
        socket.generation += 1 // Reconnect before the receipt's persistence task starts.
        var retired = false
        for _ in 0..<100 {
            let snapshot = await cache.loadSnapshot()
            if snapshot.encryptedDrafts["new-chat"]?.needsSync == false { retired = true; break }
            try? await Task.sleep(for: .milliseconds(5))
        }
        XCTAssertTrue(retired, "Transport replacement must not retain a stale durable write")
        let restoredSocket = WatchDraftTestSocket()
        let restored = WatchChatRuntime(api: FakeWatchChatAPI(), cache: cache, crypto: crypto, syncSocket: restoredSocket)
        await restored.loadCachedSnapshot()
        await restored.replayPendingDrafts()
        XCTAssertTrue(restoredSocket.events.isEmpty)
        XCTAssertFalse(socket.events.contains { $0.0 == "phased_sync_request" }, "An old transport's fetch task cannot send on the replacement socket")
    }

    // contract-test: direct surface=gui.apple assertions=drafts.sync.version-authoritative
    func testWatchSupersededReceiptPreservesNewerLocalDraftRevision() async throws {
        let directory = temporaryDirectory()
        defer { try? FileManager.default.removeItem(at: directory) }
        let cache = WatchChatOfflineCache(directory: directory)
        let crypto = FakeWatchChatCrypto()
        let socket = WatchDraftTestSocket()
        let runtime = WatchChatRuntime(api: FakeWatchChatAPI(), cache: cache, crypto: crypto, syncSocket: socket)
        await runtime.createNewChat()
        runtime.updateComposerDraft("First public draft", chatId: "new-chat")
        await runtime.leaveChat()
        await runtime.openChat(try XCTUnwrap(runtime.chats.first))
        runtime.updateComposerDraft("Newer local public draft", chatId: "new-chat")
        runtime.handleDraftSyncEvent(type: "draft_update_receipt", payload: [
            "chat_id": "new-chat", "draft_v": 1, "success": true, "superseded": true
        ])
        await runtime.replayPendingDrafts()
        XCTAssertEqual(socket.events.filter { $0.0 == "update_draft" }.count, 1, "An edit awaiting encryption must not replay its older queued revision")
        await runtime.leaveChat()
        await waitForWatchDraft { socket.events.filter { $0.0 == "update_draft" }.count == 2 }
        let newerCiphertext = try XCTUnwrap(socket.events.last?.1["encrypted_draft_md"] as? String)
        let newerText = try await crypto.decryptDraft(newerCiphertext)
        XCTAssertEqual(newerText, "Newer local public draft")
        let competing = try await crypto.encryptDraft("Competing public draft")
        runtime.handleDraftSyncEvent(type: "chat_draft_updated", payload: [
            "chat_id": "new-chat", "data": ["encrypted_draft_md": competing], "versions": ["draft_v": 2]
        ])
        XCTAssertEqual(runtime.composerDrafts["new-chat"], "Newer local public draft")
        XCTAssertFalse(socket.events.contains { $0.0 == "phased_sync_request" })
        let snapshot = await cache.loadSnapshot()
        XCTAssertEqual(snapshot.encryptedDrafts["new-chat"]?.needsSync, true)
        XCTAssertEqual(snapshot.encryptedDrafts["new-chat"]?.encryptedMarkdown, newerCiphertext)
    }

    // contract-test: direct surface=gui.apple assertions=drafts.sync.version-authoritative,drafts.persistence.local-first-encrypted
    func testWatchDraftReceiptCannotAcknowledgeNewerEditOrResurrectClearedDraft() async throws {
        let directory = temporaryDirectory()
        defer { try? FileManager.default.removeItem(at: directory) }
        let cache = WatchChatOfflineCache(directory: directory)
        let crypto = FakeWatchChatCrypto()
        let socket = WatchDraftTestSocket()
        let runtime = WatchChatRuntime(api: FakeWatchChatAPI(), cache: cache, crypto: crypto, syncSocket: socket)
        await runtime.createNewChat()
        runtime.updateComposerDraft("First public draft", chatId: "new-chat")
        await runtime.leaveChat()
        XCTAssertEqual(socket.events.count, 1)
        XCTAssertEqual(socket.events.first?.0, "update_draft")
        let firstCiphertext = try XCTUnwrap(socket.events.first?.1["encrypted_draft_md"] as? String)
        await runtime.openChat(try XCTUnwrap(runtime.chats.first))
        runtime.updateComposerDraft("Newer public draft", chatId: "new-chat")
        await runtime.leaveChat()
        XCTAssertEqual(socket.events.count, 1, "Only one unacknowledged write per chat")
        runtime.handleDraftSyncEvent(type: "draft_update_receipt", payload: ["chat_id": "new-chat", "draft_v": 1, "success": true])
        await runtime.replayPendingDrafts()
        XCTAssertEqual(socket.events.count, 2)
        XCTAssertEqual(runtime.composerDrafts["new-chat"], "Newer public draft")
        runtime.handleDraftSyncEvent(type: "chat_draft_updated", payload: ["chat_id": "new-chat", "data": ["encrypted_draft_md": firstCiphertext], "versions": ["draft_v": 1]])
        XCTAssertEqual(runtime.composerDrafts["new-chat"], "Newer public draft")
        await runtime.openChat(try XCTUnwrap(runtime.chats.first))
        runtime.updateComposerDraft("", chatId: "new-chat")
        await runtime.leaveChat()
        runtime.handleDraftSyncEvent(type: "draft_update_receipt", payload: ["chat_id": "new-chat", "draft_v": 2, "success": true])
        await runtime.replayPendingDrafts()
        XCTAssertEqual(socket.events.last?.0, "delete_draft")
        runtime.handleDraftSyncEvent(type: "chat_draft_updated", payload: ["chat_id": "new-chat", "data": ["encrypted_draft_md": firstCiphertext], "versions": ["draft_v": 2]])
        XCTAssertEqual(runtime.composerDrafts["new-chat"], "")
        XCTAssertTrue(runtime.chats.isEmpty)
    }

    // contract-test: direct surface=gui.apple assertions=drafts.access.first-party-encrypted
    func testWatchAccountInvalidationRejectsLateSnapshotWrite() async throws {
        let directory = temporaryDirectory()
        defer { try? FileManager.default.removeItem(at: directory) }
        let cache = WatchChatOfflineCache(directory: directory)
        let generation = WatchChatAccountLifecycle.generation
        WatchChatAccountLifecycle.invalidate()
        do {
            try await cache.saveSnapshot(.empty, accountGeneration: generation)
            XCTFail("A revoked account generation cannot write a snapshot")
        } catch is CancellationError { }
        let snapshot = await cache.loadSnapshot()
        XCTAssertEqual(snapshot.savedAt, .distantPast)
    }
}

@MainActor
extension WatchChatRuntimeTests {
    private func waitForWatchDraft(_ predicate: () -> Bool) async {
        for _ in 0..<100 {
            if predicate() { return }
            try? await Task.sleep(for: .milliseconds(5))
        }
    }

    // contract-test: direct surface=gui.apple assertions=drafts.draft-only.lifecycle
    func testClearingWatchDraftPreservesEstablishedChatWhenTranscriptIsUnavailable() async throws {
        let directory = temporaryDirectory()
        defer { try? FileManager.default.removeItem(at: directory) }
        let cache = WatchChatOfflineCache(directory: directory)
        let crypto = FakeWatchChatCrypto()
        let runtime = WatchChatRuntime(api: FakeWatchChatAPI(shouldThrow: true), cache: cache, crypto: crypto, syncSocket: nil)
        let ciphertext = try await crypto.encryptDraft("Public offline draft")
        runtime.handleDraftSyncEvent(type: "chat_draft_updated", payload: [
            "chat_id": "established-chat", "messages_v": 7,
            "data": ["encrypted_draft_md": ciphertext], "versions": ["draft_v": 3]
        ])
        await waitForWatchDraft { runtime.composerDrafts["established-chat"] == "Public offline draft" }
        let chat = try XCTUnwrap(runtime.chats.first)
        XCTAssertEqual(chat.messagesV, 7)
        await runtime.openChat(chat)
        XCTAssertTrue(runtime.selectedMessages.isEmpty)
        runtime.updateComposerDraft("", chatId: chat.id)
        await runtime.leaveChat()
        XCTAssertEqual(runtime.chats.map(\.id), [chat.id])
        XCTAssertEqual(runtime.composerDrafts[chat.id], "")
        let snapshot = await cache.loadSnapshot()
        XCTAssertEqual(snapshot.chats.map(\.id), [chat.id])
        XCTAssertEqual(snapshot.chats.first?.messagesV, 7)
        XCTAssertNil(snapshot.encryptedDrafts[chat.id]?.encryptedMarkdown)
    }

    // contract-test: direct surface=gui.apple assertions=drafts.draft-only.lifecycle,drafts.sync.version-authoritative
    func testWatchRemoteDraftCreatesShellPreservesMetadataOmissionAndHonorsVersionedDeletion() async throws {
        let directory = temporaryDirectory()
        defer { try? FileManager.default.removeItem(at: directory) }
        let crypto = FakeWatchChatCrypto()
        let runtime = WatchChatRuntime(api: FakeWatchChatAPI(), cache: WatchChatOfflineCache(directory: directory), crypto: crypto, syncSocket: nil)
        let ciphertext = try await crypto.encryptDraft("Remote public draft")
        runtime.handleDraftSyncEvent(type: "chat_draft_updated", payload: ["chat_id": "remote-draft", "data": ["encrypted_draft_md": ciphertext], "versions": ["draft_v": 3]])
        await waitForWatchDraft { runtime.composerDrafts["remote-draft"] == "Remote public draft" }
        XCTAssertEqual(runtime.chats.map(\.id), ["remote-draft"])
        runtime.handleDraftSyncEvent(type: "chat_details", payload: ["id": "remote-draft", "draft_v": 4])
        XCTAssertEqual(runtime.composerDrafts["remote-draft"], "Remote public draft", "Metadata omission cannot clear content")
        runtime.handleDraftSyncEvent(type: "draft_deleted", payload: ["chat_id": "remote-draft", "draft_v": 2])
        XCTAssertEqual(runtime.composerDrafts["remote-draft"], "Remote public draft", "Older deletion cannot win")
        runtime.handleDraftSyncEvent(type: "draft_deleted", payload: ["chat_id": "remote-draft", "draft_v": 4])
        await waitForWatchDraft { runtime.chats.isEmpty }
        XCTAssertTrue(runtime.chats.isEmpty)
        runtime.handleDraftSyncEvent(type: "chat_draft_updated", payload: ["chat_id": "remote-draft", "data": ["encrypted_draft_md": ciphertext], "versions": ["draft_v": 4]])
        await Task.yield()
        XCTAssertTrue(runtime.chats.isEmpty, "An equal-version echo cannot resurrect the tombstoned shell")
        XCTAssertEqual(runtime.composerDrafts["remote-draft"], "")
    }

    // contract-test: direct surface=gui.apple assertions=drafts.sync.version-authoritative,drafts.access.first-party-encrypted
    func testWatchReconnectDraftVersionsRequireTombstoneAndFetchPositiveNewerDetailsThroughSupportedPhase() async throws {
        let directory = temporaryDirectory()
        defer { try? FileManager.default.removeItem(at: directory) }
        let crypto = FakeWatchChatCrypto()
        let socket = WatchDraftTestSocket()
        let runtime = WatchChatRuntime(api: FakeWatchChatAPI(), cache: WatchChatOfflineCache(directory: directory), crypto: crypto, syncSocket: socket)
        let ciphertext = try await crypto.encryptDraft("Synced public draft")
        runtime.handleDraftSyncEvent(type: "phase_2_last_20_chats_ready", payload: ["context_epoch": 0, "chats": [["chat_details": ["id": "remote-draft", "encrypted_draft_md": ciphertext, "draft_v": 2]]]])
        await waitForWatchDraft { runtime.composerDrafts["remote-draft"] == "Synced public draft" }
        await runtime.requestDraftVersions()
        XCTAssertEqual(socket.events.last?.0, "get_draft_versions")
        runtime.handleDraftSyncEvent(type: "draft_versions_response", payload: ["versions": ["remote-draft": 0]])
        await Task.yield()
        XCTAssertEqual(runtime.composerDrafts["remote-draft"], "Synced public draft", "Absent Redis state does not delete an authoritative local draft")
        runtime.handleDraftSyncEvent(type: "draft_versions_response", payload: ["versions": ["remote-draft": 3]])
        await waitForWatchDraft { socket.events.last?.0 == "phased_sync_request" }
        XCTAssertEqual(socket.events.last?.1["phase"] as? String, "phase2")
        XCTAssertEqual(socket.events.last?.1["refresh_chat_ids"] as? [String], ["remote-draft"])
        runtime.handleDraftSyncEvent(type: "draft_versions_response", payload: ["versions": ["remote-draft": 0], "tombstone_versions": ["remote-draft": 3]])
        await waitForWatchDraft { runtime.chats.isEmpty }
        XCTAssertTrue(runtime.chats.isEmpty)
        runtime.handleDraftSyncEvent(type: "phase_2_last_20_chats_ready", payload: ["team_id": "synthetic-team", "context_epoch": 1, "chats": [["chat_details": ["id": "team-draft", "encrypted_draft_md": ciphertext, "draft_v": 10]]]])
        await Task.yield()
        XCTAssertFalse(runtime.chats.contains { $0.id == "team-draft" })
    }

    // contract-test: direct surface=gui.apple assertions=drafts.access.first-party-encrypted
    func testWatchCacheRejectsSameAccountIDFromAnotherServerScope() async throws {
        let directory = temporaryDirectory()
        defer { try? FileManager.default.removeItem(at: directory) }
        let cache = WatchChatOfflineCache(directory: directory)
        let crypto = FakeWatchChatCrypto()
        let ciphertext = try await crypto.encryptDraft("Other server draft")
        try await cache.saveSnapshot(WatchChatSnapshot(chats: [Self.chat(id: "foreign", title: "Foreign", lastMessageAt: "2026-09-30T12:00:00Z")],
            messagesByChatId: [:], savedAt: Date(), accountID: "same-owner", serverScope: "https://other.example/api|https://other.example",
            encryptedDrafts: ["foreign": WatchEncryptedDraft(encryptedMarkdown: ciphertext, encryptedPreview: ciphertext, serverVersion: 2, needsSync: false)]))
        let runtime = WatchChatRuntime(currentUserId: "same-owner", api: FakeWatchChatAPI(), cache: cache, crypto: crypto, syncSocket: nil)
        await runtime.loadCachedSnapshot()
        XCTAssertTrue(runtime.chats.isEmpty)
        XCTAssertTrue(runtime.composerDrafts.isEmpty)
    }
}

@MainActor
extension WatchChatRuntimeTests {
    // contract-test: direct surface=gui.apple assertions=drafts.draft-only.lifecycle,apple-watch.chats.new-text-reply
    func testRemoteDraftSendCreatesChatKeyForSameIdentityAndPromotesItsTurn() async throws {
        let directory = temporaryDirectory()
        defer { try? FileManager.default.removeItem(at: directory) }
        let crypto = FakeWatchChatCrypto()
        let socket = FakeWatchChatSyncSocket()
        let runtime = WatchChatRuntime(api: FakeWatchChatAPI(), cache: WatchChatOfflineCache(directory: directory), crypto: crypto,
            syncSocket: socket, syncSession: WatchSyncSession(sessionId: "fixture-session", token: nil))
        let ciphertext = try await crypto.encryptDraft("Remote public draft")
        runtime.handleDraftSyncEvent(type: "chat_draft_updated", payload: ["chat_id": "remote-draft", "data": ["encrypted_draft_md": ciphertext], "versions": ["draft_v": 3]])
        await waitForWatchDraft { runtime.chats.contains { $0.id == "remote-draft" } }
        await runtime.openChat(try XCTUnwrap(runtime.chats.first))
        let sent = await runtime.sendText("Remote public draft")
        XCTAssertTrue(sent)
        XCTAssertEqual(socket.sentTurns.first?.chatId, "remote-draft")
        XCTAssertEqual(runtime.selectedChatId, "remote-draft")
        XCTAssertEqual(runtime.selectedMessages.first?.role, .user)
        XCTAssertEqual(runtime.composerDrafts["remote-draft"], "")
    }

    // contract-test: supporting surface=gui.apple assertions=drafts.sync.version-authoritative
    func testWatchChatDTOReadsDraftCiphertextWithBothActualAPIDecoderAndRawTransportKeys() throws {
        let json = #"{"id":"public-draft","messages_v":0,"draft_v":4,"encrypted_draft_md":"ciphertext","encrypted_draft_preview":"preview-ciphertext"}"#
        for convertKeys in [false, true] {
            let decoder = JSONDecoder()
            if convertKeys { decoder.keyDecodingStrategy = .convertFromSnakeCase }
            let dto = try decoder.decode(WatchChatDTO.self, from: Data(json.utf8))
            XCTAssertEqual(dto.encryptedDraftMD, "ciphertext")
            XCTAssertEqual(dto.encryptedDraftPreview, "preview-ciphertext")
            XCTAssertEqual(dto.draftV, 4)
        }
    }
}

extension WatchChatRuntimeTests {
    // contract-test: supporting surface=gui.apple assertions=apple-watch.chats.input-actions
    func testWatchComposerTextDoesNotReplaceMicrophoneAndBusyAudioIsExclusive() {
        let typed = WatchComposerControlPolicy(busy: false, callOwnsAudio: false, hasRecordingDraft: false, hasText: true)
        XCTAssertTrue(typed.canRecord)
        XCTAssertTrue(typed.canSend)
        XCTAssertTrue(typed.canEdit)
        let call = WatchComposerControlPolicy(busy: false, callOwnsAudio: true, hasRecordingDraft: false, hasText: true)
        XCTAssertFalse(call.canRecord)
        XCTAssertTrue(call.canEdit)
        let attached = WatchComposerControlPolicy(busy: false, callOwnsAudio: false, hasRecordingDraft: true, hasText: false)
        XCTAssertFalse(attached.canRecord)
        XCTAssertFalse(attached.canActivateCall)
        XCTAssertTrue(attached.canSend)
    }

    // contract-test: supporting surface=gui.apple assertions=apple-watch.chats.local-transcription,apple-watch.chats.audio-reply
    func testWatchFinishSealsLocalDraftWithoutUploadThenExplicitSendUsesOneEncryptedAudioTurn() async throws {
        let directory = temporaryDirectory()
        defer { try? FileManager.default.removeItem(at: directory) }
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
        let audio = directory.appendingPathComponent("synthetic.m4a")
        let bytes = Data([12, 34, 56, 78])
        try bytes.write(to: audio)
        let chat = Self.chat(id: "chat-a", title: "Synthetic", lastMessageAt: "1800000000")
        let cache = WatchChatOfflineCache(directory: directory)
        try await cache.saveSnapshot(WatchChatSnapshot(chats: [chat], messagesByChatId: [:], savedAt: Date()))
        let api = FakeWatchChatAPI(uploadedAudio: Self.uploadedAudio())
        let socket = FakeWatchChatSyncSocket()
        let crypto = FakeWatchChatCrypto()
        let transcriber = WatchDraftTranscriberProbe(text: "Local editable words")
        let runtime = WatchChatRuntime(api: api, cache: cache, crypto: crypto, syncSocket: socket,
            syncSession: WatchSyncSession(sessionId: "synthetic", token: nil), recordingTranscriber: transcriber)
        await runtime.loadCachedSnapshot()
        runtime.selectedChatId = chat.id
        runtime.updateComposerDraft("Existing text", chatId: chat.id)
        let prepared = await runtime.prepareRecordingDraft(fileURL: audio, duration: 1, attachAudio: true)
        XCTAssertTrue(prepared)
        XCTAssertEqual(runtime.composerDrafts[chat.id], "Existing text\nLocal editable words")
        XCTAssertTrue(runtime.hasSelectedRecordingDraft)
        XCTAssertTrue(api.uploadedAudioRequests.isEmpty)
        XCTAssertTrue(api.transcribedAudioIds.isEmpty)
        XCTAssertTrue(socket.sentTurns.isEmpty)
        let snapshot = await cache.loadSnapshot()
        let sealed = try XCTUnwrap(snapshot.recordingDrafts.first)
        let persisted = String(decoding: try JSONEncoder().encode(snapshot), as: UTF8.self)
        XCTAssertFalse(persisted.contains("Local editable words"))
        XCTAssertFalse(persisted.contains("Existing text"))
        let opened = try await crypto.decryptDraft(sealed.encryptedPayload)
        let payload = try JSONDecoder().decode(WatchRecordingDraftPayload.self, from: Data(opened.utf8))
        XCTAssertEqual(payload.audio, bytes)
        XCTAssertEqual(payload.transcript, "Local editable words")
        let relaunched = WatchChatRuntime(api: api, cache: cache, crypto: crypto, syncSocket: nil,
            recordingTranscriber: transcriber)
        await relaunched.loadCachedSnapshot()
        relaunched.selectedChatId = chat.id
        XCTAssertTrue(relaunched.hasSelectedRecordingDraft)
        XCTAssertEqual(relaunched.composerDrafts[chat.id], "Existing text\nLocal editable words")
        let accepted = await runtime.sendText("Edited text")
        XCTAssertTrue(accepted)
        XCTAssertEqual(api.uploadedAudioRequests.count, 1)
        XCTAssertTrue(api.transcribedAudioIds.isEmpty, "Local transcription must not silently run server STT")
        XCTAssertEqual(socket.sentTurns.count, 1)
        let turn = try XCTUnwrap(socket.sentTurns.first)
        let inference = try XCTUnwrap(JSONSerialization.jsonObject(with: turn.inferenceJSON) as? [String: Any])
        let message = try XCTUnwrap(inference["message"] as? [String: Any])
        let content = try XCTUnwrap(message["content"] as? String)
        XCTAssertTrue(content.hasPrefix("Edited text\n"))
        XCTAssertEqual(content.components(separatedBy: "watch-audio-embed").count - 1, 1)
        XCTAssertFalse(runtime.hasSelectedRecordingDraft)
        let afterSend = await cache.loadSnapshot()
        XCTAssertTrue(afterSend.recordingDrafts.isEmpty)
    }

    // contract-test: supporting surface=gui.apple assertions=apple-watch.chats.local-transcription
    func testWatchLocalFailurePreservesDraftAndRecordingWithoutNetworkFallback() async throws {
        let directory = temporaryDirectory()
        defer { try? FileManager.default.removeItem(at: directory) }
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
        let audio = directory.appendingPathComponent("synthetic.m4a")
        try Data([1]).write(to: audio)
        let chat = Self.chat(id: "chat-a", title: "Synthetic", lastMessageAt: "1800000000")
        let cache = WatchChatOfflineCache(directory: directory)
        try await cache.saveSnapshot(WatchChatSnapshot(chats: [chat], messagesByChatId: [:], savedAt: Date()))
        let api = FakeWatchChatAPI()
        let transcriber = WatchDraftTranscriberProbe(text: "", fail: true)
        let runtime = WatchChatRuntime(api: api, cache: cache, crypto: FakeWatchChatCrypto(), syncSocket: nil,
            recordingTranscriber: transcriber)
        await runtime.loadCachedSnapshot()
        runtime.selectedChatId = chat.id
        runtime.updateComposerDraft("Keep exactly", chatId: chat.id)
        let prepared = await runtime.prepareRecordingDraft(fileURL: audio, duration: 1, attachAudio: true)
        XCTAssertFalse(prepared)
        XCTAssertEqual(runtime.composerDrafts[chat.id], "Keep exactly")
        XCTAssertTrue(runtime.recordingDrafts.isEmpty)
        XCTAssertTrue(FileManager.default.fileExists(atPath: audio.path), "The view retains the same recording for retry")
        XCTAssertTrue(api.uploadedAudioRequests.isEmpty)
        XCTAssertTrue(api.transcribedAudioIds.isEmpty)
    }

    // contract-test: supporting surface=gui.apple assertions=apple-watch.chats.local-transcription,apple-watch.guest.account-isolation
    func testWatchCanceledLocalTranscriptionCannotAppendAfterAccountStops() async throws {
        let directory = temporaryDirectory()
        defer { try? FileManager.default.removeItem(at: directory) }
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
        let audio = directory.appendingPathComponent("synthetic.m4a")
        try Data([1]).write(to: audio)
        let chat = Self.chat(id: "chat-a", title: "Synthetic", lastMessageAt: "1800000000")
        let cache = WatchChatOfflineCache(directory: directory)
        try await cache.saveSnapshot(WatchChatSnapshot(chats: [chat], messagesByChatId: [:], savedAt: Date()))
        let transcriber = WatchDraftTranscriberProbe(text: "Late result", suspended: true)
        let runtime = WatchChatRuntime(api: FakeWatchChatAPI(), cache: cache, crypto: FakeWatchChatCrypto(),
            syncSocket: nil, recordingTranscriber: transcriber)
        await runtime.loadCachedSnapshot()
        runtime.selectedChatId = chat.id
        runtime.updateComposerDraft("Keep exactly", chatId: chat.id)
        let task = Task { await runtime.prepareRecordingDraft(fileURL: audio, duration: 1, attachAudio: true) }
        await transcriber.waitUntilStarted()
        runtime.stopRealtimeSync()
        await runtime.cancelRecordingDraftPreparation()
        let prepared = await task.value
        XCTAssertFalse(prepared)
        XCTAssertEqual(runtime.composerDrafts[chat.id], "Keep exactly")
        XCTAssertTrue(runtime.recordingDrafts.isEmpty)
    }

    // contract-test: supporting surface=gui.apple assertions=apple-watch.chats.input-actions
    func testWatchPhoneRequiresPhysicalRouteAndCallTypingNeverUsesOrdinaryInference() async throws {
        let adapter = WatchCallActionAdapter()
        var starts = 0
        var typed = [String]()
        var muted: Bool?
        adapter.configure(projection: .init(phase: .ready), start: { _, _ in starts += 1 },
            sendText: { typed.append($0); return "typed-id" }, setMuted: { muted = $0 }, hangup: {}, invalidate: {})
        let context = WatchChatRequestContext(accountID: nil, profile: ServerProfile.current(),
            accountGeneration: WatchChatAccountLifecycle.generation)
        do { try await adapter.activate(context: context, chatID: "chat-a"); XCTFail("Simulator cannot establish physical networking eligibility") }
        catch {}
        XCTAssertEqual(starts, 0)
        adapter.update(.init(phase: .live, chatID: "chat-a", physicalRouteVerified: true))
        let routed = try await adapter.sendText("Typed during call", chatID: "chat-a")
        XCTAssertEqual(routed, "typed-id")
        XCTAssertEqual(typed, ["Typed during call"])
        let otherChat = try await adapter.sendText("Other chat", chatID: "chat-b")
        XCTAssertNil(otherChat)
        await adapter.toggleMuted()
        XCTAssertEqual(muted, true)
        await adapter.invalidate()
        adapter.update(.init(phase: .live, chatID: "chat-a", physicalRouteVerified: true))
        XCTAssertEqual(adapter.projection.phase, .unavailable, "Late call events cannot revive an invalidated account")
    }
}

private actor WatchDraftTranscriberProbe: WatchRecordingDraftTranscribing {
    let text: String
    let fail: Bool
    let suspended: Bool
    private var started = false
    private var startWaiter: CheckedContinuation<Void, Never>?
    private var resultWaiter: CheckedContinuation<String, Error>?

    init(text: String, fail: Bool = false, suspended: Bool = false) {
        self.text = text; self.fail = fail; self.suspended = suspended
    }
    func transcribe(fileURL: URL) async throws -> String {
        started = true; startWaiter?.resume(); startWaiter = nil
        if fail { throw WatchComposerActionError.localTranscriptionUnavailable }
        if suspended { return try await withCheckedThrowingContinuation { resultWaiter = $0 } }
        return text
    }
    func waitUntilStarted() async {
        if started { return }
        await withCheckedContinuation { startWaiter = $0 }
    }
    func cancel() async {
        resultWaiter?.resume(throwing: CancellationError()); resultWaiter = nil
    }
}

extension WatchChatRuntimeTests {
    // contract-test: supporting surface=gui.apple assertions=apple-watch.chats.local-transcription
    func testRecordingDraftCancelAtSaveBarrierCannotPersistCandidateOrOverwriteNewerDraft() async throws {
        for editsNewerDraft in [false, true] {
            let directory = temporaryDirectory()
            defer { try? FileManager.default.removeItem(at: directory) }
            try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
            let audio = directory.appendingPathComponent("synthetic.m4a")
            try Data([1]).write(to: audio)
            let probe = WatchSnapshotSaveProbe()
            let cache = WatchChatOfflineCache(directory: directory, beforeSnapshotCommit: { try await probe.beforeCommit() })
            let crypto = FakeWatchChatCrypto()
            let chat = Self.chat(id: "chat-a", title: "Synthetic", lastMessageAt: "1800000000")
            try await cache.saveSnapshot(WatchChatSnapshot(chats: [chat], messagesByChatId: [:], savedAt: Date()))
            let runtime = WatchChatRuntime(api: FakeWatchChatAPI(), cache: cache, crypto: crypto, syncSocket: nil,
                recordingTranscriber: WatchDraftTranscriberProbe(text: "Candidate words"))
            await runtime.loadCachedSnapshot()
            runtime.selectedChatId = chat.id
            runtime.updateComposerDraft("Original draft", chatId: chat.id)
            await runtime.leaveChat()
            runtime.selectedChatId = chat.id
            await probe.holdNext()
            let operation = Task { await runtime.prepareRecordingDraft(fileURL: audio, duration: 1, attachAudio: true) }
            await probe.waitUntilHeld()
            XCTAssertFalse(runtime.hasSelectedRecordingDraft, "Uncommitted state must never enter the editor")
            XCTAssertEqual(runtime.composerDrafts[chat.id], "Original draft")
            if editsNewerDraft { runtime.updateComposerDraft("Newer draft", chatId: chat.id) }
            await runtime.cancelRecordingDraftPreparation()
            await probe.release()
            let result = await operation.value
            XCTAssertFalse(result)
            XCTAssertTrue(runtime.recordingDrafts.isEmpty)
            XCTAssertEqual(runtime.composerDrafts[chat.id], editsNewerDraft ? "Newer draft" : "Original draft")
            await runtime.leaveChat()
            let persisted = await cache.loadSnapshot()
            XCTAssertTrue(persisted.recordingDrafts.isEmpty)
            let sealed = try XCTUnwrap(persisted.encryptedDrafts[chat.id]?.encryptedMarkdown)
            let text = try await crypto.decryptDraft(sealed)
            XCTAssertEqual(text, editsNewerDraft ? "Newer draft" : "Original draft")
        }
    }

    // contract-test: supporting surface=gui.apple assertions=apple-watch.chats.audio-reply,apple-watch.chats.local-transcription
    func testFirstOutboxSaveFailuresKeepRecordingAndDraftRecoverableAndDoNotAcceptSend() async throws {
        let directory = temporaryDirectory()
        defer { try? FileManager.default.removeItem(at: directory) }
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
        let audio = directory.appendingPathComponent("synthetic.m4a")
        try Data([1, 2]).write(to: audio)
        let probe = WatchSnapshotSaveProbe()
        let cache = WatchChatOfflineCache(directory: directory, beforeSnapshotCommit: { try await probe.beforeCommit() })
        let crypto = FakeWatchChatCrypto()
        let chat = Self.chat(id: "chat-a", title: "Synthetic", lastMessageAt: "1800000000")
        try await cache.saveSnapshot(WatchChatSnapshot(chats: [chat], messagesByChatId: [:], savedAt: Date()))
        let socket = FakeWatchChatSyncSocket()
        let api = FakeWatchChatAPI(uploadedAudio: Self.uploadedAudio())
        let runtime = WatchChatRuntime(api: api, cache: cache, crypto: crypto, syncSocket: socket,
            syncSession: WatchSyncSession(sessionId: "synthetic", token: nil),
            recordingTranscriber: WatchDraftTranscriberProbe(text: "Recorded words"))
        await runtime.loadCachedSnapshot(); runtime.selectedChatId = chat.id
        runtime.updateComposerDraft("Keep", chatId: chat.id)
        let prepared = await runtime.prepareRecordingDraft(fileURL: audio, duration: 1, attachAudio: true)
        XCTAssertTrue(prepared)
        await probe.failNext(2)
        let accepted = await runtime.sendText(runtime.composerDrafts[chat.id] ?? "")
        XCTAssertFalse(accepted, "An in-memory prepared turn is not durable acceptance")
        XCTAssertTrue(runtime.hasSelectedRecordingDraft)
        XCTAssertEqual(runtime.composerDrafts[chat.id], "Keep\nRecorded words")
        XCTAssertTrue(socket.sentTurns.isEmpty)
        XCTAssertTrue(runtime.selectedMessages.allSatisfy { !$0.isPending })
        let persisted = await cache.loadSnapshot()
        XCTAssertEqual(persisted.recordingDrafts.count, 1)
        XCTAssertTrue(persisted.pendingTextSends.isEmpty)
        let relaunched = WatchChatRuntime(api: api, cache: cache, crypto: crypto, syncSocket: nil)
        await relaunched.loadCachedSnapshot(); relaunched.selectedChatId = chat.id
        XCTAssertTrue(relaunched.hasSelectedRecordingDraft)
        XCTAssertEqual(relaunched.composerDrafts[chat.id], "Keep\nRecorded words")
    }

    // contract-test: supporting surface=gui.apple assertions=apple-watch.chats.local-transcription
    func testTextOnlyRecordingFinishPreservesDraftWithoutAttachingOrSendingAudio() async throws {
        let directory = temporaryDirectory()
        defer { try? FileManager.default.removeItem(at: directory) }
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
        let audio = directory.appendingPathComponent("synthetic.m4a")
        try Data([1]).write(to: audio)
        let cache = WatchChatOfflineCache(directory: directory)
        let chat = Self.chat(id: "chat-a", title: "Synthetic", lastMessageAt: "1800000000")
        try await cache.saveSnapshot(WatchChatSnapshot(chats: [chat], messagesByChatId: [:], savedAt: Date()))
        let api = FakeWatchChatAPI()
        let runtime = WatchChatRuntime(api: api, cache: cache, crypto: FakeWatchChatCrypto(), syncSocket: nil,
            recordingTranscriber: WatchDraftTranscriberProbe(text: "Dictated words"))
        await runtime.loadCachedSnapshot(); runtime.selectedChatId = chat.id
        runtime.updateComposerDraft("Original", chatId: chat.id)
        let prepared = await runtime.prepareRecordingDraft(fileURL: audio, duration: 1, attachAudio: false)
        XCTAssertTrue(prepared)
        XCTAssertEqual(runtime.composerDrafts[chat.id], "Original\nDictated words")
        XCTAssertFalse(runtime.hasSelectedRecordingDraft)
        let snapshot = await cache.loadSnapshot()
        XCTAssertTrue(snapshot.recordingDrafts.isEmpty)
        XCTAssertTrue(snapshot.pendingTextSends.isEmpty)
        XCTAssertTrue(api.uploadedAudioRequests.isEmpty)
        XCTAssertTrue(api.transcribedAudioIds.isEmpty)
    }

    // contract-test: supporting surface=gui.apple assertions=apple-watch.chats.input-actions
    func testWatchRecordingLeaseCannotReleaseLiveCallOrAllowOverlappingCapture() throws {
        let ownership = WatchAudioOwnership()
        let call = try ownership.acquire(owner: .liveCall)
        XCTAssertThrowsError(try ownership.acquire(owner: .recording))
        let stale = WatchAudioOwnership.Lease(id: UUID(), owner: .recording)
        XCTAssertFalse(ownership.isCurrent(stale))
        XCTAssertFalse(ownership.release(stale))
        XCTAssertTrue(ownership.isCurrent(call))
        XCTAssertTrue(ownership.release(call))
        let recording = try ownership.acquire(owner: .recording)
        XCTAssertThrowsError(try ownership.acquire(owner: .liveCall))
        XCTAssertFalse(ownership.release(call))
        XCTAssertTrue(ownership.isCurrent(recording))
        XCTAssertTrue(ownership.release(recording))
    }
}

private actor WatchSnapshotSaveProbe {
    private var hold = false
    private var held = false
    private var failures = 0
    private var heldWaiter: CheckedContinuation<Void, Never>?
    private var releaseWaiter: CheckedContinuation<Void, Never>?
    func holdNext() { hold = true; held = false }
    func failNext(_ count: Int) { failures = count }
    func beforeCommit() async throws {
        if failures > 0 { failures -= 1; throw CocoaError(.fileWriteOutOfSpace) }
        if hold {
            hold = false; held = true
            heldWaiter?.resume(); heldWaiter = nil
            await withCheckedContinuation { releaseWaiter = $0 }
        }
    }
    func waitUntilHeld() async {
        if held { return }
        await withCheckedContinuation { heldWaiter = $0 }
    }
    func release() { releaseWaiter?.resume(); releaseWaiter = nil }
}

extension WatchChatRuntimeTests {
    private func voiceHookFixture(directory: URL) async throws -> (runtime: WatchChatRuntime, cache: WatchChatOfflineCache,
        socket: FakeWatchChatSyncSocket, context: WatchChatRequestContext, scope: NativeVoiceCallScope,
        crypto: FakeWatchChatCrypto) {
        let chat = Self.chat(id: "voice-chat", title: "Synthetic", lastMessageAt: "1800000000")
        let cache = WatchChatOfflineCache(directory: directory)
        let owner = "synthetic-watch-call-owner"
        try await cache.saveSnapshot(WatchChatSnapshot(chats: [chat], messagesByChatId: [:], savedAt: Date(),
            accountID: owner, serverScope: WatchChatRuntime.currentServerScope))
        let socket = FakeWatchChatSyncSocket()
        let crypto = FakeWatchChatCrypto()
        let runtime = WatchChatRuntime(currentUserId: owner, api: FakeWatchChatAPI(), cache: cache,
            crypto: crypto, syncSocket: socket, syncSession: WatchSyncSession(sessionId: "synthetic", token: "synthetic"))
        await runtime.loadCachedSnapshot(); runtime.selectedChatId = chat.id
        let context = try runtime.voiceCallContext(for: chat.id)
        let scope = NativeVoiceCallScope(accountID: owner, profileID: context.profile.id,
            workspaceGeneration: UUID(), chatID: chat.id, mateCategory: "general_knowledge")
        return (runtime, cache, socket, context, scope, crypto)
    }

    // contract-test: supporting surface=gui.apple assertions=apple-watch.chats.input-actions
    func testCanonicalWatchActivationRequiresRealCallLeaseAndUsesExistingSocketOnce() async throws {
        let directory = temporaryDirectory()
        defer { try? FileManager.default.removeItem(at: directory) }
        let fixture = try await voiceHookFixture(directory: directory)
        do { try await fixture.runtime.activateVoiceCallCanonicalTransport(context: fixture.context); XCTFail("No capture owner") }
        catch {}
        XCTAssertNil(fixture.socket.connectedSession)
        let lease = try WatchAudioOwnership.shared.acquire(owner: .liveCall)
        defer { WatchAudioOwnership.shared.release(lease) }
        fixture.socket.becomesReadyOnConnect = true
        try await fixture.runtime.activateVoiceCallCanonicalTransport(context: fixture.context)
        XCTAssertEqual(fixture.socket.connectedSession?.sessionId, "synthetic")
        XCTAssertTrue(fixture.socket.sentTurns.isEmpty)
        // Supporting adapter-state proof only; this fake socket and lease do not
        // prove actual Watch audio activation or physical network eligibility.
    }

    // contract-test: supporting surface=gui.apple assertions=apple-watch.chats.input-actions
    func testCallTypedWireSuccessRetainsDraftUntilExactFinalEchoAndPublishesWithoutPlaintextCache() async throws {
        let directory = temporaryDirectory()
        defer { try? FileManager.default.removeItem(at: directory) }
        let f = try await voiceHookFixture(directory: directory)
        let id = NativeVoiceCallMessageID.make()
        var typedCount = 0
        f.runtime.callActions.configure(projection: .init(phase: .live, chatID: f.scope.chatID,
            callID: "call-1", scopeGeneration: f.scope.workspaceGeneration, physicalRouteVerified: true),
            start: { _, _ in }, sendText: { _ in typedCount += 1; return id }, setMuted: { _ in }, hangup: {}, invalidate: {})
        f.runtime.updateComposerDraft("Typed source", chatId: f.scope.chatID)
        let wireAccepted = await f.runtime.sendText("Typed source")
        XCTAssertFalse(wireAccepted, "Legacy composer must not clear after wire success")
        XCTAssertEqual(f.runtime.composerDrafts[f.scope.chatID], "Typed source")
        XCTAssertTrue(f.runtime.hasPendingVoiceCallTypedDraft)
        let duplicate = await f.runtime.sendText("Typed source")
        XCTAssertFalse(duplicate)
        XCTAssertEqual(typedCount, 1)
        let echo = NativeVoiceCallTranscript(callID: "call-1", messageID: id, role: .user,
            text: "Typed source", final: true, interrupted: false, userMessageID: nil, createdAt: 1800000001,
            modelName: nil, mateCategory: nil, mateName: nil)
        try f.runtime.voiceCallPublishTranscript(echo, scope: f.scope, context: f.context)
        await f.runtime.waitForVoiceCallDraftSettlement()
        XCTAssertEqual(f.runtime.composerDrafts[f.scope.chatID], "")
        XCTAssertFalse(f.runtime.hasPendingVoiceCallTypedDraft)
        XCTAssertEqual(f.runtime.selectedMessages.first?.id, id)
        XCTAssertEqual(f.runtime.selectedMessages.first?.content, "Typed source")
        XCTAssertFalse(f.runtime.selectedMessages.first?.isPending ?? true)
        let saved = await f.cache.loadSnapshot()
        XCTAssertNil(saved.encryptedDrafts[f.scope.chatID]?.encryptedMarkdown)
        XCTAssertTrue(saved.messagesByChatId[f.scope.chatID, default: []].isEmpty,
            "Transient call text is never a second cache/persistence writer")
        XCTAssertFalse(String(decoding: try JSONEncoder().encode(saved), as: UTF8.self).contains("Typed source"))
        XCTAssertTrue(f.socket.sentTurns.isEmpty, "No ordinary inference")
    }

    // contract-test: supporting surface=gui.apple assertions=apple-watch.chats.input-actions
    func testFinalEchoBeforeWireReturnStillSettlesAfterImmediateCallEnd() async throws {
        let directory = temporaryDirectory()
        defer { try? FileManager.default.removeItem(at: directory) }
        let f = try await voiceHookFixture(directory: directory)
        let id = NativeVoiceCallMessageID.make()
        f.runtime.callActions.configure(projection: .init(phase: .live, chatID: f.scope.chatID,
            callID: "call-1", scopeGeneration: f.scope.workspaceGeneration, physicalRouteVerified: true),
            start: { _, _ in }, sendText: { text in
                try f.runtime.voiceCallPublishTranscript(NativeVoiceCallTranscript(callID: "call-1", messageID: id,
                    role: .user, text: text, final: true, interrupted: false, userMessageID: nil,
                    createdAt: 1800000001, modelName: nil, mateCategory: nil, mateName: nil),
                    scope: f.scope, context: f.context)
                f.runtime.callActions.update(.init(phase: .ended, chatID: f.scope.chatID,
                    callID: "call-1", scopeGeneration: f.scope.workspaceGeneration, physicalRouteVerified: true))
                return id
            }, setMuted: { _ in }, hangup: {}, invalidate: {})
        f.runtime.updateComposerDraft("Early final source", chatId: f.scope.chatID)
        _ = await f.runtime.sendText("Early final source")
        await f.runtime.waitForVoiceCallDraftSettlement()
        XCTAssertEqual(f.runtime.composerDrafts[f.scope.chatID], "")
        XCTAssertFalse(f.runtime.hasPendingVoiceCallTypedDraft)
        XCTAssertTrue(f.socket.sentTurns.isEmpty)
    }

    // contract-test: supporting surface=gui.apple assertions=apple-watch.chats.input-actions
    func testCallTypedRejectionDisconnectAndStaleEchoPreserveOwnedOrNewerDraft() async throws {
        for scenario in ["reject", "disconnect", "newer", "early-reject"] {
            let directory = temporaryDirectory()
            defer { try? FileManager.default.removeItem(at: directory) }
            let f = try await voiceHookFixture(directory: directory)
            let id = NativeVoiceCallMessageID.make()
            f.runtime.callActions.configure(projection: .init(phase: .live, chatID: f.scope.chatID,
                callID: "call-1", scopeGeneration: f.scope.workspaceGeneration, physicalRouteVerified: true),
                start: { _, _ in }, sendText: { _ in
                    if scenario == "early-reject" { f.runtime.voiceCallRejectTyped(messageID: id, scope: f.scope, context: f.context) }
                    return id
                }, setMuted: { _ in }, hangup: {}, invalidate: {})
            f.runtime.updateComposerDraft("Retain source", chatId: f.scope.chatID)
            _ = await f.runtime.sendText("Retain source")
            if scenario == "newer" { f.runtime.updateComposerDraft("Newer edit", chatId: f.scope.chatID) }
            if scenario == "disconnect" {
                f.runtime.callActions.update(.init(phase: .failed, chatID: f.scope.chatID,
                    callID: "call-1", scopeGeneration: f.scope.workspaceGeneration, physicalRouteVerified: true))
            } else { f.runtime.voiceCallRejectTyped(messageID: id, scope: f.scope, context: f.context) }
            XCTAssertFalse(f.runtime.hasPendingVoiceCallTypedDraft)
            let stale = NativeVoiceCallTranscript(callID: "old-call", messageID: id, role: .user,
                text: "Retain source", final: true, interrupted: false, userMessageID: nil, createdAt: 1800000001,
                modelName: nil, mateCategory: nil, mateName: nil)
            XCTAssertThrowsError(try f.runtime.voiceCallPublishTranscript(stale, scope: f.scope, context: f.context))
            XCTAssertEqual(f.runtime.composerDrafts[f.scope.chatID], scenario == "newer" ? "Newer edit" : "Retain source")
            XCTAssertTrue(f.socket.sentTurns.isEmpty)
        }
    }
}

extension WatchChatRuntimeTests {
    private func artifactFrame(scope: NativeVoiceCallScope, status: String = "finished", content: String? = "{\"title\":\"Synthetic artifact\",\"code\":\"print(42)\"}") -> NativeVoiceCallFrame {
        var payload: NativeVoiceCallFrame = ["embed_id": .string("watch-call-artifact"), "type": .string("code"),
            "chat_id": .string(scope.chatID), "message_id": .string("assistant-artifact"),
            "app_id": .string("code"), "skill_id": .string("run"), "user_id": .string(scope.accountID), "status": .string(status), "version_number": .number(1)]
        if let content { payload["content"] = .string(content) }
        return ["type": .string("voice_embed"), "call_id": .string("call-1"),
            "function_call_id": .string("function-artifact"), "assistant_message_id": .string("assistant-artifact"),
            "user_message_id": .string("user-artifact"), "payload": .object(payload)]
    }

    private func configureArtifactCall(_ runtime: WatchChatRuntime, scope: NativeVoiceCallScope) {
        runtime.callActions.configure(projection: .init(phase: .live, chatID: scope.chatID, callID: "call-1",
            scopeGeneration: scope.workspaceGeneration, physicalRouteVerified: true), start: { _, _ in },
            sendText: { _ in throw NativeVoiceCallError.invalidState }, setMuted: { _ in }, hangup: {}, invalidate: {})
    }

    private func artifactReceipt(type: String, payload: [String: Any]) throws -> [String: Any] {
        if type == "store_embed" {
            return ["request_id": try XCTUnwrap(payload["request_id"]), "embed_id": try XCTUnwrap(payload["embed_id"]),
                "canonical_source": "head", "canonical_digest": CanonicalEmbedStorageReceipts.digest(try XCTUnwrap(payload["encrypted_content"] as? String))]
        }
        let count = try XCTUnwrap(payload["keys"] as? [[String: Any]]).count
        return ["request_id": try XCTUnwrap(payload["request_id"]), "created_count": count, "requested_count": count, "failed_count": 0]
    }

    // contract-test: supporting surface=gui.apple assertions=video-call.chat.skill-integration,video-call.chat.transcripts,storage.privacy.ciphertext-boundary
    func testWatchCallArtifactCommitsBeforeSpeechAndProcessingNeverCreatesTranscriptRow() async throws {
        let directory = temporaryDirectory()
        defer { try? FileManager.default.removeItem(at: directory) }
        let f = try await voiceHookFixture(directory: directory)
        configureArtifactCall(f.runtime, scope: f.scope)
        f.socket.becomesReadyOnConnect = true
        f.socket.connect(session: .init(sessionId: "synthetic", token: "synthetic"), syncState: WatchSyncClientState(clientChatVersions: [:], clientChatIds: [], clientSuggestionsCount: 0, clientEmbedIds: []))
        f.socket.artifactRequest = { type, payload in
            if type == "store_embed" {
                XCTAssertEqual(payload["chat_id"] as? String, f.scope.chatID)
                XCTAssertEqual(payload["app_id"] as? String, "code")
                XCTAssertEqual(payload["skill_id"] as? String, "run")
            }
            return try self.artifactReceipt(type: type, payload: payload)
        }
        let processing = try f.runtime.voiceCallAdmitArtifact(frame: artifactFrame(scope: f.scope, status: "processing"), scope: f.scope, context: f.context)
        let preview = try await f.runtime.voiceCallPersistArtifact(processing, context: f.context)
        XCTAssertNil(preview)
        XCTAssertTrue(f.socket.artifactRequests.isEmpty)
        XCTAssertEqual(f.crypto.artifactPreparationCount, 0)
        XCTAssertTrue(f.runtime.selectedMessages.isEmpty)
        let admission = try f.runtime.voiceCallAdmitArtifact(frame: artifactFrame(scope: f.scope), scope: f.scope, context: f.context)
        let result = try await f.runtime.voiceCallPersistArtifact(admission, context: f.context)
        let committed = try XCTUnwrap(result)
        XCTAssertEqual(committed.reference["embed_id"]?.string, "watch-call-artifact")
        XCTAssertEqual(f.socket.artifactRequests.map(\.type), ["store_embed", "store_embed_keys"])
        XCTAssertTrue(f.runtime.selectedMessages.isEmpty, "Canonical outbox owns the single assistant transcript")
        let saved = await f.cache.loadSnapshot()
        XCTAssertTrue(saved.pendingCompletions.isEmpty)
        XCTAssertTrue(saved.messagesByChatId[f.scope.chatID, default: []].isEmpty)
        XCTAssertFalse(String(decoding: try JSONEncoder().encode(saved), as: UTF8.self).contains("print(42)"))
        XCTAssertTrue(f.socket.sentTurns.isEmpty)
    }

    // contract-test: supporting surface=gui.apple assertions=video-call.chat.skill-integration,storage.privacy.ciphertext-boundary
    func testWatchCallLostHeadOrWrapperReceiptRetriesOriginalDurableCiphertextAndIDs() async throws {
        for failure in ["store_embed", "store_embed_keys"] {
            let directory = temporaryDirectory()
            defer { try? FileManager.default.removeItem(at: directory) }
            let f = try await voiceHookFixture(directory: directory)
            configureArtifactCall(f.runtime, scope: f.scope)
            f.socket.becomesReadyOnConnect = true
            f.socket.connect(session: .init(sessionId: "synthetic", token: "synthetic"), syncState: WatchSyncClientState(clientChatVersions: [:], clientChatIds: [], clientSuggestionsCount: 0, clientEmbedIds: []))
            var failOnce = true
            f.socket.artifactRequest = { type, payload in
                if type == failure, failOnce { failOnce = false; throw WatchChatRuntimeError.socketUnavailable }
                return try self.artifactReceipt(type: type, payload: payload)
            }
            let admission = try f.runtime.voiceCallAdmitArtifact(frame: artifactFrame(scope: f.scope), scope: f.scope, context: f.context)
            do { _ = try await f.runtime.voiceCallPersistArtifact(admission, context: f.context); XCTFail("Lost receipt is not committed") }
            catch WatchChatRuntimeError.socketUnavailable { }
            let retained = await f.cache.loadSnapshot()
            XCTAssertEqual(retained.pendingCompletions.count, 1)
            XCTAssertFalse(String(decoding: try JSONEncoder().encode(retained), as: UTF8.self).contains("print(42)"))
            let retryAdmission = try f.runtime.voiceCallAdmitArtifact(frame: artifactFrame(scope: f.scope), scope: f.scope, context: f.context)
            let retried = try await f.runtime.voiceCallPersistArtifact(retryAdmission, context: f.context)
            XCTAssertNotNil(retried)
            XCTAssertEqual(f.crypto.artifactPreparationCount, 1)
            let headRequests = f.socket.artifactRequests.filter { $0.type == "store_embed" }
            XCTAssertEqual(headRequests.first?.payload, headRequests.last?.payload)
            let keys = f.socket.artifactRequests.filter { $0.type == "store_embed_keys" }
            if failure == "store_embed_keys" { XCTAssertEqual(keys.first?.payload, keys.last?.payload) }
            let count = f.socket.artifactRequests.count
            _ = try await f.runtime.voiceCallPersistArtifact(retryAdmission, context: f.context)
            XCTAssertEqual(f.socket.artifactRequests.count, count, "Duplicate committed delivery does no second write")
            let altered = try f.runtime.voiceCallAdmitArtifact(frame: artifactFrame(scope: f.scope, content: "{\"code\":\"changed\"}"), scope: f.scope, context: f.context)
            do { _ = try await f.runtime.voiceCallPersistArtifact(altered, context: f.context); XCTFail("Conflicting same-version delivery") }
            catch NativeVoiceCallError.invalidResponse { }
        }
    }

    // contract-test: supporting surface=gui.apple assertions=video-call.chat.skill-integration,video-call.chat.transcripts,video-call.chat.fixed-binding
    func testWatchAdmittedArtifactCanPublishOnlyOriginalAssistantAfterHangupAndRejectsReplacement() async throws {
        let directory = temporaryDirectory()
        defer { try? FileManager.default.removeItem(at: directory) }
        let f = try await voiceHookFixture(directory: directory)
        configureArtifactCall(f.runtime, scope: f.scope)
        f.socket.becomesReadyOnConnect = true
        f.socket.connect(session: .init(sessionId: "synthetic", token: "synthetic"), syncState: WatchSyncClientState(clientChatVersions: [:], clientChatIds: [], clientSuggestionsCount: 0, clientEmbedIds: []))
        f.socket.artifactRequest = { type, payload in
            f.runtime.callActions.update(.init(phase: .ended, chatID: f.scope.chatID, callID: "call-1",
                scopeGeneration: f.scope.workspaceGeneration, physicalRouteVerified: true))
            return try self.artifactReceipt(type: type, payload: payload)
        }
        let admission = try f.runtime.voiceCallAdmitArtifact(frame: artifactFrame(scope: f.scope), scope: f.scope, context: f.context)
        let result = try await f.runtime.voiceCallPersistArtifact(admission, context: f.context)
        let committed = try XCTUnwrap(result)
        let reference = try NativeVoiceCallArtifactReference(validating: committed.reference)
        let transcript = NativeVoiceCallTranscript(callID: "call-1", messageID: "assistant-artifact", role: .assistant,
            text: try reference.markdown, final: true, interrupted: false, userMessageID: "user-artifact", createdAt: 1800000001,
            modelName: nil, mateCategory: nil, mateName: nil, embedReferences: [reference])
        XCTAssertThrowsError(try f.runtime.voiceCallPublishTranscript(transcript, scope: f.scope, context: f.context))
        try f.runtime.voiceCallPublishTranscript(transcript, scope: f.scope, context: f.context, admittedArtifact: admission)
        XCTAssertEqual(f.runtime.selectedMessages.map(\.id), ["assistant-artifact"])
        XCTAssertThrowsError(try f.runtime.voiceCallAdmitArtifact(frame: artifactFrame(scope: f.scope), scope: f.scope, context: f.context))
        f.runtime.callActions.update(.init(phase: .live, chatID: f.scope.chatID, callID: "replacement",
            scopeGeneration: f.scope.workspaceGeneration, physicalRouteVerified: true))
        XCTAssertThrowsError(try f.runtime.voiceCallPublishTranscript(transcript, scope: f.scope, context: f.context, admittedArtifact: admission))
        do { _ = try await f.runtime.voiceCallPersistArtifact(admission, context: f.context); XCTFail("Original capability cannot cross replacement") }
        catch NativeVoiceCallError.scopeChanged { }
        XCTAssertTrue(f.socket.sentTurns.isEmpty)
    }

    // contract-test: supporting surface=gui.apple assertions=video-call.chat.skill-integration,video-call.chat.fixed-binding
    func testWatchCallMismatchedCanonicalHeadOrKeyReceiptNeverReturnsCommittedReference() async throws {
        for corrupt in ["head-digest", "head-source", "keys-count", "replacement"] {
            let directory = temporaryDirectory()
            defer { try? FileManager.default.removeItem(at: directory) }
            let f = try await voiceHookFixture(directory: directory)
            configureArtifactCall(f.runtime, scope: f.scope)
            f.socket.becomesReadyOnConnect = true
            f.socket.connect(session: .init(sessionId: "synthetic", token: "synthetic"), syncState: WatchSyncClientState(clientChatVersions: [:], clientChatIds: [], clientSuggestionsCount: 0, clientEmbedIds: []))
            f.socket.artifactRequest = { type, payload in
                var receipt = try self.artifactReceipt(type: type, payload: payload)
                if type == "store_embed", corrupt == "head-digest" { receipt["canonical_digest"] = "wrong" }
                if type == "store_embed", corrupt == "head-source" { receipt["canonical_source"] = "version_row" }
                if type == "store_embed_keys", corrupt == "keys-count" { receipt["created_count"] = 0 }
                if type == "store_embed_keys", corrupt == "replacement" {
                    f.runtime.callActions.update(.init(phase: .live, chatID: f.scope.chatID, callID: "replacement",
                        scopeGeneration: f.scope.workspaceGeneration, physicalRouteVerified: true))
                }
                return receipt
            }
            let admission = try f.runtime.voiceCallAdmitArtifact(frame: artifactFrame(scope: f.scope), scope: f.scope, context: f.context)
            do { _ = try await f.runtime.voiceCallPersistArtifact(admission, context: f.context); XCTFail("Invalid proof cannot commit") }
            catch { }
            let retained = await f.cache.loadSnapshot()
            XCTAssertEqual(retained.pendingCompletions.count, 1)
            XCTAssertTrue(f.runtime.selectedMessages.isEmpty)
            if corrupt.hasPrefix("head-") { XCTAssertEqual(f.socket.artifactRequests.map(\.type), ["store_embed"]) }
        }
    }

    // contract-test: supporting surface=gui.apple assertions=video-call.chat.skill-integration,video-call.chat.fixed-binding
    func testWatchColdReferenceFetchValidatesEncryptedIdentityAndHydratesWithoutInventingCommitProof() async throws {
        for mismatch in ["none", "chat", "message", "version", "version-boolean", "version-string", "version-zero", "version-fraction", "type", "key"] {
            let directory = temporaryDirectory()
            defer { try? FileManager.default.removeItem(at: directory) }
            let f = try await voiceHookFixture(directory: directory)
            configureArtifactCall(f.runtime, scope: f.scope)
            f.socket.becomesReadyOnConnect = true
            f.socket.connect(session: .init(sessionId: "synthetic", token: "synthetic"), syncState: WatchSyncClientState(clientChatVersions: [:], clientChatIds: [], clientSuggestionsCount: 0, clientEmbedIds: []))
            let full = try WatchCanonicalStorage.object(JSONEncoder().encode(try XCTUnwrap(artifactFrame(scope: f.scope)["payload"]?.object)))
            let chat = try XCTUnwrap(f.runtime.chats.first)
            let prepared = try await f.crypto.prepareEmbedStorage(payload: full, chat: chat, messageID: "assistant-artifact")
            var fetched: [String: Any] = ["embed_id": "watch-call-artifact", "type": try XCTUnwrap(prepared.embed["encrypted_type"]),
                "content": try XCTUnwrap(prepared.embed["encrypted_content"]), "already_encrypted": true, "encryption_mode": "client",
                "user_id": f.scope.accountID, "chat_id": f.scope.chatID,
                "message_id": CanonicalEmbedStorageReceipts.digest("assistant-artifact"), "status": "finished", "version_number": 1,
                "embed_keys": try XCTUnwrap(prepared.keys["keys"]), "embed_keys_has_more_after": false]
            switch mismatch {
            case "chat": fetched["chat_id"] = CanonicalEmbedStorageReceipts.digest("unrelated-chat")
            case "message": fetched["message_id"] = CanonicalEmbedStorageReceipts.digest("unrelated-assistant")
            case "version": fetched["version_number"] = 2
            case "version-boolean": fetched["version_number"] = true
            case "version-string": fetched["version_number"] = "1"
            case "version-zero": fetched["version_number"] = 0
            case "version-fraction": fetched["version_number"] = 1.5
            case "type": fetched["type"] = "sheet"
            case "key": fetched["embed_keys"] = [["encrypted_embed_key": "wrong-key"]]
            default: break
            }
            let response = fetched
            f.socket.artifactRequest = { type, payload in
                XCTAssertEqual(type, "request_embed")
                XCTAssertEqual(payload["embed_id"] as? String, "watch-call-artifact")
                XCTAssertEqual(payload["chat_id"] as? String, f.scope.chatID)
                return response
            }
            let admission = try f.runtime.voiceCallAdmitArtifact(frame: artifactFrame(scope: f.scope, content: nil), scope: f.scope, context: f.context)
            do { _ = try await f.runtime.voiceCallPersistArtifact(admission, context: f.context); XCTFail("A head without genuine provenance cannot use the locked equality confirmation") }
            catch { }
            let row = WatchChatMessage(id: "view-only-probe", chatId: f.scope.chatID, role: .assistant,
                content: "[!](embed:watch-call-artifact)", encryptedContent: nil, embedRefs: nil, createdAt: "1800000001", isPending: false)
            let preview = f.runtime.messageWithHydratedEmbeds(row).embedRefs?.first
            XCTAssertEqual(preview?.data != nil, mismatch == "none", "Only the exact encrypted origin may hydrate")
            XCTAssertTrue(f.runtime.selectedMessages.isEmpty)
            XCTAssertEqual(f.socket.artifactRequests.map(\.type), ["request_embed"])
            let saved = await f.cache.loadSnapshot()
            XCTAssertTrue(saved.pendingCompletions.isEmpty)
        }
    }
}

extension WatchChatRuntimeTests {
    // contract-test: supporting surface=gui.apple assertions=video-call.chat.skill-integration,video-call.chat.fixed-binding,storage.privacy.ciphertext-boundary
    func testWatchColdReferenceReconfirmsFetchedCiphertextAndChatWrapperWithStableRetry() async throws {
        for (failure, version) in [("store_embed", 1), ("store_embed_keys", 1), ("store_embed_keys", 2)] {
            let directory = temporaryDirectory()
            defer { try? FileManager.default.removeItem(at: directory) }
            let f = try await voiceHookFixture(directory: directory)
            configureArtifactCall(f.runtime, scope: f.scope)
            f.socket.becomesReadyOnConnect = true
            f.socket.connect(session: .init(sessionId: "synthetic", token: "synthetic"),
                syncState: WatchSyncClientState(clientChatVersions: [:], clientChatIds: [], clientSuggestionsCount: 0, clientEmbedIds: []))
            let full = try WatchCanonicalStorage.object(JSONEncoder().encode(try XCTUnwrap(artifactFrame(scope: f.scope)["payload"]?.object)))
            let chat = try XCTUnwrap(f.runtime.chats.first)
            let prepared = try await f.crypto.prepareEmbedStorage(payload: full, chat: chat, messageID: "assistant-artifact")
            let ciphertext = try XCTUnwrap(prepared.embed["encrypted_content"] as? String)
            let encryptedType = try XCTUnwrap(prepared.embed["encrypted_type"] as? String)
            let provenance = String(repeating: "a", count: 64)
            let wrappers = try XCTUnwrap(prepared.keys["keys"] as? [[String: Any]])
            let fetched: [String: Any] = ["embed_id": "watch-call-artifact", "type": encryptedType,
                "content": ciphertext, "already_encrypted": true, "encryption_mode": "client",
                "user_id": f.scope.accountID, "chat_id": f.scope.chatID,
                "message_id": CanonicalEmbedStorageReceipts.digest("assistant-artifact"), "status": "finished", "version_number": version,
                "content_hash": provenance, "embed_keys": wrappers, "embed_keys_has_more_after": false]
            var failOnce = true
            f.socket.artifactRequest = { type, payload in
                if type == "request_embed" {
                    XCTAssertEqual(payload["chat_id"] as? String, f.scope.chatID)
                    return fetched
                }
                if type == "store_embed" {
                    XCTAssertEqual(payload["encrypted_content"] as? String, ciphertext)
                    XCTAssertEqual(payload["encrypted_type"] as? String, encryptedType)
                    XCTAssertNil(payload["version_number"], "The locked marker checks version without rewriting the stored column")
                    XCTAssertEqual(payload["content_hash"] as? String, provenance)
                    let guardFields = try XCTUnwrap(payload["canonical_metadata_enrichment"] as? [String: Any])
                    XCTAssertEqual(guardFields["expected_version"] as? Int, version)
                    XCTAssertEqual(guardFields["expected_ciphertext_sha256"] as? String, CanonicalEmbedStorageReceipts.digest(ciphertext))
                    XCTAssertNil(payload["created_at"])
                    XCTAssertNil(payload["updated_at"])
                } else {
                    let posted = try XCTUnwrap(payload["keys"] as? [[String: Any]])
                    XCTAssertEqual(posted.count, 1, "Only the exact original chat wrapper grants association authority")
                    XCTAssertEqual(posted.first?["encrypted_embed_key"] as? String,
                        wrappers.first { $0["key_type"] as? String == "chat" }?["encrypted_embed_key"] as? String)
                }
                if type == failure, failOnce { failOnce = false; throw WatchChatRuntimeError.socketUnavailable }
                return try self.artifactReceipt(type: type, payload: payload)
            }
            var referenceFrame = artifactFrame(scope: f.scope, content: nil)
            var referencePayload = try XCTUnwrap(referenceFrame["payload"]?.object)
            referencePayload["version_number"] = .number(Double(version))
            referenceFrame["payload"] = .object(referencePayload)
            let admission = try f.runtime.voiceCallAdmitArtifact(frame: referenceFrame, scope: f.scope, context: f.context)
            do { _ = try await f.runtime.voiceCallPersistArtifact(admission, context: f.context); XCTFail("Missing exact receipt") }
            catch WatchChatRuntimeError.socketUnavailable { }
            let retained = await f.cache.loadSnapshot()
            XCTAssertEqual(retained.pendingCompletions.count, 1)
            let result = try await f.runtime.voiceCallPersistArtifact(admission, context: f.context)
            XCTAssertNotNil(result)
            XCTAssertEqual(f.crypto.artifactPreparationCount, 1, "Only test setup encrypts; cold hydration never generates replacement ciphertext or wrappers")
            let heads = f.socket.artifactRequests.filter { $0.type == "store_embed" }
            XCTAssertEqual(heads.first?.payload, heads.last?.payload)
            if failure == "store_embed_keys" {
                let keys = f.socket.artifactRequests.filter { $0.type == "store_embed_keys" }
                XCTAssertEqual(keys.first?.payload, keys.last?.payload)
            }
            XCTAssertTrue(f.runtime.selectedMessages.isEmpty)
            XCTAssertTrue(f.socket.sentTurns.isEmpty)
        }
    }
}

extension WatchChatRuntimeTests {
    // contract-test: supporting surface=gui.apple assertions=video-call.chat.skill-integration,video-call.chat.fixed-binding,storage.privacy.ciphertext-boundary
    func testWatchColdLegacyNullAndMissingRevisionReconfirmEffectiveV1WithoutWritingVersionColumn() async throws {
        for legacyShape in ["null", "missing"] {
            for corruptDigest in [false, true] {
                let directory = temporaryDirectory()
                defer { try? FileManager.default.removeItem(at: directory) }
                let f = try await voiceHookFixture(directory: directory)
                configureArtifactCall(f.runtime, scope: f.scope)
                f.socket.becomesReadyOnConnect = true
                f.socket.connect(session: .init(sessionId: "synthetic", token: "synthetic"),
                    syncState: WatchSyncClientState(clientChatVersions: [:], clientChatIds: [], clientSuggestionsCount: 0, clientEmbedIds: []))
                let full = try WatchCanonicalStorage.object(JSONEncoder().encode(try XCTUnwrap(artifactFrame(scope: f.scope)["payload"]?.object)))
                let chat = try XCTUnwrap(f.runtime.chats.first)
                let prepared = try await f.crypto.prepareEmbedStorage(payload: full, chat: chat, messageID: "assistant-artifact")
                let ciphertext = try XCTUnwrap(prepared.embed["encrypted_content"] as? String)
                let encryptedType = try XCTUnwrap(prepared.embed["encrypted_type"] as? String)
                let provenance = String(repeating: "b", count: 64)
                var legacy: [String: Any] = ["embed_id": "watch-call-artifact", "type": encryptedType,
                    "content": ciphertext, "already_encrypted": true, "encryption_mode": "client",
                    "user_id": f.scope.accountID, "chat_id": f.scope.chatID,
                    "message_id": CanonicalEmbedStorageReceipts.digest("assistant-artifact"), "status": "finished",
                    "content_hash": provenance, "embed_keys": try XCTUnwrap(prepared.keys["keys"]), "embed_keys_has_more_after": false]
                if legacyShape == "null" { legacy["version_number"] = NSNull() }
                let fetched = legacy
                f.socket.artifactRequest = { type, payload in
                    if type == "request_embed" { return fetched }
                    if type == "store_embed" {
                        XCTAssertNil(payload["version_number"], "Supplying effective 1 would mismatch the stored legacy null in the equality transaction")
                        XCTAssertEqual(payload["encrypted_content"] as? String, ciphertext)
                        XCTAssertEqual(payload["encrypted_type"] as? String, encryptedType)
                        XCTAssertEqual(payload["content_hash"] as? String, provenance)
                        let marker = try XCTUnwrap(payload["canonical_metadata_enrichment"] as? [String: Any])
                        XCTAssertEqual(marker["expected_version"] as? Int, 1)
                        XCTAssertEqual(marker["expected_ciphertext_sha256"] as? String, CanonicalEmbedStorageReceipts.digest(ciphertext))
                    }
                    var receipt = try self.artifactReceipt(type: type, payload: payload)
                    if type == "store_embed", corruptDigest { receipt["canonical_digest"] = "wrong" }
                    return receipt
                }
                let admission = try f.runtime.voiceCallAdmitArtifact(frame: artifactFrame(scope: f.scope, content: nil), scope: f.scope, context: f.context)
                if corruptDigest {
                    do { _ = try await f.runtime.voiceCallPersistArtifact(admission, context: f.context); XCTFail("Effective v1 never bypasses exact head receipts") }
                    catch CanonicalEmbedStorageReceiptError.invalidHead { }
                    XCTAssertEqual(f.socket.artifactRequests.map(\.type), ["request_embed", "store_embed"])
                    let saved = await f.cache.loadSnapshot()
                    XCTAssertEqual(saved.pendingCompletions.count, 1)
                } else {
                    let result = try await f.runtime.voiceCallPersistArtifact(admission, context: f.context)
                    XCTAssertNotNil(result)
                    XCTAssertEqual(f.socket.artifactRequests.map(\.type), ["request_embed", "store_embed", "store_embed_keys"])
                    let saved = await f.cache.loadSnapshot()
                    XCTAssertTrue(saved.pendingCompletions.isEmpty)
                }
                XCTAssertEqual(f.crypto.artifactPreparationCount, 1, "Only fixture creation encrypts the original legacy record")
                XCTAssertTrue(f.runtime.selectedMessages.isEmpty)
                XCTAssertTrue(f.socket.sentTurns.isEmpty)
            }
        }
    }
}

extension WatchChatRuntimeTests {
    // contract-test: supporting surface=gui.apple assertions=video-call.chat.skill-integration,video-call.chat.transcripts,video-call.chat.fixed-binding
    func testWatchCommittedArtifactSelectionSurvivesAnotherProcessingArtifactInSameAssistantTurn() async throws {
        let directory = temporaryDirectory()
        defer { try? FileManager.default.removeItem(at: directory) }
        let f = try await voiceHookFixture(directory: directory)
        configureArtifactCall(f.runtime, scope: f.scope)
        f.socket.becomesReadyOnConnect = true
        f.socket.connect(session: .init(sessionId: "synthetic", token: "synthetic"),
            syncState: WatchSyncClientState(clientChatVersions: [:], clientChatIds: [], clientSuggestionsCount: 0, clientEmbedIds: []))
        f.socket.artifactRequest = { type, payload in try self.artifactReceipt(type: type, payload: payload) }
        var committedArtifacts = WatchVoiceCallCommittedArtifacts()
        let first = try f.runtime.voiceCallAdmitArtifact(frame: artifactFrame(scope: f.scope), scope: f.scope, context: f.context)
        let firstResult = try await f.runtime.voiceCallPersistArtifact(first, context: f.context)
        let committedFirst = try XCTUnwrap(firstResult)
        try committedArtifacts.record(committedFirst)
        let firstReference = try NativeVoiceCallArtifactReference(validating: committedFirst.reference)
        let firstTranscript = NativeVoiceCallTranscript(callID: "call-1", messageID: "assistant-artifact", role: .assistant,
            text: try firstReference.markdown, final: true, interrupted: false, userMessageID: "user-artifact", createdAt: 1800000001,
            modelName: nil, mateCategory: nil, mateName: nil, embedReferences: [firstReference])
        var secondFrame = artifactFrame(scope: f.scope, status: "processing")
        var secondPayload = try XCTUnwrap(secondFrame["payload"]?.object)
        secondPayload["embed_id"] = .string("watch-call-artifact-b")
        secondFrame["function_call_id"] = .string("function-artifact-b")
        secondFrame["payload"] = .object(secondPayload)
        let secondProcessing = try f.runtime.voiceCallAdmitArtifact(frame: secondFrame, scope: f.scope, context: f.context)
        let processingResult = try await f.runtime.voiceCallPersistArtifact(secondProcessing, context: f.context)
        XCTAssertNil(processingResult)
        let selectedFirst = try XCTUnwrap(committedArtifacts.admission(for: firstTranscript, scope: f.scope))
        XCTAssertEqual(selectedFirst.functionCallID, first.functionCallID)
        try f.runtime.voiceCallPublishTranscript(firstTranscript, scope: f.scope, context: f.context, admittedArtifact: selectedFirst)
        XCTAssertEqual(f.runtime.selectedMessages.count, 1)
        XCTAssertEqual(f.runtime.selectedMessages.first?.content, firstTranscript.text)
        XCTAssertTrue(f.socket.sentTurns.isEmpty)
        secondPayload["status"] = .string("finished")
        secondFrame["payload"] = .object(secondPayload)
        let secondFinal = try f.runtime.voiceCallAdmitArtifact(frame: secondFrame, scope: f.scope, context: f.context)
        let secondResult = try await f.runtime.voiceCallPersistArtifact(secondFinal, context: f.context)
        let committedSecond = try XCTUnwrap(secondResult)
        try committedArtifacts.record(committedSecond)
        let secondReference = try NativeVoiceCallArtifactReference(validating: committedSecond.reference)
        let combined = NativeVoiceCallTranscript(callID: "call-1", messageID: "assistant-artifact", role: .assistant,
            text: try firstReference.markdown + "\n" + secondReference.markdown, final: true, interrupted: false,
            userMessageID: "user-artifact", createdAt: 1800000001, modelName: nil, mateCategory: nil, mateName: nil,
            embedReferences: [firstReference, secondReference])
        let selectedCombined = try XCTUnwrap(committedArtifacts.admission(for: combined, scope: f.scope))
        XCTAssertEqual(selectedCombined.functionCallID, secondFinal.functionCallID)
        XCTAssertEqual(committedArtifacts.admission(for: firstTranscript, scope: f.scope)?.functionCallID, first.functionCallID,
            "The second artifact cannot erase the first committed reference's capability")
        try f.runtime.voiceCallPublishTranscript(combined, scope: f.scope, context: f.context, admittedArtifact: selectedCombined)
        f.runtime.callActions.update(.init(phase: .ended, chatID: f.scope.chatID, callID: "call-1",
            scopeGeneration: f.scope.workspaceGeneration, physicalRouteVerified: true))
        try f.runtime.voiceCallPublishTranscript(combined, scope: f.scope, context: f.context, admittedArtifact: selectedCombined)
        let replacementScope = NativeVoiceCallScope(accountID: f.scope.accountID, profileID: f.scope.profileID,
            workspaceGeneration: UUID(), chatID: f.scope.chatID, mateCategory: f.scope.mateCategory)
        XCTAssertNil(committedArtifacts.admission(for: combined, scope: replacementScope))
        let wrongUser = NativeVoiceCallTranscript(callID: combined.callID, messageID: combined.messageID, role: .assistant,
            text: combined.text, final: true, interrupted: false, userMessageID: "unrelated-user-message", createdAt: combined.createdAt,
            modelName: nil, mateCategory: nil, mateName: nil, embedReferences: combined.embedReferences)
        XCTAssertNil(committedArtifacts.admission(for: wrongUser, scope: f.scope))
        XCTAssertEqual(f.runtime.selectedMessages.count, 1, "Both artifacts belong to the original canonical assistant row")
        XCTAssertEqual(f.runtime.selectedMessages.first?.content, combined.text)
        XCTAssertEqual(f.socket.artifactRequests.map(\.type), ["store_embed", "store_embed_keys", "store_embed", "store_embed_keys"])
    }
}
