// Chat key manager — in-memory cache of per-chat AES-256 decryption keys.
// Mirrors the web app's ChatKeyManager.ts. Each chat has its own random key
// that is stored on the server wrapped (encrypted) with the user's master key.
// At load time, we unwrap each chat's key and cache it here for fast decryption
// of messages, titles, and embeds within that chat.
// Specification: specifications/features/pii-protection/specification.yml
// Assertions: pii.embed.owner-local-reveal-sync, pii.surface.semantic-parity
// Specification: specifications/features/teams/specification.yml
// Assertions: teams.membership.role-gated

import Foundation
import CryptoKit

@MainActor
final class ChatKeyManager: ObservableObject {
    static let shared = ChatKeyManager()

    /// In-memory map of chatId → raw AES-256 chat key
    // Invalidates in-flight crypto whenever authentication changes scope.
    private var generation = UUID()
    private var materialGeneration = UUID()
    private var revocations: [String: UUID] = [:]
    private let unwrapKey: @MainActor (String, SymmetricKey) async throws -> SymmetricKey
    private let decryptContent: @MainActor (String, SymmetricKey) async throws -> String
    private var chatKeys: [String: SymmetricKey] = [:]
    private var encryptedKeys: [String: String] = [:]
    private var encryptedKeyFingerprints: [String: String] = [:]
    // Existing callers use this token across awaits before installing keys or
    // publishing decrypted state. A single-chat revocation must invalidate it.
    var cacheGeneration: UUID { materialGeneration }

    /// Whether chat keys have been loaded from the initial sync
    @Published var isReady = false

    init(
        unwrapKey: @escaping @MainActor (String, SymmetricKey) async throws -> SymmetricKey = {
            try await CryptoManager.shared.unwrapChatKey(encryptedChatKeyBase64: $0, masterKey: $1)
        },
        decryptContent: @escaping @MainActor (String, SymmetricKey) async throws -> String = {
            try await CryptoManager.shared.decryptContent(base64String: $0, key: $1)
        }
    ) {
        self.unwrapKey = unwrapKey
        self.decryptContent = decryptContent
    }

    private func fence(for chatId: String) -> KeyRevocationFence {
        KeyRevocationFence(account: generation, chat: revocations[chatId])
    }

    private func isCurrent(_ fence: KeyRevocationFence, for chatId: String) -> Bool {
        fence == self.fence(for: chatId) && !Task.isCancelled
    }

    // MARK: - Key access

    /// Get the decryption key for a specific chat.
    func key(for chatId: String) -> SymmetricKey? {
        chatKeys[chatId]
    }

    /// Preserve the exact wrapper accepted by the server. AES-GCM wrapping uses
    /// a random nonce, so wrapping the same raw key again produces a different
    /// encrypted_chat_key and fails the server's immutable-key check.
    func encryptedKey(for chatId: String) -> String? {
        encryptedKeys[chatId]
    }

    func rememberEncryptedKey(_ encryptedKey: String, for chatId: String) {
        guard chatKeys[chatId] != nil else { return }
        encryptedKeys[chatId] = encryptedKey
        encryptedKeyFingerprints[chatId] = Self.fingerprint(encryptedKey)
    }

    func rememberNewEncryptedKeyIfAbsent(_ encryptedKey: String, for chatId: String,
                                         matching key: SymmetricKey,
                                         expectedGeneration: UUID? = nil) -> String? {
        guard expectedGeneration == nil || expectedGeneration == cacheGeneration,
              let currentKey = chatKeys[chatId], Self.keysEqual(currentKey, key) else { return nil }
        if let existing = encryptedKeys[chatId] { return existing }
        rememberEncryptedKey(encryptedKey, for: chatId)
        notifyEmbedKeyMaterialAvailable()
        return encryptedKey
    }

