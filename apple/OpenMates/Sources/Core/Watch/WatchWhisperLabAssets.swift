// Foreground-only optional Watch tiny assets; no production speech routing.
// Specification: specifications/features/apple-local-model-lab/specification.yml
// Assertions: apple-local-model-lab.watch-tiny, apple-local-model-lab.ephemeral-state
import Combine
import CryptoKit
import Foundation

struct WatchWhisperAsset: Codable, Equatable, Sendable {
    let path: String
    let url: URL
    let sha256: String
    let sizeBytes: Int64
}

struct WatchWhisperManifest: Codable, Equatable, Sendable {
    let model: String
    let revision: String
    let tokenizerRevision: String
    let estimatedSizeBytes: Int64
    let files: [WatchWhisperAsset]

    func validate() throws {
        func revisionIsValid(_ value: String) -> Bool {
            value.count == 40 && value.allSatisfy { $0.isHexDigit && !$0.isUppercase }
        }
        guard model == "openai_whisper-tiny", revisionIsValid(revision), revisionIsValid(tokenizerRevision),
              !files.isEmpty, Set(files.map(\.path)).count == files.count,
              estimatedSizeBytes > 0, files.reduce(0, { $0 + $1.sizeBytes }) == estimatedSizeBytes else {
            throw WatchWhisperLabError.assets
        }
        for file in files {
            let parts = file.path.split(separator: "/", omittingEmptySubsequences: false)
            let tokenizer = file.path.hasPrefix("tokenizer/")
            let repo = tokenizer ? "openai/whisper-tiny" : "argmaxinc/whisperkit-coreml"
            let pin = tokenizer ? tokenizerRevision : revision
            let remotePath = tokenizer ? String(file.path.dropFirst("tokenizer/".count)) : "\(model)/\(file.path)"
            guard !parts.isEmpty, parts.allSatisfy({ !$0.isEmpty && $0 != "." && $0 != ".." && !$0.contains("\\") }),
                  file.path != ".installed.json", !file.path.hasPrefix("/"), file.sizeBytes > 0,
                  file.sha256.count == 64, file.sha256.allSatisfy({ $0.isHexDigit && !$0.isUppercase }),
                  file.url.absoluteString == "https://huggingface.co/\(repo)/resolve/\(pin)/\(remotePath)" else {
                throw WatchWhisperLabError.assets
            }
        }
    }
    static func bundled() throws -> Self {
        guard let url = Bundle.main.url(forResource: "watch-whisper-tiny", withExtension: "json") else {
            throw WatchWhisperLabError.assets
        }
        let manifest = try JSONDecoder().decode(Self.self, from: Data(contentsOf: url))
        try manifest.validate()
        return manifest
    }
}

enum WatchWhisperLabError: Error, Sendable { case assets, transfer, audio, microphone, inference }
enum WatchWhisperInstallState: Equatable, Sendable { case absent, transfer(Double), verifying(Double), ready, failed }

typealias WatchWhisperTransfer = @Sendable (WatchWhisperAsset, URL, @escaping @Sendable (Int64) -> Void) async throws -> Void

private final class WatchWhisperTransferProgress: NSObject, URLSessionDownloadDelegate, @unchecked Sendable {
    let update: @Sendable (Int64) -> Void
    init(update: @escaping @Sendable (Int64) -> Void) { self.update = update }
    func urlSession(_ session: URLSession, downloadTask: URLSessionDownloadTask, didFinishDownloadingTo location: URL) {}
    func urlSession(_ session: URLSession, downloadTask: URLSessionDownloadTask, didWriteData bytesWritten: Int64,
                    totalBytesWritten: Int64, totalBytesExpectedToWrite: Int64) { update(totalBytesWritten) }
}

