// Web sources: services/workflowService.ts, userTaskService.ts, userPlanService.ts, projectService.ts
// Specification: specifications/features/apple-offline-workspaces/specification.yml
// Assertions: apple-workspaces.offline-complete, apple-workspaces.local-first,
// apple-workspaces.isolation, apple-workspaces.maintenance
import CryptoKit
import Foundation
import CoreFoundation

struct NativeWorkspaceOfflineScope: Hashable, Sendable, Codable {
    let accountID: String
    let server: String
    let teamID: String?
    let accountGeneration: UUID
    let teamEpoch: UInt64

    var directoryID: String {
        let identity = [server, accountID, teamID ?? ""].joined(separator: "\u{0}")
        return SHA256.hash(data: Data(identity.utf8)).map { String(format: "%02x", $0) }.joined()
    }
}

/// Page receipts are mandatory; the final page may contain real records.
struct NativeWorkspaceInventoryPages {
    private var records: [Data] = []
    private var seen: Set<String> = []
    private(set) var nextCursor: String?
    private(set) var isComplete = false

    mutating func append(_ data: Data, collection: String, idKey: String) throws {
        guard !isComplete,
              let page = try JSONSerialization.jsonObject(with: data) as? [String: Any],
              let items = page[collection] as? [[String: Any]],
              let completeValue = page["complete"] as? NSNumber,
              CFGetTypeID(completeValue) == CFBooleanGetTypeID() else { throw UserTasksError.invalidResponse }
        let complete = completeValue.boolValue
        let next = page["next_cursor"] as? String
        if complete {
            guard next == nil else { throw UserTasksError.invalidResponse }
        } else {
            guard let next, !next.isEmpty, nextCursor == nil || next > nextCursor!,
                  items.contains(where: { ($0[idKey] as? String) == next }) else { throw UserTasksError.invalidResponse }
        }
        for row in items {
            guard let id = row[idKey] as? String, !id.isEmpty, seen.insert(id).inserted else {
                throw UserTasksError.invalidResponse
            }
            records.append(try JSONSerialization.data(withJSONObject: row))
        }
        nextCursor = next
        isComplete = complete
    }

    func snapshot(collection: String) throws -> Data {
        guard isComplete else { throw UserTasksError.invalidResponse }
        let rows = try records.map { try JSONSerialization.jsonObject(with: $0) }
        return try JSONSerialization.data(withJSONObject: [collection: rows])
    }
}

private actor NativeWorkspaceInventoryCollector {
    private var pages = NativeWorkspaceInventoryPages()
    func state() -> (String?, Bool) { (pages.nextCursor, pages.isComplete) }
    func append(_ data: Data, collection: String, idKey: String) throws {
        try pages.append(data, collection: collection, idKey: idKey)
    }
    func snapshot(collection: String) throws -> Data { try pages.snapshot(collection: collection) }
}

