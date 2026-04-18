// "Read Last Response" Shortcut — returns the most recent AI response from a chat.
// Useful for quick reference without opening the app, or for chaining with other
// Shortcuts (e.g., read the last AI response and send it via Messages).

import AppIntents
import Foundation

struct ReadLastResponseIntent: AppIntent {
    static let title: LocalizedStringResource = "Read Last AI Response"
    static let description: IntentDescription = "Get the most recent AI response from your latest chat."
    static let openAppWhenRun = false

    func perform() async throws -> some IntentResult & ReturnsValue<String> {
        // Get the most recent chat
        let chatList: RecentChatList = try await APIClient.shared.request(
            .get, path: "/v1/chats"
        )

        guard let latestChat = chatList.chats.first else {
            return .result(value: "No chats found.")
        }

        // Get messages from that chat
        let messages: [RecentMessage] = try await APIClient.shared.request(
            .get, path: "/v1/chats/\(latestChat.id)/messages"
        )

        // Find the last assistant message
        if let lastAssistant = messages.last(where: { $0.role == "assistant" }),
           let content = lastAssistant.content,
           !content.isEmpty {
            let chatTitle = latestChat.title ?? "Untitled"
            // Truncate for Siri readability (max ~500 chars for voice)
            let truncated = content.count > 500
                ? String(content.prefix(500)) + "…"
                : content
            return .result(value: "From \"\(chatTitle)\":\n\n\(truncated)")
        }

        return .result(value: "No AI response found in your most recent chat.")
    }
}

private struct RecentChatList: Decodable {
    let chats: [RecentChat]

    struct RecentChat: Decodable {
        let id: String
        let title: String?
    }
}

private struct RecentMessage: Decodable {
    let id: String
    let role: String
    let content: String?
}
