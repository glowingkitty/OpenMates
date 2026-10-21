import CryptoKit
import Combine
import XCTest
@testable import OpenMates

@MainActor
final class ProjectsWorkspaceTests: XCTestCase {
    // contract-test: supporting surface=gui.apple assertions=projects.access.explicit-context,projects.focus.inferred-consent
    func testRequestContextPreparationReusesFreshFocusWithoutPendingConsent() async throws {
        let store = PendingProjectFocusStore()
        var focusReads = 0
        let first = Data(#"{"focus":null}"#.utf8)
        let prepared = try await NativeProjectAuthoringClient.prepareRequestContext(
            acceptedPlan: { nil }, personalRules: { Data("[]".utf8) },
            currentFocus: { focusReads += 1; return first },
            clearInactiveFocus: { _ in store.clearAfterNoActiveBase(chatID: "chat") },
            confirmPending: { try await store.confirmBeforeContext(chatID: "chat") })
        XCTAssertEqual(focusReads, 1, "An ordinary send needs one fresh metadata read before any Project bodies")
        XCTAssertEqual(prepared.currentFocus, first)
        XCTAssertNil(prepared.acceptedPlan)
    }

    // contract-test: supporting surface=gui.apple assertions=projects.access.explicit-context,projects.focus.inferred-consent,focus-modes.countdown
    func testRequestContextPreparationRefreshesBindingAfterPendingActivation() async throws {
        let store = PendingProjectFocusStore(), scope = UUID()
        let projectID = "11111111-1111-4111-8111-111111111111"
        let embedID = UUID().uuidString.lowercased()
        var activated = false, focusReads = 0
        store.configure(scope: scope, complete: { record in
            try store.beginCommit(record)
            activated = true
        }, reject: { _ in XCTFail("Accepted pending focus must not be rejected") })
        defer { store.reset() }
        store.ingest(fields: ["chat_id": "chat", "embed_id": embedID,
            "focus_id": "project-" + projectID, "expires_at": Date().timeIntervalSince1970 - 1], scope: scope)
        let previous = Data(#"{"focus":null}"#.utf8)
        let current = Data(("{\"focus\":{\"active\":true,\"project_id\":\"" + projectID + "\"}}").utf8)
        let prepared = try await NativeProjectAuthoringClient.prepareRequestContext(
            acceptedPlan: { nil }, personalRules: { Data("[]".utf8) },
            currentFocus: {
                focusReads += 1
                if focusReads == 1 { return previous }
                XCTAssertTrue(activated, "A second read must follow actual accepted activation")
                XCTAssertEqual(store.entry(chatID: "chat", embedID: embedID)?.status, .activated)
                return current
            }, clearInactiveFocus: { _ in store.clearAfterNoActiveBase(chatID: "chat") },
            confirmPending: { try await store.confirmBeforeContext(chatID: "chat") })
        XCTAssertEqual(focusReads, 2)
        XCTAssertEqual(prepared.currentFocus, current, "Pre-activation authority cannot supply the Project context")
    }

    // contract-test: supporting surface=gui.apple assertions=projects.access.explicit-context,chats.direction.reviewed-correction
    func testRequestContextPreparationStartsIndependentReadsBeforeEitherCompletes() async throws {
        let planStarted = expectation(description: "Plan read started")
        let focusStarted = expectation(description: "Focus read started")
        let rulesPrepared = expectation(description: "Local rules prepared")
        var planContinuation: CheckedContinuation<Data?, Never>?
        var focusContinuation: CheckedContinuation<Data, Never>?
        var released = false
        let plan = Data(#"{"summary":"Approved goal"}"#.utf8)
        let focus = Data(#"{"focus":null}"#.utf8)
        let operation = Task {
            try await NativeProjectAuthoringClient.prepareRequestContext(
                acceptedPlan: {
                    planStarted.fulfill()
                    if released { return plan }
                    return await withCheckedContinuation { planContinuation = $0 }
                }, personalRules: { rulesPrepared.fulfill(); return Data("[]".utf8) },
                currentFocus: {
                    focusStarted.fulfill()
                    if released { return focus }
                    return await withCheckedContinuation { focusContinuation = $0 }
                }, clearInactiveFocus: { _ in }, confirmPending: { false })
        }
        await fulfillment(of: [planStarted, focusStarted, rulesPrepared], timeout: 2)
        released = true
        planContinuation?.resume(returning: plan)
        focusContinuation?.resume(returning: focus)
        let prepared = try await operation.value
        XCTAssertEqual(prepared.acceptedPlan, plan)
        XCTAssertEqual(prepared.currentFocus, focus)
        XCTAssertEqual(prepared.personalRules, Data("[]".utf8))
    }

    // contract-test: supporting surface=gui.apple assertions=projects.focus.inferred-consent,focus-modes.countdown
    func testRequestContextPreparationRejectsCancelledConsentWithoutRefreshing() async throws {
        let store = PendingProjectFocusStore(), scope = UUID()
        let embedID = UUID().uuidString.lowercased()
        var focusReads = 0
        store.configure(scope: scope, complete: { _ in XCTFail("Cancelled focus cannot activate") }, reject: { _ in })
        defer { store.reset() }
        store.ingest(fields: ["chat_id": "chat", "embed_id": embedID,
            "focus_id": "project-11111111-1111-4111-8111-111111111111",
            "expires_at": Date().timeIntervalSince1970 + 60], scope: scope)
        store.cancel(chatID: "chat", embedID: embedID)
        do {
            _ = try await NativeProjectAuthoringClient.prepareRequestContext(
                acceptedPlan: { nil }, personalRules: { Data("[]".utf8) },
                currentFocus: { focusReads += 1; return Data(#"{"focus":{"active":true}}"#.utf8) },
                clearInactiveFocus: { _ in }, confirmPending: { try await store.confirmBeforeContext(chatID: "chat") })
            XCTFail("Cancelled consent cannot return a context snapshot")
        } catch {}
        XCTAssertEqual(focusReads, 1, "Rejected consent must stop before any post-confirmation read")
    }

    // contract-test: supporting surface=gui.apple assertions=apple-workspaces.maintenance,apple-workspaces.isolation
    func testAllContextMaintenanceResumeSkipsCompletedPersonalAndTeamInventories() throws {
        var scheduler = NativeWorkspaceAllContextMaintenancePolicy()
        let personal = maintenanceScope()
        let team = maintenanceScope(teamID: "team-a")
        let cohorts = [maintenanceCohort(personal), maintenanceCohort(team)]
        scheduler.update(cohorts)
        var admitted: [NativeWorkspaceOfflineScope] = []
        while let ticket = scheduler.beginNext(now: 100) {
            admitted.append(ticket.scope)
            for name in scheduler.namespaces(ticket: ticket) {
                scheduler.beganNamespace(name, ticket: ticket)
                scheduler.completedNamespace(name, ticket: ticket)
            }
            scheduler.finish(ticket, now: 100, successful: true)
        }
        XCTAssertEqual(admitted, [personal, team])
        scheduler.update(cohorts)
        XCTAssertNil(scheduler.beginNext(now: 102), "Settled chat navigation must issue zero inventory reads during cooldown")
        XCTAssertEqual(try XCTUnwrap(scheduler.delay(now: 102)), 298)
        XCTAssertNotNil(scheduler.beginNext(now: 400))
    }

    // contract-test: supporting surface=gui.apple assertions=apple-workspaces.maintenance,apple-workspaces.isolation
    func testAllContextMaintenancePausePreservesProgressAndRotatesTeamsAndNamespaces() throws {
        var scheduler = NativeWorkspaceAllContextMaintenancePolicy()
        let personal = maintenanceScope()
        let team = maintenanceScope(teamID: "team-a")
        let cohorts = [maintenanceCohort(personal), maintenanceCohort(team)]
        scheduler.update(cohorts)
        let first = try XCTUnwrap(scheduler.beginNext(now: 100))
        scheduler.beganNamespace("chat-metadata", ticket: first)
        scheduler.completedNamespace("chat-metadata", ticket: first)
        scheduler.beganNamespace("workflows", ticket: first)
        scheduler.finish(first, now: 101, successful: false, interrupted: true)
        scheduler.update(cohorts)
        let second = try XCTUnwrap(scheduler.beginNext(now: 102))
        XCTAssertEqual(second.scope, team, "Repeated pauses must not starve Teams behind personal inventories")
        scheduler.beganNamespace("chat-metadata", ticket: second)
        scheduler.finish(second, now: 103, successful: false, interrupted: true)
        let resumed = try XCTUnwrap(scheduler.beginNext(now: 104))
        XCTAssertEqual(resumed.scope, personal)
        XCTAssertEqual(scheduler.namespaces(ticket: resumed), ["user-tasks", "user-plans", "projects", "workflows"])
        scheduler.finish(resumed, now: 105, successful: false, interrupted: true)
        let resumedTeam = try XCTUnwrap(scheduler.beginNext(now: 106))
        XCTAssertEqual(scheduler.namespaces(ticket: resumedTeam).first, "workflows")
        // Late cancellation callbacks from a superseded task cannot rewind progress.
        scheduler.beganNamespace("projects", ticket: second)
        XCTAssertEqual(scheduler.namespaces(ticket: resumedTeam).first, "workflows")
    }

    // contract-test: supporting surface=gui.apple assertions=apple-workspaces.maintenance,apple-workspaces.isolation
    func testAllContextMaintenanceForceCoalescesAndRetainsFailureBackoff() throws {
        var scheduler = NativeWorkspaceAllContextMaintenancePolicy()
        let personal = maintenanceScope()
        let cohorts = [maintenanceCohort(personal)]
        scheduler.update(cohorts)
        let first = try XCTUnwrap(scheduler.beginNext(now: 100))
        scheduler.completedNamespace("chat-metadata", ticket: first)
        scheduler.update(cohorts, force: true)
        scheduler.update(cohorts, force: true)
        XCTAssertTrue(scheduler.namespaces(ticket: first).isEmpty, "Invalidated tickets cannot publish completion")
        scheduler.finish(first, now: 101, successful: false, interrupted: true)
        XCTAssertNil(scheduler.beginNext(now: 129))
        let replacement = try XCTUnwrap(scheduler.beginNext(now: 130))
        scheduler.completedNamespace("chat-metadata", ticket: replacement)
        scheduler.finish(first, now: 131, successful: true)
        XCTAssertFalse(scheduler.namespaces(ticket: replacement).contains("chat-metadata"))
        scheduler.finish(replacement, now: 131, successful: false)
        XCTAssertNil(scheduler.beginNext(now: 160))
        let retry = try XCTUnwrap(scheduler.beginNext(now: 161))
        XCTAssertFalse(scheduler.namespaces(ticket: retry).contains("chat-metadata"), "A failed namespace must not repeat successful inventories")
    }

    // contract-test: supporting surface=gui.apple assertions=apple-workspaces.maintenance,apple-workspaces.isolation
    func testAllContextMaintenanceFailedForcedReplacementUsesRetryBackoffAfterPriorSuccess() throws {
        var scheduler = NativeWorkspaceAllContextMaintenancePolicy()
        let scope = maintenanceScope()
        let cohorts = [maintenanceCohort(scope)]
        scheduler.update(cohorts)
        let settled = try XCTUnwrap(scheduler.beginNext(now: 100))
        for name in scheduler.namespaces(ticket: settled) { scheduler.completedNamespace(name, ticket: settled) }
        scheduler.finish(settled, now: 100, successful: true)
        scheduler.update(cohorts, force: true)
        let forced = try XCTUnwrap(scheduler.beginNext(now: 130))
        scheduler.completedNamespace("chat-metadata", ticket: forced)
        scheduler.finish(forced, now: 131, successful: false)
        XCTAssertEqual(try XCTUnwrap(scheduler.delay(now: 131)), 30)
        XCTAssertNil(scheduler.beginNext(now: 160))
        let retry = try XCTUnwrap(scheduler.beginNext(now: 161))
        XCTAssertFalse(scheduler.namespaces(ticket: retry).contains("chat-metadata"))
        for name in scheduler.namespaces(ticket: retry) { scheduler.completedNamespace(name, ticket: retry) }
        scheduler.finish(retry, now: 162, successful: true)
        XCTAssertEqual(try XCTUnwrap(scheduler.delay(now: 163)), 299,
                       "A completed replacement must restore the full success cooldown")
    }

    // contract-test: supporting surface=gui.apple assertions=apple-workspaces.maintenance,apple-workspaces.isolation
    func testAllContextMaintenancePausedForcedReplacementResumesAfterPriorSuccess() throws {
        var scheduler = NativeWorkspaceAllContextMaintenancePolicy()
        let scope = maintenanceScope()
        let cohorts = [maintenanceCohort(scope)]
        scheduler.update(cohorts)
        let settled = try XCTUnwrap(scheduler.beginNext(now: 100))
        for name in scheduler.namespaces(ticket: settled) { scheduler.completedNamespace(name, ticket: settled) }
        scheduler.finish(settled, now: 100, successful: true)
        scheduler.update(cohorts, force: true)
        let forced = try XCTUnwrap(scheduler.beginNext(now: 130))
        scheduler.completedNamespace("chat-metadata", ticket: forced)
        scheduler.finish(forced, now: 131, successful: false, interrupted: true)
        scheduler.update(cohorts)
        let resumed = try XCTUnwrap(scheduler.beginNext(now: 132))
        XCTAssertFalse(scheduler.namespaces(ticket: resumed).contains("chat-metadata"))
        scheduler.update(cohorts, force: true)
        scheduler.update(cohorts, force: true)
        scheduler.finish(resumed, now: 133, successful: false, interrupted: true)
        XCTAssertNil(scheduler.beginNext(now: 161), "Socket flaps must retain the 30-second forced admission bound")
        XCTAssertNotNil(scheduler.beginNext(now: 162))
    }

    // contract-test: supporting surface=gui.apple assertions=apple-workspaces.maintenance,apple-workspaces.isolation
    func testAllContextMaintenanceMembershipChangesOnlyInvalidateAffectedCohort() throws {
        var scheduler = NativeWorkspaceAllContextMaintenancePolicy()
        let personal = maintenanceScope()
        let team = maintenanceScope(teamID: "team-a")
        scheduler.update([maintenanceCohort(personal), maintenanceCohort(team)])
        for _ in 0..<2 {
            let ticket = try XCTUnwrap(scheduler.beginNext(now: 100))
            for name in scheduler.namespaces(ticket: ticket) { scheduler.completedNamespace(name, ticket: ticket) }
            scheduler.finish(ticket, now: 100, successful: true)
        }
        scheduler.update([maintenanceCohort(personal), maintenanceCohort(team, revision: "changed-role-and-key")])
        XCTAssertNil(scheduler.beginNext(now: 120))
        let changed = try XCTUnwrap(scheduler.beginNext(now: 130))
        XCTAssertEqual(changed.scope, team)
        XCTAssertEqual(scheduler.namespaces(ticket: changed).count, 8)
        scheduler.update([maintenanceCohort(personal)])
        scheduler.completedNamespace("projects", ticket: changed)
        scheduler.finish(changed, now: 131, successful: true)
        XCTAssertEqual(scheduler.count, 1, "Removed membership progress must be discarded rather than reused")
        XCTAssertNil(scheduler.beginNext(now: 131))
        let added = maintenanceScope(teamID: "team-b")
        scheduler.update([maintenanceCohort(personal), maintenanceCohort(added)])
        XCTAssertEqual(scheduler.beginNext(now: 132)?.scope, added)
    }

    // contract-test: supporting surface=gui.apple assertions=apple-workspaces.maintenance,apple-workspaces.isolation
    func testAllContextMaintenanceDoesNotReuseProgressAcrossAccountServerOrGeneration() throws {
        for changed in [maintenanceScope(accountID: "other-owner"), maintenanceScope(server: "https://other.example"),
                        maintenanceScope(generation: UUID())] {
            var scheduler = NativeWorkspaceAllContextMaintenancePolicy()
            let original = maintenanceScope()
            scheduler.update([maintenanceCohort(original)])
            let first = try XCTUnwrap(scheduler.beginNext(now: 100))
            for name in scheduler.namespaces(ticket: first) { scheduler.completedNamespace(name, ticket: first) }
            scheduler.finish(first, now: 100, successful: true)
            scheduler.update([maintenanceCohort(changed)])
            let replacement = try XCTUnwrap(scheduler.beginNext(now: 101))
            XCTAssertEqual(replacement.scope, changed)
            XCTAssertEqual(scheduler.namespaces(ticket: replacement).count, 5)
            scheduler.completedNamespace("projects", ticket: first)
            XCTAssertTrue(scheduler.namespaces(ticket: replacement).contains("projects"))
        }
    }

    // contract-test: supporting surface=gui.apple assertions=apple-workspaces.maintenance,apple-workspaces.isolation
    func testAllContextMaintenanceAuthoritativeMembershipChangeRejectsResumedTicket() throws {
        var scheduler = NativeWorkspaceAllContextMaintenancePolicy()
        let team = maintenanceScope(teamID: "team-a")
        scheduler.update([maintenanceCohort(team)])
        let initial = try XCTUnwrap(scheduler.beginNext(now: 100))
        scheduler.completedNamespace("team-management", ticket: initial)
        scheduler.finish(initial, now: 101, successful: false, interrupted: true)
        let resumed = try XCTUnwrap(scheduler.beginNext(now: 102))
        XCTAssertFalse(scheduler.namespaces(ticket: resumed).contains("team-management"))
        scheduler.revalidate(scope: team, membershipRevision: "authoritative-viewer-new-key")
        XCTAssertFalse(scheduler.isCurrent(resumed), "A stale roster cannot authorize reuse of completed Team namespaces")
        scheduler.completedNamespace("projects", ticket: resumed)
        scheduler.finish(resumed, now: 103, successful: false, interrupted: true)
        XCTAssertNil(scheduler.beginNext(now: 131))
        let authorized = try XCTUnwrap(scheduler.beginNext(now: 132))
        XCTAssertEqual(scheduler.namespaces(ticket: authorized).count, 8)
        scheduler.update([maintenanceCohort(team)])
        scheduler.revalidate(scope: team, membershipRevision: "authoritative-viewer-new-key")
        XCTAssertTrue(scheduler.isCurrent(authorized), "An unchanged cached roster must not repeatedly invalidate newer authoritative membership")
    }

    // contract-test: supporting surface=gui.apple assertions=apple-workspaces.maintenance,apple-workspaces.isolation
    func testAllContextMaintenanceFinalMembershipChangePreservesPreviousCiphertext() async throws {
        let directory = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        defer { try? FileManager.default.removeItem(at: directory) }
        let accountID = "retention-owner"
        let server = ServerProfile.custom(domain: "retention.example.invalid")
        let generation = UUID()
        let fence = TeamWorkspaceFence(accountID: accountID, environment: .init(
            currentAccountID: { accountID }, scopeGeneration: { generation }, serverProfile: { server }))
        let key = SymmetricKey(size: .bits256)
        let team = TeamWorkspaceTeam(id: "team-a", name: "Synthetic", description: "", role: .member,
            status: "active", profileImageMetadata: .generated, zeroBalance: 0, createdAt: 1, updatedAt: 1, key: key)
        let rotatedTeam = TeamWorkspaceTeam(id: team.id, name: team.name, description: "", role: team.role,
            status: team.status, profileImageMetadata: .generated, zeroBalance: 0, createdAt: 1, updatedAt: 2,
            key: SymmetricKey(size: .bits256))
        let scope = NativeWorkspaceOfflineScope(accountID: accountID, server: server.apiBaseURL.absoluteString,
            teamID: team.id, accountGeneration: generation, teamEpoch: TeamWorkspaceContext.shared.contextEpoch)
        let schedulerScope = NativeWorkspaceOfflineScope(accountID: accountID, server: scope.server,
            teamID: team.id, accountGeneration: generation, teamEpoch: 0)
        let cache = NativeWorkspaceOfflineCache(directory: directory)
        await cache.configure(scope: scope, masterKey: key)
        let path = UserTasksPaths.scoped("/v1/workflows", teamID: team.id)
        let previous = Data("previous-complete-inventory".utf8)
        let revision = try await cache.beginRefresh(namespace: "workflows", scope: scope)
        try await cache.commit(namespace: "workflows", responses: [path: previous], scope: scope, revision: revision)
        let files = FileManager.default.enumerator(at: directory, includingPropertiesForKeys: nil)!
            .allObjects.compactMap { $0 as? URL }.filter { $0.pathExtension == "aesgcm" }
        let ciphertextFile = try XCTUnwrap(files.first)
        let previousCiphertext = try Data(contentsOf: ciphertextFile)
        var scheduler = NativeWorkspaceAllContextMaintenancePolicy()
        scheduler.update([.init(scope: schedulerScope, membershipRevision: "original-key")])
        let ticket = try XCTUnwrap(scheduler.beginNext(now: 100))
        var membershipReads = 0
        do {
            try await TeamWorkspaceOfflineRetention.retain(fence: fence, teams: [team], removedIDs: [],
                masterKey: key, cache: cache, transport: { route, _ in
                    XCTAssertEqual(route, path)
                    return Data("{\"workflows\":[]}".utf8)
                }, membership: { _, _ in
                    membershipReads += 1
                    if membershipReads == 3 {
                        scheduler.revalidate(scope: schedulerScope, membershipRevision: "rotated-key")
                        return rotatedTeam
                    }
                    return team
                }, isCurrent: { scheduler.isCurrent(ticket) }, contextIDs: [team.id], namespaces: ["workflows"])
            XCTFail("The final authoritative membership change must reject the collected inventory")
        } catch is CancellationError { }
        XCTAssertEqual(membershipReads, 3)
        XCTAssertEqual(try Data(contentsOf: ciphertextFile), previousCiphertext,
                       "An invalidated ticket must not replace the previous encrypted snapshot")
        let reopened = NativeWorkspaceOfflineCache(directory: directory)
        await reopened.configure(scope: scope, masterKey: key)
        let restored = try await reopened.read(namespace: "workflows", path: path, scope: scope)
        XCTAssertEqual(restored, previous)
    }

    private func maintenanceScope(teamID: String? = nil, accountID: String = "fixture-owner",
                                  server: String = "https://fixture.example",
                                  generation: UUID = UUID(uuidString: "11111111-1111-1111-1111-111111111111")!) -> NativeWorkspaceOfflineScope {
        .init(accountID: accountID, server: server, teamID: teamID, accountGeneration: generation, teamEpoch: 0)
    }

    private func maintenanceCohort(_ scope: NativeWorkspaceOfflineScope, revision: String = "readable-v1") -> NativeWorkspaceAllContextMaintenancePolicy.Cohort {
        .init(scope: scope, membershipRevision: revision)
    }

    // contract-test: supporting surface=gui.apple assertions=chat-navigation.projects.nested-readable,projects.access.explicit-context
    func testNavigationDecryptsOnlyFoldersAndChatMembership() async throws {
        let service = ProjectsWorkspaceService()
        let project = makeProject(id: "navigation", name: "Navigation")
        let folderName = try await CryptoManager.shared.encryptWithMasterKey("Nested", masterKey: project.key)
        let target = try await CryptoManager.shared.encryptWithMasterKey("chat", masterKey: project.key)
        let folders = [ProjectWorkspaceFolderRecord(folderId: "folder", encryptedName: folderName,
            hashedParentFolderId: nil, createdAt: 0, position: 0)]
        let records = [
            ProjectWorkspaceItemRecord(projectItemId: "chat-link", itemType: "chat", targetIdEncrypted: target,
                encryptedDisplayName: "invalid-unused-ciphertext", encryptedMetadata: "invalid-unused-ciphertext",
                hashedFolderId: ChatSidebarProject.hash("folder"), createdAt: 0, position: 0),
            ProjectWorkspaceItemRecord(projectItemId: "file", itemType: "embed", targetIdEncrypted: "invalid-unused-ciphertext",
                encryptedDisplayName: "invalid-unused-ciphertext", encryptedMetadata: "invalid-unused-ciphertext",
                hashedFolderId: nil, createdAt: 0, position: 0)
        ]
        let contents = try await service.openChatNavigationContents(folders: folders, items: records, project: project)
        XCTAssertEqual(contents.folders.map(\.name), ["Nested"])
        XCTAssertEqual(contents.items.map(\.targetID), ["chat"])
        XCTAssertTrue(contents.sources.isEmpty)
        XCTAssertEqual(ChatSidebarProject(project: project, contents: contents).chatIDs(in: "folder"), ["chat"])
    }

    // contract-test: supporting surface=gui.apple assertions=chat-navigation.projects.nested-readable,projects.access.explicit-context
    func testNavigationReadsMembershipIndependentlyAndPreservesHealthyProjectsAfterFailure() async {
        let service = ProjectsWorkspaceMockService()
        let first = makeProject(id: "first", name: "First")
        let healthy = makeProject(id: "healthy", name: "Healthy")
        service.listResult = [first, healthy]
        service.contentsByProject[first.id] = .init(folders: [], items: [
            .init(id: "first-link", kind: "chat", targetID: "first-chat", name: "", metadata: [:], folderHash: nil, position: 0, createdAt: 0)
        ], sources: [])
        service.contentsByProject[healthy.id] = .init(folders: [], items: [
            .init(id: "healthy-link", kind: "chat", targetID: "healthy-chat", name: "", metadata: [:], folderHash: nil, position: 0, createdAt: 0)
        ], sources: [])
        service.failsWorkspaceContents = true
        let store = ProjectsWorkspaceStore(service: service, validateFence: { _ in })
        await store.refreshChatNavigation(accountID: "owner", teamID: nil)
        XCTAssertEqual(service.workspaceContentsReads, 0, "Navigation must not invoke full contents or source reads")
        XCTAssertEqual(store.chatNavigationProjects.map(\.id), [first.id, healthy.id])
        service.navigationFailures = [first.id]
        await store.refreshChatNavigation(accountID: "owner", teamID: nil)
        XCTAssertEqual(store.chatNavigationProjects.first?.chatIDs(in: nil), ["first-chat"], "Retain scoped membership on a transient read failure")
        XCTAssertEqual(store.chatNavigationProjects.last?.chatIDs(in: nil), ["healthy-chat"])
        XCTAssertNil(store.errorMessage, "A failed membership read must not become a generic workspace action error")
        store.reset(accountId: "other-owner")
        await store.refreshChatNavigation(accountID: "other-owner", teamID: nil)
        XCTAssertEqual(store.chatNavigationProjects.map(\.id), [healthy.id], "Previous account membership must not survive reset")
    }

    // contract-test: supporting surface=gui.apple assertions=projects.access.explicit-context,projects.files.no-server-decryption-authority
    func testProjectRequestFencePreservesCanonicalServerProfileForScopedTransport() {
        let currentProfile = ServerProfile.current()
        let fence = ProjectsWorkspaceFence(accountID: "fixture-project-owner")
        XCTAssertEqual(fence.serverProfile, currentProfile,
                       "A captured Project request must retain the canonical hosted or self-hosted profile")
        XCTAssertTrue(APIClient.isUploadContextCurrent(
            expectedAccountID: fence.accountID, currentAccountID: fence.accountID,
            expectedScope: fence.scope, currentScope: fence.scope,
            serverProfile: fence.serverProfile, currentProfile: currentProfile),
            "The real scoped-request preflight must accept an unchanged account, scope and server")
        XCTAssertFalse(APIClient.isUploadContextCurrent(
            expectedAccountID: fence.accountID, currentAccountID: "different-fixture-owner",
            expectedScope: fence.scope, currentScope: fence.scope,
            serverProfile: fence.serverProfile, currentProfile: currentProfile))
        XCTAssertFalse(APIClient.isUploadContextCurrent(
            expectedAccountID: fence.accountID, currentAccountID: fence.accountID,
            expectedScope: fence.scope, currentScope: UUID(),
            serverProfile: fence.serverProfile, currentProfile: currentProfile))
        XCTAssertFalse(APIClient.isUploadContextCurrent(
            expectedAccountID: fence.accountID, currentAccountID: fence.accountID,
            expectedScope: fence.scope, currentScope: fence.scope,
            serverProfile: fence.serverProfile, currentProfile: .custom(domain: "different-project-fixture.example")))
    }

    // contract-test: supporting surface=gui.apple assertions=focus-modes.project-authoring-persistence,focus-modes.project-authoring-click
    func testFocusSavePreapprovalReceiptDenialOnlyAcceptsTheTypedApprovalError() {
        let approvalRequired = APIError.httpError(status: 409, message: "PROJECT_WRITE_APPROVAL_REQUIRED")
        XCTAssertTrue(NativeProjectAuthoringClient.isPreapprovalReceiptDenial(approvalRequired, writeMode: .alwaysAsk))
        XCTAssertFalse(NativeProjectAuthoringClient.isPreapprovalReceiptDenial(approvalRequired, writeMode: .applyAndShow))
        XCTAssertFalse(NativeProjectAuthoringClient.isPreapprovalReceiptDenial(
            APIError.httpError(status: 409, message: "PROJECT_REVISION_CONFLICT"), writeMode: .alwaysAsk))
        XCTAssertFalse(NativeProjectAuthoringClient.isPreapprovalReceiptDenial(
            APIError.httpError(status: 403, message: "PROJECT_WRITE_APPROVAL_REQUIRED"), writeMode: .alwaysAsk))
        XCTAssertFalse(NativeProjectAuthoringClient.isPreapprovalReceiptDenial(
            ProjectsWorkspaceError.invalidContext, writeMode: .alwaysAsk))
    }

    // contract-test: supporting surface=gui.apple assertions=projects.keys.client-wrapped,projects.access.explicit-context
    func testTeamProjectRecordDecodesWithoutPersonalKeyWrapper() throws {
        let decoder = JSONDecoder(); decoder.keyDecodingStrategy = .convertFromSnakeCase
        let bytes = Data(#"{"project_id":"team-project","encrypted_project_key":null,"encrypted_name":"ciphertext","created_at":1,"updated_at":1,"key_wrappers":[{"key_type":"team","hashed_team_id":"team-hash","team_key_epoch":1,"encrypted_project_key":"wrapped"}]}"#.utf8)
        let record = try decoder.decode(ProjectWorkspaceRecord.self, from: bytes)
        XCTAssertNil(record.encryptedProjectKey)
        XCTAssertEqual(record.keyWrappers?.first?.keyType, "team")
        XCTAssertEqual(record.keyWrappers?.first?.teamKeyEpoch, 1)
        let absent = Data(#"{"project_id":"team-project","encrypted_name":"ciphertext","created_at":1,"updated_at":1,"key_wrappers":[{"key_type":"team","hashed_team_id":"team-hash","team_key_epoch":1,"encrypted_project_key":"wrapped"}]}"#.utf8)
        XCTAssertNil(try decoder.decode(ProjectWorkspaceRecord.self, from: absent).encryptedProjectKey)
    }

    // contract-test: supporting surface=gui.apple assertions=chat-navigation.projects.organize,projects.links.openmates-only-encrypted
    func testChatMovePersistsAllDestinationsBeforeRemovingSourceLinks() async {
        let service = ProjectsWorkspaceMockService()
        let source = makeProject(id: "source", name: "Source"), destination = makeProject(id: "destination", name: "Destination")
        let chats = [DevHistoryWelcomeData.chat("chat-a", title: "A"), DevHistoryWelcomeData.chat("chat-b", title: "B")]
        service.listResult = [source, destination]
        service.contentsByProject["source"] = .init(folders: [], items: chats.map { chat in
            .init(id: "link-\(chat.id)", kind: "chat", targetID: chat.id, name: chat.displayTitle, metadata: [:], folderHash: nil, position: 0, createdAt: 0)
        }, sources: [])
        let store = ProjectsWorkspaceStore(service: service, validateFence: { _ in })
        await store.refreshChatNavigation(accountID: "owner", teamID: nil)
        await store.moveChats(chats, to: .init(projectID: "destination", folderID: nil))
        XCTAssertEqual(service.organizationReceipts, ["copy:destination:chat-a", "copy:destination:chat-b", "remove:source:chat-a", "remove:source:chat-b"])
        XCTAssertFalse(store.isOrganizingChats)
        service.organizationReceipts = []
        await store.moveChats(chats, to: .init(projectID: "destination", folderID: nil), removeOtherLinks: false)
        XCTAssertEqual(service.organizationReceipts, ["copy:destination:chat-a", "copy:destination:chat-b"], "Add must retain source associations")
        service.organizationReceipts = []; service.failsCopy = true
        await store.moveChats(chats, to: .init(projectID: "destination", folderID: nil))
        XCTAssertEqual(service.organizationReceipts, ["copy:destination:chat-a"])
        XCTAssertNotNil(store.chatOrganizationErrorMessage)
        XCTAssertNil(store.errorMessage, "Chat organization failures belong to their own surface")
    }

    // contract-test: supporting surface=gui.apple assertions=chat-navigation.projects.organize,projects.access.explicit-context
    func testOrganizationCreationStopsBeforeLinkingAfterAccountChanges() async {
        let service = ProjectsWorkspaceMockService()
        service.listResult = []
        service.suspendsOrganization = true
        let store = ProjectsWorkspaceStore(service: service, validateFence: { _ in })
        await store.refreshChatNavigation(accountID: "owner", teamID: nil)
        let creation = Task { await store.createChatOrganization(chats: [DevHistoryWelcomeData.chat("chat", title: "Chat")]) }
        for _ in 0..<100 where service.organizationContinuation == nil { await Task.yield() }
        XCTAssertNotNil(service.organizationContinuation)
        store.reset(accountId: "other-owner")
        service.organizationContinuation?.resume(returning: makeProject(id: "late", name: "Old account"))
        service.organizationContinuation = nil
        let result = await creation.value
        XCTAssertNil(result); XCTAssertTrue(service.organizationReceipts.isEmpty)
        XCTAssertTrue(store.chatNavigationProjects.isEmpty)
    }

    // contract-test: supporting surface=gui.apple assertions=chat-navigation.projects.nested-readable,chat-navigation.activity.global-running
    func testProjectFolderMembershipUsesImmediateChildrenAndRecursiveActivityWithoutWideningMissingFolders() {
        let project = makeProject(id: "project", name: "Project")
        let folders = [ProjectWorkspaceFolder(id: "parent", name: "Parent", parentHash: nil, position: 0, createdAt: 0),
                       ProjectWorkspaceFolder(id: "child", name: "Child", parentHash: ChatSidebarProject.hash("parent"), position: 0, createdAt: 0)]
        let items = [ProjectWorkspaceItem(id: "root", kind: "chat", targetID: "root-chat", name: "Root", metadata: [:], folderHash: nil, position: 0, createdAt: 0),
                     ProjectWorkspaceItem(id: "nested", kind: "chat", targetID: "nested-chat", name: "Nested", metadata: [:], folderHash: ChatSidebarProject.hash("child"), position: 0, createdAt: 0)]
        let navigation = ChatSidebarProject(project: project, contents: .init(folders: folders, items: items, sources: []))
        XCTAssertEqual(navigation.chatIDs(in: nil), ["root-chat"])
        XCTAssertTrue(navigation.chatIDs(in: "parent").isEmpty)
        XCTAssertEqual(navigation.chatIDs(in: "parent", recursively: true), ["nested-chat"])
        XCTAssertTrue(navigation.chatIDs(in: "missing", recursively: true).isEmpty)
        XCTAssertEqual(navigation.breadcrumbs("child").map(\.id), ["parent", "child"])
        XCTAssertNil(navigation.parentLocation(of: nil))
        XCTAssertEqual(navigation.parentLocation(of: "parent"), .init(projectID: "project", folderID: nil))
        XCTAssertEqual(navigation.parentLocation(of: "child"), .init(projectID: "project", folderID: "parent"))
    }

    // contract-test: supporting surface=gui.apple assertions=chat-navigation.projects.nested-readable,projects.access.explicit-context
    func testRegularProjectCreateAndRenameImmediatelyUpdateNavigationWithoutLosingMembership() async {
        let service = ProjectsWorkspaceMockService()
        let original = makeProject(id: "existing", name: "Original")
        var renamed = original; renamed.name = "Renamed"
        let created = makeProject(id: "created", name: "Created")
        service.listResult = [original]; service.updatedProjectResult = renamed; service.createdProjectResult = created
        service.contentsByProject[original.id] = .init(folders: [], items: [
            .init(id: "link", kind: "chat", targetID: "chat", name: "Chat", metadata: [:], folderHash: nil, position: 0, createdAt: 0)
        ], sources: [])
        let store = ProjectsWorkspaceStore(service: service, validateFence: { _ in })
        await store.refreshChatNavigation(accountID: "owner", teamID: nil)
        await store.selectProject(original.id)
        await store.updateSelectedProject(name: "Renamed")
        XCTAssertEqual(store.chatNavigationProjects.first?.project.name, "Renamed")
        XCTAssertEqual(store.chatNavigationProjects.first?.chatIDs(in: nil), ["chat"])
        await store.createProject(name: "Created", writeMode: .alwaysAsk)
        XCTAssertEqual(store.chatNavigationProjects.map(\.id), ["created", "existing"])
        XCTAssertTrue(store.chatNavigationProjects.first?.chatIDs(in: nil).isEmpty == true)
        XCTAssertEqual(store.selectedProjectID, "created")
    }

    // contract-test: supporting surface=gui.apple assertions=chat-navigation.projects.organize,projects.access.explicit-context
    func testDeletingProjectRemovesOrganizationIndexAndRestoresNormalChatEligibility() async {
        let service = ProjectsWorkspaceMockService()
        let project = makeProject(id: "organization", name: "Organization")
        service.listResult = [project]; service.allowsDelete = true
        service.contentsByProject[project.id] = .init(folders: [], items: [
            .init(id: "link", kind: "chat", targetID: "chat", name: "Chat", metadata: [:], folderHash: nil, position: 0, createdAt: 0)
        ], sources: [])
        let store = ProjectsWorkspaceStore(service: service, validateFence: { _ in })
        await store.refreshChatNavigation(accountID: "owner", teamID: nil)
        XCTAssertTrue(store.chatNavigationProjects.contains { $0.chatIDs(in: nil).contains("chat") })
        await store.selectProject(project.id)
        await store.deleteSelectedProject()
        XCTAssertTrue(store.chatNavigationProjects.isEmpty)
        XCTAssertNil(store.selectedProjectID)
        XCTAssertFalse(store.chatNavigationProjects.contains { $0.chatIDs(in: nil, recursively: true).contains("chat") }, "Root chat history must no longer hide the former association")
    }

    // contract-test: supporting surface=gui.apple assertions=chat-navigation.projects.organize,projects.access.explicit-context
    func testOrganizationEligibilityAndChatMetadataRoundTripKeepTeamAndRecipientFences() throws {
        let decoder = JSONDecoder(); decoder.keyDecodingStrategy = .convertFromSnakeCase
        let chat = try decoder.decode(Chat.self, from: Data(#"{"id":"chat","created_at":"2026-09-12T12:00:00Z","team_id":"team","is_shared_by_others":true}"#.utf8))
        XCTAssertEqual(chat.teamId, "team"); XCTAssertEqual(chat.isSharedByOthers, true)
        XCTAssertFalse(ChatProjectEligibility.canOrganize(chat, teamID: "team"))
        var owned = chat; owned.isSharedByOthers = false
        XCTAssertFalse(ChatProjectEligibility.canOrganize(owned, teamID: nil))
        XCTAssertTrue(ChatProjectEligibility.canOrganize(owned, teamID: "team"))
        let versions = ChatStore()
        versions.performWithoutPersistence {
            versions.upsertChat(owned)
            versions.advanceMessagesVersion(chatId: owned.id, to: 2)
        }
        let updated = try XCTUnwrap(versions.chat(for: owned.id))
        XCTAssertEqual(updated.teamId, "team"); XCTAssertEqual(updated.isSharedByOthers, false)
        let persisted = PersistedChat(from: updated).toChat()
        XCTAssertEqual(persisted.teamId, "team"); XCTAssertEqual(persisted.isSharedByOthers, false)
        let legacy = try decoder.decode(Chat.self, from: Data(#"{"id":"legacy","created_at":"2026-09-12T12:00:00Z"}"#.utf8))
        XCTAssertNil(legacy.teamId); XCTAssertNil(legacy.isSharedByOthers)
        let store = ChatStore(); let revision = store.metadataReadRevision
        store.performWithoutPersistence { store.removeChat("chat") }
        XCTAssertNotEqual(store.metadataReadRevision, revision, "A pending metadata read must not resurrect a removed chat")
    }

    // contract-test: supporting surface=gui.apple assertions=chat-navigation.activity.global-running
    func testActivityUsesExactRunIdentityAndAggregatesRootWithoutNotificationPreference() {
        let activity = NativeChatActivityStore(), scope = UUID()
        activity.configure(accountID: "synthetic", scope: scope, server: ServerProfile.current(), teamID: nil)
        activity.consume(type: "ai_task_initiated", fields: ["chat_id": "child", "task_id": "old"], scope: scope)
        activity.consume(type: "ai_task_initiated", fields: ["chat_id": "child", "task_id": "new"], scope: scope)
        activity.consume(type: "post_processing_completed", fields: ["chat_id": "child", "task_id": "old"], scope: scope)
        XCTAssertEqual(activity.processingIDs, ["child"])
        XCTAssertEqual(activity.rootIDs(chats: [DevHistoryWelcomeData.chat("child", parent: "root")]), ["root"])
        activity.consume(type: "post_processing_completed", fields: ["chat_id": "child", "task_id": "new"], scope: scope)
        XCTAssertTrue(activity.processingIDs.isEmpty)
        activity.configure(accountID: "other", scope: UUID(), server: ServerProfile.current(), teamID: nil)
        activity.consume(type: "ai_task_initiated", fields: ["chat_id": "child", "task_id": "late"], scope: scope)
        XCTAssertTrue(activity.processingIDs.isEmpty)
    }

    // contract-test: supporting surface=gui.apple assertions=projects.files.connected-embed-previews,projects.surface.semantic-parity
    func testRemoteFolderDTORetainsChildrenAndSizesWithLegacyCompatibility() throws {
        let legacy = try ProjectRemoteEntry.decode(["path": "src", "kind": "directory"])
        XCTAssertTrue(legacy.children.isEmpty)
        XCTAssertNil(legacy.childFileSizeBytes)
        XCTAssertNil(legacy.childFileCount)
        XCTAssertFalse(legacy.childSummaryTruncated)
        let populated = try ProjectRemoteEntry.decode([
            "path": "frontend", "kind": "directory", "childFileCount": 1,
            "childFolderCount": 1, "childFileSizeBytes": 2048,
            "children": [["path": "frontend/src", "kind": "directory"],
                         ["path": "frontend/app.ts", "kind": "file"]]])
        XCTAssertEqual(populated.children.map(\.name), ["src", "app.ts"])
        XCTAssertEqual(populated.children.map(\.kind), ["directory", "file"])
        XCTAssertEqual(populated.childFileSizeBytes, 2048)
        XCTAssertEqual(populated.childFileCount, 1)
        XCTAssertEqual(populated.childFolderCount, 1)
        XCTAssertEqual(ProjectFolderPreviewPolicy.remoteStatus(populated), "1 file, 1 folder · 2.0 KiB in files")
        XCTAssertNil(ProjectFolderPreviewPolicy.remoteMoreText(populated))
        let limited = try ProjectRemoteEntry.decode([
            "path": "src", "kind": "directory", "childFileCount": 3,
            "childFolderCount": 0, "childFileSizeBytes": 1024, "childSummaryTruncated": true,
            "children": [["path": "src/app.ts", "kind": "file"]]])
        XCTAssertEqual(ProjectFolderPreviewPolicy.remoteStatus(limited), "At least 3 files · at least 1.0 KiB in files")
        XCTAssertEqual(ProjectFolderPreviewPolicy.remoteMoreText(limited), "More files & folders")
        XCTAssertEqual(ProjectFolderPreviewPolicy.fileSize(32), "32 B")
        XCTAssertEqual(ProjectFolderPreviewPolicy.fileSize(1048576), "1.0 MiB")
        XCTAssertThrowsError(try ProjectRemoteEntry.decode([
            "path": "src", "kind": "directory", "children": [["path": "../private", "kind": "file"]]]))
    }

    // contract-test: supporting surface=gui.apple assertions=projects.files.connected-embed-previews,projects.surface.semantic-parity
    func testFolderPreviewUsesRegularEmbedDimensionsAndAccurateSummaryStates() {
        XCTAssertEqual(ProjectFolderPreviewPolicy.width, 300)
        XCTAssertEqual(ProjectFolderPreviewPolicy.height, 200)
        XCTAssertEqual(ProjectFolderPreviewPolicy.cornerRadius, 30)
        XCTAssertEqual(ProjectFolderPreviewPolicy.visibleRowLimit, 3)
        XCTAssertEqual(ProjectFolderPreviewPolicy.fileCount(1), "1 file")
        XCTAssertEqual(ProjectFolderPreviewPolicy.fileCount(3), "3 files")
        func entry(files: Int?, folders: Int?, truncated: Bool = false) -> ProjectRemoteEntry {
            ProjectRemoteEntry(path: "src", kind: "directory", sizeBytes: nil,
                childFileCount: files, childFolderCount: folders, childSummaryTruncated: truncated)
        }
        let unavailable = entry(files: nil, folders: nil)
        XCTAssertEqual(ProjectFolderPreviewPolicy.remoteStatus(unavailable), "Contents unavailable")
        XCTAssertEqual(ProjectFolderPreviewPolicy.remoteEmptyText(unavailable), "Open to view contents")
        let empty = entry(files: 0, folders: 0)
        XCTAssertEqual(ProjectFolderPreviewPolicy.remoteStatus(empty), "0 files")
        XCTAssertEqual(ProjectFolderPreviewPolicy.remoteEmptyText(empty), "Empty folder")
        XCTAssertNil(ProjectFolderPreviewPolicy.remoteMoreText(empty))
        let populated = entry(files: 1, folders: 1)
        XCTAssertEqual(ProjectFolderPreviewPolicy.remoteStatus(populated), "1 file, 1 folder")
        XCTAssertEqual(ProjectFolderPreviewPolicy.remoteEmptyText(populated), "Open to view contents")
        XCTAssertEqual(ProjectFolderPreviewPolicy.remoteMoreText(populated), "+ 2 more files & folders")
        let limited = entry(files: 2, folders: 3, truncated: true)
        XCTAssertEqual(ProjectFolderPreviewPolicy.remoteStatus(limited), "At least 2 files, 3 folders")
        XCTAssertEqual(ProjectFolderPreviewPolicy.remoteEmptyText(limited), "Preview limited")
        XCTAssertEqual(ProjectFolderPreviewPolicy.remoteMoreText(limited), "More files & folders")
    }

    // contract-test: supporting surface=gui.apple assertions=projects.access.explicit-context,projects.files.no-server-decryption-authority
    func testRemoteResultRoutesPersonalAndTeamContextBeforeQuery() throws {
        let personal = ProjectRemoteSourceClient.resultPath(projectID: "project/a", sourceID: "source b",
            requestID: "request/c", clientID: "client+1", teamID: nil)
        let team = ProjectRemoteSourceClient.resultPath(projectID: "project/a", sourceID: "source b",
            requestID: "request/c", clientID: "client+1", teamID: "team/a")
        for path in [personal, team] {
            let components = try XCTUnwrap(URLComponents(string: path))
            XCTAssertEqual(components.percentEncodedPath,
                "/v1/projects/project%2Fa/sources/source%20b/requests/request%2Fc")
            XCTAssertEqual(components.queryItems?.first(where: { $0.name == "requesting_client_id" })?.value, "client+1")
        }
        XCTAssertNil(URLComponents(string: personal)?.queryItems?.first(where: { $0.name == "team_id" }))
        XCTAssertEqual(URLComponents(string: team)?.queryItems?.first(where: { $0.name == "team_id" })?.value, "team/a")
    }

    // contract-test: supporting surface=gui.apple assertions=projects.access.explicit-context
    func testConnectedReadmeContinuesAfterUnavailableSource() async {
        var readSources: [String] = []
        let state = await ProjectsWorkspaceStore.loadConnectedReadme(
            sources: [readmeSource("failed"), readmeSource("ready")], list: { source in
                if source.id == "failed" { throw ProjectsWorkspaceError.unsupportedSource }
                return ProjectRemoteDirectory(entries: [ProjectRemoteEntry(path: "README.md", kind: "file",
                    sizeBytes: 10, childFileCount: nil, childFolderCount: nil, childSummaryTruncated: false)],
                    omitted: 0, excluded: 0, nextCursor: nil)
            }, read: { source, path in
                readSources.append(source.id)
                XCTAssertEqual(path, "README.md")
                return ProjectRemoteText(content: "# Project", truncated: false,
                    sizeBytes: 9, lineCount: 1, expectedBase: nil)
            })
        guard case .ready(let readme) = state else { return XCTFail("A second readable source must supply its README") }
        XCTAssertEqual(readme.markdown, "# Project")
        XCTAssertEqual(readme.origin, "connected")
        XCTAssertEqual(readme.sourceID, "ready")
        XCTAssertEqual(readme.sourceSessionID, "source-session")
        XCTAssertEqual(readme.sourceKeyEpoch, 1)
        XCTAssertEqual(readSources, ["ready"])
    }

    // contract-test: supporting surface=gui.apple assertions=projects.access.explicit-context
    func testOfflineAndIncompleteSourcesCannotProveAnEmptyOverview() async {
        let offline = await ProjectsWorkspaceStore.loadConnectedReadme(
            sources: [readmeSource("offline", status: "offline")], list: { _ in
                XCTFail("Offline sources cannot dispatch a file read")
                throw ProjectsWorkspaceError.unsupportedSource
            }, read: { _, _ in throw ProjectsWorkspaceError.invalidContext })
        guard case .unavailable = offline else { return XCTFail("Offline must retain source-device requirement") }
        let incomplete = await ProjectsWorkspaceStore.loadConnectedReadme(
            sources: [readmeSource("limited")], list: { _ in
                ProjectRemoteDirectory(entries: [], omitted: 1, excluded: 0, nextCursor: "next")
            }, read: { _, _ in throw ProjectsWorkspaceError.invalidContext })
        guard case .failed = incomplete else { return XCTFail("An incomplete listing must remain retryable without claiming an offline machine") }
        let complete = await ProjectsWorkspaceStore.loadConnectedReadme(
            sources: [readmeSource("empty")], list: { _ in
                ProjectRemoteDirectory(entries: [], omitted: 0, excluded: 0, nextCursor: nil)
            }, read: { _, _ in throw ProjectsWorkspaceError.invalidContext })
        guard case .empty = complete else { return XCTFail("Complete source listing without README is empty") }
    }

    // contract-test: supporting surface=gui.apple assertions=projects.access.explicit-context,projects.surface.semantic-parity
    func testConnectedReadmeFailureDoesNotClaimRemoteMachineIsOffline() async {
        for error in [ProjectsWorkspaceError.invalidResponse, .unsupportedSource, .sourceTimedOut] {
            let state = await ProjectsWorkspaceStore.loadConnectedReadme(sources: [readmeSource("connected")],
                list: { _ in throw error }, read: { _, _ in throw ProjectsWorkspaceError.invalidContext })
            guard case .failed = state else { return XCTFail("A read/parse/timeout failure must expose retryable failure, not offline presence") }
        }
        let permission = await ProjectsWorkspaceStore.loadConnectedReadme(
            sources: [readmeSource("permission", status: "permission_required")],
            list: { _ in XCTFail("Permission-required sources must not dispatch"); throw ProjectsWorkspaceError.invalidContext },
            read: { _, _ in throw ProjectsWorkspaceError.invalidContext })
        guard case .failed = permission else { return XCTFail("Permission state must not claim the source machine is offline") }
        let offline = await ProjectsWorkspaceStore.loadConnectedReadme(sources: [readmeSource("connected")],
            list: { _ in throw APIError.httpError(status: 404, message: "source_offline") },
            read: { _, _ in throw ProjectsWorkspaceError.invalidContext })
        guard case .unavailable = offline else { return XCTFail("The backend's explicit unavailable-source code establishes offline presence") }
    }

    // contract-test: supporting surface=gui.apple assertions=projects.access.explicit-context
    func testRemoteSourceErrorClassificationRequiresExplicitPresenceFailure() {
        let offline = ProjectRemoteSourceClient.classifySourceError(APIError.httpError(status: 404, message: "source_offline"))
        guard case ProjectsWorkspaceError.sourceOffline = offline else { return XCTFail("Explicit source_offline must classify as offline") }
        for status in [403, 404, 500] {
            let error = ProjectRemoteSourceClient.classifySourceError(APIError.httpError(status: status, message: "request_failed"))
            guard case APIError.httpError = error else { return XCTFail("Other remote read errors must retain their original category") }
        }
    }

    private func readmeSource(_ id: String, status: String = "connected") -> ProjectWorkspaceSource {
        ProjectWorkspaceSource(id: id, kind: "remote_folder", name: "Source", metadata: [:],
            capabilities: ["read"], status: status, sessionID: "source-session", keyEpoch: 1)
    }

    // contract-test: supporting surface=gui.apple assertions=apple-workspaces.offline-complete,apple-workspaces.local-first,projects.access.explicit-context,projects.files.connected-embed-previews
    func testSourceRefreshRecoversPresenceAndClosesDisconnectedBrowser() async {
        let service = ProjectsWorkspaceMockService()
        let project = makeProject(id: "source-project", name: "Project")
        func source(_ status: String, session: String?) -> ProjectWorkspaceSource {
            ProjectWorkspaceSource(id: "source", kind: "local_git_repository", name: "Source",
                metadata: [:], capabilities: ["read"], status: status, sessionID: session, keyEpoch: session == nil ? nil : 1)
        }
        service.listResult = [project]
        service.contentsResult = ProjectWorkspaceContents(folders: [], items: [],
            sources: [source("offline", session: nil)])
        let store = ProjectsWorkspaceStore(service: service, validateFence: { _ in })
        await store.load(accountId: "account-a")
        await store.selectProject(project.id)
        await store.openRemoteSource("source")
        XCTAssertEqual(store.activeRemoteSourceID, "source", "Readable offline sources open a metadata-only browser")
        XCTAssertTrue(store.remoteMetadataOnly)
        XCTAssertTrue(store.remoteEntries.isEmpty, "Missing cached metadata must not invent directory entries")
        XCTAssertNotNil(store.remoteError, "An uncached offline source must expose unavailable content")
        XCTAssertNil(store.sources.first?.sessionID, "Offline browsing must not restore live source authority")

        service.sourcesResult = [source("connected", session: "session-one")]
        await store.refreshSourceStatus()
        XCTAssertEqual(store.sources.first?.status, "connected")
        XCTAssertEqual(store.sources.first?.sessionID, "session-one")
        await store.openRemoteSource("source")
        XCTAssertEqual(store.activeRemoteSourceID, "source")
        service.sourcesResult = [source("connected", session: "session-two")]
        await store.refreshSourceStatus()
        XCTAssertNil(store.activeRemoteSourceID, "A replacement binding cannot retain the previous browser")

        await store.openRemoteSource("source")
        service.sourcesResult = [source("offline", session: nil)]
        await store.refreshSourceStatus()
        XCTAssertEqual(store.sources.first?.status, "offline")
        XCTAssertNil(store.activeRemoteSourceID)
        XCTAssertTrue(store.remoteEntries.isEmpty)
        XCTAssertTrue(store.remoteFilePreviews.isEmpty)
        XCTAssertNil(store.remoteEmbed)
        XCTAssertNil(store.remoteDownloadURL)
    }

    // contract-test: supporting surface=gui.apple assertions=projects.access.explicit-context
    func testLateSourceRefreshCannotPublishAfterAccountReset() async {
        let service = ProjectsWorkspaceMockService()
        let project = makeProject(id: "source-project", name: "Project")
        service.listResult = [project]
        service.contentsResult = ProjectWorkspaceContents(folders: [], items: [], sources: [])
        let store = ProjectsWorkspaceStore(service: service, validateFence: { _ in })
        await store.load(accountId: "account-a")
        await store.selectProject(project.id)
        service.suspendSources = true
        let refresh = Task { await store.refreshSourceStatus() }
        for _ in 0..<100 where service.sourcesContinuation == nil { await Task.yield() }
        XCTAssertNotNil(service.sourcesContinuation)
        store.reset(accountId: "account-b")
        service.sourcesContinuation?.resume(returning: [readmeSource("old-source")])
        service.sourcesContinuation = nil
        await refresh.value
        XCTAssertTrue(store.sources.isEmpty)
        XCTAssertNil(store.selectedProjectID)
        XCTAssertTrue(store.sourceRootPreviews.isEmpty)
    }

    // contract-test: supporting surface=gui.apple assertions=projects.access.explicit-context,projects.files.connected-embed-previews
    func testSourceDisconnectDuringFinalFenceCheckCannotReviveRootPreview() async {
        let service = ProjectsWorkspaceMockService()
        let project = makeProject(id: "source-project", name: "Project")
        service.listResult = [project]
        let readme = ProjectWorkspaceItem(id: "stored-readme", kind: "embed", targetID: "readme-target",
            name: "README.md", metadata: [:], folderHash: nil, position: 0, createdAt: 1)
        service.storedFileResult = ["code": "# Public fixture"]
        service.contentsResult = ProjectWorkspaceContents(folders: [], items: [readme],
            sources: [readmeSource("source")])
        var rootContinuation: CheckedContinuation<ProjectRemoteDirectory, Never>?
        var fenceContinuation: CheckedContinuation<Void, Never>?
        var suspendNextFence = false
        var fenceReturned = false
        let store = ProjectsWorkspaceStore(service: service, listSourceRoot: { _, _, _ in
            await withCheckedContinuation { rootContinuation = $0 }
        }, validateFence: { _ in
            if suspendNextFence {
                suspendNextFence = false
                await withCheckedContinuation { fenceContinuation = $0 }
                fenceReturned = true
            }
        })
        await store.load(accountId: "account-a")
        await store.selectProject(project.id)
        for _ in 0..<100 {
            if rootContinuation != nil, case .ready = store.readme { break }
            await Task.yield()
        }
        guard let rootContinuation else { return XCTFail("The bounded root read must be suspended") }
        guard case .ready = store.readme else {
            rootContinuation.resume(returning: ProjectRemoteDirectory(entries: [], omitted: 0,
                excluded: 0, nextCursor: nil))
            return XCTFail("README discovery must finish before suspending the root's final fence")
        }
        suspendNextFence = true
        rootContinuation.resume(returning: ProjectRemoteDirectory(
            entries: [remoteEntry("old-session.ts")], omitted: 0, excluded: 0, nextCursor: nil))
        for _ in 0..<100 where fenceContinuation == nil { await Task.yield() }
        guard let fenceContinuation else { return XCTFail("The final publication fence must suspend") }
        service.sourcesResult = [readmeSource("source", status: "offline")]
        await store.refreshSourceStatus()
        XCTAssertEqual(store.sources.first?.status, "offline")
        fenceContinuation.resume()
        for _ in 0..<100 where !fenceReturned { await Task.yield() }
        for _ in 0..<20 { await Task.yield() }
        XCTAssertTrue(fenceReturned)
        XCTAssertTrue(store.sourceRootPreviews.isEmpty,
                      "A late account check cannot restore previews from the disconnected binding")
    }

    // contract-test: supporting surface=gui.apple assertions=projects.surface.semantic-parity
    func testProjectInspirationPreservesWebFeatureCardMetadata() throws {
        let payload = Data("""
        {"inspirationId":"hardcoded-project-brief","text":"Start every project with a short brief","category":"productivity","feature":{"icon":"folder-kanban","title":"Project planning tip","description":"Define the outcome before collecting files and chats."}}
        """.utf8)
        let inspiration = try JSONDecoder().decode(DailyInspirationData.self, from: payload)
        XCTAssertEqual(inspiration.feature?.iconName, "folder-kanban")
        XCTAssertEqual(inspiration.feature?.title, "Project planning tip")
        XCTAssertEqual(inspiration.feature?.description, "Define the outcome before collecting files and chats.")
    }

    // contract-test: supporting surface=gui.apple assertions=projects.files.connected-embed-previews
    func testConnectedRootFilesUseWebTextPreviewPolicy() {
        for path in ["Dockerfile", "Makefile", "config.toml", "notes.custom", "package-lock.json",
                     "Info.plist", "LICENSE", "docs/README.md", "types/header.hpp"] {
            XCTAssertTrue(ProjectRemotePreviewPolicy.canReadText(path), path)
        }
        for path in ["archive.pdf", "image.png", "bundle.zip", "movie.mp4", "font.woff2", "../secret", "/absolute"] {
            XCTAssertFalse(ProjectRemotePreviewPolicy.canReadText(path), path)
        }
    }

    // contract-test: supporting surface=gui.apple assertions=projects.files.connected-embed-previews,projects.files.no-server-decryption-authority
    func testRemoteTextUsesTransientCodeEmbedWithSourceAndFilename() throws {
        let text = ProjectRemoteText(content: "FROM scratch", truncated: false, sizeBytes: 12,
            lineCount: 1, expectedBase: nil)
        let embed = ProjectRemotePreviewPolicy.embed(sourceID: "fixture-source", sourceLabel: "Repository",
            path: "Dockerfile", text: text)
        XCTAssertEqual(embed.id, "remote:fixture-source:Dockerfile")
        XCTAssertEqual(embed.type, "code-code")
        XCTAssertEqual(embed.appId, "code")
        XCTAssertEqual(embed.rawData?["language"]?.value as? String, "dockerfile")
        XCTAssertEqual(embed.rawData?["filename"]?.value as? String, "Dockerfile")
        XCTAssertEqual(embed.rawData?["code"]?.value as? String, "FROM scratch")
        XCTAssertEqual(embed.rawData?["remote_source_label"]?.value as? String, "Repository")
    }

    // contract-test: supporting surface=gui.apple assertions=projects.files.connected-embed-previews
    func testConnectedDirectoryRetainsCursorPagesAndAllowsPrevious() {
        var pages = ProjectRemotePagination()
        let first = (0..<48).map { remoteEntry("file-\($0).ts") }
        pages.install(ProjectRemoteDirectory(entries: first, omitted: 10, excluded: 0,
            nextCursor: "file-47.ts"), page: 0)
        XCTAssertEqual(pages.entries.count, 48)
        XCTAssertEqual(pages.firstEntryNumber, 1)
        XCTAssertEqual(pages.lastEntryNumber, 48)
        XCTAssertEqual(pages.totalEntryCount, 58)
        XCTAssertEqual(pages.cursor(for: 1), "file-47.ts")
        XCTAssertTrue(pages.canShow(1))
        XCTAssertFalse(pages.canShow(2))
        let second = (48..<58).map { remoteEntry("file-\($0).ts") }
        pages.install(ProjectRemoteDirectory(entries: second, omitted: 0, excluded: 0,
            nextCursor: nil), page: 1)
        XCTAssertEqual(pages.entries.last?.path, "file-57.ts")
        XCTAssertEqual(pages.firstEntryNumber, 49)
        XCTAssertEqual(pages.lastEntryNumber, 58)
        XCTAssertEqual(pages.totalEntryCount, 58)
        XCTAssertTrue(pages.canShow(0))
        XCTAssertFalse(pages.canShow(2))
        XCTAssertNil(pages.cursor(for: 0))
    }

    // contract-test: supporting surface=gui.apple assertions=projects.files.connected-embed-previews
    func testLegacyConnectedDirectoryReachesEveryFileWithoutMountingAllCards() {
        var pages = ProjectRemotePagination()
        let all = (0..<105).map { remoteEntry("file-\($0).ts") }
        pages.install(ProjectRemoteDirectory(entries: all, omitted: 3, excluded: 0,
            nextCursor: nil), page: 0)
        var opened = pages.entries.map(\.path)
        XCTAssertEqual(pages.entries.count, 48)
        XCTAssertTrue(pages.showLegacyPage(1))
        opened += pages.entries.map(\.path)
        XCTAssertEqual(pages.entries.count, 48)
        XCTAssertTrue(pages.showLegacyPage(2))
        opened += pages.entries.map(\.path)
        XCTAssertEqual(pages.entries.count, 9)
        XCTAssertNil(pages.nextCursor)
        XCTAssertEqual(pages.omitted, 3, "Source omissions stay visible on the last page")
        XCTAssertEqual(opened, all.map(\.path))
        XCTAssertTrue(pages.showLegacyPage(0))
        XCTAssertEqual(pages.entries.first?.path, "file-0.ts")
        XCTAssertFalse(pages.showLegacyPage(4))
    }

    // contract-test: supporting surface=gui.apple assertions=projects.files.connected-embed-previews,projects.access.explicit-context
    func testConnectedFixturePaginationUsesOnlyImmediateChildrenAndResetsOnClose() async {
        let store = ProjectsWorkspaceStore()
        store.installPreview(variant: "largeConnectedSource")
        await store.openRemoteSource("source-preview")
        XCTAssertEqual(store.remoteEntries.count, 48)
        XCTAssertFalse(store.remoteEntries.contains { $0.path == "nested/needle-child.ts" })
        await store.showRemotePage(1)
        XCTAssertEqual(store.remotePagination.pageIndex, 1)
        XCTAssertEqual(store.remoteEntries.count, 48)
        await store.browseRemote(path: "nested")
        XCTAssertEqual(store.remotePagination.pageIndex, 0)
        XCTAssertEqual(store.remoteEntries.map(\.path), ["nested/needle-child.ts"])
        store.closeRemoteSource()
        XCTAssertTrue(store.remoteEntries.isEmpty)
        XCTAssertEqual(store.remotePagination.pageIndex, 0)
        XCTAssertNil(store.remotePagination.nextCursor)
    }

    private func remoteEntry(_ path: String) -> ProjectRemoteEntry {
        ProjectRemoteEntry(path: path, kind: "file", sizeBytes: 128,
            childFileCount: nil, childFolderCount: nil, childSummaryTruncated: false)
    }

    // contract-test: supporting surface=gui.apple assertions=projects.files.connected-embed-previews
    func testTruncatedConnectedFileDownloadsFullOriginalInsteadOfPreview() async throws {
        let store = ProjectsWorkspaceStore()
        store.installPreview(variant: "truncatedConnectedSource")
        await store.openRemoteSource("source-preview")
        await store.openRemoteText("large.txt")
        let preview = try XCTUnwrap(store.remoteText)
        XCTAssertTrue(preview.truncated)
        XCTAssertFalse(preview.content.contains("ORIGINAL FILE END"))
        await store.downloadRemoteFile("large.txt")
        let url = try XCTUnwrap(store.remoteDownloadURL)
        let downloaded = try Data(contentsOf: url)
        XCTAssertEqual(downloaded, Data(ProjectsWorkspacePreviewFixture.originalText.utf8))
        XCTAssertGreaterThan(downloaded.count, preview.content.utf8.count)
        XCTAssertEqual(url.lastPathComponent, "large.txt")
        XCTAssertTrue(store.remoteText?.truncated == true, "Downloading never replaces the bounded preview")
        store.clearRemoteText()
        XCTAssertFalse(FileManager.default.fileExists(atPath: url.path))
    }

    // contract-test: supporting surface=gui.apple assertions=projects.files.connected-embed-previews,projects.access.explicit-context
    func testConnectedOriginalDownloadRejectsCompletionAfterSourceCloses() async throws {
        let store = ProjectsWorkspaceStore()
        store.installPreview(variant: "truncatedConnectedSource")
        await store.openRemoteSource("source-preview")
        var pending: CheckedContinuation<URL, Never>?
        store.debugOriginalDownload = { _, _ in
            await withCheckedContinuation { pending = $0 }
        }
        let request = Task { await store.downloadRemoteFile("large.txt") }
        for _ in 0..<100 where pending == nil { await Task.yield() }
        let continuation = try XCTUnwrap(pending)
        store.closeRemoteSource()
        let url = try await ProjectsWorkspacePreviewFixture.downloadOriginal(path: "large.txt", progress: { _, _ in })
        continuation.resume(returning: url)
        await request.value
        XCTAssertNil(store.remoteDownloadURL)
        XCTAssertFalse(FileManager.default.fileExists(atPath: url.path))
        XCTAssertFalse(store.isLoadingRemote)
    }

    // contract-test: supporting surface=gui.apple assertions=projects.files.connected-embed-previews,projects.access.explicit-context
    func testConnectedOriginalDownloadChecksAccountFenceAfterTransport() async throws {
        let service = ProjectsWorkspaceMockService()
        service.listResult = [makeProject(id: "fixture-project", name: "Public fixture")]
        service.contentsResult = ProjectWorkspaceContents(folders: [], items: [], sources: [readmeSource("fixture-source")])
        var checks = 0
        var checkingDownload = false
        let store = ProjectsWorkspaceStore(service: service, validateFence: { _ in
            guard checkingDownload else { return }
            checks += 1
            if checks == 2 { throw ProjectsWorkspaceError.accountChanged }
        })
        await store.load(accountId: "fixture-account")
        await store.selectProject("fixture-project")
        await store.openRemoteSource("fixture-source")
        for _ in 0..<20 { await Task.yield() }
        checkingDownload = true
        checks = 0
        var transferredURL: URL?
        store.debugOriginalDownload = { path, progress in
            let url = try await ProjectsWorkspacePreviewFixture.downloadOriginal(path: path, progress: progress)
            transferredURL = url
            return url
        }
        await store.downloadRemoteFile("large.txt")
        let url = try XCTUnwrap(transferredURL)
        XCTAssertEqual(checks, 2, "Validate before dispatch and before publishing downloaded private bytes")
        XCTAssertNil(store.remoteDownloadURL)
        XCTAssertNotNil(store.remoteError)
        XCTAssertFalse(FileManager.default.fileExists(atPath: url.path))
    }

    // contract-test: supporting surface=gui.apple assertions=projects.files.connected-embed-previews,projects.surface.semantic-parity
    func testConnectedFileMetadataExistsWhileTextReadIsPending() async throws {
        let store = ProjectsWorkspaceStore()
        store.installPreview(variant: "rootFiles")
        await store.openRemoteSource("source-preview")
        let entry = try XCTUnwrap(store.remoteEntries.first { $0.path == "privacy_filter_benchmark.py" })
        var pending: CheckedContinuation<Void, Never>?
        store.debugBeforeRemoteRead = { await withCheckedContinuation { pending = $0 } }
        let read = Task { await store.openRemoteFile(entry) }
        for _ in 0..<100 where pending == nil { await Task.yield() }
        let continuation = try XCTUnwrap(pending)
        XCTAssertTrue(store.isLoadingRemote)
        XCTAssertNil(store.remoteEmbed)
        let shell = ProjectRemoteFilePresentation.metadataEmbed(sourceID: "source-preview", entry: entry)
        XCTAssertEqual(shell.appId, "code")
        XCTAssertEqual(shell.rawData?["filename"]?.value as? String, entry.name)
        XCTAssertEqual(ProjectRemoteFilePresentation.header(entry).title, entry.name)
        continuation.resume()
        await read.value
        XCTAssertEqual(store.remoteEmbed?.id, shell.id, "The shell identity must survive hydration")
        XCTAssertFalse(store.isLoadingRemote)
    }

    // contract-test: supporting surface=gui.apple assertions=projects.files.connected-embed-previews,projects.access.explicit-context
    func testConnectedImageOpensAutomaticallyDecodesPixelsAndRetriesFailure() async throws {
        let store = ProjectsWorkspaceStore()
        store.installPreview(variant: "rootFiles")
        await store.openRemoteSource("source-preview")
        let entry = try XCTUnwrap(store.remoteEntries.first { $0.path == "mates-macos.png" })
        XCTAssertEqual(ProjectRemoteFilePresentation.metadataEmbed(sourceID: "source-preview", entry: entry).appId, "images")
        var downloads = 0
        store.debugOriginalDownload = { path, progress in
            downloads += 1
            if downloads == 1 { throw ProjectsWorkspaceError.invalidResponse }
            return try await ProjectsWorkspacePreviewFixture.downloadOriginal(path: path, progress: progress)
        }
        await store.openRemoteFile(entry)
        XCTAssertEqual(downloads, 1, "Opening an image must fetch without a second action")
        XCTAssertNotNil(store.remoteError)
        XCTAssertNil(store.remoteImage)
        await store.openRemoteFile(entry)
        XCTAssertEqual(downloads, 2)
        XCTAssertNil(store.remoteError)
        let image = try XCTUnwrap(store.remoteImage)
        XCTAssertEqual(image.pixels.width, 32)
        XCTAssertEqual(image.pixels.height, 16)
        let url = try XCTUnwrap(store.remoteDownloadURL)
        store.clearRemoteText()
        XCTAssertNil(store.remoteImage)
        XCTAssertFalse(FileManager.default.fileExists(atPath: url.path))
    }

    // contract-test: supporting surface=gui.apple assertions=projects.files.connected-embed-previews,projects.access.explicit-context
    func testConnectedImageRejectsCorruptBytesAndLateCompletionAfterClose() async throws {
        let store = ProjectsWorkspaceStore()
        store.installPreview(variant: "rootFiles")
        await store.openRemoteSource("source-preview")
        let entry = try XCTUnwrap(store.remoteEntries.first { $0.path == "mates-macos.png" })
        store.debugOriginalDownload = { path, progress in
            let url = try await ProjectsWorkspacePreviewFixture.downloadOriginal(path: path, progress: progress)
            try Data("invalid public image fixture".utf8).write(to: url)
            return url
        }
        await store.openRemoteFile(entry)
        XCTAssertNotNil(store.remoteError)
        XCTAssertNil(store.remoteImage, "File download success alone is not image render success")
        var pending: CheckedContinuation<URL, Never>?
        store.debugOriginalDownload = { _, _ in await withCheckedContinuation { pending = $0 } }
        let read = Task { await store.openRemoteFile(entry) }
        for _ in 0..<100 where pending == nil { await Task.yield() }
        let continuation = try XCTUnwrap(pending)
        store.clearRemoteText()
        let url = try await ProjectsWorkspacePreviewFixture.downloadOriginal(path: entry.path, progress: { _, _ in })
        continuation.resume(returning: url)
        await read.value
        XCTAssertNil(store.remoteImage)
        XCTAssertNil(store.remoteDownloadURL)
        XCTAssertNil(store.remoteError)
        XCTAssertFalse(FileManager.default.fileExists(atPath: url.path))
    }

    // contract-test: supporting surface=gui.apple assertions=projects.files.connected-embed-previews,projects.access.explicit-context
    func testConnectedImageRejectsKnownOversizeBeforeTransport() async throws {
        let store = ProjectsWorkspaceStore()
        store.installPreview(variant: "rootFiles")
        await store.openRemoteSource("source-preview")
        var downloads = 0
        store.debugOriginalDownload = { path, progress in
            downloads += 1
            return try await ProjectsWorkspacePreviewFixture.downloadOriginal(path: path, progress: progress)
        }
        let entry = ProjectRemoteEntry(path: "oversized.png", kind: "file",
            sizeBytes: ProjectRemoteFileImage.maximumBytes + 1, childFileCount: nil,
            childFolderCount: nil, childSummaryTruncated: false)
        await store.openRemoteFile(entry)
        XCTAssertEqual(downloads, 0)
        XCTAssertNotNil(store.remoteError)
        XCTAssertNil(store.remoteDownloadURL)
        XCTAssertFalse(store.isLoadingRemote)
    }

    // contract-test: supporting surface=gui.apple assertions=projects.files.connected-embed-previews,projects.access.explicit-context
    func testOriginalDownloadPreviewLimitRejectsOversizeBeforeFirstWrite() throws {
        let cap = ProjectRemoteFileImage.maximumBytes
        XCTAssertThrowsError(try ProjectRemoteSourceClient.validateDownloadSize(
            total: cap + 1, offset: 0, chunkBytes: 128 * 1024, maximumBytes: cap))
        XCTAssertNoThrow(try ProjectRemoteSourceClient.validateDownloadSize(
            total: cap, offset: cap - 1, chunkBytes: 1, maximumBytes: cap))
        XCTAssertThrowsError(try ProjectRemoteSourceClient.validateDownloadSize(
            total: cap, offset: cap - 1, chunkBytes: 2, maximumBytes: cap))
        XCTAssertNoThrow(try ProjectRemoteSourceClient.validateDownloadSize(
            total: cap + 1, offset: 0, chunkBytes: 128 * 1024, maximumBytes: nil),
            "Explicit original downloads retain their unrestricted transfer semantics")
    }

    // contract-test: supporting surface=gui.apple assertions=projects.files.connected-embed-previews,projects.access.explicit-context
    func testConnectedSVGUsesSharedInertValidatorAndClearsOnClose() async throws {
        let store = ProjectsWorkspaceStore()
        store.installPreview(variant: "rootFiles")
        await store.openRemoteSource("source-preview")
        let safe = Data("<svg xmlns=\"http://www.w3.org/2000/svg\" width=\"32\" height=\"16\"><rect width=\"32\" height=\"16\" fill=\"red\"/></svg>".utf8)
        let entry = ProjectRemoteEntry(path: "public.svg", kind: "file", sizeBytes: safe.count,
            childFileCount: nil, childFolderCount: nil, childSummaryTruncated: false)
        store.debugOriginalDownload = { path, progress in
            let url = try await ProjectsWorkspacePreviewFixture.downloadOriginal(path: "large.txt", progress: progress)
            try safe.write(to: url)
            return url
        }
        await store.openRemoteFile(entry)
        XCTAssertEqual(store.remoteSVG?.data, safe)
        XCTAssertNil(store.remoteImage)
        XCTAssertNil(store.remoteError)
        let url = try XCTUnwrap(store.remoteDownloadURL)
        store.clearRemoteText()
        XCTAssertNil(store.remoteSVG)
        XCTAssertFalse(FileManager.default.fileExists(atPath: url.path))

        let hostile = [
            "<svg xmlns=\"http://www.w3.org/2000/svg\"><script>alert(1)</script></svg>",
            "<svg xmlns=\"http://www.w3.org/2000/svg\"><use href=\"https://example.invalid/private.svg#shape\"/></svg>"
        ]
        for text in hostile {
            store.debugOriginalDownload = { path, progress in
                let url = try await ProjectsWorkspacePreviewFixture.downloadOriginal(path: "large.txt", progress: progress)
                try Data(text.utf8).write(to: url)
                return url
            }
            await store.openRemoteFile(entry)
            XCTAssertNil(store.remoteSVG)
            XCTAssertNotNil(store.remoteError)
        }
        store.clearRemoteText()
        XCTAssertEqual(ProjectRemoteFilePreview.maximumBytes(path: "public.SVG"), 2_000_000)
    }

    // contract-test: supporting surface=gui.apple assertions=projects.files.search-scoped
    func testProjectSearchFindsNestedStoredAndConnectedSourceMatchesAndClearsOnSelection() async {
        let store = ProjectsWorkspaceStore()
        store.installPreview(variant: "largeConnectedSource")
        await store.searchFiles("needle", prioritySourceID: nil, priorityPath: nil)

        XCTAssertTrue(store.searchActive)
        XCTAssertFalse(store.isSearching)
        XCTAssertTrue(store.searchResults.contains { entry in
            if case .item(let item) = entry { return item.name == "needle-stored-nested.md" }
            return false
        })
        XCTAssertTrue(store.searchResults.contains { entry in
            if case .remote(_, let remote) = entry { return remote.path == "nested/needle-child.ts" }
            return false
        })
        await store.selectProject(nil)
        XCTAssertFalse(store.searchActive)
        XCTAssertTrue(store.searchResults.isEmpty)
    }

    // contract-test: supporting surface=gui.apple assertions=projects.files.no-server-decryption-authority
    func testHydratedProjectPreviewLivesOnlyInSelectedProjectsMemory() async throws {
        let store = ProjectsWorkspaceStore()
        store.installPreview(variant: "folders")
        let item = try XCTUnwrap(store.items.first { $0.id == "project-source" })
        await store.loadItemEmbedPreview(item)
        XCTAssertNotNil(store.itemEmbedPreviews[item.id])
        await store.selectProject(nil)
        XCTAssertTrue(store.itemEmbedPreviews.isEmpty)
    }

    // contract-test: supporting surface=gui.apple assertions=projects.files.connected-embed-previews,projects.access.explicit-context
    func testSlowReadmeDoesNotBlockLoadedFilesAndLateReadmeCannotCrossProjectSelection() async {
        let service = ProjectsWorkspaceMockService()
        let project = makeProject(id: "readme-project", name: "Project")
        let item = ProjectWorkspaceItem(id: "readme-item", kind: "embed", targetID: "readme-target",
            name: "README.md", metadata: [:], folderHash: nil, position: 0, createdAt: 1)
        service.listResult = [project]
        service.contentsResult = ProjectWorkspaceContents(folders: [], items: [item], sources: [])
        service.suspendStoredFile = true
        let store = ProjectsWorkspaceStore(service: service, validateFence: { _ in })
        await store.load(accountId: "account-a")
        await store.selectProject(project.id)
        for _ in 0..<100 where service.storedFileContinuation == nil { await Task.yield() }
        XCTAssertNotNil(service.storedFileContinuation)
        XCTAssertFalse(store.isLoadingDetail, "Files must be available while README content is pending")
        XCTAssertEqual(store.items.map(\.id), [item.id])
        await store.selectProject(nil)
        service.storedFileContinuation?.resume(returning: ["code": "# Project"])
        service.storedFileContinuation = nil
        for _ in 0..<20 { await Task.yield() }
        XCTAssertNil(store.selectedProjectID)
        XCTAssertTrue(store.items.isEmpty)
        if case .ready = store.readme { XCTFail("A previous Project's README cannot publish after navigation") }
    }

    // contract-test: supporting surface=gui.apple assertions=apple-controls.project
    func testControlProjectRefreshRejectsDeletedCachedProjectAndOpensExactCurrentSelection() async throws {
        let service = ProjectsWorkspaceMockService()
        let cached = makeProject(id: "deleted", name: "Deleted project")
        let current = makeProject(id: "current", name: "Current project")
        service.cachedListResult = [cached]
        service.listResult = [current]
        let store = ProjectsWorkspaceStore(service: service, validateFence: { _ in })
        let deletedAvailable = await store.refreshForControl(projectID: cached.id, accountID: "account-a", teamID: nil)
        XCTAssertFalse(deletedAvailable)
        XCTAssertNil(store.selectedProjectID)
        let currentAvailable = await store.refreshForControl(projectID: current.id, accountID: "account-a", teamID: nil)
        XCTAssertTrue(currentAvailable)
        await store.selectProject(current.id)
        XCTAssertEqual(store.selectedProjectID, current.id)
        XCTAssertEqual(store.selectedProject?.name, current.name)
    }

    // contract-test: supporting surface=gui.apple assertions=apple-controls.project,apple-controls.private-cache
    func testControlProjectRefreshRejectsLateInventoryAfterAccountReplacement() async throws {
        let service = ProjectsWorkspaceMockService()
        let store = ProjectsWorkspaceStore(service: service, validateFence: { _ in })
        let old = makeProject(id: "old", name: "Old project")
        let refresh = Task { await store.refreshForControl(projectID: old.id, accountID: "account-a", teamID: nil) }
        let suspended = await waitForSuspendedList(service)
        XCTAssertTrue(suspended)
        store.reset(accountId: "account-b")
        service.finishList(with: [old])
        let available = await refresh.value
        XCTAssertFalse(available)
        XCTAssertTrue(store.projects.isEmpty)
        XCTAssertNil(store.selectedProjectID)
    }

    // contract-test: supporting surface=gui.apple assertions=projects.access.explicit-context
    func testResetDuringSuspendedProjectLoadDoesNotPublishPreviousAccount() async throws {
        let service = ProjectsWorkspaceMockService()
        let store = ProjectsWorkspaceStore(service: service)
        let oldProject = makeProject(id: "old", name: "Old account")

        let load = Task { await store.load(accountId: "account-a") }
        let suspended = await waitForSuspendedList(service)
        XCTAssertTrue(suspended)
        store.reset(accountId: "account-b")
        service.finishList(with: [oldProject])
        await load.value

        XCTAssertTrue(store.projects.isEmpty)
        XCTAssertNil(store.selectedProjectID)
        XCTAssertFalse(store.isLoading)
    }

    // contract-test: supporting surface=gui.apple assertions=projects.access.explicit-context
    func testSwitchingProjectsWhileDetailLoadsKeepsNewSelectionClearOfOldContent() async throws {
        let service = ProjectsWorkspaceMockService()
        service.listResult = [makeProject(id: "first", name: "First"), makeProject(id: "second", name: "Second")]
        let store = ProjectsWorkspaceStore(service: service)
        await store.load(accountId: "account-a")

        service.suspendContents = true
        let firstLoad = Task { await store.selectProject("first") }
        let suspended = await waitForSuspendedContents(service)
        XCTAssertTrue(suspended)
        await store.selectProject(nil)
        service.finishContents(with: ProjectWorkspaceContents(
            folders: [ProjectWorkspaceFolder(id: "old-folder", name: "Private folder", parentHash: nil,
                position: 0, createdAt: 1)], items: [], sources: []))
        await firstLoad.value

        XCTAssertNil(store.selectedProjectID)
        XCTAssertTrue(store.folders.isEmpty)
        XCTAssertTrue(store.items.isEmpty)
    }

    // contract-test: supporting surface=gui.apple assertions=projects.access.explicit-context
    func testLinkedEmbedResolutionDiscardedWhenProjectSelectionChanges() async throws {
        let service = ProjectsWorkspaceMockService()
        let project = makeProject(id: "first", name: "First")
        let item = ProjectWorkspaceItem(id: "item-1", kind: "embed", targetID: "embed-1",
            name: "sample.png", metadata: ["path": "sample.png"], folderHash: nil,
            position: 0, createdAt: 1)
        service.listResult = [project]
        service.contentsResult = ProjectWorkspaceContents(folders: [], items: [item], sources: [])
        let store = ProjectsWorkspaceStore(service: service, validateFence: { _ in })
        await store.load(accountId: "account-a")
        await store.selectProject(project.id)

        let opening = Task { try await store.openLinkedEmbed(item: item) }
        for _ in 0..<100 {
            if service.embedContinuation != nil { break }
            await Task.yield()
        }
        XCTAssertNotNil(service.embedContinuation)
        await store.selectProject(nil)
        service.finishEmbed(with: EmbedRecord(id: item.targetID, type: "images-image", status: .finished,
            data: .raw(["filename": AnyCodable("sample.png")]), parentEmbedId: nil,
            appId: "images", skillId: nil, embedIds: nil, createdAt: "1"))
        do {
            _ = try await opening.value
            XCTFail("An embed from the previous Project must not open")
        } catch let error as ProjectsWorkspaceError {
            guard case .accountChanged = error else { return XCTFail("Unexpected error: \(error)") }
        }
    }

    // contract-test: supporting surface=gui.apple assertions=projects.files.no-server-decryption-authority
    func testProjectKeyMetadataUsesPlainIVEnvelopeAndWrongKeyFailsClosed() async throws {
        let projectKey = SymmetricKey(size: .bits256)
        let wrongKey = SymmetricKey(size: .bits256)
        let ciphertext = try await CryptoManager.shared.encryptWithMasterKey("Private project title", masterKey: projectKey)
        let bytes = try XCTUnwrap(Data(base64Encoded: ciphertext))

        XCTAssertGreaterThan(bytes.count, 12 + 16)
        let decrypted = try await CryptoManager.shared.decryptContent(base64String: ciphertext, key: projectKey)
        XCTAssertEqual(decrypted, "Private project title")
        do {
            _ = try await CryptoManager.shared.decryptContent(base64String: ciphertext, key: wrongKey)
            XCTFail("Wrong project key must not return plaintext")
        } catch { }
    }

    // contract-test: supporting surface=gui.apple assertions=projects.files.search-scoped
    func testProjectPathRejectsAbsoluteTraversalAndBackslash() {
        XCTAssertEqual(ProjectWorkspacePath.normalized("docs/README.md"), "docs/README.md")
        XCTAssertNil(ProjectWorkspacePath.normalized("/private/key"))
        XCTAssertNil(ProjectWorkspacePath.normalized("docs/../private/key"))
        XCTAssertNil(ProjectWorkspacePath.normalized("docs\\private"))
        XCTAssertNil(ProjectWorkspacePath.normalized("docs//README.md"))
    }

    // contract-test: supporting surface=gui.apple assertions=projects.files.expected-base
    func testFileProposalCommitmentMatchesWebAndRejectsPathTraversal() throws {
        let mutation = try ProjectFileMutation(operation: "update_file", operationID: "operation-1",
            arguments: ["path": "docs/readme.md", "expected_base": String(repeating: "a", count: 64),
                        "patch": "@@ -1 +1 @@\n-old\n+new"])
        let key = SymmetricKey(data: Data(repeating: 7, count: 32))
        XCTAssertEqual(try mutation.commitment(projectID: "project-1", chatID: "chat-1", key: key),
            "3e5b7d41a61bb62dc2c577d9140b4957794f11cd26f47d2eb45314affaab23c1")
        XCTAssertThrowsError(try ProjectFileMutation(operation: "create_file", operationID: "operation-2",
            arguments: ["path": "../secret.txt", "expected_base": NSNull(), "content": "private"]))
    }

    // contract-test: supporting surface=gui.apple assertions=projects.files.ignored-exact-inclusion
    func testIgnoredReadGrantMatchesWebAndIsExactRequestScoped() throws {
        let key = SymmetricKey(data: Data(repeating: 7, count: 32))
        let grant = try ProjectIgnoredReadGrant.make(projectID: "project-1", sourceID: "source-1",
            requestID: "request-1", chatID: "chat-1", operationID: "operation-1",
            path: "ignored.log", projectKey: key,
            now: Date(timeIntervalSince1970: 1_700_000_000))
        XCTAssertEqual(grant["expiresAt"] as? Int, 1_700_000_300_000)
        XCTAssertEqual(grant["signature"] as? String,
            "880429d6e0d867ad21b2106d36dbd97f58a1f15ec2810aafd665a07bf4694da5")
        XCTAssertThrowsError(try ProjectIgnoredReadGrant.make(projectID: "project-1", sourceID: "source-1",
            requestID: "request-1", chatID: "chat-1", operationID: "operation-1",
            path: "../private", projectKey: key))
    }

    // contract-test: supporting surface=gui.apple assertions=projects.files.write-policy-enforcement
    func testFileApprovalForReplacedProposalCannotDispatch() async throws {
        let coordinator = ProjectFileReviewCoordinator()
        let mutation = try ProjectFileMutation(operation: "update_file", operationID: "operation-1",
            arguments: ["path": "docs/plan.md", "expected_base": String(repeating: "a", count: 64),
                        "patch": "@@ -1 +1 @@\n-old\n+new"])
        func entry() -> ProjectFileReviewCoordinator.Entry {
            ProjectFileReviewCoordinator.Entry(id: "operation-1", accountID: "account-a",
                scope: OfflineStore.shared.scopeGeneration, chatID: "chat-a", projectID: "project-a",
                sourceID: "source-a", mutation: mutation, readPath: nil,
                commitment: String(repeating: "b", count: 64), status: "awaiting_approval", errorCode: nil)
        }
        let displayed = entry()
        coordinator.installReviewForTesting(displayed)
        coordinator.installReviewForTesting(entry())
        var sends = 0
        do {
            try await coordinator.decide(displayed, accepted: true, accountID: "account-a",
                activeChatID: "chat-a", send: { _, _ in sends += 1 })
            XCTFail("A stale card must not approve a replacement proposal")
        } catch let error as ProjectsWorkspaceError {
            guard case .invalidContext = error else { return XCTFail("Unexpected error: \(error)") }
        }
        XCTAssertEqual(sends, 0)
    }

    // contract-test: supporting surface=gui.apple assertions=projects.access.explicit-context
    func testRemoteCommandApprovalForReplacedReviewCannotDispatch() async throws {
        let coordinator = ProjectRemoteCommandCoordinator()
        let review = ProjectReviewFixtures.commandEntry().review
        func entry() -> ProjectRemoteCommandCoordinator.Entry {
            ProjectRemoteCommandCoordinator.Entry(id: review.executionId, accountID: "account-a",
                scope: OfflineStore.shared.scopeGeneration, review: review,
                projectName: "Project", sourceName: "Source", status: "pending", latestOutput: "")
        }
        let displayed = entry()
        coordinator.installReviewForTesting(displayed)
        coordinator.installReviewForTesting(entry())
        var sends = 0
        do {
            try await coordinator.decide(displayed, accepted: true, accountID: "account-a",
                activeChatID: review.chatId, send: { _, _ in sends += 1 })
            XCTFail("A stale command card must not authorize a replacement review")
        } catch let error as ProjectsWorkspaceError {
            guard case .invalidContext = error else { return XCTFail("Unexpected error: \(error)") }
        }
        XCTAssertEqual(sends, 0)
    }

    // contract-test: supporting surface=gui.apple assertions=code-run.remote.managed-jobs
    func testRemoteTerminalCompletionRetriesOnlyTheSameAuthenticatedEvent() async throws {
        enum FirstSend: Error { case interrupted }
        let key = SymmetricKey(size: .bits256)
        let coordinator = ProjectRemoteCommandCoordinator(
            eventKey: { _, _ in key }, checkEventFence: { _ in })
        let fixture = ProjectReviewFixtures.commandEntry(status: "running")
        let entry = ProjectRemoteCommandCoordinator.Entry(id: fixture.id, accountID: "account-a",
            scope: OfflineStore.shared.scopeGeneration, review: fixture.review,
            projectName: fixture.projectName, sourceName: fixture.sourceName,
            status: "running", latestOutput: "Checks passed.\n")
        coordinator.installReviewForTesting(entry)
        let event: [String: Any] = ["execution_id": fixture.id, "sequence": 0,
            "event_kind": "terminal", "status": "succeeded"]
        let encoded = try JSONSerialization.data(withJSONObject: event)
        let ciphertext = try await CryptoManager.shared.encryptWithMasterKey(
            String(decoding: encoded, as: UTF8.self), masterKey: key)
        let payload: [String: Any] = ["execution_id": fixture.id,
            "chat_id": fixture.review.chatId, "project_id": fixture.review.projectId,
            "source_id": fixture.review.sourceId, "encrypted_event": ciphertext,
            "sequence": 0, "event_kind": "terminal", "status": "succeeded"]
        var attempts = 0
        var successfulCompletions = 0
        let send: @MainActor (String, [String: Any]) async throws -> Void = { kind, body in
            XCTAssertEqual(kind, "remote_command_origin_completion")
            XCTAssertEqual(body["result_status"] as? String, "succeeded")
            attempts += 1
            if attempts == 1 { throw FirstSend.interrupted }
            successfulCompletions += 1
        }
        do {
            try await coordinator.receiveEvent(payload, accountID: "account-a", send: send)
            XCTFail("First send must fail")
        } catch FirstSend.interrupted { }
        XCTAssertEqual(coordinator.entries.first?.lastSequence, 0)
        XCTAssertEqual(coordinator.entries.first?.completionSent, false)

        try await coordinator.receiveEvent(payload, accountID: "account-a", send: send)
        XCTAssertEqual(attempts, 2)
        XCTAssertEqual(successfulCompletions, 1)
        XCTAssertEqual(coordinator.entries.first?.completionSent, true)
        do {
            try await coordinator.receiveEvent(payload, accountID: "account-a", send: send)
            XCTFail("A completed terminal event must not send twice")
        } catch let error as ProjectsWorkspaceError {
            guard case .invalidResponse = error else { return XCTFail("Unexpected error: \(error)") }
        }
        XCTAssertEqual(successfulCompletions, 1)
    }

    // contract-test: supporting surface=gui.apple assertions=projects.files.private-path-deny,projects.files.ignored-exact-inclusion
    func testHostedPolicyHidesPrivateAliasesAndExcludedNestedControlsBeforeDecryption() async throws {
        let adapter = HostedFilesMockAdapter(files: [
            .init(embedID: "root-ignore", path: ".gitignore"),
            .init(embedID: "nested-ignore", path: "src/.gitignore"),
            .init(embedID: "permissions", path: ".openmates/permissions.yml"),
            .init(embedID: "readme", path: "README.md"),
            .init(embedID: "debug", path: "debug.log"),
            .init(embedID: "build", path: "build/output.js"),
            .init(embedID: "ignored-control", path: "build/.gitignore"),
            .init(embedID: "drop", path: "src/generated/drop.ts"),
            .init(embedID: "keep", path: "src/generated/keep.ts"),
            .init(embedID: "vault", path: "vault/passwords.txt"),
            .init(embedID: "vault", path: "src/innocent-alias.txt"),
            .init(embedID: "internal", path: "internal/plan.txt"),
            .init(embedID: "private-control", path: "internal/hidden/.gitignore"),
        ], contents: [
            "root-ignore": "*.log\nbuild/\n",
            "nested-ignore": "generated/*\n!generated/keep.ts\n",
            "permissions": "file_access:\n  private_paths:\n    - vault/**\n",
            "readme": "needle\n", "debug": "needle\n", "build": "needle\n",
            "ignored-control": "!output.js\n", "drop": "needle\n", "keep": "needle\n",
            "vault": "needle secret\n", "internal": "needle secret\n",
            "private-control": "!plan.txt\n",
        ], privatePaths: ["internal/**"])
        let executor = ProjectHostedFileExecutor(adapter: adapter, validateFence: { _ in })
        let fence = ProjectsWorkspaceFence(accountID: "fixture")
        let listed = try await executor.execute(job: hostedJob("list", ["path": "."]),
            mutation: nil, approvedIgnoredRead: nil, fence: fence, validateAuthority: {})
        let entries = try XCTUnwrap(listed["entries"] as? [[String: String]])
        let paths = Set(entries.compactMap { $0["path"] })
        XCTAssertTrue(paths.contains("README.md"))
        XCTAssertTrue(paths.contains("src/generated/keep.ts"))
        for hidden in ["debug.log", "build/output.js", "src/generated/drop.ts",
                       "vault/passwords.txt", "src/innocent-alias.txt", "internal/plan.txt"] {
            XCTAssertFalse(paths.contains(hidden), hidden)
        }
        XCTAssertFalse(adapter.reads.contains("ignored-control"))
        XCTAssertFalse(adapter.reads.contains("private-control"))
        adapter.reads = []

        let searched = try await executor.execute(job: hostedJob("search", [
            "query": "needle", "target": "content", "mode": "literal", "path": ".",
            "glob": "**/*.md", "max_results": 20]), mutation: nil,
            approvedIgnoredRead: nil, fence: fence, validateAuthority: {})
        let matches = try XCTUnwrap(searched["matches"] as? [[String: Any]])
        XCTAssertEqual(matches.compactMap { $0["path"] as? String }, ["README.md"])
        XCTAssertFalse(adapter.reads.contains("vault"))
        XCTAssertFalse(adapter.reads.contains("internal"))
        XCTAssertFalse(adapter.reads.contains("drop"))
    }

    // contract-test: supporting surface=gui.apple assertions=projects.files.exact-patch
    func testHostedPatchRejectsNearbyContextAndAppliesOnlyDeclaredHunk() throws {
        let before = "alpha\nold\nomega\n"
        let exact = "--- a/docs/plan.md\n+++ b/docs/plan.md\n@@ -2 +2 @@\n-old\n+new\n"
        XCTAssertEqual(try ProjectHostedPatch.apply(exact, to: before, path: "docs/plan.md"),
            "alpha\nnew\nomega\n")
        let shifted = "--- a/docs/plan.md\n+++ b/docs/plan.md\n@@ -1 +1 @@\n-old\n+new\n"
        XCTAssertThrowsError(try ProjectHostedPatch.apply(shifted, to: before,
            path: "docs/plan.md"))
    }

    private func hostedJob(_ operation: String, _ arguments: [String: Any]) throws -> ProjectFileJob {
        try ProjectFileJob(["protocol_version": 1, "operation_id": "fixture-\(operation)",
            "chat_id": "fixture-chat", "project_id": "fixture-project", "operation": operation,
            "arguments": arguments, "lease_token": "fixture-lease-token-long",
            "lease_generation": 1, "lease_expires_at": Date().timeIntervalSince1970 + 60])
    }

    // contract-test: supporting surface=gui.apple assertions=projects.access.explicit-context,projects.surface.semantic-parity
    func testLateReadmeImageCannotPublishAfterAccountReset() async throws {
        let service = ProjectsWorkspaceMockService()
        let project = makeProject(id: "readme-media-project", name: "Project")
        let readmeItem = ProjectWorkspaceItem(id: "readme", kind: "embed", targetID: "readme-embed",
            name: "README.md", metadata: ["path": "README.md"], folderHash: nil, position: 0, createdAt: 1)
        let imageItem = ProjectWorkspaceItem(id: "image", kind: "embed", targetID: "image-embed",
            name: "preview.png", metadata: ["path": "assets/preview.png"], folderHash: nil, position: 1, createdAt: 2)
        service.listResult = [project]
        service.contentsResult = ProjectWorkspaceContents(folders: [], items: [readmeItem, imageItem], sources: [])
        service.storedFileResult = ["markdown": "![Preview](assets/preview.png)"]
        let store = ProjectsWorkspaceStore(service: service, validateFence: { _ in })
        await store.load(accountId: "account-a")
        await store.selectProject(project.id)
        for _ in 0..<100 { if case .ready = store.readme { break }; await Task.yield() }
        guard case .ready(let readme) = store.readme else { return XCTFail("Stored README must be available") }
        service.storedFileResult = nil
        service.suspendStoredFile = true
        let image = Task { try await store.readReadmeImage("assets/preview.png", readme: readme) }
        for _ in 0..<100 where service.storedFileContinuation == nil { await Task.yield() }
        guard let suspended = service.storedFileContinuation else { return XCTFail("Image read must suspend") }
        store.reset(accountId: "account-b")
        suspended.resume(returning: ["data_url": "data:image/png;base64," + ProjectsWorkspacePreviewFixture.readmeImageData.base64EncodedString()])
        service.storedFileContinuation = nil
        do { _ = try await image.value; XCTFail("Account changes must reject late private images") }
        catch { guard case .accountChanged? = error as? ProjectsWorkspaceError else { return XCTFail("Expected an account fence rejection") } }
    }

    private func makeProject(id: String, name: String) -> ProjectWorkspaceProject {
        ProjectWorkspaceProject(id: id, name: name, description: "", icon: "project",
            key: SymmetricKey(size: .bits256), version: 1, createdAt: 1, updatedAt: 1,
            isShared: false, itemCount: 0, teamId: nil, permissions: .denied)
    }

    private func waitForSuspendedList(_ service: ProjectsWorkspaceMockService) async -> Bool {
        for _ in 0..<100 {
            if service.listContinuation != nil { return true }
            await Task.yield()
        }
        return false
    }

    private func waitForSuspendedContents(_ service: ProjectsWorkspaceMockService) async -> Bool {
        for _ in 0..<100 {
            if service.contentsContinuation != nil { return true }
            await Task.yield()
        }
        return false
    }
    // contract-test: supporting surface=gui.apple assertions=apple-workspaces.offline-complete,apple-workspaces.isolation
    func testWorkspaceSnapshotIsCiphertextAtomicAndReopensOnlyWithItsScopeAndKey() async throws {
        let directory = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        defer { try? FileManager.default.removeItem(at: directory) }
        let scope = NativeWorkspaceOfflineScope(accountID: "account-a", server: "https://example.invalid",
            teamID: nil, accountGeneration: UUID(), teamEpoch: 1)
        let key = SymmetricKey(size: .bits256)
        let cache = NativeWorkspaceOfflineCache(directory: directory)
        await cache.configure(scope: scope, masterKey: key)
        let revision = try await cache.beginRefresh(namespace: "workflows", scope: scope)
        let privateGraph = Data("private-workflow-graph-and-instruction".utf8)
        try await cache.commit(namespace: "workflows", responses: ["list": privateGraph, "deleted": Data()],
            scope: scope, revision: revision)
        let enumerator = FileManager.default.enumerator(at: directory, includingPropertiesForKeys: nil)!
        let blobs = enumerator.allObjects.compactMap { $0 as? URL }.filter { $0.pathExtension == "aesgcm" }
        XCTAssertEqual(blobs.count, 1)
        let ciphertext = try Data(contentsOf: XCTUnwrap(blobs.first))
        XCTAssertNil(ciphertext.range(of: privateGraph))
        let reopened = NativeWorkspaceOfflineCache(directory: directory)
        await reopened.configure(scope: scope, masterKey: key)
        let restored = try await reopened.read(namespace: "workflows", path: "list", scope: scope)
        XCTAssertEqual(restored, privateGraph)
        let complete = try await reopened.hasCompleteSnapshot(namespace: "workflows", scope: scope)
        XCTAssertTrue(complete)
        let next = try await reopened.beginRefresh(namespace: "workflows", scope: scope)
        try await reopened.commit(namespace: "workflows", responses: ["list": Data("current".utf8)], scope: scope, revision: next)
        let removed = try await reopened.read(namespace: "workflows", path: "deleted", scope: scope)
        XCTAssertNil(removed)
        // A fresh actor must authenticate from disk, rather than reuse RAM.
        let wrongKey = NativeWorkspaceOfflineCache(directory: directory)
        await wrongKey.configure(scope: scope, masterKey: SymmetricKey(size: .bits256))
        do { _ = try await wrongKey.read(namespace: "workflows", path: "list", scope: scope); XCTFail("Wrong key opened workspace") }
        catch { }
    }

    // contract-test: supporting surface=gui.apple assertions=apple-workspaces.isolation,apple-workspaces.maintenance
    func testWorkspaceScopeChangeAndReplacementRefreshFenceOldCommits() async throws {
        let directory = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        defer { try? FileManager.default.removeItem(at: directory) }
        let cache = NativeWorkspaceOfflineCache(directory: directory)
        let scope = NativeWorkspaceOfflineScope(accountID: "a", server: "https://example.invalid",
            teamID: "team-a", accountGeneration: UUID(), teamEpoch: 1)
        let key = SymmetricKey(size: .bits256)
        await cache.configure(scope: scope, masterKey: key)
        let old = try await cache.beginRefresh(namespace: "projects", scope: scope)
        let current = try await cache.beginRefresh(namespace: "projects", scope: scope)
        do { try await cache.commit(namespace: "projects", responses: [:], scope: scope, revision: old); XCTFail("Old refresh committed") }
        catch is CancellationError { }
        try await cache.commit(namespace: "projects", responses: ["inventory": Data("retained".utf8)], scope: scope, revision: current)
        let newScope = NativeWorkspaceOfflineScope(accountID: "b", server: "https://other.invalid",
            teamID: "team-b", accountGeneration: UUID(), teamEpoch: 2)
        await cache.configure(scope: newScope, masterKey: key)
        do { _ = try await cache.read(namespace: "projects", path: "inventory", scope: scope); XCTFail("Old account read") }
        catch is CancellationError { }
        do { try await cache.commit(namespace: "projects", responses: [:], scope: scope, revision: current); XCTFail("Old account wrote") }
        catch is CancellationError { }
        let isolated = try await cache.read(namespace: "projects", path: "inventory", scope: newScope)
        XCTAssertNil(isolated)
        await cache.deactivate(ifScope: scope)
        let stillActive = try await cache.read(namespace: "projects", path: "inventory", scope: newScope)
        XCTAssertNil(stillActive, "A stale deactivation must preserve the replacement scope")
    }

    // contract-test: supporting surface=gui.apple assertions=apple-workspaces.offline-complete,apple-workspaces.maintenance
    func testWorkspaceInventoryRequiresFinalReceiptAndStrictCursorProgressBeyondFiveHundred() throws {
        func page(_ ids: [String], complete: Bool, cursor: String?) throws -> Data {
            try JSONSerialization.data(withJSONObject: ["tasks": ids.map { ["task_id": $0] },
                "complete": complete, "next_cursor": cursor as Any? ?? NSNull()])
        }
        var pages = NativeWorkspaceInventoryPages()
        let first = (0..<500).map { String(format: "%04d", $0) }
        try pages.append(page(first, complete: false, cursor: "0499"), collection: "tasks", idKey: "task_id")
        XCTAssertThrowsError(try pages.snapshot(collection: "tasks"))
        try pages.append(page(["0500", "0501"], complete: true, cursor: nil), collection: "tasks", idKey: "task_id")
        let result = try JSONSerialization.jsonObject(with: pages.snapshot(collection: "tasks")) as! [String: Any]
        XCTAssertEqual((result["tasks"] as? [Any])?.count, 502)
        XCTAssertThrowsError(try pages.append(page([], complete: true, cursor: nil), collection: "tasks", idKey: "task_id"))
        var repeated = NativeWorkspaceInventoryPages()
        try repeated.append(page(["a"], complete: false, cursor: "a"), collection: "tasks", idKey: "task_id")
        XCTAssertThrowsError(try repeated.append(page(["a"], complete: false, cursor: "a"), collection: "tasks", idKey: "task_id"))
        var missingReceipt = NativeWorkspaceInventoryPages()
        XCTAssertThrowsError(try missingReceipt.append(Data("{\"tasks\":[]}".utf8), collection: "tasks", idKey: "task_id"))
    }

    // contract-test: supporting surface=gui.apple assertions=apple-workspaces.isolation
    func testWorkspaceSourceSnapshotDoesNotRetainLiveHostAuthority() throws {
        let data = Data("{\"sources\":[{\"source_id\":\"s\",\"status\":\"connected\",\"source_session_id\":\"live-session\",\"key_epoch\":3,\"encrypted_metadata\":\"ciphertext\"}]}".utf8)
        let sanitized = try NativeWorkspaceOfflineRuntime.sanitizedResponse(data)
        let object = try JSONSerialization.jsonObject(with: sanitized) as! [String: Any]
        let source = (object["sources"] as! [[String: Any]])[0]
        XCTAssertNil(source["source_session_id"])
        XCTAssertEqual(source["status"] as? String, "disconnected")
        XCTAssertEqual(source["key_epoch"] as? Int, 3)
        XCTAssertEqual(source["encrypted_metadata"] as? String, "ciphertext")
    }

    // contract-test: supporting surface=gui.apple assertions=apple-workspaces.maintenance,apple-workspaces.isolation
    func testInterruptedWorkspaceRefreshPreservesPreviousCompleteSnapshot() async throws {
        let directory = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        defer { try? FileManager.default.removeItem(at: directory) }
        let cache = NativeWorkspaceOfflineCache(directory: directory)
        let scope = NativeWorkspaceOfflineScope(accountID: "a", server: "https://example.invalid",
            teamID: nil, accountGeneration: UUID(), teamEpoch: 1)
        await cache.configure(scope: scope, masterKey: SymmetricKey(size: .bits256))
        let first = try await cache.beginRefresh(namespace: "tasks", scope: scope)
        try await cache.commit(namespace: "tasks", responses: ["list": Data("previous".utf8)], scope: scope, revision: first)
        let next = try await cache.beginRefresh(namespace: "tasks", scope: scope)
        let gate = WorkspaceOfflineGETGate()
        let refresh = Task {
            let response = await gate.fetch()
            try await cache.commit(namespace: "tasks", responses: ["list": response], scope: scope, revision: next)
        }
        await gate.waitUntilStarted()
        refresh.cancel()
        await gate.finish()
        do { try await refresh.value; XCTFail("Canceled refresh committed") }
        catch is CancellationError { }
        let retained = try await cache.read(namespace: "tasks", path: "list", scope: scope)
        let complete = try await cache.hasCompleteSnapshot(namespace: "tasks", scope: scope)
        XCTAssertEqual(retained, Data("previous".utf8))
        XCTAssertTrue(complete)
        let pending = try await cache.beginRefresh(namespace: "tasks", scope: scope)
        try await cache.retain(namespace: "tasks", path: "list", data: Data("foreground".utf8), scope: scope)
        do { try await cache.commit(namespace: "tasks", responses: [:], scope: scope, revision: pending); XCTFail("Stale maintenance erased foreground data") }
        catch is CancellationError { }
        let current = try await cache.read(namespace: "tasks", path: "list", scope: scope)
        XCTAssertEqual(current, Data("foreground".utf8))
    }

    // contract-test: supporting surface=gui.apple assertions=apple-workspaces.maintenance
    func testWorkspaceDuplicateForegroundAndMaintenanceGETsShareOneFlight() async throws {
        let flights = NativeWorkspaceRequestFlights()
        let gate = WorkspaceOfflineGETGate()
        let first = Task { try await flights.perform(identity: "same-scope/list") { await gate.fetch() } }
        await gate.waitUntilStarted()
        let second = Task { try await flights.perform(identity: "same-scope/list") { await gate.fetch() } }
        for _ in 0..<100 {
            if await flights.coalescedRequestCount == 1 { break }
            await Task.yield()
        }
        let shared = await flights.coalescedRequestCount
        XCTAssertEqual(shared, 1)
        await gate.finish()
        let firstData = try await first.value
        let secondData = try await second.value
        XCTAssertEqual(firstData, secondData)
        let calls = await gate.calls
        XCTAssertEqual(calls, 1)
    }

    // contract-test: supporting surface=gui.apple assertions=apple-workspaces.maintenance
    func testWorkspaceMaintenanceCooldownCoalescesDirtySignalsAndAllowsForcedReconnect() throws {
        let scope = NativeWorkspaceOfflineScope(accountID: "a", server: "https://example.invalid",
            teamID: nil, accountGeneration: UUID(), teamEpoch: 1)
        var policy = NativeWorkspaceMaintenancePolicy()
        let first = try XCTUnwrap(policy.begin(scope: scope, now: 100))
        for namespace in ["workflows", "user-tasks", "user-plans", "projects"] {
            policy.completedNamespace(namespace, ticket: first)
        }
        policy.finish(first, now: 110, successful: true)
        for _ in 0..<50 { policy.markDirty(scope: scope) }
        XCTAssertNil(policy.begin(scope: scope, now: 111))
        XCTAssertNil(policy.begin(scope: scope, now: 409.99))
        XCTAssertEqual(policy.delay(scope: scope, now: 310), 100)
        let due = try XCTUnwrap(policy.begin(scope: scope, now: 410))
        XCTAssertTrue(policy.needsNamespace("workflows", ticket: due))
        XCTAssertNil(policy.begin(scope: scope, now: 410, force: true), "An active run must coalesce forced reconnects")
        policy.finish(due, now: 411, successful: false, interrupted: true)
        XCTAssertNil(policy.begin(scope: scope, now: 411), "Queued reconnects respect minimum admission spacing")
        XCTAssertEqual(policy.delay(scope: scope, now: 411), 29)
        XCTAssertNotNil(policy.begin(scope: scope, now: 440), "The queued essential refresh bypasses the longer success cooldown once due")
    }

    // contract-test: supporting surface=gui.apple assertions=apple-workspaces.maintenance,apple-workspaces.isolation
    func testRapidWorkspaceReconnectsRespectAdmissionAndFailureBackoffWhileNewScopeStartsImmediately() throws {
        let scope = NativeWorkspaceOfflineScope(accountID: "a", server: "https://example.invalid",
            teamID: nil, accountGeneration: UUID(), teamEpoch: 1)
        let other = NativeWorkspaceOfflineScope(accountID: "b", server: "https://example.invalid",
            teamID: nil, accountGeneration: UUID(), teamEpoch: 1)
        var policy = NativeWorkspaceMaintenancePolicy()
        let first = try XCTUnwrap(policy.begin(scope: scope, now: 10, force: true))
        for namespace in ["workflows", "user-tasks", "user-plans", "projects"] {
            policy.completedNamespace(namespace, ticket: first)
        }
        policy.finish(first, now: 12, successful: true)
        for instant in 13..<40 { XCTAssertNil(policy.begin(scope: scope, now: Double(instant), force: true)) }
        XCTAssertEqual(policy.delay(scope: scope, now: 39), 1)
        let reconnect = try XCTUnwrap(policy.begin(scope: scope, now: 40))
        policy.finish(reconnect, now: 65, successful: false)
        XCTAssertNil(policy.begin(scope: scope, now: 71, force: true), "Forced reconnect cannot bypass failure backoff")
        XCTAssertEqual(policy.delay(scope: scope, now: 71), 24)
        XCTAssertNotNil(policy.begin(scope: other, now: 71, force: true), "New account/scope has independent immediate admission")
        XCTAssertNil(policy.begin(scope: scope, now: 94.9, force: true))
        XCTAssertNotNil(policy.begin(scope: scope, now: 95), "Queued force survives until the retry wake")
    }

    // contract-test: supporting surface=gui.apple assertions=apple-workspaces.maintenance,apple-workspaces.isolation
    func testWorkspaceMaintenanceCancellationRetainsPartialProgressWithoutCompletionOrCrossScopeReuse() throws {
        let scope = NativeWorkspaceOfflineScope(accountID: "a", server: "https://example.invalid",
            teamID: "one", accountGeneration: UUID(), teamEpoch: 1)
        let other = NativeWorkspaceOfflineScope(accountID: "a", server: "https://example.invalid",
            teamID: "two", accountGeneration: scope.accountGeneration, teamEpoch: 2)
        var policy = NativeWorkspaceMaintenancePolicy()
        let first = try XCTUnwrap(policy.begin(scope: scope, now: 1))
        policy.completedNamespace("workflows", ticket: first)
        policy.finish(first, now: 2, successful: false, interrupted: true)
        let resumed = try XCTUnwrap(policy.begin(scope: scope, now: 3))
        XCTAssertFalse(policy.needsNamespace("workflows", ticket: resumed))
        XCTAssertTrue(policy.needsNamespace("projects", ticket: resumed))
        policy.finish(first, now: 100, successful: true)
        XCTAssertNil(policy.begin(scope: scope, now: 101), "An old task must not clear the replacement run")
        let changedTeam = try XCTUnwrap(policy.begin(scope: other, now: 3))
        XCTAssertTrue(policy.needsNamespace("workflows", ticket: changedTeam))
        policy.markDirty(scope: scope)
        XCTAssertTrue(policy.needsNamespace("workflows", ticket: resumed), "New changes invalidate partial progress")
        policy.finish(resumed, now: 4, successful: false)
        XCTAssertNil(policy.begin(scope: scope, now: 33.9), "Failed requests need bounded retry backoff")
        XCTAssertNotNil(policy.begin(scope: scope, now: 34))
    }

    // contract-test: supporting surface=gui.apple assertions=apple-workspaces.local-first
    func testCachedProjectListAndDetailRemainVisibleWhileRefreshIsSuspended() async throws {
        let service = ProjectsWorkspaceMockService()
        let project = makeProject(id: "cached", name: "Offline project")
        service.cachedListResult = [project]
        service.cachedContentsResult = ProjectWorkspaceContents(folders: [], items: [], sources: [])
        service.suspendContents = true
        let store = ProjectsWorkspaceStore(service: service, validateFence: { _ in })
        let load = Task { await store.load(accountId: "owner") }
        let suspendedList = await waitForSuspendedList(service)
        XCTAssertTrue(suspendedList)
        XCTAssertEqual(store.projects.map(\.id), [project.id])
        service.finishList(with: [project])
        await load.value
        let select = Task { await store.selectProject(project.id) }
        let suspendedContents = await waitForSuspendedContents(service)
        XCTAssertTrue(suspendedContents)
        XCTAssertFalse(store.isLoadingDetail)
        XCTAssertEqual(store.selectedProjectID, project.id)
        service.finishContents(with: ProjectWorkspaceContents(folders: [], items: [], sources: []))
        await select.value
    }

    // contract-test: supporting surface=gui.apple assertions=apple-workspaces.offline-complete,apple-workspaces.local-first,apple-workspaces.isolation
    func testReadmeSnapshotReopensEncryptedImagesWithoutSourceSessionAuthority() async throws {
        let directory = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        defer { try? FileManager.default.removeItem(at: directory) }
        let scope = NativeWorkspaceOfflineScope(accountID: "readme-owner", server: "https://example.invalid",
            teamID: "readme-team", accountGeneration: UUID(), teamEpoch: 1)
        let masterKey = SymmetricKey(size: .bits256)
        let project = makeProject(id: "readme-project", name: "Project")
        let connected = ProjectWorkspaceSource(id: "source", kind: "folder", name: "Files", metadata: [:],
            capabilities: ["read"], status: "connected", sessionID: "live-authority", keyEpoch: 3)
        let disconnected = ProjectWorkspaceSource(id: connected.id, kind: connected.kind, name: connected.name,
            metadata: [:], capabilities: ["read"], status: "disconnected", sessionID: nil, keyEpoch: 3)
        let contents = ProjectWorkspaceContents(folders: [], items: [], sources: [connected])
        let binding = try ProjectReadmeOfflineSnapshot.binding(project: project, contents: contents)
        XCTAssertEqual(binding, try ProjectReadmeOfflineSnapshot.binding(project: project,
            contents: .init(folders: [], items: [], sources: [disconnected])), "Presence changes cannot invalidate retained bytes")
        let cache = NativeWorkspaceOfflineCache(directory: directory)
        await cache.configure(scope: scope, masterKey: masterKey)
        let document = ProjectWorkspaceReadme(markdown: "# Private README\n![Logo](logo.png)", truncated: false,
            origin: "connected", sourceID: connected.id, sourceSessionID: connected.sessionID, sourceKeyEpoch: connected.keyEpoch)
        try await cache.retainProjectReadme(document, projectID: project.id, binding: binding, scope: scope)
        let image = ProjectsWorkspacePreviewFixture.readmeImageData
        try await cache.retainProjectReadmeImage(image, source: "logo.png", document: document,
            projectID: project.id, binding: binding, scope: scope)
        // A complete metadata refresh must not erase the independently retained README.
        let refresh = try await cache.beginRefresh(namespace: "projects", scope: scope)
        try await cache.commit(namespace: "projects", responses: [:], scope: scope, revision: refresh)
        let reopened = NativeWorkspaceOfflineCache(directory: directory)
        await reopened.configure(scope: scope, masterKey: masterKey)
        let restored = try await reopened.projectReadme(projectID: project.id, binding: binding, scope: scope)
        XCTAssertEqual(restored?.markdown, document.markdown)
        XCTAssertTrue(restored?.images.isEmpty == true, "Metadata reopen must not materialize original images")
        let restoredImage = try await reopened.projectReadmeImage(source: "logo.png", document: document,
            projectID: project.id, binding: binding, scope: scope)
        XCTAssertEqual(restoredImage, image)
        XCTAssertNil(restored?.document.sourceSessionID, "Device retention must never preserve live request authority")
        let files = FileManager.default.enumerator(at: directory, includingPropertiesForKeys: nil)!.allObjects.compactMap { $0 as? URL }
        for file in files where file.pathExtension == "aesgcm" {
            let bytes = try Data(contentsOf: file)
            XCTAssertNil(bytes.range(of: Data(document.markdown.utf8)))
            XCTAssertNil(bytes.range(of: image))
        }
        let rotated = ProjectWorkspaceSource(id: connected.id, kind: connected.kind, name: connected.name,
            metadata: [:], capabilities: ["read"], status: "connected", sessionID: "replacement", keyEpoch: 4)
        let newBinding = try ProjectReadmeOfflineSnapshot.binding(project: project,
            contents: .init(folders: [], items: [], sources: [rotated]))
        let mismatched = try await reopened.projectReadme(projectID: project.id, binding: newBinding, scope: scope)
        XCTAssertFalse(try XCTUnwrap(mismatched).isCompatible(with: .init(folders: [], items: [], sources: [rotated])),
                       "A known changed source key epoch must reject the old private README")
        let offline = ProjectWorkspaceSource(id: connected.id, kind: connected.kind, name: connected.name,
            metadata: [:], capabilities: ["read"], status: "offline", sessionID: nil, keyEpoch: nil)
        XCTAssertTrue(try XCTUnwrap(restored).isCompatible(with: .init(folders: [], items: [], sources: [offline])),
                      "Offline sources omit epoch without proving revocation")
        let other = NativeWorkspaceOfflineScope(accountID: "another-owner", server: scope.server,
            teamID: scope.teamID, accountGeneration: UUID(), teamEpoch: 2)
        await reopened.configure(scope: other, masterKey: masterKey)
        do { _ = try await reopened.projectReadme(projectID: project.id, binding: binding, scope: scope); XCTFail("Old account read") }
        catch is CancellationError { }
        let foreign = try await reopened.projectReadme(projectID: project.id, binding: binding, scope: other)
        XCTAssertNil(foreign)
    }

    // contract-test: supporting surface=gui.apple assertions=apple-workspaces.offline-complete,apple-workspaces.isolation
    func testReadmeImageBudgetAndChangedDocumentPreserveOnlyCompatibleBytes() async throws {
        let directory = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        defer { try? FileManager.default.removeItem(at: directory) }
        let scope = NativeWorkspaceOfflineScope(accountID: "owner", server: "https://example.invalid",
            teamID: nil, accountGeneration: UUID(), teamEpoch: 0)
        let cache = NativeWorkspaceOfflineCache(directory: directory)
        await cache.configure(scope: scope, masterKey: SymmetricKey(size: .bits256))
        let document = ProjectWorkspaceReadme(markdown: "First", truncated: false, origin: "stored")
        try await cache.retainProjectReadme(document, projectID: "p", binding: "metadata", scope: scope)
        for index in 0..<12 {
            try await cache.retainProjectReadmeImage(Data([UInt8(index)]), source: "image-\(index)",
                document: document, projectID: "p", binding: "metadata", scope: scope)
        }
        do {
            try await cache.retainProjectReadmeImage(Data(repeating: 1, count: 2 * 1_024 * 1_024 + 1),
                source: "image-0", document: document, projectID: "p", binding: "metadata", scope: scope)
            XCTFail("Oversized images must be rejected")
        } catch { }
        let bounded = try await cache.projectReadme(projectID: "p", binding: "metadata", scope: scope)
        XCTAssertTrue(bounded?.images.isEmpty == true)
        for index in 0..<12 {
            let bytes = try await cache.projectReadmeImage(source: "image-\(index)", document: document,
                projectID: "p", binding: "metadata", scope: scope)
            XCTAssertEqual(bytes, Data([UInt8(index)]), "Every eligible image, including those after eight, reopens independently")
        }
        let gate = WorkspaceOfflineGETGate()
        let cancelled = Task {
            _ = await gate.fetch()
            try await cache.retainProjectReadme(ProjectWorkspaceReadme(markdown: "Cancelled replacement", truncated: false, origin: "stored"),
                projectID: "p", binding: "metadata", scope: scope)
        }
        await gate.waitUntilStarted()
        cancelled.cancel()
        await gate.finish()
        do { try await cancelled.value; XCTFail("Cancelled README writes must fail") }
        catch is CancellationError { }
        let preserved = try await cache.projectReadme(projectID: "p", binding: "metadata", scope: scope)
        XCTAssertEqual(preserved?.markdown, "First")
        let preservedLastImage = try await cache.projectReadmeImage(source: "image-11", document: document,
            projectID: "p", binding: "metadata", scope: scope)
        XCTAssertEqual(preservedLastImage, Data([11]))
        let changed = ProjectWorkspaceReadme(markdown: "Changed", truncated: false, origin: "stored")
        try await cache.retainProjectReadme(changed, projectID: "p", binding: "metadata", scope: scope)
        try await cache.retainProjectReadmeImage(Data([9]), source: "stale-image", document: document,
            projectID: "p", binding: "metadata", scope: scope)
        let replaced = try await cache.projectReadme(projectID: "p", binding: "metadata", scope: scope)
        XCTAssertEqual(replaced?.markdown, "Changed")
        XCTAssertEqual(replaced?.images.count, 0, "Late images cannot attach to a replacement README")
    }

    // contract-test: supporting surface=gui.apple assertions=apple-workspaces.offline-complete,apple-workspaces.local-first,apple-workspaces.isolation
    func testLegacyReadmeImageMigrationFailurePreservesReadableBytesThenRetries() async throws {
        let directory = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        defer { try? FileManager.default.removeItem(at: directory) }
        let scope = maintenanceScope()
        let cache = NativeWorkspaceOfflineCache(directory: directory)
        let key = SymmetricKey(size: .bits256)
        await cache.configure(scope: scope, masterKey: key)
        let legacy = ProjectReadmeOfflineSnapshot(binding: "metadata", markdown: "![Logo](logo.png)", truncated: false,
            origin: "stored", sourceID: nil, sourceKeyEpoch: nil, images: ["logo.png": Data([1, 2, 3])])
        try await cache.retain(namespace: "project-readme:p", path: "document", data: JSONEncoder().encode(legacy), scope: scope)
        let imageRoot = directory.appendingPathComponent(scope.directoryID).appendingPathComponent("readme-images")
        try Data([0]).write(to: imageRoot) // Force the new object directory creation to fail.
        let read = try await cache.projectReadmeImage(source: "logo.png", document: legacy.document,
            projectID: "p", binding: "metadata", scope: scope)
        XCTAssertEqual(read, Data([1, 2, 3]))
        let unchangedData = try await cache.read(namespace: "project-readme:p", path: "document", scope: scope)
        let unchanged = try XCTUnwrap(unchangedData)
        XCTAssertEqual(try JSONDecoder().decode(ProjectReadmeOfflineSnapshot.self, from: unchanged).images, legacy.images,
                       "A failed migration must preserve the complete legacy envelope")
        try FileManager.default.removeItem(at: imageRoot)
        let migrated = try await cache.projectReadmeImage(source: "logo.png", document: legacy.document,
            projectID: "p", binding: "metadata", scope: scope)
        XCTAssertEqual(migrated, read)
        let compact = try await cache.read(namespace: "project-readme:p", path: "document", scope: scope)
        let compactData = try XCTUnwrap(compact)
        XCTAssertTrue(try JSONDecoder().decode(ProjectReadmeOfflineSnapshot.self, from: compactData).images.isEmpty)
        let reopened = NativeWorkspaceOfflineCache(directory: directory)
        await reopened.configure(scope: scope, masterKey: key)
        let restored = try await reopened.projectReadmeImage(source: "logo.png", document: legacy.document,
            projectID: "p", binding: "metadata", scope: scope)
        XCTAssertEqual(restored, read)
    }

    // contract-test: supporting surface=gui.apple assertions=apple-workspaces.offline-complete,apple-workspaces.local-first,apple-workspaces.isolation
    func testLegacyReadmeCompactionRetriesObjectHitAfterSecondWriteFailureAndReopen() async throws {
        let directory = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        defer { try? FileManager.default.removeItem(at: directory) }
        let scope = maintenanceScope()
        let key = SymmetricKey(size: .bits256)
        let fault = ReadmeMetadataWriteFault()
        let cache = NativeWorkspaceOfflineCache(directory: directory, writeCiphertext: { data, url in try fault.write(data, to: url) })
        await cache.configure(scope: scope, masterKey: key)
        let legacy = ProjectReadmeOfflineSnapshot(binding: "metadata", markdown: "![Logo](logo.png)", truncated: false,
            origin: "stored", sourceID: nil, sourceKeyEpoch: nil, images: ["logo.png": Data([1, 2, 3])])
        try await cache.retain(namespace: "project-readme:p", path: "document", data: JSONEncoder().encode(legacy), scope: scope)
        fault.setFailingMetadata(true)
        let migrated = try await cache.projectReadmeImage(source: "logo.png", document: legacy.document,
            projectID: "p", binding: "metadata", scope: scope)
        XCTAssertEqual(migrated, legacy.images["logo.png"])
        XCTAssertEqual(fault.imageWrites, 1, "The independent object write must succeed before the injected metadata failure")
        XCTAssertEqual(fault.failedMetadataWrites, 1)
        let retained = try await cache.read(namespace: "project-readme:p", path: "document", scope: scope)
        XCTAssertEqual(try JSONDecoder().decode(ProjectReadmeOfflineSnapshot.self, from: XCTUnwrap(retained)).images, legacy.images)
        let reopened = NativeWorkspaceOfflineCache(directory: directory, writeCiphertext: { data, url in try fault.write(data, to: url) })
        await reopened.configure(scope: scope, masterKey: key)
        let stillReadable = try await reopened.projectReadmeImage(source: "logo.png", document: legacy.document,
            projectID: "p", binding: "metadata", scope: scope)
        XCTAssertEqual(stillReadable, migrated, "An object hit remains readable while compaction still fails")
        XCTAssertEqual(fault.imageWrites, 1, "An existing image must not be rewritten to retry metadata")
        XCTAssertEqual(fault.failedMetadataWrites, 2, "Reopening an object hit must retry the failed second write")
        fault.setFailingMetadata(false)
        let recovered = try await reopened.projectReadmeImage(source: "logo.png", document: legacy.document,
            projectID: "p", binding: "metadata", scope: scope)
        XCTAssertEqual(recovered, migrated)
        let compacted = try await reopened.read(namespace: "project-readme:p", path: "document", scope: scope)
        XCTAssertTrue(try JSONDecoder().decode(ProjectReadmeOfflineSnapshot.self, from: XCTUnwrap(compacted)).images.isEmpty)
        XCTAssertEqual(fault.imageWrites, 1)
    }

    // contract-test: supporting surface=gui.apple assertions=apple-workspaces.maintenance,apple-workspaces.local-first
    func testReadmeImageViewportResidencyBoundsEagerParagraphListAndTableRows() {
        let viewport = CGRect(x: 0, y: 0, width: 390, height: 844)
        // These rows are all mounted, as in one large paragraph/list/Grid.
        let rows = (0..<100).map { CGRect(x: 0, y: CGFloat($0) * 200, width: 350, height: 180) }
        let initiallyVisible = rows.indices.filter { ProjectReadmeImageResidency.isVisible(frame: rows[$0], viewport: viewport) }
        XCTAssertEqual(initiallyVisible, [0, 1, 2, 3, 4])
        XCTAssertFalse(ProjectReadmeImageResidency.isVisible(frame: rows[99], viewport: viewport))
        let afterScroll = rows.map { $0.offsetBy(dx: 0, dy: -19_800) }
        let visibleAfterScroll = afterScroll.indices.filter { ProjectReadmeImageResidency.isVisible(frame: afterScroll[$0], viewport: viewport) }
        XCTAssertEqual(visibleAfterScroll, [99], "The last image is eligible on entry without retaining earlier eager rows")
        XCTAssertFalse(ProjectReadmeImageResidency.isVisible(frame: afterScroll[0], viewport: viewport))
        let tableViewport = ProjectReadmeImageResidency.clipped(viewport, to: CGRect(x: 20, y: 20, width: 250, height: 500))
        XCTAssertFalse(ProjectReadmeImageResidency.isVisible(frame: CGRect(x: 280, y: 30, width: 80, height: 80), viewport: tableViewport),
                       "A cell inside the window but outside a narrower horizontal table clip cannot retain pixels")
        XCTAssertTrue(ProjectReadmeImageResidency.isVisible(frame: CGRect(x: 30, y: 30, width: 80, height: 80), viewport: tableViewport))
        XCTAssertFalse(ProjectReadmeImageResidency.isVisible(frame: rows[0], viewport: .zero))
        XCTAssertFalse(ProjectReadmeImageResidency.isVisible(frame: rows[0], viewport: .infinite))
    }

    // contract-test: supporting surface=gui.apple assertions=apple-workspaces.offline-complete,apple-workspaces.isolation
    func testAllReadmeImageObjectsReopenWithinScopeAndRejectLateOldDocumentWrites() async throws {
        let directory = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        defer { try? FileManager.default.removeItem(at: directory) }
        let scope = maintenanceScope()
        let key = SymmetricKey(size: .bits256)
        let cache = NativeWorkspaceOfflineCache(directory: directory)
        await cache.configure(scope: scope, masterKey: key)
        let old = ProjectWorkspaceReadme(markdown: "Old", truncated: false, origin: "stored")
        let current = ProjectWorkspaceReadme(markdown: "Current", truncated: false, origin: "connected", sourceID: "host", sourceKeyEpoch: 2)
        try await cache.retainProjectReadme(old, projectID: "p", binding: "metadata", scope: scope)
        try await cache.retainProjectReadmeImage(Data([1]), source: "old.png", document: old, projectID: "p", binding: "metadata", scope: scope)
        try await cache.retainProjectReadme(current, projectID: "p", binding: "metadata", scope: scope)
        for index in 0..<12 {
            try await cache.retainProjectReadmeImage(Data([UInt8(index)]), source: "image-\(index).png", document: current,
                projectID: "p", binding: "metadata", scope: scope)
        }
        try await cache.retainProjectReadmeImage(Data([99]), source: "image-11.png", document: old,
            projectID: "p", binding: "metadata", scope: scope)
        let reopened = NativeWorkspaceOfflineCache(directory: directory)
        await reopened.configure(scope: scope, masterKey: key)
        for index in 0..<12 {
            let bytes = try await reopened.projectReadmeImage(source: "image-\(index).png", document: current,
                projectID: "p", binding: "metadata", scope: scope)
            XCTAssertEqual(bytes, Data([UInt8(index)]))
        }
        let stale = try await reopened.projectReadmeImage(source: "old.png", document: old, projectID: "p", binding: "metadata", scope: scope)
        XCTAssertNil(stale)
        let rotated = try await reopened.projectReadmeImage(source: "image-11.png", document: current, projectID: "p", binding: "rotated-project-key", scope: scope)
        XCTAssertNil(rotated)
        let imageRoot = directory.appendingPathComponent(scope.directoryID).appendingPathComponent("readme-images")
        let projectDirs = try FileManager.default.contentsOfDirectory(at: imageRoot, includingPropertiesForKeys: nil)
        XCTAssertEqual(projectDirs.count, 1)
        XCTAssertEqual(try FileManager.default.contentsOfDirectory(at: projectDirs[0], includingPropertiesForKeys: nil).count, 1,
                       "Successful replacement prunes the old document generation; a late old-image write cannot resurrect it")
        for foreign in [NativeWorkspaceOfflineScope(accountID: "other", server: scope.server, teamID: scope.teamID, accountGeneration: UUID(), teamEpoch: 0),
                        NativeWorkspaceOfflineScope(accountID: scope.accountID, server: "https://other.invalid", teamID: scope.teamID, accountGeneration: UUID(), teamEpoch: 0),
                        NativeWorkspaceOfflineScope(accountID: scope.accountID, server: scope.server, teamID: "other-team", accountGeneration: UUID(), teamEpoch: 1)] {
            await reopened.configure(scope: foreign, masterKey: key)
            let unavailable = try await reopened.projectReadmeImage(source: "image-11.png", document: current,
                projectID: "p", binding: "metadata", scope: foreign)
            XCTAssertNil(unavailable)
        }
        await reopened.configure(scope: scope, masterKey: key)
        try await reopened.clearProjectReadme(projectID: "p", scope: scope)
        let cleared = try await reopened.projectReadmeImage(source: "image-11.png", document: current, projectID: "p", binding: "metadata", scope: scope)
        XCTAssertNil(cleared)
        XCTAssertEqual(try FileManager.default.contentsOfDirectory(at: projectDirs[0], includingPropertiesForKeys: nil).count, 0)
    }

    // contract-test: supporting surface=gui.apple assertions=apple-workspaces.offline-complete,apple-workspaces.local-first,apple-workspaces.maintenance
    func testPartialAndOfflineReadmeMaintenancePreservesAllPreviouslyRetainedImages() async throws {
        let directory = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        defer { try? FileManager.default.removeItem(at: directory) }
        let scope = maintenanceScope()
        let cache = NativeWorkspaceOfflineCache(directory: directory)
        await cache.configure(scope: scope, masterKey: SymmetricKey(size: .bits256))
        let document = ProjectWorkspaceReadme(markdown: (0..<12).map { "![Image \($0)](image-\($0).png)" }.joined(separator: "\n\n"),
            truncated: false, origin: "stored")
        for id in ["partial", "offline"] {
            try await cache.retainProjectReadme(document, projectID: id, binding: "metadata", scope: scope)
            for index in 0..<12 {
                try await cache.retainProjectReadmeImage(Data([UInt8(index)]), source: "image-\(index).png", document: document,
                    projectID: id, binding: "metadata", scope: scope)
            }
        }
        var cleared = 0
        let complete = try await ProjectReadmeOfflineMaintenance.fill(projectIDs: ["partial", "offline"], load: { id in
            if id == "offline" { throw ProjectsWorkspaceError.sourceOffline }
            return document
        }, readImage: { _, _, source in
            if source == "image-11.png" { throw URLError(.networkConnectionLost) }
            return Data([42])
        }, save: { id, readme in
            try await cache.retainProjectReadme(readme, projectID: id, binding: "metadata", scope: scope)
        }, saveImage: { id, readme, source, bytes in
            try await cache.retainProjectReadmeImage(bytes, source: source, document: readme, projectID: id, binding: "metadata", scope: scope)
        }, clear: { _ in cleared += 1 }, validate: {})
        XCTAssertFalse(complete)
        XCTAssertEqual(cleared, 0)
        for id in ["partial", "offline"] {
            let last = try await cache.projectReadmeImage(source: "image-11.png", document: document,
                projectID: id, binding: "metadata", scope: scope)
            XCTAssertEqual(last, Data([11]), "A failed refresh after image eight and an offline host both preserve prior bounded bytes")
        }
    }

    // contract-test: supporting surface=gui.apple assertions=apple-workspaces.isolation,apple-workspaces.local-first
    func testReadmePresentationIdentityRejectsSameURLAfterProjectKeyAndAccountChanges() async throws {
        let service = ProjectsWorkspaceMockService()
        let project = makeProject(id: "same-project", name: "Project")
        service.listResult = [project]
        service.cachedContentsResult = .init(folders: [], items: [], sources: [])
        service.contentsError = URLError(.notConnectedToInternet)
        service.cachedReadmeResult = .init(binding: "fixture", markdown: "![Logo](same.png)", truncated: false,
            origin: "stored", sourceID: nil, sourceKeyEpoch: nil, images: [:])
        let store = ProjectsWorkspaceStore(service: service, validateFence: { _ in })
        await store.load(accountId: "account-a")
        await store.selectProject(project.id)
        guard case .ready(let document) = store.readme else { return XCTFail("Cached document required") }
        let original = store.readmePresentationIdentity(document)
        try await store.validateReadmePresentation(document, identity: original)
        XCTAssertEqual(store.readmePresentationIdentity(document), original, "Ordinary validation must keep row identity stable")
        service.listResult = [makeProject(id: project.id, name: project.name)] // Same URL and ID, different Project key.
        await store.load(accountId: "account-a")
        XCTAssertNotEqual(store.readmePresentationIdentity(document), original)
        do { try await store.validateReadmePresentation(document, identity: original); XCTFail("Old decoded pixels must reject a new Project key") }
        catch { guard case .accountChanged? = error as? ProjectsWorkspaceError else { return XCTFail("Expected presentation fence rejection") } }
        store.reset(accountId: "account-b")
        XCTAssertNotEqual(store.readmePresentationIdentity(document), original)
        do { try await store.validateReadmePresentation(document, identity: original); XCTFail("Old decoded pixels must reject a new account") }
        catch { guard case .accountChanged? = error as? ProjectsWorkspaceError else { return XCTFail("Expected presentation fence rejection") } }
    }

    // contract-test: supporting surface=gui.apple assertions=apple-workspaces.maintenance,apple-workspaces.isolation
    func testReadmeForegroundImageQueueSerializesEveryReferenceAndSkipsCancelledRows() async throws {
        let queue = ProjectReadmeImageLoadQueue()
        let gate = WorkspaceOfflineGETGate()
        var active = 0, maximumActive = 0, dispatched: [String] = []
        let first = Task { try await queue.load("first") { source in
            dispatched.append(source)
            active += 1; maximumActive = max(maximumActive, active)
            let bytes = await gate.fetch()
            active -= 1
            return bytes
        } }
        await gate.waitUntilStarted()
        let cancelled = Task { try await queue.load("cancelled") { source in
            dispatched.append(source)
            return Data([99])
        } }
        let remaining = (0..<12).map { index in Task { try await queue.load("image-\(index)") { source in
            dispatched.append(source)
            active += 1; maximumActive = max(maximumActive, active)
            await Task.yield()
            active -= 1
            return Data([UInt8(index)])
        } } }
        for _ in 0..<20 { await Task.yield() }
        XCTAssertEqual(dispatched, ["first"], "Visible rows must not fan out while an image read is suspended")
        cancelled.cancel()
        do { _ = try await cancelled.value; XCTFail("Cancelled queued rows must stop before a read") }
        catch is CancellationError { }
        await gate.finish()
        _ = try await first.value
        for (index, request) in remaining.enumerated() {
            let bytes = try await request.value
            XCTAssertEqual(bytes, Data([UInt8(index)]))
        }
        XCTAssertEqual(maximumActive, 1)
        XCTAssertEqual(dispatched.count, 13)
        XCTAssertFalse(dispatched.contains("cancelled"))
    }

    // contract-test: supporting surface=gui.apple assertions=apple-workspaces.local-first
    func testOfflineProjectContentsAndReadmeRenderWhenSettingsAreUncachedAndRefreshFails() async throws {
        let service = ProjectsWorkspaceMockService()
        let project = makeProject(id: "offline", name: "Offline")
        service.listResult = [project]
        service.cachedContentsResult = .init(folders: [
            .init(id: "folder", name: "Files", parentHash: nil, position: 0, createdAt: 1)
        ], items: [
            .init(id: "file", kind: "embed", targetID: "embed", name: "Report.pdf", metadata: [:], folderHash: nil, position: 0, createdAt: 1)
        ], sources: [])
        service.omitCachedSettings = true
        service.contentsError = URLError(.notConnectedToInternet)
        service.cachedReadmeResult = .init(binding: "fixture", markdown: "# Cached", truncated: false,
            origin: "stored", sourceID: nil, sourceKeyEpoch: nil, images: ["logo.png": ProjectsWorkspacePreviewFixture.readmeImageData])
        let store = ProjectsWorkspaceStore(service: service, validateFence: { _ in })
        await store.load(accountId: "owner")
        await store.selectProject(project.id)
        XCTAssertEqual(store.items.map(\.name), ["Report.pdf"])
        XCTAssertEqual(store.folders.map(\.name), ["Files"])
        XCTAssertFalse(store.isLoadingDetail)
        XCTAssertNil(store.errorMessage, "A transient refresh must preserve the readable offline workspace")
        guard case .ready(let document) = store.readme else { return XCTFail("Cached README must remain ready") }
        XCTAssertEqual(document.markdown, "# Cached")
        let image = try await store.readReadmeImage("logo.png", readme: document)
        XCTAssertEqual(image, ProjectsWorkspacePreviewFixture.readmeImageData)
    }

    // contract-test: supporting surface=gui.apple assertions=apple-workspaces.offline-complete,apple-workspaces.local-first,projects.files.connected-embed-previews,projects.access.explicit-context
    func testOfflineSourceBrowsesCachedUnexpandedFolderWithoutLoadingFileOrEmbedBodies() async throws {
        let service = ProjectsWorkspaceMockService()
        let project = makeProject(id: "cached-hierarchy", name: "Project")
        let offline = ProjectWorkspaceSource(id: "source", kind: "remote_folder", name: "Source", metadata: [:],
            capabilities: ["read"], status: "disconnected", sessionID: nil, keyEpoch: nil)
        let item = ProjectWorkspaceItem(id: "metadata", kind: "embed", targetID: "embed", name: "Report.pdf",
            metadata: ["embed_type": "pdf"], folderHash: nil, position: 0, createdAt: 1)
        service.listResult = [project]
        service.contentsResult = .init(folders: [], items: [item], sources: [offline])
        service.cachedRemoteDirectories = [
            ".": .init(entries: [ProjectOfflineMetadataEntry(ProjectRemoteEntry(path: "folder", kind: "directory", sizeBytes: nil, childFileCount: nil, childFolderCount: nil, childSummaryTruncated: false))], complete: true),
            "folder": .init(entries: [ProjectOfflineMetadataEntry(remoteEntry("folder/unopened.txt"))], complete: true)
        ]
        let store = ProjectsWorkspaceStore(service: service, listSourceRoot: { _, _, _ in
            XCTFail("Offline metadata browsing must not make a source request")
            throw ProjectsWorkspaceError.sourceOffline
        }, validateFence: { _ in })
        await store.load(accountId: "owner")
        await store.selectProject(project.id)
        await store.loadItemEmbedPreview(item)
        XCTAssertEqual(service.openLinkedEmbedReads, 0, "Thin entry metadata must not trigger full body preload")
        XCTAssertTrue(store.itemEmbedPreviews.isEmpty)
        await store.openRemoteSource(offline.id)
        XCTAssertTrue(store.remoteMetadataOnly)
        XCTAssertEqual(store.remoteEntries.map(\.path), ["folder"])
        await store.browseRemote(path: "folder")
        XCTAssertEqual(store.remoteEntries.map(\.path), ["folder/unopened.txt"])
        XCTAssertEqual(store.remotePath, "folder")
        XCTAssertNil(store.remoteError)
        await store.openRemoteFile(remoteEntry("folder/unopened.txt"))
        await store.downloadRemoteFile("folder/unopened.txt")
        await store.transferRemote(["folder/unopened.txt"], move: true, destinationPath: ".")
        XCTAssertNil(store.remoteText)
        XCTAssertNil(store.remoteDownloadURL)
        XCTAssertFalse(store.isSaving)
        XCTAssertEqual(service.openLinkedEmbedReads, 0)
        XCTAssertNil(store.sources.first?.sessionID, "Cached metadata cannot restore host authority")
    }

    // contract-test: supporting surface=gui.apple assertions=apple-workspaces.local-first,apple-workspaces.isolation,projects.access.explicit-context,projects.files.connected-embed-previews
    func testFreshContentsRestoreSourceAuthorityAndReadmeWhenSettingsRefreshFails() async throws {
        let service = ProjectsWorkspaceMockService()
        let project = makeProject(id: "partial-refresh", name: "Project")
        let connected = readmeSource("source")
        let disconnected = ProjectWorkspaceSource(id: connected.id, kind: connected.kind, name: connected.name,
            metadata: [:], capabilities: connected.capabilities, status: "disconnected", sessionID: nil, keyEpoch: connected.keyEpoch)
        service.listResult = [project]
        service.cachedContentsResult = .init(folders: [], items: [], sources: [disconnected])
        service.cachedSettingsResult = .init(writeMode: .alwaysAsk, selectionRequired: true,
            focusID: "retained-focus", focusInstruction: "Retained")
        service.settingsError = ProjectsWorkspaceError.invalidResponse
        service.contentsResult = .init(folders: [
            .init(id: "fresh-folder", name: "Fresh files", parentHash: nil, position: 0, createdAt: 1)
        ], items: [
            .init(id: "fresh-readme", kind: "embed", targetID: "readme", name: "README.md",
                  metadata: [:], folderHash: nil, position: 0, createdAt: 1)
        ], sources: [connected])
        service.storedFileResult = ["code": "# Fresh README"]
        let rootRead = expectation(description: "Fresh source root read")
        let store = ProjectsWorkspaceStore(service: service, listSourceRoot: { _, source, fence in
            XCTAssertEqual(fence.accountID, "owner")
            XCTAssertEqual(source, connected, "Only fresh metadata can restore live request authority")
            rootRead.fulfill()
            return .init(entries: [self.remoteEntry("fresh.txt")], omitted: 0, excluded: 0, nextCursor: nil)
        }, validateFence: { _ in })
        let readmeReady = expectation(description: "Fresh README published")
        let rootPreviewReady = expectation(description: "Fresh source root published")
        let readmeObservation = store.$readme.sink { state in
            if case .ready(let document) = state, document.markdown == "# Fresh README" { readmeReady.fulfill() }
        }
        let rootObservation = store.$sourceRootPreviews.sink { previews in
            if previews[connected.id]?.first?.path == "fresh.txt" { rootPreviewReady.fulfill() }
        }
        defer { readmeObservation.cancel(); rootObservation.cancel() }
        await store.load(accountId: "owner")
        await store.selectProject(project.id)
        await fulfillment(of: [rootRead, readmeReady, rootPreviewReady], timeout: 2)
        XCTAssertEqual(store.folders.map(\.id), ["fresh-folder"])
        XCTAssertEqual(store.items.map(\.id), ["fresh-readme"])
        XCTAssertEqual(store.sources, [connected])
        XCTAssertEqual(store.sourceRootPreviews[connected.id]?.map(\.path), ["fresh.txt"])
        XCTAssertEqual(store.settings?.writeMode, .alwaysAsk)
        XCTAssertEqual(store.settings?.focusID, "retained-focus")
        XCTAssertEqual(store.errorMessage, AppStrings.projectError(ProjectsWorkspaceError.invalidResponse))
        XCTAssertFalse(store.isLoadingDetail)
        guard case .ready(let document) = store.readme else { return XCTFail("Fresh contents must still discover the README") }
        XCTAssertEqual(document.markdown, "# Fresh README")
    }

    // contract-test: supporting surface=gui.apple assertions=apple-workspaces.local-first
    func testFreshSettingsPublishWhenContentsRefreshFailsAndKeepCachedReadme() async throws {
        let service = ProjectsWorkspaceMockService()
        let project = makeProject(id: "partial-settings", name: "Project")
        service.listResult = [project]
        service.cachedContentsResult = .init(folders: [
            .init(id: "retained-folder", name: "Retained", parentHash: nil, position: 0, createdAt: 1)
        ], items: [], sources: [])
        service.cachedReadmeResult = .init(binding: "fixture", markdown: "# Retained", truncated: false,
            origin: "stored", sourceID: nil, sourceKeyEpoch: nil, images: [:])
        service.contentsError = URLError(.notConnectedToInternet)
        service.settingsResult = .init(writeMode: .alwaysAsk, selectionRequired: true,
            focusID: "fresh-focus", focusInstruction: "Fresh")
        let store = ProjectsWorkspaceStore(service: service, validateFence: { _ in })
        await store.load(accountId: "owner")
        await store.selectProject(project.id)
        XCTAssertEqual(store.folders.map(\.id), ["retained-folder"])
        XCTAssertEqual(store.settings?.writeMode, .alwaysAsk)
        XCTAssertEqual(store.settings?.focusID, "fresh-focus")
        XCTAssertNil(store.errorMessage)
        XCTAssertFalse(store.isLoadingDetail)
        guard case .ready(let document) = store.readme else { return XCTFail("Retained README must remain readable") }
        XCTAssertEqual(document.markdown, "# Retained")
    }

    // contract-test: supporting surface=gui.apple assertions=apple-workspaces.local-first,apple-workspaces.isolation
    func testCancelledSettingsRefreshDoesNotShowErrorOrDiscardFreshContents() async throws {
        let service = ProjectsWorkspaceMockService()
        let project = makeProject(id: "cancelled-settings", name: "Project")
        service.listResult = [project]
        service.settingsError = CancellationError()
        service.contentsResult = .init(folders: [
            .init(id: "fresh", name: "Fresh", parentHash: nil, position: 0, createdAt: 1)
        ], items: [], sources: [])
        let store = ProjectsWorkspaceStore(service: service, validateFence: { _ in })
        await store.load(accountId: "owner")
        await store.selectProject(project.id)
        XCTAssertEqual(store.folders.map(\.id), ["fresh"])
        XCTAssertNil(store.errorMessage)
        XCTAssertFalse(store.isLoadingDetail)
    }

    // contract-test: supporting surface=gui.apple assertions=apple-workspaces.offline-complete,apple-workspaces.maintenance
    func testBackgroundReadmeFillVisitsEveryProjectAndAllSafeReferencedImages() async throws {
        var visited: [String] = [], saved: [String] = [], images: [String] = [], cleared: [String] = []
        let markdown = "# Overview\n\n```markdown\n![Literal](not-an-image.png)\n```\n\n" +
            (0..<12).map { "![Image \($0)](images/\($0).png)" }.joined(separator: "\n\n") +
            "\n\n![Duplicate](images/11.png)\n\n![Unsafe](../private.png)\n\n[Unrelated file](report.pdf)"
        let complete = try await ProjectReadmeOfflineMaintenance.fill(projectIDs: ["offline", "first", "empty", "last"], load: { id in
            visited.append(id)
            if id == "offline" { throw ProjectsWorkspaceError.sourceOffline }
            if id == "empty" { return nil }
            return .init(markdown: markdown, truncated: false, origin: "stored")
        }, readImage: { id, _, source in
            images.append(id + ":" + source)
            return Data([1, 2, 3])
        }, save: { id, _ in saved.append(id) }, saveImage: { _, _, _, _ in },
           clear: { cleared.append($0) }, validate: {})
        XCTAssertFalse(complete, "Unavailable Projects require a later maintenance retry")
        XCTAssertEqual(visited, ["offline", "first", "empty", "last"])
        XCTAssertEqual(saved, ["first", "last"], "One unavailable host cannot suppress another Project's cache")
        XCTAssertEqual(cleared, ["empty"], "Only authoritative empty reads reconcile retained overviews")
        let expected = ["first", "last"].flatMap { id in (0..<12).map { id + ":images/\($0).png" } }
        XCTAssertEqual(images, expected, "Deduplicate safe references, exclude code/unsafe/unrelated files, and retain references after eight")
    }

    // contract-test: supporting surface=gui.apple assertions=apple-workspaces.offline-complete,apple-workspaces.isolation,apple-workspaces.maintenance
    func testCancelledBackgroundReadmeFillCannotClearPreviouslyRetainedOverview() async throws {
        let directory = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        defer { try? FileManager.default.removeItem(at: directory) }
        let cache = NativeWorkspaceOfflineCache(directory: directory)
        let scope = NativeWorkspaceOfflineScope(accountID: "owner", server: "https://example.invalid",
            teamID: nil, accountGeneration: UUID(), teamEpoch: 0)
        await cache.configure(scope: scope, masterKey: SymmetricKey(size: .bits256))
        let document = ProjectWorkspaceReadme(markdown: "Previous complete README", truncated: false, origin: "stored")
        try await cache.retainProjectReadme(document, projectID: "p", binding: "metadata", scope: scope)
        for index in 0..<12 {
            try await cache.retainProjectReadmeImage(Data([UInt8(index)]), source: "image-\(index).png", document: document,
                projectID: "p", binding: "metadata", scope: scope)
        }
        let gate = WorkspaceOfflineGETGate()
        var clearCount = 0
        let maintenance = Task {
            try await ProjectReadmeOfflineMaintenance.fill(projectIDs: ["p"], load: { _ in
                _ = await gate.fetch()
                return nil
            }, readImage: { _, _, _ in Data() }, save: { _, _ in }, saveImage: { _, _, _, _ in },
               clear: { _ in clearCount += 1 }, validate: {})
        }
        await gate.waitUntilStarted()
        maintenance.cancel()
        await gate.finish()
        do { _ = try await maintenance.value; XCTFail("Cancellation must interrupt maintenance") }
        catch is CancellationError { }
        XCTAssertEqual(clearCount, 0)
        let retained = try await cache.projectReadme(projectID: "p", binding: "metadata", scope: scope)
        XCTAssertEqual(retained?.markdown, document.markdown)
        let retainedImage = try await cache.projectReadmeImage(source: "image-11.png", document: document,
            projectID: "p", binding: "metadata", scope: scope)
        XCTAssertEqual(retainedImage, Data([11]), "Cancellation must preserve images after the obsolete eight-image cutoff")
    }

    // contract-test: supporting surface=gui.apple assertions=apple-workspaces.offline-complete,apple-workspaces.maintenance
    func testBackgroundReadmeFillRejectsOversizedBodiesAndImagesWithoutStoppingHealthyProjects() async throws {
        var saved: [String] = [], savedImages: [String] = []
        let complete = try await ProjectReadmeOfflineMaintenance.fill(projectIDs: ["large-body", "large-image", "healthy"], load: { id in
            .init(markdown: id == "large-body" ? String(repeating: "x", count: 2 * 1_024 * 1_024 + 1) : "![Image](logo.png)",
                  truncated: false, origin: "stored")
        }, readImage: { id, _, _ in
            id == "large-image" ? Data(repeating: 1, count: 2 * 1_024 * 1_024 + 1) : Data([1])
        }, save: { id, _ in saved.append(id) }, saveImage: { id, _, _, _ in savedImages.append(id) }, clear: { _ in }, validate: {})
        XCTAssertFalse(complete)
        XCTAssertEqual(saved, ["large-image", "healthy"])
        XCTAssertEqual(savedImages, ["healthy"])
    }

}

@MainActor
private final class ProjectsWorkspaceMockService: ProjectsWorkspaceServing {
    var organizationReceipts: [String] = []
    var contentsByProject: [String: ProjectWorkspaceContents] = [:]
    var failsCopy = false
    var allowsDelete = false
    var createdProjectResult: ProjectWorkspaceProject?
    var updatedProjectResult: ProjectWorkspaceProject?
    var suspendsOrganization = false
    var organizationContinuation: CheckedContinuation<ProjectWorkspaceProject, Never>?
    func createChatOrganization(chats: [Chat], fence: ProjectsWorkspaceFence, teamID: String?) async throws -> ProjectWorkspaceProject {
        await withCheckedContinuation { organizationContinuation = $0 }
    }
    func removeChatLink(chatID: String, project: ProjectWorkspaceProject, fence: ProjectsWorkspaceFence) async throws {
        organizationReceipts.append("remove:\(project.id):\(chatID)")
    }
    var listResult: [ProjectWorkspaceProject]?
    var cachedListResult: [ProjectWorkspaceProject]?
    var cachedContentsResult: ProjectWorkspaceContents?
    var omitCachedSettings = false
    var cachedSettingsResult: ProjectWorkspaceSettings?
    var settingsResult: ProjectWorkspaceSettings?
    var settingsError: Error?
    var openLinkedEmbedReads = 0
    var cachedRemoteDirectories: [String: ProjectOfflineDirectory] = [:]
    func cachedRemoteDirectory(path: String, project: ProjectWorkspaceProject, source: ProjectWorkspaceSource,
                               fence: ProjectsWorkspaceFence) async throws -> ProjectOfflineDirectory? { cachedRemoteDirectories[path] }
    var contentsError: Error?
    var cachedReadmeResult: ProjectReadmeOfflineSnapshot?
    func cachedReadme(project: ProjectWorkspaceProject, contents: ProjectWorkspaceContents, fence: ProjectsWorkspaceFence) async throws -> ProjectReadmeOfflineSnapshot? { cachedReadmeResult }
    func cachedReadmeImage(source: String, document: ProjectWorkspaceReadme, project: ProjectWorkspaceProject, contents: ProjectWorkspaceContents, fence: ProjectsWorkspaceFence) async throws -> Data? {
        guard let cachedReadmeResult, cachedReadmeResult.markdown == document.markdown,
              cachedReadmeResult.truncated == document.truncated, cachedReadmeResult.origin == document.origin,
              cachedReadmeResult.sourceID == document.sourceID, cachedReadmeResult.sourceKeyEpoch == document.sourceKeyEpoch else { return nil }
        return cachedReadmeResult.images[source]
    }
    func cachedProjects(accountID: String, teamID: String?) async throws -> [ProjectWorkspaceProject]? { cachedListResult }
    func cachedContents(project: ProjectWorkspaceProject, fence: ProjectsWorkspaceFence) async throws -> ProjectWorkspaceContents? { cachedContentsResult }
    func cachedSettings(project: ProjectWorkspaceProject, fence: ProjectsWorkspaceFence) async throws -> ProjectWorkspaceSettings? {
        if let cachedSettingsResult { return cachedSettingsResult }
        return cachedContentsResult == nil || omitCachedSettings ? nil : ProjectWorkspaceSettings(writeMode: .applyAndShow, selectionRequired: false, focusID: nil, focusInstruction: nil)
    }
    var suspendContents = false
    var contentsResult: ProjectWorkspaceContents?
    var sourcesResult: [ProjectWorkspaceSource]?
    var suspendSources = false
    var sourcesContinuation: CheckedContinuation<[ProjectWorkspaceSource], Never>?
    var listContinuation: CheckedContinuation<[ProjectWorkspaceProject], Never>?
    var contentsContinuation: CheckedContinuation<ProjectWorkspaceContents, Never>?
    var embedContinuation: CheckedContinuation<EmbedRecord, Never>?
    var suspendStoredFile = false
    var storedFileResult: [String: Any]?
    var storedFileContinuation: CheckedContinuation<[String: Any], Never>?

    func finishList(with projects: [ProjectWorkspaceProject]) {
        listContinuation?.resume(returning: projects)
        listContinuation = nil
    }

    func finishContents(with contents: ProjectWorkspaceContents) {
        contentsContinuation?.resume(returning: contents)
        contentsContinuation = nil
    }

    func finishEmbed(with record: EmbedRecord) {
        embedContinuation?.resume(returning: record)
        embedContinuation = nil
    }

    func listProjects(accountID: String, teamID: String?) async throws -> [ProjectWorkspaceProject] {
        if let listResult { return listResult }
        return await withCheckedContinuation { listContinuation = $0 }
    }

    var navigationFailures: Set<String> = []
    var failsWorkspaceContents = false
    var workspaceContentsReads = 0
    func chatNavigationContents(project: ProjectWorkspaceProject, fence: ProjectsWorkspaceFence) async throws -> ProjectWorkspaceContents {
        if navigationFailures.contains(project.id) { throw ProjectsWorkspaceError.invalidResponse }
        let value = contentsByProject[project.id] ?? contentsResult ?? .init(folders: [], items: [], sources: [])
        return .init(folders: value.folders, items: value.items.filter { $0.kind == "chat" }, sources: [])
    }

    func contents(project: ProjectWorkspaceProject, fence: ProjectsWorkspaceFence) async throws -> ProjectWorkspaceContents {
        if let contentsError { throw contentsError }
        workspaceContentsReads += 1
        if failsWorkspaceContents { throw ProjectsWorkspaceError.sourceOffline }
        if let specific = contentsByProject[project.id] { return specific }
        if let contentsResult { return contentsResult }
        if !suspendContents { return ProjectWorkspaceContents(folders: [], items: [], sources: []) }
        return await withCheckedContinuation { contentsContinuation = $0 }
    }

    func listSources(project: ProjectWorkspaceProject, fence: ProjectsWorkspaceFence) async throws -> [ProjectWorkspaceSource] {
        if suspendSources { return await withCheckedContinuation { sourcesContinuation = $0 } }
        return sourcesResult ?? contentsResult?.sources ?? []
    }

    func settings(project: ProjectWorkspaceProject, fence: ProjectsWorkspaceFence) async throws -> ProjectWorkspaceSettings {
        if let settingsError { throw settingsError }
        if let settingsResult { return settingsResult }
        return ProjectWorkspaceSettings(writeMode: .applyAndShow, selectionRequired: false,
            focusID: nil, focusInstruction: nil)
    }

    func createProject(name: String, writeMode: ProjectWorkspaceWriteMode, fence: ProjectsWorkspaceFence,
                       teamID: String?) async throws -> ProjectWorkspaceProject {
        guard let createdProjectResult else { throw ProjectsWorkspaceError.invalidContext }
        return createdProjectResult
    }
    func updateProject(_ project: ProjectWorkspaceProject, name: String?, description: String?,
                       fence: ProjectsWorkspaceFence) async throws -> ProjectWorkspaceProject {
        guard let updatedProjectResult else { throw ProjectsWorkspaceError.invalidContext }
        return updatedProjectResult
    }
    func createFolder(_ name: String, project: ProjectWorkspaceProject, parentID: String?,
                      fence: ProjectsWorkspaceFence) async throws { throw ProjectsWorkspaceError.invalidContext }
    func moveItem(_ itemID: String, project: ProjectWorkspaceProject, folderID: String?,
                  fence: ProjectsWorkspaceFence) async throws { throw ProjectsWorkspaceError.invalidContext }
    func copyItem(_ item: ProjectWorkspaceItem, project: ProjectWorkspaceProject,
                  folderID: String?, fence: ProjectsWorkspaceFence) async throws {
        organizationReceipts.append("copy:\(project.id):\(item.targetID)")
        if failsCopy { throw ProjectsWorkspaceError.invalidContext }
    }
    func updateWriteMode(_ mode: ProjectWorkspaceWriteMode, project: ProjectWorkspaceProject,
                         fence: ProjectsWorkspaceFence) async throws -> ProjectWorkspaceSettings { throw ProjectsWorkspaceError.invalidContext }
    func activateFocus(project: ProjectWorkspaceProject, chatID: String, focusID: String,
                       instruction: String, fence: ProjectsWorkspaceFence) async throws { throw ProjectsWorkspaceError.invalidContext }
    func deleteProject(_ project: ProjectWorkspaceProject, fence: ProjectsWorkspaceFence) async throws {
        guard allowsDelete else { throw ProjectsWorkspaceError.invalidContext }
    }
    func readStoredFile(_ item: ProjectWorkspaceItem, project: ProjectWorkspaceProject,
                        fence: ProjectsWorkspaceFence) async throws -> [String: Any] {
        if let storedFileResult { return storedFileResult }
        guard suspendStoredFile else { throw ProjectsWorkspaceError.invalidContext }
        return await withCheckedContinuation { storedFileContinuation = $0 }
    }
    func openLinkedEmbed(_ item: ProjectWorkspaceItem, project: ProjectWorkspaceProject,
                         fence: ProjectsWorkspaceFence) async throws -> EmbedRecord {
        openLinkedEmbedReads += 1
        return await withCheckedContinuation { embedContinuation = $0 }
    }
}

@MainActor
private final class HostedFilesMockAdapter: ProjectHostedFileAdapter {
    let projectID = "fixture-project"
    let projectKey = SymmetricKey(data: Data(repeating: 7, count: 32))
    let chatKey = SymmetricKey(data: Data(repeating: 8, count: 32))
    let teamID: String? = nil
    let files: [ProjectHostedFile]
    let contents: [String: String]
    let protectedPaths: [String]
    var reads: [String] = []

    init(files: [ProjectHostedFile], contents: [String: String], privatePaths: [String]) {
        self.files = files
        self.contents = contents
        self.protectedPaths = privatePaths
    }

    func listFiles() async throws -> [ProjectHostedFile] { files }
    func readHead(embedID: String) async throws -> ProjectHostedHead {
        reads.append(embedID)
        guard let content = contents[embedID] else { throw ProjectHostedFileError(code: "file_not_found") }
        return ProjectHostedHead(embedKey: projectKey, content: ["code": content],
            revision: 1, hasInitialHistory: true)
    }
    func privatePaths() async throws -> [String] { protectedPaths }
    func receipt(embedID: String, job: ProjectFileJob, digest: String) async throws -> [String: Any]? {
        XCTFail("A read-only policy test must not request a revision receipt")
        return nil
    }
    func commit(_ payload: [String: Any]) async throws -> [String: Any] {
        XCTFail("A read-only policy test must not commit a revision")
        throw ProjectHostedFileError(code: "invalid_request")
    }
}

private actor WorkspaceOfflineGETGate {
    private(set) var calls = 0
    private var waiter: CheckedContinuation<Data, Never>?
    private var started: [CheckedContinuation<Void, Never>] = []
    private var finished = false
    func fetch() async -> Data {
        calls += 1
        if finished { return Data("response".utf8) }
        return await withCheckedContinuation { continuation in
            waiter = continuation
            for wait in started { wait.resume() }
            started.removeAll()
        }
    }
    func waitUntilStarted() async {
        if calls > 0 { return }
        await withCheckedContinuation { started.append($0) }
    }
    func finish() { finished = true; waiter?.resume(returning: Data("response".utf8)); waiter = nil }
}

/// Inject failure at the real encrypted metadata write, after the independent
/// image object has reached disk. Locking keeps the writer closure Sendable.
private final class ReadmeMetadataWriteFault: @unchecked Sendable {
    private let lock = NSLock()
    private var failingMetadata = false
    private var imageWriteCount = 0
    private var failedMetadataWriteCount = 0

    var imageWrites: Int { lock.lock(); defer { lock.unlock() }; return imageWriteCount }
    var failedMetadataWrites: Int { lock.lock(); defer { lock.unlock() }; return failedMetadataWriteCount }

    func setFailingMetadata(_ value: Bool) {
        lock.lock(); defer { lock.unlock() }
        failingMetadata = value
    }

    func write(_ data: Data, to url: URL) throws {
        let image = url.pathComponents.contains("readme-images")
        lock.lock()
        let fail = failingMetadata && !image
        if image { imageWriteCount += 1 }
        if fail { failedMetadataWriteCount += 1 }
        lock.unlock()
        if fail { throw CocoaError(.fileWriteNoPermission) }
        try data.write(to: url, options: .atomic)
    }
}
