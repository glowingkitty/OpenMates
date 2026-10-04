// Synthetic Workflow widget proofs; no transport, account or inference requests.
// Specification: specifications/features/apple-workflow-widget/specification.yml
import CryptoKit
import XCTest
@testable import OpenMates

@MainActor
final class WorkflowWidgetTests: XCTestCase {
    private let owner = String(repeating: "a", count: 64)
    private func storage() -> (WidgetWorkflowsStorage, UserDefaults) {
        let defaults = UserDefaults(suiteName: "org.openmates.synthetic.widget." + UUID().uuidString)!
        let key = SymmetricKey(size: .bits256)
        return (.init(defaults: defaults, loadKey: { _ in key }, deleteKey: {}), defaults)
    }
    // contract-test: supporting surface=gui.apple assertions=apple-workflow-widget.selection,apple-workflow-widget.private-cache
    func testEncryptedInventoryAndIssuedActionExpireAndConsume() throws {
        let (store, defaults) = storage()
        store.activate(owner: owner)
        let snapshot = WidgetWorkflowsSnapshot(owner: owner, teamID: "synthetic-team", updatedAt: Date(), workflows: [
            .init(id: "synthetic-workflow", title: "Synthetic private title", versionID: "v1")])
        try store.save(snapshot)
        let bytes = try XCTUnwrap(defaults.data(forKey: WidgetWorkflowsStorage.snapshotKey))
        XCTAssertFalse(String(decoding: bytes, as: UTF8.self).contains("Synthetic private title"))
        XCTAssertEqual(store.load(), snapshot)
        let route = WidgetWorkflowRunRoute(workflowID: "synthetic-workflow", owner: owner, teamID: "synthetic-team", requestID: UUID())
        let now = Date(timeIntervalSince1970: 1000)
        XCTAssertNil(store.issuedVersion(route, now: now))
        try store.authorize(route, now: now)
        XCTAssertEqual(store.issuedVersion(route, now: now), "v1")
        XCTAssertNil(store.issuedVersion(route, now: now.addingTimeInterval(121)))
        store.consume(route)
        XCTAssertNil(store.issuedVersion(route, now: now))
        store.activate(owner: String(repeating: "b", count: 64))
        XCTAssertNil(store.load())
        XCTAssertThrowsError(try store.authorize(route, now: now))
    }
    // contract-test: supporting surface=gui.apple assertions=apple-workflow-widget.run-current-scope
    func testTypedRunLinksRejectMalformedOrForeignContext() throws {
        let request = UUID()
        let url = try XCTUnwrap(WidgetWorkflowsLinks.run("workflow-one", owner: owner, teamID: "team-one", requestID: request))
        XCTAssertEqual(WidgetWorkflowsLinks.route(url), .init(workflowID: "workflow-one", owner: owner, teamID: "team-one", requestID: request))
        XCTAssertNil(WidgetWorkflowsLinks.route(URL(string: url.absoluteString + "&owner=" + owner)!))
        XCTAssertNil(WidgetWorkflowsLinks.route(URL(string: url.absoluteString + "#injected")!))
        XCTAssertNil(WidgetWorkflowsLinks.run("workflow/escape", owner: owner, teamID: nil))
        let scopedOwner = WidgetWorkflowsOwner.identity(accountID: "synthetic", apiBaseURL: URL(string: "https://example.org")!, teamID: "team-one")
        let route = WidgetWorkflowRunRoute(workflowID: "workflow-one", owner: scopedOwner, teamID: "team-one", requestID: request)
        XCTAssertTrue(route.belongsTo(accountID: "synthetic", apiBaseURL: URL(string: "https://example.org")!, teamID: "team-one"))
        XCTAssertFalse(route.belongsTo(accountID: "other", apiBaseURL: URL(string: "https://example.org")!, teamID: "team-one"))
        XCTAssertFalse(route.belongsTo(accountID: "synthetic", apiBaseURL: URL(string: "https://other.example.org")!, teamID: "team-one"))
    }
    // contract-test: supporting surface=gui.apple assertions=apple-workflow-widget.run-current-scope
    func testUnissuedActionPerformsZeroRequests() async throws {
        let profile = ServerProfile.current()
        let scope = UUID()
        let team = APIRequestTeamContext(epoch: 1, teamID: nil)
        let environment = WorkflowAPISendEnvironment(currentAccountID: { "synthetic" }, currentProfile: { profile }, currentOfflineScope: { scope }, currentTeamContext: { team })
        var calls = 0
        let service = WorkflowWidgetRunService(environment: environment, issuedVersion: { _ in nil }, markDispatched: { _ in }, consume: { _ in }, detail: { _, _ in calls += 1; throw CancellationError() }, dispatch: { _, _, _, _ in calls += 1; throw CancellationError() })
        let route = WidgetWorkflowRunRoute(workflowID: "synthetic-workflow", owner: WidgetWorkflowsOwner.identity(accountID: "synthetic", apiBaseURL: profile.apiBaseURL, teamID: nil), teamID: nil, requestID: UUID())
        do { _ = try await service.run(route, accountID: "synthetic"); XCTFail("Unissued action must fail") } catch {}
        XCTAssertEqual(calls, 0)
    }
    // contract-test: supporting surface=gui.apple assertions=apple-workflow-widget.private-cache
    func testCiphertextRejectsDifferentOwnerAndKey() throws {
        let snapshot = WidgetWorkflowsSnapshot(owner: owner, teamID: nil, updatedAt: Date(), workflows: [])
        let key = SymmetricKey(size: .bits256)
        let data = try WidgetWorkflowsSnapshotCodec.seal(snapshot, key: key)
        XCTAssertThrowsError(try WidgetWorkflowsSnapshotCodec.open(data, owner: String(repeating: "b", count: 64), key: key))
        XCTAssertThrowsError(try WidgetWorkflowsSnapshotCodec.open(data, owner: owner, key: SymmetricKey(size: .bits256)))
    }
    // contract-test: supporting surface=gui.apple assertions=apple-workflow-widget.run-current-scope,apple-workflow-widget.selection
    func testDisabledScheduleManualRunRetriesWithSameKeyThenConsumes() async throws {
        let store = WorkflowStore()
        store.showFixture("runs")
        let existing = try XCTUnwrap(store.selectedWorkflow)
        var object = try XCTUnwrap(JSONSerialization.jsonObject(with: JSONEncoder().encode(existing)) as? [String: Any])
        object["enabled"] = false
        let workflow = try JSONDecoder().decode(WorkflowDetail.self, from: JSONSerialization.data(withJSONObject: object))
        XCTAssertNotNil(WidgetWorkflowsProjection.summary(workflow))
        let run = try XCTUnwrap(store.selectedRunDetail)
        let profile = ServerProfile.current(), scope = UUID()
        let team = APIRequestTeamContext(epoch: 1, teamID: nil)
        let environment = WorkflowAPISendEnvironment(currentAccountID: { "synthetic" }, currentProfile: { profile }, currentOfflineScope: { scope }, currentTeamContext: { team })
        var issued = true, consumed = 0
        var keys: [String] = []
        let service = WorkflowWidgetRunService(environment: environment,
            issuedVersion: { _ in issued ? workflow.currentVersionId : nil }, markDispatched: { _ in }, consume: { _ in issued = false; consumed += 1 },
            detail: { _, _ in workflow }, dispatch: { _, request, _, key in
                XCTAssertEqual(request.mode, "manual")
                XCTAssertTrue(request.input.isEmpty)
                keys.append(key)
                if keys.count == 1 { throw URLError(.networkConnectionLost) }
                return run
            })
        let route = WidgetWorkflowRunRoute(workflowID: workflow.id, owner: WidgetWorkflowsOwner.identity(accountID: "synthetic", apiBaseURL: profile.apiBaseURL, teamID: nil), teamID: nil, requestID: UUID())
        do { _ = try await service.run(route, accountID: "synthetic"); XCTFail("Synthetic transport must fail once") } catch {}
        _ = try await service.run(route, accountID: "synthetic")
        do { _ = try await service.run(route, accountID: "synthetic"); XCTFail("Accepted action must be consumed") } catch {}
        XCTAssertEqual(keys.count, 2)
        XCTAssertEqual(Set(keys).count, 1)
        XCTAssertEqual(consumed, 1)
    }
    // contract-test: supporting surface=gui.apple assertions=apple-workflow-widget.run-current-scope
    func testScopeChangeDuringDetailReadCancelsBeforeRun() async throws {
        let store = WorkflowStore(); store.showFixture("runs")
        let workflow = try XCTUnwrap(store.selectedWorkflow)
        let profile = ServerProfile.current()
        var scope = UUID(), runs = 0
        let team = APIRequestTeamContext(epoch: 1, teamID: nil)
        let environment = WorkflowAPISendEnvironment(currentAccountID: { "synthetic" }, currentProfile: { profile }, currentOfflineScope: { scope }, currentTeamContext: { team })
        let service = WorkflowWidgetRunService(environment: environment, issuedVersion: { _ in workflow.currentVersionId }, markDispatched: { _ in }, consume: { _ in },
            detail: { _, _ in scope = UUID(); return workflow }, dispatch: { _, _, _, _ in runs += 1; throw CancellationError() })
        let route = WidgetWorkflowRunRoute(workflowID: workflow.id, owner: WidgetWorkflowsOwner.identity(accountID: "synthetic", apiBaseURL: profile.apiBaseURL, teamID: nil), teamID: nil, requestID: UUID())
        do { _ = try await service.run(route, accountID: "synthetic"); XCTFail("Changed scope must fail") } catch {}
        XCTAssertEqual(runs, 0)
    }

