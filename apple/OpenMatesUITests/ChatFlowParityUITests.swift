// UI parity smoke coverage for the native chat-flow surface.
// Uses the debug-only seeded chat preview so assertions are deterministic and
// do not require credentials, private chat records, network access, or AI calls.
// The deterministic parity audit covers token/source mappings; this simulator
// test verifies the visible native hierarchy exposes the expected chat elements.

import XCTest

@MainActor
final class ChatFlowParityUITests: XCTestCase {
    override func setUpWithError() throws {
        continueAfterFailure = false
    }

    func testUnauthenticatedColdBootShowsNewChatParitySurface() throws {
        let app = XCUIApplication()
        app.launchArguments = [
            "--ui-test-disable-auth-cache",
            "--ui-test-show-workspace-tabs"
        ]
        app.launch()

        XCTAssertTrue(app.descendants(matching: .any)["compact-logo-button"].waitForExistence(timeout: 10))
        XCTAssertTrue(app.descendants(matching: .any)["daily-inspiration-card"].waitForExistence(timeout: 15))
        XCTAssertTrue(app.descendants(matching: .any)["guest-interest-tags"].waitForExistence(timeout: 15))
        XCTAssertTrue(app.staticTexts["What are your interests?"].exists)

        XCTAssertTrue(app.buttons["interest-tag-privacy"].waitForExistence(timeout: 5))
        XCTAssertEqual(
            app.buttons.matching(NSPredicate(format: "label CONTAINS %@", "chat.interests.")).count,
            0,
            "Interest tags must resolve localized labels instead of raw i18n keys"
        )

        XCTAssertTrue(app.descendants(matching: .any)["workspace-switcher"].exists)
        openWorkspace("projects", in: app)
        XCTAssertTrue(app.descendants(matching: .any)["workspace-placeholder-projects"].waitForExistence(timeout: 5))
        XCTAssertTrue(app.descendants(matching: .any)["workspace-placeholder-return-to-chats"].exists)
        let switcher = app.descendants(matching: .any)["workspace-switcher"]
        XCTAssertTrue(switcher.isEnabled)
        XCTAssertEqual(switcher.label, "Projects")

        openWorkspace("tasks", in: app)
        XCTAssertTrue(app.descendants(matching: .any)["workspace-placeholder-tasks"].waitForExistence(timeout: 5))

        openWorkspace("plans", in: app)
        XCTAssertTrue(app.descendants(matching: .any)["workspace-placeholder-plans"].waitForExistence(timeout: 5))

        openWorkspace("workflows", in: app)
        XCTAssertTrue(app.descendants(matching: .any)["workspace-placeholder-workflows"].waitForExistence(timeout: 5))

        openWorkspace("chats", in: app)
        XCTAssertTrue(app.descendants(matching: .any)["guest-interest-tags"].waitForExistence(timeout: 5))
        XCTAssertFalse(app.tables.firstMatch.exists, "Product chat UI must not render default List/table chrome")

        attachScreenshot(name: "Unauthenticated new-chat parity surface")
    }

