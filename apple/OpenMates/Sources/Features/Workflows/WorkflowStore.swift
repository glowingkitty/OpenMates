// Owner-scoped native Workflow workspace state.
// Web source: frontend/packages/ui/src/stores/workflowWorkspaceStore.ts
// Specification: specifications/features/workflows/specification.yml
// Assertions: workflows.mvp.list, workflows.mvp.editor, workflows.mvp.run-history,
//             workflows.privacy.owner-scope

import Foundation
import SwiftUI

@MainActor
final class WorkflowStore: ObservableObject {
    @Published private(set) var workflows: [WorkflowSummary] = []
    @Published private(set) var selectedWorkflow: WorkflowDetail?
    @Published private(set) var runs: [WorkflowRunSummary] = []
    @Published private(set) var selectedRunDetail: WorkflowRunDetail?
    @Published private(set) var pinnedRunGraph: WorkflowGraph?
    @Published private(set) var versions: [WorkflowVersionSummary] = []
    @Published private(set) var skills: [WorkflowSkillChoice] = []
    @Published private(set) var isLoading = false
    @Published private(set) var isLoadingRun = false
    @Published private(set) var errorMessage: String?
    @Published private(set) var previewAskAIVerdict: WorkflowAskAIVerdict?

    let authoring = WorkflowAIAuthoringController()

    private let api: WorkflowAPI
    private let createWorkflowRequest: (@MainActor (WorkflowCreateRequest, WorkflowAPIOperationScope) async throws -> WorkflowDetail)?
    private let detailRequest: (@MainActor (String, WorkflowAPIOperationScope) async throws -> WorkflowDetail)?
    private let runsRequest: (@MainActor (String, WorkflowAPIOperationScope) async throws -> [WorkflowRunSummary])?
    private(set) var accountId: String?
    private var generation = 0
    private var selectionGeneration = 0
    private var selectedWorkflowId: String?
    private var selectedRunId: String?

    init(api: WorkflowAPI = WorkflowAPI(),
         createWorkflowRequest: (@MainActor (WorkflowCreateRequest, WorkflowAPIOperationScope) async throws -> WorkflowDetail)? = nil,
         detailRequest: (@MainActor (String, WorkflowAPIOperationScope) async throws -> WorkflowDetail)? = nil,
         runsRequest: (@MainActor (String, WorkflowAPIOperationScope) async throws -> [WorkflowRunSummary])? = nil) {
        self.api = api
        self.createWorkflowRequest = createWorkflowRequest
        self.detailRequest = detailRequest
        self.runsRequest = runsRequest
    }

    func reset(accountId newAccountId: String?) {
        generation += 1
        selectionGeneration += 1
        accountId = newAccountId
        selectedWorkflowId = nil
        selectedRunId = nil
        workflows = []
        selectedWorkflow = nil
        runs = []
        selectedRunDetail = nil
        pinnedRunGraph = nil
        versions = []
        skills = []
        isLoading = false
        isLoadingRun = false
        errorMessage = nil
        previewAskAIVerdict = nil
        authoring.reset(accountId: newAccountId)
    }

    // Workflows are account-global, while in-flight authoring and run requests
    // belong to the Team context in which the user started them.
    func invalidateTransientContext() {
        generation &+= 1
        selectionGeneration &+= 1
        isLoading = false
        isLoadingRun = false
        errorMessage = nil
        previewAskAIVerdict = nil
        authoring.reset(accountId: accountId)
    }

    private func isCurrent(_ requestGeneration: Int, account: String) -> Bool {
        generation == requestGeneration && accountId == account
    }

    private func operationScope(for owner: String) -> WorkflowAPIOperationScope {
        WorkflowAPIOperationScope.capture(accountID: owner)
    }

    private func isCurrent(_ requestGeneration: Int, account: String,
                           scope: WorkflowAPIOperationScope) -> Bool {
        isCurrent(requestGeneration, account: account) &&
            ServerProfile.current() == scope.profile &&
            OfflineStore.shared.scopeGeneration == scope.offlineScope &&
            TeamWorkspaceContext.shared.contextEpoch == scope.teamContext.epoch &&
            TeamWorkspaceContext.shared.teamID == scope.teamContext.teamID
    }

