// Scene delegate — enables iPad multitasking (Split View, Slide Over, Stage Manager)
// and multiple window support on iPadOS 17+ and macOS 14+.

import SwiftUI

#if os(iOS)
class SceneDelegate: NSObject, UIWindowSceneDelegate {
    func scene(
        _ scene: UIScene,
        willConnectTo session: UISceneSession,
        options connectionOptions: UIScene.ConnectionOptions
    ) {
        guard let windowScene = scene as? UIWindowScene else { return }

        // Enable all iPad multitasking sizes
        if windowScene.responds(to: #selector(getter: UIWindowScene.sizeRestrictions)) {
            windowScene.sizeRestrictions?.minimumSize = CGSize(width: 320, height: 480)
            windowScene.sizeRestrictions?.maximumSize = CGSize(width: .greatestFiniteMagnitude, height: .greatestFiniteMagnitude)
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
}

extension Notification.Name {
    static let deepLinkReceived = Notification.Name("openmates.deepLinkReceived")
}
#endif
