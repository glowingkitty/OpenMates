// Developer lab only. CPU inference over verified January English assets.
// Specification: specifications/features/apple-local-model-lab/specification.yml
// Assertions: apple-local-model-lab.local-execution, apple-local-model-lab.serialized-cancellation
import Foundation
#if os(iOS) || os(macOS)
import CPocketTTS
#endif

enum PocketTTSError: Error, Sendable { case invalidInput, invalidAssets, invalidOutput, unavailable }

/// Bound both user input and each synchronous kernel. No truncation or language fallback.
enum PocketTTSInput {
    static let maximumBytes = 600
    static let sentenceBytes = 160
    static let maximumSentences = 4
    static func sentences(_ text: String) throws -> [String] {
        let text = text.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !text.isEmpty, text.utf8.count <= maximumBytes, !text.contains("\0") else { throw PocketTTSError.invalidInput }
        var result: [String] = [], current = ""
        for word in text.split(whereSeparator: { $0.isWhitespace }) {
            guard word.utf8.count <= sentenceBytes else { throw PocketTTSError.invalidInput }
            let next = current.isEmpty ? String(word) : current + " " + word
            if next.utf8.count > sentenceBytes { result.append(current); current = String(word) }
            else { current = next }
            if let last = word.last, ".!?".contains(last) { result.append(current); current = "" }
        }
        if !current.isEmpty { result.append(current) }
        guard !result.isEmpty, result.count <= maximumSentences else { throw PocketTTSError.invalidInput }
        return result
    }
}

struct PocketTTSAudio: Sendable {
    let wav: Data
    let duration: Double
}

protocol PocketTTSRuntime: Sendable {
    func synthesize(_ text: String, directory: URL,
                    progress: @escaping @Sendable (LocalModelRunPhase) -> Void) async throws -> PocketTTSAudio
}

/// The detached worker owns its opaque engine throughout creation, use and destruction.
/// Cancellation never frees a pointer while the native sentence kernel still owns it.
struct PocketTTSCPURuntime: PocketTTSRuntime {
    static var available: Bool {
        #if (os(iOS) || os(macOS)) && (arch(arm64) || arch(x86_64))
        true
        #else
        false
        #endif
    }
    func synthesize(_ text: String, directory: URL,
                    progress: @escaping @Sendable (LocalModelRunPhase) -> Void) async throws -> PocketTTSAudio {
        let sentences = try PocketTTSInput.sentences(text)
        let worker = Task.detached(priority: .utility) {
            try Task.checkCancellation()
            progress(.tokenizerPreparation)
            let required = ["model.safetensors", "tokenizer.model", "voices/alba.safetensors"]
            guard required.allSatisfy({ FileManager.default.fileExists(atPath: directory.appendingPathComponent($0).path) }) else {
                throw PocketTTSError.invalidAssets
            }
            #if os(iOS) || os(macOS)
            progress(.modelLoading)
            guard let engine = directory.path.withCString({ om_pocket_create($0) }) else { throw PocketTTSError.invalidAssets }
            defer { progress(.cleanup); om_pocket_destroy(engine) }
            try Task.checkCancellation()
            progress(.inference)
            var pcm = Data()
            for sentence in sentences {
                try Task.checkCancellation()
                guard let audio = sentence.withCString({ om_pocket_synthesize(engine, $0) }) else {
                    throw PocketTTSError.invalidOutput
                }
                let wav: Data
                do {
                    defer { om_pocket_audio_free(audio) }
                    let count = om_pocket_audio_count(audio)
                    guard count > 44, count <= 4 * 1024 * 1024,
                          let bytes = om_pocket_audio_bytes(audio) else { throw PocketTTSError.invalidOutput }
                    wav = Data(bytes: bytes, count: count)
                }
                try Task.checkCancellation()
                pcm.append(try PocketTTSWAV.pcm(wav))
                guard pcm.count <= 16 * 1024 * 1024 else { throw PocketTTSError.invalidOutput }
            }
            guard !pcm.isEmpty else { throw PocketTTSError.invalidOutput }
            return PocketTTSAudio(wav: PocketTTSWAV.encode(pcm), duration: Double(pcm.count) / 48_000)
            #else
            throw PocketTTSError.unavailable
            #endif
        }
        return try await withTaskCancellationHandler(operation: { try await worker.value }, onCancel: { worker.cancel() })
    }
}

/// Validate the runtime's mono 24 kHz PCM16 output before combining sentence WAVs.
enum PocketTTSWAV {
    static func pcm(_ wav: Data) throws -> Data {
        let bytes = [UInt8](wav)
        func u16(_ i: Int) -> UInt16 { UInt16(bytes[i]) | UInt16(bytes[i + 1]) << 8 }
        func u32(_ i: Int) -> UInt32 { UInt32(bytes[i]) | UInt32(bytes[i + 1]) << 8 | UInt32(bytes[i + 2]) << 16 | UInt32(bytes[i + 3]) << 24 }
        guard bytes.count >= 44, String(bytes: bytes[0..<4], encoding: .ascii) == "RIFF",
              String(bytes: bytes[8..<12], encoding: .ascii) == "WAVE", Int(u32(4)) + 8 == bytes.count else { throw PocketTTSError.invalidOutput }
        var offset = 12, validFormat = false, audio: Data?
        while offset + 8 <= bytes.count {
            let size = Int(u32(offset + 4)), start = offset + 8
            guard size <= bytes.count - start else { throw PocketTTSError.invalidOutput }
            let tag = String(bytes: bytes[offset..<offset + 4], encoding: .ascii)
            if tag == "fmt " {
                guard size >= 16, u16(start) == 1, u16(start + 2) == 1, u32(start + 4) == 24_000,
                      u32(start + 8) == 48_000, u16(start + 12) == 2, u16(start + 14) == 16 else { throw PocketTTSError.invalidOutput }
                validFormat = true
            } else if tag == "data" {
                guard audio == nil, size > 0, size.isMultiple(of: 2) else { throw PocketTTSError.invalidOutput }
                audio = Data(bytes[start..<start + size])
            }
            offset = start + size + (size % 2)
        }
        guard validFormat, let audio, offset == bytes.count else { throw PocketTTSError.invalidOutput }
        return audio
    }
    static func encode(_ pcm: Data) -> Data {
        var data = Data("RIFF".utf8)
        func append<T: FixedWidthInteger>(_ value: T) { var little = value.littleEndian; withUnsafeBytes(of: &little) { data.append(contentsOf: $0) } }
        append(UInt32(pcm.count + 36)); data.append(Data("WAVEfmt ".utf8)); append(UInt32(16))
        append(UInt16(1)); append(UInt16(1)); append(UInt32(24_000)); append(UInt32(48_000))
        append(UInt16(2)); append(UInt16(16)); data.append(Data("data".utf8)); append(UInt32(pcm.count)); data.append(pcm)
        return data
    }
}
