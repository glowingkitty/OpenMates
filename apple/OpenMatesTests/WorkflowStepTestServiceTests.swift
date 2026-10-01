// Synthetic scoping proof for unsaved Workflow step tests.
// Specification: specifications/features/workflows/specification.yml

import XCTest
@testable import OpenMates

final class WorkflowStepTestServiceTests: XCTestCase {
    // contract-test: supporting surface=gui.apple assertions=workflows.control.typed-data
    func testOnlyEarlierOutputsReachStepTest() {
        let graph = WorkflowGraph(version: 1, triggerNodeId: "trigger", nodes: [
            node("trigger", .manualTrigger), node("weather", .appSkillAction),
            node("check", .check), node("later", .appSkillAction)
        ], edges: [
            WorkflowEdge(from: "trigger", to: "weather", branch: nil),
            WorkflowEdge(from: "weather", to: "check", branch: nil),
            WorkflowEdge(from: "check", to: "later", branch: "yes")
        ], variables: [:], limits: [:], uiLayout: [:])
        let outputs: [String: [String: AnyCodable]] = [
            "weather": ["temperature": AnyCodable(21)],
            "later": ["secret": AnyCodable("placeholder")],
        ]
        let scoped = WorkflowUpstreamOutputs.scoped(graph: graph, nodeId: "check", available: outputs)
        XCTAssertEqual(scoped.keys.sorted(), ["weather"])
        let inserted = WorkflowUpstreamOutputs.scoped(
            graph: graph, nodeId: "new-step", available: outputs, insertionAfter: "weather"
        )
        XCTAssertEqual(inserted.keys.sorted(), ["weather"])
    }

    private func node(_ id: String, _ type: WorkflowNodeType) -> WorkflowNode {
        WorkflowNode(id: id, type: type, title: nil, config: [:], inputMapping: [:], ui: [:])
    }
}
