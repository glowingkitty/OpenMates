// Anonymous free-usage service for the native Apple app.
// Keeps unauthenticated chat content local until signup while still using the
// public official-cloud inference budget endpoint for text-only turns.
// Anonymous chat keys are wrapped with an install-local session key in Keychain,
// then re-wrapped with the account master key during signup/login promotion.

import Combine
import CryptoKit
import Foundation

@MainActor
final class AnonymousFreeUsageService: ObservableObject {
    static let shared = AnonymousFreeUsageService()

    @Published private(set) var status: AnonymousFreeUsageStatus?

    private let api = APIClient.shared
    private let crypto = CryptoManager.shared
    private let defaults = OpenMatesSharedEnvironment.defaults

    private init() {}

    var canSendAnonymously: Bool {
        status?.active == true
    }

    var anonymousId: String {
        if let existing = defaults.string(forKey: Self.anonymousIdKey), !existing.isEmpty {
            return existing
        }
        let value = UUID().uuidString
        defaults.set(value, forKey: Self.anonymousIdKey)
        return value
    }

    func refreshStatus() async {
        do {
            let response: AnonymousFreeUsageStatus = try await api.request(.get, path: "/v1/anonymous/free-usage/status")
            status = response
        } catch {
            status = AnonymousFreeUsageStatus(active: false, reason: "unavailable", resetAt: nil, cta: nil)
        }
    }

    func isAnonymousChat(_ chatId: String) -> Bool {
        anonymousChatIds.contains(chatId)
    }

    func createAnonymousChat(now: String) async throws -> Chat {
        let chatId = "anonymous-\(UUID().uuidString)"
        let key = await ChatKeyManager.shared.createKeyForNewChat(chatId)
        try storeAnonymousChatKey(key, chatId: chatId)
        addAnonymousChatId(chatId)
        return Chat(
            id: chatId,
            title: nil,
            lastMessageAt: nil,
            createdAt: now,
            updatedAt: now,
            isArchived: false,
            isPinned: false,
            appId: "ai",
            encryptedTitle: nil,
            encryptedChatKey: nil,
            messagesV: 0,
            titleV: 0,
            draftV: 0
        )
    }

    func createAnonymousChatWithMessage(_ message: String, now: String, chatStore: ChatStore) async throws -> String {
        guard canSendAnonymously else { throw AnonymousFreeUsageError.unavailable }
        var chat = try await createAnonymousChat(now: now)
        let chatKey = try await ensureAnonymousChatKey(chatId: chat.id)
        chatStore.upsertChat(chat)

        let notice = Message(
            id: "\(chat.id.suffix(10))-notice",
            chatId: chat.id,
            role: .system,
            content: AppStrings.anonymousFreeUsageFeatureNotice,
            encryptedContent: nil,
            createdAt: now,
            updatedAt: nil,
            appId: nil,
            isStreaming: false,
            embedRefs: nil
        )
        chatStore.appendMessage(notice, to: chat.id)

        let userMessageId = "\(chat.id.suffix(10))-\(UUID().uuidString)"
        let assistantMessageId = "\(chat.id.suffix(10))-\(UUID().uuidString)"
        let userMessage = Message(
            id: userMessageId,
            chatId: chat.id,
            role: .user,
            content: message,
            encryptedContent: try await crypto.encryptContent(message, key: chatKey),
            createdAt: now,
            updatedAt: nil,
            appId: nil,
            isStreaming: false,
            embedRefs: nil
        )
        chat = copyAnonymousChat(chat, title: message, lastMessageAt: now, messagesV: 1)
        chatStore.upsertChat(chat)
        chatStore.appendMessage(userMessage, to: chat.id)

        let response = try await sendAnonymousMessage(
            chatId: chat.id,
            assistantMessageId: assistantMessageId,
            plaintext: message,
            history: []
        )
        let assistantCreatedAt = Self.isoString(from: Date())
        let assistant = Message(
            id: response.messageId,
            chatId: response.chatId,
            role: .assistant,
            content: response.assistant,
            encryptedContent: try await crypto.encryptContent(response.assistant, key: chatKey),
            createdAt: assistantCreatedAt,
            updatedAt: nil,
            appId: response.category,
            isStreaming: false,
            embedRefs: nil,
            modelName: response.modelName
        )
        chat = copyAnonymousChat(chat, title: message, lastMessageAt: assistantCreatedAt, category: response.category, messagesV: 2)
        chatStore.upsertChat(chat)
        chatStore.appendMessage(assistant, to: chat.id)
        return chat.id
    }

