// Synthetic production storage components/controller in the established Debug
// preview host. No account data, billing mutation, provider calls or inference.
import XCTest

@MainActor
final class StorageSettingsPreviewUITests: XCTestCase {
    override func setUpWithError() throws { continueAfterFailure = false }

    // contract-test: supporting surface=gui.apple assertions=storage.surface.semantic-parity,storage.cold.shared-team-authorized,settings-ui.composition.canonical-and-accessible
    func testPersonalAndEachAuthorizedTeamRenderSeparateGiBAllowances() {
        let app = launch("personal")
        let personal = scrollTo("personal-storage-free-tier", app)
        XCTAssertTrue(text(in: personal, app: app).contains("1.0 GiB"))
        XCTAssertTrue(text(in: scrollTo("storage-pricing-policy", app), app: app).contains("separate 1 GiB"))
        screenshot("Personal separate allowance", app)
        app.buttons["storage-fixture-owner"].tap()
        let owner = scrollTo("team-storage-free-tier", app)
        XCTAssertTrue(text(in: owner, app: app).contains("1.0 GiB"))
        XCTAssertEqual(element("storage-fixture-selected-team", app).label, "Owner Team")
        XCTAssertFalse(element("personal-storage-free-tier", app).exists)
        screenshot("Owner Team separate allowance", app)
        app.buttons["storage-fixture-admin"].tap()
        let admin = scrollTo("team-storage-free-tier", app)
        XCTAssertTrue(text(in: admin, app: app).contains("1.0 GiB"))
        XCTAssertEqual(element("storage-fixture-selected-team", app).label, "Admin Team")
        screenshot("Admin Team separate allowance", app)
        app.buttons["storage-fixture-personal"].tap()
        XCTAssertTrue(scrollTo("personal-storage-free-tier", app).isHittable)
        XCTAssertFalse(element("team-storage-summary", app).exists)
    }

    // contract-test: supporting surface=gui.apple assertions=storage.cold.discoverable-bounded,storage.surface.semantic-parity,settings-ui.composition.canonical-and-accessible
    func testUnpaidWarningsDeadlineAndAffectedUnitsRenderAndPageOnClick() {
        let app = launch("unpaid")
        XCTAssertTrue(scrollTo("team-storage-payment-due", app).isHittable)
        let policy = scrollTo("team-storage-active-notice", app)
        XCTAssertTrue(text(in: policy, app: app).contains("28 days")); XCTAssertTrue(text(in: policy, app: app).contains("7 days"))
        XCTAssertTrue(text(in: scrollTo("storage-notice-warning-count", app), app: app).contains("4 / 4"))
        XCTAssertTrue(text(in: scrollTo("storage-notice-deadline", app), app: app).contains("UTC"))
        let firstID = "storage-affected-unit-" + String(repeating: "a", count: 64)
        XCTAssertTrue(text(in: scrollTo(firstID, app), app: app).contains("Older chat archive"))
        screenshot("Unpaid warning with UTC deadline and first affected unit", app)
        let more = scrollTo("team-storage-load-more", app)
        XCTAssertTrue(more.isEnabled); more.tap()
        let secondID = "storage-affected-unit-" + String(repeating: "b", count: 64)
        XCTAssertTrue(text(in: scrollTo(secondID, app), app: app).contains("Artifact history"))
        XCTAssertFalse(element("team-storage-load-more", app).exists)
        screenshot("Affected storage after bounded load more", app)
    }

