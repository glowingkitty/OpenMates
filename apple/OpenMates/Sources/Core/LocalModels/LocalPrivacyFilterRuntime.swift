// Pinned local privacy-filter engine shared by foreground composer detection and diagnostics.
// Specification: specifications/features/pii-protection/specification.yml
// Assertion: pii.apple.enhanced-local-detection
// Model/decoder reference: https://github.com/openai/privacy-filter

import Foundation
#if arch(arm64) && !os(watchOS)
@preconcurrency import ExecuTorch
import Tokenizers
#endif

/// Intentionally exposes sanitized failure categories, never model paths or input text.
enum LocalPrivacyFilterError: Error, Sendable {
    case invalidRequest, unavailableRuntime, invalidAssets, invalidOutput, busy
}

struct LocalPrivacyFilterTimings: Equatable, Sendable {
    let loadSeconds: Double
    let tokenizeSeconds: Double
    let inferenceSeconds: Double
    let decodeSeconds: Double
    let totalSeconds: Double
    let usedWarmModel: Bool
}

/// One actor owns the non-thread-safe ExecuTorch Module. No network access is used.
actor LocalPrivacyFilterRuntime: LocalModelRuntime {
    private var generation: UInt64 = 0
    private var running = false
    private(set) var lastTimings: LocalPrivacyFilterTimings?
#if arch(arm64) && !os(watchOS)
    private struct Loaded {
        let directory: URL
        let module: Module
        let tokenizer: any Tokenizer
        let decoder: LocalPrivacyFilterDecoder
        let padID: Int64
    }
    private var loaded: Loaded?
#endif

    func unload() async {
        generation &+= 1
#if arch(arm64) && !os(watchOS)
        loaded = nil
#endif
    }

    func run(_ request: LocalModelTestRequest, directory: URL) async throws -> LocalModelTestOutput {
        do {
            return try await performRun(request, directory: directory)
        } catch is CancellationError {
            throw CancellationError()
        } catch let error as LocalPrivacyFilterError {
            throw error
        } catch {
            // Third-party tokenizer/runtime errors can embed paths or source text.
            // Only the sanitized category crosses into the test-page controller.
#if arch(arm64) && !os(watchOS)
            loaded = nil
#endif
            throw LocalPrivacyFilterError.invalidOutput
        }
    }

    private func performRun(_ request: LocalModelTestRequest, directory: URL) async throws -> LocalModelTestOutput {
        guard case let .detectPII(text) = request else { throw LocalPrivacyFilterError.invalidRequest }
        guard !running else { throw LocalPrivacyFilterError.busy }
        running = true
        defer { running = false }
        let runGeneration = generation
        try Task.checkCancellation()
#if arch(arm64) && !os(watchOS)
        let started = Date()
        let wasWarm = loaded?.directory == directory
        let loadStarted = Date()
        let assets = try await loadAssets(directory: directory, expectedGeneration: runGeneration)
        let loadSeconds = Date().timeIntervalSince(loadStarted)
        let tokenizeStarted = Date()
        let encoding = try assets.tokenizer.encodeWithMetadata(
            text: text, textPair: nil, addSpecialTokens: false, offsetUnit: .utf8
        )
        guard encoding.overflowEncodings.isEmpty, encoding.offsetSpans.count == encoding.tokenIds.count,
              encoding.attentionMask.allSatisfy({ $0 == 1 }) else {
            throw LocalPrivacyFilterError.invalidOutput
        }
        guard assets.tokenizer.decode(tokenIds: encoding.tokenIds, skipSpecialTokens: false) == text else {
            throw LocalPrivacyFilterError.invalidOutput
        }
        let tokenizeSeconds = Date().timeIntervalSince(tokenizeStarted)
        let inferenceStarted = Date()
        let ids = encoding.tokenIds
        if ids.isEmpty { return LocalModelTestOutput(piiSpans: []) }
        // Assemble emissions, not independently decoded labels: one global grammar
        // then closes spans coherently even when an entity crosses a window seam.
        var emissions = [Float](repeating: 0, count: ids.count * 33)
        var coverage = [Bool](repeating: false, count: ids.count)
        for window in LocalPrivacyFilterDecoder.windows(tokenCount: ids.count) {
            try checkActive(runGeneration)
            var inputIDs = [Int64](repeating: assets.padID, count: 256)
            var attention = [Int64](repeating: 0, count: 256)
            for local in 0..<window.count {
                inputIDs[local] = Int64(ids[window.start + local])
                attention[local] = 1
            }
            let outputs: [Value] = try assets.module.forward(
                Tensor<Int64>(inputIDs, shape: [1, 256]),
                Tensor<Int64>(attention, shape: [1, 256])
            )
            guard outputs.count == 1, let tensor: Tensor<Float> = outputs[0].tensor(),
                  tensor.shape == [1, 256, 33] else {
                throw LocalPrivacyFilterError.invalidOutput
            }
            let logits = tensor.scalars()
            guard logits.count == 256 * 33, logits.allSatisfy(\.isFinite) else {
                throw LocalPrivacyFilterError.invalidOutput
            }
            for local in window.writeRange {
                let global = window.start + local
                emissions.replaceSubrange((global * 33)..<((global + 1) * 33),
                                          with: logits[(local * 33)..<((local + 1) * 33)])
                coverage[global] = true
            }
            // Cancellation/unload takes effect between native forward passes. A CPU
            // kernel cannot be interrupted midway; do not report early completion.
            await Task.yield()
        }
        try checkActive(runGeneration)
        guard coverage.allSatisfy({ $0 }) else { throw LocalPrivacyFilterError.invalidOutput }
        let inferenceSeconds = Date().timeIntervalSince(inferenceStarted)
        let decodeStarted = Date()
        let path = try assets.decoder.decode(emissions)
        let offsets = encoding.offsetSpans.map { $0.start..<$0.end }
        let spans = try assets.decoder.spans(path: path, emissions: emissions, byteOffsets: offsets, text: text)
        try checkActive(runGeneration)
        lastTimings = LocalPrivacyFilterTimings(loadSeconds: loadSeconds, tokenizeSeconds: tokenizeSeconds,
            inferenceSeconds: inferenceSeconds, decodeSeconds: Date().timeIntervalSince(decodeStarted),
            totalSeconds: Date().timeIntervalSince(started), usedWarmModel: wasWarm)
        return LocalModelTestOutput(piiSpans: spans)
#else
        throw LocalPrivacyFilterError.unavailableRuntime
#endif
    }

    /// Warm only after an installed model and an active composer authorize local work.
    func warm(directory: URL) async throws -> Double {
        guard !running else { throw LocalPrivacyFilterError.busy }
        running = true
        defer { running = false }
        let started = Date()
#if arch(arm64) && !os(watchOS)
        do {
            _ = try await loadAssets(directory: directory, expectedGeneration: generation)
            return Date().timeIntervalSince(started)
        } catch is CancellationError { throw CancellationError() }
        catch let error as LocalPrivacyFilterError { throw error }
        catch { throw LocalPrivacyFilterError.invalidAssets }
#else
        throw LocalPrivacyFilterError.unavailableRuntime
#endif
    }

#if arch(arm64) && !os(watchOS)
    private func loadAssets(directory: URL, expectedGeneration: UInt64) async throws -> Loaded {
        try checkActive(expectedGeneration)
        if let cached = loaded, cached.directory == directory { return cached }
        let config = try LocalPrivacyFilterDecoder.configuration(directory: directory)
        let tokenizer = try await AutoTokenizer.from(directory: directory)
        try checkActive(expectedGeneration)
        let module = Module(filePath: directory.appendingPathComponent("model.pte").path, loadMode: .mmap)
        try module.load("forward")
        try checkActive(expectedGeneration)
        let assets = Loaded(directory: directory, module: module, tokenizer: tokenizer,
            decoder: config.decoder, padID: config.padID)
        loaded = assets
        return assets
    }
#endif

    private func checkActive(_ expectedGeneration: UInt64) throws {
        try Task.checkCancellation()
        guard generation == expectedGeneration else { throw CancellationError() }
    }
}

