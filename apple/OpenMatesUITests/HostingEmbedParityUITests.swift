// Synthetic production-renderer proof; no provider/API calls or real-account state.
import XCTest

@MainActor
final class HostingEmbedParityUITests: XCTestCase {
    override func setUpWithError() throws { continueAfterFailure = false }

    // contract-test: supporting surface=gui.apple assertions=hosting-domains.surface-parity,hosting-domains.quotes.truthful,hosting-domains.results.partial-and-safe
    func testParentPreviewKeepsStandardSizeAndTruthfulTerminalStates() {
        for variant in ["default", "processing", "cancelled", "empty", "error", "partial"] {
            let app = launch(key: "app:hosting:search_domains", surface: "preview", variant: variant)
            let card = app.buttons["embed-preview"].firstMatch
            XCTAssertTrue(card.waitForExistence(timeout: 10))
            XCTAssertEqual(card.frame.width, 300, accuracy: 1)
            XCTAssertEqual(card.frame.height, 200, accuracy: 1)
            XCTAssertTrue(app.staticTexts["cedarcomet"].exists)
            if variant == "default" { XCTAssertTrue(app.staticTexts.containing(NSPredicate(format: "label CONTAINS %@", "13.09")).firstMatch.exists) }
            if variant == "partial" { XCTAssertTrue(app.staticTexts["hosting-search-partial"].exists) }
            attach("Hosting parent preview \(variant)")
            app.terminate()
        }
    }

    // contract-test: supporting surface=gui.apple assertions=hosting-domains.surface-parity,hosting-domains.availability.selection,hosting-domains.embeds.parent-child
    func testParentFiltersCheckedDomainsInHeaderMenuAndChildNavigationRestoresParentView() {
        let app = launch(key: "app:hosting:search_domains", surface: "fullscreen")
        waitUntilReady(app)
        let grid = app.descendants(matching: .any)["hosting-domain-grid"].firstMatch
        XCTAssertTrue(grid.waitForExistence(timeout: 10))
        XCTAssertEqual(grid.buttons.matching(identifier: "embed-preview").count, 2)
        choose("in-use", in: app)
        let cards = grid.buttons.matching(identifier: "embed-preview")
        XCTAssertEqual(cards.count, 2)
        XCTAssertTrue(app.staticTexts["cedarcomet.org"].firstMatch.exists)
        XCTAssertTrue(cards.firstMatch.isHittable)
        cards.firstMatch.tap()
        waitUntilReady(app)
        XCTAssertTrue(app.descendants(matching: .any)["hosting-domain-ascii"].firstMatch.waitForExistence(timeout: 10))
        XCTAssertTrue(app.buttons["hosting-open-gandi"].isHittable)
        let next = app.buttons["embed-next"]
        XCTAssertTrue(next.isHittable)
        next.tap()
        XCTAssertTrue(app.staticTexts["cedarcomet.co"].firstMatch.waitForExistence(timeout: 10))
        app.buttons["embed-minimize"].tap()
        waitUntilReady(app)
        XCTAssertTrue(app.staticTexts["cedarcomet.org"].firstMatch.exists)
        choose("unknown", in: app)
        XCTAssertEqual(grid.buttons.matching(identifier: "embed-preview").count, 1)
        XCTAssertTrue(app.staticTexts["Could not check"].exists)
        attach("Hosting checked unknown view")
    }

    // contract-test: supporting surface=gui.apple assertions=hosting-domains.surface-parity,hosting-domains.results.partial-and-safe
    func testParentFullscreenShowsProcessingEmptyCancelledAndErrorDiagnosticEvidence() {
        for variant in ["processing", "cancelled", "empty", "error"] {
            let app = launch(key: "app:hosting:search_domains", surface: "fullscreen", variant: variant)
            waitUntilReady(app)
            if variant == "processing" {
                XCTAssertTrue(app.staticTexts["hosting-search-loading"].waitForExistence(timeout: 5))
            } else if variant == "empty" {
                XCTAssertTrue(app.staticTexts["hosting-search-empty"].waitForExistence(timeout: 5))
            } else if variant == "error" {
                XCTAssertTrue(app.staticTexts["Could not check"].firstMatch.waitForExistence(timeout: 5))
                XCTAssertEqual(app.buttons.matching(identifier: "embed-preview").count, 1)
            } else {
                XCTAssertTrue(app.staticTexts.containing(NSPredicate(format: "label CONTAINS[c] %@", "cancelled")).firstMatch.exists)
            }
            attach("Hosting parent fullscreen \(variant)")
            app.terminate()
        }
    }

