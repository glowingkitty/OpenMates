// "Search Images" Shortcut — finds images via REST API.

import AppIntents
import Foundation

struct ImageSearchIntent: AppIntent {
    static let title: LocalizedStringResource = "Search Images"
    static let description: IntentDescription = "Search for images on a topic."
    static let openAppWhenRun = false

    @Parameter(title: "Query", description: "What images to search for")
    var query: String

    @Parameter(title: "Max Results", description: "Maximum number of results", default: 5)
    var maxResults: Int

    static var parameterSummary: some ParameterSummary {
        Summary("Search images for \(\.$query)") {
            \.$maxResults
        }
    }

    func perform() async throws -> some IntentResult & ReturnsValue<String> {
        let body: [String: Any] = [
            "requests": [
                ["id": 1, "query": query, "max_results": maxResults]
            ]
        ]

        let response = try await SkillExecutor.execute(
            appId: "images", skillId: "search", body: body
        )
        return .result(value: SkillFormatter.formatResults(response, type: "images"))
    }
}
