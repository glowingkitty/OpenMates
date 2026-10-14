// Web source: frontend/packages/ui/src/components/embeds/projects/projectReferenceData.ts
//             frontend/packages/ui/src/components/embeds/projects/ProjectReferenceEmbedPreview.svelte
// Specification: specifications/features/chats/specification.yml
// Assertions: chats.surface.semantic-parity, chats.rendering.assistant-document-convergence
// Specification: specifications/features/projects/specification.yml
// Assertions: projects.files.connected-embed-previews, projects.access.explicit-context
import Foundation
import CoreFoundation

struct ProjectFileReference: Equatable, Identifiable, Sendable {
    let projectID: String
    let projectName: String
    let teamID: String?
    let sourceID: String?
    let embedID: String?
    let path: String
    let line: Int?
    let index: Int
    var id: String { "\(projectID):\(sourceID ?? embedID ?? ""):\(path):\(index)" }
}

struct ProjectReferenceEmbedModel {
    let references: [ProjectFileReference]
    let query: String?
    let projectName: String
    let skillID: String
    let status: EmbedStatus

    init(embed: EmbedRecord) {
        let data = embed.rawData ?? [:]
        let raw = data.mapValues(\.value)
        let rows = raw["results"] as? [Any] ?? []
        references = rows.enumerated().compactMap { index, row in
            guard let row = row as? [String: Any] else { return nil }
            guard let project = Self.text(row["project_id"]) ?? Self.text(raw["project_id"]),
                  let path = Self.text(row["path"]),
                  Self.text(row["source_id"]) != nil || Self.text(row["embed_id"]) != nil else { return nil }
            let line = (row["line"] as? NSNumber).flatMap { value -> Int? in
                guard CFGetTypeID(value) != CFBooleanGetTypeID(), value.doubleValue.isFinite,
                      value.doubleValue > 0, value.doubleValue < Double(Int.max),
                      value.doubleValue.rounded(.towardZero) == value.doubleValue else { return nil }
                return value.intValue
            }
            return ProjectFileReference(projectID: project,
                projectName: Self.text(row["project_name"]) ?? Self.text(raw["project_name"]) ?? "",
                teamID: Self.text(row["team_id"]) ?? Self.text(raw["team_id"]),
                sourceID: Self.text(row["source_id"]), embedID: Self.text(row["embed_id"]),
                path: path, line: line, index: index)
        }
        query = Self.text(raw["query"]) ?? Self.text(raw["path"]) ?? Self.text(raw["file_path"])
            ?? AppSkillInputPreviewModel(embed: embed).text
        projectName = references.first?.projectName ?? Self.text(raw["project_name"]) ?? ""
        skillID = (embed.skillId ?? Self.text(raw["skill_id"])
            ?? embed.type.split(separator: ":").last.map(String.init)) == "read" ? "read" : "search"
        status = embed.status
    }

    static func isReference(_ embed: EmbedRecord) -> Bool {
        let type = EmbedType.normalized(rawValue: embed.type)
        if type == .projectsSearch || type == .projectsRead { return true }
        return embed.isAppSkillUse
            && (embed.appId ?? embed.rawData?["app_id"]?.value as? String) == "projects"
            && ["search", "read"].contains(embed.skillId ?? embed.rawData?["skill_id"]?.value as? String ?? "")
    }

    @MainActor var title: String {
        let query = query ?? AppStrings.localized("embeds.projects.references.files_fallback")
        return LocalizationManager.shared.text(projectName.isEmpty
            ? "embeds.projects.references.query_only" : "embeds.projects.references.query_in_project",
            replacements: ["query": query, "project": projectName])
    }

    static func text(_ value: Any?) -> String? {
        guard let text = value as? String else { return nil }
        let trimmed = text.trimmingCharacters(in: .whitespacesAndNewlines)
        return trimmed.isEmpty ? nil : trimmed
    }
}

/// Fetch only when a reference is opened. Existing services enforce encrypted
/// project membership and source permissions; connected text stays in memory.
@MainActor
enum ProjectReferenceLoader {
    static func open(_ reference: ProjectFileReference) async throws -> EmbedRecord {
        guard let accountID = await AuthManager.currentUserId(),
              ProjectWorkspacePath.normalized(reference.path) != nil else {
            throw ProjectsWorkspaceError.invalidContext
        }
        let fence = ProjectsWorkspaceFence(accountID: accountID)
        let service = ProjectsWorkspaceService()
        let project = try await service.getProject(accountID: accountID, projectID: reference.projectID,
            teamID: reference.teamID, fence: fence)
        try Task.checkCancellation()
        let result: EmbedRecord
        if let sourceID = reference.sourceID {
            let sources = try await service.listSources(project: project, fence: fence)
            guard let source = sources.first(where: { $0.id == sourceID && $0.status == "connected" }),
                  ProjectRemotePreviewPolicy.canReadText(reference.path) else {
                throw ProjectsWorkspaceError.invalidContext
            }
            let text = try await ProjectRemoteSourceClient().readText(project: project, source: source,
                path: reference.path, fence: fence)
            result = ProjectRemotePreviewPolicy.embed(sourceID: sourceID, sourceLabel: source.name,
                path: reference.path, text: text)
        } else if let embedID = reference.embedID {
            let contents = try await service.contents(project: project, fence: fence)
            guard let item = contents.items.first(where: { $0.targetID == embedID && $0.kind == "embed" }) else {
                throw ProjectsWorkspaceError.invalidContext
            }
            result = try await service.openLinkedEmbed(item, project: project, fence: fence)
        } else {
            throw ProjectsWorkspaceError.invalidContext
        }
        try Task.checkCancellation()
        try await fence.check()
        return result
    }
}
