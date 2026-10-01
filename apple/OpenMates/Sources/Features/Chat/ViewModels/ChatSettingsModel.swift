// Web source: chats/ChatSettingsPage.svelte, sharedChatDetailsService.ts.
// Reuses the first-party encrypted Tasks/Plans services; public manifest reads
// only open rows with a chat-scoped wrapper. No plaintext is sent to the server.
import Combine
import CryptoKit
import Foundation

struct ChatSettingsPlanningRow: Identifiable {
    let id: String
    let title: String
    let detail: String
    let status: String
    var task: UserTaskItem? = nil
}

enum ChatSettingsTab: String, CaseIterable {
    case tasks, plan, files, usage, share
    var title: String { self == .plan ? "Plan" : rawValue.capitalized }
    var icon: String { switch self { case .tasks: "projectmanagement"; case .plan: "task"; case .files: "files"; case .usage: "usage"; case .share: "share" } }
}

enum ChatSettingsProjection {
    static func summary(_ value: String?) -> String {
        let text = value?.trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
        let lower = text.lowercased()
        guard !text.isEmpty, !lower.contains("[!](embed:"), !lower.contains("```json"),
              !lower.contains("\"embed_id\""), !(lower.contains("\"type\"") && lower.contains("\"content\"")) else {
            return "No summary available yet."
        }
        return text
    }
    static func progress(_ rows: [ChatSettingsPlanningRow]) -> Int {
        rows.isEmpty ? 0 : Int((Double(rows.filter { $0.status == "done" }.count) / Double(rows.count) * 100).rounded())
    }
    static func files(_ embeds: [EmbedRecord]) -> [EmbedRecord] {
        let types: Set<String> = ["audio", "audio-recording", "code", "code-code", "design", "document", "docs", "docs-doc", "image", "images-image", "model3d", "music", "notebook", "pdf", "remotion-video", "recording", "sheet", "sheets", "sheets-sheet", "spreadsheet", "video"]
        return EmbedRecord.deduplicatedById(embeds, context: "chatSettingsFiles")
            .filter { types.contains($0.type.lowercased()) }
            .sorted { $0.id < $1.id }
    }
    static func activePlans(_ rows: [ChatSettingsPlanningRow]) -> [ChatSettingsPlanningRow] {
        rows.filter { $0.status != "completed" && $0.status != "archived" }
    }
    static func visibleTabs(example: Bool, hasFiles: Bool, hasUsage: Bool) -> [ChatSettingsTab] {
        example ? ChatSettingsTab.allCases.filter { $0 == .share || ($0 == .files && hasFiles) || ($0 == .usage && hasUsage) } : ChatSettingsTab.allCases
    }
}

// The observer compares every field used by the Files projection/export. Raw
// payload equality also catches hydration where IDs and versions do not change.
struct ChatSettingsFileSnapshot: Equatable {
    let records: [EmbedRecord]
    static func == (lhs: Self, rhs: Self) -> Bool {
        guard lhs.records.count == rhs.records.count else { return false }
        return zip(lhs.records, rhs.records).allSatisfy { left, right in
            left.id == right.id && left.type == right.type && left.status == right.status &&
            left.versionNumber == right.versionNumber && left.contentHash == right.contentHash &&
            left.encryptedContent == right.encryptedContent &&
            NSDictionary(dictionary: left.rawData?.mapValues(\.value) ?? [:]).isEqual(to: right.rawData?.mapValues(\.value) ?? [:])
        }
    }
}

@MainActor
final class ChatSettingsModel: ObservableObject {
    @Published var tasks: [ChatSettingsPlanningRow] = []
    @Published var plans: [ChatSettingsPlanningRow] = []
    @Published var loading = false
    @Published var saving = false
    @Published var error: String?
    private let taskService = UserTasksService()
    private let planService = UserPlansService()
    private var generation = UUID()

    func load(chatID: String, accountID: String?, shared: Bool) async {
        guard !Task.isCancelled else { return }
        let request = UUID(); generation = request; loading = true; error = nil
        defer { if generation == request { loading = false } }
        do {
            let next: (tasks: [ChatSettingsPlanningRow], plans: [ChatSettingsPlanningRow])
            if shared {
                next = try await sharedRows(chatID: chatID)
            } else {
                guard let accountID else { throw UserTasksError.masterKeyUnavailable }
                let fence = UserTasksAccountFence(accountID: accountID)
                let teamID = TeamWorkspaceContext.shared.teamID
                let teamEpoch = TeamWorkspaceContext.shared.contextEpoch
                async let board = taskService.listBoard(filters: .init(chatID: chatID, teamID: teamID), fence: fence)
                async let planList = planService.list(chatID: chatID, teamID: teamID, fence: fence)
                let (items, linkedPlans) = try await (board, planList)
                try await fence.check()
                guard teamEpoch == TeamWorkspaceContext.shared.contextEpoch, teamID == TeamWorkspaceContext.shared.teamID else { throw UserTasksError.accountChanged }
                next = (items.compactMap { item in
                    guard case .task(let task) = item else { return nil }
                    return .init(id: task.id, title: task.title, detail: task.description.isEmpty ? task.latestInstruction : task.description, status: task.status.rawValue, task: task)
                }, linkedPlans.filter { $0.status != .completed && $0.status != .archived }.map {
                    .init(id: $0.id, title: $0.title, detail: $0.goal, status: $0.status.rawValue)
                })
            }
            guard generation == request, !Task.isCancelled else { return }
            tasks = next.tasks; plans = ChatSettingsProjection.activePlans(next.plans)
        } catch {
            guard generation == request, !Task.isCancelled else { return }
            tasks = []; plans = []; self.error = "Could not load chat plans and tasks."
        }
    }
    func create(title: String, description: String, chatID: String, accountID: String?, shared: Bool) async -> Bool {
        guard !shared, !saving, let accountID, !title.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else { return false }
        saving = true; error = nil
        defer { saving = false }
        do {
            let fence = UserTasksAccountFence(accountID: accountID)
            var input = UserTaskCreateInput(title: title.trimmingCharacters(in: .whitespacesAndNewlines))
            input.teamID = TeamWorkspaceContext.shared.teamID
            input.description = description.trimmingCharacters(in: .whitespacesAndNewlines); input.primaryChatID = chatID
            let item = try await taskService.create(input, fence: fence)
            try await fence.check()
            tasks.insert(.init(id: item.id, title: item.title, detail: item.description, status: item.status.rawValue, task: item), at: 0)
            return true
        } catch { self.error = "Could not create task."; return false }
    }
    func toggle(_ row: ChatSettingsPlanningRow, accountID: String?, shared: Bool) async {
        guard !shared, !saving, let accountID, let task = row.task else { return }
        saving = true; error = nil
        defer { saving = false }
        do {
            let fence = UserTasksAccountFence(accountID: accountID)
            let item = task.status == .done
                ? try await taskService.move(task, to: .todo, teamID: TeamWorkspaceContext.shared.teamID, fence: fence)
                : try await taskService.action("complete", task: task, teamID: TeamWorkspaceContext.shared.teamID, fence: fence)
            try await fence.check()
            if let index = tasks.firstIndex(where: { $0.id == item.id }) {
                tasks[index] = .init(id: item.id, title: item.title, detail: item.description, status: item.status.rawValue, task: item)
            }
        } catch { self.error = "Could not update task." }
    }