    func load(accountId owner: String) async {
        if accountId != owner { reset(accountId: owner) }
        let requestGeneration = generation
        let scope = operationScope(for: owner)
        isLoading = true
        errorMessage = nil
        do {
            let loaded = try await api.listWorkflows(scope: scope)
            guard isCurrent(requestGeneration, account: owner, scope: scope) else { return }
            workflows = loaded
            if let selectedWorkflowId, !loaded.contains(where: { $0.id == selectedWorkflowId }) {
                clearSelection()
            }
        } catch {
            guard isCurrent(requestGeneration, account: owner, scope: scope) else { return }
            errorMessage = error.localizedDescription
            NativeDiagnostics.warning("request_failed", category: "workflow_load_failed")
        }
        if isCurrent(requestGeneration, account: owner, scope: scope) { isLoading = false }
    }

    // Compatibility for a workspace created before MainAppView supplies the owner.
    func load() async {
        guard let accountId else { return }
        await load(accountId: accountId)
    }

    func clearSelection() {
        selectionGeneration += 1
        selectedWorkflowId = nil
        selectedRunId = nil
        selectedWorkflow = nil
        runs = []
        selectedRunDetail = nil
        pinnedRunGraph = nil
        versions = []
        isLoadingRun = false
    }

    func select(_ summary: WorkflowSummary) async { await select(id: summary.id) }

    func select(id workflowId: String) async {
        guard let owner = accountId else { return }
        selectionGeneration += 1
        let selection = selectionGeneration
        let requestGeneration = generation
        let scope = operationScope(for: owner)
        selectedWorkflowId = workflowId
        selectedRunId = nil
        selectedWorkflow = nil
        runs = []
        selectedRunDetail = nil
        pinnedRunGraph = nil
        isLoading = true
        errorMessage = nil
        // Run history is ancillary: a failed or slow history request must not
        // suppress a successfully loaded template (web selectWorkflow parity).
        async let history: Void = loadSelectionRuns(workflowId, requestGeneration: requestGeneration,
                                                    selection: selection, owner: owner, scope: scope)
        do {
            let loadedDetail: WorkflowDetail
            if let detailRequest { loadedDetail = try await detailRequest(workflowId, scope) }
            else { loadedDetail = try await api.getWorkflow(workflowId, scope: scope) }
            guard isCurrent(requestGeneration, account: owner, scope: scope),
                  selection == selectionGeneration, selectedWorkflowId == workflowId else { return }
            selectedWorkflow = loadedDetail
        } catch {
            guard isCurrent(requestGeneration, account: owner, scope: scope), selection == selectionGeneration else { return }
            errorMessage = error.localizedDescription
            NativeDiagnostics.warning("request_failed", category: "workflow_select_failed")
        }
        if isCurrent(requestGeneration, account: owner, scope: scope), selection == selectionGeneration { isLoading = false }
        await history
    }

    private func loadSelectionRuns(_ workflowId: String, requestGeneration: Int, selection: Int,
                                   owner: String, scope: WorkflowAPIOperationScope) async {
        do {
            let loadedRuns: [WorkflowRunSummary]
            if let runsRequest { loadedRuns = try await runsRequest(workflowId, scope) }
            else { loadedRuns = try await api.listRuns(workflowId: workflowId, scope: scope) }
            guard isCurrent(requestGeneration, account: owner, scope: scope),
                  selection == selectionGeneration, selectedWorkflowId == workflowId else { return }
            runs = loadedRuns
        } catch {
            guard isCurrent(requestGeneration, account: owner, scope: scope),
                  selection == selectionGeneration, selectedWorkflowId == workflowId else { return }
            NativeDiagnostics.warning("request_failed", category: "workflow_runs_failed")
        }
    }

