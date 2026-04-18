// Scene delegate — enables iPad multitasking (Split View, Slide Over, Stage Manager),
// Handoff continuation from other Apple devices, and home screen shortcut items.

import SwiftUI

#if os(iOS)
class SceneDelegate: NSObject, UIWindowSceneDelegate {
    func scene(
        _ scene: UIScene,
        willConnectTo session: UISceneSession,
        options connectionOptions: UIScene.ConnectionOptions
    ) {
        guard let windowScene = scene as? UIWindowScene else { return }

        // Enable all iPad multitasking sizes — Split View, Slide Over, Stage Manager
        if windowScene.responds(to: #selector(getter: UIWindowScene.sizeRestrictions)) {
            windowScene.sizeRestrictions?.minimumSize = CGSize(width: 320, height: 480)
            windowScene.sizeRestrictions?.maximumSize = CGSize(width: .greatestFiniteMagnitude, height: .greatestFiniteMagnitude)
        }

        // Handle Handoff activities that arrived at launch
        for activity in connectionOptions.userActivities {
            handleUserActivity(activity)
        }
    }

    func scene(_ scene: UIScene, openURLContexts URLContexts: Set<UIOpenURLContext>) {
        for context in URLContexts {
            NotificationCenter.default.post(
                name: .deepLinkReceived,
                object: nil,
                userInfo: ["url": context.url]
            )
        }
    }

    /// Handoff continuation — called when the user picks up an activity from another device
    func scene(_ scene: UIScene, continue userActivity: NSUserActivity) {
        handleUserActivity(userActivity)
    }

    func windowScene(
        _ windowScene: UIWindowScene,
        performActionFor shortcutItem: UIApplicationShortcutItem
    ) async -> Bool {
        switch shortcutItem.type {
        case "org.openmates.newchat":
            NotificationCenter.default.post(name: .newChat, object: nil)
            return true
        default:
            return false
        }
    }

    // MARK: - Handoff handler

    private func handleUserActivity(_ activity: NSUserActivity) {
        switch activity.activityType {
        case HandoffManager.viewChatActivityType:
            if let chatId = activity.userInfo?["chatId"] as? String {
                NotificationCenter.default.post(
                    name: .handoffChatReceived,
                    object: nil,
                    userInfo: ["chatId": chatId]
                )
            }
        case HandoffManager.browseChatsActivityType:
            // App is already at the chat list — no navigation needed
            break
        default:
            break
        }
    }
}

extension Notification.Name {
    static let deepLinkReceived = Notification.Name("openmates.deepLinkReceived")
    static let handoffChatReceived = Notification.Name("openmates.handoffChatReceived")
}
#endif
