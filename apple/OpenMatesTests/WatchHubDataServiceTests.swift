import CryptoKit
import Foundation
import XCTest
@testable import OpenMates

final class WatchHubDataServiceTests: XCTestCase {
    // contract-test: supporting surface=gui.apple assertions=apple-watch.chats.browse-search-open
    func testPullRefreshRequiresFingerTopOverscrollAndOneRelease() {
        var pull = WatchPullRefreshGesture()
        pull.observe(topOffset: 80)
        XCTAssertFalse(pull.release(), "Crown or programmatic movement must not refresh")
        pull.begin()
        pull.observe(topOffset: -120)
        pull.observe(topOffset: -20)
        XCTAssertFalse(pull.release(), "Dragging down from the middle is ordinary scrolling")
        pull.begin()
        pull.observe(topOffset: 47)
        XCTAssertFalse(pull.release(), "A small pull must not refresh")
        pull.begin()
        pull.observe(topOffset: .nan)
        pull.observe(topOffset: 60)
        pull.observe(topOffset: 0)
        XCTAssertTrue(pull.release(), "A released top pull survives native bounce settling")
        XCTAssertFalse(pull.release(), "One pull produces only one request")
        pull.begin()
        pull.observe(topOffset: 60)
        pull.cancel()
        XCTAssertFalse(pull.release(), "Disappearance cancels an unfinished gesture")
    }

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

    @MainActor
    // contract-test: supporting surface=gui.apple assertions=apple-workspaces.watch-retention,apple-workspaces.isolation
    func testWatchMaintainsFiftyPerStatusThenReopensAllUnvisitedColumnsOffline() async throws {
        let directory = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        defer { try? FileManager.default.removeItem(at: directory) }
        let cache = WatchHubOfflineCache(directory: directory)
        let master = SymmetricKey(size: .bits256)
        let account = "watch-hub-unit-" + UUID().uuidString
        var current: String? = account
        var requested: [String] = []
        let dependencies = WatchTaskDependencies(request: { _, path, _, context in
            try context.check(); requested.append(path)
            let status = try XCTUnwrap(WatchTaskGroup.allCases.first { path.contains("status=" + $0.status + "&") }).status
            let rows: [[String: Any]] = (0..<55).map { index in
                ["task_id": status + "-" + String(index), "source": "workflow_run", "workflow_id": "parent-workflow",
                 "title": "Private title " + String(index), "status": status, "position": index]
            }
            return try JSONSerialization.data(withJSONObject: ["tasks": rows])
        }, masterKey: { _ in master })
        let online = WatchHubDataService(userId: account, currentAccountID: { current }, taskDependencies: dependencies, offlineCache: cache)
        await online.refreshTasks()
        XCTAssertEqual(requested, WatchTaskGroup.allCases.map { "/v1/user-tasks?status=\($0.status)&limit=50" })
        XCTAssertEqual(online.tasks.count, 250)
        for group in WatchTaskGroup.allCases { XCTAssertEqual(online.tasks.filter { $0.group == group }.count, 50) }
        let offline = WatchHubDataService(userId: account, currentAccountID: { current },
            taskDependencies: WatchTaskDependencies(request: { _, _, _, _ in throw URLError(.notConnectedToInternet) }, masterKey: { _ in master }), offlineCache: cache)
        await offline.loadCachedTasks()
        XCTAssertEqual(offline.tasks.map(\.id), online.tasks.map(\.id))
        XCTAssertTrue(offline.tasksError, "Cached data must not grant fresh write authority")
        let files = try FileManager.default.contentsOfDirectory(at: directory, includingPropertiesForKeys: nil)
        XCTAssertEqual(files.count, 5)
        for file in files { XCTAssertFalse(String(decoding: try Data(contentsOf: file), as: UTF8.self).contains("Private title")) }
        current = "foreign-account"
        await offline.loadCachedTasks()
        XCTAssertTrue(offline.tasks.isEmpty)
    }