    func loadCapabilities() async {
        guard let owner = accountId else { return }
        let requestGeneration = generation
        let scope = operationScope(for: owner)
        do {
            let loaded = try await api.capabilities(scope: scope)
            guard isCurrent(requestGeneration, account: owner, scope: scope) else { return }
            skills = loaded.filter { $0.type == "app_skill" && $0.enabled }.map { capability in
                let metadata = capability.metadata.mapValues(\.value)
                return WorkflowSkillChoice(
                    id: capability.id,
                    appId: metadata["app_id"] as? String ?? capability.id.components(separatedBy: ".").first ?? "",
                    skillId: metadata["skill_id"] as? String ?? capability.id.components(separatedBy: ".").last ?? "",
                    title: capability.title,
                    inputSchema: (metadata["input_schema"] as? [String: Any] ?? [:]).mapValues(AnyCodable.init),
                    outputSchema: (metadata["output_schema"] as? [String: Any] ?? [:]).mapValues(AnyCodable.init),
                    fixedCreditCost: (metadata["cost"] as? [String: Any])?["fixed"] as? Int
                        ?? metadata["fixed_credit_cost"] as? Int,
                    testAllowed: (metadata["workflow"] as? [String: Any])?["test_allowed"] as? Bool ?? true
                )
            }
        } catch {
            guard isCurrent(requestGeneration, account: owner, scope: scope) else { return }
            NativeDiagnostics.warning("request_failed", category: "workflow_capabilities_failed")
        }
    }

    func createDraft(title: String) async {
        let graph = WorkflowGraph(version: 1, triggerNodeId: "", nodes: [], edges: [], variables: [:], limits: [:], uiLayout: [:])
        await createWorkflow(title: title, graph: graph)
    }

    func createStarter(_ kind: WorkflowStarterKind) async {
        await createWorkflow(title: kind.title, graph: kind.graph(timezone: TimeZone.current.identifier))
    }

    private func createWorkflow(title: String, graph: WorkflowGraph) async {
        guard let owner = accountId, !isLoading else { return }
        let requestGeneration = generation
        let scope = operationScope(for: owner)
        isLoading = true
        do {
            let request = WorkflowCreateRequest(title: title, description: nil, graph: graph,
                                                enabled: false, runContentRetention: .last5)
            let workflow: WorkflowDetail
            if let createWorkflowRequest {
                workflow = try await createWorkflowRequest(request, scope)
            } else {
                workflow = try await api.createWorkflow(request, scope: scope)
            }
            guard isCurrent(requestGeneration, account: owner, scope: scope) else { return }
            upsert(workflow)
            selectedWorkflowId = workflow.id
            selectedWorkflow = workflow
            runs = []
        } catch {
            guard isCurrent(requestGeneration, account: owner, scope: scope) else { return }
            errorMessage = error.localizedDescription
            NativeDiagnostics.warning("request_failed", category: "workflow_create_failed")
        }
        if isCurrent(requestGeneration, account: owner, scope: scope) { isLoading = false }
    }

    @discardableResult
    func submitInstruction(_ text: String, selectedWorkflowId targetId: String? = nil) async -> Bool {
        guard let owner = accountId else { return false }
        let requestGeneration = generation
        let scope = operationScope(for: owner)
        let session = await authoring.submit(
            text, selectedWorkflowId: targetId, timezone: TimeZone.current.identifier
        )
        guard isCurrent(requestGeneration, account: owner, scope: scope), let session else { return false }
        let committed = session.status == "draft"
            ? session.workflow.map { [$0] } ?? []
            : session.committedWorkflows
        guard !committed.isEmpty else { return false }
        for workflow in committed { upsert(workflow) }
        if let targetId, let updated = committed.first(where: { $0.id == targetId }),
           selectedWorkflowId == targetId {
            selectedWorkflow = updated
            await loadVersions()
        } else if session.status == "draft", let first = committed.first {
            await select(id: first.id)
        }
        return isCurrent(requestGeneration, account: owner, scope: scope)
    }

    func undoInstruction() async {
        guard let owner = accountId else { return }
        let requestGeneration = generation
        let scope = operationScope(for: owner)
        guard let session = await authoring.undo(), session.status == "executed",
              isCurrent(requestGeneration, account: owner, scope: scope) else { return }
        await load(accountId: owner)
        if let selectedWorkflowId, workflows.contains(where: { $0.id == selectedWorkflowId }) {
            await select(id: selectedWorkflowId)
        } else {
            clearSelection()
        }
    }