/// The only durable workspace representation is an authenticated encrypted blob.
/// A complete refresh swaps one namespace atomically; failed refreshes leave it intact.
actor NativeWorkspaceOfflineCache {
    static let shared = NativeWorkspaceOfflineCache()
    private struct Snapshot: Codable {
        let identity: String
        var complete: Bool
        var responses: [String: Data]
    }
    private let directory: URL
    private var activeScope: NativeWorkspaceOfflineScope?
    private var key: SymmetricKey?
    private var snapshots: [String: Snapshot] = [:]
    private var revisions: [String: UUID] = [:]

    init(directory: URL? = nil) {
        self.directory = directory ?? FileManager.default.urls(for: .applicationSupportDirectory,
            in: .userDomainMask)[0].appendingPathComponent("OpenMates/workspace-ciphertext", isDirectory: true)
    }

    func purge(scope: NativeWorkspaceOfflineScope) throws {
        // Namespace contains recoverable server snapshots, never send journals.
        let url = directory.appendingPathComponent(scope.directoryID, isDirectory: true)
        if FileManager.default.fileExists(atPath: url.path) { try FileManager.default.removeItem(at: url) }
        if activeScope?.directoryID == scope.directoryID { snapshots.removeAll(); revisions.removeAll() }
    }

    func configure(scope: NativeWorkspaceOfflineScope, masterKey: SymmetricKey) {
        if activeScope == scope, key == masterKey { return }
        activeScope = scope
        key = masterKey
        snapshots.removeAll()
        revisions.removeAll()
    }

    func deactivate(ifScope scope: NativeWorkspaceOfflineScope? = nil) {
        if let scope, activeScope != scope { return }
        activeScope = nil
        key = nil
        snapshots.removeAll()
        revisions.removeAll()
    }

    private func check(_ scope: NativeWorkspaceOfflineScope) throws -> SymmetricKey {
        try Task.checkCancellation()
        guard activeScope == scope, let key else { throw CancellationError() }
        return key
    }

    private func file(_ namespace: String, scope: NativeWorkspaceOfflineScope) -> URL {
        let name = SHA256.hash(data: Data(namespace.utf8)).map { String(format: "%02x", $0) }.joined()
        return directory.appendingPathComponent(scope.directoryID, isDirectory: true)
            .appendingPathComponent(name + ".aesgcm")
    }

    private func snapshot(_ namespace: String, scope: NativeWorkspaceOfflineScope) throws -> Snapshot {
        let key = try check(scope)
        if let loaded = snapshots[namespace] { return loaded }
        let url = file(namespace, scope: scope)
        guard FileManager.default.fileExists(atPath: url.path) else {
            return Snapshot(identity: scope.directoryID, complete: false, responses: [:])
        }
        let ciphertext = try Data(contentsOf: url)
        let plaintext = try AES.GCM.open(AES.GCM.SealedBox(combined: ciphertext), using: key,
            authenticating: Data((scope.directoryID + namespace).utf8))
        let loaded = try JSONDecoder().decode(Snapshot.self, from: plaintext)
        guard loaded.identity == scope.directoryID else { throw CancellationError() }
        snapshots[namespace] = loaded
        return loaded
    }

    func read(namespace: String, path: String, scope: NativeWorkspaceOfflineScope) throws -> Data? {
        try snapshot(namespace, scope: scope).responses[path]
    }

    func hasCompleteSnapshot(namespace: String, scope: NativeWorkspaceOfflineScope) throws -> Bool {
        try snapshot(namespace, scope: scope).complete
    }

    func beginRefresh(namespace: String, scope: NativeWorkspaceOfflineScope) throws -> UUID {
        _ = try check(scope)
        let revision = UUID()
        revisions[namespace] = revision
        return revision
    }

    func commit(namespace: String, responses: [String: Data], scope: NativeWorkspaceOfflineScope,
                revision: UUID, complete: Bool = true) throws {
        let key = try check(scope)
        guard revisions[namespace] == revision else { throw CancellationError() }
        try write(Snapshot(identity: scope.directoryID, complete: complete, responses: responses),
                  namespace: namespace, scope: scope, key: key)
    }

    func retain(namespace: String, path: String, data: Data, scope: NativeWorkspaceOfflineScope) throws {
        let key = try check(scope)
        var retained = try snapshot(namespace, scope: scope)
        guard retained.responses[path] != data else { return }
        retained.responses[path] = data
        revisions[namespace] = UUID()
        // An endpoint refresh does not prove the entire workspace is current.
        retained.complete = false
        try write(retained, namespace: namespace, scope: scope, key: key)
    }

    private func write(_ snapshot: Snapshot, namespace: String,
                       scope: NativeWorkspaceOfflineScope, key: SymmetricKey) throws {
        let plaintext = try JSONEncoder().encode(snapshot)
        let ciphertext = try AES.GCM.seal(plaintext, using: key,
            authenticating: Data((scope.directoryID + namespace).utf8)).combined!
        _ = try check(scope)
        let url = file(namespace, scope: scope)
        try FileManager.default.createDirectory(at: url.deletingLastPathComponent(), withIntermediateDirectories: true)
        try ciphertext.write(to: url, options: .atomic)
        var excluded = url
        var values = URLResourceValues()
        values.isExcludedFromBackup = true
        try? excluded.setResourceValues(values)
        snapshots[namespace] = snapshot
    }
}

/// Shared GET flights eliminate duplicate workspace/view requests. A caller's
/// cancellation never commits a response after its account or team has changed.
actor NativeWorkspaceRequestFlights {
    static let shared = NativeWorkspaceRequestFlights()
    private var flights: [String: (UUID, Task<Data, Error>)] = [:]
    private(set) var coalescedRequestCount = 0

    func request(path: String, profile: ServerProfile, scope: NativeWorkspaceOfflineScope,
                 api: APIClient = .shared) async throws -> Data {
        let identity = scope.directoryID + scope.accountGeneration.uuidString + String(scope.teamEpoch) + path
        return try await perform(identity: identity) {
            try await api.request(.get, path: path, serverProfile: profile,
                expectedAccountID: scope.accountID, expectedScope: scope.accountGeneration,
                expectedTeamContext: APIRequestTeamContext(epoch: scope.teamEpoch, teamID: scope.teamID))
        }
    }

    func perform(identity: String, operation: @escaping @Sendable () async throws -> Data) async throws -> Data {
        if let (_, task) = flights[identity] {
            coalescedRequestCount += 1
            return try await task.value
        }
        let id = UUID()
        let task = Task<Data, Error> { try await operation() }
        flights[identity] = (id, task)
        defer { if flights[identity]?.0 == id { flights.removeValue(forKey: identity) } }
        return try await task.value
    }

}

/// Monotonic, account/team-scoped admission and partial-run progress. Dirty
/// signals coalesce within the cooldown; reconnect may explicitly force admission.
struct NativeWorkspaceMaintenancePolicy {
    struct Ticket: Sendable {
        let scope: NativeWorkspaceOfflineScope
        let id: UUID
        let dirtyGeneration: UInt64
    }
    private struct State {
        var lastSuccess: TimeInterval?
        var dirtyGeneration: UInt64 = 0
        var completedGeneration: UInt64 = 0
        var active: Ticket?
        var completedNamespaces: Set<String> = []
        var forcePending = false
        var retryAfter: TimeInterval = 0
        var lastAdmission: TimeInterval?
    }
    let cooldown: TimeInterval
    private var states: [NativeWorkspaceOfflineScope: State] = [:]
    init(cooldown: TimeInterval = 300) { self.cooldown = cooldown }