/// Pure decoder helpers remain testable without a checkpoint or inference runtime.
struct LocalPrivacyFilterDecoder: Sendable {
    static let categories = ["account_number", "private_address", "private_date", "private_email",
                             "private_person", "private_phone", "private_url", "secret"]
    static let labelNames = ["O"] + categories.flatMap { entity in
        ["B-", "I-", "E-", "S-"].map { $0 + entity }
    }
    static let biasKeys = ["transition_bias_background_stay", "transition_bias_background_to_start",
                           "transition_bias_end_to_background", "transition_bias_end_to_start",
                           "transition_bias_inside_to_continue", "transition_bias_inside_to_end"]
    let biases: [Float]

    init(biases: [Float] = [Float](repeating: 0, count: 6)) throws {
        guard biases.count == 6, biases.allSatisfy(\.isFinite) else {
            throw LocalPrivacyFilterError.invalidAssets
        }
        self.biases = biases
    }

    static func configuration(directory: URL) throws -> (decoder: Self, padID: Int64) {
        struct ModelConfig: Decodable { let id2label: [String: String]; let pad_token_id: Int64 }
        struct Calibration: Decodable {
            struct Point: Decodable { let biases: [String: Float] }
            let operating_points: [String: Point]
        }
        let decoder = JSONDecoder()
        let config = try decoder.decode(ModelConfig.self,
                                        from: Data(contentsOf: directory.appendingPathComponent("config.json")))
        guard config.id2label.count == 33, config.pad_token_id == 199999,
              labelNames.enumerated().allSatisfy({ config.id2label[String($0.offset)] == $0.element }) else {
            throw LocalPrivacyFilterError.invalidAssets
        }
        let calibration = try decoder.decode(Calibration.self,
            from: Data(contentsOf: directory.appendingPathComponent("viterbi_calibration.json")))
        guard let values = calibration.operating_points["default"]?.biases,
              Set(values.keys) == Set(biasKeys) else { throw LocalPrivacyFilterError.invalidAssets }
        let biases = try biasKeys.map { key -> Float in
            guard let value = values[key], value.isFinite else { throw LocalPrivacyFilterError.invalidAssets }
            return value
        }
        return (try Self(biases: biases), config.pad_token_id)
    }

