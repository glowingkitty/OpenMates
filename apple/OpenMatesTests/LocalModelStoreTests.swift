import CryptoKit
import XCTest
@testable import OpenMates

@MainActor
final class LocalModelStoreTests: XCTestCase {
    private let fixture = Data("verified local fixture".utf8)
    private func root() -> URL {
        FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
    }
    private func manifest(hash: String? = nil, path: String = "model.bin") -> LocalModelManifest {
        let digest = SHA256.hash(data: fixture).map { String(format: "%02x", $0) }.joined()
        return LocalModelManifest(id: .whisper, revision: "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa", estimatedSizeBytes: Int64(fixture.count), files: [
            LocalModelFile(path: path, url: URL(string: "https://huggingface.co/fixture/resolve/aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa/model.bin")!,
                           sha256: hash ?? digest, sizeBytes: Int64(fixture.count))
        ])
    }
    private func catalog(_ manifest: LocalModelManifest) throws -> Data {
        try JSONEncoder().encode(LocalModelCatalog(models: [manifest]))
    }

    // contract-test: direct surface=gui.apple assertions=apple-local-model-lab.optional-downloads
    func testRelaunchedSixthBackgroundAttemptCannotResetThroughTransientRecovery() async throws {
        let budget = PersistedBackgroundAttemptProbe(attempts: 5)
        do {
            try await LocalModelDownloadRecovery.transfer(file: manifest().files[0], status: { _ in },
                sleep: { _ in }, attempt: { _ in try budget.startAndFail() })
            XCTFail("Exhausted persisted budget must be terminal")
        } catch {
            XCTAssertEqual(error as? LocalModelInstallError, .retryLimitReached)
        }
        XCTAssertEqual(budget.attempts, 6)
        XCTAssertEqual(budget.startedTasks, 1, "Relaunch permits only the sixth physical task")
        XCTAssertFalse(LocalModelDownloadRecovery.isTransient(LocalModelInstallError.retryLimitReached as NSError))
    }

    // contract-test: direct surface=gui.apple assertions=apple-local-model-lab.optional-downloads
    func testRecoveredSuspendedTaskResumesAndCompletedTaskCannotAwaitAnotherCallback() {
        var resumeCalls = 0
        XCTAssertTrue(LocalModelBackgroundReattachmentPolicy.reattach(state: .suspended, resume: { resumeCalls += 1 }))
        XCTAssertEqual(resumeCalls, 1, "The recovered OS task actually receives resume")
        XCTAssertFalse(LocalModelBackgroundReattachmentPolicy.reattach(state: .completed, resume: { resumeCalls += 1 }))
        XCTAssertTrue(LocalModelBackgroundReattachmentPolicy.reattach(state: .running, resume: { resumeCalls += 1 }))
        XCTAssertTrue(LocalModelBackgroundReattachmentPolicy.reattach(state: .canceling, resume: { resumeCalls += 1 }))
        XCTAssertEqual(resumeCalls, 1)
        XCTAssertEqual(try LocalModelBackgroundRetryBudget.nextAttempt(after: 5), 6)
        XCTAssertThrowsError(try LocalModelBackgroundRetryBudget.nextAttempt(after: 6))
    }

