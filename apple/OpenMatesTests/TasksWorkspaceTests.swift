import CryptoKit
import XCTest
@testable import OpenMates

@MainActor
final class TasksWorkspaceTests: XCTestCase {
    // contract-test: supporting surface=gui.apple assertions=tasks.content.client-encrypted,tasks.workflow-projections.read-only
    func testServerTaskBoardDecodesEncryptedTasksAndWorkflowProjectionsWithoutRelaxingTypes() throws {
        struct Board: Decodable { let tasks: [TaskBoardRecord] }
        let task = serverTaskFixture()
        let run: [String: Any] = [
            "task_id": "synthetic-workflow-projection", "source": "workflow_run", "projection_kind": "next_run",
            "workflow_id": "synthetic-workflow", "workflow_run_id": NSNull(), "trigger_id": "synthetic-trigger",
            "label": "Workflow run", "title": NSNull(), "status": "todo", "run_status": "scheduled",
            "can_cancel": false, "can_delete": false, "read_only": true,
            "created_at": 1_788_883_200, "updated_at": 1_788_883_200, "position": 0,
        ]
        let board: Board = try decodeFixture(["tasks": [task, run]])
        XCTAssertEqual(board.tasks.count, 2)
        guard case .task(let encrypted) = board.tasks[0].value,
              case .workflowRun(let projection) = board.tasks[1].value else {
            return XCTFail("The response discriminator must preserve both record kinds")
        }
        XCTAssertEqual(encrypted.linkedProjectHashes, [String(repeating: "a", count: 64)])
        XCTAssertEqual(encrypted.encryptedTitle, "synthetic-ciphertext")
        XCTAssertTrue(projection.readOnly)
        XCTAssertNil(projection.workflowRunId)
        XCTAssertEqual(projection.status, .todo)

        for (field, incompatible) in [("status", "future_unknown_state"), ("priority", "3")] {
            var invalid = task
            invalid[field] = incompatible
            XCTAssertThrowsError(try decodeFixture(invalid) as EncryptedUserTaskRecord,
                                 "Unknown states and string numbers must not be silently coerced")
        }
    }

    // contract-test: supporting surface=gui.apple assertions=tasks.content.client-encrypted,plans.content.client-encrypted
    func testTaskAndPlanArrayShapeFailuresKeepSafeStructuralDiagnostics() throws {
        var task = serverTaskFixture()
        task["linked_project_hashes"] = "[\"private-synthetic-hash\"]"
        do {
            let _: EncryptedUserTaskRecord = try decodeFixture(task)
            XCTFail("Undocumented JSON-in-string metadata must not be guessed into a different wire contract")
        } catch {
            let summary = APIResponseDecodingDiagnostics.summary(error: error, responseType: EncryptedUserTaskRecord.self)
            XCTAssertTrue(summary.contains("typeMismatch"))
            XCTAssertTrue(summary.contains("linkedProjectHashes"))
            XCTAssertFalse(summary.contains("private-synthetic-hash"))
            XCTAssertFalse(summary.contains("synthetic-task"))
        }
        let plan: EncryptedUserPlanRecord = try decodeFixture(serverPlanFixture())
        XCTAssertEqual(plan.status, .active)
        XCTAssertEqual(plan.linkedProjectHashes, [String(repeating: "b", count: 64)])
        XCTAssertEqual(plan.keyWrappers?.first?.keyType, "master")
        XCTAssertEqual(plan.keyWrappers?.first?.encryptedPlanKey, "synthetic-wrapped-key")
        var invalidPlan = serverPlanFixture()
        invalidPlan["linked_project_hashes"] = "[\"private-synthetic-hash\"]"
        XCTAssertThrowsError(try decodeFixture(invalidPlan) as EncryptedUserPlanRecord)
    }

    // contract-test: supporting surface=gui.apple assertions=plans.content.client-encrypted
    func testOpenedPlanJSONPreservesValidFlowsAndRejectsMalformedContent() throws {
        let plaintext = "[{\"flow_id\":\"synthetic-flow\",\"title\":\"Review\",\"expected_outcome\":\"Verified\",\"steps\":[{\"step_id\":\"synthetic-step\",\"text\":\"Inspect results\"}]}]"
        let key = SymmetricKey(size: .bits256)
        let encrypted = try ComposerEmbedCrypto.encryptContent(plaintext, using: key)
        let opened = try ComposerEmbedCrypto.decryptContent(encrypted, using: key)
        let flows = try UserPlansService.decodeOpenedJSON([UserPlanFlow].self, from: Data(opened.utf8), field: .userFlows)
        XCTAssertEqual(flows.first?.expectedOutcome, "Verified")
        XCTAssertEqual(flows.first?.steps.first?.text, "Inspect results")
        XCTAssertThrowsError(try UserPlansService.decodeOpenedJSON([UserPlanFlow].self,
            from: Data("[{\"flow_id\":\"synthetic-flow\"}]".utf8), field: .userFlows),
            "Malformed decrypted flows must remain a visible Plan load failure")
        XCTAssertThrowsError(try UserPlansService.decodeOpenedJSON([String].self,
            from: Data("[123]".utf8), field: .linkedProjectIDs))
        XCTAssertThrowsError(try ComposerEmbedCrypto.decryptContent(encrypted, using: SymmetricKey(size: .bits256)))
    }

