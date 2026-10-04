// Specification: specifications/features/apple-offline-workspaces/specification.yml
// Assertions: apple-workspaces.offline-complete, apple-workspaces.local-first, apple-workspaces.isolation, apple-workspaces.maintenance
// Client-side encrypted Tasks service. Durable text remains ciphertext on /v1/user-tasks.
// Matches the wire contract in frontend/packages/ui/src/services/userTaskService.ts.
// Specification: specifications/features/tasks/specification.yml
// Assertions: tasks.content.client-encrypted, tasks.assignment.identity-separated
// Specification: specifications/features/apple-task-board-interactions/specification.yml
// Assertions: apple-task-board.drag-move, apple-task-board.edit
// Specification: specifications/features/apple-tasks-widget/specification.yml
// Assertions: apple-tasks-widget.private-cache

import CryptoKit
import Foundation

enum UserTasksError: LocalizedError {
    case accountChanged
    case masterKeyUnavailable
    case taskKeyUnavailable
    case missingVersion
    case invalidResponse
    case incompleteInventory
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
        case .incompleteInventory: "The complete Task list is unavailable from this server."
        case .missingLinkedKey(let name): "The linked \(name) key is unavailable."
        case .invalidActivity: "This Task Activity entry could not be decrypted."
        case .unsupportedTeamMutation: "This action is not available for Team Tasks."
        }
    }
}

/// The deployed legacy list is capped at 500 rows. Only a below-cap response
/// without any paging fields can stand in for a complete inventory. Once a
/// server advertises paging, every page must satisfy the strict receipt rules.
@MainActor
enum UserTasksInventory {
    static func fetch(teamID: String?, request: (String) async throws -> Data) async throws -> Data {
        var pages = NativeWorkspaceInventoryPages()
        repeat {
            try Task.checkCancellation()
            var path = UserTasksPaths.base + "?paginate=true&limit=500"
            if let cursor = pages.nextCursor { path += "&cursor=" + UserTasksPaths.escaped(cursor) }
            let data = try await request(UserTasksPaths.scoped(path, teamID: teamID))
            try Task.checkCancellation()
            guard let envelope = try JSONSerialization.jsonObject(with: data) as? [String: Any] else {
                throw UserTasksError.invalidResponse
            }
            if pages.nextCursor == nil && !envelope.keys.contains("complete")
                && !envelope.keys.contains("next_cursor") {
                guard let rows = envelope["tasks"] as? [[String: Any]] else { throw UserTasksError.invalidResponse }
                guard rows.count < 500 else { throw UserTasksError.incompleteInventory }
                var legacy = envelope
                legacy["complete"] = true
                try pages.append(JSONSerialization.data(withJSONObject: legacy), collection: "tasks", idKey: "task_id")
            } else {
                try pages.append(data, collection: "tasks", idKey: "task_id")
            }
        } while !pages.isComplete
        return try pages.snapshot(collection: "tasks")
    }
}

@MainActor
struct UserTasksAccountFence {
    let accountID: String
    let scope: UUID
    let serverProfile: ServerProfile
    let widgetTeamEpoch: UInt64
    let teamID: String?
    private let teamContext: TeamWorkspaceContext

    var requestTeamContext: APIRequestTeamContext {
        .init(epoch: widgetTeamEpoch, teamID: teamID)
    }

    init(accountID: String, teamContext: TeamWorkspaceContext = .shared) {
        self.teamContext = teamContext
        self.teamID = teamContext.teamID
        self.accountID = accountID
        self.scope = OfflineStore.shared.scopeGeneration
        self.serverProfile = ServerProfile.current()
        self.widgetTeamEpoch = teamContext.contextEpoch
    }

    func checkTeamContext() throws {
        guard widgetTeamEpoch == teamContext.contextEpoch, teamID == teamContext.teamID else {
            throw UserTasksError.accountChanged
        }
    }

