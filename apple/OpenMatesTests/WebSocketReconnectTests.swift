import XCTest
#if os(iOS)
import UIKit
#elseif os(macOS)
import AppKit
#endif
@testable import OpenMates

@MainActor
final class WebSocketReconnectTests: XCTestCase {
    // contract-test: supporting surface=gui.apple assertions=sync.surface.semantic-parity
    func testFailedHandshakesExhaustTenRetriesInsteadOfResettingDuringConnecting() async {
        let manager = WebSocketManager()
        manager.debugReconnectDelay = 0
        var count = 0
        var nextAttempt: XCTestExpectation?
        manager.debugConnectionAttempt = {
            count += 1
            nextAttempt?.fulfill()
        }
        manager.connect(sessionId: "synthetic-session", token: nil)
        XCTAssertEqual(count, 1)
        for attempt in 1...10 {
            nextAttempt = expectation(description: "retry \(attempt) starts")
            manager.debugFailCurrentConnection()
            XCTAssertEqual(manager.connectionState, .reconnecting(attempt: attempt))
            await fulfillment(of: [nextAttempt!], timeout: 1)
            XCTAssertEqual(manager.connectionState, .connecting)
        }
        nextAttempt = expectation(description: "no eleventh retry")
        nextAttempt!.isInverted = true
        manager.debugFailCurrentConnection()
        XCTAssertEqual(manager.connectionState, .disconnected)
        await fulfillment(of: [nextAttempt!], timeout: 0.05)
        XCTAssertEqual(count, 11)
        manager.disconnect()
    }

    // contract-test: supporting surface=gui.apple assertions=auth.session.lifecycle,sync.surface.semantic-parity
    func testFreshRecoveryTokensDoNotResetFailedHandshakeRetryBudget() async {
        let manager = WebSocketManager()
        manager.debugReconnectDelay = 0
        var validations = 0
        var attempts = 0
        var nextAttempt: XCTestExpectation?
        manager.debugConnectionAttempt = { attempts += 1; nextAttempt?.fulfill() }
        manager.configureSessionRecovery {
            validations += 1
            return .authenticated(sessionID: "synthetic-session", token: "rotated-token-\(validations)")
        }
        manager.connect(sessionId: "synthetic-session", token: "initial-token")
        for attempt in 1...10 {
            nextAttempt = expectation(description: "retry \(attempt) with a fresh token")
            manager.debugFailCurrentConnection(authenticationRejected: true)
            XCTAssertEqual(manager.connectionState, .reconnecting(attempt: attempt))
            await fulfillment(of: [nextAttempt!], timeout: 1)
            XCTAssertEqual(manager.debugCurrentAuthToken, "rotated-token-\(attempt)")
        }
        nextAttempt = expectation(description: "no retry after ten freshly authenticated failures")
        nextAttempt!.isInverted = true
        manager.debugFailCurrentConnection(authenticationRejected: true)
        XCTAssertEqual(manager.connectionState, .disconnected)
        await fulfillment(of: [nextAttempt!], timeout: 0.05)
        XCTAssertEqual(validations, 10)
        XCTAssertEqual(attempts, 11)
        manager.disconnect()
    }

    // contract-test: supporting surface=gui.apple assertions=sync.surface.semantic-parity
    func testExplicitDisconnectCancelsDelayedRetry() async {
        let manager = WebSocketManager()
        manager.debugReconnectDelay = 0.03
        let cancelled = expectation(description: "cancelled retry never starts")
        cancelled.isInverted = true
        var attempts = 0
        manager.debugConnectionAttempt = {
            attempts += 1
            if attempts > 1 { cancelled.fulfill() }
        }
        manager.connect(sessionId: "synthetic-session", token: nil)
        manager.debugFailCurrentConnection()
        manager.disconnect()
        await fulfillment(of: [cancelled], timeout: 0.08)
        XCTAssertEqual(manager.connectionState, .disconnected)
        XCTAssertEqual(attempts, 1)
    }
    // contract-test: supporting surface=gui.apple assertions=auth.session.lifecycle
    func testRejectedTransportWaitsForValidationThenUsesRotatedCredentials() async {
        let manager = WebSocketManager()
        manager.debugReconnectDelay = 0
        var pending: CheckedContinuation<WebSocketManager.SessionRecoveryResult, Never>?
        var attempts = 0
        let recovered = expectation(description: "rotated connection starts")
        manager.debugConnectionAttempt = {
            attempts += 1
            if attempts == 2 { recovered.fulfill() }
        }
        manager.configureSessionRecovery {
            await withCheckedContinuation { pending = $0 }
        }
        manager.connect(sessionId: "synthetic-session", token: "old-token")
        manager.debugFailCurrentConnection(authenticationRejected: true)
        while pending == nil { await Task.yield() }
        XCTAssertEqual(attempts, 1, "Rejected credentials must not be retried during validation")
        pending?.resume(returning: .authenticated(sessionID: "synthetic-session", token: "rotated-token"))
        await fulfillment(of: [recovered], timeout: 1)
        XCTAssertEqual(manager.debugCurrentAuthToken, "rotated-token")
        manager.disconnect()
    }

