// "Search Homes" Shortcut — finds real estate listings via REST API.

import AppIntents
import Foundation

struct HomeSearchIntent: AppIntent {
    static let title: LocalizedStringResource = "Search Homes"
    static let description: IntentDescription = "Search for homes and real estate listings."
    static let openAppWhenRun = false

    @Parameter(title: "Query", description: "Location or property type to search for")
    var query: String

    static var parameterSummary: some ParameterSummary {
        Summary("Search homes for \(\.$query)")
    }

    func perform() async throws -> some IntentResult & ReturnsValue<String> {
        let body: [String: Any] = [
            "requests": [
                ["id": 1, "query": query]
            ]
        ]

        let response = try await SkillExecutor.execute(
            appId: "home", skillId: "search", body: body
        )
        return .result(value: SkillFormatter.formatResults(response, type: "home"))
    }
}
