import XCTest
@testable import OpenMates

@MainActor
final class ProjectWorkspaceReviewRuntimeTests: XCTestCase {
    // contract-test: supporting surface=gui.apple assertions=projects.files.write-policy-enforcement
    func testForegroundOwnerAndChatControlReviewAuthority() {
        let runtime = ProjectWorkspaceReviewRuntime()
        let socket = WebSocketManager() // Deliberately never connected.
        let firstOwner = UUID()
        let secondOwner = UUID()

        runtime.activate(accountID: "fixture-account", chatID: "chat-a", ownerID: firstOwner, socket: socket)
        XCTAssertTrue(runtime.isActive(ownerID: firstOwner, chatID: "chat-a"))
        XCTAssertFalse(runtime.isActive(ownerID: firstOwner, chatID: "chat-b"))
        XCTAssertFalse(runtime.isActive(ownerID: secondOwner, chatID: "chat-a"))

        runtime.activate(accountID: "fixture-account", chatID: "chat-b", ownerID: secondOwner, socket: socket)
        XCTAssertFalse(runtime.isActive(ownerID: firstOwner, chatID: "chat-a"))
        XCTAssertTrue(runtime.isActive(ownerID: secondOwner, chatID: "chat-b"))

        runtime.deactivate(ownerID: firstOwner)
        XCTAssertTrue(runtime.isActive(ownerID: secondOwner, chatID: "chat-b"),
                      "A resigned window must not revoke the new foreground owner's authority")
        runtime.deactivate(ownerID: secondOwner)
        XCTAssertFalse(runtime.isActive(ownerID: secondOwner, chatID: "chat-b"))
    }

    // contract-test: supporting surface=gui.apple assertions=projects.access.explicit-context
    func testEmptyAccountNeverAcquiresReviewAuthority() {
        let runtime = ProjectWorkspaceReviewRuntime()
        let socket = WebSocketManager()
        let owner = UUID()

        runtime.activate(accountID: "", chatID: "chat-a", ownerID: owner, socket: socket)
        XCTAssertNil(runtime.accountID)
        XCTAssertFalse(runtime.isActive(ownerID: owner, chatID: "chat-a"))

        runtime.activate(accountID: "fixture-account", chatID: "chat-a", ownerID: owner, socket: socket)
        XCTAssertTrue(runtime.isActive(ownerID: owner, chatID: "chat-a"))
        runtime.reset()
        XCTAssertNil(runtime.accountID)
        XCTAssertFalse(runtime.isActive(ownerID: owner, chatID: "chat-a"))
    }

    // contract-test: supporting surface=gui.apple assertions=projects.access.explicit-context,code-run.remote.managed-jobs
    func testReplacingSocketInvalidatesQueuedOldTransportAndRejectsItsFrames() throws {
        let runtime = ProjectWorkspaceReviewRuntime()
        let oldSocket = WebSocketManager()
        let newSocket = WebSocketManager()
        let owner = UUID()
        runtime.activate(accountID: "fixture-account", chatID: "chat-a", ownerID: owner, socket: oldSocket)

        runtime.receive(type: "remote_command_error", fields: [:], from: oldSocket)
        XCTAssertEqual(try pendingCount(runtime), 1)

        runtime.activate(accountID: "fixture-account", chatID: "chat-a", ownerID: owner, socket: newSocket)
        XCTAssertEqual(try pendingCount(runtime), 0, "Socket replacement must clear the old queue")
        runtime.receive(type: "remote_command_error", fields: [:], from: oldSocket)
        XCTAssertEqual(try pendingCount(runtime), 0, "Old socket frames must be rejected")
        runtime.receive(type: "remote_command_error", fields: [:], from: newSocket)
        XCTAssertEqual(try pendingCount(runtime), 1, "The replacement socket retains inbound authority")
        runtime.reset()
    }

    // contract-test: supporting surface=gui.apple assertions=code-run.output.bounded-delivery,code-run.execution.stream-status-visible
    func testBackpressureKeepsTerminalAndAcknowledgementEvents() {
        XCTAssertTrue(ProjectWorkspaceReviewRuntime.acceptsInbound(
            type: "remote_command_event", eventKind: "output", pendingCount: 127))
        XCTAssertFalse(ProjectWorkspaceReviewRuntime.acceptsInbound(
            type: "remote_command_event", eventKind: "output", pendingCount: 128))
        XCTAssertFalse(ProjectWorkspaceReviewRuntime.acceptsInbound(
            type: "project_file_operation_request", eventKind: nil, pendingCount: 128))
        XCTAssertTrue(ProjectWorkspaceReviewRuntime.acceptsInbound(
            type: "remote_command_event", eventKind: "terminal", pendingCount: 512))
        for kind in ["remote_command_prepared", "remote_command_rejected", "remote_command_stop_ack",
                     "remote_command_origin_completion_ack", "remote_command_error"] {
            XCTAssertTrue(ProjectWorkspaceReviewRuntime.acceptsInbound(
                type: kind, eventKind: nil, pendingCount: 512), "Dropped acknowledgement: \(kind)")
        }
    }

    private func pendingCount(_ runtime: ProjectWorkspaceReviewRuntime) throws -> Int {
        // The count is private; inspection lets this test observe synchronous
        // queue admission without connecting a socket or using a real account.
        try XCTUnwrap(Mirror(reflecting: runtime).descendant("pendingInboundCount") as? Int)
    }
}
