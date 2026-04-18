// Handoff manager — advertises the user's current chat as an NSUserActivity
// so they can continue on another Apple device (iPhone ↔ iPad ↔ Mac).
// Uses Apple's Continuity framework: the activity type is registered in
// Info.plist under NSUserActivityTypes, and the receiving device picks it up
// via onContinueUserActivity() in MainAppView.

import Foundation

#if canImport(UIKit)
import UIKit
#elseif canImport(AppKit)
import AppKit
#endif

@MainActor
final class HandoffManager: ObservableObject {
    /// Activity type constants — must match NSUserActivityTypes in Info.plist
    static let viewChatActivityType = "org.openmates.app.viewChat"
    static let composeChatActivityType = "org.openmates.app.composeChat"
    static let browseChatsActivityType = "org.openmates.app.browseChats"

    private var currentActivity: NSUserActivity?

    // MARK: - Advertise viewing a specific chat

    /// Call when the user navigates to a chat. Advertises the chat for Handoff
    /// so another device shows the OpenMates icon in the dock/app switcher.
    func advertiseChatViewing(chatId: String, chatTitle: String?) {
        let activity = NSUserActivity(activityType: Self.viewChatActivityType)
        activity.title = chatTitle ?? "OpenMates Chat"
        activity.userInfo = ["chatId": chatId]
        activity.isEligibleForHandoff = true
        activity.isEligibleForSearch = true
        activity.isEligibleForPrediction = true

        // Universal link fallback for devices without the app
        if let url = URL(string: "https://openmates.org/#chat-id=\(chatId)") {
            activity.webpageURL = url
        }

        // Content attribute set for Spotlight integration
        let attributes = activity.contentAttributeSet
            ?? CoreSpotlight.CSSearchableItemAttributeSet(contentType: .text)
        attributes.title = chatTitle ?? "OpenMates Chat"
        attributes.contentDescription = "Continue this conversation on another device"
        activity.contentAttributeSet = attributes

        activity.becomeCurrent()
        currentActivity = activity
    }

    // MARK: - Advertise browsing the chat list

    func advertiseChatBrowsing() {
        let activity = NSUserActivity(activityType: Self.browseChatsActivityType)
        activity.title = "Browse OpenMates Chats"
        activity.isEligibleForHandoff = true
        activity.becomeCurrent()
        currentActivity = activity
    }

    // MARK: - Stop advertising

    func stopAdvertising() {
        currentActivity?.invalidate()
        currentActivity = nil
    }
}

import CoreSpotlight
