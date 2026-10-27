// Web source: frontend/packages/ui/src/services/projectRemoteSources.ts, projectService.ts
// Specification: specifications/features/apple-offline-workspaces/specification.yml
// Assertions: apple-workspaces.offline-complete, apple-workspaces.local-first, apple-workspaces.isolation, apple-workspaces.maintenance
// Specification: specifications/features/projects/specification.yml
// Assertions: projects.access.explicit-context, projects.files.no-server-decryption-authority
import CryptoKit
import Foundation

/// Descriptions only. This DTO deliberately cannot encode a host session, file
/// body, expected-base hash, private absolute path or decryption authority.
struct ProjectOfflineMetadataEntry: Codable, Sendable, Equatable {
    let path: String
    let kind: String
    let sizeBytes: Int?
    let childFileCount: Int?
    let childFolderCount: Int?
    let childSummaryTruncated: Bool
    let children: [Child]
    let childFileSizeBytes: Int?
    struct Child: Codable, Sendable, Equatable { let path: String; let kind: String }

    init(_ entry: ProjectRemoteEntry) {
        path = entry.path; kind = entry.kind; sizeBytes = entry.sizeBytes
        childFileCount = entry.childFileCount; childFolderCount = entry.childFolderCount
        childSummaryTruncated = entry.childSummaryTruncated
        children = entry.children.map { Child(path: $0.path, kind: $0.kind) }
        childFileSizeBytes = entry.childFileSizeBytes
    }
    var entry: ProjectRemoteEntry {
        .init(path: path, kind: kind, sizeBytes: sizeBytes, childFileCount: childFileCount,
              childFolderCount: childFolderCount, childSummaryTruncated: childSummaryTruncated,
              children: children.map { .init(path: $0.path, kind: $0.kind) }, childFileSizeBytes: childFileSizeBytes)
    }
}

struct ProjectOfflineMetadataBinding: Hashable, Sendable {
    let project: String
    let source: String
    let epoch: Int?
    let scope: NativeWorkspaceOfflineScope
    var namespace: String { "project-directory:" + project + ":" + source }
    var memoryID: String { scope.directoryID + scope.accountGeneration.uuidString + String(scope.teamEpoch) + namespace }

    fileprivate init(project: String, source: String, epoch: Int?, scope: NativeWorkspaceOfflineScope) {
        self.project = project; self.source = source; self.epoch = epoch; self.scope = scope
    }
    @MainActor init(project: ProjectWorkspaceProject, source: ProjectWorkspaceSource, scope: NativeWorkspaceOfflineScope) throws {
        guard project.teamId == scope.teamID else { throw ProjectsWorkspaceError.invalidContext }
        let key = project.key.withUnsafeBytes { Self.digest(Data($0)) }
        self.project = Self.digest(Data((project.id + ":" + key).utf8))
        // Metadata changes include source replacement/root changes without retaining paths in filenames.
        let encoder = JSONEncoder(); encoder.outputFormatting = [.sortedKeys]
        let metadata = try encoder.encode(source.metadata)
        self.source = Self.digest(Data(source.id.utf8) + metadata)
        epoch = source.keyEpoch; self.scope = scope
    }
    static func digest(_ bytes: Data) -> String { SHA256.hash(data: bytes).map { String(format: "%02x", $0) }.joined() }
}

struct ProjectOfflineDirectory: Sendable {
    let entries: [ProjectOfflineMetadataEntry]
    let complete: Bool
    var directory: ProjectRemoteDirectory {
        .init(entries: entries.map(\.entry), omitted: complete ? 0 : 1, excluded: 0, nextCursor: nil)
    }
}

