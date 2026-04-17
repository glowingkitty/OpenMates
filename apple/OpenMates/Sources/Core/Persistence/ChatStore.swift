// In-memory chat store with persistence backing.
// Holds decrypted chat list and per-chat message arrays.
// Mirrors the web app's IndexedDB-based chat store.

import Foundation
import SwiftUI

@MainActor
final class ChatStore: ObservableObject {
    @Published var chats: [Chat] = []
    @Published private var messagesByChat: [String: [Message]] = [:]

    // MARK: - Chat operations

    func upsertChat(_ chat: Chat) {
        if let index = chats.firstIndex(where: { $0.id == chat.id }) {
            chats[index] = chat
        } else {
            chats.append(chat)
        }
        sortChats()
    }

    func removeChat(_ chatId: String) {
        chats.removeAll { $0.id == chatId }
        messagesByChat.removeValue(forKey: chatId)
    }

    func chat(for id: String) -> Chat? {
        chats.first { $0.id == id }
    }

    // MARK: - Message operations

    func messages(for chatId: String) -> [Message] {
        messagesByChat[chatId] ?? []
    }

    func setMessages(for chatId: String, messages: [Message]) {
        messagesByChat[chatId] = messages.sorted { a, b in
            a.createdAt < b.createdAt
        }
    }

    func appendMessage(_ message: Message, to chatId: String) {
        var msgs = messagesByChat[chatId] ?? []
        if let index = msgs.firstIndex(where: { $0.id == message.id }) {
            msgs[index] = message
        } else {
            msgs.append(message)
        }
        messagesByChat[chatId] = msgs
    }

    func updateMessage(id: String, in chatId: String, content: String) {
        guard var msgs = messagesByChat[chatId],
              let index = msgs.firstIndex(where: { $0.id == id }) else { return }
        let old = msgs[index]
        msgs[index] = Message(
            id: old.id, chatId: old.chatId, role: old.role,
            content: content, encryptedContent: old.encryptedContent,
            contentIv: old.contentIv, createdAt: old.createdAt,
            updatedAt: ISO8601DateFormatter().string(from: Date()),
            appId: old.appId, isStreaming: false, embedRefs: old.embedRefs
        )
        messagesByChat[chatId] = msgs
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
