// "Search Places" Shortcut — finds places and locations via REST API.
// Chain with Apple Maps for navigation.

import AppIntents
import Foundation

struct MapsSearchIntent: AppIntent {
    static let title: LocalizedStringResource = "Search Places"
    static let description: IntentDescription = "Search for places, restaurants, and points of interest."
    static let openAppWhenRun = false

    @Parameter(title: "Query", description: "What place to search for")
    var query: String

    @Parameter(title: "Near", description: "Location to search near", default: nil)
    var location: String?

    static var parameterSummary: some ParameterSummary {
        Summary("Search places for \(\.$query)") {
            \.$location
        }
    }

    func perform() async throws -> some IntentResult & ReturnsValue<String> {
        var request: [String: Any] = ["id": 1, "query": query]
        if let location { request["location"] = location }

        let body: [String: Any] = ["requests": [request]]
        let response = try await SkillExecutor.execute(
            appId: "maps", skillId: "search", body: body
        )
        return .result(value: SkillFormatter.formatResults(response, type: "places"))
    }
}
