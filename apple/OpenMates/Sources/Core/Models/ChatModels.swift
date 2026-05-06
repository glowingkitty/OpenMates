// Chat and message data models matching the backend schemas.
// Used for chat list, message display, and streaming AI responses.
// E2EE fields (encrypted_*) are decrypted client-side using per-chat keys.

import Foundation

struct Chat: Identifiable, Decodable, Sendable {
    let id: String
    var title: String?             // Decrypted title (set client-side after decryption)
    let lastMessageAt: String?
    let createdAt: String
    let updatedAt: String?
    let isArchived: Bool?
    let isPinned: Bool?
    let appId: String?
    let encryptedTitle: String?    // AES-GCM encrypted title (base64, IV prepended)
    let encryptedChatKey: String?  // Per-chat AES key wrapped with master key (base64)

    var displayTitle: String {
        title ?? "New Chat"
    }

    var lastMessageDate: Date? {
        guard let dateStr = lastMessageAt else { return nil }
        return ISO8601DateFormatter().date(from: dateStr)
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
        createdAt = try container.decodeIfPresent(String.self, forKey: .createdAt)
            ?? container.decodeIfPresent(String.self, forKey: .createdAtSnake)
            ?? ""
        updatedAt = try container.decodeIfPresent(String.self, forKey: .updatedAt)
            ?? container.decodeIfPresent(String.self, forKey: .updatedAtSnake)
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
}

enum MessageRole: String, Decodable, Sendable {
    case user
    case assistant
    case system
}

struct EmbedRef: Decodable, Identifiable, @unchecked Sendable {
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
