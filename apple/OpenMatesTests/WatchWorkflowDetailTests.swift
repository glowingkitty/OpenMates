import Foundation
import XCTest
@testable import OpenMates

@MainActor final class WatchWorkflowDetailTests: XCTestCase {
    // contract-test: supporting surface=gui.apple assertions=apple-watch.workflows.compact-editor
    func testGraphOrderingContainsEveryNodeTypeAndTerminatesCycles() throws {
        var graph = try WatchWorkflowDetailFixtures.graph()
        XCTAssertEqual(try graph.orderedNodes().map(\.id), ["trigger", "weather", "ask", "check", "message"])
        var edges = graph.raw["edges"]!.array
        edges.append(.object(["from": .string("message"), "to": .string("trigger")]))
        graph.raw["edges"] = .array(edges)
        XCTAssertEqual(try graph.orderedNodes().count, 5)
        var nodes = graph.raw["nodes"]!.array
        nodes.append(nodes[0]); graph.raw["nodes"] = .array(nodes)
        XCTAssertThrowsError(try graph.orderedNodes())
    }

    // contract-test: supporting surface=gui.apple assertions=apple-watch.workflows.compact-editor
    func testEverySupportedNodeDraftPreservesUnknownGraphAndTypedReferences() throws {
        let graph = try WatchWorkflowDetailFixtures.graph()
        for node in graph.nodes {
            var draft = WatchWorkflowNodeDraft(node: node)
            let title = try XCTUnwrap(draft.fields.firstIndex(where: { $0.path == ["title"] }))
            draft.fields[title].value = "Edited " + node.id
            let edited = try draft.editedNode()
            let changed = try graph.replacing(edited)
            let roundTrip = try JSONDecoder().decode(WatchWorkflowGraph.self, from: JSONEncoder().encode(changed))
            XCTAssertEqual(roundTrip, changed)
            for (key, value) in graph.raw where key != "nodes" { XCTAssertEqual(roundTrip.raw[key], value, key) }
            for prior in graph.nodes where prior.id != node.id { XCTAssertEqual(roundTrip.nodes.first(where: { $0.id == prior.id }), prior) }
            var expected = node.raw; expected["title"] = .string("Edited " + node.id)
            XCTAssertEqual(roundTrip.nodes.first(where: { $0.id == node.id })?.raw, expected)
        }
        XCTAssertEqual(graph.raw["variables"]?.object["futureVariable"], .integer(9_007_199_254_740_993))
    }

    // contract-test: supporting surface=gui.apple assertions=apple-watch.workflows.compact-editor
    func testUntouchedMissingAndNullTitlesStayAbsentAndNull() throws {
        let titles: [WatchWorkflowValue?] = [nil, .null]
        for originalTitle in titles {
            var raw = try XCTUnwrap(WatchWorkflowDetailFixtures.graph().nodes.first).raw
            raw["title"] = originalTitle
            let node = WatchWorkflowNode(raw: raw)
            XCTAssertEqual(try WatchWorkflowNodeDraft(node: node).editedNode(), node)
        }
    }

    // contract-test: supporting surface=gui.apple assertions=apple-watch.workflows.compact-editor
    func testPatchSendsOnlyGraphAndSuccessfulServerResponsePublishesEdit() async throws {
        let transport = try Transport()
        let service = transport.service()
        await service.load(id: "workflow-one", scope: transport.scope)
        service.beginEditing(nodeID: "trigger")
        try change(service, field: ["config", "schedule", "time"], value: "10:30")
        let original = transport.graph
        let asyncResult1 = await service.save()
        XCTAssertTrue(asyncResult1)
        XCTAssertEqual(transport.methods, [.get, .get, .patch])
        let body = try XCTUnwrap(transport.patchBody)
        let object = try JSONDecoder().decode([String: WatchWorkflowValue].self, from: body)
        XCTAssertEqual(Set(object.keys), ["graph"])
        XCTAssertNil(object["enabled"])
        XCTAssertEqual(object["graph"]?.object["edges"], original.raw["edges"])
        XCTAssertEqual(object["graph"]?.object["ui_layout"], original.raw["ui_layout"])
        XCTAssertEqual(object["graph"]?.object["future_graph_key"], original.raw["future_graph_key"])
        XCTAssertNil(service.draft)
        guard case let .loaded(detail) = service.state else { return XCTFail("Expected confirmed saved detail") }
        XCTAssertFalse(detail.enabled)
        XCTAssertEqual(detail.graph.nodes.first?.config["schedule"]?.object["time"], .string("10:30"))
    }

