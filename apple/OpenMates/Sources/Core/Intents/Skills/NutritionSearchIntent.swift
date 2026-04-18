// "Search Recipes" Shortcut — finds recipes via REST API.
// Chain with Reminders for meal planning.

import AppIntents
import Foundation

struct NutritionSearchIntent: AppIntent {
    static let title: LocalizedStringResource = "Search Recipes"
    static let description: IntentDescription = "Search for recipes and nutritional information."
    static let openAppWhenRun = false

    @Parameter(title: "Query", description: "What recipe or ingredient to search for")
    var query: String

    static var parameterSummary: some ParameterSummary {
        Summary("Search recipes for \(\.$query)")
    }

    func perform() async throws -> some IntentResult & ReturnsValue<String> {
        let body: [String: Any] = [
            "requests": [
                ["id": 1, "query": query]
            ]
        ]

        let response = try await SkillExecutor.execute(
            appId: "nutrition", skillId: "search_recipes", body: body
        )
        return .result(value: SkillFormatter.formatResults(response, type: "recipes"))
    }
}
