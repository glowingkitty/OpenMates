// Share-extension attachment smoke and real Safari article coverage.
// Uses the Quick Capture debug preview with a seeded pending attachment because
// the share extension and menu bar capture intentionally delegate to the same
// background attachment sender. This verifies the visible status/composer shape
// needed before exercising real extension-host automation.

import XCTest

@MainActor
final class ShareExtensionAttachmentParityUITests: XCTestCase {
    override func setUpWithError() throws {
        continueAfterFailure = false
    }

    func testSharedBackgroundAttachmentSurfaceShowsSendableSeededAttachment() throws {
        let app = XCUIApplication()
        app.launchArguments = [
            "--dev-preview",
            "quick-capture",
            "--ui-test-seed-quick-capture-recent-chat",
            "--ui-test-seed-quick-capture-attachment"
        ]
        app.launchEnvironment["DEV_PREVIEW"] = "quick-capture"
        app.launch()

        XCTAssertTrue(
            element(in: app, identifier: "quick-capture-tab-chats").waitForExistence(timeout: 12),
            "Expected Quick Capture preview to launch for shared attachment smoke coverage. Visible UI: \(app.debugDescription)"
        )
        XCTAssertTrue(element(in: app, identifier: "quick-capture-pending-attachments").exists)
        XCTAssertTrue(app.staticTexts["Shared fixture.pdf"].exists)
        XCTAssertTrue(element(in: app, identifier: "quick-capture-status-list").exists)
        XCTAssertTrue(element(in: app, identifier: "quick-capture-composer").exists)
        XCTAssertTrue(element(in: app, identifier: "message-field").exists)
        XCTAssertTrue(sendButton(in: app).isEnabled)
    }