    mutating func markDirty(scope: NativeWorkspaceOfflineScope, force: Bool = false) {
        var state = states[scope] ?? State()
        if let active = state.active {
            if state.dirtyGeneration == active.dirtyGeneration { state.dirtyGeneration &+= 1 }
        } else if state.dirtyGeneration == state.completedGeneration {
            state.dirtyGeneration &+= 1
        }
        state.completedNamespaces.removeAll()
        state.forcePending = state.forcePending || force
        states[scope] = state
    }

    mutating func begin(scope: NativeWorkspaceOfflineScope, now: TimeInterval, force: Bool = false) -> Ticket? {
        var state = states[scope] ?? State()
        if force { state.forcePending = true }
        if state.active != nil {
            states[scope] = state
            return nil
        }
        let forced = state.forcePending
        let forcedAdmission = forced ? (state.lastAdmission.map { $0 + 30 } ?? 0) : 0
        // Socket flaps cannot bypass failed-refresh backoff or immediately
        // repeat a full inventory. Retain the force request for the due wake.
        if now < max(state.retryAfter, forcedAdmission) {
            states[scope] = state
            return nil
        }
        if !forced, let last = state.lastSuccess, now - last < cooldown { return nil }
        if forced || state.completedNamespaces.count == 4 { state.completedNamespaces.removeAll() }
        let ticket = Ticket(scope: scope, id: UUID(), dirtyGeneration: state.dirtyGeneration)
        state.active = ticket
        state.lastAdmission = now
        state.forcePending = false
        states[scope] = state
        return ticket
    }

    func needsNamespace(_ namespace: String, ticket: Ticket) -> Bool {
        guard let state = states[ticket.scope], state.active?.id == ticket.id,
              state.dirtyGeneration == ticket.dirtyGeneration else { return true }
        return !state.completedNamespaces.contains(namespace)
    }

    mutating func completedNamespace(_ namespace: String, ticket: Ticket) {
        guard var state = states[ticket.scope], state.active?.id == ticket.id,
              state.dirtyGeneration == ticket.dirtyGeneration else { return }
        state.completedNamespaces.insert(namespace)
        states[ticket.scope] = state
    }

    mutating func finish(_ ticket: Ticket, now: TimeInterval, successful: Bool, interrupted: Bool = false) {
        guard var state = states[ticket.scope], state.active?.id == ticket.id else { return }
        state.active = nil
        if successful, state.dirtyGeneration == ticket.dirtyGeneration, state.completedNamespaces.count == 4 {
            state.lastSuccess = now
            state.completedGeneration = ticket.dirtyGeneration
            state.retryAfter = 0
        } else if !interrupted {
            state.retryAfter = now + 30
        }
        states[ticket.scope] = state
    }

    func delay(scope: NativeWorkspaceOfflineScope, now: TimeInterval) -> TimeInterval {
        guard let state = states[scope] else { return 0 }
        let cooldownRemaining = state.forcePending ? 0 :
            (state.lastSuccess.map { max(0, cooldown - (now - $0)) } ?? 0)
        let forcedRemaining = state.forcePending ?
            (state.lastAdmission.map { max(0, $0 + 30 - now) } ?? 0) : 0
        return max(0, max(cooldownRemaining, max(forcedRemaining, state.retryAfter - now)))
    }

    mutating func reset() { states.removeAll() }
}

@MainActor
enum NativeWorkspaceOfflineRuntime {
    private static var maintenance: Task<Void, Never>?
    private static var maintenanceID: UUID?
    private static var maintenanceTicket: NativeWorkspaceMaintenancePolicy.Ticket?
    private static var maintenanceWake: Task<Void, Never>?
    private static var maintenancePolicy = NativeWorkspaceMaintenancePolicy()
    private static var inventoryFlights: [String: (UUID, Task<Data, Error>)] = [:]

    static func configure(accountID: String, teamID: String?) async throws -> NativeWorkspaceOfflineScope {
        let profile = ServerProfile.current()
        let scope = NativeWorkspaceOfflineScope(accountID: accountID, server: profile.apiBaseURL.absoluteString,
            teamID: teamID, accountGeneration: OfflineStore.shared.scopeGeneration,
            teamEpoch: TeamWorkspaceContext.shared.contextEpoch)
        try await check(scope)
        guard let key = try await CryptoManager.shared.loadMasterKey(for: accountID) else {
            throw UserTasksError.masterKeyUnavailable
        }
        try await check(scope)
        await NativeWorkspaceOfflineCache.shared.configure(scope: scope, masterKey: key)
        do { try await check(scope) }
        catch {
            await NativeWorkspaceOfflineCache.shared.deactivate(ifScope: scope)
            throw error
        }
        return scope
    }

