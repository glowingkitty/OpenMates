import CryptoKit
import XCTest
@testable import OpenMates

@MainActor
final class ProjectOfflineMetadataTests: XCTestCase {
    private func project(key: SymmetricKey = SymmetricKey(size: .bits256), team: String? = nil) -> ProjectWorkspaceProject {
        .init(id: "project", name: "Fixture", description: "", icon: "project", key: key,
              version: 1, createdAt: 1, updatedAt: 1, isShared: team != nil, itemCount: 0,
              teamId: team, permissions: .denied)
    }
    private func source(epoch: Int? = 1, session: String? = "volatile-session", status: String = "connected") -> ProjectWorkspaceSource {
        .init(id: "source", kind: "remote_folder", name: "Files", metadata: ["fixture": "root"],
              capabilities: ["read"], status: status, sessionID: session, keyEpoch: epoch)
    }
    private func scope(account: String = "owner", team: String? = nil) -> NativeWorkspaceOfflineScope {
        .init(accountID: account, server: "https://example.invalid", teamID: team, accountGeneration: UUID(), teamEpoch: 1)
    }
    private func entry(_ path: String, directory: Bool = false) -> ProjectRemoteEntry {
        .init(path: path, kind: directory ? "directory" : "file", sizeBytes: directory ? nil : 24,
              childFileCount: nil, childFolderCount: nil, childSummaryTruncated: false)
    }
    private func page(_ entries: [ProjectRemoteEntry], omitted: Int = 0, cursor: String? = nil) -> ProjectRemoteDirectory {
        .init(entries: entries, omitted: omitted, excluded: 0, nextCursor: cursor)
    }
    private func temporaryDirectory() -> URL {
        FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
    }

    // contract-test: supporting surface=gui.apple assertions=apple-workspaces.offline-complete,apple-workspaces.local-first,apple-workspaces.isolation
    func testDirectoryDescriptionsReopenEncryptedWithoutBodyOrSessionAuthority() async throws {
        let directory = temporaryDirectory()
        defer { try? FileManager.default.removeItem(at: directory) }
        let cache = NativeWorkspaceOfflineCache(directory: directory), repository = ProjectOfflineMetadataRepository()
        let context = scope(), key = SymmetricKey(size: .bits256), project = project(), source = source()
        await cache.configure(scope: context, masterKey: key)
        let binding = try ProjectOfflineMetadataBinding(project: project, source: source, scope: context)
        try await repository.reconcile(project: project, sources: [source], scope: context, cache: cache, validate: {})
        let token = try repository.authority(binding: binding, source: source)
        try await repository.accept(page([entry("never-opened", directory: true)]), path: ".", cursor: nil,
            binding: binding, token: token, cache: cache, validate: {})
        try await repository.accept(page([entry("never-opened/retained.txt")]), path: "never-opened", cursor: nil,
            binding: binding, token: token, cache: cache, validate: {})
        let pending = try await repository.next(binding: binding, cache: cache)
        XCTAssertNil(pending, "Every discovered directory must finish before traversal completes")
        let retainedBytes = try await cache.read(namespace: binding.namespace, path: "tree", scope: context)
        let serialized = try XCTUnwrap(retainedBytes)
        XCTAssertNil(serialized.range(of: Data("volatile-session".utf8)))
        XCTAssertNil(serialized.range(of: Data("content".utf8)))
        let encryptedFiles = try FileManager.default.contentsOfDirectory(at: directory.appendingPathComponent(context.directoryID),
            includingPropertiesForKeys: nil).filter { $0.pathExtension == "aesgcm" }
        XCTAssertFalse(encryptedFiles.isEmpty)
        for file in encryptedFiles {
            XCTAssertNil(try Data(contentsOf: file).range(of: Data("retained.txt".utf8)))
        }
        let reopened = NativeWorkspaceOfflineCache(directory: directory)
        await reopened.configure(scope: context, masterKey: key)
        let offlineSource = self.source(epoch: nil, session: nil, status: "disconnected")
        let offlineBinding = try ProjectOfflineMetadataBinding(project: project, source: offlineSource, scope: context)
        let offlineRepository = ProjectOfflineMetadataRepository()
        let retained = try await offlineRepository.cached(path: "never-opened", binding: offlineBinding, cache: reopened)
        XCTAssertEqual(retained?.entries.map(\.path), ["never-opened/retained.txt"])
        XCTAssertTrue(retained?.complete == true)
        XCTAssertThrowsError(try offlineRepository.authority(binding: offlineBinding, source: offlineSource))
    }

