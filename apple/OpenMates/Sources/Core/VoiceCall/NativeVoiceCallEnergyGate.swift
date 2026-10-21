// Web source: frontend/packages/ui/src/services/voiceCallAudioGate.ts
// Specification: specifications/features/video-call/specification.yml
// Assertions: video-call.audio.automatic-idle, video-call.audio.background-detection
import Foundation

/// A deterministic energy detector, not a language/speech model. Its calibrated
/// physical-device behavior still requires proof; quiet input is never uploaded
/// to preserve a socket or advertised as zero provider cost.
struct NativeVoiceCallEnergyGate: Sendable {
    enum Decision: Sendable { case upload(Data), enteredIdle, idle, resumed(Data) }
    static let algorithm = "pcm16-rms-v1"
    static let threshold: Float = 0.012
    private(set) var idle = false
    private var quietSamples = 0
    private var preRoll = Data()
    private let preRollBytes = 16_000 * 2 / 5 // 200ms, memory only

    mutating func reset() { idle = false; quietSamples = 0; preRoll.removeAll(keepingCapacity: true) }
    mutating func process(_ data: Data) throws -> Decision {
        let samples = try NativeVoiceCallPCM.decode(data)
        guard !samples.isEmpty else { return .idle }
        let energy = sqrt(samples.reduce(Float.zero) { $0 + $1 * $1 } / Float(samples.count))
        let speechEnergy = energy >= Self.threshold
        if idle {
            preRoll.append(data)
            if preRoll.count > preRollBytes { preRoll.removeFirst(preRoll.count - preRollBytes) }
            if speechEnergy {
                idle = false; quietSamples = 0
                let replay = preRoll
                preRoll.removeAll(keepingCapacity: true)
                return .resumed(replay)
            }
            return .idle
        }
        quietSamples = speechEnergy ? 0 : quietSamples + samples.count
        if quietSamples >= 16_000 * 5 {
            idle = true
            preRoll = Data(data.suffix(preRollBytes))
            return .enteredIdle
        }
        return .upload(data)
    }
}
