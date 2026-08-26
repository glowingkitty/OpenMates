// Shared real-account UI-test helpers.
// Keeps credential loading, password + OTP login, TOTP generation, and stable
// chat selectors in one place for native live-dev chat tests. Credentials are
// read only from the XCTest process environment or the local live-test file
// written by scripts/apple_remote.py, and must never be logged or committed.

import CryptoKit
import XCTest

@MainActor
enum RealAccountUITestSupport {
    struct ProgressiveResponseProof {
        let firstChunkVisibleAt: Date
        let completedAt: Date
    }

    private static let streamingAccessibilitySettleInterval: TimeInterval = 20
    private static let proofResponseSettleInterval: TimeInterval = 35

    static func launchApp(
        preferPasswordLogin: Bool = true,
        disableAuthCache: Bool = false,
        extraArguments: [String] = []
    ) -> XCUIApplication {
        let app = XCUIApplication()
        var launchArguments: [String] = []
        if preferPasswordLogin {
            launchArguments.append("--ui-test-prefer-password-login")
        }
        if disableAuthCache {
            launchArguments.append("--ui-test-disable-auth-cache")
        }
        launchArguments.append(contentsOf: extraArguments)
        app.launchArguments = launchArguments
        app.launch()
        return app
    }

    static func installNotificationPermissionHandler(on testCase: XCTestCase) {
        testCase.addUIInterruptionMonitor(withDescription: "Notification Permission") { alert in
            let allowButtons = [
                alert.buttons["Allow"],
                alert.buttons["Allow Notifications"],
                alert.buttons["OK"]
            ]
            if let button = allowButtons.first(where: { $0.exists }) {
                button.tap()
                return true
            }
            return false
        }
    }

    static func logIn(app: XCUIApplication, credentials: RealAccountTestCredentials) {
        let loginSignupButton = app.buttons["header-login-signup-btn"]
        let loginTab = app.buttons["auth-login-tab"]
        if !loginTab.waitForExistence(timeout: 2),
           !loginSignupButton.waitForExistence(timeout: 3),
           let editor = waitForMessageEditor(in: app, timeout: 2),
           editor.isHittable {
            return
        }
        if !loginTab.exists {
            XCTAssertTrue(loginSignupButton.waitForExistence(timeout: 15))
            loginSignupButton.tap()
        }
        XCTAssertTrue(loginTab.waitForExistence(timeout: 10))
        loginTab.tap()

        let emailInput = app.textFields["email-input"]
        XCTAssertTrue(emailInput.waitForExistence(timeout: 10))
        guard focusForTextEntry(emailInput, in: app, identifier: "email-input") else { return }
        app.typeText(credentials.email)

        let continueButton = app.buttons["continue-button"]
        XCTAssertTrue(continueButton.waitForExistence(timeout: 10))
        continueButton.tap()

        let passwordInput = waitForPasswordInput(app: app)
        guard focusForTextEntry(passwordInput, in: app, identifier: "password-input") else { return }
        app.typeText(credentials.password)

        submitPasswordAndOtpIfNeeded(app: app, credentials: credentials)

        XCTAssertNotNil(waitForMessageEditor(in: app, timeout: 25))
    }

    static func sendWelcomePrompt(app: XCUIApplication, prompt: String) {
        openNewChatIfNeeded(app: app)
        guard let editor = waitForMessageEditor(in: app, timeout: 20) else {
            XCTFail("Expected message editor to appear")
            return
        }
        editor.coordinate(withNormalizedOffset: CGVector(dx: 0.5, dy: 0.5)).tap()
        app.typeText(prompt)

        let send = app.buttons["send-button"]
        XCTAssertTrue(send.waitForExistence(timeout: 5))
        send.tap()

        let userMessage = accessibilityElement(
            in: app,
            identifier: "message-user",
            labelContaining: prompt
        )
        XCTAssertTrue(
            userMessage.waitForExistence(timeout: 60),
            "Expected sent user message after tapping send. Visible UI: \(visibleStateLabels(in: app))"
        )
    }