    /// Install a validated server wrapper without replacing a key loaded by a
    /// newer sync event while CryptoManager was suspended.
    func installValidatedKey(_ key: SymmetricKey, encryptedKey: String, for chatId: String,
                             expectedGeneration: UUID) -> String? {
        guard expectedGeneration == cacheGeneration else { return nil }
        if let currentKey = chatKeys[chatId] {
            guard Self.keysEqual(currentKey, key) else { return nil }
            if let currentWrapper = encryptedKeys[chatId] { return currentWrapper }
        } else {
            chatKeys[chatId] = key
        }
        rememberEncryptedKey(encryptedKey, for: chatId)
        notifyEmbedKeyMaterialAvailable()
        return encryptedKey
    }

    /// Store a chat key (after unwrapping from encrypted_chat_key).
    func setKey(_ key: SymmetricKey, for chatId: String) {
        chatKeys[chatId] = key
        encryptedKeys.removeValue(forKey: chatId)
        encryptedKeyFingerprints.removeValue(forKey: chatId)
        notifyEmbedKeyMaterialAvailable()
    }

    /// Create or return the originating-device key for a new chat.
    func createKeyForNewChat(
        _ chatId: String,
        generateKey: @escaping @Sendable () async -> SymmetricKey = { await CryptoManager.shared.generateChatKey() }
    ) async -> SymmetricKey {
        if let existing = chatKeys[chatId] {
            return existing
        }
        let capturedFence = fence(for: chatId)
        let key = await generateKey()
        // Another first send (or server sync) may have installed the key while
        // generation was suspended. Never overwrite its key and wrapper.
        // Preserve the nonoptional API. A stale generated key is never cached;
        // callers must retain their cacheGeneration fence before using it.
        guard isCurrent(capturedFence, for: chatId) else { return key }
        if let existing = chatKeys[chatId] { return existing }
        chatKeys[chatId] = key
        notifyEmbedKeyMaterialAvailable()
        return key
    }

    /// Check if we have a key for a given chat.
    func hasKey(for chatId: String) -> Bool {
        chatKeys[chatId] != nil
    }

    func shouldLoadServerKey(chatId: String, encryptedChatKey: String) -> Bool {
        guard chatKeys[chatId] != nil else { return true }
        return encryptedKeyFingerprints[chatId] != Self.fingerprint(encryptedChatKey)
    }

    func markInitialSyncReady() {
        isReady = true
    }

    // MARK: - Bulk loading

    /// Unwrap and cache chat keys for a batch of chats.
    /// Called at startup after the master key is loaded from Keychain.
    func loadChatKeys(from chats: [(chatId: String, encryptedChatKey: String)], masterKey: SymmetricKey,
                      isCurrent operationIsCurrent: @escaping @MainActor () -> Bool = { true }) async {
        let capturedGeneration = generation
        // Capture every chat before the first await: revoking a later entry
        // while an earlier unwrap is suspended must also fence that entry.
        let fences = Dictionary(chats.map { ($0.chatId, fence(for: $0.chatId)) },
                                uniquingKeysWith: { first, _ in first })
        let batchSize = 20

        for (index, entry) in chats.enumerated() {
            guard capturedGeneration == generation, !Task.isCancelled, operationIsCurrent() else { return }
            let (chatId, encryptedChatKey) = entry
            guard let capturedFence = fences[chatId], isCurrent(capturedFence, for: chatId) else { continue }
            do {
                let chatKey = try await unwrapKey(encryptedChatKey, masterKey)
                guard capturedGeneration == generation, !Task.isCancelled, operationIsCurrent() else { return }
                guard isCurrent(capturedFence, for: chatId) else { continue }
                chatKeys[chatId] = chatKey
                rememberEncryptedKey(encryptedChatKey, for: chatId)
                notifyEmbedKeyMaterialAvailable()
                if NativeSyncPerfLog.verboseCrypto {
                    print("[ChatKeyManager] loaded key chat=\(chatId.prefix(8))")
                }
            } catch {
                print("[ChatKeyManager] Failed to unwrap key for chat \(chatId.prefix(8)): \(error)")
            }
            if (index + 1).isMultiple(of: batchSize) {
                await Task.yield()
            }
        }

        guard capturedGeneration == generation, !Task.isCancelled, operationIsCurrent() else { return }
        isReady = true
        NativeSyncPerfLog.info("phase=chatKeyBulkLoad requested=\(chats.count) cached=\(chatKeys.count)")
    }

