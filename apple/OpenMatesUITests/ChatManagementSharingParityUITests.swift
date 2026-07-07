// UI smoke coverage for the native chat-management testability surface.
// Uses public unauthenticated chats only, avoiding credentials, private chat
// records, share URLs, webhook secrets, or encrypted user content. Deeper
// live-account share/import/export parity remains covered by the executable spec.

import XCTest

@MainActor
final class ChatManagementSharingParityUITests: XCTestCase {
    private let fixtureShareURL = "https://app.dev.openmates.org/s/Abc123XY#testKey"
    private let fixtureSafariURL = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
    private let recentChatSeedPrompt = "Share extension recent chat destination seed"

    override func setUpWithError() throws {
        continueAfterFailure = false
    }

    func testUnauthenticatedChatListExposesManagementIdentifiers() throws {
        let app = XCUIApplication()
        app.launchArguments = ["--ui-test-shell-metrics"]
        app.launchEnvironment["UI_TEST_SHELL_METRICS"] = "1"
        app.launch()

        let chatRow = app.descendants(matching: .any)["chat-item-wrapper"]
        if !chatRow.waitForExistence(timeout: 5) {
            let sidebarToggle = app.buttons["sidebar-toggle"]
            if sidebarToggle.waitForExistence(timeout: 3) {
                sidebarToggle.tap()
            }
        }

        XCTAssertTrue(
            chatRow.waitForExistence(timeout: 12),
            "Expected public chat row identifier. Visible UI: \(visibleStateLabels(in: app))"
        )
        XCTAssertFalse(app.tables.firstMatch.exists, "Chat management UI must not render default List/table chrome")

        attachScreenshot(name: "Public chat management identifiers")
    }

    func testChatSharePreviewGeneratesLinkQRCodeAndOpensSystemShareSheet() throws {
        let app = XCUIApplication()
        app.launchArguments = ["--dev-preview", "chat-share"]
        app.launchEnvironment["DEV_PREVIEW"] = "chat-share"
        app.launchEnvironment["UI_TEST_CHAT_SHARE_URL"] = fixtureShareURL
        app.launch()

        let generateButton = app.buttons["share-generate-link"]
        XCTAssertTrue(
            generateButton.waitForExistence(timeout: 10),
            "Expected native chat share controls. Visible UI: \(visibleStateLabels(in: app))"
        )
        generateButton.tap()

        let generationStatus = app.staticTexts["share-generation-status"]
        if generationStatus.waitForExistence(timeout: 0.5) {
            XCTAssertEqual(generationStatus.label, "Sharing chat...")
        }

        let generatedLink = app.staticTexts["share-short-link-url"]
        XCTAssertTrue(generatedLink.waitForExistence(timeout: 5))
        XCTAssertEqual(generatedLink.label, fixtureShareURL)
        XCTAssertTrue(accessibilityElement(in: app, identifier: "share-qr-code").waitForExistence(timeout: 5))

        let nativeShareButton = app.buttons["share-native-sheet-button"]
        XCTAssertTrue(nativeShareButton.waitForExistence(timeout: 5))
        nativeShareButton.tap()

        XCTAssertTrue(
            waitForSystemShareSheet(in: app, timeout: 8),
            "Expected iOS system share sheet after tapping native share button."
        )
        attachScreenshot(name: "Native chat share sheet")
    }

