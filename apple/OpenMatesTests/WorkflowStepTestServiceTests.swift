// Synthetic scoping proof for unsaved Workflow step tests.
// Specification: specifications/features/workflows/specification.yml

import XCTest
@testable import OpenMates

final class WorkflowStepTestServiceTests: XCTestCase {
    // contract-test: supporting surface=gui.apple assertions=workflows.control.typed-data
    func testStepTestRequestMatchesWebDraftNodeAndScopedOutputs() throws {
        let draft = WorkflowNode(id: "events-node", type: .appSkillAction, title: "Synthetic events", config: [
            "app_id": AnyCodable("events"), "skill_id": AnyCodable("search")
        ], inputMapping: ["query": AnyCodable("Synthetic public events")], ui: [:])
        let request = WorkflowStepTestRequest(node: draft, input: [:], upstreamOutputs: [
            "earlier": ["count": AnyCodable(2), "results": AnyCodable([["title": "Synthetic result"]])]
        ])
        let encoder = JSONEncoder()
        encoder.keyEncodingStrategy = .convertToSnakeCase
        let json = try XCTUnwrap(JSONSerialization.jsonObject(with: encoder.encode(request)) as? [String: Any])
        XCTAssertEqual(Set(json.keys), ["node", "input", "upstream_outputs"])
        XCTAssertEqual((json["input"] as? [String: String])?.count, 0)
        let node = try XCTUnwrap(json["node"] as? [String: Any])
        XCTAssertEqual(node["id"] as? String, draft.id)
        XCTAssertEqual(node["type"] as? String, "app_skill_action")
        XCTAssertEqual((node["config"] as? [String: String])?["skill_id"], "search")
        XCTAssertEqual((node["input_mapping"] as? [String: String])?["query"], "Synthetic public events")
        XCTAssertNotNil((json["upstream_outputs"] as? [String: Any])?["earlier"])
        XCTAssertEqual(WorkflowStepTestWire.path(workflowId: "workflow/one", nodeId: "node?two", action: "test"),
                       "/v1/workflows/workflow%2Fone/steps/node%3Ftwo/test")
    }

    // contract-test: supporting surface=gui.apple assertions=workflows.control.typed-data
    func testStepTestAndPollingDecodeWebRunEnvelopeWithoutLosingNestedResults() throws {
        let output: [String: Any] = ["count": 2, "results": [
            ["title": "Synthetic result one", "url": "https://example.org/one"],
            ["title": "Synthetic result two", "url": "https://example.org/two"]
        ]]
        let run: [String: Any] = ["id": "synthetic-run", "workflow_id": "synthetic-workflow",
            "version_id": "synthetic-version", "trigger_type": "test", "status": "completed",
            "node_runs": [["id": "synthetic-node-run", "run_id": "synthetic-run", "workflow_id": "synthetic-workflow",
                "node_id": "events-node", "node_type": "app_skill_action", "status": "completed",
                "output_summary": output]], "output_summary": output]
        let data = try JSONSerialization.data(withJSONObject: ["run": run])
        let response = try WorkflowStepTestWire.decode(WorkflowRunResponse.self, data: data)
        XCTAssertEqual(response.run.workflowId, "synthetic-workflow")
        XCTAssertEqual(response.run.versionId, "synthetic-version")
        XCTAssertEqual(response.run.status, "completed")
        XCTAssertEqual(response.run.nodeRuns.first?.nodeId, "events-node")
        XCTAssertEqual(response.run.nodeRuns.first?.outputSummary["count"]?.value as? Int, 2)
        let nested = try XCTUnwrap(response.run.nodeRuns.first?.outputSummary["results"]?.value as? [[String: Any]])
        XCTAssertEqual(nested.count, 2)
        XCTAssertEqual(nested[1]["url"] as? String, "https://example.org/two")
        XCTAssertEqual(response.run.outputSummary["count"]?.value as? Int, 2)
        let queued = try WorkflowStepTestWire.decode(WorkflowRunResponse.self, data:
            JSONSerialization.data(withJSONObject: ["run": ["id": "synthetic-run", "workflow_id": "synthetic-workflow",
                "version_id": "synthetic-version", "status": "queued"]]))
        XCTAssertEqual(queued.run.status, "queued")
        XCTAssertTrue(queued.run.nodeRuns.isEmpty)
        var invalid = run
        invalid.removeValue(forKey: "workflow_id")
        XCTAssertThrowsError(try WorkflowStepTestWire.decode(WorkflowRunResponse.self, data:
            JSONSerialization.data(withJSONObject: ["run": invalid])), "Authority fields must remain mandatory")
    }

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
