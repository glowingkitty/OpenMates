// Executes a one-shot widget request through the app's existing authenticated Workflow API.
import Foundation

@MainActor
final class WorkflowWidgetRunService {
    static let shared = WorkflowWidgetRunService()
    private let environment: WorkflowAPISendEnvironment
    private let detail: @MainActor (String, WorkflowAPIOperationScope) async throws -> WorkflowDetail
    private let dispatch: @MainActor (String, WorkflowRunRequest, WorkflowAPIOperationScope, String) async throws -> WorkflowRunDetail
    private let issuedVersion: (WidgetWorkflowRunRoute) -> String?
    private let markDispatched: (WidgetWorkflowRunRoute) throws -> Void
    private let consume: (WidgetWorkflowRunRoute) -> Void
    private var inFlight: Set<UUID> = []

    init(environment: WorkflowAPISendEnvironment = .live,
         issuedVersion: @escaping (WidgetWorkflowRunRoute) -> String? = { WidgetWorkflowsStorage.shared.issuedVersion($0) },
         markDispatched: @escaping (WidgetWorkflowRunRoute) throws -> Void = { try WidgetWorkflowsStorage.shared.markDispatched($0) },
         consume: @escaping (WidgetWorkflowRunRoute) -> Void = { WidgetWorkflowsStorage.shared.consume($0) },
         detail: @escaping @MainActor (String, WorkflowAPIOperationScope) async throws -> WorkflowDetail = { try await WorkflowAPI().getWorkflow($0, scope: $1) },
         dispatch: @escaping @MainActor (String, WorkflowRunRequest, WorkflowAPIOperationScope, String) async throws -> WorkflowRunDetail = { try await WorkflowAPI().runWorkflow($0, request: $1, scope: $2, idempotencyKey: $3) }) {
        self.environment = environment; self.issuedVersion = issuedVersion; self.markDispatched = markDispatched; self.consume = consume; self.detail = detail; self.dispatch = dispatch
    }

    @discardableResult
    func run(_ route: WidgetWorkflowRunRoute, accountID: String) async throws -> WorkflowRunDetail {
        let scope = WorkflowAPIOperationScope(accountID: accountID, profile: environment.currentProfile(),
            offlineScope: environment.currentOfflineScope(), teamContext: environment.currentTeamContext())
        try await scope.check(environment: environment)
        guard route.belongsTo(accountID: accountID, apiBaseURL: scope.profile.apiBaseURL, teamID: scope.teamContext.teamID),
              let versionID = issuedVersion(route), !inFlight.contains(route.requestID) else { throw CancellationError() }
        inFlight.insert(route.requestID)
        defer { inFlight.remove(route.requestID) }
        let workflow = try await detail(route.workflowID, scope)
        try await scope.check(environment: environment)
        guard workflow.id == route.workflowID, workflow.currentVersionId == versionID, WidgetWorkflowsProjection.isScheduled(workflow) else { throw CancellationError() }
        // Published backend readiness validation remains authoritative, including
        // disabled schedules, required input, unsupported actions and revoked access.
        guard issuedVersion(route) == versionID else { throw CancellationError() }
        try markDispatched(route)
        let run: WorkflowRunDetail
        do {
            run = try await dispatch(route.workflowID, WorkflowRunRequest(mode: "manual", input: [:]), scope, "widget-" + route.requestID.uuidString)
        } catch {
            // Only published pre-acceptance errors retire a dispatched ticket.
            // Conflicts, server failures, malformed responses and transport
            // uncertainty keep the original idempotency identity for retry.
            if Self.isDefiniteNonAcceptance(error) { consume(route) }
            throw error
        }
        consume(route)
        try await scope.check(environment: environment)
        return run
    }
    static func isDefiniteNonAcceptance(_ error: Error) -> Bool {
        guard case let APIError.httpError(status, message) = error else { return false }
        switch (status, message) {
        case (400, "MISSING_WORKFLOW_INPUT"), (403, "TEAM_PERMISSION_DENIED"),
             (403, "FEATURE_DISABLED"), (404, "Workflow not found"):
            return true
        default:
            return false
        }
    }

}

enum WidgetWorkflowsProjection {
    static func isScheduled(_ workflow: WorkflowDetail) -> Bool {
        workflow.graph.nodes.first(where: { $0.id == workflow.graph.triggerNodeId })?.type == .scheduleTrigger
    }
    static func summary(_ workflow: WorkflowDetail) -> WidgetWorkflowSummary? {
        guard isScheduled(workflow), WidgetWorkflowsLinks.safeID(workflow.id) else { return nil }
        return .init(id: workflow.id, title: workflow.title, versionID: workflow.currentVersionId)
    }
}
