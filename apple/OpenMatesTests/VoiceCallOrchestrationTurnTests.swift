// Specification: specifications/features/video-call/specification.yml
import XCTest
@testable import OpenMates

final class VoiceCallOrchestrationTurnTests: XCTestCase {
    // contract-test: supporting surface=gui.apple assertions=video-call.chat.orchestration-continuity
    func testAcceptsOnlyMatchingCallAndValidIdentity() {
        var turns = NativeVoiceCallOrchestrationTurns()
        turns.accept(callID: "call-1", frameCallID: "call-1", messageID: "event-2")
        turns.accept(callID: "call-1", frameCallID: "other", messageID: "event-3")
        turns.accept(callID: "call-1", frameCallID: "call-1", messageID: "")
        turns.accept(callID: "call-1", frameCallID: "call-1", messageID: String(repeating: "a", count: 129))
        turns.accept(callID: "call-1", frameCallID: "call-1", messageID: nil)
        XCTAssertEqual(turns.messageIDs, ["event-2"])
        XCTAssertTrue(turns.contains("event-2"))
        turns.removeAll()
        XCTAssertFalse(turns.contains("event-2"))
    }
}
