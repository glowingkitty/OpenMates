// Specification: specifications/features/chat-navigation/specification.yml
// Assertions: chat-navigation.projects.nested-readable, chat-navigation.activity.global-running, chat-navigation.projects.organize
// Specification: specifications/features/apple-offline-workspaces/specification.yml
// Assertions: apple-workspaces.offline-complete, apple-workspaces.local-first, apple-workspaces.isolation, apple-workspaces.maintenance
// ─── Web source ─────────────────────────────────────────────────────
// Services: frontend/packages/ui/src/services/projectService.ts, projectAuthoringClientService.ts
// Svelte: frontend/packages/ui/src/components/AgentContextMessage.svelte
// CSS: .context-message, .actions — generated tokens and custom receipt controls.
// ────────────────────────────────────────────────────────────────────
// Specification: specifications/features/projects/specification.yml
// Assertions: projects.access.explicit-context, projects.files.no-server-decryption-authority
import CryptoKit
import Combine
import SwiftUI
import Yams
import Foundation

@MainActor
struct ProjectsWorkspaceFence {
    let accountID: String
    let scope: UUID
    let serverProfile: ServerProfile
    let teamContext: TeamWorkspaceSnapshot

    init(accountID: String) {
        self.accountID = accountID
        self.teamContext = TeamWorkspaceContext.shared.snapshot
        self.scope = OfflineStore.shared.scopeGeneration
        self.serverProfile = ServerProfile.custom(domain: ServerConfiguration.current.selectedDomain)
    }

    func check() async throws {
        guard TeamWorkspaceContext.shared.isCurrent(teamContext), scope == OfflineStore.shared.scopeGeneration,
              serverProfile.apiBaseURL == ServerConfiguration.current.apiBaseURL,
              accountID == (await AuthManager.currentUserId()) else {
            throw ProjectsWorkspaceError.accountChanged
        }
    }
}

@MainActor
protocol ProjectsWorkspaceServing: Sendable {
    func cachedProjects(accountID: String, teamID: String?) async throws -> [ProjectWorkspaceProject]?
    func cachedContents(project: ProjectWorkspaceProject, fence: ProjectsWorkspaceFence) async throws -> ProjectWorkspaceContents?
    func cachedSettings(project: ProjectWorkspaceProject, fence: ProjectsWorkspaceFence) async throws -> ProjectWorkspaceSettings?
    func listProjects(accountID: String, teamID: String?) async throws -> [ProjectWorkspaceProject]
    func listSources(project: ProjectWorkspaceProject, fence: ProjectsWorkspaceFence) async throws -> [ProjectWorkspaceSource]
    func contents(project: ProjectWorkspaceProject, fence: ProjectsWorkspaceFence) async throws -> ProjectWorkspaceContents
    func settings(project: ProjectWorkspaceProject, fence: ProjectsWorkspaceFence) async throws -> ProjectWorkspaceSettings
    func createProject(name: String, writeMode: ProjectWorkspaceWriteMode, fence: ProjectsWorkspaceFence, teamID: String?) async throws -> ProjectWorkspaceProject
    func createChatOrganization(chats: [Chat], fence: ProjectsWorkspaceFence, teamID: String?) async throws -> ProjectWorkspaceProject
    func removeChatLink(chatID: String, project: ProjectWorkspaceProject, fence: ProjectsWorkspaceFence) async throws
    func updateProject(_ project: ProjectWorkspaceProject, name: String?, description: String?, fence: ProjectsWorkspaceFence) async throws -> ProjectWorkspaceProject
    func createFolder(_ name: String, project: ProjectWorkspaceProject, parentID: String?, fence: ProjectsWorkspaceFence) async throws
    func moveItem(_ itemID: String, project: ProjectWorkspaceProject, folderID: String?, fence: ProjectsWorkspaceFence) async throws
    func copyItem(_ item: ProjectWorkspaceItem, project: ProjectWorkspaceProject, folderID: String?, fence: ProjectsWorkspaceFence) async throws
    func updateWriteMode(_ mode: ProjectWorkspaceWriteMode, project: ProjectWorkspaceProject, fence: ProjectsWorkspaceFence) async throws -> ProjectWorkspaceSettings
    func activateFocus(project: ProjectWorkspaceProject, chatID: String, focusID: String, instruction: String, fence: ProjectsWorkspaceFence) async throws
    func deleteProject(_ project: ProjectWorkspaceProject, fence: ProjectsWorkspaceFence) async throws
    func readStoredFile(_ item: ProjectWorkspaceItem, project: ProjectWorkspaceProject, fence: ProjectsWorkspaceFence) async throws -> [String: Any]
    func openLinkedEmbed(_ item: ProjectWorkspaceItem, project: ProjectWorkspaceProject, fence: ProjectsWorkspaceFence) async throws -> EmbedRecord
}

extension ProjectsWorkspaceServing {
    func createChatOrganization(chats: [Chat], fence: ProjectsWorkspaceFence, teamID: String?) async throws -> ProjectWorkspaceProject { throw ProjectsWorkspaceError.invalidContext }
    func removeChatLink(chatID: String, project: ProjectWorkspaceProject, fence: ProjectsWorkspaceFence) async throws { throw ProjectsWorkspaceError.invalidContext }
    func cachedProjects(accountID: String, teamID: String?) async throws -> [ProjectWorkspaceProject]? { nil }
    func cachedContents(project: ProjectWorkspaceProject, fence: ProjectsWorkspaceFence) async throws -> ProjectWorkspaceContents? { nil }
    func cachedSettings(project: ProjectWorkspaceProject, fence: ProjectsWorkspaceFence) async throws -> ProjectWorkspaceSettings? { nil }
}

@MainActor
final class ProjectsWorkspaceService: ProjectsWorkspaceServing {
    private struct ProjectListResponse: Decodable, Sendable { let projects: [ProjectWorkspaceRecord] }
    private struct ProjectResponse: Decodable { let project: ProjectWorkspaceRecord }
    private struct ContentsResponse: Decodable, Sendable {
        let folders: [ProjectWorkspaceFolderRecord]
        let items: [ProjectWorkspaceItemRecord]
    }
    private struct SourcesResponse: Decodable, Sendable { let sources: [ProjectWorkspaceSourceRecord] }
    private struct SettingsResponse: Decodable, Sendable { let settings: ProjectWorkspaceSettingsRecord }
    private struct EmbedKeyRecord: Decodable { let keyType: String; let encryptedEmbedKey: String }
    private struct EncryptedEmbed: Decodable {
        let encryptedContent: String
        let encryptedType: String?
        let status: EmbedStatus?
        let versionNumber: Int?
        let createdAt: Int?
    }
    private struct EncryptedEmbedResponse: Decodable {
        let embed: EncryptedEmbed
        let embedKeys: [EmbedKeyRecord]
    }

    private func route(_ path: String, teamID: String?) -> String {
        guard let teamID else { return path }
        let separator = path.contains("?") ? "&" : "?"
        return path + separator + "team_id=" + Self.escaped(teamID)
    }

    private static func escaped(_ value: String) -> String {
        value.addingPercentEncoding(withAllowedCharacters: CharacterSet(charactersIn: "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-._~")) ?? ""
    }

    private func projectRoute(_ project: ProjectWorkspaceProject, suffix: String = "") -> String {
        route("/v1/projects/\(Self.escaped(project.id))\(suffix)", teamID: project.teamId)
    }

    private func open(_ record: ProjectWorkspaceRecord, masterKey: SymmetricKey, teamID: String?, accountID: String) async throws -> ProjectWorkspaceProject {
        let keyData: Data
        if let teamID {
            let team = try await TeamWorkspaceService().getTeam(teamID, fence: TeamWorkspaceFence(accountID: accountID))
            guard team.canRead, let wrapper = record.keyWrappers?.first(where: {
                $0.keyType == "team" && $0.hashedTeamId == ChatSidebarProject.hash(teamID) && ($0.teamKeyEpoch ?? 0) >= 1
            }) else { throw ProjectsWorkspaceError.missingProjectKey }
            keyData = try await CryptoManager.shared.decryptBlob(base64String: wrapper.encryptedProjectKey, key: team.key)
        } else {
            guard let wrappedKey = record.encryptedProjectKey, !wrappedKey.isEmpty else { throw ProjectsWorkspaceError.missingProjectKey }
            keyData = try await CryptoManager.shared.decryptBlob(base64String: wrappedKey, key: masterKey)
        }
        guard keyData.count == 32 else { throw ProjectsWorkspaceError.missingProjectKey }
        let key = SymmetricKey(data: keyData)
        let name = try await CryptoManager.shared.decryptContent(base64String: record.encryptedName, key: key)
        guard !name.isEmpty else { throw ProjectsWorkspaceError.invalidResponse }
        let description = try await decryptOptional(record.encryptedDescription, key: key)
        let icon = try await decryptOptional(record.encryptedIcon, key: key)
        return ProjectWorkspaceProject(
            id: record.projectId, name: name, description: description, icon: icon.isEmpty ? "folder" : icon,
            key: key, version: record.version ?? 1, createdAt: record.createdAt, updatedAt: record.updatedAt,
            isShared: record.isShared ?? false, itemCount: record.itemCount ?? 0, teamId: teamID,
            permissions: record.mutationPermissions ?? .denied
        )
    }

    private func decryptOptional(_ ciphertext: String?, key: SymmetricKey) async throws -> String {
        guard let ciphertext, !ciphertext.isEmpty else { return "" }
        return try await CryptoManager.shared.decryptContent(base64String: ciphertext, key: key)
    }

    private func encrypt(_ plaintext: String, key: SymmetricKey) async throws -> String {
        // Web projectService uses the plain IV+ciphertext AES-GCM envelope.
        try await CryptoManager.shared.encryptWithMasterKey(plaintext, masterKey: key)
    }

    private func metadata(_ ciphertext: String?, key: SymmetricKey) async throws -> [String: String] {
        let plaintext = try await decryptOptional(ciphertext, key: key)
        guard !plaintext.isEmpty else { return [:] }
        guard let data = plaintext.data(using: .utf8),
              let object = try JSONSerialization.jsonObject(with: data) as? [String: Any] else {
            throw ProjectsWorkspaceError.invalidResponse
        }
        return object.compactMapValues { value in
            switch value {
            case let string as String: return string
            case let number as NSNumber: return number.stringValue
            default: return nil
            }
        }
    }

    private func response<T: Decodable & Sendable>(_ type: T.Type, path: String, fence: ProjectsWorkspaceFence,
                                        teamID: String?, cachedOnly: Bool = false) async throws -> T {
        try await fence.check()
        let scope = try await NativeWorkspaceOfflineRuntime.configure(accountID: fence.accountID, teamID: teamID)
        let data: Data
        if cachedOnly {
            guard let cached = try await NativeWorkspaceOfflineRuntime.cached(namespace: "projects", path: path, scope: scope) else {
                throw ProjectsWorkspaceError.invalidResponse
            }
            data = cached
        } else {
            data = try await NativeWorkspaceOfflineRuntime.request(namespace: "projects", path: path, scope: scope, retain: false)
        }
        try await fence.check()
        let decoded = try await NativeWorkspaceOfflineRuntime.decodeResponse(type, data: data)
        if !cachedOnly {
            let retained = path.contains("/sources") ? try NativeWorkspaceOfflineRuntime.sanitizedResponse(data) : data
            try await NativeWorkspaceOfflineRuntime.check(scope)
            try await NativeWorkspaceOfflineCache.shared.retain(namespace: "projects", path: path, data: retained, scope: scope)
        }
        return decoded
    }

