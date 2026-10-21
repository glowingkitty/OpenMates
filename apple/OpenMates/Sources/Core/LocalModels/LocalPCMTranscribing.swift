// Portable 16kHz mono speech seam shared by iOS/macOS and Watch.
// Specification: specifications/features/message-input/specification.yml
// Assertions: message-input.recording.lifecycle, message-input.privacy-context
import Foundation

/// Categories intentionally exclude source text, filenames and library diagnostics.
enum LocalSpeechRuntimeError: Error, Sendable {
    case invalidRequest, unavailableRuntime, invalidAssets, invalidOutput, busy
}

// Native speech work keeps its lease until its actual call drains.
// A Whistle session ends without reclaiming its process-lifetime model.
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
