// Optional local speech inference for the settings model lab.
// Input and output stay in memory; model files must already be downloaded and verified.
import AVFoundation
import Foundation
#if arch(arm64) && !os(watchOS)
@preconcurrency import CoreML
@preconcurrency import WhisperKit
import FluidAudio
#endif

enum LocalModelTestRequest: Sendable {
    case transcribe(URL)
    case speak(String)
    case detectPII(String)
}

struct LocalModelTestOutput: Sendable {
    let text: String?
    let audioSamples: [Float]?
    let sampleRate: Int?
    let piiSpans: [PrivacyFilterModelSpan]
    let audioDurationSeconds: Double?

    init(text: String? = nil, audioSamples: [Float]? = nil, sampleRate: Int? = nil,
         piiSpans: [PrivacyFilterModelSpan] = [], audioDurationSeconds: Double? = nil) {
        self.text = text
        self.audioSamples = audioSamples
        self.sampleRate = sampleRate
        self.piiSpans = piiSpans
        self.audioDurationSeconds = audioDurationSeconds
    }
}

protocol LocalModelRuntime: Sendable {
    func run(_ request: LocalModelTestRequest, directory: URL) async throws -> LocalModelTestOutput
    func unload() async
}

/// Categories intentionally exclude source text, filenames and library diagnostics.
enum LocalSpeechRuntimeError: Error, Sendable {
    case invalidRequest, unavailableRuntime, invalidAssets, invalidOutput, busy, incompatibleOS
}

