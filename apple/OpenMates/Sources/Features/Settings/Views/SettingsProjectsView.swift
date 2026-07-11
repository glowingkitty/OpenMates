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

struct SettingsProjectsView: View {
    @EnvironmentObject private var authManager: AuthManager
    @State private var projects: [ProjectItem] = []
    @State private var selectedProject: ProjectItem?
    @State private var projectNames: [String: String] = [:]
    @State private var projectKeys: [String: SymmetricKey] = [:]
    @State private var sources: [ProjectSource] = []
    @State private var sourceNames: [String: String] = [:]
    @State private var writeMode: WriteMode = .alwaysAsk
    @State private var isLoading = true
    @State private var isSaving = false
    @State private var statusMessage: String?
    @State private var errorMessage: String?

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
    struct ProjectSettings: Decodable { let writeMode: WriteMode }
    struct UpdateSettingsRequest: Encodable {
        let writeMode: WriteMode
        let encryptedSettings: String?
        let updatedAt: Int
    }

    enum WriteMode: String, Codable, CaseIterable {
        case alwaysAsk = "always_ask"
        case autoApproveSafeWrites = "auto_approve_safe_writes"

        var title: String {
            switch self {
            case .alwaysAsk: return L("settings.projects.write_mode_always_ask")
            case .autoApproveSafeWrites: return L("settings.projects.write_mode_safe_writes")
            }
        }
    }

    var body: some View {
        if let selectedProject {
            projectDetail(selectedProject)
        } else {
            projectList
        }
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
        .task { await loadProjects() }
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
                    selectedProject = nil
                    sources = []
                    sourceNames = [:]
                    statusMessage = nil
                    errorMessage = nil
                }
            }

            if isLoading {
                ProgressView().frame(maxWidth: .infinity).padding(.spacing8)
            } else {
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

    private func loadProjects() async {
        isLoading = true
        errorMessage = nil
        do {
            let response: ProjectsResponse = try await APIClient.shared.request(.get, path: "/v1/projects")
            projects = response.projects
            try await decryptProjects(response.projects)
        } catch {
            errorMessage = error.localizedDescription
            NativeDiagnostics.error("Project settings load failed", category: "settings.projects")
        }
        isLoading = false
    }

    private func decryptProjects(_ values: [ProjectItem]) async throws {
        guard let user = authManager.currentUser,
              let masterKey = try await CryptoManager.shared.loadMasterKey(for: user.id) else {
            throw APIError.invalidResponse
        }
        var names: [String: String] = [:]
        var keys: [String: SymmetricKey] = [:]
        for project in values {
            let keyData = try await CryptoManager.shared.decryptBlob(
                base64String: project.encryptedProjectKey,
                key: masterKey
            )
            let projectKey = SymmetricKey(data: keyData)
            keys[project.id] = projectKey
            names[project.id] = try await CryptoManager.shared.decryptContent(
                base64String: project.encryptedName,
                key: projectKey
            )
        }
        projectKeys = keys
        projectNames = names
    }

    private func loadProjectDetail(_ project: ProjectItem) async {
        isLoading = true
        errorMessage = nil
        statusMessage = nil
        do {
            async let sourceRequest: SourcesResponse = APIClient.shared.request(
                .get, path: "/v1/projects/\(project.id)/sources"
            )
            async let settingsRequest: SettingsResponse = APIClient.shared.request(
                .get, path: "/v1/projects/\(project.id)/settings"
            )
            let (sourceResponse, settingsResponse) = try await (sourceRequest, settingsRequest)
            sources = sourceResponse.sources
            writeMode = settingsResponse.settings.writeMode
            try await decryptSourceNames(sourceResponse.sources, project: project)
        } catch {
            errorMessage = error.localizedDescription
            NativeDiagnostics.error("Project detail settings load failed", category: "settings.projects")
        }
        isLoading = false
    }

    private func decryptSourceNames(_ values: [ProjectSource], project: ProjectItem) async throws {
        guard let projectKey = projectKeys[project.id] else { throw APIError.invalidResponse }
        var names: [String: String] = [:]
        for source in values {
            names[source.id] = try await CryptoManager.shared.decryptContent(
                base64String: source.encryptedDisplayName,
                key: projectKey
            )
        }
        sourceNames = names
    }

    private func saveWriteMode(_ mode: WriteMode, project: ProjectItem) {
        guard mode != writeMode, !isSaving else { return }
        isSaving = true
        errorMessage = nil
        statusMessage = nil
        Task {
            do {
                let response: SettingsResponse = try await APIClient.shared.request(
                    .patch,
                    path: "/v1/projects/\(project.id)/settings",
                    body: UpdateSettingsRequest(
                        writeMode: mode,
                        encryptedSettings: nil,
                        updatedAt: Int(Date().timeIntervalSince1970 * 1000)
                    )
                )
                writeMode = response.settings.writeMode
                statusMessage = AppStrings.success
            } catch {
                errorMessage = error.localizedDescription
                NativeDiagnostics.error("Project write policy save failed", category: "settings.projects")
            }
            isSaving = false
        }
    }
}

@MainActor
private func L(_ key: String) -> String {
    LocalizationManager.shared.text(key)
}
