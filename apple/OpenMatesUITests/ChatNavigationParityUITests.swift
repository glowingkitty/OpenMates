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
        #if os(iOS)
        XCUIDevice.shared.orientation = .portrait
        #endif
    }

    // contract-test: direct surface=gui.apple assertions=apple-notifications.delivery.idempotent-visible,workspace-shell.nav.released-surfaces-visible,chat-navigation.open.local-first-coherent
    func testWorkspaceNavigationImmediatelyClearsActiveChatAndRestoresHeader() throws {
        let app = XCUIApplication()
        app.launchArguments = ["--ui-test-authenticated-chat-navigation", "--ui-test-workspace-sidebar-fixture", "--ui-test-nav-callback-diagnostics"]
        app.launch()
        // Authentication and encrypted fixture seeding precede navigation.
        // Wait for their rendered ready state before starting the five-second
        // active-chat transition checks below.
        let metricsQuery = app.descendants(matching: .any).matching(identifier: "chat-navigation-order-metrics")
            .matching(NSPredicate(format: "label CONTAINS %@ AND label CONTAINS %@",
                "selected-chat-id=ui-test-current-chat", "active-chat-id=ui-test-current-chat"))
        _ = try NativeUITestElementResolution.requireVisible(
            metricsQuery, in: app, timeout: 60, actionable: false)
        let metrics = app.descendants(matching: .any).matching(identifier: "chat-navigation-order-metrics").firstMatch
        _ = try waitForMetric("active-chat-id", equals: "ui-test-current-chat", in: metrics)
        try assertHeaderTitle("Current Chat", in: app)
        func select(_ id: String) throws {
            let query = app.buttons.matching(identifier: id)
            if NativeUITestElementResolution.visible(query, in: app) == nil {
                if let picker = NativeUITestElementResolution.visible(app.buttons.matching(identifier: "workspace-switcher"), in: app) {
                    let beforeScreen = XCTAttachment(screenshot: app.screenshot())
                    let beforeAX = XCTAttachment(string: app.debugDescription)
                    picker.tap()
                    let expanded = XCTNSPredicateExpectation(predicate: NSPredicate { _, _ in
                        picker.exists && picker.value as? String == "expanded"
                    }, object: picker)
                    let result = XCTWaiter.wait(for: [expanded], timeout: 5)
                    if result != .completed {
                        beforeScreen.name = "workspace-picker-before-tap-screen"
                        beforeAX.name = "workspace-picker-before-tap-AX"
                        beforeScreen.lifetime = .keepAlways; beforeAX.lifetime = .keepAlways
                        add(beforeScreen); add(beforeAX)
                        let afterScreen = XCTAttachment(screenshot: app.screenshot())
                        let afterAX = XCTAttachment(string: app.debugDescription)
                        afterScreen.name = "workspace-picker-after-tap-screen"
                        afterAX.name = "workspace-picker-after-tap-AX"
                        afterScreen.lifetime = .keepAlways; afterAX.lifetime = .keepAlways
                        add(afterScreen); add(afterAX)
                    }
                    let diagnostic = app.descendants(matching: .any)["workspace-picker-debug-state"].firstMatch
                    XCTAssertEqual(result, .completed,
                        "Actual picker tap must expand before resolving its workspace row. " + (diagnostic.exists ? diagnostic.label : "diagnostic missing"))
                } else {
                    try NativeUITestElementResolution.requireVisible(app.buttons.matching(identifier: "sidebar-toggle"), in: app).tap()
                }
            }
            try NativeUITestElementResolution.requireVisible(query, in: app).tap()
        }
        try select("tasks-nav-link")
        XCTAssertTrue(app.descendants(matching: .any)["tasks-workspace"].waitForExistence(timeout: 5))
        // Five seconds is below the old 25-second heartbeat, so a passing
        // result proves navigation itself relinquished active-chat visibility.
        _ = try waitForMetric("active-chat-id", equals: "none", in: metrics)
        _ = try waitForMetric("selected-chat-id", equals: "ui-test-current-chat", in: metrics)
        try select("chats-nav-link")
        _ = try waitForMetric("active-chat-id", equals: "ui-test-current-chat", in: metrics)
        try assertHeaderTitle("Current Chat", in: app)
        let header = try NativeUITestElementResolution.requireVisible(
            app.staticTexts.matching(identifier: "chat-header-title"), in: app, actionable: false)
        XCTAssertEqual(header.label, "Current Chat")
        let screenshot = XCTAttachment(screenshot: app.screenshot())
        screenshot.name = "Workspace return retains current chat header and visibility owner"
        screenshot.lifetime = .keepAlways
        add(screenshot)
    }

    // contract-test: direct surface=gui.apple assertions=workspace-shell.nav.released-surfaces-visible
    func testCompactWorkspaceMenuOpensAboveRealChatAndNavigates() throws {
        let app = XCUIApplication()
        app.launchArguments = ["--ui-test-authenticated-chat-navigation", "--ui-test-workspace-sidebar-fixture"]
        app.launch()
        try assertHeaderTitle("Current Chat", in: app)
        let picker = app.buttons["workspace-switcher"]
        guard picker.waitForExistence(timeout: 5) else { throw XCTSkip("Compact header required") }
        picker.tap()
        let tasks = app.buttons["tasks-nav-link"]
        XCTAssertTrue(tasks.waitForExistence(timeout: 5))
        XCTAssertTrue(tasks.isHittable, "The real chat shell must not clip or cover menu options")
        XCTAssertGreaterThan(tasks.frame.minY, picker.frame.maxY)
        let shot = XCTAttachment(screenshot: app.screenshot())
        shot.name = "Workspace dropdown above real chat"; shot.lifetime = .keepAlways; add(shot)
        tasks.tap()
        XCTAssertTrue(app.descendants(matching: .any)["tasks-workspace"].waitForExistence(timeout: 8))
        XCTAssertFalse(app.buttons["workspace-switcher"].value as? String == "expanded")
    }

    // contract-test: supporting surface=gui.apple assertions=message-input.drafts.preview-persistence,message-input.embeds.gated-send,drafts.draft-only.presentation
    func testImageAndAudioDraftRestoreSurvivesSaveTypingAndReopenWithoutHeader() throws {
        let app = XCUIApplication()
        app.launchArguments = ["--ui-test-authenticated-chat-navigation", "--ui-test-nav-draft-attachments", "--ui-test-nav-callback-diagnostics"]
        app.launch()
        try assertHeaderTitle("Current Chat", in: app)
        let navigation = app.staticTexts.containing(NSPredicate(format: "label CONTAINS %@", "chat-navigation-order=")).firstMatch
        XCTAssertTrue(navigation.waitForExistence(timeout: 12))
        let ready = XCTNSPredicateExpectation(predicate: NSPredicate { _, _ in
            guard navigation.exists else { return false }
            return navigation.label.contains("chat-navigation-order=ui-test-draft-chat,ui-test-newer-chat,ui-test-current-chat,ui-test-older-chat")
                && navigation.label.contains("selected-chat-id=ui-test-current-chat")
        }, object: nil)
        XCTAssertEqual(XCTWaiter.wait(for: [ready], timeout: 12), .completed)
        let next = try NativeUITestElementResolution.requireVisible(app.buttons.matching(identifier: "chat-header-next"), in: app)
        next.tap()
        XCTAssertEqual(try waitForMetric("selected-chat-id", equals: "ui-test-newer-chat", in: navigation), "ui-test-newer-chat")
        try assertHeaderTitle("Newer Chat", in: app)
        try NativeUITestElementResolution.requireVisible(app.buttons.matching(identifier: "chat-header-next"), in: app).tap()
        XCTAssertEqual(try waitForMetric("selected-chat-id", equals: "ui-test-draft-chat", in: navigation), "ui-test-draft-chat")
        let probe = app.staticTexts["composer-draft-attachment-probe"]
        XCTAssertTrue(probe.waitForExistence(timeout: 10))
        func fields() -> [String: String] {
            Dictionary(probe.label.split(separator: ";").compactMap { item in
                let pair = item.split(separator: "=", maxSplits: 1)
                return pair.count == 2 ? (String(pair[0]), String(pair[1])) : nil
            }, uniquingKeysWith: { _, last in last })
        }
        func assertHydrated() {
            let ready = XCTNSPredicateExpectation(predicate: NSPredicate { _, _ in
                let value = fields()
                return value["nodes"] == "2" && value["resolved"] == "2" && value["cached"] == "2"
            }, object: nil)
            XCTAssertEqual(XCTWaiter.wait(for: [ready], timeout: 10), .completed)
            XCTAssertFalse(app.staticTexts["chat-header-title"].exists)
            XCTAssertFalse(app.descendants(matching: .any)["chat-header-banner"].exists)
            let atoms = app.descendants(matching: .any).matching(NSPredicate(format:
                "identifier BEGINSWITH %@", "native-composer-embed-"))
            XCTAssertGreaterThanOrEqual(atoms.count, 2, "Both image and audio must remain inline preview atoms")
        }
        assertHydrated()
        let input = app.textViews["message-editor"].firstMatch
        guard RealAccountUITestSupport.focusForTextEntry(input, in: app, identifier: "message-editor") else { return }
        input.typeText(" Later synthetic draft text")
        let saved = XCTNSPredicateExpectation(predicate: NSPredicate { _, _ in
            let value = fields()
            return value["saved"] == value["revision"] && value["saved"] != "-1"
        }, object: nil)
        XCTAssertEqual(XCTWaiter.wait(for: [saved], timeout: 10), .completed)
        assertHydrated()
        app.terminate(); app.launch()
        // The deterministic navigation fixture starts on Current Chat every launch.
        // Reopen the saved draft through the production route before checking its ciphertext.
        try assertHeaderTitle("Current Chat", in: app)
        XCTAssertTrue(navigation.waitForExistence(timeout: 12))
        XCTAssertEqual(try waitForMetric("selected-chat-id", equals: "ui-test-current-chat", in: navigation), "ui-test-current-chat")
        let beforeTapScreenshot = XCTAttachment(screenshot: app.screenshot())
        let beforeTapHierarchy = XCTAttachment(string: navigation.label + "\n" + app.debugDescription)
        try NativeUITestElementResolution.requireVisible(app.buttons.matching(identifier: "chat-header-next"), in: app).tap()
        XCTAssertEqual(try waitForMetric("selected-chat-id", equals: "ui-test-newer-chat", in: navigation,
            onTimeout: {
                beforeTapScreenshot.name = "synthetic-relaunch-next-before-screen"
                beforeTapScreenshot.lifetime = .keepAlways; self.add(beforeTapScreenshot)
                beforeTapHierarchy.name = "synthetic-relaunch-next-before-AX"
                beforeTapHierarchy.lifetime = .keepAlways; self.add(beforeTapHierarchy)
                let afterScreenshot = XCTAttachment(screenshot: app.screenshot())
                afterScreenshot.name = "synthetic-relaunch-next-after-screen"
                afterScreenshot.lifetime = .keepAlways; self.add(afterScreenshot)
                let afterHierarchy = XCTAttachment(string: navigation.label + "\n" + app.debugDescription)
                afterHierarchy.name = "synthetic-relaunch-next-after-AX"
                afterHierarchy.lifetime = .keepAlways; self.add(afterHierarchy)
            }), "ui-test-newer-chat")
        try assertHeaderTitle("Newer Chat", in: app)
        try NativeUITestElementResolution.requireVisible(app.buttons.matching(identifier: "chat-header-next"), in: app).tap()
        XCTAssertEqual(try waitForMetric("selected-chat-id", equals: "ui-test-draft-chat", in: navigation), "ui-test-draft-chat")
        XCTAssertTrue(probe.waitForExistence(timeout: 12))
        assertHydrated()
        XCTAssertTrue((app.textViews["message-editor"].firstMatch.value as? String)?.contains("Later synthetic draft text") == true,
            "Relaunch must restore later text from the saved encrypted attachment draft")
    }

    // contract-test: direct surface=gui.apple assertions=chat-navigation.draft-only.addressable,chat-navigation.order.sidebar-header-match,chat-navigation.empty-new-chat.excluded
    func testHeaderNavigationFollowsSidebarOrderIncludingDraftOnlyChat() throws {
        let app = XCUIApplication()
        app.launchArguments = ["--ui-test-authenticated-chat-navigation", "--ui-test-shell-metrics"]
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
        let shell = app.descendants(matching: .any).matching(identifier: "shell-responsive-metrics").firstMatch
        XCTAssertTrue(shell.waitForExistence(timeout: 5))
        XCTAssertEqual(try waitForMetric("chat-panel-open", equals: "true", in: shell), "true")
        let closeSidebar = try NativeUITestElementResolution.requireVisible(
            app.buttons.matching(identifier: "chat-sidebar-close"), in: app)
        closeSidebar.tap()
        XCTAssertEqual(try waitForMetric("chat-panel-open", equals: "false", in: shell), "false")
        app.terminate()
        app.launch()
        XCTAssertTrue(app.wait(for: .runningForeground, timeout: 12))
        try assertHeaderTitle("Current Chat", in: app)

        XCTAssertEqual(try waitForMetric("chat-panel-open", equals: "false", in: shell), "false",
                       "Header navigation requires the sidebar to be closed after relaunch")
        let nextButton = try NativeUITestElementResolution.requireVisible(
            app.buttons.matching(identifier: "chat-header-next"), in: app)
        let previousButton = try NativeUITestElementResolution.requireVisible(
            app.buttons.matching(identifier: "chat-header-previous"), in: app)
        XCTAssertLessThan(nextButton.frame.midX, previousButton.frame.midX, "Next/newer control belongs on the left; previous/older belongs on the right.")

        previousButton.tap()
        try assertHeaderTitle("Older Chat", in: app)
        XCTAssertEqual(try waitForMetric("selected-chat-id", equals: "ui-test-older-chat", in: metrics), "ui-test-older-chat")

        try NativeUITestElementResolution.requireVisible(
            app.buttons.matching(identifier: "chat-header-next"), in: app).tap()
        try assertHeaderTitle("Current Chat", in: app)
        XCTAssertEqual(try waitForMetric("selected-chat-id", equals: "ui-test-current-chat", in: metrics), "ui-test-current-chat")

        try NativeUITestElementResolution.requireVisible(
            app.buttons.matching(identifier: "chat-header-next"), in: app).tap()
        try assertHeaderTitle("Newer Chat", in: app)
        XCTAssertEqual(try waitForMetric("selected-chat-id", equals: "ui-test-newer-chat", in: metrics), "ui-test-newer-chat")

        try NativeUITestElementResolution.requireVisible(
            app.buttons.matching(identifier: "chat-header-next"), in: app).tap()
        XCTAssertEqual(try waitForMetric("selected-chat-id", equals: "ui-test-draft-chat", in: metrics), "ui-test-draft-chat")
        let draftEditor = app.textViews["message-editor"].firstMatch
        XCTAssertTrue(draftEditor.waitForExistence(timeout: 5))
        let restoredDraft = XCTNSPredicateExpectation(predicate: NSPredicate(format: "value == %@", "Header navigation draft"),
                                                     object: app.textViews["message-editor"].firstMatch)
        XCTAssertEqual(XCTWaiter.wait(for: [restoredDraft], timeout: 10), .completed,
                       "The selected draft must restore its encrypted composer content")
        XCTAssertFalse(app.staticTexts["chat-header-title"].exists,
                       "An unsent draft must not create generated chat header UI")
    }

    // contract-test: direct surface=gui.apple assertions=drafts.draft-only.lifecycle,chat-navigation.empty-new-chat.excluded
    func testClearingAdoptedDraftReturnsToUnfocusedWorkspaceLanding() throws {
        let app = XCUIApplication()
        app.launchArguments = ["--ui-test-window-drafts", "--ui-test-nav-callback-diagnostics", "-AppleLanguages", "(en)"]
        app.launch()
        let editor = app.textViews["message-editor"].firstMatch
        XCTAssertTrue(editor.waitForExistence(timeout: 15))
        guard RealAccountUITestSupport.focusForTextEntry(editor, in: app, identifier: "message-editor") else { return }
        let draft = "Draft to clear"
        editor.typeText(draft)
        let adopted = app.descendants(matching: .any)
            .matching(NSPredicate(format: "identifier BEGINSWITH %@", "chat-view-")).firstMatch
        XCTAssertTrue(adopted.waitForExistence(timeout: 10))
        let adoptedChatID = String(adopted.identifier.dropFirst("chat-view-".count))
        let restored = XCTNSPredicateExpectation(predicate: NSPredicate { _, _ in
            // Adoption replaces the welcome editor. Resolve the current native
            // editor on every pass rather than retaining the pre-remount target.
            let route = app.staticTexts["chat-draft-restore-probe"]
            guard route.exists,
                  route.label.contains("chat-id=\(adoptedChatID);loaded-route=\(adoptedChatID);") else { return false }
            guard let currentEditor = NativeUITestElementResolution.visible(
                app.textViews.matching(identifier: "message-editor"), in: app) else { return false }
            return (currentEditor.value as? String) == draft
        }, object: nil)
        let restoreOutcome = XCTWaiter.wait(for: [restored], timeout: 10)
        if restoreOutcome != .completed { attachSyntheticDraftNavigationReceipt(app, name: "Adopted draft restore failure") }
        XCTAssertEqual(restoreOutcome, .completed,
                       "Draft adoption must restore saved content before editing resumes")
        let adoptedEditor = try XCTUnwrap(NativeUITestElementResolution.visible(
            app.textViews.matching(identifier: "message-editor"), in: app))
        XCTAssertEqual(adoptedEditor.value as? String, draft)
        XCTAssertFalse(app.staticTexts["chat-header-title"].exists,
                       "Saving an editor draft must not create a gradient header")
        let removedID = adopted.identifier
        guard RealAccountUITestSupport.focusForTextEntry(adoptedEditor, in: app, identifier: "message-editor") else { return }
        adoptedEditor.typeText(String(repeating: XCUIKeyboardKey.delete.rawValue, count: draft.count))
        let closed = XCTNSPredicateExpectation(predicate: NSPredicate(format: "exists == false"),
                                               object: app.descendants(matching: .any)[removedID])
        XCTAssertEqual(XCTWaiter.wait(for: [closed], timeout: 12), .completed)
        XCTAssertTrue(app.descendants(matching: .any)["chat-workspace-welcome"].waitForExistence(timeout: 5))
        let keyboardClosed = XCTNSPredicateExpectation(predicate: NSPredicate(format: "exists == false"),
                                                       object: app.keyboards.firstMatch)
        XCTAssertEqual(XCTWaiter.wait(for: [keyboardClosed], timeout: 5), .completed,
                       "Deleting the draft returns to reading the workspace")
        XCTAssertEqual(app.textViews["message-editor"].firstMatch.value as? String, "")
    }

    // contract-test: supporting surface=gui.apple assertions=chat-navigation.open.local-first-coherent,message-input.focus.workspace-suppression
    func testContinuationOpensPersistedChatWithoutReplayingComposerFocus() throws {
        let app = XCUIApplication()
        app.launchArguments = ["--ui-test-authenticated-chat-navigation", "--ui-test-stale-composer-focus", "--ui-test-nav-callback-diagnostics"]
        app.launch()
        // The stale focus fixture intentionally opens its initial composer.
        // Restore the suppressed workspace through the actual Cancel action.
        let backdrop = app.buttons["chat-composer-workspace-backdrop"]
        XCTAssertTrue(backdrop.waitForExistence(timeout: 12))
        XCTAssertEqual(backdrop.value as? String, "background-opacity=0.35;background-interactive=false")
        XCTAssertTrue(app.keyboards.firstMatch.waitForExistence(timeout: 5),
            "The fixture must establish the initial composer focus request")
        XCTAssertFalse(app.staticTexts["chat-header-title"].exists,
            "Focused composing suppresses the initial transcript header")
        let initialEditor = app.textViews["message-editor"].firstMatch
        let originalDraft = initialEditor.value as? String
        try NativeUITestElementResolution.requireVisible(
            app.buttons.matching(identifier: "chat-composer-cancel"), in: app, timeout: 5).tap()
        XCTAssertTrue(backdrop.waitForNonExistence(timeout: 5))
        XCTAssertEqual(initialEditor.value as? String, originalDraft)
        XCTAssertTrue(app.keyboards.firstMatch.waitForNonExistence(timeout: 5))
        try assertHeaderTitle("Current Chat", in: app)
        let close = try NativeUITestElementResolution.requireVisible(
            app.buttons.matching(identifier: "chat-close-button"), in: app, timeout: 5)
        close.tap()
        let welcomeOpened = app.descendants(matching: .any)["chat-workspace-welcome"].waitForExistence(timeout: 5)
        if !welcomeOpened { attachSyntheticDraftNavigationReceipt(app, name: "Actual close navigation failure") }
        XCTAssertTrue(welcomeOpened)
        let cardQuery = app.buttons.matching(NSPredicate(format: "identifier IN %@",
            ["welcome-chat-card-ui-test-current-chat", "welcome-chat-compact-card-ui-test-current-chat"]))
        let landingReady = XCTNSPredicateExpectation(predicate: NSPredicate { _, _ in
            let navigation = app.staticTexts.containing(NSPredicate(format: "label CONTAINS %@", "chat-navigation-order=")).firstMatch
            guard navigation.exists, navigation.label.contains("selected-chat-id=nil;"),
                  navigation.label.contains("show-new-chat=true;"),
                  navigation.label.contains("history-presentation-pending=nil"),
                  !app.descendants(matching: .any)["chat-view-ui-test-current-chat"].exists,
                  let currentCard = NativeUITestElementResolution.visible(cardQuery, in: app) else { return false }
            return app.windows.firstMatch.frame.contains(currentCard.frame)
        }, object: nil)
        let landingOutcome = XCTWaiter.wait(for: [landingReady], timeout: 8)
        if landingOutcome != .completed { attachSyntheticDraftNavigationReceipt(app, name: "Continuation card landing readiness failure") }
        XCTAssertEqual(landingOutcome, .completed, "Tap the visible production Button after the old chat presentation is removed")
        let card = try XCTUnwrap(NativeUITestElementResolution.visible(cardQuery, in: app))
        XCTAssertTrue(app.windows.firstMatch.frame.contains(card.frame))
        card.tap()
        let routePresented = XCTNSPredicateExpectation(predicate: NSPredicate { _, _ in
            let current = app.staticTexts.containing(NSPredicate(format: "label CONTAINS %@", "chat-navigation-order=")).firstMatch
            return current.exists && current.label.contains("selected-chat-id=ui-test-current-chat;")
                && current.label.contains("show-new-chat=false;")
                && current.label.contains("history-presentation-pending=nil")
        }, object: nil)
        let routeOutcome = XCTWaiter.wait(for: [routePresented], timeout: 5)
        if routeOutcome != .completed { attachSyntheticDraftNavigationReceipt(app, name: "Continuation actual route presentation failure") }
        XCTAssertEqual(routeOutcome, .completed, "The actual card callback must select Current Chat and complete its presentation")
        try assertHeaderTitle("Current Chat", in: app)
        XCTAssertFalse(app.keyboards.firstMatch.exists, "A continuation card opens the transcript for reading")
        XCTAssertTrue(app.staticTexts.containing(NSPredicate(format: "label == %@", "Current Chat")).firstMatch.exists)
    }

    private func attachSyntheticDraftNavigationReceipt(_ app: XCUIApplication, name: String) {
        // This helper is called only by the two explicit synthetic fixtures.
        // Read actual editor AX values in the failed UI, never log production drafts.
        let editors = app.textViews.matching(identifier: "message-editor").allElementsBoundByIndex
        let editorReceipt = editors.enumerated().map { index, editor in
            "editor[\(index)];value=\(editor.value ?? "unavailable");bounds=\(editor.frame);hittable=\(editor.isHittable)"
        }.joined(separator: "\n")
        let receipt = XCTAttachment(string: editorReceipt + "\n" + app.debugDescription)
        receipt.name = name + " synthetic AX and actual editor values"
        receipt.lifetime = .keepAlways
        add(receipt)
        let screenshot = XCTAttachment(screenshot: app.screenshot())
        screenshot.name = name + " viewport"
        screenshot.lifetime = .keepAlways
        add(screenshot)
    }

    // contract-test: direct surface=gui.apple assertions=chat-navigation.open.local-first-coherent
    func testContinuationShowsCachedIdentityWhileSelectedWindowLoads() throws {
        let app = XCUIApplication()
        app.launchArguments = ["--ui-test-authenticated-chat-navigation", "--ui-test-delayed-visible-window"]
        app.launch()
        try assertHeaderTitle("Current Chat", in: app)
        let loading = app.descendants(matching: .any)["chat-initial-content-loading"].firstMatch
        let loaded = XCTNSPredicateExpectation(predicate: NSPredicate(format: "exists == false"), object: loading)
        XCTAssertEqual(XCTWaiter.wait(for: [loaded], timeout: 8), .completed)
        let close = try NativeUITestElementResolution.requireVisible(
            app.buttons.matching(identifier: "chat-close-button"), in: app, timeout: 5)
        close.tap()
        let welcome = app.descendants(matching: .any)["chat-workspace-welcome"]
        let welcomeAppeared = welcome.waitForExistence(timeout: 5)
        if !welcomeAppeared {
            let screenshot = XCTAttachment(screenshot: app.screenshot())
            screenshot.name = "Cached identity actual close missing welcome viewport"
            screenshot.lifetime = .keepAlways
            add(screenshot)
            let hierarchy = XCTAttachment(string: app.debugDescription)
            hierarchy.name = "Cached identity actual close missing welcome synthetic accessibility"
            hierarchy.lifetime = .keepAlways
            add(hierarchy)
        }
        XCTAssertTrue(welcomeAppeared)
        let card = app.descendants(matching: .any).matching(NSPredicate(format: "identifier IN %@",
            ["welcome-chat-card-ui-test-current-chat", "welcome-chat-compact-card-ui-test-current-chat"])).firstMatch
        XCTAssertTrue(card.waitForExistence(timeout: 8))
        card.tap()
        XCTAssertTrue(loading.waitForExistence(timeout: 1), "The delay is in the selected content, not a welcome/new-chat shell")
        let title = app.staticTexts["chat-header-title"].firstMatch
        XCTAssertEqual(title.label, "Current Chat", "Cached decrypted identity must appear before the window finishes loading")
        XCTAssertFalse(app.descendants(matching: .any)["chat-workspace-welcome"].exists)
        XCTAssertFalse(app.descendants(matching: .any)["follow-up-suggestions"].exists)
        XCTAssertFalse(app.keyboards.firstMatch.exists)
        XCTAssertEqual(XCTWaiter.wait(for: [XCTNSPredicateExpectation(
            predicate: NSPredicate(format: "exists == false"), object: loading)], timeout: 8), .completed)
        let history = app.scrollViews["chat-history-container"].firstMatch
        XCTAssertTrue(history.waitForExistence(timeout: 5))
        // The selectable user text exposes its stable message identity even when
        // SwiftUI flattens the single row's containing accessibility element.
        let selectedMessage = history.textViews.matching(NSPredicate(format:
            "identifier == %@ AND label == %@ AND value == %@",
            "message-selectable-text-message-ui-test-current-chat", "Current Chat", "Current Chat")).firstMatch
        let selectedRowExists = selectedMessage.waitForExistence(timeout: 5)
        if !selectedRowExists {
            let hierarchy = XCTAttachment(string: app.debugDescription)
            hierarchy.name = "synthetic-selected-chat-missing-row-AX"; hierarchy.lifetime = .keepAlways; add(hierarchy)
        }
        XCTAssertTrue(selectedRowExists, "The actual selected Current Chat user row must exist")
        let visibleSelectedMessage = XCTNSPredicateExpectation(predicate: NSPredicate { _, _ in
            guard selectedMessage.exists, !selectedMessage.frame.isEmpty else { return false }
            let visibleTranscript = history.frame.intersection(app.windows.firstMatch.frame)
            return visibleTranscript.contains(CGPoint(x: selectedMessage.frame.midX, y: selectedMessage.frame.midY))
                && selectedMessage.label == "Current Chat"
                && (selectedMessage.value as? String) == "Current Chat"
        }, object: selectedMessage)
        XCTAssertEqual(XCTWaiter.wait(for: [visibleSelectedMessage], timeout: 5), .completed,
                       "The selected chat's actual user row must render inside the transcript viewport")
        XCTAssertEqual(title.label, "Current Chat")
    }

    // contract-test: direct surface=gui.apple assertions=chat-navigation.open.local-first-coherent
    func testSelectingSidebarChatClosesPreviousFullscreenEmbedAndPreservesTranscript() throws {
        let app = XCUIApplication()
        app.launchArguments = ["--ui-test-authenticated-chat-navigation", "--ui-test-navigation-embed"]
        app.launch()
        try assertHeaderTitle("Current Chat", in: app)
        // Code cards combine their children into the production open button.
        // Scope the action to the persisted assistant's named code artifact.
        let assistant = app.descendants(matching: .any)["message-assistant"].firstMatch
        let preview = assistant.buttons.matching(NSPredicate(
            format: "identifier == %@ AND label CONTAINS %@", "embed-preview", "example.py")).firstMatch
        XCTAssertTrue(preview.waitForExistence(timeout: 10))
        preview.tap()
        let fullscreen = app.descendants(matching: .any)["embed-fullscreen-header"].firstMatch
        XCTAssertTrue(fullscreen.waitForExistence(timeout: 8))
        try selectSidebarChat("Newer Chat", in: app)
        let closed = XCTNSPredicateExpectation(predicate: NSPredicate(format: "exists == false"), object: fullscreen)
        XCTAssertEqual(XCTWaiter.wait(for: [closed], timeout: 5), .completed)
        XCTAssertFalse(app.keyboards.firstMatch.exists)
        try selectSidebarChat("Current Chat", in: app)
        XCTAssertTrue(preview.waitForExistence(timeout: 8), "Original persisted embed remains in the transcript")
        XCTAssertFalse(fullscreen.exists, "Returning to a chat does not restore a dismissed overlay")
    }

    // contract-test: supporting surface=gui.apple assertions=chats.surface.semantic-parity,chat-navigation.open.local-first-coherent
    func testSavedSheetReferenceHydratesPreviewFullscreenAndSurvivesChatReparse() throws {
        let app = XCUIApplication()
        app.launchArguments = ["--ui-test-authenticated-chat-navigation", "--ui-test-sheet-reference-hydration"]
        app.launch()
        try assertHeaderTitle("Current Chat", in: app)
        XCTAssertTrue(app.descendants(matching: .any)["sheet-preview-table"].waitForExistence(timeout: 10))
        let preview = app.descendants(matching: .any)["embed-preview-ui-test-sheet-reference"].firstMatch
        if app.windows.firstMatch.frame.width >= 600 {
            XCTAssertGreaterThan(preview.frame.width, 400,
                "A standalone assistant Sheet must use its large preview in a wide transcript")
            let screenshot = XCTAttachment(screenshot: XCUIScreen.main.screenshot())
            screenshot.name = "Persisted standalone assistant Sheet uses large preview"
            screenshot.lifetime = .keepAlways
            add(screenshot)
        }
        let openButton = try NativeUITestElementResolution.requireVisible(
            preview.buttons.matching(identifier: "embed-preview"), in: app)
        openButton.tap()
        XCTAssertTrue(app.descendants(matching: .any)["sheet-fullscreen-table"].waitForExistence(timeout: 8))
        try assertSheetFullscreenValue("Saved Row A", in: app)
        try assertSheetFullscreenValue("Saved Row B", in: app)
        try selectSidebarChat("Newer Chat", in: app)
        XCTAssertTrue(app.descendants(matching: .any)["sheet-fullscreen-table"].firstMatch
            .waitForNonExistence(timeout: 5), "Changing chats dismisses the previous Sheet fullscreen")
        try selectSidebarChat("Current Chat", in: app)
        XCTAssertTrue(app.descendants(matching: .any)["sheet-preview-table"].waitForExistence(timeout: 8))
        let restoredPreview = app.descendants(matching: .any)["embed-preview-ui-test-sheet-reference"].firstMatch
        try NativeUITestElementResolution.requireVisible(
            restoredPreview.buttons.matching(identifier: "embed-preview"), in: app).tap()
        try assertSheetFullscreenValue("Saved Row B", in: app)
    }

    private func selectSidebarChat(_ title: String, in app: XCUIApplication) throws {
        let closeQuery = app.buttons.matching(identifier: "chat-sidebar-close")
        // Retained offscreen close controls can exist while the menu is closed.
        if NativeUITestElementResolution.visible(closeQuery, in: app) == nil {
            let open = try NativeUITestElementResolution.requireVisible(
                app.buttons.matching(identifier: "sidebar-toggle"), in: app)
            open.tap()
        }
        let panel = try NativeUITestElementResolution.requireVisible(
            app.descendants(matching: .any).matching(identifier: "chat-history-panel"),
            in: app, actionable: false)
        let row = try NativeUITestElementResolution.requireVisible(
            panel.buttons.matching(NSPredicate(format: "label == %@", title)), in: app)
        row.tap()
        try assertHeaderTitle(title, in: app)
        // Regular selection retains the sidebar; compact selection closes it.
        if let close = NativeUITestElementResolution.visible(closeQuery, in: app) { close.tap() }
        _ = try NativeUITestElementResolution.requireVisible(
            app.buttons.matching(identifier: "sidebar-toggle"), in: app)
    }

    private func assertHeaderTitle(_ expected: String, in app: XCUIApplication) throws {
        let title = app.staticTexts["chat-header-title"]
        let settled = XCTNSPredicateExpectation(
            predicate: NSPredicate(format: "exists == true AND label == %@", expected), object: title)
        XCTAssertEqual(XCTWaiter.wait(for: [settled], timeout: 12), .completed,
                       "Expected chat header title \(expected); observed \(title.exists ? title.label : "missing")")
        XCTAssertEqual(title.label, expected)
    }

    private func assertSheetFullscreenValue(_ expected: String, in app: XCUIApplication) throws {
        let table = app.descendants(matching: .any)["sheet-fullscreen-table"].firstMatch
        // Fullscreen cells use selectable UITextViews so long values wrap and
        // remain copyable. Match the exact value within this table.
        let cell = table.textViews.matching(NSPredicate(format: "value == %@", expected)).firstMatch
        XCTAssertTrue(cell.waitForExistence(timeout: 8), "Missing saved table value \(expected)")
        XCTAssertEqual(cell.value as? String, expected)
    }

    // contract-test: supporting surface=gui.apple assertions=chat-navigation.order.sidebar-header-match
    func testGlobalSearchFromWorkflowRestoresCurrentChatOnCancel() throws {
        let app = XCUIApplication()
        app.launchArguments = ["--ui-test-authenticated-chat-navigation",
                               "--ui-test-workflows-fixture", "home",
                               "--ui-test-workspace-search"]
        app.launchEnvironment["UI_TEST_AUTHENTICATED_CHAT_NAVIGATION"] = "1"
        app.launch()
        // SwiftUI exposes the identifier on an enclosing Other element; read
        // the static text, as the existing navigation case does.
        let metrics = app.staticTexts
            .containing(NSPredicate(format: "label CONTAINS %@", "chat-navigation-order="))
            .firstMatch
        XCTAssertTrue(metrics.waitForExistence(timeout: 12))
        XCTAssertEqual(try waitForMetric("selected-workspace", equals: "workflows", in: metrics), "workflows")
        let before = try XCTUnwrap(Int(try stringMetric("active-chat-revision", in: metrics.label)))
        app.buttons["workspace-search-ui-test"].tap()
        XCTAssertTrue(app.textFields["search-input"].waitForExistence(timeout: 5))
        app.buttons["search-close-button"].tap()
        let searchClosed = XCTNSPredicateExpectation(
            predicate: NSPredicate(format: "exists == false"),
            object: app.textFields["search-input"])
        XCTAssertEqual(XCTWaiter.wait(for: [searchClosed], timeout: 5), .completed,
                       "Closing Search must remove its input before returning to the chat history.")
        let sidebarClose = app.buttons["chat-sidebar-close"]
        if sidebarClose.waitForExistence(timeout: 3), sidebarClose.isHittable { sidebarClose.tap() }
        try assertHeaderTitle("Current Chat", in: app)
        XCTAssertEqual(try waitForMetric("selected-workspace", equals: "chat", in: metrics), "chat")
        XCTAssertEqual(try waitForMetric("active-chat-id", equals: "ui-test-current-chat", in: metrics), "ui-test-current-chat")
        let announced = XCTNSPredicateExpectation(
            predicate: NSPredicate { _, _ in
                (self.metric("active-chat-revision", in: metrics.label).flatMap(Int.init) ?? 0) > before
            }, object: metrics)
        XCTAssertEqual(XCTWaiter.wait(for: [announced], timeout: 5), .completed,
                       "Returning from a workspace through Search must reannounce the unchanged chat.")
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

    private func waitForMetric(_ key: String, equals expected: String, in element: XCUIElement, onTimeout: (() -> Void)? = nil) throws -> String {
        let deadline = Date().addingTimeInterval(5)
        while Date() < deadline {
            if let value = metric(key, in: element.label), value == expected {
                return value
            }
            RunLoop.current.run(until: Date().addingTimeInterval(0.1))
        }
        onTimeout?()
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
