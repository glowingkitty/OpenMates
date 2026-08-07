// Unit coverage for the approved Web Search app-skill contract on Apple.
// Tests use only synthetic fixture data and local formatter/request builders.
// They do not touch provider APIs, user data, private hosts, secrets, or logs.
// Architecture: contracts/features/app-skills/web-search/contract.yml

import XCTest
@testable import OpenMates

final class WebSearchContractParityTests: XCTestCase {
    // contract-test: direct surface=gui.apple assertions=web-search.request.validated,web-search.surface-parity
    func testWebSearchShortcutRequestUsesContractCountParameter() throws {
        let body = WebSearchIntent.requestBody(query: "OpenMates", maxResults: 3)
        let requests = try XCTUnwrap(body["requests"] as? [[String: Any]])
        let request = try XCTUnwrap(requests.first)

        XCTAssertEqual(request["query"] as? String, "OpenMates")
        XCTAssertEqual(request["count"] as? Int, 3)
        XCTAssertNil(request["max_results"])
    }

    // contract-test: direct surface=gui.apple assertions=web-search.request.ids-correlated,web-search.response.sanitized,web-search.results.bounded,web-search.surface-parity
    func testWebSearchAppleFixtureMatchesContractResultShape() throws {
        let webSearch = try XCTUnwrap(
            DevEmbedPreviewFixtures.skills(for: .web).first { $0.id == "web-search" }
        )

        XCTAssertEqual(webSearch.primaryEmbed.rawData?["provider"]?.value as? String, "Brave Search")
        XCTAssertEqual(webSearch.primaryEmbed.rawData?["result_count"]?.value as? Int, 3)
        XCTAssertEqual(webSearch.childEmbeds.count, 3)

        for child in webSearch.childEmbeds {
            let data = try XCTUnwrap(child.rawData)
            let title = try XCTUnwrap(data["title"]?.value as? String)
            let description = try XCTUnwrap(data["description"]?.value as? String)

            XCTAssertFalse(title.contains("<"))
            XCTAssertFalse(description.contains("<"))
            XCTAssertEqual(data["age"]?.value as? String, data["page_age"]?.value as? String)
            XCTAssertEqual(data["language"]?.value as? String, "en")
            XCTAssertEqual(data["family_friendly"]?.value as? Bool, true)
        }
    }

    // contract-test: direct surface=gui.apple assertions=web-search.no-results.explicit,web-search.provider-error.visible,web-search.secrets.never-exposed,web-search.surface-parity
    func testWebSearchShortcutFormatterPreservesEmptyAndSafeErrors() throws {
        let emptyFormatted = SkillFormatter.formatResults([
            "results": [["id": "empty", "results": []]],
            "provider": "Brave Search",
        ], type: "web")
        XCTAssertFalse(emptyFormatted.contains("Error:"))
        XCTAssertTrue(emptyFormatted.contains("empty"))

        let errorFormatted = SkillFormatter.formatResults([
            "data": ["error": "Search provider request failed. Please try again."]
        ], type: "web")
        XCTAssertTrue(errorFormatted.contains("Error: Search provider request failed. Please try again."))
        XCTAssertFalse(errorFormatted.contains("Authorization"))
        XCTAssertFalse(errorFormatted.contains("provider_api_key"))
        XCTAssertFalse(errorFormatted.contains("raw_stack_trace"))
    }
}
