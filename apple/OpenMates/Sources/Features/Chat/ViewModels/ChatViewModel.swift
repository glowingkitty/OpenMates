// Chat view model — manages messages, streaming, and embeds for a single chat.
// Mirrors the web app's dual-phase send protocol: WebSocket plaintext for AI
// processing, then client-encrypted metadata/messages for permanent storage.
// Subscribes to StreamingClient for real-time AI response chunks.

import Foundation
import SwiftUI
import CryptoKit

@MainActor
final class ChatViewModel: ObservableObject {
    struct ChatOpeningMetrics: Equatable {
        var initialMessagesReceived = 0
        var initialMessagesDecrypted = 0
        var initialEmbedsReceived = 0
        var fullEmbedsDecrypted = 0
        var firstUsefulRenderMs = 0
    }

    @Published var chat: Chat?
    @Published var messages: [Message] = []
    @Published var embedRecords: [String: EmbedRecord] = [:]
    @Published var isLoading = false
    @Published var isStreaming = false
    @Published var streamingContent = ""
    @Published var streamingMessageId: String?
    @Published var followUpSuggestions: [String] = []
    @Published var error: String?
    @Published private(set) var openingMetrics = ChatOpeningMetrics()
    @Published private(set) var pendingComposerEmbeds: [ComposerPendingEmbed] = []

    var hasPendingComposerEmbeds: Bool {
        !pendingComposerEmbeds.isEmpty
    }

    /// Number of messages to show initially and per page when scrolling up.
    private let messagesPageSize = 50
    /// All messages fetched from the server (full history).
    private var allMessages: [Message] = []
    /// Index in `allMessages` where the currently-rendered message window starts.
    private var visibleWindowStartIndex = 0
    /// Whether there are older messages above the currently visible window.
    @Published var hasOlderMessages = false
    @Published var isLoadingOlder = false

    private let api = APIClient.shared
    private let sendPipeline = ChatSendPipeline()
    private weak var wsManager: WebSocketManager?
    private weak var chatStore: ChatStore?
    private var streamTask: Task<Void, Never>?
    private var embedHydrationTask: Task<Void, Never>?
    private var loadGeneration = 0
    private var pendingUserMessagesById: [String: Message] = [:]
    private var userMessageIdByAssistantMessageId: [String: String] = [:]
    private var assistantMessageCreatedAtById: [String: String] = [:]
    private var assistantCategoryByMessageId: [String: String] = [:]
    private var assistantModelNameByMessageId: [String: String] = [:]
    nonisolated(unsafe) private var embedRefreshObserver: Any?

    func configure(wsManager: WebSocketManager?, chatStore: ChatStore?) {
        self.wsManager = wsManager
        self.chatStore = chatStore
    }

    func loadChat(id: String, initialChat: Chat? = nil, initialMessages: [Message] = [], initialEmbeds: [EmbedRecord] = []) async {
        loadGeneration += 1
        let generation = loadGeneration
        embedHydrationTask?.cancel()
        isLoading = true
        error = nil

        if loadPublicChat(id: id) {
            isLoading = false
            return
        }

        if let initialChat {
            await loadSyncedChat(initialChat, messages: initialMessages, embeds: initialEmbeds, generation: generation)
            return
        }

        do {
            var loadedChat: Chat = try await api.request(.get, path: "/v1/chats/\(id)")

            // Ensure chat key is loaded (may not be if chat was opened via deep link)
            await ensureChatKey(for: loadedChat)

            loadedChat = await decryptMetadata(for: loadedChat)
            chat = loadedChat

            let messagesResponse: [Message] = try await api.request(.get, path: "/v1/chats/\(id)/messages")

            allMessages = messagesResponse.sorted { $0.createdAt < $1.createdAt }
            let visibleRawMessages = visibleWindow(from: allMessages, anchorMessageId: loadedChat.lastVisibleMessageId)
            let decryptedMessages = await decryptMessages(visibleRawMessages, chatId: id)
            let embedded = PublicChatContent.attachEmbeds(to: decryptedMessages)
            embedRecords = embedded.records
            followUpSuggestions = extractFollowUpSuggestions(from: embedded.messages)

            // Show only the window around the restored scroll anchor for fast rendering.
            if visibleWindowStartIndex > 0 {
                messages = embedded.messages
                hasOlderMessages = true
            } else {
                messages = embedded.messages
                hasOlderMessages = false
            }

            // Start listening for streaming events and embed updates
            subscribeToStream(chatId: id)
            subscribeToEmbedUpdates(chatId: id)
            isLoading = false
            scheduleEmbedHydration(
                syncedEmbeds: [],
                referencedIds: Set(embedded.messages.flatMap { $0.embedRefs?.map(\.id) ?? [] }),
                chatId: id,
                generation: generation,
                existingRecords: embedRecords,
                source: "rest"
            )
        } catch {
            self.error = error.localizedDescription
            isLoading = false
        }
    }

    func applySynced(chat syncedChat: Chat?, messages syncedMessages: [Message], embeds syncedEmbeds: [EmbedRecord] = []) async {
        guard let currentId = chat?.id else { return }
        if let syncedChat, syncedChat.id != currentId { return }
        if !syncedMessages.isEmpty && syncedMessages.allSatisfy({ $0.chatId != currentId }) { return }
        let nextChat = syncedChat ?? chat
        guard let nextChat else { return }
        loadGeneration += 1
        let generation = loadGeneration
        embedHydrationTask?.cancel()
        await loadSyncedChat(nextChat, messages: syncedMessages.isEmpty ? allMessages : syncedMessages, embeds: syncedEmbeds, generation: generation)
    }

    func applySyncedEmbeds(_ syncedEmbeds: [EmbedRecord]) async {
        guard let chatId = chat?.id, !messages.isEmpty, !syncedEmbeds.isEmpty else { return }
        let referencedIds = Set(messages.flatMap { $0.embedRefs?.map(\.id) ?? [] })
        guard !referencedIds.isEmpty else { return }
        let currentRecords = embedRecords
        let incomingRecords = EmbedRecord.dictionaryById(syncedEmbeds, context: "chatViewModel.applySyncedEmbeds.incoming")
        let changedEmbeds = incomingRecords.values.filter { incoming in
            guard let existing = currentRecords[incoming.id] else { return true }
            return existing.rawData == nil || existing.encryptedType != nil || existing.encryptedContent != incoming.encryptedContent
        }
        guard !changedEmbeds.isEmpty else { return }
        let mergedRecords = currentRecords.merging(incomingRecords) { _, new in new }
        embedRecords = mergedRecords
        scheduleEmbedHydration(
            syncedEmbeds: Array(mergedRecords.values),
            referencedIds: referencedIds,
            chatId: chatId,
            generation: loadGeneration,
            existingRecords: mergedRecords,
            source: "syncEmbeds"
        )
    }

    private func loadSyncedChat(_ syncedChat: Chat, messages syncedMessages: [Message], embeds syncedEmbeds: [EmbedRecord], generation: Int) async {
        var loadedChat = syncedChat
        let start = NativeSyncPerfLog.now()
        await ensureChatKey(for: loadedChat)
        loadedChat = await decryptMetadata(for: loadedChat)
        guard generation == loadGeneration else { return }
        if NativeSyncPerfLog.verboseCrypto {
            print("[ChatViewModel][loadSynced] chat=\(loadedChat.id.prefix(8)) afterMetadata title=\(loadedChat.title != nil) category=\(loadedChat.category != nil) icon=\(loadedChat.icon != nil) summary=\(loadedChat.chatSummary != nil) hasKey=\(ChatKeyManager.shared.hasKey(for: loadedChat.id))")
        }

        chat = loadedChat
        let rawMessages = syncedMessages.sorted { $0.createdAt < $1.createdAt }
        openingMetrics.initialMessagesReceived = rawMessages.count
        openingMetrics.initialEmbedsReceived = syncedEmbeds.count
        allMessages = rawMessages
        let visibleRawMessages = visibleWindow(from: rawMessages, anchorMessageId: loadedChat.lastVisibleMessageId)
        let decryptedMessages = await decryptMessages(visibleRawMessages, chatId: loadedChat.id)
        openingMetrics.initialMessagesDecrypted = decryptedMessages.count
        guard generation == loadGeneration else { return }
        let embedded = PublicChatContent.attachEmbeds(to: decryptedMessages)
        let existingRecords = embedRecords
        let referencedIds = Set(embedded.messages.flatMap { $0.embedRefs?.map(\.id) ?? [] })
        let directEmbedRefs = embedded.messages.flatMap { $0.embedRefs ?? [] }.count
        embedRecords = existingRecords.merging(embedded.records) { _, new in new }
        followUpSuggestions = extractFollowUpSuggestions(from: embedded.messages)

        messages = embedded.messages
        hasOlderMessages = chatStore?.hasOlderMessages(for: loadedChat.id, before: embedded.messages.first?.id) ?? (visibleWindowStartIndex > 0)

        subscribeToStream(chatId: loadedChat.id)
        subscribeToEmbedUpdates(chatId: loadedChat.id)
        isLoading = false
        NativeSyncPerfLog.info(
            "phase=loadSyncedChatFirstPaint chat=\(loadedChat.id.prefix(8)) visibleMessages=\(decryptedMessages.count) totalMessages=\(rawMessages.count) embedRefs=\(directEmbedRefs) inlineRecords=\(embedded.records.count) syncedEmbeds=\(syncedEmbeds.count) elapsedMs=\(NativeSyncPerfLog.ms(since: start))"
        )
        openingMetrics.firstUsefulRenderMs = NativeSyncPerfLog.ms(since: start)
        scheduleEmbedHydration(
            syncedEmbeds: syncedEmbeds,
            referencedIds: referencedIds,
            chatId: loadedChat.id,
            generation: generation,
            existingRecords: embedRecords,
            source: "loadSynced"
        )
    }

    private func scheduleEmbedHydration(
        syncedEmbeds: [EmbedRecord],
        referencedIds: Set<String>,
        chatId: String,
        generation: Int,
        existingRecords: [String: EmbedRecord],
        source: String
    ) {
        embedHydrationTask?.cancel()
        embedHydrationTask = Task { @MainActor [weak self] in
            guard let self else { return }
            await Task.yield()
            try? await Task.sleep(nanoseconds: 120_000_000)
            guard !Task.isCancelled, self.chat?.id == chatId, generation == self.loadGeneration else { return }
            let start = NativeSyncPerfLog.now()
            let relatedSyncedEmbeds = self.relatedEmbeds(referencedIds: referencedIds, from: syncedEmbeds)
            let decryptedSyncedEmbeds = await self.decryptEmbeds(
                relatedSyncedEmbeds,
                chatId: chatId,
                existingRecords: existingRecords
            )
            guard !Task.isCancelled, self.chat?.id == chatId, generation == self.loadGeneration else { return }
            self.embedRecords = decryptedSyncedEmbeds.reduce(into: self.embedRecords) { records, embed in
                records[embed.id] = embed
            }
            self.openingMetrics.fullEmbedsDecrypted += decryptedSyncedEmbeds.filter { $0.rawData != nil }.count
            await self.loadEmbeds(for: self.messages.map(\.id))
            NativeSyncPerfLog.info(
                "phase=embedHydrationComplete source=\(source) chat=\(chatId.prefix(8)) referenced=\(referencedIds.count) related=\(relatedSyncedEmbeds.count) decrypted=\(decryptedSyncedEmbeds.filter { $0.rawData != nil }.count) totalRecords=\(self.embedRecords.count) elapsedMs=\(NativeSyncPerfLog.ms(since: start))"
            )
        }
    }

