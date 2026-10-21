// Web sources: services/workflowService.ts, userTaskService.ts, userPlanService.ts, projectService.ts
// Specification: specifications/features/apple-offline-workspaces/specification.yml
// Assertions: apple-workspaces.offline-complete, apple-workspaces.local-first,
// apple-workspaces.isolation, apple-workspaces.maintenance
import CryptoKit
import Foundation
import CoreFoundation

enum NativeWorkspaceReadFailure {
    static func isCancellation(_ error: Error) -> Bool {
        error is CancellationError || (error as? URLError)?.code == .cancelled
    }

    static func isTransient(_ error: Error) -> Bool {
        if let error = error as? URLError {
            return [.notConnectedToInternet, .networkConnectionLost, .timedOut,
                    .cannotFindHost, .cannotConnectToHost, .dnsLookupFailed].contains(error.code)
        }
        if case APIError.httpError(let status, _) = error { return status == 408 || status == 429 || status >= 500 }
        return false
    }
}

/// A fetched README is the only Project file body retained offline. Source sessions
/// are intentionally absent: cached bytes never authorize a live remote read.
struct ProjectReadmeOfflineSnapshot: Codable, Sendable {
    let binding: String
    let markdown: String
    let truncated: Bool
    let origin: String
    let sourceID: String?
    let sourceKeyEpoch: Int?
    var images: [String: Data]

    var document: ProjectWorkspaceReadme {
        .init(markdown: markdown, truncated: truncated, origin: origin,
              sourceID: sourceID, sourceKeyEpoch: sourceKeyEpoch)
    }

    func isCompatible(with contents: ProjectWorkspaceContents) -> Bool {
        guard origin == "connected" else { return true }
        guard let source = contents.sources.first(where: { $0.id == sourceID && $0.capabilities.contains("read") }) else { return false }
        // The server omits an offline host's epoch; absence is not a rotation.
        return source.keyEpoch == nil || source.keyEpoch == sourceKeyEpoch
    }

