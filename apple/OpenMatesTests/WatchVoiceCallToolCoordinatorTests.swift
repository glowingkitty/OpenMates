// Specification: specifications/features/video-call/specification.yml
// Assertions: video-call.chat.fixed-binding, video-call.chat.skill-integration,
// video-call.privacy, video-call.lifecycle.recovery-and-billing
// Specification: specifications/features/apple-watch/specification.yml
// Assertions: apple-watch.chats.input-actions
import XCTest
import Combine
@testable import OpenMates

@MainActor
final class WatchVoiceCallToolCoordinatorTests: XCTestCase {
    private let scope = NativeVoiceCallScope(accountID: "owner", profileID: "development", workspaceGeneration: UUID(),
        chatID: UUID().uuidString, mateCategory: "general_knowledge")
    private func frame(_ kind: String, callID: String = "call") -> NativeVoiceCallFrame {
        ["type": .string(kind), "call_id": .string(callID), "payload": .object([:])]
    }
    // contract-test: supporting surface=gui.apple assertions=video-call.chat.skill-integration,video-call.lifecycle.recovery-and-billing,apple-watch.chats.input-actions
    func testUnsupportedFocusIsVisibleAndTerminatesWithoutMemoryApproval() async {
        let coordinator = WatchVoiceCallToolCoordinator()
        let stopped = expectation(description: "unsupported focus ended")
        var responses = 0, adapterCalls = 0
        coordinator.bind(artifacts: { _, _, _, _ in adapterCalls += 1; return .presented },
            memory: { _, _, _, _ in adapterCalls += 1; return .presented },
            respond: { _ in responses += 1 }, hangup: { stopped.fulfill() }, invalidateMemory: {})
        await coordinator.receive(.state(.init(status: .live, scope: scope, callID: "call")))
        await coordinator.receive(.tool(frame("voice_focus")))
        await fulfillment(of: [stopped], timeout: 2)
        XCTAssertEqual(coordinator.integrationError, .unsupportedTransport)
        XCTAssertEqual(responses, 0); XCTAssertEqual(adapterCalls, 0)
    }
    // contract-test: supporting surface=gui.apple assertions=video-call.chat.fixed-binding,video-call.privacy,apple-watch.chats.input-actions
    func testForeignCallOrChatNeverReachesAnAdapterAndFailsVisibly() async {
        for foreignChat in [false, true] {
            let coordinator = WatchVoiceCallToolCoordinator()
            let stopped = expectation(description: "foreign tool ended")
            var adapterCalls = 0
            coordinator.bind(artifacts: { _, _, _, _ in adapterCalls += 1; return .presented },
                memory: { _, _, _, _ in adapterCalls += 1; return .presented }, respond: { _ in XCTFail("fabricated response") },
                hangup: { stopped.fulfill() }, invalidateMemory: {})
            await coordinator.receive(.state(.init(status: .live, scope: scope, callID: "call")))
            var tool = frame("voice_tool_status", callID: foreignChat ? "call" : "foreign")
            if foreignChat { tool["payload"] = .object(["chat_id": .string("foreign")]) }
            await coordinator.receive(.tool(tool))
            await fulfillment(of: [stopped], timeout: 2)
            XCTAssertEqual(coordinator.integrationError, .invalidResponse); XCTAssertFalse(coordinator.toolWorking)
            XCTAssertEqual(adapterCalls, 0)
        }
    }
    // contract-test: supporting surface=gui.apple assertions=video-call.chat.skill-integration,video-call.privacy,apple-watch.chats.input-actions
    func testActualToolStatusRendersAndOwnerTeardownClearsItAndMemory() async {
        let coordinator = WatchVoiceCallToolCoordinator()
        var invalidations = 0
        coordinator.bind(artifacts: { _, _, _, _ in .unsupported }, memory: { _, _, _, _ in .unsupported },
            respond: { _ in XCTFail("status is not a permission") }, hangup: { XCTFail("valid status") },
            invalidateMemory: { invalidations += 1 })
        let shown = expectation(description: "status rendered")
        let subscription = coordinator.$toolWorking.dropFirst().filter { $0 }.prefix(1).sink { _ in shown.fulfill() }
        defer { subscription.cancel() }
        await coordinator.receive(.state(.init(status: .live, scope: scope, callID: "call")))
        XCTAssertFalse(coordinator.toolWorking)
        await coordinator.receive(.tool(frame("voice_tool_status")))
        await fulfillment(of: [shown], timeout: 2)
        XCTAssertTrue(coordinator.toolWorking)
        coordinator.invalidateOwner()
        XCTAssertFalse(coordinator.toolWorking); XCTAssertEqual(invalidations, 1)
        await coordinator.receive(.tool(frame("voice_tool_status")))
        XCTAssertFalse(coordinator.toolWorking)
    }
    // contract-test: supporting surface=gui.apple assertions=video-call.chat.fixed-binding,video-call.privacy,apple-watch.chats.input-actions
    func testEvaluationProjectionRejectsStaleOrdinaryTeardownAndNeverEnablesProductStart() {
        let ordinary = UUID(), evaluation = UUID(), replacement = UUID()
        var ownership = WatchVoiceCallProjectionOwnership()
        XCTAssertTrue(ownership.claim(ordinary, replacingIdle: false, audioOwned: false))
        XCTAssertTrue(ownership.claim(evaluation, replacingIdle: true, audioOwned: false))
        XCTAssertFalse(ownership.claim(ordinary, replacingIdle: false, audioOwned: false))
        XCTAssertFalse(ownership.release(ordinary)); XCTAssertTrue(ownership.isCurrent(evaluation))
        XCTAssertFalse(ownership.claim(replacement, replacingIdle: true, audioOwned: true))
        for phase in [WatchCallActionProjection.Phase.live, .ended, .failed, .unavailable] {
            XCTAssertFalse(WatchCallActionProjection(phase: phase, physicalRouteVerified: false).canStart)
        }
        XCTAssertTrue(ownership.release(evaluation)); XCTAssertFalse(ownership.release(evaluation))
        XCTAssertTrue(ownership.claim(ordinary, replacingIdle: false, audioOwned: false))
    }
}
