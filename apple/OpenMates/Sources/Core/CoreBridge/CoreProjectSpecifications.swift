import Foundation

// Thin async wrapper over the core's Project Specifications: list, open a revision with
// its history and approval state, and approve an exact revision by content hash.
// Decryption, the Project key unwrap, approval state and the hash check come from Rust
// (`view_model/project_specifications.rs`); this only maps records.
// Specification: specifications/features/specifications/specification.yml
// Assertions: contracts.revision.exact-approval, contracts.surface.semantic-parity

@MainActor
final class CoreProjectSpecifications: ProjectSpecificationsLoading {
    private let sessionProvider: @MainActor () -> CoreSession?

    init(sessionProvider: @escaping @MainActor () -> CoreSession? = { CoreSession.shared }) {
        self.sessionProvider = sessionProvider
    }

    func list(projectId: String, teamId: String?) async throws -> [ProjectSpecificationListItem] {
        guard let session = sessionProvider() else { throw ProjectSpecificationsError.noCore }
        let records = try await session.perform { core, cancellation in
            try await core.projectSpecificationsList(projectId: projectId, teamId: teamId, cancellation: cancellation)
        }
        return records.map(Self.item)
    }

    func open(projectId: String, teamId: String?, specificationId: String, revisionId: String?) async throws
        -> ProjectSpecificationOpened {
        guard let session = sessionProvider() else { throw ProjectSpecificationsError.noCore }
        let record = try await session.perform { core, cancellation in
            try await core.projectSpecificationOpen(projectId: projectId, teamId: teamId,
                                                    specificationId: specificationId, revisionId: revisionId,
                                                    cancellation: cancellation)
        }
        return Self.opened(record)
    }

    func approve(projectId: String, teamId: String?, specificationId: String, revisionId: String,
                 contentHash: String) async throws {
        guard let session = sessionProvider() else { throw ProjectSpecificationsError.noCore }
        try await session.perform { core, cancellation in
            try await core.projectSpecificationApprove(projectId: projectId, teamId: teamId,
                                                       specificationId: specificationId, revisionId: revisionId,
                                                       contentHash: contentHash, cancellation: cancellation)
        }
    }

    nonisolated static func item(_ r: ProjectSpecificationListItemRecord) -> ProjectSpecificationListItem {
        ProjectSpecificationListItem(id: r.specificationId, title: r.title, kind: r.kind, status: r.status,
                                     revisionNumber: r.revisionNumber, updatedAt: r.updatedAt,
                                     requirementCount: r.requirementCount, proofPassed: r.proofPassed,
                                     proofOpen: r.proofOpen, proofStale: r.proofStale)
    }

    nonisolated static func opened(_ r: ProjectSpecificationOpenedRecord) -> ProjectSpecificationOpened {
        let d = r.document
        let document = ProjectSpecificationDocument(
            title: d.title, project: d.project, category: d.category, summary: d.summary, outcome: d.outcome,
            role: d.role, scopeIncluded: d.scopeIncluded, scopeExcluded: d.scopeExcluded,
            assumptions: d.assumptions, designDecisions: d.designDecisions,
            chapters: d.chapters.map {
                ProjectSpecChapter(id: $0.id, title: $0.title, introduction: $0.introduction,
                                   requirementIds: $0.requirementIds, flowIds: $0.flowIds, modelIds: $0.modelIds)
            },
            requirements: d.requirements.map {
                ProjectSpecRequirement(id: $0.id, statement: $0.statement, appliesTo: $0.appliesTo, example: $0.example,
                                       proofState: $0.proofState, proofTitle: $0.proofTitle,
                                       proofExplanation: $0.proofExplanation)
            },
            flows: d.flows.map { ProjectSpecFlow(id: $0.id, title: $0.title, kind: $0.kind, steps: $0.steps) },
            models: d.models.map { model in
                ProjectSpecModel(id: model.id, description: model.description,
                                 fields: model.fields.map {
                                     ProjectSpecModelField(name: $0.name, type: $0.fieldType, description: $0.description)
                                 })
            },
            related: d.related.map { ProjectSpecRelated(title: $0.title, role: $0.role, relation: $0.relation) })
        return ProjectSpecificationOpened(
            id: r.specificationId, document: document,
            revisions: r.revisions.map {
                ProjectSpecificationRevision(id: $0.revisionId, number: $0.revisionNumber, createdAt: $0.createdAt,
                                             summary: $0.summary, status: $0.status, contentHash: $0.contentHash)
            },
            currentRevisionId: r.currentRevisionId, viewedRevisionId: r.viewedRevisionId,
            viewedContentHash: r.viewedContentHash, approvalState: r.approvalState,
            approvedRevisionId: r.approvedRevisionId, approvedAt: r.approvedAt)
    }
}
