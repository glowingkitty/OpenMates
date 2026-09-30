// UI state for ephemeral step tests and message previews. Test results remain
// in memory and are discarded on account, server, or editor scope changes.

import SwiftUI

extension AppStrings {
    static var workflowTestPending: String { localized("workflows.builder.test_pending") }
    static var workflowOutputTestFailed: String { localized("workflows.builder.output_test_failed") }
    static var workflowOutputPreviewFailed: String { localized("workflows.builder.output_preview_failed") }
}

@MainActor
final class WorkflowStepTestController: ObservableObject {
    enum Status: Equatable { case idle, processing, completed, failed, cancelled, pending }

    @Published private(set) var status: Status = .idle
    @Published private(set) var activeNodeId: String?
    @Published private(set) var outputsByNode: [String: [String: AnyCodable]] = [:]
    @Published private(set) var previewByNode: [String: [String: AnyCodable]] = [:]
    @Published private(set) var errorMessage: String?

    private let service: WorkflowStepTestService
    private var accountId: String?
    private var generation = 0
    private var activeRunId: String?
    private var activeWorkflowId: String?
    private var activeScope: WorkflowRequestScope?

    var canStop: Bool { activeRunId != nil }

    init(service: WorkflowStepTestService = WorkflowStepTestService()) { self.service = service }

    func reset(accountId: String?) {
        generation &+= 1
        self.accountId = accountId
        status = .idle
        activeNodeId = nil
        outputsByNode = [:]
        previewByNode = [:]
        errorMessage = nil
        activeRunId = nil
        activeWorkflowId = nil
        activeScope = nil
    }

    func test(workflowId: String, node: WorkflowNode, graph: WorkflowGraph,
              insertionAfter: String? = nil) async {
        guard let accountId, status != .processing else { return }
        generation &+= 1
        let stamp = generation
        status = .processing
        activeNodeId = node.id
        errorMessage = nil
        do {
            let scope = try await WorkflowRequestScope.capture(accountId: accountId)
            guard generation == stamp else { return }
            activeScope = scope
            let upstream = WorkflowUpstreamOutputs.scoped(
                graph: graph, nodeId: node.id, available: outputsByNode,
                insertionAfter: insertionAfter
            )
            var run = try await service.test(
                workflowId: workflowId, node: node, upstreamOutputs: upstream, scope: scope
            )
            guard generation == stamp else { return }
            if isPending(run.status) {
                activeRunId = run.id
                activeWorkflowId = workflowId
                for attempt in 0..<60 {
                    try Task.checkCancellation()
                    try await Task.sleep(for: .milliseconds(min(1_500 + attempt * 500, 5_000)))
                    run = try await service.run(workflowId: workflowId, runId: run.id, scope: scope)
                    guard generation == stamp else { return }
                    if !isPending(run.status) { break }
                }
            }
            guard generation == stamp else { return }
            activeRunId = nil
            activeWorkflowId = nil
            activeScope = nil
            if isPending(run.status) {
                status = .pending
                errorMessage = AppStrings.workflowTestPending
            } else if run.status == "completed" {
                let result = run.nodeRuns.first { $0.nodeId == node.id }
                outputsByNode[node.id] = result?.outputSummary ?? run.outputSummary
                status = .completed
            } else {
                status = run.status == "cancelled" ? .cancelled : .failed
                errorMessage = AppStrings.workflowOutputTestFailed
            }
        } catch {
            guard generation == stamp else { return }
            status = .failed
            errorMessage = error.localizedDescription
        }
    }

    func preview(workflowId: String, node: WorkflowNode, graph: WorkflowGraph) async {
        guard let accountId else { return }
        generation &+= 1
        let stamp = generation
        status = .processing
        activeNodeId = node.id
        errorMessage = nil
        do {
            let scope = try await WorkflowRequestScope.capture(accountId: accountId)
            let upstream = WorkflowUpstreamOutputs.scoped(
                graph: graph, nodeId: node.id, available: outputsByNode
            )
            let result = try await service.previewMessage(
                workflowId: workflowId, node: node, upstreamOutputs: upstream, scope: scope
            )
            guard generation == stamp else { return }
            previewByNode[node.id] = result
            status = .completed
        } catch {
            guard generation == stamp else { return }
            status = .failed
            errorMessage = AppStrings.workflowOutputPreviewFailed
        }
    }

    func cancel() async {
        guard let activeRunId, let activeWorkflowId, let activeScope else { return }
        try? await service.cancel(workflowId: activeWorkflowId, runId: activeRunId, scope: activeScope)
    }

    private func isPending(_ value: String) -> Bool {
        ["accepted", "queued", "running", "cancellation_requested"].contains(value)
    }
}