    static func check(_ scope: NativeWorkspaceOfflineScope) async throws {
        try Task.checkCancellation()
        guard scope.accountGeneration == OfflineStore.shared.scopeGeneration,
              scope.server == ServerProfile.current().apiBaseURL.absoluteString,
              scope.teamEpoch == TeamWorkspaceContext.shared.contextEpoch,
              scope.teamID == TeamWorkspaceContext.shared.teamID,
              await AuthManager.currentUserId() == scope.accountID else { throw CancellationError() }
        try Task.checkCancellation()
        guard scope.accountGeneration == OfflineStore.shared.scopeGeneration,
              scope.server == ServerProfile.current().apiBaseURL.absoluteString,
              scope.teamEpoch == TeamWorkspaceContext.shared.contextEpoch,
              scope.teamID == TeamWorkspaceContext.shared.teamID else { throw CancellationError() }
    }

    static func cached(namespace: String, path: String, scope: NativeWorkspaceOfflineScope) async throws -> Data? {
        try await check(scope)
        let data = try await NativeWorkspaceOfflineCache.shared.read(namespace: namespace, path: path, scope: scope)
        try await check(scope)
        return data
    }

    static func request(namespace: String, path: String, scope: NativeWorkspaceOfflineScope,
                        api: APIClient = .shared, retain: Bool = true) async throws -> Data {
        try await check(scope)
        let data = try await NativeWorkspaceRequestFlights.shared.request(path: path,
            profile: ServerProfile.current(), scope: scope, api: api)
        try await check(scope)
        if retain {
            let sanitized = path.contains("/sources") ? try sanitizedResponse(data) : data
            try? await NativeWorkspaceOfflineCache.shared.retain(namespace: namespace, path: path,
                data: sanitized, scope: scope)
            try await check(scope)
        }
        return data
    }

    // Connected-host sessions are live authority, never durable offline presence.
    nonisolated static func sanitizedResponse(_ data: Data) throws -> Data {
        func strip(_ value: Any) -> Any {
            if let rows = value as? [Any] { return rows.map(strip) }
            if let object = value as? [String: Any] {
                var retained = object.filter { !["source_session_id", "sourceSessionId"].contains($0.key) }
                    .mapValues(strip)
                if object["source_id"] != nil || object["sourceId"] != nil {
                    if (object["status"] as? String) == "connected" { retained["status"] = "disconnected" }
                }
                return retained
            }
            return value
        }
        return try JSONSerialization.data(withJSONObject: strip(JSONSerialization.jsonObject(with: data)), options: .sortedKeys)
    }

    static func coalescedInventory(namespace: String, scope: NativeWorkspaceOfflineScope,
                                   operation: @escaping @MainActor () async throws -> Data) async throws -> Data {
        let identity = scope.directoryID + scope.accountGeneration.uuidString + String(scope.teamEpoch) + namespace
        if let (_, task) = inventoryFlights[identity] {
            let data = try await task.value
            try await check(scope)
            return data
        }
        let id = UUID()
        let task = Task(priority: .utility) { try await operation() }
        inventoryFlights[identity] = (id, task)
        defer { if inventoryFlights[identity]?.0 == id { inventoryFlights.removeValue(forKey: identity) } }
        let data = try await task.value
        try await check(scope)
        return data
    }

    nonisolated static func decodeResponse<T: Decodable & Sendable>(_ type: T.Type, data: Data) async throws -> T {
        try await Task.detached(priority: .utility) {
            let decoder = JSONDecoder()
            decoder.keyDecodingStrategy = .convertFromSnakeCase
            return try decoder.decode(type, from: data)
        }.value
    }

    static func inventoryPath(_ base: String, teamID: String?) -> String {
        UserTasksPaths.scoped(base, teamID: teamID)
    }

    static func pagedInventory(namespace: String, collection: String, idKey: String,
                               scope: NativeWorkspaceOfflineScope, api: APIClient = .shared,
                               basePath: String? = nil) async throws -> Data {
        let pages = NativeWorkspaceInventoryCollector()
        var state = await pages.state()
        repeat {
            try await check(scope)
            var path = (basePath ?? "/v1/\(namespace)") + "?paginate=true&limit=500"
            if let cursor = state.0 { path += "&cursor=" + UserTasksPaths.escaped(cursor) }
            path = UserTasksPaths.scoped(path, teamID: scope.teamID)
            let data = try await request(namespace: namespace, path: path, scope: scope, api: api, retain: false)
            try await pages.append(data, collection: collection, idKey: idKey)
            state = await pages.state()
        } while !state.1
        let data = try await pages.snapshot(collection: collection)
        try await check(scope)
        return data
    }

    static func markDirty(accountID: String, teamID: String?, force: Bool = false) {
        let scope = capturedScope(accountID: accountID, teamID: teamID)
        maintenancePolicy.markDirty(scope: scope, force: force)
    }