    private struct Manifest: Decodable {
        let tasks: [EncryptedUserTaskRecord]?
        let plans: [EncryptedUserPlanRecord]?
        let taskKeyWrappers: [Wrapper]?
        let planKeyWrappers: [Wrapper]?
    }
    private struct Wrapper: Decodable {
        let keyType: String
        let hashedTaskId: String?
        let hashedPlanId: String?
        let encryptedTaskKey: String?
        let encryptedPlanKey: String?
    }
    private func sharedRows(chatID: String) async throws -> (tasks: [ChatSettingsPlanningRow], plans: [ChatSettingsPlanningRow]) {
        guard let key = ChatKeyManager.shared.key(for: chatID) else { throw UserTasksError.taskKeyUnavailable }
        let scope = OfflineStore.shared.scopeGeneration
        let profile = ServerProfile.current()
        let manifest: Manifest = try await APIClient.shared.request(.get, path: "/v1/share/chat/\(UserTasksPaths.escaped(chatID))/manifest", serverProfile: profile)
        guard scope == OfflineStore.shared.scopeGeneration, profile == ServerProfile.current() else { throw UserTasksError.accountChanged }
        var tasks: [ChatSettingsPlanningRow] = []; var plans: [ChatSettingsPlanningRow] = []
        for row in manifest.tasks ?? [] {
            let hash = SHA256.hash(data: Data(row.taskId.utf8)).map { String(format: "%02x", $0) }.joined()
            guard let wrapper = manifest.taskKeyWrappers?.first(where: { $0.keyType == "chat" && $0.hashedTaskId == hash }), let wrapped = wrapper.encryptedTaskKey else { continue }
            let rowKey = try await CryptoManager.shared.unwrapChatKey(encryptedChatKeyBase64: wrapped, masterKey: key)
            let title = try await CryptoManager.shared.decryptContent(base64String: row.encryptedTitle, key: rowKey)
            let detail = try await decrypt(row.encryptedDescription ?? row.encryptedLatestInstruction, key: rowKey)
            tasks.append(.init(id: row.taskId, title: title, detail: detail, status: row.status.rawValue))
        }
        for row in manifest.plans ?? [] where row.status != .completed && row.status != .archived {
            let hash = SHA256.hash(data: Data(row.planId.utf8)).map { String(format: "%02x", $0) }.joined()
            guard let wrapper = manifest.planKeyWrappers?.first(where: { $0.keyType == "chat" && $0.hashedPlanId == hash }), let wrapped = wrapper.encryptedPlanKey else { continue }
            let rowKey = try await CryptoManager.shared.unwrapChatKey(encryptedChatKeyBase64: wrapped, masterKey: key)
            let title = try await CryptoManager.shared.decryptContent(base64String: row.encryptedTitle, key: rowKey)
            let goal = try await decrypt(row.encryptedGoal, key: rowKey)
            plans.append(.init(id: row.planId, title: title, detail: goal, status: row.status.rawValue))
        }
        guard scope == OfflineStore.shared.scopeGeneration, profile == ServerProfile.current() else { throw UserTasksError.accountChanged }
        return (tasks, plans)
    }
    private func decrypt(_ value: String?, key: SymmetricKey) async throws -> String {
        guard let value, !value.isEmpty else { return "" }
        return try await CryptoManager.shared.decryptContent(base64String: value, key: key)
    }
}

// Only owner tab activation requests private data. Initial setup loads once;
// previews and public/recipient contexts keep their supplied local snapshots.
enum ChatSettingsRefreshAction: Equatable { case none, planning, usage }
enum ChatSettingsRefreshPolicy {
    static func action(tab: ChatSettingsTab, initialized: Bool, preview: Bool, example: Bool, shared: Bool) -> ChatSettingsRefreshAction {
        guard initialized, !preview, !example, !shared else { return .none }
        switch tab { case .tasks, .plan: return .planning; case .usage: return .usage; default: return .none }
    }
}
