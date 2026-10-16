// Workflow API models shared by the native Workflows surface.
// These structs mirror the server, web, CLI, npm SDK, and pip SDK contract.
// They intentionally keep graph/config payloads as AnyCodable so Apple can
// render and forward V1 workflows without narrowing app-skill schemas too early.
// Spec: docs/specs/workflows-v1/spec.yml
// Web source: frontend/packages/ui/src/components/workflows/WorkflowSchemaFields.svelte
//             frontend/packages/ui/src/components/workflows/workflowBuilder.ts
// Specification: specifications/features/workflows/specification.yml
// Assertions: workflows.actions.skill-contract, workflows.control.typed-data, workflows.execution.lifecycle-visible

import Foundation

/// Presents the single request authored by an app-action node without exposing
/// the skill API's batch envelope. Existing saved entries remain editable rather
/// than being silently truncated when a workflow is opened or saved.
struct WorkflowRequestInputProjection {
    let outerSchema: [String: Any]
    let requestSchema: [String: Any]
    let requests: [Any]
    private let input: [String: Any]

    init?(schema: [String: Any], input: [String: Any]) {
        guard var properties = schema["properties"] as? [String: Any],
              let envelope = properties["requests"] as? [String: Any],
              envelope["type"] as? String == "array",
              let items = envelope["items"] as? [String: Any],
              items["type"] as? String == "object" || items["properties"] is [String: Any]
        else { return nil }
        self.input = input
        requestSchema = items
        let stored = input["requests"] as? [Any] ?? []
        requests = stored.isEmpty ? [Self.schemaDefault(items)] : stored
        properties.removeValue(forKey: "requests")
        var outer = schema
        outer["properties"] = properties
        outer["required"] = (schema["required"] as? [String] ?? []).filter { $0 != "requests" }
        outerSchema = outer
    }

    func replacingRequest(at index: Int, with request: [String: Any]) -> [String: Any] {
        guard requests.indices.contains(index) else { return input }
        var nextRequests = requests
        nextRequests[index] = request
        var next = input
        next["requests"] = nextRequests
        return next
    }

    static func displayType(_ schema: [String: Any]) -> String {
        let ui = schema["x-ui"] as? [String: Any] ?? [:]
        if ui["control"] as? String == "location" { return "location" }
        switch schema["format"] as? String {
        case "date": return "date"
        case "time": return "time"
        case "uri", "url": return "url"
        default: break
        }
        switch schema["type"] as? String {
        case "integer": return "number"
        case "array": return "list"
        case "string", nil: return "text"
        case let type?: return type
        }
    }

    private static func schemaDefault(_ schema: [String: Any]) -> Any {
        if let value = schema["default"] { return value }
        switch schema["type"] as? String {
        case "object":
            let properties = schema["properties"] as? [String: [String: Any]] ?? [:]
            let required = Set(schema["required"] as? [String] ?? [])
            var result = properties.filter { required.contains($0.key) || $0.value["default"] != nil }
                .mapValues(schemaDefault)
            let ui = schema["x-ui"] as? [String: Any] ?? [:]
            if ui["control"] as? String == "date-range", ui["default"] as? String == "today" {
                result[ui["start_field"] as? String ?? "start_date"] = ["$date": "today", "format": "date"]
                result[ui["end_field"] as? String ?? "end_date"] = ["$date": "today", "format": "date"]
                if (properties["days"]?["x-ui"] as? [String: Any])?["hidden"] as? Bool == true {
                    result.removeValue(forKey: "days")
                }
            }
            return result
        case "array":
            let items = schema["items"] as? [String: Any] ?? [:]
            return items["type"] as? String == "object" ? [schemaDefault(items)] : []
        case "boolean": return false
        case "number", "integer": return schema["minimum"] ?? 0
        default: return ""
        }
    }
}

