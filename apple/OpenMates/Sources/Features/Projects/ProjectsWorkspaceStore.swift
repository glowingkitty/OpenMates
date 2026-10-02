// Web source: frontend/packages/ui/src/services/projectReadme.ts, projectService.ts
// Specification: specifications/features/projects/specification.yml
// Assertions: projects.access.explicit-context, projects.files.search-scoped, projects.files.connected-embed-previews
import CryptoKit
import Combine
import Foundation

enum ProjectWorkspaceSearchEntry: Identifiable {
    case folder(ProjectWorkspaceFolder)
    case item(ProjectWorkspaceItem)
    case virtualFolder(path: String, name: String)
    case remote(sourceID: String, entry: ProjectRemoteEntry)

    var id: String {
        switch self {
        case .folder(let folder): "folder:\(folder.id)"
        case .item(let item): "item:\(item.id)"
        case .virtualFolder(let path, _): "virtual:\(path)"
        case .remote(let sourceID, let entry): "remote:\(sourceID):\(entry.path)"
        }
    }

    var name: String {
        switch self {
        case .folder(let folder): folder.name
        case .item(let item): item.name
        case .virtualFolder(_, let name): name
        case .remote(_, let entry): entry.name
        }
    }
}

@MainActor
final class ProjectsWorkspaceStore: ObservableObject {
    enum ReadmeState {
        case loading
        case ready(ProjectWorkspaceReadme)
        case empty
        case unavailable
        case failed
    }

    @Published private(set) var projects: [ProjectWorkspaceProject] = []
    @Published private(set) var selectedProjectID: String?
    @Published private(set) var folders: [ProjectWorkspaceFolder] = []
    @Published private(set) var items: [ProjectWorkspaceItem] = []
    @Published private(set) var sources: [ProjectWorkspaceSource] = []
    @Published private(set) var settings: ProjectWorkspaceSettings?
    @Published private(set) var readme: ReadmeState = .loading
    @Published private(set) var activeRemoteSourceID: String?
    @Published private(set) var remotePath = "."
    @Published private(set) var remoteEntries: [ProjectRemoteEntry] = []
    @Published private(set) var remotePagination = ProjectRemotePagination()
    @Published private(set) var remoteText: ProjectRemoteText?
    @Published private(set) var remoteEmbed: EmbedRecord?
    @Published private(set) var remoteFilePreviews: [String: EmbedRecord] = [:]
    @Published private(set) var remoteDownloadURL: URL?
    @Published private(set) var remoteDownloadProgress: (Int, Int)?
    @Published private(set) var remoteError: String?
    @Published private(set) var isLoadingRemote = false
    @Published private(set) var sourceRootPreviews: [String: [ProjectRemoteEntry]] = [:]
    @Published private(set) var itemEmbedPreviews: [String: EmbedRecord] = [:]
    @Published private(set) var searchResults: [ProjectWorkspaceSearchEntry] = []
    @Published private(set) var searchActive = false
    @Published private(set) var isSearching = false
    @Published private(set) var searchOmitted = 0
    @Published private(set) var searchError: String?
    @Published private(set) var isLoading = false
    @Published private(set) var isLoadingDetail = false
    @Published private(set) var isSaving = false
    @Published private(set) var errorMessage: String?

    private let service: any ProjectsWorkspaceServing
    private let remoteClient: ProjectRemoteSourceClient
    private let listSourceRoot: @MainActor (ProjectWorkspaceProject, ProjectWorkspaceSource, ProjectsWorkspaceFence) async throws -> ProjectRemoteDirectory
    private let uploadService: ProjectUploadService
    private let validateFence: @MainActor (ProjectsWorkspaceFence) async throws -> Void
    private var accountID: String?
    private var teamID: String?
    private var generation = UUID()
    private var searchGeneration = UUID()
    private var remoteGeneration = UUID()
    private var downloadGeneration = UUID()
    private var sourceGeneration = UUID()
    private var sourceRefreshRequest: UUID?
    private var loadingEmbedPreviewIDs: [String: UUID] = [:]
    #if DEBUG
    private var previewVariant: String?
    /// Account-free fixture transport; nil always uses the encrypted source client.
    var debugOriginalDownload: (@MainActor (String, @escaping (Int, Int) -> Void) async throws -> URL)?
    #endif

    init(service: any ProjectsWorkspaceServing = ProjectsWorkspaceService(),
         remoteClient: ProjectRemoteSourceClient = ProjectRemoteSourceClient(),
         uploadService: ProjectUploadService = ProjectUploadService(),
         listSourceRoot: (@MainActor (ProjectWorkspaceProject, ProjectWorkspaceSource, ProjectsWorkspaceFence) async throws -> ProjectRemoteDirectory)? = nil,
         validateFence: @escaping @MainActor (ProjectsWorkspaceFence) async throws -> Void = { try await $0.check() }) {
        self.service = service
        self.remoteClient = remoteClient
        self.listSourceRoot = listSourceRoot ?? { project, source, fence in
            try await remoteClient.list(project: project, source: source, path: ".", maxEntries: 12, fence: fence)
        }
        self.uploadService = uploadService
        self.validateFence = validateFence
    }

