// Watch Tasks and read-only Workflows data. Tasks use the same per-task key
// wrapping as the web client. Ciphertext is never used as display text.
// Specification: specifications/features/apple-watch/specification.yml
// Assertions: apple-watch.lists.read-only-private, apple-watch.tasks.edit-private.

// Specification: specifications/features/apple-offline-workspaces/specification.yml
// Assertions: apple-workspaces.watch-retention, apple-workspaces.local-first, apple-workspaces.isolation

import CryptoKit
import Foundation

/// Watch user data is sealed before crossing the disk actor. File names and
/// authenticated encryption bind each entry to the personal account/server.
actor WatchHubOfflineCache {
    static let shared = WatchHubOfflineCache()
    static let maximumEntryBytes = 2_000_000
    static let maximumBytes = 64_000_000
    private let directory: URL
    private var eraseEpoch: UInt64 = 0
    private let verifyScope: @Sendable (WatchWorkflowDetailScope) async -> Bool
    init(directory: URL? = nil, verifyScope: @escaping @Sendable (WatchWorkflowDetailScope) async -> Bool = { scope in
        await MainActor.run { scope.generation == WatchChatAccountLifecycle.generation && scope.profile == ServerProfile.current() }
    }) {
        self.verifyScope = verifyScope
        self.directory = directory ?? FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask)[0]
            .appendingPathComponent("OpenMatesWatch/hub-offline", isDirectory: true)
    }
    private func binding(_ scope: WatchWorkflowDetailScope, key: String) -> Data {
        Data("\(scope.accountID)|\(scope.profile.apiBaseURL.absoluteString)|personal|\(key)".utf8)
    }
    private func url(_ scope: WatchWorkflowDetailScope, key: String) -> URL {
        directory.appendingPathComponent(SHA256.hash(data: binding(scope, key: key)).map { String(format: "%02x", $0) }.joined() + ".sealed")
    }
    func load(key: String, scope: WatchWorkflowDetailScope, masterKey: SymmetricKey) -> Data? {
        guard scope.teamID == nil, let data = try? Data(contentsOf: url(scope, key: key)),
              data.count <= Self.maximumEntryBytes + 100,
              let box = try? AES.GCM.SealedBox(combined: data) else { return nil }
        return try? AES.GCM.open(box, using: masterKey, authenticating: binding(scope, key: key))
    }
    func save(_ data: Data, key: String, scope: WatchWorkflowDetailScope, masterKey: SymmetricKey) async throws {
        let observedEraseEpoch = eraseEpoch
        guard scope.teamID == nil, data.count <= Self.maximumEntryBytes else { throw APIError.invalidResponse }
        let sealed = try AES.GCM.seal(data, using: masterKey, authenticating: binding(scope, key: key)).combined!
        try Task.checkCancellation()
        let current = await verifyScope(scope)
        try Task.checkCancellation()
        guard current, observedEraseEpoch == eraseEpoch else { throw CancellationError() }
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
        var directory = directory
        var values = URLResourceValues(); values.isExcludedFromBackup = true
        try directory.setResourceValues(values)
        let target = url(scope, key: key)
        let entries = try FileManager.default.contentsOfDirectory(at: directory, includingPropertiesForKeys: [.fileSizeKey])
        let total = try entries.filter { $0 != target }.reduce(0) { try $0 + ($1.resourceValues(forKeys: [.fileSizeKey]).fileSize ?? 0) }
        guard total + sealed.count <= Self.maximumBytes else { throw APIError.invalidResponse }
        try sealed.write(to: target, options: [.atomic, .completeFileProtection])
    }
    func remove(key: String, scope: WatchWorkflowDetailScope) throws {
        let target = url(scope, key: key)
        if FileManager.default.fileExists(atPath: target.path) { try FileManager.default.removeItem(at: target) }
    }
    func removeAll() throws {
        eraseEpoch &+= 1
        if FileManager.default.fileExists(atPath: directory.path) { try FileManager.default.removeItem(at: directory) }
    }
}

enum WatchTaskGroup: Int, CaseIterable, Identifiable {
    case backlog, todo, inProgress, blocked, done

