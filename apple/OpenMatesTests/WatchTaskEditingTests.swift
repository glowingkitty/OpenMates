// Network-free task editing proof using production encryption and service.
import CryptoKit
import Foundation
import XCTest
@testable import OpenMates

@MainActor
final class WatchTaskEditingTests: XCTestCase {
    // contract-test: supporting surface=gui.apple assertions=apple-watch.tasks.edit-private
    func testSaveEncryptsPrivateFieldsAndPublishesReturnedVersionAndColumn() async throws {
        let fixture = try await Fixture.make()
        let service = fixture.service()
        let original = try XCTUnwrap(service.tasks.first)
        var draft = WatchTaskDraft(item: original)
        draft.title = "  Updated private title  "
        draft.description = "Updated private description"
        draft.group = .done
        draft.priority = 4
        let saved = try await service.saveTask(original, draft: draft)
        let body = try XCTUnwrap(fixture.lastBody)
        XCTAssertEqual(fixture.requests, 1)
        XCTAssertEqual(fixture.lastPath, "/v1/user-tasks/watch-edit-fixture")
        XCTAssertEqual(body["version"] as? Int, 1)
        XCTAssertEqual(body["status"] as? String, "done")
        XCTAssertEqual(body["priority"] as? Int, 4)
        XCTAssertNil(body["title"])
        XCTAssertNil(body["description"])
        XCTAssertNil(body["encrypted_task_key"])
        XCTAssertNil(body["key_wrappers"])
        let encryptedTitle = try XCTUnwrap(body["encrypted_title"] as? String)
        let encryptedDescription = try XCTUnwrap(body["encrypted_description"] as? String)
        XCTAssertNotEqual(encryptedTitle, draft.title)
        XCTAssertNotEqual(encryptedDescription, draft.description)
        let title = try await CryptoManager.shared.decryptContent(base64String: encryptedTitle, key: fixture.taskKey)
        let description = try await CryptoManager.shared.decryptContent(base64String: encryptedDescription, key: fixture.taskKey)
        XCTAssertEqual(title, "Updated private title")
        XCTAssertEqual(description, draft.description)
        XCTAssertEqual(saved.title, title)
        XCTAssertEqual(saved.description, description)
        XCTAssertEqual(saved.record?.version, 2)
        XCTAssertEqual(saved.group, .done)
        XCTAssertEqual(saved.priority, 4)
        XCTAssertEqual(service.tasks, [saved])
        XCTAssertFalse(service.isSavingTask)
    }

    // contract-test: supporting surface=gui.apple assertions=apple-watch.tasks.edit-private
    func testFailurePreservesDraftAndOriginalTaskAndRetryUsesSameVersion() async throws {
        let fixture = try await Fixture.make()
        let service = fixture.service()
        let original = try XCTUnwrap(service.tasks.first)
        var draft = WatchTaskDraft(item: original)
        draft.description = "Keep this draft"
        draft.group = .blocked
        fixture.shouldFail = true
        do {
            _ = try await service.saveTask(original, draft: draft)
            XCTFail("Failed request must not report success")
        } catch {}
        XCTAssertEqual(service.tasks, [original])
        XCTAssertEqual(draft.description, "Keep this draft")
        XCTAssertEqual(draft.group, .blocked)
        XCTAssertFalse(service.isSavingTask)
        fixture.shouldFail = false
        let saved = try await service.saveTask(original, draft: draft)
        XCTAssertEqual(saved.description, draft.description)
        XCTAssertEqual(saved.group, .blocked)
        XCTAssertEqual(fixture.lastBody?["version"] as? Int, 1)
    }

    // contract-test: supporting surface=gui.apple assertions=apple-watch.tasks.edit-private
    func testEmptyTitleInvalidPriorityAndUnchangedDraftDoNotWrite() async throws {
        let fixture = try await Fixture.make()
        let service = fixture.service()
        let original = try XCTUnwrap(service.tasks.first)
        var draft = WatchTaskDraft(item: original)
        draft.title = " \n "
        await assertSaveFails(service, item: original, draft: draft, expected: .invalidDraft)
        draft = WatchTaskDraft(item: original)
        draft.priority = 5
        await assertSaveFails(service, item: original, draft: draft, expected: .invalidDraft)
        let unchanged = try await service.saveTask(original, draft: WatchTaskDraft(item: original))
        XCTAssertEqual(unchanged, original)
        XCTAssertEqual(fixture.requests, 0)
    }

    // contract-test: supporting surface=gui.apple assertions=apple-watch.tasks.edit-private,apple-watch.lists.read-only-private
    func testTeamReadonlyWorkflowAndMissingVersionAreNeverEditable() async throws {
        for patch: [String: Any] in [["team_id": "team-other"], ["read_only": true],
                                    ["source": "workflow_run", "workflow_id": "workflow-one", "title": "Workflow task"],
                                    ["version": NSNull()]] {
            let fixture = try await Fixture.make(patch: patch)
            let service = fixture.service()
            let item = try XCTUnwrap(service.tasks.first)
            XCTAssertFalse(service.canEditTask(item))
            var draft = WatchTaskDraft(item: item)
            draft.title = "Must not write"
            await assertSaveFails(service, item: item, draft: draft, expected: .readOnly)
            XCTAssertEqual(fixture.requests, 0)
        }
    }

