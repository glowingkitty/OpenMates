// Specification: specifications/features/apple-controls/specification.yml
// Assertions: apple-controls.availability, apple-controls.quick-actions, apple-controls.workflow, apple-controls.project, apple-controls.private-cache
// Projects control inventory is encrypted and account/server/Team/epoch scoped.
import Foundation
import WidgetKit

@MainActor
enum ControlProjectsBridge {
    private static var scope: WidgetWorkflowsPublicationScope?
    static func configure(accountID: String?) {
        let next = accountID.map { WidgetWorkflowsPublicationScope(WorkflowAPIOperationScope.capture(accountID: $0)) }
        if scope != nil && scope != next { ControlProjectsStorage.shared.clear() }
        scope = next
        ControlProjectsStorage.shared.activate(owner: next.map {
            WidgetWorkflowsOwner.identity(accountID: $0.accountID, apiBaseURL: $0.server.apiBaseURL, teamID: $0.teamID)
        })
        reload()
    }
    static func publish(_ projects: [ProjectWorkspaceProject], accountID: String, teamID: String?) {
        let current = WidgetWorkflowsPublicationScope(WorkflowAPIOperationScope.capture(accountID: accountID))
        guard current == scope, current.teamID == teamID else { return }
        let owner = WidgetWorkflowsOwner.identity(accountID: accountID, apiBaseURL: current.server.apiBaseURL, teamID: teamID)
        do {
            try ControlProjectsStorage.shared.save(.init(owner: owner, teamID: teamID,
                projects: projects.filter { $0.teamId == teamID && WidgetWorkflowsLinks.safeID($0.id) }
                    .map { .init(id: $0.id, title: $0.name) }))
            reload()
        } catch { ControlProjectsStorage.shared.clear(); reload() }
    }
    private static func reload() {
        if #available(iOS 18.0, macOS 26.0, *) { ControlCenter.shared.reloadControls(ofKind: "org.openmates.control.project") }
    }
}
