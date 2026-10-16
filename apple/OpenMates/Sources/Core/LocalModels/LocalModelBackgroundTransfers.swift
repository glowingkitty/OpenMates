// Durable iOS asset transfers. Only pinned public weights and sandbox-relative
// staging destinations are journaled; installation still requires full size/SHA.
// Specification: specifications/features/apple-local-model-lab/specification.yml
// Assertions: apple-local-model-lab.optional-downloads
import Foundation

/// Persisted attempts include tasks started by earlier processes. Exhaustion is
/// deliberately not a URL error, so the outer transient recovery cannot reset it.
enum LocalModelBackgroundRetryBudget {
    static func nextAttempt(after attempts: Int) throws -> Int {
        guard (0..<6).contains(attempts) else { throw LocalModelInstallError.retryLimitReached }
        return attempts + 1
    }
}

enum LocalModelBackgroundReattachmentPolicy {
    enum Action: Equatable { case resume, awaitCompletion, restart }
    /// Returns whether an existing task owns the continuation. Resume is injected
    /// to exercise the same recovered-task branch without starting real transfers.
    static func reattach(state: URLSessionTask.State, resume: () -> Void) -> Bool {
        switch action(for: state) {
        case .resume: resume(); return true
        case .awaitCompletion: return true
        case .restart: return false
        }
    }
    static func action(for state: URLSessionTask.State) -> Action {
        switch state {
        case .suspended: return .resume
        case .completed: return .restart
        case .running, .canceling: return .awaitCompletion
        @unknown default: return .restart
        }
    }
}

/// A completed OS transfer retains processing ownership until verification and
/// the next OS task are scheduled, or the final store event is enqueued. Waiting
/// never includes the remaining network transfer, and is bounded by the caller.
final class LocalModelBackgroundProcessingBarrier: @unchecked Sendable {
    private let lock = NSLock()
    private var processing: Set<String> = []
    private var observers: [UUID: AsyncStream<Void>.Continuation] = [:]
    func begin(_ staging: String) { lock.lock(); processing.insert(staging); lock.unlock() }
    func settled(_ staging: String) {
        lock.lock()
        processing.remove(staging)
        let listeners = processing.isEmpty ? Array(observers.values) : []
        lock.unlock()
        for listener in listeners { listener.yield(()) }
    }
    private func isSettled() -> Bool { lock.lock(); defer { lock.unlock() }; return processing.isEmpty }
    private func subscribe(_ id: UUID, _ continuation: AsyncStream<Void>.Continuation) {
        lock.lock()
        observers[id] = continuation
        let ready = processing.isEmpty
        lock.unlock()
        if ready { continuation.yield(()) }
    }
    private func unsubscribe(_ id: UUID) {
        lock.lock(); let continuation = observers.removeValue(forKey: id); lock.unlock()
        continuation?.finish()
    }
    @discardableResult
    func wait(timeout: Duration = .seconds(25)) async -> Bool {
        let id = UUID(), updates = AsyncStream<Void>.makeStream(bufferingPolicy: .bufferingNewest(1))
        subscribe(id, updates.continuation)
        defer { unsubscribe(id) }
        return await withTaskGroup(of: Bool.self) { group in
            group.addTask { [self] in
                for await _ in updates.stream {
                    if isSettled() { return true }
                }
                return false
            }
            group.addTask { try? await Task.sleep(for: timeout); return false }
            let settled = await group.next() ?? false
            group.cancelAll()
            return settled
        }
    }
}

/// Persist only bounded byte watermarks, never request URLs or user content.
/// A resumed physical task can report a smaller value before catching up.
enum LocalModelTransferWatermark {
    static func advance(previous: Int64, reported: Int64, total: Int64) -> Int64 {
        min(max(0, total), max(0, max(previous, reported)))
    }
}

#if os(iOS)
import UIKit