    // contract-test: supporting surface=gui.apple assertions=apple-watch.workflows.compact-editor
    func testCancelDoesNotWriteAndFailedSaveRetainsDraftForRetry() async throws {
        let transport = try Transport()
        let service = transport.service()
        await service.load(id: "workflow-one", scope: transport.scope)
        service.beginEditing(nodeID: "trigger")
        try change(service, field: ["title"], value: "Canceled name")
        service.cancelEditing()
        XCTAssertEqual(transport.methods, [.get])
        XCTAssertNil(service.draft)
        service.beginEditing(nodeID: "trigger")
        try change(service, field: ["title"], value: "Retained name")
        let draft = service.draft
        transport.failPatch = true
        let asyncResult2 = await service.save()
        XCTAssertFalse(asyncResult2)
        XCTAssertEqual(service.draft, draft)
        XCTAssertNotNil(service.saveError)
        transport.failPatch = false
        let asyncResult3 = await service.save()
        XCTAssertTrue(asyncResult3)
        guard case let .loaded(detail) = service.state else { return XCTFail("Missing saved result") }
        XCTAssertEqual(detail.graph.nodes.first?.title, "Retained name")
    }

    // contract-test: supporting surface=gui.apple assertions=apple-watch.workflows.compact-editor
    func testSaveResponseThatDoesNotConfirmEditedNodeCannotShowSuccess() async throws {
        let transport = try Transport()
        let service = transport.service()
        await service.load(id: "workflow-one", scope: transport.scope)
        service.beginEditing(nodeID: "trigger")
        try change(service, field: ["title"], value: "Unconfirmed title")
        let draft = service.draft
        transport.ignorePatchGraph = true
        let saved = await service.save()
        XCTAssertFalse(saved)
        XCTAssertEqual(service.saveError, .invalidResponse)
        XCTAssertEqual(service.draft, draft)
        guard case let .loaded(detail) = service.state else { return XCTFail("Original detail lost") }
        XCTAssertEqual(detail.graph.nodes.first?.title, "Every morning")
    }

    // contract-test: supporting surface=gui.apple assertions=apple-watch.workflows.compact-editor
    func testLoadFailureRetryAndEmptyGraphStates() async throws {
        let transport = try Transport()
        let service = transport.service()
        transport.failGet = true
        await service.load(id: "workflow-one", scope: transport.scope)
        XCTAssertEqual(service.state, .failed)
        XCTAssertTrue(service.orderedNodes.isEmpty)
        transport.failGet = false
        transport.graph = try WatchWorkflowDetailFixtures.graph(empty: true)
        await service.load(id: "workflow-one", scope: transport.scope)
        guard case .loaded = service.state else { return XCTFail("Retry did not load") }
        XCTAssertTrue(service.orderedNodes.isEmpty)
    }

    // contract-test: supporting surface=gui.apple assertions=apple-watch.workflows.compact-editor
    func testKnownConflictRetainsDraftWithoutPatch() async throws {
        let transport = try Transport()
        let service = transport.service()
        await service.load(id: "workflow-one", scope: transport.scope)
        service.beginEditing(nodeID: "trigger")
        transport.version = "other-device-version"
        let asyncResult4 = await service.save()
        XCTAssertFalse(asyncResult4)
        XCTAssertEqual(service.saveError, .changed)
        XCTAssertNotNil(service.draft)
        XCTAssertEqual(transport.methods, [.get, .get])
    }

    // contract-test: supporting surface=gui.apple assertions=apple-watch.workflows.compact-editor
    func testLatePreviousSelectionCannotPublishOrClearCurrentSelection() async throws {
        let transport = try Transport()
        let service = transport.service()
        let gate = Gate()
        transport.getGate = gate
        let first = Task { await service.load(id: "workflow-one", scope: transport.scope) }
        await gate.waitUntilEntered()
        transport.getGate = nil
        await service.load(id: "workflow-two", scope: transport.scope)
        gate.release()
        await first.value
        guard case let .loaded(detail) = service.state else { return XCTFail("Current selection lost") }
        XCTAssertEqual(detail.id, "workflow-two")
        XCTAssertFalse(service.matches(id: "workflow-one", scope: transport.scope))
    }

