// Chat store with offline persistence backing via SwiftData.
// Holds decrypted chat list and per-chat message arrays in memory.
// Persists to OfflineStore on every mutation for cold-boot and offline access.

import Foundation
import SwiftUI

@MainActor
final class ChatStore: ObservableObject {
    static let boundedWindowSize = 50

    @Published var chats: [Chat] = []
    @Published private var messagesByChat: [String: [Message]] = [:]
    @Published private var embedsByChat: [String: [String: EmbedRecord]] = [:]

    private var bridge: OfflineSyncBridge?
    private var persistenceSuppressionDepth = 0
    private var serverSortOrderByChatId: [String: Int] = [:]
    private var pendingAssistantRecoveryLookup: (String) -> Set<String> = { _ in [] }

    /// The recovery coordinator supplies account-scoped, durable job awareness.
    /// A server snapshot can precede the terminal completion commit by a lease
    /// interval; it must not erase the reply the originating device just rendered.
    func setPendingAssistantRecoveryLookup(_ lookup: @escaping (String) -> Set<String>) {
        pendingAssistantRecoveryLookup = lookup
    }

    func pendingAssistantRecoveryMessageIds(in chatId: String) -> Set<String> {
        pendingAssistantRecoveryLookup(chatId)
    }

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
        let persisted: Chat
        if let index = chats.firstIndex(where: { $0.id == chat.id }) {
            logMetadataMerge(existing: chats[index], incoming: chat)
            chats[index] = chats[index].merged(with: chat)
            persisted = chats[index]
        } else {
            chats.append(chat)
            persisted = chat
            if NativeSyncPerfLog.verboseCrypto {
                print("[ChatStore] insert chat id=\(chat.id.prefix(8)) title=\(chat.title != nil) category=\(chat.category != nil) icon=\(chat.icon != nil) summary=\(chat.chatSummary != nil) encryptedTitle=\(chat.encryptedTitle != nil)")
            }
        }
        sortChats()
        // Persist the accepted merge, so a rejected late snapshot cannot undo
        // the version/preference fence on the next launch.
        persistIfAllowed { $0.onChatsReceived([persisted]) }
    }

    func upsertChats(_ newChats: [Chat], serverSortOrder: [String]? = nil, serverSortOffset: Int = 0) {
        if let serverSortOrder {
            for (index, chatId) in serverSortOrder.enumerated() {
                serverSortOrderByChatId[chatId] = serverSortOffset + index
            }
        }

        var indexByChatId: [String: Int] = [:]
        for (index, chat) in chats.enumerated() {
            indexByChatId[chat.id] = index
        }
        var persisted: [Chat] = []
        persisted.reserveCapacity(newChats.count)
        for chat in newChats {
            if let index = indexByChatId[chat.id] {
                logMetadataMerge(existing: chats[index], incoming: chat)
                chats[index] = chats[index].merged(with: chat)
                persisted.append(chats[index])
            } else {
                indexByChatId[chat.id] = chats.count
                chats.append(chat)
                persisted.append(chat)
                if NativeSyncPerfLog.verboseCrypto {
                    print("[ChatStore] insert chat id=\(chat.id.prefix(8)) title=\(chat.title != nil) category=\(chat.category != nil) icon=\(chat.icon != nil) summary=\(chat.chatSummary != nil) encryptedTitle=\(chat.encryptedTitle != nil)")
                }
            }
        }
        sortChats()
        persistIfAllowed { $0.onChatsReceived(persisted) }
    }

    func removeChat(_ chatId: String) {
        serverSortOrderByChatId.removeValue(forKey: chatId)
        chats.removeAll { $0.id == chatId }
        messagesByChat.removeValue(forKey: chatId)
        embedsByChat.removeValue(forKey: chatId)
        persistIfAllowed { $0.onChatDeleted(chatId) }
    }

    func clearInMemory() {
        chats.removeAll()
        messagesByChat.removeAll()
        embedsByChat.removeAll()
        serverSortOrderByChatId.removeAll()
    }

    func makeSyncClientState(clientSuggestionsCount: Int) -> SyncClientState {
        let syncableChats = chats.filter { Self.isServerSyncChatId($0.id) }
        let versions = syncableChats.reduce(into: [String: [String: Int]]()) { result, chat in
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
            if let metadataV = chat.metadataV {
                chatVersions["metadata_v"] = metadataV
            }
            if !chatVersions.isEmpty {
                result[chat.id] = chatVersions
            }
        }
        let embedIds = Set(embedsByChat.values.flatMap { $0.keys }).sorted()
        return SyncClientState(
            clientChatVersions: versions,
            clientChatIds: syncableChats.map(\.id),
            clientSuggestionsCount: clientSuggestionsCount,
            clientEmbedIds: embedIds
        )
    }

    static func isServerSyncChatId(_ chatId: String) -> Bool {
        !IncognitoChatSession.isIncognitoChatId(chatId) &&
            !["demo-", "legal-", "example-", "announcements-"].contains { chatId.hasPrefix($0) }
    }

    func chat(for id: String) -> Chat? {
        chats.first { $0.id == id }
    }

    func updateLastVisibleMessage(chatId: String, messageId: String) {
        guard let index = chats.firstIndex(where: { $0.id == chatId }) else { return }
        chats[index] = chats[index].withLastVisibleMessage(messageId)
        persistIfAllowed { $0.onChatsReceived([chats[index]]) }
    }

    func updateDraftVersion(chatId: String, draftVersion: Int, hasNonEmptyDraft: Bool? = nil, clearedDraftVersion: Int? = nil) {
        guard let index = chats.firstIndex(where: { $0.id == chatId }) else { return }
        chats[index] = chats[index].withDraftVersion(draftVersion)
        if let hasNonEmptyDraft { chats[index].hasNonEmptyDraft = hasNonEmptyDraft }
        if let clearedDraftVersion {
            chats[index].clearedDraftV = max(chats[index].clearedDraftV ?? 0, clearedDraftVersion)
        }
        persistIfAllowed { $0.onChatsReceived([chats[index]]) }
    }

    func advanceMessagesVersion(chatId: String, to committedVersion: Int) {
        guard committedVersion >= 0,
              let index = chats.firstIndex(where: { $0.id == chatId }) else { return }
        let currentVersion = chats[index].messagesV ?? 0
        guard committedVersion > currentVersion else { return }
        chats[index] = chats[index].withMessagesVersion(committedVersion)
        persistIfAllowed { $0.onChatsReceived([chats[index]]) }
    }

    func updateActiveFocus(chatId: String, encryptedActiveFocusId: String?, activeFocusId: String?) {
        guard let index = chats.firstIndex(where: { $0.id == chatId }) else { return }
        chats[index] = chats[index].withActiveFocus(
            encryptedActiveFocusId: encryptedActiveFocusId,
            activeFocusId: activeFocusId
        )
        persistIfAllowed { $0.onChatsReceived([chats[index]]) }
    }

    // MARK: - Message operations

    func messages(for chatId: String) -> [Message] {
        messagesByChat[chatId] ?? []
    }

    func initialMessageWindow(for chatId: String, limit: Int = ChatStore.boundedWindowSize) -> [Message] {
        let messages = sortedMessages(for: chatId)
        guard messages.count > limit else { return messages }
        return Array(messages.suffix(limit))
    }

    func olderMessageWindow(for chatId: String, before messageId: String, limit: Int = ChatStore.boundedWindowSize) -> [Message] {
        let messages = sortedMessages(for: chatId)
        guard let boundaryIndex = messages.firstIndex(where: { $0.id == messageId }), boundaryIndex > 0 else {
            return []
        }
        let startIndex = max(0, boundaryIndex - limit)
        return Array(messages[startIndex..<boundaryIndex])
    }

    func hasOlderMessages(for chatId: String, before messageId: String?) -> Bool {
        guard let messageId else { return false }
        let messages = sortedMessages(for: chatId)
        guard let boundaryIndex = messages.firstIndex(where: { $0.id == messageId }) else { return false }
        return boundaryIndex > 0
    }

    func embeds(for chatId: String) -> [EmbedRecord] {
        Array((embedsByChat[chatId] ?? [:]).values)
    }

    func initialEmbedsForVisibleWindow(for chatId: String, messages: [Message]) -> [EmbedRecord] {
        let records = embedsByChat[chatId] ?? [:]
        guard !records.isEmpty else { return [] }
        return lightweightEmbeds(for: messages, records: records)
    }

    func setMessages(for chatId: String, messages: [Message]) {
        let sorted = messages.sorted { a, b in a.createdAt < b.createdAt }
        messagesByChat[chatId] = sorted
        persistIfAllowed { $0.onMessagesReceived(sorted, chatId: chatId) }
    }

    func appendMessage(_ message: Message, to chatId: String) {
        var msgs = messagesByChat[chatId] ?? []
        var accepted = message
        if let index = msgs.firstIndex(where: { $0.id == message.id }) {
            let existing = msgs[index]
            if message.role == .assistant, message.chatId == chatId,
               existing.chatId == chatId, existing.role == .assistant,
               pendingAssistantRecoveryLookup(chatId).contains(message.id),
               let content = message.content, content == existing.content,
               message.encryptedContent?.isEmpty ?? true,
               let ciphertext = existing.encryptedContent, !ciphertext.isEmpty {
                // Terminal recovery can encrypt before the final stream delivery
                // reaches this store. Keep that durable copy only when the exact
                // plaintext still matches; never attach old ciphertext to an edit.
                accepted = Message(
                    id: message.id, chatId: chatId, role: message.role,
                    content: content, encryptedContent: ciphertext,
                    createdAt: message.createdAt, updatedAt: message.updatedAt,
                    appId: message.appId ?? existing.appId, isStreaming: message.isStreaming,
                    embedRefs: message.embedRefs ?? existing.embedRefs,
                    modelName: message.modelName ?? existing.modelName,
                    senderName: message.senderName ?? existing.senderName,
                    category: message.category ?? existing.category,
                    encryptedSenderName: message.encryptedSenderName ?? (message.senderName == nil || message.senderName == existing.senderName ? existing.encryptedSenderName : nil),
                    encryptedCategory: message.encryptedCategory ?? (message.category == nil || message.category == existing.category ? existing.encryptedCategory : nil),
                    encryptedModelName: message.encryptedModelName ?? (message.modelName == nil || message.modelName == existing.modelName ? existing.encryptedModelName : nil),
                    piiMappings: message.piiMappings ?? existing.piiMappings,
                    encryptedPIIMappings: message.encryptedPIIMappings ?? (message.piiMappings == nil || message.piiMappings == existing.piiMappings ? existing.encryptedPIIMappings : nil),
                    thinkingContent: message.thinkingContent ?? existing.thinkingContent,
                    encryptedThinkingContent: message.encryptedThinkingContent ?? (message.thinkingContent == nil || message.thinkingContent == existing.thinkingContent ? existing.encryptedThinkingContent : nil),
                    encryptedThinkingSignature: message.encryptedThinkingSignature ?? (message.thinkingContent == nil || message.thinkingContent == existing.thinkingContent ? existing.encryptedThinkingSignature : nil),
                    thinkingTokenCount: message.thinkingTokenCount ?? existing.thinkingTokenCount
                )
            }
            msgs[index] = accepted
        } else {
            msgs.append(message)
        }
        messagesByChat[chatId] = msgs
        persistIfAllowed { $0.onMessagesReceived([accepted], chatId: chatId) }
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
            let incomingIds = Set(messages.map(\.id))
            let pendingIds = pendingAssistantRecoveryLookup(chatId)
            let pendingReplies = (messagesByChat[chatId] ?? []).filter {
                $0.chatId == chatId && $0.role == .assistant &&
                    pendingIds.contains($0.id) && !incomingIds.contains($0.id)
            }
            // Server rows win once available. Only explicitly pending assistant
            // replies survive an absent row; this never resurrects deleted history
            // or changes the authoritative messages_v advertised to the server.
            nextMessages[chatId] = (messages + pendingReplies).sorted { $0.createdAt < $1.createdAt }
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
            modelName: old.modelName,
            piiMappings: old.piiMappings,
            encryptedPIIMappings: old.encryptedPIIMappings
        )
        msgs[index] = updated
        messagesByChat[chatId] = msgs
        persistIfAllowed { $0.onMessagesReceived([updated], chatId: chatId) }
    }

    // MARK: - Sorting

    var sortedChats: [Chat] {
        chats.sorted(by: chatSortPrecedes)
    }

    var pinnedChats: [Chat] {
        sortedChats.filter { $0.isPinned == true }
    }

    var unpinnedChats: [Chat] {
        sortedChats.filter { $0.isPinned != true && $0.isArchived != true }
    }

    private func sortChats() {
        chats.sort(by: chatSortPrecedes)
    }

    private func chatSortPrecedes(_ a: Chat, _ b: Chat) -> Bool {
        let aHasDraft = a.hasNonEmptyDraft == true
        let bHasDraft = b.hasNonEmptyDraft == true
        if aHasDraft != bHasDraft {
            return aHasDraft
        }

        let aDate = a.lastMessageDate ?? .distantPast
        let bDate = b.lastMessageDate ?? .distantPast
        if aDate != bDate {
            return aDate > bDate
        }

        let aServerOrder = serverSortOrderByChatId[a.id] ?? Int.max
        let bServerOrder = serverSortOrderByChatId[b.id] ?? Int.max
        if aServerOrder != bServerOrder {
            return aServerOrder < bServerOrder
        }

        return (a.updatedDate ?? .distantPast) > (b.updatedDate ?? .distantPast)
    }

    private func sortedMessages(for chatId: String) -> [Message] {
        (messagesByChat[chatId] ?? []).sorted { $0.createdAt < $1.createdAt }
    }

    private func lightweightEmbeds(for messages: [Message], records: [String: EmbedRecord]) -> [EmbedRecord] {
        let referencedIds = Set(messages.flatMap { $0.embedRefs?.map(\.id) ?? [] })
        guard !referencedIds.isEmpty else { return [] }
        var includedIds = referencedIds
        for id in referencedIds {
            if let parentId = records[id]?.parentEmbedId {
                includedIds.insert(parentId)
            }
        }
        return includedIds.compactMap { records[$0] }
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
    func withMessagesVersion(_ messagesVersion: Int) -> Chat {
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
            encryptedAutoSpeakResponse: encryptedAutoSpeakResponse,
            encryptedChatKey: encryptedChatKey,
            messagesV: messagesVersion,
            titleV: titleV,
            draftV: draftV,
            metadataV: metadataV,
            lastVisibleMessageId: lastVisibleMessageId,
            parentId: parentId,
            isSubChat: isSubChat,
            subChatSettings: subChatSettings,
            budgetLimit: budgetLimit,
            budgetSpent: budgetSpent,
            encryptedActiveFocusId: encryptedActiveFocusId,
            activeFocusId: activeFocusId,
            isPrivate: isPrivate,
            isHidden: isHidden,
            isHiddenCandidate: isHiddenCandidate,
            hasNonEmptyDraft: hasNonEmptyDraft,
            clearedDraftV: clearedDraftV
        )
    }

}

