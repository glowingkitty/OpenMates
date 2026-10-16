// Rendered group width and footer stability use isolated production components.
import XCTest
import UIKit

@MainActor
final class EmbedResponsiveGeometryUITests: XCTestCase {
    override func setUpWithError() throws { continueAfterFailure = false }

    // contract-test: supporting surface=gui.apple assertions=chats.surface.semantic-parity,chats.layout.responsive-history
    func testResultsMapAndCalendarFillWideMessageContainer() {
        verifyResultsWidth(orientation: .landscapeLeft)
    }

    // contract-test: supporting surface=gui.apple assertions=chats.surface.semantic-parity,chats.layout.responsive-history
    func testResultsMapAndCalendarFitPhoneMessageContainer() {
        verifyResultsWidth(orientation: .portrait)
    }

    // contract-test: supporting surface=gui.apple assertions=chats.surface.semantic-parity,chats.layout.responsive-history
    func testCompactFooterAndCircleStayInsideCardAcrossTallContentAndStatusChanges() throws {
        try verifyFooter(large: false)
    }

    // contract-test: supporting surface=gui.apple assertions=chats.surface.semantic-parity,chats.layout.responsive-history
    func testLargeFooterAndCircleStayInsideAllocatedPreviewAcrossContentChanges() throws {
        try verifyFooter(large: true)
    }

    private func verifyResultsWidth(orientation: UIDeviceOrientation) {
        XCUIDevice.shared.orientation = orientation
        defer { XCUIDevice.shared.orientation = .portrait }
        let app = launch(component: "message", variant: "results-berlin-map")
        let map = element(app, "embeds-results-view-panel-map")
        XCTAssertTrue(map.waitForExistence(timeout: 10))
        // This preview proposes the measured viewport minus32pt gutters on
        // each side. Production receives its own message-container proposal.
        let available = app.windows.firstMatch.frame.width - 64
        XCTAssertEqual(map.frame.width, available, accuracy: 2)
        XCTAssertEqual(element(app, "embeds-map-view-carousel").frame.width, available, accuracy: 2)
        if available > 652 { XCTAssertGreaterThan(map.frame.width, 652) }
        app.buttons["embeds-results-view-tab-calendar"].tap()
        let calendar = element(app, "embeds-results-view-panel-calendar")
        XCTAssertTrue(calendar.waitForExistence(timeout: 5))
        XCTAssertEqual(calendar.frame.width, available, accuracy: 2)
        let scroll = element(app, "embeds-results-view-calendar-scroll")
        XCTAssertEqual(scroll.frame.width, available, accuracy: 2)
        let toolbar = element(app, "embeds-results-view-calendar-toolbar")
        XCTAssertGreaterThanOrEqual(toolbar.frame.minX, calendar.frame.minX)
        XCTAssertLessThanOrEqual(toolbar.frame.maxX, calendar.frame.maxX)
        let week = element(app, "embeds-results-view-calendar-week")
        if available - 28 >= 660 { XCTAssertEqual(week.frame.width, available - 28, accuracy: 2) }
        attach("Results full proposed width \(orientation == .portrait ? "phone" : "wide")")
    }

    private func verifyFooter(large: Bool) throws {
        XCUIDevice.shared.orientation = .portrait
        let app = launch(component: "embed-preview", variant: large ? "footer-large" : "footer-compact")
        let circleProbe = element(app, "responsive-preview-circle-bounds")
        XCTAssertTrue(circleProbe.waitForExistence(timeout: 8))
        let measured = NSPredicate { _, _ in self.parse(circleProbe.label)?.height == 61 }
        XCTAssertEqual(XCTWaiter.wait(for: [XCTNSPredicateExpectation(predicate: measured, object: circleProbe)], timeout: 5), .completed)
        let original = try bounds(app, "footer")
        for state in ["short", "long", "processing", "error", "cancelled", "full-width"] {
            XCTAssertEqual(element(app, "responsive-preview-content-state").label, state)
            let card = try bounds(app, "card")
            let footer = try bounds(app, "footer")
            let circle = try bounds(app, "circle")
            XCTAssertEqual(footer.height, 61, accuracy: 0.1)
            XCTAssertEqual(circle.width, 61, accuracy: 0.1)
            XCTAssertEqual(circle.height, 61, accuracy: 0.1)
            XCTAssertTrue(card.insetBy(dx: -0.5, dy: -0.5).contains(circle), "The complete circular icon must be inside allocated card bounds")
            XCTAssertTrue(footer.insetBy(dx: -0.5, dy: -0.5).contains(circle))
            XCTAssertEqual(footer.maxY, card.maxY - (large ? 15 : 0), accuracy: 0.5)
            XCTAssertEqual(footer.minY, original.minY, accuracy: 0.5, "Footer must not move when details/status change")
            XCTAssertEqual(footer.width, original.width, accuracy: 0.5)
            attach("\(large ? "Large" : "Compact") complete footer \(state)")
            if state != "full-width" {
                app.buttons["responsive-preview-next-content"].tap()
                let next = ["short", "long", "processing", "error", "cancelled", "full-width"]
                let expected = next[next.firstIndex(of: state)! + 1]
                XCTAssertEqual(XCTWaiter.wait(for: [XCTNSPredicateExpectation(
                    predicate: NSPredicate(format: "label == %@", expected),
                    object: element(app, "responsive-preview-content-state"))], timeout: 5), .completed)
            }
        }
    }

    private func parse(_ value: String) -> CGRect? {
        let values = value.split(separator: ",").compactMap { Double($0) }
        guard values.count == 4 else { return nil }
        return CGRect(x: values[0], y: values[1], width: values[2], height: values[3])
    }
    private func bounds(_ app: XCUIApplication, _ name: String) throws -> CGRect {
        try XCTUnwrap(parse(element(app, "responsive-preview-\(name)-bounds").label))
    }
    private func element(_ app: XCUIApplication, _ name: String) -> XCUIElement {
        app.descendants(matching: .any).matching(identifier: name).firstMatch
    }
    private func launch(component: String, variant: String) -> XCUIApplication {
        let app = XCUIApplication()
        app.launchArguments = ["--dev-preview", component, "--dev-preview-variant", variant,
            "--dev-preview-theme", "light", "-AppleLanguages", "(en)", "-AppleLocale", "en_US"]
        app.launch(); return app
    }
    private func attach(_ name: String) {
        let screenshot = XCTAttachment(screenshot: XCUIScreen.main.screenshot())
        screenshot.name = name; screenshot.lifetime = .keepAlways; add(screenshot)
    }
}
