// Deterministic URL preparation coverage, with no network or account writes.
import XCTest
@testable import OpenMates

@MainActor
final class URLMessageEmbedPreparationTests: XCTestCase {
    // contract-test: supporting surface=gui.apple assertions=chats.surface.semantic-parity
    func testWebsiteMetadataAndSurroundingTextBecomeAnOrderedEmbed() async throws {
        let prepared = try await URLMessageEmbedPreparation.prepare(
            text: "Read https://example.invalid/article then summarize it", credits: 0, validate: {},
            fetch: { endpoint, url in
                XCTAssertEqual(endpoint, "metadata")
                XCTAssertEqual(url, "https://example.invalid/article")
                return ["title": "Public article", "description": "Public fixture description"]
            }, makeID: { "website-id" })
        XCTAssertEqual(prepared.embeds.count, 1)
        XCTAssertEqual(prepared.embeds[0].type, "website")
        XCTAssertEqual(prepared.embeds[0].content["title"] as? String, "Public article")
        XCTAssertTrue(prepared.content.hasPrefix("Read \n```json\n"))
        XCTAssertTrue(prepared.content.hasSuffix("\n```\n then summarize it"))
        XCTAssertTrue(prepared.content.contains("\"url\":\"https://example.invalid/article\""))
    }

    // contract-test: supporting surface=gui.apple assertions=chats.surface.semantic-parity
    func testMobileShortAndProtocolFreeYouTubeURLsCreateStaticVideosWithoutCredits() async throws {
        for url in ["https://m.youtube.com/watch?v=fThppBugFXk", "https://youtu.be/fThppBugFXk?t=30",
                    "m.youtube.com/watch?v=fThppBugFXk", "https://www.youtube.com/shorts/fThppBugFXk",
                    "https://www.youtube.com/embed/fThppBugFXk", "https://youtube.com/v/fThppBugFXk"] {
            let prepared = try await URLMessageEmbedPreparation.prepare(
                text: "\(url)\nsummarize the video", credits: 0, validate: {},
                fetch: { _, _ in XCTFail("A zero-credit video must not fetch YouTube metadata"); return nil },
                makeID: { "video-id" })
            XCTAssertEqual(prepared.embeds.count, 1, url)
            let embed = try XCTUnwrap(prepared.embeds.first)
            XCTAssertEqual(embed.type, "video", url)
            XCTAssertEqual(embed.content["video_id"] as? String, "fThppBugFXk", url)
            XCTAssertEqual(embed.content["url"] as? String, "https://www.youtube.com/watch?v=fThppBugFXk")
            XCTAssertTrue(prepared.content.hasSuffix("summarize the video"))
        }
        XCTAssertNil(URLMessageEmbedPreparation.videoID(for: "https://example.invalid/?v=fThppBugFXk"))
        XCTAssertNil(URLMessageEmbedPreparation.videoID(for: "https://youtube.com.evil.invalid/watch?v=fThppBugFXk"))
    }

    // contract-test: supporting surface=gui.apple assertions=chats.surface.semantic-parity
    func testMetadataFailureFallsBackAndSuccessfulVideoMetadataUsesWebFields() async throws {
        let fallback = try await URLMessageEmbedPreparation.prepare(text: "https://example.invalid", credits: 1,
            validate: {}, fetch: { _, _ in throw URLError(.notConnectedToInternet) })
        XCTAssertEqual(fallback.embeds.first?.type, "website")
        let video = try await URLMessageEmbedPreparation.prepare(text: "https://m.youtube.com/watch?v=fThppBugFXk", credits: 1,
            validate: {}, fetch: { endpoint, _ in
                XCTAssertEqual(endpoint, "youtube")
                return ["video_id": "fThppBugFXk", "title": "Public video", "channel_name": "Public channel",
                        "thumbnails": ["high": "https://example.invalid/high.jpg", "maxres": "https://example.invalid/max.jpg"],
                        "duration": ["total_seconds": 123, "formatted": "2:03"]]
            })
        XCTAssertEqual(video.embeds.first?.content["thumbnail"] as? String, "https://example.invalid/max.jpg")
        XCTAssertEqual(video.embeds.first?.textPreview, "Public video (2:03)")
        let staticVideo = try await URLMessageEmbedPreparation.prepare(text: "https://youtu.be/fThppBugFXk", credits: 1,
            validate: {}, fetch: { _, _ in nil })
        XCTAssertEqual(staticVideo.embeds.first?.content["video_id"] as? String, "fThppBugFXk")
    }