    var id: Int { rawValue }
    var status: String {
        switch self {
        case .backlog: "backlog"
        case .todo: "todo"
        case .inProgress: "in_progress"
        case .blocked: "blocked"
        case .done: "done"
        }
    }

    static func from(status: String) -> WatchTaskGroup? {
        switch status {
        case "in_progress": return .inProgress
        case "blocked": return .blocked
        case "todo": return .todo
        case "backlog": return .backlog
        case "done": return .done
        default: return nil
        }
    }
}

struct WatchTaskListItem: Identifiable, Equatable {
    let id: String
    let title: String
    let group: WatchTaskGroup
    let status: String
    let position: Int
    let updatedAt: Int
    let openRequest: WatchItemOpenRequest
    let description: String
    let latestInstruction: String
    let activitySummary: String
    let blockedReason: String
    let record: WatchTaskRecord?
    var priority: Int { record?.priority ?? 0 }

    init(id: String, title: String, group: WatchTaskGroup, status: String,
         position: Int, updatedAt: Int, openRequest: WatchItemOpenRequest,
         description: String = "", latestInstruction: String = "",
         activitySummary: String = "", blockedReason: String = "", record: WatchTaskRecord? = nil) {
        self.id = id
        self.title = title
        self.group = group
        self.status = status
        self.position = position
        self.updatedAt = updatedAt
        self.openRequest = openRequest
        self.description = description
        self.latestInstruction = latestInstruction
        self.activitySummary = activitySummary
        self.blockedReason = blockedReason
        self.record = record
    }
}

struct WatchWorkflowListItem: Identifiable, Equatable {
    let id: String
    let title: String
    let enabled: Bool
    let updatedAt: Int
    let category: String?
    let icon: String?
    let openRequest: WatchItemOpenRequest

    init(
        id: String, title: String, enabled: Bool, updatedAt: Int,
        category: String? = nil, icon: String? = nil,
        openRequest: WatchItemOpenRequest
    ) {
        self.id = id
        self.title = title
        self.enabled = enabled
        self.updatedAt = updatedAt
        self.category = category
        self.icon = icon
        self.openRequest = openRequest
    }
}

struct WatchTaskListResponse: Decodable {
    let tasks: [WatchTaskRecord]
}

struct WatchWorkflowListResponse: Decodable {
    let workflows: [WatchWorkflowRecord]
}

struct WatchWorkflowRecord: Decodable {
    let id: String
    let title: String
    let enabled: Bool
    let updatedAt: Int
    let category: String?
    let icon: String?
    let teamId: String?
}

struct WatchTaskRecord: Codable, Equatable {
    let taskId: String
    let source: String?
    let workflowId: String?
    let title: String?
    let encryptedTaskKey: String?
    let encryptedTitle: String?
    let encryptedDescription: String?
    let encryptedLatestInstruction: String?
    let encryptedActivitySummary: String?
    let encryptedBlockedReason: String?
    let blockedMessage: String?
    let status: String
    let position: Int?
    let updatedAt: Int?
    let version: Int?
    let priority: Int?
    let teamId: String?
    let readOnly: Bool?
}

struct WatchTaskDraft: Equatable {
    var title: String
    var description: String
    var group: WatchTaskGroup
    var priority: Int

    init(item: WatchTaskListItem) {
        title = item.title
        description = item.description
        group = item.group
        priority = item.priority
    }

    var isValid: Bool {
        !title.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty && (0...4).contains(priority)
    }

    func hasChanges(from item: WatchTaskListItem) -> Bool {
        title.trimmingCharacters(in: .whitespacesAndNewlines) != item.title ||
            description != item.description || group != item.group || priority != item.priority
    }
}

enum WatchTaskEditingError: Error, Equatable {
    case accountChanged, readOnly, invalidDraft, unavailableKey, invalidResponse
}

struct WatchTaskUpdateResponse: Decodable { let task: WatchTaskRecord }

struct WatchTaskRequestContext: Sendable {
    let accountID: String
    let generation: UInt64
    let serverProfile: ServerProfile
    let currentAccountID: @MainActor @Sendable () -> String?
    var isWrite = false
    var writesAllowed: @MainActor @Sendable () -> Bool = { true }

