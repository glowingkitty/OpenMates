// Notification Service Extension for private APNs previews.
// APNs receives only safe fallback alert text from the backend.
// This extension decrypts optional device-targeted preview ciphertext from the
// payload and replaces the visible body locally before the notification is shown.
// If decryption fails, the safe fallback body remains unchanged.

import UserNotifications

final class NotificationService: UNNotificationServiceExtension {
    private var contentHandler: ((UNNotificationContent) -> Void)?
    private var bestAttemptContent: UNMutableNotificationContent?

    override func didReceive(
        _ request: UNNotificationRequest,
        withContentHandler contentHandler: @escaping (UNNotificationContent) -> Void
    ) {
        self.contentHandler = contentHandler

        guard let bestAttemptContent = request.content.mutableCopy() as? UNMutableNotificationContent else {
            contentHandler(request.content)
            return
        }

        self.bestAttemptContent = bestAttemptContent
        if let preview = NotificationPreviewCrypto.decryptPreview(userInfo: request.content.userInfo) {
            bestAttemptContent.body = preview
        }
        contentHandler(bestAttemptContent)
    }

    override func serviceExtensionTimeWillExpire() {
        if let contentHandler, let bestAttemptContent {
            contentHandler(bestAttemptContent)
        }
    }
}
