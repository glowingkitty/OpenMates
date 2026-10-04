import CryptoKit
import XCTest
@testable import OpenMates

@MainActor
final class TasksWorkspaceTests: XCTestCase {
    // contract-test: supporting surface=gui.apple assertions=apple-task-board.new-task-shortcuts
    func testTaskComposerViewportSubtractsOnlyUnconsumedDockedKeyboardOverlap() {
        let full = CGRect(x: 10, y: 120, width: 370, height: 700)
        let keyboard = CGRect(x: 0, y: 520, width: 390, height: 324)
        XCTAssertEqual(TasksWorkspaceLayoutPolicy.keyboardOverlap(container: full, keyboard: keyboard), 300)
        let alreadyAvoided = CGRect(x: 10, y: 120, width: 370, height: 400)
        XCTAssertEqual(TasksWorkspaceLayoutPolicy.keyboardOverlap(container: alreadyAvoided, keyboard: keyboard), 0,
                       "SwiftUI's existing keyboard inset must not be applied twice")
        XCTAssertEqual(TasksWorkspaceLayoutPolicy.keyboardOverlap(container: full, keyboard: nil), 0)
        XCTAssertEqual(TasksWorkspaceLayoutPolicy.keyboardOverlap(container: full,
            keyboard: CGRect(x: 400, y: 520, width: 390, height: 324)), 0,
            "A keyboard outside this pane must not shorten it")
        XCTAssertEqual(TasksWorkspaceLayoutPolicy.keyboardOverlap(container: full,
            keyboard: CGRect(x: 30, y: 350, width: 280, height: 220)), 0,
            "Floating iPad keyboards must not reserve a full bottom lane")
        XCTAssertEqual(TasksWorkspaceLayoutPolicy.keyboardOverlap(container: full,
            keyboard: CGRect(x: 0, y: 50, width: 390, height: 800)), full.height)
    }

    // contract-test: supporting surface=gui.apple assertions=apple-task-board.new-task-shortcuts
    func testTaskInspirationKeepsWebHeightWhenKeyboardChangesViewport() {
        XCTAssertEqual(TasksWorkspaceLayoutPolicy.bannerHeight(width: 370, height: 700), 190)
        XCTAssertEqual(TasksWorkspaceLayoutPolicy.bannerHeight(width: 370, height: 400), 190)
        XCTAssertEqual(TasksWorkspaceLayoutPolicy.bannerHeight(width: 1000, height: 900), 315)
        XCTAssertEqual(TasksWorkspaceLayoutPolicy.bannerHeight(width: 1000, height: 400), 240)
    }

    // contract-test: supporting surface=gui.apple assertions=apple-workspaces.offline-complete,tasks.content.client-encrypted
    func testLegacyTaskInventoryBelowCapPreservesCiphertextAndTeamScope() async throws {
        var paths: [String] = []
        let fixture = serverTaskFixture()
        let snapshot = try await UserTasksInventory.fetch(teamID: "synthetic/team") { path in
            paths.append(path)
            return try JSONSerialization.data(withJSONObject: ["tasks": [fixture], "eligible_external_ai": ["codex"]])
        }
        XCTAssertEqual(paths, ["/v1/user-tasks?paginate=true&limit=500&team_id=synthetic%2Fteam"])
        struct List: Decodable { let tasks: [EncryptedUserTaskRecord] }
        let decoder = JSONDecoder()
        decoder.keyDecodingStrategy = .convertFromSnakeCase
        let result = try decoder.decode(List.self, from: snapshot)
        XCTAssertEqual(result.tasks.count, 1)
        XCTAssertEqual(result.tasks[0].encryptedTitle, fixture["encrypted_title"] as? String)
        XCTAssertEqual(result.tasks[0].encryptedTaskKey, fixture["encrypted_task_key"] as? String)
    }

