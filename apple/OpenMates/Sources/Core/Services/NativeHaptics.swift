// Native-only confirmation feedback; no private content or identifiers are logged.
// Specification: specifications/features/chats/specification.yml
// Assertions: chats.message.confirmed-haptic
// Specification: specifications/features/apple-notifications/specification.yml
// Assertions: apple-notifications.delivery.confirmed-action-haptics
// Specification: specifications/features/notifications/specification.yml
// Assertions: notifications.sounds.important-events, notifications.sounds.quiet-window, notifications.sounds.silent-mode
// Svelte counterpart: frontend/packages/ui/src/services/eventSounds.ts
import Foundation
import CoreFoundation
#if os(iOS)
import UIKit
import CoreHaptics
#elseif os(macOS)
import AppKit
#elseif os(watchOS)
import WatchKit
#endif

/// OS feedback generators preserve system haptic settings. Unsupported hardware
/// and inactive apps are silent. APNs vibration remains entirely OS-controlled.
///
/// Policy (Notifications Specification v2): a light tap only on primary commit
/// actions (save, confirm, create, confirmed delete), a distinct accepted cue
/// for a message the server admitted, a notification cue and an error cue.
/// Ordinary button presses never vibrate. One shared quiet window drops any
/// haptic within 3 seconds of the previous one (never queued or replayed and a
/// dropped one does not extend it). Silent mode (device-only) plays nothing.
@MainActor
final class NativeHaptics {
    enum Event: String, CaseIterable {
        case messageAccepted, taskCreated, taskUpdated, workflowCreated, workflowUpdated
        case teamCreated, authenticated, apiKeyCreated, chatDeleted, notification, error

        /// What the user feels; every commit action renders the same light tap.
        var cue: Cue {
            switch self {
            case .messageAccepted: return .accepted
            case .notification: return .notification
            case .error: return .error
            case .taskCreated, .taskUpdated, .workflowCreated, .workflowUpdated,
                 .teamCreated, .authenticated, .apiKeyCreated, .chatDeleted:
                return .lightTap
            }
        }
    }

    /// Rendered haptic kind, small enough for tests to assert.
    enum Cue: Equatable { case lightTap, accepted, notification, error }

    /// Same key the web app uses for its device-local silent mode.
    static let silentModeKey = "openmates_silent_mode"
    static let quietWindow: TimeInterval = 3

    static let shared = NativeHaptics()
    private struct Key: Hashable { let event: Event; let id: String; let scope: String }
    private var delivered: Set<Key> = []
    private var order: [Key] = []
    private var lastPlayed: TimeInterval?
    private let enabled: @MainActor () -> Bool
    private let render: @MainActor (Cue) -> Void
    private let silent: @MainActor () -> Bool
    private let clock: @MainActor () -> TimeInterval

    init(enabled: @escaping @MainActor () -> Bool = NativeHaptics.isSupportedAndActive,
         render: @escaping @MainActor (Cue) -> Void = NativeHaptics.play,
         silent: @escaping @MainActor () -> Bool = NativeHaptics.isSilentMode,
         clock: @escaping @MainActor () -> TimeInterval = { ProcessInfo.processInfo.systemUptime }) {
        self.enabled = enabled; self.render = render; self.silent = silent; self.clock = clock
    }

    static func isSilentMode() -> Bool { UserDefaults.standard.bool(forKey: silentModeKey) }
    static func setSilentMode(_ value: Bool) { UserDefaults.standard.set(value, forKey: silentModeKey) }

    /// Call only after the owning operation's account/context fence succeeds.
    /// Consume even a suppressed event, so foregrounding, silent mode and the
    /// quiet window never replay feedback later.
    func confirmed(_ event: Event, id: String, scope: String) {
        guard !id.isEmpty, !scope.isEmpty else { return }
        let key = Key(event: event, id: id, scope: scope)
        guard delivered.insert(key).inserted else { return }
        order.append(key)
        if order.count > 512 { delivered.remove(order.removeFirst()) }
        guard !silent(), enabled() else { return }
        let now = clock()
        if let lastPlayed, now - lastPlayed < Self.quietWindow { return }
        lastPlayed = now
        render(event.cue)
    }

    private static func isSupportedAndActive() -> Bool {
        #if os(iOS)
        return UIApplication.shared.applicationState == .active && CHHapticEngine.capabilitiesForHardware().supportsHaptics
        #elseif os(macOS)
        return NSApplication.shared.isActive
        #elseif os(watchOS)
        return WKApplication.shared().applicationState == .active
        #else
        return false
        #endif
    }