    static func assertAssistantResponds(app: XCUIApplication, timeout: TimeInterval = 90) {
        let streamingBanner = accessibilityElement(in: app, identifier: "streaming-banner")
        let streamingIndicator = accessibilityElement(in: app, identifier: "streaming-indicator")
        let streamingStarted = streamingBanner.waitForExistence(timeout: 30)
            || streamingIndicator.waitForExistence(timeout: 2)

        let assistantMessage = app.otherElements.matching(identifier: "message-assistant").firstMatch
        XCTAssertTrue(
            streamingStarted || assistantMessage.waitForExistence(timeout: 10),
            "Expected assistant streaming or an assistant message to appear"
        )
        XCTAssertTrue(assistantMessage.waitForExistence(timeout: timeout))
        RunLoop.current.run(until: Date().addingTimeInterval(streamingAccessibilitySettleInterval))
        let completionMarker = app.otherElements["assistant-response-feedback"]
        XCTAssertTrue(
            completionMarker.waitForExistence(timeout: timeout),
            "Assistant response did not finish streaming"
        )

        let completedLabel = assistantMessage.label
        XCTAssertGreaterThan(completedLabel.count, 8)
        XCTAssertFalse(completedLabel.contains("app_skill_use"), "Assistant response exposed protocol metadata")
    }

    static func awaitAssistantResponseForProof(app: XCUIApplication, timeout: TimeInterval = 90) -> Date {
        let assistantMessage = app.otherElements.matching(identifier: "message-assistant").firstMatch
        XCTAssertTrue(
            assistantMessage.waitForExistence(timeout: timeout),
            "Expected an assistant response to appear"
        )
        let responseVisibleAt = Date()
        RunLoop.current.run(until: Date().addingTimeInterval(proofResponseSettleInterval))
        return responseVisibleAt
    }

    static func awaitProgressiveAssistantResponseForProof(
        app: XCUIApplication,
        timeout: TimeInterval = 90
    ) -> ProgressiveResponseProof {
        let assistantMessage = app.otherElements.matching(identifier: "message-assistant").firstMatch
        XCTAssertTrue(
            assistantMessage.waitForExistence(timeout: timeout),
            "Expected the first assistant response chunk to appear"
        )
        let firstChunkVisibleAt = Date()
        let firstChunkLabel = assistantMessage.label
        XCTAssertFalse(firstChunkLabel.isEmpty, "First assistant response chunk was empty")

        let completionMarker = app.otherElements["assistant-response-feedback"]
        let deadline = Date().addingTimeInterval(timeout)
        var observedLongerContent = false
        while Date() < deadline, !completionMarker.exists {
            if assistantMessage.label.count > firstChunkLabel.count {
                observedLongerContent = true
            }
            RunLoop.current.run(until: Date().addingTimeInterval(0.1))
        }
        XCTAssertTrue(completionMarker.exists, "Assistant response did not finish streaming")
        XCTAssertTrue(observedLongerContent, "Assistant response did not visibly grow after its first chunk")
        return ProgressiveResponseProof(firstChunkVisibleAt: firstChunkVisibleAt, completedAt: Date())
    }

