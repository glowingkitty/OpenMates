import CryptoKit
import XCTest
@testable import OpenMates

@MainActor
final class ProjectsWorkspaceTests: XCTestCase {
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

    // contract-test: supporting surface=gui.apple assertions=projects.access.explicit-context,projects.files.connected-embed-previews
    func testSourceRefreshRecoversPresenceAndClosesDisconnectedBrowser() async {
        let service = ProjectsWorkspaceMockService()
        let project = makeProject(id: "source-project", name: "Project")
        func source(_ status: String, session: String?) -> ProjectWorkspaceSource {
            ProjectWorkspaceSource(id: "source", kind: "local_git_repository", name: "Source",
                metadata: [:], capabilities: [], status: status, sessionID: session, keyEpoch: session == nil ? nil : 1)
        }
        service.listResult = [project]
        service.contentsResult = ProjectWorkspaceContents(folders: [], items: [],
            sources: [source("offline", session: nil)])
        let store = ProjectsWorkspaceStore(service: service, validateFence: { _ in })
        await store.load(accountId: "account-a")
        await store.selectProject(project.id)
        await store.openRemoteSource("source")
        XCTAssertNil(store.activeRemoteSourceID, "An offline source cannot open a browser")

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

    func contents(project: ProjectWorkspaceProject, fence: ProjectsWorkspaceFence) async throws -> ProjectWorkspaceContents {
        if let contentsResult { return contentsResult }
        if !suspendContents { return ProjectWorkspaceContents(folders: [], items: [], sources: []) }
        return await withCheckedContinuation { contentsContinuation = $0 }
    }

    func listSources(project: ProjectWorkspaceProject, fence: ProjectsWorkspaceFence) async throws -> [ProjectWorkspaceSource] {
        if suspendSources { return await withCheckedContinuation { sourcesContinuation = $0 } }
        return sourcesResult ?? contentsResult?.sources ?? []
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
                        fence: ProjectsWorkspaceFence) async throws -> [String: Any] {
        if let storedFileResult { return storedFileResult }
        guard suspendStoredFile else { throw ProjectsWorkspaceError.invalidContext }
        return await withCheckedContinuation { storedFileContinuation = $0 }
    }
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