    var selectedProject: ProjectWorkspaceProject? {
        projects.first { $0.id == selectedProjectID }
    }

    var loadedAccountID: String? { accountID }

    func load(accountId: String) async {
        await load(accountId: accountId, teamId: nil)
    }

    func load(accountId: String, teamId: String?) async {
        if accountID != accountId || teamID != teamId {
            reset(accountId: accountId)
            teamID = teamId
        }
        let requestGeneration = generation
        isLoading = true
        errorMessage = nil
        do {
            let values = try await service.listProjects(accountID: accountId, teamID: teamId)
            guard requestGeneration == generation, accountID == accountId else { return }
            projects = values.sorted { $0.updatedAt > $1.updatedAt }
            if let selectedProjectID, !projects.contains(where: { $0.id == selectedProjectID }) {
                self.selectedProjectID = nil
                clearDetail()
            }
        } catch {
            guard requestGeneration == generation else { return }
            errorMessage = AppStrings.projectError(error)
        }
        if requestGeneration == generation { isLoading = false }
    }

    func reset(accountId: String?) {
        generation = UUID()
        cancelSearch()
        #if DEBUG
        previewVariant = nil
        debugOriginalDownload = nil
        #endif
        accountID = accountId
        teamID = nil
        projects = []
        selectedProjectID = nil
        clearDetail()
        clearRemoteDownload()
        isLoading = false
        isSaving = false
        errorMessage = nil
    }

    func selectProject(_ id: String?) async {
        cancelSearch()
        #if DEBUG
        if let previewVariant {
            generation = UUID()
            selectedProjectID = id
            if id == nil { clearDetail() }
            else { installPreviewDetail(variant: previewVariant) }
            return
        }
        #endif
        generation = UUID()
        selectedProjectID = id
        clearDetail()
        guard id != nil else { return }
        await reloadSelected()
    }

    func reloadSelected() async {
        #if DEBUG
        if let previewVariant {
            installPreviewDetail(variant: previewVariant)
            return
        }
        #endif
        guard let project = selectedProject, let accountID else { return }
        let requestGeneration = generation
        let fence = ProjectsWorkspaceFence(accountID: accountID)
        isLoadingDetail = true
        readme = .loading
        sourceGeneration = UUID()
        let sourceRequest = sourceGeneration
        errorMessage = nil
        do {
            let contents = try await service.contents(project: project, fence: fence)
            let settings = try await service.settings(project: project, fence: fence)
            guard requestGeneration == generation, selectedProjectID == project.id else { return }
            try await validateFence(fence)
            folders = contents.folders
            items = contents.items
            itemEmbedPreviews = [:]
            loadingEmbedPreviewIDs = [:]
            sources = contents.sources
            self.settings = settings
            // README discovery may wait for a remote host. Its independent
            // overview state must not hold Files or Tasks behind that read.
            isLoadingDetail = false
            Task { [weak self] in
                guard let self else { return }
                let loadedReadme = await self.loadReadme(project: project, contents: contents, fence: fence)
                guard requestGeneration == self.generation, sourceRequest == self.sourceGeneration,
                      self.selectedProjectID == project.id else { return }
                guard (try? await self.validateFence(fence)) != nil,
                      requestGeneration == self.generation, sourceRequest == self.sourceGeneration,
                      self.selectedProjectID == project.id else { return }
                self.readme = loadedReadme
            }
            Task { [weak self] in
                await self?.prefetchSourceRoots(project: project, sources: contents.sources,
                    fence: fence, generation: requestGeneration, sourceGeneration: sourceRequest)
            }
        } catch {
            guard requestGeneration == generation else { return }
            errorMessage = AppStrings.projectError(error)
            readme = .failed
        }
        if requestGeneration == generation { isLoadingDetail = false }
    }

    /// Web refreshes source presence every 15 seconds. A retained workspace
    /// must recover when its encrypted source host reconnects, and discard
    /// previews from a disconnected or replaced source session.
    func refreshSourceStatus() async {
        guard !isLoadingDetail, sourceRefreshRequest == nil,
              let project = selectedProject, let accountID else { return }
        let request = UUID()
        sourceRefreshRequest = request
        defer { if sourceRefreshRequest == request { sourceRefreshRequest = nil } }
        let requestGeneration = generation
        let previousSourceGeneration = sourceGeneration
        let fence = ProjectsWorkspaceFence(accountID: accountID)
        do {
            let refreshed = try await service.listSources(project: project, fence: fence)
            try Task.checkCancellation()
            try await validateFence(fence)
            guard requestGeneration == generation, previousSourceGeneration == sourceGeneration,
                  selectedProjectID == project.id,
                  sources != refreshed else { return }
            sourceGeneration = UUID()
            let sourceRequest = sourceGeneration
            let changedIDs = Set(sources.filter { old in
                !refreshed.contains(old)
            }.map(\.id))
            sourceRootPreviews = sourceRootPreviews.filter { !changedIDs.contains($0.key) }
            if let activeRemoteSourceID, changedIDs.contains(activeRemoteSourceID) {
                closeRemoteSource()
            }
            cancelSearch()
            sources = refreshed
            let contents = ProjectWorkspaceContents(folders: folders, items: items, sources: refreshed)
            readme = .loading
            Task { [weak self] in
                guard let self else { return }
                let loaded = await self.loadReadme(project: project, contents: contents, fence: fence)
                guard (try? await self.validateFence(fence)) != nil,
                      requestGeneration == self.generation, sourceRequest == self.sourceGeneration,
                      self.selectedProjectID == project.id else { return }
                self.readme = loaded
            }
            Task { [weak self] in
                await self?.prefetchSourceRoots(project: project, sources: refreshed, fence: fence,
                    generation: requestGeneration, sourceGeneration: sourceRequest)
            }
        } catch {
            // A transient status failure preserves the last confirmed source
            // state. It cannot establish that the source device is offline.
        }
    }

