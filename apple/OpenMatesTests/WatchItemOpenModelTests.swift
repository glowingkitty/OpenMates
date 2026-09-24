import XCTest
@testable import OpenMates

final class WatchItemOpenModelTests: XCTestCase {
    // contract-test: direct surface=gui.apple assertions=apple-watch.handoff.exact-private
    func testTaskPayloadContainsOnlyKindAndOpaqueID() {
        let request = WatchItemOpenRequest(kind: .task, id: "task-123")
        XCTAssertEqual(request?.payload, ["kind": "task", "id": "task-123"])
        XCTAssertEqual(WatchItemOpenRequest.parse(request!.payload), request)
    }

    // contract-test: direct surface=gui.apple assertions=apple-watch.handoff.exact-private
    func testWorkflowPayloadParsesWithoutURLOrTitle() {
        let request = WatchItemOpenRequest.parse([
            "kind": "workflow", "id": "workflow-456",
        ])
        XCTAssertEqual(request?.kind, .workflow)
        XCTAssertEqual(request?.id, "workflow-456")
        XCTAssertEqual(request?.payload.count, 2)
    }

    // contract-test: direct surface=gui.apple assertions=apple-watch.handoff.exact-private
    func testParserRejectsUnknownKindAndInvalidID() {
        XCTAssertNil(WatchItemOpenRequest.parse(["kind": "settings", "id": "settings"]))
        XCTAssertNil(WatchItemOpenRequest.parse(["kind": "task", "id": ""] ))
        XCTAssertNil(WatchItemOpenRequest.parse(["kind": "task", "id": " task-1 "]))
        XCTAssertNil(WatchItemOpenRequest.parse(["kind": "task", "id": "task\n1"]))
        XCTAssertNil(WatchItemOpenRequest.parse(["kind": "workflow", "id": 42]))
    }
}