    // contract-test: direct surface=gui.apple assertions=apple-local-model-lab.optional-downloads
    func testBackgroundCompletionWaitsForVerificationAndNextTaskSchedulingOnly() async throws {
        let root = root(), first = manifest().files[0]
        defer { try? FileManager.default.removeItem(at: root) }
        let second = LocalModelFile(path: "second.bin", url: first.url, sha256: first.sha256, sizeBytes: first.sizeBytes)
        let manifest = LocalModelManifest(id: .whisper, revision: manifest().revision,
            estimatedSizeBytes: first.sizeBytes * 2, files: [first, second])
        let barrier = LocalModelBackgroundProcessingBarrier()
        let verifying = AsyncStream<Void>.makeStream(), nextScheduled = AsyncStream<Void>.makeStream()
        let verifyGate = BackgroundTransferTestGate(entered: verifying.continuation)
        let networkGate = BackgroundTransferTestGate(entered: nextScheduled.continuation)
        let downloader = BackgroundBarrierFixtureDownloader(bytes: fixture, barrier: barrier, nextTransfer: networkGate)
        let installer = Task {
            try await LocalModelDisk.install(manifest, root: root, downloader: downloader, progress: { _ in },
                beforeVerification: { await verifyGate.wait() })
        }
        for await _ in verifying.stream { break }
        let completed = BackgroundCompletionProbe()
        let waiting = Task { let result = await barrier.wait(timeout: .seconds(5)); completed.mark(); return result }
        await Task.yield()
        XCTAssertFalse(completed.value, "OS completion must retain verification ownership")
        await verifyGate.open()
        for await _ in nextScheduled.stream { break }
        let settled = await waiting.value
        XCTAssertTrue(settled, "Enqueueing the next task releases processing without waiting for its network transfer")
        XCTAssertTrue(completed.value)
        await networkGate.open()
        _ = try await installer.value
        barrier.settled(downloader.stagingName)
    }

    // contract-test: direct surface=gui.apple assertions=apple-local-model-lab.optional-downloads
    func testBackgroundCompletionWaitsForVerifiedInstallAndFinalActivityEvent() async throws {
        let root = root(), barrier = LocalModelBackgroundProcessingBarrier()
        defer { try? FileManager.default.removeItem(at: root) }
        let verifying = AsyncStream<Void>.makeStream()
        let verifyGate = BackgroundTransferTestGate(entered: verifying.continuation)
        let events = BackgroundCompletionProbe()
        let downloader = BackgroundBarrierFixtureDownloader(bytes: fixture, barrier: barrier, terminal: events)
        let store = LocalModelStore(catalog: try catalog(manifest()), root: root, downloader: downloader,
            verifyExisting: false, activityEvents: { event in
                if case .finished(_, _, .verified) = event { events.mark() }
            }, beforeVerification: { await verifyGate.wait() })
        let installing = Task { await store.download(.whisper) }
        for await _ in verifying.stream { break }
        let waiting = Task { await barrier.wait(timeout: .seconds(5)) }
        XCTAssertFalse(events.value)
        await verifyGate.open()
        await installing.value
        let settled = await waiting.value
        XCTAssertTrue(settled)
        XCTAssertTrue(downloader.finishedAfterEvent)
        XCTAssertEqual(store.state(for: .whisper), .ready)
    }

    // contract-test: direct surface=gui.apple assertions=apple-local-model-lab.optional-downloads
    func testBackgroundProcessingWaitHasBoundedDeadline() async {
        let barrier = LocalModelBackgroundProcessingBarrier()
        barrier.begin("partial-fixture")
        let settled = await barrier.wait(timeout: .milliseconds(1))
        XCTAssertFalse(settled, "A processing lease cannot indefinitely delay UIKit completion")
        barrier.settled("partial-fixture")
        let completed = await barrier.wait(timeout: .seconds(1))
        XCTAssertTrue(completed)
    }

    // LML-001: integrity failure never exposes partially downloaded weights to inference.
    // contract-test: direct surface=gui.apple assertions=apple-local-model-lab.optional-downloads
    func testDownloadVerifiesThenRestoresAndRemovalDeletesAssets() async throws {
        let root = root(), manifest = manifest()
        defer { try? FileManager.default.removeItem(at: root) }
        let transport = FixtureDownloader(bytes: fixture)
        let store = LocalModelStore(catalog: try catalog(manifest), root: root, downloader: transport, verifyExisting: false)
        XCTAssertEqual(store.state(for: .whisper), .notDownloaded)
        XCTAssertThrowsError(try store.installedDirectory(.whisper))
        await store.download(.whisper)
        XCTAssertEqual(store.state(for: .whisper), .ready)
        XCTAssertEqual(try Data(contentsOf: store.installedDirectory(.whisper).appendingPathComponent("model.bin")), fixture)
        let requests = await transport.requestCount
        XCTAssertEqual(requests, 1)

        let reopened = LocalModelStore(catalog: try catalog(manifest), root: root, downloader: transport, verifyExisting: false)
        await reopened.restoreExisting()
        XCTAssertEqual(reopened.state(for: .whisper), .ready)
        let afterReopen = await transport.requestCount
        XCTAssertEqual(afterReopen, 1, "Restoring an install is disk-only")
        await reopened.remove(.whisper)
        XCTAssertEqual(reopened.state(for: .whisper), .notDownloaded)
        XCTAssertFalse(FileManager.default.fileExists(atPath: root.appendingPathComponent("whisper").path))
    }

