// Watch-only encrypted guest conversations. Content never enters account caches.
// Specification: specifications/features/apple-watch/specification.yml
// Assertions: apple-watch.guest.public-inference, apple-watch.guest.account-isolation
import Combine
import CryptoKit
import Foundation

struct WatchGuestChat: Codable, Equatable, Identifiable {
    struct Message: Codable, Equatable, Identifiable {
        let id: String
        let role: String
        let content: String
        let createdAt: Int
    }
    struct Pending: Codable, Equatable {
        let id: String
        let text: String
        let createdAt: Int
    }
    var id = "anonymous-" + UUID().uuidString
    var messages: [Message] = []
    var draft = ""
    var pending: Pending?
    var title: String { messages.first?.content ?? draft }
}

struct WatchGuestChatSnapshot: Codable, Equatable {
    var anonymousID = UUID().uuidString
    var chats: [WatchGuestChat] = []
}

@MainActor
protocol WatchGuestChatPersistence {
    func load() throws -> WatchGuestChatSnapshot?
    func save(_ value: WatchGuestChatSnapshot) throws
}

@MainActor
final class EncryptedWatchGuestChatPersistence: WatchGuestChatPersistence {
    private let defaults: UserDefaults
    private let key: SymmetricKey
    let storageKey: String
    private let origin: AnonymousPublicOrigin
    private let legacyProductionKey: SymmetricKey?
    init(defaults: UserDefaults = .standard, key: SymmetricKey, origin: AnonymousPublicOrigin = .production,
         legacyProductionKey: SymmetricKey? = nil) {
        self.defaults = defaults; self.key = key; self.origin = origin; self.legacyProductionKey = legacyProductionKey
        storageKey = "openmates.watch.guest.conversations.v2." + origin.namespace
    }
    static func installed(origin: AnonymousPublicOrigin) throws -> EncryptedWatchGuestChatPersistence {
        let name = "openmates.watch.guest.local-key.v2." + origin.namespace
        let key: SymmetricKey
        if let data = try KeychainHelper.load(key: name) {
            guard data.count == 32 else { throw AnonymousPublicChatError.localStorage }
            key = SymmetricKey(data: data)
        } else {
            key = SymmetricKey(size: .bits256)
            try KeychainHelper.save(key: name, data: key.withUnsafeBytes { Data($0) })
        }
        // 394 used a hard-coded production endpoint. Its unscoped receipt can
        // therefore be imported only into production, never development/custom.
        var legacyKey: SymmetricKey?
        if origin == .production, UserDefaults.standard.data(forKey: "openmates.watch.guest.conversations.v1") != nil,
           let data = try KeychainHelper.load(key: "openmates.watch.guest.local-key.v1"), data.count == 32 {
            legacyKey = SymmetricKey(data: data)
        }
        return EncryptedWatchGuestChatPersistence(key: key, origin: origin, legacyProductionKey: legacyKey)
    }
    func load() throws -> WatchGuestChatSnapshot? {
        let plaintext: Data
        let imported: Bool
        if let data = defaults.data(forKey: storageKey) {
            guard data.count <= 4 * 1024 * 1024 else { throw AnonymousPublicChatError.localStorage }
            plaintext = try AES.GCM.open(AES.GCM.SealedBox(combined: data), using: key, authenticating: Data(origin.identifier.utf8))
            imported = false
        } else if origin == .production, let legacyProductionKey,
                  let data = defaults.data(forKey: "openmates.watch.guest.conversations.v1") {
            guard data.count <= 4 * 1024 * 1024 else { throw AnonymousPublicChatError.localStorage }
            plaintext = try AES.GCM.open(AES.GCM.SealedBox(combined: data), using: legacyProductionKey)
            imported = true
        } else { return nil }
        let value = try JSONDecoder().decode(WatchGuestChatSnapshot.self, from: plaintext)
        guard !value.anonymousID.isEmpty, value.anonymousID.count <= 128, value.chats.count <= 20,
              Set(value.chats.map(\.id)).count == value.chats.count,
              value.chats.allSatisfy({ $0.id.hasPrefix("anonymous-") && $0.id.count <= 128 &&
                  $0.messages.count <= 50 && $0.draft.count <= 20_000 && ($0.pending?.text.count ?? 0) <= 20_000 }) else {
            throw AnonymousPublicChatError.localStorage
        }
        if imported { try save(value) } // Retain original legacy bytes/key for recovery.
        return value
    }
    func save(_ value: WatchGuestChatSnapshot) throws {
        let data = try JSONEncoder().encode(value)
        guard data.count <= 4 * 1024 * 1024 - 28,
              let ciphertext = try AES.GCM.seal(data, using: key, authenticating: Data(origin.identifier.utf8)).combined else { throw AnonymousPublicChatError.localStorage }
        defaults.set(ciphertext, forKey: storageKey)
        // Confirm the persistent domain was flushed before public dispatch.
        guard defaults.synchronize() else { throw AnonymousPublicChatError.localStorage }
    }
}