    func cachedProjects(accountID: String, teamID: String?) async throws -> [ProjectWorkspaceProject]? {
        try await loadProjects(accountID: accountID, teamID: teamID, cachedOnly: true)
    }

    func cachedContents(project: ProjectWorkspaceProject, fence: ProjectsWorkspaceFence) async throws -> ProjectWorkspaceContents? {
        try await loadContents(project: project, fence: fence, cachedOnly: true)
    }

    func cachedSettings(project: ProjectWorkspaceProject, fence: ProjectsWorkspaceFence) async throws -> ProjectWorkspaceSettings? {
        try await loadSettings(project: project, fence: fence, cachedOnly: true)
    }

    func maintainOffline(scope: NativeWorkspaceOfflineScope) async throws {
        let cache = NativeWorkspaceOfflineCache.shared
        let revision = try await cache.beginRefresh(namespace: "projects", scope: scope)
        let listPath = route("/v1/projects", teamID: scope.teamID)
        let data = try await NativeWorkspaceOfflineRuntime.request(namespace: "projects", path: listPath, scope: scope, retain: false)
        let inventory = try await NativeWorkspaceOfflineRuntime.decodeResponse(ProjectListResponse.self, data: data)
        var responses = [listPath: data]
        for project in inventory.projects {
            for suffix in ["/items", "/sources", "/settings"] {
                try Task.checkCancellation()
                let path = route("/v1/projects/" + Self.escaped(project.projectId) + suffix, teamID: scope.teamID)
                let raw = try await NativeWorkspaceOfflineRuntime.request(namespace: "projects", path: path, scope: scope, retain: false)
                switch suffix {
                case "/items": _ = try await NativeWorkspaceOfflineRuntime.decodeResponse(ContentsResponse.self, data: raw)
                case "/sources": _ = try await NativeWorkspaceOfflineRuntime.decodeResponse(SourcesResponse.self, data: raw)
                default: _ = try await NativeWorkspaceOfflineRuntime.decodeResponse(SettingsResponse.self, data: raw)
                }
                responses[path] = try NativeWorkspaceOfflineRuntime.sanitizedResponse(raw)
            }
        }
        try await NativeWorkspaceOfflineRuntime.check(scope)
        try await cache.commit(namespace: "projects", responses: responses, scope: scope, revision: revision)
    }

    func listProjects(accountID: String, teamID: String? = nil) async throws -> [ProjectWorkspaceProject] {
        try await loadProjects(accountID: accountID, teamID: teamID, cachedOnly: false)
    }

    private func loadProjects(accountID: String, teamID: String?, cachedOnly: Bool) async throws -> [ProjectWorkspaceProject] {
        let fence = ProjectsWorkspaceFence(accountID: accountID)
        let response = try await response(ProjectListResponse.self, path: route("/v1/projects", teamID: teamID),
            fence: fence, teamID: teamID, cachedOnly: cachedOnly)
        try await fence.check()
        guard let masterKey = try await CryptoManager.shared.loadMasterKey(for: accountID) else {
            throw ProjectsWorkspaceError.missingMasterKey
        }
        var opened: [ProjectWorkspaceProject] = []
        for record in response.projects {
            try await fence.check()
            opened.append(try await open(record, masterKey: masterKey, teamID: teamID, accountID: accountID))
        }
        try await fence.check()
        return opened
    }

    func getProject(accountID: String, projectID: String, teamID: String?,
                    fence: ProjectsWorkspaceFence) async throws -> ProjectWorkspaceProject {
        try await fence.check()
        let path = route("/v1/projects/\(Self.escaped(projectID))", teamID: teamID)
        let response: ProjectResponse = try await APIClient.shared.request(.get, path: path, serverProfile: fence.serverProfile,
            expectedAccountID: fence.accountID, expectedScope: fence.scope, expectedTeamContext: .init(epoch: fence.teamContext.epoch, teamID: fence.teamContext.teamID))
        try await fence.check()
        guard let masterKey = try await CryptoManager.shared.loadMasterKey(for: accountID) else {
            throw ProjectsWorkspaceError.missingMasterKey
        }
        let project = try await open(response.project, masterKey: masterKey, teamID: teamID, accountID: fence.accountID)
        guard project.id == projectID else { throw ProjectsWorkspaceError.invalidResponse }
        try await fence.check()
        return project
    }

    func contents(project: ProjectWorkspaceProject, fence: ProjectsWorkspaceFence) async throws -> ProjectWorkspaceContents {
        try await loadContents(project: project, fence: fence, cachedOnly: false)
    }

    private func loadContents(project: ProjectWorkspaceProject, fence: ProjectsWorkspaceFence,
                              cachedOnly: Bool) async throws -> ProjectWorkspaceContents {
        async let contents = response(ContentsResponse.self, path: projectRoute(project, suffix: "/items"),
            fence: fence, teamID: project.teamId, cachedOnly: cachedOnly)
        async let sources = response(SourcesResponse.self, path: projectRoute(project, suffix: "/sources"),
            fence: fence, teamID: project.teamId, cachedOnly: cachedOnly)
        let (response, sourceResponse) = try await (contents, sources)
        try await fence.check()
        var folders: [ProjectWorkspaceFolder] = []
        for record in response.folders {
            let name = try await decryptOptional(record.encryptedName, key: project.key)
            folders.append(ProjectWorkspaceFolder(id: record.folderId, name: name,
                parentHash: record.hashedParentFolderId, position: record.position, createdAt: record.createdAt))
        }
        var items: [ProjectWorkspaceItem] = []
        for record in response.items {
            let targetID = try await decryptOptional(record.targetIdEncrypted, key: project.key)
            let name = try await decryptOptional(record.encryptedDisplayName, key: project.key)
            let detail = try await metadata(record.encryptedMetadata, key: project.key)
            guard !targetID.isEmpty else { throw ProjectsWorkspaceError.invalidResponse }
            items.append(ProjectWorkspaceItem(id: record.projectItemId, kind: record.itemType,
                targetID: targetID, name: name, metadata: detail, folderHash: record.hashedFolderId,
                position: record.position, createdAt: record.createdAt))
        }
        let projectSources = try await openSources(sourceResponse.sources, project: project)
        try await fence.check()
        return ProjectWorkspaceContents(folders: folders, items: items, sources: projectSources)
    }

    func listSources(project: ProjectWorkspaceProject, fence: ProjectsWorkspaceFence) async throws -> [ProjectWorkspaceSource] {
        try await fence.check()
        let response: SourcesResponse = try await APIClient.shared.request(.get,
            path: projectRoute(project, suffix: "/sources"), serverProfile: fence.serverProfile,
            expectedAccountID: fence.accountID, expectedScope: fence.scope, expectedTeamContext: .init(epoch: fence.teamContext.epoch, teamID: fence.teamContext.teamID))
        let sources = try await openSources(response.sources, project: project)
        try await fence.check()
        return sources
    }

    private func openSources(_ records: [ProjectWorkspaceSourceRecord], project: ProjectWorkspaceProject) async throws -> [ProjectWorkspaceSource] {
        var sources: [ProjectWorkspaceSource] = []
        for record in records {
            sources.append(ProjectWorkspaceSource(id: record.sourceId, kind: record.sourceType,
                name: try await decryptOptional(record.encryptedDisplayName, key: project.key),
                metadata: try await metadata(record.encryptedMetadata, key: project.key),
                capabilities: record.capabilities, status: record.status,
                sessionID: record.sourceSessionId, keyEpoch: record.keyEpoch))
        }
        return sources
    }

    func settings(project: ProjectWorkspaceProject, fence: ProjectsWorkspaceFence) async throws -> ProjectWorkspaceSettings {
        try await loadSettings(project: project, fence: fence, cachedOnly: false)
    }

    private func loadSettings(project: ProjectWorkspaceProject, fence: ProjectsWorkspaceFence,
                              cachedOnly: Bool) async throws -> ProjectWorkspaceSettings {
        var response = try await response(SettingsResponse.self, path: projectRoute(project, suffix: "/settings"),
            fence: fence, teamID: project.teamId, cachedOnly: cachedOnly)
        try await fence.check()
        if !cachedOnly, response.settings.encryptedSettings == nil {
            // Legacy Projects initialize an encrypted base Focus without granting access.
            let focusID = UUID().uuidString.lowercased()
            let settings: [String: Any] = ["default_focus": ["focus_id": focusID, "name": "Work on " + project.name,
                "instructions": "Help with work in " + project.name + ". Follow the user's instructions and the Project's connected source guidance.", "source": "generated"]]
            let encoded = try JSONSerialization.data(withJSONObject: settings)
            let encrypted = try await encrypt(String(decoding: encoded, as: UTF8.self), key: project.key)
            try await fence.check()
            response = try await APIClient.shared.request(.patch, path: projectRoute(project, suffix: "/settings"), serverProfile: fence.serverProfile,
                body: ["write_mode": (response.settings.writeMode ?? .applyAndShow).rawValue, "default_focus_id": focusID,
                       "encrypted_settings": encrypted, "updated_at": Int(Date().timeIntervalSince1970)],
                expectedAccountID: fence.accountID, expectedScope: fence.scope,
                expectedTeamContext: .init(epoch: fence.teamContext.epoch, teamID: fence.teamContext.teamID))
            try await fence.check()
        }
        let text = try await decryptOptional(response.settings.encryptedSettings, key: project.key)
        let payload = text.data(using: .utf8).flatMap { try? JSONSerialization.jsonObject(with: $0) as? [String: Any] }
        let focus = payload?["default_focus"] as? [String: Any]
        return ProjectWorkspaceSettings(writeMode: response.settings.writeMode ?? .applyAndShow,
            selectionRequired: response.settings.selectionRequired ?? false,
            focusID: focus?["focus_id"] as? String, focusInstruction: focus?["instructions"] as? String)
    }

    func createChatOrganization(chats: [Chat], fence: ProjectsWorkspaceFence, teamID: String?) async throws -> ProjectWorkspaceProject {
        guard !chats.isEmpty, chats.allSatisfy({ ChatProjectEligibility.canOrganize($0, teamID: teamID) }) else { throw ProjectsWorkspaceError.invalidContext }
        struct Suggestion: Decodable { struct Proposal: Decodable { let name: String }; let proposedProject: Proposal? }
        try await fence.check()
        let suggestion: Suggestion = try await APIClient.shared.request(.post, path: route("/v1/projects/ask/plan", teamID: teamID),
            serverProfile: fence.serverProfile,
            body: ["instruction": "Name a new project from chat titles.", "chat_titles": chats.prefix(8).map { String($0.displayTitle.prefix(200)) }],
            expectedAccountID: fence.accountID, expectedScope: fence.scope, expectedTeamContext: .init(epoch: fence.teamContext.epoch, teamID: fence.teamContext.teamID))
        try await fence.check()
        guard let name = suggestion.proposedProject?.name.trimmingCharacters(in: .whitespacesAndNewlines),
              !name.isEmpty, name.count <= 200 else { throw ProjectsWorkspaceError.invalidResponse }
        return try await createProject(name: name, writeMode: nil, fence: fence, teamID: teamID)
    }

    func removeChatLink(chatID: String, project: ProjectWorkspaceProject, fence: ProjectsWorkspaceFence) async throws {
        guard project.permissions.manageOwnItems || project.permissions.manageAnyItems else { throw ProjectsWorkspaceError.invalidContext }
        try await fence.check()
        let path = projectRoute(project, suffix: "/items") + (project.teamId == nil ? "?" : "&") + "item_type=chat&target_id=" + Self.escaped(chatID)
        let _: Data = try await APIClient.shared.request(.delete, path: path, serverProfile: fence.serverProfile,
            expectedAccountID: fence.accountID, expectedScope: fence.scope, expectedTeamContext: .init(epoch: fence.teamContext.epoch, teamID: fence.teamContext.teamID))
        try await fence.check()
    }

