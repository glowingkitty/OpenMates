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
