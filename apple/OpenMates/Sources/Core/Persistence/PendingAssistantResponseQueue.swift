// Durable pending assistant response queue for Apple chat parity.
// Stores only chat/message identifiers, mirroring the web pendingAIResponses.ts
// privacy boundary. Plaintext assistant content stays in encrypted local message
// storage and is reloaded from there when retrying server persistence.
// The queue is intentionally payload-minimal so app-group storage stays safe.

import Foundation

@MainActor
struct PendingAssistantResponseQueue {
    struct Entry: Codable, Equatable {
        let messageId: String
        let chatId: String
    }

    static let shared = PendingAssistantResponseQueue()

    private let defaults: UserDefaults
    private let storageKey: String

    init(
        defaults: UserDefaults = OpenMatesSharedEnvironment.defaults,
        storageKey: String = "openmates.apple.pending_assistant_responses.v1"
    ) {
        self.defaults = defaults
        self.storageKey = storageKey
    }

    func all() -> [Entry] {
        guard let data = defaults.data(forKey: storageKey),
              let entries = try? JSONDecoder().decode([Entry].self, from: data) else {
            return []
        }
        return entries
    }

    func add(messageId: String, chatId: String) {
        guard !messageId.isEmpty, !chatId.isEmpty else { return }
        var entries = all()
        guard !entries.contains(where: { $0.messageId == messageId }) else { return }
        entries.append(Entry(messageId: messageId, chatId: chatId))
        save(entries)
    }

    func remove(messageId: String) {
        let entries = all().filter { $0.messageId != messageId }
        save(entries)
    }

    func clear() {
        defaults.removeObject(forKey: storageKey)
    }

    private func save(_ entries: [Entry]) {
        guard !entries.isEmpty else {
            defaults.removeObject(forKey: storageKey)
            return
        }
        if let data = try? JSONEncoder().encode(entries) {
            defaults.set(data, forKey: storageKey)
        }
    }
}
