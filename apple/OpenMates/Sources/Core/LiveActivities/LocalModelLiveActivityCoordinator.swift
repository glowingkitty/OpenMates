// Lifecycle owner for one aggregate model-download Live Activity and verified
// completion notifications. All effects are serialized and cancellation fenced.
// Specification: specifications/features/apple-live-activities/specification.yml
// Assertions: apple-live-activities.download.progress, apple-live-activities.download.completion
import Foundation
import Combine
#if os(iOS)
// This SDK leaves Activity and its async update/end APIs without Sendable
// annotations. Keep framework interoperability local: all app-side handles
// remain owned by this MainActor coordinator and its ordered effect queue.
@preconcurrency import ActivityKit
import UIKit
import UserNotifications
#endif

enum LocalModelDownloadOutcome: Equatable, Sendable { case verified, cancelled, failed }
enum LocalModelDownloadActivityEvent: Sendable {
    case started(model: LocalModelID, operation: UUID, totalBytes: Int64)
    case progress(model: LocalModelID, operation: UUID, value: LocalModelInstallProgress)
    case finished(model: LocalModelID, operation: UUID, outcome: LocalModelDownloadOutcome)
}

/// Store-issued operations distinguish a fresh successful reinstall from replay.
/// A progress or terminal event from an older operation cannot mutate its replacement.
struct LocalModelLiveActivityPolicy {
    struct Item {
        let operation: UUID
        let totalBytes: Int64
        var transferredBytes: Int64 = 0
        var verifiedBytes: Int64 = 0
        var sequence: UInt64 = 0
        var phase: LocalModelInstallPhase = .transfer
    }
    private(set) var items: [LocalModelID: Item] = [:]
    mutating func consume(_ event: LocalModelDownloadActivityEvent) -> (LocalModelID, UUID)? {
        switch event {
        case let .started(model, operation, total):
            guard items[model]?.operation != operation else { return nil }
            items[model] = Item(operation: operation, totalBytes: max(1, total))
        case let .progress(model, operation, value):
            guard var item = items[model], item.operation == operation, value.sequence > item.sequence else { return nil }
            item.sequence = value.sequence
            item.phase = value.phase
            item.transferredBytes = max(item.transferredBytes, min(item.totalBytes, max(0, value.transferredBytes)))
            item.verifiedBytes = max(item.verifiedBytes, min(item.totalBytes, max(0, value.verifiedBytes)))
            items[model] = item
        case let .finished(model, operation, outcome):
            guard items[model]?.operation == operation else { return nil }
            items[model] = nil
            if outcome == .verified { return (model, operation) }
        }
        return nil
    }
    mutating func restore(model: LocalModelID, operation: UUID, transferred: Int64, verified: Int64) {
        guard var item = items[model], item.operation == operation else { return }
        item.transferredBytes = min(item.totalBytes, max(0, transferred))
        item.verifiedBytes = min(item.totalBytes, max(0, verified))
        items[model] = item
    }
    var transferredBytes: Int64 { items.values.reduce(0) { $0 + $1.transferredBytes } }
    var totalBytes: Int64 { items.values.reduce(0) { $0 + $1.totalBytes } }
    var progress: Double {
        let total = totalBytes
        guard total > 0 else { return 0 }
        // Transfer and checksum verification contribute equal bounded portions;
        // completion is emitted only by the installer's verified terminal event.
        let completed = items.values.reduce(Int64(0)) { $0 + $1.transferredBytes + $1.verifiedBytes }
        return min(0.99, max(0, Double(completed) / (Double(total) * 2)))
    }
}

/// Public model metadata only; shared by the real coordinator and its effect driver.
struct LocalModelActivityPresentation: Equatable, Sendable {
    let title: String
    let detail: String
    let phase: String
    let progress: Double
    let completedBytes: Int64
    let totalBytes: Int64
    let itemCount: Int
}

@MainActor
protocol LocalModelLiveActivityDriving: AnyObject {
    var activitiesEnabled: Bool { get }
    var foreground: Bool { get }
    var hasExistingActivity: Bool { get }
    func request(_ state: LocalModelActivityPresentation) throws
    func update(_ state: LocalModelActivityPresentation) async
    func end() async
}