    // contract-test: supporting surface=gui.apple assertions=auth.session.authoritative-enforcement
    func testGenuinelyRejectedSessionStopsSocketRetries() async {
        let manager = WebSocketManager()
        manager.debugReconnectDelay = 0
        let validated = expectation(description: "session rejection handled")
        var attempts = 0
        manager.debugConnectionAttempt = { attempts += 1 }
        manager.configureSessionRecovery { validated.fulfill(); return .rejected }
        manager.connect(sessionId: "synthetic-session", token: "expired-token")
        manager.debugFailCurrentConnection(authenticationRejected: true)
        await fulfillment(of: [validated], timeout: 1)
        await Task.yield()
        XCTAssertEqual(manager.connectionState, .disconnected)
        XCTAssertEqual(attempts, 1)
        XCTAssertNil(manager.debugCurrentAuthToken)
    }

    // contract-test: supporting surface=gui.apple assertions=auth.session.isolation
    func testDisconnectFencesLateSuccessfulRecovery() async {
        let manager = WebSocketManager()
        manager.debugReconnectDelay = 0
        var pending: CheckedContinuation<WebSocketManager.SessionRecoveryResult, Never>?
        var attempts = 0
        manager.debugConnectionAttempt = { attempts += 1 }
        manager.configureSessionRecovery { await withCheckedContinuation { pending = $0 } }
        manager.connect(sessionId: "old-session", token: "old-token")
        manager.debugFailCurrentConnection(authenticationRejected: true)
        while pending == nil { await Task.yield() }
        manager.disconnect()
        manager.connect(sessionId: "replacement-session", token: "replacement-token")
        pending?.resume(returning: .authenticated(sessionID: "old-session", token: "late-old-token"))
        await Task.yield()
        XCTAssertEqual(attempts, 2)
        XCTAssertEqual(manager.debugCurrentAuthToken, "replacement-token")
        manager.disconnect()
    }

    // contract-test: supporting surface=gui.apple assertions=auth.session.authoritative-enforcement
    func testTemporaryValidationFailureRetriesValidationWithoutReusingRejectedToken() async {
        let manager = WebSocketManager()
        manager.debugReconnectDelay = 0
        var validations = 0
        var attempts = 0
        let recovered = expectation(description: "retry after transient validation failure")
        manager.debugConnectionAttempt = { attempts += 1; if attempts == 2 { recovered.fulfill() } }
        manager.configureSessionRecovery {
            validations += 1
            return validations == 1 ? .unavailable : .authenticated(sessionID: "synthetic-session", token: "new-token")
        }
        manager.connect(sessionId: "synthetic-session", token: "rejected-token")
        manager.debugFailCurrentConnection(authenticationRejected: true)
        await fulfillment(of: [recovered], timeout: 1)
        XCTAssertEqual(validations, 2)
        XCTAssertEqual(attempts, 2)
        XCTAssertEqual(manager.debugCurrentAuthToken, "new-token")
        manager.disconnect()
    }

    // contract-test: supporting surface=gui.apple assertions=sync.surface.semantic-parity
    func testPingTimerFiresDuringUITracking() async {
        let manager = WebSocketManager()
        manager.debugConnectionAttempt = {}
        let sent = expectation(description: "ping fires during UI tracking")
        var sentCount = 0
        manager.debugPingSender = { completion in
            sentCount += 1
            if sentCount == 1 { sent.fulfill() }
            completion(nil)
        }
        manager.connect(sessionId: "synthetic-session", token: nil)
        manager.debugStartPingTimer(interval: 0.005)
        runTrackingLoop(for: 0.03)
        manager.debugPingTimer?.invalidate()
        // Delivery may need its MainActor hop after tracking ends, but the timer
        // must have queued it without a pass through the default run-loop mode.
        await fulfillment(of: [sent], timeout: 1)
        manager.disconnect()
        XCTAssertGreaterThan(sentCount, 0)
    }

