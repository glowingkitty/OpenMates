// Web source: frontend/packages/ui/src/components/settings/SettingsTeams.svelte
// Specification: specifications/features/teams/specification.yml
// Assertions: teams.lifecycle.encrypted-profiled, teams.membership.role-gated, teams.context.full-switch-local

import Combine
import CryptoKit
import Foundation

@MainActor
final class SettingsTeamsController: ObservableObject {
    @Published private(set) var teams: [TeamWorkspaceTeam] = []
    @Published private(set) var selectedID: String?
    @Published private(set) var details: SettingsTeamDetails?
    @Published private(set) var loading = false
    @Published private(set) var creating = false
    @Published private(set) var inviting = false
    @Published private(set) var failed = false
    @Published private(set) var inviteSent: Bool?
    @Published private(set) var inviteFailed = false
    private let service: any SettingsTeamsServing
    private let environment: TeamWorkspaceEnvironment
    private var accountID: String?
    private var generation = UUID()
    private var selectionGeneration = UUID()

    init(service: any SettingsTeamsServing = SettingsTeamsService(), environment: TeamWorkspaceEnvironment = .live) {
        self.service = service
        self.environment = environment
    }

    var selected: TeamWorkspaceTeam? { teams.first { $0.id == selectedID } }

    func reset() {
        generation = UUID(); selectionGeneration = UUID(); accountID = nil
        teams = []; selectedID = nil; details = nil
        loading = false; creating = false; inviting = false; failed = false
        inviteSent = nil; inviteFailed = false
    }

    func load(accountID: String?, initialTeamID: String? = nil) async {
        reset()
        guard let accountID else { return }
        self.accountID = accountID
        selectedID = initialTeamID
        let token = generation
        let fence = TeamWorkspaceFence(accountID: accountID, environment: environment)
        loading = true
        do {
            let result = try await service.list(fence: fence)
            try await fence.check()
            guard generation == token else { return }
            teams = result
            loading = false
            if initialTeamID != nil { await select(initialTeamID) }
        } catch {
            guard generation == token else { return }
            if case TeamWorkspaceError.staleContext = error { reset(); return }
            do { try await fence.check() } catch { if generation == token { reset() }; return }
            guard generation == token else { return }
            loading = false; failed = true
        }
    }

    func select(_ id: String?) async {
        selectionGeneration = UUID()
        let selectionToken = selectionGeneration
        selectedID = id; details = nil; inviteSent = nil; inviteFailed = false; inviting = false
        loading = false; failed = false
        guard let team = selected, let accountID else { return }
        let token = generation
        let fence = TeamWorkspaceFence(accountID: accountID, environment: environment)
        loading = true; failed = false
        do {
            let result = try await service.details(team: team, fence: fence)
            try await fence.check()
            guard generation == token, selectionGeneration == selectionToken else { return }
            details = result; loading = false
        } catch {
            guard generation == token, selectionGeneration == selectionToken else { return }
            if case TeamWorkspaceError.staleContext = error { reset(); return }
            do { try await fence.check() } catch { if generation == token { reset() }; return }
            guard generation == token, selectionGeneration == selectionToken else { return }
            loading = false; failed = true
        }
    }

    @discardableResult
    func create(name: String, description: String) async -> Bool {
        guard let accountID, !creating else { return false }
        let token = generation
        let fence = TeamWorkspaceFence(accountID: accountID, environment: environment)
        creating = true; failed = false
        do {
            let team = try await service.create(name: name, description: description, fence: fence)
            try await fence.check()
            guard generation == token else { return false }
            teams.insert(team, at: 0); creating = false
            await select(team.id)
            return generation == token
        } catch {
            guard generation == token else { return false }
            if case TeamWorkspaceError.staleContext = error { reset(); return false }
            do { try await fence.check() } catch { if generation == token { reset() }; return false }
            guard generation == token else { return false }
            creating = false; failed = true
            return false
        }
    }

    func invite(email: String) async {
        guard let team = selected, team.canManage, let accountID, !inviting else { return }
        let token = generation, selectionToken = selectionGeneration
        let fence = TeamWorkspaceFence(accountID: accountID, environment: environment)
        inviting = true; inviteSent = nil; inviteFailed = false
        do {
            let sent = try await service.invite(team: team, email: email, fence: fence)
            try await fence.check()
            guard generation == token, selectionGeneration == selectionToken else { return }
            inviting = false; inviteSent = sent
        } catch {
            guard generation == token, selectionGeneration == selectionToken else { return }
            if case TeamWorkspaceError.staleContext = error { reset(); return }
            do { try await fence.check() } catch { if generation == token { reset() }; return }
            guard generation == token, selectionGeneration == selectionToken else { return }
            inviting = false; inviteFailed = true
        }
    }
}

#if DEBUG
// Scoped synthetic UI state; never calls an account API or persists team keys.
@MainActor
final class SettingsTeamsUITestService: SettingsTeamsServing {
    private var teams: [TeamWorkspaceTeam] = []
    func list(fence: TeamWorkspaceFence) async throws -> [TeamWorkspaceTeam] { try await fence.check(); return teams }
    func create(name: String, description: String, fence: TeamWorkspaceFence) async throws -> TeamWorkspaceTeam {
        try await fence.check()
        let team = TeamWorkspaceTeam(id: "ui-test-created-team", name: name.trimmingCharacters(in: .whitespacesAndNewlines),
            description: description, role: .owner, status: "active", profileImageMetadata: .generated,
            zeroBalance: 0, createdAt: 1, updatedAt: 1, key: SymmetricKey(size: .bits256))
        teams.insert(team, at: 0)
        return team
    }
    func details(team: TeamWorkspaceTeam, fence: TeamWorkspaceFence) async throws -> SettingsTeamDetails {
        try await fence.check(); return SettingsTeamDetails(credits: 0, memoryCount: 0)
    }
    func invite(team: TeamWorkspaceTeam, email: String, fence: TeamWorkspaceFence) async throws -> Bool {
        try await fence.check(); guard team.canManage else { throw SettingsTeamsError.permissionDenied }; return true
    }
}
#endif