    // LML-001: a truncated download or bit corruption is never marked ready.
    // contract-test: direct surface=gui.apple assertions=apple-local-model-lab.optional-downloads
    func testBadChecksumIsRejectedAndPartialDirectoryRemoved() async throws {
        let root = root()
        defer { try? FileManager.default.removeItem(at: root) }
        let store = LocalModelStore(catalog: try catalog(manifest(hash: String(repeating: "0", count: 64))),
                                   root: root, downloader: FixtureDownloader(bytes: fixture), verifyExisting: false)
        await store.download(.whisper)
        guard case .failed = store.state(for: .whisper) else { return XCTFail("Corruption must be visible") }
        XCTAssertThrowsError(try store.installedDirectory(.whisper))
        XCTAssertEqual(try FileManager.default.contentsOfDirectory(atPath: root.path), [])
    }

    // LML-001: cached installs are checked again before the test runtime can load them.
    // contract-test: direct surface=gui.apple assertions=apple-local-model-lab.optional-downloads
    func testSameSizeCorruptionOnDiskIsRejectedOnReopen() async throws {
        let root = root(), manifest = manifest()
        defer { try? FileManager.default.removeItem(at: root) }
        let transport = FixtureDownloader(bytes: fixture)
        let store = LocalModelStore(catalog: try catalog(manifest), root: root, downloader: transport, verifyExisting: false)
        await store.download(.whisper)
        let file = try store.installedDirectory(.whisper).appendingPathComponent("model.bin")
        try Data(repeating: 0, count: fixture.count).write(to: file)
        let reopened = LocalModelStore(catalog: try catalog(manifest), root: root, downloader: transport, verifyExisting: false)
        await reopened.restoreExisting()
        guard case .failed = reopened.state(for: .whisper) else { return XCTFail("Same-size corruption must fail verification") }
        XCTAssertThrowsError(try reopened.installedDirectory(.whisper))
    }

    // LML-004: cancelling releases transport and discards only the in-progress installation.
    // contract-test: direct surface=gui.apple assertions=apple-local-model-lab.optional-downloads
    func testCancellationRemovesPartialAssetsAndLeavesRetryAvailable() async throws {
        let root = root()
        defer { try? FileManager.default.removeItem(at: root) }
        let signal = AsyncStream<Void>.makeStream()
        let downloader = WaitingDownloader(started: signal.continuation)
        let store = LocalModelStore(catalog: try catalog(manifest()), root: root, downloader: downloader, verifyExisting: false)
        let task = Task { await store.download(.whisper) }
        var iterator = signal.stream.makeAsyncIterator()
        _ = await iterator.next()
        store.cancel(.whisper)
        await task.value
        XCTAssertEqual(store.state(for: .whisper), .notDownloaded)
        XCTAssertEqual(try FileManager.default.contentsOfDirectory(atPath: root.path), [])
    }

