// Specification: specifications/features/video-call/specification.yml
// Assertions: video-call.chat.fixed-binding, video-call.chat.skill-integration,
// video-call.privacy, video-call.lifecycle.recovery-and-billing
import XCTest
@testable import OpenMates

@MainActor
final class NativeVoiceCallToolContinuationTests: XCTestCase {
    // contract-test: supporting surface=gui.apple assertions=video-call.chat.fixed-binding,video-call.privacy
    func testMemoryReplyRequiresExactRequestFunctionCallAndExplicitDecision() async {
        for field in ["request_id", "function_call_id", "call_id", "type", "approved"] {
            let fixture = ContinuationFixture()
            let stopped = expectation(description: field + " mismatch stops")
            fixture.onHangup = { stopped.fulfill() }
            fixture.handler = { _, _, frame, _ in
                var reply = fixture.reply(frame)
                reply[field] = field == "approved" ? nil : .string("foreign")
                return .response(reply)
            }
            await fixture.policy.receive(fixture.frame("voice_memory"))
            await fulfillment(of: [stopped], timeout: 2)
            XCTAssertEqual(fixture.errors, [.invalidResponse]); XCTAssertTrue(fixture.responses.isEmpty)
        }
    }

    // contract-test: supporting surface=gui.apple assertions=video-call.privacy,video-call.chat.skill-integration
    func testExactExplicitMemoryDecisionReturnsOnce() async {
        let fixture = ContinuationFixture()
        let responded = expectation(description: "exact explicit decision returned")
        fixture.onRespond = { responded.fulfill() }
        fixture.handler = { _, _, frame, validate in
            try await validate()
            return .response(fixture.reply(frame))
        }
        await fixture.policy.receive(fixture.frame("voice_memory"))
        await fulfillment(of: [responded], timeout: 2)
        XCTAssertEqual(fixture.responses.count, 1); XCTAssertTrue(fixture.errors.isEmpty)
    }

    // contract-test: supporting surface=gui.apple assertions=video-call.lifecycle.recovery-and-billing,video-call.chat.skill-integration
    func testPermissionWaitDoesNotBlockEventsAndQueueRejectsSeventeenthPendingTool() async {
        let fixture = ContinuationFixture()
        let waiting = expectation(description: "permission waiting")
        let released = expectation(description: "cancelled permission resumed")
        let stopped = expectation(description: "bounded queue stops call")
        let gate = ContinuationGate()
        fixture.onHangup = { stopped.fulfill() }
        fixture.handler = { _, _, _, validate in
            waiting.fulfill(); defer { released.fulfill() }
            await gate.wait(); try await validate(); return .presented
        }
        await fixture.policy.receive(fixture.frame("voice_memory"))
        await fulfillment(of: [waiting], timeout: 2)
        for _ in 0..<16 { await fixture.policy.receive(fixture.frame("voice_tool_status")) }
        XCTAssertEqual(fixture.hangups, 0)
        await fixture.policy.receive(fixture.frame("voice_tool_status"))
        await fulfillment(of: [stopped], timeout: 2)
        gate.release()
        await fulfillment(of: [released], timeout: 2)
        XCTAssertEqual(fixture.errors, [.unsupportedTransport]); XCTAssertTrue(fixture.responses.isEmpty)
    }

    // contract-test: supporting surface=gui.apple assertions=video-call.chat.skill-integration,video-call.chat.fixed-binding
    func testSuspendedToolKeepsSubsequentEventsInBrokerOrder() async {
        let fixture = ContinuationFixture(), gate = ContinuationGate()
        let entered = expectation(description: "first tool entered")
        let completed = expectation(description: "all tools completed"); completed.expectedFulfillmentCount = 3
        var order: [Double] = []
        fixture.handler = { _, _, frame, validate in
            let sequence = frame["payload"]!.object!["sequence"]!.number!
            order.append(sequence)
            if sequence == 0 { entered.fulfill(); await gate.wait() }
            try await validate(); completed.fulfill(); return .presented
        }
        func status(_ sequence: Double) -> NativeVoiceCallFrame {
            var frame = fixture.frame("voice_tool_status")
            frame["payload"] = .object(["sequence": .number(sequence)])
            return frame
        }
        await fixture.policy.receive(status(0))
        await fulfillment(of: [entered], timeout: 2)
        await fixture.policy.receive(status(1)); await fixture.policy.receive(status(2))
        XCTAssertEqual(order, [0])
        gate.release()
        await fulfillment(of: [completed], timeout: 2)
        XCTAssertEqual(order, [0, 1, 2]); XCTAssertTrue(fixture.errors.isEmpty)
    }

