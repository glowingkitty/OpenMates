import Foundation

// Thin async wrapper over the core's Project timeline and whole-commit restore.
// Plan: project-timeline. Logic (path recovery, restore, history) lives in Rust.

struct ProjectTimelineCommitFile: Equatable, Sendable {
    let path: String?
    let version: UInt64
    /// "added", "modified" or "unchanged"; nil when no older commit is known.
    let change: String?
}

struct ProjectTimelineCommit: Equatable, Sendable {
    let id: String
    let message: String
    let restoredFrom: String?
    let files: [ProjectTimelineCommitFile]
}

struct ProjectTimelineEntry: Identifiable, Equatable, Sendable {
    let id: String
    /// "commit", "file_version" or "file_operation".
    let kind: String
    let createdAt: UInt64
    /// "user" or "assistant".
    let author: String
    let path: String?
    let version: UInt64?
    let action: String?
    let restoredFromVersion: UInt64?
    let commit: ProjectTimelineCommit?
}

struct ProjectTimelinePage: Equatable, Sendable {
    let entries: [ProjectTimelineEntry]
    let nextCursor: String?
}

enum ProjectTimelineError: Error, Equatable {
    case noCore
}

@MainActor
protocol ProjectTimelineLoading: AnyObject, Sendable {
    func page(projectId: String, teamId: String?, before: String?) async throws -> ProjectTimelinePage
    func restore(projectId: String, teamId: String?, commitId: String) async throws
}

@MainActor
final class CoreProjectTimeline: ProjectTimelineLoading {
    private let sessionProvider: @MainActor () -> CoreSession?

    init(sessionProvider: @escaping @MainActor () -> CoreSession? = { CoreSession.shared }) {
        self.sessionProvider = sessionProvider
    }

    func page(projectId: String, teamId: String?, before: String?) async throws -> ProjectTimelinePage {
        guard let session = sessionProvider() else { throw ProjectTimelineError.noCore }
        let record = try await session.perform { core, cancellation in
            try await core.projectTimeline(projectId: projectId, teamId: teamId, limit: 30,
                                           before: before, cancellation: cancellation)
        }
        return ProjectTimelinePage(entries: record.entries.map(Self.entry), nextCursor: record.nextCursor)
    }

    func restore(projectId: String, teamId: String?, commitId: String) async throws {
        guard let session = sessionProvider() else { throw ProjectTimelineError.noCore }
        let operationId = UUID().uuidString.lowercased()
        _ = try await session.perform { core, cancellation in
            try await core.restoreProjectCommit(projectId: projectId, teamId: teamId, commitId: commitId,
                                                operationId: operationId, cancellation: cancellation)
        }
    }

    nonisolated private static func entry(_ record: ProjectTimelineEntryRecord) -> ProjectTimelineEntry {
        ProjectTimelineEntry(
            id: record.id, kind: record.kind, createdAt: record.createdAt, author: record.author,
            path: record.path, version: record.version, action: record.action,
            restoredFromVersion: record.restoredFromVersion,
            commit: record.commit.map { commit in
                ProjectTimelineCommit(
                    id: commit.commitId, message: commit.message, restoredFrom: commit.restoredFromCommitId,
                    files: commit.files.map {
                        ProjectTimelineCommitFile(path: $0.path, version: $0.version, change: $0.change)
                    })
            })
    }
}
