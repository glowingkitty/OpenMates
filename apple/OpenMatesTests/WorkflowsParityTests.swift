// Unit coverage for Workflows V1 Apple API parity.
// Uses synthetic JSON fixtures only and never touches workflow IDs, user IDs,
// auth cookies, API keys, private prompts, or live network state.
// Spec: docs/specs/workflows-v1/spec.yml

import XCTest
@testable import OpenMates

final class WorkflowsParityTests: XCTestCase {
    func testWorkflowDetailDecodesSharedApiShape() throws {
        let workflow = try JSONDecoder().decode(WorkflowDetail.self, from: workflowFixtureData())

        XCTAssertEqual(workflow.id, "wf-fixture")
        XCTAssertEqual(workflow.title, "Daily rain alert")
        XCTAssertEqual(workflow.runContentRetention, .none)
        XCTAssertEqual(workflow.graph.triggerNodeId, "trigger")
        XCTAssertEqual(workflow.graph.nodes.map(\.type), [.scheduleTrigger, .appSkillAction, .decision, .sendNotification, .end])
        XCTAssertEqual(workflow.graph.edges.first?.from, "trigger")
    }

    func testWorkflowRunDecodesRetentionAndNodeHistory() throws {
        let run = try JSONDecoder().decode(WorkflowRunDetail.self, from: runFixtureData())

        XCTAssertEqual(run.id, "run-fixture")
        XCTAssertEqual(run.status, "completed")
        XCTAssertEqual(run.contentRetentionMode, .last5)
        XCTAssertEqual(run.contentStorage, .durable)
        XCTAssertTrue(run.contentAvailable)
        XCTAssertEqual(run.nodeRuns.first?.nodeType, .appSkillAction)
        XCTAssertEqual(run.nodeRuns.first?.outputSummary["rain_probability"]?.value as? Int, 70)
    }

    func testWorkflowRequestsUseSharedApiPathsAndSnakeCasePayloads() throws {
        let workflow = try JSONDecoder().decode(WorkflowDetail.self, from: workflowFixtureData())
        let create = WorkflowCreateRequest(title: workflow.title, graph: workflow.graph, enabled: true, runContentRetention: .none)
        let update = WorkflowUpdateRequest(title: nil, graph: nil, enabled: false, runContentRetention: .last5)
        let run = WorkflowRunRequest(mode: "test", input: ["dry": AnyCodable(true)])
        let encoder = JSONEncoder()

        let createJson = try jsonObject(encoder.encode(create))
        let updateJson = try jsonObject(encoder.encode(update))
        let runJson = try jsonObject(encoder.encode(run))

        XCTAssertEqual(WorkflowAPIRequestFactory.listPath(), "/v1/workflows")
        XCTAssertEqual(WorkflowAPIRequestFactory.workflowPath("wf fixture"), "/v1/workflows/wf%20fixture")
        XCTAssertEqual(WorkflowAPIRequestFactory.enablePath("wf-fixture"), "/v1/workflows/wf-fixture/enable")
        XCTAssertEqual(WorkflowAPIRequestFactory.disablePath("wf-fixture"), "/v1/workflows/wf-fixture/disable")
        XCTAssertEqual(WorkflowAPIRequestFactory.runPath("wf-fixture"), "/v1/workflows/wf-fixture/run")
        XCTAssertEqual(WorkflowAPIRequestFactory.runsPath("wf-fixture"), "/v1/workflows/wf-fixture/runs")
        XCTAssertEqual(WorkflowAPIRequestFactory.runDetailPath(workflowId: "wf-fixture", runId: "run fixture"), "/v1/workflows/wf-fixture/runs/run%20fixture")
        XCTAssertEqual(createJson["run_content_retention"] as? String, "none")
        XCTAssertEqual(updateJson["run_content_retention"] as? String, "last_5")
        XCTAssertEqual(updateJson["enabled"] as? Bool, false)
        XCTAssertEqual(runJson["mode"] as? String, "test")
    }

    private func workflowFixtureData() -> Data {
        Data(
            #"""
            {
              "id": "wf-fixture",
              "title": "Daily rain alert",
              "status": "active",
              "enabled": true,
              "trigger_summary": "daily at 07:00",
              "next_run_at": null,
              "last_run_status": "completed",
              "run_content_retention": "none",
              "current_version_id": "version-fixture",
              "created_at": 1,
              "updated_at": 2,
              "graph": {
                "version": 1,
                "trigger_node_id": "trigger",
                "nodes": [
                  {"id": "trigger", "type": "schedule_trigger", "title": "Every morning", "config": {"schedule": {"type": "daily", "time": "07:00"}}, "input_mapping": {}, "ui": {}},
                  {"id": "weather", "type": "app_skill_action", "title": "Check weather", "config": {"app_id": "weather", "skill_id": "forecast"}, "input_mapping": {}, "ui": {}},
                  {"id": "decision", "type": "decision", "title": "Decision", "config": {"predicate": {"left": "$nodes.weather.output.rain_probability", "op": "gte", "right": 60}}, "input_mapping": {}, "ui": {}},
                  {"id": "notify", "type": "send_notification", "title": "Push", "config": {}, "input_mapping": {}, "ui": {}},
                  {"id": "end", "type": "end", "title": "Done", "config": {}, "input_mapping": {}, "ui": {}}
                ],
                "edges": [
                  {"from": "trigger", "to": "weather"},
                  {"from": "weather", "to": "decision"},
                  {"from": "decision", "to": "notify", "branch": "yes"},
                  {"from": "notify", "to": "end"}
                ],
                "variables": {},
                "limits": {},
                "ui_layout": {}
              }
            }
            """#.utf8
        )
    }

    private func runFixtureData() -> Data {
        Data(
            #"""
            {
              "id": "run-fixture",
              "workflow_id": "wf-fixture",
              "version_id": "version-fixture",
              "trigger_type": "manual",
              "status": "completed",
              "content_retention_mode": "last_5",
              "content_available": true,
              "content_storage": "durable",
              "content_expires_at": null,
              "node_runs": [
                {
                  "id": "node-run-fixture",
                  "run_id": "run-fixture",
                  "workflow_id": "wf-fixture",
                  "node_id": "weather",
                  "node_type": "app_skill_action",
                  "status": "completed",
                  "output_summary": {"rain_probability": 70}
                }
              ]
            }
            """#.utf8
        )
    }

    private func jsonObject(_ data: Data) throws -> [String: Any] {
        try XCTUnwrap(JSONSerialization.jsonObject(with: data) as? [String: Any])
    }
}
