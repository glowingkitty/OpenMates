// Workflow API models shared by the native Workflows surface.
// These structs mirror the server, web, CLI, npm SDK, and pip SDK contract.
// They intentionally keep graph/config payloads as AnyCodable so Apple can
// render and forward V1 workflows without narrowing app-skill schemas too early.
// Spec: docs/specs/workflows-v1/spec.yml

import Foundation

enum WorkflowNodeType: String, Codable, Sendable {
    case scheduleTrigger = "schedule_trigger"
    case manualTrigger = "manual_trigger"
    case webhookTrigger = "webhook_trigger"
    case appSkillAction = "app_skill_action"
    case decision
    case `repeat`
    case createChatReport = "create_chat_report"
    case sendNotification = "send_notification"
    case sendEmailNotification = "send_email_notification"
    case askUser = "ask_user"
    case customCode = "custom_code"
    case end
}

enum WorkflowRunContentRetention: String, Codable, Sendable {
    case last5 = "last_5"
    case none
}

enum WorkflowRunContentStorage: String, Codable, Sendable {
    case durable
    case ephemeral
    case deleted
}

struct WorkflowNode: Codable, Identifiable, Sendable {
    let id: String
    let type: WorkflowNodeType
    let title: String?
    let config: [String: AnyCodable]
    let inputMapping: [String: AnyCodable]
    let ui: [String: AnyCodable]

    enum CodingKeys: String, CodingKey {
        case id
        case type
        case title
        case config
        case inputMapping = "input_mapping"
        case ui
    }
}

struct WorkflowEdge: Codable, Sendable {
    let from: String
    let to: String
    let branch: String?
}

struct WorkflowGraph: Codable, Sendable {
    let version: Int
    let triggerNodeId: String
    let nodes: [WorkflowNode]
    let edges: [WorkflowEdge]
    let variables: [String: AnyCodable]
    let limits: [String: AnyCodable]
    let uiLayout: [String: AnyCodable]

    enum CodingKeys: String, CodingKey {
        case version
        case triggerNodeId = "trigger_node_id"
        case nodes
        case edges
        case variables
        case limits
        case uiLayout = "ui_layout"
    }
}

struct WorkflowSummary: Codable, Identifiable, Sendable {
    let id: String
    let title: String
    let status: String
    let enabled: Bool
    let triggerSummary: String?
    let nextRunAt: Int?
    let lastRunStatus: String?
    let runContentRetention: WorkflowRunContentRetention
    let currentVersionId: String
    let createdAt: Int
    let updatedAt: Int

    enum CodingKeys: String, CodingKey {
        case id
        case title
        case status
        case enabled
        case triggerSummary = "trigger_summary"
        case nextRunAt = "next_run_at"
        case lastRunStatus = "last_run_status"
        case runContentRetention = "run_content_retention"
        case currentVersionId = "current_version_id"
        case createdAt = "created_at"
        case updatedAt = "updated_at"
    }
}

struct WorkflowDetail: Codable, Identifiable, Sendable {
    let id: String
    let title: String
    let status: String
    let enabled: Bool
    let triggerSummary: String?
    let nextRunAt: Int?
    let lastRunStatus: String?
    let runContentRetention: WorkflowRunContentRetention
    let currentVersionId: String
    let createdAt: Int
    let updatedAt: Int
    let graph: WorkflowGraph

    enum CodingKeys: String, CodingKey {
        case id
        case title
        case status
        case enabled
        case triggerSummary = "trigger_summary"
        case nextRunAt = "next_run_at"
        case lastRunStatus = "last_run_status"
        case runContentRetention = "run_content_retention"
        case currentVersionId = "current_version_id"
        case createdAt = "created_at"
        case updatedAt = "updated_at"
        case graph
    }
}

struct WorkflowNodeRun: Codable, Identifiable, Sendable {
    let id: String
    let runId: String
    let workflowId: String
    let nodeId: String
    let nodeType: WorkflowNodeType
    let status: String
    let outputSummary: [String: AnyCodable]

    enum CodingKeys: String, CodingKey {
        case id
        case runId = "run_id"
        case workflowId = "workflow_id"
        case nodeId = "node_id"
        case nodeType = "node_type"
        case status
        case outputSummary = "output_summary"
    }
}

struct WorkflowRunDetail: Codable, Identifiable, Sendable {
    let id: String
    let workflowId: String
    let versionId: String
    let triggerType: String
    let status: String
    let contentRetentionMode: WorkflowRunContentRetention
    let contentAvailable: Bool
    let contentStorage: WorkflowRunContentStorage?
    let contentExpiresAt: Int?
    let nodeRuns: [WorkflowNodeRun]

    enum CodingKeys: String, CodingKey {
        case id
        case workflowId = "workflow_id"
        case versionId = "version_id"
        case triggerType = "trigger_type"
        case status
        case contentRetentionMode = "content_retention_mode"
        case contentAvailable = "content_available"
        case contentStorage = "content_storage"
        case contentExpiresAt = "content_expires_at"
        case nodeRuns = "node_runs"
    }
}

struct WorkflowListResponse: Codable, Sendable {
    let workflows: [WorkflowSummary]
}

struct WorkflowResponse: Codable, Sendable {
    let workflow: WorkflowDetail
}

struct WorkflowRunsResponse: Codable, Sendable {
    let runs: [WorkflowRunDetail]
}

struct WorkflowRunResponse: Codable, Sendable {
    let run: WorkflowRunDetail
}