/// Disk implementation mirrors LocalModelDisk's bounded hashing and atomic install.
/// Separate catalog/root prevents accidentally selecting the iOS large-v3 bundle.
enum WatchWhisperDisk {
    static func transfer(_ file: WatchWhisperAsset, to destination: URL,
                         progress: @escaping @Sendable (Int64) -> Void) async throws {
        let configuration = URLSessionConfiguration.ephemeral
        configuration.urlCache = nil; configuration.httpCookieStorage = nil
        configuration.httpShouldSetCookies = false
        configuration.timeoutIntervalForRequest = 60; configuration.timeoutIntervalForResource = 1800
        let session = URLSession(configuration: configuration)
        defer { session.invalidateAndCancel() }
        let delegate = WatchWhisperTransferProgress(update: progress)
        let (temporary, response) = try await session.download(for: URLRequest(url: file.url), delegate: delegate)
        defer { try? FileManager.default.removeItem(at: temporary) }
        try Task.checkCancellation()
        guard let http = response as? HTTPURLResponse, http.statusCode == 200 else { throw WatchWhisperLabError.transfer }
        try FileManager.default.moveItem(at: temporary, to: destination)
    }
    static func verify(_ asset: WatchWhisperAsset, directory: URL) throws {
        let url = directory.appendingPathComponent(asset.path)
        let values = try url.resourceValues(forKeys: [.fileSizeKey, .isRegularFileKey, .isSymbolicLinkKey])
        guard values.isRegularFile == true, values.isSymbolicLink != true,
              Int64(values.fileSize ?? -1) == asset.sizeBytes else { throw WatchWhisperLabError.assets }
        let handle = try FileHandle(forReadingFrom: url)
        defer { try? handle.close() }
        var hash = SHA256()
        while let data = try handle.read(upToCount: 262_144), !data.isEmpty {
            try Task.checkCancellation(); hash.update(data: data)
        }
        guard hash.finalize().map({ String(format: "%02x", $0) }).joined() == asset.sha256 else {
            throw WatchWhisperLabError.assets
        }
    }
    static func verifyInstalled(_ manifest: WatchWhisperManifest, directory: URL) throws {
        let receipt = try JSONDecoder().decode(WatchWhisperManifest.self,
            from: Data(contentsOf: directory.appendingPathComponent(".installed.json")))
        guard receipt == manifest else { throw WatchWhisperLabError.assets }
        for file in manifest.files { try verify(file, directory: directory) }
    }
    static func install(_ manifest: WatchWhisperManifest, root: URL, transfer: WatchWhisperTransfer,
                        progress: @escaping @Sendable (WatchWhisperInstallState) -> Void) async throws {
        try manifest.validate()
        let manager = FileManager.default
        try manager.createDirectory(at: root, withIntermediateDirectories: true)
        var excludedRoot = root
        var values = URLResourceValues(); values.isExcludedFromBackup = true; try excludedRoot.setResourceValues(values)
        // watchOS omits URLResourceValues.volumeAvailableCapacityForImportantUsage.
        // The filesystem's numeric free-size attribute is available on Watch.
        let attributes = try manager.attributesOfFileSystem(forPath: root.path)
        let free = (attributes[.systemFreeSize] as? NSNumber)?.int64Value
        if let free, free < manifest.estimatedSizeBytes * 2 + 50_000_000 { throw WatchWhisperLabError.assets }
        let staging = root.appendingPathComponent("partial-" + UUID().uuidString, isDirectory: true)
        try manager.createDirectory(at: staging, withIntermediateDirectories: true)
        defer { try? manager.removeItem(at: staging) }
        var completed: Int64 = 0
        for file in manifest.files {
            try Task.checkCancellation()
            let destination = staging.appendingPathComponent(file.path)
            try manager.createDirectory(at: destination.deletingLastPathComponent(), withIntermediateDirectories: true)
            let prior = completed
            try await transfer(file, destination) { bytes in
                progress(.transfer(Double(prior + min(file.sizeBytes, max(0, bytes))) / Double(manifest.estimatedSizeBytes)))
            }
            completed += file.sizeBytes
        }
        for (index, file) in manifest.files.enumerated() {
            progress(.verifying(Double(index) / Double(manifest.files.count)))
            try verify(file, directory: staging)
        }
        try Task.checkCancellation()
        try JSONEncoder().encode(manifest).write(to: staging.appendingPathComponent(".installed.json"), options: .atomic)
        let installed = root.appendingPathComponent("tiny", isDirectory: true)
        if manager.fileExists(atPath: installed.path) { try manager.removeItem(at: installed) }
        try manager.moveItem(at: staging, to: installed)
    }
}

