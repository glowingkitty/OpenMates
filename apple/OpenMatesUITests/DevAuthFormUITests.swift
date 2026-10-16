// Shared forms, deterministic local transport. These assertions cover state and
// interaction contracts, not account security or exact rendered visual approval.
// Web references: Basics.svelte; PasswordAndTfaOtp.svelte; signup-flow-passkey.spec.ts;
// passkey-login-alternatives.spec.ts; backup-code-login-flow.spec.ts.
import XCTest
import UIKit

@MainActor final class DevAuthFormUITests: XCTestCase {
    override func setUpWithError() throws { continueAfterFailure = false }
    override func tearDown() async throws {
        // XCTest's stop-on-failure can exit before a test's Swift defer runs.
        // The XCTest lifecycle override is nonisolated even on this class.
        // Create and use UI objects on MainActor without transferring self.
        await MainActor.run {
            XCUIDevice.shared.orientation = .portrait
            let app = XCUIApplication()
            if app.state == .runningForeground {
                Self.waitForWindowOrientation(landscape: false, app: app)
            }
        }
        try await super.tearDown()
    }

    // contract-test: supporting surface=gui.apple assertions=auth.surface.first-party-boundary
    func testMobileHeaderHasReachableDemoAndTabsForBothEntryForms() {
        let app = launch("login", "mobile-header")
        let demo = app.buttons["auth-demo-back"]
        let login = app.buttons["auth-login-tab"]
        let signup = app.buttons["auth-signup-tab"]
        XCTAssertTrue(demo.waitForExistence(timeout: 5))
        XCTAssertTrue(demo.isHittable)
        XCTAssertTrue(login.isHittable)
        XCTAssertTrue(signup.isHittable)
        XCTAssertTrue(login.isSelected)
        XCTAssertFalse(signup.isSelected)
        XCTAssertGreaterThanOrEqual(demo.frame.height, 44)
        XCTAssertEqual(login.frame.height, 44, accuracy: 1)
        XCTAssertEqual(signup.frame.height, login.frame.height, accuracy: 1)
        XCTAssertEqual(signup.frame.minY, login.frame.minY, accuracy: 1)
        // The98px web grid plus5px stagger clearance and net-5px lower
        // margin fits above Demo, with no added mobile top spacer.
        let header = app.descendants(matching: .any)["auth-entry-header"]
        XCTAssertTrue(header.exists)
        // ScrollView bounds include the unsafe top inset on iPhone. Measure
        // against the actual production header container's content origin.
        XCTAssertEqual(demo.frame.minY - header.frame.minY, 98, accuracy: 1)
        XCTAssertEqual(login.frame.minY - demo.frame.minY, 52, accuracy: 1)
        attachScreenshot("Mobile login header app gradients white glyphs and full staggered tiles")
        assertVisibleAppTiles(in: CGRect(x: header.frame.minX, y: header.frame.minY,
            width: header.frame.width, height: demo.frame.minY - header.frame.minY), app: app)
        XCTAssertTrue(app.staticTexts["login-heading"].exists)

        // Manual AX and physical touches both work. Read the visible button's
        // frame immediately before one physical touch, rather than letting
        // element.tap() derive a hit point from its earlier snapshot.
        let beforeSignupScreenshot = XCUIScreen.main.screenshot()
        let beforeSignupHierarchy = app.debugDescription
        let signupFrame = signup.frame
        let window = app.windows.firstMatch
        let windowFrame = window.frame
        window.coordinate(withNormalizedOffset: .zero).withOffset(CGVector(
            dx: signupFrame.midX - windowFrame.minX,
            dy: signupFrame.midY - windowFrame.minY)).tap()
        waitForSignupSelection(app) {
            let before = XCTAttachment(screenshot: beforeSignupScreenshot)
            before.name = "Mobile signup touch before"
            before.lifetime = .keepAlways
            add(before)
            let hierarchy = XCTAttachment(string: "touchFrame=\(signupFrame);window=\(windowFrame)\n" +
                beforeSignupHierarchy)
            hierarchy.name = "Mobile signup touch before AX"
            hierarchy.lifetime = .keepAlways
            add(hierarchy)
            attachScreenshot("Mobile signup touch after failed transition")
            let after = XCTAttachment(string: app.debugDescription)
            after.name = "Mobile signup touch after AX"
            after.lifetime = .keepAlways
            add(after)
        }
        XCTAssertTrue(signup.isSelected)
        XCTAssertFalse(login.isSelected)
        XCTAssertFalse(app.staticTexts["login-heading"].exists)
        XCTAssertFalse(app.buttons["signup-submit"].isEnabled)
        attachScreenshot("Mobile signup header shares complete app grid and navigation")

        demo.tap()
        XCTAssertEqual(app.staticTexts["fixture-auth-destination"].label, "demo")
        tap(app.buttons["fixture-auth-return"], in: app)
        XCTAssertTrue(signup.isSelected)
        login.tap()
        XCTAssertTrue(app.staticTexts["login-heading"].waitForExistence(timeout: 5))
        XCTAssertFalse(app.buttons["continue-button"].isEnabled)
    }

