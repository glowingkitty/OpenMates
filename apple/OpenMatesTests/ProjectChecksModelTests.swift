import XCTest
@testable import OpenMates

/// Project Overview Checks model: load and action failures are shown, a successful
/// action reloads the Check from the core, and source groups count like web.
@MainActor
final class ProjectChecksModelTests: XCTestCase {
    private final class FakeLoader: ProjectChecksLoading {
        var checks: [ProjectCheck] = []
        var failList = false
        var failAction = false
        var shown: [String] = []
        var confirmed: [(String, ProjectCheckDecision)] = []

        func list(projectId: String, teamId: String?) async throws -> [ProjectCheck] {
            if failList { throw ProjectChecksError.noCore }
            return checks
        }
        func show(projectId: String, teamId: String?, checkId: String) async throws -> ProjectCheck {
            shown.append(checkId)
            guard let check = checks.first(where: { $0.id == checkId }) else { throw ProjectChecksError.notFound }
            return check
        }
        func startRun(projectId: String, teamId: String?, checkId: String) async throws {
            if failAction { throw ProjectChecksError.noCore }
        }
        func confirm(projectId: String, teamId: String?, checkId: String, bindingId: String,
                     decision: ProjectCheckDecision) async throws {
            if failAction { throw ProjectChecksError.noCore }
            confirmed.append((bindingId, decision))
        }
    }

    private func check(_ id: String, aggregate: String = "never_run", sources: [ProjectCheckSource] = []) -> ProjectCheck {
        ProjectCheck(id: id, title: "Check \(id)", description: nil, lifecycle: "ready", revisionNumber: 1,
                     aggregate: aggregate, stale: false, lastRunAt: nil, sources: sources)
    }

    private func source(_ id: String, _ kind: String, _ status: String?) -> ProjectCheckSource {
        ProjectCheckSource(id: id, kind: kind, role: "required", title: id, ref: "",
                           result: status.map { .init(status: $0, detail: nil, humanDecision: nil, testResultEmbedId: nil) })
    }

    // contract-test: supporting surface=gui.apple assertions=checks.surface.semantic-parity
    func testLoadShowsChecksAndFailureIsReported() async {
        let loader = FakeLoader()
        loader.checks = [check("a"), check("b")]
        let model = ProjectChecksModel(loader: loader, projectId: "p", teamId: nil)
        await model.load()
        XCTAssertEqual(model.items.map(\.id), ["a", "b"])
        XCTAssertFalse(model.loadFailed)

        loader.failList = true
        await model.load()
        XCTAssertTrue(model.loadFailed, "A failed list is shown, never swallowed")
    }

    // contract-test: supporting surface=gui.apple assertions=checks.human.explicit-confirmation
    func testConfirmReloadsTheCheckAndFailedActionIsReported() async {
        let loader = FakeLoader()
        loader.checks = [check("a", aggregate: "waiting_for_confirmation",
                               sources: [source("h", "human_confirmation", "waiting_for_confirmation")])]
        let model = ProjectChecksModel(loader: loader, projectId: "p", teamId: "team")
        await model.load()
        model.open("a")
        XCTAssertEqual(model.opened?.id, "a")
        XCTAssertTrue(model.opened?.sources.first?.awaitsHuman == true)

        await model.confirm("a", bindingId: "h", decision: .confirmed)
        XCTAssertEqual(loader.confirmed.map(\.0), ["h"])
        XCTAssertEqual(loader.shown, ["a"], "A successful action reloads the Check")
        XCTAssertFalse(model.actionFailed)

        loader.failAction = true
        await model.run("a")
        XCTAssertTrue(model.actionFailed)
        model.close()
        XCTAssertNil(model.openedId)
        XCTAssertFalse(model.actionFailed)
    }

    // contract-test: supporting surface=gui.apple assertions=checks.sources.grouped-multi-surface
    func testSourceGroupsFollowWebOrderAndCounts() {
        let c = check("a", sources: [
            source("1", "human_confirmation", "waiting_for_confirmation"),
            source("2", "unit", "passed"), source("3", "unit", "failed"),
            source("4", "deterministic_audit", "passed"), source("5", "e2e", nil),
        ])
        let groups = ProjectCheckGroupSummary.summaries(c)
        XCTAssertEqual(groups.map(\.id), ["e2e", "unit", "audit", "human"])
        XCTAssertEqual(groups[1].passed, 1)
        XCTAssertEqual(groups[1].failed, 1)
        XCTAssertEqual(groups[1].state, "failed")
        XCTAssertEqual(groups[0].state, "pending")
        XCTAssertEqual(groups[2].state, "passed")
    }
}
