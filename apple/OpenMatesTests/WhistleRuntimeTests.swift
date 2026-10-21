import AVFoundation
import XCTest
@testable import OpenMates

@MainActor
final class WhistleRuntimeTests: XCTestCase {
    // Native inference is injected. This proves lifecycle only, not device feasibility or ASR quality.
    // contract-test: supporting surface=gui.apple assertions=message-input.recording.lifecycle
    func testCancelledNativeCallDrainsBeforeLeaseReleaseAndSuppressesText() async throws {
        let engine = WhistleEngineProbe()
        let runtime = WhistlePCMRuntime(modelURL: URL(fileURLWithPath: "/fixture/whistle.cact"), engine: engine)
        let run = Task { try await runtime.transcribe([0.25, 0.5]) }
        await engine.waitForCall()
        run.cancel()
        let beforeDrain = await engine.ended
        XCTAssertEqual(beforeDrain, 0)
        await engine.completeCall()
        do { _ = try await run.value; XCTFail("Cancelled text must never escape") }
        catch is CancellationError { }
        await runtime.unload()
        let ended = await engine.ended
        XCTAssertEqual(ended, 1)
        let capability = await runtime.capability()
        XCTAssertTrue(capability.modelResident, "Session stop never pretends to free native weights")
        XCTAssertFalse(capability.reclaimsModelOnSessionEnd)
    }

    // contract-test: supporting surface=gui.apple assertions=message-input.recording.lifecycle
    func testGlobalSpeechLeasePreventsASecondModelLoad() async throws {
        let firstEngine = WhistleEngineProbe(), secondEngine = WhistleEngineProbe()
        let first = WhistlePCMRuntime(modelURL: URL(fileURLWithPath: "/fixture/whistle.cact"), engine: firstEngine)
        let second = WhistlePCMRuntime(modelURL: URL(fileURLWithPath: "/fixture/whistle.cact"), engine: secondEngine)
        let run = Task { try await first.transcribe([0]) }
        await firstEngine.waitForCall()
        do { _ = try await second.transcribe([0]); XCTFail("Busy ownership must reject") }
        catch let error as LocalSpeechRuntimeError { if case .busy = error {} else { XCTFail("Expected busy") } }
        let secondLoads = await secondEngine.loads
        XCTAssertEqual(secondLoads, 0)
        await second.unload()
        let firstEnded = await firstEngine.ended
        XCTAssertEqual(firstEnded, 0, "Rejected owner must never reset the active owner's context")
        await firstEngine.completeCall()
        _ = try await run.value
        await first.unload()
    }

    // contract-test: supporting surface=gui.apple assertions=message-input.recording.lifecycle,message-input.privacy-context
    func testInvalidPCMNeverEntersNativeEngine() async throws {
        let engine = WhistleEngineProbe()
        let runtime = WhistlePCMRuntime(modelURL: URL(fileURLWithPath: "/fixture/whistle.cact"), engine: engine)
        let invalidInputs: [[Float]] = [[], [.nan], [.infinity], [1.1], Array(repeating: 0, count: WhistlePCMRuntime.maximumSamples + 1)]
        for pcm in invalidInputs {
            do { _ = try await runtime.transcribe(pcm); XCTFail("Expected invalid request") }
            catch let error as LocalSpeechRuntimeError { if case .invalidRequest = error {} else { XCTFail("Expected invalidRequest") } }
        }
        let loads = await engine.loads
        XCTAssertEqual(loads, 0)
        await runtime.unload()
    }

