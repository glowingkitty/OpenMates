// Synthetic transport, production fullscreen header, image and Wiki renderer.
import XCTest
import UIKit

@MainActor
final class WikiFullscreenParityUITests: XCTestCase {
    override func setUpWithError() throws { continueAfterFailure = false }

    // contract-test: supporting surface=gui.apple assertions=chats.surface.semantic-parity,chats.layout.responsive-history
    func testWikiActionOverlapsBannerAndBothHalvesRemainClickableNarrow() {
        verifyHeader(orientation: .portrait)
    }

    // contract-test: supporting surface=gui.apple assertions=chats.surface.semantic-parity,chats.layout.responsive-history
    func testWikiActionAndHeroFitWideViewport() {
        verifyHeader(orientation: .landscapeLeft)
    }

    // contract-test: supporting surface=gui.apple assertions=chats.surface.semantic-parity,chats.rendering.inline-entity-interaction
    func testSwitchingArticleReplacesHeadingDescriptionExtractImageAndDestination() {
        XCUIDevice.shared.orientation = .portrait
        let app = launch()
        XCTAssertTrue(app.staticTexts["wiki-fullscreen-title"].waitForExistence(timeout: 8))
        XCTAssertTrue(waitLabel(app.staticTexts["wiki-fullscreen-title"], "YouTube Shorts"))
        app.buttons["embed-next"].tap()
        XCTAssertTrue(waitLabel(app.staticTexts["wiki-fullscreen-title"], "OpenAI"))
        let description = app.descendants(matching: .any)["wiki-fullscreen-description"].firstMatch
        XCTAssertTrue(waitLabel(description, "Artificial intelligence research organization"))
        XCTAssertFalse(app.staticTexts.containing(NSPredicate(format: "label CONTAINS %@", "Short-form video platform")).firstMatch.exists)
        XCTAssertFalse(app.staticTexts.containing(NSPredicate(format: "label CONTAINS %@", "YouTube Shorts is a short-form")).firstMatch.exists)
        let extract = app.descendants(matching: .any)["wiki-fullscreen-extract"].firstMatch
        if !extract.isHittable { app.scrollViews["embed-fullscreen-scroll"].swipeUp() }
        XCTAssertTrue(extract.waitForExistence(timeout: 5))
        XCTAssertTrue(extract.label.contains("OpenAI researches and develops artificial intelligence."))
        app.scrollViews["embed-fullscreen-scroll"].swipeDown()
        let image = app.descendants(matching: .any)["wiki-hero-image"].firstMatch
        XCTAssertEqual(image.label, "OpenAI")
        XCTAssertTrue(waitValue(image, "loaded"))
        let cta = app.buttons["wiki-open-wikipedia"]
        XCTAssertTrue(cta.isHittable); cta.tap()
        XCTAssertTrue(waitLabel(app.staticTexts["wiki-fixture-opened-url"], "1|https://en.wikipedia.org/wiki/OpenAI"))
        attach("Wiki article replacement")
    }

    private func verifyHeader(orientation: UIDeviceOrientation) {
        XCUIDevice.shared.orientation = orientation
        defer { XCUIDevice.shared.orientation = .portrait }
        let app = launch()
        XCTAssertTrue(waitLabel(app.staticTexts["embed-presentation-state"], "ready"))
        let header = app.descendants(matching: .any)["embed-fullscreen-header"].firstMatch
        let cta = app.buttons["wiki-open-wikipedia"]
        XCTAssertTrue(cta.waitForExistence(timeout: 8)); XCTAssertTrue(cta.isHittable)
        XCTAssertEqual(cta.label, "Open on Wikipedia")
        // The header includes the CTA's lower 22 points in its hit-test bounds;
        // the gradient edge crosses the button center.
        XCTAssertEqual(cta.frame.maxY, header.frame.maxY, accuracy: 3)
        XCTAssertEqual(cta.frame.midY, header.frame.maxY - 22, accuracy: 3)
        for (index, fraction) in [0.25, 0.75].enumerated() {
            cta.coordinate(withNormalizedOffset: CGVector(dx: 0.5, dy: fraction)).tap()
            XCTAssertTrue(waitLabel(app.staticTexts["wiki-fixture-opened-url"], "\(index + 1)|https://en.wikipedia.org/wiki/YouTube_Shorts"))
        }
        let image = app.descendants(matching: .any)["wiki-hero-image"].firstMatch
        XCTAssertTrue(image.waitForExistence(timeout: 8)); XCTAssertTrue(waitValue(image, "loaded"))
        XCTAssertGreaterThan(image.frame.height, 0)
        XCTAssertLessThanOrEqual(image.frame.width, 511 + 1)
        XCTAssertLessThanOrEqual(image.frame.height, 340 + 1)
        XCTAssertGreaterThanOrEqual(image.frame.minY, cta.frame.maxY + 15)
        XCTAssertGreaterThanOrEqual(image.frame.minX, 0)
        XCTAssertLessThanOrEqual(image.frame.maxX, app.frame.maxX)
        attach("Wiki fullscreen \(orientation == .portrait ? "narrow" : "wide")")
    }

    private func launch() -> XCUIApplication {
        let app = XCUIApplication()
        app.launchArguments = ["--dev-preview", "embed-fullscreen", "--dev-preview-variant", "wiki"]
        app.launch(); return app
    }
    private func waitLabel(_ element: XCUIElement, _ value: String) -> Bool {
        XCTWaiter.wait(for: [XCTNSPredicateExpectation(predicate: NSPredicate(format: "label == %@", value), object: element)], timeout: 8) == .completed
    }
    private func waitValue(_ element: XCUIElement, _ value: String) -> Bool {
        XCTWaiter.wait(for: [XCTNSPredicateExpectation(predicate: NSPredicate(format: "value == %@", value), object: element)], timeout: 8) == .completed
    }
    private func attach(_ name: String) {
        let attachment = XCTAttachment(screenshot: XCUIScreen.main.screenshot())
        attachment.name = name; attachment.lifetime = .keepAlways; add(attachment)
    }
}