enum WorkflowNodeType: String, Codable, Sendable {
    case scheduleTrigger = "schedule_trigger"
    case manualTrigger = "manual_trigger"
    case webhookTrigger = "webhook_trigger"
    case eventTrigger = "event_trigger"
    case appSkillAction = "app_skill_action"
    case decision
    case check
    case `repeat`
    case createChatReport = "create_chat_report"
    case sendChatMessage = "send_chat_message"
    case startNewChat = "start_new_chat"
    case sendNotification = "send_notification"
    case sendEmailNotification = "send_email_notification"
    case askUser = "ask_user"
    case wait
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

enum WorkflowLifecycle: String, Codable, Sendable {
    case persisted
    case temporary
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

extension WorkflowNode {
    init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        id = try container.decode(String.self, forKey: .id)
        type = try container.decode(WorkflowNodeType.self, forKey: .type)
        title = try container.decodeIfPresent(String.self, forKey: .title)
        config = try container.decodeIfPresent([String: AnyCodable].self, forKey: .config) ?? [:]
        inputMapping = try container.decodeIfPresent([String: AnyCodable].self, forKey: .inputMapping) ?? [:]
        ui = try container.decodeIfPresent([String: AnyCodable].self, forKey: .ui) ?? [:]
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

extension WorkflowGraph {
    init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        version = try container.decodeIfPresent(Int.self, forKey: .version) ?? 1
        triggerNodeId = try container.decodeIfPresent(String.self, forKey: .triggerNodeId) ?? ""
        nodes = try container.decodeIfPresent([WorkflowNode].self, forKey: .nodes) ?? []
        edges = try container.decodeIfPresent([WorkflowEdge].self, forKey: .edges) ?? []
        variables = try container.decodeIfPresent([String: AnyCodable].self, forKey: .variables) ?? [:]
        limits = try container.decodeIfPresent([String: AnyCodable].self, forKey: .limits) ?? [:]
        uiLayout = try container.decodeIfPresent([String: AnyCodable].self, forKey: .uiLayout) ?? [:]
    }

    func encode(to encoder: Encoder) throws {
        var container = encoder.container(keyedBy: CodingKeys.self)
        try container.encode(version, forKey: .version)
        if triggerNodeId.isEmpty { try container.encodeNil(forKey: .triggerNodeId) }
        else { try container.encode(triggerNodeId, forKey: .triggerNodeId) }
        try container.encode(nodes, forKey: .nodes)
        try container.encode(edges, forKey: .edges)
        try container.encode(variables, forKey: .variables)
        try container.encode(limits, forKey: .limits)
        try container.encode(uiLayout, forKey: .uiLayout)
    }
}

struct WorkflowSummary: Codable, Identifiable, Sendable {
    let id: String
    let title: String
    let description: String?
    let status: String
    let enabled: Bool
    let lifecycle: WorkflowLifecycle
    let source: String
    let sourceChatId: String?
    let createdByAssistant: Bool
    let autoDeleteAt: Int?
    let keptAt: Int?
    let triggerSummary: String?
    let nextRunAt: Int?
    let lastRunStatus: String?
    let runContentRetention: WorkflowRunContentRetention
    let currentVersionId: String
    let createdAt: Int
    let updatedAt: Int
    var category: String? = nil
    var icon: String? = nil
    var version: Int? = nil

    enum CodingKeys: String, CodingKey {
        case id
        case title
        case description
        case status
        case enabled
        case lifecycle
        case source
        case sourceChatId = "source_chat_id"
        case createdByAssistant = "created_by_assistant"
        case autoDeleteAt = "auto_delete_at"
        case keptAt = "kept_at"
        case triggerSummary = "trigger_summary"
        case nextRunAt = "next_run_at"
        case lastRunStatus = "last_run_status"
        case runContentRetention = "run_content_retention"
        case currentVersionId = "current_version_id"
        case createdAt = "created_at"
        case updatedAt = "updated_at"
        case category
        case icon
        case version
    }
}

struct WorkflowDetail: Codable, Identifiable, Sendable {
    let id: String
    let title: String
    let description: String?
    let status: String
    let enabled: Bool
    let lifecycle: WorkflowLifecycle
    let source: String
    let sourceChatId: String?
    let createdByAssistant: Bool
    let autoDeleteAt: Int?
    let keptAt: Int?
    let triggerSummary: String?
    let nextRunAt: Int?
    let lastRunStatus: String?
    let runContentRetention: WorkflowRunContentRetention
    let currentVersionId: String
    let createdAt: Int
    let updatedAt: Int
    let graph: WorkflowGraph
    var category: String? = nil
    var icon: String? = nil
    var version: Int? = nil

