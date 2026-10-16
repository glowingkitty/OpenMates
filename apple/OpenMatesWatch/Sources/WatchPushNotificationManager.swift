// Standalone Watch APNs lifecycle and exact authenticated notification routing.
// Specification: specifications/features/apple-notifications/specification.yml
// Assertions: apple-notifications.registration.lifecycle, apple-notifications.payload.privacy-safe,
//             apple-notifications.action.routing-coherent
// Specification: specifications/features/apple-offline-workspaces/specification.yml
// Assertions: apple-workspaces.watch-retention, apple-workspaces.maintenance
import Combine
import Foundation
import UserNotifications
import WatchKit

@MainActor
final class WatchPushNotificationManager: NSObject, ObservableObject, UNUserNotificationCenterDelegate {
    static let shared = WatchPushNotificationManager()
    static let category = "OPENMATES_CHAT_MESSAGE"
    static let openAction = "OPENMATES_OPEN_CHAT"
    @Published private(set) var isRegistered = false
    @Published private(set) var pendingRoute: WatchNotificationRoute?
    private var visibility = WatchNotificationVisibility()
    var viewedChatID: String? {
        get { visibility.chatID }
        set { visibility.show(newValue, identity: identity) }
    }
    var isActive = false

    private weak var auth: WatchAuthStore?
    private var authObserver: AnyCancellable?
    private var registrationTask: Task<Void, Never>?
    private var desired: WatchPushRegistration?
    private var acknowledged: WatchPushRegistration?
    private var token: String?
    private var permission = false
    private var requestedRemoteRegistration = false
    private let tokenKey = "openmates.watch.push.token"
    private let deviceKey = "openmates.watch.push.installation"
    private let receiptKey = "openmates.watch.push.account"
    private let cleanupKey = "openmates.watch.push.pending-cleanup"
    private let revocation: WatchPushRevocation

    private override init() {
        let pending = (try? KeychainHelper.load(key: "openmates.watch.push.pending-cleanup"))
            .flatMap { try? JSONDecoder().decode(WatchPushRegistration.self, from: $0) }
        revocation = WatchPushRevocation(pendingCleanup: pending)
        super.init()
        if let data = try? KeychainHelper.load(key: tokenKey) { token = String(data: data, encoding: .utf8) }
    }

    private var identity: WatchPushIdentity? {
        guard let auth, auth.state == .authenticated, let accountID = auth.currentUser?.id else { return nil }
        return WatchPushIdentity(accountID: accountID, serverScope: WatchChatRuntime.currentServerScope,
                                 generation: WatchChatAccountLifecycle.generation)
    }

    private func installationID() throws -> String {
        if let data = try? KeychainHelper.load(key: deviceKey),
           let value = String(data: data, encoding: .utf8), !value.isEmpty { return value }
        let value = "watch-" + UUID().uuidString.lowercased()
        try KeychainHelper.save(key: deviceKey, data: Data(value.utf8))
        return value
    }

    func configureForLaunch() {
#if DEBUG
        guard !ProcessInfo.processInfo.arguments.contains(where: { $0.hasPrefix("--ui-test-") }) else { return }
#endif
        ServerConfiguration.current = WatchServerProfileStore().currentProfile().endpointConfiguration
        let center = UNUserNotificationCenter.current()
        center.delegate = self
        let open = UNNotificationAction(identifier: Self.openAction,
                                        title: WatchLocalization.text("chat.open_chat"), options: [.foreground])
        center.setNotificationCategories([UNNotificationCategory(identifier: Self.category,
            actions: [open], intentIdentifiers: [], options: [])])
    }

    func attach(_ auth: WatchAuthStore) {
        self.auth = auth
        authObserver = auth.objectWillChange.sink { [weak self] _ in
            Task { @MainActor in await self?.refresh() }
        }
        Task { await refresh() }
    }

