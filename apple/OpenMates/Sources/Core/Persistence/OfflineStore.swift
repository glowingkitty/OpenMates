// Offline persistence layer — stores chats, messages, and embeds locally using SwiftData.
// Enables full offline access to previously loaded conversations.
// Syncs with the in-memory ChatStore and resolves conflicts on reconnection.

import SwiftData
import Foundation

// MARK: - SwiftData Models

@Model
final class PersistedChat {
    @Attribute(.unique) var id: String
    var title: String?
    var encryptedTitle: String?
    var encryptedChatKey: String?
    var icon: String?
    var category: String?
    var appId: String?
    var isPinned: Bool
    var isArchived: Bool
    var isPrivate: Bool
    var lastMessageAt: String?
    var createdAt: String
    var updatedAt: String?

    @Relationship(deleteRule: .cascade, inverse: \PersistedMessage.chat)
    var messages: [PersistedMessage]?

    init(from chat: Chat) {
        self.id = chat.id
        self.title = chat.title
        self.encryptedTitle = chat.encryptedTitle
        self.encryptedChatKey = chat.encryptedChatKey
        self.appId = chat.appId
        self.isPinned = chat.isPinned ?? false
        self.isArchived = chat.isArchived ?? false
        self.isPrivate = true
        self.lastMessageAt = chat.lastMessageAt
        self.createdAt = chat.createdAt
        self.updatedAt = chat.updatedAt
    }

    func toChat() -> Chat {
        Chat(
            id: id, title: title, lastMessageAt: lastMessageAt,
            createdAt: createdAt, updatedAt: updatedAt,
            isArchived: isArchived, isPinned: isPinned,
            appId: appId, encryptedTitle: encryptedTitle,
            encryptedChatKey: encryptedChatKey
        )
    }
}

@Model
final class PersistedMessage {
    @Attribute(.unique) var id: String
    var chatId: String
    var role: String
    var content: String?
    var encryptedContent: String?
    var createdAt: String
    var updatedAt: String?
    var appId: String?

    var chat: PersistedChat?

    init(from message: Message) {
        self.id = message.id
        self.chatId = message.chatId
        self.role = message.role.rawValue
        self.content = message.content
        self.encryptedContent = message.encryptedContent
        self.createdAt = message.createdAt
        self.updatedAt = message.updatedAt
        self.appId = message.appId
    }

    func toMessage() -> Message {
        Message(
            id: id, chatId: chatId,
            role: MessageRole(rawValue: role) ?? .user,
            content: content, encryptedContent: encryptedContent,
            createdAt: createdAt,
            updatedAt: updatedAt, appId: appId,
            isStreaming: false, embedRefs: nil
        )
    }
}

@Model
final class PersistedEmbed {
    @Attribute(.unique) var id: String
    var embedType: String
    var title: String?
    var status: String?
    var chatId: String?
    var rawDataJSON: Data?
    var childEmbedIdsJSON: Data?
    var createdAt: String?

    init(from embed: EmbedRecord) {
        self.id = embed.id
        self.embedType = embed.type
        self.title = EmbedType(rawValue: embed.type)?.displayName
        self.status = embed.status.rawValue
        self.createdAt = embed.createdAt
        if case .raw(let dict) = embed.data {
            self.rawDataJSON = try? JSONSerialization.data(
                withJSONObject: dict.mapValues { $0.value })
        }
        self.childEmbedIdsJSON = try? JSONEncoder().encode(embed.childEmbedIds)
    }
}

// MARK: - Pending offline actions (queued for sync when online)

@Model
final class PendingOfflineAction {
    @Attribute(.unique) var id: String
    var actionType: String  // "send_message", "delete_message", "create_chat"
    var payloadJSON: Data?
    var createdAt: Date
    var retryCount: Int

    init(type: String, payload: [String: Any]) {
        self.id = UUID().uuidString
        self.actionType = type
        self.payloadJSON = try? JSONSerialization.data(withJSONObject: payload)
        self.createdAt = Date()
        self.retryCount = 0
    }
}

// MARK: - Offline Store Actor

@MainActor
final class OfflineStore: ObservableObject {
    static let shared = OfflineStore()

    @Published private(set) var isOffline = false
    @Published private(set) var pendingActionCount = 0

    private var modelContainer: ModelContainer?
    private var modelContext: ModelContext?

    private init() {
        do {
            let schema = Schema([
                PersistedChat.self,
                PersistedMessage.self,
                PersistedEmbed.self,
                PendingOfflineAction.self,
            ])
            let config = ModelConfiguration(
                "OpenMatesOffline",
                schema: schema,
                isStoredInMemoryOnly: false
            )
            modelContainer = try ModelContainer(for: schema, configurations: [config])
            modelContext = modelContainer?.mainContext
        } catch {
            print("[Offline] Failed to create SwiftData container: \(error)")
        }
    }

    // MARK: - Save chats from sync