    // contract-test: supporting surface=gui.apple assertions=apple-local-model-lab.optional-downloads
    func testTransferAndHashProgressAdvanceSeparatelyAndTerminalCallbacksCannotReopenInstall() async throws {
        let root = root(), manifest = manifest()
        defer { try? FileManager.default.removeItem(at: root) }
        let progress = InstallProgressProbe()
        let transport = LateProgressDownloader(bytes: fixture)
        _ = try await LocalModelDisk.install(manifest, root: root, downloader: transport, progress: { _ in },
                                             detailedProgress: { progress.append($0) })
        let values = progress.values
        XCTAssertTrue(values.contains { $0.phase == .transfer })
        XCTAssertTrue(values.contains { $0.phase == .verification && $0.verifiedBytes == 0 })
        XCTAssertEqual(values.last?.verifiedBytes, Int64(fixture.count))
        XCTAssertEqual(values.last?.transferredBytes, Int64(fixture.count))
        for (earlier, later) in zip(values, values.dropFirst()) {
            XCTAssertGreaterThan(later.sequence, earlier.sequence)
            XCTAssertGreaterThanOrEqual(later.transferredBytes, earlier.transferredBytes)
            XCTAssertGreaterThanOrEqual(later.verifiedBytes, earlier.verifiedBytes)
        }
        let store = LocalModelStore(catalog: try catalog(manifest), root: root, downloader: transport, verifyExisting: false)
        await store.download(.whisper)
        XCTAssertEqual(store.state(for: .whisper), .ready)
        await transport.emitLateProgress()
        await Task.yield()
        XCTAssertEqual(store.state(for: .whisper), .ready)
        XCTAssertNil(store.progress(for: .whisper))
    }

    // contract-test: supporting surface=gui.apple assertions=apple-local-model-lab.optional-downloads
    func testInterruptedFileRetriesPreserveEarlierVerifiedAssetsAndRejectUnpinnedResumeMetadata() async throws {
        let root = root(), first = manifest().files[0]
        defer { try? FileManager.default.removeItem(at: root) }
        let second = LocalModelFile(path: "second.bin", url: first.url.deletingLastPathComponent().appendingPathComponent("second.bin"),
                                    sha256: first.sha256, sizeBytes: first.sizeBytes)
        let manifest = LocalModelManifest(id: .whisper, revision: manifest().revision,
                                          estimatedSizeBytes: first.sizeBytes + second.sizeBytes, files: [first, second])
        let transport = RecoveringFixtureDownloader(bytes: fixture)
        let progress = InstallProgressProbe()
        _ = try await LocalModelDisk.install(manifest, root: root, downloader: transport, progress: { _ in },
                                             detailedProgress: { progress.append($0) })
        let counts = await transport.counts
        XCTAssertEqual(counts["model.bin"], 1)
        XCTAssertEqual(counts["second.bin"], 2)
        XCTAssertTrue(progress.values.contains { $0.phase == .retrying && $0.retryAttempt == 2 && $0.verifiedBytes == first.sizeBytes })
        XCTAssertEqual(progress.values.last?.verifiedBytes, manifest.estimatedSizeBytes)
        let wrong = try PropertyListSerialization.data(fromPropertyList: ["NSURLSessionDownloadURL": "https://huggingface.co/fixture/resolve/main/model.bin"], format: .binary, options: 0)
        XCTAssertNil(LocalModelDownloadRecovery.validatedResumeData(wrong, file: first))
        let exact = try PropertyListSerialization.data(fromPropertyList: ["NSURLSessionDownloadURL": first.url.absoluteString], format: .binary, options: 0)
        XCTAssertEqual(LocalModelDownloadRecovery.validatedResumeData(exact, file: first), exact)
    }

