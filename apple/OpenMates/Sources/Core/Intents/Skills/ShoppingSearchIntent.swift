// "Search Products" Shortcut — finds products and prices via REST API.
// Chain with Reminders for price drop alerts.

import AppIntents
import Foundation

struct ShoppingSearchIntent: AppIntent {
    static let title: LocalizedStringResource = "Search Products"
    static let description: IntentDescription = "Search for products and compare prices."
    static let openAppWhenRun = false

    @Parameter(title: "Product", description: "What product to search for")
    var query: String

    static var parameterSummary: some ParameterSummary {
        Summary("Search products for \(\.$query)")
    }

    func perform() async throws -> some IntentResult & ReturnsValue<String> {
        let body: [String: Any] = [
            "requests": [
                ["id": 1, "query": query]
            ]
        ]

        let response = try await SkillExecutor.execute(
            appId: "shopping", skillId: "search_products", body: body
        )
        return .result(value: SkillFormatter.formatResults(response, type: "shopping"))
    }
}