    // contract-test: supporting surface=gui.apple assertions=message-input.recording.lifecycle,message-input.privacy-context
    func testRecordingConverts44100HzIntoBounded16000HzWindows() async throws {
        let directory = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString, isDirectory: true)
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
        defer { try? FileManager.default.removeItem(at: directory) }
        let url = directory.appendingPathComponent("fixture.wav")
        let format = try XCTUnwrap(AVAudioFormat(commonFormat: .pcmFormatFloat32, sampleRate: 44_100, channels: 1, interleaved: false))
        let frames = AVAudioFrameCount(44_100 * 20.25)
        let pcm = try XCTUnwrap(AVAudioPCMBuffer(pcmFormat: format, frameCapacity: frames))
        pcm.frameLength = frames
        let channel = try XCTUnwrap(pcm.floatChannelData?[0])
        for index in 0..<Int(frames) { channel[index] = Float(sin(Double(index) * .pi / 100)) * 0.25 }
        try {
            let file = try AVAudioFile(forWriting: url, settings: format.settings)
            try file.write(from: pcm)
        }()
        let probe = WhistlePCMProbe()
        let transcriber = WhistleRecordingDraftTranscriber(makeRuntime: { probe })
        let text = try await transcriber.transcribe(fileURL: url)
        let counts = await probe.windowCounts
        XCTAssertGreaterThanOrEqual(counts.count, 2)
        XCTAssertTrue(counts.allSatisfy { $0 > 0 && $0 <= 16_000 * 20 })
        XCTAssertEqual(Double(counts.reduce(0, +)), 16_000 * 20.25, accuracy: 100)
        XCTAssertEqual(text, counts.indices.map { "segment\($0 + 1)" }.joined(separator: " "))
        let ended = await probe.ended
        XCTAssertEqual(ended, 1)
    }

    // contract-test: supporting surface=gui.apple assertions=message-input.recording.lifecycle
    func testExplicitStopWaitsForSuspendedLoadAndSessionEnd() async throws {
        let engine = WhistleBarrierEngine(held: [.load, .sessionEnd])
        let runtime = WhistlePCMRuntime(modelURL: URL(fileURLWithPath: "/fixture/whistle.cact"), engine: engine)
        let run = Task { try await runtime.transcribe([0.25]) }
        await engine.waitUntilStarted(.load)
        let stop = await runtime.requestStop()
        let repeated = Task { await runtime.unload() }
        let beforeLoadDrains = await engine.snapshot()
        XCTAssertFalse(beforeLoadDrains.started.contains(.sessionEnd))
        assertSpeechLeaseIsBusy()
        await engine.release(.load)
        await engine.waitUntilStarted(.sessionEnd)
        let whileEnding = await engine.snapshot()
        XCTAssertEqual(whileEnding.transcriptions, 0, "Stopping during load prevents inference entirely")
        XCTAssertEqual(whileEnding.ended, 0)
        assertSpeechLeaseIsBusy()
        await engine.release(.sessionEnd)
        do { _ = try await run.value; XCTFail("Stop during load must cancel") }
        catch is CancellationError { }
        await stop.value; await repeated.value; await runtime.unload()
        let finished = await engine.snapshot()
        XCTAssertEqual(finished.ended, 1, "All stop callers share one session-end operation")
    }

    // contract-test: supporting surface=gui.apple assertions=message-input.recording.lifecycle
    func testExplicitStopWaitsForNativeTranscriptionAndSuppressesItsLateText() async throws {
        let engine = WhistleBarrierEngine(held: [.transcribe, .sessionEnd])
        let runtime = WhistlePCMRuntime(modelURL: URL(fileURLWithPath: "/fixture/whistle.cact"), engine: engine)
        let run = Task { try await runtime.transcribe([0.25]) }
        await engine.waitUntilStarted(.transcribe)
        let stop = await runtime.requestStop()
        let repeated = Task { await runtime.unload() }
        let beforeNativeDrains = await engine.snapshot()
        XCTAssertFalse(beforeNativeDrains.started.contains(.sessionEnd))
        assertSpeechLeaseIsBusy()
        await engine.release(.transcribe)
        await engine.waitUntilStarted(.sessionEnd)
        assertSpeechLeaseIsBusy()
        await engine.release(.sessionEnd)
        do { _ = try await run.value; XCTFail("Native text completed after stop must never escape") }
        catch is CancellationError { }
        await stop.value; await repeated.value; await runtime.unload()
        do { _ = try await runtime.transcribe([0]); XCTFail("Stopped session cannot restart") }
        catch let error as LocalSpeechRuntimeError { if case .busy = error {} else { XCTFail("Expected busy") } }
        let finished = await engine.snapshot()
        XCTAssertEqual(finished.transcriptions, 1)
        XCTAssertEqual(finished.ended, 1)
    }

    // contract-test: supporting surface=gui.apple assertions=message-input.recording.lifecycle,message-input.privacy-context
    func testRepeatedDraftCancelDuringSuspendedFactoryStopsRuntimeBeforeReadingAudio() async throws {
        let probe = WhistlePCMProbe()
        let factory = WhistleFactoryBarrier(runtime: probe)
        let transcriber = WhistleRecordingDraftTranscriber(makeRuntime: { await factory.make() })
        let run = Task { try await transcriber.transcribe(fileURL: URL(fileURLWithPath: "/fixture/must-not-be-read.m4a")) }
        await factory.waitUntilStarted()
        await transcriber.cancel(); await transcriber.cancel()
        await factory.release()
        do { _ = try await run.value; XCTFail("Cancelled factory result cannot start transcription") }
        catch is CancellationError { }
        await transcriber.cancel()
        let counts = await probe.windowCounts, ended = await probe.ended
        XCTAssertTrue(counts.isEmpty)
        XCTAssertEqual(ended, 1)
    }

    // This writes real AAC at native test execution time; no pre-generated fixture or native job is needed here.
    // contract-test: supporting surface=gui.apple assertions=message-input.recording.lifecycle,message-input.privacy-context
    func testWatchStyle44100HzM4AAndStereoDownmixIncludesRightChannel() async throws {
        let directory = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString, isDirectory: true)
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
        defer { try? FileManager.default.removeItem(at: directory) }
        for channelCount in [1, 2] {
            let url = directory.appendingPathComponent("watch-style-\(channelCount).m4a")
            try {
                let settings: [String: Any] = [AVFormatIDKey: kAudioFormatMPEG4AAC, AVSampleRateKey: 44_100,
                                              AVNumberOfChannelsKey: channelCount, AVEncoderBitRateKey: 128_000]
                let file = try AVAudioFile(forWriting: url, settings: settings, commonFormat: .pcmFormatFloat32, interleaved: false)
                let pcm = try XCTUnwrap(AVAudioPCMBuffer(pcmFormat: file.processingFormat, frameCapacity: 44_100))
                pcm.frameLength = 44_100
                let channels = try XCTUnwrap(pcm.floatChannelData)
                for index in 0..<44_100 {
                    for channel in 0..<channelCount { channels[channel][index] = 0 }
                    channels[channelCount - 1][index] = Float(sin(Double(index) * 2 * .pi * 440 / 44_100)) * 0.5
                }
                try file.write(from: pcm)
            }()
            let source = try AVAudioFile(forReading: url)
            XCTAssertEqual(source.fileFormat.sampleRate, 44_100)
            XCTAssertEqual(source.fileFormat.channelCount, AVAudioChannelCount(channelCount))
            XCTAssertEqual(source.fileFormat.streamDescription.pointee.mFormatID, kAudioFormatMPEG4AAC)
            let probe = WhistlePCMProbe()
            let transcriber = WhistleRecordingDraftTranscriber(makeRuntime: { probe })
            _ = try await transcriber.transcribe(fileURL: url)
            let count = await probe.windowCounts.reduce(0, +)
            let rms = await probe.rms()
            XCTAssertEqual(Double(count), 16_000, accuracy: 2_048, "AAC priming may add a bounded codec tail")
            XCTAssertGreaterThan(rms, 0.08, "Mono/right-only stereo audio must survive mono conversion")
            XCTAssertLessThan(rms, 0.4)
            let ended = await probe.ended
            XCTAssertEqual(ended, 1)
        }
    }

    // contract-test: supporting surface=gui.apple assertions=message-input.privacy-context
    func testMalformedRecordingFailsLocallyAndEndsRuntimeWithoutNativeInput() async throws {
        let directory = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString, isDirectory: true)
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
        defer { try? FileManager.default.removeItem(at: directory) }
        let url = directory.appendingPathComponent("malformed.m4a")
        try Data("not an audio container".utf8).write(to: url)
        let probe = WhistlePCMProbe()
        let transcriber = WhistleRecordingDraftTranscriber(makeRuntime: { probe })
        do { _ = try await transcriber.transcribe(fileURL: url); XCTFail("Malformed audio must fail") }
        catch let error as LocalSpeechRuntimeError { if case .invalidOutput = error {} else { XCTFail("Expected sanitized local failure") } }
        let counts = await probe.windowCounts, ended = await probe.ended
        XCTAssertTrue(counts.isEmpty)
        XCTAssertEqual(ended, 1)
    }

    // contract-test: supporting surface=gui.apple assertions=message-input.privacy-context
    func testNativeOutputRejectsNegativeCodeTruncationMalformedAndOversizedJSON() throws {
        let valid = Data("{\"text\":\"ready\"}\0".utf8)
        let invalid: [(Int32, Data)] = [
            (-1, valid),
            (0, Data("{\"text\":\"unfinished".utf8)),
            (0, Data("{\"text\":\"unfinished\0".utf8)),
            (0, Data("not-json\0".utf8)),
            (0, Data("{\"text\":42}\0".utf8)),
            (0, Data([0xff, 0])),
            (0, Data(repeating: 0, count: WhistleNativeOutput.maximumBytes + 1))
        ]
        for (code, bytes) in invalid {
            XCTAssertThrowsError(try WhistleNativeOutput.parse(returnCode: code, nulTerminatedJSON: bytes)) { error in
                guard case LocalSpeechRuntimeError.invalidOutput = error else { return XCTFail("Only sanitized output failure may escape") }
            }
        }
    }

    // contract-test: supporting surface=gui.apple assertions=message-input.privacy-context
    func testNativeOutputAcceptsSilenceAndUnicodeWithoutExposingExtraNativeFields() throws {
        XCTAssertEqual(try WhistleNativeOutput.parse(returnCode: 0, nulTerminatedJSON: Data("{\"text\":\"\",\"language\":\"\"}\0".utf8)), "")
        let json = #"{"text":"  Grüße aus Köln  ","language":"de","ttft_ms":1.25}"# + "\0"
        XCTAssertEqual(try WhistleNativeOutput.parse(returnCode: 4, nulTerminatedJSON: Data(json.utf8)), "Grüße aus Köln")
    }

    private func assertSpeechLeaseIsBusy(file: StaticString = #filePath, line: UInt = #line) {
        let other = UUID()
        do {
            try LocalSpeechInferenceOwnership.shared.acquire(other)
            LocalSpeechInferenceOwnership.shared.release(other)
            XCTFail("Session must retain ownership until native work and session end both drain", file: file, line: line)
        } catch let error as LocalSpeechRuntimeError {
            if case .busy = error {} else { XCTFail("Expected busy", file: file, line: line) }
        } catch { XCTFail("Expected local busy error", file: file, line: line) }
    }

    // contract-test: supporting surface=gui.apple assertions=message-input.privacy-context
    func testMissingBundleAssetFailsLocally() throws {
        XCTAssertThrowsError(try WhistleBundledAsset.modelURL(in: Bundle(for: WhistleRuntimeTests.self)))
        XCTAssertThrowsError(try WhistleBundledAsset.verifiedModelBytes(at: URL(fileURLWithPath: "/fixture/missing.cact")))
    }
}

