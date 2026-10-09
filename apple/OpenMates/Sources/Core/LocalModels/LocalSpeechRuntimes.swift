// Optional local speech inference for the model lab and production composer.
// Input and output stay in memory; model files must already be downloaded and verified.
// Specification: specifications/features/apple-local-model-lab/specification.yml
// Assertions: apple-local-model-lab.local-execution, apple-local-model-lab.serialized-cancellation
// Specification: specifications/features/message-input/specification.yml
// Assertions: message-input.recording.lifecycle, message-input.privacy-context
import AVFoundation
import Foundation
import Darwin
#if arch(arm64) && !os(watchOS)
@preconcurrency import CoreML
@preconcurrency import WhisperKit
#endif

enum LocalModelTestRequest: Sendable {
    case transcribe(URL)
    case detectPII(String)
    case synthesize(LocalTTSSynthesisInput, destination: URL)
}

struct LocalModelTestOutput: Sendable {
    let text: String?
    let piiSpans: [PrivacyFilterModelSpan]
    let audioDurationSeconds: Double?
    let audioURL: URL?

    init(text: String? = nil, piiSpans: [PrivacyFilterModelSpan] = [], audioDurationSeconds: Double? = nil, audioURL: URL? = nil) {
        self.text = text
        self.piiSpans = piiSpans
        self.audioDurationSeconds = audioDurationSeconds
        self.audioURL = audioURL
    }
}

protocol LocalModelRuntime: Sendable {
    func run(_ request: LocalModelTestRequest, directory: URL) async throws -> LocalModelTestOutput
    func run(_ request: LocalModelTestRequest, directory: URL,
             progress: @escaping @Sendable (LocalModelRunPhase) -> Void) async throws -> LocalModelTestOutput
    func unload() async
}

// Existing runtime implementations and injected fakes keep the original entry point.
extension LocalModelRuntime {
    func run(_ request: LocalModelTestRequest, directory: URL,
             progress: @escaping @Sendable (LocalModelRunPhase) -> Void) async throws -> LocalModelTestOutput {
        switch request {
        case .transcribe: progress(.transcription)
        case .detectPII: progress(.inference)
        case .synthesize: progress(.speechSynthesis)
        }
        return try await run(request, directory: directory)
    }
}

enum LocalModelRunPhase: Int, CaseIterable, Sendable {
    case submission, tokenizerPreparation, modelLoading, transcription, inference, speechSynthesis, audioEncoding, cleanup, completion
}

struct LocalModelPhaseTiming: Equatable, Sendable {
    let phase: LocalModelRunPhase
    let durationSeconds: Double
}

/// One bounded aggregate per run; samples and private inputs are never retained.
final class LocalModelRunMeasurement: @unchecked Sendable {
    struct Snapshot: Sendable {
        let phase: LocalModelRunPhase
        let timings: [LocalModelPhaseTiming]
        let elapsed: Double
        let baselineBytes: Int64?
        let peakBytes: Int64?
        let endBytes: Int64?
        let warning: Bool
    }
    private let lock = NSLock()
    private let now: @Sendable () -> Double
    private let memory: @Sendable () -> Int64?
    private let warningAfter: Double
    private let started: Double
    private var phaseStarted: Double
    private var current: LocalModelRunPhase = .submission
    private var timings: [LocalModelPhaseTiming] = []
    private var baseline: Int64?
    private var peak: Int64?
    private var end: Int64?
    private var warned = false