    @discardableResult
    func save(title: String, description: String?, graph: WorkflowGraph) async -> Bool {
        guard let owner = accountId, let workflow = selectedWorkflow else { return false }
        let requestGeneration = generation
        let scope = operationScope(for: owner)
        isLoading = true
        do {
            let updated = try await api.updateWorkflow(workflow.id, request: WorkflowUpdateRequest(
                title: title, description: description, graph: graph, enabled: nil, runContentRetention: nil
            ), scope: scope)
            guard isCurrent(requestGeneration, account: owner, scope: scope), selectedWorkflowId == workflow.id else { return false }
            upsert(updated)
            selectedWorkflow = updated
            isLoading = false
            return true
        } catch {
            guard isCurrent(requestGeneration, account: owner, scope: scope) else { return false }
            errorMessage = error.localizedDescription
            isLoading = false
            NativeDiagnostics.warning("request_failed", category: "workflow_save_failed")
            return false
        }
    }

    @discardableResult
    func setEnabled(_ enabled: Bool) async -> Bool {
        guard let owner = accountId, let workflow = selectedWorkflow else { return false }
        let requestGeneration = generation
        let scope = operationScope(for: owner)
        isLoading = true
        do {
            let updated = enabled ? try await api.enableWorkflow(workflow.id, scope: scope) : try await api.disableWorkflow(workflow.id, scope: scope)
            guard isCurrent(requestGeneration, account: owner, scope: scope), selectedWorkflowId == workflow.id else { return false }
            upsert(updated)
            selectedWorkflow = updated
            isLoading = false
            return true
        } catch {
            guard isCurrent(requestGeneration, account: owner, scope: scope) else { return false }
            errorMessage = error.localizedDescription
            isLoading = false
            NativeDiagnostics.warning("request_failed", category: "workflow_toggle_failed")
            return false
        }
    }

    func deleteSelected() async {
        guard let owner = accountId, let workflow = selectedWorkflow else { return }
        let requestGeneration = generation
        let scope = operationScope(for: owner)
        do {
            try await api.deleteWorkflow(workflow.id, scope: scope)
            guard isCurrent(requestGeneration, account: owner, scope: scope), selectedWorkflowId == workflow.id else { return }
            workflows.removeAll { $0.id == workflow.id }
            clearSelection()
        } catch {
            guard isCurrent(requestGeneration, account: owner, scope: scope) else { return }
            errorMessage = error.localizedDescription
        }
    }

    func loadVersions() async {
        guard let owner = accountId, let workflowId = selectedWorkflowId else { return }
        let requestGeneration = generation
        let scope = operationScope(for: owner)
        do {
            let history = try await api.versions(workflowId: workflowId, scope: scope)
            guard isCurrent(requestGeneration, account: owner, scope: scope), selectedWorkflowId == workflowId else { return }
            versions = history.versions
        } catch {
            guard isCurrent(requestGeneration, account: owner, scope: scope) else { return }
            errorMessage = error.localizedDescription
        }
    }

    func restoreVersion(_ versionId: String) async {
        guard let owner = accountId, let workflowId = selectedWorkflowId else { return }
        let requestGeneration = generation
        let scope = operationScope(for: owner)
        do {
            let restored = try await api.restoreVersion(workflowId: workflowId, versionId: versionId, scope: scope)
            guard isCurrent(requestGeneration, account: owner, scope: scope), selectedWorkflowId == workflowId else { return }
            upsert(restored)
            selectedWorkflow = restored
            await loadVersions()
        } catch {
            guard isCurrent(requestGeneration, account: owner, scope: scope) else { return }
            errorMessage = error.localizedDescription
        }
    }