    // contract-test: supporting surface=gui.apple assertions=auth.surface.first-party-boundary
    func testWideLoginAndSignupKeepCenteredFormBetweenVisibleAppGrids() {
        let app = launch("login", "wide-header", landscape: true)
        defer {
            XCUIDevice.shared.orientation = .portrait
            Self.waitForWindowOrientation(landscape: false, app: app)
        }
        let header = app.descendants(matching: .any)["auth-entry-header"]
        let viewport = app.descendants(matching: .any)["dev-component-preview-bounds"]
        XCTAssertTrue(header.waitForExistence(timeout: 5))
        XCTAssertTrue(viewport.exists)
        XCTAssertGreaterThan(viewport.frame.width, 600, "Run wide coverage in landscape or on iPad")
        func assertWideLayout(_ name: String) {
            XCTAssertEqual(header.frame.width, 440, accuracy: 1)
            XCTAssertEqual(header.frame.midX, viewport.frame.midX, accuracy: 1)
            let demo = app.buttons["auth-demo-back"]
            XCTAssertTrue(demo.isHittable)
            // The desktop header starts with Demo. Mobile app rows must not
            // remain above the form when the side grids are present.
            XCTAssertEqual(demo.frame.minY, header.frame.minY, accuracy: 1)
            XCTAssertEqual(app.buttons["auth-login-tab"].frame.minY - demo.frame.minY, 52, accuracy: 1)
            // Retain the visible state even when a following pixel assertion fails.
            attachScreenshot(name)
            assertVisibleAppTiles(in: CGRect(x: viewport.frame.minX, y: viewport.frame.minY,
                width: header.frame.minX - viewport.frame.minX, height: viewport.frame.height), app: app)
            assertVisibleAppTiles(in: CGRect(x: header.frame.maxX, y: viewport.frame.minY,
                width: viewport.frame.maxX - header.frame.maxX, height: viewport.frame.height), app: app)
        }
        XCTAssertTrue(app.staticTexts["login-heading"].exists)
        assertWideLayout("Wide login centered form and visible white app icons on both sides")
        app.buttons["auth-signup-tab"].tap()
        waitForSignupSelection(app)
        XCTAssertFalse(app.staticTexts["login-heading"].exists)
        XCTAssertTrue(app.buttons["auth-signup-tab"].isSelected)
        XCTAssertFalse(app.buttons["signup-submit"].isEnabled)
        assertWideLayout("Wide signup centered form and visible white app icons on both sides")
        app.buttons["auth-demo-back"].tap()
        XCTAssertEqual(app.staticTexts["fixture-auth-destination"].label, "demo")
        tap(app.buttons["fixture-auth-return"], in: app)
        app.buttons["auth-login-tab"].tap()
        XCTAssertTrue(app.staticTexts["login-heading"].waitForExistence(timeout: 5))
    }

