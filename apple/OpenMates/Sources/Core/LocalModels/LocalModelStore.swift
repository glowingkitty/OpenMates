// Optional model assets are installed atomically after per-file checksum validation.
// The store never submits recordings, text, or inference requests to a server.
// Specification: specifications/features/apple-local-model-lab/specification.yml
// Assertions: apple-local-model-lab.optional-downloads
// Specification: specifications/features/apple-live-activities/specification.yml
// Assertions: apple-live-activities.download.progress, apple-live-activities.download.completion
import Combine
import CryptoKit
import Foundation
#if DEBUG && os(iOS)
import UIKit
#endif

enum LocalModelID: String, Codable, CaseIterable, Identifiable, Sendable {
    case whisper, privacyFilter, pocketTTS
    var id: String { rawValue }
}

struct LocalModelFile: Codable, Equatable, Sendable {
    let path: String
    let url: URL
    let sha256: String
    let sizeBytes: Int64
}

struct LocalModelManifest: Codable, Equatable, Identifiable, Sendable {
    let id: LocalModelID
    let revision: String
    let estimatedSizeBytes: Int64
    let files: [LocalModelFile]
}

struct LocalModelCatalog: Codable, Sendable {
    let models: [LocalModelManifest]
    func validated() throws -> [LocalModelManifest] {
        guard Set(models.map(\.id)).count == models.count else { throw LocalModelInstallError.invalidCatalog }
        for model in models {
            guard !model.revision.isEmpty, model.revision.allSatisfy({ $0.isASCII && ($0.isLetter || $0.isNumber || $0 == "-") }),
                  !model.files.isEmpty, Set(model.files.map(\.path)).count == model.files.count,
                  model.estimatedSizeBytes > 0,
                  model.files.reduce(Int64(0), { $0 + $1.sizeBytes }) == model.estimatedSizeBytes else {
                throw LocalModelInstallError.invalidCatalog
            }
            for file in model.files {
                let urlParts = file.url.pathComponents
                guard let resolve = urlParts.firstIndex(of: "resolve"), resolve + 1 < urlParts.count else {
                    throw LocalModelInstallError.invalidCatalog
                }
                let pinnedRevision = urlParts[resolve + 1]
                let parts = file.path.split(separator: "/", omittingEmptySubsequences: false)
                guard !parts.isEmpty, parts.allSatisfy({ !$0.isEmpty && $0 != "." && $0 != ".." && !$0.contains("\\") }),
                      !file.path.hasPrefix("/"), file.path != ".installed.json", file.sizeBytes > 0,
                      file.sha256.count == 64, file.sha256.allSatisfy({ $0.isHexDigit && !$0.isUppercase }),
                      file.url.scheme == "https", file.url.host == "huggingface.co",
                      pinnedRevision.count == 40, pinnedRevision.allSatisfy({ $0.isHexDigit && !$0.isUppercase }) else { throw LocalModelInstallError.invalidCatalog }
            }
        }
        return models
    }
}

enum LocalModelInstallState: Equatable, Sendable {
    case notDownloaded
    case downloading(Double)
    case verifying(Double)
    case waitingForConnection(Double)
    case retrying(Double)
    case ready
    case failed(String)
}

enum LocalModelInstallPhase: Equatable, Sendable { case transfer, verification, waitingForConnection, retrying }
enum LocalModelTransferStatus: Sendable { case waitingForConnection, retrying(Int), transferring }

struct LocalModelInstallProgress: Equatable, Sendable {
    let phase: LocalModelInstallPhase
    let transferredBytes: Int64
    let verifiedBytes: Int64
    let totalBytes: Int64
    let sequence: UInt64
    let retryAttempt: Int
    var fraction: Double {
        guard totalBytes > 0 else { return 0 }
        let bytes = phase == .verification ? verifiedBytes : transferredBytes
        return min(1, max(0, Double(bytes) / Double(totalBytes)))
    }
}

