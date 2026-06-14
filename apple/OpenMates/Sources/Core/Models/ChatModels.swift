// Chat and message data models matching the backend schemas.
// Used for chat list, message display, and streaming AI responses.
// E2EE fields (encrypted_*) are decrypted client-side using per-chat keys.

import Foundation
import OSLog

enum NativeSyncPerfLog {
    static let logger = Logger(subsystem: "org.openmates.app", category: "NativeSyncPerf")
    static let verboseCrypto = false

    static func now() -> CFAbsoluteTime {
        CFAbsoluteTimeGetCurrent()
    }

    static func ms(since start: CFAbsoluteTime) -> Int {
        Int((CFAbsoluteTimeGetCurrent() - start) * 1000)
    }

    static func info(_ message: String) {
        logger.info("\(message, privacy: .public)")
    }

    static func warning(_ message: String) {
        logger.warning("\(message, privacy: .public)")
    }
}

struct Chat: Identifiable, Decodable, Sendable {
    let id: String
    var title: String?             // Decrypted title (set client-side after decryption)
    let lastMessageAt: String?
    let createdAt: String
    let updatedAt: String?
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
    let encryptedChatKey: String?  // Per-chat AES key wrapped with master key (base64)
    let messagesV: Int?
    let titleV: Int?
    let draftV: Int?
    let lastVisibleMessageId: String?
    let parentId: String?
    let isSubChat: Bool?
    let subChatSettings: SubChatSettings?
    let budgetLimit: Double?
    let budgetSpent: Double?
    let encryptedActiveFocusId: String?
    var activeFocusId: String?

    init(
        id: String,
        title: String?,
        lastMessageAt: String?,
        createdAt: String,
        updatedAt: String?,
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
        encryptedChatKey: String?,
        messagesV: Int? = nil,
        titleV: Int? = nil,
        draftV: Int? = nil,
        lastVisibleMessageId: String? = nil,
        parentId: String? = nil,
        isSubChat: Bool? = nil,
        subChatSettings: SubChatSettings? = nil,
        budgetLimit: Double? = nil,
        budgetSpent: Double? = nil,
        encryptedActiveFocusId: String? = nil,
        activeFocusId: String? = nil
    ) {
        self.id = id
        self.title = title
        self.lastMessageAt = lastMessageAt
        self.createdAt = createdAt
        self.updatedAt = updatedAt
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
        self.encryptedChatKey = encryptedChatKey
        self.messagesV = messagesV
        self.titleV = titleV
        self.draftV = draftV
        self.lastVisibleMessageId = lastVisibleMessageId
        self.parentId = parentId
        self.isSubChat = isSubChat
        self.subChatSettings = subChatSettings
        self.budgetLimit = budgetLimit
        self.budgetSpent = budgetSpent
        self.encryptedActiveFocusId = encryptedActiveFocusId
        self.activeFocusId = activeFocusId
    }

    init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        id = try container.decodeIfPresent(String.self, forKey: .id)
            ?? container.decode(String.self, forKey: .chatId)
        title = try container.decodeIfPresent(String.self, forKey: .title)
        lastMessageAt = Self.decodeFlexibleDateString(container, .lastMessageAt)
            ?? Self.decodeFlexibleDateString(container, .lastMessageTimestamp)
            ?? Self.decodeFlexibleDateString(container, .lastEditedOverallTimestamp)
            ?? Self.decodeFlexibleDateString(container, .updatedAt)
        createdAt = Self.decodeFlexibleDateString(container, .createdAt)
            ?? Self.decodeFlexibleDateString(container, .updatedAt)
            ?? ISO8601DateFormatter().string(from: Date())
        updatedAt = Self.decodeFlexibleDateString(container, .updatedAt)
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
        encryptedChatKey = try container.decodeIfPresent(String.self, forKey: .encryptedChatKey)
        messagesV = try container.decodeIfPresent(Int.self, forKey: .messagesV)
        titleV = try container.decodeIfPresent(Int.self, forKey: .titleV)
        draftV = try container.decodeIfPresent(Int.self, forKey: .draftV)
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
        encryptedActiveFocusId = try container.decodeIfPresent(String.self, forKey: .encryptedActiveFocusId)
            ?? container.decodeIfPresent(String.self, forKey: .encryptedActiveFocusIdSnake)
        activeFocusId = try container.decodeIfPresent(String.self, forKey: .activeFocusId)
            ?? container.decodeIfPresent(String.self, forKey: .activeFocusIdSnake)
    }

    private static func decodeFlexibleDateString(
        _ container: KeyedDecodingContainer<CodingKeys>,
        _ key: CodingKeys
    ) -> String? {
        if let value = try? container.decodeIfPresent(String.self, forKey: key) {
            return value
        }
        if let value = try? container.decodeIfPresent(Int.self, forKey: key) {
            return ISO8601DateFormatter().string(from: Date(timeIntervalSince1970: TimeInterval(value)))
        }
        if let value = try? container.decodeIfPresent(Double.self, forKey: key) {
            return ISO8601DateFormatter().string(from: Date(timeIntervalSince1970: value))
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
        case encryptedChatSummary
        case encryptedChatKey
        case messagesV
        case titleV
        case draftV
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
        case encryptedActiveFocusId
        case encryptedActiveFocusIdSnake = "encrypted_active_focus_id"
        case activeFocusId
        case activeFocusIdSnake = "active_focus_id"
    }

    var displayTitle: String {
        title ?? "New Chat"
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
        let fractionalFormatter = ISO8601DateFormatter()
        fractionalFormatter.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        if let date = fractionalFormatter.date(from: value) {
            return date
        }
        return ISO8601DateFormatter().date(from: value)
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

struct Message: Identifiable, Decodable, Sendable {
    let id: String
    let chatId: String
    let role: MessageRole
    var content: String?           // Decrypted content (set client-side after decryption)
    let encryptedContent: String?  // AES-GCM encrypted content (base64, IV prepended)
    let createdAt: String
    let updatedAt: String?
    let appId: String?
    let isStreaming: Bool?
    let embedRefs: [EmbedRef]?
    let modelName: String?

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
        modelName: String? = nil
    ) {
        self.id = id
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
    }

    init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        id = try container.decodeIfPresent(String.self, forKey: .id)
            ?? container.decode(String.self, forKey: .messageId)
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
    }

    enum CodingKeys: String, CodingKey {
        case id
        case messageId = "message_id"
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
    }

    private static func decodeFlexibleDateString(
        _ container: KeyedDecodingContainer<CodingKeys>,
        _ key: CodingKeys
    ) -> String? {
        if let value = try? container.decodeIfPresent(String.self, forKey: key) {
            return value
        }
        if let value = try? container.decodeIfPresent(Int.self, forKey: key) {
            return ISO8601DateFormatter().string(from: Date(timeIntervalSince1970: TimeInterval(value)))
        }
        if let value = try? container.decodeIfPresent(Double.self, forKey: key) {
            return ISO8601DateFormatter().string(from: Date(timeIntervalSince1970: value))
        }
        return nil
    }
}

enum MessageRole: String, Decodable, Sendable {
    case user
    case assistant
    case system
}

struct EmbedRef: Codable, Identifiable, @unchecked Sendable {
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
