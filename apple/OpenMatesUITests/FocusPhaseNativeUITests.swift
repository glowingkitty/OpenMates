// Synthetic rendering/routing coverage; no inference and no external fixture data.
import XCTest

@MainActor
final class FocusPhaseNativeUITests: XCTestCase {
    override func setUpWithError() throws {
        continueAfterFailure = false
        #if os(iOS)
        XCUIDevice.shared.orientation = .portrait
        #endif
    }

    // contract-test: supporting surface=gui.apple assertions=focus-modes.phases,focus-modes.history-events,focus-modes.history-side-effects,chats.surface.semantic-parity
    func testCatalogHistoryLinkOpensNativePhasesAndRequirements() {
        let app = launch()
        let history = app.scrollViews["chat-history-container"]
        let links = history.buttons.matching(identifier: "focus-phase-details-link")
        XCTAssertTrue(links.firstMatch.waitForExistence(timeout: 15))
        XCTAssertEqual(links.count, 2)
        let unavailable = app.staticTexts.matching(NSPredicate(
            format: "identifier == %@ AND label == %@", "chat-history-system-message", "Phases could not be loaded.")).firstMatch
        XCTAssertTrue(unavailable.waitForExistence(timeout: 10))
        revealHistoryTarget(unavailable, in: history, app: app, requiresHitTesting: false)
        XCTAssertTrue(history.frame.intersection(app.windows.firstMatch.frame).contains(unavailable.frame),
                      "The malformed phase history must display its friendly notice inside the visible transcript")
        XCTAssertFalse(app.descendants(matching: .any).matching(NSPredicate(format: "label CONTAINS %@", "focus_phase_changed")).firstMatch.exists,
                       "Malformed typed history must render a friendly notice, never protocol JSON")
        XCTAssertEqual(links.element(boundBy: 0).label, "Confirm your career profile")
        XCTAssertFalse(app.buttons["focus-pill-body"].exists)
        revealHistoryTarget(links.element(boundBy: 0), in: history, app: app)
        assertHeaderDoesNotCoverHistory(app, target: links.element(boundBy: 0))
        attachHierarchy(app, "Catalog phase history before tap")
        links.element(boundBy: 0).tap()
        let detailOpened = app.descendants(matching: .any)["settings-focus-detail-page"].waitForExistence(timeout: 10)
        if !detailOpened {
            let receipt = XCTAttachment(string: "actual-link-callback=\(links.element(boundBy: 0).value ?? "unavailable");link-bounds=\(links.element(boundBy: 0).frame)")
            receipt.name = "Catalog phase actual callback receipt"
            receipt.lifetime = .keepAlways
            add(receipt)
            attachHierarchy(app, "Catalog phase history after failed detail opening")
        }
        XCTAssertTrue(detailOpened)
        assertPhases(app)
        XCTAssertFalse(app.webViews.firstMatch.exists)
        XCTAssertFalse(app.buttons["focus-pill-body"].exists, "Historical display must not activate focus")
        let focusScroll = app.scrollViews["settings-focus-detail-scroll"]
        XCTAssertTrue(focusScroll.waitForExistence(timeout: 5))
        let back = app.buttons["settings-focus-detail-back"]
        for _ in 0..<6 {
            if back.exists && back.isHittable
                && focusScroll.frame.intersection(app.windows.firstMatch.frame).contains(back.frame) { break }
            // Requirements are lower in the real lazy settings page. Return
            // to its top to realize the actual Back control before tapping it.
            focusScroll.swipeDown()
        }
        XCTAssertTrue(back.exists, "The native Focus detail must retain its real Back action")
        XCTAssertTrue(back.isHittable)
        XCTAssertTrue(focusScroll.frame.intersection(app.windows.firstMatch.frame).contains(back.frame))
        back.tap()
        XCTAssertTrue(app.descendants(matching: .any)["settings-app-detail-page"].waitForExistence(timeout: 5))
        attach(app, "Catalog phase detail through historical notice")
    }

    // contract-test: supporting surface=gui.apple assertions=focus-modes.phases,focus-modes.history-events,focus-modes.history-side-effects,chats.surface.semantic-parity
    func testProjectHistoryLinkDecryptsAndRendersProjectPhaseRequirements() {
        let app = launch()
        let history = app.scrollViews["chat-history-container"]
        let links = history.buttons.matching(identifier: "focus-phase-details-link")
        XCTAssertTrue(links.element(boundBy: 1).waitForExistence(timeout: 15))
        XCTAssertFalse(app.buttons["focus-pill-body"].exists)
        revealHistoryTarget(links.element(boundBy: 1), in: history, app: app)
        assertHeaderDoesNotCoverHistory(app, target: links.element(boundBy: 1))
        links.element(boundBy: 1).tap()
        XCTAssertTrue(app.descendants(matching: .any)["project-settings-back"].waitForExistence(timeout: 10))
        assertPhases(app)
        XCTAssertFalse(app.webViews.firstMatch.exists)
        XCTAssertFalse(app.buttons["focus-pill-body"].exists, "Project history display must not activate focus")
        attach(app, "Project phase detail through backward historical notice")
    }

