// Public chat data models — intro, example, legal, announcement, and tips chats.
// These are hardcoded or fetched from the backend and shown to all users.
// Mirrors the web app's DemoChat/DemoChatMessage types.

import Foundation

struct DemoChat: Identifiable, Decodable {
    let chatId: String
    let slug: String
    let title: String
    let description: String?
    let messages: [DemoMessage]
    let metadata: DemoChatMetadata?

    var id: String { chatId }
}

struct DemoMessage: Identifiable, Decodable {
    let messageId: String
    let role: String
    let content: String
    let embedRefs: [EmbedRef]?

    var id: String { messageId }
}

struct DemoChatMetadata: Decodable {
    let category: String?
    let featured: Bool?
    let order: Int?
    let iconNames: [String]?
    let videoKey: String?
}

enum PublicChatCategory: String, CaseIterable {
    case intro = "openmates_official"
    case example = "example"
    case legal = "legal"
    case announcement = "announcements"
    case tips = "tips_and_tricks"

    var displayName: String {
        switch self {
        case .intro: return "Introduction"
        case .example: return "Example Chats"
        case .legal: return "Legal"
        case .announcement: return "Announcements"
        case .tips: return "Tips & Tricks"
        }
    }

    var icon: String {
        switch self {
        case .intro: return "introduction"
        case .example: return "chat"
        case .legal: return "legal"
        case .announcement: return "announcement"
        case .tips: return "insight"
        }
    }
}
