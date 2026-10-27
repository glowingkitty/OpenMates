// Specification: specifications/features/chat-queued-followups/specification.yml
// Assertions: chat-queued-followups.admission.synced, chat-queued-followups.editing.stable-revision
// Chat and message data models matching the backend schemas.
// Used for chat list, message display, and streaming AI responses.
// E2EE fields (encrypted_*) are decrypted client-side using per-chat keys.
// Specification: specifications/features/chats/specification.yml
// Assertions: chats.followups.non-destructive-reconciliation, chats.surface.semantic-parity

// Specification: specifications/features/apple-recent-offline-chats/specification.yml
// Assertions: apple-offline.recent-cohort, apple-offline.local-first, apple-offline.interruption-isolation, apple-offline.snapshot-integrity

import Foundation
import CoreFoundation
import OSLog

// Shared immutable-format timestamp codec. Sorting hundreds of chat rows can
// call these accessors thousands of times per redraw; never construct ICU date
// formatters inside a sort comparator. The bounded cache contains dates only.
private final class ChatDateCodec: @unchecked Sendable {
    static let shared = ChatDateCodec()
    private let lock = NSLock()
    private let plain = ISO8601DateFormatter()
    private let fractional = ISO8601DateFormatter()
    private let dates = NSCache<NSString, NSDate>()

    private init() {
        fractional.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        dates.countLimit = 4096
    }

    func parse(_ value: String) -> Date? {
        if let cached = dates.object(forKey: value as NSString) { return cached as Date }
        lock.lock()
        defer { lock.unlock() }
        guard let parsed = fractional.date(from: value) ?? plain.date(from: value) else { return nil }
        dates.setObject(parsed as NSDate, forKey: value as NSString)
        return parsed
    }

    func string(from date: Date) -> String {
        lock.lock()
        defer { lock.unlock() }
        return plain.string(from: date)
    }
}

enum NativeSyncPerfLog {
    static let logger = Logger(subsystem: "org.openmates.app", category: "NativeSyncPerf")
    static let verboseCrypto = false

    static func now() -> CFAbsoluteTime {
        ProcessInfo.processInfo.systemUptime
    }

    static func ms(since start: CFAbsoluteTime) -> Int {
        Int((ProcessInfo.processInfo.systemUptime - start) * 1000)
    }

    static func info(_ message: String) {
        let sanitized = NativeClientLogCollector.sanitize(message)
        logger.info("\(sanitized, privacy: .public)")
        NativeClientLogCollector.shared.record(level: .info, category: "native_sync_perf", message: sanitized)
        NativeSyncDiagnosticsStore.shared.record(level: .info, message: sanitized)
    }

    static func warning(_ message: String) {
        let sanitized = NativeClientLogCollector.sanitize(message)
        logger.warning("\(sanitized, privacy: .public)")
        NativeClientLogCollector.shared.record(level: .warning, category: "native_sync_perf", message: sanitized)
        NativeSyncDiagnosticsStore.shared.record(level: .warning, message: sanitized)
    }
}

enum IncognitoChatSession {
    static let chatIdPrefix = "incognito-"

    static func isIncognitoChatId(_ chatId: String) -> Bool {
        chatId.hasPrefix(chatIdPrefix)
    }

    static func makeChatId() -> String {
        "\(chatIdPrefix)\(UUID().uuidString)"
    }
}

struct Chat: Identifiable, Decodable, Sendable {
    let id: String
    var title: String?             // Decrypted title (set client-side after decryption)
    let lastMessageAt: String?
    let createdAt: String
    let updatedAt: String?
    let lastEditedOverallTimestamp: String?
    let isArchived: Bool?
    let isPinned: Bool?
    let appId: String?
    var category: String?          // Decrypted category (set client-side after decryption)
    var icon: String?              // Decrypted Lucide icon name (set client-side after decryption)
    var chatSummary: String?       // Decrypted chat summary (set client-side after decryption)
    let encryptedTitle: String?    // AES-GCM encrypted title (base64, IV prepended)
    let encryptedCategory: String?
    let encryptedIcon: String?
    let encryptedChatSummary: String?
    let encryptedFollowUpRequestSuggestions: String?
    var encryptedAutoSpeakResponse: String?
    let encryptedChatKey: String?  // Per-chat AES key wrapped with master key (base64)
    let messagesV: Int?
    let titleV: Int?
    let draftV: Int?
    /// Presence, not version: nil means an older/partial snapshot omitted draft content.
    var hasNonEmptyDraft: Bool?
    var unreadCount: Int?
    var clearedDraftV: Int?
    let metadataV: Int?
    let lastVisibleMessageId: String?
    let parentId: String?
    let isSubChat: Bool?
    let subChatSettings: SubChatSettings?
    let budgetLimit: Double?
    let budgetSpent: Double?
    var encryptedFocusPhaseState: String?
    let encryptedActiveFocusId: String?
    var activeFocusId: String?
    let isPrivate: Bool?
    let isHidden: Bool?
    let isHiddenCandidate: Bool?
    var teamId: String?
    var isSharedByOthers: Bool?