    // contract-test: supporting surface=gui.apple assertions=apple-local-model-lab.optional-downloads
    func testRetriesAreBoundedAndCancellationDrainsBeforeDiscardingStaging() async throws {
        let attempts = RetryAttemptProbe()
        do {
            try await LocalModelDownloadRecovery.transfer(file: manifest().files[0], status: { _ in }, sleep: { _ in }, attempt: { _ in
                attempts.increment()
                throw NSError(domain: NSURLErrorDomain, code: NSURLErrorNetworkConnectionLost)
            })
            XCTFail("Repeated network failures must terminate")
        } catch { XCTAssertEqual((error as NSError).code, NSURLErrorNetworkConnectionLost) }
        XCTAssertEqual(attempts.count, 6)
        let root = root()
        defer { try? FileManager.default.removeItem(at: root) }
        let started = AsyncStream<Void>.makeStream()
        let transport = NonCooperativeDownloader(bytes: fixture, started: started.continuation)
        let store = LocalModelStore(catalog: try catalog(manifest()), root: root, downloader: transport, verifyExisting: false)
        let task = Task { await store.download(.whisper) }
        var iterator = started.stream.makeAsyncIterator()
        _ = await iterator.next()
        store.cancel(.whisper)
        guard case .downloading = store.state(for: .whisper) else { return XCTFail("Transport still owns installation") }
        let removal = Task { await store.remove(.whisper) }
        await transport.finish()
        await task.value
        await removal.value
        XCTAssertEqual(store.state(for: .whisper), .notDownloaded)
        XCTAssertEqual(try FileManager.default.contentsOfDirectory(atPath: root.path), [])
        await transport.emitLateProgress()
        await Task.yield()
        XCTAssertEqual(store.state(for: .whisper), .notDownloaded)
    }

    // contract-test: supporting surface=gui.apple assertions=apple-local-model-lab.optional-downloads
    func testArchivedResumeOriginalRequestRequiresExactPinnedGETAndRejectsMalformedArchive() throws {
        let file = manifest().files[0]
        func metadata(_ request: URLRequest) throws -> Data {
            let archive = try NSKeyedArchiver.archivedData(withRootObject: request as NSURLRequest, requiringSecureCoding: true)
            return try PropertyListSerialization.data(fromPropertyList: ["NSURLSessionResumeOriginalRequest": archive], format: .binary, options: 0)
        }
        let exact = try metadata(URLRequest(url: file.url))
        XCTAssertEqual(LocalModelDownloadRecovery.validatedResumeData(exact, file: file), exact)
        let mismatch = try metadata(URLRequest(url: URL(string: "https://huggingface.co/fixture/resolve/main/model.bin")!))
        XCTAssertNil(LocalModelDownloadRecovery.validatedResumeData(mismatch, file: file))
        var post = URLRequest(url: file.url); post.httpMethod = "POST"
        XCTAssertNil(LocalModelDownloadRecovery.validatedResumeData(try metadata(post), file: file))
        let malformed = try PropertyListSerialization.data(fromPropertyList: [
            "NSURLSessionResumeOriginalRequest": Data("malformed archive".utf8),
            "NSURLSessionDownloadURL": file.url.absoluteString
        ], format: .binary, options: 0)
        XCTAssertNil(LocalModelDownloadRecovery.validatedResumeData(malformed, file: file), "Malformed original request cannot bypass validation through another URL field")
    }

    // contract-test: supporting surface=gui.apple assertions=apple-local-model-lab.optional-downloads
    func testReconstructed206TransferStillRequiresFullSizeAndChecksumBeforeReady() async throws {
        for mode in Reconstructed206Downloader.Mode.allCases {
            let root = root()
            defer { try? FileManager.default.removeItem(at: root) }
            let store = LocalModelStore(catalog: try catalog(manifest()), root: root,
                downloader: Reconstructed206Downloader(bytes: fixture, mode: mode), verifyExisting: false)
            await store.download(.whisper)
            if mode == .full {
                XCTAssertEqual(store.state(for: .whisper), .ready)
                XCTAssertEqual(try Data(contentsOf: store.installedDirectory(.whisper).appendingPathComponent("model.bin")), fixture)
            } else {
                guard case .failed = store.state(for: .whisper) else { return XCTFail("A partial/corrupt 206 file is never ready") }
                XCTAssertThrowsError(try store.installedDirectory(.whisper))
            }
        }
    }

