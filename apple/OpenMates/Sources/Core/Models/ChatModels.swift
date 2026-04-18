// Chat and message data models matching the backend schemas.
// Used for chat list, message display, and streaming AI responses.
// E2EE fields (encrypted_*) are decrypted client-side using per-chat keys.

import Foundation

struct Chat: Identifiable, Decodable {
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

struct Message: Identifiable, Decodable {
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
}

enum MessageRole: String, Decodable {
    case user
    case assistant
    case system
}

struct EmbedRef: Decodable, Identifiable {
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
