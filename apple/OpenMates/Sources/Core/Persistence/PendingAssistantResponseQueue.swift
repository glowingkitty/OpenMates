// Durable pending assistant response queue for Apple chat parity.
// Stores only chat/message identifiers, mirroring the web pendingAIResponses.ts
// privacy boundary. Message content and encryption keys never enter this queue.
// The queue is intentionally payload-minimal so app-group storage stays safe.

import Foundation

@MainActor
struct PendingAssistantResponseQueue {
    struct Entry: Codable, Equatable {
        let messageId: String
        let chatId: String
        var recoveryJobId: String? = nil
        var queuedAt: Date? = nil
    }

    static let shared = PendingAssistantResponseQueue()

    private let defaults: UserDefaults
    private let storageKey: String
    private let now: () -> Date
    private let isRecoveryQueue: Bool
    static let recoveryCapacity = 100
    static let recoveryLifetime: TimeInterval = 7 * 24 * 60 * 60

    init(
        defaults: UserDefaults = OpenMatesSharedEnvironment.defaults,
        storageKey: String = "openmates.apple.pending_assistant_responses.v1",
        now: @escaping () -> Date = Date.init,
        isRecoveryQueue: Bool = false
    ) {
        self.defaults = defaults
        self.storageKey = storageKey
        self.now = now
        self.isRecoveryQueue = isRecoveryQueue
    }

    func all() -> [Entry] {
        guard let data = defaults.data(forKey: storageKey),
              let entries = try? JSONDecoder().decode([Entry].self, from: data) else {
            return []
        }
        guard isRecoveryQueue else { return entries }
        let valid = Array(entries.filter {
            guard let jobId = $0.recoveryJobId, !jobId.isEmpty,
                  !$0.chatId.isEmpty, !$0.messageId.isEmpty, let queuedAt = $0.queuedAt else { return false }
            let age = now().timeIntervalSince(queuedAt)
            return age >= 0 && age < Self.recoveryLifetime
        }.suffix(Self.recoveryCapacity))
        if valid != entries {
            NativeDiagnostics.warning("completion_recovery_metadata_pruned count=\(entries.count - valid.count)")
            save(valid)
        }
        return valid
    }

    /// Separate from the legacy response queue: those entries can trigger a
    /// legacy persistence message and must never consume sealed recovery jobs.
    static func recovery(
        ownerId: String, apiBaseURL: URL,
        defaults: UserDefaults = OpenMatesSharedEnvironment.defaults,
        now: @escaping () -> Date = Date.init
    ) -> Self {
        let scope = OfflineStore.scopeId(userId: ownerId, apiBaseURL: apiBaseURL)
        return Self(defaults: defaults,
                    storageKey: "openmates.apple.pending_completion_recovery.v1.\(scope)",
                    now: now, isRecoveryQueue: true)
    }

    func addRecovery(jobId: String, messageId: String, chatId: String) {
        guard isRecoveryQueue, !jobId.isEmpty, !messageId.isEmpty, !chatId.isEmpty else { return }
        var entries = all()
        guard !entries.contains(where: { $0.recoveryJobId == jobId }) else { return }
        entries.append(Entry(messageId: messageId, chatId: chatId, recoveryJobId: jobId, queuedAt: now()))
        save(Array(entries.suffix(Self.recoveryCapacity)))
    }

    func removeRecovery(jobId: String) {
        guard isRecoveryQueue else { return }
        save(all().filter { $0.recoveryJobId != jobId })
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
