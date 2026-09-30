// Client-side encrypted Tasks service. Durable text remains ciphertext on /v1/user-tasks.
// Matches the wire contract in frontend/packages/ui/src/services/userTaskService.ts.

import CryptoKit
import Foundation

enum UserTasksError: LocalizedError {
    case accountChanged
    case masterKeyUnavailable
    case taskKeyUnavailable
    case missingVersion
    case invalidResponse
    case missingLinkedKey(String)
    case invalidActivity
    case unsupportedTeamMutation

    var errorDescription: String? {
        switch self {
        case .accountChanged: "The active account changed. Reload Tasks."
        case .masterKeyUnavailable: "Task keys are unavailable on this device."
        case .taskKeyUnavailable: "This Task cannot be decrypted on this device."
        case .missingVersion: "The Task version is missing. Reload Tasks."
        case .invalidResponse: "The Task response could not be opened."
        case .missingLinkedKey(let name): "The linked \(name) key is unavailable."
        case .invalidActivity: "This Task Activity entry could not be decrypted."
        case .unsupportedTeamMutation: "This action is not available for Team Tasks."
        }
    }
}

@MainActor
struct UserTasksAccountFence {
    let accountID: String
    let scope: UUID
    let serverProfile: ServerProfile

    init(accountID: String) {
        self.accountID = accountID
        self.scope = OfflineStore.shared.scopeGeneration
        self.serverProfile = ServerProfile.current()
    }

    func check() async throws {
        guard scope == OfflineStore.shared.scopeGeneration,
              serverProfile == ServerProfile.current(),
              accountID == (await AuthManager.currentUserId()) else {
            throw UserTasksError.accountChanged
        }
    }
}

struct UserTaskListFilters: Sendable {
    var status: UserTaskStatus?
    var chatID: String?
    var projectID: String?
    var teamID: String?

    init(status: UserTaskStatus? = nil, chatID: String? = nil,
         projectID: String? = nil, teamID: String? = nil) {
        self.status = status
        self.chatID = chatID
        self.projectID = projectID
        self.teamID = teamID
    }
}

struct UserTaskCreateInput: Sendable {
    let title: String
    var description = ""
    var tags: [String] = []
    var status: UserTaskStatus?
    var assigneeType: UserTaskAssigneeType = .user
    var assigneeIdentity: UserTaskAssigneeIdentity?
    var primaryChatID: String?
    var linkedProjectIDs: [String] = []
    var teamID: String?
    var dueAt: Int?
    var priority = 0
}

struct UserTaskUpdateInput: Sendable {
    var title: String?
    var description: String?
    var tags: [String]?
    var status: UserTaskStatus?
    var assigneeType: UserTaskAssigneeType?
    var assigneeIdentity: UserTaskAssigneeIdentity?
    var linkedProjectIDs: [String]?
    var dueAt: Int?
    var clearDueAt = false
    var priority: Int?
}

enum UserTasksPaths {
    static let base = "/v1/user-tasks"

    static func escaped(_ value: String) -> String {
        value.addingPercentEncoding(withAllowedCharacters: CharacterSet(charactersIn:
            "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-._~")) ?? ""
    }

    static func task(_ id: String) -> String { "\(base)/\(escaped(id))" }

    static func scoped(_ path: String, teamID: String?) -> String {
        guard let teamID else { return path }
        return "\(path)\(path.contains("?") ? "&" : "?")team_id=\(escaped(teamID))"
    }

    static func list(_ filters: UserTaskListFilters) -> String {
        var query: [String] = []
        if let status = filters.status { query.append("status=\(escaped(status.rawValue))") }
        if let chatID = filters.chatID { query.append("chat_id=\(escaped(chatID))") }
        if let projectID = filters.projectID { query.append("project_id=\(escaped(projectID))") }
        if let teamID = filters.teamID { query.append("team_id=\(escaped(teamID))") }
        return query.isEmpty ? base : "\(base)?\(query.joined(separator: "&"))"
    }

