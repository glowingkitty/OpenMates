// Synthetic Checks for the Projects preview (`--ui-test-project-checks`): one passed
// Check and one waiting on a human confirmation, mirroring web checkFixtures.ts.
// Run and Confirm/Reject update the rows locally; no account or network is used.
// Specification: specifications/features/checks/specification.yml
// Assertions: checks.surface.semantic-parity, checks.human.explicit-confirmation
#if DEBUG
import Foundation

@MainActor
final class ProjectChecksPreviewLoader: ProjectChecksLoading {
    static let launchArgument = "--ui-test-project-checks"
    static var enabled: Bool { ProcessInfo.processInfo.arguments.contains(launchArgument) }

    private var checks: [String: ProjectCheck]

    init() {
        let now = UInt64(Date().timeIntervalSince1970)
        let passed = ProjectCheck(
            id: "check-search", title: "Recipe search finds saved recipes",
            description: "Searching by ingredient lists every saved recipe that uses it.",
            lifecycle: "ready", revisionNumber: 2, aggregate: "passed", stale: false, lastRunAt: now - 3_600,
            sources: [
                .init(id: "src-e2e", kind: "e2e", role: "required", title: "Search end to end",
                      ref: "tests/recipe-search.spec.ts", result: .init(status: "passed", detail: nil, humanDecision: nil, testResultEmbedId: nil)),
                .init(id: "src-unit", kind: "unit", role: "supporting", title: "Ingredient matcher",
                      ref: "src/search.test.ts", result: .init(status: "passed", detail: nil, humanDecision: nil, testResultEmbedId: nil)),
            ])
        let waiting = ProjectCheck(
            id: "check-shopping", title: "Shopping list reads well on a phone",
            description: "The list stays readable and every item can be ticked off with one thumb.",
            lifecycle: "ready", revisionNumber: 1, aggregate: "waiting_for_confirmation", stale: false,
            lastRunAt: now - 600,
            sources: [
                .init(id: "src-audit", kind: "static_analysis", role: "required", title: "Layout audit",
                      ref: "audit/shopping-list", result: .init(status: "passed", detail: nil, humanDecision: nil, testResultEmbedId: nil)),
                .init(id: "src-human", kind: "human_confirmation", role: "required", title: "Try it on a phone",
                      ref: "Open the shopping list on a phone and tick off three items.",
                      result: .init(status: "waiting_for_confirmation", detail: nil, humanDecision: nil, testResultEmbedId: nil)),
            ])
        checks = [passed.id: passed, waiting.id: waiting]
    }

    func list(projectId: String, teamId: String?) async throws -> [ProjectCheck] {
        [checks["check-search"], checks["check-shopping"]].compactMap { $0 }
    }

    func show(projectId: String, teamId: String?, checkId: String) async throws -> ProjectCheck {
        guard let check = checks[checkId] else { throw ProjectChecksError.notFound }
        return check
    }

    func startRun(projectId: String, teamId: String?, checkId: String) async throws {
        guard let check = checks[checkId] else { return }
        checks[checkId] = replacing(check, aggregate: "running", sources: check.sources)
    }

    func confirm(projectId: String, teamId: String?, checkId: String, bindingId: String,
                 decision: ProjectCheckDecision) async throws {
        guard let check = checks[checkId] else { return }
        let status = decision == .confirmed ? "passed" : "failed"
        let sources = check.sources.map { source in
            source.id == bindingId
                ? ProjectCheckSource(id: source.id, kind: source.kind, role: source.role, title: source.title, ref: source.ref,
                                     result: .init(status: status, detail: nil, humanDecision: decision.rawValue, testResultEmbedId: nil))
                : source
        }
        checks[checkId] = replacing(check, aggregate: status, sources: sources)
    }

    private func replacing(_ check: ProjectCheck, aggregate: String, sources: [ProjectCheckSource]) -> ProjectCheck {
        ProjectCheck(id: check.id, title: check.title, description: check.description, lifecycle: check.lifecycle,
                     revisionNumber: check.revisionNumber, aggregate: aggregate, stale: check.stale,
                     lastRunAt: UInt64(Date().timeIntervalSince1970), sources: sources)
    }
}
#endif
