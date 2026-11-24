// Captures "before" screenshots of the native iPhone app for the UI parity list:
// start screen, active chat with header and composer, the "@" mention dropdown and
// (best effort) the recording state. Uses only the synthetic authenticated chat
// fixture (--ui-test-authenticated-chat-navigation): no accounts, no network.
// Every screenshot is attached with `.keepAlways` as `apple-before-NN-<name>`.

// "Before" screenshots of the native iPhone app for the owner's Apple/web parity list
// (start screen, active chat header and composer, "@" mention dropdown, recording).
// Uses only the synthetic authenticated-navigation fixture: no accounts, no network.
// System permission prompts and the offline-models banner are dismissed before each
// shot so they never cover the screen being compared.

import XCTest

@MainActor
final class AppleParityScreensUITests: XCTestCase {
    override func setUpWithError() throws {
        continueAfterFailure = false
        #if os(iOS)
        XCUIDevice.shared.orientation = .portrait
        #endif
    }

    // contract-test: supporting surface=gui.apple assertions=chats.surface.semantic-parity,daily-inspiration.start-row-suggestions,daily-inspiration.start-suggestions-layout
    func testCaptureStartScreen() throws {
        let app = launchFixture(extra: ["--ui-test-start-new-chat", "--ui-test-start-inspiration"])
        XCTAssertTrue(element(app, "message-editor").waitForExistence(timeout: 30), "Start screen composer missing")
        XCTAssertTrue(app.buttons["report-issue-button"].isHittable,
                      "The new-chat welcome must expose Report Issue")
        Thread.sleep(forTimeInterval: 2)
        XCTAssertFalse(element(app, "daily-inspiration-card").exists, "The start screen has no inspiration banner")
        XCTAssertTrue(element(app, "welcome-row-actions").waitForExistence(timeout: 15), "Browse actions tile missing from the row")
        // Web parity: one CTA line (chats.resume_last_chat.title) and an inspiration card that is the
        // normal chat card with a "Daily inspiration" label, even when the inspiration has a picture.
        XCTAssertTrue(element(app, "chat-welcome-heading").label.hasPrefix("Hey "), "Start screen greeting missing")
        let cta = element(app, "welcome-workspace-subtitle")
        XCTAssertTrue(cta.waitForExistence(timeout: 10), "Start screen call to action missing")
        XCTAssertEqual(cta.label, "Continue your recent chats:")
        XCTAssertTrue(element(app, "welcome-row-inspiration-card").waitForExistence(timeout: 15), "Inspiration card missing from the row")
        XCTAssertFalse(element(app, "welcome-row-inspiration-image").exists, "Inspiration cards never use a picture background")
        capture(app, "apple-01-start-screen")
        capture(app, "apple-chats-start")
        // Web TASK-1321/AJV2Q: up to three one-line suggestions directly above the composer, below
        // the row; a tap fills the composer.
        let suggestions = element(app, "start-screen-suggestions")
        XCTAssertTrue(suggestions.waitForExistence(timeout: 15), "Start screen suggestions missing")
        let carousel = element(app, "welcome-chat-cards-carousel")
        let composerTop = element(app, "message-editor").frame.minY
        XCTAssertGreaterThan(suggestions.frame.minY, carousel.frame.maxY - 1, "Suggestions sit below the start row")
        XCTAssertLessThanOrEqual(suggestions.frame.maxY, composerTop, "Suggestions sit above the composer")
        XCTAssertLessThan(composerTop - suggestions.frame.maxY, 48, "Suggestions sit directly above the composer")
        let rows = (0..<4).map { element(app, "start-screen-suggestion-\($0)") }.filter { $0.exists }
        XCTAssertTrue((1...3).contains(rows.count), "Expected 1-3 suggestion rows, got \(rows.count)")
        for row in rows { XCTAssertLessThanOrEqual(row.frame.height, 32, "Suggestion rows are a single line") }
        for row in rows { XCTAssertEqual(row.frame.minX, rows[0].frame.minX, accuracy: 1) }
        let inspiration = element(app, "welcome-row-inspiration-card")
        for _ in 0..<4 where !inspiration.isHittable { carousel.swipeLeft() }
        XCTAssertTrue(inspiration.isHittable, "Daily inspiration is a tappable start card")
        XCTAssertGreaterThan(inspiration.frame.height, 150, "Portrait inspiration uses the large chat-card layout")
        capture(app, "apple-chats-large-inspiration")
        let first = rows[0]
        let label = first.label
        first.tap()
        let editor = element(app, "message-editor")
        let value = (editor.value as? String) ?? editor.label
        XCTAssertTrue(value.contains(label), "Tapping a suggestion puts its text into the composer")
    }

