// Cross-client contract tests for the native ComposerDocument adapter.
// The same synthetic fixture is consumed by web Vitest and Swift XCTest.
// Canonical markdown remains the durable format; native editor state is transient.
// These tests intentionally fail to compile until the native adapter exists.
// No private content, credentials, or production encryption material is used.

import XCTest
@testable import OpenMates

final class NativeComposerDocumentTests: XCTestCase {
    // contract-test: supporting surface=gui.apple assertions=message-input.recording.lifecycle,message-input.drafts.preview-persistence
    func testRestoredRecordingReferenceUsesNativePreviewFamilyAndKeepsWireType() throws {
        let markdown = "```json\n{\"type\":\"audio-recording\",\"embed_id\":\"recording-1\"}\n```"
        let document = try ComposerMarkdownAdapter.parse(markdown)
        let node = try XCTUnwrap(document.nodes.first(where: { $0.kind == "embed" }))

        XCTAssertEqual(node.embedType, "recording")
        XCTAssertEqual(node.contentRef, "embed:recording-1")
        XCTAssertNotNil(AppleComposerRendererRegistry.shared.descriptor(for: node.embedType ?? ""))
        XCTAssertEqual(try ComposerMarkdownAdapter.serialize(document), markdown)
    }

    // contract-test: supporting surface=gui.apple assertions=message-input.drafts.preview-persistence
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

    // contract-test: supporting surface=gui.apple assertions=message-input.drafts.preview-persistence
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

    // contract-test: supporting surface=gui.apple assertions=message-input.drafts.preview-persistence
    func testInvalidSharedDocumentsFailWithoutPartialSerialization() throws {
        for invalidCase in try loadFixture().invalidDocuments {
            XCTAssertThrowsError(
                try ComposerMarkdownAdapter.serialize(invalidCase.document),
                invalidCase.id
            ) { error in
                XCTAssertEqual(
                    (error as? ComposerDocumentError)?.code,
                    invalidCase.expectedError,
                    invalidCase.id
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
    let invalidDocuments: [InvalidDocumentFixture]

    enum CodingKeys: String, CodingKey {
        case schemaVersion = "schema_version"
        case cases
        case invalidDocuments = "invalid_documents"
    }
}

private struct InvalidDocumentFixture: Decodable {
    let id: String
    let expectedError: String
    let document: ComposerDocumentV1

    enum CodingKeys: String, CodingKey {
        case id
        case expectedError = "expected_error"
        case document
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