    func cancelSearch() {
        searchGeneration = UUID()
        searchResults = []
        searchActive = false
        isSearching = false
        searchOmitted = 0
        searchError = nil
    }

    func searchFiles(_ query: String, prioritySourceID: String?, priorityPath: String?) async {
        let needle = query.trimmingCharacters(in: .whitespacesAndNewlines)
        cancelSearch()
        guard !needle.isEmpty, needle.utf8.count <= 200,
              let project = selectedProject else { return }
        let requestGeneration = generation
        let searchRequest = searchGeneration
        searchActive = true
        isSearching = true
        var found: [String: ProjectWorkspaceSearchEntry] = [:]
        for folder in folders where folder.name.localizedCaseInsensitiveContains(needle) {
            let entry = ProjectWorkspaceSearchEntry.folder(folder)
            found[entry.id] = entry
        }
        for item in items {
            if item.name.localizedCaseInsensitiveContains(needle) {
                let entry = ProjectWorkspaceSearchEntry.item(item)
                found[entry.id] = entry
            }
            guard item.metadata["source"] == "hosted_project_file",
                  let path = item.filePath else { continue }
            let parts = path.split(separator: "/").map(String.init)
            guard parts.count > 1, parts.count <= 64 else { continue }
            for end in 1..<parts.count where parts[end - 1].localizedCaseInsensitiveContains(needle) {
                let entry = ProjectWorkspaceSearchEntry.virtualFolder(
                    path: parts.prefix(end).joined(separator: "/"), name: parts[end - 1])
                found[entry.id] = entry
            }
        }
        searchResults = found.values.sorted { $0.name.localizedStandardCompare($1.name) == .orderedAscending }
        #if DEBUG
        if let previewVariant {
            let entries = ProjectsWorkspacePreviewFixture.state(for: previewVariant).remoteEntries
            for source in sources where source.status == "connected" {
                for entry in entries where entry.name.localizedCaseInsensitiveContains(needle) {
                    let result = ProjectWorkspaceSearchEntry.remote(sourceID: source.id, entry: entry)
                    found[result.id] = result
                }
            }
            searchResults = found.values.sorted { $0.name.localizedStandardCompare($1.name) == .orderedAscending }
            isSearching = false
            return
        }
        #endif
        guard let accountID else { isSearching = false; return }
        let fence = ProjectsWorkspaceFence(accountID: accountID)
        for source in sources where source.status == "connected" {
            guard searchRequest == searchGeneration,
                  requestGeneration == generation, selectedProjectID == project.id,
                  !Task.isCancelled else { return }
            do {
                let result = try await remoteClient.searchFiles(project: project, source: source,
                    query: needle, priorityPath: source.id == prioritySourceID ? priorityPath : nil,
                    fence: fence)
                guard searchRequest == searchGeneration,
                      requestGeneration == generation, selectedProjectID == project.id,
                      !Task.isCancelled else { return }
                try await validateFence(fence)
                guard searchRequest == searchGeneration,
                      requestGeneration == generation, selectedProjectID == project.id,
                      !Task.isCancelled else { return }
                searchOmitted += result.omitted
                for match in result.matches {
                    let entry = ProjectWorkspaceSearchEntry.remote(sourceID: source.id, entry: match)
                    found[entry.id] = entry
                }
                searchResults = found.values.sorted {
                    $0.name.localizedStandardCompare($1.name) == .orderedAscending
                }
            } catch {
                guard searchRequest == searchGeneration,
                      requestGeneration == generation, selectedProjectID == project.id else { return }
                guard (try? await fence.check()) != nil else { cancelSearch(); return }
                guard searchRequest == searchGeneration,
                      requestGeneration == generation, selectedProjectID == project.id else { return }
                searchError = AppStrings.projectSearchPartialFailure
            }
        }
        if searchRequest == searchGeneration { isSearching = false }
    }

    func createProject(name: String, writeMode: ProjectWorkspaceWriteMode) async {
        guard let accountID, !isSaving else { return }
        let requestGeneration = generation
        let fence = ProjectsWorkspaceFence(accountID: accountID)
        isSaving = true
        errorMessage = nil
        do {
            let project = try await service.createProject(name: name, writeMode: writeMode, fence: fence, teamID: teamID)
            guard requestGeneration == generation else { return }
            try await fence.check()
            projects.insert(project, at: 0)
            isSaving = false
            await selectProject(project.id)
            return
        } catch {
            if requestGeneration == generation { errorMessage = AppStrings.projectError(error) }
        }
        if requestGeneration == generation { isSaving = false }
    }