    func persistChats(_ chats: [Chat]) {
        guard let context = modelContext else { return }
        for chat in chats {
            let targetId = chat.id
            let descriptor = FetchDescriptor<PersistedChat>(
                predicate: #Predicate { $0.id == targetId }
            )
            if let existing = try? context.fetch(descriptor).first {
                existing.title = chat.title
                existing.encryptedTitle = chat.encryptedTitle
                existing.appId = chat.appId
                existing.isPinned = chat.isPinned ?? false
                existing.isArchived = chat.isArchived ?? false
                existing.lastMessageAt = chat.lastMessageAt
                existing.updatedAt = chat.updatedAt
            } else {
                context.insert(PersistedChat(from: chat))
            }
        }
        try? context.save()
    }

    func persistMessages(_ messages: [Message], chatId: String) {
        guard let context = modelContext else { return }

        let targetChatId = chatId
        let chatDescriptor = FetchDescriptor<PersistedChat>(
            predicate: #Predicate { $0.id == targetChatId }
        )
        let persistedChat = try? context.fetch(chatDescriptor).first

        for message in messages {
            let targetId = message.id
            let descriptor = FetchDescriptor<PersistedMessage>(
                predicate: #Predicate { $0.id == targetId }
            )
            if let existing = try? context.fetch(descriptor).first {
                existing.content = message.content
                existing.updatedAt = message.updatedAt
            } else {
                let persisted = PersistedMessage(from: message)
                persisted.chat = persistedChat
                context.insert(persisted)
            }
        }
        try? context.save()
    }

    func persistEmbeds(_ embeds: [EmbedRecord]) {
        guard let context = modelContext else { return }
        for embed in embeds {
            let targetId = embed.id
            let descriptor = FetchDescriptor<PersistedEmbed>(
                predicate: #Predicate { $0.id == targetId }
            )
            if (try? context.fetch(descriptor).first) == nil {
                context.insert(PersistedEmbed(from: embed))
            }
        }
        try? context.save()
    }

    // MARK: - Load from offline store

    func loadChats() -> [Chat] {
        guard let context = modelContext else { return [] }
        let descriptor = FetchDescriptor<PersistedChat>(
            sortBy: [SortDescriptor(\.lastMessageAt, order: .reverse)]
        )
        return (try? context.fetch(descriptor))?.map { $0.toChat() } ?? []
    }

    func loadMessages(chatId: String) -> [Message] {
        guard let context = modelContext else { return [] }
        let targetChatId = chatId
        let descriptor = FetchDescriptor<PersistedMessage>(
            predicate: #Predicate { $0.chatId == targetChatId },
            sortBy: [SortDescriptor(\.createdAt)]
        )
        return (try? context.fetch(descriptor))?.map { $0.toMessage() } ?? []
    }

    // MARK: - Delete

    func deleteChat(_ chatId: String) {
        guard let context = modelContext else { return }
        let targetChatId = chatId
        let chatDescriptor = FetchDescriptor<PersistedChat>(
            predicate: #Predicate { $0.id == targetChatId }
        )
        if let chat = try? context.fetch(chatDescriptor).first {
            context.delete(chat)
        }
        let msgDescriptor = FetchDescriptor<PersistedMessage>(
            predicate: #Predicate { $0.chatId == targetChatId }
        )
        for msg in (try? context.fetch(msgDescriptor)) ?? [] {
            context.delete(msg)
        }
        try? context.save()
    }

    func clearAll() {
        guard let context = modelContext else { return }
        try? context.delete(model: PersistedChat.self)
        try? context.delete(model: PersistedMessage.self)
        try? context.delete(model: PersistedEmbed.self)
        try? context.delete(model: PendingOfflineAction.self)
        try? context.save()
    }

    // MARK: - Pending offline actions

    func queueOfflineAction(type: String, payload: [String: Any]) {
        guard let context = modelContext else { return }
        context.insert(PendingOfflineAction(type: type, payload: payload))
        try? context.save()
        updatePendingCount()
    }

    func loadPendingActions() -> [PendingOfflineAction] {
        guard let context = modelContext else { return [] }
        let descriptor = FetchDescriptor<PendingOfflineAction>(
            sortBy: [SortDescriptor(\.createdAt)]
        )
        return (try? context.fetch(descriptor)) ?? []
    }

    func removePendingAction(_ id: String) {
        guard let context = modelContext else { return }
        let descriptor = FetchDescriptor<PendingOfflineAction>(
            predicate: #Predicate { $0.id == id }
        )
        if let action = try? context.fetch(descriptor).first {
            context.delete(action)
            try? context.save()
        }
        updatePendingCount()
    }

    func incrementRetry(_ id: String) {
        guard let context = modelContext else { return }
        let descriptor = FetchDescriptor<PendingOfflineAction>(
            predicate: #Predicate { $0.id == id }
        )
        if let action = try? context.fetch(descriptor).first {
            action.retryCount += 1
            try? context.save()
        }
    }

    private func updatePendingCount() {
        guard let context = modelContext else { return }
        let descriptor = FetchDescriptor<PendingOfflineAction>()
        pendingActionCount = (try? context.fetchCount(descriptor)) ?? 0
    }

    // MARK: - Network state

    func setOffline(_ offline: Bool) {
        isOffline = offline
        if !offline {
            updatePendingCount()
        }
    }
}