    /// Unwrap and cache a single chat key (for newly loaded chats).
    @discardableResult
    func loadChatKey(chatId: String, encryptedChatKey: String, masterKey: SymmetricKey,
                     isCurrent operationIsCurrent: @escaping @MainActor () -> Bool = { true }) async -> Bool {
        let capturedFence = fence(for: chatId)
        guard isCurrent(capturedFence, for: chatId), operationIsCurrent() else { return false }
        do {
            let chatKey = try await unwrapKey(encryptedChatKey, masterKey)
            guard isCurrent(capturedFence, for: chatId), operationIsCurrent() else { return false }
            chatKeys[chatId] = chatKey
            rememberEncryptedKey(encryptedChatKey, for: chatId)
            notifyEmbedKeyMaterialAvailable()
            if NativeSyncPerfLog.verboseCrypto {
                print("[ChatKeyManager] loaded single key chat=\(chatId.prefix(8)) cached=\(chatKeys.count)")
            }
            return true
        } catch {
            print("[ChatKeyManager] Failed to unwrap key for chat \(chatId.prefix(8)): \(error)")
            return false
        }
    }

    @discardableResult
    func loadChatKey(chatId: String, wrappers: [ChatKeyWrapperRecord], masterKey: SymmetricKey,
                     isCurrent operationIsCurrent: @escaping @MainActor () -> Bool = { true }) async -> Bool {
        let capturedFence = fence(for: chatId)
        for wrapper in ChatKeyWrapperRecord.orderedMasterWrappers(wrappers, for: chatId) {
            guard isCurrent(capturedFence, for: chatId), operationIsCurrent() else { return false }
            if !shouldLoadServerKey(chatId: chatId, encryptedChatKey: wrapper.encryptedChatKey) {
                return true
            }
            if await loadChatKey(
                chatId: chatId,
                encryptedChatKey: wrapper.encryptedChatKey,
                masterKey: masterKey,
                isCurrent: operationIsCurrent
            ) {
                return isCurrent(capturedFence, for: chatId) && operationIsCurrent()
            }
        }
        return false
    }

    // MARK: - Content decryption helpers

    /// Decrypt a chat title using the cached chat key.
    func decryptTitle(for chatId: String, encryptedTitle: String) async -> String? {
        await decryptChatField(chatId: chatId, encryptedValue: encryptedTitle, fieldName: "title")
    }

    /// Decrypt any chat metadata field encrypted with the per-chat key.
    func decryptChatField(chatId: String, encryptedValue: String, fieldName: String) async -> String? {
        let capturedFence = fence(for: chatId)
        guard let chatKey = chatKeys[chatId] else {
            if NativeSyncPerfLog.verboseCrypto {
                print("[ChatKeyManager] \(fieldName) decrypt skipped missing key chat=\(chatId.prefix(8))")
            }
            return nil
        }
        do {
            let value = try await decryptContent(encryptedValue, chatKey)
            guard isCurrent(capturedFence, for: chatId) else { return nil }
            if NativeSyncPerfLog.verboseCrypto {
                print("[ChatKeyManager] \(fieldName) decrypt ok chat=\(chatId.prefix(8)) empty=\(value.isEmpty)")
            }
            return value
        } catch {
            print("[ChatKeyManager] \(fieldName) decrypt failed for \(chatId.prefix(8)): \(error)")
            return nil
        }
    }

    /// Decrypt message content using the cached chat key.
    func decryptMessageContent(chatId: String, encryptedContent: String) async -> String? {
        let capturedFence = fence(for: chatId)
        guard let chatKey = chatKeys[chatId] else { return nil }
        do {
            let value = try await decryptContent(encryptedContent, chatKey)
            guard isCurrent(capturedFence, for: chatId) else { return nil }
            return value
        } catch {
            print("[ChatKeyManager] Message decrypt failed for chat \(chatId.prefix(8)): \(error)")
            return nil
        }
    }

