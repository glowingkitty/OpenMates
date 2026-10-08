// Web source: frontend/packages/ui/src/components/settings/SettingsTeams.svelte
// Specification: specifications/features/teams/specification.yml
// Assertions: teams.lifecycle.encrypted-profiled, teams.membership.role-gated, teams.context.full-switch-local

// Specification: specifications/architecture/storage-lifecycle/specification.yml
// Assertions: storage.cold.discoverable-bounded, storage.cold.shared-team-authorized, storage.surface.semantic-parity

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
    @Published private(set) var checkingName = false
    @Published private(set) var creationFailed = false
    @Published private(set) var nameCheckFailed = false
    @Published private(set) var createdForDraft: TeamWorkspaceTeam?
    @Published private(set) var memberAvatarData: [String: Data] = [:]
    private var creationGeneration = UUID()
    private var approvedCreationName: String?
    private var memberAvatarGeneration = UUID()
    @Published private(set) var inviting = false
    @Published private(set) var failed = false
    @Published private(set) var inviteSent: Bool?
    @Published private(set) var inviteFailed = false
    @Published private(set) var management: SettingsTeamManagement?
    @Published private(set) var managementLoading = false
    @Published private(set) var managementFailed = false
    @Published private(set) var actionBusy = false
    @Published private(set) var actionFailed = false
    @Published private(set) var inviteURL: URL?
    @Published private(set) var avatarData: Data?
    @Published private(set) var avatarFailed = false
    @Published private(set) var accountDeleted = false
    @Published private(set) var imageRejected = false
    @Published private(set) var imageFinalWarning = false
    @Published private(set) var storage: TeamStorageOverview?
    @Published private(set) var storageLoading = false
    @Published private(set) var storageFailed = false
    let storageNotice = StorageNoticeController()
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
        creationGeneration = UUID()
        checkingName = false; creationFailed = false; nameCheckFailed = false
        createdForDraft = nil; approvedCreationName = nil
        memberAvatarGeneration = UUID(); memberAvatarData = [:]
        storage = nil; storageLoading = false; storageFailed = false; storageNotice.reset()
        teams = []; selectedID = nil; details = nil
        management = nil; managementLoading = false; managementFailed = false
        actionBusy = false; actionFailed = false; inviteURL = nil
        avatarData = nil; avatarFailed = false; imageRejected = false; imageFinalWarning = false; accountDeleted = false
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
        memberAvatarGeneration = UUID(); memberAvatarData = [:]
        selectionGeneration = UUID()
        let selectionToken = selectionGeneration
        storage = nil; storageLoading = false; storageFailed = false; storageNotice.reset()
        management = nil; managementLoading = false; managementFailed = false
        actionBusy = false; actionFailed = false; inviteURL = nil
        avatarData = nil; avatarFailed = false; imageRejected = false; imageFinalWarning = false; accountDeleted = false
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
            await loadAvatar()
            await loadManagement()
            await loadStorage()
        } catch {
            guard generation == token, selectionGeneration == selectionToken else { return }
            if case TeamWorkspaceError.staleContext = error { reset(); return }
            do { try await fence.check() } catch { if generation == token { reset() }; return }
            guard generation == token, selectionGeneration == selectionToken else { return }
            loading = false; failed = true
            if let connectivity = error as? URLError,
               [.notConnectedToInternet, .networkConnectionLost, .timedOut, .cannotConnectToHost, .cannotFindHost].contains(connectivity.code) {
                await loadAvatar()
                await loadManagement()
            }
        }
    }

    func loadStorage() async {
        guard let team = selected, team.canViewBilling, let accountID, !storageLoading else { return }
        let token = generation, selectionToken = selectionGeneration
        let fence = TeamWorkspaceFence(accountID: accountID, environment: environment)
        storageLoading = true; storageFailed = false
        do {
            let result = try await service.storage(team: team, fence: fence)
            try await fence.check()
            guard generation == token, selectionGeneration == selectionToken else { return }
            storage = result; storageLoading = false
            if result.billingStatus != .disabledPendingValidation {
                await storageNotice.configure(limit: 50) { [weak self, service] after in
                    guard let self, self.generation == token, self.selectionGeneration == selectionToken else { throw TeamWorkspaceError.staleContext }
                    do {
                        let result = try await service.storageNotice(team: team, fence: fence, after: after)
                        try await fence.check()
                        guard self.generation == token, self.selectionGeneration == selectionToken else { throw TeamWorkspaceError.staleContext }
                        return result
                    } catch TeamWorkspaceError.staleContext {
                        if self.generation == token, self.selectionGeneration == selectionToken { self.reset() }
                        throw TeamWorkspaceError.staleContext
                    }
                }
            } else { storageNotice.reset() }
        } catch {
            guard generation == token, selectionGeneration == selectionToken else { return }
            storage = nil; storageNotice.reset(); storageLoading = false
            if case TeamWorkspaceError.staleContext = error { reset(); return }
            do { try await fence.check() } catch { if generation == token { reset() }; return }
            guard generation == token, selectionGeneration == selectionToken else { return }
            storageFailed = true
        }
    }

    func membershipChanged(_ currentTeams: [TeamWorkspaceTeam]) async {
        guard let id = selectedID, let old = selected else { return }
        guard let current = currentTeams.first(where: { $0.id == id }), current.canRead else { reset(); return }
        guard current.role != old.role || current.updatedAt != old.updatedAt else { return }
        if let index = teams.firstIndex(where: { $0.id == id }) { teams[index] = current }
        await select(id)
    }

    func beginCreation() {
        guard !creating, !checkingName else { return }
        creationGeneration = UUID()
        approvedCreationName = nil; createdForDraft = nil
        nameCheckFailed = false; creationFailed = false; imageRejected = false; imageFinalWarning = false
    }

    func cancelCreationCheck() {
        creationGeneration = UUID(); checkingName = false; nameCheckFailed = false
    }

    @discardableResult
    func continueCreation(name: String) async -> Bool {
        guard let accountID, !checkingName, !creating else { return false }
        let normalized = name.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !normalized.isEmpty else { return false }
        let token = generation, creationToken = creationGeneration
        let fence = TeamWorkspaceFence(accountID: accountID, environment: environment)
        checkingName = true; nameCheckFailed = false
        do {
            try await service.checkCreationName(normalized, fence: fence)
            try await fence.check()
            guard generation == token, creationToken == creationGeneration else { return false }
            approvedCreationName = normalized; checkingName = false
            return true
        } catch {
            guard generation == token, creationToken == creationGeneration else { return false }
            guard (try? await fence.check()) != nil, generation == token, creationToken == creationGeneration else { return false }
            checkingName = false; nameCheckFailed = true
            return false
        }
    }

    @discardableResult
    func create(name: String, description: String, memberName: String? = nil,
                icon: String = "team", color: String = "#4d73ff", jpeg: Data? = nil) async -> Bool {
        let normalized = name.trimmingCharacters(in: .whitespacesAndNewlines)
        guard let accountID, !creating, !checkingName, approvedCreationName == normalized else { return false }
        // A failed image upload keeps this same Team, including after back/forward.
        // Editing the name after creation requires the normal rename screen.
        guard createdForDraft == nil || createdForDraft?.name == normalized else { return false }
        let token = generation
        let fence = TeamWorkspaceFence(accountID: accountID, environment: environment)
        let retryingCreatedDraft = createdForDraft != nil
        creating = true; creationFailed = false; imageRejected = false; imageFinalWarning = false
        do {
            var team: TeamWorkspaceTeam
            if let retained = createdForDraft { team = retained }
            else {
                team = try await service.createProfiledAvatar(name: normalized, description: description, memberName: memberName,
                    icon: icon, color: color, fence: fence)
                try await fence.check()
                guard generation == token else { return false }
                createdForDraft = team
                teams.removeAll { $0.id == team.id }; teams.insert(team, at: 0)
            }
            if let jpeg { team = try await service.uploadAvatar(team: team, jpeg: jpeg, fence: fence) }
            // A prior upload may have succeeded before its follow-up read failed.
            // Explicit generated recovery must overwrite that uncertain server state.
            else if retryingCreatedDraft || team.profileImageMetadata.iconName != icon || team.profileImageMetadata.backgroundColor != color {
                team = try await service.saveAvatar(team: team, icon: icon, color: color, fence: fence)
            }
            try await fence.check()
            guard generation == token else { return false }
            teams.removeAll { $0.id == team.id }; teams.insert(team, at: 0)
            createdForDraft = nil; approvedCreationName = nil; creating = false
            await select(team.id)
            return generation == token
        } catch {
            guard generation == token else { return false }
            if case TeamWorkspaceError.staleContext = error { reset(); return false }
            guard (try? await fence.check()) != nil, generation == token else { return false }
            if case SettingsTeamsError.accountDeleted = error { accountDeleted = true }
            if case SettingsTeamsError.imageRejected = error { imageRejected = true }
            if case SettingsTeamsError.imageRejectedFinalWarning = error { imageRejected = true; imageFinalWarning = true }
            creating = false; creationFailed = true
            return false
        }
    }

    func invite(email: String?) async {
        guard let team = selected, team.canManage, let accountID, !inviting else { return }
        let token = generation, selectionToken = selectionGeneration
        let fence = TeamWorkspaceFence(accountID: accountID, environment: environment)
        inviting = true; inviteSent = nil; inviteFailed = false
        do {
            let result = try await service.invitation(team: team, email: email, fence: fence)
            try await fence.check()
            guard generation == token, selectionGeneration == selectionToken else { return }
            inviting = false; inviteSent = result.delivered; inviteURL = result.url
            await loadManagement()
        } catch {
            guard generation == token, selectionGeneration == selectionToken else { return }
            if case TeamWorkspaceError.staleContext = error { reset(); return }
            do { try await fence.check() } catch { if generation == token { reset() }; return }
            guard generation == token, selectionGeneration == selectionToken else { return }
            inviting = false; inviteFailed = true
        }
    }
    func loadManagement() async {
        guard let team = selected, let accountID, !managementLoading else { return }
        let token = generation, selectionToken = selectionGeneration
        let fence = TeamWorkspaceFence(accountID: accountID, environment: environment)
        memberAvatarGeneration = UUID(); memberAvatarData = [:]
        managementLoading = true; managementFailed = false
        do {
            let value = try await service.management(team: team, fence: fence)
            try await fence.check()
            guard token == generation, selectionToken == selectionGeneration else { return }
            management = value; managementLoading = false
            await loadMemberAvatars(value.members, team: team, fence: fence)
        } catch {
            guard token == generation, selectionToken == selectionGeneration else { return }
            if case TeamWorkspaceError.staleContext = error { reset(); return }
            guard (try? await fence.check()) != nil else { reset(); return }
            managementLoading = false; managementFailed = true
        }
    }

    private func loadMemberAvatars(_ members: [SettingsTeamMember], team: TeamWorkspaceTeam, fence: TeamWorkspaceFence) async {
        let token = generation, selectionToken = selectionGeneration, avatarToken = memberAvatarGeneration
        for member in members {
            guard token == generation, selectionToken == selectionGeneration, avatarToken == memberAvatarGeneration else { return }
            let data = try? await service.memberAvatar(team: team, member: member, fence: fence)
            guard (try? await fence.check()) != nil, token == generation, selectionToken == selectionGeneration,
                  avatarToken == memberAvatarGeneration, selected?.canRead == true,
                  management?.members.contains(where: { $0 == member }) == true else { return }
            if let data { memberAvatarData[member.id] = data }
        }
    }

    private func perform(_ action: (TeamWorkspaceTeam, TeamWorkspaceFence) async throws -> TeamWorkspaceTeam?) async {
        guard let team = selected, team.canManage, let accountID, !actionBusy else { return }
        let token = generation, selectionToken = selectionGeneration
        let fence = TeamWorkspaceFence(accountID: accountID, environment: environment)
        actionBusy = true; actionFailed = false
        do {
            let updated = try await action(team, fence)
            try await fence.check()
            guard token == generation, selectionToken == selectionGeneration else { return }
            if let updated, let index = teams.firstIndex(where: { $0.id == updated.id }) { teams[index] = updated }
            actionBusy = false
            await loadManagement()
        } catch {
            guard token == generation, selectionToken == selectionGeneration else { return }
            if case TeamWorkspaceError.staleContext = error { reset(); return }
            guard (try? await fence.check()) != nil else { reset(); return }
            if case SettingsTeamsError.accountDeleted = error { accountDeleted = true }
            if case SettingsTeamsError.imageRejected = error { imageRejected = true }
            if case SettingsTeamsError.imageRejectedFinalWarning = error { imageRejected = true; imageFinalWarning = true }
            actionBusy = false; actionFailed = true
        }
    }

    func loadAvatar() async {
        guard let team = selected, let accountID else { return }
        let token = generation, selectionToken = selectionGeneration
        let fence = TeamWorkspaceFence(accountID: accountID, environment: environment)
        do {
            let data = try await service.avatar(team: team, fence: fence)
            try await fence.check()
            guard token == generation, selectionToken == selectionGeneration else { return }
            avatarData = data; avatarFailed = false
        } catch {
            guard token == generation, selectionToken == selectionGeneration else { return }
            avatarFailed = true
        }
    }
    func uploadAvatar(_ data: Data) async {
        imageRejected = false; imageFinalWarning = false
        await perform { team, fence in try await self.service.uploadAvatar(team: team, jpeg: data, fence: fence) }
        if !actionFailed { await loadAvatar() }
    }
    func saveAvatar(icon: String, color: String) async {
        await perform { team, fence in try await self.service.saveAvatar(team: team, icon: icon, color: color, fence: fence) }
        if !actionFailed { await loadAvatar() }
    }
    func rename(_ name: String) async {
        await perform { team, fence in try await self.service.rename(team: team, name: name, fence: fence) }
    }
    func changeRole(_ member: SettingsTeamMember, role: TeamWorkspaceRole) async {
        await perform { team, fence in try await self.service.changeRole(team: team, member: member, role: role, fence: fence); return nil }
    }
    func removeMember(_ member: SettingsTeamMember) async {
        await perform { team, fence in try await self.service.removeMember(team: team, member: member, fence: fence); return nil }
    }
    func revokeInvite(_ id: String) async {
        await perform { team, fence in try await self.service.revokeInvite(team: team, inviteID: id, fence: fence); return nil }
    }
    func saveSecurity(_ policy: SettingsTeamSecurity) async {
        await perform { team, fence in
            _ = try await self.service.saveSecurity(team: team, policy: policy, fence: fence)
            return nil
        }
    }
    func deleteSelected(confirmed: Bool) async {
        guard confirmed, selected?.role == .owner else { return }
        let id = selectedID
        await perform { team, fence in try await self.service.delete(team: team, fence: fence); return nil }
        guard !actionFailed, selectedID == id else { return }
        teams.removeAll { $0.id == id }
        await select(nil)
        if let accountID { await TeamWorkspaceContext.shared.load(accountID: accountID) }
    }

}

