// Read-only Watch Tasks and Workflows data. Tasks use the same per-task key
// wrapping as the web client. Ciphertext is never used as display text.
// Specification: specifications/features/apple-watch/specification.yml
// Assertions: apple-watch.lists.read-only-private.

import CryptoKit
import Foundation

enum WatchTaskGroup: Int, CaseIterable, Identifiable {
    case backlog, todo, inProgress, blocked, done

    var id: Int { rawValue }
    var status: String {
        switch self {
        case .backlog: "backlog"
        case .todo: "todo"
        case .inProgress: "in_progress"
        case .blocked: "blocked"
        case .done: "done"
        }
    }

    static func from(status: String) -> WatchTaskGroup? {
        switch status {
        case "in_progress": return .inProgress
        case "blocked": return .blocked
        case "todo": return .todo
        case "backlog": return .backlog
        case "done": return .done
        default: return nil
        }
    }
}

struct WatchTaskListItem: Identifiable, Equatable {
    let id: String
    let title: String
    let group: WatchTaskGroup
    let status: String
    let position: Int
    let updatedAt: Int
    let openRequest: WatchItemOpenRequest
    let description: String
    let latestInstruction: String
    let activitySummary: String
    let blockedReason: String

    init(id: String, title: String, group: WatchTaskGroup, status: String,
         position: Int, updatedAt: Int, openRequest: WatchItemOpenRequest,
         description: String = "", latestInstruction: String = "",
         activitySummary: String = "", blockedReason: String = "") {
        self.id = id
        self.title = title
        self.group = group
        self.status = status
        self.position = position
        self.updatedAt = updatedAt
        self.openRequest = openRequest
        self.description = description
        self.latestInstruction = latestInstruction
        self.activitySummary = activitySummary
        self.blockedReason = blockedReason
    }
}

struct WatchWorkflowListItem: Identifiable, Equatable {
    let id: String
    let title: String
    let enabled: Bool
    let updatedAt: Int
    let category: String?
    let icon: String?
    let openRequest: WatchItemOpenRequest

    init(
        id: String, title: String, enabled: Bool, updatedAt: Int,
        category: String? = nil, icon: String? = nil,
        openRequest: WatchItemOpenRequest
    ) {
        self.id = id
        self.title = title
        self.enabled = enabled
        self.updatedAt = updatedAt
        self.category = category
        self.icon = icon
        self.openRequest = openRequest
    }
}

struct WatchTaskListResponse: Decodable {
    let tasks: [WatchTaskRecord]
}

struct WatchWorkflowListResponse: Decodable {
    let workflows: [WatchWorkflowRecord]
}

struct WatchWorkflowRecord: Decodable {
    let id: String
    let title: String
    let enabled: Bool
    let updatedAt: Int
    let category: String?
    let icon: String?
}

struct WatchTaskRecord: Decodable {
    let taskId: String
    let source: String?
    let workflowId: String?
    let title: String?
    let encryptedTaskKey: String?
    let encryptedTitle: String?
    let encryptedDescription: String?
    let encryptedLatestInstruction: String?
    let encryptedActivitySummary: String?
    let encryptedBlockedReason: String?
    let blockedMessage: String?
    let status: String
    let position: Int?
    let updatedAt: Int?
}

@MainActor
final class WatchHubDataService: ObservableObject {
    @Published private(set) var tasks: [WatchTaskListItem] = []
    @Published private(set) var workflows: [WatchWorkflowListItem] = []
    @Published private(set) var isLoadingTasks = false
    @Published private(set) var isLoadingWorkflows = false
    @Published private(set) var tasksError = false
    @Published private(set) var workflowsError = false

    private let userId: String?
    private let usesFixture: Bool

    init(userId: String?, fixtureTasks: [WatchTaskListItem]? = nil, fixtureWorkflows: [WatchWorkflowListItem]? = nil) {
        self.userId = userId
        usesFixture = fixtureTasks != nil || fixtureWorkflows != nil
        tasks = fixtureTasks ?? []
        workflows = fixtureWorkflows ?? []
    }

