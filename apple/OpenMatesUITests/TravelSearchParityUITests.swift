// Synthetic persisted Travel search parents with zero providers and no real-account state.
import XCTest

@MainActor
final class TravelSearchParityUITests: XCTestCase {
    override func setUpWithError() throws {
        try super.setUpWithError()
        continueAfterFailure = false
        XCUIDevice.shared.orientation = .portrait
    }

    override func tearDownWithError() throws {
        XCUIDevice.shared.orientation = .portrait
        try super.tearDownWithError()
    }

    // contract-test: supporting surface=gui.apple assertions=chats.surface.semantic-parity,chats.rendering.assistant-document-convergence,chats.layout.responsive-history
    func testZeroProviderPreviewRetainsRouteDateAndZeroCountNarrow() throws {
        try assertEmptyPreviews(wide: false)
    }

    // contract-test: supporting surface=gui.apple assertions=chats.surface.semantic-parity,chats.rendering.assistant-document-convergence,chats.layout.responsive-history
    func testZeroProviderPreviewRetainsRouteDateAndZeroCountWide() throws {
        try assertEmptyPreviews(wide: true)
    }

    // contract-test: supporting surface=gui.apple assertions=chats.surface.semantic-parity,chats.rendering.assistant-document-convergence,chats.layout.responsive-history
    func testZeroProviderFullscreenKeepsTripHeaderAndLocalizedEmptyStateNarrow() throws {
        try assertEmptyFullscreen(wide: false)
    }

    // contract-test: supporting surface=gui.apple assertions=chats.surface.semantic-parity,chats.rendering.assistant-document-convergence,chats.layout.responsive-history
    func testZeroProviderFullscreenKeepsTripHeaderAndLocalizedEmptyStateWide() throws {
        try assertEmptyFullscreen(wide: true)
    }

    private func assertEmptyPreviews(wide: Bool) throws {
        for (variant, route, date) in [
            ("zero-provider-empty", "Berlin → Prague", "Mon, Oct 5"),
            ("zero-provider-grouped", "Oslo → Bergen", "Thu, Oct 8"),
            ("zero-provider-query", "Night train from Berlin to Prague", "")
        ] {
            XCUIDevice.shared.orientation = wide ? .landscapeLeft : .portrait
            defer { XCUIDevice.shared.orientation = .portrait }
            let app = launch(variant: variant, surface: "preview")
            defer { app.terminate() }
            try waitForViewport(app, wide: wide)
            let routeLabel = app.staticTexts["travel-search-route"].firstMatch
            XCTAssertTrue(routeLabel.waitForExistence(timeout: 8))
            XCTAssertEqual(routeLabel.label, route)
            XCTAssertTrue(routeLabel.isHittable)
            let dateLabel = app.staticTexts["travel-search-date"].firstMatch
            if date.isEmpty { XCTAssertFalse(dateLabel.exists) }
            else { XCTAssertTrue(dateLabel.isHittable); XCTAssertEqual(dateLabel.label, date) }
            let count = app.staticTexts["travel-search-count"].firstMatch
            XCTAssertEqual(count.label, "0 connections")
            XCTAssertTrue(count.isHittable)
            XCTAssertFalse(app.descendants(matching: .any)["travel-search-provider"].firstMatch.exists)
            screenshot("Travel empty preview \(variant) \(wide ? "wide" : "narrow")")
        }
    }

    private func assertEmptyFullscreen(wide: Bool) throws {
        XCUIDevice.shared.orientation = wide ? .landscapeLeft : .portrait
        defer { XCUIDevice.shared.orientation = .portrait }
        let app = launch(variant: "zero-provider-empty", surface: "fullscreen")
        defer { app.terminate() }
        try waitForViewport(app, wide: wide)
        let presentation = app.descendants(matching: .any)["embed-presentation-state"].firstMatch
        XCTAssertTrue(presentation.waitForExistence(timeout: 8))
        XCTAssertEqual(XCTWaiter.wait(for: [XCTNSPredicateExpectation(
            predicate: NSPredicate(format: "label == %@", "ready"), object: presentation)], timeout: 8), .completed)
        let title = app.staticTexts["embed-header-title"].firstMatch
        XCTAssertTrue(title.waitForExistence(timeout: 5))
        XCTAssertEqual(title.label, "Berlin → Prague  ·  Mon, October 5, 2026")
        XCTAssertTrue(title.isHittable)
        let subtitle = app.staticTexts["embed-header-subtitle"].firstMatch
        XCTAssertEqual(subtitle.label, "0 connections")
        XCTAssertTrue(subtitle.isHittable)
        let empty = app.staticTexts["search-no-results-message"].firstMatch
        XCTAssertTrue(empty.waitForExistence(timeout: 5))
        XCTAssertEqual(empty.label, "No results found")
        XCTAssertTrue(empty.isHittable)
        XCTAssertFalse(app.staticTexts["embed.no_results"].exists)
        XCTAssertFalse(app.staticTexts["app-skill-use"].exists)
        screenshot("Travel empty fullscreen \(wide ? "wide" : "narrow")")
        let close = app.buttons["embed-minimize"].firstMatch
        XCTAssertTrue(close.isHittable)
        close.tap()
        XCTAssertTrue(title.waitForNonExistence(timeout: 5))
    }

    private func launch(variant: String, surface: String) -> XCUIApplication {
        let app = XCUIApplication()
        app.launchArguments = ["--dev-preview", "embeds", "--dev-preview-app", "travel",
            "--embed-registry-key", "app:travel:search_connections", "--embed-surface", surface,
            "--embed-variant", variant, "--ui-test-embed-presentation",
            "-AppleLanguages", "(en)", "-AppleLocale", "en_US"]
        app.launch()
        return app
    }

    private func waitForViewport(_ app: XCUIApplication, wide: Bool) throws {
        let window = app.windows.firstMatch
        XCTAssertTrue(window.waitForExistence(timeout: 8))
        let viewportMatches = NSPredicate { _, _ in
            let frame = window.frame
            guard window.exists, frame.width > 0, frame.height > 0 else { return false }
            return wide ? frame.width > frame.height : frame.width < frame.height
        }
        XCTAssertEqual(XCTWaiter.wait(for: [XCTNSPredicateExpectation(predicate: viewportMatches,
                                                                    object: window)], timeout: 8), .completed)
    }

    private func screenshot(_ name: String) {
        let attachment = XCTAttachment(screenshot: XCUIScreen.main.screenshot())
        attachment.name = name
        attachment.lifetime = .keepAlways
        add(attachment)
    }
}