struct LocalModelBackgroundDownloader: LocalModelFileDownloading {
    func discardTransfers(in staging: URL) { LocalModelBackgroundTransfers.shared.discard(in: staging) }
    func finishProcessing(in staging: URL) { LocalModelBackgroundTransfers.shared.finishProcessing(in: staging) }
    func setSequentialPackActive(_ active: Bool) { LocalModelBackgroundTransfers.shared.setSequentialPackActive(active) }
    func download(_ file: LocalModelFile, to destination: URL,
                  progress: @escaping @Sendable (Int64) -> Void) async throws {
        try await download(file, to: destination, progress: progress, status: { _ in })
    }
    func download(_ file: LocalModelFile, to destination: URL,
                  progress: @escaping @Sendable (Int64) -> Void,
                  status: @escaping @Sendable (LocalModelTransferStatus) -> Void) async throws {
        try await LocalModelDownloadRecovery.transfer(file: file, status: status) { resume in
            try await LocalModelBackgroundTransfers.shared.transfer(file, to: destination,
                resume: resume, progress: progress, status: status)
        }
    }
}

/// Background tasks remain OS-owned while the process is suspended. On relaunch,
/// the store's manifest journal reattaches to the same transfer UUID/task.
final class LocalModelBackgroundTransfers: NSObject, URLSessionDownloadDelegate, @unchecked Sendable {
    static let identifier = "org.openmates.local-model-assets.v1"
    static let shared = LocalModelBackgroundTransfers()
    private struct Record: Codable, Sendable {
        let id: UUID
        let file: LocalModelFile
        let destination: String
        var attempts: Int
        var completed: Bool
        var errorCode: Int?
        var receivedBytes: Int64? = nil // Optional for journals written before byte checkpoints.
    }
    private struct Waiter {
        let continuation: CheckedContinuation<Void, Error>
        let progress: @Sendable (Int64) -> Void
        let status: @Sendable (LocalModelTransferStatus) -> Void
    }
    @MainActor
    private final class Completion {
        private let handler: () -> Void
        private var finished = false
        private var lease: UIBackgroundTaskIdentifier = .invalid
        private var deadline: Task<Void, Never>?
        init(_ handler: @escaping () -> Void) {
            self.handler = handler
            lease = UIApplication.shared.beginBackgroundTask(withName: "LocalModelAssetProcessing") { [weak self] in
                Task { @MainActor in self?.finish() }
            }
            deadline = Task { [weak self] in
                do { try await Task.sleep(for: .seconds(25)) }
                catch { return }
                self?.finish()
            }
        }
        func process() async {
            guard !finished else { return }
            await LocalModelStore.shared.finishBackgroundEvents()
            guard !finished else { return }
            await LocalModelLiveActivityCoordinator.shared.waitForPendingEffects()
            finish()
        }
        private func finish() {
            guard !finished else { return }
            finished = true
            deadline?.cancel(); deadline = nil
            if lease != .invalid { UIApplication.shared.endBackgroundTask(lease); lease = .invalid }
            handler()
        }
    }
    private let lock = NSLock()
    private let processing = LocalModelBackgroundProcessingBarrier()
    private let root: URL
    private let journal: URL
    private var records: [UUID: Record] = [:]
    private var waiters: [UUID: Waiter] = [:]
    private var tasks: [UUID: URLSessionDownloadTask] = [:]
    private var progressTimes: [UUID: Double] = [:]
    private var journalProgressTimes: [UUID: Double] = [:]
    private var cancellationRequests: Set<UUID> = []
    private var completions: [Completion] = []
    private var finishedEventsPending = false
    private var sequentialPackActive = false
    private static let packProcessingKey = "offline-ai-pack-transition"
    private var session: URLSession!
    private var bootstrapped = false
    private var bootstrapWaiters: [CheckedContinuation<Void, Never>] = []

