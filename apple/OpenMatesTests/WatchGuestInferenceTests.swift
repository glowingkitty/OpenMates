// Supporting deterministic public-protocol and encrypted-local-state checks.
// No real public inference, paid account state, or Watch radio is exercised.
import CryptoKit
import XCTest
@testable import OpenMates

@MainActor
final class WatchGuestInferenceTests: XCTestCase {
    // contract-test: supporting surface=gui.apple assertions=apple-watch.guest.public-inference,apple-watch.guest.account-isolation
    func testKnownProductionLegacyReceiptCannotMigrateIntoDevelopment() throws {
        let name = "WatchGuestLegacyTests-" + UUID().uuidString
        let defaults = try XCTUnwrap(UserDefaults(suiteName: name)); defer { defaults.removePersistentDomain(forName: name) }
        let oldKey = SymmetricKey(size: .bits256)
        var legacy = WatchGuestChatSnapshot(); var chat = WatchGuestChat(); chat.draft = "Original production draft"
        legacy.chats = [chat]
        let bytes = try XCTUnwrap(AES.GCM.seal(JSONEncoder().encode(legacy), using: oldKey).combined)
        defaults.set(bytes, forKey: "openmates.watch.guest.conversations.v1")
        let dev = EncryptedWatchGuestChatPersistence(defaults: defaults, key: SymmetricKey(size: .bits256),
            origin: try AnonymousPublicOrigin(ServerProfile.development.apiBaseURL), legacyProductionKey: oldKey)
        XCTAssertNil(try dev.load())
        let prod = EncryptedWatchGuestChatPersistence(defaults: defaults, key: SymmetricKey(size: .bits256),
            origin: .production, legacyProductionKey: oldKey)
        XCTAssertEqual(try prod.load(), legacy)
        XCTAssertNotNil(defaults.data(forKey: prod.storageKey))
        XCTAssertEqual(defaults.data(forKey: "openmates.watch.guest.conversations.v1"), bytes)
        XCTAssertNil(try dev.load())
    }

    // contract-test: supporting surface=gui.apple assertions=apple-watch.guest.public-inference,apple-watch.guest.account-isolation
    func testConfiguredPublicOriginsSeparateAnonymousIdentityCiphertextAndHistory() throws {
        let name = "WatchGuestOriginTests-" + UUID().uuidString
        let defaults = try XCTUnwrap(UserDefaults(suiteName: name)); defer { defaults.removePersistentDomain(forName: name) }
        let production = AnonymousPublicOrigin.production
        let development = try AnonymousPublicOrigin(ServerProfile.development.apiBaseURL)
        XCTAssertNotEqual(production.namespace, development.namespace)
        XCTAssertEqual(try AnonymousPublicOrigin(URL(string: "https://api.dev.openmates.org/")!), development)
        XCTAssertThrowsError(try AnonymousPublicOrigin(URL(string: "https://api.dev.openmates.org/private")!))
        let sameTestKey = SymmetricKey(size: .bits256)
        let prodDisk = EncryptedWatchGuestChatPersistence(defaults: defaults, key: sameTestKey, origin: production)
        let devDisk = EncryptedWatchGuestChatPersistence(defaults: defaults, key: sameTestKey, origin: development)
        let prod = WatchGuestChatWorkspace(transport: GuestInferenceTransport(), persistence: prodDisk)
        let prodID = try XCTUnwrap(prod.create()); prod.edit("Production only", chatID: prodID)
        let dev = WatchGuestChatWorkspace(transport: GuestInferenceTransport(), persistence: devDisk)
        XCTAssertTrue(dev.chats.isEmpty)
        let devID = try XCTUnwrap(dev.create()); dev.edit("Development only", chatID: devID)
        XCTAssertNotEqual(prod.snapshot.anonymousID, dev.snapshot.anonymousID)
        XCTAssertNotEqual(prodDisk.storageKey, devDisk.storageKey)
        XCTAssertEqual(try prodDisk.load()?.chats.first?.draft, "Production only")
        XCTAssertEqual(try devDisk.load()?.chats.first?.draft, "Development only")
        // Even copying valid ciphertext across namespaces with the same key fails
        // because the exact public origin is authenticated as AES-GCM AAD.
        let prodBytes = try XCTUnwrap(defaults.data(forKey: prodDisk.storageKey))
        defaults.set(prodBytes, forKey: devDisk.storageKey)
        XCTAssertThrowsError(try devDisk.load())
        XCTAssertEqual(try prodDisk.load()?.chats.first?.draft, "Production only")
        let request = try AnonymousPublicHTTPTransport.request(baseURL: development.url,
            path: "free-usage/status", anonymousID: dev.snapshot.anonymousID)
        XCTAssertEqual(request.url?.host, "api.dev.openmates.org")
        XCTAssertNil(request.value(forHTTPHeaderField: "Authorization"))
        XCTAssertNil(request.value(forHTTPHeaderField: "Cookie"))
    }