    // contract-test: supporting surface=gui.apple assertions=apple-local-model-lab.optional-downloads,apple-live-activities.download.progress,apple-live-activities.download.completion
    func testRecoveredOperationKeepsUUIDVerifiesStagingAndEmitsOneTerminalEvent() async throws {
        let root = root(), manifest = manifest(), operation = UUID()
        defer { try? FileManager.default.removeItem(at: root) }
        let pending = LocalModelPendingInstall(operation: operation, manifest: manifest)
        let staging = root.appendingPathComponent(pending.directoryName)
        try FileManager.default.createDirectory(at: staging, withIntermediateDirectories: true)
        try fixture.write(to: staging.appendingPathComponent("model.bin"))
        try JSONEncoder().encode(pending).write(to: staging.appendingPathComponent(".pending-install.json"))
        let finished = AsyncStream<Void>.makeStream()
        var starts: [UUID] = [], terminals: [(UUID, LocalModelDownloadOutcome)] = []
        let transport = FixtureDownloader(bytes: fixture)
        let store = LocalModelStore(catalog: try catalog(manifest), root: root, downloader: transport,
            verifyExisting: false, recoverBackgroundDownloads: true, activityEvents: { event in
                switch event {
                case .started(_, let id, _): starts.append(id)
                case .finished(_, let id, let outcome): terminals.append((id, outcome)); finished.continuation.yield(())
                case .progress: break
                }
            })
        await store.restoreExisting()
        var iterator = finished.stream.makeAsyncIterator()
        _ = await iterator.next()
        XCTAssertEqual(starts, [operation])
        XCTAssertEqual(terminals.count, 1)
        XCTAssertEqual(terminals.first?.0, operation)
        XCTAssertEqual(terminals.first?.1, .verified)
        XCTAssertEqual(store.state(for: .whisper), .ready)
        let count = await transport.requestCount
        XCTAssertEqual(count, 0, "A fully hashed staged file is reused after relaunch")
        await store.restoreExisting()
        XCTAssertEqual(terminals.count, 1, "Rechecking an installed receipt never emits a success notification")
    }

    // contract-test: supporting surface=gui.apple assertions=apple-local-model-lab.optional-downloads,apple-live-activities.download.progress
    func testCancelledRemovedOperationEmitsTerminalOnceAfterTransportDrains() async throws {
        let root = root()
        defer { try? FileManager.default.removeItem(at: root) }
        let started = AsyncStream<Void>.makeStream()
        let transport = NonCooperativeDownloader(bytes: fixture, started: started.continuation)
        var terminals: [LocalModelDownloadOutcome] = []
        let store = LocalModelStore(catalog: try catalog(manifest()), root: root, downloader: transport,
            verifyExisting: false, activityEvents: { event in
                if case .finished(_, _, let outcome) = event { terminals.append(outcome) }
            })
        let download = Task { await store.download(.whisper) }
        var iterator = started.stream.makeAsyncIterator()
        _ = await iterator.next()
        let removal = Task { await store.remove(.whisper) }
        await Task.yield()
        XCTAssertTrue(terminals.isEmpty)
        await transport.finish()
        await download.value; await removal.value
        XCTAssertEqual(terminals, [.cancelled])
    }

    // LML-001: a manifest cannot escape the app's model cache or pull mutable remote assets.
    // contract-test: direct surface=gui.apple assertions=apple-local-model-lab.optional-downloads
    func testCatalogRejectsTraversalDuplicatesAndUnpinnedURLs() throws {
        XCTAssertThrowsError(try LocalModelCatalog(models: [manifest(path: "../outside.bin")]).validated())
        XCTAssertThrowsError(try LocalModelCatalog(models: [manifest(), manifest()]).validated())
        let original = manifest()
        let file = LocalModelFile(path: "model.bin", url: URL(string: "https://huggingface.co/fixture/resolve/main/model.bin")!,
                                  sha256: original.files[0].sha256, sizeBytes: Int64(fixture.count))
        let mutable = LocalModelManifest(id: .whisper, revision: "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa", estimatedSizeBytes: Int64(fixture.count), files: [file])
        XCTAssertThrowsError(try LocalModelCatalog(models: [mutable]).validated())
    }
}