    func createProject(name: String, writeMode: ProjectWorkspaceWriteMode, fence: ProjectsWorkspaceFence, teamID: String? = nil) async throws -> ProjectWorkspaceProject {
        try await createProject(name: name, writeMode: Optional(writeMode), fence: fence, teamID: teamID)
    }

    private func createProject(name: String, writeMode: ProjectWorkspaceWriteMode?, fence: ProjectsWorkspaceFence, teamID: String?) async throws -> ProjectWorkspaceProject {
        let cleanName = name.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !cleanName.isEmpty else { throw ProjectsWorkspaceError.invalidContext }
        try await fence.check()
        guard let masterKey = try await CryptoManager.shared.loadMasterKey(for: fence.accountID) else {
            throw ProjectsWorkspaceError.missingMasterKey
        }
        let projectKey = SymmetricKey(size: .bits256)
        let focusID = UUID().uuidString.lowercased()
        let focus = ["default_focus": ["focus_id": focusID, "name": "Work on \(cleanName)",
            "instructions": "Help with work in \(cleanName). Follow the user's instructions and the Project's connected source guidance.",
            "source": "generated"]]
        let settingsData = try JSONSerialization.data(withJSONObject: focus)
        guard let settingsText = String(data: settingsData, encoding: .utf8) else { throw ProjectsWorkspaceError.invalidResponse }
        let now = Int(Date().timeIntervalSince1970)
        var body: [String: Any] = [
            "project_id": UUID().uuidString.lowercased(),
            "encrypted_project_key": try await CryptoManager.shared.wrapChatKey(projectKey, masterKey: masterKey),
            "encrypted_name": try await encrypt(cleanName, key: projectKey),
            "encrypted_description": try await encrypt("", key: projectKey),
            "encrypted_icon": try await encrypt("folder", key: projectKey),
            "encrypted_color": try await encrypt("default", key: projectKey),
            "pinned": false, "created_at": now, "updated_at": now, "last_opened_at": now,
            "write_mode": writeMode.map { $0.rawValue as Any } ?? NSNull(), "default_focus_id": focusID,
            "encrypted_settings": try await encrypt(settingsText, key: projectKey),
        ]
        try await fence.check()
        if writeMode == nil { body["chat_organization_only"] = true }
        if let teamID {
            let team = try await TeamWorkspaceService().getTeam(teamID, fence: TeamWorkspaceFence(accountID: fence.accountID))
            guard team.canContribute else { throw ProjectsWorkspaceError.invalidContext }
            body["key_wrappers"] = [["key_type": "team", "hashed_team_id": ChatSidebarProject.hash(teamID), "team_key_epoch": 1,
                "encrypted_project_key": try await CryptoManager.shared.wrapChatKey(projectKey, masterKey: team.key)]]
        }
        try await fence.check()
        let response: ProjectResponse = try await APIClient.shared.request(.post, path: route("/v1/projects", teamID: teamID), serverProfile: fence.serverProfile, body: body,
            expectedAccountID: fence.accountID, expectedScope: fence.scope, expectedTeamContext: .init(epoch: fence.teamContext.epoch, teamID: fence.teamContext.teamID))
        try await fence.check()
        return try await open(response.project, masterKey: masterKey, teamID: teamID, accountID: fence.accountID)
    }

    func updateProject(_ project: ProjectWorkspaceProject, name: String?, description: String?, fence: ProjectsWorkspaceFence) async throws -> ProjectWorkspaceProject {
        guard project.permissions.update else { throw ProjectsWorkspaceError.invalidContext }
        try await fence.check()
        var body: [String: Any] = ["version": project.version]
        if let name { body["encrypted_name"] = try await encrypt(name, key: project.key) }
        if let description { body["encrypted_description"] = try await encrypt(description, key: project.key) }
        try await fence.check()
        let response: ProjectResponse = try await APIClient.shared.request(.patch, path: projectRoute(project), serverProfile: fence.serverProfile, body: body,
            expectedAccountID: fence.accountID, expectedScope: fence.scope, expectedTeamContext: .init(epoch: fence.teamContext.epoch, teamID: fence.teamContext.teamID))
        try await fence.check()
        guard let masterKey = try await CryptoManager.shared.loadMasterKey(for: fence.accountID) else {
            throw ProjectsWorkspaceError.missingMasterKey
        }
        return try await open(response.project, masterKey: masterKey, teamID: project.teamId, accountID: fence.accountID)
    }

    func createFolder(_ name: String, project: ProjectWorkspaceProject, parentID: String?, fence: ProjectsWorkspaceFence) async throws {
        guard project.permissions.manageOwnItems || project.permissions.manageAnyItems else {
            throw ProjectsWorkspaceError.invalidContext
        }
        let cleanName = name.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !cleanName.isEmpty else { throw ProjectsWorkspaceError.invalidResponse }
        let now = Int(Date().timeIntervalSince1970)
        let body: [String: Any] = ["folder_id": UUID().uuidString.lowercased(),
            "parent_folder_id": parentID as Any? ?? NSNull(),
            "encrypted_name": try await encrypt(cleanName, key: project.key),
            "encrypted_sort_key": try await encrypt(cleanName.lowercased(), key: project.key),
            "created_at": now, "updated_at": now, "position": now]
        try await fence.check()
        let _: Data = try await APIClient.shared.request(.post, path: projectRoute(project, suffix: "/folders"), serverProfile: fence.serverProfile, body: body,
            expectedAccountID: fence.accountID, expectedScope: fence.scope, expectedTeamContext: .init(epoch: fence.teamContext.epoch, teamID: fence.teamContext.teamID))
        try await fence.check()
    }

    func moveItem(_ itemID: String, project: ProjectWorkspaceProject, folderID: String?, fence: ProjectsWorkspaceFence) async throws {
        guard project.permissions.manageOwnItems || project.permissions.manageAnyItems else {
            throw ProjectsWorkspaceError.invalidContext
        }
        try await fence.check()
        let body: [String: Any] = ["folder_id": folderID as Any? ?? NSNull(),
            "updated_at": Int(Date().timeIntervalSince1970)]
        let path = projectRoute(project, suffix: "/items/\(Self.escaped(itemID))")
        let _: Data = try await APIClient.shared.request(.patch, path: path, serverProfile: fence.serverProfile, body: body,
            expectedAccountID: fence.accountID, expectedScope: fence.scope, expectedTeamContext: .init(epoch: fence.teamContext.epoch, teamID: fence.teamContext.teamID))
        try await fence.check()
    }

    func copyItem(_ item: ProjectWorkspaceItem, project: ProjectWorkspaceProject,
                  folderID: String?, fence: ProjectsWorkspaceFence) async throws {
        guard project.permissions.manageOwnItems || project.permissions.manageAnyItems else {
            throw ProjectsWorkspaceError.invalidContext
        }
        try await fence.check()
        let metadata = try JSONSerialization.data(withJSONObject: item.metadata)
        guard let metadataText = String(data: metadata, encoding: .utf8) else {
            throw ProjectsWorkspaceError.invalidResponse
        }
        let now = Int(Date().timeIntervalSince1970)
        let body: [String: Any] = ["project_item_id": UUID().uuidString.lowercased(),
            "folder_id": folderID.map { $0 as Any } ?? NSNull(), "item_type": item.kind,
            "target_id": item.targetID,
            "target_id_encrypted": try await encrypt(item.targetID, key: project.key),
            "encrypted_display_name": try await encrypt(item.name, key: project.key),
            "encrypted_note": try await encrypt("", key: project.key),
            "encrypted_metadata": try await encrypt(metadataText, key: project.key),
            "created_at": now, "updated_at": now, "position": now]
        try await fence.check()
        let _: Data = try await APIClient.shared.request(.post,
            path: projectRoute(project, suffix: "/items"), serverProfile: fence.serverProfile, body: body,
            expectedAccountID: fence.accountID, expectedScope: fence.scope, expectedTeamContext: .init(epoch: fence.teamContext.epoch, teamID: fence.teamContext.teamID))
        try await fence.check()
    }

    func updateWriteMode(_ mode: ProjectWorkspaceWriteMode, project: ProjectWorkspaceProject, fence: ProjectsWorkspaceFence) async throws -> ProjectWorkspaceSettings {
        guard project.permissions.settings else { throw ProjectsWorkspaceError.invalidContext }
        try await fence.check()
        let body: [String: Any] = ["write_mode": mode.rawValue, "updated_at": Int(Date().timeIntervalSince1970)]
        let _: SettingsResponse = try await APIClient.shared.request(.patch, path: projectRoute(project, suffix: "/settings"), serverProfile: fence.serverProfile, body: body,
            expectedAccountID: fence.accountID, expectedScope: fence.scope, expectedTeamContext: .init(epoch: fence.teamContext.epoch, teamID: fence.teamContext.teamID))
        try await fence.check()
        return try await settings(project: project, fence: fence)
    }

    func activateFocus(project: ProjectWorkspaceProject, chatID: String, focusID: String, instruction: String, fence: ProjectsWorkspaceFence) async throws {
        try await fence.check()
        let body = ["chat_id": chatID, "focus_id": focusID, "instruction": instruction]
        let _: Data = try await APIClient.shared.request(.post, path: projectRoute(project, suffix: "/focus/activate"), serverProfile: fence.serverProfile, body: body,
            expectedAccountID: fence.accountID, expectedScope: fence.scope, expectedTeamContext: .init(epoch: fence.teamContext.epoch, teamID: fence.teamContext.teamID))
        try await fence.check()
        PendingProjectFocusStore.shared.clearForExplicitActivation(chatID: chatID)
    }

    func deleteProject(_ project: ProjectWorkspaceProject, fence: ProjectsWorkspaceFence) async throws {
        guard project.permissions.delete else { throw ProjectsWorkspaceError.invalidContext }
        try await fence.check()
        let path = projectRoute(project) + (project.teamId == nil ? "?" : "&")
            + "confirmation_project_id=\(Self.escaped(project.id))"
        let _: Data = try await APIClient.shared.request(.delete, path: path, serverProfile: fence.serverProfile,
            expectedAccountID: fence.accountID, expectedScope: fence.scope, expectedTeamContext: .init(epoch: fence.teamContext.epoch, teamID: fence.teamContext.teamID))
        try await fence.check()
    }

    private func decryptedEmbed(_ item: ProjectWorkspaceItem, project: ProjectWorkspaceProject,
                                fence: ProjectsWorkspaceFence) async throws -> (EncryptedEmbed, [String: Any], SymmetricKey) {
        guard item.kind == "embed" else { throw ProjectsWorkspaceError.invalidResponse }
        try await fence.check()
        let path = route("/v1/embeds/\(Self.escaped(item.targetID))/encrypted?project_id=\(Self.escaped(project.id))", teamID: project.teamId)
        let response: EncryptedEmbedResponse = try await APIClient.shared.request(.get, path: path, serverProfile: fence.serverProfile,
            expectedAccountID: fence.accountID, expectedScope: fence.scope, expectedTeamContext: .init(epoch: fence.teamContext.epoch, teamID: fence.teamContext.teamID))
        try await fence.check()
        guard let wrapper = response.embedKeys.first(where: { $0.keyType == "project" }) else {
            throw ProjectsWorkspaceError.missingProjectKey
        }
        let keyData = try await CryptoManager.shared.decryptBlob(base64String: wrapper.encryptedEmbedKey, key: project.key)
        guard keyData.count == 32 else { throw ProjectsWorkspaceError.missingProjectKey }
        let embedKey = SymmetricKey(data: keyData)
        let content = try await CryptoManager.shared.decryptContent(base64String: response.embed.encryptedContent, key: embedKey)
        try await fence.check()
        let parsed = EmbedRecord.parseContent(content)
        guard !parsed.isEmpty else { throw ProjectsWorkspaceError.invalidResponse }
        return (response.embed, parsed, embedKey)
    }

