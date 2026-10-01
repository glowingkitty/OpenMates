// Focused payload and local-rendering guards for the Mermaid direct embed.
// Specification: specifications/features/specifications/specification.yml
// Assertions: contracts.diagrams.private-rendering, contracts.diagrams.revision-pinned-editing

import XCTest
@testable import OpenMates

@MainActor
final class MermaidDiagramParityTests: XCTestCase {
    // contract-test: supporting surface=gui.apple assertions=contracts.diagrams.revision-pinned-editing
    func testMermaidPayloadKeepsEditableSourceAndAliases() {
        let diagram = MermaidDiagramContent(data: [
            "title": AnyCodable("Signup Flow"),
            "code": AnyCodable("sequenceDiagram\nUser->>App: Sign in"),
            "status": AnyCodable("finished")
        ])

        XCTAssertEqual(diagram.title, "Signup Flow")
        XCTAssertEqual(diagram.code, "sequenceDiagram\nUser->>App: Sign in")
        XCTAssertEqual(diagram.kind, "sequenceDiagram")
        XCTAssertEqual(diagram.status, "finished")
    }

    // contract-test: supporting surface=gui.apple assertions=contracts.diagrams.private-rendering
    func testLocalMermaidDocumentEncodesSourceAndDisablesExternalLoads() throws {
        let source = "sequenceDiagram\nUser->>App: </script><script>alert(1)</script>"
        let document = try XCTUnwrap(MermaidWebDocument.make(source: source, theme: "dark", isPreview: false, zoom: 1.2))

        XCTAssertTrue(MermaidWebDocument.isAvailable)
        XCTAssertTrue(document.contains(Data(source.utf8).base64EncodedString()))
        XCTAssertFalse(document.contains(source))
        XCTAssertTrue(document.contains("connect-src 'none'"))
        XCTAssertTrue(document.contains("frame-src 'none'"))
        XCTAssertTrue(document.contains("securityLevel:'strict'"))
        XCTAssertTrue(document.contains("new DOMParser()"))
        XCTAssertTrue(document.contains("window.webkit.messageHandlers.mermaid"))
    }
}