    // contract-test: supporting surface=gui.apple assertions=apple-workspaces.offline-complete,apple-workspaces.maintenance
    func testBreadthFirstTraversalVisitsUnexpandedDirectoriesAndAllCursorPages() async throws {
        let directory = temporaryDirectory()
        defer { try? FileManager.default.removeItem(at: directory) }
        var cache = NativeWorkspaceOfflineCache(directory: directory)
        var repository = ProjectOfflineMetadataRepository()
        let context = scope(), project = project(), source = source(), key = SymmetricKey(size: .bits256)
        await cache.configure(scope: context, masterKey: key)
        let binding = try ProjectOfflineMetadataBinding(project: project, source: source, scope: context)
        try await repository.reconcile(project: project, sources: [source], scope: context, cache: cache, validate: {})
        var token = try repository.authority(binding: binding, source: source)
        var visited: [String] = []
        while let pending = try await repository.next(binding: binding, cache: cache) {
            visited.append(pending.path + ":" + (pending.cursor ?? "first"))
            let result: ProjectRemoteDirectory
            switch visited.last ?? "" {
            case ".:first": result = page([entry("folder", directory: true)], omitted: 1, cursor: "folder")
            case ".:folder": result = page([entry("root.txt")])
            case "folder:first": result = page([entry("folder/deep", directory: true)])
            case "folder/deep:first": result = page([entry("folder/deep/unopened.txt")])
            default: return XCTFail("Traversal must neither skip nor repeat directories/cursors")
            }
            try await repository.accept(result, path: pending.path, cursor: pending.cursor,
                binding: binding, token: token, cache: cache, validate: {})
            if visited.count == 1 {
                // Resume both the staged first page and its durable cursor after
                // recreating memory. Fresh presence must issue new authority.
                cache = NativeWorkspaceOfflineCache(directory: directory)
                await cache.configure(scope: context, masterKey: key)
                repository = ProjectOfflineMetadataRepository()
                XCTAssertThrowsError(try repository.authority(binding: binding, source: source))
                try await repository.reconcile(project: project, sources: [source], scope: context, cache: cache, validate: {})
                token = try repository.authority(binding: binding, source: source)
            }
        }
        XCTAssertEqual(visited, [".:first", ".:folder", "folder:first", "folder/deep:first"])
        let retained = try await repository.cached(path: "folder/deep", binding: binding, cache: cache)
        XCTAssertEqual(retained?.entries.map(\.path), ["folder/deep/unopened.txt"])
    }

    // contract-test: supporting surface=gui.apple assertions=apple-workspaces.maintenance,apple-workspaces.local-first
    func testPartialRefreshPreservesOldDescriptionsUntilCompleteListingReconcilesDeletion() async throws {
        let directory = temporaryDirectory()
        defer { try? FileManager.default.removeItem(at: directory) }
        let cache = NativeWorkspaceOfflineCache(directory: directory), repository = ProjectOfflineMetadataRepository()
        let context = scope(), project = project(), source = source()
        await cache.configure(scope: context, masterKey: SymmetricKey(size: .bits256))
        let binding = try ProjectOfflineMetadataBinding(project: project, source: source, scope: context)
        try await repository.reconcile(project: project, sources: [source], scope: context, cache: cache, validate: {})
        let token = try repository.authority(binding: binding, source: source)
        try await repository.accept(page([entry("old.txt"), entry("removed", directory: true)]), path: ".", cursor: nil,
            binding: binding, token: token, cache: cache, validate: {})
        try await repository.accept(page([entry("removed/old.txt")]), path: "removed", cursor: nil,
            binding: binding, token: token, cache: cache, validate: {})
        _ = try await repository.next(binding: binding, cache: cache, now: Date().addingTimeInterval(301))
        try await repository.accept(page([entry("new.txt")], omitted: 1, cursor: "new.txt"), path: ".", cursor: nil,
            binding: binding, token: token, cache: cache, validate: {})
        let partial = try await repository.cached(path: ".", binding: binding, cache: cache)
        XCTAssertEqual(Set(partial?.entries.map(\.path) ?? []), ["old.txt", "removed", "new.txt"])
        XCTAssertFalse(partial?.complete ?? true)
        let retainedSubtree = try await repository.cached(path: "removed", binding: binding, cache: cache)
        XCTAssertNotNil(retainedSubtree)
        try await repository.accept(page([]), path: ".", cursor: "new.txt", binding: binding, token: token,
            cache: cache, validate: {})
        let complete = try await repository.cached(path: ".", binding: binding, cache: cache)
        XCTAssertEqual(complete?.entries.map(\.path), ["new.txt"])
        XCTAssertTrue(complete?.complete == true)
        let removedSubtree = try await repository.cached(path: "removed", binding: binding, cache: cache)
        XCTAssertNil(removedSubtree)
    }

