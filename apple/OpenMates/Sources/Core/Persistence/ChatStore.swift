// Chat store with offline persistence backing via SwiftData.
// Holds decrypted chat list and per-chat message arrays in memory.
// Persists to OfflineStore on every mutation for cold-boot and offline access.

import Foundation
import SwiftUI

@MainActor
final class ChatStore: ObservableObject {
    @Published var chats: [Chat] = []
    @Published private var messagesByChat: [String: [Message]] = [:]
    @Published private var embedsByChat: [String: [String: EmbedRecord]] = [:]

    private var bridge: OfflineSyncBridge?
    private var persistenceSuppressionDepth = 0

    func setBridge(_ bridge: OfflineSyncBridge) {
        self.bridge = bridge
    }

    func performWithoutPersistence(_ updates: () -> Void) {
        persistenceSuppressionDepth += 1
        updates()
        persistenceSuppressionDepth = max(0, persistenceSuppressionDepth - 1)
    }

    // MARK: - Chat operations

    func upsertChat(_ chat: Chat) {
        if let index = chats.firstIndex(where: { $0.id == chat.id }) {
            logMetadataMerge(existing: chats[index], incoming: chat)
            chats[index] = chats[index].merged(with: chat)
        } else {
            chats.append(chat)
            if NativeSyncPerfLog.verboseCrypto {
                print("[ChatStore] insert chat id=\(chat.id.prefix(8)) title=\(chat.title != nil) category=\(chat.category != nil) icon=\(chat.icon != nil) summary=\(chat.chatSummary != nil) encryptedTitle=\(chat.encryptedTitle != nil)")
            }
        }
        sortChats()
        persistIfAllowed { $0.onChatsReceived([chat]) }
    }

    func upsertChats(_ newChats: [Chat]) {
        for chat in newChats {
            if let index = chats.firstIndex(where: { $0.id == chat.id }) {
                logMetadataMerge(existing: chats[index], incoming: chat)
                chats[index] = chats[index].merged(with: chat)
            } else {
                chats.append(chat)
                if NativeSyncPerfLog.verboseCrypto {
                    print("[ChatStore] insert chat id=\(chat.id.prefix(8)) title=\(chat.title != nil) category=\(chat.category != nil) icon=\(chat.icon != nil) summary=\(chat.chatSummary != nil) encryptedTitle=\(chat.encryptedTitle != nil)")
                }
            }
        }
        sortChats()
        persistIfAllowed { $0.onChatsReceived(newChats) }
    }

    func removeChat(_ chatId: String) {
        chats.removeAll { $0.id == chatId }
        messagesByChat.removeValue(forKey: chatId)
        persistIfAllowed { $0.onChatDeleted(chatId) }
    }

    func clearInMemory() {
        chats.removeAll()
        messagesByChat.removeAll()
        embedsByChat.removeAll()
    }

    func makeSyncClientState(clientSuggestionsCount: Int) -> SyncClientState {
        let versions = chats.reduce(into: [String: [String: Int]]()) { result, chat in
            var chatVersions: [String: Int] = [:]
            if let messagesV = chat.messagesV {
                chatVersions["messages_v"] = messagesV
            }
            if let titleV = chat.titleV {
                chatVersions["title_v"] = titleV
            }
            if let draftV = chat.draftV {
                chatVersions["draft_v"] = draftV
            }
            if !chatVersions.isEmpty {
                result[chat.id] = chatVersions
            }
        }
        let embedIds = Set(embedsByChat.values.flatMap { $0.keys }).sorted()
        return SyncClientState(
            clientChatVersions: versions,
            clientChatIds: chats.map(\.id),
            clientSuggestionsCount: clientSuggestionsCount,
            clientEmbedIds: embedIds
        )
    }

    func chat(for id: String) -> Chat? {
        chats.first { $0.id == id }
    }

