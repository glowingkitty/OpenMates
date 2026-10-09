// APNs push notification registration and handling.
// Registers device token with backend, handles notification categories,
// and routes taps to the appropriate chat.
// Specification: specifications/features/apple-watch/specification.yml
// Assertions: apple-watch.handoff.exact-private
// Specification: specifications/features/apple-notifications/specification.yml
// Assertions: apple-notifications.registration.lifecycle, apple-notifications.action.routing-coherent

import Foundation
import CryptoKit
import Combine
import UserNotifications
import SwiftUI

struct PushRegistrationContext: Equatable {
    let accountID: String
    let profile: ServerProfile
    let scope: UUID
    let authorityGeneration: UUID?

    init(accountID: String, profile: ServerProfile, scope: UUID, authorityGeneration: UUID? = nil) {
        self.accountID = accountID; self.profile = profile; self.scope = scope
        self.authorityGeneration = authorityGeneration
    }
}

/// A tap asks for a fresh bounded read even when the destination is already open.
/// It survives reconnects, but never crosses account, server, Team or deletion.
struct ChatNotificationCatchUpIntent {
    let id: UUID
    let chatID: String
    let messageID: String?
    let accountHint: String?
    let server: ServerProfile
    var context: Context?

    struct Context {
        let accountID: String
        let scope: UUID
        let team: TeamWorkspaceSnapshot
        let deletion: Int
    }

    @MainActor init(chatID: String, messageID: String?) {
        id = UUID(); self.chatID = chatID; self.messageID = messageID
        accountHint = AuthManager.notificationAccountId
        server = ServerProfile.current()
    }

    /// Cold-launch taps bind once the existing session/Team has restored. A
    /// bound intent never rebinds to a different account or workspace.
    @MainActor mutating func bindIfReady() {
        guard context == nil, server == ServerProfile.current(),
              AuthManager.notificationSession.hasNetworkAuthority,
              let accountID = AuthManager.notificationAccountId,
              accountHint == nil || accountHint == accountID else { return }
        let team = TeamWorkspaceContext.shared.snapshot
        let scope = OfflineStore.shared.scopeGeneration
        guard team.accountID == accountID, team.server == server, team.scope == scope else { return }
        context = Context(accountID: accountID, scope: scope, team: team,
            deletion: OfflineStore.shared.chatDeletionVersion(chatID))
    }

    @MainActor var isCurrent: Bool {
        guard let context else { return false }
        let current = TeamWorkspaceContext.shared.snapshot
        return context.accountID == AuthManager.notificationAccountId && server == ServerProfile.current()
            && context.scope == OfflineStore.shared.scopeGeneration && context.team.epoch == current.epoch
            && context.team.teamID == current.teamID && context.team.accountID == current.accountID
            && context.team.server == current.server && context.team.scope == current.scope
            && context.deletion == OfflineStore.shared.chatDeletionVersion(chatID)
    }
}

enum PushCompletionNoticePolicy {
    static func permits(expected: PushRegistrationContext, current: PushRegistrationContext?, notificationsEnabled: Bool) -> Bool {
        notificationsEnabled && expected == current
    }
    static func receiptID(context: PushRegistrationContext, chatID: String, messageID: String) -> String {
        let fields = [context.accountID, context.profile.apiBaseURL.absoluteString, chatID, messageID]
        let data = (try? JSONEncoder().encode(fields)) ?? Data()
        return "openmates-chat-completion-" + SHA256.hash(data: data).map { String(format: "%02x", $0) }.joined()
    }
}

/// Only exact acknowledged messages may dismiss cards. Legacy chat-only and
/// unscoped cards remain because their recipient/workspace cannot be proven.
enum PushReadCardPolicy {
    static let scopeKey = "openmates_read_scope"

    static func scopeID(accountID: String, profile: ServerProfile, teamID: String?) -> String {
        let fields = [accountID, profile.apiBaseURL.absoluteString, teamID ?? ""]
        let data = (try? JSONEncoder().encode(fields)) ?? Data()
        return SHA256.hash(data: data).map { String(format: "%02x", $0) }.joined()
    }