/// URLSession callbacks and hashing share a bounded, ordered cumulative snapshot.
private final class LocalModelInstallReporter: @unchecked Sendable {
    private let lock = NSLock()
    private let total: Int64
    private var transferred: Int64
    private var verified: Int64 = 0
    private var sequence: UInt64 = 0
    private var retryAttempt = 0
    private let emit: @Sendable (LocalModelInstallProgress) -> Void
    init(total: Int64, transferred: Int64 = 0, emit: @escaping @Sendable (LocalModelInstallProgress) -> Void) {
        self.total = total; self.transferred = transferred; self.emit = emit
    }
    func update(_ phase: LocalModelInstallPhase, bytes: Int64, attempt: Int? = nil) {
        lock.lock()
        if phase == .transfer { transferred = max(transferred, min(total, max(0, bytes))) }
        else if phase == .verification { verified = max(verified, min(total, max(0, bytes))) }
        if let attempt { retryAttempt = attempt }
        sequence &+= 1
        let value = LocalModelInstallProgress(phase: phase, transferredBytes: transferred,
            verifiedBytes: verified, totalBytes: total, sequence: sequence, retryAttempt: retryAttempt)
        lock.unlock()
        emit(value)
    }
}

enum LocalModelInstallError: Error, Equatable {
    case invalidCatalog, invalidResponse, checksumMismatch, missingFiles, insufficientSpace, notInstalled, retryLimitReached
}

protocol LocalModelFileDownloading: Sendable {
    func download(_ file: LocalModelFile, to destination: URL,
                  progress: @escaping @Sendable (Int64) -> Void) async throws
    func download(_ file: LocalModelFile, to destination: URL,
                  progress: @escaping @Sendable (Int64) -> Void,
                  status: @escaping @Sendable (LocalModelTransferStatus) -> Void) async throws
    func discardTransfers(in staging: URL)
    func finishProcessing(in staging: URL)
}

extension LocalModelFileDownloading {
    func discardTransfers(in staging: URL) {}
    func finishProcessing(in staging: URL) {}
    func download(_ file: LocalModelFile, to destination: URL,
                  progress: @escaping @Sendable (Int64) -> Void,
                  status: @escaping @Sendable (LocalModelTransferStatus) -> Void) async throws {
        try await download(file, to: destination, progress: progress)
    }
}

/// Recovery is scoped to the exact pinned file in this active operation.
/// Earlier verified files stay in staging. The iOS transport separately persists
/// its bounded task budget and validated metadata for OS background relaunch.
enum LocalModelDownloadRecovery {
    static func transfer(file: LocalModelFile,
                         status: @escaping @Sendable (LocalModelTransferStatus) -> Void,
                         sleep: @escaping @Sendable (Int) async throws -> Void = { seconds in
                             try await Task.sleep(for: .seconds(seconds))
                         },
                         attempt: @escaping @Sendable (Data?) async throws -> Void) async throws {
        var resume: Data?
        for number in 1...6 {
            try Task.checkCancellation()
            do {
                status(.transferring)
                try await attempt(resume)
                return
            } catch {
                try Task.checkCancellation()
                let failure = error as NSError
                // If OS resume metadata becomes unusable, fall back to the exact
                // pinned request within the same attempt budget.
                guard number < 6, isTransient(failure) || (resume != nil && failure.domain == NSURLErrorDomain) else { throw error }
                resume = validatedResumeData(failure.userInfo["NSURLSessionDownloadTaskResumeData"] as? Data, file: file)
                status(.retrying(number + 1))
                NativeDiagnostics.event("offline_model_transfer_retry", category: "local_models", counts: ["attempt": number + 1])
                try await sleep(min(16, 1 << (number - 1)))
            }
        }
    }
    static func isTransient(_ error: NSError) -> Bool {
        guard error.domain == NSURLErrorDomain else { return false }
        return [NSURLErrorTimedOut, NSURLErrorNetworkConnectionLost, NSURLErrorNotConnectedToInternet,
                NSURLErrorCannotConnectToHost, NSURLErrorCannotFindHost, NSURLErrorDNSLookupFailed].contains(error.code)
    }
    static func validatedResumeData(_ data: Data?, file: LocalModelFile) -> Data? {
        guard let data, data.count <= 4_194_304,
              let plist = try? PropertyListSerialization.propertyList(from: data, format: nil) as? [String: Any] else { return nil }
        // Original request is preferred because the current URL may be an HF CDN redirect.
        if let original = plist["NSURLSessionResumeOriginalRequest"] {
            guard let requestData = original as? Data,
                  let request = try? NSKeyedUnarchiver.unarchivedObject(ofClass: NSURLRequest.self, from: requestData),
                  request.url == file.url, request.httpMethod == "GET", request.httpBody == nil,
                  request.value(forHTTPHeaderField: "Authorization") == nil,
                  request.value(forHTTPHeaderField: "Cookie") == nil else { return nil }
            return data
        }
        guard let url = plist["NSURLSessionDownloadURL"] as? String, URL(string: url) == file.url else { return nil }
        return data
    }
}

