// Offline persistence layer — stores chats, messages, and embeds locally using SwiftData.
// Enables full offline access to previously loaded conversations.
// Syncs with the in-memory ChatStore and resolves conflicts on reconnection.
// Specification: specifications/features/chats/specification.yml
// Assertions: chats.followups.non-destructive-reconciliation, chats.surface.semantic-parity
// Specification: specifications/features/app-skills/code-run/specification.yml
// Assertions: code-run.output.chat-bound-encrypted
// Specification: specifications/features/pii-protection/specification.yml
// Assertions: pii.embed.owner-local-reveal-sync, pii.surface.semantic-parity

// Specification: specifications/features/apple-recent-offline-chats/specification.yml
// Assertions: apple-offline.recent-cohort, apple-offline.local-first, apple-offline.interruption-isolation, apple-offline.snapshot-integrity

import CryptoKit
import Foundation
import SwiftData

// MARK: - SwiftData Models

@Model
final class PersistedChat {
    @Attribute(.unique) var id: String
    var title: String?
    var encryptedTitle: String?
    var encryptedCategory: String?
    var encryptedIcon: String?
    var encryptedChatSummary: String?
    var encryptedFollowUpRequestSuggestions: String?
    var encryptedAutoSpeakResponse: String?
    var encryptedChatKey: String?
    var icon: String?
    var category: String?
    var chatSummary: String?
    var appId: String?
    var isPinned: Bool
    var isArchived: Bool
    var isPrivate: Bool
    var teamId: String?
    var isSharedByOthers: Bool?
    var lastMessageAt: String?
    var lastVisibleMessageId: String?
    var messagesV: Int?
    var titleV: Int?
    var draftV: Int?
    var hasNonEmptyDraft: Bool?
    var clearedDraftV: Int?
    var metadataV: Int?
    var createdAt: String
    var updatedAt: String?
    var lastEditedOverallTimestamp: String?
    var offlineContentMessagesV: Int?
    var offlineContentRecency: String?
    var offlineContentServerCount: Int?
    var offlineContentRowCount: Int?
    var offlineSupplementalContentJSON: Data?
    var parentId: String?
    var isSubChat: Bool?
    var subChatSettingsJSON: Data?
    var budgetLimit: Double?
    var budgetSpent: Double?
    var encryptedFocusPhaseState: String?
    var encryptedActiveFocusId: String?
    var activeFocusId: String?

    @Relationship(deleteRule: .cascade, inverse: \PersistedMessage.chat)
    var messages: [PersistedMessage]?

    init(from chat: Chat) {
        self.id = chat.id
        // A prompt-derived title is presentation state until the server accepts
        // a versioned encrypted title. Do not make it survive a cold launch.
        self.title = (chat.titleV ?? 0) > 0 ? chat.title : nil
        self.encryptedTitle = chat.encryptedTitle
        self.encryptedCategory = chat.encryptedCategory
        self.encryptedIcon = chat.encryptedIcon
        self.encryptedChatSummary = chat.encryptedChatSummary
        self.encryptedFollowUpRequestSuggestions = chat.encryptedFollowUpRequestSuggestions
        self.encryptedAutoSpeakResponse = chat.encryptedAutoSpeakResponse
        self.encryptedChatKey = chat.encryptedChatKey
        self.icon = chat.icon
        self.category = chat.category
        self.chatSummary = chat.chatSummary
        self.appId = chat.appId
        self.isPinned = chat.isPinned ?? false
        self.isArchived = chat.isArchived ?? false
        self.teamId = chat.teamId
        self.isSharedByOthers = chat.isSharedByOthers
        self.isPrivate = chat.isPrivate ?? true
        self.lastMessageAt = chat.lastMessageAt
        self.lastVisibleMessageId = chat.lastVisibleMessageId
        self.messagesV = chat.messagesV
        self.titleV = chat.titleV
        self.draftV = chat.draftV
        self.hasNonEmptyDraft = chat.hasNonEmptyDraft
        self.clearedDraftV = chat.clearedDraftV
        self.metadataV = chat.metadataV
        self.createdAt = chat.createdAt
        self.updatedAt = chat.updatedAt
        self.lastEditedOverallTimestamp = OfflineRecentChatPolicy.recency(of: chat)
        self.parentId = chat.parentId
        self.isSubChat = chat.isSubChat
        self.subChatSettingsJSON = try? JSONEncoder().encode(chat.subChatSettings)
        self.budgetLimit = chat.budgetLimit
        self.budgetSpent = chat.budgetSpent
        self.encryptedFocusPhaseState = chat.encryptedFocusPhaseState
        self.encryptedActiveFocusId = chat.encryptedActiveFocusId
        self.activeFocusId = chat.activeFocusId
    }

    func toChat() -> Chat {
        Chat(
            id: id, title: title, lastMessageAt: lastMessageAt,
            createdAt: createdAt, updatedAt: updatedAt,
            lastEditedOverallTimestamp: lastEditedOverallTimestamp,
            isArchived: isArchived, isPinned: isPinned,
            appId: appId, category: category, icon: icon, chatSummary: chatSummary,
            encryptedTitle: encryptedTitle,
            encryptedCategory: encryptedCategory,
            encryptedIcon: encryptedIcon,
            encryptedChatSummary: encryptedChatSummary,
            encryptedFollowUpRequestSuggestions: encryptedFollowUpRequestSuggestions,
            encryptedAutoSpeakResponse: encryptedAutoSpeakResponse,
            encryptedChatKey: encryptedChatKey,
            messagesV: messagesV,
            titleV: titleV,
            draftV: draftV,
            metadataV: metadataV,
            lastVisibleMessageId: lastVisibleMessageId,
            parentId: parentId,
            isSubChat: isSubChat,
            subChatSettings: subChatSettingsJSON.flatMap { try? JSONDecoder().decode(SubChatSettings.self, from: $0) },
            budgetLimit: budgetLimit,
            budgetSpent: budgetSpent,
            encryptedFocusPhaseState: encryptedFocusPhaseState,
            encryptedActiveFocusId: encryptedActiveFocusId,
            activeFocusId: activeFocusId,
            isPrivate: isPrivate,
            teamId: teamId, isSharedByOthers: isSharedByOthers,
            hasNonEmptyDraft: hasNonEmptyDraft,
            clearedDraftV: clearedDraftV
        )
    }
}

@Model
final class PersistedMessage {
    @Attribute(.unique) var id: String
    var serverMessageId: String?
    var chatId: String
    var role: String
    var content: String?
    var encryptedContent: String?
    var createdAt: String
    var updatedAt: String?
    var appId: String?
    var modelName: String?
    var senderName: String?
    var category: String?
    var encryptedSenderName: String?
    var encryptedCategory: String?
    var encryptedModelName: String?
    var embedRefsJSON: Data?
    var renderDocumentJSON: Data?
    var piiMappingsJSON: Data?
    var encryptedPIIMappings: String?
    var encryptedThinkingContent: String?
    var encryptedThinkingSignature: String?
    var thinkingTokenCount: Int?