/// Every directory owns its atomic replacement boundary. A partial refresh merges
/// new descriptions with the last complete listing; only an exhausted cursor may
/// remove entries/subtrees. Whole-tree completeness means an exhaustive traversal,
/// not a point-in-time filesystem revision (the protocol has no revision token).
@MainActor
final class ProjectOfflineMetadataRepository {
    static let shared = ProjectOfflineMetadataRepository()
    struct Pending: Codable, Sendable, Equatable {
        let path: String
        var cursor: String?
        var staged: [ProjectOfflineMetadataEntry] = []
        var seenCursors: [String] = []
    }
    struct Snapshot: Codable, Sendable {
        var epoch: Int?
        var directories: [String: [ProjectOfflineMetadataEntry]] = [:]
        var pending: [Pending] = [.init(path: ".")]
        var complete = false
        var refreshedAt: Date?
    }
    private struct Authority { let session: String; let epoch: Int?; let token: UUID }
    private var snapshots: [String: Snapshot] = [:]
    private var authorities: [String: Authority] = [:]
    private var projectSources: [String: Set<String>] = [:]
    private var reconciliationRequests: [String: UUID] = [:]
    private var writes: [String: Task<Void, Error>] = [:]
    private var directoryGenerations: [String: [String: UUID]] = [:]
    private let beforePersist: () async throws -> Void
    init(beforePersist: @escaping () async throws -> Void = {}) { self.beforePersist = beforePersist }

    private func snapshot(_ binding: ProjectOfflineMetadataBinding, cache: NativeWorkspaceOfflineCache) async throws -> Snapshot {
        // A pending tombstone must reach disk before a reentrant read can load
        // the prior bytes back into memory. Failures still pass the scope fence.
        if let write = writes[binding.memoryID] { _ = await write.result }
        // Even memory hits must pass the cache actor's current owner/team fence.
        let bytes = try await cache.read(namespace: binding.namespace, path: "tree", scope: binding.scope)
        // A foreground page may have populated memory while disk was suspended.
        if let value = snapshots[binding.memoryID], binding.epoch == nil || value.epoch == binding.epoch { return value }
        let loaded = try bytes.map { try JSONDecoder().decode(Snapshot.self, from: $0) }
        let value = loaded.flatMap { binding.epoch == nil || $0.epoch == binding.epoch ? $0 : nil } ?? Snapshot(epoch: binding.epoch)
        snapshots[binding.memoryID] = value
        return value
    }
    private func persist(_ value: Snapshot, binding: ProjectOfflineMetadataBinding, cache: NativeWorkspaceOfflineCache) async throws {
        let bytes = try JSONEncoder().encode(value)
        let previous = writes[binding.memoryID]
        // Actor hops can execute out of submission order. Chain writes before
        // suspending so a late page cannot overwrite a newer merge or tombstone.
        let write = Task {
            if let previous { _ = await previous.result }
            try await beforePersist()
            try await cache.retain(namespace: binding.namespace, path: "tree", data: bytes, scope: binding.scope)
        }
        writes[binding.memoryID] = write
        try await write.value
    }
    private func save(_ value: Snapshot, binding: ProjectOfflineMetadataBinding, cache: NativeWorkspaceOfflineCache) async throws {
        snapshots[binding.memoryID] = value
        try await persist(value, binding: binding, cache: cache)
    }