    // contract-test: supporting surface=gui.apple assertions=apple-workflow-widget.run-current-scope,apple-workflow-widget.private-cache
    func testMultipleWidgetsPreserveUncertainActionBeyondInitialExpiry() throws {
        let (store, _) = storage(); store.activate(owner: owner)
        try store.save(.init(owner: owner, teamID: nil, updatedAt: Date(), workflows: [
            .init(id: "one", title: "One", versionID: "v1"), .init(id: "two", title: "Two", versionID: "v2")]))
        let now = Date(timeIntervalSince1970: 1000)
        let first = WidgetWorkflowRunRoute(workflowID: "one", owner: owner, teamID: nil, requestID: UUID())
        let issued = try store.authorize(first, now: now)
        try store.markDispatched(issued)
        let second = WidgetWorkflowRunRoute(workflowID: "two", owner: owner, teamID: nil, requestID: UUID())
        _ = try store.authorize(second, now: now)
        XCTAssertEqual(store.issuedVersion(first, now: now), "v1")
        XCTAssertEqual(store.issuedVersion(second, now: now), "v2")
        let later = now.addingTimeInterval(600)
        XCTAssertNil(store.issuedVersion(first, now: later))
        let freshTap = WidgetWorkflowRunRoute(workflowID: "one", owner: owner, teamID: nil, requestID: UUID())
        let retry = try store.authorize(freshTap, now: later)
        XCTAssertEqual(retry.requestID, first.requestID)
        XCTAssertEqual(store.issuedVersion(retry, now: later), "v1")
        store.consume(retry)
        XCTAssertNil(store.issuedVersion(retry, now: later))
        XCTAssertNotEqual(try store.authorize(freshTap, now: later).requestID, retry.requestID)
    }