    private static func capturedScope(accountID: String, teamID: String?) -> NativeWorkspaceOfflineScope {
        NativeWorkspaceOfflineScope(accountID: accountID, server: ServerProfile.current().apiBaseURL.absoluteString,
            teamID: teamID, accountGeneration: OfflineStore.shared.scopeGeneration,
            teamEpoch: TeamWorkspaceContext.shared.contextEpoch)
    }

    static func startMaintenance(accountID: String, teamID: String?, force: Bool = false) {
        let captured = capturedScope(accountID: accountID, teamID: teamID)
        if maintenance != nil, maintenanceTicket?.scope != captured { pauseMaintenance() }
        if maintenance != nil {
            if force { maintenancePolicy.markDirty(scope: captured, force: true) }
            return
        }
        maintenanceWake?.cancel()
        maintenanceWake = nil
        guard let ticket = maintenancePolicy.begin(scope: captured, now: ProcessInfo.processInfo.systemUptime, force: force) else {
            scheduleMaintenanceWake(accountID: accountID, teamID: teamID, scope: captured)
            return
        }
        let id = UUID()
        maintenanceID = id
        maintenanceTicket = ticket
        maintenance = Task(priority: .utility) {
            var successful = false
            defer {
                maintenancePolicy.finish(ticket, now: ProcessInfo.processInfo.systemUptime, successful: successful,
                                         interrupted: Task.isCancelled)
                if maintenanceID == id {
                    maintenance = nil
                    maintenanceID = nil
                    maintenanceTicket = nil
                    scheduleMaintenanceWake(accountID: accountID, teamID: teamID, scope: captured)
                }
            }
            do {
                let scope = try await configure(accountID: accountID, teamID: teamID)
                guard scope == captured else { throw CancellationError() }
                var allSucceeded = true
                for namespace in ["workflows", "user-tasks", "user-plans", "projects"] {
                    try await check(scope)
                    guard maintenancePolicy.needsNamespace(namespace, ticket: ticket) else { continue }
                    do {
                        switch namespace {
                        case "workflows": try await WorkflowAPI().maintainOffline(scope: scope)
                        case "user-tasks": try await UserTasksService().maintainOffline(scope: scope)
                        case "user-plans": try await UserPlansService().maintainOffline(scope: scope)
                        default: try await ProjectsWorkspaceService().maintainOffline(scope: scope)
                        }
                        try await check(scope)
                        maintenancePolicy.completedNamespace(namespace, ticket: ticket)
                    } catch {
                        try await check(scope)
                        allSucceeded = false
                    }
                }
                successful = allSucceeded
            } catch { /* Keep previous snapshots and retry unfinished namespaces. */ }
        }
    }

    private static func scheduleMaintenanceWake(accountID: String, teamID: String?, scope: NativeWorkspaceOfflineScope) {
        maintenanceWake?.cancel()
        // Failed/partial refreshes retry with a grace period, never a hot loop.
        let delay = max(2, maintenancePolicy.delay(scope: scope, now: ProcessInfo.processInfo.systemUptime))
        maintenanceWake = Task(priority: .utility) {
            do {
                try await Task.sleep(for: .seconds(delay))
                try await check(scope)
                maintenanceWake = nil
                startMaintenance(accountID: accountID, teamID: teamID)
            } catch { }
        }
    }

    static func pauseMaintenance() {
        maintenanceWake?.cancel()
        maintenanceWake = nil
        maintenance?.cancel()
        if let ticket = maintenanceTicket {
            maintenancePolicy.finish(ticket, now: ProcessInfo.processInfo.systemUptime, successful: false, interrupted: true)
        }
        maintenance = nil
        maintenanceID = nil
        maintenanceTicket = nil
        for (_, task) in inventoryFlights.values { task.cancel() }
        inventoryFlights.removeAll()
    }

    static func deactivate() async {
        pauseMaintenance()
        maintenancePolicy.reset()
        await NativeWorkspaceOfflineCache.shared.deactivate()
    }
}

/// Refresh all readable contexts without selecting them or invalidating the
/// foreground cache actor. This only reads explicit account/Team routes.
@MainActor
enum TeamWorkspaceOfflineRetention {
    static let chatMetadataChanged = Notification.Name("OpenMates.allContextChatMetadataChanged")
    private static var task: Task<Void, Never>?
    private static var operation = UUID()

    typealias Transport = @MainActor (String, TeamWorkspaceFence) async throws -> Data
    typealias Membership = @MainActor (String, TeamWorkspaceFence) async throws -> TeamWorkspaceTeam