    private override init() {
        root = FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask)[0]
            .appendingPathComponent("LocalModels", isDirectory: true)
        journal = root.appendingPathComponent(".background-transfers", isDirectory: true)
        super.init()
        try? FileManager.default.createDirectory(at: journal, withIntermediateDirectories: true)
        var excluded = journal
        var values = URLResourceValues(); values.isExcludedFromBackup = true
        try? excluded.setResourceValues(values)
        if let files = try? FileManager.default.contentsOfDirectory(at: journal, includingPropertiesForKeys: nil) {
            for url in files where url.pathExtension == "json" {
                guard let data = try? Data(contentsOf: url), data.count <= 1_048_576,
                      let record = try? JSONDecoder().decode(Record.self, from: data),
                      Self.valid(record), url.lastPathComponent == record.id.uuidString + ".json" else {
                    try? FileManager.default.removeItem(at: url); continue
                }
                records[record.id] = record
            }
        }
        if let files = try? FileManager.default.contentsOfDirectory(at: journal, includingPropertiesForKeys: nil) {
            for url in files where url.pathExtension == "resume" {
                let id = UUID(uuidString: url.deletingPathExtension().lastPathComponent)
                if id.flatMap({ records[$0] }) == nil { try? FileManager.default.removeItem(at: url) }
            }
        }
        let configuration = URLSessionConfiguration.background(withIdentifier: Self.identifier)
        configuration.waitsForConnectivity = true
        configuration.isDiscretionary = false
        configuration.sessionSendsLaunchEvents = true
        configuration.timeoutIntervalForResource = 86_400
        configuration.httpCookieStorage = nil
        configuration.httpShouldSetCookies = false
        configuration.urlCache = nil
        let queue = OperationQueue(); queue.maxConcurrentOperationCount = 1
        session = URLSession(configuration: configuration, delegate: self, delegateQueue: queue)
        session.getAllTasks { [weak self] recovered in self?.bootstrap(recovered) }
    }

    /// Forward UIApplicationDelegate's background-session completion here.
    @MainActor
    func handleEvents(identifier: String, completionHandler: @escaping () -> Void) {
        guard identifier == Self.identifier else { completionHandler(); return }
        let completion = Completion(completionHandler)
        lock.lock()
        if finishedEventsPending {
            finishedEventsPending = false
            lock.unlock()
            Task { await completion.process() }
        } else { completions.append(completion); lock.unlock() }
    }

    private static func valid(_ record: Record) -> Bool {
        let parts = record.destination.split(separator: "/", omittingEmptySubsequences: false)
        guard parts.count >= 2, parts.first?.hasPrefix("partial-") == true,
              parts.allSatisfy({ !$0.isEmpty && $0 != "." && $0 != ".." && !$0.contains("\\") }),
              record.attempts >= 0, record.attempts <= 6 else { return false }
        let manifest = LocalModelManifest(id: .whisper, revision: "background", estimatedSizeBytes: record.file.sizeBytes,
                                           files: [record.file])
        return (try? LocalModelCatalog(models: [manifest]).validated()) != nil
    }
    private func bootstrap(_ recovered: [URLSessionTask]) {
        lock.lock()
        for task in recovered {
            guard let description = task.taskDescription, let id = UUID(uuidString: description),
                  let record = records[id], Self.valid(record),
                  FileManager.default.fileExists(atPath: root.appendingPathComponent(record.destination).deletingLastPathComponent().path),
                  let download = task as? URLSessionDownloadTask else { task.cancel(); continue }
            tasks[id] = download
        }
        for record in Array(records.values) where !FileManager.default.fileExists(atPath: root.appendingPathComponent(record.destination).deletingLastPathComponent().path) {
            records[record.id] = nil; removeJournal(record.id)
        }
        for record in records.values where record.completed || record.errorCode != nil {
            processing.begin(Self.staging(for: record.destination))
        }
        bootstrapped = true
        let pending = bootstrapWaiters; bootstrapWaiters = []
        lock.unlock()
        for waiter in pending { waiter.resume() }
    }
    private func awaitBootstrap() async {
        await withCheckedContinuation { continuation in
            lock.lock()
            if bootstrapped { lock.unlock(); continuation.resume() }
            else { bootstrapWaiters.append(continuation); lock.unlock() }
        }
    }
    func transfer(_ file: LocalModelFile, to destination: URL, resume: Data?,
                  progress: @escaping @Sendable (Int64) -> Void,
                  status: @escaping @Sendable (LocalModelTransferStatus) -> Void) async throws {
        await awaitBootstrap()
        try Task.checkCancellation()
        let prefix = root.standardizedFileURL.path + "/"
        let path = destination.standardizedFileURL.path
        guard path.hasPrefix(prefix) else { throw LocalModelInstallError.invalidCatalog }
        let relative = String(path.dropFirst(prefix.count))
        let id = operationID(file: file, destination: relative)
        try await withTaskCancellationHandler {
            try await withCheckedThrowingContinuation { continuation in
                register(id, file: file, destination: relative, resume: resume,
                         waiter: Waiter(continuation: continuation, progress: progress, status: status))
            }
        } onCancel: { self.cancel(id) }
    }
    private func operationID(file: LocalModelFile, destination: String) -> UUID {
        lock.lock(); defer { lock.unlock() }
        if let existing = records.values.first(where: { $0.file == file && $0.destination == destination }) { return existing.id }
        let id = UUID()
        records[id] = Record(id: id, file: file, destination: destination, attempts: 0, completed: false, errorCode: nil)
        return id
    }
    private func register(_ id: UUID, file: LocalModelFile, destination: String, resume: Data?, waiter: Waiter) {
        lock.lock()
        if cancellationRequests.remove(id) != nil {
            lock.unlock(); waiter.continuation.resume(throwing: CancellationError()); return
        }
        var record = records[id] ?? Record(id: id, file: file, destination: destination,
                                          attempts: 0, completed: false, errorCode: nil)
        guard Self.valid(record), waiters[id] == nil else {
            lock.unlock(); waiter.continuation.resume(throwing: LocalModelInstallError.invalidCatalog); return
        }
        if record.completed {
            if FileManager.default.fileExists(atPath: root.appendingPathComponent(record.destination).path) {
                records[id] = nil; removeJournal(id)
                lock.unlock(); waiter.progress(file.sizeBytes); waiter.continuation.resume(); return
            }
            record.completed = false
        }
        waiters[id] = waiter
        if let existing = tasks[id] {
            if LocalModelBackgroundReattachmentPolicy.reattach(state: existing.state, resume: { existing.resume() }) {
                let received = LocalModelTransferWatermark.advance(previous: record.receivedBytes ?? 0,
                    reported: existing.countOfBytesReceived, total: record.file.sizeBytes)
                record.receivedBytes = received; records[id] = record
                try? save(record)
                processing.settled(Self.staging(for: destination))
                processing.settled(Self.packProcessingKey)
                lock.unlock()
                waiter.progress(max(0, received)); waiter.status(.transferring); return
            }
            // A recovered completed task cannot deliver a second completion.
            tasks[id] = nil
        }
        do { record.attempts = try LocalModelBackgroundRetryBudget.nextAttempt(after: record.attempts) }
        catch {
            waiters[id] = nil
            // Retain the durable exhausted budget until the install owner cleans up.
            lock.unlock(); waiter.continuation.resume(throwing: error); return
        }
        record.errorCode = nil
        records[id] = record
        do { try save(record) }
        catch { waiters[id] = nil; lock.unlock(); waiter.continuation.resume(throwing: error); return }
        let diskResume = try? Data(contentsOf: resumeURL(id))
        let safeResume = LocalModelDownloadRecovery.validatedResumeData(resume ?? diskResume, file: file)
        let task = safeResume.map { session.downloadTask(withResumeData: $0) }
            ?? session.downloadTask(with: file.url)
        task.taskDescription = id.uuidString
        tasks[id] = task
        // Enqueue and release processing under the delegate lock: a very fast
        // completion must not reserve ownership and then have it cleared here.
        task.resume()
        processing.settled(Self.staging(for: destination))
        processing.settled(Self.packProcessingKey)
        lock.unlock()
        waiter.progress(record.receivedBytes ?? 0)
    }
    private static func staging(for destination: String) -> String {
        String(destination.split(separator: "/").first ?? "")
    }
    func setSequentialPackActive(_ active: Bool) {
        lock.lock()
        sequentialPackActive = active
        if active {
            // Hold an OS completion across the model boundary until the next
            // real URLSession task is enqueued, not merely a Swift Task created.
            if !tasks.values.contains(where: { $0.state == .running || $0.state == .suspended }) {
                processing.begin(Self.packProcessingKey)
            }
        } else { processing.settled(Self.packProcessingKey) }
        lock.unlock()
    }
    func finishProcessing(in staging: URL) { processing.settled(staging.lastPathComponent) }
    func waitForPostprocessing() async { await processing.wait() }
    func discard(in staging: URL) {
        let prefix = root.standardizedFileURL.path + "/"
        let path = staging.standardizedFileURL.path
        guard path.hasPrefix(prefix), staging.lastPathComponent.hasPrefix("partial-") else { return }
        let relative = String(path.dropFirst(prefix.count)) + "/"
        lock.lock()
        let stale = records.values.filter { $0.destination.hasPrefix(relative) }
        var active: [URLSessionDownloadTask] = []
        var pending: [Waiter] = []
        for record in stale {
            if let task = tasks.removeValue(forKey: record.id) { active.append(task) }
            if let waiter = waiters.removeValue(forKey: record.id) { pending.append(waiter) }
            records[record.id] = nil; progressTimes[record.id] = nil; journalProgressTimes[record.id] = nil
            cancellationRequests.remove(record.id)
            removeJournal(record.id)
        }
        lock.unlock()
        for task in active { task.cancel() }
        for waiter in pending { waiter.continuation.resume(throwing: CancellationError()) }
    }
    private func cancel(_ id: UUID) {
        lock.lock()
        guard records[id] != nil || tasks[id] != nil || waiters[id] != nil else { lock.unlock(); return }
        cancellationRequests.insert(id)
        let task = tasks[id]
        let waiter = task == nil ? waiters.removeValue(forKey: id) : nil
        if task == nil { records[id] = nil; removeJournal(id) }
        lock.unlock()
        task?.cancel()
        waiter?.continuation.resume(throwing: CancellationError())
    }
    private func save(_ record: Record) throws {
        try JSONEncoder().encode(record).write(to: journal.appendingPathComponent(record.id.uuidString + ".json"), options: .atomic)
    }
    private func resumeURL(_ id: UUID) -> URL { journal.appendingPathComponent(id.uuidString + ".resume") }
    private func removeJournal(_ id: UUID) {
        try? FileManager.default.removeItem(at: journal.appendingPathComponent(id.uuidString + ".json"))
        try? FileManager.default.removeItem(at: resumeURL(id))
    }
    private func taskID(_ task: URLSessionTask) -> UUID? { task.taskDescription.flatMap(UUID.init(uuidString:)) }

    func urlSession(_ session: URLSession, taskIsWaitingForConnectivity task: URLSessionTask) {
        guard let id = taskID(task) else { return }
        lock.lock(); let status = waiters[id]?.status; lock.unlock()
        status?(.waitingForConnection)
    }
    func urlSession(_ session: URLSession, downloadTask: URLSessionDownloadTask, didWriteData bytesWritten: Int64,
                    totalBytesWritten: Int64, totalBytesExpectedToWrite: Int64) {
        guard let id = taskID(downloadTask) else { return }
        lock.lock()
        guard var record = records[id], !cancellationRequests.contains(id),
              tasks[id]?.taskIdentifier == downloadTask.taskIdentifier else { lock.unlock(); return }
        let received = LocalModelTransferWatermark.advance(previous: record.receivedBytes ?? 0,
            reported: totalBytesWritten, total: record.file.sizeBytes)
        record.receivedBytes = received
        records[id] = record
        let now = ProcessInfo.processInfo.systemUptime
        let complete = received == record.file.sizeBytes
        // At most one small atomic journal write per second, plus completion.
        if complete || now - (journalProgressTimes[id] ?? -Double.infinity) >= 1 {
            try? save(record)
            journalProgressTimes[id] = now
        }
        let emit = now - (progressTimes[id] ?? -Double.infinity) >= 0.15 || complete
        if emit { progressTimes[id] = now }
        let waiter = emit ? waiters[id] : nil
        lock.unlock()
        waiter?.status(.transferring)
        waiter?.progress(received)
    }
    func urlSession(_ session: URLSession, downloadTask: URLSessionDownloadTask, didFinishDownloadingTo location: URL) {
        guard let id = taskID(downloadTask) else { return }
        lock.lock()
        if let current = tasks[id], current.taskIdentifier != downloadTask.taskIdentifier { lock.unlock(); return }
        guard var record = records[id], Self.valid(record), !cancellationRequests.contains(id) else { lock.unlock(); return }
        do {
            guard let response = downloadTask.response else { throw LocalModelInstallError.invalidResponse }
            try LocalModelHTTPDownloader.validateResponse(response)
            let destination = root.appendingPathComponent(record.destination)
            // Staging's owner may have been removed while this process was away.
            guard FileManager.default.fileExists(atPath: destination.deletingLastPathComponent().path) else {
                throw LocalModelInstallError.notInstalled
            }
            if FileManager.default.fileExists(atPath: destination.path) { try FileManager.default.removeItem(at: destination) }
            try FileManager.default.moveItem(at: location, to: destination)
            record.completed = true; record.errorCode = nil; record.receivedBytes = record.file.sizeBytes
            records[id] = record
            try save(record)
        } catch {
            record.errorCode = NSURLErrorBadServerResponse
            records[id] = record
            try? save(record)
        }
        lock.unlock()
    }
    func urlSession(_ session: URLSession, task: URLSessionTask, didCompleteWithError error: Error?) {
        guard let id = taskID(task) else { return }
        lock.lock()
        // A completed recovered task can still have a queued delegate delivery.
        // Its callback must never drain the replacement task's continuation.
        if let current = tasks[id], current.taskIdentifier != task.taskIdentifier { lock.unlock(); return }
        tasks[id] = nil; progressTimes[id] = nil; journalProgressTimes[id] = nil
        guard var record = records[id] else { lock.unlock(); return }
        // Reserve before waking the detached installer or handing events to UIKit.
        processing.begin(Self.staging(for: record.destination))
        if sequentialPackActive { processing.begin(Self.packProcessingKey) }
        let waiter = waiters.removeValue(forKey: id)
        let cancelled = cancellationRequests.remove(id) != nil || (error as NSError?)?.code == NSURLErrorCancelled
        var failure: Error? = error
        if cancelled { failure = CancellationError() }
        else if !record.completed {
            failure = error ?? NSError(domain: NSURLErrorDomain, code: record.errorCode ?? NSURLErrorBadServerResponse)
            record.errorCode = (failure as NSError?)?.code
            records[id] = record
            if let bytes = LocalModelDownloadRecovery.validatedResumeData((error as NSError?)?.userInfo["NSURLSessionDownloadTaskResumeData"] as? Data, file: record.file) {
                try? bytes.write(to: resumeURL(id), options: .atomic)
            }
            try? save(record)
        }
        if (waiter != nil && record.completed) || cancelled {
            records[id] = nil; removeJournal(id)
        }
        lock.unlock()
        if let waiter {
            if let failure { waiter.continuation.resume(throwing: failure) }
            else { waiter.progress(record.file.sizeBytes); waiter.continuation.resume() }
        }
    }
    func urlSessionDidFinishEvents(forBackgroundURLSession session: URLSession) {
        lock.lock()
        let callbacks = completions; completions = []
        finishedEventsPending = callbacks.isEmpty
        lock.unlock()
        for callback in callbacks { Task { @MainActor in await callback.process() } }
    }
}
#endif