    init(
        id: String,
        title: String?,
        lastMessageAt: String?,
        createdAt: String,
        updatedAt: String?,
        lastEditedOverallTimestamp: String? = nil,
        isArchived: Bool?,
        isPinned: Bool?,
        appId: String?,
        category: String? = nil,
        icon: String? = nil,
        chatSummary: String? = nil,
        encryptedTitle: String?,
        encryptedCategory: String? = nil,
        encryptedIcon: String? = nil,
        encryptedChatSummary: String? = nil,
        encryptedFollowUpRequestSuggestions: String? = nil,
        encryptedAutoSpeakResponse: String? = nil,
        encryptedChatKey: String?,
        messagesV: Int? = nil,
        titleV: Int? = nil,
        draftV: Int? = nil,
        metadataV: Int? = nil,
        lastVisibleMessageId: String? = nil,
        parentId: String? = nil,
        isSubChat: Bool? = nil,
        subChatSettings: SubChatSettings? = nil,
        budgetLimit: Double? = nil,
        budgetSpent: Double? = nil,
        encryptedFocusPhaseState: String? = nil,
        encryptedActiveFocusId: String? = nil,
        activeFocusId: String? = nil,
        isPrivate: Bool? = nil,
        isHidden: Bool? = nil,
        isHiddenCandidate: Bool? = nil,
        teamId: String? = nil,
        isSharedByOthers: Bool? = nil,
        hasNonEmptyDraft: Bool? = nil,
        clearedDraftV: Int? = nil,
        unreadCount: Int? = nil
    ) {
        self.unreadCount = unreadCount
        self.id = id
        self.title = title
        self.lastMessageAt = lastMessageAt
        self.createdAt = createdAt
        self.updatedAt = updatedAt
        self.lastEditedOverallTimestamp = lastEditedOverallTimestamp
        self.isArchived = isArchived
        self.isPinned = isPinned
        self.appId = appId
        self.category = category
        self.icon = icon
        self.chatSummary = chatSummary
        self.encryptedTitle = encryptedTitle
        self.encryptedCategory = encryptedCategory
        self.encryptedIcon = encryptedIcon
        self.encryptedChatSummary = encryptedChatSummary
        self.encryptedFollowUpRequestSuggestions = encryptedFollowUpRequestSuggestions
        self.encryptedAutoSpeakResponse = encryptedAutoSpeakResponse
        self.encryptedChatKey = encryptedChatKey
        self.messagesV = messagesV
        self.titleV = titleV
        self.draftV = draftV
        self.hasNonEmptyDraft = hasNonEmptyDraft
        self.clearedDraftV = clearedDraftV
        self.metadataV = metadataV
        self.lastVisibleMessageId = lastVisibleMessageId
        self.parentId = parentId
        self.isSubChat = isSubChat
        self.subChatSettings = subChatSettings
        self.budgetLimit = budgetLimit
        self.budgetSpent = budgetSpent
        self.encryptedFocusPhaseState = encryptedFocusPhaseState
        self.encryptedActiveFocusId = encryptedActiveFocusId
        self.activeFocusId = activeFocusId
        self.isPrivate = isPrivate
        self.isHidden = isHidden
        self.teamId = teamId
        self.isSharedByOthers = isSharedByOthers
        self.isHiddenCandidate = isHiddenCandidate
    }

