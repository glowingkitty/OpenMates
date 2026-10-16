// Upgrade cleanup for the retired running-chat Live Activity feature.
// Downloads and upcoming memories retain their ordinary ActivityKit lifecycle.
import Foundation
#if os(iOS)
@preconcurrency import ActivityKit
#endif

@MainActor
enum LegacyProcessingActivityRetirement {
    private static var task: Task<Void, Never>?

    static func retire() {
        UserDefaults.standard.removeObject(forKey: "openmates.processing-live.owner")
        UserDefaults.standard.removeObject(forKey: "openmates.processing-live.runs")
        OpenMatesSharedEnvironment.defaults.removeObject(forKey: "openmates.processing-activity.registration.v1")
        #if os(iOS)
        guard #available(iOS 16.2, *), task == nil else { return }
        task = Task { @MainActor in
            defer { task = nil }
            for activity in Activity<OpenMatesLiveActivityAttributes>.activities
                where activity.attributes.kind == "processing" || activity.attributes.kind == "processing-remote" {
                await activity.end(nil, dismissalPolicy: .immediate)
            }
        }
        #endif
    }
}
