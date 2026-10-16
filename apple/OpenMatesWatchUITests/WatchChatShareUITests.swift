// Account-free production Watch header/menu/share screen proof.
import XCTest

@MainActor
final class WatchChatShareUITests: XCTestCase {
    // contract-test: direct surface=gui.apple assertions=apple-watch.chats.browse-search-open,apple-watch.chats.compact-layout
    func testWorkspaceRowsShowCachedCategoryIconOverrideFallbackAndLegacyState() {
        continueAfterFailure = false
        let app = XCUIApplication()
        app.launchArguments = ["--ui-test-watch-chat-list-metadata"]
        app.launch()
        let row = app.buttons["watch-chat-row-watch-list-explicit"]
        XCTAssertTrue(row.waitForExistence(timeout: 12))
        for _ in 0..<5 where !row.isHittable { app.swipeUp() }
        XCTAssertTrue(row.isHittable)
        let category = app.staticTexts["watch-chat-row-category-watch-list-explicit"]
        XCTAssertTrue(category.exists)
        XCTAssertFalse(category.label.isEmpty)
        XCTAssertFalse(category.label.contains("chat.interests."), "Category resolves a bundled locale key")
        XCTAssertGreaterThan(category.frame.width, 0)
        let categoryLabel = category.label
        let explicit = app.descendants(matching: .any)["watch-chat-row-icon-watch-list-explicit"]
        XCTAssertTrue(explicit.exists)
        XCTAssertEqual(explicit.value as? String, "lucide-code", "Valid cached icon overrides the science fallback")
        XCTAssertGreaterThan(explicit.frame.width, 0)
        let fallbackRow = app.buttons["watch-chat-row-watch-list-fallback"]
        for _ in 0..<5 where !fallbackRow.isHittable { app.swipeUp() }
        XCTAssertTrue(fallbackRow.isHittable)
        let fallback = app.descendants(matching: .any)["watch-chat-row-icon-watch-list-fallback"]
        XCTAssertEqual(fallback.value as? String, "lucide-microscope")
        XCTAssertEqual(app.staticTexts["watch-chat-row-category-watch-list-fallback"].label, categoryLabel)
        let legacyRow = app.buttons["watch-chat-row-watch-list-legacy"]
        for _ in 0..<5 where !legacyRow.isHittable { app.swipeUp() }
        XCTAssertTrue(legacyRow.isHittable)
        let legacy = app.descendants(matching: .any)["watch-chat-row-icon-watch-list-legacy"]
        XCTAssertEqual(legacy.value as? String, "lucide-help-circle")
        XCTAssertFalse(app.staticTexts["watch-chat-row-category-watch-list-legacy"].exists,
                       "Legacy cache does not invent a category before metadata arrives")
        let artifact = XCTAttachment(screenshot: XCUIScreen.main.screenshot())
        artifact.name = "Watch cached category rows and legacy fallback"
        artifact.lifetime = .keepAlways
        add(artifact)
    }

    // contract-test: direct surface=gui.apple assertions=apple-watch.chats.compact-layout
    // contract-test: supporting surface=gui.apple assertions=chat-share-settings.shared-link-open
    func testCachedHeaderLongPressShareAndSyntheticEncryptedShortURL() {
        continueAfterFailure = false
        let app = XCUIApplication()
        app.launchArguments = ["--ui-test-watch-chat-share"]
        app.launch()
        let title = app.staticTexts["watch-chat-header-title"].firstMatch
        XCTAssertTrue(title.waitForExistence(timeout: 12))
        XCTAssertEqual(title.label, "Watch sharing example")
        XCTAssertGreaterThan(title.frame.width, 0)
        XCTAssertTrue(app.descendants(matching: .any)["watch-chat-header-icon"].exists)
        let message = app.staticTexts["A synthetic sharing example."]
        for _ in 0..<3 where !message.isHittable { app.swipeUp() }
        XCTAssertTrue(message.isHittable)
        message.press(forDuration: 1)
        let share = app.buttons["watch-message-share"]
        XCTAssertTrue(share.waitForExistence(timeout: 5)); XCTAssertTrue(share.isHittable)
        XCTAssertTrue(app.buttons["watch-message-zoom-in"].exists)
        share.tap()
        XCTAssertTrue(app.descendants(matching: .any)["watch-chat-share-screen"].waitForExistence(timeout: 5))
        XCTAssertFalse(app.staticTexts["watch-chat-share-short-url"].exists)
        // watchOS propagates the enclosing screen identifier to both its
        // ScrollView and fixed close Button; their element types distinguish them.
        let scroll = app.scrollViews["watch-chat-share-screen"]
        XCTAssertTrue(scroll.waitForExistence(timeout: 5))
        let duration = app.buttons["watch-chat-share-duration-600"]
        reveal(duration, in: scroll)
        XCTAssertTrue(duration.isHittable); duration.tap()
        XCTAssertTrue(duration.isSelected, "The encrypted share uses the selected ten-minute expiry")
        let create = app.buttons["watch-chat-share-create"]
        reveal(create, in: scroll)
        XCTAssertTrue(create.isHittable); create.tap()
        let url = app.staticTexts["watch-chat-share-short-url"]
        XCTAssertTrue(url.waitForExistence(timeout: 20))
        XCTAssertTrue(url.label.contains("/s/")); XCTAssertTrue(url.label.contains("#"))
        XCTAssertFalse(url.label.contains("/share/chat/"))
        XCTAssertFalse(app.descendants(matching: .any)["share-qr-code"].exists)
        // The generated screen scrolls back to its compact header and full URL.
        reveal(url, in: scroll)
        XCTAssertTrue(url.isHittable)
        XCTAssertGreaterThan(url.frame.width, 0)
        let artifact = XCTAttachment(screenshot: XCUIScreen.main.screenshot())
        artifact.name = "Watch synthetic encrypted short share URL without QR"
        artifact.lifetime = .keepAlways
        add(artifact)
        let close = app.buttons["watch-chat-share-screen"]
        XCTAssertTrue(close.isHittable)
        close.tap()
        let dismissed = XCTNSPredicateExpectation(predicate: NSPredicate(format: "exists == false"), object: scroll)
        XCTAssertEqual(XCTWaiter.wait(for: [dismissed], timeout: 5), .completed,
                       "Close dismisses the exclusive share screen before restoring the composer")
        XCTAssertTrue(app.textFields["watch-message-input"].waitForExistence(timeout: 5))
    }

    private func reveal(_ element: XCUIElement, in scroll: XCUIElement) {
        // Full-screen flicks can skip a short Watch row and cross the fixed close
        // control. Keep drags inside the viewport and recover an overshot row.
        for _ in 0..<16 where !element.isHittable {
            let above = element.exists && !element.frame.isEmpty && element.frame.midY < scroll.frame.midY
            let start = scroll.coordinate(withNormalizedOffset: CGVector(dx: 0.5, dy: above ? 0.35 : 0.75))
            let end = scroll.coordinate(withNormalizedOffset: CGVector(dx: 0.5, dy: above ? 0.75 : 0.35))
            start.press(forDuration: 0.05, thenDragTo: end)
        }
    }
}
