// Guest-safe native Mates list/detail/composer handoff parity coverage.
// Verifies routed detail, prompt expansion, and current-chat composer preservation.
// The test must never invoke Safari or an external browser destination.
// It uses canonical public mate metadata and no private account state.

import XCTest

@MainActor
final class SettingsMatesParityUITests: XCTestCase {
    override func setUpWithError() throws {
        continueAfterFailure = false
    }

    // contract-test: supporting surface=gui.apple assertions=chats.surface.semantic-parity,settings-ui.navigation.parent-return,settings-ui.parity.web-apple-shell
    func testMateDetailsPromptAndNativeStartChatHandoff() {
        let app = XCUIApplication()
        app.launchArguments = ["--ui-test-disable-auth-cache", "-AppleLanguages", "(en)"]
        app.launch()

        XCTAssertTrue(app.buttons["settings-button"].waitForExistence(timeout: 15))
        app.buttons["settings-button"].tap()
        let matesRow = app.descendants(matching: .any)["settings-mates-row"]
        if !matesRow.waitForExistence(timeout: 8) {
            app.buttons["settings-button"].tap()
        }
        XCTAssertTrue(matesRow.waitForExistence(timeout: 8))
        matesRow.tap()

        XCTAssertTrue(app.descendants(matching: .any)["settings-mates-page"].waitForExistence(timeout: 8))
        XCTAssertFalse(app.tables.firstMatch.exists)
        let mate = app.descendants(matching: .any)["settings-mate-software_development"]
        XCTAssertTrue(mate.waitForExistence(timeout: 5))
        XCTAssertTrue(mate.isHittable)
        mate.tap()
        XCTAssertTrue(app.descendants(matching: .any)["settings-mate-detail"].waitForExistence(timeout: 5))
        let parent = app.buttons["settings-destination-back"]
        XCTAssertTrue(parent.isHittable)
        XCTAssertEqual(parent.label, "Settings / Mates")
        parent.tap()
        XCTAssertTrue(app.descendants(matching: .any)["settings-mate-detail"].waitForNonExistence(timeout: 5))
        XCTAssertTrue(mate.waitForExistence(timeout: 5))
        XCTAssertTrue(mate.isHittable)
        mate.tap()
        XCTAssertTrue(app.scrollViews["settings-mate-detail"].waitForExistence(timeout: 5))

        let promptToggle = app.buttons["settings-mate-prompt-toggle"].firstMatch
        XCTAssertTrue(promptToggle.waitForExistence(timeout: 5))
        let detail = app.scrollViews["settings-mate-detail"]
        reveal(promptToggle, in: detail)
        promptToggle.tap()
        assertRenderedPrompt(in: app, detail: detail)
        reveal(promptToggle, in: detail)
        promptToggle.tap()
        XCTAssertTrue(app.descendants(matching: .any)["mate-system-prompt"].waitForNonExistence(timeout: 5))
        let startChat = app.buttons["settings-mate-start-chat"].firstMatch
        XCTAssertTrue(startChat.waitForExistence(timeout: 5))
        reveal(startChat, in: detail)
        startChat.tap()
        XCTAssertTrue(app.descendants(matching: .any)["message-composer"].waitForExistence(timeout: 8))
        XCTAssertNotEqual(XCUIApplication(bundleIdentifier: "com.apple.mobilesafari").state, .runningForeground)
    }

