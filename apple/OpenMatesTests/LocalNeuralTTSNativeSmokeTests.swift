// Opt-in real CPU ONNX compatibility test; separate from synthetic unit/UI fixtures.
// Explicit predownloaded model root, fixed public text, no network or playback.
// This validates tensors and non-silent PCM, not pronunciation/voice quality.
// Specification: specifications/features/apple-local-model-lab/specification.yml
import AVFoundation
import Foundation
import XCTest
@testable import OpenMates

@MainActor
final class LocalNeuralTTSNativeSmokeTests: XCTestCase {
    // contract-test: direct surface=gui.apple assertions=apple-local-model-lab.optional-downloads,apple-local-model-lab.local-execution,apple-local-model-lab.ephemeral-state
    func testExplicitLocalExactModelsGenerateValidNonSilentWAVs() async throws {
        let environment = ProcessInfo.processInfo.environment
        guard environment["OPENMATES_RUN_OFFLINE_TTS_SMOKE"] == "1" else {
            throw XCTSkip("Real offline neural speech smoke test requires explicit developer opt-in.")
        }
        let rootPath = try XCTUnwrap(environment["OPENMATES_TTS_SMOKE_MODEL_ROOT"],
            "Opted-in smoke test requires an explicit already downloaded local model root.")
        guard rootPath.hasPrefix("/") else {
            return XCTFail("The model root must be an absolute local file path.")
        }
        #if !arch(arm64) || !canImport(OnnxRuntimeBindings) || os(watchOS)
        return XCTFail("Opted-in test requires the Supertonic CPU ONNX adapter on a supported arm64 app target.")
        #endif
        let modelRoot = URL(fileURLWithPath: rootPath, isDirectory: true)
        let catalogURL = try XCTUnwrap(Bundle.main.url(forResource: "catalog", withExtension: "json"))
        let manifests = try JSONDecoder().decode(LocalModelCatalog.self, from: Data(contentsOf: catalogURL)).validated()
        let models: [(id: LocalModelID, revision: String, sampleRate: Double, voice: String)] = [
            (.supertonic3, "aafc6e32416a594460b32413efc49d7fe4ce6d46", 44_100, "F1")
        ]
        let outputRoot = FileManager.default.temporaryDirectory
            .appendingPathComponent("openmates-neural-tts-smoke-" + UUID().uuidString, isDirectory: true)
        try FileManager.default.createDirectory(at: outputRoot, withIntermediateDirectories: true)
        defer { try? FileManager.default.removeItem(at: outputRoot) }
        // Public, synthetic phrase; neither private input nor a cloned voice sample.
        let phrase = "Hello world. This is a local speech test."
        for selected in models {
            let manifest = try XCTUnwrap(manifests.first { $0.id == selected.id })
            guard manifest.revision == selected.revision else {
                return XCTFail("The selected model manifest must use the exact approved revision.")
            }
            let directory = modelRoot.appendingPathComponent(selected.id.rawValue, isDirectory: true)
            // Verify all catalog sizes and SHA256s before opening native sessions.
            // An installation receipt is unnecessary for this explicit read-only asset fixture.
            try await Task.detached(priority: .utility) {
                try LocalModelDisk.verify(manifest, at: directory, needsReceipt: false)
            }.value
            let destination = outputRoot.appendingPathComponent(selected.id.rawValue).appendingPathExtension("wav")
            let runtime = LocalNeuralTTSRuntime(model: selected.id)
            let started = ProcessInfo.processInfo.systemUptime
            let result: LocalModelTestOutput
            do {
                result = try await runtime.run(.synthesize(LocalTTSSynthesisInput(
                    text: phrase, voice: selected.voice, language: "en", steps: 8), destination: destination),
                    directory: directory)
            } catch {
                await runtime.unload()
                throw error
            }
            await runtime.unload()
            let elapsed = ProcessInfo.processInfo.systemUptime - started
            XCTAssertEqual(result.audioURL, destination)
            let file = try AVAudioFile(forReading: destination, commonFormat: .pcmFormatFloat32, interleaved: false)
            XCTAssertEqual(file.fileFormat.sampleRate, selected.sampleRate)
            XCTAssertEqual(file.fileFormat.channelCount, 1)
            let duration = Double(file.length) / file.fileFormat.sampleRate
            XCTAssertGreaterThanOrEqual(duration, 0.2)
            XCTAssertLessThanOrEqual(duration, 30, "The fixed short phrase must have bounded output.")
            let reportedDuration = try XCTUnwrap(result.audioDurationSeconds)
            XCTAssertEqual(reportedDuration, duration, accuracy: 1 / selected.sampleRate)
            // Guard allocation after assertions; a failed duration never allocates an unbounded buffer.
            guard file.length > 0, file.length <= Int64(selected.sampleRate * 30) else {
                return XCTFail("Invalid waveform length.")
            }
            let buffer = try XCTUnwrap(AVAudioPCMBuffer(pcmFormat: file.processingFormat,
                                                       frameCapacity: AVAudioFrameCount(file.length)))
            try file.read(into: buffer)
            XCTAssertEqual(Int64(buffer.frameLength), file.length)
            let channel = try XCTUnwrap(buffer.floatChannelData?[0])
            let samples = UnsafeBufferPointer(start: channel, count: Int(buffer.frameLength))
            XCTAssertTrue(samples.allSatisfy(\.isFinite))
            let peak = samples.reduce(0.0) { max($0, abs(Double($1))) }
            let rms = sqrt(samples.reduce(0.0) { $0 + Double($1) * Double($1) } / Double(samples.count))
            XCTAssertGreaterThan(peak, 0.0001, "Real model output must have nonzero signal.")
            XCTAssertGreaterThan(rms, 0.00001)
            XCTAssertLessThanOrEqual(peak, 1.001)
            let receipt: [String: Any] = ["model": selected.id.rawValue, "revision": selected.revision,
                "sampleRate": selected.sampleRate, "frames": file.length, "durationSeconds": duration,
                "elapsedSeconds": elapsed, "peakAmplitude": peak, "rmsAmplitude": rms,
                "qualityClaim": false]
            let attachment = XCTAttachment(data: try JSONSerialization.data(withJSONObject: receipt, options: [.sortedKeys]),
                uniformTypeIdentifier: "public.json")
            attachment.name = selected.id.rawValue + " real offline ONNX compatibility"
            attachment.lifetime = .keepAlways
            add(attachment)
            // Remove this generated file only; installed assets and external originals are read-only.
            try FileManager.default.removeItem(at: destination)
            XCTAssertFalse(FileManager.default.fileExists(atPath: destination.path))
        }
    }
}
