import AVFoundation
import CryptoKit
import XCTest
@testable import OpenMates

// Experimental contract: docs/specifications/apple/local-model-lab.md (LML-003/004/005).
// Inference is injected; these fixtures do not fetch weights or call any provider.
@MainActor
final class LocalModelLabControllerTests: XCTestCase {
    // LML-004: a second request cannot load while the first model owns the runtime.
    // contract-test: direct surface=gui.apple assertions=apple-local-model-lab.serialized-cancellation
    func testOnlyOneRunCanOwnRuntime() async throws {
        let fixture = try await fixture()
        defer { fixture.cleanup() }
        fixture.controller.privacyText = "Disposable test person"
        fixture.controller.speechText = "Disposable speech"
        fixture.controller.run(.privacyFilter, enabled: true)
        var started = fixture.runStarted.makeAsyncIterator()
        _ = await started.next()
        fixture.controller.run(.kokoro, enabled: true)
        XCTAssertEqual(fixture.controller.runningModel, .privacyFilter)
        let runs = await fixture.runtime.runCount
        XCTAssertEqual(runs, 1)
        await fixture.finish()
        XCTAssertEqual(fixture.controller.resultModel, .privacyFilter)
        XCTAssertFalse(fixture.controller.busy)
    }

    // LML-004: cancellation remains busy until the native operation AND unload finish.
    // contract-test: direct surface=gui.apple assertions=apple-local-model-lab.serialized-cancellation
    func testCancellationWaitsForRuntimeAndUnload() async throws {
        let fixture = try await fixture()
        defer { fixture.cleanup() }
        fixture.controller.privacyText = "Disposable test person"
        fixture.controller.run(.privacyFilter, enabled: true)
        var started = fixture.runStarted.makeAsyncIterator()
        _ = await started.next()
        fixture.controller.cancel()
        XCTAssertTrue(fixture.controller.busy)
        XCTAssertTrue(fixture.controller.cancelling)
        await fixture.runtime.finishRun()
        var unloading = fixture.unloadStarted.makeAsyncIterator()
        _ = await unloading.next()
        XCTAssertTrue(fixture.controller.busy, "Native unloading still owns the run")
        XCTAssertTrue(fixture.controller.cancelling)
        XCTAssertNil(fixture.controller.output)
        await fixture.runtime.finishUnload()
        await fixture.controller.waitUntilIdle()
        XCTAssertFalse(fixture.controller.busy)
        XCTAssertFalse(fixture.controller.cancelling)
        XCTAssertNil(fixture.controller.output)
        XCTAssertNil(fixture.controller.resultModel)
    }

    // LML-005: leaving clears completed results, text and the lab-owned audio copy.
    // contract-test: direct surface=gui.apple assertions=apple-local-model-lab.ephemeral-state
    func testPageExitClearsPrivateInputsResultsAndTemporaryAudio() async throws {
        let fixture = try await fixture()
        defer { fixture.cleanup() }
        let source = try fixture.writeAudio()
        fixture.controller.importAudio(source)
        let imported = try XCTUnwrap(fixture.controller.audioInput)
        fixture.controller.privacyText = "Disposable test person"
        fixture.controller.run(.privacyFilter, enabled: true)
        var started = fixture.runStarted.makeAsyncIterator()
        _ = await started.next()
        await fixture.finish()
        XCTAssertNotNil(fixture.controller.output)
        XCTAssertEqual(fixture.controller.resultInput, "Disposable test person")
        fixture.controller.speechText = "Disposable speech"
        XCTAssertTrue(FileManager.default.fileExists(atPath: imported.path))
        fixture.controller.leave()
        XCTAssertEqual(fixture.controller.speechText, "")
        XCTAssertEqual(fixture.controller.privacyText, "")
        XCTAssertEqual(fixture.controller.resultInput, "")
        XCTAssertNil(fixture.controller.audioInput)
        XCTAssertNil(fixture.controller.output)
        XCTAssertNil(fixture.controller.resultModel)
        XCTAssertNil(fixture.controller.elapsed)
        XCTAssertNil(fixture.controller.peakResidentBytes)
        XCTAssertFalse(FileManager.default.fileExists(atPath: imported.deletingLastPathComponent().path))
        XCTAssertTrue(FileManager.default.fileExists(atPath: source.path), "The imported original remains owned by its caller")
    }

