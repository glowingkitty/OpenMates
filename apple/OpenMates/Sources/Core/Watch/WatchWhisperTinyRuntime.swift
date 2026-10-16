// Explicitly pinned, local-only multilingual tiny runtime for the Watch experiment.
// Specification: specifications/features/apple-local-model-lab/specification.yml
// Assertions: apple-local-model-lab.watch-tiny, apple-local-model-lab.serialized-cancellation
#if os(watchOS)
import AVFoundation
import Foundation
@preconcurrency import WhisperKit

actor WatchWhisperTinyRuntime: WatchWhisperRuntime {
    private var engine: WhisperKit?
    func transcribe(_ audio: URL, directory: URL,
                    phase: @escaping @Sendable (WatchWhisperRunPhase) async -> Void) async throws -> WatchWhisperResult {
        guard engine == nil else { throw WatchWhisperLabError.inference }
        try Task.checkCancellation()
        await phase(.loading)
        do {
            let tokenizer = try await WatchTinyTokenizer(directory: directory.appendingPathComponent("tokenizer"))
            try Task.checkCancellation()
            let instance = try await WhisperKit(WhisperKitConfig(modelFolder: directory.path,
                tokenizerFolder: directory.appendingPathComponent("tokenizer"), verbose: false,
                logLevel: .none, prewarm: false, load: false, download: false))
            engine = instance
            instance.tokenizer = tokenizer
            instance.textDecoder.isModelMultilingual = true
            try await instance.loadModels()
            try Task.checkCancellation()
            await phase(.transcribing)
            let file = try AVAudioFile(forReading: audio)
            let seconds = Double(file.length) / file.processingFormat.sampleRate
            let results = try await instance.transcribe(audioPath: audio.path,
                decodeOptions: DecodingOptions(detectLanguage: true, skipSpecialTokens: true,
                    concurrentWorkerCount: 1, chunkingStrategy: .vad))
            try Task.checkCancellation()
            return WatchWhisperResult(text: results.map(\.text).joined(separator: " ")
                .trimmingCharacters(in: .whitespacesAndNewlines), audioSeconds: seconds)
        } catch is CancellationError { throw CancellationError() }
          catch { throw WatchWhisperLabError.inference }
    }
    func unload() async {
        await engine?.unloadModels()
        engine = nil
    }
}

private struct WatchTinyTokenizer: WhisperTokenizer, Sendable {
    let wrapped: TokenizerWrapper
    let specialTokens: SpecialTokens
    let allLanguageTokens: Set<Int>

    init(directory: URL) async throws {
        let wrapped = try await AutoTokenizerWrapper.from(modelFolder: directory)
        func id(_ spelling: String) throws -> Int {
            guard let value = wrapped.convertTokenToId(spelling) else { throw WatchWhisperLabError.assets }
            return value
        }
        guard let whitespace = wrapped.encode(text: " ", addSpecialTokens: false).first else {
            throw WatchWhisperLabError.assets
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
