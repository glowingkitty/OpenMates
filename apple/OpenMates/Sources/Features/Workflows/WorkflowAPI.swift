// Workflow API namespace for the native app.
// Wraps the shared APIClient paths used by web, CLI, npm SDK, and pip SDK.
// Request builders are separated from network execution so unit tests can verify
// parity without live sessions, private cookies, API keys, or backend state.
// Spec: docs/specs/workflows-v1/spec.yml

import Foundation

struct WorkflowCreateRequest: Encodable, Sendable {
    let title: String
    let graph: WorkflowGraph
    let enabled: Bool
    let runContentRetention: WorkflowRunContentRetention

    enum CodingKeys: String, CodingKey {
        case title
        case graph
        case enabled
        case runContentRetention = "run_content_retention"
    }
}

struct WorkflowUpdateRequest: Encodable, Sendable {
    let title: String?
    let graph: WorkflowGraph?
    let enabled: Bool?
    let runContentRetention: WorkflowRunContentRetention?

    enum CodingKeys: String, CodingKey {
        case title
        case graph
        case enabled
        case runContentRetention = "run_content_retention"
    }
}

struct WorkflowRunRequest: Encodable, Sendable {
    let mode: String
    let input: [String: AnyCodable]
}

enum WorkflowAPIRequestFactory {
    static let basePath = "/v1/workflows"

    static func listPath() -> String { basePath }

    static func capabilitiesPath() -> String { "\(basePath)/capabilities" }

    static func workflowPath(_ workflowId: String) -> String {
        "\(basePath)/\(workflowId.addingPercentEncoding(withAllowedCharacters: .urlPathAllowed) ?? workflowId)"
    }

    static func enablePath(_ workflowId: String) -> String { "\(workflowPath(workflowId))/enable" }

    static func disablePath(_ workflowId: String) -> String { "\(workflowPath(workflowId))/disable" }

    static func runPath(_ workflowId: String) -> String { "\(workflowPath(workflowId))/run" }

    static func runsPath(_ workflowId: String) -> String { "\(workflowPath(workflowId))/runs" }

    static func runDetailPath(workflowId: String, runId: String) -> String {
        let encodedRunId = runId.addingPercentEncoding(withAllowedCharacters: .urlPathAllowed) ?? runId
        return "\(runsPath(workflowId))/\(encodedRunId)"
    }
}

actor WorkflowAPI {
    private let apiClient: APIClient

    init(apiClient: APIClient = .shared) {
        self.apiClient = apiClient
    }

    func listWorkflows() async throws -> [WorkflowSummary] {
        let response: WorkflowListResponse = try await apiClient.request(.get, path: WorkflowAPIRequestFactory.listPath())
        return response.workflows
    }

    func getWorkflow(_ workflowId: String) async throws -> WorkflowDetail {
        let response: WorkflowResponse = try await apiClient.request(.get, path: WorkflowAPIRequestFactory.workflowPath(workflowId))
        return response.workflow
    }

    func createWorkflow(_ request: WorkflowCreateRequest) async throws -> WorkflowDetail {
        let response: WorkflowResponse = try await apiClient.request(.post, path: WorkflowAPIRequestFactory.listPath(), body: request)
        return response.workflow
    }

    func updateWorkflow(_ workflowId: String, request: WorkflowUpdateRequest) async throws -> WorkflowDetail {
        let response: WorkflowResponse = try await apiClient.request(.patch, path: WorkflowAPIRequestFactory.workflowPath(workflowId), body: request)
        return response.workflow
    }

    func enableWorkflow(_ workflowId: String) async throws -> WorkflowDetail {
        let response: WorkflowResponse = try await apiClient.request(.post, path: WorkflowAPIRequestFactory.enablePath(workflowId))
        return response.workflow
    }

    func disableWorkflow(_ workflowId: String) async throws -> WorkflowDetail {
        let response: WorkflowResponse = try await apiClient.request(.post, path: WorkflowAPIRequestFactory.disablePath(workflowId))
        return response.workflow
    }

    func runWorkflow(_ workflowId: String, request: WorkflowRunRequest) async throws -> WorkflowRunDetail {
        let response: WorkflowRunResponse = try await apiClient.request(.post, path: WorkflowAPIRequestFactory.runPath(workflowId), body: request)
        return response.run
    }

    func listRuns(workflowId: String) async throws -> [WorkflowRunDetail] {
        let response: WorkflowRunsResponse = try await apiClient.request(.get, path: WorkflowAPIRequestFactory.runsPath(workflowId))
        return response.runs
    }

    func runDetail(workflowId: String, runId: String) async throws -> WorkflowRunDetail {
        let response: WorkflowRunResponse = try await apiClient.request(.get, path: WorkflowAPIRequestFactory.runDetailPath(workflowId: workflowId, runId: runId))
        return response.run
    }
}
