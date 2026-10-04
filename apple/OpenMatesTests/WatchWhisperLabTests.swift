import AVFoundation
import CryptoKit
import XCTest
@testable import OpenMates

final class WatchWhisperLabTests: XCTestCase {
    private func root() throws -> URL {
        let directory = FileManager.default.temporaryDirectory.appendingPathComponent("watch-lab-tests-" + UUID().uuidString)
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
        addTeardownBlock { try? FileManager.default.removeItem(at: directory) }
        return directory
    }
    private func manifest(bytes: Data, revision: String = String(repeating: "a", count: 40),
                          digest: String? = nil, path: String = "fixture.bin") -> WatchWhisperManifest {
        let file = WatchWhisperAsset(path: path,
            url: URL(string: "https://huggingface.co/argmaxinc/whisperkit-coreml/resolve/\(revision)/openai_whisper-tiny/\(path)")!,
            sha256: digest ?? SHA256.hash(data: bytes).map { String(format: "%02x", $0) }.joined(),
            sizeBytes: Int64(bytes.count))
        return .init(model: "openai_whisper-tiny", revision: revision, tokenizerRevision: revision,
                     estimatedSizeBytes: Int64(bytes.count), files: [file])
    }
    private func audio(in directory: URL) throws -> URL {
        let url = directory.appendingPathComponent("original.wav")
        let format = AVAudioFormat(standardFormatWithSampleRate: 16_000, channels: 1)!
        let file = try AVAudioFile(forWriting: url, settings: format.settings)
        let buffer = AVAudioPCMBuffer(pcmFormat: format, frameCapacity: 16_000)!
        buffer.frameLength = 16_000
        if let channel = buffer.floatChannelData { for index in 0..<16_000 { channel[0][index] = 0 } }
        try file.write(from: buffer)
        return url
    }
    @MainActor private func installedStore(root: URL) async -> WatchWhisperAssetStore {
        let bytes = Data("tiny-unit-assets".utf8)
        let store = WatchWhisperAssetStore(manifest: manifest(bytes: bytes), root: root, transfer: { _, destination, progress in
            try bytes.write(to: destination); progress(Int64(bytes.count))
        })
        store.download(enabled: true); await store.waitUntilIdle()
        XCTAssertEqual(store.state, .ready)
        return store
    }

    // contract-test: supporting surface=gui.apple assertions=apple-local-model-lab.watch-tiny
    func testBundledManifestPinsMultilingualTinyAndLocalTokenizer() throws {
        let pinned = try WatchWhisperManifest.bundled()
        XCTAssertEqual(pinned.model, "openai_whisper-tiny")
        XCTAssertEqual(pinned.revision, "0f63a7800b00dd0226abd051b906c246e1907482")
        XCTAssertEqual(pinned.tokenizerRevision, "169d4a4341b33bc18d8881c4b69c2e104e1cc0af")
        XCTAssertEqual(pinned.estimatedSizeBytes, 79_398_546)
        XCTAssertEqual(pinned.files.count, 21)
        for path in ["AudioEncoder.mlmodelc/model.mil", "MelSpectrogram.mlmodelc/model.mil",
                     "TextDecoder.mlmodelc/model.mil", "tokenizer/tokenizer.json", "tokenizer/tokenizer_config.json"] {
            XCTAssertTrue(pinned.files.contains(where: { $0.path == path }))
        }
        XCTAssertTrue(pinned.files.allSatisfy { !$0.url.absoluteString.contains("/main/") && !$0.url.absoluteString.contains("large-v3") })
    }

    // contract-test: supporting surface=gui.apple assertions=apple-local-model-lab.watch-tiny
    func testCatalogRejectsMutableRevisionTraversalAndWrongModel() throws {
        let bytes = Data([1, 2, 3])
        XCTAssertThrowsError(try manifest(bytes: bytes, revision: "main").validate())
        XCTAssertThrowsError(try manifest(bytes: bytes, path: "../outside.bin").validate())
        let valid = manifest(bytes: bytes)
        let wrong = WatchWhisperManifest(model: "openai_whisper-large-v3", revision: valid.revision,
            tokenizerRevision: valid.tokenizerRevision, estimatedSizeBytes: valid.estimatedSizeBytes, files: valid.files)
        XCTAssertThrowsError(try wrong.validate())
        XCTAssertNoThrow(try valid.validate())
    }

