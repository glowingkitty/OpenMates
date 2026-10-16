import CryptoKit
import XCTest
@testable import OpenMates

@MainActor
final class ProjectReadmeTests: XCTestCase {
    // contract-test: supporting surface=gui.apple assertions=projects.surface.semantic-parity
    func testReadmeRetainsBlocksAndImagesWithoutTurningCodeIntoImages() {
        let markdown = "# Project\n\nParagraph **bold**\n\n## Features\n\n- First\n- Second\n\n```swift\n![code](fake.png)\n```\n\n![Preview](assets/preview.png)"
        XCTAssertEqual(ProjectReadmeDocument.parse(markdown), [
            .markdown(.header(level: 1, text: "Project")),
            .markdown(.paragraph("Paragraph **bold**")),
            .markdown(.header(level: 2, text: "Features")),
            .markdown(.unorderedList(["First", "Second"])),
            .markdown(.codeBlock(language: "swift", code: "![code](fake.png)")),
            .markdown(.paragraph("![Preview](assets/preview.png)")),
        ])
        XCTAssertEqual(images(in: ProjectReadmeDocument.inlineParts("![Preview](assets/preview.png)")),
            [ProjectReadmeImage(source: "assets/preview.png", alt: "Preview")])
        XCTAssertTrue(images(in: ProjectReadmeDocument.inlineParts("`![code](fake.png)`")).isEmpty)
        XCTAssertTrue(images(in: ProjectReadmeDocument.inlineParts("\\![escaped](fake.png)")).isEmpty)
        let bold = ProjectReadmeDocument.inline("Paragraph **bold**")
        XCTAssertEqual(String(bold.characters), "Paragraph bold")
        XCTAssertTrue(bold.runs.contains { $0.inlinePresentationIntent?.contains(.stronglyEmphasized) == true })
    }

    // contract-test: supporting surface=gui.apple assertions=projects.surface.semantic-parity
    func testReferenceImagesResolveInListsTablesAndParagraphs() {
        let source = "![Logo][ brand ]\n\n- ![Logo][]\n\n| Preview |\n| --- |\n| ![Logo] |\n\n[BRAND]: <assets/logo.png>\n[logo]: assets/logo.png"
        let document = ProjectReadmeDocument.parse(source)
        let allImages = document.flatMap(ProjectReadmeDocument.textContents).flatMap { images(in: ProjectReadmeDocument.inlineParts($0)) }
        XCTAssertEqual(allImages.count, 3)
        XCTAssertTrue(allImages.allSatisfy { $0.source == "assets/logo.png" })
        XCTAssertTrue(document.contains { if case .markdown(.unorderedList) = $0 { return true }; return false })
        XCTAssertTrue(document.contains { if case .markdown(.table) = $0 { return true }; return false })
        let code = ProjectReadmeDocument.parse("```markdown\n[logo]: fake.png\n![Logo][logo]\n```")
        XCTAssertEqual(code, [.markdown(.codeBlock(language: "markdown", code: "[logo]: fake.png\n![Logo][logo]"))])
    }

    // contract-test: supporting surface=gui.apple assertions=projects.surface.semantic-parity
    func testOrdinaryReferenceLinksResolveAndKeepUnsafeSchemesInert() {
        let parts = ProjectReadmeDocument.parse("[Docs][docs] and [Unsafe][bad]\n\n[docs]: https://example.org/docs\n[bad]: javascript:alert")
        let inline = parts.flatMap(ProjectReadmeDocument.textContents).map(ProjectReadmeDocument.inline)
        let links = inline.flatMap { $0.runs.compactMap { $0.link } }
        XCTAssertEqual(links, [URL(string: "https://example.org/docs")!])
        XCTAssertTrue(inline.map { String($0.characters) }.joined().contains("Unsafe"))
    }

    // contract-test: supporting surface=gui.apple assertions=projects.access.explicit-context,projects.surface.semantic-parity
    func testReloadIdentityChangesEvenWithSameMarkdownAndImagePath() {
        let first = ProjectWorkspaceReadme(markdown: "![Preview](assets/preview.png)", truncated: false, origin: "stored")
        let reloaded = ProjectWorkspaceReadme(markdown: first.markdown, truncated: false, origin: "stored")
        XCTAssertNotEqual(first.renderID, reloaded.renderID)
        XCTAssertNotEqual(first, reloaded)
    }

    // contract-test: supporting surface=gui.apple assertions=projects.surface.semantic-parity
    func testLinkedImagesRemainImagesWithSafeNavigation() {
        let parts = ProjectReadmeDocument.inlineParts("[![Badge](assets/badge.png)](https://example.org/docs)")
        XCTAssertEqual(parts, [.image(ProjectReadmeImage(source: "assets/badge.png", alt: "Badge", linkURL: URL(string: "https://example.org/docs")))])
        XCTAssertNil(images(in: ProjectReadmeDocument.inlineParts("[![Badge](assets/badge.png)](javascript:alert)"))[0].linkURL)
        let referenced = ProjectReadmeDocument.parse("[![Badge][picture]][docs]\n\n[picture]: assets/badge.png\n[docs]: https://example.org/docs")
        let referenceImages = referenced.flatMap(ProjectReadmeDocument.textContents).flatMap { images(in: ProjectReadmeDocument.inlineParts($0)) }
        XCTAssertEqual(referenceImages.first?.linkURL, URL(string: "https://example.org/docs"))
    }

