import CryptoKit
import Foundation
import XCTest
@testable import OpenMates

@MainActor
final class PocketTTSLabTests: XCTestCase {
    // contract-test: supporting surface=gui.apple assertions=apple-local-model-lab.pocket-tts,apple-local-model-lab.serialized-cancellation
    func testCancellingKeepsOwnershipUntilNativeSentenceAndCleanupReturn() async throws {
        let fixture = try await fixture()
        defer { try? FileManager.default.removeItem(at: fixture.root) }
        fixture.controller.text = "The quick brown fox jumps over the lazy dog."
        fixture.controller.run(enabled: true)
        var start = fixture.runtime.started.makeAsyncIterator(); _ = await start.next()
        fixture.controller.cancel()
        XCTAssertTrue(fixture.controller.busy)
        XCTAssertTrue(fixture.controller.cancelling)
        fixture.controller.run(enabled: true)
        let calls = await fixture.runtime.calls
        XCTAssertEqual(calls, 1)
        await fixture.runtime.finish()
        await fixture.controller.waitUntilIdle()
        XCTAssertFalse(fixture.controller.busy)
        XCTAssertFalse(fixture.controller.cancelling)
        XCTAssertNil(fixture.controller.audio)
        XCTAssertNil(fixture.controller.errorMessage)
    }

    // contract-test: supporting surface=gui.apple assertions=apple-local-model-lab.pocket-tts,apple-local-model-lab.ephemeral-state
    func testLeavingDiscardsPrivateTextAndLateAudioWithoutReleasingRunEarly() async throws {
        let fixture = try await fixture()
        defer { try? FileManager.default.removeItem(at: fixture.root) }
        fixture.controller.text = "Disposable test phrase."
        fixture.controller.run(enabled: true)
        var start = fixture.runtime.started.makeAsyncIterator(); _ = await start.next()
        fixture.controller.leave()
        XCTAssertTrue(fixture.controller.busy)
        XCTAssertEqual(fixture.controller.text, "")
        await fixture.runtime.finish(); await fixture.controller.waitUntilIdle()
        XCTAssertNil(fixture.controller.audio)
        XCTAssertNil(fixture.controller.measurement)
        XCTAssertFalse(fixture.controller.busy)
    }

    // contract-test: supporting surface=gui.apple assertions=apple-local-model-lab.pocket-tts,apple-local-model-lab.local-execution
    func testSuccessfulRunRetainsRealWAVAndMeasuredLifecycleInMemory() async throws {
        let fixture = try await fixture()
        defer { try? FileManager.default.removeItem(at: fixture.root) }
        fixture.controller.text = "Disposable test phrase."
        fixture.controller.run(enabled: true)
        var start = fixture.runtime.started.makeAsyncIterator(); _ = await start.next()
        await fixture.runtime.finish(); await fixture.controller.waitUntilIdle()
        let audio = try XCTUnwrap(fixture.controller.audio)
        XCTAssertEqual(try PocketTTSWAV.pcm(audio.wav), Data([1, 0, 2, 0]))
        XCTAssertEqual(fixture.controller.measurement?.phase, .completion)
        XCTAssertNotNil(fixture.controller.measurement?.elapsed)
        fixture.controller.leave()
        XCTAssertNil(fixture.controller.audio)
    }

    // contract-test: supporting surface=gui.apple assertions=apple-local-model-lab.pocket-tts,apple-local-model-lab.isolated-scope
    func testOptOutAndInvalidInputNeverStartRuntime() async throws {
        let fixture = try await fixture()
        defer { try? FileManager.default.removeItem(at: fixture.root) }
        fixture.controller.text = "Disposable test phrase."
        fixture.controller.run(enabled: false)
        fixture.controller.text = String(repeating: "x", count: 601)
        fixture.controller.run(enabled: true)
        let calls = await fixture.runtime.calls
        XCTAssertEqual(calls, 0)
        XCTAssertFalse(fixture.controller.busy)
        XCTAssertNil(fixture.controller.audio)
    }

