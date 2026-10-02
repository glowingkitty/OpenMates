// Optional model assets are installed atomically after per-file checksum validation.
// The store never submits recordings, text, or inference requests to a server.
import Combine
import CryptoKit
import Foundation

enum LocalModelID: String, Codable, CaseIterable, Identifiable, Sendable {
    case whisper, kokoro, privacyFilter
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
    case ready
    case failed(String)
}

enum LocalModelInstallError: Error, Equatable {
    case invalidCatalog, invalidResponse, checksumMismatch, missingFiles, insufficientSpace, notInstalled
}

protocol LocalModelFileDownloading: Sendable {
    func download(_ file: LocalModelFile, to destination: URL,
                  progress: @escaping @Sendable (Int64) -> Void) async throws
}

private final class LocalDownloadProgress: NSObject, URLSessionDownloadDelegate, @unchecked Sendable {
    private let progress: @Sendable (Int64) -> Void
    private let lock = NSLock()
    private var lastUpdate = Date.distantPast
    init(_ progress: @escaping @Sendable (Int64) -> Void) { self.progress = progress }
    func urlSession(_ session: URLSession, downloadTask: URLSessionDownloadTask, didFinishDownloadingTo location: URL) {}
    func urlSession(_ session: URLSession, downloadTask: URLSessionDownloadTask, didWriteData bytesWritten: Int64,
                    totalBytesWritten: Int64, totalBytesExpectedToWrite: Int64) {
        lock.lock()
        let now = Date()
        let emit = now.timeIntervalSince(lastUpdate) >= 0.15 || totalBytesWritten == totalBytesExpectedToWrite
        if emit { lastUpdate = now }
        lock.unlock()
        if emit { progress(totalBytesWritten) }
    }
}

struct LocalModelHTTPDownloader: LocalModelFileDownloading {
    func download(_ file: LocalModelFile, to destination: URL,
                  progress: @escaping @Sendable (Int64) -> Void) async throws {
        let configuration = URLSessionConfiguration.ephemeral
        configuration.timeoutIntervalForRequest = 60
        configuration.timeoutIntervalForResource = 3_600
        configuration.urlCache = nil
        configuration.httpCookieStorage = nil
        let session = URLSession(configuration: configuration)
        defer { session.invalidateAndCancel() }
        let delegate = LocalDownloadProgress(progress)
        let (temporary, response) = try await session.download(for: URLRequest(url: file.url), delegate: delegate)
        defer { try? FileManager.default.removeItem(at: temporary) }
        try Task.checkCancellation()
        guard let response = response as? HTTPURLResponse, response.statusCode == 200 else {
            throw LocalModelInstallError.invalidResponse
        }
        try FileManager.default.moveItem(at: temporary, to: destination)
    }
}

/// Disk work runs away from the main actor and hashes bounded chunks, including the 1.2 GB PII artifact.
enum LocalModelDisk {
    static func verify(_ manifest: LocalModelManifest, at directory: URL, needsReceipt: Bool = true) throws {
        if needsReceipt {
            let data = try Data(contentsOf: directory.appendingPathComponent(".installed.json"))
            guard try JSONDecoder().decode(LocalModelManifest.self, from: data) == manifest else {
                throw LocalModelInstallError.missingFiles
            }
        }
        for file in manifest.files {
            try Task.checkCancellation()
            try verify(file, at: directory.appendingPathComponent(file.path))
        }
    }
    static func verify(_ file: LocalModelFile, at url: URL) throws {
        let values = try url.resourceValues(forKeys: [.fileSizeKey, .isRegularFileKey, .isSymbolicLinkKey])
        guard values.isRegularFile == true, values.isSymbolicLink != true,
              Int64(values.fileSize ?? -1) == file.sizeBytes else { throw LocalModelInstallError.missingFiles }
        let handle = try FileHandle(forReadingFrom: url)
        defer { try? handle.close() }
        var hash = SHA256()
        while let data = try handle.read(upToCount: 1_048_576), !data.isEmpty {
            try Task.checkCancellation()
            hash.update(data: data)
        }
        let actual = hash.finalize().map { String(format: "%02x", $0) }.joined()
        guard actual == file.sha256 else { throw LocalModelInstallError.checksumMismatch }
    }
    static func install(_ manifest: LocalModelManifest, root: URL, downloader: any LocalModelFileDownloading,
                        progress: @escaping @Sendable (Double) -> Void) async throws -> URL {
        let manager = FileManager.default
        try manager.createDirectory(at: root, withIntermediateDirectories: true)
        var root = root
        var resourceValues = URLResourceValues(); resourceValues.isExcludedFromBackup = true
        try root.setResourceValues(resourceValues)
        let available = try root.resourceValues(forKeys: [.volumeAvailableCapacityForImportantUsageKey])
            .volumeAvailableCapacityForImportantUsage
        // Downloads are sequential: leave headroom for the URLSession temporary copy of the largest file.
        let largest = manifest.files.map(\.sizeBytes).max() ?? 0
        if let available, available < manifest.estimatedSizeBytes + largest + 150_000_000 {
            throw LocalModelInstallError.insufficientSpace
        }
        let staging = root.appendingPathComponent("partial-\(manifest.id.rawValue)-\(UUID().uuidString)", isDirectory: true)
        try manager.createDirectory(at: staging, withIntermediateDirectories: true)
        defer { try? manager.removeItem(at: staging) }
        var completed: Int64 = 0
        for file in manifest.files {
            try Task.checkCancellation()
            let destination = staging.appendingPathComponent(file.path)
            try manager.createDirectory(at: destination.deletingLastPathComponent(), withIntermediateDirectories: true)
            let prior = completed
            try await downloader.download(file, to: destination) { bytes in
                progress(min(0.99, Double(prior + min(bytes, file.sizeBytes)) / Double(manifest.estimatedSizeBytes)))
            }
            try verify(file, at: destination)
            completed += file.sizeBytes
            progress(min(0.99, Double(completed) / Double(manifest.estimatedSizeBytes)))
        }
        try Task.checkCancellation()
        try JSONEncoder().encode(manifest).write(to: staging.appendingPathComponent(".installed.json"), options: .atomic)
        let installed = root.appendingPathComponent(manifest.id.rawValue, isDirectory: true)
        // Existing assets remain available until every replacement asset has passed validation.
        if manager.fileExists(atPath: installed.path) { try manager.removeItem(at: installed) }
        try manager.moveItem(at: staging, to: installed)
        progress(1)
        return installed
    }
}

