// Web source: frontend/packages/ui/src/components/VoiceCallWaveform.svelte (live-call level bars)
// Specification: specifications/features/video-call/specification.yml
// Assertions: video-call.chat.activity-status
import Foundation

/// Platform audio UI only: turns the levels of buffers that already flow through the call's
/// single audio engine (microphone tap, assistant playback tap) into a bounded, throttled
/// bar history. No second engine or session, no protocol or policy logic.
final class NativeVoiceCallLevelMeter: @unchecked Sendable {
    enum Source: Sendable { case microphone, playback }
    static let barCount = 48
    private let lock = NSLock()
    private let interval: TimeInterval
    private let now: @Sendable () -> TimeInterval
    private let sink: @Sendable ([Float]) -> Void
    private var history: [Float] = []
    private var pending: Float = 0
    private var lastEmit: TimeInterval?

    /// `interval` 0.05 s is the ~20 Hz cap so SwiftUI is not invalidated per buffer.
    init(interval: TimeInterval = 0.05,
         now: @escaping @Sendable () -> TimeInterval = { ProcessInfo.processInfo.systemUptime },
         sink: @escaping @Sendable ([Float]) -> Void) {
        self.interval = interval; self.now = now; self.sink = sink
    }

    /// RMS of one buffer scaled to 0...1 for speech; silence and non-finite input give 0.
    static func level(of samples: UnsafeBufferPointer<Float>) -> Float {
        guard !samples.isEmpty else { return 0 }
        var sum: Float = 0
        for sample in samples where sample.isFinite { sum += sample * sample }
        let rms = (sum / Float(samples.count)).squareRoot()
        return rms.isFinite ? min(1, max(0, rms * 4)) : 0
    }

    /// Called from audio threads. Levels between emissions coalesce to their maximum.
    func submit(_ source: Source, level: Float) {
        let value = level.isFinite ? min(1, max(0, level)) : 0
        lock.lock()
        pending = max(pending, value)
        let time = now()
        guard lastEmit.map({ time - $0 >= interval }) ?? true else { lock.unlock(); return }
        lastEmit = time
        history.append(pending); pending = 0
        if history.count > Self.barCount { history.removeFirst(history.count - Self.barCount) }
        let snapshot = history
        lock.unlock()
        sink(snapshot)
    }

    func reset() {
        lock.lock(); history = []; pending = 0; lastEmit = nil; lock.unlock()
    }
}
