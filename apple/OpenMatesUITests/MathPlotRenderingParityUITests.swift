// Public MathPlot gallery fixture, rendered using the production fullscreen path.
// Specification: specifications/features/chats/specification.yml
// Assertions: chats.surface.semantic-parity

import XCTest

@MainActor
final class MathPlotRenderingParityUITests: XCTestCase {
    override func setUpWithError() throws {
        continueAfterFailure = false
        XCUIDevice.shared.orientation = .portrait
    }

    override func tearDownWithError() throws {
        XCUIDevice.shared.orientation = .portrait
    }

    // contract-test: supporting surface=gui.apple assertions=chats.surface.semantic-parity
    func testMathPlotFullscreenFormulaGuttersAndGraphInNarrowAndWideViewport() {
        let app = XCUIApplication()
        app.launchArguments = ["--dev-preview", "embeds", "--dev-preview-app", "math",
                               "--embed-registry-key", "math-plot", "--embed-surface", "fullscreen",
                               "--dev-preview-theme", "light", "-AppleLanguages", "(en)", "-AppleLocale", "en_US"]
        app.launch()
        waitForOrientation(app, portrait: true)
        let card = app.descendants(matching: .any)["math-plot-formula-card"].firstMatch
        let graph = app.descendants(matching: .any)["math-plot-graph"].firstMatch
        XCTAssertTrue(card.waitForExistence(timeout: 10))
        XCTAssertTrue(graph.waitForExistence(timeout: 5))
        XCTAssertEqual(card.frame.minX, 16, accuracy: 2)
        XCTAssertEqual(card.frame.maxX, app.frame.maxX - 16, accuracy: 2)
        XCTAssertEqual(card.frame.height, 117, accuracy: 3)
        XCTAssertEqual(graph.frame.minX, card.frame.minX, accuracy: 1)
        XCTAssertEqual(graph.frame.width, card.frame.width, accuracy: 1)
        XCTAssertGreaterThanOrEqual(graph.frame.height, 200)
        // Web min-height uses the full100vh even when native header chrome
        // includes a platform status-bar inset. It must not shrink the plot.
        let expectedHeight = max(200, app.frame.height - 196 - 48 - 48 - card.frame.height - 16)
        XCTAssertEqual(graph.frame.height, expectedHeight, accuracy: 2)
        XCTAssertEqual(graph.value as? String, "3")
        XCTAssertFalse(app.descendants(matching: .any)["math-plot-render-error"].exists)
        for index in 0..<3 {
            XCTAssertTrue(app.descendants(matching: .any)["math-plot-formula-\(index)"].exists)
        }
        attach(app, name: "MathPlot narrow serif formulas labeled axes and three curves")
        graph.coordinate(withNormalizedOffset: CGVector(dx: 0.5, dy: 0.5))
            .press(forDuration: 0.05, thenDragTo: graph.coordinate(withNormalizedOffset: CGVector(dx: 0.65, dy: 0.45)))
        attach(app, name: "MathPlot native canvas pan")
        XCUIDevice.shared.orientation = .landscapeLeft
        waitForOrientation(app, portrait: false)
        XCTAssertTrue(card.waitForExistence(timeout: 5))
        let wideCard = XCTNSPredicateExpectation(predicate: NSPredicate { _, _ in card.frame.width > 500 }, object: card)
        XCTAssertEqual(XCTWaiter.wait(for: [wideCard], timeout: 5), .completed)
        XCTAssertGreaterThan(card.frame.width, 500)
        attach(app, name: "MathPlot wide responsive formula card")
        XCUIDevice.shared.orientation = .portrait
    }

    private func waitForOrientation(_ app: XCUIApplication, portrait: Bool) {
        let settled = XCTNSPredicateExpectation(predicate: NSPredicate { _, _ in
            let frame = app.frame
            return frame.width > 0 && frame.height > 0
                && (portrait ? frame.width < frame.height : frame.width > frame.height)
        }, object: app)
        XCTAssertEqual(XCTWaiter.wait(for: [settled], timeout: 10), .completed,
                       "The rendered app viewport must settle before MathPlot geometry assertions")
    }

    private func attach(_ app: XCUIApplication, name: String) {
        let attachment = XCTAttachment(screenshot: app.screenshot())
        attachment.name = name
        attachment.lifetime = .keepAlways
        add(attachment)
    }
}
