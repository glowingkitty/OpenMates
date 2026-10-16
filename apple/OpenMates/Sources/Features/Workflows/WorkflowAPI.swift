// Specification: specifications/features/apple-offline-workspaces/specification.yml
// Assertions: apple-workspaces.offline-complete, apple-workspaces.local-first, apple-workspaces.isolation, apple-workspaces.maintenance
// Workflow API namespace for the native app.
// Wraps the shared APIClient paths used by web, CLI, npm SDK, and pip SDK.
// Request builders are separated from network execution so unit tests can verify
// parity without live sessions, private cookies, API keys, or backend state.
// Spec: docs/specs/workflows-v1/spec.yml

import Foundation

struct WorkflowCreateRequest: Encodable, Sendable {
    let title: String
    let description: String?
    let graph: WorkflowGraph
    let enabled: Bool
    let runContentRetention: WorkflowRunContentRetention

    enum CodingKeys: String, CodingKey {
        case title
        case description
        case graph
        case enabled
        case runContentRetention = "run_content_retention"
    }
}

struct WorkflowUpdateRequest: Encodable, Sendable {
    let title: String?
    let description: String?
    let graph: WorkflowGraph?
    let enabled: Bool?
    let runContentRetention: WorkflowRunContentRetention?

    enum CodingKeys: String, CodingKey {
        case title
        case description
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

    static func listPath(teamID: String? = nil) -> String { scoped(basePath, teamID: teamID) }

    static func scoped(_ path: String, teamID: String?) -> String {
        guard let teamID else { return path }
        let escaped = teamID.addingPercentEncoding(withAllowedCharacters:
            CharacterSet(charactersIn: "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-._~")) ?? ""
        return "\(path)?team_id=\(escaped)"
    }

    static func capabilitiesPath() -> String { "\(basePath)/capabilities" }

    static func workflowPath(_ workflowId: String, teamID: String? = nil) -> String {
        scoped("\(basePath)/\(workflowId.addingPercentEncoding(withAllowedCharacters: .urlPathAllowed) ?? workflowId)", teamID: teamID)
    }

    static func enablePath(_ workflowId: String) -> String { "\(workflowPath(workflowId))/enable" }

    static func disablePath(_ workflowId: String) -> String { "\(workflowPath(workflowId))/disable" }

    static func runPath(_ workflowId: String) -> String { "\(workflowPath(workflowId))/run" }

    static func runsPath(_ workflowId: String) -> String { "\(workflowPath(workflowId))/runs" }

    static func versionsPath(_ workflowId: String) -> String { "\(workflowPath(workflowId))/versions" }

    static func versionPath(workflowId: String, versionId: String) -> String {
        let encoded = versionId.addingPercentEncoding(withAllowedCharacters: .urlPathAllowed) ?? versionId
        return "\(versionsPath(workflowId))/\(encoded)"
    }

    static func restoreVersionPath(workflowId: String, versionId: String) -> String {
        "\(versionPath(workflowId: workflowId, versionId: versionId))/restore"
    }

    static func runDetailPath(workflowId: String, runId: String) -> String {
        let encodedRunId = runId.addingPercentEncoding(withAllowedCharacters: .urlPathAllowed) ?? runId
        return "\(runsPath(workflowId))/\(encodedRunId)"
    }


    static func cancelRunPath(workflowId: String, runId: String) -> String {
        "\(runDetailPath(workflowId: workflowId, runId: runId))/cancel"
    }
}

@MainActor
struct WorkflowAPISendEnvironment {
    var currentAccountID: () async -> String?
    var currentProfile: () -> ServerProfile
    var currentOfflineScope: () -> UUID
    var currentTeamContext: () -> APIRequestTeamContext

    static let live = Self(
        currentAccountID: { await AuthManager.currentUserId() },
        currentProfile: { ServerProfile.current() },
        currentOfflineScope: { OfflineStore.shared.scopeGeneration },
        currentTeamContext: {
            APIRequestTeamContext(epoch: TeamWorkspaceContext.shared.contextEpoch,
                                  teamID: TeamWorkspaceContext.shared.teamID)
        }
    )
}

struct WorkflowAPIOperationScope: Sendable {
    let accountID: String
    let profile: ServerProfile
    let offlineScope: UUID
    let teamContext: APIRequestTeamContext

    @MainActor
    static func capture(accountID: String) -> Self {
        Self(accountID: accountID, profile: ServerProfile.current(),
             offlineScope: OfflineStore.shared.scopeGeneration,
             teamContext: APIRequestTeamContext(epoch: TeamWorkspaceContext.shared.contextEpoch,
                                                teamID: TeamWorkspaceContext.shared.teamID))
    }

