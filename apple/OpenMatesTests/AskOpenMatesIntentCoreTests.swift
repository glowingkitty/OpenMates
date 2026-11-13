// Tests of the "Ask OpenMates" intent's mapping from the core's turn end to the shortcut result.
// The send itself runs in the core (`CoreChatActions`); its behaviour is covered by the crate tests.
// Specification: specifications/features/chats/specification.yml
// Assertions: chats.send.immediate-admission
import XCTest
@testable import OpenMates

@MainActor
final class AskOpenMatesIntentCoreTests: XCTestCase {
    // contract-test: supporting surface=gui.apple assertions=chats.send.immediate-admission
    func testCompletedTurnReturnsTheCoreReply() {
        let end = CoreTurnEnd(outcome: .completed, wasAccepted: true, receipt: nil, replyText: "Use a 3 mm bit.")
        XCTAssertEqual(AskOpenMatesIntent.result(forEnd: end), "Use a 3 mm bit.")
    }

    // contract-test: supporting surface=gui.apple assertions=chats.send.immediate-admission
    func testCompletedTurnWithoutReplyOrNoEndPointsToTheApp() {
        let empty = CoreTurnEnd(outcome: .completed, wasAccepted: true, receipt: nil, replyText: nil)
        XCTAssertEqual(AskOpenMatesIntent.result(forEnd: empty), AskOpenMatesIntent.Message.stillProcessing)
        XCTAssertEqual(AskOpenMatesIntent.result(forEnd: nil), AskOpenMatesIntent.Message.stillProcessing)
    }

    // contract-test: supporting surface=gui.apple assertions=chats.send.immediate-admission
    func testRefusalsMapToUserFacingMessages() {
        XCTAssertNil(AskOpenMatesIntent.result(forRefusal: .accepted))
        XCTAssertEqual(AskOpenMatesIntent.result(forRefusal: .noCore), AskOpenMatesIntent.Message.notConnected)
        XCTAssertEqual(AskOpenMatesIntent.result(forRefusal: .cancelled), AskOpenMatesIntent.Message.notConnected)
    }
}
