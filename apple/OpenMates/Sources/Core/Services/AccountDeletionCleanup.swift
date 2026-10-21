// Capture the initiating request's owner before a confirmed account-deletion result.
// No identity is persisted, logged, or derived from the replacement session.
// Specification: specifications/features/billing/specification.yml
// Assertions: billing.access.authenticated-first-party
// Specification: specifications/features/auth/specification.yml
// Assertions: auth.session.isolation

import Foundation

@MainActor
struct AccountDeletionCleanup {
    struct Identity: Equatable {
        let accountID: String
        let cacheGeneration: UUID
        let activeCacheScopeID: String?
        let serverProfile: ServerProfile
        let teamID: String?
        let teamEpoch: UInt64
    }
    let identity: Identity
    private let erasedCacheScopeID: String

    init(identity: Identity) {
        self.identity = identity
        erasedCacheScopeID = OfflineStore.scopeId(userId: identity.accountID,
            apiBaseURL: identity.serverProfile.apiBaseURL)
    }

    init(fence: UserTasksAccountFence) {
        self.init(identity: Identity(accountID: fence.accountID, cacheGeneration: fence.scope,
            activeCacheScopeID: OfflineStore.shared.activeScopeId, serverProfile: fence.serverProfile,
            teamID: fence.teamID, teamEpoch: fence.widgetTeamEpoch))
    }

    init(fence: TeamWorkspaceFence) {
        self.init(identity: Identity(accountID: fence.accountID, cacheGeneration: fence.scope,
            activeCacheScopeID: OfflineStore.shared.activeScopeId, serverProfile: fence.server,
            teamID: TeamWorkspaceContext.shared.teamID, teamEpoch: TeamWorkspaceContext.shared.contextEpoch))
    }

    // A deleted account cannot reliably make another authenticated request.
    // Compare captured local ownership synchronously before any cleanup/logout.
    @discardableResult
    func eraseConfirmed(currentAccountID: String?, registry: BillingUsageDraftAudioRegistry = .shared) -> Bool {
        guard let currentAccountID else { return false }
        let current = Identity(accountID: currentAccountID, cacheGeneration: OfflineStore.shared.scopeGeneration,
            activeCacheScopeID: OfflineStore.shared.activeScopeId, serverProfile: ServerProfile.current(),
            teamID: TeamWorkspaceContext.shared.teamID, teamEpoch: TeamWorkspaceContext.shared.contextEpoch)
        return eraseConfirmed(current: current, registry: registry)
    }

    @discardableResult
    func eraseConfirmed(current: Identity, registry: BillingUsageDraftAudioRegistry) -> Bool {
        guard current == identity,
              identity.activeCacheScopeID == nil || identity.activeCacheScopeID == erasedCacheScopeID else { return false }
        registry.eraseCacheScope(erasedCacheScopeID)
        return true
    }
}