    // contract-test: supporting surface=gui.apple assertions=auth.surface.first-party-boundary
    func testSignupBenefitsStayInVerticalOrderAndDisclaimerLinksRemainActions() {
        var app = launch("signup", "basics")
        let benefits = (0..<4).map { app.staticTexts["signup-advantage-\($0)"] }
        for benefit in benefits {
            XCTAssertTrue(benefit.waitForExistence(timeout: 5))
            XCTAssertFalse(benefit.frame.isEmpty)
        }
        for index in 1..<benefits.count {
            XCTAssertGreaterThan(benefits[index].frame.minY, benefits[index - 1].frame.maxY)
            XCTAssertEqual(benefits[index].frame.minX, benefits[0].frame.minX, accuracy: 2)
        }
        XCTAssertFalse(app.buttons["signup-submit"].isEnabled)
        attachScreenshot("Signup benefits and consent layout")
        app.terminate()

        app = launch("signup", "alpha-disclaimer")
        for (identifier, destination) in [
            ("signup-alpha-github-link", "https://github.com/glowingkitty/OpenMates"),
            ("signup-alpha-instagram-link", "https://instagram.com/openmates_official")
        ] {
            tap(app.buttons[identifier], in: app)
            XCTAssertEqual(app.staticTexts["fixture-auth-destination"].label, destination)
            tap(app.buttons["fixture-auth-return"], in: app)
            XCTAssertFalse(app.textFields["signup-email"].exists)
        }
        tap(app.buttons["signup-alpha-continue"], in: app)
        XCTAssertTrue(app.textFields["signup-email"].waitForExistence(timeout: 5))
        XCTAssertEqual(app.switches["signup-terms"].value as? String, "Off")
        XCTAssertEqual(app.switches["signup-privacy"].value as? String, "Off")
    }

    // contract-test: supporting surface=gui.apple assertions=auth.surface.first-party-boundary
    func testSignupConsentLinksDoNotGrantConsentAndAcceptedFormReplacesInputs() {
        let app = launch("signup", "basics")
        for id in ["signup-stay", "signup-newsletter", "signup-terms", "signup-privacy"] {
            XCTAssertTrue(app.switches[id].waitForExistence(timeout: 5))
            XCTAssertEqual(app.switches[id].value as? String, "Off", id)
        }
        fillSignup(app)
        let submit = app.buttons["signup-submit"]
        XCTAssertFalse(submit.isEnabled)
        tap(app.buttons["signup-terms-link"], in: app)
        XCTAssertEqual(app.staticTexts["fixture-auth-destination"].label, "https://openmates.org/legal/terms")
        app.buttons["fixture-auth-return"].tap()
        XCTAssertEqual(app.switches["signup-terms"].value as? String, "Off")
        XCTAssertEqual(app.textFields["signup-email"].value as? String, "fixture@example.test")
        tap(app.switches["signup-terms"], in: app)
        XCTAssertFalse(submit.isEnabled)
        tap(app.switches["signup-privacy"], in: app)
        XCTAssertTrue(submit.isEnabled)
        XCTAssertEqual(app.switches["signup-newsletter"].value as? String, "Off")
        tap(submit, in: app)
        XCTAssertTrue(app.staticTexts["signup-code-requested"].waitForExistence(timeout: 5))
        XCTAssertEqual(app.staticTexts["signup-requested-email"].label, "fixture@example.test")
        XCTAssertTrue(app.staticTexts["fixture-signup-boundary"].exists)
        XCTAssertFalse(app.textFields["signup-email"].exists)
    }

    // contract-test: supporting surface=gui.apple assertions=auth.surface.first-party-boundary
    func testSignupRejectedAndSuspendedRequestsPreserveCorrectFormState() {
        var app = launch("signup", "error")
        fillSignup(app)
        acceptSignupConsents(app)
        tap(app.buttons["signup-submit"], in: app)
        XCTAssertTrue(app.staticTexts["auth-form-error"].waitForExistence(timeout: 5))
        XCTAssertFalse(app.staticTexts["signup-code-requested"].exists)
        XCTAssertEqual(app.textFields["signup-email"].value as? String, "fixture@example.test")
        XCTAssertTrue(app.buttons["signup-submit"].isEnabled)
        app.terminate()

        app = launch("signup", "loading")
        fillSignup(app)
        acceptSignupConsents(app)
        tap(app.buttons["signup-submit"], in: app)
        XCTAssertTrue(app.buttons["fixture-complete-signup-request"].waitForExistence(timeout: 5))
        XCTAssertFalse(app.buttons["signup-submit"].isEnabled)
        XCTAssertFalse(app.textFields["signup-email"].isEnabled)
        XCTAssertFalse(app.staticTexts["signup-code-requested"].exists)
        tap(app.buttons["fixture-complete-signup-request"], in: app)
        XCTAssertTrue(app.staticTexts["signup-code-requested"].waitForExistence(timeout: 5))
    }

