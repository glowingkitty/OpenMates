// UI smoke coverage for the native chat-management testability surface.
// Uses public unauthenticated chats only, avoiding credentials, private chat
// records, share URLs, webhook secrets, or encrypted user content. Deeper
// live-account share/import/export parity remains covered by the executable spec.

import XCTest

@MainActor
final class ChatManagementSharingParityUITests: XCTestCase {
    private let fixtureShareURL = "https://app.dev.openmates.org/s/Abc123XY#testKey"
    private let fixtureSafariURL = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"

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
        app.terminate()

        let safari = XCUIApplication(bundleIdentifier: "com.apple.mobilesafari")
        openSafariURL(fixtureSafariURL, in: safari)

        let shareButton = safari.buttons["Share"]
        XCTAssertTrue(
            shareButton.waitForExistence(timeout: 15),
            "Expected Safari Share button before opening OpenMates extension. Visible UI: \(visibleStateLabels(in: safari))"
        )
        shareButton.tap()

        XCTAssertTrue(
            tapOpenMatesShareTarget(timeout: 15),
            "Expected OpenMates in the iOS share sheet. Visible Safari UI: \(visibleStateLabels(in: safari))"
        )

        let messageInput = safari.textViews["share-extension-message-input"]
        XCTAssertTrue(
            messageInput.waitForExistence(timeout: 20),
            "Expected OpenMates share extension message input. Visible UI: \(visibleStateLabels(in: safari))"
        )
        XCTAssertTrue(
            (messageInput.value as? String ?? messageInput.label).contains("youtube.com/watch"),
            "Expected the shared Safari URL to be prefilled in the editable message input."
        )

        messageInput.tap()
        messageInput.typeText("\nSummarize this video for me")

        let sendButton = safari.buttons["share-extension-send"]
        XCTAssertTrue(sendButton.waitForExistence(timeout: 5))
        sendButton.tap()

        XCTAssertTrue(
            waitForShareExtensionToClose(in: safari, timeout: 45),
            "Expected share extension to close after server-side processing starts. Status: \(safari.staticTexts["share-extension-status"].label)"
        )

        waitForSimulatedCompletionNotificationIfRequested()
        attachScreenshot(name: "Safari share to OpenMates extension completed")
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
        let staticTexts = elementSummaries(app.staticTexts.allElementsBoundByIndex, prefix: "text")
        return (buttons + textFields + staticTexts).prefix(30).joined(separator: " | ")
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
            safari.buttons["Share"].waitForExistence(timeout: 20),
            "Expected Safari to load the fixture URL and expose Share. Visible UI: \(visibleStateLabels(in: safari))"
        )
    }

    private func tapOpenMatesShareTarget(timeout: TimeInterval) -> Bool {
        let springboard = XCUIApplication(bundleIdentifier: "com.apple.springboard")
        let deadline = Date().addingTimeInterval(timeout)

        repeat {
            let target = springboard.descendants(matching: .any)
                .matching(NSPredicate(format: "label == %@ OR identifier == %@", "OpenMates", "OpenMates"))
                .firstMatch
            if target.exists {
                target.tap()
                return true
            }

            springboard.collectionViews.firstMatch.swipeLeft()
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
        elements.compactMap { element in
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