private actor FixtureDownloader: LocalModelFileDownloading {
    let bytes: Data
    private(set) var requestCount = 0
    init(bytes: Data) { self.bytes = bytes }
    func download(_ file: LocalModelFile, to destination: URL,
                  progress: @escaping @Sendable (Int64) -> Void) async throws {
        requestCount += 1
        try bytes.write(to: destination)
        progress(Int64(bytes.count))
    }
}

private struct WaitingDownloader: LocalModelFileDownloading {
    let started: AsyncStream<Void>.Continuation
    func download(_ file: LocalModelFile, to destination: URL,
                  progress: @escaping @Sendable (Int64) -> Void) async throws {
        try Data([1]).write(to: destination)
        started.yield(())
        try await Task.sleep(for: .seconds(30))
        throw LocalModelInstallError.invalidResponse
    }
}

private final class InstallProgressProbe: @unchecked Sendable {
    private let lock = NSLock()
    private var captured: [LocalModelInstallProgress] = []
    var values: [LocalModelInstallProgress] { lock.lock(); defer { lock.unlock() }; return captured }
    func append(_ value: LocalModelInstallProgress) { lock.lock(); defer { lock.unlock() }; captured.append(value) }
}
private final class RetryAttemptProbe: @unchecked Sendable {
    private let lock = NSLock()
    private var attempts = 0
    var count: Int { lock.lock(); defer { lock.unlock() }; return attempts }
    func increment() { lock.lock(); defer { lock.unlock() }; attempts += 1 }
}
private actor LateProgressDownloader: LocalModelFileDownloading {
    let bytes: Data
    private var progress: (@Sendable (Int64) -> Void)?
    init(bytes: Data) { self.bytes = bytes }
    func download(_ file: LocalModelFile, to destination: URL,
                  progress: @escaping @Sendable (Int64) -> Void) async throws {
        self.progress = progress
        try bytes.write(to: destination)
        progress(Int64(bytes.count))
    }
    func emitLateProgress() { progress?(0) }
}
private actor RecoveringFixtureDownloader: LocalModelFileDownloading {
    let bytes: Data
    private(set) var counts: [String: Int] = [:]
    init(bytes: Data) { self.bytes = bytes }
    func download(_ file: LocalModelFile, to destination: URL,
                  progress: @escaping @Sendable (Int64) -> Void) async throws {
        try await download(file, to: destination, progress: progress, status: { _ in })
    }
    func download(_ file: LocalModelFile, to destination: URL,
                  progress: @escaping @Sendable (Int64) -> Void,
                  status: @escaping @Sendable (LocalModelTransferStatus) -> Void) async throws {
        try await LocalModelDownloadRecovery.transfer(file: file, status: status, sleep: { _ in }) { _ in
            try await self.attempt(file, destination: destination, progress: progress)
        }
    }
    private func attempt(_ file: LocalModelFile, destination: URL, progress: @Sendable (Int64) -> Void) throws {
        counts[file.path, default: 0] += 1
        if file.path == "second.bin", counts[file.path] == 1 {
            progress(file.sizeBytes / 2)
            throw NSError(domain: NSURLErrorDomain, code: NSURLErrorNetworkConnectionLost)
        }
        try bytes.write(to: destination)
        progress(file.sizeBytes)
    }
}
private actor NonCooperativeDownloader: LocalModelFileDownloading {
    let bytes: Data
    let started: AsyncStream<Void>.Continuation
    private var continuation: CheckedContinuation<Void, Never>?
    private var progress: (@Sendable (Int64) -> Void)?
    init(bytes: Data, started: AsyncStream<Void>.Continuation) { self.bytes = bytes; self.started = started }
    func download(_ file: LocalModelFile, to destination: URL,
                  progress: @escaping @Sendable (Int64) -> Void) async throws {
        self.progress = progress
        try bytes.write(to: destination)
        await withCheckedContinuation { continuation in
            self.continuation = continuation
            started.yield(())
        }
    }
    func finish() { continuation?.resume(); continuation = nil }
    func emitLateProgress() { progress?(1) }
}