    // contract-test: supporting surface=gui.apple assertions=apple-watch.guest.public-inference,apple-watch.guest.account-isolation
    func testProfileChangeFencesLateAnswerWithoutSavingItToEitherPublicScope() async throws {
        let network = GuestInferenceTransport(); let reached = expectation(description: "Original public POST")
        network.hold = reached
        let originalDisk = GuestInferenceMemory(); var originalOriginIsCurrent = true
        let original = WatchGuestChatWorkspace(transport: network, persistence: originalDisk,
            isCurrentOrigin: { originalOriginIsCurrent })
        let id = try XCTUnwrap(original.create()); original.edit("Origin-bound request", chatID: id)
        let operation = Task { await original.send(chatID: id) }
        await fulfillment(of: [reached], timeout: 3)
        originalOriginIsCurrent = false
        let nextDisk = GuestInferenceMemory()
        let next = WatchGuestChatWorkspace(transport: GuestInferenceTransport(), persistence: nextDisk)
        _ = next.create()
        network.release(); await operation.value
        XCTAssertTrue(original.chat(id)?.messages.isEmpty == true)
        XCTAssertNotNil(originalDisk.value?.chats.first?.pending)
        XCTAssertTrue(next.chats.allSatisfy { $0.messages.isEmpty && $0.pending == nil })
        let calls = network.turns.count
        await original.send(chatID: id); await original.refreshBudget()
        original.edit("Wrong scope edit", chatID: id)
        XCTAssertNil(original.create())
        XCTAssertEqual(original.chat(id)?.draft, "Origin-bound request")
        XCTAssertEqual(network.turns.count, calls)
    }

    // contract-test: supporting surface=gui.apple assertions=apple-watch.guest.public-inference,apple-watch.guest.account-isolation
    func testPublicRequestUsesPinnedSnakeCaseJSONAndHasNoAccountCredentials() throws {
        let turn = AnonymousPublicTurn(anonymousID: "local-install", chatID: "anonymous-chat", messageID: "turn",
                                      text: "Hello", history: [.init(role: "assistant", content: "Before", createdAt: 123)])
        let data = try JSONEncoder().encode(turn)
        let json = try XCTUnwrap(JSONSerialization.jsonObject(with: data) as? [String: Any])
        XCTAssertEqual(Set(json.keys), Set(["anonymous_id", "client_chat_id", "client_message_id", "plaintext_message", "message_history"]))
        XCTAssertEqual((json["message_history"] as? [[String: Any]])?.first?["created_at"] as? Int, 123)
        let request = try AnonymousPublicHTTPTransport.request(baseURL: URL(string: "https://api.openmates.org")!,
            path: "chat/stream", anonymousID: turn.anonymousID, body: data)
        XCTAssertEqual(request.url?.absoluteString, "https://api.openmates.org/v1/anonymous/chat/stream")
        XCTAssertEqual(request.value(forHTTPHeaderField: "Accept"), "application/json")
        XCTAssertEqual(request.value(forHTTPHeaderField: "X-OpenMates-Anonymous-ID"), "local-install")
        XCTAssertNil(request.value(forHTTPHeaderField: "Authorization"))
        XCTAssertNil(request.value(forHTTPHeaderField: "Cookie"))
        XCTAssertFalse(request.httpShouldHandleCookies)
        XCTAssertThrowsError(try AnonymousPublicHTTPTransport.request(baseURL: URL(string: "http://api.openmates.org")!,
            path: "chat/stream", anonymousID: "id", body: data))
    }

