// Chat key manager — in-memory cache of per-chat AES-256 decryption keys.
// Mirrors the web app's ChatKeyManager.ts. Each chat has its own random key
// that is stored on the server wrapped (encrypted) with the user's master key.
// At load time, we unwrap each chat's key and cache it here for fast decryption
// of messages, titles, and embeds within that chat.
// Unwrapping and the chat-list / message-window decryption run in the shared
// Rust core as one batched call each (generated `batchUnwrapChatKeys`,
// `batchDecryptChatMetadata`, `batchDecryptMessages`; plan
// apple-client-core-migration A3); this type keeps the in-memory key cache and
// its revocation fences until the cache moves into the core (A4).
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
    private let unwrapKeys: @MainActor ([WrappedChatKeyRecord], Data) async throws -> [UnwrappedChatKeyRecord]
    private let decryptMetadataBatch: @MainActor ([EncryptedChatMetadataRecord]) async throws -> [ChatMetadataRecord]
    private let decryptMessageBatch: @MainActor (Data, [EncryptedMessageRecord]) async throws -> [MessageFieldsRecord]
    private let decryptContent: @MainActor (String, SymmetricKey) async throws -> String
    private var chatKeys: [String: SymmetricKey] = [:]
    private var encryptedKeys: [String: String] = [:]
    private var encryptedKeyFingerprints: [String: String] = [:]
    // Existing callers use this token across awaits before installing keys or
    // publishing decrypted state. A single-chat revocation must invalidate it.
    var cacheGeneration: UUID { materialGeneration }

    /// Whether chat keys have been loaded from the initial sync
    @Published var isReady = false

    /// The batch closures default to the Rust core; tests inject suspending
    /// fakes to prove the revocation fences. Each runs off the main actor in the
    /// core's decryption pool; only the result is applied here.
    init(
        unwrapKeys: @escaping @MainActor ([WrappedChatKeyRecord], Data) async throws -> [UnwrappedChatKeyRecord] = {
            try await batchUnwrapChatKeys(masterKey: $1, wrapped: $0)
        },
        decryptMetadataBatch: @escaping @MainActor ([EncryptedChatMetadataRecord]) async throws -> [ChatMetadataRecord] = {
            try await batchDecryptChatMetadata(chats: $0)
        },
        decryptMessageBatch: @escaping @MainActor (Data, [EncryptedMessageRecord]) async throws -> [MessageFieldsRecord] = {
            try await batchDecryptMessages(chatKey: $0, messages: $1)
        },
        decryptContent: @escaping @MainActor (String, SymmetricKey) async throws -> String = {
            try await CryptoManager.shared.decryptContent(base64String: $0, key: $1)
        }
    ) {
        self.unwrapKeys = unwrapKeys
        self.decryptMetadataBatch = decryptMetadataBatch
        self.decryptMessageBatch = decryptMessageBatch
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

    /// Unwrap and cache chat keys for a batch of chats with one core call.
    /// Called at startup after the master key is loaded from Keychain. Fences
    /// are captured before the call; an entry revoked while the core works is
    /// unwrapped but never installed.
    func loadChatKeys(from chats: [(chatId: String, encryptedChatKey: String)], masterKey: SymmetricKey,
                      isCurrent operationIsCurrent: @escaping @MainActor () -> Bool = { true }) async {
        let capturedGeneration = generation
        guard !Task.isCancelled, operationIsCurrent() else { return }
        var fences: [String: KeyRevocationFence] = [:]
        var records: [WrappedChatKeyRecord] = []
        records.reserveCapacity(chats.count)
        for (chatId, encryptedChatKey) in chats where fences[chatId] == nil {
            fences[chatId] = fence(for: chatId)
            records.append(WrappedChatKeyRecord(chatId: chatId, encryptedChatKey: encryptedChatKey))
        }
        if !records.isEmpty {
            let results: [UnwrappedChatKeyRecord]
            do {
                results = try await unwrapKeys(records, masterKey.withUnsafeBytes { Data($0) })
            } catch {
                print("[ChatKeyManager] Bulk key unwrap failed requested=\(records.count): \(error)")
                results = []
            }
            guard capturedGeneration == generation, !Task.isCancelled, operationIsCurrent() else { return }
            var installedAny = false
            for (record, result) in zip(records, results) {
                guard let capturedFence = fences[record.chatId], isCurrent(capturedFence, for: record.chatId) else { continue }
                if install(result, wrapper: record.encryptedChatKey, notify: false) { installedAny = true }
            }
            // One notification for the whole batch: listeners re-scan all keys,
            // and a per-key Task + post made the bulk load cost ~100 µs/key.
            if installedAny { notifyEmbedKeyMaterialAvailable() }
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
        let record = WrappedChatKeyRecord(chatId: chatId, encryptedChatKey: encryptedChatKey)
        let result: UnwrappedChatKeyRecord?
        do {
            result = try await unwrapKeys([record], masterKey.withUnsafeBytes { Data($0) }).first
        } catch {
            print("[ChatKeyManager] Failed to unwrap key for chat \(chatId.prefix(8)): \(error)")
            return false
        }
        guard isCurrent(capturedFence, for: chatId), operationIsCurrent(), let result else { return false }
        return install(result, wrapper: encryptedChatKey)
    }

    /// Cache one core unwrap result; logs failures without key material.
    @discardableResult
    private func install(_ result: UnwrappedChatKeyRecord, wrapper: String, notify: Bool = true) -> Bool {
        switch result.outcome {
        case .unwrapped(let rawKey):
            chatKeys[result.chatId] = SymmetricKey(data: rawKey)
            rememberEncryptedKey(wrapper, for: result.chatId)
            if notify { notifyEmbedKeyMaterialAvailable() }
            if NativeSyncPerfLog.verboseCrypto {
                print("[ChatKeyManager] loaded key chat=\(result.chatId.prefix(8)) cached=\(chatKeys.count)")
            }
            return true
        case .failed(let reason):
            print("[ChatKeyManager] Failed to unwrap key for chat \(result.chatId.prefix(8)): \(reason)")
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

    // MARK: - Batched decryption (Rust core)

    /// Decrypt the chat-list metadata (title, category, icon, summary, active
    /// focus) of many chats with one core call. Only missing plaintext fields
    /// are sent; `replaceEmptyTitle` also replaces an empty title (chat list).
    /// Chats without a cached key, failed fields and chats revoked while the
    /// core worked come back unchanged. Order and count match the input.
    func decryptMetadata(_ chats: [Chat], replaceEmptyTitle: Bool) async -> [Chat] {
        var records: [EncryptedChatMetadataRecord] = []
        var recordIndex: [Int: Int] = [:]
        var fences: [Int: KeyRevocationFence] = [:]
        for (index, chat) in chats.enumerated() {
            guard let key = chatKeys[chat.id] else {
                if NativeSyncPerfLog.verboseCrypto {
                    print("[ChatKeyManager] metadata decrypt skipped missing key chat=\(chat.id.prefix(8))")
                }
                continue
            }
            let needsTitle = replaceEmptyTitle ? chat.title?.isEmpty != false : chat.title == nil
            let record = EncryptedChatMetadataRecord(
                chatId: chat.id, chatKey: key.withUnsafeBytes { Data($0) },
                encryptedTitle: needsTitle ? chat.encryptedTitle : nil,
                encryptedCategory: chat.category == nil ? chat.encryptedCategory : nil,
                encryptedIcon: chat.icon == nil ? chat.encryptedIcon : nil,
                encryptedChatSummary: chat.chatSummary == nil ? chat.encryptedChatSummary : nil,
                encryptedActiveFocusId: chat.activeFocusId == nil ? chat.encryptedActiveFocusId : nil)
            guard record.encryptedTitle != nil || record.encryptedCategory != nil || record.encryptedIcon != nil
                || record.encryptedChatSummary != nil || record.encryptedActiveFocusId != nil else { continue }
            recordIndex[index] = records.count
            fences[index] = fence(for: chat.id)
            records.append(record)
        }
        guard !records.isEmpty else { return chats }
        let results: [ChatMetadataRecord]
        do {
            results = try await decryptMetadataBatch(records)
        } catch {
            print("[ChatKeyManager] metadata batch decrypt failed chats=\(records.count): \(error)")
            return chats
        }
        guard results.count == records.count else {
            print("[ChatKeyManager] metadata batch returned \(results.count) of \(records.count) chats")
            return chats
        }
        return chats.enumerated().map { index, chat in
            guard let position = recordIndex[index], let capturedFence = fences[index],
                  isCurrent(capturedFence, for: chat.id) else { return chat }
            let fields = results[position]
            var decrypted = chat
            if let value = Self.plaintext(fields.title, field: "encrypted_title", id: chat.id) { decrypted.title = value }
            if let value = Self.plaintext(fields.category, field: "encrypted_category", id: chat.id) { decrypted.category = value }
            if let value = Self.plaintext(fields.icon, field: "encrypted_icon", id: chat.id) { decrypted.icon = value }
            if let value = Self.plaintext(fields.chatSummary, field: "encrypted_chat_summary", id: chat.id) {
                decrypted.chatSummary = value
            }
            if let value = Self.plaintext(fields.activeFocusId, field: "encrypted_active_focus_id", id: chat.id) {
                decrypted.activeFocusId = value
            }
            return decrypted
        }
    }

    /// Single-chat form of `decryptMetadata(_:replaceEmptyTitle:)`.
    func decryptMetadata(of chat: Chat, replaceEmptyTitle: Bool) async -> Chat {
        let decrypted = await decryptMetadata([chat], replaceEmptyTitle: replaceEmptyTitle)
        return decrypted.first ?? chat
    }

    /// Decrypt the encrypted content and identity fields of a message window of
    /// one chat with one core call. Only missing plaintext fields are sent.
    /// Without a cached key, after a failed batch or a revocation during the
    /// call, the messages come back unchanged. Order and count match the input.
    func decryptMessages(_ messages: [Message], chatId: String) async -> [Message] {
        guard let key = chatKeys[chatId] else {
            let encryptedCount = messages.filter { $0.encryptedContent != nil }.count
            if encryptedCount > 0 {
                print("[ChatViewModel][decrypt] messages skipped chat=\(chatId.prefix(8)) encrypted=\(encryptedCount) reason=missingChatKey")
            }
            return messages
        }
        let records = messages.map { message in
            EncryptedMessageRecord(
                messageId: message.id,
                encryptedContent: message.content?.isEmpty != false ? message.encryptedContent : nil,
                encryptedPiiMappings: message.piiMappings == nil ? message.encryptedPIIMappings : nil,
                encryptedThinkingContent: message.thinkingContent == nil ? message.encryptedThinkingContent : nil,
                encryptedSenderName: message.senderName == nil ? message.encryptedSenderName : nil,
                encryptedCategory: message.category == nil ? message.encryptedCategory : nil,
                encryptedModelName: message.modelName == nil ? message.encryptedModelName : nil)
        }
        guard records.contains(where: {
            $0.encryptedContent != nil || $0.encryptedPiiMappings != nil || $0.encryptedThinkingContent != nil
                || $0.encryptedSenderName != nil || $0.encryptedCategory != nil || $0.encryptedModelName != nil
        }) else { return messages }
        let capturedFence = fence(for: chatId)
        let results: [MessageFieldsRecord]
        do {
            results = try await decryptMessageBatch(key.withUnsafeBytes { Data($0) }, records)
        } catch {
            print("[ChatKeyManager] message batch decrypt failed chat=\(chatId.prefix(8)) messages=\(records.count): \(error)")
            return messages
        }
        guard isCurrent(capturedFence, for: chatId) else { return messages }
        guard results.count == messages.count else {
            print("[ChatKeyManager] message batch returned \(results.count) of \(messages.count) messages")
            return messages
        }
        let decoder = JSONDecoder()
        return zip(messages, results).map { message, fields in
            var decrypted = message
            let content = Self.plaintext(fields.content, field: "content", id: chatId)
            if let json = Self.plaintext(fields.piiMappings, field: "pii_mappings", id: chatId),
               let data = json.data(using: .utf8),
               let mappings = try? decoder.decode([PIIMapping].self, from: data) {
                decrypted.piiMappings = mappings
            }
            if let value = Self.plaintext(fields.thinkingContent, field: "thinking_content", id: chatId) {
                decrypted.thinkingContent = value
            }
            decrypted.applyDecryptedDisplayFields(
                content: content,
                modelName: Self.plaintext(fields.modelName, field: "model_name", id: chatId),
                senderName: Self.plaintext(fields.senderName, field: "sender_name", id: chatId),
                category: Self.plaintext(fields.category, field: "category", id: chatId))
            return decrypted
        }
    }

    /// Plaintext of one core field result; a failure is logged with its typed
    /// reason and the id prefix only (never content or key material).
    private static func plaintext(_ outcome: FieldDecryptOutcome?, field: String, id: String) -> String? {
        switch outcome {
        case .decrypted(let value):
            return value
        case .failed(let reason):
            print("[ChatKeyManager] \(field) decrypt failed for \(id.prefix(8)): \(reason)")
            return nil
        case nil:
            return nil
        }
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
        // Table-driven hex: `String(format:)` per byte cost ~1 µs each, 32 per key.
        let digits = Array("0123456789abcdef".utf8)
        var hex: [UInt8] = []
        hex.reserveCapacity(64)
        for byte in SHA256.hash(data: Data(encryptedChatKey.utf8)) {
            hex.append(digits[Int(byte >> 4)])
            hex.append(digits[Int(byte & 0x0f)])
        }
        return String(decoding: hex, as: UTF8.self)
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
