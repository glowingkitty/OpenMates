// Visual contract smoke coverage for the shared Apple message composer.
// Uses deterministic dev-preview surfaces to assert shared identifiers and the
// web 629pt max-width contract without credentials, network calls, private chat
// records, or system picker automation.
// Screenshots are attached as review artifacts; assertions stay deterministic.

import XCTest

@MainActor
final class ComposerVisualParityUITests: XCTestCase {
    private let maxComposerWidth: CGFloat = 629
    private let widthTolerance: CGFloat = 8
    private let welcomeComposerButtonIds = [
        "attach-files-button",
        "share-location-button",
        "sketch-button",
        "take-photo-button",
        "record-audio-button",
    ]

    override func setUpWithError() throws {
        continueAfterFailure = false
    }

    func testChatPreviewComposerUsesSharedIdentifiersAndWidthCap() throws {
        let app = XCUIApplication()
        app.launchArguments = ["--dev-preview", "chat-opening"]
        app.launchEnvironment["DEV_PREVIEW"] = "chat-opening"
        app.launch()

        XCTAssertTrue(app.staticTexts["Native Chat Opening Preview"].waitForExistence(timeout: 12))

        let editor = waitForMessageEditor(in: app)

        XCTAssertLessThanOrEqual(editor.frame.width, maxComposerWidth + widthTolerance)

        editor.tap()
        XCTAssertFalse(app.tables.firstMatch.exists, "Product composer UI must not render default List/table chrome")

        attachScreenshot(name: "Shared composer chat preview width cap")
    }

    func testFocusedWelcomeComposerScreenshotShowsActionButtons() throws {
        let app = launchFocusedWelcomeComposer()

        XCTAssertTrue(app.buttons["message-input-fullscreen-button"].waitForExistence(timeout: 5))
        let screenshot = XCUIScreen.main.screenshot()
        for identifier in welcomeComposerButtonIds {
            assertButtonIsVisibleInScreenshot(app.buttons[identifier], identifier: identifier, in: app, screenshot: screenshot)
        }
        attachScreenshot(screenshot, name: "Focused welcome composer action buttons visible")
    }

    func testFocusedWelcomeComposerActionButtonsAreNotNoOpsWhenSignedOut() throws {
        assertSignedOutWelcomeActionShowsSignupCTA("attach-files-button")
        assertSignedOutWelcomeActionShowsSignupCTA("sketch-button")
        assertSignedOutWelcomeActionShowsSignupCTA("take-photo-button")

        let locationApp = launchFocusedWelcomeComposer()
        let locationButton = locationApp.buttons["share-location-button"]
        XCTAssertTrue(locationButton.waitForExistence(timeout: 5), "Expected share-location-button to exist")
        XCTAssertTrue(locationButton.isHittable, "Expected share-location-button to be hittable")
        locationButton.tap()
        XCTAssertTrue(
            locationApp.descendants(matching: .any)
                .matching(NSPredicate(format: "identifier == %@", "location-overlay"))
                .firstMatch
                .waitForExistence(timeout: 5),
            "Expected location action to open the location composer overlay"
        )
    }

    func testFocusedWelcomeLocationSelectionInsertsMapsEmbedPreview() throws {
        let app = launchFocusedWelcomeComposer(
            extraArguments: ["--ui-test-location-preselected"],
            environment: ["UI_TEST_LOCATION_PRESELECTED": "1"]
        )
        let locationButton = app.buttons["share-location-button"]
        XCTAssertTrue(locationButton.waitForExistence(timeout: 5))
        locationButton.tap()

        XCTAssertTrue(app.buttons["send-button"].waitForExistence(timeout: 5))
        let editor = waitForMessageEditor(in: app)
        XCTAssertTrue(
            element(in: app, identifier: "native-composer-preview-maps-finished").waitForExistence(timeout: 5),
            "Expected selected location to insert a maps embed preview; value=\(String(describing: editor.value))"
        )
        XCTAssertFalse(
            (editor.value as? String)?.localizedCaseInsensitiveContains("Selected location (") == true,
            "Location selection must not append plain coordinate text"
        )
    }