    func ensureAnonymousChatKey(chatId: String) async throws -> SymmetricKey {
        if let key = ChatKeyManager.shared.key(for: chatId) {
            return key
        }
        guard let encrypted = anonymousChatKeys[chatId] else {
            let key = await ChatKeyManager.shared.createKeyForNewChat(chatId)
            try storeAnonymousChatKey(key, chatId: chatId)
            addAnonymousChatId(chatId)
            return key
        }
        let key = try unwrapAnonymousChatKey(encrypted)
        ChatKeyManager.shared.setKey(key, for: chatId)
        return key
    }

    func loadAnonymousChats(into chatStore: ChatStore) async {
        let ids = anonymousChatIds
        guard !ids.isEmpty else { return }
        for chatId in ids {
            _ = try? await ensureAnonymousChatKey(chatId: chatId)
        }
        let chats = OfflineStore.shared.loadChats().filter { ids.contains($0.id) }
        chatStore.performWithoutPersistence {
            chatStore.upsertChats(chats)
            for chat in chats {
                let messages = OfflineStore.shared.loadLatestMessageWindow(chatId: chat.id)
                if !messages.isEmpty {
                    chatStore.setMessages(for: chat.id, messages: messages)
                }
            }
        }
    }

    func sendAnonymousMessage(
        chatId: String,
        assistantMessageId: String,
        plaintext: String,
        history: [AnonymousHistoryMessage]
    ) async throws -> AnonymousChatResponse {
        let response: AnonymousChatResponse = try await api.request(
            .post,
            path: "/v1/anonymous/chat/stream",
            body: AnonymousChatRequest(
                anonymousId: anonymousId,
                clientChatId: chatId,
                clientMessageId: assistantMessageId,
                plaintextMessage: plaintext,
                messageHistory: history
            )
        )
        return response
    }

    func promoteAnonymousChats(chatStore: ChatStore, wsManager: WebSocketManager?, userId: String?) async -> [String] {
        guard let wsManager,
              let userId,
              let masterKey = try? await crypto.loadMasterKey(for: userId) else { return [] }

        var promotedIds: [String] = []
        for chatId in anonymousChatIds {
            guard var chat = chatStore.chat(for: chatId) else { continue }
            let messages = chatStore.messages(for: chatId).filter(Self.isPromotableMessage)
            guard !messages.isEmpty,
                  let chatKey = try? await ensureAnonymousChatKey(chatId: chatId),
                  let encryptedChatKey = try? await crypto.wrapChatKey(chatKey, masterKey: masterKey) else { continue }
            let encryptedTitle: String?
            if let existing = chat.encryptedTitle {
                encryptedTitle = existing
            } else if let title = chat.title {
                encryptedTitle = try? await crypto.encryptContent(title, key: chatKey)
            } else {
                encryptedTitle = nil
            }
            let encryptedCategory: String?
            if let existing = chat.encryptedCategory {
                encryptedCategory = existing
            } else if let category = chat.category {
                encryptedCategory = try? await crypto.encryptContent(category, key: chatKey)
            } else {
                encryptedCategory = nil
            }
            let encryptedHistory = await encryptedHistoryMessages(messages, chatKey: chatKey)
            guard !encryptedHistory.isEmpty else { continue }

            chat = copyChatForPromotion(
                chat,
                encryptedChatKey: encryptedChatKey,
                encryptedTitle: encryptedTitle,
                encryptedCategory: encryptedCategory,
                messages: messages
            )
            do {
                try await wsManager.send(WSOutboundMessage(
                    type: "encrypted_chat_metadata",
                    payload: promotionPayload(chat: chat, messageHistory: encryptedHistory)
                ))
                chatStore.upsertChat(chat)
                promotedIds.append(chatId)
            } catch {
                print("[AnonymousFreeUsage] Failed to promote anonymous chat \(chatId.prefix(8)): \(error)")
            }
        }

        if !promotedIds.isEmpty {
            removeAnonymousChatIds(promotedIds)
        }
        return promotedIds
    }

    private func encryptedHistoryMessages(_ messages: [Message], chatKey: SymmetricKey) async -> [[String: Any]] {
        var encrypted: [[String: Any]] = []
        for message in messages {
            guard let content = message.content,
                  let encryptedContent = try? await crypto.encryptContent(content, key: chatKey) else { continue }
            var payload: [String: Any] = [
                "message_id": message.id,
                "chat_id": message.chatId,
                "role": message.role.rawValue,
                "created_at": Self.unixSeconds(from: message.createdAt),
                "encrypted_content": encryptedContent
            ]
            if let sender = try? await crypto.encryptContent(message.role == .user ? "user" : "assistant", key: chatKey) {
                payload["encrypted_sender_name"] = sender
            }
            if let appId = message.appId,
               let encryptedCategory = try? await crypto.encryptContent(appId, key: chatKey) {
                payload["encrypted_category"] = encryptedCategory
            }
            if let modelName = message.modelName,
               let encryptedModelName = try? await crypto.encryptContent(modelName, key: chatKey) {
                payload["encrypted_model_name"] = encryptedModelName
            }
            encrypted.append(payload)
        }
        return encrypted
    }

