// Native project settings hub and project-specific remote-source permissions.
// Project names and source labels are decrypted on-device with existing project keys.
// The backend receives only opaque project identifiers, ciphertext, and policy values.
// Loading, empty, missing-key, saving, success, and error states remain explicit.

// ─── Web source ─────────────────────────────────────────────────────
// Svelte:  frontend/packages/ui/src/components/settings/SettingsProjects.svelte
// Service: frontend/packages/ui/src/services/projectService.ts
// Tokens:  ColorTokens.generated.swift, SpacingTokens.generated.swift,
//          TypographyTokens.generated.swift
// ────────────────────────────────────────────────────────────────────

import CryptoKit
import SwiftUI

struct SettingsProjectsRoute {
    let teamID: String?

    private static func escaped(_ value: String) -> String {
        value.addingPercentEncoding(withAllowedCharacters: CharacterSet(charactersIn:
            "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-._~")) ?? ""
    }

    private func scoped(_ path: String) -> String {
        guard let teamID else { return path }
        return path + "?team_id=" + Self.escaped(teamID)
    }

    var list: String { scoped("/v1/projects") }
    func sources(_ projectID: String) -> String {
        scoped("/v1/projects/\(Self.escaped(projectID))/sources")
    }
    func settings(_ projectID: String) -> String {
        scoped("/v1/projects/\(Self.escaped(projectID))/settings")
    }
}

struct SettingsProjectsLoadIdentity: Hashable {
    let accountID: String?
    let teamID: String?
    let projectID: String?
    let serverURL: String
    let scope: UUID
}

@MainActor
private struct SettingsProjectsFence {
    let accountID: String
    let server: ServerProfile
    let scope: UUID

    init(accountID: String) {
        self.accountID = accountID
        server = ServerProfile.current()
        scope = OfflineStore.shared.scopeGeneration
    }

    func check() async throws {
        guard OfflineStore.shared.scopeGeneration == scope,
              ServerProfile.current() == server,
              await AuthManager.currentUserId() == accountID,
              OfflineStore.shared.scopeGeneration == scope,
              ServerProfile.current() == server else {
            throw CancellationError()
        }
    }
}

struct SettingsProjectsView: View {
    var initialProjectID: String? = nil
    var teamID: String? = nil
    @EnvironmentObject private var authManager: AuthManager
    @State private var projects: [ProjectItem] = []
    @State private var selectedProject: ProjectItem?
    @State private var projectNames: [String: String] = [:]
    @State private var projectKeys: [String: SymmetricKey] = [:]
    @State private var sources: [ProjectSource] = []
    @State private var focusPhases: [FocusPhaseDefinition] = []
    @State private var sourceNames: [String: String] = [:]
    @State private var writeMode: WriteMode?
    @State private var isLoading = true
    @State private var isSaving = false
    @State private var statusMessage: String?
    @State private var errorMessage: String?
    @State private var loadGeneration = UUID()

    private var route: SettingsProjectsRoute { SettingsProjectsRoute(teamID: teamID) }
    private var loadIdentity: SettingsProjectsLoadIdentity {
        SettingsProjectsLoadIdentity(accountID: authManager.currentUser?.id,
                                     teamID: teamID, projectID: initialProjectID,
                                     serverURL: ServerProfile.current().apiBaseURL.absoluteString,
                                     scope: OfflineStore.shared.scopeGeneration)
    }

    struct ProjectItem: Identifiable, Decodable {
        let projectId: String
        let encryptedProjectKey: String
        let encryptedName: String
        let updatedAt: Int?
        var id: String { projectId }
    }

    struct ProjectSource: Identifiable, Decodable {
        let sourceId: String
        let sourceType: String
        let encryptedDisplayName: String
        let capabilities: [String]
        let status: String
        var id: String { sourceId }
    }

    struct ProjectsResponse: Decodable { let projects: [ProjectItem] }
    struct SourcesResponse: Decodable { let sources: [ProjectSource] }
    struct SettingsResponse: Decodable { let settings: ProjectSettings }
    struct ProjectSettings: Decodable { let writeMode: WriteMode?; let encryptedSettings: String? }
    struct UpdateSettingsRequest: Encodable {
        let writeMode: WriteMode
        let updatedAt: Int
    }