    @MainActor
    // contract-test: supporting surface=gui.apple assertions=apple-workspaces.isolation,apple-workspaces.watch-retention
    func testWatchHubCacheRejectsOtherAccountServerTeamKeyAndOversizedEntry() async throws {
        let directory = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        defer { try? FileManager.default.removeItem(at: directory) }
        let cache = WatchHubOfflineCache(directory: directory)
        let key = SymmetricKey(size: .bits256)
        let scope = WatchWorkflowDetailScope.capture(accountID: "cache-owner")
        try await cache.save(Data("private graph".utf8), key: "workflow-one", scope: scope, masterKey: key)
        let opened = await cache.load(key: "workflow-one", scope: scope, masterKey: key)
        XCTAssertEqual(opened, Data("private graph".utf8))
        let foreign = await cache.load(key: "workflow-one", scope: .capture(accountID: "other"), masterKey: key)
        XCTAssertNil(foreign)
        let otherServer = WatchWorkflowDetailScope(accountID: scope.accountID, profile: .custom(domain: "other.example.invalid"), generation: scope.generation, teamID: nil)
        let serverData = await cache.load(key: "workflow-one", scope: otherServer, masterKey: key)
        XCTAssertNil(serverData)
        let team = WatchWorkflowDetailScope.capture(accountID: "cache-owner", teamID: "team-other")
        let teamData = await cache.load(key: "workflow-one", scope: team, masterKey: key)
        XCTAssertNil(teamData)
        let wrongKey = await cache.load(key: "workflow-one", scope: scope, masterKey: SymmetricKey(size: .bits256))
        XCTAssertNil(wrongKey)
        do {
            try await cache.save(Data(repeating: 1, count: WatchHubOfflineCache.maximumEntryBytes + 1), key: "workflow-one", scope: scope, masterKey: key)
            XCTFail("Oversized data must preserve the prior complete cache entry")
        } catch { }
        let preserved = await cache.load(key: "workflow-one", scope: scope, masterKey: key)
        XCTAssertEqual(preserved, opened)
        try await cache.removeAll()
        let removed = await cache.load(key: "workflow-one", scope: scope, masterKey: key)
        XCTAssertNil(removed)
    }

    @MainActor
    // contract-test: supporting surface=gui.apple assertions=apple-workspaces.isolation,apple-workspaces.watch-retention
    func testEraseDuringSuspendedCacheValidationCannotRecreateLoggedOutData() async throws {
        let directory = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        defer { try? FileManager.default.removeItem(at: directory) }
        let gate = WatchHubCacheValidationGate()
        let cache = WatchHubOfflineCache(directory: directory, verifyScope: { _ in await gate.check() })
        let scope = WatchWorkflowDetailScope.capture(accountID: "erase-race-owner")
        let key = SymmetricKey(size: .bits256)
        let save = Task { try await cache.save(Data("private graph".utf8), key: "workflow", scope: scope, masterKey: key) }
        await gate.waitForSuspension()
        try await cache.removeAll()
        await gate.resume()
        do { try await save.value; XCTFail("Old validation must not resurrect the erased account cache") }
        catch is CancellationError { }
        let restored = await cache.load(key: "workflow", scope: scope, masterKey: key)
        XCTAssertNil(restored)
        XCTAssertFalse(FileManager.default.fileExists(atPath: directory.path))
    }

    @MainActor
    // contract-test: supporting surface=gui.apple assertions=apple-workspaces.watch-retention
    func testRefusedWorkflowCacheWriteKeepsFreshOnlineRowsVisible() async throws {
        let directory = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        defer { try? FileManager.default.removeItem(at: directory) }
        let key = SymmetricKey(size: .bits256)
        let account = "budget-unit-" + UUID().uuidString
        let title = String(repeating: "a", count: WatchHubOfflineCache.maximumEntryBytes + 1)
        let data = try JSONSerialization.data(withJSONObject: ["workflows": [["id": "large-workflow", "title": title,
            "enabled": false, "updated_at": 1]]])
        let cache = WatchHubOfflineCache(directory: directory)
        let service = WatchHubDataService(userId: account, currentAccountID: { account },
            taskDependencies: WatchTaskDependencies(request: { _, _, _, context in try context.check(); return data }, masterKey: { _ in key }), offlineCache: cache)
        await service.refreshWorkflows()
        XCTAssertEqual(service.workflows.map(\.id), ["large-workflow"])
        XCTAssertFalse(service.workflowsError)
        let offline = await cache.load(key: "workflows", scope: .capture(accountID: account), masterKey: key)
        XCTAssertNil(offline, "An oversized inventory is never reported as durably cached")
    }

