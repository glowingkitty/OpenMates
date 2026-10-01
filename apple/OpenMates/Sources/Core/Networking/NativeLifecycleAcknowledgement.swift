// Bounded background lifecycle delivery, preserving account and socket identity.
// Specification: specifications/features/apple-notifications/specification.yml
// Assertions: apple-notifications.delivery.idempotent-visible

import Foundation
import SwiftUI

struct NativeLifecycleDeliveryContext: Equatable {
    let accountID: String
    let profile: ServerProfile
    let scope: UUID
    let socketGeneration: Int
    let scene: ScenePhase
    let applicationIsBackground: Bool

    func matchesSession(_ current: Self) -> Bool {
        accountID == current.accountID && profile == current.profile && scope == current.scope &&
            socketGeneration == current.socketGeneration
    }

    func canDisconnect(_ current: Self?) -> Bool {
        guard let current else { return false }
        return scene != .active && current.scene == .background && current.applicationIsBackground &&
            matchesSession(current)
    }
}

@MainActor
final class NativeLifecycleAcknowledgementAttempt {
    private let captured: NativeLifecycleDeliveryContext
    private let current: @MainActor () -> NativeLifecycleDeliveryContext?
    private let disconnect: @MainActor () -> Void
    private var endBackgroundExecution: (@MainActor () -> Void)?
    private var requestTask: Task<Void, Never>?
    private var finished = false

    init(captured: NativeLifecycleDeliveryContext,
         current: @escaping @MainActor () -> NativeLifecycleDeliveryContext?,
         disconnect: @escaping @MainActor () -> Void) {
        self.captured = captured
        self.current = current
        self.disconnect = disconnect
    }

    func attachBackgroundExecutionEnd(_ end: @escaping @MainActor () -> Void) {
        if finished { end() } else { endBackgroundExecution = end }
    }

    func waitForAcknowledgement(_ send: @escaping @MainActor () async throws -> Void) async {
        guard !finished else { return }
        let task = Task { @MainActor in
            do {
                try Task.checkCancellation()
                try await send()
                self.finish()
            } catch {
                self.expire()
            }
        }
        requestTask = task
        await task.value
    }

    /// Timeout or OS expiration must stop the same unacknowledged background
    /// transport. Foreground return, new account, and replacement sockets fence it.
    func expire() {
        guard !finished else { return }
        requestTask?.cancel()
        if captured.canDisconnect(current()) { disconnect() }
        finish()
    }

    func cancel() {
        requestTask?.cancel()
        finish()
    }

    private func finish() {
        guard !finished else { return }
        finished = true
        let end = endBackgroundExecution
        endBackgroundExecution = nil
        end?()
    }
}

/// All windows share one socket; a newer lifecycle transition cancels the old
/// acknowledgement lifetime before it can close that socket or end its lease.
@MainActor
final class NativeLifecycleAcknowledgementCoordinator {
    static let shared = NativeLifecycleAcknowledgementCoordinator()
    private var attempt: NativeLifecycleAcknowledgementAttempt?

    func cancelPending() {
        attempt?.cancel()
        attempt = nil
    }

    func begin(captured: NativeLifecycleDeliveryContext,
               current: @escaping @MainActor () -> NativeLifecycleDeliveryContext?,
               disconnect: @escaping @MainActor () -> Void) -> NativeLifecycleAcknowledgementAttempt {
        cancelPending()
        let next = NativeLifecycleAcknowledgementAttempt(captured: captured, current: current, disconnect: disconnect)
        attempt = next
        return next
    }
}
