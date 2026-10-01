// Native Tasks models. Wire fields mirror userTaskService.ts and /v1/user-tasks.
// Encrypted content is kept in memory only after the account master key unlocks it.

import Foundation

enum UserTaskStatus: String, Codable, CaseIterable, Sendable, Identifiable {
    case backlog, todo, inProgress = "in_progress", blocked, done

    var id: String { rawValue }
    var title: String {
        switch self {
        case .backlog: "Backlog"
        case .todo: "Todo"
        case .inProgress: "In progress"
        case .blocked: "Blocked"
        case .done: "Done"
        }
    }
}

enum UserTaskAssigneeType: String, Codable, Sendable {
    case user, openmates, externalAI = "external_ai", unassigned
}

enum UserTaskAssigneeIdentity: String, Codable, Sendable {
    case openmates, codex

    var title: String { self == .codex ? "Codex" : "OpenMates" }
}

enum UserTaskBlockedReason: String, Codable, Sendable {
    case needsUserInput = "needs_user_input"
    case waitingForApproval = "waiting_for_approval"
    case missingCredentials = "missing_credentials"
    case ambiguousRequirement = "ambiguous_requirement"
    case externalDependency = "external_dependency"
    case environmentUnavailable = "environment_unavailable"
    case verificationFailed = "verification_failed"
    case other
}

struct UserTaskKeyWrapper: Codable, Sendable {
    let keyType: String
    let encryptedTaskKey: String
    let hashedChatId: String?
    let hashedProjectId: String?
    let hashedPlanId: String?
    let createdAt: Int
    let expiresAt: Int?

    init(keyType: String, encryptedTaskKey: String, hashedChatId: String? = nil,
         hashedProjectId: String? = nil, hashedPlanId: String? = nil,
         createdAt: Int, expiresAt: Int? = nil) {
        self.keyType = keyType
        self.encryptedTaskKey = encryptedTaskKey
        self.hashedChatId = hashedChatId
        self.hashedProjectId = hashedProjectId
        self.hashedPlanId = hashedPlanId
        self.createdAt = createdAt
        self.expiresAt = expiresAt
    }
}

struct EncryptedUserTaskRecord: Codable, Sendable {
    let taskId: String
    let encryptedTaskKey: String?
    let encryptedTitle: String
    let encryptedDescription: String?
    let encryptedTags: String?
    let encryptedActivitySummary: String?
    let encryptedLatestInstruction: String?
    let encryptedLinkedProjectIds: String?
    let encryptedBlockedReason: String?
    let encryptedExternalChatId: String?
    let encryptedExternalChatTitle: String?
    let status: UserTaskStatus
    let assigneeType: UserTaskAssigneeType
    let assigneeIdentity: UserTaskAssigneeIdentity?
    let assigneeHash: String?
    let primaryChatId: String?
    let externalChatProvider: String?
    let externalChatLookupHash: String?
    let linkedProjectIds: [String]?
    let linkedProjectHashes: [String]?
    let parentTaskId: String?
    let planId: String?
    let dueAt: Int?
    let priority: Int?
    let position: Int?
    let version: Int?
    let createdAt: Int
    let updatedAt: Int
    let startedAt: Int?
    let completedAt: Int?
    let blockedReasonCode: UserTaskBlockedReason?
    let aiExecutionState: String?
    let keyWrappers: [UserTaskKeyWrapper]?
}

struct UserTaskExternalChat: Sendable, Equatable {
    let provider: String
    let id: String
    let title: String
}

struct UserTaskItem: Identifiable, Sendable {
    let record: EncryptedUserTaskRecord
    let title: String
    let description: String
    let latestInstruction: String
    let tags: [String]
    let linkedProjectIds: [String]
    let blockedReason: String
    let externalChat: UserTaskExternalChat?

