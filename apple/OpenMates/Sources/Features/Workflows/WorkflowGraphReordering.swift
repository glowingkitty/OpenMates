// Safe native Workflow step reordering. Branch labels and earlier-result
// references retain their meaning across every accepted move.
// Web source: frontend/packages/ui/src/components/workflows/workflowReordering.ts

import Foundation

enum WorkflowGraphReordering {
    enum Direction { case up, down }

    static func canMove(_ graph: WorkflowGraph, nodeId: String, direction: Direction) -> Bool {
        adjacent(graph, nodeId: nodeId, direction: direction) != nil
    }

    static func move(_ graph: WorkflowGraph, nodeId: String, direction: Direction) -> WorkflowGraph? {
        guard let (upper, lower, edgeIndex) = adjacent(graph, nodeId: nodeId, direction: direction) else {
            return nil
        }
        let beforeIndex = graph.edges.firstIndex { $0.to == upper.id }
        let afterIndex = graph.edges.firstIndex { $0.from == lower.id }
        var nodes = graph.nodes.filter { $0.id != lower.id }
        guard let insertion = nodes.firstIndex(where: { $0.id == upper.id }) else { return nil }
        nodes.insert(lower, at: insertion)

        var edges = graph.edges.enumerated().compactMap { index, edge -> WorkflowEdge? in
            if index == beforeIndex || index == edgeIndex || edge.from == upper.id || edge.from == lower.id {
                return nil
            }
            return edge
        }
        if let beforeIndex {
            let before = graph.edges[beforeIndex]
            edges.append(WorkflowEdge(from: before.from, to: lower.id, branch: before.branch))
        }
        edges.append(WorkflowEdge(from: lower.id, to: upper.id, branch: nil))
        if let afterIndex {
            let after = graph.edges[afterIndex]
            edges.append(WorkflowEdge(from: upper.id, to: after.to, branch: after.branch))
        }
        return copy(graph, nodes: nodes, edges: edges)
    }

    static func moveTo(_ graph: WorkflowGraph, sourceId: String, targetId: String) -> WorkflowGraph? {
        guard sourceId != targetId else { return nil }
        for direction in [Direction.up, .down] {
            var current = graph
            var seen = Set<String>()
            while seen.insert(edgeSignature(current)).inserted {
                let neighbor = direction == .up
                    ? current.edges.first(where: { $0.to == sourceId })?.from
                    : current.edges.first(where: { $0.from == sourceId && $0.branch == nil })?.to
                guard let neighbor, let next = move(current, nodeId: sourceId, direction: direction) else {
                    break
                }
                current = next
                if neighbor == targetId { return current }
            }
        }
        return nil
    }

    static func moveAfter(_ graph: WorkflowGraph, sourceId: String, afterId: String) -> WorkflowGraph? {
        guard sourceId != afterId else { return nil }
        let next = graph.edges.first { $0.from == afterId && $0.branch == nil }?.to
        guard next != sourceId else { return nil }
        var cursor = sourceId
        var visited = Set<String>()
        while visited.insert(cursor).inserted {
            if cursor == afterId { return moveTo(graph, sourceId: sourceId, targetId: afterId) }
            guard let edge = graph.edges.first(where: { $0.from == cursor && $0.branch == nil }) else { break }
            cursor = edge.to
        }
        return next.flatMap { moveTo(graph, sourceId: sourceId, targetId: $0) }
    }

    private static func adjacent(_ graph: WorkflowGraph, nodeId: String,
                                 direction: Direction) -> (WorkflowNode, WorkflowNode, Int)? {
        guard let edgeIndex = graph.edges.firstIndex(where: { edge in
            direction == .up ? edge.to == nodeId : edge.from == nodeId && edge.branch == nil
        }) else { return nil }
        let edge = graph.edges[edgeIndex]
        guard let upper = graph.nodes.first(where: { $0.id == edge.from }),
              let lower = graph.nodes.first(where: { $0.id == edge.to }) else { return nil }
        let fixed: Set<WorkflowNodeType> = [
            .scheduleTrigger, .manualTrigger, .webhookTrigger, .eventTrigger, .check, .decision, .end
        ]
        guard !fixed.contains(upper.type), !fixed.contains(lower.type),
              graph.triggerNodeId != upper.id, graph.triggerNodeId != lower.id else { return nil }
        let upperIncoming = graph.edges.filter { $0.to == upper.id }
        let lowerIncoming = graph.edges.filter { $0.to == lower.id }
        let upperOutgoing = graph.edges.filter { $0.from == upper.id }
        let lowerOutgoing = graph.edges.filter { $0.from == lower.id }
        guard upperIncoming.count <= 1, lowerIncoming.count == 1,
              upperOutgoing.count == 1, lowerOutgoing.count <= 1,
              upperOutgoing[0].to == edge.to, upperOutgoing[0].from == edge.from,
              edge.branch == nil, lowerOutgoing.allSatisfy({ $0.branch == nil }),
              !references(upper.id, in: lower.config.mapValues(\.value)) else { return nil }
        return (upper, lower, edgeIndex)
    }

    private static func references(_ nodeId: String, in value: Any) -> Bool {
        if let wrapped = value as? AnyCodable { return references(nodeId, in: wrapped.value) }
        if let text = value as? String {
            return text.contains("$nodes.\(nodeId).") || text.contains("steps.\(nodeId).")
        }
        if let items = value as? [Any] { return items.contains { references(nodeId, in: $0) } }
        if let fields = value as? [String: Any] {
            return fields.values.contains { references(nodeId, in: $0) }
        }
        if let fields = value as? [String: AnyCodable] {
            return fields.values.contains { references(nodeId, in: $0.value) }
        }
        return false
    }

    private static func edgeSignature(_ graph: WorkflowGraph) -> String {
        graph.edges.map { "\($0.from)>\($0.to):\($0.branch ?? "")" }.joined(separator: "|")
    }

    private static func copy(_ graph: WorkflowGraph, nodes: [WorkflowNode],
                             edges: [WorkflowEdge]) -> WorkflowGraph {
        WorkflowGraph(version: graph.version, triggerNodeId: graph.triggerNodeId,
                      nodes: nodes, edges: edges, variables: graph.variables,
                      limits: graph.limits, uiLayout: graph.uiLayout)
    }
}
