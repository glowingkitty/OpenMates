// App-side lifecycle of the active-call Live Activity (Lock Screen and Dynamic Island).
// Target: OpenMates iOS. Start when the call goes live, end on hang-up or call end.
// Specification: specifications/features/video-call/specification.yml
// Assertions: video-call.apple.live-activity, video-call.audio.background-resume
import Foundation
#if os(iOS)
// ActivityKit's Activity is not annotated Sendable; handles stay on this MainActor object.
@preconcurrency import ActivityKit

/// Receives the Live Activity hang-up tap. The controller owner installs `handler`.
@MainActor
final class NativeVoiceCallLiveActivityHangUp {
    static let shared = NativeVoiceCallLiveActivityHangUp()
    /// Set to a closure that ends the call with the given id (see handback snippet).
    var handler: (@MainActor (String) async -> Void)?
    func hangUp(callID: String) async { await handler?(callID) }
}

@MainActor
final class NativeVoiceCallLiveActivity {
    private var activity: Activity<NativeVoiceCallActivityAttributes>?

    /// Start (or replace) the activity for a call. No-op when Live Activities are disabled.
    func start(callID: String, mateName: String, startedAt: Date = Date(), live: Bool) async {
        guard #available(iOS 16.2, *), ActivityAuthorizationInfo().areActivitiesEnabled else { return }
        if activity?.attributes.callID == callID { await update(live: live); return }
        await end()
        let attributes = NativeVoiceCallActivityAttributes(callID: callID, mateName: mateName, startedAt: startedAt)
        let content = ActivityContent(state: NativeVoiceCallActivityAttributes.ContentState(phase: live ? "live" : "connecting"),
                                      staleDate: nil)
        activity = try? Activity.request(attributes: attributes, content: content, pushType: nil)
    }

    /// Switch between connecting and live.
    func update(live: Bool) async {
        guard let activity else { return }
        let content = ActivityContent(state: NativeVoiceCallActivityAttributes.ContentState(phase: live ? "live" : "connecting"),
                                      staleDate: nil)
        await activity.update(content)
    }

    /// End immediately; the activity disappears from Lock Screen and Dynamic Island.
    func end() async {
        guard let current = activity else { return }
        activity = nil
        await current.end(nil, dismissalPolicy: .immediate)
    }
}
#endif