    // contract-test: supporting surface=gui.apple assertions=apple-workspaces.isolation,projects.access.explicit-context
    func testRotationRevocationAndReplacementSessionRejectPriorMetadataAndLatePages() async throws {
        let directory = temporaryDirectory()
        defer { try? FileManager.default.removeItem(at: directory) }
        let cache = NativeWorkspaceOfflineCache(directory: directory), repository = ProjectOfflineMetadataRepository()
        let context = scope(), project = project(), source = source()
        await cache.configure(scope: context, masterKey: SymmetricKey(size: .bits256))
        let binding = try ProjectOfflineMetadataBinding(project: project, source: source, scope: context)
        try await repository.reconcile(project: project, sources: [source], scope: context, cache: cache, validate: {})
        let original = try repository.authority(binding: binding, source: source)
        try await repository.accept(page([entry("old.txt")]), path: ".", cursor: nil,
            binding: binding, token: original, cache: cache, validate: {})
        let replacement = self.source(session: "replacement")
        try await repository.reconcile(project: project, sources: [replacement], scope: context, cache: cache, validate: {})
        do {
            try await repository.accept(page([entry("late.txt")]), path: ".", cursor: nil,
                binding: binding, token: original, cache: cache, validate: {})
            XCTFail("An old host session must never update retained descriptions")
        } catch is CancellationError { }
        let rotated = self.source(epoch: 2, session: "replacement")
        try await repository.reconcile(project: project, sources: [rotated], scope: context, cache: cache, validate: {})
        let offline = self.source(epoch: nil, session: nil, status: "offline")
        let offlineBinding = try ProjectOfflineMetadataBinding(project: project, source: offline, scope: context)
        let afterRotation = try await ProjectOfflineMetadataRepository().cached(path: ".", binding: offlineBinding, cache: cache)
        XCTAssertNil(afterRotation, "Observed rotation must stay invalidated when offline presence later omits its epoch")
        try await repository.reconcile(project: project, sources: [], scope: context, cache: cache, validate: {})
        let afterRemoval = try await ProjectOfflineMetadataRepository().cached(path: ".", binding: offlineBinding, cache: cache)
        XCTAssertNil(afterRemoval)
    }

