import CryptoKit
import XCTest
@testable import OpenMates

@MainActor
final class TeamWorkspaceContextTests: XCTestCase {
    // contract-test: supporting surface=gui.apple assertions=teams.lifecycle.encrypted-profiled
    func testTeamKeyWrapperAndMetadataUseSeparateKeys() async throws {
        let masterKey = SymmetricKey(size: .bits256)
        let teamKey = SymmetricKey(size: .bits256)
        let wrappedKey = try await CryptoManager.shared.wrapChatKey(teamKey, masterKey: masterKey)
        let unwrappedKey = try await CryptoManager.shared.unwrapChatKey(
            encryptedChatKeyBase64: wrappedKey, masterKey: masterKey)
        let metadata = try await CryptoManager.shared.encryptWithMasterKey(
            "Private team name", masterKey: teamKey)
        let plaintext = try await CryptoManager.shared.decryptContent(
            base64String: metadata, key: unwrappedKey)
        XCTAssertEqual(plaintext, "Private team name")
        do {
            _ = try await CryptoManager.shared.decryptContent(base64String: metadata, key: masterKey)
            XCTFail("Account master key must not open team metadata")
        } catch { }
    }

    // contract-test: supporting surface=gui.apple assertions=teams.membership.role-gated
    func testRoleAndStatusPolicyKeepsViewersReadOnlyAndSuspendedTeamsUnavailable() {
        let viewer = team("viewer", role: .viewer)
        XCTAssertTrue(viewer.canRead)
        XCTAssertFalse(viewer.canContribute)
        XCTAssertFalse(viewer.canManage)
        XCTAssertFalse(viewer.canViewBilling)

        let member = team("member", role: .member)
        XCTAssertTrue(member.canContribute)
        XCTAssertFalse(member.canManage)
        XCTAssertFalse(member.canViewBilling)

        let admin = team("admin", role: .admin)
        XCTAssertTrue(admin.canManage)
        XCTAssertTrue(admin.canViewBilling)
        XCTAssertTrue(team("owner", role: .owner).canManage)

        let suspended = team("suspended", role: .owner, status: "suspended")
        XCTAssertFalse(suspended.canRead)
        XCTAssertFalse(suspended.canContribute)
        XCTAssertFalse(suspended.canManage)
    }

    // contract-test: supporting surface=gui.apple assertions=teams.context.full-switch-local
    func testResetDuringSuspendedListCannotPublishPreviousAccountOrKey() async {
        let state = ScopeState()
        let service = MockTeamService()
        service.suspendList = true
        let (store, defaults, suite) = makeStore(state: state, service: service)
        defer { defaults.removePersistentDomain(forName: suite) }

        let oldLoad = Task { await store.load(accountID: "account-a") }
        for _ in 0..<100 where service.listContinuation == nil { await Task.yield() }
        XCTAssertNotNil(service.listContinuation)
        state.accountID = "account-b"
        state.scope = UUID()
        store.reset(accountID: "account-b")
        service.finishList([team("private-a", role: .owner)])
        await oldLoad.value

        XCTAssertTrue(store.teams.isEmpty)
        XCTAssertNil(store.teamID)
        XCTAssertNil(store.selectedTeam)
        XCTAssertFalse(store.isLoading)
    }

    // contract-test: supporting surface=gui.apple assertions=teams.context.full-switch-local
    func testServerSwitchDuringSuspendedListCannotPublishOldServerTeam() async {
        let state = ScopeState()
        let service = MockTeamService()
        service.suspendList = true
        let (store, defaults, suite) = makeStore(state: state, service: service)
        defer { defaults.removePersistentDomain(forName: suite) }

        let oldLoad = Task { await store.load(accountID: state.accountID) }
        for _ in 0..<100 where service.listContinuation == nil { await Task.yield() }
        XCTAssertNotNil(service.listContinuation)
        state.server = .production
        store.reset(accountID: state.accountID)
        service.finishList([team("dev-only", role: .owner)])
        await oldLoad.value

        XCTAssertTrue(store.teams.isEmpty)
        XCTAssertNil(store.teamID)
        XCTAssertNil(store.selectedTeam)
    }