    // contract-test: supporting surface=gui.apple assertions=apple-workflow-widget.run-current-scope
    func testChangedVersionRejectsBeforeDispatch() async throws {
        let store = WorkflowStore(); store.showFixture("runs")
        let workflow = try XCTUnwrap(store.selectedWorkflow)
        let profile = ServerProfile.current(), scope = UUID()
        let team = APIRequestTeamContext(epoch: 1, teamID: nil)
        let environment = WorkflowAPISendEnvironment(currentAccountID: { "synthetic" }, currentProfile: { profile }, currentOfflineScope: { scope }, currentTeamContext: { team })
        var runs = 0
        let service = WorkflowWidgetRunService(environment: environment, issuedVersion: { _ in "old-version" }, markDispatched: { _ in }, consume: { _ in },
            detail: { _, _ in workflow }, dispatch: { _, _, _, _ in runs += 1; throw CancellationError() })
        let route = WidgetWorkflowRunRoute(workflowID: workflow.id, owner: WidgetWorkflowsOwner.identity(accountID: "synthetic", apiBaseURL: profile.apiBaseURL, teamID: nil), teamID: nil, requestID: UUID())
        do { _ = try await service.run(route, accountID: "synthetic"); XCTFail("Changed version must fail") } catch {}
        XCTAssertEqual(runs, 0)
    }