    // contract-test: supporting surface=gui.apple assertions=apple-workspaces.isolation
    func testOwnerTeamProjectKeyAndSourceIdentityCannotReuseRetainedDescriptions() async throws {
        let directory = temporaryDirectory()
        defer { try? FileManager.default.removeItem(at: directory) }
        let cache = NativeWorkspaceOfflineCache(directory: directory), repository = ProjectOfflineMetadataRepository()
        let context = scope(), project = project(), source = source(), masterKey = SymmetricKey(size: .bits256)
        await cache.configure(scope: context, masterKey: masterKey)
        let binding = try ProjectOfflineMetadataBinding(project: project, source: source, scope: context)
        try await repository.reconcile(project: project, sources: [source], scope: context, cache: cache, validate: {})
        try await repository.accept(page([entry("private.txt")]), path: ".", cursor: nil, binding: binding,
            token: repository.authority(binding: binding, source: source), cache: cache, validate: {})
        let changedKey = try ProjectOfflineMetadataBinding(project: self.project(), source: source, scope: context)
        let keyMiss = try await repository.cached(path: ".", binding: changedKey, cache: cache)
        XCTAssertNil(keyMiss)
        let changedSource = ProjectWorkspaceSource(id: "other-source", kind: source.kind, name: source.name,
            metadata: source.metadata, capabilities: source.capabilities, status: source.status, sessionID: source.sessionID, keyEpoch: source.keyEpoch)
        let sourceMiss = try await repository.cached(path: ".", binding: ProjectOfflineMetadataBinding(project: project, source: changedSource, scope: context), cache: cache)
        XCTAssertNil(sourceMiss)
        for other in [scope(account: "another-owner"), scope(team: "team")] {
            await cache.configure(scope: other, masterKey: masterKey)
            let otherProject = self.project(key: project.key, team: other.teamID)
            let otherBinding = try ProjectOfflineMetadataBinding(project: otherProject, source: source, scope: other)
            let miss = try await repository.cached(path: ".", binding: otherBinding, cache: cache)
            XCTAssertNil(miss)
            do { _ = try await cache.read(namespace: binding.namespace, path: "tree", scope: context); XCTFail("Old scope") }
            catch is CancellationError { }
        }
    }

    // contract-test: supporting surface=gui.apple assertions=apple-workspaces.maintenance,apple-workspaces.isolation
    func testConcurrentDirectoryCompletionsPreserveBothAfterSuspendedValidation() async throws {
        let directory = temporaryDirectory()
        defer { try? FileManager.default.removeItem(at: directory) }
        let cache = NativeWorkspaceOfflineCache(directory: directory), repository = ProjectOfflineMetadataRepository()
        let context = scope(), project = project(), source = source(), key = SymmetricKey(size: .bits256)
        await cache.configure(scope: context, masterKey: key)
        let binding = try ProjectOfflineMetadataBinding(project: project, source: source, scope: context)
        try await repository.reconcile(project: project, sources: [source], scope: context, cache: cache, validate: {})
        let token = try repository.authority(binding: binding, source: source)
        try await repository.accept(page([entry("a", directory: true), entry("b", directory: true)]), path: ".", cursor: nil,
            binding: binding, token: token, cache: cache, validate: {})
        let suspended = expectation(description: "First directory at final validation")
        var continuation: CheckedContinuation<Void, Never>?
        var validations = 0
        let first = Task {
            try await repository.accept(page([entry("a/first.txt")]), path: "a", cursor: nil,
                binding: binding, token: token, cache: cache, validate: {
                    validations += 1
                    if validations == 2 {
                        await withCheckedContinuation { continuation = $0; suspended.fulfill() }
                    }
                })
        }
        await fulfillment(of: [suspended], timeout: 2)
        try await repository.accept(page([entry("b/second.txt")]), path: "b", cursor: nil,
            binding: binding, token: token, cache: cache, validate: {})
        continuation?.resume()
        try await first.value
        // A fresh cache actor/repository must see both commits in encrypted disk,
        // rather than passing only because the original repository retained them.
        let reopenedCache = NativeWorkspaceOfflineCache(directory: directory)
        await reopenedCache.configure(scope: context, masterKey: key)
        let reopenedRepository = ProjectOfflineMetadataRepository()
        let a = try await reopenedRepository.cached(path: "a", binding: binding, cache: reopenedCache)
        let b = try await reopenedRepository.cached(path: "b", binding: binding, cache: reopenedCache)
        XCTAssertEqual(a?.entries.map(\.path), ["a/first.txt"])
        XCTAssertEqual(b?.entries.map(\.path), ["b/second.txt"])
        let remaining = try await reopenedRepository.next(binding: binding, cache: reopenedCache)
        XCTAssertNil(remaining)
    }