    func updateLastVisibleMessage(chatId: String, messageId: String) {
        guard let index = chats.firstIndex(where: { $0.id == chatId }) else { return }
        chats[index] = chats[index].withLastVisibleMessage(messageId)
        persistIfAllowed { $0.onChatsReceived([chats[index]]) }
    }

    // MARK: - Message operations

    func messages(for chatId: String) -> [Message] {
        messagesByChat[chatId] ?? []
    }

    func embeds(for chatId: String) -> [EmbedRecord] {
        Array((embedsByChat[chatId] ?? [:]).values)
    }

    func setMessages(for chatId: String, messages: [Message]) {
        let sorted = messages.sorted { a, b in a.createdAt < b.createdAt }
        messagesByChat[chatId] = sorted
        persistIfAllowed { $0.onMessagesReceived(sorted, chatId: chatId) }
    }

    func appendMessage(_ message: Message, to chatId: String) {
        var msgs = messagesByChat[chatId] ?? []
        if let index = msgs.firstIndex(where: { $0.id == message.id }) {
            msgs[index] = message
        } else {
            msgs.append(message)
        }
        messagesByChat[chatId] = msgs
        persistIfAllowed { $0.onMessagesReceived([message], chatId: chatId) }
    }

    func upsertEmbeds(_ embeds: [EmbedRecord], for chatId: String) {
        guard !embeds.isEmpty else { return }
        var current = embedsByChat[chatId] ?? [:]
        for embed in embeds {
            current[embed.id] = embed
        }
        embedsByChat[chatId] = current
        persistIfAllowed { $0.onEmbedsReceived(embeds, chatId: chatId) }
        prefetchEmbedMediaIfOnlinePath(embeds)
    }

    func applySyncedContent(
        messagesByChat incomingMessages: [String: [Message]],
        embedsByChat incomingEmbeds: [String: [EmbedRecord]]
    ) {
        let start = NativeSyncPerfLog.now()
        var nextMessages = messagesByChat
        for (chatId, messages) in incomingMessages {
            nextMessages[chatId] = messages.sorted { $0.createdAt < $1.createdAt }
        }
        if !incomingMessages.isEmpty {
            messagesByChat = nextMessages
        }

        var nextEmbeds = embedsByChat
        for (chatId, embeds) in incomingEmbeds where !embeds.isEmpty {
            var current = nextEmbeds[chatId] ?? [:]
            for embed in embeds {
                current[embed.id] = embed
            }
            nextEmbeds[chatId] = current
        }
        if !incomingEmbeds.isEmpty {
            embedsByChat = nextEmbeds
        }

        persistIfAllowed {
            $0.onSyncContentReceived(
                messagesByChat: incomingMessages,
                embedsByChat: incomingEmbeds
            )
        }
        prefetchEmbedMediaIfOnlinePath(incomingEmbeds.values.flatMap { $0 })
        let messageCount = incomingMessages.values.reduce(0) { $0 + $1.count }
        let embedCount = incomingEmbeds.values.reduce(0) { $0 + $1.count }
        NativeSyncPerfLog.info(
            "phase=chatStoreApplySyncedContent chats=\(incomingMessages.count) messages=\(messageCount) embedChats=\(incomingEmbeds.count) embeds=\(embedCount) publishMs=\(NativeSyncPerfLog.ms(since: start))"
        )
    }

    func updateMessage(id: String, in chatId: String, content: String) {
        guard var msgs = messagesByChat[chatId],
              let index = msgs.firstIndex(where: { $0.id == id }) else { return }
        let old = msgs[index]
        let updated = Message(
            id: old.id, chatId: old.chatId, role: old.role,
            content: content, encryptedContent: old.encryptedContent,
            createdAt: old.createdAt,
            updatedAt: ISO8601DateFormatter().string(from: Date()),
            appId: old.appId, isStreaming: false, embedRefs: old.embedRefs,
            modelName: old.modelName
        )
        msgs[index] = updated
        messagesByChat[chatId] = msgs
        persistIfAllowed { $0.onMessagesReceived([updated], chatId: chatId) }
    }