    @MainActor
    // contract-test: direct surface=gui.apple assertions=apple-local-model-lab.watch-tiny
    func testInterruptedDownloadNeverBecomesReadyAndExplicitRetryInstalls() async throws {
        let bytes = Data("tiny assets".utf8), root = try root(), transfer = WatchWhisperTestTransfer(bytes: Data("tiny assets".utf8))
        let store = WatchWhisperAssetStore(manifest: manifest(bytes: bytes), root: root, transfer: {
            try await transfer.download($0, to: $1, progress: $2)
        })
        store.download(enabled: false)
        XCTAssertEqual(store.state, .absent)
        store.download(enabled: true); await store.waitUntilIdle()
        XCTAssertEqual(store.state, .failed)
        XCTAssertNil(store.installedDirectory)
        XCTAssertEqual(try FileManager.default.contentsOfDirectory(atPath: root.path), [])
        store.download(enabled: true); await store.waitUntilIdle()
        XCTAssertEqual(store.state, .ready)
        let attempts = await transfer.attempts
        XCTAssertEqual(attempts, 2)
    }

    @MainActor
    // contract-test: direct surface=gui.apple assertions=apple-local-model-lab.watch-tiny
    func testBadHashAndChangedVersionCannotRestoreReady() async throws {
        let bytes = Data("tiny assets".utf8), root = try root()
        let corrupt = WatchWhisperAssetStore(manifest: manifest(bytes: bytes, digest: String(repeating: "0", count: 64)), root: root, transfer: {
            _, destination, _ in try bytes.write(to: destination)
        })
        corrupt.download(enabled: true); await corrupt.waitUntilIdle()
        XCTAssertEqual(corrupt.state, .failed)
        let installed = await installedStore(root: root)
        XCTAssertNotNil(installed.installedDirectory)
        let changed = WatchWhisperAssetStore(manifest: manifest(bytes: Data("tiny-unit-assets".utf8), revision: String(repeating: "b", count: 40)), root: root)
        await changed.restore()
        XCTAssertEqual(changed.state, .failed)
        XCTAssertNil(changed.installedDirectory)
    }

    @MainActor
    // contract-test: direct surface=gui.apple assertions=apple-local-model-lab.watch-tiny
    func testCancellationDrainsDownloadAndDropsQueuedProgressBeforeRemoval() async throws {
        let bytes = Data("cancel assets".utf8), root = try root(), gate = WatchWhisperTransferGate()
        let store = WatchWhisperAssetStore(manifest: manifest(bytes: bytes), root: root, transfer: { _, destination, progress in
            await gate.started(progress)
            try await Task.sleep(for: .seconds(60))
            try bytes.write(to: destination)
        })
        store.download(enabled: true); await gate.waitStarted()
        store.cancel(); await store.waitUntilIdle()
        XCTAssertEqual(store.state, .absent)
        await gate.lateProgress()
        await Task.yield()
        XCTAssertEqual(store.state, .absent)
        XCTAssertEqual(try FileManager.default.contentsOfDirectory(atPath: root.path), [])
        await store.remove()
        XCTAssertEqual(store.state, .absent)
    }

    @MainActor
    // contract-test: direct surface=gui.apple assertions=apple-local-model-lab.watch-tiny
    func testRestoreVerificationCancelDrainsAndCannotPublishReady() async throws {
        let root = try root(), installed = await installedStore(root: root), gate = WatchWhisperTransferGate()
        let reopened = WatchWhisperAssetStore(manifest: installed.manifest, root: root, beforeVerification: {
            await gate.started { _ in }
            try await Task.sleep(for: .seconds(60))
        })
        let verification = Task { await reopened.restore() }
        await gate.waitStarted()
        XCTAssertEqual(reopened.state, .verifying(0)); XCTAssertTrue(reopened.active)
        reopened.cancel()
        XCTAssertTrue(reopened.active)
        await verification.value
        XCTAssertFalse(reopened.active); XCTAssertEqual(reopened.state, .absent)
        XCTAssertNil(reopened.installedDirectory)
        // Cancelled verification does not delete installed model assets.
        XCTAssertTrue(FileManager.default.fileExists(atPath: root.appendingPathComponent("tiny/.installed.json").path))
    }

