// Project Overview Specifications: presentation state of the Specifications section and
// reader. The Rust core lists, decrypts and approves Specifications
// (`CoreProjectSpecifications`); this model keeps the loaded cards, the opened revision
// and the load/action failures, which are shown and never swallowed
// (web: ProjectSpecificationsPanel.svelte `loadFailed` / `actionFailed`).
// Specification: specifications/features/specifications/specification.yml
// Assertions: contracts.revision.exact-approval, contracts.surface.semantic-parity, contracts.ui.human-readable-default
// ─── Web source ─────────────────────────────────────────────────────
// Svelte:  frontend/packages/ui/src/components/projects/ProjectSpecificationsPanel.svelte
//          frontend/packages/ui/src/components/embeds/specifications/SpecificationRevision.ts
//          frontend/packages/ui/src/components/embeds/specifications/SpecificationDocument.ts
// ────────────────────────────────────────────────────────────────────
import Foundation

/// Card of one Specification (web `SpecificationListItem`).
struct ProjectSpecificationListItem: Identifiable, Equatable, Sendable {
    let id: String
    let title: String
    let kind: String
    /// "approved" or "draft".
    let status: String
    let revisionNumber: UInt64
    /// Unix seconds; 0 when unknown.
    let updatedAt: UInt64
    let requirementCount: UInt64
    let proofPassed: UInt64
    let proofOpen: UInt64
    let proofStale: UInt64
}

struct ProjectSpecRequirement: Identifiable, Equatable, Sendable {
    let id: String
    let statement: String
    let appliesTo: [String]
    let example: String
    /// "passed", "open" or "stale"; nil when no Check projection exists (reads as not proven).
    let proofState: String?
    let proofTitle: String?
    let proofExplanation: String?
}

struct ProjectSpecFlow: Identifiable, Equatable, Sendable {
    let id: String
    let title: String
    /// "user_flow" or "edge_case".
    let kind: String
    let steps: [String]
}

struct ProjectSpecModelField: Equatable, Sendable {
    let name: String
    let type: String
    let description: String
}

struct ProjectSpecModel: Identifiable, Equatable, Sendable {
    let id: String
    let description: String
    let fields: [ProjectSpecModelField]
}

struct ProjectSpecChapter: Identifiable, Equatable, Sendable {
    let id: String
    /// Empty for the trailing section when the document has no chapters.
    let title: String
    let introduction: String
    let requirementIds: [String]
    let flowIds: [String]
    let modelIds: [String]
}

struct ProjectSpecRelated: Equatable, Sendable {
    let title: String
    let role: String
    let relation: String
}

/// Readable document of one revision (web `SpecificationDocument`).
struct ProjectSpecificationDocument: Equatable, Sendable {
    let title: String
    let project: String
    let category: String
    let summary: String
    let outcome: String
    let role: String
    let scopeIncluded: [String]
    let scopeExcluded: [String]
    let assumptions: [String]
    let designDecisions: [String]
    let chapters: [ProjectSpecChapter]
    let requirements: [ProjectSpecRequirement]
    let flows: [ProjectSpecFlow]
    let models: [ProjectSpecModel]
    let related: [ProjectSpecRelated]

    /// Chapters as shown: authored chapters plus one trailing section for the requirements,
    /// flows and models no chapter references (web `displayChapters`), so nothing disappears.
    func displayChapters(otherTitle: String) -> [ProjectSpecChapter] {
        let usedRequirements = Set(chapters.flatMap(\.requirementIds))
        let usedFlows = Set(chapters.flatMap(\.flowIds))
        let usedModels = Set(chapters.flatMap(\.modelIds))
        let rest = ProjectSpecChapter(
            id: "unassigned", title: chapters.isEmpty ? "" : otherTitle, introduction: "",
            requirementIds: requirements.map(\.id).filter { !usedRequirements.contains($0) },
            flowIds: flows.map(\.id).filter { !usedFlows.contains($0) },
            modelIds: models.map(\.id).filter { !usedModels.contains($0) })
        let hasRest = !rest.requirementIds.isEmpty || !rest.flowIds.isEmpty || !rest.modelIds.isEmpty
        return hasRest ? chapters + [rest] : chapters
    }
}

/// One revision in the history (web `SpecificationRevisionSummary`).
struct ProjectSpecificationRevision: Identifiable, Equatable, Sendable {
    let id: String
    let number: UInt64
    /// Unix seconds; 0 when unknown.
    let createdAt: UInt64
    let summary: String
    /// "approved", "draft" or "superseded".
    let status: String
    let contentHash: String
}

