// "Search Events" Shortcut — finds events near a location via REST API.
// Chain with Calendar to automatically add interesting events.

import AppIntents
import Foundation

struct EventsSearchIntent: AppIntent {
    static let title: LocalizedStringResource = "Search Events"
    static let description: IntentDescription = "Find events near a location."
    static let openAppWhenRun = false

    @Parameter(title: "Query", description: "What kind of events to find")
    var query: String

    @Parameter(title: "Location", description: "City or area to search in", default: nil)
    var location: String?

    static var parameterSummary: some ParameterSummary {
        Summary("Search events for \(\.$query)") {
            \.$location
        }
    }

    func perform() async throws -> some IntentResult & ReturnsValue<String> {
        var request: [String: Any] = ["id": 1, "query": query]
        if let location { request["location"] = location }

        let body: [String: Any] = ["requests": [request]]

        let response = try await SkillExecutor.execute(
            appId: "events", skillId: "search", body: body
        )
        return .result(value: SkillFormatter.formatResults(response, type: "events"))
    }
}
