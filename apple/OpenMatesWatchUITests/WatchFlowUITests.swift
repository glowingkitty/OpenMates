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
    func testPairInitiationFailureOffersSelfHostedServerBeforeAnyTokenExists() {
        let app = XCUIApplication()
        app.launchArguments = ["--ui-test-watch-pair-initiation-failed"]
        app.launch()
        let selfHost = app.buttons["watch-pair-self-host-button"]
        XCTAssertTrue(selfHost.waitForExistence(timeout: 12))
        XCTAssertTrue(selfHost.isHittable)
        XCTAssertTrue(app.buttons["watch-pair-refresh-button"].isHittable)
        XCTAssertFalse(app.staticTexts["watch-pair-url"].exists)
        XCTAssertFalse(app.textFields["watch-pair-pin-input"].exists)
        selfHost.tap()
        XCTAssertTrue(app.staticTexts["watch-pair-self-host-prompt"].waitForExistence(timeout: 5))
        assertBottomKeyboardTray(app.buttons["watch-pair-self-host-keyboard"], in: app)
        XCTAssertFalse(app.buttons["watch-pair-refresh-button"].exists)
        keepScreenshot("Watch server recovery before pair initiation")
        app.buttons["watch-pair-back-button"].tap()
        XCTAssertTrue(selfHost.waitForExistence(timeout: 5))
        XCTAssertTrue(selfHost.isHittable)
        XCTAssertFalse(app.staticTexts["watch-pair-url"].exists)
    }

    @MainActor
    // contract-test: direct surface=gui.apple assertions=apple-watch.pairing.iphone-first-fallback
    func testSelfHostedInitiationFailureOffersCloudRecoveryWithoutPairURL() {
        let app = XCUIApplication()
        app.launchArguments = ["--ui-test-watch-pair-selfhost-initiation-failed"]
        app.launch()
        let cloud = app.buttons["watch-pair-use-production-button"]
        XCTAssertTrue(cloud.waitForExistence(timeout: 12))
        XCTAssertTrue(cloud.isHittable)
        XCTAssertFalse(app.staticTexts["watch-pair-url"].exists)
        cloud.tap()
        let selfHost = app.buttons["watch-pair-self-host-button"]
        XCTAssertTrue(selfHost.waitForExistence(timeout: 5))
        XCTAssertTrue(selfHost.isHittable)
        XCTAssertTrue(app.buttons["watch-pair-refresh-button"].exists)
        XCTAssertFalse(app.staticTexts["watch-pair-url"].exists)
        keepScreenshot("Watch custom server failure offers Cloud recovery")
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
        let board = app.otherElements["watch-task-board"]
        XCTAssertTrue(app.buttons["watch-task-row-backlog-0"].waitForExistence(timeout: 5))
        let sectionSelector = app.buttons["watch-hub-section-selector"]
        // Swipe through the same five status pages as iPhone. Vertical scroll
        // must leave the active page intact and keep the section header fixed.
        let backlog = app.scrollViews["watch-task-column-backlog"]
        let lastBacklogTask = app.buttons["watch-task-row-backlog-11"]
        for _ in 0..<8 where !lastBacklogTask.isHittable { backlog.swipeUp() }
        XCTAssertTrue(lastBacklogTask.isHittable)
        XCTAssertTrue(backlog.exists)
        XCTAssertTrue(sectionSelector.isHittable)
        board.swipeLeft()
        XCTAssertTrue(app.buttons["watch-task-row-task-two"].waitForExistence(timeout: 5))
        board.swipeLeft()
        let task = app.buttons["watch-task-row-task-one"]
        XCTAssertTrue(task.waitForExistence(timeout: 5))
        task.tap()
        XCTAssertTrue(app.staticTexts["watch-task-detail-title"].waitForExistence(timeout: 5))
        XCTAssertEqual(app.staticTexts["watch-task-detail-description"].label,
                       "Compare motors that safely carry two people.")
        let detail = app.scrollViews["watch-task-detail-scroll"]
        detail.swipeUp()
        XCTAssertTrue(app.staticTexts["watch-task-detail-context"].exists)
        detail.swipeUp()
        XCTAssertTrue(app.staticTexts["watch-task-detail-progress"].exists)
        let openOnPhone = app.buttons["watch-task-detail-open-on-phone"]
        for _ in 0..<3 where !openOnPhone.isHittable { detail.swipeUp() }
        XCTAssertTrue(openOnPhone.isHittable)
        XCTAssertFalse(app.staticTexts["watch-ui-test-open-request"].exists)
        openOnPhone.tap()
        let openedItem = app.staticTexts["watch-ui-test-open-request"]
        XCTAssertTrue(openedItem.waitForExistence(timeout: 3))
        XCTAssertEqual(openedItem.label, "task:task-one")
        keepScreenshot("Watch read-only Task details")
        app.buttons["watch-task-detail-back"].tap()
        XCTAssertTrue(task.waitForExistence(timeout: 5))
        board.swipeLeft()
        let blocked = app.buttons["watch-task-row-task-blocked"]
        XCTAssertTrue(blocked.waitForExistence(timeout: 5))
        blocked.tap()
        XCTAssertTrue(app.staticTexts["watch-task-detail-blocked-reason"].waitForExistence(timeout: 5))
        app.buttons["watch-task-detail-back"].tap()
        board.swipeLeft()
        XCTAssertTrue(app.buttons["watch-task-row-task-done"].waitForExistence(timeout: 5))
        board.swipeRight()
        XCTAssertTrue(blocked.waitForExistence(timeout: 5))
        keepScreenshot("Watch separate Blocked Kanban page")

        sectionSelector.tap()
        XCTAssertTrue(app.buttons["watch-hub-select-chat"].waitForExistence(timeout: 3))
        keepScreenshot("Watch section menu reopened above Tasks")
        app.buttons["watch-hub-select-workflows"].tap()
        let workflow = app.buttons["watch-workflow-row-workflow-one"]
        XCTAssertTrue(workflow.waitForExistence(timeout: 5))
        keepScreenshot("Watch read-only Workflows list")
        workflow.tap()
        XCTAssertTrue(app.staticTexts["watch-workflow-detail-title"].waitForExistence(timeout: 5))
        XCTAssertEqual(openedItem.label, "task:task-one", "Opening details must not immediately hand off to iPhone.")
        let workflowDetail = app.scrollViews["watch-workflow-detail-scroll"]
        let workflowOnPhone = app.buttons["watch-workflow-detail-open-on-phone"]
        for _ in 0..<8 where !workflowOnPhone.isHittable { workflowDetail.swipeUp() }
        XCTAssertTrue(workflowOnPhone.isHittable)
        workflowOnPhone.tap()
        XCTAssertEqual(openedItem.label, "workflow:workflow-one")
        app.buttons["watch-workflow-detail-back"].tap()
        XCTAssertTrue(workflow.waitForExistence(timeout: 5))

        sectionSelector.tap()
        let chatOption = app.buttons["watch-hub-select-chat"]
        XCTAssertTrue(chatOption.waitForExistence(timeout: 3))
        chatOption.tap()
        let chatsHeading = app.buttons["watch-chats-heading"]
        XCTAssertTrue(chatsHeading.waitForExistence(timeout: 5))
        app.swipeUp()
        XCTAssertTrue(chatsHeading.isHittable)
        chatsHeading.tap()
        XCTAssertTrue(app.buttons["watch-hub-select-tasks"].waitForExistence(timeout: 3))
        keepScreenshot("Watch fixed Chats header and reopened menu")
    }

    @MainActor
    // contract-test: direct surface=gui.apple assertions=apple-watch.lists.read-only-private,apple-watch.hub.compact-navigation
    func testDigitalCrownScrollsActiveKanbanColumnWithoutChangingPage() {
        let app = XCUIApplication()
        app.launchArguments = ["--ui-test-watch-hub-lists"]
        app.launch()
        let tasksOption = app.buttons["watch-hub-select-tasks"]
        XCTAssertTrue(tasksOption.waitForExistence(timeout: 12))
        tasksOption.tap()

        let firstTask = app.buttons["watch-task-row-backlog-0"]
        let lastTask = app.buttons["watch-task-row-backlog-11"]
        let todoTask = app.buttons["watch-task-row-task-two"]
        let backlog = app.scrollViews["watch-task-column-backlog"]
        let sectionSelector = app.buttons["watch-hub-section-selector"]
        XCTAssertTrue(firstTask.waitForExistence(timeout: 5))
        XCTAssertTrue(firstTask.isHittable)
        XCTAssertFalse(lastTask.isHittable)
        let headerY = sectionSelector.frame.minY
        let firstTaskY = firstTask.frame.minY
        keepScreenshot("Watch Backlog before Crown input")

        // Public Watch XCTest Crown API: -1 is one full downward rotation.
        // Crown input alone must reveal the last row in this long column.
        for _ in 0..<12 where !lastTask.isHittable {
            XCUIDevice.shared.rotateDigitalCrown(delta: -1)
            XCTAssertTrue(backlog.exists)
            XCTAssertFalse(todoTask.isHittable)
            XCTAssertTrue(sectionSelector.isHittable)
            XCTAssertEqual(sectionSelector.frame.minY, headerY, accuracy: 0.5)
        }
        keepScreenshot("Watch Backlog after downward Crown input")
        let layout = XCTAttachment(string: app.debugDescription)
        layout.name = "Synthetic Watch Crown layout after downward rotations"
        layout.lifetime = .keepAlways
        add(layout)
        XCTAssertTrue(lastTask.isHittable,
                      "Crown did not reveal the final task; first row y before=\(firstTaskY), after=\(firstTask.frame.minY)")
        XCTAssertFalse(firstTask.isHittable)
        keepScreenshot("Watch Crown scrolled Backlog to final task")

        // Positive rotations scroll upward; they must preserve the same page.
        for _ in 0..<12 where !firstTask.isHittable {
            XCUIDevice.shared.rotateDigitalCrown(delta: 1)
            XCTAssertTrue(backlog.exists)
            XCTAssertFalse(todoTask.isHittable)
            XCTAssertTrue(sectionSelector.isHittable)
            XCTAssertEqual(sectionSelector.frame.minY, headerY, accuracy: 0.5)
        }
        XCTAssertTrue(firstTask.isHittable)
        XCTAssertFalse(lastTask.isHittable)
        keepScreenshot("Watch Crown returned Backlog to first task")

        app.otherElements["watch-task-board"].swipeLeft()
        XCTAssertTrue(todoTask.waitForExistence(timeout: 5))
        XCTAssertTrue(todoTask.isHittable)
        XCTAssertTrue(sectionSelector.isHittable)
        keepScreenshot("Watch horizontal paging after Crown scrolling")
    }

    @MainActor
    // Standalone synthetic ScrollView diagnoses simulator Crown delivery, without a product route.
    // contract-test: tooling
    func testDigitalCrownNativeScrollControl() {
        let app = XCUIApplication()
        app.launchArguments = ["--ui-test-watch-native-crown"]
        app.launch()
        let firstRow = app.staticTexts["watch-native-crown-row-0"]
        let lastRow = app.staticTexts["watch-native-crown-row-11"]
        XCTAssertTrue(firstRow.waitForExistence(timeout: 12))
        XCTAssertTrue(firstRow.isHittable)
        XCTAssertFalse(lastRow.isHittable)
        let initialY = firstRow.frame.minY
        keepScreenshot("Native Watch ScrollView before Crown diagnostic")
        for _ in 0..<12 where !lastRow.isHittable {
            XCUIDevice.shared.rotateDigitalCrown(delta: -1)
        }
        keepScreenshot("Native Watch ScrollView after Crown diagnostic")
        let layout = XCTAttachment(string: app.debugDescription)
        layout.name = "Synthetic standalone native Crown layout"
        layout.lifetime = .keepAlways
        add(layout)
        XCTAssertTrue(lastRow.isHittable,
                      "Native ScrollView Crown delivery failed; first row y before=\(initialY), after=\(firstRow.frame.minY)")
        XCTAssertFalse(firstRow.isHittable)
        for _ in 0..<12 where !firstRow.isHittable {
            XCUIDevice.shared.rotateDigitalCrown(delta: 1)
        }
        XCTAssertTrue(firstRow.isHittable)
        XCTAssertFalse(lastRow.isHittable)
    }

    @MainActor
    // contract-test: tooling
    func testFocusedDigitalCrownBindingReceivesNativeInput() {
        let app = XCUIApplication()
        app.launchArguments = ["--ui-test-watch-crown-binding"]
        app.launch()
        let focus = app.staticTexts["watch-crown-binding-focus"]
        XCTAssertTrue(focus.waitForExistence(timeout: 12))
        expectation(for: NSPredicate(format: "label == 'true'"), evaluatedWith: focus)
        waitForExpectations(timeout: 5)
        let events = app.staticTexts["watch-crown-binding-events"]
        let rotation = app.staticTexts["watch-crown-binding-rotation"]
        let initialRotation = rotation.label
        XCTAssertEqual(events.label, "0")
        XCUIDevice.shared.rotateDigitalCrown(delta: -0.25)
        expectation(for: NSPredicate(format: "label != '0'"), evaluatedWith: events)
        waitForExpectations(timeout: 5)
        keepScreenshot("Focused native Crown binding after input")
        let layout = XCTAttachment(string: app.debugDescription)
        layout.name = "Focused Crown binding delivery diagnostic"
        layout.lifetime = .keepAlways
        add(layout)
        XCTAssertGreaterThan(Int(events.label) ?? 0, 0)
        XCTAssertNotEqual(rotation.label, initialRotation)
        XCTAssertEqual(focus.label, "true")
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