    enum CodingKeys: String, CodingKey {
        case id
        case title
        case description
        case status
        case enabled
        case lifecycle
        case source
        case sourceChatId = "source_chat_id"
        case createdByAssistant = "created_by_assistant"
        case autoDeleteAt = "auto_delete_at"
        case keptAt = "kept_at"
        case triggerSummary = "trigger_summary"
        case nextRunAt = "next_run_at"
        case lastRunStatus = "last_run_status"
        case runContentRetention = "run_content_retention"
        case currentVersionId = "current_version_id"
        case createdAt = "created_at"
        case updatedAt = "updated_at"
        case graph
        case category
        case icon
        case version
    }
}

struct WorkflowNodeRun: Codable, Identifiable, Sendable {
    let id: String
    let runId: String
    let workflowId: String
    let nodeId: String
    let nodeType: WorkflowNodeType
    let status: String
    let startedAt: Int?
    let finishedAt: Int?
    let attempt: Int
    let skippedReason: String?
    let errorCode: String?
    let errorSummary: String?
    let inputSummary: [String: AnyCodable]
    let outputSummary: [String: AnyCodable]
    let creditCost: Int

    enum CodingKeys: String, CodingKey {
        case id
        case runId = "run_id"
        case workflowId = "workflow_id"
        case nodeId = "node_id"
        case nodeType = "node_type"
        case status
        case startedAt = "started_at"
        case finishedAt = "finished_at"
        case attempt
        case skippedReason = "skipped_reason"
        case errorCode = "error_code"
        case errorSummary = "error_summary"
        case inputSummary = "input_summary"
        case outputSummary = "output_summary"
        case creditCost = "credit_cost"
    }
}

extension WorkflowNodeRun {
    init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        id = try container.decode(String.self, forKey: .id)
        runId = try container.decode(String.self, forKey: .runId)
        workflowId = try container.decode(String.self, forKey: .workflowId)
        nodeId = try container.decode(String.self, forKey: .nodeId)
        nodeType = try container.decode(WorkflowNodeType.self, forKey: .nodeType)
        status = try container.decode(String.self, forKey: .status)
        startedAt = try container.decodeIfPresent(Int.self, forKey: .startedAt)
        finishedAt = try container.decodeIfPresent(Int.self, forKey: .finishedAt)
        attempt = try container.decodeIfPresent(Int.self, forKey: .attempt) ?? 1
        skippedReason = try container.decodeIfPresent(String.self, forKey: .skippedReason)
        errorCode = try container.decodeIfPresent(String.self, forKey: .errorCode)
        errorSummary = try container.decodeIfPresent(String.self, forKey: .errorSummary)
        inputSummary = try container.decodeIfPresent([String: AnyCodable].self, forKey: .inputSummary) ?? [:]
        outputSummary = try container.decodeIfPresent([String: AnyCodable].self, forKey: .outputSummary) ?? [:]
        creditCost = try container.decodeIfPresent(Int.self, forKey: .creditCost) ?? 0
    }
}

struct WorkflowRunSummary: Codable, Identifiable, Sendable {
    let id: String
    let workflowId: String
    let versionId: String
    var triggerType: String = "manual"
    var status: String = "queued"
    var startedAt: Int? = nil
    var finishedAt: Int? = nil
    var errorSummary: String? = nil
    var contentAvailable: Bool = false
    var nodeRuns: [WorkflowNodeRun] = []
    var outputSummary: [String: AnyCodable] = [:]