    /// Fresh server metadata changes volatile request authority. Cached metadata
    /// never calls this method and therefore cannot authorize a remote request.
    func reconcile(project: ProjectWorkspaceProject, sources: [ProjectWorkspaceSource], scope: NativeWorkspaceOfflineScope,
                   cache: NativeWorkspaceOfflineCache, validate: () async throws -> Void) async throws {
        let bindings = try sources.map { try ProjectOfflineMetadataBinding(project: project, source: $0, scope: scope) }
        let keyDigest = project.key.withUnsafeBytes { ProjectOfflineMetadataBinding.digest(Data($0)) }
        let projectID = ProjectOfflineMetadataBinding.digest(Data((project.id + ":" + keyDigest).utf8))
        let indexNamespace = "project-directory-index:" + projectID
        let indexKey = scope.directoryID + scope.accountGeneration.uuidString + String(scope.teamEpoch) + indexNamespace
        let request = UUID()
        reconciliationRequests[indexKey] = request
        func checkRequest() throws {
            try Task.checkCancellation()
            guard reconciliationRequests[indexKey] == request else { throw CancellationError() }
        }
        try await validate(); try checkRequest()
        let retained = try await cache.read(namespace: indexNamespace, path: "sources", scope: scope)
        try await validate(); try checkRequest()
        let previous: Set<String>
        if let memory = projectSources[indexKey] { previous = memory }
        else if let retained { previous = try JSONDecoder().decode(Set<String>.self, from: retained) }
        else { previous = [] }
        let current = Set(bindings.map(\.source))
        // Persist tombstones for removed/replaced sources, so re-adding an old ID
        // cannot resurrect metadata from before an observed revocation.
        let removedBindings = previous.subtracting(current).map {
            ProjectOfflineMetadataBinding(project: projectID, source: $0, epoch: nil, scope: scope)
        }
        // Revoke every removed source synchronously before the first disk hop.
        for binding in removedBindings {
            snapshots[binding.memoryID] = Snapshot(epoch: nil)
            authorities.removeValue(forKey: binding.memoryID)
            directoryGenerations.removeValue(forKey: binding.memoryID)
        }
        for binding in removedBindings {
            try await persist(Snapshot(epoch: nil), binding: binding, cache: cache)
            try checkRequest()
        }
        for (source, binding) in zip(sources, bindings) {
            try await validate(); try checkRequest()
            let old = authorities[binding.memoryID]
            if !source.capabilities.contains("read") || !["connected", "offline", "disconnected"].contains(source.status) {
                authorities.removeValue(forKey: binding.memoryID)
                try await save(Snapshot(epoch: source.keyEpoch), binding: binding, cache: cache)
                try checkRequest()
                continue
            }
            if source.status == "connected", source.capabilities.contains("read"), let session = source.sessionID {
                if old?.session != session || old?.epoch != source.keyEpoch {
                    authorities[binding.memoryID] = Authority(session: session, epoch: source.keyEpoch, token: UUID())
                }
            } else { authorities.removeValue(forKey: binding.memoryID) }
            _ = try await snapshot(binding, cache: cache)
            try checkRequest()
            guard let value = snapshots[binding.memoryID] else { throw CancellationError() }
            // Known rotations must retire old persisted bytes, even if no new
            // listing succeeds before the next offline launch.
            if let epoch = source.keyEpoch, value.epoch != epoch {
                try await save(Snapshot(epoch: epoch), binding: binding, cache: cache)
            } else if let epoch = source.keyEpoch, value.epoch == epoch {
                // snapshot() already rejected mismatched old epochs; persist that
                // empty replacement before offline presence omits the epoch.
                try await save(value, binding: binding, cache: cache)
            }
        }
        try await validate(); try checkRequest()
        projectSources[indexKey] = current
        try await cache.retain(namespace: indexNamespace, path: "sources", data: JSONEncoder().encode(current), scope: scope)
    }

    func cached(path: String, binding: ProjectOfflineMetadataBinding, cache: NativeWorkspaceOfflineCache) async throws -> ProjectOfflineDirectory? {
        guard path == "." || ProjectWorkspacePath.normalized(path) != nil else { throw ProjectsWorkspaceError.invalidContext }
        let value = try await snapshot(binding, cache: cache)
        let staged = value.pending.first { $0.path == path }?.staged ?? []
        guard let retained = value.directories[path] ?? (staged.isEmpty ? nil : []) else { return nil }
        var merged = Dictionary(uniqueKeysWithValues: retained.map { ($0.path, $0) })
        for entry in staged { merged[entry.path] = entry }
        return .init(entries: merged.values.sorted { $0.path.localizedStandardCompare($1.path) == .orderedAscending },
                     complete: value.pending.allSatisfy { $0.path != path })
    }

    func authority(binding: ProjectOfflineMetadataBinding, source: ProjectWorkspaceSource) throws -> UUID {
        guard source.status == "connected", source.capabilities.contains("read"),
              let authority = authorities[binding.memoryID], authority.session == source.sessionID,
              authority.epoch == source.keyEpoch else { throw CancellationError() }
        return authority.token
    }
    func checkAuthority(_ token: UUID, binding: ProjectOfflineMetadataBinding) throws {
        try Task.checkCancellation()
        guard authorities[binding.memoryID]?.token == token else { throw CancellationError() }
    }

    func next(binding: ProjectOfflineMetadataBinding, cache: NativeWorkspaceOfflineCache, now: Date = Date()) async throws -> Pending? {
        var value = try await snapshot(binding, cache: cache)
        if value.complete {
            guard now.timeIntervalSince(value.refreshedAt ?? .distantPast) >= 300 else { return nil }
            value.pending = [.init(path: ".")]; value.complete = false
            try await save(value, binding: binding, cache: cache)
        }
        return value.pending.first
    }