    static func refresh(fence: TeamWorkspaceFence, teams: [TeamWorkspaceTeam], removedIDs: Set<String>) {
        task?.cancel()
        let token = UUID(); operation = token
        task = Task(priority: .utility) {
            do {
                try await fence.check()
                guard let key = try await CryptoManager.shared.loadMasterKey(for: fence.accountID) else { return }
                try await retain(fence: fence, teams: teams, removedIDs: removedIDs, masterKey: key,
                    cache: NativeWorkspaceOfflineCache(), transport: { path, fence in
                        try await APIClient.shared.request(.get, path: path, serverProfile: fence.server,
                            expectedAccountID: fence.accountID, expectedScope: fence.scope)
                    }, membership: { id, fence in try await TeamWorkspaceService().getTeam(id, fence: fence) },
                    isCurrent: { operation == token }, revoke: { id, fence in
                        await TeamWorkspaceContext.shared.revokeCachedTeam(id, fence: fence)
                    }, publishChats: { rows, fence in
                        try await fence.check()
                        OfflineStore.shared.persistChats(rows)
                        NotificationCenter.default.post(name: chatMetadataChanged, object: nil,
                            userInfo: ["accountID": fence.accountID, "scope": fence.scope, "server": fence.server])
                    })
            } catch { /* Offline or scope changed: previous ciphertext remains intact. */ }
            if operation == token { task = nil }
        }
    }

    /// Injectable reader; tests use private directories and transports only. The
    /// foreground singleton is never reconfigured by the all-context traversal.
    static func retain(fence: TeamWorkspaceFence, teams: [TeamWorkspaceTeam], removedIDs: Set<String>,
                       masterKey: SymmetricKey, cache: NativeWorkspaceOfflineCache,
                       transport: @escaping Transport, membership: @escaping Membership,
                       isCurrent: @escaping @MainActor () -> Bool = { true },
                       revoke: @escaping @MainActor (String, TeamWorkspaceFence) async -> Void = { _, _ in },
                       publishChats: @escaping @MainActor ([Chat], TeamWorkspaceFence) async throws -> Void = { _, _ in }) async throws {
        let readable = Set(teams.filter(\.canRead).map(\.id))
        func check() async throws {
            try await fence.check(); try Task.checkCancellation()
            guard isCurrent() else { throw CancellationError() }
        }
        for id in removedIDs { try await check(); try await cache.purge(scope: scope(teamID: id, fence: fence)) }
        for id in [String?.none] + readable.sorted().map(Optional.some) {
            try await check()
            let captured = scope(teamID: id, fence: fence)
            do {
                if let id { guard try await membership(id, fence).canRead else { throw TeamWorkspaceError.unavailableTeam } }
                await cache.configure(scope: captured, masterKey: masterKey)
                let namespaces = ["chat-metadata", "workflows", "user-tasks", "user-plans", "projects"] + (id == nil ? [] : ["team-management", "team-summary", "team-images"])
                for namespace in namespaces {
                    try await check()
                    do {
                        let currentTeam: TeamWorkspaceTeam?
                        if let id { currentTeam = try await membership(id, fence) } else { currentTeam = nil }
                        let revision = try await cache.beginRefresh(namespace: namespace, scope: captured)
                        let responses = try await collect(namespace: namespace, teamID: id, fence: fence, transport: transport, managementTeam: currentTeam)
                        try await check()
                        if let id {
                            let authorized = try await membership(id, fence)
                            guard authorized.canRead else { throw TeamWorkspaceError.unavailableTeam }
                            if ["team-management", "team-summary"].contains(namespace), authorized.role != currentTeam?.role { throw CancellationError() }
                        }
                        try await cache.commit(namespace: namespace, responses: responses, scope: captured, revision: revision,
                            complete: namespace != "chat-metadata")
                        if namespace == "chat-metadata", let data = responses.values.first {
                            try await check()
                            try await publishChats(decodeChatMetadata(data, teamID: id), fence)
                        }
                    } catch {
                        try await check()
                        if isRevocation(error), let id {
                            // A role-only endpoint denial does not revoke readable
                            // membership. Only the authoritative membership read can.
                            do {
                                guard try await membership(id, fence).canRead else { throw TeamWorkspaceError.unavailableTeam }
                            } catch {
                                if isRevocation(error) {
                                    try await cache.purge(scope: captured); await revoke(id, fence); break
                                }
                                throw error
                            }
                        }
                        // Other namespace failures leave the previous complete blob.
                    }
                    await Task.yield()
                }
            } catch {
                try await check()
                if isRevocation(error), let id {
                    try await cache.purge(scope: captured); await revoke(id, fence)
                }
            }
        }
    }