    var chat: PersistedChat?

    init(from message: Message) {
        self.id = message.id
        self.serverMessageId = message.serverMessageId
        self.chatId = message.chatId
        self.role = message.role.rawValue
        self.content = message.content
        self.encryptedContent = message.encryptedContent
        self.createdAt = message.createdAt
        self.updatedAt = message.updatedAt
        self.appId = message.appId
        self.modelName = message.modelName
        self.senderName = message.senderName
        self.category = message.category
        self.encryptedSenderName = message.encryptedSenderName
        self.encryptedCategory = message.encryptedCategory
        self.encryptedModelName = message.encryptedModelName
        self.embedRefsJSON = try? JSONEncoder().encode(message.embedRefs)
        self.renderDocumentJSON = try? JSONEncoder().encode(message.renderDocumentForDisplay)
        self.piiMappingsJSON = try? JSONEncoder().encode(message.piiMappings)
        self.encryptedPIIMappings = message.encryptedPIIMappings
        self.encryptedThinkingContent = message.encryptedThinkingContent
        self.encryptedThinkingSignature = message.encryptedThinkingSignature
        self.thinkingTokenCount = message.thinkingTokenCount
    }

    func toMessage() -> Message {
        let embedRefs = embedRefsJSON.flatMap { try? JSONDecoder().decode([EmbedRef].self, from: $0) }
        let piiMappings = piiMappingsJSON.flatMap { try? JSONDecoder().decode([PIIMapping].self, from: $0) }
        let renderDocument = renderDocumentJSON.flatMap {
            try? JSONDecoder().decode(ChatHistoryRenderDocument.self, from: $0)
        }
        return Message(
            id: id, chatId: chatId,
            role: MessageRole(rawValue: role) ?? .user,
            content: content, encryptedContent: encryptedContent,
            createdAt: createdAt,
            updatedAt: updatedAt, appId: appId,
            isStreaming: false, embedRefs: embedRefs,
            modelName: modelName,
            senderName: senderName,
            category: category,
            encryptedSenderName: encryptedSenderName,
            encryptedCategory: encryptedCategory,
            encryptedModelName: encryptedModelName,
            piiMappings: piiMappings,
            encryptedPIIMappings: encryptedPIIMappings,
            encryptedThinkingContent: encryptedThinkingContent,
            encryptedThinkingSignature: encryptedThinkingSignature,
            thinkingTokenCount: thinkingTokenCount,
            renderDocument: renderDocument, serverMessageId: serverMessageId
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
final class PersistedCodeRunOutput {
    @Attribute(.unique) var id: String
    var chatId: String
    var embedId: String
    var authorUserId: String?
    var encryptedPayload: String
    var keyVersion: Int?
    var createdAt: Double
    var updatedAt: Double
    var needsSync: Bool

    init(id: String, chatId: String, embedId: String, authorUserId: String?,
         encryptedPayload: String, keyVersion: Int?, createdAt: Double, updatedAt: Double,
         needsSync: Bool = false) {
        self.id = id
        self.chatId = chatId
        self.embedId = embedId
        self.authorUserId = authorUserId
        self.encryptedPayload = encryptedPayload
        self.keyVersion = keyVersion
        self.createdAt = createdAt
        self.updatedAt = updatedAt
        self.needsSync = needsSync
    }
}

enum CodeRunOfflineStoreError: Error {
    case inactiveScope
}

@Model
final class PersistedOwnerEmbedPII {
    @Attribute(.unique) var embedId: String
    var chatId: String
    var ownerUserId: String
    var encryptedMappings: String
    var createdAt: Double

    init(embedId: String, chatId: String, ownerUserId: String,
         encryptedMappings: String, createdAt: Double) {
        self.embedId = embedId
        self.chatId = chatId
        self.ownerUserId = ownerUserId
        self.encryptedMappings = encryptedMappings
        self.createdAt = createdAt
    }
}

enum OwnerEmbedPIIOfflineStoreError: Error {
    case inactiveScope
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

    private(set) var activeScopeId: String?
    private(set) var scopeGeneration = UUID()
    private var chatDeletionVersions: [String: Int] = [:]
    private let recentContentFence = OfflineRecentChatContentFence()
    private var storageDirectory: URL?

    // Remain detached until authentication identifies the owner. The legacy
    // unscoped store is deliberately preserved, never adopted or deleted.
    private init() {}

    init(directory: URL, userId: String, apiBaseURL: URL) throws {
        storageDirectory = directory
        try activate(userId: userId, apiBaseURL: apiBaseURL)
    }

    static func scopeId(userId: String, apiBaseURL: URL) -> String {
        let identity = apiBaseURL.absoluteString.trimmingCharacters(in: CharacterSet(charactersIn: "/"))
            + "\n" + userId
        return SHA256.hash(data: Data(identity.utf8)).map { String(format: "%02x", $0) }.joined()
    }

    func activate(userId: String, apiBaseURL: URL) throws {
        let scope = Self.scopeId(userId: userId, apiBaseURL: apiBaseURL)
        guard activeScopeId != scope else { return }
        deactivate()
        let directory = try storageDirectory ?? FileManager.default.url(
            for: .applicationSupportDirectory, in: .userDomainMask,
            appropriateFor: nil, create: true
        ).appendingPathComponent("OpenMatesOfflineScopes", isDirectory: true)
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
        let schema = Self.persistenceSchema
        let config = ModelConfiguration(
            "OpenMatesOffline-\(scope)", schema: schema,
            url: directory.appendingPathComponent("\(scope).store")
        )
        let container = try ModelContainer(for: schema, configurations: [config])
        modelContainer = container
        modelContext = container.mainContext
        activeScopeId = scope
        updatePendingCount()
    }

    func deactivate() {
        #if !os(watchOS)
        if self === Self.shared { HighlightsManager.shared.reset() }
        #endif
        scopeGeneration = UUID()
        recentContentFence.invalidateScope()
        chatDeletionVersions.removeAll()
        modelContext = nil
        modelContainer = nil
        activeScopeId = nil
        pendingActionCount = 0
    }

    private static var persistenceSchema: Schema {
        Schema([
            PersistedChat.self,
            PersistedMessage.self,
            PersistedEmbed.self,
            PersistedEmbedKey.self,
            PersistedCodeRunOutput.self,
            PersistedOwnerEmbedPII.self,
            PersistedComposerDraft.self,
            PendingOfflineAction.self,
        ])
    }

    init(modelContainer: ModelContainer) {
        self.modelContainer = modelContainer
        self.modelContext = modelContainer.mainContext
    }

    func makeRecentChatCacheWriter() async -> OfflineRecentChatCacheWriter? {
        guard let container = modelContainer else { return nil }
        // Construct the worker's context on a background executor. The main
        // context and its model objects never cross the actor boundary.
        return await Task.detached(priority: .utility) {
            OfflineRecentChatCacheWriter(modelContainer: container)
        }.value
    }

    func recentContentWriteFence(for chatID: String) -> OfflineRecentChatWriteFence {
        recentContentFence.capture(chatID: chatID)
    }

    private func invalidateRecentContentReceipt(chatID: String, context: ModelContext) {
        recentContentFence.invalidate(chatID: chatID)
        let rows = FetchDescriptor<PersistedChat>(predicate: #Predicate { $0.id == chatID })
        if let row = try? context.fetch(rows).first {
            row.offlineContentMessagesV = nil
            row.offlineContentRecency = nil
            row.offlineContentServerCount = nil
            row.offlineContentRowCount = nil
        }
    }

    func hasCompleteOfflineSnapshot(for chat: Chat) -> Bool {
        guard let container = modelContainer else { return false }
        // Read a fresh context so receipts written by the cache actor, and their
        // durable invalidations, cannot be hidden by main-context registrations.
        let context = ModelContext(container)
        let chatID = chat.id
        let descriptor = FetchDescriptor<PersistedChat>(predicate: #Predicate { $0.id == chatID })
        guard let row = try? context.fetch(descriptor).first,
              let serverCount = row.offlineContentServerCount,
              let expectedRows = row.offlineContentRowCount, serverCount >= 0, expectedRows >= serverCount,
              (row.offlineContentMessagesV ?? -1) >= (chat.messagesV ?? 0),
              row.offlineContentRecency == OfflineRecentChatPolicy.recency(of: chat) else { return false }
        let messages = FetchDescriptor<PersistedMessage>(predicate: #Predicate { $0.chatId == chatID })
        return (try? context.fetchCount(messages)) == expectedRows
    }

    // MARK: - Save chats from sync

    func persistChats(_ chats: [Chat]) {
        guard let context = modelContext, let container = modelContainer else { return }
        // A fresh receipt context observes actor commits even when the main
        // context already registered this metadata row. Save invalidations once
        // per batch rather than once per chat.
        let receiptContext = ModelContext(container)
        receiptContext.autosaveEnabled = false
        let start = NativeSyncPerfLog.now()
        var fetchSeconds = 0.0
        for chat in chats {
            let targetId = chat.id
            let descriptor = FetchDescriptor<PersistedChat>(
                predicate: #Predicate { $0.id == targetId }
            )
            let fetchStart = NativeSyncPerfLog.now()
            let existingChat = try? context.fetch(descriptor).first
            fetchSeconds += NativeSyncPerfLog.now() - fetchStart
            if let existing = existingChat {
                if chat.messagesV != existing.messagesV
                    || OfflineRecentChatPolicy.recency(of: chat) > (existing.lastEditedOverallTimestamp ?? existing.createdAt) {
                    invalidateRecentContentReceipt(chatID: chat.id, context: receiptContext)
                }
                let acceptsIncomingMetadata = (chat.metadataV ?? 0) >= (existing.metadataV ?? 0)
                let acceptsIncomingSummary = (chat.metadataV ?? 0) > (existing.metadataV ?? 0)
                    || ((chat.metadataV ?? 0) == (existing.metadataV ?? 0)
                        && existing.chatSummary == nil
                        && (existing.encryptedChatSummary == nil
                            || (chat.chatSummary != nil && chat.encryptedChatSummary == existing.encryptedChatSummary)))
                let incomingTitleVersion = chat.titleV ?? 0
                let storedTitleVersion = existing.titleV ?? 0
                if incomingTitleVersion > storedTitleVersion {
                    existing.title = chat.title
                    existing.encryptedTitle = chat.encryptedTitle
                } else if incomingTitleVersion == storedTitleVersion && storedTitleVersion > 0 {
                    // Persist same-revision plaintext hydration only when it is
                    // tied to the stored ciphertext (or the stored row is an
                    // incomplete snapshot with no ciphertext yet).
                    if existing.title == nil,
                       existing.encryptedTitle == nil || existing.encryptedTitle == chat.encryptedTitle {
                        existing.title = chat.title
                    }
                    if existing.encryptedTitle == nil { existing.encryptedTitle = chat.encryptedTitle }
                } else if storedTitleVersion == 0 {
                    existing.title = nil
                    existing.encryptedTitle = chat.encryptedTitle ?? existing.encryptedTitle
                }
                existing.encryptedCategory = chat.encryptedCategory
                existing.encryptedIcon = chat.encryptedIcon
                if acceptsIncomingSummary {
                    existing.encryptedChatSummary = chat.encryptedChatSummary ?? existing.encryptedChatSummary
                    existing.chatSummary = chat.chatSummary ?? existing.chatSummary
                }
                if acceptsIncomingMetadata {
                    existing.encryptedFollowUpRequestSuggestions = chat.encryptedFollowUpRequestSuggestions
                        ?? existing.encryptedFollowUpRequestSuggestions
                }
                existing.encryptedAutoSpeakResponse = chat.encryptedAutoSpeakResponse ?? existing.encryptedAutoSpeakResponse
                existing.encryptedChatKey = chat.encryptedChatKey ?? existing.encryptedChatKey
                existing.icon = chat.icon
                existing.category = chat.category
                existing.appId = chat.appId
                existing.isPinned = chat.isPinned ?? false
                existing.isArchived = chat.isArchived ?? false
                existing.lastMessageAt = chat.lastMessageAt
                existing.updatedAt = chat.updatedAt
                existing.lastEditedOverallTimestamp = [existing.lastEditedOverallTimestamp, OfflineRecentChatPolicy.recency(of: chat)].compactMap { $0 }.max()
                existing.lastVisibleMessageId = chat.lastVisibleMessageId
                existing.messagesV = chat.messagesV
                existing.titleV = max(storedTitleVersion, incomingTitleVersion)
                existing.draftV = chat.draftV
                existing.clearedDraftV = chat.clearedDraftV
                existing.metadataV = max(existing.metadataV ?? 0, chat.metadataV ?? 0)
                existing.hasNonEmptyDraft = chat.hasNonEmptyDraft ?? (chat.draftV == 0 ? false : existing.hasNonEmptyDraft)
                existing.parentId = chat.parentId
                existing.isSubChat = chat.isSubChat
                existing.subChatSettingsJSON = try? JSONEncoder().encode(chat.subChatSettings)
                existing.budgetLimit = chat.budgetLimit
                existing.budgetSpent = chat.budgetSpent
                existing.encryptedFocusPhaseState = chat.encryptedFocusPhaseState
                existing.encryptedActiveFocusId = chat.encryptedActiveFocusId
                existing.activeFocusId = chat.activeFocusId
                existing.teamId = chat.teamId ?? existing.teamId
                existing.isSharedByOthers = chat.isSharedByOthers ?? existing.isSharedByOthers
                existing.isPrivate = chat.isPrivate ?? existing.isPrivate
            } else {
                context.insert(PersistedChat(from: chat))
            }
        }
        let saveStart = NativeSyncPerfLog.now()
        try? receiptContext.save()
        try? context.save()
        let saveMs = NativeSyncPerfLog.ms(since: saveStart)
        let elapsedMs = NativeSyncPerfLog.ms(since: start)
        if chats.count > 1 || elapsedMs >= 16 {
            NativeSyncPerfLog.info(
                "phase=offlinePersistChats chats=\(chats.count) fetchMs=\(Int(fetchSeconds * 1000)) saveMs=\(saveMs) elapsedMs=\(elapsedMs)"
            )
        }
    }

    func persistMessages(_ messages: [Message], chatId: String) {
        persistMessagesBatch([chatId: messages])
    }

    func persistMessagesBatch(_ messagesByChat: [String: [Message]]) {
        guard let context = modelContext, let container = modelContainer else { return }
        // A fresh receipt context observes actor commits even when the main
        // context already registered this metadata row. Save invalidations once
        // per batch rather than once per chat.
        let receiptContext = ModelContext(container)
        receiptContext.autosaveEnabled = false
        let start = NativeSyncPerfLog.now()
        var savedMessages = 0
        let encoder = JSONEncoder()

        for (chatId, messages) in messagesByChat {
            invalidateRecentContentReceipt(chatID: chatId, context: receiptContext)
            guard !messages.isEmpty else { continue }
            let targetChatId = chatId
            let chatDescriptor = FetchDescriptor<PersistedChat>(
                predicate: #Predicate { $0.id == targetChatId }
            )
            let persistedChat = try? context.fetch(chatDescriptor).first

            let existingDescriptor = FetchDescriptor<PersistedMessage>(
                predicate: #Predicate { $0.chatId == targetChatId }
            )
            var existingById = Dictionary(
                ((try? context.fetch(existingDescriptor)) ?? []).map { ($0.id, $0) },
                uniquingKeysWith: { first, _ in first }
            )

            for message in messages {
                // Migrate a known wire alias, never infer identity from text.
                // This also repairs caches written before client IDs won decode.
                if let alias = message.serverMessageId, alias != message.id,
                   let old = existingById[alias], old.chatId == chatId, old.role == message.role.rawValue {
                    if let canonical = existingById[message.id] {
                        let bodySource = message.localBodySource(canonical: canonical.toMessage(), alias: old.toMessage())
                        if canonical.content == nil, bodySource?.id == alias {
                            canonical.content = bodySource?.content
                        }
                        context.delete(old)
                    } else {
                        old.id = message.id
                        existingById[message.id] = old
                    }
                    existingById.removeValue(forKey: alias)
                }
                if let existing = existingById[message.id] {
                    existing.serverMessageId = message.serverMessageId ?? existing.serverMessageId
                    let sameCiphertext = message.encryptedContent != nil && message.encryptedContent == existing.encryptedContent
                    existing.content = message.content ?? (sameCiphertext ? existing.content : nil)
                    existing.encryptedContent = message.encryptedContent
                    existing.updatedAt = message.updatedAt
                    existing.appId = message.appId
                    existing.modelName = message.modelName
                    existing.senderName = message.senderName
                    existing.category = message.category
                    existing.encryptedSenderName = message.encryptedSenderName
                    existing.encryptedCategory = message.encryptedCategory
                    existing.encryptedModelName = message.encryptedModelName
                    existing.embedRefsJSON = try? encoder.encode(message.embedRefs)
                    existing.renderDocumentJSON = try? encoder.encode(message.renderDocumentForDisplay)
                } else {
                    let persisted = PersistedMessage(from: message)
                    persisted.chat = persistedChat
                    context.insert(persisted)
                    existingById[message.id] = persisted
                }
                savedMessages += 1
            }
        }

        try? receiptContext.save()
        try? context.save()
        NativeSyncPerfLog.info(
            "phase=offlinePersistMessagesBatch chats=\(messagesByChat.count) messages=\(savedMessages) persistMs=\(NativeSyncPerfLog.ms(since: start))"
        )
    }

    func persistEmbeds(_ embeds: [EmbedRecord], chatId: String) {
        persistEmbedsBatch([chatId: embeds])
    }

    func persistEmbedsBatch(_ embedsByChat: [String: [EmbedRecord]]) {
        guard let context = modelContext, let container = modelContainer else { return }
        // A fresh receipt context observes actor commits even when the main
        // context already registered this metadata row. Save invalidations once
        // per batch rather than once per chat.
        let receiptContext = ModelContext(container)
        receiptContext.autosaveEnabled = false
        let start = NativeSyncPerfLog.now()
        var savedEmbeds = 0

        for (chatId, embeds) in embedsByChat {
            invalidateRecentContentReceipt(chatID: chatId, context: receiptContext)
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

        try? receiptContext.save()
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

    /// One scoped metadata row, without materializing its transcript/embeds.
    func loadChat(id: String) -> Chat? {
        guard let context = modelContext else { return nil }
        var descriptor = FetchDescriptor<PersistedChat>(predicate: #Predicate { $0.id == id })
        descriptor.fetchLimit = 1
        return (try? context.fetch(descriptor).first)?.toChat()
    }

    func loadStartupChats(lastOpenedChatId: String?, limit: Int) -> [Chat] {
        guard let context = modelContext else { return [] }
        var descriptor = FetchDescriptor<PersistedChat>(
            sortBy: [SortDescriptor(\.lastEditedOverallTimestamp, order: .reverse),
                     SortDescriptor(\.lastMessageAt, order: .reverse), SortDescriptor(\.id)]
        )
        descriptor.fetchLimit = limit
        var chats = (try? context.fetch(descriptor))?.map { $0.toChat() } ?? []

        // A bounded recent-time query alone loses older cached pins/drafts on
        // cold launch. Supplement metadata for each priority class, independently
        // of the sidebar cap. No message or embed history is loaded here.
        let priorityPredicates: [Predicate<PersistedChat>] = [
            #Predicate { $0.isPinned && $0.hasNonEmptyDraft == true && !$0.isArchived },
            #Predicate { $0.isPinned && ($0.hasNonEmptyDraft == nil || $0.hasNonEmptyDraft == false) && !$0.isArchived },
            #Predicate { !$0.isPinned && $0.hasNonEmptyDraft == true && !$0.isArchived }
        ]
        var seen = Set(chats.map(\.id))
        for predicate in priorityPredicates {
            var priority = FetchDescriptor<PersistedChat>(predicate: predicate, sortBy: [
                SortDescriptor(\.lastMessageAt, order: .reverse),
                SortDescriptor(\.updatedAt, order: .reverse),
                SortDescriptor(\.id, order: .reverse)
            ])
            priority.fetchLimit = limit
            for item in (try? context.fetch(priority)) ?? [] where seen.insert(item.id).inserted {
                chats.append(item.toChat())
            }
        }

        if let lastOpenedChatId,
           !lastOpenedChatId.isEmpty,
           lastOpenedChatId != "/chat/new",
           !chats.contains(where: { $0.id == lastOpenedChatId }) {
            let targetId = lastOpenedChatId
            let lastOpenedDescriptor = FetchDescriptor<PersistedChat>(
                predicate: #Predicate { $0.id == targetId }
            )
            if let lastOpenedChat = (try? context.fetch(lastOpenedDescriptor).first)?.toChat() {
                chats.append(lastOpenedChat)
            }
        }

        return chats.sorted {
            let left = OfflineRecentChatPolicy.recency(of: $0), right = OfflineRecentChatPolicy.recency(of: $1)
            return left == right ? $0.id < $1.id : left > right
        }
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
            sortBy: [SortDescriptor(\.createdAt, order: .reverse), SortDescriptor(\.id, order: .reverse)]
        )
        descriptor.fetchLimit = limit
        let newestFirst = (try? context.fetch(descriptor)) ?? []
        return newestFirst.reversed().map { $0.toMessage() }
    }

    func loadOlderMessageWindow(chatId: String, before messageId: String, limit: Int = ChatStore.boundedWindowSize) -> [Message] {
        guard let context = modelContext else { return [] }
        let targetChatId = chatId
        let boundaryDescriptor = FetchDescriptor<PersistedMessage>(
            predicate: #Predicate { $0.id == messageId }
        )
        guard let boundary = try? context.fetch(boundaryDescriptor).first else { return [] }
        let boundaryCreatedAt = boundary.createdAt
        let boundaryID = boundary.id
        var descriptor = FetchDescriptor<PersistedMessage>(
            predicate: #Predicate { $0.chatId == targetChatId && ($0.createdAt < boundaryCreatedAt || ($0.createdAt == boundaryCreatedAt && $0.id < boundaryID)) },
            sortBy: [SortDescriptor(\.createdAt, order: .reverse), SortDescriptor(\.id, order: .reverse)]
        )
        descriptor.fetchLimit = limit
        let newestFirst = (try? context.fetch(descriptor)) ?? []
        return newestFirst.reversed().map { $0.toMessage() }
    }

    func hasOlderMessages(chatId: String, before message: Message) -> Bool {
        guard let context = modelContext else { return false }
        let targetID = chatId
        let timestamp = message.createdAt
        let boundaryID = message.id
        var descriptor = FetchDescriptor<PersistedMessage>(predicate: #Predicate {
            $0.chatId == targetID && ($0.createdAt < timestamp || ($0.createdAt == timestamp && $0.id < boundaryID))
        })
        descriptor.fetchLimit = 1
        return (try? context.fetch(descriptor).isEmpty) == false
    }

    func loadOldestMessageWindow(chatId: String, limit: Int = ChatStore.boundedWindowSize) -> [Message] {
        guard let context = modelContext else { return [] }
        let targetID = chatId
        var descriptor = FetchDescriptor<PersistedMessage>(predicate: #Predicate { $0.chatId == targetID },
            sortBy: [SortDescriptor(\.createdAt), SortDescriptor(\.id)])
        descriptor.fetchLimit = limit
        return ((try? context.fetch(descriptor)) ?? []).map { $0.toMessage() }
    }

    func loadNewerMessageWindow(chatId: String, after message: Message, limit: Int = ChatStore.boundedWindowSize) -> [Message] {
        guard let context = modelContext else { return [] }
        let targetID = chatId
        let timestamp = message.createdAt
        let boundaryID = message.id
        var descriptor = FetchDescriptor<PersistedMessage>(predicate: #Predicate {
            $0.chatId == targetID && ($0.createdAt > timestamp || ($0.createdAt == timestamp && $0.id > boundaryID))
        }, sortBy: [SortDescriptor(\.createdAt), SortDescriptor(\.id)])
        descriptor.fetchLimit = limit
        return ((try? context.fetch(descriptor)) ?? []).map { $0.toMessage() }
    }

    func hasNewerMessages(chatId: String, after message: Message) -> Bool {
        !loadNewerMessageWindow(chatId: chatId, after: message, limit: 1).isEmpty
    }

    func newerMessageCount(chatId: String, after message: Message) -> Int {
        guard let context = modelContext else { return 0 }
        let targetID = chatId
        let timestamp = message.createdAt
        let boundaryID = message.id
        let descriptor = FetchDescriptor<PersistedMessage>(predicate: #Predicate {
            $0.chatId == targetID && ($0.createdAt > timestamp || ($0.createdAt == timestamp && $0.id > boundaryID))
        })
        return (try? context.fetchCount(descriptor)) ?? 0
    }

    func loadMessageWindow(chatId: String, around messageID: String, limit: Int = ChatStore.boundedWindowSize) -> [Message] {
        guard let context = modelContext else { return [] }
        let targetID = messageID
        let descriptor = FetchDescriptor<PersistedMessage>(predicate: #Predicate { $0.id == targetID })
        guard let row = try? context.fetch(descriptor).first, row.chatId == chatId else { return [] }
        let target = row.toMessage()
        let older = loadOlderMessageWindow(chatId: chatId, before: messageID, limit: limit / 2)
        return older + [target] + loadNewerMessageWindow(chatId: chatId, after: target, limit: max(0, limit - older.count - 1))
    }

    func loadEmbeds(chatId: String) -> [EmbedRecord] {
        guard let context = modelContext else { return [] }
        let targetChatId = chatId
        let descriptor = FetchDescriptor<PersistedEmbed>(
            predicate: #Predicate { $0.chatId == targetChatId }
        )
        return (try? context.fetch(descriptor))?.map { $0.toEmbed() } ?? []
    }

    @discardableResult
    func persistCodeRunOutput(_ output: PersistedCodeRunOutput) throws -> Bool {
        guard let context = modelContext else { throw CodeRunOfflineStoreError.inactiveScope }
        let chatId = output.chatId
        let embedId = output.embedId
        let descriptor = FetchDescriptor<PersistedCodeRunOutput>(
            predicate: #Predicate { $0.chatId == chatId && $0.embedId == embedId }
        )
        let rows = try context.fetch(descriptor)
        guard !rows.contains(where: {
            $0.updatedAt > output.updatedAt ||
                ($0.needsSync && !output.needsSync && $0.encryptedPayload != output.encryptedPayload)
        }) else { return false }
        for old in rows where old.id != output.id { context.delete(old) }
        if let existing = rows.first(where: { $0.id == output.id }) {
            existing.authorUserId = output.authorUserId
            existing.encryptedPayload = output.encryptedPayload
            existing.keyVersion = output.keyVersion
            existing.createdAt = output.createdAt
            existing.updatedAt = output.updatedAt
            existing.needsSync = output.needsSync
        } else {
            context.insert(output)
        }
        try context.save()
        return true
    }

    func pendingCodeRunOutputs() throws -> [PersistedCodeRunOutput] {
        guard let context = modelContext else { throw CodeRunOfflineStoreError.inactiveScope }
        let descriptor = FetchDescriptor<PersistedCodeRunOutput>(
            predicate: #Predicate { $0.needsSync == true },
            sortBy: [SortDescriptor(\PersistedCodeRunOutput.updatedAt)]
        )
        return try context.fetch(descriptor)
    }

    func acknowledgeCodeRunOutput(id: String, encryptedPayload: String) throws {
        guard let context = modelContext else { throw CodeRunOfflineStoreError.inactiveScope }
        let targetId = id
        let descriptor = FetchDescriptor<PersistedCodeRunOutput>(
            predicate: #Predicate { $0.id == targetId }
        )
        guard let existing = try context.fetch(descriptor).first,
              existing.encryptedPayload == encryptedPayload else { return }
        existing.needsSync = false
        try context.save()
    }

    func loadCodeRunOutput(chatId: String, embedId: String) -> PersistedCodeRunOutput? {
        guard let context = modelContext else { return nil }
        let targetChatId = chatId
        let targetEmbedId = embedId
        let descriptor = FetchDescriptor<PersistedCodeRunOutput>(
            predicate: #Predicate { $0.chatId == targetChatId && $0.embedId == targetEmbedId },
            sortBy: [SortDescriptor(\PersistedCodeRunOutput.updatedAt, order: .reverse)]
        )
        return try? context.fetch(descriptor).first
    }

    func persistOwnerEmbedPII(_ row: PersistedOwnerEmbedPII) throws {
        guard let context = modelContext else { throw OwnerEmbedPIIOfflineStoreError.inactiveScope }
        let targetEmbedId = row.embedId
        let descriptor = FetchDescriptor<PersistedOwnerEmbedPII>(
            predicate: #Predicate { $0.embedId == targetEmbedId }
        )
        if let existing = try context.fetch(descriptor).first {
            guard existing.chatId == row.chatId, existing.ownerUserId == row.ownerUserId else {
                throw OwnerEmbedPIIOfflineStoreError.inactiveScope
            }
            existing.encryptedMappings = row.encryptedMappings
            existing.createdAt = row.createdAt
        } else {
            context.insert(row)
        }
        try context.save()
    }

    func loadOwnerEmbedPII(chatId: String, embedId: String) throws -> PersistedOwnerEmbedPII? {
        guard let context = modelContext else { throw OwnerEmbedPIIOfflineStoreError.inactiveScope }
        let targetChatId = chatId
        let targetEmbedId = embedId
        let descriptor = FetchDescriptor<PersistedOwnerEmbedPII>(
            predicate: #Predicate { $0.chatId == targetChatId && $0.embedId == targetEmbedId }
        )
        return try context.fetch(descriptor).first
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

    func removeMessageIDs(_ ids: Set<String>, from chatID: String, scope: UUID) throws {
        guard scope == scopeGeneration, let context = modelContext else { throw NSError(domain: "OpenMates.MessageScope", code: 1) }
        let target = chatID
        let descriptor = FetchDescriptor<PersistedMessage>(predicate: #Predicate { $0.chatId == target })
        for row in try context.fetch(descriptor) where ids.contains(row.id) || row.serverMessageId.map(ids.contains) == true { context.delete(row) }
        invalidateRecentContentReceipt(chatID: chatID, context: context)
        try context.save()
    }

    func storeCompressionCheckpoint(_ checkpoint: [String: Any], chatID: String, scope: UUID) throws {
        guard scope == scopeGeneration, let context = modelContext,
              let id = checkpoint["id"] as? String,
              let ciphertext = checkpoint["encrypted_summary"] as? String, !ciphertext.isEmpty,
              let boundary = checkpoint["compressed_up_to_timestamp"] as? Int else { throw OfflineStoreDraftError.staleSession }
        let target = chatID
        let descriptor = FetchDescriptor<PersistedChat>(predicate: #Predicate { $0.id == target })
        guard let row = try context.fetch(descriptor).first else { return }
        var fields = row.offlineSupplementalContentJSON.flatMap { try? JSONSerialization.jsonObject(with: $0) as? [String: Any] } ?? [:]
        var byChat = fields["compression_checkpoints_by_chat_id"] as? [String: Any] ?? [:]
        var checkpoints = byChat[chatID] as? [[String: Any]] ?? []
        // Only protocol ciphertext and opaque metadata cross the disk boundary.
        var encrypted: [String: Any] = ["id": id, "chat_id": chatID, "encrypted_summary": ciphertext, "compressed_up_to_timestamp": boundary]
        for key in ["compressed_message_count", "summary_token_estimate", "key_version", "created_at", "updated_at"] {
            if let value = checkpoint[key] { encrypted[key] = value }
        }
        checkpoints.removeAll { $0["id"] as? String == id }; checkpoints.append(encrypted)
        byChat[chatID] = checkpoints; fields["compression_checkpoints_by_chat_id"] = byChat
        row.offlineSupplementalContentJSON = try JSONSerialization.data(withJSONObject: fields)
        try context.save()
    }

    func compressionBoundary(chatID: String) -> Int? {
        guard let context = modelContext else { return nil }
        let target = chatID
        let descriptor = FetchDescriptor<PersistedChat>(predicate: #Predicate { $0.id == target })
        guard let bytes = try? context.fetch(descriptor).first?.offlineSupplementalContentJSON,
              let fields = try? JSONSerialization.jsonObject(with: bytes) as? [String: Any] else { return nil }
        guard let byChat = fields["compression_checkpoints_by_chat_id"] as? [String: Any],
              let values = byChat[chatID] as? [[String: Any]],
              let newest = values.filter({ ($0["encrypted_summary"] as? String)?.isEmpty == false }).max(by: { ($0["created_at"] as? Int ?? 0) < ($1["created_at"] as? Int ?? 0) }) else { return nil }
        return newest["compressed_up_to_timestamp"] as? Int
    }

    func deleteChat(_ chatId: String, preservingDraftTombstone: Bool = false) {
        recentContentFence.invalidate(chatID: chatId)
        chatDeletionVersions[chatId, default: 0] += 1
        if self === Self.shared {
            CodeRunOutputStore.shared.remove(chatId: chatId)
            OwnerEmbedPIIStore.shared.remove(chatId: chatId)
        }
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
        let embedDescriptor = FetchDescriptor<PersistedEmbed>(
            predicate: #Predicate { $0.chatId == targetChatId }
        )
        for embed in (try? context.fetch(embedDescriptor)) ?? [] {
            context.delete(embed)
        }
        let runDescriptor = FetchDescriptor<PersistedCodeRunOutput>(
            predicate: #Predicate { $0.chatId == targetChatId }
        )
        for output in (try? context.fetch(runDescriptor)) ?? [] {
            context.delete(output)
        }
        let ownerPIIDescriptor = FetchDescriptor<PersistedOwnerEmbedPII>(
            predicate: #Predicate { $0.chatId == targetChatId }
        )
        for row in (try? context.fetch(ownerPIIDescriptor)) ?? [] {
            context.delete(row)
        }
        let draftDescriptor = FetchDescriptor<PersistedComposerDraft>(
            predicate: #Predicate { $0.chatId == targetChatId }
        )
        for draft in (try? context.fetch(draftDescriptor)) ?? [] {
            if preservingDraftTombstone && draft.isDraftTombstone == true { continue }
            context.delete(draft)
        }
        let hashedChatId = SHA256.hash(data: Data(chatId.utf8))
            .map { String(format: "%02x", $0) }
            .joined()
        let keyDescriptor = FetchDescriptor<PersistedEmbedKey>(
            predicate: #Predicate { $0.hashedChatId == hashedChatId }
        )
        for key in (try? context.fetch(keyDescriptor)) ?? [] {
            context.delete(key)
        }
        let actionDescriptor = FetchDescriptor<PendingOfflineAction>()
        for action in (try? context.fetch(actionDescriptor)) ?? [] {
            guard let data = action.payloadJSON,
                  let payload = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
                  payload["chat_id"] as? String == chatId else { continue }
            context.delete(action)
        }
        try? context.save()
        updatePendingCount()
    }

    func chatDeletionVersion(_ chatId: String) -> Int {
        chatDeletionVersions[chatId, default: 0]
    }

    func clearAll() {
        guard let context = modelContext else { return }
        if self === Self.shared {
            CodeRunOutputStore.shared.clearAll()
            OwnerEmbedPIIStore.shared.clearAll()
        }
        try? context.delete(model: PersistedChat.self)
        try? context.delete(model: PersistedMessage.self)
        try? context.delete(model: PersistedEmbed.self)
        try? context.delete(model: PersistedEmbedKey.self)
        try? context.delete(model: PersistedCodeRunOutput.self)
        try? context.delete(model: PersistedOwnerEmbedPII.self)
        try? context.delete(model: PersistedComposerDraft.self)
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

enum OfflineStoreDraftError: Error {
    case persistenceUnavailable
    case staleSession
}

extension OfflineStore: ComposerDraftRepository {
    func upsert(_ record: ComposerDraftRecord) async throws {
        guard let context = modelContext else {
            throw OfflineStoreDraftError.persistenceUnavailable
        }
        let targetChatId = record.chatId
        let descriptor = FetchDescriptor<PersistedComposerDraft>(
            predicate: #Predicate { $0.chatId == targetChatId }
        )
        if let existing = try context.fetch(descriptor).first {
            var resolved = record
            resolved.clearedDraftVersion = max(existing.clearedDraftVersion ?? 0, record.clearedDraftVersion)
            existing.update(from: resolved)
        } else {
            context.insert(PersistedComposerDraft(record: record))
        }
        try context.save()
    }

    func record(chatId: String) async throws -> ComposerDraftRecord? {
        guard let context = modelContext else {
            throw OfflineStoreDraftError.persistenceUnavailable
        }
        let targetChatId = chatId
        let descriptor = FetchDescriptor<PersistedComposerDraft>(
            predicate: #Predicate { $0.chatId == targetChatId }
        )
        guard let persisted = try context.fetch(descriptor).first, persisted.isDraftTombstone != true else { return nil }
        return persisted.toRecord()
    }

    func remove(chatId: String) async throws {
        guard let context = modelContext else {
            throw OfflineStoreDraftError.persistenceUnavailable
        }
        let targetChatId = chatId
        let descriptor = FetchDescriptor<PersistedComposerDraft>(
            predicate: #Predicate { $0.chatId == targetChatId }
        )
        if let record = try context.fetch(descriptor).first {
            context.delete(record)
            try context.save()
        }
    }

    func removeAll() async throws {
        guard let context = modelContext else {
            throw OfflineStoreDraftError.persistenceUnavailable
        }
        try context.delete(model: PersistedComposerDraft.self)
        try context.save()
    }

    func allRecords() async throws -> [ComposerDraftRecord] {
        guard let context = modelContext else {
            throw OfflineStoreDraftError.persistenceUnavailable
        }
        let descriptor = FetchDescriptor<PersistedComposerDraft>()
        return try context.fetch(descriptor).filter { $0.isDraftTombstone != true }.map { $0.toRecord() }
    }

    func allDeletionVersions() async throws -> [String: Int] {
        guard let context = modelContext else { throw OfflineStoreDraftError.persistenceUnavailable }
        let descriptor = FetchDescriptor<PersistedComposerDraft>()
        return Dictionary(uniqueKeysWithValues: try context.fetch(descriptor)
            .filter { $0.isDraftTombstone == true }
            .map { ($0.chatId, $0.clearedDraftVersion ?? 0) })
    }

    func apply(_ mutation: ComposerDraftMutation, knownVersion: Int, knownClearedVersion: Int,
               expectedScope: UUID?) async throws -> ComposerDraftApplication {
        if let expectedScope, expectedScope != scopeGeneration { throw OfflineStoreDraftError.staleSession }
        guard let context = modelContext else { throw OfflineStoreDraftError.persistenceUnavailable }
        let targetChatId = mutation.chatId
        let descriptor = FetchDescriptor<PersistedComposerDraft>(predicate: #Predicate { $0.chatId == targetChatId })
        let existing = try context.fetch(descriptor).first
        let application = mutation.applying(to: existing?.toRecord(), knownVersion: knownVersion,
                                            knownClearedVersion: knownClearedVersion)
        if application.applied, let record = application.record {
            if let existing { existing.update(from: record) }
            else { context.insert(PersistedComposerDraft(record: record)) }
            try context.save()
        } else if application.applied, let existing {
            context.delete(existing)
            try context.save()
        }
        return application
    }
}

// A completed cohort receipt represents the full encrypted server snapshot,
// never merely the currently visible fifty rows.
struct OfflineRecentChatSnapshot: Sendable {
    let messages: [Message]
    let embeds: [EmbedRecord]
    let embedKeys: [EmbedKeyRecord]
    let chatKeyWrappers: [ChatKeyWrapperRecord]
    let messagesVersion: Int
    let supplementalContent: Data
    let codeOutputs: [OfflineCachedCodeOutput]
}

struct OfflineCachedCodeOutput: Decodable, Sendable {
    let id: String
    let chatId: String
    let embedId: String
    let authorUserId: String?
    let keyVersion: Int?
    let encryptedPayload: String
    let createdAt: Double
    let updatedAt: Double
}

enum OfflineRecentChatCacheError: Error {
    case incompleteSnapshot, staleSnapshot, keyUnavailable
}

/// A synchronous commit gate prevents a background receipt save from overtaking
/// an accepted foreground update or an account boundary. Only save is serialized.
final class OfflineRecentChatContentFence: @unchecked Sendable {
    private let lock = NSLock()
    private var scope = UUID()
    private var versions: [String: UInt64] = [:]
    func capture(chatID: String) -> OfflineRecentChatWriteFence {
        lock.lock(); defer { lock.unlock() }
        return OfflineRecentChatWriteFence(owner: self, scope: scope, chatID: chatID, version: versions[chatID, default: 0])
    }
    func invalidate(chatID: String) {
        lock.lock(); defer { lock.unlock() }; versions[chatID, default: 0] &+= 1
    }
    func invalidateScope() {
        lock.lock(); defer { lock.unlock() }; scope = UUID(); versions = [:]
    }
    func isCurrent(_ token: OfflineRecentChatWriteFence) -> Bool {
        lock.lock(); defer { lock.unlock() }
        return scope == token.scope && versions[token.chatID, default: 0] == token.version
    }
    func commit(_ token: OfflineRecentChatWriteFence, save: () throws -> Void) throws {
        lock.lock(); defer { lock.unlock() }
        guard scope == token.scope, versions[token.chatID, default: 0] == token.version else {
            throw OfflineRecentChatCacheError.staleSnapshot
        }
        try Task.checkCancellation()
        try save()
    }
}
struct OfflineRecentChatWriteFence: Sendable {
    fileprivate let owner: OfflineRecentChatContentFence
    fileprivate let scope: UUID
    fileprivate let chatID: String
    fileprivate let version: UInt64
    var isCurrent: Bool { owner.isCurrent(self) }
    func commit(save: () throws -> Void) throws { try owner.commit(self, save: save) }
}

@ModelActor
actor OfflineRecentChatCacheWriter {
    func decode(_ data: Data, chatId: String) throws -> OfflineRecentChatSnapshot {
        try Task.checkCancellation()
        guard let fields = try JSONSerialization.jsonObject(with: data) as? [String: Any],
              fields["partial_error"] as? Bool != true else {
            throw OfflineRecentChatCacheError.incompleteSnapshot
        }
        let payload = try ChatContentBatchPayload.decode(fields)
        let messages = try payload.messages(for: chatId)
        guard let version = payload.messagesVersion(for: chatId),
              let count = payload.versionsByChatId[chatId]?["server_message_count"],
              count == messages.count,
              messages.allSatisfy({ $0.chatId == chatId }),
              Set(messages.map(\.id)).count == messages.count else {
            throw OfflineRecentChatCacheError.incompleteSnapshot
        }
        let decoder = JSONDecoder()
        decoder.keyDecodingStrategy = .convertFromSnakeCase
        let codeData = try JSONSerialization.data(withJSONObject: fields["code_run_outputs"] ?? [])
        let outputs = try decoder.decode([OfflineCachedCodeOutput].self, from: codeData)
        let supplementalKeys = ["compression_checkpoints_by_chat_id", "notebook_run_outputs"]
        let supplemental = fields.filter { supplementalKeys.contains($0.key) }
        return OfflineRecentChatSnapshot(messages: messages, embeds: payload.embeds(for: chatId),
            embedKeys: payload.embedKeys, chatKeyWrappers: payload.chatKeyWrappers,
            messagesVersion: version,
            supplementalContent: try JSONSerialization.data(withJSONObject: supplemental),
            codeOutputs: outputs.filter { $0.chatId == chatId })
    }

    func persist(_ snapshot: OfflineRecentChatSnapshot, chat: Chat,
                 validatedWrapper: String?, preserving pendingIDs: Set<String>,
                 fence: OfflineRecentChatWriteFence? = nil,
                 beforeCommit: @escaping @Sendable () async -> Void = {}) async throws {
        try Task.checkCancellation()
        if let fence, !fence.isCurrent { throw OfflineRecentChatCacheError.staleSnapshot }
        // A fresh context reads metadata accepted since the preceding batch.
        let context = ModelContext(modelContainer)
        context.autosaveEnabled = false
        let chatID = chat.id
        let chats = FetchDescriptor<PersistedChat>(predicate: #Predicate { $0.id == chatID })
        guard let storedChat = try context.fetch(chats).first,
              (storedChat.messagesV ?? 0) <= snapshot.messagesVersion,
              OfflineRecentChatPolicy.recency(of: storedChat.toChat()) == OfflineRecentChatPolicy.recency(of: chat) else {
            throw OfflineRecentChatCacheError.staleSnapshot
        }
        let rows = FetchDescriptor<PersistedMessage>(predicate: #Predicate { $0.chatId == chatID })
        let existing = try context.fetch(rows)
        let existingByID = Dictionary(existing.map { ($0.id, $0.toMessage()) }, uniquingKeysWith: { _, last in last })
        let incomingIDs = Set(snapshot.messages.map(\.id))
        let acceptedAliases = Set(snapshot.messages.compactMap { message -> String? in
            guard let alias = message.serverMessageId, alias != message.id,
                  let local = existingByID[alias], local.chatId == chatID, local.role == message.role else { return nil }
            return alias
        })
        let preservedRows = existing.filter {
            pendingIDs.contains($0.id) && !incomingIDs.contains($0.id) && !acceptedAliases.contains($0.id)
        }
        let preservedIDs = Set(preservedRows.map(\.id))
        for row in existing where !preservedIDs.contains(row.id) { context.delete(row) }
        for (index, var message) in snapshot.messages.enumerated() {
            if index.isMultiple(of: 50) { try Task.checkCancellation() }
            let local = message.localBodySource(canonical: existingByID[message.id],
                alias: message.serverMessageId.flatMap { existingByID[$0] })
            if message.content == nil, let local, local.chatId == chatID, local.role == message.role,
               message.encryptedContent != nil, message.encryptedContent == local.encryptedContent {
                message.content = local.content
            }
            let row = PersistedMessage(from: message)
            row.chat = storedChat
            context.insert(row)
        }
        let embeds = FetchDescriptor<PersistedEmbed>(predicate: #Predicate { $0.chatId == chatID })
        let existingEmbeds = Dictionary(try context.fetch(embeds).map { ($0.id, $0) }, uniquingKeysWith: { _, last in last })
        for embed in snapshot.embeds {
            if let current = existingEmbeds[embed.id] { current.update(from: embed, chatId: chatID) }
            else { context.insert(PersistedEmbed(from: embed, chatId: chatID)) }
        }
        for key in snapshot.embedKeys {
            let keyID = PersistedEmbedKey.stableId(for: key)
            let keys = FetchDescriptor<PersistedEmbedKey>(predicate: #Predicate { $0.id == keyID })
            if let current = try context.fetch(keys).first { current.update(from: key) }
            else { context.insert(PersistedEmbedKey(from: key)) }
        }
        for output in snapshot.codeOutputs {
            let outputID = output.id
            let outputs = FetchDescriptor<PersistedCodeRunOutput>(predicate: #Predicate { $0.id == outputID })
            if let existing = try context.fetch(outputs).first {
                if !existing.needsSync && output.updatedAt >= existing.updatedAt {
                    existing.encryptedPayload = output.encryptedPayload
                    existing.keyVersion = output.keyVersion
                    existing.updatedAt = output.updatedAt
                }
            } else {
                context.insert(PersistedCodeRunOutput(id: output.id, chatId: chatID, embedId: output.embedId,
                    authorUserId: output.authorUserId, encryptedPayload: output.encryptedPayload,
                    keyVersion: output.keyVersion, createdAt: output.createdAt, updatedAt: output.updatedAt))
            }
        }
        if let validatedWrapper { storedChat.encryptedChatKey = validatedWrapper }
        storedChat.offlineSupplementalContentJSON = snapshot.supplementalContent
        storedChat.offlineContentMessagesV = snapshot.messagesVersion
        storedChat.offlineContentRecency = OfflineRecentChatPolicy.recency(of: chat)
        storedChat.offlineContentServerCount = snapshot.messages.count
        storedChat.offlineContentRowCount = snapshot.messages.count + preservedRows.count
        await beforeCommit()
        try Task.checkCancellation()
        if let fence { try fence.commit { try context.save() } }
        else { try context.save() }
    }
}