    // contract-test: supporting surface=gui.apple assertions=apple-workflow-widget.run-current-scope,apple-workflow-widget.private-cache
    func testLiveGenerationAndTeamEpochInvalidateButColdRelaunchRetains() {
        let profile = ServerProfile.current(), generation = UUID()
        func publication(scope: UUID = generation, epoch: UInt64 = 7) -> WidgetWorkflowsPublicationScope {
            .init(WorkflowAPIOperationScope(accountID: "synthetic", profile: profile, offlineScope: scope,
                teamContext: APIRequestTeamContext(epoch: epoch, teamID: "synthetic-team")))
        }
        let current = publication()
        XCTAssertFalse(WidgetWorkflowsPublicationScope.mustInvalidate(previous: nil, next: current))
        XCTAssertFalse(WidgetWorkflowsPublicationScope.mustInvalidate(previous: current, next: current))
        XCTAssertTrue(WidgetWorkflowsPublicationScope.mustInvalidate(previous: current, next: publication(scope: UUID())))
        XCTAssertTrue(WidgetWorkflowsPublicationScope.mustInvalidate(previous: current, next: publication(epoch: 8)))
        XCTAssertTrue(WidgetWorkflowsPublicationScope.mustInvalidate(previous: current, next: nil))
    }
    // contract-test: supporting surface=gui.apple assertions=apple-workflow-widget.private-cache,apple-workflow-widget.run-current-scope
    func testLateAcceptanceCannotConsumeNewOwnersTicketWithSameNonce() throws {
        let (store, _) = storage()
        let now = Date(timeIntervalSince1970: 1000), nonce = UUID()
        store.activate(owner: owner)
        try store.save(.init(owner: owner, teamID: nil, updatedAt: now, workflows: [.init(id: "one", title: "One", versionID: "v1")]))
        let old = WidgetWorkflowRunRoute(workflowID: "one", owner: owner, teamID: nil, requestID: nonce)
        _ = try store.authorize(old, now: now)
        store.activate(owner: owner)
        XCTAssertEqual(store.issuedVersion(old, now: now), "v1", "Cold same-owner activation preserves a legitimate retry")
        let newOwner = String(repeating: "b", count: 64)
        store.activate(owner: newOwner)
        try store.save(.init(owner: newOwner, teamID: nil, updatedAt: now, workflows: [.init(id: "one", title: "New owner", versionID: "v2")]))
        let newer = WidgetWorkflowRunRoute(workflowID: "one", owner: newOwner, teamID: nil, requestID: nonce)
        _ = try store.authorize(newer, now: now)
        store.consume(old)
        XCTAssertEqual(store.issuedVersion(newer, now: now), "v2")
        store.clear()
        XCTAssertNil(store.issuedVersion(newer, now: now))
    }

