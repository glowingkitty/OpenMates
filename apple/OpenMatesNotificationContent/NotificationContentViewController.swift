// Specification: specifications/features/apple-notifications/specification.yml
// Assertions: apple-notifications.action.direct-reply, apple-notifications.payload.privacy-safe
// Native-only OS notification editor: the notification host owns its header,
// preview, keyboard and sole Send action. No web screen corresponds to this UI.
// UIKit is confined to this OS-owned capability surface.

import UIKit
import UserNotifications
import UserNotificationsUI

// Apple documents delivery on the main thread. The imported ObjC protocol
// predates complete actor annotations; this conformance retains runtime main
// actor checks while every UIKit implementation remains actor isolated.
// https://developer.apple.com/documentation/usernotificationsui/unnotificationcontentextension/didreceive(_:)
final class NotificationContentViewController: UIViewController, @preconcurrency UNNotificationContentExtension {
    private let editor = UITextView()
    private let store = NotificationReplyStore()
    private var target: NotificationReplyTarget?
    private var notification: UNNotification?
    private var protectedDataObserver: NSObjectProtocol?
    private var validationTimer: Timer?

    override func viewDidLoad() {
        super.viewDidLoad()
        view.backgroundColor = .clear
        editor.translatesAutoresizingMaskIntoConstraints = false
        editor.backgroundColor = .clear
        editor.font = .preferredFont(forTextStyle: .body)
        editor.adjustsFontForContentSizeCategory = true
        editor.accessibilityIdentifier = "notification-reply-editor"
        editor.accessibilityLabel = NSLocalizedString("enter_message.placeholder.touch", value: "Tap to ask anything...", comment: "Notification reply editor")
        editor.isHidden = true
        view.addSubview(editor)
        NSLayoutConstraint.activate([
            editor.leadingAnchor.constraint(equalTo: view.layoutMarginsGuide.leadingAnchor),
            editor.trailingAnchor.constraint(equalTo: view.layoutMarginsGuide.trailingAnchor),
            editor.topAnchor.constraint(equalTo: view.topAnchor),
            editor.bottomAnchor.constraint(equalTo: view.bottomAnchor),
        ])
        // Poll only while visible: the app may revoke its registration in another
        // process. Rechecks also run synchronously on receive, visible and Send.
        protectedDataObserver = NotificationCenter.default.addObserver(
            forName: UIApplication.protectedDataWillBecomeUnavailableNotification, object: nil, queue: .main) { [weak self] _ in
                Task { @MainActor [weak self] in self?.recheckVisibleContext() }
            }
    }

    func didReceive(_ notification: UNNotification) {
        loadViewIfNeeded()
        self.notification = notification
        target = loadTarget(notification)
        editor.text = ""
        applyEligibility()
        if viewIfLoaded?.window != nil { recheckVisibleContext(focus: true) }
    }

    override func viewDidAppear(_ animated: Bool) {
        super.viewDidAppear(animated)
        recheckVisibleContext(focus: true)
        validationTimer?.invalidate()
        validationTimer = Timer.scheduledTimer(withTimeInterval: 0.5, repeats: true) { [weak self] _ in
            Task { @MainActor [weak self] in self?.recheckVisibleContext() }
        }
    }

    override func viewDidDisappear(_ animated: Bool) {
        super.viewDidDisappear(animated)
        validationTimer?.invalidate(); validationTimer = nil
        editor.resignFirstResponder()
        editor.text = ""
    }

    private func loadTarget(_ notification: UNNotification) -> NotificationReplyTarget? {
        let request = notification.request
        guard request.content.categoryIdentifier == "OPENMATES_CHAT_MESSAGE",
              request.content.userInfo["type"] as? String != "workflow.run_completed",
              let digest = NotificationReplyStore.payloadDigest(userInfo: request.content.userInfo) else { return nil }
        return try? store.validatedTarget(requestID: request.identifier, payloadDigest: digest)
    }

    private func applyEligibility() {
        let allowed = target != nil
        editor.isHidden = !allowed
        editor.isEditable = allowed
        preferredContentSize = CGSize(width: view.bounds.width, height: allowed ? 120 : 0)
        // The extension handles every action in its category. Invalid/legacy or
        // locked contexts retain the generic system notification without actions.
        extensionContext?.notificationActions = allowed ? [UNNotificationAction(
            identifier: "OPENMATES_REPLY",
            title: NSLocalizedString("enter_message.send", value: "Send", comment: "Send notification reply"),
            options: [.authenticationRequired])] : []
        if !allowed { editor.resignFirstResponder(); editor.text = "" }
    }

    private func recheckVisibleContext(focus: Bool = false) {
        guard let notification else { return }
        let current = loadTarget(notification)
        let changed = current != target
        if changed {
            // Locking/revocation discards typed text. Unlocking may restore only
            // this retained OS request's exact validated record, with a fresh
            // unlocked marker; never carry a draft into a changed binding.
            editor.text = ""
            target = current
            applyEligibility()
        }
        guard current != nil else { applyEligibility(); return }
        if (focus || changed), viewIfLoaded?.window != nil {
            editor.becomeFirstResponder()
        }
    }

    func didReceive(_ response: UNNotificationResponse,
                    completionHandler completion: @escaping (UNNotificationContentExtensionResponseOption) -> Void) {
        // Only the actual explicit Send callback can snapshot an editor. No
        // fabricated text-input responses or foreground-open shortcuts are used.
        guard response.actionIdentifier == "OPENMATES_REPLY", let target,
              response.notification.request.identifier == target.requestID,
              loadTarget(response.notification) == target else {
            completion(.doNotDismiss); return
        }
        do {
            _ = try store.submit(target, content: editor.text ?? "")
            editor.resignFirstResponder()
            completion(.dismissAndForwardAction)
        } catch {
            recheckVisibleContext()
            completion(.doNotDismiss)
        }
    }

    // iOS 26.2 deployment includes the Swift runtime support for isolated
    // destruction. Timer/token cleanup stays on this controller's main actor.
    isolated deinit {
        validationTimer?.invalidate()
        if let protectedDataObserver { NotificationCenter.default.removeObserver(protectedDataObserver) }
    }
}
