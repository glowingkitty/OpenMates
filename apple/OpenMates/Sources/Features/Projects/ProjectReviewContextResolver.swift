import Foundation

struct ProjectReviewContext {
    let project: ProjectWorkspaceProject
    let source: ProjectWorkspaceSource?
    let settings: ProjectWorkspaceSettings
    let focusID: String
    let teamID: String?
}

@MainActor
final class ProjectReviewContextResolver {
    private struct FocusResponse: Decodable { let focus: ActiveFocus? }
    private struct ActiveFocus: Decodable {
        let active: Bool
        let projectId: String
        let focusId: String
        let teamId: String?
    }

    private let service: ProjectsWorkspaceService

    init(service: ProjectsWorkspaceService = ProjectsWorkspaceService()) {
        self.service = service
    }

    func resolve(chatID: String, projectID: String, sourceID: String?,
                 fence: ProjectsWorkspaceFence) async throws -> ProjectReviewContext {
        try await fence.check()
        let allowed = CharacterSet(charactersIn: "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-._~")
        guard let escaped = chatID.addingPercentEncoding(withAllowedCharacters: allowed) else {
            throw ProjectsWorkspaceError.invalidResponse
        }
        let response: FocusResponse = try await APIClient.shared.request(.get,
            path: "/v1/projects/focus/current?chat_id=\(escaped)",
            serverProfile: fence.serverProfile,
            expectedAccountID: fence.accountID, expectedScope: fence.scope)
        try await fence.check()
        guard let focus = response.focus, focus.active, focus.projectId == projectID else {
            throw ProjectsWorkspaceError.invalidContext
        }
        let project = try await service.getProject(accountID: fence.accountID,
            projectID: projectID, teamID: focus.teamId, fence: fence)
        let settings = try await service.settings(project: project, fence: fence)
        let contents = try await service.contents(project: project, fence: fence)
        try await fence.check()
        let source = sourceID.flatMap { id in contents.sources.first { $0.id == id } }
            ?? (sourceID == nil && contents.sources.count == 1 ? contents.sources.first : nil)
        if sourceID != nil && source == nil { throw ProjectsWorkspaceError.invalidContext }
        if sourceID == nil && contents.sources.count > 1 { throw ProjectsWorkspaceError.invalidContext }
        return ProjectReviewContext(project: project, source: source,
            settings: settings, focusID: focus.focusId, teamID: focus.teamId)
    }
}