    // LML-004/005: a non-cooperative kernel may finish after page exit without restoring results.
    // contract-test: direct surface=gui.apple assertions=apple-local-model-lab.ephemeral-state,apple-local-model-lab.serialized-cancellation
    func testLateCompletionAfterPageExitCannotRestoreResults() async throws {
        let fixture = try await fixture()
        defer { fixture.cleanup() }
        fixture.controller.importAudio(try fixture.writeAudio())
        let imported = try XCTUnwrap(fixture.controller.audioInput)
        fixture.controller.privacyText = "Disposable private input"
        fixture.controller.speechText = "Disposable speech"
        fixture.controller.run(.whisper, enabled: true)
        var started = fixture.runStarted.makeAsyncIterator()
        _ = await started.next()
        fixture.controller.leave()
        XCTAssertEqual(fixture.controller.privacyText, "")
        XCTAssertEqual(fixture.controller.speechText, "")
        XCTAssertNil(fixture.controller.audioInput)
        XCTAssertNil(fixture.controller.output)
        XCTAssertTrue(fixture.controller.busy)
        XCTAssertTrue(FileManager.default.fileExists(atPath: imported.path), "An active kernel may still read this file")
        await fixture.finish()
        XCTAssertFalse(fixture.controller.busy)
        XCTAssertNil(fixture.controller.output)
        XCTAssertNil(fixture.controller.resultModel)
        XCTAssertEqual(fixture.controller.resultInput, "")
        XCTAssertFalse(FileManager.default.fileExists(atPath: imported.deletingLastPathComponent().path))
    }

    // LML-003: availability blocks inference, including callers outside the view.
    // contract-test: direct surface=gui.apple assertions=apple-local-model-lab.availability
    func testUnavailableHardwareBlocksRunBeforeRuntimeLoads() async throws {
        let fixture = try await fixture(available: false)
        defer { fixture.cleanup() }
        fixture.controller.privacyText = "Disposable private input"
        fixture.controller.run(.privacyFilter, enabled: true)
        let runs = await fixture.runtime.runCount
        XCTAssertEqual(runs, 0)
        XCTAssertFalse(fixture.controller.busy)
        XCTAssertNotNil(fixture.controller.errorMessage)
        XCTAssertNil(fixture.controller.output)
    }

    // contract-test: supporting surface=gui.apple assertions=apple-local-model-lab.availability
    func testCapabilityPolicyRejectsIntelAndKokoroOnOS27AndLater() {
        for id in LocalModelID.allCases {
            XCTAssertNotNil(LocalModelLabAvailability.unavailableReason(for: id, architectureSupported: false, osMajorVersion: 26))
        }
        XCTAssertNil(LocalModelLabAvailability.unavailableReason(for: .kokoro, architectureSupported: true, osMajorVersion: 26))
        for os in [27, 28] {
            XCTAssertNotNil(LocalModelLabAvailability.unavailableReason(for: .kokoro, architectureSupported: true, osMajorVersion: os))
            XCTAssertNil(LocalModelLabAvailability.unavailableReason(for: .whisper, architectureSupported: true, osMajorVersion: os))
            XCTAssertNil(LocalModelLabAvailability.unavailableReason(for: .privacyFilter, architectureSupported: true, osMajorVersion: os))
        }
    }