    private func decryptMetadata(for chat: Chat) async -> Chat {
        var decrypted = chat
        guard ChatKeyManager.shared.hasKey(for: decrypted.id) else {
            if NativeSyncPerfLog.verboseCrypto {
                print("[ChatViewModel][decrypt] chat=\(decrypted.id.prefix(8)) missing chat key; encTitle=\(decrypted.encryptedTitle != nil) encCategory=\(decrypted.encryptedCategory != nil) encIcon=\(decrypted.encryptedIcon != nil) encSummary=\(decrypted.encryptedChatSummary != nil)")
            }
            return decrypted
        }
        if decrypted.title == nil,
           let encryptedTitle = decrypted.encryptedTitle,
           let title = await ChatKeyManager.shared.decryptChatField(
               chatId: decrypted.id,
               encryptedValue: encryptedTitle,
               fieldName: "encrypted_title"
        ) {
            decrypted.title = title
            if NativeSyncPerfLog.verboseCrypto {
                print("[ChatViewModel][decrypt] chat=\(decrypted.id.prefix(8)) title ok")
            }
        } else if decrypted.title == nil, decrypted.encryptedTitle != nil {
            if NativeSyncPerfLog.verboseCrypto {
                print("[ChatViewModel][decrypt] chat=\(decrypted.id.prefix(8)) title missing after decrypt attempt")
            }
        }
        if decrypted.category == nil,
           let encryptedCategory = decrypted.encryptedCategory,
           let category = await ChatKeyManager.shared.decryptChatField(
               chatId: decrypted.id,
               encryptedValue: encryptedCategory,
               fieldName: "encrypted_category"
        ) {
            decrypted.category = category
            if NativeSyncPerfLog.verboseCrypto {
                print("[ChatViewModel][decrypt] chat=\(decrypted.id.prefix(8)) category ok")
            }
        } else if decrypted.category == nil, decrypted.encryptedCategory != nil {
            if NativeSyncPerfLog.verboseCrypto {
                print("[ChatViewModel][decrypt] chat=\(decrypted.id.prefix(8)) category missing after decrypt attempt")
            }
        }
        if decrypted.icon == nil,
           let encryptedIcon = decrypted.encryptedIcon,
           let icon = await ChatKeyManager.shared.decryptChatField(
               chatId: decrypted.id,
               encryptedValue: encryptedIcon,
               fieldName: "encrypted_icon"
        ) {
            decrypted.icon = icon
            if NativeSyncPerfLog.verboseCrypto {
                print("[ChatViewModel][decrypt] chat=\(decrypted.id.prefix(8)) icon ok")
            }
        } else if decrypted.icon == nil, decrypted.encryptedIcon != nil {
            if NativeSyncPerfLog.verboseCrypto {
                print("[ChatViewModel][decrypt] chat=\(decrypted.id.prefix(8)) icon missing after decrypt attempt")
            }
        }
        if decrypted.chatSummary == nil,
           let encryptedSummary = decrypted.encryptedChatSummary,
           let summary = await ChatKeyManager.shared.decryptChatField(
               chatId: decrypted.id,
               encryptedValue: encryptedSummary,
               fieldName: "encrypted_chat_summary"
        ) {
            decrypted.chatSummary = summary
            if NativeSyncPerfLog.verboseCrypto {
                print("[ChatViewModel][decrypt] chat=\(decrypted.id.prefix(8)) summary ok")
            }
        } else if decrypted.chatSummary == nil, decrypted.encryptedChatSummary != nil {
            if NativeSyncPerfLog.verboseCrypto {
                print("[ChatViewModel][decrypt] chat=\(decrypted.id.prefix(8)) summary missing after decrypt attempt")
            }
        }
        return decrypted
    }

    // MARK: - Public bundled chats

    private func loadPublicChat(id: String) -> Bool {
        guard let publicChat = PublicChatContent.chat(for: id) else { return false }

        chat = publicChat.chat
        embedRecords = publicChat.embedRecords
        allMessages = publicChat.messages
        messages = publicChat.messages
        followUpSuggestions = publicChat.followUpSuggestions
        hasOlderMessages = false
        isLoadingOlder = false
        isStreaming = false
        streamingContent = ""
        streamingMessageId = nil
        streamTask?.cancel()
        if let observer = embedRefreshObserver {
            NotificationCenter.default.removeObserver(observer)
            embedRefreshObserver = nil
        }
        return true
    }

    /// Ensure the chat key is available (load from master key if not cached).
    private func ensureChatKey(for chat: Chat) async {
        guard !ChatKeyManager.shared.hasKey(for: chat.id),
              let encryptedChatKey = chat.encryptedChatKey else { return }

        // Try to load master key and unwrap this chat's key
        guard let userId = await AuthManager.currentUserId(),
              let masterKey = try? await CryptoManager.shared.loadMasterKey(for: userId) else {
            return
        }

        await ChatKeyManager.shared.loadChatKey(
            chatId: chat.id,
            encryptedChatKey: encryptedChatKey,
            masterKey: masterKey
        )
    }

    /// Decrypt encrypted_content for a batch of messages using the per-chat key.
    private func decryptMessages(_ messages: [Message], chatId: String) async -> [Message] {
        let encryptedCount = messages.filter { $0.encryptedContent != nil }.count
        if encryptedCount > 0, !ChatKeyManager.shared.hasKey(for: chatId) {
            print("[ChatViewModel][decrypt] messages skipped chat=\(chatId.prefix(8)) encrypted=\(encryptedCount) reason=missingChatKey")
        }
        var result: [Message] = []
        for var msg in messages {
            if msg.content == nil || msg.content?.isEmpty == true,
               let enc = msg.encryptedContent {
                if let decrypted = await ChatKeyManager.shared.decryptMessageContent(
                    chatId: chatId, encryptedContent: enc
                ) {
                    msg.content = decrypted
                }
            }
            result.append(msg)
        }
        return result
    }

    private func decryptEmbeds(
        _ embeds: [EmbedRecord],
        chatId: String,
        existingRecords: [String: EmbedRecord] = [:]
    ) async -> [EmbedRecord] {
        guard !embeds.isEmpty else { return [] }
        let encryptedCount = embeds.filter { $0.encryptedContent != nil || $0.encryptedType != nil }.count
        var allRecords = existingRecords
        for embed in embeds {
            allRecords[embed.id] = embed
        }
        let start = NativeSyncPerfLog.now()

        var decryptedEmbeds: [EmbedRecord] = []
        for embed in embeds {
            guard embed.rawData == nil || embed.encryptedType != nil else {
                decryptedEmbeds.append(embed)
                continue
            }
            guard embed.encryptedContent != nil || embed.encryptedType != nil else {
                decryptedEmbeds.append(embed)
                continue
            }
            guard let embedKey = await EmbedKeyManager.shared.key(for: embed, chatId: chatId, allEmbeds: allRecords) else {
                if NativeSyncPerfLog.verboseCrypto {
                    print("[ChatViewModel][embeds][decrypt] key missing chat=\(chatId.prefix(8)) embed=\(embed.id.prefix(8)) parent=\(embed.parentEmbedId?.prefix(8) ?? "nil") hasEncryptedContent=\(embed.encryptedContent != nil)")
                }
                decryptedEmbeds.append(embed)
                continue
            }

            var decryptedContent: String?
            if let encryptedContent = embed.encryptedContent {
                do {
                    decryptedContent = try await CryptoManager.shared.decryptContent(
                        base64String: encryptedContent.trimmingCharacters(in: .whitespacesAndNewlines),
                        key: embedKey
                    )
                } catch {
                    if NativeSyncPerfLog.verboseCrypto {
                        print("[ChatViewModel][embeds][decrypt] content failed chat=\(chatId.prefix(8)) embed=\(embed.id.prefix(8)) error=\(error.localizedDescription)")
                    }
                }
            }

            var decryptedType: String?
            if let encryptedType = embed.encryptedType {
                do {
                    decryptedType = try await CryptoManager.shared.decryptContent(
                        base64String: encryptedType.trimmingCharacters(in: .whitespacesAndNewlines),
                        key: embedKey
                    )
                } catch {
                    if NativeSyncPerfLog.verboseCrypto {
                        print("[ChatViewModel][embeds][decrypt] type failed chat=\(chatId.prefix(8)) embed=\(embed.id.prefix(8)) error=\(error.localizedDescription)")
                    }
                }
            }

            let decrypted = embed.decryptedCopy(content: decryptedContent, type: decryptedType)
            allRecords[decrypted.id] = decrypted
            decryptedEmbeds.append(decrypted)
        }
        NativeSyncPerfLog.info(
            "phase=decryptEmbeds chat=\(chatId.prefix(8)) embeds=\(embeds.count) encrypted=\(encryptedCount) raw=\(decryptedEmbeds.filter { $0.rawData != nil }.count) decryptMs=\(NativeSyncPerfLog.ms(since: start))"
        )
        EmbedMediaOfflineCache.prefetchEmbeds(decryptedEmbeds)
        return decryptedEmbeds
    }

    /// Load the next page of older messages above the current window.
    func loadOlderMessages() {
        guard hasOlderMessages, !isLoadingOlder else { return }
        isLoadingOlder = true

        if let chatId = chat?.id,
           let topMessageId = messages.first?.id,
           let olderBatch = chatStore?.olderMessageWindow(for: chatId, before: topMessageId),
           !olderBatch.isEmpty {
            Task { @MainActor in
                let decrypted = await decryptMessages(olderBatch, chatId: chatId)
                let embedded = PublicChatContent.attachEmbeds(to: decrypted)
                for (id, record) in embedded.records {
                    embedRecords[id] = record
                }
                messages.insert(contentsOf: embedded.messages, at: 0)
                allMessages.insert(contentsOf: olderBatch, at: 0)
                hasOlderMessages = chatStore?.hasOlderMessages(for: chatId, before: embedded.messages.first?.id) ?? false
                await loadEmbeds(for: embedded.messages.map(\.id))
                isLoadingOlder = false
            }
            return
        }

        let currentStartIndex = visibleWindowStartIndex

        if currentStartIndex > 0 {
            let nextPageSize = min(messagesPageSize, currentStartIndex)
            let startIndex = currentStartIndex - nextPageSize
            let olderBatch = Array(allMessages[startIndex..<currentStartIndex])
            Task { @MainActor in
                guard let chatId = chat?.id else {
                    isLoadingOlder = false
                    return
                }
                let decrypted = await decryptMessages(olderBatch, chatId: chatId)
                let embedded = PublicChatContent.attachEmbeds(to: decrypted)
                for (id, record) in embedded.records {
                    embedRecords[id] = record
                }
                EmbedMediaOfflineCache.prefetchEmbeds(Array(embedded.records.values))
                messages.insert(contentsOf: embedded.messages, at: 0)
                visibleWindowStartIndex = startIndex
                hasOlderMessages = startIndex > 0
                await loadEmbeds(for: embedded.messages.map(\.id))
                isLoadingOlder = false
            }
        } else {
            hasOlderMessages = false
            isLoadingOlder = false
        }
    }

    // MARK: - Send message

    func sendMessage(_ content: String) async {
        guard let currentChat = chat else { return }
        do {
            let composerEmbeds = pendingComposerEmbeds
            let result = try await sendPipeline.sendUserMessage(
                content: contentWithComposerEmbedReferences(content, embeds: composerEmbeds),
                in: currentChat,
                existingMessages: allMessages,
                wsManager: wsManager,
                chatStore: chatStore,
                composerEmbeds: composerEmbeds
            )
            chat = result.chat
            pendingUserMessagesById[result.message.id] = result.message
            appendOrReplaceLocalMessage(result.message)
            pendingComposerEmbeds.removeAll()
            isStreaming = true
            streamingContent = ""
        } catch {
            self.error = error.localizedDescription
            isStreaming = false
        }
    }

    // MARK: - Stop streaming

    func stopStreaming() {
        streamTask?.cancel()
        isStreaming = false
        streamingContent = ""
        streamingMessageId = nil
    }

    // MARK: - Streaming subscription

    private func subscribeToStream(chatId: String) {
        streamTask?.cancel()
        streamTask = Task {
            let stream = await StreamingClient.shared.streamForChat(chatId)
            for await event in stream {
                guard !Task.isCancelled else { break }
                handleStreamEvent(event)
            }
        }
    }

    private func handleStreamEvent(_ event: StreamingClient.StreamEvent) {
        switch event {
        case .taskInitiated(_, _, _):
            isStreaming = true
            streamingContent = ""

        case .typingStarted(let chatId, let messageId, let metadata):
            streamingMessageId = messageId
            if let userMessageId = metadata?.userMessageId {
                userMessageIdByAssistantMessageId[messageId] = userMessageId
            }
            if let category = metadata?.category {
                assistantCategoryByMessageId[messageId] = category
            }
            if let modelName = metadata?.modelName {
                assistantModelNameByMessageId[messageId] = modelName
            }
            if let metadata {
                Task { @MainActor in
                    await sendEncryptedUserStorageIfPossible(
                        chatId: chatId,
                        assistantMessageId: messageId,
                        metadata: metadata
                    )
                }
            }

        case .chunk(let chatId, let messageId, _, let content, let isFinal, let userMessageId, let category, let modelName, let rejectionReason):
            streamingMessageId = messageId
            if let userMessageId {
                userMessageIdByAssistantMessageId[messageId] = userMessageId
            }
            if let category {
                assistantCategoryByMessageId[messageId] = category
            }
            if let modelName {
                assistantModelNameByMessageId[messageId] = modelName
            }

            let resolvedCategory = category ?? assistantCategoryByMessageId[messageId] ?? chat?.category ?? chat?.appId
            let resolvedModelName = modelName ?? assistantModelNameByMessageId[messageId]
            let displayContent = streamingDisplayContent(for: messageId, incomingContent: content, isFinal: isFinal)
            streamingContent = displayContent

            if isFinal {
                let rawAssistantMessage = Message(
                    id: messageId, chatId: chatId, role: rejectionReason == nil ? .assistant : .system,
                    content: content, encryptedContent: nil,
                    createdAt: createdAtForAssistantMessage(messageId),
                    updatedAt: nil, appId: resolvedCategory, isStreaming: false, embedRefs: nil,
                    modelName: resolvedModelName
                )
                let embedded = PublicChatContent.attachEmbeds(to: [rawAssistantMessage])
                for (id, record) in embedded.records {
                    embedRecords[id] = record
                }
                let assistantMessage = embedded.messages.first ?? rawAssistantMessage
                appendOrReplaceLocalMessage(assistantMessage)
                followUpSuggestions = extractFollowUpSuggestions(from: allMessages)
                isStreaming = false
                streamingContent = ""
                streamingMessageId = nil
                assistantMessageCreatedAtById.removeValue(forKey: messageId)
                assistantCategoryByMessageId.removeValue(forKey: messageId)
                assistantModelNameByMessageId.removeValue(forKey: messageId)
                Task { @MainActor in
                    await persistCompletedAssistantMessage(
                        assistantMessage,
                        userMessageId: userMessageIdByAssistantMessageId[messageId]
                    )
                }
            } else {
                let partialAssistantMessage = Message(
                    id: messageId, chatId: chatId, role: rejectionReason == nil ? .assistant : .system,
                    content: displayContent, encryptedContent: nil,
                    createdAt: createdAtForAssistantMessage(messageId),
                    updatedAt: nil, appId: resolvedCategory, isStreaming: true, embedRefs: nil,
                    modelName: resolvedModelName
                )
                appendOrReplaceTransientMessage(partialAssistantMessage)
                isStreaming = true
            }

        case .thinkingChunk(_, _, _):
            break

        case .thinkingComplete(_, _):
            break

        case .messageReady(_, _):
            isStreaming = false

        case .preprocessingStep(_, _, _):
            break

        case .postProcessingCompleted(let chatId, _, let followUps, let newSuggestions, let summary, let tags, let updatedTitle):
            guard chat?.id == chatId else { return }
            followUpSuggestions = Array(followUps.prefix(18))
            Task { @MainActor in
                await sendPipeline.sendPostProcessingMetadata(
                    chatId: chatId,
                    followUpSuggestions: followUps,
                    newChatSuggestions: newSuggestions,
                    chatSummary: summary,
                    chatTags: tags,
                    updatedTitle: updatedTitle,
                    wsManager: wsManager,
                    chatStore: chatStore
                )
            }

        case .error(let msg):
            error = msg
            isStreaming = false
        }
    }