#if DEBUG
// Scoped synthetic UI state; never calls an account API or persists team keys.
@MainActor
final class SettingsTeamsUITestService: SettingsTeamsServing {
    private var teams: [TeamWorkspaceTeam] = []
    func list(fence: TeamWorkspaceFence) async throws -> [TeamWorkspaceTeam] { try await fence.check(); return teams }
    func checkCreationName(_ name: String, fence: TeamWorkspaceFence) async throws { try await fence.check() }
    func createProfiledAvatar(name: String, description: String, memberName: String?, icon: String, color: String, fence: TeamWorkspaceFence) async throws -> TeamWorkspaceTeam {
        let team = try await create(name: name, description: description, fence: fence)
        return try await saveAvatar(team: team, icon: icon, color: color, fence: fence)
    }
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
    func storage(team: TeamWorkspaceTeam, fence: TeamWorkspaceFence) async throws -> TeamStorageOverview {
        try await fence.check()
        guard team.canViewBilling else { throw SettingsTeamsError.permissionDenied }
        let rawStatus = ProcessInfo.processInfo.arguments.first { $0.hasPrefix("--ui-test-team-storage-status=") }?.split(separator: "=").last.map(String.init)
        let status = rawStatus.flatMap(StorageBillingStatus.init(rawValue:)) ?? .current
        let hasDebt = status == .unpaid || status == .manualReview
        return TeamStorageOverview(totalBytes: hasDebt ? 1_073_741_825 : 0, legacyUploadBytes: 0,
            logicalS3Bytes: hasDebt ? 1_073_741_825 : 0, categories: [:], measurementAt: 1_800_000_000,
            meteringSourceVersion: "synthetic", meteringPolicyVersion: "synthetic", freeBytes: 1_073_741_824,
            creditsPerStartedExcessGibPerWeek: 3, billableGib: hasDebt ? 1 : 0,
            weeklyCostCredits: hasDebt ? 3 : 0, billingStatus: status,
            billing: StorageBillingState(status: status, warningCount: hasDebt ? 4 : 0,
                deadlineAt: hasDebt ? 1_800_000_000 : nil, expiryDue: hasDebt, expiryEnabled: false,
                outstandingCredits: hasDebt ? 3 : 0, invoices: [], hasMoreInvoices: false,
                affectedUnits: [], hasMoreAffectedUnits: false))
    }
    func storageNotice(team: TeamWorkspaceTeam, fence: TeamWorkspaceFence, after: String?) async throws -> StorageNotice {
        try await fence.check()
        guard team.canViewBilling else { throw SettingsTeamsError.permissionDenied }
        let summary = try await storage(team: team, fence: fence)
        let hasDebt = summary.billingStatus == .unpaid || summary.billingStatus == .manualReview
        return StorageNotice(episodeId: hasDebt ? "synthetic-episode" : nil, warningCount: hasDebt ? 4 : 0,
            deadlineAt: hasDebt ? 1_800_000_000 : nil, manualReview: summary.billingStatus == .manualReview,
            unitSelectionHash: nil, units: [], hasMore: false, nextAfterUnitId: nil)
    }
    func management(team: TeamWorkspaceTeam, fence: TeamWorkspaceFence) async throws -> SettingsTeamManagement {
        try await fence.check()
        return SettingsTeamManagement(members: [.init(id: "synthetic-owner", userID: "synthetic-owner", name: "Owner", role: .owner, status: "active", avatarIcon: "heart", avatarColor: "#e35d6a")], invites: [], security: SettingsTeamSecurity())
    }
    func saveAvatar(team: TeamWorkspaceTeam, icon: String, color: String, fence: TeamWorkspaceFence) async throws -> TeamWorkspaceTeam {
        try await fence.check()
        guard team.canManage else { throw SettingsTeamsError.permissionDenied }
        let updated = TeamWorkspaceTeam(id: team.id, name: team.name, description: team.description, role: team.role, status: team.status,
            profileImageMetadata: .init(version: 1, mode: "generated", iconName: icon, iconColor: "#ffffff", backgroundColor: color),
            zeroBalance: team.zeroBalance, createdAt: team.createdAt, updatedAt: team.updatedAt + 1, key: team.key)
        if let index = teams.firstIndex(where: { $0.id == team.id }) { teams[index] = updated }
        return updated
    }
    func invite(team: TeamWorkspaceTeam, email: String, fence: TeamWorkspaceFence) async throws -> Bool {
        try await fence.check(); guard team.canManage else { throw SettingsTeamsError.permissionDenied }; return true
    }
}
#endif