    enum WriteMode: String, Codable, CaseIterable {
        case applyAndShow = "apply_and_show"
        case alwaysAsk = "always_ask"

        @MainActor var title: String {
            switch self {
            case .alwaysAsk: return L("settings.projects.write_mode_always_ask")
            case .applyAndShow: return L("settings.projects.write_mode_apply_and_show")
            }
        }
    }

    var body: some View {
        ZStack {
            if let selectedProject {
                projectDetail(selectedProject)
            } else {
                projectList
            }
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .task(id: loadIdentity) { await loadProjects() }
    }

    private var projectList: some View {
        OMSettingsPage(title: AppStrings.projects, showsHeader: false) {
            if isLoading {
                ProgressView()
                    .frame(maxWidth: .infinity)
                    .padding(.spacing8)
                    .accessibilityIdentifier("project-settings-loading")
            } else if projects.isEmpty && errorMessage == nil {
                infoText(L("settings.projects.empty_description"))
                    .accessibilityIdentifier("project-settings-empty")
            } else {
                OMSettingsSection(AppStrings.projects) {
                    ForEach(projects.sorted { ($0.updatedAt ?? 0) > ($1.updatedAt ?? 0) }) { project in
                        OMSettingsRow(
                            title: projectNames[project.id] ?? L("settings.projects.untitled"),
                            icon: "project",
                            accessibilityIdentifier: "project-settings-project-row"
                        ) {
                            selectedProject = project
                            Task { await loadProjectDetail(project) }
                        }
                    }
                }
            }
            statusViews
        }
        .accessibilityIdentifier("project-settings-page")
    }

    private func projectDetail(_ project: ProjectItem) -> some View {
        OMSettingsPage(title: projectNames[project.id] ?? L("settings.projects.untitled"), showsHeader: false) {
            OMSettingsSection {
                OMSettingsRow(
                    title: AppStrings.back,
                    icon: "back",
                    showsChevron: false,
                    accessibilityIdentifier: "project-settings-back"
                ) {
                    loadGeneration = UUID()
                    selectedProject = nil
                    sources = []
                    sourceNames = [:]
                    isLoading = false
                    isSaving = false
                    statusMessage = nil
                    errorMessage = nil
                }
            }

            if isLoading {
                ProgressView().frame(maxWidth: .infinity).padding(.spacing8)
            } else {
                if !focusPhases.isEmpty { FocusModePhasesNativeView(phases: focusPhases) }
                OMSettingsSection(L("settings.projects.write_policy")) {
                    ForEach(WriteMode.allCases, id: \.self) { mode in
                        OMSettingsRow(
                            title: mode.title,
                            icon: writeMode == mode ? "check" : "settings",
                            showsChevron: false,
                            accessibilityIdentifier: "project-settings-write-mode-\(mode.rawValue)"
                        ) { saveWriteMode(mode, project: project) }
                        .opacity(isSaving ? 0.6 : 1)
                    }
                }

                OMSettingsSection(L("settings.projects.connected_sources")) {
                    if sources.isEmpty {
                        infoText(L("settings.projects.no_sources_description"))
                    } else {
                        ForEach(sources) { source in
                            VStack(alignment: .leading, spacing: .spacing2) {
                                Text(sourceNames[source.id] ?? source.id)
                                    .font(.omP.weight(.semibold))
                                    .foregroundStyle(Color.fontPrimary)
                                Text(source.sourceType.replacingOccurrences(of: "_", with: " "))
                                    .font(.omSmall)
                                    .foregroundStyle(Color.fontSecondary)
                                Text(source.status.replacingOccurrences(of: "_", with: " "))
                                    .font(.omXs)
                                    .foregroundStyle(Color.fontTertiary)
                                Text(source.capabilities.joined(separator: ", "))
                                    .font(.omXs)
                                    .foregroundStyle(Color.fontTertiary)
                            }
                            .padding(.horizontal, .spacing6)
                            .padding(.vertical, .spacing5)
                            .accessibilityIdentifier("project-settings-source-card")
                        }
                    }
                }
            }
            statusViews
        }
        .accessibilityIdentifier("project-settings-detail-page")
    }

    @ViewBuilder
    private var statusViews: some View {
        if let statusMessage { infoText(statusMessage).foregroundStyle(Color.buttonPrimary) }
        if let errorMessage {
            VStack(alignment: .leading, spacing: .spacing4) {
                infoText(errorMessage).foregroundStyle(Color.error)
                Button(AppStrings.retry) {
                    Task {
                        if let selectedProject { await loadProjectDetail(selectedProject) }
                        else { await loadProjects() }
                    }
                }
                .buttonStyle(OMPrimaryButtonStyle())
                .accessibilityIdentifier("project-settings-retry-button")
            }
        }
    }

    private func infoText(_ text: String) -> some View {
        Text(text)
            .font(.omSmall)
            .foregroundStyle(Color.fontSecondary)
            .frame(maxWidth: .infinity, alignment: .leading)
            .padding(.spacing6)
    }

    private func requestPinned<T: Decodable>(
        _ method: HTTPMethod, path: String, fence: SettingsProjectsFence,
        body: JSONRawBody? = nil
    ) async throws -> T {
        try await fence.check()
        let data: Data
        #if DEBUG
        if ProcessInfo.processInfo.arguments.contains("--ui-test-focus-phase-fixture"),
           ProcessInfo.processInfo.arguments.contains("--ui-test-account-settings-fixture"),
           fence.accountID == "ui-test-chat-navigation-user" {
            data = try await DevFocusPhaseFixture.projectResponse(path: path, accountID: fence.accountID)
        } else {
            data = try await APIClient.shared.request(method, path: path,
                                                      serverProfile: fence.server, body: body)
        }
        #else
        data = try await APIClient.shared.request(method, path: path,
                                                  serverProfile: fence.server, body: body)
        #endif
        try await fence.check()
        let decoder = JSONDecoder()
        decoder.keyDecodingStrategy = .convertFromSnakeCase
        return try decoder.decode(T.self, from: data)
    }

    private func isCurrent(_ operation: UUID, fence: SettingsProjectsFence) async -> Bool {
        guard !Task.isCancelled, loadGeneration == operation else { return false }
        guard (try? await fence.check()) != nil else { return false }
        return !Task.isCancelled && loadGeneration == operation
    }

    private func loadProjects() async {
        loadGeneration = UUID()
        let operation = loadGeneration
        selectedProject = nil
        projects = []
        projectNames = [:]
        projectKeys = [:]
        sources = []
        sourceNames = [:]
        writeMode = nil
        isLoading = true
        isSaving = false
        errorMessage = nil
        statusMessage = nil
        guard let accountID = authManager.currentUser?.id else {
            isLoading = false
            return
        }
        let fence = SettingsProjectsFence(accountID: accountID)
        do {
            let response: ProjectsResponse = try await requestPinned(.get, path: route.list, fence: fence)
            let decrypted = try await decryptProjects(response.projects, fence: fence)
            guard await isCurrent(operation, fence: fence) else { return }
            projects = response.projects
            projectKeys = decrypted.keys
            projectNames = decrypted.names
            if let initialProjectID, let project = response.projects.first(where: { $0.id == initialProjectID }) {
                selectedProject = project
                await loadProjectDetail(project, fence: fence, operation: operation)
                return
            }
        } catch {
            guard await isCurrent(operation, fence: fence) else { return }
            errorMessage = error.localizedDescription
            NativeDiagnostics.error("Project settings load failed", category: "settings.projects")
        }
        if await isCurrent(operation, fence: fence) { isLoading = false }
    }

    private func decryptProjects(_ values: [ProjectItem], fence: SettingsProjectsFence) async throws
        -> (names: [String: String], keys: [String: SymmetricKey]) {
        try await fence.check()
        guard let masterKey = try await CryptoManager.shared.loadMasterKey(for: fence.accountID) else {
            throw APIError.invalidResponse
        }
        try await fence.check()
        var names: [String: String] = [:]
        var keys: [String: SymmetricKey] = [:]
        for project in values {
            let keyData = try await CryptoManager.shared.decryptBlob(
                base64String: project.encryptedProjectKey, key: masterKey)
            guard keyData.count == 32 else { throw APIError.invalidResponse }
            let projectKey = SymmetricKey(data: keyData)
            names[project.id] = try await CryptoManager.shared.decryptContent(
                base64String: project.encryptedName, key: projectKey)
            keys[project.id] = projectKey
            try await fence.check()
        }
        return (names, keys)
    }

    private func loadProjectDetail(_ project: ProjectItem) async {
        guard let accountID = authManager.currentUser?.id else { return }
        loadGeneration = UUID()
        await loadProjectDetail(project, fence: SettingsProjectsFence(accountID: accountID),
                                operation: loadGeneration)
    }

    private func loadProjectDetail(_ project: ProjectItem, fence: SettingsProjectsFence,
                                   operation: UUID) async {
        isLoading = true
        errorMessage = nil
        statusMessage = nil
        sources = []
        sourceNames = [:]
        writeMode = nil
        focusPhases = []
        do {
            let sourceResponse: SourcesResponse = try await requestPinned(
                .get, path: route.sources(project.id), fence: fence)
            let settingsResponse: SettingsResponse = try await requestPinned(
                .get, path: route.settings(project.id), fence: fence)
            let names = try await decryptSourceNames(sourceResponse.sources, project: project, fence: fence)
            guard await isCurrent(operation, fence: fence), selectedProject?.id == project.id else { return }
            sources = sourceResponse.sources
            sourceNames = names
            writeMode = settingsResponse.settings.writeMode;
            focusPhases = []
            if let encrypted = settingsResponse.settings.encryptedSettings, let key = projectKeys[project.id] {
                if let text = try? await CryptoManager.shared.decryptContent(base64String: encrypted, key: key),
                   let data = text.data(using: .utf8),
                   let settings = (try? JSONSerialization.jsonObject(with: data)) as? [String: Any],
                   let focus = settings["default_focus"] as? [String: Any], let instruction = focus["instructions"] as? String,
                   await isCurrent(operation, fence: fence), selectedProject?.id == project.id {
                    focusPhases = FocusPhaseDefinition.fromInstruction(instruction)
                }
            }
        } catch {
            guard await isCurrent(operation, fence: fence), selectedProject?.id == project.id else { return }
            errorMessage = error.localizedDescription
            NativeDiagnostics.error("Project detail settings load failed", category: "settings.projects")
        }
        if await isCurrent(operation, fence: fence) { isLoading = false }
    }

    private func decryptSourceNames(_ values: [ProjectSource], project: ProjectItem,
                                    fence: SettingsProjectsFence) async throws -> [String: String] {
        guard let projectKey = projectKeys[project.id] else { throw APIError.invalidResponse }
        var names: [String: String] = [:]
        for source in values {
            names[source.id] = try await CryptoManager.shared.decryptContent(
                base64String: source.encryptedDisplayName, key: projectKey)
            try await fence.check()
        }
        return names
    }

    private func saveWriteMode(_ mode: WriteMode, project: ProjectItem) {
        guard mode != writeMode, !isSaving, let accountID = authManager.currentUser?.id else { return }
        let operation = loadGeneration
        let fence = SettingsProjectsFence(accountID: accountID)
        isSaving = true
        errorMessage = nil
        statusMessage = nil
        Task {
            do {
                let response: SettingsResponse = try await requestPinned(
                    .patch, path: route.settings(project.id), fence: fence,
                    body: Self.encodedBody(UpdateSettingsRequest(writeMode: mode,
                        updatedAt: Int(Date().timeIntervalSince1970 * 1000))))
                guard await isCurrent(operation, fence: fence), selectedProject?.id == project.id else { return }
                writeMode = response.settings.writeMode
                statusMessage = AppStrings.success
            } catch {
                guard await isCurrent(operation, fence: fence), selectedProject?.id == project.id else { return }
                errorMessage = error.localizedDescription
                NativeDiagnostics.error("Project write policy save failed", category: "settings.projects")
            }
            if await isCurrent(operation, fence: fence) { isSaving = false }
        }
    }

    private static func encodedBody<T: Encodable>(_ value: T) throws -> JSONRawBody {
        let encoder = JSONEncoder()
        encoder.keyEncodingStrategy = .convertToSnakeCase
        return JSONRawBody(data: try encoder.encode(value))
    }
}

@MainActor
private func L(_ key: String) -> String {
    LocalizationManager.shared.text(key)
}