    func updateSelectedProject(name: String? = nil, description: String? = nil) async {
        guard let project = selectedProject, let accountID, !isSaving else { return }
        let requestGeneration = generation
        let fence = ProjectsWorkspaceFence(accountID: accountID)
        isSaving = true
        do {
            let updated = try await service.updateProject(project, name: name, description: description, fence: fence)
            guard requestGeneration == generation else { return }
            try await fence.check()
            if let index = projects.firstIndex(where: { $0.id == project.id }) { projects[index] = updated }
        } catch {
            if requestGeneration == generation { errorMessage = AppStrings.projectError(error) }
        }
        if requestGeneration == generation { isSaving = false }
    }

    func createFolder(name: String, parentID: String? = nil) async {
        guard let project = selectedProject, let accountID, !isSaving else { return }
        let requestGeneration = generation
        let fence = ProjectsWorkspaceFence(accountID: accountID)
        isSaving = true
        do {
            try await service.createFolder(name, project: project, parentID: parentID, fence: fence)
            guard requestGeneration == generation else { return }
            try await reloadSelected()
        } catch {
            if requestGeneration == generation { errorMessage = AppStrings.projectError(error) }
        }
        if requestGeneration == generation { isSaving = false }
    }

    func moveItem(_ itemID: String, to folderID: String?) async {
        guard let project = selectedProject, let accountID, !isSaving else { return }
        let requestGeneration = generation
        let fence = ProjectsWorkspaceFence(accountID: accountID)
        isSaving = true
        do {
            try await service.moveItem(itemID, project: project, folderID: folderID, fence: fence)
            guard requestGeneration == generation else { return }
            try await reloadSelected()
        } catch {
            if requestGeneration == generation { errorMessage = AppStrings.projectError(error) }
        }
        if requestGeneration == generation { isSaving = false }
    }

    func updateWriteMode(_ mode: ProjectWorkspaceWriteMode) async {
        guard let project = selectedProject, let accountID, !isSaving else { return }
        let requestGeneration = generation
        let fence = ProjectsWorkspaceFence(accountID: accountID)
        isSaving = true
        do {
            let updated = try await service.updateWriteMode(mode, project: project, fence: fence)
            guard requestGeneration == generation else { return }
            try await fence.check()
            settings = updated
        } catch {
            if requestGeneration == generation { errorMessage = AppStrings.projectError(error) }
        }
        if requestGeneration == generation { isSaving = false }
    }

    func activateDefaultFocus(for chatID: String) async throws {
        guard let project = selectedProject, let settings, let accountID,
              let focusID = settings.focusID, let instruction = settings.focusInstruction else {
            throw ProjectsWorkspaceError.invalidContext
        }
        let fence = ProjectsWorkspaceFence(accountID: accountID)
        try await service.activateFocus(project: project, chatID: chatID, focusID: focusID,
            instruction: instruction, fence: fence)
    }

    func deleteSelectedProject() async {
        guard let project = selectedProject, let accountID, !isSaving else { return }
        let requestGeneration = generation
        let fence = ProjectsWorkspaceFence(accountID: accountID)
        isSaving = true
        do {
            try await service.deleteProject(project, fence: fence)
            guard requestGeneration == generation else { return }
            try await fence.check()
            projects.removeAll { $0.id == project.id }
            isSaving = false
            await selectProject(nil)
            return
        } catch {
            if requestGeneration == generation { errorMessage = AppStrings.projectError(error) }
        }
        if requestGeneration == generation { isSaving = false }
    }

    func readStoredFile(_ item: ProjectWorkspaceItem) async throws -> [String: Any] {
        guard let project = selectedProject, let accountID else { throw ProjectsWorkspaceError.invalidContext }
        let requestGeneration = generation
        let fence = ProjectsWorkspaceFence(accountID: accountID)
        let content = try await service.readStoredFile(item, project: project, fence: fence)
        guard requestGeneration == generation, selectedProjectID == project.id else {
            throw ProjectsWorkspaceError.accountChanged
        }
        try await fence.check()
        return content
    }

    /// Resolve a linked hosted file only for the currently selected Project.
    /// The returned record is transient; its decrypted data stays out of disk
    /// persistence and can be passed to EmbedFullscreenContainer(chatId: nil).
    func openLinkedEmbed(item: ProjectWorkspaceItem) async throws -> EmbedRecord {
        guard let project = selectedProject, let accountID,
              item.kind == "embed", items.contains(where: { $0.id == item.id && $0.targetID == item.targetID }) else {
            throw ProjectsWorkspaceError.invalidContext
        }
        let requestGeneration = generation
        let fence = ProjectsWorkspaceFence(accountID: accountID)
        let record = try await service.openLinkedEmbed(item, project: project, fence: fence)
        guard requestGeneration == generation, selectedProjectID == project.id,
              items.contains(where: { $0.id == item.id && $0.targetID == item.targetID }) else {
            throw ProjectsWorkspaceError.accountChanged
        }
        try await validateFence(fence)
        return record
    }

