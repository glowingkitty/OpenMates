// Native-only confirmation feedback; no private content or identifiers are logged.
// Specification: specifications/features/chats/specification.yml
// Assertions: chats.message.confirmed-haptic
// Specification: specifications/features/apple-notifications/specification.yml
// Assertions: apple-notifications.delivery.confirmed-action-haptics
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
@MainActor
final class NativeHaptics {
    enum Event: String, CaseIterable {
        case messageAccepted, taskCreated, taskUpdated, workflowCreated, workflowUpdated
        case teamCreated, authenticated, apiKeyCreated, notification
    }
    static let shared = NativeHaptics()
    private struct Key: Hashable { let event: Event; let id: String; let scope: String }
    private var delivered: Set<Key> = []
    private var order: [Key] = []
    private let enabled: @MainActor () -> Bool
    private let render: @MainActor (Event) -> Void

    init(enabled: @escaping @MainActor () -> Bool = NativeHaptics.isSupportedAndActive,
         render: @escaping @MainActor (Event) -> Void = NativeHaptics.play) {
        self.enabled = enabled; self.render = render
    }

    /// Call only after the owning operation's account/context fence succeeds.
    /// Consume even a suppressed event, so foregrounding never replays feedback.
    func confirmed(_ event: Event, id: String, scope: String) {
        guard !id.isEmpty, !scope.isEmpty else { return }
        let key = Key(event: event, id: id, scope: scope)
        guard delivered.insert(key).inserted else { return }
        order.append(key)
        if order.count > 512 { delivered.remove(order.removeFirst()) }
        guard enabled() else { return }
        render(event)
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

    private static func play(_ event: Event) {
        #if os(iOS)
        switch event {
        case .messageAccepted: UIImpactFeedbackGenerator(style: .light).impactOccurred()
        case .taskCreated: UIImpactFeedbackGenerator(style: .medium).impactOccurred()
        case .taskUpdated: UISelectionFeedbackGenerator().selectionChanged()
        case .workflowCreated: UIImpactFeedbackGenerator(style: .rigid).impactOccurred()
        case .workflowUpdated: UIImpactFeedbackGenerator(style: .soft).impactOccurred()
        case .teamCreated: UIImpactFeedbackGenerator(style: .heavy).impactOccurred()
        case .authenticated: UINotificationFeedbackGenerator().notificationOccurred(.success)
        case .apiKeyCreated: UIImpactFeedbackGenerator(style: .medium).impactOccurred(intensity: 0.7)
        case .notification: UIImpactFeedbackGenerator(style: .soft).impactOccurred(intensity: 0.5)
        }
        #elseif os(macOS)
        // Apple's AppKit guidance limits trackpad feedback to user actions.
        guard event != .notification else { return }
        let pattern: NSHapticFeedbackManager.FeedbackPattern
        switch event {
        case .taskUpdated, .workflowUpdated: pattern = .levelChange
        default: pattern = .generic
        }
        NSHapticFeedbackManager.defaultPerformer.perform(pattern, performanceTime: .now)
        #elseif os(watchOS)
        let pattern: WKHapticType
        switch event {
        case .messageAccepted: pattern = .start
        case .taskCreated: pattern = .success
        case .taskUpdated: pattern = .click
        case .workflowCreated: pattern = .directionUp
        case .workflowUpdated: pattern = .directionDown
        case .teamCreated: pattern = .success
        case .authenticated: pattern = .success
        case .apiKeyCreated: pattern = .success
        case .notification: pattern = .notification
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
