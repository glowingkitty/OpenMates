// Shared app/widget payload for model downloads and upcoming memories.
// Private URLs, chat IDs and encryption material never cross this boundary.
// Specification: specifications/features/apple-live-activities/specification.yml
// Assertions: apple-live-activities.download.progress, apple-live-activities.memories.upcoming
import Foundation
#if os(iOS) && canImport(ActivityKit)
import ActivityKit

@available(iOS 16.2, *)
struct OpenMatesLiveActivityAttributes: ActivityAttributes {
    struct ContentState: Codable, Hashable {
        let title: String
        let detail: String
        let phase: String
        let progress: Double
        let completedBytes: Int64
        let totalBytes: Int64
        var itemCount: Int
        var startsAt: Date?
        var expiresAt: Date?
        var staleDetail: String? = nil
        /// Optional for decoding activities created by an earlier app version.
        var upcomingPages: [UpcomingMemoryActivityPage]? = nil
        var selectedUpcomingIdentity: String? = nil
    }
    /// Stable opaque app-owned key; never a raw user, memory or embed identifier.
    let identity: String
    let kind: String
}
#endif