    // contract-test: supporting surface=gui.apple assertions=apple-watch.tasks.edit-private
    func testChangedAccountAndGenerationPreventDispatch() async throws {
        let fixture = try await Fixture.make()
        let service = fixture.service()
        let item = try XCTUnwrap(service.tasks.first)
        var draft = WatchTaskDraft(item: item)
        draft.group = .done
        fixture.currentAccountID = "different-account"
        await assertSaveFails(service, item: item, draft: draft, expected: .accountChanged)
        fixture.currentAccountID = fixture.accountID
        WatchChatAccountLifecycle.invalidate()
        await assertSaveFails(service, item: item, draft: draft, expected: .accountChanged)
        XCTAssertEqual(fixture.requests, 0)
    }

    // contract-test: supporting surface=gui.apple assertions=apple-watch.tasks.edit-private
    func testInflightOldAccountResponseCannotPublishSuccess() async throws {
        let fixture = try await Fixture.make()
        let service = fixture.service()
        let item = try XCTUnwrap(service.tasks.first)
        var draft = WatchTaskDraft(item: item)
        draft.title = "Draft from old account"
        fixture.shouldSuspend = true
        let save = Task { try await service.saveTask(item, draft: draft) }
        await fixture.waitForSuspension()
        fixture.currentAccountID = "new-account"
        fixture.resume()
        do {
            _ = try await save.value
            XCTFail("A stale response must not report success")
        } catch {
            XCTAssertEqual(error as? WatchTaskEditingError, .accountChanged)
        }
        XCTAssertEqual(service.tasks, [item])
        XCTAssertEqual(draft.title, "Draft from old account")
        XCTAssertFalse(service.isSavingTask)
    }

    // contract-test: supporting surface=gui.apple assertions=apple-watch.tasks.edit-private
    func testWrongTaskResponseAndUnadvancedVersionCannotPublishSuccess() async throws {
        for patch: [String: Any] in [["task_id": "different-task"], ["version": 1], ["team_id": "different-team"]] {
            let fixture = try await Fixture.make()
            fixture.responsePatch = patch
            let service = fixture.service()
            let item = try XCTUnwrap(service.tasks.first)
            var draft = WatchTaskDraft(item: item)
            draft.group = .done
            await assertSaveFails(service, item: item, draft: draft, expected: .invalidResponse)
            XCTAssertEqual(service.tasks, [item])
        }
    }

    // contract-test: supporting surface=gui.apple assertions=apple-watch.tasks.edit-private,apple-watch.lists.read-only-private
    func testTaskRefreshUsesVerifiedContextAndDropsInflightOldAccountRows() async throws {
        let fixture = try await Fixture.make()
        fixture.shouldSuspend = true
        let service = fixture.service(seedRows: false)
        let refresh = Task { await service.refreshTasks() }
        await fixture.waitForSuspension()
        fixture.currentAccountID = "new-account"
        fixture.resume()
        await refresh.value
        XCTAssertTrue(service.tasks.isEmpty)
        XCTAssertTrue(service.tasksError)
        XCTAssertFalse(service.isLoadingTasks)
    }

    // contract-test: supporting surface=gui.apple assertions=apple-watch.lists.read-only-private
    func testWorkflowListRefreshUsesVerifiedContextForCurrentAccount() async throws {
        let fixture = try await Fixture.make()
        let service = fixture.service(seedRows: false)
        await service.refreshWorkflows()
        XCTAssertEqual(fixture.lastPath, "/v1/workflows")
        XCTAssertEqual(service.workflows.map(\.id), ["workflow-fixture"])
        XCTAssertEqual(service.workflows.first?.title, "Old account workflow")
        XCTAssertFalse(service.workflowsError)
    }

    // contract-test: supporting surface=gui.apple assertions=apple-watch.lists.read-only-private
    func testWorkflowListRefreshDropsHeldResponseAfterAuthorityChange() async throws {
        let fixture = try await Fixture.make()
        let service = fixture.service(seedRows: false)
        // First show a valid account's list so revocation proves cleanup as well
        // as refusing newly returned private titles.
        await service.refreshWorkflows()
        XCTAssertEqual(service.workflows.count, 1)
        fixture.shouldSuspend = true
        let refresh = Task { await service.refreshWorkflows() }
        await fixture.waitForSuspension()
        fixture.currentAccountID = "new-account"
        fixture.resume()
        await refresh.value
        XCTAssertTrue(service.workflows.isEmpty)
        XCTAssertTrue(service.workflowsError)
        XCTAssertFalse(service.isLoadingWorkflows)
    }

