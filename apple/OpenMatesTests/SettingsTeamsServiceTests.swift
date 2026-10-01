import CryptoKit
import XCTest
@testable import OpenMates

@MainActor
final class SettingsTeamsServiceTests: XCTestCase {
    // contract-test: supporting surface=gui.apple assertions=teams.lifecycle.encrypted-profiled
    func testCreateUsesWrappedRandomTeamKeyAndEncryptedWebPayload() async throws {
        let scope = SettingsTeamsTestScope()
        let masterKey = SymmetricKey(size: .bits256)
        let reader = SettingsTeamsTestReader()
        var captured: [String: Any] = [:]
        let service = SettingsTeamsService(reader: reader, transport: { method, path, bytes, _ in
            XCTAssertEqual(method, .post); XCTAssertEqual(path, "/v1/teams")
            captured = try XCTUnwrap(JSONSerialization.jsonObject(with: XCTUnwrap(bytes)) as? [String: Any])
            return try JSONSerialization.data(withJSONObject: ["team": ["team_id": captured["team_id"]!]])
        }, masterKey: { _ in masterKey })
        let created = try await service.create(name: "  Encrypted workspace  ", description: "Private description", fence: scope.fence)
        XCTAssertEqual(created.id, reader.requestedID)
        XCTAssertNil(captured["name"]); XCTAssertNil(captured["description"]); XCTAssertNil(captured["team_key"])
        let wrapped = try XCTUnwrap(captured["encrypted_team_key"] as? String)
        let key = try await CryptoManager.shared.unwrapChatKey(encryptedChatKeyBase64: wrapped, masterKey: masterKey)
        let encryptedName = try XCTUnwrap(captured["encrypted_name"] as? String)
        let name = try await CryptoManager.shared.decryptContent(base64String: encryptedName, key: key)
        let description = try await CryptoManager.shared.decryptContent(base64String: XCTUnwrap(captured["encrypted_description"] as? String), key: key)
        let zero = try await CryptoManager.shared.decryptContent(base64String: XCTUnwrap(captured["encrypted_zero_balance"] as? String), key: key)
        let profile = try await CryptoManager.shared.decryptContent(base64String: XCTUnwrap(captured["encrypted_profile_image_metadata"] as? String), key: key)
        XCTAssertEqual(name, "Encrypted workspace"); XCTAssertEqual(description, "Private description"); XCTAssertEqual(zero, "0")
        let metadata = try XCTUnwrap(JSONSerialization.jsonObject(with: Data(profile.utf8)) as? [String: Any])
        XCTAssertEqual(metadata["icon_name"] as? String, "team")
        XCTAssertEqual(metadata["background_color"] as? String, "#4d73ff")
        XCTAssertEqual(captured["created_at"] as? Int, captured["updated_at"] as? Int)
        do {
            _ = try await CryptoManager.shared.decryptContent(base64String: encryptedName, key: masterKey)
            XCTFail("Account master key must not decrypt team metadata")
        } catch { }
    }

