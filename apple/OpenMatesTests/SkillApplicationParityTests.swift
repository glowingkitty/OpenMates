// Unit coverage for skill, application, code, and file/media parity fixtures.
// These tests use debug-only synthetic fixtures and never touch provider APIs,
// user files, private hosts, code-run logs, secrets, or network state.

import XCTest
@testable import OpenMates

final class SkillApplicationParityTests: XCTestCase {
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
}