    func testSeededImageAndAudioPreviewsStayLeftAlignedAcrossRotation() throws {
        XCUIDevice.shared.orientation = .portrait
        defer { XCUIDevice.shared.orientation = .portrait }

        let app = launchFocusedWelcomeComposer(
            extraArguments: ["--ui-test-welcome-seed-pending-content"]
        )
        let field = element(in: app, identifier: "message-field")
        let image = element(in: app, identifier: "native-composer-image-content")
        let audio = element(in: app, identifier: "native-composer-audio-content")
        let imageCard = element(in: app, identifier: "native-composer-preview-image-finished")
        let audioCard = element(in: app, identifier: "native-composer-preview-recording-finished")

        XCTAssertTrue(image.waitForExistence(timeout: 5), "Expected image-specific composer preview content")
        XCTAssertTrue(audio.waitForExistence(timeout: 5), "Expected audio-specific composer preview content")
        XCTAssertTrue(imageCard.waitForExistence(timeout: 5))
        XCTAssertTrue(audioCard.waitForExistence(timeout: 5))
        assertEmbed(imageCard, isLeftAlignedIn: field)
        assertEmbed(audioCard, isLeftAlignedIn: field)

        XCUIDevice.shared.orientation = .landscapeLeft
        XCTAssertTrue(image.waitForExistence(timeout: 5))
        XCTAssertTrue(audio.waitForExistence(timeout: 5))
        assertEmbed(imageCard, isLeftAlignedIn: field)
        assertEmbed(audioCard, isLeftAlignedIn: field)
    }

    func testWelcomeComposerExpandsAndCollapsesAcrossRotation() throws {
        XCUIDevice.shared.orientation = .portrait
        defer { XCUIDevice.shared.orientation = .portrait }

        let app = launchFocusedWelcomeComposer(
            extraArguments: ["--ui-test-welcome-seed-pending-content"]
        )
        let field = element(in: app, identifier: "message-field")
        let button = app.buttons["message-input-fullscreen-button"]
        XCTAssertTrue(field.waitForExistence(timeout: 5))
        XCTAssertTrue(button.waitForExistence(timeout: 5))
        attachScreenshot(name: "Welcome composer fullscreen button hit testing")
        XCTAssertTrue(
            button.isHittable,
            "Fullscreen button must be hittable. button=\(button.debugDescription) field=\(field.debugDescription) UI=\(app.debugDescription)"
        )

        let collapsedPortraitHeight = field.frame.height
        let expandLabel = button.label
        button.tap()

        XCTAssertNotEqual(button.label, expandLabel)
        XCTAssertTrue(waitForHeight(field, atLeast: collapsedPortraitHeight + 80))

        button.tap()
        XCTAssertEqual(button.label, expandLabel)
        XCTAssertLessThanOrEqual(field.frame.height, collapsedPortraitHeight + 8)

        button.tap()
        XCUIDevice.shared.orientation = .landscapeLeft
        XCTAssertTrue(button.waitForExistence(timeout: 5))
        XCTAssertTrue(button.isHittable)
        let window = app.windows.firstMatch.frame
        XCTAssertGreaterThanOrEqual(field.frame.minY, window.minY)
        XCTAssertLessThanOrEqual(field.frame.maxY, window.maxY)
        let expandedLandscapeHeight = field.frame.height

        button.tap()
        XCTAssertEqual(button.label, expandLabel)
        XCTAssertLessThan(field.frame.height, expandedLandscapeHeight - 80)
    }

    func testSketchToolExposesWebControlsInLandscape() throws {
        let app = launchFocusedWelcomeComposer(
            extraArguments: ["--ui-test-welcome-sketch-enabled"]
        )
        defer { XCUIDevice.shared.orientation = .portrait }
        XCUIDevice.shared.orientation = .landscapeLeft
        let sketchButton = app.buttons["sketch-button"]
        XCTAssertTrue(sketchButton.waitForExistence(timeout: 5))
        attachScreenshot(name: "Landscape composer before opening sketch")
        XCTAssertTrue(
            sketchButton.isHittable,
            "Sketch button must remain hittable after rotation. button=\(sketchButton.debugDescription) UI=\(app.debugDescription)"
        )
        sketchButton.tap()

        let canvas = element(in: app, identifier: "sketch-canvas")
        attachScreenshot(name: "Landscape sketch overlay after action")
        XCTAssertTrue(
            canvas.waitForExistence(timeout: 5),
            "Sketch canvas must render after the action. UI=\(app.debugDescription)"
        )
        for identifier in [
            "sketch-eraser-button",
            "sketch-undo-button",
            "sketch-clear-button",
            "sketch-zoom-in-button",
            "sketch-fullscreen-button",
        ] {
            let control = app.buttons[identifier]
            XCTAssertTrue(control.waitForExistence(timeout: 2), "Missing web-parity drawing control: \(identifier)")
            XCTAssertTrue(control.isHittable, "Drawing control is clipped: \(identifier)")
        }
    }

