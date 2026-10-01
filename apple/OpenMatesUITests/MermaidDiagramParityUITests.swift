// Rendered Mermaid preview and fullscreen smoke test using the local debug fixture.
// Specification: specifications/features/specifications/specification.yml
// Assertions: contracts.diagrams.private-rendering, contracts.diagrams.revision-pinned-editing

import XCTest

@MainActor
final class MermaidDiagramParityUITests: XCTestCase {
    override func setUpWithError() throws { continueAfterFailure = false }

    // contract-test: supporting surface=gui.apple assertions=contracts.diagrams.revision-pinned-editing,contracts.diagrams.private-rendering
    func testMermaidPreviewAndFullscreenRenderWithSourceToggle() {
        let app = XCUIApplication()
        launchCanonical(app, surface: "preview")

        let preview = app.descendants(matching: .any)["dev-embed-canonical-preview"]
        XCTAssertTrue(preview.waitForExistence(timeout: 8))
        let previewCanvas = app.webViews["mermaid-rendered-preview"]
        XCTAssertTrue(previewCanvas.waitForExistence(timeout: 20), "Mermaid preview canvas was not exposed")
        XCTAssertTrue(
            previewCanvas.staticTexts["Enter email address"].waitForExistence(timeout: 15),
            "Mermaid SVG labels never rendered in the preview"
        )
        attachScreenshot(name: "Mermaid rendered preview")
        app.terminate()

        launchCanonical(app, surface: "fullscreen")
        let fullscreen = app.descendants(matching: .any)["dev-embed-canonical-fullscreen"]
        XCTAssertTrue(fullscreen.waitForExistence(timeout: 8))
        let panel = app.webViews["mermaid-rendered-panel"]
        XCTAssertTrue(panel.waitForExistence(timeout: 20), "Fullscreen diagram canvas was not exposed")
        let renderReady = app.descendants(matching: .any)["mermaid-render-ready"]
        XCTAssertTrue(renderReady.waitForExistence(timeout: 15), "Fullscreen diagram did not finish painting")
        XCTAssertTrue(
            panel.staticTexts["Enter email address"].waitForExistence(timeout: 15),
            "Mermaid SVG labels never rendered in fullscreen"
        )
        attachScreenshot(name: "Mermaid rendered fullscreen initial")

        let zoomIn = app.buttons["mermaid-zoom-in"]
        XCTAssertTrue(zoomIn.exists && zoomIn.isHittable)
        zoomIn.tap()
        let resetZoom = app.buttons["mermaid-fit"]
        XCTAssertTrue(resetZoom.exists && resetZoom.isHittable)
        resetZoom.tap()

        let sourceToggle = app.buttons["mermaid-toggle-source"]
        XCTAssertTrue(sourceToggle.exists && sourceToggle.isHittable)
        sourceToggle.tap()
        XCTAssertTrue(app.descendants(matching: .any)["mermaid-source-panel"].waitForExistence(timeout: 5))
        XCTAssertFalse(renderReady.exists, "Diagram readiness persisted while source view was active")
        XCTAssertTrue(app.staticTexts.containing(NSPredicate(format: "label CONTAINS %@", "User->>App")).firstMatch.exists)

        sourceToggle.tap()
        XCTAssertTrue(panel.waitForExistence(timeout: 20))
        XCTAssertTrue(renderReady.waitForExistence(timeout: 20), "Restored diagram did not finish painting")
        XCTAssertTrue(
            panel.staticTexts["Enter email address"].waitForExistence(timeout: 15),
            "Mermaid SVG labels did not return after source view"
        )
        attachScreenshot(name: "Mermaid rendered fullscreen restored")
    }

    private func launchCanonical(_ app: XCUIApplication, surface: String) {
        app.launchArguments = [
            "--dev-preview", "embeds", "--dev-preview-app", "diagrams",
            "--embed-registry-key", "diagrams-mermaid", "--embed-surface", surface
        ]
        app.launchEnvironment["DEV_PREVIEW"] = "embeds"
        app.launchEnvironment["DEV_PREVIEW_APP"] = "diagrams"
        app.launch()
    }

    private func attachScreenshot(name: String) {
        let attachment = XCTAttachment(screenshot: XCUIScreen.main.screenshot())
        attachment.name = name
        attachment.lifetime = .keepAlways
        add(attachment)
    }
}