    // contract-test: supporting surface=gui.apple assertions=apple-workspaces.offline-complete
    func testLegacyTaskInventoryAtCapCannotBecomeCompleteOfflineSnapshot() async throws {
        do {
            _ = try await UserTasksInventory.fetch(teamID: nil) { _ in
                try JSONSerialization.data(withJSONObject: ["tasks": (0..<500).map { ["task_id": "task-\($0)"] }])
            }
            XCTFail("A legacy capped list cannot prove that no rows were omitted")
        } catch UserTasksError.incompleteInventory { }
    }

    // contract-test: supporting surface=gui.apple assertions=apple-workspaces.offline-complete
    func testTaskInventoryPagesIncludeFinalRowsAndRejectMissingOrRepeatedReceipts() async throws {
        var paths: [String] = []
        let snapshot = try await UserTasksInventory.fetch(teamID: nil) { path in
            paths.append(path)
            let next = paths.count == 1
            return try JSONSerialization.data(withJSONObject: ["tasks": [["task_id": next ? "task-a" : "task-b"]],
                "complete": !next, "next_cursor": next ? "task-a" as Any : NSNull()])
        }
        XCTAssertEqual(paths, ["/v1/user-tasks?paginate=true&limit=500", "/v1/user-tasks?paginate=true&limit=500&cursor=task-a"])
        let envelope = try XCTUnwrap(JSONSerialization.jsonObject(with: snapshot) as? [String: Any])
        XCTAssertEqual((envelope["tasks"] as? [[String: String]])?.map { $0["task_id"] ?? "" }, ["task-a", "task-b"])
        for invalidSecond in [
            ["tasks": [["task_id": "task-b"]]],
            ["tasks": [["task_id": "task-a"]], "complete": true],
        ] as [[String: Any]] {
            var count = 0
            do {
                _ = try await UserTasksInventory.fetch(teamID: nil) { _ in
                    count += 1
                    return try JSONSerialization.data(withJSONObject: count == 1
                        ? ["tasks": [["task_id": "task-a"]], "complete": false, "next_cursor": "task-a"]
                        : invalidSecond)
                }
                XCTFail("A partial or overlapping page must remain a visible failure")
            } catch UserTasksError.invalidResponse { }
        }
    }

    // contract-test: supporting surface=gui.apple assertions=tasks.content.client-encrypted
    func testTaskOpeningUsesWrappedKeyAndRejectsMissingKeyOrMalformedEncryptedArrays() async throws {
        let master = SymmetricKey(size: .bits256)
        let taskKey = SymmetricKey(size: .bits256)
        var fixture = serverTaskFixture()
        fixture["encrypted_task_key"] = try await CryptoManager.shared.wrapChatKey(taskKey, masterKey: master)
        fixture["encrypted_title"] = try ComposerEmbedCrypto.encryptContent("Synthetic title", using: taskKey)
        fixture["encrypted_tags"] = try ComposerEmbedCrypto.encryptContent("[\"Synthetic tag\"]", using: taskKey)
        fixture["encrypted_linked_project_ids"] = try ComposerEmbedCrypto.encryptContent("[\"synthetic-project\"]", using: taskKey)
        let service = UserTasksService()
        let opened = try await service.open(decodeFixture(fixture), masterKey: master)
        XCTAssertEqual(opened?.title, "Synthetic title")
        XCTAssertEqual(opened?.tags, ["Synthetic tag"])
        XCTAssertEqual(opened?.linkedProjectIds, ["synthetic-project"])
        var missing = fixture
        missing.removeValue(forKey: "encrypted_task_key")
        do {
            _ = try await service.open(decodeFixture(missing), masterKey: master)
            XCTFail("Missing keys must not silently remove a task from its inventory")
        } catch UserTasksError.taskKeyUnavailable { }
        fixture["encrypted_tags"] = try ComposerEmbedCrypto.encryptContent("[123]", using: taskKey)
        do {
            _ = try await service.open(decodeFixture(fixture), masterKey: master)
            XCTFail("Malformed decrypted tags must not be replaced with an empty list")
        } catch is DecodingError { }
    }