    private func copyChatForPromotion(
        _ chat: Chat,
        encryptedChatKey: String,
        encryptedTitle: String?,
        encryptedCategory: String?,
        messages: [Message]
    ) -> Chat {
        let firstCreatedAt = messages.first?.createdAt ?? chat.createdAt
        let lastEditedAt = messages.last?.createdAt ?? chat.updatedAt ?? firstCreatedAt
        return Chat(
            id: chat.id,
            title: chat.title,
            lastMessageAt: lastEditedAt,
            createdAt: chat.createdAt,
            updatedAt: lastEditedAt,
            isArchived: chat.isArchived,
            isPinned: chat.isPinned,
            appId: chat.appId ?? "ai",
            category: chat.category,
            icon: chat.icon,
            chatSummary: chat.chatSummary,
            encryptedTitle: encryptedTitle,
            encryptedCategory: encryptedCategory,
            encryptedIcon: chat.encryptedIcon,
            encryptedChatSummary: chat.encryptedChatSummary,
            encryptedChatKey: encryptedChatKey,
            messagesV: messages.count,
            titleV: encryptedTitle == nil ? chat.titleV : max(chat.titleV ?? 0, 1),
            draftV: chat.draftV,
            lastVisibleMessageId: chat.lastVisibleMessageId,
            parentId: chat.parentId,
            isSubChat: chat.isSubChat,
            subChatSettings: chat.subChatSettings,
            budgetLimit: chat.budgetLimit,
            budgetSpent: chat.budgetSpent,
            encryptedActiveFocusId: chat.encryptedActiveFocusId,
            activeFocusId: chat.activeFocusId
        )
    }

    private func copyAnonymousChat(
        _ chat: Chat,
        title: String,
        lastMessageAt: String,
        category: String? = nil,
        messagesV: Int
    ) -> Chat {
        Chat(
            id: chat.id,
            title: chat.title ?? String(title.prefix(64)),
            lastMessageAt: lastMessageAt,
            createdAt: chat.createdAt,
            updatedAt: lastMessageAt,
            isArchived: chat.isArchived,
            isPinned: chat.isPinned,
            appId: chat.appId ?? "ai",
            category: category ?? chat.category,
            icon: chat.icon,
            chatSummary: chat.chatSummary,
            encryptedTitle: chat.encryptedTitle,
            encryptedCategory: chat.encryptedCategory,
            encryptedIcon: chat.encryptedIcon,
            encryptedChatSummary: chat.encryptedChatSummary,
            encryptedChatKey: chat.encryptedChatKey,
            messagesV: messagesV,
            titleV: chat.titleV,
            draftV: chat.draftV,
            lastVisibleMessageId: chat.lastVisibleMessageId,
            parentId: chat.parentId,
            isSubChat: chat.isSubChat,
            subChatSettings: chat.subChatSettings,
            budgetLimit: chat.budgetLimit,
            budgetSpent: chat.budgetSpent,
            encryptedActiveFocusId: chat.encryptedActiveFocusId,
            activeFocusId: chat.activeFocusId
        )
    }

    private func promotionPayload(chat: Chat, messageHistory: [[String: Any]]) -> [String: Any] {
        var payload: [String: Any] = [
            "chat_id": chat.id,
            "created_at": Self.unixSeconds(from: chat.createdAt),
            "message_history": messageHistory,
            "versions": [
                "messages_v": chat.messagesV ?? messageHistory.count,
                "title_v": chat.titleV ?? 0,
                "last_edited_overall_timestamp": Self.unixSeconds(from: chat.lastMessageAt ?? chat.updatedAt ?? chat.createdAt)
            ]
        ]
        if let encryptedChatKey = chat.encryptedChatKey { payload["encrypted_chat_key"] = encryptedChatKey }
        if let encryptedTitle = chat.encryptedTitle { payload["encrypted_title"] = encryptedTitle }
        if let encryptedIcon = chat.encryptedIcon { payload["encrypted_icon"] = encryptedIcon }
        if let encryptedCategory = chat.encryptedCategory { payload["encrypted_chat_category"] = encryptedCategory }
        return payload
    }

