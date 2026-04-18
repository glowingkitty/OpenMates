// Chat Management Shortcuts — list, pin, archive, delete, and export chats.
// These give power users control over their chat history from Shortcuts.

import AppIntents
import Foundation

// MARK: - List Chats

struct ListChatsIntent: AppIntent {
    static let title: LocalizedStringResource = "List Chats"
    static let description: IntentDescription = "List your most recent OpenMates chats."
    static let openAppWhenRun = false

    @Parameter(title: "Max Results", description: "Number of chats to show", default: 10)
    var maxResults: Int

    static var parameterSummary: some ParameterSummary {
        Summary("List \(\.$maxResults) recent chats")
    }

    func perform() async throws -> some IntentResult & ReturnsValue<String> {
        let data: Data = try await APIClient.shared.request(
            .get, path: "/v1/chats"
        )

        let response = try JSONDecoder().decode(ShortcutChatList.self, from: data)
        let chats = Array(response.chats.prefix(maxResults))

        if chats.isEmpty {
            return .result(value: "No chats found.")
        }

        let lines = chats.enumerated().map { index, chat in
            let title = chat.title ?? "Untitled"
            let date = String((chat.lastMessageAt ?? chat.createdAt).prefix(10))
            let pin = (chat.isPinned ?? false) ? " [pinned]" : ""
            return "\(index + 1). \(title)\(pin) (\(date))"
        }

        return .result(value: "\(response.chats.count) total chats:\n\(lines.joined(separator: "\n"))")
    }
}

// MARK: - Pin/Unpin Chat

struct PinChatIntent: AppIntent {
    static let title: LocalizedStringResource = "Pin Chat"
    static let description: IntentDescription = "Pin or unpin an OpenMates chat."
    static let openAppWhenRun = false

    @Parameter(title: "Chat ID", description: "The ID of the chat")
    var chatId: String

    @Parameter(title: "Pin", description: "Pin (true) or unpin (false)", default: true)
    var pin: Bool

    static var parameterSummary: some ParameterSummary {
        Summary("\(\.$pin) chat \(\.$chatId)")
    }

    func perform() async throws -> some IntentResult & ReturnsValue<String> {
        let _: Data = try await APIClient.shared.request(
            .patch, path: "/v1/chats/\(chatId)",
            body: ["is_pinned": pin]
        )
        return .result(value: pin ? "Chat pinned." : "Chat unpinned.")
    }
}

// MARK: - Archive Chat

struct ArchiveChatIntent: AppIntent {
    static let title: LocalizedStringResource = "Archive Chat"
    static let description: IntentDescription = "Archive an OpenMates chat."
    static let openAppWhenRun = false

    @Parameter(title: "Chat ID", description: "The ID of the chat to archive")
    var chatId: String

    static var parameterSummary: some ParameterSummary {
        Summary("Archive chat \(\.$chatId)")
    }

    func perform() async throws -> some IntentResult & ReturnsValue<String> {
        let _: Data = try await APIClient.shared.request(
            .patch, path: "/v1/chats/\(chatId)",
            body: ["is_archived": true]
        )
        return .result(value: "Chat archived.")
    }
}

// MARK: - Delete Chat

struct DeleteChatIntent: AppIntent {
    static let title: LocalizedStringResource = "Delete Chat"
    static let description: IntentDescription = "Permanently delete an OpenMates chat."
    static let openAppWhenRun = false

    @Parameter(title: "Chat ID", description: "The ID of the chat to delete")
    var chatId: String

    static var parameterSummary: some ParameterSummary {
        Summary("Delete chat \(\.$chatId)")
    }

    func perform() async throws -> some IntentResult & ReturnsValue<String> {
        let _: Data = try await APIClient.shared.request(
            .delete, path: "/v1/chats/\(chatId)"
        )
        return .result(value: "Chat deleted.")
    }
}

// MARK: - Delete Old Chats

struct DeleteOldChatsIntent: AppIntent {
    static let title: LocalizedStringResource = "Delete Old Chats"
    static let description: IntentDescription = "Delete all chats older than a specified number of days."
    static let openAppWhenRun = false

    @Parameter(title: "Older than (days)", description: "Delete chats older than this many days")
    var olderThanDays: Int

    @Parameter(title: "Preview only", description: "Just show how many would be deleted without deleting", default: true)
    var previewOnly: Bool

    static var parameterSummary: some ParameterSummary {
        Summary("Delete chats older than \(\.$olderThanDays) days") {
            \.$previewOnly
        }
    }

    func perform() async throws -> some IntentResult & ReturnsValue<String> {
        if previewOnly {
            let data: Data = try await APIClient.shared.request(
                .get, path: "/v1/settings/chats/preview?older_than_days=\(olderThanDays)"
            )
            guard let json = try JSONSerialization.jsonObject(with: data) as? [String: Any],
                  let count = json["count"] as? Int else {
                return .result(value: "Could not preview.")
            }
            return .result(value: "\(count) chat\(count == 1 ? "" : "s") would be deleted (older than \(olderThanDays) days). Set 'Preview only' to false to delete.")
        } else {
            let _: Data = try await APIClient.shared.request(
                .post, path: "/v1/settings/chats/delete-old",
                body: ["older_than_days": olderThanDays]
            )
            return .result(value: "Chats older than \(olderThanDays) days deleted.")
        }
    }
}

// MARK: - Export Account Data

struct ExportDataIntent: AppIntent {
    static let title: LocalizedStringResource = "Export Account Data"
    static let description: IntentDescription = "Export all your OpenMates account data (GDPR data portability)."
    static let openAppWhenRun = false

    func perform() async throws -> some IntentResult & ReturnsValue<String> {
        let data: Data = try await APIClient.shared.request(
            .get, path: "/v1/settings/export-account-manifest"
        )
        guard let json = try JSONSerialization.jsonObject(with: data) as? [String: Any],
              let manifest = json["manifest"] as? [String: Any] else {
            return .result(value: "Could not fetch export manifest.")
        }

        var lines: [String] = ["Your account data summary:"]
        for (key, value) in manifest.sorted(by: { $0.key < $1.key }) {
            lines.append("• \(key): \(value)")
        }

        return .result(value: lines.joined(separator: "\n"))
    }
}

// MARK: - Chat Stats

struct ChatStatsIntent: AppIntent {
    static let title: LocalizedStringResource = "Chat Statistics"
    static let description: IntentDescription = "Get your OpenMates chat statistics."
    static let openAppWhenRun = false

    func perform() async throws -> some IntentResult & ReturnsValue<String> {
        let data: Data = try await APIClient.shared.request(
            .get, path: "/v1/settings/chats"
        )
        guard let json = try JSONSerialization.jsonObject(with: data) as? [String: Any],
              let total = json["total_count"] as? Int else {
            return .result(value: "Could not load chat stats.")
        }

        return .result(value: "You have \(total) chat\(total == 1 ? "" : "s").")
    }
}

// MARK: - Decodable helpers

private struct ShortcutChatList: Decodable {
    let chats: [ShortcutChat]
}

private struct ShortcutChat: Decodable {
    let id: String
    let title: String?
    let createdAt: String
    let lastMessageAt: String?
    let isPinned: Bool?
    let isArchived: Bool?
}
