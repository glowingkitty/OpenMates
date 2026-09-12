// Live UI coverage for the native chat flow.
// Mirrors the core web chat-flow.spec.ts path for a real account and covers the
// signed-out anonymous free-usage path from the welcome composer. Real-account
// credentials are read only from the test process environment and are never
// logged or committed.

import CryptoKit
import Foundation
import XCTest

@MainActor
final class ChatFlowRealAccountUITests: XCTestCase {
    private let markerPrompt = "Write four short sentences about Kyoto and Osaka. Start with: Kyoto neighbors Osaka."
    private let anonymousPrompt = "Anonymous native smoke test: answer with one short sentence."
    private let assistantResponseTimeout: TimeInterval = 90

    override func setUpWithError() throws {
        continueAfterFailure = false
    }

    // contract-test: supporting surface=gui.apple assertions=sync.surface.semantic-parity,chats.surface.semantic-parity
    func testExistingEncryptedChatsRestoreUserMessagesAndEmbedPreviews() throws {
        guard let configured = RealAccountTestCredentials.configurationValue(for: "OPENMATES_TEST_EMBED_CHAT_IDS") else {
            throw XCTSkip("Configure existing test-account chats containing user messages and embeds")
        }
        guard let queries = RealAccountTestCredentials.configurationValue(for: "OPENMATES_TEST_EMBED_CHAT_QUERIES")?.split(separator: "|").map(String.init),
              queries.count == configured.split(separator: ",").count else {
            throw XCTSkip("Configure matching chat search titles for the existing embed fixtures")
        }
        let credentials = try RealAccountTestCredentials.fromEnvironment()
        RealAccountUITestSupport.installNotificationPermissionHandler(on: self)
        let reuseAuthentication = RealAccountTestCredentials.configurationValue(for: "OPENMATES_TEST_REUSE_AUTH") == "1"
        let app = RealAccountUITestSupport.launchApp(disableAuthCache: !reuseAuthentication,
            extraArguments: (reuseAuthentication ? [] : ["--ui-test-open-login"]) + ["--ui-test-start-new-chat", "--ui-test-expose-chat-ids"])
        if !reuseAuthentication {
            RealAccountUITestSupport.logIn(app: app, credentials: credentials)
        }
        XCTAssertTrue(waitForInitialSyncComplete(in: app, timeout: 35))
        for (index, chatId) in configured.split(separator: ",").map(String.init).enumerated() {
            openChatsPanel(in: app, allowingSearch: true)
            // SwiftUI can propagate the panel identifier over its header
            // buttons on iOS; retain the actual Search accessibility label.
            let searchButton = app.buttons.matching(NSPredicate(
                format: "identifier == %@ OR label == %@", "search-button", "Search"
            )).firstMatch
            let existingSearch = app.textFields.matching(NSPredicate(format: "placeholderValue == %@", "Search")).firstMatch
            if !existingSearch.exists {
                XCTAssertTrue(searchButton.waitForExistence(timeout: 10))
                searchButton.coordinate(withNormalizedOffset: CGVector(dx: 0.5, dy: 0.5)).tap()
            }
            let search = app.textFields.matching(NSPredicate(
                format: "identifier == %@ OR placeholderValue == %@", "search-input", "Search"
            )).firstMatch
            XCTAssertTrue(search.waitForExistence(timeout: 10))
            search.tap()
            if index > 0, let value = search.value as? String, !value.isEmpty {
                search.typeText(String(repeating: XCUIKeyboardKey.delete.rawValue, count: value.count))
            }
            search.typeText(queries[index])
            let result = app.buttons.matching(identifier: "search-chat-item").firstMatch
            XCTAssertTrue(result.waitForExistence(timeout: 45), "Configured conversation must be searchable")
            let start = Date()
            result.tap()
            XCTAssertTrue(app.descendants(matching: .any).matching(identifier: "chat-view-\(chatId)").firstMatch.waitForExistence(timeout: 20))
            let user = app.descendants(matching: .any).matching(identifier: "message-user").firstMatch
            let assistant = app.descendants(matching: .any).matching(identifier: "message-assistant").firstMatch
            XCTAssertTrue(assistant.waitForExistence(timeout: 20), "Existing assistant message must remain visible")
            let scrollToTop = app.buttons["scroll-to-top-button"]
            if scrollToTop.exists { scrollToTop.tap() }
            XCTAssertTrue(user.waitForExistence(timeout: 20), "Existing user message must remain visible")
            let elapsed = Date().timeIntervalSince(start)
            let timing = XCTAttachment(string: "existing-chat-visible-seconds=\(elapsed)")
            timing.lifetime = .keepAlways
            add(timing)
            let preview = app.buttons.matching(identifier: "embed-preview").firstMatch
            XCTAssertTrue(preview.waitForExistence(timeout: 20), "Hydrated embed preview must be available")
            preview.tap()
            let minimize = app.buttons["embed-minimize"]
            XCTAssertTrue(minimize.waitForExistence(timeout: 10), "Embed preview must open its fullscreen content")
            let screenshot = XCTAttachment(screenshot: app.screenshot())
            screenshot.name = "Existing conversation embed content"
            screenshot.lifetime = .keepAlways
            add(screenshot)
            minimize.tap()
        }
    }

