// Synthetic skill input identity/hydration coverage. No account, network or inference.
import XCTest
@testable import OpenMates

@MainActor
final class AppSkillInputPreviewTests: XCTestCase {
    // contract-test: supporting surface=gui.apple assertions=chats.surface.semantic-parity,chats.rendering.assistant-document-convergence
    func testInputIdentitySurvivesTypedLoadingInlineThumbnailAndHydratedCompletion() throws {
        for key in ["app:web:search", "app:news:search", "app:images:search"] {
            for variant in ["input-loading", "input-partial", "input-complete"] {
                let fixture = try XCTUnwrap(DevEmbedPreviewFixtures.fixture(for: .init(
                    registryKey: key, surface: .preview, variant: variant, direction: .ltr)))
                XCTAssertFalse(fixture.primaryEmbed.isAppSkillUse)
                let model = SearchSkillPreviewModel(embed: fixture.primaryEmbed, allEmbedRecords: fixture.allRecords)
                XCTAssertEqual(model.query, "Golden Gate Bridge")
                if variant == "input-loading" { XCTAssertTrue(model.childEmbeds.isEmpty) }
                if variant == "input-partial" { XCTAssertEqual(model.childEmbeds.count, 1) }
                if variant == "input-complete" { XCTAssertFalse(model.childEmbeds.isEmpty) }
                if key == "app:images:search", variant == "input-partial" {
                    XCTAssertEqual(model.imageResults.count, 1)
                    XCTAssertEqual(model.childEmbeds.first?.type, EmbedType.imagesImageResult.rawValue)
                }
            }
        }
    }

    // contract-test: supporting surface=gui.apple assertions=chats.surface.semantic-parity
    func testCalledSkillInputMappingsUseActualRequestsAndNeverExecutionCredentials() {
        let examples: [(String, String, [String: Any], String)] = [
            ("audio", "speak", ["text": "Synthetic spoken phrase"], "Synthetic spoken phrase"),
            ("code", "get_docs", ["library": "/sveltejs/svelte", "question": "How do runes work?"], "/sveltejs/svelte · How do runes work?"),
            ("travel", "get_flight", ["flight_number": "LH123", "departure_date": "2026-10-09"], "LH123 · 2026-10-09"),
            ("travel", "search_connections", ["requests": [["legs": [["origin": "Berlin", "destination": "Paris", "date": "2026-10-09"]]]]], "Berlin · Paris · 2026-10-09"),
            ("social_media", "get-posts", ["page": "synthetic-community", "platform": "reddit"], "synthetic-community · reddit"),
            ("workflows", "create-or-modify", ["instruction": "Summarize a weekly report"], "Summarize a weekly report"),
            ("tasks", "create", ["tasks": [["title": "Synthetic task"]]], "Synthetic task")
        ]
        for (app, skill, input, expected) in examples {
            var raw = input
            raw["access_token_handle"] = "must-not-display"
            raw["aes_key"] = "must-not-display"
            let embed = EmbedRecord(id: "synthetic", type: "app:\(app):\(skill)", status: .processing,
                                    data: .raw(raw.mapValues(AnyCodable.init)), parentEmbedId: nil,
                                    appId: app, skillId: skill, embedIds: nil, createdAt: nil)
            XCTAssertEqual(AppSkillInputPreviewModel(embed: embed).text, expected)
        }
        let noInput = EmbedRecord(id: "synthetic", type: "app:calendar:list-calendars", status: .processing,
            data: .raw(["access_token_handle": AnyCodable("must-not-display")]), parentEmbedId: nil,
            appId: "calendar", skillId: "list-calendars", embedIds: nil, createdAt: nil)
        XCTAssertNil(AppSkillInputPreviewModel(embed: noInput).text)
    }

    // contract-test: supporting surface=gui.apple assertions=chats.surface.semantic-parity
    func testTypedTerminalParentsUseCalledSkillRendererWithoutGenericMarker() {
        for (app, skill) in [("finance", "check_accounts"), ("math", "calculate"), ("images", "generate"),
                             ("audio", "speak"), ("reminder", "set-reminder"), ("calendar", "create-event")] {
            for status in [EmbedStatus.processing, .finished, .error, .cancelled] {
                let embed = EmbedRecord(id: "synthetic", type: "app:\(app):\(skill)", status: status,
                    data: .raw([:]), parentEmbedId: nil, appId: app, skillId: skill,
                    embedIds: nil, createdAt: nil)
                XCTAssertFalse(embed.isAppSkillUse)
                XCTAssertTrue(AppSkillInputPreviewModel.isRegisteredSkill(embed))
            }
        }
        let child = EmbedRecord(id: "child", type: "place", status: .finished,
            data: .raw([:]), parentEmbedId: nil, appId: "maps", skillId: "search",
            embedIds: nil, createdAt: nil)
        XCTAssertFalse(AppSkillInputPreviewModel.isRegisteredSkill(child))
        let plot = EmbedRecord(id: "plot", type: "app:math:plot", status: .finished, data: .raw([:]),
            parentEmbedId: nil, appId: nil, skillId: nil, embedIds: nil, createdAt: nil)
        XCTAssertFalse(AppSkillInputPreviewModel.isRegisteredSkill(plot))
    }

    // contract-test: supporting surface=gui.apple assertions=chats.surface.semantic-parity,chats.persistence.client-encrypted
    func testProcessingWirePreviewFallbackPreservesContentAndOnlyCopiesDisplayMetadata() {
        let content = #"{"query":"content query","app_id":"images","skill_id":"search"}"#
        let merged = EmbedRecord.parseContent(ChatEmbedStreamCoordinator.processingEmbedContent(content, fields: [
            "query": "fallback query", "provider": "Brave", "results": [["image_url": "https://example.invalid/image.png"]],
            "access_token_handle": "must-not-copy", "encrypted_content": "must-not-copy"
        ]))
        XCTAssertEqual(merged["query"] as? String, "content query")
        XCTAssertEqual(merged["provider"] as? String, "Brave")
        XCTAssertEqual((merged["results"] as? [[String: Any]])?.count, 1)
        XCTAssertNil(merged["access_token_handle"])
        XCTAssertNil(merged["encrypted_content"])
        let minimal = EmbedRecord.parseContent(ChatEmbedStreamCoordinator.processingEmbedContent("app_id: images\nskill_id: search", fields: ["query": "actual wire query"]))
        XCTAssertEqual(minimal["query"] as? String, "actual wire query")
    }
}