    // contract-test: supporting surface=gui.apple assertions=chats.surface.semantic-parity
    func testMultipleURLsPreserveUnicodeOrderingAndLeaveExistingFencesOpaque() async throws {
        let text = "🌍 https://example.invalid/one compare https://youtu.be/fThppBugFXk\n```swift\nhttps://example.invalid/code\n```\n```json\n{\"type\":\"website\",\"embed_id\":\"existing\",\"url\":\"https://example.invalid/existing\"}\n```"
        var index = 0
        let prepared = try await URLMessageEmbedPreparation.prepare(text: text, credits: 0, validate: {},
            fetch: { _, _ in nil }, makeID: { index += 1; return "url-\(index)" })
        XCTAssertEqual(prepared.embeds.map(\.id), ["url-1", "url-2"])
        XCTAssertTrue(prepared.content.hasPrefix("🌍 \n```json"))
        let first = try XCTUnwrap(prepared.content.range(of: "url-1"))
        let second = try XCTUnwrap(prepared.content.range(of: "url-2"))
        XCTAssertLessThan(first.lowerBound, second.lowerBound)
        XCTAssertTrue(prepared.content.contains("compare"))
        XCTAssertTrue(prepared.content.hasSuffix("\"https://example.invalid/existing\"}\n```"))
        let secondPass = try await URLMessageEmbedPreparation.prepare(text: prepared.content, credits: 0,
            validate: {}, fetch: { _, _ in XCTFail("Prepared references must not be fetched again"); return nil })
        XCTAssertTrue(secondPass.embeds.isEmpty)
        XCTAssertEqual(secondPass.content, prepared.content)
    }

    // contract-test: supporting surface=gui.apple assertions=chats.persistence.client-encrypted,chats.surface.semantic-parity
    func testRegularAndShareAdaptersCarryIdenticalContentAndEmbedsWithoutDuplicateReferences() async throws {
        let prepared = try await URLMessageEmbedPreparation.prepare(text: "https://m.youtube.com/watch?v=fThppBugFXk\nsummarize the video", credits: 0,
            validate: {}, fetch: { _, _ in nil }, makeID: { "051-4369-video" })
        let shared = try BackgroundChatSendContract.redactedContentForSend(text: prepared.content, embeds: [])
        let composer = try XCTUnwrap(prepared.embeds.first.map(ComposerPendingEmbed.fromURL))
        XCTAssertEqual(shared.content, prepared.content)
        XCTAssertTrue(shared.piiMappings.isEmpty, "Protocol IDs cannot be redacted as phone numbers")
        XCTAssertEqual(composer.id, prepared.embeds[0].id)
        XCTAssertEqual(composer.type, prepared.embeds[0].type)
        XCTAssertEqual(composer.record.rawData?["video_id"]?.value as? String, "fThppBugFXk")
        let foregroundObject = try XCTUnwrap(composer.content?.data(using: .utf8)).flatMapJSON()
        XCTAssertEqual(foregroundObject["url"] as? String, prepared.embeds[0].content["url"] as? String)
        XCTAssertEqual(composer.serverPayload?["type"] as? String, prepared.embeds[0].serverPayload?["type"] as? String)
        XCTAssertEqual(prepared.content.components(separatedBy: "051-4369-video").count, 2)
        let withPII = try BackgroundChatSendContract.redactedContentForSend(text: "mail public@example.invalid\n" + prepared.content, embeds: [])
        XCTAssertTrue(withPII.content.contains("[EMAIL_"))
        XCTAssertTrue(withPII.content.contains("051-4369-video"))
    }