    init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        teamId = try container.decodeIfPresent(String.self, forKey: .teamId) ?? container.decodeIfPresent(String.self, forKey: .teamIdSnake)
        isSharedByOthers = try container.decodeIfPresent(Bool.self, forKey: .isSharedByOthers) ?? container.decodeIfPresent(Bool.self, forKey: .isSharedByOthersSnake)
        id = try container.decodeIfPresent(String.self, forKey: .id)
            ?? container.decode(String.self, forKey: .chatId)
        title = try container.decodeIfPresent(String.self, forKey: .title)
        lastMessageAt = Self.decodeFlexibleDateString(container, .lastMessageAt)
            ?? Self.decodeFlexibleDateString(container, .lastMessageTimestamp)
            ?? Self.decodeFlexibleDateString(container, .lastEditedOverallTimestamp)
        createdAt = Self.decodeFlexibleDateString(container, .createdAt)
            ?? Self.decodeFlexibleDateString(container, .updatedAt)
            ?? ChatDateCodec.shared.string(from: Date())
        updatedAt = Self.decodeFlexibleDateString(container, .updatedAt)
        lastEditedOverallTimestamp = Self.decodeFlexibleDateString(container, .lastEditedOverallTimestamp)
        isArchived = try container.decodeIfPresent(Bool.self, forKey: .isArchived)
        isPinned = try container.decodeIfPresent(Bool.self, forKey: .isPinned)
            ?? container.decodeIfPresent(Bool.self, forKey: .pinned)
        appId = try container.decodeIfPresent(String.self, forKey: .appId)
        category = try container.decodeIfPresent(String.self, forKey: .category)
        icon = try container.decodeIfPresent(String.self, forKey: .icon)
        chatSummary = try container.decodeIfPresent(String.self, forKey: .chatSummary)
        encryptedTitle = try container.decodeIfPresent(String.self, forKey: .encryptedTitle)
        encryptedCategory = try container.decodeIfPresent(String.self, forKey: .encryptedCategory)
        encryptedIcon = try container.decodeIfPresent(String.self, forKey: .encryptedIcon)
        encryptedChatSummary = try container.decodeIfPresent(String.self, forKey: .encryptedChatSummary)
        encryptedFollowUpRequestSuggestions = try container.decodeIfPresent(String.self, forKey: .encryptedFollowUpRequestSuggestions)
            ?? container.decodeIfPresent(String.self, forKey: .encryptedFollowUpRequestSuggestionsSnake)
        encryptedAutoSpeakResponse = try container.decodeIfPresent(String.self, forKey: .encryptedAutoSpeakResponse)
        encryptedChatKey = try container.decodeIfPresent(String.self, forKey: .encryptedChatKey)
        messagesV = try container.decodeIfPresent(Int.self, forKey: .messagesV)
        titleV = try container.decodeIfPresent(Int.self, forKey: .titleV)
        draftV = try container.decodeIfPresent(Int.self, forKey: .draftV)
        unreadCount = try container.decodeIfPresent(Int.self, forKey: .unreadCount)
            ?? container.decodeIfPresent(Int.self, forKey: .unreadCountSnake)
        clearedDraftV = try container.decodeIfPresent(Int.self, forKey: .clearedDraftV)
        if container.contains(.encryptedDraftMd) {
            hasNonEmptyDraft = try container.decodeIfPresent(String.self, forKey: .encryptedDraftMd)?.isEmpty == false
        } else {
            hasNonEmptyDraft = nil
        }
        metadataV = try container.decodeIfPresent(Int.self, forKey: .metadataV)
        lastVisibleMessageId = try container.decodeIfPresent(String.self, forKey: .lastVisibleMessageId)
        parentId = try container.decodeIfPresent(String.self, forKey: .parentId)
            ?? container.decodeIfPresent(String.self, forKey: .parentIdSnake)
        isSubChat = try container.decodeIfPresent(Bool.self, forKey: .isSubChat)
            ?? container.decodeIfPresent(Bool.self, forKey: .isSubChatSnake)
        subChatSettings = try container.decodeIfPresent(SubChatSettings.self, forKey: .subChatSettings)
            ?? container.decodeIfPresent(SubChatSettings.self, forKey: .subChatSettingsSnake)
        budgetLimit = Self.decodeFlexibleDouble(container, .budgetLimit)
            ?? Self.decodeFlexibleDouble(container, .budgetLimitSnake)
        budgetSpent = Self.decodeFlexibleDouble(container, .budgetSpent)
            ?? Self.decodeFlexibleDouble(container, .budgetSpentSnake)
        encryptedFocusPhaseState = try container.decodeIfPresent(String.self, forKey: .encryptedFocusPhaseState)
            ?? container.decodeIfPresent(String.self, forKey: .encryptedFocusPhaseStateSnake)
        encryptedActiveFocusId = try container.decodeIfPresent(String.self, forKey: .encryptedActiveFocusId)
            ?? container.decodeIfPresent(String.self, forKey: .encryptedActiveFocusIdSnake)
        activeFocusId = try container.decodeIfPresent(String.self, forKey: .activeFocusId)
            ?? container.decodeIfPresent(String.self, forKey: .activeFocusIdSnake)
        isPrivate = try container.decodeIfPresent(Bool.self, forKey: .isPrivate)
            ?? container.decodeIfPresent(Bool.self, forKey: .isPrivateSnake)
        isHidden = try container.decodeIfPresent(Bool.self, forKey: .isHidden)
            ?? container.decodeIfPresent(Bool.self, forKey: .isHiddenSnake)
        isHiddenCandidate = try container.decodeIfPresent(Bool.self, forKey: .isHiddenCandidate)
            ?? container.decodeIfPresent(Bool.self, forKey: .isHiddenCandidateSnake)
    }

    private static func decodeFlexibleDateString(
        _ container: KeyedDecodingContainer<CodingKeys>,
        _ key: CodingKeys
    ) -> String? {
        if let value = try? container.decodeIfPresent(String.self, forKey: key) {
            return value
        }
        if let value = try? container.decodeIfPresent(Int.self, forKey: key) {
            return ChatDateCodec.shared.string(from: Date(timeIntervalSince1970: TimeInterval(value)))
        }
        if let value = try? container.decodeIfPresent(Double.self, forKey: key) {
            return ChatDateCodec.shared.string(from: Date(timeIntervalSince1970: value))
        }
        return nil
    }

    private static func decodeFlexibleDouble(
        _ container: KeyedDecodingContainer<CodingKeys>,
        _ key: CodingKeys
    ) -> Double? {
        if let value = try? container.decodeIfPresent(Double.self, forKey: key) {
            return value
        }
        if let value = try? container.decodeIfPresent(Int.self, forKey: key) {
            return Double(value)
        }
        return nil
    }

    private enum CodingKeys: String, CodingKey {
        case id
        case chatId
        case title
        case lastMessageAt
        case lastMessageTimestamp
        case lastEditedOverallTimestamp
        case createdAt
        case updatedAt
        case isArchived
        case isPinned
        case pinned
        case appId
        case category
        case icon
        case chatSummary
        case encryptedTitle
        case encryptedCategory
        case encryptedIcon
        case encryptedAutoSpeakResponse
        case encryptedChatSummary
        case encryptedFollowUpRequestSuggestions
        case encryptedFollowUpRequestSuggestionsSnake = "encrypted_follow_up_request_suggestions"
        case encryptedChatKey
        case messagesV
        case titleV
        case draftV
        case unreadCount
        case unreadCountSnake = "unread_count"
        case clearedDraftV
        case encryptedDraftMd
        case metadataV
        case lastVisibleMessageId
        case parentId
        case parentIdSnake = "parent_id"
        case isSubChat
        case isSubChatSnake = "is_sub_chat"
        case subChatSettings
        case subChatSettingsSnake = "sub_chat_settings"
        case budgetLimit
        case budgetLimitSnake = "budget_limit"
        case budgetSpent
        case budgetSpentSnake = "budget_spent"
        case encryptedFocusPhaseState
        case encryptedFocusPhaseStateSnake = "encrypted_focus_phase_state"
        case encryptedActiveFocusId
        case encryptedActiveFocusIdSnake = "encrypted_active_focus_id"
        case activeFocusId
        case activeFocusIdSnake = "active_focus_id"
        case teamId
        case teamIdSnake = "team_id"
        case isSharedByOthers
        case isSharedByOthersSnake = "is_shared_by_others"
        case isPrivate
        case isPrivateSnake = "is_private"
        case isHidden
        case isHiddenSnake = "is_hidden"
        case isHiddenCandidate
        case isHiddenCandidateSnake = "is_hidden_candidate"
    }

    var displayTitle: String {
        guard let title = title?.trimmingCharacters(in: .whitespacesAndNewlines), !title.isEmpty else {
            return "New Chat"
        }
        return title
    }

    var isRetiredBundledIntro: Bool { RetiredIntroChatPolicy.excludes(id) }

    var isHiddenFromNormalSurfaces: Bool {
        isHidden == true || isHiddenCandidate == true
    }

    /// Sidebar sorting/grouping use the web overall edit timestamp. Older
    /// snapshots without that field retain their message-time fallback.
    var sidebarActivityDate: Date? {
        lastEditedOverallTimestamp.flatMap(Self.parseDate) ?? lastMessageDate
    }

    var lastMessageDate: Date? {
        guard let dateStr = lastMessageAt else { return nil }
        return Self.parseDate(dateStr)
    }

    var createdDate: Date? {
        Self.parseDate(createdAt)
    }

    var updatedDate: Date? {
        guard let updatedAt else { return nil }
        return Self.parseDate(updatedAt)
    }

    private static func parseDate(_ value: String) -> Date? {
        ChatDateCodec.shared.parse(value)
    }
}