    private func sendEncryptedUserStorageIfPossible(
        chatId: String,
        assistantMessageId: String,
        metadata: StreamingClient.ChatMetadata
    ) async {
        guard chat?.id == chatId else { return }
        let userMessageId = metadata.userMessageId ?? userMessageIdByAssistantMessageId[assistantMessageId]
        guard let userMessageId,
              let userMessage = pendingUserMessagesById[userMessageId] ?? allMessages.first(where: { $0.id == userMessageId }),
              let currentChat = chat else { return }
        do {
            let updatedChat = try await sendPipeline.sendEncryptedUserStoragePackage(
                chat: currentChat,
                userMessage: userMessage,
                assistantTaskId: assistantMessageId,
                metadata: metadata,
                wsManager: wsManager,
                chatStore: chatStore
            )
            chat = updatedChat
        } catch {
            self.error = error.localizedDescription
        }
    }

    private func persistCompletedAssistantMessage(_ message: Message, userMessageId: String?) async {
        do {
            let persisted = try await sendPipeline.persistCompletedAssistantMessage(
                message,
                userMessageId: userMessageId,
                wsManager: wsManager,
                chatStore: chatStore
            )
            appendOrReplaceLocalMessage(persisted)
        } catch {
            self.error = error.localizedDescription
        }
    }

    private func appendOrReplaceLocalMessage(_ message: Message) {
        if let index = allMessages.firstIndex(where: { $0.id == message.id }) {
            allMessages[index] = message
        } else {
            allMessages.append(message)
        }
        allMessages.sort { $0.createdAt < $1.createdAt }

        if let index = messages.firstIndex(where: { $0.id == message.id }) {
            messages[index] = message
        } else {
            messages.append(message)
        }
        messages.sort { $0.createdAt < $1.createdAt }
        chatStore?.appendMessage(message, to: message.chatId)
    }

    private func appendOrReplaceTransientMessage(_ message: Message) {
        if let index = allMessages.firstIndex(where: { $0.id == message.id }) {
            allMessages[index] = message
        } else {
            allMessages.append(message)
        }
        allMessages.sort { $0.createdAt < $1.createdAt }

        if let index = messages.firstIndex(where: { $0.id == message.id }) {
            messages[index] = message
        } else {
            messages.append(message)
        }
        messages.sort { $0.createdAt < $1.createdAt }
    }

    private func createdAtForAssistantMessage(_ messageId: String) -> String {
        if let createdAt = assistantMessageCreatedAtById[messageId] {
            return createdAt
        }
        let createdAt = ISO8601DateFormatter().string(from: Date())
        assistantMessageCreatedAtById[messageId] = createdAt
        return createdAt
    }

    private func streamingDisplayContent(for messageId: String, incomingContent: String, isFinal: Bool) -> String {
        guard !isFinal else { return incomingContent }
        let existingContent = messages.first(where: { $0.id == messageId })?.content ?? ""
        guard !incomingContent.isEmpty else { return existingContent }
        guard incomingContent.count >= existingContent.count else { return existingContent }
        return incomingContent
    }

    // MARK: - Embed update subscription

    /// Listen for WebSocket embed updates and reload embeds for this chat.
    private func subscribeToEmbedUpdates(chatId: String) {
        if let observer = embedRefreshObserver {
            NotificationCenter.default.removeObserver(observer)
            embedRefreshObserver = nil
        }
        embedRefreshObserver = NotificationCenter.default.addObserver(
            forName: .embedRefreshNeeded, object: nil, queue: .main
        ) { [weak self] _ in
            Task { @MainActor [weak self] in
                guard let self, self.chat?.id == chatId else { return }
                await self.loadEmbeds(for: self.messages.map(\.id))
            }
        }
    }

    deinit {
        if let observer = embedRefreshObserver {
            NotificationCenter.default.removeObserver(observer)
        }
    }

    // MARK: - Message actions

    func deleteMessage(_ messageId: String) async {
        guard let chatId = chat?.id else { return }
        do {
            let _: Data = try await api.request(
                .delete, path: "/v1/chats/\(chatId)/messages/\(messageId)"
            )
            messages.removeAll { $0.id == messageId }
        } catch {
            self.error = error.localizedDescription
        }
    }

    /// Fork a conversation from a specific message. Returns the new chat ID
    /// so the caller can navigate to it.
    @Published var forkedChatId: String?

    func forkFromMessage(_ messageId: String) async {
        guard let chatId = chat?.id else { return }
        do {
            let response: [String: AnyCodable] = try await api.request(
                .post, path: "/v1/chats/\(chatId)/fork",
                body: ["from_message_id": messageId]
            )
            if let newChatId = response["chat_id"]?.value as? String {
                ToastManager.shared.show("Conversation forked", type: .success)
                forkedChatId = newChatId
            }
        } catch {
            self.error = error.localizedDescription
        }
    }

    // MARK: - Embed loading

    func loadEmbeds(for messageIds: [String]) async {
        guard let chatId = chat?.id else { return }
        let requestedMessageIds = Set(messageIds)
        let visibleReferencedEmbedIds = Set(messages
            .filter { requestedMessageIds.contains($0.id) }
            .flatMap { $0.embedRefs?.map(\.id) ?? [] })
        let referencedEmbedIds = visibleReferencedEmbedIds.union(
            allMessages
                .filter { requestedMessageIds.contains($0.id) }
                .flatMap { $0.embedRefs?.map(\.id) ?? [] }
        )
        guard !referencedEmbedIds.isEmpty else { return }
        let loadedEmbedIds = Set(embedRecords.keys)
        let referencedRecords = referencedEmbedIds.compactMap { embedRecords[$0] }
        let referencedChildIds = childIdsReachable(from: referencedEmbedIds)
        let requiredEmbedIds = referencedEmbedIds.union(referencedChildIds)
        let hasUnresolvedCompositeParent = referencedRecords.contains { record in
            record.isAppSkillUse &&
                record.childEmbedIds.isEmpty &&
                !embedRecords.values.contains { $0.parentEmbedId == record.id }
        }
        let hasEncryptedUndecryptedRecord = referencedRecords.contains { record in
            record.rawData == nil && (record.encryptedContent != nil || record.encryptedType != nil)
        }
        NativeSyncPerfLog.info(
            "phase=loadEmbedsStart chat=\(chatId.prefix(8)) requestedMessages=\(requestedMessageIds.count) referenced=\(referencedEmbedIds.count) children=\(referencedChildIds.count) loaded=\(loadedEmbedIds.count) unresolvedComposite=\(hasUnresolvedCompositeParent) encryptedUndecrypted=\(hasEncryptedUndecryptedRecord)"
        )
        if !hasUnresolvedCompositeParent,
           !hasEncryptedUndecryptedRecord,
           !requiredEmbedIds.isEmpty,
           requiredEmbedIds.isSubset(of: loadedEmbedIds) {
            print("[ChatViewModel][embeds] chat=\(chatId.prefix(8)) skip fetch; required already loaded=\(requiredEmbedIds.count)")
            return
        }
        do {
            let data: Data = try await api.request(
                .get, path: "/v1/chats/\(chatId)/embeds"
            )
            let response = try decodeChatEmbedsResponse(data)
            guard chat?.id == chatId else { return }
            EmbedKeyManager.shared.store(response.embedKeys, source: "chatEmbeds:\(chatId.prefix(8))")
            let relatedEmbeds = relatedEmbeds(referencedIds: referencedEmbedIds, from: response.embeds)
            let decrypted = await decryptEmbeds(relatedEmbeds, chatId: chatId, existingRecords: embedRecords)
            for embed in decrypted {
                embedRecords[embed.id] = embed
            }
            EmbedMediaOfflineCache.prefetchEmbeds(decrypted)
            let childLinked = decrypted.filter { $0.parentEmbedId != nil || !$0.childEmbedIds.isEmpty }.count
            let rawCount = decrypted.filter { $0.rawData != nil }.count
            NativeSyncPerfLog.info(
                "phase=loadEmbedsFetched chat=\(chatId.prefix(8)) fetched=\(response.embeds.count) related=\(relatedEmbeds.count) keys=\(response.embedKeys.count) linked=\(childLinked) decryptedRaw=\(rawCount) totalRecords=\(embedRecords.count)"
            )
        } catch {
            print("[Chat] Failed to load embeds: \(error)")
        }
    }

    private func decodeChatEmbedsResponse(_ data: Data) throws -> ChatEmbedsResponse {
        let decoder = JSONDecoder()
        decoder.keyDecodingStrategy = .convertFromSnakeCase
        if let object = try? decoder.decode(ChatEmbedsResponse.self, from: data) {
            return object
        }
        let embeds = try decoder.decode([EmbedRecord].self, from: data)
        return ChatEmbedsResponse(embeds: embeds, embedKeys: [])
    }

    func embeds(for message: Message) -> [EmbedRecord] {
        message.embedRefs?.compactMap { ref in
            embedRecords[ref.id]
        } ?? []
    }

    private func childIdsReachable(from parentIds: Set<String>) -> Set<String> {
        var result = Set<String>()
        var pending = Array(parentIds)
        var visited = Set<String>()

        while let id = pending.popLast() {
            guard visited.insert(id).inserted, let record = embedRecords[id] else { continue }
            for childId in record.childEmbedIds where result.insert(childId).inserted {
                pending.append(childId)
            }
            for child in embedRecords.values where child.parentEmbedId == id && result.insert(child.id).inserted {
                pending.append(child.id)
            }
        }

        return result
    }

    private func visibleWindow(from rawMessages: [Message], anchorMessageId: String? = nil) -> [Message] {
        guard rawMessages.count > messagesPageSize else {
            visibleWindowStartIndex = 0
            return rawMessages
        }

        if let anchorMessageId,
           let anchorIndex = rawMessages.firstIndex(where: { $0.id == anchorMessageId }) {
            let preferredStart = max(0, anchorIndex - 8)
            let maxStart = rawMessages.count - messagesPageSize
            let start = min(preferredStart, maxStart)
            let end = min(rawMessages.count, start + messagesPageSize)
            visibleWindowStartIndex = start
            return Array(rawMessages[start..<end])
        }

        visibleWindowStartIndex = rawMessages.count - messagesPageSize
        return Array(rawMessages.suffix(messagesPageSize))
    }

    private func relatedEmbeds(referencedIds: Set<String>, from embeds: [EmbedRecord]) -> [EmbedRecord] {
        guard !referencedIds.isEmpty, !embeds.isEmpty else { return [] }
        let recordsById = EmbedRecord.dictionaryById(embeds, context: "chatViewModel.relatedEmbeds")
        var included = referencedIds
        for id in referencedIds {
            if let parentId = recordsById[id]?.parentEmbedId {
                included.insert(parentId)
            }
        }
        return embeds.filter { included.contains($0.id) }
    }

    private func extractFollowUpSuggestions(from messages: [Message]) -> [String] {
        guard let content = messages.last(where: { $0.role == .assistant })?.content else { return [] }
        let lines = content.components(separatedBy: .newlines)
        guard let start = lines.lastIndex(where: { $0.trimmingCharacters(in: .whitespacesAndNewlines).localizedCaseInsensitiveContains("next steps") }) else {
            return []
        }
        return lines[(start + 1)...]
            .compactMap { line -> String? in
                let trimmed = line.trimmingCharacters(in: .whitespacesAndNewlines)
                    .trimmingCharacters(in: CharacterSet(charactersIn: "-*• "))
                    .trimmingCharacters(in: .whitespacesAndNewlines)
                let cleaned = cleanFollowUpSuggestion(trimmed)
                return cleaned.isEmpty ? nil : cleaned
            }
            .prefix(6)
            .map { String($0) }
    }

