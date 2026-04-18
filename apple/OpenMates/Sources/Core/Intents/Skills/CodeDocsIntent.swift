// "Get Code Docs" Shortcut — fetches documentation for a library/framework via REST API.

import AppIntents
import Foundation

struct CodeDocsIntent: AppIntent {
    static let title: LocalizedStringResource = "Get Code Documentation"
    static let description: IntentDescription = "Look up documentation for a programming library or framework."
    static let openAppWhenRun = false

    @Parameter(title: "Library", description: "Library or framework name (e.g., 'SwiftUI', 'React')")
    var query: String

    static var parameterSummary: some ParameterSummary {
        Summary("Get docs for \(\.$query)")
    }

    func perform() async throws -> some IntentResult & ReturnsValue<String> {
        let body: [String: Any] = [
            "requests": [
                ["id": 1, "query": query]
            ]
        ]

        let response = try await SkillExecutor.execute(
            appId: "code", skillId: "get_docs", body: body
        )
        return .result(value: SkillFormatter.formatResults(response, type: "docs"))
    }
}