    // contract-test: supporting surface=gui.apple assertions=apple-workspaces.maintenance
    func testDirectoryBecomingFilePrunesItsPreviouslyRetainedSubtree() async throws {
        let directory = temporaryDirectory()
        defer { try? FileManager.default.removeItem(at: directory) }
        let cache = NativeWorkspaceOfflineCache(directory: directory), repository = ProjectOfflineMetadataRepository()
        let context = scope(), project = project(), source = source()
        await cache.configure(scope: context, masterKey: SymmetricKey(size: .bits256))
        let binding = try ProjectOfflineMetadataBinding(project: project, source: source, scope: context)
        try await repository.reconcile(project: project, sources: [source], scope: context, cache: cache, validate: {})
        let token = try repository.authority(binding: binding, source: source)
        try await repository.accept(page([entry("folder", directory: true)]), path: ".", cursor: nil,
            binding: binding, token: token, cache: cache, validate: {})
        try await repository.accept(page([entry("folder/old.txt")]), path: "folder", cursor: nil,
            binding: binding, token: token, cache: cache, validate: {})
        _ = try await repository.next(binding: binding, cache: cache, now: Date().addingTimeInterval(301))
        try await repository.accept(page([entry("folder")]), path: ".", cursor: nil,
            binding: binding, token: token, cache: cache, validate: {})
        let obsolete = try await repository.cached(path: "folder", binding: binding, cache: cache)
        XCTAssertNil(obsolete)
        let remaining = try await repository.next(binding: binding, cache: cache)
        XCTAssertNil(remaining)
    }

    // contract-test: supporting surface=gui.apple assertions=apple-workspaces.maintenance,apple-workspaces.local-first
    func testTruncatedPageRestartCanReuseCursorAndReconcileRemovedPartialDescriptions() async throws {
        let directory = temporaryDirectory()
        defer { try? FileManager.default.removeItem(at: directory) }
        let cache = NativeWorkspaceOfflineCache(directory: directory), repository = ProjectOfflineMetadataRepository()
        let context = scope(), project = project(), source = source()
        await cache.configure(scope: context, masterKey: SymmetricKey(size: .bits256))
        let binding = try ProjectOfflineMetadataBinding(project: project, source: source, scope: context)
        try await repository.reconcile(project: project, sources: [source], scope: context, cache: cache, validate: {})
        let token = try repository.authority(binding: binding, source: source)
        try await repository.accept(page([entry("a.txt")], omitted: 1, cursor: "a.txt"), path: ".", cursor: nil,
            binding: binding, token: token, cache: cache, validate: {})
        try await repository.accept(page([entry("obsolete.txt")], omitted: 1), path: ".", cursor: "a.txt",
            binding: binding, token: token, cache: cache, validate: {})
        let partial = try await repository.cached(path: ".", binding: binding, cache: cache)
        XCTAssertEqual(Set(partial?.entries.map(\.path) ?? []), ["a.txt", "obsolete.txt"])
        XCTAssertFalse(partial?.complete ?? true)
        try await repository.accept(page([entry("a.txt")], omitted: 1, cursor: "a.txt"), path: ".", cursor: nil,
            binding: binding, token: token, cache: cache, validate: {})
        try await repository.accept(page([entry("z.txt")]), path: ".", cursor: "a.txt",
            binding: binding, token: token, cache: cache, validate: {})
        let complete = try await repository.cached(path: ".", binding: binding, cache: cache)
        XCTAssertEqual(complete?.entries.map(\.path), ["a.txt", "z.txt"])
        XCTAssertTrue(complete?.complete == true)
    }

    // contract-test: supporting surface=gui.apple assertions=apple-workspaces.maintenance,projects.access.explicit-context
    func testSchedulerRetiresTerminalAuthorizationAndMissingSourceJobs() async throws {
        for status in [401, 403, 404] {
            var time = Date(timeIntervalSince1970: 1_000)
            var attempts = 0
            let scheduler = ProjectOfflineMetadataScheduler(now: { time }, wait: { delay in
                time = time.addingTimeInterval(delay)
                await Task.yield()
            })
            let completed = expectation(description: "Terminal \(status) job retired")
            scheduler.schedule(id: "source") {
                attempts += 1
                throw APIError.httpError(status: status, message: "fixture")
            }
            scheduler.schedule(id: "next-source") {
                // Re-admission proves that the terminal job was removed instead
                // of remaining on the retry queue with stale request authority.
                scheduler.schedule(id: "source") { completed.fulfill(); return false }
                return false
            }
            await fulfillment(of: [completed], timeout: 2)
            scheduler.stop()
            XCTAssertEqual(attempts, 1)
        }
    }