struct SubChatSettings: Codable, Equatable, Sendable {
    let waitForCompletion: Bool?
    let reportTrigger: String?

    private enum CodingKeys: String, CodingKey {
        case waitForCompletion
        case waitForCompletionSnake = "wait_for_completion"
        case reportTrigger
        case reportTriggerSnake = "report_trigger"
    }

    init(waitForCompletion: Bool? = nil, reportTrigger: String? = nil) {
        self.waitForCompletion = waitForCompletion
        self.reportTrigger = reportTrigger
    }

    init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        waitForCompletion = try container.decodeIfPresent(Bool.self, forKey: .waitForCompletion)
            ?? container.decodeIfPresent(Bool.self, forKey: .waitForCompletionSnake)
        reportTrigger = try container.decodeIfPresent(String.self, forKey: .reportTrigger)
            ?? container.decodeIfPresent(String.self, forKey: .reportTriggerSnake)
    }

    func encode(to encoder: Encoder) throws {
        var container = encoder.container(keyedBy: CodingKeys.self)
        try container.encodeIfPresent(waitForCompletion, forKey: .waitForCompletionSnake)
        try container.encodeIfPresent(reportTrigger, forKey: .reportTriggerSnake)
    }
}

struct PIIMapping: Codable, Equatable, Sendable {
    let placeholder: String
    let original: String
    let type: String
}

struct Message: Identifiable, Decodable, Sendable {
    let id: String
    /// Database identity is an alias; the client message ID is canonical across
    /// optimistic sends, cache hydration and Directus snapshots.
    let serverMessageId: String?
    let userMessageId: String?
    let queueRevision: Int?
    let queueMode: String?
    let queueDispatchStatus: String?
    let queueDispatchMode: String?
    let deliveryStatus: String?
    let chatId: String
    let role: MessageRole
    var content: String? {         // Decrypted content (set client-side after decryption)
        didSet {
            guard content != oldValue else { return }
            renderDocument = ChatHistoryRenderDocument.build(for: self)
        }
    }
    let encryptedContent: String?  // AES-GCM encrypted content (base64, IV prepended)
    let createdAt: String
    let updatedAt: String?
    let appId: String?
    let isStreaming: Bool?
    let embedRefs: [EmbedRef]?
    var modelName: String? {
        didSet {
            guard modelName != oldValue else { return }
            renderDocument = ChatHistoryRenderDocument.build(for: self)
        }
    }
    var senderName: String? {
        didSet {
            guard senderName != oldValue else { return }
            renderDocument = ChatHistoryRenderDocument.build(for: self)
        }
    }
    var category: String? {
        didSet {
            guard category != oldValue else { return }
            renderDocument = ChatHistoryRenderDocument.build(for: self)
        }
    }
    let encryptedSenderName: String?
    let encryptedCategory: String?
    let encryptedModelName: String?
    var piiMappings: [PIIMapping]?
    let encryptedPIIMappings: String?
    var thinkingContent: String?
    let encryptedThinkingContent: String?
    let encryptedThinkingSignature: String?
    let thinkingTokenCount: Int?
    private(set) var renderDocument: ChatHistoryRenderDocument?

    /// Resolve an explicit database alias without borrowing plaintext from an
    /// older edit or another chat. A valid canonical body always wins.
    func localBodySource(canonical: Message?, alias: Message?) -> Message? {
        guard canonical?.content == nil,
              let ciphertext = encryptedContent, !ciphertext.isEmpty,
              let alias, alias.id == serverMessageId, alias.chatId == chatId,
              alias.role == role, alias.encryptedContent == ciphertext,
              alias.content != nil else { return canonical ?? alias }
        if let canonical {
            guard canonical.id == id, canonical.chatId == chatId,
                  canonical.role == role, canonical.encryptedContent == ciphertext else { return canonical }
        }
        return alias
    }

