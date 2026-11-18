// ActivityKit attributes and hang-up intent for the call Live Activity.
// Targets: OpenMates (iOS) and OpenMatesWidget (iOS). Shared like OpenMatesLiveActivityAttributes.
// Web has no Live Activity; this keeps a call visible while the app is in the background
// (frontend/packages/ui/src/services/voiceCallBackground.ts covers the web lock-screen controls).
// Specification: specifications/features/video-call/specification.yml
// Assertions: video-call.apple.live-activity
import Foundation
#if os(iOS) && canImport(ActivityKit)
import ActivityKit
import AppIntents

@available(iOS 16.2, *)
struct NativeVoiceCallActivityAttributes: ActivityAttributes {
    struct ContentState: Codable, Hashable {
        /// "connecting" or "live". The timer runs from `startedAt` only while live.
        var phase: String
    }
    let callID: String
    let mateName: String
    /// Start of the call; drives `Text(timerInterval:)` so no per-second updates are needed.
    let startedAt: Date
}

/// Hang-up button of the Live Activity. A LiveActivityIntent runs in the app process.
@available(iOS 17.0, *)
struct NativeVoiceCallHangUpIntent: LiveActivityIntent {
    static let title: LocalizedStringResource = "voicecall.hangup"
    @Parameter(title: "call_id") var callID: String
    init() {}
    init(callID: String) { self.callID = callID }
    @MainActor func perform() async throws -> some IntentResult {
        #if !OPENMATES_WIDGET_EXTENSION
        await NativeVoiceCallLiveActivityHangUp.shared.hangUp(callID: callID)
        #endif
        return .result()
    }
}
#endif