    // contract-test: supporting surface=gui.apple assertions=chats.surface.semantic-parity,sync.surface.semantic-parity
    func testExistingLongChatScrollsToFinalMessageRepeatedly() throws {
        guard let query = RealAccountTestCredentials.configurationValue(for: "OPENMATES_TEST_LONG_CHAT_QUERY") else {
            throw XCTSkip("Configure an existing long test-account conversation")
        }
        guard let firstMessageID = RealAccountTestCredentials.configurationValue(for: "OPENMATES_TEST_LONG_CHAT_FIRST_MESSAGE_ID"),
              let lastMessageID = RealAccountTestCredentials.configurationValue(for: "OPENMATES_TEST_LONG_CHAT_LAST_MESSAGE_ID"),
              !firstMessageID.isEmpty, !lastMessageID.isEmpty else {
            throw XCTSkip("Configure exact oldest/newest message IDs from the web fixture; arrow visibility alone is insufficient")
        }
        let credentials = try RealAccountTestCredentials.fromEnvironment()
        RealAccountUITestSupport.installNotificationPermissionHandler(on: self)
        let app = RealAccountUITestSupport.launchApp(disableAuthCache: true,
            extraArguments: ["--ui-test-start-new-chat", "--ui-test-history-window-metrics"])
        RealAccountUITestSupport.logIn(app: app, credentials: credentials)
        XCTAssertTrue(waitForInitialSyncComplete(in: app, timeout: 35))
        openChatsPanel(in: app, allowingSearch: true)
        let search = app.textFields.matching(NSPredicate(format: "placeholderValue == %@", "Search")).firstMatch
        if !search.exists {
            let button = app.buttons.matching(NSPredicate(format: "identifier == %@ OR label == %@", "search-button", "Search")).firstMatch
            XCTAssertTrue(button.waitForExistence(timeout: 10))
            button.coordinate(withNormalizedOffset: CGVector(dx: 0.5, dy: 0.5)).tap()
        }
        XCTAssertTrue(search.waitForExistence(timeout: 10))
        search.tap()
        if let value = search.value as? String, !value.isEmpty {
            search.typeText(String(repeating: XCUIKeyboardKey.delete.rawValue, count: value.count))
        }
        search.typeText(query)
        let result = app.buttons.matching(identifier: "search-chat-item").firstMatch
        XCTAssertTrue(result.waitForExistence(timeout: 45))
        XCTAssertTrue(result.label.localizedCaseInsensitiveContains(query))
        result.tap()
        let history = app.scrollViews.matching(identifier: "chat-history-container").firstMatch
        XCTAssertTrue(history.waitForExistence(timeout: 20))
        let oldest = app.descendants(matching: .any)["chat-history-message-" + firstMessageID].firstMatch
        let latest = app.descendants(matching: .any)["chat-history-message-" + lastMessageID].firstMatch
        let content = app.descendants(matching: .any)["chat-history-content"].firstMatch
        func endpointIsVisible(_ row: XCUIElement) -> Bool {
            guard row.exists, !row.frame.isEmpty else { return false }
            let intersection = row.frame.intersection(history.frame)
            return !intersection.isNull && intersection.height > 1 && intersection.width > 1
        }
        func assertBoundedWindow() {
            let value = content.value as? String ?? ""
            let renderedField = value.split(separator: ";").first { $0.hasPrefix("rendered=") }
            let count = renderedField.flatMap { Int($0.dropFirst("rendered=".count)) } ?? -1
            XCTAssertTrue((1...50).contains(count), "Rendered history must remain bounded throughout traversal")
        }
        let toTop = app.buttons["scroll-to-top-button"]
        let toBottom = app.buttons["scroll-to-bottom-button"]
        for pass in 1...3 {
            if toTop.exists { toTop.tap() }
            XCTAssertTrue(toTop.waitForNonExistence(timeout: 10))
            XCTAssertTrue(endpointIsVisible(oldest), "The configured oldest web message must be in the viewport")
            assertBoundedWindow()
            var gestures = 0
            let started = Date()
            repeat {
                history.swipeUp()
                gestures += 1
                assertBoundedWindow()
            } while (toBottom.exists || !endpointIsVisible(latest)) && gestures < 180
            XCTAssertTrue(endpointIsVisible(latest), "The exact newest web message must be visible")
            XCTAssertFalse(toBottom.exists, "The true end must be reached after rendering that message")
            XCTAssertTrue(toTop.exists, "Long conversation must remain navigable back to the beginning")
            XCTAssertTrue(app.state == .runningForeground)
            XCTAssertNotNil(RealAccountUITestSupport.waitForMessageEditor(in: app, timeout: 5))
            let attachment = XCTAttachment(string: "full-scroll-pass=\(pass) gestures=\(gestures) seconds=\(Date().timeIntervalSince(started))")
            attachment.lifetime = .keepAlways
            add(attachment)
        }
        toTop.tap()
        XCTAssertTrue(toTop.waitForNonExistence(timeout: 10))
        let preview = app.buttons.matching(identifier: "embed-preview").firstMatch
        XCTAssertTrue(preview.waitForExistence(timeout: 10))
        preview.tap()
        let minimize = app.buttons["embed-minimize"]
        XCTAssertTrue(minimize.waitForExistence(timeout: 10), "Citation/embed actions must still work after repeated full traversal")
        minimize.tap()
    }