    @MainActor func check() throws {
        try Task.checkCancellation()
        guard (!isWrite || writesAllowed()), !accountID.isEmpty, currentAccountID() == accountID,
              generation == WatchChatAccountLifecycle.generation,
              serverProfile == ServerProfile.current(),
              !PairSessionDeadlineStore.isExpired(userID: accountID) else {
            throw WatchTaskEditingError.accountChanged
        }
    }
}

@MainActor
struct WatchTaskDependencies {
    let request: @MainActor (HTTPMethod, String, Data?, WatchTaskRequestContext) async throws -> Data
    let masterKey: @MainActor (String) async throws -> SymmetricKey?

    static var live: WatchTaskDependencies {
        WatchTaskDependencies(request: { method, path, body, context in
            try await APIClient.shared.requestForVerifiedWatchSession(method, path: path,
                serverProfile: context.serverProfile, body: body.map { JSONRawBody(data: $0) },
                validate: { try context.check() })
        }, masterKey: { try await CryptoManager.shared.loadMasterKey(for: $0) })
    }
}

@MainActor
final class WatchHubDataService: ObservableObject {
    @Published private(set) var tasks: [WatchTaskListItem] = []
    @Published private(set) var workflows: [WatchWorkflowListItem] = []
    @Published private(set) var isLoadingTasks = false
    @Published private(set) var isLoadingWorkflows = false
    @Published private(set) var tasksError = false
    @Published private(set) var workflowsError = false

    private let userId: String?
    private let usesFixture: Bool
    private let taskDependencies: WatchTaskDependencies
    private let writesAllowed: @MainActor @Sendable () -> Bool
    private let currentTaskAccountID: @MainActor @Sendable () -> String?
    private let taskGeneration: UInt64
    private let taskProfile: ServerProfile
    private let offlineCache: WatchHubOfflineCache
    private var maintenanceTask: Task<Void, Never>?
    private var maintenanceID = UUID()
    private var backgroundSyncAllowed = false
    @Published private(set) var isSavingTask = false

    init(userId: String?, fixtureTasks: [WatchTaskListItem]? = nil,
         fixtureWorkflows: [WatchWorkflowListItem]? = nil,
         currentAccountID: @escaping @MainActor @Sendable () -> String? = { nil },
         taskDependencies: WatchTaskDependencies? = nil,
         offlineCache: WatchHubOfflineCache = .shared,
         writesAllowed: @escaping @MainActor @Sendable () -> Bool = { true }) {
        self.writesAllowed = writesAllowed
        self.userId = userId
        self.offlineCache = offlineCache
        self.taskDependencies = taskDependencies ?? .live
        currentTaskAccountID = currentAccountID
        taskGeneration = WatchChatAccountLifecycle.generation
        taskProfile = ServerProfile.current()
        usesFixture = fixtureTasks != nil || fixtureWorkflows != nil
        tasks = fixtureTasks ?? []
        workflows = fixtureWorkflows ?? []
    }