    init(
        id: String,
        chatId: String,
        role: MessageRole,
        content: String?,
        encryptedContent: String?,
        createdAt: String,
        updatedAt: String?,
        appId: String?,
        isStreaming: Bool?,
        embedRefs: [EmbedRef]?,
        modelName: String? = nil,
        senderName: String? = nil,
        category: String? = nil,
        encryptedSenderName: String? = nil,
        encryptedCategory: String? = nil,
        encryptedModelName: String? = nil,
        piiMappings: [PIIMapping]? = nil,
        encryptedPIIMappings: String? = nil,
        thinkingContent: String? = nil,
        encryptedThinkingContent: String? = nil,
        encryptedThinkingSignature: String? = nil,
        thinkingTokenCount: Int? = nil,
        renderDocument: ChatHistoryRenderDocument? = nil,
        serverMessageId: String? = nil,
        userMessageId: String? = nil,
        queueRevision: Int? = nil, queueMode: String? = nil, queueDispatchStatus: String? = nil,
        queueDispatchMode: String? = nil, deliveryStatus: String? = nil
    ) {
        self.id = id
        self.serverMessageId = serverMessageId == id ? nil : serverMessageId
        self.userMessageId = userMessageId
        self.queueRevision = queueRevision; self.queueMode = queueMode; self.queueDispatchStatus = queueDispatchStatus
        self.queueDispatchMode = queueDispatchMode; self.deliveryStatus = deliveryStatus
        self.chatId = chatId
        self.role = role
        self.content = content
        self.encryptedContent = encryptedContent
        self.createdAt = createdAt
        self.updatedAt = updatedAt
        self.appId = appId
        self.isStreaming = isStreaming
        self.embedRefs = embedRefs
        self.modelName = modelName
        self.senderName = senderName
        self.category = category
        self.encryptedSenderName = encryptedSenderName
        self.encryptedCategory = encryptedCategory
        self.encryptedModelName = encryptedModelName
        self.piiMappings = piiMappings
        self.encryptedPIIMappings = encryptedPIIMappings
        self.thinkingContent = thinkingContent
        self.encryptedThinkingContent = encryptedThinkingContent
        self.encryptedThinkingSignature = encryptedThinkingSignature
        self.thinkingTokenCount = thinkingTokenCount
        self.renderDocument = renderDocument
        if self.renderDocument?.version != ChatHistoryRenderDocument.schemaVersion {
            self.renderDocument = ChatHistoryRenderDocument.build(for: self)
        }
    }

