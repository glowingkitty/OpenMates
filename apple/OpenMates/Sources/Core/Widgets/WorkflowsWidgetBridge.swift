// Publishes only locally cached scheduled-workflow metadata with account, server and Team fences.
import Foundation
import WidgetKit

struct WidgetWorkflowsPublicationScope: Equatable {
    let accountID: String
    let server: ServerProfile
    let offlineScope: UUID
    let teamID: String?
    let teamEpoch: UInt64
    init(_ scope: WorkflowAPIOperationScope) {
        accountID = scope.accountID; server = scope.profile; offlineScope = scope.offlineScope
        teamID = scope.teamContext.teamID; teamEpoch = scope.teamContext.epoch
    }
    static func mustInvalidate(previous: Self?, next: Self?) -> Bool {
        previous != nil && previous != next
    }
}

@MainActor
enum WorkflowsWidgetBridge {
    private static var context: WorkflowAPIOperationScope?
    private static var refreshGeneration = 0
    private static var isConfigured = false
    static func configure(accountID: String?) {
        let next = accountID.map { WorkflowAPIOperationScope.capture(accountID: $0) }
        let previousIdentity = context.map(WidgetWorkflowsPublicationScope.init)
        let nextIdentity = next.map(WidgetWorkflowsPublicationScope.init)
        let languageChanged = WidgetWorkflowsStorage.shared.setLanguage(LocalizationManager.shared.currentLanguage.code)
        guard !isConfigured || previousIdentity != nextIdentity else {
            if languageChanged { WidgetCenter.shared.reloadTimelines(ofKind: WidgetWorkflowsStorage.kind)
        if #available(iOS 18.0, macOS 26.0, *) { ControlCenter.shared.reloadControls(ofKind: "org.openmates.control.workflow") } }
            return
        }
        isConfigured = true
        refreshGeneration += 1
        if WidgetWorkflowsPublicationScope.mustInvalidate(previous: previousIdentity, next: nextIdentity) {
            WidgetWorkflowsStorage.shared.clear()
        }
        context = next
        // First configuration after a cold relaunch retains authorized retry
        // identity. Live key/scope/Team epoch transitions always invalidate it.
        WidgetWorkflowsStorage.shared.activate(owner: next.map { WidgetWorkflowsOwner.identity(accountID: $0.accountID, apiBaseURL: $0.profile.apiBaseURL, teamID: $0.teamContext.teamID) })
        WidgetCenter.shared.reloadTimelines(ofKind: WidgetWorkflowsStorage.kind)
        if #available(iOS 18.0, macOS 26.0, *) { ControlCenter.shared.reloadControls(ofKind: "org.openmates.control.workflow") }
        if accountID != nil { Task { await refresh() } }
    }
    static func refresh() async {
        guard let scope = context else { return }
        refreshGeneration += 1
        let generation = refreshGeneration
        let api = WorkflowAPI()
        do {
            try await scope.check()
            guard let summaries = try await api.cachedWorkflows(scope: scope) else { return }
            var items: [WidgetWorkflowSummary] = []
            for summary in summaries {
                guard let detail = try await api.cachedWorkflow(summary.id, scope: scope),
                      detail.currentVersionId == summary.currentVersionId,
                      let item = WidgetWorkflowsProjection.summary(detail) else { continue }
                items.append(item)
            }
            try await scope.check()
            guard generation == refreshGeneration else { return }
            let owner = WidgetWorkflowsOwner.identity(accountID: scope.accountID, apiBaseURL: scope.profile.apiBaseURL, teamID: scope.teamContext.teamID)
            let previous = WidgetWorkflowsStorage.shared.load()
            let languageChanged = WidgetWorkflowsStorage.shared.setLanguage(LocalizationManager.shared.currentLanguage.code)
            guard previous?.owner != owner || previous?.workflows != items || languageChanged else { return }
            try WidgetWorkflowsStorage.shared.save(.init(owner: owner, teamID: scope.teamContext.teamID, updatedAt: Date(), workflows: items))
            WidgetCenter.shared.reloadTimelines(ofKind: WidgetWorkflowsStorage.kind)
        if #available(iOS 18.0, macOS 26.0, *) { ControlCenter.shared.reloadControls(ofKind: "org.openmates.control.workflow") }
        } catch {
            NativeDiagnostics.warning("snapshot_unavailable", category: "workflows_widget")
        }
    }
}