    /// Hydrate only cards that SwiftUI has placed on screen. Plaintext remains
    /// in this scoped in-memory store and is discarded on Project/account reset.
    func loadItemEmbedPreview(_ item: ProjectWorkspaceItem) async {
        guard item.kind == "embed", itemEmbedPreviews[item.id] == nil,
              loadingEmbedPreviewIDs[item.id] == nil, selectedProjectID != nil else { return }
        #if DEBUG
        if previewVariant != nil {
            if let type = item.metadata["embed_type"],
               let skill = DevEmbedPreviewFixtures.skill(forRegistryKey: type) {
                itemEmbedPreviews[item.id] = skill.primaryEmbed
            }
            return
        }
        #endif
        guard let project = selectedProject, let accountID,
              items.contains(where: { $0.id == item.id && $0.targetID == item.targetID }) else { return }
        let requestGeneration = generation
        let fence = ProjectsWorkspaceFence(accountID: accountID)
        loadingEmbedPreviewIDs[item.id] = requestGeneration
        defer {
            if loadingEmbedPreviewIDs[item.id] == requestGeneration {
                loadingEmbedPreviewIDs.removeValue(forKey: item.id)
            }
        }
        do {
            let record = try await service.openLinkedEmbed(item, project: project, fence: fence)
            guard requestGeneration == generation, selectedProjectID == project.id,
                  items.contains(where: { $0.id == item.id && $0.targetID == item.targetID }) else { return }
            try await validateFence(fence)
            guard requestGeneration == generation, selectedProjectID == project.id else { return }
            itemEmbedPreviews[item.id] = record
        } catch {
            // The encrypted card remains a metadata-only fallback. Open will
            // revalidate the key and present the user's normal error path.
        }
    }

    func uploadFile(url: URL, folderID: String?) async {
        guard let project = selectedProject, let accountID, !isSaving,
              project.permissions.manageOwnItems || project.permissions.manageAnyItems else { return }
        let requestGeneration = generation
        let fence = ProjectsWorkspaceFence(accountID: accountID)
        isSaving = true
        errorMessage = nil
        do {
            try await uploadService.upload(url: url, project: project,
                folderID: folderID, fence: fence)
            guard requestGeneration == generation, selectedProjectID == project.id else { return }
            try await fence.check()
            await reloadSelected()
        } catch {
            if requestGeneration == generation { errorMessage = AppStrings.projectError(error) }
        }
        if requestGeneration == generation { isSaving = false }
    }

    func transferStored(_ selected: [ProjectWorkspaceItem], move: Bool,
                        destinationFolderID: String?) async {
        guard let project = selectedProject, let accountID, !isSaving,
              !selected.isEmpty, selected.count <= 100,
              project.permissions.manageOwnItems || project.permissions.manageAnyItems else { return }
        let requestGeneration = generation
        let fence = ProjectsWorkspaceFence(accountID: accountID)
        isSaving = true
        errorMessage = nil
        do {
            for item in selected {
                try await fence.check()
                guard generation == requestGeneration,
                      selectedProjectID == project.id else { throw ProjectsWorkspaceError.accountChanged }
                if move {
                    try await service.moveItem(item.id, project: project,
                        folderID: destinationFolderID, fence: fence)
                } else {
                    try await service.copyItem(item, project: project,
                        folderID: destinationFolderID, fence: fence)
                }
            }
        } catch {
            if requestGeneration == generation { errorMessage = AppStrings.projectError(error) }
        }
        if requestGeneration == generation {
            isSaving = false
            await reloadSelected()
        }
    }

    func transferRemote(_ paths: [String], move: Bool,
                        destinationPath: String) async {
        guard let project = selectedProject, let accountID, !isSaving,
              let sourceID = activeRemoteSourceID,
              let source = sources.first(where: { $0.id == sourceID }),
              !paths.isEmpty else { return }
        let requestGeneration = generation
        let fence = ProjectsWorkspaceFence(accountID: accountID)
        isSaving = true
        remoteError = nil
        do {
            for offset in stride(from: 0, to: paths.count, by: 20) {
                try await fence.check()
                guard generation == requestGeneration, activeRemoteSourceID == sourceID,
                      selectedProjectID == project.id else { throw ProjectsWorkspaceError.accountChanged }
                let batch = Array(paths[offset..<min(offset + 20, paths.count)])
                let result = try await remoteClient.transfer(project: project,
                    source: source, paths: batch, destinationPath: destinationPath,
                    move: move, fence: fence)
                if result.failedCount > 0 { throw ProjectsWorkspaceError.invalidResponse }
            }
        } catch {
            if requestGeneration == generation { remoteError = AppStrings.projectError(error) }
        }
        if requestGeneration == generation {
            isSaving = false
            await browseRemote(path: destinationPath)
        }
    }

    func openRemoteSource(_ sourceID: String) async {
        guard sources.contains(where: { $0.id == sourceID && $0.status == "connected" }) else { return }
        clearRemoteDownload()
        remoteGeneration = UUID()
        activeRemoteSourceID = sourceID
        remoteFilePreviews = [:]
        remotePath = "."
        remotePagination = ProjectRemotePagination()
        remoteEntries = []
        remoteText = nil
        remoteEmbed = nil
        await browseRemote(path: ".")
    }

