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
        XCTAssertEqual(workflow.lifecycle, .temporary)
        XCTAssertEqual(workflow.source, "workflow_input")
        XCTAssertEqual(workflow.sourceChatId, "chat-fixture")
        XCTAssertTrue(workflow.createdByAssistant)
        XCTAssertEqual(workflow.autoDeleteAt, 300)
        XCTAssertEqual(workflow.keptAt, 250)
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
        XCTAssertEqual(run.startedAt, 10)
        XCTAssertEqual(run.finishedAt, 20)
        XCTAssertNil(run.errorSummary)
        XCTAssertEqual(run.costSummary["credits"]?.value as? Int, 2)
        XCTAssertEqual(run.outputSummary["alert_sent"]?.value as? Bool, true)

        let nodeRun = try XCTUnwrap(run.nodeRuns.first)
        XCTAssertEqual(nodeRun.nodeType, .appSkillAction)
        XCTAssertEqual(nodeRun.startedAt, 11)
        XCTAssertEqual(nodeRun.finishedAt, 19)
        XCTAssertEqual(nodeRun.attempt, 1)
        XCTAssertNil(nodeRun.skippedReason)
        XCTAssertNil(nodeRun.errorCode)
        XCTAssertNil(nodeRun.errorSummary)
        XCTAssertEqual(nodeRun.inputSummary["location"]?.value as? String, "Berlin")
        XCTAssertEqual(nodeRun.outputSummary["rain_probability"]?.value as? Int, 70)
        XCTAssertEqual(nodeRun.creditCost, 2)
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
              "lifecycle": "temporary",
              "source": "workflow_input",
              "source_chat_id": "chat-fixture",
              "created_by_assistant": true,
              "auto_delete_at": 300,
              "kept_at": 250,
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
              "started_at": 10,
              "finished_at": 20,
              "error_summary": null,
              "cost_summary": {"credits": 2},
              "content_retention_mode": "last_5",
              "content_available": true,
              "content_storage": "durable",
              "content_expires_at": null,
              "output_summary": {"alert_sent": true},
              "node_runs": [
                {
                  "id": "node-run-fixture",
                  "run_id": "run-fixture",
                  "workflow_id": "wf-fixture",
                  "node_id": "weather",
                  "node_type": "app_skill_action",
                  "status": "completed",
                  "started_at": 11,
                  "finished_at": 19,
                  "attempt": 1,
                  "skipped_reason": null,
                  "error_code": null,
                  "error_summary": null,
                  "input_summary": {"location": "Berlin"},
                  "output_summary": {"rain_probability": 70},
                  "credit_cost": 2
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
