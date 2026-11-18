// Tests of the creative parity helpers: the image version badge label and the
// SVG code-embed document (kind detection, namespace repair, locked-down page).
import XCTest
@testable import OpenMates

final class CreativeParityTests: XCTestCase {
    // contract-test: supporting surface=gui.apple assertions=images-generate.revision.message-shows-its-version
    func testVersionBadgeOnlyWhenSeveralVersions() {
        XCTAssertNil(ImageVersionBadgeState.label(version: 1, headVersion: 1))
        XCTAssertNil(ImageVersionBadgeState.label(version: nil, headVersion: 3))
        XCTAssertNil(ImageVersionBadgeState.label(version: 2, headVersion: nil))
        XCTAssertEqual(ImageVersionBadgeState.label(version: 2, headVersion: 3), "v2")
        XCTAssertEqual(ImageVersionBadgeState.label(version: 3, headVersion: 3), "v3")
    }

    // contract-test: supporting surface=gui.apple assertions=interactive-html.render.vector-image-and-progressive-streaming
    func testSvgKindDetection() {
        XCTAssertTrue(SvgEmbedDocument.isSvg(language: "SVG", filename: nil, code: ""))
        XCTAssertTrue(SvgEmbedDocument.isSvg(language: "text", filename: "logo.svg", code: ""))
        XCTAssertTrue(SvgEmbedDocument.isSvg(language: "xml", filename: nil, code: "  <svg></svg>"))
        XCTAssertFalse(SvgEmbedDocument.isSvg(language: "xml", filename: nil, code: "<note/>"))
        XCTAssertFalse(SvgEmbedDocument.isSvg(language: "html", filename: nil, code: "<svg></svg>"))
    }

    // contract-test: supporting surface=gui.apple assertions=interactive-html.render.vector-image-and-progressive-streaming
    func testSvgNamespaceAddedOnlyWhenMissing() {
        XCTAssertEqual(SvgEmbedDocument.prepared("<svg viewBox=\"0 0 1 1\"></svg>"),
                       "<svg xmlns=\"http://www.w3.org/2000/svg\" viewBox=\"0 0 1 1\"></svg>")
        let withNamespace = "<svg xmlns=\"http://www.w3.org/2000/svg\"></svg>"
        XCTAssertEqual(SvgEmbedDocument.prepared(withNamespace), withNamespace)
        XCTAssertNil(SvgEmbedDocument.prepared("<p>no vector here</p>"))
    }

    // contract-test: supporting surface=gui.apple assertions=interactive-html.security.isolated-and-offline
    func testSvgPageIsImageOnlyWithLockedCsp() throws {
        let html = try XCTUnwrap(SvgEmbedDocument.html(for: "<svg><script>alert(1)</script></svg>"))
        XCTAssertTrue(html.contains("default-src 'none'; img-src data:"))
        XCTAssertFalse(html.contains("<script>"), "source is only embedded base64 inside an img")
        XCTAssertTrue(html.contains("<img alt=\"\" src=\"data:image/svg+xml;base64,"))
    }

    // contract-test: supporting surface=gui.apple assertions=interactive-html.render.vector-image-and-progressive-streaming
    func testStreamingSvgIsClosedByTheCoreAndHeadlessSourceKeepsLastFrame() throws {
        let partial = try XCTUnwrap(progressiveSvg(source: "<svg viewBox=\"0 0 4 4\"><g><rect width=\"2\" hei", complete: false))
        XCTAssertTrue(partial.hasSuffix("</g></svg>"), partial)
        XCTAssertNil(progressiveSvg(source: "<sv", complete: false))
    }
}
