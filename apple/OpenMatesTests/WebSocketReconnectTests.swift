import XCTest
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

}