    static func matches(userInfo: [AnyHashable: Any], scopeID: String, chatID: String,
                        messageIDs: Set<String>) -> Bool {
        guard !messageIDs.isEmpty,
              userInfo[scopeKey] as? String == scopeID,
              userInfo["chat_id"] as? String == chatID,
              let messageID = userInfo["message_id"] as? String else { return false }
        return messageIDs.contains(messageID)
    }
}

/// One installation token, fenced by the verified account and server. Transient
/// failures retry within a bounded burst; the next online transition can resume.
@MainActor
final class PushDeviceRegistration {
    private let context: () -> PushRegistrationContext?
    private let register: @MainActor (String, PushRegistrationContext) async throws -> Void
    private let sleep: @MainActor (Duration) async throws -> Void
    private let acknowledge: (Bool) -> Void
    private let retryDelays: [Duration]
    private var task: Task<Void, Never>?
    private var generation = UUID()
    private var activeContext: PushRegistrationContext?
    private var activeToken: String?
    private var acknowledged = false
    private var exhausted = false

    init(context: @escaping () -> PushRegistrationContext?,
         register: @escaping @MainActor (String, PushRegistrationContext) async throws -> Void,
         sleep: (@MainActor (Duration) async throws -> Void)?,
         retryDelays: [Duration],
         acknowledge: @escaping (Bool) -> Void) {
        self.context = context
        self.register = register
        self.sleep = sleep ?? { delay in try await Task.sleep(for: delay) }
        self.retryDelays = retryDelays
        self.acknowledge = acknowledge
    }

    func invalidate() {
        generation = UUID()
        task?.cancel()
        task = nil
        activeContext = nil
        activeToken = nil
        acknowledged = false
        exhausted = false
        acknowledge(false)
    }