private final class LocalDownloadProgress: NSObject, URLSessionDownloadDelegate, @unchecked Sendable {
    private let progress: @Sendable (Int64) -> Void
    private let status: @Sendable (LocalModelTransferStatus) -> Void
    private let lock = NSLock()
    private var lastUpdate: Double = -Double.infinity
    init(_ progress: @escaping @Sendable (Int64) -> Void, status: @escaping @Sendable (LocalModelTransferStatus) -> Void) {
        self.progress = progress; self.status = status
    }
    func urlSession(_ session: URLSession, taskIsWaitingForConnectivity task: URLSessionTask) {
        status(.waitingForConnection)
    }
    func urlSession(_ session: URLSession, downloadTask: URLSessionDownloadTask, didFinishDownloadingTo location: URL) {}
    func urlSession(_ session: URLSession, downloadTask: URLSessionDownloadTask, didWriteData bytesWritten: Int64,
                    totalBytesWritten: Int64, totalBytesExpectedToWrite: Int64) {
        lock.lock()
        let now = ProcessInfo.processInfo.systemUptime
        let emit = now - lastUpdate >= 0.15 || totalBytesWritten == totalBytesExpectedToWrite
        if emit { lastUpdate = now }
        lock.unlock()
        if emit { status(.transferring); progress(totalBytesWritten) }
    }
}

struct LocalModelHTTPDownloader: LocalModelFileDownloading {
    static func validateResponse(_ response: URLResponse) throws {
        guard let response = response as? HTTPURLResponse, [200, 206].contains(response.statusCode) else {
            throw LocalModelInstallError.invalidResponse
        }
    }
    func download(_ file: LocalModelFile, to destination: URL,
                  progress: @escaping @Sendable (Int64) -> Void) async throws {
        try await download(file, to: destination, progress: progress, status: { _ in })
    }
    func download(_ file: LocalModelFile, to destination: URL,
                  progress: @escaping @Sendable (Int64) -> Void,
                  status: @escaping @Sendable (LocalModelTransferStatus) -> Void) async throws {
        let configuration = URLSessionConfiguration.ephemeral
        configuration.waitsForConnectivity = true
        configuration.timeoutIntervalForRequest = 60
        configuration.timeoutIntervalForResource = 3_600
        configuration.urlCache = nil
        configuration.httpCookieStorage = nil
        configuration.httpShouldSetCookies = false
        let session = URLSession(configuration: configuration)
        defer { session.invalidateAndCancel() }
        try await LocalModelDownloadRecovery.transfer(file: file, status: status) { resume in
            let delegate = LocalDownloadProgress(progress, status: status)
            let temporary: URL
            let response: URLResponse
            if let resume {
                (temporary, response) = try await session.download(resumeFrom: resume, delegate: delegate)
            } else {
                (temporary, response) = try await session.download(for: URLRequest(url: file.url), delegate: delegate)
            }
            defer { try? FileManager.default.removeItem(at: temporary) }
            try Task.checkCancellation()
            try Self.validateResponse(response)
            try FileManager.default.moveItem(at: temporary, to: destination)
        }
    }
}

struct LocalModelPendingInstall: Codable, Sendable {
    let operation: UUID
    let manifest: LocalModelManifest
    var directoryName: String { "partial-\(manifest.id.rawValue)-\(operation.uuidString)" }
}