    // contract-test: direct surface=gui.apple assertions=daily-inspiration.start-row-active-first
    func testRunningChatLeadsStartRowWithActivePill() throws {
        let app = launchFixture(extra: ["--ui-test-start-new-chat", "--ui-test-start-row-active-chat"])
        XCTAssertTrue(element(app, "message-editor").waitForExistence(timeout: 30), "Start screen composer missing")
        // Web ActiveChatsHeading replaces "Continue your recent chats:" while chats run.
        let heading = element(app, "active-chats-heading")
        XCTAssertTrue(heading.waitForExistence(timeout: 15), "Active chats heading missing")
        XCTAssertEqual(heading.label, "You have 1 chat active:")
        XCTAssertFalse(element(app, "welcome-workspace-subtitle").exists, "The active heading replaces the call to action")
        XCTAssertFalse(element(app, "active-chats-link").exists, "The active count is plain text, not a link")
        let pill = element(app, "start-row-active-pill")
        XCTAssertTrue(pill.waitForExistence(timeout: 15), "Active pill missing on the running chat card")
        let cards = app.descendants(matching: .any).matching(NSPredicate(format: "identifier BEGINSWITH 'welcome-chat-card-'"))
            .allElementsBoundByIndex.filter { $0.exists && $0.frame.width > 100 }
        XCTAssertGreaterThan(cards.count, 1, "Expected several chat cards in the row")
        let firstCard = cards.min(by: { $0.frame.minX < $1.frame.minX })!
        XCTAssertTrue(firstCard.frame.contains(CGPoint(x: pill.frame.midX, y: pill.frame.midY)),
            "The running chat is the first card of the row and carries the Active pill")
        XCTAssertLessThan(pill.frame.minX - firstCard.frame.minX, 30, "The Active pill sits in the top-left corner")
        XCTAssertLessThan(pill.frame.minY - firstCard.frame.minY, 30, "The Active pill sits in the top-left corner")
        capture(app, "apple-chats-start-active")
    }

    // contract-test: supporting surface=gui.apple assertions=chats.surface.semantic-parity
    func testCaptureActiveChatHeaderAndComposer() throws {
        let app = launchFixture(extra: ["--ui-test-voice-call-ready"])
        XCTAssertTrue(element(app, "chat-header-title").waitForExistence(timeout: 60), "Active chat header missing")
        XCTAssertTrue(element(app, "message-editor").waitForExistence(timeout: 15))
        // Web parity: report issue top left, call then close top right.
        let report = element(app, "report-issue-button")
        let call = element(app, "voice-call-start")
        let close = element(app, "chat-close-button")
        XCTAssertTrue(call.waitForExistence(timeout: 15), "Call button missing for a supported chat")
        XCTAssertTrue(report.isHittable && call.isHittable && close.isHittable)
        XCTAssertLessThan(report.frame.maxX, app.frame.midX, "report issue must sit on the left")
        XCTAssertGreaterThan(call.frame.minX, app.frame.midX, "call must sit on the right")
        XCTAssertLessThan(call.frame.maxX, close.frame.minX + 1, "call sits just left of close")
        capture(app, "apple-02-active-chat-header-composer")
    }

