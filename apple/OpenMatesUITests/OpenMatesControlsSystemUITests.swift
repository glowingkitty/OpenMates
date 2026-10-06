// Actual system gallery evidence only. Configured synthetic routing needs an App Group-backed fixture.
// Specification: specifications/features/apple-controls/specification.yml
// Assertions: apple-controls.availability
import XCTest

@MainActor
final class OpenMatesControlsSystemUITests: XCTestCase {
    override func setUpWithError() throws { continueAfterFailure = false }

    // contract-test: supporting surface=gui.apple assertions=apple-controls.availability
    func testSpringBoardGalleryRegistersEightDistinctOpenMatesControls() throws {
        guard #available(iOS 18.0, *) else { throw XCTSkip("Controls require iOS or iPadOS 18 or later") }
        let app = XCUIApplication()
        app.launchArguments = ["--dev-preview", "embed-share", "--dev-workflows-widget-fixture", "--dev-controls-fixture", "--ui-test-disable-auth-cache", "-AppleLanguages", "(en)", "-AppleLocale", "en_US"]
        app.launchEnvironment["DEV_PREVIEW"] = "embed-share"
        app.launch()
        XCTAssertTrue(app.staticTexts["control-fixture-result"].waitForExistence(timeout: 10))
        XCUIDevice.shared.press(.home)
        let springboard = XCUIApplication(bundleIdentifier: "com.apple.springboard")
        XCTAssertTrue(springboard.wait(for: .runningForeground, timeout: 5))
        attachSystemEvidence(springboard, phase: "home-before-control-center")

        // One native XCTest system gesture from SpringBoard, after Home. Do not
        // repeat the two ineffective CUA foreground-app status-bar drags.
        let window = springboard.windows.firstMatch
        guard window.exists, window.frame.width > 0, window.frame.height > 0 else {
            throw XCTSkip("SpringBoard has no accessible full-screen window; inspect home-before-control-center AX evidence")
        }
        let start = window.coordinate(withNormalizedOffset: CGVector(dx: 0.98, dy: 0.01))
        let end = window.coordinate(withNormalizedOffset: CGVector(dx: 0.98, dy: 0.65))
        start.press(forDuration: 0.05, thenDragTo: end, withVelocity: .slow, thenHoldForDuration: 0)
        let edit = springboard.buttons.matching(NSPredicate(format: "label IN %@", ["Add Controls", "Add", "Customize Controls", "Edit Controls"])).firstMatch
        let directAdd = springboard.buttons.matching(NSPredicate(format: "label IN %@", ["Add a Control", "Add Control"])).firstMatch
        let hasEditingEntry = edit.waitForExistence(timeout: 5) || directAdd.exists
        attachSystemEvidence(springboard, phase: "control-center-after-one-native-gesture")
        guard hasEditingEntry else {
            throw XCTSkip("Actual Control Center editing entry is unavailable after one SpringBoard native system gesture; inspect AX/screenshot. No gallery or registration proof obtained")
        }
        if !directAdd.exists {
            guard edit.isHittable else { throw XCTSkip("Control Center editing entry exists but is not hittable; see attached AX") }
            edit.tap()
        }
        guard directAdd.waitForExistence(timeout: 5), directAdd.isHittable else {
            attachSystemEvidence(springboard, phase: "control-center-editing")
            throw XCTSkip("Actual Control Center does not expose Add a Control in its accessibility tree")
        }
        directAdd.tap()
        let search = springboard.searchFields.firstMatch
        guard search.waitForExistence(timeout: 5), search.isHittable else {
            attachSystemEvidence(springboard, phase: "control-gallery-search-unavailable")
            throw XCTSkip("System control gallery has no accessible search field; inspect actual gallery AX")
        }
        search.tap(); search.typeText("OpenMates")
        let expected = ["Ask", "New task", "Ask About Photo", "Record request", "Search", "Incognito Ask", "Workflows", "Projects"]
        var seen = Set<String>()
        // Bounded gallery enumeration; collect only system static labels matching
        // the eight exact English display names, not app-owned fixture buttons.
        for page in 0..<3 {
            for label in expected where springboard.staticTexts[label].firstMatch.exists { seen.insert(label) }
            attachSystemEvidence(springboard, phase: "openmates-control-gallery-page-\(page)")
            if seen.count == expected.count { break }
            let scroll = springboard.scrollViews.firstMatch
            if !scroll.exists { break }
            scroll.swipeUp()
        }
        let summary = XCTAttachment(string: "Actual SpringBoard OpenMates gallery display names: " + seen.sorted().joined(separator: ", "))
        summary.name = "openmates-control-gallery-registered-names"; summary.lifetime = .keepAlways; add(summary)
        XCTAssertEqual(seen, Set(expected), "The actual system gallery must expose all eight distinct OpenMates controls; inspect attached AX for missing names")
    }

    private func attachSystemEvidence(_ springboard: XCUIApplication, phase: String) {
        let screenshot = XCTAttachment(screenshot: XCUIScreen.main.screenshot())
        screenshot.name = phase; screenshot.lifetime = .keepAlways; add(screenshot)
        let tree = XCTAttachment(string: springboard.debugDescription)
        tree.name = phase + "-accessibility"; tree.lifetime = .keepAlways; add(tree)
    }
}