/// Disk work runs away from the main actor and hashes bounded chunks, including the 1.2 GB PII artifact.
enum LocalModelDisk {
    static func verify(_ manifest: LocalModelManifest, at directory: URL, needsReceipt: Bool = true,
                       progress: @escaping @Sendable (Int64) -> Void = { _ in }) throws {
        if needsReceipt {
            let data = try Data(contentsOf: directory.appendingPathComponent(".installed.json"))
            guard try JSONDecoder().decode(LocalModelManifest.self, from: data) == manifest else {
                throw LocalModelInstallError.missingFiles
            }
        }
        var completed: Int64 = 0
        progress(0)
        for file in manifest.files {
            try Task.checkCancellation()
            let prior = completed
            try verify(file, at: directory.appendingPathComponent(file.path)) { progress(prior + $0) }
            completed += file.sizeBytes
        }
    }
    static func verify(_ file: LocalModelFile, at url: URL,
                       progress: @escaping @Sendable (Int64) -> Void = { _ in }) throws {
        let values = try url.resourceValues(forKeys: [.fileSizeKey, .isRegularFileKey, .isSymbolicLinkKey])
        guard values.isRegularFile == true, values.isSymbolicLink != true,
              Int64(values.fileSize ?? -1) == file.sizeBytes else { throw LocalModelInstallError.missingFiles }
        let handle = try FileHandle(forReadingFrom: url)
        defer { try? handle.close() }
        let verificationStart = ProcessInfo.processInfo.systemUptime
        var hash = SHA256()
        var hashed: Int64 = 0
        var lastProgress = ProcessInfo.processInfo.systemUptime
        progress(0)
        while let data = try handle.read(upToCount: 1_048_576), !data.isEmpty {
            try Task.checkCancellation()
            hash.update(data: data)
            hashed += Int64(data.count)
            let now = ProcessInfo.processInfo.systemUptime
            if now - lastProgress >= 0.15 || hashed == file.sizeBytes {
                progress(hashed); lastProgress = now
            }
        }
        let actual = hash.finalize().map { String(format: "%02x", $0) }.joined()
        guard actual == file.sha256 else { throw LocalModelInstallError.checksumMismatch }
        NativeSyncPerfLog.info("phase=offlineModelVerification bytes=\(hashed) durationMs=\(Int((ProcessInfo.processInfo.systemUptime - verificationStart) * 1000))")
    }
    static func install(_ manifest: LocalModelManifest, root: URL, downloader: any LocalModelFileDownloading,
                        progress: @escaping @Sendable (Double) -> Void,
                        detailedProgress: @escaping @Sendable (LocalModelInstallProgress) -> Void = { _ in },
                        beforeVerification: @escaping @Sendable () async throws -> Void = {},
                        operation: UUID = UUID(), recoverExistingStaging: Bool = false) async throws -> URL {
        let reporter = LocalModelInstallReporter(total: manifest.estimatedSizeBytes) { value in
            detailedProgress(value)
            progress(min(0.99, Double(value.transferredBytes + value.verifiedBytes) / Double(value.totalBytes * 2)))
        }
        let manager = FileManager.default
        try manager.createDirectory(at: root, withIntermediateDirectories: true)
        var root = root
        var resourceValues = URLResourceValues(); resourceValues.isExcludedFromBackup = true
        try root.setResourceValues(resourceValues)
        let available = try root.resourceValues(forKeys: [.volumeAvailableCapacityForImportantUsageKey])
            .volumeAvailableCapacityForImportantUsage
        // Downloads are sequential: leave headroom for the URLSession temporary copy of the largest file.
        let largest = manifest.files.map(\.sizeBytes).max() ?? 0
        if !recoverExistingStaging, let available, available < manifest.estimatedSizeBytes + largest + 150_000_000 {
            throw LocalModelInstallError.insufficientSpace
        }
        let pending = LocalModelPendingInstall(operation: operation, manifest: manifest)
        let staging = root.appendingPathComponent(pending.directoryName, isDirectory: true)
        try manager.createDirectory(at: staging, withIntermediateDirectories: true)
        if recoverExistingStaging {
            try JSONEncoder().encode(pending).write(to: staging.appendingPathComponent(".pending-install.json"), options: .atomic)
        }
        defer {
            downloader.discardTransfers(in: staging)
            try? manager.removeItem(at: staging)
        }
        var completed: Int64 = 0
        for file in manifest.files {
            try Task.checkCancellation()
            let destination = staging.appendingPathComponent(file.path)
            try manager.createDirectory(at: destination.deletingLastPathComponent(), withIntermediateDirectories: true)
            let prior = completed
            reporter.update(.transfer, bytes: prior)
            if recoverExistingStaging, manager.fileExists(atPath: destination.path) {
                // Only completed, fully verified files survive recovery. A partial
                // or corrupted file never skips the exact size/SHA validation.
                do {
                    reporter.update(.verification, bytes: prior)
                    try verify(file, at: destination) { reporter.update(.verification, bytes: prior + $0) }
                    reporter.update(.transfer, bytes: prior + file.sizeBytes)
                    completed += file.sizeBytes
                    continue
                } catch is CancellationError { throw CancellationError() }
                  catch { try manager.removeItem(at: destination) }
            }
            if recoverExistingStaging {
                let free = try root.resourceValues(forKeys: [.volumeAvailableCapacityForImportantUsageKey])
                    .volumeAvailableCapacityForImportantUsage
                // Reused files already occupy disk. Check headroom only for the
                // file actually requiring transfer, after discarding corruption.
                if let free, free < file.sizeBytes + 150_000_000 { throw LocalModelInstallError.insufficientSpace }
            }
            try await downloader.download(file, to: destination, progress: { bytes in
                reporter.update(.transfer, bytes: prior + min(max(0, bytes), file.sizeBytes))
            }, status: { status in
                switch status {
                case .transferring: reporter.update(.transfer, bytes: prior)
                case .waitingForConnection: reporter.update(.waitingForConnection, bytes: prior)
                case .retrying(let attempt): reporter.update(.retrying, bytes: prior, attempt: attempt)
                }
            })
            reporter.update(.transfer, bytes: prior + file.sizeBytes)
            reporter.update(.verification, bytes: prior)
            try await beforeVerification()
            try verify(file, at: destination) { bytes in
                reporter.update(.verification, bytes: prior + bytes)
            }
            completed += file.sizeBytes
        }
        try Task.checkCancellation()
        try JSONEncoder().encode(manifest).write(to: staging.appendingPathComponent(".installed.json"), options: .atomic)
        let installed = root.appendingPathComponent(manifest.id.rawValue, isDirectory: true)
        // Existing assets remain available until every replacement asset has passed validation.
        if manager.fileExists(atPath: installed.path) {
            let backup = root.appendingPathComponent("replacement-\(manifest.id.rawValue)-\(UUID().uuidString)", isDirectory: true)
            try manager.moveItem(at: installed, to: backup)
            do { try manager.moveItem(at: staging, to: installed) }
            catch {
                try manager.moveItem(at: backup, to: installed)
                throw error
            }
            try? manager.removeItem(at: backup)
        } else { try manager.moveItem(at: staging, to: installed) }
        try? manager.removeItem(at: installed.appendingPathComponent(".pending-install.json"))
        progress(1)
        return installed
    }
}

