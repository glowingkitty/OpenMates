// "Search Mail" Shortcut — searches email providers via REST API.

import AppIntents
import Foundation

struct MailSearchIntent: AppIntent {
    static let title: LocalizedStringResource = "Search Mail"
    static let description: IntentDescription = "Search for email services and providers."
    static let openAppWhenRun = false

    @Parameter(title: "Query", description: "What to search for")
    var query: String

    static var parameterSummary: some ParameterSummary {
        Summary("Search mail for \(\.$query)")
    }

    func perform() async throws -> some IntentResult & ReturnsValue<String> {
        let body: [String: Any] = [
            "requests": [
                ["id": 1, "query": query]
            ]
        ]

        let response = try await SkillExecutor.execute(
            appId: "mail", skillId: "search", body: body
        )
        return .result(value: SkillFormatter.formatResults(response, type: "mail"))
    }
}