    // contract-test: supporting surface=gui.apple assertions=auth.surface.first-party-boundary
    func testUnavailableSignupExplainsBoundaryAndFreshLaunchClearsFixtureState() {
        var app = launch("signup", "unavailable")
        fillSignup(app)
        acceptSignupConsents(app)
        XCTAssertTrue(app.staticTexts["signup-unavailable"].exists)
        XCTAssertFalse(app.buttons["signup-submit"].isEnabled)
        XCTAssertFalse(app.staticTexts["auth-form-error"].exists)
        app.terminate()
        app = launch("signup", "basics")
        XCTAssertEqual(app.textFields["signup-email"].value as? String, "Enter E-Mail address")
        XCTAssertEqual(app.switches["signup-terms"].value as? String, "Off")
        XCTAssertFalse(app.buttons["signup-submit"].isEnabled)
    }

    // contract-test: supporting surface=gui.apple assertions=auth.login.method-convergence,auth.surface.first-party-boundary
    func testLookupKeyboardSubmitAndAlternativeReturnUseRealFormTransitions() {
        let app = launch("login", "email")
        let email = app.textFields["email-input"]
        XCTAssertTrue(email.waitForExistence(timeout: 5))
        email.tap()
        email.typeText("invalid")
        XCTAssertFalse(app.buttons["continue-button"].isEnabled)
        XCTAssertTrue(app.staticTexts["lookup-error"].exists)
        tap(app.buttons["login-passkey-option"], in: app)
        XCTAssertEqual(app.staticTexts["fixture-auth-destination"].label, "passkey")
        app.buttons["fixture-auth-return"].tap()
        XCTAssertEqual(email.value as? String, "invalid")
        email.tap()
        email.typeText("@example.test")
        tap(app.buttons["stay-logged-in-toggle"], in: app)
        XCTAssertEqual(app.buttons["stay-logged-in-toggle"].value as? String, "On")
        email.tap()
        email.typeText("\n")
        XCTAssertTrue(app.secureTextFields["password-input"].waitForExistence(timeout: 5))
        XCTAssertFalse(app.textFields["email-input"].exists)
        tap(app.buttons["login-another-account"], in: app)
        XCTAssertTrue(email.waitForExistence(timeout: 5))
        XCTAssertFalse(app.buttons["continue-button"].isEnabled)
        XCTAssertEqual(app.buttons["stay-logged-in-toggle"].value as? String, "On")
    }

    // contract-test: supporting surface=gui.apple assertions=auth.login.method-convergence
    func testPasswordKeyboardSubmitRevealsOTPAndRejectedCodeCannotComplete() {
        let app = launch("login", "password")
        let password = app.secureTextFields["password-input"]
        XCTAssertTrue(password.waitForExistence(timeout: 5))
        let passwordField = app.descendants(matching: .any)["password-login-field"]
        XCTAssertTrue(passwordField.waitForExistence(timeout: 5))
        XCTAssertEqual(passwordField.frame.height, 48, accuracy: 1)
        XCTAssertLessThanOrEqual(passwordField.frame.width, 351)
        XCTAssertGreaterThan(passwordField.frame.width, 250)
        XCTAssertGreaterThanOrEqual(password.frame.minX - passwordField.frame.minX, 44)
        let submit = app.buttons["login-button"]
        XCTAssertEqual(submit.frame.height, 50, accuracy: 1)
        XCTAssertEqual(submit.frame.width, passwordField.frame.width, accuracy: 1)
        XCTAssertGreaterThanOrEqual(app.buttons["login-another-account"].frame.height, 41)
        XCTAssertFalse(app.textFields["tfa-code-input"].exists)
        password.tap()
        password.typeText("fixture-only-password\n")
        let otp = app.textFields["tfa-code-input"]
        XCTAssertTrue(otp.waitForExistence(timeout: 5))
        let codeField = app.descendants(matching: .any)["password-login-code-field"]
        XCTAssertTrue(codeField.waitForExistence(timeout: 5))
        XCTAssertEqual(codeField.frame.height, 48, accuracy: 1)
        XCTAssertEqual(codeField.frame.width, passwordField.frame.width, accuracy: 1)
        XCTAssertEqual(codeField.frame.minX, passwordField.frame.minX, accuracy: 1)
        XCTAssertFalse(app.buttons["login-button"].isEnabled)
        otp.tap()
        otp.typeText("000000")
        tap(app.buttons["login-button"], in: app)
        XCTAssertTrue(app.staticTexts["password-login-error"].waitForExistence(timeout: 5))
        XCTAssertFalse(app.staticTexts["fixture-login-complete"].exists)
        XCTAssertFalse(app.buttons["login-button"].isEnabled)
        attachScreenshot("Password login rejected OTP and focused input chrome")
        otp.tap()
        otp.typeText("123456")
        tap(app.buttons["login-button"], in: app)
        XCTAssertTrue(app.staticTexts["fixture-login-complete"].waitForExistence(timeout: 5))
        XCTAssertFalse(app.secureTextFields["password-input"].exists)
    }