    // contract-test: supporting surface=gui.apple assertions=apple-watch.guest.public-inference
    func testCompletedTurnsRetainExactLocalHistoryAndRefreshServerBudget() async throws {
        let network = GuestInferenceTransport(); let disk = GuestInferenceMemory()
        let model = WatchGuestChatWorkspace(transport: network, persistence: disk)
        let id = try XCTUnwrap(model.create()); model.edit("First", chatID: id)
        await model.send(chatID: id)
        XCTAssertEqual(model.chat(id)?.messages.map(\.content), ["First", "Real fixture response"])
        XCTAssertNil(model.chat(id)?.pending); XCTAssertEqual(model.chat(id)?.draft, "")
        XCTAssertEqual(model.budget?.dailyRemainingPercent, 37)
        model.edit("Second", chatID: id); await model.send(chatID: id)
        XCTAssertEqual(network.turns.count, 2)
        XCTAssertEqual(network.turns[1].history.map(\.content), ["First", "Real fixture response"])
        XCTAssertEqual(network.turns[1].anonymousID, disk.value?.anonymousID)
        XCTAssertEqual(network.turns[1].chatID, id)
        XCTAssertEqual(model.chat(id)?.messages.count, 4)
    }

    // contract-test: supporting surface=gui.apple assertions=apple-watch.guest.public-inference
    func testOfflineOrDisabledBudgetNeverPostsAndKeepsEncryptedDraftEligibleForExplicitSend() async throws {
        for offline in [true, false] {
            let network = GuestInferenceTransport(); network.statusFails = offline
            network.allowed = false
            let disk = GuestInferenceMemory(); let model = WatchGuestChatWorkspace(transport: network, persistence: disk)
            let id = try XCTUnwrap(model.create()); model.edit("Saved draft", chatID: id)
            await model.send(chatID: id)
            XCTAssertTrue(network.turns.isEmpty); XCTAssertEqual(model.chat(id)?.draft, "Saved draft")
            XCTAssertNil(model.chat(id)?.pending)
            network.statusFails = false; network.allowed = true
            await model.refreshBudget(); XCTAssertTrue(network.turns.isEmpty, "Status recovery cannot submit a draft")
            await model.send(chatID: id); XCTAssertEqual(network.turns.count, 1)
        }
    }

    // contract-test: supporting surface=gui.apple assertions=apple-watch.guest.public-inference
    func testAmbiguousPostRemainsPendingAcrossRelaunchAndCannotReplay() async throws {
        for error in [GuestInferenceFailure.unknown as Error, AnonymousPublicChatError.rejected(500)] {
            let network = GuestInferenceTransport(); network.sendError = error
            let disk = GuestInferenceMemory(); let model = WatchGuestChatWorkspace(transport: network, persistence: disk)
            let id = try XCTUnwrap(model.create()); model.edit("Never replay blindly", chatID: id)
            await model.send(chatID: id)
            XCTAssertNotNil(model.chat(id)?.pending); XCTAssertEqual(model.notice, .uncertain)
            let relaunched = WatchGuestChatWorkspace(transport: network, persistence: disk)
            await relaunched.refreshBudget(); await relaunched.send(chatID: id)
            XCTAssertEqual(network.turns.count, 1); XCTAssertEqual(relaunched.chat(id)?.draft, "Never replay blindly")
            XCTAssertEqual(relaunched.notice, .uncertain)
        }
    }

    // contract-test: supporting surface=gui.apple assertions=apple-watch.guest.public-inference
    func testKnownPreAdmissionRejectionRetainsDraftWithoutInventingReply() async throws {
        let network = GuestInferenceTransport(); network.sendError = AnonymousPublicChatError.rejected(429)
        let model = WatchGuestChatWorkspace(transport: network, persistence: GuestInferenceMemory())
        let id = try XCTUnwrap(model.create()); model.edit("Budget limited", chatID: id)
        await model.send(chatID: id)
        XCTAssertNil(model.chat(id)?.pending); XCTAssertEqual(model.chat(id)?.draft, "Budget limited")
        XCTAssertTrue(model.chat(id)?.messages.isEmpty == true); XCTAssertNil(model.budget)
    }