    func closeRemoteSource() {
        remoteGeneration = UUID()
        clearRemoteDownload()
        activeRemoteSourceID = nil
        remoteFilePreviews = [:]
        remotePath = "."
        remotePagination = ProjectRemotePagination()
        remoteEntries = []
        remoteText = nil
        remoteEmbed = nil
        remoteError = nil
        isLoadingRemote = false
    }

    func showRemotePage(_ index: Int) async {
        guard !isLoadingRemote, remotePagination.canShow(index) else { return }
        await browseRemote(path: remotePath, pageIndex: index)
    }

    func downloadRemoteFile(_ path: String) async {
        guard !isLoadingRemote, let project = selectedProject,
              let sourceID = activeRemoteSourceID,
              let source = sources.first(where: { $0.id == sourceID }) else { return }
        let fence = accountID.map { ProjectsWorkspaceFence(accountID: $0) }
        #if DEBUG
        guard fence != nil || (previewVariant != nil && debugOriginalDownload != nil) else { return }
        #else
        guard fence != nil else { return }
        #endif
        let requestGeneration = generation
        clearRemoteDownload()
        let downloadRequest = downloadGeneration
        isLoadingRemote = true
        remoteError = nil
        var downloadedURL: URL?
        do {
            if let fence { try await validateFence(fence) }
            guard requestGeneration == generation, downloadRequest == downloadGeneration,
                  selectedProjectID == project.id, activeRemoteSourceID == sourceID else { return }
            let progress: (Int, Int) -> Void = { [weak self] downloaded, total in
                    Task { @MainActor in
                        guard self?.generation == requestGeneration,
                              self?.downloadGeneration == downloadRequest,
                              self?.activeRemoteSourceID == sourceID else { return }
                        self?.remoteDownloadProgress = (downloaded, total)
                    }
                }
            let url: URL
            #if DEBUG
            if let debugOriginalDownload {
                url = try await debugOriginalDownload(path, progress)
            } else {
                guard let requestFence = fence else { throw ProjectsWorkspaceError.invalidContext }
                url = try await remoteClient.downloadOriginal(project: project, source: source,
                    path: path, fence: requestFence, progress: progress)
            }
            #else
            guard let requestFence = fence else { throw ProjectsWorkspaceError.invalidContext }
            url = try await remoteClient.downloadOriginal(project: project, source: source,
                path: path, fence: requestFence, progress: progress)
            #endif
            downloadedURL = url
            guard requestGeneration == generation, downloadRequest == downloadGeneration,
                  selectedProjectID == project.id, activeRemoteSourceID == sourceID else {
                try? FileManager.default.removeItem(at: url.deletingLastPathComponent())
                return
            }
            if let fence { try await validateFence(fence) }
            guard requestGeneration == generation, downloadRequest == downloadGeneration,
                  selectedProjectID == project.id, activeRemoteSourceID == sourceID else {
                try? FileManager.default.removeItem(at: url.deletingLastPathComponent())
                return
            }
            remoteDownloadURL = url
        } catch {
            if let downloadedURL { try? FileManager.default.removeItem(at: downloadedURL.deletingLastPathComponent()) }
            if requestGeneration == generation && downloadRequest == downloadGeneration { remoteError = AppStrings.projectError(error) }
        }
        if requestGeneration == generation && downloadRequest == downloadGeneration { isLoadingRemote = false }
    }

    func clearRemoteDownload() {
        downloadGeneration = UUID()
        if let url = remoteDownloadURL {
            try? FileManager.default.removeItem(at: url.deletingLastPathComponent())
        }
        remoteDownloadURL = nil
        remoteDownloadProgress = nil
    }

    func clearRemoteText() {
        clearRemoteDownload()
        remoteGeneration = UUID()
        isLoadingRemote = false
        remoteText = nil
        remoteEmbed = nil
        remoteError = nil
    }