    // contract-test: supporting surface=gui.apple assertions=apple-workspaces.maintenance,apple-workspaces.isolation
    func testLateChildResponseCannotResurrectRemovedOrReintroducedDirectory() async throws {
        let directory = temporaryDirectory()
        defer { try? FileManager.default.removeItem(at: directory) }
        let cache = NativeWorkspaceOfflineCache(directory: directory), repository = ProjectOfflineMetadataRepository()
        let context = scope(), project = project(), source = source(), key = SymmetricKey(size: .bits256)
        await cache.configure(scope: context, masterKey: key)
        let binding = try ProjectOfflineMetadataBinding(project: project, source: source, scope: context)
        try await repository.reconcile(project: project, sources: [source], scope: context, cache: cache, validate: {})
        let token = try repository.authority(binding: binding, source: source)
        try await repository.accept(page([entry("folder", directory: true)]), path: ".", cursor: nil,
            binding: binding, token: token, cache: cache, validate: {})
        let request = try await repository.begin(path: "folder", binding: binding, token: token, cache: cache)
        let suspended = expectation(description: "Child response validation suspended")
        var continuation: CheckedContinuation<Void, Never>?
        var didSuspend = false
        let child = Task {
            try await repository.accept(page([entry("folder/stale.txt")]), path: "folder", cursor: nil,
                binding: binding, token: token, request: request, cache: cache, validate: {
                    if !didSuspend {
                        didSuspend = true
                        await withCheckedContinuation { continuation = $0; suspended.fulfill() }
                    }
                })
        }
        await fulfillment(of: [suspended], timeout: 2)
        try await repository.accept(page([]), path: ".", cursor: nil,
            binding: binding, token: token, cache: cache, validate: {})
        // Reintroducing the path must not validate an old response generation.
        try await repository.accept(page([entry("folder", directory: true)]), path: ".", cursor: nil,
            binding: binding, token: token, cache: cache, validate: {})
        _ = try await repository.begin(path: "folder", binding: binding, token: token, cache: cache)
        continuation?.resume()
        do { try await child.value; XCTFail("A pruned child response must be retired") }
        catch is CancellationError { }
        let reopened = NativeWorkspaceOfflineCache(directory: directory)
        await reopened.configure(scope: context, masterKey: key)
        let retained = try await ProjectOfflineMetadataRepository().cached(path: "folder", binding: binding, cache: reopened)
        XCTAssertNil(retained)
    }

    // contract-test: supporting surface=gui.apple assertions=apple-workspaces.maintenance,apple-workspaces.isolation
    func testOutstandingPersistFinishesBeforeSourceTombstoneOnEncryptedDisk() async throws {
        let directory = temporaryDirectory()
        defer { try? FileManager.default.removeItem(at: directory) }
        let cache = NativeWorkspaceOfflineCache(directory: directory)
        var suspendWrite = false
        var continuation: CheckedContinuation<Void, Never>?
        let suspended = expectation(description: "Page persist outstanding")
        let repository = ProjectOfflineMetadataRepository(beforePersist: {
            if suspendWrite {
                suspendWrite = false
                await withCheckedContinuation { continuation = $0; suspended.fulfill() }
            }
        })
        let context = scope(), project = project(), source = source(), key = SymmetricKey(size: .bits256)
        await cache.configure(scope: context, masterKey: key)
        let binding = try ProjectOfflineMetadataBinding(project: project, source: source, scope: context)
        try await repository.reconcile(project: project, sources: [source], scope: context, cache: cache, validate: {})
        let token = try repository.authority(binding: binding, source: source)
        suspendWrite = true
        let pageWrite = Task {
            try await repository.accept(page([entry("stale.txt")]), path: ".", cursor: nil,
                binding: binding, token: token, cache: cache, validate: {})
        }
        await fulfillment(of: [suspended], timeout: 2)
        let removal = Task {
            try await repository.reconcile(project: project, sources: [], scope: context, cache: cache, validate: {})
        }
        var revoked = false
        for _ in 0..<100 {
            do { try repository.checkAuthority(token, binding: binding) }
            catch is CancellationError { revoked = true; break }
            await Task.yield()
        }
        XCTAssertTrue(revoked, "Removal must revoke before waiting for the outstanding write")
        continuation?.resume()
        try await pageWrite.value
        try await removal.value
        let reopened = NativeWorkspaceOfflineCache(directory: directory)
        await reopened.configure(scope: context, masterKey: key)
        let retained = try await ProjectOfflineMetadataRepository().cached(path: ".", binding: binding, cache: reopened)
        XCTAssertNil(retained, "The tombstone must remain the final encrypted disk state")
    }