    static func revealLatestAssistantResponse(app: XCUIApplication) {
        let assistantMessages = accessibilityElements(in: app, identifier: "message-assistant")
        let assistantTails = accessibilityElements(in: app, identifier: "message-assistant-tail")
        let history = accessibilityElement(in: app, identifier: "chat-history-container")
        let composer = accessibilityElement(in: app, identifier: "message-editor")
        let assistantMessage = assistantMessages.firstMatch
        let assistantTail = assistantTails.firstMatch
        let visibilityDeadline = Date().addingTimeInterval(10)
        var tailIsVisible = false
        repeat {
            let tailFrame = assistantTail.frame
            tailIsVisible = assistantTail.exists
                && !tailFrame.isEmpty
                && history.frame.intersects(tailFrame)
                && tailFrame.maxY <= composer.frame.minY + 1
            if !tailIsVisible {
                RunLoop.current.run(until: Date().addingTimeInterval(0.25))
            }
        } while !tailIsVisible && Date() < visibilityDeadline

        XCTAssertTrue(assistantMessage.exists, "Completed assistant response was missing from the proof chat")
        XCTAssertTrue(
            tailIsVisible,
            "Completed assistant response tail did not become visible without manual scrolling. "
                + "Tail: \(assistantTail.frame), history: \(history.frame), composer: \(composer.frame)"
        )
        XCTAssertLessThanOrEqual(
            assistantTail.frame.maxY,
            history.frame.maxY + 1,
            "Completed assistant response extended below the visible chat history"
        )
        XCTAssertLessThanOrEqual(
            assistantTail.frame.maxY,
            composer.frame.minY + 1,
            "Completed assistant response was covered by the composer"
        )
    }

    static func waitForMessageEditor(in app: XCUIApplication, timeout: TimeInterval) -> XCUIElement? {
        let editor = accessibilityElement(in: app, identifier: "message-editor")
        let deadline = Date().addingTimeInterval(timeout)
        repeat {
            if editor.exists {
                return editor
            }
            RunLoop.current.run(until: Date().addingTimeInterval(0.2))
        } while Date() < deadline
        return nil
    }

    static func accessibilityElement(in app: XCUIApplication, identifier: String) -> XCUIElement {
        accessibilityElements(in: app, identifier: identifier).firstMatch
    }

    private static func accessibilityElements(in app: XCUIApplication, identifier: String) -> XCUIElementQuery {
        app.descendants(matching: .any)
            .matching(NSPredicate(format: "identifier == %@", identifier))
    }

    static func accessibilityElement(
        in app: XCUIApplication,
        identifier: String,
        labelContaining label: String
    ) -> XCUIElement {
        app.descendants(matching: .any)
            .matching(NSPredicate(format: "identifier == %@ AND label CONTAINS[cd] %@", identifier, label))
            .firstMatch
    }

    private static func submitPasswordAndOtpIfNeeded(app: XCUIApplication, credentials: RealAccountTestCredentials) {
        let loginButton = app.buttons["login-button"]
        XCTAssertTrue(loginButton.waitForExistence(timeout: 10))
        loginButton.tap()

        let tfaInput = app.textFields["tfa-code-input"]
        let authenticationDeadline = Date().addingTimeInterval(15)
        repeat {
            if waitForMessageEditor(in: app, timeout: 0.2) != nil {
                return
            }
            if tfaInput.exists {
                break
            }
        } while Date() < authenticationDeadline
        if !tfaInput.exists {
            return
        }

        let offsets = [0, -1, 1, 0, -1]
        for (index, offset) in offsets.enumerated() {
            waitPastTotpBoundaryIfNeeded()
            guard focusForTextEntry(tfaInput, in: app, identifier: "tfa-code-input") else { return }
            clearOtpCode(in: tfaInput, app: app)
            app.typeText(TOTP.generate(secret: credentials.otpKey, windowOffset: offset))
            loginButton.tap()

            if waitForMessageEditor(in: app, timeout: 12) != nil {
                return
            }

            if index < offsets.count - 1 {
                sleep(UInt32(index < 2 ? 3 : 5))
            }
        }

        XCTFail("Login did not complete after OTP retries")
    }

    private static func openNewChatIfNeeded(app: XCUIApplication) {
        if waitForMessageEditor(in: app, timeout: 1) != nil {
            return
        }
        let newChatButton = accessibilityElement(in: app, identifier: "new-chat-button")
        guard newChatButton.waitForExistence(timeout: 2) else { return }
        newChatButton.tap()
        XCTAssertNotNil(waitForMessageEditor(in: app, timeout: 10))
    }

