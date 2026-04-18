// "Search Chats" Shortcut — searches chat history by keyword and returns matches.
// Integrates with Spotlight and Siri for quick chat lookup.
// Returns chat titles with their last message timestamps.

import AppIntents
import Foundation

struct SearchChatsIntent: AppIntent {
    static let title: LocalizedStringResource = "Search OpenMates Chats"
    static let description: IntentDescription = "Search your chat history by keyword."
    static let openAppWhenRun = false

    @Parameter(title: "Search query", description: "Keyword to search for in chat titles")
    var query: String

    static var parameterSummary: some ParameterSummary {
        Summary("Search chats for \(\.$query)")
    }

    func perform() async throws -> some IntentResult & ReturnsValue<String> {
        let chats: ChatListResult = try await APIClient.shared.request(
            .get, path: "/v1/chats"
        )

        let matches = chats.chats.filter { chat in
            guard let title = chat.title else { return false }
            return title.localizedCaseInsensitiveContains(query)
        }

        if matches.isEmpty {
            return .result(value: "No chats found matching \"\(query)\".")
        }

        let lines = matches.prefix(10).map { chat in
            let title = chat.title ?? "Untitled"
            let date = chat.lastMessageAt ?? chat.createdAt
            return "• \(title) (\(date.prefix(10)))"
        }

        let header = "\(matches.count) chat\(matches.count == 1 ? "" : "s") found:"
        return .result(value: "\(header)\n\(lines.joined(separator: "\n"))")
    }
}

private struct ChatListResult: Decodable {
    let chats: [ChatItem]

    struct ChatItem: Decodable {
        let id: String
        let title: String?
        let lastMessageAt: String?
        let createdAt: String
    }
}
