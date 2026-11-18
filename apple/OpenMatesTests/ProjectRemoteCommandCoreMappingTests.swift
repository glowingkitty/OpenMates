import XCTest
@testable import OpenMates

/// Coordinator mapping onto the core's remote command review API: the card
/// views of a validated review, the core-built payloads and the event reducer.
@MainActor
final class ProjectRemoteCommandCoreMappingTests: XCTestCase {
    private func payload(cwd: String = "src") -> [String: Any] {
        ["protocol_version": 1, "execution_id": "run-1", "chat_id": "chat-1",
         "project_id": "project-1", "source_id": "source-1", "state": "REVIEW_REQUIRED",
         "created_at": 1_700_000_000, "review_expires_at": 4_000_000_000,
         "review_token": String(repeating: "t", count: 32), "approval_requirement": "one_run",
         "command": ["argv": ["npm", "test"], "cwd": cwd, "mode": "foreground",
                     "source_access": "read_only", "deadline_ms": 60_000,
                     "writable_profiles": [String](), "network_profile": NSNull(),
                     "credential_profiles": [String]()],
         "explanation": ["summary": "Runs the tests", "effects": [String](), "risks": [String](),
                         "uncertainty": [String]()]]
    }

    // contract-test: supporting surface=gui.apple assertions=code-run.remote.managed-jobs
    func testCoreValidatedReviewMapsOntoCardAndBack() throws {
        let data = try JSONSerialization.data(withJSONObject: payload())
        let record = try parseRemoteCommandReview(payloadJson: String(decoding: data, as: UTF8.self))
        let review = ProjectRemoteCommandReview(record: record)
        XCTAssertEqual(review.executionId, "run-1")
        XCTAssertEqual(review.command.argv, ["npm", "test"])
        XCTAssertEqual(review.record, record)
        XCTAssertTrue(ProjectRemoteCommandCoordinator.canonicalPortableRequest(review)
            .hasPrefix("{\"protocol_version\":1,\"execution_id\":\"run-1\""))
    }

    // contract-test: supporting surface=gui.apple assertions=code-run.remote.managed-jobs
    func testCoreRefusesAnEscapingWorkingDirectory() throws {
        let data = try JSONSerialization.data(withJSONObject: payload(cwd: "../outside"))
        XCTAssertThrowsError(try parseRemoteCommandReview(
            payloadJson: String(decoding: data, as: UTF8.self)))
    }

    // contract-test: supporting surface=gui.apple assertions=code-run.remote.managed-jobs
    func testEntryOutputRoundTripsThroughTheCoreReducer() throws {
        var entry = ProjectReviewFixtures.commandEntry(status: "running")
        let folded = try remoteCommandApplyEvent(state: entry.outputRecord, eventKind: "output",
            status: "running", sequence: 0, text: "ok\u{1B}[0m\n")
        entry.apply(folded)
        XCTAssertEqual(entry.latestOutput, "ok\n")
        XCTAssertEqual(entry.lastSequence, 0)
        XCTAssertThrowsError(try remoteCommandApplyEvent(state: entry.outputRecord,
            eventKind: "output", status: "running", sequence: 0, text: "dup"))
    }

    // contract-test: supporting surface=gui.apple assertions=code-run.remote.managed-jobs
    func testResponseStatusMappingComesFromTheCore() {
        XCTAssertEqual(remoteCommandStatusForResponse(kind: "remote_command_response",
            state: "WAITING_FOR_EXECUTOR", resultStatus: nil), "waiting_for_executor")
        XCTAssertEqual(remoteCommandStatusForResponse(kind: "remote_command_error",
            state: nil, resultStatus: nil), "error")
        XCTAssertNil(remoteCommandStatusForResponse(kind: "remote_command_response",
            state: "UNKNOWN", resultStatus: nil))
    }
}
