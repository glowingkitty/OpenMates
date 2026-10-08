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

    // contract-test: supporting surface=gui.apple assertions=apple-workspaces.isolation,teams.context.full-switch-local
    func testRosterCiphertextIsAccountServerBoundAndContainsNoReadableMetadata() throws {
        let state = ScopeState(); let environment = TeamWorkspaceEnvironment(currentAccountID: { state.accountID }, scopeGeneration: { state.scope }, serverProfile: { state.server })
        let suite = "EncryptedTeams.\(UUID().uuidString)"; let defaults = UserDefaults(suiteName: suite)!
        defer { defaults.removePersistentDomain(forName: suite) }
        let cache = TeamWorkspaceRosterCache(defaults: defaults); let key = SymmetricKey(size: .bits256)
        let fence = TeamWorkspaceFence(accountID: state.accountID, environment: environment)
        let data = Data(#"{"teams":[{"name":"Private roster name","role":"owner"}]}"#.utf8)
        try cache.write(data, fence: fence, masterKey: key)
        XCTAssertEqual(try cache.read(fence: fence, masterKey: key), data)
        let stored = try XCTUnwrap(defaults.dictionaryRepresentation().values.compactMap { $0 as? Data }.first)
        XCTAssertNil(stored.range(of: Data("Private roster name".utf8)))
        XCTAssertThrowsError(try cache.read(fence: fence, masterKey: SymmetricKey(size: .bits256)))
        state.server = .production
        XCTAssertNil(try cache.read(fence: TeamWorkspaceFence(accountID: state.accountID, environment: environment), masterKey: key))
        XCTAssertNil(try cache.read(fence: TeamWorkspaceFence(accountID: "another-account", environment: environment), masterKey: key))
        cache.remove(fence: fence)
        XCTAssertNil(try cache.read(fence: fence, masterKey: key))
    }

    // contract-test: supporting surface=gui.apple assertions=teams.context.full-switch-local,apple-workspaces.local-first
    func testCachedRosterAllowsColdOfflineSwitchWithoutDetailRequests() async {
        let state = ScopeState(); let service = MockTeamService()
        service.cachedResult = [team("first", role: .member), team("second", role: .viewer)]
        service.listError = URLError(.notConnectedToInternet)
        let (context, defaults, suite) = makeStore(state: state, service: service)
        defer { defaults.removePersistentDomain(forName: suite) }
        await context.load(accountID: state.accountID)
        XCTAssertTrue(context.usingCachedRoster)
        XCTAssertEqual(context.teams.count, 2)
        await context.selectTeam("first")
        XCTAssertEqual(context.teamID, "first")
        await context.selectTeam("second")
        XCTAssertEqual(context.teamID, "second")
        XCTAssertFalse(context.selectedTeam!.canContribute)
        await context.selectTeam(nil)
        XCTAssertNil(context.teamID)
        XCTAssertEqual(service.detailRequestCount, 0)
    }

    // contract-test: supporting surface=gui.apple assertions=teams.membership.role-gated,teams.context.full-switch-local
    func testCachedSelectionCannotCancelSuspendedAuthoritativeRosterRevocation() async throws {
        let state = ScopeState(); let service = MockTeamService()
        service.cachedResult = [team("revoked", role: .owner), team("retained", role: .member)]
        service.suspendList = true
        let started = expectation(description: "authoritative roster suspended"); service.listDidSuspend = started
        let (context, defaults, suite) = makeStore(state: state, service: service, revocationCleanup: { _, _, _ in })
        defer { defaults.removePersistentDomain(forName: suite) }
        let pending = Task { await context.load(accountID: state.accountID) }
        await fulfillment(of: [started], timeout: 3)
        XCTAssertNotNil(service.listContinuation)
        await context.selectTeam("revoked")
        XCTAssertEqual(context.teamID, "revoked"); XCTAssertEqual(service.detailRequestCount, 0)
        XCTAssertTrue(context.isLoading, "Cached selection must preserve roster loading")
        service.finishList([team("retained", role: .viewer)])
        await pending.value
        XCTAssertEqual(context.teams.map(\.id), ["retained"])
        XCTAssertNil(context.selectedTeam); XCTAssertNil(context.teamID)
        XCTAssertFalse(context.usingCachedRoster); XCTAssertFalse(context.isLoading)
    }

    // contract-test: supporting surface=gui.apple assertions=teams.membership.role-gated,teams.context.full-switch-local
    func testCachedSelectionCannotDiscardSuspendedRosterAuthorizationFailure() async {
        for status in [401, 403] {
            let state = ScopeState(); let service = MockTeamService()
            service.cachedResult = [team("revoked", role: .owner)]; service.suspendList = true
            let started = expectation(description: "denied roster suspended"); service.listDidSuspend = started
            let (context, defaults, suite) = makeStore(state: state, service: service, revocationCleanup: { _, _, _ in })
            defer { defaults.removePersistentDomain(forName: suite) }
            let pending = Task { await context.load(accountID: state.accountID) }
            await fulfillment(of: [started], timeout: 3)
            XCTAssertNotNil(service.listContinuation)
            await context.selectTeam("revoked")
            service.failList(APIError.httpError(status: status, message: "Scoped test denial"))
            await pending.value
            XCTAssertTrue(context.teams.isEmpty); XCTAssertNil(context.selectedTeam)
            XCTAssertFalse(context.usingCachedRoster); XCTAssertFalse(context.isLoading)
        }
    }

    // contract-test: supporting surface=gui.apple assertions=teams.context.full-switch-local,apple-workspaces.isolation
    func testAccountOrServerResetWhileRosterPurgeIsSuspendedCannotPublishOldRosterOrError() async {
        for resetServer in [false, true] {
            let state = ScopeState(); let service = MockTeamService()
            service.cachedResult = [team("revoked", role: .owner)]; service.listError = URLError(.notConnectedToInternet)
            var cleanup: CheckedContinuation<Void, Never>?
            let started = expectation(description: "old identity cleanup suspended")
            let (context, defaults, suite) = makeStore(state: state, service: service, revocationCleanup: { _, fence, _ in
                XCTAssertEqual(fence.accountID, "account-a"); XCTAssertEqual(fence.server, .development)
                await withCheckedContinuation { cleanup = $0; started.fulfill() }
            })
            defer { defaults.removePersistentDomain(forName: suite) }
            await context.load(accountID: state.accountID); await context.selectTeam("revoked")
            service.listError = nil; service.listResult = [team("obsolete-roster", role: .member)]
            let old = Task { await context.load(accountID: state.accountID) }
            await fulfillment(of: [started], timeout: 3)
            XCTAssertNotNil(cleanup); XCTAssertNil(context.teamID, "Selection is revoked before disk cleanup")
            if resetServer { state.server = .production } else { state.accountID = "account-b"; state.scope = UUID() }
            context.reset(accountID: state.accountID)
            cleanup?.resume(); await old.value
            XCTAssertEqual(context.loadedAccountID, state.accountID)
            XCTAssertTrue(context.teams.isEmpty); XCTAssertNil(context.selectedTeam); XCTAssertNil(context.error)
            XCTAssertFalse(context.isLoading)
        }
    }

    // contract-test: supporting surface=gui.apple assertions=teams.context.full-switch-local,apple-workspaces.isolation
    func testAuthorizationCatchCannotPublishAfterAccountResetDuringPurge() async {
        let state = ScopeState(); let service = MockTeamService()
        service.cachedResult = [team("revoked", role: .owner)]; service.listError = URLError(.notConnectedToInternet)
        var cleanup: CheckedContinuation<Void, Never>?
        let started = expectation(description: "revocation cleanup suspended")
        let (context, defaults, suite) = makeStore(state: state, service: service, revocationCleanup: { _, _, _ in await withCheckedContinuation { cleanup = $0; started.fulfill() } })
        defer { defaults.removePersistentDomain(forName: suite) }
        await context.load(accountID: state.accountID); await context.selectTeam("revoked")
        service.listError = TeamWorkspaceError.unavailableTeam
        let old = Task { await context.load(accountID: state.accountID) }
        await fulfillment(of: [started], timeout: 3)
        XCTAssertNotNil(cleanup)
        state.accountID = "account-b"; state.scope = UUID(); context.reset(accountID: state.accountID)
        cleanup?.resume(); await old.value
        XCTAssertTrue(context.teams.isEmpty); XCTAssertNil(context.error); XCTAssertFalse(context.isLoading)
    }

    // contract-test: supporting surface=gui.apple assertions=teams.context.full-switch-local,apple-workspaces.isolation
    func testRevocationPurgeCompletionCannotReplaceNewerSelectionOrRosterLoad() async {
        let state = ScopeState(); let service = MockTeamService()
        service.cachedResult = [team("revoked", role: .owner), team("retained", role: .member)]
        service.listError = URLError(.notConnectedToInternet)
        var cleanup: CheckedContinuation<Void, Never>?
        var cleanups = 0
        let started = expectation(description: "first revocation cleanup suspended")
        let (context, defaults, suite) = makeStore(state: state, service: service, revocationCleanup: { _, _, _ in
            cleanups += 1
            if cleanups == 1 { await withCheckedContinuation { cleanup = $0; started.fulfill() } }
        })
        defer { defaults.removePersistentDomain(forName: suite) }
        await context.load(accountID: state.accountID); await context.selectTeam("revoked")
        let fence = TeamWorkspaceFence(accountID: state.accountID, environment: .init(currentAccountID: { state.accountID }, scopeGeneration: { state.scope }, serverProfile: { state.server }))
        let revoked = Task { await context.revokeCachedTeam("revoked", fence: fence) }
        await fulfillment(of: [started], timeout: 3)
        XCTAssertNotNil(cleanup)
        await context.selectTeam("retained")
        XCTAssertEqual(context.teamID, "retained")
        service.listError = nil; service.listResult = [team("retained", role: .viewer)]
        await context.load(accountID: state.accountID)
        cleanup?.resume(); await revoked.value
        XCTAssertEqual(context.teams.map(\.id), ["retained"])
        XCTAssertEqual(context.teamID, "retained"); XCTAssertEqual(context.selectedTeam?.role, .viewer)
        XCTAssertFalse(context.isLoading)
    }

    // contract-test: supporting surface=gui.apple assertions=teams.context.full-switch-local,apple-workspaces.isolation
    func testOlderRosterPurgeCompletionCannotOverwriteNewerRosterLoad() async {
        let state = ScopeState(); let service = MockTeamService()
        service.cachedResult = [team("revoked", role: .owner)]; service.listError = URLError(.notConnectedToInternet)
        var cleanup: CheckedContinuation<Void, Never>?
        let started = expectation(description: "revocation cleanup suspended")
        let (context, defaults, suite) = makeStore(state: state, service: service, revocationCleanup: { _, _, _ in await withCheckedContinuation { cleanup = $0; started.fulfill() } })
        defer { defaults.removePersistentDomain(forName: suite) }
        await context.load(accountID: state.accountID)
        service.listError = nil; service.listResult = [team("obsolete", role: .member)]
        let old = Task { await context.load(accountID: state.accountID) }
        await fulfillment(of: [started], timeout: 3)
        XCTAssertNotNil(cleanup)
        service.cachedResult = []; service.listResult = [team("fresh", role: .viewer)]
        await context.load(accountID: state.accountID)
        cleanup?.resume(); await old.value
        XCTAssertEqual(context.teams.map(\.id), ["fresh"])
        XCTAssertNil(context.error); XCTAssertFalse(context.isLoading)
    }

    private func team(_ id: String, role: TeamWorkspaceRole, status: String = "active") -> TeamWorkspaceTeam {
        TeamWorkspaceTeam(id: id, name: id, description: "", role: role, status: status,
                          profileImageMetadata: .generated, zeroBalance: 0,
                          createdAt: 0, updatedAt: 0,
                          key: SymmetricKey(data: Data(repeating: 7, count: 32)))
    }

    private func makeStore(state: ScopeState, service: MockTeamService,
                           revocationCleanup: TeamWorkspaceContext.RevocationCleanup? = nil) -> (TeamWorkspaceContext, UserDefaults, String) {
        let suite = "TeamWorkspaceContextTests.\(UUID().uuidString)"
        let defaults = UserDefaults(suiteName: suite)!
        let environment = TeamWorkspaceEnvironment(
            currentAccountID: { state.accountID },
            scopeGeneration: { state.scope },
            serverProfile: { state.server }
        )
        return (TeamWorkspaceContext(service: service, environment: environment, defaults: defaults, revocationCleanup: revocationCleanup), defaults, suite)
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
    var cachedResult: [TeamWorkspaceTeam] = []
    var listError: Error?
    var detailRequestCount = 0
    var suspendList = false
    var listDidSuspend: XCTestExpectation?
    var suspendDetail = false
    var listContinuation: CheckedContinuation<[TeamWorkspaceTeam], Error>?
    var detailContinuation: CheckedContinuation<TeamWorkspaceTeam, Never>?

    func cachedTeams(fence: TeamWorkspaceFence) async throws -> [TeamWorkspaceTeam] { cachedResult }
    func listTeams(fence: TeamWorkspaceFence) async throws -> [TeamWorkspaceTeam] {
        if let listError { throw listError }
        if suspendList {
            return try await withCheckedThrowingContinuation { listContinuation = $0; listDidSuspend?.fulfill() }
        }
        return listResult
    }

    func getTeam(_ id: String, fence: TeamWorkspaceFence) async throws -> TeamWorkspaceTeam {
        detailRequestCount += 1
        if suspendDetail {
            return await withCheckedContinuation { detailContinuation = $0 }
        }
        return listResult.first { $0.id == id }!
    }

    func finishList(_ value: [TeamWorkspaceTeam]) {
        listContinuation?.resume(returning: value)
        listContinuation = nil
    }

    func failList(_ error: Error) {
        listContinuation?.resume(throwing: error); listContinuation = nil
    }

    func finishDetail(_ value: TeamWorkspaceTeam) {
        detailContinuation?.resume(returning: value)
        detailContinuation = nil
    }
}

// Specification: specifications/features/apple-offline-workspaces/specification.yml
// Assertions: apple-workspaces.offline-complete, apple-workspaces.isolation, apple-workspaces.maintenance
@MainActor
final class TeamWorkspaceOfflineRetentionTests: XCTestCase {
    // contract-test: supporting surface=gui.apple assertions=apple-workspaces.isolation,teams.context.full-switch-local
    func testBoundedTeamMetadataUsesScopedCurrentWrapperAndRejectsCrossTeamRows() throws {
        let id = "synthetic-team-chat"
        let teamID = "team-a"
        let teamHash = SHA256.hash(data: Data(teamID.utf8)).map { String(format: "%02x", $0) }.joined()
        let chatHash = ChatKeyWrapperRecord.hashedChatId(for: id)
        let data = try JSONSerialization.data(withJSONObject: ["chats": [["id": id, "created_at": "2026-10-07T12:00:00Z",
            "title": "plaintext must not persist", "encrypted_title": "ciphertext-title",
            "chat_key_wrappers": [
                ["hashed_chat_id": chatHash, "hashed_team_id": teamHash, "key_type": "team", "team_key_epoch": 1, "wrapper_version": 1, "encrypted_chat_key": "old-wrapper"],
                ["hashed_chat_id": chatHash, "hashed_team_id": teamHash, "key_type": "team", "team_key_epoch": 2, "wrapper_version": 1, "encrypted_chat_key": "current-wrapper"],
                ["hashed_chat_id": chatHash, "hashed_team_id": "foreign", "key_type": "team", "team_key_epoch": 99, "encrypted_chat_key": "foreign-wrapper"]
            ]]]])
        let rows = try TeamWorkspaceOfflineRetention.decodeChatMetadata(data, teamID: teamID)
        XCTAssertEqual(rows.count, 1); XCTAssertEqual(rows[0].teamId, teamID)
        XCTAssertEqual(rows[0].encryptedChatKey, "current-wrapper")
        XCTAssertEqual(rows[0].encryptedTitle, "ciphertext-title"); XCTAssertNil(rows[0].title)
        XCTAssertThrowsError(try TeamWorkspaceOfflineRetention.decodeChatMetadata(Data(#"{"chats":[{"id":"foreign","team_id":"team-b"}]}"#.utf8), teamID: teamID))
        XCTAssertThrowsError(try TeamWorkspaceOfflineRetention.decodeChatMetadata(JSONSerialization.data(withJSONObject: ["chats": (0..<101).map { ["id": "chat-\($0)"] }]), teamID: teamID))
    }

    // contract-test: supporting surface=gui.apple assertions=apple-workspaces.isolation,teams.membership.role-gated
    func testRemovingOneRosterMembershipPreservesOtherEncryptedContexts() throws {
        let fixture = RetentionFixture(); defer { fixture.clean() }
        let suite = "teams-roster-removal-" + UUID().uuidString
        let defaults = UserDefaults(suiteName: suite)!
        defer { defaults.removePersistentDomain(forName: suite) }
        let roster = TeamWorkspaceRosterCache(defaults: defaults)
        try roster.write(Data(#"{"teams":[{"team_id":"team-a","encrypted_name":"first"},{"team_id":"team-b","encrypted_name":"second"}]}"#.utf8), fence: fixture.fence, masterKey: fixture.key)
        try roster.removeTeam("team-a", fence: fixture.fence, masterKey: fixture.key)
        let raw = try XCTUnwrap(JSONSerialization.jsonObject(with: XCTUnwrap(roster.read(fence: fixture.fence, masterKey: fixture.key))) as? [String: Any])
        XCTAssertEqual((raw["teams"] as? [[String: Any]])?.compactMap { $0["team_id"] as? String }, ["team-b"])
    }

    // contract-test: supporting surface=gui.apple assertions=apple-offline.recent-cohort,apple-workspaces.isolation
    func testPersonalRecentMaintenanceCannotBeStarvedByNewTeamMetadataOrPruneTeamContent() {
        let personal = (0..<20).map { id in Chat(id: "personal-\(id)", title: nil, lastMessageAt: nil, createdAt: "2026-10-01T12:00:00Z",
            updatedAt: nil, isArchived: false, isPinned: false, appId: "ai", encryptedTitle: nil, encryptedChatKey: nil) }
        let teamRows = (0..<30).map { id in Chat(id: "team-\(id)", title: nil, lastMessageAt: nil, createdAt: "2026-10-07T12:00:00Z",
            updatedAt: nil, isArchived: false, isPinned: false, appId: "ai", encryptedTitle: nil, encryptedChatKey: nil, teamId: "team-a") }
        XCTAssertEqual(Set(OfflineRecentChatPolicy.cohort(from: personal + teamRows).map(\.id)), Set(personal.map(\.id)))
        XCTAssertEqual(OfflineRecentChatPolicy.cohort(from: personal + teamRows, teamID: "team-a").count, 20)
    }

    // contract-test: supporting surface=gui.apple assertions=apple-workspaces.offline-complete,apple-workspaces.isolation
    func testReaderRetainsPersonalAndTwoTeamsIncludingCompleteFinalPageWithoutChangingForegroundCache() async throws {
        let fixture = RetentionFixture(); defer { fixture.clean() }
        let foreground = NativeWorkspaceOfflineCache(directory: fixture.directory.appendingPathComponent("foreground"))
        let personal = fixture.scope(nil)
        await foreground.configure(scope: personal, masterKey: fixture.key)
        try await foreground.retain(namespace: "sentinel", path: "foreground", data: Data("foreground stays active".utf8), scope: personal)
        var paths: [String] = []
        try await fixture.retain { path, _ in paths.append(path); return try fixture.response(path) }
        for id in [String?.none, "team-a", "team-b"] {
            let scope = fixture.scope(id); await fixture.cache.configure(scope: scope, masterKey: fixture.key)
            let data = try await fixture.cache.read(namespace: "user-tasks", path: UserTasksPaths.scoped("/v1/user-tasks", teamID: id), scope: scope)
            let raw = try XCTUnwrap(JSONSerialization.jsonObject(with: XCTUnwrap(data)) as? [String: Any])
            XCTAssertEqual((raw["tasks"] as? [[String: Any]])?.compactMap { $0["task_id"] as? String }, ["task-a", "task-b"])
            let complete = try await fixture.cache.hasCompleteSnapshot(namespace: "user-tasks", scope: scope)
            XCTAssertTrue(complete)
            if let id {
                let members = try await fixture.cache.read(namespace: "team-management", path: SettingsTeamsService.path(id, suffix: "members"), scope: scope)
                XCTAssertNotNil(members)
                let memories = try await fixture.cache.read(namespace: "team-summary", path: SettingsTeamsService.path(id, suffix: "memories"), scope: scope)
                XCTAssertNotNil(memories)
                XCTAssertFalse(paths.contains { $0 == SettingsTeamsService.path(id, suffix: "billing") }, "Member role must not attempt admin-only wallet reads")
                XCTAssertFalse(paths.contains { $0 == SettingsTeamsService.path(id, suffix: "invites") }, "Member role must not attempt admin-only invite reads")
            }
            XCTAssertTrue(paths.contains { $0.contains("cursor=task-a") && (id == nil ? !$0.contains("team_id") : $0.contains("team_id=" + id!)) })
        }
        let retainedForeground = try await foreground.read(namespace: "sentinel", path: "foreground", scope: personal)
        XCTAssertEqual(retainedForeground, Data("foreground stays active".utf8))
        for url in FileManager.default.enumerator(at: fixture.directory, includingPropertiesForKeys: nil)!.compactMap({ $0 as? URL }).filter({ $0.pathExtension == "aesgcm" }) {
            XCTAssertNil(try Data(contentsOf: url).range(of: Data("task-a".utf8)))
        }
    }

    // contract-test: supporting surface=gui.apple assertions=apple-workspaces.offline-complete,apple-workspaces.maintenance
    func testPartialNamespaceKeepsPreviousCompleteSnapshotAndContinuesOtherNamespaces() async throws {
        let fixture = RetentionFixture(); defer { fixture.clean() }
        let scope = fixture.scope(nil); await fixture.cache.configure(scope: scope, masterKey: fixture.key)
        let revision = try await fixture.cache.beginRefresh(namespace: "user-tasks", scope: scope)
        let previous = Data(#"{"tasks":[{"task_id":"old-encrypted-row"}]}"#.utf8)
        try await fixture.cache.commit(namespace: "user-tasks", responses: ["/v1/user-tasks": previous], scope: scope, revision: revision)
        try await fixture.retain(teams: []) { path, _ in
            if path.contains("cursor=task-a") { throw URLError(.networkConnectionLost) }
            return try fixture.response(path)
        }
        let rows = try await fixture.cache.read(namespace: "user-tasks", path: "/v1/user-tasks", scope: scope)
        XCTAssertEqual(rows, previous)
        let complete = try await fixture.cache.hasCompleteSnapshot(namespace: "user-tasks", scope: scope)
        let projectsComplete = try await fixture.cache.hasCompleteSnapshot(namespace: "projects", scope: scope)
        XCTAssertTrue(complete); XCTAssertTrue(projectsComplete)
    }

    // contract-test: supporting surface=gui.apple assertions=apple-workspaces.isolation,teams.membership.role-gated
    func testObservedRevocationPurgesRecoverableTeamSnapshotAndPreservesPendingCiphertext() async throws {
        let fixture = RetentionFixture(); defer { fixture.clean() }
        let revokedScope = fixture.scope("team-a"); await fixture.cache.configure(scope: revokedScope, masterKey: fixture.key)
        try await fixture.cache.retain(namespace: "projects", path: "old", data: Data("server ciphertext snapshot".utf8), scope: revokedScope)
        try FileManager.default.createDirectory(at: fixture.directory, withIntermediateDirectories: true)
        let journal = fixture.directory.appendingPathComponent("pending-ciphertext-journal")
        try Data([42, 99]).write(to: journal)
        var revoked: [String] = []
        try await TeamWorkspaceOfflineRetention.retain(fence: fixture.fence, teams: fixture.teams, removedIDs: [], masterKey: fixture.key,
            cache: fixture.cache, transport: { path, _ in try fixture.response(path) }, membership: { id, _ in
                if id == "team-a" { throw TeamWorkspaceError.unavailableTeam }; return fixture.team(id)
            }, revoke: { id, _ in revoked.append(id) })
        XCTAssertEqual(revoked, ["team-a"])
        XCTAssertFalse(FileManager.default.fileExists(atPath: fixture.directory.appendingPathComponent(revokedScope.directoryID).path))
        XCTAssertEqual(try Data(contentsOf: journal), Data([42, 99]))
    }

    // contract-test: supporting surface=gui.apple assertions=apple-workspaces.isolation
    func testAccountChangeDuringRequestRejectsOldCompletionBeforeCommit() async throws {
        let fixture = RetentionFixture(); defer { fixture.clean() }
        do {
            try await fixture.retain(teams: []) { path, _ in
                fixture.state.accountID = "another-account"; fixture.state.scope = UUID()
                return try fixture.response(path)
            }
            XCTFail("Changed account must fence the reader")
        } catch TeamWorkspaceError.staleContext { }
        XCTAssertFalse(FileManager.default.fileExists(atPath: fixture.directory.appendingPathComponent(fixture.initialScope.directoryID).path))
    }

    // contract-test: supporting surface=gui.apple assertions=apple-workspaces.maintenance,apple-workspaces.isolation
    func testBackgroundReadCoalescesWithForegroundGETFlight() async throws {
        let fixture = RetentionFixture(); defer { fixture.clean() }
        let captured = fixture.scope(nil)
        let path = "/v1/workflows"
        let identity = captured.directoryID + captured.accountGeneration.uuidString + String(captured.teamEpoch) + path
        let gate = RetentionRequestGate()
        let foreground = Task { try await NativeWorkspaceRequestFlights.shared.perform(identity: identity) {
            try await gate.suspend()
        } }
        for _ in 0..<100 where gate.continuation == nil { await Task.yield() }
        let coalescedBefore = await NativeWorkspaceRequestFlights.shared.coalescedRequestCount
        let background = Task { try await fixture.retain(teams: []) { route, _ in
            if route == path { gate.requests += 1 }
            return try fixture.response(route)
        } }
        for _ in 0..<1000 {
            if await NativeWorkspaceRequestFlights.shared.coalescedRequestCount > coalescedBefore { break }
            await Task.yield()
        }
        let coalescedAfter = await NativeWorkspaceRequestFlights.shared.coalescedRequestCount
        XCTAssertGreaterThan(coalescedAfter, coalescedBefore)
        XCTAssertEqual(gate.requests, 1)
        try XCTUnwrap(gate.continuation).resume(returning: fixture.response(path))
        _ = try await foreground.value; try await background.value
        XCTAssertEqual(gate.requests, 1)
    }
}

@MainActor private final class RetentionRequestGate {
    var requests = 0
    var continuation: CheckedContinuation<Data, Error>?

    func suspend() async throws -> Data {
        requests += 1
        return try await withCheckedThrowingContinuation { continuation = $0 }
    }
}

@MainActor private final class RetentionFixture {
    let state = ScopeState()
    let key = SymmetricKey(size: .bits256)
    let directory = FileManager.default.temporaryDirectory.appendingPathComponent("teams-retention-" + UUID().uuidString)
    lazy var cache = NativeWorkspaceOfflineCache(directory: directory)
    lazy var initialScope = scope(nil)
    var fence: TeamWorkspaceFence { .init(accountID: state.accountID, environment: .init(currentAccountID: { self.state.accountID }, scopeGeneration: { self.state.scope }, serverProfile: { self.state.server })) }
    var teams: [TeamWorkspaceTeam] { [team("team-a"), team("team-b")] }
    func team(_ id: String) -> TeamWorkspaceTeam {
        .init(id: id, name: "Synthetic", description: "", role: .member, status: "active", profileImageMetadata: .generated,
            zeroBalance: 0, createdAt: 1, updatedAt: 1, key: key)
    }
    func scope(_ teamID: String?) -> NativeWorkspaceOfflineScope {
        .init(accountID: state.accountID, server: state.server.apiBaseURL.absoluteString, teamID: teamID,
            accountGeneration: state.scope, teamEpoch: TeamWorkspaceContext.shared.contextEpoch)
    }
    func retain(teams: [TeamWorkspaceTeam]? = nil, transport: @escaping TeamWorkspaceOfflineRetention.Transport) async throws {
        _ = initialScope
        try await TeamWorkspaceOfflineRetention.retain(fence: fence, teams: teams ?? self.teams, removedIDs: [], masterKey: key,
            cache: cache, transport: transport, membership: { id, _ in self.team(id) })
    }
    func response(_ path: String) throws -> Data {
        let components = URLComponents(string: "https://fixture.invalid" + path)!
        let route = components.path
        let last = components.queryItems?.contains { $0.name == "cursor" } == true
        let raw: [String: Any]
        if route == "/v1/chats" { raw = ["chats": [["id": "synthetic-" + (components.queryItems?.first { $0.name == "team_id" }?.value ?? "personal"), "created_at": "2026-10-07T12:00:00Z"]]] }
        else if route == "/v1/workflows" { raw = ["workflows": []] }
        else if route == "/v1/projects" { raw = ["projects": []] }
        else if route == "/v1/user-plans" { raw = ["plans": [], "complete": true] }
        else if route.hasPrefix("/v1/teams/"), route.hasSuffix("/members") { raw = ["members": []] }
        else if route.hasPrefix("/v1/teams/"), route.hasSuffix("/invites") { raw = ["invites": []] }
        else if route.hasPrefix("/v1/teams/"), route.hasSuffix("/memories") { raw = ["memories": []] }
        else if route.hasPrefix("/v1/teams/"), route.hasSuffix("/billing") { raw = ["billing": ["balance_credits": 0, "version": 1]] }
        else if route.hasPrefix("/v1/teams/") { raw = ["team": ["security_policy": [:]]] }
        else if route == "/v1/user-tasks" {
            raw = last ? ["tasks": [["task_id": "task-b"]], "complete": true] : ["tasks": [["task_id": "task-a"]], "complete": false, "next_cursor": "task-a"]
        } else if route.hasSuffix("/activity") { raw = ["activity": []] }
        else if route.hasSuffix("/dependencies") { raw = ["dependencies": []] }
        else { throw TeamWorkspaceError.invalidResponse }
        return try JSONSerialization.data(withJSONObject: raw)
    }
    func clean() { try? FileManager.default.removeItem(at: directory) }
}