    private func offlineScope(_ account: String) -> WatchWorkflowDetailScope {
        WatchWorkflowDetailScope(accountID: account, profile: taskProfile, generation: taskGeneration, teamID: nil)
    }
    private func openTaskPage(_ data: Data, masterKey: SymmetricKey) async throws -> [WatchTaskListItem] {
        let decoder = JSONDecoder(); decoder.keyDecodingStrategy = .convertFromSnakeCase
        let response = try decoder.decode(WatchTaskListResponse.self, from: data)
        var result: [WatchTaskListItem] = []
        for record in response.tasks where record.teamId == nil {
            if let item = await Self.openTask(record, masterKey: masterKey) { result.append(item) }
            try checkTaskAccount()
        }
        return result
    }
    func loadCachedTasks() async {
        guard !usesFixture, let userId else { return }
        do {
            try checkTaskAccount()
            guard let masterKey = try await taskDependencies.masterKey(userId) else { return }
            var items: [WatchTaskListItem] = []
            for group in WatchTaskGroup.allCases {
                if let data = await offlineCache.load(key: "tasks-" + group.status, scope: offlineScope(userId), masterKey: masterKey) {
                    items += Array(try await openTaskPage(data, masterKey: masterKey).filter { $0.group == group }.prefix(50))
                }
            }
            try checkTaskAccount()
            if !items.isEmpty { tasks = Self.sortedTasks(items); tasksError = true }
        } catch { if !taskAccountMatches { tasks = [] } }
    }
    func loadCachedWorkflows() async {
        guard !usesFixture, let userId else { return }
        do {
            try checkTaskAccount()
            guard let masterKey = try await taskDependencies.masterKey(userId),
                  let data = await offlineCache.load(key: "workflows", scope: offlineScope(userId), masterKey: masterKey) else { return }
            let decoder = JSONDecoder(); decoder.keyDecodingStrategy = .convertFromSnakeCase
            let rows = try decoder.decode(WatchWorkflowListResponse.self, from: data).workflows
            try checkTaskAccount()
            workflows = rows.compactMap { row in
                guard row.teamId == nil, let request = WatchItemOpenRequest(kind: .workflow, id: row.id) else { return nil }
                return WatchWorkflowListItem(id: row.id, title: row.title, enabled: row.enabled, updatedAt: row.updatedAt,
                    category: row.category, icon: row.icon, openRequest: request)
            }.sorted { $0.updatedAt > $1.updatedAt }
        } catch { if !taskAccountMatches { workflows = [] } }
    }
    /// Called from the hub's scene/navigation lifecycle; foreground reads win.
    func setBackgroundSyncAllowed(_ allowed: Bool) {
        backgroundSyncAllowed = allowed
        if !allowed { maintenanceID = UUID(); maintenanceTask?.cancel(); maintenanceTask = nil; return }
        guard !usesFixture, maintenanceTask == nil, let userId else { return }
        let operation = UUID(); maintenanceID = operation
        maintenanceTask = Task(priority: .utility) { @MainActor [weak self] in
            guard let self else { return }
            await self.loadCachedTasks(); await self.loadCachedWorkflows()
            await self.refreshTasks(); await self.refreshWorkflows()
            let service = WatchWorkflowDetailService(currentAccountID: self.currentTaskAccountID, offlineCache: self.offlineCache)
            let scope = self.offlineScope(userId)
            for workflow in self.workflows {
                guard !Task.isCancelled, self.backgroundSyncAllowed, self.maintenanceID == operation,
                      (try? self.checkTaskAccount()) != nil else { break }
                // The existing workflow routes allow 60 reads/minute. A serial
                // interval also bounds radio/CPU work and yields to navigation.
                do { try await Task.sleep(for: .seconds(3)) } catch { break }
                await service.load(id: workflow.id, scope: scope)
                guard !Task.isCancelled else { break }
                await service.loadRuns(workflowID: workflow.id, scope: scope)
            }
            if self.maintenanceID == operation { self.maintenanceTask = nil }
        }
    }
    func waitForBackgroundSync() async { await maintenanceTask?.value }
    func performBackgroundOfflineSync() async {
        guard !backgroundSyncAllowed else { return }
        setBackgroundSyncAllowed(true)
        defer { setBackgroundSyncAllowed(false) }
        await withTaskCancellationHandler(operation: { await waitForBackgroundSync() }, onCancel: {
            Task { @MainActor [weak self] in self?.setBackgroundSyncAllowed(false) }
        })
    }