    enum CodingKeys: String, CodingKey {
        case id, status
        case workflowId = "workflow_id"
        case versionId = "version_id"
        case triggerType = "trigger_type"
        case startedAt = "started_at"
        case finishedAt = "finished_at"
        case errorSummary = "error_summary"
        case contentAvailable = "content_available"
        case nodeRuns = "node_runs"
        case outputSummary = "output_summary"
    }
}

extension WorkflowRunSummary {
    init(detail: WorkflowRunDetail) {
        id = detail.id
        workflowId = detail.workflowId
        versionId = detail.versionId
        triggerType = detail.triggerType
        status = detail.status
        startedAt = detail.startedAt
        finishedAt = detail.finishedAt
        errorSummary = detail.errorSummary
        contentAvailable = detail.contentAvailable
        nodeRuns = detail.nodeRuns
        outputSummary = detail.outputSummary
    }

    init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        id = try container.decode(String.self, forKey: .id)
        workflowId = try container.decode(String.self, forKey: .workflowId)
        versionId = try container.decode(String.self, forKey: .versionId)
        triggerType = try container.decodeIfPresent(String.self, forKey: .triggerType) ?? "manual"
        status = try container.decodeIfPresent(String.self, forKey: .status) ?? "queued"
        startedAt = try container.decodeIfPresent(Int.self, forKey: .startedAt)
        finishedAt = try container.decodeIfPresent(Int.self, forKey: .finishedAt)
        errorSummary = try container.decodeIfPresent(String.self, forKey: .errorSummary)
        contentAvailable = try container.decodeIfPresent(Bool.self, forKey: .contentAvailable) ?? false
        nodeRuns = try container.decodeIfPresent([WorkflowNodeRun].self, forKey: .nodeRuns) ?? []
        outputSummary = try container.decodeIfPresent([String: AnyCodable].self, forKey: .outputSummary) ?? [:]
    }
}

struct WorkflowRunDetail: Codable, Identifiable, Sendable {
    let id: String
    let workflowId: String
    let versionId: String
    let triggerType: String
    let status: String
    let startedAt: Int?
    let finishedAt: Int?
    let errorSummary: String?
    let costSummary: [String: AnyCodable]
    let contentRetentionMode: WorkflowRunContentRetention
    let contentAvailable: Bool
    let contentStorage: WorkflowRunContentStorage?
    let contentExpiresAt: Int?
    let nodeRuns: [WorkflowNodeRun]
    let outputSummary: [String: AnyCodable]
    let completionNotification: WorkflowCompletionNotificationTarget?

    enum CodingKeys: String, CodingKey {
        case id
        case workflowId = "workflow_id"
        case versionId = "version_id"
        case triggerType = "trigger_type"
        case status
        case startedAt = "started_at"
        case finishedAt = "finished_at"
        case errorSummary = "error_summary"
        case costSummary = "cost_summary"
        case contentRetentionMode = "content_retention_mode"
        case contentAvailable = "content_available"
        case contentStorage = "content_storage"
        case contentExpiresAt = "content_expires_at"
        case nodeRuns = "node_runs"
        case outputSummary = "output_summary"
        case completionNotification = "completion_notification"
    }
}

extension WorkflowRunDetail {
    init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        id = try container.decode(String.self, forKey: .id)
        workflowId = try container.decode(String.self, forKey: .workflowId)
        versionId = try container.decode(String.self, forKey: .versionId)
        triggerType = try container.decodeIfPresent(String.self, forKey: .triggerType) ?? "manual"
        status = try container.decode(String.self, forKey: .status)
        startedAt = try container.decodeIfPresent(Int.self, forKey: .startedAt)
        finishedAt = try container.decodeIfPresent(Int.self, forKey: .finishedAt)
        errorSummary = try container.decodeIfPresent(String.self, forKey: .errorSummary)
        costSummary = try container.decodeIfPresent([String: AnyCodable].self, forKey: .costSummary) ?? [:]
        contentRetentionMode = try container.decodeIfPresent(WorkflowRunContentRetention.self, forKey: .contentRetentionMode) ?? .last5
        contentAvailable = try container.decodeIfPresent(Bool.self, forKey: .contentAvailable) ?? false
        contentStorage = try container.decodeIfPresent(WorkflowRunContentStorage.self, forKey: .contentStorage)
        contentExpiresAt = try container.decodeIfPresent(Int.self, forKey: .contentExpiresAt)
        nodeRuns = try container.decodeIfPresent([WorkflowNodeRun].self, forKey: .nodeRuns) ?? []
        outputSummary = try container.decodeIfPresent([String: AnyCodable].self, forKey: .outputSummary) ?? [:]
        completionNotification = try container.decodeIfPresent(WorkflowCompletionNotificationTarget.self, forKey: .completionNotification)
    }
}

