// The chat view model's message source for saved chats: the Rust core's open
// chat window (`CoreChatWindow`, plan apple-client-core-migration A4 lane 3).
// `loadChat` opens the chat through the core; the core decrypts, orders,
// pages and caches the messages, and this extension only places its mapped
// messages into the transcript's bounded row window (`ChatHistoryWindowPolicy`):
// - a window change replaces the rows once (cached first paint, then the
//   strict read, live updates and older pages);
// - a per-message update while a reply streams patches that one row.
// A chat shape the core refuses (incognito, anonymous, local fixtures; typed
// `.refused`) and a host without a core keep the local loader in
// `ChatViewModel`. Rows the frozen Swift send pipeline added locally (pending
// sends, its streaming reply) and the core has not delivered yet are kept in
// time order until the core's window carries them (send moves to the core in A5).
// Still Swift for an open core chat, until the core exposes them: the chat key
// and the encrypted header metadata, follow-up suggestions, embed content
// hydration, the stream/embed/lifecycle subscriptions of the Swift send path
// and queued follow-up state.
// Specification: specifications/architecture/client-core/specification.yml
// Assertions: client-core.viewmodel.capability-contract, client-core.viewmodel.stream-updates, client-core.shell.allowed-responsibilities, client-core.apple.strangler-order

import Combine
import Foundation

/// The view model's tie to the shared core window for the chat it shows.
struct ChatCoreWindowBinding {
    /// The chat this view model reads from the core (`nil`: none).
    var chatID: String?
    /// The request of this view model's last open.
    var request: UInt64 = 0
    /// Changes with every bind; async work of an older bind compares it.
    var token = UUID()
    var subscription: AnyCancellable?
    /// Ids the core delivered for this chat; a row with another id is local.
    var messageIDs = Set<String>()
    var openTask: Task<Void, Never>?
    /// `loadChat` waiting for the first window (`nil` result) or the open's end.
    var firstWindowWaiter: CheckedContinuation<CoreChatOpenOutcome?, Never>?
    /// The open ended before the first window arrived.
    var finishedOutcome: CoreChatOpenOutcome?
    /// A core window was placed into the rows.
    var painted = false
    /// Embed ids already handed to embed hydration for this bind.
    var hydratedEmbedIDs = Set<String>()
}

extension ChatViewModel {
    /// Whether `chatId`'s messages come from the core window.
    func ownsCoreWindow(_ chatId: String) -> Bool {
        coreBinding.chatID == chatId
    }

    /// The core reports older messages for the shown chat.
    var coreWindowHasOlderMessages: Bool {
        guard let bound = coreBinding.chatID, bound == chat?.id else { return false }
        return coreWindow.hasOlderMessages
    }

    /// Closes this view model's core window (the chat view disappeared).
    func closeCoreWindow() {
        detachCoreWindow(closing: true)
    }

    /// Binds this view model to `chatId` in the core window under a new
    /// request and follows its changes.
    @discardableResult
    func beginCoreWindow(chatId: String) -> UInt64 {
        detachCoreWindow(closing: false)
        let request = coreWindow.begin(chatId: chatId)
        coreBinding.chatID = chatId
        coreBinding.request = request
        coreBinding.subscription = coreWindow.changes.sink { [weak self] change in
            self?.applyCoreWindowChange(change)
        }
        return request
    }

