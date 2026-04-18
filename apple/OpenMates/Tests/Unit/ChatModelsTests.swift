// ChatModels unit tests — validates model decoding, computed properties, and edge cases.

import XCTest
@testable import OpenMates

final class ChatModelsTests: XCTestCase {

    func testChatDecodesFromJSON() throws {
        let json = """
        {
            "id": "chat-123",
            "title": "Test Chat",
            "encrypted_title": null,
            "icon": "ai",
            "category": "general",
            "app_id": "ai",
            "is_pinned": false,
            "is_archived": false,
            "is_private": true,
            "created_at": "2026-01-01T00:00:00Z",
            "updated_at": "2026-01-02T00:00:00Z"
        }
        """
        let data = json.data(using: .utf8)!
        let decoder = JSONDecoder()
        decoder.keyDecodingStrategy = .convertFromSnakeCase
        let chat = try decoder.decode(Chat.self, from: data)

        XCTAssertEqual(chat.id, "chat-123")
        XCTAssertEqual(chat.title, "Test Chat")
        XCTAssertEqual(chat.appId, "ai")
        XCTAssertEqual(chat.isPinned, false)
    }

    func testMessageDecodesFromJSON() throws {
        let json = """
        {
            "id": "msg-456",
            "chat_id": "chat-123",
            "role": "user",
            "content": "Hello world",
            "encrypted_content": null,
            "content_iv": null,
            "created_at": "2026-01-01T12:00:00Z",
            "updated_at": null,
            "app_id": null,
            "is_streaming": false,
            "embed_refs": []
        }
        """
        let data = json.data(using: .utf8)!
        let decoder = JSONDecoder()
        decoder.keyDecodingStrategy = .convertFromSnakeCase
        let message = try decoder.decode(Message.self, from: data)

        XCTAssertEqual(message.id, "msg-456")
        XCTAssertEqual(message.role, .user)
        XCTAssertEqual(message.content, "Hello world")
    }

    func testEmbedRecordDecodesFromJSON() throws {
        let json = """
        {
            "id": "embed-789",
            "embed_type": "web-search",
            "title": "Search Results",
            "status": "finished",
            "data": {"query": "test"},
            "child_embed_ids": ["embed-child-1"],
            "created_at": "2026-01-01T12:00:00Z"
        }
        """
        let data = json.data(using: .utf8)!
        let decoder = JSONDecoder()
        decoder.keyDecodingStrategy = .convertFromSnakeCase
        let embed = try decoder.decode(EmbedRecord.self, from: data)

        XCTAssertEqual(embed.id, "embed-789")
        XCTAssertEqual(embed.embedType, "web-search")
        XCTAssertEqual(embed.childEmbedIds.count, 1)
    }

    func testChatDisplayTitleFallback() throws {
        let json = """
        {
            "id": "chat-no-title",
            "title": null,
            "encrypted_title": null,
            "icon": null,
            "category": null,
            "app_id": null,
            "is_pinned": null,
            "is_archived": null,
            "is_private": true,
            "created_at": "2026-01-01T00:00:00Z",
            "updated_at": null
        }
        """
        let data = json.data(using: .utf8)!
        let decoder = JSONDecoder()
        decoder.keyDecodingStrategy = .convertFromSnakeCase
        let chat = try decoder.decode(Chat.self, from: data)

        XCTAssertEqual(chat.displayTitle, "New Chat", "Should fall back to 'New Chat' when title is nil")
    }
}
