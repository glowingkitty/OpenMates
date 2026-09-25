import Foundation
import XCTest
@testable import OpenMates

final class WatchHubDataServiceTests: XCTestCase {
    // contract-test: supporting surface=gui.apple assertions=apple-watch.lists.read-only-private
    func testNonemptyTaskListDecodesWithAPIClientSnakeCaseStrategy() throws {
        let data = Data(#"{"tasks":[{"task_id":"task-123","source":"user","workflow_id":"workflow-456","title":null,"encrypted_task_key":"wrapped-key","encrypted_title":"encrypted-title","status":"todo","position":2,"updated_at":1700000000}]}"#.utf8)
        let response = try makeAPIClientDecoder().decode(WatchTaskListResponse.self, from: data)

        let task = try XCTUnwrap(response.tasks.first)
        XCTAssertEqual(response.tasks.count, 1)
        XCTAssertEqual(task.taskId, "task-123")
        XCTAssertEqual(task.workflowId, "workflow-456")
        XCTAssertEqual(task.encryptedTaskKey, "wrapped-key")
        XCTAssertEqual(task.encryptedTitle, "encrypted-title")
        XCTAssertEqual(task.status, "todo")
        XCTAssertEqual(task.position, 2)
        XCTAssertEqual(task.updatedAt, 1_700_000_000)
    }

    // contract-test: supporting surface=gui.apple assertions=apple-watch.lists.read-only-private
    func testNonemptyWorkflowListDecodesWithAPIClientSnakeCaseStrategy() throws {
        let data = Data(#"{"workflows":[{"id":"workflow-456","title":"Daily briefing","enabled":true,"updated_at":1700000001,"category":"planning","icon":"calendar"}]}"#.utf8)
        let response = try makeAPIClientDecoder().decode(WatchWorkflowListResponse.self, from: data)

        let workflow = try XCTUnwrap(response.workflows.first)
        XCTAssertEqual(response.workflows.count, 1)
        XCTAssertEqual(workflow.id, "workflow-456")
        XCTAssertEqual(workflow.title, "Daily briefing")
        XCTAssertTrue(workflow.enabled)
        XCTAssertEqual(workflow.updatedAt, 1_700_000_001)
        XCTAssertEqual(workflow.category, "planning")
        XCTAssertEqual(workflow.icon, "calendar")
    }

    private func makeAPIClientDecoder() -> JSONDecoder {
        let decoder = JSONDecoder()
        decoder.keyDecodingStrategy = .convertFromSnakeCase
        return decoder
    }
}