    func testVisibleChatFlowElementsMatchWebParitySnapshot() throws {
        let app = XCUIApplication()
        app.launchArguments = ["--dev-preview", "chat-opening", "--ui-test-header-contract"]
        app.launchEnvironment["DEV_PREVIEW"] = "chat-opening"
        app.launchEnvironment["UI_TEST_HEADER_CONTRACT"] = "1"
        app.launch()

        let counter = app.staticTexts
            .containing(NSPredicate(format: "label CONTAINS %@", "initial-window-count=50"))
            .firstMatch
        XCTAssertTrue(counter.waitForExistence(timeout: 12))
        attachScreenshot(name: "Seeded chat-flow loaded")

        XCTAssertTrue(app.staticTexts["Native Chat Opening Preview"].exists)
        let headerContract = app.staticTexts
            .containing(NSPredicate(format: "label CONTAINS %@", "chat-header-title="))
            .firstMatch
        XCTAssertTrue(headerContract.waitForExistence(timeout: 5))
        XCTAssertTrue(headerContract.label.contains("chat-header-title=Seeded Large Chat"))
        XCTAssertTrue(headerContract.label.contains("chat-header-icon=true"))

        let userMessage = app.staticTexts
            .containing(NSPredicate(format: "label CONTAINS %@", "Seeded user message"))
            .firstMatch
        let assistantMessage = app.staticTexts
            .containing(NSPredicate(format: "label CONTAINS %@", "Seeded assistant message"))
            .firstMatch
        XCTAssertTrue(userMessage.waitForExistence(timeout: 5))
        XCTAssertTrue(assistantMessage.waitForExistence(timeout: 5))
        XCTAssertTrue(app.staticTexts["Latest assistant response visible after bounded open"].exists)
        XCTAssertTrue(app.textViews.firstMatch.exists || app.textFields.firstMatch.exists)
        XCTAssertFalse(app.tables.firstMatch.exists, "Product chat UI must not render default List/table chrome")

        attachScreenshot(name: "Seeded chat-flow parity hierarchy")
    }

    func testChatFloatingReportButtonOpensReportIssueForm() throws {
        let app = XCUIApplication()
        app.launchArguments = ["--dev-preview", "chat-opening", "--ui-test-chat-report-form"]
        app.launchEnvironment["DEV_PREVIEW"] = "chat-opening"
        app.launchEnvironment["UI_TEST_CHAT_REPORT_FORM"] = "1"
        app.launch()

        let counter = app.staticTexts
            .containing(NSPredicate(format: "label CONTAINS %@", "initial-window-count=50"))
            .firstMatch
        XCTAssertTrue(counter.waitForExistence(timeout: 12))

        let reportButton = app.descendants(matching: .any)["chat-floating-action-bug"]
        XCTAssertTrue(reportButton.waitForExistence(timeout: 12))
        XCTAssertFalse(app.staticTexts["common.report"].exists)

        reportButton.tap()

        XCTAssertTrue(app.descendants(matching: .any)["dev-report-issue-overlay"].waitForExistence(timeout: 5))
        XCTAssertTrue(app.descendants(matching: .any)["settings-report-issue-form"].waitForExistence(timeout: 5))
        XCTAssertFalse(app.staticTexts["common.report"].exists)

        attachScreenshot(name: "Chat floating report opens report form")
    }

    func testVisualChatFlowSurfaceUsesProductChromeOnly() throws {
        let app = XCUIApplication()
        app.launchArguments = ["--dev-preview", "chat-opening", "--ui-test-visual-snapshot"]
        app.launchEnvironment["DEV_PREVIEW"] = "chat-opening"
        app.launchEnvironment["UI_TEST_VISUAL_SNAPSHOT"] = "1"
        app.launch()

        let scrollToBottom = app.buttons["Scroll to bottom"]
        XCTAssertTrue(scrollToBottom.waitForExistence(timeout: 12))
        scrollToBottom.tap()

        let latestAssistantMessage = app.staticTexts["Latest assistant response visible after bounded open"]
        XCTAssertTrue(latestAssistantMessage.waitForExistence(timeout: 12))
        XCTAssertFalse(app.staticTexts["Native Chat Opening Preview"].exists)
        XCTAssertFalse(app.tables.firstMatch.exists, "Product chat UI must not render default List/table chrome")

        attachScreenshot(name: "Seeded chat-flow visual snapshot")
    }

