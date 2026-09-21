import XCTest
#if os(iOS)
import UIKit
#endif

@MainActor
final class HistoryWelcomeComponentUITests: XCTestCase {
    override func setUpWithError() throws { continueAfterFailure = false }
    // contract-test: supporting surface=gui.apple assertions=chats.surface.semantic-parity
    func testContinuationUsesProductionFilteringAndDraftCard() {
        let app = launch("welcome")
        let ids = app.staticTexts["dev-welcome-eligible-ids"]
        XCTAssertTrue(ids.waitForExistence(timeout: 5))
        XCTAssertEqual(ids.label, "fixture-resume,fixture-pinned,fixture-draft")
        XCTAssertFalse(app.staticTexts["New Chat"].exists)
        let resume = app.descendants(matching: .any).matching(NSPredicate(format: "identifier IN %@", ["welcome-chat-card-fixture-resume", "welcome-chat-compact-card-fixture-resume"])).firstMatch
        resume.tap()
        XCTAssertTrue(app.staticTexts["Continue the research"].firstMatch.exists)
        let carousel = app.scrollViews["welcome-chat-cards-carousel"]
        carousel.swipeLeft(); carousel.swipeLeft()
        let draft = app.descendants(matching: .any)["welcome-draft-card-fixture-draft"].firstMatch
        XCTAssertTrue(draft.waitForExistence(timeout: 3)); draft.tap()
        XCTAssertTrue((app.descendants(matching: .any)["dev-preview-local-action"].firstMatch.label).contains("open:fixture-draft"))
    }
    // contract-test: supporting surface=gui.apple assertions=chats.surface.semantic-parity
    func testRealHistoryWindowPagesAndReflowsWithoutAccount() {
        let app = launch("history")
        let transcript = app.descendants(matching: .any)["chat-history-content"].firstMatch
        XCTAssertTrue(transcript.waitForExistence(timeout: 5))
        let initial = transcript.value as? String ?? ""
        XCTAssertTrue(initial.contains("total=160")); XCTAssertTrue(initial.contains("rendered=50"))
        let scroll = app.scrollViews["chat-history-container"].firstMatch
        for _ in 0..<12 {
            if (transcript.value as? String ?? "") != initial { break }
            scroll.swipeDown()
        }
        XCTAssertNotEqual(transcript.value as? String, initial, "Actual older navigation must replace the bounded window")
        XCTAssertTrue((transcript.value as? String ?? "").contains("rendered=50"))
        for _ in 0..<12 { scroll.swipeUp() }
        XCTAssertTrue((transcript.value as? String ?? "").contains("rendered=50"))
        #if os(iOS)
        XCUIDevice.shared.orientation = .landscapeLeft
        XCTAssertTrue(transcript.exists)
        XCUIDevice.shared.orientation = .portrait
        #endif
        // Native link action is inherited from the isolated host's OpenURLAction.
        var visibleLink: XCUIElement?
        for _ in 0..<8 {
            visibleLink = app.buttons.matching(identifier: "a citation").allElementsBoundByIndex.first { $0.isHittable }
            if visibleLink != nil { break }
            scroll.swipeDown()
        }
        guard let link = visibleLink else {
            XCTFail("Citation must remain interactive after paging/reflow"); return
        }
        link.tap()
        XCTAssertEqual(app.descendants(matching: .any)["dev-preview-local-action"].firstMatch.label, "external-link-intercepted")
        // Citation paragraphs use InlineMarkdownFlowLayout: appendText emits a
        // separate Text element for every whitespace-terminated word. The full
        // rendered sentence is intentionally not one AX StaticText element.
        let words = app.staticTexts.matching(NSPredicate(format: "label MATCHES %@", #"^\s*paragraph\s*$"#))
        var paragraphWord: XCUIElement?
        for _ in 0..<6 {
            let viewport = scroll.frame.intersection(app.windows.firstMatch.frame).insetBy(dx: 12, dy: 12)
            paragraphWord = words.allElementsBoundByIndex.reversed().first { word in
                guard word.exists else { return false }
                let frame = word.frame
                return !frame.isEmpty && viewport.contains(frame) && word.isHittable
            }
            if paragraphWord != nil { break }
            scroll.swipeDown()
        }
        guard let word = paragraphWord else {
            let hierarchy = XCTAttachment(string: app.debugDescription)
            hierarchy.name = "History long-press accessibility hierarchy"
            hierarchy.lifetime = .keepAlways
            add(hierarchy)
            XCTFail("A fully visible rendered paragraph word is missing"); return
        }
        word.press(forDuration: 0.8)
        let copy = app.buttons["message-action-copy"].firstMatch
        XCTAssertTrue(copy.waitForExistence(timeout: 3), "Long press must open the real production message menu")
        copy.tap()
        let menuDismissed = XCTNSPredicateExpectation(predicate: NSPredicate(format: "exists == false"), object: copy)
        XCTAssertEqual(XCTWaiter.wait(for: [menuDismissed], timeout: 3), .completed,
                       "The real Copy message action must run and dismiss the menu")

    }
    // contract-test: supporting surface=gui.apple assertions=chats.surface.semantic-parity
    func testSidebarUsesFullWidthWrappedProductionRowsAndSelectionSurvivesCollapse() {
        let app = launchSidebar("account")
        let panel = app.otherElements["chat-history-panel"]
        XCTAssertTrue(panel.waitForExistence(timeout: 5))
        XCTAssertEqual(panel.frame.width, 390, accuracy: 1)
        let top = app.otherElements["chat-sidebar-topbar"]
        XCTAssertEqual(top.frame.height, 65, accuracy: 1)
        let more = app.buttons["load-more-chats"]
        XCTAssertTrue(more.waitForExistence(timeout: 5)); more.tap()
        let longRow = app.descendants(matching: .any).matching(NSPredicate(format:
            "identifier == 'chat-item-wrapper' AND value == %@", "user-chat:sidebar-long")).firstMatch
        XCTAssertTrue(longRow.waitForExistence(timeout: 5))
        let scroll = app.scrollViews["chat-sidebar-scroll"]
        for _ in 0..<4 { if longRow.isHittable { break }; scroll.swipeUp() }
        XCTAssertEqual(longRow.frame.width, 390, accuracy: 1)
        XCTAssertGreaterThan(longRow.frame.height, 66, "The actual title must wrap across multiple lines, not truncate to a single row")
        let attachment = XCTAttachment(screenshot: app.screenshot())
        attachment.name = "sidebar-account-wrapped-row"; attachment.lifetime = .keepAlways; add(attachment)
        // The trailing blank area belongs to the same production row hit target.
        longRow.coordinate(withNormalizedOffset: CGVector(dx: 0.96, dy: 0.5)).tap()
        let selectedID = app.staticTexts["sidebar-fixture-selected-id"]
        XCTAssertTrue(selectedID.waitForExistence(timeout: 5)); XCTAssertEqual(selectedID.label, "sidebar-long")
        XCTAssertTrue(app.staticTexts["sidebar-fixture-selected-content"].label.contains("telescope lenses"))
        XCTAssertFalse(panel.exists)
        app.buttons["sidebar-fixture-reopen"].tap()
        XCTAssertTrue(panel.waitForExistence(timeout: 5))
        let selected = app.descendants(matching: .any).matching(NSPredicate(format:
            "identifier == 'chat-item-wrapper' AND value == %@", "user-chat:sidebar-long")).firstMatch
        XCTAssertTrue(selected.exists)
        app.buttons["chat-sidebar-close"].tap()
        XCTAssertTrue(selectedID.waitForExistence(timeout: 5)); XCTAssertEqual(selectedID.label, "sidebar-long")
    }

    // contract-test: supporting surface=gui.apple assertions=chats.surface.semantic-parity
    func testSidebarSearchUsesActualInMemoryEngineAndOpensMatchingConversation() {
        let app = launchSidebar("account")
        let openSearch = app.buttons["search-button"]
        XCTAssertTrue(openSearch.waitForExistence(timeout: 5)); openSearch.tap()
        let input = app.textFields["search-input"]
        XCTAssertTrue(input.waitForExistence(timeout: 5)); input.typeText("telescope\n")
        let result = app.buttons.matching(identifier: "search-chat-item").matching(NSPredicate(format: "label == %@", "Telescope research")).firstMatch
        XCTAssertTrue(result.waitForExistence(timeout: 5))
        XCTAssertTrue(app.buttons.matching(identifier: "search-message-snippet").firstMatch.exists,
            "The same production engine must find message text from the detached store")
        result.tap()
        let selectedID = app.staticTexts["sidebar-fixture-selected-id"]
        XCTAssertTrue(selectedID.waitForExistence(timeout: 5)); XCTAssertEqual(selectedID.label, "sidebar-pinned")
        XCTAssertTrue(app.staticTexts["sidebar-fixture-selected-content"].label.contains("telescope lenses"))
        app.buttons["sidebar-fixture-reopen"].tap()
        XCTAssertTrue(app.buttons["search-button"].waitForExistence(timeout: 5))
        XCTAssertFalse(input.exists, "Selection closes the actual search state before reopening the sidebar")
    }

    // contract-test: supporting surface=gui.apple assertions=chats.surface.semantic-parity
    func testSidebarSearchClearAndCloseRestoreListAndHiddenActionDoesNotFakeUnlock() {
        let app = launchSidebar("guest")
        app.buttons["search-button"].tap()
        let input = app.textFields["search-input"]
        XCTAssertTrue(input.waitForExistence(timeout: 5)); input.typeText("no-matching-guest-fixture\n")
        XCTAssertTrue(app.staticTexts["search-no-results"].waitForExistence(timeout: 5))
        app.buttons["search-close-button"].tap()
        XCTAssertTrue(app.otherElements["chat-history-panel"].waitForExistence(timeout: 5))
        XCTAssertFalse(input.exists)
        let intro = app.staticTexts["chat-sidebar-section-intro"]
        XCTAssertTrue(intro.exists)
        app.buttons["chat-sidebar-show-hidden"].tap()
        XCTAssertTrue(app.staticTexts["sidebar-fixture-hidden-boundary"].waitForExistence(timeout: 5))
        app.buttons["sidebar-fixture-hidden-return"].tap()
        XCTAssertFalse(app.staticTexts["sidebar-fixture-hidden-boundary"].exists)
        XCTAssertTrue(app.buttons["chat-sidebar-show-hidden"].exists)
    }

    // Same visible-row expansion contract as web show-more-chats-flow.spec.ts;
    // use the real production button, rows and selected transcript fixture.
    // contract-test: supporting surface=gui.apple assertions=chats.surface.semantic-parity
    func testSidebarDateGroupsAndShowMoreRevealTheNextTwentyPersonalChats() {
        let app = launchSidebar("dated")
        XCTAssertTrue(app.staticTexts["chat-sidebar-section-today"].waitForExistence(timeout: 5))
        XCTAssertFalse(app.staticTexts["chat-sidebar-section-pinned"].exists,
                       "Pins keep their sort priority but use the same web date sections")
        let scroll = app.scrollViews["chat-sidebar-scroll"]
        let more = app.buttons["load-more-chats"]
        for _ in 0..<8 { if more.isHittable { break }; scroll.swipeUp() }
        XCTAssertTrue(more.isHittable); more.tap()
        let row = sidebarRow("sidebar-dated-30", app: app)
        for _ in 0..<10 { if row.isHittable { break }; scroll.swipeUp() }
        XCTAssertTrue(row.isHittable, "The first expansion exposes the actual 31st personal row")
        XCTAssertTrue(app.staticTexts["chat-sidebar-section-month_2026_8"].exists)
        row.tap()
        XCTAssertEqual(app.staticTexts["sidebar-fixture-selected-id"].label, "sidebar-dated-30")
        XCTAssertTrue(app.staticTexts["sidebar-fixture-selected-content"].label.contains("telescope lenses"))
    }

    // contract-test: supporting surface=gui.apple assertions=chats.surface.semantic-parity
    func testSidebarKeepsSearchSelectedOldChatWhenReturningToNewChat() {
        let app = launchSidebar("dated")
        app.buttons["search-button"].tap()
        let input = app.textFields["search-input"]
        XCTAssertTrue(input.waitForExistence(timeout: 5)); input.typeText("Historic\n")
        let result = app.buttons.matching(identifier: "search-chat-item")
            .matching(NSPredicate(format: "label == %@", "Historic telescope archive")).firstMatch
        XCTAssertTrue(result.waitForExistence(timeout: 5)); result.tap()
        let selected = app.staticTexts["sidebar-fixture-selected-id"]
        XCTAssertTrue(selected.waitForExistence(timeout: 5)); XCTAssertEqual(selected.label, "sidebar-dated-34")
        app.buttons["sidebar-fixture-new-chat"].tap()
        XCTAssertFalse(selected.exists)
        let retained = sidebarRow("sidebar-dated-34", app: app)
        let scroll = app.scrollViews["chat-sidebar-scroll"]
        for _ in 0..<8 { if retained.isHittable { break }; scroll.swipeUp() }
        XCTAssertTrue(retained.isHittable, "The old search selection remains a real mounted row outside the recent window")
        XCTAssertTrue(app.staticTexts["chat-sidebar-section-month_2026_7"].exists)
        let screenshot = XCTAttachment(screenshot: app.screenshot())
        screenshot.name = "sidebar-retained-old-chat-date-section"; screenshot.lifetime = .keepAlways; add(screenshot)
        retained.tap()
        XCTAssertTrue(selected.waitForExistence(timeout: 5)); XCTAssertEqual(selected.label, "sidebar-dated-34")
        XCTAssertTrue(app.staticTexts["sidebar-fixture-selected-content"].label.contains("telescope lenses"))
    }

    private func sidebarRow(_ id: String, app: XCUIApplication) -> XCUIElement {
        app.descendants(matching: .any).matching(NSPredicate(format:
            "identifier == 'chat-item-wrapper' AND value == %@", "user-chat:\(id)")).firstMatch
    }

    private func launchSidebar(_ variant: String) -> XCUIApplication {
        let app = XCUIApplication()
        app.launchArguments = ["--dev-preview", "sidebar", "--dev-preview-variant", variant,
            "--dev-preview-width", "390", "--dev-preview-height", "844", "--ui-test-expose-chat-ids",
            "-AppleLanguages", "(en)", "-AppleLocale", "en_US"]
        app.launch()
        let root = app.descendants(matching: .any)["dev-preview-root"].firstMatch
        XCTAssertTrue(root.waitForExistence(timeout: 10))
        XCTAssertEqual(root.value as? String, "auth=not-started;store=detached;socket=disconnected")
        return app
    }

    // contract-test: supporting surface=gui.apple assertions=chats.surface.semantic-parity
    func testWorkspaceKeepsActualEmbedRouteAcrossReflow() throws {
        #if os(iOS)
        guard UIDevice.current.userInterfaceIdiom == .pad else { throw XCTSkip("Split workspace acceptance runs on iPad") }
        let previousOrientation = XCUIDevice.shared.orientation
        XCUIDevice.shared.orientation = .landscapeLeft
        defer { XCUIDevice.shared.orientation = previousOrientation }
        #endif
        let app = launch("history", variant: "workspace")
        #if os(iOS)
        // Launch may restore the app's prior orientation. Establish the actual
        // mounted split viewport after launch, rather than assuming the request stuck.
        XCUIDevice.shared.orientation = .landscapeLeft
        #endif
        let workspace = app.descendants(matching: .any)["chat-embed-workspace"].firstMatch
        let landscapeReady = XCTNSPredicateExpectation(predicate: NSPredicate { _, _ in
            workspace.exists && workspace.frame.width >= 1024
        }, object: nil)
        XCTAssertEqual(XCTWaiter.wait(for: [landscapeReady], timeout: 8), .completed,
            "Workspace acceptance requires the actual wide mounted viewport")
        let card = app.buttons["embed-preview"].firstMatch
        let scroll = app.scrollViews["chat-history-container"].firstMatch
        let anchor = app.staticTexts.matching(NSPredicate(format: "label CONTAINS %@", "Workspace result reference")).firstMatch
        func targetIsFullyVisible() -> Bool {
            guard card.exists, anchor.exists else { return false }
            let viewport = scroll.frame.intersection(app.windows.firstMatch.frame).insetBy(dx: 4, dy: 12)
            return card.isHittable && anchor.isHittable
                && viewport.contains(card.frame) && viewport.contains(anchor.frame)
        }
        // A sliver of a card at the lower edge is hittable, but cannot be the
        // scroll-restoration baseline. Capture its actual adjacent paragraph too.
        for _ in 0..<8 {
            if targetIsFullyVisible() { break }
            scroll.swipeUp()
        }
        guard targetIsFullyVisible() else {
            let hierarchy = XCTAttachment(string: app.debugDescription)
            hierarchy.name = "Workspace anchor accessibility hierarchy"; hierarchy.lifetime = .keepAlways; add(hierarchy)
            let screenshot = XCTAttachment(screenshot: app.screenshot())
            screenshot.name = "Workspace anchor viewport"; screenshot.lifetime = .keepAlways; add(screenshot)
            XCTFail("The complete embed card and exact transcript anchor must both be visible before opening")
            return
        }
        let history = app.descendants(matching: .any)["chat-history-content"].firstMatch
        let historyWindowBefore = history.value as? String
        XCTAssertNotNil(historyWindowBefore)
        XCTAssertTrue(historyWindowBefore?.contains("total=8") == true,
                      "The pane fixture stays small; the separate160-row fixture covers long history")
        XCTAssertTrue(historyWindowBefore?.contains("rendered=8") == true)
        card.tap()
        let pane = app.descendants(matching: .any)["workspace-transcript"].firstMatch
        let embedPane = app.descendants(matching: .any)["workspace-embed"].firstMatch
        XCTAssertTrue(embedPane.waitForExistence(timeout: 5))
        let settledSplit = XCTNSPredicateExpectation(predicate: NSPredicate { _, _ in
            abs(pane.frame.width - 400) <= 2 && abs(embedPane.frame.minX - pane.frame.maxX - 10) <= 2
        }, object: nil)
        XCTAssertEqual(XCTWaiter.wait(for: [settledSplit], timeout: 5), .completed)
        XCTAssertEqual(pane.frame.width, 400, accuracy: 2)
        XCTAssertEqual(embedPane.frame.minX - pane.frame.maxX, 10, accuracy: 2)
        XCTAssertEqual(embedPane.frame.width, workspace.frame.width - 410, accuracy: 2)
        let child = app.buttons["embed-preview-preview-web-search-result-1"].firstMatch
        XCTAssertTrue(child.waitForExistence(timeout: 5))
        if !child.isHittable { app.swipeUp() }
        child.tap()
        let title = app.staticTexts["Top 10 Restaurants in Berlin - Local Guide"].firstMatch
        XCTAssertTrue(title.waitForExistence(timeout: 5))
        let hideChat = app.buttons["workspace-hide-chat"]
        XCTAssertTrue(hideChat.isHittable, "iPad landscape must expose real split hide control")
        hideChat.tap()
        let restore = app.buttons["embed-show-chat-button"]
        XCTAssertTrue(restore.waitForExistence(timeout: 3))
        restore.tap()
        XCTAssertTrue(hideChat.waitForExistence(timeout: 3))

        app.buttons["Toggle sidebar"].tap()
        app.buttons["Toggle sidebar"].tap()
        XCTAssertTrue(title.waitForExistence(timeout: 3), "Sidebar must preserve the selected result route")
        app.buttons["Toggle settings"].tap()
        // The row label and actual custom toggle share the inherited wrapper ID.
        // Select the real Switch, preserving the production interaction.
        let learning = app.switches["learning-mode-toggle-wrapper"].firstMatch
        XCTAssertTrue(learning.waitForExistence(timeout: 3))
        learning.tap()
        let learningPage = app.scrollViews["settings-learning-mode-page"]
        XCTAssertTrue(learningPage.waitForExistence(timeout: 3))
        app.buttons["learning-mode-enable-button"].tap()
        XCTAssertTrue(app.buttons["learning-mode-disable-button"].waitForExistence(timeout: 3),
                      "Actual production settings controls mutate only their owned guest fixture session")
        for width in ["730pt", "390pt", "Available width"] {
            app.buttons[width].tap()
            XCTAssertTrue(learningPage.waitForExistence(timeout: 3), "Actual settings destination must survive reflow")
            XCTAssertTrue(app.buttons["learning-mode-disable-button"].exists, "Owned local learning state must also survive reflow")
        }
        app.buttons["390pt"].tap()
        app.buttons["Toggle sidebar"].tap()
        let sidebarClose = app.buttons["chat-sidebar-close"]
        let settingsPane = app.descendants(matching: .any)["workspace-settings"].firstMatch
        let learningDisable = app.buttons["learning-mode-disable-button"]
        let sidebarPanel = app.descendants(matching: .any)["chat-history-panel"].firstMatch
        func settingsIsInactive(outside visibleBounds: CGRect) -> Bool {
            // XCUI retains native nodes from the mounted hidden subtree. Their
            // existence is not visibility: require both disabled real actions
            // and zero overlap with the actual constrained workspace viewport.
            (!settingsPane.exists || (!settingsPane.isEnabled && !settingsPane.frame.intersects(visibleBounds)))
                && (!learningDisable.exists || (!learningDisable.isEnabled && !learningDisable.frame.intersects(visibleBounds)))
        }
        let phoneSidebarSettled = XCTNSPredicateExpectation(predicate: NSPredicate { _, _ in
            sidebarClose.exists && sidebarClose.isHittable && sidebarPanel.exists
                && abs(sidebarPanel.frame.width - 390) <= 1 && settingsIsInactive(outside: sidebarPanel.frame)
        }, object: nil)
        guard XCTWaiter.wait(for: [phoneSidebarSettled], timeout: 3) == .completed else {
            let hierarchy = XCTAttachment(string: app.debugDescription)
            hierarchy.name = "Phone sidebar settings accessibility"; hierarchy.lifetime = .keepAlways; add(hierarchy)
            let screenshot = XCTAttachment(screenshot: app.screenshot())
            screenshot.name = "Phone sidebar settings settled viewport"; screenshot.lifetime = .keepAlways; add(screenshot)
            XCTFail("Phone sidebar must be interactive while retained settings actions are disabled and outside its visible bounds")
            return
        }
        let phoneVisibleBounds = sidebarPanel.frame
        // Use the actual product close control rather than the fixture toggle.
        sidebarClose.tap()
        let phoneWorkspaceSettled = XCTNSPredicateExpectation(predicate: NSPredicate { _, _ in
            (!sidebarClose.exists || !sidebarClose.isHittable) && settingsIsInactive(outside: phoneVisibleBounds)
        }, object: nil)
        XCTAssertEqual(XCTWaiter.wait(for: [phoneWorkspaceSettled], timeout: 3), .completed,
                       "Closing sidebar must not reopen settings")
        app.buttons["Toggle settings"].tap()
        let settingsRestored = XCTNSPredicateExpectation(predicate: NSPredicate { _, _ in
            learningDisable.exists && learningDisable.isEnabled && learningDisable.isHittable
                && phoneVisibleBounds.intersects(learningDisable.frame)
        }, object: nil)
        XCTAssertEqual(XCTWaiter.wait(for: [settingsRestored], timeout: 3), .completed,
                       "Reopening restores the existing settings destination, enabled state and actual visible action")
        learningDisable.tap()
        XCTAssertTrue(app.buttons["learning-mode-enable-button"].waitForExistence(timeout: 3),
                      "Restored settings controls remain functional after their ancestor was hidden")
        app.buttons["Toggle settings"].tap()
        app.buttons["Available width"].tap()
        XCTAssertTrue(title.waitForExistence(timeout: 3), "Actual selected child must survive settings and reflow")
        app.buttons["embed-minimize"].firstMatch.tap()
        XCTAssertTrue(child.waitForExistence(timeout: 3), "Close child restores parent route")
        app.buttons["embed-minimize"].firstMatch.tap()
        XCTAssertTrue(scroll.waitForExistence(timeout: 3), "Close parent restores the same mounted transcript")
        XCTAssertEqual(history.value as? String, historyWindowBefore, "No history page replacement on pane transitions")
        XCTAssertTrue(anchor.isHittable, "The original visible transcript anchor must remain visible")
    }

    private func launch(_ component: String, variant: String = "default") -> XCUIApplication {
        let app = XCUIApplication()
        app.launchArguments = ["--dev-preview", component, "--ui-test-history-window-metrics", "-AppleLanguages", "(en)", "-AppleLocale", "en_US"]
        app.launchArguments += ["--dev-preview-variant", variant]
        app.launch()
        let root = app.descendants(matching: .any)["dev-preview-root"].firstMatch
        XCTAssertTrue(root.waitForExistence(timeout: 10))
        XCTAssertEqual(root.value as? String, "auth=not-started;store=detached;socket=disconnected")
        return app
    }
}