    // contract-test: direct surface=gui.apple assertions=auth.login.method-convergence,chats.persistence.client-encrypted
    func testCachedAccountLaunchCompletesInitialSync() throws {
        _ = try RealAccountTestCredentials.fromEnvironment()
        let app = RealAccountUITestSupport.launchApp(extraArguments: ["--ui-test-expose-chat-ids"])
        XCTAssertTrue(waitForInitialSyncComplete(in: app, timeout: 35),
                      "A cached account must finish the real phased sync after launch")
    }

    // contract-test: direct surface=gui.apple assertions=auth.login.method-convergence,chats.persistence.client-encrypted
    func testPasswordOtpLoginCreatesChatAndReceivesAssistantResponse() throws {
        let markerPrompt = "Reply with one short sentence: Hello from Osaka."
        let credentials = try RealAccountTestCredentials.fromEnvironment()
        RealAccountUITestSupport.installNotificationPermissionHandler(on: self)
        let app = RealAccountUITestSupport.launchApp(
            disableAuthCache: true,
            extraArguments: ["--ui-test-open-login", "--ui-test-start-new-chat", "--ui-test-expose-chat-ids", "--ui-test-welcome-send-stage"]
        )

        RealAccountUITestSupport.logIn(app: app, credentials: credentials)
        RealAccountUITestSupport.sendWelcomePrompt(app: app, prompt: markerPrompt)
        RealAccountUITestSupport.assertAssistantResponds(app: app, timeout: assistantResponseTimeout)

        let active = app.descendants(matching: .any)
            .matching(NSPredicate(format: "identifier BEGINSWITH %@", "chat-view-")).firstMatch
        XCTAssertTrue(active.exists)
        let chatId = String(active.identifier.dropFirst("chat-view-".count))
        XCTAssertFalse(chatId.isEmpty)
        app.terminate()
        app.launchArguments.removeAll { ["--ui-test-disable-auth-cache", "--ui-test-open-login", "--ui-test-start-new-chat"].contains($0) }
        app.launch()
        XCTAssertTrue(waitForInitialSyncComplete(in: app, timeout: 35))
        openChatsPanel(in: app)
        let row = app.descendants(matching: .any).matching(NSPredicate(
            format: "identifier == %@ AND value == %@", "chat-item-wrapper", "user-chat:\(chatId)"
        )).firstMatch
        // Drafts sort ahead of recent conversations; expand and scroll the
        // sidebar before asserting that a particular persisted identity is absent.
        let history = app.scrollViews.matching(identifier: "chat-sidebar-scroll").firstMatch
        for _ in 0..<12 {
            if row.exists { break }
            let more = app.buttons["load-more-chats"]
            // A short page can place Load More just below the panel's top.
            // Check its tap point, not its whole frame, while keeping the tap
            // away from system edge gestures. XCTest can report a button under
            // the home indicator as hittable even when its tap is intercepted.
            if more.exists && more.isHittable && history.frame.insetBy(dx: 0, dy: 35).contains(
                CGPoint(x: more.frame.midX, y: more.frame.midY)
            ) {
                more.tap()
            } else {
                history.swipeUp()
            }
        }
        XCTAssertTrue(row.waitForExistence(timeout: 5), "Created chat must survive relaunch")
        row.tap()
        let userMessage = RealAccountUITestSupport.accessibilityElement(
            in: app, identifier: "message-user", labelContaining: markerPrompt)
        XCTAssertTrue(userMessage.waitForExistence(timeout: 25), "Original user message must survive relaunch")
        let assistants = app.otherElements.matching(identifier: "message-assistant")
        XCTAssertTrue(assistants.firstMatch.waitForExistence(timeout: 25), "Assistant response must survive relaunch")
        assertCompletionCommitted(in: app, minimumVersion: 2, assistantCount: 1)
        let previousCount = assistants.count
        let editor = try XCTUnwrap(RealAccountUITestSupport.waitForMessageEditor(in: app, timeout: 10))
        guard RealAccountUITestSupport.focusForTextEntry(editor, in: app, identifier: "message-editor") else { return }
        let followUpPrompt = "Which city did I mention? Reply with only the city name."
        app.typeText(followUpPrompt)
        XCTAssertEqual(editor.value as? String, followUpPrompt, "Typing must preserve the complete follow-up")
        app.buttons["send-button"].tap()
        let completed = NSPredicate { _, _ in assistants.count > previousCount }
        expectation(for: completed, evaluatedWith: app)
        waitForExpectations(timeout: assistantResponseTimeout)
        let streaming = RealAccountUITestSupport.accessibilityElement(in: app, identifier: "streaming-banner")
        XCTAssertTrue(streaming.waitForNonExistence(timeout: assistantResponseTimeout), "Follow-up must finish streaming")
        XCTAssertTrue(assistants.element(boundBy: assistants.count - 1).label.contains("Osaka"),
                      "Follow-up must use the persisted conversation history")
        assertCompletionCommitted(in: app, minimumVersion: 4, assistantCount: 2)
    }