@MainActor
final class LocalModelLiveActivityCoordinator: ObservableObject {
    static let shared = LocalModelLiveActivityCoordinator()
    private var policy = LocalModelLiveActivityPolicy()
    private var generation = UUID()
    private var tail: Task<Void, Never>?
    private var lastPublishedAt: TimeInterval = 0
    private var lastPublishedPhase: String?
    private var requestedCurrentBatch = false
    private var packIsActive = false
    private let defaults: UserDefaults
    private let driver: any LocalModelLiveActivityDriving
    private let clock: () -> TimeInterval
    private let completionNotificationsEnabled: Bool
    private static let completionLedgerKey = "openmates.local-model-notices.v1"
    private static let activityOperationLedgerKey = "openmates.local-model-live.operations.v1"
    private static let progressCheckpointKey = "openmates.local-model-live.progress.v1"
    private struct Checkpoint: Codable {
        let transferred: Int64
        let verified: Int64
    }
    private var checkpoints: [String: Checkpoint] = [:]
    #if os(iOS)
    private var foregroundObserver: NSObjectProtocol?
    #endif
    #if DEBUG
    // Test-only receipt is generated after real driver effects, never from UI state.
    @Published private(set) var diagnosticReceipt = "idle"
    private var requests = 0
    private var updates = 0
    private var backgroundUpdates = 0
    #endif

    init(defaults: UserDefaults = .standard,
         driver: (any LocalModelLiveActivityDriving)? = nil,
         clock: @escaping () -> TimeInterval = { ProcessInfo.processInfo.systemUptime },
         completionNotificationsEnabled: Bool = true) {
        self.defaults = defaults
        self.clock = clock
        self.completionNotificationsEnabled = completionNotificationsEnabled
        if let data = defaults.data(forKey: Self.progressCheckpointKey), data.count <= 65_536,
           let restored = try? JSONDecoder().decode([String: Checkpoint].self, from: data), restored.count <= 128 {
            checkpoints = restored
        }
        #if os(iOS)
        self.driver = driver ?? LocalModelNativeActivityDriver()
        // A background-originated restored batch waits for foreground before
        // requesting; adopting and updating an existing activity needs no UI.
        if driver == nil { foregroundObserver = NotificationCenter.default.addObserver(
            forName: UIApplication.didBecomeActiveNotification, object: nil, queue: .main) { [weak self] _ in
                Task { @MainActor [weak self] in self?.refreshPresentation() }
            } }
        #else
        self.driver = driver ?? LocalModelUnavailableActivityDriver()
        #endif
    }

    func handle(_ event: LocalModelDownloadActivityEvent) {
        enqueue { coordinator, expected in await coordinator.consume(event, expected: expected) }
    }

    private func enqueue(_ effect: @escaping @MainActor @Sendable (LocalModelLiveActivityCoordinator, UUID) async -> Void) {
        let predecessor = tail
        let expected = generation
        tail = Task { [weak self] in
            await predecessor?.value
            guard let self, expected == self.generation, !Task.isCancelled else { return }
            await effect(self, expected)
        }
    }

    /// A sequential pack keeps the current OS Activity alive between models.
    /// This is presentation ownership only; LocalModelStore still owns transfers.
    func setPackActive(_ active: Bool) {
        enqueue { coordinator, _ in
            coordinator.packIsActive = active
            if !active, coordinator.policy.items.isEmpty { await coordinator.publish(nil) }
        }
    }

    func refreshPresentation() {
        enqueue { coordinator, _ in await coordinator.publish(coordinator.presentation) }
    }

    /// Background-session completion drains only effects queued before this call.
    /// Starting a Live Activity never awaits notification permission or UI.
    func waitForPendingEffects() async { await tail?.value }

    /// Account/server/team changes and logout invalidate queued effects.
    func reset() async {
        generation = UUID()
        tail?.cancel()
        tail = nil
        policy = LocalModelLiveActivityPolicy()
        packIsActive = false
        lastPublishedPhase = nil
        requestedCurrentBatch = false
        await publish(nil)
    }

    func reconcileRestoredDownloads() async {
        let expected = generation
        await tail?.value
        guard expected == generation else { return }
        await publish(presentation)
    }

