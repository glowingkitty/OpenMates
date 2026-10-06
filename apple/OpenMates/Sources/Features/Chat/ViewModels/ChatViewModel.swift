// Chat view model — manages messages, streaming, and embeds for a single chat.
// Mirrors the web app's dual-phase send protocol: WebSocket plaintext for AI
// processing, then client-encrypted metadata/messages for permanent storage.
// Subscribes to StreamingClient for real-time AI response chunks.
// Specification: specifications/features/message-input/specification.yml
// Assertions: message-input.embeds.gated-send, message-input.send.ownership, message-input.privacy-context, message-input.recording.lifecycle, message-input.drafts.preview-persistence
// Specification: specifications/features/chats/specification.yml
// Assertions: chats.followups.non-destructive-reconciliation, chats.persistence.client-encrypted, chats.streaming.progressive-presentation, chats.rendering.assistant-document-convergence, chats.surface.semantic-parity, chats.completion.pending-delivery, chats.message.identity-idempotent
// Specification: specifications/features/app-skills/code-run/specification.yml
// Assertions: code-run.output.chat-bound-encrypted
// Specification: specifications/features/pii-protection/specification.yml
// Assertions: pii.embed.owner-local-reveal-sync, pii.surface.semantic-parity

// Specification: specifications/features/apple-recent-offline-chats/specification.yml
// Assertions: apple-offline.recent-cohort, apple-offline.local-first, apple-offline.interruption-isolation, apple-offline.snapshot-integrity
// Specification: specifications/features/apple-live-activities/specification.yml
// Assertions: apple-live-activities.processing.widget, apple-live-activities.lifecycle.isolation

import Foundation
import SwiftUI
import CryptoKit
import Combine

enum ChatStreamingLifecyclePhase: Equatable {
    case idle
    case sending
    case processing
    case typing
    case thinking
    case streaming
    case queued
    case cancelling
    case completed
    case error
}

struct ChatStreamingLifecycleState: Equatable {
    var phase: ChatStreamingLifecyclePhase = .idle
    var chatId: String?
    var taskId: String?
    var messageId: String?
    var userMessageId: String?
    var preprocessingStep: String?
    var selectedMateCategory: String?
    var selectedMateName: String?
    var thinkingContent = ""
    var isThinkingStreaming = false
    var queuedMessageText: String?
    var errorMessage: String?
    private var lastSequenceByMessageId: [String: Int] = [:]
    private var completedMessageIds = Set<String>()

    var isActive: Bool {
        switch phase {
        case .idle, .completed, .error:
            return false
        case .sending, .processing, .typing, .thinking, .streaming, .queued, .cancelling:
            return true
        }
    }

    var shouldShowProcessingDetails: Bool {
        phase == .processing && preprocessingStep != nil
    }

    var shouldShowThinkingDetails: Bool {
        isThinkingStreaming || !thinkingContent.isEmpty
    }

    @discardableResult
    mutating func apply(_ event: StreamingClient.StreamEvent) -> Bool {
        switch event {
        case .taskInitiated(let chatId, let taskId, let userMessageId):
            reset()
            self.chatId = chatId
            self.taskId = taskId
            self.userMessageId = userMessageId.isEmpty ? nil : userMessageId
            phase = .sending
            errorMessage = nil

        case .preprocessingStep(let chatId, let step, let data):
            self.chatId = chatId
            preprocessingStep = step
            if step == "mate_selected" {
                selectedMateCategory = data?["mate_category"] as? String
                selectedMateName = data?["mate_name"] as? String
            }
            phase = .processing

        case .typingStarted(let chatId, let messageId, let metadata):
            self.chatId = chatId
            self.messageId = messageId
            selectedMateCategory = metadata?.category
            selectedMateName = nil
            if let userMessageId = metadata?.userMessageId, !userMessageId.isEmpty {
                self.userMessageId = userMessageId
            }
            phase = .typing

        case .thinkingChunk(let chatId, let messageId, let content):
            self.chatId = chatId
            if self.messageId != messageId {
                thinkingContent = ""
            }
            self.messageId = messageId
            thinkingContent += content
            isThinkingStreaming = true
            phase = .thinking

        case .thinkingComplete(let chatId, let messageId):
            self.chatId = chatId
            self.messageId = messageId
            isThinkingStreaming = false
            if phase == .thinking {
                phase = .typing
            }

        case .chunk(let chatId, let messageId, let sequence, _, let isFinal, let userMessageId, let category, _, _):
            guard !completedMessageIds.contains(messageId) else { return false }
            if !isFinal {
                if let lastSequence = lastSequenceByMessageId[messageId], sequence <= lastSequence {
                    return false
                }
                lastSequenceByMessageId[messageId] = sequence
            }
            self.chatId = chatId
            self.messageId = messageId
            if let category { selectedMateCategory = category }
            if let userMessageId, !userMessageId.isEmpty {
                self.userMessageId = userMessageId
            }
            phase = isFinal ? .completed : .streaming
            if isFinal {
                completedMessageIds.insert(messageId)
                isThinkingStreaming = false
            }

        case .messageReady(let chatId, let messageId):
            guard let activeMessageId = self.messageId ?? taskId, messageId == activeMessageId else {
                return false
            }
            self.chatId = chatId
            self.messageId = messageId
            completedMessageIds.insert(messageId)
            phase = .completed
            isThinkingStreaming = false
            queuedMessageText = nil

        case .typingEnded(let chatId, let messageId):
            self.chatId = chatId
            if phase == .streaming, messageId == nil {
                return false
            }
            if let messageId, let activeMessageId = self.messageId, messageId != activeMessageId {
                return false
            }
            if let messageId { self.messageId = messageId }
            if phase == .typing || phase == .thinking || phase == .processing || phase == .streaming {
                phase = .completed
                if let completedMessageId = self.messageId {
                    completedMessageIds.insert(completedMessageId)
                }
            }
            isThinkingStreaming = false
            queuedMessageText = nil

        case .messageQueued(let chatId, let taskId, let userMessageId, let message):
            if let activeTaskId = self.taskId, taskId != activeTaskId {
                return false
            }
            self.chatId = chatId
            self.taskId = taskId ?? self.taskId
            self.userMessageId = userMessageId ?? self.userMessageId
            queuedMessageText = message
            phase = .queued

        case .cancelRequested(let chatId, let taskId):
            if let activeTaskId = self.taskId, taskId != activeTaskId {
                return false
            }
            self.chatId = chatId
            self.taskId = taskId ?? self.taskId
            phase = .cancelling
            isThinkingStreaming = false
            queuedMessageText = nil

        case .postProcessingCompleted(let chatId, let taskId, _, _, _, _, _, _, _):
            if let activeTaskId = self.taskId, taskId != activeTaskId {
                return false
            }
            self.chatId = chatId
            self.taskId = taskId
            phase = .completed
            queuedMessageText = nil

        case .error(let message):
            phase = .error
            errorMessage = message
            isThinkingStreaming = false
            queuedMessageText = nil
        }
        return true
    }

    mutating func reset() {
        self = ChatStreamingLifecycleState()
    }

    mutating func completeFromAuthoritativeSync(messageId authoritativeMessageId: String) -> Bool {
        // Before the first typing frame, the server task ID is the only known
        // assistant identity (the web completed-message handler uses the same
        // equality). Once typing identifies a message, it takes precedence.
        guard (messageId ?? taskId) == authoritativeMessageId else { return false }
        messageId = authoritativeMessageId
        completedMessageIds.insert(authoritativeMessageId)
        phase = .completed
        isThinkingStreaming = false
        queuedMessageText = nil
        return true
    }
}

/// A saved terminal row can finish only its exact current request/message.
/// Pending recovery ciphertext and optimistic plaintext are not server receipts.
enum ChatStreamingSyncCompletionPolicy {
    static func retainedForegroundMessages(_ current: [Message], incoming: [Message],
                                          lifecycle: ChatStreamingLifecycleState, chatID: String,
                                          pendingMessageIDs: Set<String>) -> [Message] {
        guard let terminal = matchingMessage(in: incoming, lifecycle: lifecycle,
            chatID: chatID, pendingMessageIDs: pendingMessageIDs) else { return current }
        let terminalIDs = Set([terminal.id, terminal.serverMessageId].compactMap { $0 })
        // Admit the exact saved terminal through the window merger's normal
        // protection of live rows. Preserve every other pending/streaming turn.
        return current.filter { row in
            !terminalIDs.contains(row.id) && !(row.serverMessageId.map(terminalIDs.contains) ?? false)
        }
    }

    static func matchingMessage(in messages: [Message], lifecycle: ChatStreamingLifecycleState,
                                chatID: String, pendingMessageIDs: Set<String>) -> Message? {
        guard lifecycle.chatId == chatID, lifecycle.isActive,
              let activeID = lifecycle.messageId ?? lifecycle.taskId else { return nil }
        return messages.first { message in
            message.chatId == chatID
                && (message.id == activeID || message.serverMessageId == activeID)
                && (message.role == .assistant || message.role == .system)
                && message.isStreaming != true
                && message.encryptedContent?.isEmpty == false
                && !pendingMessageIDs.contains(message.id)
                && !(message.serverMessageId.map(pendingMessageIDs.contains) ?? false)
        }
    }
}

enum ChatStreamingPresentationPolicy {
    static func shouldMaterializeAssistant(
        content: String,
        thinkingContent: String,
        embedCount: Int
    ) -> Bool {
        !ChatMessageStreamingRenderPolicy.visibleContent(content)
            .trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
            || !thinkingContent.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
            || embedCount > 0
    }
}

enum ChatLegacyEmbedLinkPolicy {
    static func applying(
        to messages: [Message],
        embeds: [EmbedRecord],
        synthesizeMissingContent: Bool = true
    ) -> [Message] {
        guard !messages.isEmpty, !embeds.isEmpty else { return messages }
        let embedsByMessageHash = Dictionary(grouping: embeds.compactMap { embed in
            embed.hashedMessageId.map { ($0, embed) }
        }, by: { $0.0 })
        guard !embedsByMessageHash.isEmpty else { return messages }

        return messages.map { message in
            guard message.role == .user else { return message }
            // Web `sendersChatMessages.ts` uses computeSHA256(message_id), and
            // backend `embed_service.py` uses sha256(message_id.encode()).
            let digest = SHA256.hash(data: Data(message.id.utf8))
                .map { String(format: "%02x", $0) }
                .joined()
            let linked = embedsByMessageHash[digest]?.map { $0.1 } ?? []
            guard !linked.isEmpty else { return message }
            let existing = message.embedRefs ?? []
            let existingIDs = Set(existing.map(\.id))
            let recovered = linked
                .filter { !existingIDs.contains($0.id) }
                .map { EmbedRef(id: $0.id, type: $0.type, status: $0.status.rawValue, data: nil) }
            let linkedRefs = linked.map {
                EmbedRef(id: $0.id, type: $0.type, status: $0.status.rawValue, data: nil)
            }
            let contentIsEmpty = (message.content ?? "")
                .trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
            guard !recovered.isEmpty || (synthesizeMissingContent && contentIsEmpty) else {
                return message
            }
            let recoveredContent: String?
            if synthesizeMissingContent && contentIsEmpty {
                recoveredContent = linkedRefs.map { ref in
                    "```json\n{\"type\": \"\(ref.type)\", \"embed_id\": \"\(ref.id)\"}\n```"
                }.joined(separator: "\n\n")
            } else {
                recoveredContent = message.content
            }
            return Message(
                id: message.id, chatId: message.chatId, role: message.role,
                content: recoveredContent, encryptedContent: message.encryptedContent,
                createdAt: message.createdAt, updatedAt: message.updatedAt,
                appId: message.appId, isStreaming: message.isStreaming,
                embedRefs: existing + recovered, modelName: message.modelName,
                senderName: message.senderName, category: message.category,
                encryptedSenderName: message.encryptedSenderName,
                encryptedCategory: message.encryptedCategory,
                encryptedModelName: message.encryptedModelName,
                piiMappings: message.piiMappings,
                encryptedPIIMappings: message.encryptedPIIMappings,
                thinkingContent: message.thinkingContent,
                encryptedThinkingContent: message.encryptedThinkingContent,
                encryptedThinkingSignature: message.encryptedThinkingSignature,
                thinkingTokenCount: message.thinkingTokenCount, serverMessageId: message.serverMessageId
            )
        }
    }
}

enum ChatGeneratedMetadataPolicy {
    static func applying(_ metadata: StreamingClient.ChatMetadata, to chat: Chat) -> Chat {
        let title = metadata.title?.trimmingCharacters(in: .whitespacesAndNewlines)
        let category = metadata.category?.trimmingCharacters(in: .whitespacesAndNewlines)
        let icon = metadata.iconNames.first?.trimmingCharacters(in: .whitespacesAndNewlines)
        let metadataIsUninitialized = needsGeneratedTitle(chat)
        return Chat(
            id: chat.id,
            title: metadataIsUninitialized && title?.isEmpty == false ? title : chat.title,
            lastMessageAt: chat.lastMessageAt,
            createdAt: chat.createdAt,
            updatedAt: chat.updatedAt,
            lastEditedOverallTimestamp: chat.lastEditedOverallTimestamp,
            isArchived: chat.isArchived,
            isPinned: chat.isPinned,
            appId: chat.appId,
            category: metadataIsUninitialized && category?.isEmpty == false ? category : chat.category,
            icon: metadataIsUninitialized && icon?.isEmpty == false ? icon : chat.icon,
            chatSummary: chat.chatSummary,
            encryptedTitle: chat.encryptedTitle,
            encryptedCategory: chat.encryptedCategory,
            encryptedIcon: chat.encryptedIcon,
            encryptedChatSummary: chat.encryptedChatSummary,
            encryptedFollowUpRequestSuggestions: chat.encryptedFollowUpRequestSuggestions,
            encryptedAutoSpeakResponse: chat.encryptedAutoSpeakResponse,
            encryptedChatKey: metadata.encryptedChatKey ?? chat.encryptedChatKey,
            messagesV: chat.messagesV,
            titleV: chat.titleV,
            draftV: chat.draftV,
            metadataV: chat.metadataV,
            lastVisibleMessageId: chat.lastVisibleMessageId,
            parentId: chat.parentId,
            isSubChat: chat.isSubChat,
            subChatSettings: chat.subChatSettings,
            budgetLimit: chat.budgetLimit,
            budgetSpent: chat.budgetSpent,
            encryptedFocusPhaseState: chat.encryptedFocusPhaseState,
            encryptedActiveFocusId: chat.encryptedActiveFocusId,
            activeFocusId: chat.activeFocusId
        )
    }

    static func needsGeneratedTitle(_ chat: Chat) -> Bool {
        let visibleTitle = chat.title?.trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
        return (chat.titleV ?? 0) == 0 || visibleTitle.isEmpty
    }

    static func applyingProvisionalTitle(_ title: String?, to chat: Chat) -> Chat {
        let currentTitle = chat.title?.trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
        guard currentTitle.isEmpty, (chat.titleV ?? 0) == 0,
              let title, !title.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else {
            return chat
        }
        return Chat(
            id: chat.id,
            title: title,
            lastMessageAt: chat.lastMessageAt,
            createdAt: chat.createdAt,
            updatedAt: chat.updatedAt,
            lastEditedOverallTimestamp: chat.lastEditedOverallTimestamp,
            isArchived: chat.isArchived,
            isPinned: chat.isPinned,
            appId: chat.appId,
            category: chat.category,
            icon: chat.icon,
            chatSummary: chat.chatSummary,
            encryptedTitle: chat.encryptedTitle,
            encryptedCategory: chat.encryptedCategory,
            encryptedIcon: chat.encryptedIcon,
            encryptedChatSummary: chat.encryptedChatSummary,
            encryptedFollowUpRequestSuggestions: chat.encryptedFollowUpRequestSuggestions,
            encryptedAutoSpeakResponse: chat.encryptedAutoSpeakResponse,
            encryptedChatKey: chat.encryptedChatKey,
            messagesV: chat.messagesV,
            titleV: chat.titleV,
            draftV: chat.draftV,
            metadataV: chat.metadataV,
            lastVisibleMessageId: chat.lastVisibleMessageId,
            parentId: chat.parentId,
            isSubChat: chat.isSubChat,
            subChatSettings: chat.subChatSettings,
            budgetLimit: chat.budgetLimit,
            budgetSpent: chat.budgetSpent,
            encryptedFocusPhaseState: chat.encryptedFocusPhaseState,
            encryptedActiveFocusId: chat.encryptedActiveFocusId,
            activeFocusId: chat.activeFocusId
        )
    }
}

struct ChatEncryptedMetadataAcceptedVersions: Equatable {
    let messages: Int?
    let title: Int?
    let metadata: Int?
}

enum ChatEncryptedMetadataAcknowledgementPolicy {
    static func acceptedVersions(from fields: [String: Any]) -> ChatEncryptedMetadataAcceptedVersions? {
        guard fields["status"] as? String == "queued_for_storage" else { return nil }
        let versions = fields["versions"] as? [String: Any]
        return ChatEncryptedMetadataAcceptedVersions(
            messages: versions?["messages_v"] as? Int,
            title: versions?["title_v"] as? Int,
            metadata: versions?["metadata_v"] as? Int
        )
    }
}

enum ChatFollowUpSuggestionPolicy {
    static func clearForAcceptedSend(_ current: [String]) -> [String] {
        current.isEmpty ? current : []
    }

    static func reconcile(current: [String], incoming: [String]) -> [String] {
        incoming.isEmpty ? current : incoming
    }

    static func acceptCompletedResponse(_ incoming: [String]) -> [String] {
        Array(incoming.prefix(18))
    }

    static func restore(stored: [String], hasStoredCiphertext: Bool, legacyExtracted: [String]) -> [String] {
        hasStoredCiphertext ? stored : reconcile(current: stored, incoming: legacyExtracted)
    }
}

enum ChatOpeningFallbackPolicy {
    static func shouldFetchMissingSyncedMessages(messagesV: Int?, lastMessageAt: String?) -> Bool {
        if let messagesV, messagesV > 0 {
            return true
        }
        return lastMessageAt != nil
    }
}

private enum ChatContentHydrationError: Error, Equatable {
    case websocketUnavailable
    case invalidResponse
}

/// One policy for cold loads, cached seeds, paging, and direct navigation.
/// The raw history remains separate from the bounded SwiftUI message rows.
enum ChatHistoryWindowDestination: Equatable {
    case initial(anchor: String?)
    case preserve(firstMessage: String)
    case older, newer, oldest, latest
    case message(String)
}

enum ChatHistoryWindowPolicy {
    static let capacity = 50
    static let overlap = 10
    static let stride = capacity - overlap

    static func orderedUnique(_ messages: [Message]) -> [Message] {
        // Synced/cached history is usually already canonical. Preserve its array
        // storage instead of rebuilding and sorting the complete history.
        var seenIDs = Set<String>()
        seenIDs.reserveCapacity(messages.count)
        var previousCreatedAt: String?
        var isOrderedUnique = true
        for message in messages {
            if !seenIDs.insert(message.id).inserted
                || previousCreatedAt.map({ $0 > message.createdAt }) == true {
                isOrderedUnique = false
                break
            }
            previousCreatedAt = message.createdAt
        }
        if isOrderedUnique { return messages }

        var byID: [String: Message] = [:]
        var firstPosition: [String: Int] = [:]
        for (index, message) in messages.enumerated() {
            if firstPosition[message.id] == nil { firstPosition[message.id] = index }
            byID[message.id] = message
        }
        return byID.values.sorted {
            $0.createdAt == $1.createdAt
                ? firstPosition[$0.id, default: 0] < firstPosition[$1.id, default: 0]
                : $0.createdAt < $1.createdAt
        }
    }

    static func range(in messages: [Message], destination: ChatHistoryWindowDestination,
                      current: Range<Int> = 0..<0) -> Range<Int>? {
        guard !messages.isEmpty else { return 0..<0 }
        let maximumStart = max(0, messages.count - capacity)
        let requestedStart: Int
        switch destination {
        case .oldest: requestedStart = 0
        case .latest: requestedStart = maximumStart
        case .older: requestedStart = max(0, current.lowerBound - stride)
        case .newer: requestedStart = min(maximumStart, current.lowerBound + stride)
        case .initial(let anchor):
            requestedStart = anchor.flatMap { id in messages.firstIndex { $0.id == id } }
                .map { max(0, $0 - 8) } ?? maximumStart
        case .preserve(let id):
            requestedStart = messages.firstIndex { $0.id == id } ?? min(current.lowerBound, maximumStart)
        case .message(let id):
            guard let index = messages.firstIndex(where: { $0.id == id }) else { return nil }
            requestedStart = max(0, index - 8)
        }
        let start = min(maximumStart, requestedStart)
        return start..<min(messages.count, start + capacity)
    }

    static func initialMessages(_ messages: [Message], anchor: String?) -> [Message] {
        let ordered = orderedUnique(messages)
        let range = range(in: ordered, destination: .initial(anchor: anchor)) ?? 0..<0
        return Array(ordered[range])
    }
}

/// A history refresh updates rows, not the lifetime of the chat's live reader.
/// Replaying terminal snapshots on every metadata ACK can otherwise resend
/// post-processing metadata and create an ACK -> reload -> replay feedback loop.
struct ChatStreamSubscriptionIdentity {
    private var current: (chatID: String, session: StreamingSessionGeneration, token: UUID)?

    mutating func begin(chatID: String, session: StreamingSessionGeneration) -> UUID? {
        if let current, current.chatID == chatID, current.session == session { return nil }
        let token = UUID()
        current = (chatID, session, token)
        return token
    }

    mutating func finish(_ token: UUID) {
        guard current?.token == token else { return }
        current = nil
    }

