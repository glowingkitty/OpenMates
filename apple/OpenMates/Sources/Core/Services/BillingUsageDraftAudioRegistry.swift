// Private local evidence that a recording used an explicitly preallocated draft ID.
// Web source: frontend/packages/ui/src/stores/draftAudioChatStore.ts
//             frontend/packages/ui/src/components/enter_message/MessageInput.svelte
// Usage rows/servers never create markers; discarding a draft never deletes them.
// Specification: specifications/features/billing/specification.yml
// Assertions: billing.usage.landing-complete, billing.access.authenticated-first-party

import CryptoKit
import Foundation

@MainActor
final class BillingUsageDraftAudioRegistry {
    static let shared = BillingUsageDraftAudioRegistry()
    static let storageKey = "openmates.billing.draft-audio.v1"
    static let retention: TimeInterval = 90 * 24 * 60 * 60
    static let maximumScopes = 8
    static let maximumMarkersPerScope = 512
    static let maximumPendingMessages = 128

    // Only a new-chat recording caller can confirm its allocated draft UUID.
    // Session readiness, server usage and generic chat IDs are not evidence.
    struct ConfirmedPreallocation: Sendable {
        let chatID: String
        let teamID: String?
        init?(draftChatID: String, recordingChatID: String, isNewChatComposer: Bool,
              hasAcceptedUserMessage: Bool, teamID: String?) {
            guard isNewChatComposer, !hasAcceptedUserMessage,
                  UUID(uuidString: draftChatID) != nil,
                  draftChatID == recordingChatID else { return nil }
            self.chatID = draftChatID
            self.teamID = teamID
        }
    }

    private struct Bucket: Codable {
        let cacheScopeID: String
        var touchedAt: TimeInterval
        var markers: [String: TimeInterval]
    }
    private struct Ledger: Codable { var buckets: [String: Bucket] = [:] }
    private struct Pending: Equatable {
        let namespace: String
        let chatDigest: String
        let messageDigest: String
        let cacheGeneration: UUID
        let teamEpoch: UInt64
    }
    private let defaults: UserDefaults
    private let now: () -> Date
    private let validate: @MainActor (UserTasksAccountFence) async throws -> Void
    private var pending: [Pending] = []

    init(defaults: UserDefaults = .standard, now: @escaping () -> Date = Date.init,
         validate: @escaping @MainActor (UserTasksAccountFence) async throws -> Void = { try await $0.check() }) {
        self.defaults = defaults; self.now = now; self.validate = validate
    }

    // Bridges the new-composer callback without capturing a non-Sendable fence.
    // All identity is captured at actual allocation, before asynchronous transport.
    func markCaptured(_ allocation: ConfirmedPreallocation?, accountID: String?,
                      cacheGeneration: UUID, serverProfile: ServerProfile, teamEpoch: UInt64) async throws {
        guard let allocation, let accountID else { return }
        let fence = UserTasksAccountFence(accountID: accountID)
        guard fence.scope == cacheGeneration, fence.serverProfile == serverProfile,
              fence.widgetTeamEpoch == teamEpoch, fence.teamID == allocation.teamID else { throw CancellationError() }
        guard try await mark(allocation, fence: fence) else { throw CancellationError() }
    }

    @discardableResult
    func mark(_ allocation: ConfirmedPreallocation, fence: UserTasksAccountFence) async throws -> Bool {
        try await validate(fence)
        guard allocation.teamID == fence.teamID else { return false }
        let namespace = Self.namespace(fence)
        var ledger = read()
        var bucket = ledger.buckets[namespace] ?? Bucket(cacheScopeID: Self.cacheScopeID(fence),
            touchedAt: now().timeIntervalSince1970, markers: [:])
        // Repeated recordings/retries retain one marker, never an additional row.
        bucket.markers[Self.chatDigest(allocation.chatID)] = now().timeIntervalSince1970
        bucket.touchedAt = now().timeIntervalSince1970
        ledger.buckets[namespace] = bucket
        write(ledger)
        return true
    }

    func contains(chatID: String, fence: UserTasksAccountFence) async throws -> Bool {
        try await validate(fence)
        guard UUID(uuidString: chatID) != nil else { return false }
        return read().buckets[Self.namespace(fence)]?.markers[Self.chatDigest(chatID)] != nil
    }

    // Register only actual ordinary-user commit identities, before transport.
    // A queued/optimistic/rejected send does not remove the draft marker.
    func registerOrdinarySend(chatID: String, messageID: String, role: MessageRole,
                              fence: UserTasksAccountFence) async throws {
        try await validate(fence)
        guard role == .user, UUID(uuidString: chatID) != nil,
              !messageID.isEmpty, messageID.utf8.count <= 200,
              read().buckets[Self.namespace(fence)]?.markers[Self.chatDigest(chatID)] != nil else { return }
        let namespace = Self.namespace(fence)
        pending.removeAll { $0.cacheGeneration != fence.scope || $0.teamEpoch != fence.widgetTeamEpoch }
        let item = Pending(namespace: namespace, chatDigest: Self.chatDigest(chatID),
            messageDigest: Self.digest(messageID), cacheGeneration: fence.scope, teamEpoch: fence.widgetTeamEpoch)
        if !pending.contains(item) { pending.append(item) }
        if pending.count > Self.maximumPendingMessages { pending.removeFirst(pending.count - Self.maximumPendingMessages) }
    }