    func testQuickCaptureComposerUsesSameSharedIdentifierContract() throws {
        let app = XCUIApplication()
        app.launchArguments = [
            "--dev-preview",
            "quick-capture",
            "--ui-test-seed-quick-capture-recent-chat"
        ]
        app.launchEnvironment["DEV_PREVIEW"] = "quick-capture"
        app.launch()

        XCTAssertTrue(element(in: app, identifier: "quick-capture-tab-chats").waitForExistence(timeout: 12))
        XCTAssertTrue(element(in: app, identifier: "quick-capture-composer").exists)
        XCTAssertTrue(element(in: app, identifier: "message-field").exists)
        XCTAssertTrue(element(in: app, identifier: "quick-capture-record-audio-button").exists)
        XCTAssertTrue(element(in: app, identifier: "quick-capture-send-button").exists)
        XCTAssertTrue(element(in: app, identifier: "quick-capture-recent-chats").exists)
        XCTAssertTrue(element(in: app, identifier: "quick-capture-status-list").exists)

        attachScreenshot(name: "Shared composer quick capture contract")
    }

    private func element(in app: XCUIApplication, identifier: String) -> XCUIElement {
        app.descendants(matching: .any)
            .matching(NSPredicate(format: "identifier == %@", identifier))
            .firstMatch
    }

    private func textContaining(_ text: String, in app: XCUIApplication) -> XCUIElement {
        app.staticTexts
            .matching(NSPredicate(format: "label CONTAINS[c] %@", text))
            .firstMatch
    }

    private func waitForAbsence(_ element: XCUIElement, timeout: TimeInterval = 5) -> Bool {
        let predicate = NSPredicate(format: "exists == false")
        let expectation = XCTNSPredicateExpectation(predicate: predicate, object: element)
        return XCTWaiter.wait(for: [expectation], timeout: timeout) == .completed
    }

    private func waitForHeight(
        _ element: XCUIElement,
        atLeast minimumHeight: CGFloat,
        timeout: TimeInterval = 5
    ) -> Bool {
        let deadline = Date().addingTimeInterval(timeout)
        while Date() < deadline {
            if element.frame.height >= minimumHeight { return true }
            RunLoop.current.run(until: Date().addingTimeInterval(0.1))
        }
        return false
    }

    private func assertEmbed(
        _ embed: XCUIElement,
        isLeftAlignedIn field: XCUIElement,
        file: StaticString = #filePath,
        line: UInt = #line
    ) {
        XCTAssertGreaterThan(embed.frame.width, 100, file: file, line: line)
        XCTAssertGreaterThan(embed.frame.height, 100, file: file, line: line)
        XCTAssertEqual(embed.frame.minX, field.frame.minX + 10, accuracy: 12, file: file, line: line)
        XCTAssertTrue(field.frame.intersects(embed.frame), file: file, line: line)
    }

    private func waitForMessageEditor(in app: XCUIApplication) -> XCUIElement {
        let candidates = [
            app.descendants(matching: .any).matching(NSPredicate(format: "identifier == %@", "message-editor")).firstMatch,
        ]
        let deadline = Date().addingTimeInterval(10)
        while Date() < deadline {
            if let editor = candidates.first(where: { $0.exists }) {
                return editor
            }
            RunLoop.current.run(until: Date().addingTimeInterval(0.1))
        }
        XCTFail("Expected message editor to exist. Visible UI: \(app.debugDescription)")
        return candidates[0]
    }

    private func launchFocusedWelcomeComposer(
        extraArguments: [String] = [],
        environment: [String: String] = [:]
    ) -> XCUIApplication {
        let app = XCUIApplication()
        app.launchArguments = ["--ui-test-disable-auth-cache", "--ui-test-start-new-chat"] + extraArguments
        for (key, value) in environment {
            app.launchEnvironment[key] = value
        }
        app.launch()

        let skip = app.buttons["guest-interest-skip"]
        if skip.waitForExistence(timeout: 12) {
            skip.tap()
        }

        let editor = waitForMessageEditor(in: app)
        editor.tap()
        XCTAssertTrue(app.buttons["message-input-fullscreen-button"].waitForExistence(timeout: 5))
        return app
    }

    private func assertSignedOutWelcomeActionShowsSignupCTA(
        _ identifier: String,
        file: StaticString = #filePath,
        line: UInt = #line
    ) {
        let app = launchFocusedWelcomeComposer()
        let button = app.buttons[identifier]
        XCTAssertTrue(button.waitForExistence(timeout: 5), "Expected \(identifier) to exist", file: file, line: line)
        XCTAssertTrue(button.isHittable, "Expected \(identifier) to be hittable", file: file, line: line)
        XCTAssertFalse(app.buttons["send-button"].exists, "Signup CTA should not be visible before an action", file: file, line: line)

        button.tap()

        let sendButton = app.buttons["send-button"]
        if !sendButton.waitForExistence(timeout: 2) {
            button.tap()
        }
        XCTAssertTrue(
            sendButton.waitForExistence(timeout: 5),
            "Expected \(identifier) to surface the signup CTA instead of no-oping",
            file: file,
            line: line
        )
    }