    mutating func invalidate() { current = nil }
}

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
    @Published private(set) var streamingLifecycle = ChatStreamingLifecycleState()
    @Published var followUpSuggestions: [String] = []
    @Published var error: String?
    @Published private(set) var openingMetrics = ChatOpeningMetrics()
    @Published private(set) var pendingComposerEmbeds: [ComposerPendingEmbed] = []
    @Published var subChatApprovalRequest: SubChatApprovalRequest?
    @Published var subChatProgress: SubChatProgress?
    @Published var completedSubChatIDs = Set<String>()
    private struct PendingSubChatSpawn {
        let eventID: UUID
        let child: SpawnedSubChat
        let parentID: String
        let accountScope: UUID
        let keyGeneration: UUID
    }
    private var pendingSubChatSpawns: [String: PendingSubChatSpawn] = [:]
    private var pendingSubChatCompletions: [String: (scope: UUID, payload: SubChatCompletion)] = [:]
    private var isFlushingSubChatSpawns = false
    private var subChatTransportObserver: AnyCancellable?
    nonisolated(unsafe) private var subChatKeyObserver: Any?

    var hasPendingComposerEmbeds: Bool {
        !pendingComposerEmbeds.isEmpty
    }

    /// Loaded history: a full local snapshot or the bounded remote pages visited.
    private var allMessages: [Message] = []
    /// The scope that supplied saved rows is also the completion authority.
    /// Buffered events must not borrow old history after a session/owner switch.
    private var rawHistoryReadFence: RemoteReadFence?
    private struct RemoteHistory {
        let chatId: String
        var start: ChatMessageWindowCursor?
        var end: ChatMessageWindowCursor?
        var hasOlder: Bool
        var hasNewer: Bool
        init(_ page: ChatMessageWindowPage) {
            chatId = page.chatId; start = page.startCursor; end = page.endCursor
            hasOlder = page.hasMoreBefore; hasNewer = page.hasMoreAfter
        }
    }
    private var remoteHistory: RemoteHistory?
    private var failedRemoteWindowRequest: Int?
    private var foregroundDeletionRevision = 0
    private var deletedForegroundMessageIds = Set<String>()
    /// Index in `allMessages` where the currently-rendered message window starts.
    private var visibleWindowStartIndex = 0
    private var visibleWindowEndIndex = 0
    private(set) var windowRequestGeneration = 0
    private var explicitWindowNavigationGeneration = 0
    @Published private(set) var hasNewerMessages = false
    @Published private(set) var newerMessageCount = 0
    @Published private(set) var historyWindowRevision = 0
    /// Whether there are older messages above the currently visible window.
    @Published var hasOlderMessages = false
    @Published var isLoadingOlder = false

    #if DEBUG
    var historyWindowAccessibilityValue: String {
        "rendered=\(messages.count);total=\(allMessages.count);first=\(messages.first?.id ?? "");last=\(messages.last?.id ?? "");oldest=\(allMessages.first?.id ?? "");latest=\(allMessages.last?.id ?? "");older=\(hasOlderMessages);newer=\(hasNewerMessages);newer-count=\(newerMessageCount);revision=\(historyWindowRevision)"
    }
    #endif

    private let api = APIClient.shared
    private let sendPipeline = ChatSendPipeline()
    private weak var wsManager: WebSocketManager?
    private weak var chatStore: ChatStore?
    private var queuedMessageClearTask: Task<Void, Never>?
    private var streamTask: Task<Void, Never>?
    private var streamSubscriptionIdentity = ChatStreamSubscriptionIdentity()
    private var embedHydrationTask: Task<Void, Never>?
    private var embedContentBatchRequest: (chatId: String, generation: Int, scope: UUID,
        id: UUID, task: Task<ChatContentBatchPayload, Error>)?
    private let contentBatchFetcher: (@MainActor (String) async throws -> ChatContentBatchPayload)?
    private let messageWindowFetcher: @MainActor (String, String?, ChatMessageWindowQuery) async throws -> ChatMessageWindowPage
    private var olderMessagesTask: Task<Void, Never>?
    private var loadGeneration = 0
    private let messageDecryptor: @MainActor ([Message], String) async -> [Message]
    private let accountScopeGeneration: @MainActor () -> UUID
    private let offlineStore: OfflineStore
    private let processingCoordinator: ActiveChatsCoordinator
    private var diskHistoryChatID: String?
    private var diskHasOlderMessages = false
    private var diskHasNewerMessages = false
    private var diskNewerMessageCount = 0
    private var userMessageIdByAssistantMessageId: [String: String] = [:]
    private var assistantMessageCreatedAtById: [String: String] = [:]
    private var assistantCategoryByMessageId: [String: String] = [:]
    private var assistantModelNameByMessageId: [String: String] = [:]
    private var anonymousFeatureNoticeInserted = false
    nonisolated(unsafe) private var embedRefreshObserver: Any?
    nonisolated(unsafe) private var chatLifecycleObserver: Any?

    init(
        messageDecryptor: @escaping @MainActor ([Message], String) async -> [Message] = {
            await ChatViewModel.decryptMessagesForDisplay($0, chatId: $1)
        },
        accountScopeGeneration: @escaping @MainActor () -> UUID = { OfflineStore.shared.scopeGeneration },
        contentBatchFetcher: (@MainActor (String) async throws -> ChatContentBatchPayload)? = nil,
        offlineStore: OfflineStore = .shared,
        processingCoordinator: ActiveChatsCoordinator = .shared,
        messageWindowFetcher: @escaping @MainActor (String, String?, ChatMessageWindowQuery) async throws -> ChatMessageWindowPage = {
            try await ChatMessageWindowClient.fetch(chatId: $0, teamId: $1, query: $2)
        }
    ) {
        #if DEBUG
        if ProcessInfo.processInfo.arguments.contains("--ui-test-delayed-visible-window") {
            self.messageDecryptor = { rows, chatID in
                try? await Task.sleep(for: .seconds(2))
                return await messageDecryptor(rows, chatID)
            }
        } else {
            self.messageDecryptor = messageDecryptor
        }
        #else
        self.messageDecryptor = messageDecryptor
        #endif
        self.accountScopeGeneration = accountScopeGeneration
        self.offlineStore = offlineStore
        self.processingCoordinator = processingCoordinator
        self.messageWindowFetcher = messageWindowFetcher
        #if DEBUG
        let args = ProcessInfo.processInfo.arguments
        if contentBatchFetcher == nil, args.contains("--ui-test-authenticated-chat-navigation"),
           args.contains("--ui-test-sheet-reference-hydration") {
            self.contentBatchFetcher = { chatId in
                guard chatId == "ui-test-current-chat" else { throw ChatContentHydrationError.invalidResponse }
                let record = EmbedRecord(id: "ui-test-sheet-reference", type: "sheet", status: .finished,
                    data: .raw(["table": AnyCodable("| Item | Count |\n|---|---|\n| Saved Row A | 1 |\n| Saved Row B | 2 |"),
                                "row_count": AnyCodable(2), "col_count": AnyCodable(2)]),
                    parentEmbedId: nil, appId: "sheets", skillId: "sheet", embedIds: nil,
                    hashedChatId: ChatKeyWrapperRecord.hashedChatId(for: chatId), createdAt: nil)
                return ChatContentBatchPayload(messagesByChatId: [chatId: []], versionsByChatId: [:],
                    embeds: [record], embedKeys: [], chatKeyWrappers: [], codeRunOutputs: nil)
            }
        } else {
            self.contentBatchFetcher = contentBatchFetcher
        }
        #else
        self.contentBatchFetcher = contentBatchFetcher
        #endif
    }

    func configure(wsManager: WebSocketManager?, chatStore: ChatStore?) {
        self.wsManager = wsManager
        self.chatStore = chatStore
        subChatTransportObserver = wsManager?.$connectionState.sink { [weak self] state in
            guard state == .connected else { return }
            Task { @MainActor [weak self] in
                await self?.flushPendingSubChatSpawns()
                await self?.flushPendingSubChatCompletions()
                // An offline-opened reference must retry when its content
                // transport returns, even when its placeholder ID was loaded.
                await self?.retryVisibleEmbedHydration()
            }
        }
        if subChatKeyObserver == nil {
            subChatKeyObserver = NotificationCenter.default.addObserver(
                forName: .chatKeyMaterialAvailable, object: nil, queue: .main
            ) { [weak self] notification in
                guard let expectedScope = notification.userInfo?["accountScope"] as? UUID else { return }
                Task { @MainActor [weak self] in
                    guard let self, self.accountScopeGeneration() == expectedScope else { return }
                    await self.flushPendingSubChatSpawns()
                    await self.flushPendingSubChatCompletions()
                }
            }
        }
    }

    var isSendTransportReady: Bool { wsManager?.connectionState == .connected }

    func loadChat(id: String, initialChat: Chat? = nil, initialMessages: [Message] = [], initialEmbeds: [EmbedRecord] = []) async {
        loadGeneration += 1
        let generation = loadGeneration
        remoteHistory = nil
        failedRemoteWindowRequest = nil
        deletedForegroundMessageIds.removeAll()
        let readFence = remoteReadFence(chatId: id, generation: generation)
        diskHistoryChatID = nil
        diskHasOlderMessages = false
        diskHasNewerMessages = false
        diskNewerMessageCount = 0
        followUpSuggestions = []
        cancelOlderMessagesLoad()
        embedHydrationTask?.cancel()
        embedContentBatchRequest?.task.cancel()
        embedContentBatchRequest = nil
        isLoading = true
        error = nil

        if loadPublicChat(id: id) {
            isLoading = false
            return
        }

        if let initialChat = initialChat ?? chatStore?.chat(for: id) ?? offlineStore.loadChat(id: id) {
            await loadSyncedChat(initialChat, messages: initialMessages, embeds: initialEmbeds, generation: generation)
            return
        }

        do {
            var loadedChat: Chat = try await api.request(.get, path: "/v1/chats/\(id)")

            // Ensure chat key is loaded (may not be if chat was opened via deep link)
            await ensureChatKey(for: loadedChat)

            loadedChat = await decryptMetadata(for: loadedChat)
            let storedFollowUps = await decryptFollowUpSuggestions(for: loadedChat)
            guard isCurrentRemoteRead(readFence) else { return }
            chat = loadedChat

            let page = try await fetchRemoteWindow(chatId: id, teamId: loadedChat.teamId,
                query: initialRemoteQuery(anchor: loadedChat.lastVisibleMessageId), generation: generation)
            guard generation == loadGeneration else { return }
            remoteHistory = RemoteHistory(page)
            allMessages = mergeForegroundMessages(foregroundPageMessages(page), preserving: chatStore?.messages(for: id) ?? [], chatId: id)
            rawHistoryReadFence = readFence
            let visibleRawMessages = visibleWindow(from: allMessages, anchorMessageId: loadedChat.lastVisibleMessageId)
            let decryptedMessages = await decryptMessages(visibleRawMessages, chatId: id)
            guard isCurrentRemoteRead(readFence) else { return }
            let embedded = PublicChatContent.attachEmbeds(to: decryptedMessages)
            embedRecords = embedded.records
            followUpSuggestions = ChatFollowUpSuggestionPolicy.restore(
                stored: storedFollowUps,
                hasStoredCiphertext: loadedChat.encryptedFollowUpRequestSuggestions != nil,
                legacyExtracted: extractFollowUpSuggestions(from: embedded.messages)
            )

            messages = embedded.messages
            refreshWindowBoundaries()
            historyWindowRevision += 1

            // Start listening for streaming events and embed updates
            subscribeToStream(chatId: id)
            subscribeToEmbedUpdates(chatId: id)
            subscribeToChatLifecycle(chatId: id)
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
            guard isCurrentRemoteRead(readFence) else { return }
            self.error = error is ChatMessageWindowError ? AppStrings.genericProcessingError : error.localizedDescription
            isLoading = false
        }
    }

    func applySynced(chat syncedChat: Chat?, messages syncedMessages: [Message], embeds syncedEmbeds: [EmbedRecord] = []) async {
        guard let currentId = chat?.id else { return }
        if let syncedChat, syncedChat.id != currentId { return }
        if !syncedMessages.isEmpty && syncedMessages.allSatisfy({ $0.chatId != currentId }) { return }
        let nextChat = syncedChat ?? chat
        guard let nextChat else { return }
        let destination: ChatHistoryWindowDestination = hasNewerMessages
            ? messages.first.map { .preserve(firstMessage: $0.id) } ?? .latest
            : .latest
        loadGeneration += 1
        let generation = loadGeneration
        cancelOlderMessagesLoad()
        embedHydrationTask?.cancel()
        await loadSyncedChat(nextChat, messages: syncedMessages.isEmpty ? allMessages : syncedMessages,
                             embeds: syncedEmbeds, generation: generation, destination: destination)
    }

    func applySyncedEmbeds(_ syncedEmbeds: [EmbedRecord]) async {
        guard let chatId = chat?.id, !messages.isEmpty, !syncedEmbeds.isEmpty else { return }
        messages = ChatLegacyEmbedLinkPolicy.applying(to: messages, embeds: syncedEmbeds)
        allMessages = ChatLegacyEmbedLinkPolicy.applying(
            to: allMessages,
            embeds: syncedEmbeds,
            synthesizeMissingContent: false
        )
        let referencedIds = Set(messages.flatMap { $0.embedRefs?.map(\.id) ?? [] })
        guard !referencedIds.isEmpty else { return }
        let currentRecords = embedRecords
        let incomingRecords = EmbedRecord.dictionaryById(syncedEmbeds, context: "chatViewModel.applySyncedEmbeds.incoming")
        let changedEmbeds = incomingRecords.values.filter { incoming in
            guard let existing = currentRecords[incoming.id] else { return true }
            return Self.embedRecordNeedsRefresh(existing: existing, incoming: incoming)
        }
        guard !changedEmbeds.isEmpty else { return }
        let mergedRecords = PublicChatContent.mergingHydratedRecords(existing: currentRecords, inline: incomingRecords)
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

    private func loadSyncedChat(_ syncedChat: Chat, messages syncedMessages: [Message], embeds syncedEmbeds: [EmbedRecord],
                                generation: Int, destination: ChatHistoryWindowDestination? = nil) async {
        let scopeGeneration = accountScopeGeneration()
        let readFence = remoteReadFence(chatId: syncedChat.id, generation: generation)
        var loadedChat = syncedChat
        let start = NativeSyncPerfLog.now()
        if loadedChat.encryptedChatKey == nil, let cachedChat = offlineStore.loadChat(id: loadedChat.id) {
            await ensureChatKey(for: cachedChat)
        }
        await ensureChatKey(for: loadedChat)
        loadedChat = await decryptMetadata(for: loadedChat)
        let storedFollowUps = await decryptFollowUpSuggestions(for: loadedChat)
        guard isCurrentRemoteRead(readFence) else { return }
        if NativeSyncPerfLog.verboseCrypto {
            print("[ChatViewModel][loadSynced] chat=\(loadedChat.id.prefix(8)) afterMetadata title=\(loadedChat.title != nil) category=\(loadedChat.category != nil) icon=\(loadedChat.icon != nil) summary=\(loadedChat.chatSummary != nil) hasKey=\(ChatKeyManager.shared.hasKey(for: loadedChat.id))")
        }

        chat = loadedChat
        let initialFollowUpSuggestions = ChatFollowUpSuggestionPolicy.restore(
            stored: storedFollowUps,
            hasStoredCiphertext: loadedChat.encryptedFollowUpRequestSuggestions != nil,
            legacyExtracted: followUpSuggestions
        )
        // A warm shell supplies a bounded seed, while its store retains the raw
        // history. Never mistake that seed for the complete paging/send source.
        if offlineStore.hasCompleteOfflineSnapshot(for: loadedChat) { remoteHistory = nil }
        let storedMessages = chatStore?.messages(for: loadedChat.id) ?? []
        var rawMessages = ChatHistoryWindowPolicy.orderedUnique(
            storedMessages.isEmpty ? syncedMessages : storedMessages)
        if remoteHistory?.chatId == loadedChat.id {
            rawMessages = mergeForegroundMessages(rawMessages, preserving: allMessages, chatId: loadedChat.id)
        }
        var hydrationEmbeds = syncedEmbeds
        if rawMessages.isEmpty {
            rawMessages = offlineStore.loadLatestMessageWindow(chatId: loadedChat.id)
        }
        if !rawMessages.isEmpty && remoteHistory == nil {
            let diskEmbeds = offlineStore.loadEmbeds(chatId: loadedChat.id)
            hydrationEmbeds = Array(EmbedRecord.dictionaryById(diskEmbeds, context: "offlineChatOpen")
                .merging(EmbedRecord.dictionaryById(syncedEmbeds, context: "offlineChatOpenSynced")) { _, synced in synced }.values)
            diskHistoryChatID = loadedChat.id
            refreshDiskHistoryBoundaries(rawMessages, chatId: loadedChat.id)
        }
        if rawMessages.isEmpty && shouldFetchMissingSyncedMessages(for: loadedChat) {
            do {
                let page = try await fetchRemoteWindow(chatId: loadedChat.id, teamId: loadedChat.teamId,
                    query: initialRemoteQuery(anchor: loadedChat.lastVisibleMessageId), generation: generation)
                guard generation == loadGeneration, chat?.id == loadedChat.id,
                      scopeGeneration == accountScopeGeneration() else { return }
                remoteHistory = RemoteHistory(page)
                rawMessages = mergeForegroundMessages(foregroundPageMessages(page),
                    preserving: chatStore?.messages(for: loadedChat.id) ?? [], chatId: loadedChat.id)
                // Foreground pages remain in this reader. Sending them through
                // the full-sync bridge would invalidate the 20-chat cohort or
                // mistake this partial response for complete content coverage.
            } catch {
                guard generation == loadGeneration, scopeGeneration == accountScopeGeneration() else { return }
                if let hydrationError = error as? ChatContentHydrationError {
                    self.error = hydrationError == .websocketUnavailable
                        ? AppStrings.reconnecting
                        : AppStrings.genericProcessingError
                } else {
                    self.error = error is ChatMessageWindowError ? AppStrings.genericProcessingError : error.localizedDescription
                }
                isLoading = false
                NativeSyncPerfLog.warning(
                    "phase=loadSyncedChatContentBatchFailed chat=\(loadedChat.id.prefix(8)) error=\(error.localizedDescription)"
                )
                return
            }
            guard generation == loadGeneration else { return }
        }
        openingMetrics.initialMessagesReceived = rawMessages.count
        openingMetrics.initialEmbedsReceived = hydrationEmbeds.count
        rawMessages = ChatLegacyEmbedLinkPolicy.applying(
            to: rawMessages,
            embeds: hydrationEmbeds,
            synthesizeMissingContent: false
        )
        allMessages = rawMessages
        rawHistoryReadFence = readFence
        if diskHistoryChatID == loadedChat.id,
           let anchor = loadedChat.lastVisibleMessageId, destination == nil,
           !rawMessages.contains(where: { $0.id == anchor }) {
            let cachedWindow = offlineStore.loadMessageWindow(chatId: loadedChat.id, around: anchor)
            if !cachedWindow.isEmpty {
                rawMessages = cachedWindow
                allMessages = cachedWindow
                refreshDiskHistoryBoundaries(cachedWindow, chatId: loadedChat.id)
            }
        }
        let visibleRawMessages = visibleWindow(from: rawMessages, anchorMessageId: loadedChat.lastVisibleMessageId,
                                              destination: destination)
        let selectedTail = visibleWindowEndIndex == allMessages.count
        let selectionGeneration = explicitWindowNavigationGeneration
        let decryptedMessages = await decryptMessages(visibleRawMessages, chatId: loadedChat.id)
        openingMetrics.initialMessagesDecrypted = decryptedMessages.count
        guard isCurrentRemoteRead(readFence) else { return }
        restoreActiveStreamInRawHistory(chatId: loadedChat.id)
        // A live chunk can change the raw source during decryption. Resolve the
        // intended window against that source without aborting initial loading.
        // Only deliberate newer navigation may supersede this selection.
        guard let resolvedMessages = await resolveLoadedHistoryWindow(
            initialRaw: visibleRawMessages, initialDecrypted: decryptedMessages,
            destination: selectedTail ? .latest : visibleRawMessages.first.map { .preserve(firstMessage: $0.id) } ?? .latest,
            generation: generation, navigationGeneration: selectionGeneration, scopeGeneration: scopeGeneration
        ) else { return }
        guard isCurrentRemoteRead(readFence) else { return }
        let messagesWithLegacyEmbedLinks = ChatLegacyEmbedLinkPolicy.applying(
            to: resolvedMessages,
            embeds: hydrationEmbeds
        )
        let embedded = PublicChatContent.attachEmbeds(to: messagesWithLegacyEmbedLinks)
        let existingRecords = embedRecords
        let referencedIds = Set(embedded.messages.flatMap { $0.embedRefs?.map(\.id) ?? [] })
        let directEmbedRefs = embedded.messages.flatMap { $0.embedRefs ?? [] }.count
        embedRecords = PublicChatContent.mergingHydratedRecords(
            existing: existingRecords, inline: embedded.records
        )
        let renderedMessages = embedded.messages
        followUpSuggestions = ChatFollowUpSuggestionPolicy.restore(
            stored: initialFollowUpSuggestions,
            hasStoredCiphertext: loadedChat.encryptedFollowUpRequestSuggestions != nil,
            legacyExtracted: extractFollowUpSuggestions(from: renderedMessages)
        )

        messages = renderedMessages
        #if DEBUG
        if loadedChat.id == "dev-chat-opening-large",
           ProcessInfo.processInfo.arguments.contains("--ui-test-composer-send") {
            followUpSuggestions = ["Synthetic follow-up"]
        }
        #endif
        refreshWindowBoundaries()
        historyWindowRevision += 1

        subscribeToStream(chatId: loadedChat.id)
        subscribeToEmbedUpdates(chatId: loadedChat.id)
        subscribeToChatLifecycle(chatId: loadedChat.id)
        isLoading = false
        NativeSyncPerfLog.info(
            "phase=loadSyncedChatFirstPaint chat=\(loadedChat.id.prefix(8)) visibleMessages=\(decryptedMessages.count) totalMessages=\(rawMessages.count) embedRefs=\(directEmbedRefs) inlineRecords=\(embedded.records.count) syncedEmbeds=\(syncedEmbeds.count) elapsedMs=\(NativeSyncPerfLog.ms(since: start))"
        )
        openingMetrics.firstUsefulRenderMs = NativeSyncPerfLog.ms(since: start)
        #if DEBUG
        seedComposerProcessingFixtureIfNeeded()
        #endif
        scheduleEmbedHydration(
            syncedEmbeds: hydrationEmbeds,
            referencedIds: referencedIds,
            chatId: loadedChat.id,
            generation: generation,
            existingRecords: embedRecords,
            source: "loadSynced"
        )
        Task { @MainActor [weak self] in
            await self?.flushPendingSubChatSpawns()
            await self?.flushPendingSubChatCompletions()
        }
    }

    private func shouldFetchMissingSyncedMessages(for chat: Chat) -> Bool {
        ChatOpeningFallbackPolicy.shouldFetchMissingSyncedMessages(
            messagesV: chat.messagesV,
            lastMessageAt: chat.lastMessageAt
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
        let scope = accountScopeGeneration()
        embedHydrationTask?.cancel()
        // Paging can prune a hydrated record while its messages are outside
        // the visible window. Restore already decoded local payloads before
        // returning the window; they need neither crypto nor the delayed
        // media/network hydration task, which later navigation may cancel.
        let localRecords = PublicChatContent.mergingHydratedRecords(
            existing: EmbedRecord.dictionaryById(syncedEmbeds, context: "chatViewModel.localHydrationSnapshot"),
            inline: EmbedRecord.dictionaryById(chatStore?.embeds(for: chatId) ?? [],
                                               context: "chatViewModel.localHydrationCache")
        )
        let hydratedLocal = relatedEmbeds(referencedIds: referencedIds, from: Array(localRecords.values))
            .filter { local in
                guard local.rawData != nil, !Self.embedRecordRequiresHydration(local) else { return false }
                guard let current = embedRecords[local.id] else { return true }
                // A decoded older payload must not hide new ciphertext that
                // still needs decryption, or replace an already hydrated row.
                return Self.embedRecordRequiresHydration(current)
                    && (current.encryptedContent == nil || current.encryptedContent == local.encryptedContent)
                    && (current.encryptedType == nil || current.encryptedType == local.encryptedType)
            }
        embedRecords = PublicChatContent.mergingHydratedRecords(
            existing: embedRecords,
            inline: EmbedRecord.dictionaryById(hydratedLocal, context: "chatViewModel.localHydration")
        )
        embedHydrationTask = Task { @MainActor [weak self] in
            guard let self else { return }
            await Task.yield()
            try? await Task.sleep(nanoseconds: 120_000_000)
            guard !Task.isCancelled, self.chat?.id == chatId, generation == self.loadGeneration,
                  scope == self.accountScopeGeneration() else { return }
            let start = NativeSyncPerfLog.now()
            // Encrypted messages reveal embed references only after first paint.
            // Re-read the scoped store now so its already-synced records are not
            // lost by the initial lightweight (pre-decryption) selection.
            let available = EmbedRecord.dictionaryById(
                syncedEmbeds, context: "chatViewModel.hydrationSnapshot"
            ).merging(EmbedRecord.dictionaryById(
                self.chatStore?.embeds(for: chatId) ?? [], context: "chatViewModel.hydrationCache"
            )) { _, cached in cached }
            let relatedSyncedEmbeds = self.relatedEmbeds(referencedIds: referencedIds, from: Array(available.values))
            let decryptedSyncedEmbeds = await self.decryptEmbeds(
                relatedSyncedEmbeds,
                chatId: chatId,
                existingRecords: existingRecords
            )
            guard !Task.isCancelled, self.chat?.id == chatId, generation == self.loadGeneration,
                  scope == self.accountScopeGeneration() else { return }
            self.embedRecords = PublicChatContent.mergingHydratedRecords(
                existing: self.embedRecords,
                inline: EmbedRecord.dictionaryById(decryptedSyncedEmbeds, context: "chatViewModel.syncedHydration"))
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
        if decrypted.activeFocusId == nil,
           let encryptedActiveFocusId = decrypted.encryptedActiveFocusId,
           let activeFocusId = await ChatKeyManager.shared.decryptChatField(
                chatId: decrypted.id,
                encryptedValue: encryptedActiveFocusId,
                fieldName: "encrypted_active_focus_id"
        ) {
            decrypted.activeFocusId = activeFocusId
        }
        return decrypted
    }

    // MARK: - Public bundled chats

    private func loadPublicChat(id: String) -> Bool {
        guard let publicChat = PublicChatContent.chat(for: id) else { return false }

        chat = publicChat.chat
        embedRecords = publicChat.embedRecords
        allMessages = ChatHistoryWindowPolicy.orderedUnique(publicChat.messages)
        messages = visibleWindow(from: allMessages, destination: .oldest)
        followUpSuggestions = publicChat.followUpSuggestions
        refreshWindowBoundaries()
        historyWindowRevision += 1
        isLoadingOlder = false
        isStreaming = false
        streamingContent = ""
        streamingMessageId = nil
        streamSubscriptionIdentity.invalidate()
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

    /// Decrypt encrypted message content and identity using the per-chat key.
    static func decryptMessagesForDisplay(_ messages: [Message], chatId: String) async -> [Message] {
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
            if msg.piiMappings == nil,
               let encryptedMappings = msg.encryptedPIIMappings,
               let decryptedMappings = await ChatKeyManager.shared.decryptMessageContent(
                    chatId: chatId,
                    encryptedContent: encryptedMappings
               ),
               let mappingsData = decryptedMappings.data(using: .utf8),
               let mappings = try? JSONDecoder().decode([PIIMapping].self, from: mappingsData) {
                msg.piiMappings = mappings
            }
            if msg.thinkingContent == nil,
               let encryptedThinkingContent = msg.encryptedThinkingContent {
                msg.thinkingContent = await ChatKeyManager.shared.decryptMessageContent(
                    chatId: chatId,
                    encryptedContent: encryptedThinkingContent
                )
            }
            if msg.senderName == nil,
               let encryptedSenderName = msg.encryptedSenderName {
                msg.senderName = await ChatKeyManager.shared.decryptMessageContent(
                    chatId: chatId,
                    encryptedContent: encryptedSenderName
                )
            }
            if msg.category == nil,
               let encryptedCategory = msg.encryptedCategory {
                msg.category = await ChatKeyManager.shared.decryptMessageContent(
                    chatId: chatId,
                    encryptedContent: encryptedCategory
                )
            }
            if msg.modelName == nil,
               let encryptedModelName = msg.encryptedModelName {
                msg.modelName = await ChatKeyManager.shared.decryptMessageContent(
                    chatId: chatId,
                    encryptedContent: encryptedModelName
                )
            }
            result.append(msg)
        }
        return result
    }

    private func decryptMessages(_ messages: [Message], chatId: String) async -> [Message] {
        await messageDecryptor(messages, chatId)
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
            // Metadata sync can republish the same ciphertext while a chat is
            // open. Reuse its decoded payload instead of redoing crypto/parsing.
            if let existing = existingRecords[embed.id], existing.rawData != nil,
               !Self.embedRecordRequiresHydration(existing), embed.encryptedContent != nil,
               existing.encryptedContent == embed.encryptedContent,
               existing.encryptedType == embed.encryptedType,
               existing.status == embed.status,
               existing.versionNumber == embed.versionNumber {
                decryptedEmbeds.append(existing)
                allRecords[existing.id] = existing
                continue
            }
            let hasEmptyCodeMetadata = EmbedType.normalized(rawValue: embed.type) == .codeCode
                && AppleCodeEmbedContent(data: embed.rawData).code.isEmpty
            guard Self.embedRecordRequiresHydration(embed) || embed.encryptedType != nil || hasEmptyCodeMetadata else {
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

    /// Compatibility entry point used by existing callers and race regressions.
    private struct RemoteReadFence {
        let generation: Int; let scope: UUID; let server: ServerProfile
        let team: TeamWorkspaceSnapshot; let chatId: String; let deletion: Int
        let owner: String?
        let foregroundDeletion: Int
        let streamSession: StreamingSessionGeneration
        let processingScope: ActiveChatsScope?
    }

    private func remoteReadFence(chatId: String, generation: Int) -> RemoteReadFence {
        .init(generation: generation, scope: accountScopeGeneration(), server: ServerProfile.current(),
              team: TeamWorkspaceContext.shared.snapshot, chatId: chatId,
              deletion: offlineStore.chatDeletionVersion(chatId), owner: AuthManager.notificationAccountId,
              foregroundDeletion: foregroundDeletionRevision,
              streamSession: StreamingClient.shared.sessionGeneration,
              processingScope: processingCoordinator.currentScope)
    }

    private func isCurrentRemoteRead(_ fence: RemoteReadFence) -> Bool {
        let currentTeam = TeamWorkspaceContext.shared.snapshot
        return !Task.isCancelled && loadGeneration == fence.generation && accountScopeGeneration() == fence.scope
            && ServerProfile.current() == fence.server && currentTeam.epoch == fence.team.epoch
            && currentTeam.teamID == fence.team.teamID && currentTeam.accountID == fence.team.accountID
            && currentTeam.server == fence.team.server && currentTeam.scope == fence.team.scope
            && AuthManager.notificationAccountId == fence.owner
            && StreamingClient.shared.isCurrentSession(fence.streamSession)
            && foregroundDeletionRevision == fence.foregroundDeletion
            && offlineStore.chatDeletionVersion(fence.chatId) == fence.deletion
    }

    private func initialRemoteQuery(anchor: String?) -> ChatMessageWindowQuery {
        .init(direction: anchor == nil ? .latest : .around, limit: ChatHistoryWindowPolicy.capacity,
              anchorMessageId: anchor, respectCompressionBoundary: false)
    }

    private func foregroundPageMessages(_ page: ChatMessageWindowPage) -> [Message] {
        page.messages.filter { !deletedForegroundMessageIds.contains($0.id)
            && !($0.serverMessageId.map(deletedForegroundMessageIds.contains) ?? false) }
    }

    private func foregroundPendingIDs(chatId: String, actionType: String) -> Set<String> {
        Set(offlineStore.loadPendingActions().compactMap { action in
            guard action.actionType == actionType, let data = action.payloadJSON,
                  let payload = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
                  (payload["chat_id"] ?? payload["chatId"]) as? String == chatId else { return nil }
            return (payload["message_id"] ?? payload["messageId"]) as? String
        })
    }

    private func pendingStreamingCompletionIDs(chatId: String) -> Set<String> {
        let recovery = chatStore?.pendingAssistantRecoveryMessageIds(in: chatId) ?? []
        let legacy = Set(PendingAssistantResponseQueue.shared.all()
            .filter { $0.chatId == chatId }.map(\.messageId))
        return recovery.union(legacy)
    }

    private func mergeForegroundMessages(_ incoming: [Message], preserving current: [Message], chatId: String) -> [Message] {
        let deleted = deletedForegroundMessageIds.union(foregroundPendingIDs(chatId: chatId, actionType: "delete_message"))
        let incoming = incoming.filter { !deleted.contains($0.id) && !($0.serverMessageId.map(deleted.contains) ?? false) }
        let preserved = ChatStreamingSyncCompletionPolicy.retainedForegroundMessages(
            current, incoming: incoming, lifecycle: streamingLifecycle, chatID: chatId,
            pendingMessageIDs: pendingStreamingCompletionIDs(chatId: chatId))
        return ChatMessageWindowPage.merge(incoming, preserving: preserved,
            pendingIds: foregroundPendingIDs(chatId: chatId, actionType: "send_message"))
            .filter { !deleted.contains($0.id) && !($0.serverMessageId.map(deleted.contains) ?? false) }
    }

    /// Deletion also fences reads for IDs absent from this partial viewport.
    func consumeForegroundMessageDeletion(chatId: String, messageId: String) {
        guard chat?.id == chatId else { return }
        foregroundDeletionRevision += 1
        deletedForegroundMessageIds.insert(messageId)
        cancelOlderMessagesLoad()
        allMessages.removeAll { $0.id == messageId || $0.serverMessageId == messageId }
        messages.removeAll { $0.id == messageId || $0.serverMessageId == messageId }
        visibleWindowStartIndex = messages.first.flatMap { first in allMessages.firstIndex { $0.id == first.id } } ?? 0
        visibleWindowEndIndex = min(allMessages.count, visibleWindowStartIndex + messages.count)
        refreshWindowBoundaries(); historyWindowRevision += 1
    }

    private func fetchRemoteWindow(chatId: String, teamId: String?, query: ChatMessageWindowQuery,
                                   generation: Int, fallbackMissingAnchor: Bool = true) async throws -> ChatMessageWindowPage {
        let fence = remoteReadFence(chatId: chatId, generation: generation)
        guard isCurrentRemoteRead(fence), fence.team.teamID == teamId else { throw ChatMessageWindowError.staleContext }
        let page = try await messageWindowFetcher(chatId, teamId, query).validated(chatId: chatId, query: query)
        guard isCurrentRemoteRead(fence) else { throw ChatMessageWindowError.staleContext }
        if fallbackMissingAnchor && query.direction == .around && !page.anchorFound {
            var latest = query; latest.direction = .latest; latest.anchorMessageId = nil
            let fallback = try await messageWindowFetcher(chatId, teamId, latest).validated(chatId: chatId, query: latest)
            guard isCurrentRemoteRead(fence) else { throw ChatMessageWindowError.staleContext }
            return fallback
        }
        return page
    }

    private func remoteQuery(_ destination: ChatHistoryWindowDestination) -> ChatMessageWindowQuery? {
        guard let remoteHistory, remoteHistory.chatId == chat?.id else { return nil }
        var query = ChatMessageWindowQuery(limit: ChatHistoryWindowPolicy.capacity, respectCompressionBoundary: false)
        switch destination {
        case .older where remoteHistory.hasOlder && visibleWindowStartIndex < ChatHistoryWindowPolicy.stride:
            query.direction = .before; query.before = remoteHistory.start
        case .newer where remoteHistory.hasNewer && allMessages.count - visibleWindowEndIndex < ChatHistoryWindowPolicy.stride:
            query.direction = .after; query.after = remoteHistory.end
        case .latest where remoteHistory.hasNewer:
            break
        case .oldest where remoteHistory.hasOlder:
            query.direction = .after; query.afterBeginning = true
        case .message(let id) where !allMessages.contains(where: { $0.id == id }):
            query.direction = .around; query.anchorMessageId = id
        default: return nil
        }
        return query
    }

    private func loadRemoteMessageWindow(_ query: ChatMessageWindowQuery,
        destination: ChatHistoryWindowDestination, chatId: String, generation: Int,
        requestGeneration: Int, scopeGeneration: UUID) -> Task<Void, Never> {
        let fence = remoteReadFence(chatId: chatId, generation: generation)
        let teamId = chat?.teamId
        isLoadingOlder = true
        error = nil
        failedRemoteWindowRequest = nil
        let task = Task { @MainActor [weak self] in
            guard let self else { return }
            defer {
                if windowRequestGeneration == requestGeneration {
                    isLoadingOlder = false; olderMessagesTask = nil
                }
            }
            do {
                let page = try await fetchRemoteWindow(chatId: chatId, teamId: teamId, query: query,
                    generation: generation, fallbackMissingAnchor: false)
                guard isCurrentRemoteRead(fence), isCurrentWindowRequest(chatId: chatId, generation: generation,
                    requestGeneration: requestGeneration, scopeGeneration: scopeGeneration) else { return }
                guard query.direction != .around || page.anchorFound else { throw ChatMessageWindowError.invalidResponse }
                var source: [Message]
                var nextRemote = remoteHistory ?? RemoteHistory(page)
                let oldFirstId = messages.first?.id
                if query.direction == .before || (query.direction == .after && !query.afterBeginning) {
                    source = mergeForegroundMessages(foregroundPageMessages(page), preserving: allMessages, chatId: chatId)
                    if query.direction == .before {
                        nextRemote.start = page.startCursor ?? nextRemote.start; nextRemote.hasOlder = page.hasMoreBefore
                    } else {
                        nextRemote.end = page.endCursor ?? nextRemote.end; nextRemote.hasNewer = page.hasMoreAfter
                    }
                } else {
                    let pendingIds = foregroundPendingIDs(chatId: chatId, actionType: "send_message")
                    source = mergeForegroundMessages(foregroundPageMessages(page),
                        preserving: allMessages.filter { $0.isStreaming == true || $0.encryptedContent == nil || pendingIds.contains($0.id) }, chatId: chatId)
                    nextRemote = RemoteHistory(page)
                    if query.afterBeginning { nextRemote.hasOlder = false }
                }
                var current = visibleWindowStartIndex..<visibleWindowEndIndex
                if let oldFirstId, let index = source.firstIndex(where: { $0.id == oldFirstId }) {
                    current = index..<min(source.count, index + messages.count)
                }
                let resolvedDestination: ChatHistoryWindowDestination = query.afterBeginning ? .oldest : destination
                let range = ChatHistoryWindowPolicy.range(in: source, destination: resolvedDestination, current: current) ?? 0..<0
                let visible = Array(source[range])
                let decrypted = await decryptMessages(visible, chatId: chatId)
                guard isCurrentRemoteRead(fence), isCurrentWindowRequest(chatId: chatId, generation: generation,
                    requestGeneration: requestGeneration, scopeGeneration: scopeGeneration) else { return }
                // Resolve exact terminal identity before preserving live rows;
                // otherwise a stale partial can overwrite this saved completion.
                reconcileStreamingCompletion(chatId: chatId, authoritativeMessages: source, readFence: fence)
                let pendingCompletionIDs = pendingStreamingCompletionIDs(chatId: chatId)
                let savedSourceIDs = Set(source.filter { row in
                    row.chatId == chatId && (row.role == .assistant || row.role == .system)
                        && row.isStreaming != true && row.encryptedContent?.isEmpty == false
                        && !pendingCompletionIDs.contains(row.id)
                        && !(row.serverMessageId.map(pendingCompletionIDs.contains) ?? false)
                }.flatMap { [$0.id, $0.serverMessageId].compactMap { $0 } })
                let queuedIds = foregroundPendingIDs(chatId: chatId, actionType: "send_message")
                let pending = allMessages.filter {
                    !savedSourceIDs.contains($0.id) && !($0.serverMessageId.map(savedSourceIDs.contains) ?? false)
                        && ($0.isStreaming == true || queuedIds.contains($0.id) || ($0.encryptedContent == nil && $0.content != nil))
                }
                let pendingIds = Set(pending.map(\.id))
                source = ChatMessageWindowPage.merge(source.filter { !pendingIds.contains($0.id) }, preserving: pending)
                let pendingById = Dictionary(pending.map { ($0.id, $0) }, uniquingKeysWith: { _, last in last })
                let embedded = PublicChatContent.attachEmbeds(to: decrypted.map { pendingById[$0.id] ?? $0 })
                allMessages = source; rawHistoryReadFence = fence; remoteHistory = nextRemote
                messages = embedded.messages
                embedRecords = PublicChatContent.mergingHydratedRecords(existing: embedRecords, inline: embedded.records)
                visibleWindowStartIndex = messages.first.flatMap { first in source.firstIndex { $0.id == first.id } } ?? range.lowerBound
                visibleWindowEndIndex = min(source.count, visibleWindowStartIndex + messages.count)
                refreshWindowBoundaries(); historyWindowRevision += 1
                scheduleEmbedHydration(syncedEmbeds: [],
                    referencedIds: Set(messages.flatMap { $0.embedRefs?.map(\.id) ?? [] }),
                    chatId: chatId, generation: generation, existingRecords: embedRecords, source: "remoteWindow")
            } catch {
                guard isCurrentRemoteRead(fence), windowRequestGeneration == requestGeneration else { return }
                failedRemoteWindowRequest = requestGeneration
                self.error = error is ChatMessageWindowError ? AppStrings.genericProcessingError : error.localizedDescription
            }
        }
        olderMessagesTask = task
        return task
    }

    @discardableResult
    func loadOlderMessages() -> Task<Void, Never>? { loadMessageWindow(.older) }

    @discardableResult
    func loadNewerMessages() -> Task<Void, Never>? { loadMessageWindow(.newer) }

    #if DEBUG
    private var isolatedHistory = false
    private var didSeedComposerProcessingFixture = false
    @Published private(set) var composerProcessingRecoveryReceipt = "ready"

    private func seedComposerProcessingFixtureIfNeeded() {
        guard !didSeedComposerProcessingFixture, chat?.id == "dev-chat-opening-large",
              ProcessInfo.processInfo.arguments.contains("--dev-preview"),
              ProcessInfo.processInfo.arguments.contains("--ui-test-composer-processing-recovery") else { return }
        didSeedComposerProcessingFixture = true
        handleStreamEvent(.taskInitiated(chatId: "dev-chat-opening-large", taskId: "synthetic-processing-task", userMessageId: "synthetic-processing-user"))
        handleStreamEvent(.preprocessingStep(chatId: "dev-chat-opening-large", step: "model_selected", data: nil))
    }

    func seedIsolatedHistory(chat: Chat, messages: [Message], embeds: [EmbedRecord]) {
        isolatedHistory = true
        self.chat = chat
        if chat.id == "dev-chat-opening-large", ProcessInfo.processInfo.arguments.contains("--ui-test-composer-send") {
            followUpSuggestions = ["Synthetic follow-up"]
        }
        allMessages = ChatHistoryWindowPolicy.orderedUnique(messages)
        rawHistoryReadFence = remoteReadFence(chatId: chat.id, generation: loadGeneration)
        self.messages = visibleWindow(from: allMessages, destination: .latest)
        embedRecords = EmbedRecord.dictionaryById(embeds, context: "isolatedHistory")
        isLoading = false
        refreshWindowBoundaries(); historyWindowRevision += 1
        seedComposerProcessingFixtureIfNeeded()
    }

    /// Drives the production sync and buffered-replay reducers with disposable
    /// fixture rows; never contacts inference or writes account data.
    func recoverIsolatedProcessingFixture() async {
        guard ProcessInfo.processInfo.arguments.contains("--dev-preview"),
              ProcessInfo.processInfo.arguments.contains("--ui-test-composer-processing-recovery") else { return }
        composerProcessingRecoveryReceipt = "invoked"
        guard didSeedComposerProcessingFixture, let chat, chat.id == "dev-chat-opening-large",
              streamingLifecycle.taskId == "synthetic-processing-task" else {
            composerProcessingRecoveryReceipt = "guard-rejected"
            return
        }
        composerProcessingRecoveryReceipt = "pending"
        let terminal = Message(id: "synthetic-processing-task", chatId: chat.id, role: .assistant,
            content: "Synthetic completed processing response", encryptedContent: "synthetic-terminal-ciphertext",
            createdAt: ChatSendPipeline.isoString(from: Date()), updatedAt: nil,
            appId: nil, isStreaming: false, embedRefs: nil)
        let completedHistory = allMessages + [terminal]
        // Normal fixture loading reads its authoritative in-memory ChatStore.
        // Update that disposable source before exercising production sync/replay.
        chatStore?.performWithoutPersistence {
            chatStore?.setMessages(for: chat.id, messages: completedHistory)
        }
        await applySynced(chat: chat, messages: completedHistory)
        guard let fence = rawHistoryReadFence, fence.chatId == chat.id, isCurrentRemoteRead(fence) else {
            composerProcessingRecoveryReceipt = "authority-fenced"
            return
        }
        handleStreamEvent(.taskInitiated(chatId: chat.id, taskId: terminal.id, userMessageId: "synthetic-processing-user"))
        handleStreamEvent(.preprocessingStep(chatId: chat.id, step: "model_selected", data: nil))
        let hasSavedTerminal = allMessages.contains {
            $0.id == terminal.id && $0.chatId == chat.id && $0.role == .assistant
                && $0.isStreaming != true && $0.encryptedContent == terminal.encryptedContent
        }
        if hasSavedTerminal && !isStreaming && !streamingLifecycle.isActive {
            composerProcessingRecoveryReceipt = "completed"
        }
    }
    #endif

    @discardableResult
    func loadMessageWindow(_ destination: ChatHistoryWindowDestination) -> Task<Void, Never>? {
        #if DEBUG
        if isolatedHistory {
            return Task { @MainActor in
                messages = visibleWindow(from: allMessages, destination: destination)
                refreshWindowBoundaries(); historyWindowRevision += 1
            }
        }
        #endif
        guard !isLoading, let chatId = chat?.id else { return nil }
        if destination == .older && (!hasOlderMessages || isLoadingOlder) { return nil }
        if destination == .newer && (!hasNewerMessages || isLoadingOlder) { return nil }
        explicitWindowNavigationGeneration += 1
        cancelOlderMessagesLoad()
        let generation = loadGeneration
        let requestGeneration = windowRequestGeneration
        let scopeGeneration = accountScopeGeneration()
        if let query = remoteQuery(destination) {
            return loadRemoteMessageWindow(query, destination: destination, chatId: chatId,
                generation: generation, requestGeneration: requestGeneration, scopeGeneration: scopeGeneration)
        }
        extendDiskHistoryIfNeeded(destination, chatId: chatId)
        let current = visibleWindowStartIndex..<visibleWindowEndIndex
        let source = allMessages
        guard let nextRange = ChatHistoryWindowPolicy.range(in: source, destination: destination, current: current) else { return nil }
        if nextRange == current { return nil }
        let batch = Array(source[nextRange])
        // Reuse overlap already decrypted, but never retain it as extra rows.
        let existing = Dictionary(messages.map { ($0.id, $0) }, uniquingKeysWith: { _, new in new })
        let missing = batch.filter { existing[$0.id] == nil }
        isLoadingOlder = true
        olderMessagesTask = Task { @MainActor [weak self] in
            guard let self else { return }
            defer {
                if isCurrentWindowRequest(chatId: chatId, generation: generation, requestGeneration: requestGeneration,
                                          scopeGeneration: scopeGeneration) {
                    isLoadingOlder = false
                    olderMessagesTask = nil
                }
            }
            guard isCurrentWindowRequest(chatId: chatId, generation: generation, requestGeneration: requestGeneration,
                                         scopeGeneration: scopeGeneration) else { return }
            let decrypted = await decryptMessages(missing, chatId: chatId)
            guard isCurrentWindowRequest(chatId: chatId, generation: generation, requestGeneration: requestGeneration,
                                         scopeGeneration: scopeGeneration) else { return }
            let latestVisible = Dictionary(messages.map { ($0.id, $0) }, uniquingKeysWith: { _, new in new })
            let byID = Dictionary(decrypted.map { ($0.id, $0) }, uniquingKeysWith: { _, new in new })
                .merging(latestVisible) { _, current in current }
            let windowMessages = ChatLegacyEmbedLinkPolicy.applying(
                to: batch.compactMap { byID[$0.id] },
                embeds: Array(embedRecords.values)
            )
            let embedded = PublicChatContent.attachEmbeds(to: windowMessages)
            let availableRecords = PublicChatContent.mergingHydratedRecords(
                existing: embedRecords, inline: embedded.records
            )
            let referencedIDs = Set(embedded.messages.flatMap { $0.embedRefs?.map(\.id) ?? [] })
            embedRecords = EmbedRecord.dictionaryById(
                relatedEmbeds(referencedIds: referencedIDs, from: Array(availableRecords.values)),
                context: "chatViewModel.window")
            messages = embedded.messages
            visibleWindowStartIndex = nextRange.lowerBound
            visibleWindowEndIndex = nextRange.upperBound
            refreshWindowBoundaries()
            historyWindowRevision += 1
            // Row navigation completes before media/network hydration. The UI
            // must restore its retained overlap immediately after this commit.
            scheduleEmbedHydration(syncedEmbeds: diskHistoryChatID == chatId ? offlineStore.loadEmbeds(chatId: chatId) : [], referencedIds: referencedIDs,
                chatId: chatId, generation: generation, existingRecords: embedRecords,
                source: "historyWindow")
        }
        return olderMessagesTask
    }

    func cancelHistoryWindowNavigation() {
        cancelOlderMessagesLoad()
    }

    private func refreshWindowBoundaries() {
        hasOlderMessages = visibleWindowStartIndex > 0 || diskHasOlderMessages || remoteHistory?.hasOlder == true
        newerMessageCount = max(0, allMessages.count - visibleWindowEndIndex) + diskNewerMessageCount
        hasNewerMessages = newerMessageCount > 0 || diskHasNewerMessages || remoteHistory?.hasNewer == true
    }

    private func refreshDiskHistoryBoundaries(_ source: [Message], chatId: String) {
        diskHasOlderMessages = source.first.map { offlineStore.hasOlderMessages(chatId: chatId, before: $0) } ?? false
        diskNewerMessageCount = source.last.map { offlineStore.newerMessageCount(chatId: chatId, after: $0) } ?? 0
        diskHasNewerMessages = diskNewerMessageCount > 0
    }

    private func extendDiskHistoryIfNeeded(_ destination: ChatHistoryWindowDestination, chatId: String) {
        guard remoteHistory == nil, diskHistoryChatID == chatId else { return }
        var replacement: [Message]?
        switch destination {
        case .older where diskHasOlderMessages && visibleWindowStartIndex < ChatHistoryWindowPolicy.stride:
            if let first = allMessages.first {
                let older = offlineStore.loadOlderMessageWindow(chatId: chatId, before: first.id,
                    limit: ChatHistoryWindowPolicy.stride)
                allMessages = older + allMessages
                visibleWindowStartIndex += older.count
                visibleWindowEndIndex += older.count
            }
        case .newer where diskHasNewerMessages && allMessages.count - visibleWindowEndIndex < ChatHistoryWindowPolicy.stride:
            if let last = allMessages.last {
                allMessages += offlineStore.loadNewerMessageWindow(chatId: chatId, after: last,
                    limit: ChatHistoryWindowPolicy.stride)
            }
        case .oldest where diskHasOlderMessages:
            replacement = offlineStore.loadOldestMessageWindow(chatId: chatId)
        case .latest where diskHasNewerMessages:
            replacement = offlineStore.loadLatestMessageWindow(chatId: chatId)
        case .message(let id) where !allMessages.contains(where: { $0.id == id }):
            replacement = offlineStore.loadMessageWindow(chatId: chatId, around: id)
        default:
            break
        }
        if let replacement, !replacement.isEmpty {
            allMessages = replacement
            visibleWindowStartIndex = 0
            visibleWindowEndIndex = 0
        }
        refreshDiskHistoryBoundaries(allMessages, chatId: chatId)
    }

    private func cancelOlderMessagesLoad() {
        windowRequestGeneration += 1
        olderMessagesTask?.cancel()
        olderMessagesTask = nil
        isLoadingOlder = false
    }

    private func isCurrentWindowRequest(chatId: String, generation: Int, requestGeneration: Int,
                                        scopeGeneration: UUID) -> Bool {
        !Task.isCancelled && chat?.id == chatId && loadGeneration == generation
            && windowRequestGeneration == requestGeneration && accountScopeGeneration() == scopeGeneration
    }

    // MARK: - Send message

    @discardableResult
    func sendMessage(
        _ content: String,
        piiMappings: [PIIMapping] = [],
        excludedPIIOriginals: Set<String> = [],
        excludedPIIPlaceholders: Set<String> = [],
        broadcastToSiblings: Bool = false,
        composerEmbeds explicitComposerEmbeds: [ComposerPendingEmbed]? = nil,
        messageId: String? = nil,
        editingMessageID: String? = nil
    ) async -> Bool {
        guard let currentChat = chat else { return false }
        #if DEBUG
        let fixtureArgs = ProcessInfo.processInfo.arguments
        if currentChat.id == "dev-chat-opening-large", fixtureArgs.contains("--ui-test-composer-send") {
            if fixtureArgs.contains("rejected") {
                error = AppStrings.genericProcessingError
                return false
            }
            guard fixtureArgs.contains("accepted") else { return false }
            appendOrReplaceTransientMessage(Message(id: UUID().uuidString, chatId: currentChat.id,
                role: .user, content: content, encryptedContent: nil,
                createdAt: ChatSendPipeline.isoString(from: Date()), updatedAt: nil,
                appId: nil, isStreaming: false, embedRefs: nil))
            error = nil
            return true
        }
        #endif
        if hasNewerMessages {
            let generation = loadGeneration
            let scope = accountScopeGeneration()
            while hasNewerMessages {
                guard !Task.isCancelled, chat?.id == currentChat.id, loadGeneration == generation,
                      accountScopeGeneration() == scope,
                      let task = loadMessageWindow(.latest) else { return false }
                let tailRequestGeneration = windowRequestGeneration
                await task.value
                guard !Task.isCancelled, chat?.id == currentChat.id, loadGeneration == generation,
                      accountScopeGeneration() == scope,
                      failedRemoteWindowRequest != tailRequestGeneration else { return false }
                // A new row may invalidate the source while decryption awaits.
                // Retry that bounded tail before preparing the send payload.
            }
        }
        if IncognitoChatSession.isIncognitoChatId(currentChat.id) {
            return await sendIncognitoMessage(content, in: currentChat)
        }
        if AnonymousFreeUsageService.shared.isAnonymousChat(currentChat.id) {
            return await sendAnonymousMessage(content, in: currentChat)
        }
        let editingScope = OfflineStore.shared.scopeGeneration
        do {
            let mutationFence = await captureMessageActionFence()
            var editPlan: MessageEditPlan?
            if let editingMessageID {
                guard let mutationFence, mutationFence.chatID == currentChat.id, canMutatePersonalMessages else { throw MessageContextActionError.unavailable }
                let complete = try await completeMessagesForAction(fence: mutationFence)
                editPlan = try MessageEditPlan.make(messages: complete, chatID: currentChat.id, messageID: editingMessageID)
            }
            let retainedHistory = editPlan?.retained ?? allMessages
            let preparedDeletion: (() async throws -> Void)? = editPlan.map { plan in
                { [weak self] in
                    guard let self, let mutationFence else { throw MessageContextActionError.staleContext }
                    try self.requireMessageActionFence(mutationFence)
                    try await MessageEditExecutor.removeSuffix(plan, validate: { try self.requireMessageActionFence(mutationFence) },
                        remove: { try await self.deleteOwnedMessage($0, fence: mutationFence) })
                }
            }
            let composerEmbeds = explicitComposerEmbeds ?? pendingComposerEmbeds
            let mergedPIIMappings = sendPipeline.combinedPIIMappings(
                textMappings: piiMappings,
                composerEmbeds: composerEmbeds
            )
            let result = try await sendPipeline.sendUserMessage(
                content: content,
                in: currentChat,
                existingMessages: retainedHistory,
                wsManager: wsManager,
                chatStore: chatStore,
                waitForInferenceReceipt: messageId != nil,
                composerEmbeds: composerEmbeds,
                piiMappings: mergedPIIMappings,
                excludedPIIOriginals: excludedPIIOriginals,
                excludedPIIPlaceholders: excludedPIIPlaceholders,
                broadcastToSiblings: broadcastToSiblings,
                createdAtOverride: editPlan?.removed.first?.createdAt,
                beforePreparedSend: preparedDeletion,
                validateRemoteSend: editingMessageID == nil ? nil : { [weak self] in
                    guard let self, let mutationFence else { throw MessageContextActionError.staleContext }; try self.requireMessageActionFence(mutationFence)
                },
                messageId: messageId
            )
            if editingMessageID != nil, let mutationFence { try requireMessageActionFence(mutationFence) }
            let provisionalTitle = allMessages.contains(where: { $0.role == .user })
                ? nil
                : ChatHeaderPresentation.provisionalTitle(
                    from: ChatSendPipeline.provisionalTitleSource(
                        content: content,
                        composerEmbeds: composerEmbeds
                    ) ?? ""
                )
            let presentedChat = ChatGeneratedMetadataPolicy.applyingProvisionalTitle(
                provisionalTitle,
                to: result.chat
            )
            chat = presentedChat
            // The provisional title is derived from plaintext user input. Keep
            // it in the in-memory list for immediate navigation, while the
            // generated title later replaces it through the encrypted metadata
            // path. SwiftData must never receive this plaintext fallback.
            chatStore?.performWithoutPersistence {
                chatStore?.upsertChat(presentedChat)
            }
            appendOrReplaceLocalMessage(result.message)
            followUpSuggestions = ChatFollowUpSuggestionPolicy.clearForAcceptedSend(followUpSuggestions)
            if broadcastToSiblings {
                await broadcastMessageToSiblingSubChats(
                    result.message.content ?? content,
                    piiMappings: result.message.piiMappings ?? mergedPIIMappings
                )
            }
            if let explicitComposerEmbeds {
                let sentIDs = Set(explicitComposerEmbeds.map(\.id))
                pendingComposerEmbeds.removeAll { sentIDs.contains($0.id) }
            } else {
                pendingComposerEmbeds.removeAll()
            }
            isStreaming = true
            streamingContent = ""
            return true
        } catch {
            if editingMessageID != nil && (chat?.id != currentChat.id || OfflineStore.shared.scopeGeneration != editingScope) { return false }
            self.error = error.localizedDescription
            isStreaming = false
            return false
        }
    }

    private func sendIncognitoMessage(_ content: String, in currentChat: Chat) async -> Bool {
        guard !hasPendingComposerEmbeds else {
            ToastManager.shared.show(AppStrings.uploadSignupRequired, type: .info)
            return false
        }
        do {
            let result = sendPipeline.makeLocalIncognitoUserMessage(
                content: content,
                in: currentChat,
                existingMessages: allMessages
            )
            chat = result.chat
            appendOrReplaceTransientMessage(result.message)
            followUpSuggestions = ChatFollowUpSuggestionPolicy.clearForAcceptedSend(followUpSuggestions)
            isStreaming = true
            streamingContent = ""
            try await sendPipeline.sendIncognitoUserMessage(
                message: result.message,
                in: result.chat,
                historyMessages: allMessages,
                wsManager: wsManager
            )
            return true
        } catch {
            self.error = error.localizedDescription
            isStreaming = false
            return false
        }
    }

    private func sendAnonymousMessage(_ content: String, in currentChat: Chat) async -> Bool {
        guard AnonymousFreeUsageService.shared.canSendAnonymously else {
            error = AppStrings.signUp
            return false
        }
        guard !hasPendingComposerEmbeds else {
            ToastManager.shared.show(AppStrings.uploadSignupRequired, type: .info)
            return false
        }
        do {
            let chatKey = try await AnonymousFreeUsageService.shared.ensureAnonymousChatKey(chatId: currentChat.id)
            let createdAt = ChatSendPipeline.isoString(from: Date())
            var updatedChat = anonymousUpdatedChat(currentChat, lastMessageAt: createdAt)

            if !anonymousFeatureNoticeInserted && !allMessages.contains(where: { $0.role == .system }) {
                let notice = Message(
                    id: "\(currentChat.id.suffix(10))-notice",
                    chatId: currentChat.id,
                    role: .system,
                    content: AppStrings.anonymousFreeUsageFeatureNotice,
                    encryptedContent: nil,
                    createdAt: createdAt,
                    updatedAt: nil,
                    appId: nil,
                    isStreaming: false,
                    embedRefs: nil
                )
                appendOrReplaceLocalMessage(notice)
                anonymousFeatureNoticeInserted = true
            }

            let userMessageId = "\(currentChat.id.suffix(10))-\(UUID().uuidString)"
            let assistantMessageId = "\(currentChat.id.suffix(10))-\(UUID().uuidString)"
            let userMessage = Message(
                id: userMessageId,
                chatId: currentChat.id,
                role: .user,
                content: content,
                encryptedContent: try await CryptoManager.shared.encryptContent(content, key: chatKey),
                createdAt: createdAt,
                updatedAt: nil,
                appId: nil,
                isStreaming: false,
                embedRefs: nil
            )

            chat = updatedChat
            chatStore?.upsertChat(updatedChat)
            appendOrReplaceLocalMessage(userMessage)
            followUpSuggestions = ChatFollowUpSuggestionPolicy.clearForAcceptedSend(followUpSuggestions)
            isStreaming = true
            streamingContent = ""
            streamingMessageId = assistantMessageId

            let response = try await AnonymousFreeUsageService.shared.sendAnonymousMessage(
                chatId: currentChat.id,
                assistantMessageId: assistantMessageId,
                plaintext: content,
                history: anonymousHistory(excluding: userMessageId)
            )
            let assistantCreatedAt = ChatSendPipeline.isoString(from: Date())
            let assistant = Message(
                id: response.messageId,
                chatId: response.chatId,
                role: .assistant,
                content: response.assistant,
                encryptedContent: try await CryptoManager.shared.encryptContent(response.assistant, key: chatKey),
                createdAt: assistantCreatedAt,
                updatedAt: nil,
                appId: response.category,
                isStreaming: false,
                embedRefs: nil,
                modelName: response.modelName
            )
            updatedChat = anonymousUpdatedChat(updatedChat, lastMessageAt: assistantCreatedAt, category: response.category)
            chat = updatedChat
            chatStore?.upsertChat(updatedChat)
            appendOrReplaceLocalMessage(assistant)
            followUpSuggestions = ChatFollowUpSuggestionPolicy.acceptCompletedResponse(response.followUpSuggestions)
            isStreaming = false
            streamingContent = ""
            streamingMessageId = nil
            return true
        } catch {
            self.error = error.localizedDescription
            isStreaming = false
            streamingContent = ""
            streamingMessageId = nil
            return false
        }
    }

    private func anonymousUpdatedChat(_ chat: Chat, lastMessageAt: String, category: String? = nil) -> Chat {
        let messageCount = allMessages.filter { $0.role != .system }.count + 1
        let fallbackTitle = allMessages.first(where: { $0.role == .user })?.content ?? AppStrings.newChat
        return Chat(
            id: chat.id,
            title: chat.title ?? String(fallbackTitle.prefix(64)),
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
            encryptedFollowUpRequestSuggestions: chat.encryptedFollowUpRequestSuggestions,
            encryptedAutoSpeakResponse: chat.encryptedAutoSpeakResponse,
            encryptedChatKey: chat.encryptedChatKey,
            messagesV: messageCount,
            titleV: chat.titleV,
            draftV: chat.draftV,
            lastVisibleMessageId: chat.lastVisibleMessageId,
            parentId: chat.parentId,
            isSubChat: chat.isSubChat,
            subChatSettings: chat.subChatSettings,
            budgetLimit: chat.budgetLimit,
            budgetSpent: chat.budgetSpent,
            encryptedFocusPhaseState: chat.encryptedFocusPhaseState,
            encryptedActiveFocusId: chat.encryptedActiveFocusId,
            activeFocusId: chat.activeFocusId
        )
    }

    private func anonymousHistory(excluding messageId: String) -> [AnonymousHistoryMessage] {
        allMessages.compactMap { message in
            guard message.id != messageId,
                  message.role != .system,
                  let content = message.content,
                  !content.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else { return nil }
            return AnonymousHistoryMessage(
                role: message.role.rawValue,
                content: content,
                createdAt: ChatSendPipeline.unixSeconds(from: message.createdAt),
                senderName: message.role == .user ? "User" : "Assistant"
            )
        }
    }

    private func broadcastMessageToSiblingSubChats(_ content: String, piiMappings: [PIIMapping]) async {
        guard let currentChat = chat,
              let parentId = currentChat.parentId,
              let chatStore else { return }
        let siblings = chatStore.chats.filter { sibling in
            sibling.parentId == parentId && sibling.id != currentChat.id
        }
        for sibling in siblings {
            do {
                _ = try await sendPipeline.sendUserMessage(
                    content: content,
                    in: sibling,
                    existingMessages: chatStore.messages(for: sibling.id),
                    wsManager: wsManager,
                    chatStore: chatStore,
                    activateChat: false,
                    waitForRemoteSend: true,
                    composerEmbeds: [],
                    piiMappings: piiMappings,
                    broadcastToSiblings: false
                )
            } catch {
                print("[ChatViewModel] Failed to broadcast sub-chat message to \(sibling.id.prefix(8)): \(error)")
            }
        }
    }

    // MARK: - Stop streaming

    func stopStreaming() {
        let taskId = streamingLifecycle.taskId
        let chatId = streamingLifecycle.chatId ?? chat?.id
        if taskId != nil || chatId != nil {
            streamingLifecycle.apply(.cancelRequested(chatId: chatId ?? "", taskId: taskId))
            Task { @MainActor in
                do {
                    try await sendPipeline.sendCancelAITask(taskId: taskId, chatId: chatId, wsManager: wsManager)
                } catch {
                    print("[ChatViewModel] Failed to send AI cancellation for chat \((chatId ?? "unknown").prefix(8)): \(error)")
                }
            }
        }
        streamSubscriptionIdentity.invalidate()
        streamTask?.cancel()
        queuedMessageClearTask?.cancel()
        queuedMessageClearTask = nil
        isStreaming = false
        streamingContent = ""
        streamingMessageId = nil
        streamingLifecycle.reset()
        if let chatId {
            // Continue receiving the server's cancellation/final acknowledgment,
            // without replaying the active snapshot we just stopped displaying.
            subscribeToStream(chatId: chatId, replayBufferedState: false)
        }
    }

    // MARK: - Streaming subscription

    private func subscribeToStream(chatId: String, replayBufferedState: Bool = true) {
        let sessionGeneration = StreamingClient.shared.sessionGeneration
        guard let subscriptionToken = streamSubscriptionIdentity.begin(
            chatID: chatId, session: sessionGeneration) else { return }
        let pendingRecoveryIDs = chatStore?.pendingAssistantRecoveryMessageIds(in: chatId) ?? []
        let pendingLegacyIDs = Set(PendingAssistantResponseQueue.shared.all()
            .filter { $0.chatId == chatId }.map(\.messageId))
        let materializedFinalIDs = ChatStreamReplayPolicy.materializedFinalMessageIDs(
            in: chatStore?.messages(for: chatId) ?? allMessages, chatID: chatId,
            pendingMessageIDs: pendingRecoveryIDs.union(pendingLegacyIDs))
        var previousStreamTask = streamTask
        streamTask = Task { [weak self] in
            defer { self?.streamSubscriptionIdentity.finish(subscriptionToken) }
            let stream = await StreamingClient.shared.streamForChat(chatId, session: sessionGeneration,
                                                                    replayBufferedState: replayBufferedState,
                                                                    excludingMaterializedFinalMessageIDs: materializedFinalIDs)
            previousStreamTask?.cancel()
            previousStreamTask = nil
            for await event in stream {
                guard !Task.isCancelled,
                      StreamingClient.shared.isCurrentSession(sessionGeneration),
                      let self, self.chat?.id == chatId else { break }
                self.handleStreamEvent(event)
            }
        }
    }

    func handleStreamEvent(_ event: StreamingClient.StreamEvent) {
        guard streamingLifecycle.apply(event) else { return }
        // Buffered preprocessing/typing may arrive after foreground history has
        // already materialized the final encrypted row. Reconcile before replay
        // can replace that row with a partial plaintext assistant.
        if let chatID = chat?.id, reconcileStreamingCompletion(chatId: chatID) { return }
        switch event {
        case .taskInitiated(_, _, _):
            isStreaming = true
            streamingContent = ""
            streamingMessageId = nil

        case .typingStarted(let chatId, let messageId, let metadata):
            streamingMessageId = messageId
            if let metadata, let currentChat = chat, currentChat.id == chatId {
                chat = ChatGeneratedMetadataPolicy.applying(metadata, to: currentChat)
            }
            if let userMessageId = metadata?.userMessageId {
                userMessageIdByAssistantMessageId[messageId] = userMessageId
            }
            if let category = metadata?.category {
                assistantCategoryByMessageId[messageId] = category
            }
            if let modelName = metadata?.modelName {
                assistantModelNameByMessageId[messageId] = modelName
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
                    modelName: resolvedModelName,
                    thinkingContent: streamingLifecycle.thinkingContent.isEmpty ? nil : streamingLifecycle.thinkingContent
                )
                let embedded = PublicChatContent.attachEmbeds(to: [rawAssistantMessage])
                for (id, record) in embedded.records {
                    embedRecords[id] = record
                }
                let assistantMessage = embedded.messages.first ?? rawAssistantMessage
                if IncognitoChatSession.isIncognitoChatId(chatId) {
                    appendOrReplaceTransientMessage(assistantMessage)
                } else {
                    appendOrReplaceLocalMessage(assistantMessage)
                }
                followUpSuggestions = ChatFollowUpSuggestionPolicy.reconcile(
                    current: followUpSuggestions,
                    incoming: extractFollowUpSuggestions(from: allMessages)
                )
                isStreaming = false
                streamingContent = ""
                streamingMessageId = nil
                assistantMessageCreatedAtById.removeValue(forKey: messageId)
                assistantCategoryByMessageId.removeValue(forKey: messageId)
                assistantModelNameByMessageId.removeValue(forKey: messageId)
                Task { @MainActor in
                    if !IncognitoChatSession.isIncognitoChatId(chatId),
                       !(wsManager?.ownsRecoveryPersistence(messageId: messageId) ?? false) {
                        await persistCompletedAssistantMessage(
                            assistantMessage,
                            userMessageId: userMessageIdByAssistantMessageId[messageId],
                            canonicalContent: content
                        )
                    }
                }
            } else {
                let rawPartialAssistantMessage = Message(
                    id: messageId, chatId: chatId, role: rejectionReason == nil ? .assistant : .system,
                    content: displayContent, encryptedContent: nil,
                    createdAt: createdAtForAssistantMessage(messageId),
                    updatedAt: nil, appId: resolvedCategory, isStreaming: true, embedRefs: nil,
                    modelName: resolvedModelName,
                    thinkingContent: streamingLifecycle.thinkingContent.isEmpty ? nil : streamingLifecycle.thinkingContent
                )
                let embedded = PublicChatContent.attachEmbeds(to: [rawPartialAssistantMessage])
                for (id, record) in embedded.records {
                    embedRecords[id] = record
                }
                let partialAssistantMessage = embedded.messages.first ?? rawPartialAssistantMessage
                guard ChatStreamingPresentationPolicy.shouldMaterializeAssistant(
                    content: partialAssistantMessage.content ?? displayContent,
                    thinkingContent: streamingLifecycle.thinkingContent,
                    embedCount: partialAssistantMessage.embedRefs?.count ?? embedded.records.count
                ) else {
                    isStreaming = true
                    return
                }
                appendOrReplaceTransientMessage(partialAssistantMessage)
                isStreaming = true
            }

        case .thinkingChunk(let chatId, let messageId, _):
            streamingMessageId = messageId
            isStreaming = true
            ensureStreamingAssistantMessage(chatId: chatId, messageId: messageId, metadata: nil)

        case .thinkingComplete(_, _):
            isStreaming = true

        case .messageReady(let chatId, let messageId):
            completePartialAssistantIfNeeded(chatId: chatId, messageId: messageId)
            isStreaming = false
            streamingContent = ""
            streamingMessageId = nil
            streamingLifecycle.queuedMessageText = nil

        case .preprocessingStep(_, _, _):
            isStreaming = true

        case .typingEnded(let chatId, let messageId):
            if let messageId {
                completePartialAssistantIfNeeded(chatId: chatId, messageId: messageId)
            }
            isStreaming = false
            streamingContent = ""
            streamingMessageId = nil
            streamingLifecycle.queuedMessageText = nil

        case .messageQueued(_, _, _, let message):
            isStreaming = true
            showQueuedMessage(message)

        case .cancelRequested(_, _):
            isStreaming = false
            streamingContent = ""
            streamingMessageId = nil
            streamingLifecycle.queuedMessageText = nil

        case .postProcessingCompleted(let chatId, _, let followUps, let newSuggestions, let summary, let tags, let updatedTitle, let sourceTitleVersion, let sourceMetadataVersion):
            guard chat?.id == chatId else { return }
            isStreaming = false
            followUpSuggestions = ChatFollowUpSuggestionPolicy.acceptCompletedResponse(followUps)
            Task { @MainActor in
                await sendPipeline.sendPostProcessingMetadata(
                    chatId: chatId,
                    followUpSuggestions: followUps,
                    newChatSuggestions: newSuggestions,
                    chatSummary: summary,
                    chatTags: tags,
                    updatedTitle: updatedTitle,
                    sourceTitleVersion: sourceTitleVersion,
                    sourceMetadataVersion: sourceMetadataVersion,
                    wsManager: wsManager,
                    chatStore: chatStore
                )
                if self.chat?.id == chatId, let acceptedChat = chatStore?.chat(for: chatId) {
                    self.chat = acceptedChat
                }
            }
            streamingContent = ""
            streamingMessageId = nil
            streamingLifecycle.queuedMessageText = nil

        case .error(let msg):
            error = msg
            isStreaming = false
            streamingContent = ""
            streamingMessageId = nil
            streamingLifecycle.queuedMessageText = nil
        }
    }

    private func showQueuedMessage(_ message: String?) {
        let trimmed = message?.trimmingCharacters(in: .whitespacesAndNewlines)
        streamingLifecycle.queuedMessageText = (trimmed?.isEmpty == false) ? trimmed : AppStrings.messageQueued
        queuedMessageClearTask?.cancel()
        queuedMessageClearTask = Task { @MainActor in
            try? await Task.sleep(for: .seconds(7))
            guard !Task.isCancelled else { return }
            streamingLifecycle.queuedMessageText = nil
            queuedMessageClearTask = nil
        }
    }

    private func ensureStreamingAssistantMessage(
        chatId: String,
        messageId: String,
        metadata: StreamingClient.ChatMetadata?
    ) {
        guard ChatStreamingPresentationPolicy.shouldMaterializeAssistant(
            content: streamingContent,
            thinkingContent: streamingLifecycle.thinkingContent,
            embedCount: 0
        ) else { return }
        guard !messages.contains(where: { $0.id == messageId }) else { return }
        appendOrReplaceTransientMessage(Message(
            id: messageId,
            chatId: chatId,
            role: .assistant,
            content: "",
            encryptedContent: nil,
            createdAt: createdAtForAssistantMessage(messageId),
            updatedAt: nil,
            appId: metadata?.category,
            isStreaming: true,
            embedRefs: nil,
            modelName: metadata?.modelName
        ))
    }

    private func completePartialAssistantIfNeeded(chatId: String, messageId: String) {
        guard let partial = messages.first(where: {
            $0.id == messageId && $0.isStreaming == true && ($0.content?.isEmpty == false)
        }) else { return }
        let completed = Message(
            id: partial.id,
            chatId: partial.chatId,
            role: partial.role,
            content: partial.content,
            encryptedContent: partial.encryptedContent,
            createdAt: partial.createdAt,
            updatedAt: partial.updatedAt,
            appId: partial.appId,
            isStreaming: false,
            embedRefs: partial.embedRefs,
            modelName: partial.modelName,
            piiMappings: partial.piiMappings,
            encryptedPIIMappings: partial.encryptedPIIMappings,
            thinkingContent: streamingLifecycle.thinkingContent.isEmpty
                ? partial.thinkingContent
                : streamingLifecycle.thinkingContent,
            encryptedThinkingContent: partial.encryptedThinkingContent,
            encryptedThinkingSignature: partial.encryptedThinkingSignature,
            thinkingTokenCount: partial.thinkingTokenCount
        )
        appendOrReplaceTransientMessage(completed)
        guard !IncognitoChatSession.isIncognitoChatId(chatId),
              !(wsManager?.ownsRecoveryPersistence(messageId: messageId) ?? false) else { return }
        Task { @MainActor in
            await persistCompletedAssistantMessage(
                completed,
                userMessageId: userMessageIdByAssistantMessageId[messageId]
            )
        }
    }

    private func persistCompletedAssistantMessage(
        _ message: Message,
        userMessageId: String?,
        canonicalContent: String? = nil
    ) async {
        guard !IncognitoChatSession.isIncognitoChatId(message.chatId) else { return }
        do {
            let persisted = try await sendPipeline.persistCompletedAssistantMessage(
                message,
                userMessageId: userMessageId,
                wsManager: wsManager,
                chatStore: chatStore,
                canonicalContent: canonicalContent
            )
            appendOrReplaceLocalMessage(persisted)
        } catch {
            self.error = error.localizedDescription
        }
    }

    private func appendOrReplaceLocalMessage(_ message: Message) {
        let wasAtTail = !hasNewerMessages
        let originalFirst = messages.first?.id
        if upsertRawHistoryMessage(message) { cancelOlderMessagesLoad() }
        if let index = messages.firstIndex(where: { $0.id == message.id }) {
            messages[index] = message
        } else if wasAtTail {
            messages.append(message)
        }
        messages = Array(ChatHistoryWindowPolicy.orderedUnique(messages).suffix(ChatHistoryWindowPolicy.capacity))
        if wasAtTail {
            visibleWindowEndIndex = allMessages.count
            visibleWindowStartIndex = max(0, allMessages.count - messages.count)
        } else if let originalFirst, let start = allMessages.firstIndex(where: { $0.id == originalFirst }) {
            visibleWindowStartIndex = start
            visibleWindowEndIndex = min(allMessages.count, start + messages.count)
        }
        refreshWindowBoundaries()
        chatStore?.appendMessage(message, to: message.chatId)
    }

    private func appendOrReplaceTransientMessage(_ message: Message) {
        let wasAtTail = !hasNewerMessages
        let originalFirst = messages.first?.id
        if upsertRawHistoryMessage(message) { cancelOlderMessagesLoad() }
        if let index = messages.firstIndex(where: { $0.id == message.id }) {
            messages[index] = message
        } else if wasAtTail {
            messages.append(message)
        }
        messages = Array(ChatHistoryWindowPolicy.orderedUnique(messages).suffix(ChatHistoryWindowPolicy.capacity))
        if wasAtTail {
            visibleWindowEndIndex = allMessages.count
            visibleWindowStartIndex = max(0, allMessages.count - messages.count)
        } else if let originalFirst, let start = allMessages.firstIndex(where: { $0.id == originalFirst }) {
            visibleWindowStartIndex = start
            visibleWindowEndIndex = min(allMessages.count, start + messages.count)
        }
        refreshWindowBoundaries()
    }

    /// Returns whether identity/order changed, invalidating a captured page range.
    @discardableResult
    private func upsertRawHistoryMessage(_ message: Message) -> Bool {
        if let index = allMessages.firstIndex(where: { $0.id == message.id }) {
            let previousDate = allMessages[index].createdAt
            allMessages[index] = message
            if previousDate != message.createdAt {
                allMessages = ChatHistoryWindowPolicy.orderedUnique(allMessages)
                return true
            }
            return false
        } else if allMessages.last.map({ $0.createdAt <= message.createdAt }) ?? true {
            allMessages.append(message)
        } else {
            let index = allMessages.firstIndex { $0.createdAt > message.createdAt } ?? allMessages.endIndex
            allMessages.insert(message, at: index)
        }
        return true
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

    private func subscribeToChatLifecycle(chatId: String) {
        subChatProgress = nil
        subChatApprovalRequest = nil
        if let observer = chatLifecycleObserver {
            NotificationCenter.default.removeObserver(observer)
            chatLifecycleObserver = nil
        }
        chatLifecycleObserver = NotificationCenter.default.addObserver(
            forName: .wsMessageReceived, object: nil, queue: .main
        ) { [weak self] notification in
            guard let type = notification.userInfo?["type"] as? String,
                  let raw = notification.userInfo?["raw"] as? Data,
                  let eventScope = notification.userInfo?["accountScope"] as? UUID,
                  let eventTransport = notification.userInfo?["transportGeneration"] as? Int else { return }
            Task { @MainActor [weak self] in
                guard let self, eventScope == self.accountScopeGeneration(),
                      self.wsManager?.transportGeneration == eventTransport else { return }
                await self.handleChatLifecycleEvent(type: type, raw: raw, activeChatId: chatId)
            }
        }
    }

    func handleChatLifecycleEvent(type: String, raw: Data, activeChatId: String) async {
        let decoder = JSONDecoder()
        decoder.keyDecodingStrategy = .convertFromSnakeCase
        do {
            switch type {
            case "message_deleted":
                let envelope = try decoder.decode(LifecycleEnvelope<ChatWindowMessageDeletion>.self, from: raw)
                guard let payload = envelope.payload ?? envelope.data, payload.chatId == activeChatId else { return }
                consumeForegroundMessageDeletion(chatId: payload.chatId, messageId: payload.messageId)
            case "sub_chat_confirmation_required":
                let envelope = try decoder.decode(LifecycleEnvelope<SubChatApprovalRequest>.self, from: raw)
                guard let payload = envelope.payload ?? envelope.data, payload.chatId == activeChatId else { return }
                subChatApprovalRequest = payload
            case "sub_chat_progress":
                let envelope = try decoder.decode(LifecycleEnvelope<SubChatProgress>.self, from: raw)
                guard let payload = envelope.payload ?? envelope.data, payload.chatId == activeChatId else { return }
                subChatProgress = payload
            case "sub_chat_completed":
                let envelope = try decoder.decode(LifecycleEnvelope<SubChatCompletion>.self, from: raw)
                guard let payload = envelope.payload ?? envelope.data,
                      payload.parentId == activeChatId, chat?.id == activeChatId else { return }
                await applySubChatCompletion(payload)
            case "sub_chat_confirmation_resolved":
                let envelope = try decoder.decode(LifecycleEnvelope<SubChatConfirmationResolved>.self, from: raw)
                guard let payload = envelope.payload ?? envelope.data,
                      payload.chatId == activeChatId,
                      subChatApprovalRequest?.taskId == payload.taskId else { return }
                subChatApprovalRequest = nil
            case "spawn_sub_chats":
                let envelope = try decoder.decode(LifecycleEnvelope<SpawnSubChatsPayload>.self, from: raw)
                guard let payload = envelope.payload ?? envelope.data else { return }
                await applySpawnedSubChats(payload, activeChatId: activeChatId)
            default:
                break
            }
        } catch {
            print("[ChatViewModel] Failed to decode chat lifecycle event \(type): \(error)")
        }
    }

    private func applySpawnedSubChats(_ payload: SpawnSubChatsPayload, activeChatId: String) async {
        let parentId = payload.parentId ?? payload.chatId ?? activeChatId
        let scope = accountScopeGeneration()
        let keyGeneration = ChatKeyManager.shared.cacheGeneration
        pendingSubChatSpawns = pendingSubChatSpawns.filter {
            $0.value.accountScope == scope && $0.value.keyGeneration == keyGeneration
        }
        for child in payload.subChats {
            guard !child.id.isEmpty, chatStore?.chat(for: child.id) == nil else { continue }
            if let existing = pendingSubChatSpawns[child.id] {
                // A replay must not replace the in-flight payload or move a
                // child ID to another parent while its write is suspended.
                guard existing.accountScope == scope, existing.parentID == parentId else { continue }
                continue
            }
            guard pendingSubChatSpawns.count < 32 else { continue }
            pendingSubChatSpawns[child.id] = PendingSubChatSpawn(
                eventID: UUID(), child: child, parentID: parentId,
                accountScope: scope, keyGeneration: keyGeneration
            )
        }
        await flushPendingSubChatSpawns()
    }

    private func flushPendingSubChatSpawns() async {
        guard !isFlushingSubChatSpawns, !pendingSubChatSpawns.isEmpty else { return }
        isFlushingSubChatSpawns = true
        defer { isFlushingSubChatSpawns = false }
        let scope = accountScopeGeneration()
        let keyGeneration = ChatKeyManager.shared.cacheGeneration
        pendingSubChatSpawns = pendingSubChatSpawns.filter {
            $0.value.accountScope == scope && $0.value.keyGeneration == keyGeneration
        }
        guard let socket = wsManager, socket.isConnected, let store = chatStore else { return }
        let transport = socket.transportGeneration
        for (childID, pending) in Array(pendingSubChatSpawns) {
            guard scope == accountScopeGeneration(), keyGeneration == ChatKeyManager.shared.cacheGeneration,
                  wsManager === socket, socket.transportGeneration == transport, socket.isConnected else { return }
            if store.chat(for: childID) != nil {
                pendingSubChatSpawns.removeValue(forKey: childID)
                continue
            }
            guard let parent = store.chat(for: pending.parentID),
                  ChatKeyManager.shared.hasKey(for: parent.id) || parent.encryptedChatKey?.isEmpty == false else {
                continue
            }
            do {
                let prepared = try await sendPipeline.syncSpawnedSubChat(
                    pending.child, parent: parent, wsManager: socket
                )
                try SubChatSpawnScopedStage.commitIfCurrent(isCurrent: {
                    scope == accountScopeGeneration()
                        && keyGeneration == ChatKeyManager.shared.cacheGeneration
                        && wsManager === socket && socket.transportGeneration == transport && socket.isConnected
                        && chatStore === store && store.chat(for: pending.parentID) != nil
                        && pendingSubChatSpawns[childID]?.eventID == pending.eventID
                }, commit: {
                    store.upsertChat(prepared.chat)
                    if let firstMessage = prepared.firstMessage { store.appendMessage(firstMessage, to: childID) }
                    pendingSubChatSpawns.removeValue(forKey: childID)
                })
                if let pendingCompletion = pendingSubChatCompletions.removeValue(forKey: childID),
                   pendingCompletion.scope == scope {
                    await applySubChatCompletion(pendingCompletion.payload)
                }
            } catch {
                NativeDiagnostics.failure("sub_chat_storage_failed", category: "chat_sync", level: .error, error: error)
            }
        }
    }

    private func applySubChatCompletion(_ payload: SubChatCompletion) async {
        let scope = accountScopeGeneration()
        let keyGeneration = ChatKeyManager.shared.cacheGeneration
        guard let store = chatStore, let child = store.chat(for: payload.chatId) else {
            if payload.parentId != nil, pendingSubChatCompletions.count < 32 {
                pendingSubChatCompletions[payload.chatId] = (scope, payload)
            }
            return
        }
        guard child.isSubChat == true, let parentID = child.parentId,
              payload.parentId == nil || payload.parentId == parentID else { return }
        guard let cleanSummary = SubChatBatchPreviewText.sanitize(payload.summary) else {
            completedSubChatIDs.insert(child.id)
            pendingSubChatCompletions.removeValue(forKey: child.id)
            return
        }
        if child.chatSummary == cleanSummary, child.encryptedChatSummary != nil {
            completedSubChatIDs.insert(child.id)
            pendingSubChatCompletions.removeValue(forKey: child.id)
            return
        }
        do {
            let completed = try await sendPipeline.chatWithEncryptedSubChatSummary(child, summary: cleanSummary)
            guard scope == accountScopeGeneration(), keyGeneration == ChatKeyManager.shared.cacheGeneration,
                  chatStore === store, store.chat(for: child.id)?.parentId == parentID else { return }
            store.upsertChat(completed)
            completedSubChatIDs.insert(child.id)
            pendingSubChatCompletions.removeValue(forKey: child.id)
        } catch {
            if pendingSubChatCompletions[payload.chatId] != nil || pendingSubChatCompletions.count < 32 {
                pendingSubChatCompletions[payload.chatId] = (scope, payload)
            }
            NativeDiagnostics.failure("sub_chat_summary_encryption_failed", category: "chat_sync", level: .error, error: error)
        }
    }

    private func flushPendingSubChatCompletions() async {
        let scope = accountScopeGeneration()
        pendingSubChatCompletions = pendingSubChatCompletions.filter { $0.value.scope == scope }
        for (_, pending) in Array(pendingSubChatCompletions) {
            guard scope == accountScopeGeneration() else { return }
            await applySubChatCompletion(pending.payload)
        }
    }

    func approveSubChatRequest(count: Int? = nil) async {
        guard let request = subChatApprovalRequest else { return }
        do {
            try await sendPipeline.sendSubChatConfirmation(
                chatId: request.chatId,
                taskId: request.taskId,
                action: "approve",
                approveCount: count ?? request.subChats?.count,
                wsManager: wsManager
            )
            subChatApprovalRequest = nil
        } catch {
            self.error = error.localizedDescription
        }
    }

    func cancelSubChatRequest() async {
        guard let request = subChatApprovalRequest else { return }
        do {
            try await sendPipeline.sendSubChatConfirmation(
                chatId: request.chatId,
                taskId: request.taskId,
                action: "cancel",
                approveCount: nil,
                wsManager: wsManager
            )
            subChatApprovalRequest = nil
        } catch {
            self.error = error.localizedDescription
        }
    }

    func stopSubChats() async {
        guard let chatId = chat?.id else { return }
        do {
            try await sendPipeline.sendSubChatStop(chatId: chatId, taskId: subChatProgress?.taskId, wsManager: wsManager)
        } catch {
            self.error = error.localizedDescription
        }
    }

    func deactivateActiveFocusMode() async {
        guard let currentChat = chat else { return }
        let updated = Chat(
            id: currentChat.id,
            title: currentChat.title,
            lastMessageAt: currentChat.lastMessageAt,
            createdAt: currentChat.createdAt,
            updatedAt: ISO8601DateFormatter().string(from: Date()),
            isArchived: currentChat.isArchived,
            isPinned: currentChat.isPinned,
            appId: currentChat.appId,
            category: currentChat.category,
            icon: currentChat.icon,
            chatSummary: currentChat.chatSummary,
            encryptedTitle: currentChat.encryptedTitle,
            encryptedCategory: currentChat.encryptedCategory,
            encryptedIcon: currentChat.encryptedIcon,
            encryptedChatSummary: currentChat.encryptedChatSummary,
            encryptedFollowUpRequestSuggestions: currentChat.encryptedFollowUpRequestSuggestions,
            encryptedAutoSpeakResponse: currentChat.encryptedAutoSpeakResponse,
            encryptedChatKey: currentChat.encryptedChatKey,
            messagesV: currentChat.messagesV,
            titleV: currentChat.titleV,
            draftV: currentChat.draftV,
            lastVisibleMessageId: currentChat.lastVisibleMessageId,
            parentId: currentChat.parentId,
            isSubChat: currentChat.isSubChat,
            subChatSettings: currentChat.subChatSettings,
            budgetLimit: currentChat.budgetLimit,
            budgetSpent: currentChat.budgetSpent,
            encryptedFocusPhaseState: currentChat.encryptedFocusPhaseState,
            encryptedActiveFocusId: nil,
            activeFocusId: nil
        )
        chat = updated
        chatStore?.updateActiveFocus(chatId: currentChat.id, encryptedActiveFocusId: nil, activeFocusId: nil)
        do {
            try await wsManager?.send(WSOutboundMessage(
                type: "update_encrypted_active_focus_id",
                payload: [
                    "chat_id": currentChat.id,
                    "encrypted_active_focus_id": NSNull()
                ]
            ))
        } catch {
            self.error = error.localizedDescription
        }
    }

    deinit {
        streamTask?.cancel()
        olderMessagesTask?.cancel()
        if let observer = embedRefreshObserver {
            NotificationCenter.default.removeObserver(observer)
        }
        if let observer = chatLifecycleObserver {
            NotificationCenter.default.removeObserver(observer)
        }
        if let observer = subChatKeyObserver {
            NotificationCenter.default.removeObserver(observer)
        }
    }

    // MARK: - Message actions

    func containsMessageForEdit(_ id: String) -> Bool { allMessages.contains { $0.id == id } }
    private var canMutatePersonalMessages: Bool {
        guard let chat else { return false }
        return chat.teamId == nil && chat.isSharedByOthers != true && TeamWorkspaceContext.shared.snapshot.teamID == nil
            && !IncognitoChatSession.isIncognitoChatId(chat.id) && !isStreaming
    }
    private var canForkReadableMessages: Bool {
        guard let chat, !isStreaming, !IncognitoChatSession.isIncognitoChatId(chat.id) else { return false }
        if let teamID = chat.teamId { return TeamWorkspaceContext.shared.snapshot.teamID == teamID && ChatKeyManager.shared.hasKey(for: chat.id) }
        return chat.isSharedByOthers != true && TeamWorkspaceContext.shared.snapshot.teamID == nil
    }
    private struct MessageActionFence {
        let chatID: String; let accountID: String; let scope: UUID; let server: ServerProfile
        let team: TeamWorkspaceSnapshot; let transport: Int
    }
    private func captureMessageActionFence() async -> MessageActionFence? {
        guard let chat, let socket = wsManager else { return nil }
        let scope = OfflineStore.shared.scopeGeneration, server = ServerProfile.current(), team = TeamWorkspaceContext.shared.snapshot
        let transport = socket.transportGeneration
        guard let accountID = await AuthManager.currentUserId(), self.chat?.id == chat.id,
              OfflineStore.shared.scopeGeneration == scope, ServerProfile.current() == server,
              TeamWorkspaceContext.shared.isCurrent(team), wsManager?.transportGeneration == transport else { return nil }
        return .init(chatID: chat.id, accountID: accountID, scope: scope, server: server, team: team, transport: transport)
    }
    private func requireMessageActionFence(_ captured: MessageActionFence) throws {
        try Task.checkCancellation()
        guard chat?.id == captured.chatID, OfflineStore.shared.scopeGeneration == captured.scope,
              ServerProfile.current() == captured.server, TeamWorkspaceContext.shared.isCurrent(captured.team),
              wsManager?.transportGeneration == captured.transport else { throw MessageContextActionError.staleContext }
    }
    private func completeMessagesForAction(fence: MessageActionFence, readableFork: Bool = false) async throws -> [Message] {
        try requireMessageActionFence(fence)
        guard readableFork ? canForkReadableMessages : canMutatePersonalMessages else { throw MessageContextActionError.unavailable }
        var path = "/v1/chats/\(fence.chatID)/messages"
        if readableFork, let teamID = chat?.teamId {
            var query = URLComponents(); query.queryItems = [URLQueryItem(name: "team_id", value: teamID)]
            path += "?" + (query.percentEncodedQuery ?? "")
        }
        let raw: [Message] = try await api.request(.get, path: path)
        try requireMessageActionFence(fence)
        guard raw.allSatisfy({ $0.chatId == fence.chatID }), Set(raw.map(\.id)).count == raw.count else { throw MessageContextActionError.incompleteHistory }
        let complete = await Self.decryptMessagesForDisplay(raw, chatId: fence.chatID)
        try requireMessageActionFence(fence)
        guard complete.allSatisfy({ $0.content != nil }) else { throw MessageContextActionError.incompleteHistory }
        let serverIDs = Set(complete.map(\.id))
        guard allMessages.allSatisfy({ serverIDs.contains($0.id) || $0.serverMessageId.map(serverIDs.contains) == true }) else {
            throw MessageContextActionError.incompleteHistory
        }
        return ChatHistoryWindowPolicy.orderedUnique(complete)
    }
    private func deleteOwnedMessage(_ messageID: String, fence: MessageActionFence) async throws {
        try requireMessageActionFence(fence)
        guard canMutatePersonalMessages, let socket = wsManager,
              await AuthManager.currentUserId() == fence.accountID else { throw MessageContextActionError.unavailable }
        _ = try await socket.sendAndWait(WSOutboundMessage(type: "delete_message", payload: ["chatId": fence.chatID, "messageId": messageID]),
            responseTypes: ["message_deleted", "error"],
            matching: { fields in fields["chat_id"] as? String == fence.chatID && fields["message_id"] as? String == messageID }, beforeSend: { [weak self] in
                guard let self, await AuthManager.currentUserId() == fence.accountID else { throw MessageContextActionError.staleContext }
                try self.requireMessageActionFence(fence)
            })
        try requireMessageActionFence(fence)
        try OfflineStore.shared.removeMessageIDs([messageID], from: fence.chatID, scope: fence.scope)
        chatStore?.removeMessageIDs([messageID], from: fence.chatID)
        consumeForegroundMessageDeletion(chatId: fence.chatID, messageId: messageID)
        await HighlightsManager.shared.consume(type: "message_deleted", fields: ["chat_id": fence.chatID, "message_id": messageID], scope: fence.scope)
    }
    func deleteMessage(_ messageId: String) async {
        #if DEBUG
        if isolatedHistory {
            allMessages.removeAll { $0.id == messageId }; messages.removeAll { $0.id == messageId }
            refreshWindowBoundaries(); historyWindowRevision += 1; return
        }
        #endif
        do {
            guard let fence = await captureMessageActionFence(), canMutatePersonalMessages else { throw MessageContextActionError.unavailable }
            let complete = try await completeMessagesForAction(fence: fence)
            guard complete.first?.id != messageId, complete.contains(where: { $0.id == messageId }) else { throw MessageContextActionError.unavailable }
            try await deleteOwnedMessage(messageId, fence: fence)
        } catch { self.error = AppStrings.error }
    }

    func prepareForkContext(_ messageID: String) async throws -> NativeMessageForkContext {
        guard let fence = await captureMessageActionFence(), canForkReadableMessages else { throw MessageContextActionError.unavailable }
        let complete = try await completeMessagesForAction(fence: fence, readableFork: true)
        guard let index = complete.firstIndex(where: { $0.id == messageID }) else { throw MessageContextActionError.missingBoundary }
        return .init(sourceChatID: fence.chatID, upToMessageID: messageID, defaultTitle: chat?.title ?? AppStrings.newChat,
            messageCount: index + 1, onFork: { [weak self] title in
                guard let self else { throw MessageContextActionError.staleContext }
                try self.requireMessageActionFence(fence)
                guard await self.forkFromMessage(messageID, title: title) else { throw MessageContextActionError.unavailable }
            })
    }
    @Published var forkedChatId: String?
    @discardableResult
    func forkFromMessage(_ messageId: String, title: String? = nil) async -> Bool {
        #if DEBUG
        if isolatedHistory { return false }
        #endif
        do {
            guard let fence = await captureMessageActionFence(), canForkReadableMessages,
                  let source = chat, let socket = wsManager else { throw MessageContextActionError.unavailable }
            let complete = try await completeMessagesForAction(fence: fence, readableFork: true)
            guard let index = complete.firstIndex(where: { $0.id == messageId }) else { throw MessageContextActionError.missingBoundary }
            let result = try await sendPipeline.persistFork(source: source, messages: Array(complete[...index]), socket: socket, title: title,
                validate: { [weak self] in
                    guard let self else { throw MessageContextActionError.staleContext }; try self.requireMessageActionFence(fence)
                })
            try requireMessageActionFence(fence)
            chatStore?.upsertChat(result.chat); chatStore?.setMessages(for: result.chat.id, messages: result.messages)
            forkedChatId = result.chat.id
            return true
        } catch { self.error = AppStrings.error; return false }
    }

    // MARK: - Embed loading

    func loadEmbeds(for messageIds: [String]) async {
        guard let chatId = chat?.id else { return }
        let generation = loadGeneration
        let scopeGeneration = accountScopeGeneration()
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

        // send_embed_data replaces a processing record with finalized
        // ciphertext under the same ID. Consume the newer local ChatStore row
        // before the loaded-ID fast path, otherwise the active ViewModel keeps
        // rendering its stale processing copy forever.
        if let storedEmbeds = chatStore?.embeds(for: chatId), !storedEmbeds.isEmpty {
            let localRelated = relatedEmbeds(referencedIds: referencedEmbedIds, from: storedEmbeds)
            let changedLocal = localRelated.filter { incoming in
                guard let existing = embedRecords[incoming.id] else { return true }
                return Self.embedRecordNeedsRefresh(existing: existing, incoming: incoming)
            }
            if !changedLocal.isEmpty {
                let decryptedLocal = await decryptEmbeds(
                    changedLocal,
                    chatId: chatId,
                    existingRecords: embedRecords
                )
                guard !Task.isCancelled, chat?.id == chatId, generation == loadGeneration,
                      scopeGeneration == accountScopeGeneration() else { return }
                for embed in decryptedLocal {
                    embedRecords = PublicChatContent.mergingHydratedRecords(existing: embedRecords, inline: [embed.id: embed])
                }
            }
        }

        let loadedEmbedIds = Set(embedRecords.keys)
        let referencedChildIds = childIdsReachable(from: referencedEmbedIds)
        let requiredEmbedIds = referencedEmbedIds.union(referencedChildIds)
        let hasUnresolvedCompositeParent = !EmbedRecord.unresolvedCompositeParentIds(
            referencedIds: referencedEmbedIds, from: Array(embedRecords.values),
            context: "chatViewModel.loadEmbeds").isEmpty
        let hasEncryptedUndecryptedRecord = Self.hasUndecryptedRequiredEmbed(
            ids: requiredEmbedIds,
            records: embedRecords
        )
        NativeSyncPerfLog.info(
            "phase=loadEmbedsStart chat=\(chatId.prefix(8)) requestedMessages=\(requestedMessageIds.count) referenced=\(referencedEmbedIds.count) children=\(referencedChildIds.count) loaded=\(loadedEmbedIds.count) unresolvedComposite=\(hasUnresolvedCompositeParent) encryptedUndecrypted=\(hasEncryptedUndecryptedRecord)"
        )
        let hasIncompleteReference = requiredEmbedIds.contains { id in
            embedRecords[id].map(Self.embedRecordRequiresHydration) ?? true
        }
        if !hasUnresolvedCompositeParent,
           !hasEncryptedUndecryptedRecord, !hasIncompleteReference,
           !requiredEmbedIds.isEmpty,
           requiredEmbedIds.isSubset(of: loadedEmbedIds) {
            print("[ChatViewModel][embeds] chat=\(chatId.prefix(8)) skip fetch; required already loaded=\(requiredEmbedIds.count)")
            return
        }
        do {
            if remoteHistory?.chatId == chatId {
                try await loadBoundedRemoteEmbeds(requiredEmbedIds, chatId: chatId, generation: generation)
                return
            }
            // Personal encrypted embeds use the same scoped content-batch
            // protocol as messages. There is no per-chat REST embeds endpoint.
            let batch = try await requestEmbedContentBatch(chatId: chatId, generation: generation, scope: scopeGeneration)
            guard !Task.isCancelled, chat?.id == chatId, generation == loadGeneration,
                  scopeGeneration == accountScopeGeneration() else { return }
            EmbedKeyManager.shared.store(batch.embedKeys, source: "chatEmbedContentBatch")
            OfflineStore.shared.persistEmbedKeys(batch.embedKeys)
            let fetchedEmbeds = batch.embeds(for: chatId)
            let relatedEmbeds = relatedEmbeds(referencedIds: referencedEmbedIds, from: fetchedEmbeds)
            let decrypted = await decryptEmbeds(relatedEmbeds, chatId: chatId, existingRecords: embedRecords)
            guard !Task.isCancelled, chat?.id == chatId, generation == loadGeneration,
                  scopeGeneration == accountScopeGeneration() else { return }
            embedRecords = PublicChatContent.mergingHydratedRecords(
                existing: embedRecords, inline: EmbedRecord.dictionaryById(decrypted, context: "chatViewModel.fetchedEmbeds"))
            chatStore?.upsertEmbeds(fetchedEmbeds, for: chatId)
            await CodeRunOutputStore.shared.ingestRows(batch.codeRunOutputs ?? [],
                chatId: chatId, expectedScope: scopeGeneration)
            EmbedMediaOfflineCache.prefetchEmbeds(decrypted)
            let childLinked = decrypted.filter { $0.parentEmbedId != nil || !$0.childEmbedIds.isEmpty }.count
            let rawCount = decrypted.filter { $0.rawData != nil }.count
            NativeSyncPerfLog.info(
                "phase=loadEmbedsFetched chat=\(chatId.prefix(8)) fetched=\(fetchedEmbeds.count) related=\(relatedEmbeds.count) keys=\(batch.embedKeys.count) linked=\(childLinked) decryptedRaw=\(rawCount) totalRecords=\(embedRecords.count)"
            )
        } catch {
            if remoteHistory?.chatId == chatId, generation == loadGeneration,
               scopeGeneration == accountScopeGeneration() {
                self.error = error is ChatMessageWindowError ? AppStrings.genericProcessingError : error.localizedDescription
            }
            NativeDiagnostics.failure("chat_embed_read_failed", category: "chat_sync", level: .warning, error: error)
        }
    }

    /// Cold foreground paging requests only visible embed IDs, never the full
    /// transcript. The published v1 WS response carries ciphertext and wrappers.
    private func loadBoundedRemoteEmbeds(_ ids: Set<String>, chatId: String, generation: Int) async throws {
        guard let socket = wsManager else { throw ChatContentHydrationError.websocketUnavailable }
        let fence = remoteReadFence(chatId: chatId, generation: generation)
        var fetched: [EmbedRecord] = []
        let missing = ids.filter { embedRecords[$0].map(Self.embedRecordRequiresHydration) ?? true }
        for id in missing.sorted().prefix(20) {
            guard isCurrentRemoteRead(fence) else { throw ChatMessageWindowError.staleContext }
            let response = try await socket.sendAndWait(
                WSOutboundMessage(type: "request_embed", payload: ["embed_id": id]),
                responseTypes: ["send_embed_data"],
                matching: { $0["embed_id"] as? String == id },
                preSendValidation: { [weak self] in
                    guard self?.isCurrentRemoteRead(fence) == true else { throw ChatMessageWindowError.staleContext }
                })
            guard isCurrentRemoteRead(fence), response.fields["already_encrypted"] as? Bool == true,
                  let content = response.fields["content"] as? String, !content.isEmpty,
                  let type = response.fields["type"] as? String, !type.isEmpty else { throw ChatMessageWindowError.invalidResponse }
            let fields = response.fields
            let decoder = JSONDecoder(); decoder.keyDecodingStrategy = .convertFromSnakeCase
            if let keys = fields["embed_keys"] {
                let entries = try decoder.decode([EmbedKeyRecord].self, from: JSONSerialization.data(withJSONObject: keys))
                guard entries.allSatisfy({ $0.hashedEmbedId == ChatKeyWrapperRecord.hashedChatId(for: id)
                    && !$0.encryptedEmbedKey.isEmpty }) else { throw ChatMessageWindowError.invalidResponse }
                EmbedKeyManager.shared.store(entries, source: "remoteMessageWindow")
            }
            fetched.append(EmbedRecord(id: id, type: "app-skill-use", status: .finished, data: nil,
                encryptedContent: content, encryptedType: type,
                encryptedTextPreview: fields["text_preview"] as? String,
                parentEmbedId: fields["parent_embed_id"] as? String,
                appId: fields["app_id"] as? String, skillId: fields["skill_id"] as? String,
                embedIds: (fields["embed_ids"] as? [String])?.joined(separator: "|") ?? fields["embed_ids"] as? String,
                hashedChatId: fields["chat_id"] as? String,
                versionNumber: fields["version_number"] as? Int, contentHash: fields["content_hash"] as? String,
                createdAt: nil))
        }
        let decoded = await decryptEmbeds(fetched, chatId: chatId, existingRecords: embedRecords)
        guard isCurrentRemoteRead(fence) else { throw ChatMessageWindowError.staleContext }
        embedRecords = PublicChatContent.mergingHydratedRecords(existing: embedRecords,
            inline: EmbedRecord.dictionaryById(decoded, context: "remoteMessageWindow"))
    }

    func retryVisibleEmbedHydration() async {
        await loadEmbeds(for: messages.map(\.id))
    }

    private func requestEmbedContentBatch(chatId: String, generation: Int, scope: UUID) async throws -> ChatContentBatchPayload {
        let request: (chatId: String, generation: Int, scope: UUID, id: UUID, task: Task<ChatContentBatchPayload, Error>)
        if let existing = embedContentBatchRequest, existing.chatId == chatId,
           existing.generation == generation, existing.scope == scope {
            request = existing
        } else {
            embedContentBatchRequest?.task.cancel()
            let fetcher = contentBatchFetcher
            let socket = wsManager
            let authorize: @MainActor () async throws -> Void = { [weak self] in
                try Task.checkCancellation()
                guard let self, self.chat?.id == chatId, self.loadGeneration == generation,
                      self.accountScopeGeneration() == scope else { throw CancellationError() }
            }
            let task = Task { @MainActor in
                try await authorize()
                if let fetcher { return try await fetcher(chatId) }
                guard let socket else { throw ChatContentHydrationError.websocketUnavailable }
                let response = try await socket.requestChatContentBatch(chatId: chatId, beforeSend: authorize)
                return try ChatContentBatchPayload.decode(response.fields)
            }
            request = (chatId, generation, scope, UUID(), task)
            embedContentBatchRequest = request
        }
        defer {
            if embedContentBatchRequest?.id == request.id { embedContentBatchRequest = nil }
        }
        return try await request.task.value
    }

    /// A reference/metadata row is not the content it points to. Finished sheets
    /// can have dimensions and a title before their actual markdown is available.
    static func embedRecordRequiresHydration(_ record: EmbedRecord) -> Bool {
        if case .code = record.data {
            return false
        }
        if EmbedType.normalized(rawValue: record.type) == .codeCode {
            // A code reference may include a language, filename or line count.
            // Those fields describe the file; only source completes hydration.
            return !AppleCodeEmbedContent(data: record.rawData).hasSourcePayload
        }
        if case .sheet(let sheet) = record.data {
            return sheet.markdown?.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty != false
        }
        let isSheet = record.type == "sheet" || record.type == "sheets-sheet"
            || (record.appId == "sheets" && record.skillId == "sheet")
        if isSheet {
            let raw = record.rawData ?? [:]
            return !["table", "code", "content", "markdown"].contains { key in
                (raw[key]?.value as? String)?.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty == false
            }
        }
        guard let raw = record.rawData else { return record.data == nil }
        let referenceKeys: Set<String> = ["type", "embed_id", "app_id", "skill_id", "status", "parent_embed_id", "embed_ids", "child_embed_ids"]
        return Set(raw.keys).isSubset(of: referenceKeys)
    }

    func embeds(for message: Message) -> [EmbedRecord] {
        message.embedRefs?.compactMap { ref in
            embedRecords[ref.id]
        } ?? []
    }

    /// Owner-only Finance originals for reveal controls. Never attach these to
    /// EmbedRecord or outgoing chat/embed sync payloads.
    func ownerPIIMappings(for embedId: String) -> [PIIMapping] {
        guard let chatId = chat?.id else { return [] }
        return OwnerEmbedPIIStore.shared.mappings(chatId: chatId, embedId: embedId)
    }

    func loadOwnerPIIMappings(for embedId: String) async -> [PIIMapping] {
        guard let chatId = chat?.id else { return [] }
        return await OwnerEmbedPIIStore.shared.load(chatId: chatId, embedId: embedId)
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

    static func hasUndecryptedRequiredEmbed(
        ids: Set<String>,
        records: [String: EmbedRecord]
    ) -> Bool {
        ids.compactMap { records[$0] }.contains { record in
            record.rawData == nil && (record.encryptedContent != nil || record.encryptedType != nil)
        }
    }

    static func embedRecordNeedsRefresh(existing: EmbedRecord, incoming: EmbedRecord) -> Bool {
        existing.type != incoming.type ||
            existing.status != incoming.status ||
            existing.rawData != incoming.rawData ||
            existing.encryptedContent != incoming.encryptedContent ||
            existing.encryptedType != incoming.encryptedType ||
            existing.encryptedTextPreview != incoming.encryptedTextPreview ||
            existing.parentEmbedId != incoming.parentEmbedId ||
            existing.appId != incoming.appId ||
            existing.skillId != incoming.skillId ||
            existing.embedIds != incoming.embedIds ||
            existing.versionNumber != incoming.versionNumber ||
            existing.contentHash != incoming.contentHash
    }

    private func visibleWindow(from rawMessages: [Message], anchorMessageId: String? = nil,
                               destination: ChatHistoryWindowDestination? = nil) -> [Message] {
        let current = visibleWindowStartIndex..<visibleWindowEndIndex
        let selected = ChatHistoryWindowPolicy.range(in: rawMessages,
            destination: destination ?? .initial(anchor: anchorMessageId), current: current) ?? 0..<0
        visibleWindowStartIndex = selected.lowerBound
        visibleWindowEndIndex = selected.upperBound
        return Array(rawMessages[selected])
    }

    private func resolveLoadedHistoryWindow(
        initialRaw: [Message], initialDecrypted: [Message], destination: ChatHistoryWindowDestination,
        generation: Int, navigationGeneration: Int, scopeGeneration: UUID
    ) async -> [Message]? {
        var sources = Dictionary(initialRaw.map { ($0.id, $0) }, uniquingKeysWith: { _, new in new })
        var decrypted = Dictionary(initialDecrypted.map { ($0.id, $0) }, uniquingKeysWith: { _, new in new })
        while true {
            guard !Task.isCancelled, generation == loadGeneration,
                  navigationGeneration == explicitWindowNavigationGeneration,
                  scopeGeneration == accountScopeGeneration(), let chatID = chat?.id else { return nil }
            let range = ChatHistoryWindowPolicy.range(in: allMessages, destination: destination) ?? 0..<0
            let raw = Array(allMessages[range])
            let missing = raw.filter { message in
                guard let source = sources[message.id], decrypted[message.id] != nil else { return true }
                return source.content != message.content || source.encryptedContent != message.encryptedContent
                    || source.thinkingContent != message.thinkingContent
                    || source.encryptedThinkingContent != message.encryptedThinkingContent
                    || source.encryptedPIIMappings != message.encryptedPIIMappings
                    || source.updatedAt != message.updatedAt
            }
            if !missing.isEmpty {
                let resolved = await decryptMessages(missing, chatId: chatID)
                for message in missing { sources[message.id] = message }
                for message in resolved { decrypted[message.id] = message }
                // The source may have changed during this bounded await, too.
                continue
            }
            visibleWindowStartIndex = range.lowerBound
            visibleWindowEndIndex = range.upperBound
            return raw.compactMap { decrypted[$0.id] }
        }
    }

    @discardableResult
    private func reconcileStreamingCompletion(chatId: String, authoritativeMessages: [Message]? = nil,
                                              readFence: RemoteReadFence? = nil) -> Bool {
        guard let fence = readFence ?? rawHistoryReadFence, fence.chatId == chatId,
              isCurrentRemoteRead(fence) else { return false }
        guard let completed = ChatStreamingSyncCompletionPolicy.matchingMessage(
            in: authoritativeMessages ?? allMessages, lifecycle: streamingLifecycle, chatID: chatId,
            pendingMessageIDs: pendingStreamingCompletionIDs(chatId: chatId)),
            let activeID = streamingLifecycle.messageId ?? streamingLifecycle.taskId,
            streamingLifecycle.completeFromAuthoritativeSync(messageId: activeID) else { return false }
        isStreaming = false
        streamingContent = ""
        streamingMessageId = nil
        for id in Set([activeID, completed.id]) {
            assistantMessageCreatedAtById.removeValue(forKey: id)
            assistantCategoryByMessageId.removeValue(forKey: id)
            assistantModelNameByMessageId.removeValue(forKey: id)
            userMessageIdByAssistantMessageId.removeValue(forKey: id)
        }
        // Partial pages are never an active-chat census. Publish only the exact
        // matched turn receipt under the same account/server/Team widget scope.
        if let scope = fence.processingScope {
            processingCoordinator.finished(chatID: chatId, turnID: activeID, scope: scope)
        }
        return true
    }

    private func restoreActiveStreamInRawHistory(chatId: String) {
        if reconcileStreamingCompletion(chatId: chatId) { return }
        guard isStreaming, let activeMessageId = streamingMessageId else { return }
        guard !allMessages.contains(where: { $0.id == activeMessageId }), !streamingContent.isEmpty else { return }
        upsertRawHistoryMessage(Message(
            id: activeMessageId, chatId: chatId, role: .assistant, content: streamingContent,
            encryptedContent: nil, createdAt: createdAtForAssistantMessage(activeMessageId),
            updatedAt: nil, appId: assistantCategoryByMessageId[activeMessageId] ?? chat?.category ?? chat?.appId,
            isStreaming: true, embedRefs: nil, modelName: assistantModelNameByMessageId[activeMessageId]
        ))
    }

    private func relatedEmbeds(referencedIds: Set<String>, from embeds: [EmbedRecord]) -> [EmbedRecord] {
        EmbedRecord.relatedRecords(
            referencedIds: referencedIds,
            from: embeds,
            context: "chatViewModel.relatedEmbeds"
        )
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

    private func decryptFollowUpSuggestions(for chat: Chat) async -> [String] {
        guard let encrypted = chat.encryptedFollowUpRequestSuggestions,
              let plaintext = await ChatKeyManager.shared.decryptChatField(
                chatId: chat.id,
                encryptedValue: encrypted,
                fieldName: "encrypted_follow_up_request_suggestions"
              ) else { return [] }
        return Self.decodeFollowUpSuggestions(plaintext)
    }

    static func decodeFollowUpSuggestions(_ plaintext: String) -> [String] {
        guard let data = plaintext.data(using: .utf8),
              let decoded = try? JSONSerialization.jsonObject(with: data) as? [Any] else { return [] }
        let suggestions: [String] = decoded.compactMap { value -> String? in
            guard let suggestion = value as? String else { return nil }
            let trimmed = suggestion.trimmingCharacters(in: .whitespacesAndNewlines)
            return trimmed.isEmpty ? nil : trimmed
        }
        return Array(suggestions.prefix(18))
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
        let explicit = embed.childEmbedIds.compactMap { embedRecords[$0] }
        if !explicit.isEmpty { return explicit }
        return embedRecords.values
            .filter { $0.parentEmbedId == embed.id }
            .sorted { ($0.createdAt ?? $0.id) < ($1.createdAt ?? $1.id) }
    }

    func isStreamingMessage(_ messageId: String) -> Bool {
        streamingMessageId == messageId && isStreaming
    }

    // MARK: - Attachment upload

    @discardableResult
    func uploadAttachment(
        data: Data,
        filename: String,
        trackingId: String? = nil
    ) async -> ComposerPendingEmbed? {
        guard let chatId = chat?.id else { return nil }
        guard !AnonymousFreeUsageService.shared.isAnonymousChat(chatId) else {
            ToastManager.shared.show(AppStrings.uploadSignupRequired, type: .info)
            return nil
        }
        let safeUpload = redactedUploadContentIfNeeded(data, filename: filename)
        if let textContent = safeUpload.redactedText ?? String(data: data, encoding: .utf8), isSupportedPIIRedactableTextFile(filename) {
            return registerPendingComposerEmbed(
                .document(filename: filename, textContent: textContent, piiMappings: safeUpload.piiMappings)
            )
        }
        let uploadId = trackingId ?? UUID().uuidString
        PendingUploadStore.shared.startUpload(id: uploadId, chatId: chatId, filename: filename)

        guard let upload = await uploadData(
            safeUpload.data,
            filename: filename,
            uploadId: uploadId,
            contentType: Self.contentType(for: filename, fallback: "application/octet-stream"),
            markFinishedOnSuccess: false
        ) else { return nil }
        let embed = registerPendingComposerEmbed(
            upload,
            localData: safeUpload.data,
            transcription: nil,
            duration: nil,
            piiMappings: safeUpload.piiMappings,
            textContent: safeUpload.redactedText
        )
        PendingUploadStore.shared.markFinished(id: uploadId)
        return embed
    }

    private struct RedactedUploadContent {
        let data: Data
        let piiMappings: [PIIMapping]
        let redactedText: String?
    }

    private func redactedUploadContentIfNeeded(_ data: Data, filename: String) -> RedactedUploadContent {
        guard isSupportedPIIRedactableTextFile(filename),
              let text = String(data: data, encoding: .utf8) else {
            return RedactedUploadContent(data: data, piiMappings: [], redactedText: nil)
        }
        let redaction = PIIDetector.redactionResult(
            in: text,
            options: PIIPrivacySettingsStore.shared.detectionOptions()
        )
        guard !redaction.mappings.isEmpty,
              let redactedData = redaction.redactedText.data(using: .utf8) else {
            return RedactedUploadContent(data: data, piiMappings: [], redactedText: nil)
        }
        print("[Chat] Redacted \(redaction.mappings.count) PII item(s) before uploading supported text attachment")
        return RedactedUploadContent(
            data: redactedData,
            piiMappings: redaction.mappings,
            redactedText: redaction.redactedText
        )
    }

    private func isSupportedPIIRedactableTextFile(_ filename: String) -> Bool {
        let supportedExtensions: Set<String> = [
            "txt", "md", "markdown", "csv", "tsv", "json", "jsonl", "xml", "html", "htm", "log",
            "yaml", "yml", "toml", "ini", "env", "conf", "config", "properties",
            "js", "jsx", "ts", "tsx", "svelte", "css", "scss", "sass", "less",
            "py", "rb", "php", "java", "kt", "kts", "swift", "go", "rs", "c", "h", "cpp", "hpp",
            "cs", "m", "mm", "sh", "bash", "zsh", "fish", "ps1", "sql", "r", "lua", "dart"
        ]
        let ext = URL(fileURLWithPath: filename).pathExtension.lowercased()
        return supportedExtensions.contains(ext)
    }

    func uploadRecording(
        url: URL,
        duration: TimeInterval,
        waveform: AudioRecordingWaveform? = nil,
        realtimeResult: AudioRecordingRealtimeResultProvider? = nil,
        trackingId: String? = nil
    ) async -> ComposerPendingEmbed? {
        guard let chatId = chat?.id else { return nil }
        let scope = AudioRecordingUploadScope.capture()
        guard let embed = await AudioRecordingUploadService.prepare(
            url: url,
            duration: duration,
            chatId: chatId,
            waveform: waveform,
            realtimeResult: realtimeResult,
            trackingId: trackingId
        ) else { return nil }
        guard scope.isCurrent, chat?.id == chatId, !Task.isCancelled else { return nil }
        return registerPendingComposerEmbed(embed)
    }

    private func uploadData(
        _ data: Data,
        filename: String,
        uploadId: String,
        contentType: String,
        markFinishedOnSuccess: Bool
    ) async -> UploadFileResponse? {
        guard let chatId = chat?.id else { return nil }

        do {
            let responseData = try await APIClient.shared.uploadFile(
                data: data,
                filename: filename,
                contentType: contentType,
                chatId: chatId
            )
            let decoder = JSONDecoder()
            decoder.keyDecodingStrategy = .convertFromSnakeCase
            let upload = try decoder.decode(UploadFileResponse.self, from: responseData)
            PendingUploadStore.shared.updateProgress(id: uploadId, progress: 1.0)
            if markFinishedOnSuccess {
                PendingUploadStore.shared.markFinished(id: uploadId)
            }
            return upload
        } catch {
            NativeDiagnostics.error(
                "Composer attachment upload failed: \(type(of: error))",
                category: "apple_composer"
            )
            PendingUploadStore.shared.markError(id: uploadId, message: AppStrings.error)
            return nil
        }
    }

    func uploadFile(url: URL) async -> ComposerPendingEmbed? {
        if let chatId = chat?.id, AnonymousFreeUsageService.shared.isAnonymousChat(chatId) {
            ToastManager.shared.show(AppStrings.uploadSignupRequired, type: .info)
            return nil
        }
        guard let data = try? Data(contentsOf: url) else { return nil }
        return await uploadAttachment(data: data, filename: url.lastPathComponent)
    }

    func uploadFile(data: Data, filename: String) async -> ComposerPendingEmbed? {
        if let chatId = chat?.id, AnonymousFreeUsageService.shared.isAnonymousChat(chatId) {
            ToastManager.shared.show(AppStrings.uploadSignupRequired, type: .info)
            return nil
        }
        return await uploadAttachment(data: data, filename: filename)
    }

    func removePendingComposerEmbed(id: String) {
        pendingComposerEmbeds.removeAll { $0.id == id }
    }

    #if DEBUG
    func seedUITestPendingComposerEmbed() -> ComposerPendingEmbed? {
        guard pendingComposerEmbeds.isEmpty else { return pendingComposerEmbeds.first }
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
        return registerPendingComposerEmbed(
            upload,
            localData: Data(base64Encoded: "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="),
            transcription: nil,
            duration: nil,
            piiMappings: [],
            textContent: nil
        )
    }
    #endif

    private func registerPendingComposerEmbed(
        _ upload: UploadFileResponse,
        localData: Data?,
        transcription: TranscriptionMetadata?,
        duration: TimeInterval?,
        piiMappings: [PIIMapping],
        textContent: String?
    ) -> ComposerPendingEmbed {
        let embed = ComposerPendingEmbed.from(
            upload: upload,
            localData: localData,
            transcription: transcription,
            duration: duration,
            piiMappings: piiMappings,
            textContent: textContent
        )
        return registerPendingComposerEmbed(embed)
    }

    @discardableResult
    private func registerPendingComposerEmbed(_ embed: ComposerPendingEmbed) -> ComposerPendingEmbed {
        pendingComposerEmbeds.removeAll { $0.id == embed.id }
        pendingComposerEmbeds.append(embed)
        embedRecords[embed.record.id] = embed.record
        if let chatId = chat?.id {
            chatStore?.upsertEmbeds([embed.record], for: chatId)
        }
        return embed
    }

    private static func contentType(for filename: String, fallback: String) -> String {
        switch URL(fileURLWithPath: filename).pathExtension.lowercased() {
        case "jpg", "jpeg": return "image/jpeg"
        case "png": return "image/png"
        case "gif": return "image/gif"
        case "webp": return "image/webp"
        case "heic": return "image/heic"
        case "heif": return "image/heif"
        case "svg": return "image/svg+xml"
        case "pdf": return "application/pdf"
        case "m4a", "mp4": return "audio/mp4"
        case "webm": return "audio/webm"
        case "ogg": return "audio/ogg"
        case "mp3": return "audio/mpeg"
        case "wav": return "audio/wav"
        case "aac": return "audio/aac"
        default: return fallback
        }
    }
}

struct ChatContentBatchPayload: Decodable {
    let messagesByChatId: [String: [String]]
    let versionsByChatId: [String: [String: Int]]
    let embeds: [EmbedRecord]
    let embedKeys: [EmbedKeyRecord]
    let chatKeyWrappers: [ChatKeyWrapperRecord]
    let codeRunOutputs: [CodeRunOutputSyncedPayload]?

    static func decode(_ fields: [String: Any]) throws -> ChatContentBatchPayload {
        guard JSONSerialization.isValidJSONObject(fields) else {
            throw ChatContentHydrationError.invalidResponse
        }
        let data = try JSONSerialization.data(withJSONObject: fields)
        let decoder = JSONDecoder()
        decoder.keyDecodingStrategy = .convertFromSnakeCase
        return try decoder.decode(ChatContentBatchPayload.self, from: data)
    }

    func messages(for chatId: String) throws -> [Message] {
        guard let encodedMessages = messagesByChatId[chatId] else {
            throw ChatContentHydrationError.invalidResponse
        }
        let decoder = JSONDecoder()
        decoder.keyDecodingStrategy = .convertFromSnakeCase
        return try encodedMessages.map { encoded in
            guard let data = encoded.data(using: .utf8) else {
                throw ChatContentHydrationError.invalidResponse
            }
            return try decoder.decode(Message.self, from: data)
        }
    }

    func messagesVersion(for chatId: String) -> Int? {
        versionsByChatId[chatId]?["messages_v"]
    }

    static func mergedMessages(snapshot: [Message], preserving existing: [Message]) -> [Message] {
        var messagesById = existing.reduce(into: [String: Message]()) { $0[$1.id] = $1 }
        for var message in snapshot {
            let local = message.localBodySource(canonical: messagesById[message.id],
                alias: message.serverMessageId.flatMap { messagesById[$0] })
            if let alias = message.serverMessageId, alias != message.id,
               messagesById[alias]?.chatId == message.chatId, messagesById[alias]?.role == message.role {
                messagesById.removeValue(forKey: alias)
            }
            if message.content == nil, let local, local.chatId == message.chatId, local.role == message.role,
               message.encryptedContent != nil, message.encryptedContent == local.encryptedContent {
                message.content = local.content
            }
            messagesById[message.id] = message
        }
        return messagesById.values.sorted { $0.createdAt < $1.createdAt }
    }

    func embeds(for chatId: String) -> [EmbedRecord] {
        let hashedChatId = ChatKeyWrapperRecord.hashedChatId(for: chatId)
        return embeds.filter { embed in
            embed.hashedChatId == hashedChatId ||
                embed.rawData?["chat_id"]?.value as? String == chatId ||
                embed.rawData?["chatId"]?.value as? String == chatId
        }
    }

    private enum CodingKeys: String, CodingKey {
        case messagesByChatId
        case versionsByChatId
        case embeds
        case embedKeys
        case chatKeyWrappers
        case codeRunOutputs
    }
}

struct UploadFileResponse: Decodable, Equatable, Sendable {
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

struct UploadedFileVariant: Decodable, Equatable, Sendable {
    let s3Key: String
    let sizeBytes: Int?
    let width: Int?
    let height: Int?
    let format: String?
    let encryption: String?

    init(s3Key: String, sizeBytes: Int?, width: Int?, height: Int?, format: String?, encryption: String? = nil) {
        self.s3Key = s3Key
        self.sizeBytes = sizeBytes
        self.width = width
        self.height = height
        self.format = format
        self.encryption = encryption
    }
}

struct AudioRecordingWaveform: Codable, Equatable, Sendable {
    static let version = 1
    static let kind = "rms-envelope"
    static let sampleCount = 128

    let version: Int
    let kind: String
    let samples: [Int]
    let durationSeconds: TimeInterval?

    init?(normalizedLevels: [Double], duration: TimeInterval?) {
        let levels = normalizedLevels.filter(\.isFinite)
        guard !levels.isEmpty else { return nil }
        let resampled = (0..<Self.sampleCount).map { index in
            let start = min(levels.count - 1, index * levels.count / Self.sampleCount)
            let end = min(levels.count, max(start + 1, (index + 1) * levels.count / Self.sampleCount))
            let sumOfSquares = levels[start..<end].reduce(0.0) { partial, rawLevel in
                let level = min(1, max(0, rawLevel))
                return partial + level * level
            }
            return Int((sqrt(sumOfSquares / Double(max(1, end - start))) * 100).rounded())
        }
        self.init(samples: resampled, duration: duration)
    }

    init?(samples: [Int], duration: TimeInterval?) {
        guard !samples.isEmpty else { return nil }
        version = Self.version
        kind = Self.kind
        self.samples = samples.map { min(100, max(0, $0)) }
        durationSeconds = duration.flatMap { $0.isFinite && $0 > 0 ? $0 : nil }
    }

    var contentObject: [String: Any] {
        var object: [String: Any] = [
            "version": version,
            "kind": kind,
            "samples": samples
        ]
        if let durationSeconds { object["duration_seconds"] = durationSeconds }
        return object
    }
}

struct AudioRecordingRealtimeResult: Equatable, Sendable {
    let title: String?
    let transcript: String
    let transcriptOriginal: String
    let transcriptCorrected: String?
    let useCorrected: Bool
    let model: String
    let correctionModel: String?

    var transcriptionMetadata: TranscriptionMetadata {
        TranscriptionMetadata(
            title: title,
            transcript: transcript,
            transcriptOriginal: transcriptOriginal,
            transcriptCorrected: transcriptCorrected,
            useCorrected: useCorrected,
            model: model,
            correctionModel: correctionModel,
            waveform: nil
        )
    }
}

typealias AudioRecordingRealtimeResultProvider = @MainActor @Sendable () async -> AudioRecordingRealtimeResult?

struct AudioRecordingUploadPipelineResult: Equatable, Sendable {
    let upload: UploadFileResponse
    let transcription: TranscriptionMetadata
}

@MainActor
enum AudioRecordingUploadPipeline {
    typealias Upload = @MainActor @Sendable () async -> UploadFileResponse?
    typealias BatchTranscription = @MainActor @Sendable (UploadFileResponse) async -> TranscriptionMetadata?

    static func run(
        waveform: AudioRecordingWaveform?,
        realtimeResult: AudioRecordingRealtimeResultProvider?,
        upload: @escaping Upload,
        batchTranscription: @escaping BatchTranscription,
        batchTimeout: Duration = .seconds(20)
    ) async -> AudioRecordingUploadPipelineResult? {
        let realtimeTask = Task { @MainActor in
            await resolveRealtime(realtimeResult)
        }
        defer { realtimeTask.cancel() }
        return await withTaskCancellationHandler {
            async let uploaded = upload()
            guard let uploadResult = await uploaded, !Task.isCancelled else { return nil }
            let transcription: TranscriptionMetadata
            let realtimeResult = await realtimeTask.value
            guard !Task.isCancelled else { return nil }
            if let realtimeResult {
                transcription = realtimeResult.transcriptionMetadata.withWaveform(waveform)
            } else {
                // A failed or stalled transcription must not strand an already
                // uploaded recording in the composer. Keep its playable file and
                // waveform even when there is no transcript to display.
                let batchResult = await boundedBatchTranscription(
                    uploadResult, operation: batchTranscription, timeout: batchTimeout
                )
                guard !Task.isCancelled else { return nil }
                transcription = (batchResult ?? TranscriptionMetadata(transcript: nil))
                    .withWaveform(waveform ?? batchResult?.waveform)
            }
            return AudioRecordingUploadPipelineResult(upload: uploadResult, transcription: transcription)
        } onCancel: {
            realtimeTask.cancel()
        }
    }

    private static func boundedBatchTranscription(
        _ upload: UploadFileResponse,
        operation: @escaping BatchTranscription,
        timeout: Duration
    ) async -> TranscriptionMetadata? {
        await withTaskGroup(of: TranscriptionMetadata?.self) { group in
            group.addTask { await operation(upload) }
            group.addTask {
                try? await Task.sleep(for: timeout)
                return nil
            }
            let result = await group.next() ?? nil
            group.cancelAll()
            return result
        }
    }

    private static func resolveRealtime(
        _ realtimeResult: AudioRecordingRealtimeResultProvider?
    ) async -> AudioRecordingRealtimeResult? {
        await realtimeResult?()
    }
}

// A late audio result may belong to a closed account or a different server.
// This fence protects upload/transcription presentation; it never resends a message.
struct AudioRecordingUploadScope: Equatable {
    let accountGeneration: UUID
    let apiURL: URL
    let uploadURL: URL
    @MainActor static func capture() -> Self {
        let profile = ServerProfile.current()
        return .init(accountGeneration: OfflineStore.shared.scopeGeneration, apiURL: profile.apiBaseURL, uploadURL: profile.uploadBaseURL)
    }
    @MainActor var isCurrent: Bool { self == Self.capture() }
}

@MainActor
enum AudioRecordingUploadService {
    static let batchTranscriptionPath = "/v1/apps/audio/skills/transcribe"

    static func prepare(
        url: URL,
        duration: TimeInterval,
        chatId: String,
        waveform: AudioRecordingWaveform? = nil,
        realtimeResult: AudioRecordingRealtimeResultProvider? = nil,
        trackingId: String? = nil,
        uploadOperation: AudioRecordingUploadPipeline.Upload? = nil
    ) async -> ComposerPendingEmbed? {
        guard !AnonymousFreeUsageService.shared.isAnonymousChat(chatId) else {
            ToastManager.shared.show(AppStrings.uploadSignupRequired, type: .info)
            return nil
        }
        let scope = AudioRecordingUploadScope.capture()
        guard let data = try? Data(contentsOf: url), !data.isEmpty, !Task.isCancelled else { return nil }

        let uploadId = trackingId ?? UUID().uuidString
        let filename = url.lastPathComponent
        let mimeType = "audio/mp4"
        PendingUploadStore.shared.startUpload(id: uploadId, chatId: chatId, filename: AppStrings.audioRecording)

        let pipeline = await AudioRecordingUploadPipeline.run(
            waveform: waveform,
            realtimeResult: realtimeResult,
            upload: {
                guard scope.isCurrent, !Task.isCancelled else { return nil }
                let result: UploadFileResponse?
                if let uploadOperation {
                    result = await uploadOperation()
                } else {
                    result = await upload(data: data, filename: filename, contentType: mimeType,
                        chatId: chatId, uploadId: uploadId)
                }
                guard scope.isCurrent, !Task.isCancelled else { return nil }
                if result != nil {
                    PendingUploadStore.shared.updateStatus(id: uploadId, status: .transcribing)
                }
                return result
            },
            batchTranscription: { upload in
                guard scope.isCurrent, !Task.isCancelled else { return nil }
                return await batchTranscription(
                    upload: upload,
                    filename: filename,
                    mimeType: mimeType,
                    chatId: chatId
                )
            }
        )

        guard scope.isCurrent, !Task.isCancelled else {
            PendingUploadStore.shared.cancelUpload(id: uploadId)
            return nil
        }
        guard let pipeline else {
            if PendingUploadStore.shared.activeUploads[uploadId]?.status.isError != true {
                PendingUploadStore.shared.markError(id: uploadId, message: AppStrings.uploadProgressError)
            }
            return nil
        }
        let embed = ComposerPendingEmbed.from(
            upload: pipeline.upload,
            localData: data,
            transcription: pipeline.transcription,
            duration: duration,
            piiMappings: [],
            textContent: nil
        )
        PendingUploadStore.shared.markFinished(id: uploadId)
        return embed
    }

    private static func upload(
        data: Data,
        filename: String,
        contentType: String,
        chatId: String,
        uploadId: String
    ) async -> UploadFileResponse? {
        do {
            let responseData = try await APIClient.shared.uploadFile(
                data: data,
                filename: filename,
                contentType: contentType,
                chatId: chatId
            )
            let decoder = JSONDecoder()
            decoder.keyDecodingStrategy = .convertFromSnakeCase
            let upload = try decoder.decode(UploadFileResponse.self, from: responseData)
            PendingUploadStore.shared.updateProgress(id: uploadId, progress: 1.0)
            return upload
        } catch {
            if Task.isCancelled || error is CancellationError || (error as? URLError)?.code == .cancelled {
                return nil
            }
            NativeDiagnostics.error(
                "Composer recording upload failed category=\(failureCategory(error))",
                category: "apple_composer"
            )
            let message = failureMessage(error)
            PendingUploadStore.shared.markError(id: uploadId, message: message)
            return nil
        }
    }

    static func failureMessage(_ error: Error) -> String {
        if case APIError.httpError(status: 401, message: _) = error {
            return AppStrings.localized("settings.app_settings_memories.authentication_required")
        }
        return AppStrings.uploadProgressError
    }

    // Do not record server detail, transcript, filenames, keys, or cookie values.
    static func failureCategory(_ error: Error) -> String {
        if case APIError.httpError(let status, _) = error { return "http_\(status)" }
        if let error = error as? URLError { return "url_\(error.code.rawValue)" }
        if error is DecodingError { return "response_decode" }
        if error is CancellationError { return "cancelled" }
        return "transport"
    }

    private static func batchTranscription(
        upload: UploadFileResponse,
        filename: String,
        mimeType: String,
        chatId: String
    ) async -> TranscriptionMetadata? {
        let s3Key = upload.files["original"]?.s3Key ?? upload.files.values.first?.s3Key
        guard let s3Key else { return nil }

        let requestId = UUID().uuidString
        let request: [String: Any] = [
            "requests": [[
                "id": requestId,
                "embed_id": upload.embedId,
                "s3_key": s3Key,
                "s3_base_url": upload.s3BaseUrl,
                "aes_key": upload.aesKey,
                "aes_nonce": upload.aesNonce,
                "vault_wrapped_aes_key": upload.vaultWrappedAesKey,
                "filename": filename,
                "mime_type": mimeType,
                "chat_id": chatId
            ]]
        ]

        do {
            let response: TranscribeSkillResponse = try await APIClient.shared.request(
                .post,
                path: batchTranscriptionPath,
                body: request
            )
            return response.data.results.first?.results.first
        } catch {
            guard !Task.isCancelled, !(error is CancellationError), (error as? URLError)?.code != .cancelled else { return nil }
            NativeDiagnostics.error(
                "Composer recording transcription failed category=\(failureCategory(error))",
                category: "apple_composer"
            )
            return nil
        }
    }
}

struct TranscriptionMetadata: Decodable, Equatable, Sendable {
    let title: String?
    let transcript: String?
    let transcriptOriginal: String?
    let transcriptCorrected: String?
    let useCorrected: Bool?
    let model: String?
    let correctionModel: String?
    let waveform: AudioRecordingWaveform?

    init(
        title: String? = nil,
        transcript: String?,
        transcriptOriginal: String? = nil,
        transcriptCorrected: String? = nil,
        useCorrected: Bool? = nil,
        model: String? = nil,
        correctionModel: String? = nil,
        waveform: AudioRecordingWaveform? = nil
    ) {
        self.title = title
        self.transcript = transcript
        self.transcriptOriginal = transcriptOriginal
        self.transcriptCorrected = transcriptCorrected
        self.useCorrected = useCorrected
        self.model = model
        self.correctionModel = correctionModel
        self.waveform = waveform
    }

    var displayTranscript: String? {
        if useCorrected == true, let transcriptCorrected, !transcriptCorrected.isEmpty {
            return transcriptCorrected
        }
        return transcript
    }

    func withWaveform(_ waveform: AudioRecordingWaveform?) -> TranscriptionMetadata {
        TranscriptionMetadata(
            title: title,
            transcript: transcript,
            transcriptOriginal: transcriptOriginal,
            transcriptCorrected: transcriptCorrected,
            useCorrected: useCorrected,
            model: model,
            correctionModel: correctionModel,
            waveform: waveform
        )
    }
}

struct ComposerEmbedReferenceScope: Equatable {
    let accountScope: UUID
    let server: String
    let teamID: String?
    let teamEpoch: UInt64

    @MainActor static var current: Self {
        let team = TeamWorkspaceContext.shared.snapshot
        return Self(accountScope: OfflineStore.shared.scopeGeneration,
                    server: ServerProfile.current().apiBaseURL.absoluteString,
                    teamID: team.teamID, teamEpoch: team.epoch)
    }
}

enum ComposerEmbedStorageDisposition: Equatable {
    case requiredEncryptedBundle
    // A saved/decrypted local record selected by the user. This provenance does
    // not itself claim a fresh server availability receipt.
    case existingStoredReference(ComposerEmbedReferenceScope)
}

struct ComposerEmbedStorageError: LocalizedError, Equatable {
    enum Reason: Equatable, Sendable { case missingContent, staleReference, changedReference }
    let reason: Reason
    let embedID: String
    private let description: String
    var errorDescription: String? { description }

    // Capture translated text on the main actor; LocalizedError consumers can
    // then read its immutable description safely from any thread.
    @MainActor static func missingRequiredContent(_ id: String) -> Self {
        Self(reason: .missingContent, embedID: id, description: AppStrings.chatStorageMissingAttachmentContent)
    }
    @MainActor static func staleStoredReference(_ id: String) -> Self {
        Self(reason: .staleReference, embedID: id, description: AppStrings.chatStorageStaleAttachmentReference)
    }
    @MainActor static func changedStoredReference(_ id: String) -> Self {
        Self(reason: .changedReference, embedID: id, description: AppStrings.chatStorageChangedAttachmentReference)
    }
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
    let piiMappings: [PIIMapping]
    let storageDisposition: ComposerEmbedStorageDisposition

    init(id: String, type: String, referenceType: String, status: String, content: String?,
         textPreview: String?, record: EmbedRecord, localData: Data?, filename: String,
         size: Int, piiMappings: [PIIMapping],
         storageDisposition: ComposerEmbedStorageDisposition = .requiredEncryptedBundle) {
        self.id = id; self.type = type; self.referenceType = referenceType; self.status = status
        self.content = content; self.textPreview = textPreview; self.record = record
        self.localData = localData; self.filename = filename; self.size = size
        self.piiMappings = piiMappings; self.storageDisposition = storageDisposition
    }

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

    static func fromURL(_ embed: BackgroundPreparedEmbed) -> ComposerPendingEmbed {
        let record = EmbedRecord(
            id: embed.id, type: embed.type, status: .finished,
            data: .raw(embed.content.mapValues { AnyCodable($0) }),
            parentEmbedId: nil, appId: embed.type == "video" ? "videos" : "web",
            skillId: nil, embedIds: nil, createdAt: String(Int(Date().timeIntervalSince1970))
        )
        return ComposerPendingEmbed(
            id: embed.id, type: embed.type, referenceType: embed.referenceType,
            status: embed.status, content: jsonString(embed.content), textPreview: embed.textPreview,
            record: record, localData: nil, filename: embed.textPreview ?? "", size: 0, piiMappings: []
        )
    }

    @MainActor
    static func restoredRecording(from record: EmbedRecord) -> ComposerPendingEmbed? {
        guard record.type == "audio-recording", let raw = record.rawData else { return nil }
        let object = raw.mapValues(\.value)
        guard JSONSerialization.isValidJSONObject(object),
              let encoded = try? JSONSerialization.data(withJSONObject: object, options: [.sortedKeys]),
              let content = String(data: encoded, encoding: .utf8) else { return nil }
        let filename = raw["filename"]?.value as? String ?? AppStrings.audioRecording
        let preview = raw["title"]?.value as? String
            ?? raw["transcript_corrected"]?.value as? String
            ?? raw["transcript"]?.value as? String
        return ComposerPendingEmbed(
            id: record.id,
            type: record.type,
            referenceType: "audio-recording",
            status: record.status.rawValue,
            content: content,
            textPreview: preview,
            record: record,
            localData: nil,
            filename: filename,
            size: 0,
            piiMappings: []
        )
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
            localData: Data(base64Encoded: "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="),
            transcription: nil,
            duration: nil
        )
    }
    #endif

    static func from(
        upload: UploadFileResponse,
        localData: Data?,
        transcription: TranscriptionMetadata?,
        duration: TimeInterval?,
        piiMappings: [PIIMapping] = [],
        textContent: String? = nil
    ) -> ComposerPendingEmbed {
        let classification = ComposerUploadClassification(upload: upload)
        let contentObject = classification.contentObject(
            upload: upload,
            transcription: transcription,
            duration: duration,
            textContent: textContent
        )
        let content = classification.shouldSendContent ? jsonString(contentObject) : nil
        let preview = transcription?.title ?? transcription?.displayTranscript ?? upload.filename
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
            size: localData?.count ?? upload.files.values.compactMap(\.sizeBytes).max() ?? 0,
            piiMappings: piiMappings
        )
    }

    static func document(filename: String, textContent: String, piiMappings: [PIIMapping]) -> ComposerPendingEmbed {
        let embedId = UUID().uuidString.lowercased()
        let now = String(Int(Date().timeIntervalSince1970))
        let contentObject: [String: Any] = [
            "app_id": "docs",
            "type": "file",
            "status": "finished",
            "filename": filename,
            "title": filename,
            "content": textContent,
            "word_count": textContent.split { $0.isWhitespace }.count
        ]
        let content = jsonString(contentObject)
        let record = EmbedRecord(
            id: embedId,
            type: "docs-doc",
            status: .finished,
            data: .raw(contentObject.mapValues { AnyCodable($0) }),
            parentEmbedId: nil,
            appId: "docs",
            skillId: nil,
            embedIds: nil,
            createdAt: now
        )
        return ComposerPendingEmbed(
            id: embedId,
            type: "docs-doc",
            referenceType: "docs-doc",
            status: "finished",
            content: content,
            textPreview: filename,
            record: record,
            localData: Data(textContent.utf8),
            filename: filename,
            size: textContent.utf8.count,
            piiMappings: piiMappings
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
            shouldSendContent = true
        } else {
            embedType = "docs-doc"
            referenceType = "file"
            status = "finished"
            appId = "docs"
            skillId = nil
            shouldSendContent = true
        }
    }

    func contentObject(upload: UploadFileResponse, transcription: TranscriptionMetadata?, duration: TimeInterval?, textContent: String?) -> [String: Any] {
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
                if let encryption = variant.encryption { item["encryption"] = encryption }
                return item
            },
            "aes_key": upload.aesKey,
            "aes_nonce": upload.aesNonce,
            "vault_wrapped_aes_key": upload.vaultWrappedAesKey
        ]
        if let skillId { object["skill_id"] = skillId }
        // The AI pipeline resolves uploaded images by their user-facing file
        // reference. Web uploads persist the same field, and the backend uses
        // it to build the filename -> embed ID index for images.view.
        if appId == "images" { object["embed_ref"] = upload.filename }
        if let contentHash = upload.contentHash { object["content_hash"] = contentHash }
        if let pageCount = upload.pageCount { object["page_count"] = pageCount }
        if let transcription {
            if let title = transcription.title { object["title"] = title }
            if let transcript = transcription.transcript { object["transcript"] = transcript }
            if let displayTranscript = transcription.displayTranscript { object["transcription"] = displayTranscript }
            if let transcriptOriginal = transcription.transcriptOriginal { object["transcript_original"] = transcriptOriginal }
            if let transcriptCorrected = transcription.transcriptCorrected { object["transcript_corrected"] = transcriptCorrected }
            if let useCorrected = transcription.useCorrected { object["use_corrected"] = useCorrected }
            if let model = transcription.model { object["model"] = model }
            if let correctionModel = transcription.correctionModel { object["correction_model"] = correctionModel }
            if let waveform = transcription.waveform { object["waveform"] = waveform.contentObject }
        }
        if let duration { object["duration"] = duration }
        if let textContent, !textContent.isEmpty, appId == "docs" {
            object["content"] = textContent
            object["title"] = upload.filename
            object["word_count"] = textContent.split { $0.isWhitespace }.count
        }
        return object
    }
}

private struct TranscribeSkillResponse: Decodable {
    struct ResponseData: Decodable {
        struct ResultGroup: Decodable {
            let results: [TranscriptionMetadata]
        }
        let results: [ResultGroup]
    }
    let data: ResponseData
}

/// A bounded cache of bundled public fixtures. Never accepts account chat IDs
/// and keeps only one locale, so language switches cannot reuse translated rows.
@MainActor
struct LocalizedPublicChatCache<Value> {
    private var locale: String?
    private var values: [String: Value] = [:]

    mutating func value(for id: String, locale: String, allowedIDs: Set<String>,
                        build: () -> Value?) -> Value? {
        guard allowedIDs.contains(id) else { return nil }
        if self.locale != locale { values.removeAll(); self.locale = locale }
        if let cached = values[id] { return cached }
        guard let value = build() else { return nil }
        values[id] = value
        return value
    }
}

@MainActor
enum PublicChatContent {
    static func mergingHydratedRecords(
        existing: [String: EmbedRecord], inline: [String: EmbedRecord]
    ) -> [String: EmbedRecord] {
        existing.merging(inline) { hydrated, parsed in
            // A user's canonical JSON reference contains only type/embed_id.
            // Parsing it must not replace an uploaded or decrypted record with
            // an empty shell during chat opening or history paging.
            let parsedIsReference = ChatViewModel.embedRecordRequiresHydration(parsed)
            if parsedIsReference {
                let carriesNewCiphertext = parsed.encryptedContent != nil
                    && parsed.encryptedContent != hydrated.encryptedContent
                if !carriesNewCiphertext && !ChatViewModel.embedRecordRequiresHydration(hydrated) {
                    return hydrated
                }
                if parsed.encryptedContent == nil && hydrated.encryptedContent != nil { return hydrated }
            }
            return parsed
        }
    }

    struct PublicChat {
        let chat: Chat
        let messages: [Message]
        let followUpSuggestions: [String]
        let embedRecords: [String: EmbedRecord]
    }

    private static let publicChatIDs: Set<String> = [
        "announcements-introducing-openmates-v09",
        "legal-privacy", "legal-terms", "legal-imprint",
        "example-gigantic-airplanes", "example-artemis-ii-mission",
        "example-beautiful-single-page-html", "example-eu-chat-control-law",
        "example-flights-berlin-bangkok", "example-creativity-drawing-meetups-berlin"
    ]
    private static var cache = LocalizedPublicChatCache<PublicChat>()

    static func isPublicChat(_ id: String) -> Bool { publicChatIDs.contains(id) }

    static func chat(for id: String) -> PublicChat? {
        cache.value(for: id, locale: LocalizationManager.shared.currentLanguage.code,
                    allowedIDs: publicChatIDs) { buildChat(for: id) }
    }

    private static func buildChat(for id: String) -> PublicChat? {
        let createdAt = "2026-04-20T12:00:00Z"

        switch id {
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
            // Bind public speech to the bundled source UUID through its exact
            // untranslated content key and role, preserving existing native IDs.
            PublicAssistantSpeechManifest.registerMessage(chatID: id, nativeID: messageSpec.id,
                contentKey: messageSpec.key, role: messageSpec.role.rawValue)
            return message(
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

            let extractedIds = Set(extracted.refs.map(\.id))
            let refs = extracted.refs + (original.embedRefs ?? []).filter { !extractedIds.contains($0.id) }
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
                embedRefs: refs.isEmpty ? nil : refs,
                modelName: original.modelName,
                senderName: original.senderName, category: original.category,
                encryptedSenderName: original.encryptedSenderName,
                encryptedCategory: original.encryptedCategory,
                encryptedModelName: original.encryptedModelName,
                piiMappings: original.piiMappings, encryptedPIIMappings: original.encryptedPIIMappings,
                thinkingContent: original.thinkingContent,
                encryptedThinkingContent: original.encryptedThinkingContent,
                encryptedThinkingSignature: original.encryptedThinkingSignature,
                thinkingTokenCount: original.thinkingTokenCount, serverMessageId: original.serverMessageId
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
            modelName: message.modelName, serverMessageId: message.serverMessageId
        )
    }

    private static func extractEmbeds(from content: String, fallbackAppId: String?) -> (content: String, refs: [EmbedRef], records: [EmbedRecord]) {
        var cleaned = content
        var records: [EmbedRecord] = []
        var refsById: [String: (location: Int, ref: EmbedRef)] = [:]

        func recordRef(_ ref: EmbedRef, location: Int) {
            guard refsById[ref.id] == nil else { return }
            refsById[ref.id] = (location, ref)
        }

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
                record = embedRecord(
                    id: embedId,
                    type: "code-code",
                    appId: "code",
                    skillId: nil,
                    data: object,
                    parentEmbedId: object["parent_embed_id"] as? String,
                    embedIds: nil
                )
            } else if type == "sheet", let embedId = object["embed_id"] as? String {
                record = embedRecord(
                    id: embedId,
                    type: "sheets-sheet",
                    appId: "sheets",
                    skillId: object["skill_id"] as? String ?? "sheet",
                    data: object,
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
            recordRef(embedRef(for: record), location: match.range.location)
            cleaned.replaceSubrange(fullRange, with: "\n[[embed:\(record.id)]]\n")
        }

        let markdownEmbedPattern = #"\[!\]\(embed:([^)]+)\)"#
        for match in regexMatches(markdownEmbedPattern, in: cleaned).reversed() {
            guard let refRange = Range(match.range(at: 1), in: cleaned),
                  let fullRange = Range(match.range(at: 0), in: cleaned) else { continue }

            let ref = String(cleaned[refRange])
            recordRef(EmbedRef(id: ref, type: "web-website", status: "finished", data: nil), location: match.range.location)
            cleaned.replaceSubrange(fullRange, with: "\n[[embedref:\(ref)]]\n")
        }

        let inlineEmbedPattern = #"\[\[embed(?:ref)?:([^\]]+)\]\]"#
        for match in regexMatches(inlineEmbedPattern, in: cleaned).reversed() {
            guard let idRange = Range(match.range(at: 1), in: cleaned) else { continue }
            recordRef(EmbedRef(id: String(cleaned[idRange]), type: "web-website", status: "finished", data: nil), location: match.range.location)
        }

        let orderedRefs = refsById.values.sorted { lhs, rhs in lhs.location < rhs.location }.map { $0.ref }
        return (sanitize(cleaned), orderedRefs, records)
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
            "[[ai_models_group]]"
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
enum SubChatSpawnScopedStage {
    static func prepareAndSend<Prepared, Receipt>(
        isCurrent: () -> Bool,
        prepare: () async throws -> Prepared,
        send: (Prepared) async throws -> Receipt
    ) async throws -> (Prepared, Receipt) {
        guard isCurrent() else { throw ChatSendError.webSocketUnavailable }
        let prepared = try await prepare()
        guard isCurrent() else { throw ChatSendError.webSocketUnavailable }
        let receipt = try await send(prepared)
        guard isCurrent() else { throw ChatSendError.webSocketUnavailable }
        return (prepared, receipt)
    }

    static func commitIfCurrent(isCurrent: () -> Bool, commit: () -> Void) throws {
        guard isCurrent() else { throw ChatSendError.webSocketUnavailable }
        commit()
    }
}

struct ChatSendRetryFence: Codable, Equatable {
    let processEpoch: UUID
    let accountID: String
    let accountScope: UUID
    let server: String
    let teamID: String?
    let teamEpoch: UInt64
    let keyGeneration: UUID
    let deletionVersion: Int
    let chatKeyDigest: String

    func permitsReplay(in current: Self, hasOriginalMessage: Bool,
                       expectedVersion: Int, currentVersion: Int) -> Bool {
        guard hasOriginalMessage, accountID == current.accountID, server == current.server,
              teamID == current.teamID, chatKeyDigest == current.chatKeyDigest,
              currentVersion == expectedVersion else { return false }
        // A cold launch can rebind only after the exact local encrypted message
        // and current authorized chat key are verified. Within one process,
        // account/key/Team/deletion epochs cannot be rebound after mutation.
        return processEpoch != current.processEpoch || (
            accountScope == current.accountScope && teamEpoch == current.teamEpoch
            && keyGeneration == current.keyGeneration && deletionVersion == current.deletionVersion
        )
    }
}

struct ChatRetainedSendBundle: Codable, Equatable {
    let chatID: String
    let chatTeamID: String?
    let messageID: String
    let turnID: String
    let inputDigest: String
    let messagesVersion: Int
    let fence: ChatSendRetryFence
    let preflight: Data
    let outbound: Data

    init(chatID: String, messageID: String, turnID: String, inputDigest: String,
         messagesVersion: Int, fence: ChatSendRetryFence,
         preflight: [String: Any], outbound: [String: Any], chatTeamID: String? = nil) throws {
        self.chatID = chatID; self.chatTeamID = chatTeamID; self.messageID = messageID; self.turnID = turnID
        self.inputDigest = inputDigest; self.messagesVersion = messagesVersion; self.fence = fence
        self.preflight = try JSONSerialization.data(withJSONObject: preflight, options: [.sortedKeys])
        self.outbound = try JSONSerialization.data(withJSONObject: outbound, options: [.sortedKeys])
    }

    @MainActor func payloads() throws -> (preflight: [String: Any], outbound: [String: Any]) {
        guard let head = try JSONSerialization.jsonObject(with: preflight) as? [String: Any],
              let send = try JSONSerialization.jsonObject(with: outbound) as? [String: Any],
              head["chat_id"] as? String == chatID, head["message_id"] as? String == messageID,
              head["turn_id"] as? String == turnID, send["chat_id"] as? String == chatID,
              send["turn_id"] as? String == turnID,
              (send["message"] as? [String: Any])?["message_id"] as? String == messageID,
              let committed = head["inference_request"] as? [String: Any],
              NSDictionary(dictionary: committed).isEqual(to: send) else { throw ChatSendError.retryUnavailable }
        return (head, send)
    }
}

/// Exact prepared requests are encrypted with the owner's master key before
/// Keychain persistence. This store has no automatic replay or account adoption.
@MainActor
final class ChatRetainedSendStore {
    private let read: (String) throws -> Data?
    private let write: (String, Data) throws -> Void
    private let erase: (String) throws -> Void

    init(read: @escaping (String) throws -> Data? = { try KeychainHelper.load(key: $0) },
         write: @escaping (String, Data) throws -> Void = { try KeychainHelper.save(key: $0, data: $1) },
         erase: @escaping (String) throws -> Void = { try KeychainHelper.delete(key: $0) }) {
        self.read = read; self.write = write; self.erase = erase
    }

    private func key(accountID: String, server: String, chatID: String, messageID: String) throws -> String {
        let identity = try JSONEncoder().encode([accountID, server, chatID, messageID])
        return "retained-chat-turn-" + SHA256.hash(data: identity).map { String(format: "%02x", $0) }.joined()
    }

    func load(accountID: String, server: String, chatID: String, messageID: String,
              masterKey: SymmetricKey) throws -> ChatRetainedSendBundle? {
        let storageKey = try key(accountID: accountID, server: server, chatID: chatID, messageID: messageID)
        guard let bytes = try read(storageKey) else { return nil }
        guard let encrypted = String(data: bytes, encoding: .utf8) else { throw ChatSendError.retryUnavailable }
        let plaintext = try ComposerEmbedCrypto.decryptContent(encrypted, using: masterKey)
        let bundle = try JSONDecoder().decode(ChatRetainedSendBundle.self, from: Data(plaintext.utf8))
        guard bundle.fence.accountID == accountID, bundle.fence.server == server,
              bundle.chatID == chatID, bundle.messageID == messageID else { throw ChatSendError.retryUnavailable }
        _ = try bundle.payloads()
        return bundle
    }

    func save(_ bundle: ChatRetainedSendBundle, masterKey: SymmetricKey) throws {
        _ = try bundle.payloads()
        let storageKey = try key(accountID: bundle.fence.accountID, server: bundle.fence.server,
                                 chatID: bundle.chatID, messageID: bundle.messageID)
        // A repeated identity must never replace a partially persisted request.
        if let existing = try load(accountID: bundle.fence.accountID, server: bundle.fence.server,
                                   chatID: bundle.chatID, messageID: bundle.messageID, masterKey: masterKey) {
            guard existing == bundle else { throw ChatSendError.retryUnavailable }
            return
        }
        let json = String(decoding: try JSONEncoder().encode(bundle), as: UTF8.self)
        let sealed = try ComposerEmbedCrypto.encryptContent(json, using: masterKey)
        try write(storageKey, Data(sealed.utf8))
    }

    func remove(_ bundle: ChatRetainedSendBundle, masterKey: SymmetricKey) throws {
        guard let existing = try load(accountID: bundle.fence.accountID, server: bundle.fence.server,
                                      chatID: bundle.chatID, messageID: bundle.messageID, masterKey: masterKey),
              existing.turnID == bundle.turnID, existing == bundle else { return }
        try erase(key(accountID: bundle.fence.accountID, server: bundle.fence.server,
                      chatID: bundle.chatID, messageID: bundle.messageID))
    }
}

@MainActor
enum ChatPreparedSendRetentionStage {
    static func retainThenCommit(retain: @MainActor () throws -> Void,
                                 commit: @MainActor () async throws -> Void) async throws {
        try retain()
        try await commit()
    }
}

@MainActor
final class ChatSendPipeline {
    private let crypto = CryptoManager.shared
    private static var encryptedUserStorageClaimed = Set<String>()
    private var completedAssistantStorageSent = Set<String>()
    private struct PreparedTurn {
        let result: SendResult
        let bundle: ChatRetainedSendBundle
    }
    private var preparedTurns: [String: PreparedTurn] = [:]
    private static let processEpoch = UUID()
    private let retainedSendStore = ChatRetainedSendStore()
    private var preparingMessageIDs = Set<String>()

    struct SendResult {
        let chat: Chat
        let message: Message
    }

    struct SpawnedSubChatStorage {
        let chat: Chat
        let firstMessage: Message?
    }

    struct SubChatSpawnFence: Equatable {
        let accountScope: UUID
        let keyGeneration: UUID
        let transportGeneration: Int

        func matches(accountScope: UUID, keyGeneration: UUID, transportGeneration: Int) -> Bool {
            self.accountScope == accountScope && self.keyGeneration == keyGeneration
                && self.transportGeneration == transportGeneration
        }

        @MainActor
        func isCurrent(wsManager: WebSocketManager) -> Bool {
            matches(accountScope: OfflineStore.shared.scopeGeneration,
                    keyGeneration: ChatKeyManager.shared.cacheGeneration,
                    transportGeneration: wsManager.transportGeneration)
                && wsManager.isConnected
        }
    }

    /// Match the web client's spawned-child storage path: validate the parent's
    /// existing key, reuse its wrapper, encrypt every child field, then ask the
    /// server to store the child. No plaintext child shell is persisted on failure.
    func syncSpawnedSubChat(
        _ child: SpawnedSubChat,
        parent: Chat,
        wsManager: WebSocketManager?
    ) async throws -> SpawnedSubChatStorage {
        guard let wsManager, !child.id.isEmpty,
              ChatKeyManager.shared.hasKey(for: parent.id) || parent.encryptedChatKey?.isEmpty == false else {
            throw ChatSendError.chatKeyMismatch
        }
        let fence = SubChatSpawnFence(accountScope: OfflineStore.shared.scopeGeneration,
                                      keyGeneration: ChatKeyManager.shared.cacheGeneration,
                                      transportGeneration: wsManager.transportGeneration)
        let (prepared, acknowledgement) = try await SubChatSpawnScopedStage.prepareAndSend(
            isCurrent: { fence.isCurrent(wsManager: wsManager) },
            prepare: {
                let keyMaterial = try await self.ensureChatKey(
                    chatId: parent.id, encryptedChatKey: parent.encryptedChatKey
                )
                guard fence.isCurrent(wsManager: wsManager) else { throw ChatSendError.webSocketUnavailable }
                guard let childWrapper = ChatKeyManager.shared.installValidatedKey(
                    keyMaterial.key, encryptedKey: keyMaterial.encryptedChatKey,
                    for: child.id, expectedGeneration: fence.keyGeneration
                ) else { throw ChatSendError.chatKeyMismatch }
                let now = Date()
                let timestamp = Self.isoString(from: now)
                let title = (child.title?.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty == false
                    ? child.title! : child.prompt).trimmingCharacters(in: .whitespacesAndNewlines)
                let category = child.category?.trimmingCharacters(in: .whitespacesAndNewlines)
                let icon = child.icon?.trimmingCharacters(in: .whitespacesAndNewlines)
                let encryptedTitle = title.isEmpty ? nil : try await self.crypto.encryptContent(title, key: keyMaterial.key)
                let encryptedCategory = category?.isEmpty == false
                    ? try await self.crypto.encryptContent(category!, key: keyMaterial.key) : nil
                let encryptedIcon = icon?.isEmpty == false
                    ? try await self.crypto.encryptContent(icon!, key: keyMaterial.key) : nil
                let encryptedContent = child.userMessageId.isEmpty ? nil
                    : try await self.crypto.encryptContent(child.prompt, key: keyMaterial.key)
                let encryptedSenderName = encryptedContent == nil ? nil
                    : try await self.crypto.encryptContent("user", key: keyMaterial.key)
                let childChat = Chat(
                    id: child.id, title: title.isEmpty ? nil : title,
                    lastMessageAt: encryptedContent == nil ? nil : timestamp,
                    createdAt: timestamp, updatedAt: timestamp,
                    isArchived: false, isPinned: false, appId: parent.appId,
                    category: category, icon: icon,
                    encryptedTitle: encryptedTitle, encryptedCategory: encryptedCategory,
                    encryptedIcon: encryptedIcon, encryptedChatKey: childWrapper,
                    messagesV: encryptedContent == nil ? 0 : 1, titleV: 0,
                    parentId: parent.id, isSubChat: true,
                    subChatSettings: SubChatSettings(waitForCompletion: child.waitForCompletion, reportTrigger: nil)
                )
                let firstMessage = encryptedContent.map { encrypted in
                    Message(id: child.userMessageId, chatId: child.id, role: .user,
                            content: child.prompt, encryptedContent: encrypted,
                            createdAt: timestamp, updatedAt: nil, appId: nil,
                            isStreaming: false, embedRefs: nil)
                }
                let payload = try self.spawnedSubChatStoragePayload(
                    chat: childChat, firstMessage: firstMessage,
                    encryptedSenderName: encryptedSenderName,
                    timestamp: Int(now.timeIntervalSince1970)
                )
                return (chat: childChat, firstMessage: firstMessage, payload: payload)
            },
            send: { prepared in
                try await wsManager.sendAndWait(
                    WSOutboundMessage(type: "encrypted_chat_metadata", payload: prepared.payload),
                    responseTypes: ["encrypted_metadata_stored", "incomplete_chat_metadata", "chat_key_mismatch"]
                ) { fields in
                    fields["chat_id"] as? String == child.id
                        && (child.userMessageId.isEmpty || fields["message_id"] as? String == child.userMessageId)
                }
            }
        )
        guard let accepted = ChatEncryptedMetadataAcknowledgementPolicy.acceptedVersions(from: acknowledgement.fields) else {
            throw ChatSendError.chatKeyMismatch
        }
        let acceptedChat = copyChat(prepared.chat, messagesV: accepted.messages,
                                    titleV: accepted.title, metadataV: accepted.metadata)
        return SpawnedSubChatStorage(chat: acceptedChat, firstMessage: prepared.firstMessage)
    }

    func persistFork(source: Chat, messages: [Message], socket: WebSocketManager, title: String? = nil,
                     validate: @escaping () throws -> Void) async throws -> (chat: Chat, messages: [Message]) {
        try validate()
        let id = UUID().uuidString, now = Date(), keyGeneration = ChatKeyManager.shared.cacheGeneration
        let material = try await ensureChatKey(chatId: id, encryptedChatKey: nil)
        try validate()
        let prepared = try await MessageForkPayloadBuilder.prepare(source: source, messages: messages, id: id, now: now,
            key: material.key, wrappedKey: material.encryptedChatKey, title: title, validate: validate)
        try validate()
        guard keyGeneration == ChatKeyManager.shared.cacheGeneration else { throw MessageContextActionError.staleContext }
        let response = try await socket.sendAndWait(WSOutboundMessage(type: "encrypted_chat_metadata", payload: prepared.payload),
            responseTypes: ["encrypted_metadata_stored", "incomplete_chat_metadata", "chat_key_mismatch"],
            matching: { $0["chat_id"] as? String == id }, beforeSend: { try validate() })
        try validate()
        guard ChatEncryptedMetadataAcknowledgementPolicy.acceptedVersions(from: response.fields) != nil else { throw ChatSendError.chatKeyMismatch }
        return (prepared.chat, prepared.messages)
    }

    func spawnedSubChatStoragePayload(
        chat: Chat, firstMessage: Message?, encryptedSenderName: String?, timestamp: Int
    ) throws -> [String: Any] {
        guard chat.isSubChat == true, let parentID = chat.parentId,
              let encryptedChatKey = chat.encryptedChatKey, !encryptedChatKey.isEmpty,
              firstMessage == nil || firstMessage?.encryptedContent != nil else {
            throw ChatSendError.chatKeyMismatch
        }
        var payload: [String: Any] = [
            "chat_id": chat.id, "parent_id": parentID, "is_sub_chat": true,
            "encrypted_chat_key": encryptedChatKey, "created_at": timestamp,
            "versions": ["messages_v": chat.messagesV ?? 0, "title_v": chat.titleV ?? 0,
                         "last_edited_overall_timestamp": timestamp]
        ]
        if let encryptedTitle = chat.encryptedTitle { payload["encrypted_title"] = encryptedTitle }
        if let encryptedCategory = chat.encryptedCategory { payload["encrypted_chat_category"] = encryptedCategory }
        if let encryptedIcon = chat.encryptedIcon { payload["encrypted_icon"] = encryptedIcon }
        if let firstMessage {
            payload["message_id"] = firstMessage.id
            payload["encrypted_content"] = firstMessage.encryptedContent
            payload["encrypted_sender_name"] = encryptedSenderName
        }
        return payload
    }

    func chatWithEncryptedSubChatSummary(_ child: Chat, summary: String) async throws -> Chat {
        guard child.isSubChat == true,
              ChatKeyManager.shared.hasKey(for: child.id) || child.encryptedChatKey?.isEmpty == false else {
            throw ChatSendError.chatKeyMismatch
        }
        let keyMaterial = try await ensureChatKey(chatId: child.id, encryptedChatKey: child.encryptedChatKey)
        return try await encryptSubChatSummary(child, summary: summary, key: keyMaterial.key)
    }

    func encryptSubChatSummary(_ child: Chat, summary: String, key: SymmetricKey) async throws -> Chat {
        guard child.isSubChat == true else { throw ChatSendError.chatKeyMismatch }
        let encrypted = try await crypto.encryptContent(summary, key: key)
        return copyChat(child, updatedAt: Self.isoString(from: Date()),
                        chatSummary: summary, encryptedChatSummary: encrypted)
    }

    func makeLocalIncognitoUserMessage(
        content: String,
        in chat: Chat,
        existingMessages: [Message],
        piiMappings: [PIIMapping] = []
    ) -> SendResult {
        let now = Date()
        let createdAt = Self.isoString(from: now)
        let messageId = "\(chat.id.suffix(10))-\(UUID().uuidString)"
        let nextMessagesV = max(chat.messagesV ?? existingMessages.count, existingMessages.count) + 1
        let updatedChat = copyChat(
            chat,
            title: chat.title ?? String(content.prefix(64)),
            lastMessageAt: createdAt,
            updatedAt: createdAt,
            messagesV: nextMessagesV
        )
        let message = Message(
            id: messageId,
            chatId: chat.id,
            role: .user,
            content: content,
            encryptedContent: nil,
            createdAt: createdAt,
            updatedAt: nil,
            appId: nil,
            isStreaming: false,
            embedRefs: nil,
            piiMappings: piiMappings.isEmpty ? nil : piiMappings
        )
        return SendResult(chat: updatedChat, message: message)
    }

    func sendIncognitoUserMessage(
        message: Message,
        in chat: Chat,
        historyMessages: [Message],
        wsManager: WebSocketManager?
    ) async throws {
        guard let wsManager else { throw ChatSendError.webSocketUnavailable }
        try await sendSetActiveChat(chat.id, wsManager: wsManager)
        try await wsManager.send(WSOutboundMessage(
            type: "chat_message_added",
            payload: incognitoUserMessagePayload(
                chatId: chat.id,
                message: message,
                messageHistory: historyMessages
            )
        ))
    }

    func sendIncognitoUserMessage(
        content: String,
        in chat: Chat,
        existingMessages: [Message],
        wsManager: WebSocketManager?
    ) async throws {
        let result = makeLocalIncognitoUserMessage(content: content, in: chat, existingMessages: existingMessages)
        try await sendIncognitoUserMessage(
            message: result.message,
            in: result.chat,
            historyMessages: existingMessages + [result.message],
            wsManager: wsManager
        )
    }

    func incognitoUserMessagePayload(
        chatId: String,
        message: Message,
        messageHistory: [Message]
    ) -> [String: Any] {
        let createdAtUnix = Self.unixSeconds(from: message.createdAt)
        return [
            "chat_id": chatId,
            "is_incognito": true,
            "message": [
                "message_id": message.id,
                "chat_id": chatId,
                "role": message.role.rawValue,
                "sender_name": "User",
                "status": "sent",
                "content": message.content ?? "",
                "created_at": createdAtUnix,
                "chat_has_title": false
            ],
            "message_history": incognitoMessageHistoryPayload(messageHistory, fallbackChatId: chatId)
        ]
    }

    func combinedPIIMappings(
        textMappings: [PIIMapping],
        composerEmbeds: [ComposerPendingEmbed]
    ) -> [PIIMapping] {
        PIIDetector.mergePIIMappings(textMappings + composerEmbeds.flatMap(\.piiMappings))
    }

    func contentAndMappingsForSend(
        content: String,
        existingMessages: [Message],
        piiMappings: [PIIMapping] = [],
        excludedPIIOriginals: Set<String> = [],
        excludedPIIPlaceholders: Set<String> = []
    ) -> (content: String, piiMappings: [PIIMapping]) {
        let rewrite = PIIDetector.rewriteKnownPIIPlaceholders(
            in: content,
            mappings: knownPIIMappings(in: existingMessages),
            excludedOriginals: excludedPIIOriginals,
            excludedPlaceholders: excludedPIIPlaceholders
        )
        return (
            rewrite.text,
            PIIDetector.mergePIIMappings(rewrite.appliedMappings + piiMappings)
        )
    }

    private func knownPIIMappings(in messages: [Message]) -> [PIIMapping] {
        PIIDetector.mergePIIMappings(
            messages
                .filter { $0.role == .user }
                .flatMap { $0.piiMappings ?? [] }
        )
    }

    private func incognitoMessageHistoryPayload(_ messages: [Message], fallbackChatId: String) -> [[String: Any]] {
        messages.compactMap { message in
            let content = (message.content ?? "").trimmingCharacters(in: .whitespacesAndNewlines)
            guard !content.isEmpty, message.role != .system else { return nil }
            return [
                "message_id": message.id,
                "chat_id": message.chatId.isEmpty ? fallbackChatId : message.chatId,
                "role": message.role.rawValue,
                "sender_name": message.role == .user ? "User" : "Assistant",
                "content": content,
                "created_at": Self.unixSeconds(from: message.createdAt)
            ]
        }
    }

    // Durable preflight commits history along with the current message. A cache-miss
    // retry cannot append history to that immutable commitment afterward.
    func savedChatHistoryPayload(_ messages: [Message], chatId: String, key: SymmetricKey) async throws -> [[String: Any]] {
        var seen = Set<String>()
        var history: [[String: Any]] = []
        for message in messages.sorted(by: { $0.createdAt < $1.createdAt }) {
            guard message.chatId == chatId, message.role != .system,
                  message.isStreaming != true, seen.insert(message.id).inserted else { continue }
            var content = message.content ?? ""
            if content.isEmpty, let encrypted = message.encryptedContent {
                content = try await crypto.decryptContent(base64String: encrypted, key: key)
            }
            if content.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty,
               let embedRefs = message.embedRefs, !embedRefs.isEmpty {
                content = embedRefs.map { ref in
                    "```json\n{\"type\": \"\(ref.type)\", \"embed_id\": \"\(ref.id)\"}\n```"
                }.joined(separator: "\n\n")
            }
            guard !content.isEmpty else { throw ChatSendError.historyUnavailable }
            var row: [String: Any] = [
                "message_id": message.id, "chat_id": chatId,
                "role": message.role.rawValue, "content": content,
                "sender_name": message.senderName ?? (message.role == .user ? "User" : "Assistant"),
                "created_at": Self.unixSeconds(from: message.createdAt)
            ]
            if let category = message.category ?? message.appId { row["category"] = category }
            history.append(row)
        }
        return history
    }

    func sendUserMessage(
        content: String,
        in chat: Chat,
        existingMessages: [Message],
        wsManager: WebSocketManager?,
        chatStore: ChatStore?,
        activateChat: Bool = true,
        waitForRemoteSend: Bool = true,
        waitForInferenceReceipt: Bool = false,
        composerEmbeds: [ComposerPendingEmbed] = [],
        piiMappings: [PIIMapping] = [],
        excludedPIIOriginals: Set<String> = [],
        excludedPIIPlaceholders: Set<String> = [],
        broadcastToSiblings: Bool = false,
        beforeRemoteSend: ((String, [String: Any], [String: Any]) throws -> Void)? = nil,
        createdAtOverride: String? = nil,
        beforePreparedSend: (() async throws -> Void)? = nil,
        validateRemoteSend: (() throws -> Void)? = nil,
        messageId requestedMessageId: String? = nil
    ) async throws -> SendResult {
        guard let wsManager else { throw ChatSendError.webSocketUnavailable }
        // Pin speech/account context before encryption and preference awaits.
        let accountScope = OfflineStore.shared.scopeGeneration
        let server = ServerProfile.current()
        let team = TeamWorkspaceContext.shared.snapshot
        let keyGeneration = ChatKeyManager.shared.cacheGeneration
        let deletionVersion = OfflineStore.shared.chatDeletionVersion(chat.id)
        preparedTurns = preparedTurns.filter {
            let fence = $0.value.bundle.fence
            return fence.accountScope == accountScope && fence.server == server.apiBaseURL.absoluteString
                && fence.teamID == team.teamID && fence.teamEpoch == team.epoch && fence.keyGeneration == keyGeneration
        }
        let speechScope = AssistantSpeechAppRuntime.shared.scope(for: chat.id)
        let validateSendContext: () throws -> Void = {
            try Task.checkCancellation()
            guard OfflineStore.shared.scopeGeneration == accountScope,
                  ServerProfile.current() == server, TeamWorkspaceContext.shared.isCurrent(team),
                  ChatKeyManager.shared.cacheGeneration == keyGeneration,
                  OfflineStore.shared.chatDeletionVersion(chat.id) == deletionVersion else {
                throw ChatSendError.webSocketUnavailable
            }
            try validateRemoteSend?()
            if let speechScope { try AssistantSpeechAppRuntime.shared.requireCurrent(speechScope, socket: wsManager) }
        }
        let now = Date()
        let createdAt = createdAtOverride ?? Self.isoString(from: now)
        let createdAtUnix = createdAtOverride.map(Self.unixSeconds) ?? Int(now.timeIntervalSince1970)
        let messageId = requestedMessageId ?? "\(chat.id.suffix(10))-\(UUID().uuidString)"
        guard preparingMessageIDs.insert(messageId).inserted else { throw ChatSendError.retryUnavailable }
        defer { preparingMessageIDs.remove(messageId) }
        // Nil content alone is never evidence of an already stored attachment.
        _ = try Self.requiredEncryptedBundles(composerEmbeds, referenceScope: .current)
        guard let accountID = await AuthManager.currentUserId(),
              let masterKey = try await crypto.loadMasterKey(for: accountID) else { throw ChatSendError.missingMasterKey }
        try validateSendContext()
        let keyMaterial = try await ensureChatKey(chatId: chat.id, encryptedChatKey: chat.encryptedChatKey)
        try validateSendContext()
        let retryFence = ChatSendRetryFence(processEpoch: Self.processEpoch, accountID: accountID,
            accountScope: accountScope, server: server.apiBaseURL.absoluteString,
            teamID: team.teamID, teamEpoch: team.epoch, keyGeneration: keyGeneration,
            deletionVersion: deletionVersion,
            chatKeyDigest: keyMaterial.key.withUnsafeBytes { SHA256.hash(data: Data($0)).map { String(format: "%02x", $0) }.joined() })
        let inputDigest = try Self.sendInputDigest(content: content, composerEmbeds: composerEmbeds,
            piiMappings: piiMappings, excludedPIIOriginals: excludedPIIOriginals,
            excludedPIIPlaceholders: excludedPIIPlaceholders, broadcastToSiblings: broadcastToSiblings,
            createdAtOverride: createdAtOverride, isEdit: beforePreparedSend != nil,
            knownMappings: knownPIIMappings(in: existingMessages.filter { $0.id != messageId }))
        if requestedMessageId != nil,
           let retained = try preparedTurns[messageId]?.bundle ?? retainedSendStore.load(
            accountID: accountID, server: server.apiBaseURL.absoluteString,
            chatID: chat.id, messageID: messageId, masterKey: masterKey) {
            let payloads = try retained.payloads()
            let original = (chatStore?.messages(for: chat.id) ?? existingMessages).first { $0.id == messageId }
                ?? OfflineStore.shared.loadMessageWindow(chatId: chat.id, around: messageId).first { $0.id == messageId }
            let currentChat = chatStore?.chat(for: chat.id) ?? chat
            let originalCiphertext = (payloads.preflight["encrypted_user_message"] as? [String: Any])?["encrypted_content"] as? String
            let originalMappingCiphertext = (payloads.preflight["encrypted_user_message"] as? [String: Any])?["encrypted_pii_mappings"] as? String
            guard retained.chatID == chat.id, retained.messageID == messageId,
                  retained.inputDigest == inputDigest, retained.chatTeamID == chat.teamId, let original,
                  original.chatId == chat.id, original.role == .user,
                  original.encryptedContent == originalCiphertext, originalCiphertext != nil,
                  original.encryptedPIIMappings == originalMappingCiphertext,
                  retained.fence.permitsReplay(in: retryFence, hasOriginalMessage: true,
                    expectedVersion: retained.messagesVersion, currentVersion: currentChat.messagesV ?? existingMessages.count) else {
                throw ChatSendError.retryUnavailable
            }
            let validateRetry: () throws -> Void = {
                try validateSendContext()
                let liveChat = chatStore?.chat(for: chat.id) ?? currentChat
                guard (liveChat.messagesV ?? existingMessages.count) == retained.messagesVersion,
                      chatStore == nil || chatStore?.messages(for: chat.id).contains(where: {
                        $0.id == messageId && $0.encryptedContent == originalCiphertext
                      }) == true else { throw ChatSendError.retryUnavailable }
            }
            try validateRetry()
            try beforeRemoteSend?(retained.turnID, payloads.preflight, payloads.outbound)
            try await sendRemoteUserMessage(chatId: chat.id, activateChat: activateChat,
                wsManager: wsManager, turnId: retained.turnID, preflightPayload: payloads.preflight,
                outboundPayload: payloads.outbound, waitForInferenceReceipt: true,
                validateRemoteSend: validateRetry)
            try validateSendContext()
            try retainedSendStore.remove(retained, masterKey: masterKey)
            if preparedTurns[messageId]?.bundle.turnID == retained.turnID { preparedTurns.removeValue(forKey: messageId) }
            return SendResult(chat: currentChat, message: original)
        }
        // The immutable retained replay above intentionally bypasses this probe:
        // readiness changes must never replace an interrupted turn's original bundle.
        let referenceScope = ComposerEmbedReferenceScope(accountScope: accountScope,
            server: server.apiBaseURL.absoluteString, teamID: team.teamID, teamEpoch: team.epoch)
        try await Self.validateFreshStoredReferences(composerEmbeds, referenceScope: referenceScope,
            serverProfile: server, validate: validateSendContext) { ids in
                try await APIClient.shared.embedReferenceAvailability(chatID: chat.id, embedIDs: ids,
                    serverProfile: server, expectedAccountID: accountID, expectedScope: accountScope,
                    expectedTeamContext: APIRequestTeamContext(epoch: team.epoch, teamID: team.teamID))
            }
        let contentWithEmbedReferences = Self.contentByAppendingComposerEmbedReferences(
            content,
            composerEmbeds: composerEmbeds
        )
        let urlPreparation = try await URLMessageEmbedPreparation.prepare(
            text: contentWithEmbedReferences,
            credits: URLMessageEmbedPreparation.cachedCredits(accountID: await AuthManager.currentUserId()),
            validate: validateSendContext
        )
        let preparedEmbeds = composerEmbeds + urlPreparation.embeds.map(ComposerPendingEmbed.fromURL)
        try validateSendContext()
        let sendPreparation = contentAndMappingsForSend(
            content: urlPreparation.content,
            existingMessages: existingMessages,
            piiMappings: piiMappings,
            excludedPIIOriginals: excludedPIIOriginals,
            excludedPIIPlaceholders: excludedPIIPlaceholders
        )
        let contentForSend = sendPreparation.content
        let mappingsForSend = sendPreparation.piiMappings
        let encryptedContent = try await crypto.encryptContent(contentForSend, key: keyMaterial.key)
        let encryptedPIIMappings = try await encryptPIIMappings(mappingsForSend, key: keyMaterial.key)
        let encryptedEmbedPayloads = try await encryptedEmbeds(
            preparedEmbeds,
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
            content: contentForSend,
            encryptedContent: encryptedContent,
            createdAt: createdAt,
            updatedAt: nil,
            appId: nil,
            isStreaming: nil,
            embedRefs: preparedEmbeds.isEmpty ? nil : preparedEmbeds.map { embed in
                EmbedRef(id: embed.id, type: embed.type, status: embed.status, data: nil)
            },
            piiMappings: mappingsForSend.isEmpty ? nil : mappingsForSend,
            encryptedPIIMappings: encryptedPIIMappings
        )

        let history = existingMessages.isEmpty ? [] : try await savedChatHistoryPayload(
            existingMessages.filter { $0.id != message.id } + [message],
            chatId: chat.id, key: keyMaterial.key
        )

        var messagePayload: [String: Any] = [
            "message_id": messageId,
            "role": "user",
            "content": contentForSend,
            "created_at": createdAtUnix,
            "sender_name": "user",
            "chat_has_title": (updatedChat.titleV ?? 0) > 0,
            "current_chat_title_v": updatedChat.titleV ?? 0,
            "current_chat_metadata_v": updatedChat.metadataV ?? updatedChat.titleV ?? 0
        ]
        if (updatedChat.titleV ?? 0) > 0 {
            messagePayload["current_chat_title"] = updatedChat.title
        }

        messagePayload.merge(try await AssistantSpeechAppRuntime.shared.prepareSend(chat: chat, userMessageID: messageId, socket: wsManager, expectedScope: speechScope), uniquingKeysWith: { _, new in new })

        var outboundPayload: [String: Any] = [
            "chat_id": chat.id,
            "message": messagePayload,
            "encrypted_chat_key": keyMaterial.encryptedChatKey
        ]
        if !history.isEmpty { outboundPayload["message_history"] = history }
        outboundPayload.merge(
            chatContextPayloadFields(
                for: chat,
                broadcastToSiblings: broadcastToSiblings,
                activeFocusId: nil
            ),
            uniquingKeysWith: { _, new in new }
        )
        let activeFocusId: String?
        if let inMemoryActiveFocusId = chat.activeFocusId {
            activeFocusId = inMemoryActiveFocusId
        } else if let encryptedActiveFocusId = chat.encryptedActiveFocusId {
            activeFocusId = try? await crypto.decryptContent(
                base64String: encryptedActiveFocusId,
                key: keyMaterial.key
            )
        } else {
            activeFocusId = nil
        }
        if let activeFocusId, !activeFocusId.isEmpty {
            outboundPayload.merge(
                chatContextPayloadFields(
                    for: chat,
                    broadcastToSiblings: broadcastToSiblings,
                    activeFocusId: activeFocusId
                ),
                uniquingKeysWith: { _, new in new }
            )
        }
        if let encryptedPhaseState = chatStore?.chat(for: chat.id)?.encryptedFocusPhaseState ?? chat.encryptedFocusPhaseState {
            let text = try await crypto.decryptContent(base64String: encryptedPhaseState, key: keyMaterial.key)
            if let data = text.data(using: .utf8), let states = try JSONSerialization.jsonObject(with: data) as? [String: Any] {
                outboundPayload["focus_phase_state"] = states
            }
        }
        // Optional owned reference material is transient and never restores Project consent.
        if let context = try? await NativeProjectAuthoringClient.shared.requestContext(chatID: chat.id, text: contentForSend) {
            outboundPayload.merge(context, uniquingKeysWith: { _, new in new })
        }
        let sendableEmbeds = preparedEmbeds.compactMap(\.serverPayload)
        if !sendableEmbeds.isEmpty {
            outboundPayload["embeds"] = sendableEmbeds
        }
        if !encryptedEmbedPayloads.isEmpty {
            outboundPayload["encrypted_embeds"] = encryptedEmbedPayloads
        }
        if let encryptedPIIMappings {
            outboundPayload["encrypted_pii_mappings"] = encryptedPIIMappings
        }

        let turnId = UUID().uuidString.lowercased()
        let recoveryKeyPair = try await crypto.deriveRecoveryKeyPair(
            chatKey: keyMaterial.key,
            chatId: chat.id,
            keyVersion: 1
        )
        // This exact object is committed by the server before inference starts.
        // Only the transport wrapper gains preflight fields after acknowledgement.
        outboundPayload["turn_id"] = turnId
        outboundPayload["recovery_public_key"] = recoveryKeyPair.publicKey
        outboundPayload["chat_key_version"] = ChatCompletionRecoveryCoordinator.protocolVersion
        var encryptedUserMessage: [String: Any] = [
            "client_message_id": messageId,
            "chat_id": chat.id,
            "encrypted_content": encryptedContent,
            "role": "user",
            "created_at": createdAtUnix,
            "updated_at": createdAtUnix,
        ]
        if let encryptedPIIMappings {
            encryptedUserMessage["encrypted_pii_mappings"] = encryptedPIIMappings
        }
        let encryptedTitle: String?
        if Self.shouldIncludeInitialChatMetadata(
            messagesVersion: chat.messagesV, titleVersion: chat.titleV,
            existingMessageCount: existingMessages.count
        ) {
            if let existingEncryptedTitle = chat.encryptedTitle {
                encryptedTitle = existingEncryptedTitle
            } else {
                encryptedTitle = try await crypto.encryptContent("", key: keyMaterial.key)
            }
        } else {
            encryptedTitle = nil
        }
        let preflightPayload = savedChatPreflightPayload(
            chatId: chat.id,
            turnId: turnId,
            messageId: messageId,
            encryptedChatKey: keyMaterial.encryptedChatKey,
            recoveryPublicKey: recoveryKeyPair.publicKey,
            expectedMessagesVersion: max(chat.messagesV ?? existingMessages.count, existingMessages.count),
            encryptedUserMessage: encryptedUserMessage,
            inferenceRequest: outboundPayload,
            encryptedTitle: encryptedTitle,
            createdAt: createdAtUnix
        )

        // Notification actions persist this exact preflight/commit pair before
        // local insertion, so interrupted retries cannot create another message.
        try validateSendContext()
        let retainedBundle = try ChatRetainedSendBundle(chatID: chat.id, messageID: messageId,
            turnID: turnId, inputDigest: inputDigest, messagesVersion: nextMessagesV, fence: retryFence,
            preflight: preflightPayload, outbound: outboundPayload, chatTeamID: chat.teamId)
        // Retention must succeed before callbacks, destructive edit preparation,
        // optimistic insertion, or transport. Never truncate oversized payloads.
        try await ChatPreparedSendRetentionStage.retainThenCommit(retain: {
            try self.retainedSendStore.save(retainedBundle, masterKey: masterKey)
        }, commit: {
            try validateSendContext()
            try beforeRemoteSend?(turnId, preflightPayload, outboundPayload)
            try await beforePreparedSend?()
            try validateSendContext()
        })
        chatStore?.upsertChat(updatedChat)
        // A new chat can be sent directly from the welcome composer, before a
        // ChatViewModel exists to register its uploaded attachment. Keep the
        // durable records beside the optimistic user message so the first
        // render and a later cold open can resolve its [[embed:...]] references.
        if !preparedEmbeds.isEmpty {
            chatStore?.upsertEmbeds(preparedEmbeds.map(\.record), for: chat.id)
        }
        chatStore?.appendMessage(message, to: chat.id)

        preparedTurns[messageId] = PreparedTurn(
            result: SendResult(chat: updatedChat, message: message), bundle: retainedBundle)

        if waitForRemoteSend {
            try await sendRemoteUserMessage(
                chatId: chat.id,
                activateChat: activateChat,
                wsManager: wsManager,
                turnId: turnId,
                preflightPayload: preflightPayload,
                outboundPayload: outboundPayload,
                waitForInferenceReceipt: waitForInferenceReceipt,
                validateRemoteSend: validateSendContext
            )
            try validateSendContext()
            try retainedSendStore.remove(retainedBundle, masterKey: masterKey)
            if preparedTurns[messageId]?.bundle.turnID == turnId { preparedTurns.removeValue(forKey: messageId) }
        } else {
            Task { @MainActor in
                do {
                    try await self.sendRemoteUserMessage(
                        chatId: chat.id,
                        activateChat: activateChat,
                        wsManager: wsManager,
                        turnId: turnId,
                        preflightPayload: preflightPayload,
                        outboundPayload: outboundPayload,
                        waitForInferenceReceipt: waitForInferenceReceipt,
                        validateRemoteSend: validateSendContext
                    )
                    try validateSendContext()
                    try self.retainedSendStore.remove(retainedBundle, masterKey: masterKey)
                    if self.preparedTurns[messageId]?.bundle.turnID == turnId { self.preparedTurns.removeValue(forKey: messageId) }
                } catch {
                    print("[ChatSendPipeline] Background send failed for chat \(chat.id.prefix(8)): \(error)")
                }
            }
        }

        return SendResult(chat: updatedChat, message: message)
    }

    static func sendInputDigest(content: String, composerEmbeds: [ComposerPendingEmbed],
                                piiMappings: [PIIMapping], excludedPIIOriginals: Set<String>,
                                excludedPIIPlaceholders: Set<String>, broadcastToSiblings: Bool,
                                createdAtOverride: String?, isEdit: Bool,
                                knownMappings: [PIIMapping] = []) throws -> String {
        let encoder = JSONEncoder()
        encoder.outputFormatting = [.sortedKeys]
        let mappings = try encoder.encode(piiMappings)
        let knownMappings = try encoder.encode(knownMappings)
        let input: [String: Any] = [
            "content": content,
            "embeds": composerEmbeds.map { embed -> [String: Any] in
                let isReference: Bool
                if case .existingStoredReference = embed.storageDisposition { isReference = true } else { isReference = false }
                return ["id": embed.id, "type": embed.type, "reference_type": embed.referenceType,
                        "status": embed.status, "content": embed.content as Any? ?? NSNull(),
                        "text_preview": embed.textPreview as Any? ?? NSNull(), "existing_reference": isReference]
            },
            "pii_mappings": mappings.base64EncodedString(),
            "known_pii_mappings": knownMappings.base64EncodedString(),
            "excluded_pii_originals": excludedPIIOriginals.sorted(),
            "excluded_pii_placeholders": excludedPIIPlaceholders.sorted(),
            "broadcast_to_siblings": broadcastToSiblings,
            "created_at_override": createdAtOverride as Any? ?? NSNull(), "is_edit": isEdit
        ]
        let bytes = try JSONSerialization.data(withJSONObject: input, options: [.sortedKeys])
        return SHA256.hash(data: bytes).map { String(format: "%02x", $0) }.joined()
    }

    static func contentByAppendingComposerEmbedReferences(
        _ content: String,
        composerEmbeds: [ComposerPendingEmbed]
    ) -> String {
        var result = content.trimmingCharacters(in: .whitespacesAndNewlines)
        for embed in composerEmbeds where !containsEmbedReference(embed.id, in: result) {
            if !result.isEmpty { result += "\n\n" }
            result += embed.markdownReference
        }
        return result
    }

    static func provisionalTitleSource(
        content: String,
        composerEmbeds: [ComposerPendingEmbed],
        embedTypesByID: [String: String] = [:]
    ) -> String? {
        let embedFencePattern = #"```(?:json_embed|json)\s*[\s\S]*?\"embed_id\"\s*:\s*\"[^\"]+\"[\s\S]*?```"#
        let contentRange = NSRange(content.startIndex..<content.endIndex, in: content)
        let textOnly = (try? NSRegularExpression(pattern: embedFencePattern))?
            .stringByReplacingMatches(in: content, range: contentRange, withTemplate: "")
            .trimmingCharacters(in: .whitespacesAndNewlines)
        let knownTypes = embedTypesByID.merging(Dictionary(composerEmbeds.map { ($0.id, $0.type) },
            uniquingKeysWith: { first, _ in first })) { _, composerType in composerType }
        let referencedType = referencedEmbedIDs(in: content).compactMap { knownTypes[$0] }.first
        let embedLabel = (composerEmbeds.first?.type ?? referencedType).map { titleLabel(for: $0) }
        let titleContent = textOnly ?? content
        let cleanedText: String
        if embedLabel != nil, let regex = try? NSRegularExpression(pattern: #"\[\[embed(?:ref)?:[^\]]+\]\]"#) {
            cleanedText = regex.stringByReplacingMatches(in: titleContent,
                range: NSRange(titleContent.startIndex..<titleContent.endIndex, in: titleContent), withTemplate: "")
                .split(whereSeparator: \.isWhitespace).joined(separator: " ")
        } else {
            cleanedText = titleByReplacingEmbedReferences(titleContent, embedTypes: [], embedTypesByID: knownTypes)
                .trimmingCharacters(in: .whitespacesAndNewlines)
        }
        if !cleanedText.isEmpty {
            if let embedLabel, !cleanedText.hasPrefix(embedLabel) {
                return "\(embedLabel) \(cleanedText)"
            }
            return cleanedText
        }

        return composerEmbeds.lazy
            .filter { $0.type == "audio-recording" }
            .compactMap { embed -> String? in
                guard let preview = embed.textPreview?.trimmingCharacters(in: .whitespacesAndNewlines),
                      !preview.isEmpty,
                      preview != embed.filename.trimmingCharacters(in: .whitespacesAndNewlines) else {
                    return nil
                }
                return "\(titleLabel(for: embed.type)) \(preview)"
            }
            .first ?? embedLabel
    }

    static func titleByReplacingEmbedReferences(_ title: String, embedTypes: [String],
                                                embedTypesByID: [String: String] = [:]) -> String {
        let fallback = embedTypes.first.map { titleLabel(for: $0) } ?? "[Attachment]"
        let pattern = #"\[\[embed(?:ref)?:([^\]]+)\]\]"#
        guard let regex = try? NSRegularExpression(pattern: pattern) else { return title }
        let range = NSRange(title.startIndex..<title.endIndex, in: title)
        var replaced = title
        for match in regex.matches(in: title, range: range).reversed() {
            guard let idRange = Range(match.range(at: 1), in: title),
                  let replacementRange = Range(match.range, in: replaced) else { continue }
            let label = embedTypesByID[String(title[idRange])].map { titleLabel(for: $0) } ?? fallback
            replaced.replaceSubrange(replacementRange, with: label)
        }
        return replaced.split(whereSeparator: \.isWhitespace).joined(separator: " ")
    }

    private static func referencedEmbedIDs(in content: String) -> [String] {
        let pattern = #"\[\[embed(?:ref)?:([^\]]+)\]\]"#
        guard let regex = try? NSRegularExpression(pattern: pattern) else { return [] }
        return regex.matches(in: content, range: NSRange(content.startIndex..<content.endIndex, in: content))
            .compactMap { Range($0.range(at: 1), in: content).map { String(content[$0]) } }
    }

    private static func titleLabel(for type: String) -> String {
        let normalized = type.lowercased()
        if normalized.contains("image") { return "[Image]" }
        if normalized.contains("audio") || normalized.contains("recording") { return "[Audio]" }
        if normalized.contains("video") { return "[Video]" }
        if normalized.contains("pdf") { return "[PDF]" }
        return "[File]"
    }

    private static func containsEmbedReference(_ embedId: String, in content: String) -> Bool {
        if content.contains("embed:\(embedId)") { return true }
        let escapedID = NSRegularExpression.escapedPattern(for: embedId)
        let pattern = #"\"embed_id\"\s*:\s*\""# + escapedID + #"\""#
        guard let regex = try? NSRegularExpression(pattern: pattern) else { return false }
        return regex.firstMatch(
            in: content,
            range: NSRange(content.startIndex..<content.endIndex, in: content)
        ) != nil
    }

    func sendSubChatConfirmation(
        chatId: String,
        taskId: String,
        action: String,
        approveCount: Int?,
        wsManager: WebSocketManager?
    ) async throws {
        guard let wsManager else { throw ChatSendError.webSocketUnavailable }
        try await wsManager.send(WSOutboundMessage(
            type: "sub_chat_confirmation",
            payload: subChatConfirmationPayload(
                chatId: chatId,
                taskId: taskId,
                action: action,
                approveCount: approveCount
            )
        ))
    }

    func sendSubChatStop(chatId: String, taskId: String?, wsManager: WebSocketManager?) async throws {
        guard let wsManager else { throw ChatSendError.webSocketUnavailable }
        try await wsManager.send(WSOutboundMessage(
            type: "sub_chat_stop",
            payload: subChatStopPayload(chatId: chatId, taskId: taskId)
        ))
    }

    func subChatConfirmationPayload(
        chatId: String,
        taskId: String,
        action: String,
        approveCount: Int?
    ) -> [String: Any] {
        var payload: [String: Any] = [
            "chat_id": chatId,
            "task_id": taskId,
            "action": action
        ]
        if let approveCount {
            payload["approve_count"] = approveCount
        }
        return payload
    }

    func subChatStopPayload(chatId: String, taskId: String?) -> [String: Any] {
        var payload: [String: Any] = ["chat_id": chatId]
        if let taskId {
            payload["task_id"] = taskId
        }
        return payload
    }

    func sendCancelAITask(taskId: String?, chatId: String?, wsManager: WebSocketManager?) async throws {
        guard let wsManager else { throw ChatSendError.webSocketUnavailable }
        guard let taskId, !taskId.isEmpty else { return }
        try await wsManager.send(WSOutboundMessage(
            type: "cancel_ai_task",
            payload: cancelAITaskPayload(taskId: taskId, chatId: chatId)
        ))
    }

    func cancelAITaskPayload(taskId: String, chatId: String?) -> [String: Any] {
        var payload: [String: Any] = ["task_id": taskId]
        if let chatId, !chatId.isEmpty {
            payload["chat_id"] = chatId
        }
        return payload
    }

    func chatContextPayloadFields(
        for chat: Chat,
        broadcastToSiblings: Bool,
        activeFocusId: String?
    ) -> [String: Any] {
        var payload: [String: Any] = [
            "broadcast": broadcastToSiblings
        ]
        if let parentId = chat.parentId, !parentId.isEmpty {
            payload["parent_id"] = parentId
        }
        if let activeFocusId, !activeFocusId.isEmpty {
            payload["active_focus_id"] = activeFocusId
        }
        return payload
    }

    private func sendRemoteUserMessage(
        chatId: String,
        activateChat: Bool,
        wsManager: ChatWebSocketTransport,
        turnId: String,
        preflightPayload: [String: Any],
        outboundPayload: [String: Any],
        waitForInferenceReceipt: Bool = false,
        validateRemoteSend: (() throws -> Void)? = nil
    ) async throws {
        let scope = OfflineStore.shared.scopeGeneration
        for attempt in 0..<2 {
            do {
                try validateRemoteSend?()
                if activateChat {
                    try await wsManager.send(WSOutboundMessage(type: "set_active_chat", payload: ["chat_id": chatId]))
                }
                try await sendSavedChatTurn(
                    turnId: turnId,
                    preflightPayload: preflightPayload,
                    outboundPayload: outboundPayload,
                    transport: wsManager,
                    waitForInferenceReceipt: waitForInferenceReceipt,
                    validateRemoteSend: validateRemoteSend
                )
                return
            } catch WebSocketError.notConnected where waitForInferenceReceipt && attempt == 0 {
                try await waitForReconnect(wsManager, accountScope: scope, validateRemoteSend: validateRemoteSend)
            } catch WebSocketError.messageTimeout where waitForInferenceReceipt && attempt == 0 {
                try await waitForReconnect(wsManager, accountScope: scope, validateRemoteSend: validateRemoteSend)
            }
        }
        throw ChatSendError.webSocketUnavailable
    }

    private func waitForReconnect(_ transport: ChatWebSocketTransport, accountScope: UUID,
                                  validateRemoteSend: (() throws -> Void)?) async throws {
        guard let socket = transport as? WebSocketManager else { throw ChatSendError.webSocketUnavailable }
        for _ in 0..<120 {
            try Task.checkCancellation()
            guard OfflineStore.shared.scopeGeneration == accountScope else {
                throw ChatSendError.webSocketUnavailable
            }
            try validateRemoteSend?()
            if socket.connectionState == .connected { return }
            try await Task.sleep(for: .milliseconds(250))
        }
        throw WebSocketError.notConnected
    }

    func sendSavedChatTurn(
        turnId: String,
        preflightPayload: [String: Any],
        outboundPayload: [String: Any],
        transport: ChatWebSocketTransport,
        waitForInferenceReceipt: Bool = false,
        validateRemoteSend: (() throws -> Void)? = nil
    ) async throws {
        // Capture ownership before the preflight await. A replaced account/team
        // must not adopt this queued send into its local processing activity.
        let processingScope = ActiveChatsCoordinator.shared.currentScope
        let processingChatID = outboundPayload["chat_id"] as? String
        let processingMessageID = (outboundPayload["message"] as? [String: Any])?["message_id"] as? String
        func processingStarted() {
            if let processingScope, let processingChatID, let processingMessageID {
                ActiveChatsCoordinator.shared.started(chatID: processingChatID,
                    turnID: processingMessageID, scope: processingScope)
            }
        }
        func processingFailed() {
            if let processingScope, let processingChatID, let processingMessageID {
                ActiveChatsCoordinator.shared.finished(chatID: processingChatID,
                    turnID: processingMessageID, scope: processingScope)
            }
        }
        try validateRemoteSend?()
        let acknowledgement = (try await transport.sendAndWait(
            WSOutboundMessage(type: "chat_turn_preflight", payload: preflightPayload),
            responseType: "chat_turn_preflight_ack"
        ) {
                $0["turn_id"] as? String == turnId
        }).fields
        // Account/socket ownership may change while waiting for preflight. Do not
        // send this turn's plaintext history through a replacement session.
        try validateRemoteSend?()
        guard let preflightId = acknowledgement["preflight_id"] as? String, !preflightId.isEmpty,
              let state = acknowledgement["state"] as? String else {
            throw ChatSendError.webSocketUnavailable
        }
        guard let committedTurnId = outboundPayload["turn_id"] as? String,
              committedTurnId == turnId,
              let preflightInference = preflightPayload["inference_request"] as? [String: Any],
              NSDictionary(dictionary: preflightInference).isEqual(to: outboundPayload) else {
            throw ChatSendError.webSocketUnavailable
        }
        // Retrying an exact durable turn returns its current server state, not
        // necessarily PREPARED. A notification interrupted after admission must
        // finish its queue entry without submitting another inference request.
        // FAILED is not successful delivery to AI and stays visible to retry/error
        // handling; the server cannot safely enqueue that same failed turn again.
        // See backend/core/directus/extensions/chat-recovery-transaction/src/operations.js.
        if waitForInferenceReceipt {
            switch state {
            case "ENQUEUED", "RUNNING":
                processingStarted()
                return
            case "TERMINAL":
                processingFailed()
                return
            case "FAILED":
                processingFailed()
                throw ChatSendError.inferenceFailed
            default:
                break
            }
        }
        guard state == "PREPARED" || state == "LEGACY" else {
            throw ChatSendError.webSocketUnavailable
        }
        var committedPayload = outboundPayload
        committedPayload["protocol_version"] = ChatCompletionRecoveryCoordinator.protocolVersion
        committedPayload["preflight_id"] = preflightId
        let commit = WSOutboundMessage(type: "chat_message_added", payload: committedPayload)
        processingStarted()
        do {
            if waitForInferenceReceipt {
                guard let chatId = outboundPayload["chat_id"] as? String, !chatId.isEmpty,
                      let message = outboundPayload["message"] as? [String: Any],
                      let messageId = message["message_id"] as? String, !messageId.isEmpty else {
                    throw ChatSendError.webSocketUnavailable
                }
                // Socket-write completion only means bytes left this client. Keep a
                // background reply pending until AI admission is acknowledged. Register
                // the waiter before sending so a fast server cannot outrun it.
                _ = try await transport.sendAndWait(commit, responseType: "ai_task_initiated") { fields in
                    if fields["code"] as? String != nil {
                        return fields["turn_id"] as? String == turnId ||
                            (fields["chat_id"] as? String == chatId &&
                             ((fields["user_message_id"] ?? fields["message_id"]) as? String) == messageId)
                    }
                    return fields["chat_id"] as? String == chatId &&
                        fields["user_message_id"] as? String == messageId &&
                        ((fields["ai_task_id"] ?? fields["task_id"]) as? String)?.isEmpty == false
                }
            } else {
                try await transport.send(commit)
            }
        } catch {
            // A transport timeout may follow server admission. Keep the stale,
            // time-bounded state until an exact terminal receipt proves completion.
            if let sendError = error as? ChatSendError, case .inferenceFailed = sendError { processingFailed() }
            throw error
        }
    }

    static func shouldIncludeInitialChatMetadata(
        messagesVersion: Int?, titleVersion: Int?, existingMessageCount: Int
    ) -> Bool {
        // Title generation can lag behind a completed conversation. Existing
        // messages make this an existing chat even while its title version is 0.
        (messagesVersion ?? 0) == 0 && existingMessageCount == 0 && (titleVersion ?? 0) == 0
    }

    func savedChatPreflightPayload(
        chatId: String,
        turnId: String,
        messageId: String,
        encryptedChatKey: String,
        recoveryPublicKey: String,
        expectedMessagesVersion: Int,
        encryptedUserMessage: [String: Any],
        inferenceRequest: [String: Any],
        encryptedTitle: String?,
        createdAt: Int
    ) -> [String: Any] {
        var payload: [String: Any] = [
            "protocol_version": ChatCompletionRecoveryCoordinator.protocolVersion,
            "chat_id": chatId,
            "turn_id": turnId,
            "message_id": messageId,
            "chat_key_version": ChatCompletionRecoveryCoordinator.protocolVersion,
            "encrypted_chat_key": encryptedChatKey,
            "recovery_public_key": recoveryPublicKey,
            "expected_messages_v": expectedMessagesVersion,
            "encrypted_user_message": encryptedUserMessage,
            "inference_request": inferenceRequest,
        ]
        if let encryptedTitle {
            payload["encrypted_chat_metadata"] = [
                "encrypted_title": encryptedTitle,
                "encrypted_chat_key": encryptedChatKey,
                "created_at": createdAt,
                "updated_at": createdAt,
            ]
        }
        return payload
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
        guard claimEncryptedUserStorage(messageId: userMessage.id) else { return chat }
        var storageCompleted = false
        defer {
            if !storageCompleted {
                releaseEncryptedUserStorage(messageId: userMessage.id)
            }
        }

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
        let encryptedPIIMappings: String?
        if let existing = userMessage.encryptedPIIMappings {
            encryptedPIIMappings = existing
        } else {
            encryptedPIIMappings = try await encryptPIIMappings(userMessage.piiMappings ?? [], key: keyMaterial.key)
        }
        let isNewChatMetadata = ChatGeneratedMetadataPolicy.needsGeneratedTitle(chat)
        let generatedTitle = metadata.title.map {
            Self.titleByReplacingEmbedReferences(
                $0.trimmingCharacters(in: .whitespacesAndNewlines),
                embedTypes: userMessage.embedRefs?.map(\.type) ?? []
            )
        }
        // The prompt title belongs only in the view model's in-memory presentation.
        // The generated title is the first authoritative encrypted title.
        let titleForStorage = generatedTitle?.isEmpty == false ? generatedTitle : nil
        let encryptedTitle = isNewChatMetadata && generatedTitle?.isEmpty == false
            ? try await encryptOptional(generatedTitle, key: keyMaterial.key) : nil
        let icon = isNewChatMetadata ? preferredIcon(from: metadata.iconNames, category: metadata.category) : nil
        let encryptedIcon = try await encryptOptional(icon, key: keyMaterial.key)
        let encryptedCategory = isNewChatMetadata ? try await encryptOptional(metadata.category, key: keyMaterial.key) : nil
        let encryptedSenderName = try await crypto.encryptContent("user", key: keyMaterial.key)
        let encryptedUserCategory = try await encryptOptional(metadata.category, key: keyMaterial.key)
        let createdAtUnix = Self.unixSeconds(from: userMessage.createdAt)
        let nextTitleV = encryptedTitle == nil ? chat.titleV : max(chat.titleV ?? 0, 0) + 1
        let updatedChat = copyChat(
            chat,
            title: isNewChatMetadata ? (titleForStorage ?? chat.title) : chat.title,
            updatedAt: Self.isoString(from: Date()),
            category: isNewChatMetadata ? (metadata.category ?? chat.category) : chat.category,
            icon: isNewChatMetadata ? (icon ?? chat.icon) : chat.icon,
            encryptedTitle: encryptedTitle ?? chat.encryptedTitle,
            encryptedCategory: encryptedCategory ?? chat.encryptedCategory,
            encryptedIcon: encryptedIcon ?? chat.encryptedIcon,
            encryptedChatKey: keyMaterial.encryptedChatKey,
            titleV: nextTitleV
        )
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
        if let encryptedPIIMappings { payload["encrypted_pii_mappings"] = encryptedPIIMappings }
        payload["encrypted_sender_name"] = encryptedSenderName
        if let encryptedUserCategory { payload["encrypted_category"] = encryptedUserCategory }

        let acknowledgement = try await wsManager.sendAndWait(
            WSOutboundMessage(type: "encrypted_chat_metadata", payload: payload),
            responseTypes: ["encrypted_metadata_stored", "incomplete_chat_metadata", "chat_key_mismatch"]
        ) { fields in
            fields["chat_id"] as? String == chat.id
                && fields["message_id"] as? String == userMessage.id
        }
        guard let acceptedVersions = ChatEncryptedMetadataAcknowledgementPolicy.acceptedVersions(
            from: acknowledgement.fields
        ) else {
            throw ChatSendError.webSocketUnavailable
        }
        let acceptedChat = copyChat(
            updatedChat,
            messagesV: acceptedVersions.messages,
            titleV: acceptedVersions.title,
            metadataV: acceptedVersions.metadata
        )
        chatStore?.upsertChat(acceptedChat)
        storageCompleted = true
        return acceptedChat
    }

    func claimEncryptedUserStorage(messageId: String) -> Bool {
        Self.encryptedUserStorageClaimed.insert(messageId).inserted
    }

    func releaseEncryptedUserStorage(messageId: String) {
        Self.encryptedUserStorageClaimed.remove(messageId)
    }

    func persistCompletedAssistantMessage(
        _ message: Message,
        userMessageId: String?,
        wsManager: WebSocketManager?,
        chatStore: ChatStore?,
        canonicalContent: String? = nil
    ) async throws -> Message {
        guard let wsManager else { throw ChatSendError.webSocketUnavailable }
        guard !completedAssistantStorageSent.contains(message.id) else { return message }
        guard let chat = chatStore?.chat(for: message.chatId) else { return message }
        let keyMaterial = try await ensureChatKey(chatId: message.chatId, encryptedChatKey: chat.encryptedChatKey)
        let encryptedContent: String
        if let existing = message.encryptedContent {
            encryptedContent = existing
        } else {
            let contentForPersistence = Self.canonicalAssistantContentForPersistence(
                displayContent: message.content,
                canonicalStreamContent: canonicalContent
            )
            encryptedContent = try await crypto.encryptContent(contentForPersistence, key: keyMaterial.key)
        }
        let encryptedCategory = try await encryptOptional(message.appId, key: keyMaterial.key)
        let encryptedModelName = try await encryptOptional(message.modelName, key: keyMaterial.key)
        let encryptedThinkingContent = try await encryptOptional(message.thinkingContent, key: keyMaterial.key)
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
            modelName: message.modelName,
            piiMappings: message.piiMappings,
            encryptedPIIMappings: message.encryptedPIIMappings,
            thinkingContent: message.thinkingContent,
            encryptedThinkingContent: encryptedThinkingContent,
            encryptedThinkingSignature: message.encryptedThinkingSignature,
            thinkingTokenCount: message.thinkingTokenCount, serverMessageId: message.serverMessageId
        )

        chatStore?.appendMessage(persisted, to: message.chatId)
        let localMessageCountAfterAppend = chatStore?.messages(for: message.chatId).count ?? 1

        if message.role == .system {
            var systemMessage: [String: Any] = [
                "message_id": message.id,
                "role": "system",
                "encrypted_content": encryptedContent,
                "created_at": createdAtUnix,
                "status": AgentContextEvent.parse(message.content ?? "") == nil ? "waiting_for_user" : "synced"
            ]
            if let userMessageId { systemMessage["user_message_id"] = userMessageId }
            do {
                try await wsManager.send(WSOutboundMessage(
                    type: "chat_system_message_added",
                    payload: [
                        "chat_id": message.chatId,
                        "message": systemMessage
                    ]
                ))
                completedAssistantStorageSent.insert(message.id)
                PendingAssistantResponseQueue.shared.remove(messageId: message.id)
            } catch {
                throw error
            }
        } else {
            let payload = assistantCompletionPayload(
                for: persisted,
                userMessageId: userMessageId,
                encryptedContent: encryptedContent,
                encryptedCategory: encryptedCategory,
                encryptedModelName: encryptedModelName,
                encryptedThinkingContent: encryptedThinkingContent,
                createdAtUnix: createdAtUnix,
                currentMessagesV: chat.messagesV,
                localMessageCountAfterAppendingAssistant: localMessageCountAfterAppend
            )
            do {
                try await wsManager.send(WSOutboundMessage(
                    type: "ai_response_completed",
                    payload: payload
                ))
                completedAssistantStorageSent.insert(message.id)
                PendingAssistantResponseQueue.shared.remove(messageId: message.id)
            } catch {
                PendingAssistantResponseQueue.shared.add(messageId: message.id, chatId: message.chatId)
                throw error
            }
        }
        return persisted
    }

    func flushPendingAssistantResponses(
        wsManager: WebSocketManager?,
        chatStore: ChatStore?,
        queue: PendingAssistantResponseQueue = .shared
    ) async {
        guard let chatStore else { return }
        for entry in queue.all() {
            let messages = chatStore.messages(for: entry.chatId)
            guard let message = messages.first(where: { $0.id == entry.messageId }) else { continue }
            guard message.role == .assistant || message.role == .system else {
                queue.remove(messageId: entry.messageId)
                continue
            }
            do {
                _ = try await persistCompletedAssistantMessage(
                    message,
                    userMessageId: inferredUserMessageId(before: message, in: messages),
                    wsManager: wsManager,
                    chatStore: chatStore
                )
            } catch {
                print("[ChatSendPipeline] Pending assistant response retry failed for chat \(entry.chatId.prefix(8)) message \(entry.messageId.prefix(8)): \(error)")
            }
        }
    }

    func inferredUserMessageId(before message: Message, in messages: [Message]) -> String? {
        let sortedMessages = messages.sorted { $0.createdAt < $1.createdAt }
        guard let messageIndex = sortedMessages.firstIndex(where: { $0.id == message.id }) else { return nil }
        return sortedMessages[..<messageIndex].last(where: { $0.role == .user })?.id
    }

    func completedAssistantMessagesVersion(
        currentMessagesV: Int?,
        localMessageCountAfterAppendingAssistant: Int
    ) -> Int {
        let localVersionBeforeAssistant = max(0, localMessageCountAfterAppendingAssistant - 1)
        return max(currentMessagesV ?? 0, localVersionBeforeAssistant) + 1
    }

    func assistantCompletionPayload(
        for message: Message,
        userMessageId: String?,
        encryptedContent: String,
        encryptedCategory: String?,
        encryptedModelName: String?,
        encryptedThinkingContent: String? = nil,
        createdAtUnix: Int,
        currentMessagesV: Int?,
        localMessageCountAfterAppendingAssistant: Int
    ) -> [String: Any] {
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
        if let encryptedThinkingContent { messagePayload["encrypted_thinking_content"] = encryptedThinkingContent }
        return [
            "chat_id": message.chatId,
            "message": messagePayload,
            "versions": [
                "messages_v": completedAssistantMessagesVersion(
                    currentMessagesV: currentMessagesV,
                    localMessageCountAfterAppendingAssistant: localMessageCountAfterAppendingAssistant
                ),
                "last_edited_overall_timestamp": createdAtUnix
            ]
        ]
    }

    static func canonicalAssistantContentForPersistence(
        displayContent: String?,
        canonicalStreamContent: String?
    ) -> String {
        let canonical = canonicalStreamContent?.trimmingCharacters(in: .whitespacesAndNewlines)
        if canonical?.isEmpty == false {
            return canonicalStreamContent ?? ""
        }
        return displayContent ?? ""
    }

    func sendPostProcessingMetadata(
        chatId: String,
        followUpSuggestions: [String],
        newChatSuggestions: [String],
        chatSummary: String?,
        chatTags: [String],
        updatedTitle: String?,
        sourceTitleVersion: Int? = nil,
        sourceMetadataVersion: Int? = nil,
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
            let encryptedFollowUpSuggestions = try await encryptStringArray(
                Array(followUpSuggestions.prefix(18)),
                key: keyMaterial.key
            )
            payload["encrypted_follow_up_suggestions"] = encryptedFollowUpSuggestions
            if !chatTags.isEmpty {
                payload["encrypted_chat_tags"] = try await encryptStringArray(Array(chatTags.prefix(10)), key: keyMaterial.key)
            }
            let acceptsGeneratedSummary = sourceMetadataVersion.map {
                (chat.metadataV ?? 0) <= $0
                    || (chat.chatSummary?.isEmpty != false && chat.encryptedChatSummary == nil)
            } ?? true
            var encryptedSummary: String?
            if acceptsGeneratedSummary, let chatSummary, !chatSummary.isEmpty {
                encryptedSummary = try await crypto.encryptContent(chatSummary, key: keyMaterial.key)
                payload["encrypted_chat_summary"] = encryptedSummary
            }
            let acceptsGeneratedTitle = sourceTitleVersion.map { (chat.titleV ?? 0) <= $0 } ?? true
            var encryptedUpdatedTitle: String?
            if acceptsGeneratedTitle, let updatedTitle, !updatedTitle.isEmpty {
                encryptedUpdatedTitle = try await crypto.encryptContent(updatedTitle, key: keyMaterial.key)
                payload["encrypted_title"] = encryptedUpdatedTitle
            }
            let proposedTitleVersion = encryptedUpdatedTitle == nil
                ? (chat.titleV ?? 0)
                : max(chat.titleV ?? 0, sourceTitleVersion ?? 0) + 1
            let currentMetadataVersion = (chat.metadataV ?? 0) > 0
                ? (chat.metadataV ?? 0) : (chat.titleV ?? 0)
            payload["versions"] = [
                "messages_v": chat.messagesV ?? 0,
                "title_v": proposedTitleVersion,
                "metadata_v": currentMetadataVersion,
                "draft_v": chat.draftV ?? 0
            ]
            if !newChatSuggestions.isEmpty,
               let userId = await AuthManager.currentUserId(),
               let masterKey = try await crypto.loadMasterKey(for: userId) {
                var encryptedSuggestions: [String] = []
                for suggestion in newChatSuggestions.prefix(6) {
                    encryptedSuggestions.append(try await crypto.encryptWithMasterKey(suggestion, masterKey: masterKey))
                }
                payload["encrypted_new_chat_suggestions"] = encryptedSuggestions
            }
            let acknowledgement = try await wsManager.sendAndWait(
                WSOutboundMessage(type: "update_post_processing_metadata", payload: payload),
                responseType: "post_processing_metadata_stored"
            ) { fields in
                fields["chat_id"] as? String == chatId
            }
            let acceptedVersions = acknowledgement.fields["versions"] as? [String: Any]
            let acceptedTitleVersion = acceptedVersions?["title_v"] as? Int
            let acceptedMetadataVersion = acceptedVersions?["metadata_v"] as? Int
            let acceptedExpectedMutation = acceptedMetadataVersion == currentMetadataVersion + 1
            let acceptedGeneratedTitle = encryptedUpdatedTitle != nil
                && acceptedExpectedMutation
                && acceptedTitleVersion == proposedTitleVersion
            let acceptedGeneratedSummary = encryptedSummary != nil && acceptedExpectedMutation
            chatStore?.upsertChat(copyChat(
                chat,
                title: acceptedGeneratedTitle ? updatedTitle : chat.title,
                updatedAt: Self.isoString(from: Date()),
                chatSummary: acceptedGeneratedSummary ? chatSummary : chat.chatSummary,
                encryptedTitle: acceptedGeneratedTitle ? encryptedUpdatedTitle : chat.encryptedTitle,
                encryptedChatSummary: acceptedGeneratedSummary ? encryptedSummary : chat.encryptedChatSummary,
                encryptedFollowUpRequestSuggestions: encryptedFollowUpSuggestions,
                encryptedAutoSpeakResponse: chat.encryptedAutoSpeakResponse,
                encryptedChatKey: keyMaterial.encryptedChatKey,
                titleV: acceptedGeneratedTitle ? acceptedTitleVersion : chat.titleV,
                metadataV: acceptedMetadataVersion ?? chat.metadataV
            ))
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
        let accountScope = OfflineStore.shared.scopeGeneration
        let cacheGeneration = ChatKeyManager.shared.cacheGeneration
        func requireCurrentScope() throws {
            guard accountScope == OfflineStore.shared.scopeGeneration,
                  cacheGeneration == ChatKeyManager.shared.cacheGeneration else {
                throw ChatSendError.webSocketUnavailable
            }
        }
        guard let userId = await AuthManager.currentUserId(),
              let masterKey = try await crypto.loadMasterKey(for: userId) else {
            throw ChatSendError.missingMasterKey
        }
        try requireCurrentScope()

        if let key = ChatKeyManager.shared.key(for: chatId) {
            if requiresCachedChatKeyValidation(cachedKeyExists: true, encryptedChatKey: encryptedChatKey),
               let encryptedChatKey {
                let wrappedKey = try await crypto.unwrapChatKey(encryptedChatKeyBase64: encryptedChatKey, masterKey: masterKey)
                guard Self.symmetricKeysEqual(key, wrappedKey) else {
                    throw ChatSendError.chatKeyMismatch
                }
                try requireCurrentScope()
                guard let stableEncrypted = ChatKeyManager.shared.installValidatedKey(
                    key, encryptedKey: encryptedChatKey, for: chatId, expectedGeneration: cacheGeneration
                ) else { throw ChatSendError.webSocketUnavailable }
                return (key, stableEncrypted)
            }
            if let cachedEncryptedKey = ChatKeyManager.shared.encryptedKey(for: chatId) {
                return (key, cachedEncryptedKey)
            }
            let encrypted = try await crypto.wrapChatKey(key, masterKey: masterKey)
            try requireCurrentScope()
            guard let stableEncrypted = ChatKeyManager.shared.rememberNewEncryptedKeyIfAbsent(
                encrypted, for: chatId, matching: key, expectedGeneration: cacheGeneration
            ) else { throw ChatSendError.webSocketUnavailable }
            return (key, stableEncrypted)
        }

        if let encryptedChatKey {
            let key = try await crypto.unwrapChatKey(encryptedChatKeyBase64: encryptedChatKey, masterKey: masterKey)
            try requireCurrentScope()
            guard let stableEncrypted = ChatKeyManager.shared.installValidatedKey(
                key, encryptedKey: encryptedChatKey, for: chatId, expectedGeneration: cacheGeneration
            ) else { throw ChatSendError.webSocketUnavailable }
            return (key, stableEncrypted)
        }

        let key = await ChatKeyManager.shared.createKeyForNewChat(chatId)
        try requireCurrentScope()
        if let cachedEncryptedKey = ChatKeyManager.shared.encryptedKey(for: chatId) {
            return (key, cachedEncryptedKey)
        }
        let encrypted = try await crypto.wrapChatKey(key, masterKey: masterKey)
        try requireCurrentScope()
        guard let stableEncrypted = ChatKeyManager.shared.rememberNewEncryptedKeyIfAbsent(
            encrypted, for: chatId, matching: key, expectedGeneration: cacheGeneration
        ) else { throw ChatSendError.webSocketUnavailable }
        return (key, stableEncrypted)
    }

    func requiresCachedChatKeyValidation(cachedKeyExists: Bool, encryptedChatKey: String?) -> Bool {
        cachedKeyExists && encryptedChatKey?.isEmpty == false
    }

    private static func symmetricKeysEqual(_ lhs: SymmetricKey, _ rhs: SymmetricKey) -> Bool {
        lhs.withUnsafeBytes { leftBytes in
            rhs.withUnsafeBytes { rightBytes in
                Data(leftBytes) == Data(rightBytes)
            }
        }
    }

    private func encryptedEmbeds(
        _ embeds: [ComposerPendingEmbed],
        chatId: String,
        messageId: String,
        chatKey: SymmetricKey
    ) async throws -> [[String: Any]] {
        let persistableEmbeds = try Self.requiredEncryptedBundles(embeds, referenceScope: .current)
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
            guard let content = embed.content else { throw ComposerEmbedStorageError.missingRequiredContent(embed.id) }
            let embedKey = ComposerEmbedCrypto.deriveKey(chatKey: chatKey, embedId: embed.id)
            let hashedEmbedId = sha256Hex(embed.id)
            let wrappedWithMaster = try ComposerEmbedCrypto.wrapKey(embedKey, using: masterKey)
            let wrappedWithChat = try ComposerEmbedCrypto.wrapKey(embedKey, using: chatKey)
            var payload: [String: Any] = [
                "embed_id": embed.id,
                "encrypted_type": try ComposerEmbedCrypto.encryptContent(embed.type, using: embedKey),
                "encrypted_content": try ComposerEmbedCrypto.encryptContent(content, using: embedKey),
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
                payload["encrypted_text_preview"] = try ComposerEmbedCrypto.encryptContent(textPreview, using: embedKey)
            }
            encryptedPayloads.append(payload)
        }
        return encryptedPayloads
    }

    static func requiredEncryptedBundles(_ embeds: [ComposerPendingEmbed],
                                         referenceScope: ComposerEmbedReferenceScope) throws -> [ComposerPendingEmbed] {
        try embeds.filter { embed in
            switch embed.storageDisposition {
            case .requiredEncryptedBundle:
                guard embed.content != nil else { throw ComposerEmbedStorageError.missingRequiredContent(embed.id) }
                return true
            case .existingStoredReference(let provenance):
                guard provenance == referenceScope else { throw ComposerEmbedStorageError.staleStoredReference(embed.id) }
                // Edits must be prepared explicitly as a fresh bundle. Never
                // silently discard new content because an old ID was retained.
                guard embed.content == nil else { throw ComposerEmbedStorageError.changedStoredReference(embed.id) }
                return false
            }
        }
    }

    /// Fresh sends only. Stored reference edits remain explicit new bundles;
    /// a local decrypted record is never a missing server head's replacement.
    static func validateFreshStoredReferences(_ embeds: [ComposerPendingEmbed],
        referenceScope: ComposerEmbedReferenceScope, serverProfile: ServerProfile,
        validate: () throws -> Void,
        probe: ([String]) async throws -> [String: EmbedReferenceAvailabilityState]) async throws {
        _ = try requiredEncryptedBundles(embeds, referenceScope: referenceScope)
        try validate()
        guard APIClient.supportsEmbedReferenceAvailability(serverProfile) else { return }
        var seen = Set<String>()
        let ids = embeds.compactMap { embed -> String? in
            guard case .existingStoredReference = embed.storageDisposition,
                  seen.insert(embed.id).inserted else { return nil }
            return embed.id
        }
        guard !ids.isEmpty else { return }
        let states = try await probe(ids)
        try Task.checkCancellation()
        try validate()
        guard Set(states.keys) == Set(ids) else { throw APIError.invalidResponse }
        for id in ids {
            switch states[id] {
            case .ready: break // Cross-chat owner/master references are authoritative here.
            case .missing: throw ComposerEmbedStorageError.missingRequiredContent(id)
            case .unusable: throw ComposerEmbedStorageError.staleStoredReference(id)
            case nil: throw APIError.invalidResponse
            }
        }
    }

    private func sha256Hex(_ value: String) -> String {
        SHA256.hash(data: Data(value.utf8)).map { String(format: "%02x", $0) }.joined()
    }

    private func encryptOptional(_ value: String?, key: SymmetricKey) async throws -> String? {
        guard let value, !value.isEmpty else { return nil }
        return try await crypto.encryptContent(value, key: key)
    }

    private func encryptPIIMappings(_ mappings: [PIIMapping], key: SymmetricKey) async throws -> String? {
        guard !mappings.isEmpty else { return nil }
        let data = try JSONEncoder().encode(mappings)
        let json = String(data: data, encoding: .utf8) ?? "[]"
        return try await crypto.encryptContent(json, key: key)
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
        encryptedFollowUpRequestSuggestions: String? = nil,
        encryptedAutoSpeakResponse: String? = nil,
        encryptedChatKey: String? = nil,
        messagesV: Int? = nil,
        titleV: Int? = nil,
        metadataV: Int? = nil
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
            encryptedFollowUpRequestSuggestions: encryptedFollowUpRequestSuggestions ?? chat.encryptedFollowUpRequestSuggestions,
            encryptedAutoSpeakResponse: encryptedAutoSpeakResponse ?? chat.encryptedAutoSpeakResponse,
            encryptedChatKey: encryptedChatKey ?? chat.encryptedChatKey,
            messagesV: messagesV ?? chat.messagesV,
            titleV: titleV ?? chat.titleV,
            draftV: chat.draftV,
            metadataV: metadataV ?? chat.metadataV,
            lastVisibleMessageId: chat.lastVisibleMessageId,
            parentId: chat.parentId,
            isSubChat: chat.isSubChat,
            subChatSettings: chat.subChatSettings,
            budgetLimit: chat.budgetLimit,
            budgetSpent: chat.budgetSpent,
            encryptedFocusPhaseState: chat.encryptedFocusPhaseState,
            encryptedActiveFocusId: chat.encryptedActiveFocusId,
            activeFocusId: chat.activeFocusId
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
    case chatKeyMismatch
    case historyUnavailable
    case inferenceFailed
    case retryContextUnavailable(String)

    @MainActor static var retryUnavailable: Self { .retryContextUnavailable(AppStrings.chatStorageRetryContextChanged) }

    var errorDescription: String? {
        switch self {
        case .missingMasterKey:
            return "Missing encryption key for this device. Please sign in again."
        case .webSocketUnavailable:
            return "Realtime connection is not ready. Please try again."
        case .historyUnavailable:
            return "Chat history could not be decrypted. Please reload this chat before sending."
        case .inferenceFailed:
            return "The message was saved, but its AI response failed. Open the chat to retry."
        case .chatKeyMismatch:
            return "Chat encryption keys are out of sync. Please reload this chat before sending."
        case .retryContextUnavailable(let description):
            return description
        }
    }
}

struct SubChatApprovalRequest: Decodable, Equatable, Sendable {
    let chatId: String
    let taskId: String
    let subChats: [SpawnedSubChat]?
    let maxAutoSubChats: Int?
    let maxDirectSubChats: Int?
    let existingSubChats: Int?
    let remainingSubChats: Int?
}

struct SubChatProgress: Decodable, Equatable, Sendable {
    let chatId: String
    let taskId: String?
    let executionMode: String?
    let status: String?
    let total: Int?
    let completed: Int?
    let activeSubChatId: String?
}

struct SpawnSubChatsPayload: Decodable, Equatable, Sendable {
    let parentId: String?
    let chatId: String?
    let subChats: [SpawnedSubChat]
}

struct SpawnedSubChat: Decodable, Equatable, Identifiable, Sendable {
    let id: String
    let userMessageId: String
    let prompt: String
    let title: String?
    let category: String?
    let icon: String?
    let waitForCompletion: Bool?
}

struct SubChatCompletion: Decodable, Equatable, Sendable {
    let chatId: String
    let parentId: String?
    let summary: String?
}

struct SubChatConfirmationResolved: Decodable, Equatable, Sendable {
    let chatId: String
    let taskId: String
    let status: String
}

private struct LifecycleEnvelope<Payload: Decodable>: Decodable {
    let payload: Payload?
    let data: Payload?
}