    // MARK: - Cleanup

    /// Remove a single chat key (on chat delete).
    func removeKey(for chatId: String) {
        revocations[chatId] = UUID()
        materialGeneration = UUID()
        chatKeys.removeValue(forKey: chatId)
        encryptedKeys.removeValue(forKey: chatId)
        encryptedKeyFingerprints.removeValue(forKey: chatId)
    }

    /// Clear all keys (on logout).
    func clearAll() {
        generation = UUID()
        materialGeneration = UUID()
        revocations.removeAll()
        chatKeys.removeAll()
        encryptedKeys.removeAll()
        encryptedKeyFingerprints.removeAll()
        isReady = false
    }

    private func notifyEmbedKeyMaterialAvailable() {
        let expectedScope = OfflineStore.shared.scopeGeneration
        Task { @MainActor in
            guard expectedScope == OfflineStore.shared.scopeGeneration else { return }
            NotificationCenter.default.post(name: .chatKeyMaterialAvailable, object: nil,
                                            userInfo: ["accountScope": expectedScope])
            await CodeRunOutputStore.shared.handleEmbedKeysAvailable()
        }
    }

    private static func fingerprint(_ encryptedChatKey: String) -> String {
        SHA256.hash(data: Data(encryptedChatKey.utf8)).map { String(format: "%02x", $0) }.joined()
    }

    private static func keysEqual(_ lhs: SymmetricKey, _ rhs: SymmetricKey) -> Bool {
        lhs.withUnsafeBytes { lhsBytes in
            rhs.withUnsafeBytes { rhsBytes in Data(lhsBytes) == Data(rhsBytes) }
        }
    }
}

private struct KeyRevocationFence: Equatable {
    let account: UUID
    let chat: UUID?
}

extension Notification.Name {
    static let chatKeyMaterialAvailable = Notification.Name("openmates.chatKeyMaterialAvailable")
}

struct ChatKeyWrapperRecord: Decodable, Sendable {
    let id: String?
    let hashedChatId: String
    let keyType: String
    let encryptedChatKey: String
    let wrapperVersion: Int?
    let createdAt: String?

    private enum CodingKeys: String, CodingKey {
        case id, hashedChatId, keyType, encryptedChatKey, wrapperVersion, createdAt
    }

    init(from decoder: Decoder) throws {
        let values = try decoder.container(keyedBy: CodingKeys.self)
        id = try values.decodeIfPresent(String.self, forKey: .id)
        hashedChatId = try values.decode(String.self, forKey: .hashedChatId)
        keyType = try values.decode(String.self, forKey: .keyType)
        encryptedChatKey = try values.decode(String.self, forKey: .encryptedChatKey)
        wrapperVersion = try values.decodeIfPresent(Int.self, forKey: .wrapperVersion)
        if let text = try? values.decode(String.self, forKey: .createdAt) {
            createdAt = text
        } else if let seconds = try? values.decode(Int64.self, forKey: .createdAt) {
            createdAt = String(seconds)
        } else if let seconds = try? values.decode(Double.self, forKey: .createdAt) {
            createdAt = String(Int64(seconds))
        } else {
            createdAt = nil
        }
    }

    static func orderedMasterWrappers(
        _ wrappers: [ChatKeyWrapperRecord],
        for chatId: String
    ) -> [ChatKeyWrapperRecord] {
        let hashedChatId = Self.hashedChatId(for: chatId)
        return wrappers
            .filter {
                $0.keyType == "master" &&
                    $0.hashedChatId == hashedChatId &&
                    !$0.encryptedChatKey.isEmpty
            }
            .sorted {
                let left = ($0.wrapperVersion ?? 0, $0.createdAt ?? "", $0.id ?? "")
                let right = ($1.wrapperVersion ?? 0, $1.createdAt ?? "", $1.id ?? "")
                return left > right
            }
    }

    static func hashedChatId(for chatId: String) -> String {
        SHA256.hash(data: Data(chatId.utf8)).map { String(format: "%02x", $0) }.joined()
    }
}