    #if DEBUG
    // contract-test: supporting surface=gui.apple assertions=apple-task-board.edit,apple-workspaces.isolation,teams.context.full-switch-local
    func testTeamSwitchSynchronouslyClearsTaskStateAndWithholdsSuspendedEditResponse() async throws {
        let accountID = "synthetic-task-account"
        let suite = "TaskTeamFenceTests-\(UUID().uuidString)"
        let defaults = try XCTUnwrap(UserDefaults(suiteName: suite))
        defer { defaults.removePersistentDomain(forName: suite) }
        let context = TeamWorkspaceContext(service: TaskFenceTeamService(),
            environment: .init(currentAccountID: { accountID },
                scopeGeneration: { OfflineStore.shared.scopeGeneration },
                serverProfile: { ServerProfile.current() }), defaults: defaults)
        await context.load(accountID: accountID)
        await context.selectTeam("team-a")
        let store = TasksWorkspaceStore(teamContext: context)
        store.installPreview(accountID: accountID)
        store.openTask("preview-backlog-1")
        store.promptDraft = "Previous team draft"
        let original = try XCTUnwrap(store.selectedTask)
        let generation = store.interactionGeneration
        let started = expectation(description: "task edit suspended in first team")
        var resume: CheckedContinuation<UserTaskItem, Error>?
        store.debugTaskEditor = { _, _ in
            try await withCheckedThrowingContinuation { resume = $0; started.fulfill() }
        }
        let saving = Task { await store.saveTask(original, patch: .init(title: "Previous team update")) }
        await fulfillment(of: [started], timeout: 3)
        XCTAssertTrue(store.isSaving)
        await context.selectTeam("team-b")
        store.reset(accountID: accountID)
        // The account, server and offline scope are unchanged; only the team
        // changed. Clearing must complete before any asynchronous reload.
        XCTAssertNotEqual(store.interactionGeneration, generation)
        XCTAssertTrue(store.boardItems.isEmpty)
        XCTAssertTrue(store.plans.isEmpty)
        XCTAssertNil(store.selectedTaskID)
        XCTAssertTrue(store.promptDraft.isEmpty)
        XCTAssertFalse(store.isSaving)
        try XCTUnwrap(resume).resume(returning: original)
        let accepted = await saving.value
        XCTAssertFalse(accepted)
        XCTAssertTrue(store.boardItems.isEmpty)
        XCTAssertNil(store.taskEditErrorMessage)
        let staleCallbackAccepted = await store.saveTask(original, patch: .init(title: "Delayed old view callback"))
        XCTAssertFalse(staleCallbackAccepted)
        XCTAssertFalse(store.isSaving)
    }

    // contract-test: supporting surface=gui.apple assertions=apple-workspaces.isolation,teams.context.full-switch-local
    func testTaskRequestFenceCapturesTeamIDAndRejectsReturningToSameTeamAfterEpochChange() async throws {
        let accountID = "synthetic-task-account"
        let suite = "TaskRequestTeamFenceTests-\(UUID().uuidString)"
        let defaults = try XCTUnwrap(UserDefaults(suiteName: suite))
        defer { defaults.removePersistentDomain(forName: suite) }
        let context = TeamWorkspaceContext(service: TaskFenceTeamService(),
            environment: .init(currentAccountID: { accountID },
                scopeGeneration: { OfflineStore.shared.scopeGeneration },
                serverProfile: { ServerProfile.current() }), defaults: defaults)
        await context.load(accountID: accountID)
        await context.selectTeam("team-a")
        let fence = UserTasksAccountFence(accountID: accountID, teamContext: context)
        XCTAssertNoThrow(try fence.checkTeamContext())
        XCTAssertEqual(fence.requestTeamContext.teamID, "team-a")
        XCTAssertEqual(fence.requestTeamContext.epoch, context.contextEpoch)
        await context.selectTeam("team-b")
        XCTAssertThrowsError(try fence.checkTeamContext())
        await context.selectTeam("team-a")
        XCTAssertEqual(context.teamID, fence.teamID)
        XCTAssertNotEqual(context.contextEpoch, fence.widgetTeamEpoch)
        XCTAssertThrowsError(try fence.checkTeamContext(), "Team ID alone cannot fence a switch away and back")
    }