    init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        let databaseId = try container.decodeIfPresent(String.self, forKey: .id)
        id = try container.decodeIfPresent(String.self, forKey: .clientMessageId)
            ?? container.decodeIfPresent(String.self, forKey: .clientMessageIdSnake)
            ?? container.decodeIfPresent(String.self, forKey: .canonicalMessageId)
            ?? container.decodeIfPresent(String.self, forKey: .messageId)
            ?? container.decode(String.self, forKey: .id)
        let suppliedAlias = try container.decodeIfPresent(String.self, forKey: .serverMessageId)
        serverMessageId = suppliedAlias ?? (databaseId != id ? databaseId : nil)
        userMessageId = try container.decodeIfPresent(String.self, forKey: .userMessageId)
            ?? container.decodeIfPresent(String.self, forKey: .userMessageIdSnake)
        queueRevision = try container.decodeIfPresent(Int.self, forKey: .queueRevision)
            ?? container.decodeIfPresent(Int.self, forKey: .queueRevisionSnake)
        queueMode = try container.decodeIfPresent(String.self, forKey: .queueMode)
            ?? container.decodeIfPresent(String.self, forKey: .queueModeSnake)
        queueDispatchStatus = try container.decodeIfPresent(String.self, forKey: .queueDispatchStatus)
            ?? container.decodeIfPresent(String.self, forKey: .queueDispatchStatusSnake)
        queueDispatchMode = try container.decodeIfPresent(String.self, forKey: .queueDispatchMode)
            ?? container.decodeIfPresent(String.self, forKey: .queueDispatchModeSnake)
        deliveryStatus = try container.decodeIfPresent(String.self, forKey: .deliveryStatus)
        chatId = try container.decodeIfPresent(String.self, forKey: .chatId)
            ?? container.decode(String.self, forKey: .chatIdSnake)
        role = try container.decode(MessageRole.self, forKey: .role)
        content = try container.decodeIfPresent(String.self, forKey: .content)
        encryptedContent = try container.decodeIfPresent(String.self, forKey: .encryptedContent)
            ?? container.decodeIfPresent(String.self, forKey: .encryptedContentSnake)
        createdAt = Self.decodeFlexibleDateString(container, .createdAt)
            ?? Self.decodeFlexibleDateString(container, .createdAtSnake)
            ?? ""
        updatedAt = Self.decodeFlexibleDateString(container, .updatedAt)
            ?? Self.decodeFlexibleDateString(container, .updatedAtSnake)
        appId = try container.decodeIfPresent(String.self, forKey: .appId)
            ?? container.decodeIfPresent(String.self, forKey: .appIdSnake)
        isStreaming = try container.decodeIfPresent(Bool.self, forKey: .isStreaming)
            ?? container.decodeIfPresent(Bool.self, forKey: .isStreamingSnake)
        embedRefs = try container.decodeIfPresent([EmbedRef].self, forKey: .embedRefs)
            ?? container.decodeIfPresent([EmbedRef].self, forKey: .embedRefsSnake)
        modelName = try container.decodeIfPresent(String.self, forKey: .modelName)
            ?? container.decodeIfPresent(String.self, forKey: .modelNameSnake)
        senderName = try container.decodeIfPresent(String.self, forKey: .senderName)
            ?? container.decodeIfPresent(String.self, forKey: .senderNameSnake)
        category = try container.decodeIfPresent(String.self, forKey: .category)
        encryptedSenderName = try container.decodeIfPresent(String.self, forKey: .encryptedSenderName)
            ?? container.decodeIfPresent(String.self, forKey: .encryptedSenderNameSnake)
        encryptedCategory = try container.decodeIfPresent(String.self, forKey: .encryptedCategory)
            ?? container.decodeIfPresent(String.self, forKey: .encryptedCategorySnake)
        encryptedModelName = try container.decodeIfPresent(String.self, forKey: .encryptedModelName)
            ?? container.decodeIfPresent(String.self, forKey: .encryptedModelNameSnake)
        piiMappings = try container.decodeIfPresent([PIIMapping].self, forKey: .piiMappings)
            ?? container.decodeIfPresent([PIIMapping].self, forKey: .piiMappingsSnake)
        encryptedPIIMappings = try container.decodeIfPresent(String.self, forKey: .encryptedPIIMappings)
            ?? container.decodeIfPresent(String.self, forKey: .encryptedPIIMappingsSnake)
        thinkingContent = try container.decodeIfPresent(String.self, forKey: .thinkingContent)
            ?? container.decodeIfPresent(String.self, forKey: .thinkingContentSnake)
        encryptedThinkingContent = try container.decodeIfPresent(String.self, forKey: .encryptedThinkingContent)
            ?? container.decodeIfPresent(String.self, forKey: .encryptedThinkingContentSnake)
        encryptedThinkingSignature = try container.decodeIfPresent(String.self, forKey: .encryptedThinkingSignature)
            ?? container.decodeIfPresent(String.self, forKey: .encryptedThinkingSignatureSnake)
        thinkingTokenCount = try container.decodeIfPresent(Int.self, forKey: .thinkingTokenCount)
            ?? container.decodeIfPresent(Int.self, forKey: .thinkingTokenCountSnake)
        renderDocument = try container.decodeIfPresent(ChatHistoryRenderDocument.self, forKey: .renderDocument)
        if renderDocument?.version != ChatHistoryRenderDocument.schemaVersion {
            renderDocument = ChatHistoryRenderDocument.build(for: self)
        }
    }

    enum CodingKeys: String, CodingKey {
        case id
        case messageId = "message_id"
        case canonicalMessageId = "messageId"
        case clientMessageId
        case clientMessageIdSnake = "client_message_id"
        case serverMessageId
        case userMessageId
        case userMessageIdSnake = "user_message_id"
        case queueRevision
        case queueRevisionSnake = "queue_revision"
        case queueMode
        case queueModeSnake = "queue_mode"
        case queueDispatchStatus
        case queueDispatchStatusSnake = "queue_dispatch_status"
        case queueDispatchMode
        case queueDispatchModeSnake = "queue_dispatch_mode"
        case deliveryStatus = "status"
        case chatId
        case chatIdSnake = "chat_id"
        case role
        case content
        case encryptedContent
        case encryptedContentSnake = "encrypted_content"
        case createdAt
        case createdAtSnake = "created_at"
        case updatedAt
        case updatedAtSnake = "updated_at"
        case appId
        case appIdSnake = "app_id"
        case isStreaming
        case isStreamingSnake = "is_streaming"
        case embedRefs
        case embedRefsSnake = "embed_refs"
        case modelName
        case modelNameSnake = "model_name"
        case senderName
        case senderNameSnake = "sender_name"
        case category
        case encryptedSenderName
        case encryptedSenderNameSnake = "encrypted_sender_name"
        case encryptedCategory
        case encryptedCategorySnake = "encrypted_category"
        case encryptedModelName
        case encryptedModelNameSnake = "encrypted_model_name"
        case piiMappings
        case piiMappingsSnake = "pii_mappings"
        case encryptedPIIMappings
        case encryptedPIIMappingsSnake = "encrypted_pii_mappings"
        case thinkingContent
        case thinkingContentSnake = "thinking_content"
        case encryptedThinkingContent
        case encryptedThinkingContentSnake = "encrypted_thinking_content"
        case encryptedThinkingSignature
        case encryptedThinkingSignatureSnake = "encrypted_thinking_signature"
        case thinkingTokenCount
        case thinkingTokenCountSnake = "thinking_token_count"
        case renderDocument
    }

    private static func decodeFlexibleDateString(
        _ container: KeyedDecodingContainer<CodingKeys>,
        _ key: CodingKeys
    ) -> String? {
        if let value = try? container.decodeIfPresent(String.self, forKey: key) {
            return value
        }
        if let value = try? container.decodeIfPresent(Int.self, forKey: key) {
            return ChatDateCodec.shared.string(from: Date(timeIntervalSince1970: TimeInterval(value)))
        }
        if let value = try? container.decodeIfPresent(Double.self, forKey: key) {
            return ChatDateCodec.shared.string(from: Date(timeIntervalSince1970: value))
        }
        return nil
    }

    var renderDocumentForDisplay: ChatHistoryRenderDocument? {
        renderDocument
    }
}

enum MessageRole: String, Codable, Sendable {
    case user
    case assistant
    case system
}

struct EmbedRef: Codable, Equatable, Identifiable, @unchecked Sendable {
    let id: String
    let type: String
    let status: String?
    let data: [String: AnyCodable]?
}

// MARK: - Chat list response

struct ChatListResponse: Decodable {
    let chats: [Chat]
}

// MARK: - Message send

struct SendMessageRequest: Encodable {
    let chatId: String
    let content: String
    let encryptedContent: String?
    let contentIv: String?
    let appId: String?
}

// MARK: - Streaming

struct StreamChunk: Decodable {
    let type: String
    let content: String?
    let messageId: String?
    let done: Bool?
}

