// Unit coverage for skill, application, code, and file/media parity fixtures.
// These tests use debug-only synthetic fixtures and never touch provider APIs,
// user files, private hosts, code-run logs, secrets, or network state.

import XCTest
@testable import OpenMates

final class SkillApplicationParityTests: XCTestCase {
    func testShortcutSkillFormatterUnwrapsRestSdkEnvelope() throws {
        let response: [String: Any] = [
            "success": true,
            "data": [
                "results": [
                    [
                        "id": 1,
                        "results": [
                            [
                                "title": "Open Air Concert",
                                "date_start": "2026-07-10T19:00:00Z",
                                "venue": [
                                    "name": "Park Stage",
                                    "city": "Berlin",
                                ],
                            ],
                        ],
                        "total_available": 1,
                    ],
                ],
            ],
            "credits_charged": 1,
        ]

        let formatted = SkillFormatter.formatResults(response, type: "events")

        XCTAssertFalse(formatted.contains("No details available"))
        XCTAssertTrue(formatted.contains("Open Air Concert"))
        XCTAssertTrue(formatted.contains("Starts: 2026-07-10T19:00:00Z"))
        XCTAssertTrue(formatted.contains("Venue: Park Stage, Berlin"))
    }

    func testShortcutSkillFormatterPreservesUnknownPayloadAsJson() throws {
        let response: [String: Any] = [
            "success": true,
            "data": [
                "answer": "42",
                "confidence": "high",
            ],
        ]

        let formatted = SkillFormatter.formatResults(response, type: "unknown")

        XCTAssertFalse(formatted.contains("No details available"))
        XCTAssertTrue(formatted.contains("\"answer"))
        XCTAssertTrue(formatted.contains("42"))
    }

    func testCodeFixturesClassifyApplicationCodeAndDocsStates() throws {
        let codeSkills = DevEmbedPreviewFixtures.skills(for: .code)
        let skillsById = Dictionary(uniqueKeysWithValues: codeSkills.map { ($0.id, $0) })

        let code = try XCTUnwrap(skillsById["code-code"]?.primaryEmbed)
        XCTAssertEqual(code.type, EmbedType.codeCode.rawValue)
        XCTAssertEqual(code.appId, "code")
        XCTAssertEqual(code.rawData?["language"]?.value as? String, "svelte")
        XCTAssertEqual(code.rawData?["filename"]?.value as? String, "MyComponent.svelte")
        XCTAssertFalse(code.isAppSkillUse)

        let application = try XCTUnwrap(skillsById["code-application"]?.primaryEmbed)
        XCTAssertEqual(application.type, EmbedType.codeApplication.rawValue)
        XCTAssertEqual(application.appId, "code")
        XCTAssertEqual(application.status, .finished)
        XCTAssertEqual(application.rawData?["title"]?.value as? String, "Habit Garden")
        XCTAssertEqual(application.rawData?["framework"]?.value as? String, "vite")
        XCTAssertFalse(application.isAppSkillUse)

        let docs = try XCTUnwrap(skillsById["code-get-docs"]?.primaryEmbed)
        XCTAssertTrue(docs.isAppSkillUse)
        XCTAssertEqual(docs.type, EmbedType.codeGetDocs.rawValue)
        XCTAssertEqual(docs.appId, "code")
        XCTAssertEqual(docs.skillId, "get_docs")
        XCTAssertEqual(docs.rawData?["library"]?.value as? String, "svelte")
    }

    func testCompositeSkillFixturesPreserveChildEmbedRelationships() throws {
        let webSearch = try XCTUnwrap(
            DevEmbedPreviewFixtures.skills(for: .web).first { $0.id == "web-search" }
        )

        XCTAssertTrue(webSearch.primaryEmbed.isAppSkillUse)
        XCTAssertEqual(webSearch.primaryEmbed.type, EmbedType.webSearch.rawValue)
        XCTAssertEqual(webSearch.primaryEmbed.childEmbedIds, webSearch.childEmbeds.map(\.id))
        XCTAssertEqual(webSearch.childEmbeds.count, 3)

        for child in webSearch.childEmbeds {
            XCTAssertEqual(child.type, EmbedType.webWebsite.rawValue)
            XCTAssertEqual(child.parentEmbedId, webSearch.primaryEmbed.id)
            XCTAssertNotNil(webSearch.allRecords[child.id])
        }
    }

