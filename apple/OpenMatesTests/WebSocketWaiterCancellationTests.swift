import XCTest
@testable import OpenMates

@MainActor
final class WebSocketWaiterCancellationTests: XCTestCase {
    // contract-test: supporting surface=gui.apple assertions=projects.access.explicit-context
    func testCallerCancellationStopsSuspendedSendBeforeCommit() async {
        let manager = WebSocketManager()
        let entered = expectation(description: "send entered preflight")
        let stopped = expectation(description: "cancellation reaches preflight")
        var didCommit = false
        let operation = Task {
            try await manager.awaitMessage(responseTypes: ["commit_embed_revision_result"],
                timeout: .seconds(20), matching: { _ in true }) {
                entered.fulfill()
                do { try await Task.sleep(for: .seconds(20)) }
                catch { stopped.fulfill(); throw error }
                didCommit = true
            }
        }
        await fulfillment(of: [entered], timeout: 2)
        operation.cancel()
        do { _ = try await operation.value; XCTFail("Cancelled commit must not complete") }
        catch { XCTAssertTrue(error is CancellationError) }
        await fulfillment(of: [stopped], timeout: 2)
        XCTAssertFalse(didCommit)
    }

    // contract-test: supporting surface=gui.apple assertions=projects.access.explicit-context
    func testAlreadyCancelledCallerDoesNotRegisterOrSend() async {
        let manager = WebSocketManager()
        var didSend = false
        let operation = Task {
            withUnsafeCurrentTask { $0?.cancel() }
            return try await manager.awaitMessage(responseTypes: ["result"], timeout: .seconds(20),
                matching: { _ in true }) { didSend = true }
        }
        do { _ = try await operation.value; XCTFail("Expected cancellation") }
        catch { XCTAssertTrue(error is CancellationError) }
        XCTAssertFalse(didSend)
    }
}
