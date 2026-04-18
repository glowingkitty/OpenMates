// "Search Health Appointments" Shortcut — finds doctor/specialist appointments.
// Chain with Calendar to book appointments.

import AppIntents
import Foundation

struct HealthSearchIntent: AppIntent {
    static let title: LocalizedStringResource = "Search Health Appointments"
    static let description: IntentDescription = "Search for doctor or specialist appointments."
    static let openAppWhenRun = false

    @Parameter(title: "Specialty", description: "Type of doctor or treatment")
    var query: String

    @Parameter(title: "Location", description: "City or area", default: nil)
    var location: String?

    static var parameterSummary: some ParameterSummary {
        Summary("Search health appointments for \(\.$query)") {
            \.$location
        }
    }

    func perform() async throws -> some IntentResult & ReturnsValue<String> {
        var request: [String: Any] = ["id": 1, "query": query]
        if let location { request["location"] = location }

        let body: [String: Any] = ["requests": [request]]
        let response = try await SkillExecutor.execute(
            appId: "health", skillId: "search_appointments", body: body
        )
        return .result(value: SkillFormatter.formatResults(response, type: "health"))
    }
}