struct WorkflowCompletionNotificationTarget: Codable, Sendable {
    let notificationID: String
    let chatID: String?
    let messageID: String?
    let deliveryID: String?

    enum CodingKeys: String, CodingKey {
        case notificationID = "notification_id"
        case chatID = "chat_id"
        case messageID = "message_id"
        case deliveryID = "delivery_id"
    }
}

struct WorkflowVersionSummary: Codable, Identifiable, Sendable {
    let versionId: String
    let versionNumber: Int
    let createdAt: Int
    let createdByClient: String
    let graphHash: String
    let restoredFromVersionId: String?
    let current: Bool
    let changeSummary: [String: AnyCodable]?
    var id: String { versionId }

    enum CodingKeys: String, CodingKey {
        case versionId = "version_id"
        case versionNumber = "version_number"
        case createdAt = "created_at"
        case createdByClient = "created_by_client"
        case graphHash = "graph_hash"
        case restoredFromVersionId = "restored_from_version_id"
        case current
        case changeSummary = "change_summary"
    }
}

struct WorkflowVersionDetail: Codable, Sendable {
    let versionId: String
    let versionNumber: Int
    let graph: WorkflowGraph

    enum CodingKeys: String, CodingKey {
        case graph
        case versionId = "version_id"
        case versionNumber = "version_number"
    }
}

struct WorkflowVersionHistory: Codable, Sendable {
    let versions: [WorkflowVersionSummary]
    let currentVersionId: String
    let retention: [String: AnyCodable]

    enum CodingKeys: String, CodingKey {
        case versions, retention
        case currentVersionId = "current_version_id"
    }
}

struct WorkflowCapability: Codable, Identifiable, Sendable {
    let type: String
    let id: String
    let title: String
    let enabled: Bool
    let reason: String?
    let metadata: [String: AnyCodable]
}

struct WorkflowCapabilitiesResponse: Codable, Sendable {
    let capabilities: [WorkflowCapability]
}

struct WorkflowVersionResponse: Codable, Sendable {
    let version: WorkflowVersionDetail
}

struct WorkflowRunStatusResponse: Codable, Sendable {
    let status: String
}

struct WorkflowDeleteResponse: Codable, Sendable {
    let deleted: Bool
}

struct WorkflowListResponse: Codable, Sendable {
    let workflows: [WorkflowSummary]
}

struct WorkflowResponse: Codable, Sendable {
    let workflow: WorkflowDetail
}

struct WorkflowRunsResponse: Codable, Sendable {
    let runs: [WorkflowRunSummary]
}

struct WorkflowRunResponse: Codable, Sendable {
    let run: WorkflowRunDetail
}

// Node badges follow WorkflowGraphRenderer's status aliases. A terminal parent
// never changes an individual node's outcome or retained encrypted summaries.
enum WorkflowNodeRunPresentation: String {
    case completed, failed, cancelled, skipped, queued, running, cancellationRequested = "cancellation_requested", waiting

    init(status: String) {
        switch status {
        case "acknowledged", "completed", "no_new_results": self = .completed
        case "failed", "expired": self = .failed
        case "cancelled": self = .cancelled
        case "skipped": self = .skipped
        case "queued": self = .queued
        case "running": self = .running
        case "cancellation_requested": self = .cancellationRequested
        default: self = .waiting
        }
    }
}

