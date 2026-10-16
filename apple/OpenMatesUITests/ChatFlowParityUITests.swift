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
    private let focusedWebComposerMinHeight: CGFloat = 100
    private let focusedWebComposerMaxHeight: CGFloat = 140

    override func setUpWithError() throws {
        continueAfterFailure = false
    }

    // contract-test: direct surface=gui.apple assertions=chats.rendering.assistant-document-convergence,chats.rendering.inline-entity-interaction
    func testAssistantNestedMarkdownKeepsReferenceLabelsAndExplicitBreak() throws {
        let app = XCUIApplication()
        app.launchArguments = ["--dev-preview", "component", "--dev-preview-component", "message",
                               "--dev-preview-variant", "markdown-nested-emphasis", "--dev-preview-theme", "light",
                               "-AppleLanguages", "(en)", "-AppleLocale", "en_US"]
        app.launch()
        let fixture = app.descendants(matching: .any)["markdown-repair-fixture"].firstMatch
        XCTAssertTrue(fixture.waitForExistence(timeout: 10))
        let screenZen = app.buttons["ScreenZen"]
        XCTAssertTrue(screenZen.waitForExistence(timeout: 5))
        XCTAssertTrue(screenZen.isHittable)
        let opal = fixture.descendants(matching: .any).matching(NSPredicate(format: "label == %@ OR value == %@", "Opal (Best overall for strict focus)", "Opal (Best overall for strict focus)")).firstMatch
        XCTAssertTrue(opal.exists, "The actual heading block must parse emphasis rather than render raw header text")
        XCTAssertGreaterThanOrEqual(fixture.descendants(matching: .any).matching(NSPredicate(format: "label CONTAINS %@ OR value CONTAINS %@", "How...:", "How...:")).count, 2,
                                    "Recommendation headings must retain their following parsed bullet rows")
        XCTAssertEqual(fixture.descendants(matching: .any).matching(NSPredicate(format: "label CONTAINS %@ OR label CONTAINS %@", "embed:", "**")).count, 0,
                       "The assistant must render emphasis and references instead of raw Markdown destinations")
        let before = app.staticTexts["Before"]
        let events = app.buttons["Events"]
        XCTAssertTrue(before.exists)
        XCTAssertTrue(events.exists)
        XCTAssertGreaterThan(events.frame.minY, before.frame.minY + before.frame.height * 0.8,
                             "The explicit hard break must start the inline Events reference on the next line")
        XCTAssertEqual(events.frame.minX, before.frame.minX, accuracy: 2,
                       "Continuation indentation must not push the inline reference away from the paragraph edge")
        XCTAssertLessThan(events.frame.width, fixture.frame.width * 0.6,
                          "An inline reference must hug its icon and label, not stretch across the paragraph")
        let openedReference = app.staticTexts["markdown-repair-opened-reference"]
        XCTAssertTrue(openedReference.waitForExistence(timeout: 5))
        XCTAssertEqual(openedReference.label, "none")
        screenZen.tap()
        XCTAssertEqual(XCTWaiter.wait(for: [XCTNSPredicateExpectation(
            predicate: NSPredicate(format: "label == %@", "apps.apple.com-JJi"), object: openedReference)], timeout: 5), .completed)
        events.tap()
        XCTAssertEqual(XCTWaiter.wait(for: [XCTNSPredicateExpectation(
            predicate: NSPredicate(format: "label == %@", "events-JJi"), object: openedReference)], timeout: 5), .completed)
        attachScreenshot(name: "Assistant nested Markdown and explicit Events break")
    }

    // contract-test: supporting surface=gui.apple assertions=landing-onboarding.uses-real-chat-shell,workspace-shell.nav.released-surfaces-visible
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
        XCTAssertFalse(app.descendants(matching: .any)["plans-nav-link"].exists,
                       "The web header exposes Chat, Projects, Workflows and Tasks")
        openWorkspace("projects", in: app)
        XCTAssertTrue(app.descendants(matching: .any)["projects-home-greeting"].waitForExistence(timeout: 5))
        let switcher = app.descendants(matching: .any)["workspace-switcher"]
        XCTAssertTrue(switcher.isEnabled)
        XCTAssertEqual(switcher.label, "Projects")

        openWorkspace("tasks", in: app)
        XCTAssertTrue(app.descendants(matching: .any)["tasks-workspace"].waitForExistence(timeout: 5))

        openWorkspace("workflows", in: app)
        XCTAssertTrue(app.descendants(matching: .any)["workflows-home"].waitForExistence(timeout: 5))

        openWorkspace("chats", in: app)
        XCTAssertTrue(app.descendants(matching: .any)["guest-interest-tags"].waitForExistence(timeout: 5))
        XCTAssertFalse(app.tables.firstMatch.exists, "Product chat UI must not render default List/table chrome")

        attachScreenshot(name: "Unauthenticated new-chat parity surface")
    }

    // contract-test: supporting surface=gui.apple assertions=workspace-shell.nav.released-surfaces-visible
    func testWideWorkspaceTabsUseEntireHighlightedSegment() throws {
        #if os(iOS)
        guard UIDevice.current.userInterfaceIdiom == .pad else {
            throw XCTSkip("Desktop workspace segments require the iPad wide layout")
        }
        XCUIDevice.shared.orientation = .landscapeLeft
        defer { XCUIDevice.shared.orientation = .portrait }
        #endif
        let app = XCUIApplication()
        app.launchArguments = ["--ui-test-disable-auth-cache", "--ui-test-show-workspace-tabs"]
        app.launch()
        let ids = ["chats-nav-link", "projects-nav-link", "workflows-nav-link", "tasks-nav-link"]
        let switcher = app.descendants(matching: .any)["workspace-switcher"]
        XCTAssertTrue(switcher.waitForExistence(timeout: 10))
        XCTAssertEqual(switcher.frame.width, 288, accuracy: 1)
        XCTAssertFalse(app.descendants(matching: .any)["plans-nav-link"].exists)
        var previousMaxX: CGFloat?
        for id in ids {
            let tab = app.buttons[id]
            XCTAssertTrue(tab.exists)
            XCTAssertEqual(tab.frame.width, 72, accuracy: 1)
            XCTAssertEqual(tab.frame.height, 44.8, accuracy: 1)
            if let previousMaxX { XCTAssertEqual(tab.frame.minX, previousMaxX, accuracy: 1) }
            previousMaxX = tab.frame.maxX
        }
        for (id, destination) in [
            ("projects-nav-link", "projects-home-greeting"),
            ("workflows-nav-link", "workflows-home"),
            ("tasks-nav-link", "tasks-workspace"),
        ] {
            let tab = app.buttons[id]
            tab.coordinate(withNormalizedOffset: CGVector(dx: 0.9, dy: 0.15)).tap()
            XCTAssertTrue(app.descendants(matching: .any)[destination].waitForExistence(timeout: 5),
                          "The tab's padded corner must change workspaces")
            tab.coordinate(withNormalizedOffset: CGVector(dx: 0.1, dy: 0.85)).tap()
            XCTAssertTrue(app.descendants(matching: .any)[destination].exists,
                          "The highlighted tab's full segment must stay interactive")
        }
        attachScreenshot(name: "Wide header with four full workspace hit regions")
    }

    // contract-test: supporting surface=gui.apple assertions=chats.surface.semantic-parity
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
        XCTAssertTrue(headerContract.label.contains("chat-compact-header-icon=false"))
        XCTAssertFalse(app.descendants(matching: .any)["chat-header-icon"].exists)

        let userMessage = app.staticTexts
            .containing(NSPredicate(format: "label CONTAINS %@", "Seeded user message"))
            .firstMatch
        let assistantMessage = app.staticTexts
            .containing(NSPredicate(format: "label CONTAINS %@", "Seeded assistant message"))
            .firstMatch
        XCTAssertTrue(userMessage.waitForExistence(timeout: 5))
        XCTAssertTrue(assistantMessage.waitForExistence(timeout: 5))
        XCTAssertTrue(app.staticTexts["Latest assistant response visible after bounded open"].exists)
        XCTAssertTrue(app.descendants(matching: .any)["message-editor"].exists)
        XCTAssertFalse(app.tables.firstMatch.exists, "Product chat UI must not render default List/table chrome")

        attachScreenshot(name: "Seeded chat-flow parity hierarchy")
    }

    // contract-test: supporting surface=gui.apple assertions=issue-reporting.form.role-aware-controls
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

    // contract-test: supporting surface=gui.apple assertions=chats.layout.responsive-history
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

    // contract-test: supporting surface=gui.apple assertions=message-input.suggestions.contextual
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
        XCTAssertTrue(
            waitForAnyButton(
                ["welcome-chat-card-demo-for-everyone", "welcome-chat-compact-card-demo-for-everyone"],
                in: app,
                timeout: 10
            ),
            "Expected either the regular or compact demo-for-everyone card to exist"
        )

        let messageEditor = waitForMessageEditor(in: app)
        messageEditor.tap()
        app.typeText("coding")

        XCTAssertFalse(app.tables.firstMatch.exists, "Product chat UI must not render default List/table chrome")

        attachScreenshot(name: "Guest interest tag selection filters suggestions")
    }

    // contract-test: direct surface=gui.apple assertions=message-input.suggestions.contextual,message-input.layout.responsive-parity
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
        waitForFrameHeight(atLeast: focusedWebComposerMinHeight, element: messageField, timeout: 5)
        let focusedScreenshot = XCUIScreen.main.screenshot()
        attachScreenshot(focusedScreenshot, name: "Focused welcome message input visible")
        XCTAssertTrue(messageField.isHittable, "Focused welcome composer field should stay visible and hittable")
        assertElementIsVisibleInScreenshot(messageField, in: app, screenshot: focusedScreenshot)
        XCTAssertGreaterThanOrEqual(
            messageField.frame.height,
            focusedWebComposerMinHeight,
            "Focused welcome composer should expand to the web-like message-field height instead of collapsing/disappearing"
        )
        XCTAssertLessThanOrEqual(
            messageField.frame.height,
            focusedWebComposerMaxHeight,
            "Focused welcome composer must match the web bottom composer height instead of stretching into a full-screen panel"
        )
        messageEditor.typeText("a")
        waitForFrameHeight(atLeast: focusedWebComposerMinHeight, element: messageField, timeout: 5)
        XCTAssertLessThanOrEqual(
            messageField.frame.height,
            focusedWebComposerMaxHeight,
            "Typing the first character must not remove the web composer's height cap"
        )
        let keyboard = app.keyboards.firstMatch
        if keyboard.exists {
            XCTAssertLessThanOrEqual(
                messageField.frame.maxY,
                keyboard.frame.minY - 2,
                "Focused welcome composer field must render above the software keyboard"
            )
        }

        let attachmentToggle = app.buttons["composer-attachment-toggle"]
        XCTAssertTrue(attachmentToggle.exists)
        attachmentToggle.tap()
        XCTAssertTrue(app.buttons["composer-attachment-drawing"].exists)
        XCTAssertTrue(app.buttons["composer-attachment-camera"].exists)
        XCTAssertTrue(app.buttons["new-chat-suggestion-card-chat.new_chat_suggestions.discover_web_search"].waitForExistence(timeout: 10))
        XCTAssertTrue(app.buttons["new-chat-suggestion-card-chat.new_chat_suggestions.discover_image_generate"].exists)
        XCTAssertFalse(app.tables.firstMatch.exists, "Product chat UI must not render default List/table chrome")

        attachScreenshot(name: "Guest default suggestions before interest selection")
    }

    // contract-test: direct surface=gui.apple assertions=message-input.layout.responsive-parity
    func testGuestComposerKeepsHeightCapAfterFirstCharacter() throws {
        let app = XCUIApplication()
        app.launchArguments = [
            "--ui-test-disable-auth-cache",
            "--ui-test-start-new-chat",
        ]
        app.launch()

        XCTAssertTrue(app.descendants(matching: .any)["guest-interest-tags"].waitForExistence(timeout: 15))
        let messageEditor = waitForMessageEditor(in: app)
        messageEditor.tap()

        let messageField = app.descendants(matching: .any)["message-field"]
        XCTAssertTrue(messageField.waitForExistence(timeout: 5))
        waitForFrameHeight(atLeast: focusedWebComposerMinHeight, element: messageField, timeout: 5)
        XCTAssertLessThanOrEqual(messageField.frame.height, focusedWebComposerMaxHeight)

        messageEditor.tap()
        messageEditor.typeText("a")

        XCTAssertLessThanOrEqual(
            messageField.frame.height,
            focusedWebComposerMaxHeight,
            "Typing the first character must not remove the web composer's height cap"
        )
    }

    // contract-test: supporting surface=gui.apple assertions=landing-onboarding.uses-real-chat-shell
    func testWelcomeRecentOverflowUsesLargeHeightOnTallPhone() throws {
        let app = XCUIApplication()
        app.launchArguments = [
            "--ui-test-disable-auth-cache",
            "--ui-test-start-new-chat",
            "--ui-test-welcome-recent-overflow"
        ]
        app.launch()

        let carousel = app.scrollViews["welcome-chat-cards-carousel"]
        XCTAssertTrue(carousel.waitForExistence(timeout: 15))

        let largeCard = app.buttons["welcome-chat-card-ui-test-welcome-recent-0"]
        XCTAssertTrue(largeCard.waitForExistence(timeout: 5))

        let overflow = app.descendants(matching: .any)["welcome-chat-overflow-large"]
        for _ in 0..<12 where !overflow.isHittable {
            carousel.swipeLeft()
        }

        XCTAssertTrue(overflow.waitForExistence(timeout: 5))
        XCTAssertTrue(overflow.isHittable, "Expected large overflow counter to be reachable in the recent-chat carousel")
        XCTAssertEqual(
            overflow.frame.height,
            largeCard.frame.height,
            accuracy: 1,
            "Tall phones should use the full continuation-card height throughout the carousel"
        )

        attachScreenshot(name: "Welcome tall-phone large continuation cards")
    }

    // contract-test: supporting surface=gui.apple assertions=landing-onboarding.uses-real-chat-shell
    func testWelcomeLargeRecentCardOnTallPhoneOpensActionsOnLongPress() throws {
        let app = XCUIApplication()
        app.launchArguments = [
            "--ui-test-disable-auth-cache",
            "--ui-test-start-new-chat",
            "--ui-test-welcome-recent-overflow"
        ]
        app.launch()

        let largeCard = app.buttons["welcome-chat-card-ui-test-welcome-recent-0"]
        XCTAssertTrue(largeCard.waitForExistence(timeout: 15))
        XCTAssertGreaterThanOrEqual(largeCard.frame.height, 190)

        largeCard.press(forDuration: 0.8)

        XCTAssertTrue(
            app.descendants(matching: .any)["chat-actions-menu"].waitForExistence(timeout: 5),
            "Long-pressing a recent-chat preview must open the custom chat actions"
        )
    }

    // contract-test: direct surface=gui.apple assertions=message-input.drafts.preview-persistence
    func testTextDraftBlursIntoCompactPreviewWithoutLosingContent() throws {
        let app = XCUIApplication()
        app.launchArguments = ["--ui-test-disable-auth-cache", "--ui-test-start-new-chat"]
        app.launch()

        let editor = waitForMessageEditor(in: app)
        editor.tap()
        editor.typeText("Keep this draft")
        XCTAssertTrue(app.keyboards.firstMatch.waitForExistence(timeout: 5))

        app.coordinate(withNormalizedOffset: CGVector(dx: 0.5, dy: 0.25)).tap()

        XCTAssertFalse(app.keyboards.firstMatch.waitForExistence(timeout: 2))
        XCTAssertEqual(editor.value as? String, "Keep this draft")
        let messageField = app.descendants(matching: .any)["message-field"]
        XCTAssertLessThanOrEqual(
            messageField.frame.height,
            64,
            "A blurred text-only draft must return to the compact web preview height"
        )
        XCTAssertFalse(
            app.descendants(matching: .any)["action-buttons"].exists,
            "Draft preview mode hides CTA and attachment actions until the field is focused again"
        )
    }

    // contract-test: supporting surface=gui.apple assertions=chats.surface.semantic-parity,chat-navigation.open.local-first-coherent
    func testEncryptedWelcomeGridHydratesPagesSearchAndDelayedKeysWithoutDiscardingMetadata() throws {
        let app = XCUIApplication()
        app.launchArguments = ["--ui-test-authenticated-chat-navigation", "--ui-test-encrypted-welcome-grid", "--ui-test-nav-callback-diagnostics",
            "--ui-test-fresh-new-chat", "-AppleLanguages", "(en)"]
        app.launch()
        let receipt = app.staticTexts["welcome-grid-fixture-metadata"]
        XCTAssertTrue(receipt.waitForExistence(timeout: 15))
        let seeded = XCTNSPredicateExpectation(predicate: NSPredicate { _, _ in
            receipt.exists && receipt.label.contains("records=65;preserved=true")
        }, object: nil)
        XCTAssertEqual(XCTWaiter.wait(for: [seeded], timeout: 15), .completed)
        XCTAssertFalse(receipt.label.contains("ui-test-grid-45"), "An older page should remain encrypted until requested")
        let showAll = app.buttons["welcome-show-all-chats"]
        XCTAssertTrue(showAll.waitForExistence(timeout: 10))
        XCTAssertTrue(showAll.isHittable)
        let interactions = app.staticTexts["welcome-grid-interaction-metrics"]
        let interactionBeforeTap = interactions.exists ? interactions.label : "missing"
        showAll.tap()
        let grid = app.descendants(matching: .any)["welcome-chat-grid"].firstMatch
        let gridAppeared = grid.waitForExistence(timeout: 5)
        if !gridAppeared {
            let diagnostic = XCTAttachment(string: "Before Show all: " + interactionBeforeTap + "\n" + app.debugDescription)
            diagnostic.name = "Encrypted welcome Show all callback and hierarchy"
            diagnostic.lifetime = .keepAlways
            add(diagnostic)
            attachScreenshot(name: "Encrypted welcome Show all transition failure")
        }
        XCTAssertTrue(gridAppeared)
        let back = app.buttons["welcome-back-to-recent"]
        XCTAssertTrue(back.isHittable)
        XCTAssertEqual(back.frame.midX, grid.frame.midX, accuracy: 2, "Back to recent should be centered")
        func waitForHydration(_ index: Int) {
            let ready = XCTNSPredicateExpectation(predicate: NSPredicate { _, _ in
                receipt.exists && receipt.label.components(separatedBy: ";").first?.dropFirst("hydrated=".count)
                    .split(separator: ",").contains(Substring("ui-test-grid-\(index)")) == true
                    && receipt.label.contains("records=65;preserved=true")
            }, object: nil)
            XCTAssertEqual(XCTWaiter.wait(for: [ready], timeout: 10), .completed,
                "Production grid demand and key-arrival retry must hydrate title, category, icon and summary")
        }
        waitForHydration(25)
        XCTAssertFalse(receipt.label.contains("ui-test-grid-45"))
        let scroll = app.scrollViews["welcome-chat-grid-list"]
        let more = app.buttons["welcome-browse-load-more"]
        for _ in 0..<35 where !more.isHittable { scroll.swipeUp() }
        XCTAssertTrue(more.isHittable)
        more.tap()
        waitForHydration(45)
        XCTAssertFalse(receipt.label.contains("ui-test-grid-64"))
        let search = app.textFields["welcome-browse-search"]
        XCTAssertTrue(search.isHittable)
        search.tap()
        search.typeText("Encrypted Grid Chat 64")
        waitForHydration(64)
        let result = app.buttons["welcome-chat-card-ui-test-grid-64"]
        let titled = XCTNSPredicateExpectation(predicate: NSPredicate { _, _ in
            result.exists && result.label.contains("Encrypted Grid Chat 64")
                && result.label.contains("Preserved grid summary 64")
        }, object: nil)
        XCTAssertEqual(XCTWaiter.wait(for: [titled], timeout: 10), .completed)
        search.typeText("\n")
        for _ in 0..<5 where !result.isHittable { scroll.swipeDown() }
        XCTAssertTrue(result.isHittable)
        attachScreenshot(name: "Encrypted older welcome grid card after delayed key and search")
        result.tap()
        let navigation = app.descendants(matching: .any)["chat-navigation-order-metrics"].firstMatch
        let opened = XCTNSPredicateExpectation(predicate: NSPredicate { _, _ in
            navigation.exists && navigation.label.contains("selected-chat-id=ui-test-grid-64;")
                && navigation.label.contains("show-new-chat=false")
        }, object: nil)
        let routeResult = XCTWaiter.wait(for: [opened], timeout: 10)
        attachScreenshot(name: "Encrypted grid card production route after tap")
        let routeHierarchy = XCTAttachment(string: navigation.label + "\n" + app.debugDescription)
        routeHierarchy.name = "Encrypted grid card post-tap route and hierarchy"
        routeHierarchy.lifetime = .keepAlways
        add(routeHierarchy)
        XCTAssertEqual(routeResult, .completed,
            "Opening a saved grid card must select its production chat route")
        let question = app.descendants(matching: .any).matching(NSPredicate(
            format: "identifier == %@ AND label CONTAINS %@", "message-user", "Synthetic saved grid question ui-test-grid-64"
        )).firstMatch
        XCTAssertTrue(question.waitForExistence(timeout: 10))
        let header = app.staticTexts["chat-header-title"]
        XCTAssertTrue(header.waitForExistence(timeout: 10))
        XCTAssertEqual(header.label, "Encrypted Grid Chat 64")
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

    private func waitForAnyButton(_ identifiers: [String], in app: XCUIApplication, timeout: TimeInterval) -> Bool {
        let deadline = Date().addingTimeInterval(timeout)
        while Date() < deadline {
            if identifiers.contains(where: { app.buttons[$0].exists }) {
                return true
            }
            RunLoop.current.run(until: Date().addingTimeInterval(0.1))
        }
        return identifiers.contains(where: { app.buttons[$0].exists })
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