@MainActor
final class LocalModelStore: ObservableObject {
    static let shared: LocalModelStore = {
        #if DEBUG
        if ProcessInfo.processInfo.arguments.contains("--ui-test-local-lab-progress-fixture") {
            return LocalModelStore.makeProgressFixture()
        }
        #endif
        #if os(iOS)
        return LocalModelStore(downloader: LocalModelBackgroundDownloader(), verifyExisting: false, recoverBackgroundDownloads: true,
            activityEvents: { LocalModelLiveActivityCoordinator.shared.handle($0) })
        #else
        return LocalModelStore(verifyExisting: false, activityEvents: { LocalModelLiveActivityCoordinator.shared.handle($0) })
        #endif
    }()
    let models: [LocalModelManifest]
    @Published private(set) var states: [LocalModelID: LocalModelInstallState] = [:]
    @Published private(set) var catalogError: String?
    @Published private(set) var progressByModel: [LocalModelID: LocalModelInstallProgress] = [:]
    private let root: URL
    private let downloader: any LocalModelFileDownloading
    private let beforeVerification: @Sendable () async throws -> Void
    private let recoverBackgroundDownloads: Bool
    private var jobs: [LocalModelID: Task<URL, Error>] = [:]
    private var generations: [LocalModelID: UUID] = [:]
    private var restoreJob: Task<Void, Never>?
    private var pendingOperations: [LocalModelID: UUID] = [:]
    private var activityOperations: Set<UUID> = []
    private let activityEvents: @MainActor (LocalModelDownloadActivityEvent) -> Void