    func readStoredFile(_ item: ProjectWorkspaceItem, project: ProjectWorkspaceProject,
                        fence: ProjectsWorkspaceFence) async throws -> [String: Any] {
        try await decryptedEmbed(item, project: project, fence: fence).1
    }

    func openLinkedEmbed(_ item: ProjectWorkspaceItem, project: ProjectWorkspaceProject,
                         fence: ProjectsWorkspaceFence) async throws -> EmbedRecord {
        let (head, content, embedKey) = try await decryptedEmbed(item, project: project, fence: fence)
        let decryptedType: String?
        if let encryptedType = head.encryptedType, !encryptedType.isEmpty {
            decryptedType = try await CryptoManager.shared.decryptContent(base64String: encryptedType,
                                                                            key: embedKey)
        } else {
            decryptedType = nil
        }
        try await fence.check()
        guard let type = decryptedType ?? content["type"] as? String, !type.isEmpty,
              let revision = head.versionNumber, revision > 0 else {
            throw ProjectsWorkspaceError.invalidResponse
        }
        let appID = content["app_id"] as? String
        let skillID = content["skill_id"] as? String
        let parentID = content["parent_embed_id"] as? String
        let embedIDs = content["embed_ids"] as? String
        return EmbedRecord(id: item.targetID, type: type, status: head.status ?? .finished,
            data: .raw(content.mapValues { AnyCodable($0) }), parentEmbedId: parentID,
            appId: appID, skillId: skillID, embedIds: embedIDs,
            versionNumber: revision, createdAt: head.createdAt.map(String.init))
    }
}


// Specification: specifications/features/focus-modes/specification.yml
// Assertions: focus-modes.project-recommendation-catalog, focus-modes.project-recommendation-full-assessment,
// focus-modes.project-authoring-click, focus-modes.project-authoring-persistence
// Web source: frontend/packages/ui/src/services/projectAuthoringClientService.ts
// Web source: frontend/packages/openmates-cli/src/cliProjectAuthoringSave.ts
@MainActor
struct NativeProjectAuthoringJob: Identifiable {
    var value: [String: Any]
    let recommendationID: String
    let fence: ProjectsWorkspaceFence
    var id: String { value["job_id"] as? String ?? "" }
    var status: String { value["status"] as? String ?? "failed" }
    var draft: [String: Any]? { value["draft"] as? [String: Any] }
    var projectID: String { value["project_id"] as? String ?? "" }
    var chatID: String { value["chat_id"] as? String ?? "" }
}

/// Explicit clicks start authoring. Assessments and history parsing never do.
/// All drafts remain transient; only the existing encrypted file CAS is durable.
@MainActor
final class NativeProjectAuthoringClient: ObservableObject {
    static let shared = NativeProjectAuthoringClient()
    @Published private(set) var jobs: [String: NativeProjectAuthoringJob] = [:]
    private var starts = Set<String>()
    private var assessments = Set<String>()
    private var monitors: [String: Task<Void, Never>] = [:]
    private let service = ProjectsWorkspaceService()

    func reset() {
        monitors.values.forEach { $0.cancel() }; monitors.removeAll()
        jobs.removeAll(); starts.removeAll(); assessments.removeAll()
    }

    static func boundedHistory(_ messages: [Message]) -> [[String: String]] {
        let history = messages.compactMap { message -> [String: String]? in
            guard message.role == .user || message.role == .assistant,
                  let content = message.content, !content.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else { return nil }
            return ["role": message.role.rawValue, "content": content]
        }
        if history.count <= 60 && history.reduce(0, { $0 + ($1["content"]?.count ?? 0) }) <= 12_000 { return history }
        let recent = history.suffix(8).map { ["role": $0["role"]!, "content": String($0["content"]!.prefix(1000))] }
        if history.count > 8, let first = history.first(where: { $0["role"] == "user" }) {
            return [["role": "user", "content": String(first["content"]!.prefix(3000))]] + recent
        }
        return recent
    }

    static func itemRevision(_ item: [String: Any]) -> String {
        let fields = ["updated_at", "encrypted_metadata", "encrypted_note", "target_id_hash", "deleted_target_state"]
        let text = fields.map { name -> String in
            guard let value = item[name], !(value is NSNull) else { return "" }
            if let string = value as? String { return string }
            if let number = value as? NSNumber { return number.stringValue == "0" ? "" : number.stringValue }
            return ""
        }.joined(separator: "\0")
        return ProjectHostedFileExecutor.sha256(text)
    }

    static func parseFocusDocument(_ markdown: String) throws -> [String: Any] {
        guard markdown.count <= 96_000, markdown.hasPrefix("---\n"),
              let end = markdown.range(of: "\n---", range: markdown.index(markdown.startIndex, offsetBy: 4)..<markdown.endIndex) else {
            throw ProjectsWorkspaceError.invalidResponse
        }
        let header = String(markdown[markdown.index(markdown.startIndex, offsetBy: 4)..<end.lowerBound])
        let metadata = try guideMetadata(header)
        let remainder = markdown[end.upperBound...]
        guard remainder.isEmpty || remainder.hasPrefix("\n") else { throw ProjectsWorkspaceError.invalidResponse }
        let instruction = remainder.trimmingCharacters(in: .whitespacesAndNewlines)
        let applicability = metadata["preprocessor_hint"] ?? metadata["preprocessor-hint"] ?? metadata["when_to_use"]
        guard let name = metadata["name"] as? String, !name.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty, name.count <= 200,
              let description = metadata["description"] as? String, !description.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty, description.count <= 2000,
              let when = applicability as? String, !when.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty, when.count <= 2000,
              !instruction.isEmpty, instruction.count <= 64_000 else { throw ProjectsWorkspaceError.invalidResponse }
        let phases = metadata["phases"] as? [[String: Any]] ?? []
        guard (metadata["phases"] == nil || metadata["phases"] is [[String: Any]]), phases.count <= 16 else { throw ProjectsWorkspaceError.invalidResponse }
        var ids = Set<String>()
        for phase in phases {
            guard let id = phase["id"] as? String, ids.insert(id).inserted,
                  id.range(of: "^[a-zA-Z0-9_-]{1,80}$", options: .regularExpression) != nil,
                  let title = phase["name"] as? String, !title.isEmpty, title.count <= 120,
                  let text = phase["instructions"] as? String, !text.isEmpty, text.count <= 16_000 else { throw ProjectsWorkspaceError.invalidResponse }
        }
        return ["name": name, "description": description, "when_to_use": when,
                "instructions": instruction, "phases": phases]
    }

    private static func escaped(_ value: String) -> String {
        value.addingPercentEncoding(withAllowedCharacters: CharacterSet(charactersIn:
            "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-._~")) ?? ""
    }
    private func route(_ path: String, teamID: String?) -> String {
        guard let teamID else { return path }
        return path + (path.contains("?") ? "&" : "?") + "team_id=" + Self.escaped(teamID)
    }
    private func request(_ method: HTTPMethod, path: String, body: [String: Any]? = nil,
                         fence: ProjectsWorkspaceFence) async throws -> [String: Any] {
        try await fence.check()
        let data: Data
        if let body {
            data = try await APIClient.shared.request(method, path: path, serverProfile: fence.serverProfile, body: body,
                expectedAccountID: fence.accountID, expectedScope: fence.scope,
                expectedTeamContext: .init(epoch: fence.teamContext.epoch, teamID: fence.teamContext.teamID))
        } else {
            data = try await APIClient.shared.request(method, path: path, serverProfile: fence.serverProfile,
                expectedAccountID: fence.accountID, expectedScope: fence.scope,
                expectedTeamContext: .init(epoch: fence.teamContext.epoch, teamID: fence.teamContext.teamID))
        }
        try await fence.check()
        guard let value = try JSONSerialization.jsonObject(with: data) as? [String: Any] else { throw ProjectsWorkspaceError.invalidResponse }
        return value
    }
    private func activeFocus(chatID: String, projectID: String, fence: ProjectsWorkspaceFence) async throws -> [String: Any] {
        let result = try await request(.get, path: "/v1/projects/focus/current?chat_id=" + Self.escaped(chatID), fence: fence)
        guard let focus = result["focus"] as? [String: Any], focus["active"] as? Bool == true,
              focus["project_id"] as? String == projectID,
              (focus["team_id"] as? String) == fence.teamContext.teamID else { throw ProjectsWorkspaceError.invalidContext }
        return focus
    }
    private func fresh(_ focus: [String: Any], chatID: String, projectID: String, fence: ProjectsWorkspaceFence) async throws {
        let current = try await activeFocus(chatID: chatID, projectID: projectID, fence: fence)
        guard current["focus_id"] as? String == focus["focus_id"] as? String,
              current["specialist_focus_id"] as? String == focus["specialist_focus_id"] as? String else { throw ProjectsWorkspaceError.invalidContext }
    }
    private func detail(_ project: ProjectWorkspaceProject, fence: ProjectsWorkspaceFence) async throws -> [[String: Any]] {
        let result = try await request(.get, path: route("/v1/projects/" + Self.escaped(project.id), teamID: project.teamId), fence: fence)
        guard let items = result["items"] as? [[String: Any]] else { throw ProjectsWorkspaceError.invalidResponse }
        return items
    }
    private func metadata(_ item: [String: Any], project: ProjectWorkspaceProject) async throws -> [String: Any] {
        guard let ciphertext = item["encrypted_metadata"] as? String, !ciphertext.isEmpty else { return [:] }
        let plaintext = try await CryptoManager.shared.decryptContent(base64String: ciphertext, key: project.key)
        guard let data = plaintext.data(using: .utf8), let object = try JSONSerialization.jsonObject(with: data) as? [String: Any] else { throw ProjectsWorkspaceError.invalidResponse }
        return object
    }
    private func target(_ item: [String: Any], project: ProjectWorkspaceProject) async throws -> String {
        guard let ciphertext = item["target_id_encrypted"] as? String else { throw ProjectsWorkspaceError.invalidResponse }
        return try await CryptoManager.shared.decryptContent(base64String: ciphertext, key: project.key)
    }
    private func selectedFocus(_ id: String, revision: String, items: [[String: Any]], project: ProjectWorkspaceProject,
                               chatID: String, fence: ProjectsWorkspaceFence) async throws -> [String: Any] {
        guard let item = items.first(where: { $0["project_item_id"] as? String == id && $0["item_type"] as? String == "embed" && ($0["deleted_target_state"] == nil || $0["deleted_target_state"] is NSNull) }),
              Self.itemRevision(item) == revision, let chatKey = ChatKeyManager.shared.key(for: chatID) else { throw ProjectsWorkspaceError.invalidContext }
        _ = chatKey
        let metadata = try await metadata(item, project: project)
        guard let path = (metadata["path"] ?? metadata["display_path"]) as? String,
              path.hasPrefix(".openmates/focuses/") else { throw ProjectsWorkspaceError.invalidContext }
        let text = try await readMarkdown(item: item, path: path, project: project, chatID: chatID, fence: fence)
        return try Self.parseFocusDocument(text)
    }