    /// The native REST chat list is a bounded authorized metadata page, not a
    /// complete account history receipt. Its wrappers are scoped by the server.
    static func decodeChatMetadata(_ data: Data, teamID: String?) throws -> [Chat] {
        guard let raw = try JSONSerialization.jsonObject(with: data) as? [String: Any],
              let rows = raw["chats"] as? [[String: Any]], rows.count <= 100 else { throw TeamWorkspaceError.invalidResponse }
        let decoder = JSONDecoder(); decoder.keyDecodingStrategy = .convertFromSnakeCase
        var seen: Set<String> = []
        return try rows.map { source in
            guard let id = source["id"] as? String, !id.isEmpty, seen.insert(id).inserted,
                  source["team_id"] == nil || source["team_id"] is NSNull || source["team_id"] as? String == teamID else { throw TeamWorkspaceError.invalidResponse }
            var row = source
            if let teamID { row["team_id"] = teamID } else { row.removeValue(forKey: "team_id") }
            let chatHash = ChatKeyWrapperRecord.hashedChatId(for: id)
            let recipientHash = teamID.map { SHA256.hash(data: Data($0.utf8)).map { String(format: "%02x", $0) }.joined() }
            let wrappers = (source["chat_key_wrappers"] as? [[String: Any]] ?? []).filter { wrapper in
                (wrapper["hashed_chat_id"] as? String) == chatHash &&
                    (wrapper["key_type"] as? String) == (teamID == nil ? "master" : "team") &&
                    (recipientHash == nil || wrapper["hashed_team_id"] as? String == recipientHash) &&
                    ((wrapper["expires_at"] as? Double).map { $0 > Date().timeIntervalSince1970 } ?? true)
            }.sorted { left, right in
                let l = (left["team_key_epoch"] as? Int ?? 0, left["wrapper_version"] as? Int ?? 0, left["id"] as? String ?? "")
                let r = (right["team_key_epoch"] as? Int ?? 0, right["wrapper_version"] as? Int ?? 0, right["id"] as? String ?? "")
                return l > r
            }
            if let encrypted = wrappers.first?["encrypted_chat_key"] as? String { row["encrypted_chat_key"] = encrypted }
            // No plaintext title/profile is accepted into this background cache.
            for key in ["title", "category", "icon", "chat_summary"] { row.removeValue(forKey: key) }
            return try decoder.decode(Chat.self, from: JSONSerialization.data(withJSONObject: row))
        }
    }

    private static func isRevocation(_ error: Error) -> Bool {
        if case TeamWorkspaceError.unavailableTeam = error { return true }
        if case APIError.httpError(let status, _) = error { return [401, 403, 404].contains(status) }
        return false
    }

    private static func scope(teamID: String?, fence: TeamWorkspaceFence) -> NativeWorkspaceOfflineScope {
        .init(accountID: fence.accountID, server: fence.server.apiBaseURL.absoluteString,
            teamID: teamID, accountGeneration: fence.scope, teamEpoch: TeamWorkspaceContext.shared.contextEpoch)
    }

    private static func get(_ path: String, teamID: String?, fence: TeamWorkspaceFence, transport: @escaping Transport) async throws -> Data {
        try await fence.check(); try Task.checkCancellation()
        let scopedPath = UserTasksPaths.scoped(path, teamID: teamID)
        let captured = scope(teamID: teamID, fence: fence)
        let identity = captured.directoryID + captured.accountGeneration.uuidString + String(captured.teamEpoch) + scopedPath
        let data = try await NativeWorkspaceRequestFlights.shared.perform(identity: identity) {
            try await transport(scopedPath, fence)
        }
        try await fence.check(); try Task.checkCancellation()
        return data
    }

    private static func paged(_ base: String, collection: String, idKey: String,
                              teamID: String?, fence: TeamWorkspaceFence, transport: @escaping Transport) async throws -> Data {
        var pages = NativeWorkspaceInventoryPages()
        repeat {
            var path = base + "?paginate=true&limit=500"
            if let cursor = pages.nextCursor { path += "&cursor=" + UserTasksPaths.escaped(cursor) }
            try pages.append(await get(path, teamID: teamID, fence: fence, transport: transport), collection: collection, idKey: idKey)
        } while !pages.isComplete
        return try pages.snapshot(collection: collection)
    }

