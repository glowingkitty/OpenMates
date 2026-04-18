// "Today's Inspiration" Shortcut — returns the current daily inspiration phrase.
// Uses the public /v1/default-inspirations endpoint (no auth required).
// Great for Siri ("What's today's inspiration?") and home screen automation.

import AppIntents
import Foundation

struct TodaysInspirationIntent: AppIntent {
    static let title: LocalizedStringResource = "Today's Inspiration"
    static let description: IntentDescription = "Get today's daily inspiration from OpenMates."
    static let openAppWhenRun = false

    func perform() async throws -> some IntentResult & ReturnsValue<String> {
        let baseURL: String = {
            #if DEBUG
            return "https://dev.openmates.org/api"
            #else
            return "https://api.openmates.org"
            #endif
        }()

        guard let url = URL(string: "\(baseURL)/v1/default-inspirations?lang=en") else {
            return .result(value: "Could not load today's inspiration.")
        }

        let (data, _) = try await URLSession.shared.data(from: url)
        let response = try JSONDecoder().decode(InspirationResponse.self, from: data)

        if let first = response.inspirations.first {
            var result = first.phrase
            if let videoTitle = first.video?.title {
                result += "\n\nWatch: \(videoTitle)"
            }
            return .result(value: result)
        }

        return .result(value: "No inspiration available today. Check back later!")
    }
}

private struct InspirationResponse: Decodable {
    let inspirations: [Item]

    struct Item: Decodable {
        let phrase: String
        let category: String
        let video: Video?

        struct Video: Decodable {
            let title: String?
            let channelName: String?

            enum CodingKeys: String, CodingKey {
                case title
                case channelName = "channel_name"
            }
        }

        enum CodingKeys: String, CodingKey {
            case phrase, category, video
        }
    }
}
