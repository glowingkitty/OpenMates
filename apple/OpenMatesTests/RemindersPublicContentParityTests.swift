// Unit coverage for public-content parity models.
// These tests use synthetic fixture data only and never touch reminder IDs,
// notification tokens, private chat IDs, user emails, or network state.

import XCTest
@testable import OpenMates

final class RemindersPublicContentParityTests: XCTestCase {
    func testDailyInspirationDecodesWebCompatiblePayload() throws {
        let data = Data(
            #"""
            {
              "inspirationId": "daily-public-fixture",
              "text": "Learn something useful today",
              "title": "Daily prompt",
              "category": "general_knowledge",
              "iconName": "book",
              "startedChatId": null,
              "video": {
                "youtubeId": "public-video",
                "title": "Public video",
                "channelName": "OpenMates",
                "thumbnailUrl": "https://example.com/thumb.jpg",
                "durationSeconds": 120,
                "viewCount": 42,
                "publishedAt": "2026-01-01T00:00:00Z"
              }
            }
            """#.utf8
        )

        let inspiration = try JSONDecoder().decode(DailyInspirationData.self, from: data)

        XCTAssertEqual(inspiration.inspirationId, "daily-public-fixture")
        XCTAssertEqual(inspiration.text, "Learn something useful today")
        XCTAssertEqual(inspiration.category, "general_knowledge")
        XCTAssertEqual(inspiration.video?.youtubeId, "public-video")
        XCTAssertNil(inspiration.startedChatId)
    }

    func testDemoChatDecodesReadOnlyPublicFixture() throws {
        let data = Data(
            #"""
            {
              "chatId": "example-public-fixture",
              "slug": "public-fixture",
              "title": "Public fixture chat",
              "description": "A sanitized public chat fixture",
              "messages": [
                {
                  "messageId": "m-public-1",
                  "role": "assistant",
                  "content": "Public content only",
                  "embedRefs": null
                }
              ],
              "metadata": {
                "category": "example",
                "featured": true,
                "order": 1,
                "iconNames": ["chat"],
                "videoKey": null
              }
            }
            """#.utf8
        )

        let chat = try JSONDecoder().decode(DemoChat.self, from: data)

        XCTAssertEqual(chat.id, "example-public-fixture")
        XCTAssertEqual(chat.slug, "public-fixture")
        XCTAssertEqual(chat.messages.map(\.role), ["assistant"])
        XCTAssertEqual(chat.metadata?.category, PublicChatCategory.example.rawValue)
        XCTAssertEqual(chat.metadata?.featured, true)
    }

    func testPublicChatCategoriesClassifyNativeGroups() {
        XCTAssertEqual(PublicChatCategory.intro.displayName, "Introduction")
        XCTAssertEqual(PublicChatCategory.example.icon, "chat")
        XCTAssertEqual(PublicChatCategory.legal.rawValue, "legal")
        XCTAssertEqual(PublicChatCategory.announcement.rawValue, "announcements")
        XCTAssertEqual(PublicChatCategory.tips.rawValue, "tips_and_tricks")
    }
}
