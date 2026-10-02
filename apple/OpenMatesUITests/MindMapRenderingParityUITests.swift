// Actual native MindMap rendering evidence against the captured narrow/wide web fixture.
// Web sources: MindMapEmbedFullscreen.svelte, MindMapCanvas.svelte, mindMapContent.ts
// Specification: specifications/features/chats/specification.yml
import XCTest
import UIKit

@MainActor final class MindMapRenderingParityUITests: XCTestCase {
    override func setUpWithError() throws { continueAfterFailure = false }
    override func tearDownWithError() throws { XCUIDevice.shared.orientation = .portrait }

    // contract-test: supporting surface=gui.apple assertions=chats.surface.semantic-parity
    func testPortraitTopDownGraphAndCompactZoomControls() {
        XCUIDevice.shared.orientation = .portrait
        let app = launch(surface: "fullscreen")
        assertTopDownGraph(app)
        let controls = app.descendants(matching: .any)["mindmap-zoom-controls"].firstMatch
        XCTAssertTrue(controls.exists)
        XCTAssertLessThanOrEqual(controls.frame.height, 64)
        XCTAssertLessThan(controls.frame.width, app.frame.width - 32)
        XCTAssertGreaterThanOrEqual(controls.frame.minX, app.frame.minX)
        XCTAssertLessThanOrEqual(controls.frame.maxX, app.frame.maxX)
        XCTAssertTrue(app.buttons["mindmap-zoom-reset"].isHittable)
        XCTAssertTrue(app.buttons["mindmap-zoom-in"].isHittable)
        let root = app.descendants(matching: .any)["mindmap-node-launch"].firstMatch
        let fittedWidth = root.frame.width
        app.buttons["mindmap-zoom-in"].tap()
        XCTAssertGreaterThan(root.frame.width, fittedWidth)
        app.buttons["mindmap-zoom-reset"].tap()
        XCTAssertEqual(root.frame.width, fittedWidth, accuracy: 1)
        let canvas = app.descendants(matching: .any)["mindmap-fullscreen-canvas"].firstMatch
        XCTAssertLessThanOrEqual(canvas.frame.maxX, app.frame.maxX)
        let beforePan = root.frame.midX
        canvas.coordinate(withNormalizedOffset: CGVector(dx: 0.5, dy: 0.75))
            .press(forDuration: 0.1, thenDragTo: canvas.coordinate(withNormalizedOffset: CGVector(dx: 0.6, dy: 0.75)))
        XCTAssertGreaterThan(root.frame.midX, beforePan + 10)
        app.buttons["mindmap-zoom-reset"].tap()
        XCTAssertEqual(root.frame.midX, beforePan, accuracy: 2)
        XCTAssertEqual(controls.descendants(matching: .button).count, 3)
        capture("MindMap fullscreen portrait top down and node icons")
        app.buttons["mindmap-collapse-launch"].tap()
        XCTAssertTrue(app.descendants(matching: .any)["mindmap-node-launch"].exists)
        XCTAssertFalse(app.descendants(matching: .any)["mindmap-node-build"].exists)
        XCTAssertFalse(app.descendants(matching: .any)["mindmap-node-copy"].exists)
        XCTAssertEqual(app.buttons["mindmap-collapse-launch"].label, "Expand Launch Plan")
        capture("MindMap fullscreen collapsed descendants hidden")
        app.buttons["mindmap-collapse-launch"].tap()
        let expanded = XCTNSPredicateExpectation(predicate: NSPredicate(format: "label == %@", "Collapse Launch Plan"),
                                                object: app.buttons["mindmap-collapse-launch"])
        XCTAssertEqual(XCTWaiter.wait(for: [expanded], timeout: 5), .completed)
        capture("MindMap fullscreen expanded root and restored tree")
        let hierarchy = XCTAttachment(string: app.debugDescription)
        hierarchy.name = "MindMap reexpanded actual accessibility frames"
        hierarchy.lifetime = .keepAlways
        add(hierarchy)
        assertTopDownGraph(app)
        XCTAssertEqual(root.frame.width, fittedWidth, accuracy: 1)
    }

    // contract-test: supporting surface=gui.apple assertions=chats.surface.semantic-parity
    func testLandscapeTopDownGraphCapture() {
        XCUIDevice.shared.orientation = .landscapeLeft
        let app = launch(surface: "fullscreen")
        assertTopDownGraph(app)
        let canvas = app.descendants(matching: .any)["mindmap-fullscreen-canvas"].firstMatch
        XCTAssertLessThanOrEqual(canvas.frame.maxX, app.frame.maxX)
        capture("MindMap fullscreen landscape top down and node icons")
    }