/// Applied context receipts are display provenance, never access grants.
/// Source: frontend/packages/ui/src/utils/{loadedMemoryReceipt,associateLoadedMemories}.ts
struct ChatAppliedMemory: Equatable, Sendable, Identifiable {
    let id: String
    let title: String
    let source: String
    let appId: String?
    let projectId: String?
    let revision: String
    let body: String
}

struct ChatLoadedMemoryReceipt: Equatable, Sendable {
    let setKey: String
    let userMessageId: String?
    let assistantMessageId: String?
    let memories: [ChatAppliedMemory]

    static func parse(_ content: String?) -> Self? {
        guard let content, content.utf8.count <= 160_000,
              let bytes = content.data(using: .utf8),
              let event = try? JSONSerialization.jsonObject(with: bytes) as? [String: Any],
              event["type"] as? String == "memories_loaded",
              let setKey = event["set_key"] as? String, digest(setKey),
              let rows = event["memories"] as? [[String: Any]], (1...24).contains(rows.count),
              let count = event["count"] as? NSNumber, CFGetTypeID(count) != CFBooleanGetTypeID(),
              count.doubleValue == Double(rows.count) else { return nil }
        func optionalIdentity(_ key: String) -> Bool {
            guard let value = event[key] else { return true }
            guard let value = value as? String else { return false }
            return value.range(of: "^[A-Za-z0-9][A-Za-z0-9_:-]{0,239}$", options: .regularExpression) != nil
        }
        guard optionalIdentity("user_message_id"), optionalIdentity("assistant_message_id") else { return nil }
        var ids = Set<String>(), total = 0, memories: [ChatAppliedMemory] = []
        for row in rows {
            guard let id = text(row["id"], max: 240), ids.insert(id).inserted,
                  let title = text(row["title"], max: 180), let body = text(row["body"], max: 20_000),
                  let revision = row["revision"] as? String, digest(revision),
                  let source = row["source"] as? String else { return nil }
            let app = row["app_id"] as? String, project = row["project_id"] as? String
            if source == "app" {
                guard let app = text(app, max: 64), app.range(of: "^[a-z][a-z0-9_]*$", options: .regularExpression) != nil,
                      id.hasPrefix("app:\(app):"), row["project_id"] == nil || row["project_id"] is NSNull else { return nil }
            } else if source == "project" {
                guard text(project, max: 240) != nil, row["app_id"] == nil || row["app_id"] is NSNull else { return nil }
            } else { return nil }
            total += (body as NSString).length
            guard total <= 32_000 else { return nil }
            memories.append(ChatAppliedMemory(id: id, title: title, source: source, appId: app,
                projectId: project, revision: revision, body: body))
        }
        return Self(setKey: setKey, userMessageId: event["user_message_id"] as? String,
            assistantMessageId: event["assistant_message_id"] as? String, memories: memories)
    }
    private static func text(_ value: Any?, max: Int) -> String? {
        guard let string = value as? String, !string.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty,
              (string as NSString).length <= max else { return nil }
        return string
    }
    private static func digest(_ string: String) -> Bool {
        string.range(of: "^[a-f0-9]{64}$", options: .regularExpression) != nil
    }
}

struct ChatMemoryAssociations {
    var byAssistantID: [String: [ChatAppliedMemory]] = [:]
    var attachedReceiptIDs: Set<String> = []

    /// Resolve across the loaded ordered history before transcript windowing.
    /// An explicit identity never falls back to a nearby response on mismatch.
    static func resolve(_ messages: [Message], pending: ChatTransientAssistantResponse?,
                        userMessageIDs: [String: String] = [:]) -> Self {
        var result = Self()
        let assistants = messages.filter { $0.role == .assistant }
        for (index, row) in messages.enumerated() where row.role == .system {
            guard let receipt = ChatLoadedMemoryReceipt.parse(row.content) else { continue }
            func userID(_ candidate: Message) -> String? { candidate.userMessageId ?? userMessageIDs[candidate.id] }
            func matches(_ candidate: Message) -> Bool {
                candidate.chatId == row.chatId && (receipt.userMessageId == nil || userID(candidate) == nil || receipt.userMessageId == userID(candidate))
            }
            let candidate: Message?
            if let assistantID = receipt.assistantMessageId {
                candidate = assistants.first { $0.id == assistantID && matches($0) }
            } else if let user = receipt.userMessageId {
                let found = assistants.filter { userID($0) == user && $0.chatId == row.chatId }
                candidate = found.count == 1 ? found[0] : nil
            } else {
                var first = index, last = index + 1
                while first > 0 && messages[first - 1].role != .user { first -= 1 }
                guard first > 0 || messages.first?.role == .user else { continue }
                while last < messages.count && messages[last].role != .user { last += 1 }
                let found = messages[first..<last].filter { $0.role == .assistant && matches($0) }
                candidate = found.count == 1 ? found[0] : nil
            }
            let pendingMatches = pending.map { pending in
                pending.chatId == row.chatId && candidate == nil
                    && (receipt.userMessageId == nil || receipt.userMessageId == pending.userMessageId)
                    && (receipt.assistantMessageId == pending.id || (receipt.assistantMessageId == nil && receipt.userMessageId != nil && receipt.userMessageId == pending.userMessageId))
            } ?? false
            guard let target = candidate?.id ?? (pendingMatches ? pending?.id : nil) else { continue }
            result.attachedReceiptIDs.insert(row.id)
            var current = result.byAssistantID[target] ?? []
            for memory in receipt.memories where !current.contains(where: { $0.id == memory.id && $0.revision == memory.revision }) { current.append(memory) }
            result.byAssistantID[target] = current
        }
        return result
    }
}