    struct Window: Equatable, Sendable {
        let start: Int
        let count: Int
        let writeRange: Range<Int>
    }

    /// 50% overlap; adjacent ownership meets exactly at each midpoint, including
    /// short tails. No token can silently disappear from inference.
    static func windows(tokenCount: Int) -> [Window] {
        guard tokenCount > 0 else { return [] }
        var result: [Window] = []
        var start = 0
        while start < tokenCount {
            let count = min(256, tokenCount - start)
            let last = start + 256 >= tokenCount
            result.append(Window(start: start, count: count,
                                 writeRange: (start == 0 ? 0 : 64)..<(last ? count : 192)))
            if last { break }
            start += 128
        }
        return result
    }

    private func role(_ label: Int) -> Int { label == 0 ? 0 : (label - 1) % 4 + 1 }
    private func entity(_ label: Int) -> Int { label == 0 ? -1 : (label - 1) / 4 }

    private func transition(_ from: Int, _ to: Int) -> Float? {
        let previous = role(from), next = role(to)
        if previous == 0 || previous == 3 || previous == 4 {
            if next == 0 { return biases[previous == 0 ? 0 : 2] }
            if next == 1 || next == 4 { return biases[previous == 0 ? 1 : 3] }
        } else if entity(from) == entity(to) {
            if next == 2 { return biases[4] }
            if next == 3 { return biases[5] }
        }
        return nil
    }