    init(catalog: Data? = nil, root: URL? = nil, downloader: any LocalModelFileDownloading = LocalModelHTTPDownloader(),
         verifyExisting: Bool = true, recoverBackgroundDownloads: Bool = false,
         activityEvents: @escaping @MainActor (LocalModelDownloadActivityEvent) -> Void = { _ in },
         beforeVerification: @escaping @Sendable () async throws -> Void = {}) {
        self.recoverBackgroundDownloads = recoverBackgroundDownloads
        self.activityEvents = activityEvents
        self.beforeVerification = beforeVerification
        self.root = root ?? FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask)[0]
            .appendingPathComponent("LocalModels", isDirectory: true)
        self.downloader = downloader
        do {
            let bundled = Bundle.main.url(forResource: "catalog", withExtension: "json", subdirectory: "LocalModels")
                ?? Bundle.main.url(forResource: "catalog", withExtension: "json")
            guard let data = try catalog ?? bundled.map({ try Data(contentsOf: $0) }) else {
                throw LocalModelInstallError.invalidCatalog
            }
            models = try JSONDecoder().decode(LocalModelCatalog.self, from: data).validated()
        } catch {
            models = []
            catalogError = AppStrings.localLabDownloadFailed
        }
        for id in LocalModelID.allCases { states[id] = .notDownloaded }
        if verifyExisting || recoverBackgroundDownloads {
            restoreJob = Task { await restoreExisting(validateInstalled: verifyExisting) }
        }
    }
    func state(for id: LocalModelID) -> LocalModelInstallState { states[id] ?? .notDownloaded }
    func progress(for id: LocalModelID) -> LocalModelInstallProgress? { progressByModel[id] }
    func manifest(for id: LocalModelID) -> LocalModelManifest? { models.first { $0.id == id } }
    func installedDirectory(_ id: LocalModelID) throws -> URL {
        guard state(for: id) == .ready else { throw LocalModelInstallError.notInstalled }
        return root.appendingPathComponent(id.rawValue, isDirectory: true)
    }
    func download(_ id: LocalModelID) async { await download(id, operation: pendingOperations[id] ?? UUID()) }
    private func download(_ id: LocalModelID, operation: UUID,
                          onStarted: @MainActor () -> Void = {}) async {
        guard jobs[id] == nil, state(for: id) != .ready, let manifest = manifest(for: id) else { onStarted(); return }
        let generation = operation; generations[id] = generation
        activityOperations.insert(generation)
        activityEvents(.started(model: id, operation: generation, totalBytes: manifest.estimatedSizeBytes))
        states[id] = .downloading(0)
        progressByModel[id] = nil
        let root = root, downloader = downloader, beforeVerification = beforeVerification
        let recoverExistingStaging = recoverBackgroundDownloads
        // An immutable MainActor reference is Sendable; a nested capture of an
        // outer weak variable would race under Swift 6. Progress tasks stay weak
        // and generation-fenced after the operation finishes or is removed.
        let progressStore = self
        let job = Task.detached(priority: .utility) {
            try await LocalModelDisk.install(manifest, root: root, downloader: downloader, progress: { _ in },
                detailedProgress: { value in
                    Task { @MainActor [weak progressStore] in
                        progressStore?.acceptProgress(value, id: id, generation: generation)
                    }
                }, beforeVerification: beforeVerification, operation: operation, recoverExistingStaging: recoverExistingStaging)
        }
        jobs[id] = job
        pendingOperations[id] = nil
        onStarted()
        do {
            _ = try await job.value
            if generations[id] == generation { states[id] = .ready }
        } catch {
            if generations[id] == generation {
                if job.isCancelled || error is CancellationError { states[id] = .notDownloaded }
                else if (error as? LocalModelInstallError) == .insufficientSpace {
                    states[id] = .failed(AppStrings.localLabNotEnoughSpace)
                } else { states[id] = .failed(AppStrings.localLabDownloadFailed) }
            }
        }
        if generations[id] == generation {
            let outcome: LocalModelDownloadOutcome = state(for: id) == .ready ? .verified :
                (job.isCancelled ? .cancelled : .failed)
            finishActivity(id, operation: generation, outcome: outcome)
            jobs[id] = nil; progressByModel[id] = nil
        }
    }
    private func finishActivity(_ id: LocalModelID, operation: UUID, outcome: LocalModelDownloadOutcome) {
        guard activityOperations.remove(operation) != nil else { return }
        activityEvents(.finished(model: id, operation: operation, outcome: outcome))
        if let manifest = manifest(for: id) {
            let staging = root.appendingPathComponent(LocalModelPendingInstall(operation: operation, manifest: manifest).directoryName)
            downloader.finishProcessing(in: staging)
        }
    }
    private func acceptProgress(_ value: LocalModelInstallProgress, id: LocalModelID, generation: UUID) {
        guard generations[id] == generation, jobs[id] != nil else { return }
        switch state(for: id) {
        case .downloading, .verifying, .waitingForConnection, .retrying: break
        default: return // Queued callbacks can never overwrite a terminal state.
        }
        guard value.sequence > (progressByModel[id]?.sequence ?? 0) else { return }
        progressByModel[id] = value
        if activityOperations.contains(generation) { activityEvents(.progress(model: id, operation: generation, value: value)) }
        switch value.phase {
        case .transfer: states[id] = .downloading(value.fraction)
        case .verification: states[id] = .verifying(value.fraction)
        case .waitingForConnection: states[id] = .waitingForConnection(value.fraction)
        case .retrying: states[id] = .retrying(value.fraction)
        }
    }
    func cancel(_ id: LocalModelID) { jobs[id]?.cancel() }
    func remove(_ id: LocalModelID) async {
        let running = jobs[id]
        if let pending = pendingOperations.removeValue(forKey: id), let manifest = manifest(for: id) {
            let staging = root.appendingPathComponent(LocalModelPendingInstall(operation: pending, manifest: manifest).directoryName)
            downloader.discardTransfers(in: staging)
            try? FileManager.default.removeItem(at: staging)
        }
        let operation = generations[id]
        running?.cancel()
        let removalGeneration = UUID()
        generations[id] = removalGeneration
        if let running { _ = try? await running.value }
        if let operation { finishActivity(id, operation: operation, outcome: .cancelled) }
        guard generations[id] == removalGeneration else { return }
        jobs[id] = nil
        progressByModel[id] = nil
        do {
            let directory = root.appendingPathComponent(id.rawValue, isDirectory: true)
            if FileManager.default.fileExists(atPath: directory.path) { try FileManager.default.removeItem(at: directory) }
            states[id] = .notDownloaded
        } catch { states[id] = .failed(AppStrings.localLabDownloadFailed) }
    }
    /// Initial disk restoration and recovered operation registration, not full downloads.
    func waitUntilRestored() async { if let restoreJob { await restoreJob.value } }
    /// Background event delivery waits for current verification/install ownership
    /// and the next OS task enqueue, never for the rest of a long download.
    func finishBackgroundEvents() async {
        await waitUntilRestored()
        #if os(iOS)
        await LocalModelBackgroundTransfers.shared.waitForPostprocessing()
        #endif
    }
    func prepareForLab() async {
        await waitUntilRestored()
        await restoreExisting(validateInstalled: true)
    }
    func restoreExisting(validateInstalled: Bool = true) async {
        // Recover only a journal matching this exact pinned catalog. Arbitrary
        // stale staging is discarded, and active owners are never disturbed.
        var pendingInstalls: [LocalModelPendingInstall] = []
        if jobs.isEmpty, let entries = try? FileManager.default.contentsOfDirectory(at: root, includingPropertiesForKeys: nil) {
            for entry in entries where entry.lastPathComponent.hasPrefix("partial-") {
                if recoverBackgroundDownloads,
                   let data = try? Data(contentsOf: entry.appendingPathComponent(".pending-install.json")),
                   let pending = try? JSONDecoder().decode(LocalModelPendingInstall.self, from: data),
                   pending.directoryName == entry.lastPathComponent,
                   models.contains(pending.manifest),
                   !pendingInstalls.contains(where: { $0.manifest.id == pending.manifest.id }) {
                    pendingInstalls.append(pending)
                    pendingOperations[pending.manifest.id] = pending.operation
                } else { try? FileManager.default.removeItem(at: entry) }
            }
        }
        if validateInstalled {
            for manifest in models {
                let id = manifest.id
                let directory = root.appendingPathComponent(id.rawValue, isDirectory: true)
                guard FileManager.default.fileExists(atPath: directory.path), jobs[id] == nil, state(for: id) != .ready else { continue }
                let generation = UUID(); generations[id] = generation
                states[id] = .verifying(0)
                progressByModel[id] = nil
                let progressStore = self
                let reporter = LocalModelInstallReporter(total: manifest.estimatedSizeBytes, transferred: manifest.estimatedSizeBytes) { value in
                    Task { @MainActor [weak progressStore] in
                        progressStore?.acceptProgress(value, id: id, generation: generation)
                    }
                }
                let job = Task.detached(priority: .utility) {
                    try LocalModelDisk.verify(manifest, at: directory) { reporter.update(.verification, bytes: $0) }
                    return directory
                }
                jobs[id] = job
                do {
                    _ = try await job.value
                    if generations[id] == generation { states[id] = .ready }
                } catch {
                    if generations[id] == generation {
                        states[id] = job.isCancelled || error is CancellationError ? .notDownloaded : .failed(AppStrings.localLabDownloadFailed)
                    }
                }
                if generations[id] == generation { jobs[id] = nil; progressByModel[id] = nil }
            }
        }
        for pending in pendingInstalls {
            guard pendingOperations[pending.manifest.id] == pending.operation else { continue }
            if state(for: pending.manifest.id) == .ready {
                let staging = root.appendingPathComponent(pending.directoryName)
                downloader.discardTransfers(in: staging)
                try? FileManager.default.removeItem(at: staging)
                pendingOperations[pending.manifest.id] = nil
                continue
            }
            guard jobs[pending.manifest.id] == nil else { continue }
            // Each resumed operation owns its own Task; initialization does not
            // wait for every large transfer before discovering the others.
            await withCheckedContinuation { continuation in
                Task { await download(pending.manifest.id, operation: pending.operation,
                                      onStarted: { continuation.resume() }) }
            }
        }
    }
    #if DEBUG
    private static func makeProgressFixture() -> LocalModelStore {
        let bytes = Data(repeating: 0x41, count: 1_048_576)
        let root = FileManager.default.temporaryDirectory.appendingPathComponent("local-model-progress-fixture-" + UUID().uuidString)
        let revision = String(repeating: "a", count: 40)
        let digest = SHA256.hash(data: bytes).map { String(format: "%02x", $0) }.joined()
        let models = LocalModelID.allCases.map { id in
            LocalModelManifest(id: id, revision: revision, estimatedSizeBytes: Int64(bytes.count), files: [
                LocalModelFile(path: "fixture.bin", url: URL(string: "https://huggingface.co/fixture/resolve/\(revision)/fixture.bin")!,
                               sha256: digest, sizeBytes: Int64(bytes.count))
            ])
        }
        do {
            let privacy = models.first { $0.id == .privacyFilter }!
            let directory = root.appendingPathComponent(LocalModelID.privacyFilter.rawValue)
            try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
            try bytes.write(to: directory.appendingPathComponent("fixture.bin"))
            try JSONEncoder().encode(privacy).write(to: directory.appendingPathComponent(".installed.json"))
            let catalog = try JSONEncoder().encode(LocalModelCatalog(models: models))
            let hold = ProcessInfo.processInfo.arguments.contains("--ui-test-local-lab-hold-download")
            let interrupted = ProcessInfo.processInfo.arguments.contains("--ui-test-local-lab-interrupted-download")
            return LocalModelStore(catalog: catalog, root: root,
                downloader: LocalModelProgressFixtureDownloader(bytes: bytes, hold: hold, interrupted: interrupted,
                    activityFixture: ProcessInfo.processInfo.arguments.contains("--ui-test-local-lab-live-activity")),
                activityEvents: { LocalModelLiveActivityCoordinator.shared.handle($0) },
                beforeVerification: { try await Task.sleep(for: .seconds(3)) })
        } catch {
            return LocalModelStore(catalog: Data(), root: root, verifyExisting: false)
        }
    }
    #endif

}