private actor WhistleEngineProbe: WhistleNativeEngine {
    private var call: CheckedContinuation<String, Never>?
    private var startedWaiters: [CheckedContinuation<Void, Never>] = []
    private var started = false
    var loads = 0
    var ended = 0
    func load(modelURL: URL) { loads += 1 }
    func transcribe(_ samples: [Float]) async -> String {
        await withCheckedContinuation { continuation in
            call = continuation; started = true
            let waiters = startedWaiters; startedWaiters.removeAll()
            waiters.forEach { $0.resume() }
        }
    }
    func waitForCall() async {
        if started { return }
        await withCheckedContinuation { startedWaiters.append($0) }
    }
    func completeCall() { call?.resume(returning: "private fixture transcript"); call = nil }
    func endSession() { ended += 1 }
    func capability() -> WhistleRuntimeCapability {
        .init(nativeAvailable: true, modelResident: loads > 0, reclaimsModelOnSessionEnd: false,
              nativeScratchErasureVerified: false, minimumOS: "26.2")
    }
}

private actor WhistlePCMProbe: LocalPCMTranscribing {
    var windowCounts: [Int] = []
    var ended = 0
    private var sumSquares = 0.0
    func transcribe(_ samples: [Float]) -> String {
        windowCounts.append(samples.count)
        sumSquares += samples.reduce(0) { $0 + Double($1) * Double($1) }
        return "segment\(windowCounts.count)"
    }
    func rms() -> Double { sqrt(sumSquares / Double(max(1, windowCounts.reduce(0, +)))) }
    func unload() { ended += 1 }
}

