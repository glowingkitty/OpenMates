// "Search News" Shortcut — executes the news search skill via REST API.
// Returns news articles as formatted text. Chain with Reminders for daily news digests.

import AppIntents
import Foundation

struct NewsSearchIntent: AppIntent {
    static let title: LocalizedStringResource = "Search News"
    static let description: IntentDescription = "Search for news articles on a topic."
    static let openAppWhenRun = false

    @Parameter(title: "Topic", description: "What news to search for")
    var topic: String

    @Parameter(title: "Max Results", description: "Maximum number of articles", default: 5)
    var maxResults: Int

    static var parameterSummary: some ParameterSummary {
        Summary("Search news about \(\.$topic)") {
            \.$maxResults
        }
    }

    func perform() async throws -> some IntentResult & ReturnsValue<String> {
        let body: [String: Any] = [
            "requests": [
                ["id": 1, "query": topic, "max_results": maxResults]
            ]
        ]

        let response = try await SkillExecutor.execute(
            appId: "news", skillId: "search", body: body
        )
        return .result(value: SkillFormatter.formatResults(response, type: "news"))
    }
}