    static func activity(_ id: String, teamID: String? = nil, cursor: String? = nil) -> String {
        var path = "\(task(id))/activity?limit=200"
        if let teamID { path += "&team_id=\(escaped(teamID))" }
        if let cursor { path += "&cursor=\(escaped(cursor))" }
        return path
    }
}

@MainActor
final class UserTasksService {
    private struct ListResponse: Decodable { let tasks: [TaskBoardRecord] }
    private struct TaskResponse: Decodable { let task: EncryptedUserTaskRecord }
    private struct DependencyResponse: Decodable { let dependencies: [UserTaskDependency] }
    private struct ActivityResponse: Decodable {
        let entries: [UserTaskActivityRecord]
        let nextCursor: String?
    }
    private struct ActivityEntryResponse: Decodable { let entry: UserTaskActivityRecord }
    private struct ProposalResponse: Decodable { let proposedTasks: [UserTaskProposal] }

    private let api: APIClient
    private let projects: ProjectsWorkspaceServing

    init(api: APIClient = .shared, projects: ProjectsWorkspaceServing = ProjectsWorkspaceService()) {
        self.api = api
        self.projects = projects
    }

    func listBoard(filters: UserTaskListFilters = .init(), fence: UserTasksAccountFence) async throws -> [TaskBoardItem] {
        try await fence.check()
        let response: ListResponse = try await api.request(.get, path: UserTasksPaths.list(filters),
            serverProfile: fence.serverProfile,
            expectedAccountID: fence.accountID, expectedScope: fence.scope)
        try await fence.check()
        let masterKey = try await requireMasterKey(fence)
        var items: [TaskBoardItem] = []
        for record in response.tasks {
            try await fence.check()
            switch record.value {
            case .task(let encrypted):
                if let item = try await open(encrypted, masterKey: masterKey) { items.append(.task(item)) }
            case .workflowRun(let run):
                items.append(.workflowRun(run))
            }
        }
        try await fence.check()
        return items
    }

    func create(_ input: UserTaskCreateInput, fence: UserTasksAccountFence) async throws -> UserTaskItem {
        try await fence.check()
        let title = input.title.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !title.isEmpty else { throw UserTasksError.invalidResponse }
        let masterKey = try await requireMasterKey(fence)
        let taskKey = SymmetricKey(size: .bits256)
        let encryptedTaskKey = try await CryptoManager.shared.wrapChatKey(taskKey, masterKey: masterKey)
        let timestamp = Int(Date().timeIntervalSince1970)
        let wrappers = try await keyWrappers(taskKey: taskKey, encryptedTaskKey: encryptedTaskKey,
                                             timestamp: timestamp, chatID: input.primaryChatID,
                                             projectIDs: input.linkedProjectIDs, teamID: input.teamID,
                                             fence: fence)
        let json: [String: Any] = [
            "task_id": UUID().uuidString.lowercased(),
            "encrypted_task_key": encryptedTaskKey,
            "encrypted_title": try ComposerEmbedCrypto.encryptContent(title, using: taskKey),
            "encrypted_description": try ComposerEmbedCrypto.encryptContent(input.description, using: taskKey),
            "encrypted_tags": try ComposerEmbedCrypto.encryptContent(jsonArray(input.tags), using: taskKey),
            "encrypted_linked_project_ids": try ComposerEmbedCrypto.encryptContent(jsonArray(input.linkedProjectIDs), using: taskKey),
            "status": (input.status ?? (input.assigneeType == .openmates && input.dueAt == nil ? .inProgress : .todo)).rawValue,
            "assignee_type": input.assigneeType.rawValue,
            "assignee_identity": (input.assigneeIdentity ?? (input.assigneeType == .openmates ? .openmates : nil))?.rawValue as Any? ?? NSNull(),
            "primary_chat_id": input.primaryChatID as Any? ?? NSNull(),
            "linked_project_ids": input.linkedProjectIDs,
            "due_at": input.dueAt as Any? ?? NSNull(),
            "priority": input.priority,
            "position": timestamp,
            "version": 1,
            "created_at": timestamp,
            "updated_at": timestamp,
            "key_wrappers": wrappers,
        ]
        try await fence.check()
        let response: TaskResponse = try await requestJSON(.post, path: UserTasksPaths.base, body: json, fence: fence)
        try await fence.check()
        guard let opened = try await open(response.task, masterKey: masterKey) else {
            throw UserTasksError.taskKeyUnavailable
        }
        return opened
    }