    @MainActor
    // contract-test: direct surface=gui.apple assertions=apple-local-model-lab.watch-tiny,apple-local-model-lab.ephemeral-state
    func testDisableCancelsHeldTransferAndClearsPrivateInputBeforeLateCallback() async throws {
        let bytes = Data("held transfer assets".utf8), root = try root(), gate = WatchWhisperTransferGate()
        let store = WatchWhisperAssetStore(manifest: manifest(bytes: bytes), root: root.appendingPathComponent("assets"), transfer: {
            _, destination, progress in
            await gate.started(progress)
            try await Task.sleep(for: .seconds(60))
            try bytes.write(to: destination)
        })
        let controller = WatchWhisperLabController(store: store, temporaryRoot: root, runtimeFactory: { WatchWhisperPositiveRuntime() })
        let original = try audio(in: root)
        controller.enabled = true; controller.importAudio(original)
        let copy = try XCTUnwrap(controller.audioInput)
        store.download(enabled: true); await gate.waitStarted()
        controller.disable()
        XCTAssertFalse(controller.enabled); XCTAssertNil(controller.audioInput); XCTAssertNil(controller.transcript)
        XCTAssertFalse(FileManager.default.fileExists(atPath: copy.path))
        await store.waitUntilIdle()
        XCTAssertEqual(store.state, .absent); XCTAssertFalse(store.active)
        await gate.lateProgress(); await Task.yield()
        XCTAssertEqual(store.state, .absent); XCTAssertNil(store.installedDirectory)
        XCTAssertEqual(try FileManager.default.contentsOfDirectory(atPath: store.root.path), [])
        XCTAssertTrue(FileManager.default.fileExists(atPath: original.path))
    }

    @MainActor
    // contract-test: direct surface=gui.apple assertions=apple-local-model-lab.watch-tiny,apple-local-model-lab.ephemeral-state
    func testVerifiedReopenAndPositiveRuntimeResultUseOnlyLocalAssets() async throws {
        let root = try root(), store = await installedStore(root: root.appendingPathComponent("assets"))
        let reopened = WatchWhisperAssetStore(manifest: store.manifest, root: store.root, transfer: { _, _, _ in
            XCTFail("Reopening verified assets must not fetch the network")
            throw WatchWhisperLabError.transfer
        })
        await reopened.restore()
        XCTAssertEqual(reopened.state, .ready)
        let original = try audio(in: root)
        let controller = WatchWhisperLabController(store: reopened, temporaryRoot: root,
            memory: { 12_345_678 }, runtimeFactory: { WatchWhisperPositiveRuntime() })
        controller.enabled = true; controller.importAudio(original)
        let copy = try XCTUnwrap(controller.audioInput)
        XCTAssertNotEqual(copy, original)
        controller.run(); await controller.waitUntilIdle()
        XCTAssertEqual(controller.transcript, "English und Deutsch test fixture")
        XCTAssertEqual(controller.timings.map(\.phase), [.loading, .transcribing, .unloading])
        XCTAssertEqual(controller.sampledPeakBytes, 12_345_678)
        XCTAssertNotNil(controller.elapsed)
        controller.leave()
        XCTAssertNil(controller.transcript); XCTAssertNil(controller.audioInput)
        XCTAssertFalse(FileManager.default.fileExists(atPath: copy.path))
        XCTAssertTrue(FileManager.default.fileExists(atPath: original.path))
        XCTAssertEqual(reopened.state, .ready)
        await reopened.remove(); XCTAssertEqual(reopened.state, .absent)
    }