@MainActor
final class LocalModelStore: ObservableObject {
    static let shared = LocalModelStore()
    let models: [LocalModelManifest]
    @Published private(set) var states: [LocalModelID: LocalModelInstallState] = [:]
    @Published private(set) var catalogError: String?
    private let root: URL
    private let downloader: any LocalModelFileDownloading
    private var jobs: [LocalModelID: Task<URL, Error>] = [:]
    private var generations: [LocalModelID: UUID] = [:]

    init(catalog: Data? = nil, root: URL? = nil, downloader: any LocalModelFileDownloading = LocalModelHTTPDownloader(),
         verifyExisting: Bool = true) {
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
        if verifyExisting { Task { await restoreExisting() } }
    }
    func state(for id: LocalModelID) -> LocalModelInstallState { states[id] ?? .notDownloaded }
    func manifest(for id: LocalModelID) -> LocalModelManifest? { models.first { $0.id == id } }
    func installedDirectory(_ id: LocalModelID) throws -> URL {
        guard state(for: id) == .ready else { throw LocalModelInstallError.notInstalled }
        return root.appendingPathComponent(id.rawValue, isDirectory: true)
    }
    func download(_ id: LocalModelID) async {
        guard jobs[id] == nil, state(for: id) != .ready, let manifest = manifest(for: id) else { return }
        let generation = UUID(); generations[id] = generation
        states[id] = .downloading(0)
        let root = root, downloader = downloader
        // An immutable MainActor reference is Sendable; a nested capture of an
        // outer weak variable would race under Swift 6. Progress tasks stay weak
        // and generation-fenced after the operation finishes or is removed.
        let progressStore = self
        let job = Task.detached(priority: .utility) {
            try await LocalModelDisk.install(manifest, root: root, downloader: downloader) { fraction in
                Task { @MainActor [weak progressStore] in
                    guard let store = progressStore, store.generations[id] == generation else { return }
                    if case .downloading(let previous) = store.state(for: id) {
                        store.states[id] = .downloading(max(previous, fraction))
                    }
                }
            }
        }
        jobs[id] = job
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
        if generations[id] == generation { jobs[id] = nil }
    }
    func cancel(_ id: LocalModelID) { jobs[id]?.cancel() }
    func remove(_ id: LocalModelID) async {
        let running = jobs[id]
        running?.cancel()
        generations[id] = UUID()
        if let running { _ = try? await running.value }
        jobs[id] = nil
        do {
            let directory = root.appendingPathComponent(id.rawValue, isDirectory: true)
            if FileManager.default.fileExists(atPath: directory.path) { try FileManager.default.removeItem(at: directory) }
            states[id] = .notDownloaded
        } catch { states[id] = .failed(AppStrings.localLabDownloadFailed) }
    }
    func restoreExisting() async {
        // Only this app's interrupted staging directories are discarded; installed revisions remain intact.
        if let entries = try? FileManager.default.contentsOfDirectory(at: root, includingPropertiesForKeys: nil) {
            for entry in entries where entry.lastPathComponent.hasPrefix("partial-") {
                // Restoration runs at initialization, before this store can start a download.
                if jobs.isEmpty { try? FileManager.default.removeItem(at: entry) }
            }
        }
        for manifest in models {
            let id = manifest.id
            let directory = root.appendingPathComponent(id.rawValue, isDirectory: true)
            guard FileManager.default.fileExists(atPath: directory.path), jobs[id] == nil else { continue }
            let generation = UUID(); generations[id] = generation
            states[id] = .downloading(1)
            let job = Task.detached(priority: .utility) {
                try LocalModelDisk.verify(manifest, at: directory)
                return directory
            }
            jobs[id] = job
            do {
                _ = try await job.value
                if generations[id] == generation { states[id] = .ready }
            } catch {
                if generations[id] == generation { states[id] = .failed(AppStrings.localLabDownloadFailed) }
            }
            if generations[id] == generation { jobs[id] = nil }
        }
    }
}