    private func decodeFixture<T: Decodable>(_ object: [String: Any]) throws -> T {
        let decoder = JSONDecoder()
        decoder.keyDecodingStrategy = .convertFromSnakeCase
        return try decoder.decode(T.self, from: JSONSerialization.data(withJSONObject: object))
    }

    private func serverTaskFixture() -> [String: Any] {
        ["task_id": "synthetic-task", "encrypted_task_key": "synthetic-wrapped-key",
         "encrypted_title": "synthetic-ciphertext", "status": "todo", "assignee_type": "external_ai",
         "assignee_identity": "codex", "linked_project_hashes": [String(repeating: "a", count: 64)],
         "version": 2, "priority": 3, "position": 0, "created_at": 1_788_883_200, "updated_at": 1_788_883_200]
    }

    private func serverPlanFixture() -> [String: Any] {
        ["plan_id": "synthetic-plan", "encrypted_title": "synthetic-ciphertext", "encrypted_goal": "synthetic-ciphertext",
         "status": "active", "linked_project_hashes": [String(repeating: "b", count: 64)], "version": 2,
         "created_at": 1_788_883_200, "updated_at": 1_788_883_200,
         "key_wrappers": [["key_type": "master", "encrypted_plan_key": "synthetic-wrapped-key", "created_at": 1_788_883_200]]]
    }

    // contract-test: supporting surface=gui.apple assertions=tasks.lifecycle.visible
    func testPlanBoardColumnsFollowDeployedLifecycle() {
        XCTAssertEqual(UserPlanStatus.draft.boardColumn, .backlog)
        XCTAssertEqual(UserPlanStatus.awaitingConfirmation.boardColumn, .todo)
        XCTAssertEqual(UserPlanStatus.executing.boardColumn, .inProgress)
        XCTAssertEqual(UserPlanStatus.blocked.boardColumn, .blocked)
        XCTAssertEqual(UserPlanStatus.completed.boardColumn, .done)
        XCTAssertNil(UserPlanStatus.archived.boardColumn)
    }

    // contract-test: supporting surface=gui.apple assertions=tasks.activity.task-scoped-authorization
    func testTeamScopeIsPreservedInMutationPaths() {
        XCTAssertEqual(UserTasksPaths.scoped("/v1/user-tasks/task-1", teamID: "team/a"),
                       "/v1/user-tasks/task-1?team_id=team%2Fa")
        XCTAssertEqual(UserTasksPaths.scoped("/v1/user-tasks/task-1?version=2", teamID: "team/a"),
                       "/v1/user-tasks/task-1?version=2&team_id=team%2Fa")
        XCTAssertEqual(UserTasksPaths.list(.init(projectID: "project/1", teamID: "team/a")),
                       "/v1/user-tasks?project_id=project%2F1&team_id=team%2Fa")
    }

    // contract-test: supporting surface=gui.apple assertions=tasks.activity.client-encrypted
    func testActivityCipherRejectsAnotherTasksAAD() throws {
        let key = SymmetricKey(size: .bits256)
        let context = "task_activity_comment:task-a:entry-a:v1"
        let sealed = try UserTasksService.sealActivity("Sensitive comment", key: key, associatedData: context)
        XCTAssertEqual(try UserTasksService.openActivityCipher(sealed, key: key, associatedData: context),
                       "Sensitive comment")
        XCTAssertThrowsError(try UserTasksService.openActivityCipher(sealed, key: key,
            associatedData: "task_activity_comment:task-b:entry-a:v1"))
    }