    func update(_ task: UserTaskItem, patch: UserTaskUpdateInput,
                teamID: String? = nil, fence: UserTasksAccountFence) async throws -> UserTaskItem {
        try await fence.check()
        let masterKey = try await requireMasterKey(fence)
        let taskKey = try await requireTaskKey(task.record, masterKey: masterKey)
        let timestamp = Int(Date().timeIntervalSince1970)
        var json: [String: Any] = ["version": try version(task.record), "updated_at": timestamp]
        if let title = patch.title { json["encrypted_title"] = try ComposerEmbedCrypto.encryptContent(title, using: taskKey) }
        if let description = patch.description { json["encrypted_description"] = try ComposerEmbedCrypto.encryptContent(description, using: taskKey) }
        if let tags = patch.tags { json["encrypted_tags"] = try ComposerEmbedCrypto.encryptContent(jsonArray(tags), using: taskKey) }
        if let status = patch.status { json["status"] = status.rawValue }
        if let assignee = patch.assigneeType {
            json["assignee_type"] = assignee.rawValue
            json["assignee_identity"] = (patch.assigneeIdentity ?? (assignee == .openmates ? .openmates : nil))?.rawValue as Any? ?? NSNull()
        }
        if let projectIDs = patch.linkedProjectIDs {
            json["encrypted_linked_project_ids"] = try ComposerEmbedCrypto.encryptContent(jsonArray(projectIDs), using: taskKey)
            json["linked_project_ids"] = projectIDs
            guard let wrapped = task.record.encryptedTaskKey, !wrapped.isEmpty else {
                throw UserTasksError.taskKeyUnavailable
            }
            json["key_wrappers"] = try await keyWrappers(taskKey: taskKey,
                encryptedTaskKey: wrapped, timestamp: timestamp,
                chatID: task.primaryChatId, projectIDs: projectIDs, teamID: teamID, fence: fence)
        }
        if patch.clearDueAt { json["due_at"] = NSNull() }
        else if let dueAt = patch.dueAt { json["due_at"] = dueAt }
        if let priority = patch.priority { json["priority"] = priority }
        let response: TaskResponse = try await requestJSON(.patch,
            path: UserTasksPaths.scoped(UserTasksPaths.task(task.id), teamID: teamID), body: json, fence: fence)
        try await fence.check()
        guard let opened = try await open(response.task, masterKey: masterKey) else {
            throw UserTasksError.taskKeyUnavailable
        }
        return opened
    }

    func action(_ name: String, task: UserTaskItem, teamID: String? = nil,
                fence: UserTasksAccountFence,
                blockedReason: String? = nil,
                blockedReasonCode: UserTaskBlockedReason = .needsUserInput) async throws -> UserTaskItem {
        guard ["complete", "block", "unblock", "skip"].contains(name) else { throw UserTasksError.invalidResponse }
        try await fence.check()
        let masterKey = try await requireMasterKey(fence)
        var body: [String: Any] = ["version": try version(task.record)]
        if let teamID { body["team_id"] = teamID }
        if name == "block" {
            body["blocked_reason_code"] = blockedReasonCode.rawValue
            if let blockedReason, !blockedReason.isEmpty {
                let taskKey = try await requireTaskKey(task.record, masterKey: masterKey)
                body["encrypted_blocked_reason"] = try ComposerEmbedCrypto.encryptContent(blockedReason, using: taskKey)
            }
        }
        let response: TaskResponse = try await requestJSON(.post, path: "\(UserTasksPaths.task(task.id))/\(name)",
            body: body, fence: fence)
        try await fence.check()
        guard let opened = try await open(response.task, masterKey: masterKey) else {
            throw UserTasksError.taskKeyUnavailable
        }
        return opened
    }