    func runSelected() async {
        guard let owner = accountId, let workflowId = selectedWorkflowId else { return }
        let requestGeneration = generation
        let scope = operationScope(for: owner)
        do {
            let run = try await api.runWorkflow(workflowId, request: WorkflowRunRequest(mode: "test", input: [:]), scope: scope)
            guard isCurrent(requestGeneration, account: owner, scope: scope), selectedWorkflowId == workflowId else { return }
            runs.insert(WorkflowRunSummary(detail: run), at: 0)
            selectedRunId = run.id
            selectedRunDetail = run
            pinnedRunGraph = run.versionId == selectedWorkflow?.currentVersionId ? selectedWorkflow?.graph : nil
        } catch {
            guard isCurrent(requestGeneration, account: owner, scope: scope) else { return }
            errorMessage = error.localizedDescription
            NativeDiagnostics.warning("request_failed", category: "workflow_run_failed")
        }
    }

    func refreshRuns() async {
        guard let owner = accountId, let workflowId = selectedWorkflowId else { return }
        let requestGeneration = generation
        let scope = operationScope(for: owner)
        do {
            let loaded = try await api.listRuns(workflowId: workflowId, scope: scope)
            guard isCurrent(requestGeneration, account: owner, scope: scope), selectedWorkflowId == workflowId else { return }
            runs = loaded
        } catch {
            guard isCurrent(requestGeneration, account: owner, scope: scope) else { return }
            NativeDiagnostics.warning("request_failed", category: "workflow_runs_failed")
        }
    }

    func selectRun(_ runId: String?) async {
        selectedRunId = runId
        selectedRunDetail = nil
        pinnedRunGraph = nil
        isLoadingRun = false
        guard let owner = accountId, let workflowId = selectedWorkflowId, let runId else { return }
        let requestGeneration = generation
        let scope = operationScope(for: owner)
        isLoadingRun = true
        do {
            let detail = try await api.runDetail(workflowId: workflowId, runId: runId, scope: scope)
            guard isCurrent(requestGeneration, account: owner, scope: scope), selectedWorkflowId == workflowId,
                  selectedRunId == runId else { return }
            selectedRunDetail = detail
            if detail.versionId == selectedWorkflow?.currentVersionId {
                pinnedRunGraph = selectedWorkflow?.graph
            } else {
                let version = try await api.version(workflowId: workflowId, versionId: detail.versionId, scope: scope)
                guard isCurrent(requestGeneration, account: owner, scope: scope), selectedWorkflowId == workflowId,
                      selectedRunId == runId else { return }
                pinnedRunGraph = version.graph
            }
        } catch {
            guard isCurrent(requestGeneration, account: owner, scope: scope), selectedRunId == runId else { return }
            errorMessage = error.localizedDescription
        }
        if isCurrent(requestGeneration, account: owner, scope: scope), selectedRunId == runId { isLoadingRun = false }
    }

    func cancelRun(_ runId: String) async {
        guard let owner = accountId, let workflowId = selectedWorkflowId else { return }
        let requestGeneration = generation
        let scope = operationScope(for: owner)
        do {
            _ = try await api.cancelRun(workflowId: workflowId, runId: runId, scope: scope)
            guard isCurrent(requestGeneration, account: owner, scope: scope), selectedWorkflowId == workflowId else { return }
            await refreshRuns()
            await selectRun(runId)
        } catch {
            guard isCurrent(requestGeneration, account: owner, scope: scope) else { return }
            errorMessage = error.localizedDescription
        }
    }

    func deleteRun(_ runId: String) async {
        guard let owner = accountId, let workflowId = selectedWorkflowId else { return }
        let requestGeneration = generation
        let scope = operationScope(for: owner)
        do {
            let status = try await api.deleteRun(workflowId: workflowId, runId: runId, scope: scope)
            guard isCurrent(requestGeneration, account: owner, scope: scope), selectedWorkflowId == workflowId else { return }
            if status == "deleted" {
                runs.removeAll { $0.id == runId }
                if selectedRunId == runId { selectedRunId = nil; selectedRunDetail = nil; pinnedRunGraph = nil }
            }
        } catch {
            guard isCurrent(requestGeneration, account: owner, scope: scope) else { return }
            errorMessage = error.localizedDescription
        }
    }