    // contract-test: supporting surface=gui.apple assertions=storage.surface.semantic-parity,storage.cold.shared-team-authorized,storage.cold.discoverable-bounded
    func testStatusDisclosureAndMemberSelectionDiscardSuspendedOwnerPage() {
        for (variant, identifier) in [("disabled", "team-storage-preview"), ("current", "team-storage-summary"), ("manual-review", "team-storage-manual-review")] {
            let app = launch(variant)
            XCTAssertTrue(scrollTo(identifier, app).isHittable)
            if variant == "disabled" {
                XCTAssertTrue(text(in: element(identifier, app), app: app).contains("price preview"))
                XCTAssertFalse(element("team-storage-active-notice", app).exists)
            } else if variant == "current" {
                XCTAssertFalse(element("team-storage-payment-due", app).exists)
                XCTAssertFalse(element("team-storage-preview", app).exists)
                let empty = app.staticTexts.matching(NSPredicate(format: "label CONTAINS %@", "No active team storage payment notice.")).firstMatch
                for _ in 0..<10 where !empty.isHittable { app.swipeUp() }
                XCTAssertTrue(empty.exists); XCTAssertTrue(empty.isHittable)
            }
            screenshot("Team storage state " + variant, app)
            app.terminate()
        }
        let app = launch("selection-fencing")
        scrollTo("team-storage-load-more", app).tap()
        XCTAssertTrue(element("storage-fixture-pending-page", app).waitForExistence(timeout: 5))
        XCTAssertTrue(app.buttons["storage-fixture-member"].isHittable)
        app.buttons["storage-fixture-member"].tap()
        XCTAssertTrue(element("storage-fixture-restricted", app).waitForExistence(timeout: 5))
        XCTAssertEqual(element("storage-fixture-selected-team", app).label, "Member Team")
        let pendingGone = XCTNSPredicateExpectation(predicate: NSPredicate(format: "exists == false"), object: element("storage-fixture-pending-page", app))
        XCTAssertEqual(XCTWaiter.wait(for: [pendingGone], timeout: 5), .completed)
        XCTAssertFalse(element("team-storage-summary", app).exists)
        XCTAssertFalse(element("team-storage-active-notice", app).exists)
        XCTAssertFalse(element("team-storage-load-more", app).exists)
        XCTAssertFalse(element("storage-affected-unit-" + String(repeating: "b", count: 64), app).exists)
        screenshot("Member selection suppresses late Owner affected page", app)
    }

    private func launch(_ variant: String) -> XCUIApplication {
        let app = XCUIApplication()
        app.launchArguments = ["--dev-preview", "component", "--dev-preview-component", "storage", "--dev-preview-variant", variant,
            "--dev-preview-theme", "light", "-AppleLanguages", "(en)", "-AppleLocale", "en_US"]
        app.launch()
        let root = element("dev-preview-root", app)
        XCTAssertTrue(root.waitForExistence(timeout: 10))
        XCTAssertEqual(root.value as? String, "auth=not-started;store=detached;socket=disconnected")
        XCTAssertFalse(element("dev-preview-error", app).exists)
        XCTAssertTrue(element("dev-component-preview-storage", app).waitForExistence(timeout: 5))
        XCTAssertFalse(app.tables.firstMatch.exists); XCTAssertFalse(app.webViews.firstMatch.exists)
        return app
    }
    private func element(_ id: String, _ app: XCUIApplication) -> XCUIElement { app.descendants(matching: .any)[id].firstMatch }
    private func text(in element: XCUIElement, app: XCUIApplication) -> String {
        // SwiftUI propagates the detail-row identifier to sibling StaticTexts.
        // Info boxes instead expose a containing Other with child StaticTexts.
        // Read the exact identifier's full scope; firstMatch may be only the label.
        let matches = app.descendants(matching: .any)
            .matching(identifier: element.identifier).allElementsBoundByIndex
        return matches.flatMap { match in
            [match.label] + match.descendants(matching: .staticText).allElementsBoundByIndex.map(\.label)
        }.joined(separator: " ")
    }
    @discardableResult private func scrollTo(_ id: String, _ app: XCUIApplication) -> XCUIElement {
        let target = element(id, app)
        for _ in 0..<5 where !target.isHittable { app.swipeDown() }
        for _ in 0..<16 where !target.isHittable { app.swipeUp() }
        XCTAssertTrue(target.exists, id); XCTAssertTrue(target.isHittable, id)
        XCTAssertGreaterThan(target.frame.width, 0); XCTAssertGreaterThan(target.frame.height, 0)
        XCTAssertTrue(app.frame.intersects(target.frame), id)
        return target
    }
    private func screenshot(_ name: String, _ app: XCUIApplication) {
        let attachment = XCTAttachment(screenshot: app.screenshot()); attachment.name = name
        attachment.lifetime = .keepAlways; add(attachment)
    }
}