@MainActor
final class EmbedKeyManager {
    static let shared = EmbedKeyManager()

    private var generation = UUID()
    private var revocations: [String: UUID] = [:]
    private let masterKey: @MainActor () async -> SymmetricKey?
    private let chatKey: @MainActor (String) -> SymmetricKey?
    private let unwrapKey: @MainActor (String, SymmetricKey) async -> SymmetricKey?
    private var entriesByHashedEmbedId: [String: [EmbedKeyRecord]] = [:]
    private var keyCache: [String: SymmetricKey] = [:]
    private var chatIdHashCache: [String: String] = [:]

    init(
        masterKey: @escaping @MainActor () async -> SymmetricKey? = {
            guard let userId = await AuthManager.currentUserId() else { return nil }
            return try? await CryptoManager.shared.loadMasterKey(for: userId)
        },
        chatKey: @escaping @MainActor (String) -> SymmetricKey? = { ChatKeyManager.shared.key(for: $0) },
        unwrapKey: @escaping @MainActor (String, SymmetricKey) async -> SymmetricKey? = {
            guard let data = try? await CryptoManager.shared.decryptBlob(base64String: $0, key: $1) else { return nil }
            return SymmetricKey(data: data)
        }
    ) {
        self.masterKey = masterKey
        self.chatKey = chatKey
        self.unwrapKey = unwrapKey
    }

    private func fence(for chatId: String) -> KeyRevocationFence {
        KeyRevocationFence(account: generation, chat: revocations[chatId])
    }

    private func isCurrent(_ fence: KeyRevocationFence, for chatId: String) -> Bool {
        fence == self.fence(for: chatId) && !Task.isCancelled
    }

    func store(_ entries: [EmbedKeyRecord], source: String) {
        guard !entries.isEmpty else { return }
        for entry in entries {
            var existing = entriesByHashedEmbedId[entry.hashedEmbedId] ?? []
            if !existing.contains(where: {
                $0.keyType == entry.keyType &&
                $0.hashedChatId == entry.hashedChatId &&
                $0.encryptedEmbedKey == entry.encryptedEmbedKey
            }) {
                existing.append(entry)
            }
            entriesByHashedEmbedId[entry.hashedEmbedId] = existing
        }
        print("[EmbedKeyManager] stored source=\(source) entries=\(entries.count) hashedEmbeds=\(entriesByHashedEmbedId.count)")
        let expectedScope = OfflineStore.shared.scopeGeneration
        Task { @MainActor in
            guard expectedScope == OfflineStore.shared.scopeGeneration else { return }
            await CodeRunOutputStore.shared.handleEmbedKeysAvailable()
        }
    }