    // contract-test: supporting surface=gui.apple assertions=auth.login.method-convergence
    func testOTPVariantStartsVisibleAndBackupModeFormatsTheSubmittedCode() {
        let app = launch("login", "otp")
        let password = app.secureTextFields["password-input"]
        let code = app.textFields["tfa-code-input"]
        XCTAssertTrue(code.waitForExistence(timeout: 5))
        password.tap()
        password.typeText("fixture-only-password")
        code.tap()
        code.typeText("123")
        XCTAssertFalse(app.buttons["login-button"].isEnabled)
        tap(app.buttons["login-code-mode"], in: app)
        XCTAssertFalse(app.buttons["login-button"].isEnabled)
        code.tap()
        code.typeText("abcdefgh1234")
        XCTAssertEqual(code.value as? String, "ABCD-EFGH-1234")
        XCTAssertTrue(app.buttons["login-button"].isEnabled)
        attachScreenshot("Password login backup code field and reachable submit")
        tap(app.buttons["login-button"], in: app)
        XCTAssertTrue(app.staticTexts["fixture-login-complete"].waitForExistence(timeout: 5))
    }

    // contract-test: supporting surface=gui.apple assertions=auth.login.method-convergence
    func testLookupAndPasswordErrorVariantsCannotProduceLocalCompletion() {
        var app = launch("login", "lookup-error")
        let email = app.textFields["email-input"]
        XCTAssertTrue(email.waitForExistence(timeout: 5))
        email.tap()
        email.typeText("fixture@example.test\n")
        XCTAssertTrue(app.staticTexts["lookup-error"].waitForExistence(timeout: 5))
        XCTAssertFalse(app.secureTextFields["password-input"].exists)
        XCTAssertTrue(app.buttons["continue-button"].isEnabled)
        app.terminate()
        app = launch("login", "password-error")
        let password = app.secureTextFields["password-input"]
        XCTAssertTrue(password.waitForExistence(timeout: 5))
        password.tap()
        password.typeText("fixture-only-password\n")
        XCTAssertTrue(app.textFields["tfa-code-input"].waitForExistence(timeout: 5))
        XCTAssertTrue(app.staticTexts["password-login-error"].exists)
        XCTAssertFalse(app.staticTexts["fixture-login-complete"].exists)
    }