    // contract-test: supporting surface=gui.apple assertions=apple-workspaces.maintenance
    func testSchedulerCadenceStartsAfterActualDispatchFollowingCacheSuspension() async throws {
        var time = Date(timeIntervalSince1970: 1_000), dispatches: [Date] = []
        let scheduler = ProjectOfflineMetadataScheduler(now: { time }, wait: { delay in
            time = time.addingTimeInterval(delay); await Task.yield()
        })
        let suspended = expectation(description: "Pre-dispatch cache suspended")
        let completed = expectation(description: "Two actual dispatches")
        var continuation: CheckedContinuation<Void, Never>?
        scheduler.schedule(id: "source") {
            if dispatches.isEmpty {
                await withCheckedContinuation { continuation = $0; suspended.fulfill() }
            }
            dispatches.append(time)
            if dispatches.count == 2 { completed.fulfill(); return false }
            return true
        }
        await fulfillment(of: [suspended], timeout: 2)
        time = time.addingTimeInterval(10)
        continuation?.resume()
        await fulfillment(of: [completed], timeout: 2)
        scheduler.stop()
        XCTAssertEqual(dispatches.count, 2)
        if dispatches.count == 2 { XCTAssertGreaterThanOrEqual(dispatches[1].timeIntervalSince(dispatches[0]), 3) }
    }

    // contract-test: supporting surface=gui.apple assertions=apple-workspaces.maintenance
    func testCancelledJobCompletionCannotRetireReadmittedJob() async throws {
        for stopWorker in [false, true] {
            var time = Date(timeIntervalSince1970: 1_000)
            let scheduler = ProjectOfflineMetadataScheduler(now: { time }, wait: { delay in
                time = time.addingTimeInterval(delay); await Task.yield()
            })
            let suspended = expectation(description: "Old operation suspended")
            let completed = expectation(description: "Replacement operation completes")
            var continuation: CheckedContinuation<Void, Never>?
            scheduler.schedule(id: "source") {
                await withCheckedContinuation { continuation = $0; suspended.fulfill() }
                return false
            }
            await fulfillment(of: [suspended], timeout: 2)
            if stopWorker { scheduler.stop() } else { scheduler.cancel(id: "source") }
            scheduler.schedule(id: "source") { completed.fulfill(); return false }
            continuation?.resume()
            await fulfillment(of: [completed], timeout: 2)
            scheduler.stop()
        }
    }

    // contract-test: supporting surface=gui.apple assertions=apple-workspaces.maintenance
    func testSchedulerCoalescesRepeatedAdmissionAndReservesGlobalForegroundBudget() async throws {
        var time = Date(timeIntervalSince1970: 1_000), requests: [Date] = []
        let scheduler = ProjectOfflineMetadataScheduler(now: { time }, wait: { delay in
            time = time.addingTimeInterval(delay)
            await Task.yield()
        })
        let completed = expectation(description: "Three serial slices")
        scheduler.schedule(id: "same-source") {
            requests.append(time)
            if requests.count == 3 { completed.fulfill(); return false }
            return true
        }
        scheduler.schedule(id: "same-source") { XCTFail("Duplicate admission must join the same worker"); return false }
        await fulfillment(of: [completed], timeout: 2)
        scheduler.stop()
        XCTAssertEqual(requests.count, 3)
        for index in 1..<requests.count { XCTAssertGreaterThanOrEqual(requests[index].timeIntervalSince(requests[index - 1]), 3) }
    }
}
