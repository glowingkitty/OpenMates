// APNs push notification registration and handling.
// Registers device token with backend, handles notification categories,
// and routes taps to the appropriate chat.

import Foundation
import UserNotifications
import SwiftUI

struct NotificationReplyRequest: Identifiable, Equatable {
    let id: String
    let chatId: String
    let content: String

    init(chatId: String, content: String) {
        self.id = UUID().uuidString
        self.chatId = chatId
        self.content = content
    }
}

@MainActor
final class PushNotificationManager: NSObject, ObservableObject {
    static let shared = PushNotificationManager()

    private enum NotificationAction {
        static let chatMessageCategory = "OPENMATES_CHAT_MESSAGE"
        static let reply = "OPENMATES_REPLY"
        static let openChat = "OPENMATES_OPEN_CHAT"
    }

    @Published var isRegistered = false
    @Published var pendingChatId: String?
    @Published var pendingReplyRequest: NotificationReplyRequest?

    override private init() {
        super.init()
    }

    func requestPermission() async -> Bool {
        let center = UNUserNotificationCenter.current()
        center.delegate = self
        configureChatMessageCategory(center: center)

        do {
            let granted = try await center.requestAuthorization(options: [.alert, .badge, .sound])
            if granted {
                await registerForRemoteNotifications()
            }
            isRegistered = granted
            return granted
        } catch {
            print("[Push] Permission error: \(error)")
            return false
        }
    }

    func registerForRemoteNotifications() async {
        #if os(iOS)
        await MainActor.run {
            UIApplication.shared.registerForRemoteNotifications()
        }
        #elseif os(macOS)
        NSApplication.shared.registerForRemoteNotifications()
        #endif
    }

    func handleDeviceToken(_ token: Data) {
        let tokenString = token.map { String(format: "%02x", $0) }.joined()
        print("[Push] Device token: \(tokenString)")

        Task {
            let publicKey = NotificationPreviewCrypto.loadOrCreatePublicKey()
            var body: [String: Any] = [
                "token": tokenString,
                "platform": "apns",
                "encryption_version": NotificationPreviewCrypto.encryptionVersion
            ]
            if let publicKey {
                body["notification_public_key"] = publicKey
            }
            try? await APIClient.shared.request(
                .post,
                path: "/v1/notifications/register-device",
                body: body
            ) as Data
        }
    }

    func handleRegistrationError(_ error: Error) {
        print("[Push] Registration failed: \(error.localizedDescription)")
    }

    func setBadgeCount(_ count: Int) {
        #if os(iOS)
        UNUserNotificationCenter.current().setBadgeCount(count) { error in
            if let error { print("[Push] Badge error: \(error)") }
        }
        #endif
    }

    func showChatMessageNotification(chatId: String) async {
        let center = UNUserNotificationCenter.current()
        configureChatMessageCategory(center: center)

        let settings = await center.notificationSettings()
        guard settings.authorizationStatus == .authorized || settings.authorizationStatus == .provisional else {
            return
        }

        let content = UNMutableNotificationContent()
        content.title = AppStrings.openMatesName
        content.body = AppStrings.newMessageReceived
        content.sound = .default
        content.categoryIdentifier = NotificationAction.chatMessageCategory
        content.threadIdentifier = chatId
        content.userInfo = ["chat_id": chatId]

        let request = UNNotificationRequest(
            identifier: "openmates-chat-\(chatId)-\(UUID().uuidString)",
            content: content,
            trigger: nil
        )

        do {
            try await center.add(request)
        } catch {
            print("[Push] Failed to show chat notification: \(error)")
        }
    }

    private func configureChatMessageCategory(center: UNUserNotificationCenter) {
        let replyAction = UNTextInputNotificationAction(
            identifier: NotificationAction.reply,
            title: AppStrings.clickToRespond,
            options: [],
            textInputButtonTitle: AppStrings.sendAction,
            textInputPlaceholder: AppStrings.typeMessage
        )
        let openAction = UNNotificationAction(
            identifier: NotificationAction.openChat,
            title: AppStrings.openChat,
            options: [.foreground]
        )
        let category = UNNotificationCategory(
            identifier: NotificationAction.chatMessageCategory,
            actions: [replyAction, openAction],
            intentIdentifiers: [],
            options: []
        )
        center.setNotificationCategories([category])
    }
}

// MARK: - UNUserNotificationCenterDelegate

extension PushNotificationManager: UNUserNotificationCenterDelegate {
    nonisolated func userNotificationCenter(
        _ center: UNUserNotificationCenter,
        willPresent notification: UNNotification
    ) async -> UNNotificationPresentationOptions {
        return [.banner, .sound, .badge]
    }

    nonisolated func userNotificationCenter(
        _ center: UNUserNotificationCenter,
        didReceive response: UNNotificationResponse
    ) async {
        let userInfo = response.notification.request.content.userInfo
        guard let chatId = (userInfo["chat_id"] as? String) ?? (userInfo["chatId"] as? String) else {
            return
        }

        if response.actionIdentifier == PushNotificationManager.NotificationAction.reply,
           let textResponse = response as? UNTextInputNotificationResponse {
            let reply = textResponse.userText.trimmingCharacters(in: .whitespacesAndNewlines)
            guard !reply.isEmpty else { return }
            await MainActor.run {
                pendingReplyRequest = NotificationReplyRequest(chatId: chatId, content: reply)
                setBadgeCount(0)
            }
            return
        }

        if response.actionIdentifier == PushNotificationManager.NotificationAction.openChat ||
            response.actionIdentifier == UNNotificationDefaultActionIdentifier {
            await MainActor.run {
                pendingChatId = chatId
                // Clear badge when user taps a notification
                setBadgeCount(0)
            }
        }
    }

    /// Increment badge count (called when a push notification arrives while app is active).
    func incrementBadge() {
        #if os(iOS)
        let currentCount = UIApplication.shared.applicationIconBadgeNumber
        setBadgeCount(currentCount + 1)
        #endif
    }

    /// Clear badge when user opens any chat.
    func clearBadge() {
        setBadgeCount(0)
    }
}