    func move(_ task: UserTaskItem, to status: UserTaskStatus,
              position: Int? = nil, teamID: String? = nil,
              fence: UserTasksAccountFence) async throws -> UserTaskItem {
        try await fence.check()
        let masterKey = try await requireMasterKey(fence)
        var move: [String: Any] = ["task_id": task.id, "status": status.rawValue,
                                  "version": try version(task.record)]
        if let position { move["position"] = position }
        struct Response: Decodable { let tasks: [EncryptedUserTaskRecord] }
        let response: Response = try await requestJSON(.post, path: "\(UserTasksPaths.base)/reorder",
            body: ["moves": [move], "team_id": teamID as Any? ?? NSNull()], fence: fence)
        try await fence.check()
        guard let record = response.tasks.first,
              let opened = try await open(record, masterKey: masterKey) else {
            throw UserTasksError.invalidResponse
        }
        return opened
    }

    func delete(_ task: UserTaskItem, teamID: String? = nil,
                fence: UserTasksAccountFence) async throws {
        try await fence.check()
        let path = UserTasksPaths.scoped("\(UserTasksPaths.task(task.id))?version=\(try version(task.record))",
                                         teamID: teamID)
        let _: Data = try await api.request(.delete, path: path, serverProfile: fence.serverProfile,
            expectedAccountID: fence.accountID, expectedScope: fence.scope)
        try await fence.check()
    }

    func dependencies(for task: UserTaskItem, fence: UserTasksAccountFence) async throws -> [UserTaskDependency] {
        try await fence.check()
        let response: DependencyResponse = try await api.request(.get,
            path: "\(UserTasksPaths.task(task.id))/dependencies", serverProfile: fence.serverProfile,
            expectedAccountID: fence.accountID, expectedScope: fence.scope)
        try await fence.check()
        return response.dependencies
    }

    func activity(for task: UserTaskItem, teamID: String? = nil,
                  fence: UserTasksAccountFence) async throws -> [UserTaskActivityEntry] {
        try await fence.check()
        let masterKey = try await requireMasterKey(fence)
        let taskKey = try await requireTaskKey(task.record, masterKey: masterKey)
        var entries: [UserTaskActivityEntry] = []
        var cursor: String?
        repeat {
            let response: ActivityResponse = try await api.request(.get,
                path: UserTasksPaths.activity(task.id, teamID: teamID, cursor: cursor),
                serverProfile: fence.serverProfile,
                expectedAccountID: fence.accountID, expectedScope: fence.scope)
            try await fence.check()
            entries += try response.entries.map { try openActivity($0, taskKey: taskKey) }
            cursor = response.nextCursor
        } while cursor != nil
        return entries.sorted { $0.record.createdAt < $1.record.createdAt }
    }

    func addComment(_ message: String, task: UserTaskItem, teamID: String? = nil,
                    fence: UserTasksAccountFence) async throws -> UserTaskActivityEntry {
        try await fence.check()
        let clean = message.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !clean.isEmpty else { throw UserTasksError.invalidActivity }
        let masterKey = try await requireMasterKey(fence)
        let taskKey = try await requireTaskKey(task.record, masterKey: masterKey)
        let entryID = UUID().uuidString.lowercased()
        let ciphertext = try Self.sealActivity(clean, key: taskKey,
            associatedData: "task_activity_comment:\(task.id):\(entryID):v1")
        let body: [String: Any] = ["entry_id": entryID, "encrypted_message": ciphertext,
                                   "embed_refs": [], "created_at": Int(Date().timeIntervalSince1970)]
        let response: ActivityEntryResponse = try await requestJSON(.post,
            path: UserTasksPaths.activity(task.id, teamID: teamID), body: body, fence: fence)
        try await fence.check()
        return try openActivity(response.entry, taskKey: taskKey)
    }