    @MainActor
    // contract-test: direct surface=gui.apple assertions=apple-local-model-lab.serialized-cancellation,apple-local-model-lab.ephemeral-state,apple-local-model-lab.watch-tiny
    func testExitSuppressesLateNativeResultAndKeepsBusyUntilUnloadFinishes() async throws {
        let root = try root(), store = await installedStore(root: root.appendingPathComponent("assets"))
        let gate = WatchWhisperRuntimeGate()
        let controller = WatchWhisperLabController(store: store, temporaryRoot: root, runtimeFactory: { gate })
        let original = try audio(in: root)
        controller.enabled = true; controller.importAudio(original)
        let copy = try XCTUnwrap(controller.audioInput)
        controller.run(); await gate.waitStarted()
        controller.leave()
        XCTAssertNil(controller.audioInput); XCTAssertNil(controller.transcript)
        XCTAssertTrue(controller.running); XCTAssertTrue(controller.cancelling)
        XCTAssertTrue(FileManager.default.fileExists(atPath: copy.path))
        controller.enabled = true; controller.run()
        await gate.releaseNative(); await gate.waitUnloading()
        XCTAssertTrue(controller.running); XCTAssertTrue(controller.cancelling)
        await gate.releaseUnload(); await controller.waitUntilIdle()
        XCTAssertFalse(controller.running); XCTAssertFalse(controller.cancelling)
        XCTAssertNil(controller.transcript); XCTAssertNil(controller.phase)
        XCTAssertFalse(FileManager.default.fileExists(atPath: copy.path))
        XCTAssertTrue(FileManager.default.fileExists(atPath: original.path))
        let runs = await gate.runs; XCTAssertEqual(runs, 1)
    }
}

private actor WatchWhisperTestTransfer {
    let bytes: Data
    var attempts = 0
    init(bytes: Data) { self.bytes = bytes }
    func download(_ file: WatchWhisperAsset, to destination: URL, progress: @Sendable (Int64) -> Void) throws {
        attempts += 1
        if attempts == 1 { progress(file.sizeBytes / 2); throw URLError(.networkConnectionLost) }
        try bytes.write(to: destination); progress(file.sizeBytes)
    }
}
private actor WatchWhisperTransferGate {
    private var progress: (@Sendable (Int64) -> Void)?
    private var waiter: CheckedContinuation<Void, Never>?
    func started(_ callback: @escaping @Sendable (Int64) -> Void) {
        progress = callback; waiter?.resume(); waiter = nil
    }
    func waitStarted() async { if progress == nil { await withCheckedContinuation { waiter = $0 } } }
    func lateProgress() { progress?(Int64.max) }
}
private actor WatchWhisperPositiveRuntime: WatchWhisperRuntime {
    func transcribe(_ audio: URL, directory: URL, phase: @Sendable (WatchWhisperRunPhase) async -> Void) async throws -> WatchWhisperResult {
        guard FileManager.default.fileExists(atPath: directory.appendingPathComponent(".installed.json").path) else { throw WatchWhisperLabError.assets }
        await phase(.loading); await phase(.transcribing)
        return .init(text: "English und Deutsch test fixture", audioSeconds: 1)
    }
    func unload() async {}
}
private actor WatchWhisperRuntimeGate: WatchWhisperRuntime {
    private var native: CheckedContinuation<Void, Never>?
    private var unloadWait: CheckedContinuation<Void, Never>?
    private var startedWait: CheckedContinuation<Void, Never>?
    private var unloadingWait: CheckedContinuation<Void, Never>?
    private var started = false
    private var unloading = false
    var runs = 0
    func transcribe(_ audio: URL, directory: URL, phase: @Sendable (WatchWhisperRunPhase) async -> Void) async throws -> WatchWhisperResult {
        runs += 1; await phase(.loading); await phase(.transcribing)
        await withCheckedContinuation { native = $0; started = true; startedWait?.resume(); startedWait = nil }
        return .init(text: "Must be discarded", audioSeconds: 1)
    }
    func waitStarted() async { if !started { await withCheckedContinuation { startedWait = $0 } } }
    func releaseNative() { native?.resume(); native = nil }
    func unload() async {
        await withCheckedContinuation { unloadWait = $0; unloading = true; unloadingWait?.resume(); unloadingWait = nil }
    }
    func waitUnloading() async { if !unloading { await withCheckedContinuation { unloadingWait = $0 } } }
    func releaseUnload() { unloadWait?.resume(); unloadWait = nil }
}
