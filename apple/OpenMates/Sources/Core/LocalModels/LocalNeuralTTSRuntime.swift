// Optional local synthesis for the model lab and production response playback.
// Assets must already be verified; adapters never download models or use OS speech.
// Specification: specifications/features/apple-local-model-lab/specification.yml
// Assertions: apple-local-model-lab.local-execution, apple-local-model-lab.serialized-cancellation, apple-local-model-lab.ephemeral-state
// Specification: specifications/features/assistant-response-speech/specification.yml
// Assertions: assistant-speech.surface.semantic-parity
import Foundation
#if canImport(OnnxRuntimeBindings) && !os(watchOS)
@preconcurrency import OnnxRuntimeBindings
#endif

struct LocalTTSSynthesisInput: Sendable {
    let text: String
    let voice: String
    let language: String
    let steps: Int
    static let supertonicVoices = (1...5).map { "F\($0)" } + (1...5).map { "M\($0)" }
    static let supertonicLanguages = ["en", "ko", "ja", "ar", "bg", "cs", "da", "de", "el", "es", "et", "fi", "fr", "hi", "hr", "hu", "id", "it", "lt", "lv", "nl", "pl", "pt", "ro", "ru", "sk", "sl", "sv", "tr", "uk", "vi"]
    func validate(for model: LocalModelID) throws {
        guard !text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty,
              text.count <= 2_000 else { throw LocalSpeechRuntimeError.invalidRequest }
        switch model {
        case .supertonic3:
            guard Self.supertonicVoices.contains(voice), Self.supertonicLanguages.contains(language),
                  (1...20).contains(steps) else { throw LocalSpeechRuntimeError.invalidRequest }
        default: throw LocalSpeechRuntimeError.invalidRequest
        }
    }
}

/// Common mono PCM16 format, bounded duration, no retained private input in headers.
enum LocalTTSWAV {
    static func encode(samples: [Float], sampleRate: Int) throws -> Data {
        guard (8_000...96_000).contains(sampleRate), !samples.isEmpty,
              samples.count <= sampleRate * 120, samples.allSatisfy(\.isFinite) else {
            throw LocalSpeechRuntimeError.invalidOutput
        }
        let byteCount = UInt32(samples.count * 2)
        var data = Data()
        func append<T: FixedWidthInteger>(_ value: T) {
            var little = value.littleEndian
            withUnsafeBytes(of: &little) { data.append(contentsOf: $0) }
        }
        data.append(contentsOf: "RIFF".utf8); append(byteCount + 36)
        data.append(contentsOf: "WAVEfmt ".utf8); append(UInt32(16))
        append(UInt16(1)); append(UInt16(1)); append(UInt32(sampleRate))
        append(UInt32(sampleRate * 2)); append(UInt16(2)); append(UInt16(16))
        data.append(contentsOf: "data".utf8); append(byteCount)
        for value in samples { append(Int16((max(-1, min(1, value)) * 32767).rounded())) }
        return data
    }
    static func write(samples: [Float], sampleRate: Int, to destination: URL) throws -> LocalModelTestOutput {
        let data = try encode(samples: samples, sampleRate: sampleRate)
        try Task.checkCancellation()
        try data.write(to: destination, options: .atomic)
        return LocalModelTestOutput(audioDurationSeconds: Double(samples.count) / Double(sampleRate), audioURL: destination)
    }
}