    // contract-test: supporting surface=gui.apple assertions=projects.surface.semantic-parity
    func testChatProtocolExamplesStayLiteralWithoutInteractiveControls() {
        XCTAssertEqual(ProjectReadmeDocument.parse("[[app_store_group]]"), [.literal("[[app_store_group]]")])
        let examples = ProjectReadmeDocument.parse("```interactive_response\n{\"answer\": \"example\"}\n```\n\n~~~json\n{\"literal\":true}\n~~~")
        XCTAssertEqual(examples, [
            .markdown(.codeBlock(language: "interactive_response", code: "{\"answer\": \"example\"}")),
            .markdown(.codeBlock(language: "json", code: "{\"literal\":true}")),
        ])
    }

    // contract-test: supporting surface=gui.apple assertions=projects.surface.semantic-parity
    func testMixedFenceMarkersAndShortClosersKeepImageSyntaxLiteral() {
        for (opening, inner, closing) in [("```markdown", "~~~", "```"), ("~~~markdown", "```", "~~~"), ("````markdown", "```", "````")] {
            let body = "\(inner)\n![literal](assets/a.png)\n[logo]: assets/private.png\n\(inner)"
            let parts = ProjectReadmeDocument.parse("\(opening)\n\(body)\n\(closing)\n\nAfter")
            XCTAssertEqual(parts, [.markdown(.codeBlock(language: "markdown", code: body)), .markdown(.paragraph("After"))])
            XCTAssertTrue(parts.flatMap(ProjectReadmeDocument.textContents).flatMap { images(in: ProjectReadmeDocument.inlineParts($0)) }.isEmpty)
        }
    }

    // contract-test: supporting surface=gui.apple assertions=projects.access.explicit-context,projects.surface.semantic-parity
    func testImagesUseProxyAndRejectCredentialsAndEscapingPaths() throws {
        let proxy = try XCTUnwrap(ProjectReadmeDocument.publicImageURL("https://example.org/logo.png"))
        XCTAssertEqual(proxy.host, "preview.openmates.org")
        XCTAssertEqual(proxy.path, "/api/v1/image")
        XCTAssertEqual(URLComponents(url: proxy, resolvingAgainstBaseURL: false)?.queryItems?.first?.value, "https://example.org/logo.png")
        for source in ["https://user:password@example.org/a.png", "file:///tmp/a.png", "data:image/png;base64,a", "https://127.0.0.1/a.png", "https://localhost/a.png", "https://[::1]/a.png"] {
            XCTAssertNil(ProjectReadmeDocument.publicImageURL(source))
        }
        XCTAssertEqual(ProjectReadmeDocument.relativePath("./assets/a%20b.png"), "assets/a b.png")
        for source in ["../secret.png", "%2e%2e/secret.png", "/root/a.png", "https://example.org/a.png", "assets/%5Csecret.png", "assets/%00secret.png"] {
            XCTAssertNil(ProjectReadmeDocument.relativePath(source))
        }
        XCTAssertFalse(ProjectReadmeDocument.inline("[Bad](javascript:alert)").runs.contains { $0.link != nil })
        XCTAssertTrue(ProjectReadmeDocument.inline("[Docs](https://example.org)").runs.contains { $0.link != nil })
        XCTAssertEqual(String(ProjectReadmeDocument.inline("<img src=\"private.png\">").characters), "<img src=\"private.png\">")
    }

    // contract-test: supporting surface=gui.apple assertions=projects.access.explicit-context
    func testRemoteImageAssemblesExactBoundedChunksAndVerifiesContentHash() async throws {
        let bytes = Data(repeating: 7, count: 128 * 1024 + 17)
        let hash = SHA256.hash(data: bytes).map { String(format: "%02x", $0) }.joined()
        var offsets: [Int] = []
        let assembled = try await ProjectRemoteSourceClient.assembleReadmeImage { offset in
            offsets.append(offset)
            return self.chunk(bytes, offset: offset, hash: hash)
        }
        XCTAssertEqual(assembled, bytes)
        XCTAssertEqual(offsets, [0, 128 * 1024])
        do {
            _ = try await ProjectRemoteSourceClient.assembleReadmeImage { offset in self.chunk(bytes, offset: offset, hash: "wrong") }
            XCTFail("The actual bytes must match the declared content hash")
        } catch { }
    }

    // contract-test: supporting surface=gui.apple assertions=projects.access.explicit-context
    func testRemoteImageRejectsChangedIdentityAndOversizedPayloads() async {
        for changed in [false, true] {
            do {
                _ = try await ProjectRemoteSourceClient.assembleReadmeImage { offset in
                    let size = changed ? 128 * 1024 + 1 : 2 * 1024 * 1024 + 1
                    return ["size_bytes": size, "offset": offset, "mime_type": "image/png",
                        "content_hash": offset == 0 ? "first" : "changed",
                        "content_base64": Data(repeating: 1, count: offset == 0 ? 128 * 1024 : 1).base64EncodedString()]
                }
                XCTFail("Unbounded or changed remote images must be rejected")
            } catch { }
        }
    }

    private func images(in parts: [ProjectReadmeInlinePart]) -> [ProjectReadmeImage] {
        parts.compactMap { if case .image(let image) = $0 { return image }; return nil }
    }
    private func chunk(_ bytes: Data, offset: Int, hash: String) -> [String: Any] {
        ["size_bytes": bytes.count, "offset": offset, "mime_type": "image/png", "content_hash": hash,
         "content_base64": bytes.subdata(in: offset..<min(bytes.count, offset + 128 * 1024)).base64EncodedString()]
    }
}