extension WorkflowRunDetail {
    var needsLiveRefresh: Bool {
        // Match web shouldPollWorkflowRunDetail: terminal executions stop
        // polling once chat delivery is resolved. Stale unfinished node records
        // receive the canonical terminal presentation below.
        if !WorkflowRunSummary.terminalStatuses.contains(status) { return true }
        return WorkflowRunSummary(detail: self).deliveryState() == .pending
    }

    func needsRefresh(comparedTo summary: WorkflowRunSummary) -> Bool {
        id == summary.id && (needsLiveRefresh || status != summary.status || finishedAt != summary.finishedAt
            || contentAvailable != summary.contentAvailable)
    }
}

extension WorkflowNodeRun {
    var isChatDelivery: Bool { [.sendChatMessage, .startNewChat, .createChatReport].contains(nodeType) }

    var deliveryStatus: String {
        guard isChatDelivery, !["failed", "cancelled", "skipped"].contains(status) else { return status }
        if let delivery = outputSummary["status"]?.value as? String,
           ["acknowledged", "no_new_results", "delivery_pending", "claimed", "expired", "cancelled", "failed"].contains(delivery) {
            if ["delivery_pending", "claimed", "acknowledged"].contains(delivery),
               (outputSummary["delivery_id"]?.value as? String)?.isEmpty != false { return "failed" }
            return delivery
        }
        if status == "completed" {
            return (outputSummary["delivery_id"]?.value as? String)?.isEmpty == false ? "delivery_pending" : "failed"
        }
        return status
    }

    func presentationStatus(executionStatus: String?) -> String {
        let projected = isChatDelivery ? deliveryStatus : status
        guard let executionStatus, WorkflowRunSummary.terminalStatuses.contains(executionStatus) else { return projected }
        if isChatDelivery, ["delivery_pending", "claimed"].contains(projected) { return projected }
        if ["planned", "queued", "running", "waiting", "cancellation_requested"].contains(projected) {
            return executionStatus == "cancelled" ? "cancelled" : "failed"
        }
        return projected
    }
}

extension WorkflowRunSummary {
    static let terminalStatuses: Set<String> = ["completed", "failed", "cancelled", "skipped", "skipped_by_user"]
    enum DeliveryState { case pending, failed }

    private var deliveryStatuses: [String: String] {
        var result = Dictionary(nodeRuns.filter(\.isChatDelivery).map { ($0.nodeId, $0.deliveryStatus) },
                                uniquingKeysWith: { _, newer in newer })
        let deliveries = outputSummary["deliveries"]?.value as? [String: Any] ?? [:]
        for (nodeID, value) in deliveries {
            guard let delivery = value as? [String: Any], let status = delivery["status"] as? String else { continue }
            result[nodeID] = ["delivery_pending", "claimed", "acknowledged"].contains(status)
                && (delivery["delivery_id"] as? String)?.isEmpty != false ? "failed" : status
        }
        return result
    }

    func deliveryState(detail: WorkflowRunDetail? = nil) -> DeliveryState? {
        var statuses = deliveryStatuses
        if let detail, detail.id == id, detail.workflowId == workflowId {
            for (nodeID, status) in WorkflowRunSummary(detail: detail).deliveryStatuses {
                let terminal = ["acknowledged", "no_new_results", "expired", "cancelled", "failed"]
                if statuses[nodeID] == nil || terminal.contains(status) || !terminal.contains(statuses[nodeID] ?? "") {
                    statuses[nodeID] = status
                }
            }
        }
        if statuses.values.contains(where: { ["delivery_pending", "claimed"].contains($0) }) { return .pending }
        if statuses.values.contains(where: { ["expired", "cancelled", "failed"].contains($0) }) { return .failed }
        return nil
    }

    func displayStatus(detail: WorkflowRunDetail? = nil) -> String {
        if ["failed", "cancelled", "skipped", "skipped_by_user"].contains(status) { return status }
        switch deliveryState(detail: detail) {
        case .pending: return "waiting"
        case .failed: return "failed"
        case nil: return status
        }
    }
}
