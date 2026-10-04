// Specification: specifications/features/chat-navigation/specification.yml
// Assertions: chat-navigation.projects.nested-readable, chat-navigation.activity.global-running, chat-navigation.projects.organize
// Specification: specifications/features/apple-offline-workspaces/specification.yml
// Assertions: apple-workspaces.offline-complete, apple-workspaces.local-first, apple-workspaces.isolation, apple-workspaces.maintenance
// Web source: frontend/packages/ui/src/services/projectService.ts
// Specification: specifications/features/projects/specification.yml
// Assertions: projects.access.explicit-context, projects.files.no-server-decryption-authority
import CryptoKit
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
        let response = try await response(SettingsResponse.self, path: projectRoute(project, suffix: "/settings"),
            fence: fence, teamID: project.teamId, cachedOnly: cachedOnly)
        try await fence.check()
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