    private func cleanFollowUpSuggestion(_ suggestion: String) -> String {
        var cleaned = suggestion
        cleaned = cleaned.replacingOccurrences(
            of: #"\[\[[^\]|]+(?:\|([^\]]+))?\]\]"#,
            with: "$1",
            options: .regularExpression
        )
        cleaned = cleaned.replacingOccurrences(
            of: #"\[([^\]]+)\]\([^)]+\)"#,
            with: "$1",
            options: .regularExpression
        )
        return cleaned.trimmingCharacters(in: CharacterSet(charactersIn: ". \n\t"))
    }

    func childEmbeds(for embed: EmbedRecord) -> [EmbedRecord] {
        embed.childEmbedIds.compactMap { embedRecords[$0] }
    }

    func isStreamingMessage(_ messageId: String) -> Bool {
        streamingMessageId == messageId && isStreaming
    }

    // MARK: - Attachment upload

    @discardableResult
    func uploadAttachment(data: Data, filename: String) async -> UploadFileResponse? {
        guard let chatId = chat?.id else { return nil }
        let uploadId = UUID().uuidString
        PendingUploadStore.shared.startUpload(id: uploadId, chatId: chatId, filename: filename)

        guard let upload = await uploadData(
            data,
            filename: filename,
            uploadId: uploadId,
            contentType: "application/octet-stream",
            markFinishedOnSuccess: false
        ) else { return nil }
        registerPendingComposerEmbed(upload, localData: data, transcript: nil, duration: nil)
        PendingUploadStore.shared.markFinished(id: uploadId)
        return upload
    }

    func uploadRecording(url: URL, duration: TimeInterval) async -> String? {
        guard let chatId = chat?.id,
              let data = try? Data(contentsOf: url) else { return nil }
        let uploadId = UUID().uuidString
        let filename = url.lastPathComponent
        PendingUploadStore.shared.startUpload(id: uploadId, chatId: chatId, filename: filename)

        guard let upload = await uploadData(
            data,
            filename: filename,
            uploadId: uploadId,
            contentType: "audio/mp4",
            markFinishedOnSuccess: false
        ) else {
            return nil
        }

        PendingUploadStore.shared.updateStatus(id: uploadId, status: .transcribing)
        let s3Key = upload.files["original"]?.s3Key ?? upload.files.values.first?.s3Key
        guard let s3Key else {
            PendingUploadStore.shared.markError(id: uploadId, message: AppStrings.uploadProgressError)
            return nil
        }

        let embedId = UUID().uuidString
        let request: [String: Any] = [
            "requests": [[
                "id": embedId,
                "embed_id": upload.embedId,
                "s3_key": s3Key,
                "s3_base_url": upload.s3BaseUrl,
                "aes_key": upload.aesKey,
                "aes_nonce": upload.aesNonce,
                "vault_wrapped_aes_key": upload.vaultWrappedAesKey,
                "filename": filename,
                "mime_type": "audio/mp4",
                "chat_id": chatId
            ]]
        ]

        do {
            let response: TranscribeSkillResponse = try await APIClient.shared.request(
                .post,
                path: "apps/audio/skills/transcribe",
                body: request
            )
            let transcript = response.data.results.first?.results.first?.transcript
            registerPendingComposerEmbed(upload, localData: data, transcript: transcript, duration: duration)
            PendingUploadStore.shared.markFinished(id: uploadId)
            return transcript
        } catch {
            print("[Chat] Recording transcription error: \(error)")
            PendingUploadStore.shared.markError(id: uploadId, message: AppStrings.uploadProgressError)
            return nil
        }
    }

    private func uploadData(
        _ data: Data,
        filename: String,
        uploadId: String,
        contentType: String,
        markFinishedOnSuccess: Bool
    ) async -> UploadFileResponse? {
        guard let chatId = chat?.id else { return nil }

        let boundary = UUID().uuidString
        var body = Data()

        body.append("--\(boundary)\r\n".data(using: .utf8)!)
        body.append("Content-Disposition: form-data; name=\"file\"; filename=\"\(filename)\"\r\n".data(using: .utf8)!)
        body.append("Content-Type: \(contentType)\r\n\r\n".data(using: .utf8)!)
        body.append(data)
        body.append("\r\n--\(boundary)\r\n".data(using: .utf8)!)
        body.append("Content-Disposition: form-data; name=\"chat_id\"\r\n\r\n".data(using: .utf8)!)
        body.append(chatId.data(using: .utf8)!)
        body.append("\r\n--\(boundary)--\r\n".data(using: .utf8)!)

        do {
            let uploadURL = await APIClient.shared.uploadBaseURL
                .appendingPathComponent("v1/upload/file")
            var request = URLRequest(url: uploadURL)
            request.httpMethod = "POST"
            request.setValue("multipart/form-data; boundary=\(boundary)", forHTTPHeaderField: "Content-Type")
            request.httpBody = body

            let (responseData, response) = try await URLSession.shared.data(for: request)
            guard let httpResponse = response as? HTTPURLResponse,
                  (200...299).contains(httpResponse.statusCode) else {
                print("[Chat] Upload failed")
                PendingUploadStore.shared.markError(id: uploadId, message: AppStrings.error)
                return nil
            }
            let decoder = JSONDecoder()
            decoder.keyDecodingStrategy = .convertFromSnakeCase
            let upload = try decoder.decode(UploadFileResponse.self, from: responseData)
            PendingUploadStore.shared.updateProgress(id: uploadId, progress: 1.0)
            if markFinishedOnSuccess {
                PendingUploadStore.shared.markFinished(id: uploadId)
            }
            return upload
        } catch {
            print("[Chat] Upload error: \(error)")
            PendingUploadStore.shared.markError(id: uploadId, message: AppStrings.error)
            return nil
        }
    }

    func uploadFile(url: URL) async {
        guard let data = try? Data(contentsOf: url) else { return }
        await uploadAttachment(data: data, filename: url.lastPathComponent)
    }

    func removePendingComposerEmbed(id: String) {
        pendingComposerEmbeds.removeAll { $0.id == id }
    }

    #if DEBUG
    func seedUITestPendingComposerEmbed() {
        guard pendingComposerEmbeds.isEmpty else { return }
        let upload = UploadFileResponse(
            embedId: "ui-test-pending-image",
            filename: "ui-test-image.png",
            contentType: "image/png",
            contentHash: nil,
            files: [
                "original": UploadedFileVariant(
                    s3Key: "ui-test-image.png",
                    sizeBytes: 128,
                    width: 32,
                    height: 32,
                    format: "png"
                )
            ],
            s3BaseUrl: "https://example.invalid/ui-test",
            aesKey: "ui-test-aes-key",
            aesNonce: "ui-test-aes-nonce",
            vaultWrappedAesKey: "ui-test-wrapped-key",
            pageCount: nil,
            deduplicated: true
        )
        registerPendingComposerEmbed(upload, localData: Data(repeating: 0, count: 128), transcript: nil, duration: nil)
    }
    #endif

    private func registerPendingComposerEmbed(
        _ upload: UploadFileResponse,
        localData: Data?,
        transcript: String?,
        duration: TimeInterval?
    ) {
        let embed = ComposerPendingEmbed.from(
            upload: upload,
            localData: localData,
            transcript: transcript,
            duration: duration
        )
        pendingComposerEmbeds.removeAll { $0.id == embed.id }
        pendingComposerEmbeds.append(embed)
        embedRecords[embed.record.id] = embed.record
        if let chatId = chat?.id {
            chatStore?.upsertEmbeds([embed.record], for: chatId)
        }
    }

    private func contentWithComposerEmbedReferences(_ content: String, embeds: [ComposerPendingEmbed]) -> String {
        guard !embeds.isEmpty else { return content }
        let references = embeds.map(\.markdownReference).joined(separator: "\n")
        let trimmed = content.trimmingCharacters(in: .whitespacesAndNewlines)
        return trimmed.isEmpty ? references : "\(trimmed)\n\n\(references)"
    }
}

struct UploadFileResponse: Decodable {
    let embedId: String
    let filename: String
    let contentType: String
    let contentHash: String?
    let files: [String: UploadedFileVariant]
    let s3BaseUrl: String
    let aesKey: String
    let aesNonce: String
    let vaultWrappedAesKey: String
    let pageCount: Int?
    let deduplicated: Bool?
}

struct UploadedFileVariant: Decodable {
    let s3Key: String
    let sizeBytes: Int?
    let width: Int?
    let height: Int?
    let format: String?
}

struct ComposerPendingEmbed: Identifiable {
    let id: String
    let type: String
    let referenceType: String
    let status: String
    let content: String?
    let textPreview: String?
    let record: EmbedRecord
    let localData: Data?
    let filename: String
    let size: Int

    var markdownReference: String {
        "```json\n{\"type\": \"\(referenceType)\", \"embed_id\": \"\(id)\"}\n```"
    }

    var serverPayload: [String: Any]? {
        guard let content else { return nil }
        var payload: [String: Any] = [
            "embed_id": id,
            "type": type,
            "status": status,
            "content": content,
            "createdAt": Int(Date().timeIntervalSince1970),
            "updatedAt": Int(Date().timeIntervalSince1970)
        ]
        if let textPreview { payload["text_preview"] = textPreview }
        return payload
    }

    var canPersistDirectly: Bool {
        content != nil
    }

    #if DEBUG
    static var uiTestFixture: ComposerPendingEmbed {
        from(
            upload: UploadFileResponse(
                embedId: "ui-test-pending-image",
                filename: "ui-test-image.png",
                contentType: "image/png",
                contentHash: nil,
                files: [
                    "original": UploadedFileVariant(
                        s3Key: "ui-test-image.png",
                        sizeBytes: 128,
                        width: 32,
                        height: 32,
                        format: "png"
                    )
                ],
                s3BaseUrl: "https://example.invalid/ui-test",
                aesKey: "ui-test-aes-key",
                aesNonce: "ui-test-aes-nonce",
                vaultWrappedAesKey: "ui-test-wrapped-key",
                pageCount: nil,
                deduplicated: true
            ),
            localData: Data(repeating: 0, count: 128),
            transcript: nil,
            duration: nil
        )
    }
    #endif

    static func from(
        upload: UploadFileResponse,
        localData: Data?,
        transcript: String?,
        duration: TimeInterval?
    ) -> ComposerPendingEmbed {
        let classification = ComposerUploadClassification(upload: upload)
        let contentObject = classification.contentObject(upload: upload, transcript: transcript, duration: duration)
        let content = classification.shouldSendContent ? jsonString(contentObject) : nil
        let preview = transcript ?? upload.filename
        let record = EmbedRecord(
            id: upload.embedId,
            type: classification.embedType,
            status: EmbedStatus(rawValue: classification.status) ?? .finished,
            data: .raw(contentObject.mapValues { AnyCodable($0) }),
            parentEmbedId: nil,
            appId: classification.appId,
            skillId: classification.skillId,
            embedIds: nil,
            createdAt: String(Int(Date().timeIntervalSince1970))
        )
        return ComposerPendingEmbed(
            id: upload.embedId,
            type: classification.embedType,
            referenceType: classification.referenceType,
            status: classification.status,
            content: content,
            textPreview: preview,
            record: record,
            localData: localData,
            filename: upload.filename,
            size: localData?.count ?? upload.files.values.compactMap(\.sizeBytes).max() ?? 0
        )
    }

    private static func jsonString(_ object: [String: Any]) -> String {
        guard JSONSerialization.isValidJSONObject(object),
              let data = try? JSONSerialization.data(withJSONObject: object, options: [.sortedKeys]),
              let string = String(data: data, encoding: .utf8) else {
            return "{}"
        }
        return string
    }
}

private struct ComposerUploadClassification {
    let embedType: String
    let referenceType: String
    let status: String
    let appId: String
    let skillId: String?
    let shouldSendContent: Bool

    init(upload: UploadFileResponse) {
        let mime = upload.contentType.lowercased()
        let ext = (upload.filename as NSString).pathExtension.lowercased()
        if mime.hasPrefix("audio/") || ["m4a", "mp3", "wav", "webm", "mp4"].contains(ext) {
            embedType = "audio-recording"
            referenceType = "audio-recording"
            status = "finished"
            appId = "audio"
            skillId = "transcribe"
            shouldSendContent = true
        } else if mime.hasPrefix("image/") || ["jpg", "jpeg", "png", "gif", "heic", "webp"].contains(ext) {
            embedType = "images-image"
            referenceType = "image"
            status = "finished"
            appId = "images"
            skillId = "upload"
            shouldSendContent = true
        } else if mime == "application/pdf" || ext == "pdf" {
            embedType = "pdf"
            referenceType = "pdf"
            status = upload.deduplicated == true ? "finished" : "processing"
            appId = "pdf"
            skillId = nil
            shouldSendContent = upload.deduplicated == true
        } else {
            embedType = "docs-doc"
            referenceType = "file"
            status = "finished"
            appId = "docs"
            skillId = nil
            shouldSendContent = true
        }
    }