    /// Resolve a selected stored path through the ordinary protected/ignored-path reader.
    private func readMarkdown(item: [String: Any], path: String, project: ProjectWorkspaceProject,
                              chatID: String, fence: ProjectsWorkspaceFence) async throws -> String {
        guard let chatKey = ChatKeyManager.shared.key(for: chatID), ProjectWorkspacePath.normalized(path) != nil else { throw ProjectsWorkspaceError.invalidContext }
        let focus = try await activeFocus(chatID: chatID, projectID: project.id, fence: fence)
        let adapter = ProjectHostedWorkspaceAdapter(project: project, chatKey: chatKey, fence: fence,
            commit: { _ in throw ProjectsWorkspaceError.invalidContext })
        let descriptor = ProjectFileJob(contextChatID: chatID, projectID: project.id, path: path)
        let result = try await ProjectHostedFileExecutor(adapter: adapter).execute(job: descriptor, mutation: nil,
            approvedIgnoredRead: nil, fence: fence, validateAuthority: {
                guard OfflineStore.shared.scopeGeneration == fence.scope else { throw CancellationError() }
            })
        try await fresh(focus, chatID: chatID, projectID: project.id, fence: fence)
        let latest = try await detail(project, fence: fence)
        guard let current = latest.first(where: { $0["project_item_id"] as? String == item["project_item_id"] as? String }),
              Self.itemRevision(current) == Self.itemRevision(item), let content = result["content"] as? String,
              result["truncated"] as? Bool != true else { throw ProjectsWorkspaceError.invalidContext }
        return content
    }

    // Specification: specifications/features/chats/specification.yml
    // Assertions: chats.direction.reviewed-correction
    /// Only a current, actually approved Plan already linked to this chat is projected.
    /// Approval metadata is read fresh; the server additionally validates its durable revision.
    private func acceptedPlanContext(chatID: String, fence: ProjectsWorkspaceFence) async throws -> [String: Any]? {
        let response = try await request(.get, path: route("/v1/user-plans?chat_id=" + Self.escaped(chatID) + "&limit=20", teamID: fence.teamContext.teamID), fence: fence)
        guard let plans = response["plans"] as? [[String: Any]] else { throw ProjectsWorkspaceError.invalidResponse }
        for candidate in plans.prefix(20) {
            guard let id = candidate["plan_id"] as? String,
                  Self.acceptedPlanIdentity(candidate, chatID: chatID) != nil else { continue }
            let detail = try await request(.get, path: route("/v1/user-plans/" + Self.escaped(id), teamID: fence.teamContext.teamID), fence: fence)
            guard let plan = detail["plan"] as? [String: Any], let identity = Self.acceptedPlanIdentity(plan, chatID: chatID),
                  let wrapper = (plan["key_wrappers"] as? [[String: Any]])?.first(where: { $0["key_type"] as? String == "master" }),
                  let encryptedKey = wrapper["encrypted_plan_key"] as? String,
                  let masterKey = try await CryptoManager.shared.loadMasterKey(for: fence.accountID) else { continue }
            let planKey = try await CryptoManager.shared.unwrapChatKey(encryptedChatKeyBase64: encryptedKey, masterKey: masterKey)
            var fields: [String: String] = [:]
            for field in ["goal", "scope_in", "scope_out", "constraints"] {
                if let encrypted = plan["encrypted_" + field] as? String, !encrypted.isEmpty {
                    fields[field] = try await CryptoManager.shared.decryptContent(base64String: encrypted, key: planKey)
                    try await fence.check()
                }
            }
            guard let summary = Self.acceptedPlanSummary(fields) else { continue }
            let current = try await request(.get, path: route("/v1/user-plans/" + Self.escaped(id), teamID: fence.teamContext.teamID), fence: fence)
            guard let freshPlan = current["plan"] as? [String: Any],
                  let freshIdentity = Self.acceptedPlanIdentity(freshPlan, chatID: chatID),
                  NSDictionary(dictionary: identity).isEqual(to: freshIdentity) else { continue }
            var snapshot = identity; snapshot["summary"] = summary
            return snapshot
        }
        return nil
    }

    static func specialistItemID(projectID: String, focusID: String?) -> String? {
        guard let focusID else { return nil }
        let prefix = "project-focus:" + projectID + ":"
        return focusID.hasPrefix(prefix) ? String(focusID.dropFirst(prefix.count)) : focusID
    }

    static func acceptedPlanIdentity(_ plan: [String: Any], chatID: String) -> [String: Any]? {
        guard let id = plan["plan_id"] as? String, UUID(uuidString: id) != nil,
              plan["primary_chat_id"] as? String == chatID,
              ["active", "executing", "running_checks", "blocked"].contains(plan["status"] as? String ?? ""),
              let version = plan["version"] as? Int, version >= 1,
              plan["approval_state"] as? String == "approved",
              let revision = plan["approved_revision_id"] as? String, !revision.isEmpty,
              plan["submitted_revision_id"] as? String == revision else { return nil }
        return ["plan_id": id, "version": version, "approved_revision_id": revision]
    }

    static func acceptedPlanSummary(_ fields: [String: String]) -> String? {
        guard let goal = fields["goal"], !goal.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else { return nil }
        let labels = [("goal", "Goal"), ("scope_in", "Scope in"), ("scope_out", "Scope out"), ("constraints", "Constraints")]
        let summary = labels.compactMap { key, label -> String? in
            guard let text = fields[key], !text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else { return nil }
            return label + ": " + String(text.prefix(key == "goal" ? 1600 : 800))
        }.joined(separator: "\n")
        return String(summary.prefix(4000))
    }

    /// First-party transient request snapshots: metadata selection precedes private body reads.
    /// No historical card can activate a Project or supply trusted access.
    func requestContext(chatID: String, text: String) async throws -> [String: Any] {
        guard let accountID = await AuthManager.currentUserId(), await AuthManager.isRecoveryEligibleDevice() else { return [:] }
        let fence = ProjectsWorkspaceFence(accountID: accountID)
        var result: [String: Any] = [:]
        if let snapshot = try? await acceptedPlanContext(chatID: chatID, fence: fence) { result["accepted_plan_context"] = snapshot }
        try await fence.check()
        var rules: [[String: Any]] = []
        if let ciphertext = AuthManager.notificationSession.currentUser?.encryptedSettings,
           let masterKey = try await CryptoManager.shared.loadMasterKey(for: accountID) {
            let plaintext = try await CryptoManager.shared.decryptContent(base64String: ciphertext, key: masterKey)
            try await fence.check()
            if let data = plaintext.data(using: .utf8), let settings = try JSONSerialization.jsonObject(with: data) as? [String: Any],
               let supplied = settings["rule_documents"] as? [[String: Any]], supplied.count <= 24 {
                for entry in supplied {
                    guard let id = entry["id"] as? String, !id.isEmpty, id.count <= 240, !id.hasPrefix("app:"),
                          let document = entry["document"] as? String, Self.validRuleDocument(document) else { throw ProjectsWorkspaceError.invalidResponse }
                    rules.append(["id": id, "source": "personal", "document": document])
                }
            }
        }
        guard Set(rules.compactMap { $0["id"] as? String }).count == rules.count,
              rules.reduce(0, { $0 + ($1["document"] as? String ?? "").count }) <= 64_000 else { throw ProjectsWorkspaceError.invalidResponse }
        if !rules.isEmpty { result["custom_rule_documents"] = rules }
        // Safe authority metadata may clear a past decline, but never a waiting countdown.
        let previous = try await request(.get, path: "/v1/projects/focus/current?chat_id=" + Self.escaped(chatID), fence: fence)
        if (previous["focus"] as? [String: Any])?["active"] as? Bool != true {
            PendingProjectFocusStore.shared.clearAfterNoActiveBase(chatID: chatID)
        }
        // A pending Project cannot be read until its live deadline is confirmed.
        try await PendingProjectFocusStore.shared.confirmBeforeContext(chatID: chatID)
        let current = try await request(.get, path: "/v1/projects/focus/current?chat_id=" + Self.escaped(chatID), fence: fence)
        guard let focus = current["focus"] as? [String: Any], focus["active"] as? Bool == true,
              let projectID = focus["project_id"] as? String,
              focus["team_id"] as? String == fence.teamContext.teamID else { return result }
        let project = try await service.getProject(accountID: accountID, projectID: projectID, teamID: focus["team_id"] as? String, fence: fence)
        let contents = try await request(.get, path: route("/v1/projects/" + Self.escaped(project.id), teamID: project.teamId), fence: fence)
        guard let items = contents["items"] as? [[String: Any]] else { throw ProjectsWorkspaceError.invalidResponse }
        var folderSnapshots: [String: String] = [:]
        var focusCatalog: [[String: Any]] = []
        var focusItems: [String: (item: [String: Any], path: String)] = [:]
        var referenceCatalog: [[String: Any]] = []
        var referenceItems: [String: (item: [String: Any], path: String)] = [:]
        var bodyTotal = 0
        for item in items where item["deleted_target_state"] == nil || item["deleted_target_state"] is NSNull {
            guard ["embed", "upload"].contains(item["item_type"] as? String ?? ""), let id = item["project_item_id"] as? String else { continue }
            let metadata = try await metadata(item, project: project)
            guard let path = (metadata["path"] ?? metadata["display_path"]) as? String, ProjectWorkspacePath.normalized(path) != nil else { continue }
            if path.range(of: "^\\.openmates/rules/[a-zA-Z0-9_-]+\\.md$", options: .regularExpression) != nil {
                let document = try await readMarkdown(item: item, path: path, project: project, chatID: chatID, fence: fence)
                guard Self.validRuleDocument(document) else { throw ProjectsWorkspaceError.invalidResponse }
                rules.append(["id": id, "source": "project", "project_id": project.id, "document": document])
            } else if let title = metadata["focus_title"] as? String, let description = metadata["focus_description"] as? String,
                      let when = metadata["focus_when_to_use"] as? String,
                      path.range(of: "^\\.openmates/focuses/[a-zA-Z0-9_-]+/SKILL\\.md$", options: .regularExpression) != nil {
                focusCatalog.append(["id": id, "title": String(title.prefix(180)), "summary": String(description.prefix(1200)),
                    "when_to_use": String(when.prefix(1200)), "revision": Self.itemRevision(item)])
                focusItems[id] = (item, path)
            } else if path.range(of: "^\\.openmates/(specs|facts)/[a-zA-Z0-9_/-]+\\.md$", options: .regularExpression) != nil {
                referenceCatalog.append(["kind": path.hasPrefix(".openmates/specs/") ? "spec" : "fact", "id": id,
                    "title": String((metadata["title"] as? String ?? path).prefix(200)),
                    "description": String((metadata["description"] as? String ?? metadata["summary"] as? String ?? "").prefix(640)), "revision": Self.itemRevision(item)])
                referenceItems[id] = (item, path)
            }
        }
        guard rules.count <= 24, Set(rules.compactMap { $0["id"] as? String }).count == rules.count,
              rules.reduce(0, { $0 + ($1["document"] as? String ?? "").count }) <= 64_000 else { throw ProjectsWorkspaceError.invalidResponse }
        result["custom_rule_documents"] = rules
        let specialist = Self.specialistItemID(projectID: project.id, focusID: focus["specialist_focus_id"] as? String)
        if let specialist {
            focusCatalog.sort { ($0["id"] as? String == specialist ? 0 : 1) < ($1["id"] as? String == specialist ? 0 : 1) }
        }
        focusCatalog = Array(focusCatalog.prefix(20)); result["project_focus_catalog"] = focusCatalog
        if !focusCatalog.isEmpty {
            let candidates = focusCatalog.map { entry -> [String: Any] in
                ["kind": "focus", "id": entry["id"]!, "title": entry["title"]!, "description": String((entry["summary"] as? String ?? "").prefix(640)),
                 "when_to_use": String((entry["when_to_use"] as? String ?? "").prefix(640)), "revision": entry["revision"]!]
            }
            let selection = try await request(.post, path: route("/v1/projects/" + Self.escaped(project.id) + "/context/select", teamID: project.teamId),
                body: ["chat_id": chatID, "text": String(text.prefix(8000)), "candidates": candidates], fence: fence)
            var selected = Array((selection["selected"] as? [[String: Any]] ?? []).filter { chosen in
                chosen["kind"] as? String == "focus" && candidates.contains { $0["id"] as? String == chosen["id"] as? String && $0["revision"] as? String == chosen["revision"] as? String }
            }.prefix(4))
            if let specialist, let candidate = candidates.first(where: { $0["id"] as? String == specialist }),
               !selected.contains(where: { $0["id"] as? String == specialist }) { selected.append(candidate) }
            var documents: [[String: Any]] = []
            for candidate in selected {
                guard let id = candidate["id"] as? String, let stored = focusItems[id] else { continue }
                let document = try await readMarkdown(item: stored.item, path: stored.path, project: project, chatID: chatID, fence: fence)
                _ = try Self.parseFocusDocument(document); bodyTotal += document.count
                guard bodyTotal <= 60_000 else { throw ProjectsWorkspaceError.invalidResponse }
                documents.append(["item_id": id, "revision": candidate["revision"]!, "document": document])
            }
            result["project_focus_documents"] = documents
        }
        referenceCatalog = Array(referenceCatalog.prefix(20))
        for folder in (contents["folders"] as? [[String: Any]] ?? []).prefix(24 - referenceCatalog.count) {
            guard let id = folder["folder_id"] as? String, let encrypted = folder["encrypted_name"] as? String else { continue }
            let name = try await CryptoManager.shared.decryptContent(base64String: encrypted, key: project.key)
            try await fence.check()
            let bytes = try JSONSerialization.data(withJSONObject: ["name": name, "parent_reference": folder["hashed_parent_folder_id"] ?? NSNull()])
            folderSnapshots[id] = String(decoding: bytes, as: UTF8.self)
            referenceCatalog.append(["kind": "folder", "id": id, "title": String(name.prefix(200)), "description": "", "revision": Self.itemRevision(folder)])
        }
        if !referenceCatalog.isEmpty {
            let selection = try await request(.post, path: route("/v1/projects/" + Self.escaped(project.id) + "/context/select", teamID: project.teamId),
                body: ["chat_id": chatID, "text": String(text.prefix(8000)), "candidates": referenceCatalog], fence: fence)
            let selected = Array((selection["selected"] as? [[String: Any]] ?? []).prefix(4))
            var documents: [[String: Any]] = []; var referenceTotal = 0
            for chosen in selected {
                guard let id = chosen["id"] as? String, let candidate = referenceCatalog.first(where: {
                    $0["id"] as? String == id && $0["kind"] as? String == chosen["kind"] as? String && $0["revision"] as? String == chosen["revision"] as? String
                }) else { continue }
                let document: String
                if candidate["kind"] as? String == "folder", let snapshot = folderSnapshots[id] {
                    let current = try await request(.get, path: route("/v1/projects/" + Self.escaped(project.id), teamID: project.teamId), fence: fence)
                    guard let folder = (current["folders"] as? [[String: Any]])?.first(where: { $0["folder_id"] as? String == id }),
                          Self.itemRevision(folder) == candidate["revision"] as? String else { throw ProjectsWorkspaceError.invalidContext }
                    document = snapshot
                } else if let stored = referenceItems[id] {
                    document = try await readMarkdown(item: stored.item, path: stored.path, project: project, chatID: chatID, fence: fence)
                } else { continue }
                referenceTotal += document.count
                guard !document.isEmpty, document.count <= 24_000, referenceTotal <= 48_000 else { throw ProjectsWorkspaceError.invalidResponse }
                documents.append(["item_id": id, "kind": candidate["kind"]!, "title": candidate["title"]!, "description": candidate["description"]!,
                                  "revision": candidate["revision"]!, "document": document])
            }
            result["project_context_documents"] = documents
        }
        try await fresh(focus, chatID: chatID, projectID: project.id, fence: fence)
        return result
    }