    // contract-test: supporting surface=gui.apple assertions=chats.persistence.client-encrypted,chats.surface.semantic-parity
    func testExistingAttachmentReferenceSurvivesURLPreparationWithoutDuplication() async throws {
        let attachment = BackgroundPreparedEmbed(id: "existing-file", type: "docs-doc", referenceType: "file",
            status: "finished", content: ["filename": "public-notes.md"], textPreview: "public-notes.md")
        let input = try BackgroundChatSendContract.contentForSend(text: "https://example.invalid/article", embeds: [attachment])
        let prepared = try await URLMessageEmbedPreparation.prepare(text: input, credits: 0,
            validate: {}, fetch: { _, _ in nil }, makeID: { "website" })
        XCTAssertEqual(prepared.embeds.count, 1)
        XCTAssertTrue(prepared.content.hasSuffix(attachment.markdownReference))
        XCTAssertEqual(prepared.content.components(separatedBy: "existing-file").count, 2)
        let redacted = try BackgroundChatSendContract.redactedContentForSend(text: prepared.content, embeds: [])
        XCTAssertEqual(redacted.content, prepared.content)
    }

    // contract-test: supporting surface=gui.apple assertions=chats.surface.semantic-parity
    func testWholeMessageMetadataBudgetExhaustionStillMaterializesEveryURL() async throws {
        var elapsed: TimeInterval = 0
        var fetched: [String] = []
        var validations = 0
        let prepared = try await URLMessageEmbedPreparation.prepare(
            text: "Read https://example.invalid/one compare https://example.invalid/two then https://youtu.be/fThppBugFXk summarize all",
            credits: 1, validate: { validations += 1 },
            fetch: { _, url in
                fetched.append(url)
                elapsed = 3.1 // deterministic deadline expiration; no sleep/network.
                return ["title": "Response after optional metadata deadline"]
            }, metadataBudget: 3, clock: { elapsed })
        XCTAssertEqual(fetched, ["https://example.invalid/one"])
        XCTAssertEqual(prepared.embeds.map(\.type), ["website", "website", "video"])
        XCTAssertEqual(prepared.embeds.count, 3)
        XCTAssertTrue(prepared.embeds.allSatisfy { $0.content["title"] as? String == nil })
        XCTAssertEqual(prepared.embeds[2].content["video_id"] as? String, "fThppBugFXk")
        XCTAssertTrue(prepared.content.hasSuffix(" summarize all"))
        XCTAssertEqual(validations, 8, "Skipped metadata must preserve before/after account and cancellation fences")
    }

    // contract-test: supporting surface=gui.apple assertions=chats.surface.semantic-parity
    func testMismatchedYouTubeMetadataIsDiscardedForStaticFallback() async throws {
        let prepared = try await URLMessageEmbedPreparation.prepare(
            text: "https://m.youtube.com/watch?v=fThppBugFXk summarize the video", credits: 1, validate: {},
            fetch: { _, _ in
                ["video_id": "dQw4w9WgXcQ", "title": "Wrong video title", "url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
                 "thumbnails": ["maxres": "https://example.invalid/wrong-video.jpg"], "view_count": 100]
            })
        let embed = try XCTUnwrap(prepared.embeds.first)
        XCTAssertEqual(embed.content["video_id"] as? String, "fThppBugFXk")
        XCTAssertEqual(embed.content["url"] as? String, "https://www.youtube.com/watch?v=fThppBugFXk")
        XCTAssertNil(embed.content["title"] as? String)
        XCTAssertNil(embed.content["thumbnail"])
        XCTAssertNil(embed.content["view_count"] as? Int)
        XCTAssertTrue(prepared.content.hasSuffix(" summarize the video"))
    }

    // contract-test: supporting surface=gui.apple assertions=chats.persistence.client-encrypted
    func testCancellationAndAccountChangeRejectMetadataBeforeMaterialization() async throws {
        var valid = true
        var ids = 0
        do {
            _ = try await URLMessageEmbedPreparation.prepare(text: "https://example.invalid", credits: 1,
                validate: { if !valid { throw BackgroundChatSendError.notAuthenticated } },
                fetch: { _, _ in valid = false; return ["title": "Previous account metadata"] },
                makeID: { ids += 1; return "unexpected" })
            XCTFail("An account change must reject the send preparation")
        } catch BackgroundChatSendError.notAuthenticated { }
        XCTAssertEqual(ids, 0)
        do {
            _ = try await URLMessageEmbedPreparation.prepare(text: "https://example.invalid", credits: 0,
                validate: {}, fetch: { _, _ in throw CancellationError() })
            XCTFail("Cancellation cannot produce a fallback send")
        } catch is CancellationError { }
    }
}

private extension Data {
    func flatMapJSON() throws -> [String: Any] {
        try XCTUnwrap(JSONSerialization.jsonObject(with: self) as? [String: Any])
    }
}