    /// Opens `id` through the core. Returns `false` only when the core does
    /// not own this chat shape (`.refused`) or the app has no core; the caller
    /// then reads the local copy. Returns once the first window is shown or
    /// the open ended without one.
    func openThroughCore(id: String, initialChat: Chat?, initialEmbeds: [EmbedRecord], generation: Int) async -> Bool {
        guard coreWindow.isAttached else {
            detachCoreWindow(closing: false)
            return false
        }
        let request = beginCoreWindow(chatId: id)
        let token = coreBinding.token
        let window = coreWindow
        coreBinding.openTask = Task { @MainActor [weak self] in
            let outcome = await window.open(request: request, chatId: id)
            self?.finishCoreOpen(outcome, token: token)
        }

        // The header (title, icon, chat key) still comes from the local chat
        // row, else from the core's chat list row.
        if let local = initialChat ?? chatStore?.chat(for: id) ?? offlineStore.loadChat(id: id) {
            if local.encryptedChatKey == nil, let cached = offlineStore.loadChat(id: id) {
                await ensureChatKey(for: cached)
            }
            await ensureChatKey(for: local)
            let header = await decryptMetadata(for: local)
            guard coreBinding.token == token, generation == loadGeneration else { return true }
            chat = header
        } else if let row = CoreChatList.shared.chat(for: id) {
            chat = row
        }

        let outcome: CoreChatOpenOutcome? = await withCheckedContinuation { continuation in
            if coreBinding.token != token {
                continuation.resume(returning: .cancelled)
            } else if coreBinding.painted {
                continuation.resume(returning: nil)
            } else if let finished = coreBinding.finishedOutcome {
                continuation.resume(returning: finished)
            } else {
                coreBinding.firstWindowWaiter = continuation
            }
        }
        guard coreBinding.token == token, generation == loadGeneration else { return true }
        switch outcome {
        case nil, .opened?:
            break
        case .refused?, .noCore?:
            detachCoreWindow(closing: false)
            return false
        case .cancelled?:
            return true
        case .failed(let failure)?:
            error = failure == .Offline ? AppStrings.reconnecting : AppStrings.genericProcessingError
            isLoading = false
            NativeSyncPerfLog.warning(
                "phase=core.window.loadChat chat=\(id.prefix(8)) outcome=\(CoreSession.errorClass(failure))")
            return true
        }
        if chat?.id != id {
            chat = Chat(id: id, title: coreWindow.title, lastMessageAt: nil, createdAt: "", updatedAt: nil,
                        isArchived: nil, isPinned: nil, appId: nil,
                        category: coreWindow.category.isEmpty ? nil : coreWindow.category,
                        encryptedTitle: nil, encryptedChatKey: nil)
        }
        isLoading = false
        await finishCoreChatOpening(chatId: id, token: token, generation: generation, initialEmbeds: initialEmbeds)
        return true
    }

    /// The Swift parts of an open chat that the core window does not carry yet.
    private func finishCoreChatOpening(chatId: String, token: UUID, generation: Int, initialEmbeds: [EmbedRecord]) async {
        if let header = chat {
            let stored = await decryptFollowUpSuggestions(for: header)
            guard coreBinding.token == token, generation == loadGeneration else { return }
            followUpSuggestions = ChatFollowUpSuggestionPolicy.restore(
                stored: stored,
                hasStoredCiphertext: header.encryptedFollowUpRequestSuggestions != nil,
                legacyExtracted: extractFollowUpSuggestions(from: messages))
        }
        subscribeToStream(chatId: chatId)
        subscribeToEmbedUpdates(chatId: chatId)
        subscribeToChatLifecycle(chatId: chatId)
        for fields in Array(pendingQueuedEvents.values) {
            await applyQueuedFollowupEvent(type: "queued_message_updated", fields: fields)
        }
        guard coreBinding.token == token else { return }
        if !initialEmbeds.isEmpty { await applySyncedEmbeds(initialEmbeds) }
        Task { @MainActor [weak self] in
            await self?.flushPendingSubChatSpawns()
            await self?.flushPendingSubChatCompletions()
        }
    }

    /// The core's open of this bind ended.
    private func finishCoreOpen(_ outcome: CoreChatOpenOutcome, token: UUID) {
        guard coreBinding.token == token else { return }
        coreBinding.openTask = nil
        if let waiter = coreBinding.firstWindowWaiter {
            coreBinding.firstWindowWaiter = nil
            waiter.resume(returning: outcome)
            return
        }
        guard coreBinding.painted else {
            coreBinding.finishedOutcome = outcome
            return
        }
        // The cached window is shown; the strict read failed. Offline keeps
        // the cached rows quietly, any other failure is reported.
        if case .failed(let failure) = outcome, failure != .Offline {
            error = AppStrings.genericProcessingError
            NativeSyncPerfLog.warning(
                "phase=core.window.refresh outcome=\(CoreSession.errorClass(failure))")
        }
    }

    /// Unbinds from the core window; `closing` also closes this bind's window
    /// in the core (a newer open by another reader is left alone).
    func detachCoreWindow(closing: Bool) {
        let binding = coreBinding
        coreBinding = ChatCoreWindowBinding()
        binding.openTask?.cancel()
        binding.firstWindowWaiter?.resume(returning: .cancelled)
        guard closing, binding.chatID != nil else { return }
        let window = coreWindow
        let request = binding.request
        Task { @MainActor in await window.close(request: request) }
    }

