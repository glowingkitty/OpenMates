// Specification: specifications/features/apple-offline-workspaces/specification.yml
// Assertions: apple-workspaces.offline-complete, apple-workspaces.local-first, apple-workspaces.isolation, apple-workspaces.maintenance
// Web source: frontend/packages/ui/src/services/projectService.ts
// Specification: specifications/features/projects/specification.yml
// Assertions: projects.access.explicit-context, projects.files.no-server-decryption-authority, projects.surface.semantic-parity
import CryptoKit
import Foundation

enum ProjectsWorkspaceError: LocalizedError {
    case accountChanged
    case missingMasterKey
    case missingProjectKey
    case invalidResponse
    case invalidContext
    case unsupportedSource
    case sourceOffline
    case sourceTimedOut

    var errorDescription: String? {
        switch self {
        case .accountChanged: return "The active account changed. Reload Projects."
        case .missingMasterKey: return "Project keys are unavailable on this device."
        case .missingProjectKey: return "This Project cannot be decrypted on this device."
        case .invalidResponse: return "The Project response could not be opened."
        case .invalidContext: return "Select an authorized Project context first."
        case .unsupportedSource: return "This connected source is unavailable on this device."
        case .sourceOffline: return "Remote machine is offline"
        case .sourceTimedOut: return "The remote machine did not respond. Retry the Project read."
        }
    }
}

extension AppStrings {
    static func projectError(_ error: Error) -> String {
        guard let workspace = error as? ProjectsWorkspaceError else {
            return localized("projects.workspace_error_generic")
        }
        switch workspace {
        case .accountChanged: return localized("projects.workspace_error_account")
        case .missingMasterKey: return localized("projects.workspace_error_master_key")
        case .missingProjectKey: return localized("projects.workspace_error_project_key")
        case .invalidResponse: return localized("projects.workspace_error_response")
        case .invalidContext: return localized("projects.workspace_error_context")
        case .unsupportedSource: return localized("projects.workspace_error_source")
        case .sourceOffline: return localized("projects.workspace_error_source_offline")
        case .sourceTimedOut: return localized("projects.workspace_error_source_timeout")
        }
    }
}

enum ProjectWorkspaceWriteMode: String, Codable, CaseIterable, Identifiable, Sendable {
    case applyAndShow = "apply_and_show"
    case alwaysAsk = "always_ask"

    var id: String { rawValue }
    @MainActor var title: String {
        switch self {
        case .applyAndShow: return AppStrings.projectApplyAndShow
        case .alwaysAsk: return AppStrings.projectAlwaysAsk
        }
    }
}

enum ProjectWorkspaceTab: String, CaseIterable, Identifiable {
    case overview
    case files
    case tasks
    var id: String { rawValue }
    @MainActor var title: String {
        switch self {
        case .overview: AppStrings.projectOverview
        case .files: AppStrings.projectFiles
        case .tasks: AppStrings.projectTasks
        }
    }
}

struct ProjectWorkspaceProject: Identifiable, Sendable {
    let id: String
    var name: String
    var description: String
    var icon: String
    let key: SymmetricKey
    var version: Int
    var createdAt: Int
    var updatedAt: Int
    var isShared: Bool
    var itemCount: Int
    var teamId: String?
    var permissions: ProjectWorkspacePermissions
}

struct ProjectWorkspacePermissions: Decodable, Sendable {
    let create: Bool
    let update: Bool
    let archive: Bool
    let delete: Bool
    let settings: Bool
    let manageAnyItems: Bool
    let manageAnySources: Bool
    let manageOwnItems: Bool
    let manageOwnSources: Bool

    static let denied = ProjectWorkspacePermissions(create: false, update: false,
        archive: false, delete: false, settings: false, manageAnyItems: false,
        manageAnySources: false, manageOwnItems: false, manageOwnSources: false)
}

struct ProjectWorkspaceFolder: Identifiable, Sendable {
    let id: String
    let name: String
    let parentHash: String?
    let position: Int
    let createdAt: Int
}

