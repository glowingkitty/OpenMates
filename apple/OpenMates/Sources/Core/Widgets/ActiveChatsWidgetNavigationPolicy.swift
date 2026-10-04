// Shared policy used by MainAppView's authenticated widget route and sidebar.
// Specification: specifications/features/apple-live-activities/specification.yml
// Assertions: apple-live-activities.processing.widget, apple-live-activities.lifecycle.isolation
import Foundation

@MainActor
enum ActiveChatsWidgetNavigationPolicy {
    static func accepts(_ route: WidgetActiveChatsRoute, accountID: String, server: ServerProfile,
                        readableTeamIDs: Set<String>) -> Bool {
        route.belongsTo(accountID: accountID, apiBaseURL: server.apiBaseURL, teamID: route.teamID)
            && (route.teamID.map { readableTeamIDs.contains($0) } ?? true)
    }
    static func canOpen(_ chat: Chat, teamID: String?, hiddenUnlocked: Bool) -> Bool {
        chat.teamId == teamID && (!chat.isHiddenFromNormalSurfaces || hiddenUnlocked)
    }
    static func rows(ids: [String], chats: [Chat], teamID: String?, hiddenUnlocked: Bool) -> [Chat] {
        let byID = Dictionary(chats.map { ($0.id, $0) }, uniquingKeysWith: { first, _ in first })
        return ids.enumerated().compactMap { index, id in
            guard WidgetActiveChatsLinks.safeID(id) else { return nil }
            if let chat = byID[id], chat.teamId == teamID,
               !chat.isHiddenFromNormalSurfaces || hiddenUnlocked { return chat }
            // Unknown/hidden runs retain a link without revealing title, category,
            // summary or draft. They are never persisted or opened as metadata.
            return Chat(id: id, title: AppStrings.activeChatsWidgetChat(number: index + 1),
                lastMessageAt: nil, createdAt: "1970-01-01T00:00:00Z", updatedAt: nil,
                isArchived: false, isPinned: false, appId: nil,
                encryptedTitle: nil, encryptedChatKey: nil, teamId: teamID)
        }
    }
}