    private func fillSignup(_ app: XCUIApplication) {
        let email = app.textFields["signup-email"]
        XCTAssertTrue(email.waitForExistence(timeout: 5))
        email.tap()
        email.typeText("fixture@example.test\n")
        XCTAssertEqual(app.textFields["signup-username"].value as? String, "fixture")
    }
    private func acceptSignupConsents(_ app: XCUIApplication) {
        tap(app.switches["signup-terms"], in: app)
        tap(app.switches["signup-privacy"], in: app)
    }
    private func tap(_ element: XCUIElement, in app: XCUIApplication) {
        XCTAssertTrue(element.waitForExistence(timeout: 5))
        for _ in 0..<6 {
            if element.isHittable { break }
            let scroll = app.scrollViews.firstMatch
            if element.frame.minY < app.windows.firstMatch.frame.midY { scroll.swipeDown() }
            else { scroll.swipeUp() }
        }
        XCTAssertTrue(element.isHittable)
        element.tap()
    }
    private func launch(_ component: String, _ variant: String, landscape: Bool = false) -> XCUIApplication {
        XCUIDevice.shared.orientation = landscape ? .landscapeLeft : .portrait
        let app = XCUIApplication()
        app.launchArguments = ["--dev-preview", component, "--dev-preview-variant", variant,
            "--dev-preview-theme", "light", "-AppleLanguages", "(en)", "-AppleLocale", "en_US"]
        app.launch()
        Self.waitForWindowOrientation(landscape: landscape, app: app)
        return app
    }
    private static func waitForWindowOrientation(landscape: Bool, app: XCUIApplication) {
        let expected = NSPredicate { _, _ in
            let frame = app.windows.firstMatch.frame
            return frame.width > 0 && frame.height > 0 && (frame.width > frame.height) == landscape
        }
        XCTAssertEqual(XCTWaiter.wait(for: [XCTNSPredicateExpectation(predicate: expected, object: nil)],
                                     timeout: 5), .completed,
                       "Wait for the app window to settle into the requested orientation")
    }
    private func waitForSignupSelection(_ app: XCUIApplication, onFailure: () -> Void = {}) {
        let transitioned = NSPredicate { _, _ in
            app.buttons["auth-signup-tab"].isSelected &&
            !app.buttons["auth-login-tab"].isSelected &&
            app.staticTexts["signup-advantage-0"].exists &&
            !app.staticTexts["login-heading"].exists
        }
        let result = XCTWaiter.wait(for: [XCTNSPredicateExpectation(predicate: transitioned, object: nil)], timeout: 5)
        if result != .completed { onFailure() }
        XCTAssertEqual(result, .completed,
                       "Selecting signup must update its tab and replace the login form with signup benefits")
    }
    private func assertVisibleAppTiles(in region: CGRect, app: XCUIApplication,
                                       file: StaticString = #filePath, line: UInt = #line) {
        // Accepted treatment: app gradients at0.2 over light grey20, while
        // glyphs remain fully white. Measure actual blended pixels and reject
        // opaque backgrounds or a global opacity wash that also fades glyphs.
        let window = app.windows.firstMatch.frame
        // Use the same full-screen source as our retained visual evidence.
        // app.screenshot() is an element capture and may crop in raw device
        // coordinates while its AX window frames already use landscape axes.
        let screenshot = XCUIScreen.main.screenshot()
        let evidence = XCTAttachment(screenshot: screenshot)
        evidence.name = "App tile oracle source"
        evidence.lifetime = .keepAlways
        add(evidence)
        guard let source = normalizedScreenshot(screenshot.image, window: window,
                                                file: file, line: line) else { return }
        let scale = CGFloat(source.width) / window.width
        let visible = region.intersection(window)
        guard !visible.isEmpty, let crop = source.cropping(to: CGRect(
            x: (visible.minX - window.minX) * scale, y: (visible.minY - window.minY) * scale,
            width: visible.width * scale, height: visible.height * scale)) else {
            XCTFail("Expected visible app-grid region", file: file, line: line); return
        }
        let raw = screenshot.image.cgImage
        let geometry = XCTAttachment(string:
            "window=\(window);region=\(region);visible=\(visible);" +
            "imageSize=\(screenshot.image.size);imageOrientation=\(screenshot.image.imageOrientation.rawValue);" +
            "rawPixels=\(raw?.width ?? 0)x\(raw?.height ?? 0);" +
            "normalizedPixels=\(source.width)x\(source.height);scale=\(scale);cropPixels=\(crop.width)x\(crop.height)")
        geometry.name = "App tile oracle geometry"
        geometry.lifetime = .keepAlways
        add(geometry)
        let cropEvidence = XCTAttachment(image: UIImage(cgImage: crop))
        cropEvidence.name = "App tile oracle measured crop"
        cropEvidence.lifetime = .keepAlways
        add(cropEvidence)
        var pixels = [UInt8](repeating: 0, count: crop.width * crop.height * 4)
        let rendered = pixels.withUnsafeMutableBytes { bytes -> Bool in
            guard let context = CGContext(data: bytes.baseAddress, width: crop.width, height: crop.height,
                bitsPerComponent: 8, bytesPerRow: crop.width * 4, space: CGColorSpaceCreateDeviceRGB(),
                bitmapInfo: CGImageAlphaInfo.premultipliedLast.rawValue | CGBitmapInfo.byteOrder32Big.rawValue) else { return false }
            context.draw(crop, in: CGRect(x: 0, y: 0, width: CGFloat(crop.width), height: CGFloat(crop.height)))
            return true
        }
        XCTAssertTrue(rendered, file: file, line: line)
        // Web/generated tokens: grey20 light=0.953 (~243/255). These six
        // palettes cover both side grids and the mobile rows without locating
        // individual tiles: web, nutrition, language, finance, code and mail.
        let palettes: [(Int, Int)] = [(0xDE1E66, 0xFF763B), (0xFD8450, 0xF42C2D),
            (0x4989F2, 0x2F44BF), (0x0A6E04, 0x2CB81E),
            (0x155D91, 0x42ABF4), (0xA82E1C, 0xEF6A58)]
        let expectedBlends: [[Int]] = palettes.flatMap { start, end in
            (0...8).map { step in
                let fraction = Double(step) / 8
                return [16, 8, 0].map { shift in
                    let first = Double((start >> shift) & 255)
                    let last = Double((end >> shift) & 255)
                    let gradient = first + (last - first) * fraction
                    return Int((243 * 0.8 + gradient * 0.2).rounded())
                }
            }
        }
        var blended = 0
        var opaqueColored = 0
        var white = 0
        for offset in stride(from: 0, to: pixels.count, by: 4) {
            let red = Int(pixels[offset]), green = Int(pixels[offset + 1]), blue = Int(pixels[offset + 2])
            let range = max(red, max(green, blue)) - min(red, min(green, blue))
            if range >= 12 && min(red, min(green, blue)) >= 190 && expectedBlends.contains(where: {
                abs(red - $0[0]) <= 4 && abs(green - $0[1]) <= 4 && abs(blue - $0[2]) <= 4
            }) { blended += 1 }
            // At0.2, an RGB gradient over a neutral background has range<=51.
            //75 leaves room for rasterization/color conversion but rejects
            // the former opaque app backgrounds.
            if range >= 75 { opaqueColored += 1 }
            if min(red, min(green, blue)) >= 250 { white += 1 }
        }
        XCTAssertGreaterThan(CGFloat(blended) / (scale * scale), 60,
            "App backgrounds must match their0.2 gradient blend over grey20", file: file, line: line)
        XCTAssertLessThan(CGFloat(opaqueColored) / (scale * scale), 1,
            "App backgrounds must remain translucent", file: file, line: line)
        XCTAssertGreaterThan(CGFloat(white) / (scale * scale), 8,
            "App glyphs must remain fully white despite translucent backgrounds", file: file, line: line)
    }
    private func normalizedScreenshot(_ image: UIImage, window: CGRect,
                                      file: StaticString, line: UInt) -> CGImage? {
        // AX frames follow the interface orientation. Screenshot raw pixels can
        // remain in the sensor's portrait canvas (UI226:1206x2622), with either
        // UIImage orientation metadata or rotated content inside that canvas.
        func drawUpright(_ image: UIImage) -> CGImage? {
            guard let raw = image.cgImage else { return nil }
            let swapsAxes: Bool
            switch image.imageOrientation {
            case .left, .right, .leftMirrored, .rightMirrored: swapsAxes = true
            default: swapsAxes = false
            }
            let size = CGSize(width: CGFloat(swapsAxes ? raw.height : raw.width),
                              height: CGFloat(swapsAxes ? raw.width : raw.height))
            let format = UIGraphicsImageRendererFormat()
            format.scale = 1
            return UIGraphicsImageRenderer(size: size, format: format).image { _ in
                image.draw(in: CGRect(origin: .zero, size: size))
            }.cgImage
        }
        guard window.width > 0, window.height > 0, var source = drawUpright(image) else {
            XCTFail("Expected rendered app screenshot and window", file: file, line: line); return nil
        }
        let expectedAspect = window.width / window.height
        var aspect = CGFloat(source.width) / CGFloat(source.height)
        if abs(aspect - expectedAspect) > 0.01 && abs(1 / aspect - expectedAspect) <= 0.01 {
            let rotation: UIImage.Orientation
            switch XCUIDevice.shared.orientation {
            case .landscapeLeft: rotation = .left
            case .landscapeRight: rotation = .right
            default:
                XCTFail("Screenshot axes disagree with the settled device orientation", file: file, line: line)
                return nil
            }
            guard let rotated = drawUpright(UIImage(cgImage: source, scale: 1, orientation: rotation)) else {
                XCTFail("Expected screenshot rotation to succeed", file: file, line: line); return nil
            }
            source = rotated
            aspect = CGFloat(source.width) / CGFloat(source.height)
        }
        XCTAssertEqual(aspect, expectedAspect, accuracy: 0.01,
                       "Normalized screenshot must match AX window axes before cropping", file: file, line: line)
        guard abs(aspect - expectedAspect) <= 0.01 else { return nil }
        return source
    }
    private func attachScreenshot(_ name: String) {
        let attachment = XCTAttachment(screenshot: XCUIScreen.main.screenshot())
        attachment.name = name
        attachment.lifetime = .keepAlways
        add(attachment)
    }
}
