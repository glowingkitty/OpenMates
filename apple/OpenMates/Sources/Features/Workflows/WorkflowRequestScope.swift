// Captured account and server boundary for multi-request Workflow operations.

import Foundation

struct WorkflowRequestScope {
    let accountId: String
    let serverProfile: ServerProfile
    let offlineScope: UUID
    let teamContext: APIRequestTeamContext?

    init(accountId: String, serverProfile: ServerProfile, offlineScope: UUID,
         teamContext: APIRequestTeamContext? = nil) {
        self.accountId = accountId
        self.serverProfile = serverProfile
        self.offlineScope = offlineScope
        self.teamContext = teamContext
    }

    @MainActor
    static func snapshot(accountId: String) -> WorkflowRequestScope {
        WorkflowRequestScope(
            accountId: accountId, serverProfile: ServerProfile.current(),
            offlineScope: OfflineStore.shared.scopeGeneration,
            teamContext: APIRequestTeamContext(epoch: TeamWorkspaceContext.shared.contextEpoch,
                                               teamID: TeamWorkspaceContext.shared.teamID)
        )
    }

    @MainActor
    func matchesContext(environment: WorkflowAPISendEnvironment = .live) -> Bool {
        let teamMatches: Bool
        if let teamContext {
            let current = environment.currentTeamContext()
            teamMatches = current.epoch == teamContext.epoch && current.teamID == teamContext.teamID
        } else {
            teamMatches = true
        }
        return environment.currentProfile() == serverProfile &&
            environment.currentOfflineScope() == offlineScope && teamMatches
    }

    @MainActor
    func check(environment: WorkflowAPISendEnvironment = .live) async throws {
        guard !accountId.isEmpty, matchesContext(environment: environment),
              await environment.currentAccountID() == accountId,
              matchesContext(environment: environment) else { throw CancellationError() }
    }

    static func capture(accountId: String) async throws -> WorkflowRequestScope {
        let scope = await MainActor.run { snapshot(accountId: accountId) }
        try await scope.check()
        return scope
    }
}