    func refreshTasks() async {
        if usesFixture { return }
        guard !isLoadingTasks, !isSavingTask, let userId else { return }
        isLoadingTasks = true
        defer { isLoadingTasks = false }
        do {
            try checkTaskAccount()
            guard let masterKey = try await taskDependencies.masterKey(userId) else { throw WatchTaskEditingError.unavailableKey }
            var decrypted: [WatchTaskListItem] = []
            var cachedIDsByStatus: [String: Set<String>] = [:]
            for group in WatchTaskGroup.allCases {
                try checkTaskAccount()
                let data = try await taskDependencies.request(.get, "/v1/user-tasks?status=\(group.status)&limit=50", nil, taskContext(userId))
                try checkTaskAccount()
                let rows = try await openTaskPage(data, masterKey: masterKey).filter { $0.group == group }
                let wire = try JSONSerialization.jsonObject(with: data) as? [String: Any]
                let personal = (wire?["tasks"] as? [[String: Any]] ?? []).filter { $0["team_id"] == nil || $0["team_id"] is NSNull }
                let cacheData = try JSONSerialization.data(withJSONObject: ["tasks": Array(personal.filter { $0["status"] as? String == group.status }.prefix(50))])
                decrypted += Array(rows.prefix(50))
                cachedIDsByStatus[group.status] = Set(rows.prefix(50).map(\.id))
                tasks = Self.sortedTasks(decrypted + tasks.filter { $0.group.rawValue > group.rawValue })
                try? await offlineCache.save(cacheData, key: "tasks-" + group.status, scope: offlineScope(userId), masterKey: masterKey)
                try checkTaskAccount()
                await Task.yield()
            }
            tasks = Self.sortedTasks(decrypted)
            // A task may move between status GETs. Repair only pages whose
            // membership changed after choosing the freshest observed row.
            let encoder = JSONEncoder(); encoder.keyEncodingStrategy = .convertToSnakeCase
            for group in WatchTaskGroup.allCases {
                let items = Array(tasks.filter { $0.group == group }.prefix(50))
                guard Set(items.map(\.id)) != cachedIDsByStatus[group.status] else { continue }
                struct CachedRows: Encodable { let tasks: [WatchTaskRecord] }
                let data = try encoder.encode(CachedRows(tasks: items.compactMap(\.record)))
                try checkTaskAccount()
                try? await offlineCache.save(data, key: "tasks-" + group.status, scope: offlineScope(userId), masterKey: masterKey)
                try checkTaskAccount()
            }
            tasksError = false
        } catch {
            if !taskAccountMatches { tasks = [] }
            else if Task.isCancelled { return }
            else { await loadCachedTasks() }
            tasksError = true
            NativeDiagnostics.event("watch_tasks_refresh_failed", category: "watch_hub", level: .warning)
        }
    }

    func canEditTask(_ item: WatchTaskListItem) -> Bool {
        guard writesAllowed(), !isLoadingTasks, !tasksError, let record = item.record, record.taskId == item.id, record.source != "workflow_run",
              item.openRequest.kind == .task, record.teamId == nil, record.readOnly != true,
              let version = record.version, version > 0, record.encryptedTaskKey != nil,
              tasks.contains(item) else { return false }
        return (try? checkTaskAccount()) != nil
    }