actor WhisperKitLocalRuntime: LocalModelRuntime {
    private var running = false
    private var generation: UInt64 = 0

    func unload() async { generation &+= 1 }

    func run(_ request: LocalModelTestRequest, directory: URL) async throws -> LocalModelTestOutput {
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
            let tokenizer = try await LocalWhisperTokenizer(directory: directory.appendingPathComponent("tokenizer"))
            try checkActive(token)
            // Install the local tokenizer before loading. WhisperKit’s tokenizer loader
            // otherwise falls back to a network fetch even when download is false.
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
                let results = try await engine.transcribe(audioPath: audioURL.path,
                    decodeOptions: DecodingOptions(detectLanguage: true, skipSpecialTokens: true,
                        concurrentWorkerCount: 1, chunkingStrategy: .vad))
                try checkActive(token)
                await engine.unloadModels()
                return LocalModelTestOutput(text: results.map(\.text).joined(separator: " ")
                    .trimmingCharacters(in: .whitespacesAndNewlines), audioDurationSeconds: duration)
            } catch {
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

actor KokoroLocalRuntime: LocalModelRuntime {
    private var running = false
    private var generation: UInt64 = 0

    func unload() async { generation &+= 1 }

    func run(_ request: LocalModelTestRequest, directory: URL) async throws -> LocalModelTestOutput {
        guard case let .speak(text) = request else { throw LocalSpeechRuntimeError.invalidRequest }
        guard !running else { throw LocalSpeechRuntimeError.busy }
        // FluidAudio 0.17.5 documents uncatchable MPSGraph/BNNS failures on OS 27.
        // https://github.com/FluidInference/FluidAudio/blob/v0.17.5/Sources/FluidAudio/TTS/KokoroAne/Pipeline/KokoroAneModelStore.swift
        guard ProcessInfo.processInfo.operatingSystemVersion.majorVersion < 27 else {
            throw LocalSpeechRuntimeError.incompatibleOS
        }
        running = true
        defer { running = false }
        let token = generation
        try Task.checkCancellation()
        #if arch(arm64) && !os(watchOS)
        do {
            // Prevent all existence/migration/voice fallbacks from downloading.
            let chain = directory.appendingPathComponent("ANE")
            let bundleNames = ModelNames.KokoroAne.requiredCoreMLModels.sorted()
            for name in bundleNames {
                let bundle = chain.appendingPathComponent(name)
                try SpeechAssetPreflight.require(bundle, ["coremldata.bin", "model.mil", "weights/weight.bin"])
                let mil = try Data(contentsOf: bundle.appendingPathComponent("model.mil"), options: .mappedIfSafe)
                guard mil.range(of: Data("[FlexibleShapeInformation =".utf8)) != nil else {
                    throw LocalSpeechRuntimeError.invalidAssets
                }
            }
            try SpeechAssetPreflight.require(directory, ["ANE/vocab.json", "ANE/af_heart.bin",
                "G2PEncoder.mlmodelc/model.mil", "G2PDecoder.mlmodelc/model.mil", "g2p_vocab.json", "us_lexicon_cache.json"])
            let frontend = try LocalEnglishSpeechFrontend(directory: directory)
            let phonemes = try frontend.phonemize(text)
            let vocabulary = try KokoroAneVocab.load(from: chain.appendingPathComponent("vocab.json"))
            // The library encoder silently drops unsupported IPA scalars. Surface them.
            guard phonemes.unicodeScalars.allSatisfy({ vocabulary.map[Character($0)] != nil }) else {
                throw LocalSpeechRuntimeError.invalidOutput
            }
            try checkActive(token)
            // Match FluidAudio’s repository layout entirely inside this verified model root.
            let staging = directory.appendingPathComponent(".runtime")
            let repo = staging.appendingPathComponent("kokoro-82m-coreml")
            try FileManager.default.createDirectory(at: repo, withIntermediateDirectories: true)
            let link = repo.appendingPathComponent("ANE")
            if FileManager.default.fileExists(atPath: link.path) {
                guard link.resolvingSymlinksInPath() == chain.resolvingSymlinksInPath() else {
                    throw LocalSpeechRuntimeError.invalidAssets
                }
            } else {
                try FileManager.default.createSymbolicLink(at: link, withDestinationURL: chain)
            }
            // The library’s ordinary English frontend hardcodes a global cache and
            // downloads missing assets. Use local G2P + IPA entry point instead.
            AppLogger.minimumLevel = .fault
            AppLogger.mirrorsToConsole = false
            let engine = KokoroAneManager(variant: .english, defaultVoice: "af_heart", directory: staging)
            do {
                let result = try await engine.synthesizeFromPhonemesDetailed(phonemes, voice: "af_heart")
                try checkActive(token)
                guard !result.samples.isEmpty, result.samples.allSatisfy(\.isFinite), result.sampleRate > 0 else {
                    throw LocalSpeechRuntimeError.invalidOutput
                }
                await engine.cleanup()
                return LocalModelTestOutput(audioSamples: result.samples, sampleRate: result.sampleRate,
                    audioDurationSeconds: Double(result.samples.count) / Double(result.sampleRate))
            } catch {
                await engine.cleanup()
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

/// Local BART-G2P decoding follows FluidAudio’s Apache-2.0 G2PModel tensor contract.
/// Keeps models scoped to one run instead of using its global downloading frontend.
private final class LocalEnglishSpeechFrontend {
    private struct Vocabulary: Decodable {
        let grapheme_to_id: [String: Int]
        let id_to_phoneme: [String: String]
        let bos_token_id: Int?
        let eos_token_id: Int?
        let unk_token_id: Int?
    }
    private struct Lexicon: Decodable {
        let lower: [String: [String]]
        let caseSensitive: [String: [String]]?
    }
    private let vocabulary: Vocabulary
    private let lexicon: Lexicon
    private let encoder: MLModel
    private let decoder: MLModel

    init(directory: URL) throws {
        vocabulary = try JSONDecoder().decode(Vocabulary.self, from: Data(contentsOf: directory.appendingPathComponent("g2p_vocab.json")))
        lexicon = try JSONDecoder().decode(Lexicon.self, from: Data(contentsOf: directory.appendingPathComponent("us_lexicon_cache.json")))
        let config = MLModelConfiguration()
        config.computeUnits = .cpuOnly
        encoder = try MLModel(contentsOf: directory.appendingPathComponent("G2PEncoder.mlmodelc"), configuration: config)
        decoder = try MLModel(contentsOf: directory.appendingPathComponent("G2PDecoder.mlmodelc"), configuration: config)
    }

    func phonemize(_ text: String) throws -> String {
        guard !text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else { throw LocalSpeechRuntimeError.invalidRequest }
        // The lab frontend accepts plain English and bounded integer numbers.
        // Reject unsupported formats before tokenization rather than silently omitting them.
        guard text.count <= 1000 else { throw LocalSpeechRuntimeError.invalidRequest }
        let allowed = CharacterSet(charactersIn: "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789 \t\r\n.,!?;:’\u{27}-")
        guard text.unicodeScalars.allSatisfy({ allowed.contains($0) }) else { throw LocalSpeechRuntimeError.invalidRequest }
        let unsupported = try NSRegularExpression(pattern: "[.,:][0-9]|-[[:space:]]*[0-9]|(^|[[:space:]])0[0-9]|[A-Za-z][0-9]|[0-9][A-Za-z]|[0-9]{10,}|[A-Za-z]{65,}")
        guard unsupported.firstMatch(in: text, range: NSRange(text.startIndex..., in: text)) == nil else {
            throw LocalSpeechRuntimeError.invalidRequest
        }
        // Currency signs, decimal/time notation and non-English Unicode fail visibly.

        let normalized = text.replacingOccurrences(of: "’", with: "'")
        let regex = try NSRegularExpression(pattern: "[A-Za-z]+(?:'[A-Za-z]+)*|[0-9]+|[.,!?;:]")
        let formatter = NumberFormatter(); formatter.locale = Locale(identifier: "en_US"); formatter.numberStyle = .spellOut
        var output: [String] = []
        for match in regex.matches(in: normalized, range: NSRange(normalized.startIndex..., in: normalized)) {
            try Task.checkCancellation()
            guard let range = Range(match.range, in: normalized) else { continue }
            let word = String(normalized[range])
            if word.count == 1, let char = word.first, ".,!?;:".contains(char) {
                if !output.isEmpty { output[output.count - 1] += word }
                continue
            }
            if let number = Int64(word), let expanded = formatter.string(from: NSNumber(value: number)) {
                for part in expanded.split(whereSeparator: { !$0.isLetter }) { output.append(try resolve(String(part))) }
            } else { output.append(try resolve(word)) }
        }
        let phonemes = output.joined(separator: " ")
        // Kokoro has a finite phoneme context. Reject overlong input rather than truncate.
        guard !phonemes.isEmpty, phonemes.unicodeScalars.count <= 500 else { throw LocalSpeechRuntimeError.invalidRequest }
        return phonemes
    }

    private func resolve(_ word: String) throws -> String {
        if let known = lexicon.caseSensitive?[word] ?? lexicon.lower[word.lowercased()], !known.isEmpty { return known.joined() }
        let bos = vocabulary.bos_token_id ?? 1, eos = vocabulary.eos_token_id ?? 2, unk = vocabulary.unk_token_id ?? 3
        let inputIDs = [bos] + word.lowercased().map { vocabulary.grapheme_to_id[String($0)] ?? unk } + [eos]
        let input = try MLMultiArray(shape: [1, NSNumber(value: inputIDs.count)], dataType: .int32)
        for (i, id) in inputIDs.enumerated() { input[i] = NSNumber(value: id) }
        let encoded = try encoder.prediction(from: MLDictionaryFeatureProvider(dictionary: ["input_ids": input]))
        guard let hidden = encoded.featureValue(for: "encoder_hidden_states")?.multiArrayValue else { throw LocalSpeechRuntimeError.invalidOutput }
        var ids = [bos]
        var ended = false
        for _ in 0..<64 {
            try Task.checkCancellation()
            let n = ids.count
            let tokens = try MLMultiArray(shape: [1, NSNumber(value: n)], dataType: .int32)
            let positions = try MLMultiArray(shape: [1, NSNumber(value: n)], dataType: .int32)
            let mask = try MLMultiArray(shape: [1, NSNumber(value: n), NSNumber(value: n)], dataType: .float32)
            for i in 0..<n {
                tokens[i] = NSNumber(value: ids[i]); positions[i] = NSNumber(value: i + 2)
                for j in 0..<n { mask[[0, i, j] as [NSNumber]] = NSNumber(value: j > i ? -10000 : 0) }
            }
            let decoded = try decoder.prediction(from: MLDictionaryFeatureProvider(dictionary: [
                "decoder_input_ids": tokens, "encoder_hidden_states": hidden, "position_ids": positions, "causal_mask": mask]))
            guard let logits = decoded.featureValue(for: "logits")?.multiArrayValue,
                  logits.shape.count == 3, let last = logits.shape.last else { throw LocalSpeechRuntimeError.invalidOutput }
            var best = 0, value = -Float.infinity
            for index in 0..<last.intValue {
                let score = logits[[0, n - 1, index] as [NSNumber]].floatValue
                if score > value { best = index; value = score }
            }
            if best == eos { ended = true; break }
            ids.append(best)
        }
        guard ended else { throw LocalSpeechRuntimeError.invalidOutput }
        let result = ids.filter { ![0, bos, eos, unk].contains($0) }.compactMap { vocabulary.id_to_phoneme[String($0)] }.joined()
        guard !result.isEmpty else { throw LocalSpeechRuntimeError.invalidOutput }
        return result
    }
}
#endif