actor LocalNeuralTTSRuntime: LocalModelRuntime {
    let model: LocalModelID
    private var running = false
    private var drain: Task<LocalModelTestOutput, Error>?
    init(model: LocalModelID) { self.model = model }

    func run(_ request: LocalModelTestRequest, directory: URL) async throws -> LocalModelTestOutput {
        try await run(request, directory: directory, progress: { _ in })
    }
    func run(_ request: LocalModelTestRequest, directory: URL,
             progress: @escaping @Sendable (LocalModelRunPhase) -> Void) async throws -> LocalModelTestOutput {
        guard !running else { throw LocalSpeechRuntimeError.busy }
        guard case let .synthesize(input, destination) = request else { throw LocalSpeechRuntimeError.invalidRequest }
        try input.validate(for: model)
        running = true
        defer { running = false; drain = nil }
        let model = model
        let work = Task.detached(priority: .userInitiated) {
            do {
                try Task.checkCancellation()
                switch model {
                case .supertonic3:
                    #if canImport(OnnxRuntimeBindings) && !os(watchOS)
                    // The pinned helper only opens explicit local file paths.
                    progress(.modelLoading)
                    let onnx = directory.appendingPathComponent("onnx")
                    let style = try ST3loadVoiceStyle([directory.appendingPathComponent("voice_styles/\(input.voice).json").path], verbose: false)
                    try Task.checkCancellation()
                    let env = try ORTEnv(loggingLevel: .error)
                    let engine = try ST3loadTextToSpeech(onnx.path, false, env)
                    try Task.checkCancellation()
                    progress(.speechSynthesis)
                    let (samples, _) = try engine.call(input.text, input.language, style, input.steps)
                    progress(.audioEncoding)
                    return try LocalTTSWAV.write(samples: samples, sampleRate: engine.sampleRate, to: destination)
                    #else
                    throw LocalSpeechRuntimeError.unavailableRuntime
                    #endif
                default: throw LocalSpeechRuntimeError.invalidRequest
                }
            } catch {
                // Destination belongs to this operation's ephemeral directory.
                try? FileManager.default.removeItem(at: destination)
                throw error
            }
        }
        drain = work
        do {
            return try await withTaskCancellationHandler {
                let value = try await work.value
                try Task.checkCancellation()
                return value
            } onCancel: { work.cancel() }
        } catch {
            try? FileManager.default.removeItem(at: destination)
            throw error
        }
    }
    func unload() async {
        // Native sessions live entirely inside the awaited worker. Unload never
        // declares idle while the model still retains its native sessions.
        if let drain { _ = try? await drain.value }
    }
}

// Single production worker, separate from the laboratory. Native ORT state is
// touched only by its serial queue, including cancellation/memory eviction.
final class SupertonicComposerRuntime: @unchecked Sendable {
    private let ownerID = UUID()
    private let queue = DispatchQueue(label: "org.openmates.local-speech", qos: .userInitiated)
    #if canImport(OnnxRuntimeBindings) && arch(arm64) && !os(watchOS)
    private var engine: ST3TextToSpeech?
    private var environment: ORTEnv?
    private var directory: URL?
    private var styles: [String: ST3Style] = [:]
    #endif

    func prepare(directory: URL) async throws {
        try await withCheckedThrowingContinuation { (continuation: CheckedContinuation<Void, Error>) in
            queue.async { [self] in
                do { try load(directory); continuation.resume() }
                catch { continuation.resume(throwing: error) }
            }
        }
    }
    func synthesize(_ input: LocalTTSSynthesisInput, directory: URL) async throws -> Data {
        try input.validate(for: .supertonic3)
        let bytes: Data = try await withCheckedThrowingContinuation { continuation in
            queue.async { [self] in
                do {
                    try load(directory)
                    #if canImport(OnnxRuntimeBindings) && arch(arm64) && !os(watchOS)
                    guard let engine else { throw LocalSpeechRuntimeError.unavailableRuntime }
                    let style: ST3Style
                    if let cached = styles[input.voice] { style = cached }
                    else {
                        style = try ST3loadVoiceStyle([directory.appendingPathComponent("voice_styles/" + input.voice + ".json").path], verbose: false)
                        styles[input.voice] = style
                    }
                    let (samples, _) = try engine.call(input.text, input.language, style, input.steps)
                    continuation.resume(returning: try LocalTTSWAV.encode(samples: samples, sampleRate: engine.sampleRate))
                    #else
                    throw LocalSpeechRuntimeError.unavailableRuntime
                    #endif
                } catch { continuation.resume(throwing: error) }
            }
        }
        try Task.checkCancellation()
        return bytes
    }
    private func load(_ directory: URL) throws {
        #if canImport(OnnxRuntimeBindings) && arch(arm64) && !os(watchOS)
        if self.directory == directory, engine != nil { return }
        engine = nil; environment = nil; styles = [:]
        try LocalSpeechInferenceOwnership.shared.acquire(ownerID)
        do {
            let env = try ORTEnv(loggingLevel: .error)
            let loaded = try ST3loadTextToSpeech(directory.appendingPathComponent("onnx").path, false, env)
            environment = env; engine = loaded; self.directory = directory
        } catch {
            LocalSpeechInferenceOwnership.shared.release(ownerID)
            throw error
        }
        #else
        throw LocalSpeechRuntimeError.unavailableRuntime
        #endif
    }
    func unload() {
        queue.async { [self] in
            #if canImport(OnnxRuntimeBindings) && arch(arm64) && !os(watchOS)
            engine = nil; environment = nil; directory = nil; styles = [:]
            LocalSpeechInferenceOwnership.shared.release(ownerID)
            #endif
        }
    }
}