    /// Capture membership before dispatch; a completed parent removal retires
    /// this generation even if a later listing reintroduces the same path.
    func begin(path: String, binding: ProjectOfflineMetadataBinding, token: UUID,
               cache: NativeWorkspaceOfflineCache) async throws -> UUID {
        let value = try await snapshot(binding, cache: cache)
        try checkAuthority(token, binding: binding)
        let known = path == "." || value.directories.values.joined().contains { $0.path == path && $0.kind == "directory" }
            || value.pending.contains { $0.path == path || $0.staged.contains { $0.path == path && $0.kind == "directory" } }
        guard known else { throw CancellationError() }
        if let generation = directoryGenerations[binding.memoryID]?[path] { return generation }
        let generation = UUID()
        directoryGenerations[binding.memoryID, default: [:]][path] = generation
        return generation
    }

    func accept(_ page: ProjectRemoteDirectory, path: String, cursor: String?, binding: ProjectOfflineMetadataBinding,
                token: UUID, request: UUID? = nil, cache: NativeWorkspaceOfflineCache, validate: () async throws -> Void) async throws {
        let requestGeneration: UUID
        if let request { requestGeneration = request }
        else { requestGeneration = try await begin(path: path, binding: binding, token: token, cache: cache) }
        try await validate(); try checkAuthority(token, binding: binding)
        _ = try await snapshot(binding, cache: cache)
        try await validate(); try checkAuthority(token, binding: binding)
        // Validation can suspend while another directory commits. Take the latest
        // state only after it returns, then mutate/publish before any suspension.
        guard var value = snapshots[binding.memoryID],
              directoryGenerations[binding.memoryID]?[path] == requestGeneration else { throw CancellationError() }
        guard page.entries.allSatisfy({ entry in
            guard ProjectWorkspacePath.normalized(entry.path) != nil else { return false }
            let parent = entry.path.split(separator: "/").dropLast().joined(separator: "/")
            return (parent.isEmpty ? "." : parent) == path && ["file", "directory"].contains(entry.kind)
        }) else { throw ProjectsWorkspaceError.invalidResponse }
        let index: Int
        if let existing = value.pending.firstIndex(where: { $0.path == path }) { index = existing }
        else {
            guard cursor == nil else { return } // Later foreground pages cannot invent a complete traversal.
            value.pending.append(.init(path: path)); index = value.pending.count - 1
        }
        guard value.pending[index].cursor == cursor else { return }
        var pending = value.pending[index]
        pending.staged = Dictionary((pending.staged + page.entries.map(ProjectOfflineMetadataEntry.init))
            .map { ($0.path, $0) }, uniquingKeysWith: { _, new in new }).values.sorted { $0.path < $1.path }
        value.complete = false
        if let next = page.nextCursor {
            guard next != cursor, !pending.seenCursors.contains(next) else { throw ProjectsWorkspaceError.invalidResponse }
            pending.seenCursors.append(next); pending.cursor = next
            value.pending[index] = pending
        } else if page.omitted > 0 {
            // Legacy truncated responses cannot prove completion. Preserve their
            // descriptions but retry from the root page after a later cooldown.
            let retained = value.directories[path] ?? []
            value.directories[path] = Dictionary((retained + pending.staged).map { ($0.path, $0) },
                uniquingKeysWith: { _, new in new }).values.sorted { $0.path < $1.path }
            pending.cursor = nil; pending.seenCursors = []; pending.staged = []
            value.pending[index] = pending
            value.complete = false
        } else {
            let entries = Dictionary(pending.staged.map { ($0.path, $0) }, uniquingKeysWith: { _, new in new })
            let previous = value.directories[path] ?? []
            value.directories[path] = entries.values.sorted { $0.path < $1.path }
            value.pending.remove(at: index)
            directoryGenerations[binding.memoryID] = directoryGenerations[binding.memoryID]?.filter { candidate in
                guard candidate.key != path else { return true }
                let prefix = path == "." ? "" : path + "/"
                guard candidate.key.hasPrefix(prefix) else { return true }
                let relative = candidate.key.dropFirst(prefix.count)
                guard let child = relative.split(separator: "/").first else { return true }
                return entries[prefix + String(child)]?.kind == "directory"
            }
            for removed in previous where removed.kind == "directory" && entries[removed.path]?.kind != "directory" {
                value.directories = value.directories.filter { $0.key != removed.path && !$0.key.hasPrefix(removed.path + "/") }
                value.pending.removeAll { $0.path == removed.path || $0.path.hasPrefix(removed.path + "/") }
                directoryGenerations[binding.memoryID] = directoryGenerations[binding.memoryID]?.filter {
                    $0.key != removed.path && !$0.key.hasPrefix(removed.path + "/")
                }
            }
            // Traverse every actual directory, never the three-row child preview.
            for entry in entries.values.sorted(by: { $0.path < $1.path }) where entry.kind == "directory" {
                if !value.pending.contains(where: { $0.path == entry.path }) { value.pending.append(.init(path: entry.path)) }
            }
            value.complete = value.pending.isEmpty
            if value.complete { value.refreshedAt = Date() }
        }
        try checkAuthority(token, binding: binding)
        try await save(value, binding: binding, cache: cache)
    }
}