    // contract-test: supporting surface=gui.apple assertions=apple-task-board.new-task-shortcuts,apple-workspaces.isolation
    func testTaskComposerDraftSurvivesOpeningAndClosingDetailAndClearsOnReset() {
        let store = TasksWorkspaceStore()
        store.installPreview()
        store.promptDraft = "Unsaved task request"
        store.openTask("preview-backlog-1")
        store.closeDetail()
        XCTAssertEqual(store.promptDraft, "Unsaved task request")
        XCTAssertEqual(store.boardItems.count, 6, "Focusing and opening detail must never create a task")
        store.reset(accountID: nil)
        XCTAssertTrue(store.promptDraft.isEmpty)
    }

    // contract-test: supporting surface=gui.apple assertions=apple-task-board.edit
    func testTaskEditSuccessUpdatesSelectedBoardTaskAndRejectsStaleVersion() async throws {
        let store = TasksWorkspaceStore()
        store.installPreview()
        store.openTask("preview-backlog-1")
        let original = try XCTUnwrap(store.selectedTask)
        let patch = UserTaskUpdateInput(title: "Updated task", description: "Updated description", tags: ["release"],
            dueAt: 1_788_969_600, priority: 4)
        let succeeded = await store.saveTask(original, patch: patch)
        XCTAssertTrue(succeeded)
        let updated = try XCTUnwrap(store.selectedTask)
        XCTAssertEqual(updated.title, "Updated task")
        XCTAssertEqual(updated.description, "Updated description")
        XCTAssertEqual(updated.tags, ["release"])
        XCTAssertEqual(updated.dueAt, 1_788_969_600)
        XCTAssertEqual(updated.priority, 4)
        XCTAssertEqual(updated.version, original.version + 1)
        XCTAssertEqual(updated.assigneeType, original.assigneeType)
        XCTAssertEqual(updated.assigneeIdentity, original.assigneeIdentity)
        XCTAssertEqual(updated.status, original.status)
        XCTAssertEqual(updated.linkedProjectIds, original.linkedProjectIds)
        let staleSucceeded = await store.saveTask(original, patch: .init(title: "Stale overwrite"))
        XCTAssertFalse(staleSucceeded)
        XCTAssertEqual(store.selectedTask?.title, "Updated task")
        XCTAssertEqual(store.taskEditErrorMessage, AppStrings.tasksEditConflict)
    }

    // contract-test: supporting surface=gui.apple assertions=apple-task-board.edit
    func testFailedTaskEditKeepsAuthoritativeTaskAndPendingEditDoesNotPublishEarly() async throws {
        let store = TasksWorkspaceStore()
        store.installPreview()
        store.openTask("preview-backlog-1")
        let original = try XCTUnwrap(store.selectedTask)
        var resume: CheckedContinuation<UserTaskItem, Error>?
        store.debugTaskEditor = { task, patch in
            XCTAssertEqual(task.version, original.version)
            XCTAssertEqual(patch.title, "Unsent draft")
            return try await withCheckedThrowingContinuation { resume = $0 }
        }
        let saving = Task { await store.saveTask(original, patch: .init(title: "Unsent draft")) }
        await Task.yield()
        XCTAssertTrue(store.isSaving)
        XCTAssertEqual(store.selectedTask?.title, original.title)
        try XCTUnwrap(resume).resume(throwing: UserTasksError.invalidResponse)
        let succeeded = await saving.value
        XCTAssertFalse(succeeded)
        XCTAssertFalse(store.isSaving)
        XCTAssertEqual(store.selectedTask?.title, original.title)
        XCTAssertEqual(store.selectedTask?.version, original.version)
        XCTAssertEqual(store.taskEditErrorMessage, AppStrings.tasksEditFailed)
    }