    func refresh() async {
        let captured = identity
        guard let captured, auth?.isVerifiedOnline == true else { invalidate(); return }
        guard await finishPendingCleanup(), captured == identity, auth?.isVerifiedOnline == true else { return }
        let center = UNUserNotificationCenter.current()
        var settings = await center.notificationSettings()
        guard captured == identity, auth?.isVerifiedOnline == true else { invalidate(); return }
        if settings.authorizationStatus == .notDetermined {
            _ = try? await center.requestAuthorization(options: [.alert, .sound, .badge])
            settings = await center.notificationSettings()
        }
        guard captured == identity, auth?.isVerifiedOnline == true else { invalidate(); return }
        permission = settings.authorizationStatus == .authorized || settings.authorizationStatus == .provisional
        NativeDiagnostics.event("permission_checked", category: "watch_push", flags: ["allowed": permission])
        guard permission else { await unregisterCurrentDevice(); invalidate(); return }
        if !requestedRemoteRegistration {
            requestedRemoteRegistration = true
            NativeDiagnostics.event("apns_registration_requested", category: "watch_push")
            WKApplication.shared().registerForRemoteNotifications()
        }
        guard let token else { return }
        guard let deviceID = try? installationID() else { isRegistered = false; return }
        let registration = WatchPushRegistration(identity: captured, token: token, deviceID: deviceID)
        guard desired != registration || (registrationTask == nil && acknowledged != registration) else { return }
        registrationTask?.cancel()
        desired = registration
        isRegistered = acknowledged == registration
        let profile = ServerProfile.current()
        registrationTask = Task { @MainActor [weak self] in
            guard let self else { return }
            defer { if self.desired == registration { self.registrationTask = nil } }
            do {
                let data = try await APIClient.shared.requestForWatchPush(.post,
                    path: "/v1/notifications/register-device", serverProfile: profile,
                    body: ["token": registration.token, "device_id": registration.deviceID,
                           "platform": "watchos", "environment": Self.environment],
                    validate: { [weak self] in
                        guard let self, self.desired == registration,
                              registration.isCurrent(identity: self.identity, token: self.token,
                                permission: self.permission, online: self.auth?.isVerifiedOnline == true),
                              profile == ServerProfile.current() else { throw CancellationError() }
                    })
                guard self.desired == registration,
                      registration.isCurrent(identity: self.identity, token: self.token,
                        permission: self.permission, online: self.auth?.isVerifiedOnline == true),
                      profile == ServerProfile.current() else { throw CancellationError() }
                let result = try JSONDecoder().decode(RegistrationResponse.self, from: data)
                guard result.success else { throw APIError.invalidResponse }
                try KeychainHelper.save(key: self.receiptKey, data: JSONEncoder().encode(captured))
                self.acknowledged = registration
                self.isRegistered = true
                NativeDiagnostics.event("registration_acknowledged", category: "watch_push")
            } catch {
                if self.desired == registration { self.isRegistered = false }
                NativeDiagnostics.event("registration_unacknowledged", category: "watch_push", level: .warning)
            }
        }
    }

    func receiveDeviceToken(_ data: Data) {
        NativeDiagnostics.event("apns_token_received", category: "watch_push")
        token = data.map { String(format: "%02x", $0) }.joined()
        if let token { try? KeychainHelper.save(key: tokenKey, data: Data(token.utf8)) }
        Task { await refresh() }
    }

    func remoteRegistrationFailed(error: Error) {
        requestedRemoteRegistration = false
        invalidate()
        NativeDiagnostics.failure("apns_registration_failed", category: "watch_push", level: .warning, error: error)
    }

    func invalidate() {
        registrationTask?.cancel()
        registrationTask = nil
        desired = nil
        acknowledged = nil
        isRegistered = false
        visibility.invalidateUnlessMatching(identity)
        if let pendingRoute, (identity != nil && pendingRoute.identity != identity) || auth?.state == .unauthenticated {
            self.pendingRoute = nil
        }
    }

