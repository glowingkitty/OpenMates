import AVFoundation

// Real provider audio data playback. The runtime owns account/turn guards before
// calling this adapter. stop() unblocks any pending completion deterministically.
@MainActor
final class AssistantSpeechAudioPlayer: NSObject {
    private var player: AVAudioPlayer?
    private var playbackDelegate: AssistantSpeechPlaybackDelegate?
    private var generation = UUID()
    private var completion: CheckedContinuation<Void, Error>?
    func play(_ data: Data) async throws {
        try Task.checkCancellation()
        stop()
        let token = generation
        #if os(iOS)
        try AVAudioSession.sharedInstance().setCategory(.playback, mode: .default)
        try AVAudioSession.sharedInstance().setActive(true)
        #endif
        let next = try AVAudioPlayer(data: data)
        let delegate = AssistantSpeechPlaybackDelegate(token: token) { [weak self] token, error in
            guard let self, self.generation == token else { return }
            self.finish(error)
        }
        playbackDelegate = delegate
        next.delegate = delegate; player = next
        try await withTaskCancellationHandler {
            try await withCheckedThrowingContinuation { continuation in
                completion = continuation
                guard !Task.isCancelled else { finish(CancellationError()); return }
                next.prepareToPlay()
                if !next.play() { finish(CocoaError(.fileReadCorruptFile)) }
            }
        } onCancel: { Task { @MainActor [weak self] in if self?.generation == token { self?.stop() } } }
    }
    func stop() { generation = UUID(); player?.stop(); finish(CancellationError()) }
    private func finish(_ error: Error? = nil) {
        let pending = completion; completion = nil; player = nil; playbackDelegate = nil
        if let error { pending?.resume(throwing: error) } else { pending?.resume() }
    }
}

// AVFoundation may invoke delegates outside the main actor. Transfer only the
// immutable playback token and outcome, never its non-Sendable AVAudioPlayer.
// A token also rejects a delayed callback after another clip has started.
private final class AssistantSpeechPlaybackDelegate: NSObject, AVAudioPlayerDelegate {
    let token: UUID
    let completed: @MainActor @Sendable (UUID, Error?) -> Void
    init(token: UUID, completed: @escaping @MainActor @Sendable (UUID, Error?) -> Void) {
        self.token = token; self.completed = completed
    }
    func audioPlayerDidFinishPlaying(_ player: AVAudioPlayer, successfully flag: Bool) {
        let token = token, completed = completed
        Task { @MainActor in completed(token, flag ? nil : CocoaError(.fileReadCorruptFile)) }
    }
    func audioPlayerDecodeErrorDidOccur(_ player: AVAudioPlayer, error: Error?) {
        let token = token, completed = completed
        Task { @MainActor in completed(token, error ?? CocoaError(.fileReadCorruptFile)) }
    }
}
