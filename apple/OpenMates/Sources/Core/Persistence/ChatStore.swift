// Chat store with offline persistence backing via SwiftData.
// Holds decrypted chat list and per-chat message arrays in memory.
// Persists to OfflineStore on every mutation for cold-boot and offline access.

import Foundation
import SwiftUI

@MainActor
final class ChatStore: ObservableObject {
    @Published var chats: [Chat] = []
    @Published private var messagesByChat: [String: [Message]] = [:]

    private var bridge: OfflineSyncBridge?

    func setBridge(_ bridge: OfflineSyncBridge) {
        self.bridge = bridge
    }

    // MARK: - Chat operations

    func upsertChat(_ chat: Chat) {
        if let index = chats.firstIndex(where: { $0.id == chat.id }) {
            chats[index] = chat
        } else {
            chats.append(chat)
        }
        sortChats()
        bridge?.onChatsReceived([chat])
    }

    func upsertChats(_ newChats: [Chat]) {
        for chat in newChats {
            if let index = chats.firstIndex(where: { $0.id == chat.id }) {
                chats[index] = chat
            } else {
                chats.append(chat)
            }
        }
        sortChats()
        bridge?.onChatsReceived(newChats)
    }

    func removeChat(_ chatId: String) {
        chats.removeAll { $0.id == chatId }
        messagesByChat.removeValue(forKey: chatId)
        bridge?.onChatDeleted(chatId)
    }

    func clearInMemory() {
        chats.removeAll()
        messagesByChat.removeAll()
    }

    func chat(for id: String) -> Chat? {
        chats.first { $0.id == id }
    }

    // MARK: - Message operations

    func messages(for chatId: String) -> [Message] {
        messagesByChat[chatId] ?? []
    }

    func setMessages(for chatId: String, messages: [Message]) {
        let sorted = messages.sorted { a, b in a.createdAt < b.createdAt }
        messagesByChat[chatId] = sorted
        bridge?.onMessagesReceived(sorted, chatId: chatId)
    }

    func appendMessage(_ message: Message, to chatId: String) {
        var msgs = messagesByChat[chatId] ?? []
        if let index = msgs.firstIndex(where: { $0.id == message.id }) {
            msgs[index] = message
        } else {
            msgs.append(message)
        }
        messagesByChat[chatId] = msgs
        bridge?.onMessagesReceived([message], chatId: chatId)
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
            appId: old.appId, isStreaming: false, embedRefs: old.embedRefs
        )
        msgs[index] = updated
        messagesByChat[chatId] = msgs
        bridge?.onMessagesReceived([updated], chatId: chatId)
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
}