    // WebSocketManager calls this only after its current-socket generation check.
    // The ordinary message commit acknowledgement supplies a durable version.
    // Metadata-only `status: synced`, errors and socket-write success do not qualify.
    func consumeAcceptedMessage(type: String, fields: [String: Any], fence: UserTasksAccountFence) async throws {
        try await validate(fence)
        guard type == "chat_message_confirmed", let version = fields["new_messages_v"] as? Int, version > 0,
              let chatID = fields["chat_id"] as? String,
              let messageID = fields["message_id"] as? String else { return }
        try accept(chatID: chatID, messageID: messageID, fence: fence)
    }

    // An exact retry's validated preflight response may already prove durable
    // admission. Root calls this after comparing its committed inference payload.
    func acceptPersistedOrdinaryTurn(chatID: String, messageID: String, state: String,
                                     fence: UserTasksAccountFence) async throws {
        try await validate(fence)
        guard ["ENQUEUED", "RUNNING", "TERMINAL"].contains(state) else { return }
        try accept(chatID: chatID, messageID: messageID, fence: fence)
    }

    private func accept(chatID: String, messageID: String, fence: UserTasksAccountFence) throws {
        let item = Pending(namespace: Self.namespace(fence), chatDigest: Self.chatDigest(chatID),
            messageDigest: Self.digest(messageID), cacheGeneration: fence.scope, teamEpoch: fence.widgetTeamEpoch)
        guard pending.contains(item) else { return }
        pending.removeAll { $0.namespace == item.namespace && $0.chatDigest == item.chatDigest }
        var ledger = read()
        ledger.buckets[item.namespace]?.markers.removeValue(forKey: item.chatDigest)
        write(ledger)
    }

    // Called exclusively by the actual scoped cache's authoritative chat-delete
    // path. Draft-only discard uses preservingDraftTombstone and skips this.
    // UUIDs identify one chat across that owner's team buckets.
    func removeDeletedChat(chatID: String, cacheScopeID: String) {
        guard UUID(uuidString: chatID) != nil else { return }
        let digest = Self.chatDigest(chatID)
        var ledger = read()
        let namespaces = ledger.buckets.filter { $0.value.cacheScopeID == cacheScopeID }.map(\.key)
        for namespace in namespaces { ledger.buckets[namespace]?.markers.removeValue(forKey: digest) }
        pending.removeAll { namespaces.contains($0.namespace) && $0.chatDigest == digest }
        write(ledger)
    }

    // Erasure removes all team/profile marker buckets belonging to that actual
    // account/server cache. Normal logout/deactivation preserves private evidence.
    func eraseCacheScope(_ cacheScopeID: String) {
        var ledger = read()
        let namespaces = ledger.buckets.filter { $0.value.cacheScopeID == cacheScopeID }.map(\.key)
        for namespace in namespaces { ledger.buckets.removeValue(forKey: namespace) }
        pending.removeAll { namespaces.contains($0.namespace) }
        write(ledger)
    }

    private func read() -> Ledger {
        guard let data = defaults.data(forKey: Self.storageKey), data.count <= 2_000_000,
              let ledger = try? JSONDecoder().decode(Ledger.self, from: data) else { return .init() }
        let bounded = pruned(ledger)
        // Reads also remove expired evidence from disk, without extending its age.
        write(bounded)
        return bounded
    }
    private func write(_ ledger: Ledger) {
        let bounded = pruned(ledger)
        if bounded.buckets.isEmpty { defaults.removeObject(forKey: Self.storageKey); return }
        guard let data = try? JSONEncoder().encode(bounded), data.count <= 2_000_000 else { return }
        defaults.set(data, forKey: Self.storageKey)
    }
    private func pruned(_ source: Ledger) -> Ledger {
        let timestamp = now().timeIntervalSince1970
        var result = Ledger()
        for (namespace, var bucket) in source.buckets {
            let markers = bucket.markers.filter {
                $0.key.count == 64 && $0.value.isFinite && $0.value <= timestamp + 60 && $0.value >= timestamp - Self.retention
            }.sorted { $0.value == $1.value ? $0.key < $1.key : $0.value > $1.value }
            bucket.markers = Dictionary(uniqueKeysWithValues: markers.prefix(Self.maximumMarkersPerScope).map { ($0.key, $0.value) })
            if !bucket.markers.isEmpty { result.buckets[namespace] = bucket }
        }
        let recent = result.buckets.sorted {
            $0.value.touchedAt == $1.value.touchedAt ? $0.key < $1.key : $0.value.touchedAt > $1.value.touchedAt
        }.prefix(Self.maximumScopes)
        result.buckets = Dictionary(uniqueKeysWithValues: recent.map { ($0.key, $0.value) })
        return result
    }
    static func persistentNamespace(accountID: String, profile: ServerProfile, teamID: String?) -> String {
        digest(["billing-draft-audio-v1", accountID, profile.id,
            profile.apiBaseURL.absoluteString, profile.webBaseURL.absoluteString,
            profile.uploadBaseURL.absoluteString, teamID ?? "personal"].joined(separator: "\n"))
    }
    private static func namespace(_ fence: UserTasksAccountFence) -> String {
        persistentNamespace(accountID: fence.accountID, profile: fence.serverProfile, teamID: fence.teamID)
    }
    private static func cacheScopeID(_ fence: UserTasksAccountFence) -> String {
        OfflineStore.scopeId(userId: fence.accountID, apiBaseURL: fence.serverProfile.apiBaseURL)
    }
    private static func chatDigest(_ chatID: String) -> String { digest(chatID.lowercased()) }
    private static func digest(_ value: String) -> String {
        SHA256.hash(data: Data(value.utf8)).map { String(format: "%02x", $0) }.joined()
    }
}
