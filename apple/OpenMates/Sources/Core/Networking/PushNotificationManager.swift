// APNs push notification registration and handling.
// Registers device token with backend, handles notification categories,
// and routes taps to the appropriate chat.

import Foundation
import CryptoKit
import Combine
import UserNotifications
import SwiftUI

// The OS may suspend the app after its response completion handler returns.
// Store replies and exact prepared turns in Keychain before acknowledging them.
struct NotificationPreparedTurn: Codable, Equatable {
    let turnId: String
    let preflight: Data
    let outbound: Data

    init(turnId: String, preflight: [String: Any], outbound: [String: Any]) throws {
        self.turnId = turnId
        self.preflight = try JSONSerialization.data(withJSONObject: preflight)
        self.outbound = try JSONSerialization.data(withJSONObject: outbound)
    }

    func payloads() throws -> (preflight: [String: Any], outbound: [String: Any]) {
        guard let preflight = try JSONSerialization.jsonObject(with: preflight) as? [String: Any],
              let outbound = try JSONSerialization.jsonObject(with: outbound) as? [String: Any] else {
            throw NotificationReplyError.invalidPreparedTurn
        }
        return (preflight, outbound)
    }
}

enum NotificationReplyError: Error {
    case invalidPreparedTurn, accountChanged, chatUnavailable
}

struct NotificationReplyRequest: Identifiable, Equatable, Codable {
    let id: String
    let chatId: String
    let content: String
    let accountId: String
    let serverURL: String
    var preparedTurn: NotificationPreparedTurn?

    init(id: String = UUID().uuidString, chatId: String, content: String,
         accountId: String, serverURL: String) {
        self.id = id
        self.chatId = chatId
        self.content = content
        self.accountId = accountId
        self.serverURL = serverURL
    }
}

struct NotificationReplyLedger: Codable {
    var pending: [NotificationReplyRequest] = []
    var completedIds: [String] = []

    mutating func enqueue(_ request: NotificationReplyRequest) {
        guard !completedIds.contains(request.id), !pending.contains(where: { $0.id == request.id }) else { return }
        pending.append(request)
    }

    func requests(accountId: String, serverURL: String) -> [NotificationReplyRequest] {
        pending.filter { $0.accountId == accountId && $0.serverURL == serverURL }
    }