    func refresh(token: String) {
        guard !token.isEmpty, let captured = context() else {
            invalidate()
            return
        }
        if captured == activeContext, token == activeToken {
            guard task == nil, !acknowledged, !exhausted else { return }
        } else {
            invalidate()
            activeContext = captured
            activeToken = token
        }
        let capturedGeneration = generation
        task = Task { [weak self] in
            guard let self else { return }
            defer { if self.generation == capturedGeneration { self.task = nil } }
            for attempt in 0...self.retryDelays.count {
                guard !Task.isCancelled, self.generation == capturedGeneration,
                      self.context() == captured else { return }
                do {
                    try await self.register(token, captured)
                    guard !Task.isCancelled, self.generation == capturedGeneration,
                          self.context() == captured else { return }
                    self.acknowledged = true
                    self.acknowledge(true)
                    return
                } catch {
                    guard !Task.isCancelled, self.generation == capturedGeneration,
                          self.context() == captured else { return }
                    self.acknowledge(false)
                    NativeDiagnostics.warning("APNs device registration acknowledgement failed: \(type(of: error))",
                                              category: "push_notifications")
                }
                guard attempt < self.retryDelays.count else { self.exhausted = true; return }
                do { try await self.sleep(self.retryDelays[attempt]) } catch { return }
            }
        }
    }
}

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
    @Published private(set) var completionCatchUpIntent: ChatNotificationCatchUpIntent?

    func completionCatchUpIntent(for chatID: String) -> ChatNotificationCatchUpIntent? {
        guard var intent = completionCatchUpIntent, intent.chatID == chatID else { return nil }
        if intent.context == nil {
            intent.bindIfReady()
            if intent.context != nil { completionCatchUpIntent = intent }
        }
        return intent
    }

    func finishCompletionCatchUp(_ id: UUID) {
        if completionCatchUpIntent?.id == id { completionCatchUpIntent = nil }
    }
    @Published var pendingEmbedId: String?
    @Published private(set) var replyQueueRevision = 0
    private static let replyLedgerKey = "openmates.notification.replyLedger.v1"
    private var completedReplyIds = Set<String>()
    private var isSendingReplies = false
    private var connectionObserver: AnyCancellable?
    private var badgeActivationObserver: AnyCancellable?
    private var registrationAuthObserver: AnyCancellable?
    private weak var registrationAuthSession: AuthManager?
    private var permissionAuthorized = false
    private var installationToken: String?
    private var preferenceRefreshTask: Task<Void, Never>?
    private var preferenceRefreshContext: PushRegistrationContext?
    private var schedulingCompletionReceipts: Set<String> = []
    private static let completionNoticeLedgerKey = "openmates.chat-completion-notices.v1"
    private lazy var deviceRegistration = makeDeviceRegistration()
    private func makeDeviceRegistration() -> PushDeviceRegistration {
        PushDeviceRegistration(
        context: { [weak self] in self?.registrationContext() },
        register: { token, context in
            let publicKey = NotificationPreviewCrypto.loadOrCreatePublicKey()
            var body: [String: Any] = [
                "token": token, "platform": "apns", "environment": Self.apnsEnvironment,
                "encryption_version": NotificationPreviewCrypto.encryptionVersion,
                "device_id": Self.installationID
            ]
            body["alerts_enabled"] = PushNotificationManager.shared.permissionAuthorized
                && AuthManager.notificationSession.currentUser?.pushNotificationEnabled != false
            if let publicKey { body["notification_public_key"] = publicKey }
            else { NativeDiagnostics.warning("Notification preview key is unavailable", category: "push_notifications") }
            let _: Data = try await APIClient.shared.request(.post,
                path: "/v1/notifications/register-device", serverProfile: context.profile, body: body,
                expectedAccountID: context.accountID, expectedScope: context.scope)
        }, sleep: nil, retryDelays: [.seconds(1), .seconds(4), .seconds(16)],
        acknowledge: { [weak self] registered in
            guard let self else { return }
            self.isRegistered = registered
            if registered { self.refreshAuthoritativePreferenceAfterRegistration() }
            NativeDiagnostics.event("push_registration_ack", category: "push_notifications", flags: ["acknowledged": registered])
        })
    }

    private func registrationContext() -> PushRegistrationContext? {
        let auth = AuthManager.notificationSession
        guard permissionAuthorized, auth.state == .authenticated,
              auth.hasNetworkAuthority,
              let account = auth.currentUser?.id else { return nil }
        return PushRegistrationContext(accountID: account, profile: ServerProfile.current(),
                                       scope: OfflineStore.shared.scopeGeneration,
                                       authorityGeneration: auth.networkAuthority?.generation)
    }

    func invalidateRegistration() {
        deviceRegistration.invalidate()
        if preferenceRefreshContext != currentAuthenticatedNoticeContext() {
            preferenceRefreshTask?.cancel(); preferenceRefreshTask = nil
            preferenceRefreshContext = nil
        }
    }

    private func currentAuthenticatedNoticeContext() -> PushRegistrationContext? {
        let auth = AuthManager.notificationSession
        guard auth.hasNetworkAuthority, let accountID = auth.currentUser?.id else { return nil }
        return .init(accountID: accountID, profile: ServerProfile.current(), scope: OfflineStore.shared.scopeGeneration,
                     authorityGeneration: auth.networkAuthority?.generation)
    }

    private func refreshAuthoritativePreferenceAfterRegistration() {
        guard let context = registrationContext(), preferenceRefreshContext != context else { return }
        // One coalesced authoritative read per verified registration context.
        // OS permission alone never creates an account notification preference.
        preferenceRefreshContext = context
        guard AuthManager.notificationSession.currentUser?.pushNotificationEnabled != true else { return }
        preferenceRefreshTask?.cancel()
        preferenceRefreshTask = Task { [weak self] in
            guard let self else { return }
            defer { if self.preferenceRefreshContext == context { self.preferenceRefreshTask = nil } }
            do {
                let response: SessionResponse = try await APIClient.shared.request(.get, path: "/v1/auth/session",
                    serverProfile: context.profile, expectedAccountID: context.accountID, expectedScope: context.scope)
                guard !Task.isCancelled, self.preferenceRefreshContext == context,
                      self.currentAuthenticatedNoticeContext() == context, response.success, let user = response.user else { return }
                AuthManager.notificationSession.applyAuthoritativePushNotificationPreference(user,
                    accountID: context.accountID, profile: context.profile, scope: context.scope)
                NativeDiagnostics.event("push_preference_profile_refreshed", category: "push_notifications",
                    flags: ["enabled": user.pushNotificationEnabled == true])
            } catch {
                guard !Task.isCancelled else { return }
                NativeDiagnostics.event("push_preference_profile_refresh_failed", category: "push_notifications", level: .warning)
            }
        }
    }

    /// Refresh permissions after returning from OS Settings; keep diagnostic
    /// output to state flags and never print installation tokens or identities.
    func refreshAuthorizationAndRegistration() async {
        let settings = await UNUserNotificationCenter.current().notificationSettings()
        permissionAuthorized = settings.authorizationStatus == .authorized || settings.authorizationStatus == .provisional
        if permissionAuthorized {
            refreshRegistration()
            if currentAuthenticatedNoticeContext() != nil { await registerForRemoteNotifications() }
        } else { invalidateRegistration() }
        let auth = AuthManager.notificationSession
        let stored = try? KeychainHelper.load(key: Self.deviceTokenKey)
        NativeDiagnostics.event("push_registration_state", category: "push_notifications", flags: [
            "permission": permissionAuthorized, "token_present": installationToken != nil || stored != nil,
            "server_ack": isRegistered, "notifications_opt_in": auth.currentUser?.pushNotificationEnabled == true,
            "online_session": auth.sessionValidationState == .onlineAuthenticated,
            "socket_connected": AppSessionCoordinator.shared.webSocketManager.connectionState == .connected,
            "production_environment": Self.apnsEnvironment == "production"
        ], counts: ["authorization": settings.authorizationStatus.rawValue])
    }

    func refreshRegistration() {
        observeRegistrationAuthentication()
        let stored = try? KeychainHelper.load(key: Self.deviceTokenKey)
        guard let token = installationToken ?? stored.flatMap({ String(data: $0, encoding: .utf8) }) else { return }
        deviceRegistration.refresh(token: token)
    }

    private func observeRegistrationAuthentication() {
        let auth = AuthManager.notificationSession
        guard registrationAuthSession !== auth else { return }
        registrationAuthSession = auth
        let accountIDs = auth.$currentUser.map { user -> String? in user?.id }
        let contexts = Publishers.CombineLatest3(auth.$state, auth.$networkAuthority, accountIDs)
        registrationAuthObserver = contexts
            .removeDuplicates { previous, current in
                previous.0 == current.0 && previous.1 == current.1 && previous.2 == current.2
            }
            .sink { [weak self] _ in
                // Published values are emitted before assignment. Read the
                // complete verified context on the following actor turn.
                Task { @MainActor in self?.refreshRegistration() }
            }
    }

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
            guard authManager.hasNetworkAuthority, accountId != nil,
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
            guard authManager.hasNetworkAuthority, authManager.currentUser?.id == request.accountId,
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
            if !authManager.hasNetworkAuthority { await authManager.validateSessionAfterOfflineBootstrap() }
            guard authManager.hasNetworkAuthority else { return }
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
        #if DEBUG
        // Component preview processes never register devices or drain real replies.
        guard DevPreviewLaunchConfiguration.current == nil else { return }
        #endif
        let center = UNUserNotificationCenter.current()
        center.delegate = self
        configureChatMessageCategory(center: center)
        if connectionObserver == nil {
            connectionObserver = AppSessionCoordinator.shared.webSocketManager.$connectionState
                .removeDuplicates()
                .sink { [weak self] state in
                    Task { @MainActor in
                        guard let self else { return }
                        if state == .connected {
                            self.refreshRegistration()
                            await self.flushQueuedReplies()
                        } else { self.refreshRegistration() }
                    }
                }
        }
        observeBadgeActivation()
        observeRegistrationAuthentication()
        Task { @MainActor in
            let settings = await center.notificationSettings()
            permissionAuthorized = settings.authorizationStatus == .authorized || settings.authorizationStatus == .provisional
            refreshRegistration()
            if permissionAuthorized, currentAuthenticatedNoticeContext() != nil {
                await registerForRemoteNotifications()
            }
        }
    }

    private func observeBadgeActivation() {
        #if os(iOS)
        guard badgeActivationObserver == nil else { return }
        badgeActivationObserver = NotificationCenter.default.publisher(for: UIApplication.didBecomeActiveNotification)
            .sink { _ in
                Task { @MainActor in UnreadMessagesStore.shared.resynchronizeBadge() }
            }
        #endif
    }

    func requestPermission() async -> Bool {
        let center = UNUserNotificationCenter.current()
        center.delegate = self
        configureChatMessageCategory(center: center)

        do {
            let granted = try await center.requestAuthorization(options: [.alert, .badge, .sound])
            permissionAuthorized = granted
            if granted {
                refreshRegistration()
                await registerForRemoteNotifications()
            } else { invalidateRegistration() }
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

        installationToken = tokenString
        do { try KeychainHelper.save(key: Self.deviceTokenKey, data: Data(tokenString.utf8)) }
        catch { NativeDiagnostics.warning("APNs installation token persistence failed: \(type(of: error))", category: "push_notifications") }
        refreshRegistration()
    }

    func unregisterCurrentDevice() async {
        invalidateRegistration()
        permissionAuthorized = false
        let auth = AuthManager.notificationSession
        let accountID = auth.currentUser?.id
        let profile = ServerProfile.current()
        let scope = OfflineStore.shared.scopeGeneration
        guard let stored = try? KeychainHelper.load(key: Self.deviceTokenKey),
              let token = String(data: stored, encoding: .utf8),
              !token.isEmpty, let accountID, auth.state == .authenticated else {
            isRegistered = false
            return
        }
        do {
            let _: Data = try await APIClient.shared.request(
                .delete,
                path: "/v1/notifications/unregister-device",
                serverProfile: profile,
                body: ["token": token, "device_id": Self.installationID],
                expectedAccountID: accountID, expectedScope: scope
            )
            guard auth.currentUser?.id == accountID, ServerProfile.current() == profile,
                  OfflineStore.shared.scopeGeneration == scope, installationToken == nil || installationToken == token else { return }
            try KeychainHelper.delete(key: Self.deviceTokenKey)
            installationToken = nil
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

    func showChatMessageNotification(chatId: String, messageID: String? = nil) async {
        guard !chatId.isEmpty, let captured = currentAuthenticatedNoticeContext(),
              PushCompletionNoticePolicy.permits(expected: captured, current: currentAuthenticatedNoticeContext(),
                  notificationsEnabled: AuthManager.notificationSession.currentUser?.pushNotificationEnabled == true) else { return }
        let noticeChat = AppSessionCoordinator.shared.chatStore.chat(for: chatId) ?? OfflineStore.shared.loadChat(id: chatId)
        let readScope = noticeChat.map { PushReadCardPolicy.scopeID(accountID: captured.accountID,
            profile: captured.profile, teamID: $0.teamId) }
        let identifier = PushCompletionNoticePolicy.receiptID(context: captured, chatID: chatId, messageID: messageID ?? UUID().uuidString)
        let ledger = UserDefaults.standard.stringArray(forKey: Self.completionNoticeLedgerKey) ?? []
        guard !ledger.contains(identifier), schedulingCompletionReceipts.insert(identifier).inserted else { return }
        defer { schedulingCompletionReceipts.remove(identifier) }
        let center = UNUserNotificationCenter.current()
        configureChatMessageCategory(center: center)

        let settings = await center.notificationSettings()
        guard (settings.authorizationStatus == .authorized || settings.authorizationStatus == .provisional),
              PushCompletionNoticePolicy.permits(expected: captured, current: currentAuthenticatedNoticeContext(),
                  notificationsEnabled: AuthManager.notificationSession.currentUser?.pushNotificationEnabled == true) else {
            return
        }

        let content = UNMutableNotificationContent()
        content.title = AppStrings.openMatesName
        content.body = AppStrings.newMessageReceived
        content.sound = .default
        content.categoryIdentifier = NotificationAction.chatMessageCategory
        content.threadIdentifier = chatId
        content.userInfo = ["chat_id": chatId]
        if let messageID { content.userInfo["message_id"] = messageID }
        if let readScope { content.userInfo[PushReadCardPolicy.scopeKey] = readScope }

        let request = UNNotificationRequest(
            identifier: identifier,
            content: content,
            trigger: nil
        )

        do {
            try await center.add(request)
            guard PushCompletionNoticePolicy.permits(expected: captured, current: currentAuthenticatedNoticeContext(),
                notificationsEnabled: AuthManager.notificationSession.currentUser?.pushNotificationEnabled == true) else {
                center.removePendingNotificationRequests(withIdentifiers: [identifier])
                center.removeDeliveredNotifications(withIdentifiers: [identifier])
                return
            }
            var updated = UserDefaults.standard.stringArray(forKey: Self.completionNoticeLedgerKey) ?? []
            if !updated.contains(identifier) { updated.append(identifier) }
            UserDefaults.standard.set(Array(updated.suffix(256)), forKey: Self.completionNoticeLedgerKey)
            NativeDiagnostics.event("chat_completion_notice_scheduled", category: "push_notifications",
                flags: ["stable_message_receipt": messageID != nil])
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

    func showWatchWebOpenNotification(_ payload: WatchPhoneOpenPayload) async {
        guard payload.destination(currentProfile: ServerProfile.current()) != nil else { return }
        let center = UNUserNotificationCenter.current()
        var settings = await center.notificationSettings()
        if settings.authorizationStatus == .notDetermined {
            _ = try? await center.requestAuthorization(options: [.alert, .sound])
            settings = await center.notificationSettings()
        }
        guard settings.authorizationStatus == .authorized || settings.authorizationStatus == .provisional else { return }

        let content = UNMutableNotificationContent()
        content.title = AppStrings.openMatesName
        content.body = AppStrings.tapToExplore
        content.sound = .default
        content.userInfo = payload.message
        let request = UNNotificationRequest(
            identifier: "openmates-watch-web-\(UUID().uuidString)",
            content: content,
            trigger: nil
        )
        do {
            try await center.add(request)
        } catch {
            NativeDiagnostics.warning("Watch web notification scheduling failed: \(type(of: error))", category: "push_notifications")
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
        NativeDiagnostics.event("notification_presented", category: "push_notifications", flags: [
            "remote_push": notification.request.trigger is UNPushNotificationTrigger,
            "local_request": notification.request.trigger == nil
        ])
        return [.banner, .sound, .badge]
    }

    nonisolated func userNotificationCenter(
        _ center: UNUserNotificationCenter,
        didReceive response: UNNotificationResponse,
        withCompletionHandler completionHandler: @escaping () -> Void
    ) {
        NativeDiagnostics.event("notification_response", category: "push_notifications", flags: [
            "remote_push": response.notification.request.trigger is UNPushNotificationTrigger,
            "local_request": response.notification.request.trigger == nil
        ])
        let userInfo = response.notification.request.content.userInfo
        let watchMessage = Dictionary(uniqueKeysWithValues: userInfo.compactMap { key, value -> (String, Any)? in
            guard let key = key as? String else { return nil }
            return (key, value)
        })
        let completionMessageID = (userInfo["message_id"] as? String) ?? (userInfo["messageId"] as? String)
        if let payload = WatchPhoneOpenPayload.parse(watchMessage) {
            let actionIdentifier = response.actionIdentifier
            let completion = NotificationCompletionBox(completionHandler)
            Task { @MainActor in
                defer { completion.complete() }
                guard actionIdentifier == UNNotificationDefaultActionIdentifier,
                      let destination = payload.destination(currentProfile: ServerProfile.current()) else { return }
                #if os(iOS)
                UIApplication.shared.open(destination)
                #elseif os(macOS)
                NSWorkspace.shared.open(destination)
                #endif
            }
            return
        }
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
                    UnreadMessagesStore.shared.resynchronizeBadge()
                } catch {
                    NativeDiagnostics.warning("Notification reply persistence failed: \(type(of: error))", category: "push_notifications")
                }
            } else {
                handleNotificationResponse(actionIdentifier: actionIdentifier, chatId: chatId, embedId: embedId,
                    messageID: completionMessageID)
            }
        }
    }

    private func handleNotificationResponse(actionIdentifier: String, chatId: String, embedId: String?, messageID: String?) {
        if actionIdentifier == Self.NotificationAction.openChat ||
            actionIdentifier == UNNotificationDefaultActionIdentifier {
            NativeDiagnostics.info("Notification open action received", category: "push_notifications")
            completionCatchUpIntent = ChatNotificationCatchUpIntent(chatID: chatId, messageID: messageID)
            pendingEmbedId = embedId
            pendingChatId = chatId
            // Chat activation clears only its target; retain other unread chats.
            UnreadMessagesStore.shared.resynchronizeBadge()
        }
    }

    /// Best effort on this executing device after the exact viewed-message ACK.
    /// Account/server/Team/deletion fences are rechecked after OS inventory reads.
    func removeAcknowledgedChatNotifications(chatID: String, messageIDs: Set<String>,
        accountID: String, profile: ServerProfile, scope: UUID, team: TeamWorkspaceSnapshot,
        deletion: Int) async {
        func isCurrent() -> Bool {
            let current = TeamWorkspaceContext.shared.snapshot
            return !Task.isCancelled && AuthManager.notificationSession.hasNetworkAuthority
                && AuthManager.notificationAccountId == accountID && ServerProfile.current() == profile
                && OfflineStore.shared.scopeGeneration == scope && current.accountID == team.accountID
                && current.server == team.server && current.scope == team.scope
                && current.teamID == team.teamID && current.epoch == team.epoch
                && team.accountID == accountID && team.server == profile && team.scope == scope
                && OfflineStore.shared.chatDeletionVersion(chatID) == deletion
        }
        guard !messageIDs.isEmpty, isCurrent() else { return }
        let center = UNUserNotificationCenter.current()
        let delivered = await center.deliveredNotifications()
        guard isCurrent() else { return }
        let pending = await center.pendingNotificationRequests()
        guard isCurrent() else { return }
        let readScope = PushReadCardPolicy.scopeID(accountID: accountID, profile: profile, teamID: team.teamID)
        let deliveredIDs = delivered.compactMap { notification in
            PushReadCardPolicy.matches(userInfo: notification.request.content.userInfo, scopeID: readScope,
                chatID: chatID, messageIDs: messageIDs) ? notification.request.identifier : nil
        }
        let pendingIDs = pending.compactMap { request in
            PushReadCardPolicy.matches(userInfo: request.content.userInfo, scopeID: readScope,
                chatID: chatID, messageIDs: messageIDs) ? request.identifier : nil
        }
        if !deliveredIDs.isEmpty { center.removeDeliveredNotifications(withIdentifiers: deliveredIDs) }
        if !pendingIDs.isEmpty { center.removePendingNotificationRequests(withIdentifiers: pendingIDs) }
    }
}