    private func assertButtonIsVisibleInScreenshot(
        _ button: XCUIElement,
        identifier: String,
        in app: XCUIApplication,
        screenshot: XCUIScreenshot,
        file: StaticString = #filePath,
        line: UInt = #line
    ) {
        XCTAssertTrue(button.waitForExistence(timeout: 5), "Expected \(identifier) to exist", file: file, line: line)
        XCTAssertTrue(button.isHittable, "Expected \(identifier) to be hittable", file: file, line: line)

        let windowFrame = app.windows.firstMatch.frame
        let visibleFrame = button.frame.intersection(windowFrame)
        XCTAssertGreaterThan(visibleFrame.width, 18, "Expected \(identifier) visible width", file: file, line: line)
        XCTAssertGreaterThan(visibleFrame.height, 18, "Expected \(identifier) visible height", file: file, line: line)

        #if canImport(UIKit)
        let buttonScreenshot = button.screenshot()
        guard let image = UIImage(data: buttonScreenshot.pngRepresentation), let cgImage = image.cgImage else {
            XCTFail("Could not decode button screenshot while checking \(identifier)", file: file, line: line)
            return
        }

        var pixels = [UInt8](repeating: 0, count: cgImage.width * cgImage.height * 4)
        guard let context = CGContext(
            data: &pixels,
            width: cgImage.width,
            height: cgImage.height,
            bitsPerComponent: 8,
            bytesPerRow: cgImage.width * 4,
            space: CGColorSpaceCreateDeviceRGB(),
            bitmapInfo: CGImageAlphaInfo.premultipliedLast.rawValue
        ) else {
            XCTFail("Could not prepare button screenshot pixels while checking \(identifier)", file: file, line: line)
            return
        }

        context.translateBy(x: 0, y: CGFloat(cgImage.height))
        context.scaleBy(x: 1, y: -1)
        context.draw(cgImage, in: CGRect(x: 0, y: 0, width: cgImage.width, height: cgImage.height))

        let highlightedPixelRatio = highlightedPixelRatio(
            in: CGRect(x: 0, y: 0, width: cgImage.width, height: cgImage.height),
            pixels: pixels,
            imageWidth: cgImage.width,
            imageHeight: cgImage.height,
            scaleX: 1,
            scaleY: 1
        )
        XCTAssertGreaterThan(
            highlightedPixelRatio,
            0.02,
            "Expected \(identifier) screenshot region to contain visible icon pixels, ratio \(highlightedPixelRatio)",
            file: file,
            line: line
        )
        #endif
    }

    #if canImport(UIKit)
    private func highlightedPixelRatio(
        in rect: CGRect,
        pixels: [UInt8],
        imageWidth: Int,
        imageHeight: Int,
        scaleX: CGFloat,
        scaleY: CGFloat
    ) -> Double {
        let minX = max(0, Int((rect.minX * scaleX).rounded(.down)))
        let maxX = min(imageWidth - 1, Int((rect.maxX * scaleX).rounded(.up)))
        let minY = max(0, Int((rect.minY * scaleY).rounded(.down)))
        let maxY = min(imageHeight - 1, Int((rect.maxY * scaleY).rounded(.up)))
        var highlighted = 0
        var total = 0

        for y in minY...maxY {
            for x in minX...maxX {
                let offset = (y * imageWidth + x) * 4
                let red = Int(pixels[offset])
                let green = Int(pixels[offset + 1])
                let blue = Int(pixels[offset + 2])
                let maxChannel = max(red, green, blue)
                let minChannel = min(red, green, blue)
                if maxChannel > 110 && maxChannel - minChannel > 24 {
                    highlighted += 1
                }
                total += 1
            }
        }

        guard total > 0 else { return 0 }
        return Double(highlighted) / Double(total)
    }
    #endif

    private func attachScreenshot(name: String) {
        let attachment = XCTAttachment(screenshot: XCUIScreen.main.screenshot())
        attachment.name = name
        attachment.lifetime = .keepAlways
        add(attachment)
    }

    private func attachScreenshot(_ screenshot: XCUIScreenshot, name: String) {
        let attachment = XCTAttachment(screenshot: screenshot)
        attachment.name = name
        attachment.lifetime = .keepAlways
        add(attachment)
    }
}