    private func fixture(available: Bool = true) async throws -> LabControllerFixture {
        let root = FileManager.default.temporaryDirectory.appendingPathComponent("local-lab-test-" + UUID().uuidString)
        try FileManager.default.createDirectory(at: root, withIntermediateDirectories: true)
        let bytes = Data("disposable fixture asset".utf8)
        let digest = SHA256.hash(data: bytes).map { String(format: "%02x", $0) }.joined()
        let revision = String(repeating: "a", count: 40)
        let models = LocalModelID.allCases.map { id in
            LocalModelManifest(id: id, revision: revision, estimatedSizeBytes: Int64(bytes.count), files: [
                LocalModelFile(path: "model.bin", url: URL(string: "https://huggingface.co/fixture/resolve/\(revision)/model.bin")!,
                               sha256: digest, sizeBytes: Int64(bytes.count))
            ])
        }
        let store = LocalModelStore(catalog: try JSONEncoder().encode(LocalModelCatalog(models: models)),
                                   root: root.appendingPathComponent("models"),
                                   downloader: LabFixtureDownloader(bytes: bytes), verifyExisting: false)
        for id in LocalModelID.allCases {
            await store.download(id)
            _ = try store.installedDirectory(id)
        }
        let started = AsyncStream<Void>.makeStream()
        let unloading = AsyncStream<Void>.makeStream()
        let runtime = ControlledLabRuntime(started: started.continuation, unloading: unloading.continuation)
        let controller = LocalModelLabController(store: store, temporaryRoot: root,
            availability: { _ in available ? nil : AppStrings.localLabArchitectureUnavailable },
            runtimeFactory: { _ in runtime })
        return LabControllerFixture(root: root, controller: controller, runtime: runtime,
                                    runStarted: started.stream, unloadStarted: unloading.stream)
    }
}

private struct LabFixtureDownloader: LocalModelFileDownloading {
    let bytes: Data
    func download(_ file: LocalModelFile, to destination: URL,
                  progress: @escaping @Sendable (Int64) -> Void) async throws {
        try bytes.write(to: destination)
        progress(Int64(bytes.count))
    }
}

/// Continuations deliberately ignore cancellation, matching a native kernel that must drain.
private actor ControlledLabRuntime: LocalModelRuntime {
    private let started: AsyncStream<Void>.Continuation
    private let unloading: AsyncStream<Void>.Continuation
    private var runContinuation: CheckedContinuation<LocalModelTestOutput, Never>?
    private var unloadContinuation: CheckedContinuation<Void, Never>?
    private(set) var runCount = 0
    init(started: AsyncStream<Void>.Continuation, unloading: AsyncStream<Void>.Continuation) {
        self.started = started
        self.unloading = unloading
    }
    func run(_ request: LocalModelTestRequest, directory: URL) async throws -> LocalModelTestOutput {
        runCount += 1
        return await withCheckedContinuation { continuation in
            runContinuation = continuation
            started.yield(())
        }
    }
    func unload() async {
        await withCheckedContinuation { continuation in
            unloadContinuation = continuation
            unloading.yield(())
        }
    }
    func finishRun() {
        runContinuation?.resume(returning: LocalModelTestOutput(text: "Disposable generated output"))
        runContinuation = nil
    }
    func finishUnload() {
        unloadContinuation?.resume()
        unloadContinuation = nil
    }
}

@MainActor
private struct LabControllerFixture {
    let root: URL
    let controller: LocalModelLabController
    let runtime: ControlledLabRuntime
    let runStarted: AsyncStream<Void>
    let unloadStarted: AsyncStream<Void>
    func finish() async {
        await runtime.finishRun()
        var unloading = unloadStarted.makeAsyncIterator()
        _ = await unloading.next()
        await runtime.finishUnload()
        await controller.waitUntilIdle()
    }
    func cleanup() {
        controller.leave()
        try? FileManager.default.removeItem(at: root)
    }
    func writeAudio() throws -> URL {
        let source = root.appendingPathComponent("disposable-input.wav")
        let format = AVAudioFormat(standardFormatWithSampleRate: 16_000, channels: 1)!
        let buffer = AVAudioPCMBuffer(pcmFormat: format, frameCapacity: 160)!
        buffer.frameLength = 160
        for index in 0..<160 { buffer.floatChannelData![0][index] = 0 }
        try autoreleasepool {
            let writer = try AVAudioFile(forWriting: source, settings: format.settings)
            try writer.write(from: buffer)
        }
        return source
    }
}