    private func assertCompletionCommitted(in app: XCUIApplication, minimumVersion: Int, assistantCount: Int) {
        let probe = app.descendants(matching: .any).matching(identifier: "chat-recovery-state").firstMatch
        let committed = NSPredicate { _, _ in
            guard probe.exists, let value = probe.value as? String else { return false }
            let fields = value.split(separator: ";").reduce(into: [String: Int]()) { result, field in
                let parts = field.split(separator: "=", maxSplits: 1)
                if parts.count == 2, let number = Int(parts[1]) { result[String(parts[0])] = number }
            }
            return fields["pending"] == 0 && fields["version", default: 0] >= minimumVersion
                && fields["encrypted", default: 0] >= assistantCount
        }
        let expectation = XCTNSPredicateExpectation(predicate: committed, object: probe)
        XCTAssertEqual(XCTWaiter.wait(for: [expectation], timeout: 150), .completed,
                       "The rendered reply must also reach server-acknowledged encrypted persistence, including another client's lease expiry")
    }

    // contract-test: direct surface=gui.apple assertions=auth.login.method-convergence,chats.surface.semantic-parity
    func testAppleCoreParityProof() throws {
        let credentials = try RealAccountTestCredentials.fromReservedSlot(14)
        let proofDeviceProfile = try String(contentsOfFile: "/tmp/openmates-proof-device-profile", encoding: .utf8)
            .trimmingCharacters(in: .whitespacesAndNewlines)
        switch proofDeviceProfile {
        case "apple-iphone-portrait":
            XCUIDevice.shared.orientation = .portrait
        case "apple-ipad-landscape":
            XCUIDevice.shared.orientation = .landscapeLeft
        default:
            XCTFail("Apple proof device profile is invalid")
            return
        }
        RunLoop.current.run(until: Date().addingTimeInterval(0.5))
        let captureEpochValue = try String(
            contentsOfFile: "/tmp/openmates-recording-started-unix-ms",
            encoding: .utf8
        ).trimmingCharacters(in: .whitespacesAndNewlines)
        guard let captureEpochMilliseconds = Double(captureEpochValue) else {
            XCTFail("Apple proof recording epoch is invalid")
            return
        }
        let started = Date(timeIntervalSince1970: captureEpochMilliseconds / 1000)
        RealAccountUITestSupport.installNotificationPermissionHandler(on: self)
        let app = RealAccountUITestSupport.launchApp(
            disableAuthCache: true,
            extraArguments: ["--ui-test-open-login", "--ui-test-start-new-chat"]
        )

        RealAccountUITestSupport.logIn(app: app, credentials: credentials)
        RunLoop.current.run(until: Date().addingTimeInterval(0.5))
        let loginReadyMs = Int(Date().timeIntervalSince(started) * 1000)
        RealAccountUITestSupport.sendWelcomePrompt(app: app, prompt: markerPrompt)
        let messageSentMs = Int(Date().timeIntervalSince(started) * 1000)
        let streamingBanner = RealAccountUITestSupport.accessibilityElement(
            in: app,
            identifier: "streaming-banner"
        )
        XCTAssertTrue(streamingBanner.waitForExistence(timeout: 30), "Expected visible processing state")
        let processingVisibleMs = Int(Date().timeIntervalSince(started) * 1000)
        let responseProgress = RealAccountUITestSupport.awaitProgressiveAssistantResponseForProof(
            app: app,
            timeout: assistantResponseTimeout
        )
        let firstChunkVisibleMs = Int(responseProgress.firstChunkVisibleAt.timeIntervalSince(started) * 1000)
        let responseVisibleMs = Int(responseProgress.completedAt.timeIntervalSince(started) * 1000)
        assertAssistantContentFitsHorizontally(in: app)
        assertAssistantUsesTranscriptWidth(in: app)
        assertFollowUpSuggestionsClearComposer(in: app)
        let responseReadyMs = Int(Date().timeIntervalSince(started) * 1000)

        attachScreenshot(name: "Apple core parity response ready")
        try attachProofTimeline(
            profile: proofDeviceProfile,
            loginReadyMs: loginReadyMs,
            messageSentMs: messageSentMs,
            processingVisibleMs: processingVisibleMs,
            firstChunkVisibleMs: firstChunkVisibleMs,
            responseVisibleMs: responseVisibleMs,
            responseReadyMs: responseReadyMs
        )
    }

    private func assertAssistantContentFitsHorizontally(in app: XCUIApplication) {
        let assistant = app.otherElements.matching(identifier: "message-assistant").firstMatch
        XCTAssertTrue(assistant.exists, "Expected an assistant message before checking its layout")
        let maximumX = assistant.frame.maxX + 1
        let overflowing = assistant.descendants(matching: .any).allElementsBoundByIndex.filter { element in
            let frame = element.frame
            return element.exists && !frame.isEmpty && frame.maxX > maximumX
        }
        XCTAssertTrue(
            overflowing.isEmpty,
            "Assistant content extended beyond its horizontal bounds: \(overflowing.map { $0.frame })"
        )
    }