    private func consume(_ event: LocalModelDownloadActivityEvent, expected: UUID) async {
        if case let .started(_, operation, _) = event, policy.items.isEmpty {
            let seen = defaults.stringArray(forKey: Self.activityOperationLedgerKey) ?? []
            requestedCurrentBatch = seen.contains(operation.uuidString)
            lastPublishedPhase = nil
        }
        let completion = policy.consume(event)
        switch event {
        case let .started(model, operation, _):
            if let checkpoint = checkpoints[operation.uuidString] {
                policy.restore(model: model, operation: operation, transferred: checkpoint.transferred, verified: checkpoint.verified)
            }
        case let .progress(model, operation, _):
            if let item = policy.items[model], item.operation == operation {
                checkpoints[operation.uuidString] = .init(transferred: item.transferredBytes, verified: item.verifiedBytes)
            }
        case let .finished(_, operation, _): checkpoints[operation.uuidString] = nil
        }
        // Keep the bounded durable watermark across ActivityKit/URLSession
        // reattachment; a resumed task must not briefly publish zero.
        if checkpoints.count > 128 {
            let active = Set(policy.items.values.map(\.operation.uuidString))
            checkpoints = checkpoints.filter { active.contains($0.key) }
        }
        if let data = try? JSONEncoder().encode(checkpoints) { defaults.set(data, forKey: Self.progressCheckpointKey) }
        // A model joining an already requested (possibly dismissed) batch also
        // retains the dismissal receipt across process restart.
        if requestedCurrentBatch { rememberActivityOperations() }
        guard expected == generation, !Task.isCancelled else { return }
        let terminal: Bool
        switch event { case .finished: terminal = true; default: terminal = false }
        if let state = presentation {
            let now = clock()
            if terminal || state.phase != lastPublishedPhase || now - lastPublishedAt >= 1 {
                await publish(state)
                lastPublishedAt = now
                lastPublishedPhase = state.phase
            }
        } else if !packIsActive {
            await publish(nil)
            requestedCurrentBatch = false
            lastPublishedPhase = nil
        }
        // Completion notices have their own account preference and UN gate.
        // They never delay requesting or ending the download Live Activity.
        #if os(iOS)
        if let (model, operation) = completion, expected == generation, !Task.isCancelled {
            await notifyVerified(model: model, operation: operation, expected: expected)
        }
        #endif
    }

    private var presentation: LocalModelActivityPresentation? {
        guard let item = policy.items.sorted(by: { $0.key.rawValue < $1.key.rawValue }).first else { return nil }
        let phase: String
        let label: String
        switch item.value.phase {
        case .transfer: phase = "transfer"; label = AppStrings.liveActivityTransfer
        case .verification: phase = "verification"; label = AppStrings.liveActivityVerifying
        case .waitingForConnection: phase = "waiting"; label = AppStrings.liveActivityWaiting
        case .retrying: phase = "retrying"; label = AppStrings.liveActivityRetrying
        }
        return .init(title: policy.items.count == 1 ? modelTitle(item.key) : AppStrings.liveActivityDownloadsTitle,
                     detail: label, phase: phase, progress: policy.progress,
                     completedBytes: policy.transferredBytes, totalBytes: policy.totalBytes, itemCount: policy.items.count)
    }

    private func modelTitle(_ model: LocalModelID) -> String {
        AppStrings.offlineAIModelCapability(model)
    }

    private func rememberActivityOperations() {
        var seen = defaults.stringArray(forKey: Self.activityOperationLedgerKey) ?? []
        for operation in policy.items.values.map(\.operation.uuidString) where !seen.contains(operation) { seen.append(operation) }
        defaults.set(Array(seen.suffix(128)), forKey: Self.activityOperationLedgerKey)
    }

    private func publish(_ state: LocalModelActivityPresentation?) async {
        if state == nil, packIsActive { return }
        guard let state, driver.activitiesEnabled else {
            await driver.end()
            #if DEBUG
            diagnosticReceipt = state == nil ? "ended;requests=\(requests);updates=\(updates);background=\(backgroundUpdates)" : "disabled"
            #endif
            return
        }
        if driver.hasExistingActivity {
            requestedCurrentBatch = true
            rememberActivityOperations()
            #if DEBUG
            let wasBackground = !driver.foreground
            #endif
            await driver.update(state)
            #if DEBUG
            updates += 1
            if wasBackground { backgroundUpdates += 1 }
            diagnosticReceipt = "updated;requests=\(requests);updates=\(updates);background=\(backgroundUpdates);bytes=\(state.completedBytes)"
            #endif
        } else if !requestedCurrentBatch, driver.foreground {
            do {
                // Latch only a successful request: transient request failure may
                // retry on foreground. Successful user dismissal stays respected.
                try driver.request(state)
                requestedCurrentBatch = true
                rememberActivityOperations()
                #if DEBUG
                requests += 1
                diagnosticReceipt = "requested;requests=\(requests);updates=\(updates);background=\(backgroundUpdates);bytes=\(state.completedBytes)"
                #endif
            } catch {
                NativeDiagnostics.event("model_live_activity_unavailable", category: "live_activities", level: .warning)
                #if DEBUG
                diagnosticReceipt = "request-failed"
                #endif
            }
        }
    }