    func testSafariShareSheetSendsURLThroughOpenMatesExtension() throws {
        let credentials = try RealAccountTestCredentials.fromEnvironment()
        RealAccountUITestSupport.installNotificationPermissionHandler(on: self)

        let app = RealAccountUITestSupport.launchApp()
        RealAccountUITestSupport.logIn(app: app, credentials: credentials)
        RealAccountUITestSupport.sendWelcomePrompt(app: app, prompt: recentChatSeedPrompt)
        app.terminate()

        let safari = XCUIApplication(bundleIdentifier: "com.apple.mobilesafari")
        openSafariURL(fixtureSafariURL, in: safari)

        tapSafariShareButton(in: safari)

        XCTAssertTrue(
            tapOpenMatesShareTarget(timeout: 15),
            "Expected OpenMates in the iOS share sheet. Visible Safari UI: \(visibleStateLabels(in: safari))"
        )

        let shareHosts = shareExtensionHosts(in: safari)
        let messageInput = waitForShareExtensionElement(
            identifier: "share-extension-message-input",
            in: shareHosts,
            timeout: 20
        )
        XCTAssertTrue(
            messageInput?.exists == true,
            "Expected OpenMates share extension message input. Visible UI: \(visibleStateLabels(in: safari))"
        )
        XCTAssertTrue(
            (messageInput?.value as? String ?? messageInput?.label ?? "").contains("youtube.com/watch"),
            "Expected the shared Safari URL to be prefilled in the editable message input."
        )

        let recentChat = waitForShareExtensionElement(
            identifier: "share-extension-chat-destination",
            in: shareHosts,
            timeout: 20
        )
        XCTAssertTrue(
            recentChat?.exists == true,
            "Expected at least one selectable recent chat destination. Status: \(safari.staticTexts["share-extension-status"].label)"
        )
        recentChat?.tap()
        XCTAssertEqual(recentChat?.value as? String, "Selected")

        messageInput?.tap()
        messageInput?.typeText("\nSummarize this video for me")

        let sendButton = waitForShareExtensionElement(identifier: "share-extension-send", in: shareHosts, timeout: 5)
        XCTAssertTrue(sendButton?.exists == true)
        sendButton?.tap()

        XCTAssertTrue(
            waitForShareExtensionToClose(in: safari, timeout: 45),
            "Expected share extension to close after server-side processing starts. Status: \(safari.staticTexts["share-extension-status"].label)"
        )

        waitForSimulatedCompletionNotificationIfRequested()
        attachScreenshot(name: "Safari share to OpenMates extension completed")
    }

    func testSafariShareSheetShowsUnifiedOpenMatesComposer() throws {
        let safari = XCUIApplication(bundleIdentifier: "com.apple.mobilesafari")
        openSafariURL(fixtureSafariURL, in: safari)

        tapSafariShareButton(in: safari)

        XCTAssertTrue(
            tapOpenMatesShareTarget(timeout: 15),
            "Expected OpenMates in the iOS share sheet. Visible Safari UI: \(visibleStateLabels(in: safari))"
        )

        let shareHosts = shareExtensionHosts(in: safari)
        XCTAssertNotNil(
            waitForShareExtensionElement(identifier: "share-extension-root", in: shareHosts, timeout: 20),
            "Expected OpenMates share extension root. Visible UI: \(visibleStateLabels(in: safari))"
        )
        XCTAssertNotNil(
            waitForShareExtensionElement(identifier: "message-composer", in: shareHosts, timeout: 5),
            "Expected share extension to expose the unified message composer container."
        )
        XCTAssertNotNil(
            waitForShareExtensionElement(identifier: "message-field", in: shareHosts, timeout: 5),
            "Expected share extension to expose the unified message field."
        )

        let messageInput = waitForShareExtensionElement(
            identifier: "share-extension-message-input",
            in: shareHosts,
            timeout: 5
        )
        XCTAssertTrue(
            messageInput?.exists == true,
            "Expected OpenMates share extension message input. Visible UI: \(visibleStateLabels(in: safari))"
        )
        XCTAssertTrue(
            (messageInput?.value as? String ?? messageInput?.label ?? "").contains("youtube.com/watch"),
            "Expected the shared Safari URL to be prefilled in the editable message input."
        )
        XCTAssertNotNil(waitForShareExtensionElement(identifier: "share-extension-send", in: shareHosts, timeout: 5))

        attachScreenshot(name: "Safari share extension unified composer")
    }

    private func attachScreenshot(name: String) {
        let attachment = XCTAttachment(screenshot: XCUIScreen.main.screenshot())
        attachment.name = name
        attachment.lifetime = .keepAlways
        add(attachment)
    }