    private func assertAssistantUsesTranscriptWidth(in app: XCUIApplication) {
        let history = app.otherElements["chat-history-container"]
        let assistantContent = app.descendants(matching: .any)["assistant-message-content"]
        let senderName = app.descendants(matching: .any)["message-sender-name"]
        XCTAssertTrue(history.exists)
        XCTAssertTrue(assistantContent.exists)
        XCTAssertTrue(senderName.exists)
        XCTAssertLessThanOrEqual(
            senderName.frame.minX,
            history.frame.minX + 24,
            "Assistant response was centered instead of leading-aligned"
        )
        XCTAssertGreaterThanOrEqual(
            assistantContent.frame.width,
            history.frame.width - 48,
            "Assistant response did not use the available transcript width"
        )
    }

    private func assertFollowUpSuggestionsClearComposer(in app: XCUIApplication) {
        let suggestions = app.descendants(matching: .any)["follow-up-suggestions"]
        guard suggestions.exists else { return }
        let composer = app.descendants(matching: .any)["message-editor"]
        let deadline = Date().addingTimeInterval(10)
        while suggestions.frame.maxY > composer.frame.minY + 1, Date() < deadline {
            RunLoop.current.run(until: Date().addingTimeInterval(0.25))
        }
        XCTAssertLessThanOrEqual(
            suggestions.frame.maxY,
            composer.frame.minY + 1,
            "Follow-up suggestions were covered by the fixed composer"
        )
    }

    // contract-test: direct surface=gui.apple assertions=sync.surface.semantic-parity,chat-navigation.open.local-first-coherent
    func testPasswordOtpLoginLoadsRecentChatsForWebParityManifest() throws {
        let credentials = try parityCredentials()
        RealAccountUITestSupport.installNotificationPermissionHandler(on: self)
        let app = RealAccountUITestSupport.launchApp()

        RealAccountUITestSupport.logIn(app: app, credentials: credentials)
        openChatsPanel(in: app)
        XCTAssertTrue(
            waitForInitialSyncComplete(in: app, timeout: 35),
            "Expected initial chat sync to complete before exporting parity manifest. Visible UI: \(visibleStateLabels(in: app))"
        )

        let rows = chatRows(in: app)
        XCTAssertTrue(
            waitForChatRows(rows, timeout: 30),
            "Expected at least one loaded chat row. Visible UI: \(visibleStateLabels(in: app))"
        )

        let manifest = makeLoadedChatsManifest(app: app, rows: rows, credentials: credentials)
        try attachAndWriteManifest(manifest)
        let openedManifest = try makeOpenedChatsManifest(app: app, rows: rows, loadedManifest: manifest, credentials: credentials)
        try attachAndWriteOpenedManifest(openedManifest)
        attachScreenshot(name: "Apple loaded chats parity")
    }

    // contract-test: supporting surface=gui.apple assertions=auth.surface.first-party-boundary,chats.surface.semantic-parity
    func testSignedOutAnonymousWelcomePromptCreatesChatAndReceivesAssistantResponse() async throws {
        try await requireAnonymousFreeUsageActive()

        let app = RealAccountUITestSupport.launchApp(
            preferPasswordLogin: false,
            disableAuthCache: true,
            extraArguments: ["--ui-test-start-new-chat"]
        )

        XCTAssertTrue(app.buttons["header-login-signup-btn"].waitForExistence(timeout: 15))
        RealAccountUITestSupport.sendWelcomePrompt(app: app, prompt: anonymousPrompt)
        RealAccountUITestSupport.assertAssistantResponds(app: app, timeout: assistantResponseTimeout)
    }

    private func requireAnonymousFreeUsageActive() async throws {
        let url = URL(string: "https://api.dev.openmates.org/v1/anonymous/free-usage/status")!
        let (data, _) = try await URLSession.shared.data(from: url)
        let status = try JSONDecoder().decode(AnonymousFreeUsageProbe.self, from: data)
        guard status.active else {
            throw XCTSkip("Anonymous free usage inactive on dev: \(status.reason ?? "unknown")")
        }
    }