    /// Only returned encrypted records become saved state. A failure leaves the
    /// caller's draft untouched and does not invent a successful local mutation.
    func saveTask(_ item: WatchTaskListItem, draft: WatchTaskDraft) async throws -> WatchTaskListItem {
        try checkTaskAccount()
        guard !isSavingTask, canEditTask(item), let userId, let record = item.record,
              let version = record.version else { throw WatchTaskEditingError.readOnly }
        let title = draft.title.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !title.isEmpty, (0...4).contains(draft.priority) else { throw WatchTaskEditingError.invalidDraft }
        guard draft.hasChanges(from: item) else { return item }
        isSavingTask = true
        defer { isSavingTask = false }
        guard let masterKey = try await taskDependencies.masterKey(userId),
              let wrappedKey = record.encryptedTaskKey else { throw WatchTaskEditingError.unavailableKey }
        try checkTaskAccount()
        let key = try await CryptoManager.shared.unwrapChatKey(encryptedChatKeyBase64: wrappedKey, masterKey: masterKey)
        try checkTaskAccount()
        var body: [String: Any] = ["version": version, "updated_at": Int(Date().timeIntervalSince1970)]
        if title != item.title { body["encrypted_title"] = try await CryptoManager.shared.encryptContent(title, key: key) }
        if draft.description != item.description {
            body["encrypted_description"] = try await CryptoManager.shared.encryptContent(draft.description, key: key)
        }
        if draft.group != item.group { body["status"] = draft.group.status }
        if draft.priority != item.priority { body["priority"] = draft.priority }
        try checkTaskAccount()
        guard canEditTask(item) else { throw WatchTaskEditingError.readOnly }
        let escapedID = item.id.addingPercentEncoding(withAllowedCharacters: CharacterSet(charactersIn:
            "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-._~")) ?? ""
        guard !escapedID.isEmpty else { throw WatchTaskEditingError.invalidResponse }
        let data = try await taskDependencies.request(.patch, "/v1/user-tasks/\(escapedID)",
            JSONSerialization.data(withJSONObject: body), taskContext(userId, writing: true))
        try checkTaskAccount()
        let decoder = JSONDecoder()
        decoder.keyDecodingStrategy = .convertFromSnakeCase
        let response = try decoder.decode(WatchTaskUpdateResponse.self, from: data)
        guard response.task.taskId == item.id, response.task.source != "workflow_run",
              response.task.teamId == nil, response.task.readOnly != true,
              response.task.encryptedTaskKey == wrappedKey,
              let returnedVersion = response.task.version, returnedVersion > version,
              let returned = await Self.openTask(response.task, masterKey: masterKey) else {
            throw WatchTaskEditingError.invalidResponse
        }
        try checkTaskAccount()
        guard let index = tasks.firstIndex(where: { $0.id == item.id && $0.record?.version == version }) else {
            throw WatchTaskEditingError.invalidResponse
        }
        tasks[index] = returned
        tasks = Self.sortedTasks(tasks)
        let encoder = JSONEncoder(); encoder.keyEncodingStrategy = .convertToSnakeCase
        for group in WatchTaskGroup.allCases {
            struct CachedRows: Encodable { let tasks: [WatchTaskRecord] }
            let records = Array(tasks.filter { $0.group == group }.prefix(50)).compactMap(\.record)
            try checkTaskAccount()
            let cacheData = try encoder.encode(CachedRows(tasks: records))
            try? await offlineCache.save(cacheData, key: "tasks-" + group.status, scope: offlineScope(userId), masterKey: masterKey)
        }
        try checkTaskAccount()
        return returned
    }

    private func taskContext(_ accountID: String, writing: Bool = false) -> WatchTaskRequestContext {
        WatchTaskRequestContext(accountID: accountID, generation: taskGeneration, serverProfile: taskProfile,
            currentAccountID: currentTaskAccountID, isWrite: writing, writesAllowed: writesAllowed)
    }

    private var taskAccountMatches: Bool {
        guard let userId, !userId.isEmpty else { return false }
        return currentTaskAccountID() == userId && !PairSessionDeadlineStore.isExpired(userID: userId)
            && taskGeneration == WatchChatAccountLifecycle.generation && taskProfile == ServerProfile.current()
    }
    private func checkTaskAccount() throws {
        try Task.checkCancellation()
        guard taskAccountMatches else { throw WatchTaskEditingError.accountChanged }
    }

    private static func sortedTasks(_ items: [WatchTaskListItem]) -> [WatchTaskListItem] {
        var latest: [String: WatchTaskListItem] = [:]
        for item in items {
            // Later status responses win equal/unknown timestamps. Updated
            // rows cannot leave duplicate ForEach IDs or duplicate offline rows.
            if let previous = latest[item.id], previous.updatedAt > item.updatedAt { continue }
            latest[item.id] = item
        }
        return latest.values.sorted {
            if $0.group != $1.group { return $0.group.rawValue < $1.group.rawValue }
            if $0.position != $1.position { return $0.position < $1.position }
            if $0.updatedAt != $1.updatedAt { return $0.updatedAt > $1.updatedAt }
            return $0.id < $1.id
        }
    }