    // contract-test: supporting surface=gui.apple assertions=apple-task-board.edit,apple-workspaces.isolation
    func testTaskEditCompletionAfterResetCannotRepopulateAnotherAccount() async throws {
        let store = TasksWorkspaceStore()
        store.installPreview()
        store.openTask("preview-backlog-1")
        let original = try XCTUnwrap(store.selectedTask)
        var resume: CheckedContinuation<UserTaskItem, Error>?
        store.debugTaskEditor = { _, _ in
            try await withCheckedThrowingContinuation { resume = $0 }
        }
        let saving = Task { await store.saveTask(original, patch: .init(title: "Old account")) }
        await Task.yield()
        XCTAssertTrue(store.isSaving)
        store.reset(accountID: nil)
        try XCTUnwrap(resume).resume(returning: original)
        let succeeded = await saving.value
        XCTAssertFalse(succeeded)
        XCTAssertTrue(store.boardItems.isEmpty)
        XCTAssertNil(store.selectedTask)
        XCTAssertNil(store.taskEditErrorMessage)
        XCTAssertFalse(store.isSaving)
    }
    #endif

    // contract-test: supporting surface=gui.apple assertions=apple-task-board.edit,tasks.content.client-encrypted
    func testTaskEditorPatchUsesCapturedVersionAndEncryptsOptionalContent() throws {
        let service = UserTasksService()
        let record: EncryptedUserTaskRecord = try decodeFixture(serverTaskFixture())
        let key = SymmetricKey(size: .bits256)
        let body = try service.updateBody(for: record, patch: .init(title: "Changed", description: "Details", tags: ["release"],
            clearDueAt: true, priority: 4), key: key, timestamp: 1_788_883_201)
        XCTAssertEqual(body["version"] as? Int, record.version)
        XCTAssertEqual(try ComposerEmbedCrypto.decryptContent(try XCTUnwrap(body["encrypted_title"] as? String), using: key), "Changed")
        XCTAssertEqual(try ComposerEmbedCrypto.decryptContent(try XCTUnwrap(body["encrypted_description"] as? String), using: key), "Details")
        XCTAssertEqual(try ComposerEmbedCrypto.decryptContent(try XCTUnwrap(body["encrypted_tags"] as? String), using: key), "[\"release\"]")
        XCTAssertTrue(body["due_at"] is NSNull)
        XCTAssertEqual(body["priority"] as? Int, 4)
        XCTAssertNil(body["status"])
        XCTAssertNil(body["assignee_type"])
        XCTAssertNil(body["assignee_identity"])
        XCTAssertNil(body["title"])
        XCTAssertNil(body["description"])
    }

