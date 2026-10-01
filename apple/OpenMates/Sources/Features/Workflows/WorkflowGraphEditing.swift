// Pure graph edits for native workflow authoring. Saving still goes through the
// owner-authenticated workflow API, which validates the complete definition.
// Specification: specifications/features/workflows/specification.yml
// Assertions: workflows.activation.reachable-side-effect, workflows.control.check

import Foundation

enum WorkflowGraphEditError: Error, Equatable {
    case duplicateNode
    case missingAnchor
    case dependentNodes([String])
    case multipleOutgoingEdges
    case cannotRemoveTrigger
}

enum WorkflowGraphEditing {
    static func inserting(
        _ node: WorkflowNode,
        into graph: WorkflowGraph,
        after anchorId: String?,
        branch: String? = nil
    ) throws -> WorkflowGraph {
        guard !graph.nodes.contains(where: { $0.id == node.id }) else {
            throw WorkflowGraphEditError.duplicateNode
        }
        if let anchorId, !graph.nodes.contains(where: { $0.id == anchorId }) {
            throw WorkflowGraphEditError.missingAnchor
        }

        var nodes = graph.nodes
        let index = anchorId.flatMap { anchor in nodes.firstIndex(where: { $0.id == anchor }) }
        nodes.insert(node, at: index.map { $0 + 1 } ?? 0)
        var edges = graph.edges
        let isTrigger = [.scheduleTrigger, .manualTrigger, .webhookTrigger, .eventTrigger].contains(node.type)

        if let anchorId {
            let prior = edges.firstIndex(where: { $0.from == anchorId && $0.branch == branch })
            let continuation = prior.map { edges.remove(at: $0).to }
            edges.append(WorkflowEdge(from: anchorId, to: node.id, branch: branch))
            if let continuation {
                edges.append(WorkflowEdge(from: node.id, to: continuation, branch: nil))
            }
        } else if isTrigger {
            let incoming = Set(graph.edges.map(\.to))
            for root in graph.nodes where !incoming.contains(root.id) && root.type != .end {
                edges.append(WorkflowEdge(from: node.id, to: root.id, branch: nil))
            }
        }

        return copy(graph, nodes: nodes, edges: edges,
                    triggerNodeId: anchorId == nil && isTrigger ? node.id : graph.triggerNodeId)
    }

    static func replacing(_ node: WorkflowNode, in graph: WorkflowGraph) throws -> WorkflowGraph {
        guard let index = graph.nodes.firstIndex(where: { $0.id == node.id }) else {
            throw WorkflowGraphEditError.missingAnchor
        }
        var nodes = graph.nodes
        nodes[index] = node
        return copy(graph, nodes: nodes, edges: graph.edges)
    }

    static func removing(_ nodeId: String, from graph: WorkflowGraph) throws -> WorkflowGraph {
        guard graph.nodes.contains(where: { $0.id == nodeId }) else {
            throw WorkflowGraphEditError.missingAnchor
        }
        let removedTrigger = nodeId == graph.triggerNodeId
        let dependents = graph.nodes
            .filter { $0.id != nodeId && references(nodeId, in: $0) }
            .map(\.id)
        guard dependents.isEmpty else {
            throw WorkflowGraphEditError.dependentNodes(dependents)
        }
        let outgoing = graph.edges.filter { $0.from == nodeId }
        guard outgoing.count <= 1 else {
            throw WorkflowGraphEditError.multipleOutgoingEdges
        }
        let nextId = outgoing.first?.to
        var edges = graph.edges.filter { $0.from != nodeId && $0.to != nodeId }
        if let nextId {
            for incoming in graph.edges where incoming.to == nodeId {
                edges.append(WorkflowEdge(from: incoming.from, to: nextId, branch: incoming.branch))
            }
        }
        return copy(graph, nodes: graph.nodes.filter { $0.id != nodeId }, edges: edges,
                    triggerNodeId: removedTrigger ? "" : nil)
    }

    private static func references(_ id: String, in node: WorkflowNode) -> Bool {
        guard let data = try? JSONEncoder().encode(node.config),
              let text = String(data: data, encoding: .utf8)
        else { return false }
        return text.contains("$nodes.\(id).") || text.contains("steps.\(id).")
    }

    private static func copy(
        _ graph: WorkflowGraph,
        nodes: [WorkflowNode],
        edges: [WorkflowEdge],
        triggerNodeId: String? = nil
    ) -> WorkflowGraph {
        WorkflowGraph(version: graph.version,
                      triggerNodeId: triggerNodeId ?? graph.triggerNodeId,
                      nodes: nodes, edges: edges, variables: graph.variables,
                      limits: graph.limits, uiLayout: graph.uiLayout)
    }
}