    private func visibleStateLabels(in app: XCUIApplication) -> String {
        let buttons = elementSummaries(app.buttons.allElementsBoundByIndex, prefix: "button")
        let textFields = elementSummaries(app.textFields.allElementsBoundByIndex, prefix: "textField")
        let textViews = elementSummaries(app.textViews.allElementsBoundByIndex, prefix: "textView")
        let staticTexts = elementSummaries(app.staticTexts.allElementsBoundByIndex, prefix: "text")
        return (buttons + textFields + textViews + staticTexts).prefix(30).joined(separator: " | ")
    }

    private func shareExtensionHosts(in safari: XCUIApplication) -> [XCUIApplication] {
        [safari, XCUIApplication(bundleIdentifier: "org.openmates.app.share")]
    }

    private func waitForShareExtensionElement(
        identifier: String,
        in hosts: [XCUIApplication],
        timeout: TimeInterval
    ) -> XCUIElement? {
        let deadline = Date().addingTimeInterval(timeout)
        repeat {
            for host in hosts {
                let element = host.descendants(matching: .any)[identifier]
                if element.exists { return element }
            }
            RunLoop.current.run(until: Date().addingTimeInterval(0.2))
        } while Date() < deadline
        return nil
    }

    private func waitForSystemShareSheet(in app: XCUIApplication, timeout: TimeInterval) -> Bool {
        let deadline = Date().addingTimeInterval(timeout)
        repeat {
            if app.sheets.firstMatch.exists { return true }
            if app.buttons["Copy"].exists || app.buttons["Add to Reading List"].exists { return true }
            if app.staticTexts["cellTitleLabel"].exists { return true }
            if app.collectionViews.firstMatch.exists { return true }
            if app.otherElements.matching(NSPredicate(format: "label CONTAINS[c] %@", "Activity")).firstMatch.exists {
                return true
            }
            RunLoop.current.run(until: Date().addingTimeInterval(0.2))
        } while Date() < deadline
        return false
    }

    private func openSafariURL(_ url: String, in safari: XCUIApplication) {
        safari.launch()

        let continueButton = safari.buttons["Continue"]
        if continueButton.waitForExistence(timeout: 2) {
            continueButton.tap()
        }

        if safariAlreadyShowsFixturePage(safari) {
            XCTAssertTrue(
                waitForSafariShareSurface(in: safari, timeout: 20),
                "Expected Safari to expose a share surface for the existing fixture page. Visible UI: \(visibleStateLabels(in: safari))"
            )
            return
        }

        let addressCandidates = [
            safari.textFields["Address"],
            safari.textFields["Search or enter website name"],
            safari.textFields["TabBarItemTitle"],
            safari.textFields.firstMatch,
        ]
        let addressField = addressCandidates.first { $0.waitForExistence(timeout: 3) } ?? safari.textFields.firstMatch
        XCTAssertTrue(
            addressField.waitForExistence(timeout: 10),
            "Expected Safari address field. Visible UI: \(visibleStateLabels(in: safari))"
        )
        addressField.tap()
        addressField.typeText(url)
        addressField.typeText("\n")

        XCTAssertTrue(
            waitForSafariShareSurface(in: safari, timeout: 20),
            "Expected Safari to load the fixture URL and expose a share surface. Visible UI: \(visibleStateLabels(in: safari))"
        )
    }

    private func safariAlreadyShowsFixturePage(_ safari: XCUIApplication) -> Bool {
        let addressValues = safari.textFields.allElementsBoundByIndex.map {
            String(describing: $0.value ?? $0.label).lowercased()
        }
        return addressValues.contains { $0.contains("youtube.com") || $0.contains("youtu.be") }
    }