    func unregisterCurrentDevice() async {
        let receipt = (try? KeychainHelper.load(key: receiptKey))
            .flatMap { try? JSONDecoder().decode(WatchPushIdentity.self, from: $0) }
        let registration: WatchPushRegistration? = acknowledged ?? desired ?? {
            guard let token, let owner = identity ?? receipt, let deviceID = try? installationID() else { return nil }
            return WatchPushRegistration(identity: owner, token: token, deviceID: deviceID)
        }()
        registrationTask?.cancel()
        desired = nil
        acknowledged = nil
        isRegistered = false
        pendingRoute = nil
        visibility.show(nil, identity: nil)
        revocation.revoke(registration) {
            // OS visibility and routing are revoked even if auth is offline,
            // expired, or the server cannot acknowledge DELETE.
            self.requestedRemoteRegistration = false
            self.token = nil
            try? KeychainHelper.delete(key: self.tokenKey)
            try? KeychainHelper.delete(key: self.receiptKey)
            WKApplication.shared().unregisterForRemoteNotifications()
            let center = UNUserNotificationCenter.current()
            center.removeAllDeliveredNotifications()
            center.removeAllPendingNotificationRequests()
        }
        if let pending = revocation.pendingCleanup,
           let data = try? JSONEncoder().encode(pending) { try? KeychainHelper.save(key: cleanupKey, data: data) }
        _ = await finishPendingCleanup()
    }

    private func finishPendingCleanup() async -> Bool {
        guard let captured = identity,
              let pending = revocation.cleanupFor(identity: captured, online: auth?.isVerifiedOnline == true) else { return true }
        let profile = ServerProfile.current()
        do {
            let data = try await APIClient.shared.requestForWatchPush(.delete,
                path: "/v1/notifications/unregister-device", serverProfile: profile,
                body: ["token": pending.token, "device_id": pending.deviceID], validate: { [weak self] in
                    guard let self, captured == self.identity, self.auth?.isVerifiedOnline == true,
                          self.revocation.pendingCleanup == pending,
                          profile == ServerProfile.current() else { throw CancellationError() }
                })
            guard captured == identity, profile == ServerProfile.current(), revocation.pendingCleanup == pending,
                  auth?.isVerifiedOnline == true,
                  try JSONDecoder().decode(RegistrationResponse.self, from: data).success else { return false }
            revocation.acknowledge(pending)
            try? KeychainHelper.delete(key: cleanupKey)
            return true
        } catch {
            NativeDiagnostics.event("unregister_unacknowledged", category: "watch_push", level: .warning)
            return false
        }
    }

    func consume(_ route: WatchNotificationRoute) { if pendingRoute == route { pendingRoute = nil } }
    func permitsOpen(_ route: WatchNotificationRoute) -> Bool {
        route.permitsOpen(identity: identity, online: auth?.isVerifiedOnline == true)
    }

    nonisolated func userNotificationCenter(_ center: UNUserNotificationCenter,
        willPresent notification: UNNotification) async -> UNNotificationPresentationOptions {
        let chatID = notification.request.content.userInfo["chat_id"] as? String
        return await MainActor.run {
            NativeDiagnostics.event("notification_received", category: "watch_push", flags: ["has_chat": chatID != nil])
            return self.visibility.shouldPresent(chatID: chatID, identity: self.identity,
                                          active: self.isActive) ? [.banner, .sound] : []
        }
    }