#if DEBUG
/// Disposable native UI coverage: no remote assets, provider calls or real account state.
private struct LocalModelProgressFixtureDownloader: LocalModelFileDownloading {
    let bytes: Data
    let hold: Bool
    let interrupted: Bool
    let activityFixture: Bool
    func download(_ file: LocalModelFile, to destination: URL,
                  progress: @escaping @Sendable (Int64) -> Void) async throws {
        try await download(file, to: destination, progress: progress, status: { _ in })
    }
    func download(_ file: LocalModelFile, to destination: URL,
                  progress: @escaping @Sendable (Int64) -> Void,
                  status: @escaping @Sendable (LocalModelTransferStatus) -> Void) async throws {
        #if os(iOS)
        // Only the deterministic UI fixture leases a short execution window.
        // Production transfers use URLSession background delivery, not this task.
        let lease = await MainActor.run { activityFixture ? LocalModelProgressFixtureLease() : nil }
        defer { Task { @MainActor in lease?.end() } }
        #endif
        status(.transferring)
        for step in 1...4 {
            try await Task.sleep(for: .milliseconds(hold ? 500 : activityFixture ? 3_000 : 1_000))
            progress(file.sizeBytes * Int64(step) / 4)
            if hold { while true { try await Task.sleep(for: .seconds(1)) } }
            if interrupted, step == 2 {
                status(.waitingForConnection)
                try await Task.sleep(for: .seconds(3))
                status(.retrying(1))
                try await Task.sleep(for: .seconds(2))
                status(.transferring)
            }
        }
        try bytes.write(to: destination)
    }
}

#if os(iOS)
@MainActor
private final class LocalModelProgressFixtureLease {
    private var identifier: UIBackgroundTaskIdentifier = .invalid
    init() {
        identifier = UIApplication.shared.beginBackgroundTask(withName: "LocalModelActivityFixture") { [weak self] in
            Task { @MainActor in self?.end() }
        }
        Task { [weak self] in
            try? await Task.sleep(for: .seconds(20))
            self?.end()
        }
    }
    func end() {
        guard identifier != .invalid else { return }
        UIApplication.shared.endBackgroundTask(identifier)
        identifier = .invalid
    }
}
#endif

#endif
