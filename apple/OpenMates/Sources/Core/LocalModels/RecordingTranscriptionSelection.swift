// Explicit recording-only STT choice. Live calls continue sending direct audio to their broker.
// Specification: specifications/features/message-input/specification.yml
// Assertions: message-input.recording.lifecycle, message-input.privacy-context
import Foundation

enum RecordingTranscriptionPreference: String, CaseIterable, Sendable {
    case automatic, whisper, whistle, off
}

struct BundledSpeechModelDescriptor: Equatable, Sendable {
    let id = "whistle"
    let modelURL: URL?
    let includedSizeBytes: Int64 = 16_919_407
    let bundledSizeBytes: Int64 = 16_942_123 // Model and both Apache license notices.
    let documentsSizeBytes: Int64 = 0
    let canDownload = false
    let canDelete = false
    let reclaimsModelOnSessionEnd = false
    var isIncluded: Bool { modelURL != nil }
    static func appBundle() -> Self { .init(modelURL: try? WhistleBundledAsset.modelURL()) }
}

enum RecordingTranscriptionRoute: Equatable, Sendable {
    case online, disabled, whisper, whistle, unavailable(RecordingTranscriptionPreference)

    static func resolve(preference: RecordingTranscriptionPreference, whisperReady: Bool,
                        whistleIncluded: Bool, changing: Bool) -> Self {
        if preference == .off { return .disabled }
        if changing { return .unavailable(preference) }
        switch preference {
        case .automatic: return whisperReady ? .whisper : .online
        case .whisper: return whisperReady ? .whisper : .unavailable(.whisper)
        case .whistle: return whistleIncluded ? .whistle : .unavailable(.whistle)
        case .off: return .disabled
        }
    }

    var localModelIdentifier: String? {
        switch self {
        case .whisper, .unavailable(.whisper), .unavailable(.automatic): "whisper-large-v3-local"
        case .whistle, .unavailable(.whistle): "whistle-local"
        case .online, .disabled, .unavailable(.off): nil
        }
    }
}

struct RecordingTranscriptionSelection: Sendable {
    let route: RecordingTranscriptionRoute
    let runtime: (any LocalPCMTranscribing)?
    let preferenceGeneration: UUID
    var isDisabled: Bool { route == .disabled }
}

@MainActor
struct RecordingTranscriptionRuntimeFactory {
    let whisper: @MainActor (URL) -> any LocalPCMTranscribing
    let whistle: @MainActor (URL) -> any LocalPCMTranscribing
    static var live: Self {
        .init(whisper: { WhisperKitComposerRuntime(directory: $0) },
              whistle: { WhistlePCMRuntime(modelURL: $0) })
    }
}

/// An explicit unavailable local choice remains a local failure. It never grants a server route.
actor UnavailableRecordingTranscriber: LocalPCMTranscribing {
    func transcribe(_ samples: [Float]) throws -> String { throw LocalSpeechRuntimeError.unavailableRuntime }
    func unload() {}
}

/// Runtime registration ends only after the wrapped engine has actually drained.
actor RegisteredRecordingTranscriber: LocalPCMTranscribing {
    private let runtime: any LocalPCMTranscribing
    private let onEnd: @Sendable () async -> Void
    private var stop: Task<Void, Never>?
    init(runtime: any LocalPCMTranscribing, onEnd: @escaping @Sendable () async -> Void) {
        self.runtime = runtime; self.onEnd = onEnd
    }
    func transcribe(_ samples: [Float]) async throws -> String {
        guard stop == nil else { throw CancellationError() }
        let text = try await runtime.transcribe(samples)
        try Task.checkCancellation()
        guard stop == nil else { throw CancellationError() }
        return text
    }
    func unload() async {
        if let stop { await stop.value; return }
        let runtime = self.runtime, onEnd = self.onEnd
        let task = Task { await runtime.unload(); await onEnd() }
        stop = task
        await task.value
    }
}
