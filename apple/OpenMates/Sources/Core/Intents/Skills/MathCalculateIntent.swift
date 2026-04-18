// "Calculate" Shortcut — performs math calculations via REST API.
// Chain with Notes for calculation logs.

import AppIntents
import Foundation

struct MathCalculateIntent: AppIntent {
    static let title: LocalizedStringResource = "Calculate"
    static let description: IntentDescription = "Perform a mathematical calculation."
    static let openAppWhenRun = false

    @Parameter(title: "Expression", description: "Math expression to calculate (e.g., '2^10 + sqrt(144)')")
    var expression: String

    static var parameterSummary: some ParameterSummary {
        Summary("Calculate \(\.$expression)")
    }

    func perform() async throws -> some IntentResult & ReturnsValue<String> {
        let body: [String: Any] = [
            "requests": [
                ["id": 1, "expression": expression]
            ]
        ]

        let response = try await SkillExecutor.execute(
            appId: "math", skillId: "calculate", body: body
        )
        return .result(value: SkillFormatter.formatResults(response, type: "math"))
    }
}