    // contract-test: supporting surface=gui.apple assertions=auth.session.isolation,sync.surface.semantic-parity
    func testQueuedTimerFireCannotPingAReplacementConnection() async {
        let manager = WebSocketManager()
        manager.debugConnectionAttempt = {}
        var sentCount = 0
        manager.debugPingSender = { completion in sentCount += 1; completion(nil) }
        manager.connect(sessionId: "old-session", token: nil)
        manager.debugStartPingTimer(interval: 25)
        manager.debugPingTimer?.fire()
        // The old timer already queued its MainActor work when it is invalidated.
        manager.disconnect()
        manager.connect(sessionId: "replacement-session", token: nil)
        await Task.yield()
        XCTAssertEqual(sentCount, 0)
        XCTAssertEqual(manager.connectionState, .connecting)
        manager.disconnect()
    }

    // contract-test: supporting surface=gui.apple assertions=auth.session.isolation,sync.surface.semantic-parity
    func testLatePingFailureCannotDisconnectAReplacementConnection() async {
        let manager = WebSocketManager()
        manager.debugConnectionAttempt = {}
        let sent = expectation(description: "old socket ping sent")
        var completion: (@Sendable (Error?) -> Void)?
        manager.debugPingSender = { callback in completion = callback; sent.fulfill() }
        manager.connect(sessionId: "old-session", token: nil)
        manager.debugStartPingTimer(interval: 25)
        manager.debugPingTimer?.fire()
        await fulfillment(of: [sent], timeout: 1)
        manager.disconnect()
        manager.connect(sessionId: "replacement-session", token: nil)
        completion?(NSError(domain: NSURLErrorDomain, code: NSURLErrorNetworkConnectionLost))
        await Task.yield()
        XCTAssertEqual(manager.connectionState, .connecting)
        manager.disconnect()
    }

    // contract-test: supporting surface=gui.apple assertions=sync.surface.semantic-parity
    func testPingDiagnosticsReportOnlyScalarsFromPrivateError() async {
        NativeClientLogCollector.shared.resetForTests()
        let manager = WebSocketManager()
        manager.debugConnectionAttempt = {}
        manager.debugReconnectDelay = 30
        let sent = expectation(description: "ping completion delivered")
        let privateValue = "PRIVATE_SOCKET_DETAIL_CANARY"
        manager.debugPingSender = { completion in
            completion(NSError(domain: privateValue, code: 73,
                               userInfo: [NSLocalizedDescriptionKey: privateValue]))
            sent.fulfill()
        }
        manager.connect(sessionId: privateValue, token: privateValue)
        manager.debugStartPingTimer(interval: 25)
        manager.debugPingTimer?.fire()
        await fulfillment(of: [sent], timeout: 1)
        await Task.yield()
        let messages = NativeClientLogCollector.shared.entriesSnapshot(limit: 200).map(\.message)
        XCTAssertTrue(messages.contains { $0.contains("event=socket_ping_failed") && $0.contains("error_code=73") && $0.contains("error_domain_class=0") })
        XCTAssertFalse(messages.contains { $0.contains(privateValue) })
        XCTAssertEqual(manager.connectionState, .reconnecting(attempt: 1))
        manager.disconnect()
    }

    // contract-test: supporting surface=gui.apple assertions=sync.surface.semantic-parity
    func testMonotonicDiagnosticsKeepCadenceAndDrainBoundedSamples() {
        var timings = WebSocketTimingWindow()
        timings.startPingSchedule(at: 100, interval: 25)
        XCTAssertEqual(timings.pingScheduleDrift(at: 180), 55_000)
        XCTAssertEqual(timings.pingScheduleDrift(at: 200.125), 125)
        timings.recordCallback(at: 210, deliveredAt: 210.02)
        timings.recordCallback(at: 211, deliveredAt: 211.09)
        timings.recordReceive(routingMilliseconds: 12)
        timings.recordReceive(routingMilliseconds: 3)
        timings.recordSyncEvent()
        let counts = timings.takeWindowCounts()
        XCTAssertEqual(counts["callback_count"], 2)
        XCTAssertEqual(counts["callback_main_delay_max_ms"], 90)
        XCTAssertEqual(counts["received_count"], 2)
        XCTAssertEqual(counts["receive_routing_total_ms"], 15)
        XCTAssertEqual(counts["sync_event_count"], 1)
        XCTAssertTrue(timings.takeWindowCounts().values.allSatisfy { $0 == 0 })
        XCTAssertEqual(WebSocketTimingWindow.errorDomainClass(NSURLErrorDomain), 1)
        XCTAssertEqual(WebSocketTimingWindow.errorDomainClass("private-domain"), 0)
    }

    private func runTrackingLoop(for duration: TimeInterval) {
        #if os(iOS)
        let mode = RunLoop.Mode.tracking
        #elseif os(macOS)
        let mode = RunLoop.Mode.eventTracking
        #else
        let mode = RunLoop.Mode.common
        #endif
        let deadline = Date(timeIntervalSinceNow: duration)
        while Date() < deadline {
            RunLoop.main.run(mode: mode, before: deadline)
        }
    }

}
