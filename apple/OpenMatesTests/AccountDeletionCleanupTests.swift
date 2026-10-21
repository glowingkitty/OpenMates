// Synthetic ownership and private preferences only. No account/server mutation.
import XCTest
@testable import OpenMates

@MainActor
final class AccountDeletionCleanupTests: XCTestCase {
    private var suite: String!
    private var defaults: UserDefaults!
    private let chatID = "00000000-0000-0000-0000-000000000385"

    override func setUpWithError() throws {
        suite = "org.openmates.tests.account-deletion.\(UUID().uuidString)"
        defaults = try XCTUnwrap(UserDefaults(suiteName: suite))
    }
    override func tearDownWithError() throws { defaults.removePersistentDomain(forName: suite) }

    private func identity(_ fence: UserTasksAccountFence) -> AccountDeletionCleanup.Identity {
        .init(accountID: fence.accountID, cacheGeneration: fence.scope,
            activeCacheScopeID: OfflineStore.scopeId(userId: fence.accountID, apiBaseURL: fence.serverProfile.apiBaseURL),
            serverProfile: fence.serverProfile, teamID: fence.teamID, teamEpoch: fence.widgetTeamEpoch)
    }
    private func mark(_ fence: UserTasksAccountFence, registry: BillingUsageDraftAudioRegistry) async throws {
        let allocation = try XCTUnwrap(BillingUsageDraftAudioRegistry.ConfirmedPreallocation(
            draftChatID: chatID, recordingChatID: chatID, isNewChatComposer: true,
            hasAcceptedUserMessage: false, teamID: fence.teamID))
        _ = try await registry.mark(allocation, fence: fence)
    }

    // contract-test: supporting surface=gui.apple assertions=billing.access.authenticated-first-party,auth.session.isolation
    func testConfirmedDeletionErasesCapturedOwnerAndRetainsOtherAccountMarkers() async throws {
        let a = UserTasksAccountFence(accountID: "synthetic-deleted-owner")
        let b = UserTasksAccountFence(accountID: "synthetic-other-owner")
        let registry = BillingUsageDraftAudioRegistry(defaults: defaults, validate: { _ in })
        try await mark(a, registry: registry); try await mark(b, registry: registry)
        let captured = identity(a)
        XCTAssertTrue(AccountDeletionCleanup(identity: captured).eraseConfirmed(current: captured, registry: registry))
        let removed = try await registry.contains(chatID: chatID, fence: a)
        let retained = try await registry.contains(chatID: chatID, fence: b)
        XCTAssertFalse(removed); XCTAssertTrue(retained)
    }

    // contract-test: supporting surface=gui.apple assertions=billing.access.authenticated-first-party,auth.session.isolation
    func testLateDeletionResultCannotEraseOrLogoutReplacementAccount() async throws {
        let a = UserTasksAccountFence(accountID: "synthetic-original-owner")
        let b = UserTasksAccountFence(accountID: "synthetic-replacement-owner")
        let registry = BillingUsageDraftAudioRegistry(defaults: defaults, validate: { _ in })
        try await mark(a, registry: registry); try await mark(b, registry: registry)
        let cleanup = AccountDeletionCleanup(identity: identity(a))
        var logoutCalled = false
        if cleanup.eraseConfirmed(current: identity(b), registry: registry) { logoutCalled = true }
        XCTAssertFalse(logoutCalled)
        let originalRetained = try await registry.contains(chatID: chatID, fence: a)
        let replacementRetained = try await registry.contains(chatID: chatID, fence: b)
        XCTAssertTrue(originalRetained); XCTAssertTrue(replacementRetained)
    }

    // contract-test: supporting surface=gui.apple assertions=billing.access.authenticated-first-party,auth.session.isolation
    func testGenerationServerCacheAndTeamChangesRetainCapturedMarkers() async throws {
        let owner = UserTasksAccountFence(accountID: "synthetic-original-owner")
        let registry = BillingUsageDraftAudioRegistry(defaults: defaults, validate: { _ in })
        try await mark(owner, registry: registry)
        let captured = identity(owner)
        let cleanup = AccountDeletionCleanup(identity: captured)
        let changed = [
            AccountDeletionCleanup.Identity(accountID: captured.accountID, cacheGeneration: UUID(), activeCacheScopeID: captured.activeCacheScopeID, serverProfile: captured.serverProfile, teamID: captured.teamID, teamEpoch: captured.teamEpoch),
            .init(accountID: captured.accountID, cacheGeneration: captured.cacheGeneration, activeCacheScopeID: "replacement-cache", serverProfile: captured.serverProfile, teamID: captured.teamID, teamEpoch: captured.teamEpoch),
            .init(accountID: captured.accountID, cacheGeneration: captured.cacheGeneration, activeCacheScopeID: captured.activeCacheScopeID, serverProfile: captured.serverProfile == .production ? .development : .production, teamID: captured.teamID, teamEpoch: captured.teamEpoch),
            .init(accountID: captured.accountID, cacheGeneration: captured.cacheGeneration, activeCacheScopeID: captured.activeCacheScopeID, serverProfile: captured.serverProfile, teamID: "replacement-team", teamEpoch: captured.teamEpoch),
            .init(accountID: captured.accountID, cacheGeneration: captured.cacheGeneration, activeCacheScopeID: captured.activeCacheScopeID, serverProfile: captured.serverProfile, teamID: captured.teamID, teamEpoch: captured.teamEpoch &+ 1)
        ]
        for current in changed { XCTAssertFalse(cleanup.eraseConfirmed(current: current, registry: registry)) }
        let retained = try await registry.contains(chatID: chatID, fence: owner)
        XCTAssertTrue(retained)
    }
}
