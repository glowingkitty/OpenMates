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
            } catch {
                print("[ChatKeyManager] Failed to unwrap key for chat \(chatId.prefix(8)): \(error)")
            }
        }

        isReady = true
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
        } catch {
            print("[ChatKeyManager] Failed to unwrap key for chat \(chatId.prefix(8)): \(error)")
        }
    }

    // MARK: - Content decryption helpers

    /// Decrypt a chat title using the cached chat key.
    func decryptTitle(for chatId: String, encryptedTitle: String) async -> String? {
        guard let chatKey = chatKeys[chatId] else { return nil }
        do {
            return try await CryptoManager.shared.decryptContent(
                base64String: encryptedTitle, key: chatKey
            )
        } catch {
            print("[ChatKeyManager] Title decrypt failed for \(chatId.prefix(8)): \(error)")
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