    func showFixture(_ kind: String) {
        reset(accountId: "workflow-preview")
        let now = Int(Date().timeIntervalSince1970)
        // Match deployed WorkflowGraphRenderer.preview.ts capability fixtures so
        // screenshots exercise the production schema/date controls.
        skills = [WorkflowSkillChoice(
            id: "weather.forecast", appId: "weather", skillId: "forecast", title: "Forecast",
            inputSchema: [
                "type": AnyCodable("object"),
                "x-ui": AnyCodable(["control": "date-range", "start_field": "start_date", "end_field": "end_date", "min": "today", "max_offset_days": 13, "default": "today"] as [String: Any]),
                "properties": AnyCodable([
                    "location": ["type": "string"],
                    "latitude": ["type": "number"], "longitude": ["type": "number"],
                    "start_date": ["type": "string", "format": "date"],
                    "end_date": ["type": "string", "format": "date"],
                    "timezone": ["type": "string"],
                    "units": ["type": "string", "enum": ["metric"], "default": "metric"]
                ] as [String: Any]), "required": AnyCodable(["location"])
            ],
            outputSchema: ["properties": AnyCodable([
                "rain_probability": ["type": "number", "example": 60],
                "rain_expected": ["type": "boolean", "example": true],
                "rain_periods": ["type": "array", "example": [["start": "09:00", "end": "11:00"]]],
                "forecast_day": ["type": "object"]
            ] as [String: Any])], fixedCreditCost: 10
        )]
        skills.append(WorkflowSkillChoice(
            id: "news.search", appId: "news", skillId: "search", title: "Search",
            inputSchema: ["type": AnyCodable("object"), "properties": AnyCodable([
                "requests": ["type": "array", "items": ["type": "object", "properties": ["query": ["type": "string"], "count": ["type": "integer", "minimum": 1, "maximum": 20]], "required": ["query"]]]
            ] as [String: Any])],
            outputSchema: ["properties": AnyCodable(["results": ["type": "array", "example": [["title": "Example article", "url": "https://example.com/article"]]]] as [String: Any])]
        ))
        skills.append(WorkflowSkillChoice(
            id: "ai.ask", appId: "ai", skillId: "ask", title: "Ask",
            inputSchema: ["type": AnyCodable("object"), "properties": AnyCodable(["prompt": ["type": "string"]]), "required": AnyCodable(["prompt"])],
            outputSchema: ["properties": AnyCodable(["answer": ["type": "string", "title": "Answer", "example": "A concise summary"]])]
        ))
        let regularNodes = [
            WorkflowNode(id: "trigger", type: .scheduleTrigger, title: nil,
                         config: ["schedule": AnyCodable(["type": "daily", "time": "09:00", "timezone": "Europe/Berlin"])],
                         inputMapping: [:], ui: [:]),
            WorkflowNode(id: "weather", type: .appSkillAction, title: "Get forecast",
                         config: ["app_id": AnyCodable("weather"), "skill_id": AnyCodable("forecast"),
                                  "input": AnyCodable(["location": "Berlin"])], inputMapping: [:], ui: [:]),
            WorkflowNode(id: "rain", type: .check, title: "Rain expected today",
                         config: ["predicate": AnyCodable(["left": "$nodes.weather.output.rain_probability",
                                                           "op": "gt", "right": 0] as [String: Any])],
                         inputMapping: [:], ui: [:]),
            WorkflowNode(id: "news", type: .appSkillAction, title: "Search news",
                         config: ["app_id": AnyCodable("news"), "skill_id": AnyCodable("search"),
                                  "input": AnyCodable(["requests": [["query": "Germany news", "count": 6]]])],
                         inputMapping: [:], ui: [:]),
            WorkflowNode(id: "message", type: .sendChatMessage, title: "Send morning report",
                         config: ["title": AnyCodable("Morning weather and news"),
                                  "message": AnyCodable("Your morning update\n{{steps.weather.rain_periods}}\n{{steps.news.results}}")],
                         inputMapping: [:], ui: [:])
        ]
        var nodes: [WorkflowNode] = kind == "ask-ai-blocked" ? [
            regularNodes[0],
            WorkflowNode(id: "ask-ai", type: .appSkillAction, title: "Ask AI",
                         config: ["app_id": AnyCodable("ai"), "skill_id": AnyCodable("ask"),
                                  "input": AnyCodable(["prompt": "Search for new AI events"] )],
                         inputMapping: [:], ui: [:])
        ] : regularNodes
        if kind == "editor-all-nodes" {
            nodes.insert(WorkflowNode(id: "ask-ai", type: .appSkillAction, title: "Ask AI",
                config: ["app_id": AnyCodable("ai"), "skill_id": AnyCodable("ask"), "input": AnyCodable(["prompt": "Summarize {{steps.news.results}}", "model": "auto"])], inputMapping: [:], ui: [:]), at: nodes.count - 1)
        }
        previewAskAIVerdict = kind == "ask-ai-blocked" ? .asksToInvokeAppSkill : kind == "editor-all-nodes" ? .allowed : nil
        let edges = zip(nodes, nodes.dropFirst()).map { WorkflowEdge(from: $0.0.id, to: $0.1.id, branch: nil) }
        let graph = WorkflowGraph(version: 2, triggerNodeId: "trigger", nodes: nodes,
                                  edges: edges, variables: [:], limits: [:], uiLayout: [:])
        var detail = WorkflowDetail(
            id: "workflow-fixture", title: "Weekly AI events",
            description: "Find useful AI events every week.",
            status: kind == "home" ? "draft" : "active", enabled: kind != "home",
            lifecycle: .persisted, source: "manual", sourceChatId: nil,
            createdByAssistant: false, autoDeleteAt: nil, keptAt: nil,
            triggerSummary: "Every day, 09:00",
            nextRunAt: kind == "home" || kind == "no-runs" ? nil : now + 86_400,
            lastRunStatus: nil, runContentRetention: .last5,
            currentVersionId: "fixture-version", createdAt: now - 3_600, updatedAt: now, graph: graph
        )
        detail.category = "technology"
        detail.icon = "calendar-days"
        workflows = [summary(from: detail)]
        if kind != "home" { selectedWorkflowId = detail.id; selectedWorkflow = detail }
        if kind == "runs" {
            let payload = Data(#"{"id":"run-fixture","workflow_id":"workflow-fixture","version_id":"fixture-version","trigger_type":"schedule","status":"completed","started_at":1696075200,"finished_at":1696075260,"content_available":true,"node_runs":[{"id":"node-run-fixture","run_id":"run-fixture","workflow_id":"workflow-fixture","node_id":"trigger","node_type":"schedule_trigger","status":"completed"}]}"#.utf8)
            if let run = try? JSONDecoder().decode(WorkflowRunDetail.self, from: payload) {
                runs = [WorkflowRunSummary(detail: run)]
                selectedRunId = run.id
                selectedRunDetail = run
                pinnedRunGraph = graph
            }
        }
    }

    private func upsert(_ workflow: WorkflowDetail) {
        let value = summary(from: workflow)
        if let index = workflows.firstIndex(where: { $0.id == value.id }) { workflows[index] = value }
        else { workflows.insert(value, at: 0) }
    }

    private func summary(from workflow: WorkflowDetail) -> WorkflowSummary {
        var value = WorkflowSummary(
            id: workflow.id, title: workflow.title, description: workflow.description,
            status: workflow.status, enabled: workflow.enabled, lifecycle: workflow.lifecycle,
            source: workflow.source, sourceChatId: workflow.sourceChatId,
            createdByAssistant: workflow.createdByAssistant, autoDeleteAt: workflow.autoDeleteAt,
            keptAt: workflow.keptAt, triggerSummary: workflow.triggerSummary,
            nextRunAt: workflow.nextRunAt, lastRunStatus: workflow.lastRunStatus,
            runContentRetention: workflow.runContentRetention, currentVersionId: workflow.currentVersionId,
            createdAt: workflow.createdAt, updatedAt: workflow.updatedAt
        )
        value.category = workflow.category
        value.icon = workflow.icon
        value.version = workflow.version
        return value
    }
}

// Mirrors the disabled starter graphs in workflowExamples.ts. Each card creates
// the complete graph the web editor opens, so its schedule, query, and recipient
// still need the owner's review before activation.
enum WorkflowStarterKind: CaseIterable {
    case rainAlert, newsBrief, hourlyApartments

