// Web source (78e8d99023): services/voiceCallContext.ts,
// agenticProjectContextService.ts: loadSelectedProjectFocusDocuments.
// Specification: specifications/features/video-call/specification.yml
// Assertions: video-call.chat.project-context, video-call.chat.fixed-binding
#if !os(watchOS)
import CryptoKit
import Foundation

/// One already authorized specialist, read through the existing private/ignored
/// path policy. This transient projection grants no activation or file authority.
/// Routing discovery and memory availability are separate capabilities; this
/// reader supplies neither fabricated metadata nor unrelated private documents.
@MainActor
final class NativeVoiceCallProjectContext {
    private let scope: NativeVoiceCallScope
    private let fence: ProjectsWorkspaceFence
    private let request: @MainActor (String) async throws -> Data
    private let checkCurrent: @MainActor () throws -> Void
    private let service = ProjectsWorkspaceService()

    init(scope: NativeVoiceCallScope,
         request: @escaping @MainActor (String) async throws -> Data,
         checkCurrent: @escaping @MainActor () throws -> Void) {
        self.scope = scope
        self.fence = ProjectsWorkspaceFence(accountID: scope.accountID)
        self.request = request
        self.checkCurrent = checkCurrent
    }

    private func check() async throws {
        try Task.checkCancellation()
        try checkCurrent()
        guard fence.scope == scope.workspaceGeneration,
              fence.serverProfile.id == scope.profileID, fence.teamContext.teamID == nil
        else { throw NativeVoiceCallError.scopeChanged }
        try await fence.check()
        try checkCurrent()
    }

    private func fetch(_ path: String) async throws -> NativeVoiceCallFrame {
        try await check()
        let bytes = try await request(path)
        try await check()
        guard bytes.count <= 2 * 1_024 * 1_024,
              let value = try? JSONDecoder().decode(NativeVoiceCallFrame.self, from: bytes)
        else { throw NativeVoiceCallError.contextUnavailable }
        return value
    }

    private func focus() async throws -> NativeVoiceCallFrame? {
        let response = try await fetch("/v1/projects/focus/current?chat_id=" + scope.chatID)
        if response["focus"] == .null { return nil }
        guard let value = response["focus"]?.object else { throw NativeVoiceCallError.contextUnavailable }
        if value["active"]?.bool == false { return nil }
        guard value["active"]?.bool == true, value["team_id"] == nil || value["team_id"] == .null,
              let projectID = value["project_id"]?.string, UUID(uuidString: projectID) != nil,
              let focusID = value["focus_id"]?.string, !focusID.isEmpty
        else { throw NativeVoiceCallError.contextUnavailable }
        return value
    }

    private func sameFocus(_ original: NativeVoiceCallFrame) async throws {
        guard let current = try await focus(),
              current["project_id"] == original["project_id"], current["focus_id"] == original["focus_id"],
              current["specialist_focus_id"] == original["specialist_focus_id"],
              current["team_id"] == original["team_id"]
        else { throw NativeVoiceCallError.contextUnavailable }
    }

    private func item(projectID: String, itemID: String) async throws -> NativeVoiceCallFrame {
        let response = try await fetch("/v1/projects/" + projectID)
        guard case .array(let items)? = response["items"], items.count <= 500,
              items.allSatisfy({ $0.object != nil }) else { throw NativeVoiceCallError.contextTooLarge }
        let matches = items.compactMap(\.object).filter { $0["project_item_id"]?.string == itemID }
        guard matches.count == 1, let item = matches.first, item["item_type"]?.string == "embed",
              item["deleted_target_state"] == nil || item["deleted_target_state"] == .null
        else { throw NativeVoiceCallError.contextUnavailable }
        return item
    }

    private func opened(_ ciphertext: String, key: SymmetricKey) async throws -> String {
        try await check()
        let value = try await CryptoManager.shared.decryptContent(base64String: ciphertext, key: key)
        try await check()
        return value
    }