    /// Same constrained start/transition/end scoring as OpenAI's CRF decoder.
    /// Raw logits are equivalent to log-softmax here: row constants cancel.
    func decode(_ emissions: [Float]) throws -> [Int] {
        guard emissions.count % 33 == 0, emissions.allSatisfy(\.isFinite) else {
            throw LocalPrivacyFilterError.invalidOutput
        }
        let count = emissions.count / 33
        guard count > 0 else { return [] }
        var scores = (0..<33).map { label in
            let tag = role(label)
            return tag == 0 || tag == 1 || tag == 4 ? Double(emissions[label]) : -Double.infinity
        }
        var back = [UInt8](repeating: 0, count: count * 33)
        // Precompute the sparse valid predecessor lists once per decode.
        let predecessors = (0..<33).map { next in
            (0..<33).compactMap { previous -> (Int, Double)? in
                transition(previous, next).map { (previous, Double($0)) }
            }
        }
        if count > 1 {
            for token in 1..<count {
                if token % 128 == 0 { try Task.checkCancellation() }
                var nextScores = [Double](repeating: -Double.infinity, count: 33)
                for next in 0..<33 {
                    var best = -Double.infinity
                    var previous = 0
                    for (candidate, bias) in predecessors[next] {
                        let score = scores[candidate] + bias
                        if score > best { best = score; previous = candidate }
                    }
                    nextScores[next] = best + Double(emissions[token * 33 + next])
                    back[token * 33 + next] = UInt8(previous)
                }
                scores = nextScores
            }
        }
        var last = 0
        for candidate in 1..<33 where role(candidate) == 3 || role(candidate) == 4 {
            if scores[candidate] > scores[last] { last = candidate }
        }
        guard scores[last].isFinite else { throw LocalPrivacyFilterError.invalidOutput }
        var path = [Int](repeating: 0, count: count)
        path[count - 1] = last
        if count > 1 {
            for token in stride(from: count - 1, through: 1, by: -1) {
                path[token - 1] = Int(back[token * 33 + path[token]])
            }
        }
        return path
    }

    func spans(path: [Int], emissions: [Float], byteOffsets: [Range<Int>], text: String) throws -> [PrivacyFilterModelSpan] {
        guard path.count == byteOffsets.count, emissions.count == path.count * 33,
              path.allSatisfy({ (0..<33).contains($0) }) else { throw LocalPrivacyFilterError.invalidOutput }
        let mapping = Self.utf16BoundaryMap(text)
        var result: [PrivacyFilterModelSpan] = []
        var token = 0
        while token < path.count {
            let category = entity(path[token])
            if category < 0 { token += 1; continue }
            let first = token
            token += 1
            while token < path.count, entity(path[token]) == category,
                  role(path[token]) != 1, role(path[token]) != 4 { token += 1 }
            let byteStart = byteOffsets[first].lowerBound
            let byteEnd = byteOffsets[token - 1].upperBound
            guard byteStart >= 0, byteEnd > byteStart, byteEnd < mapping.starts.count,
                  let label = PrivacyFilterModelLabel(rawValue: Self.categories[category]) else {
                throw LocalPrivacyFilterError.invalidOutput
            }
            let start = mapping.starts[byteStart], end = mapping.ends[byteEnd]
            guard end > start else { throw LocalPrivacyFilterError.invalidOutput }
            var probability = 0.0
            for index in first..<token {
                let row = emissions[(index * 33)..<((index + 1) * 33)]
                guard let maximum = row.max(), row.allSatisfy(\.isFinite) else {
                    throw LocalPrivacyFilterError.invalidOutput
                }
                let sum = row.reduce(0.0) { $0 + exp(Double($1 - maximum)) }
                probability += exp(Double(emissions[index * 33 + path[index]] - maximum)) / sum
            }
            result.append(PrivacyFilterModelSpan(label: label,
                range: NSRange(location: start, length: end - start), score: probability / Double(token - first)))
        }
        return result
    }

    /// Round byte-fragment boundaries outward to full Unicode scalars. Never
    /// decode a token prefix: BPE may split an emoji's UTF-8 bytes across tokens.
    static func utf16BoundaryMap(_ text: String) -> (starts: [Int], ends: [Int]) {
        var starts = [Int](repeating: 0, count: text.utf8.count + 1)
        var ends = starts
        var byte = 0, utf16 = 0
        for scalar in text.unicodeScalars {
            let value = scalar.value
            let width = value <= 0x7F ? 1 : (value <= 0x7FF ? 2 : (value <= 0xFFFF ? 3 : 4))
            let units = value <= 0xFFFF ? 1 : 2
            starts[byte] = utf16
            ends[byte] = utf16
            if width > 1 {
                for inner in 1..<width {
                    starts[byte + inner] = utf16
                    ends[byte + inner] = utf16 + units
                }
            }
            byte += width
            utf16 += units
            starts[byte] = utf16
            ends[byte] = utf16
        }
        return (starts, ends)
    }
}
