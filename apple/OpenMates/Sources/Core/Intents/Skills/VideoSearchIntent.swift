// Video Shortcuts — search videos and get transcripts via REST API.

import AppIntents
import Foundation

struct VideoSearchIntent: AppIntent {
    static let title: LocalizedStringResource = "Search Videos"
    static let description: IntentDescription = "Search for videos on a topic."
    static let openAppWhenRun = false

    @Parameter(title: "Query", description: "What to search for")
    var query: String

    @Parameter(title: "Max Results", description: "Maximum number of results", default: 5)
    var maxResults: Int

    static var parameterSummary: some ParameterSummary {
        Summary("Search videos for \(\.$query)") {
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
            appId: "videos", skillId: "search", body: body
        )
        return .result(value: SkillFormatter.formatResults(response, type: "videos"))
    }
}

struct VideoTranscriptIntent: AppIntent {
    static let title: LocalizedStringResource = "Get Video Transcript"
    static let description: IntentDescription = "Get the transcript of a YouTube video."
    static let openAppWhenRun = false

    @Parameter(title: "YouTube URL or ID", description: "YouTube video URL or ID")
    var videoId: String

    static var parameterSummary: some ParameterSummary {
        Summary("Get transcript for \(\.$videoId)")
    }

    func perform() async throws -> some IntentResult & ReturnsValue<String> {
        let body: [String: Any] = [
            "requests": [
                ["id": 1, "url": videoId]
            ]
        ]

        let response = try await SkillExecutor.execute(
            appId: "videos", skillId: "get_transcript", body: body
        )
        return .result(value: SkillFormatter.formatResults(response, type: "transcript"))
    }
}