    func refreshTasks() async {
        if usesFixture { return }
        guard !isLoadingTasks, let userId else { return }
        isLoadingTasks = true
        defer { isLoadingTasks = false }
        do {
            let response: WatchTaskListResponse = try await APIClient.shared.request(
                .get, path: "/v1/user-tasks?limit=200"
            )
            guard let masterKey = try await CryptoManager.shared.loadMasterKey(for: userId) else {
                tasks = []
                tasksError = true
                return
            }
            var decrypted: [WatchTaskListItem] = []
            for record in response.tasks {
                if let item = await Self.openTask(record, masterKey: masterKey) {
                    decrypted.append(item)
                }
            }
            tasks = decrypted.sorted {
                if $0.group.rawValue != $1.group.rawValue { return $0.group.rawValue < $1.group.rawValue }
                if $0.position != $1.position { return $0.position < $1.position }
                return $0.updatedAt > $1.updatedAt
            }
            tasksError = false
            NativeDiagnostics.event(
                "watch_tasks_refreshed", category: "watch_hub",
                counts: ["response_rows": response.tasks.count, "displayed_rows": tasks.count]
            )
        } catch {
            tasksError = true
            NativeDiagnostics.failure(
                "watch_tasks_refresh_failed", category: "watch_hub",
                level: .warning, error: error
            )
        }
    }

    /// Uses the same account-wrapped Task key and encrypted detail fields as iPhone.
    /// A malformed optional field fails closed rather than displaying ciphertext.
    static func openTask(_ record: WatchTaskRecord, masterKey: SymmetricKey) async -> WatchTaskListItem? {
        guard let group = WatchTaskGroup.from(status: record.status) else { return nil }
        if record.source == "workflow_run" {
            guard let workflowID = record.workflowId,
                  let request = WatchItemOpenRequest(kind: .workflow, id: workflowID),
                  let title = record.title, !title.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else { return nil }
            return WatchTaskListItem(id: record.taskId, title: title, group: group,
                status: record.status, position: record.position ?? 0, updatedAt: record.updatedAt ?? 0,
                openRequest: request, blockedReason: record.blockedMessage ?? "")
        }
        guard let request = WatchItemOpenRequest(kind: .task, id: record.taskId),
              let encryptedKey = record.encryptedTaskKey, let encryptedTitle = record.encryptedTitle else { return nil }
        do {
            let taskKey = try await CryptoManager.shared.unwrapChatKey(
                encryptedChatKeyBase64: encryptedKey, masterKey: masterKey)
            let title = try await CryptoManager.shared.decryptContent(base64String: encryptedTitle, key: taskKey)
            guard !title.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else { return nil }
            let description = try await openText(record.encryptedDescription, key: taskKey)
            let instruction = try await openText(record.encryptedLatestInstruction, key: taskKey)
            let summary = try await openText(record.encryptedActivitySummary, key: taskKey)
            let blockedReason = try await openText(record.encryptedBlockedReason, key: taskKey)
            return WatchTaskListItem(id: record.taskId, title: title, group: group,
                status: record.status, position: record.position ?? 0, updatedAt: record.updatedAt ?? 0,
                openRequest: request, description: description, latestInstruction: instruction,
                activitySummary: summary, blockedReason: blockedReason)
        } catch {
            return nil
        }
    }

    private static func openText(_ ciphertext: String?, key: SymmetricKey) async throws -> String {
        guard let ciphertext, !ciphertext.isEmpty else { return "" }
        return try await CryptoManager.shared.decryptContent(base64String: ciphertext, key: key)
    }

    func refreshWorkflows() async {
        if usesFixture { return }
        guard !isLoadingWorkflows else { return }
        isLoadingWorkflows = true
        defer { isLoadingWorkflows = false }
        do {
            let response: WatchWorkflowListResponse = try await APIClient.shared.request(
                .get, path: "/v1/workflows"
            )
            workflows = response.workflows.compactMap { workflow in
                guard let request = WatchItemOpenRequest(kind: .workflow, id: workflow.id),
                      !workflow.title.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else { return nil }
                return WatchWorkflowListItem(
                    id: workflow.id, title: workflow.title,
                    enabled: workflow.enabled, updatedAt: workflow.updatedAt,
                    category: workflow.category, icon: workflow.icon,
                    openRequest: request
                )
            }.sorted { $0.updatedAt > $1.updatedAt }
            workflowsError = false
            NativeDiagnostics.event(
                "watch_workflows_refreshed", category: "watch_hub",
                counts: ["response_rows": response.workflows.count, "displayed_rows": workflows.count]
            )
        } catch {
            workflowsError = true
            NativeDiagnostics.failure(
                "watch_workflows_refresh_failed", category: "watch_hub",
                level: .warning, error: error
            )
        }
    }
}
