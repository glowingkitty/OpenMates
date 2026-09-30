import CryptoKit
import XCTest
@testable import OpenMates

@MainActor
final class ProjectsWorkspaceTests: XCTestCase {
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
        guard case .unavailable = incomplete else { return XCTFail("An incomplete listing cannot prove README absence") }
        let complete = await ProjectsWorkspaceStore.loadConnectedReadme(
            sources: [readmeSource("empty")], list: { _ in
                ProjectRemoteDirectory(entries: [], omitted: 0, excluded: 0, nextCursor: nil)
            }, read: { _, _ in throw ProjectsWorkspaceError.invalidContext })
        guard case .empty = complete else { return XCTFail("Complete source listing without README is empty") }
    }

    private func readmeSource(_ id: String, status: String = "connected") -> ProjectWorkspaceSource {
        ProjectWorkspaceSource(id: id, kind: "remote_folder", name: "Source", metadata: [:],
            capabilities: ["read"], status: status, sessionID: "source-session", keyEpoch: 1)
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
}

@MainActor
private final class ProjectsWorkspaceMockService: ProjectsWorkspaceServing {
    var listResult: [ProjectWorkspaceProject]?
    var suspendContents = false
    var contentsResult: ProjectWorkspaceContents?
    var listContinuation: CheckedContinuation<[ProjectWorkspaceProject], Never>?
    var contentsContinuation: CheckedContinuation<ProjectWorkspaceContents, Never>?
    var embedContinuation: CheckedContinuation<EmbedRecord, Never>?

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

    func contents(project: ProjectWorkspaceProject, fence: ProjectsWorkspaceFence) async throws -> ProjectWorkspaceContents {
        if let contentsResult { return contentsResult }
        if !suspendContents { return ProjectWorkspaceContents(folders: [], items: [], sources: []) }
        return await withCheckedContinuation { contentsContinuation = $0 }
    }

    func settings(project: ProjectWorkspaceProject, fence: ProjectsWorkspaceFence) async throws -> ProjectWorkspaceSettings {
        ProjectWorkspaceSettings(writeMode: .applyAndShow, selectionRequired: false,
            focusID: nil, focusInstruction: nil)
    }

    func createProject(name: String, writeMode: ProjectWorkspaceWriteMode, fence: ProjectsWorkspaceFence,
                       teamID: String?) async throws -> ProjectWorkspaceProject { throw ProjectsWorkspaceError.invalidContext }
    func updateProject(_ project: ProjectWorkspaceProject, name: String?, description: String?,
                       fence: ProjectsWorkspaceFence) async throws -> ProjectWorkspaceProject { throw ProjectsWorkspaceError.invalidContext }
    func createFolder(_ name: String, project: ProjectWorkspaceProject, parentID: String?,
                      fence: ProjectsWorkspaceFence) async throws { throw ProjectsWorkspaceError.invalidContext }
    func moveItem(_ itemID: String, project: ProjectWorkspaceProject, folderID: String?,
                  fence: ProjectsWorkspaceFence) async throws { throw ProjectsWorkspaceError.invalidContext }
    func copyItem(_ item: ProjectWorkspaceItem, project: ProjectWorkspaceProject,
                  folderID: String?, fence: ProjectsWorkspaceFence) async throws {
        throw ProjectsWorkspaceError.invalidContext
    }
    func updateWriteMode(_ mode: ProjectWorkspaceWriteMode, project: ProjectWorkspaceProject,
                         fence: ProjectsWorkspaceFence) async throws -> ProjectWorkspaceSettings { throw ProjectsWorkspaceError.invalidContext }
    func activateFocus(project: ProjectWorkspaceProject, chatID: String, focusID: String,
                       instruction: String, fence: ProjectsWorkspaceFence) async throws { throw ProjectsWorkspaceError.invalidContext }
    func deleteProject(_ project: ProjectWorkspaceProject, fence: ProjectsWorkspaceFence) async throws { throw ProjectsWorkspaceError.invalidContext }
    func readStoredFile(_ item: ProjectWorkspaceItem, project: ProjectWorkspaceProject,
                        fence: ProjectsWorkspaceFence) async throws -> [String: Any] { throw ProjectsWorkspaceError.invalidContext }
    func openLinkedEmbed(_ item: ProjectWorkspaceItem, project: ProjectWorkspaceProject,
                         fence: ProjectsWorkspaceFence) async throws -> EmbedRecord {
        await withCheckedContinuation { embedContinuation = $0 }
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