    func key(
        for embed: EmbedRecord,
        chatId: String,
        allEmbeds: [String: EmbedRecord],
        visited: Set<String> = []
    ) async -> SymmetricKey? {
        let capturedFence = fence(for: chatId)
        guard isCurrent(capturedFence, for: chatId) else { return nil }
        if let cached = keyCache[cacheKey(embedId: embed.id, chatId: chatId)] {
            return cached
        }

        if let parentId = embed.parentEmbedId,
           parentId != embed.id,
           !visited.contains(parentId),
           let parent = allEmbeds[parentId],
           let parentKey = await key(
               for: parent,
               chatId: chatId,
               allEmbeds: allEmbeds,
               visited: visited.union([embed.id])
           ) {
            guard isCurrent(capturedFence, for: chatId) else { return nil }
            keyCache[cacheKey(embedId: embed.id, chatId: chatId)] = parentKey
            return parentKey
        }

        guard isCurrent(capturedFence, for: chatId) else { return nil }
        let hashedEmbedId = sha256Hex(embed.id)
        guard let entries = entriesByHashedEmbedId[hashedEmbedId], !entries.isEmpty else {
            if NativeSyncPerfLog.verboseCrypto {
                print("[EmbedKeyManager] missing key entries embed=\(embed.id.prefix(8)) hash=\(hashedEmbedId.prefix(12))")
            }
            return nil
        }

        if let masterEntry = entries.first(where: { $0.keyType == "master" }),
           let wrappingKey = await masterKey(),
           isCurrent(capturedFence, for: chatId),
           let embedKey = await unwrapKey(masterEntry.encryptedEmbedKey, wrappingKey) {
            guard isCurrent(capturedFence, for: chatId) else { return nil }
            keyCache[cacheKey(embedId: embed.id, chatId: chatId)] = embedKey
            if NativeSyncPerfLog.verboseCrypto {
                print("[EmbedKeyManager] unwrapped master embed=\(embed.id.prefix(8))")
            }
            return embedKey
        }

        guard isCurrent(capturedFence, for: chatId) else { return nil }
        let hashedChatId = embed.hashedChatId ?? chatIdHash(chatId)
        let chatEntries = entries.filter { entry in
            entry.keyType == "chat" && (entry.hashedChatId == hashedChatId || entry.hashedChatId == nil)
        }
        for entry in chatEntries {
            guard isCurrent(capturedFence, for: chatId) else { return nil }
            guard let wrappingKey = chatKey(chatId),
                  let embedKey = await unwrapKey(entry.encryptedEmbedKey, wrappingKey) else {
                continue
            }
            guard isCurrent(capturedFence, for: chatId) else { return nil }
            keyCache[cacheKey(embedId: embed.id, chatId: chatId)] = embedKey
            if NativeSyncPerfLog.verboseCrypto {
                print("[EmbedKeyManager] unwrapped chat embed=\(embed.id.prefix(8)) chat=\(chatId.prefix(8))")
            }
            return embedKey
        }

        if NativeSyncPerfLog.verboseCrypto {
            print("[EmbedKeyManager] unwrap failed embed=\(embed.id.prefix(8)) entries=\(entries.count) hasChatKey=\(chatKey(chatId) != nil)")
        }
        return nil
    }

    func clearAll() {
        generation = UUID()
        revocations.removeAll()
        entriesByHashedEmbedId.removeAll()
        keyCache.removeAll()
        chatIdHashCache.removeAll()
    }

    func removeKeys(for chatId: String) {
        revocations[chatId] = UUID()
        let hashedChatId = chatIdHash(chatId)
        entriesByHashedEmbedId = entriesByHashedEmbedId.compactMapValues { entries in
            let retained = entries.filter { $0.hashedChatId != hashedChatId }
            return retained.isEmpty ? nil : retained
        }
        keyCache = keyCache.filter { !$0.key.hasSuffix(":\(chatId)") }
        chatIdHashCache.removeValue(forKey: chatId)
    }

    private func chatIdHash(_ chatId: String) -> String {
        if let cached = chatIdHashCache[chatId] { return cached }
        let hashed = sha256Hex(chatId)
        chatIdHashCache[chatId] = hashed
        return hashed
    }

    private func cacheKey(embedId: String, chatId: String) -> String {
        "\(embedId):\(chatId)"
    }

    private func sha256Hex(_ value: String) -> String {
        let digest = SHA256.hash(data: Data(value.utf8))
        return digest.map { String(format: "%02x", $0) }.joined()
    }
}

/// Owner-only Finance reveal data. Canonical embeds and WebSocket sync never
/// carry these originals; the scoped disk row contains master-key ciphertext.
@MainActor
final class OwnerEmbedPIIStore: ObservableObject {
    static let shared = OwnerEmbedPIIStore()

    @Published private(set) var mappingsByEmbedKey: [String: [PIIMapping]] = [:]
    private var scopeGeneration = OfflineStore.shared.scopeGeneration
    private init() {}

    private static func key(chatId: String, embedId: String) -> String { "\(chatId):\(embedId)" }

    private func resetIfScopeChanged() {
        let current = OfflineStore.shared.scopeGeneration
        guard current != scopeGeneration else { return }
        scopeGeneration = current
        mappingsByEmbedKey.removeAll()
    }

    func mappings(chatId: String, embedId: String) -> [PIIMapping] {
        resetIfScopeChanged()
        return mappingsByEmbedKey[Self.key(chatId: chatId, embedId: embedId)] ?? []
    }