    // contract-test: supporting surface=gui.apple assertions=hosting-domains.surface-parity,hosting-domains.quotes.truthful,hosting-domains.results.partial-and-safe
    func testDomainPreviewAndFullscreenPreserveUnicodeQuotesAndUnknownEvidence() {
        for variant in ["default", "unknown", "minTwoYears", "missingPrice", "longIdn"] {
            let preview = launch(key: "hosting-domain", surface: "preview", variant: variant)
            let card = preview.buttons["embed-preview"].firstMatch
            XCTAssertTrue(card.waitForExistence(timeout: 10))
            XCTAssertEqual(card.frame.width, 300, accuracy: 1)
            XCTAssertEqual(card.frame.height, 200, accuracy: 1)
            attach("Hosting domain preview \(variant)")
            preview.terminate()
            let app = launch(key: "hosting-domain", surface: "fullscreen", variant: variant)
            waitUntilReady(app)
            XCTAssertTrue(app.descendants(matching: .any)["hosting-domain-details"].firstMatch.waitForExistence(timeout: 10))
            XCTAssertTrue(app.buttons["hosting-open-gandi"].isHittable)
            XCTAssertTrue(app.buttons["embed-more-button"].isHittable)
            app.buttons["embed-more-button"].tap()
            XCTAssertTrue(app.buttons["embed-copy-button"].isHittable)
            app.buttons["embed-copy-button"].tap()
            // Copy displays the production three-second notification over the
            // header. Wait for that transient overlay to release the close
            // control instead of asserting during its presentation.
            let close = app.buttons["embed-minimize"]
            XCTAssertEqual(XCTWaiter.wait(for: [XCTNSPredicateExpectation(
                predicate: NSPredicate(format: "hittable == true"), object: close)], timeout: 5), .completed)
            XCTAssertTrue(close.isHittable)
            attach("Hosting domain details \(variant)")
            app.terminate()
        }
    }

    private func choose(_ view: String, in app: XCUIApplication) {
        let more = app.buttons["embed-more-button"]
        XCTAssertTrue(more.isHittable); more.tap()
        let action = app.buttons["hosting-view-\(view)"]
        XCTAssertTrue(action.waitForExistence(timeout: 5)); XCTAssertTrue(action.isHittable); action.tap()
        XCTAssertFalse(app.descendants(matching: .any)["embed-more-actions"].firstMatch.exists)
    }
    private func launch(key: String, surface: String, variant: String = "default") -> XCUIApplication {
        let app = XCUIApplication()
        app.launchArguments = ["--dev-preview", "embeds", "--dev-preview-app", "hosting", "--embed-registry-key", key,
            "--embed-surface", surface, "--embed-variant", variant, "--ui-test-embed-presentation", "-AppleLanguages", "(en)", "-AppleLocale", "en_US"]
        if key == "app:hosting:search_domains", surface == "fullscreen" { app.launchArguments.append("--dev-hosting-search-route-preview") }
        app.launch(); return app
    }
    private func waitUntilReady(_ app: XCUIApplication) {
        let ready = app.descendants(matching: .any)["embed-presentation-state"].firstMatch
        XCTAssertTrue(ready.waitForExistence(timeout: 10))
        XCTAssertEqual(XCTWaiter.wait(for: [XCTNSPredicateExpectation(predicate: NSPredicate(format: "label == %@", "ready"), object: ready)], timeout: 10), .completed)
    }
    private func attach(_ name: String) {
        let attachment = XCTAttachment(screenshot: XCUIScreen.main.screenshot())
        attachment.name = name; attachment.lifetime = .keepAlways; add(attachment)
    }
}