    // This live test requires real AI inference and runs on the dev simulator.
    // It deliberately traverses Safari's OS share sheet and the installed
    // extension, so the Quick Capture fixture cannot satisfy its assertions.
    // contract-test: supporting surface=gui.apple assertions=sync.surface.semantic-parity,chats.persistence.client-encrypted,chats.surface.semantic-parity
    func testSafariArticleShareLoadsRealDestinationsAndSummarizesInNewChat() throws {
        #if os(iOS)
        let articleURL = RealAccountTestCredentials.configurationValue(for: "OPENMATES_TEST_SHARE_ARTICLE_URL")
            ?? "https://www.apple.com/newsroom/2024/06/introducing-apple-intelligence-for-iphone-ipad-and-mac/"
        let article = try XCTUnwrap(URL(string: articleURL))
        XCTAssertEqual(article.scheme, "https")
        let articleSearch = RealAccountTestCredentials.configurationValue(for: "OPENMATES_TEST_SHARE_ARTICLE_SEARCH")
            ?? "Apple Intelligence"
        let marker = "Safari share proof \(UUID().uuidString.prefix(8))"
        let instruction = "Summarize this article in three short bullet points, including its privacy approach. Start your answer with: \(marker)."
        RealAccountUITestSupport.installNotificationPermissionHandler(on: self)
        let reuseAuth = RealAccountTestCredentials.configurationValue(for: "OPENMATES_TEST_REUSE_AUTH") == "1"
        let app = RealAccountUITestSupport.launchApp(disableAuthCache: !reuseAuth,
            extraArguments: reuseAuth ? [] : ["--ui-test-open-login"])
        if !reuseAuth {
            RealAccountUITestSupport.logIn(app: app, credentials: try RealAccountTestCredentials.fromEnvironment())
        }
        let synchronized = app.descendants(matching: .any).matching(NSPredicate(
            format: "identifier == %@ AND value == %@", "chat-sync-complete", "true")).firstMatch
        XCTAssertTrue(synchronized.waitForExistence(timeout: 45), "Authenticated app must finish real account synchronization")

        let safari = XCUIApplication(bundleIdentifier: "com.apple.mobilesafari")
        // Reopen the host process so a previous extension or edited address
        // cannot leave Safari's capsule in a transition. Its compact title
        // and actual editor have distinct, observed identifiers.
        safari.launch()
        let editableAddress = safari.textFields["URL"]
        if !editableAddress.waitForExistence(timeout: 2) {
            let address = safari.textFields["TabBarItemTitle"]
            XCTAssertTrue(address.waitForExistence(timeout: 10), "Safari compact address control must be available")
            address.tap()
        }
        XCTAssertTrue(editableAddress.waitForExistence(timeout: 10), "Safari must expand its actual URL editor")
        editableAddress.tap()
        let clearAddress = safari.buttons["ClearTextButton"]
        if clearAddress.exists { clearAddress.tap() }
        editableAddress.tap()
        editableAddress.typeText(articleURL + "\n")
        XCTAssertTrue(safari.webViews.firstMatch.waitForExistence(timeout: 30), "Public article must load in Safari")
        let share = safari.buttons["Share"].firstMatch
        if !share.exists {
            let pageMenu = safari.buttons.matching(NSPredicate(
                format: "label == 'More' OR label == 'Page Menu' OR identifier == 'MoreButton'")).firstMatch
            XCTAssertTrue(pageMenu.waitForExistence(timeout: 5), "Safari must expose its page actions")
            pageMenu.tap()
        }
        XCTAssertTrue(share.waitForExistence(timeout: 5))
        share.tap()
        var openMates = safari.buttons["OpenMates"].firstMatch
        if !openMates.waitForExistence(timeout: 3) {
            let more = safari.buttons.matching(NSPredicate(format: "label == 'More' OR label == 'More…' OR label == 'More...'")).firstMatch
            XCTAssertTrue(more.waitForExistence(timeout: 5), "Share sheet must expose additional activities")
            more.tap()
            openMates = safari.descendants(matching: .any).matching(NSPredicate(format: "label == 'OpenMates'")).firstMatch
        }
        XCTAssertTrue(openMates.waitForExistence(timeout: 5), "Installed OpenMates share extension must be offered")
        openMates.tap()

        let root = element(in: safari, identifier: "share-extension-root")
        XCTAssertTrue(root.waitForExistence(timeout: 15), "Real share extension must be hosted by Safari")
        let editor = safari.textViews["share-extension-message-input"]
        XCTAssertTrue(editor.waitForExistence(timeout: 10))
        XCTAssertTrue((editor.value as? String ?? "").contains(articleURL), "Safari must pass the public article URL without losing its path")
        let status = element(in: safari, identifier: "share-extension-status")
        let ready = NSPredicate { _, _ in
            ["New Chat is ready.", "Choose a recent chat or keep New Chat selected."].contains(status.label)
        }
        XCTAssertEqual(XCTWaiter.wait(for: [XCTNSPredicateExpectation(predicate: ready, object: status)], timeout: 35), .completed,
                       "Real recent-chat load must complete successfully; a timeout or auth error cannot pass")
        XCTAssertFalse(element(in: safari, identifier: "share-extension-retry-recent-chats").exists,
                       "A successful load must hide its recovery control")
        let destinations = safari.descendants(matching: .any).matching(identifier: "share-extension-chat-destination")
        XCTAssertGreaterThan(destinations.count, 0, "Authenticated account must expose genuine recent destinations")
        XCTAssertFalse(destinations.allElementsBoundByIndex.allSatisfy { $0.label == "Untitled chat" },
                       "Recent chat titles must decrypt in the extension")
        let newChat = element(in: safari, identifier: "share-extension-new-chat")
        XCTAssertTrue(newChat.isHittable)
        newChat.tap()
        // Edit through UIKit's real selection menu. A normalized tap in this
        // fixed-height, scrolling field can place the caret inside a wrapped
        // URL, so explicitly replace the selected content with the verified
        // Safari payload plus the user's instruction.
        editor.tap()
        editor.press(forDuration: 1.1)
        let menuSelectAll = safari.menuItems["Select All"]
        let selectAll = menuSelectAll.exists ? menuSelectAll : safari.buttons["Select All"]
        XCTAssertTrue(selectAll.waitForExistence(timeout: 5), "Share editor must expose native text selection")
        selectAll.tap()
        editor.typeText(articleURL + "\n\n" + instruction)
        let content = editor.value as? String ?? ""
        XCTAssertTrue(content.contains(articleURL), "Adding an instruction must preserve the complete article URL")
        XCTAssertTrue(content.contains(instruction))
        let send = element(in: safari, identifier: "share-extension-send")
        XCTAssertTrue(send.isEnabled && send.isHittable)
        send.tap()
        let sendFinished = NSPredicate { _, _ in
            !root.exists || (send.isEnabled && status.label != "Sending...")
        }
        XCTAssertEqual(XCTWaiter.wait(for: [XCTNSPredicateExpectation(predicate: sendFinished, object: root)], timeout: 50), .completed,
                       "Share sending must finish or show a visible failure within its deadline")
        XCTAssertFalse(root.exists,
                       "Share extension must finish only after the encrypted user message is stored; status: \(root.exists ? status.label : "dismissed")")

        // Use ordinary startup for the persistence check. The first launch's
        // fresh-login flags intentionally bypass the saved session on every
        // launch and cannot establish real restart recovery.
        app.launchArguments.removeAll {
            ["--ui-test-disable-auth-cache", "--ui-test-open-login"].contains($0)
        }
        app.terminate()
        app.launch()
        XCTAssertTrue(synchronized.waitForExistence(timeout: 45))
        let sidebar = app.buttons["sidebar-toggle"]
        let history = element(in: app, identifier: "chat-history-panel")
        if !history.exists || !history.isHittable { sidebar.tap() }
        XCTAssertTrue(history.waitForExistence(timeout: 10))
        // Existing drafts can legitimately rank ahead of a freshly shared
        // chat. Search its article metadata rather than assuming it is among
        // the first six bounded sidebar rows. The unique sent-message marker
        // still identifies this exact turn after opening a candidate.
        func openArticleSearch() {
            let input = app.textFields["search-input"]
            if !input.isHittable {
                if !history.isHittable { sidebar.tap() }
                let search = app.buttons["search-button"]
                XCTAssertTrue(search.waitForExistence(timeout: 5))
                search.tap()
                XCTAssertTrue(input.waitForExistence(timeout: 5))
                input.tap()
                input.typeText(articleSearch)
            }
        }
        openArticleSearch()
        let rows = app.buttons.matching(identifier: "search-chat-item")
        XCTAssertTrue(rows.firstMatch.waitForExistence(timeout: 30), "Article search must finish and expose real synchronized chats")
        let candidateCount = rows.count
        var foundSharedChat = false
        for index in 0..<candidateCount {
            if index > 0 { openArticleSearch() }
            let row = rows.element(boundBy: index)
            if !row.isHittable {
                let results = element(in: app, identifier: "search-results")
                for _ in 0..<4 where !row.isHittable { results.swipeUp() }
            }
            guard row.isHittable else { continue }
            row.tap()
            let sentMessage = app.descendants(matching: .any).matching(NSPredicate(
                format: "identifier == %@ AND label CONTAINS %@", "message-user", marker)).firstMatch
            if sentMessage.waitForExistence(timeout: 5) {
                XCTAssertTrue(sentMessage.label.contains(articleURL), "Saved encrypted message must decrypt with the original URL")
                foundSharedChat = true
                break
            }
        }
        XCTAssertTrue(foundSharedChat, "New shared chat must appear through the real authenticated synchronization path")
        let summary = app.descendants(matching: .any).matching(NSPredicate(
            format: "identifier == %@ AND label CONTAINS %@", "message-assistant", marker)).firstMatch
        XCTAssertTrue(summary.waitForExistence(timeout: 120), "The public article must produce a real assistant summary")
        let completed = element(in: app, identifier: "assistant-response-feedback")
        XCTAssertTrue(completed.waitForExistence(timeout: 120))
        XCTAssertGreaterThan(summary.label.count, marker.count + 80, "Summary must contain substantive article content")
        XCTAssertTrue(summary.label.localizedCaseInsensitiveContains("privacy"), "Summary must address the requested article topic")
        #else
        throw XCTSkip("Safari share-sheet verification runs on iOS Simulator")
        #endif
    }

    private func element(in app: XCUIApplication, identifier: String) -> XCUIElement {
        app.descendants(matching: .any)
            .matching(NSPredicate(format: "identifier == %@", identifier))
            .firstMatch
    }

    private func sendButton(in app: XCUIApplication) -> XCUIElement {
        let identified = element(in: app, identifier: "quick-capture-send-button")
        return identified.exists ? identified : app.buttons["Send"].firstMatch
    }
}