    /// Applies one change of the core window to the rows.
    func applyCoreWindowChange(_ change: CoreChatWindowChange) {
        switch change {
        case .window(let chatId, let reason):
            guard chatId == coreBinding.chatID else { return }
            placeCoreWindow(chatId: chatId, reason: reason)
        case .message(let chatId, let messageId):
            guard chatId == coreBinding.chatID, let message = coreWindow.message(id: messageId) else { return }
            patchCoreMessage(message, chatId: chatId)
        case .unavailable(let chatId):
            guard chatId == coreBinding.chatID else { return }
            emptyCoreRows()
            if !coreBinding.painted {
                error = AppStrings.genericProcessingError
                isLoading = false
                resumeFirstWindowWaiter(.cancelled)
            }
        case .cleared:
            guard coreBinding.chatID != nil else { return }
            emptyCoreRows()
            isLoading = false
            resumeFirstWindowWaiter(.cancelled)
        }
    }

    private func resumeFirstWindowWaiter(_ outcome: CoreChatOpenOutcome?) {
        guard let waiter = coreBinding.firstWindowWaiter else { return }
        coreBinding.firstWindowWaiter = nil
        waiter.resume(returning: outcome)
    }

    /// The core window as the row source plus local rows it does not carry yet.
    private func placeCoreWindow(chatId: String, reason: CoreChatWindowChange.Reason) {
        let core = coreWindow.messages
        let coreIDs = Set(core.map(\.id))
        let localOnly = allMessages.filter {
            $0.chatId == chatId && !coreIDs.contains($0.id) && !coreBinding.messageIDs.contains($0.id)
        }
        coreBinding.messageIDs.formUnion(coreIDs)
        var source = core
        for local in localOnly {
            let index = source.firstIndex { $0.createdAt > local.createdAt } ?? source.endIndex
            source.insert(local, at: index)
        }

        let destination: ChatHistoryWindowDestination
        var current = visibleWindowStartIndex..<visibleWindowEndIndex
        let firstShown = messages.first?.id
        if !coreBinding.painted {
            destination = .initial(anchor: chat?.lastVisibleMessageId)
        } else if reason == .olderPage, let firstShown, let start = source.firstIndex(where: { $0.id == firstShown }) {
            current = start..<min(source.count, start + messages.count)
            destination = .older
        } else if !hasNewerMessages {
            destination = .latest
        } else {
            destination = firstShown.map { .preserve(firstMessage: $0) } ?? .latest
        }
        guard let range = ChatHistoryWindowPolicy.range(in: source, destination: destination, current: current) else { return }
        allMessages = source
        let embedded = PublicChatContent.attachEmbeds(to: Array(source[range]))
        embedRecords = PublicChatContent.mergingHydratedRecords(existing: embedRecords, inline: embedded.records)
        messages = embedded.messages
        visibleWindowStartIndex = range.lowerBound
        visibleWindowEndIndex = range.upperBound
        refreshWindowBoundaries()
        historyWindowRevision += 1
        isLoading = false
        coreBinding.painted = true
        resumeFirstWindowWaiter(nil)
        hydrateCoreEmbedsIfNeeded(chatId: chatId)
    }

    /// One streaming message: its row is patched in place, never re-merged.
    private func patchCoreMessage(_ mapped: Message, chatId: String) {
        coreBinding.messageIDs.insert(mapped.id)
        let embedded = PublicChatContent.attachEmbeds(to: [mapped])
        guard let message = embedded.messages.first else { return }
        if !embedded.records.isEmpty {
            embedRecords = PublicChatContent.mergingHydratedRecords(existing: embedRecords, inline: embedded.records)
        }
        let wasAtTail = !hasNewerMessages
        if let index = allMessages.firstIndex(where: { $0.id == message.id }) {
            allMessages[index] = message
        } else {
            allMessages.append(message)
        }
        if let index = messages.firstIndex(where: { $0.id == message.id }) {
            messages[index] = message
        } else if wasAtTail {
            messages.append(message)
            if messages.count > ChatHistoryWindowPolicy.capacity {
                messages.removeFirst(messages.count - ChatHistoryWindowPolicy.capacity)
            }
            visibleWindowEndIndex = allMessages.count
            visibleWindowStartIndex = max(0, allMessages.count - messages.count)
        }
        refreshWindowBoundaries()
        hydrateCoreEmbedsIfNeeded(chatId: chatId)
    }