    // contract-test: supporting surface=gui.apple assertions=chats.surface.semantic-parity
    func testPreviewFitsAllGraphLevelsWithoutInteractiveCollapseControls() {
        XCUIDevice.shared.orientation = .portrait
        let app = launch(surface: "preview", variant: "finished")
        let canvas = app.descendants(matching: .any)["mindmap-rendered-preview"].firstMatch
        XCTAssertTrue(canvas.waitForExistence(timeout: 10))
        assertTopDownGraph(app)
        XCTAssertEqual(app.staticTexts["embed-basic-info-title"].label, "Launch Plan")
        let launch = app.descendants(matching: .any)["mindmap-node-launch"].firstMatch
        let copy = app.descendants(matching: .any)["mindmap-node-copy"].firstMatch
        XCTAssertGreaterThanOrEqual(launch.frame.minY, canvas.frame.minY - 1)
        XCTAssertLessThanOrEqual(copy.frame.maxY, canvas.frame.maxY + 1)
        XCTAssertFalse(app.buttons["mindmap-collapse-launch"].exists)
        capture("MindMap preview all levels fitted")
    }

    // contract-test: supporting surface=gui.apple assertions=chats.surface.semantic-parity
    func testProcessingPreviewKeepsInvalidSourceVisibleAndProcessingFooter() {
        let app = launch(surface: "preview")
        XCTAssertTrue(app.staticTexts["Invalid mind map JSON"].waitForExistence(timeout: 10))
        XCTAssertTrue(app.staticTexts["Processing..."].exists)
        XCTAssertEqual(app.staticTexts["embed-basic-info-title"].label, "Mind Map")
        XCTAssertFalse(app.descendants(matching: .any)["mindmap-node-launch"].exists)
        capture("MindMap processing preview invalid source and processing footer")
    }

    // contract-test: supporting surface=gui.apple assertions=chats.surface.semantic-parity
    func testMindMapDownloadExportsCanonicalFileThroughNarrowMoreMenu() {
        XCUIDevice.shared.orientation = .portrait
        let app = launch(surface: "fullscreen")
        XCTAssertTrue(app.descendants(matching: .any)["mindmap-node-launch"].waitForExistence(timeout: 10))
        let more = app.buttons["embed-more-button"]
        XCTAssertTrue(more.waitForExistence(timeout: 5))
        more.tap()
        let download = app.buttons["embed-download-button"]
        XCTAssertTrue(download.waitForExistence(timeout: 5))
        XCTAssertTrue(download.isHittable)
        capture("MindMap narrow More canonical download action")
        download.tap()
        XCTAssertTrue(app.otherElements["ShareSheet.RemoteContainerView"].firstMatch.waitForExistence(timeout: 8))
        let filename = app.descendants(matching: .any).matching(NSPredicate(
            // The native file preview shows the basename above its file size.
            // NativeMindMapDownloadFileTests verifies the extension and file bytes.
            format: "identifier == %@ AND label == %@", "LP.CaptionBar.TopCaption", "launch-plan")).firstMatch
        XCTAssertTrue(filename.waitForExistence(timeout: 5))
        XCTAssertTrue(app.descendants(matching: .any).matching(NSPredicate(
            format: "identifier == %@ AND label == %@", "LP.CaptionBar.BottomCaption", "1 KB")).firstMatch.exists)
        XCTAssertTrue(app.cells.matching(NSPredicate(format: "label == %@", "Save to Files")).firstMatch.isHittable)
        capture("MindMap canonical ommindmap system file export")
    }

    private func launch(surface: String, variant: String = "default") -> XCUIApplication {
        let app = XCUIApplication()
        app.launchArguments = ["--dev-preview", "embeds", "--dev-preview-app", "mindmaps",
                               "--embed-registry-key", "mindmaps-mindmap", "--embed-surface", surface, "--embed-variant", variant,
                               "--ui-test-embed-presentation",
                               "--dev-preview-theme", "light", "-AppleLanguages", "(en)", "-AppleLocale", "en_US"]
        app.launch()
        if surface == "fullscreen" {
            let presentation = app.descendants(matching: .any)["embed-presentation-state"].firstMatch
            XCTAssertTrue(presentation.waitForExistence(timeout: 5))
            let ready = XCTNSPredicateExpectation(predicate: NSPredicate(format: "label == %@", "ready"), object: presentation)
            XCTAssertEqual(XCTWaiter.wait(for: [ready], timeout: 5), .completed)
        }
        return app
    }

    private func assertTopDownGraph(_ app: XCUIApplication) {
        let root = app.descendants(matching: .any)["mindmap-node-launch"].firstMatch
        let build = app.descendants(matching: .any)["mindmap-node-build"].firstMatch
        let copy = app.descendants(matching: .any)["mindmap-node-copy"].firstMatch
        XCTAssertTrue(root.waitForExistence(timeout: 10))
        XCTAssertTrue(build.exists)
        XCTAssertTrue(copy.exists)
        XCTAssertLessThan(root.frame.midY, build.frame.midY)
        XCTAssertLessThan(build.frame.midY, copy.frame.midY)
        XCTAssertEqual(root.frame.midX, build.frame.midX, accuracy: 2,
                       "The symmetric fixture's root must center above the middle branch")
    }

    private func capture(_ name: String) {
        let attachment = XCTAttachment(screenshot: XCUIScreen.main.screenshot())
        attachment.name = name
        attachment.lifetime = .keepAlways
        add(attachment)
    }
}