    func remove(chatId: String) {
        resetIfScopeChanged()
        mappingsByEmbedKey = mappingsByEmbedKey.filter { !$0.key.hasPrefix("\(chatId):") }
    }

    func clearAll() {
        mappingsByEmbedKey.removeAll()
    }

    #if DEBUG
    /// UI previews can exercise reveal/navigation without writing owner secrets.
    func seedPreviewMappings(chatId: String, embedId: String, mappings: [PIIMapping]) {
        resetIfScopeChanged()
        mappingsByEmbedKey[Self.key(chatId: chatId, embedId: embedId)] = mappings
    }
    #endif

    func persist(_ mappings: [PIIMapping], chatId: String, embedId: String,
                 ownerUserId: String, masterKey: SymmetricKey) async throws {
        resetIfScopeChanged()
        let fence = CodeRunScopeFence(store: OfflineStore.shared)
        let deletionVersion = OfflineStore.shared.chatDeletionVersion(chatId)
        guard fence.isCurrent(in: OfflineStore.shared), !mappings.isEmpty,
              mappings.allSatisfy({ !$0.placeholder.isEmpty && !$0.original.isEmpty && $0.type == "COUNTERPARTY" })
        else { throw OwnerEmbedPIIError.invalidContext }
        guard let plaintext = String(data: try JSONEncoder().encode(mappings), encoding: .utf8) else {
            throw OwnerEmbedPIIError.invalidPayload
        }
        let encrypted = try await CryptoManager.shared.encryptWithMasterKey(plaintext, masterKey: masterKey)
        let currentUserId = await AuthManager.currentUserId()
        guard fence.isCurrent(in: OfflineStore.shared), currentUserId == ownerUserId,
              OfflineStore.shared.chatDeletionVersion(chatId) == deletionVersion else {
            throw OwnerEmbedPIIError.invalidContext
        }
        try OfflineStore.shared.persistOwnerEmbedPII(PersistedOwnerEmbedPII(
            embedId: embedId, chatId: chatId, ownerUserId: ownerUserId,
            encryptedMappings: encrypted, createdAt: Date().timeIntervalSince1970
        ))
        guard fence.isCurrent(in: OfflineStore.shared) else { throw OwnerEmbedPIIError.invalidContext }
        mappingsByEmbedKey[Self.key(chatId: chatId, embedId: embedId)] = mappings
    }

    func load(chatId: String, embedId: String) async -> [PIIMapping] {
        resetIfScopeChanged()
        let fence = CodeRunScopeFence(store: OfflineStore.shared)
        let deletionVersion = OfflineStore.shared.chatDeletionVersion(chatId)
        guard fence.isCurrent(in: OfflineStore.shared) else { return [] }
        let cacheKey = Self.key(chatId: chatId, embedId: embedId)
        if let cached = mappingsByEmbedKey[cacheKey] { return cached }
        guard let row = try? OfflineStore.shared.loadOwnerEmbedPII(chatId: chatId, embedId: embedId) else { return [] }
        guard let userId = await AuthManager.currentUserId(),
              userId == row.ownerUserId,
              let key = try? await CryptoManager.shared.loadMasterKey(for: userId),
              fence.isCurrent(in: OfflineStore.shared),
              let plaintext = try? await CryptoManager.shared.decryptContent(
                base64String: row.encryptedMappings, key: key
              ),
              let data = plaintext.data(using: .utf8),
              let mappings = try? JSONDecoder().decode([PIIMapping].self, from: data),
              mappings.allSatisfy({ !$0.placeholder.isEmpty && !$0.original.isEmpty && $0.type == "COUNTERPARTY" }),
              fence.isCurrent(in: OfflineStore.shared),
              OfflineStore.shared.chatDeletionVersion(chatId) == deletionVersion else { return [] }
        mappingsByEmbedKey[cacheKey] = mappings
        return mappings
    }
}

enum OwnerEmbedPIIError: Error {
    case invalidContext
    case invalidPayload
}