    init(now: @escaping @Sendable () -> Double = { ProcessInfo.processInfo.systemUptime },
         memory: @escaping @Sendable () -> Int64? = { LocalModelRunMeasurement.residentBytes() },
         warningAfter: Double = 30) {
        self.now = now; self.memory = memory; self.warningAfter = warningAfter
        let start = now(); started = start; phaseStarted = start
        let bytes = memory(); baseline = bytes; peak = bytes; end = bytes
    }
    func transition(_ phase: LocalModelRunPhase) {
        lock.lock(); defer { lock.unlock() }
        guard phase.rawValue > current.rawValue else { return }
        let time = now()
        let seconds = max(0, time - phaseStarted)
        timings.append(LocalModelPhaseTiming(phase: current, durationSeconds: seconds))
        NativeSyncPerfLog.info("phase=offlineModel phaseCode=\(current.rawValue) durationMs=\(Int(seconds * 1000))")
        current = phase; phaseStarted = time; warned = false
    }
    /// Returns true once per long-running phase. This reports waiting, never kernel idleness.
    @discardableResult func sample() -> Bool {
        let bytes = memory()
        lock.lock(); defer { lock.unlock() }
        if let bytes { end = bytes; peak = max(peak ?? bytes, bytes) }
        guard current != .completion, !warned, now() - phaseStarted >= warningAfter else { return false }
        warned = true
        NativeSyncPerfLog.warning("phase=offlineModelWaiting phaseCode=\(current.rawValue) durationMs=\(Int(max(0, now() - phaseStarted) * 1000))")
        return true
    }
    func snapshot() -> Snapshot {
        lock.lock(); defer { lock.unlock() }
        let time = now()
        let active = LocalModelPhaseTiming(phase: current, durationSeconds: max(0, time - phaseStarted))
        return Snapshot(phase: current, timings: timings + (current == .completion ? [] : [active]),
                        elapsed: max(0, time - started), baselineBytes: baseline, peakBytes: peak,
                        endBytes: end, warning: warned)
    }
    static func residentBytes() -> Int64? {
        var info = mach_task_basic_info()
        var count = mach_msg_type_number_t(MemoryLayout<mach_task_basic_info>.size / MemoryLayout<integer_t>.size)
        let status = withUnsafeMutablePointer(to: &info) { pointer in
            pointer.withMemoryRebound(to: integer_t.self, capacity: Int(count)) {
                task_info(mach_task_self_, task_flavor_t(MACH_TASK_BASIC_INFO), $0, &count)
            }
        }
        return status == KERN_SUCCESS ? Int64(info.resident_size) : nil
    }
}

/// Categories intentionally exclude source text, filenames and library diagnostics.
enum LocalSpeechRuntimeError: Error, Sendable {
    case invalidRequest, unavailableRuntime, invalidAssets, invalidOutput, busy
}

actor WhisperKitLocalRuntime: LocalModelRuntime {
    private var running = false
    private var generation: UInt64 = 0

    func unload() async { generation &+= 1 }

    func run(_ request: LocalModelTestRequest, directory: URL) async throws -> LocalModelTestOutput {
        try await run(request, directory: directory, progress: { _ in })
    }

    func run(_ request: LocalModelTestRequest, directory: URL,
             progress: @escaping @Sendable (LocalModelRunPhase) -> Void) async throws -> LocalModelTestOutput {
        guard case let .transcribe(audioURL) = request else { throw LocalSpeechRuntimeError.invalidRequest }
        guard !running else { throw LocalSpeechRuntimeError.busy }
        running = true
        defer { running = false }
        let token = generation
        try Task.checkCancellation()
        #if arch(arm64) && !os(watchOS)
        do {
            try SpeechAssetPreflight.require(directory, [
                "AudioEncoder.mlmodelc/model.mil", "MelSpectrogram.mlmodelc/model.mil",
                "TextDecoder.mlmodelc/model.mil", "tokenizer/tokenizer.json", "tokenizer/tokenizer_config.json"
            ])
            progress(.tokenizerPreparation)
            let tokenizer = try await LocalWhisperTokenizer(directory: directory.appendingPathComponent("tokenizer"))
            try checkActive(token)
            // Install the local tokenizer before loading. WhisperKit’s tokenizer loader
            // otherwise falls back to a network fetch even when download is false.
            progress(.modelLoading)
            let engine = try await WhisperKit(WhisperKitConfig(
                modelFolder: directory.path, tokenizerFolder: directory.appendingPathComponent("tokenizer"),
                verbose: false, logLevel: .none, prewarm: false, load: false, download: false))
            engine.tokenizer = tokenizer
            engine.textDecoder.isModelMultilingual = true
            do {
                try await engine.loadModels()
                try checkActive(token)
                let file = try AVAudioFile(forReading: audioURL)
                let duration = Double(file.length) / file.processingFormat.sampleRate
                progress(.transcription)
                let results = try await engine.transcribe(audioPath: audioURL.path,
                    decodeOptions: DecodingOptions(detectLanguage: true, skipSpecialTokens: true,
                        concurrentWorkerCount: 1, chunkingStrategy: .vad))
                try checkActive(token)
                progress(.cleanup)
                await engine.unloadModels()
                return LocalModelTestOutput(text: results.map(\.text).joined(separator: " ")
                    .trimmingCharacters(in: .whitespacesAndNewlines), audioDurationSeconds: duration)
            } catch {
                progress(.cleanup)
                await engine.unloadModels()
                throw error
            }
        } catch is CancellationError { throw CancellationError() }
          catch let error as LocalSpeechRuntimeError { throw error }
          catch { throw LocalSpeechRuntimeError.invalidOutput }
        #else
        throw LocalSpeechRuntimeError.unavailableRuntime
        #endif
    }

    private func checkActive(_ token: UInt64) throws {
        try Task.checkCancellation()
        guard token == generation else { throw CancellationError() }
    }
}

