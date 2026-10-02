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
        return LocalModelManifest(id: .kokoro, revision: "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa", estimatedSizeBytes: Int64(fixture.count), files: [
            LocalModelFile(path: path, url: URL(string: "https://huggingface.co/fixture/resolve/aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa/model.bin")!,
                           sha256: hash ?? digest, sizeBytes: Int64(fixture.count))
        ])
    }
    private func catalog(_ manifest: LocalModelManifest) throws -> Data {
        try JSONEncoder().encode(LocalModelCatalog(models: [manifest]))
    }

    // LML-001: integrity failure never exposes partially downloaded weights to inference.
    // contract-test: direct surface=gui.apple assertions=apple-local-model-lab.optional-downloads
    func testDownloadVerifiesThenRestoresAndRemovalDeletesAssets() async throws {
        let root = root(), manifest = manifest()
        defer { try? FileManager.default.removeItem(at: root) }
        let transport = FixtureDownloader(bytes: fixture)
        let store = LocalModelStore(catalog: try catalog(manifest), root: root, downloader: transport, verifyExisting: false)
        XCTAssertEqual(store.state(for: .kokoro), .notDownloaded)
        XCTAssertThrowsError(try store.installedDirectory(.kokoro))
        await store.download(.kokoro)
        XCTAssertEqual(store.state(for: .kokoro), .ready)
        XCTAssertEqual(try Data(contentsOf: store.installedDirectory(.kokoro).appendingPathComponent("model.bin")), fixture)
        let requests = await transport.requestCount
        XCTAssertEqual(requests, 1)

        let reopened = LocalModelStore(catalog: try catalog(manifest), root: root, downloader: transport, verifyExisting: false)
        await reopened.restoreExisting()
        XCTAssertEqual(reopened.state(for: .kokoro), .ready)
        let afterReopen = await transport.requestCount
        XCTAssertEqual(afterReopen, 1, "Restoring an install is disk-only")
        await reopened.remove(.kokoro)
        XCTAssertEqual(reopened.state(for: .kokoro), .notDownloaded)
        XCTAssertFalse(FileManager.default.fileExists(atPath: root.appendingPathComponent("kokoro").path))
    }

    // LML-001: a truncated download or bit corruption is never marked ready.
    // contract-test: direct surface=gui.apple assertions=apple-local-model-lab.optional-downloads
    func testBadChecksumIsRejectedAndPartialDirectoryRemoved() async throws {
        let root = root()
        defer { try? FileManager.default.removeItem(at: root) }
        let store = LocalModelStore(catalog: try catalog(manifest(hash: String(repeating: "0", count: 64))),
                                   root: root, downloader: FixtureDownloader(bytes: fixture), verifyExisting: false)
        await store.download(.kokoro)
        guard case .failed = store.state(for: .kokoro) else { return XCTFail("Corruption must be visible") }
        XCTAssertThrowsError(try store.installedDirectory(.kokoro))
        XCTAssertEqual(try FileManager.default.contentsOfDirectory(atPath: root.path), [])
    }

    // LML-001: cached installs are checked again before the test runtime can load them.
    // contract-test: direct surface=gui.apple assertions=apple-local-model-lab.optional-downloads
    func testSameSizeCorruptionOnDiskIsRejectedOnReopen() async throws {
        let root = root(), manifest = manifest()
        defer { try? FileManager.default.removeItem(at: root) }
        let transport = FixtureDownloader(bytes: fixture)
        let store = LocalModelStore(catalog: try catalog(manifest), root: root, downloader: transport, verifyExisting: false)
        await store.download(.kokoro)
        let file = try store.installedDirectory(.kokoro).appendingPathComponent("model.bin")
        try Data(repeating: 0, count: fixture.count).write(to: file)
        let reopened = LocalModelStore(catalog: try catalog(manifest), root: root, downloader: transport, verifyExisting: false)
        await reopened.restoreExisting()
        guard case .failed = reopened.state(for: .kokoro) else { return XCTFail("Same-size corruption must fail verification") }
        XCTAssertThrowsError(try reopened.installedDirectory(.kokoro))
    }

    // LML-004: cancelling releases transport and discards only the in-progress installation.
    // contract-test: direct surface=gui.apple assertions=apple-local-model-lab.optional-downloads
    func testCancellationRemovesPartialAssetsAndLeavesRetryAvailable() async throws {
        let root = root()
        defer { try? FileManager.default.removeItem(at: root) }
        let signal = AsyncStream<Void>.makeStream()
        let downloader = WaitingDownloader(started: signal.continuation)
        let store = LocalModelStore(catalog: try catalog(manifest()), root: root, downloader: downloader, verifyExisting: false)
        let task = Task { await store.download(.kokoro) }
        var iterator = signal.stream.makeAsyncIterator()
        _ = await iterator.next()
        store.cancel(.kokoro)
        await task.value
        XCTAssertEqual(store.state(for: .kokoro), .notDownloaded)
        XCTAssertEqual(try FileManager.default.contentsOfDirectory(atPath: root.path), [])
    }

    // LML-001: a manifest cannot escape the app's model cache or pull mutable remote assets.
    // contract-test: direct surface=gui.apple assertions=apple-local-model-lab.optional-downloads
    func testCatalogRejectsTraversalDuplicatesAndUnpinnedURLs() throws {
        XCTAssertThrowsError(try LocalModelCatalog(models: [manifest(path: "../outside.bin")]).validated())
        XCTAssertThrowsError(try LocalModelCatalog(models: [manifest(), manifest()]).validated())
        let original = manifest()
        let file = LocalModelFile(path: "model.bin", url: URL(string: "https://huggingface.co/fixture/resolve/main/model.bin")!,
                                  sha256: original.files[0].sha256, sizeBytes: Int64(fixture.count))
        let mutable = LocalModelManifest(id: .kokoro, revision: "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa", estimatedSizeBytes: Int64(fixture.count), files: [file])
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
