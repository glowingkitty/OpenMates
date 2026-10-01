// Focused graph-editing contract tests. These use synthetic workflow data only.

import XCTest
@testable import OpenMates

final class WorkflowGraphEditingTests: XCTestCase {
    // contract-test: supporting surface=gui.apple assertions=workflows.control.check
    func testInsertingIntoOneCheckBranchPreservesTheOtherBranchAndContinuation() throws {
        let graph = fixtureGraph()
        let action = node("added", .appSkillAction)

        let changed = try WorkflowGraphEditing.inserting(
            action, into: graph, after: "check", branch: "yes"
        )

        XCTAssertTrue(changed.nodes.contains(where: { $0.id == "added" }))
        XCTAssertTrue(changed.edges.contains(where: {
            $0.from == "check" && $0.to == "added" && $0.branch == "yes"
        }))
        XCTAssertTrue(changed.edges.contains(where: {
            $0.from == "added" && $0.to == "yes" && $0.branch == nil
        }))
        XCTAssertTrue(changed.edges.contains(where: {
            $0.from == "check" && $0.to == "no" && $0.branch == "no"
        }))
        XCTAssertTrue(changed.edges.contains(where: {
            $0.from == "check" && $0.to == "finish" && $0.branch == nil
        }))
    }

    // contract-test: supporting surface=gui.apple assertions=workflows.composition.earlier-action-reference
    func testRemovingReferencedActionRejectsTheEdit() {
        var graph = fixtureGraph()
        graph = WorkflowGraph(
            version: graph.version, triggerNodeId: graph.triggerNodeId,
            nodes: graph.nodes.map { node in
                guard node.id == "finish" else { return node }
                return WorkflowNode(
                    id: node.id, type: node.type, title: node.title,
                    config: ["message": AnyCodable("{{steps.yes.answer}}")],
                    inputMapping: node.inputMapping, ui: node.ui
                )
            }, edges: graph.edges, variables: graph.variables,
            limits: graph.limits, uiLayout: graph.uiLayout
        )

        XCTAssertThrowsError(try WorkflowGraphEditing.removing("yes", from: graph)) { error in
            XCTAssertEqual(error as? WorkflowGraphEditError, .dependentNodes(["finish"]))
        }
    }

    // contract-test: supporting surface=gui.apple assertions=workflows.control.check
    func testRemovingSingleActionReconnectsItsBranch() throws {
        let changed = try WorkflowGraphEditing.removing("yes", from: fixtureGraph())

        XCTAssertFalse(changed.nodes.contains(where: { $0.id == "yes" }))
        XCTAssertTrue(changed.edges.contains(where: {
            $0.from == "check" && $0.to == "finish" && $0.branch == "yes"
        }))
        XCTAssertTrue(changed.edges.contains(where: {
            $0.from == "check" && $0.to == "no" && $0.branch == "no"
        }))
    }

    // contract-test: supporting surface=gui.apple assertions=workflows.mvp.steps
    func testRemovingTriggerReturnsAValidUnscheduledDraft() throws {
        let changed = try WorkflowGraphEditing.removing("trigger", from: fixtureGraph())
        XCTAssertEqual(changed.triggerNodeId, "")
        XCTAssertFalse(changed.nodes.contains(where: { $0.id == "trigger" }))
        XCTAssertFalse(changed.edges.contains(where: { $0.from == "trigger" || $0.to == "trigger" }))
    }

    // contract-test: supporting surface=gui.apple assertions=workflows.activation.reachable-side-effect
    func testAddingActionToBlankDraftDoesNotMislabelItAsTrigger() throws {
        let blank = WorkflowGraph(version: 1, triggerNodeId: "", nodes: [], edges: [],
                                  variables: [:], limits: [:], uiLayout: [:])
        let changed = try WorkflowGraphEditing.inserting(node("action", .appSkillAction), into: blank, after: nil)
        XCTAssertEqual(changed.triggerNodeId, "")
        XCTAssertEqual(changed.nodes.map(\.id), ["action"])
    }

    // contract-test: supporting surface=gui.apple assertions=workflows.mvp.steps
    func testAddingTriggerAfterActionConnectsExistingRoot() throws {
        let blank = WorkflowGraph(version: 1, triggerNodeId: "", nodes: [node("action", .appSkillAction)],
                                  edges: [], variables: [:], limits: [:], uiLayout: [:])
        let changed = try WorkflowGraphEditing.inserting(node("trigger", .scheduleTrigger), into: blank, after: nil)
        XCTAssertEqual(changed.triggerNodeId, "trigger")
        XCTAssertTrue(changed.edges.contains { $0.from == "trigger" && $0.to == "action" })
    }

    private func fixtureGraph() -> WorkflowGraph {
        WorkflowGraph(
            version: 2, triggerNodeId: "trigger",
            nodes: [
                node("trigger", .scheduleTrigger), node("check", .decision),
                node("yes", .appSkillAction), node("no", .appSkillAction),
                node("finish", .sendNotification),
            ],
            edges: [
                WorkflowEdge(from: "trigger", to: "check", branch: nil),
                WorkflowEdge(from: "check", to: "yes", branch: "yes"),
                WorkflowEdge(from: "check", to: "no", branch: "no"),
                WorkflowEdge(from: "check", to: "finish", branch: nil),
                WorkflowEdge(from: "yes", to: "finish", branch: nil),
                WorkflowEdge(from: "no", to: "finish", branch: nil),
            ], variables: [:], limits: [:], uiLayout: [:]
        )
    }

    private func node(_ id: String, _ type: WorkflowNodeType) -> WorkflowNode {
        WorkflowNode(id: id, type: type, title: nil, config: [:], inputMapping: [:], ui: [:])
    }
}
