// Shared data model for passing daily inspiration data between the main app
// and the WidgetKit extension via the App Group container (UserDefaults).
// Both targets encode/decode this struct independently — keep fields in sync
// with WidgetInspiration in OpenMatesWidget/OpenMatesWidget.swift.

import Foundation

struct WidgetInspirationData: Codable {
    let phrase: String
    let title: String
    let category: String
    let inspirationId: String
    let videoTitle: String?
    let channelName: String?
    let thumbnailUrl: String?
    let updatedAt: Date
}