    func testGuestInterestTagsSelectAndFilterSuggestions() throws {
        let app = XCUIApplication()
        app.launchArguments = ["--ui-test-disable-auth-cache", "--ui-test-start-new-chat"]
        app.launch()

        XCTAssertTrue(app.descendants(matching: .any)["guest-interest-tags"].waitForExistence(timeout: 15))
        XCTAssertFalse(app.descendants(matching: .any)["guest-interest-continue"].exists)

        tapVisibleInterestTags(count: 3, in: app)
        XCTAssertFalse(app.descendants(matching: .any)["guest-interest-continue"].exists)
        tapVisibleInterestTags(count: 1, in: app)

        let continueButton = app.descendants(matching: .any)["guest-interest-continue"]
        XCTAssertTrue(continueButton.waitForExistence(timeout: 5))
        continueButton.tap()

        XCTAssertTrue(app.buttons["guest-interest-select-interests"].waitForExistence(timeout: 5))
        XCTAssertTrue(app.buttons["welcome-chat-card-demo-for-everyone"].waitForExistence(timeout: 10))

        let codingSuggestion = app.buttons["new-chat-suggestion-card-chat.new_chat_suggestions.learn_coding"]
        XCTAssertTrue(codingSuggestion.waitForExistence(timeout: 10))

        let messageEditor = app.textFields["message-editor"]
        XCTAssertTrue(messageEditor.waitForExistence(timeout: 5))
        messageEditor.tap()
        messageEditor.typeText("coding")

        XCTAssertTrue(codingSuggestion.waitForExistence(timeout: 5))
        XCTAssertFalse(app.buttons["new-chat-suggestion-card-chat.new_chat_suggestions.cover_letter"].isHittable)
        XCTAssertFalse(app.tables.firstMatch.exists, "Product chat UI must not render default List/table chrome")

        attachScreenshot(name: "Guest interest tag selection filters suggestions")
    }

    private func tapVisibleInterestTags(count: Int, in app: XCUIApplication) {
        let tagContainer = app.scrollViews["guest-interest-rail"]
        XCTAssertTrue(tagContainer.waitForExistence(timeout: 5), "Expected guest interest tags")

        var tapped = 0
        var visited = Set<String>()
        let tagButtons = app.buttons.matching(NSPredicate(format: "identifier BEGINSWITH %@", "interest-tag-"))

        for _ in 0..<8 where tapped < count {
            for index in 0..<tagButtons.count where tapped < count {
                let tag = tagButtons.element(boundBy: index)
                let tagId = tag.identifier
                let check = app.descendants(matching: .any)["\(tagId)-check"]
                guard !visited.contains(tagId), !check.exists, tag.exists, tag.isHittable else { continue }
                visited.insert(tagId)
                tag.tap()
                XCTAssertTrue(check.waitForExistence(timeout: 5))
                tapped += 1
            }

            if tapped < count {
                tagContainer.swipeLeft()
            }
        }

        XCTAssertEqual(tapped, count, "Expected to select \(count) visible interest tags")
    }

    private func openWorkspace(_ workspace: String, in app: XCUIApplication) {
        let returnToChats = app.descendants(matching: .any)["workspace-placeholder-return-to-chats"]
        if returnToChats.exists && returnToChats.isHittable {
            returnToChats.tap()
            XCTAssertTrue(app.descendants(matching: .any)["guest-interest-tags"].waitForExistence(timeout: 5))
            if workspace == "chats" { return }
        }

        let testId = "\(workspace)-nav-link"
        let directEntry = app.descendants(matching: .any)[testId]
        if directEntry.exists && directEntry.isHittable {
            directEntry.tap()
            return
        }

        let switcher = app.descendants(matching: .any)["workspace-switcher"]
        XCTAssertTrue(switcher.waitForExistence(timeout: 5), "Expected workspace switcher")
        switcher.tap()

        let menuEntry = app.buttons[testId]
        XCTAssertTrue(menuEntry.waitForExistence(timeout: 5), "Expected native workspace menu entry \(testId)")
        menuEntry.tap()
    }

    private func attachScreenshot(name: String) {
        let attachment = XCTAttachment(screenshot: XCUIScreen.main.screenshot())
        attachment.name = name
        attachment.lifetime = .keepAlways
        add(attachment)
    }

}