    // contract-test: supporting surface=gui.apple assertions=message-input.drafts.preview-persistence,chats.surface.semantic-parity,settings-ui.navigation.parent-return
    func testMateSelectionPreservesCurrentChatAndDraft() {
        let app = XCUIApplication()
        app.launchArguments = ["--ui-test-disable-auth-cache", "--ui-test-authenticated-chat-navigation", "-AppleLanguages", "(en)"]
        app.launchEnvironment["UI_TEST_AUTHENTICATED_CHAT_NAVIGATION"] = "1"
        app.launch()
        let title = app.staticTexts["chat-header-title"]
        XCTAssertTrue(title.waitForExistence(timeout: 12))
        XCTAssertEqual(title.label, "Current Chat")
        let editor = app.descendants(matching: .any)["message-editor"].firstMatch
        XCTAssertTrue(editor.waitForExistence(timeout: 8))
        editor.tap()
        editor.typeText("Keep this draft")
        app.coordinate(withNormalizedOffset: CGVector(dx: 0.5, dy: 0.25)).tap()

        app.buttons["settings-button"].tap()
        let mates = app.descendants(matching: .any)["settings-mates-row"].firstMatch
        XCTAssertTrue(mates.waitForExistence(timeout: 8))
        mates.tap()
        let mate = app.buttons["settings-mate-software_development"]
        XCTAssertTrue(mate.waitForExistence(timeout: 5))
        mate.tap()
        let toggle = app.buttons["settings-mate-prompt-toggle"]
        XCTAssertTrue(toggle.waitForExistence(timeout: 5))
        let detail = app.scrollViews["settings-mate-detail"]
        XCTAssertTrue(detail.waitForExistence(timeout: 5))
        reveal(toggle, in: detail)
        toggle.tap()
        assertRenderedPrompt(in: app, detail: detail)
        reveal(toggle, in: detail)
        toggle.tap()
        XCTAssertTrue(app.descendants(matching: .any)["mate-system-prompt"].waitForNonExistence(timeout: 5))
        app.buttons["settings-destination-back"].tap()
        XCTAssertTrue(detail.waitForNonExistence(timeout: 5))
        XCTAssertTrue(mate.waitForExistence(timeout: 5))
        XCTAssertTrue(mate.isHittable)
        mate.tap()
        XCTAssertTrue(detail.waitForExistence(timeout: 5))
        XCTAssertFalse(app.descendants(matching: .any)["mate-system-prompt"].exists,
                       "Returning to the detail starts with its prompt collapsed")
        let select = app.buttons["settings-mate-start-chat"]
        XCTAssertTrue(select.waitForExistence(timeout: 5))
        reveal(select, in: detail)
        select.tap()
        XCTAssertTrue(editor.waitForExistence(timeout: 8))
        let preserved = XCTNSPredicateExpectation(
            predicate: NSPredicate(format: "value CONTAINS %@", "Keep this draft"),
            object: editor)
        XCTAssertEqual(XCTWaiter.wait(for: [preserved], timeout: 5), .completed)
        // The canonical mention is a TextKit attachment. Its raw editor value
        // contains an object replacement character; assert the rendered chip.
        let chip = app.staticTexts["@Software Development"].firstMatch
        XCTAssertTrue(chip.waitForExistence(timeout: 5))
        XCTAssertTrue(chip.isHittable)
        XCTAssertTrue(app.descendants(matching: .any)["message-composer"].firstMatch.frame.intersects(chip.frame))
        let attachment = XCTAttachment(screenshot: app.screenshot())
        attachment.name = "Mates selection preserves current chat and draft"
        attachment.lifetime = .keepAlways
        add(attachment)
        XCTAssertEqual(title.label, "Current Chat")
        let metrics = app.staticTexts.containing(NSPredicate(format: "label CONTAINS %@", "chat-navigation-order=")).firstMatch
        XCTAssertTrue(metrics.label.contains("selected-chat-id=ui-test-current-chat"))
        XCTAssertTrue(editor.isHittable)
        XCTAssertFalse(detail.exists && detail.isHittable, "The retained Mates pane must not cover the active composer")
    }

    private func reveal(_ element: XCUIElement, in detail: XCUIElement) {
        for _ in 0..<8 where !element.isHittable {
            if element.exists && element.frame.maxY < detail.frame.minY { detail.swipeDown() }
            else { detail.swipeUp() }
        }
        XCTAssertTrue(element.isHittable, "Expected the Mates control to be visible after scrolling")
        XCTAssertTrue(detail.frame.intersects(element.frame))
    }

    private func assertRenderedPrompt(in app: XCUIApplication, detail: XCUIElement) {
        let prompt = app.staticTexts["mate-system-prompt"].firstMatch
        XCTAssertTrue(prompt.waitForExistence(timeout: 5))
        XCTAssertFalse(prompt.label.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
        XCTAssertTrue(detail.frame.intersects(prompt.frame), "Expanded prompt must be rendered in the visible detail viewport")
        let attachment = XCTAttachment(screenshot: app.screenshot())
        attachment.name = "Mates expanded system prompt"
        attachment.lifetime = .keepAlways
        add(attachment)
    }
}