    // contract-test: supporting surface=gui.apple assertions=teams.membership.role-gated,teams.invites.fragment-key-web-flow
    func testInviteNormalizesDeliveryAddressEncryptsHintAndRejectsViewerBeforeTransport() async throws {
        let scope = SettingsTeamsTestScope()
        let team = makeSettingsTestTeam("team/encoded", role: .owner)
        var calls = 0
        let service = SettingsTeamsService(transport: { method, path, bytes, _ in
            calls += 1
            XCTAssertEqual(method, .post); XCTAssertEqual(path, "/v1/teams/team%2Fencoded/invites")
            let body = try XCTUnwrap(JSONSerialization.jsonObject(with: XCTUnwrap(bytes)) as? [String: Any])
            XCTAssertEqual(body["recipient_email"] as? String, "teammate@example.com")
            XCTAssertEqual(body["role"] as? String, "member")
            XCTAssertEqual((body["expires_at"] as? Int ?? 0) - (body["created_at"] as? Int ?? 0), 7 * 24 * 60 * 60)
            let hint = try await CryptoManager.shared.decryptContent(base64String: XCTUnwrap(body["encrypted_recipient_hint"] as? String), key: team.key)
            let hintObject = try XCTUnwrap(JSONSerialization.jsonObject(with: Data(hint.utf8)) as? [String: String])
            XCTAssertEqual(hintObject, ["recipient_email": "teammate@example.com", "role": "member"])
            return Data(#"{"invite":{"delivery_status":"sent"}}"#.utf8)
        })
        let sent = try await service.invite(team: team, email: "  Teammate@Example.COM \n", fence: scope.fence)
        XCTAssertTrue(sent)
        do {
            _ = try await service.invite(team: makeSettingsTestTeam("viewer", role: .viewer), email: "teammate@example.com", fence: scope.fence)
            XCTFail("Viewer may not create invites")
        } catch SettingsTeamsError.permissionDenied { }
        XCTAssertEqual(calls, 1)
    }

    // contract-test: supporting surface=gui.apple assertions=teams.lifecycle.encrypted-profiled,teams.membership.role-gated
    func testBillingDecryptsBalanceAndCountsOnlyTeamMemories() async throws {
        let scope = SettingsTeamsTestScope()
        let team = makeSettingsTestTeam("one", role: .owner)
        let encrypted = try await CryptoManager.shared.encryptWithMasterKey("72", masterKey: team.key)
        var paths: [String] = []
        let service = SettingsTeamsService(transport: { _, path, _, _ in
            paths.append(path)
            let result: [String: Any] = path.hasSuffix("billing")
                ? ["billing": ["balance_credits": -1, "encrypted_balance": encrypted]]
                : ["memories": [["id": "team-memory-1"], ["id": "team-memory-2"]]]
            return try JSONSerialization.data(withJSONObject: result)
        })
        let result = try await service.details(team: team, fence: scope.fence)
        XCTAssertEqual(result, SettingsTeamDetails(credits: 72, memoryCount: 2))
        XCTAssertEqual(paths, ["/v1/teams/one/billing", "/v1/teams/one/memories"])
    }

    // contract-test: supporting surface=gui.apple assertions=teams.membership.role-gated
    func testMemberAndViewerDetailsSkipForbiddenBillingRead() async throws {
        let scope = SettingsTeamsTestScope()
        var paths: [String] = []
        let service = SettingsTeamsService(transport: { _, path, _, _ in
            paths.append(path)
            XCTAssertTrue(path.hasSuffix("/memories"))
            return Data(#"{"memories":[{"id":"readable-team-memory"}]}"#.utf8)
        })
        for role in [TeamWorkspaceRole.member, .viewer] {
            let result = try await service.details(team: makeSettingsTestTeam(role.rawValue, role: role), fence: scope.fence)
            XCTAssertEqual(result, SettingsTeamDetails(credits: 0, memoryCount: 1))
        }
        XCTAssertEqual(paths, ["/v1/teams/member/memories", "/v1/teams/viewer/memories"])
    }

    // contract-test: supporting surface=gui.apple assertions=teams.context.full-switch-local
    func testFoundationReaderPinsIdentityAndRejectsLateChangedAccountResponse() async throws {
        let scope = SettingsTeamsTestScope()
        let fence = scope.fence
        let reader = TeamWorkspaceService(transport: { path, pinned in
            XCTAssertEqual(path, "/v1/teams")
            XCTAssertEqual(pinned.accountID, "settings-test-account")
            XCTAssertEqual(pinned.scope, fence.scope); XCTAssertEqual(pinned.server, .development)
            scope.accountID = "another-account"
            return Data(#"{"teams":[]}"#.utf8)
        })
        do {
            _ = try await reader.listTeams(fence: fence)
            XCTFail("Reader must reject a response after account changes")
        } catch TeamWorkspaceError.staleContext { }
    }

    // contract-test: supporting surface=gui.apple assertions=teams.context.full-switch-local
    func testStaleFenceCannotStartTransport() async throws {
        let scope = SettingsTeamsTestScope()
        let fence = scope.fence
        scope.accountID = "another-account"
        var calls = 0
        let service = SettingsTeamsService(transport: { _, _, _, _ in calls += 1; return Data() })
        do {
            _ = try await service.details(team: makeSettingsTestTeam("one"), fence: fence)
            XCTFail("Changed account must invalidate team operations")
        } catch TeamWorkspaceError.staleContext { }
        XCTAssertEqual(calls, 0)
    }

    // contract-test: supporting surface=gui.apple assertions=teams.context.full-switch-local
    func testControllerAccountResetSuppressesOldListAndKeys() async {
        let scope = SettingsTeamsTestScope()
        let service = SettingsTeamsTestService()
        service.suspendList = true
        let controller = SettingsTeamsController(service: service, environment: scope.environment)
        let task = Task { await controller.load(accountID: scope.accountID) }
        for _ in 0..<100 where service.listContinuation == nil { await Task.yield() }
        XCTAssertNotNil(service.listContinuation)
        scope.accountID = "another-account"; scope.scope = UUID(); controller.reset()
        service.listContinuation?.resume(returning: [makeSettingsTestTeam("old-private-team")])
        await task.value
        XCTAssertTrue(controller.teams.isEmpty); XCTAssertNil(controller.selected); XCTAssertFalse(controller.loading)
    }

    // contract-test: supporting surface=gui.apple assertions=teams.context.full-switch-local,settings-ui.navigation.parent-return
    func testReturningToOverviewSuppressesPendingTeamDetail() async {
        let scope = SettingsTeamsTestScope()
        let service = SettingsTeamsTestService()
        service.teams = [makeSettingsTestTeam("one")]
        let controller = SettingsTeamsController(service: service, environment: scope.environment)
        await controller.load(accountID: scope.accountID)
        service.suspendDetails = true
        let task = Task { await controller.select("one") }
        for _ in 0..<100 where service.detailContinuation == nil { await Task.yield() }
        XCTAssertNotNil(service.detailContinuation)
        await controller.select(nil)
        service.detailContinuation?.resume(returning: SettingsTeamDetails(credits: 123, memoryCount: 3))
        await task.value
        XCTAssertNil(controller.selectedID); XCTAssertNil(controller.details); XCTAssertFalse(controller.loading)
    }
}

@MainActor private final class SettingsTeamsTestScope {
    var accountID = "settings-test-account"
    var scope = UUID()
    var server = ServerProfile.development
    var environment: TeamWorkspaceEnvironment {
        TeamWorkspaceEnvironment(currentAccountID: { self.accountID }, scopeGeneration: { self.scope }, serverProfile: { self.server })
    }
    var fence: TeamWorkspaceFence { TeamWorkspaceFence(accountID: accountID, environment: environment) }
}

@MainActor private final class SettingsTeamsTestReader: TeamWorkspaceServing {
    var requestedID: String?
    func listTeams(fence: TeamWorkspaceFence) async throws -> [TeamWorkspaceTeam] { [] }
    func getTeam(_ id: String, fence: TeamWorkspaceFence) async throws -> TeamWorkspaceTeam {
        requestedID = id; return makeSettingsTestTeam(id)
    }
}

@MainActor private final class SettingsTeamsTestService: SettingsTeamsServing {
    var teams: [TeamWorkspaceTeam] = []
    var suspendList = false
    var suspendDetails = false
    var listContinuation: CheckedContinuation<[TeamWorkspaceTeam], Never>?
    var detailContinuation: CheckedContinuation<SettingsTeamDetails, Never>?
    func list(fence: TeamWorkspaceFence) async throws -> [TeamWorkspaceTeam] {
        if suspendList { return await withCheckedContinuation { listContinuation = $0 } }
        return teams
    }
    func details(team: TeamWorkspaceTeam, fence: TeamWorkspaceFence) async throws -> SettingsTeamDetails {
        if suspendDetails { return await withCheckedContinuation { detailContinuation = $0 } }
        return SettingsTeamDetails(credits: 0, memoryCount: 0)
    }
    func create(name: String, description: String, fence: TeamWorkspaceFence) async throws -> TeamWorkspaceTeam { makeSettingsTestTeam("created") }
    func invite(team: TeamWorkspaceTeam, email: String, fence: TeamWorkspaceFence) async throws -> Bool { true }
}

private func makeSettingsTestTeam(_ id: String, role: TeamWorkspaceRole = .owner) -> TeamWorkspaceTeam {
    TeamWorkspaceTeam(id: id, name: "Synthetic team", description: "Test state", role: role, status: "active",
        profileImageMetadata: .generated, zeroBalance: 0, createdAt: 1, updatedAt: 1, key: SymmetricKey(size: .bits256))
}
