// Shared real-account UI-test helpers.
// Keeps credential loading, password + OTP login, TOTP generation, and stable
// chat selectors in one place for native live-dev chat tests. Credentials are
// read only from the XCTest process environment and must never be logged or
// committed.

import CryptoKit
import XCTest

@MainActor
enum RealAccountUITestSupport {
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
        let loginSignupButton = app.buttons["login-signup-button"]
        if !loginSignupButton.waitForExistence(timeout: 6), waitForMessageEditor(in: app, timeout: 2) != nil {
            return
        }

        XCTAssertTrue(loginSignupButton.waitForExistence(timeout: 15))
        loginSignupButton.tap()

        let loginTab = app.buttons["auth-login-tab"]
        XCTAssertTrue(loginTab.waitForExistence(timeout: 10))
        loginTab.tap()

        let emailInput = app.textFields["email-input"]
        XCTAssertTrue(emailInput.waitForExistence(timeout: 10))
        emailInput.tap()
        emailInput.typeText(credentials.email)

        let continueButton = app.buttons["continue-button"]
        XCTAssertTrue(continueButton.waitForExistence(timeout: 10))
        continueButton.tap()

        let passwordInput = waitForPasswordInput(app: app)
        passwordInput.tap()
        passwordInput.typeText(credentials.password)

        submitPasswordAndOtpIfNeeded(app: app, credentials: credentials)

        XCTAssertNotNil(waitForMessageEditor(in: app, timeout: 25))
        app.tap()
    }

    static func sendWelcomePrompt(app: XCUIApplication, prompt: String) {
        openNewChatIfNeeded(app: app)
        guard let editor = waitForMessageEditor(in: app, timeout: 20) else {
            XCTFail("Expected message editor to appear")
            return
        }
        editor.tap()
        editor.typeText(prompt)

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
        let streamingStarted = app.otherElements["streaming-banner"].waitForExistence(timeout: 30)
            || app.otherElements["streaming-indicator"].waitForExistence(timeout: 2)

        let assistantMessage = accessibilityElement(in: app, identifier: "message-assistant")
        XCTAssertTrue(
            streamingStarted || assistantMessage.waitForExistence(timeout: 10),
            "Expected assistant streaming or an assistant message to appear"
        )
        XCTAssertTrue(assistantMessage.waitForExistence(timeout: timeout))
        XCTAssertGreaterThan(assistantMessage.label.count, 8)
    }

    static func waitForMessageEditor(in app: XCUIApplication, timeout: TimeInterval) -> XCUIElement? {
        let deadline = Date().addingTimeInterval(timeout)
        repeat {
            if let editor = messageEditorCandidates(in: app).first(where: { $0.exists }) {
                return editor
            }
            RunLoop.current.run(until: Date().addingTimeInterval(0.2))
        } while Date() < deadline
        return nil
    }

    static func accessibilityElement(in app: XCUIApplication, identifier: String) -> XCUIElement {
        app.descendants(matching: .any)
            .matching(NSPredicate(format: "identifier == %@", identifier))
            .firstMatch
    }

    static func accessibilityElement(
        in app: XCUIApplication,
        identifier: String,
        labelContaining label: String
    ) -> XCUIElement {
        app.descendants(matching: .any)
            .matching(NSPredicate(format: "identifier == %@ AND label CONTAINS %@", identifier, label))
            .firstMatch
    }

    private static func submitPasswordAndOtpIfNeeded(app: XCUIApplication, credentials: RealAccountTestCredentials) {
        let loginButton = app.buttons["login-button"]
        XCTAssertTrue(loginButton.waitForExistence(timeout: 10))
        loginButton.tap()

        let tfaInput = app.textFields["tfa-code-input"]
        if !tfaInput.waitForExistence(timeout: 15) {
            return
        }

        let offsets = [0, -1, 1, 0, -1]
        for (index, offset) in offsets.enumerated() {
            waitPastTotpBoundaryIfNeeded()
            tfaInput.tap()
            clearOtpCode(in: tfaInput)
            tfaInput.typeText(TOTP.generate(secret: credentials.otpKey, windowOffset: offset))
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
        let newChatButton = accessibilityElement(in: app, identifier: "new-chat-button")
        guard newChatButton.waitForExistence(timeout: 2) else { return }
        newChatButton.tap()
        XCTAssertNotNil(waitForMessageEditor(in: app, timeout: 10))
    }

    private static func messageEditorCandidates(in app: XCUIApplication) -> [XCUIElement] {
        [
            app.textFields.matching(identifier: "message-editor").firstMatch,
            app.textViews.matching(identifier: "message-editor").firstMatch,
        ]
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

    private static func clearOtpCode(in element: XCUIElement) {
        guard let value = element.value as? String else { return }
        let digitCount = value.filter(\.isNumber).count
        guard digitCount > 0 else { return }
        element.typeText(String(repeating: XCUIKeyboardKey.delete.rawValue, count: min(max(digitCount, 6), 12)))
    }
}

struct RealAccountTestCredentials {
    let email: String
    let password: String
    let otpKey: String

    static func fromEnvironment() throws -> RealAccountTestCredentials {
        let environment = ProcessInfo.processInfo.environment
        guard let email = environment["OPENMATES_TEST_ACCOUNT_EMAIL"], !email.isEmpty,
              let password = environment["OPENMATES_TEST_ACCOUNT_PASSWORD"], !password.isEmpty,
              let otpKey = environment["OPENMATES_TEST_ACCOUNT_OTP_KEY"], !otpKey.isEmpty
        else {
            throw XCTSkip("Missing OPENMATES_TEST_ACCOUNT_EMAIL/PASSWORD/OTP_KEY")
        }
        return RealAccountTestCredentials(email: email, password: password, otpKey: otpKey)
    }

    static func fromReservedSlot(_ slot: Int) throws -> RealAccountTestCredentials {
        guard (14...20).contains(slot) else {
            throw XCTSkip("Reserved Apple account slot must be 14-20")
        }

        let environment = ProcessInfo.processInfo.environment
        let prefix = "OPENMATES_TEST_ACCOUNT_\(slot)"
        guard let email = environment["\(prefix)_EMAIL"], !email.isEmpty,
              let password = environment["\(prefix)_PASSWORD"], !password.isEmpty,
              let otpKey = environment["\(prefix)_OTP_KEY"], !otpKey.isEmpty
        else {
            throw XCTSkip("Missing reserved credentials for slot \(slot)")
        }
        return RealAccountTestCredentials(email: email, password: password, otpKey: otpKey)
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
