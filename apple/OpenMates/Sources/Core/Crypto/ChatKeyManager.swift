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
    private var chatKeys: [String: SymmetricKey] = [:]

    /// Whether chat keys have been loaded from the initial sync
    @Published var isReady = false

    private init() {}

    // MARK: - Key access

    /// Get the decryption key for a specific chat.
    func key(for chatId: String) -> SymmetricKey? {
        chatKeys[chatId]
    }

    /// Store a chat key (after unwrapping from encrypted_chat_key).
    func setKey(_ key: SymmetricKey, for chatId: String) {
        chatKeys[chatId] = key
    }

    /// Create or return the originating-device key for a new chat.
    func createKeyForNewChat(_ chatId: String) async -> SymmetricKey {
        if let existing = chatKeys[chatId] {
            return existing
        }
        let key = await CryptoManager.shared.generateChatKey()
        chatKeys[chatId] = key
        return key
    }

    /// Check if we have a key for a given chat.
    func hasKey(for chatId: String) -> Bool {
        chatKeys[chatId] != nil
    }

    // MARK: - Bulk loading

    /// Unwrap and cache chat keys for a batch of chats.
    /// Called at startup after the master key is loaded from Keychain.
    func loadChatKeys(from chats: [(chatId: String, encryptedChatKey: String)], masterKey: SymmetricKey) async {
        let crypto = CryptoManager.shared

        for (chatId, encryptedChatKey) in chats {
            do {
                let chatKey = try await crypto.unwrapChatKey(
                    encryptedChatKeyBase64: encryptedChatKey,
                    masterKey: masterKey
                )
                chatKeys[chatId] = chatKey
                if NativeSyncPerfLog.verboseCrypto {
                    print("[ChatKeyManager] loaded key chat=\(chatId.prefix(8))")
                }
            } catch {
                print("[ChatKeyManager] Failed to unwrap key for chat \(chatId.prefix(8)): \(error)")
            }
        }

        isReady = true
        NativeSyncPerfLog.info("phase=chatKeyBulkLoad requested=\(chats.count) cached=\(chatKeys.count)")
    }

    /// Unwrap and cache a single chat key (for newly loaded chats).
    func loadChatKey(chatId: String, encryptedChatKey: String, masterKey: SymmetricKey) async {
        let crypto = CryptoManager.shared
        do {
            let chatKey = try await crypto.unwrapChatKey(
                encryptedChatKeyBase64: encryptedChatKey,
                masterKey: masterKey
            )
            chatKeys[chatId] = chatKey
            if NativeSyncPerfLog.verboseCrypto {
                print("[ChatKeyManager] loaded single key chat=\(chatId.prefix(8)) cached=\(chatKeys.count)")
            }
        } catch {
            print("[ChatKeyManager] Failed to unwrap key for chat \(chatId.prefix(8)): \(error)")
        }
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
    }

    /// Clear all keys (on logout).
    func clearAll() {
        chatKeys.removeAll()
        isReady = false
    }
}

@MainActor
final class EmbedKeyManager {
    static let shared = EmbedKeyManager()

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
            keyCache[cacheKey(embedId: embed.id, chatId: chatId)] = parentKey
            return parentKey
        }

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
            keyCache[cacheKey(embedId: embed.id, chatId: chatId)] = embedKey
            if NativeSyncPerfLog.verboseCrypto {
                print("[EmbedKeyManager] unwrapped master embed=\(embed.id.prefix(8))")
            }
            return embedKey
        }

        let hashedChatId = embed.hashedChatId ?? chatIdHash(chatId)
        let chatEntries = entries.filter { entry in
            entry.keyType == "chat" && (entry.hashedChatId == hashedChatId || entry.hashedChatId == nil)
        }
        for entry in chatEntries {
            guard let chatKey = ChatKeyManager.shared.key(for: chatId),
                  let embedKey = await decryptWrappedKey(entry.encryptedEmbedKey, wrappingKey: chatKey) else {
                continue
            }
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
        entriesByHashedEmbedId.removeAll()
        keyCache.removeAll()
        chatIdHashCache.removeAll()
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