    private func tapSafariShareButton(in safari: XCUIApplication) {
        let directShareButton = safari.buttons["Share"]
        if directShareButton.waitForExistence(timeout: 3) {
            directShareButton.tap()
            return
        }

        let moreButton = safari.buttons["MoreMenuButton"]
        XCTAssertTrue(
            moreButton.waitForExistence(timeout: 10),
            "Expected Safari Share or More button. Visible UI: \(visibleStateLabels(in: safari))"
        )
        moreButton.tap()

        XCTAssertTrue(
            directShareButton.waitForExistence(timeout: 5),
            "Expected Share action inside Safari More menu. Visible UI: \(visibleStateLabels(in: safari))"
        )
        directShareButton.tap()
    }

    private func waitForSafariShareSurface(in safari: XCUIApplication, timeout: TimeInterval) -> Bool {
        let deadline = Date().addingTimeInterval(timeout)
        repeat {
            if safari.buttons["Share"].exists || safari.buttons["MoreMenuButton"].exists {
                return true
            }
            RunLoop.current.run(until: Date().addingTimeInterval(0.2))
        } while Date() < deadline
        return false
    }

    private func tapOpenMatesShareTarget(timeout: TimeInterval) -> Bool {
        let shareSheetHosts = [
            XCUIApplication(bundleIdentifier: "com.apple.springboard"),
            XCUIApplication(bundleIdentifier: "com.apple.mobilesafari")
        ]
        let deadline = Date().addingTimeInterval(timeout)

        repeat {
            for host in shareSheetHosts {
                let target = host.descendants(matching: .any)
                    .matching(NSPredicate(format: "label == %@ OR identifier == %@", "OpenMates", "OpenMates"))
                    .firstMatch
                if target.exists {
                    target.tap()
                    return true
                }
            }

            for host in shareSheetHosts {
                let carousel = host.collectionViews.firstMatch
                if carousel.exists {
                    carousel.swipeLeft()
                    break
                }
            }
            RunLoop.current.run(until: Date().addingTimeInterval(0.4))
        } while Date() < deadline

        return false
    }

    private func waitForShareExtensionToClose(in app: XCUIApplication, timeout: TimeInterval) -> Bool {
        let root = app.descendants(matching: .any)["share-extension-root"]
        let deadline = Date().addingTimeInterval(timeout)
        repeat {
            if !root.exists { return true }
            if app.staticTexts["share-extension-status"].label.lowercased().contains("error") { return false }
            RunLoop.current.run(until: Date().addingTimeInterval(0.5))
        } while Date() < deadline
        return !root.exists
    }

    private func waitForSimulatedCompletionNotificationIfRequested() {
        guard ProcessInfo.processInfo.environment["OPENMATES_SHARE_WORKFLOW_EXPECT_NOTIFICATION"] == "1" else { return }

        let springboard = XCUIApplication(bundleIdentifier: "com.apple.springboard")
        let notificationTitle = springboard.staticTexts["OpenMates"]
        let notificationBody = springboard.staticTexts["New message received"]

        XCTAssertTrue(
            notificationTitle.waitForExistence(timeout: 120),
            "Expected simulated OpenMates completion notification after share flow."
        )
        XCTAssertTrue(notificationBody.waitForExistence(timeout: 5))
    }

    private func accessibilityElement(in app: XCUIApplication, identifier: String) -> XCUIElement {
        app.descendants(matching: .any)
            .matching(NSPredicate(format: "identifier == %@", identifier))
            .firstMatch
    }

    private func elementSummaries(_ elements: [XCUIElement], prefix: String) -> [String] {
        elements.prefix(4).compactMap { element in
            guard element.exists else { return nil }
            let identifier = element.identifier.trimmingCharacters(in: .whitespacesAndNewlines)
            let label = element.label.trimmingCharacters(in: .whitespacesAndNewlines)
            guard !identifier.isEmpty || !label.isEmpty else { return nil }
            if identifier.isEmpty { return "\(prefix):\(redact(label))" }
            if label.isEmpty || label == identifier { return "\(prefix)#\(identifier)" }
            return "\(prefix)#\(identifier)=\(redact(label))"
        }
    }

    private func redact(_ value: String) -> String {
        value.contains("@") ? "<email>" : value
    }
}