    func contentObject(upload: UploadFileResponse, transcript: String?, duration: TimeInterval?) -> [String: Any] {
        var object: [String: Any] = [
            "app_id": appId,
            "type": referenceType,
            "status": status,
            "filename": upload.filename,
            "s3_base_url": upload.s3BaseUrl,
            "files": upload.files.mapValues { variant in
                var item: [String: Any] = ["s3_key": variant.s3Key]
                if let size = variant.sizeBytes { item["size_bytes"] = size }
                if let width = variant.width { item["width"] = width }
                if let height = variant.height { item["height"] = height }
                if let format = variant.format { item["format"] = format }
                return item
            },
            "aes_key": upload.aesKey,
            "aes_nonce": upload.aesNonce,
            "vault_wrapped_aes_key": upload.vaultWrappedAesKey
        ]
        if let skillId { object["skill_id"] = skillId }
        if let contentHash = upload.contentHash { object["content_hash"] = contentHash }
        if let pageCount = upload.pageCount { object["page_count"] = pageCount }
        if let transcript { object["transcript"] = transcript }
        if let duration { object["duration"] = duration }
        return object
    }
}

private struct TranscribeSkillResponse: Decodable {
    struct ResponseData: Decodable {
        struct ResultGroup: Decodable {
            struct Result: Decodable {
                let transcript: String?
            }
            let results: [Result]
        }
        let results: [ResultGroup]
    }
    let data: ResponseData
}

private struct ChatEmbedsResponse: Decodable {
    let embeds: [EmbedRecord]
    let embedKeys: [EmbedKeyRecord]

    init(embeds: [EmbedRecord], embedKeys: [EmbedKeyRecord]) {
        self.embeds = embeds
        self.embedKeys = embedKeys
    }

    private enum CodingKeys: String, CodingKey {
        case embeds
        case embedKeys
    }
}