    @MainActor var title: String {
        switch self {
        case .rainAlert: AppStrings.workflowStarterRainTitle
        case .newsBrief: AppStrings.workflowStarterNewsTitle
        case .hourlyApartments: AppStrings.workflowStarterApartmentsTitle
        }
    }

    func graph(timezone: String) -> WorkflowGraph {
        let schedule: [String: Any]
        let actions: [WorkflowNode]
        switch self {
        case .rainAlert:
            schedule = ["timezone": timezone, "type": "daily", "time": "09:00"]
            actions = [
                Self.skill("weather", app: "weather", title: "Get forecast", input: [
                    "location": "Berlin",
                    "start_date": ["$date": "today", "format": "date"],
                    "end_date": ["$date": "today", "format": "date"]
                ]),
                Self.node("rain", type: .check, title: "Rain expected today", config: [
                    "predicate": ["left": "$nodes.weather.output.rain_probability", "op": "gt", "right": 0]
                ]),
                Self.skill("news", app: "news", title: "Search news", input: [
                    "requests": [["query": "Germany news", "freshness": "pd", "count": 6]]
                ]),
                Self.node("message", type: .sendChatMessage, title: "Send morning report", config: [
                    "title": "Morning weather and news",
                    "message": "Your morning update\n{{steps.weather.rain_periods}}\n{{steps.news.results}}",
                    "blocks": [
                        ["id": "weather", "source": "$nodes.weather.output.rain_periods",
                         "include_if": "$nodes.rain.output.matched"],
                        ["id": "news", "source": "$nodes.news.output.results", "only_new_results": true]
                    ]
                ])
            ]
        case .newsBrief:
            schedule = ["timezone": timezone, "type": "weekly", "weekdays": ["sunday"], "time": "09:00"]
            actions = [
                Self.skill("events", app: "events", title: "Search events", input: [
                    "requests": [["query": "AI", "providers": ["Luma", "Eventbrite"],
                                  "location": "Berlin",
                                  "start_date": ["$date": "next_week_start", "format": "datetime"],
                                  "end_date": ["$date": "next_week_end", "format": "datetime"],
                                  "count": 10] as [String: Any]]
                ]),
                Self.node("message", type: .sendChatMessage, title: "Send AI events", config: [
                    "title": "AI events for the upcoming week",
                    "message": "Here are the upcoming events: {{steps.events.results}}"
                ])
            ]
        case .hourlyApartments:
            schedule = ["timezone": timezone, "type": "hourly", "minute": 0]
            actions = [
                Self.skill("apartments", app: "home", title: "Search home", input: [
                    "requests": [["query": "Berlin", "listing_type": "rent",
                                  "property_type": "apartment", "max_price_eur": 1200,
                                  "sort": "newest", "providers": ["Kleinanzeigen"],
                                  "max_results": 10] as [String: Any]]
                ]),
                Self.node("message", type: .sendChatMessage, title: "Send new apartments", config: [
                    "title": "New apartments",
                    "message": "Here are the new apartments: {{steps.apartments.results}}"
                ])
            ]
        }
        let nodes = [Self.node("trigger", type: .scheduleTrigger, title: nil,
                               config: ["schedule": schedule])] + actions
        let edges = zip(nodes, nodes.dropFirst()).map {
            WorkflowEdge(from: $0.0.id, to: $0.1.id, branch: nil)
        }
        return WorkflowGraph(version: 2, triggerNodeId: "trigger", nodes: nodes,
                             edges: edges, variables: [:], limits: [:], uiLayout: [:])
    }

    private static func node(_ id: String, type: WorkflowNodeType, title: String?,
                             config: [String: Any]) -> WorkflowNode {
        WorkflowNode(id: id, type: type, title: title, config: config.mapValues(AnyCodable.init),
                     inputMapping: [:], ui: [:])
    }

    private static func skill(_ id: String, app: String, title: String,
                              input: [String: Any]) -> WorkflowNode {
        node(id, type: .appSkillAction, title: title, config: [
            "app_id": app, "skill_id": app == "weather" ? "forecast" : "search", "input": input
        ])
    }
}