    func load(activeFocus: NativeVoiceCallJSON?) async throws -> NativeVoiceCallFrame {
        try await check()
        let encryptedFocusID = activeFocus?.object?["focus_id"]?.string
        guard let current = try await focus() else {
            guard encryptedFocusID?.contains("project-focus:") != true else { throw NativeVoiceCallError.contextUnavailable }
            return [:]
        }
        let projectID = current["project_id"]!.string!
        guard let specialist = current["specialist_focus_id"]?.string else {
            guard current["specialist_focus_id"] == nil || current["specialist_focus_id"] == .null,
                  encryptedFocusID?.contains("project-focus:") != true else { throw NativeVoiceCallError.contextUnavailable }
            return [:]
        }
        let prefix = "project-focus:" + projectID + ":"
        guard specialist.hasPrefix(prefix), UUID(uuidString: scope.chatID) != nil else { throw NativeVoiceCallError.contextUnavailable }
        let itemID = String(specialist.dropFirst(prefix.count))
        guard UUID(uuidString: itemID) != nil,
              encryptedFocusID?.contains("project-focus:") != true || encryptedFocusID == specialist
        else { throw NativeVoiceCallError.contextUnavailable }
        try await check()
        let eligible = await AuthManager.isRecoveryEligibleDevice()
        try await check()
        guard eligible else { throw NativeVoiceCallError.contextUnavailable }
        let project = try await service.getProject(accountID: scope.accountID, projectID: projectID,
            teamID: nil, fence: fence)
        try await check()
        guard project.id == projectID, project.teamId == nil,
              let chatKey = ChatKeyManager.shared.key(for: scope.chatID)
        else { throw NativeVoiceCallError.contextUnavailable }
        let selected = try await item(projectID: projectID, itemID: itemID)
        guard let encryptedMetadata = selected["encrypted_metadata"]?.string,
              let encryptedTarget = selected["target_id_encrypted"]?.string
        else { throw NativeVoiceCallError.contextUnavailable }
        let metadataText = try await opened(encryptedMetadata, key: project.key)
        guard let metadataData = metadataText.data(using: .utf8), metadataData.count <= 64_000,
              let metadata = try? JSONDecoder().decode(NativeVoiceCallFrame.self, from: metadataData),
              let path = (metadata["path"] ?? metadata["display_path"])?.string,
              path.range(of: "^\\.openmates/focuses/[a-zA-Z0-9_-]+/SKILL\\.md$", options: .regularExpression) != nil,
              ProjectWorkspacePath.normalized(path) == path
        else { throw NativeVoiceCallError.contextUnavailable }
        let embedID = try await opened(encryptedTarget, key: project.key)
        guard UUID(uuidString: embedID) != nil else { throw NativeVoiceCallError.contextUnavailable }
        try await sameFocus(current)
        let base = ProjectHostedWorkspaceAdapter(project: project, chatKey: chatKey, fence: fence,
            commit: { _ in throw NativeVoiceCallError.contextUnavailable })
        let adapter = SelectedReader(base: base, path: path, embedID: embedID, checkCurrent: checkCurrent)
        let executor = ProjectHostedFileExecutor(adapter: adapter, validateFence: { [self] _ in try await check() })
        try await check()
        let result = try await executor.execute(
            job: ProjectFileJob(contextChatID: scope.chatID, projectID: projectID, path: path),
            mutation: nil, approvedIgnoredRead: nil, fence: fence, validateAuthority: checkCurrent)
        try await check()
        guard let text = result["content"] as? String, result["path"] as? String == path,
              result["truncated"] as? Bool == false, !text.isEmpty, text.utf16.count <= 60_000,
              let revision = result["revision"] as? Int, revision >= 1
        else { throw NativeVoiceCallError.contextUnavailable }
        _ = try NativeProjectAuthoringClient.parseFocusDocument(text)
        // The selected item revision protects path/target authority. Re-read its
        // encrypted head as well: an embed edit need not change the item record.
        let verified = try await executor.execute(
            job: ProjectFileJob(contextChatID: scope.chatID, projectID: projectID, path: path),
            mutation: nil, approvedIgnoredRead: nil, fence: fence, validateAuthority: checkCurrent)
        try await check()
        guard verified["revision"] as? Int == revision, verified["content"] as? String == text,
              verified["path"] as? String == path, verified["truncated"] as? Bool == false,
              try await item(projectID: projectID, itemID: itemID) == selected
        else { throw NativeVoiceCallError.contextUnavailable }
        try await sameFocus(current)
        try await check()
        let selectedData = try JSONEncoder().encode(selected)
        guard let raw = try JSONSerialization.jsonObject(with: selectedData) as? [String: Any]
        else { throw NativeVoiceCallError.contextUnavailable }
        return ["project_focus_documents": .array([.object([
            "item_id": .string(itemID),
            "revision": .string(NativeProjectAuthoringClient.itemRevision(raw)),
            "document": .string(text)
        ])])]
    }

    /// Add the original voice binding check around every hosted-reader await,
    /// including policy files. Mutating adapter methods never acknowledge success.
    @MainActor
    private final class SelectedReader: ProjectHostedFileAdapter {
        let base: ProjectHostedWorkspaceAdapter
        let path: String
        let embedID: String
        let checkCurrent: @MainActor () throws -> Void
        var projectID: String { base.projectID }
        var projectKey: SymmetricKey { base.projectKey }
        var chatKey: SymmetricKey { base.chatKey }
        var teamID: String? { base.teamID }
        init(base: ProjectHostedWorkspaceAdapter, path: String, embedID: String,
             checkCurrent: @escaping @MainActor () throws -> Void) {
            self.base = base; self.path = path; self.embedID = embedID; self.checkCurrent = checkCurrent
        }
        func listFiles() async throws -> [ProjectHostedFile] {
            try checkCurrent()
            let files = try await base.listFiles()
            try checkCurrent()
            let matches = files.filter { $0.path == path }
            guard files.count <= 500, matches.count == 1, matches.first?.embedID == embedID
            else { throw NativeVoiceCallError.contextUnavailable }
            return files
        }
        func readHead(embedID: String) async throws -> ProjectHostedHead {
            try checkCurrent()
            let head = try await base.readHead(embedID: embedID)
            try checkCurrent()
            return head
        }
        func privatePaths() async throws -> [String] {
            try checkCurrent()
            let paths = try await base.privatePaths()
            try checkCurrent()
            return paths
        }
        func receipt(embedID: String, job: ProjectFileJob, digest: String) async throws -> [String: Any]? {
            throw NativeVoiceCallError.contextUnavailable
        }
        func commit(_ payload: [String: Any]) async throws -> [String: Any] {
            throw NativeVoiceCallError.contextUnavailable
        }
    }
}
#endif