    // MARK: - Sorting

    var sortedChats: [Chat] {
        chats.sorted { a, b in
            (a.lastMessageDate ?? .distantPast) > (b.lastMessageDate ?? .distantPast)
        }
    }

    var pinnedChats: [Chat] {
        sortedChats.filter { $0.isPinned == true }
    }

    var unpinnedChats: [Chat] {
        sortedChats.filter { $0.isPinned != true && $0.isArchived != true }
    }

    private func sortChats() {
        chats.sort { a, b in
            (a.lastMessageDate ?? .distantPast) > (b.lastMessageDate ?? .distantPast)
        }
    }

    private func logMetadataMerge(existing: Chat, incoming: Chat) {
        let preservedTitle = existing.title != nil && incoming.title == nil
        let preservedCategory = existing.category != nil && incoming.category == nil
        let preservedIcon = existing.icon != nil && incoming.icon == nil
        let preservedSummary = existing.chatSummary != nil && incoming.chatSummary == nil
        if NativeSyncPerfLog.verboseCrypto {
            print("[ChatStore] merge chat id=\(existing.id.prefix(8)) incomingTitle=\(incoming.title != nil) existingTitle=\(existing.title != nil) preserveTitle=\(preservedTitle) preserveCategory=\(preservedCategory) preserveIcon=\(preservedIcon) preserveSummary=\(preservedSummary)")
        }
    }

    private func persistIfAllowed(_ action: (OfflineSyncBridge) -> Void) {
        guard persistenceSuppressionDepth == 0, let bridge else { return }
        action(bridge)
    }

    private func prefetchEmbedMediaIfOnlinePath(_ embeds: [EmbedRecord]) {
        guard persistenceSuppressionDepth == 0 else { return }
        EmbedMediaOfflineCache.prefetchEmbeds(embeds)
    }
}

private extension Chat {
    func merged(with incoming: Chat) -> Chat {
        Chat(
            id: id,
            title: incoming.title ?? title,
            lastMessageAt: incoming.lastMessageAt ?? lastMessageAt,
            createdAt: createdAt,
            updatedAt: incoming.updatedAt ?? updatedAt,
            isArchived: incoming.isArchived ?? isArchived,
            isPinned: incoming.isPinned ?? isPinned,
            appId: incoming.appId ?? appId,
            category: incoming.category ?? category,
            icon: incoming.icon ?? icon,
            chatSummary: incoming.chatSummary ?? chatSummary,
            encryptedTitle: incoming.encryptedTitle ?? encryptedTitle,
            encryptedCategory: incoming.encryptedCategory ?? encryptedCategory,
            encryptedIcon: incoming.encryptedIcon ?? encryptedIcon,
            encryptedChatSummary: incoming.encryptedChatSummary ?? encryptedChatSummary,
            encryptedChatKey: incoming.encryptedChatKey ?? encryptedChatKey,
            messagesV: incoming.messagesV ?? messagesV,
            titleV: incoming.titleV ?? titleV,
            draftV: incoming.draftV ?? draftV,
            lastVisibleMessageId: incoming.lastVisibleMessageId ?? lastVisibleMessageId
        )
    }

    func withLastVisibleMessage(_ messageId: String) -> Chat {
        Chat(
            id: id,
            title: title,
            lastMessageAt: lastMessageAt,
            createdAt: createdAt,
            updatedAt: updatedAt,
            isArchived: isArchived,
            isPinned: isPinned,
            appId: appId,
            category: category,
            icon: icon,
            chatSummary: chatSummary,
            encryptedTitle: encryptedTitle,
            encryptedCategory: encryptedCategory,
            encryptedIcon: encryptedIcon,
            encryptedChatSummary: encryptedChatSummary,
            encryptedChatKey: encryptedChatKey,
            messagesV: messagesV,
            titleV: titleV,
            draftV: draftV,
            lastVisibleMessageId: messageId
        )
    }
}