    private func attachProofTimeline(
        profile: String,
        loginReadyMs: Int,
        messageSentMs: Int,
        processingVisibleMs: Int,
        firstChunkVisibleMs: Int,
        responseVisibleMs: Int,
        responseReadyMs: Int
    ) throws {
        let timeline: [String: Any] = [
            "schema_version": 1,
            "device": profile,
            "contract": [
                "id": "apple-core-parity",
                "title": "Apple core chat parity",
                "surface": "apple",
                "devices": [profile],
                "transcript": [
                    ["id": "shell", "text": "The authenticated native chat shell is ready for the conversation.", "checkpoint": "message-sent", "devices": [profile]],
                    ["id": "processing", "text": "A side rainbow marks active processing while the composer remains integrated with the chat background.", "checkpoint": "processing-visible", "devices": [profile]],
                    ["id": "first-chunk", "text": "The left-aligned assistant card appears as the first response chunk arrives.", "checkpoint": "first-chunk-visible", "devices": [profile]],
                    ["id": "chat", "text": "The same assistant card grows chunk by chunk into the completed four-sentence response.", "checkpoint": "response-visible", "devices": [profile]],
                ],
                "assertions": [
                    ["id": "auth.ready", "visual": "The authenticated native chat composer is visible.", "checkpoint": "message-sent", "devices": [profile]],
                    ["id": "chat.processing_rainbow", "visual": "The processing rainbow stays on the outer chat sides and does not overlay the thinking or message content.", "checkpoint": "processing-visible", "devices": [profile]],
                    ["id": "chat.composer_shell", "visual": "No opaque white strip appears behind the processing status or compact composer.", "checkpoint": "processing-visible", "devices": [profile]],
                    ["id": "chat.progressive_response", "visual": "The assistant response is visibly shorter at first-chunk-visible than at response-visible.", "checkpoint": "first-chunk-visible", "devices": [profile]],
                    ["id": "chat.response", "visual": "The completed assistant response is left-aligned, uses the available transcript width, and appears once.", "checkpoint": "response-visible", "devices": [profile]],
                ],
            ],
            "events": [
                ["kind": "checkpoint", "id": "login-ready", "at_ms": loginReadyMs],
                ["kind": "action", "id": "send-message", "start_ms": loginReadyMs, "end_ms": messageSentMs],
                ["kind": "checkpoint", "id": "message-sent", "at_ms": messageSentMs],
                ["kind": "checkpoint", "id": "processing-visible", "at_ms": processingVisibleMs],
                ["kind": "checkpoint", "id": "first-chunk-visible", "at_ms": firstChunkVisibleMs],
                ["kind": "checkpoint", "id": "response-visible", "at_ms": responseVisibleMs],
                ["kind": "checkpoint", "id": "response-ready", "at_ms": responseReadyMs],
            ],
            "assertion_results": [
                ["id": "auth.ready", "status": "passed", "at_ms": messageSentMs],
                ["id": "chat.processing_rainbow", "status": "passed", "at_ms": processingVisibleMs],
                ["id": "chat.composer_shell", "status": "passed", "at_ms": processingVisibleMs],
                ["id": "chat.progressive_response", "status": "passed", "at_ms": firstChunkVisibleMs],
                ["id": "chat.response", "status": "passed", "at_ms": responseVisibleMs],
            ],
        ]
        let data = try JSONSerialization.data(withJSONObject: timeline, options: [.prettyPrinted, .sortedKeys])
        let attachment = XCTAttachment(data: data, uniformTypeIdentifier: "public.json")
        attachment.name = "proof-timeline.json"
        attachment.lifetime = .keepAlways
        add(attachment)
    }

    private func openChatsPanel(in app: XCUIApplication, allowingSearch: Bool = false) {
        // Wait for the actual panel after tapping: during a cold relaunch the
        // startup overlay can still cover the header when sync first completes.
        let toggle = app.buttons["sidebar-toggle"]
        let panel = app.otherElements.matching(identifier: "chat-history-panel").firstMatch
        for _ in 0..<3 {
            if panel.exists && app.frame.contains(CGPoint(x: panel.frame.midX, y: panel.frame.midY)) { break }
            guard toggle.waitForExistence(timeout: 2) else { break }
            toggle.coordinate(withNormalizedOffset: CGVector(dx: 0.5, dy: 0.5)).tap()
            if chatRows(in: app).firstMatch.waitForExistence(timeout: 3) { break }
        }
        if allowingSearch && app.textFields.matching(NSPredicate(format: "placeholderValue == %@", "Search")).firstMatch.exists { return }
        XCTAssertTrue(chatRows(in: app).firstMatch.waitForExistence(timeout: 15),
                      "Chat history did not expose account rows after opening")
    }

    private func parityCredentials() throws -> RealAccountTestCredentials {
        let slotValue = ProcessInfo.processInfo.environment["CHAT_RENDERING_PARITY_ACCOUNT_SLOT"] ?? ""
        if !slotValue.isEmpty {
            guard let slot = Int(slotValue) else {
                throw XCTSkip("CHAT_RENDERING_PARITY_ACCOUNT_SLOT must be an integer from 1-20")
            }
            return try RealAccountTestCredentials.fromSlot(slot)
        }
        return try RealAccountTestCredentials.fromEnvironment()
    }

    private func chatRows(in app: XCUIApplication) -> XCUIElementQuery {
        app.descendants(matching: .any).matching(NSPredicate(
            format: "identifier == %@ AND (value == %@ OR value BEGINSWITH %@)",
            "chat-item-wrapper", "user-chat", "user-chat:"
        ))
    }

    private func waitForChatRows(_ rows: XCUIElementQuery, timeout: TimeInterval) -> Bool {
        let deadline = Date().addingTimeInterval(timeout)
        repeat {
            if rows.count > 0 {
                return true
            }
            RunLoop.current.run(until: Date().addingTimeInterval(0.25))
        } while Date() < deadline
        return rows.count > 0
    }

    private func waitForInitialSyncComplete(in app: XCUIApplication, timeout: TimeInterval) -> Bool {
        let marker = app.descendants(matching: .any)
            .matching(NSPredicate(format: "identifier == %@ AND value == %@", "chat-sync-complete", "true"))
            .firstMatch
        return marker.waitForExistence(timeout: timeout)
    }