    // contract-test: supporting surface=gui.apple assertions=apple-watch.guest.public-inference,apple-watch.guest.account-isolation
    func testSuspendedOwnerCannotPublishLateReplyAndNewOwnerDoesNotReplayIt() async throws {
        let reached = expectation(description: "POST reached")
        let network = GuestInferenceTransport(); network.hold = reached
        let disk = GuestInferenceMemory(); let model = WatchGuestChatWorkspace(transport: network, persistence: disk)
        let id = try XCTUnwrap(model.create()); model.edit("Original guest", chatID: id)
        let send = Task { await model.send(chatID: id) }
        await fulfillment(of: [reached], timeout: 3)
        model.suspend(); network.release(); await send.value
        XCTAssertTrue(model.chat(id)?.messages.isEmpty == true)
        XCTAssertNotNil(model.chat(id)?.pending); XCTAssertEqual(model.notice, .uncertain)
        let next = WatchGuestChatWorkspace(transport: network, persistence: disk)
        await next.send(chatID: id); XCTAssertEqual(network.turns.count, 1)
    }

    // contract-test: supporting surface=gui.apple assertions=apple-watch.guest.public-inference
    func testPendingMustPersistBeforePostAndWrongChatReplyNeverBecomesSuccess() async throws {
        let network = GuestInferenceTransport(); let disk = GuestInferenceMemory()
        let model = WatchGuestChatWorkspace(transport: network, persistence: disk)
        let id = try XCTUnwrap(model.create()); model.edit("Keep me", chatID: id)
        disk.failSave = true; await model.send(chatID: id)
        XCTAssertTrue(network.turns.isEmpty); XCTAssertEqual(model.notice, .storage)
        disk.failSave = false; network.wrongChat = true; await model.send(chatID: id)
        XCTAssertEqual(model.notice, .uncertain); XCTAssertTrue(model.chat(id)?.messages.isEmpty == true)
        XCTAssertNotNil(model.chat(id)?.pending)
    }

    // contract-test: supporting surface=gui.apple assertions=apple-watch.guest.public-inference,apple-watch.guest.account-isolation
    func testLocalSnapshotIsEncryptedAndWrongKeyFailsWithoutReplacingIt() throws {
        let name = "WatchGuestInferenceTests-" + UUID().uuidString
        let defaults = try XCTUnwrap(UserDefaults(suiteName: name)); defer { defaults.removePersistentDomain(forName: name) }
        let key = SymmetricKey(size: .bits256)
        let disk = EncryptedWatchGuestChatPersistence(defaults: defaults, key: key)
        var value = WatchGuestChatSnapshot(); var chat = WatchGuestChat(); chat.draft = "private guest sentinel"
        value.chats = [chat]; try disk.save(value)
        XCTAssertEqual(try disk.load(), value)
        let bytes = try XCTUnwrap(defaults.data(forKey: disk.storageKey))
        XCTAssertNil(bytes.range(of: Data(chat.draft.utf8)))
        XCTAssertThrowsError(try EncryptedWatchGuestChatPersistence(defaults: defaults, key: SymmetricKey(size: .bits256)).load())
        XCTAssertEqual(defaults.data(forKey: disk.storageKey), bytes)
        XCTAssertNil(defaults.object(forKey: "openmates.apple.anonymous.chat_ids.v1"))
    }
}

private enum GuestInferenceFailure: Error { case unknown }
@MainActor private final class GuestInferenceMemory: WatchGuestChatPersistence {
    var value: WatchGuestChatSnapshot?
    var failSave = false
    func load() throws -> WatchGuestChatSnapshot? { value }
    func save(_ value: WatchGuestChatSnapshot) throws {
        if failSave { throw GuestInferenceFailure.unknown }; self.value = value
    }
}
@MainActor private final class GuestInferenceTransport: AnonymousPublicChatTransport {
    var allowed = true
    var statusFails = false
    var sendError: Error?
    var wrongChat = false
    var turns: [AnonymousPublicTurn] = []
    var hold: XCTestExpectation?
    private var continuation: CheckedContinuation<Void, Never>?
    func budget(anonymousID: String) async throws -> AnonymousPublicBudget {
        if statusFails { throw GuestInferenceFailure.unknown }
        return .init(active: allowed, canSendText: allowed, dailyRemainingPercent: 37, resetAt: nil)
    }
    func send(_ turn: AnonymousPublicTurn) async throws -> AnonymousPublicAnswer {
        turns.append(turn)
        if let hold { await withCheckedContinuation { continuation = $0; hold.fulfill() } }
        if let sendError { throw sendError }
        return .init(status: "completed", chatId: wrongChat ? "other-chat" : turn.chatID,
                     messageId: UUID().uuidString, assistant: "Real fixture response")
    }
    func release() { continuation?.resume(); continuation = nil; hold = nil }
}
