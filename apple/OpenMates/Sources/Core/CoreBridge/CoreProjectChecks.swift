import Foundation

// Thin async wrapper over the core's Project Checks: list, show, start a run and
// record a human decision. Decryption, result mapping, aggregate and stale state
// come from Rust (`view_model/project_checks.rs`); this only maps records.
// Specification: specifications/features/checks/specification.yml
// Assertions: checks.surface.semantic-parity, checks.human.explicit-confirmation

@MainActor
final class CoreProjectChecks: ProjectChecksLoading {
    private let sessionProvider: @MainActor () -> CoreSession?
    /// Latest run per Check, from the last list/show; a human decision belongs to that run.
    private var latestRunIds: [String: String] = [:]

    init(sessionProvider: @escaping @MainActor () -> CoreSession? = { CoreSession.shared }) {
        self.sessionProvider = sessionProvider
    }

    func list(projectId: String, teamId: String?) async throws -> [ProjectCheck] {
        guard let session = sessionProvider() else { throw ProjectChecksError.noCore }
        let records = try await session.perform { core, cancellation in
            try await core.projectChecksList(projectId: projectId, teamId: teamId, cancellation: cancellation)
        }
        return records.map(remember)
    }

    func show(projectId: String, teamId: String?, checkId: String) async throws -> ProjectCheck {
        guard let session = sessionProvider() else { throw ProjectChecksError.noCore }
        let record = try await session.perform { core, cancellation in
            try await core.projectCheckShow(projectId: projectId, teamId: teamId, checkId: checkId,
                                            cancellation: cancellation)
        }
        return remember(record)
    }

    func startRun(projectId: String, teamId: String?, checkId: String) async throws {
        guard let session = sessionProvider() else { throw ProjectChecksError.noCore }
        _ = try await session.perform { core, cancellation in
            try await core.projectCheckStartRun(projectId: projectId, teamId: teamId, checkId: checkId,
                                                cancellation: cancellation)
        }
    }

    func confirm(projectId: String, teamId: String?, checkId: String, bindingId: String,
                 decision: ProjectCheckDecision) async throws {
        guard let session = sessionProvider() else { throw ProjectChecksError.noCore }
        guard let runId = latestRunIds[checkId] else { throw ProjectChecksError.notFound }
        try await session.perform { core, cancellation in
            try await core.projectCheckConfirmHuman(projectId: projectId, teamId: teamId, checkId: checkId,
                                                    runId: runId, bindingId: bindingId,
                                                    decision: decision.rawValue, note: nil,
                                                    cancellation: cancellation)
        }
    }

    private func remember(_ record: ProjectCheckDetailRecord) -> ProjectCheck {
        latestRunIds[record.check.checkId] = record.latestRun?.runId
        return Self.check(record)
    }

    nonisolated static func check(_ record: ProjectCheckDetailRecord) -> ProjectCheck {
        let results = Dictionary((record.latestRun?.sourceResults ?? []).map { ($0.bindingId, $0) },
                                 uniquingKeysWith: { first, _ in first })
        return ProjectCheck(
            id: record.check.checkId, title: record.check.title, description: record.check.description,
            lifecycle: record.check.status, revisionNumber: record.revision.revisionNumber,
            aggregate: record.aggregate, stale: record.stale,
            lastRunAt: record.latestRun.map { $0.finishedAt ?? $0.createdAt },
            sources: record.revision.sources.map { source in
                ProjectCheckSource(
                    id: source.bindingId, kind: source.kind, role: source.role, title: source.title,
                    ref: source.reference,
                    result: results[source.bindingId].map {
                        ProjectCheckSourceResult(status: $0.displayStatus, detail: $0.detail,
                                                 humanDecision: $0.humanDecision,
                                                 testResultEmbedId: $0.testResultEmbedId)
                    })
            })
    }
}