    /// Preserve duplicate-key rejection before constructing dictionaries.
    private static func guideMetadata(_ yaml: String) throws -> [String: Any] {
        guard yaml.range(of: "(^|[\\s\\[,])[*&][A-Za-z0-9_-]+", options: .regularExpression) == nil,
              let root = try Yams.compose(yaml: yaml) else { throw ProjectsWorkspaceError.invalidResponse }
        var nodes = 0
        func validate(_ node: Yams.Node, depth: Int) -> Bool {
            nodes += 1
            guard depth <= 20, nodes <= 2048 else { return false }
            switch node {
            case .scalar: return true
            case let .sequence(sequence): return sequence.allSatisfy { validate($0, depth: depth + 1) }
            case let .mapping(mapping):
                var keys = Set<String>()
                return mapping.allSatisfy { pair in
                    guard let key = pair.key.scalar?.string, key != "<<", keys.insert(key).inserted else { return false }
                    return validate(pair.value, depth: depth + 1)
                }
            @unknown default: return false
            }
        }
        guard validate(root, depth: 0), let dictionary = root.any as? [String: Any] else { throw ProjectsWorkspaceError.invalidResponse }
        return dictionary
    }

    static func validRuleDocument(_ document: String) -> Bool {
        let text = document.replacingOccurrences(of: "\r\n", with: "\n")
        guard text.count <= 24_000, text.hasPrefix("---\n"),
              let end = text.range(of: "\n---", range: text.index(text.startIndex, offsetBy: 4)..<text.endIndex) else { return false }
        let header = String(text[text.index(text.startIndex, offsetBy: 4)..<end.lowerBound])
        guard let metadata = try? guideMetadata(header), Set(metadata.keys) == Set(["title", "description", "when_to_use"]) else { return false }
        let remainder = text[end.upperBound...]
        guard remainder.isEmpty || remainder.hasPrefix("\n") else { return false }
        let body = remainder.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !body.isEmpty, body.count <= 20_000 else { return false }
        for field in ["title", "description", "when_to_use"] {
            guard let value = metadata[field] as? String, !value.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty,
                  value.count <= (field == "title" ? 180 : 1200) else { return false }
        }
        return true
    }

    func completePendingFocus(_ record: PendingProjectFocusRecord) async throws {
        guard let accountID = await AuthManager.currentUserId() else { throw ProjectsWorkspaceError.invalidContext }
        let fence = ProjectsWorkspaceFence(accountID: accountID)
        let socket = AppSessionCoordinator.shared.webSocketManager
        let transport = socket.transportGeneration
        func current() throws {
            guard PendingProjectFocusStore.shared.isCurrent(record), record.scope == fence.scope,
                  socket.transportGeneration == transport else { throw CancellationError() }
        }
        try current()
        let confirmed = try await request(.post, path: route("/v1/projects/" + Self.escaped(record.projectID) + "/focus/countdown", teamID: fence.teamContext.teamID),
            body: ["chat_id": record.chatID, "activation_request_id": record.embedID], fence: fence)
        try current()
        guard confirmed["accepted"] as? Bool == true, confirmed["request_id"] as? String == record.embedID else { throw ProjectsWorkspaceError.invalidContext }
        // These are the first private Project reads, after the server confirms the live deadline.
        let project = try await service.getProject(accountID: accountID, projectID: record.projectID, teamID: fence.teamContext.teamID, fence: fence)
        try current()
        let settings = try await service.settings(project: project, fence: fence)
        try current()
        guard !settings.selectionRequired, let focusID = settings.focusID, let instruction = settings.focusInstruction, !instruction.isEmpty else { throw ProjectsWorkspaceError.invalidContext }
        var activated = false
        do {
            _ = try await request(.post, path: route("/v1/projects/" + Self.escaped(project.id) + "/focus/activate", teamID: project.teamId),
                body: ["chat_id": record.chatID, "activation_request_id": record.embedID, "focus_id": focusID, "instruction": instruction], fence: fence)
            activated = true; try current()
            let response = try await socket.sendAndWait(WSOutboundMessage(type: "project_focus_decision", payload:
                ["chat_id": record.chatID, "request_id": record.embedID, "accepted": true]),
                responseTypes: ["project_focus_decision_confirmed", "project_focus_decision_error"],
                matching: { $0["request_id"] as? String == record.embedID }, beforeSend: { try current() },
                preSendValidation: {
                    try current()
                    try PendingProjectFocusStore.shared.beginCommit(record)
                })
            try await fence.check(); try current()
            guard response.type == "project_focus_decision_confirmed" else { throw ProjectsWorkspaceError.invalidContext }
        } catch {
            if activated {
                // Decline atomically revokes only this activation request, preserving a newer manual base.
                try? await rejectPendingFocus(record)
            }
            throw error
        }
    }

    func rejectPendingFocus(_ record: PendingProjectFocusRecord) async throws {
        guard record.scope == OfflineStore.shared.scopeGeneration, await AuthManager.isRecoveryEligibleDevice() else { throw CancellationError() }
        let socket = AppSessionCoordinator.shared.webSocketManager
        let response = try await socket.sendAndWait(WSOutboundMessage(type: "project_focus_decision", payload:
            ["chat_id": record.chatID, "request_id": record.embedID, "accepted": false]),
            responseTypes: ["project_focus_decision_confirmed", "project_focus_decision_error"], matching: { $0["request_id"] as? String == record.embedID },
            beforeSend: { guard record.scope == OfflineStore.shared.scopeGeneration else { throw CancellationError() } })
        guard response.type == "project_focus_decision_confirmed" else { throw ProjectsWorkspaceError.invalidContext }
    }