    nonisolated func userNotificationCenter(_ center: UNUserNotificationCenter,
        didReceive response: UNNotificationResponse) async {
        let action = response.actionIdentifier
        let chatID = response.notification.request.content.userInfo["chat_id"] as? String
        await MainActor.run {
            guard action == UNNotificationDefaultActionIdentifier || action == Self.openAction,
                  let chatID, let data = try? KeychainHelper.load(key: self.receiptKey),
                  let receipt = try? JSONDecoder().decode(WatchPushIdentity.self, from: data),
                  receipt.serverScope == WatchChatRuntime.currentServerScope else { return }
            let captured = WatchPushIdentity(accountID: receipt.accountID, serverScope: receipt.serverScope,
                                             generation: WatchChatAccountLifecycle.generation)
            self.pendingRoute = WatchNotificationRoute(chatID: chatID, identity: captured)
            NativeDiagnostics.event("notification_open_requested", category: "watch_push")
        }
    }

    private struct RegistrationResponse: Decodable { let success: Bool }
    private static var environment: String {
#if DEBUG
        "sandbox"
#else
        "production"
#endif
    }
}

/// OS grants are opportunistic. Never hold an application refresh task open
/// indefinitely or claim the complete cohort from a partial execution window.
@MainActor final class WatchBackgroundOfflineSync {
    static let shared = WatchBackgroundOfflineSync()
    enum Slot: CaseIterable { case chats, hub }
    private struct Work { let owner: String; let perform: @MainActor () async -> Void }
    private var work: [Slot: Work] = [:]
    private var scheduled = false
    private var activeID: UUID?
    private var operation: Task<Void, Never>?
    private var deadline: Task<Void, Never>?
    func register(_ slot: Slot, owner: String, perform: @escaping @MainActor () async -> Void) {
        work[slot] = Work(owner: owner, perform: perform)
        schedule()
    }
    func unregister(_ slot: Slot, owner: String) {
        if work[slot]?.owner == owner { work[slot] = nil }
    }
    func schedule() {
        guard !scheduled, !work.isEmpty else { return }
        scheduled = true
        WKApplication.shared().scheduleBackgroundRefresh(withPreferredDate: Date().addingTimeInterval(15 * 60), userInfo: nil) { error in
            Task { @MainActor in
                if error != nil {
                    self.scheduled = false
                    NativeDiagnostics.event("offline_refresh_schedule_failed", category: "watch_hub", level: .warning)
                }
            }
        }
    }
    func handle(_ task: WKApplicationRefreshBackgroundTask) {
        scheduled = false
        guard activeID == nil else { task.setTaskCompletedWithSnapshot(false); schedule(); return }
        let id = UUID(); activeID = id
        let jobs = Slot.allCases.compactMap { work[$0] }
        operation = Task(priority: .utility) { @MainActor in
            for job in jobs {
                guard !Task.isCancelled, self.activeID == id else { break }
                await job.perform()
            }
            self.finish(id: id, task: task)
        }
        deadline = Task { @MainActor in
            do { try await Task.sleep(for: .seconds(20)) } catch { return }
            self.finish(id: id, task: task)
        }
    }
    private func finish(id: UUID, task: WKApplicationRefreshBackgroundTask) {
        guard activeID == id else { return }
        activeID = nil
        operation?.cancel(); operation = nil
        deadline?.cancel(); deadline = nil
        task.setTaskCompletedWithSnapshot(false)
        schedule()
    }
}

final class WatchPushAppDelegate: NSObject, WKApplicationDelegate {
    func handle(_ backgroundTasks: Set<WKRefreshBackgroundTask>) {
        Task { @MainActor in
            for task in backgroundTasks {
                if let refresh = task as? WKApplicationRefreshBackgroundTask {
                    WatchBackgroundOfflineSync.shared.handle(refresh)
                } else { task.setTaskCompletedWithSnapshot(false) }
            }
        }
    }
    func didRegisterForRemoteNotifications(withDeviceToken deviceToken: Data) {
        Task { @MainActor in WatchPushNotificationManager.shared.receiveDeviceToken(deviceToken) }
    }
    func didFailToRegisterForRemoteNotificationsWithError(_ error: Error) {
        Task { @MainActor in
            WatchPushNotificationManager.shared.remoteRegistrationFailed(error: error)
        }
    }
}
