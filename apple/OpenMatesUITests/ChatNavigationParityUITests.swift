// Chat header/sidebar navigation parity coverage.
// Launches a DEBUG-only authenticated fixture with deterministic in-memory chats
// so the native app can prove the same sidebar/header order as the web spec
// without credentials, private records, WebSocket traffic, or provider calls.
//
// Web source: frontend/apps/web_app/tests/chat-header-navigation-order.spec.ts

import XCTest

@MainActor
final class ChatNavigationParityUITests: XCTestCase {
    override func setUpWithError() throws {
        continueAfterFailure = false
    }

    // contract-test: direct surface=gui.apple assertions=chat-navigation.draft-only.addressable,chat-navigation.order.sidebar-header-match,chat-navigation.empty-new-chat.excluded
    func testHeaderNavigationFollowsSidebarOrderIncludingDraftOnlyChat() throws {
        let app = XCUIApplication()
        app.launchArguments = ["--ui-test-authenticated-chat-navigation"]
        app.launchEnvironment["UI_TEST_AUTHENTICATED_CHAT_NAVIGATION"] = "1"
        app.launch()

        XCTAssertTrue(app.wait(for: .runningForeground, timeout: 12))
        try assertHeaderTitle("Current Chat", in: app)

        let metrics = app.staticTexts
            .containing(NSPredicate(format: "label CONTAINS %@", "chat-navigation-order="))
            .firstMatch
        XCTAssertTrue(metrics.waitForExistence(timeout: 12))
        let order = try stringMetric("chat-navigation-order", in: metrics.label)
        XCTAssertTrue(
            order.hasPrefix("ui-test-draft-chat,ui-test-newer-chat,ui-test-current-chat,ui-test-older-chat"),
            "Header navigation order must match the rendered sidebar order. Actual: \(order)"
        )
        XCTAssertFalse(order.contains("ui-test-empty-shell-chat"), "Empty new-chat shells must not be navigable.")
        XCTAssertEqual(try stringMetric("selected-chat-id", in: metrics.label), "ui-test-current-chat")

        let sidebarToggle = app.buttons["sidebar-toggle"]
        sidebarToggle.tap()
        XCTAssertTrue(app.descendants(matching: .any)["chat-history-panel"].waitForExistence(timeout: 5))
        try assertSidebarRowsInOrder(["Header navigation draft", "Newer Chat", "Current Chat", "Older Chat"], in: app)
        app.terminate()
        app.launch()
        XCTAssertTrue(app.wait(for: .runningForeground, timeout: 12))
        try assertHeaderTitle("Current Chat", in: app)

        let nextButton = app.buttons["chat-header-next"]
        let previousButton = app.buttons["chat-header-previous"]
        XCTAssertTrue(nextButton.waitForExistence(timeout: 5))
        XCTAssertTrue(previousButton.waitForExistence(timeout: 5))
        XCTAssertLessThan(nextButton.frame.midX, previousButton.frame.midX, "Next/newer control belongs on the left; previous/older belongs on the right.")

        previousButton.tap()
        try assertHeaderTitle("Older Chat", in: app)
        XCTAssertEqual(try waitForMetric("selected-chat-id", equals: "ui-test-older-chat", in: metrics), "ui-test-older-chat")

        app.buttons["chat-header-next"].tap()
        try assertHeaderTitle("Current Chat", in: app)
        XCTAssertEqual(try waitForMetric("selected-chat-id", equals: "ui-test-current-chat", in: metrics), "ui-test-current-chat")

        app.buttons["chat-header-next"].tap()
        try assertHeaderTitle("Newer Chat", in: app)
        XCTAssertEqual(try waitForMetric("selected-chat-id", equals: "ui-test-newer-chat", in: metrics), "ui-test-newer-chat")

        app.buttons["chat-header-next"].tap()
        try assertHeaderTitle("Header navigation draft", in: app)
        XCTAssertTrue(app.descendants(matching: .any)["draft-chat-badge"].waitForExistence(timeout: 5))
        XCTAssertEqual(try waitForMetric("selected-chat-id", equals: "ui-test-draft-chat", in: metrics), "ui-test-draft-chat")
    }

    private func assertHeaderTitle(_ expected: String, in app: XCUIApplication) throws {
        let title = app.staticTexts["chat-header-title"]
        XCTAssertTrue(title.waitForExistence(timeout: 8), "Missing chat header title for \(expected)")
        XCTAssertEqual(title.label, expected)
    }

    private func assertSidebarRowsInOrder(_ titles: [String], in app: XCUIApplication) throws {
        let rows = titles.map { title in
            app.buttons.matching(NSPredicate(format: "label == %@", title)).firstMatch
        }
        for (index, row) in rows.enumerated() {
            XCTAssertTrue(row.waitForExistence(timeout: 5), "Missing sidebar row: \(titles[index])")
        }
        for index in 1..<rows.count {
            XCTAssertLessThan(rows[index - 1].frame.minY, rows[index].frame.minY)
        }
    }

    private func waitForMetric(_ key: String, equals expected: String, in element: XCUIElement) throws -> String {
        let deadline = Date().addingTimeInterval(5)
        while Date() < deadline {
            if let value = metric(key, in: element.label), value == expected {
                return value
            }
            RunLoop.current.run(until: Date().addingTimeInterval(0.1))
        }
        XCTFail("Timed out waiting for \(key)=\(expected). Last metrics: \(element.label)")
        return try stringMetric(key, in: element.label)
    }

    private func stringMetric(_ key: String, in label: String) throws -> String {
        try XCTUnwrap(metric(key, in: label), "Missing metric \(key) in: \(label)")
    }

    private func metric(_ key: String, in label: String) -> String? {
        label
            .split(separator: ";")
            .map { $0.trimmingCharacters(in: .whitespacesAndNewlines) }
            .first { $0.hasPrefix("\(key)=") }?
            .dropFirst(key.count + 1)
            .description
    }
}