    // contract-test: supporting surface=gui.apple assertions=tasks.assignment.identity-separated,tasks.content.client-encrypted
    func testTaskContentUpdateBodyPreservesHistoricalAndCodexAssignment() throws {
        let service = UserTasksService()
        let key = SymmetricKey(size: .bits256)
        for identity: UserTaskAssigneeIdentity in [.legacyOpenCode, .codex] {
            var fixture = serverTaskFixture()
            fixture["assignee_identity"] = identity.rawValue
            let record: EncryptedUserTaskRecord = try decodeFixture(fixture)
            // The detail editor omits an unchanged assignment. The service also
            // protects callers that include the existing external_ai type.
            for assigneeType: UserTaskAssigneeType? in [nil, .externalAI] {
                let body = try service.updateBody(for: record,
                    patch: UserTaskUpdateInput(title: "Edited title", description: "Edited description",
                                               assigneeType: assigneeType),
                    key: key, timestamp: 1_788_883_201)
                XCTAssertNil(body["assignee_type"])
                XCTAssertNil(body["assignee_identity"])
                XCTAssertEqual(body["version"] as? Int, record.version)
                let title = try XCTUnwrap(body["encrypted_title"] as? String)
                let description = try XCTUnwrap(body["encrypted_description"] as? String)
                XCTAssertNotEqual(title, "Edited title")
                XCTAssertEqual(try ComposerEmbedCrypto.decryptContent(title, using: key), "Edited title")
                XCTAssertEqual(try ComposerEmbedCrypto.decryptContent(description, using: key), "Edited description")
            }
            let reassigned = try service.updateBody(for: record,
                patch: UserTaskUpdateInput(assigneeType: .user), key: key, timestamp: 1_788_883_201)
            XCTAssertEqual(reassigned["assignee_type"] as? String, "user")
            XCTAssertTrue(reassigned["assignee_identity"] is NSNull)
        }
        let codex: EncryptedUserTaskRecord = try decodeFixture(serverTaskFixture())
        XCTAssertThrowsError(try service.updateBody(for: codex,
            patch: UserTaskUpdateInput(assigneeType: .externalAI, assigneeIdentity: .legacyOpenCode),
            key: key, timestamp: 1_788_883_201), "Historical attribution must never enable a new OpenCode assignment")
    }

    // contract-test: supporting surface=gui.apple assertions=tasks.lifecycle.visible,tasks.content.client-encrypted
    func testRetainedTaskBoardDecodesHistoricalAssignmentAndBlockerMetadata() throws {
        struct Board: Decodable { let tasks: [TaskBoardRecord] }
        // The personal dev board retained these values after the supported
        // assignment list changed. Keep content synthetic and exercise the two
        // fields independently so fixing one cannot hide the next load failure.
        var historicalAssignment = serverTaskFixture()
        historicalAssignment["assignee_identity"] = "opencode"
        var historicalBlocker = serverTaskFixture()
        historicalBlocker["status"] = "blocked"
        historicalBlocker["blocked_reason_code"] = "missing_execution_context"
        let board: Board = try decodeFixture(["tasks": [historicalAssignment, historicalBlocker]])
        guard case .task(let assigned) = board.tasks[0].value,
              case .task(let blocked) = board.tasks[1].value else {
            return XCTFail("Historical metadata must remain an encrypted Task record")
        }
        XCTAssertEqual(assigned.assigneeIdentity, .legacyOpenCode)
        XCTAssertEqual(assigned.assigneeIdentity?.title, "OpenCode")
        XCTAssertEqual(assigned.encryptedTitle, "synthetic-ciphertext")
        XCTAssertEqual(blocked.status, .blocked)
        XCTAssertEqual(blocked.blockedReasonCode, .legacyMissingExecutionContext)

        for field in ["assignee_identity", "blocked_reason_code"] {
            var incompatible = serverTaskFixture()
            incompatible[field] = "future_unknown_value"
            XCTAssertThrowsError(try decodeFixture(incompatible) as EncryptedUserTaskRecord,
                                 "Read compatibility is limited to known historical metadata")
        }
    }

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

