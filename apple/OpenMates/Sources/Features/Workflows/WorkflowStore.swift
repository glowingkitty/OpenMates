// WorkflowStore.swift
//
// Owns native workflow list, selected detail, editable draft, and run history.
// It keeps workflow data outside the chat sync store because workflow payloads
// are server-owned and independently encrypted.
//
// Spec: docs/specs/workflows-v1/spec.yml
//
// ─── Web source ─────────────────────────────────────────────────────
// Svelte: frontend/packages/ui/src/stores/workflowWorkspaceStore.ts
// CSS:    frontend/apps/web_app/src/routes/workflows/+page.svelte
// Tokens: ColorTokens.generated.swift, SpacingTokens.generated.swift
// ────────────────────────────────────────────────────────────────────

import Foundation
import SwiftUI

@MainActor
final class WorkflowStore: ObservableObject {
    @Published private(set) var workflows: [WorkflowSummary] = []
    @Published private(set) var selectedWorkflow: WorkflowDetail?
    @Published private(set) var runs: [WorkflowRunDetail] = []
    @Published private(set) var isLoading = false

    private let api: WorkflowAPI

    init(api: WorkflowAPI = WorkflowAPI()) {
        self.api = api
    }

    func load() async {
        isLoading = true
        defer { isLoading = false }
        do {
            workflows = try await api.listWorkflows()
        } catch {
            NativeDiagnostics.warning("request_failed", category: "workflow_load_failed")
        }
    }

    func select(_ summary: WorkflowSummary) async {
        isLoading = true
        defer { isLoading = false }
        do {
            selectedWorkflow = try await api.getWorkflow(summary.id)
            runs = (try? await api.listRuns(workflowId: summary.id)) ?? []
        } catch {
            NativeDiagnostics.warning("request_failed", category: "workflow_select_failed")
        }
    }

    func createDraft(title: String) async {
        let graph = WorkflowGraph(
            version: 1,
            triggerNodeId: "manual",
            nodes: [WorkflowNode(id: "manual", type: .manualTrigger, title: nil, config: [:], inputMapping: [:], ui: [:])],
            edges: [],
            variables: [:],
            limits: [:],
            uiLayout: [:]
        )
        isLoading = true
        defer { isLoading = false }
        do {
            let workflow = try await api.createWorkflow(
                WorkflowCreateRequest(title: title, description: nil, graph: graph, enabled: false, runContentRetention: .last5)
            )
            upsert(workflow)
            selectedWorkflow = workflow
            runs = []
        } catch {
            NativeDiagnostics.warning("request_failed", category: "workflow_create_failed")
        }
    }

    func save(title: String, description: String?, graph: WorkflowGraph) async {
        guard let workflow = selectedWorkflow else { return }
        isLoading = true
        defer { isLoading = false }
        do {
            let updated = try await api.updateWorkflow(
                workflow.id,
                request: WorkflowUpdateRequest(title: title, description: description, graph: graph, enabled: nil, runContentRetention: nil)
            )
            upsert(updated)
            selectedWorkflow = updated
        } catch {
            NativeDiagnostics.warning("request_failed", category: "workflow_save_failed")
        }
    }

    func setEnabled(_ enabled: Bool) async {
        guard let workflow = selectedWorkflow else { return }
        isLoading = true
        defer { isLoading = false }
        do {
            let updated = enabled
                ? try await api.enableWorkflow(workflow.id)
                : try await api.disableWorkflow(workflow.id)
            upsert(updated)
            selectedWorkflow = updated
        } catch {
            NativeDiagnostics.warning("request_failed", category: "workflow_toggle_failed")
        }
    }

    func runSelected() async {
        guard let workflow = selectedWorkflow else { return }
        isLoading = true
        defer { isLoading = false }
        do {
            let run = try await api.runWorkflow(workflow.id, request: WorkflowRunRequest(mode: "manual", input: [:]))
            runs.insert(run, at: 0)
        } catch {
            NativeDiagnostics.warning("request_failed", category: "workflow_run_failed")
        }
    }

    func showFixture(_ kind: String) {
        let graph = WorkflowGraph(
            version: 1,
            triggerNodeId: "manual",
            nodes: [WorkflowNode(id: "manual", type: .manualTrigger, title: AppStrings.workflows, config: [:], inputMapping: [:], ui: [:])],
            edges: [],
            variables: [:],
            limits: [:],
            uiLayout: [:]
        )
        let detail = WorkflowDetail(
            id: "workflow-fixture",
            title: AppStrings.workflows,
            description: nil,
            status: kind == "home" ? AppStrings.disabled : AppStrings.enabled,
            enabled: kind != "home",
            lifecycle: .persisted,
            source: "manual",
            sourceChatId: nil,
            createdByAssistant: false,
            autoDeleteAt: nil,
            keptAt: nil,
            triggerSummary: nil,
            nextRunAt: nil,
            lastRunStatus: nil,
            runContentRetention: .last5,
            currentVersionId: "fixture-version",
            createdAt: 0,
            updatedAt: 0,
            graph: graph
        )
        workflows = [WorkflowSummary(
            id: detail.id,
            title: detail.title,
            description: detail.description,
            status: detail.status,
            enabled: detail.enabled,
            lifecycle: detail.lifecycle,
            source: detail.source,
            sourceChatId: detail.sourceChatId,
            createdByAssistant: detail.createdByAssistant,
            autoDeleteAt: detail.autoDeleteAt,
            keptAt: detail.keptAt,
            triggerSummary: detail.triggerSummary,
            nextRunAt: detail.nextRunAt,
            lastRunStatus: detail.lastRunStatus,
            runContentRetention: detail.runContentRetention,
            currentVersionId: detail.currentVersionId,
            createdAt: detail.createdAt,
            updatedAt: detail.updatedAt
        )]
        selectedWorkflow = kind == "home" ? nil : detail
    }

    private func upsert(_ workflow: WorkflowDetail) {
        let summary = WorkflowSummary(
            id: workflow.id,
            title: workflow.title,
            description: workflow.description,
            status: workflow.status,
            enabled: workflow.enabled,
            lifecycle: workflow.lifecycle,
            source: workflow.source,
            sourceChatId: workflow.sourceChatId,
            createdByAssistant: workflow.createdByAssistant,
            autoDeleteAt: workflow.autoDeleteAt,
            keptAt: workflow.keptAt,
            triggerSummary: workflow.triggerSummary,
            nextRunAt: workflow.nextRunAt,
            lastRunStatus: workflow.lastRunStatus,
            runContentRetention: workflow.runContentRetention,
            currentVersionId: workflow.currentVersionId,
            createdAt: workflow.createdAt,
            updatedAt: workflow.updatedAt
        )
        if let index = workflows.firstIndex(where: { $0.id == summary.id }) {
            workflows[index] = summary
        } else {
            workflows.insert(summary, at: 0)
        }
    }
}