/// Matches web chatSyncServiceHandlersAI.ts final-chunk classification exactly.
enum ChatStreamFinalityPolicy {
    static func continuesTurn(_ fields: [String: Any]) -> Bool {
        fields["awaiting_async_skill_continuation"] as? Bool == true
            && fields["interrupted_by_revocation"] as? Bool != true
            && fields["interrupted_by_soft_limit"] as? Bool != true
            && (fields["rejection_reason"] as? String)?.isEmpty != false
    }
}

/// RAM-only preparation identity. A cache match is never send authorization.
struct ChatPreparationScope: Equatable, Sendable {
    let account: UUID
    let server: String
    let keyGeneration: UUID
    let teamID: String?
    let teamEpoch: UInt64
    let socketGeneration: Int
}

struct ChatPreparedPrivacyGeneration: Equatable, Sendable {
    let scope: ChatPreparationScope
    let generation: String
    let mutationRevision: UInt64
    private(set) var touchedAt: Date

    /// The caller supplies the fresh server generation on every Send. A focus
    /// warm-up, clock match, or local revision alone cannot authorize reuse.
    mutating func validateReuse(scope: ChatPreparationScope, freshGeneration: String?,
                                mutationRevision: UInt64, now: Date) -> Bool {
        guard self.scope == scope, freshGeneration == generation, !generation.isEmpty,
              self.mutationRevision == mutationRevision,
              now >= touchedAt, now.timeIntervalSince(touchedAt) < 7_200 else { return false }
        touchedAt = now
        return true
    }
}

enum ChatQueuedRevisionError: Error, Equatable {
    case invalidRequest
    case rejected(reason: String, currentRevision: Int?, retryable: Bool)
    case invalidReceipt
}

/// Immutable transport package for the existing revision API. Plaintext is only
/// the privacy-filtered inference value paired with its encrypted durable body.
struct ChatQueuedRevisionRequest: Sendable {
    let chatID: String
    let messageID: String
    let expectedRevision: Int
    let clientRequestID: String
    private let bytes: Data
    enum Mode: String, Sendable { case followUp = "follow_up", steer }

    init(chatID: String, messageID: String, expectedRevision: Int, clientRequestID: String = UUID().uuidString,
         mode: Mode, teamID: String?, content: String? = nil, encryptedContent: String? = nil,
         encryptedPIIMappings: String? = nil) throws {
        guard !chatID.isEmpty, (1...255).contains(messageID.count), expectedRevision >= 1,
              expectedRevision < Int.max, (1...128).contains(clientRequestID.count) else { throw ChatQueuedRevisionError.invalidRequest }
        var fields: [String: Any] = ["chat_id": chatID, "message_id": messageID,
            "expected_revision": expectedRevision, "client_request_id": clientRequestID, "queue_mode": mode.rawValue]
        if let teamID { fields["team_id"] = teamID }
        if let content {
            guard !content.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty,
                  content.utf8.count <= 2 * 1024 * 1024, let encryptedContent, !encryptedContent.isEmpty else { throw ChatQueuedRevisionError.invalidRequest }
            fields["content"] = content; fields["encrypted_content"] = encryptedContent
            fields["encrypted_pii_mappings"] = encryptedPIIMappings.map { $0 as Any } ?? NSNull()
        } else if encryptedContent != nil || encryptedPIIMappings != nil { throw ChatQueuedRevisionError.invalidRequest }
        self.chatID = chatID; self.messageID = messageID; self.expectedRevision = expectedRevision; self.clientRequestID = clientRequestID
        bytes = try JSONSerialization.data(withJSONObject: fields, options: [.sortedKeys])
    }
    func payload() throws -> [String: Any] {
        guard let fields = try JSONSerialization.jsonObject(with: bytes) as? [String: Any] else { throw ChatQueuedRevisionError.invalidRequest }
        return fields
    }
    func validateReceipt(_ fields: [String: Any], type: String) throws -> Int {
        guard fields["chat_id"] as? String == chatID, fields["message_id"] as? String == messageID,
              fields["client_request_id"] as? String == clientRequestID else { throw ChatQueuedRevisionError.invalidReceipt }
        if type == "queued_message_revision_rejected" {
            guard let reason = fields["reason_code"] as? String, !reason.isEmpty else { throw ChatQueuedRevisionError.invalidReceipt }
            throw ChatQueuedRevisionError.rejected(reason: reason, currentRevision: fields["current_revision"] as? Int,
                retryable: fields["retryable"] as? Bool == true)
        }
        guard type == "queued_message_updated", let revision = fields["queue_revision"] as? Int,
              revision == expectedRevision + 1,
              fields["queue_mode"] as? String == (try payload())["queue_mode"] as? String else { throw ChatQueuedRevisionError.invalidReceipt }
        if let content = (try payload())["encrypted_content"] as? String {
            guard fields["encrypted_content"] as? String == content else { throw ChatQueuedRevisionError.invalidReceipt }
            let expectedMappings = (try payload())["encrypted_pii_mappings"]
            guard NSDictionary(dictionary: ["value": fields["encrypted_pii_mappings"] ?? NSNull()]).isEqual(to: ["value": expectedMappings ?? NSNull()]) else { throw ChatQueuedRevisionError.invalidReceipt }
        }
        return revision
    }
}

struct ChatTransientAssistantResponse: Identifiable, Equatable, Sendable {
    let id: String
    let chatId: String
    let userMessageId: String?
    let mateCategory: String
    let mateName: String?
    var modelName: String? = nil
    var providerName: String? = nil
    var serverRegion: String? = nil
}
