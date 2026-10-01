// Specification: specifications/features/assistant-response-speech/specification.yml
// Assertions: assistant-speech.surface.semantic-parity
import AVFoundation

// Web: assistantSpeechQueue.ts (1.25x playback with preserved pitch).
// Provider bytes stay in memory. AVAudioUnitTimePitch preserves the curated voice
// while changing tempo; the app's scoped runtime owns lifecycle cancellation.
@MainActor
final class AssistantSpeechAudioPlayer {
    private let engine = AVAudioEngine()
    private let node = AVAudioPlayerNode()
    private let tempo = AVAudioUnitTimePitch()
    private var pendingCue: AVAudioPlayer?
    private var configured = false
    private var generation = UUID()
    var onApproachingEnd: (@MainActor () -> Void)?
    private var prefetchTask: Task<Void, Never>?
    var onInterrupted: (@MainActor () -> Void)?
    private var interruptionObserver: NSObjectProtocol?
    init() {
        #if os(iOS)
        interruptionObserver = NotificationCenter.default.addObserver(forName: AVAudioSession.interruptionNotification,
            object: nil, queue: .main) { [weak self] notification in
                let type = notification.userInfo?[AVAudioSessionInterruptionTypeKey] as? UInt
                if type == AVAudioSession.InterruptionType.began.rawValue {
                    Task { @MainActor [weak self] in self?.onInterrupted?() }
                }
            }
        #endif
    }
    private var completion: CheckedContinuation<Void, Error>?
    func play(_ data: Data) async throws {
        try Task.checkCancellation()
        stop()
        let token = generation
        #if os(iOS)
        try AVAudioSession.sharedInstance().setCategory(.playback, mode: .default)
        try AVAudioSession.sharedInstance().setActive(true)
        #endif
        let buffer = try AssistantSpeechWaveform.buffer(data)
        if !configured {
            engine.attach(node); engine.attach(tempo)
            engine.connect(node, to: tempo, format: buffer.format)
            engine.connect(tempo, to: engine.mainMixerNode, format: nil)
            tempo.rate = 1.25; tempo.pitch = 0
            configured = true
        }
        try engine.start()
        try await withTaskCancellationHandler {
            try await withCheckedThrowingContinuation { continuation in
                completion = continuation
                guard !Task.isCancelled else { finish(CancellationError()); return }
                node.scheduleBuffer(buffer, completionCallbackType: .dataPlayedBack) { [weak self] _ in
                    Task { @MainActor in
                        guard let self, self.generation == token else { return }
                        self.finish()
                    }
                }
                node.play()
                prefetchTask = Task { [weak self] in
                    guard let self else { return }
                    while !Task.isCancelled, generation == token, completion != nil {
                        try? await Task.sleep(nanoseconds: 250_000_000)
                        guard !Task.isCancelled, node.isPlaying, let render = node.lastRenderTime,
                              let time = node.playerTime(forNodeTime: render) else { continue }
                        let remaining = (Double(buffer.frameLength) / buffer.format.sampleRate - Double(time.sampleTime) / time.sampleRate) / 1.25
                        if remaining <= 6 { onApproachingEnd?(); return }
                    }
                }
            }
        } onCancel: { Task { @MainActor [weak self] in if self?.generation == token { self?.stop() } } }
    }
    func startPendingCue() {
        guard pendingCue == nil,
              let url = Bundle.main.url(forResource: "assistant-speech-pending", withExtension: "wav"),
              let cue = try? AVAudioPlayer(contentsOf: url) else { return }
        cue.numberOfLoops = -1
        pendingCue = cue
        cue.play()
    }
    func stopPendingCue() { pendingCue?.stop(); pendingCue = nil }
    func pause() { node.pause() }
    func resume() {
        guard completion != nil else { return }
        do { if !engine.isRunning { try engine.start() }; node.play() }
        catch { finish(error) }
    }
    func stop() { prefetchTask?.cancel(); prefetchTask = nil; stopPendingCue(); generation = UUID(); node.stop(); engine.stop(); finish(CancellationError()) }
    private func finish(_ error: Error? = nil) {
        prefetchTask?.cancel(); prefetchTask = nil
        let pending = completion; completion = nil
        if let error { pending?.resume(throwing: error) } else { pending?.resume() }
    }
}