    private func emptyCoreRows() {
        coreBinding.messageIDs = []
        allMessages = []
        messages = []
        visibleWindowStartIndex = 0
        visibleWindowEndIndex = 0
        refreshWindowBoundaries()
        historyWindowRevision += 1
    }

    /// Embed content still hydrates in Swift (core gap); only new references start it.
    private func hydrateCoreEmbedsIfNeeded(chatId: String) {
        let referenced = Set(messages.flatMap { $0.embedRefs?.map(\.id) ?? [] })
        guard !referenced.isSubset(of: coreBinding.hydratedEmbedIDs) else { return }
        coreBinding.hydratedEmbedIDs.formUnion(referenced)
        scheduleEmbedHydration(
            syncedEmbeds: chatStore?.embeds(for: chatId) ?? [],
            referencedIds: referenced,
            chatId: chatId,
            generation: loadGeneration,
            existingRecords: embedRecords,
            source: "coreWindow")
    }

    /// A synced header for the open core chat: messages stay the core's.
    func applySyncedHeaderToCoreWindow(_ synced: Chat, embeds: [EmbedRecord]) async {
        let token = coreBinding.token
        await ensureChatKey(for: synced)
        let header = await decryptMetadata(for: synced)
        let stored = await decryptFollowUpSuggestions(for: header)
        guard coreBinding.token == token, ownsCoreWindow(header.id) else { return }
        chat = header
        if header.encryptedFollowUpRequestSuggestions != nil {
            followUpSuggestions = ChatFollowUpSuggestionPolicy.restore(
                stored: stored, hasStoredCiphertext: true, legacyExtracted: [])
        }
        if !embeds.isEmpty { await applySyncedEmbeds(embeds) }
    }

    /// A push for the open core chat re-opens it in the core (cached window,
    /// then the strict read). True when the pushed reply is stored and complete.
    func refreshCoreWindowForNotification(chatID: String, messageID: String?,
                                          isCurrent: @escaping @MainActor () -> Bool) async -> Bool {
        guard !isLoading, isCurrent() else { return false }
        let request = coreWindow.begin(chatId: chatID)
        coreBinding.request = request
        let outcome = await coreWindow.open(request: request, chatId: chatID)
        guard outcome == .opened, isCurrent(), ownsCoreWindow(chatID) else { return false }
        if let messageID {
            let reply = coreWindow.message(id: messageID)
                ?? coreWindow.messages.last(where: { $0.serverMessageId == messageID })
            return reply.map { $0.isStreaming != true } ?? false
        }
        guard let reply = coreWindow.messages.last(where: { $0.role != .user }) else { return false }
        return reply.isStreaming != true
    }

    /// Row navigation for a core chat: older pages come from the core; every
    /// other move re-windows the rows already held.
    func loadCoreMessageWindow(_ destination: ChatHistoryWindowDestination) -> Task<Void, Never>? {
        guard !isLoading, !isLoadingOlder, let chatId = coreBinding.chatID else { return nil }
        if destination == .older, visibleWindowStartIndex < ChatHistoryWindowPolicy.stride, coreWindow.hasOlderMessages {
            explicitWindowNavigationGeneration += 1
            isLoadingOlder = true
            let token = coreBinding.token
            let window = coreWindow
            olderMessagesTask = Task { @MainActor [weak self] in
                // The merged window arrives as a `.olderPage` change.
                _ = await window.loadOlder()
                guard let self, self.coreBinding.token == token else { return }
                self.isLoadingOlder = false
                self.olderMessagesTask = nil
            }
            return olderMessagesTask
        }
        if destination == .older && !hasOlderMessages { return nil }
        if destination == .newer && !hasNewerMessages { return nil }
        let current = visibleWindowStartIndex..<visibleWindowEndIndex
        guard let next = ChatHistoryWindowPolicy.range(in: allMessages, destination: destination, current: current),
              next != current else { return nil }
        explicitWindowNavigationGeneration += 1
        let embedded = PublicChatContent.attachEmbeds(to: Array(allMessages[next]))
        embedRecords = PublicChatContent.mergingHydratedRecords(existing: embedRecords, inline: embedded.records)
        messages = embedded.messages
        visibleWindowStartIndex = next.lowerBound
        visibleWindowEndIndex = next.upperBound
        refreshWindowBoundaries()
        historyWindowRevision += 1
        hydrateCoreEmbedsIfNeeded(chatId: chatId)
        return Task { @MainActor in }
    }
}