    static func binding(project: ProjectWorkspaceProject, contents: ProjectWorkspaceContents) throws -> String {
        let keyHash = project.key.withUnsafeBytes { SHA256.hash(data: Data($0)).map { String(format: "%02x", $0) }.joined() }
        let items = contents.items.filter { $0.kind == "embed" }.sorted { $0.id < $1.id }.map {
            ["id": $0.id, "target": $0.targetID, "metadata": $0.metadata, "name": $0.name,
             "folder": $0.folderHash as Any? ?? NSNull(), "created": $0.createdAt] as [String: Any]
        }
        let sources = contents.sources.filter { $0.capabilities.contains("read") }.sorted { $0.id < $1.id }.map {
            ["id": $0.id, "metadata": $0.metadata] as [String: Any]
        }
        let bytes = try JSONSerialization.data(withJSONObject: ["key": keyHash, "items": items, "sources": sources], options: .sortedKeys)
        return SHA256.hash(data: bytes).map { String(format: "%02x", $0) }.joined()
    }
}

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
    private let writeCiphertext: @Sendable (Data, URL) throws -> Void
    private var activeScope: NativeWorkspaceOfflineScope?
    private var key: SymmetricKey?
    private var snapshots: [String: Snapshot] = [:]
    private var revisions: [String: UUID] = [:]

    init(directory: URL? = nil, writeCiphertext: @escaping @Sendable (Data, URL) throws -> Void = {
        try $0.write(to: $1, options: .atomic)
    }) {
        self.writeCiphertext = writeCiphertext
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

    private static func digest(_ value: String) -> String {
        SHA256.hash(data: Data(value.utf8)).map { String(format: "%02x", $0) }.joined()
    }

    private func readmeImagesDirectory(projectID: String, scope: NativeWorkspaceOfflineScope) -> URL {
        directory.appendingPathComponent(scope.directoryID, isDirectory: true)
            .appendingPathComponent("readme-images", isDirectory: true)
            .appendingPathComponent(Self.digest(projectID), isDirectory: true)
    }

    private func imageNamespace(projectID: String, snapshot: ProjectReadmeOfflineSnapshot, source: String) throws -> String {
        var metadata = snapshot
        metadata.images = [:]
        let encoder = JSONEncoder()
        encoder.outputFormatting = .sortedKeys
        let document = SHA256.hash(data: try encoder.encode(metadata)).map { String(format: "%02x", $0) }.joined()
        return ["project-readme-image", Self.digest(projectID), document, Self.digest(source)].joined(separator: ":")
    }

    private func file(_ namespace: String, scope: NativeWorkspaceOfflineScope) -> URL {
        let root = directory.appendingPathComponent(scope.directoryID, isDirectory: true)
        let parts = namespace.split(separator: ":")
        if parts.count == 4, parts[0] == "project-readme-image",
           parts.dropFirst().allSatisfy({ $0.count == 64 && $0.allSatisfy { $0.isHexDigit } }) {
            return root.appendingPathComponent("readme-images", isDirectory: true)
                .appendingPathComponent(String(parts[1]), isDirectory: true)
                .appendingPathComponent(String(parts[2]), isDirectory: true)
                .appendingPathComponent(String(parts[3]) + ".aesgcm")
        }
        return root.appendingPathComponent(Self.digest(namespace) + ".aesgcm")
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
        if !namespace.hasPrefix("project-readme") { snapshots[namespace] = loaded }
        return loaded
    }

    func read(namespace: String, path: String, scope: NativeWorkspaceOfflineScope) throws -> Data? {
        try snapshot(namespace, scope: scope).responses[path]
    }

    private func readmeSnapshot(projectID: String, binding: String, scope: NativeWorkspaceOfflineScope) throws -> ProjectReadmeOfflineSnapshot? {
        guard let data = try read(namespace: "project-readme:" + projectID, path: "document", scope: scope) else { return nil }
        let value = try JSONDecoder().decode(ProjectReadmeOfflineSnapshot.self, from: data)
        return value.binding == binding ? value : nil
    }

    func projectReadme(projectID: String, binding: String, scope: NativeWorkspaceOfflineScope) throws -> ProjectReadmeOfflineSnapshot? {
        guard var value = try readmeSnapshot(projectID: projectID, binding: binding, scope: scope) else { return nil }
        // Legacy envelopes contain at most eight images; never hand original-byte
        // inventories to the foreground. Each image is reopened independently.
        value.images = [:]
        return value
    }

    private func matches(_ snapshot: ProjectReadmeOfflineSnapshot, document: ProjectWorkspaceReadme) -> Bool {
        snapshot.markdown == document.markdown && snapshot.truncated == document.truncated &&
            snapshot.origin == document.origin && snapshot.sourceID == document.sourceID &&
            snapshot.sourceKeyEpoch == document.sourceKeyEpoch
    }

    func projectReadmeImage(source: String, document: ProjectWorkspaceReadme, projectID: String,
                            binding: String, scope: NativeWorkspaceOfflineScope) throws -> Data? {
        guard let value = try readmeSnapshot(projectID: projectID, binding: binding, scope: scope),
              matches(value, document: document) else { return nil }
        let namespace = try imageNamespace(projectID: projectID, snapshot: value, source: source)
        if let data = try read(namespace: namespace, path: "image", scope: scope) {
            guard !data.isEmpty, data.count <= 2 * 1_024 * 1_024 else { throw URLError(.dataLengthExceedsMaximum) }
            // An earlier image write may have succeeded while its metadata
            // compaction failed. Retry on hits as well as first migration.
            try compactLegacyReadmeImage(source: source, snapshot: value, projectID: projectID, scope: scope)
            return data
        }
        guard let legacy = value.images[source], !legacy.isEmpty,
              legacy.count <= 2 * 1_024 * 1_024 else { return nil }
        // Migrate one bounded original at a time. A failed object or metadata
        // write leaves its legacy bytes readable; neither write clears an overview.
        do {
            try retain(namespace: namespace, path: "image", data: legacy, scope: scope)
            try compactLegacyReadmeImage(source: source, snapshot: value, projectID: projectID, scope: scope)
        } catch {
            _ = try check(scope)
        }
        return legacy
    }

    private func compactLegacyReadmeImage(source: String, snapshot: ProjectReadmeOfflineSnapshot,
                                           projectID: String, scope: NativeWorkspaceOfflineScope) throws {
        guard snapshot.images[source] != nil else { return }
        do {
            // This actor does not suspend between rechecking the current
            // document and its atomic metadata rewrite.
            guard var current = try readmeSnapshot(projectID: projectID, binding: snapshot.binding, scope: scope),
                  matches(current, document: snapshot.document), current.images.removeValue(forKey: source) != nil else { return }
            try retain(namespace: "project-readme:" + projectID, path: "document", data: JSONEncoder().encode(current), scope: scope)
        } catch {
            // A valid independent object remains readable after disk failure.
            // Cancellation or a changed scope still rejects the response.
            _ = try check(scope)
        }
    }

    func retainProjectReadme(_ document: ProjectWorkspaceReadme, projectID: String, binding: String,
                             scope: NativeWorkspaceOfflineScope) throws {
        guard document.markdown.utf8.count <= 2 * 1_024 * 1_024 else { throw URLError(.dataLengthExceedsMaximum) }
        let previous = try readmeSnapshot(projectID: projectID, binding: binding, scope: scope)
        let keepImages = previous.map { matches($0, document: document) } == true
        let value = ProjectReadmeOfflineSnapshot(binding: binding, markdown: document.markdown,
            truncated: document.truncated, origin: document.origin, sourceID: document.sourceID,
            sourceKeyEpoch: document.sourceKeyEpoch, images: keepImages ? previous?.images ?? [:] : [:])
        try retain(namespace: "project-readme:" + projectID, path: "document", data: JSONEncoder().encode(value), scope: scope)
        // The actor has no suspension between the successful metadata swap and
        // pruning. An image for an older document cannot attach or prune this one.
        try pruneReadmeImages(projectID: projectID, keeping: value, scope: scope)
    }

    func retainProjectReadmeImage(_ data: Data, source: String, document: ProjectWorkspaceReadme,
                                  projectID: String, binding: String, scope: NativeWorkspaceOfflineScope) throws {
        guard !data.isEmpty, data.count <= 2 * 1_024 * 1_024 else { throw URLError(.dataLengthExceedsMaximum) }
        guard var value = try readmeSnapshot(projectID: projectID, binding: binding, scope: scope),
              matches(value, document: document) else { return }
        try retain(namespace: imageNamespace(projectID: projectID, snapshot: value, source: source),
                   path: "image", data: data, scope: scope)
        if value.images.removeValue(forKey: source) != nil {
            try retain(namespace: "project-readme:" + projectID, path: "document", data: JSONEncoder().encode(value), scope: scope)
        }
    }

    func clearProjectReadme(projectID: String, scope: NativeWorkspaceOfflineScope) throws {
        let namespace = "project-readme:" + projectID
        let revision = try beginRefresh(namespace: namespace, scope: scope)
        try commit(namespace: namespace, responses: [:], scope: scope, revision: revision)
        try pruneReadmeImages(projectID: projectID, keeping: nil, scope: scope)
    }

    private func pruneReadmeImages(projectID: String, keeping value: ProjectReadmeOfflineSnapshot?,
                                   scope: NativeWorkspaceOfflineScope) throws {
        _ = try check(scope)
        if let value {
            guard let current = try readmeSnapshot(projectID: projectID, binding: value.binding, scope: scope),
                  matches(current, document: value.document) else { return }
        } else {
            guard try read(namespace: "project-readme:" + projectID, path: "document", scope: scope) == nil else { return }
        }
        let root = readmeImagesDirectory(projectID: projectID, scope: scope)
        guard FileManager.default.fileExists(atPath: root.path) else { return }
        let retainedGeneration = try value.map {
            String(try imageNamespace(projectID: projectID, snapshot: $0, source: "").split(separator: ":")[2])
        }
        for child in try FileManager.default.contentsOfDirectory(at: root, includingPropertiesForKeys: nil) where child.lastPathComponent != retainedGeneration {
            _ = try check(scope)
            try FileManager.default.removeItem(at: child)
        }
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
        if !namespace.hasPrefix("project-readme-image:") { revisions[namespace] = UUID() }
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
        try writeCiphertext(ciphertext, url)
        var excluded = url
        var values = URLResourceValues()
        values.isExcludedFromBackup = true
        try? excluded.setResourceValues(values)
        if !namespace.hasPrefix("project-readme") { snapshots[namespace] = snapshot }
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
    let requiredNamespaces: Set<String>
    private var states: [NativeWorkspaceOfflineScope: State] = [:]
    init(cooldown: TimeInterval = 300,
         requiredNamespaces: Set<String> = ["workflows", "user-tasks", "user-plans", "projects"]) {
        self.cooldown = cooldown
        self.requiredNamespaces = requiredNamespaces
    }

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
        if forced || state.completedNamespaces.isSuperset(of: requiredNamespaces) { state.completedNamespaces.removeAll() }
        let ticket = Ticket(scope: scope, id: UUID(), dirtyGeneration: state.dirtyGeneration)
        // Admission supersedes the settled inventory. A failed or paused forced
        // replacement must not inherit that inventory's remaining cooldown.
        state.lastSuccess = nil
        state.active = ticket
        state.lastAdmission = now
        state.forcePending = false
        states[scope] = state
        return ticket
    }

    func isCurrent(_ ticket: Ticket) -> Bool {
        guard let state = states[ticket.scope] else { return false }
        return state.active?.id == ticket.id && state.dirtyGeneration == ticket.dirtyGeneration
    }

    mutating func requestRefresh(scope: NativeWorkspaceOfflineScope) {
        // A reconnect/dirty burst queues one replacement generation.
        guard states[scope]?.forcePending != true else { return }
        markDirty(scope: scope, force: true)
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
        if successful, state.dirtyGeneration == ticket.dirtyGeneration, state.completedNamespaces.isSuperset(of: requiredNamespaces) {
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

/// All-context progress belongs to account/server/Team, not the selected Team's
/// navigation epoch. Live operation fences still guard every read and commit.
struct NativeWorkspaceAllContextMaintenancePolicy {
    struct Cohort {
        let scope: NativeWorkspaceOfflineScope
        let membershipRevision: String
    }
    private var policies: [NativeWorkspaceOfflineScope: NativeWorkspaceMaintenancePolicy] = [:]
    private var revisions: [NativeWorkspaceOfflineScope: String] = [:]
    private var rosterRevisions: [NativeWorkspaceOfflineScope: String] = [:]
    private var namespaceCursors: [NativeWorkspaceOfflineScope: Int] = [:]
    private var order: [NativeWorkspaceOfflineScope] = []
    private var cursor = 0
    var count: Int { order.count }

    static func namespaces(teamID: String?) -> [String] {
        ["chat-metadata", "workflows", "user-tasks", "user-plans", "projects"] +
            (teamID == nil ? [] : ["team-management", "team-summary", "team-images"])
    }

    mutating func update(_ cohorts: [Cohort], force: Bool = false) {
        let next = order.isEmpty ? nil : order[cursor % order.count]
        let valid = Set(cohorts.map(\.scope))
        policies = policies.filter { valid.contains($0.key) }
        revisions = revisions.filter { valid.contains($0.key) }
        rosterRevisions = rosterRevisions.filter { valid.contains($0.key) }
        namespaceCursors = namespaceCursors.filter { valid.contains($0.key) }
        order = cohorts.map(\.scope)
        cursor = next.flatMap { order.firstIndex(of: $0) } ?? 0
        for cohort in cohorts {
            let previous = rosterRevisions[cohort.scope]
            if policies[cohort.scope] == nil {
                policies[cohort.scope] = NativeWorkspaceMaintenancePolicy(
                    requiredNamespaces: Set(Self.namespaces(teamID: cohort.scope.teamID)))
            }
            if previous.map({ $0 != cohort.membershipRevision }) == true,
               revisions[cohort.scope] != cohort.membershipRevision {
                policies[cohort.scope]?.markDirty(scope: cohort.scope, force: true)
                namespaceCursors[cohort.scope] = 0
            }
            if force { policies[cohort.scope]?.requestRefresh(scope: cohort.scope) }
            // An unchanged cached roster must not replace a newer authoritative
            // membership revision observed while resuming a Team.
            if previous == nil || previous != cohort.membershipRevision { revisions[cohort.scope] = cohort.membershipRevision }
            rosterRevisions[cohort.scope] = cohort.membershipRevision
        }
    }

    mutating func markDirty(_ scope: NativeWorkspaceOfflineScope) {
        policies[scope]?.requestRefresh(scope: scope)
    }

    mutating func revalidate(scope: NativeWorkspaceOfflineScope, membershipRevision: String) {
        guard let previous = revisions[scope], previous != membershipRevision else { return }
        revisions[scope] = membershipRevision
        policies[scope]?.markDirty(scope: scope, force: true)
        namespaceCursors[scope] = 0
    }

    func isCurrent(_ ticket: NativeWorkspaceMaintenancePolicy.Ticket) -> Bool {
        policies[ticket.scope]?.isCurrent(ticket) == true
    }

    mutating func beginNext(now: TimeInterval, excluding visited: Set<NativeWorkspaceOfflineScope> = []) -> NativeWorkspaceMaintenancePolicy.Ticket? {
        for _ in 0..<order.count {
            let scope = order[cursor % order.count]
            cursor = (cursor + 1) % order.count
            guard !visited.contains(scope) else { continue }
            if let ticket = policies[scope]?.begin(scope: scope, now: now) { return ticket }
        }
        return nil
    }

    func namespaces(ticket: NativeWorkspaceMaintenancePolicy.Ticket) -> [String] {
        guard policies[ticket.scope]?.isCurrent(ticket) == true else { return [] }
        let names = Self.namespaces(teamID: ticket.scope.teamID)
        let start = namespaceCursors[ticket.scope, default: 0] % names.count
        return Array(names[start...] + names[..<start]).filter {
            policies[ticket.scope]?.needsNamespace($0, ticket: ticket) == true
        }
    }

    mutating func beganNamespace(_ name: String, ticket: NativeWorkspaceMaintenancePolicy.Ticket) {
        guard policies[ticket.scope]?.isCurrent(ticket) == true else { return }
        let names = Self.namespaces(teamID: ticket.scope.teamID)
        if let index = names.firstIndex(of: name) { namespaceCursors[ticket.scope] = (index + 1) % names.count }
    }

    mutating func completedNamespace(_ name: String, ticket: NativeWorkspaceMaintenancePolicy.Ticket) {
        policies[ticket.scope]?.completedNamespace(name, ticket: ticket)
    }

    mutating func finish(_ ticket: NativeWorkspaceMaintenancePolicy.Ticket, now: TimeInterval,
                         successful: Bool, interrupted: Bool = false) {
        policies[ticket.scope]?.finish(ticket, now: now, successful: successful, interrupted: interrupted)
    }

    func delay(now: TimeInterval) -> TimeInterval? {
        order.map { policies[$0]?.delay(scope: $0, now: now) ?? 0 }.min()
    }
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
        TeamWorkspaceOfflineRetention.markDirty(accountID: accountID, teamID: teamID)
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
    typealias OverviewRetention = @MainActor ([String: Data], NativeWorkspaceOfflineScope, NativeWorkspaceOfflineCache) async throws -> Void

    private static var scheduler = NativeWorkspaceAllContextMaintenancePolicy()
    private static var activeTicket: NativeWorkspaceMaintenancePolicy.Ticket?
    private static var wake: Task<Void, Never>?
    private static var configuration: (fence: TeamWorkspaceFence, teams: [TeamWorkspaceTeam])?
    private static var identity: NativeWorkspaceOfflineScope?
    private static var pendingRemovals: Set<String> = []

    private static func schedulerScope(teamID: String?, fence: TeamWorkspaceFence) -> NativeWorkspaceOfflineScope {
        .init(accountID: fence.accountID, server: fence.server.apiBaseURL.absoluteString,
              teamID: teamID, accountGeneration: fence.scope, teamEpoch: 0)
    }

    private static func membershipRevision(_ team: TeamWorkspaceTeam) -> String {
        let key = team.key.withUnsafeBytes { SHA256.hash(data: Data($0)).map { String(format: "%02x", $0) }.joined() }
        return "\(team.role.rawValue)|\(team.status)|\(team.updatedAt)|\(key)"
    }

    static func markDirty(accountID: String, teamID: String?) {
        scheduler.markDirty(schedulerScope(teamID: teamID, fence: .init(accountID: accountID)))
        if task == nil { scheduleWake() }
    }

    static func pause() {
        wake?.cancel(); wake = nil
        task?.cancel(); task = nil
        operation = UUID()
        if let ticket = activeTicket {
            scheduler.finish(ticket, now: ProcessInfo.processInfo.systemUptime, successful: false, interrupted: true)
        }
        activeTicket = nil
        // A dirty event while paused cannot start work behind navigation/auth.
        configuration = nil
    }

    static func refresh(fence: TeamWorkspaceFence, teams: [TeamWorkspaceTeam], removedIDs: Set<String>, force: Bool = false) {
        let newIdentity = schedulerScope(teamID: nil, fence: fence)
        if identity != newIdentity { pendingRemovals.removeAll() }
        if identity != newIdentity || !removedIDs.isEmpty { pause() }
        identity = newIdentity
        pendingRemovals.formUnion(removedIDs)
        let readable = teams.filter { $0.canRead && !pendingRemovals.contains($0.id) }
        configuration = (fence, readable)
        let cohorts = [NativeWorkspaceAllContextMaintenancePolicy.Cohort(
            scope: newIdentity, membershipRevision: "personal")] + readable.sorted { $0.id < $1.id }.map { team in
                return NativeWorkspaceAllContextMaintenancePolicy.Cohort(scope: schedulerScope(teamID: team.id, fence: fence),
                    membershipRevision: membershipRevision(team))
            }
        // Roster/force changes invalidate the relevant generation, while repeated
        // resumes coalesce with admitted work. Every Team read still reauthorizes.
        scheduler.update(cohorts, force: force)
        wake?.cancel(); wake = nil
        guard task == nil else { return }
        guard !pendingRemovals.isEmpty || scheduler.delay(now: ProcessInfo.processInfo.systemUptime) == 0 else {
            scheduleWake(); return
        }
        let token = UUID(); operation = token
        task = Task(priority: .utility) {
            var shouldScheduleWake = true
            defer {
                if operation == token {
                    if let ticket = activeTicket {
                        scheduler.finish(ticket, now: ProcessInfo.processInfo.systemUptime,
                                         successful: false, interrupted: Task.isCancelled)
                    }
                    task = nil; activeTicket = nil
                    if shouldScheduleWake { scheduleWake() }
                }
            }
            do {
                try await fence.check(); try Task.checkCancellation()
                let cache = NativeWorkspaceOfflineCache()
                // Authoritative removals run before any admission/cooldown gate.
                for id in pendingRemovals.sorted() {
                    try await fence.check(); try Task.checkCancellation()
                    try await cache.purge(scope: scope(teamID: id, fence: fence))
                    guard operation == token else { throw CancellationError() }
                    pendingRemovals.remove(id)
                }
                guard let key = try await CryptoManager.shared.loadMasterKey(for: fence.accountID) else {
                    shouldScheduleWake = false; return
                }
                var visited: Set<NativeWorkspaceOfflineScope> = []
                for _ in 0..<scheduler.count {
                    try await fence.check(); try Task.checkCancellation()
                    guard operation == token,
                          let ticket = scheduler.beginNext(now: ProcessInfo.processInfo.systemUptime, excluding: visited) else { break }
                    visited.insert(ticket.scope)
                    activeTicket = ticket
                    let currentTeams = configuration?.teams ?? readable
                    let complete = try await retain(fence: fence, teams: currentTeams, removedIDs: [], masterKey: key,
                        cache: cache, transport: { path, fence in
                            try await APIClient.shared.request(.get, path: path, serverProfile: fence.server,
                                expectedAccountID: fence.accountID, expectedScope: fence.scope)
                        }, membership: { id, fence in
                            let team = try await TeamWorkspaceService().getTeam(id, fence: fence)
                            if team.canRead { scheduler.revalidate(scope: ticket.scope, membershipRevision: membershipRevision(team)) }
                            return team
                        }, isCurrent: { operation == token && scheduler.isCurrent(ticket) }, revoke: { id, fence in
                            await TeamWorkspaceContext.shared.revokeCachedTeam(id, fence: fence)
                        }, publishChats: { rows, fence in
                            try await fence.check()
                            OfflineStore.shared.persistChats(rows)
                            NotificationCenter.default.post(name: chatMetadataChanged, object: nil,
                                userInfo: ["accountID": fence.accountID, "scope": fence.scope, "server": fence.server])
                        }, retainOverviews: { responses, scope, cache in
                            guard scope.teamID != TeamWorkspaceContext.shared.teamID else { return }
                            try await ProjectsWorkspaceService().maintainReadmes(responses: responses, scope: scope,
                                cache: cache, masterKey: key, validate: {
                                    try await fence.check(); try Task.checkCancellation()
                                    guard operation == token, scheduler.isCurrent(ticket) else { throw CancellationError() }
                                })
                        }, contextIDs: [ticket.scope.teamID], namespaces: scheduler.namespaces(ticket: ticket),
                        beganNamespace: { name in scheduler.beganNamespace(name, ticket: ticket) },
                        completedNamespace: { name in scheduler.completedNamespace(name, ticket: ticket) })
                    scheduler.finish(ticket, now: ProcessInfo.processInfo.systemUptime, successful: complete)
                    if activeTicket?.id == ticket.id { activeTicket = nil }
                }
            } catch {
                // Key availability/auth transitions resume through their owner;
                // they must not create a two-second keychain polling loop.
                if activeTicket == nil { shouldScheduleWake = false }
                // Keep encrypted snapshots and completed progress for a fenced resume.
            }
        }
    }

    private static func scheduleWake() {
        wake?.cancel(); wake = nil
        guard task == nil, let configuration,
              let delay = scheduler.delay(now: ProcessInfo.processInfo.systemUptime) else { return }
        let token = operation
        wake = Task(priority: .utility) {
            do {
                try await Task.sleep(for: .seconds(max(2, delay)))
                try await configuration.fence.check(); try Task.checkCancellation()
                guard operation == token else { return }
                wake = nil
                refresh(fence: configuration.fence, teams: configuration.teams, removedIDs: [])
            } catch { }
        }
    }

    /// Injectable reader; tests use private directories and transports only. The
    /// foreground singleton is never reconfigured by the all-context traversal.
    @discardableResult
    static func retain(fence: TeamWorkspaceFence, teams: [TeamWorkspaceTeam], removedIDs: Set<String>,
                       masterKey: SymmetricKey, cache: NativeWorkspaceOfflineCache,
                       transport: @escaping Transport, membership: @escaping Membership,
                       isCurrent: @escaping @MainActor () -> Bool = { true },
                       revoke: @escaping @MainActor (String, TeamWorkspaceFence) async -> Void = { _, _ in },
                       publishChats: @escaping @MainActor ([Chat], TeamWorkspaceFence) async throws -> Void = { _, _ in },
                       retainOverviews: OverviewRetention? = nil,
                       contextIDs: [String?]? = nil, namespaces requestedNamespaces: [String]? = nil,
                       beganNamespace: @MainActor (String) -> Void = { _ in },
                       completedNamespace: @MainActor (String) -> Void = { _ in }) async throws -> Bool {
        var complete = true
        let readable = Set(teams.filter(\.canRead).map(\.id))
        func check() async throws {
            try await fence.check(); try Task.checkCancellation()
            guard isCurrent() else { throw CancellationError() }
        }
        for id in removedIDs { try await check(); try await cache.purge(scope: scope(teamID: id, fence: fence)) }
        for id in contextIDs ?? ([String?.none] + readable.sorted().map(Optional.some)) {
            guard id == nil || readable.contains(id!) else { throw TeamWorkspaceError.unavailableTeam }
            try await check()
            let captured = scope(teamID: id, fence: fence)
            do {
                if let id { guard try await membership(id, fence).canRead else { throw TeamWorkspaceError.unavailableTeam } }
                await cache.configure(scope: captured, masterKey: masterKey)
                let namespaces = requestedNamespaces ?? NativeWorkspaceAllContextMaintenancePolicy.namespaces(teamID: id)
                for namespace in namespaces {
                    try await check()
                    beganNamespace(namespace)
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
                        // The authoritative membership read may invalidate this
                        // scheduler generation even while membership stays readable.
                        try await check()
                        let retained = namespace == "projects" ? try responses.mapValues(NativeWorkspaceOfflineRuntime.sanitizedResponse) : responses
                        try await cache.commit(namespace: namespace, responses: retained, scope: captured, revision: revision,
                            complete: namespace != "chat-metadata")
                        if namespace == "projects", let retainOverviews {
                            try await retainOverviews(responses, captured, cache)
                            try await check()
                            if let id { guard try await membership(id, fence).canRead else { throw TeamWorkspaceError.unavailableTeam } }
                        }
                        if namespace == "chat-metadata", let data = responses.values.first {
                            try await check()
                            try await publishChats(decodeChatMetadata(data, teamID: id), fence)
                        }
                        try await check()
                        completedNamespace(namespace)
                    } catch {
                        complete = false
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
                complete = false
                try await check()
                if isRevocation(error), let id {
                    try await cache.purge(scope: captured); await revoke(id, fence)
                }
            }
        }
        return complete
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
            // Both run and scheduled-run rows use the board's workflow_run
            // discriminator. Keep them in the inventory, but they have no
            // canonical Task dependency graph or activity collection.
            if namespace == "user-tasks", row["source"] as? String == "workflow_run" { continue }
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
                    responses[UserTasksPaths.scoped(route, teamID: teamID)] = try await get(route, teamID: teamID, fence: fence, transport: transport)
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