#if arch(arm64) && !os(watchOS)
private enum SpeechAssetPreflight {
    static func require(_ directory: URL, _ files: [String]) throws {
        for file in files {
            guard FileManager.default.isReadableFile(atPath: directory.appendingPathComponent(file).path) else {
                throw LocalSpeechRuntimeError.invalidAssets
            }
        }
    }
}

private struct LocalWhisperTokenizer: WhisperTokenizer, Sendable {
    let wrapped: TokenizerWrapper
    let specialTokens: SpecialTokens
    let allLanguageTokens: Set<Int>

    init(directory: URL) async throws {
        let wrapped = try await AutoTokenizerWrapper.from(modelFolder: directory)
        func id(_ spelling: String) throws -> Int {
            guard let value = wrapped.convertTokenToId(spelling) else { throw LocalSpeechRuntimeError.invalidAssets }
            return value
        }
        guard let whitespace = wrapped.encode(text: " ", addSpecialTokens: false).first else {
            throw LocalSpeechRuntimeError.invalidAssets
        }
        self.wrapped = wrapped
        self.specialTokens = try SpecialTokens(endToken: id("<|endoftext|>"), englishToken: id("<|en|>"),
            noSpeechToken: id("<|nospeech|>"), noTimestampsToken: id("<|notimestamps|>"),
            specialTokenBegin: id("<|endoftext|>"), startOfPreviousToken: id("<|startofprev|>"),
            startOfTranscriptToken: id("<|startoftranscript|>"), timeTokenBegin: id("<|0.00|>"),
            transcribeToken: id("<|transcribe|>"), translateToken: id("<|translate|>"), whitespaceToken: whitespace)
        self.allLanguageTokens = Set(Constants.languages.values.compactMap { wrapped.convertTokenToId("<|\($0)|>") })
    }
    func encode(text: String) -> [Int] { wrapped.encode(text: text) }
    func decode(tokens: [Int]) -> String { wrapped.decode(tokens: tokens) }
    func convertTokenToId(_ token: String) -> Int? { wrapped.convertTokenToId(token) }
    func convertIdToToken(_ id: Int) -> String? { wrapped.convertIdToToken(id) }
    // Segment timestamps are enabled; word alignment is intentionally disabled.
    // Group complete UTF-8 tokens rather than splitting an incomplete Unicode scalar.
    func splitToWordTokens(tokenIds: [Int]) -> (words: [String], wordTokens: [[Int]]) {
        var words: [String] = [], groups: [[Int]] = [], pending: [Int] = []
        for token in tokenIds {
            pending.append(token)
            let decoded = wrapped.decode(tokens: pending)
            guard !decoded.contains("\u{fffd}") else { continue }
            if decoded.first?.isWhitespace == true || words.isEmpty || token >= specialTokens.specialTokenBegin {
                words.append(decoded); groups.append(pending)
            } else {
                words[words.count - 1] += decoded; groups[groups.count - 1] += pending
            }
            pending = []
        }
        if !pending.isEmpty { words.append(wrapped.decode(tokens: pending)); groups.append(pending) }
        return (words, groups)
    }
}

