import CryptoKit
import Foundation

/// First-party encrypted Project reads for a hosted file job. The coordinator
/// owns the chat lease and socket authority; this adapter pins every HTTP read
/// to the account, store scope, and server profile captured for that lease.
@MainActor
final class ProjectHostedWorkspaceAdapter: ProjectHostedFileAdapter {
    private struct SettingsResponse: Decodable { let settings: SettingsRecord }
    private struct SettingsRecord: Decodable { let encryptedSettings: String? }
    private struct EmbedResponse: Decodable {
        let embed: EmbedRecordPayload
        let embedKeys: [EmbedKeyPayload]
        let hasInitialHistory: Bool?
    }
    private struct EmbedRecordPayload: Decodable {
        let encryptedContent: String
        let versionNumber: Int?
    }
    private struct EmbedKeyPayload: Decodable {
        let keyType: String
        let encryptedEmbedKey: String
    }

    let projectID: String
    let projectKey: SymmetricKey
    let chatKey: SymmetricKey
    let teamID: String?
    private let project: ProjectWorkspaceProject
    private let service: ProjectsWorkspaceService
    private let fence: ProjectsWorkspaceFence
    private let commitOperation: @MainActor ([String: Any]) async throws -> [String: Any]

    init(project: ProjectWorkspaceProject, chatKey: SymmetricKey,
         fence: ProjectsWorkspaceFence,
         service: ProjectsWorkspaceService = ProjectsWorkspaceService(),
         commit: @escaping @MainActor ([String: Any]) async throws -> [String: Any]) {
        self.projectID = project.id
        self.projectKey = project.key
        self.chatKey = chatKey
        self.teamID = project.teamId
        self.project = project
        self.fence = fence
        self.service = service
        self.commitOperation = commit
    }

    func listFiles() async throws -> [ProjectHostedFile] {
        try await fence.check()
        let contents = try await service.contents(project: project, fence: fence)
        try await fence.check()
        return contents.items.compactMap { item in
            guard item.kind == "embed" || item.kind == "upload", !item.targetID.isEmpty else {
                return nil
            }
            let candidate = item.metadata["path"] ?? item.metadata["file_path"] ??
                item.metadata["filename"] ?? item.name
            // A malformed metadata link taints the ciphertext target when the
            // executor builds the path policy. Never silently drop it here.
            return ProjectHostedFile(embedID: item.targetID,
                path: candidate.isEmpty ? "/" : candidate)
        }
    }

    func readHead(embedID: String) async throws -> ProjectHostedHead {
        try await fence.check()
        let path = route("/v1/embeds/\(Self.escaped(embedID))/encrypted?project_id=\(Self.escaped(projectID))")
        let response: EmbedResponse = try await APIClient.shared.request(.get, path: path,
            serverProfile: fence.serverProfile,
            expectedAccountID: fence.accountID, expectedScope: fence.scope)
        try await fence.check()
        guard let wrapper = response.embedKeys.first(where: { $0.keyType == "project" }),
              let revision = response.embed.versionNumber, revision >= 1 else {
            throw ProjectHostedFileError(code: "file_key_unavailable")
        }
        let keyData = try await CryptoManager.shared.decryptBlob(
            base64String: wrapper.encryptedEmbedKey, key: projectKey)
        guard keyData.count == 32 else { throw ProjectHostedFileError(code: "file_key_unavailable") }
        let embedKey = SymmetricKey(data: keyData)
        let plaintext = try await CryptoManager.shared.decryptContent(
            base64String: response.embed.encryptedContent, key: embedKey)
        try await fence.check()
        let content = EmbedRecord.parseContent(plaintext)
        guard !content.isEmpty else { throw ProjectHostedFileError(code: "unsupported_file_content") }
        return ProjectHostedHead(embedKey: embedKey, content: content,
            revision: revision, hasInitialHistory: response.hasInitialHistory == true)
    }

    func privatePaths() async throws -> [String] {
        try await fence.check()
        let response: SettingsResponse = try await APIClient.shared.request(.get,
            path: route("/v1/projects/\(Self.escaped(projectID))/settings"),
            serverProfile: fence.serverProfile,
            expectedAccountID: fence.accountID, expectedScope: fence.scope)
        try await fence.check()
        guard let ciphertext = response.settings.encryptedSettings, !ciphertext.isEmpty else {
            return []
        }
        let plaintext = try await CryptoManager.shared.decryptContent(
            base64String: ciphertext, key: projectKey)
        try await fence.check()
        guard let data = plaintext.data(using: .utf8),
              let root = try JSONSerialization.jsonObject(with: data) as? [String: Any] else {
            throw ProjectHostedFileError(code: "protected_path")
        }
        guard let access = root["file_access"] else { return [] }
        guard let access = access as? [String: Any] else {
            throw ProjectHostedFileError(code: "protected_path")
        }
        guard let rawPaths = access["private_paths"] else { return [] }
        guard let paths = rawPaths as? [String], paths.count <= 256,
              paths.allSatisfy({ !$0.isEmpty && $0.utf8.count <= 4_096 }) else {
            throw ProjectHostedFileError(code: "protected_path")
        }
        return paths
    }

    func receipt(embedID: String, job: ProjectFileJob, digest: String) async throws -> [String: Any]? {
        try await fence.check()
        let path = route("/v1/embeds/\(Self.escaped(embedID))/revision-receipts/\(Self.escaped(job.operationID))" +
            "?project_id=\(Self.escaped(projectID))&chat_id=\(Self.escaped(job.chatID))" +
            "&proposal_digest=\(Self.escaped(digest))")
        let data: Data
        do {
            data = try await APIClient.shared.request(.get, path: path,
                serverProfile: fence.serverProfile,
                expectedAccountID: fence.accountID, expectedScope: fence.scope)
        } catch APIError.httpError(let status, _) where status == 404 {
            try await fence.check()
            return nil
        }
        try await fence.check()
        guard let receipt = try JSONSerialization.jsonObject(with: data) as? [String: Any] else {
            throw ProjectHostedFileError(code: "invalid_receipt")
        }
        return receipt
    }

    func commit(_ payload: [String: Any]) async throws -> [String: Any] {
        try await fence.check()
        let result = try await commitOperation(payload)
        try await fence.check()
        return result
    }

    private func route(_ path: String) -> String {
        guard let teamID else { return path }
        return path + (path.contains("?") ? "&" : "?") + "team_id=\(Self.escaped(teamID))"
    }

    private static func escaped(_ value: String) -> String {
        value.addingPercentEncoding(withAllowedCharacters: CharacterSet(charactersIn:
            "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-._~")) ?? ""
    }
}
