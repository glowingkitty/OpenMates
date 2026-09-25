// Chat key manager — in-memory cache of per-chat AES-256 decryption keys.
// Mirrors the web app's ChatKeyManager.ts. Each chat has its own random key
// that is stored on the server wrapped (encrypted) with the user's master key.
// At load time, we unwrap each chat's key and cache it here for fast decryption
// of messages, titles, and embeds within that chat.

import Foundation
import CryptoKit

@MainActor
final class ChatKeyManager: ObservableObject {
    static let shared = ChatKeyManager()

    /// In-memory map of chatId → raw AES-256 chat key
    // Invalidates in-flight crypto whenever authentication changes scope.
    private var generation = UUID()
    private var chatKeys: [String: SymmetricKey] = [:]
    private var encryptedKeys: [String: String] = [:]
    private var encryptedKeyFingerprints: [String: String] = [:]
    var cacheGeneration: UUID { generation }

    /// Whether chat keys have been loaded from the initial sync
    @Published var isReady = false

    private init() {}

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
        encryptedKeys[chatId] = encryptedKey
        encryptedKeyFingerprints[chatId] = Self.fingerprint(encryptedKey)
    }

    func rememberNewEncryptedKeyIfAbsent(_ encryptedKey: String, for chatId: String,
                                         matching key: SymmetricKey,
                                         expectedGeneration: UUID? = nil) -> String? {
        guard expectedGeneration == nil || expectedGeneration == generation,
              let currentKey = chatKeys[chatId], Self.keysEqual(currentKey, key) else { return nil }
        if let existing = encryptedKeys[chatId] { return existing }
        rememberEncryptedKey(encryptedKey, for: chatId)
        return encryptedKey
    }

    /// Install a validated server wrapper without replacing a key loaded by a
    /// newer sync event while CryptoManager was suspended.
    func installValidatedKey(_ key: SymmetricKey, encryptedKey: String, for chatId: String,
                             expectedGeneration: UUID) -> String? {
        guard expectedGeneration == generation else { return nil }
        if let currentKey = chatKeys[chatId] {
            guard Self.keysEqual(currentKey, key) else { return nil }
            if let currentWrapper = encryptedKeys[chatId] { return currentWrapper }
        } else {
            chatKeys[chatId] = key
        }
        rememberEncryptedKey(encryptedKey, for: chatId)
        return encryptedKey
    }

    /// Store a chat key (after unwrapping from encrypted_chat_key).
    func setKey(_ key: SymmetricKey, for chatId: String) {
        chatKeys[chatId] = key
        encryptedKeys.removeValue(forKey: chatId)
        encryptedKeyFingerprints.removeValue(forKey: chatId)
    }

    /// Create or return the originating-device key for a new chat.
    func createKeyForNewChat(
        _ chatId: String,
        generateKey: @escaping @Sendable () async -> SymmetricKey = { await CryptoManager.shared.generateChatKey() }
    ) async -> SymmetricKey {
        if let existing = chatKeys[chatId] {
            return existing
        }
        let capturedGeneration = generation
        let key = await generateKey()
        // Another first send (or server sync) may have installed the key while
        // generation was suspended. Never overwrite its key and wrapper.
        if let existing = chatKeys[chatId] { return existing }
        if capturedGeneration == generation && !Task.isCancelled {
            chatKeys[chatId] = key
        }
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
    func loadChatKeys(from chats: [(chatId: String, encryptedChatKey: String)], masterKey: SymmetricKey) async {
        let capturedGeneration = generation
        let crypto = CryptoManager.shared
        let batchSize = 20

        for (index, entry) in chats.enumerated() {
            guard capturedGeneration == generation, !Task.isCancelled else { return }
            let (chatId, encryptedChatKey) = entry
            do {
                let chatKey = try await crypto.unwrapChatKey(
                    encryptedChatKeyBase64: encryptedChatKey,
                    masterKey: masterKey
                )
                guard capturedGeneration == generation, !Task.isCancelled else { return }
                chatKeys[chatId] = chatKey
                rememberEncryptedKey(encryptedChatKey, for: chatId)
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

        guard capturedGeneration == generation, !Task.isCancelled else { return }
        isReady = true
        NativeSyncPerfLog.info("phase=chatKeyBulkLoad requested=\(chats.count) cached=\(chatKeys.count)")
    }

    /// Unwrap and cache a single chat key (for newly loaded chats).
    @discardableResult
    func loadChatKey(chatId: String, encryptedChatKey: String, masterKey: SymmetricKey) async -> Bool {
        let capturedGeneration = generation
        let crypto = CryptoManager.shared
        do {
            let chatKey = try await crypto.unwrapChatKey(
                encryptedChatKeyBase64: encryptedChatKey,
                masterKey: masterKey
            )
            guard capturedGeneration == generation, !Task.isCancelled else { return false }
            chatKeys[chatId] = chatKey
            rememberEncryptedKey(encryptedChatKey, for: chatId)
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
    func loadChatKey(chatId: String, wrappers: [ChatKeyWrapperRecord], masterKey: SymmetricKey) async -> Bool {
        let capturedGeneration = generation
        for wrapper in ChatKeyWrapperRecord.orderedMasterWrappers(wrappers, for: chatId) {
            guard capturedGeneration == generation, !Task.isCancelled else { return false }
            if !shouldLoadServerKey(chatId: chatId, encryptedChatKey: wrapper.encryptedChatKey) {
                return true
            }
            if await loadChatKey(
                chatId: chatId,
                encryptedChatKey: wrapper.encryptedChatKey,
                masterKey: masterKey
            ) {
                return capturedGeneration == generation && !Task.isCancelled
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
        guard let chatKey = chatKeys[chatId] else {
            if NativeSyncPerfLog.verboseCrypto {
                print("[ChatKeyManager] \(fieldName) decrypt skipped missing key chat=\(chatId.prefix(8))")
            }
            return nil
        }
        do {
            let value = try await CryptoManager.shared.decryptContent(
                base64String: encryptedValue, key: chatKey
            )
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
        guard let chatKey = chatKeys[chatId] else { return nil }
        do {
            return try await CryptoManager.shared.decryptContent(
                base64String: encryptedContent, key: chatKey
            )
        } catch {
            print("[ChatKeyManager] Message decrypt failed for chat \(chatId.prefix(8)): \(error)")
            return nil
        }
    }

    // MARK: - Cleanup

    /// Remove a single chat key (on chat delete).
    func removeKey(for chatId: String) {
        chatKeys.removeValue(forKey: chatId)
        encryptedKeys.removeValue(forKey: chatId)
        encryptedKeyFingerprints.removeValue(forKey: chatId)
    }

    /// Clear all keys (on logout).
    func clearAll() {
        generation = UUID()
        chatKeys.removeAll()
        encryptedKeys.removeAll()
        encryptedKeyFingerprints.removeAll()
        isReady = false
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

struct ChatKeyWrapperRecord: Decodable, Sendable {
    let id: String?
    let hashedChatId: String
    let keyType: String
    let encryptedChatKey: String
    let wrapperVersion: Int?
    let createdAt: String?

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
    private var entriesByHashedEmbedId: [String: [EmbedKeyRecord]] = [:]
    private var keyCache: [String: SymmetricKey] = [:]
    private var chatIdHashCache: [String: String] = [:]

    private init() {}

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
    }

    func key(
        for embed: EmbedRecord,
        chatId: String,
        allEmbeds: [String: EmbedRecord],
        visited: Set<String> = []
    ) async -> SymmetricKey? {
        let capturedGeneration = generation
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
            guard capturedGeneration == generation, !Task.isCancelled else { return nil }
            keyCache[cacheKey(embedId: embed.id, chatId: chatId)] = parentKey
            return parentKey
        }

        guard capturedGeneration == generation, !Task.isCancelled else { return nil }
        let hashedEmbedId = sha256Hex(embed.id)
        guard let entries = entriesByHashedEmbedId[hashedEmbedId], !entries.isEmpty else {
            if NativeSyncPerfLog.verboseCrypto {
                print("[EmbedKeyManager] missing key entries embed=\(embed.id.prefix(8)) hash=\(hashedEmbedId.prefix(12))")
            }
            return nil
        }

        if let masterEntry = entries.first(where: { $0.keyType == "master" }),
           let masterKey = await currentMasterKey(),
           let embedKey = await decryptWrappedKey(masterEntry.encryptedEmbedKey, wrappingKey: masterKey) {
            guard capturedGeneration == generation, !Task.isCancelled else { return nil }
            keyCache[cacheKey(embedId: embed.id, chatId: chatId)] = embedKey
            if NativeSyncPerfLog.verboseCrypto {
                print("[EmbedKeyManager] unwrapped master embed=\(embed.id.prefix(8))")
            }
            return embedKey
        }

        guard capturedGeneration == generation, !Task.isCancelled else { return nil }
        let hashedChatId = embed.hashedChatId ?? chatIdHash(chatId)
        let chatEntries = entries.filter { entry in
            entry.keyType == "chat" && (entry.hashedChatId == hashedChatId || entry.hashedChatId == nil)
        }
        for entry in chatEntries {
            guard capturedGeneration == generation, !Task.isCancelled else { return nil }
            guard let chatKey = ChatKeyManager.shared.key(for: chatId),
                  let embedKey = await decryptWrappedKey(entry.encryptedEmbedKey, wrappingKey: chatKey) else {
                continue
            }
            guard capturedGeneration == generation, !Task.isCancelled else { return nil }
            keyCache[cacheKey(embedId: embed.id, chatId: chatId)] = embedKey
            if NativeSyncPerfLog.verboseCrypto {
                print("[EmbedKeyManager] unwrapped chat embed=\(embed.id.prefix(8)) chat=\(chatId.prefix(8))")
            }
            return embedKey
        }

        if NativeSyncPerfLog.verboseCrypto {
            print("[EmbedKeyManager] unwrap failed embed=\(embed.id.prefix(8)) entries=\(entries.count) hasChatKey=\(ChatKeyManager.shared.hasKey(for: chatId))")
        }
        return nil
    }

    func clearAll() {
        generation = UUID()
        entriesByHashedEmbedId.removeAll()
        keyCache.removeAll()
        chatIdHashCache.removeAll()
    }

    func removeKeys(for chatId: String) {
        let hashedChatId = chatIdHash(chatId)
        entriesByHashedEmbedId = entriesByHashedEmbedId.compactMapValues { entries in
            let retained = entries.filter { $0.hashedChatId != hashedChatId }
            return retained.isEmpty ? nil : retained
        }
        keyCache = keyCache.filter { !$0.key.hasSuffix(":\(chatId)") }
        chatIdHashCache.removeValue(forKey: chatId)
    }

    private func currentMasterKey() async -> SymmetricKey? {
        guard let userId = await AuthManager.currentUserId() else { return nil }
        return try? await CryptoManager.shared.loadMasterKey(for: userId)
    }

    private func decryptWrappedKey(_ encrypted: String, wrappingKey: SymmetricKey) async -> SymmetricKey? {
        guard let data = try? await CryptoManager.shared.decryptBlob(base64String: encrypted, key: wrappingKey) else {
            return nil
        }
        return SymmetricKey(data: data)
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