    // contract-test: supporting surface=gui.apple assertions=teams.context.full-switch-local
    func testSelectionDetailFromPreviousTeamCannotReplaceNewContext() async {
        let state = ScopeState()
        let service = MockTeamService()
        service.listResult = [team("first", role: .member), team("second", role: .admin)]
        let (store, defaults, suite) = makeStore(state: state, service: service)
        defer { defaults.removePersistentDomain(forName: suite) }
        await store.load(accountID: state.accountID)
        service.suspendDetail = true

        let oldSelection = Task { await store.selectTeam("first") }
        for _ in 0..<100 where service.detailContinuation == nil { await Task.yield() }
        XCTAssertNotNil(service.detailContinuation)
        await store.selectTeam(nil)
        let epoch = store.contextEpoch
        service.finishDetail(team("first", role: .member))
        await oldSelection.value

        XCTAssertNil(store.teamID)
        XCTAssertNil(store.selectedTeam)
        XCTAssertEqual(store.contextEpoch, epoch)
        XCTAssertFalse(store.isLoading, "Personal selection must cancel the old detail loading state")
    }

    // contract-test: supporting surface=gui.apple assertions=teams.context.full-switch-local
    func testRetainedSelectionIsAccountAndServerScopedAndEpochChangesOnlyForContext() async {
        let state = ScopeState()
        let service = MockTeamService()
        service.listResult = [team("team-a", role: .admin)]
        let (store, defaults, suite) = makeStore(state: state, service: service)
        defer { defaults.removePersistentDomain(forName: suite) }

        await store.load(accountID: state.accountID)
        await store.selectTeam("team-a")
        let selectedEpoch = store.contextEpoch
        let selectedSnapshot = store.snapshot
        XCTAssertEqual(store.teamID, "team-a")
        XCTAssertTrue(store.isCurrent(selectedSnapshot))
        await store.load(accountID: state.accountID)
        XCTAssertEqual(store.contextEpoch, selectedEpoch)

        store.reset(accountID: state.accountID)
        await store.load(accountID: state.accountID)
        XCTAssertEqual(store.teamID, "team-a")

        state.server = .production
        XCTAssertFalse(store.isCurrent(selectedSnapshot))
        await store.load(accountID: state.accountID)
        XCTAssertNil(store.teamID)
        state.server = .development
        state.accountID = "account-b"
        state.scope = UUID()
        await store.load(accountID: state.accountID)
        XCTAssertNil(store.teamID)

        let accountBSnapshot = store.snapshot
        state.scope = UUID()
        XCTAssertFalse(store.isCurrent(accountBSnapshot))
        await store.load(accountID: state.accountID)
        XCTAssertNil(store.teamID)
    }

    private func team(_ id: String, role: TeamWorkspaceRole, status: String = "active") -> TeamWorkspaceTeam {
        TeamWorkspaceTeam(id: id, name: id, description: "", role: role, status: status,
                          profileImageMetadata: .generated, zeroBalance: 0,
                          createdAt: 0, updatedAt: 0,
                          key: SymmetricKey(data: Data(repeating: 7, count: 32)))
    }

    private func makeStore(state: ScopeState, service: MockTeamService) -> (TeamWorkspaceContext, UserDefaults, String) {
        let suite = "TeamWorkspaceContextTests.\(UUID().uuidString)"
        let defaults = UserDefaults(suiteName: suite)!
        let environment = TeamWorkspaceEnvironment(
            currentAccountID: { state.accountID },
            scopeGeneration: { state.scope },
            serverProfile: { state.server }
        )
        return (TeamWorkspaceContext(service: service, environment: environment, defaults: defaults), defaults, suite)
    }
}

@MainActor
private final class ScopeState {
    var accountID = "account-a"
    var scope = UUID()
    var server = ServerProfile.development
}

@MainActor
private final class MockTeamService: TeamWorkspaceServing {
    var listResult: [TeamWorkspaceTeam] = []
    var suspendList = false
    var suspendDetail = false
    var listContinuation: CheckedContinuation<[TeamWorkspaceTeam], Never>?
    var detailContinuation: CheckedContinuation<TeamWorkspaceTeam, Never>?

    func listTeams(fence: TeamWorkspaceFence) async throws -> [TeamWorkspaceTeam] {
        if suspendList {
            return await withCheckedContinuation { listContinuation = $0 }
        }
        return listResult
    }

    func getTeam(_ id: String, fence: TeamWorkspaceFence) async throws -> TeamWorkspaceTeam {
        if suspendDetail {
            return await withCheckedContinuation { detailContinuation = $0 }
        }
        return listResult.first { $0.id == id }!
    }

    func finishList(_ value: [TeamWorkspaceTeam]) {
        listContinuation?.resume(returning: value)
        listContinuation = nil
    }

    func finishDetail(_ value: TeamWorkspaceTeam) {
        detailContinuation?.resume(returning: value)
        detailContinuation = nil
    }
}