    @MainActor
    func check(environment: WorkflowAPISendEnvironment = .live) async throws {
        func matchesContext() -> Bool {
            let team = environment.currentTeamContext()
            return environment.currentProfile() == profile &&
                environment.currentOfflineScope() == offlineScope &&
                team.epoch == teamContext.epoch && team.teamID == teamContext.teamID
        }
        guard matchesContext(), await environment.currentAccountID() == accountID,
              matchesContext() else { throw CancellationError() }
    }
}

actor WorkflowAPI {
    private let apiClient: APIClient

    init(apiClient: APIClient = .shared) {
        self.apiClient = apiClient
    }

    private func request<T: Decodable & Sendable>(
        _ method: HTTPMethod, path: String, scope: WorkflowAPIOperationScope,
        body: (any Encodable & Sendable)? = nil, headers: [String: String]? = nil
    ) async throws -> T {
        try await scope.check()
        let data: Data = try await apiClient.request(
            method, path: path, serverProfile: scope.profile, body: body, headers: headers,
            expectedAccountID: scope.accountID, expectedScope: scope.offlineScope,
            expectedTeamContext: scope.teamContext
        )
        try await scope.check()
        return try Self.decodeResponse(T.self, from: data)
    }

    // Workflow models have explicit snake_case CodingKeys, including graph/node
    // fields. The shared client's camel-case conversion would drop those keys.
    nonisolated static func decodeResponse<T: Decodable>(_ type: T.Type, from data: Data) throws -> T {
        try JSONDecoder().decode(type, from: data)
    }

    private func offlineScope(_ scope: WorkflowAPIOperationScope) async throws -> NativeWorkspaceOfflineScope {
        try await scope.check()
        return try await NativeWorkspaceOfflineRuntime.configure(accountID: scope.accountID,
            teamID: scope.teamContext.teamID)
    }

    func cachedWorkflows(scope: WorkflowAPIOperationScope) async throws -> [WorkflowSummary]? {
        let cachedScope = try await offlineScope(scope)
        guard let data = try await NativeWorkspaceOfflineRuntime.cached(namespace: "workflows",
            path: WorkflowAPIRequestFactory.listPath(teamID: scope.teamContext.teamID), scope: cachedScope) else { return nil }
        return try Self.decodeResponse(WorkflowListResponse.self, from: data).workflows
    }

    func cachedWorkflow(_ id: String, scope: WorkflowAPIOperationScope) async throws -> WorkflowDetail? {
        let cachedScope = try await offlineScope(scope)
        guard let data = try await NativeWorkspaceOfflineRuntime.cached(namespace: "workflows",
            path: WorkflowAPIRequestFactory.workflowPath(id, teamID: scope.teamContext.teamID), scope: cachedScope) else { return nil }
        return try Self.decodeResponse(WorkflowResponse.self, from: data).workflow
    }

    func listWorkflows(scope: WorkflowAPIOperationScope) async throws -> [WorkflowSummary] {
        let cachedScope = try await offlineScope(scope)
        let path = WorkflowAPIRequestFactory.listPath(teamID: scope.teamContext.teamID)
        let data = try await NativeWorkspaceOfflineRuntime.request(namespace: "workflows",
            path: path, scope: cachedScope, api: apiClient, retain: false)
        let decoded = try Self.decodeResponse(WorkflowListResponse.self, from: data)
        try await NativeWorkspaceOfflineCache.shared.retain(namespace: "workflows", path: path, data: data, scope: cachedScope)
        return decoded.workflows
    }

    func maintainOffline(scope: NativeWorkspaceOfflineScope) async throws {
        let cache = NativeWorkspaceOfflineCache.shared
        let revision = try await cache.beginRefresh(namespace: "workflows", scope: scope)
        let listPath = WorkflowAPIRequestFactory.listPath(teamID: scope.teamID)
        let list = try await NativeWorkspaceOfflineRuntime.request(namespace: "workflows", path: listPath,
            scope: scope, api: apiClient, retain: false)
        let summaries = try Self.decodeResponse(WorkflowListResponse.self, from: list).workflows
        var responses = [listPath: list]
        for summary in summaries {
            try Task.checkCancellation()
            let path = WorkflowAPIRequestFactory.workflowPath(summary.id, teamID: scope.teamID)
            let data = try await NativeWorkspaceOfflineRuntime.request(namespace: "workflows", path: path,
                scope: scope, api: apiClient, retain: false)
            let detail = try Self.decodeResponse(WorkflowResponse.self, from: data).workflow
            guard detail.id == summary.id, detail.currentVersionId == summary.currentVersionId else {
                throw UserTasksError.invalidResponse
            }
            responses[path] = data
        }
        try await NativeWorkspaceOfflineRuntime.check(scope)
        try await cache.commit(namespace: "workflows", responses: responses, scope: scope, revision: revision)
        await WorkflowsWidgetBridge.refresh()
    }

    func capabilities(scope: WorkflowAPIOperationScope) async throws -> [WorkflowCapability] {
        let response: WorkflowCapabilitiesResponse = try await request(.get, path: WorkflowAPIRequestFactory.capabilitiesPath(), scope: scope)
        return response.capabilities
    }

    func getWorkflow(_ workflowId: String, scope: WorkflowAPIOperationScope) async throws -> WorkflowDetail {
        let cachedScope = try await offlineScope(scope)
        let path = WorkflowAPIRequestFactory.workflowPath(workflowId, teamID: scope.teamContext.teamID)
        let data = try await NativeWorkspaceOfflineRuntime.request(namespace: "workflows",
            path: path, scope: cachedScope, api: apiClient, retain: false)
        let decoded = try Self.decodeResponse(WorkflowResponse.self, from: data)
        guard decoded.workflow.id == workflowId else { throw UserTasksError.invalidResponse }
        try await NativeWorkspaceOfflineCache.shared.retain(namespace: "workflows", path: path, data: data, scope: cachedScope)
        return decoded.workflow
    }

    func createWorkflow(_ body: WorkflowCreateRequest, scope: WorkflowAPIOperationScope) async throws -> WorkflowDetail {
        let response: WorkflowResponse = try await request(.post, path: WorkflowAPIRequestFactory.listPath(), scope: scope, body: body)
        return response.workflow
    }

    func updateWorkflow(_ workflowId: String, request body: WorkflowUpdateRequest,
                        scope: WorkflowAPIOperationScope) async throws -> WorkflowDetail {
        let response: WorkflowResponse = try await request(.patch, path: WorkflowAPIRequestFactory.workflowPath(workflowId), scope: scope, body: body)
        return response.workflow
    }

    func deleteWorkflow(_ workflowId: String, scope: WorkflowAPIOperationScope) async throws {
        let _: WorkflowDeleteResponse = try await request(.delete, path: WorkflowAPIRequestFactory.workflowPath(workflowId), scope: scope)
    }

    func versions(workflowId: String, scope: WorkflowAPIOperationScope) async throws -> WorkflowVersionHistory {
        try await request(.get, path: WorkflowAPIRequestFactory.versionsPath(workflowId), scope: scope)
    }

    func version(workflowId: String, versionId: String,
                 scope: WorkflowAPIOperationScope) async throws -> WorkflowVersionDetail {
        let response: WorkflowVersionResponse = try await request(.get, path: WorkflowAPIRequestFactory.versionPath(workflowId: workflowId, versionId: versionId), scope: scope)
        return response.version
    }

    func restoreVersion(workflowId: String, versionId: String,
                        scope: WorkflowAPIOperationScope) async throws -> WorkflowDetail {
        let response: WorkflowResponse = try await request(.post, path: WorkflowAPIRequestFactory.restoreVersionPath(workflowId: workflowId, versionId: versionId), scope: scope, body: [:] as [String: String])
        return response.workflow
    }

    func enableWorkflow(_ workflowId: String, scope: WorkflowAPIOperationScope) async throws -> WorkflowDetail {
        let response: WorkflowResponse = try await request(.post, path: WorkflowAPIRequestFactory.enablePath(workflowId), scope: scope)
        return response.workflow
    }

    func disableWorkflow(_ workflowId: String, scope: WorkflowAPIOperationScope) async throws -> WorkflowDetail {
        let response: WorkflowResponse = try await request(.post, path: WorkflowAPIRequestFactory.disablePath(workflowId), scope: scope)
        return response.workflow
    }

    func runWorkflow(_ workflowId: String, request body: WorkflowRunRequest,
                     scope: WorkflowAPIOperationScope, idempotencyKey: String? = nil) async throws -> WorkflowRunDetail {
        let response: WorkflowRunResponse = try await request(
            .post, path: WorkflowAPIRequestFactory.runPath(workflowId), scope: scope, body: body,
            headers: ["Idempotency-Key": idempotencyKey ?? "\(workflowId)-\(UUID().uuidString)"]
        )
        return response.run
    }

    func listRuns(workflowId: String, scope: WorkflowAPIOperationScope) async throws -> [WorkflowRunSummary] {
        let response: WorkflowRunsResponse = try await request(.get, path: WorkflowAPIRequestFactory.runsPath(workflowId), scope: scope)
        return response.runs
    }

    func runDetail(workflowId: String, runId: String,
                   scope: WorkflowAPIOperationScope) async throws -> WorkflowRunDetail {
        let response: WorkflowRunResponse = try await request(.get, path: WorkflowAPIRequestFactory.runDetailPath(workflowId: workflowId, runId: runId), scope: scope)
        return response.run
    }

    func cancelRun(workflowId: String, runId: String,
                   scope: WorkflowAPIOperationScope) async throws -> String {
        let response: WorkflowRunStatusResponse = try await request(
            .post, path: WorkflowAPIRequestFactory.cancelRunPath(workflowId: workflowId, runId: runId),
            scope: scope, body: [:] as [String: String]
        )
        return response.status
    }

    func deleteRun(workflowId: String, runId: String,
                   scope: WorkflowAPIOperationScope) async throws -> String {
        let response: WorkflowRunStatusResponse = try await request(
            .delete, path: WorkflowAPIRequestFactory.runDetailPath(workflowId: workflowId, runId: runId), scope: scope
        )
        return response.status
    }
}