    func testRelatedEmbedGraphIncludesChildrenForReferencedCompositeParent() throws {
        let webSearch = try XCTUnwrap(
            DevEmbedPreviewFixtures.skills(for: .web).first { $0.id == "web-search" }
        )
        let shuffled = Array(webSearch.childEmbeds.reversed()) + [webSearch.primaryEmbed]

        let related = EmbedRecord.relatedRecords(
            referencedIds: [webSearch.primaryEmbed.id],
            from: shuffled,
            context: "test.relatedGraph"
        )

        XCTAssertEqual(Set(related.map(\.id)), Set(webSearch.allRecords.keys))
    }

    func testSearchPreviewModelUsesParentPreviewMetadataWithoutChildHydration() throws {
        let parent = EmbedRecord(
            id: "metadata-only-news-parent",
            type: EmbedType.newsSearch.rawValue,
            status: .finished,
            data: .raw([
                "app_id": AnyCodable("news"),
                "skill_id": AnyCodable("search"),
                "query": AnyCodable("privacy ai"),
                "provider": AnyCodable("Brave Search"),
                "result_count": AnyCodable(2),
                "embed_ids": AnyCodable(["child-1", "child-2"]),
                "preview_results": AnyCodable([
                    [
                        "title": "OpenMates privacy launch",
                        "url": "https://news.example/openmates",
                        "favicon": "https://news.example/favicon.ico",
                    ]
                ]),
            ]),
            parentEmbedId: nil,
            appId: "news",
            skillId: "search",
            embedIds: "child-1|child-2",
            createdAt: "2026-06-21T12:00:00Z"
        )

        let model = SearchSkillPreviewModel(embed: parent, allEmbedRecords: [parent.id: parent])

        XCTAssertEqual(model.previewResultCount, 2)
        XCTAssertEqual(model.websiteResults.map(\.title), ["OpenMates privacy launch"])
        XCTAssertTrue(model.websiteResults.first?.faviconURL?.contains("news.example") == true)
    }

    func testFileMediaFixturesUseSyntheticPublicPayloads() throws {
        let imageUpload = try XCTUnwrap(
            DevEmbedPreviewFixtures.skills(for: .images).first { $0.id == "images-upload" }?.primaryEmbed
        )
        XCTAssertEqual(imageUpload.type, EmbedType.image.rawValue)
        XCTAssertEqual(imageUpload.rawData?["filename"]?.value as? String, "golden-gate-sunset.jpg")
        XCTAssertNil(imageUpload.rawData?["private_url"])
        XCTAssertNil(imageUpload.rawData?["secret"])

        let pdf = try XCTUnwrap(
            DevEmbedPreviewFixtures.skills(for: .pdf).first { $0.id == "pdf" }?.primaryEmbed
        )
        XCTAssertEqual(pdf.type, EmbedType.pdf.rawValue)
        XCTAssertEqual(pdf.rawData?["filename"]?.value as? String, "Q4 2025 Report.pdf")
        XCTAssertEqual(pdf.rawData?["page_count"]?.value as? Int, 18)

        let generatedVideo = try XCTUnwrap(
            DevEmbedPreviewFixtures.skills(for: .videos).first { $0.id == "videos-generate" }?.primaryEmbed
        )
        XCTAssertTrue(generatedVideo.isAppSkillUse)
        XCTAssertEqual(generatedVideo.type, EmbedType.videosGenerate.rawValue)
        XCTAssertEqual(generatedVideo.rawData?["title"]?.value as? String, "Product launch promo")
    }

    func testDiagramsMermaidFixtureDecodesSourcePayload() throws {
        let diagramsSkills = DevEmbedPreviewFixtures.skills(for: .diagrams)
        let mermaid = try XCTUnwrap(diagramsSkills.first { $0.id == "diagrams-mermaid" }?.primaryEmbed)

        XCTAssertEqual(mermaid.type, EmbedType.diagramsMermaid.rawValue)
        XCTAssertEqual(EmbedType.diagramsMermaid.appId, "diagrams")
        XCTAssertEqual(EmbedType.diagramsMermaid.displayName, "Diagram")
        XCTAssertEqual(mermaid.appId, "diagrams")
        XCTAssertEqual(mermaid.skillId, "mermaid")
        XCTAssertEqual(mermaid.rawData?["title"]?.value as? String, "Signup Flow")
        XCTAssertEqual(mermaid.rawData?["diagram_kind"]?.value as? String, "sequenceDiagram")
        XCTAssertTrue((mermaid.rawData?["diagram_code"]?.value as? String ?? "").contains("User->>App"))
    }
}
