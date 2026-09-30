// Native transport for the workflow natural-language authoring session.
// Web source: frontend/packages/ui/src/services/workflowInputService.ts
//             frontend/apps/web_app/src/routes/workflows/+page.svelte
// Specification: specifications/features/workflows/specification.yml
// AI authoring behavior follows the deployed web contract and user's Apple scope.

import Foundation

struct WorkflowInputChange: Decodable, Sendable {
    let workflowId: String
    let addedNodeIds: [String]
    let editedNodeIds: [String]
    let removedNodes: [WorkflowRemovedNode]

    enum CodingKeys: String, CodingKey {
        case workflowId = "workflow_id"
        case addedNodeIds = "added_node_ids"
        case editedNodeIds = "edited_node_ids"
        case removedNodes = "removed_nodes"
    }
}

struct WorkflowRemovedNode: Decodable, Sendable {
    let id: String
    let title: String
}

struct WorkflowInputSession: Decodable, Sendable {
    let sessionId: String
    let status: String
    let message: String?
    let error: String?
    let errorCode: String?
    let workflow: WorkflowDetail?
    let previewWorkflow: WorkflowDetail?
    let workflows: [WorkflowDetail]?
    let changes: [WorkflowInputChange]?
    let assumptions: [String]?
    let undoAvailable: Bool?

    var committedWorkflows: [WorkflowDetail] {
        guard status == "executed" else { return [] }
        return workflows ?? workflow.map { [$0] } ?? []
    }

    enum CodingKeys: String, CodingKey {
        case status, message, error, workflow, workflows, changes, assumptions
        case sessionId = "session_id"
        case errorCode = "error_code"
        case previewWorkflow = "preview_workflow"
        case undoAvailable = "undo_available"
    }
}

private struct WorkflowInputResponse: Decodable {
    let session: WorkflowInputSession
}

private struct WorkflowInputRequest: Encodable {
    let text: String
    let inputType = "text"
    let selectedWorkflowId: String?
    let timezone: String
    let optimisticSave = true

    enum CodingKeys: String, CodingKey {
        case text, timezone
        case inputType = "input_type"
        case selectedWorkflowId = "selected_workflow_id"
        case optimisticSave = "optimistic_save"
    }
}

protocol WorkflowAIAuthoringServing: Sendable {
    func submit(_ text: String, selectedWorkflowId: String?, timezone: String,
                scope: WorkflowRequestScope) async throws -> WorkflowInputSession
    func get(_ sessionId: String, scope: WorkflowRequestScope) async throws -> WorkflowInputSession
    func undo(_ sessionId: String, scope: WorkflowRequestScope) async throws -> WorkflowInputSession
}

actor WorkflowAIAuthoringService: WorkflowAIAuthoringServing {
    private let client: APIClient

    init(client: APIClient = .shared) { self.client = client }

    func submit(_ text: String, selectedWorkflowId: String?, timezone: String,
                scope: WorkflowRequestScope) async throws -> WorkflowInputSession {
        let request = WorkflowInputRequest(text: text, selectedWorkflowId: selectedWorkflowId, timezone: timezone)
        let response: WorkflowInputResponse = try await client.request(
            .post, path: "/v1/workflows/input", serverProfile: scope.serverProfile, body: request,
            expectedAccountID: scope.accountId, expectedScope: scope.offlineScope,
            expectedTeamContext: scope.teamContext
        )
        return response.session
    }

    func get(_ sessionId: String, scope: WorkflowRequestScope) async throws -> WorkflowInputSession {
        let encoded = sessionId.addingPercentEncoding(withAllowedCharacters: .urlPathAllowed) ?? sessionId
        let response: WorkflowInputResponse = try await client.request(
            .get, path: "/v1/workflows/input/\(encoded)", serverProfile: scope.serverProfile,
            expectedAccountID: scope.accountId, expectedScope: scope.offlineScope,
            expectedTeamContext: scope.teamContext
        )
        return response.session
    }

    func undo(_ sessionId: String, scope: WorkflowRequestScope) async throws -> WorkflowInputSession {
        let encoded = sessionId.addingPercentEncoding(withAllowedCharacters: .urlPathAllowed) ?? sessionId
        let response: WorkflowInputResponse = try await client.request(
            .post, path: "/v1/workflows/input/\(encoded)/undo", serverProfile: scope.serverProfile,
            body: [:] as [String: String], expectedAccountID: scope.accountId,
            expectedScope: scope.offlineScope, expectedTeamContext: scope.teamContext
        )
        return response.session
    }

    func finish(_ initial: WorkflowInputSession, scope: WorkflowRequestScope,
                onProgress: @Sendable (WorkflowInputSession) async -> Void) async throws -> WorkflowInputSession {
        var session = initial
        var checks = 0
        while session.status == "queued" || session.status == "saving" {
            try Task.checkCancellation()
            await onProgress(session)
            try await Task.sleep(for: .milliseconds(checks < 2 ? 500 : 1_500))
            checks += 1
            session = try await get(session.sessionId, scope: scope)
        }
        await onProgress(session)
        return session
    }
}