#endif

// A native speech call keeps its lease until it has actually drained. This
// prevents a cancelled warm TTS call and a new Whisper load from retaining both
// speech engines alongside enhanced anonymization.
final class LocalSpeechInferenceOwnership: @unchecked Sendable {
    static let shared = LocalSpeechInferenceOwnership()
    private let lock = NSLock()
    private var owner: UUID?
    func acquire(_ id: UUID) throws {
        lock.lock(); defer { lock.unlock() }
        guard owner == nil || owner == id else { throw LocalSpeechRuntimeError.busy }
        owner = id
    }
    func release(_ id: UUID) {
        lock.lock(); defer { lock.unlock() }
        if owner == id { owner = nil }
    }
}

// Production composer adapter. One engine per capture, retained across bounded
// PCM windows and released when capture finishes or its generation is cancelled.
protocol LocalPCMTranscribing: Sendable {
    func transcribe(_ samples: [Float]) async throws -> String
    func unload() async
}

actor WhisperKitComposerRuntime: LocalPCMTranscribing {
    private let ownerID = UUID()
    private let directory: URL
    private var generation: UInt64 = 0
    private var running = false
    #if arch(arm64) && !os(watchOS)
    private var engine: WhisperKit?
    #endif
    init(directory: URL) { self.directory = directory }

    func transcribe(_ samples: [Float]) async throws -> String {
        guard !running, !samples.isEmpty, samples.count <= 16_000 * 30 else { throw LocalSpeechRuntimeError.busy }
        running = true
        defer { running = false }
        let token = generation
        #if arch(arm64) && !os(watchOS)
        do {
            try Task.checkCancellation()
            if engine == nil {
                try LocalSpeechInferenceOwnership.shared.acquire(ownerID)
                try SpeechAssetPreflight.require(directory, [
                    "AudioEncoder.mlmodelc/model.mil", "MelSpectrogram.mlmodelc/model.mil",
                    "TextDecoder.mlmodelc/model.mil", "tokenizer/tokenizer.json", "tokenizer/tokenizer_config.json"
                ])
                let tokenizer = try await LocalWhisperTokenizer(directory: directory.appendingPathComponent("tokenizer"))
                try requireCurrent(token)
                let loaded = try await WhisperKit(WhisperKitConfig(
                    modelFolder: directory.path, tokenizerFolder: directory.appendingPathComponent("tokenizer"),
                    verbose: false, logLevel: .none, prewarm: false, load: false, download: false))
                loaded.tokenizer = tokenizer
                loaded.textDecoder.isModelMultilingual = true
                engine = loaded
                try await loaded.loadModels()
                try requireCurrent(token)
            }
            guard let engine else { throw LocalSpeechRuntimeError.unavailableRuntime }
            let result = try await engine.transcribe(audioArray: samples,
                decodeOptions: DecodingOptions(detectLanguage: true, skipSpecialTokens: true,
                    concurrentWorkerCount: 1, chunkingStrategy: .vad))
            try requireCurrent(token)
            return result.map(\.text).joined(separator: " ").trimmingCharacters(in: .whitespacesAndNewlines)
        } catch {
            await engine?.unloadModels(); engine = nil
            LocalSpeechInferenceOwnership.shared.release(ownerID)
            throw error
        }
        #else
        throw LocalSpeechRuntimeError.unavailableRuntime
        #endif
    }
    private func requireCurrent(_ token: UInt64) throws {
        try Task.checkCancellation()
        guard token == generation else { throw CancellationError() }
    }
    func unload() async {
        generation &+= 1
        // An in-flight native call owns its engine until it drains. Its stale
        // generation will unload before returning; do not unload beneath it.
        guard !running else { return }
        #if arch(arm64) && !os(watchOS)
        await engine?.unloadModels(); engine = nil
        LocalSpeechInferenceOwnership.shared.release(ownerID)
        #endif
    }
}