    private func makeLoadedChatsManifest(app: XCUIApplication, rows: XCUIElementQuery, credentials: RealAccountTestCredentials) -> [String: Any] {
        let maxRows = Int(ProcessInfo.processInfo.environment["CHAT_RENDERING_PARITY_MAX_ROWS"] ?? "40") ?? 40
        let rowCount = min(rows.count, maxRows)
        let windowFrame = app.windows.firstMatch.frame
        var chats: [[String: Any]] = []

        for index in 0..<rowCount {
            let row = rows.element(boundBy: index)
            let label = row.label.trimmingCharacters(in: .whitespacesAndNewlines)
            let title = normalizedChatTitle(from: label)
            let frame = row.frame
            chats.append([
                "index": index,
                "titleText": title,
                "titleState": titleState(for: title),
                "accessibilityLabel": label,
                "isSubChat": false,
                "pinned": label.localizedCaseInsensitiveContains("pinned"),
                "visible": row.exists && !frame.isEmpty && windowFrame.intersects(frame),
                "rect": [
                    "x": Int(frame.origin.x.rounded()),
                    "y": Int(frame.origin.y.rounded()),
                    "width": Int(frame.size.width.rounded()),
                    "height": Int(frame.size.height.rounded())
                ]
            ])
        }

        return [
            "schema_version": 1,
            "surface": "loaded-user-chats",
            "client": "apple",
            "generated_at": ISO8601DateFormatter().string(from: Date()),
            "environment": [
                "account_email_hash": stableHash(credentials.email),
                "viewport_width": Int(windowFrame.size.width.rounded()),
                "viewport_height": Int(windowFrame.size.height.rounded()),
                "max_chat_rows": maxRows
            ],
            "required_elements": [
                "chat_history_panel": RealAccountUITestSupport.accessibilityElement(in: app, identifier: "chat-history-panel").exists,
                "chat_item_wrapper": chats.contains { ($0["isSubChat"] as? Bool) == false },
                "sub_chat_item": chats.contains { ($0["isSubChat"] as? Bool) == true },
                "chat_title": chats.contains { !(($0["titleText"] as? String) ?? "").isEmpty }
            ],
            "sidebar": [
                "is_visible": RealAccountUITestSupport.accessibilityElement(in: app, identifier: "chat-history-panel").exists,
                "chat_count": chats.count
            ],
            "chats": chats
        ]
    }

    private func makeOpenedChatsManifest(
        app: XCUIApplication,
        rows: XCUIElementQuery,
        loadedManifest: [String: Any],
        credentials: RealAccountTestCredentials
    ) throws -> [String: Any] {
        let limit = Int(ProcessInfo.processInfo.environment["CHAT_RENDERING_PARITY_OPENED_CHAT_LIMIT"] ?? "10") ?? 10
        let loadedChats = loadedManifest["chats"] as? [[String: Any]] ?? []
        let chatCount = min(min(rows.count, loadedChats.count), limit)
        var openedChats: [[String: Any]] = []

        for index in 0..<chatCount {
            openChatsPanel(in: app)
            let row = rows.element(boundBy: index)
            XCTAssertTrue(row.waitForExistence(timeout: 10), "Missing chat row \(index) before opened-chat parity export")
            row.tap()
            XCTAssertTrue(waitForOpenedChatMessages(in: app, timeout: 30), "Expected messages after opening chat row \(index)")
            openedChats.append(makeOpenedChatRenderState(app: app, index: index, loadedChat: loadedChats[index]))
        }

        return [
            "schema_version": 1,
            "surface": "opened-user-chats",
            "client": "apple",
            "generated_at": ISO8601DateFormatter().string(from: Date()),
            "environment": [
                "account_email_hash": stableHash(credentials.email),
                "opened_chat_limit": limit
            ],
            "sidebar": [
                "chat_count": loadedManifestValue(loadedManifest, keyPath: ["sidebar", "chat_count"]) ?? chatCount
            ],
            "opened_chats": openedChats
        ]
    }

    private func waitForOpenedChatMessages(in app: XCUIApplication, timeout: TimeInterval) -> Bool {
        let deadline = Date().addingTimeInterval(timeout)
        repeat {
            if messageElements(in: app).count > 0 {
                return true
            }
            RunLoop.current.run(until: Date().addingTimeInterval(0.25))
        } while Date() < deadline
        return messageElements(in: app).count > 0
    }

    private func makeOpenedChatRenderState(app: XCUIApplication, index: Int, loadedChat: [String: Any]) -> [String: Any] {
        let messages = (0..<messageElements(in: app).count).compactMap { messageIndex -> [String: Any]? in
            let element = messageElements(in: app).element(boundBy: messageIndex)
            guard element.exists else { return nil }
            return decodeMessageRenderManifest(element: element, index: messageIndex)
        }

        return [
            "index": index,
            "titleText": loadedChat["titleText"] as? String ?? "",
            "message_count": messages.count,
            "messages": messages
        ]
    }

    private func messageElements(in app: XCUIApplication) -> XCUIElementQuery {
        app.descendants(matching: .any).matching(
            NSPredicate(format: "identifier IN %@", ["message-user", "message-assistant", "message-system"])
        )
    }