struct ProjectWorkspaceItem: Identifiable, Sendable {
    let id: String
    let kind: String
    let targetID: String
    let name: String
    let metadata: [String: String]
    let folderHash: String?
    let position: Int
    let createdAt: Int

    var filePath: String? {
        let candidate = metadata["path"] ?? metadata["remote_path"] ?? name
        return ProjectWorkspacePath.normalized(candidate)
    }
}

struct ProjectWorkspaceSource: Identifiable, Equatable, Sendable {
    let id: String
    let kind: String
    let name: String
    let metadata: [String: String]
    let capabilities: [String]
    let status: String
    let sessionID: String?
    let keyEpoch: Int?
}

struct ProjectWorkspaceContents: Sendable {
    let folders: [ProjectWorkspaceFolder]
    let items: [ProjectWorkspaceItem]
    let sources: [ProjectWorkspaceSource]
}

struct ProjectWorkspaceSettings: Sendable {
    let writeMode: ProjectWorkspaceWriteMode
    let selectionRequired: Bool
    let focusID: String?
    let focusInstruction: String?
}

struct ProjectWorkspaceReadme: Hashable {
    /// A reload must reset lazy media even when Markdown/source paths are unchanged.
    let renderID = UUID()
    let markdown: String
    let truncated: Bool
    let origin: String
    var sourceID: String? = nil
    var sourceSessionID: String? = nil
    var sourceKeyEpoch: Int? = nil
}

enum ProjectWorkspacePath {
    static func normalized(_ raw: String) -> String? {
        guard !raw.isEmpty, !raw.hasPrefix("/"), !raw.contains("\\"),
              raw.range(of: "^[A-Za-z]:", options: .regularExpression) == nil,
              !raw.unicodeScalars.contains(where: { $0.value < 32 || $0.value == 127 }) else { return nil }
        let components = raw.split(separator: "/", omittingEmptySubsequences: false)
        guard components.allSatisfy({ !$0.isEmpty && $0 != "." && $0 != ".." }) else { return nil }
        return components.joined(separator: "/")
    }
}

// These mirror the encrypted API records. Nothing in them is persisted as plaintext.
struct ProjectWorkspaceKeyWrapper: Decodable, Sendable {
    let keyType: String
    let hashedTeamId: String?
    let teamKeyEpoch: Int?
    let encryptedProjectKey: String
}

struct ProjectWorkspaceRecord: Decodable, Sendable {
    let projectId: String
    let encryptedProjectKey: String?
    let keyWrappers: [ProjectWorkspaceKeyWrapper]?
    let encryptedName: String
    let encryptedDescription: String?
    let encryptedIcon: String?
    let createdAt: Int
    let updatedAt: Int
    let itemCount: Int?
    let version: Int?
    let isShared: Bool?
    let mutationPermissions: ProjectWorkspacePermissions?
}

struct ProjectWorkspaceFolderRecord: Decodable, Sendable {
    let folderId: String
    let encryptedName: String
    let hashedParentFolderId: String?
    let createdAt: Int
    let position: Int
}

struct ProjectWorkspaceItemRecord: Decodable, Sendable {
    let projectItemId: String
    let itemType: String
    let targetIdEncrypted: String
    let encryptedDisplayName: String?
    let encryptedMetadata: String?
    let hashedFolderId: String?
    let createdAt: Int
    let position: Int
}

struct ProjectWorkspaceSourceRecord: Decodable, Sendable {
    let sourceId: String
    let sourceType: String
    let encryptedDisplayName: String
    let encryptedMetadata: String?
    let capabilities: [String]
    let status: String
    let sourceSessionId: String?
    let keyEpoch: Int?
}

struct ProjectWorkspaceSettingsRecord: Decodable, Sendable {
    let writeMode: ProjectWorkspaceWriteMode?
    let selectionRequired: Bool?
    let encryptedSettings: String?
}
