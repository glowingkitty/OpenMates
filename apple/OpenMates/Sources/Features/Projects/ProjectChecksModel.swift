// Project Overview Checks: presentation state of the Checks section. The Rust core
// lists, decrypts and runs Checks (`CoreProjectChecks`); this model only keeps the
// loaded rows, the opened Check and the load/action failures, which are shown and
// never swallowed (web: ProjectChecksPanel.svelte `loadFailed` / `actionFailed`).
// Specification: specifications/features/checks/specification.yml
// Assertions: checks.surface.semantic-parity, checks.human.explicit-confirmation
// ─── Web source ─────────────────────────────────────────────────────
// Svelte:  frontend/packages/ui/src/components/projects/ProjectChecksPanel.svelte
//          frontend/packages/ui/src/components/embeds/checks/checkGrouping.ts
// ────────────────────────────────────────────────────────────────────
import Foundation

/// Latest result of one source of a Check, already mapped to the display status by the core.
struct ProjectCheckSourceResult: Equatable, Sendable {
    let status: String
    let detail: String?
    let humanDecision: String?
    let testResultEmbedId: String?
}

/// One source (test, audit, AI question or human confirmation) of a Check's current revision.
struct ProjectCheckSource: Identifiable, Equatable, Sendable {
    let id: String
    let kind: String
    let role: String
    let title: String
    let ref: String
    let result: ProjectCheckSourceResult?

    var isHuman: Bool { kind == "human_confirmation" }
    var awaitsHuman: Bool { isHuman && (result == nil || result?.status == "waiting_for_confirmation") }
}

/// A Check as the Project Overview shows it.
struct ProjectCheck: Identifiable, Equatable, Sendable {
    let id: String
    let title: String
    let description: String?
    let lifecycle: String
    let revisionNumber: UInt64
    /// `never_run`, `queued`, `running`, `passed`, `failed`, `error`, `blocked`, `waiting_for_confirmation`, `cancelled`.
    let aggregate: String
    let stale: Bool
    /// Unix seconds of the latest run, nil when it never ran.
    let lastRunAt: UInt64?
    let sources: [ProjectCheckSource]
}

/// Human decision on a `human_confirmation` source.
enum ProjectCheckDecision: String, Sendable {
    case confirmed
    case rejected
}

/// Source groups in web order (`SOURCE_GROUP_ORDER`), with their pass/fail/pending counts.
struct ProjectCheckGroupSummary: Identifiable, Equatable {
    let id: String
    let total: Int
    let passed: Int
    let failed: Int
    let pending: Int

    static let order = ["e2e", "unit", "integration", "audit", "ai", "human"]

    static func group(of kind: String) -> String {
        switch kind {
        case "static_analysis", "deterministic_audit": return "audit"
        case "ai_evaluation": return "ai"
        case "human_confirmation": return "human"
        default: return kind
        }
    }

    static func summaries(_ check: ProjectCheck) -> [ProjectCheckGroupSummary] {
        order.compactMap { id in
            let sources = check.sources.filter { group(of: $0.kind) == id }
            guard !sources.isEmpty else { return nil }
            let passed = sources.filter { $0.result?.status == "passed" }.count
            let failed = sources.filter { ["failed", "error"].contains($0.result?.status ?? "") }.count
            return ProjectCheckGroupSummary(id: id, total: sources.count, passed: passed, failed: failed,
                                            pending: sources.count - passed - failed)
        }
    }

    /// "passed", "failed" or "pending", like the web chip state.
    var state: String { failed > 0 ? "failed" : pending > 0 ? "pending" : "passed" }
}

enum ProjectChecksError: Error, Equatable {
    case noCore
    case notFound
}

@MainActor
protocol ProjectChecksLoading: AnyObject {
    func list(projectId: String, teamId: String?) async throws -> [ProjectCheck]
    func show(projectId: String, teamId: String?, checkId: String) async throws -> ProjectCheck
    func startRun(projectId: String, teamId: String?, checkId: String) async throws
    func confirm(projectId: String, teamId: String?, checkId: String, bindingId: String,
                 decision: ProjectCheckDecision) async throws
}

@MainActor
final class ProjectChecksModel: ObservableObject {
    @Published private(set) var items: [ProjectCheck] = []
    @Published private(set) var loadFailed = false
    @Published private(set) var actionFailed = false
    @Published private(set) var busy = false
    @Published var openedId: String?

    private let loader: ProjectChecksLoading
    private let projectId: String
    private let teamId: String?
    private var generation = 0

    init(loader: ProjectChecksLoading, projectId: String, teamId: String?) {
        self.loader = loader
        self.projectId = projectId
        self.teamId = teamId
    }

    var opened: ProjectCheck? { items.first { $0.id == openedId } }

    func load() async {
        generation += 1
        let mine = generation
        loadFailed = false
        do {
            let loaded = try await loader.list(projectId: projectId, teamId: teamId)
            if mine == generation { items = loaded }
        } catch {
            NativeDiagnostics.warning("project_checks_list_failed", category: "projects")
            if mine == generation { loadFailed = true }
        }
    }

    func open(_ id: String) {
        actionFailed = false
        openedId = id
    }

    func close() {
        openedId = nil
        actionFailed = false
    }

    func run(_ checkId: String) async {
        await act(checkId) { [loader, projectId, teamId] in
            try await loader.startRun(projectId: projectId, teamId: teamId, checkId: checkId)
        }
    }

    func confirm(_ checkId: String, bindingId: String, decision: ProjectCheckDecision) async {
        await act(checkId) { [loader, projectId, teamId] in
            try await loader.confirm(projectId: projectId, teamId: teamId, checkId: checkId,
                                     bindingId: bindingId, decision: decision)
        }
    }

    private func act(_ checkId: String, _ task: @escaping () async throws -> Void) async {
        guard !busy else { return }
        busy = true
        actionFailed = false
        defer { busy = false }
        do {
            try await task()
            let fresh = try await loader.show(projectId: projectId, teamId: teamId, checkId: checkId)
            items = items.map { $0.id == checkId ? fresh : $0 }
        } catch {
            NativeDiagnostics.warning("project_checks_action_failed", category: "projects")
            actionFailed = true
        }
    }
}

/// Keeps one Checks model per selected Project so the Overview section and the
/// page-level detail sheet share it. Not published: the models publish themselves.
@MainActor
final class ProjectChecksHost: ObservableObject {
    private var current: (key: String, model: ProjectChecksModel)?

    func model(projectId: String, teamId: String?, loader: () -> ProjectChecksLoading) -> ProjectChecksModel {
        let key = "\(teamId ?? "personal")/\(projectId)"
        if let current, current.key == key { return current.model }
        let model = ProjectChecksModel(loader: loader(), projectId: projectId, teamId: teamId)
        current = (key, model)
        return model
    }
}