    func check() async throws {
        try checkTeamContext()
        guard scope == OfflineStore.shared.scopeGeneration,
              serverProfile == ServerProfile.current(),
              accountID == (await AuthManager.currentUserId()),
              scope == OfflineStore.shared.scopeGeneration,
              serverProfile == ServerProfile.current() else {
            throw UserTasksError.accountChanged
        }
        try checkTeamContext()
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
    private struct ListResponse: Decodable, Sendable { let tasks: [TaskBoardRecord] }
    private struct TaskResponse: Decodable, Sendable { let task: EncryptedUserTaskRecord }
    private struct DependencyResponse: Decodable, Sendable { let dependencies: [UserTaskDependency] }
    private struct ActivityResponse: Decodable, Sendable {
        let entries: [UserTaskActivityRecord]
        let nextCursor: String?
    }
    private struct ActivityEntryResponse: Decodable, Sendable { let entry: UserTaskActivityRecord }
    private struct ProposalResponse: Decodable, Sendable { let proposedTasks: [UserTaskProposal] }

    private let api: APIClient
    private let projects: ProjectsWorkspaceServing

    init(api: APIClient = .shared, projects: ProjectsWorkspaceServing = ProjectsWorkspaceService()) {
        self.api = api
        self.projects = projects
    }

    private func openBoard(_ data: Data, filters: UserTaskListFilters,
                           fence: UserTasksAccountFence, widgetOnlyIfMissing: Bool = false) async throws -> [TaskBoardItem] {
        let response = try await NativeWorkspaceOfflineRuntime.decodeResponse(ListResponse.self, data: data)
        let masterKey = try await requireMasterKey(fence)
        var items: [TaskBoardItem] = []
        var widgetTasks: [UserTaskItem] = []
        for record in response.tasks {
            try await fence.check()
            switch record.value {
            case .task(let encrypted):
                if let item = try await open(encrypted, masterKey: masterKey) {
                    widgetTasks.append(item)
                    if (filters.status == nil || item.status == filters.status),
                       (filters.chatID == nil || item.primaryChatId == filters.chatID),
                       (filters.projectID == nil || item.linkedProjectIds.contains(filters.projectID!)) {
                        items.append(.task(item))
                    }
                }
            case .workflowRun(let run):
                if filters.projectID == nil, filters.chatID == nil,
                   filters.status == nil || run.status == filters.status { items.append(.workflowRun(run)) }
            }
        }
        try await fence.check()
        TasksWidgetBridge.publish(widgetTasks, fence: fence, teamID: filters.teamID, onlyIfMissing: widgetOnlyIfMissing)
        return items
    }

    func cachedBoard(filters: UserTaskListFilters = .init(), fence: UserTasksAccountFence) async throws -> [TaskBoardItem]? {
        let scope = try await NativeWorkspaceOfflineRuntime.configure(accountID: fence.accountID, teamID: filters.teamID)
        let path = NativeWorkspaceOfflineRuntime.inventoryPath(UserTasksPaths.base, teamID: filters.teamID)
        guard let data = try await NativeWorkspaceOfflineRuntime.cached(namespace: "user-tasks", path: path, scope: scope) else { return nil }
        return try await openBoard(data, filters: filters, fence: fence, widgetOnlyIfMissing: true)
    }

    func listBoard(filters: UserTaskListFilters = .init(), fence: UserTasksAccountFence) async throws -> [TaskBoardItem] {
        try await fence.check()
        let scope = try await NativeWorkspaceOfflineRuntime.configure(accountID: fence.accountID, teamID: filters.teamID)
        let data = try await inventory(scope: scope)
        return try await openBoard(data, filters: filters, fence: fence)
    }

    private func inventory(scope: NativeWorkspaceOfflineScope) async throws -> Data {
        try await NativeWorkspaceOfflineRuntime.coalescedInventory(namespace: "user-tasks", scope: scope) {
            try await self.fetchInventory(scope: scope)
        }
    }

    private func fetchInventory(scope: NativeWorkspaceOfflineScope) async throws -> Data {
        let cache = NativeWorkspaceOfflineCache.shared
        let data = try await taskInventory(scope: scope)
        try await NativeWorkspaceOfflineRuntime.check(scope)
        let path = NativeWorkspaceOfflineRuntime.inventoryPath(UserTasksPaths.base, teamID: scope.teamID)
        try await cache.retain(namespace: "user-tasks", path: path, data: data, scope: scope)
        return data
    }

    private func taskInventory(scope: NativeWorkspaceOfflineScope) async throws -> Data {
        let data = try await UserTasksInventory.fetch(teamID: scope.teamID) { path in
            try await NativeWorkspaceOfflineRuntime.request(namespace: "user-tasks", path: path,
                scope: scope, api: self.api, retain: false)
        }
        try await NativeWorkspaceOfflineRuntime.check(scope)
        return data
    }

    func maintainOffline(scope: NativeWorkspaceOfflineScope) async throws {
        let widgetFence = UserTasksAccountFence(accountID: scope.accountID)
        let data = try await taskInventory(scope: scope)
        let inventory = try await NativeWorkspaceOfflineRuntime.decodeResponse(ListResponse.self, data: data)
        let cache = NativeWorkspaceOfflineCache.shared
        let revision = try await cache.beginRefresh(namespace: "user-tasks", scope: scope)
        let listPath = NativeWorkspaceOfflineRuntime.inventoryPath(UserTasksPaths.base, teamID: scope.teamID)
        var responses = [listPath: data]
        for item in inventory.tasks {
            guard case .task(let record) = item.value else { continue }
            // Team dependency creation/reads are outside the backend's supported
            // Task model. Cache the supported personal dependency graph only.
            if scope.teamID == nil {
                let dependencies = UserTasksPaths.task(record.taskId) + "/dependencies"
                let raw = try await NativeWorkspaceOfflineRuntime.request(namespace: "user-tasks", path: dependencies,
                    scope: scope, api: api, retain: false)
                _ = try await NativeWorkspaceOfflineRuntime.decodeResponse(DependencyResponse.self, data: raw)
                responses[dependencies] = raw
            }
            var cursor: String?
            var seen: Set<String> = []
            repeat {
                let path = UserTasksPaths.activity(record.taskId, teamID: scope.teamID, cursor: cursor)
                let activity = try await NativeWorkspaceOfflineRuntime.request(namespace: "user-tasks", path: path,
                    scope: scope, api: api, retain: false)
                let page = try await NativeWorkspaceOfflineRuntime.decodeResponse(ActivityResponse.self, data: activity)
                responses[path] = activity
                if let next = page.nextCursor, !seen.insert(next).inserted { throw UserTasksError.invalidResponse }
                cursor = page.nextCursor
            } while cursor != nil
        }
        try await NativeWorkspaceOfflineRuntime.check(scope)
        try await cache.commit(namespace: "user-tasks", responses: responses, scope: scope, revision: revision)
        // The existing offline-maintenance inventory also refreshes the widget
        // when the app opens without visiting Tasks. Publication remains fenced;
        // unavailable title keys do not invalidate the encrypted offline cache.
        _ = try? await openBoard(data, filters: .init(teamID: scope.teamID), fence: widgetFence)
    }

    private func localResponse<T: Decodable & Sendable>(_ type: T.Type, path: String, teamID: String?,
                                             fence: UserTasksAccountFence) async throws -> T {
        let scope = try await NativeWorkspaceOfflineRuntime.configure(accountID: fence.accountID, teamID: teamID)
        let scopedPath = UserTasksPaths.scoped(path, teamID: path.contains("team_id=") ? nil : teamID)
        let raw: Data
        if let cached = try await NativeWorkspaceOfflineRuntime.cached(namespace: "user-tasks", path: scopedPath, scope: scope) {
            raw = cached
        } else {
            raw = try await NativeWorkspaceOfflineRuntime.request(namespace: "user-tasks", path: scopedPath, scope: scope, api: api)
        }
        try await fence.check()
        return try await NativeWorkspaceOfflineRuntime.decodeResponse(type, data: raw)
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
        try await fence.check()
        TasksWidgetBridge.upsert(opened, fence: fence, teamID: input.teamID)
        return opened
    }

    func update(_ task: UserTaskItem, patch: UserTaskUpdateInput,
                teamID: String? = nil, fence: UserTasksAccountFence) async throws -> UserTaskItem {
        try await fence.check()
        let masterKey = try await requireMasterKey(fence)
        let taskKey = try await requireTaskKey(task.record, masterKey: masterKey)
        let timestamp = Int(Date().timeIntervalSince1970)
        var json = try updateBody(for: task.record, patch: patch, key: taskKey, timestamp: timestamp)
        if let projectIDs = patch.linkedProjectIDs {
            guard let wrapped = task.record.encryptedTaskKey, !wrapped.isEmpty else {
                throw UserTasksError.taskKeyUnavailable
            }
            json["key_wrappers"] = try await keyWrappers(taskKey: taskKey,
                encryptedTaskKey: wrapped, timestamp: timestamp,
                chatID: task.primaryChatId, projectIDs: projectIDs, teamID: teamID, fence: fence)
        }
        let response: TaskResponse = try await requestJSON(.patch,
            path: UserTasksPaths.scoped(UserTasksPaths.task(task.id), teamID: teamID), body: json, fence: fence)
        try await fence.check()
        guard let opened = try await open(response.task, masterKey: masterKey) else {
            throw UserTasksError.taskKeyUnavailable
        }
        try await fence.check()
        TasksWidgetBridge.upsert(opened, fence: fence, teamID: teamID)
        return opened
    }

    // Build the production PATCH payload before adding asynchronously opened
    // Project wrappers. Content edits must not rewrite the existing assignment.
    func updateBody(for record: EncryptedUserTaskRecord, patch: UserTaskUpdateInput,
                    key taskKey: SymmetricKey, timestamp: Int) throws -> [String: Any] {
        var json: [String: Any] = ["version": try version(record), "updated_at": timestamp]
        if let title = patch.title { json["encrypted_title"] = try ComposerEmbedCrypto.encryptContent(title, using: taskKey) }
        if let description = patch.description { json["encrypted_description"] = try ComposerEmbedCrypto.encryptContent(description, using: taskKey) }
        if let tags = patch.tags { json["encrypted_tags"] = try ComposerEmbedCrypto.encryptContent(jsonArray(tags), using: taskKey) }
        if let status = patch.status { json["status"] = status.rawValue }
        if let assignee = patch.assigneeType,
           assignee != record.assigneeType || (patch.assigneeIdentity != nil && patch.assigneeIdentity != record.assigneeIdentity) {
            guard patch.assigneeIdentity != .legacyOpenCode else { throw UserTasksError.invalidResponse }
            json["assignee_type"] = assignee.rawValue
            json["assignee_identity"] = (patch.assigneeIdentity ?? (assignee == .openmates ? .openmates : nil))?.rawValue as Any? ?? NSNull()
        }
        if let projectIDs = patch.linkedProjectIDs {
            json["encrypted_linked_project_ids"] = try ComposerEmbedCrypto.encryptContent(jsonArray(projectIDs), using: taskKey)
            json["linked_project_ids"] = projectIDs
        }
        if patch.clearDueAt { json["due_at"] = NSNull() }
        else if let dueAt = patch.dueAt { json["due_at"] = dueAt }
        if let priority = patch.priority { json["priority"] = priority }
        return json
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
        try await fence.check()
        TasksWidgetBridge.upsert(opened, fence: fence, teamID: teamID)
        return opened
    }

    func move(_ task: UserTaskItem, to status: UserTaskStatus,
              position: Int? = nil, teamID: String? = nil,
              fence: UserTasksAccountFence) async throws -> UserTaskItem {
        try await fence.check()
        // Match TasksPage.persistMove: lifecycle metadata is updated before ordering.
        var transitioned = task
        if status == .done && task.status != .done {
            transitioned = try await action("complete", task: task, teamID: teamID, fence: fence)
        } else if status == .blocked && task.status != .blocked {
            transitioned = try await action("block", task: task, teamID: teamID, fence: fence)
        } else if task.status == .blocked && status != .blocked {
            transitioned = try await action("unblock", task: task, teamID: teamID, fence: fence)
        } else if status == .backlog && task.status != .backlog {
            transitioned = try await action("skip", task: task, teamID: teamID, fence: fence)
        }
        try await fence.check()
        let masterKey = try await requireMasterKey(fence)
        var move: [String: Any] = ["task_id": task.id, "status": status.rawValue,
                                  "version": try version(transitioned.record)]
        if let position { move["position"] = position }
        struct Response: Decodable { let tasks: [EncryptedUserTaskRecord] }
        let response: Response = try await requestJSON(.post, path: "\(UserTasksPaths.base)/reorder",
            body: ["moves": [move], "team_id": teamID as Any? ?? NSNull()], fence: fence)
        try await fence.check()
        guard let record = response.tasks.first,
              let opened = try await open(record, masterKey: masterKey) else {
            throw UserTasksError.invalidResponse
        }
        try await fence.check()
        TasksWidgetBridge.upsert(opened, fence: fence, teamID: teamID)
        return opened
    }

    func delete(_ task: UserTaskItem, teamID: String? = nil,
                fence: UserTasksAccountFence) async throws {
        try await fence.check()
        let path = UserTasksPaths.scoped("\(UserTasksPaths.task(task.id))?version=\(try version(task.record))",
                                         teamID: teamID)
        let _: Data = try await api.request(.delete, path: path, serverProfile: fence.serverProfile,
            expectedAccountID: fence.accountID, expectedScope: fence.scope,
            expectedTeamContext: fence.requestTeamContext)
        try await fence.check()
        TasksWidgetBridge.remove(task.id, fence: fence, teamID: teamID)
    }

    func dependencies(for task: UserTaskItem, fence: UserTasksAccountFence) async throws -> [UserTaskDependency] {
        try await fence.check()
        let response: DependencyResponse = try await localResponse(DependencyResponse.self,
            path: "\(UserTasksPaths.task(task.id))/dependencies", teamID: TeamWorkspaceContext.shared.teamID, fence: fence)
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
        var seen: Set<String> = []
        repeat {
            let response: ActivityResponse = try await localResponse(ActivityResponse.self,
                path: UserTasksPaths.activity(task.id, teamID: teamID, cursor: cursor), teamID: teamID, fence: fence)
            try await fence.check()
            entries += try response.entries.map { try openActivity($0, taskKey: taskKey) }
            if let next = response.nextCursor, !seen.insert(next).inserted { throw UserTasksError.invalidResponse }
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

    func open(_ record: EncryptedUserTaskRecord,
              masterKey: SymmetricKey) async throws -> UserTaskItem? {
        let taskKey = try await requireTaskKey(record, masterKey: masterKey)
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
        return try JSONDecoder().decode([String].self, from: data)
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
            expectedAccountID: fence.accountID, expectedScope: fence.scope,
            expectedTeamContext: fence.requestTeamContext)
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