    func assess(_ frame: [String: Any], messages: [Message]) async throws -> [[String: Any]] {
        guard let chatID = frame["chat_id"] as? String, let projectID = frame["project_id"] as? String,
              let messageID = frame["user_message_id"] as? String,
              let accountID = await AuthManager.currentUserId() else { return [] }
        let boundary = accountID + ":" + chatID + ":" + messageID
        guard assessments.insert(boundary).inserted else { return [] }
        let fence = ProjectsWorkspaceFence(accountID: accountID)
        let history = Self.boundedHistory(messages); guard !history.isEmpty else { return [] }
        let focus = try await activeFocus(chatID: chatID, projectID: projectID, fence: fence)
        let project = try await service.getProject(accountID: accountID, projectID: projectID, teamID: focus["team_id"] as? String, fence: fence)
        let items = try await detail(project, fence: fence)
        var catalog: [[String: Any]] = []
        var linkedWorkflowIDs = Set<String>()
        for item in items where item["deleted_target_state"] == nil || item["deleted_target_state"] is NSNull {
            if item["item_type"] as? String == "workflow" { linkedWorkflowIDs.insert(try await target(item, project: project)); continue }
            guard ["embed", "upload"].contains(item["item_type"] as? String ?? "") else { continue }
            let metadata = try await metadata(item, project: project)
            guard let title = metadata["focus_title"] as? String, let summary = metadata["focus_description"] as? String,
                  metadata["focus_when_to_use"] is String,
                  let path = metadata["display_path"] as? String,
                  path.range(of: "^\\.openmates/focuses/[a-zA-Z0-9_-]+/SKILL\\.md$", options: .regularExpression) != nil else { continue }
            catalog.append(["kind": "focus", "id": item["project_item_id"] as? String ?? "", "title": String(title.prefix(200)),
                            "summary": String(summary.prefix(640)), "revision": Self.itemRevision(item)])
        }
        if !linkedWorkflowIDs.isEmpty {
            let workflows = try await request(.get, path: route("/v1/workflows", teamID: project.teamId), fence: fence)
            for workflow in workflows["workflows"] as? [[String: Any]] ?? [] {
                guard let id = workflow["id"] as? String, linkedWorkflowIDs.contains(id),
                      let version = workflow["version"] as? Int, version >= 1,
                      let title = workflow["title"] as? String, workflow["status"] as? String != "deleted" else { continue }
                catalog.append(["kind": "workflow", "id": id, "title": String(title.prefix(200)),
                                "summary": String((workflow["description"] as? String ?? "").prefix(640)), "revision": String(version)])
            }
        }
        guard catalog.count <= 40 else { return [] } // Incomplete catalogs cannot safely propose a new Focus.
        try await fresh(focus, chatID: chatID, projectID: projectID, fence: fence)
        let result = try await request(.post, path: "/v1/projects/" + Self.escaped(projectID) + "/authoring/recommend",
            body: ["chat_id": chatID, "message_id": messageID, "team_id": project.teamId.map { $0 as Any } ?? NSNull(), "catalog": catalog, "history": history], fence: fence)
        var events: [[String: Any]] = []
        for supplied in result["recommendations"] as? [[String: Any]] ?? [] {
            var recommendation = supplied
            guard recommendation["chat_id"] as? String == chatID, recommendation["project_id"] as? String == projectID else { continue }
            if recommendation["action"] as? String == "inspect", recommendation["kind"] as? String == "focus" {
                guard let id = recommendation["target_id"] as? String, let revision = recommendation["expected_revision"] as? String,
                      catalog.contains(where: { $0["id"] as? String == id && $0["revision"] as? String == revision }),
                      let assessment = recommendation["recommendation_id"] as? String else { continue }
                let document = try await selectedFocus(id, revision: revision, items: items, project: project, chatID: chatID, fence: fence)
                try await fresh(focus, chatID: chatID, projectID: projectID, fence: fence)
                let inspected = try await request(.post, path: "/v1/projects/" + Self.escaped(projectID) + "/authoring/inspect",
                    body: ["assessment_id": assessment, "history": history, "document": document], fence: fence)
                guard let accepted = inspected["recommendation"] as? [String: Any] else { continue }
                recommendation = accepted
            }
            guard let parsed = ProjectAuthoringRecommendation.parse(recommendation), parsed.chatID == chatID, parsed.projectID == projectID else { continue }
            guard UUID(uuidString: parsed.id) != nil else { continue }
            recommendation["event_id"] = parsed.id
            recommendation["type"] = "project_authoring_recommendation"
            recommendation["created_at"] = (recommendation["created_at"] as? Int)
                ?? Int((parsed.expiresAt ?? Date().timeIntervalSince1970) - 1200)
            events.append(recommendation)
        }
        try await fresh(focus, chatID: chatID, projectID: projectID, fence: fence)
        return events
    }

    func start(_ recommendation: ProjectAuthoringRecommendation, messages: [Message]) async throws {
        guard let accountID = await AuthManager.currentUserId(), !recommendation.isExpired,
              jobs[recommendation.id] == nil, starts.insert(recommendation.id).inserted else { throw ProjectsWorkspaceError.invalidContext }
        defer { starts.remove(recommendation.id) }
        let fence = ProjectsWorkspaceFence(accountID: accountID)
        let focus = try await activeFocus(chatID: recommendation.chatID, projectID: recommendation.projectID, fence: fence)
        let project = try await service.getProject(accountID: accountID, projectID: recommendation.projectID, teamID: focus["team_id"] as? String, fence: fence)
        let history = Self.boundedHistory(messages); guard !history.isEmpty else { throw ProjectsWorkspaceError.invalidContext }
        let items = try await detail(project, fence: fence)
        var body: [String: Any] = ["recommendation_id": recommendation.id, "expected_revision": recommendation.expectedRevision.map { $0 as Any } ?? NSNull(),
                                   "history": history, "timezone": TimeZone.current.identifier]
        if recommendation.kind == "focus", recommendation.action == "update" {
            guard let id = recommendation.targetID, let revision = recommendation.expectedRevision else { throw ProjectsWorkspaceError.invalidContext }
            body["target"] = try await selectedFocus(id, revision: revision, items: items, project: project, chatID: recommendation.chatID, fence: fence)
        } else if recommendation.kind == "workflow", let id = recommendation.targetID {
            for item in items where item["item_type"] as? String == "workflow" {
                guard try await target(item, project: project) == id else { continue }
                let currentMetadata = try await metadata(item, project: project)
                body["remote_binding"] = currentMetadata["remote_workflow_file"]
                break
            }
        }
        try await fresh(focus, chatID: recommendation.chatID, projectID: recommendation.projectID, fence: fence)
        let result = try await request(.post, path: "/v1/projects/" + Self.escaped(project.id) + "/authoring/jobs", body: body, fence: fence)
        guard let job = result["job"] as? [String: Any], job["job_id"] is String,
              job["project_id"] as? String == project.id, job["chat_id"] as? String == recommendation.chatID else { throw ProjectsWorkspaceError.invalidResponse }
        jobs[recommendation.id] = NativeProjectAuthoringJob(value: job, recommendationID: recommendation.id, fence: fence)
        monitor(recommendation.id)
    }

    private func monitor(_ recommendationID: String) {
        monitors[recommendationID]?.cancel()
        monitors[recommendationID] = Task { @MainActor [weak self] in
            guard let self else { return }
            defer { self.monitors.removeValue(forKey: recommendationID) }
            for _ in 0..<150 {
                guard !Task.isCancelled, let job = self.jobs[recommendationID], ["running", "pending_file"].contains(job.status) else { return }
                do { try await Task.sleep(for: .seconds(2)); try await self.refresh(recommendationID) }
                catch { return }
            }
        }
    }

    func refresh(_ recommendationID: String) async throws {
        guard var job = jobs[recommendationID] else { throw ProjectsWorkspaceError.invalidContext }
        let result = try await request(.get, path: "/v1/projects/" + Self.escaped(job.projectID) + "/authoring/jobs/" + Self.escaped(job.id), fence: job.fence)
        guard let value = result["job"] as? [String: Any], value["job_id"] as? String == job.id,
              value["project_id"] as? String == job.projectID, value["chat_id"] as? String == job.chatID else { throw ProjectsWorkspaceError.invalidResponse }
        job.value = value; jobs[recommendationID] = job
        if job.status == "needs_binding_save" { try await save(recommendationID) }
        else if job.status == "needs_save" {
            let active = try await activeFocus(chatID: job.chatID, projectID: job.projectID, fence: job.fence)
            let project = try await service.getProject(accountID: job.fence.accountID, projectID: job.projectID,
                teamID: active["team_id"] as? String, fence: job.fence)
            if try await service.settings(project: project, fence: job.fence).writeMode == .applyAndShow { try await save(recommendationID) }
        }
    }

    private func updateMetadata(_ metadata: [String: Any], item: [String: Any], project: ProjectWorkspaceProject,
                                fence: ProjectsWorkspaceFence) async throws {
        let bytes = try JSONSerialization.data(withJSONObject: metadata)
        guard let text = String(data: bytes, encoding: .utf8), let id = item["project_item_id"] as? String else { throw ProjectsWorkspaceError.invalidResponse }
        let encrypted = try await CryptoManager.shared.encryptWithMasterKey(text, masterKey: project.key)
        let _: [String: Any] = try await request(.patch, path: route("/v1/projects/" + Self.escaped(project.id) + "/items/" + Self.escaped(id), teamID: project.teamId),
            body: ["encrypted_metadata": encrypted, "updated_at": Int(Date().timeIntervalSince1970), "expected_item_revision": Self.itemRevision(item)], fence: fence)
    }

    func save(_ recommendationID: String, approved: Bool = false) async throws {
        guard var job = jobs[recommendationID], ["needs_save", "needs_binding_save"].contains(job.status), let draft = job.draft else { throw ProjectsWorkspaceError.invalidContext }
        let focus = try await activeFocus(chatID: job.chatID, projectID: job.projectID, fence: job.fence)
        let project = try await service.getProject(accountID: job.fence.accountID, projectID: job.projectID, teamID: focus["team_id"] as? String, fence: job.fence)
        let items = try await detail(project, fence: job.fence)
        let operationID = "project-authoring:" + job.id
        var acknowledgment: [String: Any]
        let suffix: String
        if job.status == "needs_binding_save" {
            guard let id = job.value["project_item_id"] as? String,
                  let version = job.value["workflow_version_id"] as? String,
                  let binding = draft["remote_binding"] as? [String: Any], binding["project_id"] as? String == project.id,
                  binding["workflow_version_id"] as? String == version,
                  let item = items.first(where: { $0["project_item_id"] as? String == id && $0["item_type"] as? String == "workflow" }) else { throw ProjectsWorkspaceError.invalidContext }
            var metadata = try await metadata(item, project: project)
            guard Self.itemRevision(item) == job.value["expected_item_revision"] as? String || metadata["authoring_save_operation"] as? String == operationID else { throw ProjectsWorkspaceError.invalidContext }
            if metadata["authoring_save_operation"] as? String != operationID {
                metadata["remote_workflow_file"] = binding; metadata["remote_file_status"] = "saved"; metadata["authoring_save_operation"] = operationID
                try await fresh(focus, chatID: job.chatID, projectID: project.id, fence: job.fence)
                try await updateMetadata(metadata, item: item, project: project, fence: job.fence)
            }
            guard let saved = (try await detail(project, fence: job.fence)).first(where: { $0["project_item_id"] as? String == id }) else { throw ProjectsWorkspaceError.invalidResponse }
            acknowledgment = ["project_item_id": id, "saved_item_revision": Self.itemRevision(saved), "workflow_version_id": version]
            suffix = "/workflow-saved"
        } else {
            acknowledgment = try await saveFocus(job: job, draft: draft, project: project, items: items, focus: focus, approved: approved)
            suffix = "/saved"
        }
        try await fresh(focus, chatID: job.chatID, projectID: project.id, fence: job.fence)
        let result = try await request(.post, path: "/v1/projects/" + Self.escaped(project.id) + "/authoring/jobs/" + Self.escaped(job.id) + suffix,
            body: acknowledgment, fence: job.fence)
        guard let saved = result["job"] as? [String: Any], saved["job_id"] as? String == job.id else { throw ProjectsWorkspaceError.invalidResponse }
        job.value = saved; jobs[recommendationID] = job // Server acknowledgment alone determines readiness.
        if job.status == "ready" { ToastManager.shared.show(L("notifications.project_authoring.ready"), type: .success, dedupeKey: "project-authoring:" + job.id) }
    }