/// A single global queue leaves foreground request capacity available. Work runs
/// in small slices, resumes its durable BFS on the next slice, and backs off on
/// unavailable hosts. It never participates in chat sync's completion barrier.
@MainActor
final class ProjectOfflineMetadataScheduler {
    static let shared = ProjectOfflineMetadataScheduler()
    private struct Job { let identity = UUID(); let operation: () async throws -> Bool; var retryAfter: Date }
    private var jobs: [String: Job] = [:]
    private var order: [String] = []
    private var worker: Task<Void, Never>?
    private var workerGeneration = UUID()
    private var lastRequest = Date.distantPast
    private let now: () -> Date
    private let wait: (TimeInterval) async throws -> Void
    init(now: @escaping () -> Date = Date.init,
         wait: @escaping (TimeInterval) async throws -> Void = { try await Task.sleep(for: .seconds($0)) }) {
        self.now = now; self.wait = wait
    }
    func schedule(id: String, operation: @escaping () async throws -> Bool) {
        // A repeated load joins the existing traversal rather than restarting it.
        guard jobs[id] == nil else { return }
        jobs[id] = Job(operation: operation, retryAfter: .distantPast); order.append(id)
        startWorkerIfNeeded()
    }
    private func startWorkerIfNeeded() {
        guard worker == nil, !order.isEmpty else { return }
        let generation = UUID(); workerGeneration = generation
        worker = Task { [weak self] in await self?.run(generation: generation) }
    }
    private func run(generation: UUID) async {
        defer {
            if workerGeneration == generation {
                worker = nil
                startWorkerIfNeeded()
            }
        }
        while !Task.isCancelled, workerGeneration == generation, !order.isEmpty {
            let id = order.removeFirst()
            guard var job = jobs[id] else { continue }
            do {
                let delay = max(0, max(lastRequest.addingTimeInterval(3), job.retryAfter).timeIntervalSince(now()))
                // Keep each suspension bounded; backing off one host must not
                // prevent a healthy host elsewhere in the queue from progressing.
                if delay > 3, order.contains(where: { (jobs[$0]?.retryAfter ?? .distantFuture) <= now() }) {
                    order.append(id); continue
                }
                try await wait(min(delay, 3))
                guard workerGeneration == generation, jobs[id]?.identity == job.identity else { continue }
                if job.retryAfter > now() { order.append(id); continue }
                try Task.checkCancellation()
                let more = try await job.operation()
                // Completion is a conservative dispatch fence: validation/cache
                // awaits inside the operation can precede the actual request.
                lastRequest = now()
                guard workerGeneration == generation, jobs[id]?.identity == job.identity else { continue }
                if more { order.append(id) } else { jobs.removeValue(forKey: id) }
            } catch {
                lastRequest = now()
                guard workerGeneration == generation, jobs[id]?.identity == job.identity else { continue }
                if NativeWorkspaceReadFailure.isCancellation(error) || Self.isTerminal(error) { jobs.removeValue(forKey: id) }
                else { job.retryAfter = now().addingTimeInterval(30); jobs[id] = job; order.append(id) }
            }
            await Task.yield()
        }
    }
    private static func isTerminal(_ error: Error) -> Bool {
        if case APIError.httpError(let status, _) = error { return [401, 403, 404].contains(status) }
        return false
    }
    func cancel(id: String) { jobs.removeValue(forKey: id); order.removeAll { $0 == id } }
    func stop() {
        // Keep an outstanding worker until it unwinds, so immediate re-admission
        // cannot overlap a cancelled operation that has not returned yet.
        worker?.cancel(); jobs.removeAll(); order.removeAll()
    }
}
