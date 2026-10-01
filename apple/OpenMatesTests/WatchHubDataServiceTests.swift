import CryptoKit
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

    // contract-test: supporting surface=gui.apple assertions=apple-watch.lists.read-only-private
    func testKanbanKeepsBlockedSeparateInCanonicalIPhoneOrder() {
        XCTAssertEqual(WatchTaskGroup.allCases.map(\.status),
                       ["backlog", "todo", "in_progress", "blocked", "done"])
        XCTAssertEqual(WatchTaskGroup.from(status: "blocked"), .blocked)
        XCTAssertNil(WatchTaskGroup.from(status: "archived"))
    }

    @MainActor
    // contract-test: supporting surface=gui.apple assertions=apple-watch.lists.read-only-private
    func testTaskDetailsDecryptWithWrappedTaskKeyAndRejectForeignKey() async throws {
        let masterKey = SymmetricKey(size: .bits256)
        let taskKey = SymmetricKey(size: .bits256)
        let wrappedKey = try await CryptoManager.shared.wrapChatKey(taskKey, masterKey: masterKey)
        var wire: [String: Any] = ["task_id": "task-private", "status": "blocked",
                                   "encrypted_task_key": wrappedKey]
        let fields = ["encrypted_title": "Private task", "encrypted_description": "Private description",
                      "encrypted_latest_instruction": "Private context", "encrypted_activity_summary": "Private progress",
                      "encrypted_blocked_reason": "Private reason"]
        for (field, plaintext) in fields {
            wire[field] = try await CryptoManager.shared.encryptContent(plaintext, key: taskKey)
        }
        let record = try makeAPIClientDecoder().decode(WatchTaskRecord.self,
            from: JSONSerialization.data(withJSONObject: wire))
        let opened = await WatchHubDataService.openTask(record, masterKey: masterKey)
        let task = try XCTUnwrap(opened)
        XCTAssertEqual(task.title, "Private task")
        XCTAssertEqual(task.description, "Private description")
        XCTAssertEqual(task.latestInstruction, "Private context")
        XCTAssertEqual(task.activitySummary, "Private progress")
        XCTAssertEqual(task.blockedReason, "Private reason")
        XCTAssertEqual(task.group, .blocked)
        let foreign = await WatchHubDataService.openTask(record, masterKey: SymmetricKey(size: .bits256))
        XCTAssertNil(foreign)
        wire["encrypted_description"] = "invalid-ciphertext"
        let corrupt = try makeAPIClientDecoder().decode(WatchTaskRecord.self,
            from: JSONSerialization.data(withJSONObject: wire))
        let failed = await WatchHubDataService.openTask(corrupt, masterKey: masterKey)
        XCTAssertNil(failed)
    }

    @MainActor
    // contract-test: supporting surface=gui.apple assertions=apple-watch.lists.read-only-private,apple-watch.handoff.exact-private
    func testWorkflowProjectionKeepsItsOwnColumnAndParentHandoff() async throws {
        let data = Data(#"{"task_id":"projection-one","source":"workflow_run","workflow_id":"workflow-parent","title":"Workflow waiting","status":"blocked","blocked_message":"Waiting for provider"}"#.utf8)
        let record = try makeAPIClientDecoder().decode(WatchTaskRecord.self, from: data)
        let opened = await WatchHubDataService.openTask(record, masterKey: SymmetricKey(size: .bits256))
        let task = try XCTUnwrap(opened)
        XCTAssertEqual(task.group, .blocked)
        XCTAssertEqual(task.blockedReason, "Waiting for provider")
        XCTAssertEqual(task.openRequest.kind, .workflow)
        XCTAssertEqual(task.openRequest.id, "workflow-parent")
        XCTAssertTrue(task.description.isEmpty)
    }

    private func makeAPIClientDecoder() -> JSONDecoder {
        let decoder = JSONDecoder()
        decoder.keyDecodingStrategy = .convertFromSnakeCase
        return decoder
    }
}