    private func saveFocus(job: NativeProjectAuthoringJob, draft: [String: Any], project: ProjectWorkspaceProject,
                           items: [[String: Any]], focus: [String: Any], approved: Bool) async throws -> [String: Any] {
        let operationID = "project-authoring:" + job.id
        guard draft["save_operation_id"] as? String == operationID, let id = job.value["result_id"] as? String,
              let markdown = draft["markdown"] as? String, markdown.utf8.count <= 200_000, !markdown.contains("\r"), !markdown.contains("\0"),
              let document = draft["document"] as? [String: Any],
              let expectedHead = draft["expected_embed_revision"] as? Int, expectedHead >= 0,
              let chatKey = ChatKeyManager.shared.key(for: job.chatID) else { throw ProjectsWorkspaceError.invalidResponse }
        let parsed = try Self.parseFocusDocument(markdown)
        guard NSDictionary(dictionary: parsed).isEqual(to: document) else { throw ProjectsWorkspaceError.invalidResponse }
        let item = items.first { $0["project_item_id"] as? String == id && $0["item_type"] as? String == "embed" }
        var metadata: [String: Any] = [:]
        if let item { metadata = try await self.metadata(item, project: project) }
        let metadataWasSaved = metadata["authoring_save_operation"] as? String == operationID
        if job.value["action"] as? String == "update" {
            guard let item, Self.itemRevision(item) == job.value["expected_revision"] as? String || metadata["authoring_save_operation"] as? String == operationID else { throw ProjectsWorkspaceError.invalidContext }
        } else if item != nil && metadata["authoring_save_operation"] as? String != operationID { throw ProjectsWorkspaceError.invalidContext }
        let pathValue = item == nil ? draft["path"] as? String : (metadata["path"] ?? metadata["display_path"]) as? String
        guard let pathValue, let path = ProjectWorkspacePath.normalized(pathValue),
              path.range(of: "^\\.openmates/focuses/[a-zA-Z0-9_/-]+(?:\\.md|/SKILL\\.md)$", options: .regularExpression) != nil else { throw ProjectsWorkspaceError.invalidResponse }
        let embedID: String
        if let item { embedID = try await target(item, project: project) }
        else { embedID = try ProjectHostedFileExecutor.identity(key: project.key, path: path, kind: "embed") }
        let socket = AppSessionCoordinator.shared.webSocketManager
        let transport = socket.transportGeneration
        let adapter = ProjectHostedWorkspaceAdapter(project: project, chatKey: chatKey, fence: job.fence, commit: { payload in
            try await self.fresh(focus, chatID: job.chatID, projectID: project.id, fence: job.fence)
            guard socket.transportGeneration == transport, payload["expected_revision"] as? Int == expectedHead else { throw ProjectsWorkspaceError.invalidContext }
            var payload = payload
            if var create = payload["create"] as? [String: Any] {
                create["project_item_id"] = id
                let encoded = try JSONSerialization.data(withJSONObject: metadata)
                create["encrypted_metadata"] = try await CryptoManager.shared.encryptWithMasterKey(String(decoding: encoded, as: UTF8.self), masterKey: project.key)
                payload["create"] = create
            }
            let requestID = UUID().uuidString.lowercased(); payload["request_id"] = requestID
            let response = try await socket.sendAndWait(WSOutboundMessage(type: "commit_embed_revision", payload: payload),
                responseType: "commit_embed_revision_result", timeout: .seconds(20), matching: { $0["request_id"] as? String == requestID }, beforeSend: {
                    guard socket.transportGeneration == transport, OfflineStore.shared.scopeGeneration == job.fence.scope else { throw CancellationError() }
                })
            try await self.fresh(focus, chatID: job.chatID, projectID: project.id, fence: job.fence)
            return response.fields
        })
        var original = ""
        if expectedHead > 0 {
            let head = try await adapter.readHead(embedID: embedID)
            guard [expectedHead, expectedHead + 1].contains(head.revision), let text = ["code", "content", "markdown", "text"].compactMap({ head.content[$0] as? String }).first else { throw ProjectsWorkspaceError.invalidContext }
            original = head.revision == expectedHead ? text : try await historicalText(embedID: embedID, revision: expectedHead, key: head.embedKey, project: project, fence: job.fence)
        }
        let mutation = try ProjectFileMutation(operation: expectedHead == 0 ? "create_file" : "update_file", operationID: operationID,
            arguments: expectedHead == 0 ? ["path": path, "expected_base": NSNull(), "content": markdown]
            : ["path": path, "expected_base": ProjectHostedFileExecutor.sha256(original), "patch": Self.replacementPatch(path: path, old: original, next: markdown)])
        let descriptor = ProjectFileJob(authoringOperationID: operationID, chatID: job.chatID, projectID: project.id, mutation: mutation)
        let digest = try mutation.commitment(projectID: project.id, chatID: job.chatID, key: project.key)
        let storedReceipt = try await adapter.receipt(embedID: embedID, job: descriptor, digest: digest)
        let receipt = storedReceipt?["status"] as? String == "committed" ? storedReceipt : nil
        let settings = try await service.settings(project: project, fence: job.fence)
        guard !settings.selectionRequired else { throw ProjectsWorkspaceError.invalidContext }
        if receipt == nil && settings.writeMode == .alwaysAsk {
            guard approved else { throw ProjectsWorkspaceError.invalidContext }
            try await fresh(focus, chatID: job.chatID, projectID: project.id, fence: job.fence)
            _ = try await request(.post, path: route("/v1/projects/" + Self.escaped(project.id) + "/write-approvals", teamID: project.teamId),
                body: ["chat_id": job.chatID, "operation_id": operationID, "proposal_digest": digest], fence: job.fence)
        }
        metadata.merge(["path": path, "display_path": path, "source": "hosted_project_file",
                        "focus_title": document["name"] as? String ?? "", "focus_description": document["description"] as? String ?? "",
                        "focus_when_to_use": document["when_to_use"] as? String ?? "", "authoring_save_operation": operationID]) { _, new in new }
        if expectedHead == 0, item != nil, receipt == nil { throw ProjectsWorkspaceError.invalidContext }
        try await fresh(focus, chatID: job.chatID, projectID: project.id, fence: job.fence)
        _ = try await ProjectHostedFileExecutor(adapter: adapter).execute(job: descriptor, mutation: mutation,
            approvedIgnoredRead: nil, fence: job.fence, validateAuthority: {
                guard OfflineStore.shared.scopeGeneration == job.fence.scope, socket.transportGeneration == transport else { throw CancellationError() }
            })
        if let item, !metadataWasSaved {
            try await fresh(focus, chatID: job.chatID, projectID: project.id, fence: job.fence)
            try await updateMetadata(metadata, item: item, project: project, fence: job.fence)
        }
        guard let saved = (try await detail(project, fence: job.fence)).first(where: { $0["project_item_id"] as? String == id }) else { throw ProjectsWorkspaceError.invalidResponse }
        return ["save_operation_id": operationID, "project_item_id": id, "embed_id": embedID,
                "saved_revision": Self.itemRevision(saved), "expected_revision": job.value["expected_revision"] ?? NSNull()]
    }

    private func historicalText(embedID: String, revision: Int, key: SymmetricKey,
                                project: ProjectWorkspaceProject, fence: ProjectsWorkspaceFence) async throws -> String {
        let result = try await request(.get, path: route("/v1/embeds/" + Self.escaped(embedID) + "/versions/" + String(revision) +
            "?capability=bounded-v1&project_id=" + Self.escaped(project.id), teamID: project.teamId), fence: fence)
        guard let rows = result["rows"] as? [[String: Any]], !rows.isEmpty, rows.count <= 33 else { throw ProjectsWorkspaceError.invalidResponse }
        var content: String?; var current = (rows.first?["version_number"] as? Int ?? 0) - 1
        for row in rows {
            guard let number = row["version_number"] as? Int, number == current + 1 else { throw ProjectsWorkspaceError.invalidResponse }
            if let snapshot = row["encrypted_snapshot"] as? String {
                content = try await CryptoManager.shared.decryptContent(base64String: snapshot, key: key)
            } else if let patch = row["encrypted_patch"] as? String, let previous = content {
                let plaintext = try await CryptoManager.shared.decryptContent(base64String: patch, key: key)
                // Paths in version patches are not authority; use their common header for reconstruction only.
                guard let header = plaintext.components(separatedBy: "\n").first, header.hasPrefix("--- a/") else { throw ProjectsWorkspaceError.invalidResponse }
                content = try ProjectHostedPatch.apply(plaintext, to: previous, path: String(header.dropFirst(6)))
            } else { throw ProjectsWorkspaceError.invalidResponse }
            current = number
            try await fence.check()
        }
        guard current == revision, let content else { throw ProjectsWorkspaceError.invalidResponse }
        return content
    }

    static func replacementPatch(path: String, old: String, next: String) -> String {
        func lines(_ value: String, marker: String) -> (Int, [String]) {
            guard !value.isEmpty else { return (0, []) }
            var parts = value.components(separatedBy: "\n"); let newline = parts.last == ""
            if newline { parts.removeLast() }
            var rows = parts.map { marker + $0 }; if !newline { rows.append("\\ No newline at end of file") }
            return (parts.count, rows)
        }
        let previous = lines(old, marker: "-"), next = lines(next, marker: "+")
        return (["--- a/" + path, "+++ b/" + path, "@@ -\(previous.0 == 0 ? 0 : 1),\(previous.0) +\(next.0 == 0 ? 0 : 1),\(next.0) @@"] + previous.1 + next.1 + [""]).joined(separator: "\n")
    }
}

// ─── Web source ─────────────────────────────────────────────────────
// Svelte: frontend/packages/ui/src/components/AgentContextMessage.svelte
// CSS: .context-message, .actions — custom neutral receipt controls, generated tokens.
// ────────────────────────────────────────────────────────────────────
struct NativeProjectAuthoringJobView: View {
    let job: NativeProjectAuthoringJob
    @ObservedObject var client: NativeProjectAuthoringClient
    @State private var saving = false
    @State private var failed = false
    @State private var expanded = false

    var body: some View {
        VStack(alignment: .leading, spacing: .spacing3) {
            if job.status == "ready" {
                Text(L("notifications.project_authoring.ready"))
                Button(L("notifications.project_authoring.view")) {
                    let resultID = job.value["result_id"] as? String ?? ""
                    let destination = job.value["kind"] as? String == "workflow" ? "workflows/" + resultID : "projects/" + job.projectID
                    if let url = URL(string: "openmates://" + destination) {
                        NotificationCenter.default.post(name: .deepLinkReceived, object: nil, userInfo: ["url": url])
                    }
                }.buttonStyle(.plain).foregroundStyle(Color.buttonPrimary)
                    .accessibilityIdentifier("project-authoring-ready-link")
            } else if job.status == "needs_save", let markdown = job.draft?["markdown"] as? String {
                Button { expanded.toggle() } label: {
                    HStack { Text(L("rules.review_draft")); Image(systemName: expanded ? "chevron.up" : "chevron.down") }
                }.buttonStyle(.plain).accessibilityIdentifier("project-authoring-review-draft")
                    .accessibilityValue(L(expanded ? "rules.expanded" : "rules.collapsed"))
                if expanded {
                    Text(job.draft?["path"] as? String ?? "").font(.omSmall.monospaced())
                    ScrollView(.vertical) { Text(markdown).font(.omSmall).textSelection(.enabled).frame(maxWidth: .infinity, alignment: .leading) }
                        .frame(maxHeight: 320).accessibilityIdentifier("project-authoring-generated-file")
                }
                Button(AppStrings.projectApproveWrite) {
                    guard !saving else { return }; saving = true; failed = false
                    Task { @MainActor in
                        defer { saving = false }
                        do { try await client.save(job.recommendationID, approved: true) } catch { failed = true }
                    }
                }.buttonStyle(OMPrimaryButtonStyle()).disabled(saving).accessibilityIdentifier("project-authoring-save")
            } else if job.status == "needs_input", let question = job.draft?["question"] as? String {
                Text(question)
            } else if ["failed", "conflict", "partial"].contains(job.status) {
                Text(L("rules.authoring_failed")).foregroundStyle(Color.error)
            } else {
                Text(L("rules.job_" + (["running", "pending_file", "needs_binding_save"].contains(job.status) ? job.status : "running")))
                Button(L("common.refresh")) { Task { try? await client.refresh(job.recommendationID) } }
                    .buttonStyle(.plain).accessibilityIdentifier("project-authoring-refresh")
            }
            if failed { Text(L("rules.authoring_save_failed")).foregroundStyle(Color.error).accessibilityIdentifier("project-authoring-save-error") }
        }
        .font(.omSmall).accessibilityIdentifier("project-authoring-job")
    }
}
