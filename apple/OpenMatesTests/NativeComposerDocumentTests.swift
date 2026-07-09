// Cross-client contract tests for the native ComposerDocument adapter.
// The same synthetic fixture is consumed by web Vitest and Swift XCTest.
// Canonical markdown remains the durable format; native editor state is transient.
// These tests intentionally fail to compile until the native adapter exists.
// No private content, credentials, or production encryption material is used.

import XCTest
@testable import OpenMates

final class NativeComposerDocumentTests: XCTestCase {
    func testSharedFixturesParseAndSerializeCanonically() throws {
        let fixture = try loadFixture()
        XCTAssertEqual(fixture.schemaVersion, 1)

        for testCase in fixture.cases {
            let document = try ComposerMarkdownAdapter.parse(testCase.canonicalMarkdown)

            XCTAssertEqual(document, testCase.document, testCase.id)
            XCTAssertEqual(
                try ComposerMarkdownAdapter.serialize(document),
                testCase.canonicalMarkdown,
                testCase.id
            )
        }
    }

    func testSharedSelectionFixturesUseUTF16Offsets() throws {
        for testCase in try loadFixture().cases {
            for selection in testCase.selectionFixtures {
                XCTAssertEqual(
                    ComposerPositionMap.utf16Length(selection.source),
                    selection.utf16Offset,
                    "\(testCase.id)/\(selection.label)"
                )
            }
        }
    }

    private func loadFixture() throws -> ComposerFixture {
        let repositoryRoot = URL(fileURLWithPath: #filePath)
            .deletingLastPathComponent()
            .deletingLastPathComponent()
            .deletingLastPathComponent()
        let fixtureURL = repositoryRoot
            .appendingPathComponent("shared/composer/fixtures/composer-document-v1.json")
        return try JSONDecoder().decode(ComposerFixture.self, from: Data(contentsOf: fixtureURL))
    }
}

private struct ComposerFixture: Decodable {
    let schemaVersion: Int
    let cases: [ComposerFixtureCase]

    enum CodingKeys: String, CodingKey {
        case schemaVersion = "schema_version"
        case cases
    }
}

private struct ComposerFixtureCase: Decodable {
    let id: String
    let canonicalMarkdown: String
    let document: ComposerDocumentV1
    let selectionFixtures: [SelectionFixture]

    enum CodingKeys: String, CodingKey {
        case id
        case canonicalMarkdown = "canonical_markdown"
        case document
        case selectionFixtures = "selection_fixtures"
    }
}

private struct SelectionFixture: Decodable {
    let label: String
    let source: String
    let utf16Offset: Int

    enum CodingKeys: String, CodingKey {
        case label
        case source
        case utf16Offset = "utf16_offset"
    }
}
