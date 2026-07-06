// UI parity smoke coverage for the native chat-flow surface.
// Uses the debug-only seeded chat preview so assertions are deterministic and
// do not require credentials, private chat records, network access, or AI calls.
// The deterministic parity audit covers token/source mappings; this simulator
// test verifies the visible native hierarchy exposes the expected chat elements.

import XCTest
#if canImport(UIKit)
import UIKit
#endif

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
        XCTAssertTrue(app.descendants(matching: .any)["daily-inspiration-carousel-progress"].waitForExistence(timeout: 15))
        XCTAssertTrue(app.descendants(matching: .any)["guest-interest-tags"].waitForExistence(timeout: 15))
        XCTAssertTrue(app.staticTexts["What are your interests?"].exists)
        XCTAssertFalse(app.staticTexts["common.skip"].exists)

        let tagRail = app.scrollViews["guest-interest-rail"]
        XCTAssertTrue(tagRail.waitForExistence(timeout: 5))
        let appWidth = app.windows.firstMatch.frame.width
        XCTAssertGreaterThanOrEqual(
            tagRail.frame.width,
            appWidth * 0.85,
            "Guest interest rail should span the available welcome surface instead of using a narrow centered cap"
        )

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

        let reportButtonById = app.descendants(matching: .any)["chat-floating-action-bug"]
        let reportButtonByLabel = app.buttons["Report Issue"]
        XCTAssertTrue(
            reportButtonById.waitForExistence(timeout: 12) || reportButtonByLabel.waitForExistence(timeout: 2)
        )
        XCTAssertFalse(app.staticTexts["common.report"].exists)

        let reportButton = reportButtonById.exists ? reportButtonById : reportButtonByLabel
        reportButton.tap()

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

        let messageEditor = waitForMessageEditor(in: app)
        messageEditor.tap()
        app.typeText("coding")

        XCTAssertTrue(codingSuggestion.waitForExistence(timeout: 5))
        XCTAssertFalse(app.buttons["new-chat-suggestion-card-chat.new_chat_suggestions.cover_letter"].isHittable)
        XCTAssertFalse(app.tables.firstMatch.exists, "Product chat UI must not render default List/table chrome")

        attachScreenshot(name: "Guest interest tag selection filters suggestions")
    }

    func testGuestDefaultSuggestionsShowWhenComposerFocusedBeforeInterestSelection() throws {
        let app = XCUIApplication()
        app.launchArguments = ["--ui-test-disable-auth-cache", "--ui-test-start-new-chat"]
        app.launch()

        XCTAssertTrue(app.descendants(matching: .any)["guest-interest-tags"].waitForExistence(timeout: 15))
        XCTAssertFalse(app.buttons["new-chat-suggestion-card-chat.new_chat_suggestions.discover_web_search"].exists)

        let messageEditor = waitForMessageEditor(in: app)
        messageEditor.tap()

        XCTAssertTrue(app.buttons["message-input-fullscreen-button"].waitForExistence(timeout: 5))

        let messageField = app.descendants(matching: .any)["message-field"]
        XCTAssertTrue(messageField.waitForExistence(timeout: 5))
        waitForFrameHeight(atLeast: 90, element: messageField, timeout: 5)
        let focusedScreenshot = XCUIScreen.main.screenshot()
        attachScreenshot(focusedScreenshot, name: "Focused welcome message input visible")
        XCTAssertTrue(messageField.isHittable, "Focused welcome composer field should stay visible and hittable")
        assertElementIsVisibleInScreenshot(messageField, in: app, screenshot: focusedScreenshot)
        XCTAssertGreaterThanOrEqual(
            messageField.frame.height,
            90,
            "Focused welcome composer should expand to the web-like message-field height instead of collapsing/disappearing"
        )
        let keyboard = app.keyboards.firstMatch
        if keyboard.exists {
            XCTAssertLessThanOrEqual(
                messageField.frame.maxY,
                keyboard.frame.minY - 2,
                "Focused welcome composer field must render above the software keyboard"
            )
        }

        XCTAssertTrue(app.buttons["sketch-button"].exists)
        XCTAssertTrue(app.buttons["take-photo-button"].exists)
        XCTAssertTrue(app.buttons["new-chat-suggestion-card-chat.new_chat_suggestions.discover_web_search"].waitForExistence(timeout: 10))
        XCTAssertTrue(app.buttons["new-chat-suggestion-card-chat.new_chat_suggestions.discover_image_generate"].exists)
        XCTAssertFalse(app.tables.firstMatch.exists, "Product chat UI must not render default List/table chrome")

        attachScreenshot(name: "Guest default suggestions before interest selection")
    }

    func testWelcomeRecentOverflowUsesCompactHeightOnPhone() throws {
        let app = XCUIApplication()
        app.launchArguments = [
            "--ui-test-disable-auth-cache",
            "--ui-test-start-new-chat",
            "--ui-test-welcome-recent-overflow"
        ]
        app.launch()

        let carousel = app.scrollViews["welcome-chat-cards-carousel"]
        XCTAssertTrue(carousel.waitForExistence(timeout: 15))

        let compactCard = app.buttons["welcome-chat-compact-card-ui-test-welcome-recent-0"]
        XCTAssertTrue(compactCard.waitForExistence(timeout: 5))

        let overflow = app.descendants(matching: .any)["welcome-chat-overflow-compact"]
        for _ in 0..<12 where !overflow.isHittable {
            carousel.swipeLeft()
        }

        XCTAssertTrue(overflow.waitForExistence(timeout: 5))
        XCTAssertTrue(overflow.isHittable, "Expected compact overflow counter to be reachable in the recent-chat carousel")
        XCTAssertLessThanOrEqual(
            overflow.frame.height,
            50,
            "Compact overflow counter should match the web compact 44px treatment instead of using large-card height"
        )
        XCTAssertLessThanOrEqual(
            overflow.frame.height,
            compactCard.frame.height + 1,
            "Compact overflow counter must not be taller than compact recent cards"
        )

        attachScreenshot(name: "Welcome compact recent overflow height")
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

    private func waitForMessageEditor(in app: XCUIApplication) -> XCUIElement {
        let candidates = [
            app.textFields.matching(identifier: "message-editor").firstMatch,
            app.textViews.matching(identifier: "message-editor").firstMatch,
            app.descendants(matching: .any)["message-editor"],
            app.descendants(matching: .any)["message-field"],
            app.descendants(matching: .any)["message-composer"],
        ]

        for candidate in candidates where candidate.waitForExistence(timeout: 5) {
            return candidate
        }

        XCTFail("Expected message composer input to exist as an editor or composer wrapper")
        return candidates[0]
    }

    private func waitForFrameHeight(atLeast minimumHeight: CGFloat, element: XCUIElement, timeout: TimeInterval) {
        let deadline = Date().addingTimeInterval(timeout)
        while element.exists && element.frame.height < minimumHeight && Date() < deadline {
            RunLoop.current.run(until: Date().addingTimeInterval(0.1))
        }
    }

    private func assertElementIsVisibleInScreenshot(
        _ element: XCUIElement,
        in app: XCUIApplication,
        screenshot: XCUIScreenshot,
        file: StaticString = #filePath,
        line: UInt = #line
    ) {
        let windowFrame = app.windows.firstMatch.frame
        let visibleFrame = element.frame.intersection(windowFrame)
        XCTAssertGreaterThan(visibleFrame.width, 40, "Message input should have visible width", file: file, line: line)
        XCTAssertGreaterThan(visibleFrame.height, 40, "Message input should have visible height", file: file, line: line)

        #if canImport(UIKit)
        guard let image = UIImage(data: screenshot.pngRepresentation), let cgImage = image.cgImage else {
            XCTFail("Could not decode focused message input screenshot", file: file, line: line)
            return
        }

        let imageWidth = cgImage.width
        let imageHeight = cgImage.height
        var pixels = [UInt8](repeating: 0, count: imageWidth * imageHeight * 4)
        guard let context = CGContext(
            data: &pixels,
            width: imageWidth,
            height: imageHeight,
            bitsPerComponent: 8,
            bytesPerRow: imageWidth * 4,
            space: CGColorSpaceCreateDeviceRGB(),
            bitmapInfo: CGImageAlphaInfo.premultipliedLast.rawValue
        ) else {
            XCTFail("Could not prepare focused message input screenshot pixels", file: file, line: line)
            return
        }
        context.translateBy(x: 0, y: CGFloat(imageHeight))
        context.scaleBy(x: 1, y: -1)
        context.draw(cgImage, in: CGRect(x: 0, y: 0, width: imageWidth, height: imageHeight))

        let scaleX = CGFloat(imageWidth) / windowFrame.width
        let scaleY = CGFloat(imageHeight) / windowFrame.height
        let fieldSampleFrame = visibleFrame.insetBy(dx: 4, dy: 4)
        let comparisonFrame = comparisonSampleFrame(for: visibleFrame, in: windowFrame)
        let fieldAverage = averageRGB(in: fieldSampleFrame, pixels: pixels, imageWidth: imageWidth, imageHeight: imageHeight, scaleX: scaleX, scaleY: scaleY)
        let surroundingAverage = averageRGB(in: comparisonFrame, pixels: pixels, imageWidth: imageWidth, imageHeight: imageHeight, scaleX: scaleX, scaleY: scaleY)
        let delta = colorDistance(fieldAverage, surroundingAverage)
        XCTAssertGreaterThan(
            delta,
            6,
            "Focused message input must be visually distinguishable in the screenshot (delta: \(delta))",
            file: file,
            line: line
        )
        #endif
    }

    private func comparisonSampleFrame(for elementFrame: CGRect, in windowFrame: CGRect) -> CGRect {
        let sampleHeight: CGFloat = 24
        if elementFrame.minY - sampleHeight - 8 > windowFrame.minY {
            return CGRect(
                x: elementFrame.minX + elementFrame.width * 0.2,
                y: elementFrame.minY - sampleHeight - 8,
                width: elementFrame.width * 0.6,
                height: sampleHeight
            )
        }
        return CGRect(
            x: elementFrame.minX + elementFrame.width * 0.2,
            y: min(windowFrame.maxY - sampleHeight, elementFrame.maxY + 8),
            width: elementFrame.width * 0.6,
            height: sampleHeight
        )
    }

    private func averageRGB(
        in rect: CGRect,
        pixels: [UInt8],
        imageWidth: Int,
        imageHeight: Int,
        scaleX: CGFloat,
        scaleY: CGFloat
    ) -> (Double, Double, Double) {
        var totalR = 0.0
        var totalG = 0.0
        var totalB = 0.0
        var count = 0.0

        for row in 0..<5 {
            for column in 0..<5 {
                let xPoint = rect.minX + rect.width * (CGFloat(column) + 0.5) / 5
                let yPoint = rect.minY + rect.height * (CGFloat(row) + 0.5) / 5
                let x = min(max(Int(xPoint * scaleX), 0), imageWidth - 1)
                let y = min(max(Int(yPoint * scaleY), 0), imageHeight - 1)
                let index = (y * imageWidth + x) * 4
                totalR += Double(pixels[index])
                totalG += Double(pixels[index + 1])
                totalB += Double(pixels[index + 2])
                count += 1
            }
        }

        return (totalR / count, totalG / count, totalB / count)
    }

    private func colorDistance(_ lhs: (Double, Double, Double), _ rhs: (Double, Double, Double)) -> Double {
        let red = lhs.0 - rhs.0
        let green = lhs.1 - rhs.1
        let blue = lhs.2 - rhs.2
        return sqrt(red * red + green * green + blue * blue)
    }

    private func attachScreenshot(name: String) {
        attachScreenshot(XCUIScreen.main.screenshot(), name: name)
    }

    private func attachScreenshot(_ screenshot: XCUIScreenshot, name: String) {
        let attachment = XCTAttachment(screenshot: screenshot)
        attachment.name = name
        attachment.lifetime = .keepAlways
        add(attachment)
    }

}