    var id: String { record.taskId }
    var status: UserTaskStatus { record.status }
    var assigneeType: UserTaskAssigneeType { record.assigneeType }
    var assigneeIdentity: UserTaskAssigneeIdentity? { record.assigneeIdentity }
    var primaryChatId: String? { record.primaryChatId }
    var planId: String? { record.planId }
    var dueAt: Int? { record.dueAt }
    var priority: Int { record.priority ?? 0 }
    var position: Int { record.position ?? 0 }
    var version: Int { record.version ?? 0 }
}

struct WorkflowRunTaskProjection: Codable, Identifiable, Sendable {
    let taskId: String
    let source: String
    let projectionKind: String
    let workflowId: String
    let workflowRunId: String?
    let triggerId: String?
    let label: String
    let title: String?
    let status: UserTaskStatus
    let runStatus: String
    let canCancel: Bool
    let canDelete: Bool?
    let dueAt: Int?
    let scheduledAt: Int?
    let blockedMessage: String?
    let readOnly: Bool
    let createdAt: Int
    let updatedAt: Int
    let position: Int

    var id: String { taskId }
    var displayTitle: String { title ?? label }
}

enum TaskBoardItem: Identifiable, Sendable {
    case task(UserTaskItem)
    case workflowRun(WorkflowRunTaskProjection)

    var id: String {
        switch self {
        case .task(let task): task.id
        case .workflowRun(let run): run.id
        }
    }
    var title: String {
        switch self {
        case .task(let task): task.title
        case .workflowRun(let run): run.displayTitle
        }
    }
    var status: UserTaskStatus {
        switch self {
        case .task(let task): task.status
        case .workflowRun(let run): run.status
        }
    }
    var position: Int {
        switch self {
        case .task(let task): task.position
        case .workflowRun(let run): run.position
        }
    }
}

struct TaskBoardRecord: Decodable, Sendable {
    let value: TaskBoardRecordValue

    init(from decoder: Decoder) throws {
        let discriminator = try decoder.container(keyedBy: Discriminator.self)
        if try discriminator.decodeIfPresent(String.self, forKey: .source) == "workflow_run" {
            value = .workflowRun(try WorkflowRunTaskProjection(from: decoder))
        } else {
            value = .task(try EncryptedUserTaskRecord(from: decoder))
        }
    }

    private enum Discriminator: String, CodingKey { case source }
}

enum TaskBoardRecordValue: Sendable {
    case task(EncryptedUserTaskRecord)
    case workflowRun(WorkflowRunTaskProjection)
}

struct UserTaskProposal: Codable, Sendable, Identifiable {
    let title: String
    let description: String?
    let status: UserTaskStatus?
    let assigneeType: UserTaskAssigneeType?

    var id: String { title }
}

struct UserTaskDependency: Decodable, Sendable, Identifiable {
    let edgeId: String?
    let targetRef: String
    let targetKind: String
    let targetId: String
    let targetStatus: String?
    let satisfied: Bool

    var id: String { edgeId ?? targetRef }
}

struct UserTaskActivityRecord: Codable, Sendable, Identifiable {
    let entryId: String
    let taskId: String
    let kind: String
    let actorType: String
    let actorIdentity: UserTaskAssigneeIdentity?
    let actorHash: String?
    let actorDisplayName: String?
    let actorProfileImageUrl: String?
    let authorHash: String?
    let eventType: String
    let sourceSurface: String
    let previousStatus: UserTaskStatus?
    let nextStatus: UserTaskStatus?
    let createdAt: Int
    let deletedAt: Int?
    let deletedByHash: String?
    let deletedByDisplayName: String?
    let encryptedMessage: String?
    let encryptedEmbedKeyMaterial: String?
    let embedRefs: [String]

    var id: String { entryId }
}

struct UserTaskActivityEntry: Identifiable, Sendable {
    let record: UserTaskActivityRecord
    let message: String?
    let embedKeyMaterial: String?

    var id: String { record.entryId }
}
