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
    var encryptedCategory: String?
    var encryptedIcon: String?
    var encryptedChatSummary: String?
    var encryptedChatKey: String?
    var icon: String?
    var category: String?
    var chatSummary: String?
    var appId: String?
    var isPinned: Bool
    var isArchived: Bool
    var isPrivate: Bool
    var lastMessageAt: String?
    var lastVisibleMessageId: String?
    var messagesV: Int?
    var titleV: Int?
    var draftV: Int?
    var createdAt: String
    var updatedAt: String?
    var parentId: String?
    var isSubChat: Bool?
    var subChatSettingsJSON: Data?
    var budgetLimit: Double?
    var budgetSpent: Double?
    var encryptedActiveFocusId: String?
    var activeFocusId: String?

    @Relationship(deleteRule: .cascade, inverse: \PersistedMessage.chat)
    var messages: [PersistedMessage]?

    init(from chat: Chat) {
        self.id = chat.id
        self.title = chat.title
        self.encryptedTitle = chat.encryptedTitle
        self.encryptedCategory = chat.encryptedCategory
        self.encryptedIcon = chat.encryptedIcon
        self.encryptedChatSummary = chat.encryptedChatSummary
        self.encryptedChatKey = chat.encryptedChatKey
        self.icon = chat.icon
        self.category = chat.category
        self.chatSummary = chat.chatSummary
        self.appId = chat.appId
        self.isPinned = chat.isPinned ?? false
        self.isArchived = chat.isArchived ?? false
        self.isPrivate = true
        self.lastMessageAt = chat.lastMessageAt
        self.lastVisibleMessageId = chat.lastVisibleMessageId
        self.messagesV = chat.messagesV
        self.titleV = chat.titleV
        self.draftV = chat.draftV
        self.createdAt = chat.createdAt
        self.updatedAt = chat.updatedAt
        self.parentId = chat.parentId
        self.isSubChat = chat.isSubChat
        self.subChatSettingsJSON = try? JSONEncoder().encode(chat.subChatSettings)
        self.budgetLimit = chat.budgetLimit
        self.budgetSpent = chat.budgetSpent
        self.encryptedActiveFocusId = chat.encryptedActiveFocusId
        self.activeFocusId = chat.activeFocusId
    }

    func toChat() -> Chat {
        Chat(
            id: id, title: title, lastMessageAt: lastMessageAt,
            createdAt: createdAt, updatedAt: updatedAt,
            isArchived: isArchived, isPinned: isPinned,
            appId: appId, category: category, icon: icon, chatSummary: chatSummary,
            encryptedTitle: encryptedTitle,
            encryptedCategory: encryptedCategory,
            encryptedIcon: encryptedIcon,
            encryptedChatSummary: encryptedChatSummary,
            encryptedChatKey: encryptedChatKey,
            messagesV: messagesV,
            titleV: titleV,
            draftV: draftV,
            lastVisibleMessageId: lastVisibleMessageId,
            parentId: parentId,
            isSubChat: isSubChat,
            subChatSettings: subChatSettingsJSON.flatMap { try? JSONDecoder().decode(SubChatSettings.self, from: $0) },
            budgetLimit: budgetLimit,
            budgetSpent: budgetSpent,
            encryptedActiveFocusId: encryptedActiveFocusId,
            activeFocusId: activeFocusId
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
    var modelName: String?
    var embedRefsJSON: Data?
    var piiMappingsJSON: Data?
    var encryptedPIIMappings: String?

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
        self.modelName = message.modelName
        self.embedRefsJSON = try? JSONEncoder().encode(message.embedRefs)
        self.piiMappingsJSON = try? JSONEncoder().encode(message.piiMappings)
        self.encryptedPIIMappings = message.encryptedPIIMappings
    }

    func toMessage() -> Message {
        let embedRefs = embedRefsJSON.flatMap { try? JSONDecoder().decode([EmbedRef].self, from: $0) }
        let piiMappings = piiMappingsJSON.flatMap { try? JSONDecoder().decode([PIIMapping].self, from: $0) }
        return Message(
            id: id, chatId: chatId,
            role: MessageRole(rawValue: role) ?? .user,
            content: content, encryptedContent: encryptedContent,
            createdAt: createdAt,
            updatedAt: updatedAt, appId: appId,
            isStreaming: false, embedRefs: embedRefs,
            modelName: modelName,
            piiMappings: piiMappings,
            encryptedPIIMappings: encryptedPIIMappings
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
    var encryptedContent: String?
    var encryptedType: String?
    var encryptedTextPreview: String?
    var parentEmbedId: String?
    var appId: String?
    var skillId: String?
    var embedIds: String?
    var hashedChatId: String?
    var hashedUserId: String?
    var rawDataJSON: Data?
    var childEmbedIdsJSON: Data?
    var createdAt: String?

    init(from embed: EmbedRecord, chatId: String?) {
        self.id = embed.id
        self.embedType = embed.type
        self.title = EmbedType(rawValue: embed.type)?.displayName
        self.status = embed.status.rawValue
        self.chatId = chatId
        self.encryptedContent = embed.encryptedContent
        self.encryptedType = embed.encryptedType
        self.encryptedTextPreview = embed.encryptedTextPreview
        self.parentEmbedId = embed.parentEmbedId
        self.appId = embed.appId
        self.skillId = embed.skillId
        self.embedIds = embed.embedIds
        self.hashedChatId = embed.hashedChatId
        self.hashedUserId = embed.hashedUserId
        self.createdAt = embed.createdAt
        if case .raw(let dict) = embed.data {
            self.rawDataJSON = try? JSONSerialization.data(
                withJSONObject: dict.mapValues { $0.value })
        }
        self.childEmbedIdsJSON = try? JSONEncoder().encode(embed.childEmbedIds)
    }

    func update(from embed: EmbedRecord, chatId: String?) {
        embedType = embed.type
        title = EmbedType(rawValue: embed.type)?.displayName
        status = embed.status.rawValue
        self.chatId = chatId ?? self.chatId
        encryptedContent = embed.encryptedContent
        encryptedType = embed.encryptedType
        encryptedTextPreview = embed.encryptedTextPreview
        parentEmbedId = embed.parentEmbedId
        appId = embed.appId
        skillId = embed.skillId
        embedIds = embed.embedIds
        hashedChatId = embed.hashedChatId
        hashedUserId = embed.hashedUserId
        createdAt = embed.createdAt
        if case .raw(let dict) = embed.data {
            rawDataJSON = try? JSONSerialization.data(withJSONObject: dict.mapValues { $0.value })
        }
        childEmbedIdsJSON = try? JSONEncoder().encode(embed.childEmbedIds)
    }

    func toEmbed() -> EmbedRecord {
        let raw = rawDataJSON.flatMap { data -> [String: AnyCodable]? in
            guard let object = try? JSONSerialization.jsonObject(with: data) as? [String: Any] else { return nil }
            return object.mapValues { AnyCodable($0) }
        }
        return EmbedRecord(
            id: id,
            type: embedType,
            status: EmbedStatus(rawValue: status ?? "") ?? .finished,
            data: raw.map { .raw($0) },
            encryptedContent: encryptedContent,
            encryptedType: encryptedType,
            encryptedTextPreview: encryptedTextPreview,
            parentEmbedId: parentEmbedId,
            appId: appId,
            skillId: skillId,
            embedIds: embedIds,
            hashedChatId: hashedChatId,
            hashedUserId: hashedUserId,
            createdAt: createdAt
        )
    }
}

@Model
final class PersistedEmbedKey {
    @Attribute(.unique) var id: String
    var hashedEmbedId: String
    var keyType: String
    var hashedChatId: String?
    var encryptedEmbedKey: String

    init(from key: EmbedKeyRecord) {
        self.id = Self.stableId(for: key)
        self.hashedEmbedId = key.hashedEmbedId
        self.keyType = key.keyType
        self.hashedChatId = key.hashedChatId
        self.encryptedEmbedKey = key.encryptedEmbedKey
    }

    func update(from key: EmbedKeyRecord) {
        hashedEmbedId = key.hashedEmbedId
        keyType = key.keyType
        hashedChatId = key.hashedChatId
        encryptedEmbedKey = key.encryptedEmbedKey
    }

    func toEmbedKey() -> EmbedKeyRecord {
        EmbedKeyRecord(
            hashedEmbedId: hashedEmbedId,
            keyType: keyType,
            hashedChatId: hashedChatId,
            encryptedEmbedKey: encryptedEmbedKey
        )
    }

    static func stableId(for key: EmbedKeyRecord) -> String {
        [
            key.hashedEmbedId,
            key.keyType,
            key.hashedChatId ?? "none",
            key.encryptedEmbedKey
        ].joined(separator: ":")
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
                PersistedEmbedKey.self,
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
                existing.encryptedCategory = chat.encryptedCategory
                existing.encryptedIcon = chat.encryptedIcon
                existing.encryptedChatSummary = chat.encryptedChatSummary
                existing.encryptedChatKey = chat.encryptedChatKey
                existing.icon = chat.icon
                existing.category = chat.category
                existing.chatSummary = chat.chatSummary
                existing.appId = chat.appId
                existing.isPinned = chat.isPinned ?? false
                existing.isArchived = chat.isArchived ?? false
                existing.lastMessageAt = chat.lastMessageAt
                existing.updatedAt = chat.updatedAt
                existing.lastVisibleMessageId = chat.lastVisibleMessageId
                existing.messagesV = chat.messagesV
                existing.titleV = chat.titleV
                existing.draftV = chat.draftV
                existing.parentId = chat.parentId
                existing.isSubChat = chat.isSubChat
                existing.subChatSettingsJSON = try? JSONEncoder().encode(chat.subChatSettings)
                existing.budgetLimit = chat.budgetLimit
                existing.budgetSpent = chat.budgetSpent
                existing.encryptedActiveFocusId = chat.encryptedActiveFocusId
                existing.activeFocusId = chat.activeFocusId
            } else {
                context.insert(PersistedChat(from: chat))
            }
        }
        try? context.save()
    }

    func persistMessages(_ messages: [Message], chatId: String) {
        persistMessagesBatch([chatId: messages])
    }

    func persistMessagesBatch(_ messagesByChat: [String: [Message]]) {
        guard let context = modelContext else { return }
        let start = NativeSyncPerfLog.now()
        var savedMessages = 0
        let encoder = JSONEncoder()

        for (chatId, messages) in messagesByChat {
            guard !messages.isEmpty else { continue }
            let targetChatId = chatId
            let chatDescriptor = FetchDescriptor<PersistedChat>(
                predicate: #Predicate { $0.id == targetChatId }
            )
            let persistedChat = try? context.fetch(chatDescriptor).first

            let existingDescriptor = FetchDescriptor<PersistedMessage>(
                predicate: #Predicate { $0.chatId == targetChatId }
            )
            let existingById = Dictionary(
                ((try? context.fetch(existingDescriptor)) ?? []).map { ($0.id, $0) },
                uniquingKeysWith: { first, _ in first }
            )

            for message in messages {
                if let existing = existingById[message.id] {
                    existing.content = message.content
                    existing.encryptedContent = message.encryptedContent
                    existing.updatedAt = message.updatedAt
                    existing.appId = message.appId
                    existing.modelName = message.modelName
                    existing.embedRefsJSON = try? encoder.encode(message.embedRefs)
                } else {
                    let persisted = PersistedMessage(from: message)
                    persisted.chat = persistedChat
                    context.insert(persisted)
                }
                savedMessages += 1
            }
        }

        try? context.save()
        NativeSyncPerfLog.info(
            "phase=offlinePersistMessagesBatch chats=\(messagesByChat.count) messages=\(savedMessages) persistMs=\(NativeSyncPerfLog.ms(since: start))"
        )
    }

    func persistEmbeds(_ embeds: [EmbedRecord], chatId: String) {
        persistEmbedsBatch([chatId: embeds])
    }

    func persistEmbedsBatch(_ embedsByChat: [String: [EmbedRecord]]) {
        guard let context = modelContext else { return }
        let start = NativeSyncPerfLog.now()
        var savedEmbeds = 0

        for (chatId, embeds) in embedsByChat {
            guard !embeds.isEmpty else { continue }
            let targetChatId = chatId
            let existingDescriptor = FetchDescriptor<PersistedEmbed>(
                predicate: #Predicate { $0.chatId == targetChatId }
            )
            let existingById = Dictionary(
                ((try? context.fetch(existingDescriptor)) ?? []).map { ($0.id, $0) },
                uniquingKeysWith: { first, _ in first }
            )

            for embed in embeds {
                if let existing = existingById[embed.id] {
                    existing.update(from: embed, chatId: chatId)
                } else {
                    context.insert(PersistedEmbed(from: embed, chatId: chatId))
                }
                savedEmbeds += 1
            }
        }

        try? context.save()
        NativeSyncPerfLog.info(
            "phase=offlinePersistEmbedsBatch chats=\(embedsByChat.count) embeds=\(savedEmbeds) persistMs=\(NativeSyncPerfLog.ms(since: start))"
        )
    }

    func persistEmbedKeys(_ keys: [EmbedKeyRecord]) {
        guard let context = modelContext else { return }
        for key in keys {
            let targetId = PersistedEmbedKey.stableId(for: key)
            let descriptor = FetchDescriptor<PersistedEmbedKey>(
                predicate: #Predicate { $0.id == targetId }
            )
            if let existing = try? context.fetch(descriptor).first {
                existing.update(from: key)
            } else {
                context.insert(PersistedEmbedKey(from: key))
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

    func loadLatestMessageWindow(chatId: String, limit: Int = ChatStore.boundedWindowSize) -> [Message] {
        guard let context = modelContext else { return [] }
        let targetChatId = chatId
        var descriptor = FetchDescriptor<PersistedMessage>(
            predicate: #Predicate { $0.chatId == targetChatId },
            sortBy: [SortDescriptor(\.createdAt, order: .reverse)]
        )
        descriptor.fetchLimit = limit
        let newestFirst = (try? context.fetch(descriptor)) ?? []
        return newestFirst.map { $0.toMessage() }.sorted { $0.createdAt < $1.createdAt }
    }

    func loadOlderMessageWindow(chatId: String, before messageId: String, limit: Int = ChatStore.boundedWindowSize) -> [Message] {
        guard let context = modelContext else { return [] }
        let targetChatId = chatId
        let boundaryDescriptor = FetchDescriptor<PersistedMessage>(
            predicate: #Predicate { $0.id == messageId }
        )
        guard let boundary = try? context.fetch(boundaryDescriptor).first else { return [] }
        let boundaryCreatedAt = boundary.createdAt
        var descriptor = FetchDescriptor<PersistedMessage>(
            predicate: #Predicate { $0.chatId == targetChatId && $0.createdAt < boundaryCreatedAt },
            sortBy: [SortDescriptor(\.createdAt, order: .reverse)]
        )
        descriptor.fetchLimit = limit
        let newestFirst = (try? context.fetch(descriptor)) ?? []
        return newestFirst.map { $0.toMessage() }.sorted { $0.createdAt < $1.createdAt }
    }

    func loadEmbeds(chatId: String) -> [EmbedRecord] {
        guard let context = modelContext else { return [] }
        let targetChatId = chatId
        let descriptor = FetchDescriptor<PersistedEmbed>(
            predicate: #Predicate { $0.chatId == targetChatId }
        )
        return (try? context.fetch(descriptor))?.map { $0.toEmbed() } ?? []
    }

    func loadEmbedKeys() -> [EmbedKeyRecord] {
        guard let context = modelContext else { return [] }
        let descriptor = FetchDescriptor<PersistedEmbedKey>()
        return (try? context.fetch(descriptor))?.map { $0.toEmbedKey() } ?? []
    }

    func persistedMessageCount() -> Int {
        guard let context = modelContext else { return 0 }
        let descriptor = FetchDescriptor<PersistedMessage>()
        return (try? context.fetchCount(descriptor)) ?? 0
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
        try? context.delete(model: PersistedEmbedKey.self)
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