@MainActor
final class WatchWhisperAssetStore: ObservableObject {
    @Published private(set) var state: WatchWhisperInstallState = .absent
    let manifest: WatchWhisperManifest?
    let root: URL
    private let transfer: WatchWhisperTransfer
    private let beforeVerification: @Sendable () async throws -> Void
    private var job: Task<Void, Never>?
    private var generation = UUID()
    var active: Bool { job != nil }
    init(manifest: WatchWhisperManifest? = try? .bundled(), root: URL? = nil,
         beforeVerification: @escaping @Sendable () async throws -> Void = {},
         transfer: @escaping WatchWhisperTransfer = { try await WatchWhisperDisk.transfer($0, to: $1, progress: $2) }) {
        self.manifest = manifest
        self.root = root ?? FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask)[0]
            .appendingPathComponent("WatchWhisperLab", isDirectory: true)
        self.transfer = transfer
        self.beforeVerification = beforeVerification
        if manifest == nil { state = .failed }
    }
    var installedDirectory: URL? { state == .ready ? root.appendingPathComponent("tiny", isDirectory: true) : nil }
    func restore() async {
        guard !active, let manifest else { return }
        let directory = root.appendingPathComponent("tiny", isDirectory: true)
        guard FileManager.default.fileExists(atPath: directory.path) else { return }
        let token = UUID(); generation = token; state = .verifying(0)
        let beforeVerification = beforeVerification
        let task = Task.detached {
            try await beforeVerification()
            try WatchWhisperDisk.verifyInstalled(manifest, directory: directory)
        }
        cancelTransfer = { task.cancel() }
        job = Task {
            do { try await task.value; if generation == token { state = task.isCancelled ? .absent : .ready } }
            catch { if generation == token { state = task.isCancelled ? .absent : .failed } }
            if generation == token { job = nil; cancelTransfer = nil }
        }
        await job?.value
    }
    func download(enabled: Bool) {
        guard enabled, !active, state != .ready, let manifest else { return }
        let token = UUID(); generation = token; state = .transfer(0)
        let root = root, transfer = transfer, store = self
        let work = Task.detached {
            try await WatchWhisperDisk.install(manifest, root: root, transfer: transfer) { next in
                Task { @MainActor [weak store] in store?.accept(next, token: token) }
            }
        }
        job = Task {
            do { try await work.value; if generation == token { state = work.isCancelled ? .absent : .ready } }
            catch { if generation == token { state = work.isCancelled ? .absent : .failed } }
            if generation == token { job = nil; cancelTransfer = nil }
        }
        cancelTransfer = { work.cancel() }
    }
    private var cancelTransfer: (() -> Void)?
    func cancel() { cancelTransfer?() }
    func waitUntilIdle() async { await job?.value }
    func remove() async {
        guard !active else { return }
        generation = UUID()
        do {
            let directory = root.appendingPathComponent("tiny")
            if FileManager.default.fileExists(atPath: directory.path) { try FileManager.default.removeItem(at: directory) }
            state = .absent
        } catch { state = .failed }
    }
    private func accept(_ next: WatchWhisperInstallState, token: UUID) {
        guard generation == token, active else { return }
        switch (state, next) {
        case (.transfer(let old), .transfer(let new)) where new >= old: state = next
        case (.transfer, .verifying): state = next
        case (.verifying(let old), .verifying(let new)) where new >= old: state = next
        default: break
        }
    }
}
