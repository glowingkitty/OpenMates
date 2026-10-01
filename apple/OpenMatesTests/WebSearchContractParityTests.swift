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
        let firstResult = try XCTUnwrap(WebsiteResultModel(embed: webSearch.childEmbeds[0]))
        XCTAssertTrue(firstResult.previewImageURL?.contains("/images/examples/group1.jpg") == true)
        XCTAssertEqual(firstResult.cardEmbed.rawData?["thumbnail_original"]?.value as? String, "/images/examples/group1.jpg")
        XCTAssertNil(firstResult.previewFaviconURL)

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

    // contract-test: supporting surface=gui.apple assertions=web-search.surface-parity
    func testYouTubeSearchResultUsesVideoPresentationAndPrivacyHost() throws {
        let videoID = "dQw4w9WgXcQ"
        XCTAssertEqual(YouTubeVideoURL.videoID(from: "https://www.youtube.com/watch?t=3&v=\(videoID)"), videoID)
        XCTAssertEqual(YouTubeVideoURL.videoID(from: "https://youtu.be/\(videoID)"), videoID)
        XCTAssertEqual(YouTubeVideoURL.videoID(from: "https://m.youtube.com/shorts/\(videoID)"), videoID)
        XCTAssertNil(YouTubeVideoURL.videoID(from: "https://youtube.com.evil.example/watch?v=\(videoID)"))
        XCTAssertEqual(YouTubeVideoURL.privacyEmbedURL(videoID: videoID)?.host, "www.youtube-nocookie.com")

        let website = EmbedRecord(
            id: "video-search-child", type: EmbedType.webWebsite.rawValue,
            status: .finished,
            data: .raw([
                "url": AnyCodable("https://www.youtube.com/watch?v=\(videoID)"),
                "title": AnyCodable("Video result"),
                "channel_name": AnyCodable("Creator")
            ]),
            parentEmbedId: "web-search-parent", appId: "web", skillId: nil,
            embedIds: nil, createdAt: nil
        )
        let result = try XCTUnwrap(WebsiteResultModel(embed: website))
        let presented = try XCTUnwrap(result.videoEmbed)
        XCTAssertEqual(presented.type, EmbedType.videosVideo.rawValue)
        XCTAssertEqual(presented.rawData?["video_id"]?.value as? String, videoID)
        XCTAssertEqual(presented.rawData?["channel"]?.value as? String, "Creator")
        XCTAssertEqual(presented.parentEmbedId, website.parentEmbedId)
    }

    // contract-test: supporting surface=gui.apple assertions=web-search.surface-parity
    func testWebSearchThumbnailUsesTheSameSourcePriorityAsWeb() throws {
        let child = EmbedRecord(
            id: "thumbnail-priority", type: EmbedType.webWebsite.rawValue,
            status: .finished,
            data: .raw([
                "url": AnyCodable("https://example.com/result"),
                "thumbnail_url": AnyCodable("https://example.com/thumbnail.jpg"),
                "thumbnail_original": AnyCodable("https://example.com/original.jpg")
            ]),
            parentEmbedId: "search-parent", appId: "web", skillId: nil,
            embedIds: nil, createdAt: nil
        )
        let result = try XCTUnwrap(WebsiteResultModel(embed: child))
        XCTAssertTrue(result.previewImageURL?.contains("thumbnail.jpg") == true)
        XCTAssertFalse(result.previewImageURL?.contains("original.jpg") == true)
        XCTAssertTrue(result.thumbnailStripURL?.contains("max_width=520") == true)
    }

    // contract-test: supporting surface=gui.apple assertions=web-search.surface-parity
    func testPersistedWebSearchParentKeepsQueryProviderAndInlineResults() throws {
        let payload = #"""
        app_id: web
        skill_id: search
        query: best restaurants in Berlin
        provider: Brave Search
        result_count: 1
        preview_results[1]{url,title,preview_image_url}:
          https://example.org,Synthetic preview,https://app.dev.openmates.org/favicon.svg
        """#
        let parent = EmbedRecord(id: "persisted-search", type: "app-skill-use", status: .finished, data: nil,
                                 parentEmbedId: nil, appId: "web", skillId: "search", embedIds: nil, createdAt: nil)
            .decryptedCopy(content: payload, type: "app-skill-use")
        let model = SearchSkillPreviewModel(embed: parent, allEmbedRecords: [:])
        XCTAssertEqual(model.query, "best restaurants in Berlin")
        XCTAssertEqual(model.provider, "Brave Search")
        XCTAssertEqual(model.previewResultCount, 1)
        XCTAssertEqual(model.websiteResults.first?.title, "Synthetic preview")
        let thumbnail = try XCTUnwrap(model.websiteResults.first?.thumbnailStripURL)
        XCTAssertTrue(thumbnail.contains("preview.openmates.org/api/v1/image"))
    }

    // contract-test: supporting surface=gui.apple assertions=web-search.surface-parity
    func testWebsiteFaviconFallbackMatchesWebProxyRoute() throws {
        let fallback = try XCTUnwrap(EmbedFieldReader.proxiedFaviconImageURL(
            directURL: nil, pageURL: "https://example.com/page"
        ))
        let fallbackComponents = try XCTUnwrap(URLComponents(string: fallback))
        XCTAssertEqual(fallbackComponents.path, "/api/v1/favicon")
        XCTAssertEqual(fallbackComponents.queryItems?.first { $0.name == "url" }?.value, "https://example.com/page")

        let supplied = try XCTUnwrap(EmbedFieldReader.proxiedFaviconImageURL(
            directURL: "https://example.com/favicon.png", pageURL: "https://example.com/page"
        ))
        let suppliedComponents = try XCTUnwrap(URLComponents(string: supplied))
        XCTAssertEqual(suppliedComponents.path, "/api/v1/image")
        XCTAssertEqual(suppliedComponents.queryItems?.first { $0.name == "max_width" }?.value, "38")
    }
}
