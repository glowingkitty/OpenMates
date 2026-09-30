// Owner-scoped unsaved step tests and message previews. Only preceding tested
// values are sent to a step; no full run context or chat history is forwarded.
// Web source: WorkflowGraphRenderer.svelte and workflowOutputExamples.ts

import Foundation

struct WorkflowStepTestRequest: Encodable {
    let node: WorkflowNode
    let input: [String: AnyCodable]
    let upstreamOutputs: [String: [String: AnyCodable]]

    enum CodingKeys: String, CodingKey {
        case node, input
        case upstreamOutputs = "upstream_outputs"
    }
}

private struct WorkflowStepPreviewResponse: Decodable {
    let preview: [String: AnyCodable]
}

actor WorkflowStepTestService {
    private let client: APIClient

    init(client: APIClient = .shared) { self.client = client }

    func test(workflowId: String, node: WorkflowNode,
              upstreamOutputs: [String: [String: AnyCodable]],
              scope: WorkflowRequestScope) async throws -> WorkflowRunDetail {
        let request = WorkflowStepTestRequest(node: node, input: [:], upstreamOutputs: upstreamOutputs)
        let response: WorkflowRunResponse = try await client.request(
            .post, path: stepPath(workflowId: workflowId, nodeId: node.id, action: "test"),
            serverProfile: scope.serverProfile, body: request,
            expectedAccountID: scope.accountId, expectedScope: scope.offlineScope, expectedTeamContext: scope.teamContext
        )
        return response.run
    }

    func previewMessage(workflowId: String, node: WorkflowNode,
                        upstreamOutputs: [String: [String: AnyCodable]],
                        scope: WorkflowRequestScope) async throws -> [String: AnyCodable] {
        let request = WorkflowStepTestRequest(node: node, input: [:], upstreamOutputs: upstreamOutputs)
        let response: WorkflowStepPreviewResponse = try await client.request(
            .post, path: stepPath(workflowId: workflowId, nodeId: node.id, action: "preview"),
            serverProfile: scope.serverProfile, body: request,
            expectedAccountID: scope.accountId, expectedScope: scope.offlineScope, expectedTeamContext: scope.teamContext
        )
        return response.preview
    }

    func run(workflowId: String, runId: String, scope: WorkflowRequestScope) async throws -> WorkflowRunDetail {
        let path = WorkflowAPIRequestFactory.runDetailPath(workflowId: workflowId, runId: runId)
        let response: WorkflowRunResponse = try await client.request(
            .get, path: path, serverProfile: scope.serverProfile,
            expectedAccountID: scope.accountId, expectedScope: scope.offlineScope, expectedTeamContext: scope.teamContext
        )
        return response.run
    }

    func cancel(workflowId: String, runId: String, scope: WorkflowRequestScope) async throws {
        let _: WorkflowRunStatusResponse = try await client.request(
            .post, path: WorkflowAPIRequestFactory.cancelRunPath(workflowId: workflowId, runId: runId),
            serverProfile: scope.serverProfile, body: [:] as [String: String],
            expectedAccountID: scope.accountId, expectedScope: scope.offlineScope, expectedTeamContext: scope.teamContext
        )
    }

    private func stepPath(workflowId: String, nodeId: String, action: String) -> String {
        let workflow = workflowId.addingPercentEncoding(withAllowedCharacters: .urlPathAllowed) ?? workflowId
        let node = nodeId.addingPercentEncoding(withAllowedCharacters: .urlPathAllowed) ?? nodeId
        return "/v1/workflows/\(workflow)/steps/\(node)/\(action)"
    }
}

enum WorkflowUpstreamOutputs {
    static func scoped(graph: WorkflowGraph, nodeId: String,
                       available: [String: [String: AnyCodable]],
                       insertionAfter: String? = nil) -> [String: [String: AnyCodable]] {
        var ancestors = Set<String>()
        func visit(_ current: String) {
            for edge in graph.edges where edge.to == current && ancestors.insert(edge.from).inserted {
                visit(edge.from)
            }
        }
        if graph.nodes.contains(where: { $0.id == nodeId }) {
            visit(nodeId)
        } else if let insertionAfter {
            ancestors.insert(insertionAfter)
            visit(insertionAfter)
        }
        return available.filter { ancestors.contains($0.key) }
    }
}
