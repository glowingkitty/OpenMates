// Account-fenced publication of the minimal encrypted Tasks widget snapshot.
// Specification: specifications/features/apple-tasks-widget/specification.yml
// Assertions: apple-tasks-widget.private-cache, apple-tasks-widget.status-filter

import CryptoKit
import Foundation
import WidgetKit

struct TasksWidgetPublicationContext: Equatable, Sendable {
    let accountID: String
    let scope: UUID
    let server: ServerProfile
    let teamID: String?
    let teamEpoch: UInt64
    var owner: String {
        let raw = [accountID, scope.uuidString, server.apiBaseURL.absoluteString,
                   teamID ?? "", String(teamEpoch)].joined(separator: "\u{0}")
        return SHA256.hash(data: Data(raw.utf8)).map { String(format: "%02x", $0) }.joined()
    }

    func allowsResult(_ captured: Self, current: Self) -> Bool {
        self == captured && self == current
    }
}

@MainActor
enum TasksWidgetBridge {
    private static var context: TasksWidgetPublicationContext?
    private static var isConfigured = false

    /// Main app calls on authenticated account, server and team context changes,
    /// including logout. Synchronous invalidation happens before later loads.
    static func configure(accountID: String?) {
        let next = accountID.map { TasksWidgetPublicationContext(accountID: $0, scope: OfflineStore.shared.scopeGeneration,
            server: ServerProfile.current(), teamID: TeamWorkspaceContext.shared.teamID,
            teamEpoch: TeamWorkspaceContext.shared.contextEpoch) }
        guard !isConfigured || next != context else { return }
        isConfigured = true
        context = next
        WidgetTasksStorage.activate(owner: next?.owner)
        WidgetCenter.shared.reloadTimelines(ofKind: WidgetTasksStorage.kind)
    }

    static func publish(_ tasks: [UserTaskItem], fence: UserTasksAccountFence, teamID: String?, onlyIfMissing: Bool = false) {
        guard let context, accepts(context, fence: fence, teamID: teamID) else { return }
        if onlyIfMissing, WidgetTasksStorage.load() != nil { return }
        var builder = WidgetTasksSnapshotBuilder()
        for task in tasks {
            guard let status = WidgetTaskFilter(rawValue: task.record.status.rawValue),
                  builder.hasCapacity(for: status), let item = summary(task) else { continue }
            builder.append(item)
            if builder.isFull { break }
        }
        persist(WidgetTasksSnapshot(owner: context.owner, updatedAt: Date(), tasks: builder.tasks))
    }

    static func upsert(_ task: UserTaskItem, fence: UserTasksAccountFence, teamID: String?) {
        guard let context, accepts(context, fence: fence, teamID: teamID), let item = summary(task) else { return }
        var tasks = WidgetTasksStorage.load()?.tasks ?? []
        if let index = tasks.firstIndex(where: { $0.id == item.id }) { tasks[index] = item }
        else { tasks.insert(item, at: 0) }
        persist(WidgetTasksSnapshot(owner: context.owner, updatedAt: Date(), tasks: tasks))
    }

    static func remove(_ id: String, fence: UserTasksAccountFence, teamID: String?) {
        guard let context, accepts(context, fence: fence, teamID: teamID), let snapshot = WidgetTasksStorage.load() else { return }
        persist(WidgetTasksSnapshot(owner: context.owner, updatedAt: Date(), tasks: snapshot.tasks.filter { $0.id != id }))
    }

    private static func accepts(_ context: TasksWidgetPublicationContext, fence: UserTasksAccountFence, teamID: String?) -> Bool {
        let captured = TasksWidgetPublicationContext(accountID: fence.accountID, scope: fence.scope,
            server: fence.serverProfile, teamID: teamID, teamEpoch: fence.widgetTeamEpoch)
        let current = TasksWidgetPublicationContext(accountID: context.accountID, scope: OfflineStore.shared.scopeGeneration,
            server: ServerProfile.current(), teamID: TeamWorkspaceContext.shared.teamID,
            teamEpoch: TeamWorkspaceContext.shared.contextEpoch)
        return context.allowsResult(captured, current: current)
    }

    private static func summary(_ task: UserTaskItem) -> WidgetTaskSummary? {
        guard WidgetTasksLinks.task(task.id) != nil,
              let status = WidgetTaskFilter(rawValue: task.record.status.rawValue) else { return nil }
        return WidgetTaskSummary(id: task.id, title: task.title, status: status)
    }

    private static func persist(_ snapshot: WidgetTasksSnapshot) {
        let bounded = WidgetTasksSnapshot(owner: snapshot.owner, updatedAt: snapshot.updatedAt,
            tasks: WidgetTasksSnapshotBuilder.bounded(snapshot.tasks))
        let previous = WidgetTasksStorage.load()
        let defaults = UserDefaults(suiteName: WidgetTasksStorage.suiteName)
        let language = LocalizationManager.shared.currentLanguage.code
        let contentChanged = previous?.owner != bounded.owner || previous?.tasks != bounded.tasks
        let languageChanged = defaults?.string(forKey: WidgetTasksStorage.languageKey) != language
        guard contentChanged || languageChanged else { return }
        do {
            // Unchanged inventories need no encryption/write/reload. JSON and
            // keychain work stays small because this snapshot holds at most 60
            // summaries; keeping this synchronous preserves publication fencing.
            if contentChanged { try WidgetTasksStorage.save(bounded) }
            if languageChanged { defaults?.set(language, forKey: WidgetTasksStorage.languageKey) }
            WidgetCenter.shared.reloadTimelines(ofKind: WidgetTasksStorage.kind)
        } catch {
            NativeDiagnostics.error("Tasks widget snapshot unavailable", category: "tasks")
        }
    }
}
