// Web source: frontend/packages/ui/src/services/voiceCall.ts, voiceCallAudioGate.ts
// Specification: specifications/features/video-call/specification.yml
// Assertions: video-call.audio.single-owner, video-call.audio.startup-buffer,
// video-call.audio.automatic-idle, video-call.audio.background-detection

import Foundation

/// Production adapters reuse the app audio reservation, AVAudioEngine converter,
/// and PCM player. Capture produces ordered signed little-endian PCM16 mono 16k;
/// playback consumes PCM16 mono 24k. No call-audio file or STT duplicate is made.
/// reserve must stop/drain ordinary assistant speech and reject recorder overlap.
protocol NativeVoiceCallAudio: Sendable {
    func reserve(scope: NativeVoiceCallScope) async throws
    func start(input: @escaping @Sendable (Data) async -> Void,
               failure: @escaping @Sendable (NativeVoiceCallError) async -> Void) async throws
    func setMicrophoneEnabled(_ enabled: Bool) async
    /// Network-input idle is separate from manual mute so local detection can
    /// resume from real speech without uploading silence.
    func setInputIdle(_ idle: Bool) async
    func play(_ pcm16: Data, sampleRate: Int) async throws
    func interruptPlayback() async
    /// Stops capture/player/detector, drains callbacks, releases only this lease.
    func stop() async
}

extension NativeVoiceCallAudio {
    func setInputIdle(_ idle: Bool) async { }
}

/// Reusable converter for adapters already owning an AVAudioConverter. No
/// resampling is hidden here; callers must provide true 16k/24k mono samples.
enum NativeVoiceCallPCM {
    static func encode(_ samples: [Float]) -> Data {
        var output = Data(capacity: samples.count * 2)
        for sample in samples {
            let safe = sample.isFinite ? min(1, max(-1, sample)) : 0
            let integer = Int16(max(-32768, min(32767, Int((safe * 32768).rounded()))))
            let word = UInt16(bitPattern: integer)
            output.append(UInt8(truncatingIfNeeded: word))
            output.append(UInt8(truncatingIfNeeded: word >> 8))
        }
        return output
    }

    static func decode(_ data: Data) throws -> [Float] {
        guard data.count % 2 == 0 else { throw NativeVoiceCallError.invalidResponse }
        let bytes = Array(data)
        return stride(from: 0, to: bytes.count, by: 2).map {
            Float(Int16(bitPattern: UInt16(bytes[$0]) | UInt16(bytes[$0 + 1]) << 8)) / 32768
        }
    }
}

/// Only a successfully warmed, verified detector may request automatic idle.
/// Detector loading/failure returns continuous streaming; manual mute always wins.
struct NativeVoiceCallInputGate: Sendable {
    enum Detector: Sendable { case loading, ready, failed }
    private(set) var detector: Detector = .loading
    private(set) var muted = false
    private(set) var idle = false
    private var silenceSince: TimeInterval?

    mutating func setDetector(_ value: Detector) {
        detector = value
        if case .ready = value { return }
        idle = false
        silenceSince = nil
    }

    mutating func setMuted(_ value: Bool) {
        muted = value
        silenceSince = nil
        if value { idle = false }
    }

    /// A source using this helper retains its bounded pre-speech PCM separately
    /// and replays it in order before current speech when idle changes to false.
    mutating func observe(speech: Bool, at: TimeInterval) -> Bool {
        guard !muted, case .ready = detector else { return false }
        if speech { silenceSince = nil; idle = false }
        else {
            if silenceSince == nil { silenceSince = at }
            if at - (silenceSince ?? at) >= 5 { idle = true }
        }
        return idle
    }
}