    #if DEBUG
    // contract-test: supporting surface=gui.apple assertions=tasks.lifecycle.visible,tasks.surface.semantic-parity
    func testLargeBoardFixtureKeepsFullTasksPlansAndWorkflowTotalsWhileFiltering() {
        let store = TasksWorkspaceStore()
        store.installPreview(manyBacklog: true)
        XCTAssertEqual(store.boardItems.count, 59)
        XCTAssertEqual(store.plans.count, 2)
        XCTAssertEqual(store.visibleBoardItems.filter { $0.status == .backlog }.count, 55)
        XCTAssertEqual(store.visiblePlans.filter { $0.status.boardColumn == .backlog }.count, 1)
        XCTAssertEqual(store.visibleBoardItems.filter { $0.status == .done }.count, 1,
                       "Workflow projections share the Tasks render window")
        XCTAssertEqual(store.visiblePlans.filter { $0.status.boardColumn == .done }.count, 1)
        store.searchText = "#Self driving ballpit"
        XCTAssertEqual(store.visibleBoardItems.count, 2)
        XCTAssertTrue(store.visiblePlans.isEmpty)
        store.searchText = "Extra backlog task 53"
        XCTAssertEqual(store.visibleBoardItems.map(\.id), ["preview-extra-52"],
                       "Search includes records beyond the initially mounted window")
        store.searchText = ""
        XCTAssertEqual(store.visibleBoardItems.count, 59)
        XCTAssertEqual(store.visiblePlans.count, 2)
        store.reset(accountID: nil)
        XCTAssertTrue(store.visibleBoardItems.isEmpty)
        XCTAssertTrue(store.visiblePlans.isEmpty)
        XCTAssertTrue(store.searchText.isEmpty)
    }
    #endif

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
    // contract-test: supporting surface=gui.apple assertions=tasks.lifecycle.visible,tasks.surface.semantic-parity
    func testWorkspaceSearchMatchesWebLabelsAssigneesPlanStatusAndProjectNames() {
        let store = TasksWorkspaceStore()
        store.installPreview()
        XCTAssertEqual(store.filterTags, ["Self driving ballpit", "OpenMates"])
        store.searchText = " #Research "
        XCTAssertEqual(store.visibleBoardItems.count, 2, "A leading label marker applies to titles too")
        store.searchText = "external_ai"
        XCTAssertTrue(store.visibleBoardItems.isEmpty)
        store.searchText = "openmates"
        XCTAssertEqual(store.visibleBoardItems.count, 3, "Assignment is searchable even without that label")
        store.searchText = "user"
        XCTAssertEqual(store.visibleBoardItems.count, 2, "Workflow projections retain the web human assignment")
        store.searchText = "completed"
        XCTAssertEqual(store.visiblePlans.map(\.id), ["preview-plan-completed"])
        store.searchText = "#OpenMates"
        XCTAssertEqual(store.visiblePlans.count, 2, "Linked Project names participate in Plan search")
        store.searchText = "#"
        XCTAssertEqual(store.visibleBoardItems.count, 6)
        XCTAssertEqual(store.visiblePlans.count, 2)
        store.searchText = "research#"
        XCTAssertTrue(store.visibleBoardItems.isEmpty, "Only the leading marker is removed")
    }

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

    // contract-test: supporting surface=gui.apple assertions=apple-task-board.drag-move
    func testTaskMovePublishesFirstPositionWithoutChangingEncryptedRecord() async throws {
        let store = TasksWorkspaceStore()
        store.installPreview()
        let original = try XCTUnwrap(store.boardItems.compactMap { item -> UserTaskItem? in
            if case .task(let task) = item, task.id == "preview-backlog-1" { return task }; return nil
        }.first)
        let started = expectation(description: "move suspended")
        var continuation: CheckedContinuation<UserTaskItem, Error>?
        store.debugTaskMover = { task, status, position in
            XCTAssertEqual(status, .todo)
            XCTAssertEqual(position, -1)
            return try await withCheckedThrowingContinuation { continuation = $0; started.fulfill() }
        }
        let operation = Task { await store.moveTask(original, to: .todo) }
        await fulfillment(of: [started], timeout: 3)
        let pending = try XCTUnwrap(store.boardItems.first { $0.id == original.id })
        XCTAssertEqual(pending.status, .todo)
        XCTAssertEqual(pending.position, -1)
        if case .task(let task) = pending {
            XCTAssertEqual(task.record.status, .backlog)
            XCTAssertEqual(task.record.encryptedTitle, original.record.encryptedTitle)
            XCTAssertEqual(task.record.version, original.record.version)
        } else { XCTFail("A normal task must stay a task") }
        XCTAssertTrue(store.isSaving)
        continuation?.resume(returning: original.placing(on: .todo, at: -1))
        await operation.value
        XCTAssertFalse(store.isSaving)
        XCTAssertNil(store.interactionErrorMessage)
        XCTAssertEqual(store.firstPosition(in: .todo, excluding: "another-task"), -2)
        XCTAssertEqual(store.firstPosition(in: .done, excluding: original.id), -1,
                       "Workflow projections participate in destination ordering")
    }