    private func launch() -> XCUIApplication {
        let app = XCUIApplication()
        app.launchArguments = ["--ui-test-disable-auth-cache", "--ui-test-authenticated-chat-navigation",
            "--ui-test-account-settings-fixture", "--ui-test-app-store-fixture", "--ui-test-focus-phase-fixture",
            "-AppleLanguages", "(en)", "-AppleLocale", "en_US"]
        app.launch()
        #if os(iOS)
        XCUIDevice.shared.orientation = .portrait
        #endif
        // SwiftUI places this ID on an enclosing Other element. The actual
        // static text exposes the metric label, as in ChatNavigationParityUITests.
        let metrics = app.staticTexts
            .containing(NSPredicate(format: "label CONTAINS %@", "chat-navigation-order="))
            .firstMatch
        XCTAssertEqual(XCTWaiter.wait(for: [XCTNSPredicateExpectation(predicate: NSPredicate { _, _ in
            metrics.exists && metrics.label.contains("selected-chat-id=ui-test-current-chat;")
        }, object: nil)], timeout: 15), .completed, "Synthetic account/cache setup must finish before routing")
        return app
    }

    private func revealHistoryTarget(_ target: XCUIElement, in history: XCUIElement,
                                     app: XCUIApplication, requiresHitTesting: Bool = true) {
        func visibleViewport() -> CGRect {
            history.frame.intersection(app.windows.firstMatch.frame).insetBy(dx: 0, dy: 16)
        }
        func targetIsInTranscript() -> Bool {
            target.exists && !target.frame.isEmpty && visibleViewport().contains(target.frame)
        }
        for _ in 0..<6 {
            // Noninteractive StaticText has no activation point. Never swipe
            // an already visible target merely because AX calls it unhittable.
            if targetIsInTranscript() { break }
            guard target.exists, !target.frame.isEmpty else { break }
            let viewport = visibleViewport(), bounds = target.frame
            guard !viewport.isEmpty else { break }
            if bounds.minY < viewport.minY {
                history.swipeDown()
            } else if bounds.maxY > viewport.maxY {
                history.swipeUp()
            } else {
                break
            }
        }
        if !targetIsInTranscript() || (requiresHitTesting && !target.isHittable) {
            let receipt = XCTAttachment(string: "target=\(target.identifier);bounds=\(target.frame);viewport=\(visibleViewport());hittable=\(target.isHittable)")
            receipt.name = "Focus history target visibility bounds"
            receipt.lifetime = .keepAlways
            add(receipt)
            attachHierarchy(app, "Focus history target visibility failure")
            attach(app, "Focus history target viewport")
        }
        XCTAssertTrue(targetIsInTranscript(), "The historical target must fit inside the actual transcript viewport")
        if requiresHitTesting {
            XCTAssertTrue(target.isHittable, "Tap the actual visible historical phase link")
        }
    }

    private func attachHierarchy(_ app: XCUIApplication, _ name: String) {
        let attachment = XCTAttachment(string: app.debugDescription)
        attachment.name = name; attachment.lifetime = .keepAlways
        add(attachment)
    }

    private func assertHeaderDoesNotCoverHistory(_ app: XCUIApplication, target: XCUIElement) {
        let banner = app.descendants(matching: .any).matching(identifier: "chat-header-banner").firstMatch
        XCTAssertTrue(banner.exists)
        XCTAssertLessThanOrEqual(banner.frame.maxY, target.frame.minY,
                                 "Decorative header bounds must not overlap the actual history link")
    }

    private func assertPhases(_ app: XCUIApplication) {
        let phases = app.descendants(matching: .any).matching(identifier: "focus-mode-phases").firstMatch
        XCTAssertTrue(phases.waitForExistence(timeout: 10))
        let requirements = app.descendants(matching: .any).matching(identifier: "focus-phase-requirement")
        XCTAssertGreaterThan(requirements.count, 0)
        XCTAssertTrue(app.staticTexts["1. Understand your situation"].exists)
        // Scroll the actual settings content to the confirmation requirement;
        // the notice overlay must not replace the destination's content.
        for _ in 0..<6 {
            if app.staticTexts["• The user confirms the career profile."].isHittable { break }
            app.swipeUp()
        }
        XCTAssertTrue(app.staticTexts["• The user confirms the career profile."].exists)
        XCTAssertTrue(app.staticTexts["Your confirmation is required"].exists)
        XCTAssertTrue(app.descendants(matching: .any).matching(identifier: "focus-phase-instructions").firstMatch.exists)
    }

    private func attach(_ app: XCUIApplication, _ name: String) {
        let attachment = XCTAttachment(screenshot: app.screenshot())
        attachment.name = name; attachment.lifetime = .keepAlways
        add(attachment)
    }
}