    private static func collect(namespace: String, teamID: String?, fence: TeamWorkspaceFence, transport: @escaping Transport,
                                managementTeam: TeamWorkspaceTeam? = nil) async throws -> [String: Data] {
        if namespace == "chat-metadata" {
            let path = UserTasksPaths.scoped("/v1/chats?limit=100&offset=0", teamID: teamID)
            let data = try await get(path, teamID: nil, fence: fence, transport: transport)
            _ = try decodeChatMetadata(data, teamID: teamID)
            return [path: data]
        }
        if namespace == "team-management" {
            guard let team = managementTeam, team.canRead else { throw TeamWorkspaceError.unavailableTeam }
            let membersPath = SettingsTeamsService.path(team.id, suffix: "members")
            let members = try await get(membersPath, teamID: nil, fence: fence, transport: transport)
            guard let raw = try JSONSerialization.jsonObject(with: members) as? [String: Any], raw["members"] is [[String: Any]] else { throw TeamWorkspaceError.invalidResponse }
            var responses = [membersPath: members]
            if team.canManage {
                let invitesPath = SettingsTeamsService.path(team.id, suffix: "invites")
                let invites = try await get(invitesPath, teamID: nil, fence: fence, transport: transport)
                guard let raw = try JSONSerialization.jsonObject(with: invites) as? [String: Any], raw["invites"] is [[String: Any]] else { throw TeamWorkspaceError.invalidResponse }
                let detailPath = String(SettingsTeamsService.path(team.id, suffix: "").dropLast())
                let detail = try await get(detailPath, teamID: nil, fence: fence, transport: transport)
                guard let raw = try JSONSerialization.jsonObject(with: detail) as? [String: Any], raw["team"] is [String: Any] else { throw TeamWorkspaceError.invalidResponse }
                responses[invitesPath] = invites; responses[detailPath] = detail
            }
            return responses
        }
        if namespace == "team-summary" {
            guard let team = managementTeam, team.canRead else { throw TeamWorkspaceError.unavailableTeam }
            let memoriesPath = SettingsTeamsService.path(team.id, suffix: "memories")
            let memories = try await get(memoriesPath, teamID: nil, fence: fence, transport: transport)
            guard let raw = try JSONSerialization.jsonObject(with: memories) as? [String: Any], raw["memories"] is [Any] else { throw TeamWorkspaceError.invalidResponse }
            var responses = [memoriesPath: memories]
            if team.canViewBilling {
                let path = SettingsTeamsService.path(team.id, suffix: "billing")
                let billing = try await get(path, teamID: nil, fence: fence, transport: transport)
                guard let raw = try JSONSerialization.jsonObject(with: billing) as? [String: Any], raw["billing"] is [String: Any] else { throw TeamWorkspaceError.invalidResponse }
                responses[path] = billing
            }
            return responses
        }
        if namespace == "team-images" {
            guard let team = managementTeam, team.canRead else { throw TeamWorkspaceError.unavailableTeam }
            let path = SettingsTeamsService.path(team.id, suffix: "profile-image")
            guard team.profileImageMetadata.mode == "uploaded", team.profileImageMetadata.imageURL == path else { return [:] }
            let data = try await get(path, teamID: nil, fence: fence, transport: transport)
            guard data.count <= 5 * 1_024 * 1_024, NativeImageRaster.uprightImage(from: data) != nil else { throw TeamWorkspaceError.invalidResponse }
            return [path: data]
        }
        let collection = ["workflows": "workflows", "user-tasks": "tasks", "user-plans": "plans", "projects": "projects"][namespace]!
        let idKey = ["workflows": "id", "user-tasks": "task_id", "user-plans": "plan_id", "projects": "project_id"][namespace]!
        let base = "/v1/" + namespace
        let list: Data
        if namespace == "user-tasks" || namespace == "user-plans" {
            list = try await paged(base, collection: collection, idKey: idKey, teamID: teamID, fence: fence, transport: transport)
        } else { list = try await get(base, teamID: teamID, fence: fence, transport: transport) }
        guard let json = try JSONSerialization.jsonObject(with: list) as? [String: Any],
              let rows = json[collection] as? [[String: Any]] else { throw TeamWorkspaceError.invalidResponse }
        var responses = [UserTasksPaths.scoped(base, teamID: teamID): list]
        for row in rows {
            if let returnedTeam = row["team_id"] as? String, returnedTeam != teamID { throw TeamWorkspaceError.invalidResponse }
            guard let id = row[idKey] as? String else { throw TeamWorkspaceError.invalidResponse }
            let path = base + "/" + UserTasksPaths.escaped(id)
            if namespace == "workflows" {
                let detail = try await get(path, teamID: teamID, fence: fence, transport: transport)
                guard let payload = try JSONSerialization.jsonObject(with: detail) as? [String: Any],
                      let workflow = payload["workflow"] as? [String: Any], workflow["id"] as? String == id,
                      workflow["current_version_id"] as? String == row["current_version_id"] as? String else { throw TeamWorkspaceError.invalidResponse }
                responses[UserTasksPaths.scoped(path, teamID: teamID)] = detail
            } else if namespace == "projects" {
                for suffix in ["items", "sources", "settings"] {
                    let route = path + "/" + suffix
                    responses[UserTasksPaths.scoped(route, teamID: teamID)] = try NativeWorkspaceOfflineRuntime.sanitizedResponse(await get(route, teamID: teamID, fence: fence, transport: transport))
                }
            } else if namespace == "user-plans" {
                for (suffix, name) in [("assumptions", "assumptions"), ("criteria", "criteria"), ("verification", "verifications"), ("reference-patterns", "reference_patterns")] {
                    let route = path + "/" + suffix
                    responses[UserTasksPaths.scoped(route, teamID: teamID)] = try await paged(route, collection: name, idKey: "id", teamID: teamID, fence: fence, transport: transport)
                }
            } else {
                if teamID == nil {
                    let route = path + "/dependencies"
                    responses[route] = try await get(route, teamID: teamID, fence: fence, transport: transport)
                }
                var cursor: String?; var seen: Set<String> = []
                repeat {
                    let route = UserTasksPaths.activity(id, teamID: teamID, cursor: cursor)
                    let page = try await get(route, teamID: nil, fence: fence, transport: transport)
                    guard let raw = try JSONSerialization.jsonObject(with: page) as? [String: Any] else { throw TeamWorkspaceError.invalidResponse }
                    responses[route] = page
                    cursor = raw["next_cursor"] as? String
                    if let cursor, !seen.insert(cursor).inserted { throw TeamWorkspaceError.invalidResponse }
                } while cursor != nil
            }
        }
        return responses
    }
}