    private static func waitForPasswordInput(app: XCUIApplication) -> XCUIElement {
        let passwordInput = app.secureTextFields["password-input"]
        if passwordInput.waitForExistence(timeout: 30) {
            return passwordInput
        }

        XCTFail("Password step did not appear. Visible auth labels: \(visibleAuthLabels(in: app))")
        return passwordInput
    }

    private static func visibleAuthLabels(in app: XCUIApplication) -> String {
        let textLabels = app.staticTexts.allElementsBoundByIndex.compactMap(redactedLabel)
        let buttonLabels = app.buttons.allElementsBoundByIndex.compactMap(redactedLabel)
        return (textLabels + buttonLabels).prefix(12).joined(separator: " | ")
    }

    private static func visibleStateLabels(in app: XCUIApplication) -> String {
        let buttons = elementSummaries(app.buttons.allElementsBoundByIndex, prefix: "button")
        let textFields = elementSummaries(app.textFields.allElementsBoundByIndex, prefix: "textField")
        let staticTexts = elementSummaries(app.staticTexts.allElementsBoundByIndex, prefix: "text")
        return (buttons + textFields + staticTexts).prefix(30).joined(separator: " | ")
    }

    private static func elementSummaries(_ elements: [XCUIElement], prefix: String) -> [String] {
        elements.compactMap { element in
            let identifier = element.identifier.trimmingCharacters(in: .whitespacesAndNewlines)
            let label = redactedLabel(for: element) ?? ""
            guard !identifier.isEmpty || !label.isEmpty else { return nil }
            if identifier.isEmpty { return "\(prefix):\(label)" }
            if label.isEmpty || label == identifier { return "\(prefix)#\(identifier)" }
            return "\(prefix)#\(identifier)=\(label)"
        }
    }

    private static func redactedLabel(for element: XCUIElement) -> String? {
        let label = element.label.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !label.isEmpty else { return nil }
        return label.contains("@") ? "<email>" : label
    }

    private static func waitPastTotpBoundaryIfNeeded() {
        let secondsIntoWindow = Int(Date().timeIntervalSince1970) % 30
        guard secondsIntoWindow >= 25 else { return }
        sleep(UInt32(30 - secondsIntoWindow + 2))
    }

    private static func focusForTextEntry(
        _ element: XCUIElement,
        in app: XCUIApplication,
        identifier: String
    ) -> Bool {
        let focusedElement = app.descendants(matching: .any)
            .matching(NSPredicate(format: "identifier == %@ AND hasKeyboardFocus == true", identifier))
            .firstMatch
        for _ in 0..<3 {
            element.coordinate(withNormalizedOffset: CGVector(dx: 0.5, dy: 0.5)).tap()
            if focusedElement.waitForExistence(timeout: 1) {
                return true
            }
        }
        XCTFail("Expected \(identifier) to receive keyboard focus")
        return false
    }

    private static func clearOtpCode(in element: XCUIElement, app: XCUIApplication) {
        guard let value = element.value as? String else { return }
        let digitCount = value.filter(\.isNumber).count
        guard digitCount > 0 else { return }
        app.typeText(String(repeating: XCUIKeyboardKey.delete.rawValue, count: min(max(digitCount, 6), 12)))
    }
}

struct RealAccountTestCredentials {
    let email: String
    let password: String
    let otpKey: String

    static func fromEnvironment() throws -> RealAccountTestCredentials {
        let environment = ProcessInfo.processInfo.environment
        if let credentials = read(environment: environment, prefix: "OPENMATES_TEST_ACCOUNT") {
            return credentials
        }

        if let credentials = read(environment: readCredentialFile(), prefix: "OPENMATES_TEST_ACCOUNT") {
            return credentials
        }

        throw XCTSkip("Missing OPENMATES_TEST_ACCOUNT_EMAIL/PASSWORD/OTP_KEY")
    }