    @MainActor
    // contract-test: supporting surface=gui.apple assertions=apple-workspaces.isolation
    func testAuthenticatedOfflineReadScopeDoesNotGrantWriteAuthority() throws {
        let account = "offline-read-owner"
        let read = WatchTaskRequestContext(accountID: account, generation: WatchChatAccountLifecycle.generation,
            serverProfile: ServerProfile.current(), currentAccountID: { account }, writesAllowed: { false })
        XCTAssertNoThrow(try read.check())
        var write = read; write.isWrite = true
        XCTAssertThrowsError(try write.check())
    }

    @MainActor
    // contract-test: supporting surface=gui.apple assertions=apple-workspaces.watch-retention,apple-workspaces.isolation
    func testTaskMovingBetweenStatusResponsesHasOneFreshOnlineAndOfflineRow() async throws {
        for laterTimestamp in [200, 100] {
            let directory = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
            defer { try? FileManager.default.removeItem(at: directory) }
            let cache = WatchHubOfflineCache(directory: directory)
            let key = SymmetricKey(size: .bits256)
            let account = "moving-task-" + UUID().uuidString
            let dependencies = WatchTaskDependencies(request: { _, path, _, context in
                try context.check()
                var rows: [[String: Any]] = []
                if path.contains("status=backlog&") || path.contains("status=todo&") {
                    let moved = path.contains("status=todo&")
                    rows = [["task_id": "moving-task", "source": "workflow_run", "workflow_id": "workflow-parent",
                        "title": moved ? "Moved title" : "Prior title", "status": moved ? "todo" : "backlog",
                        "updated_at": moved ? laterTimestamp : 100]]
                }
                return try JSONSerialization.data(withJSONObject: ["tasks": rows])
            }, masterKey: { _ in key })
            let online = WatchHubDataService(userId: account, currentAccountID: { account }, taskDependencies: dependencies, offlineCache: cache)
            await online.refreshTasks()
            XCTAssertEqual(online.tasks.count, 1)
            XCTAssertEqual(online.tasks.first?.group, .todo)
            XCTAssertEqual(online.tasks.first?.title, "Moved title")
            let backlog = await cache.load(key: "tasks-backlog", scope: .capture(accountID: account), masterKey: key)
            XCTAssertTrue(try makeAPIClientDecoder().decode(WatchTaskListResponse.self, from: XCTUnwrap(backlog)).tasks.isEmpty)
            let offline = WatchHubDataService(userId: account, currentAccountID: { account }, taskDependencies: dependencies, offlineCache: cache)
            await offline.loadCachedTasks()
            XCTAssertEqual(offline.tasks.map(\.id), ["moving-task"])
            XCTAssertEqual(offline.tasks.first?.group, .todo)
            XCTAssertEqual(offline.tasks.first?.title, "Moved title")
        }
    }

    private func makeAPIClientDecoder() -> JSONDecoder {
        let decoder = JSONDecoder()
        decoder.keyDecodingStrategy = .convertFromSnakeCase
        return decoder
    }
}

private actor WatchHubCacheValidationGate {
    private var held: CheckedContinuation<Bool, Never>?
    private var observer: CheckedContinuation<Void, Never>?
    func check() async -> Bool {
        await withCheckedContinuation { continuation in
            held = continuation; observer?.resume(); observer = nil
        }
    }
    func waitForSuspension() async {
        if held != nil { return }
        await withCheckedContinuation { observer = $0 }
    }
    func resume() { held?.resume(returning: true); held = nil }
}
