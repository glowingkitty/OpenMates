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
        "composer-attachment-toggle",
        "record-audio-button",
    ]

    override func setUpWithError() throws {
        continueAfterFailure = false
    }

    // contract-test: direct surface=gui.apple assertions=message-input.layout.responsive-parity
    func testChatPreviewComposerUsesSharedIdentifiersAndWidthCap() throws {
        XCUIDevice.shared.orientation = .portrait
        defer { XCUIDevice.shared.orientation = .portrait }

        let app = XCUIApplication()
        app.launchArguments = ["--dev-preview", "chat-opening"]
        app.launchEnvironment["DEV_PREVIEW"] = "chat-opening"
        app.launch()

        XCTAssertTrue(app.staticTexts["Native Chat Opening Preview"].waitForExistence(timeout: 12))

        let editor = waitForMessageEditor(in: app)

        XCTAssertLessThanOrEqual(editor.frame.width, maxComposerWidth + widthTolerance)

        editor.tap()
        let field = element(in: app, identifier: "message-field")
        let fullscreenButton = app.buttons["message-input-fullscreen-button"]
        XCTAssertTrue(field.waitForExistence(timeout: 5))
        XCTAssertTrue(
            fullscreenButton.waitForExistence(timeout: 5),
            "Expected the focused production composer to expose fullscreen. Visible UI: \(app.debugDescription)"
        )
        let collapsedPortraitHeight = field.frame.height

        fullscreenButton.tap()
        XCTAssertTrue(waitForHeight(field, atLeast: collapsedPortraitHeight + 80))

        XCUIDevice.shared.orientation = .landscapeLeft
        XCTAssertTrue(fullscreenButton.waitForExistence(timeout: 5))
        let window = app.windows.firstMatch.frame
        XCTAssertGreaterThanOrEqual(field.frame.minY, window.minY)
        XCTAssertLessThanOrEqual(field.frame.maxY, window.maxY)
        let expandedLandscapeHeight = field.frame.height

        fullscreenButton.tap()
        XCTAssertLessThan(field.frame.height, expandedLandscapeHeight - 80)
        XCTAssertFalse(app.tables.firstMatch.exists, "Product composer UI must not render default List/table chrome")

        attachScreenshot(name: "Shared composer chat preview width cap")
    }

    // contract-test: direct surface=gui.apple assertions=message-input.actions.visibility,message-input.layout.responsive-parity
    func testFocusedWelcomeComposerScreenshotShowsActionButtons() throws {
        let app = launchFocusedWelcomeComposer()

        XCTAssertTrue(app.buttons["message-input-fullscreen-button"].waitForExistence(timeout: 5))
        let screenshot = XCUIScreen.main.screenshot()
        for identifier in welcomeComposerButtonIds {
            assertButtonIsVisibleInScreenshot(app.buttons[identifier], identifier: identifier, in: app, screenshot: screenshot)
        }
        attachScreenshot(screenshot, name: "Focused welcome composer action buttons visible")

        app.buttons["composer-attachment-toggle"].tap()
        let menu = element(in: app, identifier: "composer-attachment-menu")
        XCTAssertTrue(menu.waitForExistence(timeout: 5))
        for identifier in ["composer-attachment-drawing", "composer-attachment-location", "composer-attachment-camera", "composer-attachment-files"] {
            let action = app.buttons[identifier]
            XCTAssertTrue(action.waitForExistence(timeout: 5), "Missing attachment menu action: \(identifier)")
            XCTAssertTrue(action.isHittable, "Attachment menu action is obscured: \(identifier)")
            assertButtonIsVisibleInScreenshot(
                action,
                identifier: identifier,
                in: app,
                screenshot: screenshot,
                leadingIconOnly: true
            )
        }
        attachScreenshot(name: "Focused welcome composer attachment menu open")

        let outsideMenu = app.windows.firstMatch.coordinate(withNormalizedOffset: CGVector(dx: 0.5, dy: 0.2))
        outsideMenu.tap()
        XCTAssertFalse(app.buttons["composer-attachment-drawing"].exists, "Outside tap should dismiss the attachment menu")
    }

    // contract-test: direct surface=gui.apple assertions=message-input.layout.responsive-parity
    func testCollapsedComposerGrowsThroughThreeLinesThenScrollsAboveActions() throws {
        let app = launchFocusedWelcomeComposer(
            extraArguments: ["--ui-test-welcome-seed-suggestions"]
        )
        let editor = waitForMessageEditor(in: app)
        let field = element(in: app, identifier: "message-field")
        let suggestions = element(in: app, identifier: "new-chat-suggestions")
        XCTAssertTrue(field.waitForExistence(timeout: 5))
        XCTAssertTrue(suggestions.waitForExistence(timeout: 5))
        let initialHeight = field.frame.height

        editor.typeText("First line")
        XCTAssertTrue(
            waitForSuggestions(suggestions, above: field),
            "Welcome suggestions must settle above the active composer"
        )
        let oneLineSuggestionsMaxY = suggestions.frame.maxY
        XCTAssertLessThanOrEqual(
            oneLineSuggestionsMaxY,
            field.frame.minY,
            "Welcome suggestions must remain above the active composer"
        )

        editor.typeText("\nSecond line\nThird line")
        XCTAssertTrue(
            waitForSuggestions(
                suggestions,
                above: field,
                maxYLessThan: oneLineSuggestionsMaxY - 20
            ),
            "Welcome suggestions must follow the growing composer upward"
        )

        let threeLineHeight = field.frame.height
        XCTAssertGreaterThan(
            threeLineHeight,
            initialHeight + 20,
            "The collapsed composer should expand upward to reveal three recent lines"
        )
        XCTAssertLessThan(
            suggestions.frame.maxY,
            oneLineSuggestionsMaxY - 20,
            "Welcome suggestions should move upward as the multiline composer grows"
        )
        XCTAssertLessThanOrEqual(
            suggestions.frame.maxY,
            field.frame.minY,
            "Three visible lines must not overlap the welcome suggestions"
        )
        let sendButton = app.buttons["send-button"]
        XCTAssertTrue(sendButton.waitForExistence(timeout: 5))
        XCTAssertLessThanOrEqual(
            editor.frame.maxY,
            sendButton.frame.minY + 2,
            "Multiline text must remain above the bottom action controls"
        )

        editor.typeText("\nFourth line\nFifth line")

        XCTAssertEqual(
            field.frame.height,
            threeLineHeight,
            accuracy: 4,
            "After three visible lines, the editor should scroll instead of growing over the controls"
        )
        XCTAssertLessThanOrEqual(
            suggestions.frame.maxY,
            field.frame.minY,
            "Scrollable fourth and fifth lines must keep suggestions above the composer"
        )
        XCTAssertTrue(
            (editor.value as? String)?.contains("Fifth line") == true,
            "The newest line should remain in the scrollable editor value"
        )
        attachScreenshot(name: "Collapsed composer three-line scrolling cap")
    }

    // contract-test: supporting surface=gui.apple assertions=message-input.embeds.gated-send
    func testFocusedWelcomeComposerActionButtonsAreNotNoOpsWhenSignedOut() throws {
        assertSignedOutWelcomeActionShowsSignupCTA("composer-attachment-files")
        assertSignedOutWelcomeActionShowsSignupCTA("composer-attachment-drawing")
        assertSignedOutWelcomeActionShowsSignupCTA("composer-attachment-camera")

        let locationApp = launchFocusedWelcomeComposer()
        locationApp.buttons["composer-attachment-toggle"].tap()
        let locationButton = locationApp.buttons["composer-attachment-location"]
        XCTAssertTrue(locationButton.waitForExistence(timeout: 5), "Expected location action to exist")
        XCTAssertTrue(locationButton.isHittable, "Expected location action to be hittable")
        locationButton.tap()
        XCTAssertTrue(
            locationApp.descendants(matching: .any)
                .matching(NSPredicate(format: "identifier == %@", "location-overlay"))
                .firstMatch
                .waitForExistence(timeout: 5),
            "Expected location action to open the location composer overlay"
        )
    }

    // contract-test: direct surface=gui.apple assertions=message-input.embeds.gated-send
    func testFocusedWelcomeLocationSelectionInsertsMapsEmbedPreview() throws {
        let app = launchFocusedWelcomeComposer(
            extraArguments: ["--ui-test-location-preselected"],
            environment: ["UI_TEST_LOCATION_PRESELECTED": "1"]
        )
        app.buttons["composer-attachment-toggle"].tap()
        let locationButton = app.buttons["composer-attachment-location"]
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

    // contract-test: direct surface=gui.apple assertions=message-input.layout.responsive-parity,message-input.embeds.gated-send
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

    // contract-test: direct surface=gui.apple assertions=message-input.layout.responsive-parity
    func testWelcomeComposerExpandsAndCollapsesAcrossRotation() throws {
        XCUIDevice.shared.orientation = .portrait
        defer { XCUIDevice.shared.orientation = .portrait }

        let app = launchFocusedWelcomeComposer()
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

    // contract-test: supporting surface=gui.apple assertions=message-input.embeds.gated-send,message-input.layout.responsive-parity
    func testSketchToolExposesWebControlsInLandscape() throws {
        let app = launchFocusedWelcomeComposer(
            extraArguments: ["--ui-test-welcome-sketch-enabled"]
        )
        defer { XCUIDevice.shared.orientation = .portrait }
        app.buttons["composer-attachment-toggle"].tap()
        let sketchButton = app.buttons["composer-attachment-drawing"]
        XCTAssertTrue(sketchButton.waitForExistence(timeout: 5))
        XCTAssertTrue(
            sketchButton.isHittable,
            "Sketch button must be hittable before opening the tool. button=\(sketchButton.debugDescription) UI=\(app.debugDescription)"
        )
        sketchButton.tap()

        let canvas = element(in: app, identifier: "sketch-canvas")
        XCTAssertTrue(canvas.waitForExistence(timeout: 5), "Sketch canvas must render after the action. UI=\(app.debugDescription)")
        XCUIDevice.shared.orientation = .landscapeLeft
        attachScreenshot(name: "Landscape sketch overlay after action")
        XCTAssertTrue(
            canvas.waitForExistence(timeout: 5),
            "Sketch canvas must survive rotation. UI=\(app.debugDescription)"
        )
        for identifier in ["sketch-eraser-button", "sketch-fullscreen-button"] {
            let control = app.buttons[identifier]
            XCTAssertTrue(control.waitForExistence(timeout: 2), "Missing web-parity drawing control: \(identifier)")
            XCTAssertTrue(control.isHittable, "Drawing control is clipped: \(identifier)")
        }

        let toolbar = app.scrollViews["sketch-toolbar-scroll"]
        let undo = app.buttons["sketch-undo-button"]
        let save = app.buttons["sketch-save-button"]
        XCTAssertTrue(toolbar.waitForExistence(timeout: 2))
        XCTAssertTrue(undo.waitForExistence(timeout: 2))
        XCTAssertTrue(save.waitForExistence(timeout: 2))
        XCTAssertFalse(undo.isEnabled, "Undo must stay disabled until the canvas has a stroke")
        XCTAssertFalse(save.isEnabled, "Save must stay disabled until the canvas has a stroke")

        let strokeStart = canvas.coordinate(withNormalizedOffset: CGVector(dx: 0.35, dy: 0.35))
        let strokeEnd = canvas.coordinate(withNormalizedOffset: CGVector(dx: 0.65, dy: 0.65))
        strokeStart.press(forDuration: 0.1, thenDragTo: strokeEnd)

        toolbar.swipeLeft()
        for identifier in ["sketch-zoom-in-button", "sketch-clear-button"] {
            let control = app.buttons[identifier]
            XCTAssertTrue(control.waitForExistence(timeout: 2), "Missing web-parity drawing control: \(identifier)")
            XCTAssertTrue(control.isHittable, "Drawing control remains unreachable after scrolling: \(identifier)")
        }
        XCTAssertTrue(waitForEnabled(undo), "Undo must become actionable after drawing")
        XCTAssertTrue(waitForEnabled(save), "Save must become actionable after drawing")
    }

    // contract-test: supporting surface=gui.apple assertions=message-input.layout.responsive-parity
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

    private func waitForSuggestions(
        _ suggestions: XCUIElement,
        above field: XCUIElement,
        maxYLessThan upperBound: CGFloat? = nil,
        timeout: TimeInterval = 5
    ) -> Bool {
        let deadline = Date().addingTimeInterval(timeout)
        while Date() < deadline {
            let suggestionsMaxY = suggestions.frame.maxY
            if suggestionsMaxY <= field.frame.minY,
               upperBound.map({ suggestionsMaxY < $0 }) ?? true {
                return true
            }
            RunLoop.current.run(until: Date().addingTimeInterval(0.1))
        }
        return false
    }

    private func waitForEnabled(_ element: XCUIElement, timeout: TimeInterval = 5) -> Bool {
        let predicate = NSPredicate(format: "isEnabled == true")
        let expectation = XCTNSPredicateExpectation(predicate: predicate, object: element)
        return XCTWaiter.wait(for: [expectation], timeout: timeout) == .completed
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
        app.buttons["composer-attachment-toggle"].tap()
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
        leadingIconOnly: Bool = false,
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

        let sampleWidth = leadingIconOnly ? min(cgImage.width, Int(54 * image.scale)) : cgImage.width
        let highlightedPixelRatio = highlightedPixelRatio(
            in: CGRect(x: 0, y: 0, width: sampleWidth, height: cgImage.height),
            pixels: pixels,
            imageWidth: cgImage.width,
            imageHeight: cgImage.height,
            scaleX: 1,
            scaleY: 1
        )
        XCTAssertGreaterThan(
            highlightedPixelRatio,
            leadingIconOnly ? 0.01 : 0.02,
            "Expected \(identifier) screenshot region to contain colored icon pixels, ratio \(highlightedPixelRatio)",
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
