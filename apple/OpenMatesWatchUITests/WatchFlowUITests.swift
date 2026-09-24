// Network-free simulator coverage for the Watch's iPhone-first pairing and
// read-only Tasks/Workflows concept. Uses production views with seeded data.

import XCTest
import CoreGraphics

final class WatchFlowUITests: XCTestCase {
    override func setUpWithError() throws {
        continueAfterFailure = false
    }

    @MainActor
    // contract-test: direct surface=gui.apple assertions=apple-watch.pairing.iphone-first-fallback
    func testPairingStartsWithIPhoneApprovalAndRevealsShortURL() {
        let app = XCUIApplication()
        app.launchArguments = ["--ui-test-watch-pair-waiting"]
        app.launch()

        XCTAssertTrue(app.staticTexts["watch-pair-confirm-iphone-title"].waitForExistence(timeout: 12))
        XCTAssertTrue(app.buttons["watch-pair-login-without-iphone-button"].exists)
        XCTAssertFalse(app.staticTexts["watch-pair-url"].exists)
        keepScreenshot("Watch iPhone-first pairing")

        app.buttons["watch-pair-login-without-iphone-button"].tap()
        let shortURL = app.staticTexts["watch-pair-url"]
        XCTAssertTrue(shortURL.waitForExistence(timeout: 5))
        XCTAssertEqual(shortURL.label.replacingOccurrences(of: "\n", with: ""), "openmates.org/#pair=WATCH42")
        XCTAssertFalse(app.buttons["watch-pair-show-qr-button"].exists)
        keepScreenshot("Watch Cloud short URL pairing")

        app.buttons["watch-pair-self-host-button"].tap()
        XCTAssertTrue(app.staticTexts["watch-pair-self-host-prompt"].waitForExistence(timeout: 5))
        assertBottomKeyboardTray(app.buttons["watch-pair-self-host-keyboard"], in: app)
        keepScreenshot("Watch self-host domain entry")
    }

    @MainActor
    // contract-test: direct surface=gui.apple assertions=apple-watch.pairing.iphone-first-fallback
    func testSelfHostedShortURLUsesItsDomainAndOffersCloud() {
        let app = XCUIApplication()
        app.launchArguments = ["--ui-test-watch-pair-selfhost-short-url"]
        app.launch()

        let shortURL = app.staticTexts["watch-pair-url"]
        XCTAssertTrue(shortURL.waitForExistence(timeout: 12))
        XCTAssertEqual(shortURL.label.replacingOccurrences(of: "\n", with: ""), "mydomain.org/#pair=WATCH42")
        XCTAssertTrue(app.buttons["watch-pair-use-production-button"].exists)
        XCTAssertFalse(app.buttons["watch-pair-show-qr-button"].exists)
        keepScreenshot("Watch self-host short URL pairing")
    }

    @MainActor
    // contract-test: direct surface=gui.apple assertions=apple-watch.pairing.iphone-first-fallback
    func testApprovedPairingShowsCodeEntry() {
        let app = XCUIApplication()
        app.launchArguments = ["--ui-test-watch-pair-code-entry"]
        app.launch()

        XCTAssertTrue(app.staticTexts["watch-pair-code-prompt"].waitForExistence(timeout: 12))
        assertBottomKeyboardTray(app.buttons["watch-pair-pin-keyboard"], in: app)
        XCTAssertFalse(app.buttons["watch-pair-show-qr-button"].exists)
        keepScreenshot("Watch pair code entry")
    }

    @MainActor
    // contract-test: direct surface=gui.apple assertions=apple-watch.hub.compact-navigation,apple-watch.lists.read-only-private,apple-watch.handoff.exact-private
    func testHubShowsTaskAndWorkflowRowsAndRequestsExactItem() {
        let app = XCUIApplication()
        app.launchArguments = ["--ui-test-watch-hub-lists"]
        app.launch()

        XCTAssertTrue(app.buttons["watch-hub-select-chat"].waitForExistence(timeout: 12))
        XCTAssertTrue(app.buttons["watch-hub-select-tasks"].exists)
        XCTAssertTrue(app.buttons["watch-hub-select-workflows"].exists)
        keepScreenshot("Watch Chat Tasks Workflows selector")

        app.buttons["watch-hub-select-tasks"].tap()
        XCTAssertTrue(app.buttons["watch-task-row-task-one"].waitForExistence(timeout: 5))
        XCTAssertTrue(app.buttons["watch-task-row-task-two"].exists)
        XCTAssertTrue(app.buttons["watch-hub-search"].exists)
        XCTAssertTrue(app.buttons["watch-hub-new"].exists)
        keepScreenshot("Watch read-only Tasks list")

        app.buttons["watch-task-row-task-one"].tap()
        let openedItem = app.staticTexts["watch-ui-test-open-request"]
        XCTAssertTrue(openedItem.waitForExistence(timeout: 3))
        XCTAssertEqual(openedItem.label, "task:task-one")

        app.buttons["watch-hub-section-selector"].tap()
        app.buttons["watch-hub-select-workflows"].tap()
        let workflow = app.buttons["watch-workflow-row-workflow-one"]
        XCTAssertTrue(workflow.waitForExistence(timeout: 5))
        keepScreenshot("Watch read-only Workflows list")
        workflow.tap()
        XCTAssertEqual(openedItem.label, "workflow:workflow-one")
    }

    @MainActor
    private func keepScreenshot(_ name: String) {
        let attachment = XCTAttachment(screenshot: XCUIScreen.main.screenshot())
        attachment.name = name
        attachment.lifetime = .keepAlways
        add(attachment)
    }

    @MainActor
    private func assertBottomKeyboardTray(_ tray: XCUIElement, in app: XCUIApplication) {
        XCTAssertTrue(tray.waitForExistence(timeout: 5))
        XCTAssertTrue(tray.isHittable)
        XCTAssertGreaterThan(tray.frame.maxY, app.frame.maxY - 16)
        XCTAssertGreaterThan(tray.frame.width, app.frame.width * 0.85)

        // XCUI can report a hittable frame even when SwiftUI paints the tray
        // below the visible Watch viewport. Sample a quiet part of its grey
        // background near the physical bottom of the screenshot.
        guard let screenshot = XCUIScreen.main.screenshot().image.cgImage else {
            XCTFail("Could not decode Watch screenshot")
            return
        }
        let width = screenshot.width
        let height = screenshot.height
        var rgba = [UInt8](repeating: 0, count: width * height * 4)
        let rendered = rgba.withUnsafeMutableBytes { buffer -> Bool in
            guard let context = CGContext(
                data: buffer.baseAddress,
                width: width,
                height: height,
                bitsPerComponent: 8,
                bytesPerRow: width * 4,
                space: CGColorSpaceCreateDeviceRGB(),
                bitmapInfo: CGImageAlphaInfo.premultipliedLast.rawValue
            ) else { return false }
            context.draw(screenshot, in: CGRect(x: 0, y: 0, width: width, height: height))
            return true
        }
        XCTAssertTrue(rendered)
        guard rendered else { return }
        let x = width * 7 / 10
        let bottomInset = min(40, height / 8)
        let nearBottom = (height - bottomInset) * width * 4 + x * 4
        let nearTop = bottomInset * width * 4 + x * 4
        let trayBrightness = max(rgba[nearBottom], rgba[nearTop])
        XCTAssertGreaterThan(trayBrightness, 35, "Keyboard tray has no visible grey pixels at the Watch bottom")
    }
}