    func extractProposals(correctedText: String, chatID: String? = nil,
                          projectIDs: [String] = [], fence: UserTasksAccountFence) async throws -> [UserTaskProposal] {
        try await fence.check()
        let response: ProposalResponse = try await requestJSON(.post,
            path: "\(UserTasksPaths.base)/extract", body: [
                "corrected_text": correctedText, "mode": "create",
                "context_chat_id": chatID as Any? ?? NSNull(), "project_ids": projectIDs,
            ], fence: fence)
        try await fence.check()
        return response.proposedTasks
    }

    private func open(_ record: EncryptedUserTaskRecord,
                      masterKey: SymmetricKey) async throws -> UserTaskItem? {
        guard let encryptedTaskKey = record.encryptedTaskKey, !encryptedTaskKey.isEmpty else { return nil }
        let taskKey = try await CryptoManager.shared.unwrapChatKey(
            encryptedChatKeyBase64: encryptedTaskKey, masterKey: masterKey)
        guard record.version != nil else { throw UserTasksError.missingVersion }
        let title = try decryptOptional(record.encryptedTitle, key: taskKey)
        let description = try decryptOptional(record.encryptedDescription, key: taskKey)
        let tags = try stringArray(record.encryptedTags, key: taskKey)
        let linkedProjects = try stringArray(record.encryptedLinkedProjectIds, key: taskKey)
        let externalChat: UserTaskExternalChat?
        if let provider = record.externalChatProvider,
           let externalID = record.encryptedExternalChatId {
            externalChat = UserTaskExternalChat(provider: provider,
                id: try decryptOptional(externalID, key: taskKey),
                title: try decryptOptional(record.encryptedExternalChatTitle, key: taskKey))
        } else { externalChat = nil }
        return UserTaskItem(record: record, title: title, description: description,
            latestInstruction: try decryptOptional(record.encryptedLatestInstruction, key: taskKey),
            tags: tags, linkedProjectIds: linkedProjects,
            blockedReason: try decryptOptional(record.encryptedBlockedReason, key: taskKey),
            externalChat: externalChat)
    }

    private func openActivity(_ record: UserTaskActivityRecord,
                              taskKey: SymmetricKey) throws -> UserTaskActivityEntry {
        guard record.kind == "comment", record.deletedAt == nil else {
            return UserTaskActivityEntry(record: record, message: nil, embedKeyMaterial: nil)
        }
        guard let encryptedMessage = record.encryptedMessage else { throw UserTasksError.invalidActivity }
        let message = try Self.openActivityCipher(encryptedMessage, key: taskKey,
            associatedData: "task_activity_comment:\(record.taskId):\(record.entryId):v1")
        let embedKeys: String?
        if let encryptedKeys = record.encryptedEmbedKeyMaterial {
            embedKeys = try Self.openActivityCipher(encryptedKeys, key: taskKey,
                associatedData: "task_activity_embed_keys:\(record.taskId):\(record.entryId):v1")
        } else { embedKeys = nil }
        return UserTaskActivityEntry(record: record, message: message, embedKeyMaterial: embedKeys)
    }

    static func sealActivity(_ plaintext: String, key: SymmetricKey,
                             associatedData: String) throws -> String {
        let sealed = try AES.GCM.seal(Data(plaintext.utf8), using: key,
                                      authenticating: Data(associatedData.utf8))
        guard let combined = sealed.combined else { throw UserTasksError.invalidActivity }
        return combined.base64EncodedString()
    }

    static func openActivityCipher(_ ciphertext: String, key: SymmetricKey,
                                   associatedData: String) throws -> String {
        guard let data = Data(base64Encoded: ciphertext) else { throw UserTasksError.invalidActivity }
        let box = try AES.GCM.SealedBox(combined: data)
        let opened = try AES.GCM.open(box, using: key, authenticating: Data(associatedData.utf8))
        guard let string = String(data: opened, encoding: .utf8) else { throw UserTasksError.invalidActivity }
        return string
    }