@MainActor
fileprivate enum PublicChatContent {
    struct PublicChat {
        let chat: Chat
        let messages: [Message]
        let followUpSuggestions: [String]
        let embedRecords: [String: EmbedRecord]
    }

    static func chat(for id: String) -> PublicChat? {
        let createdAt = "2026-04-20T12:00:00Z"

        switch id {
        case "demo-for-everyone":
            return publicChat(
                id: id,
                title: AppStrings.demoForEveryoneTitle,
                appId: "ai",
                createdAt: createdAt,
                messages: [
                    assistant(id: "for-everyone-1", chatId: id, contentKey: "demo_chats.for_everyone.message", createdAt: createdAt, appId: "ai")
                ],
                followUpKeys: demoFollowUpKeys("for_everyone")
            )
        case "demo-for-developers":
            return publicChat(
                id: id,
                title: AppStrings.demoForDevelopersTitle,
                appId: "code",
                createdAt: createdAt,
                messages: [
                    assistant(id: "for-developers-1", chatId: id, contentKey: "demo_chats.for_developers.message", createdAt: createdAt, appId: "code")
                ],
                followUpKeys: demoFollowUpKeys("for_developers")
            )
        case "demo-who-develops-openmates":
            return publicChat(
                id: id,
                title: AppStrings.demoWhoDevTitle,
                appId: "ai",
                createdAt: createdAt,
                messages: [
                    assistant(id: "who-develops-openmates-1", chatId: id, contentKey: "demo_chats.who_develops_openmates.message", createdAt: createdAt, appId: "ai")
                ],
                followUpKeys: demoFollowUpKeys("who_develops_openmates")
            )
        case "announcements-introducing-openmates-v09":
            return publicChat(
                id: id,
                title: AppStrings.demoAnnouncementsV09Title,
                appId: "ai",
                createdAt: createdAt,
                messages: [
                    assistant(id: "announcements-introducing-openmates-v09-1", chatId: id, contentKey: "demo_chats.announcements_introducing_openmates_v09.message", createdAt: createdAt, appId: "ai")
                ],
                followUpKeys: []
            )
        case "legal-privacy":
            return legalChat(
                id: id,
                title: AppStrings.legalPrivacyTitle,
                content: legalPrivacyContent(),
                followUpKeys: (1...6).map { "legal.privacy.follow_up_\($0)" },
                createdAt: "2026-04-16T18:00:00Z"
            )
        case "legal-terms":
            return legalChat(
                id: id,
                title: AppStrings.legalTermsTitle,
                content: legalTermsContent(),
                followUpKeys: (1...6).map { "legal.terms.follow_up_\($0)" },
                createdAt: "2026-01-28T00:00:00Z"
            )
        case "legal-imprint":
            return legalChat(
                id: id,
                title: AppStrings.legalImprintTitle,
                content: legalImprintContent(),
                followUpKeys: (1...5).map { "legal.imprint.follow_up_\($0)" },
                createdAt: "2026-01-28T00:00:00Z"
            )
        default:
            return exampleChat(for: id, createdAt: createdAt)
        }
    }

    private static func exampleChat(for id: String, createdAt: String) -> PublicChat? {
        let specs: [String: (title: String, appId: String, messages: [MessageSpec], followUps: ClosedRange<Int>)] = [
            "example-gigantic-airplanes": (
                AppStrings.exampleGiganticAirplanesTitle,
                "general_knowledge",
                [
                    .user("example-gigantic-airplanes-user-1", "example_chats.gigantic_airplanes.user_message_1"),
                    .assistant("example-gigantic-airplanes-assistant-1", "example_chats.gigantic_airplanes.assistant_message_1"),
                    .user("example-gigantic-airplanes-user-2", "example_chats.gigantic_airplanes.user_message_2"),
                    .assistant("example-gigantic-airplanes-assistant-2", "example_chats.gigantic_airplanes.assistant_message_2")
                ],
                1...6
            ),
            "example-artemis-ii-mission": (
                AppStrings.exampleArtemisMissionTitle,
                "science",
                [
                    .user("example-artemis-ii-mission-user-1", "example_chats.artemis_ii_mission.user_message_1"),
                    .assistant("example-artemis-ii-mission-assistant-2", "example_chats.artemis_ii_mission.assistant_message_2")
                ],
                1...4
            ),
            "example-beautiful-single-page-html": (
                AppStrings.exampleBeautifulHtmlTitle,
                "software_development",
                [
                    .user("example-beautiful-single-page-html-user-1", "example_chats.beautiful_single_page_html.user_message_1"),
                    .assistant("example-beautiful-single-page-html-assistant-2", "example_chats.beautiful_single_page_html.assistant_message_2")
                ],
                1...6
            ),
            "example-eu-chat-control-law": (
                AppStrings.exampleEuChatControlTitle,
                "legal_law",
                [
                    .user("example-eu-chat-control-law-user-1", "example_chats.eu_chat_control_law.user_message_1"),
                    .assistant("example-eu-chat-control-law-assistant-1", "example_chats.eu_chat_control_law.assistant_message_1")
                ],
                1...6
            ),
            "example-flights-berlin-bangkok": (
                AppStrings.exampleFlightsBerlinBangkokTitle,
                "general_knowledge",
                [
                    .user("example-flights-berlin-bangkok-user-1", "example_chats.flights_berlin_bangkok.user_message_1"),
                    .assistant("example-flights-berlin-bangkok-assistant-1", "example_chats.flights_berlin_bangkok.assistant_message_1")
                ],
                1...6
            ),
            "example-creativity-drawing-meetups-berlin": (
                AppStrings.exampleCreativityDrawingTitle,
                "general_knowledge",
                [
                    .user("example-creativity-drawing-meetups-berlin-user-1", "example_chats.creativity_drawing_meetups_berlin.user_message_1"),
                    .assistant("example-creativity-drawing-meetups-berlin-assistant-1", "example_chats.creativity_drawing_meetups_berlin.assistant_message_1")
                ],
                1...6
            )
        ]

        guard let spec = specs[id] else { return nil }
        let messages = spec.messages.map { messageSpec in
            message(
                id: messageSpec.id,
                chatId: id,
                role: messageSpec.role,
                content: text(messageSpec.key),
                createdAt: createdAt,
                appId: messageSpec.role == .assistant ? spec.appId : nil
            )
        }
        return publicChat(
            id: id,
            title: spec.title,
            appId: spec.appId,
            createdAt: createdAt,
            messages: messages,
            followUpKeys: spec.followUps.map { "example_chats.\(exampleKey(for: id)).follow_up_\($0)" }
        )
    }

    private struct MessageSpec {
        let id: String
        let role: MessageRole
        let key: String

        static func user(_ id: String, _ key: String) -> MessageSpec {
            MessageSpec(id: id, role: .user, key: key)
        }

        static func assistant(_ id: String, _ key: String) -> MessageSpec {
            MessageSpec(id: id, role: .assistant, key: key)
        }
    }

    private static func publicChat(
        id: String,
        title: String,
        appId: String,
        createdAt: String,
        messages: [Message],
        followUpKeys: [String]
    ) -> PublicChat {
        let embedded = attachEmbeds(to: messages)
        let demoRecords = demoEmbedRecords(for: id)
        let embedRecords = embedded.records.merging(demoRecords) { _, demo in demo }
        let messagesWithDemoRefs = attachDemoAppSkillRefs(
            to: embedded.messages,
            demoRecords: demoRecords
        )

        return PublicChat(
            chat: Chat(
                id: id,
                title: title,
                lastMessageAt: createdAt,
                createdAt: createdAt,
                updatedAt: createdAt,
                isArchived: false,
                isPinned: id.hasPrefix("demo-"),
                appId: appId,
                encryptedTitle: nil,
                encryptedChatKey: nil
            ),
            messages: messagesWithDemoRefs,
            followUpSuggestions: followUpKeys.map(text).filter { !$0.isEmpty && !$0.contains(".follow_up_") },
            embedRecords: embedRecords
        )
    }

    private static func legalChat(
        id: String,
        title: String,
        content: String,
        followUpKeys: [String],
        createdAt: String
    ) -> PublicChat {
        publicChat(
            id: id,
            title: title,
            appId: "ai",
            createdAt: createdAt,
            messages: [
                message(id: "\(id)-message-1", chatId: id, role: .assistant, content: content, createdAt: createdAt, appId: "ai")
            ],
            followUpKeys: followUpKeys
        )
    }

    private static func assistant(id: String, chatId: String, contentKey: String, createdAt: String, appId: String) -> Message {
        message(id: id, chatId: chatId, role: .assistant, content: text(contentKey), createdAt: createdAt, appId: appId)
    }

    private static func message(
        id: String,
        chatId: String,
        role: MessageRole,
        content: String,
        createdAt: String,
        appId: String?,
        embedRefs: [EmbedRef]? = nil
    ) -> Message {
        Message(
            id: id,
            chatId: chatId,
            role: role,
            content: sanitize(content),
            encryptedContent: nil,
            createdAt: createdAt,
            updatedAt: nil,
            appId: appId,
            isStreaming: false,
            embedRefs: embedRefs,
            modelName: role == .assistant ? "Gemini 3 Flash" : nil
        )
    }

    static func attachEmbeds(to messages: [Message]) -> (messages: [Message], records: [String: EmbedRecord]) {
        var records: [String: EmbedRecord] = [:]
        let updatedMessages = messages.map { original in
            let extracted = extractEmbeds(from: original.content ?? "", fallbackAppId: original.appId)
            for record in extracted.records {
                records[record.id] = record
            }

            return Message(
                id: original.id,
                chatId: original.chatId,
                role: original.role,
                content: extracted.content,
                encryptedContent: original.encryptedContent,
                createdAt: original.createdAt,
                updatedAt: original.updatedAt,
                appId: original.appId,
                isStreaming: original.isStreaming,
                embedRefs: extracted.refs.isEmpty ? nil : extracted.refs,
                modelName: original.modelName
            )
        }
        return (updatedMessages, records)
    }

    private static func attachDemoAppSkillRefs(
        to messages: [Message],
        demoRecords: [String: EmbedRecord]
    ) -> [Message] {
        let parentRecords = EmbedRecord.deduplicatedById(
            Array(demoRecords.values),
            context: "publicChat.demoAppSkillRefs"
        )
            .filter(\.isAppSkillUse)
        guard !parentRecords.isEmpty else { return messages }

        var assignedParentIds = Set<String>()
        var updatedMessages = messages.map { message in
            guard message.role == .assistant else { return message }
            let existingRefs = message.embedRefs ?? []
            let existingIds = Set(existingRefs.map(\.id))
            let matchingParents = parentRecords.filter { parent in
                guard !existingIds.contains(parent.id) else { return false }
                let childIds = Set(parent.childEmbedIds)
                return !childIds.isEmpty && !childIds.isDisjoint(with: existingIds)
            }
            guard !matchingParents.isEmpty else { return message }
            assignedParentIds.formUnion(matchingParents.map(\.id))
            return messageWithEmbedRefs(
                message,
                refs: matchingParents.map(embedRef) + existingRefs
            )
        }

        let unassignedParents = parentRecords.filter { !assignedParentIds.contains($0.id) }
        guard !unassignedParents.isEmpty,
              let lastAssistantIndex = updatedMessages.lastIndex(where: { $0.role == .assistant })
        else { return updatedMessages }

        let target = updatedMessages[lastAssistantIndex]
        let existingRefs = target.embedRefs ?? []
        let existingIds = Set(existingRefs.map(\.id))
        let newRefs = unassignedParents
            .filter { !existingIds.contains($0.id) }
            .map(embedRef)
        guard !newRefs.isEmpty else { return updatedMessages }
        updatedMessages[lastAssistantIndex] = messageWithEmbedRefs(
            target,
            refs: newRefs + existingRefs
        )
        return updatedMessages
    }

    private static func messageWithEmbedRefs(_ message: Message, refs: [EmbedRef]) -> Message {
        Message(
            id: message.id,
            chatId: message.chatId,
            role: message.role,
            content: message.content,
            encryptedContent: message.encryptedContent,
            createdAt: message.createdAt,
            updatedAt: message.updatedAt,
            appId: message.appId,
            isStreaming: message.isStreaming,
            embedRefs: refs,
            modelName: message.modelName
        )
    }

    private static func extractEmbeds(from content: String, fallbackAppId: String?) -> (content: String, refs: [EmbedRef], records: [EmbedRecord]) {
        var cleaned = content
        var refs: [EmbedRef] = []
        var records: [EmbedRecord] = []

        let jsonPattern = #"```(json_embed|json)\s*([\s\S]*?)\s*```"#
        for match in regexMatches(jsonPattern, in: content).reversed() {
            guard let fenceRange = Range(match.range(at: 1), in: content),
                  let jsonRange = Range(match.range(at: 2), in: content),
                  let fullRange = Range(match.range(at: 0), in: cleaned) else { continue }

            let fence = String(content[fenceRange])
            let json = String(content[jsonRange])
            guard let data = json.data(using: .utf8),
                  let object = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
                  let type = object["type"] as? String else { continue }

            let record: EmbedRecord
            if fence == "json_embed", type == "website", let url = object["url"] as? String {
                record = embedRecord(
                    id: stableEmbedId(prefix: "web", value: url),
                    type: "web-website",
                    appId: "web",
                    skillId: nil,
                    data: object,
                    parentEmbedId: object["parent_embed_id"] as? String,
                    embedIds: nil
                )
            } else if type == "app_skill_use", let embedId = object["embed_id"] as? String {
                let appId = object["app_id"] as? String ?? fallbackAppId ?? "web"
                let skillId = object["skill_id"] as? String ?? "search"
                let embedType = "app:\(appId):\(skillId)"
                record = embedRecord(
                    id: embedId,
                    type: embedType,
                    appId: appId,
                    skillId: skillId,
                    data: object,
                    parentEmbedId: object["parent_embed_id"] as? String,
                    embedIds: embedIds(from: object["embed_ids"] ?? object["child_embed_ids"])
                )
            } else if type == "code", let embedId = object["embed_id"] as? String {
                var codeData = object
                if codeData["language"] == nil { codeData["language"] = "html" }
                if codeData["filename"] == nil { codeData["filename"] = "index.html" }
                record = embedRecord(
                    id: embedId,
                    type: "code-code",
                    appId: "code",
                    skillId: nil,
                    data: codeData,
                    parentEmbedId: object["parent_embed_id"] as? String,
                    embedIds: nil
                )
            } else if type == "sheet", let embedId = object["embed_id"] as? String {
                record = embedRecord(
                    id: embedId,
                    type: "sheets-sheet",
                    appId: "sheets",
                    skillId: nil,
                    data: ["title": "Table", "rows": []],
                    parentEmbedId: object["parent_embed_id"] as? String,
                    embedIds: nil
                )
            } else if let embedId = object["embed_id"] as? String {
                record = embedRecord(
                    id: embedId,
                    type: normalizedEmbedType(from: type, appId: object["app_id"] as? String ?? fallbackAppId, skillId: object["skill_id"] as? String),
                    appId: object["app_id"] as? String ?? fallbackAppId,
                    skillId: object["skill_id"] as? String,
                    data: object,
                    parentEmbedId: object["parent_embed_id"] as? String,
                    embedIds: embedIds(from: object["embed_ids"] ?? object["child_embed_ids"])
                )
            } else {
                continue
            }

            records.insert(record, at: 0)
            refs.insert(embedRef(for: record), at: 0)
            cleaned.replaceSubrange(fullRange, with: "\n[[embed:\(record.id)]]\n")
        }

        let markdownEmbedPattern = #"\[!\]\(embed:([^)]+)\)"#
        for match in regexMatches(markdownEmbedPattern, in: cleaned).reversed() {
            guard let refRange = Range(match.range(at: 1), in: cleaned),
                  let fullRange = Range(match.range(at: 0), in: cleaned) else { continue }

            let ref = String(cleaned[refRange])
            cleaned.replaceSubrange(fullRange, with: "\n[[embedref:\(ref)]]\n")
        }

        return (sanitize(cleaned), refs, records)
    }

    private static func embedRef(for record: EmbedRecord) -> EmbedRef {
        EmbedRef(id: record.id, type: record.type, status: record.status.rawValue, data: nil)
    }

    private static func embedRecord(
        id: String,
        type: String,
        appId: String?,
        skillId: String?,
        data: [String: Any],
        parentEmbedId: String?,
        embedIds: String?
    ) -> EmbedRecord {
        EmbedRecord(
            id: id,
            type: type,
            status: .finished,
            data: .raw(data.mapValues { AnyCodable($0) }),
            parentEmbedId: parentEmbedId,
            appId: appId,
            skillId: skillId,
            embedIds: embedIds,
            createdAt: "2026-04-20T12:00:00Z"
        )
    }

    private static func demoEmbedRecords(for chatId: String) -> [String: EmbedRecord] {
        guard let fileName = demoEmbedFileName(for: chatId),
              let sourceURL = demoEmbedURL(fileName: fileName),
              let source = try? String(contentsOf: sourceURL, encoding: .utf8) else {
            return [:]
        }

        var records: [String: EmbedRecord] = [:]
        let objectPattern = #"\{\s*embed_id:\s*"([^"]+)"([\s\S]*?)\n\s*\},"#
        for match in regexMatches(objectPattern, in: source) {
            guard let idRange = Range(match.range(at: 1), in: source),
                  let blockRange = Range(match.range(at: 2), in: source) else { continue }

            let embedId = String(source[idRange])
            let block = String(source[blockRange])
            guard let rawType = firstRegexCapture(#"type:\s*"([^"]+)""#, in: block),
                  let rawContent = firstRegexCapture(#"content:\s*`([\s\S]*?)`"#, in: block) else { continue }
            let content = unescapedDemoEmbedContent(rawContent)
            var data = parseToonObject(content)
            data["embed_id"] = embedId
            data["type"] = data["type"] ?? rawType

            let parentEmbedId = firstRegexCapture(#"parent_embed_id:\s*"([^"]+)""#, in: block)
            let embedIds = firstRegexCapture(#"embed_ids:\s*\[([^\]]*)\]"#, in: block)
                .map(parseEmbedIdArray)
                ?? firstRegexCapture(#"embed_ids:\s*"([^"]*)""#, in: block)
                ?? data["embed_ids"] as? String
            let appId = data["app_id"] as? String
            let skillId = data["skill_id"] as? String
            let normalizedType = normalizedEmbedType(from: rawType, appId: appId, skillId: skillId)

            let record = embedRecord(
                id: embedId,
                type: normalizedType,
                appId: appId ?? EmbedType(rawValue: normalizedType)?.appId,
                skillId: skillId,
                data: data,
                parentEmbedId: parentEmbedId,
                embedIds: embedIds
            )
            records[embedId] = record
            if let embedRef = data["embed_ref"] as? String, !embedRef.isEmpty {
                records[embedRef] = record
            }
        }
        return records
    }

    private static func unescapedDemoEmbedContent(_ content: String) -> String {
        content
            .replacingOccurrences(of: #"\n"#, with: "\n")
            .replacingOccurrences(of: #"\""#, with: "\"")
            .replacingOccurrences(of: #"\u20ac"#, with: "€")
    }

    private static func firstRegexCapture(_ pattern: String, in text: String) -> String? {
        guard let regex = try? NSRegularExpression(pattern: pattern, options: []),
              let match = regex.firstMatch(in: text, range: NSRange(text.startIndex..., in: text)),
              let range = Range(match.range(at: 1), in: text) else {
            return nil
        }
        return String(text[range])
    }

    private static func parseEmbedIdArray(_ value: String) -> String {
        value
            .split(separator: ",")
            .map {
                $0.trimmingCharacters(in: CharacterSet(charactersIn: " \n\t\""))
            }
            .filter { !$0.isEmpty }
            .joined(separator: "|")
    }

    private static func demoEmbedFileName(for chatId: String) -> String? {
        switch chatId {
        case "example-gigantic-airplanes": return "gigantic-airplanes.ts"
        case "example-artemis-ii-mission": return "artemis-ii-mission.ts"
        case "example-beautiful-single-page-html": return "beautiful-single-page-html.ts"
        case "example-eu-chat-control-law": return "eu-chat-control-law-criticisms.ts"
        case "example-flights-berlin-bangkok": return "flights-berlin-to-bangkok.ts"
        case "example-creativity-drawing-meetups-berlin": return "creativity-drawing-meetups-berlin.ts"
        default: return nil
        }
    }

    private static func demoEmbedURL(fileName: String) -> URL? {
        let resourceName = (fileName as NSString).deletingPathExtension
        let resourceExtension = (fileName as NSString).pathExtension
        let bundleCandidates = [
            Bundle.main.url(forResource: resourceName, withExtension: resourceExtension, subdirectory: "example_chats"),
            Bundle.main.url(forResource: resourceName, withExtension: resourceExtension, subdirectory: "demo_chats/example_chats"),
            Bundle.main.url(forResource: resourceName, withExtension: resourceExtension),
            Bundle.main.url(forResource: fileName, withExtension: nil, subdirectory: "example_chats"),
            Bundle.main.url(forResource: fileName, withExtension: nil, subdirectory: "demo_chats/example_chats"),
            Bundle.main.url(forResource: fileName, withExtension: nil)
        ]
        if let bundled = bundleCandidates.compactMap({ $0 }).first {
            return bundled
        }

        let sourceFile = URL(fileURLWithPath: #filePath)
        let repoRoot = sourceFile
            .deletingLastPathComponent() // ViewModels/
            .deletingLastPathComponent() // Chat/
            .deletingLastPathComponent() // Features/
            .deletingLastPathComponent() // Sources/
            .deletingLastPathComponent() // OpenMates/
            .deletingLastPathComponent() // apple/
        return repoRoot.appendingPathComponent("frontend/packages/ui/src/demo_chats/data/example_chats/\(fileName)")
    }

    private static func parseToonObject(_ content: String) -> [String: Any] {
        var result: [String: Any] = [:]
        for line in content.components(separatedBy: .newlines) {
            let trimmed = line.trimmingCharacters(in: .whitespacesAndNewlines)
            guard let separator = trimmed.firstIndex(of: ":") else { continue }
            let key = String(trimmed[..<separator]).trimmingCharacters(in: .whitespacesAndNewlines)
            var value = String(trimmed[trimmed.index(after: separator)...]).trimmingCharacters(in: .whitespacesAndNewlines)
            if value.hasPrefix("\""), value.hasSuffix("\""), value.count >= 2 {
                value.removeFirst()
                value.removeLast()
            }
            value = value
                .replacingOccurrences(of: #"\""#, with: #"""#)
                .replacingOccurrences(of: #"\\n"#, with: "\n")
            if !key.isEmpty {
                result[key] = value
            }
        }
        return result
    }

    private static func embedIds(from value: Any?) -> String? {
        if let ids = value as? [String] {
            return ids.joined(separator: "|")
        }
        if let ids = value as? [Any] {
            let strings = ids.compactMap { $0 as? String }
            return strings.isEmpty ? nil : strings.joined(separator: "|")
        }
        return value as? String
    }

    private static func normalizedEmbedType(from type: String, appId: String?, skillId: String?) -> String {
        if type == "code" {
            return "code-code"
        }
        if type == "website" || type == "web_result" || type == "search_result" {
            return "web-website"
        }
        if type == "image_result" {
            return "images-image-result"
        }
        if type == "connection" {
            return "travel-connection"
        }
        if type == "event_result" || type == "event" {
            return "events-event"
        }
        if type == "video_result" {
            return "videos-video"
        }
        if let appId, let skillId, type == "app_skill_use" {
            return "app:\(appId):\(skillId)"
        }
        return type
    }

    private static func stableEmbedId(prefix: String, value: String) -> String {
        var hash: UInt64 = 14_695_981_039_346_656_037
        for byte in value.utf8 {
            hash ^= UInt64(byte)
            hash &*= 1_099_511_628_211
        }
        return "\(prefix)-\(String(hash, radix: 16))"
    }

    private static func regexMatches(_ pattern: String, in text: String) -> [NSTextCheckingResult] {
        guard let regex = try? NSRegularExpression(pattern: pattern, options: []) else { return [] }
        return regex.matches(in: text, range: NSRange(text.startIndex..., in: text))
    }

    private static func demoFollowUpKeys(_ key: String) -> [String] {
        (1...3).map { "demo_chats.\(key).follow_up_\($0)" }
    }

    private static func exampleKey(for id: String) -> String {
        switch id {
        case "example-gigantic-airplanes": return "gigantic_airplanes"
        case "example-artemis-ii-mission": return "artemis_ii_mission"
        case "example-beautiful-single-page-html": return "beautiful_single_page_html"
        case "example-eu-chat-control-law": return "eu_chat_control_law"
        case "example-flights-berlin-bangkok": return "flights_berlin_bangkok"
        case "example-creativity-drawing-meetups-berlin": return "creativity_drawing_meetups_berlin"
        default: return id
        }
    }

    private static func legalPrivacyContent() -> String {
        [
            "# \(AppStrings.legalPrivacyTitle)",
            "*\(text("legal.privacy.last_updated")): April 16, 2026*",
            section("legal.privacy.data_protection.heading", "legal.privacy.data_protection.overview"),
            text("legal.privacy.data_protection.website_vs_webapp"),
            section("legal.privacy.vercel.heading", "legal.privacy.vercel.description"),
            section("legal.privacy.webapp_services.heading", "legal.privacy.webapp_services.intro"),
            section("legal.privacy.hetzner.heading", "legal.privacy.hetzner.description"),
            section("legal.privacy.brevo.heading", "legal.privacy.brevo.description"),
            section("legal.privacy.stripe.heading", "legal.privacy.stripe.description"),
            section("legal.privacy.brave.heading", "legal.privacy.brave.description"),
            section("legal.privacy.google.heading", "legal.privacy.google.description"),
            section("legal.privacy.firecrawl.heading", "legal.privacy.firecrawl.description")
        ].joined(separator: "\n\n")
    }

    private static func legalTermsContent() -> String {
        [
            "# \(AppStrings.legalTermsTitle)",
            "*Last updated: January 28, 2026*",
            section("legal.terms.acceptance.heading", "legal.terms.acceptance.text"),
            section("legal.terms.service.heading", "legal.terms.service.text"),
            section("legal.terms.accounts.heading", "legal.terms.accounts.text"),
            section("legal.terms.credits.heading", "legal.terms.credits.text"),
            section("legal.terms.acceptable_use.heading", "legal.terms.acceptable_use.text"),
            section("legal.terms.privacy.heading", "legal.terms.privacy.text")
        ].filter { !$0.contains(".heading") && !$0.contains(".text") }.joined(separator: "\n\n")
    }

    private static func legalImprintContent() -> String {
        [
            "# \(AppStrings.legalImprintTitle)",
            "## \(text("legal.imprint.information_tmg"))",
            "OpenMates",
            "## \(text("legal.imprint.contact"))",
            "\(text("legal.imprint.email")): support@openmates.org"
        ].joined(separator: "\n\n")
    }

    private static func section(_ titleKey: String, _ bodyKey: String) -> String {
        "## \(text(titleKey))\n\n\(text(bodyKey))"
    }

    private static func text(_ key: String) -> String {
        LocalizationManager.shared.text(key)
    }

    private static func sanitize(_ content: String) -> String {
        let placeholders = [
            "[[example_chats_group]]",
            "[[dev_example_chats_group]]",
            "[[app_store_group]]",
            "[[dev_app_store_group]]",
            "[[skills_group]]",
            "[[dev_skills_group]]",
            "[[focus_modes_group]]",
            "[[dev_focus_modes_group]]",
            "[[settings_memories_group]]",
            "[[dev_settings_memories_group]]",
            "[[ai_models_group]]",
            "[[for_developers_embed]]"
        ]
        var cleaned = content
        let embedPlaceholderPattern = #"\[\[embed(?:ref)?:[^\]]+\]\]"#
        let embedPlaceholderMatches = regexMatches(embedPlaceholderPattern, in: cleaned)
            .compactMap { match -> String? in
                guard let range = Range(match.range(at: 0), in: cleaned) else { return nil }
                return String(cleaned[range])
            }
        for (index, placeholder) in embedPlaceholderMatches.enumerated() {
            cleaned = cleaned.replacingOccurrences(of: placeholder, with: "__OM_EMBED_PLACEHOLDER_\(index)__")
        }
        for (index, placeholder) in placeholders.enumerated() {
            cleaned = cleaned.replacingOccurrences(of: placeholder, with: "__OM_DEMO_PLACEHOLDER_\(index)__")
        }
        cleaned = cleaned
            .replacingOccurrences(of: #"\[\[[^\]]+\]\]"#, with: "", options: .regularExpression)
            .replacingOccurrences(of: "\n\n\n", with: "\n\n")
            .trimmingCharacters(in: .whitespacesAndNewlines)
        for (index, placeholder) in placeholders.enumerated() {
            cleaned = cleaned.replacingOccurrences(of: "__OM_DEMO_PLACEHOLDER_\(index)__", with: placeholder)
        }
        for (index, placeholder) in embedPlaceholderMatches.enumerated() {
            cleaned = cleaned.replacingOccurrences(of: "__OM_EMBED_PLACEHOLDER_\(index)__", with: placeholder)
        }
        return cleaned
    }
}

@MainActor
final class ChatSendPipeline {
    private let crypto = CryptoManager.shared
    private var encryptedUserStorageSent = Set<String>()
    private var completedAssistantStorageSent = Set<String>()

    struct SendResult {
        let chat: Chat
        let message: Message
    }

    func sendUserMessage(
        content: String,
        in chat: Chat,
        existingMessages: [Message],
        wsManager: WebSocketManager?,
        chatStore: ChatStore?,
        activateChat: Bool = true,
        waitForRemoteSend: Bool = true,
        composerEmbeds: [ComposerPendingEmbed] = []
    ) async throws -> SendResult {
        guard let wsManager else { throw ChatSendError.webSocketUnavailable }
        let now = Date()
        let createdAt = Self.isoString(from: now)
        let createdAtUnix = Int(now.timeIntervalSince1970)
        let messageId = "\(chat.id.suffix(10))-\(UUID().uuidString)"
        let keyMaterial = try await ensureChatKey(chatId: chat.id, encryptedChatKey: chat.encryptedChatKey)
        let encryptedContent = try await crypto.encryptContent(content, key: keyMaterial.key)
        let encryptedEmbedPayloads = try await encryptedEmbeds(
            composerEmbeds,
            chatId: chat.id,
            messageId: messageId,
            chatKey: keyMaterial.key
        )
        let nextMessagesV = max(chat.messagesV ?? existingMessages.count, existingMessages.count) + 1
        let updatedChat = copyChat(
            chat,
            lastMessageAt: createdAt,
            updatedAt: createdAt,
            encryptedChatKey: keyMaterial.encryptedChatKey,
            messagesV: nextMessagesV
        )
        let message = Message(
            id: messageId,
            chatId: chat.id,
            role: .user,
            content: content,
            encryptedContent: encryptedContent,
            createdAt: createdAt,
            updatedAt: nil,
            appId: nil,
            isStreaming: nil,
            embedRefs: composerEmbeds.isEmpty ? nil : composerEmbeds.map { embed in
                EmbedRef(id: embed.id, type: embed.type, status: embed.status, data: nil)
            }
        )

        chatStore?.upsertChat(updatedChat)
        chatStore?.appendMessage(message, to: chat.id)

        var messagePayload: [String: Any] = [
            "message_id": messageId,
            "role": "user",
            "content": content,
            "created_at": createdAtUnix,
            "sender_name": "user",
            "chat_has_title": (updatedChat.titleV ?? 0) > 0
        ]
        if (updatedChat.titleV ?? 0) > 0 {
            messagePayload["current_chat_title"] = updatedChat.title
        }

        var outboundPayload: [String: Any] = [
            "chat_id": chat.id,
            "message": messagePayload,
            "encrypted_chat_key": keyMaterial.encryptedChatKey
        ]
        let sendableEmbeds = composerEmbeds.compactMap(\.serverPayload)
        if !sendableEmbeds.isEmpty {
            outboundPayload["embeds"] = sendableEmbeds
        }
        if !encryptedEmbedPayloads.isEmpty {
            outboundPayload["encrypted_embeds"] = encryptedEmbedPayloads
        }

        if waitForRemoteSend {
            try await sendRemoteUserMessage(
                chatId: chat.id,
                activateChat: activateChat,
                wsManager: wsManager,
                outboundPayload: outboundPayload
            )
        } else {
            Task { @MainActor in
                do {
                    try await self.sendRemoteUserMessage(
                        chatId: chat.id,
                        activateChat: activateChat,
                        wsManager: wsManager,
                        outboundPayload: outboundPayload
                    )
                } catch {
                    print("[ChatSendPipeline] Background send failed for chat \(chat.id.prefix(8)): \(error)")
                }
            }
        }

        return SendResult(chat: updatedChat, message: message)
    }

    private func sendRemoteUserMessage(
        chatId: String,
        activateChat: Bool,
        wsManager: WebSocketManager,
        outboundPayload: [String: Any]
    ) async throws {
        if activateChat {
            try await sendSetActiveChat(chatId, wsManager: wsManager)
        }
        try await wsManager.send(WSOutboundMessage(
            type: "chat_message_added",
            payload: outboundPayload
        ))
    }

    func sendEncryptedUserStoragePackage(
        chat: Chat,
        userMessage: Message,
        assistantTaskId: String,
        metadata: StreamingClient.ChatMetadata,
        wsManager: WebSocketManager?,
        chatStore: ChatStore?
    ) async throws -> Chat {
        guard let wsManager else { throw ChatSendError.webSocketUnavailable }
        guard encryptedUserStorageSent.insert(userMessage.id).inserted else { return chat }

        let keyMaterial = try await ensureChatKey(
            chatId: chat.id,
            encryptedChatKey: metadata.encryptedChatKey ?? chat.encryptedChatKey
        )
        let content = userMessage.content ?? ""
        let encryptedContent: String
        if let existing = userMessage.encryptedContent {
            encryptedContent = existing
        } else {
            encryptedContent = try await crypto.encryptContent(content, key: keyMaterial.key)
        }
        let isNewChatMetadata = (chat.titleV ?? 0) == 0
        let encryptedTitle = isNewChatMetadata ? try await encryptOptional(metadata.title, key: keyMaterial.key) : nil
        let icon = isNewChatMetadata ? preferredIcon(from: metadata.iconNames, category: metadata.category) : nil
        let encryptedIcon = try await encryptOptional(icon, key: keyMaterial.key)
        let encryptedCategory = isNewChatMetadata ? try await encryptOptional(metadata.category, key: keyMaterial.key) : nil
        let encryptedSenderName = try await crypto.encryptContent("user", key: keyMaterial.key)
        let encryptedUserCategory = try await encryptOptional(metadata.category, key: keyMaterial.key)
        let createdAtUnix = Self.unixSeconds(from: userMessage.createdAt)
        let nextTitleV = encryptedTitle == nil ? chat.titleV : max(chat.titleV ?? 0, 0) + 1
        let updatedChat = copyChat(
            chat,
            title: isNewChatMetadata ? (metadata.title ?? chat.title) : chat.title,
            updatedAt: Self.isoString(from: Date()),
            category: isNewChatMetadata ? (metadata.category ?? chat.category) : chat.category,
            icon: isNewChatMetadata ? (icon ?? chat.icon) : chat.icon,
            encryptedTitle: encryptedTitle ?? chat.encryptedTitle,
            encryptedCategory: encryptedCategory ?? chat.encryptedCategory,
            encryptedIcon: encryptedIcon ?? chat.encryptedIcon,
            encryptedChatKey: keyMaterial.encryptedChatKey,
            titleV: nextTitleV
        )
        chatStore?.upsertChat(updatedChat)

        var payload: [String: Any] = [
            "chat_id": chat.id,
            "message_id": userMessage.id,
            "encrypted_content": encryptedContent,
            "created_at": createdAtUnix,
            "encrypted_chat_key": keyMaterial.encryptedChatKey,
            "versions": [
                "messages_v": updatedChat.messagesV ?? 1,
                "title_v": updatedChat.titleV ?? 0,
                "last_edited_overall_timestamp": createdAtUnix
            ],
            "task_id": assistantTaskId
        ]
        if let encryptedTitle { payload["encrypted_title"] = encryptedTitle }
        if let encryptedIcon { payload["encrypted_icon"] = encryptedIcon }
        if let encryptedCategory { payload["encrypted_chat_category"] = encryptedCategory }
        payload["encrypted_sender_name"] = encryptedSenderName
        if let encryptedUserCategory { payload["encrypted_category"] = encryptedUserCategory }

        try await wsManager.send(WSOutboundMessage(type: "encrypted_chat_metadata", payload: payload))
        return updatedChat
    }

    func persistCompletedAssistantMessage(
        _ message: Message,
        userMessageId: String?,
        wsManager: WebSocketManager?,
        chatStore: ChatStore?
    ) async throws -> Message {
        guard let wsManager else { throw ChatSendError.webSocketUnavailable }
        guard completedAssistantStorageSent.insert(message.id).inserted else { return message }
        guard let chat = chatStore?.chat(for: message.chatId) else { return message }
        let keyMaterial = try await ensureChatKey(chatId: message.chatId, encryptedChatKey: chat.encryptedChatKey)
        let encryptedContent: String
        if let existing = message.encryptedContent {
            encryptedContent = existing
        } else {
            encryptedContent = try await crypto.encryptContent(message.content ?? "", key: keyMaterial.key)
        }
        let encryptedCategory = try await encryptOptional(message.appId, key: keyMaterial.key)
        let encryptedModelName = try await encryptOptional(message.modelName, key: keyMaterial.key)
        let createdAtUnix = Self.unixSeconds(from: message.createdAt)
        let persisted = Message(
            id: message.id,
            chatId: message.chatId,
            role: message.role,
            content: message.content,
            encryptedContent: encryptedContent,
            createdAt: message.createdAt,
            updatedAt: message.updatedAt,
            appId: message.appId,
            isStreaming: false,
            embedRefs: message.embedRefs,
            modelName: message.modelName
        )

        chatStore?.appendMessage(persisted, to: message.chatId)

        if message.role == .system {
            var systemMessage: [String: Any] = [
                "message_id": message.id,
                "role": "system",
                "encrypted_content": encryptedContent,
                "created_at": createdAtUnix,
                "status": "waiting_for_user"
            ]
            if let userMessageId { systemMessage["user_message_id"] = userMessageId }
            try await wsManager.send(WSOutboundMessage(
                type: "chat_system_message_added",
                payload: [
                    "chat_id": message.chatId,
                    "message": systemMessage
                ]
            ))
        } else {
            var messagePayload: [String: Any] = [
                "message_id": message.id,
                "chat_id": message.chatId,
                "role": "assistant",
                "created_at": createdAtUnix,
                "status": "synced",
                "encrypted_content": encryptedContent
            ]
            if let userMessageId { messagePayload["user_message_id"] = userMessageId }
            if let encryptedCategory { messagePayload["encrypted_category"] = encryptedCategory }
            if let encryptedModelName { messagePayload["encrypted_model_name"] = encryptedModelName }
            try await wsManager.send(WSOutboundMessage(
                type: "ai_response_completed",
                payload: [
                    "chat_id": message.chatId,
                    "message": messagePayload,
                    "versions": [
                        "messages_v": chat.messagesV ?? chatStore?.messages(for: message.chatId).count ?? 1,
                        "last_edited_overall_timestamp": createdAtUnix
                    ]
                ]
            ))
        }
        return persisted
    }

    func sendPostProcessingMetadata(
        chatId: String,
        followUpSuggestions: [String],
        newChatSuggestions: [String],
        chatSummary: String?,
        chatTags: [String],
        updatedTitle: String?,
        wsManager: WebSocketManager?,
        chatStore: ChatStore?
    ) async {
        guard let wsManager, let chat = chatStore?.chat(for: chatId) else { return }
        do {
            let keyMaterial = try await ensureChatKey(chatId: chatId, encryptedChatKey: chat.encryptedChatKey)
            var payload: [String: Any] = [
                "chat_id": chatId,
                "encrypted_chat_key": keyMaterial.encryptedChatKey
            ]
            if !followUpSuggestions.isEmpty {
                payload["encrypted_follow_up_suggestions"] = try await encryptStringArray(Array(followUpSuggestions.prefix(18)), key: keyMaterial.key)
            }
            if !chatTags.isEmpty {
                payload["encrypted_chat_tags"] = try await encryptStringArray(Array(chatTags.prefix(10)), key: keyMaterial.key)
            }
            var encryptedSummary: String?
            if let chatSummary, !chatSummary.isEmpty {
                encryptedSummary = try await crypto.encryptContent(chatSummary, key: keyMaterial.key)
                payload["encrypted_chat_summary"] = encryptedSummary
            }
            var encryptedUpdatedTitle: String?
            if let updatedTitle, !updatedTitle.isEmpty {
                encryptedUpdatedTitle = try await crypto.encryptContent(updatedTitle, key: keyMaterial.key)
                payload["encrypted_title"] = encryptedUpdatedTitle
            }
            if !newChatSuggestions.isEmpty,
               let userId = await AuthManager.currentUserId(),
               let masterKey = try await crypto.loadMasterKey(for: userId) {
                var encryptedSuggestions: [String] = []
                for suggestion in newChatSuggestions.prefix(6) {
                    encryptedSuggestions.append(try await crypto.encryptWithMasterKey(suggestion, masterKey: masterKey))
                }
                payload["encrypted_new_chat_suggestions"] = encryptedSuggestions
            }
            guard payload.count > 2 else { return }
            if encryptedSummary != nil || encryptedUpdatedTitle != nil || chat.encryptedChatKey != keyMaterial.encryptedChatKey {
                chatStore?.upsertChat(copyChat(
                    chat,
                    title: updatedTitle?.isEmpty == false ? updatedTitle : chat.title,
                    updatedAt: Self.isoString(from: Date()),
                    chatSummary: chatSummary?.isEmpty == false ? chatSummary : chat.chatSummary,
                    encryptedTitle: encryptedUpdatedTitle ?? chat.encryptedTitle,
                    encryptedChatSummary: encryptedSummary ?? chat.encryptedChatSummary,
                    encryptedChatKey: keyMaterial.encryptedChatKey
                ))
            }
            try await wsManager.send(WSOutboundMessage(type: "update_post_processing_metadata", payload: payload))
        } catch {
            print("[ChatSendPipeline] Failed to send post-processing metadata: \(error)")
        }
    }

    func sendSetActiveChat(_ chatId: String?, wsManager: WebSocketManager) async throws {
        try await wsManager.send(WSOutboundMessage(
            type: "set_active_chat",
            payload: ["chat_id": chatId as Any]
        ))
    }

    private func ensureChatKey(chatId: String, encryptedChatKey: String?) async throws -> (key: SymmetricKey, encryptedChatKey: String) {
        guard let userId = await AuthManager.currentUserId(),
              let masterKey = try await crypto.loadMasterKey(for: userId) else {
            throw ChatSendError.missingMasterKey
        }

        if let key = ChatKeyManager.shared.key(for: chatId) {
            let encrypted: String
            if let encryptedChatKey {
                encrypted = encryptedChatKey
            } else {
                encrypted = try await crypto.wrapChatKey(key, masterKey: masterKey)
            }
            return (key, encrypted)
        }

        if let encryptedChatKey {
            let key = try await crypto.unwrapChatKey(encryptedChatKeyBase64: encryptedChatKey, masterKey: masterKey)
            ChatKeyManager.shared.setKey(key, for: chatId)
            return (key, encryptedChatKey)
        }

        let key = await ChatKeyManager.shared.createKeyForNewChat(chatId)
        let encrypted = try await crypto.wrapChatKey(key, masterKey: masterKey)
        return (key, encrypted)
    }

    private func encryptedEmbeds(
        _ embeds: [ComposerPendingEmbed],
        chatId: String,
        messageId: String,
        chatKey: SymmetricKey
    ) async throws -> [[String: Any]] {
        let persistableEmbeds = embeds.filter(\.canPersistDirectly)
        guard !persistableEmbeds.isEmpty else { return [] }
        guard let userId = await AuthManager.currentUserId(),
              let masterKey = try await crypto.loadMasterKey(for: userId) else {
            throw ChatSendError.missingMasterKey
        }

        let hashedChatId = sha256Hex(chatId)
        let hashedMessageId = sha256Hex(messageId)
        let hashedUserId = sha256Hex(userId)
        let now = Int(Date().timeIntervalSince1970)

        var encryptedPayloads: [[String: Any]] = []
        for embed in persistableEmbeds {
            guard let content = embed.content else { continue }
            let embedKey = deriveEmbedKey(from: chatKey, embedId: embed.id)
            let hashedEmbedId = sha256Hex(embed.id)
            let wrappedWithMaster = try await encryptRawKey(embedKey, wrappingKey: masterKey)
            let wrappedWithChat = try await encryptRawKey(embedKey, wrappingKey: chatKey)
            var payload: [String: Any] = [
                "embed_id": embed.id,
                "encrypted_type": try await encryptEmbedField(embed.type, key: embedKey),
                "encrypted_content": try await encryptEmbedField(content, key: embedKey),
                "status": embed.status,
                "hashed_chat_id": hashedChatId,
                "hashed_message_id": hashedMessageId,
                "hashed_user_id": hashedUserId,
                "created_at": now,
                "updated_at": now,
                "embed_keys": [
                    [
                        "hashed_embed_id": hashedEmbedId,
                        "key_type": "master",
                        "hashed_chat_id": NSNull(),
                        "encrypted_embed_key": wrappedWithMaster,
                        "hashed_user_id": hashedUserId,
                        "created_at": now
                    ],
                    [
                        "hashed_embed_id": hashedEmbedId,
                        "key_type": "chat",
                        "hashed_chat_id": hashedChatId,
                        "encrypted_embed_key": wrappedWithChat,
                        "hashed_user_id": hashedUserId,
                        "created_at": now
                    ]
                ]
            ]
            if let textPreview = embed.textPreview {
                payload["encrypted_text_preview"] = try await encryptEmbedField(textPreview, key: embedKey)
            }
            encryptedPayloads.append(payload)
        }
        return encryptedPayloads
    }

    private func deriveEmbedKey(from chatKey: SymmetricKey, embedId: String) -> SymmetricKey {
        HKDF<SHA256>.deriveKey(
            inputKeyMaterial: chatKey,
            salt: Data("openmates-embed-key-v1".utf8),
            info: Data(embedId.utf8),
            outputByteCount: 32
        )
    }

    private func encryptEmbedField(_ value: String, key: SymmetricKey) async throws -> String {
        try await encryptRawData(Data(value.utf8), key: key)
    }

    private func encryptRawKey(_ key: SymmetricKey, wrappingKey: SymmetricKey) async throws -> String {
        let raw = key.withUnsafeBytes { Data($0) }
        return try await encryptRawData(raw, key: wrappingKey)
    }

    private func encryptRawData(_ data: Data, key: SymmetricKey) async throws -> String {
        let encrypted = try await crypto.encrypt(data, using: key)
        var combined = Data()
        combined.append(encrypted.nonce)
        combined.append(encrypted.ciphertext)
        return combined.base64EncodedString()
    }

    private func sha256Hex(_ value: String) -> String {
        SHA256.hash(data: Data(value.utf8)).map { String(format: "%02x", $0) }.joined()
    }

    private func encryptOptional(_ value: String?, key: SymmetricKey) async throws -> String? {
        guard let value, !value.isEmpty else { return nil }
        return try await crypto.encryptContent(value, key: key)
    }

    private func encryptStringArray(_ values: [String], key: SymmetricKey) async throws -> String {
        let data = try JSONSerialization.data(withJSONObject: values)
        let json = String(data: data, encoding: .utf8) ?? "[]"
        return try await crypto.encryptContent(json, key: key)
    }

    private func preferredIcon(from iconNames: [String], category: String?) -> String {
        iconNames.first ?? categoryIconFallback(category)
    }

    private func categoryIconFallback(_ category: String?) -> String {
        switch category {
        case "web": return "search"
        case "travel": return "plane"
        case "videos": return "video"
        case "nutrition": return "utensils"
        case "code": return "code"
        default: return "sparkles"
        }
    }

    private func copyChat(
        _ chat: Chat,
        title: String? = nil,
        lastMessageAt: String? = nil,
        updatedAt: String? = nil,
        category: String? = nil,
        icon: String? = nil,
        chatSummary: String? = nil,
        encryptedTitle: String? = nil,
        encryptedCategory: String? = nil,
        encryptedIcon: String? = nil,
        encryptedChatSummary: String? = nil,
        encryptedChatKey: String? = nil,
        messagesV: Int? = nil,
        titleV: Int? = nil
    ) -> Chat {
        Chat(
            id: chat.id,
            title: title ?? chat.title,
            lastMessageAt: lastMessageAt ?? chat.lastMessageAt,
            createdAt: chat.createdAt,
            updatedAt: updatedAt ?? chat.updatedAt,
            isArchived: chat.isArchived,
            isPinned: chat.isPinned,
            appId: chat.appId,
            category: category ?? chat.category,
            icon: icon ?? chat.icon,
            chatSummary: chatSummary ?? chat.chatSummary,
            encryptedTitle: encryptedTitle ?? chat.encryptedTitle,
            encryptedCategory: encryptedCategory ?? chat.encryptedCategory,
            encryptedIcon: encryptedIcon ?? chat.encryptedIcon,
            encryptedChatSummary: encryptedChatSummary ?? chat.encryptedChatSummary,
            encryptedChatKey: encryptedChatKey ?? chat.encryptedChatKey,
            messagesV: messagesV ?? chat.messagesV,
            titleV: titleV ?? chat.titleV,
            draftV: chat.draftV,
            lastVisibleMessageId: chat.lastVisibleMessageId
        )
    }

    static func isoString(from date: Date) -> String {
        ISO8601DateFormatter().string(from: date)
    }

    static func unixSeconds(from isoString: String) -> Int {
        let fractional = ISO8601DateFormatter()
        fractional.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        if let date = fractional.date(from: isoString) ?? ISO8601DateFormatter().date(from: isoString) {
            return Int(date.timeIntervalSince1970)
        }
        return Int(Date().timeIntervalSince1970)
    }
}

private enum ChatSendError: LocalizedError {
    case missingMasterKey
    case webSocketUnavailable

    var errorDescription: String? {
        switch self {
        case .missingMasterKey:
            return "Missing encryption key for this device. Please sign in again."
        case .webSocketUnavailable:
            return "Realtime connection is not ready. Please try again."
        }
    }
}
