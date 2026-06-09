// Real-account UI coverage for the native chat flow.
// Mirrors the core web chat-flow.spec.ts path: password + OTP login, create a
// new chat from the welcome composer, send the Kyoto/Osaka marker prompt, and
// verify that an assistant response starts and resolves in the real app.
// Credentials are read only from the test process environment and are never
// logged or committed.

import CryptoKit
import XCTest

@MainActor
final class ChatFlowRealAccountUITests: XCTestCase {
    private let markerPrompt = "Kyoto and Osaka quick tip test"
    private let assistantResponseTimeout: TimeInterval = 90

    override func setUpWithError() throws {
        continueAfterFailure = false
    }

    func testPasswordOtpLoginCreatesChatAndReceivesAssistantResponse() throws {
        let credentials = try TestCredentials.fromEnvironment()
        let app = XCUIApplication()
        app.launchArguments = ["--ui-test-prefer-password-login"]
        app.launch()

        logIn(app: app, credentials: credentials)
        sendWelcomePrompt(app: app)
        assertAssistantResponds(app: app)
    }

    private func logIn(app: XCUIApplication, credentials: TestCredentials) {
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
    }

    private func submitPasswordAndOtpIfNeeded(app: XCUIApplication, credentials: TestCredentials) {
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

    private func sendWelcomePrompt(app: XCUIApplication) {
        openNewChatIfNeeded(app: app)
        guard let editor = waitForMessageEditor(in: app, timeout: 20) else {
            XCTFail("Expected message editor to appear")
            return
        }
        editor.tap()
        editor.typeText(markerPrompt)

        let send = app.buttons["send-button"]
        XCTAssertTrue(send.waitForExistence(timeout: 5))
        send.tap()

        let userMessage = app.otherElements.matching(identifier: "chat-message-user")
            .containing(NSPredicate(format: "label CONTAINS %@", markerPrompt))
            .firstMatch
        XCTAssertTrue(userMessage.waitForExistence(timeout: 60))
    }

    private func openNewChatIfNeeded(app: XCUIApplication) {
        let newChatButton = app.buttons.matching(identifier: "new-chat-button").firstMatch
        guard newChatButton.waitForExistence(timeout: 2) else { return }
        newChatButton.tap()
        XCTAssertNotNil(waitForMessageEditor(in: app, timeout: 10))
    }

    private func assertAssistantResponds(app: XCUIApplication) {
        let streamingStarted = app.otherElements["streaming-banner"].waitForExistence(timeout: 30)
            || app.otherElements["streaming-indicator"].waitForExistence(timeout: 2)

        let assistantMessage = app.otherElements.matching(identifier: "chat-message-assistant").firstMatch
        XCTAssertTrue(
            streamingStarted || assistantMessage.waitForExistence(timeout: 10),
            "Expected assistant streaming or an assistant message to appear"
        )
        XCTAssertTrue(assistantMessage.waitForExistence(timeout: assistantResponseTimeout))
        XCTAssertGreaterThan(assistantMessage.label.count, 8)
    }

    private func messageEditor(in app: XCUIApplication) -> XCUIElement {
        messageEditorCandidates(in: app).first { $0.exists }
            ?? app.textFields.matching(identifier: "message-editor").firstMatch
    }

    private func waitForMessageEditor(in app: XCUIApplication, timeout: TimeInterval) -> XCUIElement? {
        let deadline = Date().addingTimeInterval(timeout)
        repeat {
            if let editor = messageEditorCandidates(in: app).first(where: { $0.exists }) {
                return editor
            }
            RunLoop.current.run(until: Date().addingTimeInterval(0.2))
        } while Date() < deadline
        return nil
    }

    private func messageEditorCandidates(in app: XCUIApplication) -> [XCUIElement] {
        [
            app.textFields.matching(identifier: "message-editor").firstMatch,
            app.textViews.matching(identifier: "message-editor").firstMatch,
        ]
    }

    private func waitForPasswordInput(app: XCUIApplication) -> XCUIElement {
        let passwordInput = app.secureTextFields["password-input"]
        if passwordInput.waitForExistence(timeout: 30) {
            return passwordInput
        }

        XCTFail("Password step did not appear. Visible auth labels: \(visibleAuthLabels(in: app))")
        return passwordInput
    }

    private func visibleAuthLabels(in app: XCUIApplication) -> String {
        let textLabels = app.staticTexts.allElementsBoundByIndex.compactMap(redactedLabel)
        let buttonLabels = app.buttons.allElementsBoundByIndex.compactMap(redactedLabel)
        return (textLabels + buttonLabels).prefix(12).joined(separator: " | ")
    }

    private func redactedLabel(for element: XCUIElement) -> String? {
        let label = element.label.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !label.isEmpty else { return nil }
        return label.contains("@") ? "<email>" : label
    }

    private func waitPastTotpBoundaryIfNeeded() {
        let secondsIntoWindow = Int(Date().timeIntervalSince1970) % 30
        guard secondsIntoWindow >= 25 else { return }
        sleep(UInt32(30 - secondsIntoWindow + 2))
    }

    private func clearText(in element: XCUIElement) {
        guard let value = element.value as? String, !value.isEmpty else { return }
        element.press(forDuration: 1.0)
        let selectAll = XCUIApplication().menuItems["Select All"]
        if selectAll.waitForExistence(timeout: 2) {
            selectAll.tap()
            element.typeText(XCUIKeyboardKey.delete.rawValue)
        } else {
            element.typeText(String(repeating: XCUIKeyboardKey.delete.rawValue, count: value.count))
        }
    }

    private func clearOtpCode(in element: XCUIElement) {
        guard let value = element.value as? String else { return }
        let digitCount = value.filter(\.isNumber).count
        guard digitCount > 0 else { return }
        element.typeText(String(repeating: XCUIKeyboardKey.delete.rawValue, count: min(max(digitCount, 6), 12)))
    }
}

private struct TestCredentials {
    let email: String
    let password: String
    let otpKey: String

    static func fromEnvironment() throws -> TestCredentials {
        let environment = ProcessInfo.processInfo.environment
        guard let email = environment["OPENMATES_TEST_ACCOUNT_EMAIL"], !email.isEmpty,
              let password = environment["OPENMATES_TEST_ACCOUNT_PASSWORD"], !password.isEmpty,
              let otpKey = environment["OPENMATES_TEST_ACCOUNT_OTP_KEY"], !otpKey.isEmpty
        else {
            throw XCTSkip("Missing OPENMATES_TEST_ACCOUNT_EMAIL/PASSWORD/OTP_KEY")
        }
        return TestCredentials(email: email, password: password, otpKey: otpKey)
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