    // contract-test: supporting surface=gui.apple assertions=apple-workflow-widget.run-current-scope
    func testDefiniteRejectionRetiresTicketAndCorrectedGraphUsesFreshAction() async throws {
        let fixture = WorkflowStore(); fixture.showFixture("runs")
        let original = try XCTUnwrap(fixture.selectedWorkflow)
        let run = try XCTUnwrap(fixture.selectedRunDetail)
        var object = try XCTUnwrap(JSONSerialization.jsonObject(with: JSONEncoder().encode(original)) as? [String: Any])
        object["current_version_id"] = "corrected-version"
        let corrected = try JSONDecoder().decode(WorkflowDetail.self, from: JSONSerialization.data(withJSONObject: object))
        let profile = ServerProfile.current(), scope = UUID()
        let team = APIRequestTeamContext(epoch: 1, teamID: nil)
        let scopedOwner = WidgetWorkflowsOwner.identity(accountID: "synthetic", apiBaseURL: profile.apiBaseURL, teamID: nil)
        let (storage, _) = storage(); storage.activate(owner: scopedOwner)
        try storage.save(.init(owner: scopedOwner, teamID: nil, updatedAt: Date(), workflows: [try XCTUnwrap(WidgetWorkflowsProjection.summary(original))]))
        let first = try storage.authorize(.init(workflowID: original.id, owner: scopedOwner, teamID: nil, requestID: UUID()))
        var current = original
        var keys: [String] = []
        let environment = WorkflowAPISendEnvironment(currentAccountID: { "synthetic" }, currentProfile: { profile }, currentOfflineScope: { scope }, currentTeamContext: { team })
        let service = WorkflowWidgetRunService(environment: environment,
            issuedVersion: { storage.issuedVersion($0) }, markDispatched: { try storage.markDispatched($0) }, consume: { storage.consume($0) },
            detail: { _, _ in current }, dispatch: { _, request, _, key in
                XCTAssertEqual(request.mode, "manual")
                keys.append(key)
                if current.currentVersionId == original.currentVersionId { throw APIError.httpError(status: 400, message: "MISSING_WORKFLOW_INPUT") }
                return run
            })
        do { _ = try await service.run(first, accountID: "synthetic"); XCTFail("Synthetic missing input must reject") } catch {}
        XCTAssertNil(storage.issuedVersion(first))
        current = corrected
        try storage.save(.init(owner: scopedOwner, teamID: nil, updatedAt: Date(), workflows: [try XCTUnwrap(WidgetWorkflowsProjection.summary(corrected))]))
        let next = try storage.authorize(.init(workflowID: corrected.id, owner: scopedOwner, teamID: nil, requestID: UUID()))
        XCTAssertNotEqual(first.requestID, next.requestID)
        _ = try await service.run(next, accountID: "synthetic")
        XCTAssertEqual(keys.count, 2)
        XCTAssertNotEqual(keys[0], keys[1])
        XCTAssertNil(storage.issuedVersion(next))
    }
    // contract-test: supporting surface=gui.apple assertions=apple-workflow-widget.run-current-scope
    func testOnlyPublishedPreAcceptanceErrorsRetireRetryIdentity() {
        XCTAssertTrue(WorkflowWidgetRunService.isDefiniteNonAcceptance(APIError.httpError(status: 400, message: "MISSING_WORKFLOW_INPUT")))
        XCTAssertFalse(WorkflowWidgetRunService.isDefiniteNonAcceptance(APIError.httpError(status: 409, message: "MISSING_WORKFLOW_INPUT")))
        XCTAssertFalse(WorkflowWidgetRunService.isDefiniteNonAcceptance(APIError.httpError(status: 500, message: "MISSING_WORKFLOW_INPUT")))
        XCTAssertFalse(WorkflowWidgetRunService.isDefiniteNonAcceptance(APIError.httpError(status: 400, message: "Unknown response")))
        XCTAssertFalse(WorkflowWidgetRunService.isDefiniteNonAcceptance(URLError(.networkConnectionLost)))
        XCTAssertFalse(WorkflowWidgetRunService.isDefiniteNonAcceptance(DecodingError.dataCorrupted(.init(codingPath: [], debugDescription: "Synthetic malformed response"))))
    }

    // contract-test: supporting surface=gui.apple assertions=apple-workflow-widget.run-current-scope,apple-workflow-widget.private-cache
    func testForegroundIntentHelperDeliversOneIssuedRouteAndRestoresWindow() throws {
        XCTAssertTrue(RunWidgetWorkflowIntent.openAppWhenRun)
        let (storage, _) = storage(); storage.activate(owner: owner)
        try storage.save(.init(owner: owner, teamID: nil, updatedAt: Date(), workflows: [.init(id: "one", title: "One", versionID: "v1")]))
        var delivered: [URL] = [], opened = 0
        try RunWidgetWorkflowIntent.deliver(identifier: owner + ":one", storage: storage,
            receive: { delivered.append($0) }, openMainWindow: { opened += 1 })
        XCTAssertEqual(delivered.count, 1)
        XCTAssertEqual(opened, 1)
        let route = try XCTUnwrap(WidgetWorkflowsLinks.route(delivered[0]))
        XCTAssertEqual(route.workflowID, "one")
        XCTAssertEqual(storage.issuedVersion(route), "v1")
        XCTAssertThrowsError(try RunWidgetWorkflowIntent.deliver(identifier: owner + ":missing", storage: storage,
            receive: { delivered.append($0) }, openMainWindow: { opened += 1 }))
        XCTAssertEqual(delivered.count, 1)
        XCTAssertEqual(opened, 1)
    }

}