    private func requireMasterKey(_ fence: UserTasksAccountFence) async throws -> SymmetricKey {
        try await fence.check()
        guard let key = try await CryptoManager.shared.loadMasterKey(for: fence.accountID) else {
            throw UserTasksError.masterKeyUnavailable
        }
        try await fence.check()
        return key
    }

    private func requireTaskKey(_ record: EncryptedUserTaskRecord,
                                masterKey: SymmetricKey) async throws -> SymmetricKey {
        guard let encrypted = record.encryptedTaskKey, !encrypted.isEmpty else {
            throw UserTasksError.taskKeyUnavailable
        }
        return try await CryptoManager.shared.unwrapChatKey(
            encryptedChatKeyBase64: encrypted, masterKey: masterKey)
    }

    private func keyWrappers(taskKey: SymmetricKey, encryptedTaskKey: String,
                             timestamp: Int, chatID: String?, projectIDs: [String],
                             teamID: String?, fence: UserTasksAccountFence) async throws -> [[String: Any]] {
        var wrappers: [[String: Any]] = [["key_type": "master", "encrypted_task_key": encryptedTaskKey,
                                          "created_at": timestamp]]
        if let chatID {
            guard let chatKey = ChatKeyManager.shared.key(for: chatID) else {
                throw UserTasksError.missingLinkedKey("chat")
            }
            wrappers.append(["key_type": "chat", "encrypted_task_key": try ComposerEmbedCrypto.wrapKey(taskKey, using: chatKey),
                             "hashed_chat_id": Self.sha256Hex(chatID), "created_at": timestamp])
        }
        if !projectIDs.isEmpty {
            let available = try await projects.listProjects(accountID: fence.accountID, teamID: teamID)
            try await fence.check()
            for projectID in projectIDs {
                guard let project = available.first(where: { $0.id == projectID }) else {
                    throw UserTasksError.missingLinkedKey("Project")
                }
                wrappers.append(["key_type": "project",
                                 "encrypted_task_key": try ComposerEmbedCrypto.wrapKey(taskKey, using: project.key),
                                 "hashed_project_id": Self.sha256Hex(projectID), "created_at": timestamp])
            }
        }
        return wrappers
    }

    private static func sha256Hex(_ value: String) -> String {
        SHA256.hash(data: Data(value.utf8)).map { String(format: "%02x", $0) }.joined()
    }

    private func decryptOptional(_ value: String?, key: SymmetricKey) throws -> String {
        guard let value, !value.isEmpty else { return "" }
        return try ComposerEmbedCrypto.decryptContent(value, using: key)
    }

    private func stringArray(_ value: String?, key: SymmetricKey) throws -> [String] {
        let text = try decryptOptional(value, key: key)
        guard let data = text.data(using: .utf8), !text.isEmpty else { return [] }
        let array = try JSONSerialization.jsonObject(with: data) as? [String]
        return array ?? []
    }

    private func jsonArray(_ values: [String]) throws -> String {
        let data = try JSONSerialization.data(withJSONObject: values)
        guard let text = String(data: data, encoding: .utf8) else { throw UserTasksError.invalidResponse }
        return text
    }

    private func version(_ record: EncryptedUserTaskRecord) throws -> Int {
        guard let version = record.version else { throw UserTasksError.missingVersion }
        return version
    }

    private func requestJSON<T: Decodable>(_ method: HTTPMethod, path: String,
                                            body: [String: Any], fence: UserTasksAccountFence) async throws -> T {
        try await fence.check()
        let data: Data = try await api.request(method, path: path,
            serverProfile: fence.serverProfile,
            body: JSONRawBody(data: try JSONSerialization.data(withJSONObject: body)),
            expectedAccountID: fence.accountID, expectedScope: fence.scope)
        try await fence.check()
        let decoder = JSONDecoder()
        decoder.keyDecodingStrategy = .convertFromSnakeCase
        do {
            return try decoder.decode(T.self, from: data)
        } catch {
            APIResponseDecodingDiagnostics.record(error: error, responseType: T.self)
            throw error
        }
    }
}