@MainActor
final class WatchGuestChatWorkspace: ObservableObject {
    enum Notice: Equatable { case unavailable, uncertain, storage, invalidDraft, historyFull }
    @Published private(set) var snapshot = WatchGuestChatSnapshot()
    @Published private(set) var budget: AnonymousPublicBudget?
    @Published private(set) var busy = false
    @Published private(set) var notice: Notice?
    private let transport: any AnonymousPublicChatTransport
    private let isCurrentOrigin: @MainActor () -> Bool
    private var persistence: (any WatchGuestChatPersistence)?
    private var generation = 0
    private var operation: Task<Void, Never>?

    init(transport: any AnonymousPublicChatTransport, persistence: (any WatchGuestChatPersistence)?,
         isCurrentOrigin: @escaping @MainActor () -> Bool = { true }) {
        self.transport = transport; self.persistence = persistence; self.isCurrentOrigin = isCurrentOrigin
        do {
            guard let persistence else { throw AnonymousPublicChatError.localStorage }
            if let stored = try persistence.load() { snapshot = stored }
            // Pending is deliberately not replayed after process loss.
            if snapshot.chats.contains(where: { $0.pending != nil }) { notice = .uncertain }
        } catch { self.persistence = nil; notice = .storage }
    }
    #if DEBUG
    private static var uiTestDisks: [String: EncryptedWatchGuestChatPersistence] = [:]
    private static let uiTestDefaults: UserDefaults = {
        let name = "openmates.watch.guest.inference-uitests"
        let defaults = UserDefaults(suiteName: name)!
        defaults.removePersistentDomain(forName: name)
        return defaults
    }()
    private static func uiTestDisk(origin: AnonymousPublicOrigin) -> EncryptedWatchGuestChatPersistence {
        if let disk = uiTestDisks[origin.identifier] { return disk }
        let disk = EncryptedWatchGuestChatPersistence(defaults: uiTestDefaults,
            key: SymmetricKey(size: .bits256), origin: origin)
        uiTestDisks[origin.identifier] = disk
        return disk
    }
    #endif
    convenience init(publicOrigin: URL, isCurrentOrigin: @escaping @MainActor () -> Bool) {
        guard let origin = try? AnonymousPublicOrigin(publicOrigin) else {
            self.init(transport: AnonymousPublicHTTPTransport(), persistence: nil, isCurrentOrigin: { false })
            return
        }
        let transport = AnonymousPublicHTTPTransport(origin: origin, isCurrentOrigin: isCurrentOrigin)
        #if DEBUG
        if ProcessInfo.processInfo.arguments.contains("--ui-test-watch-guest-local-drafts") {
            self.init(transport: transport, persistence: Self.uiTestDisk(origin: origin), isCurrentOrigin: isCurrentOrigin)
            return
        }
        #endif
        self.init(transport: transport, persistence: try? EncryptedWatchGuestChatPersistence.installed(origin: origin),
                  isCurrentOrigin: isCurrentOrigin)
    }
    var chats: [WatchGuestChat] { snapshot.chats }
    func chat(_ id: String) -> WatchGuestChat? { snapshot.chats.first { $0.id == id } }
    @discardableResult
    func create() -> String? {
        guard isCurrentOrigin(), !busy, persistence != nil, snapshot.chats.count < 20 else { notice = .storage; return nil }
        var next = snapshot; let chat = WatchGuestChat(); next.chats.insert(chat, at: 0)
        guard commit(next) else { return nil }
        notice = nil
        return chat.id
    }
    func edit(_ text: String, chatID: String) {
        guard isCurrentOrigin(), !busy, text.count <= 20_000, let index = snapshot.chats.firstIndex(where: { $0.id == chatID }),
              snapshot.chats[index].pending == nil else { return }
        var next = snapshot; next.chats[index].draft = text; _ = commit(next)
    }
    func suspend() {
        generation += 1; operation?.cancel(); operation = nil; busy = false; budget = nil
        if snapshot.chats.contains(where: { $0.pending != nil }) { notice = .uncertain }
    }
    func refreshBudget() async {
        guard isCurrentOrigin(), !Task.isCancelled else { return }
        let token = generation
        do {
            let value = try await transport.budget(anonymousID: snapshot.anonymousID)
            guard token == generation, isCurrentOrigin(), !Task.isCancelled else { return }
            budget = value
            if !value.active || !value.canSendText { notice = .unavailable }
            else if notice == .unavailable { notice = nil }
        } catch {
            guard token == generation, isCurrentOrigin(), !Task.isCancelled else { return }
            budget = nil; notice = .unavailable
        }
    }
    func startSend(chatID: String) {
        guard !busy else { return }
        operation = Task { await send(chatID: chatID) }
    }
    func send(chatID: String) async {
        guard isCurrentOrigin(), !busy, persistence != nil, let original = chat(chatID), original.pending == nil else { return }
        guard !original.draft.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty,
              original.draft.count <= 20_000 else { notice = .invalidDraft; return }
        guard original.messages.count <= 48, original.messages.allSatisfy({ $0.content.count <= 20_000 }) else { notice = .historyFull; return }
        busy = true; notice = nil
        let token = generation
        defer { if generation == token { busy = false } }
        await refreshBudget()
        guard token == generation, isCurrentOrigin(), !Task.isCancelled else { return }
        guard budget?.active == true, budget?.canSendText == true else { return }
        // Draft may have changed during status fetch only through another owner;
        // never send a different or superseded snapshot.
        guard chat(chatID) == original else { return }
        let pending = WatchGuestChat.Pending(id: UUID().uuidString, text: original.draft,
                                             createdAt: Int(Date().timeIntervalSince1970))
        var next = snapshot
        guard let index = next.chats.firstIndex(where: { $0.id == chatID }) else { return }
        next.chats[index].pending = pending
        guard commit(next) else { return } // Durable recovery precedes public POST.
        let turn = AnonymousPublicTurn(anonymousID: snapshot.anonymousID, chatID: chatID, messageID: pending.id,
                                       text: pending.text, history: original.messages.map {
            .init(role: $0.role, content: $0.content, createdAt: $0.createdAt)
        })
        do {
            let answer = try await transport.send(turn)
            guard token == generation, isCurrentOrigin(), !Task.isCancelled else { return }
            guard answer.status == "completed", answer.chatId == chatID,
                  !answer.messageId.isEmpty, answer.messageId.count <= 128,
                  !answer.assistant.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty,
                  answer.assistant.utf8.count <= 256 * 1024,
                  !original.messages.contains(where: { $0.id == answer.messageId }) else {
                notice = .uncertain; return
            }
            var completed = snapshot
            guard let position = completed.chats.firstIndex(where: { $0.id == chatID }),
                  completed.chats[position].pending == pending else { return }
            completed.chats[position].messages += [
                .init(id: pending.id, role: "user", content: pending.text, createdAt: pending.createdAt),
                .init(id: answer.messageId, role: "assistant", content: answer.assistant, createdAt: Int(Date().timeIntervalSince1970))
            ]
            completed.chats[position].pending = nil; completed.chats[position].draft = ""
            if !commit(completed) { notice = .storage } // Keep pending; no retry on save failure.
            await refreshBudget()
        } catch {
            guard token == generation, isCurrentOrigin(), !Task.isCancelled else { return }
            // Only pre-admission rejections are safe to retry. 5xx, cancellation,
            // malformed/lost replies and timeouts may already have consumed budget.
            if case AnonymousPublicChatError.rejected(let code) = error, [400, 401, 403, 404, 422, 429].contains(code) {
                var rejected = snapshot
                if let position = rejected.chats.firstIndex(where: { $0.id == chatID }) {
                    rejected.chats[position].pending = nil; _ = commit(rejected)
                }
                budget = nil; notice = .unavailable
            } else { notice = .uncertain }
        }
    }
    private func commit(_ value: WatchGuestChatSnapshot) -> Bool {
        guard isCurrentOrigin(), !Task.isCancelled else { return false }
        do {
            guard let persistence else { throw AnonymousPublicChatError.localStorage }
            try persistence.save(value); snapshot = value; return true
        } catch { notice = .storage; return false }
    }
}