    private static func play(_ cue: Cue) {
        #if os(iOS)
        switch cue {
        case .lightTap, .accepted: UIImpactFeedbackGenerator(style: .light).impactOccurred()
        case .notification: UIImpactFeedbackGenerator(style: .soft).impactOccurred(intensity: 0.5)
        case .error: UINotificationFeedbackGenerator().notificationOccurred(.error)
        }
        #elseif os(macOS)
        // Apple's AppKit guidance limits trackpad feedback to user actions.
        switch cue {
        case .lightTap, .accepted:
            NSHapticFeedbackManager.defaultPerformer.perform(.generic, performanceTime: .now)
        case .notification, .error: break
        }
        #elseif os(watchOS)
        let pattern: WKHapticType
        switch cue {
        case .lightTap: pattern = .click
        case .accepted: pattern = .start
        case .notification: pattern = .notification
        case .error: pattern = .failure
        }
        WKInterfaceDevice.current().play(pattern)
        #endif
    }
}

/// Joins durable encrypted user storage with matching processing admission.
/// PREPARED is returned only after Directus' prepare_preflight transaction commits
/// the exact encrypted user row and committed_messages_v. Legacy queue receipts
/// are NOT durable proof and remain silent without an authoritative receipt.
@MainActor
final class NativeMessageHapticGate {
    private struct Pending {
        let turnID: String
        let chatID: String
        let messageID: String
        let expectedVersion: Int
        let started: Date
        var admitted = false
        var stored = false
    }
    private var scope: String?
    private var pending: [String: Pending] = [:]
    private var attempted: Set<String> = []
    private var attemptedOrder: [String] = []
    private let haptics: NativeHaptics
    init(haptics: NativeHaptics = .shared) { self.haptics = haptics }

    func begin(turnID: String, chatID: String, messageID: String, preflightState: String,
               scope: String, expectedVersion: Int = 1, committedVersion: Int? = nil, now: Date = Date()) {
        synchronize(scope, now: now)
        guard ["PREPARED", "LEGACY"].contains(preflightState), !turnID.isEmpty,
              !chatID.isEmpty, !messageID.isEmpty, expectedVersion > 0,
              pending[messageID] == nil, pending.count < 64,
              attempted.insert(turnID).inserted else { return }
        attemptedOrder.append(turnID)
        if attemptedOrder.count > 512 { attempted.remove(attemptedOrder.removeFirst()) }
        pending[messageID] = Pending(turnID: turnID, chatID: chatID, messageID: messageID,
            expectedVersion: expectedVersion, started: now)
        if preflightState == "PREPARED", let committedVersion {
            confirmedDurability(chatID: chatID, messageID: messageID,
                version: committedVersion, scope: scope, now: now)
        }
    }

    func cancel(messageID: String, scope: String) {
        guard self.scope == scope else { return }
        pending.removeValue(forKey: messageID)
    }

    func consume(type: String, fields: [String: Any], scope: String, now: Date = Date()) {
        synchronize(scope, now: now)
        guard type == "ai_task_initiated", fields["code"] == nil,
              let chatID = fields["chat_id"] as? String,
              let messageID = fields["user_message_id"] as? String,
              let taskID = (fields["ai_task_id"] ?? fields["task_id"]) as? String, !taskID.isEmpty,
              var turn = pending[messageID], turn.chatID == chatID else { return }
        turn.admitted = true
        publish(turn, scope: scope)
    }

    /// Only the successful exact-row transaction receipt may call this today.
    /// encrypted_metadata_stored/status=queued_for_storage never calls it.
    func confirmedDurability(chatID: String, messageID: String, version: Int,
                             scope: String, now: Date = Date()) {
        synchronize(scope, now: now)
        guard var turn = pending[messageID], turn.chatID == chatID,
              version == turn.expectedVersion else { return }
        turn.stored = true
        publish(turn, scope: scope)
    }

    /// A version binds storage proof to this immutable preflight, not any chat row.
    static func preparedStorageVersion(_ receipt: [String: Any], expected: Any?) -> Int? {
        guard receipt["state"] as? String == "PREPARED", receipt["code"] == nil,
              let expected = integer(expected), expected < Int.max,
              let committed = integer(receipt["committed_messages_v"]), committed == expected + 1 else { return nil }
        return committed
    }
    private static func integer(_ value: Any?) -> Int? {
        guard let number = value as? NSNumber, CFGetTypeID(number) != CFBooleanGetTypeID(),
              !["f", "d"].contains(String(cString: number.objCType)), number.int64Value >= 0,
              number.uint64Value <= UInt64(Int.max) else { return nil }
        return number.intValue
    }
    private func publish(_ turn: Pending, scope: String) {
        if turn.admitted && turn.stored {
            pending.removeValue(forKey: turn.messageID)
            haptics.confirmed(.messageAccepted, id: turn.turnID, scope: scope)
        } else { pending[turn.messageID] = turn }
    }
    private func synchronize(_ current: String, now: Date) {
        if scope != current { scope = current; pending.removeAll() }
        pending = pending.filter { now.timeIntervalSince($0.value.started) < 120 }
    }
}