    #if DEBUG
    // contract-test: supporting surface=gui.apple assertions=tasks.lifecycle.visible,tasks.content.client-encrypted
    func testSupplementaryLoadFailuresPreserveBoardAndOldGenerationCannotOverwriteCurrentErrors() {
        struct Failed: LocalizedError { let label: String; var errorDescription: String? { label } }
        let store = TasksWorkspaceStore()
        store.installPreview()
        let previous = store.debugLoadGeneration
        store.debugApplyLoadFailure(Failed(label: "Plan response failed"), stage: "plans", generation: previous)
        XCTAssertNil(store.errorMessage, "A Plan failure must not replace the successfully loaded Tasks board")
        XCTAssertEqual(store.boardItems.count, 6)
        XCTAssertEqual(store.plansLoadErrorMessage, "Plan response failed")
        store.debugApplyLoadFailure(Failed(label: "Project labels failed"), stage: "project_names", generation: previous)
        XCTAssertEqual(store.boardItems.count, 6)
        XCTAssertEqual(store.projectNamesLoadErrorMessage, "Project labels failed")

        store.reset(accountID: nil)
        store.installPreview(projectID: "preview-project")
        let current = store.debugLoadGeneration
        store.debugApplyLoadFailure(Failed(label: "Current load failed"), stage: "tasks", generation: current)
        store.debugApplyLoadFailure(Failed(label: "Old load failed"), stage: "tasks", generation: previous)
        store.debugApplyLoadFailure(Failed(label: "Old Plan failed"), stage: "plans", generation: previous)
        XCTAssertEqual(store.errorMessage, "Current load failed")
        XCTAssertNil(store.plansLoadErrorMessage)
        XCTAssertNil(store.projectNamesLoadErrorMessage)
        XCTAssertEqual(store.boardItems.count, 2, "A stale response must not change the current Project board")
        store.reset(accountID: nil)
        XCTAssertNil(store.errorMessage)
        XCTAssertNil(store.plansLoadErrorMessage)
        XCTAssertNil(store.projectNamesLoadErrorMessage)
        XCTAssertTrue(store.boardItems.isEmpty)
        XCTAssertTrue(store.projectNames.isEmpty)
    }
    #endif

    #if DEBUG
    // contract-test: supporting surface=gui.apple assertions=tasks.content.client-encrypted,tasks.workflow-projections.read-only
    func testAccountResetDropsDecryptedPreviewStateAndSelection() {
        let store = TasksWorkspaceStore()
        store.installPreview()
        XCTAssertEqual(store.boardItems.count, 6)
        XCTAssertEqual(store.plans.count, 2)
        store.openTask("preview-backlog-1")
        XCTAssertNotNil(store.selectedTask)
        store.openWorkflowRun("preview-workflow")
        XCTAssertNil(store.selectedTask)
        XCTAssertEqual(store.selectedWorkflowRun?.workflowRunId, "weather-report-run")
        store.reset(accountID: nil)
        XCTAssertTrue(store.boardItems.isEmpty)
        XCTAssertTrue(store.plans.isEmpty)
        XCTAssertTrue(store.projectNames.isEmpty)
        XCTAssertNil(store.selectedTask)
        XCTAssertNil(store.selectedPlan)
        XCTAssertNil(store.selectedWorkflowRun)
    }

    // contract-test: supporting surface=gui.apple assertions=tasks.lifecycle.visible
    func testProjectPreviewContainsOnlyLinkedTasksAndPlans() {
        let store = TasksWorkspaceStore()
        store.installPreview(projectID: "preview-project")
        XCTAssertEqual(store.boardItems.count, 2)
        XCTAssertEqual(store.plans.count, 2)
        XCTAssertTrue(store.boardItems.allSatisfy { item in
            if case .task(let task) = item { return task.linkedProjectIds == ["preview-project"] }
            return false
        })
        XCTAssertTrue(store.plans.allSatisfy { $0.linkedProjectIds == ["preview-project"] })
        XCTAssertEqual(store.projectNames["preview-project"], "OpenMates")
    }

    // contract-test: supporting surface=gui.apple assertions=tasks.lifecycle.visible
    func testChangedProjectStartsFreshLoadWhilePreviousRequestIsSuspended() async {
        struct Stopped: Error {}
        let store = TasksWorkspaceStore()
        store.reset(accountID: "suspended-request-test")
        let firstStarted = expectation(description: "first project request started")
        let secondStarted = expectation(description: "second project request started")
        var firstContinuation: CheckedContinuation<Void, Never>?
        var secondContinuation: CheckedContinuation<Void, Never>?
        store.debugBoardLoader = { filters in
            if filters.projectID == "project-a" {
                await withCheckedContinuation { continuation in
                    firstContinuation = continuation
                    firstStarted.fulfill()
                }
            } else if filters.projectID == "project-b" {
                await withCheckedContinuation { continuation in
                    secondContinuation = continuation
                    secondStarted.fulfill()
                }
            }
            throw Stopped()
        }

        let first = Task { await store.load(accountID: "suspended-request-test", projectID: "project-a") }
        await fulfillment(of: [firstStarted], timeout: 3)
        let second = Task { await store.load(accountID: "suspended-request-test", projectID: "project-b") }
        await fulfillment(of: [secondStarted], timeout: 3)
        XCTAssertTrue(store.isLoading)

        firstContinuation?.resume()
        await first.value
        XCTAssertTrue(store.isLoading, "The stale request must not clear the new request's loading state")
        secondContinuation?.resume()
        await second.value
        XCTAssertFalse(store.isLoading, "The current request must release its loading state")
    }
    #endif
}
