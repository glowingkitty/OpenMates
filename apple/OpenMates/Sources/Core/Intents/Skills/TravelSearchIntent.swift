// Travel Shortcuts — search flights/trains and hotels via REST API.
// Chain with Notes or Calendar for trip planning automations.

import AppIntents
import Foundation

struct SearchConnectionsIntent: AppIntent {
    static let title: LocalizedStringResource = "Search Travel Connections"
    static let description: IntentDescription = "Search for flights or train connections between cities."
    static let openAppWhenRun = false

    @Parameter(title: "From", description: "Departure city or airport")
    var origin: String

    @Parameter(title: "To", description: "Arrival city or airport")
    var destination: String

    @Parameter(title: "Date", description: "Travel date (YYYY-MM-DD)", default: nil)
    var date: String?

    static var parameterSummary: some ParameterSummary {
        Summary("Search connections from \(\.$origin) to \(\.$destination)") {
            \.$date
        }
    }

    func perform() async throws -> some IntentResult & ReturnsValue<String> {
        var request: [String: Any] = [
            "id": 1,
            "origin": origin,
            "destination": destination
        ]
        if let date { request["date"] = date }

        let body: [String: Any] = ["requests": [request]]
        let response = try await SkillExecutor.execute(
            appId: "travel", skillId: "search_connections", body: body
        )
        return .result(value: SkillFormatter.formatResults(response, type: "travel"))
    }
}

struct SearchStaysIntent: AppIntent {
    static let title: LocalizedStringResource = "Search Hotels"
    static let description: IntentDescription = "Search for hotels and accommodations."
    static let openAppWhenRun = false

    @Parameter(title: "Location", description: "City or area")
    var location: String

    @Parameter(title: "Check-in", description: "Check-in date (YYYY-MM-DD)", default: nil)
    var checkin: String?

    @Parameter(title: "Check-out", description: "Check-out date (YYYY-MM-DD)", default: nil)
    var checkout: String?

    static var parameterSummary: some ParameterSummary {
        Summary("Search hotels in \(\.$location)") {
            \.$checkin
            \.$checkout
        }
    }

    func perform() async throws -> some IntentResult & ReturnsValue<String> {
        var request: [String: Any] = ["id": 1, "location": location]
        if let checkin { request["checkin"] = checkin }
        if let checkout { request["checkout"] = checkout }

        let body: [String: Any] = ["requests": [request]]
        let response = try await SkillExecutor.execute(
            appId: "travel", skillId: "search_stays", body: body
        )
        return .result(value: SkillFormatter.formatResults(response, type: "stays"))
    }
}