    func browseRemote(path: String, pageIndex: Int = 0) async {
        let sameDirectory = path == remotePath
        if !sameDirectory || pageIndex == 0 { remotePagination = ProjectRemotePagination() }
        guard pageIndex == 0 || (sameDirectory && remotePagination.canShow(pageIndex)) else { return }
        remoteGeneration = UUID()
        let remoteRequest = remoteGeneration
        remoteError = nil
        remoteText = nil
        remoteEmbed = nil
        if remotePagination.showLegacyPage(pageIndex) {
            remoteEntries = remotePagination.entries
            return
        }
        #if DEBUG
        if let previewVariant {
            let entries = ProjectsWorkspacePreviewFixture.state(for: previewVariant).remoteEntries
                .filter { entry in
                    let parts = entry.path.split(separator: "/")
                    return (parts.count > 1 ? parts.dropLast().joined(separator: "/") : ".") == path
                }.sorted { $0.path.localizedStandardCompare($1.path) == .orderedAscending }
            // Replay a complete legacy response through production pagination.
            remotePagination.install(ProjectRemoteDirectory(entries: entries, omitted: 0,
                excluded: 0, nextCursor: nil), page: pageIndex)
            remotePath = path
            remoteEntries = remotePagination.entries
            return
        }
        #endif
        guard let project = selectedProject, let accountID,
              let source = sources.first(where: { $0.id == activeRemoteSourceID }) else { return }
        let requestGeneration = generation
        let fence = ProjectsWorkspaceFence(accountID: accountID)
        isLoadingRemote = true
        do {
            let directory = try await remoteClient.list(project: project, source: source,
                path: path, cursor: remotePagination.cursor(for: pageIndex), fence: fence)
            guard requestGeneration == generation, remoteRequest == remoteGeneration,
                  activeRemoteSourceID == source.id else { return }
            try await validateFence(fence)
            guard requestGeneration == generation, remoteRequest == remoteGeneration,
                  activeRemoteSourceID == source.id else { return }
            remotePath = path
            remotePagination.install(directory, page: pageIndex)
            remoteEntries = remotePagination.entries
            if remotePagination.omitted > 0 && remotePagination.nextCursor == nil {
                remoteError = AppStrings.projectRemoteLimited
            }
        } catch {
            if requestGeneration == generation && remoteRequest == remoteGeneration {
                remoteError = AppStrings.projectError(error)
            }
        }
        if requestGeneration == generation && remoteRequest == remoteGeneration { isLoadingRemote = false }
    }

    func openRemoteText(_ path: String) async {
        remoteGeneration = UUID()
        let remoteRequest = remoteGeneration
        remoteText = nil
        remoteEmbed = nil
        remoteError = nil
        #if DEBUG
        if let previewVariant {
            remoteText = previewVariant == "truncatedConnectedSource"
                ? ProjectsWorkspacePreviewFixture.truncatedText
                : ProjectRemoteText(content: path == "README.md"
                ? "# OpenMates\n\nA private workspace for planning and research.\n"
                : "// Preview of \(path)\n", truncated: false,
                sizeBytes: 64, lineCount: 3, expectedBase: nil)
            if let text = remoteText, let source = sources.first(where: { $0.id == activeRemoteSourceID }) {
                remoteEmbed = ProjectRemotePreviewPolicy.embed(sourceID: source.id, sourceLabel: source.name, path: path, text: text)
                cacheRemotePreview(path: path, source: source, text: text)
            }
            return
        }
        #endif
        guard let project = selectedProject, let accountID,
              let source = sources.first(where: { $0.id == activeRemoteSourceID }) else { return }
        let requestGeneration = generation
        let fence = ProjectsWorkspaceFence(accountID: accountID)
        isLoadingRemote = true
        remoteError = nil
        do {
            let result = try await remoteClient.readText(project: project, source: source,
                                                         path: path, fence: fence)
            guard requestGeneration == generation, remoteRequest == remoteGeneration,
                  activeRemoteSourceID == source.id else { return }
            try await validateFence(fence)
            guard requestGeneration == generation, remoteRequest == remoteGeneration,
                  activeRemoteSourceID == source.id else { return }
            remoteText = result
            remoteEmbed = ProjectRemotePreviewPolicy.embed(sourceID: source.id, sourceLabel: source.name, path: path, text: result)
            cacheRemotePreview(path: path, source: source, text: result)
        } catch {
            if requestGeneration == generation && remoteRequest == remoteGeneration { remoteError = AppStrings.projectError(error) }
        }
        if requestGeneration == generation && remoteRequest == remoteGeneration { isLoadingRemote = false }
    }

    private func cacheRemotePreview(path: String, source: ProjectWorkspaceSource, text: ProjectRemoteText) {
        // Web virtual preview snippets are bounded to 20,000 characters. Retain
        // at most one page of opened cards; only the active fullscreen has the
        // complete bounded read, and neither value is written to disk.
        let snippet = String(text.content.prefix(20_000))
        let preview = ProjectRemoteText(content: snippet,
            truncated: text.truncated || snippet.count < text.content.count,
            sizeBytes: text.sizeBytes, lineCount: text.lineCount, expectedBase: nil)
        if remoteFilePreviews[path] == nil && remoteFilePreviews.count >= ProjectRemotePagination.pageSize,
           let evicted = remoteFilePreviews.keys.first { remoteFilePreviews.removeValue(forKey: evicted) }
        remoteFilePreviews[path] = ProjectRemotePreviewPolicy.embed(sourceID: source.id,
            sourceLabel: source.name, path: path, text: preview)
    }

    func folderHash(_ folderID: String) -> String {
        SHA256.hash(data: Data(folderID.utf8)).map { String(format: "%02x", $0) }.joined()
    }

    func childFolders(parentID: String?) -> [ProjectWorkspaceFolder] {
        let parentHash = parentID.map(folderHash)
        return folders.filter { $0.parentHash == parentHash }
            .sorted { $0.position == $1.position ? $0.name < $1.name : $0.position < $1.position }
    }

    func childItems(parentID: String?) -> [ProjectWorkspaceItem] {
        let parentHash = parentID.map(folderHash)
        return items.filter { $0.folderHash == parentHash }
            .sorted { $0.position == $1.position ? $0.name < $1.name : $0.position < $1.position }
    }