    // contract-test: supporting surface=gui.apple assertions=video-call.privacy,video-call.chat.fixed-binding
    func testNormalHangupCancelsPendingMemoryWithoutBrokerDecision() async {
        let fixture = ContinuationFixture(), gate = ContinuationGate()
        let waiting = expectation(description: "memory requested"), resumed = expectation(description: "memory cancelled")
        fixture.handler = { _, _, frame, validate in
            waiting.fulfill(); defer { resumed.fulfill() }
            await gate.wait(); try await validate(); return .response(fixture.reply(frame))
        }
        await fixture.policy.receive(fixture.frame("voice_memory"))
        await fulfillment(of: [waiting], timeout: 2)
        fixture.end(); gate.release()
        await fulfillment(of: [resumed], timeout: 2)
        XCTAssertTrue(fixture.responses.isEmpty); XCTAssertTrue(fixture.errors.isEmpty)
    }

    // contract-test: supporting surface=gui.apple assertions=video-call.chat.fixed-binding,video-call.chat.skill-integration
    func testAlreadyAdmittedArtifactMayFinishItsOriginalTupleAfterNormalHangup() async {
        let fixture = ContinuationFixture(), gate = ContinuationGate()
        let admitted = expectation(description: "artifact admitted")
        var completed: [NativeVoiceCallFrame] = []
        fixture.handler = { scope, callID, frame, validate in
            XCTAssertEqual(scope, fixture.scope); XCTAssertEqual(callID, "call")
            admitted.fulfill(); await gate.wait(); try await validate()
            completed.append(frame); return .presented
        }
        let original = fixture.frame("voice_embed")
        await fixture.policy.receive(original)
        await fulfillment(of: [admitted], timeout: 2)
        fixture.end(); gate.release()
        await fixture.policy.finishAdmittedArtifacts()
        XCTAssertEqual(completed, [original]); XCTAssertTrue(fixture.responses.isEmpty); XCTAssertTrue(fixture.errors.isEmpty)
    }

    // contract-test: supporting surface=gui.apple assertions=video-call.chat.fixed-binding,video-call.privacy
    func testOwnerLossAndReplacementRevokeSuspendedArtifactCompletion() async {
        for replace in [false, true] {
            let fixture = ContinuationFixture(), gate = ContinuationGate()
            let admitted = expectation(description: "artifact admitted"), resumed = expectation(description: "revoked artifact resumed")
            var completions = 0
            fixture.handler = { _, _, _, validate in
                admitted.fulfill(); defer { resumed.fulfill() }
                await gate.wait(); try await validate(); completions += 1; return .presented
            }
            await fixture.policy.receive(fixture.frame("voice_embed"))
            await fulfillment(of: [admitted], timeout: 2)
            if replace { fixture.policy.update(.init(status: .live, scope: fixture.scope, callID: "replacement")) }
            else { fixture.policy.invalidateOwner() }
            gate.release()
            await fulfillment(of: [resumed], timeout: 2)
            XCTAssertEqual(completions, 0); XCTAssertTrue(fixture.responses.isEmpty); XCTAssertTrue(fixture.errors.isEmpty)
        }
    }
}

@MainActor
private final class ContinuationGate {
    private var continuation: CheckedContinuation<Void, Never>?
    func wait() async { await withCheckedContinuation { continuation = $0 } }
    func release() { continuation?.resume(); continuation = nil }
}

@MainActor
private final class ContinuationFixture {
    let scope = NativeVoiceCallScope(accountID: "owner", profileID: "development", workspaceGeneration: UUID(),
        chatID: UUID().uuidString, mateCategory: "general_knowledge")
    var handler: NativeVoiceCallToolContinuation.Handler = { _, _, _, _ in .unsupported }
    var responses: [NativeVoiceCallFrame] = []
    var errors: [NativeVoiceCallError] = []
    var hangups = 0
    var onHangup: (() -> Void)?
    var onRespond: (() -> Void)?
    lazy var policy: NativeVoiceCallToolContinuation = {
        let value = NativeVoiceCallToolContinuation(handler: { [weak self] scope, callID, frame, validate in
            guard let self else { throw NativeVoiceCallError.scopeChanged }
            return try await handler(scope, callID, frame, validate)
        }, respond: { [weak self] response in self?.responses.append(response); self?.onRespond?() },
           fail: { [weak self] error in self?.errors.append(error) }, hangup: { [weak self] in
               self?.hangups += 1; self?.end(); self?.onHangup?()
           })
        value.update(.init(status: .live, scope: scope, callID: "call")); return value
    }()
    func end() { policy.update(.init(status: .ended, scope: scope, callID: "call")) }
    func frame(_ kind: String) -> NativeVoiceCallFrame {
        ["type": .string(kind), "call_id": .string("call"), "function_call_id": .string("function"),
         "assistant_message_id": .string("assistant"), "user_message_id": .string("user"),
         "payload": .object(["chat_id": .string(scope.chatID), "request_id": .string("request")])]
    }
    func reply(_ frame: NativeVoiceCallFrame) -> NativeVoiceCallFrame {
        ["type": .string("voice_memory_response"), "call_id": frame["call_id"]!,
         "function_call_id": frame["function_call_id"]!, "request_id": frame["payload"]!.object!["request_id"]!,
         "approved": .bool(false), "settings_memories": .array([])]
    }
}