    // contract-test: supporting surface=gui.apple assertions=apple-watch.tasks.edit-private
    func testExpiredSessionAndChangedServerContextFailClosed() async throws {
        let fixture = try await Fixture.make()
        let current = WatchTaskRequestContext(accountID: fixture.accountID,
            generation: WatchChatAccountLifecycle.generation, serverProfile: ServerProfile.current(),
            currentAccountID: { fixture.currentAccountID })
        try current.check()
        let otherProfile: ServerProfile = ServerProfile.current() == .production ? .development : .production
        let wrongServer = WatchTaskRequestContext(accountID: fixture.accountID,
            generation: WatchChatAccountLifecycle.generation, serverProfile: otherProfile,
            currentAccountID: { fixture.currentAccountID })
        XCTAssertThrowsError(try wrongServer.check())
        PairSessionDeadlineStore.save(userID: fixture.accountID, deadline: Int(Date().timeIntervalSince1970) - 1)
        defer { PairSessionDeadlineStore.clear() }
        XCTAssertThrowsError(try current.check())
    }

    private func assertSaveFails(_ service: WatchHubDataService, item: WatchTaskListItem,
                                 draft: WatchTaskDraft, expected: WatchTaskEditingError) async {
        do {
            _ = try await service.saveTask(item, draft: draft)
            XCTFail("Save must reject this request")
        } catch {
            XCTAssertEqual(error as? WatchTaskEditingError, expected)
        }
    }

    @MainActor
    private final class Fixture {
        let accountID = "watch-task-test-\(UUID().uuidString)"
        var currentAccountID: String?
        let masterKey = SymmetricKey(size: .bits256)
        let taskKey = SymmetricKey(size: .bits256)
        var wire: [String: Any] = [:]
        var item: WatchTaskListItem!
        var requests = 0
        var lastBody: [String: Any]?
        var lastPath: String?
        var shouldFail = false
        var shouldSuspend = false
        var responsePatch: [String: Any] = [:]
        private var suspended: CheckedContinuation<Void, Never>?
        private var suspensionWaiter: CheckedContinuation<Void, Never>?

        static func make(patch: [String: Any] = [:]) async throws -> Fixture {
            let fixture = Fixture()
            fixture.currentAccountID = fixture.accountID
            fixture.wire = ["task_id": "watch-edit-fixture", "source": "user", "status": "todo",
                            "version": 1, "priority": 0, "position": 0, "updated_at": 1,
                            "encrypted_task_key": try await CryptoManager.shared.wrapChatKey(fixture.taskKey, masterKey: fixture.masterKey),
                            "encrypted_title": try await CryptoManager.shared.encryptContent("Original task", key: fixture.taskKey),
                            "encrypted_description": try await CryptoManager.shared.encryptContent("Original description", key: fixture.taskKey)]
            fixture.wire.merge(patch) { _, replacement in replacement }
            let decoder = JSONDecoder()
            decoder.keyDecodingStrategy = .convertFromSnakeCase
            let record = try decoder.decode(WatchTaskRecord.self, from: JSONSerialization.data(withJSONObject: fixture.wire))
            fixture.item = await WatchHubDataService.openTask(record, masterKey: fixture.masterKey)
            return fixture
        }

        func service(seedRows: Bool = true) -> WatchHubDataService {
            WatchHubDataService(userId: accountID, fixtureTasks: seedRows ? [item] : nil,
                currentAccountID: { self.currentAccountID }, taskDependencies: WatchTaskDependencies(
                    request: { method, path, body, context in
                        try context.check()
                        self.requests += 1
                        self.lastPath = path
                        if let body { self.lastBody = try JSONSerialization.jsonObject(with: body) as? [String: Any] }
                        if self.shouldSuspend {
                            await withCheckedContinuation { continuation in
                                self.suspended = continuation
                                self.suspensionWaiter?.resume()
                                self.suspensionWaiter = nil
                            }
                        }
                        if self.shouldFail { throw URLError(.notConnectedToInternet) }
                        if method == .get {
                            if path == "/v1/workflows" {
                                return try JSONSerialization.data(withJSONObject: ["workflows": [[
                                    "id": "workflow-fixture", "title": "Old account workflow",
                                    "enabled": true, "updated_at": 1,
                                ]]])
                            }
                            return try JSONSerialization.data(withJSONObject: ["tasks": [self.wire]])
                        }
                        var returned = self.wire
                        returned.merge(self.lastBody ?? [:]) { _, replacement in replacement }
                        returned["version"] = (self.wire["version"] as? Int ?? 0) + 1
                        returned.merge(self.responsePatch) { _, replacement in replacement }
                        return try JSONSerialization.data(withJSONObject: ["task": returned])
                    }, masterKey: { _ in self.masterKey }))
        }

        func waitForSuspension() async {
            if suspended != nil { return }
            await withCheckedContinuation { suspensionWaiter = $0 }
        }

        func resume() {
            suspended?.resume()
            suspended = nil
        }
    }
}