    mutating func complete(_ id: String) {
        pending.removeAll { $0.id == id }
        if !completedIds.contains(id) { completedIds.append(id) }
        completedIds = Array(completedIds.suffix(128))
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
    @Published private(set) var replyQueueRevision = 0
    private static let replyLedgerKey = "openmates.notification.replyLedger.v1"
    private var completedReplyIds = Set<String>()
    private var isSendingReplies = false
    private var connectionObserver: AnyCancellable?

    private func replyLedger() throws -> NotificationReplyLedger {
        guard let data = try KeychainHelper.load(key: Self.replyLedgerKey) else { return NotificationReplyLedger() }
        return try JSONDecoder().decode(NotificationReplyLedger.self, from: data)
    }

    private func saveReplyLedger(_ ledger: NotificationReplyLedger) throws {
        try KeychainHelper.save(key: Self.replyLedgerKey, data: JSONEncoder().encode(ledger))
        completedReplyIds = Set(ledger.completedIds)
        replyQueueRevision += 1
    }

    func pendingReplies(accountId: String) throws -> [NotificationReplyRequest] {
        try replyLedger().requests(accountId: accountId, serverURL: ServerConfiguration.current.apiBaseURL.absoluteString)
    }

    func enqueueReply(_ request: NotificationReplyRequest) throws {
        var ledger = try replyLedger()
        ledger.enqueue(request)
        try saveReplyLedger(ledger)
    }

    func prepareReply(_ id: String, turn: NotificationPreparedTurn) throws {
        var ledger = try replyLedger()
        guard let index = ledger.pending.firstIndex(where: { $0.id == id }) else { throw NotificationReplyError.chatUnavailable }
        ledger.pending[index].preparedTurn = turn
        try saveReplyLedger(ledger)
    }

    func completeReply(_ id: String) throws {
        var ledger = try replyLedger()
        ledger.complete(id)
        try saveReplyLedger(ledger)
    }

    /// Resolve a notification target beyond the initial sidebar metadata page.
    func chatForNotification(_ chatId: String) async throws -> Chat {
        let authManager = AuthManager.notificationSession
        let accountId = authManager.currentUser?.id
        let server = ServerConfiguration.current.apiBaseURL
        let scope = OfflineStore.shared.scopeGeneration
        func validate() throws {
            guard authManager.state == .authenticated, accountId != nil,
                  authManager.currentUser?.id == accountId,
                  ServerConfiguration.current.apiBaseURL == server,
                  OfflineStore.shared.scopeGeneration == scope else { throw NotificationReplyError.accountChanged }
        }
        try validate()
        let chatStore = AppSessionCoordinator.shared.chatStore
        let wsManager = AppSessionCoordinator.shared.webSocketManager
        let syncDecoder = JSONDecoder()
        syncDecoder.keyDecodingStrategy = .convertFromSnakeCase
        var chat = chatStore.chat(for: chatId)
            ?? OfflineStore.shared.loadChats().first(where: { $0.id == chatId })
        var offset = 0
        while chat == nil {
            let pageOffset = offset
            let response = try await wsManager.sendAndWait(
                WSOutboundMessage(type: "load_more_chats", payload: ["offset": pageOffset, "limit": 50, "context_epoch": 0]),
                responseType: "load_more_chats_response",
                matching: { ($0["offset"] as? Int) == pageOffset })
            try validate()
            let page = try syncDecoder.decode(ChatMetadataPage.self,
                from: JSONSerialization.data(withJSONObject: response.fields))
            guard page.error == nil else { throw NotificationReplyError.chatUnavailable }
            let items = page.chats ?? []
            chat = items.compactMap(\.chatDetails).first(where: { $0.id == chatId })
            offset = page.offset + items.count
            if page.hasMore != true || items.isEmpty { break }
        }
        try validate()
        guard let target = chat, target.id == chatId,
              !target.id.hasPrefix("incognito-") else {
            throw NotificationReplyError.chatUnavailable
        }
        chatStore.upsertChat(target)
        return target
    }

    private func sendNotificationReply(_ request: NotificationReplyRequest, authManager: AuthManager) async throws {
        let runtime = AppSessionCoordinator.shared
        let chatStore = runtime.chatStore
        let wsManager = runtime.webSocketManager
        let transportGeneration = wsManager.transportGeneration
        let scope = OfflineStore.shared.scopeGeneration
        func requireCurrentAccount() throws {
            guard authManager.state == .authenticated, authManager.currentUser?.id == request.accountId,
                  request.serverURL == ServerConfiguration.current.apiBaseURL.absoluteString,
                  scope == OfflineStore.shared.scopeGeneration,
                  transportGeneration == wsManager.transportGeneration else { throw NotificationReplyError.accountChanged }
        }
        try requireCurrentAccount()
        let pipeline = ChatSendPipeline()
        if let prepared = request.preparedTurn {
            let payloads = try prepared.payloads()
            try await pipeline.sendSavedChatTurn(turnId: prepared.turnId,
                preflightPayload: payloads.preflight, outboundPayload: payloads.outbound, transport: wsManager, waitForInferenceReceipt: true, validateRemoteSend: requireCurrentAccount)
            try requireCurrentAccount()
            try completeReply(request.id)
            return
        }

        // Notification replies can target chats outside the initial metadata
        // window. Resolve that exact chat and its complete encrypted history;
        // never substitute the active chat or an empty history after cold launch.
        let target = try await chatForNotification(request.chatId)
        try requireCurrentAccount()
        let response = try await wsManager.requestChatContentBatch(chatId: target.id)
        try requireCurrentAccount()
        let batch = try ChatContentBatchPayload.decode(response.fields)
        if let masterKey = try await CryptoManager.shared.loadMasterKey(for: request.accountId) {
            await ChatKeyManager.shared.loadChatKey(chatId: target.id, wrappers: batch.chatKeyWrappers, masterKey: masterKey)
        }
        try requireCurrentAccount()
        let cached = ChatContentBatchPayload.mergedMessages(
            snapshot: OfflineStore.shared.loadMessages(chatId: target.id),
            preserving: chatStore.messages(for: target.id))
        let history = ChatContentBatchPayload.mergedMessages(
            snapshot: try batch.messages(for: target.id), preserving: cached)
        chatStore.upsertChat(target)
        chatStore.advanceMessagesVersion(chatId: target.id, to: batch.messagesVersion(for: target.id) ?? 0)
        chatStore.applySyncedContent(messagesByChat: [target.id: history], embedsByChat: [:])
        try requireCurrentAccount()
        guard let resolved = chatStore.chat(for: target.id) else { throw NotificationReplyError.chatUnavailable }
        _ = try await pipeline.sendUserMessage(content: request.content, in: resolved,
            existingMessages: history, wsManager: wsManager, chatStore: chatStore, activateChat: false, waitForInferenceReceipt: true,
            beforeRemoteSend: { turnId, preflight, outbound in
                try requireCurrentAccount()
                try self.prepareReply(request.id, turn: NotificationPreparedTurn(
                    turnId: turnId, preflight: preflight, outbound: outbound))
            }, validateRemoteSend: requireCurrentAccount)
        try requireCurrentAccount()
        try completeReply(request.id)
        NativeDiagnostics.info("Notification reply forwarded to chat processing", category: "push_notifications")
    }

    /// One app-scoped drain also runs when no product window is mounted.
    func flushQueuedReplies() async {
        guard !isSendingReplies, let accountId = AuthManager.notificationAccountId else { return }
        isSendingReplies = true
        defer { isSendingReplies = false }
        do {
            guard try !pendingReplies(accountId: accountId).isEmpty else { return }
            let authManager = AuthManager.notificationSession
            if authManager.state == .initializing { await authManager.checkSession() }
            guard authManager.state == .authenticated, authManager.currentUser?.id == accountId else { return }
            let runtime = AppSessionCoordinator.shared
            _ = runtime.prepareAuthenticatedRuntime(lastOpenedChatId: authManager.currentUser?.lastOpened)
            let socket = runtime.webSocketManager
            if socket.connectionState != .connected {
                if authManager.webSocketToken == nil { await authManager.validateSessionAfterOfflineBootstrap() }
                guard authManager.state == .authenticated, authManager.currentUser?.id == accountId else { return }
                socket.connect(sessionId: AuthManager.nativeSessionId, token: authManager.webSocketToken,
                               syncState: runtime.chatStore.makeSyncClientState(clientSuggestionsCount: 0))
                let deadline = Date().addingTimeInterval(10)
                while socket.connectionState != .connected, Date() < deadline, !Task.isCancelled {
                    try await Task.sleep(for: .milliseconds(100))
                }
            }
            guard socket.connectionState == .connected else { return }
            var attempted = Set<String>()
            var failedChats = Set<String>()
            while let reply = try pendingReplies(accountId: accountId).first(where: {
                !attempted.contains($0.id) && !failedChats.contains($0.chatId)
            }) {
                attempted.insert(reply.id)
                do {
                    try await sendNotificationReply(reply, authManager: authManager)
                } catch {
                    failedChats.insert(reply.chatId)
                    NativeDiagnostics.warning("Notification reply remains queued: \(type(of: error))", category: "push_notifications")
                }
            }
        } catch {
            NativeDiagnostics.warning("Notification reply queue unavailable: \(type(of: error))", category: "push_notifications")
        }
    }

    override private init() {
        super.init()
        configureForLaunch()
    }

    func configureForLaunch() {
        let center = UNUserNotificationCenter.current()
        center.delegate = self
        configureChatMessageCategory(center: center)
        if connectionObserver == nil {
            connectionObserver = AppSessionCoordinator.shared.webSocketManager.$connectionState
                .removeDuplicates()
                .sink { [weak self] state in
                    guard state == .connected else { return }
                    Task { @MainActor in await self?.flushQueuedReplies() }
                }
        }
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
        let failure = error as NSError
        NativeDiagnostics.warning("APNs registration failed: domain=\(failure.domain) code=\(failure.code)", category: "push_notifications")
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
        let notificationId = response.notification.request.identifier
        let completion = NotificationCompletionBox(completionHandler)
        Task { @MainActor in
            defer { completion.complete() }
            if actionIdentifier == Self.NotificationAction.reply {
                let reply = replyText?.trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
                guard !reply.isEmpty, let accountId = AuthManager.notificationAccountId else {
                    NativeDiagnostics.warning("Notification reply requires an account session", category: "push_notifications")
                    return
                }
                let identity = accountId + "\n" + ServerConfiguration.current.apiBaseURL.absoluteString + "\n" + notificationId + "\n" + chatId + "\n" + reply
                let id = SHA256.hash(data: Data(identity.utf8)).map { String(format: "%02x", $0) }.joined()
                do {
                    try enqueueReply(NotificationReplyRequest(id: id, chatId: chatId, content: reply,
                        accountId: accountId, serverURL: ServerConfiguration.current.apiBaseURL.absoluteString))
                    NativeDiagnostics.info("Notification reply saved for delivery", category: "push_notifications")
                    Task { @MainActor in await self.flushQueuedReplies() }
                    // Allow normal session bootstrap/send to finish while the OS
                    // grants execution time. An offline reply remains protected
                    // in Keychain and is replayed on reconnect or the next launch.
                    let deadline = Date().addingTimeInterval(15)
                    while !completedReplyIds.contains(id), Date() < deadline, !Task.isCancelled {
                        try? await Task.sleep(for: .milliseconds(250))
                    }
                    setBadgeCount(0)
                } catch {
                    NativeDiagnostics.warning("Notification reply persistence failed: \(type(of: error))", category: "push_notifications")
                }
            } else {
                handleNotificationResponse(actionIdentifier: actionIdentifier, chatId: chatId, embedId: embedId)
            }
        }
    }

    private func handleNotificationResponse(actionIdentifier: String, chatId: String, embedId: String?) {
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