    // contract-test: supporting surface=gui.apple assertions=apple-task-board.drag-move
    func testFailedMoveRestoresOnlyOriginalCardAndPreservesReader() async throws {
        let store = TasksWorkspaceStore()
        store.installPreview()
        store.openTask("preview-backlog-1")
        let task = try XCTUnwrap(store.selectedTask)
        store.debugTaskMover = { _, _, _ in throw UserTasksError.invalidResponse }
        await store.moveTask(task, to: .done)
        XCTAssertEqual(store.selectedTask?.status, .backlog)
        XCTAssertEqual(store.selectedTask?.position, task.position)
        XCTAssertEqual(store.boardItems.count, 6)
        XCTAssertNotNil(store.interactionErrorMessage)
        XCTAssertNil(store.errorMessage, "Move feedback must not hide the retained board")
        XCTAssertFalse(store.isSaving)
    }

    // contract-test: supporting surface=gui.apple assertions=apple-task-board.drag-move,tasks.content.client-encrypted
    func testOldMoveCannotRepublishAfterAccountReset() async throws {
        let store = TasksWorkspaceStore()
        store.installPreview()
        store.openTask("preview-backlog-1")
        let task = try XCTUnwrap(store.selectedTask)
        let started = expectation(description: "old move suspended")
        var continuation: CheckedContinuation<UserTaskItem, Error>?
        store.debugTaskMover = { _, _, _ in
            try await withCheckedThrowingContinuation { continuation = $0; started.fulfill() }
        }
        let operation = Task { await store.moveTask(task, to: .todo) }
        await fulfillment(of: [started], timeout: 3)
        store.reset(accountID: nil)
        continuation?.resume(returning: task.placing(on: .todo, at: -1))
        await operation.value
        XCTAssertTrue(store.boardItems.isEmpty)
        XCTAssertNil(store.selectedTask)
        XCTAssertNil(store.interactionErrorMessage)
        XCTAssertFalse(store.isSaving)
    }

    // contract-test: supporting surface=gui.apple assertions=apple-task-board.workflow-run,tasks.workflow-projections.read-only
    func testWorkflowProjectionOpensExactRunAndRejectsUnknownTaskIDs() {
        let store = TasksWorkspaceStore()
        store.installPreview()
        store.openWorkflowRun("preview-backlog-1")
        XCTAssertNil(store.selectedWorkflowRun)
        store.openWorkflowRun("missing-projection")
        XCTAssertNil(store.selectedWorkflowRun)
        store.openWorkflowRun("preview-workflow")
        XCTAssertEqual(store.selectedWorkflowRun?.workflowId, "weather-report")
        XCTAssertEqual(store.selectedWorkflowRun?.workflowRunId, "weather-report-run")
        XCTAssertNil(store.selectedTask)
    }
    #endif
}

@MainActor
private final class TaskFenceTeamService: TeamWorkspaceServing {
    private let values = ["team-a", "team-b"].map { id in
        TeamWorkspaceTeam(id: id, name: id, description: "", role: .member, status: "active",
            profileImageMetadata: .generated, zeroBalance: 0, createdAt: 1, updatedAt: 1,
            key: SymmetricKey(size: .bits256))
    }

    func listTeams(fence: TeamWorkspaceFence) async throws -> [TeamWorkspaceTeam] { values }
    func getTeam(_ id: String, fence: TeamWorkspaceFence) async throws -> TeamWorkspaceTeam {
        guard let value = values.first(where: { $0.id == id }) else { throw TeamWorkspaceError.unavailableTeam }
        return value
    }
}
