// Unread messages store — tracks unread message counts per chat for badge display.
// Mirrors the web app's unreadMessagesStore.ts: increments on background AI responses,
// clears when user opens a chat, syncs total count to app badge.

import Foundation
import SwiftUI
#if os(iOS)
import UIKit
#endif

@MainActor
final class UnreadMessagesStore: ObservableObject {
    static let shared = UnreadMessagesStore()

    @Published private var unreadCounts: [String: Int] = [:]
    @Published private(set) var totalUnread: Int = 0

    private init() {}

    // MARK: - Increment (when AI response completes for a background chat)

    func incrementUnread(chatId: String) {
        unreadCounts[chatId, default: 0] += 1
        recalculateTotal()
    }

    // MARK: - Set specific count (for cross-device sync)

    func setUnread(chatId: String, count: Int) {
        if count <= 0 {
            unreadCounts.removeValue(forKey: chatId)
        } else {
            unreadCounts[chatId] = count
        }
        recalculateTotal()
    }

    // MARK: - Clear (when user opens a chat)

    func clearUnread(chatId: String) {
        unreadCounts.removeValue(forKey: chatId)
        recalculateTotal()
    }

    // MARK: - Query

    func getUnreadCount(chatId: String) -> Int {
        unreadCounts[chatId] ?? 0
    }

    func hasUnread(chatId: String) -> Bool {
        (unreadCounts[chatId] ?? 0) > 0
    }

    // MARK: - Clear all (on logout)

    func clearAll() {
        unreadCounts.removeAll()
        recalculateTotal()
    }

    // MARK: - Recalculate and update badge

    private func recalculateTotal() {
        totalUnread = unreadCounts.values.reduce(0, +)
        updateAppBadge()
    }

    private func updateAppBadge() {
        #if os(iOS)
        Task {
            let center = UNUserNotificationCenter.current()
            let settings = await center.notificationSettings()
            if settings.badgeSetting == .enabled {
                try? await center.setBadgeCount(totalUnread)
            }
        }
        #endif
    }
}
