// Unit coverage for Workflows V1 Apple API parity.
// Uses synthetic JSON fixtures only and never touches workflow IDs, user IDs,
// auth cookies, API keys, private prompts, or live network state.
// Spec: docs/specs/workflows-v1/spec.yml

import XCTest
@testable import OpenMates

final class WorkflowsParityTests: XCTestCase {
    // contract-test: supporting surface=gui.apple assertions=workflows-ui.mvp.ask-ai
    func testAskAIHintsUseWebRequestShapeAndDecodeBlockedVerdict() throws {
        let request = WorkflowAskAIHintsRequest(
            instruction: "Summarize the earlier result",
            references: [WorkflowAskAIReferenceHint(
                reference: "$nodes.weather.output.summary", label: "Weather summary",
                valueType: "string", inserted: true
            )]
        )
        let body = try jsonObject(JSONEncoder().encode(request))
        let references = try XCTUnwrap(body["references"] as? [[String: Any]])
        XCTAssertEqual(body["instruction"] as? String, "Summarize the earlier result")
        XCTAssertEqual(references.first?["reference"] as? String, "$nodes.weather.output.summary")
        XCTAssertEqual(references.first?["value_type"] as? String, "string")
        XCTAssertEqual(references.first?["inserted"] as? Bool, true)

        let response = try JSONDecoder().decode(WorkflowAskAIHintsResponse.self, from: Data(#"{"verdict":"asks_to_invoke_app_skill","suggested_references":["$nodes.weather.output.summary"],"reminder":null}"#.utf8))
        XCTAssertEqual(response.verdict, .asksToInvokeAppSkill)
        XCTAssertEqual(response.suggestedReferences, ["$nodes.weather.output.summary"])
        XCTAssertTrue(response.verdict.blocksSave)
    }

    // contract-test: supporting surface=gui.apple assertions=workflows-ui.mvp.ask-ai,workflows.composition.earlier-action-reference
    func testAskAISavePolicyBlocksAppInvocationAndRequiresPriorValueWhenAvailable() {
        XCTAssertEqual(WorkflowAskAISavePolicy.failure(
            instruction: "Search the web", hasEarlierReference: true,
            verdict: .asksToInvokeAppSkill), .appSkillInvocation)
        XCTAssertEqual(WorkflowAskAISavePolicy.failure(
            instruction: "   ", hasEarlierReference: true,
            verdict: .unverified), .missingInstruction)
        XCTAssertEqual(WorkflowAskAISavePolicy.failure(
            instruction: "Summarize weather", hasEarlierReference: false,
            verdict: .allowed), .missingEarlierReference)
        XCTAssertNil(WorkflowAskAISavePolicy.failure(
            instruction: "Summarize weather", hasEarlierReference: true,
            verdict: .unverified), "An unavailable hint may not suppress the server's own save validation.")
    }

    @MainActor
    // contract-test: supporting surface=gui.apple assertions=workflows.access.boundaries,teams.context.full-switch-local
    func testAskAIDebounceDoesNotSendOldInstructionAfterTeamContextChanges() async throws {
        let service = RecordingAskAIHintService()
        var context = WorkflowAskAIHintContext(
            profile: ServerProfile.current(), activeScopeID: "synthetic-scope",
            offlineGeneration: UUID(), teamEpoch: 10, teamID: "team-before"
        )
        let scope = WorkflowRequestScope(accountId: "synthetic-owner",
                                         serverProfile: context.profile,
                                         offlineScope: context.offlineGeneration)
        let controller = WorkflowAskAIHintsController(
            service: service, context: { context },
            captureScope: { _ in scope },
            currentAccountID: { "synthetic-owner" }
        )
        controller.reset(accountId: "synthetic-owner")
        controller.schedule(nodeId: "ask-ai", instruction: "Summarize the prior result", references: [])
        try await Task.sleep(for: .milliseconds(1_150))
        let initialCalls = await service.callCount
        XCTAssertEqual(initialCalls, 1,
                       "The authorized unchanged context must send the hint once.")
        controller.schedule(nodeId: "ask-ai", instruction: "Summarize the new result", references: [])
        context = WorkflowAskAIHintContext(
            profile: context.profile, activeScopeID: context.activeScopeID,
            offlineGeneration: context.offlineGeneration, teamEpoch: 11, teamID: "team-after"
        )
        try await Task.sleep(for: .milliseconds(1_150))
        let calls = await service.callCount
        XCTAssertEqual(calls, 1, "The debounce must discard the old Team prompt before any API send.")
    }

    @MainActor
    // contract-test: supporting surface=gui.apple assertions=workflows.access.boundaries,teams.context.full-switch-local
    func testWorkflowQueuedMutationChecksOwnerAndTeamBeforeSending() async throws {
        let boundary = SuspendedWorkflowRequestBoundary()
        let profile = ServerProfile.current()
        let offlineScope = UUID()
        let operation = WorkflowAPIOperationScope(
            accountID: "synthetic-owner", profile: profile, offlineScope: offlineScope,
            teamContext: APIRequestTeamContext(epoch: 10, teamID: "team-before")
        )
        let environment = WorkflowAPISendEnvironment(
            currentAccountID: { await boundary.currentAccountID() },
            currentProfile: { profile }, currentOfflineScope: { offlineScope },
            currentTeamContext: { boundary.teamContext }
        )
        let executor = RecordingWorkflowRequestExecutor()

        let allowed = Task { @MainActor in
            do { try await operation.check(environment: environment); executor.send() }
            catch { XCTFail("An unchanged authorized scope must reach the request executor.") }
        }
        await boundary.waitUntilAccountCheck()
        boundary.releaseAccountCheck(as: "synthetic-owner")
        await allowed.value
        XCTAssertEqual(executor.sendCount, 1)

        let switchedAccount = Task { @MainActor in
            do { try await operation.check(environment: environment); executor.send() }
            catch { /* Expected: the old mutation is discarded before request execution. */ }
        }
        await boundary.waitUntilAccountCheck()
        boundary.releaseAccountCheck(as: "new-owner")
        await switchedAccount.value
        XCTAssertEqual(executor.sendCount, 1, "An account switch must not execute the queued mutation.")

        let switchedTeam = Task { @MainActor in
            do { try await operation.check(environment: environment); executor.send() }
            catch { /* Expected: the old Team context is discarded before request execution. */ }
        }
        await boundary.waitUntilAccountCheck()
        boundary.teamContext = APIRequestTeamContext(epoch: 11, teamID: "team-after")
        boundary.releaseAccountCheck(as: "synthetic-owner")
        await switchedTeam.value
        XCTAssertEqual(executor.sendCount, 1, "A Team switch must not execute the queued mutation.")
    }

    @MainActor
    // contract-test: supporting surface=gui.apple assertions=workflows.access.boundaries,teams.context.full-switch-local
    func testAuthoringTeamSwitchDuringAuthorizationSkipsQueuedSubmit() async throws {
        let startingTeam = APIRequestTeamContext(epoch: TeamWorkspaceContext.shared.contextEpoch,
                                                 teamID: TeamWorkspaceContext.shared.teamID)
        let boundary = SuspendedWorkflowRequestBoundary(teamContext: startingTeam,
                                                        suspendFirstOnly: true)
        let scope = WorkflowRequestScope(
            accountId: "synthetic-owner", serverProfile: ServerProfile.current(),
            offlineScope: OfflineStore.shared.scopeGeneration, teamContext: startingTeam
        )
        let environment = WorkflowAPISendEnvironment(
            currentAccountID: { await boundary.currentAccountID() },
            currentProfile: { ServerProfile.current() },
            currentOfflineScope: { OfflineStore.shared.scopeGeneration },
            currentTeamContext: { boundary.teamContext }
        )
        let service = RecordingWorkflowAIAuthoringService()
        let controller = WorkflowAIAuthoringController(
            service: service, captureScope: { _ in scope },
            checkScope: { try await $0.check(environment: environment) }
        )
        controller.reset(accountId: "synthetic-owner")

        let allowed = Task { @MainActor in
            await controller.submit("Summarize the earlier result", selectedWorkflowId: nil, timezone: "Europe/Berlin")
        }
        await boundary.waitUntilAccountCheck()
        boundary.releaseAccountCheck(as: "synthetic-owner")
        _ = await allowed.value
        let allowedSubmitCount = await service.submitCount
        XCTAssertEqual(allowedSubmitCount, 1, "The unchanged authorized scope must submit once.")

        boundary.rearmAccountCheck()
        let stale = Task { @MainActor in
            await controller.submit("Send the new result", selectedWorkflowId: nil, timezone: "Europe/Berlin")
        }
        await boundary.waitUntilAccountCheck()
        boundary.teamContext = APIRequestTeamContext(epoch: startingTeam.epoch &+ 1, teamID: "team-after")
        boundary.releaseAccountCheck(as: "synthetic-owner")
        let staleResult = await stale.value
        let finalSubmitCount = await service.submitCount
        XCTAssertNil(staleResult)
        XCTAssertEqual(finalSubmitCount, 1,
                       "A Team switch during authorization must never reach the authoring service.")
    }

    // contract-test: supporting surface=gui.apple assertions=workflows.surface.semantic-parity
    func testWorkflowAPIResponseDecoderPreservesServerSnakeCaseFields() throws {
        let workflow = try WorkflowAPI.decodeResponse(WorkflowDetail.self, from: workflowFixtureData())
        XCTAssertTrue(workflow.createdByAssistant)
        XCTAssertEqual(workflow.currentVersionId, "version-fixture")
        XCTAssertEqual(workflow.graph.triggerNodeId, "trigger")
        XCTAssertEqual(workflow.sourceChatId, "chat-fixture")
    }

    // contract-test: supporting surface=gui.apple assertions=workflows.surface.semantic-parity
    func testWorkflowListAndDetailPathsUseCapturedTeamScope() {
        XCTAssertEqual(WorkflowAPIRequestFactory.listPath(teamID: "team/a&b"), "/v1/workflows?team_id=team%2Fa%26b")
        XCTAssertEqual(WorkflowAPIRequestFactory.workflowPath("workflow", teamID: "team/a"), "/v1/workflows/workflow?team_id=team%2Fa")
        XCTAssertEqual(WorkflowAPIRequestFactory.enablePath("workflow"), "/v1/workflows/workflow/enable")
    }

    // contract-test: supporting surface=gui.apple assertions=workflows.surface.semantic-parity
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

    // contract-test: supporting surface=gui.apple assertions=workflows.execution.lifecycle-visible,workflows.content.encrypted-retained
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

    // contract-test: supporting surface=gui.apple assertions=workflows.surface.semantic-parity
    func testWorkflowRequestsUseSharedApiPathsAndSnakeCasePayloads() throws {
        let workflow = try JSONDecoder().decode(WorkflowDetail.self, from: workflowFixtureData())
        let create = WorkflowCreateRequest(title: workflow.title, description: workflow.description, graph: workflow.graph, enabled: true, runContentRetention: .none)
        let update = WorkflowUpdateRequest(title: nil, description: "Updated description", graph: nil, enabled: false, runContentRetention: .last5)
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
        XCTAssertEqual(WorkflowAPIRequestFactory.versionsPath("wf-fixture"), "/v1/workflows/wf-fixture/versions")
        XCTAssertEqual(WorkflowAPIRequestFactory.versionPath(workflowId: "wf-fixture", versionId: "v 2"), "/v1/workflows/wf-fixture/versions/v%202")
        XCTAssertEqual(WorkflowAPIRequestFactory.cancelRunPath(workflowId: "wf-fixture", runId: "run-fixture"), "/v1/workflows/wf-fixture/runs/run-fixture/cancel")
        XCTAssertEqual(WorkflowAPIRequestFactory.runDetailPath(workflowId: "wf-fixture", runId: "run fixture"), "/v1/workflows/wf-fixture/runs/run%20fixture")
        XCTAssertEqual(createJson["run_content_retention"] as? String, "none")
        XCTAssertEqual(updateJson["run_content_retention"] as? String, "last_5")
        XCTAssertEqual(updateJson["enabled"] as? Bool, false)
        XCTAssertEqual(runJson["mode"] as? String, "test")
    }

    // contract-test: supporting surface=gui.apple assertions=workflows.mvp.steps,workflows.schedule.recurrence
    func testStarterCardsCreateDisabledWebGraphsWithScheduleAndRecipientSteps() throws {
        for kind in WorkflowStarterKind.allCases {
            let graph = kind.graph(timezone: "Europe/Berlin")
            XCTAssertEqual(graph.version, 2)
            XCTAssertEqual(graph.triggerNodeId, "trigger")
            XCTAssertEqual(graph.nodes.first?.type, .scheduleTrigger)
            XCTAssertEqual(graph.nodes.last?.type, .sendChatMessage)
            XCTAssertEqual(graph.edges.count, graph.nodes.count - 1)
            let payload = try jsonObject(JSONEncoder().encode(graph))
            let nodes = try XCTUnwrap(payload["nodes"] as? [[String: Any]])
            let trigger = try XCTUnwrap(nodes.first?["config"] as? [String: Any])
            let schedule = try XCTUnwrap(trigger["schedule"] as? [String: Any])
            XCTAssertEqual(schedule["timezone"] as? String, "Europe/Berlin")
            switch kind {
            case .rainAlert:
                XCTAssertEqual(nodes.map { $0["id"] as? String },
                               ["trigger", "weather", "rain", "news", "message"])
                XCTAssertEqual(schedule["type"] as? String, "daily")
                XCTAssertEqual(schedule["time"] as? String, "09:00")
            case .newsBrief:
                XCTAssertEqual(nodes.map { $0["id"] as? String }, ["trigger", "events", "message"])
                XCTAssertEqual(schedule["weekdays"] as? [String], ["sunday"])
            case .hourlyApartments:
                XCTAssertEqual(nodes.map { $0["id"] as? String }, ["trigger", "apartments", "message"])
                XCTAssertEqual(schedule["minute"] as? Int, 0)
            }
        }
    }

    @MainActor
    // contract-test: supporting surface=gui.apple assertions=workflows-ui.workspace.recommendation-led-composition,workflows.activation.reachable-side-effect
    func testRapidStarterTapSendsOneCreateAndAllowsLaterCreation() async throws {
        let detail = try JSONDecoder().decode(WorkflowDetail.self, from: workflowFixtureData())
        let recorder = SuspendedWorkflowCreateExecutor(result: detail)
        let store = WorkflowStore(createWorkflowRequest: { request, scope in
            await recorder.create(request, scope: scope)
        })
        store.reset(accountId: "synthetic-owner")

        let first = Task { @MainActor in await store.createStarter(.rainAlert) }
        await recorder.waitUntilFirstRequest()
        XCTAssertTrue(store.isLoading)
        await store.createStarter(.newsBrief)
        XCTAssertEqual(recorder.callCount, 1,
                       "A second tap while creation is pending must not send a duplicate request.")

        recorder.releaseFirstRequest()
        await first.value
        XCTAssertFalse(store.isLoading)
        await store.createStarter(.newsBrief)
        XCTAssertEqual(recorder.callCount, 2,
                       "A later starter selection must still create after the first request finishes.")
        XCTAssertFalse(recorder.requests[0].enabled)
        XCTAssertEqual(recorder.requests[0].graph.nodes.map(\.id),
                       ["trigger", "weather", "rain", "news", "message"])
    }

    // contract-test: supporting surface=gui.apple assertions=workflows.activation.reachable-side-effect,workflows.mvp.steps
    func testBlankServerGraphAndMinimalNodesDecodeAndRoundTrip() throws {
        let data = Data(#"{"version":1,"trigger_node_id":null,"nodes":[{"id":"n1","type":"check"}],"edges":[]}"#.utf8)
        let graph = try JSONDecoder().decode(WorkflowGraph.self, from: data)
        XCTAssertEqual(graph.triggerNodeId, "")
        XCTAssertEqual(graph.nodes.first?.type, .check)
        XCTAssertTrue(graph.nodes.first?.config.isEmpty == true)
        XCTAssertTrue(graph.nodes.first?.inputMapping.isEmpty == true)
        let encoded = try jsonObject(JSONEncoder().encode(graph))
        XCTAssertTrue(encoded["trigger_node_id"] is NSNull)
    }

    // contract-test: supporting surface=gui.apple assertions=workflows.execution.lifecycle-visible,workflows-ui.runs.timeline-execution-detail
    func testRunListSummaryDoesNotRequireRetainedNodeContent() throws {
        let data = Data(#"{"runs":[{"id":"r1","workflow_id":"w1","version_id":"v1","trigger_type":"manual","status":"queued"}]}"#.utf8)
        let result = try JSONDecoder().decode(WorkflowRunsResponse.self, from: data)
        XCTAssertEqual(result.runs.count, 1)
        XCTAssertEqual(result.runs.first?.status, "queued")
        XCTAssertFalse(result.runs.first?.contentAvailable ?? true)
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

private actor RecordingAskAIHintService: WorkflowAskAIHintServing {
    private(set) var callCount = 0

    func hints(_ request: WorkflowAskAIHintsRequest,
               scope: WorkflowRequestScope) async throws -> WorkflowAskAIHintsResponse {
        callCount += 1
        return WorkflowAskAIHintsResponse(verdict: .allowed, suggestedReferences: [], reminder: nil)
    }
}

private actor RecordingWorkflowAIAuthoringService: WorkflowAIAuthoringServing {
    private(set) var submitCount = 0

    func submit(_ text: String, selectedWorkflowId: String?, timezone: String,
                scope: WorkflowRequestScope) async throws -> WorkflowInputSession {
        submitCount += 1
        return try JSONDecoder().decode(WorkflowInputSession.self,
            from: Data(#"{"session_id":"synthetic-session","status":"draft"}"#.utf8))
    }

    func get(_ sessionId: String, scope: WorkflowRequestScope) async throws -> WorkflowInputSession {
        throw CancellationError()
    }

    func undo(_ sessionId: String, scope: WorkflowRequestScope) async throws -> WorkflowInputSession {
        throw CancellationError()
    }
}

@MainActor
private final class SuspendedWorkflowCreateExecutor {
    let result: WorkflowDetail
    private(set) var requests: [WorkflowCreateRequest] = []
    var callCount: Int { requests.count }
    private var entered: CheckedContinuation<Void, Never>?
    private var firstRequest: CheckedContinuation<Void, Never>?

    init(result: WorkflowDetail) { self.result = result }

    func create(_ request: WorkflowCreateRequest,
                scope: WorkflowAPIOperationScope) async -> WorkflowDetail {
        requests.append(request)
        if requests.count == 1 {
            await withCheckedContinuation { continuation in
                firstRequest = continuation
                entered?.resume()
                entered = nil
            }
        }
        return result
    }

    func waitUntilFirstRequest() async {
        if firstRequest != nil { return }
        await withCheckedContinuation { continuation in entered = continuation }
    }

    func releaseFirstRequest() {
        firstRequest?.resume()
        firstRequest = nil
    }
}

@MainActor
private final class RecordingWorkflowRequestExecutor {
    private(set) var sendCount = 0
    func send() { sendCount += 1 }
}

@MainActor
private final class SuspendedWorkflowRequestBoundary {
    var teamContext: APIRequestTeamContext
    private let suspendFirstOnly: Bool
    private var hasSuspended = false
    private var resumedAccountID: String?
    private var accountCheck: CheckedContinuation<String?, Never>?
    private var entered: CheckedContinuation<Void, Never>?

    init(teamContext: APIRequestTeamContext = APIRequestTeamContext(epoch: 10, teamID: "team-before"),
         suspendFirstOnly: Bool = false) {
        self.teamContext = teamContext
        self.suspendFirstOnly = suspendFirstOnly
    }

    func currentAccountID() async -> String? {
        if suspendFirstOnly && hasSuspended { return resumedAccountID }
        hasSuspended = true
        return await withCheckedContinuation { continuation in
            accountCheck = continuation
            entered?.resume()
            entered = nil
        }
    }

    func waitUntilAccountCheck() async {
        if accountCheck != nil { return }
        await withCheckedContinuation { continuation in entered = continuation }
    }

    func releaseAccountCheck(as accountID: String?) {
        resumedAccountID = accountID
        accountCheck?.resume(returning: accountID)
        accountCheck = nil
    }

    func rearmAccountCheck() { hasSuspended = false }
}