    private func storeAnonymousChatKey(_ key: SymmetricKey, chatId: String) throws {
        var keys = anonymousChatKeys
        keys[chatId] = try wrapAnonymousChatKey(key)
        defaults.set(keys, forKey: Self.anonymousChatKeysKey)
    }

    private func wrapAnonymousChatKey(_ key: SymmetricKey) throws -> String {
        let sessionKey = try localSessionKey()
        let rawKey = key.withUnsafeBytes { Data($0) }
        let sealed = try AES.GCM.seal(rawKey, using: sessionKey)
        let nonce = sealed.nonce.withUnsafeBytes { Data($0) }
        var combined = Data()
        combined.append(nonce)
        combined.append(sealed.ciphertext)
        combined.append(sealed.tag)
        return combined.base64EncodedString()
    }

    private func unwrapAnonymousChatKey(_ encrypted: String) throws -> SymmetricKey {
        guard let data = Data(base64Encoded: encrypted), data.count >= 12 + 16 else {
            throw AnonymousFreeUsageError.invalidLocalKey
        }
        let nonce = try AES.GCM.Nonce(data: data.prefix(12))
        let ciphertext = Data(data.dropFirst(12).dropLast(16))
        let tag = Data(data.suffix(16))
        let sealed = try AES.GCM.SealedBox(nonce: nonce, ciphertext: ciphertext, tag: tag)
        let raw = try AES.GCM.open(sealed, using: try localSessionKey())
        return SymmetricKey(data: raw)
    }

    private func localSessionKey() throws -> SymmetricKey {
        if let existing = try KeychainHelper.load(key: Self.localSessionKeychainKey) {
            return SymmetricKey(data: existing)
        }
        let key = SymmetricKey(size: .bits256)
        try KeychainHelper.save(key: Self.localSessionKeychainKey, data: key.withUnsafeBytes { Data($0) })
        return key
    }

    private var anonymousChatIds: [String] {
        defaults.stringArray(forKey: Self.anonymousChatIdsKey) ?? []
    }

    private var anonymousChatKeys: [String: String] {
        defaults.dictionary(forKey: Self.anonymousChatKeysKey) as? [String: String] ?? [:]
    }

    private func addAnonymousChatId(_ chatId: String) {
        var ids = anonymousChatIds
        guard !ids.contains(chatId) else { return }
        ids.append(chatId)
        defaults.set(ids, forKey: Self.anonymousChatIdsKey)
    }

    private func removeAnonymousChatIds(_ chatIds: [String]) {
        let removeSet = Set(chatIds)
        defaults.set(anonymousChatIds.filter { !removeSet.contains($0) }, forKey: Self.anonymousChatIdsKey)
        var keys = anonymousChatKeys
        for chatId in chatIds {
            keys.removeValue(forKey: chatId)
        }
        defaults.set(keys, forKey: Self.anonymousChatKeysKey)
    }

    private static func isPromotableMessage(_ message: Message) -> Bool {
        message.role != .system && (message.content?.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty == false)
    }

    private static func unixSeconds(from isoString: String) -> Int {
        let fractional = ISO8601DateFormatter()
        fractional.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        if let date = fractional.date(from: isoString) {
            return Int(date.timeIntervalSince1970)
        }
        return Int((ISO8601DateFormatter().date(from: isoString) ?? Date()).timeIntervalSince1970)
    }

    private static func isoString(from date: Date) -> String {
        ISO8601DateFormatter().string(from: date)
    }

    private static let anonymousIdKey = "openmates.apple.anonymous.id.v1"
    private static let anonymousChatIdsKey = "openmates.apple.anonymous.chat_ids.v1"
    private static let anonymousChatKeysKey = "openmates.apple.anonymous.chat_keys.v1"
    private static let localSessionKeychainKey = "openmates.anonymousFreeUsage.sessionKey.v1"
}

struct AnonymousFreeUsageStatus: Decodable {
    let active: Bool
    let reason: String?
    let resetAt: String?
    let cta: String?
}

struct AnonymousChatRequest: Encodable {
    let anonymousId: String
    let clientChatId: String
    let clientMessageId: String
    let plaintextMessage: String
    let messageHistory: [AnonymousHistoryMessage]
}

struct AnonymousHistoryMessage: Encodable {
    let role: String
    let content: String
    let createdAt: Int
    let senderName: String?
}

struct AnonymousChatResponse: Decodable {
    let status: String
    let chatId: String
    let messageId: String
    let assistant: String
    let category: String?
    let modelName: String?
    let creditsCharged: Int?
    let followUpSuggestions: [String]
}

enum AnonymousFreeUsageError: LocalizedError {
    case invalidLocalKey
    case unavailable

    var errorDescription: String? {
        nil
    }
}