    // contract-test: supporting surface=gui.apple assertions=apple-local-model-lab.pocket-tts
    func testInputIsBoundedWithoutSilentlyTruncating() throws {
        XCTAssertEqual(try PocketTTSInput.sentences("First sentence. Second sentence!"), ["First sentence.", "Second sentence!"])
        XCTAssertThrowsError(try PocketTTSInput.sentences("One. Two. Three. Four. Five."))
        XCTAssertThrowsError(try PocketTTSInput.sentences(String(repeating: "é", count: 81)))
        XCTAssertThrowsError(try PocketTTSInput.sentences("text\0text"))
        let words = Array(repeating: "word", count: 65).joined(separator: " ")
        let sentences = try PocketTTSInput.sentences(words)
        XCTAssertTrue(sentences.allSatisfy { $0.utf8.count <= 160 })
        XCTAssertEqual(sentences.joined(separator: " "), words)
    }

    // contract-test: supporting surface=gui.apple assertions=apple-local-model-lab.pocket-tts
    func testWAVValidationRejectsMalformedOrUnsupportedAudio() throws {
        let pcm = Data([1, 0, 2, 0])
        let valid = PocketTTSWAV.encode(pcm)
        XCTAssertEqual(try PocketTTSWAV.pcm(valid), pcm)
        XCTAssertThrowsError(try PocketTTSWAV.pcm(valid.dropLast()))
        var stereo = valid; stereo[22] = 2
        XCTAssertThrowsError(try PocketTTSWAV.pcm(stereo))
        var length = valid; length[40] = 255
        XCTAssertThrowsError(try PocketTTSWAV.pcm(length))
    }

    private func fixture() async throws -> (root: URL, controller: PocketTTSLabController, runtime: PocketBlockingRuntime) {
        let root = FileManager.default.temporaryDirectory.appendingPathComponent("pocket-lab-unit-" + UUID().uuidString)
        let directory = root.appendingPathComponent("pocketTTS")
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
        let data = Data([1]), revision = String(repeating: "a", count: 40)
        let manifest = LocalModelManifest(id: .pocketTTS, revision: revision, estimatedSizeBytes: 1,
            files: [.init(path: "fixture.bin", url: URL(string: "https://huggingface.co/fixture/resolve/\(revision)/fixture.bin")!,
                          sha256: SHA256.hash(data: data).map { String(format: "%02x", $0) }.joined(), sizeBytes: 1)])
        try data.write(to: directory.appendingPathComponent("fixture.bin"))
        try JSONEncoder().encode(manifest).write(to: directory.appendingPathComponent(".installed.json"))
        let store = LocalModelStore(catalog: try JSONEncoder().encode(LocalModelCatalog(models: [manifest])), root: root)
        await store.waitUntilRestored()
        XCTAssertEqual(store.state(for: .pocketTTS), .ready)
        let runtime = PocketBlockingRuntime()
        return (root, PocketTTSLabController(store: store, runtime: runtime, availability: { true }), runtime)
    }
}

private actor PocketBlockingRuntime: PocketTTSRuntime {
    nonisolated let started: AsyncStream<Void>
    private let startedContinuation: AsyncStream<Void>.Continuation
    private var continuation: CheckedContinuation<Void, Never>?
    private(set) var calls = 0
    init() { let stream = AsyncStream<Void>.makeStream(); started = stream.stream; startedContinuation = stream.continuation }
    func synthesize(_ text: String, directory: URL,
                    progress: @escaping @Sendable (LocalModelRunPhase) -> Void) async throws -> PocketTTSAudio {
        calls += 1; progress(.modelLoading)
        await withCheckedContinuation { continuation = $0; startedContinuation.yield(()) }
        progress(.cleanup)
        return PocketTTSAudio(wav: PocketTTSWAV.encode(Data([1, 0, 2, 0])), duration: 2.0 / 24_000)
    }
    func finish() { continuation?.resume(); continuation = nil }
}
