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

private final class NotificationCompletionBox: @unchecked Sendable {
    private let completionHandler: () -> Void

    init(_ completionHandler: @escaping () -> Void) {
        self.completionHandler = completionHandler
    }

    func complete() {
        completionHandler()
    }
}

@MainActor
final class PushNotificationManager: NSObject, ObservableObject {
    static let shared = PushNotificationManager()

    private static let installationIDKey = "openmates.push.installationId"
    private static let deviceTokenKey = "openmates.push.deviceToken"

    private enum NotificationAction {
        static let chatMessageCategory = "OPENMATES_CHAT_MESSAGE"
        static let reply = "OPENMATES_REPLY"
        static let openChat = "OPENMATES_OPEN_CHAT"
    }

    @Published var isRegistered = false
    @Published var pendingChatId: String?
    @Published var pendingEmbedId: String?
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
            isRegistered = false
            return granted
        } catch {
            NativeDiagnostics.warning("Notification permission request failed: \(type(of: error))", category: "push_notifications")
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
        NativeDiagnostics.info("APNs device token received", category: "push_notifications")

        Task {
            let publicKey = NotificationPreviewCrypto.loadOrCreatePublicKey()
            var body: [String: Any] = [
                "token": tokenString,
                "platform": "apns",
                "environment": Self.apnsEnvironment,
                "encryption_version": NotificationPreviewCrypto.encryptionVersion,
                "device_id": Self.installationID
            ]
            if let publicKey {
                body["notification_public_key"] = publicKey
            } else {
                NativeDiagnostics.warning("Notification preview key is unavailable", category: "push_notifications")
            }
            do {
                let _: Data = try await APIClient.shared.request(
                    .post,
                    path: "/v1/notifications/register-device",
                    body: body
                )
                try KeychainHelper.save(key: Self.deviceTokenKey, data: Data(tokenString.utf8))
                isRegistered = true
            } catch {
                isRegistered = false
                NativeDiagnostics.warning(
                    "APNs device registration acknowledgement failed: \(type(of: error))",
                    category: "push_notifications"
                )
            }
        }
    }

    func unregisterCurrentDevice() async {
        guard let stored = try? KeychainHelper.load(key: Self.deviceTokenKey),
              let token = String(data: stored, encoding: .utf8),
              !token.isEmpty else {
            isRegistered = false
            return
        }
        do {
            let _: Data = try await APIClient.shared.request(
                .delete,
                path: "/v1/notifications/unregister-device",
                body: ["token": token, "device_id": Self.installationID]
            )
            try KeychainHelper.delete(key: Self.deviceTokenKey)
            isRegistered = false
            #if os(iOS)
            UIApplication.shared.unregisterForRemoteNotifications()
            #elseif os(macOS)
            NSApplication.shared.unregisterForRemoteNotifications()
            #endif
        } catch {
            NativeDiagnostics.warning(
                "APNs device unregister acknowledgement failed: \(type(of: error))",
                category: "push_notifications"
            )
        }
    }

    private static var installationID: String {
        if let stored = try? KeychainHelper.load(key: installationIDKey),
           let existing = String(data: stored, encoding: .utf8),
           !existing.isEmpty {
            return existing
        }
        let created = UUID().uuidString.lowercased()
        do {
            try KeychainHelper.save(key: installationIDKey, data: Data(created.utf8))
        } catch {
            NativeDiagnostics.warning(
                "APNs installation identity persistence failed: \(type(of: error))",
                category: "push_notifications"
            )
        }
        return created
    }

    private static var apnsEnvironment: String {
        #if DEBUG
        "sandbox"
        #else
        "production"
        #endif
    }

    func handleRegistrationError(_ error: Error) {
        NativeDiagnostics.warning("APNs registration failed: \(type(of: error))", category: "push_notifications")
    }

    func setBadgeCount(_ count: Int) {
        #if os(iOS)
        UNUserNotificationCenter.current().setBadgeCount(count) { error in
            if let error {
                NativeDiagnostics.warning("Notification badge update failed: \(type(of: error))", category: "push_notifications")
            }
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
            NativeDiagnostics.warning("Chat notification scheduling failed: \(type(of: error))", category: "push_notifications")
        }
    }

    func showWatchEmbedNotification(chatId: String, embedId: String) async {
        let center = UNUserNotificationCenter.current()
        var settings = await center.notificationSettings()
        if settings.authorizationStatus == .notDetermined {
            _ = try? await center.requestAuthorization(options: [.alert, .sound])
            settings = await center.notificationSettings()
        }
        guard settings.authorizationStatus == .authorized || settings.authorizationStatus == .provisional else {
            return
        }

        let content = UNMutableNotificationContent()
        content.title = AppStrings.openMatesName
        content.body = AppStrings.embedTapToShowDetails
        content.sound = .default
        content.threadIdentifier = chatId
        content.userInfo = ["chat_id": chatId, "embed_id": embedId]

        let request = UNNotificationRequest(
            identifier: "openmates-watch-embed-\(chatId)-\(embedId)-\(UUID().uuidString)",
            content: content,
            trigger: nil
        )

        do {
            try await center.add(request)
        } catch {
            NativeDiagnostics.warning("Watch embed notification scheduling failed: \(type(of: error))", category: "push_notifications")
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
        didReceive response: UNNotificationResponse,
        withCompletionHandler completionHandler: @escaping () -> Void
    ) {
        let userInfo = response.notification.request.content.userInfo
        guard let chatId = (userInfo["chat_id"] as? String) ?? (userInfo["chatId"] as? String) else {
            completionHandler()
            return
        }
        let embedId = (userInfo["embed_id"] as? String) ?? (userInfo["embedId"] as? String)

        let actionIdentifier = response.actionIdentifier
        let replyText = (response as? UNTextInputNotificationResponse)?.userText
        completeNotificationResponseOnMain(
            actionIdentifier: actionIdentifier,
            chatId: chatId,
            embedId: embedId,
            replyText: replyText,
            completion: NotificationCompletionBox(completionHandler)
        )
    }

    private nonisolated func completeNotificationResponseOnMain(
        actionIdentifier: String,
        chatId: String,
        embedId: String?,
        replyText: String?,
        completion: NotificationCompletionBox
    ) {
        if Thread.isMainThread {
            MainActor.assumeIsolated {
                self.handleNotificationResponse(
                    actionIdentifier: actionIdentifier,
                    chatId: chatId,
                    embedId: embedId,
                    replyText: replyText
                )
                completion.complete()
            }
        } else {
            DispatchQueue.main.async {
                MainActor.assumeIsolated {
                    self.handleNotificationResponse(
                        actionIdentifier: actionIdentifier,
                        chatId: chatId,
                        embedId: embedId,
                        replyText: replyText
                    )
                    completion.complete()
                }
            }
        }
    }

    private func handleNotificationResponse(actionIdentifier: String, chatId: String, embedId: String?, replyText: String?) {
        if actionIdentifier == Self.NotificationAction.reply {
            let reply = replyText?.trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
            guard !reply.isEmpty else { return }
            NativeDiagnostics.info("Notification reply action received", category: "push_notifications")
            pendingReplyRequest = NotificationReplyRequest(chatId: chatId, content: reply)
            setBadgeCount(0)
            return
        }

        if actionIdentifier == Self.NotificationAction.openChat ||
            actionIdentifier == UNNotificationDefaultActionIdentifier {
            NativeDiagnostics.info("Notification open action received", category: "push_notifications")
            pendingEmbedId = embedId
            pendingChatId = chatId
            // Clear badge when user taps a notification.
            setBadgeCount(0)
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