    static func fromReservedSlot(_ slot: Int) throws -> RealAccountTestCredentials {
        guard (14...20).contains(slot) else {
            throw XCTSkip("Reserved Apple account slot must be 14-20")
        }

        return try fromSlot(slot)
    }

    static func fromSlot(_ slot: Int) throws -> RealAccountTestCredentials {
        guard (1...20).contains(slot) else {
            throw XCTSkip("Apple test account slot must be 1-20")
        }

        let environment = ProcessInfo.processInfo.environment
        let prefix = "OPENMATES_TEST_ACCOUNT_\(slot)"
        if let credentials = read(environment: environment, prefix: prefix) {
            return credentials
        }

        if let credentials = read(environment: readCredentialFile(), prefix: prefix) {
            return credentials
        }

        throw XCTSkip("Missing credentials for slot \(slot)")
    }

    private static func read(environment: [String: String], prefix: String) -> RealAccountTestCredentials? {
        guard let email = environment["\(prefix)_EMAIL"], !email.isEmpty,
              let password = environment["\(prefix)_PASSWORD"], !password.isEmpty,
              let otpKey = environment["\(prefix)_OTP_KEY"], !otpKey.isEmpty else {
            return nil
        }
        return RealAccountTestCredentials(email: email, password: password, otpKey: otpKey)
    }

    private static func readCredentialFile() -> [String: String] {
        let sourceFileURL = URL(fileURLWithPath: #filePath)
        let credentialFileURL = sourceFileURL
            .deletingLastPathComponent()
            .deletingLastPathComponent()
            .appendingPathComponent(".openmates-live-test-account.env")
        guard let contents = try? String(contentsOf: credentialFileURL, encoding: .utf8) else {
            return [:]
        }

        var values: [String: String] = [:]
        for rawLine in contents.split(separator: "\n") {
            let line = rawLine.trimmingCharacters(in: .whitespacesAndNewlines)
            guard !line.isEmpty, !line.hasPrefix("#") else { continue }
            let parts = line.split(separator: "=", maxSplits: 1, omittingEmptySubsequences: false)
            guard parts.count == 2 else { continue }
            values[String(parts[0])] = String(parts[1])
        }
        return values
    }
}

private enum TOTP {
    static func generate(secret: String, windowOffset: Int = 0, date: Date = Date()) -> String {
        let key = SymmetricKey(data: base32Decode(secret))
        let counter = UInt64(Int64(floor(date.timeIntervalSince1970 / 30.0)) + Int64(windowOffset))
        var counterBigEndian = counter.bigEndian
        let counterData = Data(bytes: &counterBigEndian, count: MemoryLayout<UInt64>.size)
        let hash = HMAC<Insecure.SHA1>.authenticationCode(for: counterData, using: key)
        let bytes = Array(hash)
        let offset = Int(bytes[19] & 0x0f)
        let code = (UInt32(bytes[offset] & 0x7f) << 24)
            | (UInt32(bytes[offset + 1]) << 16)
            | (UInt32(bytes[offset + 2]) << 8)
            | UInt32(bytes[offset + 3])
        return String(format: "%06u", code % 1_000_000)
    }

    private static func base32Decode(_ value: String) -> Data {
        let alphabet = Array("ABCDEFGHIJKLMNOPQRSTUVWXYZ234567")
        let lookup = Dictionary(uniqueKeysWithValues: alphabet.enumerated().map { ($1, $0) })
        var bits = 0
        var bitBuffer = 0
        var output = Data()

        for character in value.uppercased() where character != "=" && character != " " {
            guard let index = lookup[character] else { continue }
            bitBuffer = (bitBuffer << 5) | index
            bits += 5
            if bits >= 8 {
                bits -= 8
                output.append(UInt8((bitBuffer >> bits) & 0xff))
            }
        }

        return output
    }
}