private struct Reconstructed206Downloader: LocalModelFileDownloading {
    enum Mode: CaseIterable, Sendable { case full, truncated, corrupt }
    let bytes: Data
    let mode: Mode
    func download(_ file: LocalModelFile, to destination: URL,
                  progress: @escaping @Sendable (Int64) -> Void) async throws {
        let response = HTTPURLResponse(url: file.url, statusCode: 206, httpVersion: "HTTP/1.1", headerFields: nil)!
        try LocalModelHTTPDownloader.validateResponse(response)
        let split = bytes.count / 2
        let savedPrefix = bytes.prefix(split)
        let receivedSuffix = bytes.suffix(bytes.count - split)
        var reconstructed = Data(savedPrefix)
        if mode != .truncated { reconstructed.append(receivedSuffix) }
        if mode == .corrupt { reconstructed[0] ^= 0xff }
        try reconstructed.write(to: destination)
        progress(Int64(reconstructed.count))
    }
}


private final class PersistedBackgroundAttemptProbe: @unchecked Sendable {
    private let lock = NSLock()
    private var count: Int
    private var started = 0
    init(attempts: Int) { count = attempts }
    var attempts: Int { lock.lock(); defer { lock.unlock() }; return count }
    var startedTasks: Int { lock.lock(); defer { lock.unlock() }; return started }
    func startAndFail() throws {
        lock.lock(); defer { lock.unlock() }
        count = try LocalModelBackgroundRetryBudget.nextAttempt(after: count)
        started += 1
        throw NSError(domain: NSURLErrorDomain, code: NSURLErrorNetworkConnectionLost)
    }
}
private final class BackgroundCompletionProbe: @unchecked Sendable {
    private let lock = NSLock()
    private var completed = false
    var value: Bool { lock.lock(); defer { lock.unlock() }; return completed }
    func mark() { lock.lock(); completed = true; lock.unlock() }
}
private actor BackgroundTransferTestGate {
    let entered: AsyncStream<Void>.Continuation
    private var continuation: CheckedContinuation<Void, Never>?
    private var isOpen = false
    init(entered: AsyncStream<Void>.Continuation) { self.entered = entered }
    func wait() async {
        guard !isOpen else { return }
        await withCheckedContinuation { continuation in
            self.continuation = continuation
            entered.yield(())
        }
    }
    func open() { isOpen = true; continuation?.resume(); continuation = nil }
}
private final class BackgroundBarrierFixtureDownloader: LocalModelFileDownloading, @unchecked Sendable {
    let bytes: Data
    let barrier: LocalModelBackgroundProcessingBarrier
    let nextTransfer: BackgroundTransferTestGate?
    let terminal: BackgroundCompletionProbe?
    private let lock = NSLock()
    private var count = 0
    private var staging = ""
    private var finalEventWasEnqueued = false
    init(bytes: Data, barrier: LocalModelBackgroundProcessingBarrier,
         nextTransfer: BackgroundTransferTestGate? = nil, terminal: BackgroundCompletionProbe? = nil) {
        self.bytes = bytes; self.barrier = barrier; self.nextTransfer = nextTransfer; self.terminal = terminal
    }
    var stagingName: String { lock.lock(); defer { lock.unlock() }; return staging }
    var finishedAfterEvent: Bool { lock.lock(); defer { lock.unlock() }; return finalEventWasEnqueued }
    private func enqueue(at destination: URL) -> Int {
        lock.lock(); defer { lock.unlock() }
        staging = destination.deletingLastPathComponent().lastPathComponent
        count += 1
        barrier.settled(staging)
        return count
    }
    func download(_ file: LocalModelFile, to destination: URL,
                  progress: @escaping @Sendable (Int64) -> Void) async throws {
        let number = enqueue(at: destination)
        if number == 2, let nextTransfer { await nextTransfer.wait() }
        try bytes.write(to: destination)
        barrier.begin(stagingName)
        progress(file.sizeBytes)
    }
    func finishProcessing(in staging: URL) {
        lock.lock(); finalEventWasEnqueued = terminal?.value ?? false; lock.unlock()
        barrier.settled(staging.lastPathComponent)
    }
}