/// One opened Specification: the viewed revision's document, the history and approval state.
struct ProjectSpecificationOpened: Equatable, Sendable {
    let id: String
    let document: ProjectSpecificationDocument
    let revisions: [ProjectSpecificationRevision]
    let currentRevisionId: String
    let viewedRevisionId: String
    let viewedContentHash: String
    /// "draft", "approved" or "stale" (approved earlier, changed afterwards).
    let approvalState: String
    let approvedRevisionId: String?
    let approvedAt: UInt64?

    var viewed: ProjectSpecificationRevision? { revisions.first { $0.id == viewedRevisionId } }
    var approvedRevision: ProjectSpecificationRevision? { revisions.first { $0.id == approvedRevisionId } }
    var isCurrent: Bool { viewedRevisionId == currentRevisionId }
    var isApproved: Bool { approvalState != "draft" && approvedRevisionId == viewedRevisionId }
    /// Only the current, not yet approved revision can be approved (web `canApprove`).
    var canApprove: Bool { viewed != nil && isCurrent && !isApproved }
    var sortedRevisions: [ProjectSpecificationRevision] { revisions.sorted { $0.number > $1.number } }
}

enum ProjectSpecificationsError: Error, Equatable {
    case noCore
    case notFound
}

@MainActor
protocol ProjectSpecificationsLoading: AnyObject {
    func list(projectId: String, teamId: String?) async throws -> [ProjectSpecificationListItem]
    func open(projectId: String, teamId: String?, specificationId: String, revisionId: String?) async throws
        -> ProjectSpecificationOpened
    func approve(projectId: String, teamId: String?, specificationId: String, revisionId: String,
                 contentHash: String) async throws
}

@MainActor
final class ProjectSpecificationsModel: ObservableObject {
    @Published private(set) var items: [ProjectSpecificationListItem] = []
    @Published private(set) var loaded = false
    @Published private(set) var loadFailed = false
    @Published private(set) var actionFailed = false
    @Published private(set) var busy = false
    @Published private(set) var opened: ProjectSpecificationOpened?

    private let loader: ProjectSpecificationsLoading
    private let projectId: String
    private let teamId: String?
    private var generation = 0

    init(loader: ProjectSpecificationsLoading, projectId: String, teamId: String?) {
        self.loader = loader
        self.projectId = projectId
        self.teamId = teamId
    }

    func load() async {
        generation += 1
        let mine = generation
        loadFailed = false
        do {
            let fresh = try await loader.list(projectId: projectId, teamId: teamId)
            if mine == generation { items = fresh; loaded = true }
        } catch {
            NativeDiagnostics.warning("project_specifications_list_failed", category: "projects")
            if mine == generation { loadFailed = true }
        }
    }

    /// Opens a Specification at a revision (default: the current one).
    func open(_ id: String, revisionId: String? = nil) async {
        actionFailed = false
        busy = true
        defer { busy = false }
        do {
            opened = try await loader.open(projectId: projectId, teamId: teamId, specificationId: id,
                                           revisionId: revisionId)
        } catch {
            NativeDiagnostics.warning("project_specifications_open_failed", category: "projects")
            actionFailed = true
        }
    }

    func selectRevision(_ revisionId: String) async {
        guard let opened, revisionId != opened.viewedRevisionId else { return }
        await open(opened.id, revisionId: revisionId)
    }

    /// Approves exactly the viewed revision and its content hash, then reloads it and the cards.
    func approveViewed() async {
        guard let opened, opened.canApprove, let viewed = opened.viewed, !busy else { return }
        actionFailed = false
        busy = true
        do {
            try await loader.approve(projectId: projectId, teamId: teamId, specificationId: opened.id,
                                     revisionId: viewed.id, contentHash: viewed.contentHash)
            busy = false
        } catch {
            busy = false
            NativeDiagnostics.warning("project_specifications_approve_failed", category: "projects")
            actionFailed = true
            return
        }
        await open(opened.id, revisionId: viewed.id)
        await load()
    }

    func close() {
        opened = nil
        actionFailed = false
    }
}

/// Keeps one Specifications model per selected Project so the Overview section and the
/// page-level reader share it.
@MainActor
final class ProjectSpecificationsHost: ObservableObject {
    private var current: (key: String, model: ProjectSpecificationsModel)?

    func model(projectId: String, teamId: String?,
               loader: () -> ProjectSpecificationsLoading) -> ProjectSpecificationsModel {
        let key = "\(teamId ?? "personal")/\(projectId)"
        if let current, current.key == key { return current.model }
        let model = ProjectSpecificationsModel(loader: loader(), projectId: projectId, teamId: teamId)
        current = (key, model)
        return model
    }
}
