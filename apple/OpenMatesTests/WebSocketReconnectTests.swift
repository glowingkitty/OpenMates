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
}
