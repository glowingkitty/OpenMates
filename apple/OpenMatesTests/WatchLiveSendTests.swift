// Explicit opt-in integration coverage for one disposable synthetic Watch text turn.
// Uses the production Watch runtime, crypto and socket; root alone executes it.
import XCTest
import CryptoKit
@testable import OpenMates

@MainActor
final class WatchLiveSendTests: XCTestCase {
    // contract-test: supporting surface=gui.apple assertions=apple-watch.chats.new-text-reply,apple-watch.pairing.private-session
    func testLivePersonalDisposableWatchTextUsesActualCryptoAndCanonicalAcknowledgements() async throws {
        let env = ProcessInfo.processInfo.environment
        guard env["OPENMATES_TEST_WATCH_TEXT_SEND"] == "1" else {
            throw XCTSkip("One real disposable Watch text turn requires explicit opt-in")
        }
        guard env["OPENMATES_TEST_WATCH_SOCKET_READY_VERIFIED"] == "1",
              env["OPENMATES_TEST_PERSONAL_VERIFIED"] == "1",
              let email = env["OPENMATES_TEST_ACCOUNT_EMAIL"],
              let identityHash = env["OPENMATES_TEST_PERSONAL_IDENTITY_HASH"], identityHash.count == 64,
              let accountHash = env["OPENMATES_TEST_PERSONAL_ACCOUNT_HASH"], accountHash.count == 64,
              Self.hash(email.trimmingCharacters(in: .whitespacesAndNewlines).lowercased()) == identityHash,
              ServerProfile.current() == .development,
              let accountID = AuthManager.notificationAccountId, Self.hash(accountID) == accountHash else {
            XCTFail("Real Watch text opt-in requires prior verified readiness and the exact recovered personal development identity")
            return
        }
        let firstSequence = NativeClientLogCollector.shared.entriesSnapshot(limit: 1).last?.sequence ?? 0
        defer {
            // Keep only schema-checked scalar events emitted during this opted-in run.
            // No URL, body, identifier or arbitrary error string can match this grammar.
            let scalarEvents = NativeClientLogCollector.shared.entriesAfter(sequence: firstSequence, limit: 200)
                .filter { $0.category == "watch_chat_socket" && $0.message.range(of:
                    #"^event=(turn_admission_failed|response_timeout|ready_timeout)( [a-z_]+=(true|false|-?[0-9]+))*$"#,
                    options: .regularExpression) != nil }
                .map(\.message)
            if !scalarEvents.isEmpty {
                let stages = XCTAttachment(string: scalarEvents.joined(separator: "\n"))
                stages.name = "Disposable Watch send scalar stage diagnostics"
                stages.lifetime = .keepAlways
                add(stages)
            }
        }
        let context = WatchChatRequestContext(accountID: accountID, profile: .development,
            accountGeneration: WatchChatAccountLifecycle.generation, validate: {
                guard AuthManager.notificationAccountId == accountID else { throw CancellationError() }
            })
        let directory = FileManager.default.temporaryDirectory.appendingPathComponent("watch-live-synthetic-" + UUID().uuidString)
        let cache = WatchChatOfflineCache(directory: directory)
        let socket = WatchRealtimeSyncSocket()
        var runtime: WatchChatRuntime?
        defer {
            runtime?.stopRealtimeSync()
            socket.disconnect()
            // Retain this small encrypted disposable cache and the remote chat.
            // The native host never deletes a path outside verified repository scope.
        }
        var stage = "master_key"
        do {
            guard let masterKey = try await CryptoManager.shared.loadMasterKey(for: accountID) else {
                XCTFail("Approved native owner master key is unavailable; no turn was dispatched")
                return
            }
            try context.check()
            stage = "session_restore"
            let connectionID = UUID().uuidString
            let restored = try await WatchSessionTransport.loadSession(
                body: SessionRequest(sessionId: connectionID, deviceInfo: WatchCompatibleSession.makeNativeDeviceInfo()), context: context)
            try context.check()
            guard restored.isAuthenticated, restored.user?.id == accountID,
                  let token = restored.wsToken, !token.isEmpty else {
                XCTFail("Disposable Watch send did not restore the exact approved native session")
                return
            }
            let session = WatchSyncSession(sessionId: connectionID, token: token)
            stage = "socket_sync"
            socket.connect(session: session, syncState: WatchSyncClientState(clientChatVersions: [:], clientChatIds: [],
                clientSuggestionsCount: 0, clientEmbedIds: []))
            _ = try await socket.requestEvent(type: "", payload: [:], responseTypes: ["phased_sync_complete"], matching: {
                ($0["context_epoch"] as? Int) == 0 && $0["phase"] as? String == "all"
                    && ($0["team_id"] == nil || $0["team_id"] is NSNull)
            })
            try context.check()
            let chatRuntime = WatchChatRuntime(currentUserId: accountID, api: APIClient.shared, cache: cache,
                syncSocket: socket, syncSession: session)
            runtime = chatRuntime
            stage = "new_chat_crypto"
            await chatRuntime.createNewChat()
            guard let chat = chatRuntime.selectedChat, let wrapped = chat.encryptedChatKey else {
                XCTFail("Production Watch crypto could not create a fresh transient chat identity")
                return
            }
            XCTAssertTrue(UUID(uuidString: chat.id) != nil)
            XCTAssertTrue(chatRuntime.selectedMessages.isEmpty)
            let key = try await CryptoManager.shared.unwrapChatKey(encryptedChatKeyBase64: wrapped, masterKey: masterKey)
            var preflightTurnID: String?
            var committedMessageID: String?
            socket.setEventHandler { type, payload in
                if type == "chat_turn_preflight_ack" {
                    preflightTurnID = payload["turn_id"] as? String
                } else if type == "ai_task_initiated", payload["chat_id"] as? String == chat.id {
                    committedMessageID = (payload["user_message_id"] ?? payload["message_id"]) as? String
                }
            }
            let publicText = "Synthetic Watch send verification. Reply with exactly WATCH_OK."
            stage = "single_text_send"
            try context.check()
            // Exactly one call: a queued return alone is not accepted as successful send proof.
            let queued = await chatRuntime.sendText(publicText)
            try context.check()
            guard queued, chatRuntime.errorMessage == nil else {
                XCTFail("Disposable Watch send did not complete canonical admission; inspect private scalar socket stages")
                return
            }
            let saved = await cache.loadSnapshot()
            guard saved.pendingTextSends.isEmpty,
                  let local = chatRuntime.selectedMessages.first(where: { $0.role == .user && !$0.isPending }),
                  let cipher = local.encryptedContent, cipher != publicText,
                  preflightTurnID.flatMap(UUID.init(uuidString:)) != nil,
                  committedMessageID == local.id else {
                XCTFail("Disposable Watch send requires exact preflight/commit message identity, ciphertext and retired pending state")
                return
            }
            let openedLocal = try await CryptoManager.shared.decryptContent(base64String: cipher, key: key)
            XCTAssertTrue(openedLocal == publicText, "Production Watch message encryption must round-trip the public synthetic text")
            stage = "private_rest_reread"
            let page = try await APIClient.shared.fetchMessageWindow(chatId: chat.id, query: WatchMessageWindowQuery(), context: context)
            try context.check()
            guard let stored = page.messages.first(where: { $0.id == local.id && $0.chatId == chat.id && $0.role == .user }),
                  let storedCipher = stored.encryptedContent, storedCipher == cipher else {
                XCTFail("Pinned REST reread must contain this exact disposable encrypted user message")
                return
            }
            let rereadText = try await CryptoManager.shared.decryptContent(base64String: storedCipher, key: key)
            XCTAssertTrue(rereadText == publicText, "Private encrypted reread must decrypt to the public synthetic text")
            let receipt = XCTAttachment(string: "verified_personal=true;development=true;production_watch_crypto=true;production_watch_socket=true;preflight_commit_correlated=true;pending_retired=true;encrypted_rest_reread=true;inference_dispatches=1;physical_watch_proof=false")
            receipt.name = "Disposable Watch text canonical send receipt"
            receipt.lifetime = .keepAlways
            add(receipt)
        } catch {
            XCTFail("Disposable Watch text stage=\(stage) error_type=\(String(reflecting: type(of: error))) error_code=\((error as NSError).code)")
        }
    }

    private static func hash(_ value: String) -> String {
        SHA256.hash(data: Data(value.utf8)).map { String(format: "%02x", $0) }.joined()
    }
}