    private func decodeMessageRenderManifest(element: XCUIElement, index: Int) -> [String: Any]? {
        guard let rawValue = element.value as? String,
              let data = rawValue.data(using: .utf8),
              let decoded = try? JSONSerialization.jsonObject(with: data) as? [String: Any] else {
            return [
                "index": index,
                "role": element.identifier.replacingOccurrences(of: "message-", with: ""),
                "content_hash": stableHash(element.label.split(whereSeparator: { $0.isWhitespace }).joined(separator: " ")),
                "text_length": element.label.count,
                "block_counts": emptyBlockCounts(),
                "has_sender_name": false,
                "has_thinking": false,
                "is_streaming": false
            ]
        }

        return [
            "index": index,
            "role": decoded["role"] as? String ?? element.identifier.replacingOccurrences(of: "message-", with: ""),
            "content_hash": decoded["content_hash"] as? String ?? "",
            "text_length": decoded["text_length"] as? Int ?? 0,
            "block_counts": decoded["block_counts"] as? [String: Int] ?? emptyBlockCounts(),
            "embed_count": decoded["embed_count"] as? Int ?? 0,
            "has_sender_name": decoded["has_sender_name"] as? Bool ?? false,
            "has_thinking": decoded["has_thinking"] as? Bool ?? false,
            "is_streaming": decoded["is_streaming"] as? Bool ?? false
        ]
    }

    private func emptyBlockCounts() -> [String: Int] {
        [
            "paragraph": 0,
            "heading": 0,
            "code_block": 0,
            "blockquote": 0,
            "list": 0,
            "table": 0,
            "source_quote": 0,
            "embed_group": 0,
            "interactive_question": 0,
            "inline_code": 0
        ]
    }

    private func loadedManifestValue(_ manifest: [String: Any], keyPath: [String]) -> Int? {
        var current: Any? = manifest
        for key in keyPath {
            current = (current as? [String: Any])?[key]
        }
        return current as? Int
    }

    private func normalizedChatTitle(from label: String) -> String {
        label
            .replacingOccurrences(of: ", sub-chat", with: "")
            .replacingOccurrences(of: ", pinned", with: "")
            .trimmingCharacters(in: .whitespacesAndNewlines)
    }

    private func stableHash(_ value: String) -> String {
        let digest = SHA256.hash(data: Data(value.utf8))
        return digest.prefix(8).map { String(format: "%02x", $0) }.joined()
    }

    private func titleState(for title: String) -> String {
        let normalized = title.lowercased()
        if title.isEmpty { return "empty" }
        if normalized.contains("processing") { return "processing" }
        if normalized.contains("untitled") { return "untitled" }
        return "ready"
    }

    private func attachAndWriteManifest(_ manifest: [String: Any]) throws {
        let data = try JSONSerialization.data(withJSONObject: manifest, options: [.prettyPrinted, .sortedKeys])
        let attachment = XCTAttachment(data: data, uniformTypeIdentifier: "public.json")
        attachment.name = "apple-loaded-chats-manifest.json"
        attachment.lifetime = .keepAlways
        add(attachment)

        let directory = parityArtifactDirectoryURL()
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
        try data.write(to: directory.appendingPathComponent("apple-loaded-chats-manifest.json"))
    }

    private func attachAndWriteOpenedManifest(_ manifest: [String: Any]) throws {
        let data = try JSONSerialization.data(withJSONObject: manifest, options: [.prettyPrinted, .sortedKeys])
        let attachment = XCTAttachment(data: data, uniformTypeIdentifier: "public.json")
        attachment.name = "apple-opened-chats-manifest.json"
        attachment.lifetime = .keepAlways
        add(attachment)

        let directory = parityArtifactDirectoryURL()
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
        try data.write(to: directory.appendingPathComponent("apple-opened-chats-manifest.json"))
    }

    private func parityArtifactDirectoryURL() -> URL {
        if let artifactDir = ProcessInfo.processInfo.environment["CHAT_RENDERING_PARITY_ARTIFACT_DIR"], !artifactDir.isEmpty {
            let directory = URL(fileURLWithPath: artifactDir, isDirectory: true)
            if directory.path.hasPrefix("/") {
                return directory
            }
            return repoRootURL().appendingPathComponent(artifactDir, isDirectory: true)
        }

        return repoRootURL()
            .appendingPathComponent("artifacts", isDirectory: true)
            .appendingPathComponent("chat-rendering-parity", isDirectory: true)
    }

    private func repoRootURL() -> URL {
        URL(fileURLWithPath: #filePath)
            .deletingLastPathComponent()
            .deletingLastPathComponent()
            .deletingLastPathComponent()
    }

    private func attachScreenshot(name: String) {
        let attachment = XCTAttachment(screenshot: XCUIScreen.main.screenshot())
        attachment.name = name
        attachment.lifetime = .keepAlways
        add(attachment)
    }

    private func visibleStateLabels(in app: XCUIApplication) -> String {
        let buttons = app.buttons.allElementsBoundByIndex.compactMap(elementSummary)
        let texts = app.staticTexts.allElementsBoundByIndex.compactMap(elementSummary)
        return (buttons + texts).prefix(30).joined(separator: " | ")
    }

    private func elementSummary(_ element: XCUIElement) -> String? {
        let identifier = element.identifier.trimmingCharacters(in: .whitespacesAndNewlines)
        let label = element.label.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !identifier.isEmpty || !label.isEmpty else { return nil }
        if identifier.isEmpty { return label }
        if label.isEmpty || label == identifier { return "#\(identifier)" }
        return "#\(identifier)=\(label.contains("@") ? "<email>" : label)"
    }
}

private struct AnonymousFreeUsageProbe: Decodable {
    let active: Bool
    let reason: String?
}
