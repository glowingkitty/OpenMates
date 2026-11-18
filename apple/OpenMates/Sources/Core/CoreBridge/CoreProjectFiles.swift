// Create a new empty document, sheet, slide deck or code file in a Project
// folder through the Rust core. The core builds the blank content, encrypts it
// (embed key wrapped with the master key and the Project key) and uploads the
// embed with its Project link; nothing here builds content or touches keys.
// Web source: frontend/packages/ui/src/services/projectService.ts
//   `createProjectDocument` (ported to `work::Projects::create_document`).
// Specification: specifications/features/projects/specification.yml
// Assertions: projects.items.create-documents, storage.privacy.ciphertext-boundary

import Foundation

/// Kind of a new Project file; raw values are the core's wire names.
enum ProjectDocumentKind: String, CaseIterable, Sendable {
    case document, sheet, slides, code
}

/// A Project file the core created, ready to open.
struct CreatedProjectFile: Equatable, Sendable {
    let embedId: String
    let embedType: String
    let projectItemId: String
}

/// Why a Project file could not be created.
enum ProjectFileCreateError: Error, Equatable {
    /// No core (signed out, unit-test host or failed launch).
    case noCore
}

/// The core call behind the Project create menu; tests inject a fake.
@MainActor
protocol ProjectFileCreating: AnyObject, Sendable {
    /// Creates `kind` named `name` in `folderId` (Project root when nil) of `projectId`.
    func createProjectFile(projectId: String, teamId: String?, kind: ProjectDocumentKind,
                           name: String, folderId: String?) async throws -> CreatedProjectFile
}

/// The app's implementation: `ViewModelCore.createProjectDocument` through `CoreSession`.
@MainActor
final class CoreProjectFiles: ProjectFileCreating {
    private let sessionProvider: @MainActor () -> CoreSession?

    init(sessionProvider: @escaping @MainActor () -> CoreSession? = { CoreSession.shared }) {
        self.sessionProvider = sessionProvider
    }

    func createProjectFile(projectId: String, teamId: String?, kind: ProjectDocumentKind,
                           name: String, folderId: String?) async throws -> CreatedProjectFile {
        guard let session = sessionProvider() else { throw ProjectFileCreateError.noCore }
        let record = try await session.perform { core, cancellation in
            try await core.createProjectDocument(projectId: projectId, teamId: teamId,
                kind: kind.rawValue, name: name, folderId: folderId, cancellation: cancellation)
        }
        return CreatedProjectFile(embedId: record.embedId, embedType: record.embedType,
                                  projectItemId: record.projectItemId)
    }
}
