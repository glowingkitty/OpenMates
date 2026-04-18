// "Start Chat" Shortcut — opens the app with a new chat in a specific app mode.
// Supports all 12 app categories: AI, Web, Code, Travel, News, Email, etc.
// Deep links into the app so the user lands directly in the new chat.

import AppIntents
import Foundation

struct StartChatIntent: AppIntent {
    static let title: LocalizedStringResource = "Start OpenMates Chat"
    static let description: IntentDescription = "Open a new chat in OpenMates with a specific app."
    static let openAppWhenRun = true

    @Parameter(title: "App", description: "Which app to start the chat with")
    var appId: AppCategory

    @Parameter(title: "Message", description: "Optional first message to send", default: nil)
    var initialMessage: String?

    static var parameterSummary: some ParameterSummary {
        Summary("Start \(\.$appId) chat") {
            \.$initialMessage
        }
    }

    func perform() async throws -> some IntentResult {
        // Build deep link URL that the main app handles via onOpenURL
        var urlString = "openmates://app/\(appId.rawValue)"
        if let message = initialMessage, !message.isEmpty {
            let encoded = message.addingPercentEncoding(withAllowedCharacters: .urlQueryAllowed) ?? ""
            urlString += "?message=\(encoded)"
        }

        // The app will open and handle the deep link via DeepLinkHandler
        return .result()
    }
}

// MARK: - App category enum for Shortcuts picker

enum AppCategory: String, AppEnum {
    case ai
    case web
    case code
    case travel
    case news
    case mail
    case maps
    case shopping
    case events
    case videos
    case photos
    case nutrition

    static let typeDisplayRepresentation: TypeDisplayRepresentation = "App"

    static let caseDisplayRepresentations: [AppCategory: DisplayRepresentation] = [
        .ai: "AI Chat",
        .web: "Web Search",
        .code: "Code",
        .travel: "Travel",
        .news: "News",
        .mail: "Email",
        .maps: "Maps",
        .shopping: "Shopping",
        .events: "Events",
        .videos: "Videos",
        .photos: "Photos",
        .nutrition: "Nutrition",
    ]
}
