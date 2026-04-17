// APNs push notification registration and handling.
// Registers device token with backend, handles notification categories,
// and routes taps to the appropriate chat.

import Foundation
import UserNotifications
import SwiftUI

@MainActor
final class PushNotificationManager: NSObject, ObservableObject {
    static let shared = PushNotificationManager()

    @Published var isRegistered = false
    @Published var pendingChatId: String?

    override private init() {
        super.init()
    }

    func requestPermission() async -> Bool {
        let center = UNUserNotificationCenter.current()
        center.delegate = self

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
            try? await APIClient.shared.request(
                .post,
                path: "/v1/notifications/register-device",
                body: ["token": tokenString, "platform": "apns"]
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
        if let chatId = userInfo["chat_id"] as? String {
            await MainActor.run {
                pendingChatId = chatId
            }
        }
    }
}
