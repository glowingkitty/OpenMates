// Native parity for the web Workflow graph reorder contract.
// Web source: frontend/packages/ui/src/components/workflows/__tests__/workflowReordering.test.ts
// Specification: specifications/features/workflows/specification.yml

import XCTest
@testable import OpenMates

final class WorkflowGraphReorderingTests: XCTestCase {
    // contract-test: supporting surface=gui.apple assertions=workflows.mvp.steps
    func testAdjacentMovePreservesTriggerAndContinuation() {
        let graph = linearGraph()
        XCTAssertFalse(WorkflowGraphReordering.canMove(graph, nodeId: "a", direction: .up))
        XCTAssertTrue(WorkflowGraphReordering.canMove(graph, nodeId: "b", direction: .up))
        let moved = WorkflowGraphReordering.move(graph, nodeId: "b", direction: .up)
        XCTAssertEqual(moved?.nodes.map(\.id), ["trigger", "b", "a", "c", "send"])
        XCTAssertEqual(links(moved), ["a->c", "b->a", "c->send", "trigger->b"])
        XCTAssertEqual(links(WorkflowGraphReordering.moveAfter(graph, sourceId: "c", afterId: "trigger")),
                       ["a->b", "b->send", "c->a", "trigger->c"])
    }

    // contract-test: supporting surface=gui.apple assertions=workflows.control.typed-data
    func testReferenceCannotMoveAfterConsumer() {
        let base = linearGraph()
        let nodes = base.nodes.map { node in
            node.id == "b"
                ? WorkflowNode(id: node.id, type: node.type, title: nil,
                               config: ["input": AnyCodable(["prompt": "Use {{steps.a.answer}} and $nodes.a.output.summary"])],
                               inputMapping: [:], ui: [:])
                : node
        }
        let dependent = WorkflowGraph(version: base.version, triggerNodeId: base.triggerNodeId,
                                      nodes: nodes, edges: base.edges, variables: [:], limits: [:], uiLayout: [:])
        XCTAssertFalse(WorkflowGraphReordering.canMove(dependent, nodeId: "b", direction: .up))
        XCTAssertNil(WorkflowGraphReordering.moveTo(dependent, sourceId: "b", targetId: "a"))
        XCTAssertNil(WorkflowGraphReordering.moveTo(dependent, sourceId: "a", targetId: "b"))
    }

    // contract-test: supporting surface=gui.apple assertions=workflows.control.check
    func testBranchLabelRemainsAttachedDuringMove() {
        let nodes = ["trigger", "check", "yes", "next", "no"].map { id in
            node(id, type: id == "trigger" ? .scheduleTrigger : id == "check" ? .check : .appSkillAction)
        }
        let graph = WorkflowGraph(version: 1, triggerNodeId: "trigger", nodes: nodes, edges: [
            WorkflowEdge(from: "trigger", to: "check", branch: nil),
            WorkflowEdge(from: "check", to: "yes", branch: "yes"),
            WorkflowEdge(from: "yes", to: "next", branch: nil),
            WorkflowEdge(from: "check", to: "no", branch: "no"),
        ], variables: [:], limits: [:], uiLayout: [:])
        let moved = WorkflowGraphReordering.move(graph, nodeId: "next", direction: .up)
        XCTAssertEqual(moved?.edges.first(where: { $0.branch == "yes" })?.to, "next")
        XCTAssertEqual(moved?.edges.first(where: { $0.from == "next" })?.to, "yes")
        XCTAssertFalse(WorkflowGraphReordering.canMove(graph, nodeId: "yes", direction: .up))
    }

    private func linearGraph() -> WorkflowGraph {
        WorkflowGraph(version: 2, triggerNodeId: "trigger", nodes: [
            node("trigger", type: .scheduleTrigger), node("a"), node("b"), node("c"),
            node("send", type: .sendChatMessage)
        ], edges: [
            WorkflowEdge(from: "trigger", to: "a", branch: nil),
            WorkflowEdge(from: "a", to: "b", branch: nil),
            WorkflowEdge(from: "b", to: "c", branch: nil),
            WorkflowEdge(from: "c", to: "send", branch: nil),
        ], variables: [:], limits: [:], uiLayout: [:])
    }

    private func node(_ id: String, type: WorkflowNodeType = .appSkillAction) -> WorkflowNode {
        WorkflowNode(id: id, type: type, title: nil, config: [:], inputMapping: [:], ui: [:])
    }

    private func links(_ graph: WorkflowGraph?) -> [String] {
        graph?.edges.map { "\($0.from)->\($0.to)" }.sorted() ?? []
    }
}