private actor WhistleBarrierEngine: WhistleNativeEngine {
    enum Stage: Hashable, Sendable { case load, transcribe, sessionEnd }
    struct Snapshot: Sendable {
        let started: Set<Stage>
        let transcriptions: Int
        let ended: Int
    }
    private let held: Set<Stage>
    private var released: Set<Stage> = []
    private var started: Set<Stage> = []
    private var barriers: [Stage: CheckedContinuation<Void, Never>] = [:]
    private var observers: [Stage: [CheckedContinuation<Void, Never>]] = [:]
    private var transcriptions = 0
    private var ended = 0
    init(held: Set<Stage>) { self.held = held }
    private func enter(_ stage: Stage) async {
        started.insert(stage)
        let waiters = observers.removeValue(forKey: stage) ?? []
        waiters.forEach { $0.resume() }
        if held.contains(stage), !released.contains(stage) {
            await withCheckedContinuation { barriers[stage] = $0 }
        }
    }
    func waitUntilStarted(_ stage: Stage) async {
        if started.contains(stage) { return }
        await withCheckedContinuation { observers[stage, default: []].append($0) }
    }
    func release(_ stage: Stage) { released.insert(stage); barriers.removeValue(forKey: stage)?.resume() }
    func load(modelURL: URL) async { await enter(.load) }
    func transcribe(_ samples: [Float]) async -> String {
        transcriptions += 1; await enter(.transcribe); return "late private fixture transcript"
    }
    func endSession() async { await enter(.sessionEnd); ended += 1 }
    func snapshot() -> Snapshot { .init(started: started, transcriptions: transcriptions, ended: ended) }
    func capability() -> WhistleRuntimeCapability {
        .init(nativeAvailable: true, modelResident: started.contains(.load), reclaimsModelOnSessionEnd: false,
              nativeScratchErasureVerified: false, minimumOS: "26.2")
    }
}

private actor WhistleFactoryBarrier {
    private let runtime: any LocalPCMTranscribing
    private var started = false
    private var result: CheckedContinuation<any LocalPCMTranscribing, Never>?
    private var observers: [CheckedContinuation<Void, Never>] = []
    init(runtime: any LocalPCMTranscribing) { self.runtime = runtime }
    func make() async -> any LocalPCMTranscribing {
        await withCheckedContinuation { continuation in
            result = continuation; started = true
            let waiters = observers; observers.removeAll(); waiters.forEach { $0.resume() }
        }
    }
    func waitUntilStarted() async {
        if started { return }
        await withCheckedContinuation { observers.append($0) }
    }
    func release() { result?.resume(returning: runtime); result = nil }
}
