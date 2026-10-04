import XCTest
@testable import OpenMates
final class FocusPhaseTests: XCTestCase {
    private let event = #"{"type":"focus_phase_changed","event_id":"11111111-1111-4111-8111-111111111111","chat_id":"22222222-2222-4222-8222-222222222222","focus_id":"jobs-career_insights","run_id":"33333333-3333-4333-8333-333333333333","version":2,"previous_phase_id":"confirm_profile","phase_id":"explore","phase_title":"Explore career directions","direction":"forward","created_at":1}"#
    // contract-test: supporting surface=gui.apple assertions=focus-modes.phases,focus-modes.history-events
    func testPhaseHistoryLinksToFocusDetailsWithoutReplayingState() throws {
        let parsed = try XCTUnwrap(FocusPhaseEvent.parse(event))
        XCTAssertEqual(parsed.phaseTitle, "Explore career directions")
        XCTAssertEqual(parsed.detailPath, "apps/jobs/focus/career_insights")
        XCTAssertEqual(parsed.direction, "forward")
        XCTAssertNil(FocusPhaseEvent.parse("ordinary system notice"))
    }
    // contract-test: supporting surface=gui.apple assertions=focus-modes.phases
    func testPhaseCiphertextSurvivesChatDecodeAndCopy() throws {
        let decoder = JSONDecoder(); decoder.keyDecodingStrategy = .convertFromSnakeCase
        let chat = try decoder.decode(Chat.self, from: Data(#"{"id":"chat","created_at":1,"encrypted_focus_phase_state":"opaque","messages_v":2}"#.utf8))
        XCTAssertEqual(chat.encryptedFocusPhaseState, "opaque")
        XCTAssertEqual(chat.withMessagesVersion(3).encryptedFocusPhaseState, "opaque")
    }
    // contract-test: supporting surface=gui.apple assertions=focus-modes.phases
    func testProjectTextUsesPhasesAndNoQuestionCountGate() {
        let instruction = "---\nphases_version: 1\nphases:\n  - id: understand\n    title: Understand\n    instructions: Ask five questions by default and honor skip requests.\n    requirements:\n      - id: enough\n        text: Enough context or explicit request to proceed.\n---\nGlobal instruction"
        let phases = FocusPhaseDefinition.fromInstruction(instruction)
        XCTAssertEqual(phases.count, 1)
        XCTAssertTrue(phases.first?.instructions.contains("honor skip") == true)
        XCTAssertEqual(phases.first?.requirements.first?.id, "enough")
        XCTAssertTrue(FocusPhaseDefinition.fromInstruction("Legacy instruction").isEmpty)
    }
}