    private func clearDetail() {
        sourceGeneration = UUID()
        sourceRefreshRequest = nil
        folders = []
        items = []
        itemEmbedPreviews = [:]
        loadingEmbedPreviewIDs = [:]
        sources = []
        settings = nil
        readme = .loading
        isLoadingDetail = false
        closeRemoteSource()
        sourceRootPreviews = [:]
        remoteFilePreviews = [:]
    }

    private func loadReadme(project: ProjectWorkspaceProject, contents: ProjectWorkspaceContents,
                            fence: ProjectsWorkspaceFence) async -> ReadmeState {
        let readmes = contents.items.filter { item in
            item.kind == "embed" && item.folderHash == nil && item.filePath?.lowercased() == "readme.md"
        }.sorted { $0.createdAt > $1.createdAt }
        if let item = readmes.first {
            do {
                let content = try await service.readStoredFile(item, project: project, fence: fence)
                let markdown = ["code", "content", "markdown", "text"]
                    .compactMap { content[$0] as? String }.first
                guard let markdown else { return .failed }
                return .ready(ProjectWorkspaceReadme(markdown: markdown, truncated: false, origin: "stored"))
            } catch { return .failed }
        }
        return await Self.loadConnectedReadme(sources: contents.sources, list: { source in
            try await self.remoteClient.list(project: project, source: source,
                                              path: ".", maxEntries: 500, fence: fence)
        }, read: { source, path in
            try await self.remoteClient.readText(project: project, source: source,
                                                 path: path, fence: fence)
        })
    }

    /// A failed or incomplete source must not hide a README from another source.
    /// Only a complete check of every readable source can prove an empty overview.
    static func loadConnectedReadme(sources: [ProjectWorkspaceSource],
        list: (ProjectWorkspaceSource) async throws -> ProjectRemoteDirectory,
        read: (ProjectWorkspaceSource, String) async throws -> ProjectRemoteText) async -> ReadmeState {
        let readable = sources.filter { $0.capabilities.contains("read") }
        var unavailable = readable.contains { $0.status != "connected" }
        for source in readable where source.status == "connected" {
            do {
                let directory = try await list(source)
                guard let entry = directory.entries.first(where: {
                    $0.kind == "file" && $0.path.lowercased() == "readme.md"
                }) else {
                    unavailable = unavailable || directory.omitted > 0 || directory.nextCursor != nil
                    continue
                }
                let text = try await read(source, entry.path)
                return .ready(ProjectWorkspaceReadme(markdown: text.content,
                    truncated: text.truncated, origin: "connected"))
            } catch { unavailable = true }
        }
        return unavailable ? .unavailable : .empty
    }

    private func prefetchSourceRoots(project: ProjectWorkspaceProject,
                                     sources: [ProjectWorkspaceSource],
                                     fence: ProjectsWorkspaceFence, generation requestGeneration: UUID,
                                     sourceGeneration sourceRequest: UUID) async {
        for source in sources.filter({ $0.status == "connected" && $0.capabilities.contains("read") }).prefix(3) {
            guard requestGeneration == generation, sourceRequest == sourceGeneration,
                  selectedProjectID == project.id else { return }
            guard let directory = try? await listSourceRoot(project, source, fence),
                  (try? await validateFence(fence)) != nil else { continue }
            // The account check can suspend. Source presence or selection may
            // change during it, so this is the final check before publication.
            guard requestGeneration == generation, sourceRequest == sourceGeneration,
                  selectedProjectID == project.id else { return }
            sourceRootPreviews[source.id] = Array(directory.entries.prefix(3))
        }
    }

    #if DEBUG
    /// Isolated renderer fixture. It never installs an account ID or writes to
    /// a service, so production actions cannot mutate live Project data.
    func installPreview(variant: String) {
        previewVariant = variant
        debugOriginalDownload = nil
        if variant == "truncatedConnectedSource" {
            debugOriginalDownload = ProjectsWorkspacePreviewFixture.downloadOriginal(path:progress:)
        }
        generation = UUID()
        accountID = nil
        let state = ProjectsWorkspacePreviewFixture.state(for: variant)
        projects = [state.project]
        selectedProjectID = variant == "landing" ? nil : state.project.id
        installPreviewDetail(variant: variant)
        isLoading = false
        isSaving = false
        errorMessage = nil
    }

    private func installPreviewDetail(variant: String) {
        let state = ProjectsWorkspacePreviewFixture.state(for: variant)
        folders = state.folders
        items = state.items
        itemEmbedPreviews = [:]
        sources = state.sources
        settings = ProjectWorkspaceSettings(writeMode: .applyAndShow,
            selectionRequired: false, focusID: nil, focusInstruction: nil)
        readme = state.readme
        sourceRootPreviews = state.rootPreviews
        activeRemoteSourceID = nil
        remoteFilePreviews = [:]
        remotePath = "."
        remoteEntries = []
        remoteText = nil
        remoteEmbed = nil
        remoteError = nil
        isLoadingDetail = false
        isLoadingRemote = false
    }
    #endif
}