extension Chat {
    func withSpeechPreference(_ ciphertext: String, metadataVersion: Int) -> Chat {
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
            encryptedAutoSpeakResponse: ciphertext,
            encryptedChatKey: encryptedChatKey,
            messagesV: messagesV,
            titleV: titleV,
            draftV: draftV,
            metadataV: metadataVersion,
            lastVisibleMessageId: lastVisibleMessageId,
            parentId: parentId,
            isSubChat: isSubChat,
            subChatSettings: subChatSettings,
            budgetLimit: budgetLimit,
            budgetSpent: budgetSpent,
            encryptedActiveFocusId: encryptedActiveFocusId,
            activeFocusId: activeFocusId,
            isPrivate: isPrivate,
            isHidden: isHidden,
            isHiddenCandidate: isHiddenCandidate,
            hasNonEmptyDraft: hasNonEmptyDraft,
            clearedDraftV: clearedDraftV
        )
    }

}

private extension Chat {
    func withDraftVersion(_ draftVersion: Int) -> Chat {
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
            encryptedAutoSpeakResponse: encryptedAutoSpeakResponse,
            encryptedChatKey: encryptedChatKey,
            messagesV: messagesV,
            titleV: titleV,
            draftV: draftVersion,
            metadataV: metadataV,
            lastVisibleMessageId: lastVisibleMessageId,
            parentId: parentId,
            isSubChat: isSubChat,
            subChatSettings: subChatSettings,
            budgetLimit: budgetLimit,
            budgetSpent: budgetSpent,
            encryptedActiveFocusId: encryptedActiveFocusId,
            activeFocusId: activeFocusId,
            isPrivate: isPrivate,
            isHidden: isHidden,
            isHiddenCandidate: isHiddenCandidate,
            hasNonEmptyDraft: draftVersion == 0 ? false : hasNonEmptyDraft,
            clearedDraftV: clearedDraftV
        )
    }

    func merged(with incoming: Chat) -> Chat {
        let incomingVersion = max(incoming.draftV ?? 0, incoming.clearedDraftV ?? 0)
        let incomingClears = incoming.hasNonEmptyDraft == false
            || (incoming.draftV == 0 && (incoming.messagesV ?? 0) > 0)
        let acceptsDraft = incomingClears
            ? ComposerDraftVersionPolicy.acceptsDeletion(version: incomingVersion, currentVersion: draftV ?? 0)
            : ComposerDraftVersionPolicy.acceptsContent(version: incomingVersion,
                currentVersion: draftV ?? 0, hasDraft: hasNonEmptyDraft == true, clearedVersion: clearedDraftV ?? 0)
        let clears = acceptsDraft && incomingClears
        let resolvedDraftVersion = clears ? 0 : (acceptsDraft ? incoming.draftV ?? draftV : draftV)
        let resolvedPresence = clears ? false : (acceptsDraft ? incoming.hasNonEmptyDraft ?? hasNonEmptyDraft : hasNonEmptyDraft)
        let resolvedClearedVersion = clears
            ? max(clearedDraftV ?? 0, max(draftV ?? 0, incomingVersion))
            : max(clearedDraftV ?? 0, incoming.clearedDraftV ?? 0)
        return Chat(
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
            encryptedAutoSpeakResponse: (incoming.metadataV ?? incoming.titleV ?? 0) >= (metadataV ?? titleV ?? 0) ? (incoming.encryptedAutoSpeakResponse ?? encryptedAutoSpeakResponse) : encryptedAutoSpeakResponse,
            encryptedChatKey: incoming.encryptedChatKey ?? encryptedChatKey,
            messagesV: [messagesV, incoming.messagesV].compactMap { $0 }.max(),
            titleV: [titleV, incoming.titleV].compactMap { $0 }.max(),
            draftV: resolvedDraftVersion,
            metadataV: [metadataV, incoming.metadataV].compactMap { $0 }.max(),
            lastVisibleMessageId: incoming.lastVisibleMessageId ?? lastVisibleMessageId,
            parentId: incoming.parentId ?? parentId,
            isSubChat: incoming.isSubChat ?? isSubChat,
            subChatSettings: incoming.subChatSettings ?? subChatSettings,
            budgetLimit: incoming.budgetLimit ?? budgetLimit,
            budgetSpent: incoming.budgetSpent ?? budgetSpent,
            encryptedActiveFocusId: incoming.encryptedActiveFocusId ?? encryptedActiveFocusId,
            activeFocusId: incoming.activeFocusId ?? activeFocusId,
            isPrivate: incoming.isPrivate ?? isPrivate,
            isHidden: incoming.isHidden ?? isHidden,
            isHiddenCandidate: incoming.isHiddenCandidate ?? isHiddenCandidate,
            hasNonEmptyDraft: resolvedPresence,
            clearedDraftV: resolvedClearedVersion
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
            encryptedAutoSpeakResponse: encryptedAutoSpeakResponse,
            encryptedChatKey: encryptedChatKey,
            messagesV: messagesV,
            titleV: titleV,
            draftV: draftV,
            metadataV: metadataV,
            lastVisibleMessageId: messageId,
            parentId: parentId,
            isSubChat: isSubChat,
            subChatSettings: subChatSettings,
            budgetLimit: budgetLimit,
            budgetSpent: budgetSpent,
            encryptedActiveFocusId: encryptedActiveFocusId,
            activeFocusId: activeFocusId,
            isPrivate: isPrivate,
            isHidden: isHidden,
            isHiddenCandidate: isHiddenCandidate,
            hasNonEmptyDraft: hasNonEmptyDraft,
            clearedDraftV: clearedDraftV
        )
    }

    func withActiveFocus(encryptedActiveFocusId: String?, activeFocusId: String?) -> Chat {
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
            encryptedAutoSpeakResponse: encryptedAutoSpeakResponse,
            encryptedChatKey: encryptedChatKey,
            messagesV: messagesV,
            titleV: titleV,
            draftV: draftV,
            metadataV: metadataV,
            lastVisibleMessageId: lastVisibleMessageId,
            parentId: parentId,
            isSubChat: isSubChat,
            subChatSettings: subChatSettings,
            budgetLimit: budgetLimit,
            budgetSpent: budgetSpent,
            encryptedActiveFocusId: encryptedActiveFocusId,
            activeFocusId: activeFocusId,
            isPrivate: isPrivate,
            isHidden: isHidden,
            isHiddenCandidate: isHiddenCandidate,
            hasNonEmptyDraft: hasNonEmptyDraft,
            clearedDraftV: clearedDraftV
        )
    }
}