    // contract-test: supporting surface=gui.apple assertions=apple-watch.workflows.compact-editor
    func testAccountChangeDiscardsLateSaveAndTeamContextNeverDispatches() async throws {
        let transport = try Transport()
        let service = transport.service()
        await service.load(id: "workflow-one", scope: transport.scope)
        service.beginEditing(nodeID: "trigger")
        try change(service, field: ["title"], value: "Must not appear")
        let gate = Gate(); transport.patchGate = gate
        let saving = Task { await service.save() }
        await gate.waitUntilEntered()
        transport.accountID = "different-account"
        gate.release()
        let asyncResult5 = await saving.value
        XCTAssertFalse(asyncResult5)
        XCTAssertEqual(service.state, .unavailable)
        XCTAssertNil(service.draft)
        XCTAssertTrue(service.orderedNodes.isEmpty)
        let priorMethods = transport.methods
        let teamScope = WatchWorkflowDetailScope.capture(accountID: transport.accountID, teamID: "team-one")
        await service.load(id: "workflow-one", scope: teamScope)
        XCTAssertEqual(service.state, .unavailable)
        XCTAssertEqual(transport.methods, priorMethods)
    }

    // contract-test: supporting surface=gui.apple assertions=apple-watch.workflows.compact-editor
    func testSessionGenerationChangeRejectsPendingReadAndInvalidDraftDoesNotDispatch() async throws {
        let transport = try Transport()
        let service = transport.service()
        await service.load(id: "workflow-one", scope: transport.scope)
        service.beginEditing(nodeID: "ask")
        try change(service, field: ["config", "input", "prompt"], value: "")
        let asyncResult6 = await service.save()
        XCTAssertFalse(asyncResult6)
        XCTAssertEqual(service.saveError, .invalidDraft)
        XCTAssertEqual(transport.methods, [.get])
        let gate = Gate(); transport.getGate = gate
        let loading = Task { await service.load(id: "workflow-one", scope: transport.scope) }
        await gate.waitUntilEntered()
        WatchChatAccountLifecycle.invalidate()
        gate.release(); await loading.value
        XCTAssertEqual(service.state, .unavailable)
        XCTAssertTrue(service.orderedNodes.isEmpty)
    }

    // contract-test: supporting surface=gui.apple assertions=apple-watch.workflows.compact-editor
    func testOpaqueIDIsEncodedAsOnePathSegment() throws {
        XCTAssertEqual(try WatchWorkflowDetailService.path(id: "workflow/one?team_id=other"), "/v1/workflows/workflow%2Fone%3Fteam_id%3Dother")
    }

    private func change(_ service: WatchWorkflowDetailService, field: [String], value: String) throws {
        var draft = try XCTUnwrap(service.draft)
        let index = try XCTUnwrap(draft.fields.firstIndex(where: { $0.path == field }))
        draft.fields[index].value = value; service.draft = draft
    }
    @MainActor private final class Transport {
        var graph: WatchWorkflowGraph
        var accountID = WatchWorkflowDetailFixtures.accountID
        var scope: WatchWorkflowDetailScope { .capture(accountID: accountID) }
        var version = "fixture-v1"
        var methods: [HTTPMethod] = []
        var failGet = false
        var failPatch = false
        var ignorePatchGraph = false
        var patchBody: Data?
        var getGate: Gate?
        var patchGate: Gate?
        init() throws { graph = try WatchWorkflowDetailFixtures.graph() }
        func service() -> WatchWorkflowDetailService {
            WatchWorkflowDetailService(currentAccountID: { [self] in accountID }, request: request)
        }
        func request(method: HTTPMethod, path: String, body: Data?, scope: WatchWorkflowDetailScope,
                     validate: @escaping WatchWorkflowDetailService.Validate) async throws -> Data {
            try validate(); methods.append(method)
            let id = String(path.split(separator: "/").last!)
            if method == .get {
                if failGet { throw APIError.invalidResponse }
                if let gate = getGate { await gate.enter() }
            } else if method == .patch {
                patchBody = body
                if failPatch { throw APIError.invalidResponse }
                if let gate = patchGate { await gate.enter() }
                try validate()
                struct Patch: Decodable { let graph: WatchWorkflowGraph }
                let submitted = try JSONDecoder().decode(Patch.self, from: XCTUnwrap(body)).graph
                if !ignorePatchGraph { graph = submitted }
                version = "fixture-v2"
            } else { throw APIError.invalidResponse }
            try validate()
            return try WatchWorkflowDetailFixtures.response(id: id, graph: graph, version: version)
        }
    }
    @MainActor private final class Gate {
        private var entered = false
        private var waiting: CheckedContinuation<Void, Never>?
        private var parked: CheckedContinuation<Void, Never>?
        func enter() async {
            entered = true; waiting?.resume(); waiting = nil
            await withCheckedContinuation { parked = $0 }
        }
        func waitUntilEntered() async {
            if !entered { await withCheckedContinuation { waiting = $0 } }
        }
        func release() { parked?.resume(); parked = nil }
    }
}