    // contract-test: supporting surface=gui.apple assertions=chats.surface.semantic-parity
    func testCaptureMentionDropdown() throws {
        let app = launchFixture()
        let editor = element(app, "message-editor")
        XCTAssertTrue(editor.waitForExistence(timeout: 60))
        editor.tap()
        app.typeText("@")
        XCTAssertTrue(element(app, "mention-dropdown").waitForExistence(timeout: 10), "Mention dropdown did not open")
        // 5c: the results show right away and no auto-selection notice takes their place.
        let firstResult = element(app, "mention-result")
        XCTAssertTrue(firstResult.waitForExistence(timeout: 5) && firstResult.isHittable, "No visible mention result")
        let notice = app.staticTexts.containing(NSPredicate(format: "label CONTAINS[c] %@", "auto selects")).firstMatch
        XCTAssertFalse(notice.exists, "Auto-selection notice is still shown")
        capture(app, "apple-03-mention-dropdown")
        // Clear the "@" so the saved draft does not reopen the list in later launches.
        app.typeText(XCUIKeyboardKey.delete.rawValue)
        XCTAssertTrue(element(app, "mention-dropdown").waitForNonExistence(timeout: 5), "Mention dropdown stayed open")
    }

    // contract-test: supporting surface=gui.apple assertions=chats.surface.semantic-parity
    func testCaptureRecordingState() throws {
        // The live microphone path stops the app on the hosted simulator (no audio
        // input), so the real chat screen forces its recording state without a
        // microphone. Web parity: the composer turns into the slim 48pt bar.
        let app = launchFixture(extra: ["--ui-test-force-recording-overlay"])
        let overlay = element(app, "record-overlay")
        XCTAssertTrue(overlay.waitForExistence(timeout: 60), "Recording bar missing")
        XCTAssertEqual(overlay.frame.height, 48, accuracy: 1, "Composer recording is the web compact bar")
        let cancel = element(app, "record-cancel-button")
        let finish = element(app, "record-finish-button")
        XCTAssertTrue(cancel.isHittable && finish.isHittable)
        XCTAssertLessThan(cancel.frame.maxX, finish.frame.minX, "cancel on the left, finish on the right")
        XCTAssertFalse(element(app, "timer-pill").exists, "no timer pill in the compact bar")
        XCTAssertFalse(element(app, "mention-dropdown").exists, "no leftover mention list behind the recording bar")
        capture(app, "apple-04-recording-state")
    }

    private func launchFixture(extra: [String] = []) -> XCUIApplication {
        let app = XCUIApplication()
        app.launchArguments = ["--ui-test-authenticated-chat-navigation", "--ui-test-workspace-sidebar-fixture"] + extra
        app.launch()
        clearPrompts(app)
        return app
    }

    private func element(_ app: XCUIApplication, _ id: String) -> XCUIElement {
        app.descendants(matching: .any)[id].firstMatch
    }

    /// Answers system permission alerts (notifications, microphone) and closes the
    /// offline-models banner, so neither covers the screenshot.
    private func clearPrompts(_ app: XCUIApplication) {
        let springboard = XCUIApplication(bundleIdentifier: "com.apple.springboard")
        for _ in 0..<3 {
            let alert = springboard.alerts.firstMatch
            guard alert.waitForExistence(timeout: 1) else { break }
            let allow = alert.buttons["Allow"]
            (allow.exists ? allow : alert.buttons.element(boundBy: 0)).tap()
        }
        let later = app.buttons["Later"]
        if later.exists && later.isHittable {
            later.tap()
            // Let the banner finish sliding out so it is not in the shot.
            Thread.sleep(forTimeInterval: 1.5)
        }
    }

    private func capture(_ app: XCUIApplication, _ name: String) {
        clearPrompts(app)
        let shot = XCTAttachment(screenshot: app.screenshot())
        shot.name = name
        shot.lifetime = .keepAlways
        add(shot)
    }
}
