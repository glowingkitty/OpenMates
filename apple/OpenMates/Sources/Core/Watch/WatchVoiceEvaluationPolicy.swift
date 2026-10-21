// Volatile development diagnostic admission, separate from product route qualification.
// Specification: specifications/features/apple-watch/specification.yml
// Assertions: apple-watch.chats.input-actions
// Specification: specifications/features/video-call/specification.yml
// Assertions: video-call.privacy, video-call.audio.single-owner
import Foundation

struct WatchVoiceEvaluationBinding: Equatable, Sendable {
    let accountID: String
    let profile: ServerProfile
    let accountGeneration: UInt64
    let chatID: String
    let attemptID: UUID
    let routeFingerprint: String
}

/// Pure policy tested independently. Constructing a policy cannot issue the
/// physical-device lease; its initializer is private to the actual issuer.
struct WatchVoiceEvaluationPolicy {
    private enum Phase: Equatable { case offered, running, revoked }
    private var phase = Phase.offered
    let binding: WatchVoiceEvaluationBinding
    private let offeredUntil: TimeInterval
    private var runningUntil: TimeInterval?
    init(binding: WatchVoiceEvaluationBinding, observedAt: TimeInterval) {
        self.binding = binding; offeredUntil = observedAt + 30
    }
    private func matches(_ current: WatchVoiceEvaluationBinding) -> Bool {
        current == binding && current.profile == .development && !current.accountID.isEmpty &&
            UUID(uuidString: current.chatID) != nil && !current.routeFingerprint.isEmpty
    }
    mutating func consume(current: WatchVoiceEvaluationBinding, now: TimeInterval) throws {
        guard phase == .offered, now < offeredUntil, matches(current) else {
            phase = .revoked; throw NativeVoiceCallError.unsupportedTransport
        }
        phase = .running; runningUntil = now + 60
    }
    func permitsExecution(current: WatchVoiceEvaluationBinding, now: TimeInterval) -> Bool {
        phase == .running && now < (runningUntil ?? 0) && matches(current)
    }
    func permitsStart(current: WatchVoiceEvaluationBinding, now: TimeInterval) -> Bool {
        phase == .offered && now < offeredUntil && matches(current)
    }
    mutating func revoke() { phase = .revoked }
}
