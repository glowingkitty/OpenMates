// "Search the Web" Shortcut — executes the web search skill via REST API.
// Returns search results as formatted text. No LLM inference involved.

import AppIntents
import Foundation

struct WebSearchIntent: AppIntent {
    static let title: LocalizedStringResource = "Search the Web"
    static let description: IntentDescription = "Search the web using OpenMates and get results."
    static let openAppWhenRun = false

    @Parameter(title: "Query", description: "What to search for")
    var query: String

    @Parameter(title: "Max Results", description: "Maximum number of results to return", default: 5)
    var maxResults: Int

    static var parameterSummary: some ParameterSummary {
        Summary("Search the web for \(\.$query)") {
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
            appId: "web", skillId: "search", body: body
        )
        return .result(value: SkillFormatter.formatResults(response, type: "web"))
    }
}

struct WebReadIntent: AppIntent {
    static let title: LocalizedStringResource = "Read a Web Page"
    static let description: IntentDescription = "Read and extract content from a web page URL."
    static let openAppWhenRun = false

    @Parameter(title: "URL", description: "The web page URL to read")
    var url: String

    static var parameterSummary: some ParameterSummary {
        Summary("Read web page \(\.$url)")
    }

    func perform() async throws -> some IntentResult & ReturnsValue<String> {
        let body: [String: Any] = [
            "requests": [
                ["id": 1, "url": url]
            ]
        ]

        let response = try await SkillExecutor.execute(
            appId: "web", skillId: "read", body: body
        )
        return .result(value: SkillFormatter.formatResults(response, type: "read"))
    }
}