    /// Uses the same account-wrapped Task key and encrypted detail fields as iPhone.
    /// A malformed optional field fails closed rather than displaying ciphertext.
    static func openTask(_ record: WatchTaskRecord, masterKey: SymmetricKey) async -> WatchTaskListItem? {
        guard let group = WatchTaskGroup.from(status: record.status) else { return nil }
        if record.source == "workflow_run" {
            guard let workflowID = record.workflowId,
                  let request = WatchItemOpenRequest(kind: .workflow, id: workflowID),
                  let title = record.title, !title.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else { return nil }
            return WatchTaskListItem(id: record.taskId, title: title, group: group,
                status: record.status, position: record.position ?? 0, updatedAt: record.updatedAt ?? 0,
                openRequest: request, blockedReason: record.blockedMessage ?? "")
        }
        guard let request = WatchItemOpenRequest(kind: .task, id: record.taskId),
              let encryptedKey = record.encryptedTaskKey, let encryptedTitle = record.encryptedTitle else { return nil }
        do {
            let taskKey = try await CryptoManager.shared.unwrapChatKey(
                encryptedChatKeyBase64: encryptedKey, masterKey: masterKey)
            let title = try await CryptoManager.shared.decryptContent(base64String: encryptedTitle, key: taskKey)
            guard !title.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else { return nil }
            let description = try await openText(record.encryptedDescription, key: taskKey)
            let instruction = try await openText(record.encryptedLatestInstruction, key: taskKey)
            let summary = try await openText(record.encryptedActivitySummary, key: taskKey)
            let blockedReason = try await openText(record.encryptedBlockedReason, key: taskKey)
            return WatchTaskListItem(id: record.taskId, title: title, group: group,
                status: record.status, position: record.position ?? 0, updatedAt: record.updatedAt ?? 0,
                openRequest: request, description: description, latestInstruction: instruction,
                activitySummary: summary, blockedReason: blockedReason, record: record)
        } catch {
            return nil
        }
    }

    private static func openText(_ ciphertext: String?, key: SymmetricKey) async throws -> String {
        guard let ciphertext, !ciphertext.isEmpty else { return "" }
        return try await CryptoManager.shared.decryptContent(base64String: ciphertext, key: key)
    }

    func refreshWorkflows() async {
        if usesFixture { return }
        guard !isLoadingWorkflows, let userId else { return }
        isLoadingWorkflows = true
        defer { isLoadingWorkflows = false }
        do {
            try checkTaskAccount()
            let data = try await taskDependencies.request(.get, "/v1/workflows", nil, taskContext(userId))
            try checkTaskAccount()
            let decoder = JSONDecoder()
            decoder.keyDecodingStrategy = .convertFromSnakeCase
            let response = try decoder.decode(WatchWorkflowListResponse.self, from: data)
            workflows = response.workflows.compactMap { workflow in
                guard workflow.teamId == nil, let request = WatchItemOpenRequest(kind: .workflow, id: workflow.id),
                      !workflow.title.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else { return nil }
                return WatchWorkflowListItem(
                    id: workflow.id, title: workflow.title,
                    enabled: workflow.enabled, updatedAt: workflow.updatedAt,
                    category: workflow.category, icon: workflow.icon,
                    openRequest: request
                )
            }.sorted { $0.updatedAt > $1.updatedAt }
            do {
                if let masterKey = try await taskDependencies.masterKey(userId) {
                    try checkTaskAccount()
                    let wire = try JSONSerialization.jsonObject(with: data) as? [String: Any]
                    let personalRows = (wire?["workflows"] as? [[String: Any]] ?? []).filter { $0["team_id"] == nil || $0["team_id"] is NSNull }
                    try await offlineCache.save(JSONSerialization.data(withJSONObject: ["workflows": personalRows]), key: "workflows", scope: offlineScope(userId), masterKey: masterKey)
                }
            } catch { /* Persistence limits never hide valid online rows. */ }
            try checkTaskAccount()
            workflowsError = false
            NativeDiagnostics.event(
                "watch_workflows_refreshed", category: "watch_hub",
                counts: ["response_rows": response.workflows.count, "displayed_rows": workflows.count]
            )
        } catch {
            if !taskAccountMatches { workflows = [] }
            else if Task.isCancelled { return }
            else { await loadCachedWorkflows() }
            workflowsError = true
            NativeDiagnostics.failure(
                "watch_workflows_refresh_failed", category: "watch_hub",
                level: .warning, error: error
            )
        }
    }
}