    #if os(iOS)
    private var preferencesPermit: Bool {
        let auth = AuthManager.notificationSession
        return auth.state == .authenticated && auth.currentUser?.pushNotificationEnabled == true
    }
    private func notifyVerified(model: LocalModelID, operation: UUID, expected: UUID) async {
        guard completionNotificationsEnabled, preferencesPermit else { return }
        let center = UNUserNotificationCenter.current()
        let settings = await center.notificationSettings()
        guard settings.authorizationStatus == .authorized || settings.authorizationStatus == .provisional else { return }
        let identifier = "openmates-model-ready-" + operation.uuidString
        var ledger = defaults.stringArray(forKey: Self.completionLedgerKey) ?? []
        guard !ledger.contains(identifier), expected == generation, preferencesPermit, !Task.isCancelled else { return }
        let content = UNMutableNotificationContent()
        content.title = AppStrings.openMatesName
        content.body = AppStrings.liveActivityDownloadComplete(model: modelTitle(model))
        content.sound = .default
        do {
            try await center.add(.init(identifier: identifier, content: content, trigger: nil))
            ledger.append(identifier)
            defaults.set(Array(ledger.suffix(128)), forKey: Self.completionLedgerKey)
            if expected != generation || !preferencesPermit {
                center.removeDeliveredNotifications(withIdentifiers: [identifier])
                center.removePendingNotificationRequests(withIdentifiers: [identifier])
            }
        } catch {
            NativeDiagnostics.event("model_completion_notice_failed", category: "live_activities", level: .warning)
        }
    }
    #endif
}

#if os(iOS)
@MainActor
private final class LocalModelNativeActivityDriver: LocalModelLiveActivityDriving {
    var activitiesEnabled: Bool {
        if #available(iOS 16.2, *) { return ActivityAuthorizationInfo().areActivitiesEnabled }
        return false
    }
    var foreground: Bool { UIApplication.shared.applicationState == .active }
    var hasExistingActivity: Bool {
        if #available(iOS 16.2, *) { return usableActivity != nil }
        return false
    }
    @available(iOS 16.2, *)
    private var activities: [Activity<OpenMatesLiveActivityAttributes>] {
        Activity<OpenMatesLiveActivityAttributes>.activities.filter { $0.attributes.kind == "download" }
    }
    @available(iOS 16.2, *)
    private var usableActivity: Activity<OpenMatesLiveActivityAttributes>? {
        activities.first { $0.activityState == .active || $0.activityState == .stale }
    }
    @available(iOS 16.2, *)
    private func content(_ state: LocalModelActivityPresentation) -> ActivityContent<OpenMatesLiveActivityAttributes.ContentState> {
        .init(state: .init(title: state.title, detail: state.detail, phase: state.phase,
            progress: state.progress, completedBytes: state.completedBytes, totalBytes: state.totalBytes,
            itemCount: state.itemCount, startsAt: nil, expiresAt: nil), staleDate: Date().addingTimeInterval(90))
    }
    func request(_ state: LocalModelActivityPresentation) throws {
        if #available(iOS 16.2, *) {
            _ = try Activity.request(attributes: OpenMatesLiveActivityAttributes(identity: "model-downloads", kind: "download"),
                                     content: content(state), pushType: nil)
        }
    }
    func update(_ state: LocalModelActivityPresentation) async {
        if #available(iOS 16.2, *), let retained = usableActivity {
            for duplicate in activities where duplicate.id != retained.id { await duplicate.end(nil, dismissalPolicy: .immediate) }
            await retained.update(content(state))
        }
    }
    func end() async {
        if #available(iOS 16.2, *) { for activity in activities { await activity.end(nil, dismissalPolicy: .immediate) } }
    }
}
#else
@MainActor
private final class LocalModelUnavailableActivityDriver: LocalModelLiveActivityDriving {
    var activitiesEnabled: Bool { false }
    var foreground: Bool { false }
    var hasExistingActivity: Bool { false }
    func request(_ state: LocalModelActivityPresentation) throws {}
    func update(_ state: LocalModelActivityPresentation) async {}
    func end() async {}
}
#endif
